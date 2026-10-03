"""v2 on the burned OOS (2026-08-25 14:15 .. 2026-10-03). NON-BLIND: v2's design knew how v1 did here."""
import datetime as dt, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src import v2
from src.tape import universe

u = universe()
p = pd.concat([pd.read_parquet("data/is_prints.parquet"), pd.read_parquet("data/locked/oos_prints.parquet")], ignore_index=True)
tr, wf = v2.run(p, u.set_index("cond").end)
oos0 = u.loc[u.oos, "start"].min().timestamp()
res = {}
for name, part in (("is_eval", tr[(tr.month >= v2.E.EVAL_START) & (tr.ts < oos0)]), ("burned_oos", tr[tr.ts >= oos0])):
    res[name] = v2.E.metrics(part)
    print(name, {k: res[name][k] for k in ("n_trades", "n_matches", "per_share_c", "per_share_ci_c", "total_pnl_usd",
                                          "sharpe_ann", "max_dd_pct", "worst_day_pct", "months_positive", "months_total", "capital_usd")})
oos = tr[tr.ts >= oos0]
print(oos.groupby("month").agg(n=("pnl", "size"), pnl=("pnl", "sum"), ps=("pnl_ps", "mean")).round(3))
Path("results/v2").mkdir(parents=True, exist_ok=True)
Path("results/v2/burned_oos.json").write_text(json.dumps(res, indent=2, default=float))
tr.to_parquet("data/v2_trades_is_oos.parquet")
with open("results/oos_peeks.log", "a") as f:
    f.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} v2 evaluated on burned OOS (non-blind, labelled)\n")
