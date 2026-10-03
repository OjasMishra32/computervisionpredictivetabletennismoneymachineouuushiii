"""Blind forward test of the frozen v2 rule (HYPOTHESIS_V2.md). Run ONCE; every run is logged.

    python scripts/forward_test.py                       # the pre-registered forward window
    python scripts/forward_test.py --start 2026-09-01T00:00 --end 2026-09-03T00:00 --dry   # plumbing check on an old window

Window: ATP/WTA singles moneylines, volume >= $5k, start in [start, end), resolved at run time.
Wallet qualification, sizing normalisation and the wallet filter use only months before the window's
month (walk-forward), exactly as in-sample.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import polymarket as pm, tiers, v2  # noqa: E402
from src.tape import universe  # noqa: E402

FWD_START = "2026-10-03T13:00"
LOG = Path("results/forward_peeks.log")


def window_universe(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    days = pd.date_range((start - pd.Timedelta(days=4)).normalize(), end.normalize(), freq="D")
    rows = []
    for d in days:
        rows += pm._window("tennis", d.strftime("%Y-%m-%d"), (d + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
    w = pd.DataFrame(rows).drop_duplicates("cond")
    w["start"] = pd.to_datetime(w.start_time, utc=True, format="mixed")
    w["end"] = pd.to_datetime(w.finished.fillna(w.closed_time), utc=True, format="mixed")
    w = w[w.series.isin(["atp", "wta", "challenger"]) & (w.volume >= 5_000) & (w.start >= start) & (w.start < end)
          & w.res0.isin([0.0, 0.5, 1.0])]
    w["fee_rate"] = w.fee_rate.fillna(0.0)
    w["delay"] = w.seconds_delay.fillna(1).astype(int)
    return w.reset_index(drop=True)


def _prints(r):
    try:
        return tiers.match_prints(SimpleNamespace(**r))
    except Exception:
        return None


def cluster_ci(df, col, n_boot=2000, seed=0):
    g = df.groupby("cond")[col].agg(["sum", "size"])
    rng = np.random.default_rng(seed)
    k = len(g)
    bs = [g["sum"].to_numpy()[i].sum() / g["size"].to_numpy()[i].sum() for i in (rng.integers(0, k, k) for _ in range(n_boot))]
    return float(np.mean(df[col])), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def main(start: str, end: str | None, dry: bool):
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now(tz="UTC")
    if not dry:
        assert start == FWD_START, "the pre-registered window starts at " + FWD_START
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} forward test run, window [{start}, {end_ts})\n")
    w = window_universe(start_ts, end_ts)
    print(f"window matches: {len(w)}", flush=True)
    pm.fetch_many_trades(w.cond.tolist(), workers=6)
    with ProcessPoolExecutor(6) as ex:
        fw = [d for d in ex.map(_prints, w.to_dict("records"), chunksize=4) if d is not None]
    fw = pd.concat(fw, ignore_index=True)
    u = universe()
    hist = [pd.read_parquet("data/is_prints.parquet"), pd.read_parquet("data/locked/oos_prints.parquet")]
    allp = pd.concat(hist + [fw], ignore_index=True).drop_duplicates(["cond", "ts", "wallet", "p", "usd"])
    if dry:  # an old window is already inside the history; keep only months up to the window
        allp = allp[pd.to_datetime(allp.ts, unit="s", utc=True) < end_ts]
    ends = pd.concat([u.set_index("cond").end, w.set_index("cond").end])
    ends = ends[~ends.index.duplicated()]
    tr, wf = v2.run(allp, ends)
    ft = tr[tr.cond.isin(set(w.cond))].copy()
    ft["m30_ps"] = ft.gross30 - (ft.gross_res - ft.pnl_ps)    # 30 s markout net of the same fee
    out = {"window": [start, str(end_ts)], "matches_in_window": int(len(w)), "v2_trades": int(len(ft)),
           "v2_matches": int(ft.cond.nunique())}
    if len(ft):
        out["primary_m30_per_share_c"] = [round(100 * x, 3) for x in cluster_ci(ft.dropna(subset=["m30_ps"]), "m30_ps")]
        out["secondary_res"] = {k: v for k, v in v2.E.metrics(ft).items()
                                if k in ("per_share_c", "per_share_ci_c", "total_pnl_usd", "sharpe_ann", "max_dd_pct",
                                         "worst_day_pct", "capital_usd", "n_trades", "n_matches")}
        pf = fw[(fw.bucket == "0-3s")].copy()
        sel = set(tr[tr.cond.isin(set(w.cond))].wallet)
        pf["net30"] = pf.mo30 - pf.fee_rate * pf.p * (1 - pf.p)
        out["h6_fast_vs_others_net30_c"] = {"fast": float(pf[pf.wallet.isin(sel)].net30.mean() * 100),
                                            "others": float(pf[~pf.wallet.isin(sel)].net30.mean() * 100)}
        lo = out["primary_m30_per_share_c"][1]
        out["verdict"] = "PASS" if lo > 0 else "FAIL"
    print(json.dumps(out, indent=2))
    if not dry:
        Path("results/v2").mkdir(parents=True, exist_ok=True)
        Path("results/v2/forward.json").write_text(json.dumps(out, indent=2))
        ft.to_parquet("data/v2_forward_trades.parquet")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=FWD_START)
    ap.add_argument("--end", default=None)
    ap.add_argument("--dry", action="store_true", help="plumbing check on an old (already-seen) window; not logged")
    a = ap.parse_args()
    main(a.start, a.end, a.dry)
