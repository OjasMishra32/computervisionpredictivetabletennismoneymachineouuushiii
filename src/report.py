"""Static figures for the quant note (light mode, print-friendly)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FIG = Path("results/figures")
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
    "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False, "lines.linewidth": 2,
})


def _save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIG / f"{name}.png", dpi=200)
    plt.close(fig)


def tiers_figure(tab: pd.DataFrame):
    """tab: index = bucket label, columns = 'fast', 'others' (30 s markout, cents/share, net of fee)."""
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    x = np.arange(len(tab))
    w = 0.38
    ax.bar(x - w / 2 - 0.01, tab["fast"], w, color=BLUE, label="Fast-tier wallets")
    ax.bar(x + w / 2 + 0.01, tab["others"], w, color=ORANGE, label="All other takers")
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(x, tab.index)
    ax.set_xlabel("Seconds since the score event (jump onset)")
    ax.set_ylabel("30 s markout, ¢/share, net of fee")
    ax.set_title("Who gets paid after a point")
    ax.legend(loc="upper right")
    _save(fig, "fig1_tiers")


def calibration_figure(cal: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(3.4, 3.2))
    ax.plot([0.5, 1], [0.5, 1], color=INK2, lw=0.8, ls="--")
    ax.errorbar(cal.mean_price, cal.win_rate, yerr=[cal.win_rate - cal.lo, cal.hi - cal.win_rate],
                fmt="o", ms=4, color=BLUE, ecolor=BLUE, elinewidth=1, capsize=0)
    ax.set_xlabel("In-play price of the favourite")
    ax.set_ylabel("Realised win rate")
    ax.set_title("Live prices are calibrated")
    _save(fig, "fig2_calibration")


def walkforward_figure(wf: pd.DataFrame, shadow: pd.DataFrame, oos_start=None):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 2.9))
    x = np.arange(len(wf))
    a1.bar(x, wf.net30_c, color=BLUE, width=0.7)
    a1.axhline(0, color=INK2, lw=0.8)
    a1.set_xticks(x, wf.month, rotation=60, fontsize=7)
    a1.set_ylabel("¢/share, net of fee")
    a1.set_title("Fast tier, picked on past data only")
    if len(shadow):
        d = shadow.groupby(pd.to_datetime(shadow.ts, unit="s").dt.floor("D")).pnl.sum().cumsum()
        a2.plot(d.index, d.values / 1e3, color=BLUE)
        if oos_start is not None:
            a2.axvline(oos_start, color=INK2, lw=0.8, ls="--")
            a2.text(oos_start, a2.get_ylim()[1] * 0.95, " OOS", color=INK2, fontsize=8, va="top")
        a2.set_ylabel("Cumulative P&L, $k")
        a2.set_title("Shadow book at fast-tier speed")
        a2.tick_params(axis="x", labelrotation=45, labelsize=7)
    _save(fig, "fig3_walkforward")


def tracking_figure(tennis: pd.DataFrame, tt: pd.DataFrame | None = None):
    fig, ax = plt.subplots(figsize=(3.6, 3.0))
    t = tennis.dropna(subset=["pred_err_sd_cm"])
    ax.plot(t.lead_ms, 1.645 * t.pred_err_sd_cm, color=BLUE, marker="o", ms=4, label="Tennis (physics, 340 fps)")
    if tt is not None and len(tt):
        ax.plot(tt.lead_ms, tt.margin_cm, color=ORANGE, marker="o", ms=4, label="Table tennis (video, 120 fps)")
    ax.set_xlabel("Lead before the bounce, ms")
    ax.set_ylabel("Callable margin at 95%, cm out")
    ax.set_title("How early an out can be called")
    ax.legend(loc="upper left")
    _save(fig, "fig4_tracking")


def h4_figure(leads: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(3.6, 3.0))
    ax.hist(leads.lead_s.clip(-30, 90), bins=40, color=BLUE, edgecolor=SURF, linewidth=1)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_xlabel("Book move leads the public score feed by, s")
    ax.set_ylabel("Score changes")
    ax.set_title("The book knows first")
    _save(fig, "fig5_h4")
