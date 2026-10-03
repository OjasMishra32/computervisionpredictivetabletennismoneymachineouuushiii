"""Decision-time features for every in-sample 0-3 s print (all wallets).

    .venv/bin/python research/v2/selection/build_features.py

Everything here uses only information available before the print executes:
  pre_spread  ask - bid from the latest ask-side / bid-side prints STRICTLY BEFORE this print (<= 30 s old)
              (the stored `spread` column includes the print itself, so it is partly post-trade)
  pay_up      dir * (p - pre_mid): how far through the prior mid the taker paid (cents of price)
  cum_usd     in-play USD traded in the match before this print (match volume so far)
  n_jumps     jumps whose detector had fired (detect_ts < ts) earlier in the match
  t_start     seconds since the scheduled match start
  series      atp / wta
Reads only IS files (data/is_prints.parquet, data/derived/*_is.parquet). Output: data/v2_selection/feat_0_3s.parquet
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "v2_selection" / "feat_0_3s.parquet"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    a = pq.read_table(ROOT / "data/is_prints.parquet", columns=["cond", "ts", "p", "dir", "usd"]).to_pandas()
    sub = pd.read_parquet(ROOT / "data/derived/prints_0_3s_is.parquet", columns=["cond", "ts"])
    idx = sub.index.to_numpy()
    assert (a.cond.to_numpy()[idx] == sub.cond.to_numpy()).all() and (a.ts.to_numpy()[idx] == sub.ts.to_numpy()).all()

    g = a.cond.astype("category").cat.codes.to_numpy()
    ts, p, d, usd = a.ts.to_numpy(), a.p.to_numpy(), a.dir.to_numpy(), a.usd.to_numpy()
    first = np.r_[True, g[1:] != g[:-1]]
    # latest ask-/bid-side price strictly before each row, within its match (rows are grouped by cond, ts sorted)
    df = pd.DataFrame({"g": g, "ap": np.where(d > 0, p, np.nan), "at": np.where(d > 0, ts, np.nan),
                       "bp": np.where(d < 0, p, np.nan), "bt": np.where(d < 0, ts, np.nan)})
    ff = df.groupby("g", sort=False)[["ap", "at", "bp", "bt"]].ffill()
    prev = ff.shift(1)
    prev[first] = np.nan
    ask = np.where(ts - prev["at"].to_numpy() <= 30, prev["ap"].to_numpy(), np.nan)
    bid = np.where(ts - prev["bt"].to_numpy() <= 30, prev["bp"].to_numpy(), np.nan)
    ok = np.isfinite(ask) & np.isfinite(bid) & (ask >= bid)
    pre_spread = np.where(ok, ask - bid, np.nan)
    pre_mid = np.where(ok, (ask + bid) / 2, np.nan)
    cum = pd.Series(usd).groupby(g, sort=False).cumsum().to_numpy() - usd

    f = pd.DataFrame({"pre_spread": pre_spread[idx], "pay_up": (d * (p - pre_mid))[idx], "cum_usd": cum[idx]},
                     index=sub.index)
    del a, df, ff, prev

    j = pd.read_parquet(ROOT / "data/derived/jumps_is.parquet", columns=["cond", "detect_ts"])
    jd = {c: np.sort(x.detect_ts.to_numpy()) for c, x in j.groupby("cond")}
    nj = np.zeros(len(sub), dtype=np.int32)
    for c, ix in sub.groupby("cond").indices.items():
        arr = jd.get(c)
        if arr is not None:
            nj[ix] = np.searchsorted(arr, sub.ts.to_numpy()[ix], "left")  # detect_ts < ts
    f["n_jumps"] = nj

    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["cond", "series", "start"])
    u = u.set_index("cond")
    st = sub.cond.map(u.start.map(lambda t: t.timestamp())).to_numpy()
    f["t_start"] = sub.ts.to_numpy() - st
    f["series"] = sub.cond.map(u.series).to_numpy()
    f.to_parquet(OUT)
    print(f.describe(include="all").T.to_string())
    print("wrote", OUT, len(f))


if __name__ == "__main__":
    sys.exit(main())
