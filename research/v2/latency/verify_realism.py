"""Adversarial realism / statistics checks for the latency lens (reviewer script).

    .venv/bin/python research/v2/latency/verify_realism.py

What it does (all on the same live forward recording the lens used; nothing is tuned):
  0. Reproduces analyze.py on the recording truncated at the lens's snapshot time (book_last_utc in
     out/summary.json) and diffs the headline numbers. Reproduction outputs go to
     data/v2_latency/verify_repro/ so the lens's own out/ and results.json are not overwritten.
  1. M1 shift placebo: move the official anchor T_p by -4..+4 s; a method locked onto the real book
     move returns the same absolute reprice time (estimate relative to the true T is unchanged).
  2. Clock sanity: no source should ever see a point before its official stamp.
  3. Optimistic source leads: a loose upper bound on what an origin-speed (cache-free) poller could have
     seen (previous poll's CDN object age + poll period for the WTA API; poll period for ESPN), plus the
     tighter bound for any feed derived from the official scoring system: it cannot precede the official
     stamp, so it leads the book by > 1.3 s only where book - T_p > 1.3 s.
  4. M2 placebo: the same biggest-move rule in the WRONG direction. If the wrong direction produces as
     many "leads > 1.3 s" as the right one, M2's positive shares are window artefacts.
  5. Cross-market (set_winner "+$378"): concentration by match / event, the lag of the side reprice
     that generated each dollar, look-ahead in the level selection, sensitivity to execution time and
     to causal (real-time) jump detection, and a causal touch-taking version with no hindsight.
  6. ML oracle stale depth: how much of it the takers who already move the book consume (queue
     competition), per-share economics, and concentration.
  7. Local receive latency of the CLOB feed (rt - server ts) to sanity-check the 0.3 s allowance.
Output: research/v2/latency/out/verify_realism.json (and a printed summary).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import load as L  # noqa: E402
import analyze as A  # noqa: E402

ORIG = json.loads((HERE / "out" / "summary.json").read_text())
CUT_MS = pd.Timestamp(ORIG["recording"]["book_last_utc"]).value / 1e6
REPRO = ROOT / "data" / "v2_latency" / "verify_repro"
OUTF = HERE / "out" / "verify_realism.json"
FEE = 0.05
RNG = np.random.default_rng(20261003)

# ----------------------------------------------------------------------------- truncate + capture
_orig_read = L.read


def read_cut(stream, live=L.LIVE, with_run=False):
    for x in _orig_read(stream, live, with_run=with_run):
        rec = x[1] if with_run else x
        rt = rec.get("rt") if isinstance(rec, dict) else None
        if rt is not None and rt > CUT_MS:
            continue
        yield x


L.read = read_cut
BOOKS: dict = {}


class CapBooks(L.Books):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        BOOKS["b"] = self


L.Books = CapBooks
A.OUT = REPRO / "out"


def r2(x, k=3):
    try:
        return None if x is None or not np.isfinite(x) else round(float(x), k)
    except TypeError:
        return x


def qs(x):
    x = np.asarray(pd.Series(x).dropna(), dtype=float)
    if not len(x):
        return {"n": 0}
    return {"n": int(len(x)), "median": r2(np.median(x)), "p10": r2(np.percentile(x, 10)),
            "p90": r2(np.percentile(x, 90)), "max": r2(np.max(x)), "share_gt_1p3": r2(np.mean(x > 1.3))}


def main() -> dict:
    out: dict = {"cutoff_utc": ORIG["recording"]["book_last_utc"]}
    t0 = time.time()
    res = A.main()
    out["repro_seconds"] = round(time.time() - t0, 1)
    books: L.Books = BOOKS["b"]

    # ------------------------------------------------------------------ 0. reproduction diff
    def g(d, *ks):
        for k in ks:
            d = (d or {}).get(k)
        return d
    keys = [("m1", "book_vs_official_T_s", "n"), ("m1", "book_vs_official_T_s", "median"),
            ("m1", "book_vs_official_T_s", "share_gt_1p3"),
            ("m1", "espn:all", "lead_vs_book_s", "n"), ("m1", "espn:all", "lead_vs_book_s", "median"),
            ("m1", "espn:all", "lead_vs_book_s", "share_gt_1p3"),
            ("m1", "pm_sports:all", "lead_vs_book_s", "n"), ("m1", "pm_sports:all", "lead_vs_book_s", "median"),
            ("m1", "wta:all", "lead_vs_book_s", "n"), ("m1", "wta:all", "lead_vs_book_s", "median"),
            ("m1", "wta:all", "lead_vs_book_s", "share_gt_1p3"),
            ("cross_market", "all_lagging_gt_1p3_stale_at_ml+1.3s", "sum_net_edge_usd_hold"),
            ("cross_market", "all_lagging_gt_1p3_stale_at_ml+1.3s", "sum_net_edge_usd_exit"),
            ("cross_market", "tennis_set_winner", "stale_at_ml+1.3s", "sum_net_edge_usd"),
            ("cross_market", "tennis_set_winner", "stale_at_ml+1.3s", "sum_net_exit_usd"),
            ("stale_depth", "pre", "mean_net_edge_usd"), ("stale_depth", "pre", "median_usd")]
    out["reproduction"] = {"/".join(k): {"claimed": g(ORIG, *k), "reproduced": g(res, *k)} for k in keys}
    out["reproduction_all_match"] = all(
        (v["claimed"] == v["reproduced"]) or (isinstance(v["claimed"], (int, float)) and isinstance(v["reproduced"], (int, float))
                                              and abs(v["claimed"] - v["reproduced"]) <= 1e-6 + 0.01 * abs(v["claimed"]))
        for v in out["reproduction"].values())

    M1 = pd.read_csv(A.OUT / "m1_points.csv")
    S1 = pd.read_csv(A.OUT / "m1_source_leads.csv")
    XM = pd.read_csv(A.OUT / "cross_market.csv")
    DEP = pd.read_csv(A.OUT / "stale_depth.csv")
    TT = pd.read_csv(A.OUT / "trades_around_reprice.csv")

    meta = L.load_meta()
    ev = L.events_table(meta)
    # same tick fix-up as analyze.main
    for tk in ev.tok0:
        arr = books.top.get(tk)
        if arr is not None and len(arr):
            q = arr[:, 1:3][np.isfinite(arr[:, 1:3])] * 100
            if len(q) and np.any(np.abs(q - np.round(q)) > 1e-6):
                ev.loc[ev.tok0 == tk, "tick"] = 0.001
    evd = ev.set_index("slug")
    mids = {}

    def mid_of(tok):
        if tok not in mids:
            mids[tok] = books.mid_series(tok)
        return mids[tok]

    # ------------------------------------------------------------------ 1. M1 shift placebo
    ok = M1[M1.ok == True].copy()  # noqa: E712
    sp = {}
    for s in (-4, -2, -1, 0, 1, 2, 4):
        est, est_rel = [], []
        for r in ok.itertuples():
            e = evd.loc[r.slug]
            t, mid, _, _ = mid_of(e.tok0)
            d = 1 if r.winner == 0 else -1
            lo = -min(10_000, 0.5 * r.gap_prev_s * 1000)
            hi = min(25_000, r.gap_next_s * 1000 - 4_000)
            rp = A.reprice_window(t, mid, r.T_ms + s * 1000, d, lo, hi, e.tick)
            if rp and rp.get("ok"):
                est.append((rp["t_half"] - r.T_ms) / 1000)
        sp[f"shift_{s:+d}s"] = {"n": len(est), "median_book_minus_true_T_s": r2(np.median(est))}
    out["m1_shift_placebo"] = sp
    # bootstrap by match for the M1 median
    slugs = ok.slug.unique()
    bs = []
    for _ in range(2000):
        pick = RNG.choice(slugs, len(slugs), replace=True)
        bs.append(np.median(np.concatenate([ok[ok.slug == s_].book_vs_T_s.to_numpy() for s_ in pick])))
    out["m1_median_cluster_bootstrap_95ci_s"] = [r2(np.percentile(bs, 2.5)), r2(np.percentile(bs, 97.5))]
    out["m1_matches"] = int(len(slugs))
    out["m1_points_per_match"] = ok.groupby("slug").size().to_dict()
    # a zero-latency feed of the official stamp (not public; a bound): share of points where it leads by > 1.3 s
    out["zero_latency_official_feed_share_lead_gt_1p3"] = r2(np.mean(ok.book_vs_T_s > 1.3))
    for dly in (3.5, 5.0, 10.0):
        out[f"official_stamp_plus_{dly}s_feed_share_lead_gt_1p3"] = r2(np.mean(ok.book_vs_T_s - dly > 1.3))

    # ------------------------------------------------------------------ 2. clock sanity
    out["source_minus_official_T_min_s"] = S1.groupby(["src", "level"]).src_vs_T_s.min().round(2).to_dict()
    out["source_minus_official_T_min_s"] = {f"{k[0]}:{k[1]}": v for k, v in out["source_minus_official_T_min_s"].items()}
    out["share_source_before_official_T"] = r2(np.mean(S1.src_vs_T_s < 0))

    # ------------------------------------------------------------------ 3. optimistic leads (CDN age + poll period)
    polls = pd.DataFrame([r for r in L.read("polls") if r.get("src") in ("wta_list", "wta_score", "espn_atp", "espn_wta")])
    polls["age_s"] = pd.to_numeric(polls.get("age"), errors="coerce").fillna(0.0)
    period = {"wta_list": 2.0, "wta_score": 4.0, "espn_atp": 2.0, "espn_wta": 2.0}
    gaps = {}
    for src, gp in polls.groupby("src"):
        x = np.diff(np.sort(gp.rt.unique())) / 1000
        gaps[src] = {"median_poll_gap_s": r2(np.median(x)), "p90_poll_gap_s": r2(np.percentile(x, 90)),
                     "median_cdn_age_s": r2(gp.age_s.median())}
    out["poll_cadence"] = gaps
    key_of = M1.drop_duplicates("slug").set_index("slug").key.to_dict()
    # Earliest time the ORIGIN could have had the new state: the previous poll of the same endpoint for the
    # same match/tournament returned the old state from a CDN object created at t_prev - age_prev, so the
    # origin may have changed any time after that. lead_origin_ub = t_book - (t_prev - age_prev) is a loose
    # upper bound on what a cache-free (origin-speed) poller could have achieved. For push/ESPN (max-age=1,
    # age 0) the bound is lead + poll period.
    polls["tidn"] = pd.to_numeric(polls.get("tid"), errors="coerce")
    opt = []
    for r in S1[S1.lead_s.notna()].itertuples():
        if r.src == "wta":
            tid, mid_ = key_of.get(r.slug, "|").split("|")[:2]
            if r.via == "wta_score":
                q = polls[(polls.src == "wta_score") & (polls.get("mid").astype(str) == str(mid_))]
            else:
                q = polls[(polls.src == "wta_list") & (polls.tidn == float(tid))]
            cur = q[q.rt == r.rt]
            prev = q[q.rt < r.rt].sort_values("rt").tail(1)
            age_now = float(cur.age_s.max()) if len(cur) else np.nan
            xc_now = cur.xc.iloc[0] if len(cur) and "xc" in cur else None
            if len(prev):
                origin_lb = float(prev.rt.iloc[0]) - 1000 * float(prev.age_s.iloc[0])
            else:
                origin_lb = r.rt - 1000 * (period.get(r.via, 4.0) + 30.0)
            ub = r.lead_s + (r.rt - origin_lb) / 1000
        elif r.src == "espn":
            age_now, xc_now = 0.0, None
            ub = r.lead_s + 2.0
        else:
            age_now, xc_now = 0.0, None
            ub = r.lead_s
        opt.append({"src": r.src, "lead_s": r.lead_s, "age_now_s": age_now, "xc_now": xc_now, "lead_origin_ub_s": ub})
    OP = pd.DataFrame(opt)
    out["optimistic_leads"] = {src: {"lead_s": qs(gp.lead_s), "lead_origin_upper_bound_s": qs(gp.lead_origin_ub_s),
                                     "first_seen_poll_cache_status": gp.xc_now.fillna("n/a").value_counts().to_dict(),
                                     "first_seen_poll_age_s_median": r2(gp.age_now_s.median())}
                               for src, gp in OP.groupby("src")}
    out["exact_0_of_n"] = {"n": int(S1.lead_s.notna().sum()), "n_gt_1p3": int((S1.lead_s > 1.3).sum()),
                           "cp95_upper_share": r2(1 - 0.05 ** (1 / max(1, int(S1.lead_s.notna().sum()))), 4),
                           "max_lead_s": r2(S1.lead_s.max())}

    # ------------------------------------------------------------------ 4. M2 wrong-direction placebo
    pm_u, _ = L.pm_sports_units(ev)
    es_u = L.espn_units(ev)
    wt_u, _, _ = L.wta_units(ev)
    U = A.dedupe_units(pm_u + es_u + wt_u)
    U, _ = A.drop_post_outage(U)
    m2 = []
    for r in U.itertuples():
        e = evd.loc[r.slug]
        t, mid, _, _ = mid_of(e.tok0)
        d = 1 if r.winner == 0 else -1
        row = {"src": r.src, "series": r.slug.split("-")[0]}
        for lab, dd in (("right", d), ("wrong", -d)):
            bm = A.biggest_move(t, mid, r.rt, dd, e.tick)
            row[lab] = (bm["t_half"] - r.rt) / 1000 if bm and bm.get("ok") else np.nan
            row[lab + "_D"] = bm["D"] if bm and bm.get("ok") else np.nan
        m2.append(row)
    M2 = pd.DataFrame(m2)
    out["m2_placebo"] = {}
    for (src, ser), gp in M2.groupby(["src", "series"]):
        out["m2_placebo"][f"{src}:{ser}"] = {"n": int(len(gp)),
                                             "right_dir_share_gt_1p3": r2(np.mean(gp.right > 1.3)),
                                             "wrong_dir_share_gt_1p3": r2(np.mean(gp.wrong > 1.3)),
                                             "right_dir_median_lead_s": r2(gp.right.median()),
                                             "wrong_dir_median_lead_s": r2(gp.wrong.median()),
                                             "right_median_move_c": r2(gp.right_D.median() * 100, 2),
                                             "wrong_median_move_c": r2(gp.wrong_D.median() * 100, 2)}

    # ------------------------------------------------------------------ 5. cross-market
    st = XM[XM.stale_sh.notna()].copy()
    xm = {}
    for smt, gp in st.groupby("smt"):
        sh = gp.stale_sh.sum()
        xm[smt] = {"n_lagging": int(len(gp)), "n_with_stale": int((gp.stale_sh > 0).sum()),
                   "n_matches_with_stale": int(gp[gp.stale_sh > 0].slug.nunique()),
                   "hold_usd": r2(gp.stale_net_usd.sum(), 1), "exit_usd": r2(gp.stale_net_exit_usd.sum(), 1),
                   "hold_c_per_share": r2(100 * gp.stale_net_usd.sum() / sh, 3) if sh else None,
                   "exit_c_per_share": r2(100 * gp.stale_net_exit_usd.sum() / sh, 3) if sh else None}
    tot_sh = st.stale_sh.sum()
    xm["ALL"] = {"hold_c_per_share": r2(100 * st.stale_net_usd.sum() / tot_sh, 3),
                 "exit_c_per_share": r2(100 * st.stale_net_exit_usd.sum() / tot_sh, 3), "shares": r2(tot_sh, 0)}
    sw = st[(st.smt == "tennis_set_winner") & (st.stale_sh > 0)].sort_values("stale_net_usd", ascending=False)
    if len(sw):
        top = sw.iloc[0]
        xm["set_winner_detail"] = {
            "matches": sw.slug.unique().tolist(),
            "top_event_share_of_hold": r2(top.stale_net_usd / sw.stale_net_usd.sum(), 3),
            "top_event": {"lag_s": r2(top.lag_s), "ml_move_c": r2(top.ml_move * 100, 2), "stale_usd": r2(top.stale_usd, 0),
                          "stale_shares": r2(top.stale_sh, 0), "hold_usd": r2(top.stale_net_usd, 1),
                          "exit_usd": r2(top.stale_net_exit_usd, 1)},
            "hold_usd_excl_top_event": r2(sw.stale_net_usd.iloc[1:].sum(), 1),
            "hold_usd_lag_le_5s": r2(sw[sw.lag_s <= 5].stale_net_usd.sum(), 1),
            "n_lag_le_5s": int((sw.lag_s <= 5).sum()),
            "hold_usd_lag_gt_10s": r2(sw[sw.lag_s > 10].stale_net_usd.sum(), 1),
            "n_lag_gt_10s": int((sw.lag_s > 10).sum()),
            "share_events_ml_move_1c": r2(np.mean(sw.ml_move <= 0.0105)),
            "per_event_hold_t_stat": r2(sw.stale_net_usd.mean() / (sw.stale_net_usd.std(ddof=1) / np.sqrt(len(sw)))),
            "per_event_hold_t_stat_excl_top": r2(sw.stale_net_usd.iloc[1:].mean() / (sw.stale_net_usd.iloc[1:].std(ddof=1) / np.sqrt(len(sw) - 1))),
            "expected_max_z_of_7_null": r2(np.mean(np.max(RNG.standard_normal((20000, 7)), axis=1))),
            "expected_max_z_of_42_null": r2(np.mean(np.max(RNG.standard_normal((20000, 42)), axis=1))),
        }
    allst = st[st.stale_sh > 0]
    xm["all_types_lag_bucket_hold_usd"] = {
        "lag_le_3s": r2(allst[allst.lag_s <= 3].stale_net_usd.sum(), 1),
        "lag_3_10s": r2(allst[(allst.lag_s > 3) & (allst.lag_s <= 10)].stale_net_usd.sum(), 1),
        "lag_gt_10s": r2(allst[allst.lag_s > 10].stale_net_usd.sum(), 1)}
    xm["share_pairs_side_never_moved"] = r2(1 - XM.moved.mean())
    out["cross_market_audit"] = xm
    out["cross_market_resim"] = cross_market_resim(books, meta, ev, evd, mid_of)

    # ------------------------------------------------------------------ 6. ML oracle: competition + per share
    TT["w"] = TT.with_move.astype(bool)
    cons = TT[TT.w & (TT.dt_s >= -0.25) & (TT.dt_s <= 0.5)].groupby(["slug", "n"]).usd.sum().rename("with_move_usd_m0p25_p0p5")
    cons2 = TT[TT.w & (TT.dt_s >= -1.3) & (TT.dt_s <= 0.5)].groupby(["slug", "n"]).usd.sum().rename("with_move_usd_m1p3_p0p5")
    Dm = DEP.merge(cons, on=["slug", "n"], how="left").merge(cons2, on=["slug", "n"], how="left").fillna(
        {"with_move_usd_m0p25_p0p5": 0.0, "with_move_usd_m1p3_p0p5": 0.0})
    has = Dm[Dm.usd_pre > 0]
    orc = {"n_points": int(len(DEP)), "n_points_with_stale_pre": int(len(has)),
           "median_ratio_printed_to_stale_pre": r2((has.with_move_usd_m0p25_p0p5 / has.usd_pre).median()),
           "share_points_printed_ge_stale_pre": r2(np.mean(has.with_move_usd_m0p25_p0p5 >= has.usd_pre)),
           "total_stale_usd_pre": r2(DEP.usd_pre.sum(), 0),
           "total_with_move_printed_usd_m0p25_p0p5": r2(Dm.with_move_usd_m0p25_p0p5.sum(), 0)}
    for lab in ("pre2s", "pre1s", "pre", "post"):
        sh = DEP[f"sh_{lab}"].sum()
        orc[lab] = {"hold_c_per_share": r2(100 * DEP[f"net_usd_{lab}"].sum() / sh), "exit_c_per_share": r2(100 * DEP[f"net_exit_usd_{lab}"].sum() / sh),
                    "hold_usd_total": r2(DEP[f"net_usd_{lab}"].sum(), 0)}
    for lab in ("pre1s", "pre"):
        sh = DEP[f"sh_{lab}"].sum()
        orc[lab]["gross_c_per_share_no_fee"] = r2(100 * DEP[f"edge_usd_{lab}"].sum() / sh)
        big = DEP[DEP.D >= 0.03]
        shb = big[f"sh_{lab}"].sum()
        orc[lab]["D_ge_3c"] = {"n": int(len(big)), "hold_c_per_share": r2(100 * big[f"net_usd_{lab}"].sum() / shb),
                               "exit_c_per_share": r2(100 * big[f"net_exit_usd_{lab}"].sum() / shb),
                               "hold_usd_by_match": big.groupby("slug")[f"net_usd_{lab}"].sum().round(0).to_dict()}
    bym = DEP.groupby("slug").net_usd_pre.sum().sort_values(ascending=False)
    orc["pre_hold_usd_by_match"] = bym.round(0).to_dict()
    orc["pre_hold_usd_excl_top2_matches"] = r2(bym.iloc[2:].sum(), 0)
    top5 = DEP.net_usd_pre.sort_values(ascending=False).head(5).sum()
    orc["pre_top5_points_share_of_hold"] = r2(top5 / DEP.net_usd_pre.sum())
    out["ml_oracle_audit"] = orc

    # ------------------------------------------------------------------ 7. local receive latency
    out["clob_rt_minus_server_ts_ms"] = clob_latency()
    out["variant_recount"] = variant_recount()
    out["repro_hygiene"] = hygiene()
    OUTF.write_text(json.dumps(out, indent=1, default=float))
    return out


def detect_jumps_causal(t, mid, thr=0.01, H=2000, sep=10_000):
    """Same scan as analyze.detect_jumps but also returns t_det: the first update at which the move from
    the pre-jump mid reaches thr (what a real-time detector can know)."""
    out = []
    if len(t) < 3:
        return out
    last = -np.inf
    i, n = 1, len(t)
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
            kd = int(np.argmax(mv * dirn >= thr - 1e-9))
            out.append((float(t[i + h]), dirn, float(abs(mv[k])), float(t[i + kd])))
            last = t[i + h]
            i = j
        else:
            i += 1
    return out


def cross_market_resim(books, meta, ev, evd, mid_of) -> dict:
    """Replicates analyze.main's cross-market loop, then (a) varies the execution time, (b) uses causal
    detection time, and (c) runs a causal, hindsight-free touch-taking rule on every side market."""
    slugs = set(ev[(ev.src_meta == "v2") & ~ev.doubles].slug)
    side = meta[meta.slug.isin(slugs) & (meta.smt != "moneyline") & (meta.oi == 0)].drop_duplicates("tok")
    side_by_slug = {sl: g for sl, g in side.groupby("slug")}
    side_toks = set(side.tok)
    v2_first = min((a[0, 0] for tk, a in books.top.items() if tk in side_toks), default=np.inf)
    v2_last = max((a[-1, 0] for tk, a in books.top.items() if tk in side_toks), default=-np.inf)
    jumps = []
    for e in ev[ev.slug.isin(side_by_slug) & ~ev.doubles].drop_duplicates("slug").itertuples():
        t, mid, _, _ = mid_of(e.tok0)
        for jt, jd, js, td in detect_jumps_causal(t, mid):
            if v2_first + 60_000 <= jt <= v2_last - 30_000:
                jumps.append((e.slug, jt, jd, js, td))
    det_lag = np.array([(td - jt) / 1000 for _, jt, _, _, td in jumps])
    offs = (1.3, 1.6, 2.0, 2.5)
    rows, causal = [], []
    smid = {}
    for slug, jt, jd, js, td in jumps:
        e = evd.loc[slug]
        for sm in side_by_slug[slug].itertuples():
            if sm.tok not in smid:
                smid[sm.tok] = books.mid_series(sm.tok, max_spread=0.10)
            ts, ms, _, _ = smid[sm.tok]
            if len(ts) == 0 or ts[0] > jt - 5000:
                continue
            i0 = np.searchsorted(ts, jt - 5000, "right") - 1
            if i0 < 0 or ms[i0] < 0.03 or ms[i0] > 0.97:
                continue
            oc = L.norm(str(sm.outcome))
            rel = 1 if oc == L.norm(e.n0) else (-1 if oc == L.norm(e.n1) else 0)
            tick = float(sm.tick or 0.01)
            if rel:
                rp, ds = A.reprice_window(ts, ms, jt, jd * rel, -5000, 30_000, tick), jd * rel
                # (c) causal: decide at t_det + 0.3 s using only data up to then; order lands at t_det + 1.3 s
                td_send = td + 300
                k_now = np.searchsorted(ts, td_send, "right") - 1
                moved_already = k_now >= 0 and (ms[k_now] - ms[i0]) * ds >= tick - 1e-9
                if not moved_already:
                    tex = td + 1300
                    bids, asks = books.book_at(sm.tok, tex)
                    if ds > 0 and asks:
                        px = min(asks)
                        sz = asks[px]
                    elif ds < 0 and bids:
                        px = max(bids)
                        sz = bids[px]
                    else:
                        px = sz = None
                    if px is not None and 0.02 < px < 0.98:
                        rec = {"slug": slug, "smt": sm.smt, "px": px, "sz": sz, "ml_move": js}
                        for H in (10, 60):
                            kk = np.searchsorted(ts, tex + H * 1000, "right") - 1
                            nb, na = A.top_at(books, sm.tok, tex + H * 1000)
                            m_h = ms[kk] if kk >= 0 else np.nan
                            ex = nb if ds > 0 else na
                            rec[f"hold{H}_c"] = 100 * ((m_h - px) * ds - FEE * px * (1 - px))
                            rec[f"exit{H}_c"] = 100 * ((ex - px) * ds - FEE * px * (1 - px) - FEE * ex * (1 - ex)) if np.isfinite(ex) else np.nan
                        causal.append(rec)
            else:
                ru = A.reprice_window(ts, ms, jt, 1, -5000, 30_000, tick)
                rd = A.reprice_window(ts, ms, jt, -1, -5000, 30_000, tick)
                rp, ds = (ru, 1) if (ru and ru.get("ok")) else (rd, -1)
            if not (rp and rp.get("ok")):
                continue
            lag = (rp["t_half"] - jt) / 1000
            if lag <= 1.3:
                continue
            k = np.searchsorted(ts, rp["t_half"] + 3000, "right") - 1
            nb, na = A.top_at(books, sm.tok, rp["t_half"] + 3000)
            row = {"slug": slug, "smt": sm.smt, "lag_s": lag, "ml_move": js, "t_det_minus_t_ml_s": (td - jt) / 1000}
            for o in offs:
                sd = A.stale_depth(books, sm.tok, jt + o * 1000, ds, ms[k], nb if ds > 0 else na)
                row[f"sh_{o}"], row[f"hold_{o}"], row[f"exit_{o}"] = sd["sh"], sd["net_usd"], sd["net_exit_usd"]
            sd = A.stale_depth(books, sm.tok, td + 1300, ds, ms[k], nb if ds > 0 else na)
            row["sh_causal"], row["hold_causal"], row["exit_causal"] = sd["sh"], sd["net_usd"], sd["net_exit_usd"]
            rows.append(row)
    R = pd.DataFrame(rows)
    C = pd.DataFrame(causal)
    res = {"n_ml_jumps": len(jumps), "t_det_minus_t_half_s": qs(det_lag),
           "replicated_n_lagging": int(len(R))}
    for scope, gp in (("set_winner", R[R.smt == "tennis_set_winner"]), ("all", R)):
        d = {}
        for o in list(offs) + ["causal"]:
            sh = gp[f"sh_{o}"].sum()
            d[f"exec_{o}"] = {"hold_usd": r2(gp[f"hold_{o}"].sum(), 1), "exit_usd": r2(gp[f"exit_{o}"].sum(), 1),
                              "shares": r2(sh, 0), "hold_c_ps": r2(100 * gp[f"hold_{o}"].sum() / sh) if sh else None,
                              "exit_c_ps": r2(100 * gp[f"exit_{o}"].sum() / sh) if sh else None}
        res[scope] = d
    if len(C):
        cr = {}
        for scope, gp in [("ALL", C)] + list(C.groupby("smt")):
            w = gp.sz
            cr[scope] = {"n_trades": int(len(gp)), "n_matches": int(gp.slug.nunique()), "shares": r2(w.sum(), 0),
                         "median_spread_proxy_px": r2(gp.px.median()),
                         **{f"{c}_c_ps_sizew": r2(np.nansum(gp[c] * w) / w[gp[c].notna()].sum()) for c in ("hold10_c", "exit10_c", "hold60_c", "exit60_c")},
                         **{f"{c}_mean_c": r2(gp[c].mean()) for c in ("hold10_c", "exit10_c", "hold60_c")}}
        res["causal_touch_rule"] = cr
        # cluster bootstrap by match for the all-types hold10 per-share
        sl = C.slug.unique()
        bs = []
        for _ in range(2000):
            pick = RNG.choice(sl, len(sl), replace=True)
            cc = pd.concat([C[C.slug == s_] for s_ in pick])
            bs.append(np.nansum(cc.hold10_c * cc.sz) / cc.sz[cc.hold10_c.notna()].sum())
        res["causal_touch_rule"]["ALL"]["hold10_c_ps_cluster_ci95"] = [r2(np.percentile(bs, 2.5)), r2(np.percentile(bs, 97.5))]
    return res


def clob_latency(max_recs: int = 1_500_000) -> dict:
    x = []
    for i, r in enumerate(L.read("clob")):
        if i >= max_recs:
            break
        ts = r.get("ts")
        if ts and r.get("e") in ("bba", "pc", "t", "b"):
            x.append(r["rt"] - ts)
    x = np.asarray(x, dtype=float)
    if not len(x):
        return {"n": 0}
    return {"n": int(len(x)), "median": r2(np.median(x), 1), "p10": r2(np.percentile(x, 10), 1),
            "p90": r2(np.percentile(x, 90), 1), "p99": r2(np.percentile(x, 99), 1)}


def variant_recount() -> dict:
    return {
        "claimed": 16,
        "items_not_counted": [
            "M1 forward window before vs after the -4 s trim (2 runs; outcome-informed change)",
            "4 stale-depth snapshots (-2/-1/-0.25/+0.5 s) counted as 1",
            "hold vs exit valuation for every P&L table (x2)",
            "7 side-market types x 3 jump cuts reported separately in the cross-market P&L (21 cells) counted as 3",
            "post-outage drop rules (60 s push / 10 s poll), 5c/10c spread filters, 1c/2 s/10 s jump detector",
            "Gamma REST score source tested and dropped",
        ],
        "reviewer_count_lower_bound": 16 + 1 + 3 + 21 - 3 + 1,
        "note": "For the measurement claims this barely matters (effects are 20-40 s); it matters for the "
                "set_winner P&L, which is the best of >= 42 cells (7 types x 3 cuts x hold/exit).",
    }


def hygiene() -> dict:
    gi = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    src = (HERE / "analyze.py").read_text()
    fp = (HERE / "fetch_pbp.py").read_text()
    try:
        rc = subprocess.run(["git", "check-ignore", "-q", "data/live_v2"], cwd=ROOT, capture_output=True).returncode
        ign = {0: True, 1: False}.get(rc)          # 128 = not a git repository here
    except Exception:
        ign = None
    return {"data_dir_gitignored": "data/" in gi, "git_check_ignore_live_v2": ign,
            "analyze_has_time_cutoff": ("CUT" in src) or ("cutoff" in src.lower()),
            "fetch_pbp_default_date_is_today": "dt.datetime.now(dt.timezone.utc).date()" in fp,
            "consequence": "Inputs (data/live_v2, data/live, data/v2_latency/pbp) are not in the public repo, "
                           "analyze.py has no snapshot cutoff (re-running adds hours of data), and fetch_pbp.py "
                           "defaults to the current UTC date, so the stated commands do not reproduce the numbers "
                           "from a clone or on 2026-10-04."}


if __name__ == "__main__":
    o = main()
    print(json.dumps(o, indent=1, default=float))
