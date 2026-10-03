"""Backtest EXAMPLE MATCH for the video: one match of the tier-0 feed-latency backtest, shown trade by trade.

    LABEL: Example match from the backtest (selected for illustration) · simulated 1 s licensed-feed baseline ·
           real Polymarket price path · paper  (+ the share of backtest matches that were profitable)

    python scripts/backtest_example_match.py         # -> results/viz/v60_assets/backtest_match/match.json
    python scripts/backtest_example_match.py render  # match.json -> example_match.mp4 (1920x1080, 30 fps, 12 s),
                                                     #   example_match.png (300 dpi still), example_match_onscreen.json
    python scripts/backtest_example_match.py render --at 6.0 --out f.png   # one preview frame (QA)

`render` reads match.json only (no model run) and draws it in a keynote style: pure black, Inter (OFL, in
results/viz/v60_assets/fonts/), the real Polymarket prints as a thin white line drawn left to right, orange
dots for our modelled fills with their settlement P&L, grey dots for missed calls, the cumulative paper P&L top
right with the profitable-share stat under it, and the label bottom left on every frame.

The selection rule was committed first (results/viz/v60_assets/backtest_match/SELECTION.md) and is applied here
mechanically. The cell is the latency sweep's ("video", "tournament_lagcal", V = 1.0 s, "own120"): our CV on a
licensed video feed 1 s behind the court, reprice timing drawn once per tournament, stamp lag = the calibrated
3.14 s (an inference, post hoc). scripts/tier0_latency_sweep.py and src/tier0.py are imported and called
unchanged (`SW.cell`, `T.draws`, `T.simulate`, `T.metrics`). The per-call timing decomposition (CV call, order
arrival, reprice) recomputes the same expressions `T.simulate` uses from the same draws and is asserted equal
to the tau that `T.simulate` returns; the sweep's per-seed P&L is asserted reproduced for all 20 seeds.

Real: the Polymarket prints (price path), the historical jump times and directions, match results, fees, venue
delays. Modelled (paper): every call, order, fill price, share count and P&L. No order was ever sent.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from scripts import tier0_latency_sweep as SW  # noqa: E402
from src import tier0 as T  # noqa: E402

warnings.filterwarnings("ignore")

LABEL = ("Example match from the backtest (selected for illustration) · simulated 1 s licensed-feed baseline · "
         "real Polymarket price path · paper")
SOURCE, READING, V, CV = "video", "tournament_lagcal", 1.0, "own120"
OUTDIR = ROOT / "results/viz/v60_assets/backtest_match"
MIN_TRADES = 6
EPS = 1e-9
PRINTS = {"IS": ROOT / "data/is_prints.parquet", "burned_OOS": ROOT / "data/locked/oos_prints.parquet"}


# ------------------------------------------------------------------------------------------ runs
def run(c: dict, period: str, seed: int) -> tuple:
    """The sweep's _job for one (period, seed), keeping the call table. Returns (calls, metrics, sc, cvs, draws)."""
    sc, cvs = SW.cell(SOURCE, READING, V, CV, c)
    P = c["per"][period]
    J = P["J"]
    dr = T.draws(len(J), P["seed"] + seed, max(c["n_tour"], 1))
    calls = T.simulate(J, P["M"], sc, dr, c["pools"], cvs, c["mix"])
    m = T.metrics(calls, T.period_days(J, sc.regime))
    return calls, m, sc, cvs, dr


def match_table(calls: pd.DataFrame) -> pd.DataFrame:
    tr = calls[calls.shares > EPS]
    g = tr.groupby("cond").agg(n_trades=("pnl", "size"), pnl=("pnl", "sum"), start=("start", "first"))
    return g.reset_index()


def share_stats(g: pd.DataFrame) -> dict:
    n = int(len(g))
    k = int((g.pnl > 0).sum())
    return {"traded_matches": n, "profitable_matches": k, "share_profitable": round(k / n, 4) if n else None,
            "median_match_pnl_usd": round(float(g.pnl.median()), 2) if n else None,
            "mean_match_pnl_usd": round(float(g.pnl.mean()), 2) if n else None,
            "total_pnl_usd": round(float(g.pnl.sum()), 2),
            "matches_with_ge6_trades": int((g.n_trades >= MIN_TRADES).sum()),
            "eligible_ge6_trades_and_profitable": int(((g.n_trades >= MIN_TRADES) & (g.pnl > 0)).sum())}


# ------------------------------------------------------------------------ per-call decomposition
def decompose(c: dict, period: str, sc, cvs: dict, dr: dict) -> pd.DataFrame:
    """Per call (index i = position in simulate's filtered X, the 'i' column of its output): the same
    expressions as T.simulate for lead, CV call time, network, order arrival and reprice time (seconds after
    the modelled ball landing), plus the pool point and the correct/wrong draw."""
    P = c["per"][period]
    J, M = P["J"], P["M"]
    cov = T.coverage_set(M, sc.coverage, sc.regime)
    X = J[J.cond.isin(cov)]
    ref = X[sc.stale].to_numpy()
    dirn = X["dir"].to_numpy()
    q_c0 = np.where(dirn > 0, ref, 1 - ref) + sc.stale_adj
    ok = np.isfinite(ref) & (q_c0 >= T.ZONE[0]) & (q_c0 <= T.ZONE[1])
    X = X[ok]
    q_c0 = q_c0[ok]
    r = X.row.to_numpy()
    n = len(X)
    pool = c["pools"][sc.pool]
    pidx = np.minimum((dr["pool"][r] * len(pool)).astype(int), len(pool) - 1)
    men = X.men.to_numpy()
    p_out = np.where(men, c["mix"]["men"]["out"], c["mix"]["women"]["out"])
    is_out = dr["end"][r] < p_out
    cvd = cvs[sc.cv]
    lead, prec_cv, called = T.lead_and_precision(cvd, dr["lead"][r], dr["bin"][r])
    early = is_out & called
    lead = np.where(early, lead, 0.0)
    prec = np.where(early, prec_cv, sc.p_event)
    lat = X.region.map(T.REGION_MS).to_numpy(float) / 1000.0
    t_call = -lead + cvd["t_inf"]                       # CV call on the delayed video (t_inf already holds + V)
    t_gate = t_call + lat + T.GATEWAY                    # order reaches the venue (London gateway)
    arrival = t_gate + X.delay.to_numpy(float)           # order becomes live after the venue's order delay
    R = pool.R.to_numpy()
    assert sc.r_mode == "tournament"
    tu = dr["tour"][X.tour.to_numpy()]
    R_draw = R[np.minimum((tu * len(pool)).astype(int), len(pool) - 1)]
    t_rep = R_draw + sc.stamp_lag + sc.r_shift
    return pd.DataFrame({"i": np.arange(n), "lead_s": lead, "t_cv_call_s": t_call, "network_s": lat,
                         "t_order_at_venue_s": t_gate, "t_order_live_s": arrival, "t_official_stamp_s":
                         np.full(n, sc.stamp_lag), "R_tournament_s": R_draw, "t_book_reprice_s": t_rep,
                         "tau_check": t_rep - arrival, "p_correct": prec, "stale_token_price": q_c0,
                         "ref0": X[sc.stale].to_numpy(), "post30_0": X["post30"].to_numpy(float),
                         "detect_ts": X.detect_ts.to_numpy(float), "jump_dir": dirn[ok], "live_pool_point": pidx})


def miss_reason(row) -> str | None:
    if row.shares > EPS:
        return None
    if row.correct and row.tau < 0:
        return "too late: our limit order would go live after the book repriced (never chases)"
    if row.sh_raw <= EPS:
        return "no stale depth left in the book for our share"
    return "blocked by the 100-share per-match net cap"


# ------------------------------------------------------------------------------------------ main
def main():
    print(LABEL)
    c = SW.ctx()
    sweep = pd.read_csv(ROOT / "results/tier0/latency_sweep_seeds.csv")
    sweep = sweep[(sweep.source == SOURCE) & (sweep.reading == READING) & (sweep.x_s == V) & (sweep.cv == CV)]
    assert len(sweep) == 2 * SW.SEEDS, len(sweep)

    # 1. every seed of the cell (seed choice + supplementary spread); check against the published sweep
    runs, per_seed = {}, []
    for s in range(SW.SEEDS):
        tot = 0.0
        rec = {"seed": s}
        for p in SW.PERIODS:
            calls, m, sc, cvs, dr = run(c, p, s)
            pub = float(sweep[(sweep.period == p) & (sweep.seed == s)].pnl_usd.iloc[0])
            assert abs(m["pnl_usd"] - pub) < 1e-3, (p, s, m["pnl_usd"], pub)
            runs[(p, s)] = (calls, m, sc, cvs, dr)
            tot += m["pnl_usd"]
            st = share_stats(match_table(calls))
            rec[p] = {"pnl_usd": round(m["pnl_usd"], 2), "share_profitable": st["share_profitable"],
                      "median_match_pnl_usd": st["median_match_pnl_usd"], "traded_matches": st["traded_matches"]}
        g = pd.concat([match_table(runs[(p, s)][0]) for p in SW.PERIODS])
        st = share_stats(g)
        rec["pooled"] = {"pnl_usd": round(tot, 2), "share_profitable": st["share_profitable"],
                         "median_match_pnl_usd": st["median_match_pnl_usd"], "traded_matches": st["traded_matches"]}
        rec["total_pnl_usd"] = tot
        per_seed.append(rec)
        print(f"seed {s:2d}  total ${tot:,.2f}  profitable share pooled {st['share_profitable']}", flush=True)

    # 2. median seed by total P&L: rank 10 of 20 ascending (lower median), ties lower index (SELECTION.md)
    order = sorted(per_seed, key=lambda r: (r["total_pnl_usd"], r["seed"]))
    k_med = len(order) // 2 - 1
    seed = order[k_med]["seed"]
    print(f"median seed (rank {k_med + 1} of {len(order)}): {seed}")

    # 3. match table at that seed, both periods pooled; choose
    tabs = []
    for p in SW.PERIODS:
        g = match_table(runs[(p, seed)][0])
        g["period"] = p
        tabs.append(g)
    G = pd.concat(tabs, ignore_index=True)
    elig = G[(G.n_trades >= MIN_TRADES) & (G.pnl > 0)]
    elig = elig.sort_values(["n_trades", "start", "cond"], ascending=[False, True, True], kind="stable")
    pick = elig.iloc[0]
    period, cond = pick.period, pick.cond
    ties = elig[elig.n_trades == pick.n_trades]
    print(f"chosen {cond} ({period}): {int(pick.n_trades)} trades, ${pick.pnl:,.2f}; "
          f"{len(elig)} eligible, {len(ties)} at the max trade count")

    stats = {p: share_stats(G[G.period == p]) for p in SW.PERIODS}
    stats["pooled"] = share_stats(G)

    # 4. the chosen match, call by call
    calls, m, sc, cvs, dr = runs[(period, seed)]
    D = decompose(c, period, sc, cvs, dr)
    mc = calls[calls.cond == cond].merge(D, on="i", how="left", validate="one_to_one")
    assert np.allclose(mc.tau.to_numpy(), mc.tau_check.to_numpy(), atol=1e-9)
    assert (np.where(mc.correct, mc.d0, -mc.d0) == mc.jump_dir).all()   # correct = buy in the jump direction
    mc = mc.sort_values("ts", kind="stable").reset_index(drop=True)
    mc["fill"] = mc.shares > EPS
    mc["cum_pnl"] = np.where(mc.fill, mc.pnl, 0.0).cumsum()
    # edge at the fill vs the post-jump price (the model prices a fill as post-jump price - measured edge, or
    # + measured cost for a wrong call; edge_c is that per-share edge), net of the fee
    mc["edge_usd"] = np.where(mc.fill, mc.shares * (mc.edge_c - mc.fee_ps), 0.0)
    mc["cum_edge"] = mc.edge_usd.cumsum()
    J = c["per"][period]["J"]
    U = c["per"][period]["M"].set_index("cond")
    jm = J[J.cond == cond].iloc[0]
    out0, out1 = (str(U.loc[cond, "out0"]), str(U.loc[cond, "out1"])) if "out0" in U else ("outcome 0", "outcome 1")

    calls_out = []
    for k, r in enumerate(mc.itertuples()):
        tok0 = r.d0 > 0
        # display clock: the modelled reprice is placed at the historical jump onset (ASSUMPTION, display only)
        t0 = float(r.ts) - float(r.t_book_reprice_s)
        rel = {"cv_call": r.t_cv_call_s, "order_at_venue": r.t_order_at_venue_s, "order_live": r.t_order_live_s,
               "official_stamp": r.t_official_stamp_s, "book_reprice": r.t_book_reprice_s}
        calls_out.append({
            "n": k + 1,
            "jump_onset_ts": float(r.ts), "jump_onset_utc": datetime.fromtimestamp(r.ts, timezone.utc).isoformat(),
            "jump_detect_ts": float(r.detect_ts),
            "jump_dir_outcome0": int(r.jump_dir),
            "jump_size": round(float(r.size), 4),
            "stale_price_outcome0_vwap": round(float(r.ref0), 4),
            "post_jump_price_outcome0_vwap30s": None if not np.isfinite(r.post30_0) else round(float(r.post30_0), 4),
            "point_ending": "out ball" if r.is_out else "other ending (winner, net, ...)",
            "cv_called_early": bool(r.early), "cv_lead_s": round(float(r.lead_s), 3),
            "call_correct": bool(r.correct), "p_correct_model": round(float(r.p_correct), 4),
            "times_s_after_ball_landing": {kk: round(float(v), 4) for kk, v in rel.items()},
            "network_to_london_s": round(float(r.network_s), 3), "venue_order_delay_s": int(r.delay),
            "tau_s": round(float(r.tau), 4),
            "display_clock_ts": {kk: round(t0 + float(v), 3) for kk, v in
                                 {"ball_landing": 0.0, **rel}.items()},
            "order": {"side": "BUY", "token": out0 if tok0 else out1, "token_index": 0 if tok0 else 1,
                      "max_usd": sc.trade_cap},
            "result": "fill" if r.fill else "miss",
            "miss_reason": miss_reason(r),
            "fill_price_token": round(float(r.q), 4) if r.fill else None,
            "fill_price_outcome0_equiv": (round(float(r.q if tok0 else 1 - r.q), 4) if r.fill else None),
            "shares": round(float(r.shares), 3), "usd_in": round(float(r.usd_in), 2),
            "shares_before_net_cap": round(float(r.sh_raw), 3),
            "fee_per_share": round(float(r.fee_ps), 5), "payout_per_share": float(r.payout),
            "pnl_per_share": round(float(r.pnl_ps), 5) if r.fill else None,
            "pnl_usd": round(float(r.pnl), 4) if r.fill else 0.0,
            "cum_pnl_usd": round(float(r.cum_pnl), 4),
            "edge_per_share_vs_post_jump": round(float(r.edge_c), 5) if r.fill else None,
            "edge_usd_net_fee": round(float(r.edge_usd), 4),
            "cum_edge_usd_net_fee": round(float(r.cum_edge), 4),
        })

    pr = pd.read_parquet(PRINTS[period], columns=["cond", "ts", "p", "usd"], filters=[("cond", "==", cond)])
    pr = pr.sort_values("ts", kind="stable")
    fills = mc[mc.fill]
    full = {**stats, "chosen_seed_index": seed}
    pct = lambda x: f"{100 * x:.1f}%"  # noqa: E731
    share_line = (f"{stats['pooled']['profitable_matches']} of {stats['pooled']['traded_matches']} traded backtest "
                  f"matches ({pct(stats['pooled']['share_profitable'])}) were profitable at this setting "
                  f"(IS {pct(stats['IS']['share_profitable'])}, burned OOS "
                  f"{pct(stats['burned_OOS']['share_profitable'])}; seed {seed})")
    res = {
        "label": LABEL,
        "label_share": share_line,
        "label_full": f"{LABEL} · {share_line}",
        "what": "One match of the tier-0 backtest at the simulated 1 s licensed-feed baseline (video + our CV, "
                "V = 1.0 s), shown call by call. Real: the Polymarket price path, jump times and directions, "
                "match result, fee, venue delay. Modelled (paper, no order was sent): calls, orders, fills, P&L.",
        "selection": {"rule_file": "results/viz/v60_assets/backtest_match/SELECTION.md",
                      "rule": "reading = calibrated (tournament_lagcal), V = 1.0 s, seed = the median seed by total "
                              "P&L (rank 10 of 20, lower median); among matches with >= 6 trades and positive P&L, "
                              "the one with the most trades; ties by earliest start",
                      "seed_index": seed, "seed_rank": f"{k_med + 1} of {len(order)} by total P&L (IS + burned OOS)",
                      "seed_total_pnl_usd": round(order[k_med]["total_pnl_usd"], 2),
                      "eligible_matches": int(len(elig)),
                      "eligible_at_max_trades": int(len(ties)),
                      "runner_up": None if len(elig) < 2 else {
                          "cond": elig.iloc[1].cond, "period": elig.iloc[1].period,
                          "n_trades": int(elig.iloc[1].n_trades), "pnl_usd": round(float(elig.iloc[1].pnl), 2)},
                      "illustrative_not_typical": "This match was chosen for the most trades among profitable "
                                                  "ones; it is not a typical match. See profitable_share."},
        "setting": {"source": SOURCE, "reading": READING, "reading_label": SW.READ_LABEL[READING],
                    "video_delay_V_s": V, "cv": CV, "stamp_lag_s": sc.stamp_lag,
                    "stamp_lag_note": "calibrated 3.14 s is an inference (fast-tier prints), chosen post hoc; the "
                                      "pre-registered stamp lag is 2.0 s",
                    "period": period, "period_note": None if period == "IS" else
                    "burned OOS: not blind (the OOS set was used in earlier runs)",
                    "seed_draws": int(c["per"][period]["seed"] + seed),
                    "scenario": {k: v for k, v in T.as_dict(sc).items()},
                    "model": "src/tier0.py CORRECTED via scripts/tier0_latency_sweep.py cell(); imported unchanged"},
        "match": {"cond": cond, "slug": jm.slug, "title": jm.title, "series": jm.series, "league": jm.league,
                  "start_utc": pd.Timestamp(jm.start).isoformat(), "end_utc": pd.Timestamp(jm.end).isoformat(),
                  "outcome0": out0, "outcome1": out1, "winner": out0 if jm.res0 == 1 else out1,
                  "res0": float(jm.res0), "volume_usd": round(float(jm.volume), 2), "fee_rate": float(jm.fee_rate),
                  "venue_order_delay_s": int(jm.delay), "region": jm.region,
                  "network_assumption_ms": T.REGION_MS[jm.region]},
        "summary": {"calls": int(len(mc)), "fills": int(mc.fill.sum()), "misses": int((~mc.fill).sum()),
                    "fills_correct": int((mc.fill & mc.correct).sum()), "fills_wrong": int((mc.fill & ~mc.correct).sum()),
                    "misses_by_reason": {k: int(v) for k, v in mc[~mc.fill].apply(miss_reason, axis=1).value_counts().items()},
                    "shares": round(float(fills.shares.sum()), 2), "usd_in": round(float(fills.usd_in.sum()), 2),
                    "pnl_usd": round(float(fills.pnl.sum()), 2),
                    "pnl_c_per_share": round(float(fills.pnl.sum() / fills.shares.sum() * 100), 3),
                    "best_trade_usd": round(float(fills.pnl.max()), 2), "worst_trade_usd": round(float(fills.pnl.min()), 2),
                    "trades_positive": int((fills.pnl > 0).sum()),
                    "edge_usd_net_fee_at_fill": round(float(fills.edge_usd.sum()), 2),
                    "pnl_note": "pnl_usd is settlement P&L (each position held to the match result, as in the backtest), so a correct call on the eventual loser's point still loses at settlement; edge_usd_net_fee is the modelled edge at the fill against the post-jump price, before settlement variance"},
        "profitable_share": full,
        "profitable_share_note": "Traded matches = matches with >= 1 fill at the chosen seed; profitable = match P&L "
                                 "> 0 (fees included). Pooled = IS + burned OOS.",
        "profitable_share_all_seeds": {
            "note": "supplementary, not used for the choice: the same statistics for each of the sweep's 20 seeds",
            "pooled_share_profitable": {"mean": round(float(np.mean([r["pooled"]["share_profitable"] for r in per_seed])), 4),
                                        "min": min(r["pooled"]["share_profitable"] for r in per_seed),
                                        "max": max(r["pooled"]["share_profitable"] for r in per_seed)},
            "IS_share_profitable_mean": round(float(np.mean([r["IS"]["share_profitable"] for r in per_seed])), 4),
            "burned_OOS_share_profitable_mean": round(float(np.mean([r["burned_OOS"]["share_profitable"] for r in per_seed])), 4),
            "pooled_median_match_pnl_usd_mean": round(float(np.mean([r["pooled"]["median_match_pnl_usd"] for r in per_seed])), 2),
            "per_seed": [{k: v for k, v in r.items() if k != "total_pnl_usd"} | {"total_pnl_usd": round(r["total_pnl_usd"], 2)}
                         for r in per_seed]},
        "calls": calls_out,
        "price_path": {"source": str(PRINTS[period].relative_to(ROOT)),
                       "note": "every Polymarket print of this match's in-play tape used by the backtest (real); "
                               "p = outcome-0 price, usd = print size",
                       "outcome": out0, "n": int(len(pr)),
                       "ts": [float(x) for x in pr.ts], "p": [round(float(x), 4) for x in pr.p],
                       "usd": [round(float(x), 2) for x in pr.usd]},
        "fields": {
            "times_s_after_ball_landing": "model clock, origin = the modelled ball landing (point end). cv_call = "
                                          "-CV lead + 20 ms inference + V; order_at_venue = + network to London + 2 ms "
                                          "gateway; order_live = + the venue's order delay; official_stamp = stamp lag; "
                                          "book_reprice = R (drawn per tournament from the live day) + stamp lag",
            "tau_s": "book_reprice - order_live; a correct call fills only if tau >= 0 (limit order)",
            "display_clock_ts": "ASSUMPTION, display only: the model does not place the ball landing on the "
                                "historical clock; here the modelled book reprice is put at the historical jump "
                                "onset (first print of the detector's 10 s window), and the other events keep "
                                "their modelled offsets",
            "jump_dir_outcome0": "+1 = the historical move was up in outcome 0",
            "fill_price_token": "price paid for the bought token (live-book model); fill_price_outcome0_equiv "
                                "puts it on the outcome-0 price axis (1 - price for an outcome-1 buy)",
            "pnl_usd": "settlement P&L: shares x (payout - fill price - fee per share); 0 for a miss",
            "edge_usd_net_fee": "modelled edge at the fill: shares x (edge per share vs the post-jump price - fee per share); negative for a wrong call",
        },
        "checks": {"sweep_pnl_reproduced_all_20_seeds_both_periods": True,
                   "tau_decomposition_equals_simulate": True},
        "oos_peek": "this run reads burned OOS (non-blind) through the sweep's code; results/oos_peeks.log is not "
                    "written by this script",
        "run": {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "script": "scripts/backtest_example_match.py", "python": sys.version.split()[0]},
    }
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "match.json").write_text(json.dumps(res, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    print(json.dumps({k: res[k] for k in ("label_full", "match", "summary", "profitable_share")}, indent=1, default=str))


# ------------------------------------------------------------------------------------------ render
FONT_DIR = ROOT / "results/viz/v60_assets/fonts"
RW, RH, FPS, DUR = 1920, 1080, 30, 12.0
SS = 2                                    # supersampling for anti-aliasing (drawn at 2x, box-reduced)
C_WHITE, C_ORANGE = (245, 245, 247), (255, 159, 10)
C_GREY, C_GREY2, C_GREY3, C_GRID = (142, 142, 147), (110, 110, 115), (88, 88, 92), (30, 30, 32)
PL, PR, PT, PB = 176, 1808, 304, 896      # plot box (1x px); price axis 0..100 c
T_FADE, T_A, T_B, T_END_HEAD = 0.5, 0.6, 9.4, 9.8   # chrome fade-in; line draws T_A..T_B; head dot fades out
T_NOTE = 9.6                              # best / worst trade notes fade in
RAMP = 0.3                                # counter roll per fill (s)
MINUS = "−"


class Face:
    """One Inter weight: Pillow glyph rendering plus GPOS pair kerning (Pillow's basic layout has no GPOS) and
    tabular digits for counters (fixed cell = the widest digit; Inter's tnum glyphs are not in the cmap)."""

    def __init__(self, name: str):
        from fontTools.ttLib import TTFont
        self.path = str(FONT_DIR / name)
        f = TTFont(self.path)
        self.upem = f["head"].unitsPerEm
        self.cmap = f.getBestCmap()
        hm = f["hmtx"]
        self.tab = max(hm[self.cmap[ord(d)]][0] for d in "0123456789")
        g = f["GPOS"].table
        idx = sorted({i for fr in g.FeatureList.FeatureRecord if fr.FeatureTag == "kern"
                      for i in fr.Feature.LookupListIndex})
        self.lookups = []
        for i in idx:
            subs = []
            for st in g.LookupList.Lookup[i].SubTable:
                st = getattr(st, "ExtSubTable", st)
                if type(st).__name__ == "PairPos":
                    subs.append((st, set(st.Coverage.glyphs)))
            self.lookups.append(subs)
        self._k, self._f = {}, {}

    def font(self, px: float):
        from PIL import ImageFont
        key = round(px * 4) / 4
        if key not in self._f:
            self._f[key] = ImageFont.truetype(self.path, key)
        return self._f[key]

    def kern(self, a: str, b: str) -> int:
        key = (a, b)
        if key in self._k:
            return self._k[key]
        g1, g2 = self.cmap.get(ord(a)), self.cmap.get(ord(b))
        v = 0
        for subs in self.lookups:
            for st, cov in subs:
                if g1 not in cov:
                    continue
                if st.Format == 1:
                    rec = next((r for r in st.PairSet[st.Coverage.glyphs.index(g1)].PairValueRecord
                                if r.SecondGlyph == g2), None)
                    if rec is None:
                        continue
                    v += getattr(rec.Value1, "XAdvance", 0) or 0
                else:
                    c1 = st.ClassDef1.classDefs.get(g1, 0)
                    c2 = st.ClassDef2.classDefs.get(g2, 0)
                    v += getattr(st.Class1Record[c1].Class2Record[c2].Value1, "XAdvance", 0) or 0
                break
        self._k[key] = v
        return v

    def layout(self, s: str, px: float, tnum: bool = False) -> tuple[list, float]:
        """x offset of each character (px) and the total advance."""
        font = self.font(px)
        xs, x, prev = [], 0.0, None
        for ch in s:
            if prev is not None and not (tnum and prev.isdigit() and ch.isdigit()):
                x += self.kern(prev, ch) * px / self.upem
            if tnum and ch.isdigit():
                cell = self.tab * px / self.upem
                xs.append(x + (cell - font.getlength(ch)) / 2)
                x += cell
            else:
                xs.append(x)
                x += font.getlength(ch)
            prev = ch
        return xs, x


class Canvas:
    """A frame drawn at K = SS x out_scale px per layout px (layout is 1920 x 1080)."""

    def __init__(self, faces: dict, scale: int = 1, base=None):
        from PIL import Image, ImageDraw
        self.K = SS * scale
        self.F = faces
        self.im = base.copy() if base is not None else Image.new("RGB", (RW * self.K, RH * self.K), (0, 0, 0))
        self.d = ImageDraw.Draw(self.im, "RGBA")

    def text(self, x, y, s, face="400", px=18.0, col=C_WHITE, a=1.0, align="left", tnum=False,
             halo: float = 0.0) -> float:
        """Draw s with its baseline at y; align left / right / center at x; halo = a black keyline (layout px)
        so small type stays legible over the price line. Returns the width (layout px)."""
        if a <= 0.004:
            return self.F[face].layout(s, px, tnum)[1]
        F, K = self.F[face], self.K
        xs, w = F.layout(s, px * K, tnum)
        x0 = x * K - {"left": 0.0, "right": w, "center": w / 2}[align]
        font = F.font(px * K)
        fill = (*col, int(round(255 * min(a, 1.0))))
        if halo > 0:
            hw = max(1, int(round(halo * K)))
            for ch, dx in zip(s, xs):
                if ch != " ":
                    self.d.text((x0 + dx, y * K), ch, font=font, fill=(0, 0, 0, int(255 * min(a, 1.0))),
                                anchor="ls", stroke_width=hw, stroke_fill=(0, 0, 0, int(255 * min(a, 1.0))))
        for ch, dx in zip(s, xs):
            if ch != " ":
                self.d.text((x0 + dx, y * K), ch, font=font, fill=fill, anchor="ls")
        return w / K

    def width(self, s, face="400", px=18.0, tnum=False) -> float:
        return self.F[face].layout(s, px, tnum)[1]

    def dot(self, x, y, r, col, a=1.0):
        K = self.K
        self.d.ellipse([(x - r) * K, (y - r) * K, (x + r) * K, (y + r) * K], fill=(*col, int(255 * min(a, 1))))

    def ring(self, x, y, r, col, a=1.0, w=1.5):
        K = self.K
        self.d.ellipse([(x - r) * K, (y - r) * K, (x + r) * K, (y + r) * K], outline=(*col, int(255 * min(a, 1))),
                       width=max(1, int(round(w * K))))

    def glow(self, x, y, r, col, a=1.0):
        from PIL import Image, ImageFilter
        K = self.K
        key = (r, K)
        if key not in GLOW:
            n = int(r * K * 4)
            m = Image.new("L", (n, n), 0)
            from PIL import ImageDraw
            ImageDraw.Draw(m).ellipse([n * 0.375, n * 0.375, n * 0.625, n * 0.625], fill=255)
            GLOW[key] = m.filter(ImageFilter.GaussianBlur(r * K * 0.45))
        m = GLOW[key]
        n = m.size[0]
        mask = m.point(lambda v: int(v * min(a, 1.0)))
        self.im.paste(Image.new("RGB", (n, n), col), (int(x * K - n / 2), int(y * K - n / 2)), mask)

    def line(self, pts, col, w, a=1.0):
        K = self.K
        if len(pts) > 1:
            self.d.line([(px * K, py * K) for px, py in pts], fill=(*col, int(255 * a)), width=max(1, round(w * K)),
                        joint="curve")

    def rect(self, x0, y0, x1, y1, col, a=1.0):
        K = self.K
        self.d.rectangle([x0 * K, y0 * K, x1 * K - 1, y1 * K - 1], fill=(*col, int(255 * a)))

    def out(self):
        return self.im.reduce(SS)


GLOW: dict = {}


def _ease_out(u):
    u = min(max(u, 0.0), 1.0)
    return 1 - (1 - u) ** 3


def _back_out(u):
    u = min(max(u, 0.0), 1.0)
    c = 1.9
    return 1 + (c + 1) * (u - 1) ** 3 + c * (u - 1) ** 2


def _usd(v: float, cents: bool = True) -> str:
    s = f"{abs(v):,.2f}" if cents else f"{abs(round(v)):,.0f}"
    if round(v, 2 if cents else 0) == 0:
        return "$" + s
    return ("+" if v > 0 else MINUS) + "$" + s


class Scene:
    """Everything the frames need, computed once from match.json."""

    def __init__(self, m: dict):
        self.m = m
        pp = m["price_path"]
        self.ts = np.asarray(pp["ts"], float)
        self.p = np.asarray(pp["p"], float)
        self.t0, self.t1 = float(self.ts[0]), float(self.ts[-1])
        self.X = PL + (self.ts - self.t0) / (self.t1 - self.t0) * (PR - PL)
        self.Y = self.y(self.p)
        # head progress: mild ease (k = 0.35 => ends at 0.65x and middle at 1.35x the mean speed)
        u = np.linspace(0, 1, 20001)
        self.u_grid, self.s_grid = u, u - 0.35 / (2 * np.pi) * np.sin(2 * np.pi * u)
        ev = []
        for c in m["calls"]:
            ts = c["display_clock_ts"]["order_live"]
            fill = c["result"] == "fill"
            p = c["fill_price_outcome0_equiv"] if fill else c["stale_price_outcome0_vwap"]
            ev.append({"n": c["n"], "fill": fill, "ts": ts, "x": self.x(ts), "y": float(self.y(p)),
                       "t": self.reveal(ts), "pnl": float(c["pnl_usd"]), "dir": int(c["jump_dir_outcome0"]),
                       "miss": c["miss_reason"]})
        self.ev = sorted(ev, key=lambda e: e["t"])
        self.fills = [e for e in self.ev if e["fill"]]
        self.total = float(sum(e["pnl"] for e in self.fills))
        assert abs(self.total - m["summary"]["pnl_usd"]) < 0.005, (self.total, m["summary"]["pnl_usd"])
        assert len(self.fills) == m["summary"]["fills"] and len(self.ev) - len(self.fills) == m["summary"]["misses"]
        self.best = max(self.fills, key=lambda e: e["pnl"])
        self.worst = min(self.fills, key=lambda e: e["pnl"])

    def x(self, ts):
        return PL + (ts - self.t0) / (self.t1 - self.t0) * (PR - PL)

    @staticmethod
    def y(p):
        return PT + (1 - np.asarray(p, float)) * (PB - PT)

    def head_ts(self, t: float) -> float:
        u = min(max((t - T_A) / (T_B - T_A), 0.0), 1.0)
        s = u - 0.35 / (2 * np.pi) * np.sin(2 * np.pi * u)
        return self.t0 + s * (self.t1 - self.t0)

    def reveal(self, ts: float) -> float:
        frac = (ts - self.t0) / (self.t1 - self.t0)
        return T_A + float(np.interp(frac, self.s_grid, self.u_grid)) * (T_B - T_A)

    def counter(self, t: float) -> float:
        v = sum(e["pnl"] * _ease_out((t - e["t"]) / RAMP) for e in self.fills if t >= e["t"])
        return self.total if t >= self.fills[-1]["t"] + RAMP else v


def place_labels(cv_faces: dict, sc: Scene) -> list:
    """Transient per-fill labels (settlement P&L, whole dollars), placed on the side away from the price jump,
    in up to three lanes; when every slot near a fill is taken, the older overlapping labels fade out early."""
    px, face = 15.0, "500"
    F = cv_faces[face]
    cap = 0.727 * px
    out = []
    for e in sc.fills:
        s = _usd(e["pnl"], cents=False)
        w = F.layout(s, px)[1]
        pref = 1 if e["dir"] > 0 else -1         # +1 = label below (the price jumped up), -1 = above
        slots = [(pref, 0), (pref, 1), (pref, 2), (-pref, 0), (-pref, 1)]
        t0 = e["t"]
        live = [o for o in out if o["t_end"] > t0]
        chosen, hits = None, None
        for side, lane in slots:
            base = e["y"] + side * (15 + lane * 19) + (cap if side > 0 else 0)
            box = (e["x"] - w / 2 - 4, base - cap - 3, e["x"] + w / 2 + 4, base + 3)
            if box[1] < PT - 24 or box[3] > PB + 6 or box[0] < PL - 4 or box[2] > PR + 30:
                continue
            h = [o for o in live if not (box[2] < o["box"][0] or box[0] > o["box"][2] or box[3] < o["box"][1]
                                         or box[1] > o["box"][3])]
            if not h:
                chosen, hits = (side, lane, base, box), []
                break
            if chosen is None:
                chosen, hits = (side, lane, base, box), h
        side, lane, base, box = chosen
        for o in hits:                           # make room: older overlapping labels fade out now
            o["t_hold"] = min(o["t_hold"], t0)
            o["t_end"] = min(o["t_end"], t0 + 0.12)
        out.append({"s": s, "x": e["x"], "base": base, "side": side, "box": box, "pos": e["pnl"] > 0,
                    "t0": t0, "t_hold": t0 + 0.85, "t_end": t0 + 1.2})
    return out


NOTE_Y = PT + 50                          # best / worst notes sit in the empty band above 79c, with a leader


def _note_pos(sc: Scene, e: dict) -> tuple:
    """Best / worst trade note: value baseline at NOTE_Y above the marker; the leader runs down to the marker."""
    return min(max(e["x"], PL + 80), PR - 80), NOTE_Y


def static_layers(faces: dict, sc: Scene, scale: int):
    """(chrome, label): chrome = title, axes, captions (fades in); label = the hard label (every frame)."""
    m = sc.m
    ch = Canvas(faces, scale)
    lab = Canvas(faces, scale)
    mt = m["match"]
    a, b = mt["outcome0"], mt["outcome1"]
    day = datetime.fromisoformat(mt["start_utc"]).strftime("%-d %B %Y")
    ch.text(112, 116, f"{a} vs {b}", "600", 38, C_WHITE)
    ch.text(112, 152, f"{mt['league']} · {mt['series'].upper()} · {day} · {mt['winner'].split()[-1]} won",
            "400", 21, C_GREY)
    # price grid
    for c in (0, 25, 50, 75, 100):
        yy = float(sc.y(c / 100))
        ch.rect(PL, yy - 0.5, PR, yy + 0.5, C_GRID)
        ch.text(PL - 16, yy + 5, f"{c}¢", "400", 15, C_GREY3, align="right")
    ch.text(PL, PT - 26, f"Polymarket price, {a} to win · every print (real)", "400", 15, C_GREY2)
    # hour ticks (UTC)
    h0 = int(np.ceil(sc.t0 / 3600)) * 3600
    for hts in range(h0, int(sc.t1) + 1, 3600):
        xx = sc.x(hts)
        s = datetime.fromtimestamp(hts, timezone.utc).strftime("%H:%M")
        ch.rect(xx - 0.5, PB + 6, xx + 0.5, PB + 13, C_GREY3)
        ch.text(xx - ch.width(s, "400", 15) / 2, PB + 36, s + (" UTC" if hts + 3600 > sc.t1 else ""), "400", 15,
                C_GREY2)
    # legend labels (the counts are dynamic)
    ch.dot(118, 192, 6, C_ORANGE)
    ch.text(132, 198, "Our fills", "400", 18, C_GREY)
    ch.dot(266, 192, 4.5, C_GREY)
    ch.text(280, 198, "Missed calls", "400", 18, C_GREY)
    # counter captions
    ps = m["profitable_share"]["pooled"]
    ch.text(PR, 98, "Cumulative P&L at settlement · paper", "400", 18, C_GREY, align="right")
    share = (f"{ps['profitable_matches']} of {ps['traded_matches']} traded backtest matches "
             f"({100 * ps['share_profitable']:.1f}%) were profitable at this setting")
    ch.text(PR, 236, share, "400", 18, C_GREY, align="right")
    median = f"Median traded match {_usd(ps['median_match_pnl_usd'])}"
    ch.text(PR, 262, median, "400", 18, C_GREY2, align="right")
    # the hard label: two lines, small grey, bottom left
    l1 = m["label"] + " ·"
    l2 = m["label_share"]
    assert (m["label"] + " · " + l2) == m["label_full"]
    lab.text(112, 1010, l1, "400", 16, C_GREY2)
    lab.text(112, 1034, l2, "400", 16, C_GREY2)
    strings = {"title": f"{a} vs {b}",
               "subtitle": f"{mt['league']} · {mt['series'].upper()} · {day} · {mt['winner'].split()[-1]} won",
               "y_caption": f"Polymarket price, {a} to win · every print (real)",
               "y_ticks": ["0¢", "25¢", "50¢", "75¢", "100¢"],
               "x_ticks_utc": [datetime.fromtimestamp(h, timezone.utc).strftime("%H:%M")
                               for h in range(h0, int(sc.t1) + 1, 3600)],
               "counter_caption": "Cumulative P&L at settlement · paper", "share_line": share,
               "median_line": median, "label_line1": l1, "label_line2": l2}
    return ch, lab, strings


def draw_frame(faces, sc: Scene, labels: list, base, t: float, scale: int = 1, final: bool = False):
    cv = Canvas(faces, scale, base)
    ht = sc.t1 if final else sc.head_ts(t)
    # price line up to the head
    k = int(np.searchsorted(sc.ts, ht, side="right"))
    if k >= 1:
        xs, ys = list(sc.X[:k]), list(sc.Y[:k])
        if k < len(sc.ts):
            f = (ht - sc.ts[k - 1]) / max(sc.ts[k] - sc.ts[k - 1], 1e-9)
            xs.append(float(sc.x(ht)))
            ys.append(float(sc.Y[k - 1] + f * (sc.Y[k] - sc.Y[k - 1])))
        cv.line(list(zip(xs, ys)), C_WHITE, 2.0)
        hx, hy = xs[-1], ys[-1]
    else:
        hx, hy = PL, float(sc.Y[0])
    # markers: misses (grey, behind) then fills (orange, black keyline so the line reads through)
    for e in sc.ev:
        u = 1.0 if final else (t - e["t"]) / 0.32
        if u < 0:
            continue
        r = (6.0 if e["fill"] else 4.0) * _back_out(u)
        if e["fill"]:
            cv.dot(e["x"], e["y"], r + 2.0, (0, 0, 0))
            cv.dot(e["x"], e["y"], r, C_ORANGE)
            if not final and u < 2.2:          # pulse ring
                v = u / 2.2
                cv.ring(e["x"], e["y"], 6.0 + 20 * _ease_out(v), C_ORANGE, 0.55 * (1 - v), 1.6)
        else:
            cv.dot(e["x"], e["y"], r + 1.5, (0, 0, 0))
            cv.dot(e["x"], e["y"], r, C_GREY, 0.85)
    # transient per-fill labels
    if not final:
        for L in labels:
            if not (L["t0"] <= t < L["t_end"]):
                continue
            a = min((t - L["t0"]) / 0.12, 1.0)
            if t > L["t_hold"]:
                a *= max(0.0, 1 - (t - L["t_hold"]) / max(L["t_end"] - L["t_hold"], 1e-6))
            drift = 5 * (1 - _ease_out((t - L["t0"]) / 0.3)) * (-L["side"])
            cv.text(L["x"], L["base"] + drift, L["s"], "500", 15, C_ORANGE if L["pos"] else (200, 200, 205),
                    a * (1.0 if L["pos"] else 0.85), align="center", halo=2.0)
    # head
    if not final and t < T_END_HEAD and t >= T_A - 0.2:
        a = min((t - (T_A - 0.2)) / 0.2, 1.0) * (1.0 if t < T_B else max(0.0, 1 - (t - T_B) / (T_END_HEAD - T_B)))
        cv.glow(hx, hy, 14, C_WHITE, 0.55 * a)
        cv.dot(hx, hy, 4.5, C_WHITE, a)
    # best / worst trade notes
    na = 1.0 if final else min(max((t - T_NOTE) / 0.6, 0.0), 1.0)
    if na > 0:
        na = _ease_out(na)
        for e, word, col in ((sc.best, "best trade", C_ORANGE), (sc.worst, "worst trade", C_WHITE)):
            cv.ring(e["x"], e["y"], 11, col, 0.9 * na, 1.6)
            x, y = _note_pos(sc, e)
            y0, y1 = y + 30, e["y"] - 13
            cv.rect(e["x"] - 0.5, y0 + (y1 - y0) * (1 - na), e["x"] + 0.5, y1, C_GREY, 0.6 * na)
            cv.text(x, y, _usd(e["pnl"]), "600", 20, col, na, align="center")
            cv.text(x, y + 20, word, "400", 15, C_GREY, na, align="center")
    # counter, legend counts
    a = 1.0 if final else min(t / T_FADE, 1.0)
    val = sc.total if final else sc.counter(t)
    cv.text(PR, 196, _usd(val), "600", 84, C_WHITE, a, align="right", tnum=True)
    nf = len(sc.fills) if final else sum(1 for e in sc.fills if e["t"] <= t)
    nm = (len(sc.ev) - len(sc.fills)) if final else sum(1 for e in sc.ev if not e["fill"] and e["t"] <= t)
    cv.text(132 + cv.width("Our fills", "400", 18) + 8, 198, str(nf), "500", 18, C_WHITE, a, tnum=True)
    cv.text(280 + cv.width("Missed calls", "400", 18) + 8, 198, str(nm), "500", 18, C_WHITE, a, tnum=True)
    return cv


def render(argv: list):
    import argparse
    import hashlib
    import subprocess
    from PIL import Image, ImageChops
    ap = argparse.ArgumentParser(prog="backtest_example_match.py render")
    ap.add_argument("--at", type=float, default=None, help="render one frame at this time (s) to --out")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    src = OUTDIR / "match.json"
    m = json.loads(src.read_text())
    faces = {w: Face(f"Inter_{n}.ttf") for w, n in (("400", "400Regular"), ("500", "500Medium"),
                                                     ("600", "600SemiBold"))}
    sc = Scene(m)
    labels = place_labels(faces, sc)

    def bases(scale):
        ch, lab, strings = static_layers(faces, sc, scale)
        return ch.im, lab.im, strings

    chrome, lab, strings = bases(1)
    full = ImageChops.add(chrome, lab)
    black = Image.new("RGB", chrome.size, (0, 0, 0))

    def base_at(t):
        if t >= T_FADE:
            return full
        return ImageChops.add(Image.blend(black, chrome, _ease_out(t / T_FADE)), lab)

    if args.at is not None:
        img = draw_frame(faces, sc, labels, base_at(args.at), args.at).out()
        img.save(args.out or str(OUTDIR / f"preview_{args.at:.2f}.png"))
        return

    n = int(round(DUR * FPS))
    mp4 = OUTDIR / "example_match.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}",
           "-r", str(FPS), "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-c:v", "libx264",
           "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries",
           "bt709", "-color_trc", "bt709", "-movflags", "+faststart", "-tag:v", "avc1", str(mp4)]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        t = i / FPS
        pr.stdin.write(draw_frame(faces, sc, labels, base_at(t), t).out().tobytes())
        if i % 60 == 0:
            print(f"frame {i}/{n}", flush=True)
    pr.stdin.close()
    assert pr.wait() == 0
    # the 300 dpi still: the final state at 2x (3840 x 2160 px = 12.8 x 7.2 in at 300 dpi)
    ch2, lab2, _ = bases(2)
    still = draw_frame(faces, sc, labels, ImageChops.add(ch2, lab2), DUR, scale=2, final=True).out()
    png = OUTDIR / "example_match.png"
    still.save(png, dpi=(300, 300), optimize=True)
    ps = m["profitable_share"]["pooled"]
    onscreen = {
        "label": m["label"], "label_full": m["label_full"],
        "label_on_every_frame": True, "label_lines": [strings["label_line1"], strings["label_line2"]],
        "outputs": {"video": str(mp4.relative_to(ROOT)), "still": str(png.relative_to(ROOT)),
                    "video_spec": f"{RW}x{RH}, {FPS} fps, {DUR:g} s ({n} frames), H.264 yuv420p bt709",
                    "still_spec": f"{still.size[0]}x{still.size[1]} px, 300 dpi (final state)"},
        "source": {"match_json": str(src.relative_to(ROOT)),
                   "match_json_sha256": hashlib.sha256(src.read_bytes()).hexdigest()},
        "on_screen": {**strings,
                      "counter_final": _usd(sc.total), "counter_start": _usd(0.0),
                      "legend_final": {"Our fills": len(sc.fills), "Missed calls": len(sc.ev) - len(sc.fills)},
                      "best_trade": [_usd(sc.best["pnl"]), "best trade"],
                      "worst_trade": [_usd(sc.worst["pnl"]), "worst trade"],
                      "per_fill_labels": "transient, settlement P&L of each fill in whole dollars, in fill order: "
                                         + ", ".join(L["s"] for L in labels)},
        "what_is_drawn": {
            "line": "every Polymarket print of the match's in-play tape (real), outcome-0 price, linear between prints",
            "orange_dot": "a modelled fill (paper): x = order live time on the display clock (the modelled book "
                          "reprice put at the historical jump onset; display assumption, see match.json fields), "
                          "y = fill price on the outcome-0 axis (1 - price for an outcome-1 buy)",
            "grey_dot": "a missed call (order did not fill): y = stale outcome-0 VWAP before the jump",
            "counter": "cumulative settlement P&L of the fills shown so far (each position held to the match "
                       "result), rolling over 0.3 s per fill; ends exactly at the match P&L",
            "per_fill_labels": "settlement P&L of the fill, whole dollars; orange if > 0, light grey if < 0; a "
                               "correct call on the eventual loser's point loses at settlement",
            "timing": f"chrome fades in over {T_FADE} s (label at full opacity from frame 0); line draws "
                      f"{T_A}-{T_B} s with a mild ease; best / worst notes from {T_NOTE} s; hold to {DUR:g} s"},
        "numbers": {"pnl_usd": m["summary"]["pnl_usd"], "fills": m["summary"]["fills"],
                    "misses": m["summary"]["misses"], "calls": m["summary"]["calls"],
                    "profitable_share_pooled": ps["share_profitable"],
                    "profitable_matches": ps["profitable_matches"], "traded_matches": ps["traded_matches"],
                    "median_match_pnl_usd": ps["median_match_pnl_usd"]},
        "render": {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "script": "scripts/backtest_example_match.py render",
                   "font": "Inter (SIL OFL 1.1), results/viz/v60_assets/fonts/"},
    }
    (OUTDIR / "example_match_onscreen.json").write_text(json.dumps(onscreen, indent=1, ensure_ascii=False))
    print(json.dumps(onscreen["on_screen"], indent=1, ensure_ascii=False))


if __name__ == "__main__":
    if sys.argv[1:2] == ["render"]:
        render(sys.argv[2:])
    else:
        main()
