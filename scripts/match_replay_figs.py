#!/usr/bin/env python
"""Paper figures for the match replay (house style: docs/paper/STYLE_GUIDE.md, light background, 11 pt).

    BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not
    purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real
    recorded order book; paper only.

No video of any match was received, bought or watched. Reads results/replay/ (replay.json, points.csv,
seed_fills.csv, selected_match_tob_events.csv.gz, selected_match_trades.csv) and writes

  results/replay/fig_replay_points.{png,pdf}   the race between our order and the book's reprice on four
                                               points of the selected match, at V = 0, 0.5 and 1.0 s
  results/replay/fig_replay_pnl.{png,pdf}      cumulative P&L over the 9 matches at V = 0 / 0.5 / 1.0 s

Example points are picked by display rules written here before drawing (FEATURE_RULES); one of them is
chosen on the replay's own outcome and says so. Nothing here changes a result.

    .venv/bin/python scripts/match_replay_figs.py
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.legend_handler import HandlerTuple  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "replay"
M1 = ROOT / "research/v2/latency/out/m1_points.csv"

# house palette (STYLE_GUIDE "Figure styling"): ours orange, comparisons black / greys
ORANGE, BLACK, DGREY, MGREY, LGREY, GRID = "#F26B21", "#000000", "#555555", "#9A9A9A", "#D4D4D4", "#E5E5E5"
VS = (0.0, 0.5, 1.0)
VCOL = {0.0: BLACK, 0.5: DGREY, 1.0: ORANGE}
FS = 11                                   # every text in the figures is 11 pt at final size
FULL_W = 6.5                              # in


def paper_style() -> str:
    """Source Sans 3 from docs/paper/fonts when the paper build has committed it, else a system sans."""
    fam = None
    fdir = ROOT / "docs/paper/fonts"
    for f in sorted(fdir.glob("SourceSans3-*.ttf")) if fdir.exists() else []:
        font_manager.fontManager.addfont(str(f))
        fam = "Source Sans 3"
    if fam is None:
        for path, name in (("/System/Library/Fonts/HelveticaNeue.ttc", "Helvetica Neue"),):
            if Path(path).exists():
                font_manager.fontManager.addfont(path)
                fam = name
                break
    fam = fam or "DejaVu Sans"
    plt.rcParams.update({
        "font.family": fam, "font.size": FS, "axes.titlesize": FS, "axes.labelsize": FS, "xtick.labelsize": FS,
        "ytick.labelsize": FS, "legend.fontsize": FS, "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "axes.edgecolor": "#333333", "axes.linewidth": 0.6, "xtick.major.width": 0.6,
        "ytick.major.width": 0.6, "xtick.color": "#333333", "ytick.color": "#333333", "axes.labelcolor": BLACK,
        "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "pdf.fonttype": 42,
        "ps.fonttype": 42, "axes.unicode_minus": True, "lines.solid_capstyle": "butt"})
    return fam


def load():
    res = json.loads((OUT / "replay.json").read_text())
    pts = pd.read_csv(OUT / "points.csv")
    sf = pd.read_csv(OUT / "seed_fills.csv", comment="#")
    ev = pd.read_csv(OUT / "selected_match_tob_events.csv.gz", comment="#")
    tr = pd.read_csv(OUT / "selected_match_trades.csv", comment="#")
    return res, pts, sf, ev, tr


SENT = ("filled", "partial", "missed (book already moved)")


def feature_points(res, pts) -> list[dict]:
    """Display rules for the example points of the selected match (no rule looks at P&L except (c), which
    is labelled as chosen on the replay's outcome):
      typical  the V = 1.0 s order whose execution - reprice is closest to the match median at V = 1.0 s
      largest  the largest matched book move (m1 D) among points with an order sent at all three V
      won      the largest matched book move among points whose V = 0 order filled before the reprice
               (chosen on the replay's own outcome, to show a race that is won; not representative)
      wrong    the first simulated wrong call that filled at V = 1.0 s
    """
    sel = res["selected_match"]
    s = pts[pts.slug == sel]
    m1 = pd.read_csv(M1)
    D = dict(zip(m1[m1.slug == sel].n, m1[m1.slug == sel].D))
    st = s.pivot(index="n", columns="V", values="status")
    all_sent = st.index[st.apply(lambda r: all(x in SENT for x in r), axis=1)]
    s1 = s[s.V == 1.0]
    calls1 = s1[~s1.status.str.startswith("skipped") & (s1.status != "no book recorded")]
    med = float(calls1.exec_minus_book_s.median())
    o1 = s1[s1.status.isin(SENT) & s1.exec_minus_book_s.notna()]
    typical = int(o1.loc[(o1.exec_minus_book_s - med).abs().idxmin(), "n"])
    cand = [n for n in all_sent if np.isfinite(D.get(n, np.nan)) and n in set(s1[s1.exec_minus_book_s.notna()].n)]
    largest = int(max(cand, key=lambda n: D[n]))
    s0 = s[(s.V == 0.0) & (s.shares > 1e-9) & (s.beat_book == True) & s.correct_call.astype(bool)]  # noqa: E712
    won = int(max(s0.n, key=lambda n: D.get(n, -1)))
    w1 = s1[(s1.shares > 1e-9) & ~s1.correct_call.astype(bool)]
    wrong = int(w1.n.min())
    return [
        {"n": typical, "key": "typical", "title": f"Point {typical}: typical race at 1 s",
         "rule": f"the V = 1.0 s order whose execution minus reprice is closest to the match median (+{med:.2f} s)"},
        {"n": largest, "key": "largest", "title": f"Point {largest}: largest move, {D[largest] * 100:.1f}c",
         "rule": "the largest matched book move among points with an order sent at all three V"},
        {"n": won, "key": "won", "title": f"Point {won}: picked win at V = 0",
         "rule": "the largest matched book move among points whose V = 0 order filled before the reprice "
                 "(chosen on the replay's own outcome; not representative)"},
        {"n": wrong, "key": "wrong", "title": f"Point {wrong}: simulated wrong call",
         "rule": "the first simulated wrong call that filled at V = 1.0 s"},
    ]


def race_data(res, pts, ev, tr, n: int) -> dict:
    sel = res["selected_match"]
    m = next(x for x in res["matches"] if x["slug"] == sel)
    g = pts[(pts.slug == sel) & (pts.n == n)].set_index("V")
    r = g.loc[1.0]
    b = int(r.bounce_ms)
    tok = 0 if r.called_player == m["n0"] else 1
    col = f"ask{tok}"
    t = ev.t_ms.to_numpy()
    i0 = max(0, np.searchsorted(t, b - 3000, side="right") - 1)
    i1 = np.searchsorted(t, b + 4000, side="right")
    w = ev.iloc[i0:i1]
    trw = tr[(tr.t_ms >= b - 3000) & (tr.t_ms <= b + 4000) & (tr.token == tok)]
    rows = {}
    for V in VS:
        q = g.loc[V]
        rows[V] = {"frame": (q.frame_ms - b) / 1000, "call": (q.call_ms - b) / 1000, "arrive": (q.arrive_ms - b) / 1000,
                   "exec": (q.exec_ms - b) / 1000, "status": q.status, "shares": float(q.shares),
                   "vwap": float(q.vwap) if pd.notna(q.vwap) else np.nan, "ask_exec": float(q.ask_at_exec),
                   "limit": float(q.limit), "pnl_mark": float(q.pnl_mark)}
    return {"n": n, "r": r, "b": b, "tok": tok, "x": (w.t_ms.to_numpy() - b) / 1000, "ask": w[col].to_numpy(),
            "trx": (trw.t_ms.to_numpy() - b) / 1000, "trp": trw.price.to_numpy(),
            "reprice": (r.t_book_srv_ms - b) / 1000 if pd.notna(r.t_book_srv_ms) else np.nan,
            "stamp": (r.T_ms - b) / 1000, "rows": rows, "limit": float(r.limit), "called": r.called_player,
            "winner": r.point_winner_name, "correct": bool(r.correct_call), "score": r.score_after}


XLIM = (-0.75, 2.55)


def race_panel(axp, axl, d, title, letter, show_ylabel, show_xlabel):
    x, a = d["x"], d["ask"]
    xs = np.r_[XLIM[0], x[x > XLIM[0]]]
    ys = np.r_[a[x <= XLIM[0]][-1] if (x <= XLIM[0]).any() else a[0], a[x > XLIM[0]]]
    axp.step(xs, ys, where="post", color=BLACK, lw=1.3, zorder=3)
    axp.axhline(d["limit"], color=ORANGE, lw=1.0, ls=(0, (4, 2)), zorder=2)
    if len(d["trx"]):
        k = (d["trx"] >= XLIM[0]) & (d["trx"] <= XLIM[1])
        axp.scatter(d["trx"][k], d["trp"][k], s=14, color=MGREY, zorder=2, lw=0)
    for ax in (axp, axl):
        if np.isfinite(d["reprice"]):
            ax.axvline(d["reprice"], color=BLACK, lw=1.0, ls=(0, (3, 2)), zorder=1)
        ax.axvline(d["stamp"], color=MGREY, lw=0.9, ls=(0, (1, 1.6)), zorder=1)
        ax.axvline(0, color=LGREY, lw=0.8, zorder=0)
        ax.set_xlim(*XLIM)
    # y range: the ask path in the window, the limit and every execution price
    k = (x >= XLIM[0]) & (x <= XLIM[1])
    vals = list(ys) + [d["limit"]] + [v["vwap"] for v in d["rows"].values() if np.isfinite(v["vwap"])] + \
        [v["ask_exec"] for v in d["rows"].values() if np.isfinite(v["ask_exec"])]
    lo, hi = np.nanmin(vals), np.nanmax(vals)
    lo, hi = np.floor(lo * 100 - 1) / 100, np.ceil(hi * 100 + 1) / 100
    axp.set_ylim(lo - 0.002, hi + 0.002)
    step = 0.01 if hi - lo <= 0.05 else 0.02
    axp.set_yticks(np.round(np.arange(lo, hi + 1e-9, step), 2))
    axp.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.2f}"))
    axp.tick_params(axis="x", labelbottom=False, length=0)
    axp.grid(axis="y", color=GRID, lw=0.4, zorder=0)
    # executions on the price panel: filled at the VWAP, missed at the ask that was there
    for V in VS:
        v = d["rows"][V]
        filled = v["shares"] > 1e-9
        y = v["vwap"] if filled else v["ask_exec"]
        if filled:
            axp.scatter([v["exec"]], [y], s=34, color=ORANGE, edgecolor="white", lw=0.8, zorder=5)
        else:
            axp.scatter([v["exec"]], [y], s=34, marker="X", facecolor="white", edgecolor=ORANGE, lw=1.1, zorder=5)
    # latency lanes: V = 0 on top
    for j, V in enumerate(VS):
        v = d["rows"][V]
        yl = 2 - j
        axl.barh(yl, v["call"] - v["frame"], left=v["frame"], height=0.46, color=LGREY, lw=0, zorder=2)
        axl.barh(yl, v["exec"] - v["call"], left=v["call"], height=0.46, color=MGREY, lw=0, zorder=2)
        filled = v["shares"] > 1e-9
        if filled:
            axl.scatter([v["exec"]], [yl], s=40, color=ORANGE, edgecolor="white", lw=0.8, zorder=5)
        else:
            axl.scatter([v["exec"]], [yl], s=40, marker="X", facecolor="white", edgecolor=ORANGE, lw=1.1, zorder=5)
    axl.set_ylim(-0.6, 2.6)
    axl.set_yticks([2, 1, 0], ["V = 0", "0.5 s", "1 s"])
    axl.tick_params(axis="y", length=0)
    axl.spines["left"].set_visible(False)
    axl.set_xticks([0, 1, 2])
    if show_xlabel:
        axl.set_xlabel("seconds from the assumed landing")
    if show_ylabel:
        axp.set_ylabel("best ask")
    axp.set_title(f"({letter}) {title}", loc="left", fontsize=FS, fontweight="bold", pad=4)


def fig_points(res, pts, ev, tr, label):
    feats = feature_points(res, pts)
    fig = plt.figure(figsize=(FULL_W, 7.3))
    top, bot = 0.825, 0.19
    gs = fig.add_gridspec(2, 2, left=0.105, right=0.985, top=top, bottom=bot, wspace=0.27, hspace=0.36)
    for i, f in enumerate(feats):
        sub = gs[i // 2, i % 2].subgridspec(2, 1, height_ratios=[1.55, 1], hspace=0.08)
        axp = fig.add_subplot(sub[0])
        axl = fig.add_subplot(sub[1], sharex=axp)
        d = race_data(res, pts, ev, tr, f["n"])
        f["data"] = d
        race_panel(axp, axl, d, f["title"], "abcd"[i], i % 2 == 0, i // 2 == 1)
    H = [Line2D([], [], color=BLACK, lw=1.3, drawstyle="steps-post"),
         Line2D([], [], color=ORANGE, lw=1.0, ls=(0, (4, 2))),
         Line2D([], [], color=BLACK, lw=1.0, ls=(0, (3, 2))),
         Line2D([], [], color=MGREY, lw=0.9, ls=(0, (1, 1.6))),
         Line2D([], [], color=MGREY, marker="o", ms=4, lw=0),
         Patch(color=LGREY), Patch(color=MGREY),
         (Line2D([], [], color=ORANGE, marker="o", ms=6.5, lw=0, markeredgecolor="white"),
          Line2D([], [], color=ORANGE, marker="X", ms=7, lw=0, markerfacecolor="white", markeredgewidth=1.1))]
    L = ["best ask of the called player", "our limit: landing ask + 1c", "book reprice (half-move)",
         "umpire stamp: landing + 2 s", "recorded trade", "feed delay V + 20 ms (assumed)",
         "67 ms + 1 s venue taker delay", "order filled / missed"]
    # column-major: left column = the market, right column = our order
    order = [0, 2, 3, 4, 1, 5, 6, 7]
    fig.legend([H[i] for i in order], [L[i] for i in order], loc="upper left", bbox_to_anchor=(0.0, 0.997), ncol=2,
               handlelength=1.7, columnspacing=1.2, handletextpad=0.5, borderaxespad=0.1, labelspacing=0.3,
               handler_map={tuple: HandlerTuple(ndivide=None, pad=0.6)})
    fig.text(0.0, 0.006, "\n".join(textwrap.wrap(label, 84)), fontsize=FS, color=DGREY, ha="left", va="bottom")
    fig.savefig(OUT / "fig_replay_points.png", dpi=300)
    fig.savefig(OUT / "fig_replay_points.pdf")
    plt.close(fig)
    return feats


def cum_path(F: pd.DataFrame, grid: np.ndarray) -> np.ndarray:
    F = F.sort_values("exec_ms")
    c = F.pnl_mark.fillna(0).cumsum().to_numpy()
    i = np.searchsorted(F.exec_ms.to_numpy(), grid, side="right") - 1
    return np.where(i >= 0, c[np.clip(i, 0, None)], 0.0)


def fig_pnl(res, pts, sf, label):
    fig = plt.figure(figsize=(FULL_W, 4.6))
    gs = fig.add_gridspec(1, 2, width_ratios=[2.25, 1], left=0.11, right=0.985, top=0.92, bottom=0.415, wspace=0.36)
    ax, bx = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    pc = {0.0: BLACK, 0.5: MGREY, 1.0: ORANGE}           # V = 0.5 in mid grey so the two grey lines separate
    F0 = pts[pts.shares > 1e-9]
    t0 = int(F0.exec_ms.min()) - 300_000
    t1 = int(F0.exec_ms.max()) + 120_000
    grid = np.arange(t0, t1, 15_000)
    tg = pd.to_datetime(grid, unit="ms", utc=True)
    ends = {}
    for V in VS:
        p0 = cum_path(F0[F0.V == V], grid)
        if V != 0.5:                                   # seed bands for the two ends of the delay range
            paths = np.array([cum_path(g, grid) for _, g in sf[sf.V == V].groupby("seed")])
            ax.fill_between(tg, paths.min(0), paths.max(0), color=pc[V], alpha=0.17 if V == 1.0 else 0.10, lw=0,
                            step="post", zorder=1)
        ax.step(tg, p0, where="post", color=pc[V], lw=1.8 if V == 1.0 else 1.25, zorder=3 if V == 1.0 else 2)
        ends[V] = p0[-1]
    ax.axhline(0, color="#333333", lw=0.6)
    # direct labels right of the line ends, pushed apart in data units (about 1 line of 11 pt text)
    ylo, yhi = -330, 25
    gap = (yhi - ylo) * 0.085
    order = sorted(VS, key=lambda V: ends[V], reverse=True)
    ys, prev = {}, None
    for V in order:
        y = ends[V] if prev is None else min(ends[V], prev - gap)
        ys[V] = prev = y
    xl = tg[-1] + pd.Timedelta(minutes=4)
    for V in VS:
        a = res["headline_by_V"][f"V{V:g}"]["all"]
        ax.text(xl, ys[V], f"{V:g} s  \u2212${-a['pnl_mark_usd']:.0f}", va="center", ha="left", color=pc[V],
                fontweight="bold" if V == 1.0 else "normal")
    ax.set_xlim(tg[0], tg[-1] + pd.Timedelta(minutes=42))
    ax.set_ylim(ylo, yhi)
    ax.set_xticks([pd.Timestamp(f"2026-10-03 {h}:00", tz="UTC") for h in (10, 11, 12)])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="UTC"))
    ax.set_xlabel("UTC, 2026-10-03 (execution time)")
    ax.set_ylabel("cumulative P&L, $")
    ax.grid(axis="y", color=GRID, lw=0.4)
    ax.set_title("(a) 9 matches, marked at +30 s mid", loc="left", fontweight="bold", pad=4)
    # (b) per-share net with match-clustered 95 % CI, marked (filled) and held to the result (open)
    for i, V in enumerate(VS):
        a = res["headline_by_V"][f"V{V:g}"]["all"]
        for k, off, mk in (("mark", -0.14, "o"), ("hold", 0.14, "s")):
            v, ci = a[f"per_share_{k}_c"], a[f"per_share_{k}_ci95_c"]
            bx.errorbar([i + off], [v], yerr=[[v - ci[0]], [ci[1] - v]], fmt=mk, ms=5.5, color=pc[V], lw=1.1,
                        capsize=0, mfc=pc[V] if k == "mark" else "white", mew=1.1)
    bx.axhline(0, color="#333333", lw=0.6)
    bx.set_xticks(range(3), ["0", "0.5", "1"])
    bx.set_xlim(-0.5, 2.5)
    bx.set_ylim(-3.4, 0.25)
    bx.set_xlabel("feed delay V, s")
    bx.set_ylabel("net cents per share")
    bx.grid(axis="y", color=GRID, lw=0.4)
    bx.set_title("(b) per share", loc="left", fontweight="bold", pad=4)
    H = [Line2D([], [], color=DGREY, lw=1.25), Patch(color=DGREY, alpha=0.22),
         Line2D([], [], color=DGREY, marker="o", lw=1.1, ms=5.5),
         Line2D([], [], color=DGREY, marker="s", lw=1.1, ms=5.5, mfc="white", mew=1.1)]
    fig.legend(H, ["seed 0 (the replay shown)", "range over 20 seeds (V = 0, 1 s)",
                   "marked, match-clustered 95% CI", "held to the match result, 95% CI"],
               loc="lower left", bbox_to_anchor=(0.0, 0.13), ncol=2, handlelength=1.5, columnspacing=1.2,
               handletextpad=0.5, labelspacing=0.3)
    fig.text(0.0, 0.006, "\n".join(textwrap.wrap(label, 84)), fontsize=FS, color=DGREY, ha="left", va="bottom")
    fig.savefig(OUT / "fig_replay_pnl.png", dpi=300)
    fig.savefig(OUT / "fig_replay_pnl.pdf")
    plt.close(fig)


def main():
    fam = paper_style()
    res, pts, sf, ev, tr = load()
    label = res["label"]
    feats = fig_points(res, pts, ev, tr, label)
    fig_pnl(res, pts, sf, label)
    print(f"font: {fam}")
    for f in feats:
        print(f"  ({f['key']}) point {f['n']}: {f['rule']}")
    return feats


if __name__ == "__main__":
    main()
