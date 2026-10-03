"""Lens "exit": concise results.json, decomposition tables and figures from analyze_exit.py output.

    .venv/bin/python research/v2/exit/report_exit.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "v2_exit"
TAB = HERE / "tables"
FIG = HERE / "figures"
PRIMARY = "sh500/touch/fbB/norebate"        # pre-declared base fill model
RECOMMENDED = "sh500/improve1/fbB/norebate"  # touch fills at 1 tick worse: queue priority bought, never better than touch
REG = "1s/5%"
# reference palette (dataviz skill, light mode), fixed slot order
C = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100", "ink": "#0b0b0b",
     "ink2": "#52514e", "grid": "#e4e3df", "surface": "#fcfcfb"}


def style(ax):
    ax.set_facecolor(C["surface"])
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(C["ink2"])
    ax.tick_params(colors=C["ink2"], labelsize=9)
    ax.grid(axis="y", color=C["grid"], lw=0.8)
    ax.set_axisbelow(True)


def tr(name):
    return pd.read_parquet(CACHE / f"tr_{name}.parquet")


def decomposition(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for reg, g in [("all", t)] + list(t.groupby("regime")):
        for how, h in g.groupby("how"):
            rows.append({"regime": reg, "exit": how, "share_of_trades": len(h) / len(g), "n": len(h),
                         "per_share_c": h.pnl_ps.mean() * 100, "pnl_usd": h.pnl.sum(),
                         "hold_median_s": float(np.nanmedian(h.hold_s))})
    return pd.DataFrame(rows)


def main():
    r = json.loads((HERE / "results_full.json").read_text())
    fam, base = r["families"], r["baselines"]
    TAB.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)

    # ---- comparison table: every family, all IS (walk-forward) and the 1s/5% regime
    rows = []
    for k, v in list(base.items()) + list(fam.items()):
        a, b = v["all"], v["regime_1s5"]
        rows.append({"variant": k, "n": a["n_trades"], "ps_c": a["per_share_net_c"], "ci_lo": a["ci95_c"][0],
                     "ci_hi": a["ci95_c"][1], "ps_sw_c": a["per_share_net_sw_c"], "pnl_usd": a["total_pnl_usd"],
                     "sharpe": a["sharpe_daily_ann"], "max_dd_usd": a["max_dd_usd"], "months_pos": a["months_positive"],
                     "maker_fill": a.get("fill_rate_maker"), "hold_med_s": a.get("hold_median_s"),
                     "ps_1s5_c": b["per_share_net_c"], "ci_1s5_lo": b["ci95_c"][0], "ci_1s5_hi": b["ci95_c"][1],
                     "ps_1s5_sw_c": b["per_share_net_sw_c"], "pnl_1s5_usd": b["total_pnl_usd"],
                     "sharpe_1s5": b["sharpe_daily_ann"], "max_dd_1s5_usd": b["max_dd_usd"]})
    comp = pd.DataFrame(rows)
    comp.to_csv(TAB / "comparison_all_variants.csv", index=False)

    # ---- exit-type decomposition for primary + recommended + pessimistic
    for name in ("primary", "sh500_improve1_fbB_norebate", "sh500_pegthrough_fbB_norebate", "sh500_touch50_fbB_norebate"):
        decomposition(tr(name)).to_csv(TAB / f"decomp_{name}.csv", index=False)

    # ---- figure 1: walk-forward equity curves (sh500 sizing)
    series = [("Hold to resolution", "sh500_hold_to_resolution", C["blue"]),
              ("Maker exit, touch (base)", "primary", C["orange"]),
              ("Maker exit, 1 tick inside (recommended)", "sh500_improve1_fbB_norebate", C["aqua"]),
              ("Maker exit, back of queue (pessimistic)", "sh500_pegthrough_fbB_norebate", C["yellow"])]
    fig, ax = plt.subplots(figsize=(8.6, 4.4), dpi=150)
    fig.patch.set_facecolor(C["surface"])
    style(ax)
    first_1s5, last_day = None, None
    for label, name, col in series:
        t = tr(name)
        d = t.groupby("date").pnl.sum().sort_index().cumsum() / 1e3
        d.index = d.index.tz_localize(None)
        ax.plot(d.index, d.values, color=col, lw=2, label=label)
        ax.annotate(f"${d.values[-1]:,.0f}k", (d.index[-1], d.values[-1]), xytext=(4, 0), textcoords="offset points",
                    fontsize=8, color=C["ink"], va="center")
        if first_1s5 is None:
            first_1s5 = t.loc[t.regime == REG, "date"].min().tz_localize(None)
            last_day = t.date.max().tz_localize(None)
    ax.axvspan(first_1s5, last_day, color=C["grid"], alpha=0.5, lw=0)
    ax.text(first_1s5, ax.get_ylim()[1] * 0.97, "  1 s delay / 5% fee", fontsize=8, color=C["ink2"], va="top")
    ax.set_ylabel("cumulative net P&L, $k", color=C["ink2"], fontsize=9)
    ax.set_title("Fast-tier entries, four exits (walk-forward, in-sample, <=500 shares/trade)", fontsize=10,
                 color=C["ink"], loc="left")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "exit_equity_wf.png")
    plt.close(fig)

    # ---- figure 2: per-share net in the current regime with 95% CI, by exit / fill model
    order = [("Hold to resolution", "baselines", "sh500/hold_to_resolution"),
             ("30 s mid markout (not tradable)", "baselines", "sh500/mid30_markout_benchmark"),
             ("Taker out after H", "baselines", "sh500/taker_out_wf"),
             ("Maker exit: touch", "families", "sh500/touch/fbB/norebate"),
             ("Maker exit: 1 tick inside (recommended)", "families", "sh500/improve1/fbB/norebate"),
             ("Maker exit: touch, 50% fills dropped", "families", "sh500/touch50/fbB/norebate"),
             ("Maker exit: pegged, back of queue", "families", "sh500/pegthrough/fbB/norebate"),
             ("Maker exit: fixed level, trade-through", "families", "sh500/through/fbB/norebate")]
    fig, ax = plt.subplots(figsize=(8.6, 4.0), dpi=150)
    fig.patch.set_facecolor(C["surface"])
    style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=C["grid"], lw=0.8)
    for i, (label, grp, key) in enumerate(order):
        b = r[grp][key]["regime_1s5"]
        m, lo, hi = b["per_share_net_c"], b["ci95_c"][0], b["ci95_c"][1]
        col = C["blue"] if grp == "baselines" else C["orange"]
        ax.plot([lo, hi], [i, i], color=col, lw=2, solid_capstyle="round")
        ax.plot([m], [i], "o", color=col, ms=7, mec=C["surface"], mew=1.5)
        ax.annotate(f"{m:+.2f}c  [{lo:+.2f}, {hi:+.2f}]", (max(hi, m), i), xytext=(6, 0), textcoords="offset points",
                    fontsize=8, color=C["ink"], va="center")
    ax.axvline(0, color=C["ink2"], lw=1)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([o[0] for o in order], fontsize=8.5, color=C["ink"])
    ax.invert_yaxis()
    ax.set_xlabel("net P&L per share, cents (1 s / 5% regime, Jul-Aug 2026, match-clustered 95% CI)",
                  fontsize=8.5, color=C["ink2"])
    ax.set_title("The exit decides the sign; the queue assumption decides the size", fontsize=10, color=C["ink"], loc="left")
    xl = ax.get_xlim()
    ax.set_xlim(xl[0], xl[1] + 0.9)
    fig.tight_layout()
    fig.savefig(FIG / "exit_fillmodel_1s5.png")
    plt.close(fig)

    # ---- concise results.json
    rec, pri = fam[RECOMMENDED], fam[PRIMARY]
    hold = base["sh500/hold_to_resolution"]

    def wf_block(f):
        a, b = f["all"], f["regime_1s5"]
        return {"n_trades": a["n_trades"], "per_share_net_c": a["per_share_net_c"], "ci_lo_c": a["ci95_c"][0],
                "ci_hi_c": a["ci95_c"][1], "per_share_net_sw_c": a["per_share_net_sw_c"],
                "total_pnl_usd": a["total_pnl_usd"], "sharpe": a["sharpe_daily_ann"], "max_dd_usd": a["max_dd_usd"],
                "max_dd_pct": a["max_dd_pct_of_capital"], "capital_usd": a["capital_3x_peak"],
                "months_positive": a["months_positive"], "months_total": a["months_total"],
                "maker_fill_rate": a.get("fill_rate_maker"), "hold_median_s": a.get("hold_median_s"),
                "regime_1s5pct_per_share_c": b["per_share_net_c"], "regime_1s5pct_ci_c": b["ci95_c"],
                "regime_1s5pct_per_share_sw_c": b["per_share_net_sw_c"], "regime_1s5pct_pnl_usd": b["total_pnl_usd"],
                "regime_1s5pct_sharpe": b["sharpe_daily_ann"], "regime_1s5pct_max_dd_usd": b["max_dd_usd"],
                "regime_1s5pct_months_positive": b["months_positive"], "regime_1s5pct_months_total": b["months_total"],
                "choices": f.get("choices")}

    plac = json.loads((HERE / "placebo.json").read_text()) if (HERE / "placebo.json").exists() else None
    diag = pd.read_csv(TAB / "diag_spread_at_fill.csv").to_dict("records") if (TAB / "diag_spread_at_fill.csv").exists() else None
    out = {
        "lens": "exit",
        "n_variants": r["n_variants"] + (plac["n_variants"] if plac else 0),
        "n_variants_breakdown": {"analyze_exit (baselines + taker-out + maker families, unique cells)": r["n_variants"],
                                 "placebo_exit": plac["n_variants"] if plac else 0},
        "placebo_nonfast_0_3s": plac,
        "diag_spread_at_touch_fills": diag,
        "recommended": {"key": RECOMMENDED, **wf_block(rec)},
        "primary_predeclared": {"key": PRIMARY, **wf_block(pri)},
        "baseline_hold_to_resolution": {"key": "sh500/hold_to_resolution", **wf_block(hold)},
        "baseline_mid30": {"key": "sh500/mid30_markout_benchmark", **wf_block(base["sh500/mid30_markout_benchmark"])},
        "baseline_taker_out": {"key": "sh500/taker_out_wf", **wf_block(base["sh500/taker_out_wf"])},
        "sensitivity_1s5_per_share_c": {k: {"ps_c": v["regime_1s5"]["per_share_net_c"], "ci": v["regime_1s5"]["ci95_c"],
                                             "pnl_usd": v["regime_1s5"]["total_pnl_usd"]} for k, v in fam.items()},
        "files": {"tables": sorted(str(p.relative_to(ROOT)) for p in TAB.glob("*.csv")),
                  "figures": sorted(str(p.relative_to(ROOT)) for p in FIG.glob("*.png"))},
    }
    (HERE / "results.json").write_text(json.dumps(out, indent=1, default=float))
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        print(comp[["variant", "n", "ps_c", "ci_lo", "ci_hi", "pnl_usd", "sharpe", "max_dd_usd", "months_pos",
                    "maker_fill", "ps_1s5_c", "ci_1s5_lo", "ci_1s5_hi", "pnl_1s5_usd", "sharpe_1s5"]].round(2).to_string())


if __name__ == "__main__":
    main()
