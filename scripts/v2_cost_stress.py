"""v2 (causal) with costs doubled: the brief's "what happens when costs double" check.

Trades are held fixed (the frozen v2 book from scripts/v2_causal.py); only the cost charged per share
changes. pnl_ps in the book is already net of each match's own taker fee, rate*q*(1-q).
  base          as reported (actual fee, fills at the fast tier's own prices)
  fee_x2        the actual fee charged twice
  fee5_x2       today's 5% fee charged twice on every trade, including the 0%-fee months
  costs_x2      fee charged twice + an extra half-spread (0.5c, a 1c spread) on every share
  costs_x2_1c   fee charged twice + 1c on every share
A fee-aware wallet filter would drop marginal trades if fees really doubled, so holding the book fixed
is the harsher test. Burned OOS is non-blind (HYPOTHESIS_V2.md); no parameter is changed here.
"""
import datetime as dt, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src import v2
from src.tape import universe

u = universe()
oos_conds = set(u.loc[u.oos, "cond"])
tr = pd.read_parquet("data/v2_trades_is_oos.parquet")
SCEN = {
    "base": lambda t: t.pnl_ps,
    "fee_x2": lambda t: t.pnl_ps - t.fee,
    "fee5_x2": lambda t: t.gross_res - 2 * t.fee5,
    "costs_x2": lambda t: t.pnl_ps - t.fee - 0.005,
    "costs_x2_1c": lambda t: t.pnl_ps - t.fee - 0.01,
}
KEYS = ("n_trades", "per_share_c", "per_share_ci_c", "total_pnl_usd", "sharpe_ann", "max_dd_pct",
        "worst_day_usd", "worst_month_usd", "months_positive", "months_total")
out = {}
for name, part in (("is_eval", tr[(tr.month >= v2.E.EVAL_START) & ~tr.cond.isin(oos_conds)]),
                   ("burned_oos", tr[tr.cond.isin(oos_conds)])):
    for s, f in SCEN.items():
        q = part.assign(pnl_ps=f(part))
        q = q.assign(pnl=q.shares * q.pnl_ps)
        m = v2.E.metrics(q)
        out[f"{name}/{s}"] = {k: m[k] for k in KEYS}
        print(f"{name:10} {s:12}", {k: (round(m[k], 2) if isinstance(m[k], float) else m[k]) for k in KEYS})
Path("results/v2").mkdir(parents=True, exist_ok=True)
first_time = not Path("results/v2/cost_stress.json").exists()
Path("results/v2/cost_stress.json").write_text(json.dumps(out, indent=2, default=float))
if first_time:
    with open("results/oos_peeks.log", "a") as fh:
        fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} v2 cost stress (fees/costs doubled, book fixed) on burned OOS (non-blind, no parameter change)\n")
