"""One command to reproduce every number in the note from cached public data.

    python run_all.py           # in-sample work, live and tracking summaries, figures
    python run_all.py --oos     # also evaluates the locked out-of-sample period (logged)

Data comes from scripts/fetch_polymarket.py (public Polymarket endpoints, no keys).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src import backtest as bt, fasttier, prints, report, strategies as st
from src.tape import universe

RES = Path("results")


def calibration(df: pd.DataFrame, n_boot=500, seed=0) -> pd.DataFrame:
    df = df[df.res.isin([0.0, 1.0])]
    s = df.assign(minute=(df.ts // 60).astype(int)).groupby(["cond", "minute"]).first().reset_index()
    s["fav"] = np.maximum(s.p, 1 - s.p)
    s["won"] = np.where(s.p >= 0.5, s.res, 1 - s.res)
    s["bin"] = pd.cut(s.fav, [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.97, 0.98, 0.99, 1.0], right=False)
    rng = np.random.default_rng(seed)
    rows = []
    for b, g in s.groupby("bin", observed=True):
        m = g.groupby("cond").agg(w=("won", "sum"), n=("won", "size"))
        bs = [m.w.to_numpy()[i].sum() / m.n.to_numpy()[i].sum() for i in (rng.integers(0, len(m), len(m)) for _ in range(n_boot))]
        rows.append({"bin": str(b), "n_obs": len(g), "n_matches": len(m), "mean_price": g.fav.mean(),
                     "win_rate": g.won.mean(), "lo": np.percentile(bs, 2.5), "hi": np.percentile(bs, 97.5)})
    out = pd.DataFrame(rows)
    out["edge_c"] = (out.win_rate - out.mean_price) * 100
    return out


MATCH_CAP_USD = 3_000  # most capital the shadow book commits to one match
CAPITAL_BUFFER = 3     # capital = 3x the peak dollars locked in open positions


def shadow_book(sh: pd.DataFrame, u: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Apply the per-match cap; capital = peak dollars locked in open positions (held to resolution)."""
    if sh.empty:
        return sh, 0.0
    sh = sh.sort_values("ts", kind="stable").copy()
    sh["cum"] = sh.groupby("cond").usd_in.cumsum()
    sh = sh[sh.cum <= MATCH_CAP_USD]
    end = u.set_index("cond").end.map(lambda t: int(t.timestamp()) if pd.notna(t) else None)
    sh["end_ts"] = sh.cond.map(end).fillna(sh.ts + 4 * 3600).astype(int)
    ev = pd.concat([pd.DataFrame({"t": sh.ts, "d": sh.usd_in}), pd.DataFrame({"t": sh.end_ts, "d": -sh.usd_in})])
    peak = float(ev.sort_values("t", kind="stable").d.cumsum().max())
    return sh, peak


def shadow_stats(sh: pd.DataFrame, u: pd.DataFrame) -> dict:
    sh, peak = shadow_book(sh, u)
    if sh.empty:
        return {}
    tr = pd.DataFrame({"cond": sh.cond, "pnl_ps": sh.net_res, "pnl": sh.shares * sh.net_res, "fee": sh.fee,
                       "usd_in": sh.usd_in, "exit": "resolution",
                       "date": pd.to_datetime(sh.ts, unit="s", utc=True).dt.floor("D")})
    out = bt.stats(tr, capital=CAPITAL_BUFFER * peak)
    out["peak_locked_usd"] = peak
    out["trades_per_day"] = out["n_trades"] / max(out["days"], 1)
    return out


def run_split(u: pd.DataFrame, label: str, plateau: bool) -> dict:
    out = {}
    grid_h1 = [(J, H) for J in (0.02, 0.03, 0.04, 0.06, 0.08) for H in (10, 30, 60, 120)] if plateau else [(0.04, 30)]
    out["h1"] = {f"J{J}_H{H}": bt.stats(bt.run(st.h1_trades, u, J=J, H=H)) for J, H in grid_h1}
    grid_h2 = [(lo, hi) for lo in (0.80, 0.85, 0.90) for hi in (0.95, 0.97)] if plateau else [(0.85, 0.97)]
    out["h2"] = {f"lo{lo}_hi{hi}": bt.stats(bt.run(st.h2_trades, u, lo=lo, hi=hi)) for lo, hi in grid_h2}
    grid_h5 = [(J, W) for J in (0.02, 0.03, 0.04, 0.06) for W in (10, 20, 30, 60)] if plateau else [(0.04, 30)]
    out["h5"] = {f"J{J}_W{W}": bt.stats(bt.run(st.h5_fills, u, J=J, W=W)) for J, W in grid_h5}
    out["h5"]["always_on"] = bt.stats(bt.run(st.h5_fills, u, always_on=True))
    print(label, "strategies done", flush=True)
    return out


def main(oos: bool):
    RES.mkdir(exist_ok=True)
    u = universe()
    summary = {"universe": {"matches": int(len(u)), "is": int((~u.oos).sum()), "oos": int(u.oos.sum()),
                            "oos_start": str(u.loc[u.oos, "start"].min()), "volume_usd": float(u.volume.sum())}}
    summary["is"] = run_split(u[~u.oos], "IS", plateau=True)

    p_is = prints.build("is")
    cal = calibration(p_is)
    cal.to_csv(RES / "calibration_is.csv", index=False)
    report.calibration_figure(cal)
    summary["is"]["calibration"] = cal.round(4).to_dict("records")

    wf, sh, by_bucket = fasttier.walk_forward(p_is)
    wf.to_csv(RES / "fasttier_walkforward_is.csv", index=False)
    summary["is"]["h6_walkforward"] = wf.round(4).to_dict("records")
    summary["is"]["h6_shadow"] = shadow_stats(sh, u)
    summary["is"]["h6_months_positive"] = float((wf.net30_c > 0).mean())
    order = ["0-3s", "3-6s", "6-10s", "10-20s", "20-40s", "40-120s", ">120s"]
    report.tiers_figure(by_bucket.reindex(order))
    oos_start = None
    if oos:
        po = prints.build("oos")
        both = pd.concat([p_is, po], ignore_index=True)
        wf2, sh2, _ = fasttier.walk_forward(both)
        oos_m = pd.Period(pd.Timestamp(summary["universe"]["oos_start"]).tz_localize(None), "M")
        summary["oos"] = run_split(u[u.oos], "OOS", plateau=False)
        summary["oos"]["h6_walkforward"] = wf2[wf2.month >= str(oos_m)].round(4).to_dict("records")
        sh_oos = sh2[pd.to_datetime(sh2.ts, unit="s", utc=True) >= pd.Timestamp(summary["universe"]["oos_start"])]
        summary["oos"]["h6_shadow"] = shadow_stats(sh_oos, u)
        summary["oos"]["calibration"] = calibration(po).round(4).to_dict("records")
        wf, sh, oos_start = wf2, sh2, pd.Timestamp(summary["universe"]["oos_start"]).tz_localize(None)
    sh_capped, _ = shadow_book(sh, u)
    sh_capped = sh_capped.assign(pnl=sh_capped.shares * sh_capped.net_res)
    report.walkforward_figure(wf, sh_capped, oos_start)

    hk = RES / "hawkeye_tennis_calls.csv"
    tt = RES / "tracking" / "summary.json"
    report.tracking_figure(pd.read_csv(hk) if hk.exists() else pd.DataFrame(columns=["lead_ms", "pred_err_sd_cm"]))
    summary["tracking_tennis_physics"] = pd.read_csv(hk).round(4).to_dict("records") if hk.exists() else None
    summary["tracking_table_tennis_video"] = json.loads(tt.read_text()) if tt.exists() else None
    h4 = RES / "h4_leads.csv"
    if h4.exists():
        L = pd.read_csv(h4)
        report.h4_figure(L)
        summary["h4"] = {"n": int(len(L)), "median_lead_s": float(L.lead_s.median()),
                         "share_book_first": float((L.lead_s > 0).mean())}
    (RES / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print("wrote results/summary.json and results/figures/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos", action="store_true", help="evaluate the locked out-of-sample period (logged)")
    main(ap.parse_args().oos)
