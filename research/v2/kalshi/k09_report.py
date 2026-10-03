"""Step 7: figures + results.json for the Kalshi lens (reads k04/k06 outputs only).

Run: .venv/bin/python research/v2/kalshi/k07_report.py
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
from k_common import CACHE, OUT, ROOT  # noqa: E402
from src.backtest import stats  # noqa: E402

PRIMARY = "pm_gap_curfee:ps_hedge"     # pre-declared headline TAKER variant (declared before the full run)
BEST_TAKER = "pm_gaprob_curfee:ps_hedge"  # post-hoc family (sweep-resistant Kalshi fair), disclosed
MAKER = "maker_curfee:ps_pm60"          # passive family, print-price fill model (optimistic), post-hoc, disclosed
MAKER_Q = "maker_curfee:qb_pm60"        # passive family, quote-price fill model (consistent), post-hoc, disclosed
KEEP = ["n_trades", "n_matches", "mean_pnl_per_share_c", "ci95_pnl_per_share_c", "total_pnl_usd", "sharpe_ann",
        "max_dd", "months_positive", "months_total", "mean_fee_c", "hit_rate"]
LENS = ROOT / "research/v2/kalshi"


def fig_paths():
    a = pd.read_csv(OUT / "event_avg_path.csv")
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.plot(a.tau, a.k, label="Kalshi", lw=2)
    ax.plot(a.tau, a.pm, label="Polymarket", lw=2)
    ax.axhline(0.5, color="grey", lw=0.6, ls=":")
    ax.axvline(0, color="grey", lw=0.6)
    ax.set_xlabel("seconds from event anchor (first venue's jump detection)")
    ax.set_ylabel("fraction of eventual move")
    ax.set_title("Average repricing path, events where both venues moved >= 2c")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "fig_event_path.png", dpi=150)
    plt.close(fig)


def fig_lead():
    ev = pd.read_parquet(OUT / "leadlag_events.parquet")
    b = ev[(ev.move_pm >= 0.02) & (ev.move_k >= 0.02) & ev.t50_pm.notna() & ev.t50_k.notna()].copy()
    b["lead"] = b.t50_pm - b.t50_k
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    bins = np.arange(-30.5, 31.5, 1)
    for dl, g in b.groupby("delay"):
        ax.hist(g.lead.clip(-30, 30), bins=bins, density=True, histtype="step", lw=1.6,
                label=f"PM delay {dl}s (n={len(g):,}, median {g.lead.median():+.0f}s)")
    ax.axvline(0, color="grey", lw=0.6)
    ax.set_xlabel("lead = t50(Polymarket) - t50(Kalshi), seconds (>0: Kalshi first)")
    ax.set_ylabel("density")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "fig_lead_hist.png", dpi=150)
    plt.close(fig)


def fig_ccf():
    c = pd.read_csv(OUT / "ccf_by_delay.csv")
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    ax.plot(c.lag, c.delay3, label="PM delay 3 s", marker=".")
    ax.plot(c.lag, c.delay1, label="PM delay 1 s", marker=".")
    ax.axvline(0, color="grey", lw=0.6)
    ax.set_xlabel("lag L (corr of r_PM(t), r_Kalshi(t+L)); L<0 = Kalshi moves first")
    ax.set_ylabel("cross-correlation, 1 s returns")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "fig_ccf.png", dpi=150)
    plt.close(fig)


def fig_wf(tr: pd.DataFrame, name: str, fname: str = "fig_wf_primary.png"):
    g = tr.groupby("month").agg(ps=("pnl_ps", "mean"), pnl=("pnl", "sum"), n=("pnl_ps", "size"))
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))
    ax[0].bar(g.index, 100 * g.ps, color=["C2" if v > 0 else "C3" for v in g.ps])
    ax[0].set_ylabel("net c/share (walk-forward)")
    ax[1].bar(g.index, g.pnl, color=["C2" if v > 0 else "C3" for v in g.pnl])
    ax[1].set_ylabel("net $ P&L")
    for a in ax:
        a.tick_params(axis="x", rotation=60, labelsize=7)
        a.axhline(0, color="k", lw=0.5)
    fig.suptitle(name, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / fname, dpi=150)
    plt.close(fig)


def variant(name: str, summ: dict, fig: str | None = None) -> dict:
    tag, col = name.split(":")
    tr = pd.read_parquet(OUT / f"trades_wf_{tag}_{col}.parquet")
    if "date" not in tr:
        tr["date"] = pd.to_datetime(tr.ts, unit="s", utc=True).dt.floor("D")
    if "fee" not in tr:
        tr["fee"] = 0.0
    tr["exit"] = col
    if fig:
        fig_wf(tr, name, fig)
    cur = tr[(tr.fee_rate == 0.05) & (tr.delay == 1)]
    st_cur = stats(cur[["cond", "pnl_ps", "pnl", "fee", "usd_in", "exit", "date"]], n_boot=1000) if len(cur) else {}
    v = summ[name]
    return {
        "wf": {k: v.get(k) for k in KEEP},
        "wf_1s5pct": {k: st_cur.get(k) for k in KEEP if k in st_cur},
        "by_regime": {k: {kk: x.get(kk) for kk in ["n_trades", "mean_pnl_per_share_c", "ci95_pnl_per_share_c",
                                                   "total_pnl_usd"]} for k, x in v.get("by_regime", {}).items()},
        "picks": v.get("picks"),
        "usd_deployed_per_month": tr.groupby("month").usd_in.sum().to_dict(),
        "pnl_usd_per_month": tr.groupby("month").pnl.sum().to_dict(),
        "share_wtd_c_per_month": (100 * tr.groupby("month").pnl.sum() / tr.groupby("month").shares.sum()).to_dict(),
    }


def main():
    ll = json.loads((OUT / "leadlag_summary.json").read_text())
    bt = json.loads((OUT / "backtest_summary.json").read_text())
    mk = json.loads((OUT / "maker_summary.json").read_text())
    fig_paths(); fig_lead(); fig_ccf()
    tag = PRIMARY.split(":")[0]
    grid = pd.read_csv(OUT / f"grid_IS_{tag}.csv")
    base = grid[(grid.G == 0) & (grid.E < -1)].iloc[0]
    tbl = lambda src: {k: {kk: v.get(kk) for kk in KEEP} | {"by_regime_1s5pct": v.get("by_regime", {}).get("0.05/1s")}
                       for k, v in src.items() if isinstance(v, dict) and k != "latency_sensitivity"}
    res = {
        "lens": "kalshi",
        "matched_matches": int(pd.read_parquet(CACHE / "matched.parquet").shape[0]),
        "matches_with_both_tapes": ll["matches_used"],
        "leadlag": {k: ll[k] for k in ["ccf_peak_lag", "ccf_peak", "ccf_lag0", "events_both_moved", "lead_all",
                                       "lead_by_delay", "lead_by_regime", "lead_by_month", "t50_pm_median",
                                       "t50_k_median", "pm_usd_inplay", "kalshi_usd_inplay", "pm_prints",
                                       "kalshi_prints"]},
        "fasttier_vs_kalshi": ll.get("fasttier"),
        "primary_taker": {"name": PRIMARY, **variant(PRIMARY, bt, "fig_wf_primary.png")},
        "best_taker": {"name": BEST_TAKER, **variant(BEST_TAKER, bt, "fig_wf_best_taker.png")},
        "maker_print_model": {"name": MAKER, **variant(MAKER, mk, "fig_wf_maker.png")},
        "maker_quote_model": {"name": MAKER_Q, **variant(MAKER_Q, mk)},
        "baseline_primary_all_signals_no_filter_c": {c: float(base[c]) for c in base.index if c.endswith("_c")},
        "all_taker_variants_wf": tbl(bt),
        "all_maker_variants_wf": tbl(mk),
        "latency_sensitivity_taker": bt.get("latency_sensitivity"),
        "latency_sensitivity_maker": mk.get("latency_sensitivity"),
        "n_variants_wf_taker": bt.get("n_variants_wf"),
        "n_variants_wf_maker": mk.get("n_variants_wf"),
        "n_signal_families": 4,
        "n_variants_total": int(bt.get("n_variants_wf", 0)) + int(mk.get("n_variants_wf", 0)),
    }
    (LENS / "results.json").write_text(json.dumps(res, indent=1, default=float))
    for k in ["primary_taker", "best_taker", "maker_print_model", "maker_quote_model"]:
        print(k, json.dumps({kk: res[k][kk] for kk in ["wf", "wf_1s5pct"]}, default=float))
    print("n_variants_total", res["n_variants_total"])


if __name__ == "__main__":
    main()
