"""Stage 2: condition the fast-tier trades on features known at decision time (nested walk-forward).

    .venv/bin/python research/v2/selection/features_wf.py      (needs qualify_grid.py output)

Base set = the uncapped month-m trades of wallets chosen by the stage-1 primary nested rule
(and, for comparison, by the baseline rule). For month m, every filter is fitted only on base
trades from evaluated months < m (themselves walk-forward picks), priced at the fee known at m:
  single-feature filters  keep the bins whose prior mean(mo30) - fee_now * mean(p(1-p)) > 0
  ridge model             one-hot of all features -> predicted mo30; keep if pred - fee_now*p(1-p) > thr
  unified model           ALL wallets' 0-3 s prints, wallet past-edge features + trade features
Then a nested meta-choice among these (same pre-specified objective as stage 1) gives the honest series.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import (BASELINE, CACHE, HERE, Engine, Rule, apply_cap, jsonable, month_rows, regime_table, summarize,
                    wallet_scores)
from qualify_grid import GRID, OBJECTIVES, light_stats, nested_choice, objective

OUT = HERE / "out"
MIN_TRAIN, MIN_BIN = 3000, 200
RIDGE_LAMBDA = 100.0
STAGE2_META_HISTORY = 3
UNIFIED_LOOK, UNIFIED_MM = "all", 5


def add_bins(d: pd.DataFrame) -> dict:
    inf = np.inf
    b = {
        "since": np.where(d.since == 0, "0s", "1-2s"),
        "size": pd.cut(d.usd, [0, 50, 250, 1000, inf], right=False, labels=["<50", "50-250", "250-1k", ">=1k"]),
        "price": pd.cut(d.px, [0, .2, .4, .6, .8, 1.01], right=False, labels=["<.2", ".2-.4", ".4-.6", ".6-.8", ">=.8"]),
        "spread": np.select([d.pre_spread.isna(), d.pre_spread <= 0.0105, d.pre_spread <= 0.0305],
                            ["na", "<=1c", "1-3c"], ">3c"),
        "payup": np.select([d.pay_up.isna(), d.pay_up <= 0, d.pay_up <= 0.0105, d.pay_up <= 0.0305],
                           ["na", "<=0", "0-1c", "1-3c"], ">3c"),
        "volume": pd.cut(d.cum_usd, [-1, 1e4, 5e4, 2e5, inf], labels=["<10k", "10-50k", "50-200k", ">=200k"]),
        "series": d.series.to_numpy(),
        "tstart": pd.cut(d.t_start / 60, [-inf, 30, 60, 120, inf], labels=["<30m", "30-60m", "60-120m", ">=120m"]),
        "njumps": pd.cut(d.n_jumps, [-1, 5, 15, 30, inf], labels=["0-5", "6-15", "16-30", ">30"]),
    }
    for k, v in b.items():
        d["f_" + k] = pd.Categorical(np.asarray(v).astype(str))
    return {k: "f_" + k for k in b}


def bin_filter(train: pd.DataFrame, test: pd.DataFrame, col: str, fee: float, margin: float = 0.0) -> np.ndarray:
    if len(train) < MIN_TRAIN:
        return np.ones(len(test), bool)
    g = train.groupby(col, observed=True).agg(mo=("mo30", "mean"), pq=("pq", "mean"), n=("mo30", "count"))
    good = set(g.index[(g.mo - fee * g.pq > margin) | (g.n < MIN_BIN)])
    seen = set(g.index)
    v = test[col].astype(str).to_numpy()
    return np.array([(x in good) or (x not in seen) for x in v])


def apply_variant(v, train, test, fee, fcols, feature_cols, levels) -> np.ndarray:
    kind, arg = v.split(":", 1)
    if kind == "bin":
        return bin_filter(train, test, fcols[arg], fee, 0.0)
    if kind == "bin@0.5c":
        return bin_filter(train, test, fcols[arg], fee, 0.005)
    if kind == "ridge":
        thr = {"0": 0.0, "0.25c": 0.0025, "0.5c": 0.005}[arg]
        return model_filter(train, test, feature_cols, levels, fee, thr)
    raise ValueError(v)


def design(df: pd.DataFrame, cols: list, levels: dict, extra: list | None = None) -> np.ndarray:
    mats = [np.ones((len(df), 1))]
    for c in cols:
        lv = levels[c][1:]                       # drop the first level
        v = df[c].astype(str).to_numpy()
        mats.append(np.stack([(v == l).astype(float) for l in lv], axis=1) if lv else np.zeros((len(df), 0)))
    if extra:
        mats.append(df[extra].to_numpy(dtype=float))
    return np.hstack(mats)


def ridge(X, y, lam):
    p = X.shape[1]
    reg = lam * np.eye(p)
    reg[0, 0] = 0
    return np.linalg.solve(X.T @ X + reg, X.T @ y)


def model_filter(train, test, cols, levels, fee, thr) -> np.ndarray:
    if len(train) < MIN_TRAIN:
        return np.ones(len(test), bool)
    tr = train[train.mo30.notna()]
    beta = ridge(design(tr, cols, levels), tr.mo30.clip(-0.25, 0.25).to_numpy(), RIDGE_LAMBDA)
    pred = design(test, cols, levels) @ beta - fee * test.pq.to_numpy()
    return pred > thr


def unified_scores(E: Engine) -> pd.DataFrame:
    """Wallet features for every print in month m from data < m (eligible = enough history)."""
    parts = []
    for m in E.eval_months:
        sc = wallet_scores(E.wm, m, UNIFIED_LOOK, UNIFIED_MM, E.fee_now[m])
        x = E.by_month[m][["wid"]].copy()
        s = sc.reindex(x.wid.to_numpy())
        x["u_elig"] = s.eb.notna().to_numpy().astype(float)
        x["u_eb"] = s.eb.fillna(0).clip(-0.05, 0.05).to_numpy() * 10     # in units of 10c
        x["u_lognm"] = np.log1p(s.nm.fillna(0).to_numpy())
        parts.append(x)
    return pd.concat(parts)


def main():
    OUT.mkdir(exist_ok=True)
    E = Engine()
    fcols = add_bins(E.d)
    E.by_month = {m: g for m, g in E.d.groupby("month")}
    levels = {c: sorted(E.d[c].astype(str).unique()) for c in fcols.values()}
    s1 = json.loads((OUT / "stage1.json").read_text())
    rule_of = {r.name: r for r in GRID}
    ch1 = {m: (rule_of[s1["nested"]["pnl30_now_all"]["choice"][str(m)]]
               if s1["nested"]["pnl30_now_all"]["choice"][str(m)] != "stand_aside" else None) for m in E.eval_months}
    bases = {"nested": E.trades(lambda m: ch1[m], cap=False), "baseline": E.trades(BASELINE, cap=False)}

    # unified model universe: all wallets' 0-3 s prints in evaluated months, with wallet features
    allp = pd.concat([E.by_month[m] for m in E.eval_months])
    us = unified_scores(E)
    allp = allp.assign(u_elig=us.u_elig.to_numpy(), u_eb=us.u_eb.to_numpy(), u_lognm=us.u_lognm.to_numpy())

    variants = (["none"] + [f"bin:{k}" for k in fcols] + [f"bin@0.5c:{k}" for k in fcols]
                + ["ridge:0", "ridge:0.25c", "ridge:0.5c"])
    results, months_tab, monthly = {}, [], {}
    feature_cols = list(fcols.values())
    for bname, base in bases.items():
        for v in variants:
            keep_parts = []
            for i, m in enumerate(E.eval_months):
                test = base[base.month == m]
                train = base[base.month < m]
                fee = E.fee_now[m]
                if v == "none":
                    k = np.ones(len(test), bool)
                else:
                    k = apply_variant(v, train, test, fee, fcols, feature_cols, levels)
                keep_parts.append(test[k])
            tr = apply_cap(pd.concat(keep_parts))
            key = f"{bname}|{v}"
            rows = month_rows(tr)
            monthly[key] = (key, rows)
            results[key] = light_stats(tr, E)
            months_tab.append(rows.reset_index().assign(variant=key))
    for thr in (0.0, 0.0025, 0.005):
        keep_parts = []
        for m in E.eval_months:
            test = allp[allp.month == m]
            train = allp[allp.month < m]
            if len(train) < MIN_TRAIN * 5:
                keep_parts.append(test[test.wid.isin(E.selected(BASELINE, m))])   # no history yet: baseline
                continue
            tr0 = train[train.mo30.notna()]
            extra = ["u_elig", "u_eb", "u_lognm"]
            beta = ridge(design(tr0, feature_cols, levels, extra), tr0.mo30.clip(-0.25, 0.25).to_numpy(), RIDGE_LAMBDA)
            pred = design(test, feature_cols, levels, extra) @ beta - E.fee_now[m] * test.pq.to_numpy()
            keep_parts.append(test[pred > thr])
        tr = apply_cap(pd.concat(keep_parts))
        key = f"unified|{thr * 100:g}c"
        rows = month_rows(tr)
        monthly[key] = (key, rows)
        results[key] = light_stats(tr, E)
        months_tab.append(rows.reset_index().assign(variant=key))
        if thr == 0.0:
            res_beta = dict(zip(["const"] + [f"{c}={l}" for c in feature_cols for l in levels[c][1:]] + extra,
                                np.round(beta * 100, 3)))
    grid = pd.DataFrame(results).T
    grid.to_csv(OUT / "stage2_variants.csv")
    pd.concat(months_tab).to_csv(OUT / "stage2_months.csv", index=False)

    # nested meta choice among the stage-2 variants built on the nested stage-1 base (+ unified)
    cand = {k: v for k, v in monthly.items() if k.startswith("nested|") or k.startswith("unified|")}
    out = {"n_variants_stage2": len(monthly), "variants": grid, "unified_last_beta_c": res_beta, "nested": {}}
    for kind in ["pnl30_now_all", "pnl30_now_last3"]:
        choice = {}
        for i, m in enumerate(E.eval_months):
            if i < 1 + 2 + STAGE2_META_HISTORY:     # filters start in month 3 (Feb); need 3 months of their record
                choice[m] = "nested|none"
                continue
            prior = E.eval_months[:i]
            best = max(cand, key=lambda k: objective(cand[k][1][cand[k][1].index.isin(prior)], E.fee_now[m], kind))
            choice[m] = best
        # assemble the nested stage-2 series month by month from each chosen variant's trades
        parts = []
        for m, k in choice.items():
            parts.append((m, k))
        out["nested"][kind] = {"choice": {str(m): k for m, k in choice.items()}}
    # rebuild the chosen series' trades (need trade level for stats)
    for kind in out["nested"]:
        choice = {pd.Period(k, "M"): v for k, v in out["nested"][kind]["choice"].items()}
        tr = rebuild(E, bases, allp, choice, fcols, feature_cols, levels)
        out["nested"][kind].update(summary=summarize(tr, E.u, E.eval_days), light=light_stats(tr, E),
                                   months=month_rows(tr).drop(columns=["sh_mo30", "sh_mores", "sh_pq"]),
                                   regimes=regime_table(tr))
        tr.to_parquet(CACHE / f"stage2_nested_{kind}_trades.parquet")
    # what the primary stage-2 meta rule would freeze for the next month
    out["frozen_next_stage2_primary"] = max(cand, key=lambda k: objective(cand[k][1], 0.05, "pnl30_now_all"))
    out["frozen_next_stage2_last3"] = max(cand, key=lambda k: objective(cand[k][1], 0.05, "pnl30_now_last3"))

    # descriptive: feature bins on the stage-1 nested walk-forward trades (capped), all months and Jul-Aug
    t1 = apply_cap(bases["nested"])
    desc = []
    for f, c in fcols.items():
        for period, sub in (("all", t1), ("jul_aug", t1[t1.month >= pd.Period("2026-07", "M")]),
                            ("1s5", t1[t1.regime == "1s/5%"])):
            g = sub.assign(pnl=sub.shares * sub.net_res).groupby(c, observed=True).agg(
                n=("ts", "size"), gross30_c=("mo30", "mean"), net30_c=("net30", "mean"), net_res_c=("net_res", "mean"),
                fee_c=("fee", "mean"), pnl=("pnl", "sum"))
            g[["gross30_c", "net30_c", "net_res_c", "fee_c"]] *= 100
            desc.append(g.reset_index().rename(columns={c: "bin"}).assign(feature=f, period=period))
    desc = pd.concat(desc)
    desc.to_csv(OUT / "stage2_feature_bins.csv", index=False)
    out["feature_bins_1s5"] = desc[desc.period == "1s5"]
    (OUT / "stage2.json").write_text(json.dumps(jsonable(out), indent=1))
    pd.set_option("display.width", 250)
    cols = ["n", "net30_c", "net_res_c", "pnl", "pnl30", "sharpe", "n_1s5", "net30_1s5_c", "net_res_1s5_c", "pnl_1s5",
            "pnl30_1s5", "sharpe_1s5"]
    print(grid[cols].astype(float).round(3).to_string())
    for k, v in out["nested"].items():
        print(k, v["choice"])
        print({kk: round(float(vv), 3) for kk, vv in v["light"].items()})
    print("frozen", out["frozen_next_stage2_primary"], out["frozen_next_stage2_last3"])
    print(desc[desc.period == "1s5"].round(3).to_string())


def rebuild(E, bases, allp, choice, fcols, feature_cols, levels) -> pd.DataFrame:
    parts = []
    for i, m in enumerate(E.eval_months):
        key = choice[m]
        if key.startswith("unified|"):
            thr = float(key.split("|")[1][:-1]) / 100
            test = allp[allp.month == m]
            train = allp[allp.month < m]
            tr0 = train[train.mo30.notna()]
            extra = ["u_elig", "u_eb", "u_lognm"]
            beta = ridge(design(tr0, feature_cols, levels, extra), tr0.mo30.clip(-0.25, 0.25).to_numpy(), RIDGE_LAMBDA)
            pred = design(test, feature_cols, levels, extra) @ beta - E.fee_now[m] * test.pq.to_numpy()
            parts.append(test[pred > thr])
            continue
        bname, v = key.split("|", 1)
        base = bases[bname]
        test, train, fee = base[base.month == m], base[base.month < m], E.fee_now[m]
        k = np.ones(len(test), bool) if v == "none" else apply_variant(v, train, test, fee, fcols, feature_cols, levels)
        parts.append(test[k])
    return apply_cap(pd.concat(parts))


if __name__ == "__main__":
    main()
