"""v2 with the causal (detection-time) window, on IS + burned OOS, plus slippage sensitivity.
Burned OOS is non-blind (see HYPOTHESIS_V2.md); split by match start (universe().oos)."""
import datetime as dt, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src import v2
from src.tape import universe

u = universe()
oos_conds = set(u.loc[u.oos, "cond"])
p = pd.concat([pd.read_parquet("data/is_prints.parquet"), pd.read_parquet("data/locked/oos_prints.parquet")], ignore_index=True)
out = {}
for causal in (True, False):
    tr, _ = v2.run(p, u.set_index("cond").end, causal=causal)
    tag = "causal" if causal else "onset"
    if causal:
        tr.to_parquet("data/v2_trades_is_oos.parquet")
    for name, part in (("is_eval", tr[(tr.month >= v2.E.EVAL_START) & ~tr.cond.isin(oos_conds)]),
                       ("burned_oos", tr[tr.cond.isin(oos_conds)])):
        for slip in ((0.0, 0.005, 0.01) if causal else (0.0,)):
            q = part.assign(pnl_ps=part.pnl_ps - slip)
            q = q.assign(pnl=q.shares * q.pnl_ps)
            m = v2.E.metrics(q)
            key = f"{tag}/{name}/slip{slip}"
            out[key] = m
            print(key, {k: (round(m[k], 3) if isinstance(m[k], float) else m[k]) for k in
                        ("n_trades", "per_share_c", "per_share_ci_c", "total_pnl_usd", "sharpe_ann", "max_dd_pct", "months_positive", "months_total", "capital_usd")})
Path("results/v2").mkdir(parents=True, exist_ok=True)
Path("results/v2/causal.json").write_text(json.dumps(out, indent=2, default=float))
B = {"is_eval": out["causal/is_eval/slip0.0"], "burned_oos": out["causal/burned_oos/slip0.0"]}
Path("results/v2/burned_oos.json").write_text(json.dumps(B, indent=2, default=float))
with open("results/oos_peeks.log", "a") as f:
    f.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} v2-causal (D9 fix) evaluated on burned OOS (non-blind)\n")
