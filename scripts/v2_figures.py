"""Fig. 6: v1 vs v2 cumulative P&L and v2 by month (IS + burned OOS)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import run_all
from src import fasttier, report
from src.tape import universe

u = universe()
oos0 = u.loc[u.oos, "start"].min()
tr = pd.read_parquet("data/v2_trades_is_oos.parquet")
tr = tr[tr.month >= "2026-02"]
v2d = tr.groupby(pd.to_datetime(tr.ts, unit="s").dt.floor("D")).pnl.sum()
p = pd.concat([pd.read_parquet("data/is_prints.parquet"), pd.read_parquet("data/locked/oos_prints.parquet")], ignore_index=True)
_, sh, _ = fasttier.walk_forward(p)
sh1, _ = run_all.shadow_book(sh, u)
sh1 = sh1.assign(pnl=sh1.shares * sh1.net_res)
sh1 = sh1[pd.to_datetime(sh1.ts, unit="s") >= pd.Timestamp("2026-02-01")]
v1d = sh1.groupby(pd.to_datetime(sh1.ts, unit="s").dt.floor("D")).pnl.sum()
idx = v1d.index.union(v2d.index)
mon = tr.groupby("month").pnl.sum().reset_index()
import json
S = json.loads(Path("results/summary.json").read_text())
B = json.loads(Path("results/v2/burned_oos.json").read_text())
v1c, v2c = S["is"]["h6_shadow"]["capital"], B["is_eval"]["capital_usd"]
o1 = S['oos']['h6_shadow']['total_pnl_usd'] / 1e3
lab1 = f"v1 dollar sizing: Sharpe {S['is']['h6_shadow']['sharpe_ann']:.1f} IS, OOS {'−' if o1 < 0 else '+'}${abs(o1):,.0f}k"
lab2 = f"v2 risk sizing + net cap: Sharpe {B['is_eval']['sharpe_ann']:.1f} IS, OOS +${B['burned_oos']['total_pnl_usd']/1e3:,.1f}k"
report.v2_figure(v1d.reindex(idx, fill_value=0), v2d.reindex(idx, fill_value=0), mon, oos0.tz_localize(None), v1c, v2c, lab1, lab2)
print(mon)
