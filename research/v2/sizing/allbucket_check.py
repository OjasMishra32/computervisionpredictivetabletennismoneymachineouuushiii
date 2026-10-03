"""Placebo for window-defined features: the same decision-time features OUTSIDE the 0-3 s window.

    python research/v2/sizing/allbucket_check.py   # -> research/v2/sizing/out/allbucket_check.csv

Walk-forward fast-tier wallets (qualified on months < m exactly as src.fasttier.qualify) also trade
outside the 0-3 s post-jump bucket. Those prints were not selected by the ex-post jump detector, so a
feature gradient that also shows up there is not an artefact of conditioning on a >=4c jump that is
only confirmed up to 10 s later. Features use earlier-second prints only (same as features.py).
IS only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src import fasttier  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"


def main():
    t = pq.read_table(ROOT / "data/is_prints.parquet",
                      columns=["cond", "ts", "p", "dir", "usd", "wallet", "bucket", "mo30", "mo_res", "fee_rate"],
                      read_dictionary=["cond", "wallet"])
    pr = t.to_pandas()
    del t
    pr["month"] = pd.to_datetime(pr.ts, unit="s").dt.to_period("M")
    months = sorted(pr.month.unique())
    sel_rows = []
    for m in months[2:]:
        past = pr[pr.month < m]
        sel = fasttier.qualify(past[["wallet", "bucket", "mo30", "cond"]].assign(wallet=past.wallet.astype(str)))
        cur = pr[(pr.month == m) & pr.wallet.astype(str).isin(set(sel))]
        sel_rows.append(cur.index.to_numpy())
    idx = np.concatenate(sel_rows)
    pr = pr.sort_values(["cond", "ts"], kind="stable")
    fast = pr.loc[np.sort(idx)].copy()
    fast["cond"] = fast.cond.astype(str)
    pr["cond"] = pr.cond.astype(str)
    ref = pd.Series(np.nan, index=fast.index)
    n3 = pd.Series(np.nan, index=fast.index)
    groups = {c: g for c, g in pr[["cond", "ts", "p", "usd"]].groupby("cond", sort=False)}
    for c, g in fast.groupby("cond", sort=False):
        P = groups[c]
        ts, p, usd = P.ts.to_numpy(), P.p.to_numpy(), P.usd.to_numpy()
        pv = np.concatenate([[0.0], np.cumsum(p * usd)]); vv = np.concatenate([[0.0], np.cumsum(usd)])
        st = g.ts.to_numpy()
        lo = np.searchsorted(ts, st - 63, "left"); hi = np.searchsorted(ts, st - 3, "left")
        e = np.searchsorted(ts, st, "left")
        w = vv[hi] - vv[lo]
        ref.loc[g.index] = np.where(w > 0, (pv[hi] - pv[lo]) / np.where(w > 0, w, 1), np.nan)
        n3.loc[g.index] = e - hi
    fast["fill_move"] = (fast.p - ref) * fast.dir
    fast["n_prior3"] = n3
    fast["q"] = np.where(fast.dir > 0, fast.p, 1 - fast.p)
    fast["fee5"] = 0.05 * fast.q * (1 - fast.q)
    fast["win"] = np.where(fast.bucket.astype(str) == "0-3s", "0-3s", "outside 0-3s")
    rows = []
    cuts = {"fill_move": pd.cut(fast.fill_move, [-1, -0.02, 0, 0.02, 0.03, 0.04, 0.05, 0.07, 0.1, 1]),
            "n_prior3": pd.cut(fast.n_prior3, [-1, 0, 1, 3, 1e9]),
            "q": pd.cut(fast.q, [0, .1, .2, .3, .5, .7, .8, .9, 1])}
    for name, c in cuts.items():
        g = fast.assign(_b=c).groupby(["win", "_b"], observed=True).agg(
            n=("mo30", "size"), gross30_c=("mo30", "mean"), gross_res_c=("mo_res", "mean"), fee5_c=("fee5", "mean"))
        g = g.reset_index().rename(columns={"_b": "bucket"})
        g["gross30_c"] *= 100; g["gross_res_c"] *= 100; g["fee5_c"] *= 100
        g["net30_5_c"] = g.gross30_c - g.fee5_c
        g.insert(0, "feature", name)
        rows.append(g)
    out = pd.concat(rows)
    OUT.mkdir(exist_ok=True)
    out["bucket"] = out.bucket.astype(str)
    out.round(4).to_csv(OUT / "allbucket_check.csv", index=False)
    pd.set_option("display.width", 200)
    print(out.round(3).to_string(index=False))
    print(fast.groupby("bucket", observed=True).mo30.agg(["size", "mean"]))


if __name__ == "__main__":
    main()
