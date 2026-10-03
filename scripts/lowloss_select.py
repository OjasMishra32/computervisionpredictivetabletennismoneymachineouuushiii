"""Loss-averse v2 variants on IS only: the grid and walk-forward meta-selection of
research/v2/lowloss/GRID.md (declared before this script was run).

    .venv/bin/python scripts/lowloss_select.py          # ~10 min, 1 process, ~3 GB peak
      -> research/v2/lowloss/out/{variants,monthly,daily,selection}.csv, results.json
         data/v2_lowloss/{features_is,whist_is,stitched_trades_is}.parquet (cache / stitched book)

The feature table is v2.run(causal=True)'s, built the same way with less memory: cond and wallet are
integer codes (pd.factorize(sort=True), so every sort order is unchanged) while the 8.3M prints are
in memory, and walk_forward gets only the causal 0-3 s prints (qualification and the shadow book use
nothing else). The baseline variant must reproduce results/v2/causal.json causal/is_eval/slip0.0.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import fasttier, v2  # noqa: E402
from src.tape import universe  # noqa: E402
from src.tiers import add_causal_bucket  # noqa: E402

E = v2.E
OUT = ROOT / "research/v2/lowloss/out"
CACHE = ROOT / "data/v2_lowloss"
GRID_MD = ROOT / "research/v2/lowloss/GRID.md"
COLS = ["cond", "ts", "p", "dir", "usd", "wallet", "spread", "fee_rate", "delay", "res",
        "mo5", "mo15", "mo30", "mo_res"]
EVAL_MONTHS = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
HIST_START = "2026-01"
BASE = "n100_d50_z05-95_sinf"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------------------------- build
def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    fp, wp = CACHE / "features_is.parquet", CACHE / "whist_is.parquet"
    if fp.exists() and wp.exists():
        return pd.read_parquet(fp), pd.read_parquet(wp)
    CACHE.mkdir(parents=True, exist_ok=True)
    log("loading IS prints")
    p = pd.read_parquet(ROOT / "data/is_prints.parquet", columns=COLS)
    cc, cond_u = pd.factorize(p.cond, sort=True)
    wc, wal_u = pd.factorize(p.wallet, sort=True)
    p["cond"] = cc.astype(np.int32)
    p["wallet"] = wc.astype(np.int32)
    del cc, wc
    log(f"{len(p):,} prints, {len(cond_u):,} matches; causal bucket")
    lab = add_causal_bucket(p[["cond", "ts", "p", "usd", "dir"]])
    p["bucket_c"] = lab.bucket_c
    del lab
    m_all = set(pd.to_datetime(p.ts, unit="s").dt.to_period("M").unique())
    p03 = p[p.bucket_c == "0-3s"].copy()
    assert set(pd.to_datetime(p03.ts, unit="s").dt.to_period("M").unique()) == m_all, "month grid differs"
    log(f"walk-forward on {len(p03):,} causal 0-3 s prints")
    wf, sh, _ = fasttier.walk_forward(p03, bucket="bucket_c")
    u = universe()
    ends = u.set_index("cond").end
    ends_c = pd.Series(ends.reindex(pd.Index(cond_u)).to_numpy(), index=np.arange(len(cond_u), dtype=np.int32))
    log(f"features for {len(sh):,} shadow rows")
    keep = p.cond.isin(set(sh.cond))
    f = v2.prepare(v2.build_features(sh, p.loc[keep, ["cond", "ts", "p", "dir", "usd", "wallet"]], ends_c))
    del p, keep
    f["lock_end"] = f.ts + v2.LOCK_S
    whist = p03[["wallet", "ts", "mo30"]].copy()
    whist["month"] = pd.to_datetime(whist.ts, unit="s").dt.to_period("M").astype(str)
    whist = whist[["wallet", "month", "mo30"]]
    cond_u, wal_u = np.asarray(cond_u, dtype=object), np.asarray(wal_u, dtype=object)
    f["cond"] = cond_u[f.cond.to_numpy()]
    f["wallet"] = wal_u[f.wallet.to_numpy()]
    whist["wallet"] = wal_u[whist.wallet.to_numpy()]
    for c in f.columns:   # parquet round-trip safety for object/period/category columns
        if isinstance(f[c].dtype, pd.CategoricalDtype) or isinstance(f[c].dtype, pd.PeriodDtype):
            f[c] = f[c].astype(str)
    f.to_parquet(fp)
    whist.to_parquet(wp)
    wf.to_csv(OUT / "fasttier_wf_is.csv", index=False)
    return pd.read_parquet(fp), pd.read_parquet(wp)


# ------------------------------------------------------------------------------------- grid
def grid() -> list[E.Policy]:
    pols = []
    for net in (100, 50, 25):
        for dep in (0.5, 0.25):
            for zone in ("0.05-0.95", "0.15-0.85"):
                for sk in (np.inf, 1.5):
                    z = "05-95" if zone == "0.05-0.95" else "15-85"
                    name = f"n{net}_d{int(dep * 100)}_z{z}_s{'inf' if np.isinf(sk) else sk}"
                    pols.append(replace(v2.POLICY, name=name, net_cap=net, deploy_frac=dep, zone=zone,
                                        stop_k=sk, family="lowloss"))
    base = [q for q in pols if q.name == BASE]
    assert len(base) == 1
    return base + [q for q in pols if q.name != BASE]


# ---------------------------------------------------------------------------------- metrics
def daily_on(tr: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    d = tr.groupby("date").pnl.sum()
    d.index = pd.DatetimeIndex(d.index).as_unit("ns")
    out = d.reindex(days, fill_value=0.0)
    assert abs(out.sum() - tr.pnl.sum()) < 1e-6 * max(1.0, abs(tr.pnl.sum())), "trade dates outside calendar"
    return out


def series_metrics(tr: pd.DataFrame, days: pd.DatetimeIndex) -> dict:
    d = daily_on(tr, days)
    eq = d.cumsum().to_numpy()
    peak = np.maximum.accumulate(np.maximum(eq, 0.0))
    down = np.minimum(d.to_numpy(), 0.0)
    em = E.metrics(tr)
    mon = tr.groupby("month").pnl.sum().reindex(EVAL_MONTHS, fill_value=0.0)
    mt = tr.groupby("cond").pnl.sum()
    act = tr.groupby("date").pnl.sum()
    sd = d.std()
    dd = float((eq - peak).min())
    return {
        "profitable_days_pct": float((d > 0).mean() * 100),
        "losing_days_pct": float((d < 0).mean() * 100),
        "active_days": int(len(act)), "profitable_active_days_pct": float((act > 0).mean() * 100),
        "calendar_days": int(len(d)),
        "worst_day_usd": float(d.min()), "worst_month_usd": float(mon.min()),
        "months_positive": int((mon > 0).sum()),
        "max_dd_usd": dd, "max_dd_pct_cap": float(dd / em["capital_usd"] * 100),
        "sharpe_ann": float(d.mean() / sd * np.sqrt(365)) if sd > 0 else float("nan"),
        "sortino_ann": float(d.mean() / np.sqrt((down ** 2).mean()) * np.sqrt(365)) if (down < 0).any() else float("inf"),
        "pnl_usd": float(tr.pnl.sum()), "mean_daily_usd": float(d.mean()),
        "per_share_c": em["per_share_c"], "per_share_ci_c": em["per_share_ci_c"],
        "profitable_matches_pct": float((mt > 0).mean() * 100), "n_matches": int(len(mt)),
        "n_trades": int(len(tr)), "shares": float(tr.shares.sum()), "usd_traded": float(tr.usd_in.sum()),
        "peak_locked_usd": em["peak_locked_usd"], "capital_usd": em["capital_usd"],
    }


# -------------------------------------------------------------------------------- selection
def choose(month: str, dmat: pd.DataFrame, dmonth: np.ndarray, active: pd.DataFrame, order: list[str]):
    hist = (dmonth >= HIST_START) & (dmonth < month)
    H = dmat[hist]
    if int((active.loc[hist, BASE] > 0).sum()) < 10:
        return BASE, {"reason": "history < 10 baseline days"}
    share = (H > 0).mean()
    mean = H.mean()
    feas = [v for v in order if mean[v] >= 0.5 * mean[BASE]]
    if not feas:
        return BASE, {"reason": "nothing feasible"}
    best = max(feas, key=lambda v: (share[v], mean[v], -order.index(v)))
    return best, {"reason": "max share", "hist_days": int(len(H)), "n_feasible": len(feas),
                  "share": float(share[best] * 100), "mean": float(mean[best]),
                  "base_share": float(share[BASE] * 100), "base_mean": float(mean[BASE])}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    grid_sha = hashlib.sha256(GRID_MD.read_bytes()).hexdigest()
    log("GRID.md sha256", grid_sha)
    f, whist = build()
    log(f"features: {len(f):,} rows, months {f.month.min()}..{f.month.max()}")
    pols = grid()
    order = [q.name for q in pols]
    trades: dict[str, pd.DataFrame] = {}
    E._WCACHE.clear()
    # no-stop variants first (their daily P&L gives the stop twins' sigma)
    for q in [q for q in pols if np.isinf(q.stop_k)] + [q for q in pols if np.isfinite(q.stop_k)]:
        sig = None
        if np.isfinite(q.stop_k):
            sig = E.sigma_from_history(trades[q.name.rsplit("_s", 1)[0] + "_sinf"])
        trades[q.name] = E.simulate(f, q, "res", "actual", whist, sig)
        log(q.name, f"{len(trades[q.name]):,} trades")
        if q.name == BASE:   # sanity check (GRID.md): must reproduce the frozen causal v2 on IS
            ref = json.loads((ROOT / "results/v2/causal.json").read_text())["causal/is_eval/slip0.0"]
            m = E.metrics(trades[BASE])
            chk = {"n_trades": (m["n_trades"], ref["n_trades"]), "per_share_c": (m["per_share_c"], ref["per_share_c"]),
                   "total_pnl_usd": (m["total_pnl_usd"], ref["total_pnl_usd"])}
            log("baseline check", chk)
            assert m["n_trades"] == ref["n_trades"] and abs(m["total_pnl_usd"] - ref["total_pnl_usd"]) < 0.01, chk

    last = max(tr.date.max() for tr in trades.values())
    cal = pd.date_range("2026-01-01", pd.Timestamp(last).tz_convert("UTC").tz_localize(None), freq="D", tz="UTC").as_unit("ns")
    days = cal[cal >= pd.Timestamp("2026-02-01", tz="UTC")]
    dmonth = np.asarray(cal.tz_localize(None).to_period("M").astype(str))
    dmat = pd.DataFrame({v: daily_on(trades[v][trades[v].month >= HIST_START], cal) for v in order}, index=cal)
    active = pd.DataFrame({v: trades[v].groupby("date").size().pipe(lambda s: s.set_axis(pd.DatetimeIndex(s.index).as_unit("ns")))
                          .reindex(cal, fill_value=0) for v in order}, index=cal)

    # per-variant full-period (Feb-Aug) metrics and monthly table
    rows, mrows = [], []
    for v in order:
        tr = trades[v][trades[v].month.isin(EVAL_MONTHS)]
        rows.append({"variant": v, **series_metrics(tr, days)})
        for m in [HIST_START] + EVAL_MONTHS:
            dm = dmat.loc[dmonth == m, v]
            tm = trades[v][trades[v].month == m]
            mrows.append({"variant": v, "month": m, "pnl_usd": float(tm.pnl.sum()), "n_trades": len(tm),
                          "profitable_days_pct": float((dm > 0).mean() * 100), "worst_day_usd": float(dm.min()),
                          "mean_daily_usd": float(dm.mean()),
                          "per_share_c": float(tm.pnl.sum() / tm.shares.sum() * 100) if len(tm) else float("nan"),
                          "profitable_matches_pct": float((tm.groupby("cond").pnl.sum() > 0).mean() * 100) if len(tm) else float("nan")})
    V = pd.DataFrame(rows)
    V["per_share_lo_c"] = V.per_share_ci_c.map(lambda x: x[0]); V["per_share_hi_c"] = V.per_share_ci_c.map(lambda x: x[1])
    V.drop(columns="per_share_ci_c").to_csv(OUT / "variants.csv", index=False)
    M = pd.DataFrame(mrows)
    M.to_csv(OUT / "monthly.csv", index=False)
    dmat.to_csv(OUT / "daily.csv", index_label="date")

    # walk-forward meta-selection and the stitched series
    sel, parts = [], []
    for m in EVAL_MONTHS:
        v, info = choose(m, dmat, dmonth, active, order)
        sel.append({"month": m, "chosen": v, **info})
        parts.append(trades[v][trades[v].month == m])
    S = pd.DataFrame(sel)
    S.to_csv(OUT / "selection.csv", index=False)
    st = pd.concat(parts).sort_values("ts", kind="stable")
    st.to_parquet(CACHE / "stitched_trades_is.parquet")
    stitched = series_metrics(st, days)
    stitched_monthly = st.groupby("month").pnl.sum().reindex(EVAL_MONTHS, fill_value=0.0).to_dict()
    frozen = S.chosen.iloc[-1]
    info_next, info_next_d = choose("2026-09", dmat, dmonth, active, order)  # info only (GRID.md)
    fp = next(q for q in pols if q.name == frozen)
    res = {
        "grid_md_sha256": grid_sha, "baseline": BASE,
        "selection": sel, "frozen_v2_safe": frozen,
        "frozen_policy": {"net_cap": fp.net_cap, "deploy_frac": fp.deploy_frac, "zone": fp.zone,
                          "stop_k": fp.stop_k, "sizing": fp.sizing, "wallet": fp.wallet,
                          "usd_cap": fp.usd_cap, "match_cap": fp.match_cap},
        "info_choice_with_history_jan_aug": [info_next, info_next_d],
        "stitched_is": stitched, "stitched_monthly_usd": stitched_monthly,
        "variants_is_context_only": {r["variant"]: r for r in rows},
        "frozen_variant_full_is_context_only": next(r for r in rows if r["variant"] == frozen),
        "calendar": [str(days[0].date()), str(days[-1].date())],
    }
    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    show = ["variant", "profitable_days_pct", "worst_day_usd", "worst_month_usd", "max_dd_usd", "sharpe_ann",
            "sortino_ann", "pnl_usd", "per_share_c", "per_share_lo_c", "profitable_matches_pct", "n_trades"]
    print(V[show].round(2).to_string(index=False))
    print(S.to_string(index=False))
    print("STITCHED", json.dumps({k: (round(x, 3) if isinstance(x, float) else x) for k, x in stitched.items()}))
    print("FROZEN v2-safe:", frozen, "| info (history Jan-Aug):", info_next)


if __name__ == "__main__":
    main()
