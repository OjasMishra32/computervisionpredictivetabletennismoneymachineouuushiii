"""COURTSIDE paper figures, v2 house style (docs/paper/figstyle.py): main text F1-F5 and appendix A1-A7.

Writes results/paper/v2/<name>.pdf (vector, drawn at final print size, TrueType fonts embedded) and a 300 dpi PNG of
each. Every number comes from a committed result file, through the loaders of scripts/paper_figures.py where they
exist (imported, not copied); nothing here re-runs a backtest or opens held-out data. An input that is not there yet
(results/e2e, results/capacity may still be running) gets a clearly marked placeholder for that panel only.

Usage: .venv/bin/python scripts/paper_figures_v2.py [--only F1 F3 A4]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs/paper"))

import figstyle as fs  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

from scripts import paper_figures as pf  # noqa: E402  (shared loaders: load, sweep_curves, v2_daily_paths, ...)

OUT = ROOT / "results/paper/v2"
W = fs.FIG_W
O, K, G = fs.ORANGE, fs.INK, fs.GREY
M = fs.MINUS
T = fs.THIN
ND = fs.NDASH

SOURCES: dict[str, list[str]] = {}   # figure name -> data files actually read (for FIGURES.md)
TITLES: dict[str, list[str]] = {}    # figure name -> panel takeaway titles


def load(rel: str, fig: str | None = None):
    v = pf.load(rel)
    if fig and v is not None:
        SOURCES.setdefault(fig, [])
        if rel not in SOURCES[fig]:
            SOURCES[fig].append(rel)
    return v


def note_src(fig: str, *rels: str) -> None:
    for rel in rels:
        SOURCES.setdefault(fig, [])
        if rel not in SOURCES[fig] and (ROOT / rel).exists():
            SOURCES[fig].append(rel)


def ptitle(fig_name: str, ax, letter: str, title: str, **kw) -> None:
    TITLES.setdefault(fig_name, []).append(f"{letter} {title}".strip())
    fs.panel(ax, letter, title.replace("$", r"\$"), **kw)  # a literal $, never mathtext


def s_fmt(v: float) -> str:
    """Seconds for labels: 46 ms, 0.5 s, 12.2 s, 28 s."""
    if v < 1:
        return f"{v * 1000:.0f}{T}ms" if v < 0.1 else f"{v:g}{T}s"
    return f"{v:.1f}{T}s" if v < 20 and abs(v - round(v)) > 0.05 else f"{round(v):d}{T}s"


def rng(lo: float, hi: float) -> str:
    def one(v):
        return f"{v:g}" if v < 10 else f"{round(v):d}"
    return f"{one(lo)}{ND}{one(hi)}{T}s"


# ============================================================================================== F1
def stamp_lags() -> tuple[float, float]:
    """(pre-registered, calibrated) stamp lags in s, from the latency sweep's own metadata."""
    sw = pf.load("results/tier0/latency_sweep.json")
    pre, cal = 2.0, None
    if sw:
        pre = float(sw["model"]["revised_primary"]["stamp_lag"])
        m = re.search(r"([0-9.]+) s", str(sw["grids"]["video_stamp_lag_sensitivity"]["tournament_lagcal"]))
        cal = float(m.group(1)) if m else None
    return pre, cal


def reprice_window() -> tuple[float, float, float] | None:
    """(lo, hi, book-minus-stamp) in s: when the book reprices, counted from the end of the point.

    The book reprices a measured median 1.16 s before the official stamp (research/v2/latency, n = 482); the stamp's
    own lag after the point is unmeasured, so the reprice lies between stamp lag 2.0 s (pre-registered) and 3.14 s
    (calibrated) minus 1.16 s = 0.84-1.98 s. F1 and F4 both draw this one window (results/e2e/summary.json quotes the
    same two implied values under reprice_reference.implied_after_point_s and is checked against them)."""
    m1 = pf.latency_m1()
    if not m1:
        return None
    b = float(m1["book_vs_official_T_s"]["median"])
    pre, cal = stamp_lags()
    lo, hi = pre + b, (cal if cal else pre) + b
    e2e = pf.load("results/e2e/summary.json")
    imp = ((e2e or {}).get("reprice_reference") or {}).get("implied_after_point_s") or {}
    if imp:
        vals = sorted(v for k, v in imp.items() if k.startswith("stamp_lag"))
        assert len(vals) == 2 and abs(vals[0] - lo) < 0.006 and abs(vals[1] - hi) < 0.006, (vals, lo, hi)
    return lo, hi, b


TIME_AFTER = "seconds after the point ends"          # F1a, F4a: one wording for the time axis after the event
LEAD_TT = "lead before the ball reaches the table end (ms)"   # table tennis: 'contact' as defined in the source
LEAD_TENNIS = "lead before the bounce (ms)"          # tennis simulation (A6)


def F1() -> list[str]:
    name = "fig1_race"
    fig = plt.figure(figsize=(W, 3.2))
    # ---------------------------------------------------------------- (a) the information race
    AX_L, AX_W = 1.36, 4.30
    axa = fs.axes_in(fig, AX_L, 1.98, AX_W, 0.88)
    wr = pf.webrtc_latency()
    note_src(name, "results/webrtc/latency.json")
    sw = load("results/tier0/latency_sweep.json", name)
    m1 = pf.latency_m1()
    note_src(name, "research/v2/latency/results.json")
    pub = pf.public_stream_s()
    note_src(name, "results/home_stream/sub_second_routes.json")
    src = {s_["key"]: s_ for s_ in sw["sources"]} if sw else {}

    rows = []  # (row label, kind, lo, hi, extra, status)
    if wr:
        rows.append(("Our CV pipeline", "ours", wr["p50"] / 1e3, wr["p99"] / 1e3, None, "measured"))
    else:
        rows.append(("Our CV pipeline", "pending", None, None, None, ""))
    if "official_feed" in src:
        lo, hi = src["official_feed"]["band_s"]
        rows.append(("Official stamp (venue)", "unmeasured", lo, hi, None, "unmeasured"))
    if "betting_video" in src:
        lo, hi = src["betting_video"]["band_s"]
        rows.append(("Licensed video", "range", lo, hi, None, "vendor-stated"))
    if "tv" in src:
        lo, hi = src["tv"]["band_s"]
        rows.append(("TV broadcast", "range", lo, hi, None, "published"))
    if pub:
        rows.append(("Public WebRTC stream", "point", pub, pub, None, "measured"))
    if m1:
        feeds = [("ESPN", -m1["espn:game"]["lead_vs_book_s"]["median"]),
                 ("PM", -m1["pm_sports:game"]["lead_vs_book_s"]["median"]),
                 ("WTA", -m1["wta:point"]["lead_vs_book_s"]["median"])]
        v = [x for _, x in feeds]
        rows.append(("Score feeds", "feeds", min(v), max(v), feeds, "measured"))

    ax = axa
    x0, x1 = 0.01, 100
    fs.log_time_axis(ax, ticks=(0.01, 0.1, 0.5, 1, 3, 10, 60), lim=(x0, x1), label=f"{TIME_AFTER} (log scale)")
    n = len(rows)
    ax.set_ylim(n - 0.5, -0.6)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r_[0] for r_ in rows])
    ax.tick_params(axis="y", length=0, pad=6)
    for t, r_ in zip(ax.get_yticklabels(), rows):
        if r_[1] in ("ours", "pending"):
            t.set_color(O)
            t.set_fontweight("semibold")
    ax.spines["left"].set_visible(False)
    rw = reprice_window()
    if rw:
        r_lo, r_hi, b = rw
        ax.axvspan(r_lo, r_hi, color=fs.SHADE, lw=0, zorder=0.3)
        # label in a strip above the frame, centred on the band (never in the rows)
        ax.annotate(f"book reprices, {fs.f(abs(b))}{T}s before the stamp", xy=(np.sqrt(r_lo * r_hi), 1.0),
                    xycoords=("data", "axes fraction"), xytext=(0, 2.0), textcoords="offset points", ha="center",
                    va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED, annotation_clip=False)
    RANGE_LW = 3.0  # 3 pt range bars
    for i, (lab, kind, lo, hi, extra, status) in enumerate(rows):
        if kind == "pending":
            ax.text(x0 * 1.3, i, "pending: results/webrtc/latency.json", va="center", fontsize=fs.FS_SMALL,
                    color=O, style="italic")
            continue
        val = None   # direct value label right of the mark
        if kind == "ours":   # p50 dot, whisker to the p99
            ax.plot([lo, hi], [i, i], color=O, lw=1.0, zorder=4, solid_capstyle="butt")
            ax.plot([lo], [i], ls="none", marker="o", ms=4.6, color=O, mew=0, zorder=5)
            val = (hi, f"{wr['p50']:.0f}{T}ms (p50) · own clip, loopback", O)
        elif kind == "unmeasured":
            ax.plot([lo, hi], [i, i], color=G, lw=1.6, ls=(0, (2.2, 1.6)), zorder=4)
            val = (hi, rng(lo, hi), K)
        elif kind == "range":
            ax.plot([lo, hi], [i, i], color=G, lw=RANGE_LW, zorder=4, solid_capstyle="butt")
            val = (hi, rng(lo, hi), K)
        elif kind == "point":
            ax.plot([lo], [i], ls="none", marker="o", ms=4.6, color=G, mew=0, zorder=5)
            val = (lo, f"{fs.f(lo)}{T}s", K)
        elif kind == "feeds":
            ax.plot([lo, hi], [i, i], color=G, lw=RANGE_LW, zorder=4, solid_capstyle="butt")
            # one range, the three medians named to its left (the dots fused at print size)
            ax.annotate(f"{' · '.join(f'{k_} {round(v_):d}' for k_, v_ in extra)}{T}s", xy=(lo, i),
                        xytext=(-5, 0), textcoords="offset points", ha="right", va="center",
                        fontsize=fs.FS_SMALL, color=K, zorder=6)
        if val:
            ax.annotate(val[1], xy=(val[0], i), xytext=(5, 0), textcoords="offset points", ha="left",
                        va="center", fontsize=fs.FS_SMALL, color=val[2], zorder=6)
        # one right-hand column: how each number was obtained
        ax.annotate(status, xy=(1.0, i), xycoords=("axes fraction", "data"), xytext=(8, 0),
                    textcoords="offset points", ha="left", va="center", fontsize=fs.FS_SMALL, color=fs.MUTED,
                    annotation_clip=False)
    ax.tick_params(axis="x", length=2.6)
    ta = f"We call in {wr['p50']:.0f}{T}ms; feeds take seconds" if wr else "Who sees the point first"
    ptitle(name, ax, "a", ta, x_in=0.06, y_in=3.06)

    # ---------------------------------------------------------------- (b) early out-calls on real footage
    axb = fs.axes_in(fig, 0.56, 0.42, 4.40, 0.80)
    ax = axb
    tr = load("results/tracking/summary.json", name)
    snap = ((tr or {}).get("early_call") or {}).get("precision_recall_test_snapshot")
    if not snap:
        fs.placeholder(ax, "results/tracking/summary.json")
        ptitle(name, ax, "b", "Early out-calls: pending", x_in=0.06, y_in=1.40)
    else:
        leads = sorted(int(k[:-2]) for k in snap)
        P = [snap[f"{x}ms"] for x in leads]
        fs.hgrid(ax)
        prec = [d["precision"] for d in P]
        rec = [d["recall"] for d in P]
        lo = [d["precision_wilson95"][0] for d in P]
        hi = [d["precision_wilson95"][1] for d in P]
        ax.plot(leads, rec, color=G, lw=fs.LW_2, zorder=3)
        ax.plot(leads, rec, ls="none", marker="o", ms=3.4, color=G, mew=0, zorder=4)
        fs.whiskers(ax, leads, prec, lo, hi, O, lw=0.9)
        ax.plot(leads, prec, color=O, lw=fs.LW_2, zorder=4)
        ax.plot(leads, prec, ls="none", marker="o", ms=3.8, color=O, mew=0, zorder=5)
        for x, d in zip(leads, P):  # right calls / calls made, above each precision point
            ax.annotate(f"{d['tp']}/{d['tp'] + d['fp']}", xy=(x, max(d["precision_wilson95"][1], d["precision"])),
                        xytext=(0, 3.0), textcoords="offset points", ha="center", va="bottom",
                        fontsize=fs.FS_SMALL, color=O)
        ax.set_xlim(-12, 210)
        ax.set_ylim(0, 1.27)
        ax.set_xticks(leads)
        ax.set_yticks([0, 0.5, 1.0])
        fs.unicode_ticks(ax)
        ax.tick_params(axis="x", length=2.6)
        ax.set_xlabel(LEAD_TT)
        ax.set_ylabel("precision, recall")
        fs.direct_label(ax, [dict(x=leads[-1], y=prec[-1], text="precision (95% CI)", color=O),
                             dict(x=leads[-1], y=rec[-1], text="recall", color=G)], dx_pt=12, leader=False)
        clean = [x for x, d in zip(leads, P) if d["fp"] == 0]
        upto = max(x for x in clean if all(snap[f"{y}ms"]["fp"] == 0 for y in leads if y <= x))
        ptitle(name, ax, "b", f"No false out-calls up to {upto}{T}ms early", x_in=0.06, y_in=1.40)
    return fs.save_fig(fig, name, OUT)

# ============================================================================================== F2
def month_mid(month: str, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.Timestamp:
    """Middle of the part of ``month`` that lies inside [lo, hi] (a split month sits on its own side of the cut)."""
    a = max(pd.Timestamp(month + "-01"), lo)
    b = min(pd.Timestamp(month + "-01") + pd.offsets.MonthEnd(0), hi)
    return a + (b - a) / 2


def month_axis(ax, months: list[pd.Timestamp]) -> None:
    ax.set_xticks(months)
    ax.set_xticklabels([m.strftime("%b") for m in months])
    ax.xaxis.set_minor_locator(NullLocator())


def F2() -> list[str]:
    name = "fig2_edge"
    fig = plt.figure(figsize=(W, 2.6))
    axa = fs.axes_in(fig, 0.50, 0.40, 2.00, 1.78)
    axb = fs.axes_in(fig, 4.08, 0.40, 1.60, 1.78)
    al = load("results/alpha/alpha.json", name)
    paths = pf.v2_daily_paths()
    note_src(name, "results/lowloss/daily.csv", "results/v2/causal.json", "results/v2/cost_stress.json",
             "data/v2_trades_is_oos.parquet")
    oos0 = oos1 = None
    if paths:
        oos0 = paths[0]["burned_oos"].index.min()
        oos1 = paths[0]["burned_oos"].index.max()

    # ---------------------------------------------------------------- (a) monthly markout by who trades
    ax = axa
    if not al:
        fs.placeholder(ax, "results/alpha/alpha.json")
    else:
        A = al["A_source"]
        if oos0 is None:  # no daily file: the OOS starts at the first OOS month
            oos0 = pd.Timestamp(A["OOS"]["months"][0]["month"] + "-01")
            oos1 = pd.Timestamp(A["OOS"]["months"][-1]["month"] + "-01") + pd.offsets.MonthEnd(0)
        is0 = pd.Timestamp(A["IS"]["months"][0]["month"] + "-01")
        # the two tiers are net 30 s markouts; copy-3-s-later is held to resolution (alpha.json), so its label says
        # so and it is drawn thinner, without markers
        series = [("fast_net30_c", K, "Fast tier", fs.LW, True),
                  ("others_net30_c", G, "Everyone else", fs.LW_2, True),
                  ("copy_3s_later_net_to_resolution_c", G, f"Copy 3{T}s later,\nheld to resolution", 0.9, False)]
        dy = {"copy_3s_later_net_to_resolution_c": -7.0}  # its two-line label hangs below its end point
        fs.hgrid(ax)
        x_is = [month_mid(m["month"], is0, oos0) for m in A["IS"]["months"]]
        x_oos = [month_mid(m["month"], oos0, oos1) for m in A["OOS"]["months"]]
        items = []
        for key, col, lab, lw, mk in series:
            y_is = [m[key] for m in A["IS"]["months"]]
            y_oos = [m[key] for m in A["OOS"]["months"]]
            ax.plot(x_is, y_is, color=col, lw=lw, ls=fs.IS_LS, zorder=4)
            ax.plot([x_is[-1]] + x_oos, [y_is[-1]] + y_oos, color=col, lw=lw, ls=fs.OOS_LS, zorder=4)
            if mk:  # filled = IS, hollow = OOS
                ax.plot(x_is, y_is, ls="none", marker="o", ms=2.8, color=col, mew=0, zorder=5)
                ax.plot(x_oos, y_oos, ls="none", marker="o", ms=2.8, mfc="white", mec=col, mew=0.9, zorder=5)
            items.append(dict(x=x_oos[-1], y=y_oos[-1], text=lab, color=col if col != G else fs.MUTED,
                              dy_pt=dy.get(key, 0.0)))
        ax.set_xlim(is0 - pd.Timedelta(days=4), oos1 + pd.Timedelta(days=4))
        fs.oos_shade(ax, oos0)
        fs.zero_line(ax)
        ax.set_ylim(-3.2, 3.2)
        ax.set_yticks([-3, -2, -1, 0, 1, 2, 3])
        fs.unicode_ticks(ax, "y")
        ax.set_ylabel(f"net 30{T}s markout, {fs.CENT}/share")
        month_axis(ax, [pd.Timestamp(m) for m in ("2025-12-01", "2026-02-01", "2026-04-01", "2026-06-01",
                                                   "2026-08-01", "2026-10-01")])
        fs.direct_label(ax, items, dx_pt=5, leader=False, pad_pt=4.0)
    ptitle(name, ax, "a", "Only the fast tier earns; copying late loses", x_in=0.06, y_in=2.42)

    # ---------------------------------------------------------------- (b) v2 cumulative P&L, costs doubled
    ax = axb
    if not paths:
        fs.placeholder(ax, "results/lowloss/daily.csv")
    else:
        base, stressed, _cs = paths
        fs.hgrid(ax)
        lines = [("base", base["is_eval"], base["burned_oos"], K, fs.LW, "Base")]
        if stressed:  # both stressed paths grey (nested: all costs x2 always sits below fees x2), told apart by width
            lines.append(("fee_x2", stressed[("is_eval", "fee_x2")], stressed[("burned_oos", "fee_x2")], G,
                          fs.LW_2, f"Fees {fs.TIMES}2"))
            lines.append(("costs_x2", stressed[("is_eval", "costs_x2")], stressed[("burned_oos", "costs_x2")], G,
                          0.9, f"All costs {fs.TIMES}2"))
        items = []
        for _k, s_is, s_oos, col, lw, lab in lines[::-1]:
            c1 = s_is.cumsum() / 1e3
            c2 = (s_oos.cumsum() / 1e3) + c1.iloc[-1]
            # dashing a jagged daily path breaks into blotches: the OOS part is drawn at weekly closes (and the
            # last day), so the dash pattern reads; the end value is the exact daily total
            c2w = c2.resample("W-SUN").last().dropna()
            c2w = c2w[c2w.index < c2.index[-1]]
            c2w = pd.concat([c2w, c2.iloc[[-1]]])
            ax.plot(c1.index, c1.values, color=col, lw=lw, ls=fs.IS_LS, zorder=4)
            ax.plot([c1.index[-1]] + list(c2w.index), [c1.iloc[-1]] + list(c2w.values), color=col, lw=lw,
                    ls=(0, (3.0, 1.6)), zorder=4)
            items.append(dict(x=c2.index[-1], y=float(c2.iloc[-1]),
                              text=f"{lab}\nOOS {fs.usd(s_oos.sum(), 1, sign=True, k=True)}",
                              color=col if col != G else fs.MUTED))
        x_lo = base["is_eval"].index.min()
        ax.set_xlim(x_lo - pd.Timedelta(days=3), oos1 + pd.Timedelta(days=3))
        fs.oos_shade(ax, oos0)
        fs.zero_line(ax)
        ax.set_ylim(-3, 48)
        ax.set_yticks([0, 10, 20, 30, 40])
        ax.set_ylabel("cumulative net P&L, $k")
        month_axis(ax, [pd.Timestamp(m) for m in ("2026-02-01", "2026-04-01", "2026-06-01", "2026-08-01",
                                                   "2026-10-01")])
        fs.direct_label(ax, items, dx_pt=5, bounds=(0.0, 1.1), leader=False)
    ptitle(name, ax, "b", "v2 earns; doubled costs erase the OOS gain", x_in=3.52, y_in=2.42)
    return fs.save_fig(fig, name, OUT)


# ============================================================================================== F3
REF_LINES = ((0.5, "best licensed", 2), (1.0, "base", 1), (3.0, "requirement", 1))


def ref_verticals(ax, labels: bool = True) -> None:
    """Dotted verticals at 0.5 s (best licensed case), 1 s (base case) and 3 s (requirement). Every label starts at
    its own line, above the frame; 'best licensed' is one tier higher because it runs across the 1 s and 3 s lines,
    and each line is continued up to its own label."""
    if labels:
        fs.vref_labelled(ax, REF_LINES, color=K, lw=0.8)
    else:
        for x, _lab, _tier in REF_LINES:
            fs.vref(ax, x, color=K, lw=0.8)


def F3() -> list[str]:
    name = "fig3_speed_value"
    fig = plt.figure(figsize=(W, 2.75))
    axa = fs.axes_in(fig, 0.56, 0.42, 2.60, 1.74)
    axb = fs.axes_in(fig, 3.72, 0.42, 2.60, 1.74)
    curves = pf.sweep_curves()
    sw = load("results/tier0/latency_sweep.json", name)
    note_src(name, "results/tier0/latency_sweep.csv", "results/tier0/latency_sweep_seeds.csv")
    pre, cal = stamp_lags()
    readings = [("tournament_lagcal", O, f"calibrated lag {cal:g}{T}s"),
                ("tournament", K, f"pre-registered lag {pre:g}{T}s")]
    if curves is None or sw is None:
        for ax, letter in ((axa, "a"), (axb, "b")):
            fs.placeholder(ax, "results/tier0/latency_sweep.csv")
            ptitle(name, ax, letter, "pending", dx_in=-0.5)
        return fs.save_fig(fig, name, OUT)
    be = sw["breakeven_video_delay"]
    bes = {(r, p): be[r][p]["breakeven_V_s_seed_mean_curve"] for r, _, _ in readings for p in ("IS", "burned_OOS")}
    v1 = {(r, p): sw["video_own120"][r]["1"][p]["sharpe_ann"] for r, _, _ in readings for p in ("IS", "burned_OOS")}

    for ax, metric, lo_k, hi_k, ylab in ((axa, "pnl_per_day_usd", "usd_lo", "usd_hi", "net $ per day"),
                                         (axb, "sharpe_ann", "sr_lo", "sr_hi", "Sharpe ratio, annualised")):
        fs.log_time_axis(ax, ticks=(0.1, 0.5, 1, 3, 10, 60), lim=(0.05, 60), label="feed delay V, s (log scale)")
        fs.hgrid(ax)
        for reading, col, _lab in readings:
            for period, ls in (("IS", fs.IS_LS), ("burned_OOS", fs.OOS_LS)):
                c = curves[(reading, period)]
                c = c[c.x_s >= 0.05]
                if period == "burned_OOS":  # one band per reading (the OOS one) keeps the panel readable
                    fs.add_ci_band(ax, c.x_s, c[lo_k], c[hi_k], col if col != K else G,
                                   alpha=0.13 if col != K else 0.12)
                ax.plot(c.x_s, c[metric], color=col, ls=ls, lw=fs.LW, zorder=4)
        ref_verticals(ax)
        fs.zero_line(ax)
        ax.set_ylabel(ylab)

    # (a) $/day: break-even dots and reading labels
    ax = axa
    ax.set_ylim(-88, 272)
    ax.set_yticks([0, 100, 200])
    fs.unicode_ticks(ax, "y")
    for (r, p), x in bes.items():  # filled = IS, hollow = OOS (as everywhere)
        col = O if r == "tournament_lagcal" else K
        ax.plot([x], [0], ls="none", marker="o", ms=4.2, mfc=col if p == "IS" else "white", mec=col, mew=1.1,
                zorder=7)
    bc = [bes[("tournament_lagcal", p)] for p in ("IS", "burned_OOS")]
    bp = [bes[("tournament", p)] for p in ("IS", "burned_OOS")]
    # break-even key in the empty upper right (open circles on the zero line)
    ax.text(3.6, 150, "break-even V", ha="left", va="center", fontsize=fs.FS_SMALL, color=fs.MUTED)
    ax.text(3.6, 118, f"{fs.f(min(bc))}{ND}{fs.f(max(bc))}{T}s", ha="left", va="center", fontsize=fs.FS, color=O)
    ax.text(3.6, 86, f"{fs.f(min(bp))}{ND}{fs.f(max(bp))}{T}s", ha="left", va="center", fontsize=fs.FS, color=K)
    lab_cal = readings[0][2].replace(" lag", "\nlag")
    lab_pre = readings[1][2].replace(" lag", "\nlag")
    ax.text(0.058, 236, lab_cal, ha="left", va="center", fontsize=fs.FS, color=O, zorder=8, linespacing=1.1)
    ax.text(0.058, -50, lab_pre, ha="left", va="center", fontsize=fs.FS, color=K, zorder=8, linespacing=1.1)
    lo_be, hi_be = min(bes.values()), max(bes.values())
    ptitle(name, ax, "a", f"Profit hits zero at {fs.f(lo_be)}{ND}{fs.f(hi_be)}{T}s of delay", x_in=0.06, y_in=2.55)

    # (b) Sharpe: base-case values at V = 1 s
    ax = axb
    ax.set_ylim(-9, 31)
    ax.set_yticks([0, 10, 20, 30])
    fs.unicode_ticks(ax, "y")
    for (r, p), v in v1.items():
        col = O if r == "tournament_lagcal" else K
        ax.plot([1.0], [v], ls="none", marker="o", ms=3.6, mfc=col if p == "IS" else "white", mec=col, mew=1.0,
                zorder=7)
    ax.text(0.985, 0.97, "IS solid\nOOS dashed\n20-seed OOS band", transform=ax.transAxes, ha="right",
            va="top", fontsize=fs.FS_SMALL, color=fs.MUTED, linespacing=1.2)
    lo1, hi1 = min(v1.values()), max(v1.values())
    ptitle(name, ax, "b", f"Sharpe at the 1{T}s base: {fs.f(lo1)}{ND}{fs.f(hi1)}", x_in=3.24, y_in=2.55)
    return fs.save_fig(fig, name, OUT)


# ============================================================================================== F4
def kusd(v, _pos=None) -> str:
    a = abs(v)
    body = f"${a / 1e3:g}k" if a >= 1e3 else f"${a:g}"
    return (M if v < 0 else "") + body


def e2e_stages(e2e: dict) -> list[tuple[str, float, str]] | None:
    """(label, mean ms, kind) per waterfall row from results/e2e/summary.json. Means are used because they add up
    exactly to the mean total (medians do not)."""
    st = {r["stage"]: r["ms"]["mean"] for r in e2e.get("stage_ms", [])}
    need = ["sender: frame into encoder", "encode + WHIP + MediaMTX + RTP in", "H.264 decode + handoff",
            "prep + queue + detector", "tracker + features + classifier", "strategy rule (fair value, edge)",
            "risk check", "unsigned order built", "network one-way (RTT/2)", "venue order delay (secondsDelay)"]
    if any(k not in st for k in need):
        return None
    feed = e2e.get("budget_with_1s_simulated_feed", {}).get("feed_simulated_ms")
    rows = []
    if feed is not None:
        rows.append(("Licensed feed V (simulated)", float(feed), "assumed"))
    rows += [("WebRTC: encode, send, decode", st[need[0]] + st[need[1]] + st[need[2]], "ours"),
             ("CV on a laptop: detect, classify", st[need[3]] + st[need[4]], "ours"),
             ("Decision, risk, order ready", st[need[5]] + st[need[6]] + st[need[7]], "ours"),
             ("Network to the venue", st[need[8]], "other"),
             ("Venue order delay", st[need[9]], "rule")]
    return rows


def F4() -> list[str]:
    name = "fig4_frame_to_trade"
    fig = plt.figure(figsize=(W, 3.2))
    # ---------------------------------------------------------------- (a) latency waterfall
    axa = fs.axes_in(fig, 1.92, 2.12, 3.86, 0.80)
    ax = axa
    e2e = load("results/e2e/summary.json", name)
    rows = e2e_stages(e2e) if e2e else None
    if not rows:
        fs.placeholder(ax, "results/e2e/summary.json", "pipeline latency waterfall")
        ptitle(name, ax, "a", "Frame to trade: pending the end-to-end run", x_in=0.06, y_in=3.06)
    else:
        ms = np.array([r[1] for r in rows])
        starts = np.concatenate([[0.0], np.cumsum(ms)[:-1]]) / 1e3
        ends = np.cumsum(ms) / 1e3
        total = ends[-1]
        ours = sum(r[1] for r in rows if r[2] == "ours")
        n = len(rows)
        ax.set_xlim(0, 3.2)
        ax.set_ylim(n - 0.5, -0.6)
        rw = reprice_window()  # the same window as F1a (0.84-1.98 s), not e2e's narrower 1.0-1.5 s working band
        if rw:
            ax.axvspan(rw[0], rw[1], color=fs.SHADE, lw=0, zorder=0.3)
            ax.annotate("book reprices", xy=((rw[0] + rw[1]) / 2, 1.0), xycoords=("data", "axes fraction"),
                        xytext=(0, 1.5), textcoords="offset points", ha="center", va="bottom",
                        fontsize=fs.FS_SMALL, color=fs.MUTED, annotation_clip=False)
        req = e2e.get("budget_with_1s_simulated_feed", {}).get("requirement_ms")
        if req:
            fs.vref(ax, req / 1e3, color=K, lw=0.8)
            ax.annotate(f"{req / 1e3:g}{T}s requirement", xy=(req / 1e3, 1.0), xycoords=("data", "axes fraction"),
                        xytext=(0, 1.5), textcoords="offset points", ha="center", va="bottom",
                        fontsize=fs.FS_SMALL, color=K, annotation_clip=False)
        ax.axvline(total, color=K, lw=0.9, zorder=2.6)
        ax.annotate(f"executable {total:.2f}{T}s", xy=(total, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(0, 1.5), textcoords="offset points", ha="center", va="bottom", fontsize=fs.FS_SMALL,
                    color=K, annotation_clip=False)
        h = 0.56
        gpu = None
        ref = (e2e.get("production_gpu_reference") or {}).get("online_vs_offline") or {}
        if ref.get("emitted_call_latency_ms"):
            gpu = (ref.get("gpu", "GPU"), ref["emitted_call_latency_ms"]["mean"])
        for i, ((lab, v, kind), x0, x1) in enumerate(zip(rows, starts, ends)):
            if kind == "ours":
                ax.barh(i, x1 - x0, left=x0, height=h, color=O, edgecolor=O, lw=0.9, zorder=3)
            elif kind == "assumed":
                ax.barh(i, x1 - x0, left=x0, height=h, color="white", edgecolor=G, lw=0.7, ls=(0, (2.5, 1.5)),
                        zorder=3)
            else:
                ax.barh(i, x1 - x0, left=x0, height=h, color=G, lw=0, zorder=3)
            if v >= 100:
                txt = f"{v / 1e3:g}{T}s" + (", simulated" if kind == "assumed" else "")
            elif v >= 1:
                txt = f"+{v:.0f}{T}ms"
            else:
                txt = f"+{v:.1f}{T}ms"
            if lab.startswith("CV") and gpu:
                txt += f" ({gpu[0].replace('NVIDIA ', '')} GPU: {gpu[1]:.0f}{T}ms)"
            if lab.startswith("Network"):
                txt += ", RTT/2"
            if kind == "rule":
                txt = "+" + txt + ", venue rule"
            ax.annotate(txt, xy=(x1, i), xytext=(4, 0), textcoords="offset points", ha="left", va="center",
                        fontsize=fs.FS_SMALL, color=O if kind == "ours" else K, zorder=6)
        ax.set_yticks(range(n))
        ax.set_yticklabels([r[0] for r in rows])
        for t, r in zip(ax.get_yticklabels(), rows):
            if r[2] == "ours":
                t.set_color(O)
        ax.tick_params(axis="y", length=0, pad=6)
        ax.spines["left"].set_visible(False)
        ax.set_xticks([0, 0.5, 1, 1.5, 2, 2.5, 3])
        fs.unicode_ticks(ax, "x")
        ax.set_xlabel(TIME_AFTER)
        # 'order-ready in 54 ms' (capture to unsigned order, e2e) is a different span from F1's 'call in 46 ms'
        # (frame send to call, webrtc/latency.json): the title names which one
        ptitle(name, ax, "a", f"Order-ready in {ours:.0f}{T}ms; executable at {fs.f(total)}{T}s", x_in=0.06,
               y_in=3.06)

    # ---------------------------------------------------------------- (b, c) capacity vs capital
    axb = fs.axes_in(fig, 0.58, 0.44, 2.30, 0.88)
    axc = fs.axes_in(fig, 3.80, 0.44, 2.30, 0.88)
    capj = load("results/capacity/capacity.json", name)
    cells = ROOT / "results/capacity/cv_cells.csv"
    if not capj or not cells.exists():
        for ax, letter in ((axb, "b"), (axc, "c")):
            fs.placeholder(ax, "results/capacity/cv_cells.csv", "capacity vs size")
        ptitle(name, axb, "b", "Capacity: pending", x_in=0.06, y_in=1.52)
        ptitle(name, axc, "c", "Capacity: pending", x_in=3.28, y_in=1.52)
        return fs.save_fig(fig, name, OUT)
    note_src(name, "results/capacity/cv_cells.csv")
    A = pd.read_csv(cells)
    base = capj["grid"]["base"]
    path_order = 250 if 250 in set(A.order_cap) else int(A.order_cap.min())
    pre, cal = stamp_lags()
    readings = [("lagcal", O, f"calibrated lag {cal:g}{T}s"), ("prereg", K, f"pre-registered lag {pre:g}{T}s")]

    def path(rk, p):
        D = A[(A.reading == rk) & (A.period == p) & (A.growth == 1.0) & (A.phi == base["phi"]) &
              (A.coverage.astype(str) == str(base["coverage"])) & (A.order_cap == path_order)]
        return D.sort_values("net_cap")

    half = {}
    for p in ("IS", "burned_OOS"):
        h = capj["answers"]["cv"].get(f"lagcal|phi{base['phi']:g}|cov{base['coverage']}|g1|{p}", {})
        h = h.get("at_half_sharpe", {})
        if h.get("reached_within_grid"):
            half[p] = h
    for ax, col_m, lo_k, hi_k, ylab in ((axb, "pnl_per_day_usd", "pnl_per_day_usd_p2_5", "pnl_per_day_usd_p97_5",
                                         "net $ per day"),
                                        (axc, "sharpe_ann", "sharpe_ann_p2_5", "sharpe_ann_p97_5",
                                         "Sharpe ratio")):
        fs.hgrid(ax)
        for rk, col, _lab in readings:
            for p, ls in (("IS", fs.IS_LS), ("burned_OOS", fs.OOS_LS)):
                D = path(rk, p)
                if p == "burned_OOS" and rk == "lagcal" and ax is axc:
                    # one seed band (calibrated OOS) where it carries the message; $/day seed bands span
                    # several hundred dollars at large size and would set the scale
                    fs.add_ci_band(ax, D.capital_usd, D[lo_k], D[hi_k], col, alpha=0.13)
                ax.plot(D.capital_usd, D[col_m], color=col, ls=ls, lw=fs.LW, zorder=4)
                if p == "IS":  # filled = IS, hollow = OOS
                    ax.plot(D.capital_usd, D[col_m], ls="none", marker="o", ms=2.6, color=col, mew=0, zorder=5)
                else:
                    ax.plot(D.capital_usd, D[col_m], ls="none", marker="o", ms=2.8, mfc="white", mec=col, mew=0.8,
                            zorder=5)
        for p, h in half.items():  # where the Sharpe halves: a larger marker, same fill rule
            yv = h["pnl_per_day_usd"] if col_m == "pnl_per_day_usd" else h["sharpe_ann"]
            ax.plot([h["capital_usd"]], [yv], ls="none", marker="o", ms=5.2, mfc=O if p == "IS" else "white",
                    mec=O, mew=1.2, zorder=7)
        fs.zero_line(ax)
        ax.set_xscale("log")
        ax.set_xlim(6.5e3, 1.25e5)
        ax.xaxis.set_major_locator(FixedLocator([1e4, 3e4, 1e5]))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(kusd))
        ax.set_xlabel("capital required (log scale)")
        ax.set_ylabel(ylab)
    ax = axb
    ax.set_ylim(-110, 400)
    ax.set_yticks([0, 100, 200, 300, 400])
    ax.yaxis.set_major_formatter(FuncFormatter(kusd))
    ax.text(6.9e3, 300, readings[0][2].replace(" lag", "\nlag"), ha="left", va="center", fontsize=fs.FS,
            color=O, linespacing=1.1)
    ax.text(6.9e3, -72, readings[1][2], ha="left", va="center", fontsize=fs.FS, color=K)
    # calibrated OOS $/day along the path is 37, 57, 67, 61, 44, 24, 168: not monotone, so the title says erratic
    ptitle(name, ax, "b", "Dollars grow in sample; OOS is erratic", x_in=0.06, y_in=1.52)
    ax = axc
    ax.set_ylim(-10, 23)
    ax.set_yticks([0, 10, 20])
    fs.unicode_ticks(ax, "y")
    ax.text(6.9e3, -6.5, readings[1][2], ha="left", va="center", fontsize=fs.FS, color=K)
    if half:
        caps = sorted(h["capital_usd"] for h in half.values())
        xs = [h["capital_usd"] for h in half.values()]
        ys = [h["sharpe_ann"] for h in half.values()]
        tx, ty = 3.0e4, 19.0
        for x, y in zip(xs, ys):  # one label, a leader to each half-Sharpe point (IS and OOS)
            ax.annotate("", xy=(x, y), xytext=(tx * 1.08, ty - 2.2), textcoords="data",
                        arrowprops=dict(arrowstyle="-", color=O, lw=0.5, shrinkA=0, shrinkB=3.2))
        ax.text(tx, ty, "Sharpe halves", ha="left", va="center", fontsize=fs.FS_SMALL, color=O)
        t = f"Sharpe halves by {kusd(round(caps[0], -3))}{ND}{kusd(round(caps[-1], -3))}"
    else:
        t = "Sharpe falls with size"
    ptitle(name, ax, "c", t, x_in=3.28, y_in=1.52)
    return fs.save_fig(fig, name, OUT)


# ============================================================================================== F5
def F5() -> list[str]:
    """One real still with the predicted arc (already rendered by scripts/cv_showcase.py), cropped clean of the
    on-screen panels: no banner, no HUD, only the court, the ball's comet, the predicted arc and its landing label."""
    name = "fig5_cv_still"
    from PIL import Image
    still = "results/viz/stills/still_01_tt_call_408ms.png"
    caps = load("results/viz/stills/captions.json", name) or {}
    p = ROOT / still
    crop = (150, 150, 1920, 664)  # px in the 1920 x 1080 still: below the top text box, above the call banner
    w_px, h_px = crop[2] - crop[0], crop[3] - crop[1]
    img_h = W * h_px / w_px
    fig = plt.figure(figsize=(W, img_h + 0.26))
    ax = fs.axes_in(fig, 0.0, 0.0, W, img_h)
    if not p.exists():
        fs.placeholder(ax, still)
        ptitle(name, ax, "", "CV still: pending", x_in=0.0, y_in=img_h + 0.08)
        return fs.save_fig(fig, name, OUT)
    note_src(name, still)
    im = Image.open(p).convert("RGB").crop(crop)
    ax.imshow(np.asarray(im), interpolation="none", aspect="auto")
    ax.set_axis_off()
    cap = caps.get(Path(still).name, "")
    m = re.search(r"calls MISS (\d+) ms before", cap)
    ms = m.group(1) if m else re.search(r"_(\d+)ms", still).group(1)
    # 'contact' in the source means the ball reaching the table end, so the title says that; the call is the
    # frozen model's, the arc and its +/-81 cm landing band are the display-only physics fit (the tag says so)
    ptitle(name, ax, "", f"Miss called {ms}{T}ms before the table end", x_in=0.0, y_in=img_h + 0.08)
    fig.text(1.0, (img_h + 0.08) / fig.get_size_inches()[1],
             "call: frozen tier-0 model · arc and band: physics fit, display only", ha="right", va="baseline",
             fontsize=fs.FS_SMALL, color=fs.MUTED, style="italic")
    return fs.save_fig(fig, name, OUT)


# ============================================================================================== appendix
def A1() -> list[str]:
    """v2 net edge by size and the $/day cost ladder (gross -> net of fees -> after fixed costs)."""
    name = "figA1_capacity_costs"
    fig = plt.figure(figsize=(W, 2.5))
    axa = fs.axes_in(fig, 0.52, 0.66, 2.05, 1.44)
    axb = fs.axes_in(fig, 4.18, 0.66, 2.17, 1.44)
    fin = load("results/financials/financials.json", name)
    sw = load("results/tier0/latency_sweep.json", name)
    if not fin:
        fs.placeholder(axa, "results/financials/financials.json")
        fs.placeholder(axb, "results/financials/financials.json")
        return fs.save_fig(fig, name, OUT)
    v2f = fin["strategies"]["v2"]
    sc = v2f["scaling"]
    sizes = [k for k in ("0.5x", "1x", "2x", "5x", "all prints") if k in sc]
    xs = np.arange(len(sizes))
    ax = axa
    fs.hgrid(ax)
    fs.zero_line(ax)
    for per, off, mfc, ls in (("IS", -0.09, K, fs.IS_LS), ("OOS", 0.09, "white", fs.OOS_LS)):  # hollow = OOS
        y = np.array([sc[k][per]["per_share_c"] for k in sizes])
        lo = np.array([sc[k][per]["per_share_ci95_c"][0] for k in sizes])
        hi = np.array([sc[k][per]["per_share_ci95_c"][1] for k in sizes])
        fs.whiskers(ax, xs + off, y, lo, hi, K, lw=0.8)
        ax.plot(xs + off, y, color=K, ls=ls, lw=fs.LW_2, zorder=4)
        ax.plot(xs + off, y, ls="none", marker="o", ms=3.6, mfc=mfc, mec=K, mew=1.0, zorder=5)
        ax.annotate(per, xy=(xs[0] + off, y[0]), xytext=(-7, 0), textcoords="offset points", ha="right",
                    va="center", fontsize=fs.FS_SMALL, color=K)
    ax.set_xlim(-0.75, len(sizes) - 0.5)
    ax.set_xticks(xs)
    caps = [sc[k]["OOS"].get("capital_usd") for k in sizes]
    ax.set_xticklabels([f"{k.replace('x', fs.TIMES).replace('all prints', 'all')}\n{kusd(round(c, -3))}"
                        for k, c in zip(sizes, caps)], linespacing=1.15)
    ax.tick_params(axis="x", length=0)
    ax.set_ylim(-3.9, 2.3)
    ax.set_yticks([-3, -2, -1, 0, 1, 2])
    fs.unicode_ticks(ax, "y")
    ax.set_ylabel(f"net {fs.CENT} per share, 95% CI")
    ax.set_xlabel("size (OOS capital)")
    ptitle(name, ax, "a", "v2's OOS edge fades as size grows", x_in=0.06, y_in=2.34)

    ax = axb
    fixed = v2f["cost"]["daily"]
    rows = []
    for per, lab in (("IS", "v2, IS"), ("OOS", "v2, OOS")):
        w = v2f["periods"][per]["waterfall"]["usd_per_day"]
        rows.append((lab, w["gross_edge"], w["net_trading"], K))
    if sw:
        cv = sw["video_own120"]
        rows.append(("CV calibrated, OOS", None, cv["tournament_lagcal"]["1"]["burned_OOS"]["usd_per_day"], O))
        rows.append(("CV pre-registered, OOS", None, cv["tournament"]["1"]["burned_OOS"]["usd_per_day"], O))
    fs.zero_line(ax, axis="x")
    pos = 0
    for i, (lab, gross, net, col) in enumerate(rows):
        after = net - fixed["central"]
        oos = "OOS" in lab  # filled = IS, hollow = OOS (as everywhere)
        pts = [v for v in (gross, net, after) if v is not None]
        ax.plot([min(pts), max(pts)], [i, i], color=G, lw=0.6, zorder=2)
        ax.plot([net - fixed["high"], net - fixed["low"]], [i, i], color=col, lw=0.9, zorder=3)
        if gross is not None:  # gross edge: a short grey tick (no fill to encode)
            ax.plot([gross], [i], ls="none", marker="|", ms=7.0, color=G, mew=1.3, zorder=4)
        ax.plot([net], [i], ls="none", marker="o", ms=4.0, mfc="white" if oos else G, mec=G, mew=1.0, zorder=4)
        ax.plot([after], [i], ls="none", marker="o", ms=4.6, mfc="white" if oos else col, mec=col, mew=1.1,
                zorder=5)
        ax.annotate(fs.usd(after, 0, sign=True), xy=(after, i), xytext=(0, -5.5), textcoords="offset points",
                    ha="center", va="top", fontsize=fs.FS_SMALL, color=col, zorder=6, bbox=fs.knockout())
        pos += after > 0
        if i == 0:
            for v, t in ((gross, "gross"), (net, "net"), (after, "after costs")):
                if v is not None:
                    ax.annotate(t, xy=(v, i), xytext=(0, 5), textcoords="offset points", ha="center",
                                va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED, zorder=6,
                                bbox=fs.knockout())  # the zero line stops at the word
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.tick_params(axis="y", length=0, pad=6)
    ax.spines["left"].set_visible(False)
    ax.set_ylim(len(rows) - 0.12, -0.75)
    ax.set_xlim(-360, 330)
    ax.set_xticks([-300, -150, 0, 150, 300])
    ax.xaxis.set_major_formatter(FuncFormatter(kusd))
    ax.set_xlabel(f"$ per day (CV at V = 1{T}s)")
    after_pos = [r[0] for r in rows if (r[2] - fixed["central"]) > 0]
    tb = (f"After fixed costs only {after_pos[0].replace(', ', ' ')} stays positive" if len(after_pos) == 1
          else "Fixed costs decide the sign")
    ptitle(name, ax, "b", tb, x_in=2.80, y_in=2.34)
    return fs.save_fig(fig, name, OUT)


def A2() -> list[str]:
    """Latency sweep at every stamp-lag reading, IS and burned OOS ($/day vs V)."""
    name = "figA2_sweep_lags"
    fig = plt.figure(figsize=(W, 2.6))
    axa = fs.axes_in(fig, 0.56, 0.42, 2.60, 1.62)
    axb = fs.axes_in(fig, 3.72, 0.42, 2.60, 1.62)
    curves = pf.sweep_curves()
    note_src(name, "results/tier0/latency_sweep.csv", "results/tier0/latency_sweep_seeds.csv")
    if curves is None:
        fs.placeholder(axa, "results/tier0/latency_sweep.csv")
        fs.placeholder(axb, "results/tier0/latency_sweep.csv")
        return fs.save_fig(fig, name, OUT)
    pre, cal = stamp_lags()
    # (reading, colour, label, place label above (+) or below (-) its line)
    spec = [("tournament_lagcal", O, f"calibrated {cal:g}{T}s", +1),
            ("tournament_lag3", fs.ORANGE_LIGHT, f"lag 3.0{T}s", -1),
            ("tournament", K, f"pre-registered {pre:.1f}{T}s", +1),
            ("tournament_lag1", G, f"stress 1.0{T}s", -1)]
    for ax, period, letter, title, x_in in ((axa, "IS", "a", "In sample, break-even tracks the stamp lag", 0.06),
                                            (axb, "burned_OOS", "b", "Out of sample, the same shift", 3.24)):
        fs.log_time_axis(ax, ticks=(0.1, 0.5, 1, 3, 10, 60), lim=(0.05, 60), label="feed delay V, s (log scale)")
        fs.hgrid(ax)
        for r, col, lab, side in spec:
            c = curves[(r, period)]
            c = c[c.x_s >= 0.05]
            ax.plot(c.x_s, c.pnl_per_day_usd, color=col, lw=fs.LW, ls=fs.IS_LS if period == "IS" else fs.OOS_LS,
                    zorder=4 if col != fs.ORANGE_LIGHT else 3.5)
        # the four lines start 3-60 $/day apart and merge past 3 s: a key in the empty upper right, in the
        # same top-to-bottom order as the lines at the left edge
        for j, (_r, col, lab, _side) in enumerate(spec):
            ax.text(3.45, 0.93 - 0.115 * j, lab.replace("\n", " "), transform=ax.get_xaxis_transform(), ha="left",
                    va="center", fontsize=fs.FS_SMALL, color=col if col != fs.ORANGE_LIGHT else fs.ORANGE_LIGHT_TEXT)
        ref_verticals(ax)
        fs.zero_line(ax)
        ax.set_ylabel("net $ per day")
        ax.set_ylim(-48, 232 if period == "IS" else 150)
        ax.set_yticks([0, 100, 200] if period == "IS" else [0, 50, 100])
        fs.unicode_ticks(ax, "y")
        ptitle(name, ax, letter, title, x_in=x_in, y_in=2.43)
    return fs.save_fig(fig, name, OUT)


def A3() -> list[str]:
    """v2 by venue regime and by month, IS and OOS (results/risk/risk_stats.json)."""
    name = "figA3_regime_month"
    fig = plt.figure(figsize=(W, 2.5))
    axa = fs.axes_in(fig, 0.56, 0.50, 2.35, 1.60)
    axb = fs.axes_in(fig, 3.80, 0.50, 2.45, 1.60)
    rs = load("results/risk/risk_stats.json", name)
    if not rs:
        fs.placeholder(axa, "results/risk/risk_stats.json")
        fs.placeholder(axb, "results/risk/risk_stats.json")
        return fs.save_fig(fig, name, OUT)
    reg = rs["regime"]
    order = [r for r in ("3s/0%", "3s/3%", "1s/3%", "1s/5%") if r in reg["is_eval"]]
    ax = axa
    fs.hgrid(ax)
    fs.zero_line(ax)
    for i, r in enumerate(order):
        d = reg["is_eval"][r]
        fs.whiskers(ax, [i - 0.08], [d["per_share_c"]], [d["ci_c"][0]], [d["ci_c"][1]], K, lw=0.9)
        ax.plot([i - 0.08], [d["per_share_c"]], ls="none", marker="o", ms=4.2, color=K, mew=0, zorder=5)
        if r in reg.get("burned_oos", {}):
            o = reg["burned_oos"][r]
            fs.whiskers(ax, [i + 0.12], [o["per_share_c"]], [o["ci_c"][0]], [o["ci_c"][1]], K, lw=0.9)
            ax.plot([i + 0.12], [o["per_share_c"]], ls="none", marker="o", ms=4.2, mfc="white", mec=K, mew=1.0,
                    zorder=5)
            ax.annotate("OOS", xy=(i + 0.12, o["per_share_c"]), xytext=(5, 0), textcoords="offset points",
                        ha="left", va="center", fontsize=fs.FS_SMALL, color=K)
    d0 = reg["is_eval"][order[0]]
    ax.annotate("IS", xy=(-0.08, d0["per_share_c"]), xytext=(-6, 0), textcoords="offset points", ha="right",
                va="center", fontsize=fs.FS_SMALL, color=K)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([r.replace("s/", f"{T}s / ") for r in order])
    ax.tick_params(axis="x", length=0)
    ax.set_xlim(-0.6, len(order) - 0.4)
    ax.set_ylim(-0.4, 2.9)
    ax.set_yticks([0, 1, 2])
    ax.set_xlabel("venue regime: taker delay / fee")
    ax.set_ylabel(f"net {fs.CENT} per share, 95% CI")
    # not monotone in the regime (3 s/3% 1.36 c < 1 s/3% 1.45 c, CIs overlap): the title states what holds,
    # every regime's CI is above zero, IS and OOS
    all_pos = all(reg[p][r]["ci_c"][0] > 0 for p in reg for r in reg[p])
    ptitle(name, ax, "a", "Edge stays positive in every venue regime" if all_pos else "Edge by venue regime",
           x_in=0.06, y_in=2.34)

    ax = axb
    bm = rs["by_month"]
    paths = pf.v2_daily_paths()
    if paths:
        is0, oos0, oos1 = (paths[0]["is_eval"].index.min(), paths[0]["burned_oos"].index.min(),
                           paths[0]["burned_oos"].index.max())
    else:
        is0 = pd.Timestamp(min(bm["is_eval"]) + "-01")
        oos0 = pd.Timestamp(min(bm["burned_oos"]) + "-01")
        oos1 = pd.Timestamp(max(bm["burned_oos"]) + "-01") + pd.offsets.MonthEnd(0)
    fs.hgrid(ax)
    for per, col, lo, hi in (("is_eval", K, is0, oos0), ("burned_oos", G, oos0, oos1)):
        for m, v in bm[per].items():
            a = max(pd.Timestamp(m + "-01"), lo)
            b = min(pd.Timestamp(m + "-01") + pd.offsets.MonthEnd(0), hi)
            ax.bar(a + (b - a) / 2, v["pnl_usd"] / 1e3, width=max((b - a).days * 0.78, 3.0), color=col, lw=0,
                   zorder=3)
    ax.set_xlim(is0 - pd.Timedelta(days=6), oos1 + pd.Timedelta(days=6))
    fs.oos_shade(ax, oos0)
    fs.zero_line(ax)
    ax.set_ylim(-1.2, 9)
    ax.set_yticks([0, 2, 4, 6, 8])
    fs.unicode_ticks(ax, "y")
    ax.set_ylabel("v2 net P&L per month, $k")
    month_axis(ax, [pd.Timestamp(m) for m in ("2026-02-01", "2026-04-01", "2026-06-01", "2026-08-01",
                                               "2026-10-01")])
    n_pos = sum(v["pnl_usd"] > 0 for v in bm["is_eval"].values())
    ptitle(name, ax, "b", f"{n_pos} of {len(bm['is_eval'])} in-sample months are positive", x_in=3.28, y_in=2.34)
    return fs.save_fig(fig, name, OUT)


def forest_rows(name: str):
    """(family, label, value, lo, hi) of every pre-registered or blind test, on one cents-per-share axis."""
    S = load("results/summary.json", name)
    ex = load("results/expand/results.json", name)
    t3 = load("results/tier0_v3/blind.json", name)
    mk = load("results/maker/oos.json", name)
    rp = load("results/replay/replay.json", name)
    cs = load("results/v2/cost_stress.json", name)
    causal = load("results/v2/causal.json", name)
    rows = []

    def add(fam, lab, v, ci):
        rows.append((fam, lab, v, ci[0] if ci else None, ci[1] if ci else None))
    if S:
        for k, lab, key in (("h1", "H1 follow the jump, OOS", "J0.04_H30"), ("h2", "H2 favourites, OOS", "lo0.85_hi0.97"),
                            ("h5", "H5 quote after jumps, OOS", "J0.04_W30")):
            d = S["oos"][k][key]
            add("other", lab, d["mean_pnl_per_share_c"], d["ci95_pnl_per_share_c"])
        d = S["oos"]["h6_shadow"]
        add("other", "v1 copy fast tier, OOS (blind)", d["mean_pnl_per_share_c"], d["ci95_pnl_per_share_c"])
    if mk:
        add("other", "maker v1, blind OOS (per fill)", mk["primary"]["value_c"], mk["primary"]["ci95_c"])
    if causal:
        d = causal["causal/burned_oos/slip0.0"]
        add("v2", "v2 burned OOS (non-blind)", d["per_share_c"], d["per_share_ci_c"])
    if cs:
        d = cs["burned_oos/fee_x2"]
        add("v2", f"v2 burned OOS, fees {fs.TIMES}2", d["per_share_c"], d["per_share_ci_c"])
    if ex:
        for p, lab in (("u2_is", "v2 unseen markets U2, IS period"), ("u2_oos", "v2 unseen markets U2, OOS (blind)")):
            d = ex["primary"][p]
            add("v2", lab, d["per_share_c"], d["per_share_ci_c"])
    if t3:
        for p, lab in (("u2_is", "tier-0 v3 frozen rule, U2 IS"), ("u2_oos", "tier-0 v3 frozen rule, U2 OOS")):
            d = t3["sets"][p]["primary"]
            ci = d.get("per_share_ci95_c") or d.get("per_share_ci_c") or (
                [d["per_share_ci95_c_lo"], d["per_share_ci95_c_hi"]] if "per_share_ci95_c_lo" in d else None)
            add("cv", lab, d["per_share_c"], ci)
    if rp:
        a = rp["cells"]["V1|lag2|lead_model|florida"]["all"]
        n_m = len(rp.get("matches", [])) or None
        add("cv", f"replay, V = 1{T}s, lag 2{T}s" + (f" ({n_m} matches)" if n_m else ""), a["per_share_mark_c"],
            a["per_share_mark_ci95_c"])
    return rows


def A4() -> list[str]:
    name = "figA4_forest"
    rows = forest_rows(name)
    n = len(rows)
    row_h = 0.185
    H = max(2.4, n * row_h + 0.85)
    fig = plt.figure(figsize=(W, H))
    ax = fs.axes_in(fig, 2.30, 0.45, 2.55, n * row_h + 0.05)
    if not rows:
        fs.placeholder(ax, "results/summary.json and the blind-test files")
        return fs.save_fig(fig, name, OUT)
    lim = (-4.0, 4.0)
    col = {"other": G, "v2": K, "cv": O}
    fam_prev = None
    for i, (fam, lab, v, lo, hi) in enumerate(rows):
        c = col[fam]
        if fam_prev is not None and fam != fam_prev:
            ax.axhline(i - 0.5, color=fs.GRID, lw=0.6, zorder=0)
        fam_prev = fam
        if lo is not None:
            a, b = max(lo, lim[0]), min(hi, lim[1])
            ax.plot([a, b], [i, i], color=c, lw=1.0, zorder=3, solid_capstyle="butt")
            for edge, clipped in ((lim[0], lo < lim[0]), (lim[1], hi > lim[1])):
                if clipped:  # the CI runs past the axis: an arrowhead at the edge
                    ax.annotate("", xy=(edge, i), xytext=(edge - 0.35 * np.sign(edge), i),
                                arrowprops=dict(arrowstyle="-|>", color=c, lw=1.0, mutation_scale=6,
                                                shrinkA=0, shrinkB=0), zorder=3)
        passed = lo is not None and lo > 0
        oos = "OOS" in lab  # filled = IS (or not split), hollow = OOS, as in every other figure
        ax.plot([v], [i], ls="none", marker="o", ms=4.4, mfc="white" if oos else c, mec=c, mew=1.1, zorder=5)
        ci = f" [{fs.num(lo, 2)}, {fs.num(hi, 2)}]" if lo is not None else ""
        ax.annotate(f"{fs.num(v, 2, sign=True)}{ci}", xy=(1.0, i), xycoords=("axes fraction", "data"),
                    xytext=(10, 0), textcoords="offset points", ha="left", va="center", fontsize=fs.FS_SMALL,
                    color=K if passed else fs.MUTED, fontweight="semibold" if passed else "normal",
                    annotation_clip=False)
    ax.axvline(0, color=fs.ZERO, lw=0.8, zorder=1)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r[1] for r in rows])
    for t, r in zip(ax.get_yticklabels(), rows):
        t.set_color(col[r[0]] if r[0] != "other" else K)
    ax.tick_params(axis="y", length=0, pad=6)
    ax.spines["left"].set_visible(False)
    ax.set_ylim(n - 0.5, -0.6)
    ax.set_xlim(*lim)
    ax.set_xticks([-4, -2, 0, 2, 4])
    fs.unicode_ticks(ax, "x")
    ax.set_xlabel(f"net {fs.CENT} per share, 95% CI")
    ax.annotate("estimate [95% CI]", xy=(1.0, -0.6), xycoords=("axes fraction", "data"), xytext=(10, 2),
                textcoords="offset points", ha="left", va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED,
                annotation_clip=False)
    pos = [r for r in rows if r[3] is not None and r[3] > 0]
    title = ("Only v2 at fast-tier fills clears zero" if pos and all(r[0] == "v2" for r in pos)
             else "Every test on one axis")
    ptitle(name, ax, "", title, x_in=0.06, y_in=H - 0.16)
    return fs.save_fig(fig, name, OUT)


GRID_SEP = fs.GRID  # family separators (A4) and the A7a 'base' divider: gridline grey, nothing darker


def A5() -> list[str]:
    """Concentration of v2 P&L in the top-k wallets, matches and days."""
    name = "figA5_concentration"
    fig = plt.figure(figsize=(W, 2.4))
    ax = fs.axes_in(fig, 0.56, 0.55, 5.75, 1.45)
    al = load("results/alpha/alpha.json", name)
    if not al:
        fs.placeholder(ax, "results/alpha/alpha.json")
        return fs.save_fig(fig, name, OUT)
    F = al["F_concentration"]
    units = [u for u in ("wallets", "matches", "days") if u in F.get("IS", {})]
    ks = (1, 5, 10)
    gap = 0.9
    x = []
    for gi, _u in enumerate(units):
        for ki, _k in enumerate(ks):
            x.append(gi * (len(ks) + gap) + ki)
    x = np.array(x, float)
    fs.hgrid(ax)
    bw = 0.36
    for per, off, col in (("IS", -bw / 2 - 0.01, K), ("OOS", bw / 2 + 0.01, G)):
        if per not in F:
            continue
        ys = [F[per].get(u, {}).get(f"top{k}_share_of_pnl", np.nan) * 100 for u in units for k in ks]
        ax.bar(x + off, ys, width=bw, color=col, lw=0, zorder=3)
        ax.annotate(per, xy=(x[0] + off, ys[0]), xytext=(0, 3), textcoords="offset points", ha="center",
                    va="bottom", fontsize=fs.FS_SMALL, color=col if col != G else fs.MUTED)
    ax.axhline(100, color=K, lw=0.7, ls=fs.DOT_LS, zorder=2)
    xm = (len(ks) + gap) * (1 if len(units) > 1 else 0) + (len(ks) - 1) / 2  # above the low 'matches' bars
    ax.annotate("100% of P&L", xy=(xm, 100), xytext=(0, 3), textcoords="offset points", ha="center",
                va="bottom", fontsize=fs.FS_SMALL, color=K)
    ax.set_xticks(x)
    ax.set_xticklabels([f"top {k}" for _u in units for k in ks])
    ax.tick_params(axis="x", length=0)
    for gi, u in enumerate(units):
        xc = gi * (len(ks) + gap) + (len(ks) - 1) / 2
        ax.annotate(u, xy=(xc, 0), xycoords=("data", "axes fraction"), xytext=(0, -17), textcoords="offset points",
                    ha="center", va="top", fontsize=fs.FS, color=K, fontweight="semibold")
    ax.set_xlim(x[0] - 0.7, x[-1] + 0.7)
    top = max(F[p].get(u, {}).get(f"top{k}_share_of_pnl", 0) for p in ("IS", "OOS") if p in F
              for u in units for k in ks) * 100
    ax.set_ylim(0, max(120, fs.nice_ceil(top + 15, 50)))
    ax.set_yticks(np.arange(0, ax.get_ylim()[1] + 1, 50))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:.0f}%"))
    ax.set_ylabel("share of v2 P&L")
    w5 = F["IS"]["wallets"]["top5_share_of_pnl"] * 100
    ptitle(name, ax, "", f"Five wallets carry {fs.f(w5, 0)}% of in-sample P&L", x_in=0.06, y_in=2.24)
    return fs.save_fig(fig, name, OUT)


def A6() -> list[str]:
    """Spin-aware tennis landing model (simulation): landing error and out-call accuracy vs lead."""
    name = "figA6_spin_sim"
    fig = plt.figure(figsize=(W, 2.5))
    axa = fs.axes_in(fig, 0.56, 0.45, 1.72, 1.65)
    axb = fs.axes_in(fig, 3.86, 0.45, 1.72, 1.65)
    sp = load("results/spin/tennis/key_numbers.json", name)
    if not sp:
        fs.placeholder(axa, "results/spin/tennis/key_numbers.json")
        fs.placeholder(axb, "results/spin/tennis/key_numbers.json")
        return fs.save_fig(fig, name, OUT)
    spec = [("baseline", G, "no spin"), ("bls", O, "spin-aware BLS"), ("ukf", fs.ORANGE_LIGHT, "spin-aware UKF")]
    ax = axa
    fs.hgrid(ax)
    items = []
    for k, col, lab in spec:
        if k not in sp:
            continue
        d = sp[k]["sd_cm"]
        xs = sorted(int(x) for x in d)
        ys = [d[str(x)] for x in xs]
        ax.plot(xs, ys, color=col, lw=fs.LW, zorder=4 if k != "ukf" else 3.5)
        items.append(dict(x=xs[-1], y=ys[-1], text=lab.replace("spin-aware ", "spin, "),
                          color=col if k != "ukf" else fs.ORANGE_LIGHT_TEXT))
    fs.log_time_axis(ax, which="y", ticks=(0.1, 0.3, 1, 3, 10, 30), lim=(0.1, 30))
    ax.set_xlim(0, 400)
    ax.set_xticks([0, 100, 200, 300, 400])
    ax.set_xlabel(LEAD_TENNIS)
    ax.set_ylabel("landing error SD, cm (log scale)")
    fs.direct_label(ax, items, dx_pt=4)
    fs.tag(ax, "simulation", x=0.03, y=0.96, ha="left", va="top")
    r200 = sp["baseline"]["sd_cm"]["200"] / sp["bls"]["sd_cm"]["200"]
    ptitle(name, ax, "a", f"Spin-aware fit cuts error {r200:.0f}{fs.TIMES} at 200{T}ms", x_in=0.06, y_in=2.34)

    ax = axb
    fs.hgrid(ax)
    items = []
    prec_all = []
    rec_min = []
    for k, col, lab in spec[1:]:
        if k not in sp or "pout95_recall" not in sp[k]:
            continue
        d = sp[k]["pout95_recall"]
        xs = sorted(int(x) for x in d)
        ys = [d[str(x)] for x in xs]
        prec_all += [sp[k]["pout95_precision"][str(x)] for x in xs]
        ax.plot(xs, ys, color=col, lw=fs.LW, zorder=4 if k != "ukf" else 3.5)
        items.append(dict(x=xs[-1], y=ys[-1], text=f"recall, {lab.split()[-1]}",
                          color=col if k != "ukf" else fs.ORANGE_LIGHT_TEXT))
        rec_min.append(min(ys))
    if prec_all and min(prec_all) == max(prec_all):  # INK is reserved for v2 / pre-registered: precision in grey
        ax.axhline(prec_all[0], color=G, lw=fs.LW_2, zorder=4)
        items.append(dict(x=400, y=prec_all[0], text="precision, both", color=fs.MUTED))
    ax.set_xlim(0, 400)
    ax.set_xticks([0, 100, 200, 300, 400])
    ax.set_ylim(0.84, 1.02)
    ax.set_yticks([0.85, 0.9, 0.95, 1.0])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:.2f}"))
    ax.set_xlabel(LEAD_TENNIS)
    ax.set_ylabel("OUT calls, precision and recall")
    fs.direct_label(ax, items, dx_pt=4)
    fs.tag(ax, "simulation", x=0.03, y=0.04, ha="left", va="bottom")
    rmin = min(rec_min)  # over every recall line drawn (UKF ends at 0.88), not only BLS
    pr = f"{prec_all[0]:g}" if prec_all and min(prec_all) == max(prec_all) else "high"
    ptitle(name, ax, "b", f"OUT calls: precision {pr}, recall \u2265 {fs.f(rmin, 2)}", x_in=3.24, y_in=2.34)
    return fs.save_fig(fig, name, OUT)


def A7() -> list[str]:
    """(a) market-side signal decay within a point; (b) the all-points replay on live-recorded books."""
    name = "figA7_decay_replay"
    fig = plt.figure(figsize=(W, 2.6))
    axa = fs.axes_in(fig, 0.56, 0.50, 2.45, 1.62)
    axb = fs.axes_in(fig, 3.80, 0.50, 1.95, 1.62)
    dj = load("results/decay/decay.json", name)
    ax = axa
    if not dj:
        fs.placeholder(ax, "results/decay/decay.json")
    else:
        sub = dj["tennis"]["subsets"]
        bins = ["0-0.25", "1-2", "2-3", "3-5", "5-10", "10-30", "baseline"]
        xpos = np.array([0, 1.7, 2.7, 3.7, 4.7, 5.7, 7.0])
        fs.hgrid(ax)
        fs.zero_line(ax)
        items = []
        for who, col, lab in (("fast", K, "fast tier"), ("others", G, "everyone else")):
            for per, ls, mfc, off in (("IS", fs.IS_LS, col, -0.09), ("burned_OOS", fs.OOS_LS, "white", 0.09)):
                cur = sub[per]["curves"][who]["net30"]
                ys = np.array([cur[b]["mean_c"] if cur[b]["mean_c"] is not None else np.nan for b in bins], float)
                lo = np.array([cur[b]["ci_c"][0] if cur[b].get("ci_c") else np.nan for b in bins], float)
                hi = np.array([cur[b]["ci_c"][1] if cur[b].get("ci_c") else np.nan for b in bins], float)
                x = xpos + off
                ax.plot(x[1:6], ys[1:6], color=col, ls=ls, lw=fs.LW_2, zorder=4)
                fs.whiskers(ax, x, ys, lo, hi, col, lw=0.7)
                ax.plot(x, ys, ls="none", marker="o", ms=3.0, mfc=mfc, mec=col, mew=0.9, zorder=5)
                if per == "IS":
                    items.append(dict(x=x[5], y=float(ys[5]), text=lab, color=col if col != G else fs.MUTED))
        ax.axvline(6.35, color=GRID_SEP, lw=0.6)
        ax.text(0.85, -0.25, f"0.25{ND}1{T}s not resolvable", ha="center", va="center", rotation=90,
                fontsize=fs.FS_SMALL, color=fs.MUTED, zorder=6, bbox=fs.knockout())
        ax.set_xticks(xpos)
        ax.set_xticklabels(["0", "1", "2", "3", "5", "10", "base"])
        ax.tick_params(axis="x", length=2)
        ax.set_xlim(-0.5, 7.5)
        ax.set_ylim(-2.2, 1.7)
        ax.set_yticks([-2, -1, 0, 1])
        fs.unicode_ticks(ax, "y")
        ax.set_xlabel("seconds since the score move (bin start)")
        ax.set_ylabel(f"net 30{T}s markout, {fs.CENT}/share")
        ax.text(5.7, 1.38, "fast tier", ha="center", va="center", fontsize=fs.FS_SMALL, color=K)
        ax.text(3.2, -1.75, "everyone else", ha="center", va="center", fontsize=fs.FS_SMALL, color=fs.MUTED)
    ptitle(name, ax, "a", "The fast tier stays ahead at every horizon", x_in=0.06, y_in=2.43)

    rp = load("results/replay/replay.json", name)
    ax = axb
    if not rp:
        fs.placeholder(ax, "results/replay/replay.json")
        ptitle(name, ax, "b", "Replay: pending", x_in=3.28, y_in=2.43)
        return fs.save_fig(fig, name, OUT)
    Vs = [0.0, 0.5, 1.0]
    keyv = {0.0: "0", 0.5: "0.5", 1.0: "1"}
    cols = {1: G, 2: K, 3: O}
    fs.hgrid(ax)
    fs.zero_line(ax)
    items = []
    for lag, off in ((1, -0.03), (2, 0.0), (3, 0.03)):
        ys, lo, hi = [], [], []
        for v in Vs:
            a = rp["cells"][f"V{keyv[v]}|lag{lag}|lead_model|florida"]["all"]
            ys.append(a["per_share_mark_c"])
            lo.append(a["per_share_mark_ci95_c"][0])
            hi.append(a["per_share_mark_ci95_c"][1])
        x = np.array(Vs) + off
        fs.whiskers(ax, x, ys, lo, hi, cols[lag], lw=0.8)
        ax.plot(x, ys, color=cols[lag], lw=fs.LW_2, marker="o", ms=3.2, mew=0, zorder=4)
        items.append(dict(x=x[-1], y=ys[-1], text=f"lag {lag}{T}s", color=cols[lag] if lag != 1 else fs.MUTED))
    ref = rp.get("sweep_reference", {}).get("headline_reading_OOS_c")
    if ref:
        ax.plot(Vs, [ref["V0"], ref["V0.5"], ref["V1"]], ls="none", marker="x", ms=4.5, mew=1.0, color=K, zorder=6)
        ax.annotate("sweep, OOS", xy=(0.0, ref["V0"]), xytext=(5, 0), textcoords="offset points", ha="left",
                    va="center", fontsize=fs.FS_SMALL, color=K)
    ax.set_xlim(-0.12, 1.12)
    ax.set_xticks(Vs)
    ax.set_xticklabels(["0", "0.5", "1"])
    ax.set_ylim(-2.0, 1.2)
    ax.set_yticks([-2, -1, 0, 1])
    fs.unicode_ticks(ax, "y")
    fs.direct_label(ax, items, dx_pt=10, leader=False)  # after the limits (display-space offsets)
    ax.set_xlabel("feed delay V, s")
    ax.set_ylabel(f"net {fs.CENT} per share, 95% CI")
    # the title speaks only for the 9 cells drawn (model leads, Florida network); the count over all 36 cells
    # (also London and zero lead) is a tag, computed from the same file
    drawn = [rp["cells"][f"V{keyv[v]}|lag{lag}|lead_model|florida"]["all"]["per_share_mark_c"] for v in Vs
             for lag in (1, 2, 3)]
    neg = sum(1 for c in rp["cells"].values() if c["all"]["per_share_mark_c"] < 0)
    fs.tag(ax, f"all settings: {neg} of {len(rp['cells'])} below zero", x=0.97, y=0.04)
    tb = ("Trading every point loses at every delay" if all(v < 0 for v in drawn)
          else "Replay of every point")
    ptitle(name, ax, "b", tb, x_in=3.28, y_in=2.43)
    return fs.save_fig(fig, name, OUT)


FIGS = {"F1": F1, "F2": F2, "F3": F3, "F4": F4, "F5": F5, "A1": A1, "A2": A2, "A3": A3,
        "A4": A4, "A5": A5, "A6": A6, "A7": A7}


# ============================================================================================== FIGURES.md
INFO = {  # figure key -> (role, figure name in the brief, replaces in results/paper/, notes for the integration pass)
    "F1": ("main", "Who sees the point first", "fig1_latency_cv",
           "a: dot-and-range on a log time axis from the end of the point. Our row = frame leaving our virtual camera "
           "to the call (own clip, WebRTC over loopback on one laptop, CV fed 10 frames/s; not glass-to-glass, no "
           "network): p50 dot, p99 whisker; 'call in 46 ms' is a different span from F4's 'order-ready in 54 ms' "
           "(capture to unsigned order, results/e2e). Vendor and published rows are 3 pt ranges; the stamp row is a "
           "dashed range because the stamp lag is unmeasured; the public stream is one measured median; score feeds are "
           "one range over the ESPN, Polymarket-sports and WTA medians of the lag behind the book (named left of it). "
           "The shaded column is the book's reprice, 0.84-1.98 s: the measured median 1.16 s book-before-stamp "
           "subtracted from the two stamp-lag readings (pre-registered 2.0 s, calibrated 3.14 s); F4a draws the same "
           "window. b: the six snapshot points of the frozen model on the held-out test games (summary.json), precision "
           "with Wilson 95% whiskers, right/called counts above, recall in grey. The former panel c (tennis spin "
           "landing error) duplicated A6a and was dropped."),
    "F2": ("main", "The edge exists", "fig2_speed_edge",
           "a: monthly net 30 s markout of the fast tier and everyone else (the axis), and copy-3-s-later held to "
           "resolution (a different horizon, said in its label, drawn thinner without markers); filled = IS, hollow = "
           "OOS; August is split at the OOS cut and each part sits mid-way through its own days. b: cumulative v2 P&L at "
           "the fast tier's fills; the OOS part is drawn at weekly closes (and the last day) so the dashes read; end "
           "labels are the exact daily totals. The stressed paths are re-drawn from the committed trade file by the "
           "loader in scripts/paper_figures.py, which asserts every total against cost_stress.json to the cent."),
    "F3": ("main", "What speed is worth", "fig3_signal_decay (panels a, b)",
           "Seed-mean curves; the band is the 2.5-97.5% range of the 20 seeds around the OOS curve only (four "
           "overlapping bands were unreadable). Circles on the zero line in a = break-even V of the seed-mean curve; "
           "dots in b = the 1 s base case; filled = IS, hollow = OOS. Dotted verticals: 0.5 s best licensed case, 1 s "
           "base, 3 s requirement, each label starting at its own line ('best licensed' one tier up). Numbers rounded "
           "half up (Sharpe 11.95 -> 12.0). Simulated: assumed feed latency (licensed feed not purchased); the caption "
           "must keep that label."),
    "F4": ("main", "Frame to trade", "(new)",
           "a: stage means from results/e2e/summary.json (means add up exactly to the total; the p50 total is 2,119 ms "
           "vs the 2,124 ms mean); 'order-ready in 54 ms' = capture to unsigned order (mean 54.2 ms, n = 24), not F1's "
           "46 ms call. The shaded book-reprice window is F1a's 0.84-1.98 s (e2e's own working band 1.0-1.5 s lies "
           "inside it). The CV stage was measured on a laptop; the L4 GPU figure in its label is the production "
           "reference quoted in the same file. Order not sent; feed 1 s simulated. b, c: CV strategy along the "
           "capacity study's size path (net cap 50-5,000 shares at $250 orders, 10 matches a day, half the stale "
           "depth); filled = IS, hollow = OOS; the larger circles = where the Sharpe halves; band in c = 20-seed range, "
           "calibrated OOS. b's title says 'erratic' because the calibrated OOS path is 37, 57, 67, 61, 44, 24, 168 "
           "$/day. Either part draws a marked placeholder if its input is missing."),
    "F5": ("main", "CV visual (optional)", "(new)",
           "Real match footage (OpenTTGames held-out test_2, CC BY-NC-SA 4.0: credit it in the caption). Cropped from "
           "the rendered still, below its top text box and above its call banner. 'Table end' = the source's "
           "'contact' (ball reaches the table end). The call is the frozen tier-0 model's; the arc, cone and the "
           "'LONG +74 cm, +/-81 cm (95%)' landing label are the display-only physics fit (its band reaches the table, "
           "so the figure does not rest the miss on it); the tag above the image says so."),
    "A1": ("appendix", "A1 restyled", "figA1_capacity",
           "a: v2 at scaled caps (optimistic at large size: no impact model); filled = IS, hollow = OOS. b: gross edge "
           "(grey tick), net of fees (grey dot) and after central fixed costs (coloured dot) with the low-high "
           "fixed-cost range as the bar; hollow on OOS rows; CV rows at V = 1 s, burned OOS."),
    "A2": ("appendix", "A2 restyled", "figA2_sweep_lags",
           "Seed means for the four stamp-lag readings; the key is ordered like the lines at the left edge."),
    "A3": ("appendix", "A3 restyled", "figA3_regime_month", "b: August split at the OOS cut, as in F2."),
    "A4": ("appendix", "Robustness forest plot", "figA4_forest",
           "Axis clipped at +-4 c (arrowheads mark a CI that runs past it; the exact CI is in the right column). "
           "Colour = family (grey earlier hypotheses and maker, black v2, orange CV / tier-0 / replay); hollow = an OOS "
           "test, filled = IS or not split (replay), as in every figure; a CI above zero is set in semibold in the "
           "right column."),
    "A5": ("appendix", "A5 restyled", "figA5_concentration", "Above 100% means the rest lost money."),
    "A6": ("appendix", "A6 restyled", "figA6_spin_sim",
           "Simulation only; a: log scale (the only copy of the tennis landing-error curves). b: precision in grey "
           "(INK is reserved for v2 / pre-registered); the recall bound in the title is the minimum over both lines "
           "drawn (UKF 0.88 at 400 ms)."),
    "A7": ("appendix", "All-points replay (+ signal decay)", "fig3_signal_decay (panels c, d)",
           "a: market-side markout by seconds since the score move; 0.25-1 s bins are empty in the data; filled = IS, "
           "hollow = OOS. b: replay of 9 live-recorded matches trading every point, Florida network, model leads (9 of "
           "the 36 cells); x = sweep OOS reference. The title speaks for the 9 cells drawn; the tag counts all 36 "
           "(London network and zero lead too) from replay.json."),
}
OLD_PROBLEMS = [
    "Every glyph at 11 pt in panels 1.6-1.9 in tall: tick labels, direct labels and titles crowd the data "
    "(Fig. 1a row labels take half the width; Fig. 3 has 4 panels at 0.3 of the page each).",
    "Collisions: 'book -1.2 s' arrow over the ladder (Fig. 1a); 'pre-registered lag' text through the curves and "
    "'lag 1 s' grey on grey (Fig. 3a, 3d); stacked Sharpe labels with leader lines (Fig. 3b); A1 legend on top of "
    "the bars, '(a)' clipped by the y label, value labels running below the axis; A6 'simulation' tag on the lines.",
    "Hatching (stamp, licensed video, 'not resolvable', CV bars in A1) and a stray blue (source bands, A2, A6) "
    "against the house palette; four overlapping seed bands in Fig. 3a/b turn brown.",
    "No takeaway titles: panels say what is plotted, not what it shows; IS/OOS encoded three different ways "
    "(filled/hollow, solid/dashed, 'filled = IS' notes in the axes).",
    "Legends inside the data (Fig. 2a, A1b, A6) and a legend above A2 instead of direct labels; A4 forest with "
    "a +-7.5 c axis set by one CI, so the informative rows are squeezed into the middle.",
    "Fig. 2a: August drawn twice with a sideways offset; A3b: OOS August/October bars a few pixels wide next to "
    "IS bars with no OOS shading; A5: 'filled = IS, hollow = OOS' note instead of labels.",
    "Main-text Fig. 3 mixes four stories (sweep $/day, Sharpe, market-side decay, replay); the end-to-end "
    "latency and capacity results have no figure.",
]


def write_figures_md(written: dict) -> Path:
    lines = ["# Paper figures, v2 house style", "",
             "Generated by `scripts/paper_figures_v2.py` (style: `docs/paper/figstyle.py`). Every figure is a vector "
             "PDF drawn at its printed size (6.5 in wide, Source Sans 3 at 8.5-9.5 pt, fonts embedded) plus a 300 dpi "
             "PNG. Numbers come only from the result files listed; nothing here re-runs a backtest. Captions stay in "
             "LaTeX; the honesty labels (simulated, assumed feed latency, paper only, order not sent) belong in them.",
             "", "Palette: orange #E8601C our CV strategy / pipeline; near-black #222 v2 or the pre-registered "
             "reading only; grey #8C8C8C others and any secondary series; light grey only as shading (OOS periods, "
             "source bands, seed bands), never as a line, marker or bar. IS solid, OOS dashed; filled marker = IS, "
             "hollow marker = OOS, with no other meaning anywhere. Time axes: 'seconds after the point ends'; lead "
             "axes: 'lead before the ball reaches the table end' (table tennis) or 'lead before the bounce' (tennis "
             "simulation). Numbers rounded half up, true minus signs, thin spaces before units.", "",
             "Rebuild: `nice -n 10 .venv/bin/python scripts/paper_figures_v2.py` (or `--only F1 A4`).", ""]
    for role, head in (("main", "## Main text"), ("appendix", "## Appendix")):
        lines += [head, ""]
        for k, f in FIGS.items():
            info = INFO.get(k)
            if not info or info[0] != role or k not in written:
                continue
            files = written[k]
            stem = Path(files[0]).stem
            lines.append(f"### {k}: {stem} ({info[1]})")
            lines.append("")
            lines.append("- Files: " + ", ".join(f"`{x}`" for x in files))
            lines.append(f"- Replaces: `{info[2]}`" if not info[2].startswith("(") else f"- Replaces: {info[2]}")
            for t in TITLES.get(stem, []):
                lines.append(f"- Panel title: {t}")
            srcs = SOURCES.get(stem, [])
            if srcs:
                lines.append("- Data: " + ", ".join(f"`{x}`" for x in srcs))
            lines.append(f"- Notes: {info[3]}")
            lines.append("")
    lines += ["## What was wrong with the previous figures (results/paper/*.png)", ""]
    lines += [f"- {x}" for x in OLD_PROBLEMS]
    lines.append("")
    out = OUT / "FIGURES.md"
    out.write_text("\n".join(lines))
    return out


def main(only: list[str] | None = None) -> dict:
    fs.apply()
    written = {}
    for k, f in FIGS.items():
        if only and k not in only:
            continue
        written[k] = f()
        print(f"{k}: {', '.join(written[k])}")
    if not only:
        print(f"index: {write_figures_md(written).relative_to(ROOT)}")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    main(ap.parse_args().only)
