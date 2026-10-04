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


F1_LEADS = (0, 25, 50, 100, 150, 200, 250, 300)   # ms: the snapshot grid of summary.json, continued to 300 ms


def early_call_points(name: str):
    """Precision / recall of the frozen model's early MISS calls on the held-out test games, at F1_LEADS.

    The full curve to 300 ms is results/tracking/test_precision_vs_lead_snapshot.csv (1/120 s steps); the six
    snapshot points in summary.json are the same numbers and are checked against it, so the axis is not cut at
    200 ms (precision is 0.67 from 225 to 283 ms and 0.5 at 300 ms)."""
    csv = ROOT / "results/tracking/test_precision_vs_lead_snapshot.csv"
    tr = load("results/tracking/summary.json", name)
    snap = ((tr or {}).get("early_call") or {}).get("precision_recall_test_snapshot") or {}
    if not csv.exists():
        if not snap:
            return None
        rows = []
        for k, d in sorted(snap.items(), key=lambda kv: int(kv[0][:-2])):
            rows.append(dict(lead=int(k[:-2]), precision=d["precision"], recall=d["recall"], tp=d["tp"], fp=d["fp"],
                             lo=d["precision_wilson95"][0], hi=d["precision_wilson95"][1]))
        return rows
    note_src(name, "results/tracking/test_precision_vs_lead_snapshot.csv")
    C = pd.read_csv(csv)
    rows = []
    for x in F1_LEADS:
        m = C[(C.lead_ms - x).abs() < 1e-6]
        if m.empty:
            continue
        r_ = m.iloc[0]
        rows.append(dict(lead=x, precision=float(r_.precision), recall=float(r_.recall), tp=int(r_.tp), fp=int(r_.fp),
                         lo=float(r_.prec_lo95), hi=float(r_.prec_hi95)))
        s_ = snap.get(f"{x}ms")
        if s_:  # the CSV and the frozen snapshot are the same evaluation
            assert (s_["tp"], s_["fp"]) == (rows[-1]["tp"], rows[-1]["fp"]), (x, s_, rows[-1])
    return rows


def engine_call_points(name: str):
    """The live causal engine's early MISS calls on the held-out test games, by lead (results/engine/
    online_vs_offline.json, run fp16_cl_fuse_compile_b1_realtime, A_engine_calls.online): the deployable numbers."""
    ov = load("results/engine/online_vs_offline.json", name)
    try:
        on = ov["runs"]["fp16_cl_fuse_compile_b1_realtime"]["A_engine_calls"]["online"]
        n_miss = ov["runs"]["fp16_cl_fuse_compile_b1_realtime"]["A_engine_calls"]["miss_first_call_lead_ms"]["n_miss"]
    except (TypeError, KeyError):
        return None, None
    rows = []
    for k, d in sorted(on.items(), key=lambda kv: int(kv[0][:-2])):
        rows.append(dict(lead=int(k[:-2]), precision=d["precision"], recall=d["recall"], tp=d["tp"], fp=d["fp"]))
    return rows, n_miss


def F1() -> list[str]:
    name = "fig1_race"
    H = 3.78
    fig = plt.figure(figsize=(W, H))
    AX_L, AX_W = 1.42, 3.22
    axa = fs.axes_in(fig, AX_L, 2.32, AX_W, 1.02)
    # ---------------------------------------------------------------- (a) the information race
    wr = pf.webrtc_latency()
    note_src(name, "results/webrtc/latency.json")
    sw = load("results/tier0/latency_sweep.json", name)
    m1 = pf.latency_m1()
    note_src(name, "research/v2/latency/results.json")
    pub = pf.public_stream_s()
    note_src(name, "results/home_stream/sub_second_routes.json")
    src = {s_["key"]: s_ for s_ in sw["sources"]} if sw else {}
    pre, cal = stamp_lags()
    rows = []  # (row label, kind, lo, hi, extra, status)
    # our row: frame to order-ready from the end-to-end run (results/e2e) when it exists, else the WebRTC
    # frame-to-call run (results/webrtc); INTEGRATION_TODO P-10 source order
    e2e = load("results/e2e/summary.json", name)
    ours_ms = (e2e or {}).get("our_pipeline_frame_to_order_ready_ms")
    if ours_ms:
        wr = {"p50": ours_ms["p50"], "p99": ours_ms["p99"], "what": "order"}
    elif wr:
        wr = dict(wr, what="call")
    if wr:
        rows.append(("Our pipeline", "ours", wr["p50"] / 1e3, wr["p99"] / 1e3, None, "measured, own clip"))
    else:
        rows.append(("Our pipeline", "pending", None, None, None, ""))
    band = tuple(src["official_feed"]["band_s"]) if "official_feed" in src else None
    rows.append(("Official stamp", "stamp", pre, cal if cal else pre, band, "unmeasured"))
    if "betting_video" in src:
        lo, hi = src["betting_video"]["band_s"]
        rows.append(("Licensed video", "range", lo, hi, None, "vendor-stated"))
    if "tv" in src:
        lo, hi = src["tv"]["band_s"]
        rows.append(("TV broadcast", "range", lo, hi, None, "published"))
    if pub:
        rows.append(("Public stream", "point", pub, pub, None, "measured"))
    if m1:
        v = [-m1[k]["lead_vs_book_s"]["median"] for k in ("espn:game", "pm_sports:game", "wta:point")]
        rows.append(("Score feeds", "range", min(v), max(v), None, "measured"))
    ax = axa
    x0, x1 = 0.03, 120
    fs.log_time_axis(ax, ticks=(0.05, 0.1, 0.5, 1, 3, 10, 60), lim=(x0, x1), label=f"{TIME_AFTER} (log scale)")
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
        ax.annotate(f"book reprices ({fs.f(abs(b))}{T}s before the stamp)", xy=(np.sqrt(r_lo * r_hi), 1.0),
                    xycoords=("data", "axes fraction"), xytext=(0, 2.0), textcoords="offset points", ha="center",
                    va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED, annotation_clip=False)
    for i, (lab, kind, lo, hi, extra, status) in enumerate(rows):
        if kind == "pending":
            ax.text(x0 * 1.3, i, "pending: results/webrtc/latency.json", va="center", fontsize=fs.FS_SMALL,
                    color=O, style="italic")
            continue
        left = False
        if kind == "ours":
            ax.plot([lo, hi], [i, i], color=O, lw=1.0, zorder=4, solid_capstyle="butt")
            ax.plot([lo], [i], ls="none", marker="o", ms=4.6, color=O, mew=0, zorder=5)
            val = (hi, f"{wr['p50']:.0f}{T}ms p50", O)
        elif kind == "stamp":
            if extra:
                ax.fill_between(list(extra), [i - 0.3] * 2, [i + 0.3] * 2, color=fs.BAND, lw=0, zorder=1)
            ax.plot([lo, hi], [i, i], color=G, lw=1.6, ls=(0, (2.2, 1.6)), zorder=4)
            val = (max(hi, extra[1] if extra else hi), f"{lo:.1f}{ND}{hi:g}{T}s", K)
        elif kind == "range":
            ax.plot([lo, hi], [i, i], color=G, lw=3.0, zorder=4, solid_capstyle="butt")
            left = hi > 20
            val = ((lo if left else hi), rng(lo, hi), K)
        else:  # point
            ax.plot([lo], [i], ls="none", marker="o", ms=4.6, color=G, mew=0, zorder=5)
            val = (lo, f"{fs.f(lo)}{T}s", K)
        ax.annotate(val[1], xy=(val[0], i), xytext=(-5 if left else 5, 0), textcoords="offset points",
                    ha="right" if left else "left", va="center", fontsize=fs.FS_SMALL, color=val[2], zorder=6)
        ax.annotate(status, xy=(1.0, i), xycoords=("axes fraction", "data"), xytext=(8, 0),
                    textcoords="offset points", ha="left", va="center", fontsize=fs.FS_SMALL, color=fs.MUTED,
                    annotation_clip=False)
    ta = ((f"Our order is ready in {wr['p50']:.0f}{T}ms; feeds take seconds" if wr["what"] == "order"
           else f"We call in {wr['p50']:.0f}{T}ms; feeds take seconds") if wr else "Who sees the point first")
    ptitle(name, ax, "a", ta, x_in=0.06, y_in=H - 0.18)

    # ---------------------------------------------------------------- (b) early out-calls: live engine vs offline
    axb = fs.axes_in(fig, AX_L, 0.52, AX_W, 0.98)
    ax = axb
    P = early_call_points(name)
    E, n_miss = engine_call_points(name)
    if not P or not E:
        fs.placeholder(ax, "results/engine/online_vs_offline.json")
        ptitle(name, ax, "b", "Early out-calls: pending", x_in=0.06, y_in=1.66)
        return fs.save_fig(fig, name, OUT)
    fs.hgrid(ax)
    ax.plot([d["lead"] for d in P], [d["recall"] for d in P], color=G, lw=fs.LW_2, zorder=3)
    ax.plot([d["lead"] for d in P], [d["recall"] for d in P], ls="none", marker="o", ms=3.4, color=G, mew=0,
            zorder=4)
    ax.plot([d["lead"] for d in E], [d["recall"] for d in E], color=O, lw=fs.LW, zorder=5)
    ax.plot([d["lead"] for d in E], [d["recall"] for d in E], ls="none", marker="o", ms=4.2, color=O, mew=0,
            zorder=6)
    for d in E:  # right / called above the live-engine points where the offline line leaves room
        if d["lead"] not in (0, 50, 200):
            continue
        ax.annotate(f"{d['tp']}/{d['tp'] + d['fp']}", xy=(d["lead"], d["recall"]), xytext=(0, 4),
                    textcoords="offset points", ha="center", va="bottom", fontsize=fs.FS_SMALL, color=O, zorder=7)
    p1 = next(d for d in P if d["lead"] == 25) if any(d["lead"] == 25 for d in P) else P[1]
    ax.annotate("offline evaluation (look-ahead feature)", xy=(p1["lead"], p1["recall"]), xytext=(8, 0),
                textcoords="offset points", ha="left", va="center", fontsize=fs.FS_SMALL, color=fs.MUTED, zorder=7)
    ax.annotate("live causal engine", xy=(120, 0.205), ha="left", va="bottom", fontsize=fs.FS, color=O, zorder=7)
    ax.set_xlim(-12, 312)
    ax.set_ylim(0, 0.68)
    ax.set_xticks([0, 50, 100, 150, 200, 250, 300])
    ax.set_yticks([0, 0.2, 0.4, 0.6])
    fs.unicode_ticks(ax)
    ax.set_xlabel(LEAD_TT)
    ax.set_ylabel("misses called")
    tp0 = max(d["tp"] for d in E)
    fp_all = sum(d["fp"] for d in E)
    tb = (f"Live engine: {tp0} of {n_miss} misses called early, none wrong" if fp_all == 0
          else f"Live engine: {tp0} of {n_miss} misses called early")
    ptitle(name, ax, "b", tb, x_in=0.06, y_in=1.66)
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
    fig = plt.figure(figsize=(W, 2.14))   # 2.38 in before the integration pass (page budget); text sizes unchanged
    PW = 1.85  # both panels the same width over the same dates, so months and OOS shading line up across the row
    axa = fs.axes_in(fig, 0.50, 0.40, PW, 1.32)
    axb = fs.axes_in(fig, 3.80, 0.40, PW, 1.32)
    al = load("results/alpha/alpha.json", name)
    paths = pf.v2_daily_paths()
    note_src(name, "results/lowloss/daily.csv", "results/v2/causal.json", "results/v2/cost_stress.json",
             "data/v2_trades_is_oos.parquet")
    oos0 = oos1 = None
    if paths:
        oos0 = paths[0]["burned_oos"].index.min()
        oos1 = paths[0]["burned_oos"].index.max()
    is0 = None
    if al:
        A = al["A_source"]
        is0 = pd.Timestamp(A["IS"]["months"][0]["month"] + "-01")
        if oos0 is None:  # no daily file: the OOS starts at the first OOS month
            oos0 = pd.Timestamp(A["OOS"]["months"][0]["month"] + "-01")
            oos1 = pd.Timestamp(A["OOS"]["months"][-1]["month"] + "-01") + pd.offsets.MonthEnd(0)
    if is0 is None and paths:
        is0 = paths[0]["is_eval"].index.min()
    xlim = (is0 - pd.Timedelta(days=4), oos1 + pd.Timedelta(days=4)) if is0 is not None else None
    ticks = [m for m in pd.date_range(is0, oos1 + pd.Timedelta(days=4), freq="2MS")] if is0 is not None else []

    # ---------------------------------------------------------------- (a) monthly markout by who trades
    ax = axa
    if not al:
        fs.placeholder(ax, "results/alpha/alpha.json")
    else:
        # INK here is the fast tier because v2 is measured at the fast tier's own fills (b's INK line)
        series = [("fast_net30_c", K, "Fast tier\n(v2 copies it)"), ("others_net30_c", G, "Everyone else")]
        fs.hgrid(ax)
        x_is = [month_mid(m["month"], is0, oos0) for m in A["IS"]["months"]]
        x_oos = [month_mid(m["month"], oos0, oos1) for m in A["OOS"]["months"]]
        items = []
        for key, col, lab in series:
            y_is = [m[key] for m in A["IS"]["months"]]
            y_oos = [m[key] for m in A["OOS"]["months"]]
            ax.plot(x_is, y_is, color=col, lw=fs.LW if col == K else fs.LW_2, ls=fs.IS_LS, zorder=4)
            ax.plot([x_is[-1]] + x_oos, [y_is[-1]] + y_oos, color=col, lw=fs.LW if col == K else fs.LW_2,
                    ls=fs.OOS_LS, zorder=4)
            ax.plot(x_is, y_is, ls="none", marker="o", ms=2.8, color=col, mew=0, zorder=5)  # filled = IS
            ax.plot(x_oos, y_oos, ls="none", marker="o", ms=2.8, mfc="white", mec=col, mew=0.9, zorder=5)
            items.append(dict(x=x_oos[-1], y=y_oos[-1], text=lab, color=col if col != G else fs.MUTED))
        # copy-3-s-later is held to resolution (a different horizon from the 30 s markout), so it is shown as
        # its print-weighted IS and OOS means only (alpha.json headline; the file gives no CI for it), thin
        cp = al.get("headline", {}).get("copy_3s_later_c") or {
            p: A[p]["print_weighted"]["copy_3s_later_net_to_resolution_c"] for p in ("IS", "OOS")}
        ax.plot([is0, oos0], [cp["IS"]] * 2, color=G, lw=0.9, ls=fs.IS_LS, zorder=3.5)
        ax.plot([oos0, oos1], [cp["OOS"]] * 2, color=G, lw=0.9, ls=fs.OOS_LS, zorder=3.5)
        ax.annotate(f"copy 3{T}s later\n(to resolution)", xy=(is0, cp["IS"]), xytext=(1.5, -2.5),
                    textcoords="offset points", ha="left", va="top", fontsize=fs.FS_SMALL, color=fs.MUTED,
                    linespacing=1.1, zorder=6)
        ax.set_xlim(*xlim)
        fs.oos_shade(ax, oos0)
        fs.zero_line(ax)
        ax.set_ylim(-3.15, 2.8)   # room under the copy-3-s line for its two-line label at the 2.14 in height
        ax.set_yticks([-2, -1, 0, 1, 2])
        fs.unicode_ticks(ax, "y")
        ax.set_ylabel(f"net 30{T}s markout, {fs.CENT}/share")
        month_axis(ax, ticks)
        # each label at its own line end (Everyone else at -1.86, not lifted towards the gap)
        fs.direct_label(ax, items, dx_pt=5, leader=False, pad_pt=2.0)
    ptitle(name, ax, "a", "Only the fast tier earns; copying late loses", x_in=0.06, y_in=1.96)

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
        if xlim is None:
            xlim = (base["is_eval"].index.min() - pd.Timedelta(days=4), oos1 + pd.Timedelta(days=4))
            ticks = list(pd.date_range(base["is_eval"].index.min(), oos1, freq="2MS"))
        ax.set_xlim(*xlim)
        fs.oos_shade(ax, oos0)
        fs.zero_line(ax)
        ax.set_ylim(-3, 48)
        ax.set_yticks([0, 10, 20, 30, 40])
        ax.set_ylabel("cumulative net P&L, $k")
        month_axis(ax, ticks)
        fs.direct_label(ax, items, dx_pt=5, bounds=(0.0, 1.1), leader=False)
    ptitle(name, ax, "b", "v2 earns; doubled costs erase the OOS gain", x_in=3.24, y_in=1.96)
    return fs.save_fig(fig, name, OUT)


# ============================================================================================== F3
REF_LINES = ((0.5, "best case", 2), (1.0, "base", 1), (3.0, "requirement", 1))
TIER_PT = 13.5   # vertical distance between two tiers of reference labels at 11 pt


def ref_verticals(ax, labels: bool = True) -> None:
    """Dotted verticals at the three feed-latency scenarios: 0.5 s (licensed feed, best case), 1 s (base case) and
    3 s (the organiser's requirement). Every label starts at its own line, above the frame; the 0.5 s label is one
    tier higher because it runs across the 1 s line, and each line is continued up to its own label."""
    if labels:  # grey 0.6 pt with muted labels: INK belongs to the pre-registered curve
        fs.vref_labelled(ax, REF_LINES, tier_pt=TIER_PT)
    else:
        for x, _lab, _tier in REF_LINES:
            fs.vref(ax, x)


def sweep_reading(reading: str, period: str) -> pd.DataFrame | None:
    """Seed-mean $/day and Sharpe against V for any reading of the video/own120 sweep (latency_sweep.csv)."""
    df = pf.load("results/tier0/latency_sweep.csv")
    if df is None:
        return None
    d = df[(df.source == "video") & (df.cv == "own120") & (df.reading == reading) & (df.period == period)]
    return d.drop_duplicates("x_s").sort_values("x_s")


SCEN_VS = (0.5, 1.0, 3.0)   # the three feed-latency scenarios of Table 3


def video_band(ax, sw: dict, y: float, label_dy: float = 3.0) -> None:
    """The licensed-video source band (vendor-stated 0.5-8 s) as a thin bar in the empty top of the panel, labelled
    just below its left end; never shading over the data."""
    src = {s_["key"]: s_ for s_ in sw.get("sources", [])}
    if "betting_video" not in src:
        return
    lo, hi = src["betting_video"]["band_s"]
    ax.plot([lo, hi], [y, y], color=fs.BAND, lw=4.0, solid_capstyle="butt", zorder=2)
    ax.annotate("licensed video (vendor)", xy=(lo, y), xytext=(1.0, -label_dy), textcoords="offset points", ha="left",
                va="top", fontsize=fs.FS_SMALL, color=fs.MUTED, zorder=6, path_effects=fs.halo(3.0))


def F3() -> list[str]:
    """What speed is worth: net $/day of the CV strategy against the feed delay V, in sample (a) and out of sample (b),
    at the pre-registered and the post hoc stamp-lag readings and the post hoc inference read point by point."""
    name = "fig3_speed_value"
    H = 2.68
    fig = plt.figure(figsize=(W, H))
    AXW, AXH, B = 2.48, 1.33, 0.55
    axa = fs.axes_in(fig, 0.80, B, AXW, AXH)
    axb = fs.axes_in(fig, 3.86, B, AXW, AXH)
    sw = load("results/tier0/latency_sweep.json", name)
    note_src(name, "results/tier0/latency_sweep.csv")
    pre, cal = stamp_lags()
    spec = [("tournament", K, "pre-registered", fs.LW), ("tournament_lagcal", O, "post hoc", fs.LW),
            ("stamp_calibrated", fs.ORANGE_LIGHT, "post hoc, per point", fs.LW_2)]
    cur = {(r, p): sweep_reading(r, p) for r, _c, _l, _w in spec for p in ("IS", "burned_OOS")}
    if sw is None or any(v is None or v.empty for v in cur.values()):
        for ax, letter in ((axa, "a"), (axb, "b")):
            fs.placeholder(ax, "results/tier0/latency_sweep.csv")
            ptitle(name, ax, letter, "pending", dx_in=-0.5)
        return fs.save_fig(fig, name, OUT)
    be = sw["breakeven_video_delay"]
    for ax, period, letter, ylim, yt, strip_y, x_in in (
            (axa, "IS", "a", (-100, 262), [0, 100, 200], 240, 0.06),
            (axb, "burned_OOS", "b", (-75, 172), [0, 50, 100, 150], 158, 3.30)):
        oos = period == "burned_OOS"
        fs.log_time_axis(ax, ticks=(0.1, 0.5, 1, 3, 10, 60), lim=(0.05, 60), label="feed delay V, s (log scale)")
        fs.hgrid(ax)
        for r, col, _lab, lw in spec[::-1]:
            c = cur[(r, period)]
            c = c[c.x_s >= 0.05]
            ax.plot(c.x_s, c.pnl_per_day_usd, color=col, lw=lw, ls=fs.OOS_LS if oos else fs.IS_LS,
                    zorder=4 if col != fs.ORANGE_LIGHT else 3.6)
            if r != "stamp_calibrated":  # the three scenarios of Table 3: filled = IS, hollow = OOS
                for v in SCEN_VS:
                    yv = float(c[np.isclose(c.x_s, v)].pnl_per_day_usd.iloc[0])
                    ax.plot([v], [yv], ls="none", marker="o", ms=4.0, mfc="white" if oos else col, mec=col,
                            mew=1.0, zorder=6)
        ref_verticals(ax)
        fs.zero_line(ax)
        video_band(ax, sw, strip_y)
        ax.set_ylim(*ylim)
        ax.set_yticks(yt)
        ax.yaxis.set_major_formatter(FuncFormatter(kusd))
        ax.set_ylabel("net $ per day" if not oos else "")
        # direct labels, each in free space next to its own line: pre-registered just above its curve at the left
        # end; post hoc right of its drop near 1.2 s; the per-point reading under its flat tail
        cpre = cur[("tournament", period)]
        ccal = cur[("tournament_lagcal", period)]
        m_ = (cpre.x_s >= 0.05) & (cpre.x_s <= 0.6)
        y_pre = float(cpre[m_].pnl_per_day_usd.max())
        ax.annotate("pre-registered", xy=(0.056, y_pre), xytext=(0, 1.2), textcoords="offset points", ha="left",
                    va="bottom", fontsize=fs.FS, color=K, zorder=8, path_effects=fs.halo(3.0))
        y_cal = float(ccal[np.isclose(ccal.x_s, 1.15)].pnl_per_day_usd.iloc[0])
        ax.annotate(f"post hoc, L = {cal:g}{T}s", xy=(1.3, y_cal), xytext=(0, 4), textcoords="offset points",
                    ha="left", va="bottom", fontsize=fs.FS, color=O, zorder=8, path_effects=fs.halo(3.0))
        ax.annotate("post hoc, per point", xy=(1.15, -17), xytext=(0, -5), textcoords="offset points", ha="left",
                    va="top", fontsize=fs.FS_SMALL, color=fs.ORANGE_LIGHT_TEXT, zorder=8, path_effects=fs.halo(3.0))
        b_pre = be["tournament"][period]["breakeven_V_s_seed_mean_curve"]
        b_cal = be["tournament_lagcal"][period]["breakeven_V_s_seed_mean_curve"]
        what = "OOS" if oos else "IS"
        ptitle(name, ax, letter, f"{what}: zero profit at {fs.f(b_pre)}{ND}{fs.f(b_cal)}{T}s of delay", x_in=x_in,
               y_in=H - 0.22)
    return fs.save_fig(fig, name, OUT)


# ============================================================================================== F4
def kusd(v, _pos=None) -> str:
    a = abs(v)
    body = f"${a / 1e3:g}k" if a >= 1e3 else f"${a:g}"
    return (M if v < 0 else "") + body


def e2e_stages(e2e: dict) -> list[tuple[str, float, str, str]] | None:
    """(row label, mean ms, kind, value label) per timeline row from results/e2e/summary.json. Means are used
    because they add up exactly to the mean total (medians do not); our three stages are one row whose label
    breaks them down."""
    st = {r["stage"]: r["ms"]["mean"] for r in e2e.get("stage_ms", [])}
    need = ["sender: frame into encoder", "encode + WHIP + MediaMTX + RTP in", "H.264 decode + handoff",
            "prep + queue + detector", "tracker + features + classifier", "strategy rule (fair value, edge)",
            "risk check", "unsigned order built", "network one-way (RTT/2)", "venue order delay (secondsDelay)"]
    if any(k not in st for k in need):
        return None
    feed = e2e.get("budget_with_1s_simulated_feed", {}).get("feed_simulated_ms")
    video = st[need[0]] + st[need[1]] + st[need[2]]
    cv = st[need[3]] + st[need[4]]
    order = st[need[5]] + st[need[6]] + st[need[7]]
    rows = []
    if feed is not None:
        rows.append(("licensed feed", float(feed), "assumed", f"{feed / 1e3:g}{T}s, simulated"))
    rows += [("our pipeline", video + cv + order, "ours",
              f"{video + cv + order:.0f}{T}ms: video {video:.0f}, CV {cv:.0f}, order {order:.1f}"),
             ("network", st[need[8]], "other", f"{st[need[8]]:.0f}{T}ms (RTT/2)"),
             ("venue delay", st[need[9]], "rule", f"{st[need[9]] / 1e3:g}{T}s (venue rule)")]
    return rows


def cap_path(A: pd.DataFrame, base: dict, rk: str, p: str, order: int) -> pd.DataFrame:
    D = A[(A.reading == rk) & (A.period == p) & (A.growth == 1.0) & (A.phi == base["phi"]) &
          (A.coverage.astype(str) == str(base["coverage"])) & (A.order_cap == order)]
    return D.sort_values("net_cap")


def F4() -> list[str]:
    """Frame to trade: the measured pipeline, a simulated 1 s feed, the network and the venue hold against the 3 s bar
    (one panel; the capacity panels are the appendix figure A8, figA8_capacity)."""
    name = "fig4_frame_to_trade"
    H = 1.66
    fig = plt.figure(figsize=(W, H))
    # ---------------------------------------------------------------- frame-to-executable timeline
    axa = fs.axes_in(fig, 1.22, 0.40, 4.98, 0.84)
    ax = axa
    e2e = load("results/e2e/summary.json", name)
    rows = e2e_stages(e2e) if e2e else None
    if not rows:
        fs.placeholder(ax, "results/e2e/summary.json", "pipeline latency timeline")
        ptitle(name, ax, "", "Frame to trade: pending the end-to-end run", x_in=0.06, y_in=H - 0.18)
    else:
        ms = np.array([r[1] for r in rows])
        starts = np.concatenate([[0.0], np.cumsum(ms)[:-1]]) / 1e3
        ends = np.cumsum(ms) / 1e3
        total = ends[-1]
        n = len(rows)
        ax.set_xlim(0, 3.25)
        ax.set_ylim(n - 0.45, -0.55)
        rw = reprice_window()  # the same window as F1a (0.84-1.98 s)
        if rw:
            ax.axvspan(rw[0], rw[1], color=fs.SHADE, lw=0, zorder=0.3)
            ax.annotate("book reprices", xy=((rw[0] + rw[1]) / 2, 1.0), xycoords=("data", "axes fraction"),
                        xytext=(0, 2.0), textcoords="offset points", ha="center", va="bottom",
                        fontsize=fs.FS_SMALL, color=fs.MUTED, annotation_clip=False)
        req = e2e.get("budget_with_1s_simulated_feed", {}).get("requirement_ms")
        if req:  # reference: grey dotted, muted label (INK is reserved for v2 / pre-registered)
            fs.vref(ax, req / 1e3)
            ax.annotate(f"{req / 1e3:g}{T}s requirement", xy=(req / 1e3, 1.0), xycoords=("data", "axes fraction"),
                        xytext=(0, 2.0), textcoords="offset points", ha="center", va="bottom",
                        fontsize=fs.FS_SMALL, color=fs.MUTED, annotation_clip=False)
        ax.axvline(total, color=O, lw=0.9, zorder=2.6)  # our pipeline's total: orange, solid
        ax.annotate(f"executable {fs.f(total, 2)}{T}s", xy=(total, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(0, 2.0), textcoords="offset points", ha="center", va="bottom", fontsize=fs.FS_SMALL,
                    color=O, annotation_clip=False)
        h = 0.58
        for i, ((lab, v, kind, txt), x0, x1) in enumerate(zip(rows, starts, ends)):
            if kind == "ours":
                ax.barh(i, max(x1 - x0, 0.012), left=x0, height=h, color=O, lw=0, zorder=3)
            elif kind == "assumed":
                ax.barh(i, x1 - x0, left=x0, height=h, color="white", edgecolor=G, lw=0.8, ls=(0, (2.5, 1.5)),
                        zorder=3)
            else:
                ax.barh(i, x1 - x0, left=x0, height=h, color=G, lw=0, zorder=3)
            ax.annotate(txt, xy=(max(x1, x0 + 0.012), i), xytext=(4, 0), textcoords="offset points", ha="left",
                        va="center", fontsize=fs.FS_SMALL, color=O if kind == "ours" else K, zorder=6,
                        path_effects=fs.halo(3.0))
        ax.set_yticks(range(n))
        ax.set_yticklabels([r[0] for r in rows])
        for t, r in zip(ax.get_yticklabels(), rows):
            if r[2] == "ours":
                t.set_color(O)
                t.set_fontweight("semibold")
        ax.tick_params(axis="y", length=0, pad=6)
        ax.spines["left"].set_visible(False)
        ax.set_xticks([0, 0.5, 1, 1.5, 2, 2.5, 3])
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:g}{T}s" if v else "0"))
        ours = sum(r[1] for r in rows if r[2] == "ours")
        ptitle(name, ax, "", f"Frame to executable order in {fs.f(total, 2)}{T}s; our part {ours:.0f}{T}ms",
               x_in=0.06, y_in=H - 0.18)

    return fs.save_fig(fig, name, OUT)


def A8() -> list[str]:
    """Capital capacity of the CV strategy at the 1 s base case: (a) Sharpe and (b) $/day against capital."""
    name = "figA8_capacity"
    H = 2.30
    fig = plt.figure(figsize=(W, H))
    # ---------------------------------------------------------------- (b, c) capacity vs capital
    axb = fs.axes_in(fig, 0.86, 0.55, 2.26, 1.36)
    axc = fs.axes_in(fig, 4.02, 0.55, 2.26, 1.36)
    capj = load("results/capacity/capacity.json", name)
    cells = ROOT / "results/capacity/cv_cells.csv"
    yt = H - 0.18
    if not capj or not cells.exists():
        for ax, letter in ((axb, "b"), (axc, "c")):
            fs.placeholder(ax, "results/capacity/cv_cells.csv", "capacity vs size")
        ptitle(name, axb, "a", "Capacity: pending", x_in=0.06, y_in=yt)
        ptitle(name, axc, "b", "Capacity: pending", x_in=3.28, y_in=yt)
        return fs.save_fig(fig, name, OUT)
    note_src(name, "results/capacity/cv_cells.csv")
    A = pd.read_csv(cells)
    base = capj["grid"]["base"]
    path_order = 250 if 250 in set(A.order_cap) else int(A.order_cap.min())
    pre, cal = stamp_lags()
    readings = [("prereg", K), ("lagcal", O)]
    half = {}
    for p in ("IS", "burned_OOS"):
        h_ = capj["answers"]["cv"].get(f"lagcal|phi{base['phi']:g}|cov{base['coverage']}|g1|{p}", {})
        if h_.get("at_half_sharpe", {}).get("reached_within_grid"):
            half[p] = h_
    cmax = max(cap_path(A, base, rk, p, path_order).capital_usd.max() for rk, _c in readings for p in ("IS", "burned_OOS"))
    ymax_usd = max(cap_path(A, base, rk, p, path_order).pnl_per_day_usd.max() for rk, _c in readings
                   for p in ("IS", "burned_OOS"))
    xt = [t_ for t_ in (1e4, 3e4, 1e5, 3e5) if t_ <= cmax * 1.25]
    for ax, col_m in ((axb, "sharpe_ann"), (axc, "pnl_per_day_usd")):
        fs.hgrid(ax)
        for rk, col in readings:
            for p, ls in (("IS", fs.IS_LS), ("burned_OOS", fs.OOS_LS)):
                D = cap_path(A, base, rk, p, path_order)
                ax.plot(D.capital_usd, D[col_m], color=col, ls=ls, lw=fs.LW, zorder=4)
        fs.zero_line(ax)
        ax.set_xscale("log")
        ax.set_xlim(3.0e3, max(1.3e5, cmax * 1.25))
        ax.xaxis.set_major_locator(FixedLocator(xt))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(kusd))
        ax.set_xlabel("capital (log scale)")
    # (b) Sharpe: the half-Sharpe points of the post hoc reading (filled IS, hollow OOS)
    ax = axb
    for p, h_ in half.items():
        hh = h_["at_half_sharpe"]
        ax.plot([hh["capital_usd"]], [hh["sharpe_ann"]], ls="none", marker="o", ms=5.0,
                mfc=O if p == "IS" else "white", mec=O, mew=1.2, zorder=7)
    ax.set_ylim(-4, 17)
    ax.set_yticks([0, 5, 10, 15])
    fs.unicode_ticks(ax, "y")
    ax.set_ylabel("Sharpe")
    ax.annotate(f"post hoc, L = {cal:g}{T}s", xy=(3.2e3, 15.6), ha="left", va="center", fontsize=fs.FS, color=O,
                zorder=8)
    ax.annotate("pre-registered", xy=(3.4e3, -2.0), ha="left", va="center", fontsize=fs.FS, color=K, zorder=8)
    caps = sorted(h_["at_half_sharpe"]["capital_usd"] for h_ in half.values())
    tb = (f"Sharpe halves by {kusd(round(caps[0], -3))}{ND}{kusd(round(caps[-1], -3))} (post hoc)" if caps
          else "Sharpe falls with size")
    ptitle(name, ax, "a", tb, x_in=0.06, y_in=yt)
    # (c) $/day against the fixed data costs (grey dotted references)
    ax = axc
    fx = capj["answers"]["cv"][f"lagcal|phi{base['phi']:g}|cov{base['coverage']}|g1|burned_OOS"]["fixed_costs"]
    if "licence_low" in fx:  # the cheapest data stack (results/financials), labelled in the free space left of the data
        yv = fx["licence_low"]["cost_usd_per_day"]
        ax.axhline(yv, color=fs.REF, lw=fs.LW_VREF, ls=fs.DOT_LS, zorder=2.5)
        ax.annotate(f"cheapest data\nstack, {fs.usd(yv)}/day", xy=(3.2e3, yv), xytext=(0, 2.0),
                    textcoords="offset points", ha="left", va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED,
                    zorder=6, linespacing=0.95)
    top_ = fs.nice_ceil(ymax_usd * 1.08, 100)
    ax.set_ylim(-0.17 * top_, top_)
    ax.set_yticks([v_ for v_ in (0, 100, 200, 300, 400, 500) if v_ < top_])
    ax.yaxis.set_major_formatter(FuncFormatter(kusd))
    ax.set_ylabel("net $ per day")
    need = []
    for p in ("IS", "burned_OOS"):
        f_ = capj["answers"]["cv"][f"lagcal|phi{base['phi']:g}|cov{base['coverage']}|g1|{p}"]["fixed_costs"]
        if f_.get("licence_low", {}).get("capital_needed_usd"):
            need.append(f_["licence_low"]["capital_needed_usd"])
    tc = (f"The cheapest data stack needs {kusd(round(min(need), -3))}{ND}{kusd(round(max(need), -3))}" if need
          else "Fixed costs decide")
    ptitle(name, ax, "b", tc, x_in=3.28, y_in=yt)
    return fs.save_fig(fig, name, OUT)




# ============================================================================================== F5
def F5() -> list[str]:
    """One real still with the predicted arc (already rendered by scripts/cv_showcase.py), cropped clean of the
    on-screen panels (no top text box, no call banner, no HUD) and labelled directly in the house type: the ball at
    the call, its tracked path and the display-only predicted arc. The still's own 'LONG +74 cm' and 'END LINE' tags
    stay (they are part of the rendered frame)."""
    name = "fig5_cv_still"
    from PIL import Image
    still = "results/viz/stills/still_01_tt_call_408ms.png"
    caps = load("results/viz/stills/captions.json", name) or {}
    p = ROOT / still
    # px in the 1920 x 1080 still: below the top text box (ends at y 135), above the call banner (starts at y 700);
    # 90 px trimmed at each side so the printed height reaches the house minimum (2.4 in with the title strip)
    crop = (90, 138, 1810, 700)
    w_px, h_px = crop[2] - crop[0], crop[3] - crop[1]
    img_h = W * h_px / w_px
    top = 0.30
    fig = plt.figure(figsize=(W, img_h + top))
    ax = fs.axes_in(fig, 0.0, 0.0, W, img_h)
    if not p.exists():
        fs.placeholder(ax, still)
        ptitle(name, ax, "", "CV still: pending", x_in=0.0, y_in=img_h + 0.09)
        return fs.save_fig(fig, name, OUT)
    note_src(name, still)
    im = Image.open(p).convert("RGB").crop(crop)
    ax.imshow(np.asarray(im), interpolation="none", aspect="auto")
    ax.set_axis_off()
    cap = caps.get(Path(still).name, "")
    m = re.search(r"calls MISS (\d+) ms before", cap)
    ms = m.group(1) if m else re.search(r"_(\d+)ms", still).group(1)

    def px(x, y):  # original-still pixel -> cropped-image pixel (the axes' data coordinates)
        return x - crop[0], y - crop[1]

    box = dict(boxstyle="square,pad=0.2", facecolor="#0B1030", edgecolor="none", alpha=0.72)
    lab = dict(fontsize=fs.FS_SMALL, color="white", zorder=8, bbox=box, linespacing=1.1)
    # 'contact' in the source means the ball reaching the table end, so the title says that; the frame shows the
    # offline rule's call (408 ms, look-ahead feature); the live causal engine called the same flight later
    ax.annotate("ball at the call", xy=px(700, 268), xytext=px(560, 200), ha="right", va="center",
                arrowprops=dict(arrowstyle="-", color="white", lw=0.6, shrinkA=0, shrinkB=2), **lab)
    ax.annotate("tracked path", xy=px(560, 350), xytext=px(560, 440), ha="center", va="center",
                arrowprops=dict(arrowstyle="-", color="white", lw=0.6, shrinkA=0, shrinkB=2), **lab)
    ax.annotate("predicted arc (display only)", xy=px(1180, 289), xytext=px(1190, 180), ha="center", va="center",
                arrowprops=dict(arrowstyle="-", color="white", lw=0.6, shrinkA=0, shrinkB=2), **lab)
    live = None
    ov = load("results/engine/online_vs_offline.json", name)
    try:
        for f_ in ov["runs"]["fp16_cl_fuse_compile_b1_realtime"]["flights_called_or_miss"]:
            mt = re.search(r"test_(\d+)_.*flight (\d+)|test_(\d+)", still)
            if f_.get("video") == "test_2" and int(f_.get("f_net", -1)) == 2819:
                live = f_.get("lead_engine_call_ms")
    except (TypeError, KeyError):
        live = None
    t5 = (f"Held-out miss called {ms}{T}ms early offline, {live:.0f}{T}ms live" if live
          else f"Held-out miss called {ms}{T}ms early (offline rule)")
    ptitle(name, ax, "", t5, x_in=0.0, y_in=img_h + 0.09)
    return fs.save_fig(fig, name, OUT)


# ============================================================================================== appendix
def A1() -> list[str]:
    """v2 net edge by size and the $/day cost ladder (gross -> net of fees -> after fixed costs)."""
    name = "figA1_capacity_costs"
    fig = plt.figure(figsize=(W, 2.95))
    axa = fs.axes_in(fig, 0.66, 0.92, 2.05, 1.52)
    axb = fs.axes_in(fig, 4.30, 0.92, 2.05, 1.52)
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
        ax.annotate(per, xy=(xs[0] + off, y[0]), xytext=(-7, 0), textcoords="offset points",
                    ha="right", va="center", fontsize=fs.FS_SMALL, color=K, path_effects=fs.halo(3.0))
    ax.set_xlim(-1.15, len(sizes) - 0.5)
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
    ptitle(name, ax, "a", f"v2{fs.RSQUO}s OOS edge fades as size grows", x_in=0.06, y_in=2.74)

    ax = axb
    fixed = v2f["cost"]["daily"]
    rows = []
    for per, lab in (("IS", "v2, IS"), ("OOS", "v2, OOS")):
        w = v2f["periods"][per]["waterfall"]["usd_per_day"]
        rows.append((lab, w["gross_edge"], w["net_trading"], K))
    if sw:
        cv = sw["video_own120"]
        rows.append(("CV pre-registered, OOS", None, cv["tournament"]["1"]["burned_OOS"]["usd_per_day"], O))
        rows.append(("CV post hoc, OOS", None, cv["tournament_lagcal"]["1"]["burned_OOS"]["usd_per_day"], O))
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
        ax.annotate(fs.usd(after, 0, sign=True), xy=(after, i), xytext=(0, 5.0), textcoords="offset points",
                    ha="center", va="bottom", fontsize=fs.FS_SMALL, color=col, zorder=6, path_effects=fs.halo(3.0))
        pos += after > 0
        if i == 0:  # the marker key, once, in a band above the first row
            for v, t, ha, dx in ((gross, "gross", "left", -4), (net, "net", "right", 4),
                                 (after, "after costs", "right", 4)):
                if v is not None:
                    ax.annotate(t, xy=(v, -0.95), xytext=(dx, 0), textcoords="offset points", ha=ha,
                                va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED, zorder=6,
                                path_effects=fs.halo(3.0))
                    ax.plot([v, v], [-0.62, -0.25], color=fs.GRID, lw=0.6, zorder=1.8)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.tick_params(axis="y", length=0, pad=6)
    ax.spines["left"].set_visible(False)
    ax.set_ylim(len(rows) - 0.4, -1.25)
    ax.set_xlim(-360, 440)
    ax.set_xticks([-300, 0, 300])
    ax.xaxis.set_major_formatter(FuncFormatter(kusd))
    ax.set_xlabel(f"$ per day (CV at V = 1{T}s)")
    after_pos = [r[0] for r in rows if (r[2] - fixed["central"]) > 0]
    tb = (f"After fixed costs only {after_pos[0].replace(', ', ' ')} stays positive" if len(after_pos) == 1
          else "Fixed costs decide the sign")
    ptitle(name, ax, "b", tb, x_in=2.86, y_in=2.74)
    return fs.save_fig(fig, name, OUT)


def curve_label(ax, xs, ys, text: str, color: str, side: int = +1, x0: float = 0.055, pad_pt: float = 1.5,
                fontsize: float = fs.FS_SMALL):
    """Direct label at the left end of a curve on a log-x axis: just above (side +1) or just below (-1) the curve
    over the whole width the text takes, so the label never sits on its own line (measured after a draw)."""
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float)
    t = ax.text(x0, 0.0, text, ha="left", va="bottom" if side > 0 else "top", fontsize=fontsize, color=color,
                zorder=8, linespacing=1.05, bbox=fs.knockout(pad=0.4))
    fig = ax.figure
    fig.canvas.draw()
    bb = t.get_window_extent(fig.canvas.get_renderer())
    inv = ax.transData.inverted()
    xa, xb = inv.transform((bb.x0, bb.y0))[0], inv.transform((bb.x1, bb.y0))[0]
    inside = (xs > xa) & (xs < xb)
    seg = np.r_[np.interp(np.log([xa, xb]), np.log(xs), ys), ys[inside]]
    yref = seg.max() if side > 0 else seg.min()
    y_px = ax.transData.transform((x0, yref))[1] + side * pad_pt * fig.dpi / 72.0
    t.set_y(inv.transform((0.0, y_px))[1])
    return t


def A2() -> list[str]:
    """Latency sweep at every stamp-lag reading, IS and burned OOS ($/day vs V)."""
    name = "figA2_sweep_lags"
    fig = plt.figure(figsize=(W, 2.95))
    axa = fs.axes_in(fig, 0.80, 0.55, 2.48, 1.58)
    axb = fs.axes_in(fig, 3.86, 0.55, 2.48, 1.58)
    curves = pf.sweep_curves()
    note_src(name, "results/tier0/latency_sweep.csv", "results/tier0/latency_sweep_seeds.csv")
    if curves is None:
        fs.placeholder(axa, "results/tier0/latency_sweep.csv")
        fs.placeholder(axb, "results/tier0/latency_sweep.csv")
        return fs.save_fig(fig, name, OUT)
    pre, cal = stamp_lags()
    # (reading, colour, label, place label above (+) or below (-) its line)
    spec = [("tournament_lagcal", O, f"post hoc, {cal:g}{T}s", +1),
            ("tournament_lag3", fs.ORANGE_LIGHT, f"lag 3{T}s", -1),
            ("tournament", K, f"pre-registered, {pre:g}{T}s", +1),
            ("tournament_lag1", G, f"stress, 1{T}s", -1)]
    for ax, period, letter, title, x_in in ((axa, "IS", "a", "IS: break-even moves with the lag", 0.06),
                                            (axb, "burned_OOS", "b", "OOS: the same shift", 3.30)):
        fs.log_time_axis(ax, ticks=(0.1, 0.5, 1, 3, 10, 60), lim=(0.05, 60), label="feed delay V, s (log scale)")
        fs.hgrid(ax)
        for r, col, lab, side in spec:
            c = curves[(r, period)]
            c = c[c.x_s >= 0.05]
            ax.plot(c.x_s, c.pnl_per_day_usd, color=col, lw=fs.LW, ls=fs.IS_LS if period == "IS" else fs.OOS_LS,
                    zorder=4 if col != fs.ORANGE_LIGHT else 3.5)
        ref_verticals(ax)
        ax.set_ylim(-48, 245 if period == "IS" else 150)
        # a colour key in the empty upper right (the four lines run 3-60 $/day apart and merge past 3 s, so
        # labels on the lines would sit on each other); stamp lag L, top to bottom in the order of the curves
        if period == "IS":
            top = ax.get_ylim()[1]
            for k, (r, col, lab, _side) in enumerate(spec):
                ax.annotate(lab, xy=(1.5, top - 18 - k * 30), ha="left", va="top", fontsize=fs.FS_SMALL,
                            color=col if col != fs.ORANGE_LIGHT else fs.ORANGE_LIGHT_TEXT, zorder=8,
                            path_effects=fs.halo(3.0))
            ax.annotate("stamp lag L:", xy=(1.5, top + 2), ha="left", va="bottom", fontsize=fs.FS_SMALL,
                        color=fs.MUTED, zorder=8, alpha=0.0)
        fs.zero_line(ax)
        ax.set_ylabel("net $ per day")
        ax.set_yticks([0, 100, 200] if period == "IS" else [0, 50, 100])
        fs.unicode_ticks(ax, "y")
        ax.set_ylabel("net $ per day" if period == "IS" else "")
        ptitle(name, ax, letter, title, x_in=x_in, y_in=2.75)
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
    for per, lo, hi in (("is_eval", is0, oos0), ("burned_oos", oos0, oos1)):
        for m, v in bm[per].items():  # filled = IS, hollow = OOS (v2 throughout, so INK)
            a = max(pd.Timestamp(m + "-01"), lo)
            b = min(pd.Timestamp(m + "-01") + pd.offsets.MonthEnd(0), hi)
            oos = per == "burned_oos"
            ax.bar(a + (b - a) / 2, v["pnl_usd"] / 1e3, width=max((b - a).days * 0.78, 3.0),
                   color="white" if oos else K, edgecolor=K, lw=0.9 if oos else 0, zorder=3)
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
    row_h = 0.215
    H = max(2.4, n * row_h + 1.0)
    fig = plt.figure(figsize=(W, H))
    ax = fs.axes_in(fig, 2.62, 0.56, 2.20, n * row_h + 0.05)
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
    title = ("Only the copy book (v2) clears zero" if pos and all(r[0] == "v2" for r in pos)
             else "Every test on one axis")
    ptitle(name, ax, "", title, x_in=0.06, y_in=H - 0.16)
    return fs.save_fig(fig, name, OUT)


GRID_SEP = fs.GRID  # family separators (A4) and the A7a 'base' divider: gridline grey, nothing darker


def A5() -> list[str]:
    """Concentration of v2 P&L in the top-k wallets, matches and days."""
    name = "figA5_concentration"
    fig = plt.figure(figsize=(W, 2.6))
    ax = fs.axes_in(fig, 0.86, 0.62, 5.50, 1.52)
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
    KEYS = []
    for per, off in (("IS", -bw / 2 - 0.02), ("OOS", bw / 2 + 0.02)):
        if per not in F:
            continue
        ys = [F[per].get(u, {}).get(f"top{k}_share_of_pnl", np.nan) * 100 for u in units for k in ks]
        oos = per == "OOS"  # filled = IS, hollow = OOS (v2 throughout, so INK)
        ax.bar(x + off, ys, width=bw, color="white" if oos else K, edgecolor=K, lw=0.9 if oos else 0, zorder=3)
        # key, top right: a filled and a hollow swatch
        kx = x[-1] - 2.6 + (0 if per == "IS" else 1.25)
        ky = ax.get_ylim()[1] if False else None
        KEYS.append((kx, per, oos))
    ax.axhline(100, color=fs.REF, lw=fs.LW_VREF, ls=fs.DOT_LS, zorder=2)
    xm = (len(ks) + gap) * (1 if len(units) > 1 else 0) + (len(ks) - 1) / 2  # above the low 'matches' bars
    ax.annotate("100% of P&L", xy=(xm, 100), xytext=(0, 3), textcoords="offset points", ha="center",
                va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED)
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
    yk = ax.get_ylim()[1] * 0.90
    for kx, per, oos in KEYS:
        ax.bar([kx], [ax.get_ylim()[1] * 0.07], bottom=yk - ax.get_ylim()[1] * 0.035, width=0.30,
               color="white" if oos else K, edgecolor=K, lw=0.9 if oos else 0, zorder=6)
        ax.annotate(per, xy=(kx + 0.22, yk), ha="left", va="center", fontsize=fs.FS_SMALL, color=K, zorder=6)
    w5 = F["IS"]["wallets"]["top5_share_of_pnl"] * 100
    ptitle(name, ax, "", f"Five wallets carry {fs.f(w5, 0)}% of in-sample P&L", x_in=0.06, y_in=2.40)
    return fs.save_fig(fig, name, OUT)


def A6() -> list[str]:
    """Spin-aware tennis landing model (simulation): landing error and out-call accuracy vs lead."""
    name = "figA6_spin_sim"
    fig = plt.figure(figsize=(W, 2.8))
    axa = fs.axes_in(fig, 0.66, 0.56, 1.80, 1.66)
    axb = fs.axes_in(fig, 3.96, 0.56, 1.66, 1.66)
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
    ptitle(name, ax, "a", f"Spin-aware fit cuts error {r200:.0f}{fs.TIMES} at 200{T}ms", x_in=0.06, y_in=2.60)

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
        ax.annotate("precision", xy=(200, prec_all[0]), xytext=(0, 3), textcoords="offset points", ha="center",
                    va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED, zorder=8)
    ax.set_xlim(0, 400)
    ax.set_xticks([0, 100, 200, 300, 400])
    ax.set_ylim(0.84, 1.025)
    ax.set_yticks([0.85, 0.9, 0.95, 1.0])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:.2f}"))
    ax.set_xlabel(LEAD_TENNIS)
    ax.set_ylabel("OUT calls, precision and recall")
    fs.direct_label(ax, items, dx_pt=4)
    fs.tag(ax, "simulation", x=0.03, y=0.04, ha="left", va="bottom")
    rmin = min(rec_min)  # over every recall line drawn (UKF ends at 0.88), not only BLS
    pr = f"{prec_all[0]:g}" if prec_all and min(prec_all) == max(prec_all) else "high"
    ptitle(name, ax, "b", f"OUT calls: precision {pr}, recall \u2265 {fs.f(rmin, 2)}", x_in=3.30, y_in=2.60)
    return fs.save_fig(fig, name, OUT)


def A7() -> list[str]:
    """(a) market-side signal decay within a point; (b) the all-points replay on live-recorded books."""
    name = "figA7_decay_replay"
    fig = plt.figure(figsize=(W, 2.85))
    axa = fs.axes_in(fig, 0.70, 0.62, 2.40, 1.66)
    axb = fs.axes_in(fig, 3.92, 0.62, 1.80, 1.66)
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
        ax.text(0.85, -0.45, f"no data, 0.25{ND}1{T}s", ha="center", va="center", rotation=90,
                fontsize=fs.FS_SMALL, color=fs.MUTED, zorder=6)
        ax.set_xticks(xpos)
        ax.set_xticklabels(["0", "1", "2", "3", "5", "10", "base"])
        ax.tick_params(axis="x", length=2)
        ax.set_xlim(-0.5, 7.5)
        ax.set_ylim(-2.2, 1.7)
        ax.set_yticks([-2, -1, 0, 1])
        fs.unicode_ticks(ax, "y")
        ax.set_xlabel("seconds since the score move (bin start)")
        ax.set_ylabel(f"net 30{T}s markout, {fs.CENT}/share")
        ax.text(3.2, 0.93, "fast tier", ha="center", va="center", fontsize=fs.FS_SMALL, color=K)
        ax.text(3.2, -1.75, "everyone else", ha="center", va="center", fontsize=fs.FS_SMALL, color=fs.MUTED)
    ptitle(name, ax, "a", "The fast tier stays ahead at every horizon", x_in=0.06, y_in=2.62)

    rp = load("results/replay/replay.json", name)
    ax = axb
    if not rp:
        fs.placeholder(ax, "results/replay/replay.json")
        ptitle(name, ax, "b", "Replay: pending", x_in=3.30, y_in=2.62)
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
    ax.set_ylim(-2.35, 1.2)
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
    fs.tag(ax, (f"all {neg} settings lose" if neg == len(rp["cells"]) else f"{neg} of {len(rp['cells'])} settings lose"),
           x=0.97, y=0.03)
    tb = ("Trading every point loses at every delay" if all(v < 0 for v in drawn)
          else "Replay of every point")
    ptitle(name, ax, "b", tb, x_in=3.30, y_in=2.62)
    return fs.save_fig(fig, name, OUT)


FIGS = {"F1": F1, "F2": F2, "F3": F3, "F4": F4, "F5": F5, "A1": A1, "A2": A2, "A3": A3,
        "A4": A4, "A5": A5, "A6": A6, "A7": A7, "A8": A8}


# ============================================================================================== FIGURES.md
INFO = {  # figure key -> (role, figure name in the brief, replaces in results/paper/, notes for the integration pass)
    "F1": ("appendix", "Who sees the point first (paper Fig. A3)", "fig1_latency_cv",
           "a: dot-and-range on a log time axis (0.03-120 s) from the end of the point. Our row = frame to order-ready "
           "from the end-to-end run (results/e2e; own footage over WebRTC on a laptop, order not sent): p50 dot, p99 "
           "whisker (INTEGRATION_TODO P-10; falls back to results/webrtc frame-to-call when e2e is absent). Vendor "
           "and published rows are 3 pt ranges; the score-feed label sits left of its bar. The stamp row is the two "
           "stamp lags the paper uses (2.0 s pre-registered to 3.14 s post hoc), dashed because the stamp lag is "
           "unmeasured, over the cited 1-3 s band. The shaded column is the book's reprice (0.84-1.98 s). b: the live "
           "causal engine's early MISS calls (orange; results/engine/online_vs_offline.json A_engine_calls.online; "
           "labels right/called) against the offline evaluation, which used a look-ahead feature (grey; "
           "results/tracking/test_precision_vs_lead_snapshot.csv), as share of the 41 held-out misses called by each "
           "lead (INTEGRATION_TODO P-5: the causal engine is the deployable number)."),
    "F2": ("main", "The edge exists (paper Fig. 2)", "fig2_speed_edge",
           "a: monthly net 30 s markout of the fast tier and of everyone else; filled = IS, hollow = OOS; August split "
           "at the OOS cut. Copy-3-s-later is held to resolution, drawn as its IS and OOS means. b: cumulative v2 P&L "
           "at the fast tier's fills, base, fees x2 and all costs x2; OOS drawn at weekly closes; end labels are the "
           "exact OOS totals."),
    "F3": ("main", "What speed is worth (paper Fig. 3)", "fig3_signal_decay (panels a, b)",
           "Net $/day against feed delay V, a = IS (solid), b = burned OOS (dashed), at the pre-registered (black) and "
           "post hoc (orange) stamp lag and the post hoc inference read per point (light orange; INTEGRATION_TODO "
           "P-9). Dots = the 0.5 / 1 / 3 s scenarios of Table 1B (filled IS, hollow OOS). Grey dotted verticals: "
           "0.5 s best case, 1 s base, 3 s requirement; grey bar: the vendor-stated licensed-video source band "
           "(0.5-8 s). Labels sit in free space next to their own line, with a white halo where a reference line "
           "passes behind. Titles carry the break-even range (seed-mean curves)."),
    "F4": ("main", "Frame to trade (paper Fig. 1)", "(new)",
           "One panel: stage means from results/e2e/summary.json (means add up to the mean total 2,124 ms; the p50 "
           "total is 2,119 ms): simulated 1 s feed (dashed outline), our pipeline (video, CV, order), network RTT/2, "
           "venue hold; orange line = executable time; grey dotted = 3 s requirement; shaded = book-reprice window "
           "(same as F1a). The capacity panels moved to A8."),
    "F5": ("unused", "CV still (not in the paper)", "(new)",
           "Real held-out footage (OpenTTGames test_2, flight 2819, CC BY-NC-SA 4.0), the frame at the offline rule's "
           "call; the title gives both leads: offline 408 ms (look-ahead feature) and the live engine's 325 ms "
           "(online_vs_offline.json flights_called_or_miss). Labels: ball at the call, tracked path, predicted arc "
           "(display only)."),
    "A1": ("appendix", "Capacity and costs (paper Fig. A5)", "figA1_capacity",
           "a: v2 at scaled caps; filled = IS, hollow = OOS. b: gross (grey tick), net of fees (grey dot), after central "
           "fixed costs (coloured dot, value above it) with the low-high fixed-cost range as the bar; marker key once in "
           "a band above the rows; CV rows pre-registered first."),
    "A2": ("unused", "Sweep at every stamp lag (not in the paper)", "figA2_sweep_lags",
           "Seed means for the four stamp-lag readings; a colour key in the empty upper right of a (the lines merge "
           "past 3 s, so labels on the lines collided); reference verticals as in F3."),
    "A3": ("appendix", "Regime and month (paper Fig. A1)", "figA3_regime_month",
           "b: August split at the OOS cut; OOS bars hollow."),
    "A4": ("unused", "Robustness forest plot (not in the paper)", "figA4_forest",
           "Axis clipped at +-4 c (arrowheads mark a CI that runs past it; the exact CI is in the right column); colour "
           "= family; hollow = OOS test; a CI above zero in semibold."),
    "A5": ("unused", "Concentration (not in the paper)", "figA5_concentration",
           "Above 100% means the rest lost money; IS filled, OOS hollow, with a two-swatch key."),
    "A6": ("unused", "Tennis spin simulation (not in the paper)", "figA6_spin_sim",
           "Simulation only; a: log scale; b: precision in grey, labelled above its line."),
    "A7": ("appendix", "Decay and all-points replay (paper Fig. A2)", "fig3_signal_decay (panels c, d)",
           "a: market-side markout by seconds since the score move; the empty 0.25-1 s bins are marked 'no data'. b: "
           "replay of 9 live-recorded matches trading every point (model leads, Florida network); x = sweep OOS cell; "
           "the tag counts all 36 settings."),
    "A8": ("appendix", "Capacity of the CV strategy (paper Fig. A4)", "(new; formerly F4 b, c)",
           "Along the capacity study's size path (net cap 50-5,000 shares at $250 orders, 10 matches a day, half the "
           "stale depth): a Sharpe, b $/day against capital, IS solid, OOS dashed; circles = where the post hoc "
           "Sharpe halves; dotted = the cheapest data stack ($/day). Axes follow the grid's range."),
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
             "PDF drawn at its printed size (6.5 in wide, Source Sans 3 at 11-12 pt so figure text meets the track's "
             "11 pt minimum, fonts embedded) plus a 300 dpi PNG. The paper (scripts/build_paper.py) uses these files. Numbers come only from the result files listed; nothing here re-runs a backtest. Captions stay in "
             "LaTeX; the honesty labels (simulated, assumed feed latency, paper only, order not sent) belong in them.",
             "", "Palette: orange #E8601C our CV strategy / pipeline; near-black #222 v2 or the pre-registered "
             "reading only; grey #8C8C8C others and any secondary series; light grey only as shading (OOS periods, "
             "source bands, seed bands), never as a line, marker or bar. IS solid, OOS dashed; filled marker = IS, "
             "hollow marker = OOS, with no other meaning anywhere (bars too: hollow = OOS). Reference verticals "
             "(0.5 / 1 / 3 s, requirements) are grey dotted 0.6 pt with muted labels, never INK. INK marks the fast "
             "tier in F2a and A7a because v2 is measured at the fast tier's own fills. Seed and CI ranges that would "
             "overlap are thin whiskers, never overlapping translucent fills. Time axes: 'seconds after the point "
             "ends'; lead "
             "axes: 'lead before the ball reaches the table end' (table tennis) or 'lead before the bounce' (tennis "
             "simulation). Numbers rounded half up, true minus signs, thin spaces before units.", "",
             "Rebuild: `nice -n 10 .venv/bin/python scripts/paper_figures_v2.py` (or `--only F1 A4`).", ""]
    for role, head in (("main", "## Main text"), ("appendix", "## Appendix"), ("unused", "## Drawn but not in the paper")):
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
