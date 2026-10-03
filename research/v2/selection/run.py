"""One command for the whole selection lens (IS only, about 2 minutes on one core):

    .venv/bin/python research/v2/selection/run.py            # features -> stage 1 -> stage 2 -> decay -> results.json
    .venv/bin/python research/v2/selection/run.py --report   # only re-assemble results.json + figures from out/

Writes research/v2/selection/results.json and research/v2/selection/out/*.png
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd

from common import BASELINE, CACHE, HERE, Engine, Rule, jsonable, month_rows, regime_table, summarize

OUT = HERE / "out"
FROZEN = Rule("ew2", "eb", 0.005, 5)
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"   # categorical slots 1-3 (validated all-pairs)


def paired_diff(a: pd.DataFrame, b: pd.DataFrame, col: str, n_boot=2000, seed=0):
    ga = a.groupby("cond")[col].agg(["sum", "count"])
    gb = b.groupby("cond")[col].agg(["sum", "count"])
    j = ga.join(gb, lsuffix="_a", rsuffix="_b", how="outer").fillna(0)
    S = j.to_numpy()
    rng = np.random.default_rng(seed)
    k = len(j)
    point = S[:, 0].sum() / S[:, 1].sum() - S[:, 2].sum() / S[:, 3].sum()
    bs = []
    for _ in range(n_boot):
        x = S[rng.integers(0, k, k)]
        bs.append(x[:, 0].sum() / x[:, 1].sum() - x[:, 2].sum() / x[:, 3].sum())
    return float(point * 100), [float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)]


def regime_summary(tr, E):
    r = tr[tr.regime == "1s/5%"]
    days = pd.date_range(pd.Timestamp("2026-07-01", tz="UTC"), E.eval_days[-1], freq="D")
    return summarize(r, E.u, days)


def figures(E, series: dict, grid: pd.DataFrame, s1: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                         "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "figure.facecolor": "white"})
    months = [str(m) for m in E.eval_months]
    x = np.arange(len(months))
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.6), sharey=False)
    nb = series["nested"]
    gm = nb.groupby(nb.month.astype(str)).agg(g=("mo30", "mean"), f=("fee", "mean")).reindex(months) * 100
    ax = axs[0]
    ax.plot(x, gm.g, color=C1, lw=2, marker="o", ms=4, label="gross 30 s markout")
    ax.plot(x, gm.f, color=MUTED, lw=2, ls="--", label="taker fee paid")
    ax.set_title("A. Gross edge vs fee (c/share)", loc="left", color=INK)
    ax.set_ylim(-0.1, 3.2)
    ax.legend(frameon=False, loc="upper left", ncol=2)
    for ax, col, title in ((axs[1], "net30", "B. Net 30 s markout (c/share)"),
                           (axs[2], "net_res", "C. Net to resolution (c/share)")):
        for name, c, lab in (("baseline", MUTED, "baseline t>3"), ("nested", C1, "nested selection")):
            t = series[name]
            v = t.groupby(t.month.astype(str))[col].mean().reindex(months) * 100
            ax.plot(x, v, color=c, lw=2, marker="o", ms=4, label=lab)
        ax.axhline(0, color=INK, lw=0.8)
        ax.axvspan(6.5, 8.5, color=GRID, alpha=0.5, lw=0)
        ax.text(7.5, ax.get_ylim()[1] * 0.92, "1 s / 5%\nmonths", ha="center", va="top", color=MUTED, fontsize=8)
        ax.set_title(title, loc="left", color=INK)
        ax.legend(frameon=False, loc="lower left")
    for ax in axs:
        ax.set_xticks(x, [m[2:] for m in months], rotation=45)
    fig.tight_layout()
    fig.savefig(OUT / "fig_monthly.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    v = grid.net30_1s5_c.sort_values().to_numpy()
    ax.hist(v, bins=30, color=C1, alpha=0.85, edgecolor="white", linewidth=1)
    b = float(grid.loc[BASELINE.name, "net30_1s5_c"])
    n = float(s1["nested"]["pnl30_now_all"]["light"]["net30_1s5_c"])
    ax.axvline(b, color=MUTED, lw=2, ls="--")
    ax.axvline(n, color=C2, lw=2)
    ax.text(b, ax.get_ylim()[1] * 0.95, " baseline t>3", color=INK, va="top", fontsize=8)
    ax.text(n, ax.get_ylim()[1] * 0.80, " nested (honest)", color=INK, va="top", fontsize=8)
    ax.set_xlabel("net 30 s markout in 1 s / 5% matches, c/share")
    ax.set_ylabel("variants")
    ax.set_title(f"All {len(grid)} walk-forward qualification variants, 1 s / 5% regime", loc="left", color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "fig_grid_1s5.png", dpi=160)
    plt.close(fig)


def main(report_only: bool):
    if not report_only:
        if not (CACHE / "feat_0_3s.parquet").exists():
            import build_features
            build_features.main()
        import decay
        import features_wf
        import qualify_grid
        qualify_grid.main()
        features_wf.main()
        decay.main()
    E = Engine()
    s1 = json.loads((OUT / "stage1.json").read_text())
    s2 = json.loads((OUT / "stage2.json").read_text())
    dc = json.loads((OUT / "decay.json").read_text())
    grid = pd.read_csv(OUT / "stage1_grid_summary.csv", index_col=0)
    series = {"baseline": E.trades(BASELINE),
              "nested": pd.read_parquet(CACHE / "stage1_nested_pnl30_now_all_trades.parquet"),
              "nested_stage2": pd.read_parquet(CACHE / "stage2_nested_pnl30_now_all_trades.parquet"),
              "frozen_rule_insample": E.trades(FROZEN)}
    out = {"lens": "selection", "is_only": True, "oos_start_excluded": "2026-08-25 14:15 UTC",
           "eval_months": [str(m) for m in E.eval_months],
           "variant_count": {"stage1_grid": s1["n_variants_grid"], "stage1_nested_objectives": len(s1["nested"]),
                             "stage2_filters": s2["n_variants_stage2"], "stage2_nested_objectives": len(s2["nested"])},
           "series": {}}
    out["variant_count"]["total"] = sum(out["variant_count"].values())
    for name, tr in series.items():
        out["series"][name] = {"all": summarize(tr, E.u, E.eval_days, n_boot=2000),
                               "regime_1s5": regime_summary(tr, E),
                               "months": month_rows(tr).drop(columns=["sh_mo30", "sh_mores", "sh_pq"]),
                               "regimes": regime_table(tr)}
    b5 = series["baseline"][series["baseline"].regime == "1s/5%"]
    for name in ("nested", "nested_stage2", "frozen_rule_insample"):
        t5 = series[name][series[name].regime == "1s/5%"]
        out["series"][name]["diff_vs_baseline_1s5"] = {
            "net30_c": paired_diff(t5, b5, "net30"), "net_res_c": paired_diff(t5, b5, "net_res")}
        out["series"][name]["diff_vs_baseline_all"] = {
            "net30_c": paired_diff(series[name], series["baseline"], "net30"),
            "net_res_c": paired_diff(series[name], series["baseline"], "net_res")}
    out["nested_choices_stage1"] = s1["nested"]["pnl30_now_all"]["choice"]
    out["nested_choices_stage2"] = s2["nested"]["pnl30_now_all"]["choice"]
    out["nested_alt_objectives_stage1"] = {k: v["light"] for k, v in s1["nested"].items()}
    out["frozen_for_next_month"] = {"stage1_primary": s1["frozen_next_rule_primary"],
                                    "stage1_last3": s1["frozen_next_rule_last3"],
                                    "stage2_primary": s2["frozen_next_stage2_primary"],
                                    "stage2_last3": s2["frozen_next_stage2_last3"]}
    out["grid_1s5_distribution"] = s1["grid_1s5_distribution"]
    n5 = out["series"]["nested"]["regime_1s5"]
    out["recommended_rule"] = {
        "name": FROZEN.name,
        "text": ("Monthly, on data before m: wallets with >=15 weighted prints and >=5 weighted matches in the 0-3 s "
                 "post-onset bucket (month weight 0.5^((age-1)/2)); DerSimonian-Laird EB-shrunk mean 30 s markout minus "
                 "expected fee (rate known at start of m x wallet mean p(1-p)) > 0.5c. Take their 0-3 s trades, "
                 "<=$1k/trade, <=$3k/match, hold to resolution; no extra trade filters."),
        "honest_estimate_1s5": {"net30_c": n5["net30_c"], "net30_ci_c": n5["net30_ci_c"], "net_res_c": n5["net_res_c"],
                                "net_res_ci_c": n5["net_res_ci_c"]}}
    out["grid_marginals_median"] = {k: grid.groupby(k)[["net30_c", "net_res_c", "net30_1s5_c", "net_res_1s5_c",
                                                         "pnl", "pnl_1s5", "sharpe"]].median()
                                    for k in ("look", "score", "mm")}
    out["stage2_variants"] = s2["variants"]
    out["unified_model_last_beta_c"] = s2["unified_last_beta_c"]
    out["decay"] = dc
    (HERE / "results.json").write_text(json.dumps(jsonable(out), indent=1))
    figures(E, series, grid, s1)
    for name in series:
        a, r = out["series"][name]["all"], out["series"][name]["regime_1s5"]
        print(f"{name:22s} all: n={a['n_trades']} net30={a['net30_c']:.3f} net_res={a['net_res_c']:.3f} "
              f"{a['net_res_ci_c']} pnl=${a['pnl_usd']:,.0f} SR={a['sharpe_ann']:.2f} DD={a['max_dd_pct']:.1f}% | "
              f"1s5: n={r['n_trades']} net30={r['net30_c']:.3f} {r['net30_ci_c']} net_res={r['net_res_c']:.3f} "
              f"{r['net_res_ci_c']} pnl=${r['pnl_usd']:,.0f} SR={r['sharpe_ann']:.2f}")
        if "diff_vs_baseline_1s5" in out["series"][name]:
            print("   diff vs baseline 1s5:", out["series"][name]["diff_vs_baseline_1s5"],
                  " all:", out["series"][name]["diff_vs_baseline_all"])
    print("variants:", out["variant_count"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    sys.exit(main(ap.parse_args().report))
