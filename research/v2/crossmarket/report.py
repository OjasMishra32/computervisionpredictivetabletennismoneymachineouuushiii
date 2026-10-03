"""Figures + results.json + markdown tables from analysis.json.
Run: .venv/bin/python research/v2/crossmarket/report.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUT  # noqa: E402

A = json.loads((OUT / "analysis.json").read_text())


def md(df: pd.DataFrame, fmt: str = "{:.2f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (list, tuple)):
                cells.append("[" + ", ".join(fmt.format(x) for x in v) + "]")
            elif isinstance(v, float):
                cells.append(fmt.format(v))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def figs():
    es = pd.DataFrame(A["event_study"]["rows"])
    es = es[es.side != "all"]
    order = [b for b in ["1-3s", "3-6s", "6-10s", "10-20s", "20-60s", "60-300s", ">300s"] if b in set(es.bucket)]
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    for side, col, off in (("implied", "#1f6f8b", -0.15), ("contrary", "#c0504d", 0.15)):
        g = es[es.side == side].set_index("bucket").reindex(order)
        x = np.arange(len(order)) + off
        lo = g.net_res_c - g.ci.map(lambda c: c[0])
        hi = g.ci.map(lambda c: c[1]) - g.net_res_c
        ax[0].errorbar(x, g.net_res_c, yerr=[lo, hi], fmt="o", color=col, label=f"{side}-direction takers", capsize=3)
    ax[0].axhline(0, color="k", lw=0.6)
    ax[0].set_xticks(range(len(order)))
    ax[0].set_xticklabels(order)
    ax[0].set_xlabel("side print time after moneyline jump detection")
    ax[0].set_ylabel("taker net markout to resolution (c/share)")
    ax[0].set_title("Side takers after a moneyline jump (IS)")
    ax[0].legend(fontsize=8)
    cu = pd.DataFrame(A["event_study"]["catchup"]).set_index("bucket").reindex(order).dropna(how="all")
    ax[1].bar(range(len(cu)), cu["median"], color="#1f6f8b")
    ax[1].axhline(1, color="k", lw=0.6, ls="--")
    for i, (n, m) in enumerate(zip(cu["size"], cu["median"])):
        ax[1].text(i, m + 0.03, f"n={int(n)}", ha="center", fontsize=7)
    ax[1].set_xticks(range(len(cu)))
    ax[1].set_xticklabels(cu.index)
    ax[1].set_ylabel("median share of implied move in side price")
    ax[1].set_title("Catch-up of side markets to the moneyline")
    fig.tight_layout()
    fig.savefig(OUT / "fig_event_study.png", dpi=150)
    plt.close(fig)
    mon = pd.DataFrame(A["backtest"].get("wf_res_monthly", []))
    if len(mon):
        fig, ax = plt.subplots(figsize=(7, 3.2))
        ax.bar(mon.month, mon.pnl_usd, color=np.where(mon.pnl_usd >= 0, "#1f6f8b", "#c0504d"))
        ax.axhline(0, color="k", lw=0.6)
        ax.set_ylabel("net $ P&L (hold to resolution)")
        ax.set_title("Crossmarket stale-quote taker, walk-forward by month (IS)")
        fig.tight_layout()
        fig.savefig(OUT / "fig_wf_monthly.png", dpi=150)
        plt.close(fig)


def fig_lean():
    lm = A["lean_maker"]
    mon = pd.DataFrame(lm.get("wf_monthly", []))
    tk = pd.DataFrame(A["backtest"].get("wf_res_monthly", []))
    d = pd.DataFrame(lm["diagnostics"])
    d = d[d.regime == "all"]
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.6))
    labels = ["unconditional\nmaker", "anti-lean\nplacebo", "lean with\nmoneyline"]
    lo = d.net_c - d.ci.map(lambda c: c[0])
    hi = d.ci.map(lambda c: c[1]) - d.net_c
    ax[0].bar(range(3), d.net_c, yerr=[lo, hi], capsize=4, color=["#999999", "#c0504d", "#1f6f8b"])
    ax[0].axhline(0, color="k", lw=0.6)
    ax[0].set_xticks(range(3))
    ax[0].set_xticklabels(labels)
    ax[0].set_ylabel("maker net to resolution (c/share)")
    ax[0].set_title("Side-market maker fills, Feb-Aug 2026 (IS)")
    if len(mon):
        x = np.arange(len(mon))
        ax[1].bar(x - 0.2, mon.pnl_usd, 0.4, color="#1f6f8b", label="lean maker (walk-forward)")
        if len(tk):
            tkm = tk.set_index("month").reindex(mon.month)
            ax[1].bar(x + 0.2, tkm.pnl_usd.fillna(0), 0.4, color="#e0a030", label="stale-quote taker (walk-forward)")
        ax[1].set_xticks(x)
        ax[1].set_xticklabels(mon.month, rotation=0, fontsize=8)
        ax[1].axhline(0, color="k", lw=0.6)
        ax[1].set_ylabel("net $ P&L per month")
        ax[1].legend(fontsize=8)
        ax[1].set_title("Dollar P&L is small: capacity is tiny")
    fig.tight_layout()
    fig.savefig(OUT / "fig_lean_maker.png", dpi=150)
    plt.close(fig)


def tables():
    out = []
    cap = pd.DataFrame(A["capacity"]["by_type"])
    out.append("### Capacity by side-market type (IS)\n" + md(cap[["smt", "markets", "lifetime_vol_usd", "inplay_prints",
                                                                    "inplay_usd", "median_print_usd", "p90_print_usd",
                                                                    "matches", "inplay_share_of_lifetime"]], "{:,.2f}"))
    cm = pd.DataFrame(A["capacity"]["by_month"])
    out.append("### Capacity by month\n" + md(cm, "{:,.3f}"))
    bt = pd.DataFrame(A["beta_walkforward"])
    out.append("### Walk-forward b\n" + md(bt, "{:.3f}"))
    out.append("### Beta model R^2 by month (pooled, vs zero forecast)\n" + md(pd.DataFrame(A["beta_model_r2"]), "{:.3f}"))
    out.append("beta model chosen walk-forward: " + json.dumps(A["beta_model_choice"]))
    for key in ("event_study", "event_study_2c"):
        es = pd.DataFrame(A[key]["rows"])
        out.append(f"### {key}\n" + md(es.drop(columns=[c for c in ("mean_abs_impl_c",) if c in es]), "{:.2f}"))
        out.append(f"#### {key} by regime (delay+1..60 s)\n" + md(pd.DataFrame(A[key]["by_regime"])))
        out.append(f"#### {key} by type (delay+1..60 s)\n" + md(pd.DataFrame(A[key]["by_type"])))
        out.append(f"#### {key} who takes early (delay+1..10 s)\n" + md(pd.DataFrame(A[key]["who_takes_early"])))
    out.append("### catch-up\n" + md(pd.DataFrame(A["event_study"]["catchup"])))
    b = A["backtest"]
    out.append("### backtest walk-forward choices\n" + md(pd.DataFrame(b["choices"])))
    for ex in ("res", "taker60", "passive"):
        st = b.get(f"wf_{ex}", {})
        out.append(f"### wf exit={ex}\n" + json.dumps({k: st.get(k) for k in (
            "n_trades", "n_matches", "mean_pnl_per_share_c", "ci95_pnl_per_share_c", "share_weighted_net_c",
            "hit_rate", "mean_fee_c", "total_pnl_usd", "sharpe_ann", "max_dd", "capital", "months_positive",
            "months_total")}, default=float))
        if f"wf_{ex}_monthly" in b:
            out.append(md(pd.DataFrame(b[f"wf_{ex}_monthly"])))
            out.append(md(pd.DataFrame(b[f"wf_{ex}_by_regime"])))
            out.append(md(pd.DataFrame(b[f"wf_{ex}_by_type"])))
    out.append("### type filter variant\n" + json.dumps({k: b["wf_typefilter_res"].get(k) for k in (
        "n_trades", "mean_pnl_per_share_c", "ci95_pnl_per_share_c", "total_pnl_usd", "sharpe_ann")}, default=float))
    if "wf_typefilter_res_monthly" in b:
        out.append(md(pd.DataFrame(b["wf_typefilter_res_monthly"])))
    out.append("### fixed k=1, min_impl=0.02, 1s/5% only\n" + json.dumps({k: b["fixed_k1_mi0.02_1s5"].get(k) for k in (
        "n_trades", "mean_pnl_per_share_c", "ci95_pnl_per_share_c", "total_pnl_usd", "sharpe_ann")}, default=float))
    g = pd.DataFrame(b["grid_all_cells"])
    out.append("### all grid cells (eval months, reported not chosen)\n" + md(g))
    mk = A["maker"]
    out.append("### maker variant cells\n" + md(pd.DataFrame(mk["cells"])))
    out.append("maker wf: " + json.dumps({k: mk["wf"].get(k) for k in (
        "n_trades", "mean_pnl_per_share_c", "ci95_pnl_per_share_c", "total_pnl_usd", "sharpe_ann")}, default=float))
    if "wf_monthly" in mk:
        out.append(md(pd.DataFrame(mk["wf_monthly"])))
        out.append(md(pd.DataFrame(mk["wf_by_regime"])))
    lm = A["lean_maker"]
    out.append("### lean maker cells (eval months)\n" + md(pd.DataFrame(lm["cells"])))
    out.append("### lean maker walk-forward choices\n" + md(pd.DataFrame(lm["choices"])))
    out.append("lean maker wf: " + json.dumps({k: lm["wf"].get(k) for k in (
        "n_trades", "n_matches", "mean_pnl_per_share_c", "ci95_pnl_per_share_c", "share_weighted_net_c",
        "hit_rate", "total_pnl_usd", "sharpe_ann", "max_dd", "capital", "months_positive", "months_total",
        "worst_month_usd", "worst_day_pct")}, default=float))
    if "wf_monthly" in lm:
        out.append(md(pd.DataFrame(lm["wf_monthly"])))
        out.append(md(pd.DataFrame(lm["wf_by_regime"])))
        out.append(md(pd.DataFrame(lm["wf_by_type"])))
    out.append("### lean maker diagnostics\n" + md(pd.DataFrame(lm["diagnostics"])))
    out.append(f"variants counted: {A['n_variants']}")
    (OUT / "tables.md").write_text("\n\n".join(out))
    print("\n\n".join(out))


def per30() -> dict:
    """Current-regime (1 s / 5%) notional and P&L per 30 days for the walk-forward books."""
    from common import CACHE
    out = {}
    for name, f in (("lean_maker", "wf_lean_maker.parquet"), ("taker", "wf_trades_res.parquet")):
        x = pd.read_parquet(CACHE / f)
        x = x[x.regime == "1s/5%"]
        days = (x.date.max() - x.date.min()).days + 1
        out[f"{name}_1s5_days"] = int(days)
        out[f"{name}_1s5_notional_usd_per_30d"] = float(x.usd_in.sum() / days * 30)
        out[f"{name}_1s5_pnl_usd_per_30d"] = float(x.pnl.sum() / days * 30)
    return out


def write_results():
    b, lm = A["backtest"], A["lean_maker"]
    tk, wl = b["wf_res"], lm["wf"]
    reg_l = {r["regime"]: r for r in lm.get("wf_by_regime", [])}
    reg_t = {r["regime"]: r for r in b.get("wf_res_by_regime", [])}
    cap = pd.DataFrame(A["capacity"]["by_month"])
    diag = pd.DataFrame(lm["diagnostics"])
    lean15 = diag[(diag.book.str.startswith("lean")) & (diag.regime == "1s/5%")].iloc[0]
    mon_l = pd.DataFrame(lm.get("wf_monthly", []))
    res = {
        "lens": "crossmarket",
        "is_only": True,
        "n_variants": A["n_variants"],
        "variants": A["variants"],
        "stated_lens_taker": {
            "rule": "after a moneyline jump (detect_ts), send IOC orders on each side market of the match from "
                    "detect+1 s for 30 s; fill at the first print on our side at >= send+delay whose move since the "
                    "side's last print is < k * model-implied move and |implied| >= min_impl; k, min_impl walk-forward "
                    "(max past $ P&L); size min($1k, 50% of print), <= $3k/match; hold to resolution",
            "wf": {k: tk.get(k) for k in ("n_trades", "n_matches", "mean_pnl_per_share_c", "ci95_pnl_per_share_c",
                                          "total_pnl_usd", "sharpe_ann", "max_dd", "months_positive", "months_total")},
            "wf_taker60": {k: b["wf_taker60"].get(k) for k in ("mean_pnl_per_share_c", "ci95_pnl_per_share_c", "total_pnl_usd")},
            "wf_passive": {k: b["wf_passive"].get(k) for k in ("mean_pnl_per_share_c", "ci95_pnl_per_share_c", "total_pnl_usd")},
            "by_regime": reg_t, "monthly": b.get("wf_res_monthly"), "choices": b["choices"],
        },
        "lean_maker": {
            "rule": "rest only on the side of each side market that gains from the moneyline-implied move since the "
                    "side's last print (|implied| >= min_impl, info strictly before print time - delay); filled by "
                    "takers trading against it at the print price, 20% of the print, <= $250/fill, <= $2k/match; "
                    "hold to resolution; 0 fee + 15% rebate; window and min_impl walk-forward (max past $ P&L)",
            "wf": {k: wl.get(k) for k in ("n_trades", "n_matches", "mean_pnl_per_share_c", "ci95_pnl_per_share_c",
                                          "share_weighted_net_c", "hit_rate", "total_pnl_usd", "sharpe_ann", "max_dd",
                                          "capital", "months_positive", "months_total", "worst_month_usd")},
            "months_positive_per_share": int((mon_l.net_c > 0).sum()) if len(mon_l) else None,
            "by_regime": reg_l, "monthly": lm.get("wf_monthly"), "choices": lm["choices"],
            "diagnostics": lm["diagnostics"],
            **per30(),
            "capacity_1s5_contrary_flow_usd_per_month_upper_bound": float(lean15.flow_usd_per_month),
        },
        "event_study": A["event_study"],
        "capacity_by_type": A["capacity"]["by_type"],
        "capacity_by_month": cap.to_dict("records"),
        "beta_walkforward": A["beta_walkforward"],
        "beta_model_choice": A["beta_model_choice"],
    }
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    figs()
    fig_lean()
    tables()
    write_results()
