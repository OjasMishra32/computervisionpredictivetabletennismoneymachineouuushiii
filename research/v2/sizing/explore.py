"""Descriptive edge tables for the fast-tier prints (IS, all walk-forward-selected months).

    python research/v2/sizing/explore.py     # -> research/v2/sizing/out/edge_by_*.csv

These tables are DESCRIPTIVE ONLY: they span every IS month, so no rule is taken from them directly.
Every rule in walkforward.py chooses its parameters on months < m and is scored on month m.
Edge columns are cents per share (equal weight per print), with 95% CIs clustered by match:
  gross30 = mo30; net30 = mo30 - actual fee; net30_5 = mo30 - 0.05 q(1-q) (today's fee);
  net_res = dir*(res-p) - actual fee; net_res_5 = dir*(res-p) - 0.05 q(1-q);
  sd_res / sd30 = per-share std of the hold-to-resolution / 30 s P&L.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "out"


def ci(df, col, n_boot=400, seed=0):
    d = df[["cond", col]].dropna()
    g = d.groupby("cond")[col].agg(["sum", "size"])
    s, n = g["sum"].to_numpy(), g["size"].to_numpy()
    rng = np.random.default_rng(seed)
    k = len(g)
    if k < 5:
        return np.nan, np.nan
    bs = [s[i].sum() / n[i].sum() for i in (rng.integers(0, k, k) for _ in range(n_boot))]
    return np.percentile(bs, 2.5) * 100, np.percentile(bs, 97.5) * 100


def table(df, by):
    rows = []
    for key, g in df.groupby(by, observed=True, dropna=False):
        r = {"bucket": str(key), "n": len(g), "n_matches": g.cond.nunique(), "q_mean": g.q.mean(),
             "usd_k": g.usd_in.sum() / 1e3}
        for c in ("gross30", "net30", "net30_5", "net_res", "net_res_5", "fee"):
            r[c] = g[c].mean() * 100
        r["net30_5_lo"], r["net30_5_hi"] = ci(g, "net30_5")
        r["net_res_5_lo"], r["net_res_5_hi"] = ci(g, "net_res_5")
        r["sd30"] = g.gross30.std() * 100
        r["sd_res"] = g.net_res.std() * 100
        rows.append(r)
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(exist_ok=True)
    f = pd.read_parquet(ROOT / "data/v2_sizing/features.parquet")
    f["gross30"] = f.mo30
    f["net30"] = f.mo30 - f.fee
    f["net30_5"] = f.mo30 - f.fee5
    f["net_res"] = f.mo_res_all - f.fee
    f["net_res_5"] = f.mo_res_all - f.fee5
    cuts = {
        "q": pd.cut(f.q, [0, .05, .1, .15, .2, .3, .4, .5, .6, .7, .8, .85, .9, .95, 1]),
        "fill_move": pd.cut(f.fill_move, [-1, -0.02, 0, 0.02, 0.03, 0.04, 0.05, 0.07, 0.1, 1]),
        "pre_move": pd.cut(f.pre_move, [-1, -0.01, 0.01, 0.03, 0.05, 1]).cat.add_categories("none").fillna("none"),
        "spread0": pd.cut(f.spread0, [-1, 0.0051, 0.0101, 0.02, 0.04, 1]).cat.add_categories("none").fillna("none"),
        "usd": pd.cut(f.usd, [0, 5, 20, 50, 100, 250, 500, 1000, 2500, 1e9]),
        "n_prior3": pd.cut(f.n_prior3, [-1, 0, 1, 3, 1e9]),
        "clip_k": pd.cut(f.clip_k, [-1, 0, 1, 1e9]),
        "regime": f.regime,
        "month": f.month,
    }
    for name, c in cuts.items():
        t_all = table(f.assign(_b=c), "_b").assign(subset="all")
        sub = f.regime == "1s/5%"
        t_5 = table(f[sub].assign(_b=c[sub]), "_b").assign(subset="1s/5%")
        t = pd.concat([t_all, t_5])
        t.round(4).to_csv(OUT / f"edge_by_{name}.csv", index=False)
        print(f"\n== {name}")
        print(t[["subset", "bucket", "n", "q_mean", "gross30", "net30_5", "net30_5_lo", "net30_5_hi", "net_res_5",
                 "net_res_5_lo", "net_res_5_hi", "sd30", "sd_res"]].round(2).to_string(index=False))


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
