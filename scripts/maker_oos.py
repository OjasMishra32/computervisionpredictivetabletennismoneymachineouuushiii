"""maker v1 (leaning maker on tennis side markets): blind OOS test in one command.

Pre-registration: research/v2/maker/PREREG.md (A). Deviations / pre-run decisions: research/v2/maker/DEVIATIONS.md.
Paper only: public keyless Polymarket endpoints (gamma-api, data-api), no order code, no keys.

Steps:
  build   research/v2/maker/oos_build.py: OOS side-market catalogue, tapes, per-print tables (counts only)
  check   build-code parity on 400 IS events, then the PREREG 2.3 IS parity (oos_test.py parity)
  run     the single OOS run (oos_test.py run): appends the peeks line first, then writes results
  figure  results/maker/equity_is_oos.png (cumulative P&L, IS walk-forward vs blind OOS)
  reproduce  recompute the committed OOS numbers from the cached data and compare (logs a peeks line)
  all     build, check, run, figure

Usage (repo root):  .venv/bin/python scripts/maker_oos.py all
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MAKER = ROOT / "research" / "v2" / "maker"
FIG = ROOT / "results" / "maker" / "equity_is_oos.png"
IS_WF = ROOT / "data" / "v2_crossmarket" / "wf_lean_maker.parquet"   # IS walk-forward book (analyze.lean_maker)
OOS_BOOK = MAKER / "oos" / "book_v1.csv"
OOS_RES = MAKER / "oos" / "results.json"
OOS_CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")

# reference palette (dataviz skill), light surface; two series = slots 1 and 2
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
C_IS, C_OOS = "#2a78d6", "#eb6834"


def sh(*args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def figure(out: Path = FIG):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    wf = pd.read_parquet(IS_WF).sort_values("ts", kind="stable")
    oos = pd.read_csv(OOS_BOOK).sort_values("ts", kind="stable") if OOS_BOOK.exists() else None
    res = json.loads(OOS_RES.read_text()) if OOS_RES.exists() else None
    t_is = pd.to_datetime(wf.ts, unit="s", utc=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                         "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK})
    fig, axes = plt.subplots(2, 1, figsize=(11, 7.6), sharex=True, facecolor=SURFACE,
                             gridspec_kw={"height_ratios": [1, 1], "hspace": 0.12})
    panels = (("pnl", "Cumulative P&L ($), frozen sizing", lambda v: f"${v:,.0f}"),
              ("pnl_ps", "Cumulative P&L at 1 share per fill ($)\n(the weighting of the primary statistic)", lambda v: f"${v:,.1f}"))
    for ax, (col, ylab, fmt) in zip(axes, panels):
        ax.set_facecolor(SURFACE)
        y_is = wf[col].cumsum().to_numpy()
        ax.plot(t_is, y_is, color=C_IS, lw=1.6, drawstyle="steps-post", label="In-sample walk-forward (Feb 1 - Aug 25, 2026)")
        ax.annotate(f"IS {fmt(y_is[-1])}", (t_is.iloc[-1], y_is[-1]), xytext=(-6, 8), textcoords="offset points",
                    ha="right", color=INK, fontsize=9)
        if oos is not None and len(oos):
            t_o = pd.to_datetime(oos.ts, unit="s", utc=True)
            y_o = y_is[-1] + oos[col].cumsum().to_numpy()
            ax.plot(pd.Index([t_is.iloc[-1]]).append(pd.DatetimeIndex(t_o)), np.r_[y_is[-1], y_o], color=C_OOS, lw=1.6,
                    drawstyle="steps-post", label="Blind OOS, frozen maker v1 (Aug 25 - Oct 3, 2026)")
            ax.annotate(f"OOS {'+' if y_o[-1] - y_is[-1] >= 0 else '-'}{fmt(abs(y_o[-1] - y_is[-1]))}",
                        (t_o.iloc[-1], y_o[-1]), xytext=(6, 0), textcoords="offset points", ha="left",
                        va="center", color=INK, fontsize=9)
        ax.axvline(OOS_CUT, color=INK2, lw=0.9, ls=(0, (4, 3)))
        ax.axhline(0, color=INK2, lw=0.6)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_ylabel(ylab, fontsize=9.5)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes[0].text(OOS_CUT, axes[0].get_ylim()[1], "  blind OOS starts 2026-08-25 14:15 UTC", color=INK2, fontsize=8.5,
                 va="top", ha="left")
    axes[0].legend(loc="upper left", frameon=False, fontsize=9)
    title = "Maker v1 (leaning maker, Polymarket tennis side markets): in-sample walk-forward vs blind out-of-sample"
    sub = "Paper backtest on real public trade tapes; held to resolution; maker fee 0, 15% rebate."
    if res is not None:
        p = res["primary"]
        sub += (f"  OOS primary: {p['value_c']:+.2f}c/share [{p['ci95_c'][0]:+.2f}, {p['ci95_c'][1]:+.2f}], "
                f"{p['n_fills']:,} fills / {p['n_matches']:,} matches -> {p['verdict']}"
                f"{' (underpowered)' if p['underpowered'] else ''}.")
    fig.suptitle(title, x=0.06, ha="left", fontsize=12, color=INK, y=0.985)
    fig.text(0.06, 0.935, sub, ha="left", fontsize=9, color=INK2)
    fig.text(0.06, 0.015, "IS = analyze.lean_maker walk-forward book (cells chosen monthly; always/4c from May). "
             "OOS = frozen cell always/4c with frozen b_T, lambda 1.0; OOS moneyline tapes used only as the signal input.",
             ha="left", fontsize=7.5, color=INK2)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("build", "check", "run", "figure", "reproduce", "all"))
    a = ap.parse_args()
    if a.step in ("build", "all"):
        sh("research/v2/maker/oos_build.py")
    if a.step in ("check", "all"):
        sh("research/v2/maker/oos_build.py", "--check-is", "400")
        sh("research/v2/maker/oos_test.py", "parity")
    if a.step in ("run", "all"):
        sh("research/v2/maker/oos_test.py", "run")
    if a.step in ("figure", "all"):
        figure()
    if a.step == "reproduce":
        sh("research/v2/maker/oos_test.py", "reproduce")


if __name__ == "__main__":
    main()
