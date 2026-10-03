"""Adversarial realism + leakage check of the tier-0 COUNTERFACTUAL (research/v2/tier0).

    .venv/bin/python research/v2/tier0/verify_realism.py

COUNTERFACTUAL WITH ASSUMED DATA. Assumed: licensed live feed + courtside camera, not purchased; parameters
from our measurements. No live ATP/WTA point feed was bought or used. OOS = burned OOS (not blind).

What it does
  1. Reproduces the primary headline with the builder's code (scripts/tier0_backtest.run_one) and with an
     independent re-implementation written here (own coverage, CV lead coupling, depth curve, net cap,
     metrics). Same random draws, so the two must agree to the cent.
  2. Stale-price audit. The jump detector's onset is the first print of the 10 s window before detection,
     and `ref` is a VWAP over [onset-63, onset-3), which spans the previous point(s). A courtside trader lifts
     the book that rests when THIS point ends. We rebuild that price from the prints just before onset
     (mid proxy from the latest bid-side and ask-side prints <= 30 s old) and re-run the primary.
  3. Live cross-check of the per-share edge on the measured stale depth (stale_depth.csv: what sweeping the
     resting quotes 2 s / 1 s / 0.25 s before the reprice actually earned against the new mid).
  4. Timing decomposition. The model draws t_reprice - t_stamp per point and adds a CONSTANT stamp lag, i.e.
     it attributes all the spread of R to the book. The opposite (equally unmeasured) reading puts the spread
     in the umpire stamp: t_reprice - t_bounce constant. Also: the official stamp has 1 s resolution
     (all T_ms end in 000); if it is truncated, R is overstated by 0.5 s on average.
  5. Order-type consistency: an order that cannot see the book (1 s delay) and "never chases" is a limit at
     the stale price + slip, which cannot fill inside the decay window at a half-moved price.
  6. Depth sampling by live MATCH (cluster) instead of i.i.d. points.
  7. Bookkeeping: 50/50 resolutions, fee rates, PREREG/output timestamps, text claims about live data.

Writes research/v2/tier0/verify_out/verify_realism.json
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from scripts import tier0_backtest as B  # noqa: E402
from src import tier0 as T  # noqa: E402

LABEL = ("COUNTERFACTUAL WITH ASSUMED DATA. assumed: licensed live feed + courtside camera, not purchased; "
         "parameters from our measurements. OOS = burned OOS (not blind).")
OUT = ROOT / "research/v2/tier0/verify_out"
OUT.mkdir(parents=True, exist_ok=True)
LAT = ROOT / "research/v2/latency/out"


# ============================================================================ independent re-implementation
def own_cv():
    s = json.loads((ROOT / "results/tracking/summary.json").read_text())["early_call"]
    te, oof = s["precision_recall_test_snapshot"], s["precision_recall_train_oof_snapshot"]
    leads = [0, 25, 50, 100]                      # PREREG: leads above 100 ms not used
    rec = np.array([te[f"{L}ms"]["recall"] for L in leads])
    prec = np.array([(te[f"{L}ms"]["tp"] + oof[f"{L}ms"]["tp"]) /
                     (te[f"{L}ms"]["tp"] + oof[f"{L}ms"]["tp"] + te[f"{L}ms"]["fp"] + oof[f"{L}ms"]["fp"])
                     for L in leads])
    rmono = np.maximum.accumulate(rec[::-1])[::-1]
    return np.array(leads) / 1000.0, rmono, prec


def own_coverage(u: pd.DataFrame, n: int) -> set:
    m = u[u.delay == 1].copy()
    m["day"] = m.start.dt.floor("D")
    m = m.sort_values(["day", "prestart_usd", "cond"], ascending=[True, False, True], kind="stable")
    return set(m.groupby("day").head(n).cond)


def own_depth(u2, u1, u025, upost, tau):
    out = np.where(tau >= 2, u2,
          np.where(tau >= 1, u1 + (u2 - u1) * (tau - 1),
          np.where(tau >= 0.25, u025 + (u1 - u025) * (tau - 0.25) / 0.75,
          np.where(tau >= 0, u025,
          np.where(tau >= -0.5, u025 + (upost - u025) * (-tau / 0.5), 0.0)))))
    return np.maximum(out, 0.0)


def own_net_cap(cond, d0, sh, cap):
    out = sh.copy()
    net = {}
    for i in range(len(sh)):                        # rows are sorted by (cond, ts)
        c = cond[i]
        x = net.get(c, 0.0)
        allow = max(0.0, cap - d0[i] * x)
        out[i] = min(sh[i], allow)
        net[c] = x + d0[i] * out[i]
    return out


def own_sim(J, cov, pool, mix, dr, *, stale="ref", r_mode="sample", r_shift=0.0, fill="decay",
            cluster_rng=None, lag=2.0, phi=0.5, p_event=0.95, net_cap=100.0, trade_cap=1000.0, slip=0.005,
            price="model", live_edge=None, edge_scale=False):
    """price='model': the builder's fill price (stale `ref` + slip, moved by size*mfrac after the reprice).
    price='live': a correct call pays (post-jump price) - e, where e is the per-share edge vs the new mid that
    the FIRST 100 resting shares actually offered on the sampled live point at the same tau (live_edge:
    columns e2, e1, e025 in price units, aligned with `pool`), decaying to 0 over the 0.5 s after the
    reprice. Post-jump price = VWAP [detect, detect+30) (a pricing model only; no decision uses it),
    falling back to ref + size. edge_scale=True scales e by (historical size / live D)."""
    X = J[J.cond.isin(cov)]
    ref = X[stale].to_numpy()
    dirn = X["dir"].to_numpy()
    q0 = np.where(dirn > 0, ref, 1 - ref)
    ok = np.isfinite(ref) & (q0 >= 0.05) & (q0 <= 0.95)
    X, q0, dirn = X[ok], q0[ok], dirn[ok]
    r = X.row.to_numpy()
    n = len(X)
    if cluster_rng is None:
        pidx = np.minimum((dr["pool"][r] * len(pool)).astype(int), len(pool) - 1)
    else:   # one live match per historical match, then a point within it
        slugs = pool.slug.unique()
        conds = X.cond.unique()
        pick = dict(zip(conds, cluster_rng.integers(0, len(slugs), len(conds))))
        members = {k: np.flatnonzero(pool.slug.to_numpy() == s) for k, s in enumerate(slugs)}
        sl = X.cond.map(pick).to_numpy()
        pidx = np.array([members[k][min(int(u * len(members[k])), len(members[k]) - 1)]
                         for k, u in zip(sl, dr["pool"][r])])
    leads, rmono, prec_l = own_cv()
    p_out = np.where(X.men.to_numpy(), mix["men"]["out"], mix["women"]["out"])
    is_out = dr["end"][r] < p_out
    u = dr["lead"][r]
    callable_ = rmono[None, :] >= u[:, None]                     # (n, leads)
    called = callable_[:, 0]
    k = callable_.sum(1) - 1
    early = is_out & called
    lead = np.where(early, leads[np.maximum(k, 0)], 0.0)
    prec = np.where(early, prec_l[np.maximum(k, 0)], p_event)
    lat = X.region.map(T.REGION_MS).to_numpy(float) / 1000
    arrival = -lead + 0.020 + lat + 0.002 + X.delay.to_numpy(float)
    R = pool.R.to_numpy()
    if r_mode == "sample":
        t_rep = R[pidx] + r_shift + lag
    elif r_mode == "const":                                         # spread of R is umpire-stamp noise
        t_rep = np.full(n, np.median(R) + r_shift + lag)
    else:
        raise ValueError(r_mode)
    tau = t_rep - arrival
    scale = np.minimum(1.0, X.volume.to_numpy(float) / pool.V_live.to_numpy()[pidx])
    g = lambda c: pool[c].to_numpy()[pidx]  # noqa: E731
    u2, u1, u025, upost = g("usd_2"), g("usd_1"), g("usd_025"), g("usd_post")
    correct = dr["prec"][r] < prec
    size = X["size"].to_numpy()
    mfrac = np.where(tau >= 0, 0.0, np.where(tau >= -0.5, 0.5 - tau, 1.0))
    qc = q0 + size * mfrac + slip
    if price == "live":
        post = X["post30"].to_numpy() if "post30" in X else np.full(n, np.nan)
        post_tok = np.where(dirn > 0, post, 1 - post)
        post_tok = np.where(np.isfinite(post_tok), post_tok, q0 + size)
        e = own_depth(*(live_edge[k].to_numpy()[pidx] for k in ("e2", "e1", "e025")), np.zeros(n), tau)
        if edge_scale:
            e = e * size / pool.D.to_numpy()[pidx]
        qc = np.clip(post_tok - e, 0.01, 0.99)
    dc = own_depth(u2, u1, u025, upost, tau) * scale * phi
    fill_ok = (tau >= -0.5) if fill == "decay" else (tau >= 0)
    shc = np.where(fill_ok, np.minimum(trade_cap / qc, dc / qc), 0.0)
    qw = np.clip((1 - q0) - size * mfrac, 0.01, 0.99) + slip
    dw = own_depth(u2, u1, u025, upost, np.maximum(tau, 0)) * scale
    shw = np.minimum(trade_cap / qw, dw / qw)
    q = np.where(correct, qc, qw)
    sh = np.where(correct, shc, shw)
    tok0 = np.where(correct, dirn > 0, dirn < 0)
    res0 = X.res0.to_numpy(float)
    pay = np.where(tok0, res0, 1 - res0)
    fee = X.fee_rate.to_numpy(float) * q * (1 - q)
    D = pd.DataFrame({"cond": X.cond.to_numpy(), "ts": X.onset_ts.to_numpy(), "q": q, "sh_raw": sh,
                      "d0": np.where(tok0, 1.0, -1.0), "pnl_ps": pay - q - fee, "correct": correct, "tau": tau,
                      "size": size, "res0": res0, "drift": (X[stale].to_numpy() - X["ref"].to_numpy()) * dirn})
    D = D.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    D["shares"] = own_net_cap(D.cond.to_numpy(), D.d0.to_numpy(), D.sh_raw.to_numpy(), net_cap)
    D["pnl"] = D.shares * D.pnl_ps
    D["date"] = pd.to_datetime(D.ts, unit="s", utc=True).dt.floor("D")
    return D


def own_metrics(D, days, n_boot=1000, seed=0):
    tr = D[D.shares > 1e-9]
    daily = tr.groupby("date").pnl.sum().reindex(days, fill_value=0.0)
    eq = daily.cumsum()
    g = tr.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n_boot, len(g)))
    ps = g.p.to_numpy()[idx].sum(1) / g.s.to_numpy()[idx].sum(1) * 100
    return {"calls": int(len(D)), "trades": int(len(tr)),
            "fill_rate": round(float(tr.correct.sum() / max(len(D), 1)), 4),
            "per_share_c": round(float(tr.pnl.sum() / tr.shares.sum() * 100), 3),
            "per_share_ci95_c": [round(float(np.percentile(ps, 2.5)), 3), round(float(np.percentile(ps, 97.5)), 3)],
            "pnl_usd": round(float(tr.pnl.sum()), 1), "pnl_per_day_usd": round(float(tr.pnl.sum() / len(days)), 1),
            "sharpe_ann": round(float(daily.mean() / daily.std() * np.sqrt(365)), 2) if daily.std() > 0 else None,
            "max_dd_usd": round(float((eq - eq.cummax()).min()), 1), "worst_day_usd": round(float(daily.min()), 1),
            "pnl_wrong_usd": round(float(tr[~tr.correct].pnl.sum()), 1)}


# ================================================================================== stale-price rebuild
def pre_onset_prices(J: pd.DataFrame, conds: set) -> pd.DataFrame:
    """Per jump (in `conds`): mid proxy and last print just before onset, VWAP [onset-10, onset), and the
    post-jump VWAP [detect, detect+30) (diagnostic only: it is NOT available to a trader)."""
    Jc = J[J.cond.isin(conds)]
    out = {k: np.full(len(J), np.nan) for k in ("mid_pre", "last_pre", "vwap10", "post30", "gap_pre")}
    for c, g in Jc.groupby("cond", sort=False):
        P = pr_groups.get(c)
        if P is None:
            continue
        ts, p, d, usd = P.ts.to_numpy(float), P.p.to_numpy(), P.dir.to_numpy(), P.usd.to_numpy()
        pv = np.concatenate([[0.0], np.cumsum(p * usd)]); vv = np.concatenate([[0.0], np.cumsum(usd)])
        ask_i = np.flatnonzero(d > 0); bid_i = np.flatnonzero(d < 0)
        for j, on, det in zip(g.index.to_numpy(), g.onset_ts.to_numpy(float), g.detect_ts.to_numpy(float)):
            b = np.searchsorted(ts, on, "left")          # prints strictly before onset: [0, b)
            if b == 0:
                continue
            gap = on - ts[b - 1]
            out["gap_pre"][j] = gap
            if gap <= 30:
                out["last_pre"][j] = p[b - 1]
                ka = np.searchsorted(ask_i, b, "left") - 1
                kb = np.searchsorted(bid_i, b, "left") - 1
                a_p = p[ask_i[ka]] if ka >= 0 and on - ts[ask_i[ka]] <= 30 else np.nan
                b_p = p[bid_i[kb]] if kb >= 0 and on - ts[bid_i[kb]] <= 30 else np.nan
                out["mid_pre"][j] = (a_p + b_p) / 2 if np.isfinite(a_p) and np.isfinite(b_p) and a_p >= b_p else p[b - 1]
            a = np.searchsorted(ts, on - 10, "left")
            if vv[b] - vv[a] > 0:
                out["vwap10"][j] = (pv[b] - pv[a]) / (vv[b] - vv[a])
            lo = np.searchsorted(ts, det, "left"); hi = np.searchsorted(ts, det + 30, "left")
            if vv[hi] - vv[lo] > 0:
                out["post30"][j] = (pv[hi] - pv[lo]) / (vv[hi] - vv[lo])
    return pd.DataFrame(out, index=J.index)


pr_groups: dict = {}


# ============================================================================= live-day checks (2026-10-03)
def _live_books(depth: bool):
    """Moneyline books + last-trade prints of the 9 live WTA matches behind m1_points.csv / stale_depth.csv
    (public Polymarket CLOB websocket, recorded by research/v2/latency). ~40 s to load."""
    sys.path.insert(0, str(ROOT / "research/v2/latency"))
    import load as L  # noqa: E402
    m1 = pd.read_csv(LAT / "m1_points.csv")
    meta = L.load_meta()
    ev = L.events_table(meta)
    e = ev[ev.slug.isin(set(m1.slug))].drop_duplicates("slug").set_index("slug")
    toks = set(e.tok0) | set(e.tok1)
    books = L.Books(toks, set(e.tok0) if depth else set(), dict(zip(meta.ra, meta.tok)))
    return m1, e, books


def live_first_shares(books_bundle) -> pd.DataFrame:
    """Per live point with D >= 3c: per-share edge vs the new mid (mid at t_reprice + 3 s) of the FIRST 100 and
    200 shares resting at prices better than the new mid, 2 s / 1 s / 0.25 s before the reprice."""
    f = OUT / "live_first_shares.csv"
    if f.exists():
        return pd.read_csv(f)
    m1, e, books = books_bundle
    P = m1[(m1.ok == True) & (m1.D >= 0.03 - 1e-9)]  # noqa: E712
    rows = []
    for r in P.itertuples():
        tok = e.loc[r.slug].tok0
        t, mid, _, _ = books.mid_series(tok)
        d = 1 if r.winner == 0 else -1
        m_new = mid[np.searchsorted(t, r.t_book + 3000, "right") - 1]
        row = {"slug": r.slug, "n": r.n, "D": r.D}
        for lab, tq in (("2", r.t_book - 2000), ("1", r.t_book - 1000), ("025", r.t_book - 250)):
            bids, asks = books.book_at(tok, tq)
            if d > 0:
                lv = sorted((p, s_) for p, s_ in asks.items() if p < m_new)
                ed = [m_new - p for p, _ in lv]
            else:
                lv = sorted(((p, s_) for p, s_ in bids.items() if p > m_new), reverse=True)
                ed = [p - m_new for p, _ in lv]
            for N in (100, 200):
                left, gsum = N, 0.0
                for (p, s_), x in zip(lv, ed):
                    take = min(s_, left)
                    gsum += take * x
                    left -= take
                    if left <= 0:
                        break
                got = N - left
                row[f"sh{N}_{lab}"] = got
                row[f"e{N}_{lab}"] = gsum / got if got > 0 else 0.0
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(f, index=False)
    return out


def live_detector_check(books_bundle) -> pd.DataFrame:
    """Run the historical >= 4c detector (src.tiers.jump_onsets) on the live-day prints, then compare its
    stale-price proxies with the real quote mid just before the last same-direction official WTA point whose
    book reprice lies in [onset-63, detect+0.5] s."""
    f = OUT / "live_detector_check.csv"
    if f.exists():
        return pd.read_csv(f)
    from src.tiers import jump_onsets
    m1, e, books = books_bundle
    P = m1[m1.ok == True].copy()  # noqa: E712
    P["tb"], P["tb1"], P["d"] = P.t_book / 1000, P.t_book_first / 1000, np.where(P.winner == 0, 1, -1)
    rows = []
    for s, r in e.iterrows():
        t, mid, _, _ = books.mid_series(r.tok0)
        t = np.asarray(t); mid = np.asarray(mid)
        mid_at = lambda x: mid[np.searchsorted(t, x * 1000, "right") - 1]  # noqa: E731
        tr = []
        for tok, sgn in ((r.tok0, 1), (r.tok1, -1)):
            for rt, p, sz, side in books.trades.get(tok, []):
                if np.isfinite(p):
                    tr.append((rt / 1000, p if sgn == 1 else 1 - p, sz * p, (1 if side == "BUY" else -1) * sgn))
        if len(tr) < 20:
            continue
        tr = np.array(sorted(tr))
        ts, p, usd, dr = tr[:, 0], tr[:, 1], tr[:, 2], tr[:, 3]
        pv = np.concatenate([[0], np.cumsum(p * usd)]); vv = np.concatenate([[0], np.cumsum(usd)])
        vw = lambda lo, hi: ((pv[np.searchsorted(ts, hi)] - pv[np.searchsorted(ts, lo)]) /  # noqa: E731
                             (vv[np.searchsorted(ts, hi)] - vv[np.searchsorted(ts, lo)])
                             if vv[np.searchsorted(ts, hi)] > vv[np.searchsorted(ts, lo)] else np.nan)
        pts = P[P.slug == s]
        for on, d, sz, det in jump_onsets(ts, p, usd):
            if not (t[0] / 1000 + 60 <= on - 63 and det + 10 <= t[-1] / 1000 - 30):
                continue
            win = pts[(pts.tb >= on - 63) & (pts.tb <= det + 0.5)]
            same = win[win.d == d]
            row = {"slug": s, "onset": on, "detect": det, "dir": d, "size": sz, "ref": vw(on - 63, on - 3),
                   "ref_short": vw(on - 33, on - 1), "n_pts_in_window": len(win), "n_pts_same_dir": len(same)}
            if len(same):
                lp = same.iloc[-1]
                row.update({"pt_pre_mid": mid_at(lp.tb1 - 0.25), "pt_post_mid": mid_at(lp.tb + 3), "pt_D": lp.D})
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(f, index=False)
    return out


def main():
    res = {"label": LABEL}
    c = B.context()
    pools, mix = c["pools"], c["mix"]
    calib = c["calib"]["central"]["stamp_lag_s"]
    official = json.loads((T.OUT / "results.json").read_text())

    # ---------------------------------------------------------------- 1. reproduce the headline
    rep = {}
    for per in ("IS", "burned_OOS"):
        m = B.run_one(T.PRIMARY, per)
        P = c["per"][per]
        dr = T.draws(len(P["J"]), P["seed"])
        cov = own_coverage(P["M"], 10)
        D = own_sim(P["J"], cov, pools["D>=3c"], mix, dr)
        days = T.period_days(P["J"], "delay1")
        om = own_metrics(D, days)
        rep[per] = {"builder_code": {k: round(m[k], 3) for k in ("per_share_c", "pnl_usd", "pnl_per_day_usd", "sharpe_ann")},
                    "results_json": {k: official["primary"][per][k] for k in ("per_share_c", "pnl_usd", "pnl_per_day_usd", "sharpe_ann")},
                    "independent": om}
    res["1_reproduction"] = rep
    print(json.dumps(rep, indent=1))

    # ---------------------------------------------------------------- 2. stale-price audit (primary coverage)
    global pr_groups
    stale_rep = {}
    Jx = {}
    for per, path in (("IS", ROOT / "data/is_prints.parquet"), ("burned_OOS", ROOT / "data/locked/oos_prints.parquet")):
        P = c["per"][per]
        J = P["J"].copy()
        cov = own_coverage(P["M"], 10)
        pr = pq.read_table(path, columns=["cond", "ts", "p", "dir", "usd"],
                           filters=[("cond", "in", sorted(cov))]).to_pandas()
        pr_groups = {k: g.sort_values("ts", kind="stable") for k, g in pr.groupby("cond", sort=False)}
        del pr
        extra = pre_onset_prices(J, cov)
        J = J.join(extra)
        Jx[per] = J
        X = J[J.cond.isin(cov)]
        q0 = np.where(X.dir > 0, X.ref, 1 - X.ref)
        X = X[np.isfinite(X.ref) & (q0 >= 0.05) & (q0 <= 0.95)]
        dd = X["dir"].to_numpy()
        row = {"n_covered_in_zone_jumps": int(len(X))}
        for k in ("ref", "ref_short", "vwap10", "mid_pre", "last_pre"):
            ok = X[k].notna() & X.post30.notna()
            mv = (X.post30[ok] - X[k][ok]) * dd[ok.to_numpy()]
            row[f"move_post30_minus_{k}_c"] = {"n": int(ok.sum()), "mean": round(float(mv.mean() * 100), 3),
                                               "median": round(float(mv.median() * 100), 3)}
        ok = X.mid_pre.notna() & X.post30.notna()
        mv = (X.post30[ok] - X.mid_pre[ok]) * dd[ok.to_numpy()]
        row["single_point_move_share_lt_4c"] = round(float((mv < 0.04).mean()), 3)
        row["single_point_move_share_lt_2c"] = round(float((mv < 0.02).mean()), 3)
        drift = (X.mid_pre - X.ref) * dd
        row["drift_ref_to_mid_pre_c"] = {"mean": round(float(drift.mean() * 100), 3), "median": round(float(drift.median() * 100), 3),
                                         "share_gt_2c": round(float((drift > 0.02).mean()), 3)}
        row["mid_pre_available_share"] = round(float(X.mid_pre.notna().mean()), 3)
        row["gap_last_print_before_onset_s_median"] = round(float(X.gap_pre.median()), 2)
        stale_rep[per] = row
    res["2_stale_price_audit"] = stale_rep
    print(json.dumps(stale_rep, indent=1))

    # primary re-run with the pre-onset stale price (builder's code; stale column swapped)
    def run_builder(sc, per, J):
        P = c["per"][per]
        dr = T.draws(len(J), P["seed"])
        calls = T.simulate(J, P["M"], sc, dr, pools, c["cvs"], mix)
        return T.metrics(calls, T.period_days(J, sc.regime))

    keys = ("n_calls", "n_trades", "fill_rate", "per_share_c", "per_share_ci95_c", "pnl_usd", "pnl_per_day_usd",
            "sharpe_ann", "max_dd_usd", "pnl_wrong_usd")
    stale_runs = {}
    for per in ("IS", "burned_OOS"):
        J = Jx[per]
        J = J.assign(mid_pre_fb=J.mid_pre.fillna(J.ref_short).fillna(J.ref))
        stale_runs[per] = {}
        for k in ("ref", "ref_short", "vwap10", "mid_pre", "mid_pre_fb"):
            m = run_builder(replace(T.PRIMARY, stale=k), per, J)
            stale_runs[per][k] = {kk: (np.round(m[kk], 3).tolist() if isinstance(m[kk], list) else round(float(m[kk]), 3)) for kk in keys}
    res["2b_primary_by_stale_price"] = stale_runs
    print(json.dumps(stale_runs, indent=1))

    # ---------------------------------------------------------------- 3. live per-share edge on stale depth
    d = pd.read_csv(LAT / "stale_depth.csv")
    d3 = d[d.D >= 0.03 - 1e-9]
    live = {}
    for tag, sh, edge, net in (("pre2s", "sh_pre2s", "edge_usd_pre2s", "net_usd_pre2s"),
                               ("pre1s", "sh_pre1s", "edge_usd_pre1s", "net_usd_pre1s"),
                               ("pre025s", "sh_pre", "edge_usd_pre", "net_usd_pre")):
        live[tag] = {"n_points": int(len(d3)), "share_weighted_edge_c": round(float(d3[edge].sum() / d3[sh].sum() * 100), 3),
                     "share_weighted_net_after_fee_c": round(float(d3[net].sum() / d3[sh].sum() * 100), 3),
                     "median_point_net_usd": round(float(d3[net].median()), 2),
                     "mean_point_net_usd": round(float(d3[net].mean()), 2),
                     "median_point_D_c": round(float(d3.D.median() * 100), 2)}
    res["3_live_stale_depth_edge"] = live
    print(json.dumps(live, indent=1))

    # ---------------------------------------------------------------- 3b. live day: first-100-share edge, detector check
    bundle = None
    if not ((OUT / "live_first_shares.csv").exists() and (OUT / "live_detector_check.csv").exists()):
        bundle = _live_books(depth=True)
    FS = live_first_shares(bundle)
    LD = live_detector_check(bundle)
    fs = {}
    for lab in ("2", "1", "025"):
        for N in (100, 200):
            w = FS[f"sh{N}_{lab}"]
            fs[f"t-{lab}s_first{N}"] = {"share_points_full": round(float((w >= N).mean()), 3),
                                        "edge_c_share_weighted": round(float((FS[f"e{N}_{lab}"] * w).sum() / w.sum() * 100), 3),
                                        "edge_c_median_point": round(float(FS.loc[w > 0, f"e{N}_{lab}"].median() * 100), 3)}
    fs["live_D_c_mean"] = round(float(FS.D.mean() * 100), 3)
    Y = LD[LD.pt_pre_mid.notna()].copy()
    true_edge = (Y.pt_post_mid - Y.pt_pre_mid) * Y.dir * 100
    det = {"n_detector_jumps": int(len(LD)), "n_with_same_dir_official_point": int(len(Y)),
           "share_ge2_points_in_window": round(float((LD.n_pts_in_window >= 2).mean()), 3),
           "true_single_point_mid_move_c": {"mean": round(float(true_edge.mean()), 3), "median": round(float(true_edge.median()), 3),
                                            "share_lt_4c": round(float((true_edge < 4).mean()), 3)}}
    for k in ("ref", "ref_short"):
        err = (Y.pt_pre_mid - Y[k]) * Y.dir * 100
        det[f"stale_proxy_{k}_minus_true_pre_mid_c (>0 = proxy overstates edge)"] = {
            "n": int(err.notna().sum()), "mean": round(float(err.mean()), 3), "median": round(float(err.median()), 3)}
    res["3b_live_day"] = {"first_shares_edge_vs_new_mid": fs, "detector_vs_official_points": det}
    print(json.dumps(res["3b_live_day"], indent=1))
    # 3c. the participants who really trade in that window: prints landing 0-0.5 s before the reprice
    tt = pd.read_csv(LAT / "trades_around_reprice.csv")
    ft = {}
    for lab, sub in (("all_points", tt), ("D>=3c", tt[tt.D >= 0.03 - 1e-9])):
        w = sub[(sub.dt_s >= -0.5) & (sub.dt_s < 0) & sub.with_move]
        ft[lab] = {"n_prints": int(len(w)), "gross_c": round(float((w.edge_vs_new_mid * w.sh).sum() / w.sh.sum() * 100), 3),
                   "net_c": round(float(((w.edge_vs_new_mid - w.fee) * w.sh).sum() / w.sh.sum() * 100), 3)}
    mdl = {}
    for per in ("IS", "burned_OOS"):
        _, calls = B.run_one(T.PRIMARY, per, keep=True)
        a = calls[(calls.shares > 1e-9) & calls.correct & (calls.tau >= 0)]
        mdl[per] = {"n": int(len(a)), "gross_c": round(float(((a.payout - a.q) * a.shares).sum() / a.shares.sum() * 100), 3),
                    "net_c": round(float((a.pnl).sum() / a.shares.sum() * 100), 3)}
    res["3c_fast_tier_vs_model"] = {"measured_fast_tier_prints_landing_[-0.5,0)_with_move": ft,
                                    "model_correct_fills_before_reprice": mdl}
    print(json.dumps(res["3c_fast_tier_vs_model"], indent=1))
    pool3 = pools["D>=3c"]
    LE = pool3[["slug", "n"]].merge(FS[["slug", "n", "e100_2", "e100_1", "e100_025"]], on=["slug", "n"], how="left",
                                    validate="one_to_one").fillna(0.0)
    LE = LE.rename(columns={"e100_2": "e2", "e100_1": "e1", "e100_025": "e025"})

    # ---------------------------------------------------------------- 4-6. timing / order type / cluster
    var = {}
    pool = pools["D>=3c"]
    for per in ("IS", "burned_OOS"):
        P = c["per"][per]
        J = Jx[per].assign(mid_pre_fb=lambda z: z.mid_pre.fillna(z.ref_short).fillna(z.ref))
        dr = T.draws(len(J), P["seed"])
        cov = own_coverage(P["M"], 10)
        days = T.period_days(J, "delay1")
        runs = {
            "primary (reproduced)": {},
            "stamp 1 s resolution truncated: R - 0.5 s": {"r_shift": -0.5},
            "R spread = umpire noise: t_reprice - t_bounce constant (lag 2.0)": {"r_mode": "const"},
            "R spread = umpire noise, calibrated lag 3.14": {"r_mode": "const", "lag": calib},
            "limit order at stale+slip (no decay-window fills)": {"fill": "limit"},
            "depth/timing sampled by live match (cluster)": {"cluster_rng": np.random.default_rng(7)},
            "stale = mid_pre (fallback ref_short, ref)": {"stale": "mid_pre_fb"},
            "mid_pre + limit order": {"stale": "mid_pre_fb", "fill": "limit"},
            "mid_pre + limit + R - 0.5 s": {"stale": "mid_pre_fb", "fill": "limit", "r_shift": -0.5},
            "mid_pre + limit, calibrated lag 3.14 (sampled R)": {"stale": "mid_pre_fb", "fill": "limit", "lag": calib},
            "mid_pre + limit, umpire-noise reading, lag 3.14": {"stale": "mid_pre_fb", "fill": "limit", "r_mode": "const", "lag": calib},
            "LIVE-PRICED: fill = post - edge of first 100 live shares": {"price": "live", "live_edge": LE},
            "LIVE-PRICED, edge scaled by size/D": {"price": "live", "live_edge": LE, "edge_scale": True},
            "LIVE-PRICED + R - 0.5 s": {"price": "live", "live_edge": LE, "r_shift": -0.5},
            "LIVE-PRICED, calibrated lag 3.14": {"price": "live", "live_edge": LE, "lag": calib},
            "LIVE-PRICED, umpire-noise reading, lag 2.0": {"price": "live", "live_edge": LE, "r_mode": "const"},
            "LIVE-PRICED, umpire-noise reading, lag 3.14": {"price": "live", "live_edge": LE, "r_mode": "const", "lag": calib},
            "LIVE-PRICED, phi 0.25": {"price": "live", "live_edge": LE, "phi": 0.25},
            "LIVE-PRICED, p_event 0.99": {"price": "live", "live_edge": LE, "p_event": 0.99},
        }
        var[per] = {}
        for name, kw in runs.items():
            D = own_sim(J, cov, pool, mix, dr, **kw)
            var[per][name] = own_metrics(D, days)
        # where the primary's P&L comes from
        D = own_sim(J, cov, pool, mix, dr)
        tr = D[D.shares > 1e-9]
        bins = pd.cut(tr.tau, [-0.5, 0, 0.5, 1, 2, 99], right=False)
        var[per]["primary_pnl_by_tau_bucket_usd"] = {str(k): v for k, v in tr.groupby(bins, observed=True).pnl.sum().round(0).to_dict().items()}
        sb = pd.cut(tr["size"], [0.04, 0.05, 0.07, 0.10, 1])
        var[per]["primary_per_share_c_by_jump_size"] = (tr.groupby(sb, observed=True).apply(
            lambda z: z.pnl.sum() / z.shares.sum() * 100, include_groups=False).round(2).rename(index=str).to_dict())
        half = tr.res0 == 0.5
        var[per]["primary_5050_resolution_trades"] = int(half.sum())
        var[per]["primary_5050_resolution_pnl_usd"] = round(float(tr[half].pnl.sum()), 1)
    res["4_variants"] = {p: {k: (v if isinstance(v, dict) and "per_share_c" not in v else v) for k, v in d_.items()}
                         for p, d_ in var.items()}
    for per in var:
        print(per)
        for k, v in var[per].items():
            if isinstance(v, dict) and "per_share_c" in v:
                print(f"  {k:72s} {v['per_share_c']:6.2f}c {v['per_share_ci95_c']}  ${v['pnl_per_day_usd']:7.1f}/d  "
                      f"Sh {v['sharpe_ann']}  fill {v['fill_rate']}")
            else:
                print("  ", k, v)

    # ---------------------------------------------------------------- 7. bookkeeping
    mt = {str(p.relative_to(ROOT)): pd.Timestamp(p.stat().st_mtime, unit="s", tz="UTC").isoformat()
          for p in [ROOT / "research/v2/tier0/PREREG.md", ROOT / "research/v2/tier0/DEVIATIONS.md",
                    ROOT / "research/v2/tier0/RESULTS.md", ROOT / "src/tier0.py", ROOT / "scripts/tier0_backtest.py",
                    *sorted((ROOT / "results/tier0").glob("*.*"))]}
    log = [l for l in (ROOT / "results/oos_peeks.log").read_text().splitlines() if "tier0" in l]
    claims = []
    pat = re.compile(r"(used|using|with|from)\s+(the\s+)?(real\s+|official\s+)?live\s+(atp|wta)", re.I)
    for f in list((ROOT / "research/v2/tier0").glob("*.md")) + [ROOT / "src/tier0.py", ROOT / "scripts/tier0_backtest.py",
                                                                  ROOT / "results/tier0/results.json"]:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if pat.search(line) and not re.search(r"not|never|no live|did not", line, re.I):
                claims.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:160]}")
    grid = pd.read_csv(T.OUT / "grid.csv", usecols=["cv", "stamp_lag", "phi", "coverage", "p_event", "net_cap", "period"])
    res["7_bookkeeping"] = {"mtimes_utc": mt, "oos_peeks_tier0": log, "affirmative_live_data_claims": claims,
                            "grid_levels": {k: sorted(map(float if k != "cv" else str, grid[k].unique())) for k in
                                            ("cv", "stamp_lag", "phi", "coverage", "p_event", "net_cap")},
                            "grid_rows": int(len(grid))}
    print(json.dumps(res["7_bookkeeping"], indent=1))
    (OUT / "verify_realism.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
