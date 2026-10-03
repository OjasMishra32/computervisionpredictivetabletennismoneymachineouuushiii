"""v2 on IS only must reproduce the sizing lens (G_50pct_net100: 1.584c/sh, $43,268, Sharpe 16.77)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src import v2
from src.tape import universe

u = universe()
p = pd.read_parquet("data/is_prints.parquet")
tr, wf = v2.run(p, u.set_index("cond").end)
ev = tr[tr.month >= v2.E.EVAL_START]
m = v2.E.metrics(ev)
print({k: m[k] for k in m if k in ("n_trades", "per_share_c", "ci95_c", "total_pnl", "sharpe", "max_dd_pct", "capital")} if isinstance(m, dict) else m)
print(m)
