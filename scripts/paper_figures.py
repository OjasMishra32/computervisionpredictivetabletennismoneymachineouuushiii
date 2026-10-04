"""Every figure in the COURTSIDE paper (docs/paper/PLAN.md section 6 and 9.1), in one journal style.

Writes results/paper/fig*.pdf (vector, drawn at final printed size, fonts embedded) and a 300 dpi PNG of each.
Numbers are read only from committed result files. A missing input draws a labelled "pending" panel instead of
failing, so the build never invents a value. Nothing here runs a backtest or opens new held-out data: Fig. 2(b)
re-draws the committed v2 trade file with the cost lambdas of scripts/v2_cost_stress.py and asserts that its
totals equal results/v2/cost_stress.json to the cent.

Style (docs/paper/STYLE_GUIDE.md (b)): Source Sans 3 at 11 pt for every glyph (the track's 11 pt rule covers
figure text), white background, no top/right spines, 0.6 pt axes, orange #F26B21 for the fast tier and our
strategy, black and greys for everyone else, blue only for source-class bands, IS solid / OOS dashed (filled /
hollow markers), panel letters (a)(b)(c)(d) top left, direct labels instead of legends.

Usage: .venv/bin/python scripts/paper_figures.py [--only fig3]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/paper"
FONTS = ROOT / "docs/paper/fonts"

ORANGE, BLACK, DGREY, MGREY, LGREY = "#F26B21", "#000000", "#555555", "#9A9A9A", "#D4D4D4"
BLUE = "#2C6FBB"
FS = 11.0  # every glyph, final size
LABEL_CV = "assumed feed latency"
MINUS = "−"

FIG_W = 6.5  # text width, inches


# ----------------------------------------------------------------------------------------------- style
def setup_style() -> None:
    for f in ("SourceSans3-Regular.ttf", "SourceSans3-It.ttf", "SourceSans3-Semibold.ttf",
              "SourceSans3-SemiboldIt.ttf"):
        font_manager.fontManager.addfont(str(FONTS / f))
    plt.rcParams.update({
        "font.family": "Source Sans 3", "font.size": FS,
        "axes.labelsize": FS, "axes.titlesize": FS, "xtick.labelsize": FS, "ytick.labelsize": FS,
        "legend.fontsize": FS, "figure.titlesize": FS,
        "mathtext.fontset": "custom", "mathtext.rm": "Source Sans 3", "mathtext.it": "Source Sans 3:italic",
        "mathtext.bf": "Source Sans 3:semibold", "mathtext.sf": "Source Sans 3",
        "axes.unicode_minus": True,
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "axes.edgecolor": "#262626", "axes.linewidth": 0.6, "axes.labelcolor": BLACK,
        "axes.spines.top": False, "axes.spines.right": False,
        "xtick.color": "#262626", "ytick.color": "#262626", "xtick.labelcolor": BLACK, "ytick.labelcolor": BLACK,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.minor.width": 0.4, "ytick.minor.width": 0.4,
        "xtick.major.size": 3.0, "ytick.major.size": 3.0, "xtick.minor.size": 1.8, "ytick.minor.size": 1.8,
        "xtick.major.pad": 2.0, "ytick.major.pad": 2.0,
        "axes.labelpad": 2.0, "lines.linewidth": 1.3, "lines.markersize": 4.0,
        "hatch.linewidth": 0.5, "hatch.color": "#7A7A7A",
        "legend.frameon": False, "legend.handlelength": 1.8, "legend.borderaxespad": 0.2,
        "legend.handletextpad": 0.4, "legend.columnspacing": 1.0, "legend.labelspacing": 0.25,
    })


def load(rel: str):
    p = ROOT / rel
    if not p.exists():
        return None
    if p.suffix == ".json":
        return json.loads(p.read_text())
    if p.suffix == ".csv":
        return pd.read_csv(p)
    return p


def fmt_signed(x: float, nd: int = 2) -> str:
    s = f"{x:+.{nd}f}"
    return s.replace("-", MINUS)


def fmt_num(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace("-", MINUS)


def panel(ax, letter: str, x: float = -0.02, y: float = 1.0) -> None:
    ax.text(x, y, f"({letter})", transform=ax.transAxes, ha="right", va="bottom", fontsize=FS,
            fontweight="semibold", color=BLACK, clip_on=False)


def tag(ax, text: str = LABEL_CV, x: float = 0.99, y: float = 0.98, ha: str = "right", va: str = "top") -> None:
    ax.text(x, y, text, transform=ax.transAxes, ha=ha, va=va, fontsize=FS, style="italic", color=DGREY,
            bbox=dict(boxstyle="square,pad=0.12", fc="white", ec="none", alpha=0.85), zorder=20)


def pending(ax, what: str) -> None:
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(True); s.set_color(LGREY); s.set_linestyle((0, (3, 2)))
    ax.text(0.5, 0.5, f"pending\n{what}", transform=ax.transAxes, ha="center", va="center", fontsize=FS,
            color=DGREY, style="italic")


def zero_line(ax) -> None:
    ax.axhline(0, color=BLACK, lw=0.6, zorder=1)


def save(fig, name: str) -> list[str]:
    OUT.mkdir(parents=True, exist_ok=True)
    pdf, png = OUT / f"{name}.pdf", OUT / f"{name}.png"
    fig.savefig(pdf)  # no bbox_inches: the PDF is exactly the figsize, so 11 pt stays 11 pt in the paper
    fig.savefig(png, dpi=300)
    plt.close(fig)
    return [str(pdf.relative_to(ROOT)), str(png.relative_to(ROOT))]


def log_s_formatter(v, _pos=None) -> str:
    if v >= 1:
        return f"{v:g}"
    if v >= 0.1:
        return f"{v:g}"
    if v >= 0.001:
        return f"{v * 1000:g} ms"
    return ""


# ------------------------------------------------------------------------------------- shared readers
def webrtc_latency() -> dict | None:
    """Our WebRTC -> CV pipeline latency (ms), only from results/webrtc/latency.json (else None = "pending").

    Prefers the file's own headline (measured frame-send -> call emit, the setting where the engine keeps up);
    falls back to the first capture_to_decision_ms block. The assumed-capture estimate is never used here."""
    d = load("results/webrtc/latency.json")
    if not d:
        return None
    h = d.get("headline", {})
    m = h.get("measured_frame_send_to_emit_ms")
    if isinstance(m, dict) and m.get("p50") is not None:
        return {"p50": float(m["p50"]), "p99": float(m.get("p99") or m["p50"]), "n": m.get("n"),
                "key": "headline.measured_frame_send_to_emit_ms", "setting": h.get("setting")}

    def find(o):
        if isinstance(o, dict):
            v = o.get("capture_to_decision_ms")
            if isinstance(v, dict) and v.get("p50") is not None:
                return {"p50": float(v["p50"]), "p99": float(v.get("p99") or v["p50"]), "n": v.get("n"),
                        "key": "capture_to_decision_ms", "setting": None}
            for v in o.values():
                r = find(v)
                if r:
                    return r
        if isinstance(o, list):
            for v in o:
                r = find(v)
                if r:
                    return r
        return None

    return find(d)


def public_stream_s() -> float | None:
    import re
    d = load("results/home_stream/sub_second_routes.json")
    if not d:
        return None
    m = re.search(r"median ([0-9.]+) s", d["bottom_line"]["why_not_match"])
    return float(m.group(1)) if m else None


def latency_m1() -> dict | None:
    d = load("research/v2/latency/results.json")
    return d["summary"]["m1"] if d else None


def sweep_curves():
    """Per-cell seed-mean and seed-percentile curves for video/own120 at the two headline readings."""
    df = load("results/tier0/latency_sweep.csv")
    seeds_p = ROOT / "results/tier0/latency_sweep_seeds.csv"
    if df is None or not seeds_p.exists():
        return None
    df = df[(df.source == "video") & (df.cv == "own120")]
    s = pd.read_csv(seeds_p, usecols=["source", "reading", "x_s", "cv", "period", "seed", "pnl_per_day_usd",
                                      "sharpe_ann"])
    s = s[(s.source == "video") & (s.cv == "own120")]
    out = {}
    for reading in ("tournament_lagcal", "tournament", "tournament_lag1", "tournament_lag3"):
        for period in ("IS", "burned_OOS"):
            c = df[(df.reading == reading) & (df.period == period)].drop_duplicates("x_s").sort_values("x_s")
            ss = s[(s.reading == reading) & (s.period == period)]
            q = ss.groupby("x_s").agg(
                usd_lo=("pnl_per_day_usd", lambda v: np.percentile(v, 2.5)),
                usd_hi=("pnl_per_day_usd", lambda v: np.percentile(v, 97.5)),
                sr_lo=("sharpe_ann", lambda v: np.nanpercentile(v, 2.5)),
                sr_hi=("sharpe_ann", lambda v: np.nanpercentile(v, 97.5))).reset_index()
            out[(reading, period)] = c.merge(q, on="x_s", how="left")
    return out


# ============================================================================================ Fig. 1
def fig1() -> list[str]:
    """(a) information-tier ladder on one log axis; (b) held-out early-call precision/recall."""
    fig = plt.figure(figsize=(FIG_W, 1.85))
    axa = fig.add_axes([0.335, 0.285, 0.30, 0.70])
    axb = fig.add_axes([0.725, 0.285, 0.265, 0.585])

    sweep = load("results/tier0/latency_sweep.json")
    ovo = load("results/engine/online_vs_offline.json")
    decay = load("results/decay/decay.json")
    m1 = latency_m1()
    pub = public_stream_s()
    wr = webrtc_latency()

    rows = []  # (label, lo_s, hi_s, kind, mid_s)
    if ovo:
        st = ovo["headline"]["fp16_cl_fuse_compile_b1_realtime"]["stream"]["after_startup"]["call_ready_ms"]
        rows.append(("our CV engine, call ready", st["p50"] / 1e3, st["p99"] / 1e3, "ours", st["p50"] / 1e3))
    if wr:
        rows.append(("our WebRTC \u2192 CV (own clip)", wr["p50"] / 1e3, wr["p99"] / 1e3, "ours", wr["p50"] / 1e3))
    else:
        rows.append(("our WebRTC \u2192 CV pipeline", None, None, "pending", None))
    rows.append(("in-venue camera (not ours)", 1 / 120, 0.15, "bound", None))
    if sweep:
        m = re.search(r"order delay \(([0-9.]+) s\)", sweep["model"]["video"])
        d = float(m.group(1)) if m else None
        if d:
            rows.append(("venue taker order delay", d, d, "rule", d))
        lag = sweep["grids"]["stamp_lag_s"]
        rows.append(("official stamp (unmeasured)", min(lag), max(lag), "model", None))
        bv = next(s for s in sweep["sources"] if s["key"] == "betting_video")["band_s"]
        rows.append(("licensed video (vendor-stated)", bv[0], bv[1], "vendor", None))
    if pub:
        rows.append(("public stream (preliminary)", pub, pub, "measured", pub))
    if m1:
        e = -m1["espn:game"]["lead_vs_book_s"]["median"]
        p = -m1["pm_sports:game"]["lead_vs_book_s"]["median"]
        w = -m1["wta:point"]["lead_vs_book_s"]["median"]
        rows.append(("score feeds (ESPN, PM, WTA)", min(e, p, w), max(e, p, w), "measured3", (e, p, w)))

    ax = axa
    ax.set_xscale("log")
    ax.set_xlim(1e-3, 100)
    n = len(rows)
    ax.set_ylim(n - 0.5, -0.6)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r[0] for r in rows])
    for t, r in zip(ax.get_yticklabels(), rows):
        if r[3] in ("ours", "pending"):
            t.set_color(ORANGE)
    ax.tick_params(axis="y", length=0, pad=4)
    ax.spines["left"].set_visible(False)
    ax.xaxis.set_major_locator(FixedLocator([1e-3, 1e-2, 0.1, 1, 10, 100]))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: {1e-3: "", 1e-2: "0.01", 0.1: "0.1", 1: "1",
                                                             10: "10", 100: "100"}.get(v, "")))
    ax.set_xlabel("seconds after the bounce (log)")
    for x in (1e-2, 0.1, 1, 10):
        ax.axvline(x, color="#EDEDED", lw=0.5, zorder=0)
    h = 0.56
    for i, (lab, lo, hi, kind, mid) in enumerate(rows):
        if kind == "pending":
            ax.text(1.4e-3, i, "pending", ha="left", va="center", fontsize=FS, style="italic", color=ORANGE)
            continue
        if kind == "measured3":
            ax.plot([lo, hi], [i, i], color=BLACK, lw=0.8, zorder=3)
            for v, mk in zip(mid, ("o", "s", "D")):
                ax.plot([v], [i], marker=mk, ms=3.6, color=BLACK, ls="none", zorder=4)
        elif lo == hi:
            if kind == "rule":
                ax.plot([lo], [i], marker="|", ms=9, mew=1.8, color=BLACK, ls="none", zorder=4)
            else:
                ax.plot([lo], [i], marker="o", ms=4.5, color=BLACK, ls="none", zorder=4)
        else:
            hatch = {"model": "////", "vendor": "xxxx"}.get(kind)
            ec = {"model": DGREY, "vendor": BLUE}.get(kind, "none")
            fc = {"vendor": "#E3ECF7", "model": "white", "ours": ORANGE, "bound": LGREY}[kind]
            ax.add_patch(Rectangle((lo, i - h / 2), hi - lo, h, facecolor=fc, edgecolor=ec, lw=0.6, hatch=hatch,
                                   zorder=3))
    # the book reprices before the official stamp: a negative time cannot sit on a log axis, so arrow + text
    if m1 and sweep:
        b = -m1["book_vs_official_T_s"]["median"]
        i_stamp = next(i for i, r in enumerate(rows) if r[3] == "model")
        ax.annotate("", xy=(0.12, i_stamp), xytext=(0.95, i_stamp),
                    arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=1.0, mutation_scale=7))
        ax.text(0.11, i_stamp, f"book {MINUS}{b:.1f} s", ha="right", va="center", fontsize=FS, color=ORANGE)
    fig.text(0.008, 0.975, "(a)", ha="left", va="top", fontsize=FS, fontweight="semibold")

    # (b) early calls on held-out 120 fps table-tennis video: the live causal engine leads (orange); the offline
    # evaluation (snapshot rule with a look-ahead feature) is shown in grey and labelled as such
    tr = load("results/tracking/summary.json")
    eng = (ovo or {}).get("runs", {}).get("fp16_cl_fuse_compile_b1_realtime", {}).get("A_engine_calls", {}).get("online")
    ax = axb
    if not tr or not eng:
        pending(ax, "results/tracking/summary.json, results/engine/online_vs_offline.json")
    else:
        ec = tr["early_call"]
        leads = [0, 25, 50, 100, 150, 200]
        snap = ec["precision_recall_test_snapshot"]
        P = [snap[f"{l}ms"]["precision"] for l in leads]
        R = [snap[f"{l}ms"]["recall"] for l in leads]
        Wlo = [snap[f"{l}ms"]["precision_wilson95"][0] for l in leads]
        Whi = [snap[f"{l}ms"]["precision_wilson95"][1] for l in leads]
        Pe = [eng[f"{l}ms"]["precision"] for l in leads]
        Re = [eng[f"{l}ms"]["recall"] for l in leads]
        ax.fill_between(leads, Wlo, Whi, color=LGREY, alpha=0.45, lw=0)
        ax.plot(leads, P, color=MGREY, marker="o", ms=3.0, mfc="white", lw=0.9)
        ax.plot(leads, R, color=MGREY, ls=(0, (3, 1.5)), marker="o", ms=3.0, mfc="white", lw=0.9)
        ax.plot(leads, Pe, color=ORANGE, marker="o", ms=3.4, lw=1.3, zorder=4)
        ax.plot(leads, Re, color=ORANGE, ls=(0, (3, 1.5)), marker="o", ms=3.4, lw=1.3, zorder=4)
        ax.set_xlim(-8, 208)
        ax.set_ylim(0, 1.04)
        ax.set_xticks([0, 100, 200])
        ax.set_yticks([0, 0.5, 1.0])
        ax.set_yticklabels(["0", "0.5", "1"])
        ax.set_xlabel("call lead (ms)")
        e50 = eng["50ms"]
        ax.text(0.0, 1.03, f"{e50['tp']} of {e50['tp'] + e50['fn']} called, 0 false", transform=ax.transAxes,
                ha="left", va="bottom", fontsize=FS, color=ORANGE)
        ax.text(6, 0.87, "precision", ha="left", va="center", fontsize=FS, color=ORANGE)
        ax.text(205, 0.2, "recall", ha="right", va="center", fontsize=FS, color=ORANGE)
        ax.annotate("offline,\nlook-ahead", xy=(25, R[1]), xytext=(60, 0.52), fontsize=FS, color=DGREY, ha="left",
                    va="center", arrowprops=dict(arrowstyle="-", color=DGREY, lw=0.6))
    fig.text(0.655, 0.975, "(b)", ha="left", va="top", fontsize=FS, fontweight="semibold")
    return save(fig, "fig1_latency_cv")


# ============================================================================================ Fig. 2
def v2_daily_paths():
    """Base daily P&L from results/lowloss/daily.csv; stressed paths re-drawn from the committed trade file."""
    d = load("results/lowloss/daily.csv")
    causal = load("results/v2/causal.json")
    cs = load("results/v2/cost_stress.json")
    if d is None or causal is None:
        return None
    d = d[(d.run == "a") & (d.policy == "v2")]
    base = {}
    for book, per in (("u1_is", "is_eval"), ("u1_oos", "burned_oos")):
        s = d[d.book == book].assign(date=lambda x: pd.to_datetime(x.date)).set_index("date").pnl_usd
        tot = causal[f"causal/{per}/slip0.0"]["total_pnl_usd"]
        assert abs(s.sum() - tot) < 0.01, f"daily.csv {book} total {s.sum():.2f} != causal.json {tot:.2f}"
        base[per] = s
    stressed = {}
    parquet = ROOT / "data/v2_trades_is_oos.parquet"
    if parquet.exists() and cs:
        sys.path.insert(0, str(ROOT))
        from src import v2  # noqa: E402
        from src.tape import universe  # noqa: E402
        u = universe()
        oos_conds = set(u.loc[u.oos, "cond"])
        tr = pd.read_parquet(parquet)
        # same row selection and lambdas as scripts/v2_cost_stress.py (fee_x2, costs_x2)
        scen = {"fee_x2": lambda t: t.pnl_ps - t.fee, "costs_x2": lambda t: t.pnl_ps - t.fee - 0.005}
        for per, part in (("is_eval", tr[(tr.month >= v2.E.EVAL_START) & ~tr.cond.isin(oos_conds)]),
                          ("burned_oos", tr[tr.cond.isin(oos_conds)])):
            for name, f in scen.items():
                q = part.assign(pnl_ps=f(part))
                q = q.assign(pnl=q.shares * q.pnl_ps)
                q = q[q.month >= v2.E.EVAL_START]
                ser = v2.E.daily_series(q)
                ser.index = ser.index.tz_localize(None)
                want = cs[f"{per}/{name}"]["total_pnl_usd"]
                assert abs(ser.sum() - want) < 0.01, f"{per}/{name}: {ser.sum():.2f} != cost_stress {want:.2f}"
                stressed[(per, name)] = ser
    return base, stressed, cs


def fig2() -> list[str]:
    fig = plt.figure(figsize=(FIG_W, 1.6))
    axa = fig.add_axes([0.075, 0.16, 0.385, 0.71])
    axb = fig.add_axes([0.585, 0.16, 0.255, 0.71])

    al = load("results/alpha/alpha.json")
    ax = axa
    if not al:
        pending(ax, "results/alpha/alpha.json")
    else:
        A = al["A_source"]
        series = [("fast_net30_c", ORANGE, "fast tier"), ("others_net30_c", BLACK, "other takers"),
                  ("copy_3s_later_net_to_resolution_c", MGREY, "copy 3 s later")]
        months = sorted({m["month"] for p in ("IS", "OOS") for m in A[p]["months"]})
        xi = {m: i for i, m in enumerate(months)}
        is_months = {x["month"] for x in A["IS"]["months"]}
        for key, col, lab in series:
            for per, mfc, ls in (("IS", col, "-"), ("OOS", "white", "--")):
                ms = A[per]["months"]
                xs = [xi[m["month"]] + (0.22 if (per == "OOS" and m["month"] in is_months) else 0) for m in ms]
                ax.plot(xs, [m[key] for m in ms], color=col, ls=ls, lw=1.1, marker="o", ms=3.4, mfc=mfc, mec=col,
                        mew=0.9)
        oos_x = xi["2026-08"] + 0.11
        ax.axvspan(oos_x, len(months) - 0.5, color="#F1F1F1", lw=0, zorder=0)
        ax.text(oos_x + 0.15, 3.15, "OOS", ha="left", va="top", fontsize=FS, color=DGREY)
        zero_line(ax)
        ax.set_xlim(-0.5, len(months) - 0.5)
        lab = {m: pd.Timestamp(m + "-01").strftime("%b") for m in months}
        ticks = [i for i, m in enumerate(months) if i % 2 == 0]
        ax.set_xticks(ticks)
        ax.set_xticklabels([lab[months[i]] for i in ticks])
        ax.set_ylim(-5.0, 3.2)
        ax.set_yticks([-3, -2, -1, 0, 1, 2, 3])
        ax.set_ylabel("¢ per share")
        handles = [Line2D([], [], color=c, lw=1.1, marker="o", ms=3.4, label=l) for _, c, l in series[1:]]
        ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.30, -0.03), handlelength=1.4,
                  labelspacing=0.1, borderaxespad=0.1)
        ax.text(1.5, 2.85, "fast tier", color=ORANGE, fontsize=FS, ha="left", va="center")
    panel(ax, "a", x=-0.13)

    ax = axb
    paths = v2_daily_paths()
    if not paths:
        pending(ax, "results/lowloss/daily.csv")
    else:
        base, stressed, cs = paths
        is_b, oos_b = base["is_eval"], base["burned_oos"]

        def draw(is_s, oos_s, col, lw, z):
            c1 = is_s.cumsum()
            c2 = oos_s.cumsum() + c1.iloc[-1]
            ax.plot(c1.index, c1.values / 1e3, color=col, lw=lw, ls="-", zorder=z)
            ax.plot(c2.index, c2.values / 1e3, color=col, lw=lw, ls=(0, (2.5, 1.2)), zorder=z)
            return c1.iloc[-1], c2.iloc[-1] - c1.iloc[-1]

        res = {}
        if stressed:
            res["costs_x2"] = draw(stressed[("is_eval", "costs_x2")], stressed[("burned_oos", "costs_x2")], MGREY,
                                   1.1, 2)
            res["fee_x2"] = draw(stressed[("is_eval", "fee_x2")], stressed[("burned_oos", "fee_x2")], DGREY, 1.1, 3)
        res["base"] = draw(is_b, oos_b, ORANGE, 1.5, 4)
        oos0 = oos_b.index.min()
        ax.axvline(oos0, color=DGREY, lw=0.6, ls=":")
        ax.set_xlim(is_b.index.min(), oos_b.index.max() + pd.Timedelta(days=1))
        ax.set_ylabel("net P&L ($k)")
        ax.set_ylim(-2, 47)
        ax.set_yticks([0, 10, 20, 30, 40])
        zero_line(ax)
        ticks = [pd.Timestamp(x) for x in ("2026-02-01", "2026-05-01", "2026-08-01")]
        ax.set_xticks(ticks)
        ax.set_xticklabels([t.strftime("%b") for t in ticks])
        ax.text(oos0 - pd.Timedelta(days=3), 46.5, "OOS \u2192", ha="right", va="top", fontsize=FS, color=DGREY)
        x_end = 1.03
        names = {"base": ("base", ORANGE), "fee_x2": ("fees ×2", DGREY), "costs_x2": ("all costs ×2", MGREY)}
        ypos = {"base": 0.86, "fee_x2": 0.50, "costs_x2": 0.14}
        for k, (i_tot, o_tot) in res.items():
            nm, col = names[k]
            ax.text(x_end, ypos[k], f"{nm}\n{fmt_signed(i_tot / 1e3, 1)}k | {fmt_signed(o_tot / 1e3, 1)}k",
                    transform=ax.transAxes, ha="left", va="center", fontsize=FS, color=col, clip_on=False,
                    linespacing=1.05)
    panel(ax, "b", x=-0.20)
    return save(fig, "fig2_speed_edge")


# ============================================================================================ Fig. 3
def draw_bands(ax, pub, m1) -> None:
    ax.axvspan(0.04, 0.15, color="#EEEEEE", lw=0, zorder=0)
    ax.axvspan(0.5, 8.0, color=BLUE, alpha=0.09, lw=0, zorder=0)
    if m1:
        lo = -m1["espn:game"]["lead_vs_book_s"]["median"]
        hi = -m1["wta:point"]["lead_vs_book_s"]["median"]
        ax.axvspan(lo, hi, color="#DADADA", lw=0, zorder=0)
    if pub:
        ax.axvline(pub, color=DGREY, lw=0.8, ls=(0, (1, 1)), zorder=0.5)
    ax.axvline(1.0, color=BLACK, lw=1.1, ls=(0, (1, 1.4)), zorder=5)


def fig3() -> list[str]:
    """Centrepiece, one row: (a) $/day and (b) Sharpe against feed delay V (log) at both stamp-lag readings, with the
    source-class bands and the 1 s licensed-feed baseline; (c) market-side decay of the net markout within a point.
    The live-book replay that used to be panel (d) is drawn on its own as Fig. A (fig_replay)."""
    fig = plt.figure(figsize=(FIG_W, 1.9))
    H = 1.9
    bot, top = 0.50 / H, 0.29 / H
    hgt = 1 - bot - top
    axa = fig.add_axes([0.50 / FIG_W, bot, 1.50 / FIG_W, hgt])
    axb = fig.add_axes([2.62 / FIG_W, bot, 1.50 / FIG_W, hgt])
    axc = fig.add_axes([4.66 / FIG_W, bot, 1.80 / FIG_W, hgt])

    sw = load("results/tier0/latency_sweep.json")
    curves = sweep_curves()
    pub = public_stream_s()
    m1 = latency_m1()
    readings = [("tournament_lagcal", ORANGE), ("tournament", BLACK)]

    for ax, metric, lo_k, hi_k, ylab, letter in ((axa, "pnl_per_day_usd", "usd_lo", "usd_hi", "$ per day", "a"),
                                                  (axb, "sharpe_ann", "sr_lo", "sr_hi", "Sharpe", "b")):
        if curves is None or sw is None:
            pending(ax, "results/tier0/latency_sweep.csv")
            panel(ax, letter, x=-0.12)
            continue
        ax.set_xscale("log")
        ax.set_xlim(0.05, 60)
        for (reading, col) in readings:
            for period, ls in (("IS", "-"), ("burned_OOS", (0, (3, 1.5)))):
                c = curves[(reading, period)]
                c = c[c.x_s >= 0.05]
                ax.fill_between(c.x_s, c[lo_k], c[hi_k], color=col, alpha=0.10 if col == ORANGE else 0.07, lw=0,
                                zorder=1)
                ax.plot(c.x_s, c[metric], color=col, ls=ls, lw=1.25, zorder=3)
        if metric == "pnl_per_day_usd":
            ax.set_ylim(-60, 250)
            ax.set_yticks([0, 100, 200])
        else:
            ax.set_ylim(-14, 27)
            ax.set_yticks([-10, 0, 10, 20])
        draw_bands(ax, pub, m1)
        zero_line(ax)
        ax.xaxis.set_major_locator(FixedLocator([0.1, 1, 10]))
        ax.xaxis.set_minor_locator(FixedLocator([0.05, 0.2, 0.5, 2, 5, 20, 60]))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:g}"))
        ax.xaxis.set_minor_formatter(FuncFormatter(lambda v, p: ""))
        ax.set_xlabel("feed delay V (s, log)")
        ax.set_ylabel(ylab)
        tr = ax.get_xaxis_transform()
        if letter == "a":
            ax.text(0.085, 1.01, "venue", transform=tr, ha="center", va="bottom", fontsize=FS, color=DGREY)
            ax.text(2.0, 1.01, "licensed", transform=tr, ha="center", va="bottom", fontsize=FS, color=BLUE)
            if m1:
                ax.text(60, 1.01, "feeds", transform=tr, ha="right", va="bottom", fontsize=FS, color=DGREY)
            be = sw["breakeven_video_delay"]
            for reading, col in readings:
                xs = [be[reading][p]["breakeven_V_s_seed_mean_curve"] for p in ("IS", "burned_OOS")]
                ax.plot(xs, [0, 0], ls="none", marker="o", ms=4.6, mfc="white", mec=col, mew=1.1, zorder=6)
            ax.text(58, 200, "post hoc", color=ORANGE, fontsize=FS, ha="right", va="center", zorder=9,
                    bbox=dict(boxstyle="square,pad=0.05", fc="white", ec="none", alpha=0.85))
            ax.text(58, 125, "pre-reg.", color=BLACK, fontsize=FS, ha="right", va="center", zorder=9,
                    bbox=dict(boxstyle="square,pad=0.05", fc="white", ec="none", alpha=0.85))
        else:
            ax.text(1.0, 1.01, "1 s feed", transform=tr, ha="center", va="bottom", fontsize=FS, color=BLACK)
            v = sw["video_own120"]
            for reading, col in readings:
                for p in ("IS", "burned_OOS"):
                    sr = v[reading]["1"][p]["sharpe_ann"]
                    ax.plot([1.0], [sr], marker="o", ms=3.8, color=col, mfc=col if p == "IS" else "white", mew=1.0,
                            zorder=7)
            tag(ax, LABEL_CV, x=0.02, y=0.02, ha="left", va="bottom")
        panel(ax, letter, x=-0.20)

    # (c) market-side decay within a point
    dj = load("results/decay/decay.json")
    ax = axc
    if not dj:
        pending(ax, "results/decay/decay.json")
    else:
        bins = ["0-0.25", "0.25-0.5", "0.5-1", "1-2", "2-3", "3-5", "5-10", "10-30", "baseline"]
        ticklab = ["0", "", "", "1", "", "3", "", "10", ""]
        xs = np.arange(len(bins))
        sub = dj["tennis"]["subsets"]
        for who, col in (("fast", ORANGE), ("others", BLACK)):
            for per, ls, mfc, off in (("IS", "-", col, -0.1), ("burned_OOS", (0, (3, 1.5)), "white", 0.1)):
                cur = sub[per]["curves"][who]["net30"]
                ys = np.array([cur[b]["mean_c"] if cur[b]["mean_c"] is not None else np.nan for b in bins], float)
                lo = np.array([cur[b]["ci_c"][0] if cur[b]["ci_c"] else np.nan for b in bins], float)
                hi = np.array([cur[b]["ci_c"][1] if cur[b]["ci_c"] else np.nan for b in bins], float)
                x = xs + off
                ax.plot(x[3:8], ys[3:8], color=col, ls=ls, lw=1.1, zorder=3)
                ax.errorbar(x, ys, yerr=[ys - lo, hi - ys], fmt="none", ecolor=col, elinewidth=0.7, capsize=0,
                            zorder=3)
                ax.plot(x, ys, ls="none", marker="o", ms=3.2, color=col, mfc=mfc, mec=col, mew=0.9, zorder=4)
        ax.add_patch(Rectangle((0.55, -2.4), 1.9, 4.2, facecolor="none", edgecolor=LGREY, hatch="////", lw=0,
                               zorder=0))
        ax.axvline(7.5, color=LGREY, lw=0.6)
        zero_line(ax)
        ax.set_xlim(-0.5, len(bins) - 0.5)
        ax.set_ylim(-2.4, 1.7)
        ax.set_yticks([-2, -1, 0, 1])
        ax.set_xticks(xs)
        ax.set_xticklabels(ticklab)
        ax.tick_params(axis="x", which="major", length=2)
        ax.set_xlabel("s since the score move")
        ax.set_ylabel("¢ per share")
        ax.text(5.0, 1.38, "fast tier", color=ORANGE, fontsize=FS, ha="center", va="center")
        ax.text(5.0, -1.85, "others", color=BLACK, fontsize=FS, ha="center", va="center")
        ax.text(8.0, 1.42, "base", color=DGREY, fontsize=FS, ha="center", va="center")
    panel(ax, "c", x=-0.17)
    return save(fig, "fig3_signal_decay")


def fig_replay() -> list[str]:
    """Live-book replay of the 1 s trader (9 matches recorded 2026-10-03), every point, three stamp lags."""
    fig = plt.figure(figsize=(FIG_W * 0.62, 2.1))
    ax = fig.add_axes([0.15, 0.22, 0.62, 0.66])
    rp = load("results/replay/replay.json")
    if not rp:
        pending(ax, "results/replay/replay.json")
        return save(fig, "figA_replay")
    Vs = [0.0, 0.5, 1.0]
    keyv = {0.0: "0", 0.5: "0.5", 1.0: "1"}
    cols = {1: "#A8A8A8", 2: BLACK, 3: ORANGE}
    ends = []
    for lag, off in ((1, -0.035), (2, 0.0), (3, 0.035)):
        ys, lo, hi = [], [], []
        for v in Vs:
            a = rp["cells"][f"V{keyv[v]}|lag{lag}|lead_model|florida"]["all"]
            ys.append(a["per_share_mark_c"]); lo.append(a["per_share_mark_ci95_c"][0])
            hi.append(a["per_share_mark_ci95_c"][1])
        x = np.array(Vs) + off
        ys, lo, hi = map(np.array, (ys, lo, hi))
        ax.errorbar(x, ys, yerr=[ys - lo, hi - ys], color=cols[lag], lw=1.2, marker="o", ms=3.6, elinewidth=0.7,
                    capsize=0, zorder=3)
        ends.append((lag, ys[-1]))
    placed = []
    for lag, y in sorted(ends, key=lambda t: t[1]):
        yy = y if not placed else max(y, placed[-1] + 0.45)
        placed.append(yy)
        ax.text(1.09, yy, f"lag {lag} s", color=cols[lag], fontsize=FS, ha="left", va="center")
    ref = rp.get("sweep_reference", {})
    if ref.get("headline_reading_OOS_c"):
        r = ref["headline_reading_OOS_c"]
        ax.plot(Vs, [r["V0"], r["V0.5"], r["V1"]], ls="none", marker="x", ms=5, color=DGREY, mew=1.0, zorder=4)
        ax.text(0.08, r["V0"], "sweep, OOS", fontsize=FS, color=DGREY, ha="left", va="center")
    zero_line(ax)
    neg = sum(1 for c in rp["cells"].values() if c["all"]["per_share_mark_c"] < 0)
    ax.text(0.99, 1.02, f"{neg} of {len(rp['cells'])} cells < 0", transform=ax.transAxes, fontsize=FS,
            ha="right", va="bottom", color=BLACK)
    ax.set_xlim(-0.12, 1.45)
    ax.set_xticks(Vs)
    ax.set_xticklabels(["0", "0.5", "1"])
    ax.set_ylim(-2.0, 1.3)
    ax.set_yticks([-2, -1, 0, 1])
    ax.set_xlabel("assumed feed delay V (s)")
    ax.set_ylabel("¢ per share, marked")
    return save(fig, "figA_replay")


# ============================================================================================ Fig. 4
def fig4() -> list[str]:
    fig = plt.figure(figsize=(FIG_W, 2.1))
    axa = fig.add_axes([0.105, 0.25, 0.335, 0.64])
    axb = fig.add_axes([0.585, 0.25, 0.405, 0.64])
    fin = load("results/financials/financials.json")
    sw = load("results/tier0/latency_sweep.json")
    ax = axa
    if not fin:
        pending(ax, "results/financials/financials.json")
        pending(axb, "results/financials/financials.json")
        panel(axa, "a"); panel(axb, "b")
        return save(fig, "figA1_capacity")
    sc = fin["strategies"]["v2"]["scaling"]
    sizes = ["0.5x", "1x", "2x", "5x", "all prints"]
    xs = np.arange(len(sizes))
    for per, off, mfc, ls in (("IS", -0.12, ORANGE, "-"), ("OOS", 0.12, "white", (0, (3, 1.5)))):
        y = np.array([sc[s][per]["per_share_c"] for s in sizes])
        lo = np.array([sc[s][per]["per_share_ci95_c"][0] for s in sizes])
        hi = np.array([sc[s][per]["per_share_ci95_c"][1] for s in sizes])
        ax.errorbar(xs + off, y, yerr=[y - lo, hi - y], fmt="none", ecolor=ORANGE, elinewidth=0.8, capsize=0)
        ax.plot(xs + off, y, ls=ls, lw=0.9, color=ORANGE, marker="o", ms=4, mfc=mfc, mec=ORANGE, mew=1.0)
    zero_line(ax)
    ax.set_xticks(xs)
    caps = [sc[s]["OOS"]["capital_usd"] for s in sizes]
    ax.set_xticklabels([f"{s.replace('x', chr(215)).replace('all prints', 'all')}\n${c / 1e3:.0f}k" for s, c in
                        zip(sizes, caps)])
    ax.set_ylim(-3.8, 2.4)
    ax.set_yticks([-3, -2, -1, 0, 1, 2])
    ax.set_ylabel("net ¢/share [95% CI]")
    ax.set_xlim(-0.5, len(sizes) - 0.5)
    ax.text(0.02, 0.03, "size; OOS capital", transform=ax.transAxes, fontsize=FS, color=DGREY, ha="left",
            va="bottom")
    ax.text(1.0, 1.85, "IS", color=ORANGE, fontsize=FS, ha="center", va="bottom")
    ax.text(2.25, 0.55, "OOS", color=ORANGE, fontsize=FS, ha="left", va="bottom")
    panel(ax, "a", x=-0.14)

    ax = axb
    v2f = fin["strategies"]["v2"]
    fixed = v2f["cost"]["daily"]
    bw = 0.27
    groups = []
    for per in ("IS", "OOS"):
        w = v2f["periods"][per]["waterfall"]["usd_per_day"]
        groups.append((f"v2\n{per}", w["gross_edge"], w["net_trading"], False))
    if sw:
        cv = sw["video_own120"]
        groups.append(("CV pre\n1 s OOS", None, cv["tournament"]["1"]["burned_OOS"]["usd_per_day"], True))
        groups.append(("CV post\n1 s OOS", None, cv["tournament_lagcal"]["1"]["burned_OOS"]["usd_per_day"], True))
    for gi, (name, gross, net, is_cv) in enumerate(groups):
        x0 = gi
        after = net - fixed["central"]
        if gross is not None:
            ax.bar(x0 - bw, gross, width=bw, color="#C8C8C8", lw=0)
        ax.bar(x0, net, width=bw, color=ORANGE if not is_cv else "white", edgecolor=ORANGE, lw=0.9,
               hatch="////" if is_cv else None)
        ax.bar(x0 + bw, after, width=bw, color="white", edgecolor=BLACK, lw=0.9)
        ax.plot([x0 + bw, x0 + bw], [net - fixed["low"], net - fixed["high"]], color=BLACK, lw=0.7)
        ax.text(x0 + bw, net - fixed["high"] - 8, fmt_signed(after, 0), ha="center", va="top", fontsize=FS)
    zero_line(ax)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([g[0] for g in groups])
    ax.tick_params(axis="x", length=0)
    ax.set_xlim(-0.55, len(groups) - 0.45)
    ax.set_ylim(-540, 720)
    ax.set_yticks([-300, -200, -100, 0, 100, 200, 300])
    ax.set_ylabel("$ per day")
    handles = [Patch(fc="#C8C8C8", ec="none", label="gross"), Patch(fc=ORANGE, ec=ORANGE, label="net of fees"),
               Patch(fc="white", ec=BLACK, label="after fixed costs")]
    ax.legend(handles=handles, loc="upper right", ncol=1, handlelength=1.0, bbox_to_anchor=(1.01, 1.03),
              labelspacing=0.1)
    panel(ax, "b", x=-0.14)
    return save(fig, "figA1_capacity")


# ======================================================================================= Appendix figs
def figA1() -> list[str]:
    """v2 by venue regime and by month, IS and OOS (risk_stats)."""
    rs = load("results/risk/risk_stats.json")
    fig = plt.figure(figsize=(FIG_W, 2.3))
    axa = fig.add_axes([0.08, 0.24, 0.36, 0.70])
    axb = fig.add_axes([0.56, 0.24, 0.42, 0.70])
    if not rs:
        pending(axa, "risk_stats.json"); pending(axb, "risk_stats.json")
        return save(fig, "figA3_regime_month")
    reg = rs["regime"]
    order = ["3s/0%", "3s/3%", "1s/3%", "1s/5%"]
    ax = axa
    for i, r in enumerate(order):
        d = reg["is_eval"][r]
        ax.errorbar([i - 0.1], [d["per_share_c"]], yerr=[[d["per_share_c"] - d["ci_c"][0]], [d["ci_c"][1] - d["per_share_c"]]],
                    fmt="o", color=ORANGE, ms=4.5, elinewidth=0.8)
        if r in reg.get("burned_oos", {}):
            o = reg["burned_oos"][r]
            ax.errorbar([i + 0.12], [o["per_share_c"]], yerr=[[o["per_share_c"] - o["ci_c"][0]], [o["ci_c"][1] - o["per_share_c"]]],
                        fmt="o", color=ORANGE, mfc="white", ms=4.5, elinewidth=0.8)
    zero_line(ax)
    ax.set_xticks(range(len(order))); ax.set_xticklabels(order)
    ax.set_xlabel("venue regime (taker delay / fee)")
    ax.set_ylabel("net ¢/share [95% CI]")
    ax.set_ylim(-0.5, 3.0)
    ax.text(3.2, 0.45, "OOS", color=ORANGE, fontsize=FS, ha="left", va="center")
    ax.text(0.1, 2.75, "IS", color=ORANGE, fontsize=FS, ha="left", va="center")
    panel(ax, "a", x=-0.12)
    ax = axb
    bm = rs["by_month"]
    months = sorted(set(bm["is_eval"]) | set(bm["burned_oos"]))
    xi = {m: i for i, m in enumerate(months)}
    for per, col, mfc, off in (("is_eval", ORANGE, ORANGE, -0.12), ("burned_oos", ORANGE, "white", 0.12)):
        xs = [xi[m] + off for m in bm[per]]
        ax.bar(xs, [bm[per][m]["pnl_usd"] / 1e3 for m in bm[per]], width=0.24, color=mfc, edgecolor=col, lw=0.8)
    zero_line(ax)
    ax.set_xticks(range(len(months)))
    ax.set_xticklabels([pd.Timestamp(m + "-01").strftime("%b") for m in months])
    ax.set_ylabel("v2 net P&L ($k)")
    ax.set_xlabel("2026; filled = IS, hollow = OOS")
    panel(ax, "b", x=-0.12)
    return save(fig, "figA3_regime_month")


def figA2() -> list[str]:
    """Forest plot of every pre-registered or blind test on one cents-per-share axis."""
    S = load("results/summary.json"); ex = load("results/expand/results.json"); t3 = load("results/tier0_v3/blind.json")
    mk = load("results/maker/oos.json"); rp = load("results/replay/replay.json"); cs = load("results/v2/cost_stress.json")
    causal = load("results/v2/causal.json")
    rows = []  # label, value, lo, hi, pass(bool|None)

    def add(lab, v, ci, ok):
        rows.append((lab, v, ci[0] if ci else None, ci[1] if ci else None, ok))
    if S:
        for k, lab, key in (("h1", "H1 follow the jump, OOS", "J0.04_H30"), ("h2", "H2 favourites, OOS", "lo0.85_hi0.97"),
                            ("h5", "H5 quote after jumps, OOS", "J0.04_W30")):
            d = S["oos"][k][key]
            add(lab, d["mean_pnl_per_share_c"], d["ci95_pnl_per_share_c"],
                d["ci95_pnl_per_share_c"][0] > 0)
        d = S["oos"]["h6_shadow"]
        add("v1 copy fast tier, OOS (blind)", d["mean_pnl_per_share_c"], d["ci95_pnl_per_share_c"], False)
    if causal:
        d = causal["causal/burned_oos/slip0.0"]
        add("v2 burned OOS (non-blind)", d["per_share_c"], d["per_share_ci_c"], d["per_share_ci_c"][0] > 0)
    if cs:
        d = cs["burned_oos/fee_x2"]
        add("v2 burned OOS, fees ×2", d["per_share_c"], d["per_share_ci_c"], d["per_share_ci_c"][0] > 0)
    if ex:
        for p, lab in (("u2_is", "v2 unseen markets U2, IS period"), ("u2_oos", "v2 unseen markets U2, OOS (blind)")):
            d = ex["primary"][p]
            add(lab, d["per_share_c"], d["per_share_ci_c"], bool(d["pass"]))
    if t3:
        for p, lab in (("u2_is", "tier-0 v3 frozen rule, U2 IS"), ("u2_oos", "tier-0 v3 frozen rule, U2 OOS")):
            d = t3["sets"][p]["primary"]
            ci = d.get("per_share_ci95_c") or d.get("per_share_ci_c") or (
                [d["per_share_ci95_c_lo"], d["per_share_ci95_c_hi"]] if "per_share_ci95_c_lo" in d else None)
            add(lab, d["per_share_c"], ci, False)
    if mk:
        add("maker v1, blind OOS (per fill)", mk["primary"]["value_c"], mk["primary"]["ci95_c"], False)
    if rp:
        a = rp["cells"]["V1|lag2|lead_model|florida"]["all"]
        add("replay, V = 1 s, lag 2 s (9 matches)", a["per_share_mark_c"], a["per_share_mark_ci95_c"], False)
    fig = plt.figure(figsize=(FIG_W, 0.25 * len(rows) + 0.7))
    ax = fig.add_axes([0.44, 0.55 / (0.25 * len(rows) + 0.7), 0.54, 1 - 0.75 / (0.25 * len(rows) + 0.7)])
    for i, (lab, v, lo, hi, ok) in enumerate(rows):
        col = ORANGE if ok else BLACK
        if lo is not None:
            ax.plot([lo, hi], [i, i], color=col, lw=1.0)
        ax.plot([v], [i], "o", color=col, ms=4.5, mfc=col if ok else "white")
    ax.axvline(0, color=BLACK, lw=0.6)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_xlabel("net ¢ per share [95% CI]")
    return save(fig, "figA4_forest")


def figA3() -> list[str]:
    """Latency-sweep extensions: every stamp-lag reading, IS and OOS ($/day vs V)."""
    curves = sweep_curves()
    fig = plt.figure(figsize=(FIG_W, 2.9))
    axa = fig.add_axes([0.10, 0.19, 0.38, 0.56])
    axb = fig.add_axes([0.60, 0.19, 0.38, 0.56])
    if curves is None:
        pending(axa, "latency_sweep.csv"); pending(axb, "latency_sweep.csv")
        return save(fig, "figA2_sweep_lags")
    cols = {"tournament_lag1": MGREY, "tournament": BLACK, "tournament_lagcal": ORANGE, "tournament_lag3": BLUE}
    labs = {"tournament_lag1": "lag 1.0 s (stress)", "tournament": "lag 2.0 s (pre-reg.)",
            "tournament_lagcal": "lag 3.14 s (post hoc)", "tournament_lag3": "lag 3.0 s"}
    for ax, period, letter in ((axa, "IS", "a"), (axb, "burned_OOS", "b")):
        ax.set_xscale("log"); ax.set_xlim(0.05, 60)
        for r, col in cols.items():
            c = curves[(r, period)]
            c = c[c.x_s >= 0.05]
            ax.plot(c.x_s, c.pnl_per_day_usd, color=col, lw=1.2, ls="-" if period == "IS" else "--")
        ax.axvline(1.0, color=BLACK, lw=1.0, ls=(0, (1, 1.5)))
        zero_line(ax)
        ax.set_xlabel("feed delay V (s, log scale)")
        ax.set_ylabel("net $ per day")
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:g}"))
        ax.text(0.98, 0.95, "in sample" if period == "IS" else "burned OOS", transform=ax.transAxes, ha="right",
                va="top", fontsize=FS, color=DGREY)
        panel(ax, letter, x=-0.12)
    handles = [Line2D([], [], color=c, lw=1.2, label=labs[r]) for r, c in cols.items()]
    fig.legend(handles=handles, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.0), fontsize=FS,
               handlelength=1.4, columnspacing=1.2, labelspacing=0.15)
    tag(axa, LABEL_CV, x=0.98, y=0.78)
    return save(fig, "figA2_sweep_lags")


def figA4() -> list[str]:
    """Spin-aware tennis landing error vs lead (simulation)."""
    sp = load("results/spin/tennis/key_numbers.json")
    fig = plt.figure(figsize=(FIG_W * 0.62, 2.2))
    ax = fig.add_axes([0.15, 0.22, 0.80, 0.70])
    if not sp:
        pending(ax, "results/spin/tennis/key_numbers.json")
        return save(fig, "figA6_spin_sim")
    for k, col, lab in (("baseline", BLACK, "no-spin baseline"), ("bls", ORANGE, "spin-aware (BLS)"),
                        ("ukf", BLUE, "spin-aware (UKF)")):
        if k not in sp:
            continue
        d = sp[k]["sd_cm"]
        xs = sorted(int(x) for x in d)
        ax.plot(xs, [d[str(x)] for x in xs], color=col, marker="o", ms=3, label=lab)
    ax.set_xlabel("lead before landing (ms)")
    ax.set_ylabel("landing error SD (cm)")
    ax.legend(loc="upper left")
    tag(ax, "simulation", x=0.98, y=0.04, va="bottom")
    return save(fig, "figA6_spin_sim")


def figA5() -> list[str]:
    """Concentration of v2 P&L in the top-k wallets, matches and days."""
    al = load("results/alpha/alpha.json")
    fig = plt.figure(figsize=(FIG_W, 2.0))
    ax = fig.add_axes([0.08, 0.24, 0.90, 0.68])
    if not al:
        pending(ax, "results/alpha/alpha.json")
        return save(fig, "figA5_concentration")
    F = al["F_concentration"]
    cats = []
    for unit in ("wallets", "matches", "days"):
        for k in (1, 5, 10):
            cats.append((unit, k))
    xs = np.arange(len(cats))
    for per, off, fc in (("IS", -0.18, ORANGE), ("OOS", 0.18, "white")):
        if per not in F:
            continue
        ys = [F[per].get(u, {}).get(f"top{k}_share_of_pnl", np.nan) * 100 for u, k in cats]
        ax.bar(xs + off, ys, width=0.34, color=fc, edgecolor=ORANGE, lw=0.8)
    ax.axhline(100, color=DGREY, lw=0.6, ls=":")
    ax.set_xticks(xs)
    ax.set_xticklabels([f"top {k}\n{u}" if k == 5 else f"top {k}" for u, k in cats])
    ax.set_ylabel("share of v2 P&L (%)")
    ax.text(0.99, 0.95, "filled = IS, hollow = OOS", transform=ax.transAxes, ha="right", va="top", fontsize=FS,
            color=DGREY)
    return save(fig, "figA5_concentration")


# keys follow the paper's numbering (Fig. 4 was moved to the appendix as Fig. A1 to keep the main text at 5 pages)
FIGS = {"fig1": fig1, "fig2": fig2, "fig3": fig3, "figA_replay": fig_replay, "figA1": fig4, "figA2": figA3, "figA3": figA1, "figA4": figA2,
        "figA5": figA5, "figA6": figA4}


def main(only: list[str] | None = None) -> dict:
    setup_style()
    written = {}
    for k, f in FIGS.items():
        if only and k not in only:
            continue
        written[k] = f()
        print(f"{k}: {', '.join(written[k])}")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    main(ap.parse_args().only)
