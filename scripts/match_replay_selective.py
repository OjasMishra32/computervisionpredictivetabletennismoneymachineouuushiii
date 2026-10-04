#!/usr/bin/env python
"""Match replay, selective variant: the all-points replay of scripts/match_replay.py, trading a point only if
its EX-ANTE Markov fair-value swing is >= T.

    EXPLORATORY, added after seeing the all-points replay; not pre-registered; one day, 9 matches; backtest
    replay on real recorded book; assumed feed latency; paper only.

Why: the multi-month latency sweep (src/tier0.py) trades only historical jumps >= 4c, a set selected on the
realised move. The all-points replay (research/replay/RESULTS.md) calls every official point and loses at every
feed delay. A live trader who knows the score can compute, before a point is played, how far fair value moves
between "A wins it" and "B wins it" (src/markov.py, calibrated to the pre-point price as engine/fair/value.py
does). This script asks whether trading only the points whose ex-ante swing is large changes the replay.

Everything per point is scripts/match_replay.py, imported and unchanged (book replay, recorder-outage rule D1,
CV lead draws, timing, limit = reference ask + 1c, 100-share net cap per match, fill walk, fee, +30 s mark,
hold to result, beat-the-book test, statistics, match-clustered bootstrap). The only addition is a filter in
front of it: points whose ex-ante swing is < T are not called at all (they are removed before the replay, so
they neither trade nor use the net cap). The per-point random draws are the replay's own (drawn for all 994
points in the same order, then subset), so every T is a paired comparison with the all-points replay.

    .venv/bin/python scripts/match_replay_selective.py --cache /path/outside/repo.pkl
    .venv/bin/python scripts/match_replay_selective.py --doc-only      # redraw figure + doc from selective.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.fair.value import MatchFair, _serve_pair  # noqa: E402
from scripts import match_replay as MR  # noqa: E402  (also puts research/v2/latency on the path)
from src import tier0  # noqa: E402
from src.markov import TOUR_SERVE, Format, State  # noqa: E402

LABEL = ("EXPLORATORY, added after seeing the all-points replay; not pre-registered; one day, 9 matches; "
         "backtest replay on real recorded book; assumed feed latency; paper only")
OUT = ROOT / "results" / "replay" / "selective"
DOC = ROOT / "research" / "replay" / "SELECTIVE.md"

# ---- DECLARED BEFORE RUNNING (commit of this file precedes the first run; see SELECTIVE.md) -------------------
THRESHOLDS = (0.02, 0.04, 0.06)   # ex-ante swing threshold T (probability units); 0.04 = reference (src/tier0.py
#                                   JUMP_MIN, the sweep's >= 4c jump detector)
REF_T = 0.04
LAGS = (2.0, 3.0)                 # stamp lag, s; 2.0 primary
PRIMARY_LAG = 2.0
VS = (0.0, 0.5, 1.0)              # video feed delay, s
SEEDS = range(20)                 # seed 0 = the replay shown everywhere (CI); 0-19 = robustness
LEAD, NET = "model", "florida"    # the replay's headline lead model and network
# ex-ante swing: score + server belief before the point, (pa, pb) calibrated to the pre-point outcome-0 mid
TOUR, FMT = "wta", Format()       # women's best of 3, 7-point tiebreaks (engine/run.py uses the same)
PRE_AFTER_PREV_MS = 2_000         # pre-point price instant = previous point's official stamp + 2 s
FIRST_PRE_MS = 30_000             # first point of a match: its own stamp - 30 s
CAL_MAX_SPREAD = 0.10             # a mid is usable for calibration if the spread is <= 10c (engine StrategyConfig)
# no valid mid at the pre-point instant -> keep the last calibration of this match; none yet -> not eligible
MOVE_REF = 0.04                   # diagnostic only: realised move >= 4c (the sweep's jump size)
# --------------------------------------------------------------------------------------------------------------

TCOL = {0.02: "#2a78d6", 0.04: "#eb6834", 0.06: "#1baf7a"}     # dataviz reference palette, slots 1-3
TMARK = {0.02: "o", 0.04: "s", 0.06: "D"}


def tname(T) -> str:
    return "all" if T is None else f"T{round(T * 100):d}c"


# ============================================================================== ex-ante swing per point
SCORE = {0: "0", 1: "15", 2: "30", 3: "40"}


def score_str(s: State) -> tuple[str, str]:
    """Point score of a State in m1_points' notation (outcome-0 player first)."""
    if s.ga == 6 and s.gb == 6:
        return str(s.pa), str(s.pb)
    if s.pa >= 3 and s.pb >= 3:
        if s.pa == s.pb:
            return "40", "40"
        return ("A", "40") if s.pa > s.pb else ("40", "A")
    return SCORE[s.pa], SCORE[s.pb]


def valid_mid(s, t: int, outages: np.ndarray):
    """Outcome-0 mid from the book captured at t, or None. Token 0's own book, else 1 - token 1's mid."""
    if s is None or MR.in_outage(t, outages) or s[6] < t - MR.GAP_MS:
        return None
    for tok, (bb, ba) in ((0, (s[0], s[1])), (1, (s[2], s[3]))):
        if s[7 + tok] and np.isfinite(bb) and np.isfinite(ba) and 0 <= ba - bb <= CAL_MAX_SPREAD + 1e-9:
            m = (bb + ba) / 2
            m = m if tok == 0 else 1 - m
            if 0 < m < 1:
                return float(m)
    return None


def pre_instants(P: pd.DataFrame) -> np.ndarray:
    T = P.T_ms.to_numpy().astype(np.int64)
    prev = P.groupby("key", sort=False).T_ms.shift(1).to_numpy()
    return np.where(np.isfinite(prev), np.nan_to_num(prev).astype(np.int64) + PRE_AFTER_PREV_MS,
                    T - FIRST_PRE_MS).astype(np.int64)


def score_winner(model, s: State, p) -> bool | None:
    """Did the outcome-0 player win this point, according to the official score columns (the score after the
    point vs the score before it)? None if the two scores are not one point apart. m1_points' `ga`/`gb` are the
    outcome-0 / outcome-1 player's scores on all 9 matches (checked in run(): the implied winners agree with
    m1's `winner` column on >= 94 % of points in every match)."""
    ga, gb = str(p.ga), str(p.gb)
    if s.ga == 6 and s.gb == 6:                                   # tiebreak: integer counts, no 'G'
        try:
            a1, b1 = int(ga), int(gb)
        except ValueError:
            return None
        if (a1, b1) == (s.pa + 1, s.pb):
            return True
        if (a1, b1) == (s.pa, s.pb + 1):
            return False
        return None
    if "G" in (ga, gb):
        return ga == "G"
    for a in (True, False):
        nxt = model.step(s, a)
        if nxt is not None and (nxt.sa, nxt.sb, nxt.ga, nxt.gb) == (s.sa, s.sb, s.ga, s.gb) and score_str(nxt) == (ga, gb):
            return a
    return None


def exante_swings(P: pd.DataFrame, M: pd.DataFrame, snaps: dict, t_pre: np.ndarray, outages: np.ndarray) -> pd.DataFrame:
    """Walk every match point by point, as a live engine would: before point n, the score (official score
    columns) and the server belief from points 1..n-1, (pa, pb) refit to the outcome-0 mid at t_pre
    (MatchFair.recalibrate, engine/fair/value.py), swing = |v(A wins the point) - v(B wins it)|. Then advance
    by the point's winner as the official score shows it (deviation S1: m1's `winner` column disagrees with
    the score on 27 points; it is still the replay's call direction, unchanged)."""
    cidx = dict(zip(M.slug, M.cond))
    mu = TOUR_SERVE[TOUR]
    rows = []
    for key, g in P.groupby("key", sort=False):
        mf = MatchFair(*_serve_pair(mu, 0.0), FMT, State(), 0.5, TOUR)   # tour average until the first price
        cal = False
        prev = None
        for i in g.index:
            p = P.loc[i]
            s, p0 = mf.state, mf.p_server0
            row = {"i": i, "key": key, "slug": p.slug, "n": int(p.n), "t_pre_ms": int(t_pre[i]),
                   "m1_winner": float(p.winner)}
            if s is None:
                row.update(source="match already over", swing=np.nan, state="", score_ok=False)
                rows.append(row)
                continue
            mid = valid_mid(snaps[cidx[p.slug]].get(int(t_pre[i])), int(t_pre[i]), outages)
            if mid is not None:
                mf.recalibrate(mid)
                cal = True
                src = "pre-point mid"
            else:
                src = "carried from an earlier point" if cal else "no price yet"
            j = mf.jump()
            sa_, sb_ = score_str(s)
            # consistency of the rebuilt score with the official columns (set, game, previous point's score)
            ok = (int(p.set) == s.sa + s.sb + 1) and (int(p.game) == s.ga + s.gb + 1)
            if prev is not None and (int(prev.set), int(prev.game)) == (int(p.set), int(p.game)):
                ok = ok and (str(prev.ga), str(prev.gb)) == (sa_, sb_)
            w = score_winner(mf.model, s, p)
            row.update(source=src, mid_pre=mid, pa=mf.model.p[0], pb=mf.model.p[1], p_server0=p0,
                       state=f"sets {s.sa}-{s.sb} games {s.ga}-{s.gb} pts {sa_}-{sb_}", score_ok=ok,
                       v_now=j.v_now, v_if_a=j.v_if_a, v_if_b=j.v_if_b,
                       swing=abs(j.v_if_a - j.v_if_b) if cal else np.nan,
                       score_winner=np.nan if w is None else float(not w))
            rows.append(row)
            mf.apply_point(bool(p.winner == 0) if w is None else w)
            prev = p
    S = pd.DataFrame(rows).set_index("i").sort_index()
    return S


# ================================================================================================== run
def sub(d: dict, mask: np.ndarray) -> dict:
    return {k: v[mask] for k, v in d.items()}


def move_diag(D: pd.DataFrame, traded: pd.Series) -> dict:
    """Realised book move (m1_points.D: mid move in the point winner's direction over the reprice window) of
    traded vs not-traded replayable points."""
    out = {}
    for nm, g in (("traded", D[traded]), ("not_traded", D[~traded])):
        x = g.D_move.dropna().to_numpy() * 100
        out[nm] = {"points": int(len(g)), "with_move": int(len(x)),
                   "mean_c": float(x.mean()) if len(x) else np.nan,
                   "median_c": float(np.median(x)) if len(x) else np.nan,
                   "mean_abs_c": float(np.abs(x).mean()) if len(x) else np.nan,
                   "share_ge_4c": float((x >= MOVE_REF * 100 - 1e-9).mean()) if len(x) else np.nan}
    return out


def run(cache: str | None) -> dict:
    P, M = MR.load_points()
    print("parsing the recording ...")
    R = MR.parse_recording(M, cache)
    lat = np.array(R["recv_latency_ms"])
    l_recv = int(round(float(np.median(lat))))
    rows = {c: MR.effective_events(e, l_recv) for c, e in R["events"].items()}
    outages = np.array([(a - l_recv, b - l_recv) for a, b in R["outages_rt"]], dtype=np.int64).reshape(-1, 2)
    winners = {}
    for c, e in R["events"].items():
        w = [d for _, _, k, d in e if k == 3]
        winners[c] = w[-1] if w else None
    if any(w is None for w in winners.values()):
        raise SystemExit("no market_resolved for some market")

    cvd = tier0.cv_systems()["own120"]
    p_out = tier0.point_mix()["women"]["out"]
    plan = []
    for seed in SEEDS:
        dr = MR.draws(len(P), seed)
        lead = MR.leads_ms(dr, cvd, p_out)
        for lag in LAGS:
            for V in VS:
                plan.append((seed, lag, V, dr, lead, MR.cell_times(P, lead, lag, V, MR.NETS[NET])))
    t_pre = pre_instants(P)
    gap_min = float(P.gap_prev_s[P.groupby("key").cumcount() > 0].min())
    print(f"pre-point instant: previous stamp + {PRE_AFTER_PREV_MS / 1000:g} s; smallest gap between stamps "
          f"{gap_min:g} s, so it precedes the earliest assumed bounce by >= {gap_min - max(LAGS) - PRE_AFTER_PREV_MS / 1000:g} s")
    cond_of = P.slug.map(dict(zip(M.slug, M.cond))).to_numpy()
    need = {c: set() for c in M.cond}
    for c, t in zip(cond_of, t_pre):
        need[c].add(int(t))
    for *_, tm in plan:
        for k in ("t_ref", "exec", "mark"):
            for c, t in zip(cond_of, tm[k]):
                need[c].add(int(t))
    print(f"capturing books at {sum(len(v) for v in need.values()):,} instants ...")
    snaps = {c: MR.capture(rows[c], np.array(sorted(need[c]), dtype=np.int64)) for c in M.cond}

    print("ex-ante swings (calibrating to each pre-point mid) ...")
    S = exante_swings(P, M, snaps, t_pre, outages)
    n_bad = int((S.score_ok == False).sum())  # noqa: E712
    print(f"  score reconstruction disagrees with m1's set/game/score columns on {n_bad} of {S.score_ok.notna().sum()} points")
    print("  swing source:", S.source.value_counts().to_dict())
    # orientation and the m1 `winner` column against the official score
    agree = S[S.score_winner.notna()].assign(a=lambda x: x.score_winner == x.m1_winner).groupby("slug").a.mean()
    if (agree < 0.5).any():
        raise SystemExit(f"score columns look flipped against outcome 0 for {agree[agree < 0.5].index.tolist()}")
    bad_w = S[S.score_winner.notna() & (S.score_winner != S.m1_winner)].join(P[["D"]])
    wcheck = {"agreement_by_match": agree.to_dict(), "n_points_score_winner_unknown": int(S.score_winner.isna().sum()),
              "n_points_m1_winner_disagrees_with_score": int(len(bad_w)),
              "points": [{"slug": r.slug, "n": int(r.n), "m1_winner": r.m1_winner, "score_winner": r.score_winner,
                          "book_move_in_m1_winner_direction_c": None if not np.isfinite(r.D) else float(r.D * 100)}
                         for r in bad_w.itertuples()]}
    print(f"  m1 `winner` disagrees with the official score on {len(bad_w)} points "
          f"({int(bad_w.D.notna().sum())} with a recorded book; book move in m1's direction there: "
          f"{np.round(bad_w.D.dropna().to_numpy() * 100, 1).tolist()} c)")
    bad_keys = set(zip(bad_w.slug, bad_w.n))
    # call direction from the official score (diagnostic for the m1 `winner` issue; the replay keeps m1's)
    w_score = np.where(S.score_winner.notna(), S.score_winner, P.winner).astype(float)
    P_sd = P.assign(winner=w_score)
    # look-ahead margin measured on the recorded reprices (m1 t_book / t_book_first: receive clock -> server)
    own_rp = (P.t_book.to_numpy() - l_recv - t_pre) / 1000
    own_rp1 = (P.t_book_first.to_numpy() - l_recv - t_pre) / 1000
    prev_rp = P.groupby("key", sort=False).t_book.shift(1).to_numpy() - l_recv
    from_mid = (S.source == "pre-point mid").to_numpy()
    stale = from_mid & np.isfinite(prev_rp) & (prev_rp > t_pre)
    timing = {"own_reprice_minus_pre_instant_s_min": float(np.nanmin(own_rp)),
              "own_first_reprice_minus_pre_instant_s_min": float(np.nanmin(own_rp1)),
              "points_with_own_reprice": int(np.isfinite(own_rp).sum()),
              "calibrated_points_with_previous_reprice": int((from_mid & np.isfinite(prev_rp)).sum()),
              "calibrated_points_previous_reprice_after_pre_instant": int(stale.sum())}
    print(f"  look-ahead margin: the point's own reprice is >= {timing['own_reprice_minus_pre_instant_s_min']:g} s "
          f"after the pre-point instant; previous point's reprice after it on "
          f"{timing['calibrated_points_previous_reprice_after_pre_instant']} of "
          f"{timing['calibrated_points_with_previous_reprice']} calibrated points")
    swing = S.swing.to_numpy()
    elig = {None: np.ones(len(P), bool)}
    for T in THRESHOLDS:
        elig[T] = np.nan_to_num(swing, nan=-1.0) >= T - 1e-12

    ref = json.loads((ROOT / "results/replay/replay.json").read_text())
    res_cells, seed_rows, frames = {}, [], []
    for seed, lag, V, dr, lead, tm in plan:
        for T, mask in elig.items():
            Pm = P[mask].reset_index(drop=True)
            D = MR.simulate(Pm, M, snaps, sub(tm, mask), sub(dr, mask), lead[mask], winners, l_recv,
                            {"T": tname(T), "lag": lag, "V": V, "lead": LEAD, "net": NET, "seed": seed}, outages)
            D["D_move"] = P.D.to_numpy()[mask]
            D["swing"] = swing[mask]
            s = MR.stats(D, ci=(seed == 0))
            rep = D[D.status != "no book recorded"]
            if seed == 0:
                frames.append(D)
                nm = f"{tname(T)}|lag{lag:g}|V{V:g}"
                Fb = D[(D.shares > 1e-9) & pd.Series([(a, b) in bad_keys for a, b in zip(D.slug, D.n)], index=D.index)]
                res_cells[nm] = {"T": T, "lag": lag, "V": V, "all": s,
                                 "eligible_points": int(mask.sum()), "eligible_replayable": int(len(rep)),
                                 "fills_on_m1_winner_errors": {"fills": int(len(Fb)),
                                                               "pnl_mark_usd": float(Fb.pnl_mark.sum(skipna=True)),
                                                               "pnl_hold_usd": float(Fb.pnl_hold.sum())},
                                 "move_traded_vs_not": None,
                                 "by_match": {m: MR.stats(g, ci=False) for m, g in D.groupby("slug", sort=False)}}
                Dsd = MR.simulate(P_sd[mask].reset_index(drop=True), M, snaps, sub(tm, mask), sub(dr, mask),
                                  lead[mask], winners, l_recv, {"T": tname(T), "lag": lag, "V": V}, outages)
                ssd = MR.stats(Dsd, ci=False)
                res_cells[nm]["score_direction_diag"] = {k: ssd[k] for k in (
                    "fills", "fills_wrong", "pnl_mark_usd", "pnl_hold_usd", "per_share_mark_c", "per_share_hold_c")}
            seed_rows.append({"T": tname(T), "lag": lag, "V": V, "seed": seed, **{k: s[k] for k in (
                "calls", "orders", "fills", "fills_wrong", "calls_beat_book", "calls_with_reprice",
                "share_calls_beat_book", "shares", "pnl_hold_usd", "pnl_mark_usd", "per_share_hold_c",
                "per_share_mark_c")}})
    # realised move of traded vs not traded: over ALL replayable points (so the not-traded side includes the
    # points the filter removed), seed 0
    for f in frames:
        T, lag, V = f["T"].iloc[0], float(f["lag"].iloc[0]), float(f["V"].iloc[0])
        nm = f"{T}|lag{lag:g}|V{V:g}"
        allp = [g for g in frames if g["T"].iloc[0] == "all" and float(g["lag"].iloc[0]) == lag
                and float(g["V"].iloc[0]) == V][0]
        replayable = allp[allp.status != "no book recorded"][["slug", "n", "D_move"]]
        traded_keys = set(zip(f.slug[f.shares > 1e-9], f.n[f.shares > 1e-9]))
        tr = pd.Series([(a, b) in traded_keys for a, b in zip(replayable.slug, replayable.n)], index=replayable.index)
        res_cells[nm]["move_traded_vs_not"] = move_diag(replayable, tr)

    SR = pd.DataFrame(seed_rows)
    seeds = {}
    for (T, lag, V), g in SR.groupby(["T", "lag", "V"], sort=False):
        seeds[f"{T}|lag{lag:g}|V{V:g}"] = {
            **{k: {"mean": float(g[k].mean()), "sd": float(g[k].std(ddof=1)), "min": float(g[k].min()),
                   "max": float(g[k].max())} for k in g.columns if k not in ("T", "lag", "V", "seed")},
            "seeds_marked_positive": int((g.pnl_mark_usd > 0).sum()), "seeds_held_positive": int((g.pnl_hold_usd > 0).sum()),
            "n_seeds": int(len(g))}

    # ---- does the all-points cell reproduce scripts/match_replay.py's committed replay.json?
    repro = {}
    for lag in LAGS:
        for V in VS:
            a = res_cells[f"all|lag{lag:g}|V{V:g}"]["all"]
            b = ref["cells"][f"V{V:g}|lag{lag:g}|lead_{LEAD}|{NET}"]["all"]
            repro[f"lag{lag:g}|V{V:g}"] = {"fills": [a["fills"], b["fills"]],
                                            "pnl_mark_usd": [a["pnl_mark_usd"], b["pnl_mark_usd"]],
                                            "pnl_hold_usd": [a["pnl_hold_usd"], b["pnl_hold_usd"]],
                                            "identical": bool(a["fills"] == b["fills"] and abs(a["pnl_mark_usd"] - b["pnl_mark_usd"]) < 1e-6
                                                              and abs(a["pnl_hold_usd"] - b["pnl_hold_usd"]) < 1e-6)}
    print("all-points cells reproduce replay.json:", all(v["identical"] for v in repro.values()))

    # ---- swing diagnostics over replayable points (primary lag, V = 1, seed 0: replayability is cell-specific
    # only through the outage rule; use that cell's replayable set)
    head_all = [g for g in frames if g["T"].iloc[0] == "all" and float(g["lag"].iloc[0]) == PRIMARY_LAG
                and float(g["V"].iloc[0]) == 1.0][0]
    rp = head_all.status != "no book recorded"
    sw = swing[rp.to_numpy()]
    dm = P.D.to_numpy()[rp.to_numpy()]
    ok = np.isfinite(sw) & np.isfinite(dm)
    rs = pd.Series(sw[ok]).corr(pd.Series(np.abs(dm[ok])), method="spearman")
    rs_signed = pd.Series(sw[ok]).corr(pd.Series(dm[ok]), method="spearman")
    swd = {"replayable_points": int(rp.sum()), "with_swing": int(np.isfinite(sw).sum()),
           "swing_c_quantiles": {q: float(np.nanpercentile(sw, q) * 100) for q in (10, 25, 50, 75, 90)},
           "share_ge": {tname(T): float(np.mean(np.nan_to_num(sw, nan=-1) >= T - 1e-12)) for T in THRESHOLDS},
           "spearman_swing_vs_abs_realised_move": float(rs), "spearman_swing_vs_signed_realised_move": float(rs_signed),
           "n_for_correlation": int(ok.sum()),
           "by_threshold": {}}
    for T in THRESHOLDS:
        e = np.nan_to_num(sw, nan=-1) >= T - 1e-12
        big = np.nan_to_num(dm, nan=-1) >= MOVE_REF - 1e-9
        x_e, x_n = dm[e & np.isfinite(dm)] * 100, dm[~e & np.isfinite(dm)] * 100
        swd["by_threshold"][tname(T)] = {
            "eligible": int(e.sum()), "not_eligible": int((~e).sum()),
            "realised_move_eligible": {"n": int(len(x_e)), "mean_c": float(x_e.mean()) if len(x_e) else np.nan,
                                       "median_c": float(np.median(x_e)) if len(x_e) else np.nan,
                                       "share_ge_4c": float((x_e >= 4 - 1e-9).mean()) if len(x_e) else np.nan},
            "realised_move_not_eligible": {"n": int(len(x_n)), "mean_c": float(x_n.mean()) if len(x_n) else np.nan,
                                           "median_c": float(np.median(x_n)) if len(x_n) else np.nan,
                                           "share_ge_4c": float((x_n >= 4 - 1e-9).mean()) if len(x_n) else np.nan},
            "realised_ge_4c_points": int(big.sum()),
            "realised_ge_4c_that_are_eligible": int((big & e).sum()),
        }

    OUT.mkdir(parents=True, exist_ok=True)
    pts = P[["key", "slug", "n", "set", "game", "ga", "gb", "winner", "T_ms", "D"]].join(
        S[["t_pre_ms", "source", "state", "p_server0", "mid_pre", "pa", "pb", "v_now", "v_if_a", "v_if_b", "swing",
           "score_ok", "score_winner"]])
    pts = pts.rename(columns={"D": "realised_move_D", "ga": "score_after_a", "gb": "score_after_b"})
    pts["T_ms"] = pts.T_ms.astype(np.int64)        # full ms precision (float_format would round it to 6 digits)
    pts["replayable_lag2_V1"] = rp.to_numpy()
    for T in THRESHOLDS:
        pts[f"eligible_{tname(T)}"] = elig[T]
    pts.insert(0, "label", LABEL)
    pts.to_csv(OUT / "points_swing.csv", index=False, float_format="%.6g")

    res = {
        "label": LABEL,
        "status": "exploratory, post hoc: designed after the all-points replay's P&L was seen; not pre-registered",
        "declared_before_running": {
            "thresholds_c": [round(T * 100) for T in THRESHOLDS], "reference_T_c": round(REF_T * 100),
            "stamp_lags_s": LAGS, "primary_lag_s": PRIMARY_LAG, "V_s": VS, "seeds": list(SEEDS),
            "lead": LEAD, "net": NET, "net_cap_shares": MR.NET_CAP, "limit": "reference ask + 1c",
            "precision": MR.PRECISION,
            "swing": "|P(A wins match | A wins the point) - P(A wins match | B wins it)|, src/markov.py, women's "
                     "best of 3 (Format()), via engine/fair/value.py MatchFair: score and server belief from the "
                     "official winners of the earlier points of the match (server unknown, p_server0 = 0.5 at the "
                     "first point, Bayes-updated after every point), (pa, pb) refit by MatchFair.recalibrate to the "
                     "outcome-0 mid at the pre-point instant",
            "pre_point_instant": f"previous point's official stamp + {PRE_AFTER_PREV_MS / 1000:g} s (first point "
                                 f"of a match: its stamp - {FIRST_PRE_MS / 1000:g} s)",
            "valid_mid": f"book snapshot seen, spread <= {CAL_MAX_SPREAD:.2f}, a message within "
                         f"{MR.GAP_MS / 1000:g} s, not inside a recorder outage; else the last calibration of the "
                         "match is kept; no calibration yet -> not eligible",
        },
        "unchanged_from": "scripts/match_replay.py (imported: simulate, stats, cluster_ci, draws, leads, cell_times, "
                          "capture, outage rule D1)",
        "pre_point_instant_margin_s": gap_min - max(LAGS) - PRE_AFTER_PREV_MS / 1000,
        "pre_point_instant_vs_recorded_reprices": timing,
        "score_reconstruction_mismatches": n_bad,
        "m1_winner_vs_official_score": wcheck,
        "swing_source_counts": S.source.value_counts().to_dict(),
        "swing_diagnostics": swd,
        "reproduces_all_points_replay": repro,
        "cells": res_cells,
        "seeds": seeds,
    }
    (OUT / "selective.json").write_text(json.dumps(_clean(res), indent=1, default=MR._js))
    return res


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# =============================================================================================== figure
def figure(res: dict) -> None:
    from scripts import match_replay_report as REP
    REP._style()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.9), sharey=True)
    off = {None: -0.045, 0.02: -0.015, 0.04: 0.015, 0.06: 0.045}
    for ax, lag in zip(axes, LAGS):
        for T in (None, *THRESHOLDS):
            nm = tname(T)
            y = [res["cells"][f"{nm}|lag{lag:g}|V{V:g}"]["all"]["pnl_mark_usd"] for V in VS]
            lo = [res["seeds"][f"{nm}|lag{lag:g}|V{V:g}"]["pnl_mark_usd"]["min"] for V in VS]
            hi = [res["seeds"][f"{nm}|lag{lag:g}|V{V:g}"]["pnl_mark_usd"]["max"] for V in VS]
            x = np.array(VS) + off[T]
            col = REP.INK2 if T is None else TCOL[T]
            lab = "all points (the replay)" if T is None else f"ex-ante swing ≥ {round(T * 100)}c" + (
                " (reference)" if T == REF_T else "")
            ax.vlines(x, lo, hi, color=col, lw=1.0, alpha=0.55)
            ax.plot(x, y, color=col, lw=2, ls="--" if T is None else "-", marker="o" if T is None else TMARK[T],
                    ms=8, mec=REP.SURF, mew=1.5, label=lab, zorder=3)
            ax.annotate(nm.replace("T", "≥ ") if T is not None else "all", (x[-1], y[-1]), xytext=(8, 0),
                        textcoords="offset points", va="center", fontsize=8.5, color=REP.INK)
        ax.axhline(0, color=REP.INK2, lw=0.8)
        ax.set_xticks(VS)
        ax.set_xticklabels([f"{V:g} s" for V in VS])
        ax.set_xlim(-0.15, 1.25)
        ax.set_xlabel("video feed delay V")
        ax.set_title(f"stamp lag {lag:g} s" + (" (primary)" if lag == PRIMARY_LAG else ""), fontsize=10.5, loc="left")
        ax.grid(axis="y", color=REP.GRID, lw=0.6)
    axes[0].set_ylabel("$ P&L, marked at the +30 s mid (9 matches)")
    h, lb = axes[0].get_legend_handles_labels()
    fig.legend(h, lb, loc="upper left", bbox_to_anchor=(0.01, 0.935), ncol=4, fontsize=9)
    fig.suptitle("Trading only points with a large ex-ante Markov swing: marked P&L by feed delay "
                 "(seed 0; whisker = range over 20 seeds)", x=0.01, ha="left", fontsize=11.5, color=REP.INK)
    fig.tight_layout(rect=(0, 0.06, 1, 0.88))
    REP._footer(fig, LABEL)
    fig.savefig(OUT / "fig_selective.png", dpi=150)
    plt.close(fig)


# ================================================================================================== doc
def f2(x, nd=2):
    return "-" if x is None else f"{x:+.{nd}f}"


def usd(x):
    return "-" if x is None else ("−$" if x < 0 else "+$") + f"{abs(x):,.0f}"


def ci(c):
    return "" if not c or c[0] is None else f" [{c[0]:+.2f}, {c[1]:+.2f}]"


def main_table(res, lag) -> str:
    h = ("| T | V | eligible points (replayable) | calls | fills (wrong) | calls beating the book | c/share marked "
         "[95% CI] | c/share held [95% CI] | $ marked | $ held | realised move c, traded / not (median) |")
    out = [h, "|" + "---|" * 11]
    for T in (None, *THRESHOLDS):
        for V in VS:
            c = res["cells"][f"{tname(T)}|lag{lag:g}|V{V:g}"]
            a = c["all"]
            mv = c["move_traded_vs_not"]
            share = a["share_calls_beat_book"]
            tl = "all points" if T is None else f"≥ {round(T * 100)}c" + (" (ref)" if T == REF_T else "")
            out.append(
                f"| {tl} | {V:g} s | {c['eligible_points']} ({a['replayable_points']}) | {a['calls']} | "
                f"{a['fills']} ({a['fills_wrong']}) | {a['calls_beat_book']} of {a['calls_with_reprice']}"
                f" ({'-' if share is None else f'{share:.0%}'}) | "
                f"{f2(a['per_share_mark_c'])}{ci(a.get('per_share_mark_ci95_c'))} | "
                f"{f2(a['per_share_hold_c'])}{ci(a.get('per_share_hold_ci95_c'))} | {usd(a['pnl_mark_usd'])} | "
                f"{usd(a['pnl_hold_usd'])} | {f2(mv['traded']['median_c'], 1)} / {f2(mv['not_traded']['median_c'], 1)} |")
    return "\n".join(out)


def seed_table(res, lag) -> str:
    out = ["| T | V | fills | calls beating the book | c/share marked | $ marked | $ held | seeds with $ marked > 0 |",
           "|" + "---|" * 8]
    for T in (None, *THRESHOLDS):
        for V in VS:
            s = res["seeds"][f"{tname(T)}|lag{lag:g}|V{V:g}"]
            tl = "all points" if T is None else f"≥ {round(T * 100)}c"
            m = lambda k, nd=1: f"{s[k]['mean']:+.{nd}f} ± {s[k]['sd']:.{nd}f}"  # noqa: E731
            out.append(f"| {tl} | {V:g} s | {s['fills']['mean']:.1f} ± {s['fills']['sd']:.1f} | "
                       f"{s['calls_beat_book']['mean']:.1f} ± {s['calls_beat_book']['sd']:.1f} | "
                       f"{m('per_share_mark_c', 2)} | {m('pnl_mark_usd', 0)} | {m('pnl_hold_usd', 0)} | "
                       f"{s['seeds_marked_positive']} of {s['n_seeds']} |")
    return "\n".join(out)


def move_table(res) -> str:
    sd = res["swing_diagnostics"]
    out = ["| T | eligible / not (replayable) | realised move, eligible: median c (share ≥ 4c) | realised move, not "
           "eligible: median c (share ≥ 4c) | realised ≥ 4c points that pass the filter |", "|---|---|---|---|---|"]
    for T in THRESHOLDS:
        b = sd["by_threshold"][tname(T)]
        e, n = b["realised_move_eligible"], b["realised_move_not_eligible"]
        pct = lambda x: "-" if x is None else f"{x:.0%}"  # noqa: E731
        out.append(f"| ≥ {round(T * 100)}c | {b['eligible']} / {b['not_eligible']} | {f2(e['median_c'], 1)} "
                   f"({pct(e['share_ge_4c'])}, n {e['n']}) | {f2(n['median_c'], 1)} ({pct(n['share_ge_4c'])}, n {n['n']}) | "
                   f"{b['realised_ge_4c_that_are_eligible']} of {b['realised_ge_4c_points']} |")
    return "\n".join(out)


DECLARATION = """\
Declared in this file and in `scripts/match_replay_selective.py` (constants block) and committed before the
first run. The design was written after the all-points replay's P&L had been seen, so it is exploratory.

* **Filter.** Trade an official point only if its **ex-ante Markov swing** is ≥ T, **T ∈ {2c, 4c, 6c}**;
  **4c is the reference** (the latency sweep's ≥ 4c jump detector, `src/tier0.py` `JUMP_MIN`). Points below T
  are removed before the replay: no call, no order, no use of the net cap.
* **Swing.** |P(A wins the match | A wins the point) − P(A wins the match | B wins the point)| from
  `src/markov.py`, women's best of 3 with 7-point tiebreaks (`Format()`, as `engine/run.py`), computed through
  `engine/fair/value.py` `MatchFair`: the score before the point is rebuilt from the official winners of the
  match's earlier points; the server is not in the data, so the belief starts at 0.5 and is Bayes-updated
  after every point (`MatchFair.apply_point`); the serve/return point-win probabilities are refit
  (`MatchFair.recalibrate`, tour WTA) so that fair value at that score equals the outcome-0 mid at the
  **pre-point instant = the previous point's official stamp + 2 s** (first point of a match: its stamp − 30 s).
  A mid is usable if a book snapshot was seen, its spread is ≤ 10c (the engine's `max_spread`), the market had
  a message in the last 60 s and the instant is not inside a recorder outage; otherwise the match's last
  calibration is kept, and a point with no calibration yet is not eligible.
* **Everything else unchanged** from `scripts/match_replay.py` (imported, not copied): stamp lag **2.0 s
  primary, 3.0 s** also; **V ∈ {0, 0.5, 1.0} s**; model CV lead; Florida 67 ms; **20 seeds** (0-19; seed 0 is
  the shown replay and carries the CIs); net cap 100 shares per match; limit = stale (reference) ask + 1c;
  wrong calls 5 % (precision 0.95); 1 s taker delay; fee; +30 s mark; hold to result; outage rule D1.
* **Reported** per T × V × lag: points eligible, calls, fills, share of calls beating the book, net per share
  marked and held with the match-clustered 95 % CI, $ P&L marked and held, 20-seed mean ± SD, and as a
  diagnostic the realised book move (`m1_points.D`) of traded vs not-traded points. The all-points cells are
  reported alongside and must reproduce `results/replay/replay.json`.
"""


def write_doc(res) -> None:
    sd = res["swing_diagnostics"]
    q = sd["swing_c_quantiles"]
    repro_ok = all(v["identical"] for v in res["reproduces_all_points_replay"].values())
    src = res["swing_source_counts"]
    tm_ = res["pre_point_instant_vs_recorded_reprices"]
    txt = f"""# Match replay, selective variant: trade only points with a large ex-ante swing

> **{LABEL}.**
>
> Same caveats as the replay (`RESULTS.md`): no video was received, bought or watched; the feed, its delay V, the
> CV call and its lead are assumed; the bounce is the official stamp minus an assumed lag. Real: the official WTA
> point stamps and winners, the Polymarket books recorded live on 2026-10-03, the venue delay, the fee, the results.
> No order was sent. Use of the forward recording is logged in `results/oos_peeks.log`.

## Conclusion

{conclusion(res)}

![selective](../../results/replay/selective/fig_selective.png)

`results/replay/selective/fig_selective.png`: marked $ P&L over the 9 matches at V = 0, 0.5, 1 s for each T and
for all points (seed 0; whisker = min to max over the 20 seeds). Left: stamp lag 2.0 s (primary); right: 3.0 s.

## 1. Results, stamp lag 2.0 s (primary), seed 0

{main_table(res, 2.0)}

Eligible points: all points of the 9 matches with swing ≥ T (in brackets, those the replay can price). Calls:
eligible, replayable, quoted inside 5-95c. Calls beating the book: execution before the book's matched reprice
(`t_book`), of the calls that have one. CI: match-clustered bootstrap, 10,000 resamples of the matches with a fill
(`match_replay.cluster_ci`). Realised move: `m1_points.D`, the outcome-0 mid's move in the point winner's direction
across the point, of the filled points vs every other replayable point (the not-traded side includes the points the
filter removed). Diagnostic only: it is hindsight.

## 2. Stamp lag 3.0 s, seed 0

{main_table(res, 3.0)}

## 3. 20 seeds (mean ± SD over seeds 0-19)

Stamp lag 2.0 s:

{seed_table(res, 2.0)}

Stamp lag 3.0 s:

{seed_table(res, 3.0)}

## 4. Does the ex-ante swing pick the points the book moves on? (diagnostic)

Replayable points (stamp lag 2.0 s, V = 1 s): {sd['replayable_points']}, of which {sd['with_swing']} have an ex-ante
swing. Swing quantiles (p10 / p25 / median / p75 / p90): {q['10']:.1f} / {q['25']:.1f} / {q['50']:.1f} /
{q['75']:.1f} / {q['90']:.1f}c. Spearman correlation of the ex-ante swing with the size of the realised book move
|D|: {sd['spearman_swing_vs_abs_realised_move']:+.2f} (n {sd['n_for_correlation']}).

{move_table(res)}

## 5. Checks

* **All-points cells reproduce the committed replay** (`results/replay/replay.json`, same fills and $ to the cent at
  both lags and every V): {'yes' if repro_ok else 'NO'}. The filter is the only change.
* **Score reconstruction:** the score before each point, rebuilt point by point with `src/markov.py`'s scoring
  rules, disagrees with `m1_points.csv`'s set, game and previous point-score columns on
  {res['score_reconstruction_mismatches']} of 994 points (deviation S1).
* **No look-ahead in the filter:** the pre-point instant is ≥ {res['pre_point_instant_margin_s']:g} s before the
  earliest assumed bounce of the point (smallest gap between consecutive stamps minus 3 s lag minus 2 s); the score and
  the server belief use only earlier points; the replay's own reference price is read later, at the bounce, as before.
  Measured on the recorded book: the point's own matched reprice (`m1_points.t_book`) comes ≥
  {tm_['own_reprice_minus_pre_instant_s_min']:.1f} s after the pre-point instant on all {tm_['points_with_own_reprice']}
  points that have one (its first reprice ≥ {tm_['own_first_reprice_minus_pre_instant_s_min']:.1f} s after). The other
  way round, on {tm_['calibrated_points_previous_reprice_after_pre_instant']} of the
  {tm_['calibrated_points_with_previous_reprice']} calibrated points with a matched previous reprice, that reprice came
  after the pre-point instant, so the swing there was fitted to a mid that had not yet absorbed the previous point (no
  look-ahead; a noisier swing).
* **Where the swing's price came from** (all 994 points): {', '.join(f'{k}: {v}' for k, v in src.items())}.
* **m1's `winner` column vs the official score:** on {res['m1_winner_vs_official_score']['n_points_m1_winner_disagrees_with_score']}
  of 994 points the `winner` column of `m1_points.csv` (the replay's call direction) disagrees with the change in
  the official score: back-to-deuce points, where it names the player who had the advantage, and 9 tiebreak points
  of two early matches. The score is right where it can be checked: on the
  {sum(1 for p in res['m1_winner_vs_official_score']['points'] if p['book_move_in_m1_winner_direction_c'] is not None)}
  of them with a recorded book the mid's move in m1's winner direction was
  {', '.join(f"{p['book_move_in_m1_winner_direction_c']:+.1f}" for p in res['m1_winner_vs_official_score']['points'] if p['book_move_in_m1_winner_direction_c'] is not None)}c
  (against m1's winner, or flat).
  This variant keeps the replay's direction unchanged (it uses the score only for the swing); fills on those points:
  {res['cells']['all|lag2|V1']['fills_on_m1_winner_errors']['fills']} at the headline cell
  ({usd(res['cells']['all|lag2|V1']['fills_on_m1_winner_errors']['pnl_mark_usd'])} marked), 1-3 in every cell. The
  fix belongs to `research/v2/latency/load.py` (`_derive_pw`) and the replay; it is outside these files.
  Diagnostic: {sdiag(res)}
* **Score knowledge is assumed.** The official point-by-point feed reached our poller 1-2 minutes late on this day
  (`m1_points.pbp_delay_s`); a live trader would need the score from the video itself or a faster feed. The
  server is not observed (belief only).

## 6. Deviation from the declaration

**S1 (bug fix, before any P&L of this variant was read).** The declaration rebuilt the score "from the official
winners of the match's earlier points", i.e. m1's `winner` column. The first run's own consistency check showed
that score disagreeing with m1's official set / game / point-score columns on 447 of 963 points: one wrong
back-to-deuce winner shifts the rebuilt score for the rest of the match, and 31 points fell after a spurious match
end. The score is now rebuilt from the official score columns (the point winner is the side whose score moved;
`score_winner()`), and the check passes on all 994 points. The first run's outputs were overwritten; only its console
log and its per-point score file were read, no P&L. T, the swing, the pre-point instant, the cells and the replay are as declared.

## 7. Declaration (committed before the first run)

{DECLARATION}
## Reproduce

```bash
.venv/bin/python scripts/match_replay_selective.py --cache /path/outside/the/repo.pkl   # ~5-8 min
.venv/bin/python scripts/match_replay_selective.py --doc-only                          # figure + this file
```

Outputs in `results/replay/selective/`: `selective.json` (label, declaration, every T × lag × V cell at seed 0 with
CIs and per match, 20-seed summaries, swing diagnostics, reproduction check), `points_swing.csv` (each point's
pre-point state, server belief, pre-point mid, calibrated serve probabilities, ex-ante swing and eligibility),
`fig_selective.png`.
"""
    DOC.write_text(txt)


def sdiag(res) -> str:
    """Seed-0 cells re-run with the call direction from the official score instead of m1's `winner` column."""
    sel = [(T, lag, V) for T in THRESHOLDS for lag in LAGS for V in VS]
    d, flips = [], []
    for T, lag, V in sel:
        c = res["cells"][f"{tname(T)}|lag{lag:g}|V{V:g}"]
        a, b = c["all"]["pnl_mark_usd"], c["score_direction_diag"]["pnl_mark_usd"]
        d.append(b - a)
        if (a > 0) != (b > 0):
            flips.append(f"{tname(T).replace('T', '≥ ')}, lag {lag:g} s, V = {V:g} s: {usd(a)} → {usd(b)}")
    k = res["cells"][f"T4c|lag{PRIMARY_LAG:g}|V1"]
    return (f"re-running every seed-0 cell with the call direction taken from the official score changes the 18 "
            f"selective cells' marked P&L by {min(d):+.0f} to {max(d):+.0f} $ (reference T = 4c, lag 2 s, V = 1 s: "
            f"{usd(k['all']['pnl_mark_usd'])} → {usd(k['score_direction_diag']['pnl_mark_usd'])}); sign changes: "
            + ("; ".join(flips) if flips else "none") + ".")


def conclusion(res) -> str:
    """Plain conclusion. The wording was written after the results were seen; every number is read from
    selective.json."""
    c, s = res["cells"], res["seeds"]
    g = lambda T, lag, V: c[f"{tname(T)}|lag{lag:g}|V{V:g}"]["all"]  # noqa: E731
    gs = lambda T, lag, V: s[f"{tname(T)}|lag{lag:g}|V{V:g}"]  # noqa: E731
    pos = lambda T, lag, V: gs(T, lag, V)["seeds_marked_positive"]  # noqa: E731
    sel = [T for T in THRESHOLDS]
    neg2 = sum((g(T, PRIMARY_LAG, V)["pnl_mark_usd"] or 0) < 0 for T in sel for V in VS)
    maxpos2 = max(pos(T, PRIMARY_LAG, V) for T in sel for V in VS)
    sd = res["swing_diagnostics"]
    b4 = sd["by_threshold"]["T4c"]
    r = lambda T, lag, V: f"{f2(g(T, lag, V)['per_share_mark_c'])}c"  # noqa: E731
    mv = lambda T, lag, V: c[f"{tname(T)}|lag{lag:g}|V{V:g}"]["move_traded_vs_not"]  # noqa: E731
    k30 = g(REF_T, 3.0, 0.0)
    k35 = g(REF_T, 3.0, 0.5)
    k31 = g(REF_T, 3.0, 1.0)
    w = res["m1_winner_vs_official_score"]
    out = f"""\
**Plain answer: on these 9 matches, picking points by their ex-ante Markov swing does not rescue the 1 s video
trader. At the primary stamp lag (2.0 s) it still loses at every T and every V; it loses less mostly because it
trades less.**

* **Primary stamp lag 2.0 s: {neg2} of {len(sel) * len(VS)} selective cells lose money marked** (seed 0), and no
  selective cell is positive in more than {maxpos2} of 20 seeds. At the headline V = 1 s: all points
  {g(None, 2.0, 1.0)['fills']} fills, {r(None, 2.0, 1.0)} per share, {usd(g(None, 2.0, 1.0)['pnl_mark_usd'])} marked;
  T = 2c {g(0.02, 2.0, 1.0)['fills']} fills, {r(0.02, 2.0, 1.0)}, {usd(g(0.02, 2.0, 1.0)['pnl_mark_usd'])};
  **T = 4c (reference) {g(0.04, 2.0, 1.0)['fills']} fills, {r(0.04, 2.0, 1.0)}{ci(g(0.04, 2.0, 1.0)['per_share_mark_ci95_c'])},
  {usd(g(0.04, 2.0, 1.0)['pnl_mark_usd'])}**; T = 6c {g(0.06, 2.0, 1.0)['fills']} fills, {r(0.06, 2.0, 1.0)}{ci(g(0.06, 2.0, 1.0)['per_share_mark_ci95_c'])},
  {usd(g(0.06, 2.0, 1.0)['pnl_mark_usd'])} (20-seed mean {gs(0.06, 2.0, 1.0)['per_share_mark_c']['mean']:+.2f}c). The
  smaller dollar losses come from fewer fills; per share, the filtered cells are less negative at V = 0 (all points
  {r(None, 2.0, 0.0)}, T = 4c {r(0.04, 2.0, 0.0)}, T = 6c {r(0.06, 2.0, 0.0)}; point estimates whose CIs overlap, the
  difference is not tested) and not at 1 s for T ≤ 4c.
* **Stamp lag 3.0 s (the optimistic sensitivity): T = 4c is positive at V = 0** ({k30['fills']} fills,
  {f2(k30['per_share_mark_c'])}c{ci(k30['per_share_mark_ci95_c'])}, {usd(k30['pnl_mark_usd'])} marked; positive in
  {pos(0.04, 3.0, 0.0)} of 20 seeds), is about zero at V = 0.5 s ({f2(k35['per_share_mark_c'])}c, {pos(0.04, 3.0, 0.5)} of 20
  seeds positive) and loses at V = 1 s ({f2(k31['per_share_mark_c'])}c{ci(k31['per_share_mark_ci95_c'])}, {pos(0.04, 3.0, 1.0)} of 20).
  This is the only selective cell whose marked CI lies above zero, out of 18 selective cells (3 T × 3 V × 2
  lags), and it sits at the stamp lag that gives the trader the most time; at the same lag every T loses at V = 1 s.
  Read it as one post hoc cell, not as an edge: among 18 correlated cells designed after the all-points result, one
  95 % CI clear of zero is about what chance alone gives; a percentile bootstrap over only
  {k30['matches_with_fills']} matches with fills tends to give intervals that are too narrow; and the 20 seeds re-draw
  only the simulated CV lead and wrong calls on the same 9 matches, so "{pos(0.04, 3.0, 0.0)} of 20 seeds" says
  nothing about other matches or days.
* **On this day the ex-ante swing does pick the points the book moves on.** Over the {sd['replayable_points']} replayable points
  its Spearman correlation with the size of the realised book move is
  {sd['spearman_swing_vs_abs_realised_move']:+.2f}; T = 4c keeps {b4['realised_ge_4c_that_are_eligible']} of the
  {b4['realised_ge_4c_points']} points whose book moved ≥ 4c, plus as many smaller ones (half of the
  {b4['eligible']} eligible points moved ≥ 4c). So a set close to the sweep's "≥ 4c jumps" can be chosen without
  hindsight, at about twice the size. Even so, no 1 s cell turned positive. The selective cells that are positive
  are those where most orders execute before the book reprices (V = 0 with a 3 s lag: about two thirds of calls); at
  V = 1 s and lag 2 s only {g(0.04, 2.0, 1.0)['share_calls_beat_book']:.0%} of T = 4c calls beat the book. With 9
  matches this describes where the P&L sits; it does not test why.
* **Traded vs not traded (diagnostic, hindsight):** at T = 4c, V = 1 s, lag 2 s the filled points' realised move has
  median {f2(mv(0.04, 2.0, 1.0)['traded']['median_c'], 1)}c vs {f2(mv(0.04, 2.0, 1.0)['not_traded']['median_c'], 1)}c for
  every other replayable point (≥ 4c: {mv(0.04, 2.0, 1.0)['traded']['share_ge_4c']:.0%} vs
  {mv(0.04, 2.0, 1.0)['not_traded']['share_ge_4c']:.0%}); at T = 6c {f2(mv(0.06, 2.0, 1.0)['traded']['median_c'], 1)}c vs
  {f2(mv(0.06, 2.0, 1.0)['not_traded']['median_c'], 1)}c. At T = 4c the points that fill at 1 s move no more than the
  rest; at T = 6c they move more, and still lose per share.
* **Held-to-result P&L** is positive in several selective cells (e.g. T = 4c, lag 2 s, V = 0.5 s:
  {usd(g(0.04, 2.0, 0.5)['pnl_hold_usd'])} held against {usd(g(0.04, 2.0, 0.5)['pnl_mark_usd'])} marked). It is mostly the
  match result on a ≤ 100-share net position, so it is noise for this question; read the marked figure.
* **What this is:** {LABEL}. 18 selective cells on one day; the reading above is descriptive, and no T is chosen.
  A separate data issue for the replay's owners (not fixed here): m1's `winner` column disagrees with the official
  score on {w['n_points_m1_winner_disagrees_with_score']} of 994 points (§5). As a diagnostic, {sdiag(res)}"""
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None, help="pickle of the parsed recording (keep it outside the repo)")
    ap.add_argument("--doc-only", action="store_true")
    a = ap.parse_args()
    if a.doc_only:
        res = json.loads((OUT / "selective.json").read_text())
    else:
        res = _clean(run(a.cache))
        res = json.loads((OUT / "selective.json").read_text())
    figure(res)
    write_doc(res)
    print(f"wrote {OUT.relative_to(ROOT)}/selective.json, fig_selective.png, points_swing.csv and "
          f"{DOC.relative_to(ROOT)}")
