"""Shared figure style for the COURTSIDE paper (v2 figures, scripts/paper_figures_v2.py).

House style, after the research notes of AQR, Man AHL and J.P. Morgan:

* Source Sans 3 (the paper's body face, docs/paper/fonts) at 11-12 pt at final print size (the track's 11 pt
  minimum holds for figure text too: every glyph on the five main pages is >= 11 pt); figures are drawn at their
  printed size (6.5 in wide), so an 11 pt glyph in matplotlib is an 11 pt glyph on the page.
* Palette with fixed meanings: orange #E8601C = our CV strategy / our pipeline; near-black #222 = v2 or the
  pre-registered reading; mid grey #8C8C8C = others / everyone else; light grey shading = OOS periods and source
  bands; red only for losses if a panel needs it. No hatching.
* Lines 1.4-1.8 pt, small markers, thin CI bands or whiskers, light horizontal gridlines (#E6E6E6) only, no top or
  right spines, zero line in light grey. Reference verticals (0.5 / 1 / 3 s) are grey dotted 0.6 pt with muted
  labels, so they never read as a data series. Seed / CI ranges that would overlap are drawn as thin whiskers at a
  few x values, never as overlapping translucent fills (two fills mix into brown).
* IS solid, OOS dashed, everywhere.
* Direct labels at line ends (``direct_label``), de-overlapped in display space; a legend only when that fails.
* Each panel: bold letter top-left plus a short sentence-case takeaway title (``panel``). Captions stay in LaTeX.
* Every figure is written as vector PDF (fonts embedded as TrueType) and a 300 dpi PNG (``save_fig``), and
  ``save_fig`` reports any two text boxes that overlap or any text that leaves the canvas.

Import:  sys.path.insert(0, "docs/paper"); import figstyle as fs; fs.apply()
"""
from __future__ import annotations

import itertools
import math
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.text import Text  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "docs/paper/fonts"

# ------------------------------------------------------------------------------------------------ palette
ORANGE = "#E8601C"        # our CV strategy / our pipeline
ORANGE_LIGHT = "#F4AE88"  # a second reading of ours (e.g. a nearby stamp lag), only next to ORANGE
ORANGE_LIGHT_TEXT = "#D9824F"  # ORANGE_LIGHT is too pale for 9 pt text: its labels use this
INK = "#222222"           # v2 / pre-registered reading only (not a generic dark series colour)
GREY = "#8C8C8C"          # others / everyone else / any secondary series
GREY_LIGHT = "#B8B8B8"    # placeholder frames only: never a line, marker or bar colour (vanishes in print)
SHADE = "#EFEFEF"         # OOS period shading
BAND = "#E2E2E2"          # source / range bands
GRID = "#E6E6E6"
ZERO = "#B5B5B5"          # zero line
AXIS = "#4A4A4A"          # spines and ticks
MUTED = "#6B6B6B"         # annotation text
RED = "#C0392B"           # losses only, if needed
WHITE = "#FFFFFF"

# ------------------------------------------------------------------------------------------------ type
FS = 11.0         # axis labels, tick labels, direct labels (the track's 11 pt minimum applies to figure text)
FS_SMALL = 11.0   # annotations, value labels: never below 11 pt
FS_TITLE = 12.0   # panel letter and takeaway title
FIG_W = 6.5       # text width, inches

LW = 1.6          # primary lines
LW_2 = 1.4        # secondary lines
LW_REF = 0.8      # reference / leader lines
MS = 3.0          # marker size (points)

MINUS = "−"
THIN = " "
NDASH = "–"
TIMES = "×"
CENT = "¢"
RSQUO = "’"

IS_LS = "-"
OOS_LS = (0, (4.0, 2.2))
DOT_LS = (0, (1.0, 1.8))


def apply() -> None:
    """Register the paper's fonts and set the rcParams every v2 figure uses."""
    fam = "DejaVu Sans"
    for f in ("SourceSans3-Regular.ttf", "SourceSans3-It.ttf", "SourceSans3-Semibold.ttf",
              "SourceSans3-SemiboldIt.ttf"):
        p = FONTS / f
        if p.exists():
            font_manager.fontManager.addfont(str(p))
            fam = "Source Sans 3"
    plt.rcParams.update({
        "font.family": fam, "font.size": FS,
        "axes.labelsize": FS, "axes.titlesize": FS_TITLE, "xtick.labelsize": FS, "ytick.labelsize": FS,
        "legend.fontsize": FS_SMALL, "figure.titlesize": FS_TITLE,
        "mathtext.fontset": "custom", "mathtext.rm": fam, "mathtext.it": f"{fam}:italic",
        "mathtext.bf": f"{fam}:semibold", "mathtext.sf": fam,
        "axes.unicode_minus": True,
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "axes.edgecolor": AXIS, "axes.linewidth": 0.6, "axes.labelcolor": INK, "text.color": INK,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False,
        "axes.axisbelow": True,
        "xtick.color": AXIS, "ytick.color": AXIS, "xtick.labelcolor": INK, "ytick.labelcolor": INK,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.minor.width": 0.4, "ytick.minor.width": 0.4,
        "xtick.major.size": 2.6, "ytick.major.size": 2.6, "xtick.minor.size": 1.5, "ytick.minor.size": 1.5,
        "xtick.major.pad": 2.2, "ytick.major.pad": 2.2,
        "axes.labelpad": 3.0, "lines.linewidth": LW, "lines.markersize": MS, "lines.solid_capstyle": "butt",
        "lines.dash_capstyle": "butt", "patch.linewidth": 0.0,
        "legend.frameon": False, "legend.handlelength": 1.8, "legend.borderaxespad": 0.2,
        "legend.handletextpad": 0.4, "legend.columnspacing": 1.0, "legend.labelspacing": 0.25,
        "savefig.dpi": 300,
    })


# ------------------------------------------------------------------------------------------------ numbers
def r(x: float, nd: int = 1) -> float:
    """Round half up on the decimal value as written (11.95 -> 12.0), not on its binary approximation (Python's
    f-string gives 11.9). Every number printed in a figure goes through this."""
    q = Decimal(1).scaleb(-nd)
    return float(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP))


def f(x: float, nd: int = 1) -> str:
    """``x`` with ``nd`` decimals, rounded half up, true minus sign."""
    return f"{r(x, nd):.{nd}f}".replace("-", MINUS)


def num(x: float, nd: int = 1, sign: bool = False) -> str:
    """Number with a true minus sign (rounded half up); ``sign`` adds a plus to positives."""
    v = r(x, nd)
    s = f"{v:+,.{nd}f}" if sign else f"{v:,.{nd}f}"
    return s.replace("-", MINUS)


def usd(x: float, nd: int = 0, sign: bool = False, k: bool = False) -> str:
    """$ amount with a true minus sign before the dollar ('−$75'); ``k`` writes thousands as '$40.4k'."""
    v = r(abs(x) / 1e3 if k else abs(x), nd)
    body = f"${v:,.{nd}f}" + ("k" if k else "")
    if x < 0:
        return MINUS + body
    return ("+" if sign else "") + body


def unit(v: str, u: str) -> str:
    """Value and unit joined by a thin space ('46 ms')."""
    return f"{v}{THIN}{u}"


# ------------------------------------------------------------------------------------------------ layout
def axes_in(fig, left: float, bottom: float, width: float, height: float):
    """Add axes placed in inches from the figure's bottom-left corner."""
    W, H = fig.get_size_inches()
    return fig.add_axes([left / W, bottom / H, width / W, height / H])


def panel(ax, letter: str, title: str = "", dx_in: float = -0.42, dy_in: float = 0.10, fig=None,
          x_in: float | None = None, y_in: float | None = None) -> None:
    """Bold panel letter at the top-left of the panel box and a sentence-case takeaway title after it.

    ``dx_in`` is the letter's offset from the axes' left edge (negative = into the y-label margin), so the letter
    sits at the panel's real top-left corner, not at the plot frame; ``x_in`` / ``y_in`` place the letter's left
    edge / baseline at absolute figure inches instead. An empty ``letter`` writes only the title."""
    fig = fig or ax.figure
    W, H = fig.get_size_inches()
    bb = ax.get_position()
    x = (x_in / W) if x_in is not None else bb.x0 + dx_in / W
    y = (y_in / H) if y_in is not None else bb.y1 + dy_in / H
    if letter:
        fig.text(x, y, letter, ha="left", va="baseline", fontsize=FS_TITLE, fontweight="semibold", color=INK)
    if title:
        fig.text(x + (0.155 / W if letter else 0.0), y, title, ha="left", va="baseline", fontsize=FS_TITLE,
                 color=INK)


def hgrid(ax, axis: str = "y") -> None:
    """Light horizontal gridlines behind the data (the house style has no vertical gridlines)."""
    ax.grid(True, axis=axis, color=GRID, lw=0.5, zorder=0)
    ax.set_axisbelow(True)


def zero_line(ax, y: float = 0.0, axis: str = "y") -> None:
    if axis == "y":
        ax.axhline(y, color=ZERO, lw=0.7, zorder=1.5)
    else:
        ax.axvline(y, color=ZERO, lw=0.7, zorder=1.5)


def despine(ax, left: bool = True, bottom: bool = True) -> None:
    ax.spines["left"].set_visible(left)
    ax.spines["bottom"].set_visible(bottom)


def add_ci_band(ax, x, lo, hi, color: str, alpha: float = 0.16, zorder: float = 1.0, **kw):
    """A thin confidence / seed band (no edge)."""
    return ax.fill_between(np.asarray(x), np.asarray(lo, float), np.asarray(hi, float), color=color, alpha=alpha,
                           lw=0, zorder=zorder, **kw)


def whiskers(ax, x, y, lo, hi, color: str, horizontal: bool = False, lw: float = 0.9, zorder: float = 3):
    """CI whiskers without caps."""
    x, y, lo, hi = (np.atleast_1d(np.asarray(v, float)) for v in (x, y, lo, hi))
    for xi, yi, a, b in zip(x, y, lo, hi):
        if horizontal:
            ax.plot([a, b], [yi, yi], color=color, lw=lw, zorder=zorder, solid_capstyle="butt")
        else:
            ax.plot([xi, xi], [a, b], color=color, lw=lw, zorder=zorder, solid_capstyle="butt")


def oos_shade(ax, start, end=None, label: str | None = "OOS", y: float = 1.0, color: str = SHADE,
              label_ha: str = "left", pad_pt: float = 0.0, va: str = "bottom", dy_pt: float = 1.5) -> None:
    """Light grey shading over the out-of-sample period; its label sits just above the plot frame (outside the
    data) at the start of the period by default (``y`` < 1 with ``va='top'`` puts it inside)."""
    start = float(np.asarray(ax.convert_xunits(start), float))
    end = ax.get_xlim()[1] if end is None else float(np.asarray(ax.convert_xunits(end), float))
    xl = ax.get_xlim()
    ax.axvspan(start, end, color=color, lw=0, zorder=0)
    ax.set_xlim(xl)
    if label:
        x = start if label_ha == "left" else end
        off = pad_pt if label_ha == "left" else -pad_pt
        ax.annotate(label, xy=(x, y), xycoords=("data", "axes fraction"), xytext=(off, dy_pt if va == "bottom"
                    else -dy_pt), textcoords="offset points", ha=label_ha, va=va, fontsize=FS_SMALL, color=MUTED,
                    zorder=6, annotation_clip=False)


LW_VREF = 0.6     # reference verticals (0.5 / 1 / 3 s, requirements): grey, thinner than any data line
REF = GREY        # their colour: never INK, which is reserved for v2 / the pre-registered reading


def vref(ax, x: float, color: str = REF, ls=DOT_LS, lw: float = LW_VREF, zorder: float = 2.5) -> None:
    """Dotted vertical reference line (grey, 0.6 pt)."""
    ax.axvline(x, color=color, ls=ls, lw=lw, zorder=zorder)


def vref_labelled(ax, refs, color: str = REF, lw: float = LW_VREF, tier_pt: float = 11.0, pad_pt: float = 1.5,
                  fontsize: float = FS_SMALL, label_color: str = MUTED) -> None:
    """Dotted grey verticals with muted labels above the frame, every label LEFT-aligned at its own line.

    ``refs``: iterable of (x, label, tier). Tier 1 sits just above the frame, tier 2 one line higher; each line is
    continued (dotted, outside the frame) up to its own label's baseline, so a label that runs across another
    line's x is on a different tier and is never read as that line's label."""
    fig = ax.figure
    h_in = ax.get_position().height * fig.get_size_inches()[1]
    tr = ax.get_xaxis_transform()
    for x, lab, tier in refs:
        ax.axvline(x, color=color, ls=DOT_LS, lw=lw, zorder=2.5)
        dy_pt = pad_pt + (tier - 1) * tier_pt
        top = 1.0 + (dy_pt + 0.35 * fontsize) / 72.0 / h_in
        ax.plot([x, x], [1.0, top], transform=tr, color=color, ls=DOT_LS, lw=lw, clip_on=False, zorder=2.5)
        ax.annotate(lab, xy=(x, 1.0), xycoords=tr, xytext=(2.0, dy_pt), textcoords="offset points", ha="left",
                    va="bottom", fontsize=fontsize, color=label_color, annotation_clip=False)


def _fmt_tick(v, _pos=None) -> str:
    if v == 0:
        return "0"
    s = f"{v:g}"
    return s.replace("-", MINUS)


def log_time_axis(ax, which: str = "x", ticks=(0.1, 0.5, 1, 3, 10, 60), lim=None, label: str | None = None,
                  fmt=None) -> None:
    """Log axis with clean, explicit ticks (no minor ticks, no 10^n labels)."""
    if which == "x":
        ax.set_xscale("log")
        axis = ax.xaxis
        if lim:
            ax.set_xlim(*lim)
        if label is not None:
            ax.set_xlabel(label)
    else:
        ax.set_yscale("log")
        axis = ax.yaxis
        if lim:
            ax.set_ylim(*lim)
        if label is not None:
            ax.set_ylabel(label)
    axis.set_major_locator(FixedLocator(list(ticks)))
    axis.set_minor_locator(NullLocator())
    axis.set_major_formatter(FuncFormatter(fmt or _fmt_tick))


def unicode_ticks(ax, axis: str = "both", fmt=None) -> None:
    """Tick labels with true minus signs and no trailing zeros (fixed to the current tick positions)."""
    f = FuncFormatter(fmt or _fmt_tick)
    if axis in ("x", "both"):
        ax.xaxis.set_major_formatter(f)
    if axis in ("y", "both"):
        ax.yaxis.set_major_formatter(f)


def placeholder(ax, what: str, note: str = "") -> None:
    """A clearly marked placeholder panel for an input that is not there yet (never a made-up value)."""
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(True)
        sp.set_color(GREY_LIGHT)
        sp.set_linestyle((0, (3, 2)))
        sp.set_linewidth(0.6)
    ax.set_facecolor("#FAFAFA")
    ax.text(0.5, 0.56, "PLACEHOLDER", transform=ax.transAxes, ha="center", va="bottom", fontsize=FS,
            fontweight="semibold", color=MUTED)
    ax.text(0.5, 0.50, f"waiting for {what}" + (f"\n{note}" if note else ""), transform=ax.transAxes,
            ha="center", va="top", fontsize=FS_SMALL, color=MUTED, style="italic", linespacing=1.2)


def tag(ax, text: str, x: float = 0.99, y: float = 0.02, ha: str = "right", va: str = "bottom",
        color: str = MUTED) -> None:
    """A short muted honesty tag inside the axes (e.g. 'simulated')."""
    ax.text(x, y, text, transform=ax.transAxes, ha=ha, va=va, fontsize=FS_SMALL, style="italic", color=color,
            zorder=8)


# ------------------------------------------------------------------------------------------------ labels
def halo(width: float = 2.4, color: str = "white"):
    """Path effect that knocks a thin white outline around text, so a reference line or band behind a label
    is interrupted instead of crossing the glyphs."""
    from matplotlib import patheffects
    return [patheffects.withStroke(linewidth=width, foreground=color)]


def knockout(pad: float = 0.8, color: str = "white") -> dict:
    """A borderless background box for a label that a reference line or gridline would otherwise cross (a halo
    leaves the line visible in the gaps between glyphs; this interrupts it for the whole word)."""
    return dict(boxstyle=f"square,pad={pad / 10:g}", facecolor=color, edgecolor="none")


def direct_label(ax, items, dx_pt: float = 4.0, gap_pt: float | None = None, ha: str = "left",
                 bounds=None, leader: bool | None = None, leader_min_pt: float = 5.0, fontsize: float = FS,
                 pad_pt: float = 1.0, **text_kw):
    """Place direct labels next to line ends (or any anchor) with no vertical overlap.

    items: iterable of dicts {x, y, text, color[, dy_pt, weight]} in data coordinates. Each label wants to sit at its
    anchor's height (plus ``dy_pt``), ``dx_pt`` points to the right (``ha='left'``) or left (``ha='right'``). Labels are
    sorted by height and pushed apart in display space so that neighbours are at least one line height apart and
    all stay inside ``bounds`` (axes-fraction (lo, hi) for the label centres, default the axes). A label moved more
    than ``leader_min_pt`` gets a thin leader line back to its anchor (``leader=False`` disables it). ``pad_pt`` is
    the extra white space between neighbouring labels.
    Call it after the axis limits are final: the offsets are computed in display space at call time.
    Returns the list of created annotations."""
    items = [dict(it) for it in items]
    if not items:
        return []
    fig = ax.figure
    fig.canvas.draw()  # transforms must be final
    to_pt = 72.0 / fig.dpi
    trans = ax.transData
    ax_bb = ax.get_window_extent()
    lo_b, hi_b = bounds if bounds else (0.0, 1.0)
    lo_px = ax_bb.y0 + lo_b * ax_bb.height
    hi_px = ax_bb.y0 + hi_b * ax_bb.height
    for it in items:
        it["x"] = float(np.asarray(ax.convert_xunits(it["x"]), float))  # dates and categories -> floats
        it["y"] = float(np.asarray(ax.convert_yunits(it["y"]), float))
        x_px, y_px = trans.transform((it["x"], it["y"]))
        it["ax_px"], it["ay_px"] = x_px, y_px
        nl = it["text"].count("\n") + 1
        it["h_px"] = (fontsize * 1.18 * nl) / to_pt
        it["want_px"] = y_px + it.get("dy_pt", 0.0) / to_pt
    gap_px = None if gap_pt is None else gap_pt / to_pt
    order = sorted(range(len(items)), key=lambda i: items[i]["want_px"])
    pos = [items[i]["want_px"] for i in order]
    hs = [items[i]["h_px"] for i in order]

    def need(a, b):
        return gap_px if gap_px is not None else (hs[a] + hs[b]) / 2 + pad_pt / to_pt

    for _ in range(50):  # relax: push up, clip at top, push down, clip at bottom
        moved = False
        for k in range(1, len(pos)):
            if pos[k] - pos[k - 1] < need(k, k - 1):
                pos[k] = pos[k - 1] + need(k, k - 1)
                moved = True
        if pos[-1] > hi_px - hs[-1] / 2:
            pos[-1] = hi_px - hs[-1] / 2
            moved = True
        for k in range(len(pos) - 2, -1, -1):
            if pos[k + 1] - pos[k] < need(k + 1, k):
                pos[k] = pos[k + 1] - need(k + 1, k)
                moved = True
        if pos[0] < lo_px + hs[0] / 2:
            pos[0] = lo_px + hs[0] / 2
            moved = True
        if not moved:
            break
    out = []
    for k, i in enumerate(order):
        it = items[i]
        dy_px = pos[k] - it["ay_px"]
        dy = dy_pt_val = dy_px * to_pt
        dx = dx_pt if ha == "left" else -dx_pt
        moved_far = abs(dy_pt_val - it.get("dy_pt", 0.0)) > leader_min_pt
        use_leader = moved_far if leader is None else (leader and moved_far)
        arrow = dict(arrowstyle="-", color=it.get("color", INK), lw=0.5, shrinkA=0, shrinkB=1.5) if use_leader else None
        a = ax.annotate(it["text"], xy=(it["x"], it["y"]), xytext=(dx, dy), textcoords="offset points",
                        ha=ha, va="center", fontsize=fontsize, color=it.get("color", INK),
                        fontweight=it.get("weight", "normal"), annotation_clip=False, arrowprops=arrow,
                        zorder=9, **text_kw)
        out.append(a)
    return out


# ------------------------------------------------------------------------------------------------ checks
def text_boxes(fig):
    """(text, bbox) for every visible, non-empty text artist in the figure (after a draw)."""
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    out = []
    for t in fig.findobj(Text):
        if not t.get_visible() or not t.get_text().strip():
            continue
        try:
            bb = t.get_window_extent(r)
        except Exception:  # noqa: BLE001
            continue
        if bb.width <= 0 or bb.height <= 0:
            continue
        out.append((t.get_text(), bb))
    return out


def layout_problems(fig, tol_px: float = 0.5) -> list[str]:
    """Overlapping text boxes and text outside the canvas, as human-readable lines (empty = clean)."""
    # matplotlib's text box is the full line box (ascent + descent + leading, about 1.3 em); the inked glyphs fill
    # roughly its middle 70 %, so the check uses that inner box: still conservative, but neighbouring 9 pt rows
    # 0.14 in apart are not flagged
    boxes = []
    for txt, bb in text_boxes(fig):
        shrink = 0.15 * bb.height
        boxes.append((txt, bb.from_extents(bb.x0, bb.y0 + shrink, bb.x1, bb.y1 - shrink)))
    W, H = fig.canvas.get_width_height()
    probs = []
    for t in fig.findobj(Text):  # the house range is 11-12 pt at print size
        if t.get_visible() and t.get_text().strip() and not (FS_SMALL - 1e-6 <= t.get_fontsize() <= FS_TITLE + 1e-6):
            probs.append(f"font {t.get_fontsize():g} pt: {t.get_text()!r}")
    for txt, bb in boxes:
        if bb.x0 < -tol_px or bb.y0 < -tol_px or bb.x1 > W + tol_px or bb.y1 > H + tol_px:
            probs.append(f"outside canvas: {txt!r}")
    for (t1, b1), (t2, b2) in itertools.combinations(boxes, 2):
        ix = min(b1.x1, b2.x1) - max(b1.x0, b2.x0)
        iy = min(b1.y1, b2.y1) - max(b1.y0, b2.y0)
        if ix > tol_px and iy > tol_px:
            probs.append(f"overlap: {t1!r} x {t2!r}")
    return probs


def save_fig(fig, name: str, outdir: Path, check: bool = True, meta: dict | None = None) -> list[str]:
    """Write ``name``.pdf (vector, exact figure size, TrueType fonts) and ``name``.png (300 dpi).

    The figure is never cropped (no bbox_inches), so text keeps its point size when LaTeX places the PDF at 6.5 in.
    Returns the written paths relative to the repo root and prints any layout problem."""
    outdir.mkdir(parents=True, exist_ok=True)
    if check:
        for p in layout_problems(fig):
            print(f"  [layout] {name}: {p}")
    md = {"Creator": "scripts/paper_figures_v2.py", "Title": name}
    if meta:
        md.update(meta)
    pdf, png = outdir / f"{name}.pdf", outdir / f"{name}.png"
    fig.savefig(pdf, metadata=md)
    fig.savefig(png, dpi=300)
    plt.close(fig)
    out = []
    for p in (pdf, png):
        try:
            out.append(str(p.relative_to(ROOT)))
        except ValueError:
            out.append(str(p))
    return out


def log_ticks_between(lo: float, hi: float, candidates=(0.01, 0.05, 0.1, 0.5, 1, 3, 10, 60)) -> list[float]:
    return [c for c in candidates if lo <= c <= hi]


def nice_ceil(x: float, step: float) -> float:
    return math.ceil(x / step) * step
