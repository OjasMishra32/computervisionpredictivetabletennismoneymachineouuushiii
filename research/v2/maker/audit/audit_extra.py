"""Audit extras on the independent OOS per-print table (labelled post-hoc; no rule change)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SP = Path(__file__).parent
sys.path.insert(0, str(SP))
from indep_maker_oos import book, cluster_ci  # own code

pp = pd.read_parquet(SP / "indep_pp.parquet")
lean, _ = book(pp)
anti, _ = book(pp, side="anti")
print("lean", len(lean), lean.pnl_ps.mean() * 100, "anti", len(anti), anti.pnl_ps.mean() * 100)

# 1. paired cluster bootstrap of the lean minus anti-lean gap (clusters = matches)
ev = sorted(set(lean.event_id) | set(anti.event_id))
idx = {e: i for i, e in enumerate(ev)}
k = len(ev)
def sums(f):
    s = np.zeros(k); n = np.zeros(k)
    np.add.at(s, f.event_id.map(idx).to_numpy(), f.pnl_ps.to_numpy()); np.add.at(n, f.event_id.map(idx).to_numpy(), 1)
    return s, n
ls, ln = sums(lean); as_, an = sums(anti)
rng = np.random.default_rng(0)
g = []
for _ in range(2000):
    p = rng.integers(0, k, k)
    g.append(ls[p].sum() / ln[p].sum() - as_[p].sum() / an[p].sum())
g = np.array(g) * 100
print(f"gap lean-anti OOS {(ls.sum()/ln.sum()-as_.sum()/an.sum())*100:.2f}c CI [{np.percentile(g,2.5):.2f}, {np.percentile(g,97.5):.2f}]"
      f" P(gap<=0)={np.mean(g<=0):.3f}; P(gap>=3.31 IS)={np.mean(g>=3.31):.3f}")

# 2. alternative CIs for the primary
s, n = lean.groupby("event_id").pnl_ps.sum(), lean.groupby("event_id").size()
mu = s.sum() / n.sum()
G = len(s)
se = np.sqrt(G / (G - 1) * (((s - mu * n) ** 2).sum()) / n.sum() ** 2)
print(f"primary {mu*100:.3f}c cluster-robust SE {se*100:.3f}c t-CI [{(mu-1.96*se)*100:.2f}, {(mu+1.96*se)*100:.2f}] z={mu/se:.2f}")
print("bootstrap lower bound across seeds 0-9:", [round(cluster_ci(lean, seed=sd)[0], 2) for sd in range(10)])
# market-clustered and day-clustered for comparison
for by in ("cond", "day"):
    f = lean.assign(day=pd.to_datetime(lean.ts, unit="s", utc=True).dt.floor("D").astype(str))
    f = f.assign(event_id=f[by])
    print(f"CI clustered by {by}:", [round(x, 2) for x in cluster_ci(f)], "clusters", f.event_id.nunique())

# 3. dollar concentration
lean["day"] = pd.to_datetime(lean.ts, unit="s", utc=True).dt.floor("D")
print("fills > $100:", int((lean.usd > 100).sum()), "notional share", round(lean[lean.usd > 100].usd.sum() / lean.usd.sum(), 3),
      "their $ P&L", round(lean[lean.usd > 100].pnl.sum(), 1), "rest $ P&L", round(lean[lean.usd <= 100].pnl.sum(), 1))
top = lean.reindex(lean.pnl.abs().sort_values(ascending=False).index).head(10)
print("top-10 |$| fills sum", round(top.pnl.sum(), 1), "of total", round(lean.pnl.sum(), 1))
evp = lean.groupby("event_id").pnl.sum().sort_values()
print("worst 5 matches $", evp.head(5).round(1).to_dict(), "total ex worst 5:", round(evp.iloc[5:].sum(), 1),
      "ex best 5:", round(evp.iloc[:-5].sum(), 1))
print("payout 0.5 fills", int((lean.payout == 0.5).sum()), "excl them net_c", round(lean[lean.payout != 0.5].pnl_ps.mean() * 100, 3),
      "their $", round(lean[lean.payout == 0.5].pnl.sum(), 1))

# 4. stresses (ii) and (iv), own code
rows = []
for cond, g0 in pp.groupby("cond", sort=False):
    g0 = g0.sort_values("ts", kind="stable")
    ts, q, aa, tstar = g0.ts.to_numpy(), g0.q0.to_numpy(), g0.at_ask.to_numpy(), g0.tstar.to_numpy()
    L = {}
    for name, mask, tok in (("L0", ~aa, lambda x: x), ("L1", aa, lambda x: 1 - x)):
        tss, qs = ts[mask], q[mask]
        out = np.full(len(g0), np.nan)
        if len(tss):
            j = np.searchsorted(tss, tstar, "left") - 1
            jj = np.maximum(j, 0)
            ok = (j >= 0) & (tstar - tss[jj] <= 120)
            out = np.where(ok, tok(qs[jj]), np.nan)
        L[name] = out
    rows.append(pd.DataFrame({"L0": L["L0"], "L1": L["L1"]}, index=g0.index))
pp = pp.join(pd.concat(rows))
c = pp.dropna(subset=["q_ref", "p_ref", "p_new", "impl", "res_s0"])
c = c[(c.tstar - c.ts_r) <= 600]
idir = np.sign(c.impl); tdir = np.where(c.at_ask, 1.0, -1.0)
f = c[(tdir == -idir) & (c.impl.abs() >= 0.04)].copy()
long0 = f.impl > 0
tok_px = np.where(long0, f.q0, 1 - f.q0)
Lv = np.where(long0, f.L0, f.L1)
ok = np.isfinite(Lv) & (tok_px < Lv) & (Lv > 0.02) & (Lv < 0.98)
f = f[ok].assign(px=Lv[ok]).sort_values("ts", kind="stable")
payout = np.where(f.impl > 0, f.res_s0, 1 - f.res_s0)
for nm, share, reb in (("ii", 0.2, True), ("iv", 0.1, False)):
    sh = np.minimum(share * f["size"], 250 / f.px)
    r = 0.15 * f.fee_rate * f.px * (1 - f.px) if reb else 0.0
    b = f.assign(pnl_ps=payout - f.px + r, shares=sh)
    b = b.assign(pnl=b.shares * b.pnl_ps)
    print(f"stress ({nm}) own code: n={len(b)} net {b.pnl_ps.mean()*100:.3f}c CI {[round(x,2) for x in cluster_ci(b)]} $ {b.pnl.sum():.1f}")
