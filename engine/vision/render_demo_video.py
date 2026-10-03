"""Render results/engine/engine_live_demo.mp4 (1280x720, <= 40 s) from the demo's own logs. PAPER ONLY.

  python -m engine.vision.render_demo_video [--anchor K] [--out results/engine/engine_live_demo.mp4]

Everything drawn comes from files the demo wrote; nothing is simulated here:
  video frames      the held-out clip (data/vision/test_2_copyts.mp4), decoded with PyAV
  ball track        demo_vision_trace.json `frames` (the engine's online tracker, this run)
  P(miss) strip     demo_vision_trace.json `decisions` (the live frozen classifier, gated, this run)
  calls             demo_run.json anchors[K].primary.calls (CallEvents as the strategy received them, with the
                    measured vision latency), labels / audit / as-run latency from demo_run.json vision.events
  fair-value refresh demo_run.json anchors[K].primary.bounce_refreshes (when each BOUNCE's refresh was installed)
  orders, fills     demo_run.json anchors[K].primary.orders / fills (paper executor against the recorded book)
  book              demo_run.json figure_series (best bid / ask of both tokens of the recorded WTA market)

The clip plays at 0.25x (each 120 fps frame is one 30 fps output frame). The market clock is the demo's
own mapping: clip frame f sits at t = (f - f_end) / 120 s from the WTA point's physical end, so calls,
order arrivals (+one-way) and executions (+1 s venue delay) appear at the clip frame they correspond to.
K defaults to demo_run.json `figure_anchor` (the only anchor whose book series is stored).
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

from .events import assert_paper_only
from .stream import REPO

OUT_DIR = REPO / "results" / "engine"
W, H, FPS_OUT, SRC_FPS = 1280, 720, 30, 120.0
BG, PANEL, GRID = "#0e1116", "#161b22", "#2a313c"
INK, INK2, MUTED = "#f0f3f6", "#b6bec9", "#7d8590"
BLUE, ORANGE, YELLOW, GREEN, RED = "#4c9aff", "#f08a4b", "#ffd33d", "#3fb950", "#f85149"
VX, VY, VW, VH = 24, 70, 832, 468          # video panel (16:9)
SX, SY, SW, SH = 24, 556, 832, 146         # score strip
PX, PY, PW, PH = 876, 70, 380, 632         # side panel


def _usd(x):
    return f"{'-' if x < 0 else '+'}${abs(x):.2f}"


def _esc(s):
    return s.replace("$", r"\$")


def _fig_rect(x, y, w, h):
    return [x / W, 1 - (y + h) / H, w / W, h / H]


def _fx(x):
    return x / W


def _fy(y):
    return 1 - y / H


def load(anchor=None):
    D = json.loads((OUT_DIR / "demo_run.json").read_text())
    T = json.loads((OUT_DIR / "demo_vision_trace.json").read_text())
    if D["vision"].get("call_source") != "frozen_model_live":
        raise SystemExit("demo_run.json was not made by the live classifier; run python -m engine.vision.demo_live")
    k = D["figure_anchor"] if anchor is None else anchor
    if k != D["figure_anchor"]:
        raise SystemExit(f"only the figure anchor ({D['figure_anchor']}) has a stored book series")
    return D, T, k


def gpu_same_calls(D):
    """The L4 runs of the same clip (vision_bench_gpu.json, realtime 120 fps, batch 1): same call frames?"""
    p = OUT_DIR / "vision_bench_gpu.json"
    if not p.exists():
        return None
    G = json.loads(p.read_text())
    r = G["runs"].get("torch-cuda-cl-fuse-compile|B1|realtime")
    if not r or not isinstance(r.get("events_vs_labels"), list):
        return None
    lap = [(e["call"], e["frame"]) for e in D["vision"]["events"]]
    gpu = [(e["call"], e["frame"]) for e in r["events_vs_labels"]]
    return dict(same=lap == gpu, n=len(gpu), p50=r["event_latency_ms"]["p50"] if r.get("event_latency_ms") else None,
                call_ready_p50=r["call_ready_ms"]["p50"], gpu=G["env"]["gpu"], job=r["config"].get("job"))


def build_log(D, k):
    """Time-ordered side-panel entries [(t_rel_s, kind, lines, colour)] from the primary scenario."""
    an = D["anchors"][k]
    res = an["primary"]
    w = an["winner"]
    ev_by_frame = {e["frame"]: e for e in D["vision"]["events"]}
    orders = {o["id"]: o for o in res["orders"]}
    fills = {f["order_id"]: f for f in res["fills"]}
    # each BOUNCE starts a fair-value refresh that is installed only after its measured compute time
    # (run.py: install at t_call + ceil(compute_ms)); show when it landed, as logged, not at the call
    refresh = list(res.get("bounce_refreshes") or [])
    sur = lambda n: n.split()[-1]
    out = []
    for c in res["calls"]:
        d = c["decision"]
        e = ev_by_frame.get(c["frame"], {})
        if c["call"] != "MISS":
            r = next((r for r in refresh if abs(r["t_rel_s"] - r["compute_ms"] / 1000.0 - c["t_dec_rel_s"]) < 0.005),
                     None)
            if r is not None:
                refresh.remove(r)
            out.append((c["t_dec_rel_s"], "bounce",
                        [f"BOUNCE f{c['frame']}: no trade; fair-value refresh lands {r['t_rel_s']:+.2f} s"
                         if r is not None else f"BOUNCE f{c['frame']}: no trade; no fair-value refresh"], MUTED))
            continue
        right = d.get("winner") == w
        col = BLUE if right else ORANGE
        lead = e.get("actual_lead_ms")
        lines = [f"MISS f{c['frame']} -> {sur(d['winner_name'])} wins ({'right' if right else 'WRONG'} here)",
                 f"   label {e.get('label')}" + (f"; audit: {e['audit'].replace('_', ' ')}" if e.get("audit") else "")]
        if lead is not None:
            lines.append(f"   ball reached its line {lead:.0f} ms after the call")
        lines.append(f"   vision {c['latency_ms']:.0f} ms processing, decision {c['t_dec_rel_s']:+.3f} s")
        as_run = e.get("latency_ms")     # frame -> CallEvent as the laptop actually ran (queue included)
        if as_run is not None and as_run > c["latency_ms"] + 1:
            lines.append(f"   (as run on this laptop: {as_run / 1000:.1f} s, queued)")
        if d["action"] == "SEND":
            lines.append(f"   BUY {d['shares']:.0f} {sur(d['winner_name'])} <= {d['limit']:.2f} (ask {d['ask']:.2f}), "
                         f"edge {100 * d['edge']:+.1f}c: sent")
        else:
            why = d["reason"].replace("_", " ")
            if d.get("edge") is not None:
                why += f", edge {100 * d['edge']:+.1f}c"
            lines.append(f"   no order: {why}")
        out.append((c["t_dec_rel_s"], "miss", lines, col))
        o = orders.get(d.get("order_id")) if d.get("order_id") else None
        if o:
            out.append((o["t_arrive_rel_s"], "arrive", [f"   order reaches the venue at {o['t_arrive_rel_s']:+.3f} s"],
                        INK2))
            f = fills.get(o["id"])
            if f:
                txt = f"   FILLED {f['shares']:.0f} @ {f['vwap']:.3f} at {f['t_exec_rel_s']:+.3f} s, fee ${f['fee']:.2f}"
                out.append((o["t_exec_rel_s"], "fill", [txt], GREEN))
            else:
                out.append((o["t_exec_rel_s"], "nofill",
                            [f"   {o['status']} at {o['t_exec_rel_s']:+.3f} s ({str(o['reason']).replace('_', ' ')})"], RED))
    out.sort(key=lambda x: x[0])
    return out


def frames(clip, f0, f_from, f_to):
    import av
    c = av.open(str(clip))
    st = c.streams.video[0]
    st.thread_type = "AUTO"
    i = f0
    last = None
    try:
        for fr in c.decode(st):
            if i > f_to:
                break
            if i >= f_from:
                last = fr.to_ndarray(width=VW, height=VH, format="rgb24", interpolation="AREA")
                yield i, last
            i += 1
    finally:
        c.close()


def render(D, T, k, out_path, intro_s=3.0, outro_s=6.0, max_s=40.0, crf=20, preview=None):
    """preview: output-frame indices to save as PNG next to out_path instead of encoding the video."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK,
                         "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED})
    V = D["vision"]
    an = D["anchors"][k]
    res = an["primary"]
    sc = res["scenario"]
    f_end = an["f_end"]
    f0, nfr = V["first_frame"], V["frames"]
    f_last = f0 + nfr - 1
    t_rel = lambda f: (f - f_end) / SRC_FPS
    log = build_log(D, k)
    calls = res["calls"]
    first_call = min(c["frame"] for c in calls) if calls else f0
    t_after = max([x[0] for x in log], default=t_rel(f_last)) + 0.35   # keep the market clock running to the last fill
    f_stop = max(f_last, int(np.ceil(f_end + t_after * SRC_FPS)))
    budget = int(max_s * FPS_OUT) - int(intro_s * FPS_OUT) - int(outro_s * FPS_OUT) - 2
    f_start = max(f0, min(first_call - 120, f_stop - budget + 1))
    if f_stop - f_start + 1 > budget:
        raise SystemExit("clip section does not fit in the time budget")
    trk = {int(r[0]): (r[1], r[2]) for r in T["frames"] if r[1] is not None}
    dec = np.array([(r[0], r[1], r[2], r[3]) for r in T["decisions"]], float)
    tau_on = 0.9799
    ev_by_frame = {e["frame"]: e for e in V["events"]}
    ser = D["figure_series"]
    gpu = gpu_same_calls(D)
    names = D["match"]["names"]
    sur = lambda n: n.split()[-1]
    st_b = an["state_before"]
    w = an["winner"]
    wl = "A" if w == 0 else "B"
    tok_col = {wl: BLUE, ("B" if wl == "A" else "A"): ORANGE}
    tok_name = {"A": names[0], "B": names[1]}
    t_lo, t_hi = t_rel(f_start), t_rel(f_stop)
    vis = [p for p in ser if t_lo - 1 <= p[0] <= t_hi]
    ys = [v for p in vis for v in (p[2], p[3]) if v is not None] + [f["vwap"] for f in res["fills"]]
    y_lo, y_hi = (min(ys) - 0.02, max(ys) + 0.02) if ys else (0, 1)
    t_book = (an["t_book_ms"] - res["t_end_ms"]) / 1000.0

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=BG)
    ax_v = fig.add_axes(_fig_rect(VX, VY, VW, VH))
    ax_s = fig.add_axes(_fig_rect(SX + 38, SY + 34, SW - 50, SH - 56))
    fig.patches.append(plt.Rectangle((_fx(PX), _fy(PY + PH)), PW / W, PH / H, transform=fig.transFigure,
                                     color=PANEL, zorder=-1))
    ax_p = fig.add_axes(_fig_rect(PX + 46, PY + 104, PW - 62, 142))
    for ax in (ax_s, ax_p):
        ax.set_facecolor(PANEL)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.patches.append(plt.Rectangle((_fx(SX), _fy(SY + SH)), SW / W, SH / H, transform=fig.transFigure,
                                     color=PANEL, zorder=-1))
    # static text
    fig.text(_fx(24), _fy(26), "COURTSIDE engine: live vision call  ->  paper order  ->  fill", fontsize=16,
             weight="bold", color=INK, va="center")
    fig.text(_fx(24), _fy(50), "ILLUSTRATIVE PAIRING: table-tennis calls on a held-out clip (OpenTTGames test_2), mapped "
             "onto a recorded Polymarket WTA order book. Different sport, different point; not a backtest.",
             fontsize=9, color=YELLOW, va="center")
    fig.text(_fx(W - 24), _fy(26), "PAPER ONLY  ·  no order sent anywhere", fontsize=10, color=BG, ha="right",
             va="center", weight="bold", bbox=dict(boxstyle="round,pad=0.35", fc=YELLOW, ec="none"))
    fig.text(_fx(SX + 10), _fy(SY + 12), "live classifier score P(miss) at each decision frame (gated)  ·  "
             f"B = BOUNCE call  ·  MISS = 3 frames in a row >= tau_online {tau_on}", fontsize=8.5, color=INK2, va="center")
    fig.text(_fx(PX + 14), _fy(PY + 18), "Paper trading log  (from demo_run.json)", fontsize=10.5,
             weight="bold", color=INK, va="center")
    for j, s_ in enumerate([f"Recorded book: {D['match']['slug']}, point {an['n']}",
                            f"set {an['set']}, games {st_b['ga']}-{st_b['gb']}, points {st_b['pa']}-{st_b['pb']}; "
                            f"{sur(names[w])} won it (book moved {100 * an['D']:.1f}c)",
                            f"t = 0: physical point end = official stamp - {sc['stamp_lag_s']:g} s",
                            f"order: +{sc['one_way_ms']} ms to the venue, executes 1 s later"]):
        fig.text(_fx(PX + 14), _fy(PY + 37 + 14 * j), s_, fontsize=8.2, color=INK2 if j < 2 else MUTED, va="center")
    log_top, log_bottom = PY + 290, PY + PH - 8
    clock = fig.text(_fx(VX + 10), _fy(VY + VH - 14), "", fontsize=10, color=INK, va="center",
                     bbox=dict(boxstyle="round,pad=0.3", fc="#000000", ec="none", alpha=0.6))
    fig.text(_fx(VX + 10), _fy(VY + 16), "engine's own calls, live: BlurBall -> online tracker -> frozen H3 classifier",
             fontsize=8.5, color=INK, va="center", bbox=dict(boxstyle="round,pad=0.3", fc="#000000", ec="none", alpha=0.6))
    speed = fig.text(_fx(VX + VW - 10), _fy(VY + 16), "0.25x", fontsize=10, color=INK, ha="right", va="center",
                     weight="bold", bbox=dict(boxstyle="round,pad=0.3", fc="#000000", ec="none", alpha=0.6))
    # video
    ax_v.set_axis_off()
    im = ax_v.imshow(np.zeros((VH, VW, 3), np.uint8), extent=(0, VW, VH, 0), interpolation="nearest")
    ax_v.set_xlim(0, VW)
    ax_v.set_ylim(VH, 0)
    trail = LineCollection([], linewidths=2.2, capstyle="round", zorder=3)
    ax_v.add_collection(trail)
    ball, = ax_v.plot([], [], "o", ms=13, mfc="none", mec=YELLOW, mew=2, zorder=4)
    banner = ax_v.text(VW / 2, 40, "", ha="center", va="top", fontsize=14, weight="bold", color=INK, zorder=6,
                       bbox=dict(boxstyle="round,pad=0.45", fc=BG, ec=BLUE, lw=2, alpha=0.92), visible=False)
    btag = ax_v.text(0, 0, "", fontsize=10, weight="bold", color=BG, zorder=5, ha="center", va="bottom",
                     bbox=dict(boxstyle="round,pad=0.25", fc=INK2, ec="none"), visible=False)
    sx = VW / 1920.0
    # score strip
    ax_s.set_xlim(f_start, f_stop)
    ax_s.set_ylim(-0.03, 1.1)
    ax_s.set_yticks([0, 0.5, 1])
    ax_s.axhline(tau_on, color=YELLOW, lw=1, ls=(0, (3, 2)))
    ax_s.text(f_start + 3, tau_on - 0.04, "tau_online", color=YELLOW, fontsize=7.5, va="top")
    ax_s.tick_params(labelsize=7.5)
    ax_s.set_xlabel("clip frame (120 fps)", fontsize=7.5, labelpad=1)
    sc_pts = ax_s.scatter([], [], s=6, zorder=3)
    marked = set()
    head_s = ax_s.axvline(f_start, color=INK, lw=1)
    # price panel
    ax_p.set_xlim(t_lo, t_hi)
    ax_p.set_ylim(y_lo, y_hi)
    ax_p.tick_params(labelsize=7.5)
    ax_p.set_xlabel("seconds from the WTA point's physical end", fontsize=7.5, labelpad=1)
    ax_p.set_ylabel("price ($)", fontsize=7.5, labelpad=2)
    ax_p.grid(axis="y", color=GRID, lw=0.5)
    ax_p.axvline(0, color=INK2, lw=0.8)
    lines_p = {}
    for tl in ("A", "B"):
        la, = ax_p.step([], [], where="post", color=tok_col[tl], lw=1.8, label=f"{sur(tok_name[tl])} ask")
        lb, = ax_p.step([], [], where="post", color=tok_col[tl], lw=1.0, ls=(0, (3, 2)), label=f"{sur(tok_name[tl])} bid")
        lines_p[tl] = (la, lb)
    ax_p.legend(loc="upper left", fontsize=7, frameon=False, ncol=2, labelcolor=INK2)
    head_p = ax_p.axvline(t_lo, color=INK, lw=1)
    rb_line = ax_p.axvline(t_book, color=MUTED, lw=1, ls=(0, (2, 2)), visible=False)
    rb_txt = ax_p.text(t_book, y_hi, "book reprice ", color=MUTED, fontsize=7, va="top", ha="right", visible=False)
    fill_pts = []
    for f in res["fills"]:
        p, = ax_p.plot([f["t_exec_rel_s"]], [f["vwap"]], "s", ms=8, color=tok_col[f["token"]], mec=INK, mew=1,
                       zorder=5, visible=False)
        fill_pts.append((f["t_exec_rel_s"], p))
    log_texts = []
    overlay = fig.add_axes([0, 0, 1, 1], zorder=20)
    overlay.set_axis_off()
    ov_bg = overlay.add_patch(plt.Rectangle((0, 0), 1, 1, color=BG, alpha=0.0, transform=overlay.transAxes))
    ov_txt = overlay.text(0.5, 0.5, "", ha="center", va="center", fontsize=12, color=INK, linespacing=1.6,
                          transform=overlay.transAxes)

    def series_upto(tl, t):
        pts = [p for p in ser if p[1] == tl and p[0] <= t]
        if not pts:
            return [], [], []
        xs = [max(t_lo, p[0]) for p in pts] + [t]
        return xs, [p[3] for p in pts] + [pts[-1][3]], [p[2] for p in pts] + [pts[-1][2]]

    def draw_log(t):
        for tx in log_texts:
            tx.remove()
        log_texts.clear()
        shown = [x for x in log if x[0] <= t]
        rows = []
        for _, kind, ls, col in shown:
            for j, s in enumerate(ls):
                rows.append((s, col if (j == 0 or kind in ("fill", "nofill", "arrive")) else INK2,
                             kind == "miss" and j == 0, kind))
        lh = 14.5
        cap = int((log_bottom - log_top) / lh)
        while len(rows) > cap:                      # drop the oldest BOUNCE line first, then the oldest line
            i = next((i for i, r in enumerate(rows) if r[3] == "bounce"), 0)
            rows.pop(i)
        y = log_top
        for s, col, bold, kind in rows:
            log_texts.append(fig.text(_fx(PX + 14), _fy(y), _esc(s), fontsize=8 if kind == "bounce" else 8.4, color=col,
                                      weight="bold" if bold else "normal", va="top", family="DejaVu Sans"))
            y += lh

    proc = None if preview is not None else subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                             "-r", str(FPS_OUT), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)], stdin=subprocess.PIPE)
    n_out = 0

    def emit():
        nonlocal n_out
        if proc is None:
            if n_out in preview:
                fig.savefig(Path(out_path).with_name(f"{Path(out_path).stem}_{n_out:04d}.png"), dpi=100, facecolor=BG)
        else:
            fig.canvas.draw()
            proc.stdin.write(fig.canvas.buffer_rgba().tobytes())
        n_out += 1

    def set_frame(f, img):
        t = t_rel(f)
        im.set_data(img)
        seg, cols = [], []
        for j in range(f - 36, f):
            a, b = trk.get(j), trk.get(j + 1)
            if a and b:
                seg.append([(a[0] * sx, a[1] * sx), (b[0] * sx, b[1] * sx)])
                al = (j - (f - 36)) / 36.0
                cols.append((1.0, 0.83, 0.24, 0.15 + 0.85 * al))
        trail.set_segments(seg)
        trail.set_colors(cols)
        p = trk.get(f)
        ball.set_data(([p[0] * sx], [p[1] * sx]) if p else ([], []))
        clock.set_text(f"test_2 frame {min(f, f_last)}{'' if f <= f_last else ' (clip over: held)'}   ·   "
                       f"t = {t:+.3f} s to point end")
        # calls: banner once the call has been emitted (frame time + measured latency)
        banner.set_visible(False)
        btag.set_visible(False)
        for c in calls:
            age = t - c["t_dec_rel_s"]
            if age < 0:
                continue
            if c["call"] == "MISS" and age <= 1.6:            # market seconds (6.4 s of video)
                e = ev_by_frame.get(c["frame"], {})
                right = c["decision"].get("winner") == w
                lead = e.get("actual_lead_ms")
                banner.set_text(f"MISS at frame {c['frame']}"
                                + (f"  ·  {lead:.0f} ms before the ball reached its line" if lead is not None else "")
                                + f"\nvision {c['latency_ms']:.0f} ms processing (laptop)  ·  WTA mapping: "
                                  f"{sur(c['decision']['winner_name'])} wins ({'right' if right else 'wrong'})")
                banner.get_bbox_patch().set_edgecolor(BLUE if right else ORANGE)
                banner.set_visible(True)
            elif c["call"] == "BOUNCE" and age <= 0.35:
                xy = ev_by_frame.get(c["frame"], {}).get("extra", {}).get("xy")
                if xy:
                    btag.set_position((xy[0] * sx, xy[1] * sx - 16))
                    btag.set_text("BOUNCE")
                    btag.set_visible(True)
        # score strip
        m = dec[:, 0] <= f
        if m.any():
            sc_pts.set_offsets(np.c_[dec[m, 0], dec[m, 3]])
            sc_pts.set_facecolors([(ORANGE if v >= tau_on else BLUE) for v in dec[m, 3]])
            sc_pts.set_edgecolors("none")
        head_s.set_xdata([min(f, f_stop)] * 2)
        for c in calls:
            if c["t_dec_rel_s"] <= t and c["frame"] not in marked:
                marked.add(c["frame"])
                ax_s.axvline(c["frame"], color=(RED if c["call"] == "MISS" else MUTED), lw=1.2 if c["call"] == "MISS" else 0.8,
                             zorder=1)
                ax_s.text(c["frame"], 1.09, "MISS" if c["call"] == "MISS" else "B", color=(RED if c["call"] == "MISS" else MUTED), fontsize=7,
                          ha="center", va="bottom")
        # book
        for tl, (la, lb) in lines_p.items():
            xs, asks, bids = series_upto(tl, t)
            la.set_data(xs, asks)
            lb.set_data(xs, bids)
        head_p.set_xdata([max(t_lo, min(t, t_hi))] * 2)
        rb_line.set_visible(t >= t_book)
        rb_txt.set_visible(t >= t_book)
        for tx, p in fill_pts:
            p.set_visible(t >= tx)
        draw_log(t)

    # --- intro
    gen = frames(REPO / V["clip"], f0, f_start, f_last)
    f, img = next(gen)
    set_frame(f, img)
    ov_bg.set_alpha(0.86)
    intro = ("COURTSIDE streaming engine, end-to-end demo (paper only)\n\n"
             f"Held-out clip: OpenTTGames test_2 frames {f0}-{f_last} (never used in training), 120 fps\n"
             "Every call is made live by the engine: detector -> tracker -> frozen classifier\n"
             "Each MISS call goes to the strategy, which prices a paper order on a recorded WTA order book\n\n"
             "ILLUSTRATIVE PAIRING: different sport, different point. It shows mechanics and timing, not an edge.\n"
             "Shown at 0.25x speed. Orders execute 1 s after they reach the venue (the venue's delay).")
    ov_txt.set_text(intro)
    for _ in range(int(intro_s * FPS_OUT)):
        emit()
    ov_bg.set_alpha(0.0)
    ov_txt.set_text("")
    # --- clip (0.25x), then the last frame held while the market clock runs to the last fill
    emit()
    last = img
    for f, img in gen:
        set_frame(f, img)
        last = img
        emit()
    for f in range(f_last + 1, f_stop + 1):
        set_frame(f, last)
        emit()
    # --- outro
    S = D["sensitivity"]
    prim = S[0]
    asrun = next((s for s in S if s["scenario"]["vision"] == "as_run"), None)
    sent_k = sum(1 for c in calls if c["decision"]["action"] == "SEND")
    miss_k = sum(1 for c in calls if c["call"] == "MISS")
    tm = V["timing"]
    lines = [f"This WTA point: {miss_k} MISS calls -> {sent_k} paper orders -> {len(res['fills'])} filled "
             f"({sum(f['shares'] for f in res['fills']):.0f} shares); P&L marked 10 s after: {_usd(res['pnl_marked_10s'])}",
             f"All {prim['anchors']} anchored WTA points (same calls, same rule): {prim['orders_sent']} orders, "
             f"{prim['orders_filled']} filled, P&L marked +10 s {_usd(prim['pnl_marked_10s'])}, fees ${prim['fees']:.2f}",
             f"Vision on this shared laptop: {tm['fps_sustained']} fps; processing latency p50 "
             f"{tm['call_ready_processing_ms']['p50']:.0f} ms (used above)"
             + (f"; with its real queueing every call was stale ({asrun['orders_sent']} orders)" if asrun else "")]
    if gpu:
        lines.append(f"Same clip on one {gpu['gpu']} at a real 120 fps feed: "
                     + ("the same " if gpu["same"] else "different calls: ") + f"{gpu['n']} calls, "
                     f"frame -> call p50 {gpu['p50']:.0f} ms (vision_bench_gpu.json)")
    l4p = OUT_DIR / "demo_run_L4.json"
    if l4p.exists():
        s0 = json.loads(l4p.read_text())["sensitivity"][0]
        if s0["scenario"] == prim["scenario"]:
            lines.append(f"Same market replay with the L4 run's calls and latency: {s0['orders_sent']} orders, "
                         f"{s0['orders_filled']} filled, P&L marked +10 s {_usd(s0['pnl_marked_10s'])} (demo_run_L4.json)")
    lines += ["", "ILLUSTRATIVE PAIRING: table-tennis calls on a WTA book. Not a backtest; the P&L is not evidence of an edge.",
              "Paper only: no order was sent anywhere. Source: results/engine/demo_run.json, demo_vision_trace.json"]
    ov_bg.set_alpha(0.88)
    ov_txt.set_fontsize(11.5)
    ov_txt.set_text(_esc("\n".join(lines)))
    for _ in range(int(outro_s * FPS_OUT)):
        emit()
    if proc is not None:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed")
    plt.close(fig)
    return dict(frames=n_out, seconds=round(n_out / FPS_OUT, 2), clip_frames=(f_start, f_stop), anchor=k,
                log_entries=len(log), gpu_same_calls=gpu)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anchor", type=int, default=None)
    ap.add_argument("--out", default=str(OUT_DIR / "engine_live_demo.mp4"))
    ap.add_argument("--max-seconds", type=float, default=40.0)
    ap.add_argument("--preview", default=None, help="comma-separated output frame numbers: save PNGs, no video")
    a = ap.parse_args()
    assert_paper_only()
    D, T, k = load(a.anchor)
    pv = None if a.preview is None else {int(x) for x in a.preview.split(",")}
    info = render(D, T, k, Path(a.out), max_s=a.max_seconds, preview=pv)
    print(json.dumps(info), flush=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
