"""Presentation demo videos of the H3 early call on held-out OpenTTGames test footage.

Presentation only: this script changes no reported number and no model. It refits the frozen
model exactly as `early_call.py --final` did: HGB with random_state=0 on game_1..5 flights, the
same gate and taus read from early_call_final.json. It then asserts that its scores and online
first-call leads reproduce results/tracking/test_flights.csv before rendering anything.

Selection (automatic, on the post-hoc AUDITED test labels, results/tracking/test_flights_audited.csv,
and only flights the audit left unchanged):
  MISS   : the 3 test misses with the longest online first-call lead (tau_online, 3 consecutive
           frames, i.e. the rule a live trader would use) whose ball is tracked on >= 50% of the
           flight frames.
  BOUNCE : a correctly passed bounce that the model actually judged: the horizon gate is open at
           -50 ms, P(miss) < 0.2 there and < 0.5 at every decision frame; among these, the one
           landing deepest (closest to the end line).

Overlay: detected ball + fading trail, table outline, dashed arc extrapolated from the causal
fit at that frame, and a status box. For a MISS the status switches TRACKING -> "MISS CALLED -NN ms"
at the online first-call frame. For a BOUNCE it switches to "BOUNCE -50 ms" at the snapshot
decision frame. Each clip runs in real time and is followed by a 0.25x replay of the last ~0.6 s
before contact.

Outputs: results/tracking/demo/*.mp4 (H.264, 1280x720, 60 fps), *.png posters, manifest.json
Usage: python render_demo.py   (CPU; ~5 min)
"""
import json
import os

import av
import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import early_call as E
from common import FPS, OTTG, WORK, geometry_all
from plots import _to_px

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RES = os.environ.get("TRACK_RESULTS", os.path.join(REPO, "results", "tracking"))
OUT = os.path.join(RES, "demo")
W, H = 1280, 720
SC = W / 1920.0
OUT_FPS = 60
CRF = os.environ.get("DEMO_CRF", "21")   # keeps results/tracking/ under 20 MB in total
CREDIT = "Footage: OpenTTGames (OSAI), CC BY-NC-SA 4.0"

RED = (230, 57, 70)
GREEN = (46, 196, 112)
YELLOW = (255, 209, 70)
WHITE = (245, 245, 245)
GREY = (170, 170, 170)


def font(size, bold=False):
    import matplotlib.font_manager as fm
    return ImageFont.truetype(fm.findfont("DejaVu Sans:bold" if bold else "DejaVu Sans"), size)


F_BIG, F_MED, F_SMALL, F_TINY = font(30, True), font(19, True), font(16), font(14)


# ----------------------------------------------------------------------------- model / selection
def frozen_scores():
    fin = json.load(open(os.path.join(WORK, "early_call_final.json")))
    E.GATE_H = fin["gate_h_s"]
    fl = pd.read_csv(os.path.join(WORK, "flights.csv"))
    tr = fl[fl.split == "train"].reset_index(drop=True)
    te_a = pd.read_csv(os.path.join(RES, "test_flights_audited.csv"))
    te_o = pd.read_csv(os.path.join(RES, "test_flights.csv"))
    te = te_a[te_a.audit.isna()].reset_index(drop=True)          # flights the audit left unchanged
    geo = geometry_all()
    tracks = E.load_tracks(sorted(fl.video.unique()))
    S_tr, _ = E.build_samples(tr, tracks, geo)
    S, objs = E.build_samples(te, tracks, geo)
    s, _ = E.fit_predict(fin["model"], S_tr, S)
    S = S.assign(score=s)
    # reproduce the frozen evaluation exactly
    orig = te_o.set_index(["video", "f_net"])
    leads = {}
    for fid, g in S.groupby("fid"):
        arr = np.full(int(g.k.max()) + 1, -np.inf)
        arr[g.k.values] = g.score.values
        pers = np.array([arr[k:k + E.PERSIST].min() if k + E.PERSIST - 1 < len(arr) else -np.inf
                         for k in range(len(arr))])
        ok = np.where(pers >= fin["tau_online"])[0]
        leads[fid] = int(ok.max()) if len(ok) else None
        r = te.loc[fid]
        o = orig.loc[(r.video, r.f_net)]
        p50 = g.score[g.k == E.k_of(50)]
        if len(p50) and np.isfinite(o.p_miss_at_50ms):
            assert abs(float(p50.iloc[0]) - o.p_miss_at_50ms) < 1e-9, (r.video, r.f_net)
        exp = o.first_call_lead_ms
        got = np.nan if leads[fid] is None else E.ms(leads[fid])
        assert (np.isnan(exp) and np.isnan(got)) or abs(exp - got) < 1e-6, (r.video, r.f_net, exp, got)
    te["online_lead_frames"] = te.index.map(leads)
    te["max_score"] = S.groupby("fid").score.max()
    s50 = S[S.k == E.k_of(50)].set_index("fid")
    te["p50"] = s50.score
    te["gated50"] = np.minimum(s50.tau_end, s50.tau_net) > E.GATE_H
    te["dist_out_m"] = te.set_index(["video", "f_net"]).index.map(orig.dist_out_m)
    cover = []
    for fid in te.index:
        Fo = objs[fid]
        cover.append(len(Fo.fr) / max(1, te.loc[fid, "t_ref"] - te.loc[fid, "t0"] + 1))
    te["coverage"] = cover
    return fin, te, S, objs, tracks, geo


def select(te, fin):
    # out balls often leave the frame, so only half of the flight needs a tracked ball
    miss = te[(te.label == "MISS") & te.online_lead_frames.notna() & (te.coverage >= 0.5)]
    miss = miss.sort_values("online_lead_frames", ascending=False).head(3)
    # a bounce the model actually judged: the gate is open at -50 ms (the ball is within 100 ms
    # of the end line, i.e. it lands deep) and P(miss) stays low
    b = te[(te.label == "BOUNCE") & (te.max_score < 0.5) & (te.p50 < 0.2) & (te.gated50 == False)
           & (te.coverage >= 0.9) & (te.dist_out_m < 0)]
    b = b.sort_values("dist_out_m", ascending=False).head(1)
    return list(miss.index) + list(b.index)


# ----------------------------------------------------------------------------- frames / drawing
def decode(video, s, e):
    c = av.open(os.path.join(OTTG, f"{video}.mp4"))
    st = c.streams.video[0]
    st.thread_type = "AUTO"
    fps, tb = float(st.average_rate), float(st.time_base)
    c.seek(int(max(s - 2, 0) / fps / tb), stream=st, backward=True, any_frame=False)
    out = {}
    for fr in c.decode(st):
        i = int(round(fr.pts * tb * fps))
        if i < s:
            continue
        if i > e:
            break
        out[i] = fr.to_ndarray(width=W, height=H, format="rgb24", interpolation="AREA")
    c.close()
    return out


def blend_circle(img, c, r, color, alpha):
    x, y = int(round(c[0])), int(round(c[1]))
    x0, y0, x1, y1 = max(x - r - 2, 0), max(y - r - 2, 0), min(x + r + 3, W), min(y + r + 3, H)
    if x1 <= x0 or y1 <= y0:
        return
    roi = img[y0:y1, x0:x1]
    lay = roi.copy()
    cv2.circle(lay, (x - x0, y - y0), r, color, -1, cv2.LINE_AA)
    cv2.addWeighted(lay, alpha, roi, 1 - alpha, 0, dst=roi)


def dashed(img, pts, color, thick=2, on=7, off=5):
    """Dashed polyline with dash length measured along the curve (px)."""
    acc, draw = 0.0, True
    for p, q in zip(pts[:-1], pts[1:]):
        seg = float(np.hypot(*(q - p)))
        if draw:
            cv2.line(img, tuple(np.round(p).astype(int)), tuple(np.round(q).astype(int)), color, thick, cv2.LINE_AA)
        acc += seg
        if acc >= (on if draw else off):
            acc, draw = 0.0, not draw


def rounded_box(draw, xy, fill, r=10):
    draw.rounded_rectangle(xy, radius=r, fill=fill)


class Clip:
    def __init__(self, fid, te, S, objs, tracks, geo, fin):
        self.r = te.loc[fid]
        self.v = self.r.video
        self.F = objs[fid]
        self.g = geo[self.v]
        self.trk = tracks[self.v]
        self.fin = fin
        g = S[S.fid == fid]
        self.score = dict(zip(g.t.values, g.score.values))
        self.gated = dict(zip(g.t.values, (np.minimum(g.tau_end, g.tau_net) > E.GATE_H).values))
        self.t_ref = int(self.r.t_ref)
        self.is_miss = self.r.label == "MISS"
        if self.is_miss:
            self.lead_k = int(self.r.online_lead_frames)
        else:
            self.lead_k = E.k_of(50)
        self.call_frame = self.t_ref - self.lead_k
        self.lead_ms = E.ms(self.lead_k)
        self.first_dec = min(self.score) if self.score else self.t_ref
        corners = self.g["corners"] * SC
        self.table = np.round(corners).astype(np.int32).reshape(-1, 1, 2)
        if self.is_miss:
            mt = self.r.miss_type if isinstance(self.r.miss_type, str) else "out"
            self.actual = "MISS (into the net)" if mt == "net" else "MISS (out)"
        else:
            self.actual = "TABLE BOUNCE"

    # -------------------------------------------------------------------------- overlay
    def render(self, base, f, mode):
        img = base.copy()
        # table outline
        lay = img.copy()
        cv2.polylines(lay, [self.table], True, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.addWeighted(lay, 0.55, img, 0.45, 0, dst=img)
        called = f >= self.call_frame
        col = (RED if self.is_miss else GREEN) if called else WHITE
        # dashed arc from the causal fit at this frame (only during the analysed flight)
        if self.first_dec <= f <= self.t_ref and self.F.features(f) is not None:
            from plots import _arc
            au, aw = _arc(self.F, f, horizon=0.2)
            x, y = _to_px(au, aw, self.g, self.r.dir)
            pts = np.stack([x * SC, y * SC], 1)
            pts = pts[(pts[:, 0] > -50) & (pts[:, 0] < W + 50) & (pts[:, 1] > -50) & (pts[:, 1] < H + 50)]
            if len(pts) > 2:
                dashed(img, pts, col, 2)
        # fading trail + ball
        trail = [(t, self.trk[t]) for t in range(f - 18, f + 1) if t in self.trk]
        for t, p in trail[:-1]:
            a = 0.15 + 0.6 * (1 - (f - t) / 19.0)
            blend_circle(img, (p[0] * SC, p[1] * SC), max(2, int(5 - (f - t) * 0.18)), YELLOW, a)
        if f in self.trk:
            p = self.trk[f]
            c = (int(round(p[0] * SC)), int(round(p[1] * SC)))
            cv2.circle(img, c, 10, YELLOW, 2, cv2.LINE_AA)
            cv2.circle(img, c, 3, YELLOW, -1, cv2.LINE_AA)
        return self.text(img, f, mode, called)

    def text(self, img, f, mode, called):
        pil = Image.fromarray(img).convert("RGBA")
        ov = Image.new("RGBA", pil.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        # status box
        bx0, by0, bx1, by1 = 20, 20, 470, 156
        rounded_box(d, (bx0, by0, bx1, by1), (15, 18, 24, 190))
        d.text((bx0 + 14, by0 + 10), "TIER-0 CALL  (ball tracking, 1 camera)", font=F_TINY, fill=GREY)
        if called:
            fill = RED if self.is_miss else GREEN
            msg = (f"MISS CALLED  −{self.lead_ms:.0f} ms" if self.is_miss
                   else f"BOUNCE  −{self.lead_ms:.0f} ms")
            rounded_box(d, (bx0 + 10, by0 + 32, bx1 - 10, by0 + 76), fill + (235,), r=7)
            d.text((bx0 + 20, by0 + 36), msg, font=F_BIG, fill=(255, 255, 255))
        else:
            d.text((bx0 + 20, by0 + 36), "TRACKING", font=F_BIG, fill=WHITE)
        # P(miss) bar
        tau = self.fin["tau_online"] if self.is_miss else self.fin["tau_snapshot"]
        yb = by0 + 88
        d.text((bx0 + 14, yb), "P(miss)", font=F_SMALL, fill=GREY)
        x0, x1 = bx0 + 92, bx1 - 70
        d.rectangle((x0, yb + 5, x1, yb + 15), fill=(70, 70, 70, 255))
        s = self.score.get(f)   # the evaluated score (0 while the horizon gate is closed)
        if s is not None:
            d.rectangle((x0, yb + 5, x0 + (x1 - x0) * float(s), yb + 15),
                        fill=(RED if s >= tau else YELLOW) + (255,))
            d.text((x1 + 8, yb), f"{s:.2f}", font=F_SMALL, fill=WHITE)
        else:
            d.text((x1 + 8, yb), "—", font=F_SMALL, fill=GREY)
        xt = x0 + (x1 - x0) * tau
        d.line((xt, yb + 1, xt, yb + 19), fill=(255, 255, 255, 255), width=2)
        actual = self.actual if f >= self.t_ref else "—"
        d.text((bx0 + 14, yb + 26), f"actual: {actual}", font=F_SMALL,
               fill=WHITE if f >= self.t_ref else GREY)
        # mode tag + clock (top right)
        tag = "REAL TIME" if mode == "rt" else "0.25× SLOW-MO REPLAY"
        tw = d.textlength(tag, font=F_MED)
        rounded_box(d, (W - tw - 46, 20, W - 20, 54), (15, 18, 24, 190))
        d.text((W - tw - 33, 25), tag, font=F_MED, fill=YELLOW if mode != "rt" else WHITE)
        clock = f"{self.v}   frame {f}   t = {f / FPS:7.3f} s"
        cw = d.textlength(clock, font=F_TINY)
        rounded_box(d, (W - cw - 40, 60, W - 20, 84), (15, 18, 24, 170), r=6)
        d.text((W - cw - 30, 64), clock, font=F_TINY, fill=WHITE)
        to_c = (self.t_ref - f) / FPS * 1000
        if 0 < to_c <= 1500:
            s2 = f"contact / table end in {to_c:4.0f} ms"
            c2 = d.textlength(s2, font=F_TINY)
            rounded_box(d, (W - c2 - 40, 90, W - 20, 114), (15, 18, 24, 170), r=6)
            d.text((W - c2 - 30, 94), s2, font=F_TINY, fill=GREY)
        # credit (bottom left) and legend (bottom right)
        cwid = d.textlength(CREDIT, font=F_TINY)
        rounded_box(d, (14, H - 40, 34 + cwid, H - 14), (0, 0, 0, 150), r=6)
        d.text((24, H - 36), CREDIT, font=F_TINY, fill=WHITE)
        leg = "yellow: detected ball (BlurBall)   dashed: arc extrapolated from the fit so far"
        lw = d.textlength(leg, font=F_TINY)
        rounded_box(d, (W - lw - 34, H - 40, W - 14, H - 14), (0, 0, 0, 150), r=6)
        d.text((W - lw - 24, H - 36), leg, font=F_TINY, fill=GREY)
        return np.array(Image.alpha_composite(pil, ov).convert("RGB"))

    # -------------------------------------------------------------------------- timeline
    def timeline(self, pre_s=3.0, post_s=0.6, sm_before=72, sm_after=18, freeze_s=0.6, short=False):
        t0 = int(self.r.t0)
        if short:
            pre_s, post_s, sm_before, sm_after, freeze_s = 0.6, 0.3, 48, 8, 0.4
        rt0 = max(t0 - int(pre_s * FPS), 0)
        rt1 = self.t_ref + int(post_s * FPS)
        sm0 = min(self.t_ref - sm_before, self.call_frame - 12)
        sm1 = self.t_ref + sm_after
        tl = [(f, "rt") for f in range(rt0, rt1 + 1, int(FPS / OUT_FPS))]
        for f in range(sm0, sm1 + 1):
            reps = int(round(OUT_FPS / (FPS * 0.25)))            # 2 output frames per source frame
            if f == self.call_frame:
                reps += int(freeze_s * OUT_FPS)                   # hold on the call
            tl += [(f, "slow")] * reps
        return tl, (min(rt0, sm0), max(rt1, sm1))


def encode(path, frames_iter):
    out = av.open(path, mode="w", options={"movflags": "faststart"})
    st = out.add_stream("libx264", rate=OUT_FPS,
                        options={"crf": CRF, "preset": "slow", "profile": "high", "tune": "film"})
    st.width, st.height, st.pix_fmt = W, H, "yuv420p"
    n = 0
    for img in frames_iter:
        for p in st.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            out.mux(p)
        n += 1
    for p in st.encode():
        out.mux(p)
    out.close()
    return n


def render_clip(clip, tl, frames):
    cache = {}
    for f, mode in tl:
        key = (f, mode)
        if key not in cache:
            cache.clear()
            cache[key] = clip.render(frames[f], f, mode)
        yield cache[key]


def title_card(seconds=0.8):
    img = Image.new("RGB", (W, H), (12, 14, 20))
    d = ImageDraw.Draw(img)
    l1, l2 = "Calling the point before the ball lands", \
        "BlurBall ball detector + causal arc fit  ·  held-out OpenTTGames test videos  ·  real time, then 0.25×"
    d.text(((W - d.textlength(l1, font=F_BIG)) / 2, H / 2 - 40), l1, font=F_BIG, fill=WHITE)
    d.text(((W - d.textlength(l2, font=F_SMALL)) / 2, H / 2 + 10), l2, font=F_SMALL, fill=GREY)
    d.text((24, H - 36), CREDIT, font=F_TINY, fill=GREY)
    a = np.array(img)
    return [a] * int(seconds * OUT_FPS)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fin, te, S, objs, tracks, geo = frozen_scores()
    picks = select(te, fin)
    print("selected:", [(te.loc[i, "video"], int(te.loc[i, "f_net"]), te.loc[i, "label"],
                         te.loc[i, "online_lead_frames"]) for i in picks], flush=True)
    manifest = {"note": "presentation only; frozen model, audited test labels; see render_demo.py",
                "tau_online": fin["tau_online"], "tau_snapshot": fin["tau_snapshot"], "clips": []}
    clips, frames_all = [], {}
    for n, fid in enumerate(picks, 1):
        c = Clip(fid, te, S, objs, tracks, geo, fin)
        tl, (a, b) = c.timeline()
        frames = decode(c.v, a, b)
        frames_all[fid] = frames
        clips.append(c)
        kind = "miss" if c.is_miss else "bounce"
        name = f"{n:02d}_{kind}_{c.v}_f{int(c.r.f_net)}_{'lead' if c.is_miss else 'at'}{c.lead_ms:.0f}ms"
        path = os.path.join(OUT, name + ".mp4")
        nfr = encode(path, render_clip(c, tl, frames))
        poster = c.render(frames[c.call_frame], c.call_frame, "slow")
        Image.fromarray(poster).save(os.path.join(OUT, name + ".png"), optimize=True)
        info = dict(file=name + ".mp4", poster=name + ".png", video=c.v, f_net=int(c.r.f_net),
                    label=c.r.label, actual=c.actual, call=("MISS" if c.is_miss else "BOUNCE"),
                    call_lead_ms=round(c.lead_ms, 1), call_rule=("online (tau_online, 3 frames)" if c.is_miss
                                                                  else "snapshot at -50 ms (P(miss) < tau_snapshot)"),
                    p_miss_at_50ms=round(float(c.r.p50), 4), duration_s=round(nfr / OUT_FPS, 2),
                    size_mb=round(os.path.getsize(path) / 1e6, 2))
        manifest["clips"].append(info)
        print(info, flush=True)

    # supercut: title card + the 4 calls back to back (short timelines)
    def sup():
        yield from title_card()
        for c in clips:
            fid = c.r.name
            tl, _ = c.timeline(short=True)
            yield from render_clip(c, tl, frames_all[fid])
    path = os.path.join(OUT, "supercut.mp4")
    nfr = encode(path, sup())
    best = clips[0]
    Image.fromarray(best.render(frames_all[best.r.name][best.call_frame], best.call_frame, "slow")).save(
        os.path.join(OUT, "supercut.png"), optimize=True)
    manifest["supercut"] = dict(file="supercut.mp4", poster="supercut.png", duration_s=round(nfr / OUT_FPS, 2),
                                size_mb=round(os.path.getsize(path) / 1e6, 2))
    print(manifest["supercut"])
    json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
