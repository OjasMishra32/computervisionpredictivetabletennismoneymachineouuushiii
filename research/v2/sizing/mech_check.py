"""Is the fill_move effect mechanical? Same decision-time feature for EVERY taker in the 0-3 s window.

    python research/v2/sizing/mech_check.py   # -> research/v2/sizing/out/mech_check.csv

The 0-3 s bucket is defined from a jump detector that looks up to 10 s past the onset, so a print
that pays only a little above the pre-event level inside a detected >=4c jump is partly guaranteed a
further move. If that were the whole story, slow takers (not walk-forward fast tier) with a small
fill_move would earn as much as fast-tier prints with the same fill_move. This script compares them.
IS only (prints_0_3s_is.parquet, is_prints.parquet).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "out"


def main():
    f = pd.read_parquet(ROOT / "data/v2_sizing/features.parquet", columns=["cond", "ts", "wallet", "p", "dir", "usd"])
    fast_keys = set(zip(f.cond, f.ts, f.wallet, f.p.round(6), f.usd.round(4)))
    a = pd.read_parquet(ROOT / "data/derived/prints_0_3s_is.parquet",
                        columns=["cond", "ts", "p", "dir", "usd", "wallet", "mo30", "mo_res", "res", "with_jump"])
    a["month"] = pd.to_datetime(a.ts, unit="s").dt.to_period("M").astype(str)
    a = a[a.month >= "2025-12"].reset_index(drop=True)
    key = list(zip(a.cond, a.ts, a.wallet, a.p.round(6), a.usd.round(4)))
    a["fast"] = [k in fast_keys for k in key]
    t = pq.read_table(ROOT / "data/is_prints.parquet", columns=["cond", "ts", "p", "usd"], read_dictionary=["cond"])
    pr = t.to_pandas()
    pr = pr[pr.cond.isin(set(a.cond))]
    pr["cond"] = pr.cond.astype(str)
    pr = pr.sort_values(["cond", "ts"], kind="stable")
    ref = np.full(len(a), np.nan)
    groups = {c: g for c, g in pr.groupby("cond", sort=False)}
    for c, g in a.groupby("cond", sort=False):
        P = groups[c]
        ts, p, usd = P.ts.to_numpy(), P.p.to_numpy(), P.usd.to_numpy()
        pv = np.concatenate([[0.0], np.cumsum(p * usd)]); vv = np.concatenate([[0.0], np.cumsum(usd)])
        st = g.ts.to_numpy()
        lo = np.searchsorted(ts, st - 63, "left"); hi = np.searchsorted(ts, st - 3, "left")
        w = vv[hi] - vv[lo]
        ref[g.index.to_numpy()] = np.where(w > 0, (pv[hi] - pv[lo]) / np.where(w > 0, w, 1), np.nan)
    a["fill_move"] = (a.p - ref) * a.dir
    a["fmb"] = pd.cut(a.fill_move, [-1, -0.02, 0, 0.02, 0.03, 0.04, 0.05, 0.07, 0.1, 1])
    out = (a.groupby(["fmb", "fast"], observed=True)
           .agg(n=("mo30", "size"), gross30_c=("mo30", "mean"), gross_res_c=("mo_res", "mean"),
                with_jump=("with_jump", "mean"))
           .reset_index())
    out["gross30_c"] *= 100
    out["gross_res_c"] *= 100
    OUT.mkdir(exist_ok=True)
    out.round(4).to_csv(OUT / "mech_check.csv", index=False)
    print(out.round(3).to_string(index=False))
    print("matched fast rows", int(a.fast.sum()), "of", len(f))


if __name__ == "__main__":
    main()
