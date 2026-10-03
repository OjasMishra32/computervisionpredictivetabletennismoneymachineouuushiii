"""Stage 1: walk-forward wallet-qualification variants + nested (honest) choice among them.

    .venv/bin/python research/v2/selection/qualify_grid.py

Every variant qualifies wallets in month m from data strictly before m and is scored on month m.
The NESTED series picks, in each month m, the variant whose own walk-forward record on the earlier
evaluated months was best (objectives pre-specified below), re-priced at the fee known at the
start of m. Only the nested series is an honest estimate; single-variant series are diagnostics.
Outputs go to research/v2/selection/out/.
"""
from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from common import (BASELINE, CACHE, HERE, NESTED_MIN_HISTORY, Engine, Rule, jsonable, month_rows, regime_table,
                    summarize)

OUT = HERE / "out"
LOOKS = ["all", "1m", "2m", "3m", "6m", "ew1", "ew2", "ew3"]
SCORES = [("t", 2), ("t", 3), ("t", 4), ("t", 5), ("top", 10), ("top", 25), ("top", 50),
          ("tnet", 2), ("tnet", 3), ("eb", 0.0), ("eb", 0.0025), ("eb", 0.005)]
MMS = [5, 10, 20]
GRID = [Rule(l, s, t, mm) for l, (s, t), mm in itertools.product(LOOKS, SCORES, MMS)]

# Pre-specified nested objectives (primary = "pnl30_now_all"). Each is computed on a variant's own
# walk-forward months j < m, re-priced at fee_now[m] (the fee rate known when month m starts).
OBJECTIVES = ["pnl30_now_all", "pnl30_now_last3", "pnlres_now_all", "net30ps_now_all"]


def objective(rows: pd.DataFrame, fee: float, kind: str) -> float:
    if rows.empty:
        return -np.inf
    if kind.endswith("last3"):
        rows = rows.iloc[-3:]
    if kind.startswith("pnl30"):
        return float((rows.sh_mo30 - fee * rows.sh_pq).sum())
    if kind.startswith("pnlres"):
        return float((rows.sh_mores - fee * rows.sh_pq).sum())
    if kind.startswith("net30ps"):
        if rows.n.mean() < 1000:          # tiny books cannot be judged per share
            return -np.inf
        return float((rows.sh_mo30 - fee * rows.sh_pq).sum() / rows.shares.sum())
    raise ValueError(kind)


def nested_choice(E: Engine, monthly: dict, kind: str, stand_aside: bool = True) -> dict:
    """month -> Rule (or None = stand aside), using only variants' results on earlier evaluated months."""
    choice = {}
    for i, m in enumerate(E.eval_months):
        if i < NESTED_MIN_HISTORY:
            choice[m] = BASELINE
            continue
        prior = E.eval_months[:i]
        best, best_v = None, -np.inf
        for name, (rule, rows) in monthly.items():
            v = objective(rows[rows.index.isin(prior)], E.fee_now[m], kind)
            if v > best_v:
                best, best_v = rule, v
        choice[m] = best if (best_v > 0 or not stand_aside) else None
    return choice


def light_stats(tr: pd.DataFrame, E: Engine) -> dict:
    pnl = tr.shares * tr.net_res
    daily = pnl.groupby(tr.date).sum().reindex(E.eval_days, fill_value=0.0)
    r5 = tr[tr.regime == "1s/5%"]
    pnl5 = r5.shares * r5.net_res
    d5 = pnl5.groupby(r5.date).sum().reindex(pd.date_range(pd.Timestamp("2026-07-01", tz="UTC"), E.eval_days[-1], freq="D"),
                                             fill_value=0.0)
    late = tr[tr.month >= pd.Period("2026-07", "M")]
    return {"n": len(tr), "net30_c": tr.net30.mean() * 100, "net_res_c": tr.net_res.mean() * 100,
            "pnl": pnl.sum(), "pnl30": (tr.shares * tr.net30).sum(),
            "sharpe": daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else np.nan,
            "n_1s5": len(r5), "net30_1s5_c": r5.net30.mean() * 100, "net_res_1s5_c": r5.net_res.mean() * 100,
            "pnl_1s5": pnl5.sum(), "pnl30_1s5": (r5.shares * r5.net30).sum(),
            "sharpe_1s5": d5.mean() / d5.std() * np.sqrt(365) if d5.std() > 0 else np.nan,
            "net30_julaug_c": late.net30.mean() * 100, "net_res_julaug_c": late.net_res.mean() * 100,
            "pnl_julaug": (late.shares * late.net_res).sum()}


def main():
    OUT.mkdir(exist_ok=True)
    E = Engine()
    monthly, summ, mrows = {}, [], []
    for r in GRID:
        tr = E.trades(r)
        rows = month_rows(tr)
        monthly[r.name] = (r, rows)
        s = light_stats(tr, E)
        s.update(variant=r.name, look=r.look, score=r.score, thr=r.thr, mm=r.mm,
                 months_pos_net30=int((rows.net30_c > 0).sum()), months_pos_pnl=int((rows.pnl > 0).sum()),
                 months=len(rows), mean_wallets=rows.wallets.mean())
        summ.append(s)
        mrows.append(rows.reset_index().assign(variant=r.name))
    grid = pd.DataFrame(summ).set_index("variant")
    grid.to_csv(OUT / "stage1_grid_summary.csv")
    pd.concat(mrows).to_csv(OUT / "stage1_grid_months.csv", index=False)

    res = {"n_variants_grid": len(GRID), "baseline": BASELINE.name, "nested": {}}
    base_tr = E.trades(BASELINE)
    res["baseline_summary"] = summarize(base_tr, E.u, E.eval_days)
    res["baseline_months"] = month_rows(base_tr).drop(columns=["sh_mo30", "sh_mores", "sh_pq"])
    res["baseline_regimes"] = regime_table(base_tr)
    for kind in OBJECTIVES:
        ch = nested_choice(E, monthly, kind)
        tr = E.trades(lambda m: ch[m])
        rows = month_rows(tr)
        res["nested"][kind] = {
            "choice": {str(m): (r.name if r is not None else "stand_aside") for m, r in ch.items()},
            "summary": summarize(tr, E.u, E.eval_days), "light": light_stats(tr, E),
            "months": rows.drop(columns=["sh_mo30", "sh_mores", "sh_pq"]), "regimes": regime_table(tr)}
        tr.to_parquet(CACHE / f"stage1_nested_{kind}_trades.parquet")
    # the rule the primary nested procedure would freeze for the next (unseen) month
    fake_next = E.eval_months[-1] + 1
    E.fee_now[fake_next] = 0.05
    best, best_v = None, -np.inf
    for name, (rule, rows) in monthly.items():
        v = objective(rows, 0.05, "pnl30_now_all")
        if v > best_v:
            best, best_v = rule, v
    res["frozen_next_rule_primary"] = best.name
    best3 = max(monthly.items(), key=lambda kv: objective(kv[1][1], 0.05, "pnl30_now_last3"))
    res["frozen_next_rule_last3"] = best3[0]
    res["grid_1s5_distribution"] = {
        "share_variants_net_res_1s5_pos": float((grid.net_res_1s5_c > 0).mean()),
        "share_variants_net30_1s5_pos": float((grid.net30_1s5_c > 0).mean()),
        "median_net_res_1s5_c": float(grid.net_res_1s5_c.median()),
        "median_net30_1s5_c": float(grid.net30_1s5_c.median()),
        "baseline_net_res_1s5_c": float(grid.loc[BASELINE.name, "net_res_1s5_c"]),
        "baseline_net30_1s5_c": float(grid.loc[BASELINE.name, "net30_1s5_c"])}
    (OUT / "stage1.json").write_text(json.dumps(jsonable(res), indent=1))
    cols = ["n", "net30_c", "net_res_c", "pnl", "sharpe", "n_1s5", "net30_1s5_c", "net_res_1s5_c", "pnl_1s5",
            "sharpe_1s5", "mean_wallets"]
    pd.set_option("display.width", 250)
    print(grid.sort_values("pnl30_1s5", ascending=False)[cols].head(25).round(3).to_string())
    print(grid.loc[BASELINE.name, cols])
    for k, v in res["nested"].items():
        print(k, v["choice"])
        print({kk: round(vv, 3) if isinstance(vv, float) else vv for kk, vv in v["light"].items()})
    print("frozen:", res["frozen_next_rule_primary"], res["frozen_next_rule_last3"])


if __name__ == "__main__":
    main()
