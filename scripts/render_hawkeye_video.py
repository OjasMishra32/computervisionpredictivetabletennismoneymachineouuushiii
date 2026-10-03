"""Render the Hawk-Eye-style replay + real tape as an MP4 (results/viz/courtside_replay.mp4).

Same data as the interactive page (results/viz/viz_data.json): a simulated groundstroke
landing 13.7 cm long, the tracker's landing estimate as the ball flies, then the real
Polymarket tape around a 9.2c jump with fast-tier prints highlighted.
"""
import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Ellipse, Polygon, Rectangle  # noqa: E402

D = json.loads(Path("results/viz/viz_data.json").read_text())
OUT = Path("results/viz/courtside_replay.mp4")
FRAMES = Path("data/v2_video_frames")
W, H, FPS = 1280, 720, 30
BG, SURR, COURT, LINE, BALL = "#0a1a2a", "#2d5a49", "#27598b", "#f4f7fa", "#d9f24b"
AMBER, RED, INK, MUTED, FAST, OTHERS = "#f2b33d", "#ff6b5a", "#e6eef6", "#8fa2b5", "#3987e5", "#eb6834"
BL = 23.77
TB = D["shot"]["t_bounce"]
TRAJ = np.array(D["shot"]["traj"])
LAND = D["shot"]["land"]
PREDS = D["shot"]["preds"]
CALL_LEAD = max(p["lead_ms"] for p in PREDS if p["p_out"] >= 0.95)

CAM, TGT = np.array([2.4, -14.5, 11.5]), np.array([-0.9, 14.2, 0.0])
F = (TGT - CAM) / np.linalg.norm(TGT - CAM)
R = np.cross(F, [0, 0, 1]); R /= np.linalg.norm(R)
UPV = np.cross(R, F)


def raw(p):
    d = np.asarray(p) - CAM
    z = d @ F
    return np.array([d @ R / z, d @ UPV / z, z])


box = np.array([raw(p) for p in [[-5.485, 0, 0], [5.485, 0, 0], [-5.485, BL, 0], [5.485, BL, 0], [0, 12, 2.6], [0, -1.5, 0], [0, 25.2, 0]]])
CW, CH = 820, H  # court view occupies the left part of the frame
S = min(CW * 0.92 / np.ptp(box[:, 0]), CH * 0.86 / np.ptp(box[:, 1]))
OX = CW / 2 - S * (box[:, 0].min() + box[:, 0].max()) / 2
OY = CH / 2 + S * (box[:, 1].min() + box[:, 1].max()) / 2 + 10


def P(p):
    x, y, z = raw(p)
    return np.array([OX + x * S, OY - y * S]), z


def poly(ax, pts, **kw):
    ax.add_patch(Polygon([P(p)[0] for p in pts], closed=True, **kw))


def seg(ax, a, b, w=0.05, color=LINE):
    (pa, za), (pb, zb) = P(a), P(b)
    ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color=color, lw=max(0.8, S * w / ((za + zb) / 2) * 0.75), solid_capstyle="butt")


def ball_at(tf):
    i = np.searchsorted(TRAJ[:, 0], tf)
    if i <= 0:
        return TRAJ[0, 1:]
    if i >= len(TRAJ):
        return TRAJ[-1, 1:]
    a, b = TRAJ[i - 1], TRAJ[i]
    u = (tf - a[0]) / (b[0] - a[0])
    return a[1:] + u * (b[1:] - a[1:])


def pred_at(lead):
    c = [p for p in PREDS if p["lead_ms"] >= lead]
    return min(c, key=lambda p: p["lead_ms"]) if c and 0 <= lead <= 400 else None


def world_ellipse(ax, x, y, rx, ry, fc, ec):
    a = np.linspace(0, 2 * np.pi, 48)
    poly(ax, np.c_[x + rx * np.cos(a), y + ry * np.sin(a), np.zeros_like(a)], fc=fc, ec=ec, lw=1.6)


def draw_court(ax, T):
    ax.add_patch(Rectangle((0, 0), CW, H, color=BG))
    poly(ax, [[-9.6, -6.4, 0], [9.6, -6.4, 0], [9.6, 30.2, 0], [-9.6, 30.2, 0]], color=SURR)
    poly(ax, [[-5.485, 0, 0], [5.485, 0, 0], [5.485, BL, 0], [-5.485, BL, 0]], color=COURT)
    for a, b in [((-5.485, 0), (5.485, 0)), ((-5.485, BL), (5.485, BL)), ((-5.485, 0), (-5.485, BL)), ((5.485, 0), (5.485, BL)),
                 ((-4.115, 0), (-4.115, BL)), ((4.115, 0), (4.115, BL)), ((-4.115, 5.485), (4.115, 5.485)),
                 ((-4.115, 18.285), (4.115, 18.285)), ((0, 5.485), (0, 18.285))]:
        seg(ax, (*a, 0), (*b, 0))
    flying = T < 0
    b = ball_at(T + TB) if flying else np.array([LAND[0], LAND[1], 0.034])

    def net():
        poly(ax, [[-6.4, 11.885, 0], [6.4, 11.885, 0], [6.4, 11.885, 1.07], [0, 11.885, 0.914], [-6.4, 11.885, 1.07]], fc=(0.04, 0.07, 0.11, 0.55))
        seg(ax, (-6.4, 11.885, 1.07), (0, 11.885, 0.914)); seg(ax, (0, 11.885, 0.914), (6.4, 11.885, 1.07))
    if b[1] <= 11.885:
        net()
    pr = pred_at(-T * 1000) if flying else None
    if pr:
        called = pr["p_out"] >= 0.95
        world_ellipse(ax, pr["x"], pr["y"], 2 * pr["sx"], 2 * pr["sy"], (1, .42, .35, .32) if called else (.95, .7, .24, .25), RED if called else AMBER)
    if not flying:
        world_ellipse(ax, LAND[0], LAND[1] - 0.04, 0.035, 0.09, (1, 1, 1, .9), "white")
    if flying and T + TB > 0:
        tr = TRAJ[(TRAJ[:, 0] <= T + TB) & (TRAJ[:, 0] >= T + TB - 0.3)]
        for i in range(1, len(tr)):
            (pa, _), (pb, z) = P(tr[i - 1, 1:]), P(tr[i, 1:])
            ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color=BALL, alpha=0.75 * i / len(tr), lw=max(1.2, S * 0.05 / z))
        (sh, zs) = P([b[0], b[1], 0])
        ax.add_patch(Ellipse(sh, max(4, S * 0.18 / zs), max(2, S * 0.08 / zs), color=(0, 0, 0, .35)))
        (q, zq) = P(b)
        ax.add_patch(plt.Circle(q, max(3.5, S * 0.1 / zq), color=BALL))
    if b[1] > 11.885:
        net()
    return pr


def draw_inset(ax, pr, flying):
    sz, x0, y0, half = 180, 18, 125, 0.45
    cxw, cyw = LAND[0], BL + 0.05
    mx = lambda x: x0 + (x - (cxw - half)) / (2 * half) * sz
    my = lambda y: y0 + ((cyw + half) - y) / (2 * half) * sz
    pxm = sz / (2 * half)
    ax.add_patch(Rectangle((x0, y0), sz, sz, color=SURR))
    ax.add_patch(Rectangle((x0, my(BL)), sz, y0 + sz - my(BL), color=COURT))
    ax.add_patch(Rectangle((x0, my(BL)), sz, my(BL - 0.05) - my(BL), color=LINE))
    if pr:
        called = pr["p_out"] >= 0.95
        ax.add_patch(Ellipse((mx(pr["x"]), my(pr["y"])), max(3, 4 * pr["sx"] * pxm), max(3, 4 * pr["sy"] * pxm),
                             fc=(1, .42, .35, .32) if called else (.95, .7, .24, .25), ec=RED if called else AMBER, lw=1.6, clip_on=True))
    if not flying:
        ax.add_patch(plt.Circle((mx(LAND[0]), my(LAND[1])), 0.0335 * pxm, color="white"))
        ax.plot([mx(LAND[0]) + 14] * 2, [my(BL), my(LAND[1] + 0.0335)], color=RED, ls="--", lw=1.4)
        ax.text(x0 + 8, y0 + 18, f"OUT {D['shot']['out_cm']:.1f} cm", color="#ffd2cb", fontsize=12, family="monospace", va="center", weight="bold")
    ax.add_patch(Rectangle((x0, y0), sz, sz, fill=False, ec=(1, 1, 1, .45), lw=1))
    ax.text(x0 + 6, y0 + sz - 8, "ZOOM · 90 cm", color=INK, fontsize=9, family="monospace", alpha=.85)


def draw_hud(ax, T, pr):
    if T < 0:
        called = pr is not None and pr["p_out"] >= 0.95
        chip, col = ("OUT CALLED", RED) if called else ("TRACKING", AMBER)
        lines = [f"to bounce   {int(round(-T * 1000))} ms", f"P(out)      {int(round(pr['p_out'] * 100)) if pr else 0}%",
                 f"landing ±2σ {2 * pr['sy'] * 100:.1f} cm" if pr else "landing ±2σ fitting…"]
    else:
        chip, col = f"CALLED {CALL_LEAD} MS EARLY", INK
        lines = ["to bounce   landed", "P(out)      100%", f"out by      {D['shot']['out_cm']:.1f} cm"]
    ax.text(22, 30, chip, color=col, fontsize=14, family="monospace", weight="bold",
            bbox=dict(boxstyle="round,pad=0.45", fc=(0, 0, 0, .35), ec=col, lw=1.2))
    for i, s in enumerate(lines):
        ax.text(22, 68 + 22 * i, s, color=INK if i == 0 else MUTED, fontsize=12, family="monospace")
    ax.text(22, H - 22, "Physics replay · 340 fps tracking, ±3.6 mm noise · slow motion", color=MUTED, fontsize=10, family="monospace")


TP = D["tape"]
PR = [p for p in TP["prints"] if -60 <= p["t"] <= 150]
g10 = lambda t: np.sign(t) * np.log10(1 + abs(t))
pv = np.sort([p["p"] * 100 for p in PR])
YD = (np.floor(pv[0] - 1), np.ceil(pv[-1] + 1))


def draw_tape(ax, T):
    x0, x1, y0, y1 = CW + 40, W - 24, 120, H - 110
    ax.add_patch(Rectangle((CW, 0), W - CW, H, color="#0e1b29"))
    xt = lambda t: x0 + (g10(np.clip(t, -60, 150)) - g10(-60)) / (g10(150) - g10(-60)) * (x1 - x0)
    yp = lambda c: y0 + (YD[1] - c) / (YD[1] - YD[0]) * (y1 - y0)
    ax.add_patch(Rectangle((xt(0), y0), xt(3) - xt(0), y1 - y0, color=FAST, alpha=.16))
    for c in np.arange(np.ceil(YD[0] / 5) * 5, YD[1] + 1, 5):
        ax.plot([x0, x1], [yp(c)] * 2, color=(1, 1, 1, .08), lw=1)
        ax.text(x0 - 8, yp(c), f"{int(c)}¢", color=MUTED, fontsize=9, family="monospace", ha="right", va="center")
    for t in (-60, -10, 0, 3, 10, 60, 150):
        ax.text(xt(t), y1 + 18, f"{'+' if t > 0 else ''}{t}", color=MUTED, fontsize=9, family="monospace", ha="center")
    ax.text((x0 + x1) / 2, y1 + 40, "seconds from the point (log)", color=MUTED, fontsize=9, family="monospace", ha="center")
    for p in sorted(PR, key=lambda p: p["fast"]):
        vis = p["t"] <= T
        ax.add_patch(plt.Circle((xt(p["t"]), yp(p["p"] * 100)), 7 if p["fast"] else 4.5, color=FAST if p["fast"] else OTHERS,
                                alpha=1 if vis else .1, ec="#0e1b29", lw=1.5))
    ax.plot([xt(T)] * 2, [y0, y1], color=INK, lw=1, ls=(0, (3, 3)))
    name = TP["out0"].split(" ")[-1] + " vs " + TP["out1"].split(" ")[-1]
    ax.text(x0 - 30, 46, f"Real tape · {name}", color=INK, fontsize=15, weight="bold")
    ax.text(x0 - 30, 72, f"{TP['title'].split(':')[0]} · {TP['date']} · {TP['out0'].split(' ')[-1]} to win", color=MUTED, fontsize=10)
    ax.add_patch(plt.Circle((x0 - 22, 96), 6, color=FAST)); ax.text(x0 - 10, 96, "fast-tier wallet", color=INK, fontsize=10, va="center")
    ax.add_patch(plt.Circle((x0 + 130, 96), 4.5, color=OTHERS)); ax.text(x0 + 142, 96, "everyone else", color=INK, fontsize=10, va="center")
    if T >= 0:
        msg = "fast tier picks off stale quotes" if T < 3 else ("everyone else pays ~1¢ a share" if T < 55 else "public score feed finally updates")
        ax.text(x0 - 30, H - 40, msg, color=FAST if T < 3 else (OTHERS if T < 55 else INK), fontsize=13, weight="bold")


def frame(i, T):
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    pr = draw_court(ax, T)
    draw_inset(ax, pr, T < 0)
    draw_hud(ax, T, pr)
    draw_tape(ax, T)
    fig.savefig(FRAMES / f"f{i:04d}.png", dpi=100, facecolor=BG)
    plt.close(fig)


if __name__ == "__main__":
    FRAMES.mkdir(parents=True, exist_ok=True)
    for f in FRAMES.glob("*.png"):
        f.unlink()
    ts = list(np.linspace(-TB, 0, int(4.2 * FPS)))                 # ~0.23x slow motion flight
    ts += [0.0] * int(0.8 * FPS)                                    # hold on the call
    ts += list(((np.linspace(0, 1, int(7 * FPS))) ** 2) * 150)      # market: 0 -> 150 s, eased
    ts += [150.0] * int(1.0 * FPS)
    for i, T in enumerate(ts):
        frame(i, float(T))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(FRAMES / "f%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(OUT)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(FRAMES / f"f{int(4.4 * FPS):04d}.png"), str(OUT.with_suffix(".png"))], check=True)
    print("wrote", OUT, OUT.stat().st_size // 1024, "KB,", len(ts) / FPS, "s")
