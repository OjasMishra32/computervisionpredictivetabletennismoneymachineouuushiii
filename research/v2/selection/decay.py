"""Edge decay, crowding, score calibration, recency in the 1 s / 5% months, and an all-bucket check.

    .venv/bin/python research/v2/selection/decay.py       (needs qualify_grid.py output)

All diagnostics use walk-forward selections (wallets picked on months < m, measured in m), IS only.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy import stats as sps

from common import BASELINE, HERE, ROOT, Engine, Rule, jsonable, wallet_scores
from qualify_grid import GRID

OUT = HERE / "out"
FROZEN = Rule("ew2", "eb", 0.005, 5)        # the rule the primary nested procedure freezes (stage1.json)


def cohort_table(E: Engine, rule: Rule) -> pd.DataFrame:
    first, rows = {}, []
    for m in E.eval_months:
        sel = E.selected(rule, m)
        for w in sel:
            first.setdefault(int(w), m)
        x = E.by_month[m]
        x = x[np.isin(x.wid.to_numpy(), sel)]
        coh = x.wid.map(lambda w: first[int(w)])
        lab = np.select([coh <= pd.Period("2026-02", "M"), coh <= pd.Period("2026-04", "M"),
                         coh <= pd.Period("2026-06", "M")], ["<=Feb", "Mar-Apr", "May-Jun"], "Jul-Aug")
        g = x.assign(cohort=lab).groupby("cohort").agg(n=("ts", "size"), wallets=("wid", "nunique"),
                                                       gross30_c=("mo30", "mean"), net30_c=("net30", "mean"),
                                                       net_res_c=("net_res", "mean"))
        rows.append(g.reset_index().assign(month=str(m)))
    t = pd.concat(rows)
    t[["gross30_c", "net30_c", "net_res_c"]] *= 100
    return t


def crowding(E: Engine, choice: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    per_month, parts = [], []
    for m in E.eval_months:
        r = choice[m]
        x = E.by_month[m]
        sel = E.selected(r, m) if r is not None else np.array([], dtype=np.int32)
        bsel = E.selected(BASELINE, m)
        fast = np.isin(x.wid.to_numpy(), sel)
        x = x.assign(jump=x.cond + ":" + (x.ts - x.since).astype(int).astype(str), fast=fast)
        nfast = x[x.fast].groupby("jump").wid.nunique()
        x["n_fast_in_jump"] = x.jump.map(nfast).fillna(0).astype(int)
        f = x[x.fast]
        parts.append(f.assign(mgroup=("Dec-Apr" if m <= pd.Period("2026-04", "M") else
                                      "May-Jun" if m <= pd.Period("2026-06", "M") else "Jul-Aug")))
        per_month.append({"month": str(m), "n_qual_baseline": len(bsel), "n_qual_nested": len(sel),
                          "share_usd_0_3s_baseline_wallets": float(x.usd[np.isin(x.wid, bsel)].sum() / x.usd.sum()),
                          "share_usd_0_3s_nested_wallets": float(x.usd[x.fast].sum() / x.usd.sum()),
                          "jumps_with_any_nested_fast": int(nfast.size), "jumps_total": int(x.jump.nunique()),
                          "mean_nested_fast_per_active_jump": float(nfast.mean()) if len(nfast) else 0.0,
                          "gross30_nested_c": float(f.mo30.mean() * 100), "fee_c": float(f.fee.mean() * 100),
                          "net30_nested_c": float(f.net30.mean() * 100),
                          "others_net30_c": float(x[~x.fast].net30.mean() * 100)})
    f = pd.concat(parts)
    f["crowd"] = pd.cut(f.n_fast_in_jump, [0, 1, 2, 4, 8, 1e9], labels=["1", "2", "3-4", "5-8", "9+"])
    c = f.groupby(["mgroup", "crowd"], observed=True).agg(n=("ts", "size"), gross30_c=("mo30", "mean"),
                                                          net30_c=("net30", "mean"), net_res_c=("net_res", "mean"))
    c[["gross30_c", "net30_c", "net_res_c"]] *= 100
    return pd.DataFrame(per_month), c.reset_index()


def rank_ic(E: Engine) -> pd.DataFrame:
    rows = []
    for m in E.eval_months[1:]:
        sc = wallet_scores(E.wm, m, "all", 5, E.fee_now[m])
        x = E.by_month[m]
        real = x.groupby("wid").agg(n_m=("ts", "size"), net30=("net30", "mean"), gross=("mo30", "mean"))
        real = real[real.n_m >= 20]
        j = sc.join(real, how="inner")
        if len(j) < 20:
            continue
        r = {"month": str(m), "n_wallets": len(j)}
        for s in ("t", "mean", "eb", "tnet", "eb_net"):
            r[f"ic_{s}"] = float(sps.spearmanr(j[s], j.net30).statistic)
        sl = sps.linregress(j.eb, j.gross)
        r["calib_slope_gross_on_eb"], r["calib_intercept_c"] = float(sl.slope), float(sl.intercept * 100)
        top = j[j.eb_net > 0.005]
        r["n_eb_net_gt_0.5c"] = len(top)
        r["realized_net30_eb_sel_c"] = float(top.net30.mean() * 100) if len(top) else np.nan
        t3 = j[j.t > 3]
        r["realized_net30_t3_sel_c"] = float(t3.net30.mean() * 100) if len(t3) else np.nan
        t3_not_eb = j[(j.t > 3) & (j.eb_net <= 0.005)]
        r["n_t3_not_eb"] = len(t3_not_eb)
        r["realized_net30_t3_not_eb_c"] = float(t3_not_eb.net30.mean() * 100) if len(t3_not_eb) else np.nan
        rows.append(r)
    return pd.DataFrame(rows)


def recency(grid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for look in ["1m", "2m", "3m", "6m", "ew1", "ew2", "ew3"]:
        a = grid[grid.look == look].set_index(["score", "thr", "mm"])
        b = grid[grid.look == "all"].set_index(["score", "thr", "mm"])
        j = a.join(b, rsuffix="_all", how="inner")
        rows.append({"look": look, "pairs": len(j),
                     "d_net30_1s5_c": float((j.net30_1s5_c - j.net30_1s5_c_all).mean()),
                     "win_net30_1s5": float((j.net30_1s5_c > j.net30_1s5_c_all).mean()),
                     "d_net_res_1s5_c": float((j.net_res_1s5_c - j.net_res_1s5_c_all).mean()),
                     "d_pnl30_1s5": float((j.pnl30_1s5 - j.pnl30_1s5_all).mean()),
                     "d_net30_all_c": float((j.net30_c - j.net30_c_all).mean())})
    return pd.DataFrame(rows)


def all_buckets(E: Engine, rule: Rule) -> pd.DataFrame:
    """Selected wallets' prints in EVERY bucket (from data/is_prints.parquet, IS only), same month."""
    sel = {m: set(E.d.wallet[E.d.wid.isin(E.selected(rule, m))].unique()) for m in E.eval_months}
    union = set().union(*sel.values())
    cols = ["cond", "ts", "p", "dir", "usd", "wallet", "fee_rate", "mo30", "mo_res", "bucket"]
    f = pq.ParquetFile(ROOT / "data/is_prints.parquet")
    parts = []
    for b in f.iter_batches(batch_size=500_000, columns=cols):
        x = b.to_pandas()
        x = x[x.wallet.isin(union)]
        if len(x):
            parts.append(x)
    x = pd.concat(parts)
    x["month"] = pd.to_datetime(x.ts, unit="s").dt.to_period("M")
    keep = np.zeros(len(x), bool)
    for m, s in sel.items():
        keep |= ((x.month == m) & x.wallet.isin(s)).to_numpy()
    x = x[keep]
    fee = x.fee_rate * x.p * (1 - x.p)
    x = x.assign(net30=x.mo30 - fee, net_res=x.mo_res - fee, late=x.month >= pd.Period("2026-07", "M"))
    g = x.groupby(["bucket", "late"], observed=True).agg(n=("ts", "size"), usd=("usd", "sum"),
                                                          gross30_c=("mo30", "mean"), net30_c=("net30", "mean"),
                                                          net_res_c=("net_res", "mean"))
    g[["gross30_c", "net30_c", "net_res_c"]] *= 100
    return g.reset_index()


def main():
    E = Engine()
    s1 = json.loads((OUT / "stage1.json").read_text())
    rule_of = {r.name: r for r in GRID}
    ch = s1["nested"]["pnl30_now_all"]["choice"]
    choice = {m: (rule_of[ch[str(m)]] if ch[str(m)] != "stand_aside" else None) for m in E.eval_months}
    grid = pd.read_csv(OUT / "stage1_grid_summary.csv", index_col=0)
    res = {}
    res["cohorts_baseline"] = cohort_table(E, BASELINE)
    res["cohorts_frozen"] = cohort_table(E, FROZEN)
    res["crowding_by_month"], res["crowding_by_level"] = crowding(E, choice)
    res["rank_ic"] = rank_ic(E)
    res["recency_vs_all_history"] = recency(grid)
    res["all_buckets_frozen_rule"] = all_buckets(E, FROZEN)
    (OUT / "decay.json").write_text(json.dumps(jsonable(res), indent=1))
    pd.set_option("display.width", 250)
    for k, v in res.items():
        print("==", k)
        print(v.round(3).to_string())


if __name__ == "__main__":
    main()
