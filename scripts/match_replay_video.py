#!/usr/bin/env python
"""Demo video of the match replay: results/replay/replay_match.mp4 (1920x1080, 30 fps, 44.4 s).

    BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not
    purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real
    recorded order book; paper only.

No video of the match was received, bought or watched; the video shows the recorded ORDER BOOK, the official
point stamps and the simulated orders, never match footage. Everything drawn comes from results/replay/
(points.csv, selected_match_book.csv, selected_match_tob_events.csv.gz, selected_match_trades.csv,
seed_fills.csv, replay.json). The three slowed-down points are picked by the display rules in
scripts/match_replay_figs.py (feature_points); one of them is chosen on the replay's outcome and says so on
screen.

Frames are drawn with matplotlib and piped to ffmpeg (one python + one ffmpeg process).

    nice -n 10 .venv/bin/python scripts/match_replay_video.py               # full render
    nice -n 10 .venv/bin/python scripts/match_replay_video.py --stills DIR  # a few PNG stills for checking
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import match_replay_figs as MF  # noqa: E402

OUT = ROOT / "results" / "replay"
W, H, DPI, FPS = 1920, 1080, 100, 30

# docs/live palette: navy, blue fast tier, coral losses, amber warnings
BG, PANEL, LINE, INK, MUTED = "#07111b", "#0d1b29", "#1c2e40", "#e8eef4", "#8fa2b5"
COURT, FAST, CORAL, GOOD, AMBER = "#27598b", "#3987e5", "#f06a52", "#3fb67f", "#f2b33d"
DIM = "#4f6478"

RIBBON = ("BACKTEST REPLAY  ·  real match recorded live 2026-10-03  ·  assumed 1 s licensed feed  ·  "
          "fills vs the real order book  ·  paper only")
FOOT1 = ("Assumed: 1 s licensed video feed (not purchased; no match video was received)  ·  ball landing = official "
         "umpire stamp − 2.0 s stamp lag  ·  CV call 95 % precision, wrong calls simulated (seed 0)  ·  20 ms inference"
         "  ·  67 ms network  ·  1 s venue taker delay")
FOOT2 = ("Real: official WTA point stamps and winners  ·  Polymarket order book and trades recorded live on 2026-10-03"
         "  ·  every fill priced against that recorded book  ·  no order was sent  ·  paper only")

TITLE_S, MAIN_S, END_S = 3.4, 33.0, 8.0
HOLD_S = 1.5                  # main scene holds the final state at the end
XF = 10                       # crossfade frames between segments
RACE_X = (-0.6, 3.15)         # race strip, seconds from the assumed landing
WIN_S = 540.0                 # main chart window, match seconds
NOW_AT = 0.8                  # "now" at 80 % of the window
RAMP_S = 5.0                  # log-speed ramp into / out of a slowed point, match seconds
SENT = ("filled", "partial", "missed (book already moved)")


# ----------------------------------------------------------------------------------------------- helpers
def fonts():
    fam = {"display": "DejaVu Sans", "body": "DejaVu Sans", "mono": "DejaVu Sans Mono"}
    for path, key, name in (("/System/Library/Fonts/Avenir Next Condensed.ttc", "display", "Avenir Next Condensed"),
                            ("/System/Library/Fonts/Avenir Next.ttc", "body", "Avenir Next"),
                            ("/System/Library/Fonts/Menlo.ttc", "mono", "Menlo")):
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            fam[key] = name
    plt.rcParams.update({"axes.unicode_minus": True, "font.family": fam["body"], "text.color": INK,
                         "axes.edgecolor": LINE, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.facecolor": PANEL, "figure.facecolor": BG, "savefig.facecolor": BG})
    return fam


F = {}


def pt(px):
    return px * 72.0 / DPI


def fx(x):
    return x / W


def fy(y):
    return 1 - y / H


def rect(x, y, w, h):
    return [x / W, 1 - (y + h) / H, w / W, h / H]


def ftxt(fig, x, y, s, size, color=INK, font="body", weight="normal", ha="left", va="baseline", **kw):
    return fig.text(fx(x), fy(y), s, fontsize=pt(size), color=color, family=F[font], fontweight=weight, ha=ha,
                    va=va, parse_math=False, **kw)


def panel(fig, x, y, w, h, fc=PANEL, ec=LINE, lw=1.2, r=14, alpha=1.0, z=-1):
    p = FancyBboxPatch((fx(x), fy(y + h)), w / W, h / H, boxstyle=f"round,pad=0,rounding_size={r / W}",
                       transform=fig.transFigure, fc=fc, ec=ec, lw=lw, alpha=alpha, zorder=z)
    fig.patches.append(p)
    return p


def money(x, nd=2):
    s = f"${abs(x):,.{nd}f}"
    return ("−" if x < -0.5 * 10 ** -nd else "+" if x > 0.5 * 10 ** -nd else "") + s


def ease(u):
    u = min(max(u, 0.0), 1.0)
    return 1 - (1 - u) ** 3


def grab(fig):
    fig.canvas.draw()
    return np.asarray(fig.canvas.buffer_rgba())[:, :, :3].copy()


def lerp_img(a, b, k):
    return (a.astype(np.float32) * (1 - k) + b.astype(np.float32) * k).astype(np.uint8)


def short(name):
    return name.split()[-1]


# ----------------------------------------------------------------------------------------------- data
def load():
    res, pts, sf, ev, tr = MF.load()
    tl = pd.read_csv(OUT / "selected_match_book.csv", comment="#")
    sel = res["selected_match"]
    m = next(x for x in res["matches"] if x["slug"] == sel)
    S = pts[pts.slug == sel]
    feats = MF.feature_points(res, pts)
    return res, pts, sf, ev, tr, tl, m, S, feats


def build(res, pts, ev, tr, tl, m, S, feats):
    g1 = S[S.V == 1.0].sort_values("n").reset_index(drop=True)
    by_v = {V: S[S.V == V].set_index("n") for V in MF.VS}
    t0 = int(g1.T_ms.min()) - 25_000
    t1 = int(g1.T_ms.max()) + 32_000
    feat_n = {f["n"]: f for f in feats if f["key"] in ("wrong", "typical", "won")}
    # games per set, from the official game-ending points
    games, score = [], {}
    for r in g1.itertuples():
        sc = score.setdefault(r.set, [0, 0])
        if r.game_end:
            sc[0 if r.point_winner_name == m["n0"] else 1] += 1
        games.append((r.set, sc[0], sc[1]))
    g1["games_after"] = games
    # races (one per order sent at V = 1 s, and the featured points)
    orders = g1[g1.status.isin(SENT) | g1.n.isin(list(feat_n))].copy()
    E_t = ev.t_ms.to_numpy()
    races = []
    for r in orders.itertuples():
        b = int(r.bounce_ms)
        tok = 0 if r.called_player == m["n0"] else 1
        i0 = max(0, np.searchsorted(E_t, b + RACE_X[0] * 1000 - 500, side="right") - 1)
        i1 = np.searchsorted(E_t, b + RACE_X[1] * 1000 + 500, side="right")
        w = ev.iloc[i0:i1]
        trw = tr[(tr.t_ms >= b + RACE_X[0] * 1000) & (tr.t_ms <= b + RACE_X[1] * 1000) & (tr.token == tok)]
        lanes = {}
        for V in MF.VS:
            q = by_v[V].loc[r.n]
            lanes[V] = {"frame": (q.frame_ms - b) / 1000, "call": (q.call_ms - b) / 1000,
                        "arrive": (q.arrive_ms - b) / 1000, "exec": (q.exec_ms - b) / 1000, "status": q.status,
                        "shares": float(q.shares), "vwap": float(q.vwap) if pd.notna(q.vwap) else np.nan,
                        "ask_exec": float(q.ask_at_exec) if pd.notna(q.ask_at_exec) else np.nan,
                        "limit": float(q.limit) if pd.notna(q.limit) else np.nan,
                        "pnl_mark": float(q.pnl_mark) if pd.notna(q.pnl_mark) else 0.0}
        x = (w.t_ms.to_numpy() - b) / 1000
        a = w[f"ask{tok}"].to_numpy()
        vals = [v for v in a[(x >= RACE_X[0]) & (x <= RACE_X[1])] if np.isfinite(v)]
        vals += [r.limit] + [lanes[V]["vwap"] for V in MF.VS if np.isfinite(lanes[V]["vwap"])]
        vals += [lanes[V]["ask_exec"] for V in MF.VS if np.isfinite(lanes[V]["ask_exec"])]
        lo, hi = np.nanmin(vals), np.nanmax(vals)
        races.append({
            "n": int(r.n), "b": b, "T": int(r.T_ms), "exec": int(r.exec_ms), "call": int(r.call_ms), "tok": tok,
            "x": x, "ask": a, "trx": (trw.t_ms.to_numpy() - b) / 1000, "trp": trw.price.to_numpy(),
            "reprice": (r.t_book_srv_ms - b) / 1000 if pd.notna(r.t_book_srv_ms) else np.nan,
            "stamp": (r.T_ms - b) / 1000, "limit": float(r.limit), "lanes": lanes, "called": r.called_player,
            "winner": r.point_winner_name, "correct": bool(r.correct_call), "score": r.score_after,
            "set": int(r.set), "game": int(r.game), "status": r.status, "shares": float(r.shares),
            "vwap": float(r.vwap) if pd.notna(r.vwap) else np.nan, "pnl_mark": float(r.pnl_mark) if pd.notna(r.pnl_mark) else 0.0,
            "emb": float(r.exec_minus_book_s) if pd.notna(r.exec_minus_book_s) else np.nan,
            "ylo": np.floor(lo * 100 - 1) / 100, "yhi": np.ceil(hi * 100 + 1) / 100,
            "feature": feat_n.get(int(r.n)), "sent": r.status in SENT})
    return g1, races, t0, t1, feat_n


def time_map(t0, t1, races, main_s):
    """Video seconds <-> match ms. Fast-forward at a constant speed except around the featured points, which play
    in real time; the speed ramps in log space over RAMP_S match seconds on each side."""
    tt = np.arange(t0, t1 + 1, 10, dtype=np.float64)            # 10 ms grid
    w = np.ones_like(tt)                                          # 1 = full fast-forward, 0 = real time
    for r in races:
        if not r["feature"]:
            continue
        a = r["b"] + RACE_X[0] * 1000
        b = r["b"] + (r["lanes"][1.0]["exec"] + 1.05) * 1000
        d = np.maximum(np.maximum(a - tt, tt - b), 0) / 1000 / RAMP_S
        w = np.minimum(w, np.clip(d, 0, 1))

    def total(Sf):
        sp = np.exp(np.log(Sf) * w)
        return np.concatenate([[0], np.cumsum(0.010 / sp[:-1])]), sp

    lo, hi = 2.0, 5000.0
    for _ in range(60):
        mid = np.sqrt(lo * hi)
        v, _ = total(mid)
        lo, hi = (mid, hi) if v[-1] > main_s else (lo, mid)
    v, sp = total(np.sqrt(lo * hi))
    return tt, v, sp, float(np.sqrt(lo * hi))


# ----------------------------------------------------------------------------------------------- title card
class Title:
    def __init__(self, res, m, tl, ribbon_label):
        self.fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
        fig = self.fig
        bgax = fig.add_axes([0, 0, 1, 1], facecolor=BG)
        bgax.set_axis_off()
        x = (tl.t_ms.to_numpy() - tl.t_ms.iloc[0]) / 1000
        bgax.plot(x, tl.mid0, color=FAST, lw=2.2, alpha=0.13)
        bgax.fill_between(x, tl.bid0, tl.ask0, color=FAST, alpha=0.06, lw=0)
        bgax.set_xlim(x[0], x[-1])
        bgax.set_ylim(-0.25, 1.15)
        self.items = []
        a = ftxt(fig, 120, 300, "COURTSIDE  ·  MATCH REPLAY", 30, FAST, "display", "bold")
        b = ftxt(fig, 116, 400, f"{m['n0']} v {m['n1']}", 92, INK, "display", "bold")
        c = ftxt(fig, 120, 462, f"WTA Beijing  ·  {m['points']} official points  ·  Polymarket order book recorded "
                 f"live on 2026-10-03 ({m['first_T'][11:16]}–{m['last_T'][11:16]} UTC)", 25, MUTED)
        d = ftxt(fig, 120, 548, "If a licensed video feed showed each point 1 second late, could a computer-vision "
                 "call still beat the order book?", 30, INK)
        chips = ["ball landing = umpire stamp − 2.0 s (assumed)", "1.0 s licensed feed (assumed, not purchased)",
                 "CV call 95 % precision, wrong calls simulated", "67 ms network + 1 s venue taker delay",
                 "fills priced against the real recorded book"]
        cx, cy = 120, 610
        ch = []
        ren = fig.canvas.get_renderer()
        for s in chips:
            t = ftxt(fig, cx, cy + 30, s, 18, INK if "real" in s else MUTED, ha="center")
            wpx = t.get_window_extent(ren).width + 40
            if cx + wpx > 1800:
                cx, cy = 120, cy + 60
            t.set_position((fx(cx + wpx / 2), fy(cy + 30)))
            p = panel(fig, cx, cy, wpx, 46, fc=PANEL, ec=LINE, r=23)
            ch.append((p, t))
            cx += wpx + 14
        nv = ftxt(fig, 120, 760, "No match video was received or used. What you see is the recorded Polymarket order "
                  "book, the official point stamps and the simulated orders.", 21, MUTED)
        lab = panel(fig, 120, 860, 1680, 104, fc=AMBER, ec=AMBER, alpha=0.08, r=12)
        lab2 = panel(fig, 120, 860, 1680, 104, fc="none", ec=AMBER, lw=1.6, r=12)
        lines = textwrap.wrap(res["label"], 140)
        lt = [ftxt(fig, 150, 900 + 34 * i, s, 21, AMBER, "body", "demibold") for i, s in enumerate(lines)]
        self.groups = [([a], 0.0), ([b], 0.12), ([c], 0.25), ([d], 0.45),
                       ([z for pair in ch for z in pair], 0.65), ([nv], 0.8), ([lab, lab2] + lt, 0.95)]
        self.base = {}
        for arts, _ in self.groups:
            for z in arts:
                self.base[id(z)] = z.get_alpha() if z.get_alpha() is not None else 1.0

    def frame(self, t):
        for arts, t_in in self.groups:
            k = ease((t - t_in) / 0.45)
            for z in arts:
                z.set_alpha(self.base[id(z)] * k)
        return grab(self.fig)


# ----------------------------------------------------------------------------------------------- main scene
class Main:
    def __init__(self, res, m, tl, g1, races, t0, t1, tmap, feats):
        self.res, self.m, self.g1, self.races, self.t0, self.t1 = res, m, g1, races, t0, t1
        self.tt, self.vv, self.sp, self.S = tmap
        self.tl = tl
        self.tlx = tl.t_ms.to_numpy()
        self.fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
        fig = self.fig
        bg = fig.add_axes([0, 0, 1, 1], facecolor=BG, zorder=-10)
        bg.set_axis_off()
        # ---------------- header + ribbon + footer
        ftxt(fig, 34, 56, "COURTSIDE", 36, INK, "display", "bold")
        ftxt(fig, 228, 56, "MATCH REPLAY", 36, FAST, "display", "bold")
        ftxt(fig, 470, 55, f"{m['n0']} v {m['n1']}  ·  WTA Beijing  ·  {m['points']} official points", 20, MUTED)
        self.clock = ftxt(fig, 1888, 56, "", 24, INK, "mono", ha="right")
        self.speed = ftxt(fig, 1560, 56, "", 19, MUTED, "body", "demibold", ha="right")
        panel(fig, 32, 72, 1856, 40, fc=AMBER, ec=AMBER, alpha=0.09, r=8)
        panel(fig, 32, 72, 1856, 40, fc="none", ec=AMBER, lw=1.5, r=8)
        ftxt(fig, 960, 99, RIBBON, 19.5, AMBER, "display", "bold", ha="center")
        ftxt(fig, 34, 1043, FOOT1, 14.2, MUTED)
        ftxt(fig, 34, 1066, FOOT2, 14.2, MUTED)
        # ---------------- main chart
        panel(fig, 32, 124, 1300, 470)
        self.ax = ax = fig.add_axes(rect(104, 182, 1210, 362))
        ax.set_facecolor(PANEL)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.spines["left"].set_color(LINE)
        ax.spines["bottom"].set_color(LINE)
        ax.tick_params(labelsize=pt(15), colors=MUTED, length=0, pad=6)
        ax.grid(axis="y", color=LINE, lw=1.0)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.2f}"))
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
            lambda v, _: pd.Timestamp(self.t0 + v * 1000, unit="ms").strftime("%H:%M")))
        ax.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(120))
        ax.set_ylabel(f"{m['n0']} to win, $  (= implied probability)", fontsize=pt(15), color=MUTED, labelpad=10)
        self.band = None
        self.mid, = ax.plot([], [], color=INK, lw=2.0, zorder=4, solid_joinstyle="round")
        self.nowline = ax.axvline(0, color=FAST, lw=1.4, alpha=0.55, zorder=3)
        self.glow = ax.scatter([], [], s=[], color=FAST, alpha=0.25, zorder=5, lw=0)
        self.dot = ax.scatter([], [], s=70, color=FAST, edgecolor=INK, lw=1.5, zorder=6)
        self.ticks = LineCollection([], colors=MUTED, linewidths=1.6, alpha=0.75, transform=ax.get_xaxis_transform(),
                                    zorder=2)
        ax.add_collection(self.ticks)
        self.blocked = ax.scatter([], [], s=46, facecolor="none", edgecolor=DIM, lw=1.4, zorder=5)
        self.fills_ok = ax.scatter([], [], s=120, color=FAST, edgecolor=PANEL, lw=1.8, zorder=7)
        self.fills_bad = ax.scatter([], [], s=130, marker="D", color=AMBER, edgecolor=PANEL, lw=1.6, zorder=7)
        self.missed = ax.scatter([], [], s=120, marker="X", color=CORAL, edgecolor=PANEL, lw=1.2, zorder=7)
        self.pulse = ax.scatter([], [], s=[], facecolor="none", edgecolor=FAST, lw=2.2, zorder=8)
        self.tag = ax.text(0, 0, "", fontsize=pt(16), color=INK, family=F["mono"], ha="center", va="bottom", zorder=9,
                           bbox=dict(boxstyle="round,pad=0.35,rounding_size=0.5", fc=BG, ec=FAST, lw=1.4))
        self.ylim = None
        H_ = [Line2D([], [], color=FAST, marker="o", lw=0, ms=10, mec=PANEL),
              Line2D([], [], color=AMBER, marker="D", lw=0, ms=9, mec=PANEL),
              Line2D([], [], color=CORAL, marker="X", lw=0, ms=10, mec=PANEL),
              Line2D([], [], color=DIM, marker="o", lw=0, ms=8, mfc="none", mew=1.4),
              Line2D([], [], color=MUTED, lw=2, marker="|", ms=12, ls="none")]
        fig.legend(H_, ["fill, correct call", "fill, simulated wrong call", "missed: book already moved",
                              "blocked: 100-share net cap", "official point"],
                         loc="upper right", bbox_to_anchor=(fx(1318), fy(132)), ncol=5, frameon=False,
                         fontsize=pt(15), labelcolor=MUTED, handletextpad=0.3, columnspacing=1.3)
        ftxt(fig, 56, 158, "1 s FEED", 19, FAST, "display", "bold")
        self.setgame = ftxt(fig, 130, 158, "", 19, MUTED, "display", "bold")
        self.score = ftxt(fig, 116, 220, "", 44, INK, "display", "bold", zorder=12,
                          bbox=dict(boxstyle="round,pad=0.25,rounding_size=0.4", fc=PANEL, ec="none", alpha=0.82))
        self.games = ftxt(fig, 118, 250, "", 17, MUTED, zorder=12)
        # minimap
        panel(fig, 32, 600, 1300, 48)
        self.mm = mm = fig.add_axes(rect(104, 606, 1210, 36))
        mm.set_axis_off()
        mx = (self.tlx - t0) / 1000
        mm.plot(mx, tl.mid0, color=DIM, lw=1.2)
        self.mm_play, = mm.plot([], [], color=INK, lw=1.5)
        mm.set_xlim(0, (t1 - t0) / 1000)
        mm.set_ylim(np.nanmin(tl.mid0) - 0.05, np.nanmax(tl.mid0) + 0.05)
        self.mm_win = Rectangle((0, -1), 1, 3, fc=FAST, ec=FAST, alpha=0.18, lw=1.2)
        mm.add_patch(self.mm_win)
        for r in races:
            if r["feature"]:
                mm.axvline((r["T"] - t0) / 1000, color=AMBER, lw=1.6, alpha=0.9)
        ftxt(fig, 52, 630, "MATCH", 14, MUTED, "display", "bold")
        # ---------------- sidebar
        panel(fig, 1352, 124, 536, 524)
        ftxt(fig, 1378, 162, "RUNNING P&L  ·  1 s FEED  ·  THIS MATCH", 18, MUTED, "display", "bold")
        self.pnl = ftxt(fig, 1374, 262, "", 100, INK, "display", "bold")
        ftxt(fig, 1378, 296, "marked at the +30 s mid, after fees; booked when the mark is known", 14.5, MUTED)
        self.held = ftxt(fig, 1378, 318, "", 14.5, MUTED)
        labels = ["official points stamped", "CV calls (~1 s before the stamp)", "blocked by the 100-share net cap", "orders sent",
                  "filled  (simulated wrong calls)", "missed: book already moved", "calls that beat the book's reprice"]
        self.tv = []
        for i, s in enumerate(labels):
            y = 362 + 31 * i
            ftxt(fig, 1378, y, s, 17, MUTED)
            self.tv.append(ftxt(fig, 1864, y, "", 18, INK, "mono", ha="right"))
            fig.lines.append(Line2D([fx(1378), fx(1864)], [fy(y + 10)] * 2, transform=fig.transFigure, color=LINE,
                                    lw=0.8))
        ftxt(fig, 1378, 596, "NET POSITION  ·  CAP ±100 SHARES", 15, MUTED, "display", "bold")
        self.gx0, self.gx1, self.gy = 1430, 1812, 616
        panel(fig, self.gx0, self.gy, self.gx1 - self.gx0, 12, fc=LINE, ec=LINE, r=6)
        self.gbar = Rectangle((fx(960), fy(self.gy + 12)), 0, 12 / H, transform=fig.transFigure, fc=FAST, ec="none")
        fig.patches.append(self.gbar)
        fig.lines.append(Line2D([fx((self.gx0 + self.gx1) / 2)] * 2, [fy(self.gy - 5), fy(self.gy + 17)],
                                transform=fig.transFigure, color=MUTED, lw=1.2))
        ftxt(fig, self.gx0 - 8, self.gy + 11, short(m["n1"]), 14, MUTED, ha="right")
        ftxt(fig, self.gx1 + 8, self.gy + 11, short(m["n0"]), 14, MUTED)
        self.gval = ftxt(fig, 1864, 596, "", 15, INK, "mono", ha="right")
        # ---------------- race strip
        panel(fig, 32, 660, 1300, 372)
        self.rh1 = ftxt(fig, 56, 696, "", 25, INK, "display", "bold")
        self.rh2 = ftxt(fig, 56, 724, "", 17, MUTED)
        self.badge_p = panel(fig, 1150, 676, 160, 34, fc=AMBER, ec=AMBER, alpha=0.0, r=17)
        self.badge = ftxt(fig, 1230, 699, "", 17, BG, "display", "bold", ha="center")
        self.rule = ftxt(fig, 1310, 727, "", 14, AMBER, ha="right")
        self.rp = rp = fig.add_axes(rect(300, 748, 1010, 104))
        self.rl = rl = fig.add_axes(rect(300, 862, 1010, 128))
        for a_ in (rp, rl):
            a_.set_facecolor(PANEL)
            for s in ("top", "right"):
                a_.spines[s].set_visible(False)
            a_.spines["left"].set_color(LINE)
            a_.spines["bottom"].set_color(LINE)
            a_.set_xlim(*RACE_X)
            a_.tick_params(labelsize=pt(14), colors=MUTED, length=0, pad=5)
        rp.tick_params(labelbottom=False)
        rp.grid(axis="y", color=LINE, lw=0.9)
        rp.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.2f}"))
        rp.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
        rl.set_ylim(-0.6, 2.6)
        rl.set_yticks([])
        rl.spines["left"].set_visible(False)
        rl.set_xticks(np.arange(-0.5, 3.01, 0.5))
        rl.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.1f} s" if v else "0"))
        ftxt(fig, 56, 790, "best ask of the", 15, MUTED)
        ftxt(fig, 56, 810, "called player", 15, MUTED)
        ftxt(fig, 56, 830, "(recorded book)", 15, MUTED)
        lane_lab = [("1.0 s feed", "headline, assumed", INK), ("0.5 s feed", "faster licensed feed", MUTED),
                    ("0 s", "camera at the venue", MUTED)]
        self.lane_y = {1.0: 2, 0.5: 1, 0.0: 0}
        for V, (a1, a2, c) in zip((1.0, 0.5, 0.0), lane_lab):
            ypx = 862 + 128 * (2.6 - self.lane_y[V]) / 3.2
            ftxt(fig, 56, ypx, a1, 18, c, "display", "bold", va="center")
            ftxt(fig, 152 if V != 0.0 else 92, ypx + 1, a2, 14, MUTED, va="center")
        self.rax = ftxt(fig, 805, 1024, "seconds from the assumed ball landing (official stamp − 2.0 s)", 14, MUTED,
                        ha="center")
        self.r_ask, = rp.plot([], [], color=INK, lw=2.2, drawstyle="steps-post", zorder=4)
        self.r_lim = rp.axhline(0, color=FAST, lw=1.6, ls=(0, (5, 3)), zorder=3)
        self.r_lim_t = rp.text(RACE_X[0], 0, "", fontsize=pt(14), color=FAST, ha="left", va="bottom", zorder=5)
        self.r_tr = rp.scatter([], [], s=30, color=MUTED, zorder=3, lw=0)
        self.r_exec_pts = rp.scatter([], [], s=90, color=FAST, zorder=6, edgecolor=PANEL, lw=1.4)
        self.r_land = [a_.axvline(0, color=INK, lw=1.2, alpha=0.45, zorder=1) for a_ in (rp, rl)]
        self.r_stamp = [a_.axvline(2.0, color=MUTED, lw=1.2, ls=(0, (1, 2)), zorder=1) for a_ in (rp, rl)]
        self.r_rep = [a_.axvline(0, color=CORAL, lw=2.0, ls=(0, (4, 2.5)), zorder=2) for a_ in (rp, rl)]
        self.r_rep_t = rp.text(0, 0.95, "book reprices", transform=rp.get_xaxis_transform(), fontsize=pt(15),
                               color=CORAL, ha="left", va="top", fontweight="bold", zorder=8,
                               bbox=dict(boxstyle="square,pad=0.15", fc=PANEL, ec="none", alpha=0.85))
        rp.text(0, 1.02, "ball lands", transform=rp.get_xaxis_transform(), fontsize=pt(14), color=MUTED, ha="center",
                va="bottom")
        rp.text(2.0, 1.02, "umpire stamp", transform=rp.get_xaxis_transform(), fontsize=pt(14), color=MUTED,
                ha="center", va="bottom")
        self.play = [a_.axvline(0, color=FAST, lw=2.0, alpha=0.9, zorder=9) for a_ in (rp, rl)]
        self.lane_art = {}
        for V in MF.VS:
            al = 1.0 if V == 1.0 else 0.42
            y = self.lane_y[V]
            hgt = 0.5 if V == 1.0 else 0.36
            seg_v = Rectangle((0, y - hgt / 2), 0, hgt, fc=COURT, ec="none", alpha=al, zorder=3)
            seg_d = Rectangle((0, y - hgt / 2), 0, hgt, fc=FAST, ec="none", alpha=al * 0.95, zorder=3)
            rl.add_patch(seg_v)
            rl.add_patch(seg_d)
            end = rl.scatter([], [], s=170 if V == 1.0 else 90, zorder=6, lw=1.6)
            txt = rl.text(0, y, "", fontsize=pt(16 if V == 1.0 else 14), color=INK if V == 1.0 else MUTED,
                          va="center", ha="left", family=F["mono"], zorder=7)
            self.lane_art[V] = (seg_v, seg_d, end, txt, al)
        self.node_t = [rl.text(0, 2.36, "CV call · order sent", fontsize=pt(13.5), color=MUTED, ha="center",
                               va="bottom", zorder=8)]
        self.in_v = rl.text(0, 2, "1.0 s feed + 20 ms CV", fontsize=pt(13.5), color=INK, ha="center", va="center",
                            zorder=8, fontweight="demibold")
        self.in_d = rl.text(0, 2, "67 ms + 1 s venue taker delay", fontsize=pt(13.5), color=BG, ha="center",
                            va="center", zorder=8, fontweight="bold")
        # ---------------- tape
        panel(fig, 1352, 660, 536, 372)
        ftxt(fig, 1378, 696, "ORDER TAPE  ·  1 s FEED", 18, MUTED, "display", "bold")
        for x_, s, ha in ((1378, "pt", "left"), (1428, "score", "left"), (1505, "order", "left"),
                          (1752, "vs reprice", "right"), (1864, "P&L", "right")):
            ftxt(fig, x_, 724, s, 13.5, DIM, ha=ha)
        self.rows = []
        for i in range(9):
            y = 758 + 31 * i
            hl = panel(fig, 1366, y - 22, 508, 29, fc=FAST, ec="none", alpha=0.0, r=6)
            cells = [ftxt(fig, 1378, y, "", 15.5, MUTED, "mono"), ftxt(fig, 1428, y, "", 15.5, INK, "mono"),
                     ftxt(fig, 1505, y, "", 15.5, INK, "mono"), ftxt(fig, 1752, y, "", 15.5, INK, "mono", ha="right"),
                     ftxt(fig, 1864, y, "", 15.5, INK, "mono", ha="right")]
            self.rows.append((hl, cells))
        # ---------------- schedule (video time of each event)
        self.v_of = lambda t: float(np.interp(t, self.tt, self.vv))
        self.t_of = lambda v: float(np.interp(v, self.vv, self.tt))
        g = g1
        self.T = g.T_ms.to_numpy()
        self.vT = np.array([self.v_of(t) for t in self.T])
        calls = g[~g.status.str.startswith("skipped") & (g.status != "no book recorded")]
        self.v_call = np.array([self.v_of(t) for t in calls.call_ms])
        blk = g[g.status == "blocked (net cap)"]
        self.v_blk = np.array([self.v_of(t) for t in blk.call_ms])
        mid_at = lambda t: float(np.interp(t, self.tlx, tl.mid0.ffill().to_numpy()))  # noqa: E731
        self.blk_xy = np.array([((t - t0) / 1000, mid_at(t)) for t in blk.call_ms]).reshape(-1, 2)
        self.n_reprice_calls = calls.beat_book.notna().to_numpy()
        self.beat = (calls.beat_book == True).to_numpy()  # noqa: E712
        # race schedule
        rs = sorted(races, key=lambda r: r["b"])
        starts = []
        for r in rs:
            if r["feature"]:
                starts.append(self.v_of(r["b"] + RACE_X[0] * 1000))
            else:
                starts.append(self.v_of(r["b"]))
        for i, r in enumerate(rs):
            r["v_start"] = starts[i]
            nxt = starts[i + 1] if i + 1 < len(rs) else starts[i] + 1.0
            r["v_dur"] = float(np.clip(nxt - starts[i] - 0.04, 0.16, 0.6))
            fe = (r["lanes"][1.0]["exec"] - RACE_X[0]) / (RACE_X[1] - RACE_X[0])
            r["v_reveal"] = self.v_of(r["exec"]) if r["feature"] else r["v_start"] + r["v_dur"] * fe
            r["v_mark"] = max(r["v_reveal"], self.v_of(r["exec"] + 30_000))
        self.rs = rs
        self.sent = [r for r in rs if r["sent"]]
        self.pnl_disp = 0.0
        self.ylim = None
        self.set_final = {}
        for st, ga, gb in g1.games_after:
            self.set_final[st] = (ga, gb)
        sets = "  ".join(f"{a}–{b}" for a, b in self.set_final.values())
        self.banner = ftxt(fig, 718, 360, f"MATCH OVER  ·  {m['winner_name']} wins {sets}", 46, INK, "display", "bold",
                           ha="center", va="center", zorder=20,
                           bbox=dict(boxstyle="round,pad=0.6,rounding_size=0.6", fc=BG, ec=FAST, lw=2.0, alpha=0.92))
        st1 = res["selected_story"]["V1"]
        self.banner2 = ftxt(fig, 718, 432, f"1 s feed, this match: {st1['fills']} fills, beat the book on "
                            f"{st1['beat_book']} of {st1['calls_with_reprice']} calls  ·  next: all 9 matches",
                            19, MUTED, ha="center", va="center", zorder=20)
        self.v_end = float(self.vv[-1])
        self.final_held = res["selected_story"]["V1"]["pnl_hold_usd"]

    # ---- per-frame
    def race_state(self, v):
        cur = None
        for r in self.rs:
            if r["v_start"] <= v:
                cur = r
        if cur is None:
            return None, None
        if cur["feature"]:
            rt = (self.t_of(v) - cur["b"]) / 1000
        else:
            rt = RACE_X[0] + (v - cur["v_start"]) / cur["v_dur"] * (RACE_X[1] - RACE_X[0])
        return cur, rt

    def frame(self, v):
        t = self.t_of(v)
        k_end = ease((v - self.v_end - 0.1) / 0.45)
        self.banner.set_alpha(k_end)
        self.banner.get_bbox_patch().set_alpha(0.92 * k_end)
        self.banner2.set_alpha(k_end)
        x_now = (t - self.t0) / 1000
        ax = self.ax
        # header
        self.clock.set_text(pd.Timestamp(t, unit="ms").strftime("%H:%M:%S.") + f"{int(t % 1000):03d} UTC")
        spd = float(np.interp(t, self.tt, self.sp))
        self.speed.set_text("REAL TIME  ×1" if spd < 1.5 else f"FAST-FORWARD  ×{spd:,.0f}")
        self.speed.set_color(AMBER if spd < 1.5 else MUTED)
        if v > self.v_end:
            self.speed.set_text("FINAL")
        # main chart window
        xa, xb = x_now - NOW_AT * WIN_S, x_now + (1 - NOW_AT) * WIN_S
        ax.set_xlim(xa, xb)
        tl = self.tl
        i0 = max(0, np.searchsorted(self.tlx, self.t0 + xa * 1000) - 1)
        i1 = np.searchsorted(self.tlx, t, side="right")
        xs = (self.tlx[i0:i1] - self.t0) / 1000
        bid, ask, mid = tl.bid0.to_numpy()[i0:i1], tl.ask0.to_numpy()[i0:i1], tl.mid0.to_numpy()[i0:i1]
        if self.band is not None:
            self.band.remove()
        self.band = ax.fill_between(xs, bid, ask, color=FAST, alpha=0.22, lw=0, step="post", zorder=3)
        self.mid.set_data(xs, mid)
        okm = np.isfinite(mid)
        ymid = mid[okm][-1] if okm.any() else 0.5
        self.nowline.set_xdata([x_now])
        self.dot.set_offsets([[x_now, ymid]])
        ph = (v * 1.6) % 1.0
        self.glow.set_offsets([[x_now, ymid]])
        self.glow.set_sizes([200 + 700 * ph])
        self.glow.set_alpha(0.35 * (1 - ph))
        lo = np.nanmin(bid) if len(bid) and np.isfinite(bid).any() else 0.4
        hi = np.nanmax(ask) if len(ask) and np.isfinite(ask).any() else 0.6
        tgt = np.array([lo - 0.045, hi + 0.075])
        if tgt[1] - tgt[0] < 0.16:
            c = tgt.mean()
            tgt = np.array([c - 0.08, c + 0.08])
        self.ylim = tgt if self.ylim is None else self.ylim + (tgt - self.ylim) * min(1.0, 0.10 * max(1, spd / 50))
        ax.set_ylim(*self.ylim)
        # official point ticks
        k = self.T <= t
        seg = []
        for T_, ge in zip(self.T[k], self.g1.game_end.to_numpy()[k]):
            xx = (T_ - self.t0) / 1000
            if xx >= xa:
                seg.append([(xx, 0), (xx, 0.075 if ge else 0.04)])
        self.ticks.set_segments(seg)
        # orders on the chart
        rev = [r for r in self.sent if r["v_reveal"] <= v]
        ok, bad, mis = [], [], []
        for r in rev:
            xx = (r["exec"] - self.t0) / 1000
            if r["shares"] > 1e-9:
                p0 = r["vwap"] if r["tok"] == 0 else 1 - r["vwap"]
                (ok if r["correct"] else bad).append((xx, p0))
            else:
                l0 = r["limit"] if r["tok"] == 0 else 1 - r["limit"]
                mis.append((xx, l0))
        for art, arr in ((self.fills_ok, ok), (self.fills_bad, bad), (self.missed, mis)):
            art.set_offsets(np.array(arr).reshape(-1, 2))
        nb = int((self.v_blk <= v).sum())
        self.blocked.set_offsets(self.blk_xy[:nb])
        # pulses + tag on the newest order
        pul, sz, cols = [], [], []
        newest = None
        for r in rev:
            age = v - r["v_reveal"]
            if age < 0.8:
                xx = (r["exec"] - self.t0) / 1000
                y0 = (r["vwap"] if r["shares"] > 1e-9 else r["limit"])
                y0 = y0 if r["tok"] == 0 else 1 - y0
                u = age / 0.8
                pul.append((xx, y0))
                sz.append(150 + 2200 * ease(u))
                c = FAST if (r["shares"] > 1e-9 and r["correct"]) else AMBER if r["shares"] > 1e-9 else CORAL
                cols.append(matplotlib.colors.to_rgba(c, 0.9 * (1 - u)))
            if age < 1.1:
                newest = (r, age)
        self.pulse.set_offsets(np.array(pul).reshape(-1, 2))
        self.pulse.set_sizes(sz)
        self.pulse.set_edgecolors(cols if cols else "none")
        if newest:
            r, age = newest
            y0 = (r["vwap"] if r["shares"] > 1e-9 else r["limit"])
            y0 = y0 if r["tok"] == 0 else 1 - y0
            if r["shares"] > 1e-9:
                s = f"{'WRONG CALL · ' if not r['correct'] else ''}FILL {r['shares']:.0f} @ {r['vwap']:.2f}"
                c = FAST if r["correct"] else AMBER
            else:
                s, c = "MISSED · book moved", CORAL
            self.tag.set_text(s)
            self.tag.set_position(((r["exec"] - self.t0) / 1000, y0 + (self.ylim[1] - self.ylim[0]) * 0.06))
            a = 1.0 if age < 0.8 else 1 - (age - 0.8) / 0.3
            self.tag.set_alpha(a)
            self.tag.get_bbox_patch().set_edgecolor(c)
            self.tag.get_bbox_patch().set_alpha(a)
            self.tag.set_color(c)
        else:
            self.tag.set_text("")
            self.tag.get_bbox_patch().set_alpha(0)
        # score
        j = int(k.sum()) - 1
        if j >= 0:
            row = self.g1.iloc[j]
            st, ga, gb = row.games_after
            sc = row.score_after
            if row.game_end:
                sc = f"GAME {short(row.point_winner_name).upper()}"
            self.setgame.set_text(f"SET {st}  ·  GAME {row.game}")
            self.score.set_text(sc.replace("-", "–") if not row.game_end else sc)
            prev = "".join(f"  ·  set {k}: {self.set_final[k][0]}–{self.set_final[k][1]}" for k in self.set_final if k < st)
            self.games.set_text(f"games: {short(self.m['n0'])} {ga}–{gb} {short(self.m['n1'])}{prev}")
        else:
            self.setgame.set_text("SET 1  ·  GAME 1")
            self.score.set_text("0–0")
            self.games.set_text(f"games: {short(self.m['n0'])} 0–0 {short(self.m['n1'])}")
        # minimap
        mmx = (self.tlx[: i1] - self.t0) / 1000
        self.mm_play.set_data(mmx, tl.mid0.to_numpy()[: i1])
        self.mm_win.set_x(xa)
        self.mm_win.set_width(xb - xa)
        # sidebar
        pnl = sum(r["pnl_mark"] for r in self.sent if r["v_mark"] <= v)
        self.pnl_disp += (pnl - self.pnl_disp) * 0.3
        if abs(pnl - self.pnl_disp) < 0.005:
            self.pnl_disp = pnl
        self.pnl.set_text(money(self.pnl_disp))
        self.pnl.set_color(CORAL if self.pnl_disp < -0.005 else GOOD if self.pnl_disp > 0.005 else INK)
        n_pts = int((self.vT <= v).sum())
        n_calls = int((self.v_call <= v).sum())
        orders = [r for r in self.sent if r["v_reveal"] <= v]
        fills = [r for r in orders if r["shares"] > 1e-9]
        wrong = sum(1 for r in fills if not r["correct"])
        miss = len(orders) - len(fills)
        beat = int(self.beat[: n_calls].sum())
        nrep = int(self.n_reprice_calls[: n_calls].sum())
        vals = [f"{n_pts} / {len(self.T)}", f"{n_calls}", f"{nb}", f"{len(orders)}", f"{len(fills)}  ({wrong})",
                f"{miss}", f"{beat} of {nrep}"]
        for tv, s in zip(self.tv, vals):
            tv.set_text(s)
        if v >= self.vT[-1] + 0.2:
            self.held.set_text(f"match over, {self.m['winner_name']} won · held to the result: "
                               f"{money(self.final_held)}")
        else:
            self.held.set_text("held to the result: settles when the match ends")
        net = 0.0
        for r in orders:
            if r["shares"] > 1e-9:
                net += r["shares"] if r["tok"] == 0 else -r["shares"]
        mid_x = (self.gx0 + self.gx1) / 2
        half = (self.gx1 - self.gx0) / 2
        wpx = net / 100 * half
        self.gbar.set_x(fx(mid_x + min(0, wpx)))
        self.gbar.set_width(abs(wpx) / W)
        self.gbar.set_facecolor(AMBER if abs(net) >= 99.5 else FAST)
        self.gval.set_text(f"{net:+.0f} sh" + ("  AT CAP" if abs(net) >= 99.5 else ""))
        self.gval.set_color(AMBER if abs(net) >= 99.5 else INK)
        # race strip
        self.draw_race(v)
        # tape
        self.draw_tape(v)
        return grab(self.fig)

    def draw_race(self, v):
        r, rt = self.race_state(v)
        rp = self.rp
        if r is None:
            self.rh1.set_text("THE RACE  ·  waiting for the first order")
            self.rh2.set_text("")
            for a_ in (self.r_ask,):
                a_.set_data([], [])
            return
        rt_c = min(max(rt, RACE_X[0]), RACE_X[1])
        self.rh1.set_text(f"THE RACE  ·  POINT {r['n']}  ·  SET {r['set']}, GAME {r['game']}  ·  "
                          f"{r['score'].replace('-', '–')}")
        if r["correct"]:
            self.rh2.set_text(f"{r['winner']} won the point  ·  CV call: {r['called']} (correct)  ·  buy "
                              f"{short(r['called'])} at ≤ {r['limit']:.2f} (ask at landing + 1c)")
            self.rh2.set_color(MUTED)
        else:
            self.rh2.set_text(f"{r['winner']} won the point  ·  CV call: {r['called']}  ·  SIMULATED WRONG CALL "
                              f"(5 % of calls)  ·  buy {short(r['called'])} at ≤ {r['limit']:.2f}")
            self.rh2.set_color(AMBER)
        feat = r["feature"] is not None and rt <= RACE_X[1] + 1.2
        self.badge_p.set_alpha(0.95 if feat else 0.0)
        self.badge.set_text("REAL TIME" if feat else "")
        if feat:
            rules = {"typical": "picked by rule: the typical race at 1 s (median execution − reprice)",
                     "wrong": "picked by rule: the first simulated wrong call that filled",
                     "won": "picked on outcome: largest move where the 0 s feed won (not representative)"}
            self.rule.set_text(rules[r["feature"]["key"]])
        else:
            self.rule.set_text("")
        # price trace up to the playhead
        x, a = r["x"], r["ask"]
        k = x <= rt_c
        xs = np.r_[x[k], rt_c] if k.any() else np.array([])
        ys = np.r_[a[k], a[k][-1]] if k.any() else np.array([])
        self.r_ask.set_data(xs, ys)
        rp.set_ylim(r["ylo"] - 0.003, r["yhi"] + 0.003)
        self.r_lim.set_ydata([r["limit"]])
        self.r_lim_t.set_position((RACE_X[0] + 0.03, r["limit"] + 0.0012))
        self.r_lim_t.set_text(f"our limit {r['limit']:.2f}")
        kt = r["trx"] <= rt_c
        self.r_tr.set_offsets(np.c_[r["trx"][kt], r["trp"][kt]] if kt.any() else np.zeros((0, 2)))
        rep = r["reprice"]
        show_rep = np.isfinite(rep) and rt_c >= rep
        for ln in self.r_rep:
            ln.set_xdata([rep if np.isfinite(rep) else -9])
            ln.set_alpha(1.0 if show_rep else 0.0)
        self.r_rep_t.set_x(rep + 0.03 if np.isfinite(rep) else -9)
        self.r_rep_t.set_alpha(1.0 if show_rep else 0.0)
        if not np.isfinite(rep):
            self.r_rep_t.set_text("")
        else:
            self.r_rep_t.set_text("book reprices")
        for ln in self.play:
            ln.set_xdata([rt_c])
            ln.set_alpha(0.9 if rt < RACE_X[1] else 0.0)
        # lanes
        ex_pts, ex_c = [], []
        for V in MF.VS:
            L = r["lanes"][V]
            seg_v, seg_d, end, txt, al = self.lane_art[V]
            st = L["status"]
            sent = st in SENT
            a0, a1 = L["frame"], L["call"]
            seg_v.set_x(a0)
            seg_v.set_width(max(0.0, min(rt_c, a1) - a0))
            if sent:
                seg_d.set_x(a1)
                seg_d.set_width(max(0.0, min(rt_c, L["exec"]) - a1))
            else:
                seg_d.set_width(0)
            y = self.lane_y[V]
            done = rt_c >= L["exec"] if sent else rt_c >= a1
            if done and sent:
                filled = L["shares"] > 1e-9
                c = (FAST if r["correct"] else AMBER) if filled else CORAL
                end.set_offsets([[L["exec"], y]])
                end.set_paths([matplotlib.markers.MarkerStyle("o" if filled else "X").get_path().transformed(
                    matplotlib.markers.MarkerStyle("o" if filled else "X").get_transform())])
                end.set_facecolor(matplotlib.colors.to_rgba(c, al))
                end.set_edgecolor(matplotlib.colors.to_rgba(PANEL, al))
                if filled:
                    s = f"FILLED {L['shares']:.0f} @ {L['vwap']:.3f}" if V == 1.0 else f"filled {L['shares']:.0f} @ {L['vwap']:.3f}"
                else:
                    s = (f"MISSED: ask {L['ask_exec']:.2f} > {L['limit']:.2f}" if V == 1.0
                         else f"missed: ask {L['ask_exec']:.2f}")
                txt.set_text(s)
                txt.set_position((L["exec"] + 0.07, y))
                txt.set_color(c if V == 1.0 else matplotlib.colors.to_rgba(c, 0.75))
                if V == 1.0:
                    ex_pts.append((L["exec"], L["vwap"] if filled else L["ask_exec"]))
                    ex_c.append(c)
            elif done and not sent:
                end.set_offsets(np.zeros((0, 2)))
                txt.set_text("blocked: net cap" if st.startswith("blocked") else st)
                txt.set_position((max(a1, 0) + 0.07, y))
                txt.set_color(DIM)
            else:
                end.set_offsets(np.zeros((0, 2)))
                txt.set_text("")
        self.r_exec_pts.set_offsets(np.array(ex_pts).reshape(-1, 2))
        self.r_exec_pts.set_facecolor(ex_c if ex_c else "none")
        L1 = r["lanes"][1.0]
        self.node_t[0].set_x(L1["call"])
        self.node_t[0].set_alpha(1.0 if rt_c >= L1["call"] - 0.02 else 0.0)
        self.in_v.set_x((L1["frame"] + L1["call"]) / 2)
        self.in_v.set_alpha(1.0 if rt_c >= L1["call"] - 0.05 else 0.0)
        self.in_d.set_x((L1["arrive"] + L1["exec"]) / 2)
        self.in_d.set_alpha(1.0 if (rt_c >= L1["exec"] - 0.05 and L1["status"] in SENT) else 0.0)

    def draw_tape(self, v):
        rev = [r for r in self.sent if r["v_reveal"] <= v][::-1][: len(self.rows)]
        for i, (hl, cells) in enumerate(self.rows):
            if i >= len(rev):
                for c in cells:
                    c.set_text("")
                hl.set_alpha(0)
                continue
            r = rev[i]
            age = v - r["v_reveal"]
            hl.set_alpha(0.22 * max(0.0, 1 - age / 0.9) if i == 0 else 0.0)
            filled = r["shares"] > 1e-9
            cells[0].set_text(f"{r['n']}")
            cells[1].set_text(r["score"].replace("G", "G"))
            if filled:
                cells[2].set_text(f"{'FILL' if r['correct'] else 'WRONG'} {r['shares']:.0f}@{r['vwap']:.2f}")
                cells[2].set_color(FAST if r["correct"] else AMBER)
            else:
                cells[2].set_text("MISSED")
                cells[2].set_color(CORAL)
            e = r["emb"]
            cells[3].set_text("no reprice" if not np.isfinite(e) else f"{e:+.2f} s")
            cells[3].set_color(MUTED if not np.isfinite(e) else CORAL if e > 0 else GOOD)
            if filled and v >= r["v_mark"]:
                cells[4].set_text(money(r["pnl_mark"]))
                cells[4].set_color(CORAL if r["pnl_mark"] < 0 else GOOD)
            elif filled:
                cells[4].set_text("…")
                cells[4].set_color(MUTED)
            else:
                cells[4].set_text("–")
                cells[4].set_color(DIM)


# ----------------------------------------------------------------------------------------------- end card
class End:
    def __init__(self, res, pts, sf):
        self.res = res
        self.fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
        fig = self.fig
        bg = fig.add_axes([0, 0, 1, 1], facecolor=BG, zorder=-10)
        bg.set_axis_off()
        ftxt(fig, 34, 56, "COURTSIDE", 36, INK, "display", "bold")
        ftxt(fig, 228, 56, "MATCH REPLAY", 36, FAST, "display", "bold")
        panel(fig, 32, 72, 1856, 40, fc=AMBER, ec=AMBER, alpha=0.09, r=8)
        panel(fig, 32, 72, 1856, 40, fc="none", ec=AMBER, lw=1.5, r=8)
        ftxt(fig, 960, 99, RIBBON, 19.5, AMBER, "display", "bold", ha="center")
        hv = res["headline_by_V"]
        nrep = hv["V1"]["all"]["replayable_points"]
        self.h1 = ftxt(fig, 40, 176, "ALL 9 MATCHES RECORDED LIVE ON 2026-10-03", 46, INK, "display", "bold")
        self.h2 = ftxt(fig, 42, 212, f"{nrep} replayable official points  ·  stamp lag 2.0 s  ·  Florida 67 ms  ·  "
                       "seed 0 shown, bands = range over 20 seeds  ·  P&L marked at the +30 s mid", 19, MUTED)
        # chart
        panel(fig, 32, 236, 1010, 548)
        self.ax = ax = fig.add_axes(rect(126, 262, 760, 460))
        ax.set_facecolor(PANEL)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.spines["left"].set_color(LINE)
        ax.spines["bottom"].set_color(LINE)
        ax.tick_params(labelsize=pt(15), colors=MUTED, length=0, pad=6)
        ax.grid(axis="y", color=LINE, lw=1.0)
        ax.set_ylabel("cumulative P&L, $", fontsize=pt(16), color=MUTED)
        F0 = pts[pts.shares > 1e-9]
        t0 = int(F0.exec_ms.min()) - 300_000
        t1 = int(F0.exec_ms.max()) + 120_000
        grid = np.arange(t0, t1, 15_000)
        self.gx = (grid - t0) / 3.6e6
        self.col = {0.0: INK, 0.5: MUTED, 1.0: FAST}
        self.paths, self.bands, self.lines, self.labels = {}, {}, {}, {}
        for V in MF.VS:
            p0 = MF.cum_path(F0[F0.V == V], grid)
            P = np.array([MF.cum_path(g, grid) for _, g in sf[sf.V == V].groupby("seed")])
            self.paths[V] = (p0, P.min(0), P.max(0))
            self.lines[V], = ax.step([], [], where="post", color=self.col[V], lw=3.4 if V == 1.0 else 2.0,
                                     zorder=4 if V == 1.0 else 3)
            self.labels[V] = ax.text(0, 0, "", fontsize=pt(20 if V == 1.0 else 17), color=self.col[V], parse_math=False,
                                     fontweight="bold" if V == 1.0 else "normal", va="center", family=F["display"])
        ax.axhline(0, color=MUTED, lw=1.0, alpha=0.6)
        ax.set_xlim(0, self.gx[-1] + 0.62)
        ax.set_ylim(-335, 30)
        hrs = pd.to_datetime(grid[0], unit="ms")
        ticks = [(pd.Timestamp(f"2026-10-03 {h}:00") - hrs).total_seconds() / 3600 for h in (10, 11, 12)]
        ax.set_xticks(ticks, ["10:00", "11:00", "12:00"])
        ax.set_xlabel("UTC, 2026-10-03 (execution time)", fontsize=pt(15), color=MUTED)
        self.band_art = {}
        # stat grid
        panel(fig, 1062, 236, 826, 548)
        cols = [(0.0, "0 s", "camera at the venue"), (0.5, "0.5 s", "faster licensed feed"),
                (1.0, "1.0 s", "HEADLINE · assumed feed")]
        self.cx = {0.0: 1300, 0.5: 1520, 1.0: 1745}
        panel(fig, 1650, 250, 220, 520, fc=FAST, ec=FAST, alpha=0.10, r=12)
        panel(fig, 1650, 250, 220, 520, fc="none", ec=FAST, lw=1.6, r=12)
        for V, a1, a2 in cols:
            ftxt(fig, self.cx[V], 292, f"V = {a1}", 26, FAST if V == 1.0 else INK, "display", "bold", ha="center")
            ftxt(fig, self.cx[V], 316, a2, 13.5, FAST if V == 1.0 else MUTED, "body", "demibold", ha="center")
        rows = [("calls that beat the\nbook's reprice", 386), ("net per share,\nmarked [95 % CI]", 486),
                ("P&L marked\n/ held to result", 590), ("fills (simulated\nwrong calls)", 690)]
        for s, y in rows:
            for i, l in enumerate(s.split("\n")):
                ftxt(fig, 1084, y - 10 + 21 * i, l, 16, MUTED)
            fig.lines.append(Line2D([fx(1084), fx(1866)], [fy(y + 52)] * 2, transform=fig.transFigure, color=LINE,
                                    lw=0.9))
        self.stats = []
        for V in MF.VS:
            a = hv[f"V{V:g}"]["all"]
            ci = a["per_share_mark_ci95_c"]
            big = [(f"{a['share_calls_beat_book'] * 100:.0f}%", INK, 44, 392),
                   (f"−{abs(a['per_share_mark_c']):.2f}c", CORAL, 40, 490),
                   (f"−${abs(a['pnl_mark_usd']):.0f} / −${abs(a['pnl_hold_usd']):.0f}", CORAL, 25, 590),
                   (f"{a['fills']} ({a['fills_wrong']})", INK, 30, 692)]
            small = [(f"{a['calls_beat_book']} of {a['calls_with_reprice']} calls", 422),
                     (f"[{ci[0]:.2f}, {ci[1]:.2f}]".replace("-", "−"), 520),
                     ("", 620), (f"fill rate {a['fill_rate'] * 100:.0f}%", 722)]
            arts = [ftxt(fig, self.cx[V], y, s, sz, c, "display", "bold", ha="center") for s, c, sz, y in big]
            arts += [ftxt(fig, self.cx[V], y, s, 14.5, MUTED, ha="center") for s, y in small]
            self.stats.append(arts)
        # limitation box
        panel(fig, 32, 800, 1856, 196, fc=AMBER, ec=AMBER, alpha=0.07, r=12)
        panel(fig, 32, 800, 1856, 196, fc="none", ec=AMBER, lw=1.6, r=12)
        sr = res["seed_robustness"]["summary"]
        lim = [
            ("LIMITATION  ·  no licensed video feed was bought: the 1 s delay, the camera call and the landing time "
             "are assumptions.", AMBER, 22, "demibold"),
            (f"A faster licensed feed is the lever: calls that beat the book's reprice rise from "
             f"{hv['V1']['all']['share_calls_beat_book'] * 100:.0f}% at 1 s to "
             f"{hv['V0']['all']['share_calls_beat_book'] * 100:.0f}% at 0 s, and correct fills before the reprice from "
             f"{hv['V1']['all']['correct_fills_before_reprice']} to {hv['V0']['all']['correct_fills_before_reprice']}.",
             INK, 21, "normal"),
            ("In this replay that is still not enough: the trader loses at every delay, in all 20 seeds "
             f"(mean −${abs(sr['V1']['pnl_mark_usd']['mean']):.0f} ± {sr['V1']['pnl_mark_usd']['sd']:.0f} at 1 s) "
             "and in all 36 sensitivity cells, marked.", INK, 21, "normal"),
            ("Next step: one live session on a licensed low-latency feed, to measure the real stamp lag and feed "
             "delay. One day, 9 matches: an illustration, not new evidence.", MUTED, 19, "normal")]
        self.lim = []
        for i, (s, c, sz, wgt) in enumerate(lim):
            self.lim.append(ftxt(fig, 60, 842 + 42 * i, s, sz, c, "body", wgt))
        ftxt(fig, 34, 1043, textwrap.shorten(res["label"], 400), 14.2, MUTED)
        ftxt(fig, 34, 1066, "Protocol committed before any P&L (research/replay/PROTOCOL.md)  ·  results: "
             "research/replay/RESULTS.md  ·  no order was sent, no match video was received", 14.2, MUTED)
        self.groups = [(self.stats[0], 0.5), (self.stats[1], 0.8), (self.stats[2], 1.1), (self.lim[:1], 1.8),
                       (self.lim[1:2], 2.15), (self.lim[2:3], 2.5), (self.lim[3:], 2.85)]

    def frame(self, t):
        ax = self.ax
        u = ease((t - 0.15) / 2.2)
        n = max(2, int(len(self.gx) * u))
        for V in MF.VS:
            p0, lo, hi = self.paths[V]
            self.lines[V].set_data(self.gx[:n], p0[:n])
            if V in self.band_art:
                self.band_art[V].remove()
            if V != 0.5:
                self.band_art[V] = ax.fill_between(self.gx[:n], lo[:n], hi[:n], color=self.col[V],
                                                   alpha=0.16 if V == 1.0 else 0.09, lw=0, step="post", zorder=1)
        ends = {V: self.paths[V][0][n - 1] for V in MF.VS}
        order = sorted(MF.VS, key=lambda V: ends[V], reverse=True)
        prev = None
        for V in order:
            y = ends[V] if prev is None else min(ends[V], prev - 26)
            prev = y
            self.labels[V].set_position((self.gx[n - 1] + 0.06, y))
            self.labels[V].set_text(f"{V:g} s  {money(ends[V], 0)}" if u >= 1 else f"{V:g} s")
        for arts, t_in in self.groups:
            k = ease((t - t_in) / 0.5)
            for z in arts:
                z.set_alpha(k)
        return grab(self.fig)


# ----------------------------------------------------------------------------------------------- run
def render(stills: str | None):
    global F
    F = fonts()
    res, pts, sf, ev, tr, tl, m, S, feats = load()
    g1, races, t0, t1, feat_n = build(res, pts, ev, tr, tl, m, S, feats)
    tmap = time_map(t0, t1, races, MAIN_S - HOLD_S)
    print(f"fast-forward x{tmap[3]:.0f}; featured points {sorted(feat_n)} in real time")
    title = Title(res, m, tl, RIBBON)
    main = Main(res, m, tl, g1, races, t0, t1, tmap, feats)
    end = End(res, pts, sf)
    if stills:
        d = Path(stills)
        d.mkdir(parents=True, exist_ok=True)
        import PIL.Image as Image
        Image.fromarray(title.frame(TITLE_S)).save(d / "title.png")
        for r in main.rs:
            if r["feature"]:
                v = main.v_of(r["b"] + 1.9 * 1000)
                Image.fromarray(main.frame(v)).save(d / f"feature_{r['n']}.png")
                v = main.v_of(r["b"] + 3.0 * 1000)
                Image.fromarray(main.frame(v)).save(d / f"feature_{r['n']}_end.png")
        for v in (6.0, 14.0, MAIN_S - 0.1):
            for k in range(8):
                main.frame(v - (8 - k) / FPS)
            Image.fromarray(main.frame(v)).save(d / f"main_{v:05.1f}.png")
        Image.fromarray(end.frame(END_S)).save(d / "end.png")
        print(f"stills in {d}")
        return
    out = OUT / "replay_match.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r",
           str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
           "-threads", "2", "-movflags", "+faststart", "-metadata",
           "title=COURTSIDE match replay (BACKTEST REPLAY, paper only)", "-metadata",
           f"comment={res['label']}", str(out)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    nT, nM, nE = int(round(TITLE_S * FPS)), int(round(MAIN_S * FPS)), int(round(END_S * FPS))
    last = None
    for i in range(nT):
        last = title.frame(i / FPS)
        ff.stdin.write(last.tobytes())
    title_last = last
    for i in range(nM):
        img = main.frame(i / FPS)
        if i < XF:
            img = lerp_img(title_last, img, ease((i + 1) / XF))
        ff.stdin.write(img.tobytes())
        last = img
        if i % 150 == 0:
            print(f"  main {i}/{nM}", flush=True)
    main_last = last
    for i in range(nE):
        img = end.frame(i / FPS)
        if i < XF:
            img = lerp_img(main_last, img, ease((i + 1) / XF))
        ff.stdin.write(img.tobytes())
    ff.stdin.close()
    ff.wait()
    print(f"wrote {out} ({(nT + nM + nE) / FPS:.1f} s, {nT + nM + nE} frames)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", default=None)
    render(ap.parse_args().stills)
