"""Decision-time features for every walk-forward fast-tier print (IS only).

    python research/v2/sizing/features.py      # -> data/v2_sizing/features.parquet

Input rows: data/derived/shadow_is_uncapped.parquet (the walk-forward-selected fast-tier wallets'
0-3 s prints; months Dec 2025 - Aug 2026, all IS). Every feature below uses only prints in EARLIER
seconds than the print itself (tape timestamps are whole seconds and the order of prints within one
second is unknown), plus the print's own price (our limit price) and the wallet's own ticket.

  q          price of the token bought (p if dir>0 else 1-p)
  fee5       counterfactual fee under today's schedule: 0.05*q*(1-q)
  ref        VWAP of outcome-0 prints in [ts-63, ts-3)  (pre-event level as of 3 s ago)
  last       last outcome-0 print price in an earlier second, within 10 s
  pre_move   (last - ref) * dir : move in our direction already printed before our second
  fill_move  (p - ref) * dir    : how far above the pre-event level we are paying
  bid0/ask0  latest bid-/ask-side prints <=30 s old, earlier seconds only; spread0 = ask0-bid0
  n_prior3   prints in the match in [ts-3, ts); usd_prior3 their dollars
  clip_k     earlier-second prints by the same wallet in the same match within the last 3 s
  end_ts     match end (universe), for capital lock-up and daily-stop marks
  mo_res_all dir*(res-p) including 50/50 resolutions (the shared table leaves those NaN)

No OOS data is read: the shadow table, is_prints and universe_is are IS-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "v2_sizing"
OOS_START = pd.Timestamp("2026-08-25 14:15", tz="UTC")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sh = pd.read_parquet(ROOT / "data/derived/shadow_is_uncapped.parquet")
    sh = sh.drop(columns=[c for c in ("__index_level_0__",) if c in sh])
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["cond", "start", "end", "res0"])
    assert (u.start < OOS_START).all(), "universe_is must be IS only"
    assert sh.cond.isin(u.cond).all()
    conds = set(sh.cond.unique())

    t = pq.read_table(ROOT / "data/is_prints.parquet", columns=["cond", "ts", "p", "dir", "usd", "wallet"],
                      read_dictionary=["cond", "wallet"])
    pr = t.to_pandas()
    del t
    pr = pr[pr.cond.isin(conds)]
    pr["cond"] = pr.cond.astype(str)
    pr["wallet"] = pr.wallet.astype(str)
    pr = pr.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)

    sh = sh.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    feats = {k: np.full(len(sh), np.nan) for k in
             ("ref", "last", "bid0", "ask0", "n_prior3", "usd_prior3", "clip_k")}
    pr_groups = {c: g for c, g in pr.groupby("cond", sort=False)}
    for c, g in sh.groupby("cond", sort=False):
        P = pr_groups[c]
        ts = P.ts.to_numpy(); p = P.p.to_numpy(); usd = P.usd.to_numpy(); d = P.dir.to_numpy()
        wal = P.wallet.to_numpy()
        pv = np.concatenate([[0.0], np.cumsum(p * usd)]); vv = np.concatenate([[0.0], np.cumsum(usd)])
        # latest bid-side / ask-side print up to each index (inclusive)
        idx = np.arange(len(ts))
        ask_i = np.maximum.accumulate(np.where(d > 0, idx, -1))
        bid_i = np.maximum.accumulate(np.where(d < 0, idx, -1))
        st = g.ts.to_numpy()
        rows = g.index.to_numpy()
        a = np.searchsorted(ts, st - 63, "left"); b = np.searchsorted(ts, st - 3, "left")
        w = vv[b] - vv[a]
        feats["ref"][rows] = np.where(w > 0, (pv[b] - pv[a]) / np.where(w > 0, w, 1), np.nan)
        e = np.searchsorted(ts, st, "left")  # first print in our own second -> e-1 = last earlier print
        l10 = np.searchsorted(ts, st - 10, "left")
        has = (e - 1 >= l10) & (e > 0)
        feats["last"][rows] = np.where(has, p[np.maximum(e - 1, 0)], np.nan)
        for side_i, key in ((ask_i, "ask0"), (bid_i, "bid0")):
            j = np.where(e > 0, side_i[np.maximum(e - 1, 0)], -1)
            ok = (j >= 0) & (st - ts[np.maximum(j, 0)] <= 30)
            feats[key][rows] = np.where(ok, p[np.maximum(j, 0)], np.nan)
        s3 = np.searchsorted(ts, st - 3, "left")
        feats["n_prior3"][rows] = e - s3
        feats["usd_prior3"][rows] = vv[e] - vv[s3]
        gw = g.wallet.to_numpy()
        ck = np.zeros(len(st))
        for k in range(len(st)):
            if e[k] > s3[k]:
                ck[k] = np.count_nonzero(wal[s3[k]:e[k]] == gw[k])
        feats["clip_k"][rows] = ck
    for k, v in feats.items():
        sh[k] = v
    sh["q"] = np.where(sh.dir > 0, sh.p, 1 - sh.p)
    sh["fee5"] = 0.05 * sh.q * (1 - sh.q)
    sh["pre_move"] = (sh["last"] - sh.ref) * sh.dir
    sh["fill_move"] = (sh.p - sh.ref) * sh.dir
    sh["spread0"] = sh.ask0 - sh.bid0
    end = u.set_index("cond").end
    sh["end_ts"] = sh.cond.map(end).map(lambda x: x.timestamp() if pd.notna(x) else np.nan)
    sh["end_ts"] = sh.end_ts.fillna(sh.ts + 4 * 3600)
    sh["end_ts"] = np.maximum(sh.end_ts, sh.ts)
    sh["mo_res_all"] = sh.dir * (sh.res - sh.p)
    sh["date"] = pd.to_datetime(sh.ts, unit="s", utc=True).dt.floor("D")
    sh["month"] = sh.month.astype(str)
    sh["regime"] = sh.delay.astype(int).astype(str) + "s/" + (sh.fee_rate * 100).round().astype(int).astype(str) + "%"
    assert pd.to_datetime(sh.ts.max(), unit="s", utc=True) < OOS_START + pd.Timedelta(hours=8)
    sh = sh.sort_values("ts", kind="stable").reset_index(drop=True)
    sh.to_parquet(OUT / "features.parquet")
    print("rows", len(sh), "matches", sh.cond.nunique())
    print(sh[["ref", "last", "pre_move", "fill_move", "spread0", "n_prior3", "clip_k"]].describe().T.round(4))


if __name__ == "__main__":
    main()
