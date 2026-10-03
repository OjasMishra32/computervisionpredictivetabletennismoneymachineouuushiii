"""CV showcase reel and stills: early ball calls on real table-tennis footage, a 1/4x replay, a simulated
tennis Hawk-Eye-class replay and a speed card.

    results/viz/cv_showcase.mp4     1920x1080, 30 fps, H.264, faststart, no audio
    results/viz/stills/*.png        8 stills, 300 dpi, plus captions.json
    results/viz/cv_showcase_manifest.json   segment timing, inputs and every number shown

Presentation only. This script computes no metric and fits no classifier. Inputs and labels:

 * Real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0). data/cv_showcase/ holds the raw frames
   around four held-out test flights, their BlurBall tracks and the FROZEN tier-0 model's per-frame P(MISS).
   scripts/cv_showcase_assets.py made it on HiPerGator: it refits the frozen HGB exactly as
   `early_call.py --final` did and asserts that its scores and first-call leads reproduce
   results/tracking/test_flights.csv.
 * Every CALL shown on real footage is the frozen model's (online rule: P(MISS) >= tau_online on 3
   consecutive decision frames). The spin-aware model did not pass its single test run (10/12 = 0.83
   precision at 50 ms, results/spin/tt/test/report_numbers.json), so it makes no call here.
 * The predicted arc, its uncertainty cone, the table-height crossing ellipse, P(in/long/net/wide) and the
   spin readout on the featured flight (test_2, f_net 2819) come from the online drag + Magnus physics fit
   (src/spin/tt_physics.py), re-run here frame by frame exactly as src/spin/tt_features.py does. They are
   labelled "display only". The re-run is checked against results/spin/tt/test/showcase/test_2_2819.json,
   which HiPerGator wrote after the test evaluation.
 * Tennis: simulated physics: Hawk-Eye-class camera model (not real footage). One shot from the nominal
   simulated population (src/spin/physics.build_population, seed 7, the population behind
   results/spin/tennis/), fitted frame by frame with the spin-aware batch fit `bls`
   (src/spin/tennis_filter.bls_fit). Population numbers come from results/spin/tennis/key_numbers.json.
 * Speed card: research/v2/latency/RESULTS.md (live Polymarket books vs the official WTA point log,
   2026-10-03; no match video) and research/v2/feed_latency/LATENCY_SWEEP.md. No live Polymarket match
   video exists or is implied.

Usage (repo root):
    python scripts/cv_showcase.py                 # prep (cached) + video + stills
    python scripts/cv_showcase.py --only video    # or: stills, prep
    python scripts/cv_showcase.py --preview 12.5 40 --out-dir /tmp/x   # single frames at those seconds
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (REPO, os.path.join(REPO, "src", "spin"), os.path.join(REPO, "src", "tracking"),
           os.path.join(REPO, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ASSETS = os.path.join(REPO, "data", "cv_showcase")
PREP = os.path.join(ASSETS, "prep.pkl")
VIZ = os.path.join(REPO, "results", "viz")
OUT_MP4 = os.path.join(VIZ, "cv_showcase.mp4")
STILLS = os.path.join(VIZ, "stills")
MANIFEST = os.path.join(VIZ, "cv_showcase_manifest.json")

W, H, FPS = 1920, 1080, 30
SS = 2                       # supersampling of the overlay layer (anti-aliasing)
SRC_FPS = 120.0

LBL_REAL = "real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0)"
LBL_SIM = "simulated physics: Hawk-Eye-class camera model (not real footage)"
LBL_MKT = "market timing: live Polymarket books vs the official WTA point log (2026-10-03); no match video"

# ------------------------------------------------------------------------------------------- style
NAVY0 = (5, 11, 26)
NAVY1 = (10, 21, 46)
NAVY2 = (18, 34, 68)
WHITE = (255, 255, 255)
MUTED = (148, 163, 194)
DIM = (92, 108, 140)
ACCENT = (58, 148, 255)
CORAL = (255, 104, 88)
BALL_T = (226, 240, 96)       # tennis ball (scene object, not UI)

# table-tennis HUD band and its four columns (x of each column's text)
HUD_Y0, HUD_Y1 = 852, 1004
COL2, COL3, COL4 = 528, 920, 1380

FONT_DIR = "/Library/Fonts"
F_FILES = {w: os.path.join(FONT_DIR, f"SF-Pro-Display-{w}.otf") for w in
           ("Light", "Regular", "Medium", "Semibold", "Bold")}
F_MONO = "/System/Library/Fonts/SFNSMono.ttf"


def _fallback(bold=False, mono=False):
    import matplotlib.font_manager as fm
    name = "DejaVu Sans Mono" if mono else "DejaVu Sans"
    return fm.findfont(name + (":bold" if bold else ""))


_FC = {}


def font(size, weight="Regular", mono=False, ss=None):
    ss = SS if ss is None else ss
    key = (size, weight, mono, ss)
    if key not in _FC:
        px = max(1, int(round(size * ss)))
        if mono:
            try:
                f = ImageFont.truetype(F_MONO, px)
                f.set_variation_by_name(weight if weight != "Regular" else "Regular")
            except Exception:
                f = ImageFont.truetype(_fallback(weight in ("Semibold", "Bold"), True), px)
        else:
            path = F_FILES.get(weight)
            if path and os.path.exists(path):
                f = ImageFont.truetype(path, px)
            else:
                f = ImageFont.truetype(_fallback(weight in ("Semibold", "Bold")), px)
        _FC[key] = f
    return _FC[key]


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def rgba(c, a=1.0):
    return (int(c[0]), int(c[1]), int(c[2]), int(round(255 * min(max(a, 0.0), 1.0))))


def mix(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def fmt_int(x):
    return f"{int(round(x)):,}"


def signed(v, spec="+.0f"):
    """Number with a typographic minus (U+2212), as on every other on-screen negative."""
    return format(v, spec).replace("-", "−")


# ------------------------------------------------------------------------------------------ canvas
class Canvas:
    """RGB frame drawn at SS x supersampling (footage upscaled with NEAREST, so reduce() returns it
    unchanged), plus a 1x glow layer blurred and added at the end."""

    def __init__(self, base=None, ss=None):
        ss = SS if ss is None else ss
        self.ss = ss
        if base is None:
            base = np.zeros((H, W, 3), np.uint8)
        self.im = Image.fromarray(base).resize((W * ss, H * ss), Image.NEAREST)
        self.d = ImageDraw.Draw(self.im, "RGBA")
        self.glow = None

    # coordinates are in 1920x1080 units
    def _p(self, pts):
        s = self.ss
        return [(float(x) * s, float(y) * s) for x, y in pts]

    def line(self, pts, col, width=2.0, a=1.0, joint="curve"):
        if len(pts) < 2:
            return
        self.d.line(self._p(pts), fill=rgba(col, a), width=max(1, int(round(width * self.ss))), joint=joint)

    def poly(self, pts, fill=None, a=1.0, outline=None, oa=1.0, width=1.0):
        if len(pts) < 3:
            return
        P = self._p(pts)
        if fill is not None:
            self.d.polygon(P, fill=rgba(fill, a))
        if outline is not None:
            self.d.line(P + [P[0]], fill=rgba(outline, oa), width=max(1, int(round(width * self.ss))))

    def rrect(self, box, r=10, fill=None, a=1.0, outline=None, oa=1.0, width=1.0):
        s = self.ss
        b = [box[0] * s, box[1] * s, box[2] * s, box[3] * s]
        if b[2] <= b[0] or b[3] <= b[1]:
            return
        self.d.rounded_rectangle(b, radius=r * s, fill=None if fill is None else rgba(fill, a),
                                 outline=None if outline is None else rgba(outline, oa),
                                 width=max(1, int(round(width * s))))

    def rect(self, box, fill, a=1.0):
        s = self.ss
        x0, y0, x1, y1 = box[0] * s, box[1] * s, box[2] * s - 1, box[3] * s - 1
        if x1 < x0 or y1 < y0:
            return
        self.d.rectangle([x0, y0, x1, y1], fill=rgba(fill, a))

    def circle(self, c, r, fill=None, a=1.0, outline=None, oa=1.0, width=1.0):
        s = self.ss
        x, y = c
        b = [(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s]
        self.d.ellipse(b, fill=None if fill is None else rgba(fill, a),
                       outline=None if outline is None else rgba(outline, oa), width=max(1, int(round(width * s))))

    def arc(self, c, r, a0, a1, col, width=2.0, a=1.0):
        s = self.ss
        x, y = c
        self.d.arc([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], a0, a1, fill=rgba(col, a),
                   width=max(1, int(round(width * s))))

    def text(self, xy, txt, size=20, weight="Regular", col=WHITE, a=1.0, anchor="la", mono=False, tracking=0.0):
        f = font(size, weight, mono, self.ss)
        s = self.ss
        if not tracking:
            self.d.text((xy[0] * s, xy[1] * s), txt, font=f, fill=rgba(col, a), anchor=anchor)
            return
        total = self.textlen(txt, size, weight, mono, tracking)
        x = xy[0] - (total if anchor[0] == "r" else total / 2 if anchor[0] == "m" else 0)
        for ch in txt:
            self.d.text((x * s, xy[1] * s), ch, font=f, fill=rgba(col, a), anchor="l" + anchor[1])
            x += f.getlength(ch) / s + tracking

    def textlen(self, txt, size=20, weight="Regular", mono=False, tracking=0.0):
        f = font(size, weight, mono, self.ss)
        return f.getlength(txt) / self.ss + tracking * len(txt)

    # glow: drawn at 1x with cv2, blurred, added
    def glow_line(self, pts, col, width=6, a=1.0):
        import cv2
        if self.glow is None:
            self.glow = np.zeros((H, W, 3), np.float32)
        P = np.round(np.asarray(pts, float) * 4).astype(np.int32).reshape(-1, 1, 2)
        if len(P) < 2:
            return
        tmp = np.zeros((H, W, 3), np.float32)
        cv2.polylines(tmp, [P], False, tuple(float(c) * a for c in col), int(width), cv2.LINE_AA, shift=2)
        self.glow += tmp

    def glow_dot(self, c, r, col, a=1.0):
        import cv2
        if self.glow is None:
            self.glow = np.zeros((H, W, 3), np.float32)
        cv2.circle(self.glow, (int(round(c[0] * 4)), int(round(c[1] * 4))), int(r * 4),
                   tuple(float(x) * a for x in col), -1, cv2.LINE_AA, shift=2)

    def finish(self, blur=9.0, strength=0.9):
        import cv2
        out = np.asarray(self.im.reduce(self.ss))
        if self.glow is not None:
            g = cv2.GaussianBlur(self.glow, (0, 0), blur)
            out = np.clip(out.astype(np.float32) + strength * g, 0, 255).astype(np.uint8)
        return out


# ------------------------------------------------------------------------------- shared chrome
def chrome(cv, section, label, mode=None, mode_col=WHITE, a=1.0):
    """Wordmark + section (top left), honesty label (bottom left), mode tag (bottom right). Every text is
    >= 18 px and sits on its own backing so it reads over footage and court lines on a projector."""
    sw = cv.textlen(section, 18, "Medium", tracking=1.2)
    xw = 70 + cv.textlen("COURTSIDE", 20, "Semibold", tracking=3.0) + 14
    cv.rrect((34, 30, xw + 15 + sw + 16, 68), 9, NAVY0, 0.72 * a)
    cv.rect((48, 44, 58, 54), ACCENT, a)
    cv.text((70, 49), "COURTSIDE", 20, "Semibold", WHITE, a, "lm", tracking=3.0)
    x = xw
    cv.rect((x, 39, x + 1, 59), MUTED, 0.5 * a)
    cv.text((x + 15, 49), section, 18, "Medium", (196, 206, 226), a, "lm", tracking=1.2)
    # honesty / credit label
    tw = cv.textlen(label, 19, "Regular")
    cv.rrect((40, 1018, 40 + tw + 30, 1058), 9, NAVY0, 0.80 * a)
    cv.text((55, 1038), label, 19, "Regular", (232, 238, 250), a, "lm")
    if mode:
        mw = cv.textlen(mode, 17, "Semibold", tracking=1.6)
        cv.rrect((W - 40 - mw - 34, 1018, W - 40, 1058), 9, NAVY0, 0.80 * a)
        cv.circle((W - 40 - mw - 18, 1038), 5, mode_col, a)
        cv.text((W - 40 - mw - 6, 1038), mode, 17, "Semibold", WHITE, a, "lm", tracking=1.6)


def callout(cv, y, text, sub=None, t=1.0, col=CORAL, align="c"):
    """Big broadcast slab, wiped in from the left (t in 0..1). align 'l' / 'r' pins it to that side (40 px
    margin) so it stays clear of the table end the ball is flying towards."""
    if t <= 0:
        return
    size = 54
    tw = cv.textlen(text, size, "Bold", tracking=1.0)
    w = tw + 96
    sw = cv.textlen(sub, 20, "Regular") + 36 if sub else 0
    x0 = {"c": (W - w) / 2, "l": 40.0, "r": W - 40 - w}[align]
    xm = x0 + w / 2
    e = ease_out(t)
    x1 = x0 + w * e
    cv.rrect((x0, y, x1, y + 88), 6, col, 0.96)
    cv.rect((x0, y + 88, x0 + (x1 - x0) * min(1.0, e * 1.15), y + 92), WHITE, 0.9)
    # the text fades in only once the wipe has uncovered all of it (it used to spill past the slab mid-wipe)
    e_need = (xm + tw / 2 + 8 - x0) / w
    if e >= e_need:
        ta = ease((e - e_need) / max(1.0 - e_need, 1e-6)) if e < 1.0 else 1.0
        cv.text((xm, y + 45), text, size, "Bold", WHITE, ta, "mm", tracking=1.0)
    if sub and e >= e_need:
        sa = ease((e - e_need) / max(1.0 - e_need, 1e-6)) if e < 1.0 else 1.0
        xs = min(max(xm, 40 + sw / 2), W - 40 - sw / 2)
        cv.rrect((xs - sw / 2, y + 100, xs + sw / 2, y + 136), 7, NAVY0, 0.86 * sa)
        cv.text((xs, y + 118), sub, 20, "Regular", (232, 238, 250), sa, "mm")


def bar(cv, x, y, w, h, v, col, track=(255, 255, 255), ta=0.14, tick=None):
    cv.rrect((x, y, x + w, y + h), h / 2, track, ta)
    if v is not None and v > 0.003:
        cv.rrect((x, y, x + max(h, w * min(v, 1.0)), y + h), h / 2, col, 1.0)
    if tick is not None:
        xt = x + w * tick
        cv.rect((xt - 1, y - 4, xt + 1, y + h + 4), WHITE, 0.9)


def spin_glyph(cv, c, r, top_rpm, side_rpm, direction=1.0, phase=0.0, a=1.0):
    """Ball with a rotation arrow: topspin turns forward (clockwise for a ball flying right) and the
    axis tilts with the sidespin share."""
    cv.circle(c, r, NAVY2, 0.9 * a, WHITE, 0.85 * a, 1.6)
    tilt = math.degrees(math.atan2(side_rpm, max(abs(top_rpm), 1.0)))
    cw = (top_rpm >= 0) == (direction > 0)
    a0 = (phase * (1 if cw else -1)) % 360
    rr = r + 9
    cv.arc(c, rr, a0, a0 + 250, ACCENT, 3.0, a)
    end = math.radians(a0 + 250 if cw else a0)
    # arrow head at the leading end
    hx, hy = c[0] + rr * math.cos(end), c[1] + rr * math.sin(end)
    tang = end + (math.pi / 2 if cw else -math.pi / 2)
    p1 = (hx + 9 * math.cos(tang), hy + 9 * math.sin(tang))
    p2 = (hx + 6 * math.cos(tang + 2.5), hy + 6 * math.sin(tang + 2.5))
    p3 = (hx + 6 * math.cos(tang - 2.5), hy + 6 * math.sin(tang - 2.5))
    cv.poly([p1, p2, p3], ACCENT, a)
    # spin axis
    th = math.radians(90 + tilt)
    dx, dy = (r - 3) * math.cos(th), (r - 3) * math.sin(th)
    cv.line([(c[0] - dx, c[1] - dy), (c[0] + dx, c[1] + dy)], MUTED, 1.4, 0.8 * a)
    cv.circle(c, 2.5, WHITE, a)


# --------------------------------------------------------------------------------- footage reader
class ClipReader:
    """Sequential PyAV reader of one cut clip (frame i of the file = source frame first + i)."""

    def __init__(self, path, first):
        self.path, self.first = path, first
        self.c = None
        self.cache = {}
        self.cur = None

    def _open(self):
        import av
        if self.c is not None:
            self.c.close()
        self.c = av.open(self.path)
        st = self.c.streams.video[0]
        st.thread_type = "AUTO"
        self.it = self.c.decode(st)
        self.cur = self.first - 1

    def get(self, f):
        if f in self.cache:
            return self.cache[f]
        if self.c is None or f <= self.cur:
            self._open()
        img = None
        while self.cur < f:
            fr = next(self.it)
            self.cur += 1
            if self.cur >= f - 1:
                img = fr.to_ndarray(format="rgb24")
                self.cache[self.cur] = img
        # evict the frames farthest from f (evicting the smallest key dropped f itself after a backward seek,
        # e.g. the stills pass re-reading the call frame after the video pass)
        for k in sorted(self.cache, key=lambda k: abs(k - f), reverse=True)[:max(len(self.cache) - 6, 0)]:
            self.cache.pop(k)
        return self.cache[f]


_VIGN = None


def grade(img, dim=1.0):
    """Mild broadcast grade: a soft vignette so the graphics read; footage content is unchanged."""
    global _VIGN
    if _VIGN is None:
        y, x = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2)
        _VIGN = (1.0 - 0.28 * np.clip(r - 0.55, 0, 1) ** 1.6)[..., None]
    return np.clip(img.astype(np.float32) * _VIGN * dim, 0, 255).astype(np.uint8)


# ===================================================================================== PREP
def prep_tt(clip, cams, check_json=None):
    """Online physics fit at every decision frame (same loop as src/spin/tt_features.online_features)
    and, per frame, the mean predicted path, its 95% image cone and the table-height crossing ellipse."""
    import cv_showcase_tt_fits as SF
    import tt_camera
    import tt_features as TF
    import tt_physics as PH
    cam = tt_camera.Camera.from_dict(cams[clip["video"]]["camera"])
    trk = {int(k): tuple(v) for k, v in clip["track"].items()}
    t0, t_ref, d = clip["t0"], clip["t_ref"], clip["dir"]
    anchor, ainfo = TF.find_anchor(trk, t0, d, cam)
    fr = np.array([f for f in range(t0, t_ref + 1) if f in trk], int)
    uv = np.array([trk[f] for f in fr], float)
    dec = list(range(t0 + TF.NMIN - 1 + TF.LAG, t_ref + 1))
    fits = SF.online_fits(cam, fr, uv, d, dec, anchor, t0)
    out = {}
    for t, fit, prob, f in fits:
        if fit is None or f is None:
            continue
        n_now = int(t - TF.LAG - t0)
        SP = PH._sigma_points(fit.theta, fit.cov)
        B = len(SP)
        P, _ = PH.integrate(SP[:, :3], SP[:, 3:6], PH.spin_vectors(SP), n_now + PH.HORIZON_FRAMES)
        mean = P[:, 0]
        ks = np.arange(len(mean))
        end = len(mean) - 1
        hit = np.flatnonzero((ks > n_now) & (mean[:, 2] <= PH.R_BALL))
        if len(hit):
            end = int(hit[0])
        far = np.flatnonzero((ks > n_now) & (d * mean[:, 0] > PH.HALF_L + 1.2))
        if len(far):
            end = min(end, int(far[0]))
        seg = P[n_now:end + 1]                                    # (L, B, 3)
        UV = cam.project(seg)
        dev = UV[:, 1:] - UV[:, :1]
        S = np.einsum("lbi,lbj->lij", dev, dev) / (B - 1)
        m = UV[:, 0]
        tg = np.gradient(m, axis=0)
        tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-9)
        nrm = np.stack([-tg[:, 1], tg[:, 0]], 1)
        hw = 1.96 * np.sqrt(np.maximum(np.einsum("li,lij,lj->l", nrm, S, nrm), 0))
        # table-height crossing of every sigma point
        land = []
        for b in range(B):
            kl = PH._first_cross(P[:, b, 2], PH.R_BALL, n_now, rising=False)
            land.append(None if kl is None else PH._interp(P[:, b], kl))
        ell = None
        if land[0] is not None and all(x is not None for x in land):
            L = np.array(land)
            dv = L[1:, :2] - L[0, :2]
            C2 = dv.T @ dv / (B - 1)
            w_, U = np.linalg.eigh(C2)
            ang = np.linspace(0, 2 * np.pi, 72)
            circ = np.stack([np.cos(ang), np.sin(ang)], 1) * np.sqrt(np.maximum(w_, 0)) * math.sqrt(5.991)
            pts = L[0, :2] + circ @ U.T
            ell = cam.project(np.c_[pts, np.full(len(pts), PH.R_BALL)]).astype(np.float32)
        out[int(t)] = dict(
            uv=m.astype(np.float32), hw=hw.astype(np.float32), ell=ell,
            land_uv=None if land[0] is None else cam.project(land[0]).astype(np.float32),
            p_in=f["ph_p_in"], p_long=f["ph_p_long"], p_net=f["ph_p_net"], p_wide=f["ph_p_wide"],
            x_land=f["ph_x_land"], x_land_sd=f["ph_x_land_sd"], top_rpm=60 * f["ph_top"],
            top_sd_rpm=60 * f["ph_top_sd"], side_rpm=60 * f["ph_side"], side_sd_rpm=60 * f["ph_side_sd"],
            rms_px=f["ph_rms_px"], npts=f["ph_npts"])
    dev_max = None
    if check_json and os.path.exists(check_json):
        J = json.load(open(check_json))
        dp, dr = 0.0, 0.0                    # the JSON rounds P to 3 decimals and rpm to integers
        for r in J["decision_frames"]:
            o = out[r["t"]]
            dp = max(dp, *(abs(o[k] - r[k]) for k in ("p_in", "p_long", "p_net", "p_wide")))
            dr = max(dr, abs(o["top_rpm"] - r["top_rpm"]), abs(o["side_rpm"] - r["side_rpm"]))
        assert len(J["decision_frames"]) == len(out) and dp <= 6e-4 and dr <= 0.51, \
            f"physics re-run does not reproduce {check_json}: dP {dp}, d rpm {dr}"
        dev_max = dict(p=dp, rpm=dr, n=len(out))
    geo = dict(
        table=cam.project(np.c_[tt_camera.CORNERS_W, np.zeros(4)]).astype(np.float32),
        net=cam.project(np.array([[0, -PH.NET_HALF_W, 0], [0, PH.NET_HALF_W, 0], [0, PH.NET_HALF_W, PH.NET_H],
                                  [0, -PH.NET_HALF_W, PH.NET_H]])).astype(np.float32),
        end=cam.project(np.array([[d * PH.HALF_L, -PH.HALF_W, 0], [d * PH.HALF_L, PH.HALF_W, 0]])).astype(np.float32),
        centre=cam.project(np.array([[-PH.HALF_L, 0, 0], [PH.HALF_L, 0, 0]])).astype(np.float32))
    return dict(fits=out, anchor=ainfo, geo=geo, reproduction_max_dev=dev_max)


def prep_tennis():
    """One simulated near-line OUT shot from the nominal population and the spin-aware batch fit
    (bls, model M0) at every frame from 150 ms after contact to the bounce."""
    from src import hawkeye as Hk
    from src.spin import physics as P, tennis_filter as F
    pop = P.build_population("nominal", n=60000, seed=7)
    d, land = pop["d"], pop["land"]
    dl, ds = land[:, 1] - Hk.BASELINE, np.abs(land[:, 0]) - Hk.SIDELINE
    rpm = np.linalg.norm(pop["w0"], axis=1) * 60 / (2 * np.pi)
    # display rule (fixed before looking at any fit): first shot in population order that lands
    # 2-4.5 cm long over the baseline, |x| < 2.5 m, with > 2800 rpm topspin
    cand = np.flatnonzero((d > 0.02) & (d < 0.045) & (dl > ds) & (rpm > 2800) & (np.abs(land[:, 0]) < 2.5))
    i = int(cand[0])
    traj, meas, tl = pop["traj"][i], pop["meas"][i], float(pop["tland"][i])
    st = pop["stimes"]
    kl = int(np.floor(tl * Hk.FPS))
    ks = np.arange(P.W_FIT, kl + 1)
    ks = ks[np.isfinite(meas[ks, 0])]
    M = np.repeat(meas[None], len(ks), 0)
    th0 = F._init_theta(M, np.full(len(ks), 50))
    r = F.bls_fit(M, ks, theta0=th0, max_iter=15)
    ld = F.landing_distribution(r["y"], r["ycov"], r["active"])
    serve = np.zeros(len(ks), bool)
    po = F.p_out(ld["land"], ld["cov"], serve)
    sdd = F.sd_signed_distance(ld["land"], ld["cov"], serve)
    y = r["y"]
    pl, plt, ptraj, _ = P.integrate_truth(y[:, 0:3], y[:, 3:6], y[:, 6:9], y[:, 9], y[:, 10], np.zeros(3))
    _, tl_ns, traj_ns, _ = P.integrate_truth(pop["p0"][i][None], pop["v0"][i][None], np.zeros((1, 3)), 1.0, 0.0,
                                            np.zeros(3))
    lead_ms = (tl - st[ks]) * 1000
    # display call rule (causal): P(OUT) >= 0.95 on PERSIST consecutive frames; the call is the last of them
    PERSIST = 5
    hit = np.array([j for j in range(PERSIST - 1, len(po)) if (po[j - PERSIST + 1:j + 1] >= 0.95).all()], int)
    called = hit
    k_call = int(ks[called[0]]) if len(called) else None
    return dict(
        shot_index=i, pop_n=len(d), traj=traj, stimes=st, tland=tl, land=land[i], d_true=float(d[i]),
        p0=pop["p0"][i], v0=pop["v0"][i], w0=pop["w0"][i], rpm_true=float(rpm[i]),
        ks=ks, lead_ms=lead_ms, land_hat=ld["land"], land_cov=ld["cov"], p_out=po, sd_d=sdd,
        d_hat=ld["land"][:, 1] - Hk.BASELINE, spin_hat=y[:, 6:9],
        pred_traj=ptraj, pred_tland=plt, nospin_traj=traj_ns[0], nospin_land_y=float(np.nanmax(traj_ns[0][:, 1])),
        k_call=k_call, call_lead_ms=None if k_call is None else float((tl - st[k_call]) * 1000),
        call_sd95_cm=None if k_call is None else float(1.96 * sdd[called[0]] * 100),
        call_d_hat_cm=None if k_call is None else float(ld["land"][called[0], 1] - Hk.BASELINE) * 100,
        call_rule=f"P(OUT) >= 0.95 on {PERSIST} consecutive frames ({1000 * PERSIST / Hk.FPS:.0f} ms)")


def prep(force=False):
    if os.path.exists(PREP) and not force:
        return pickle.load(open(PREP, "rb"))
    t = time.time()
    A = json.load(open(os.path.join(ASSETS, "assets.json")))
    cams = json.load(open(os.path.join(REPO, "results", "spin", "tt", "test", "cameras.json")))
    feat = [c for c in A["clips"] if (c["video"], c["f_net"]) == ("test_2", 2819)][0]
    tt = prep_tt(feat, cams, os.path.join(REPO, "results", "spin", "tt", "test", "showcase", "test_2_2819.json"))
    print(f"[prep] table tennis physics re-run: {len(tt['fits'])} decision frames, reproduction max dev "
          f"{tt['reproduction_max_dev']}", flush=True)
    geos = {}
    import tt_camera
    import tt_physics as PH
    for c in A["clips"]:
        cam = tt_camera.Camera.from_dict(cams[c["video"]]["camera"])
        d = c["dir"]
        geos[(c["video"], c["f_net"])] = dict(
            table=cam.project(np.c_[tt_camera.CORNERS_W, np.zeros(4)]).astype(np.float32),
            end=cam.project(np.array([[d * PH.HALF_L, -PH.HALF_W, 0], [d * PH.HALF_L, PH.HALF_W, 0]])).astype(np.float32))
    ten = prep_tennis()
    print(f"[prep] tennis shot {ten['shot_index']}: {ten['d_true']*100:.1f} cm out, {ten['rpm_true']:.0f} rpm, "
          f"OUT called {ten['call_lead_ms']:.0f} ms before the bounce (+-{ten['call_sd95_cm']:.2f} cm 95%)", flush=True)
    P_ = dict(assets=A, tt=tt, geos=geos, tennis=ten)
    pickle.dump(P_, open(PREP, "wb"))
    print(f"[prep] done in {time.time() - t:.0f} s", flush=True)
    return P_


# ===================================================================================== NUMBERS
def load_numbers():
    S = json.load(open(os.path.join(REPO, "results", "tracking", "summary.json")))
    ec = S["early_call"]
    snap50 = ec["precision_recall_test_snapshot"]["50ms"]
    lead = ec["miss_first_call_lead_test_ms"]
    online0 = ec["precision_recall_test_online"]["0ms"]
    R = json.load(open(os.path.join(REPO, "results", "spin", "tt", "test", "report_numbers.json")))
    sp50 = R["snapshot_spin"]["50ms"]
    K = json.load(open(os.path.join(REPO, "results", "spin", "tennis", "key_numbers.json")))
    return dict(
        n_test=S["n_flights"]["test"], tau_online=ec["tau_online"], tau_snapshot=ec["tau_snapshot"],
        snap50_tp=snap50["tp"], snap50_calls=snap50["tp"] + snap50["fp"], snap50_ci=snap50["precision_wilson95"],
        snap50_recall=snap50["recall"], online_calls=online0["tp"] + online0["fp"], online_fp=online0["fp"],
        lead_median=lead["median"], n_miss=lead["n_miss"],
        spin50_tp=sp50["tp"], spin50_calls=sp50["calls"], spin50_prec=sp50["precision"],
        ten_margin95_200=K["bls"]["margin95_cm"]["200"], ten_prec_200=K["bls"]["pout95_precision"]["200"],
        ten_recall_200=K["bls"]["pout95_recall"]["200"], ten_base_margin95_200=K["baseline"]["margin95_cm"]["200"],
        ten_base_margin95_25=K["baseline"]["margin95_cm"]["25"])


# research/v2/latency/RESULTS.md (bottom line, section 5) and research/v2/feed_latency/LATENCY_SWEEP.md
# (bottom line, section 1); typed in here with their source, not computed.
SPEED = dict(
    book_vs_stamp_s=-1.2,          # PM moneyline reprices a median 1.2 s before the official WTA point stamp (n=482)
    book_n_points=482, book_n_matches=9,
    venue_delay_s=1.0,             # Polymarket venue order delay
    inference_s=0.02,              # CV inference, LATENCY_SWEEP section 1
    stamp_lag_s=2.0,               # t_stamp - t_bounce assumed by the revised primary; NOT measured
    breakeven_before_stamp_s=0.9,  # CV call must be >= ~0.9 s before the official stamp
    breakeven_video_delay=(1.09, 1.01),  # IS, burned OOS at stamp lag 2.0 s
)


# ===================================================================================== TABLE TENNIS
class TT:
    def __init__(self, P_, video, f_net, physics=False):
        A = P_["assets"]
        self.c = [c for c in A["clips"] if (c["video"], c["f_net"]) == (video, f_net)][0]
        c = self.c
        self.video, self.f_net, self.label = video, f_net, c["label"]
        self.t0, self.t_ref, self.call = c["t0"], c["t_ref"], c["call_frame"]
        self.lead_ms = c["online_lead_ms"]
        self.dir = c["dir"]
        self.reader = ClipReader(os.path.join(ASSETS, c["file"]), c["first_frame"])
        self.trk = {int(k): v for k, v in c["track"].items()}
        self.score = {int(k): v for k, v in c["score"].items()}
        self.gated = {int(k): v for k, v in c["gated"].items()}
        self.tau = A["tau_online"] if c["label"] == "MISS" else A["tau_snapshot"]
        self.geo = P_["geos"][(video, f_net)]
        self.fits = P_["tt"]["fits"] if physics else {}
        self.fit_ts = sorted(self.fits)
        self.first_dec = min(self.score)
        self.p50 = c["p_miss_at_50ms"]

    def fit_at(self, f):
        best = None
        for t in self.fit_ts:
            if t <= f:
                best = t
            else:
                break
        return best

    # ---------------------------------------------------------------------------- scene graphics
    def draw_table(self, cv, a=1.0, end_hi=0.0):
        T = self.geo["table"]
        cv.poly([tuple(p) for p in T], None, outline=WHITE, oa=0.22 * a, width=1.4)
        e = self.geo["end"]
        if end_hi > 0:
            cv.glow_line(e, (255, 255, 255), 5, 0.55 * end_hi)
            cv.line([tuple(e[0]), tuple(e[1])], WHITE, 3.0, 0.95 * end_hi)
            near = e[0] if e[0][1] > e[1][1] else e[1]          # corner nearer the camera
            off = 1 if self.dir > 0 else -1
            tw = cv.textlen("END LINE", 16, "Semibold", tracking=1.4)
            xa, ya = near[0] + 18 * off, near[1] + 22
            bx = (xa - 8, ya - 14, xa + tw + 8, ya + 14) if off > 0 else (xa - tw - 8, ya - 14, xa + 8, ya + 14)
            cv.rrect(bx, 6, NAVY0, 0.7 * end_hi)
            cv.text((xa, ya), "END LINE", 16, "Semibold", WHITE, 0.95 * end_hi,
                    "lm" if off > 0 else "rm", tracking=1.4)

    def draw_trail(self, cv, f, n=30, col=WHITE, head=True):
        pts = [(t, self.trk[t]) for t in range(f - n, f + 1) if t in self.trk]
        if len(pts) >= 2:
            for j in range(1, len(pts)):
                (ta, pa), (tb, pb) = pts[j - 1], pts[j]
                if tb - ta > 3:
                    continue
                age = (f - tb) / n
                w = 1.0 + 7.0 * (1 - age) ** 1.4
                cv.line([pa, pb], mix(ACCENT, WHITE, 1 - age), w, 0.15 + 0.8 * (1 - age) ** 1.2)
            cv.glow_line([p for _, p in pts[-12:]], (120, 180, 255), 7, 0.55)
        if head and f in self.trk:
            p = self.trk[f]
            cv.glow_dot(p, 9, (140, 190, 255), 0.9)
            cv.circle(p, 14, None, 1, WHITE, 0.95, 2.2)
            cv.circle(p, 3.5, WHITE, 1.0)

    def draw_arc(self, cv, t, col=ACCENT, a=1.0, cone=True, ell=True, ghost=False):
        r = self.fits[t]
        uv, hw = r["uv"], r["hw"]
        if len(uv) < 2:
            return
        if cone and not ghost:
            n_ = np.stack([-np.gradient(uv[:, 1]), np.gradient(uv[:, 0])], 1)
            n_ /= np.maximum(np.linalg.norm(n_, axis=1, keepdims=True), 1e-9)
            h = np.minimum(hw, 160.0)[:, None]
            left, right = uv + n_ * h, uv - n_ * h
            cv.poly([tuple(p) for p in np.vstack([left, right[::-1]])], col, 0.16 * a, outline=None)
            cv.line([tuple(p) for p in left], col, 1.0, 0.45 * a)
            cv.line([tuple(p) for p in right], col, 1.0, 0.45 * a)
        if ghost:
            cv.line([tuple(p) for p in uv], WHITE, 1.4, a)
            return
        cv.glow_line(uv, col, 6, 0.6 * a)
        # dashed bright centre line
        L = np.r_[0, np.cumsum(np.linalg.norm(np.diff(uv, axis=0), axis=1))]
        dash, gap = 16.0, 9.0
        s = 0.0
        while s < L[-1]:
            e = min(s + dash, L[-1])
            seg = np.array([np.interp(x, L, uv[:, 0]) for x in np.linspace(s, e, 5)]), \
                np.array([np.interp(x, L, uv[:, 1]) for x in np.linspace(s, e, 5)])
            cv.line(list(zip(*seg)), col, 3.2, a)
            s = e + gap
        if ell and r["ell"] is not None:
            outside = (r["x_land"] > 0) if np.isfinite(r["x_land"]) else False
            ec = CORAL if outside else ACCENT
            cv.poly([tuple(p) for p in r["ell"]], ec, 0.18 * a, outline=ec, oa=0.95 * a, width=2.0)
            lu = r["land_uv"]
            cv.line([(lu[0] - 7, lu[1]), (lu[0] + 7, lu[1])], WHITE, 1.6, a)
            cv.line([(lu[0], lu[1] - 7), (lu[0], lu[1] + 7)], WHITE, 1.6, a)
            if np.isfinite(r["x_land"]):
                tag = (f"LONG +{r['x_land']*100:.0f} cm" if r["x_land"] > 0 else f"IN {signed(r['x_land']*100)} cm")
                sd = f"±{1.96*r['x_land_sd']*100:.0f} cm (95%)" if np.isfinite(r["x_land_sd"]) else ""
                tw = max(cv.textlen(tag, 21, "Semibold"), cv.textlen(sd, 17, "Regular")) + 26
                x = min(lu[0] + 26, W - 24 - tw)
                y = lu[1] - 76
                cv.rrect((x, y, x + tw, y + 60), 7, NAVY0, 0.86 * a)
                cv.rect((x, y, x + 3, y + 60), ec, a)
                cv.text((x + 14, y + 19), tag, 21, "Semibold", WHITE, a, "lm")
                cv.text((x + 14, y + 44), sd, 17, "Regular", (200, 210, 230), a, "lm")
                cv.line([(x + 8, y + 60), (lu[0] + 6, lu[1] - 6)], WHITE, 1.0, 0.6 * a)

    # ---------------------------------------------------------------------------------- HUD band
    def hud(self, cv, f, a=1.0, physics=True, phase=0.0):
        """Bottom band. Type floor: 15 px for caps headers, 16 px for everything else (projector)."""
        y0, y1 = HUD_Y0, HUD_Y1
        cv.rrect((40, y0, W - 40, y1), 14, NAVY0, 0.84 * a, outline=WHITE, oa=0.10 * a)
        called = self.call is not None and f >= self.call
        done = f >= self.t_ref
        is_miss = self.label == "MISS"
        dec = self.t_ref - 6                       # snapshot decision frame (50 ms before the bounce)
        HDR = (176, 188, 214)
        # M1: call status + frozen P(MISS)
        x = 64
        cv.text((x, y0 + 24), "CALL · FROZEN TIER-0 MODEL", 15, "Semibold", HDR, a, "lm", tracking=1.3)
        if is_miss and called:
            st, fill = "MISS CALLED", CORAL
        elif not is_miss and f >= dec:
            st, fill = ("TABLE BOUNCE · IN" if done else "NO CALL"), None
        else:
            st, fill = "TRACKING", None
        sw = cv.textlen(st, 24, "Bold", tracking=1.0) + 30
        if fill:
            cv.rrect((x, y0 + 42, x + sw, y0 + 82), 8, fill, a)
        else:
            cv.rrect((x, y0 + 42, x + sw, y0 + 82), 8, None, outline=WHITE, oa=0.7 * a, width=1.6)
        cv.text((x + 15, y0 + 62), st, 24, "Bold", WHITE, a, "lm", tracking=1.0)
        sc = None
        known = [t for t in self.score if t <= f]
        if known:
            tl = max(known)
            sc = None if self.gated.get(tl, False) else self.score[tl]
        yb = y0 + 110
        cv.text((x, yb), "P(MISS)", 16, "Semibold", WHITE, a, "lm", tracking=0.8)
        bx, bw = x + 84, 210
        if sc is None:
            bar(cv, bx, yb - 4, bw, 8, None, CORAL, tick=self.tau)
            txt = "no score (gated)" if known else "waiting"
            cv.text((bx + bw + 14, yb), txt, 16, "Regular", MUTED, a, "lm")
        else:
            bar(cv, bx, yb - 4, bw, 8, sc, CORAL if sc >= self.tau else WHITE, tick=self.tau)
            cv.text((bx + bw + 14, yb), f"{sc:.3f}", 19, "Semibold", WHITE, a, "lm", mono=True)
        cv.text((bx + bw * self.tau, yb + 24), f"τ {self.tau:.2f}", 15, "Regular", MUTED, a, "mm")
        # divider
        cv.rect((COL2 - 24, y0 + 16, COL2 - 23, y1 - 16), WHITE, 0.12 * a)
        if physics and self.fit_ts:
            tf = self.fit_at(min(f, self.t_ref))
            r = self.fits.get(tf) if tf is not None else None
            # M2: P(in/long/net/wide)
            x = COL2
            cv.text((x, y0 + 24), "PHYSICS FIT · DISPLAY ONLY", 15, "Semibold", HDR, a, "lm", tracking=1.3)
            rows = [("IN", "p_in", ACCENT), ("LONG", "p_long", CORAL), ("NET", "p_net", CORAL), ("WIDE", "p_wide", CORAL)]
            for j, (nm, key, col) in enumerate(rows):
                yy = y0 + 54 + j * 24
                v = None if r is None else r[key]
                cv.text((x, yy), nm, 15, "Semibold", WHITE, a, "lm", tracking=0.8)
                bar(cv, x + 62, yy - 4, 220, 8, v, col)
                cv.text((x + 352, yy), "—" if v is None else f"{100*v:.0f}%", 17, "Medium", WHITE, a, "rm", mono=True)
            cv.rect((COL3 - 24, y0 + 16, COL3 - 23, y1 - 16), WHITE, 0.12 * a)
            # M3: spin
            x = COL3
            cv.text((x, y0 + 24), "SPIN · PHYSICS FIT ±1σ", 15, "Semibold", HDR, a, "lm", tracking=1.3)
            if r is not None:
                spin_glyph(cv, (x + 36, y0 + 84), 24, r["top_rpm"], r["side_rpm"], self.dir, phase, a)
                kind = "TOPSPIN" if r["top_rpm"] >= 0 else "BACKSPIN"
                cv.text((x + 92, y0 + 56), kind, 15, "Semibold", HDR, a, "lm", tracking=1.2)
                big = signed(r["top_rpm"], "+,.0f")
                cv.text((x + 92, y0 + 86), big, 28, "Semibold", WHITE, a, "lm", mono=True)
                cv.text((x + 92 + cv.textlen(big, 28, "Semibold", mono=True) + 8, y0 + 89),
                        f"rpm ±{r['top_sd_rpm']:,.0f}", 17, "Regular", MUTED, a, "lm")
                cv.text((x + 92, y0 + 120), f"sidespin {signed(r['side_rpm'], '+,.0f')} rpm ±{r['side_sd_rpm']:,.0f}", 17,
                        "Regular", WHITE, a, "lm")
            else:
                cv.text((x + 4, y0 + 80), "fitting…", 20, "Regular", MUTED, a, "lm")
        else:
            x = COL2
            cv.text((x, y0 + 24), "FLIGHT", 15, "Semibold", HDR, a, "lm", tracking=1.3)
            res = ("ball goes out, no table bounce" if is_miss else "ball lands on the far half")
            cv.text((x, y0 + 62), f"{self.video} · flight {self.f_net}", 26, "Semibold", WHITE, a, "lm")
            cv.text((x, y0 + 98), (f"outcome (label): {res}" if done else "outcome: not yet known"), 18,
                    "Regular", MUTED if not done else WHITE, a, "lm")
            if not is_miss and self.p50 is not None and f >= dec:
                cv.text((x, y0 + 124), f"P(MISS) 50 ms before the bounce: {self.p50:.2f}, below τ {self.tau:.2f}: no call",
                        17, "Regular", MUTED, a, "lm")
        xd = COL4 - 24
        cv.rect((xd, y0 + 16, xd + 1, y1 - 16), WHITE, 0.12 * a)
        # M4: time to contact / result
        x = COL4
        if not done:
            ms = (self.t_ref - f) / SRC_FPS * 1000
            cv.text((x, y0 + 24), "TIME TO CONTACT", 15, "Semibold", HDR, a, "lm", tracking=1.3)
            cv.text((x, y0 + 72), f"{ms:4.0f}", 50, "Semibold", WHITE, a, "lm", mono=True)
            cv.text((x + cv.textlen(f"{ms:4.0f}", 50, "Semibold", mono=True) + 10, y0 + 80), "ms", 20, "Medium",
                    MUTED, a, "lm")
            cv.text((x, y0 + 120), "contact = ball reaches the table end" if is_miss else "contact = table bounce",
                    17, "Regular", MUTED, a, "lm")
        else:
            cv.text((x, y0 + 24), "RESULT (LABEL)", 15, "Semibold", HDR, a, "lm", tracking=1.3)
            res = "OUT" if is_miss else "IN"
            col = CORAL if is_miss else ACCENT
            cv.rrect((x, y0 + 46, x + 104, y0 + 96), 8, col, a)
            cv.text((x + 52, y0 + 71), res, 28, "Bold", WHITE, a, "mm", tracking=1.0)
            if is_miss and self.lead_ms is not None:
                cv.text((x + 122, y0 + 58), "call was right", 20, "Semibold", WHITE, a, "lm")
                cv.text((x + 122, y0 + 86), f"made {self.lead_ms:.0f} ms early", 18, "Regular", MUTED, a, "lm")
            elif not is_miss:
                cv.text((x + 122, y0 + 58), "no call made", 20, "Semibold", WHITE, a, "lm")
                cv.text((x + 122, y0 + 86), "correct pass", 18, "Regular", MUTED, a, "lm")

    def clock(self, cv, f, a=1.0, notes=True):
        s = f"{self.video}  ·  frame {f}  ·  120 fps source"
        tw = cv.textlen(s, 17, "Medium", mono=True)
        cv.rrect((W - 40 - tw - 30, 30, W - 40, 68), 9, NAVY0, 0.80 * a)
        cv.text((W - 55, 49), s, 17, "Medium", WHITE, 0.95 * a, "rm", mono=True)
        l1 = ("Calls: frozen tier-0 model (online rule: P(MISS) ≥ τ on 3 frames)." if self.label == "MISS" else
              "Frozen tier-0 model, snapshot rule: call MISS if P(MISS) ≥ τ 50 ms before the bounce.")
        l2 = ("Arc, cone, P(in/long/net/wide), spin: physics fit, display only. "
              "The spin-aware model failed its test and makes no call.")
        lines = [l1, l2] if notes else [l1]
        tw = max(cv.textlen(x, 17, "Regular") for x in lines)
        cv.rrect((W - 40 - tw - 30, 76, W - 40, 88 + 24 * len(lines)), 9, NAVY0, 0.80 * a)
        for j, x in enumerate(lines):
            cv.text((W - 55, 99 + 24 * j), x, 17, "Regular", (226, 233, 247), a, "rm")


# ----------------------------------------------------------------------- landing chart (slow-mo)
def landing_chart(cv, tt, f, box=(1360, 148, 1880, 384), a=1.0):
    x0, y0, x1, y1 = box
    cv.rrect((x0, y0, x1, y1), 12, NAVY0, 0.92 * a, outline=WHITE, oa=0.1 * a)
    cv.text((x0 + 20, y0 + 26), "PREDICTED CROSSING PAST THE END LINE", 15, "Semibold", (176, 188, 214), a, "lm",
            tracking=1.2)
    cv.text((x0 + 20, y0 + 50), "physics fit at each decision frame · 95% band · display only", 16, "Regular", MUTED,
            a, "lm")
    px0, px1, py0, py1 = x0 + 70, x1 - 22, y0 + 88, y1 - 40
    ymin, ymax = -0.2, 1.4
    lead0 = (tt.t_ref - tt.fit_ts[0]) / SRC_FPS * 1000

    def X(t):
        lead = (tt.t_ref - t) / SRC_FPS * 1000
        return px0 + (px1 - px0) * (1 - lead / lead0)

    def Y(v):
        return py1 - (py1 - py0) * (min(max(v, ymin), ymax) - ymin) / (ymax - ymin)

    for v in (0.0, 0.5, 1.0):
        cv.rect((px0, Y(v), px1, Y(v) + 1), WHITE, (0.35 if v == 0 else 0.08) * a)
        cv.text((px0 - 10, Y(v)), f"{v:+.1f} m" if v else "0", 15, "Regular", MUTED, a, "rm")
    cv.text((px1, Y(0.0) + 14), "END LINE", 15, "Semibold", WHITE, 0.75 * a, "rm", tracking=1.2)
    for lead in (500, 400, 300, 200, 100, 0):
        xx = px0 + (px1 - px0) * (1 - lead / lead0)
        cv.text((xx, py1 + 22), f"−{lead}" if lead else "0 ms", 15, "Regular", MUTED, a, "mm")
    ts = [t for t in tt.fit_ts if t <= f and np.isfinite(tt.fits[t]["x_land"])]
    clipped = False
    if len(ts) >= 2:
        up = [(X(t), Y(tt.fits[t]["x_land"] + 1.96 * tt.fits[t]["x_land_sd"])) for t in ts]
        lo = [(X(t), Y(tt.fits[t]["x_land"] - 1.96 * tt.fits[t]["x_land_sd"])) for t in ts]
        clipped = any(tt.fits[t]["x_land"] + 1.96 * tt.fits[t]["x_land_sd"] > ymax for t in ts)
        cv.poly(up + lo[::-1], CORAL, 0.20 * a)
        cv.line([(X(t), Y(tt.fits[t]["x_land"])) for t in ts], CORAL, 2.4, a)
        xe, ye = X(ts[-1]), Y(tt.fits[ts[-1]]["x_land"])
        cv.circle((xe, ye), 4.5, WHITE, a)
        r = tt.fits[ts[-1]]
        v, h = r["x_land"], 1.96 * r["x_land_sd"]
        lab = (f"{signed(v, '+.1f')} ± {h:.1f} m" if max(abs(v), h) >= 1.0 else
               f"{signed(v * 100)} ± {h * 100:.0f} cm")
        if v > ymax:
            lab += " (off scale)"
        tw_ = cv.textlen(lab, 17, "Semibold")
        # beside the dot, never on it: left of it when there is room, else right; below it when it is pinned
        # to the top of the plot
        ly = ye + 20 if ye - 16 < py0 + 10 else ye - 16
        if xe - 12 - tw_ >= px0:
            cv.rrect((xe - 12 - tw_ - 6, ly - 12, xe - 8, ly + 12), 5, NAVY0, 0.85 * a)
            cv.text((xe - 12, ly), lab, 17, "Semibold", WHITE, a, "rm")
        else:
            cv.rrect((xe + 8, ly - 12, xe + 12 + tw_ + 6, ly + 12), 5, NAVY0, 0.85 * a)
            cv.text((xe + 12, ly), lab, 17, "Semibold", WHITE, a, "lm")
        cv.circle((xe, ye), 4.5, WHITE, a)
    if clipped:
        cv.text((px0 + 4, py0 - 14), "▲ band above +1.4 m clipped", 15, "Regular", MUTED, a, "lm")
    if tt.call is not None and f >= tt.call:
        xc = X(tt.call)
        cv.rect((xc, py0, xc + 1.5, py1), CORAL, 0.9 * a)
        cv.text((xc + 6, py1 - 12), "CALL", 15, "Semibold", CORAL, a, "lm", tracking=1.2)


# ===================================================================================== SEGMENTS
class Seg:
    def __init__(self, name, n, fn, fade_in=8, fade_out=8, label=None):
        self.name, self.n, self.fn, self.fi, self.fo, self.label = name, n, fn, fade_in, fade_out, label

    def frame(self, i):
        img = self.fn(i)
        k = 1.0
        if self.fi and i < self.fi:
            k = ease((i + 1) / (self.fi + 1))
        if self.fo and i >= self.n - self.fo:
            k = min(k, ease((self.n - i) / (self.fo + 1)))
        if k < 1.0:
            nav = np.array(NAVY0, np.float32)
            img = (img.astype(np.float32) * k + nav * (1 - k)).astype(np.uint8)
        return img


def navy_bg(t=0.0):
    """Deep navy radial gradient with a faint moving grid (1x array)."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((x - W * 0.62) / W) ** 2 + ((y - H * 0.35) / H) ** 2)
    k = np.clip(1.0 - r * 1.25, 0, 1)[..., None]
    img = np.array(NAVY0, np.float32) * (1 - k) + np.array(NAVY2, np.float32) * k
    return img.astype(np.uint8)


_BG = None


def bg():
    global _BG
    if _BG is None:
        _BG = navy_bg()
    return _BG.copy()


def grid(cv, t, a=1.0, step=80):
    off = (t * 12) % step
    for xx in np.arange(-step, W + step, step):
        cv.rect((xx + off, 0, xx + off + 1, H), WHITE, 0.025 * a)
    for yy in np.arange(-step, H + step, step):
        cv.rect((0, yy + off * 0.5, W, yy + off * 0.5 + 1), WHITE, 0.025 * a)


def slate(num, title, sub, label, n=48):
    def fn(i):
        cv = Canvas(bg())
        t = i / FPS
        grid(cv, t)
        e = ease_out(i / 14)
        dy = 70
        cv.text((160, 470 + dy), num, 120, "Light", ACCENT, e, "ls")
        x = 160 + cv.textlen(num, 120, "Light") + 36
        cv.rect((x - 18, 380 + dy, x - 16, 470 + dy), WHITE, 0.25 * e)
        cv.text((x + 30 * (1 - e), 422 + dy), title, 54, "Bold", WHITE, e, "ls", tracking=1.0)
        cv.text((x + 30 * (1 - e), 462 + dy), sub, 22, "Regular", MUTED, e, "ls")
        tw = cv.textlen(label, 21, "Medium")
        cv.rrect((x, 496 + dy, x + tw + 32, 538 + dy), 9, NAVY0, 0.8 * e, outline=ACCENT, oa=0.6 * e)
        cv.text((x + 16, 517 + dy), label, 21, "Medium", WHITE, e, "lm")
        return cv.finish()
    return Seg("slate:" + title, n, fn, 6, 6)


def title_card(N, n=120):
    def fn(i):
        cv = Canvas(bg())
        t = i / FPS
        grid(cv, t)
        # stylised flight arc sweeping across
        xs = np.linspace(1000, 1840, 160)
        ys = 900 - 560 * np.sin(np.pi * (xs - 1000) / 900) ** 1.1
        k = int(len(xs) * ease(i / 45))
        if k > 2:
            pts = list(zip(xs[:k], ys[:k]))
            cv.glow_line(pts, ACCENT, 5, 0.6)
            cv.line(pts, ACCENT, 2.4, 0.9)
            cv.circle(pts[-1], 7, WHITE, 1.0)
        # everything is fully in by ~1.6 s, leaving ~2.1 s to read before the fade
        e1, e2, e3 = ease_out((i - 4) / 14), ease_out((i - 12) / 14), ease_out((i - 20) / 14)
        cv.rect((160, 336, 172, 348), ACCENT, e1)
        cv.text((186, 342), "COURTSIDE", 24, "Semibold", WHITE, e1, "lm", tracking=4.0)
        cv.text((160 + 40 * (1 - e1), 456), "Calling the ball", 92, "Bold", WHITE, e1, "ls")
        cv.text((160 + 40 * (1 - e2), 556), "before it lands.", 92, "Bold", WHITE, e2, "ls")
        cv.text((160, 618), "Computer-vision early calls: table tennis on real match footage,", 28, "Regular",
                (176, 188, 214), e3, "ls")
        cv.text((160, 656), "tennis in a simulated Hawk-Eye-class camera model.", 28, "Regular", (176, 188, 214), e3, "ls")
        for j, (lab, col) in enumerate(((LBL_REAL, ACCENT), (LBL_SIM, MUTED))):
            ee = ease_out((i - 30 - 5 * j) / 14)
            y = 750 + 52 * j
            tw = cv.textlen(lab, 21, "Medium")
            cv.rrect((160, y, 160 + tw + 32, y + 40), 9, NAVY0, 0.85 * ee, outline=col, oa=0.7 * ee)
            cv.text((176, y + 20), lab, 21, "Medium", WHITE, ee, "lm")
        return cv.finish()
    return Seg("title", n, fn, 0, 8)


def end_card(N, n=240):
    def fn(i):
        cv = Canvas(bg())
        grid(cv, i / FPS)
        e = [ease_out((i - 5 * j) / 14) for j in range(8)]
        cv.text((160, 220), "What the reel shows", 52, "Bold", WHITE, e[0], "ls")
        lines = [
            (f"Table tennis, real footage: {N['snap50_tp']}/{N['snap50_calls']} MISS calls correct at 50 ms on held-out "
             f"games (precision 95% CI {N['snap50_ci'][0]:.2f}–{N['snap50_ci'][1]:.2f}; recall "
             f"{100*N['snap50_recall']:.0f}%)."),
            (f"Online rule: {N['online_calls']} of {N['n_miss']} test misses called, {N['online_fp']} false calls, "
             f"median lead {N['lead_median']:.0f} ms, best 408 ms."),
            (f"Spin-aware table-tennis model: {N['spin50_tp']}/{N['spin50_calls']} at 50 ms on test. It did not pass; "
             f"its physics fit is shown for display only."),
            (f"Tennis (simulation): ±{N['ten_margin95_200']:.2f} cm (95%) at 200 ms before the bounce, vs "
             f"±{N['ten_base_margin95_200']:.1f} cm for the current Hawk-Eye-class predictor."),
            "The edge needs the call inside the venue's 1 s order delay; the stamp lag is not yet measured.",
        ]
        for j, s in enumerate(lines):
            y = 300 + 62 * j
            cv.rect((160, y - 10, 166, y + 10), ACCENT if j != 2 else CORAL, e[j + 1])
            cv.text((186, y), s, 26, "Regular", WHITE, e[j + 1], "lm")
        # credits: the three honesty labels verbatim, bottom left like every other segment's label
        cr = [
            f"Table tennis: {LBL_REAL}. Ball detector: BlurBall (MIT).",
            f"Tennis: {LBL_SIM}.",
            f"Speed card: {LBL_MKT}.",
        ]
        tw = max(cv.textlen(s, 20, "Regular") for s in cr)
        cv.rrect((140, 846, 140 + tw + 44, 1004), 12, NAVY0, 0.8 * e[6], outline=WHITE, oa=0.10 * e[6])
        cv.text((162, 876), "SOURCES AND LABELS", 15, "Semibold", (176, 188, 214), e[6], "lm", tracking=1.4)
        for j, s in enumerate(cr):
            cv.text((162, 912 + 32 * j), s, 20, "Regular", (220, 228, 244), e[6], "lm")
        return cv.finish()
    return Seg("end", n, fn, 8, 0)


# ------------------------------------------------------------------------- segment 1: real time
def seg_featured(tt, N, mode_slow=False):
    """Featured call in real time: run in, freeze on the call frame, run on to contact, hold."""
    call = tt.call
    pre = 42
    plan = [(call - 4 * (pre - j), "rt") for j in range(pre)]
    plan += [(call, "freeze")] * 84
    plan += [(call + 4 * j, "rt") for j in range(1, 20)]
    plan += [(call + 4 * 19, "hold")] * 36
    return _tt_seg("featured", tt, plan, N, physics=True)


def seg_quick(tt, N):
    plan = [(tt.call - 4 * (20 - j), "rt") for j in range(20)]
    plan += [(tt.call, "freeze")] * 60
    plan += [(tt.call + 4 * j, "rt") for j in range(1, 11)]
    plan += [(tt.call + 40, "hold")] * 30
    return _tt_seg(f"quick:{tt.video}_{tt.f_net}", tt, plan, N, physics=False)


def seg_bounce(tt, N):
    dec = tt.t_ref - 6                     # snapshot decision frame, 50 ms before the bounce
    plan = [(dec - 4 * (24 - j), "rt") for j in range(24)]
    plan += [(dec, "freeze")] * 60
    plan += [(dec + 4 * j, "rt") for j in range(1, 11)]
    plan += [(dec + 40, "hold")] * 30
    return _tt_seg(f"bounce:{tt.video}_{tt.f_net}", tt, plan, N, physics=False)


def seg_slowmo(tt, N):
    plan = [(f, "slow") for f in range(tt.t0 - 40, tt.call)]
    plan += [(tt.call, "freeze")] * 45
    plan += [(f, "slow") for f in range(tt.call, tt.t_ref + 22)]
    plan += [(tt.t_ref + 21, "hold")] * 30
    return _tt_seg("slowmo", tt, plan, N, physics=True, slow=True)


def _tt_seg(name, tt, plan, N, physics, slow=False):
    # index of the first freeze frame, to time the call animation
    first_freeze = next((j for j, (_, m) in enumerate(plan) if m == "freeze"), None)

    def fn(i):
        f, mode = plan[i]
        img = grade(tt.reader.get(f), dim=0.9 if mode in ("freeze", "hold") else 1.0)
        cv = Canvas(img)
        is_miss = tt.label == "MISS"
        called = tt.call is not None and f >= tt.call
        tf = tt.fit_at(min(f, tt.t_ref)) if physics else None
        end_hi = 0.0
        if physics and tf is not None:
            r = tt.fits[tf]
            end_hi = 1.0 if (np.isfinite(r["x_land"])) else 0.4
        tt.draw_table(cv, 1.0, end_hi if physics else (0.8 if f >= tt.t_ref - 30 else 0.0))
        if physics and tf is not None and f <= tt.t_ref + 2:
            if slow:
                ghosts = [t for t in tt.fit_ts if t < tf][-14::2]
                for j, gt in enumerate(ghosts):
                    tt.draw_arc(cv, gt, a=0.08 + 0.22 * j / max(len(ghosts), 1), ghost=True)
            tt.draw_arc(cv, tf, CORAL if called else ACCENT, 1.0)
        tt.draw_trail(cv, f, n=36 if slow else 30)
        # call pulse
        if first_freeze is not None and mode == "freeze" and called and f in tt.trk:
            k = i - first_freeze
            for rr in (0, 10):
                t_ = ((k + rr) % 30) / 30
                cv.circle(tt.trk[f], 16 + 70 * ease_out(t_), None, 1, CORAL, 0.9 * (1 - t_), 3.0)
        # HUD
        tt.hud(cv, f, 1.0, physics=physics, phase=(i * 9) % 360)
        tt.clock(cv, f, 1.0, notes=physics)
        if slow:
            landing_chart(cv, tt, min(f, tt.t_ref))
        # callout
        if is_miss and called and first_freeze is not None:
            k = i - first_freeze
            text = f"MISS CALLED · {tt.lead_ms:.0f} ms BEFORE CONTACT"
            sub = (f"frozen tier-0 model · P(MISS) ≥ {tt.tau:.2f} on 3 frames · "
                   "contact = ball reaches the table end")
            callout(cv, 700, text, sub, t=min(1.0, k / 12) if k >= 0 else 1.0, align="l" if tt.dir > 0 else "r")
        elif not is_miss and f >= tt.t_ref - 6 and first_freeze is not None:
            k = i - first_freeze
            text = f"NO MISS CALL · P(MISS) {tt.p50:.2f}" if f < tt.t_ref else "TABLE BOUNCE · IN"
            sub = f"frozen tier-0 model · snapshot 50 ms before the bounce · a MISS call needs P(MISS) ≥ {tt.tau:.2f}"
            callout(cv, 700, text, sub, t=min(1.0, k / 12), col=ACCENT, align="l" if tt.dir > 0 else "r")
        mode_txt = {"rt": "REAL TIME", "freeze": "FREEZE · CALL FRAME" if is_miss else "FREEZE · DECISION FRAME",
                    "hold": "REAL TIME", "slow": "¼× SLOW MOTION"}[mode]
        if slow and mode in ("freeze", "hold"):
            mode_txt = "¼× SLOW MOTION · " + ("FREEZE" if mode == "freeze" else "HOLD")
        sec = "02  ¼× REPLAY · ARC LOCKS IN" if slow else "01  REAL MATCH FOOTAGE · EARLY CALL"
        chrome(cv, sec, LBL_REAL, mode_txt, CORAL if mode == "freeze" else ACCENT)
        return cv.finish()
    return Seg(name, len(plan), fn, 6, 6)


def seg_stats(last_img_fn, N, n=195):
    import cv2
    cache = {}

    def fn(i):
        if "bg" not in cache:
            b = last_img_fn()
            b = cv2.GaussianBlur(b, (0, 0), 18)
            cache["bg"] = (b.astype(np.float32) * 0.35 + np.array(NAVY0, np.float32) * 0.65).astype(np.uint8)
        cv = Canvas(cache["bg"].copy())
        e = [ease_out((i - 5 * j) / 16) for j in range(6)]
        cv.text((160, 214), "HELD-OUT TEST GAMES  ·  test_1–7", 18, "Semibold", (176, 188, 214), e[0], "ls", tracking=2.0)
        nt = N["n_test"]
        cv.text((160, 252), f"{nt['BOUNCE'] + nt['MISS']} flights: {nt['BOUNCE']} table bounces, {nt['MISS']} misses."
                " Models and τ fixed on game_1–5; each model scored once on test.", 22, "Regular", WHITE, e[0], "ls")
        # big stat
        cv.text((160, 470), f"{N['snap50_tp']}/{N['snap50_calls']}", 190, "Bold", WHITE, e[1], "ls")
        cv.text((700, 368), "MISS calls correct", 40, "Semibold", WHITE, e[1], "ls")
        cv.text((700, 414), "at a 50 ms lead (snapshot rule)", 28, "Regular", MUTED, e[1], "ls")
        cv.text((700, 462), f"precision 95% CI {N['snap50_ci'][0]:.2f}–{N['snap50_ci'][1]:.2f}  ·  recall "
                f"{100*N['snap50_recall']:.0f}% of misses", 24, "Regular", MUTED, e[1], "ls")
        cols = [
            ("ONLINE RULE", f"{N['online_calls']} of {N['n_miss']}", f"misses called, {N['online_fp']} wrong · "
             f"median lead {N['lead_median']:.0f} ms, best 408 ms", ACCENT),
            ("SPIN-AWARE MODEL", f"{N['spin50_tp']}/{N['spin50_calls']}",
             f"calls correct at 50 ms on test (precision {N['spin50_prec']:.2f}): below the 0.95 bar, so it makes "
             "no call here", CORAL),
        ]
        for j, (h, big, s, col) in enumerate(cols):
            x = 160 + 820 * j
            ee = e[2 + j]
            cv.rect((x, 560, x + 4, 764), col, ee)
            cv.text((x + 24, 584), h, 17, "Semibold", (176, 188, 214), ee, "ls", tracking=1.8)
            cv.text((x + 24, 652), big, 58, "Bold", WHITE, ee, "ls")
            for k_, part in enumerate(_wrap(cv, s, 22, 680)):
                cv.text((x + 24, 692 + 30 * k_), part, 22, "Regular", (190, 202, 226), ee, "ls")
        chrome(cv, "01  REAL MATCH FOOTAGE · TEST RESULTS", LBL_REAL, "RESULTS", ACCENT, e[0])
        return cv.finish()
    return Seg("stats", n, fn, 8, 8)


def _wrap(cv, s, size, width, weight="Regular"):
    out, cur = [], ""
    for wd in s.split():
        t = (cur + " " + wd).strip()
        if cv.textlen(t, size, weight) > width and cur:
            out.append(cur)
            cur = wd
        else:
            cur = t
    if cur:
        out.append(cur)
    return out


# ===================================================================================== TENNIS 3D
class Cam3:
    CX = 0.43 * W          # principal point left of centre: the right column holds the readouts

    def __init__(self, C, T, fov):
        C, T = np.asarray(C, float), np.asarray(T, float)
        fw = T - C
        fw /= np.linalg.norm(fw)
        rt = np.cross(fw, [0, 0, 1.0])
        rt /= np.linalg.norm(rt)
        up = np.cross(rt, fw)
        self.R = np.stack([rt, -up, fw])
        self.C = C
        self.f = (W / 2) / math.tan(math.radians(fov) / 2)

    def cam(self, X):
        return (np.asarray(X, float) - self.C) @ self.R.T

    def proj_c(self, Xc):
        z = np.maximum(Xc[..., 2], 1e-6)
        return np.stack([self.f * Xc[..., 0] / z + self.CX, self.f * Xc[..., 1] / z + H / 2], -1)

    def project(self, X):
        Xc = self.cam(X)
        return self.proj_c(Xc), Xc[..., 2]

    def poly(self, X, near=0.15):
        """Near-plane clipped polygon -> pixel points."""
        P = self.cam(X)
        out = []
        n = len(P)
        for j in range(n):
            a, b = P[j], P[(j + 1) % n]
            ina, inb = a[2] >= near, b[2] >= near
            if ina:
                out.append(a)
            if ina != inb:
                t = (near - a[2]) / (b[2] - a[2])
                out.append(a + t * (b - a))
        if len(out) < 3:
            return []
        return [tuple(p) for p in self.proj_c(np.array(out))]

    def seg(self, a, b, near=0.15, n=1):
        """Clipped (and optionally subdivided) segment -> pixel polyline."""
        pts = np.linspace(a, b, n + 1)
        Pc = self.cam(pts)
        keep = Pc[:, 2] >= near
        if keep.sum() < 2:
            if keep.sum() == 0:
                return []
        out = []
        for j in range(len(Pc) - 1):
            p, q = Pc[j], Pc[j + 1]
            if p[2] < near and q[2] < near:
                continue
            if p[2] < near:
                p = p + (near - p[2]) / (q[2] - p[2]) * (q - p)
            if q[2] < near:
                q = p + (near - p[2]) / (q[2] - p[2]) * (q - p)
            if not out:
                out.append(p)
            out.append(q)
        return [tuple(x) for x in self.proj_c(np.array(out))] if len(out) >= 2 else []


BL, SL, DL, NY, NHc, NHp, SV = 23.77, 4.115, 5.485, 11.885, 0.914, 1.07, 6.40
COURT_LINES = [
    ((-DL, 0), (DL, 0)), ((-DL, BL), (DL, BL)), ((-DL, 0), (-DL, BL)), ((DL, 0), (DL, BL)),
    ((-SL, 0), (-SL, BL)), ((SL, 0), (SL, BL)), ((-SL, NY - SV), (SL, NY - SV)), ((-SL, NY + SV), (SL, NY + SV)),
    ((0, NY - SV), (0, NY + SV)), ((0, 0), (0, 0.10)), ((0, BL - 0.10), (0, BL)),
]


def cam_path(t, kf):
    """Piecewise smoothstep between keyframes [(t, C, T, fov), ...]."""
    if t <= kf[0][0]:
        return Cam3(*kf[0][1:])
    for (ta, Ca, Ta, fa), (tb, Cb, Tb, fb) in zip(kf[:-1], kf[1:]):
        if t <= tb:
            u = ease((t - ta) / (tb - ta))
            return Cam3(np.array(Ca) + u * (np.array(Cb) - np.array(Ca)),
                        np.array(Ta) + u * (np.array(Tb) - np.array(Ta)), fa + u * (fb - fa))
    return Cam3(*kf[-1][1:])


def draw_court(cv, cam):
    cv.poly(cam.poly(np.array([[-14, -9, 0], [14, -9, 0], [14, 33, 0], [-14, 33, 0]])), (12, 30, 66), 1.0)
    cv.poly(cam.poly(np.array([[-DL, 0, 0], [DL, 0, 0], [DL, BL, 0], [-DL, BL, 0]])), (24, 62, 128), 1.0)
    # faint ground grid
    for xx in np.arange(-14, 14.1, 2.0):
        cv.line(cam.seg(np.array([xx, -9, 0]), np.array([xx, 33, 0]), n=8), WHITE, 1.0, 0.035)
    for yy in np.arange(-8, 33, 2.0):
        cv.line(cam.seg(np.array([-14, yy, 0]), np.array([14, yy, 0]), n=8), WHITE, 1.0, 0.035)
    for (a, b) in COURT_LINES:
        pts = cam.seg(np.array([a[0], a[1], 0.0]), np.array([b[0], b[1], 0.0]), n=12)
        cv.line(pts, WHITE, 2.2, 0.92)
    # net
    xs = np.linspace(-6.4, 6.4, 33)
    top = np.stack([xs, np.full_like(xs, NY), NHc + (NHp - NHc) * (np.abs(xs) / 6.4) ** 2], 1)
    poly = np.vstack([np.stack([xs, np.full_like(xs, NY), np.zeros_like(xs)], 1), top[::-1]])
    cv.poly(cam.poly(poly), (8, 16, 34), 0.55)
    for a_ in range(len(top) - 1):
        cv.line(cam.seg(top[a_], top[a_ + 1]), WHITE, 2.6, 0.95)
    for x_ in (-6.4, 6.4):
        cv.line(cam.seg(np.array([x_, NY, 0]), np.array([x_, NY, NHp])), (200, 210, 230), 2.0, 0.9)


def ellipse_world(center, cov, k=2.448, n=72, z=0.0):
    w_, U = np.linalg.eigh(cov)
    ang = np.linspace(0, 2 * np.pi, n)
    c = np.stack([np.cos(ang), np.sin(ang)], 1) * np.sqrt(np.maximum(w_, 0)) * k
    pts = center[:2] + c @ U.T
    return np.c_[pts, np.full(n, z)]


def seg_tennis(T, N):
    tl = T["tland"]
    st = T["stimes"]
    traj = T["traj"]
    kland = int(np.floor(tl * 340))
    INTRO, SLOW = 1.6, 11.0
    t_fly = tl * SLOW
    k_call = T["k_call"]
    t_call_seg = INTRO + st[k_call] * SLOW
    FREEZE = 1.6
    POST, CARD = 3.2, 6.0
    total = INTRO + t_fly + FREEZE + POST + CARD
    n = int(round(total * FPS))
    xl, yl = T["land"][0], T["land"][1]
    # camera positions (C, fov) at key times; the target follows the ball towards the landing point
    kf = [
        (0.0, (-5.0, -10.0, 6.0), 55),
        (INTRO + 0.35 * t_fly, (13.0, 5.0, 6.0), 50),
        (t_call_seg - 0.2, (-5.0, 32.0, 4.5), 46),
        (t_call_seg + FREEZE + 0.5 * (t_fly - (t_call_seg - INTRO)), (-3.0, 29.0, 2.6), 42),
        (INTRO + t_fly + FREEZE + 1.2, (-1.5, 25.9, 1.05), 34),
        (total, (-1.2, 25.4, 0.85), 30),
    ]
    assert all(a_[0] < b_[0] for a_, b_ in zip(kf[:-1], kf[1:])), [k_[0] for k_ in kf]
    LAND = np.array([xl, yl, 0.0])

    def camera(ts, u):
        if ts <= kf[0][0]:
            C, fov = np.array(kf[0][1]), kf[0][2]
        else:
            C, fov = np.array(kf[-1][1]), kf[-1][2]
            for (ta, Ca, fa), (tb, Cb, fb) in zip(kf[:-1], kf[1:]):
                if ts <= tb:
                    w_ = ease((ts - ta) / (tb - ta))
                    C, fov = np.array(Ca) + w_ * (np.array(Cb) - np.array(Ca)), fa + w_ * (fb - fa)
                    break
        sb = min(1.0, 0.05 + 0.95 * (u / tl) ** 2.6)
        if ts > INTRO + t_fly + FREEZE:
            sb = 1.0
        Tg = (1 - sb) * pos_at(min(u, tl)) + sb * LAND + np.array([0, 0, 0.25 * (1 - sb)])
        return Cam3(C, Tg, fov)

    def sim_time(ts):
        """segment seconds -> (simulated flight seconds, mode)"""
        if ts < INTRO:
            return 0.0, "intro"
        if ts < t_call_seg:
            return (ts - INTRO) / SLOW, "fly"
        if ts < t_call_seg + FREEZE:
            return st[k_call], "freeze"
        u = (ts - FREEZE - INTRO) / SLOW
        if u < tl:
            return u, "fly"
        return tl, "post"

    def fit_index(k):
        j = np.searchsorted(T["ks"], k, side="right") - 1
        return None if j < 0 else int(j)

    def pos_at(u):
        x = u * 340
        k = int(np.floor(x))
        if k + 1 >= len(traj) or not np.isfinite(traj[k + 1, 0]):
            return T["land"]
        fr = x - k
        return traj[k] * (1 - fr) + traj[k + 1] * fr

    def fn(i):
        ts = i / FPS
        u, mode = sim_time(ts)
        cam = camera(ts, u)
        cv = Canvas(bg())
        draw_court(cv, cam)
        k = int(np.floor(u * 340))
        j = fit_index(min(k, kland))
        p = pos_at(u)
        # no-spin counterfactual (truth physics from the same launch, spin switched off)
        ns = T["nospin_traj"]
        ns = ns[np.isfinite(ns[:, 0])]
        nsp = [cam.seg(ns[a], ns[a + 1]) for a in range(0, len(ns) - 1, 3)]
        pts = [q for s_ in nsp for q in s_]
        ns_label = None
        if len(pts) > 1 and mode != "intro":
            cv.line(pts, MUTED, 1.6, 0.55)
            # label at the no-spin apex (clear of the ball and the net), drawn last on its own backing; it must
            # stay left of the readout column and above the callout band
            txt = f"same launch, no spin: lands {signed(ns[-1][1] - BL, '+.1f')} m past the baseline"
            tw = cv.textlen(txt, 17, "Regular")
            for jl in (int(np.argmax(ns[:, 2])), int(np.argmin(np.abs(ns[:, 1] - (BL - 3.0))))):
                pe, ze = cam.project(ns[jl])
                lx = min(max(pe[0] - tw / 2, 24), W - 560 - tw)
                ly = pe[1] - 26
                if ze > 0.3 and 0 < pe[0] < W - 520 and 110 < ly < 740:
                    ns_label = (lx, ly, txt, tw)
                    break
        # true path so far (white trail)
        ku = min(k, kland)
        if ku >= 1:
            tr = traj[:ku + 1]
            tr = np.vstack([tr, p[None]])
            P2, Z2 = cam.project(tr)
            ok = Z2 > 0.2
            seg_pts = [tuple(q) for q in P2[ok]]
            cv.glow_line(seg_pts[-60:], (200, 220, 255), 6, 0.5)
            cv.line(seg_pts, WHITE, 2.6, 0.9)
        # fitted prediction from the current decision frame
        called = k_call is not None and k >= k_call
        if j is not None and mode != "post":
            pt = T["pred_traj"][j]
            pt = pt[np.isfinite(pt[:, 0])]
            pt = np.vstack([pt, T["land_hat"][j][None]])
            P3, Z3 = cam.project(pt)
            ok = Z3 > 0.2
            col = CORAL if called else ACCENT
            cv.glow_line([tuple(q) for q in P3[ok]], col, 5, 0.6)
            cv.line([tuple(q) for q in P3[ok]], col, 2.4, 0.95)
            E = ellipse_world(T["land_hat"][j], T["land_cov"][j])
            cv.poly(cam.poly(E), col, 0.4, outline=col, oa=1.0, width=1.6)
        # landing mark after the bounce
        if mode == "post" or u >= tl:
            M = ellipse_world(T["land"], np.diag([0.034 ** 2, 0.05 ** 2]), k=1.0)
            cv.poly(cam.poly(M), (235, 240, 250), 0.85)
            pm, zm = cam.project(T["land"])
            if zm > 0.2 and mode == "post":
                tg = f"OUT · {T['d_true']*100:.1f} cm"
                tw = cv.textlen(tg, 20, "Bold", tracking=1.0) + 28
                cv.rrect((pm[0] - tw / 2, pm[1] - 92, pm[0] + tw / 2, pm[1] - 56), 8, CORAL, 1.0)
                cv.text((pm[0], pm[1] - 74), tg, 20, "Bold", WHITE, 1.0, "mm", tracking=1.0)
                cv.line([(pm[0], pm[1] - 56), (pm[0], pm[1] - 12)], WHITE, 1.4, 0.8)
            bl = cam.seg(np.array([xl - 1.6, BL, 0.0]), np.array([xl + 1.6, BL, 0.0]), n=4)
            if len(bl) >= 2 and mode == "post":
                q = bl[0] if bl[0][0] < bl[-1][0] else bl[-1]
                cv.text((q[0] + 10, q[1] + 24), "BASELINE", 16, "Semibold", WHITE, 0.9, "lm", tracking=1.4)
        # ball + shadow + spin vector
        if u < tl:
            sh, zs = cam.project(np.array([p[0], p[1], 0.0]))
            if zs > 0.2:
                rr = max(3.0, cam.f * 0.04 / zs)
                s_ = cv.ss
                cv.d.ellipse([(sh[0] - rr * 1.6) * s_, (sh[1] - rr * 0.6) * s_, (sh[0] + rr * 1.6) * s_,
                              (sh[1] + rr * 0.6) * s_], fill=rgba((0, 0, 0), 0.45))
            pb, zb = cam.project(p)
            if zb > 0.2:
                rb = max(6.0, cam.f * 0.0335 / zb)
                cv.glow_dot(pb, rb + 4, BALL_T, 0.7)
                cv.circle(pb, rb, BALL_T, 1.0)
                cv.circle((pb[0] - rb * 0.3, pb[1] - rb * 0.3), rb * 0.35, (255, 255, 230), 0.8)
                if mode != "intro" and j is not None:
                    w = T["spin_hat"][j]
                    wn = w / max(np.linalg.norm(w), 1e-9)
                    tip, zt = cam.project(p + 0.9 * wn)
                    if zt > 0.2:
                        # screen length capped so the arrow never runs into the readout column near the bounce
                        dvec = np.array(tip) - np.array(pb)
                        dl = np.linalg.norm(dvec)
                        dn = dvec / max(dl, 1e-9)
                        tip = np.array(pb) + dn * min(dl, 150.0)
                        cv.line([tuple(pb), tuple(tip)], ACCENT, 3.0, 1.0)
                        nn = np.array([-dn[1], dn[0]])
                        cv.poly([tuple(tip + dn * 10), tuple(tip - dn * 4 + nn * 7), tuple(tip - dn * 4 - nn * 7)],
                                ACCENT, 1.0)
                        lw_ = cv.textlen("spin axis", 17, "Semibold")
                        lx_ = tip[0] + 16 if tip[0] + 16 + lw_ < W - 540 else tip[0] - 16 - lw_
                        cv.rrect((lx_ - 6, tip[1] - 30, lx_ + lw_ + 6, tip[1] - 4), 6, NAVY0, 0.75)
                        cv.text((lx_, tip[1] - 17), "spin axis", 17, "Semibold", (140, 190, 255), 1.0, "lm")
                    # rotation ring in the plane of travel
                    v = T["v0"] / np.linalg.norm(T["v0"])
                    e1 = np.array([v[0], v[1], 0.0])
                    e1 /= np.linalg.norm(e1)
                    e2 = np.array([0, 0, 1.0])
                    ph = (ts * 2.2) % (2 * np.pi)
                    ring = [p + 0.32 * (math.cos(a_ + ph) * e1 + math.sin(a_ + ph) * e2)
                            for a_ in np.linspace(0, 1.6 * np.pi, 40)]
                    Rp, Rz = cam.project(np.array(ring))
                    if (Rz > 0.2).all():
                        cv.line([tuple(q) for q in Rp], ACCENT, 2.0, 0.85)
        if ns_label is not None:
            lx, ly, txt, tw = ns_label
            cv.rrect((lx - 8, ly - 14, lx + tw + 8, ly + 14), 6, NAVY0, 0.72)
            cv.text((lx, ly), txt, 17, "Regular", (206, 214, 232), 1.0, "lm")
        # ------------------------------------------------------------------ HUD panel (opaque: court lines
        # must not show through the readouts)
        HDR = (176, 188, 214)
        x0, y0 = W - 40 - 470, 92
        cv.rrect((x0, y0, W - 40, y0 + 352), 14, NAVY0, 0.95, outline=WHITE, oa=0.12)
        cv.text((x0 + 22, y0 + 28), "SPIN-AWARE PHYSICS FIT (BLS)", 15, "Semibold", HDR, 1, "lm", tracking=1.3)
        if j is None:
            cv.text((x0 + 22, y0 + 80), "acquiring track…", 28, "Medium", WHITE, 1, "lm")
            cv.text((x0 + 22, y0 + 116), f"fit starts {1000 * T['stimes'][T['ks'][0]]:.0f} ms after contact", 18, "Regular",
                    MUTED, 1, "lm")
        else:
            po = float(T["p_out"][j])
            cv.text((x0 + 22, y0 + 66), "P(OUT)", 17, "Semibold", WHITE, 1, "lm", tracking=1.0)
            cv.text((W - 62, y0 + 72), f"{po:.3f}", 46, "Semibold", CORAL if po >= 0.95 else WHITE, 1, "rm", mono=True)
            bar(cv, x0 + 22, y0 + 104, 426, 8, po, CORAL if po >= 0.95 else ACCENT, tick=0.95)
            cv.text((x0 + 22 + 426 * 0.95, y0 + 128), "0.95", 15, "Regular", MUTED, 1, "mm")
            dh = T["d_hat"][j] * 100
            sd95 = 1.96 * T["sd_d"][j] * 100
            cv.text((x0 + 22, y0 + 160), "LANDING vs BASELINE", 15, "Semibold", HDR, 1, "lm", tracking=1.2)
            cv.text((x0 + 22, y0 + 192), f"{signed(dh, '+.1f')} cm", 32, "Semibold", WHITE, 1, "lm", mono=True)
            cv.text((x0 + 214, y0 + 194), f"± {sd95:.1f} cm (95%)", 20, "Regular", MUTED, 1, "lm")
            lead = (tl - u) * 1000
            cv.text((x0 + 22, y0 + 234), "BOUNCE IN", 15, "Semibold", HDR, 1, "lm", tracking=1.2)
            cv.text((x0 + 22, y0 + 266), f"{max(lead, 0):.0f} ms", 32, "Semibold", WHITE, 1, "lm", mono=True)
            rpm = np.linalg.norm(T["spin_hat"][j]) * 60 / (2 * np.pi)
            cv.text((x0 + 240, y0 + 234), "SPIN (FIT · TRUTH)", 15, "Semibold", HDR, 1, "lm", tracking=1.2)
            cv.text((x0 + 240, y0 + 266), f"{rpm:,.0f} rpm", 32, "Semibold", WHITE, 1, "lm", mono=True)
            cv.text((x0 + 240, y0 + 298), f"truth {T['rpm_true']:,.0f} rpm topspin", 17, "Regular", MUTED, 1, "lm")
            cv.text((x0 + 22, y0 + 330), "simulated 340 fps camera · 3.6 mm noise", 17, "Regular", MUTED, 1, "lm")
        # inset: landing zone, top view
        inset(cv, T, j, u >= tl, called)
        # callout
        if called:
            kk = (ts - t_call_seg) * FPS
            text = f"OUT CALLED · {T['call_lead_ms']:.0f} ms BEFORE THE BOUNCE · ±{T['call_sd95_cm']:.1f} cm"
            sub = (f"this simulated shot · call rule: {T['call_rule'].replace('>=', '≥')} · "
                   "±: 95% interval of the landing estimate")
            if ts < INTRO + t_fly + FREEZE + POST:
                callout(cv, 780, text, sub, t=min(1.0, kk / 12))
        if mode == "intro":
            e = ease_out(i / 12) * (1 - ease((ts - INTRO + 0.4) / 0.4))
            t1_ = f"Topspin drive · {np.linalg.norm(T['v0']):.0f} m/s · {T['rpm_true']:,.0f} rpm"
            t2_ = f"lands {T['d_true']*100:.1f} cm past the baseline (simulated truth)"
            bw_ = max(cv.textlen(t1_, 34, "Semibold"), cv.textlen(t2_, 22, "Regular")) + 52
            cv.rrect((40, 96, 40 + bw_, 210), 12, NAVY0, 0.88 * e, outline=WHITE, oa=0.1 * e)
            cv.text((66, 146), t1_, 34, "Semibold", WHITE, e, "ls")
            cv.text((66, 186), t2_, 22, "Regular", (196, 206, 226), e, "ls")
        if ts >= INTRO + t_fly + FREEZE + POST:
            kc = (ts - (INTRO + t_fly + FREEZE + POST)) * FPS
            cv.rect((0, 0, W, H), NAVY0, 0.6 * ease_out(kc / 14))
            pop_card(cv, T, N, kc)
        mt = {"intro": "SIMULATION", "fly": f"SIMULATION · 1/{SLOW:.0f}× SPEED", "freeze": "SIMULATION · FREEZE",
              "post": "SIMULATION · LANDING"}[mode]
        chrome(cv, "03  TENNIS · HAWK-EYE-CLASS REPLAY", LBL_SIM, mt, CORAL if mode == "freeze" else ACCENT)
        return cv.finish()
    meta = dict(n=n, call_lead_ms=T["call_lead_ms"], call_sd95_cm=T["call_sd95_cm"], d_true_cm=T["d_true"] * 100)
    return Seg("tennis", n, fn, 6, 8), meta


def inset(cv, T, j, landed, called):
    x0, y0, x1, y1 = W - 40 - 470, 458, W - 40, 762
    cv.rrect((x0, y0, x1, y1), 14, NAVY0, 0.95, outline=WHITE, oa=0.12)
    cv.text((x0 + 20, y0 + 26), "LANDING ZONE · TOP VIEW", 15, "Semibold", (176, 188, 214), 1, "lm", tracking=1.3)
    cv.text((x0 + 20, y0 + 50), "95% ellipse of the fit · 1 square = 5 cm", 17, "Regular", MUTED, 1, "lm")
    px0, py0, px1, py1 = x0 + 20, y0 + 70, x1 - 20, y1 - 18
    cx = T["land"][0]
    scale = (px1 - px0) / 0.60                                 # 60 cm wide
    yc = BL                                                    # baseline outer edge at the middle

    def P(x, y):
        return (px0 + (x - (cx - 0.30)) * scale, (py0 + py1) / 2 - (y - yc) * scale)

    cv.rect((px0, py0, px1, py1), (24, 62, 128), 1.0)
    yb = P(cx, BL)[1]
    cv.rect((px0, py0, px1, yb), (12, 30, 66), 1.0)
    cv.text((px1 - 10, py0 + 18), "OUT", 17, "Semibold", CORAL, 1.0, "rm", tracking=1.4)
    cv.text((px1 - 10, py1 - 16), "IN", 17, "Semibold", (120, 180, 255), 1.0, "rm", tracking=1.4)
    for g in np.arange(-0.30, 0.31, 0.05):
        xx = P(cx + g, 0)[0]
        cv.rect((xx, py0, xx + 1, py1), WHITE, 0.06)
    for g in np.arange(-0.25, 0.26, 0.05):
        yy = P(cx, yc + g)[1]
        if py0 < yy < py1:
            cv.rect((px0, yy, px1, yy + 1), WHITE, 0.06)
    # baseline: 5 cm line whose outer edge is y = 23.77
    cv.rect((px0, P(cx, BL)[1], px1, P(cx, BL - 0.05)[1]), WHITE, 0.95)
    if j is not None:
        col = CORAL if called else ACCENT
        E = ellipse_world(T["land_hat"][j], T["land_cov"][j])
        pts = clip_rect([P(q[0], q[1]) for q in E], px0, py0, px1, py1)    # true clip, not a clamp
        cv.poly(pts, col, 0.35, outline=col, oa=1.0, width=2.0)
        c = P(T["land_hat"][j][0], T["land_hat"][j][1])
        if px0 < c[0] < px1 and py0 < c[1] < py1:
            cv.circle(c, 3.5, WHITE, 1.0)
    if landed:
        M = ellipse_world(T["land"], np.diag([0.034 ** 2, 0.034 ** 2]), k=1.0, n=48)
        cv.poly([P(q[0], q[1]) for q in M], (240, 244, 252), 0.55, outline=WHITE, oa=0.9, width=1.4)
        c = P(T["land"][0], T["land"][1])
        lab = f"ball centre {T['d_true']*100:.1f} cm out (truth)"
        tw = cv.textlen(lab, 17, "Semibold")
        lx = c[0] + 40 if c[0] + 40 + tw < px1 - 8 else max(px0 + 8, px1 - 8 - tw)
        ly = c[1] - 44
        cv.rrect((lx - 6, ly - 13, lx + tw + 6, ly + 13), 5, NAVY0, 0.8)
        cv.text((lx, ly), lab, 17, "Semibold", WHITE, 1, "lm")


def clip_rect(pts, x0, y0, x1, y1):
    """Sutherland-Hodgman clip of a closed polygon to an axis-aligned box."""
    def clip(P, inside, cross):
        out = []
        for j in range(len(P)):
            a, b = P[j - 1], P[j]
            if inside(b):
                if not inside(a):
                    out.append(cross(a, b))
                out.append(b)
            elif inside(a):
                out.append(cross(a, b))
        return out

    def xcut(xc):
        return lambda a, b: (xc, a[1] + (b[1] - a[1]) * (xc - a[0]) / (b[0] - a[0]))

    def ycut(yc):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (yc - a[1]) / (b[1] - a[1]), yc)

    P = list(pts)
    for inside, cross in ((lambda q: q[0] >= x0, xcut(x0)), (lambda q: q[0] <= x1, xcut(x1)),
                          (lambda q: q[1] >= y0, ycut(y0)), (lambda q: q[1] <= y1, ycut(y1))):
        if not P:
            break
        P = clip(P, inside, cross)
    return P


def pop_card(cv, T, N, k):
    e = ease_out(k / 14)
    x0, y0, x1, y1 = 160, 250, 1240, 700
    cv.rrect((x0, y0, x1, y1), 18, NAVY0, 0.97 * e, outline=WHITE, oa=0.12 * e)
    cv.text((x0 + 44, y0 + 56), "ALL SIMULATED NEAR-LINE SHOTS", 17, "Semibold", (176, 188, 214), e, "ls", tracking=2.0)
    cv.text((x0 + 44, y0 + 92), f"{T['pop_n']:,} groundstrokes · 340 fps · 3.6 mm noise · results/spin/tennis",
            20, "Regular", MUTED, e, "ls")
    cv.text((x0 + 44, y0 + 200), f"±{N['ten_margin95_200']:.2f} cm", 96, "Bold", WHITE, e, "ls")
    cv.text((x0 + 520, y0 + 160), "95% landing margin, 200 ms", 26, "Semibold", WHITE, e, "ls")
    cv.text((x0 + 520, y0 + 194), "before the bounce (spin-aware fit)", 26, "Semibold", WHITE, e, "ls")
    rows = [
        ("OUT called 200 ms before the bounce", f"precision {N['ten_prec_200']:.3f} · recall {100*N['ten_recall_200']:.1f}%"),
        ("Current Hawk-Eye-class predictor", f"±{N['ten_base_margin95_200']:.1f} cm at 200 ms "
                                             f"(±{N['ten_base_margin95_25']:.1f} cm at 25 ms)"),
    ]
    for j, (a_, b_) in enumerate(rows):
        y = y0 + 290 + 62 * j
        cv.rect((x0 + 44, y - 12, x0 + 48, y + 12), ACCENT if j == 0 else MUTED, e)
        cv.text((x0 + 64, y), a_, 22, "Semibold", WHITE, e, "lm")
        cv.text((x0 + 600, y), b_, 22, "Regular", MUTED, e, "lm")
    cv.text((x0 + 44, y1 - 34), "Model study on simulated physics, not measured Hawk-Eye data.", 20, "Regular",
            (196, 206, 226), e, "ls")


# ===================================================================================== SPEED CARD
def seg_speed(N, n=270):
    S = SPEED
    best = 0.408
    med = N["lead_median"] / 1000
    t_stamp = S["stamp_lag_s"]
    t_book = t_stamp + S["book_vs_stamp_s"]
    xa, xb = 580, 1740
    tmin, tmax = -0.6, 2.3
    HDR = (176, 188, 214)

    def X(t):
        return xa + (xb - xa) * (t - tmin) / (tmax - tmin)

    def fn(i):
        cv = Canvas(bg())
        grid(cv, i / FPS, 0.6)
        e0 = ease_out(i / 14)
        cv.text((160, 176), "SPEED", 18, "Semibold", ACCENT, e0, "ls", tracking=3.0)
        cv.text((160, 236), "Where a CV call sits against the market clock", 46, "Bold", WHITE, e0, "ls")
        cv.text((160, 278), "seconds relative to the bounce (contact).  Positive = after.", 24, "Regular", HDR, e0, "ls")
        yax = 640
        prog = ease((i - 10) / 70)
        cv.rect((xa, yax, xa + (xb - xa) * prog, yax + 2), WHITE, 0.5)
        for t in np.arange(-0.5, 2.31, 0.5):
            if X(t) <= xa + (xb - xa) * prog:
                cv.rect((X(t), yax - 6, X(t) + 1, yax + 8), WHITE, 0.5)
                cv.text((X(t), yax + 28), f"{signed(t, '+.1f')} s" if t else "0", 18, "Medium", HDR, 1, "mm", mono=True)
        # bounce
        eb = ease_out((i - 14) / 12)
        cv.rect((X(0) - 1, 384, X(0) + 1, yax), WHITE, 0.8 * eb)
        cv.text((X(0), 366), "BOUNCE / CONTACT", 16, "Semibold", WHITE, eb, "mm", tracking=1.4)
        # book reprice (needs the assumed stamp lag to sit on this axis)
        ek = ease_out((i - 58) / 14)
        if ek > 0:
            cv.rect((X(t_book) - 1.5, 420, X(t_book) + 1.5, yax), ACCENT, ek)
            cv.circle((X(t_book), yax), 9, ACCENT, ek)
            cv.text((X(t_book) + 16, 330), f"book reprices ≈ {signed(t_book, '+.1f')} s", 21, "Semibold", (120, 180, 255),
                    ek, "lm")
            cv.text((X(t_book) + 16, 358), f"median {abs(S['book_vs_stamp_s']):.1f} s before the official stamp",
                    18, "Regular", HDR, ek, "lm")
            cv.text((X(t_book) + 16, 382), f"(live, {S['book_n_points']} WTA points, {S['book_n_matches']} matches);",
                    18, "Regular", HDR, ek, "lm")
            cv.text((X(t_book) + 16, 406), f"placed with the assumed {t_stamp:.1f} s stamp lag", 18, "Regular",
                    HDR, ek, "lm")
        es = ease_out((i - 74) / 14)
        if es > 0:
            cv.rect((X(t_stamp) - 1, 446, X(t_stamp) + 1, yax), MUTED, es)
            cv.circle((X(t_stamp), yax), 8, MUTED, es)
            cv.text((X(t_stamp) - 14, 450), f"official stamp {signed(t_stamp, '+.1f')} s", 19, "Semibold", WHITE, es, "rm")
            cv.text((X(t_stamp) - 14, 476), "assumed lag, not measured", 17, "Regular", HDR, es, "rm")
        # CV calls (real table-tennis calls) and the orders they send, drawn on top of the market markers
        rows = [("best real table-tennis call", -best, 500), ("median real table-tennis call", -med, 580)]
        for j, (lab, tc, y) in enumerate(rows):
            ee = ease_out((i - 26 - 10 * j) / 14)
            if ee <= 0:
                continue
            live = tc + S["inference_s"] + S["venue_delay_s"]
            xe = X(tc) + (X(live) - X(tc)) * ee
            cv.rrect((X(tc), y - 17, xe, y + 17), 8, (60, 24, 28), 0.88 * ee, outline=CORAL, oa=0.9 * ee, width=1.4)
            cv.circle((X(tc), y), 9, CORAL, ee)
            cv.text((X(tc) - 18, y - 11), f"CV call {signed(tc * 1000)} ms", 20, "Semibold", WHITE, ee, "rm")
            cv.text((X(tc) - 18, y + 14), lab, 17, "Regular", HDR, ee, "rm")
            if ee > 0.9:
                cv.circle((xe, y), 5, WHITE, ee)
                ol = f"order live ≈ {signed(live, '+.2f')} s"
                tw = cv.textlen(ol, 18, "Semibold")
                xb_ = X(t_book)
                if xe - 16 - tw - 6 < xb_ + 4 and xe - 10 > xb_ - 4:      # would sit on the book line: put it outside
                    cv.text((xe + 16, y), ol, 18, "Semibold", WHITE, ee, "lm")
                else:
                    cv.text((xe - 16, y), ol, 18, "Semibold", WHITE, ee, "rm")
        el = ease_out((i - 40) / 14)
        if el > 0:
            cv.text((160, 716), "order live = CV call + 20 ms inference + 1 s Polymarket venue order delay "
                    "(network 10–140 ms not drawn)", 19, "Regular", HDR, el, "lm")
            cv.text((160, 744), "CV call times are real table-tennis calls on OpenTTGames footage (held-out games); "
                    "no tennis or Polymarket match video is used.", 19, "Regular", HDR, el, "lm")
        et = ease_out((i - 96) / 16)
        if et > 0:
            cv.rrect((160, 800, W - 160, 940), 14, NAVY0, 0.88 * et, outline=ACCENT, oa=0.5 * et)
            cv.text((196, 844), f"The edge exists only while the CV call lands ≥ ~{S['breakeven_before_stamp_s']:.1f} s "
                    "before the official stamp.", 28, "Semibold", WHITE, et, "lm")
            cv.text((196, 892), (f"Break-even video delay at a {t_stamp:.1f} s stamp lag: "
                                 f"{S['breakeven_video_delay'][0]:.2f} s in sample, {S['breakeven_video_delay'][1]:.2f} s "
                                 "burned OOS (research/v2/feed_latency/LATENCY_SWEEP.md)."), 21, "Regular", HDR, et, "lm")
        chrome(cv, "04  SPEED", LBL_MKT, "TIMING CARD", ACCENT, e0)
        return cv.finish()
    return Seg("speed", n, fn, 8, 8)


# ===================================================================================== BUILD
def build(P_):
    N = load_numbers()
    feat = TT(P_, "test_2", 2819, physics=True)
    q1 = TT(P_, "test_4", 5750)
    q2 = TT(P_, "test_6", 1484)
    bo = TT(P_, "test_6", 1299)
    s_feat = seg_featured(feat, N)
    s_q1, s_q2, s_bo = seg_quick(q1, N), seg_quick(q2, N), seg_bounce(bo, N)
    s_stats = seg_stats(lambda: grade(bo.reader.get(bo.t_ref + 40)), N)
    feat_slow = TT(P_, "test_2", 2819, physics=True)
    s_slow = seg_slowmo(feat_slow, N)
    s_ten, ten_meta = seg_tennis(P_["tennis"], N)
    segs = [
        title_card(N),
        slate("01", "Real match footage", "A miss called before the ball reaches the table end",
              LBL_REAL),
        s_feat, s_q1, s_q2, s_bo, s_stats,
        slate("02", "¼× replay", "The fitted arc locks in, frame by frame", LBL_REAL),
        s_slow,
        slate("03", "Tennis, simulated", "Spin-aware physics fit in a Hawk-Eye-class camera model", LBL_SIM),
        s_ten,
        seg_speed(N),
        end_card(N),
    ]
    return segs, N, ten_meta, dict(feat=feat, q1=q1, q2=q2, bo=bo, slow=feat_slow)


def timeline(segs):
    t, rows = 0, []
    for s in segs:
        rows.append(dict(name=s.name, start_s=round(t / FPS, 3), dur_s=round(s.n / FPS, 3), frames=s.n))
        t += s.n
    return rows, t


def render_video(segs, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r",
           str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-maxrate", "6M",
           "-bufsize", "12M", "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1", "-threads", "4",
           "-movflags", "+faststart", tmp]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    total = sum(s.n for s in segs)
    done = 0
    for s in segs:
        ts = time.time()
        for i in range(s.n):
            p.stdin.write(np.ascontiguousarray(s.frame(i)).tobytes())
        done += s.n
        print(f"[video] {s.name}: {s.n} frames in {time.time() - ts:.0f} s ({done}/{total})", flush=True)
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    os.replace(tmp, path)
    print(f"[video] wrote {path} in {time.time() - t0:.0f} s", flush=True)


def frame_at(segs, sec):
    k = int(round(sec * FPS))
    for s in segs:
        if k < s.n:
            return s.frame(k), s.name
        k -= s.n
    s = segs[-1]
    return s.frame(s.n - 1), s.name


def seg_by(segs, prefix):
    return next(s for s in segs if s.name.startswith(prefix))


def save_png(img, path):
    Image.fromarray(img).save(path, dpi=(300, 300), optimize=True)


def render_stills(segs, P_, N, ten_meta):
    os.makedirs(STILLS, exist_ok=True)
    global SS
    old = SS
    SS = 3                                                    # finer anti-aliasing for print
    _FC.clear()
    feat = seg_by(segs, "featured")
    slow = seg_by(segs, "slowmo")
    tt = TT(P_, "test_2", 2819, physics=True)
    ten = P_["tennis"]
    picks = []
    # 1: featured call frame, callout fully in
    picks.append(("still_01_tt_call_408ms.png", feat, 42 + 40,
                  "Real match footage (OpenTTGames, held-out test_2, flight 2819; CC BY-NC-SA 4.0). The frozen "
                  "tier-0 model calls MISS 408 ms before the ball reaches the table end (online rule: "
                  f"P(MISS) ≥ {N['tau_online']:.2f} on 3 consecutive frames). Comet: BlurBall detections. Arc, "
                  "95% cone, table-height crossing ellipse, P(in/long/net/wide) and spin: online drag + Magnus "
                  "physics fit, display only."))
    # 2: slow-mo late in the flight, ghosts + chart
    plan_idx = (tt.call - (tt.t0 - 40)) + 45 + (tt.t_ref - 8 - tt.call)
    picks.append(("still_02_tt_arc_lock_in.png", slow, plan_idx,
                  "Quarter-speed replay of the same flight, 67 ms before contact. Faint lines: the predicted arc at "
                  "earlier decision frames; they converge as track points accumulate. Inset: the fit's predicted "
                  "crossing past the end line with its 95% band (physics fit, display only)."))
    # 3: early decision frame: wide cone (slow-mo index of t = first fit + 4)
    early = tt.fit_ts[0] + 4
    picks.append(("still_03_tt_uncertainty_early.png", slow, early - (tt.t0 - 40),
                  f"Same flight at {1000*(tt.t_ref-early)/SRC_FPS:.0f} ms before contact, before the call: with "
                  "few track points the physics fit's 95% cone is wide and its predicted crossing past the end line is "
                  f"+{tt.fits[early]['x_land']:.1f} ± {1.96*tt.fits[early]['x_land_sd']:.1f} m (inset); compare "
                  "still 2. Real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0)."))
    q1 = seg_by(segs, "quick:test_4")
    q2 = seg_by(segs, "quick:test_6")
    picks.append(("still_04_tt_call_83ms.png", q1, 20 + 30,
                  "Real match footage (OpenTTGames, held-out test_4, flight 5750; CC BY-NC-SA 4.0). Fast ball (about 19 m/s, image estimate): the "
                  "frozen model calls MISS 83 ms before the ball reaches the table end."))
    picks.append(("still_05_tt_call_25ms.png", q2, 20 + 30,
                  "Real match footage (OpenTTGames, held-out test_6, flight 1484; CC BY-NC-SA 4.0). The frozen model calls MISS "
                  "25 ms before contact, the median first-call lead of the 8 online calls on the test games."))
    st = seg_by(segs, "tennis")
    tl, stt = ten["tland"], ten["stimes"]
    t_call = 1.6 + stt[ten["k_call"]] * 11.0
    picks.append(("still_06_tennis_out_call.png", st, int(round((t_call + 1.0) * FPS)),
                  f"Simulated physics: Hawk-Eye-class camera model (not real footage). A topspin drive "
                  f"({ten['rpm_true']:,.0f} rpm) that lands {ten['d_true']*100:.1f} cm long. The spin-aware fit "
                  f"calls OUT {ten['call_lead_ms']:.0f} ms before the bounce (P(OUT) ≥ 0.95 on 5 consecutive frames; "
                  f"landing ±{ten['call_sd95_cm']:.1f} cm, 95%). White: true path; coral: fitted prediction and its 95% landing ellipse; grey: the same "
                  "launch without spin (Magnus effect); blue: fitted spin axis."))
    picks.append(("still_07_tennis_landing.png", st, int(round((1.6 + tl * 11.0 + 1.6 + 2.6) * FPS)),
                  "Simulated physics (not real footage). Close-up after the bounce: ball mark beyond the baseline, "
                  "the final 95% landing ellipse and the top-view inset."))
    sp = seg_by(segs, "speed")
    picks.append(("still_08_speed_card.png", sp, sp.n - 12,
                  "Speed card. CV call times are real-footage calls (OpenTTGames); order timing adds 20 ms inference "
                  "and Polymarket's 1 s venue order delay. Book reprice: median 1.2 s before the official WTA point "
                  "stamp (live data, 482 points, 2026-10-03; no match video). The 2.0 s stamp lag is assumed, not "
                  "measured."))
    caps = {}
    for name, seg, idx, cap in picks:
        idx = int(min(max(idx, 0), seg.n - 1))
        img = seg.fn(idx)
        save_png(img, os.path.join(STILLS, name))
        caps[name] = cap
        print(f"[stills] {name}", flush=True)
    json.dump(caps, open(os.path.join(STILLS, "captions.json"), "w"), indent=1, ensure_ascii=False)
    SS = old
    _FC.clear()
    return caps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["prep", "video", "stills"], default=None)
    ap.add_argument("--reprep", action="store_true")
    ap.add_argument("--preview", type=float, nargs="*")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args()
    P_ = prep(force=a.reprep)
    if a.only == "prep":
        return
    segs, N, ten_meta, _ = build(P_)
    rows, total = timeline(segs)
    print(f"[build] {len(segs)} segments, {total} frames = {total / FPS:.1f} s", flush=True)
    if a.preview is not None:
        od = a.out_dir or os.path.join(ASSETS, "preview")
        os.makedirs(od, exist_ok=True)
        for sec in a.preview:
            img, nm = frame_at(segs, sec)
            Image.fromarray(img).save(os.path.join(od, f"t{sec:06.2f}.png"))
            print(f"[preview] {sec:.2f}s -> {nm}", flush=True)
        return
    if a.only in (None, "video"):
        render_video(segs, OUT_MP4)
    caps = None
    if a.only in (None, "stills"):
        caps = render_stills(segs, P_, N, ten_meta)
    feat = P_["tt"]
    man = dict(
        output=os.path.relpath(OUT_MP4, REPO), fps=FPS, size=[W, H], frames=total, duration_s=round(total / FPS, 2),
        segments=rows,
        labels=dict(real=LBL_REAL, sim=LBL_SIM, market=LBL_MKT),
        calls_source="frozen tier-0 model (data/cv_showcase/assets.json from scripts/cv_showcase_assets.py)",
        featured=dict(video="test_2", f_net=2819, call_lead_ms=408.3, physics_reproduction_max_dev=feat["reproduction_max_dev"],
                      anchor=feat["anchor"]),
        tennis=dict(shot_index=P_["tennis"]["shot_index"], d_true_cm=round(P_["tennis"]["d_true"] * 100, 2),
                    rpm_true=round(P_["tennis"]["rpm_true"]), call_lead_ms=round(P_["tennis"]["call_lead_ms"], 1),
                    call_sd95_cm=round(P_["tennis"]["call_sd95_cm"], 2)),
        numbers=N, speed=SPEED, stills=caps)
    if a.only == "stills" and os.path.exists(MANIFEST):
        old = json.load(open(MANIFEST))
        old["stills"] = caps
        man = old
    json.dump(man, open(MANIFEST, "w"), indent=1, ensure_ascii=False, default=float)


if __name__ == "__main__":
    main()
