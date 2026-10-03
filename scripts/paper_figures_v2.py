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
O, K, G, GL = fs.ORANGE, fs.INK, fs.GREY, fs.GREY_LIGHT
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


def F1() -> list[str]:
    name = "fig1_race"
    fig = plt.figure(figsize=(W, 3.2))
    # ---------------------------------------------------------------- (a) the information race
    axa = fs.axes_in(fig, 1.78, 2.04, 3.22, 0.90)
    wr = pf.webrtc_latency()
    note_src(name, "results/webrtc/latency.json")
    sw = load("results/tier0/latency_sweep.json", name)
    m1 = pf.latency_m1()
    note_src(name, "research/v2/latency/results.json")
    pub = pf.public_stream_s()
    note_src(name, "results/home_stream/sub_second_routes.json")
    src = {s["key"]: s for s in sw["sources"]} if sw else {}

    rows = []  # label, kind, lo, hi, points, value text, source text
    if wr:
        rows.append(("Our pipeline: WebRTC + CV", "ours", wr["p50"] / 1e3, wr["p99"] / 1e3, None,
                     f"{wr['p50']:.0f}{T}ms", "measured, p50"))
    else:
        rows.append(("Our pipeline: WebRTC + CV", "pending", None, None, None, "pending", ""))
    if "official_feed" in src:
        lo, hi = src["official_feed"]["band_s"]
        rows.append(("Venue tablet, official stamp", "unmeasured", lo, hi, None, rng(lo, hi), "unmeasured"))
    if "betting_video" in src:
        lo, hi = src["betting_video"]["band_s"]
        rows.append(("Licensed video", "vendor", lo, hi, None, rng(lo, hi), "vendor-stated"))
    if "tv" in src:
        lo, hi = src["tv"]["band_s"]
        rows.append(("TV broadcast", "vendor", lo, hi, None, rng(lo, hi), "published"))
    if pub:
        rows.append(("Public WebRTC stream", "measured", pub, pub, None, f"{pub:.1f}{T}s", "measured"))
    if m1:
        pts = [-m1[k]["lead_vs_book_s"]["median"] for k in ("espn:game", "pm_sports:game", "wta:point")]
        rows.append(("Score feeds (ESPN, PM, WTA)", "measured3", min(pts), max(pts), pts,
                     rng(min(pts), max(pts)), "measured"))

    ax = axa
    x0, x1 = 0.01, 100
    fs.log_time_axis(ax, ticks=(0.01, 0.1, 0.5, 1, 3, 10, 60), lim=(x0, x1),
                     label="seconds after the bounce (log scale)")
    n = len(rows)
    ax.set_ylim(n - 0.45, -1.15)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r[0] for r in rows])
    ax.tick_params(axis="y", length=0, pad=6)
    for t, r in zip(ax.get_yticklabels(), rows):
        if r[1] in ("ours", "pending"):
            t.set_color(O)
            t.set_fontweight("semibold")
    ax.spines["left"].set_visible(False)
    # the book reprices ~1.2 s before the official stamp: with the stamp lag unmeasured, that puts the reprice
    # 0.8 s (pre-registered 2.0 s lag) to 2.0 s (calibrated 3.14 s lag) after the bounce
    if m1:
        b = m1["book_vs_official_T_s"]["median"]
        pre, cal = stamp_lags()
        r_lo, r_hi = pre + b, (cal if cal else pre) + b
        ax.axvspan(r_lo, r_hi, color=fs.SHADE, lw=0, zorder=0.3)
        ax.text(np.sqrt(r_lo * r_hi), -0.72, f"book reprices, {abs(b):.1f}{T}s before the stamp", ha="center",
                va="center", fontsize=fs.FS_SMALL, color=fs.MUTED, zorder=6)
    h = 0.50
    for i, (lab, kind, lo, hi, pts, vtxt, stxt) in enumerate(rows):
        if kind == "pending":
            ax.text(x0 * 1.3, i, "pending: results/webrtc/latency.json", va="center", fontsize=fs.FS_SMALL,
                    color=O, style="italic")
            continue
        if kind == "ours":
            ax.barh(i, lo - x0, left=x0, height=h, color=O, zorder=3)
            ax.plot([lo, hi], [i, i], color=O, lw=1.0, zorder=3)
            ax.plot([hi, hi], [i - 0.16, i + 0.16], color=O, lw=1.0, zorder=3)
        elif kind == "measured":
            ax.barh(i, lo - x0, left=x0, height=h, color=G, zorder=3)
        elif kind == "measured3":
            ax.barh(i, lo - x0, left=x0, height=h, color=G, zorder=3)
            ax.plot([lo, hi], [i, i], color=fs.MUTED, lw=0.9, zorder=4)
            for p in pts:
                ax.plot([p], [i], marker="o", ms=3.0, color=fs.MUTED, mew=0, zorder=5)
        elif kind in ("vendor", "unmeasured"):
            solid = "#D0D0D0" if kind == "vendor" else "white"
            ax.barh(i, lo - x0, left=x0, height=h, color=solid, zorder=3,
                    edgecolor="none" if kind == "vendor" else G, lw=0.0 if kind == "vendor" else 0.6,
                    ls=(0, (2.5, 1.5)))
            ax.barh(i, hi - lo, left=lo, height=h, color="#E9E9E9" if kind == "vendor" else "white", zorder=3,
                    edgecolor=G if kind == "unmeasured" else "#C4C4C4", lw=0.6,
                    ls=(0, (2.5, 1.5)) if kind == "unmeasured" else "-")
        # right-hand value column (outside the data)
        ax.annotate(vtxt, xy=(1.0, i), xycoords=("axes fraction", "data"), xytext=(8, 0),
                    textcoords="offset points", ha="left", va="center", fontsize=fs.FS,
                    color=O if kind == "ours" else K, annotation_clip=False)
        ax.annotate(stxt, xy=(1.0, i), xycoords=("axes fraction", "data"), xytext=(46, 0),
                    textcoords="offset points", ha="left", va="center", fontsize=fs.FS_SMALL, color=fs.MUTED,
                    annotation_clip=False)
    ax.tick_params(axis="x", length=2.6)
    ta = (f"Our pipeline adds {wr['p50']:.0f}{T}ms; the feeds add seconds" if wr
          else "Who sees the point first")
    ptitle(name, ax, "a", ta, x_in=0.06, y_in=3.04)

    # ---------------------------------------------------------------- (b) early out-calls on real footage
    axb = fs.axes_in(fig, 0.47, 0.47, 2.25, 0.80)
    ax = axb
    p = ROOT / "results/tracking/test_precision_vs_lead_snapshot.csv"
    tr = load("results/tracking/summary.json", name)
    if not p.exists() or not tr:
        fs.placeholder(ax, "results/tracking/test_precision_vs_lead_snapshot.csv")
    else:
        note_src(name, "results/tracking/test_precision_vs_lead_snapshot.csv")
        d = pd.read_csv(p)
        d = d[d.lead_ms <= 200 + 1e-9]
        fs.hgrid(ax)
        fs.add_ci_band(ax, d.lead_ms, d.prec_lo95, d.prec_hi95, O, alpha=0.14, step="post")
        ax.plot(d.lead_ms, d.precision, color=O, lw=fs.LW, drawstyle="steps-post", zorder=4)
        ax.plot(d.lead_ms, d.recall, color=K, lw=fs.LW_2, drawstyle="steps-post", zorder=4)
        ax.set_xlim(0, 200)
        ax.set_ylim(0, 1.24)
        ax.set_xticks([0, 50, 100, 150, 200])
        ax.set_yticks([0, 0.5, 1.0])
        fs.unicode_ticks(ax)
        ax.set_xlabel("call lead before contact (ms)")
        s50 = tr["early_call"]["precision_recall_test_snapshot"]["50ms"]
        ax.plot([50], [s50["precision"]], marker="o", ms=3.6, color=O, mec="white", mew=0.7, zorder=6)
        ax.text(57, 1.13, f"{s50['tp']} of {s50['tp'] + s50['fp']} right at 50{T}ms", ha="left", va="center",
                fontsize=fs.FS_SMALL, color=O)
        last = d.iloc[-1]
        fs.direct_label(ax, [dict(x=200, y=float(last.precision), text="precision", color=O),
                             dict(x=200, y=float(last.recall), text="recall", color=K)], dx_pt=4)
    ptitle(name, ax, "b", "Out-calls stay precise up to 200 ms early", x_in=0.06, y_in=1.44)

    # ---------------------------------------------------------------- (c) tennis spin model, simulation
    axc = fs.axes_in(fig, 3.78, 0.47, 1.95, 0.80)
    ax = axc
    sp = load("results/spin/tennis/key_numbers.json", name)
    if not sp:
        fs.placeholder(ax, "results/spin/tennis/key_numbers.json")
    else:
        fs.hgrid(ax)
        items = []
        for k, col, lab, lw in (("baseline", G, "no spin", fs.LW_2), ("bls", O, "spin-aware", fs.LW)):
            d = sp[k]["sd_cm"]
            xs = sorted(int(x) for x in d)
            ys = [d[str(x)] for x in xs]
            ax.plot(xs, ys, color=col, lw=lw, zorder=4)
            items.append(dict(x=xs[-1], y=ys[-1], text=f"{lab}\n{ys[-1]:.1f}{T}cm", color=col))
        ax.set_xlim(0, 400)
        ax.set_ylim(0, 18)
        ax.set_xticks([0, 100, 200, 300, 400])
        ax.set_yticks([0, 5, 10, 15])
        ax.set_xlabel("lead before the bounce (ms)")
        ax.set_ylabel("landing error, cm")
        fs.direct_label(ax, items, dx_pt=4)
        fs.tag(ax, "simulation", x=0.03, y=0.96, ha="left", va="top")
    ptitle(name, ax, "c", "Spin model cuts tennis landing error", x_in=3.30, y_in=1.44)
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
    axa = fs.axes_in(fig, 0.50, 0.40, 2.10, 1.78)
    axb = fs.axes_in(fig, 3.98, 0.40, 1.62, 1.78)
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
        series = [("fast_net30_c", K, "Fast tier", fs.LW), ("others_net30_c", G, "Everyone else", fs.LW_2),
                  ("copy_3s_later_net_to_resolution_c", GL, f"Copy 3{T}s later", fs.LW_2)]
        fs.hgrid(ax)
        x_is = [month_mid(m["month"], is0, oos0) for m in A["IS"]["months"]]
        x_oos = [month_mid(m["month"], oos0, oos1) for m in A["OOS"]["months"]]
        items = []
        for key, col, lab, lw in series:
            y_is = [m[key] for m in A["IS"]["months"]]
            y_oos = [m[key] for m in A["OOS"]["months"]]
            ax.plot(x_is, y_is, color=col, lw=lw, ls=fs.IS_LS, marker="o", ms=2.8, mew=0, zorder=4)
            ax.plot([x_is[-1]] + x_oos, [y_is[-1]] + y_oos, color=col, lw=lw, ls=fs.OOS_LS, zorder=4)
            ax.plot(x_oos, y_oos, ls="none", marker="o", ms=2.8, mfc="white", mec=col, mew=0.9, zorder=5)
            items.append(dict(x=x_oos[-1], y=y_oos[-1], text=lab, color=col if col != GL else fs.MUTED))
        ax.set_xlim(is0 - pd.Timedelta(days=4), oos1 + pd.Timedelta(days=4))
        fs.oos_shade(ax, oos0)
        fs.zero_line(ax)
        ax.set_ylim(-3.2, 3.2)
        ax.set_yticks([-3, -2, -1, 0, 1, 2, 3])
        fs.unicode_ticks(ax, "y")
        ax.set_ylabel(f"net {fs.CENT} per share")
        month_axis(ax, [pd.Timestamp(m) for m in ("2025-12-01", "2026-02-01", "2026-04-01", "2026-06-01",
                                                   "2026-08-01", "2026-10-01")])
        fs.direct_label(ax, items, dx_pt=5)
    ptitle(name, ax, "a", "Only the fast tier earns; copying late loses", x_in=0.06, y_in=2.42)

    # ---------------------------------------------------------------- (b) v2 cumulative P&L, costs doubled
    ax = axb
    if not paths:
        fs.placeholder(ax, "results/lowloss/daily.csv")
    else:
        base, stressed, _cs = paths
        fs.hgrid(ax)
        lines = [("base", base["is_eval"], base["burned_oos"], K, fs.LW, "Base")]
        if stressed:
            lines.append(("fee_x2", stressed[("is_eval", "fee_x2")], stressed[("burned_oos", "fee_x2")], G,
                          fs.LW_2, f"Fees {fs.TIMES}2"))
            lines.append(("costs_x2", stressed[("is_eval", "costs_x2")], stressed[("burned_oos", "costs_x2")], GL,
                          fs.LW_2, f"All costs {fs.TIMES}2"))
        items = []
        for _k, s_is, s_oos, col, lw, lab in lines[::-1]:
            c1 = s_is.cumsum() / 1e3
            c2 = (s_oos.cumsum() / 1e3) + c1.iloc[-1]
            ax.plot(c1.index, c1.values, color=col, lw=lw, ls=fs.IS_LS, zorder=4)
            ax.plot([c1.index[-1]] + list(c2.index), [c1.iloc[-1]] + list(c2.values), color=col, lw=lw,
                    ls=fs.OOS_LS, zorder=4)
            items.append(dict(x=c2.index[-1], y=float(c2.iloc[-1]),
                              text=f"{lab}\nOOS {fs.usd(s_oos.sum(), 1, sign=True, k=True)}",
                              color=col if col != GL else fs.MUTED))
        x_lo = base["is_eval"].index.min()
        ax.set_xlim(x_lo - pd.Timedelta(days=3), oos1 + pd.Timedelta(days=3))
        fs.oos_shade(ax, oos0)
        fs.zero_line(ax)
        ax.set_ylim(-3, 48)
        ax.set_yticks([0, 10, 20, 30, 40])
        ax.set_ylabel("cumulative net P&L, $k")
        month_axis(ax, [pd.Timestamp(m) for m in ("2026-02-01", "2026-04-01", "2026-06-01", "2026-08-01",
                                                   "2026-10-01")])
        fs.direct_label(ax, items, dx_pt=5, bounds=(0.0, 1.1))
    ptitle(name, ax, "b", "v2 earns; doubled costs erase the OOS gain", x_in=3.42, y_in=2.42)
    return fs.save_fig(fig, name, OUT)


# ============================================================================================== F3
REF_LINES = ((0.5, "best licensed", "right"), (1.0, "base", "left"), (3.0, "requirement", "left"))


def ref_verticals(ax, labels: bool = True) -> None:
    """Dotted verticals at 0.5 s (best licensed case), 1 s (base case) and 3 s (requirement), labelled just above
    the frame so the labels never sit on data."""
    for x, lab, ha in REF_LINES:
        fs.vref(ax, x, color=K, lw=0.8)
        if labels:
            ax.annotate(lab, xy=(x, 1.0), xycoords=("data", "axes fraction"), xytext=(-2.5 if ha == "right" else 2.5,
                        1.5), textcoords="offset points", ha=ha, va="bottom", fontsize=fs.FS_SMALL, color=K,
                        annotation_clip=False)


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
    for (r, p), x in bes.items():
        col = O if r == "tournament_lagcal" else K
        ax.plot([x], [0], ls="none", marker="o", ms=4.2, mfc="white", mec=col, mew=1.1, zorder=7)
    bc = [bes[("tournament_lagcal", p)] for p in ("IS", "burned_OOS")]
    bp = [bes[("tournament", p)] for p in ("IS", "burned_OOS")]
    # break-even key in the empty upper right (open circles on the zero line)
    ax.text(3.6, 150, "break-even V", ha="left", va="center", fontsize=fs.FS_SMALL, color=fs.MUTED)
    ax.text(3.6, 118, f"{min(bc):.1f}{ND}{max(bc):.1f}{T}s", ha="left", va="center", fontsize=fs.FS, color=O)
    ax.text(3.6, 86, f"{min(bp):.1f}{ND}{max(bp):.1f}{T}s", ha="left", va="center", fontsize=fs.FS, color=K)
    lab_cal = readings[0][2].replace(" lag", "\nlag")
    lab_pre = readings[1][2].replace(" lag", "\nlag")
    ax.text(0.058, 236, lab_cal, ha="left", va="center", fontsize=fs.FS, color=O, zorder=8, linespacing=1.1)
    ax.text(0.058, -50, lab_pre, ha="left", va="center", fontsize=fs.FS, color=K, zorder=8, linespacing=1.1)
    lo_be, hi_be = min(bes.values()), max(bes.values())
    ptitle(name, ax, "a", f"Profit hits zero at {lo_be:.1f}{ND}{hi_be:.1f}{T}s of delay", x_in=0.06, y_in=2.55)

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
    ptitle(name, ax, "b", f"Sharpe at the 1{T}s base: {lo1:.1f}{ND}{hi1:.1f}", x_in=3.24, y_in=2.55)
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
        band = e2e.get("budget_with_1s_simulated_feed", {}).get("reprice_band_ms")
        if band:
            ax.axvspan(band[0] / 1e3, band[1] / 1e3, color=fs.SHADE, lw=0, zorder=0.3)
            ax.annotate("book reprices", xy=(sum(band) / 2e3, 1.0), xycoords=("data", "axes fraction"),
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
                ax.barh(i, x1 - x0, left=x0, height=h, color=G if kind == "rule" else GL, lw=0, zorder=3)
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
        ax.set_xlabel("seconds after the point")
        ptitle(name, ax, "a", f"Our pipeline is {ours:.0f}{T}ms of a {total:.1f}{T}s path", x_in=0.06, y_in=3.06)

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
                ax.plot(D.capital_usd, D[col_m], ls="none", marker="o", ms=2.4, color=col, mew=0, zorder=5)
        for p, h in half.items():
            yv = h["pnl_per_day_usd"] if col_m == "pnl_per_day_usd" else h["sharpe_ann"]
            ax.plot([h["capital_usd"]], [yv], ls="none", marker="o", ms=4.6, mfc="white", mec=O, mew=1.1, zorder=7)
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
    ptitle(name, ax, "b", "Out of sample, dollars flatten with size", x_in=0.06, y_in=1.52)
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
    m = re.search(r"calls MISS (\d+) ms before", caps.get(Path(still).name, ""))
    ms = m.group(1) if m else re.search(r"_(\d+)ms", still).group(1)
    ptitle(name, ax, "", f"Frozen model calls the miss {ms}{T}ms before contact", x_in=0.0, y_in=img_h + 0.08)
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
    for per, off, mfc, ls in (("IS", -0.09, K, fs.IS_LS), ("OOS", 0.09, "white", fs.OOS_LS)):
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
        pts = [v for v in (gross, net, after) if v is not None]
        ax.plot([min(pts), max(pts)], [i, i], color=GL, lw=0.8, zorder=2)
        ax.plot([net - fixed["high"], net - fixed["low"]], [i, i], color=col, lw=0.9, zorder=3)
        if gross is not None:
            ax.plot([gross], [i], ls="none", marker="o", ms=4.0, color="#C9C9C9", mew=0, zorder=4)
        ax.plot([net], [i], ls="none", marker="o", ms=4.0, color=G, mew=0, zorder=4)
        ax.plot([after], [i], ls="none", marker="o", ms=4.6, color=col, mew=0, zorder=5)
        ax.annotate(fs.usd(after, 0, sign=True), xy=(after, i), xytext=(0, -5.5), textcoords="offset points",
                    ha="center", va="top", fontsize=fs.FS_SMALL, color=col)
        pos += after > 0
        if i == 0:
            for v, t in ((gross, "gross"), (net, "net"), (after, "after costs")):
                if v is not None:
                    ax.annotate(t, xy=(v, i), xytext=(0, 5), textcoords="offset points", ha="center",
                                va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED)
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
                    va="center", fontsize=fs.FS_SMALL, color=col if col != fs.ORANGE_LIGHT else "#D9824F")
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
    ptitle(name, ax, "a", "Edge falls as the venue's protection falls", x_in=0.06, y_in=2.34)

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
            ax.axhline(i - 0.5, color=GRID_SEP, lw=0.6, zorder=0)
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
        ax.plot([v], [i], ls="none", marker="o", ms=4.4, mfc=c if passed else "white", mec=c, mew=1.1, zorder=5)
        ci = f" [{fs.num(lo, 2)}, {fs.num(hi, 2)}]" if lo is not None else ""
        ax.annotate(f"{fs.num(v, 2, sign=True)}{ci}", xy=(1.0, i), xycoords=("axes fraction", "data"),
                    xytext=(10, 0), textcoords="offset points", ha="left", va="center", fontsize=fs.FS_SMALL,
                    color=K if passed else fs.MUTED, annotation_clip=False)
    ax.axvline(0, color=ZERO_DARK, lw=0.8, zorder=1)
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
    title = ("Only v2 at the fast tier's fills clears zero" if pos and all(r[0] == "v2" for r in pos)
             else "Every test on one axis")
    ptitle(name, ax, "", title, x_in=0.06, y_in=H - 0.16)
    return fs.save_fig(fig, name, OUT)


GRID_SEP = "#D9D9D9"
ZERO_DARK = "#8C8C8C"


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
    ptitle(name, ax, "", f"Five copied wallets carry {w5:.0f}% of v2's in-sample P&L", x_in=0.06, y_in=2.24)
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
                          color=col if k != "ukf" else "#D9824F"))
    fs.log_time_axis(ax, which="y", ticks=(0.1, 0.3, 1, 3, 10, 30), lim=(0.1, 30))
    ax.set_xlim(0, 400)
    ax.set_xticks([0, 100, 200, 300, 400])
    ax.set_xlabel("lead before the bounce (ms)")
    ax.set_ylabel("landing error SD, cm (log scale)")
    fs.direct_label(ax, items, dx_pt=4)
    fs.tag(ax, "simulation", x=0.03, y=0.96, ha="left", va="top")
    r200 = sp["baseline"]["sd_cm"]["200"] / sp["bls"]["sd_cm"]["200"]
    ptitle(name, ax, "a", f"Spin-aware fit cuts error {r200:.0f}{fs.TIMES} at 200{T}ms", x_in=0.06, y_in=2.34)

    ax = axb
    fs.hgrid(ax)
    items = []
    prec_all = []
    for k, col, lab in spec[1:]:
        if k not in sp or "pout95_recall" not in sp[k]:
            continue
        d = sp[k]["pout95_recall"]
        xs = sorted(int(x) for x in d)
        ys = [d[str(x)] for x in xs]
        prec_all += [sp[k]["pout95_precision"][str(x)] for x in xs]
        ax.plot(xs, ys, color=col, lw=fs.LW, zorder=4 if k != "ukf" else 3.5)
        items.append(dict(x=xs[-1], y=ys[-1], text=f"recall, {lab.split()[-1]}",
                          color=col if k != "ukf" else "#D9824F"))
    if prec_all and min(prec_all) == max(prec_all):
        ax.axhline(prec_all[0], color=K, lw=fs.LW_2, zorder=4)
        items.append(dict(x=400, y=prec_all[0], text="precision", color=K))
    ax.set_xlim(0, 400)
    ax.set_xticks([0, 100, 200, 300, 400])
    ax.set_ylim(0.84, 1.02)
    ax.set_yticks([0.85, 0.9, 0.95, 1.0])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:.2f}"))
    ax.set_xlabel("lead before the bounce (ms)")
    ax.set_ylabel("OUT calls, precision and recall")
    fs.direct_label(ax, items, dx_pt=4)
    fs.tag(ax, "simulation", x=0.03, y=0.04, ha="left", va="bottom")
    rmin = min(sp["bls"]["pout95_recall"].values())
    pr = f"{prec_all[0]:g}" if prec_all and min(prec_all) == max(prec_all) else "high"
    ptitle(name, ax, "b", f"OUT calls: precision {pr}, recall \u2265 {rmin:.2f}", x_in=3.24, y_in=2.34)
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
                fontsize=fs.FS_SMALL - 0.5, color=fs.MUTED)
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
    fs.direct_label(ax, items, dx_pt=10)  # after the limits: offsets are computed in display space
    ax.set_xlabel("feed delay V, s")
    ax.set_ylabel(f"net {fs.CENT} per share, 95% CI")
    neg = sum(1 for c in rp["cells"].values() if c["all"]["per_share_mark_c"] < 0)
    ptitle(name, ax, "b", f"Replay of every point loses in {neg} of {len(rp['cells'])} settings", x_in=3.28, y_in=2.43)
    return fs.save_fig(fig, name, OUT)


FIGS = {"F1": F1, "F2": F2, "F3": F3, "F4": F4, "F5": F5, "A1": A1, "A2": A2, "A3": A3,
        "A4": A4, "A5": A5, "A6": A6, "A7": A7}


# ============================================================================================== FIGURES.md
INFO = {  # figure key -> (role, figure name in the brief, replaces in results/paper/, notes for the integration pass)
    "F1": ("main", "Who sees the point first", "fig1_latency_cv",
           "a: horizontal bars from the bounce on a log time axis; our row = frame leaving our virtual camera to the "
           "call (WebRTC loopback, own clip, CV fed 10 frames/s), p50 bar and p99 whisker; vendor/published rows are "
           "ranges (solid to the low end, light box to the high end); the stamp row is dashed because the stamp lag is "
           "unmeasured; score feeds are the ESPN, Polymarket-sports and WTA medians of the lead behind the book. The "
           "shaded column is the book's reprice implied by the measured median book-minus-stamp time and the two "
           "stamp-lag readings (pre-registered 2.0 s, calibrated 3.14 s). b: snapshot rule, held-out test games, Wilson "
           "95% band on precision. c: simulation only (no tennis video)."),
    "F2": ("main", "The edge exists", "fig2_speed_edge",
           "a: monthly net 30 s markout of the fast tier and everyone else, and copy-3-s-later net to resolution "
           "(as in alpha.json); August is split at the OOS cut and each part sits mid-way through its own days. "
           "b: cumulative v2 P&L at the fast tier's fills; the stressed paths are re-drawn from the committed trade file "
           "by the loader in scripts/paper_figures.py, which asserts every total against cost_stress.json to the cent."),
    "F3": ("main", "What speed is worth", "fig3_signal_decay (panels a, b)",
           "Seed-mean curves; the band is the 2.5-97.5% range of the 20 seeds around the OOS curve only (four "
           "overlapping bands were unreadable). Open circles = break-even V of the seed-mean curve; dots in b = the "
           "1 s base case. Dotted verticals: 0.5 s best licensed case, 1 s base, 3 s requirement. Simulated: assumed "
           "feed latency (licensed feed not purchased); the caption must keep that label."),
    "F4": ("main", "Frame to trade", "(new)",
           "a: stage means from results/e2e/summary.json (means add up exactly to the total; the p50 total is 2,119 ms "
           "vs the 2,124 ms mean). The CV stage was measured on a laptop; the L4 GPU figure in its label is the "
           "production reference quoted in the same file. Order not sent; feed 1 s simulated. b, c: CV strategy along "
           "the capacity study's size path (net cap 50-5,000 shares at $250 orders, 10 matches a day, half the stale "
           "depth); open circles = where the Sharpe halves; band in c = 20-seed range, calibrated OOS. Either part "
           "draws a marked placeholder if its input is missing."),
    "F5": ("main", "CV visual (optional)", "(new)",
           "Real match footage (OpenTTGames held-out test_2, CC BY-NC-SA 4.0: credit it in the caption). Cropped from "
           "the rendered still, below its top text box and above its call banner; the arc, cone and landing label are "
           "the physics fit for display, the call itself is the frozen tier-0 model."),
    "A1": ("appendix", "A1 restyled", "figA1_capacity",
           "a: v2 at scaled caps (optimistic at large size: no impact model). b: gross edge, net of fees, and after "
           "central fixed costs with the low-high fixed-cost range as the bar; CV rows at V = 1 s, burned OOS."),
    "A2": ("appendix", "A2 restyled", "figA2_sweep_lags",
           "Seed means for the four stamp-lag readings; the key is ordered like the lines at the left edge."),
    "A3": ("appendix", "A3 restyled", "figA3_regime_month", "b: August split at the OOS cut, as in F2."),
    "A4": ("appendix", "Robustness forest plot", "figA4_forest",
           "Axis clipped at +-4 c (arrowheads mark a CI that runs past it; the exact CI is in the right column). "
           "Colour = family (grey earlier hypotheses and maker, black v2, orange CV / tier-0 / replay); filled = CI "
           "above zero."),
    "A5": ("appendix", "A5 restyled", "figA5_concentration", "Above 100% means the rest lost money."),
    "A6": ("appendix", "A6 restyled", "figA6_spin_sim", "Simulation only; a: log scale."),
    "A7": ("appendix", "All-points replay (+ signal decay)", "fig3_signal_decay (panels c, d)",
           "a: market-side markout by seconds since the score move; 0.25-1 s bins are empty in the data. b: replay of "
           "9 live-recorded matches trading every point, Florida network, model leads; x = sweep OOS reference."),
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
             "reading; grey #8C8C8C others; light grey shading OOS and source bands. IS solid, OOS dashed.", "",
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
