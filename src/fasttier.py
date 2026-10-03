"""H6: walk-forward test of the fast tier (wallets that win right after score events).

Each month m, wallets qualify on data strictly before m. Their prints in the 0-3 s post-jump
bucket during m are scored net of that match's taker fee. A "shadow book" that takes those
same trades (capped size) is the P&L a trader with tier-0/1 speed could have earned.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_PRINTS, MIN_MATCHES, MIN_T = 30, 10, 3.0
SHADOW_MAX_USD = 1_000


def qualify(past: pd.DataFrame, bucket: str = "bucket") -> pd.Index:
    f = past[past[bucket] == "0-3s"]
    g = f.groupby("wallet").agg(n=("mo30", "size"), nm=("cond", "nunique"), m=("mo30", "mean"), sd=("mo30", "std"))
    g = g[(g.n >= MIN_PRINTS) & (g.nm >= MIN_MATCHES) & (g.sd > 0)]
    t = g.m / (g.sd / np.sqrt(g.nm))
    return g.index[t > MIN_T]


def net_cols(df: pd.DataFrame) -> pd.DataFrame:
    fee = df.fee_rate * df.p * (1 - df.p)  # fee on the token bought is symmetric in p
    df = df.assign(fee=fee, net30=df.mo30 - fee, net_res=df.mo_res - fee)
    # follower: enters ~delay+3 s later at the then-mid plus half the spread, pays the fee too
    lag_mo = np.where(df.delay >= 3, df.mo15, df.mo5)  # closest stored horizon to delay + 3 s
    df["follow_res"] = df.mo_res - lag_mo - df.spread.fillna(0.01) / 2 - fee
    return df


def walk_forward(prints: pd.DataFrame, start_month: int = 2, bucket: str = "bucket"):
    """bucket="bucket" labels by jump onset (ex-post event study); "bucket_c" by detection time (causal)."""
    prints = prints.assign(month=pd.to_datetime(prints.ts, unit="s").dt.to_period("M"))
    prints = net_cols(prints)
    months = sorted(prints.month.unique())
    rows, shadow, labelled = [], [], []
    for m in months[start_month:]:
        sel = qualify(prints[prints.month < m], bucket)
        labelled.append(prints[prints.month == m].assign(fast=lambda d: d.wallet.isin(sel)))
        cur = prints[(prints.month == m) & (prints[bucket] == "0-3s") & prints.wallet.isin(sel)]
        rest = prints[(prints.month == m) & (prints[bucket] == "0-3s") & ~prints.wallet.isin(sel)]
        rows.append({"month": str(m), "n_wallets": len(sel), "n_prints": len(cur), "n_matches": cur.cond.nunique(),
                     "usd_k": cur.usd.sum() / 1e3, "net30_c": cur.net30.mean() * 100,
                     "net_res_c": cur.net_res.mean() * 100, "follow_res_c": cur.follow_res.mean() * 100,
                     "others_net30_c": rest.net30.mean() * 100})
        if len(cur):
            sh = cur.assign(usd_in=np.minimum(cur.usd, SHADOW_MAX_USD))
            sh["shares"] = sh.usd_in / np.where(sh.dir > 0, sh.p, 1 - sh.p)
            shadow.append(sh.assign(pnl=sh.shares * sh.net_res, pnl30=sh.shares * sh.net30))
    lab = pd.concat(labelled) if labelled else pd.DataFrame()
    by_bucket = (lab.groupby([bucket, "fast"], observed=True).net30.mean().unstack() * 100
                 ).rename(columns={True: "fast", False: "others"}) if len(lab) else pd.DataFrame()
    return pd.DataFrame(rows), (pd.concat(shadow) if shadow else pd.DataFrame()), by_bucket


def cluster_ci(x: pd.DataFrame, col: str, n_boot: int = 2000, seed: int = 0):
    g = x.groupby("cond")[col].agg(["sum", "size"])
    rng = np.random.default_rng(seed)
    k = len(g)
    bs = [g["sum"].to_numpy()[i].sum() / g["size"].to_numpy()[i].sum()
          for i in (rng.integers(0, k, k) for _ in range(n_boot))]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
