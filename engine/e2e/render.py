"""Figure and video for the end-to-end timing proof, drawn ONLY from results/e2e/trace.jsonl + summary.json
(and the clip's own frames for the picture). Paper only; no order was sent.

  python -m engine.e2e.render                  # fig_waterfall.png + e2e_timeline.mp4
  python -m engine.e2e.render --figure-only

fig_waterfall.png (light, paper): top, the budget from the point to an executable order with the 1 s simulated feed
(p50 over the run's complete MISS-call traces), laptop CV measured and L4 CV as the production reference, dotted
lines at the 1 s feed and the 3 s requirement, the range of the median reprice under the three stamp-lag readings
shaded (not measured); bottom, our own pipeline (capture -> order ready) stage by stage, p50 bars with p90 whiskers
and ms labels. The footer carries LABEL verbatim and the run's conditions (summary budget conditions.sentence).

e2e_timeline.mp4 (dark, 1280x720, ~27 s): the clip around the featured MISS call with the engine's ball track
and the call; then that call's order timeline (every stage stamp from the trace) racing the live book ticker of
the token it buys (the trace's 20 Hz top-of-book rows); then the run's numbers.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from engine.e2e import LABEL  # noqa: E402

OUT = REPO / "results" / "e2e"
CLIP = REPO / "data" / "vision" / "test_2_copyts.mp4"
SRC0 = 2000

LIGHT = dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
             blue="#2a78d6", orange="#eb6834", aqua="#1baf7a", b300="#6da7ec", b450="#2a78d6", b600="#184f95",
             feed="#e1e0d9", hatch="#898781", band="#f0efec")
DARK = dict(surface="#1a1a19", page="#0d0d0d", ink="#ffffff", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a",
            axis="#383835", blue="#3987e5", orange="#d95926", aqua="#199e70", yellow="#c98500", b300="#6da7ec",
            b450="#3987e5", b600="#86b6ef", feed="#383835", band="#2c2c2a")

# pipeline stages (summary.stage_ms order) -> (short label, group)
GROUPS = {"sender: frame into encoder": ("sender", "video"),
          "encode + WHIP + MediaMTX + RTP in": ("encode + WebRTC transport", "video"),
          "H.264 decode + handoff": ("decode", "video"),
          "prep + queue + detector": ("frame prep + detector", "cv"),
          "tracker + features + classifier": ("tracker + classifier", "cv"),
          "strategy rule (fair value, edge)": ("strategy rule", "trade"),
          "risk check": ("risk check", "trade"),
          "unsigned order built": ("order built", "trade")}
GROUP_NAME = {"video": "video over WebRTC", "cv": "CV engine (laptop GPU)", "trade": "decision + risk + order"}


def load():
    rows = [json.loads(x) for x in open(OUT / "trace.jsonl") if x.strip()]
    meta = next(r for r in rows if r["type"] == "meta")
    calls = [r for r in rows if r["type"] == "call"]
    summ = json.load(open(OUT / "summary.json"))
    return meta, calls, summ


def complete(calls):
    return [r for r in calls if r.get("order") and r.get("fill") and r["t"].get("capture") is not None
            and r["t"].get("executable") is not None]


# ============================================================================================ figure
def figure(summ, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    C = LIGHT
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
                         "font.size": 8.5, "axes.edgecolor": C["axis"], "axes.labelcolor": C["ink2"],
                         "xtick.color": C["muted"], "ytick.color": C["ink2"], "text.color": C["ink"]})
    B = summ["budget_with_1s_simulated_feed"]
    n = summ["counts"]["complete_order_traces"]
    feed = B["feed_simulated_ms"]
    ours = B["ours_capture_to_order_ready_ms"]["p50"]
    net = B["network_one_way_ms"]["p50"]
    ven = B["venue_delay_ms"]["p50"]
    l4 = (B.get("with_l4_vision") or {}).get("ours_ms")
    cond = (B.get("conditions") or {}).get("sentence")
    fig = plt.figure(figsize=(7.2, 5.15), dpi=300, facecolor=C["surface"])
    gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 1.55], hspace=0.66, left=0.255, right=0.955, top=0.865, bottom=0.15)
    ax = fig.add_subplot(gs[0])
    ax.set_facecolor(C["surface"])
    bars = [("Laptop CV (measured)", ours)]
    if l4 is not None:
        bars.append(("L4 GPU CV (composite)", l4))
    ys = np.arange(len(bars))[::-1] * 1.0
    h = 0.42
    lo, hi = summ["reprice_reference"]["band_s"]
    imp = summ["reprice_reference"].get("implied_after_point_s") or {}
    ax.axvspan(lo, hi, color=C["band"], zorder=0, lw=0)
    mids = " / ".join(f"{v:.2f}" for v in sorted(imp.values())) if imp else f"{lo:.2f}-{hi:.2f}"
    ax.text(max((lo + hi) / 2, 1.0) + 0.06, ys.min() - 0.5, f"median reprice {mids} s\n(by unmeasured stamp lag)",
            ha="left" if (lo + hi) / 2 < 1.0 else "center", va="top", fontsize=6.4, color=C["ink2"], linespacing=1.0,
            zorder=5, bbox=dict(boxstyle="round,pad=0.12", fc=C["band"], ec="none"))
    for (name, o), y in zip(bars, ys):
        segs = [(0.0, feed / 1e3, C["feed"], "//"), (feed / 1e3, o / 1e3, C["blue"], None),
                ((feed + o) / 1e3, net / 1e3, C["orange"], None), ((feed + o + net) / 1e3, ven / 1e3, C["aqua"], None)]
        for x0, w, col, hat in segs:
            ax.barh(y, max(w - 0.004, 0.002), left=x0 + 0.002, height=h, color=col, hatch=hat,
                    edgecolor=C["hatch"] if hat else "none", linewidth=0, zorder=2)
        tot = (feed + o + net + ven) / 1e3
        ax.text(tot + 0.04, y, f"{tot * 1e3:,.0f} ms", va="center", ha="left", fontsize=8, color=C["ink"],
                fontweight="bold")
        ax.text(feed / 1e3 / 2, y, "feed 1,000 ms\n(simulated)", ha="center", va="center", fontsize=6.6,
                color=C["ink2"], linespacing=1.0, zorder=3,
                bbox=dict(boxstyle="round,pad=0.15", fc=C["surface"], ec="none", alpha=0.85))
        ax.text((feed + o + net + ven / 2) / 1e3, y, f"venue delay {ven:,.0f} ms", ha="center", va="center",
                fontsize=6.8, color="white", zorder=3)
        ax.annotate(f"ours {o:,.0f} ms + network {net:,.0f} ms", xy=((feed + (o + net) / 2) / 1e3, y + h / 2),
                    xytext=(1.62, y + h / 2 + 0.2), ha="left", va="center", fontsize=6.8,
                    color=C["ink"], arrowprops=dict(arrowstyle="-", color=C["muted"], lw=0.6,
                                                    connectionstyle="angle,angleA=0,angleB=75"))
    for x, txt in ((1.0, "1 s feed "), (3.0, "< 3 s requirement ")):
        ax.axvline(x, color=C["ink2"], ls=(0, (1.2, 1.8)), lw=1.0, zorder=4)
        ax.text(x, ys.max() + 0.62, txt, ha="right", va="bottom", fontsize=7, color=C["ink2"])
    ax.set_yticks(ys)
    ax.set_yticklabels([b[0] for b in bars], fontsize=8)
    ax.set_xlim(0, 3.25)
    ax.set_ylim(ys.min() - 1.0, ys.max() + 0.85)
    ax.set_xticks([0, 0.5, 1, 1.5, 2, 2.5, 3])
    ax.set_xticklabels(["0", "0.5", "1.0", "1.5", "2.0", "2.5", "3.0 s"])
    ax.tick_params(length=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_title(f"A. Physical point to executable order, 1 s simulated feed (p50, n = {n} timing probes)", loc="left",
                 fontsize=9, color=C["ink"], pad=19, fontweight="bold")
    ax.legend(handles=[Patch(fc=C["feed"], hatch="//", ec=C["hatch"], lw=0, label="feed (simulated)"),
                       Patch(fc=C["blue"], label="our pipeline: capture to order ready"),
                       Patch(fc=C["orange"], label="network one-way (RTT/2, measured)"),
                       Patch(fc=C["aqua"], label="venue order delay (secondsDelay)")],
              loc="lower left", bbox_to_anchor=(-0.33, 1.0), ncol=4, frameon=False, fontsize=6.4,
              handlelength=1.1, columnspacing=0.9, handletextpad=0.4)

    # B: our pipeline waterfall
    bx = fig.add_subplot(gs[1])
    bx.set_facecolor(C["surface"])
    st = [s for s in summ["stage_ms"] if s["stage"] in GROUPS]
    gcol = {"video": C["b300"], "cv": C["b450"], "trade": C["b600"]}
    x = 0.0
    yy = np.arange(len(st) + 1)[::-1]
    for s, y in zip(st, yy[:-1]):
        lab, g = GROUPS[s["stage"]]
        w, p90 = s["ms"]["p50"], s["ms"]["p90"]
        bx.barh(y, max(w, 0.05), left=x, height=0.56, color=gcol[g], lw=0, zorder=2)
        bx.plot([x + w, x + p90], [y, y], color=C["muted"], lw=0.8, zorder=3, solid_capstyle="butt")
        bx.plot([x + p90, x + p90], [y - 0.12, y + 0.12], color=C["muted"], lw=0.8, zorder=3)
        txt = f"{w:.2f} ms" if w < 1 else f"{w:.1f} ms"
        p90t = f"{p90:.2f}" if p90 < 1 else f"{p90:.1f}"
        bx.text(x + max(w, p90) + 0.5, y, f"{txt}  (p90 {p90t})", va="center", ha="left", fontsize=6.8,
                color=C["ink"])
        x += w
    tot = summ["spans_ms"]["capture_to_order_ready"]
    bx.barh(yy[-1], tot["p50"], left=0, height=0.56, color=C["blue"], lw=0, zorder=2)
    bx.plot([tot["p50"], tot["p90"]], [yy[-1], yy[-1]], color=C["muted"], lw=0.8, zorder=3)
    bx.text(max(tot["p50"], tot["p90"]) + 0.5, yy[-1], f"{tot['p50']:.1f} ms  (p90 {tot['p90']:.1f}, p99 {tot['p99']:.1f})",
            va="center", ha="left", fontsize=7, color=C["ink"], fontweight="bold")
    bx.set_yticks(yy)
    bx.set_yticklabels([GROUPS[s["stage"]][0] for s in st] + ["capture to order ready"], fontsize=7.6)
    for t in bx.get_yticklabels()[-1:]:
        t.set_fontweight("bold")
    xmax = max(tot["p99"], x) * 1.32
    bx.set_xlim(0, xmax)
    bx.grid(axis="x", color=C["grid"], lw=0.6, zorder=0)
    bx.set_axisbelow(True)
    bx.tick_params(length=0)
    for s in ("top", "right", "left"):
        bx.spines[s].set_visible(False)
    fps = (B.get("conditions") or {}).get("stream_fps")
    bx.set_xlabel("ms after the call frame was captured (paced sender" + (f", {fps:g} frames/s)" if fps else ")"),
                  fontsize=7.5)
    bx.set_title("B. Our pipeline, stage by stage (bar p50, whisker p90)", loc="left", fontsize=9,
                 color=C["ink"], pad=6, fontweight="bold")
    bx.legend(handles=[Patch(fc=gcol[g], label=GROUP_NAME[g]) for g in ("video", "cv", "trade")], loc="upper right",
              frameon=False, fontsize=6.6, handlelength=1.1)
    import textwrap
    foot = LABEL[0].upper() + LABEL[1:] + "."
    if cond:
        foot += "\n" + "\n".join(textwrap.wrap("Conditions: " + cond + ".", 150))
    fig.text(0.012, 0.012, foot, fontsize=5.6, color=C["muted"], va="bottom", linespacing=1.35)
    fig.savefig(path, facecolor=C["surface"])
    plt.close(fig)
    print(f"wrote {path}")


# ============================================================================================ video
def pick_call(calls):
    """The complete MISS trace whose capture -> executable is the run's median (ties: earliest)."""
    full = complete(calls)
    tot = np.array([r["t"]["executable"] - r["t"]["capture"] for r in full])
    med = np.median(tot)
    i = int(np.argmin(np.abs(tot - med)))
    return full[i]


def clip_frames(f_lo, f_hi, size):
    import av
    out = {}
    with av.open(str(CLIP)) as c:
        st = c.streams.video[0]
        st.thread_type = "AUTO"
        tb = float(st.time_base)
        for fr in c.decode(st):
            src = int(round(fr.pts * tb * 120))
            if src < f_lo:
                continue
            if src > f_hi:
                break
            out[src] = fr.to_ndarray(width=size[0], height=size[1], format="rgb24")
    return out


class Writer:
    def __init__(self, path, w=1280, h=720, fps=30):
        self.w, self.h = w, h
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                   "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0", "-c:v", "libx264", "-preset",
                                   "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                                   str(path)], stdin=subprocess.PIPE)

    def add(self, fig):
        fig.canvas.draw()
        a = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
        self.p.stdin.write(np.ascontiguousarray(a).tobytes())

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def video(meta, calls, summ, path: Path, fps=30):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    C = DARK
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"]})
    r = pick_call(calls)
    T = r["t"]
    t0 = T["capture"]
    rel = {k: (v - t0) * 1e3 for k, v in T.items() if v is not None}
    f_call = r["frame"]
    track = {int(f): (x, y) for f, x, y in r.get("track", [])}
    W, H = 1280, 720
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=C["page"])
    wr = Writer(path, W, H, fps)
    mk = r["market"]
    names = mk["names"]
    o, fl, nw = r["order"], r["fill"], r["network"]
    dec = r["decision"]
    foot = LABEL
    fps_in = float((summ["budget_with_1s_simulated_feed"].get("conditions") or {}).get("stream_fps") or 10.0)

    def chrome(title, sub=None):
        fig.clf()
        fig.patch.set_facecolor(C["page"])
        fig.text(0.03, 0.955, title, fontsize=19, color=C["ink"], fontweight="bold", va="top")
        if sub:
            fig.text(0.03, 0.905, sub, fontsize=11.5, color=C["ink2"], va="top")
        fig.text(0.03, 0.02, foot, fontsize=8.6, color=C["muted"])

    # ---- part 1: the clip and the call (9 s)
    f_lo, f_hi = f_call - 100, f_call + 26
    frames = clip_frames(f_lo, f_hi, (960, 540))
    order = sorted(frames)
    n1 = 9 * fps
    for i in range(n1):
        f = order[min(len(order) - 1, int(i / n1 * len(order)))]
        chrome("1. Our own clip, streamed over WebRTC into the CV engine",
               f"OpenTTGames test_2 (held out), 120 fps source sent at {fps_in:g} frames/s, every frame "
               f"({120 / fps_in:.0f}x slow motion; the laptop cannot run 120 fps in real time); frame {f}")
        ax = fig.add_axes([0.125, 0.105, 0.75, 0.75])
        ax.imshow(frames[f])
        ax.set_axis_off()
        pts = [(ff, track[ff]) for ff in range(f - 40, f + 1) if ff in track]
        if pts:
            xs = [p[1][0] * 960 / 1920 for p in pts]
            ys_ = [p[1][1] * 540 / 1080 for p in pts]
            ax.plot(xs, ys_, color=C["yellow"], lw=2, alpha=0.9)
            ax.scatter(xs[-1:], ys_[-1:], s=60, color=C["yellow"], edgecolors=C["page"], linewidths=2, zorder=5)
        ax.text(10, 22, "engine ball track", color=C["ink"], fontsize=11,
                bbox=dict(boxstyle="round,pad=0.3", fc=C["surface"], ec="none", alpha=0.85))
        if f >= f_call:
            ax.text(480, 470, f"MISS call at frame {f_call}   p(miss) {r['p_miss']:.2f}\n"
                              f"capture to call {rel['call_emitted']:.1f} ms (WebRTC {rel['handoff']:.1f} + engine "
                              f"{rel['call_emitted'] - rel['handoff']:.1f})",
                    ha="center", va="center", color=C["ink"], fontsize=15, fontweight="bold", linespacing=1.4,
                    bbox=dict(boxstyle="round,pad=0.5", fc=C["surface"], ec=C["yellow"], lw=2))
        wr.add(fig)

    # ---- part 2: the order timeline racing the live book ticker (13 s)
    stages = [("capture", "frame captured (virtual camera)"), ("frame_sent", "frame sent into the encoder"),
              ("frame_received", "frame received (last RTP packet)"), ("decoded", "decoded (H.264)"),
              ("detected", "ball detected"), ("call_emitted", "MISS call emitted"),
              ("decision", "strategy decision (live book)"), ("risk_checked", "risk checked"),
              ("order_ready", "order ready (unsigned, not sent)"), ("network_arrival", "at venue (+ RTT/2)"),
              ("executable", "executable (+ secondsDelay)")]
    stages = [(k, lab) for k, lab in stages if k in rel]
    t_end = rel["executable"]
    tk = r.get("ticker", {}).get("rows", [])
    tk_t = np.array([(x[0] - t0) * 1e3 for x in tk]) if tk else np.array([])
    bid = np.array([np.nan if x[3] is None else x[3] for x in tk], float) if tk else np.array([])
    ask = np.array([np.nan if x[4] is None else x[4] for x in tk], float) if tk else np.array([])
    asz = [x[6] for x in tk]
    bsz = [x[5] for x in tk]
    # the cursor: 0 -> order ready slowly (one stage at a time), then on to the fill, then hold
    n_ours, n_rest, n_hold = int(5.0 * fps), int(5.5 * fps), int(2.5 * fps)
    sched = list(np.linspace(-5, rel["order_ready"] + 2, n_ours)) + \
        list(np.linspace(rel["order_ready"] + 2, t_end + 120, n_rest)) + [t_end + 120] * n_hold
    win = (-600.0, t_end + 450.0)
    lim_px = o["limit"]
    ob = r["book_at_order_ready"]
    side_name = o.get("outcome_name") or names[o.get("outcome", 0)]
    spans = [(0.0, rel["order_ready"], C["blue"], "our pipeline"),
             (rel["order_ready"], rel["network_arrival"], C["orange"], "network"),
             (rel["network_arrival"], t_end, C["aqua"], "venue delay")]
    for tc in sched:
        rk_ = r.get("risk") or {}
        chrome("2. The order, stage by stage, against the live book",
               f"{mk['slug']} (pre-match)  ·  buy {side_name} @ <= {lim_px:.2f}  ·  {o['kind'].replace('_', ' ')} "
               f"(rule: {dec['action']}{', ' + dec['reason'] if dec['reason'] else ''}; risk: "
               f"{'ok' if rk_.get('ok') else 'declined, ' + str(rk_.get('reason'))})")
        # left: the stage clock
        y = 0.8
        fig.text(0.03, y + 0.035, "ms after capture", fontsize=10, color=C["muted"])
        for k, lab in stages:
            on = rel[k] <= tc + 1e-9
            col = C["ink"] if on else C["axis"]
            fig.text(0.03, y, lab, fontsize=11.5, color=col, va="top")
            fig.text(0.355, y, f"{rel[k]:,.1f}", fontsize=11.5, color=col, va="top", ha="right",
                     fontweight="bold" if k in ("call_emitted", "order_ready", "executable") and on else "normal")
            y -= 0.052
        if tc >= t_end:
            if fl.get("vwap") is not None:
                msg = f"paper fill {fl['shares']:,.0f} @ {fl['vwap']:.3f}\n(fee ${fl['fee']:.2f}, {fl['status']})"
            else:
                msg = f"paper order missed\n({fl.get('reason')})"
            fig.text(0.03, y - 0.01, msg, fontsize=12.5, color=C["ink"], va="top", fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.4", fc=C["surface"], ec=C["aqua"], lw=1.5))
        # right top: the whole path on one linear axis
        af = fig.add_axes([0.43, 0.715, 0.54, 0.075])
        af.set_facecolor(C["surface"])
        af.set_xlim(*win)
        af.set_ylim(0, 1)
        af.set_yticks([])
        af.tick_params(labelbottom=False, length=0)
        for s in af.spines.values():
            s.set_visible(False)
        for x0, x1, col, lab in spans:
            if tc > x0:
                af.barh(0.5, min(tc, x1) - x0, left=x0, height=0.62, color=col, lw=0)
        for j, (x0, x1, col, lab) in enumerate(spans):
            if tc >= x1:     # short spans: label to the left above (ours) / below (network); venue centred above
                txt = f"{lab} {x1 - x0:,.0f} ms"
                if j == 2:
                    af.text((x0 + x1) / 2, 0.92, txt, ha="center", va="bottom", fontsize=10.5, color=C["ink"])
                elif j == 0:
                    af.text(x0 - 12, 0.5, txt, ha="right", va="center", fontsize=10.5, color=C["ink"])
                else:
                    af.text(x0, 0.92, txt, ha="left", va="bottom", fontsize=10.5, color=C["ink"])
        # right bottom: the live book of the token being bought
        ax = fig.add_axes([0.43, 0.15, 0.54, 0.47], sharex=af)
        ax.set_facecolor(C["surface"])
        ax.tick_params(colors=C["muted"], labelsize=9.5, length=0)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(C["axis"])
        ax.grid(axis="y", color=C["grid"], lw=0.8)
        ax.set_xlabel("ms after capture", color=C["ink2"], fontsize=10.5)
        for x0, x1, col, lab in spans:
            if tc > x0:
                ax.axvspan(x0, min(tc, x1), color=col, alpha=0.12, lw=0)
        if len(tk_t):
            m = (tk_t <= tc) & (tk_t >= win[0])
            ax.step(tk_t[m], bid[m], where="post", color=C["blue"], lw=2, label="best bid")
            ax.step(tk_t[m], ask[m], where="post", color=C["orange"], lw=2, label="best ask")
            inwin = (tk_t >= win[0]) & (tk_t <= win[1])
            lo = np.nanmin(np.r_[bid[inwin], ask[inwin], lim_px]) - 0.012
            hi = np.nanmax(np.r_[bid[inwin], ask[inwin], lim_px]) + 0.012
            ax.set_ylim(lo, hi)
            j = np.searchsorted(tk_t, tc, side="right") - 1
            if j >= 0:
                ax.set_title(f"live book, {side_name}:  bid {bid[j]:.3f} x {bsz[j] or 0:,.0f}   |   ask {ask[j]:.3f} x "
                             f"{asz[j] or 0:,.0f}", loc="left", color=C["ink"], fontsize=11.5, pad=8)
        ax.axhline(lim_px, color=C["ink2"], ls=(0, (1.5, 2)), lw=1)
        ax.text(win[0] + 15, lim_px, f"our limit {lim_px:.2f}", color=C["ink2"], fontsize=9.5, va="bottom", ha="left")
        ax.legend(loc="lower left", frameon=False, labelcolor=C["ink2"], fontsize=9.5, ncol=2)
        ax.axvline(min(tc, win[1]), color=C["ink"], lw=1, alpha=0.7)
        if tc >= t_end and fl.get("vwap") is not None:
            ax.scatter([t_end], [fl["vwap"]], s=120, color=C["aqua"], edgecolors=C["surface"], linewidths=2, zorder=6)
        fig.text(0.97, 0.95, f"RTT {nw['rtt_ms']:.0f} ms measured at order ready  ·  venue delay "
                             f"{r['venue']['seconds_delay']:.0f} s", ha="right", va="top", fontsize=11, color=C["ink2"])
        wr.add(fig)

    # ---- part 3: the run's numbers (4 s)
    B = summ["budget_with_1s_simulated_feed"]
    sp = summ["spans_ms"]
    cnt = summ["counts"]
    cd = B.get("conditions") or {}
    imp = summ["reprice_reference"].get("implied_after_point_s") or {}
    aft = B.get("executable_after_median_reprice_ms") or {}
    n_ = cnt["complete_order_traces"]
    lines = [
        (f"{n_} MISS calls on {len(cnt['markets'])} live pre-match tennis book"
         f"{'s' if len(cnt['markets']) != 1 else ''} ({', '.join(cnt['markets'])}), every stage logged", C["ink2"], 12),
        (f"CV fed at {cd.get('stream_fps', 10):g} frames/s, every frame ({cd.get('slow_motion', '12x')} slow motion; the "
         f"laptop cannot run 120 fps in real time)", C["yellow"], 12.5),
        (f"all {n_} orders were timing probes: the rule and the risk check declined every call (pre-match books)",
         C["yellow"], 12.5),
        (f"our pipeline, capture to order ready:  p50 {sp['capture_to_order_ready']['p50']:.1f} ms  "
         f"(max {sp['capture_to_order_ready']['max']:.1f}, n = {n_})", C["ink"], 17),
        (f"network one-way (RTT/2):  p50 {B['network_one_way_ms']['p50']:.0f} ms     venue delay  "
         f"{B['venue_delay_ms']['p50']:,.0f} ms", C["ink"], 17),
        (f"with the 1 s simulated feed:  {B['total_ms']['p50']:,.0f} ms p50 (max {B['total_ms']['max']:,.0f})  vs  "
         f"< 3,000 ms required", C["ink"], 19),
        ((f"executable {min(aft.values()) / 1e3:.2f}-{max(aft.values()) / 1e3:.2f} s after the median reprice "
          f"({' / '.join(f'{v:.2f}' for v in sorted(imp.values()))} s after the point, by unmeasured stamp lag)")
         if aft else "", C["ink2"], 12.5),
        (f"the 1 s feed and the venue's 1 s order delay, not our {sp['capture_to_order_ready']['p50']:.0f} ms, "
         f"are what make it late", C["ink2"], 12.5),
    ]
    for i in range(5 * fps):
        chrome("3. The run", None)
        y = 0.86
        for txt, col, fs in lines:
            fig.text(0.05, y, txt, fontsize=fs, color=col, va="top",
                     fontweight="bold" if fs >= 17 else "normal")
            y -= 0.026 + fs * 0.0042
        wr.add(fig)
    wr.close()
    plt.close(fig)
    print(f"wrote {path} (featured call rid {r['rid']}, frame {f_call}, {mk['slug']})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--figure-only", action="store_true")
    ap.add_argument("--video-only", action="store_true")
    a = ap.parse_args(argv)
    meta, calls, summ = load()
    if not a.video_only:
        figure(summ, OUT / "fig_waterfall.png")
    if not a.figure_only:
        video(meta, calls, summ, OUT / "e2e_timeline.mp4")


if __name__ == "__main__":
    main()
