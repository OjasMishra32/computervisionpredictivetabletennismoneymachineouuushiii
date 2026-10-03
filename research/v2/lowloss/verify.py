"""Independent audit of the v2-safe (lowloss) pipeline. Reads only; writes one JSON (--out).

    .venv/bin/python research/v2/lowloss/verify.py              # parts a + b, ~3-4 min, 1 process
    .venv/bin/python research/v2/lowloss/verify.py --part a     # burned OOS recompute only
    .venv/bin/python research/v2/lowloss/verify.py --part b     # IS selection checks only

(a) Burned OOS, recomputed without scripts/lowloss_test.py or its caches:
    prints = is_prints + locked/oos_prints (only the columns v2.run needs), ends = universe().end,
    and the CANONICAL src.v2.run(causal=True) with v2.POLICY swapped for
    replace(POLICY, name="v2_safe_n50", net_cap=50) (PREREG.md "The frozen rule"). The same feature
    table is also simulated with the frozen v2 policy and must equal data/v2_trades_is_oos.parquet.
    Metrics are re-implemented here (not lowloss_test.book_metrics): per-trade P&L is rebuilt from
    the raw print fields (dir*(res-p) - fee_rate*q*(1-q)), the book is matches with universe().start
    >= 2026-08-25 14:15 UTC, the calendar is 2026-08-25 .. last book trade date. Also: invariants of
    the net cap, a day-clustered CI, and the profitable-day share with P&L booked on the match's
    resolution date instead of the entry date.
(b) IS selection (GRID.md), from lowloss_select's IS-only feature cache: re-simulate the 24 variants,
    re-implement the walk-forward choice and the sigma history, check both use months < m only, and
    redo the choice with each trade's P&L dated at its match's resolution (strictly causal at a month
    boundary). Also: how often the daily-stop mark uses a resolution before the match had ended.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src import v2  # noqa: E402
from src.tape import universe  # noqa: E402

E = v2.E
CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")
COLS = ["cond", "ts", "p", "dir", "usd", "wallet", "spread", "fee_rate", "delay", "res",
        "mo5", "mo15", "mo30", "mo_res"]
Z = 1.959963984540054


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------------- shared metric code
def wilson_lo(k: int, n: int) -> float:
    ph = k / n
    den = 1 + Z * Z / n
    return float(((ph + Z * Z / (2 * n)) - Z * np.sqrt(ph * (1 - ph) / n + Z * Z / (4 * n * n))) / den)


def cluster_ci(tr: pd.DataFrame, key: str, n_boot: int, seed: int) -> list[float]:
    g = tr.groupby(key).agg(p=("pnl_x", "sum"), s=("shares", "sum"))
    P, S = g.p.to_numpy(), g.s.to_numpy()
    rng = np.random.default_rng(seed)
    k = len(g)
    bs = np.empty(n_boot)
    for b in range(n_boot):
        i = rng.integers(0, k, k)
        bs[b] = P[i].sum() / S[i].sum()
    return [float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)]


def book_stats(tr: pd.DataFrame, start: pd.Timestamp, ends_by_cond: pd.Series) -> dict:
    """tr has pnl_x (rebuilt P&L), shares, ts, cond."""
    tr = tr.copy()
    tr["d_entry"] = pd.to_datetime(tr.ts, unit="s", utc=True).dt.floor("D")
    last = tr.d_entry.max()
    days = pd.date_range(start, last, freq="D", tz="UTC")
    d = tr.groupby("d_entry").pnl_x.sum().reindex(days, fill_value=0.0)
    assert abs(d.sum() - tr.pnl_x.sum()) < 1e-6, "entry dates outside calendar"
    act = tr.groupby("d_entry").pnl_x.sum()
    # resolution-date booking: a position's P&L is realised when its match ends
    endt = tr.cond.map(ends_by_cond)
    res_t = np.maximum(endt.map(lambda x: x.timestamp() if pd.notna(x) else np.nan).fillna(tr.ts), tr.ts)
    tr["d_res"] = pd.to_datetime(res_t, unit="s", utc=True).dt.floor("D")
    dr = tr.groupby("d_res").pnl_x.sum()
    dr_in = dr.reindex(days, fill_value=0.0)
    eq = d.cumsum().to_numpy()
    dd = float((eq - np.maximum.accumulate(np.maximum(eq, 0))).min())
    k_act, n_act = int((act > 0).sum()), int(len(act))
    return {
        "n_trades": int(len(tr)), "n_matches": int(tr.cond.nunique()),
        "calendar": [str(days[0].date()), str(days[-1].date())], "calendar_days": int(len(days)),
        "profitable_days": int((d > 0).sum()), "profitable_days_pct": float((d > 0).mean() * 100),
        "active_days": n_act, "profitable_active_days": k_act,
        "profitable_active_days_pct": float(k_act / n_act * 100),
        "wilson95_lo_active_pct": wilson_lo(k_act, n_act) * 100,
        "worst_day_usd": float(d.min()), "max_dd_usd": dd,
        "pnl_usd": float(tr.pnl_x.sum()), "shares": float(tr.shares.sum()),
        "per_share_c": float(tr.pnl_x.sum() / tr.shares.sum() * 100),
        "per_share_ci_c_match_seed0_1000": cluster_ci(tr, "cond", 1000, 0),
        "per_share_ci_c_match_seed7_10000": cluster_ci(tr, "cond", 10000, 7),
        "per_share_ci_c_day_seed7_10000": cluster_ci(tr, "d_entry", 10000, 7),
        "profitable_matches_pct": float((tr.groupby("cond").pnl_x.sum() > 0).mean() * 100),
        "resolution_booking": {
            "days_resolved_after_calendar": int((dr.index > days[-1]).sum()),
            "profitable_days_in_calendar": int((dr_in > 0).sum()),
            "profitable_days_pct": float((dr_in > 0).mean() * 100),
            "worst_day_usd": float(dr_in.min()),
        },
    }


# ------------------------------------------------------------------------------- part (a)
def part_a(res: dict):
    t0 = time.time()
    u = universe()
    ends = u.set_index("cond").end
    start_of = u.set_index("cond").start
    assert (u.oos == (u.start >= CUT)).all(), "universe().oos differs from start >= cutoff"
    log("loading prints (", len(COLS), "columns )")
    p = pd.concat([pd.read_parquet(ROOT / f, columns=COLS) for f in
                   ("data/is_prints.parquet", "data/locked/oos_prints.parquet")], ignore_index=True)
    log(f"{len(p):,} prints")

    V2, SAFE = v2.POLICY, replace(v2.POLICY, name="v2_safe_n50", net_cap=50)
    captured = {}
    orig = E.simulate

    def sim_both(f, pol, measure, fee_mode, whist, sigma_by_month=None):
        assert pol is SAFE
        out = orig(f, pol, measure, fee_mode, whist, sigma_by_month)
        captured["v2"] = orig(f, V2, measure, fee_mode, whist, sigma_by_month)
        captured["f_rows"] = len(f)
        return out

    E.simulate, v2.POLICY = sim_both, SAFE
    try:
        tr_safe, _ = v2.run(p, ends, causal=True)
    finally:
        E.simulate, v2.POLICY = orig, V2
    tr_v2 = captured["v2"]
    del p
    log(f"canonical v2.run done in {time.time() - t0:.0f}s: v2 {len(tr_v2):,} trades, v2-safe {len(tr_safe):,}")

    def same(a, b):
        ka = a.sort_values(["cond", "ts", "shares"], kind="stable")[["ts", "shares", "pnl"]].to_numpy()
        kb = b.sort_values(["cond", "ts", "shares"], kind="stable")[["ts", "shares", "pnl"]].to_numpy()
        return len(a) == len(b) and bool(np.allclose(ka, kb, rtol=1e-9, atol=1e-9))

    ref_v2 = pd.read_parquet(ROOT / "data/v2_trades_is_oos.parquet", columns=["cond", "ts", "shares", "pnl"])
    theirs = pd.read_parquet(ROOT / "data/v2_lowloss/trades_a_v2_safe.parquet", columns=["cond", "ts", "shares", "pnl"])
    res["a_pipeline"] = {"v2_equals_canonical_v2_trades_is_oos": same(tr_v2, ref_v2),
                         "v2_safe_equals_lowloss_test_trades_a_v2_safe": same(tr_safe, theirs),
                         "n_v2": int(len(tr_v2)), "n_v2_safe": int(len(tr_safe)), "feature_rows": captured["f_rows"]}
    log("pipeline", res["a_pipeline"])

    out = {}
    for name, tr in (("v2", tr_v2), ("v2_safe", tr_safe)):
        tr = tr[tr.month >= E.EVAL_START].copy()
        # rebuild P&L from raw print fields
        q = np.where(tr.dir > 0, tr.p, 1 - tr.p)
        assert np.allclose(q, tr.q)
        fee = tr.fee_rate.astype(float).to_numpy() * q * (1 - q)
        ps = tr.dir.to_numpy() * (tr.res.to_numpy() - tr.p.to_numpy()) - fee
        n_nan = int(np.isnan(ps).sum())
        tr["pnl_x"] = tr.shares.to_numpy() * np.nan_to_num(ps)
        inv = {"res_nan_trades": n_nan,
               "max_abs_pnl_ps_diff": float(np.nanmax(np.abs(ps - tr.pnl_ps.to_numpy()))),
               "q_min": float(q.min()), "q_max": float(q.max()),
               "max_usd_in": float(tr.usd_in.max())}
        # sequential per-match caps on the whole book (all months)
        full = (tr_v2 if name == "v2" else tr_safe).sort_values("ts", kind="stable")
        net = (full.dir * full.shares).groupby(full.cond).cumsum().abs()
        gross = (full.shares * full.q).groupby(full.cond).cumsum()
        inv["max_running_abs_net_shares"] = float(net.max())
        inv["max_match_gross_usd"] = float(gross.max())
        book = tr[tr.cond.map(start_of) >= CUT]
        assert tr.cond.map(start_of).notna().all()
        st = book_stats(book, pd.Timestamp("2026-08-25", tz="UTC"), ends)
        st["invariants"] = inv
        out[name] = st
        log(name, {k: st[k] for k in ("n_trades", "n_matches", "profitable_days", "calendar_days", "profitable_days_pct",
                                       "per_share_c", "per_share_ci_c_match_seed0_1000", "worst_day_usd", "pnl_usd")})
    # paired, same 40 days
    res["a_burned_oos"] = out
    rep = json.loads((ROOT / "results/lowloss/results.json").read_text())["runs"]["a_burned_oos_nonblind"]["books"]["u1_oos"]
    res["a_reported"] = {s: {k: rep[s][k] for k in ("profitable_days_pct", "profitable_active_days", "active_days",
                                                    "per_share_c", "per_share_ci_c", "worst_day_usd", "pnl_usd", "n_trades")}
                         for s in ("v2", "v2_safe")}
    res["a_match"] = {s: {"profitable_days_pct": abs(out[s]["profitable_days_pct"] - rep[s]["profitable_days_pct"]) < 1e-9,
                          "per_share_c": abs(out[s]["per_share_c"] - rep[s]["per_share_c"]) < 1e-9,
                          "per_share_ci_c": bool(np.allclose(out[s]["per_share_ci_c_match_seed0_1000"], rep[s]["per_share_ci_c"])),
                          "pnl_usd": abs(out[s]["pnl_usd"] - rep[s]["pnl_usd"]) < 1e-6}
                      for s in ("v2", "v2_safe")}
    log("matches reported", res["a_match"])


# ------------------------------------------------------------------------------- part (b)
def grid_from_md() -> list:
    """GRID.md: baseline first, then net 100,50,25 x deploy .5,.25 x zone x stop, nested, skipping baseline."""
    pols = []
    for net in (100, 50, 25):
        for dep in (0.5, 0.25):
            for zone, z in (("0.05-0.95", "05-95"), ("0.15-0.85", "15-85")):
                for sk in (np.inf, 1.5):
                    pols.append(replace(v2.POLICY, name=f"n{net}_d{int(dep * 100)}_z{z}_s{'inf' if np.isinf(sk) else sk}",
                                        net_cap=net, deploy_frac=dep, zone=zone, stop_k=sk))
    base = "n100_d50_z05-95_sinf"
    return [q for q in pols if q.name == base] + [q for q in pols if q.name != base]


def my_sigma(tr: pd.DataFrame) -> dict:
    d = tr.groupby("date").pnl.sum()
    d.index = pd.DatetimeIndex(d.index)
    d = d.reindex(pd.date_range(d.index.min(), d.index.max(), freq="D", tz="UTC"), fill_value=0.0)
    mon = d.index.tz_localize(None).to_period("M").astype(str)
    return {m: (float(d[mon < m].std()) if (mon < m).sum() >= 10 else np.inf) for m in sorted(set(mon))}


def choose(month, D, dmon, act_base, order, base):
    h = (dmon >= "2026-01") & (dmon < month)
    if int((act_base[h] > 0).sum()) < 10:
        return base, None
    H = D[h]
    share, mean = (H > 0).mean(), H.mean()
    feas = [v for v in order if mean[v] >= 0.5 * mean[base]]
    if not feas:
        return base, None
    best = max(feas, key=lambda v: (share[v], mean[v], -order.index(v)))
    ranked = sorted(feas, key=lambda v: (share[v], mean[v], -order.index(v)), reverse=True)
    ru = ranked[1] if len(ranked) > 1 else None
    return best, {"share": float(share[best] * 100), "runner_up": ru,
                  "runner_up_share": float(share[ru] * 100) if ru else None,
                  "lead_days": float(round((share[best] - share[ru]) * h.sum(), 3)) if ru else None,
                  "hist_days": int(h.sum()), "n_feasible": len(feas)}


def part_b(res: dict):
    f = pd.read_parquet(ROOT / "data/v2_lowloss/features_is.parquet")
    whist = pd.read_parquet(ROOT / "data/v2_lowloss/whist_is.parquet")
    assert f.month.max() <= "2026-09", f.month.max()
    u = universe()
    oos_conds = set(u.loc[u.start >= CUT, "cond"])
    res["b_features"] = {"rows": int(len(f)), "months": [f.month.min(), f.month.max()],
                         "rows_in_oos_matches": int(f.cond.isin(oos_conds).sum()),
                         "max_ts_utc": str(pd.to_datetime(f.ts.max(), unit="s", utc=True))}
    pols = grid_from_md()
    order = [q.name for q in pols]
    base = order[0]
    E._WCACHE.clear()
    trades, sig_ok = {}, {}
    for q in [q for q in pols if np.isinf(q.stop_k)] + [q for q in pols if np.isfinite(q.stop_k)]:
        sig = None
        if np.isfinite(q.stop_k):
            twin = trades[q.name.rsplit("_s", 1)[0] + "_sinf"]
            sig = E.sigma_from_history(twin)
            mine = my_sigma(twin)
            sig_ok[q.name] = all(np.isclose(sig[m], mine[m]) or (np.isinf(sig[m]) and np.isinf(mine[m])) for m in mine)
        trades[q.name] = E.simulate(f, q, "res", "actual", whist, sig)
    res["b_sigma_matches_months_lt_m"] = sig_ok
    # stop look-ahead: the stop marks the resolution P&L at ts + 4 h; if the match ends later, it is known too early
    tb = trades[base]
    late = (tb.end_ts > tb.ts + v2.LOCK_S)
    res["b_stop_mark_before_match_end"] = {"share_of_baseline_trades": float(late.mean()),
                                           "share_of_baseline_abs_pnl": float(tb.pnl.abs()[late].sum() / tb.pnl.abs().sum())}

    last = max(t.date.max() for t in trades.values())
    cal = pd.date_range("2026-01-01", pd.Timestamp(last).tz_convert("UTC").tz_localize(None), freq="D", tz="UTC")
    dmon = np.asarray(cal.tz_localize(None).to_period("M").astype(str))

    def mat(datecol, resolved_before=None):
        D = {}
        for v in order:
            t = trades[v][trades[v].month >= "2026-01"]
            if resolved_before is not None:
                t = t[np.maximum(t.end_ts.fillna(t.ts), t.ts) < resolved_before.timestamp()]
            s = t.groupby(t[datecol]).pnl.sum()
            s.index = pd.DatetimeIndex(s.index).as_unit("ns")
            D[v] = s.reindex(cal.as_unit("ns"), fill_value=0.0)
        return pd.DataFrame(D)

    for v in order:
        t = trades[v]
        rt = np.maximum(t.end_ts.fillna(t.ts), t.ts)
        t["date_res"] = pd.to_datetime(rt, unit="s", utc=True).dt.floor("D")
    D_entry, D_res = mat("date"), mat("date_res")
    act_base = trades[base].groupby("date").size()
    act_base.index = pd.DatetimeIndex(act_base.index).as_unit("ns")
    act_base = act_base.reindex(cal.as_unit("ns"), fill_value=0).to_numpy()

    theirs = pd.read_csv(ROOT / "research/v2/lowloss/out/selection.csv")
    their_daily = pd.read_csv(ROOT / "research/v2/lowloss/out/daily.csv", index_col=0)
    res["b_daily_matrix_equals_out_daily_csv"] = bool(np.allclose(their_daily[order].to_numpy(), D_entry.to_numpy(), atol=1e-6))
    months = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    sel = {}
    for m in months:
        a, ia = choose(m, D_entry, dmon, act_base, order, base)
        # minimal causal fix: entry-date booking, but only trades already resolved when month m begins
        c, ic = choose(m, mat("date", pd.Timestamp(m + "-01", tz="UTC")), dmon, act_base, order, base)
        # resolution-date booking (also strictly causal: a day's P&L is what was realised that day)
        b, ib = choose(m, D_res, dmon, act_base, order, base)
        sel[m] = {"entry_booking": a, "entry_info": ia, "entry_booking_resolved_only": c, "entry_resolved_info": ic,
                  "resolution_booking": b, "resolution_info": ib,
                  "reported": theirs.set_index("month").chosen.get(m)}
    res["b_selection"] = sel
    # stitched series recomputed, and boundary matches whose variant switches
    days = cal[cal >= pd.Timestamp("2026-02-01", tz="UTC")]
    parts = [trades[sel[m]["entry_booking"]][trades[sel[m]["entry_booking"]].month == m] for m in months[:-1]]
    st = pd.concat(parts)
    d = st.groupby("date").pnl.sum()
    d.index = pd.DatetimeIndex(d.index).as_unit("ns")
    d = d.reindex(days.as_unit("ns"), fill_value=0.0)
    span = st.groupby("cond").month.nunique()
    res["b_stitched"] = {"profitable_days_pct": float((d > 0).mean() * 100), "worst_day_usd": float(d.min()),
                         "pnl_usd": float(st.pnl.sum()), "per_share_c": float(st.pnl.sum() / st.shares.sum() * 100),
                         "matches_spanning_months": int((span > 1).sum())}
    rep = json.loads((ROOT / "research/v2/lowloss/out/results.json").read_text())["stitched_is"]
    res["b_stitched_reported"] = {k: rep[k] for k in ("profitable_days_pct", "worst_day_usd", "pnl_usd", "per_share_c")}
    # stitched series under the resolution-booking choices, for comparison (P&L still dated at entry)
    alt = pd.concat([trades[sel[m]["resolution_booking"]][trades[sel[m]["resolution_booking"]].month == m] for m in months[:-1]])
    da = alt.groupby("date").pnl.sum()
    da.index = pd.DatetimeIndex(da.index).as_unit("ns")
    da = da.reindex(days.as_unit("ns"), fill_value=0.0)
    res["b_stitched_if_resolution_booking_choices"] = {"profitable_days_pct": float((da > 0).mean() * 100),
                                                       "worst_day_usd": float(da.min()), "pnl_usd": float(alt.pnl.sum())}
    log("selection", json.dumps({m: [s["reported"], s["entry_booking"], s["entry_booking_resolved_only"],
                                     s["resolution_booking"]] for m, s in sel.items()}))
    log("stitched", res["b_stitched"], "reported", res["b_stitched_reported"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["a", "b", "ab"], default="ab")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    res: dict = {}
    if "b" in a.part:
        part_b(res)
    if "a" in a.part:
        part_a(res)
    txt = json.dumps(res, indent=2, default=lambda x: None if x is None else (float(x) if np.isscalar(x) else str(x)))
    if a.out:
        Path(a.out).write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
