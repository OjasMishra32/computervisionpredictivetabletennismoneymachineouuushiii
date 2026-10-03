"""Latency lens analysis: which public tennis score source is fastest, and does any beat the book?

Inputs: data/live_v2 recordings from research/v2/latency/recorder.py (live forward data, used
only to measure latency; no trading rule is tuned on it).

For every score change ("unit": a point or a game) seen by a source we find the matching
moneyline reprice on Polymarket and report lead = t_book - t_source (seconds; > 0 means the
source saw it first). Two book-matching methods:

  M1 (official clock, WTA matches only): the WTA point-by-point log stamps every point with the
     official scoring time T_p. The book reprice for point p is the half-move crossing time of
     the outcome-0 mid inside [T_p - min(10, gap/2), T_p + min(25, gap_next - 4)], in the point
     winner's direction (fallback: first >= 1 tick move). Each source's observation of that
     point (or of the game it ended) gets lead = t_book - t_source, and delay = t_source - T_p.
  M2 (source clock, every match): the biggest implied-direction mid move (3 s horizon) in
     [t_source - 90 s, t_source + 30 s]; onset = first update reaching half of that move.

Also: (i) cross-market lag (side markets vs moneyline) around every M1 reprice, (ii) depth
resting at stale prices just before the reprice and at t_source + 1.3 s.

    python research/v2/latency/analyze.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load as L  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
DELAY_S = 1.3          # 1 s venue order delay + 0.3 s network/processing
FEE_RATE = 0.05


# ----------------------------------------------------------------------------- reprice detection
def reprice_window(t, mid, A, d, lo, hi, tick):
    """Half-move crossing of mid in direction d within [A+lo, A+hi] (ms). Returns dict or None."""
    if len(t) == 0:
        return None
    i0 = np.searchsorted(t, A + lo, "right") - 1
    j1 = np.searchsorted(t, A + hi, "right") - 1
    if i0 < 0 or j1 <= i0:
        return None
    m0, m1 = mid[i0], mid[j1]
    D = (m1 - m0) * d
    seg, ts = mid[i0 + 1:j1 + 1], t[i0 + 1:j1 + 1]
    mv = (seg - m0) * d
    out = {"m0": m0, "m1": m1, "D": D, "ok": bool(D >= tick - 1e-9), "exc": float(np.max(mv)) if len(mv) else 0.0}
    if not out["ok"]:
        return out
    thr = max(tick, 0.5 * D)
    out["t_half"] = float(ts[np.argmax(mv >= thr - 1e-9)])
    out["t_first"] = float(ts[np.argmax(mv >= tick - 1e-9)])
    return out


def biggest_move(t, mid, A, d, tick, lo=-90_000, hi=30_000, H=3_000):
    if len(t) == 0:
        return None
    a = np.searchsorted(t, A + lo, "left")
    b = np.searchsorted(t, A + hi, "right")
    if b - a < 1:
        return None
    best_g, best_i = -np.inf, None
    for i in range(max(a, 1), b):
        prev = mid[i - 1]
        j = np.searchsorted(t, t[i] + H, "right")
        g = np.max((mid[i:j] - prev) * d)
        if g > best_g + 1e-12:
            best_g, best_i = g, i
    if best_i is None or best_g < tick - 1e-9:
        return {"ok": False, "D": best_g}
    prev = mid[best_i - 1]
    j = np.searchsorted(t, t[best_i] + H, "right")
    mv = (mid[best_i:j] - prev) * d
    k = int(np.argmax(mv >= max(tick, 0.5 * best_g) - 1e-9))
    return {"ok": True, "D": float(best_g), "t_half": float(t[best_i + k]), "t_first": float(t[best_i])}


def detect_jumps(t, mid, thr=0.01, H=2000, sep=10_000):
    """Moneyline jumps: mid moves >= thr within H ms; returns (t_half, direction, size), >= sep apart."""
    out = []
    if len(t) < 3:
        return out
    last = -np.inf
    i = 1
    n = len(t)
    while i < n:
        if t[i] < last + sep:
            i += 1
            continue
        j = np.searchsorted(t, t[i] + H, "right")
        mv = mid[i:j] - mid[i - 1]
        k = int(np.argmax(np.abs(mv)))
        if abs(mv[k]) >= thr - 1e-9:
            dirn = 1 if mv[k] > 0 else -1
            h = int(np.argmax(mv * dirn >= 0.5 * abs(mv[k]) - 1e-9))
            out.append((float(t[i + h]), dirn, float(abs(mv[k]))))
            last = t[i + h]
            i = j
        else:
            i += 1
    return out


def qstats(x) -> dict:
    x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
    if len(x) == 0:
        return {"n": 0}
    return {"n": int(len(x)), "median": round(float(np.median(x)), 2), "p10": round(float(np.percentile(x, 10)), 2),
            "p25": round(float(np.percentile(x, 25)), 2), "p75": round(float(np.percentile(x, 75)), 2),
            "p90": round(float(np.percentile(x, 90)), 2), "mean": round(float(np.mean(x)), 2),
            "share_gt_1p3": round(float(np.mean(x > DELAY_S)), 3), "share_gt_0": round(float(np.mean(x > 0)), 3)}


def drop_post_outage(U: pd.DataFrame):
    """A change first seen right after a recording outage carries a late timestamp by construction.
    pm_sports (push, ~32 s per game): drop if the feed (all tennis games, both recorders) was silent
    > 60 s before it. Polled sources (2-4 s): drop if no successful poll of that source in the 10 s before."""
    if U.empty:
        return U, {}
    pm_t = np.unique(np.array([r["rt"] for r in L.read("pmsports") if "gameId" in r] +
                              [r["rt"] for r in L.read("sports", L.LEGACY) if "gameId" in r], dtype=float))
    polls = defaultdict(list)
    for r in L.read("polls"):
        if r.get("code") == 200:
            fam = {"espn_atp": "espn", "espn_wta": "espn", "wta_list": "wta", "wta_score": "wta"}.get(r.get("src"))
            if fam:
                polls[fam].append(r["rt"])
    polls = {k: np.unique(np.array(v, dtype=float)) for k, v in polls.items()}
    def resumes(arr, lim):
        if len(arr) < 2:
            return np.empty(0)
        g = np.diff(arr)
        return arr[1:][g > lim]          # first message/poll after each silence longer than lim

    res_pm = np.append(resumes(pm_t, 60_000), pm_t[:1])
    res_poll = {k: np.append(resumes(v, 10_000), v[:1]) for k, v in polls.items()}
    keep = []
    for r in U.itertuples():
        if r.src == "pm_sports":
            ends, lim = res_pm, 60_000
        else:
            ends, lim = res_poll.get(r.src, np.empty(0)), 10_000
        keep.append(not bool(np.any((r.rt >= ends) & (r.rt <= ends + lim))))
    keep = np.array(keep)
    return U[keep].reset_index(drop=True), U[~keep].groupby("src").size().astype(int).to_dict()


def dedupe_units(units: list[dict]) -> pd.DataFrame:
    U = pd.DataFrame(units)
    if U.empty:
        return U
    U = U[~U.amb].copy()
    U["pa"] = U["pa"].astype(object).where(U["pa"].notna(), None)
    U["pb"] = U["pb"].astype(object).where(U["pb"].notna(), None)
    U["ukey"] = U.apply(lambda r: f'{r.slug}|{r.set}|{r.game}|{r.level}|{r.pa}|{r.pb}', axis=1)
    U = U.sort_values("rt").drop_duplicates(["src", "ukey"], keep="first")
    return U.reset_index(drop=True)


# ----------------------------------------------------------------------------- main analysis
def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    meta = L.load_meta()
    ev = L.events_table(meta)
    evd = ev.set_index("slug")
    pm_u, leagues = L.pm_sports_units(ev)
    es_u = L.espn_units(ev)
    wt_u, pbp, winfo = L.wta_units(ev)
    U = dedupe_units(pm_u + es_u + wt_u)
    U, n_drop = drop_post_outage(U)
    print("units dropped as post-outage (late by construction):", n_drop)
    P = pd.DataFrame(pbp)
    print(f"units: {U.groupby('src').size().to_dict() if len(U) else {}}  pbp points: {len(P)}")

    slugs = set(U.slug) | (set(P.slug.dropna()) if len(P) else set()) | set(ev[(ev.src_meta == "v2") & ~ev.doubles].slug)
    ev_i = ev[ev.slug.isin(slugs)]
    side = meta[meta.slug.isin(slugs) & (meta.smt != "moneyline") & (meta.oi == 0)].drop_duplicates("tok")
    toks = set(ev_i.tok0) | set(ev_i.tok1) | set(side.tok)
    books = L.Books(toks, set(ev_i.tok0) | set(side.tok), dict(zip(meta.ra, meta.tok)))
    mids = {tk: books.mid_series(tk) for tk in ev_i.tok0}
    # tick: 0.001 if any observed quote is off the 1c grid, else the market's listed tick
    for tk in ev_i.tok0:
        arr = books.top.get(tk)
        if arr is not None and len(arr):
            q = arr[:, 1:3][np.isfinite(arr[:, 1:3])] * 100
            if len(q) and np.any(np.abs(q - np.round(q)) > 1e-6):
                ev.loc[ev.tok0 == tk, "tick"] = 0.001
    evd = ev.set_index("slug")
    print("book tokens loaded:", len(books.top))

    # ---------------------------------------------------------------- M1: official clock (WTA pbp)
    m1_rows = []
    if len(P):
        P = P[P.slug.notna() & P.winner.notna() & np.isfinite(P["T"])].sort_values(["key", "n"]).reset_index(drop=True)
        for key, g in P.groupby("key"):
            g = g.sort_values("n")
            T = g["T"].to_numpy() * 1000
            for i, r in enumerate(g.itertuples()):
                e = evd.loc[r.slug]
                t, mid, _, _ = mids[e.tok0]
                d = 1 if r.winner == 0 else -1
                gap_prev = (T[i] - T[i - 1]) if i > 0 else 20_000
                gap_next = (T[i + 1] - T[i]) if i + 1 < len(T) else 25_000
                lo = -min(10_000, 0.5 * gap_prev)
                hi = min(25_000, gap_next - 4_000)   # the book anticipates the NEXT official stamp by up to ~4 s
                rp = reprice_window(t, mid, T[i], d, lo, hi, e.tick)
                rp_wrong = reprice_window(t, mid, T[i], -d, lo, hi, e.tick)   # placebo: loser's direction
                cov = len(t) > 0 and (t[0] + 60_000 <= T[i] <= t[-1] - 30_000)
                row = {"key": key, "slug": r.slug, "n": r.n, "set": r.set, "game": r.game, "ga": r.ga, "gb": r.gb,
                       "covered": bool(cov),
                       "game_end": r.game_end, "winner": r.winner, "T_ms": T[i], "rt_pbp_seen": r.rt_seen,
                       "first_poll": r.first_poll, "gap_prev_s": gap_prev / 1000, "gap_next_s": gap_next / 1000}
                if rp_wrong is not None:
                    row["exc_wrong"] = rp_wrong["exc"]
                if rp is not None:
                    row["exc_right"] = rp["exc"]
                if rp is not None:
                    row.update({"D": rp["D"], "ok": rp["ok"], "m0": rp["m0"], "tick": e.tick})
                    if rp["ok"]:
                        row.update({"t_book": rp["t_half"], "t_book_first": rp["t_first"],
                                    "book_vs_T_s": (rp["t_half"] - T[i]) / 1000,
                                    "book1_vs_T_s": (rp["t_first"] - T[i]) / 1000})
                m1_rows.append(row)
    M1 = pd.DataFrame(m1_rows)
    if len(M1):
        M1["pbp_delay_s"] = (M1.rt_pbp_seen - M1.T_ms) / 1000
    M1.to_csv(OUT / "m1_points.csv", index=False)

    # map source units onto pbp points
    src_rows = []
    if len(M1) and len(U):
        for r in U.itertuples():
            g = M1[M1.slug == r.slug]
            if g.empty:
                continue
            if r.level == "game":
                c = g[(g.set == r.set) & (g.game == r.game) & g.game_end]
            else:
                c = g[(g.set == r.set) & (g.game == r.game) & (g.ga == r.pa) & (g.gb == r.pb)]
            c = c[c.T_ms <= r.rt + 2000]
            if c.empty:
                continue
            p = c.iloc[-1]
            row = {"src": r.src, "via": getattr(r, "via", None), "slug": r.slug, "level": r.level, "rt": r.rt,
                   "n": p.n, "T_ms": p.T_ms, "src_vs_T_s": (r.rt - p.T_ms) / 1000,
                   "winner_ok": bool(p.winner == r.winner)}
            if p.get("ok") is True or p.get("ok") == 1.0:
                row.update({"t_book": p.t_book, "lead_s": (p.t_book - r.rt) / 1000,
                            "lead_first_s": (p.t_book_first - r.rt) / 1000, "D": p.D})
            src_rows.append(row)
    S1 = pd.DataFrame(src_rows)
    S1.to_csv(OUT / "m1_source_leads.csv", index=False)

    # ---------------------------------------------------------------- M2: source clock, all matches
    m2_rows = []
    for r in U.itertuples():
        e = evd.loc[r.slug]
        t, mid, _, _ = mids[e.tok0]
        d = 1 if r.winner == 0 else -1
        bm = biggest_move(t, mid, r.rt, d, e.tick)
        row = {"src": r.src, "slug": r.slug, "level": r.level, "rt": r.rt, "set": r.set, "game": r.game,
               "series": r.slug.split("-")[0]}
        if bm and bm["ok"]:
            row.update({"lead_s": (bm["t_half"] - r.rt) / 1000, "D": bm["D"]})
        else:
            row.update({"lead_s": np.nan, "D": bm["D"] if bm else np.nan})
        m2_rows.append(row)
    M2 = pd.DataFrame(m2_rows)
    M2.to_csv(OUT / "m2_source_leads.csv", index=False)

    # ---------------------------------------------------------------- source vs source (same unit)
    pair_rows = []
    if len(U):
        gu = U[U.level == "game"].copy()
        gu["gkey"] = gu.slug + "|" + gu.set.astype(str) + "|" + gu.game.astype(str)
        wide = gu.pivot_table(index="gkey", columns="src", values="rt", aggfunc="min")
        for a in wide.columns:
            for b in wide.columns:
                if a < b:
                    x = ((wide[b] - wide[a]) / 1000).dropna()
                    if len(x):
                        pair_rows.append({"a": a, "b": b, "n": len(x), "median_b_minus_a_s": round(float(x.median()), 2),
                                          "p10": round(float(x.quantile(.1)), 2), "p90": round(float(x.quantile(.9)), 2),
                                          "share_a_first": round(float((x > 0).mean()), 3),
                                          "share_a_stalled_gt_120s": round(float((x < -120).mean()), 3),
                                          "share_b_stalled_gt_120s": round(float((x > 120).mean()), 3),
                                          "median_excl_stalls": round(float(x[abs(x) <= 120].median()), 2) if (abs(x) <= 120).any() else None})
    pairs = pd.DataFrame(pair_rows)

    # ---------------------------------------------------------------- (i) cross-market lag
    # anchor = every moneyline jump detected on the book (all singles matches with side-market books),
    # side reprice = half-move crossing in [t_ml - 5 s, t_ml + 30 s]; also stale side depth at t_ml + 1.3 s.
    v2_first = min((a[0, 0] for tk, a in books.top.items() if tk in set(side.tok)), default=np.inf)
    v2_last = max((a[-1, 0] for tk, a in books.top.items() if tk in set(side.tok)), default=-np.inf)
    side_by_slug = {sl: g for sl, g in side.groupby("slug")}
    jumps = []
    for e in ev_i[~ev_i.doubles].itertuples():
        if e.slug not in side_by_slug:
            continue
        t, mid, _, _ = mids[e.tok0]
        for jt, jd, js in detect_jumps(t, mid, thr=0.01, H=2000, sep=10_000):
            if v2_first + 60_000 <= jt <= v2_last - 30_000:
                jumps.append((e.slug, jt, jd, js))
    pbp_t = M1[M1.ok == True][["slug", "t_book"]] if len(M1) else pd.DataFrame(columns=["slug", "t_book"])  # noqa: E712
    xm_rows = []
    for slug, jt, jd, js in jumps:
        e = evd.loc[slug]
        near_pt = pbp_t[(pbp_t.slug == slug) & (abs(pbp_t.t_book - jt) < 3000)]
        for sm in side_by_slug[slug].itertuples():
            ts, ms, _, _ = books.mid_series(sm.tok, max_spread=0.10)
            if len(ts) == 0 or ts[0] > jt - 5000:
                continue
            i0 = np.searchsorted(ts, jt - 5000, "right") - 1
            if i0 < 0 or ms[i0] < 0.03 or ms[i0] > 0.97:     # dead / decided side market
                continue
            oc = L.norm(str(sm.outcome))
            rel = 1 if oc == L.norm(e.n0) else (-1 if oc == L.norm(e.n1) else 0)
            tick = float(sm.tick or 0.01)
            if rel:
                rp = reprice_window(ts, ms, jt, jd * rel, -5000, 30_000, tick)
                ds = jd * rel
            else:
                ru = reprice_window(ts, ms, jt, 1, -5000, 30_000, tick)
                rd = reprice_window(ts, ms, jt, -1, -5000, 30_000, tick)
                rp, ds = (ru, 1) if (ru and ru.get("ok")) else (rd, -1)
            row = {"slug": slug, "t_ml": jt, "ml_move": js, "smt": sm.smt, "tok": sm.tok, "dir_known": rel != 0,
                   "m0": float(ms[i0]), "moved": bool(rp and rp.get("ok")), "pbp_point": len(near_pt) > 0}
            if rp and rp.get("ok"):
                row["lag_s"] = (rp["t_half"] - jt) / 1000
                row["lag_first_s"] = (rp["t_first"] - jt) / 1000
                row["D"] = rp["D"]
                if row["lag_s"] > DELAY_S:
                    k = np.searchsorted(ts, rp["t_half"] + 3000, "right") - 1
                    nb, na = top_at(books, sm.tok, rp["t_half"] + 3000)
                    sd = stale_depth(books, sm.tok, jt + DELAY_S * 1000, ds, ms[k], nb if ds > 0 else na)
                    row.update({f"stale_{kk}": v for kk, v in sd.items()})
            xm_rows.append(row)
    XM = pd.DataFrame(xm_rows)
    XM.to_csv(OUT / "cross_market.csv", index=False)
    print("ml jumps for cross-market:", len(jumps), "pairs:", len(XM))

    # ---------------------------------------------------------------- (ii) depth at stale prices
    dep_rows = []
    if len(M1):
        ok = M1[M1.ok == True]  # noqa: E712
        for r in ok.itertuples():
            e = evd.loc[r.slug]
            d = 1 if r.winner == 0 else -1
            t, mid, _, _ = mids[e.tok0]
            j = np.searchsorted(t, r.t_book + 3000, "right") - 1
            m_new = mid[j] if j >= 0 else np.nan
            row = {"slug": r.slug, "n": r.n, "D": r.D, "m_new": m_new, "game_end": r.game_end}
            nb, na = top_at(books, e.tok0, r.t_book + 3000)
            for lab, tq in (("pre2s", r.t_book - 2000), ("pre1s", r.t_book - 1000), ("pre", r.t_book - 250),
                            ("post", r.t_book + 500)):
                row.update({f"{k}_{lab}": v for k, v in
                            stale_depth(books, e.tok0, tq, d, m_new, nb if d > 0 else na).items()})
            dep_rows.append(row)
    DEP = pd.DataFrame(dep_rows)
    DEP.to_csv(OUT / "stale_depth.csv", index=False)
    # stale depth at t_source + 1.3 s for source observations (what a source-driven taker would meet)
    sd_rows = []
    if len(S1) and "t_book" in S1:
        # only meaningful when the source actually leads (otherwise the book has already repriced)
        for r in S1[S1.t_book.notna() & (S1.lead_s > DELAY_S)].itertuples():
            e = evd.loc[r.slug]
            mrow = M1[(M1.slug == r.slug) & (M1.n == r.n)].iloc[0]
            d = 1 if mrow.winner == 0 else -1
            t, mid, _, _ = mids[e.tok0]
            j = np.searchsorted(t, r.t_book + 3000, "right") - 1
            m_new = mid[j] if j >= 0 else np.nan
            sd = stale_depth(books, e.tok0, r.rt + DELAY_S * 1000, d, m_new)
            sd_rows.append({"src": r.src, "lead_s": r.lead_s, **sd})
    SD = pd.DataFrame(sd_rows)

    TT = trade_timing(M1, evd, books, mids)
    TT.to_csv(OUT / "trades_around_reprice.csv", index=False)
    res = summarise(U, P, M1, S1, M2, pairs, XM, DEP, SD, books, leagues, winfo)
    res["trades_around_reprice"] = trade_timing_summary(TT)
    res["cadence"] = cadence()
    sp_rows = []
    for r in pd.concat([side[["tok", "smt", "slug"]],
                        ev_i[~ev_i.doubles & (ev_i.src_meta == "v2")].rename(columns={"tok0": "tok"}).assign(smt="moneyline")[["tok", "smt", "slug"]]]).itertuples():
        a = books.top.get(r.tok)
        if r.slug not in set(XM.slug if len(XM) else []) or a is None or not len(a):
            continue
        sp = a[:, 2] - a[:, 1]
        okq = np.isfinite(sp) & (a[:, 1] > 0) & (a[:, 2] < 1)
        if okq.any():
            sp_rows.append({"smt": r.smt, "med_spread": float(np.median(sp[okq])), "n_updates": int(len(a))})
    if sp_rows:
        spd = pd.DataFrame(sp_rows).groupby("smt").agg(n_markets=("smt", "size"), median_spread=("med_spread", "median"),
                                                       median_quote_updates=("n_updates", "median"))
        res["side_market_spreads_live"] = spd.round(4).to_dict("index")
    res["recording"]["units_dropped_post_outage"] = n_drop
    (OUT / "summary.json").write_text(json.dumps(res, indent=1, default=float))
    write_results(res)
    plots(M1, S1, M2, XM)
    return res


def top_at(books: L.Books, tok: str, t: float):
    arr = books.top.get(tok)
    if arr is None or not len(arr):
        return np.nan, np.nan
    i = np.searchsorted(arr[:, 0], t, "right") - 1
    return (arr[i, 1], arr[i, 2]) if i >= 0 else (np.nan, np.nan)


def stale_depth(books: L.Books, a: str, tq: float, d: int, m_new: float, exit_px: float = np.nan) -> dict:
    """Shares/$ resting at prices that are stale relative to the post-reprice mid m_new, and the
    gross/net (5% fee) edge from sweeping them. d=+1: buy asks below m_new; d=-1: sell bids above.
    net_usd values the position at m_new (hold, one taker fee); net_exit_usd exits immediately at the
    post-reprice opposite touch exit_px (two taker fees) -- the conservative number."""
    bids, asks = books.book_at(a, tq)
    if not np.isfinite(m_new):
        return {"sh": np.nan, "usd": np.nan, "edge_usd": np.nan, "net_usd": np.nan, "touch_sh": np.nan,
                "net_exit_usd": np.nan}
    if d > 0:
        lv = sorted((p, s) for p, s in asks.items() if p < m_new)
        edge = [(m_new - p) for p, _ in lv]
        touch = lv[0][1] if lv else 0.0
    else:
        lv = sorted(((p, s) for p, s in bids.items() if p > m_new), reverse=True)
        edge = [(p - m_new) for p, _ in lv]
        touch = lv[0][1] if lv else 0.0
    sh = sum(s for _, s in lv)
    usd = sum(p * s if d > 0 else (1 - p) * s for p, s in lv)
    gross = sum(s * x for (_, s), x in zip(lv, edge))
    fee = sum(s * FEE_RATE * p * (1 - p) for p, s in lv)
    if np.isfinite(exit_px):
        ex = sum(s * ((exit_px - p) * d - FEE_RATE * p * (1 - p) - FEE_RATE * exit_px * (1 - exit_px)) for p, s in lv)
    else:
        ex = np.nan
    return {"sh": sh, "usd": usd, "edge_usd": gross, "net_usd": gross - fee, "touch_sh": touch, "net_exit_usd": ex}


def summarise(U, P, M1, S1, M2, pairs, XM, DEP, SD, books, leagues, winfo) -> dict:
    res = {"recording": {}, "sources": {}, "m1": {}, "m2": {}, "pairs": pairs.to_dict("records"),
           "cross_market": {}, "stale_depth": {}}
    rts = [x[0] for a in books.top.values() for x in a[[0, -1]]] if books.top else []
    if rts:
        res["recording"] = {"book_first_utc": pd.Timestamp(min(rts), unit="ms").isoformat(),
                            "book_last_utc": pd.Timestamp(max(rts), unit="ms").isoformat(),
                            "hours": round((max(rts) - min(rts)) / 3.6e6, 2)}
    res["recording"].update({"n_units_by_src": {f"{k[0]}:{k[1]}": int(v) for k, v in
                                                U.groupby(["src", "level"]).size().items()} if len(U) else {},
                             "n_matches_by_src": U.groupby("src").slug.nunique().astype(int).to_dict() if len(U) else {},
                             "pm_sports_leagues_msgs": leagues, **winfo,
                             "n_pbp_points": int(len(P)),
                             "n_pbp_matches": int(P.key.nunique()) if len(P) else 0})
    if len(M1):
        ok = M1[M1.ok == True]  # noqa: E712
        res["m1"]["book_vs_official_T_s"] = qstats(ok.book_vs_T_s)
        res["m1"]["book_first_tick_vs_official_T_s"] = qstats(ok.book1_vs_T_s)
        res["m1"]["book_vs_official_T_s_game_end"] = qstats(ok[ok.game_end == True].book_vs_T_s)  # noqa: E712
        res["m1"]["book_vs_official_T_s_D_ge_1c"] = qstats(ok[ok.D >= 0.01].book_vs_T_s)
        res["m1"]["book_vs_official_T_s_D_ge_3c"] = qstats(ok[ok.D >= 0.03].book_vs_T_s)
        cov = M1[M1.covered == True]  # noqa: E712
        res["m1"]["placebo"] = {"median_max_excursion_winner_dir_c": round(float(cov.exc_right.median() * 100), 2),
                                "median_max_excursion_loser_dir_c": round(float(cov.exc_wrong.median() * 100), 2),
                                "share_net_move_toward_winner": round(float((cov.D > 0).mean()), 3),
                                "share_net_move_toward_loser": round(float((cov.D < 0).mean()), 3)}
        res["m1"]["by_match"] = {k: qstats(g.book_vs_T_s) for k, g in ok.groupby("slug")}
        cov = M1[M1.covered == True]  # noqa: E712
        res["m1"]["n_points_with_book_coverage"] = int(len(cov))
        res["m1"]["share_covered_points_with_reprice"] = round(float((cov.ok == True).mean()), 3) if len(cov) else None  # noqa: E712
        res["m1"]["n_matches_with_reprices"] = int(ok.slug.nunique())
        live_pbp = M1[M1.first_poll == False]  # noqa: E712
        res["m1"]["pbp_endpoint_delay_s"] = qstats(live_pbp.pbp_delay_s)
    if len(S1):
        for (src, lev), g in S1.groupby(["src", "level"]):
            res["m1"][f"{src}:{lev}"] = {"source_delay_vs_official_T_s": qstats(g.src_vs_T_s),
                                         "lead_vs_book_s": qstats(g.lead_s) if "lead_s" in g else {"n": 0},
                                         "winner_agrees_with_pbp": round(float(g.winner_ok.mean()), 3)}
        for src, g in S1.groupby("src"):
            res["m1"][f"{src}:all"] = {"source_delay_vs_official_T_s": qstats(g.src_vs_T_s),
                                       "lead_vs_book_s": qstats(g.lead_s) if "lead_s" in g else {"n": 0}}
    if len(M2):
        for (src, lev), g in M2.groupby(["src", "level"]):
            res["m2"][f"{src}:{lev}"] = {**qstats(g.lead_s), "n_units": int(len(g)),
                                         "share_no_book_move": round(float(g.lead_s.isna().mean()), 3)}
        for (src, ser), g in M2.groupby(["src", "series"]):
            res["m2"][f"{src}:series={ser}"] = qstats(g.lead_s)
    if len(XM):
        res["cross_market"]["n_ml_jumps"] = int(XM.groupby(["slug", "t_ml"]).ngroups)
        res["cross_market"]["n_matches"] = int(XM.slug.nunique())
        allm = XM[XM.moved]
        res["cross_market"]["all_side_markets"] = {"n_pairs": int(len(XM)), "share_side_moved": round(float(XM.moved.mean()), 3),
                                                   "lag_half_s": qstats(allm.lag_s) if len(allm) else {"n": 0},
                                                   "lag_first_tick_s": qstats(allm.lag_first_s) if len(allm) else {"n": 0}}
        hrs = (XM.t_ml.max() - XM.t_ml.min()) / 3.6e6
        res["cross_market"]["hours_covered"] = round(float(hrs), 2)
        for cut, g in (("ml_jump_ge_3c", XM[XM.ml_move >= 0.03]), ("ml_jump_at_wta_point", XM[XM.pbp_point])):
            gm = g[g.moved]
            st = g[g.get("stale_sh", pd.Series(dtype=float)).notna()] if "stale_sh" in g else g.iloc[0:0]
            res["cross_market"][cut] = {"n_pairs": int(len(g)), "share_side_moved": round(float(g.moved.mean()), 3) if len(g) else None,
                                        "lag_half_s": qstats(gm.lag_s) if len(gm) else {"n": 0},
                                        "n_lagging_gt_1p3": int(len(st)),
                                        "sum_net_edge_usd_hold": round(float(st.stale_net_usd.sum()), 2) if len(st) else 0.0,
                                        "sum_net_edge_usd_exit": round(float(st.stale_net_exit_usd.sum()), 2) if len(st) else 0.0}
        if "stale_sh" in XM:
            st = XM[XM.stale_sh.notna()]
            res["cross_market"]["all_lagging_gt_1p3_stale_at_ml+1.3s"] = {
                "n": int(len(st)), "share_with_stale_depth": round(float((st.stale_sh > 0).mean()), 3) if len(st) else None,
                "sum_usd": round(float(st.stale_usd.sum()), 0), "sum_net_edge_usd_hold": round(float(st.stale_net_usd.sum()), 2),
                "sum_net_edge_usd_exit": round(float(st.stale_net_exit_usd.sum()), 2),
                "per_hour_net_edge_usd_hold": round(float(st.stale_net_usd.sum() / hrs), 2) if hrs > 0 else None,
                "per_hour_net_edge_usd_exit": round(float(st.stale_net_exit_usd.sum() / hrs), 2) if hrs > 0 else None}
        for smt, g in XM.groupby("smt"):
            gm = g[g.moved]
            res["cross_market"][smt] = {"n_pairs": int(len(g)), "share_side_moved": round(float(g.moved.mean()), 3),
                                        "lag_half_s": qstats(gm.lag_s) if len(gm) else {"n": 0},
                                        "lag_first_tick_s": qstats(gm.lag_first_s) if len(gm) else {"n": 0}}
            if "stale_sh" in g:
                st = g[g.stale_sh.notna()]
                res["cross_market"][smt]["stale_at_ml+1.3s"] = {
                    "n_lagging_gt_1p3": int(len(st)), "share_with_stale_depth": round(float((st.stale_sh > 0).mean()), 3) if len(st) else None,
                    "sum_net_edge_usd": round(float(st.stale_net_usd.sum()), 2) if len(st) else 0.0,
                    "sum_net_exit_usd": round(float(st.stale_net_exit_usd.sum()), 2) if len(st) else 0.0,
                    "mean_net_edge_usd": round(float(st.stale_net_usd.mean()), 2) if len(st) else None,
                    "median_usd": round(float(st.stale_usd.median()), 1) if len(st) else None}
    if len(DEP):
        for lab in ("pre2s", "pre1s", "pre", "post"):
            big = DEP[DEP.D >= 0.03]
            res["stale_depth"][lab + "_D_ge_3c"] = {"n": int(len(big)),
                                                   "median_usd": round(float(big[f"usd_{lab}"].median()), 1) if len(big) else None,
                                                   "mean_net_edge_usd": round(float(big[f"net_usd_{lab}"].mean()), 2) if len(big) else None,
                                                   "median_net_edge_usd": round(float(big[f"net_usd_{lab}"].median()), 2) if len(big) else None}
            res["stale_depth"][lab] = {"median_shares": round(float(DEP[f"sh_{lab}"].median()), 1),
                                       "median_usd": round(float(DEP[f"usd_{lab}"].median()), 1),
                                       "mean_usd": round(float(DEP[f"usd_{lab}"].mean()), 1),
                                       "median_net_edge_usd": round(float(DEP[f"net_usd_{lab}"].median()), 2),
                                       "mean_net_edge_usd": round(float(DEP[f"net_usd_{lab}"].mean()), 2),
                                       "mean_net_exit_usd": round(float(DEP[f"net_exit_usd_{lab}"].mean()), 2),
                                       "sum_net_edge_usd": round(float(DEP[f"net_usd_{lab}"].sum()), 0),
                                       "share_events_any_stale": round(float((DEP[f"sh_{lab}"] > 0).mean()), 3),
                                       "n": int(DEP[f"sh_{lab}"].notna().sum())}
    if len(SD):
        for src, g in SD.groupby("src"):
            res["stale_depth"][f"at_{src}+1.3s"] = {"n": int(len(g)), "share_any_stale": round(float((g.sh > 0).mean()), 3),
                                                   "mean_usd": round(float(g.usd.mean()), 1),
                                                   "mean_net_edge_usd": round(float(g.net_usd.mean()), 2)}
    return res


def trade_timing(M1, evd, books, mids) -> pd.DataFrame:
    """Every moneyline print within +-5 s of an M1 reprice, in outcome-0 terms: who trades at the
    stale price, and when relative to the reprice (prints arrive after the 1 s order delay)."""
    rows = []
    if not len(M1):
        return pd.DataFrame()
    for r in M1[M1.ok == True].itertuples():  # noqa: E712
        e = evd.loc[r.slug]
        d = 1 if r.winner == 0 else -1
        t, mid, _, _ = mids[e.tok0]
        j = np.searchsorted(t, r.t_book + 3000, "right") - 1
        m_new = mid[j] if j >= 0 else np.nan
        for tok, sgn in ((e.tok0, 1), (e.tok1, -1)):
            for rt, p, sz, side in books.trades.get(tok, []):
                if abs(rt - r.t_book) > 5000 or not np.isfinite(p):
                    continue
                p0 = p if sgn == 1 else 1 - p
                dir0 = (1 if side == "BUY" else -1) * sgn
                rows.append({"slug": r.slug, "n": r.n, "dt_s": (rt - r.t_book) / 1000, "p0": p0, "sh": sz,
                             "usd": sz * (p0 if dir0 > 0 else 1 - p0), "with_move": dir0 == d,
                             "edge_vs_new_mid": (m_new - p0) * dir0, "D": r.D,
                             "fee": FEE_RATE * p0 * (1 - p0)})
    return pd.DataFrame(rows)


def trade_timing_summary(TT: pd.DataFrame) -> dict:
    if TT.empty:
        return {}
    TT = TT.copy()
    TT["bin"] = pd.cut(TT.dt_s, [-5, -3, -2, -1, -0.5, 0, 0.5, 1, 2, 3, 5])
    out = {}
    for b, g in TT.groupby("bin", observed=True):
        w = g[g.with_move]
        out[str(b)] = {"n_prints": int(len(g)), "usd": round(float(g.usd.sum()), 0),
                       "share_usd_with_move": round(float(w.usd.sum() / g.usd.sum()), 3) if g.usd.sum() else None,
                       "with_move_net_edge_c_per_share": round(float(((w.edge_vs_new_mid - w.fee) * w.sh).sum() / w.sh.sum() * 100), 2) if len(w) else None}
    return out


VARIANTS = [
    # (source, book-matching method) -- every lead configuration computed; nothing here is tuned
    *[(src, m) for src in ("pm_sports", "espn", "wta_api(list+score)") for m in
      ("M1 official-clock half-move", "M1 official-clock first-tick", "M2 biggest-move [-90,+30]")],
    ("wta_pbp endpoint", "delay vs its own timestamps"),
    ("cross-market", "ML jump >=1c/2s, side half-move in [-5,+30] s"),
    ("cross-market", "cut: ML jump >=3c"),
    ("cross-market", "cut: ML jump at an official WTA point"),
    ("cross-market stale depth", "side book at t_ml+1.3 s vs side mid at t_side+3 s (hold) / opposite touch (exit)"),
    ("stale depth", "ML book at t_book-2s/-1s/-0.25s/+0.5s vs mid at t_book+3s"),
    ("trades around reprice", "prints within +-5 s of t_book"),
]
EXCLUDED_SOURCES = {
    "atptour.com / app.atptour.com": "Cloudflare challenge (HTTP 403) -> blocks automated access, skipped",
    "protennislive.com (official ATP/WTA live scoring app)": "Cloudflare HTTP 503 to non-browser clients, skipped",
    "sofascore.com / api.sofascore.com": "HTTP 403 even on robots.txt, skipped",
    "itftennis.com": "Imperva bot-protection JS challenge page, skipped",
    "livescore.com public API": "robots.txt disallows /api/ -> not used",
    "flashscore": "ToS prohibits automated extraction; obfuscated feed, not used",
    "gamma-api.polymarket.com event score (REST)": "tested: Cloudflare-cached (max-age=300, purged on change), "
                                                   "~6 s behind the sports websocket in the one change observed; not recorded",
}


def write_results(res: dict) -> None:
    m1 = res.get("m1", {})
    b = m1.get("book_vs_official_T_s", {})
    srcs = {k.split(":")[0]: v for k, v in m1.items() if k.endswith(":all")}
    best = min(srcs.items(), key=lambda kv: kv[1]["source_delay_vs_official_T_s"].get("median", 1e9)) if srcs else (None, {})
    lead_shares = {k: v["lead_vs_book_s"].get("share_gt_1p3") for k, v in srcs.items()}
    out = {
        "lens": "latency",
        "headline": (f"No public score source beats the Polymarket book: the moneyline reprices a median "
                     f"{-b.get('median', float('nan')):.1f} s BEFORE the official WTA point timestamp (n={b.get('n')}), "
                     f"while the fastest public source ({best[0]}) reports a median "
                     f"{best[1].get('source_delay_vs_official_T_s', {}).get('median', float('nan')):.1f} s AFTER it; "
                     f"share of source-observed changes leading the book by >1.3 s = {lead_shares}."),
        "variants": [list(v) for v in VARIANTS], "n_variants": len(VARIANTS),
        "excluded_sources": EXCLUDED_SOURCES,
        "summary": res,
        "reproduce": ["python research/v2/latency/recorder.py --hours 20   # live recording (nohup)",
                      "python research/v2/latency/fetch_pbp.py              # official WTA point log, cached",
                      "python research/v2/latency/analyze.py                # all numbers + out/*.csv + figure"],
    }
    (OUT.parent / "results.json").write_text(json.dumps(out, indent=1, default=float))


def cadence() -> dict:
    """How often each source can possibly update: push interval (pm_sports), CDN cache age and
    response time of the polled endpoints."""
    out = {}
    per = defaultdict(list)
    for r in list(L.read("pmsports")) + list(L.read("sports", L.LEGACY)):
        if "gameId" in r and str(r.get("leagueAbbreviation", "")).lower() in ("atp", "wta", "challenger", "wta challenger"):
            per[r["gameId"]].append(r["rt"])
    gaps = []
    for g, v in per.items():
        v = np.unique(np.array(v)) / 1000
        gaps += list(np.diff(v)[np.diff(v) > 1.0])
    out["pm_sports_msg_gap_s"] = qstats(gaps)
    pl = pd.DataFrame([r for r in L.read("polls") if r.get("src") in ("espn_atp", "espn_wta", "wta_list", "wta_score", "wta_pbp")])
    if len(pl):
        for src, g in pl.groupby("src"):
            age = pd.to_numeric(g.get("age"), errors="coerce")
            out[src] = {"n_polls": int(len(g)), "ok_share": round(float((g.get("code") == 200).mean()), 3),
                        "resp_ms_median": float(np.nanmedian(pd.to_numeric(g.ms, errors="coerce"))),
                        "cdn_age_s_median": float(np.nanmedian(age)) if age.notna().any() else None,
                        "cache_control": g.cc.dropna().mode().iloc[0] if g.cc.notna().any() else None,
                        "x_cache_hit_share": round(float(g.xc.fillna("").str.contains("Hit").mean()), 3)}
    return out


def plots(M1, S1, M2, XM) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(17, 4.4))
    srcs = sorted(M2.src.unique()) if len(M2) else []
    for s in srcs:
        x = np.sort(M2[M2.src == s].lead_s.dropna())
        if len(x):
            ax[0].plot(x, np.arange(1, len(x) + 1) / len(x), label=f"{s} (n={len(x)})")
    ax[0].axvline(DELAY_S, color="k", ls="--", lw=1)
    ax[0].axvline(0, color="grey", lw=0.8)
    ax[0].set_xlim(-95, 35)
    ax[0].set_xlabel("lead = t_book - t_source  [s]  (>1.3 s = actionable)")
    ax[0].set_ylabel("ECDF")
    ax[0].set_title("M2: source-anchored biggest move, all matches")
    ax[0].legend(fontsize=8)
    if len(S1) and "lead_s" in S1:
        for s in sorted(S1.src.unique()):
            x = np.sort(S1[S1.src == s].src_vs_T_s.dropna())
            if len(x):
                ax[1].plot(x, np.arange(1, len(x) + 1) / len(x), label=f"{s} vs official T (n={len(x)})")
    if len(M1) and "book_vs_T_s" in M1:
        x = np.sort(M1.book_vs_T_s.dropna())
        if len(x):
            ax[1].plot(x, np.arange(1, len(x) + 1) / len(x), "k", lw=2, label=f"Polymarket book vs official T (n={len(x)})")
    ax[1].axvline(0, color="grey", lw=0.8)
    ax[1].set_xlim(-12, 90)
    ax[1].set_xlabel("time after official point timestamp T_p  [s]")
    ax[1].set_title("M1: WTA official point clock")
    ax[1].legend(fontsize=8)
    if len(XM) and "lag_s" in XM:
        for smt, g in XM[XM.moved].groupby("smt"):
            x = np.sort(g.lag_s.dropna())
            if len(x) >= 5:
                ax[2].plot(x, np.arange(1, len(x) + 1) / len(x), label=f"{smt.replace('tennis_', '')} (n={len(x)})")
        ax[2].axvline(DELAY_S, color="k", ls="--", lw=1)
        ax[2].axvline(0, color="grey", lw=0.8)
        ax[2].set_xlim(-5, 30)
        ax[2].set_xlabel("side-market reprice - moneyline jump  [s]")
        ax[2].set_title("(i) cross-market lag (side markets that moved)")
        ax[2].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "latency_ecdf.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    r = main()
    print(json.dumps(r, indent=1, default=float)[:6000])
