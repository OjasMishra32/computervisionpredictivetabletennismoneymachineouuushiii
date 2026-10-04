"""COURTSIDE 75-90 s cut (research/compliance/VIDEO_REQUIREMENTS.md, the table at the top): visual assets.

    .venv/bin/python scripts/make_video_60.py select      # write the selection rule + chosen calls (before any render)
    .venv/bin/python scripts/make_video_60.py cut         # cut the source clips on HiPerGator, copy them to data/v60/src
    .venv/bin/python scripts/make_video_60.py overlays    # per-call overlaid clips from the engine's logged output
    .venv/bin/python scripts/make_video_60.py segments    # every other segment as an animated 1080p plate
    .venv/bin/python scripts/make_video_60.py all         # select (if missing), overlays, segments, manifest
    .venv/bin/python scripts/make_video_60.py manifest    # rewrite results/viz/v60_assets/manifest.json only

Outputs (results/viz/v60_assets/)
    selection.json        the rule and the calls it picked (written before any clip is rendered)
    clips/<id>.mp4        1920x1080 30 fps, real held-out OpenTTGames footage with the overlay drawn from the
                          streaming engine's own log (gitignored: results/viz/v60_assets/clips/)
    clips/<id>.json       output frame -> source frame map, call / contact times in the clip, verification
    seg_*.mp4             animated plates for the other segments (1920x1080, 30 fps, no audio) + seg_*.png
    manifest.json         every number on screen -> file + key + value; every asset -> inputs and labels

What is drawn on the footage, and from where (nothing invented):
    ball + comet trail    engine track log (frame, x, y) of the L4 real-time run, pickle
                          results/engine/online_vs_offline_raw_compile.pkl on HiPerGator (copied to data/v60/)
    P(miss) gauge         the engine's per-frame gated P(miss) (trace: t, dir, t0, p, gate) of the same run
    predicted arc         the engine's own trajectory fit at that decision frame (early_call.Flight.features on
                          the logged track and flight start); re-scored with the frozen classifier and checked
                          against the logged score before it is drawn
    call stamp            the CallEvent (results/engine/online_events_L4.jsonl, identical to the pickle's events)
                          at its own frame; lead = labelled contact frame T_ref (results/tracking/test_flights.csv)
                          minus the call frame, at 120 fps
Paper trading only. Footage: OpenTTGames (OSAI), held-out games, CC BY-NC-SA 4.0, overlays added.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import pickle
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import make_video_v2 as v2  # noqa: E402  (drawing primitives, palette, value registry; unmodified)
from make_video_v2 import (AMBER, BG, BLUE, CORAL, DIM, GREEN, GREY, GRID, INK, INK2, MUTED, ORANGE,  # noqa: E402
                           PANEL, PANEL2, SAND, C, ease, ease_io, f0, f1, f2, fmt, rr, tsprite, usd)

W, H, FPS = 1920, 1080, 30
SRC_FPS = 120.0
ASSETS = Path("results/viz/v60_assets")
CLIPS = ASSETS / "clips"
SELECTION = ASSETS / "selection.json"
MANIFEST = ASSETS / "manifest.json"
WORK = Path("data/v60")                       # gitignored scratch: source cuts + the engine pickle
SRC = WORK / "src"
RAW = WORK / "online_vs_offline_raw_compile.pkl"
EVENTS = Path("results/engine/online_events_L4.jsonl")
OVO = Path("results/engine/online_vs_offline.json")
FLIGHTS = Path("results/tracking/test_flights_audited.csv")
RUN = "fp16_cl_fuse_compile_b1_realtime"     # the run whose events are online_events_L4.jsonl

HPG = "ojasvamishra@hpg.rc.ufl.edu"
SSH = ["ssh", "-S", os.path.expanduser("~/.ssh/cm-hpg"), "-o", "BatchMode=yes", HPG]
SCP = ["scp", "-o", "ControlPath=" + os.path.expanduser("~/.ssh/cm-hpg"), "-o", "BatchMode=yes"]
HPG_ROOT = "/blue/ai-workshop/ojasvamishra/courtside"
HPG_OTTG = HPG_ROOT + "/openttgames"
HPG_RAW = HPG_ROOT + "/results/engine/online_vs_offline_raw_compile.pkl"
HPG_OUT = HPG_ROOT + "/work/v60_clips"

LABEL_FOOT = "OpenTTGames held-out games (CC BY-NC-SA 4.0)"
LABEL_REPLAY = "backtest replay of a real match recorded 2026-10-03; assumed 1 s licensed feed; no video of this match"
LABEL_RESULTS = "simulated 1 s licensed-feed baseline"
LABEL_SIM = "simulated physics"
END_CARD = "Paper trading only · Voice: AI (ElevenLabs)"

PRE_S, POST_S = 2.0, 1.5        # source cut around the call frame
SLOW_PRE, SLOW_POST = 18, 14    # source frames at 1/4 speed before the call / after max(call, contact)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def jload(p):
    return json.loads(Path(p).read_text())


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


# ====================================================================================================
# 1. selection (written before anything is rendered)
# ====================================================================================================
RULE = {
    "population": "the 172 CallEvents the streaming engine emitted on the held-out games test_1..test_7 in the L4 "
                  "real-time run (results/engine/online_events_L4.jsonl; run fp16_cl_fuse_compile_b1_realtime of "
                  "results/engine/online_vs_offline.json)",
    "eligible": "the call is matched to a labelled test flight (online_vs_offline.json runs.<run>."
                "flights_called_or_miss: same video, the flight's engine_miss_frame / engine_bounce_frame equals the "
                "call frame), the call agrees with the label (MISS call on a MISS-labelled flight, BOUNCE call on a "
                "BOUNCE-labelled flight), it was made at or before the labelled contact frame T_ref (lead >= 0), and "
                "the flight carries no post-hoc label-audit flag (test_flights_audited.csv audit empty)",
    "chosen": "every eligible MISS call; then, for each held-out game without an eligible MISS call, the eligible "
              "BOUNCE call whose lead is closest to the median lead of all eligible BOUNCE calls (ties: earliest "
              "frame). Lead = (T_ref - call frame) / 120 fps.",
    "why": "shows the model's own calls exactly where it made them, on as many different held-out games as possible, "
           "MISS calls preferred; BOUNCE examples are representative (median lead), not the best ones",
    "not_shown_but_counted": "all 172 calls are in the on-screen totals (counters), including the 7 MISS calls on "
                             "balls outside the labelled flights, the MISS call after contact, the BOUNCE calls on "
                             "MISS-labelled flights and the 37 labelled MISS flights the engine did not call",
}


def load_flights():
    import csv
    rows = {}
    with open(FLIGHTS) as fh:
        for r in csv.DictReader(fh):
            rows[(r["video"], int(r["f_net"]))] = r
    return rows


def select():
    ev = [json.loads(ln) for ln in EVENTS.read_text().splitlines() if ln.strip()]
    ovo = jload(OVO)
    fl = ovo["runs"][RUN]["flights_called_or_miss"]
    aud = load_flights()
    elig = []
    for f in fl:
        key = (f["video"], f["f_net"])
        audit = (aud.get(key) or {}).get("audit") or None
        for call, fr in (("MISS", f["engine_miss_frame"]), ("BOUNCE", f["engine_bounce_frame"])):
            if fr is None:
                continue
            e = [x for x in ev if x["video"] == f["video"] and x["frame"] == fr and x["call"] == call]
            assert len(e) == 1, (key, call, fr)
            e = e[0]
            lead = (f["t_ref"] - fr) * 1000.0 / SRC_FPS
            ok = (call == f["label"]) and lead >= 0 and audit is None
            elig.append(dict(video=f["video"], call=call, frame=fr, label=f["label"], f_net=f["f_net"], t0=f["t0"],
                             t_ref=f["t_ref"], audit=audit, lead_ms=round(lead, 1), eligible=ok,
                             direction=e["direction"], p_miss_at_call=e["p_miss"],
                             predicted_lead_ms=e["lead_ms"], emitted_latency_ms=e["latency_ms"],
                             engine_flight_t0=e["flight_t0"], rule=e["rule"]))
    ok = [x for x in elig if x["eligible"]]
    miss = sorted([x for x in ok if x["call"] == "MISS"], key=lambda x: (x["video"], x["frame"]))
    bl = [x["lead_ms"] for x in ok if x["call"] == "BOUNCE"]
    med = float(np.median(bl))
    games = sorted({x["video"] for x in ev}, key=lambda s: int(s.split("_")[1]))
    have = {x["video"] for x in miss}
    pick = list(miss)
    for g in games:
        if g in have:
            continue
        cand = [x for x in ok if x["call"] == "BOUNCE" and x["video"] == g]
        if cand:
            pick.append(min(cand, key=lambda x: (abs(x["lead_ms"] - med), x["frame"])))
    for x in pick:
        x["id"] = f"{x['video']}_f{x['frame']}_{x['call'].lower()}"
        x["clip_src_frames"] = [x["frame"] - int(PRE_S * SRC_FPS), x["frame"] + int(POST_S * SRC_FPS)]
    out = {
        "written_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "written_before_rendering": True,
        "rule": RULE,
        "inputs": {str(EVENTS): sha(EVENTS), str(OVO): sha(OVO), str(FLIGHTS): sha(FLIGHTS)},
        "eligible_counts": {"MISS": len(miss), "BOUNCE": len(bl),
                            "BOUNCE_median_lead_ms": med},
        "considered": {"matched_calls": len(elig),
                       "excluded": [dict((k, x[k]) for k in ("video", "call", "frame", "label", "lead_ms", "audit"))
                                    for x in elig if not x["eligible"] and x["call"] == "MISS"]},
        "chosen": pick,
        "games": sorted({x["video"] for x in pick}),
    }
    ASSETS.mkdir(parents=True, exist_ok=True)
    SELECTION.write_text(json.dumps(out, indent=1))
    print(f"selection: {len(pick)} calls on {len(out['games'])} games -> {SELECTION}")
    for x in pick:
        print(f"  {x['id']:<28} label {x['label']:<6} lead {x['lead_ms']:>6.1f} ms  P(miss) {x['p_miss_at_call']:.3f}")
    return out


# ====================================================================================================
# 2. source cuts on HiPerGator (frame-exact, high-quality re-encode, 120 fps kept)
# ====================================================================================================
def cut():
    sel = jload(SELECTION)
    lines = ["set -eo pipefail", "module load ffmpeg", f"mkdir -p {HPG_OUT}"]
    for x in sel["chosen"]:
        a, b = x["clip_src_frames"]
        out = f"{HPG_OUT}/{x['id']}.mp4"
        vf = f"select='between(n\\,{a}\\,{b})',setpts=N/({SRC_FPS:.0f}*TB)"
        lines.append(f"[ -s {out} ] || ffmpeg -v error -nostdin -y -i {HPG_OTTG}/{x['video']}.mp4 -an -vf \"{vf}\" "
                     f"-r {SRC_FPS:.0f} -c:v libx264 -preset slow -crf 14 -pix_fmt yuv420p {out}")
        lines.append(f"echo {x['id']} $(stat -c %s {out})")
    script = "\n".join(lines)
    cmd = (f"cd {HPG_ROOT} && srun -A ai-workshop --qos=ai-workshop -c 8 --mem=8G -t 00:30:00 "
           f"-J v60cut bash -lc {shlex.quote(script)}")
    print("HiPerGator:", len(sel["chosen"]), "cuts")
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True)
    print(r.stdout[-2000:], r.stderr[-2000:])
    r.check_returncode()
    SRC.mkdir(parents=True, exist_ok=True)
    for x in sel["chosen"]:
        run(SCP + [f"{HPG}:{HPG_OUT}/{x['id']}.mp4", str(SRC / f"{x['id']}.mp4")])
    if not RAW.exists():
        run(SCP + [f"{HPG}:{HPG_RAW}", str(RAW)])


# ====================================================================================================
# 3. the engine's own log: track, per-frame score, and its trajectory fit (re-derived and checked)
# ====================================================================================================
class EngineLog:
    """Everything drawn on the footage comes from here. fit() re-runs the engine's own feature code
    (src/tracking/early_call.Flight, imported exactly as engine/vision/stream.py imports it) on the logged track
    and the logged flight start, re-scores it with the frozen classifier and requires the result to equal the
    score the engine logged at that frame; a frame that does not reproduce gets no arc."""

    def __init__(self):
        from engine.vision.stream import load_frozen, load_geometry, tracking_modules
        self.fz = load_frozen()
        self.M = tracking_modules()
        self.E = self.M.E
        self.E.GATE_H = float(self.fz["gate_h_s"])
        self.feats = list(self.fz.get("feats", self.E.FEATS_ALL))
        self.tau_on = float(self.fz["tau_online"])
        self.tau_snap = float(self.fz["tau_snapshot"])
        self.persist = int(self.fz.get("persist", 3))
        self._load_geometry = load_geometry
        blob = pickle.load(open(RAW, "rb"))
        self.raws = {r["video"]: r for r in blob["raws"]}
        self.meta = blob["meta"]
        self._g, self._trk, self._tr, self._fit = {}, {}, {}, {}
        self.checked = {"frames": 0, "reproduced": 0, "max_abs_dp": 0.0}

    def geo(self, v):
        if v not in self._g:
            self._g[v] = self._load_geometry(v, self.fz)[0]
        return self._g[v]

    def trk(self, v):
        if v not in self._trk:
            tk = self.raws[v]["track"]
            ok = np.isfinite(tk[:, 1])
            self._trk[v] = {int(f): (float(x), float(y)) for f, x, y in tk[ok][:, :3]}
        return self._trk[v]

    def trace(self, v):
        if v not in self._tr:
            self._tr[v] = {int(t): (float(d), int(t0), float(p), bool(g)) for t, d, t0, p, g in self.raws[v]["trace"]}
        return self._tr[v]

    def run_len(self, v, t):
        """consecutive decision frames up to t with P >= tau_online on the same flight (the persistence count)."""
        tr = self.trace(v)
        if t not in tr:
            return 0
        key = tr[t][:2]
        n = 0
        while t in tr and tr[t][:2] == key and tr[t][2] >= self.tau_on:
            n += 1
            t -= 1
        return n

    def fit(self, v, t):
        if (v, t) in self._fit:
            return self._fit[(v, t)]
        tr = self.trace(v).get(t)
        out = None
        if tr is not None:
            E, g, trk = self.E, self.geo(v), self.trk(v)
            d, t0, p_log, gate_log = tr
            F = E.Flight(SimpleNamespace(dir=d, t0=t0, t_ref=t - E.LAG), trk, g)
            f = F.features(t)
            if f is not None:
                X = np.array([[f[k] for k in self.feats]], dtype=float)
                p_raw = float(self.fz["model"].predict_proba(X)[0, 1])
                gate = min(f["tau_end"], f["tau_net"]) <= self.fz["gate_h_s"]
                p = p_raw if gate else 0.0
                m = F.fr <= t - E.LAG
                fr, u, w = F.fr[m][-E.NFIT:], F.u[m][-E.NFIT:], F.w[m][-E.NFIT:]
                tau = (fr - (t - E.LAG)) / E.FPS
                cu, _ = E.robust_quadfit(tau, u)
                cw, _ = E.robust_quadfit(tau, w)
                same = (abs(p - p_log) <= 1e-9 and bool(gate) == gate_log and cu[2] == f["u_now"]
                        and cw[2] == f["w_now"])
                self.checked["frames"] += 1
                self.checked["reproduced"] += int(same)
                self.checked["max_abs_dp"] = max(self.checked["max_abs_dp"], abs(p - p_log))
                out = dict(ok=same, d=d, t0=t0, p=p_log, gate=gate_log, f=f, cu=cu, cw=cw, tau_first=float(tau[0]),
                           hb=F.hb, L=F.L, npts=len(fr))
        self._fit[(v, t)] = out
        return out

    def to_px(self, v, d, u, w):
        g = self.geo(v)
        L = g["x_right"] - g["x_left"]
        x = g["x_left"] + u * L if d > 0 else g["x_right"] - u * L
        af, bf = g["far_line"]
        an, bn = g["near_line"]
        ymid = 0.5 * ((af + an) * x + bf + bn)
        return x, ymid - w * L

    def arc(self, v, ft, horizon=0.45):
        """observed (tau <= 0) and predicted (tau > 0) pixel polylines of the fit; landing point at the mid level."""
        E = self.E
        cu, cw = ft["cu"], ft["cw"]
        u_now, du = cu[2], cu[1]
        tl = E.first_cross(cw, 0.0)
        stop = min(tl if tl is not None else horizon, horizon)
        obs_t = np.linspace(ft["tau_first"], 0.0, 24)
        pre_t = np.linspace(0.0, max(stop, 1e-3), 40)
        ob = [self.to_px(v, ft["d"], np.polyval(cu, s), np.polyval(cw, s)) for s in obs_t]
        pr = [self.to_px(v, ft["d"], u_now + du * s, np.polyval(cw, s)) for s in pre_t]
        land = None
        if tl is not None and tl <= horizon:
            ul = u_now + du * tl
            land = dict(px=self.to_px(v, ft["d"], ul, 0.0), u=float(ul), long=bool(ul > 1.0), tau_s=float(tl))
        return ob, pr, land


# ====================================================================================================
# 4. overlay rendering (cv2 anti-aliased shapes, PIL text), piped to ffmpeg
# ====================================================================================================
def hexrgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def blend(dst, src_rgba, x, y, k=1.0):
    """alpha-blend a PIL RGBA sprite (or HxWx4 uint8 array) onto the HxWx3 uint8 frame at (x, y)."""
    a = np.asarray(src_rgba) if not isinstance(src_rgba, np.ndarray) else src_rgba
    h, w = a.shape[:2]
    x, y = int(round(x)), int(round(y))
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, dst.shape[1]), min(y + h, dst.shape[0])
    if x1 <= x0 or y1 <= y0 or k <= 0.003:
        return
    s = a[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    al = s[..., 3:4] / 255.0 * k
    reg = dst[y0:y1, x0:x1].astype(np.float32)
    dst[y0:y1, x0:x1] = (reg * (1 - al) + s[..., :3] * al).astype(np.uint8)


_SPR = {}


def spr(s, size, w="demi", fill=INK, plate=None, pad=(18, 8), r=10, outline=None, spacing=0):
    key = (s, size, w, fill, plate, pad, r, outline, spacing)
    if key not in _SPR:
        t = tsprite(s, size, w, fill, spacing=spacing)
        if plate is None:
            _SPR[key] = t
        else:
            pl = rr((t.size[0] + 2 * pad[0], t.size[1] + 2 * pad[1]), r, C(plate[0], plate[1]),
                    C(outline[0], outline[1]) if outline else None, 2 if outline else 1)
            pl.alpha_composite(t, pad)
            _SPR[key] = pl
    return _SPR[key]


def glow_layer(shape, draw_fn, blur=9, gain=1.0):
    """draw_fn(img) draws on a black float image; returns (sharp, glow) float32 HxWx3 arrays."""
    img = np.zeros(shape, np.float32)
    draw_fn(img)
    import cv2
    g = cv2.GaussianBlur(img, (0, 0), blur) * gain
    return img, g


CYAN = "#5fd4ff"


def p_color(p):
    if p >= 0.98:
        return CORAL
    if p >= 0.6:
        return AMBER
    return CYAN


def gauge_panel(p, active, gate, run_n, hist, tau_on, persist):
    """P(miss) gauge: value, bar with the call threshold, persistence pips, sparkline of the logged score."""
    Wp, Hp = 548, 222
    im = rr((Wp, Hp), 18, C(BG, 210), C(GRID, 255), 2)
    d = ImageDraw.Draw(im)
    im.alpha_composite(tsprite("P(MISS)  ·  MODEL'S LIVE SCORE", 18, "demi", MUTED, spacing=1.6), (22, 14))
    col = p_color(p) if active else DIM
    val = tsprite(f"{p:.3f}" if active else "–", 66, "heavy", col)
    im.alpha_composite(val, (18, 38))
    sub = "gate open" if (active and gate) else ("gated (far from net / end line)" if active else "no flight yet")
    im.alpha_composite(tsprite(sub, 18, "demi", INK2 if active else DIM), (236, 54))
    for i in range(persist):
        on = active and i < run_n
        x0 = 238 + i * 28
        d.rounded_rectangle((x0, 92, x0 + 20, 106), radius=4, fill=C(CORAL if on else GRID, 255 if on else 220))
    im.alpha_composite(tsprite(f"{persist} in a row ≥ {tau_on:.2f} = MISS call", 16, "medium", MUTED),
                       (238 + persist * 28 + 6, 87))
    bx0, bx1, by0, by1 = 22, Wp - 22, 130, 148
    d.rounded_rectangle((bx0, by0, bx1, by1), radius=9, fill=C(PANEL2, 255))
    if active and p > 0:
        d.rounded_rectangle((bx0, by0, bx0 + max(18, (bx1 - bx0) * p), by1), radius=9, fill=C(col, 255))
    xt = bx0 + (bx1 - bx0) * tau_on
    d.line((xt, by0 - 7, xt, by1 + 7), fill=C(INK, 235), width=3)
    sx0, sx1, sy0, sy1 = 22, Wp - 22, 164, Hp - 14
    d.line((sx0, sy1, sx1, sy1), fill=C(GRID, 255), width=1)
    yt = sy1 - (sy1 - sy0) * tau_on
    for xx in range(sx0, sx1, 10):
        d.line((xx, yt, xx + 5, yt), fill=C(INK, 120), width=1)
    n = 60
    h = hist[-n:]
    if len(h) >= 2:
        pts = [(sx1 - (sx1 - sx0) * (len(h) - 1 - i) / (n - 1), sy1 - (sy1 - sy0) * q) for i, q in enumerate(h)]
        d.line(pts, fill=C(col if active else MUTED, 255), width=3, joint="curve")
    return im


def stamp_sprite(call, lead_ms):
    big = "MISS" if call == "MISS" else "IN"
    col = CORAL if call == "MISS" else GREEN
    t1 = tsprite(big, 116, "heavy", INK)
    t2 = tsprite(f"{f0(lead_ms)} ms early", 44, "heavy", INK)
    w = max(t1.size[0], t2.size[0]) + 80
    h = t1.size[1] + t2.size[1] + 8
    im = rr((w, h), 22, C(col, 240), C(INK, 235), 3)
    im.alpha_composite(t1, ((w - t1.size[0]) // 2, 4))
    im.alpha_composite(t2, ((w - t2.size[0]) // 2, t1.size[1] - 14))
    return im


def outcome_label(x):
    if x["label"] == "BOUNCE":
        return "bounce (label)"
    return "hits the net (label)" if x.get("miss_type") == "net" else "passes the end line (label)"


def fade_k(im, k):
    if k >= 0.999:
        return im
    out = im.copy()
    out.putalpha(im.getchannel("A").point(lambda q: int(q * k)))
    return out


def scale_spr(im, k):
    if abs(k - 1) < 1e-3:
        return im
    return im.resize((max(1, int(im.size[0] * k)), max(1, int(im.size[1] * k))), Image.LANCZOS)


def out_timeline(x, slow_all=False):
    """output frame -> absolute source frame, with a 1/4-speed window around the call and the contact."""
    a, b = x["clip_src_frames"]
    s0 = a if slow_all else x["frame"] - SLOW_PRE
    s1 = max(x["frame"], x["t_ref"]) + SLOW_POST
    seq, f, slow = [], float(a), []
    while f <= b:
        fi = int(round(f))
        sl = s0 <= fi <= s1
        seq.append(fi)
        slow.append(sl)
        f += 1.0 if sl else SRC_FPS / FPS
    return seq, slow


def window_tags(x):
    """every other CallEvent the engine emitted inside the clip window, with what the labels say about it."""
    a, b = x["clip_src_frames"]
    ev = [json.loads(ln) for ln in EVENTS.read_text().splitlines() if ln.strip()]
    fl = jload(OVO)["runs"][RUN]["flights_called_or_miss"]
    m = {}
    for f in fl:
        for c, fr in (("MISS", f["engine_miss_frame"]), ("BOUNCE", f["engine_bounce_frame"])):
            if fr is not None:
                m[(f["video"], fr, c)] = f
    tags = []
    for e in ev:
        if e["video"] != x["video"] or not (a <= e["frame"] <= b) or e["frame"] == x["frame"]:
            continue
        f = m.get((e["video"], e["frame"], e["call"]))
        word = "MISS" if e["call"] == "MISS" else "IN"
        if f is None:
            sub, kind = "ball not in the labelled set", "unlabelled"
        else:
            lead = (f["t_ref"] - e["frame"]) * 1000.0 / SRC_FPS
            if f["audit"]:
                sub, kind = f"label audit: {f['audit'].replace('_', ' ')} (call likely wrong)", "disputed"
            elif e["call"] != f["label"]:
                sub, kind = f"WRONG: label says {'MISS' if f['label'] == 'MISS' else 'bounce'}", "wrong"
            elif lead > 0:
                sub, kind = f"right, {f0(lead)} ms early", "right"
            elif lead == 0:
                sub, kind = "right, on the bounce frame", "right"
            else:
                sub, kind = f"right, {f0(-lead)} ms after the bounce", "late"
        tags.append(dict(frame=e["frame"], call=e["call"], word=word, sub=sub, kind=kind,
                         xy=e["extra"].get("xy"), t_ref=None if f is None else f["t_ref"],
                         label=None if f is None else f["label"]))
    return tags


def tag_sprite(t):
    col = CORAL if t["call"] == "MISS" else GREEN
    w1 = tsprite(t["word"], 34, "heavy", INK)
    w2 = tsprite(t["sub"], 18, "demi", CORAL if t["kind"] == "wrong" else INK2)
    w = max(w1.size[0], w2.size[0]) + 30
    h = w1.size[1] + w2.size[1] + 2
    im = rr((w, h), 12, C(BG, 215), C(CORAL if t["kind"] == "wrong" else col, 255), 3)
    im.alpha_composite(w1, ((w - w1.size[0]) // 2, 2))
    im.alpha_composite(w2, ((w - w2.size[0]) // 2, w1.size[1] - 2))
    return im


def render_clip(x, L: EngineLog, out_mp4: Path, cell=False, slow_all=False):
    import cv2
    v = x["video"]
    trk, tr = L.trace(v), L.trace(v)
    trk = L.trk(v)
    scale, hs = (0.45, 1.5) if cell else (1.0, 1.0)
    OW, OH = int(round(W * scale / 2)) * 2, int(round(H * scale / 2)) * 2
    seq, slow = out_timeline(x, slow_all)
    a = x["clip_src_frames"][0]
    src = SRC / f"{x['id']}.mp4"
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "21",
                            "-tune", "film", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_mp4)],
                           stdin=subprocess.PIPE)
    call_f, tref = x["frame"], x["t_ref"]
    call_fit = L.fit(v, call_f)
    assert call_fit is not None and call_fit["ok"], f"{x['id']}: the call frame does not reproduce from the log"
    call_arc = L.arc(v, call_fit)
    stamp = stamp_sprite(x["call"], x["lead_ms"])
    tags = window_tags(x)
    for t in tags:
        t["spr"], t["out0"] = tag_sprite(t), None
    chip1 = spr(f"REAL FOOTAGE · {LABEL_FOOT}" if not cell else f"{v} · {LABEL_FOOT}", 22, "demi", AMBER,
                plate=(BG, 215), outline=(AMBER, 190))
    chip2 = spr(f"held-out game {v} · engine's own logged calls (NVIDIA L4, 120 fps, real time)", 19, "medium", INK2,
                plate=(BG, 200))
    cur_i, cur = -1, None
    info = {"out_frames": len(seq), "call_out_frame": None, "contact_out_frame": None, "slow_from_out_frame": None,
            "slow_to_out_frame": None, "arc_frames_drawn": 0, "arc_frames_skipped_not_reproduced": 0}
    t_call_out = None
    for oi, (s, sl) in enumerate(zip(seq, slow)):
        idx = s - a
        while cur_i < idx:
            buf = dec.stdout.read(W * H * 3)
            if len(buf) < W * H * 3:
                raise RuntimeError(f"{src}: ran out of frames at {cur_i + 1} (wanted {idx})")
            cur, cur_i = buf, cur_i + 1
        fr = np.frombuffer(cur, np.uint8).reshape(H, W, 3).copy()
        if sl and info["slow_from_out_frame"] is None:
            info["slow_from_out_frame"] = oi
        if sl:
            info["slow_to_out_frame"] = oi
        if s >= call_f and info["call_out_frame"] is None:
            info["call_out_frame"], t_call_out = oi, oi
        if s >= tref and info["contact_out_frame"] is None:
            info["contact_out_frame"] = oi
        called = s >= call_f
        # ---- shapes: trail, arc, landing, flashes (anti-aliased, with glow) ----
        hist = [(f, trk[f]) for f in range(s - 30, s + 1) if f in trk]
        ft = None
        if not called:
            q = L.fit(v, s)
            if q is not None and q["ok"] and q["npts"] >= 10:
                ft = q
                info["arc_frames_drawn"] += 1
            elif q is not None and not q["ok"]:
                info["arc_frames_skipped_not_reproduced"] += 1
        arc_k = 1.0
        if called and s > tref + 12:
            arc_k = max(0.0, 1.0 - (s - tref - 12) / 24.0)
        arc = (call_arc if arc_k > 0 else None) if called else (L.arc(v, ft) if ft else None)
        p_now = tr.get(s)
        pcol = hexrgb(p_color(p_now[2])) if p_now else hexrgb(CYAN)
        if called:
            pcol = hexrgb(CORAL if x["call"] == "MISS" else GREEN)

        def draw(img):
            S = 4      # cv2 fixed-point subpixel shift
            sh = lambda pt: (int(round(pt[0] * (1 << S))), int(round(pt[1] * (1 << S))))  # noqa: E731
            if arc is not None:
                ob, pr, land = arc
                kk = arc_k if called else 0.75
                col = tuple(c / 255 * kk for c in pcol)
                pts = np.array([sh(p) for p in ob], np.int32)
                cv2.polylines(img, [pts], False, tuple(c * 0.55 for c in col), 2, cv2.LINE_AA, S)
                for i in range(0, len(pr) - 1, 2):          # dashed prediction
                    cv2.line(img, sh(pr[i]), sh(pr[i + 1]), col, 4 if called else 3, cv2.LINE_AA, S)
                if land is not None:
                    lc = hexrgb(CORAL) if land["long"] else hexrgb(GREEN)
                    lc = tuple(c / 255 * kk for c in lc)
                    cv2.ellipse(img, sh(land["px"]), (int(26 * 16), int(9 * 16)), 0, 0, 360, lc, 3, cv2.LINE_AA, S)
                    cv2.ellipse(img, sh(land["px"]), (int(8 * 16), int(3 * 16)), 0, 0, 360, lc, -1, cv2.LINE_AA, S)
            # comet trail
            n = len(hist)
            for i in range(1, n):
                (f_a, pa), (f_b, pb) = hist[i - 1], hist[i]
                if f_b - f_a > 4:
                    continue
                k = (s - f_b) / 30.0
                al = (1 - k) ** 1.6
                th = max(1, int(round(2 + 9 * (1 - k))))
                c = (1.0 * al, (0.42 + 0.5 * (1 - k)) * al, 0.13 * al + 0.6 * (1 - k) ** 4 * al)
                cv2.line(img, sh(pa), sh(pb), c, th, cv2.LINE_AA, S)
            if s in trk:
                cv2.circle(img, sh(trk[s]), 13 * 16, (1.0, 0.95, 0.85), 2, cv2.LINE_AA, S)
            # call flash at the ball, contact flash
            if called:
                k = (s - call_f) / 10.0
                if 0 <= k <= 1 and call_f in trk:
                    r = int((20 + 90 * ease(k)) * 16)
                    cv2.circle(img, sh(trk[call_f]), r, tuple(c / 255 * (1 - k) for c in pcol), 5, cv2.LINE_AA, S)
            if s >= tref:
                k = (s - tref) / 12.0
                if 0 <= k <= 1:
                    pt = trk.get(tref) or (hist[-1][1] if hist else None)
                    if pt is not None:
                        r = int((14 + 60 * ease(k)) * 16)
                        cv2.circle(img, sh(pt), r, (1 - k, 1 - k, 1 - k), 3, cv2.LINE_AA, S)
        sharp, glow = glow_layer((H, W, 3), draw, blur=7, gain=1.4)
        f32 = fr.astype(np.float32) / 255.0
        f32 *= 0.92                                          # slight grade so the HUD reads
        m = np.clip(sharp.max(axis=2, keepdims=True) * 1.6, 0, 1)
        f32 = f32 * (1 - m) + sharp * m
        f32 = 1 - (1 - f32) * (1 - np.clip(glow * 0.55, 0, 1))   # screen-blend glow
        fr = (np.clip(f32, 0, 1) * 255).astype(np.uint8)
        # ---- HUD: chips, gauge, stamp, timeline (hs > 1 for the 2x2 cells, drawn bigger then scaled down) ----
        def B(im, xx, yy, k=1.0, anchor="la"):
            im = scale_spr(im, hs) if hs != 1.0 else im
            xx -= {"l": 0, "m": im.size[0] / 2, "r": im.size[0]}[anchor[0]]
            yy -= {"a": 0, "m": im.size[1] / 2, "b": im.size[1]}[anchor[1]]
            blend(fr, im, xx, yy, k)
            return im.size
        M_ = 44 * hs
        cw_, chh = B(chip1, M_, 38 * hs)
        if not cell:
            B(chip2, M_, 38 * hs + chh + 8)
        hist_p = [tr[t][2] for t in range(s - 90, s + 1) if t in tr and tr[t][:2] == (tr.get(s) or (None, None))[:2]] \
            if p_now else []
        if called:
            pc = tr.get(call_f)
            gp = gauge_panel(pc[2], True, pc[3], L.run_len(v, call_f), [tr[t][2] for t in range(call_f - 90, call_f + 1)
                                                                         if t in tr and tr[t][:2] == pc[:2]],
                             L.tau_on, L.persist)
        else:
            gp = gauge_panel(p_now[2] if p_now else 0.0, p_now is not None, p_now[3] if p_now else False,
                             L.run_len(v, s), hist_p, L.tau_on, L.persist)
        B(gp, W - M_, 38 * hs, anchor="ra")
        sp = spr("¼ SPEED" if sl else "REAL TIME", 20, "demi", AMBER if sl else MUTED, plate=(BG, 190))
        sw_, _ = B(sp, M_, H - M_, anchor="lb")
        if not cell:
            B(spr(f"frame {s:,}", 20, "medium", INK2, plate=(BG, 190)), M_ + sw_ + 10, H - M_, anchor="lb")
        # every other call the engine made in this window, at its own frame
        for t in tags:
            if s >= t["frame"] and t["out0"] is None:
                t["out0"] = oi
            if t["out0"] is None:
                continue
            age = oi - t["out0"]
            k = min(1.0, (age + 1) / 3.0) * (1.0 - ease_io((age - 16) / 6.0) if age > 16 else 1.0)
            if k <= 0.01:
                continue
            bx, by = trk.get(t["frame"]) or tuple(t["xy"] or (W / 2, H / 2))
            sp_ = scale_spr(t["spr"], hs)
            blend(fr, sp_, min(max(bx - sp_.size[0] / 2, 20), W - 20 - sp_.size[0]),
                  min(max(by - 70 - sp_.size[1], 160 * hs + 40), H - 300 * hs), k)
        # the selected call's stamp
        if called:
            k = (oi - t_call_out) / 5.0
            sc = 1.0 + 0.35 * (1 - ease(min(max(k, 0), 1)))
            st = scale_spr(stamp, sc)
            B(st, W / 2, H - (258 if not cell else 250 * hs), min(1.0, 0.35 + k), anchor="mm")
        # call -> outcome timeline (bottom centre)
        tl_w = 760
        f_lo, f_hi = min(x["engine_flight_t0"], call_f - 30), max(tref, call_f) + 8
        X = lambda f: 20 + tl_w * (f - f_lo) / (f_hi - f_lo)  # noqa: E731
        tl = Image.new("RGBA", (tl_w + 40, 76), (0, 0, 0, 0))
        dd = ImageDraw.Draw(tl)
        dd.rounded_rectangle((0, 28, tl_w + 40, 76), radius=12, fill=C(BG, 200))
        dd.line((20, 52, 20 + tl_w, 52), fill=C(GRID, 255), width=4)
        nowx = X(min(max(s, f_lo), f_hi))
        dd.line((20, 52, nowx, 52), fill=C(INK2, 255), width=4)
        cx, kx = X(call_f), X(tref)
        ccol = CORAL if x["call"] == "MISS" else GREEN
        dd.line((cx, 38, cx, 66), fill=C(ccol, 255 if called else 110), width=4)
        dd.line((kx, 38, kx, 66), fill=C(INK, 255 if s >= tref else 110), width=4)
        if called:
            dd.line((cx, 45, kx, 45), fill=C(ccol, 255), width=3)
        dd.ellipse((nowx - 7, 45, nowx + 7, 59), fill=C(INK, 255))
        lab_c = spr("model call", 18, "demi", ccol)
        lab_k = spr(outcome_label(x), 18, "demi", INK2)
        tl.alpha_composite(fade_k(lab_c, 1.0 if called else 0.55), (int(max(0, cx - lab_c.size[0] - 4)), 2))
        tl.alpha_composite(fade_k(lab_k, 1.0 if s >= tref else 0.55),
                           (int(min(kx + 4, tl.size[0] - lab_k.size[0])), 2))
        B(tl, W / 2, H - M_ + 8, anchor="mb")
        if scale != 1.0:
            fr = cv2.resize(fr, (OW, OH), interpolation=cv2.INTER_AREA)
        enc.stdin.write(fr.tobytes())
    enc.stdin.close()
    enc.wait()
    dec.kill()
    info["other_calls_in_window"] = [dict({k: t[k] for k in ("frame", "call", "sub", "kind", "label", "t_ref")},
                                          out_frame=t["out0"]) for t in tags]
    info.update(fps=FPS, src_frames=seq, slow=[bool(q) for q in slow],
                call_out_t=info["call_out_frame"] / FPS, contact_out_t=info["contact_out_frame"] / FPS,
                duration_s=len(seq) / FPS,
                call_fit=dict(reproduced=call_fit["ok"], p_logged=call_fit["p"], tau_mid_ms=1000 * call_fit["f"]["tau_mid"],
                              tau_end_ms=1000 * call_fit["f"]["tau_end"], tau_net_ms=1000 * call_fit["f"]["tau_net"],
                              u_now=call_fit["f"]["u_now"], w_now=call_fit["f"]["w_now"],
                              landing=call_arc[2]))
    return info


def overlays(only=None):
    sel = jload(SELECTION)
    fl = load_flights()
    L = EngineLog()
    CLIPS.mkdir(parents=True, exist_ok=True)
    out = []
    for x in sel["chosen"]:
        if only and x["id"] not in only:
            continue
        x = dict(x, miss_type=(fl.get((x["video"], x["f_net"])) or {}).get("miss_type") or None)
        mp4 = CLIPS / f"{x['id']}.mp4"
        info = render_clip(x, L, mp4)
        render_clip(x, L, CLIPS / f"{x['id']}_cell.mp4", cell=True)
        side = dict(id=x["id"], file=str(mp4), file_cell=str(CLIPS / f"{x['id']}_cell.mp4"),
                    cell_note="same frames and timing, 864x486, HUD drawn 1.5x for the 2x2 grid", source_cut=str(SRC / f"{x['id']}.mp4"),
                    source_cut_sha256=sha(SRC / f"{x['id']}.mp4"), event=x, label=LABEL_FOOT,
                    outcome_tick=outcome_label(x), **info)
        side = json.loads(json.dumps(side, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
        (CLIPS / f"{x['id']}.json").write_text(json.dumps(side, indent=1))
        out.append(side)
        print(f"  {x['id']:<26} {info['duration_s']:.2f} s  call at {info['call_out_t']:.2f} s  "
              f"{mp4.stat().st_size / 1e6:.1f} MB  arcs {info['arc_frames_drawn']}")
    print("fit reproduction:", L.checked)
    return out, L.checked


# ====================================================================================================
# 5. the 1 s equity curve: the committed sweep cells re-run day by day (totals must match draw for draw)
# ====================================================================================================
EQUITY = ASSETS / "equity_1s.csv"
EQUITY_CHECK = ASSETS / "equity_1s_check.json"


def equity_1s():
    """Daily paper P&L of the V = 1 s video cells of results/tier0/latency_sweep_seeds.csv (readings
    tournament_lagcal and tournament, IS and burned OOS, 20 seeds each), from the unchanged sweep code. Each seed's
    total must equal the committed pnl_usd; the series is the seed mean (and p10 / p90) of the cumulative P&L."""
    import warnings
    import pandas as pd
    warnings.filterwarnings("ignore")
    sys.argv = [sys.argv[0]]
    from scripts import tier0_latency_sweep as S
    from src import tier0 as T
    ref = pd.read_csv("results/tier0/latency_sweep_seeds.csv")
    c = S.ctx()
    rows, checks = [], []
    for rd in ("tournament_lagcal", "tournament"):
        for per in ("IS", "burned_OOS"):
            cum = []
            for seed in range(S.SEEDS):
                sc, cvs = S.cell("video", rd, 1.0, "own120", c)
                P = c["per"][per]
                dr = T.draws(len(P["J"]), P["seed"] + seed, max(c["n_tour"], 1))
                calls = T.simulate(P["J"], P["M"], sc, dr, c["pools"], cvs, c["mix"])
                days = T.period_days(P["J"], sc.regime)
                tr = calls[calls.shares > 1e-9]
                daily = tr.groupby("date").pnl.sum().reindex(days, fill_value=0.0)
                r = ref[(ref.source == "video") & (ref.reading == rd) & (ref.x_s == 1.0) & (ref.cv == "own120")
                        & (ref.period == per) & (ref.seed == seed)]
                want = float(r.pnl_usd.iloc[0])
                got = float(daily.sum())
                checks.append(dict(reading=rd, period=per, seed=seed, committed_pnl_usd=want, rerun_pnl_usd=got,
                                   match=abs(got - want) <= 1e-3))
                cum.append(daily.cumsum().to_numpy())
            M = np.vstack(cum)
            for i, d in enumerate(days):
                rows.append(dict(date=str(d.date()), reading=rd, period=per, cum_usd_mean=float(M[:, i].mean()),
                                 cum_usd_p10=float(np.percentile(M[:, i], 10)),
                                 cum_usd_p90=float(np.percentile(M[:, i], 90))))
    pd.DataFrame(rows).to_csv(EQUITY, index=False, float_format="%.4f")
    ok = all(x["match"] for x in checks)
    EQUITY_CHECK.write_text(json.dumps(dict(
        what="daily paper P&L of the committed latency-sweep cells at V = 1 s (scripts/tier0_latency_sweep.py "
             "cell() + src/tier0.simulate, unchanged), seed mean / p10 / p90 of the cumulative P&L",
        label=LABEL_RESULTS, all_seed_totals_match_committed=ok, n=len(checks),
        max_abs_diff_usd=max(abs(x["rerun_pnl_usd"] - x["committed_pnl_usd"]) for x in checks),
        reference="results/tier0/latency_sweep_seeds.csv", reference_sha256=sha("results/tier0/latency_sweep_seeds.csv"),
        checks=checks), indent=1))
    print(f"equity_1s: {len(checks)} seed cells, all totals match committed: {ok}")
    if not ok:
        raise SystemExit("equity re-run does not reproduce the committed sweep; not drawing it")


# ====================================================================================================
# 6. animated plates for the other segments (v2 drawing system, fixed timings, no narration)
# ====================================================================================================
MX = 120


class FnO(v2.Fn):
    """v2.Fn drawn on a transparent layer, then alpha-composited (ImageDraw on an RGBA frame replaces alpha)."""

    def draw(self, im, t):
        k = self.vis(t)
        if k > 0.004:
            ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
            self.fn(ov, t, k)
            im.alpha_composite(ov)


class GVid(v2.Vid):
    """v2.Vid that stays invisible before t_show (its paused first frame shows from t_show to t0)."""

    def __init__(self, *a, t_show=0.0, **kw):
        super().__init__(*a, **kw)
        self.t_show = t_show

    def draw(self, im, t):
        if t >= self.t_show:
            super().draw(im, t)


class Seg(v2.Scene):
    def __init__(self, sid, dur, labels=()):    # noqa: D107  (no narration lines; fixed timings)
        self.id = self.key = sid
        self.title, self.hold, self.labels = "", 0.0, list(labels)
        self.lines, self.els, self.sfx = [], [], []
        self.full_bleed, self.start, self.dur, self.index = False, 0.0, dur, 0
        self._cache, self._cache_t = None, None


def header(S, kicker, title, t0=0.05):
    S.add(v2.Txt((MX, 58), kicker.upper(), 19, "demi", ORANGE, spacing=3.2, t0=t0, slide=-18, rise=0),
          v2.Txt((MX, 88), title, 46, "demi", INK, t0=t0 + 0.1, slide=-24, rise=0))
    if S.labels:
        v2.label_chips(S, top=50)


def write_seg(S, name, R):
    path = ASSETS / f"seg_{name}.mp4"
    n = int(round(S.dur * FPS))
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)
    last = None
    for i in range(n):
        last = S.render(i / FPS)
        enc.stdin.write(last.convert("RGB").tobytes())
    enc.stdin.close()
    enc.wait()
    S.close()
    last.convert("RGB").save(ASSETS / f"seg_{name}.png")
    print(f"  seg_{name}.mp4  {S.dur:.1f} s  {path.stat().st_size / 1e6:.1f} MB")
    return dict(file=str(path), still=str(ASSETS / f"seg_{name}.png"), duration_s=S.dur, labels=S.labels)


def pill(s, size=18, fill=INK, plate=PANEL, outline=GRID, w="demi"):
    return spr(s, size, w, fill, plate=(plate, 235), outline=(outline, 255), pad=(16, 8), r=10)


# ---------------- cold open: one real MISS call, slow motion, title ----------------
def seg_coldopen(R, L, dry=False):
    sel = jload(SELECTION)
    x = next(c for c in sel["chosen"] if c["video"] == "test_2" and c["frame"] == 2819)
    fl = load_flights()
    xx = dict(x, miss_type=(fl.get((x["video"], x["f_net"])) or {}).get("miss_type"),
              clip_src_frames=[2776, x["clip_src_frames"][1]])
    clip = CLIPS / "coldopen_test_2_f2819_miss.mp4"
    cj = CLIPS / "coldopen_test_2_f2819_miss.json"
    if dry and cj.exists():
        info = {k: v for k, v in jload(cj).items() if k not in ("id", "event", "label", "note")}
    else:
        info = render_clip(xx, L, clip, slow_all=True)
    side = json.loads(json.dumps(dict(id="coldopen_test_2_f2819_miss", event=xx, label=LABEL_FOOT,
                                      note="window starts at frame 2776, after the engine's previous call (frame 2766), so "
                                           "no call in the window is left unstamped; 1/4 speed until 14 frames after "
                                           "the outcome", **info),
                                 default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    (CLIPS / "coldopen_test_2_f2819_miss.json").write_text(json.dumps(side, indent=1))
    dur_clip = info["duration_s"]
    S = Seg("coldopen", round(dur_clip + 1.3, 2))
    S.add(v2.Vid(clip, (0, 0, W, H), t0=0.0, pre=True, kb_hold=1.4, fin=0.01))

    def dim(im, t, k):
        a = int(150 * k)
        im.alpha_composite(Image.new("RGBA", (W, H), C(BG, a)))
    tT = dur_clip - 0.15
    S.add(FnO(dim, t0=tT, fin=0.5))
    S.add(v2.Txt((W / 2, H / 2 - 40), "COURTSIDE", 168, "heavy", INK, "mm", spacing=14, t0=tT + 0.1, rise=26),
          v2.Txt((W / 2, H / 2 + 80), f"MISS called {f0(x['lead_ms'])} ms early · real held-out footage · the engine's own call",
                 30, "demi", AMBER, "mm", t0=tT + 0.45))
    R.put("cold_lead_ms", x["lead_ms"], str(OVO), f"runs.{RUN}.flights_called_or_miss[test_2, f_net 2819]: "
          "(t_ref - engine_miss_frame) / 120 fps × 1000", fmt=f0,
          note="the streaming engine's own call; the offline evaluation's first-call lead for this flight is 408.3 ms "
               "(results/tracking/demo/manifest.json), a different run")
    R.scene = "coldopen"
    R.v("cold_lead_ms")
    return S, side


# ---------------- strategy in one sentence ----------------
def seg_strategy(R):
    S = Seg("strategy", 7.0)
    words = ("Our computer vision calls the point before the ball lands, so we trade the Polymarket match price "
             "before it reprices.").split()
    hi = {2: ORANGE, 3: ORANGE, 4: ORANGE, 5: ORANGE, 6: ORANGE, 7: ORANGE, 8: ORANGE,
          16: BLUE, 17: BLUE, 18: BLUE}
    x0, y, lh, size = MX, 250, 96, 74
    x = x0
    f = v2.F(size, "heavy")
    for i, wd in enumerate(words):
        wpx = f.getlength(wd + " ")
        if x + wpx > W - MX:
            x, y = x0, y + lh
        S.add(v2.Txt((x, y), wd, size, "heavy", hi.get(i, INK), t0=0.25 + 0.15 * i, fin=0.3, rise=22))
        x += wpx
    band = R.get("results/e2e/summary.json", "reprice_reference", "band_s")
    R.put("reprice_band_s", band, "results/e2e/summary.json", "reprice_reference.band_s",
          fmt=lambda b: f"{fmt(b[0], 1, keep0=True)}–{fmt(b[1], 1, keep0=True)}",
          note="inference: the book reprices a median 1.16 s before the official stamp (measured, n = 482); the stamp "
               "lag after the physical point is not measured")
    R.scene = "strategy"
    t1 = 0.25 + 0.15 * len(words) + 0.2
    ax0, ax1, ay = MX + 40, W - MX - 40, 760
    sec = lambda s: ax0 + (ax1 - ax0) * (s + 0.6) / 2.4   # noqa: E731   axis -0.6 .. 1.8 s after the bounce

    def axis(im, t, k):
        d = ImageDraw.Draw(im, "RGBA")
        d.line((ax0, ay, ax1, ay), fill=C(GRID, int(255 * k)), width=4)
        if band:
            d.rectangle((sec(band[0]), ay - 46, sec(band[1]), ay + 46), fill=C(BLUE, int(90 * k)))
        for s_ in (0.0,):
            d.line((sec(s_), ay - 30, sec(s_), ay + 30), fill=C(INK, int(255 * k)), width=4)
    S.add(FnO(axis, t0=t1, fin=0.4))
    S.add(v2.Txt((sec(0.0), ay + 44), "ball lands", 26, "demi", INK, "ma", t0=t1 + 0.1))
    if band:
        S.add(v2.Txt((sec(sum(band) / 2), ay + 56), f"Polymarket reprices\n~{R.d('reprice_band_s')} s after the point "
                     f"(inferred)", 24, "demi", BLUE, "ma", align="m", t0=t1 + 0.6))

    def dot(im, t, k):
        p = ease_io((t - t1 - 0.5) / 1.1)
        X = sec(-0.45) + (sec(-0.12) - sec(-0.45)) * p
        d = ImageDraw.Draw(im, "RGBA")
        for r_, a in ((22, 50), (14, 120), (9, 255)):
            d.ellipse((X - r_, ay - r_, X + r_, ay + r_), fill=C(ORANGE, int(a * k)))
    S.add(FnO(dot, t0=t1 + 0.3, fin=0.3, live=True))
    S.add(v2.Txt((sec(-0.12) - 16, ay - 70), "our call", 28, "heavy", ORANGE, "ra", t0=t1 + 1.5))
    if band:
        def window(im, t, k):
            d = ImageDraw.Draw(im, "RGBA")
            xa, xb = sec(-0.12), sec(band[0])
            d.line((xa, ay - 120, xb, ay - 120), fill=C(INK2, int(220 * k)), width=3)
            for xx_ in (xa, xb):
                d.line((xx_, ay - 130, xx_, ay - 110), fill=C(INK2, int(220 * k)), width=3)
        S.add(FnO(window, t0=t1 + 1.9, fin=0.4),
              v2.Txt(((sec(-0.12) + sec(band[0])) / 2, ay - 172), "we trade in this window", 26, "demi", INK2, "ma",
                     t0=t1 + 2.0))
    return S


# ---------------- the edge: information-tier ladder + fast tier wins every month ----------------
def seg_edge(R):
    S = Seg("edge", 8.0, labels=["Polymarket tennis, public tapes; wallets' own fills (not our trades)"])
    header(S, "the edge exists", "Who learns the point first takes the stale price")
    R.scene = "edge"
    ssr = "results/home_stream/sub_second_routes.json"
    setka = next((r for r in (R.get(ssr, "routes") or []) if r.get("id") == "setka_flussonic_public"), {})
    R.put("setka_s", ((setka.get("latency") or {}).get("measured_s") or {}).get("lo"), ssr,
          "routes[id=setka_flussonic_public].latency.measured_s.lo (WebRTC/WHEP median, preliminary)", fmt=f1)
    lt = "research/v2/latency/results.json"
    R.put("espn_lag_s", -R.get(lt, "summary", "m1", "espn:game", "lead_vs_book_s", "median"), lt,
          "-summary.m1['espn:game'].lead_vs_book_s.median", fmt=f0)
    R.put("wta_lag_s", -R.get(lt, "summary", "m1", "wta:point", "lead_vs_book_s", "median"), lt,
          "-summary.m1['wta:point'].lead_vs_book_s.median", fmt=f0)
    rungs = [("Venue camera", "not allowed for trading", R.v("band_cam"), DIM),
             ("Licensed betting video", "vendor-stated", R.v("band_vid"), BLUE),
             ("Official point feed", "umpire tablet; lag not measured", R.v("band_feed"), SAND),
             ("TV broadcast", "cited surveys", R.v("band_tv"), GREY),
             ("Public match stream", f"we measured {R.d('setka_s')} s (preliminary)", [R.v("setka_s"), R.v("setka_s")],
              CORAL),
             ("Public score feeds", f"measured: ESPN {R.d('espn_lag_s')} s, WTA {R.d('wta_lag_s')} s late",
              [R.v("espn_lag_s"), R.v("wta_lag_s")], CORAL)]
    lx0, lx1, ly0 = MX + 10, 900, 236
    lo, hi = math.log10(0.03), math.log10(60)
    LX = lambda s: lx0 + (lx1 - lx0) * (math.log10(max(s, 0.03)) - lo) / (hi - lo)  # noqa: E731
    rh = 92
    band = R.v("reprice_band_s") if "reprice_band_s" in R.entries else R.get("results/e2e/summary.json",
                                                                              "reprice_reference", "band_s")

    def grid(im, t, k):
        d = ImageDraw.Draw(im, "RGBA")
        yb = ly0 + rh * len(rungs) + 4
        d.line((lx0, yb, lx1, yb), fill=C(GRID, int(255 * k)), width=2)
        for s_ in (0.05, 0.1, 0.5, 1, 5, 10, 60):
            d.line((LX(s_), ly0 - 6, LX(s_), yb), fill=C(GRID, int(110 * k)), width=1)
        if band:
            d.rectangle((LX(band[0]), ly0 - 10, LX(band[1]), yb), fill=C(ORANGE, int(70 * k)))
            d.line((LX(band[0]), ly0 - 10, LX(band[0]), yb), fill=C(ORANGE, int(255 * k)), width=2)
    S.add(FnO(grid, t0=0.3, fin=0.4))
    for s_, lab in ((0.05, "0.05"), (0.1, "0.1"), (0.5, "0.5"), (1, "1 s"), (5, "5"), (10, "10"), (60, "60 s")):
        S.add(v2.Txt((LX(s_), ly0 + rh * len(rungs) + 12), lab, 17, "medium", MUTED, "ma", t0=0.35))
    for i, (nm, sub, b, col) in enumerate(rungs):
        y = ly0 + i * rh
        tt = 0.5 + 0.28 * i
        S.add(v2.Txt((lx0, y), nm, 23, "demi", INK, t0=tt, slide=-14, rise=0),
              v2.Txt((lx0, y + 30), sub, 16, "medium", MUTED, t0=tt + 0.05, slide=-14, rise=0))
        if b and None not in b:
            def bar(im, t, k, b=b, y=y, col=col, tt=tt):
                p = ease((t - tt) / 0.5)
                xa, xb = LX(b[0]), LX(b[1])
                xb = xa + max(xb - xa, 14) * p
                ImageDraw.Draw(im, "RGBA").rounded_rectangle((xa, y + 56, max(xb, xa + 14), y + 72), radius=8,
                                                             fill=C(col, int(235 * k)))
            S.add(FnO(bar, t0=tt, fin=0.3, live=False))
    if band:
        S.add(v2.Txt((LX(band[1]) + 10, ly0 - 44), f"book reprices ~{R.d('reprice_band_s')} s after the point", 18,
                     "demi", ORANGE, t0=2.3))
    S.add(v2.Txt((lx0, ly0 + rh * len(rungs) + 46), "seconds after the point is over (log scale)", 16, "medium",
                 MUTED, t0=0.4))
    # alpha chart (right)
    rows = R.v("ft_rows") or []
    bx, by, bw, bh = 990, 300, 810, 520
    allv = [r[k] for r in rows for k in ("fast_net30_c", "copy_3s_later_net_to_resolution_c")]
    ylo, yhi = (min(allv + [0]) - 0.5, max(allv + [0]) + 0.6) if allv else (-3, 3)
    n = len(rows)
    oos_i = next((i for i, r in enumerate(rows) if r["period"] == "OOS"), n)

    def setup(ax):
        ax.set_xlim(-0.6, max(n, 1) - 0.4)
        ax.set_ylim(ylo, yhi)
        ax.set_xticks(range(n))
        ax.set_xticklabels([dt.date.fromisoformat(r["month"] + "-01").strftime("%b\n%y") for r in rows], fontsize=13)
        ax.set_ylabel("¢ per share, after fees", fontsize=15)
        ax.axhline(0, color="#3a516b", lw=1.4)
        if oos_i < n:
            ax.axvspan(oos_i - 0.5, n - 0.4, color="#ffffff", alpha=0.04, lw=0)
            ax.text(oos_i - 0.4, yhi - 0.1, "out of sample", fontsize=13, color=MUTED, va="top")
    axes_img, _, to_px = v2.chart(bw, bh, (0.1, 0.14, 0.88, 0.82), setup, lambda ax: {})
    S.add(v2.Spr(axes_img, (bx, by), t0=2.4, rise=0))
    bars = {0: [], 1: []}
    bw_ = 0.34
    for i, r in enumerate(rows):
        for j, (k, col) in enumerate((("fast_net30_c", BLUE), ("copy_3s_later_net_to_resolution_c", CORAL))):
            xa, yb = to_px(i + (j - 0.5) * bw_ - bw_ / 2 + 0.03, 0)
            xb, yt = to_px(i + (j - 0.5) * bw_ + bw_ / 2 - 0.03, r[k])
            bars[j].append((bx + xa, bx + xb, by + yb, by + yt, col, 255 if r["period"] == "IS" else 170))
    S.add(v2.Bars(bars[0], t0=2.7, stagger=0.06), v2.Bars(bars[1], t0=4.4, stagger=0.06))
    S.add(v2.Num((bx + 70, 222), R.v("ft_pos"), lambda v: f"{f0(v)}/{R.d('ft_n')} months up", 36, "heavy", BLUE,
                 t0=3.3, dur=0.8),
          v2.Txt((bx + 72, 266), "fast tier: trades within 3 s of a point", 17, "demi", INK2, t0=3.4),
          v2.Num((bx + 450, 222), R.v("fol_neg"), lambda v: f"{f0(v)}/{R.d('ft_n')} months down", 36, "heavy", CORAL,
                 t0=5.0, dur=0.8),
          v2.Txt((bx + 452, 266), "copy them 3 s later", 17, "demi", INK2, t0=5.1))
    S.add(v2.Txt((bx + 70, by + bh + 8), f"factor-neutral alpha t = {R.d('fac_t')} (four-factor, Newey-West)", 18,
                 "demi", MUTED, t0=6.0))
    return S


# ---------------- proof: 2x2 grids of the engine's own calls + honest totals ----------------
def seg_proof(R):
    S = Seg("proof", 19.0)
    R.scene = "proof"
    sel = jload(SELECTION)
    by_id = {x["id"]: x for x in sel["chosen"]}
    ovo = jload(OVO)
    run_ = ovo["runs"][RUN]
    hd = ovo["headline"][RUN]
    P = R.put
    P("pf_games", len(run_["population"]["videos"]), str(OVO), f"len(runs.{RUN}.population.videos)", fmt=f0)
    P("pf_frames", run_["timing"]["frames"], str(OVO), f"runs.{RUN}.timing.frames", fmt=f0)
    P("pf_dropped", run_["timing"]["frames_dropped"], str(OVO), f"runs.{RUN}.timing.frames_dropped", fmt=f0)
    P("pf_video_s", run_["timing"]["video_seconds"], str(OVO), f"runs.{RUN}.timing.video_seconds", fmt=f0)
    em = run_["calls"]["emitted"]
    P("pf_calls", em["MISS"] + em["BOUNCE"], str(OVO), f"runs.{RUN}.calls.emitted.MISS + .BOUNCE", fmt=f0)
    P("pf_miss", em["MISS"], str(OVO), f"runs.{RUN}.calls.emitted.MISS", fmt=f0)
    P("pf_in", em["BOUNCE"], str(OVO), f"runs.{RUN}.calls.emitted.BOUNCE", fmt=f0)
    P("pf_lat", hd["stream"]["after_startup"]["emitted_call_latency_ms"]["p50"], str(OVO),
      f"headline.{RUN}.stream.after_startup.emitted_call_latency_ms.p50", fmt=f1)
    c = run_["calls"]
    P("pf_miss_on_bounce", c["miss_calls_on_BOUNCE_flights"], str(OVO), f"runs.{RUN}.calls.miss_calls_on_BOUNCE_flights",
      fmt=f0)
    P("pf_miss_on_miss", c["miss_calls_on_MISS_flights"], str(OVO), f"runs.{RUN}.calls.miss_calls_on_MISS_flights", fmt=f0)
    P("pf_in_right", c["bounce_calls_on_BOUNCE_flights"], str(OVO), f"runs.{RUN}.calls.bounce_calls_on_BOUNCE_flights",
      fmt=f0)
    P("pf_in_matched", c["bounce_calls_on_BOUNCE_flights"] + c["bounce_calls_on_MISS_flights"], str(OVO),
      f"runs.{RUN}.calls.bounce_calls_on_BOUNCE_flights + .bounce_calls_on_MISS_flights", fmt=f0)
    P("pf_in_prec", c["bounce_call_precision"] * 100, str(OVO), f"runs.{RUN}.calls.bounce_call_precision × 100", fmt=f0)
    a0 = run_["A_engine_calls"]["online"]["0ms"]
    P("pf_recall_tp", a0["tp"], str(OVO), f"runs.{RUN}.A_engine_calls.online['0ms'].tp", fmt=f0)
    P("pf_recall_fp", a0["fp"], str(OVO), f"runs.{RUN}.A_engine_calls.online['0ms'].fp", fmt=f0)
    P("pf_n_miss_flights", run_["population"]["MISS"], str(OVO), f"runs.{RUN}.population.MISS", fmt=f0)
    P("pf_unmatched", c["unmatched"]["MISS"] + c["unmatched"]["BOUNCE"], str(OVO),
      f"runs.{RUN}.calls.unmatched.MISS + .BOUNCE", fmt=f0)
    P("pf_unmatched_miss", c["unmatched"]["MISS"], str(OVO), f"runs.{RUN}.calls.unmatched.MISS", fmt=f0)
    P("pf_flights", run_["population"]["flights"], str(OVO), f"runs.{RUN}.population.flights", fmt=f0)
    assert R.v("pf_calls") == sum(1 for ln in EVENTS.read_text().splitlines() if ln.strip())
    cw, ch, gap = 848, 477, 10
    gx = (W - 2 * cw - gap) // 2
    pos = [(gx, 10), (gx + cw + gap, 10), (gx, 10 + ch + gap), (gx + cw + gap, 10 + ch + gap)]
    grids = [(0.0, 9.6, ["test_4_f9837_miss", "test_1_f313_bounce", "test_3_f3442_bounce", "test_4_f5751_miss"]),
             (9.6, 19.0, ["test_5_f4099_bounce", "test_6_f9190_bounce", "test_7_f7145_bounce", "test_2_f2819_miss"])]
    inp = 0.4
    plan = []
    for g0, g1, ids in grids:
        for i, cid in enumerate(ids):
            side = jload(CLIPS / f"{cid}.json")
            st = g0 + 0.15 + 1.2 * i
            el = GVid(CLIPS / f"{cid}_cell.mp4", (*pos[i], cw, ch), src_start=inp, t0=st, t1=g1 - 0.05, pre=True,
                      fin=0.25, fout=0.05, border=GRID, t_show=g0)
            S.add(el)
            plan.append(dict(id=cid, cell=i, grid_start=g0, play_from=st, clip_in_s=inp,
                             stamp_at=round(st + side["call_out_t"] - inp, 3),
                             call=by_id[cid]["call"], lead_ms=by_id[cid]["lead_ms"]))
    def flash(im, t, k):
        a = max(0.0, 1.0 - abs(t - 9.6) / 0.18)
        if a > 0:
            im.alpha_composite(Image.new("RGBA", (W, H), C(INK, int(150 * a))))
    S.add(v2.Fn(flash, t0=9.35, t1=9.85, fin=0.01, fout=0.01, live=True))
    # titles over each grid
    for g0, title in ((0.0, "7 HELD-OUT GAMES · THE ENGINE'S OWN CALLS"), (9.6, "EVERY CALL COUNTED, RIGHT OR WRONG")):
        t = tsprite(title, 44, "heavy", INK, spacing=2)
        pl = rr((t.size[0] + 60, t.size[1] + 26), 16, C(BG, 228), C(ORANGE, 255), 3)
        pl.alpha_composite(t, (30, 13))
        S.add(v2.Spr(pl, (W / 2, H / 2 - 40), "mm", t0=g0 + 0.05, t1=g0 + 1.5, fin=0.2, fout=0.3, rise=10))
    # counter strip
    sy = 10 + 2 * ch + gap + 8

    def strip(t0, t1, items):
        x = gx
        wcol = (2 * cw + gap) / len(items)
        S.add(v2.Spr(rr((2 * cw + gap, H - sy - 8), 12, C(PANEL, 245), C(GRID, 255), 1), (gx, sy), t0=t0, t1=t1,
                     rise=0, fin=0.2, fout=0.2))
        for i, (val, f, lab, col) in enumerate(items):
            xx = x + i * wcol + 22
            S.add(v2.Num((xx, sy + 4), val, f, 36, "heavy", col, t0=t0 + 0.1 + 0.15 * i, t1=t1, dur=t1 - t0 - 2.2,
                         fin=0.2, fout=0.2),
                  v2.Txt((xx + 2, sy + 47), lab, 15, "demi", MUTED, t0=t0 + 0.15 + 0.15 * i, t1=t1, fin=0.2, fout=0.2,
                         maxw=wcol - 30, lh=1.15))
    strip(0.0, 9.6, [
        (R.v("pf_games"), lambda v: f"{f0(v)}", f"held-out games · {R.d('pf_video_s')} s of video", INK),
        (R.v("pf_frames"), lambda v: f"{f0(v)}", f"frames at 120 fps, real time · {R.d('pf_dropped')} dropped", INK),
        (R.v("pf_calls"), lambda v: f"{f0(v)}", f"calls emitted · {R.d('pf_miss')} MISS · {R.d('pf_in')} IN", ORANGE),
        (R.v("pf_lat"), lambda v: f"{f1(v)} ms", "frame to call, p50 (NVIDIA L4)", INK)])
    strip(9.6, 19.0, [
        (R.v("pf_miss_on_bounce"), lambda v: f"{f0(v)}",
         f"MISS calls on a labelled bounce ({R.d('pf_miss_on_miss')} on labelled misses, "
         f"{R.d('pf_unmatched_miss')} on unlabelled balls)", GREEN),
        (R.v("pf_in_right"), lambda v: f"{f0(v)} / {R.d('pf_in_matched')}",
         f"IN calls right on labelled flights ({R.d('pf_in_prec')}%)", INK),
        (R.v("pf_recall_tp"), lambda v: f"{f0(v)} / {R.d('pf_n_miss_flights')}",
         "labelled misses called before the outcome", AMBER),
        (R.v("pf_unmatched"), lambda v: f"{f0(v)}", f"calls on balls outside the {R.d('pf_flights')} labelled flights",
         MUTED)])
    return S, plan


# ---------------- spin flash (tennis, simulated physics) ----------------
def seg_spin(R):
    S = Seg("spin", 3.0, labels=[LABEL_SIM])
    R.scene = "spin"
    S.add(v2.Txt((MX, 58), "SPIN MODEL · TENNIS", 19, "demi", ORANGE, spacing=3.2, t0=0.0, rise=0),
          v2.Txt((MX, 88), "Spin-aware trajectory vs no-spin baseline", 44, "demi", INK, t0=0.05, rise=0))
    v2.label_chips(S, top=50)
    cur = R.v("tennis_curves") or {}
    if cur:
        leads = sorted(int(k) for k in cur["baseline"])
        allv = [cur[m][str(L_)] for m in ("baseline", "bls") for L_ in leads]

        def setup(ax):
            ax.set_xlim(0, max(leads))
            ax.set_ylim(0, max(allv) * 1.12)
            ax.set_xlabel("prediction lead before the bounce (ms)", fontsize=16)
            ax.set_ylabel("landing error, cm (sd)", fontsize=16)

        def plot(ax):
            a = ax.plot(leads, [cur["baseline"][str(L_)] for L_ in leads], color=GREY, lw=4)
            b = ax.plot(leads, [cur["bls"][str(L_)] for L_ in leads], color=ORANGE, lw=5)
            return {"base": a, "spin": b}
        img, lay, tp = v2.chart(1040, 640, (0.1, 0.14, 0.86, 0.8), setup, plot)
        S.add(v2.Spr(img, (MX, 230), t0=0.05, rise=0, fin=0.2))
        xf = tp(0, 0)[0]
        S.add(v2.Wipe(lay["base"], (MX, 230), dur=0.9, x_from=xf, t0=0.15, fin=0.01),
              v2.Wipe(lay["spin"], (MX, 230), dur=0.9, x_from=xf, t0=0.35, fin=0.01,
                      heads=[[tp(L_, cur["bls"][str(L_)]) for L_ in leads]]))
        S.add(v2.Txt((MX + 860, 300), "no-spin baseline", 20, "demi", GREY, "ra", t0=0.6),
              v2.Txt((MX + 860, 760), "spin model", 20, "demi", ORANGE, "ra", t0=0.8))
    S.add(v2.Txt((1260, 330), f"{R.d('spin_x_lo')}–{R.d('spin_x_hi')}×", 150, "heavy", ORANGE, t0=1.2, rise=30),
          v2.Txt((1266, 520), "less landing error\n300–400 ms before the bounce", 30, "demi", INK, lh=1.3, t0=1.4),
          v2.Txt((1266, 640), f"spin read to within {R.d('spin_rpm')} rpm (median, 200 ms lead)", 22, "medium", INK2, t0=1.6))
    return S


# ---------------- pipeline with measured ms ----------------
def seg_pipeline(R):
    e2 = "results/e2e/summary.json"
    S = Seg("pipeline", 10.0, labels=["paper: order built, never signed or sent; 1 s feed simulated"])
    header(S, "the pipeline", "From the frame to a fill, every stage measured")
    R.scene = "pipeline"
    st = {s["stage"]: s["ms"]["p50"] for s in (R.get(e2, "stage_ms") or [])}

    def sk(name):
        return f"stage_ms[stage='{name}'].ms.p50"
    P = R.put
    P("pp_feed", R.get(e2, "budget_with_1s_simulated_feed", "feed_simulated_ms"), e2,
      "budget_with_1s_simulated_feed.feed_simulated_ms", fmt=f0, note="simulated: licensed feed not purchased")
    P("pp_video", R.get(e2, "spans_ms", "capture_to_decoded", "p50"), e2, "spans_ms.capture_to_decoded.p50", fmt=f1)
    P("pp_cv_l4", R.get(e2, "production_gpu_reference", "online_vs_offline", "emitted_call_latency_ms", "p50"), e2,
      "production_gpu_reference.online_vs_offline.emitted_call_latency_ms.p50", fmt=f1)
    P("pp_cv_laptop", R.get(e2, "spans_ms", "decoded_to_call", "p50"), e2, "spans_ms.decoded_to_call.p50", fmt=f1)
    P("pp_fair", st.get("strategy rule (fair value, edge)"), e2, sk("strategy rule (fair value, edge)"), fmt=f2)
    P("pp_risk", st.get("risk check"), e2, sk("risk check"), fmt=f2)
    P("pp_order", st.get("unsigned order built"), e2, sk("unsigned order built"), fmt=f2)
    P("pp_net", st.get("network one-way (RTT/2)"), e2, sk("network one-way (RTT/2)"), fmt=f1)
    P("pp_venue", st.get("venue order delay (secondsDelay)"), e2, sk("venue order delay (secondsDelay)"), fmt=f0)
    P("pp_total", R.get(e2, "budget_with_1s_simulated_feed", "total_ms", "p50"), e2,
      "budget_with_1s_simulated_feed.total_ms.p50", fmt=f0)
    P("pp_total_l4", R.get(e2, "budget_with_1s_simulated_feed", "with_l4_vision", "total_ms"), e2,
      "budget_with_1s_simulated_feed.with_l4_vision.total_ms", fmt=f0)
    P("pp_req", R.get(e2, "budget_with_1s_simulated_feed", "requirement_ms"), e2,
      "budget_with_1s_simulated_feed.requirement_ms", fmt=f0)
    P("pp_n", R.get(e2, "counts", "complete_order_traces"), e2, "counts.complete_order_traces", fmt=f0)
    P("pp_calls", R.get(e2, "counts", "calls"), e2, "counts.calls", fmt=f0)
    fp = R.get(e2, "fills", "timing_probe") or {}
    P("pp_filled", (fp.get("status") or {}).get("filled"), e2, "fills.timing_probe.status.filled", fmt=f0)
    boxes = [("Licensed feed", "pp_feed", "simulated, 1 s", AMBER),
             ("WebRTC in + decode", "pp_video", "measured", BLUE),
             ("GPU vision call", "pp_cv_l4", f"NVIDIA L4 (laptop run {R.d('pp_cv_laptop')} ms)", ORANGE),
             ("Fair value", "pp_fair", "point-leverage model", BLUE),
             ("Risk checks", "pp_risk", "limits, kill switch", BLUE),
             ("Order built", "pp_order", "unsigned, paper", BLUE),
             ("Network", "pp_net", "measured RTT/2", BLUE),
             ("Polymarket delay", "pp_venue", "venue's taker delay", AMBER),
             ("Fill vs live book", None, f"{R.d('pp_filled')}/{R.d('pp_n')} filled (paper)", GREEN)]
    bw, bh, gx = 300, 150, 45
    row1 = [(MX + i * (bw + gx), 250) for i in range(5)]
    row2 = [(MX + (4 - i) * (bw + gx), 500) for i in range(4)]
    xy = row1 + row2
    T0 = 0.5
    centers = []
    for i, ((nm, key, sub, col), (x, y)) in enumerate(zip(boxes, xy)):
        tt = T0 + 0.42 * i
        for e in v2.card((x, y, x + bw, y + bh), None, t0=tt, accent=col):
            S.add(e)
        S.add(v2.Txt((x + 26, y + 18), nm, 22, "demi", INK, t0=tt + 0.05))
        if key:
            val = R.v(key)
            fm = (lambda v: f"{f0(v)} ms") if (val or 0) >= 100 else ((lambda v: f"{f1(v)} ms") if (val or 0) >= 1
                                                                       else (lambda v: f"{f2(v)} ms"))
            S.add(v2.Num((x + 24, y + 50), val, fm, 46, "heavy", col, t0=tt + 0.1, dur=0.6))
        else:
            S.add(v2.Txt((x + 24, y + 56), "paper fill", 40, "heavy", col, t0=tt + 0.1))
        S.add(v2.Txt((x + 26, y + 110), sub, 15, "medium", MUTED, t0=tt + 0.15, maxw=bw - 40))
        centers.append((x + bw / 2, y + bh / 2))

    def links(im, t, k):
        d = ImageDraw.Draw(im, "RGBA")
        for i in range(len(centers) - 1):
            tt = T0 + 0.42 * (i + 1)
            p = ease((t - tt) / 0.3)
            if p <= 0:
                continue
            (x0, y0), (x1, y1) = centers[i], centers[i + 1]
            if y0 == y1:
                xa, xb = (x0 + bw / 2, x1 - bw / 2) if x1 > x0 else (x0 - bw / 2, x1 + bw / 2)
                d.line((xa, y0, xa + (xb - xa) * p, y0), fill=C(MUTED, int(255 * k)), width=3)
            else:
                d.line((x0, y0 + bh / 2, x0, y0 + bh / 2 + (y1 - y0 - bh) * p), fill=C(MUTED, int(255 * k)), width=3)
        # travelling packet
        tp_ = (t - T0 - 0.42 * len(centers)) / 2.2
        if 0 <= tp_ <= 1:
            seg_f = tp_ * (len(centers) - 1)
            j = min(int(seg_f), len(centers) - 2)
            u = seg_f - j
            X = centers[j][0] + (centers[j + 1][0] - centers[j][0]) * u
            Y = centers[j][1] + (centers[j + 1][1] - centers[j][1]) * u
            for r_, a in ((18, 50), (11, 140), (6, 255)):
                d.ellipse((X - r_, Y - r_, X + r_, Y + r_), fill=C(ORANGE, int(a * k)))
    S.add(FnO(links, t0=T0, fin=0.2, live=True))
    # total bar vs the 3 s requirement
    tb = T0 + 0.42 * len(boxes) + 0.2
    req = R.v("pp_req") or 3000
    tot = R.v("pp_total") or 0
    bx0, bx1, by = MX, W - MX, 800
    ours = tot - (R.v("pp_feed") or 0) - (R.v("pp_net") or 0) - (R.v("pp_venue") or 0)
    R.put("pp_ours", ours, "results/e2e/summary.json", "budget total_ms.p50 - feed - network - venue (derived)", fmt=f0)
    parts = [(R.v("pp_feed") or 0, AMBER, "feed 1 s"), (ours, ORANGE, ""), (R.v("pp_net") or 0, BLUE, ""),
             (R.v("pp_venue") or 0, AMBER, "venue 1 s")]
    XS = lambda ms: bx0 + (bx1 - bx0) * ms / req  # noqa: E731

    def total(im, t, k):
        d = ImageDraw.Draw(im, "RGBA")
        p = ease_io((t - tb) / 1.2)
        d.rounded_rectangle((bx0, by, bx1, by + 48), radius=10, fill=C(PANEL2, int(255 * k)))
        acc, xe_all = 0.0, XS(tot * p)
        for ms, col, _ in parts:
            xa, xb = XS(acc), min(XS(acc + ms), xe_all)
            if xb > xa:
                d.rectangle((xa, by, xb, by + 48), fill=C(col, int(240 * k)))
            acc += ms
        d.line((bx1, by - 18, bx1, by + 66), fill=C(INK, int(255 * k)), width=4)
    S.add(FnO(total, t0=tb, fin=0.3, live=True))
    acc = 0.0
    for ms, col, lab in parts:
        if lab:
            S.add(v2.Txt((XS(acc + ms / 2), by + 24), lab, 20, "heavy", BG, "mm", t0=tb + 1.1, rise=0))
        acc += ms
    S.add(v2.Txt((bx1, by + 72), f"{f0(req / 1000)} s requirement", 20, "demi", INK, "ra", t0=tb),
          v2.Txt((bx0, by + 72), f"feed + ours + network + venue · p50 of {R.d('pp_n')} complete order traces "
                 f"({R.d('pp_calls')} calls)", 17, "medium", MUTED, t0=tb + 0.2))
    S.add(v2.Num((XS(tot), by - 14), tot, lambda v: f"{f0(v)} ms", 66, "heavy", GREEN, "rb", t0=tb + 0.4, dur=1.0),
          v2.Txt((XS(tot) + 18, by - 58), f"inside the 3 s limit\n{R.d('pp_total_l4')} ms with L4 vision", 19, "demi",
                 INK2, lh=1.3, t0=tb + 1.2))
    return S


# ---------------- what speed is worth: returns vs feed latency (draw-in) ----------------
def seg_latency(R):
    S = Seg("latency", 7.0, labels=[LABEL_RESULTS, "assumed data: licensed feed / video not purchased"])
    header(S, "what speed is worth", "Paper P&L vs how late the video reaches us")
    R.scene = "latency"
    vo = R.v("sweep_curves") or {}
    cx, cy, cw, ch = MX - 10, 214, 1700, 700
    pos = lambda d: {float(k): v for k, v in d.items() if float(k) > 0}  # noqa: E731
    sel = {"tournament_lagcal": (ORANGE, "calibrated reading (stamp lag 3.14 s, inferred)"),
           "tournament": (SAND, "pre-registered reading (stamp lag 2.0 s)")}
    ally = [vo[r][k][p]["usd_per_day_seed_ci95"][i] for r in sel if r in vo for k in vo[r] for p in ("IS", "burned_OOS")
            for i in (0, 1) if float(k) > 0]
    ylo, yhi = (min(ally + [0]) - 10, max(ally) + 30) if ally else (-50, 250)
    bands = [("band_vid", "licensed betting video", BLUE), ("band_feed", "official feed", SAND),
             ("band_tv", "TV", GREY), ("band_stream", "public streams", GREY)]

    def setup(ax):
        ax.set_xscale("log")
        ax.set_xlim(0.05, 60)
        ax.set_ylim(ylo, yhi)
        ax.set_xticks([0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 60])
        ax.set_xticklabels(["0.05", "0.1", "0.25", "0.5", "1", "2", "3", "5", "10", "20", "60"], fontsize=15)
        ax.set_xlabel("feed delay: seconds from the bounce until our CV sees it (log)", fontsize=16)
        ax.set_ylabel("paper P&L, $ per day", fontsize=16)
        ax.axhline(0, color="#3a516b", lw=1.6)

    def plot(ax):
        out = {"bands": [], "ci": [], "is": [], "oos": []}
        for i, (nm, lab, col) in enumerate(bands):
            b = R.v(nm)
            if not b:
                continue
            yb = yhi - (i + 0.8) * (yhi - ylo) * 0.07
            out["bands"] += ax.plot([max(b[0], 0.05), b[1]], [yb, yb], color=col, lw=9, alpha=0.55,
                                    solid_capstyle="butt")
            out["bands"].append(ax.text(min(b[1], 60) * 1.06 if b[1] < 30 else max(b[0], 0.05) / 1.06, yb,
                                        f"{lab} {b[0]:g}–{b[1]:g} s", fontsize=12.5, color=INK2, va="center",
                                        ha="left" if b[1] < 30 else "right"))
        for r, (col, _) in sel.items():
            if r not in vo:
                continue
            d = pos(vo[r])
            xs = sorted(d)
            lo_ = [d[x]["IS"]["usd_per_day_seed_ci95"][0] for x in xs]
            hi_ = [d[x]["IS"]["usd_per_day_seed_ci95"][1] for x in xs]
            out["ci"].append(ax.fill_between(xs, lo_, hi_, color=col, alpha=0.13, lw=0))
            out["is"] += ax.plot(xs, [d[x]["IS"]["usd_per_day"] for x in xs], color=col, lw=4.2)
            out["oos"] += ax.plot(xs, [d[x]["burned_OOS"]["usd_per_day"] for x in xs], color=col, lw=3,
                                  ls=(0, (4, 3)))
        return out
    ax_img, lay, tp = v2.chart(cw, ch, (0.07, 0.13, 0.91, 0.84), setup, plot)
    S.add(v2.Spr(ax_img, (cx, cy), t0=0.2, rise=0))
    S.add(v2.Spr(lay["bands"], (cx, cy), t0=0.6, rise=0, fin=0.6))
    xf = tp(0.05, 0)[0]
    S.add(v2.Wipe(lay["ci"], (cx, cy), t0=1.3, dur=1.8, x_from=xf, fin=0.01),
          v2.Wipe(lay["is"], (cx, cy), t0=1.3, dur=1.8, x_from=xf, fin=0.01,
                  heads=[[tp(x, pos(vo[r])[x]["IS"]["usd_per_day"]) for x in sorted(pos(vo[r]))] for r in sel if r in vo]),
          v2.Wipe(lay["oos"], (cx, cy), t0=1.9, dur=1.8, x_from=xf, fin=0.01))
    x1p = tp(1, 0)[0]

    def vline(im, t, k):
        d = ImageDraw.Draw(im, "RGBA")
        y = cy + tp(1, yhi)[1] + 4
        while y < cy + tp(1, ylo)[1]:
            d.line((cx + x1p, y, cx + x1p, y + 7), fill=C(INK, int(220 * k)), width=3)
            y += 14
        for r, (col, _) in sel.items():
            if r in vo and "1" in vo[r]:
                for p_, a in (("IS", 255), ("burned_OOS", 160)):
                    X, Y = tp(1, vo[r]["1"][p_]["usd_per_day"])
                    d.ellipse((cx + X - 9, cy + Y - 9, cx + X + 9, cy + Y + 9), fill=C(col, int(a * k)),
                              outline=C(INK, int(255 * k)), width=2)
    S.add(FnO(vline, t0=3.6, fin=0.4))
    S.add(v2.Txt((cx + x1p, cy - 8), "1 s licensed feed (simulated baseline)", 18, "demi", INK, "ma", t0=3.7))
    for nm, col, dy, who in (("be_t_is", SAND, 20, "pre-registered"), ("be_lc_is", ORANGE, 50, "calibrated")):
        v = R.v(nm)
        if v:
            X, Y = tp(v, 0)
            lab = tsprite(f"break-even {R.d(nm)} s ({who}, in sample)", 16, "demi", col)
            pl = rr((lab.size[0] + 14, lab.size[1] + 4), 6, C(BG, 225))
            pl.alpha_composite(lab, (7, 2))
            S.add(v2.Spr(rr((5, 24), 2, C(col)), (cx + X, cy + Y), "mm", t0=4.4, rise=0),
                  v2.Spr(pl, (cx + X - 4, cy + Y + dy), "la", t0=4.5, rise=0))
    ly = cy + ch + 4
    lx = cx + 120
    for r, (col, lab) in sel.items():
        S.add(v2.Spr(rr((30, 6), 3, C(col)), (lx, ly + 12), t0=1.4, rise=0),
              v2.Txt((lx + 40, ly), lab, 17, "demi", INK2, t0=1.4))
        lx += 60 + tsprite(lab, 17).size[0]
    S.add(v2.Txt((lx, ly), "solid: in sample · dashed: held out · shading: seed 95% band", 17, "medium", MUTED, t0=2.0))
    return S


# ---------------- edge decay panel (draw-in) ----------------
def seg_decay(R):
    S = Seg("decay", 5.0, labels=["Polymarket tennis prints; fast tier = walk-forward wallets (not our trades)"])
    header(S, "the edge decays", "Fast-tier markout vs seconds after the price move")
    R.scene = "decay"
    dc = "results/decay/decay.json"
    prim = R.get(dc, "tennis", "primary") or "IS+burned_OOS"
    cur = R.get(dc, "tennis", "subsets", prim, "curves") or {}
    bins = [b for b in (R.get(dc, "bins") or []) if b not in (R.get(dc, "empty_by_construction") or [])]
    ser = {k: [(b, (cur.get(k, {}).get("net30", {}).get(b) or {})) for b in bins] for k in ("fast", "others")}
    R.put("decay_fast", [(b, v.get("mean_c"), v.get("ci_c")) for b, v in ser["fast"]], dc,
          f"tennis.subsets['{prim}'].curves.fast.net30[bin].mean_c / ci_c (pre-registered bins, empty bins dropped)")
    R.put("decay_others", [(b, v.get("mean_c"), v.get("ci_c")) for b, v in ser["others"]], dc,
          f"tennis.subsets['{prim}'].curves.others.net30[bin].mean_c / ci_c")
    R.put("decay_matches", R.get(dc, "tennis", "subsets", prim, "matches"), dc, f"tennis.subsets['{prim}'].matches",
          fmt=f0)
    fast, oth = R.v("decay_fast"), R.v("decay_others")
    allv = [c for s in (fast, oth) for _, m, ci in s if ci for c in ci]
    ylo, yhi = min(allv + [0]) - 0.3, max(allv + [0]) + 0.4
    labs = [b.replace("-", "–") + " s" for b in bins]
    cx, cy, cw, ch = MX - 10, 214, 1220, 660

    def setup(ax):
        ax.set_xlim(-0.4, len(bins) - 0.6)
        ax.set_ylim(ylo, yhi)
        ax.set_xticks(range(len(bins)))
        ax.set_xticklabels(labs, fontsize=15)
        ax.set_xlabel("seconds since the price move (pre-registered bins)", fontsize=16)
        ax.set_ylabel("30 s markout after fees, ¢ per share", fontsize=16)
        ax.axhline(0, color="#3a516b", lw=1.6)

    def plot(ax):
        out = {"fast": [], "others": []}
        for nm, s, col in (("fast", fast, BLUE), ("others", oth, CORAL)):
            xs = list(range(len(s)))
            ys = [m for _, m, _ in s]
            out[nm] += ax.plot(xs, ys, color=col, lw=4, marker="o", ms=10)
            for i, (_, m, ci) in enumerate(s):
                if ci:
                    out[nm] += ax.plot([i, i], ci, color=col, lw=2.2, alpha=0.7)
        return out
    img, lay, tp = v2.chart(cw, ch, (0.11, 0.13, 0.86, 0.84), setup, plot)
    S.add(v2.Spr(img, (cx, cy), t0=0.2, rise=0))
    xf = tp(-0.4, 0)[0]
    S.add(v2.Wipe(lay["fast"], (cx, cy), t0=0.6, dur=1.6, x_from=xf, fin=0.01,
                  heads=[[tp(i, m) for i, (_, m, _) in enumerate(fast)]], head_col=BLUE),
          v2.Wipe(lay["others"], (cx, cy), t0=1.3, dur=1.6, x_from=xf, fin=0.01,
                  heads=[[tp(i, m) for i, (_, m, _) in enumerate(oth)]], head_col=CORAL))
    kx = 1370

    def big(y, val, tail, col, t0):
        S.add(v2.Txt((kx, y), v2.cents(val, 2), 58, "heavy", col, t0=t0),
              v2.Txt((kx + 230, y + 22), tail, 24, "demi", INK2, t0=t0 + 0.1))
    S.add(v2.Txt((kx, 250), "FAST TIER", 18, "demi", BLUE, spacing=2.4, t0=0.8))
    big(278, fast[0][1], f"at {labs[0]}", INK, 1.0)
    big(350, fast[1][1], f"at {labs[1]}", INK, 1.6)
    S.add(v2.Txt((kx, 450), "EVERYONE ELSE", 18, "demi", CORAL, spacing=2.4, t0=1.8))
    big(478, oth[0][1], f"at {labs[0]}", CORAL, 2.0)
    S.add(v2.Txt((kx, 580), f"{R.d('decay_matches')} matches · 30 s markout after fees\nmatch-clustered 95% CIs", 17,
                 "medium", MUTED, lh=1.35, t0=2.2))
    return S


# ---------------- the test: today's replay + rigor badges ----------------
def seg_replay(R):
    S = Seg("replay", 12.0, labels=[LABEL_REPLAY])
    header(S, "the test", "A real Polymarket match from today, replayed")
    R.scene = "replay"
    rpv = Path("results/replay/replay_match.mp4")
    if v2.mv.valid_mp4(rpv):
        dur = v2.clip_dur(rpv) or 0
        R.put("replay_video_s", dur, str(rpv), "ffprobe format.duration at render time", fmt=f1)
        S.add(v2.Vid(rpv, (MX, 214, 1152, 648), src_start=min(6.0, max(0.0, dur - 9.0)), t0=0.2, radius=14,
                     pre=True, border=GRID))
    rx = MX + 1152 + 40
    S.add(v2.Txt((rx, 220), R.d("rep_match"), 26, "demi", INK, maxw=W - MX - rx, t0=0.4),
          v2.Txt((rx, 262), f"recorded live {R.d('rep_date')} · real book, real points", 18, "medium", MUTED,
                 maxw=W - MX - rx, t0=0.5),
          v2.Txt((rx, 330), f"all {R.d('rep_n')} matches replayed today, 1 s feed", 18, "demi", INK2, t0=1.2),
          v2.Num((rx, 360), R.v("rep_v1_c"), lambda v: f"{fmt(v, 2, keep0=True)}¢", 64, "heavy",
                 CORAL if (R.v("rep_v1_c") or 0) < 0 else GREEN, t0=1.3, dur=0.9),
          v2.Txt((rx, 444), f"per share, 95% CI {R.d('rep_v1_ci')}¢", 18, "medium", INK2, t0=1.6),
          v2.Txt((rx, 480), f"{R.d('rep_beat_share')}% of calls beat the book's reprice", 18, "medium", INK2,
                 maxw=W - MX - rx, t0=1.8))
    # rigor strip
    rows = R.v("blind_rows") or []
    npass = sum(1 for r in rows if r[1] == "PASS")
    nfail = sum(1 for r in rows if r[1] == "FAIL")
    npend = sum(1 for r in rows if r[1] not in ("PASS", "FAIL"))
    R.put("blind_pass", npass, "several", "blind_rows verdict == PASS (see blind_rows)", fmt=f0)
    R.put("blind_fail", nfail, "several", "blind_rows verdict == FAIL", fmt=f0)
    R.put("blind_other", npend, "several", "blind_rows verdict neither (pending / P&L shown)", fmt=f0)
    badges = [("PRE-REGISTERED", f"{len(R.v('prereg_files') or [])} protocols committed before results"),
              ("BLIND TESTS", f"{npass} pass · {nfail} fail · {npend} other, all reported"),
              ("DEFLATED SHARPE", f"in sample {R.d('dsr_is')} · held out {R.d('dsr_oos')} ({R.d('n_trials')} trials)"),
              ("PEEKS LOGGED", f"{R.d('peeks')} looks at held-out data, each logged")]
    bw = (W - 2 * MX - 3 * 24) // 4
    for i, (k, v) in enumerate(badges):
        x = MX + i * (bw + 24)
        tt = 7.6 + 0.35 * i
        for e in v2.card((x, 900, x + bw, 1040), None, t0=tt, accent=ORANGE if i < 2 else BLUE):
            S.add(e)
        S.add(v2.Txt((x + 26, 918), k, 22, "heavy", INK, spacing=2, t0=tt + 0.05),
              v2.Txt((x + 26, 958), v, 17, "medium", INK2, maxw=bw - 46, lh=1.3, t0=tt + 0.1))
    return S


# ---------------- the profit: counters, equity curve, capacity ----------------
def seg_profit(R):
    S = Seg("profit", 10.0, labels=[LABEL_RESULTS, "paper trading only; licensed feed not purchased"])
    header(S, "the profit", "At a 1 s licensed feed, simulated")
    R.scene = "profit"
    cards = [("Calibrated reading", f"stamp lag {R.d('lc_lag')} s (inferred, post hoc)", ORANGE,
              [("in sample", "lc_is_day", "lc_is_sh"), ("held out", "lc_oos_day", "lc_oos_sh")]),
             ("Pre-registered reading", f"stamp lag {R.d('pre_lag')} s", SAND,
              [("in sample", "t_is_day", "t_is_sh"), ("held out", "t_oos_day", "t_oos_sh")])]
    for ci, (title, sub, col, rows) in enumerate(cards):
        x0 = MX + ci * 850
        for e in v2.card((x0, 214, x0 + 810, 470), None, t0=0.3 + 0.3 * ci, accent=col):
            S.add(e)
        S.add(v2.Txt((x0 + 30, 232), title, 26, "demi", col, t0=0.4 + 0.3 * ci),
              v2.Txt((x0 + 30, 270), sub, 16, "medium", MUTED, t0=0.45 + 0.3 * ci))
        for j, (lab, kd, ks) in enumerate(rows):
            xx = x0 + 30 + j * 390
            tt = 0.8 + 0.3 * ci + 0.25 * j
            S.add(v2.Txt((xx, 310), lab, 17, "demi", INK2, t0=tt),
                  v2.Num((xx - 4, 334), R.v(kd), lambda v: f"{usd(v)}/day", 58, "heavy", INK, t0=tt + 0.1, dur=1.4),
                  v2.Num((xx, 412), R.v(ks), lambda v: f"Sharpe {f1(v)}", 24, "demi", col, t0=tt + 0.2, dur=1.4))
    # equity
    import csv
    eq = list(csv.DictReader(open(EQUITY))) if EQUITY.exists() else []
    chk = jload(EQUITY_CHECK) if EQUITY_CHECK.exists() else {}
    if eq and chk.get("all_seed_totals_match_committed"):
        R.put("eq_rows", len(eq), str(EQUITY), "rows (date × reading × period), seed-mean cumulative P&L",
              note="re-run of the committed V = 1 s sweep cells; every seed total equals latency_sweep_seeds.csv "
                   "(equity_1s_check.json)")
        R.v("eq_rows")
        ser = {}
        for r in eq:
            ser.setdefault((r["reading"], r["period"]), []).append((dt.date.fromisoformat(r["date"]),
                                                                    float(r["cum_usd_mean"]),
                                                                    float(r["cum_usd_p10"]), float(r["cum_usd_p90"])))
        # chain held-out after in sample
        curves = {}
        for rd in ("tournament_lagcal", "tournament"):
            a = ser.get((rd, "IS"), [])
            b = ser.get((rd, "burned_OOS"), [])
            off = a[-1][1] if a else 0.0
            curves[rd] = (a, [(d, m + off, lo + off, hi + off) for d, m, lo, hi in b])
        allv = [v for rd in curves for part in curves[rd] for q in part for v in q[1:]]
        d0 = min(q[0] for rd in curves for part in curves[rd] for q in part)
        d1 = max(q[0] for rd in curves for part in curves[rd] for q in part)
        oos0 = min((q[0] for rd in curves for q in curves[rd][1]), default=None)
        cx, cy, cw, ch = MX - 10, 500, 1300, 470

        def setup(ax):
            import matplotlib.dates as mdates
            ax.set_xlim(d0, d1)
            ax.set_ylim(min(allv + [0]) * 1.1 - 50, max(allv) * 1.08)
            ax.set_ylabel("cumulative paper P&L, $", fontsize=15)
            ax.xaxis.set_major_locator(mdates.MonthLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
            ax.axhline(0, color="#3a516b", lw=1.4)
            if oos0:
                ax.axvspan(oos0, d1, color="#ffffff", alpha=0.04, lw=0)
                ax.text(oos0, max(allv) * 1.02, "  held out", fontsize=13, color=MUTED, va="top")

        def plot(ax):
            out = {"band": [], "line": []}
            for rd, col in (("tournament_lagcal", ORANGE), ("tournament", SAND)):
                for part, ls in zip(curves[rd], ("-", "-")):
                    if not part:
                        continue
                    ds = [q[0] for q in part]
                    out["band"].append(ax.fill_between(ds, [q[2] for q in part], [q[3] for q in part], color=col,
                                                       alpha=0.14, lw=0))
                    out["line"] += ax.plot(ds, [q[1] for q in part], color=col, lw=3.6, ls=ls)
            return out
        img, lay, tp = v2.chart(cw, ch, (0.1, 0.1, 0.88, 0.86), setup, plot)
        import matplotlib.dates as mdates
        S.add(v2.Spr(img, (cx, cy), t0=2.6, rise=0))
        xf = tp(mdates.date2num(d0), 0)[0]
        S.add(v2.Wipe(lay["band"], (cx, cy), t0=3.0, dur=3.0, x_from=xf, fin=0.01),
              v2.Wipe(lay["line"], (cx, cy), t0=3.0, dur=3.0, x_from=xf, fin=0.01))
        S.add(v2.Txt((cx + 110, cy + ch - 6), "mean of 20 seeds (band: p10–p90) · orange calibrated · sand "
                     "pre-registered", 15, "medium", MUTED, t0=3.2))
    else:
        R.put("eq_rows", None, str(EQUITY), "missing or not reproduced: equity curve not drawn")
    # capacity one-liner (results/capacity, if present)
    cp = "results/capacity/capacity.json"

    def cap(key):
        g = [x for x in (R.get(cp, "growth", key) or []) if x.get("growth") == 1.0]
        return g[0]["capital_where_sharpe_halves_usd"] / 1000 if g else None
    for nm, key in (("cap_lc_is", "lagcal|cov10|IS"), ("cap_lc_oos", "lagcal|cov10|burned_OOS"),
                    ("cap_pr_is", "prereg|cov10|IS"), ("cap_pr_oos", "prereg|cov10|burned_OOS")):
        R.put(nm, cap(key), cp, f"growth['{key}'][growth=1.0].capital_where_sharpe_halves_usd / 1000", fmt=f0,
              note="capital where the seed-mean Sharpe halves along the size path; 10 covered matches a day, "
                   "phi 0.5 (results/capacity paragraph)")
    kx = 1470
    S.add(v2.Txt((kx, 520), "CAPACITY", 18, "demi", MUTED, spacing=2.6, t0=5.0))
    if R.v("cap_lc_oos") is not None:
        S.add(v2.Txt((kx, 552), "Sharpe halves at", 20, "demi", INK2, t0=5.2),
              v2.Txt((kx, 582), f"${R.d('cap_lc_oos')}k–${R.d('cap_lc_is')}k", 50, "heavy", ORANGE, t0=5.3),
              v2.Txt((kx, 650), "of capital, calibrated\n(held out – in sample)", 18, "medium", INK2, lh=1.3, t0=5.4),
              v2.Txt((kx, 708), f"pre-registered: ${R.d('cap_pr_oos')}k–${R.d('cap_pr_is')}k", 18, "demi", SAND,
                     t0=5.6))
    else:
        S.add(v2.Txt((kx, 552), "capacity study pending", 24, "demi", AMBER, maxw=W - MX - kx, t0=5.2))
    S.add(v2.Txt((kx, 780), f"Fills simulated against recorded books; {R.d('lc_is_days')} in-sample and "
                 f"{R.d('lc_oos_days')} held-out days.", 16, "medium", MUTED, maxw=W - MX - kx, lh=1.35, t0=5.8))
    return S


# ---------------- end card ----------------
def seg_endcard(R):
    S = Seg("endcard", 4.0)
    R.scene = "endcard"
    S.add(v2.Txt((W / 2, 400), "COURTSIDE", 150, "heavy", INK, "mm", spacing=12, t0=0.1, rise=24),
          v2.Txt((W / 2, 520), R.d("repo_url"), 30, "demi", ORANGE, "mm", t0=0.4),
          v2.Txt((W / 2, 640), "Paper trading only · simulated 1 s licensed-feed baseline · Voice: AI (ElevenLabs)", 26,
                 "demi", INK2, "mm", t0=0.7),
          v2.Txt((W / 2, 690), "Footage: OpenTTGames held-out games, CC BY-NC-SA 4.0 (overlays added)", 22, "medium",
                 MUTED, "mm", t0=0.8))
    return S


# ====================================================================================================
# 7. manifest
# ====================================================================================================
def git_rev():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def write_manifest(R, assets, extra):
    def ser(v):
        try:
            json.dumps(v)
            return v
        except TypeError:
            return json.loads(json.dumps(v, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    used = {k: dict(value=ser(e["value"]), file=e["file"], key=e["key"], pending=e["value"] is None,
                    note=e.get("note"), used_in=e["used_in"],
                    shown=(e["fmt"](e["value"]) if callable(e.get("fmt")) and e["value"] is not None else None))
            for k, e in R.entries.items() if e["used_in"]}
    files = sorted({e["file"] for e in used.values() if e["file"] and Path(e["file"]).is_file()})
    mine = {"generated_utc", "git", "spec", "labels", "assets", "values", "input_files", *extra}
    keep = {k: v for k, v in (jload(MANIFEST).items() if MANIFEST.exists() else []) if k not in mine}
    m = dict(**keep, generated_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), git=git_rev(),
             spec="research/compliance/VIDEO_REQUIREMENTS.md (75-90 s table)",
             labels=dict(footage=LABEL_FOOT, replay=LABEL_REPLAY, results=LABEL_RESULTS, tennis=LABEL_SIM,
                         end_card=END_CARD),
             assets=assets, values=used, input_files={f: sha(f) for f in files}, **extra)
    MANIFEST.write_text(json.dumps(m, indent=1, default=str))
    print(f"manifest: {len(used)} values, {len(assets)} assets -> {MANIFEST}")


# ====================================================================================================
def segments(only=None, dry=False):
    R = v2.Reg()
    v2.build_values(R, dt.datetime.now(dt.timezone.utc))
    L = EngineLog()
    assets, extra = {}, {}
    builders = [("coldopen", lambda: seg_coldopen(R, L, dry)), ("strategy", lambda: seg_strategy(R)),
                ("edge", lambda: seg_edge(R)), ("proof", lambda: seg_proof(R)), ("spin", lambda: seg_spin(R)),
                ("pipeline", lambda: seg_pipeline(R)), ("latency", lambda: seg_latency(R)),
                ("decay", lambda: seg_decay(R)), ("replay", lambda: seg_replay(R)), ("profit", lambda: seg_profit(R)),
                ("endcard", lambda: seg_endcard(R))]
    if "reprice_band_s" not in R.entries:
        R.put("reprice_band_s", R.get("results/e2e/summary.json", "reprice_reference", "band_s"),
              "results/e2e/summary.json", "reprice_reference.band_s",
              fmt=lambda b: f"{fmt(b[0], 1, keep0=True)}–{fmt(b[1], 1, keep0=True)}")
    for name, fn in builders:
        if only and name not in only:
            continue
        out = fn()
        S, more = (out if isinstance(out, tuple) else (out, None))
        if dry:
            S.close()
            assets[f"seg_{name}"] = dict(file=str(ASSETS / f"seg_{name}.mp4"), still=str(ASSETS / f"seg_{name}.png"),
                                         duration_s=S.dur, labels=S.labels)
        else:
            assets[f"seg_{name}"] = write_seg(S, name, R)
        if more is not None:
            assets[f"seg_{name}"]["plan" if name == "proof" else "clip"] = more
    return R, L, assets, extra


def verify_fits(L):
    """re-derive the engine's fit at every logged decision frame inside every clip window; all must reproduce the
    logged score (the overlays draw an arc only on frames that do)."""
    c0 = dict(L.checked)
    for x in jload(SELECTION)["chosen"]:
        a, b = x["clip_src_frames"]
        tr = L.trace(x["video"])
        for t in range(a, b + 1):
            if t in tr:
                L.fit(x["video"], t)
    return {k: L.checked[k] - c0.get(k, 0) if k != "max_abs_dp" else L.checked[k] for k in L.checked}


# ====================================================================================================
# 8. tennis: one simulated shot through the spin-aware batch fit (bls), at every decision frame
# ====================================================================================================
TENNIS_DIR = ASSETS / "tennis_sim"
TENNIS_JSON = TENNIS_DIR / "shot.json"
TENNIS_PQ = Path("results/spin/tennis/raw/nominal_s7.parquet")
TENNIS_RULE = {
    "population": "the nominal simulated world of results/spin/tennis (hawkeye.simulate population, seed 7, 4,948 "
                  "near-line groundstrokes at 340 fps, 3.6 mm noise); method bls = the spin-aware batch physics fit "
                  "(results/spin/tennis/raw/nominal_s7.parquet)",
    "eligible": "lands OUT by more than 2 cm and at most 10 cm, and the bls P(out) first reaches 0.95 at the 200 ms "
                "lead of the evaluation grid (P(out) >= 0.95 at 200 ms and < 0.95 at 250 ms)",
    "chosen": "the eligible shot whose true landing is closest to 5 cm out (ties: lowest shot index)",
    "why": "a near-line OUT call at the 200 ms lead named in the spec; selected for illustration. The population "
           "numbers on screen come from results/spin/tennis/key_numbers.json",
}


def tennis_sim():
    """Re-run the spin-aware batch fit (src/spin/tennis_filter.bls_fit, unchanged) on the chosen simulated shot at
    every frame from 700 ms before the bounce to the bounce, plus the no-spin hawkeye predictor at the same frames.
    The fit at the evaluation's own decision frames must reproduce the parquet's d_hat and P(out)."""
    import pandas as pd
    from src import hawkeye as Hk
    from src.spin import physics as P, tennis_filter as F
    if not TENNIS_PQ.exists():
        raise SystemExit(f"{TENNIS_PQ} missing (see results/spin/tennis/raw/MOVED.txt)")
    df = pd.read_parquet(TENNIS_PQ, columns=["method", "lead_ms", "shot", "d", "d_hat", "sd_d", "p_out"])
    b = df[df.method == "bls"]
    piv = b.pivot(index="shot", columns="lead_ms", values="p_out")
    dtrue = b.groupby("shot").d.first()
    el = dtrue[(dtrue > 0.02) & (dtrue <= 0.10) & (piv[200] >= 0.95) & (piv[250] < 0.95)]
    order = sorted(el.index, key=lambda s: (abs(el[s] - 0.05), s))
    shot = int(order[0])
    pop = P.build_population("nominal", n=60000, seed=7)
    assert abs(pop["d"][shot] - dtrue[shot]) < 1e-9, "population does not match the parquet"
    meas = pop["meas"][shot:shot + 1]
    tland = float(pop["tland"][shot])
    K = meas.shape[1]

    def kdec(L_ms):
        k = min(int(np.floor((tland - L_ms / 1000.0) * P.FPS)), K - 1)
        for _ in range(4):
            if np.isfinite(meas[0, k, 0]):
                break
            k -= 1
        return k

    eval_leads = [400, 350, 300, 250, 200, 150, 100, 50, 25, 0]
    k_eval = [kdec(L) for L in eval_leads]
    k_fine = sorted(set(range(kdec(700), kdec(0) + 1)) | set(k_eval))
    k_fine = [k for k in k_fine if np.isfinite(meas[0, k, 0]) and k >= P.W_FIT]
    ks = np.array(k_fine)
    n = len(ks)
    M = np.repeat(meas, n, 0)
    sv = np.repeat(pop["serve"][shot:shot + 1], n)
    r = F.bls_fit(M, ks, theta0=F._init_theta(M, np.full(n, 50)), max_iter=15)
    ld = F.landing_distribution(r["y"], r["ycov"], r["active"])
    po = F.p_out(ld["land"], ld["cov"], sv)
    sdd = F.sd_signed_distance(ld["land"], ld["cov"], sv)
    dh = Hk.signed_out_distance(ld["land"], sv)
    sel = np.full(n, shot)
    wt = P.true_spin_at(pop, sel, ks)
    vt = P.true_vel_at(pop, sel, ks)
    wh = r["y"][:, 6:9]

    def rpm_perp(w, v):
        vh = v / np.linalg.norm(v, axis=1, keepdims=True)
        wp = w - np.sum(w * vh, 1, keepdims=True) * vh
        return np.linalg.norm(wp, axis=1) * 60 / (2 * np.pi)

    win = np.stack([meas[0, k - P.W_FIT + 1:k + 1] for k in ks])
    bl_land, _, _ = F.baseline_predict(win)
    st = pop["stimes"]
    rows = []
    for i, k in enumerate(ks):
        rows.append(dict(k=int(k), t=float(st[k]), lead_ms=float((tland - st[k]) * 1000), land=ld["land"][i, :2].tolist(),
                         cov=ld["cov"][i].tolist(), p_out=float(po[i]), sd_d_cm=float(sdd[i] * 100),
                         d_hat_cm=float(dh[i] * 100), w_hat=wh[i].tolist(), rpm_hat=float(rpm_perp(wh[i:i + 1], vt[i:i + 1])[0]),
                         rpm_true=float(rpm_perp(wt[i:i + 1], vt[i:i + 1])[0]), baseline_land=bl_land[i, :2].tolist(),
                         baseline_d_cm=float(Hk.signed_out_distance(bl_land[i:i + 1], sv[:1])[0] * 100),
                         chi2r=float(r["chi2r"][i])))
    chk = []
    for L, k in zip(eval_leads, k_eval):
        i = k_fine.index(k)
        ref = b[(b.shot == shot) & (b.lead_ms == L)].iloc[0]
        chk.append(dict(lead_ms=L, k=k, d_hat_cm=rows[i]["d_hat_cm"], d_hat_cm_parquet=float(ref.d_hat * 100),
                        p_out=rows[i]["p_out"], p_out_parquet=float(ref.p_out),
                        ok=bool(abs(rows[i]["d_hat_cm"] - ref.d_hat * 100) < 0.05 and abs(rows[i]["p_out"] - ref.p_out) < 0.01)))
    traj = pop["traj"][shot]
    ok = np.isfinite(traj[:, 0])
    kk = np.flatnonzero(ok)
    first_call = next((x for x in rows if x["p_out"] >= 0.95 and all(y["p_out"] >= 0.95 for y in rows if y["k"] >= x["k"])), None)
    out = dict(rule=TENNIS_RULE, shot=shot, n_eligible=int(len(el)), label=LABEL_SIM,
               inputs={str(TENNIS_PQ): sha(TENNIS_PQ)}, fps=P.FPS, noise_m=P.NOISE,
               tland_s=tland, land_true=pop["land"][shot, :2].tolist(), d_true_cm=float(pop["d"][shot] * 100),
               p0=pop["p0"][shot].tolist(), v0=pop["v0"][shot].tolist(), w0=pop["w0"][shot].tolist(),
               rpm0=float(np.linalg.norm(pop["w0"][shot]) * 60 / (2 * np.pi)),
               traj_t=st[kk].tolist(), traj=traj[kk].tolist(), meas=meas[0, kk].tolist(),
               fits=rows, eval_grid_check=chk, eval_grid_all_reproduce=all(c["ok"] for c in chk),
               eval_grid_p_out={str(L): float(piv.loc[shot, L]) for L in eval_leads},
               called_at_eval_lead_ms=200,
               stays_called_from_lead_ms=None if first_call is None else first_call["lead_ms"])
    TENNIS_DIR.mkdir(parents=True, exist_ok=True)
    TENNIS_JSON.write_text(json.dumps(out, indent=1))
    print(f"tennis: shot {shot} lands {out['d_true_cm']:.1f} cm out, {n} fits, eval grid reproduces: "
          f"{out['eval_grid_all_reproduce']}")
    for c in chk:
        print("  ", c)
    if not out["eval_grid_all_reproduce"]:
        raise SystemExit("the re-run does not reproduce the evaluation at its decision frames; not drawing it")
    return out


# ====================================================================================================
# 9. the final cut: keynote design system (research/compliance/VIDEO_REQUIREMENTS.md, DESIGN)
#    pure black / white canvas, Inter, one orange accent, greys, red only for losses, 8% margins,
#    12-column grid, stats rail on the right third (lower band on full-bleed footage), small labels
# ====================================================================================================
FINAL = Path("results/viz/courtside_60.mp4")
FINAL_SRT = Path("results/viz/courtside_60.srt")
DOC = Path("docs/video_script_60.md")
FW = WORK / "final"                              # scratch (gitignored): voice wavs, segment renders, mix
REAL_TENNIS = ASSETS / "tennis_real" / "tennis_tracked.mp4"
REAL_TENNIS_LICENSE = ASSETS / "tennis_real" / "LICENSE.md"
EXAMPLE_MATCH = ASSETS / "backtest_match" / "example_match.mp4"
EXAMPLE_MATCH_JSON = ASSETS / "backtest_match" / "match.json"
TEAM = "Ojasva Mishra · Yoan Exposito · Rafael Penhas · Ian Hoang · University of Florida"
END_LINE = ("Paper trading only · simulated 1 s licensed-feed baseline · Voice: AI (ElevenLabs) · "
            "footage: OpenTTGames CC BY-NC-SA 4.0")

KBK, KWH, KINK, KGREY = (0, 0, 0), (255, 255, 255), (29, 29, 31), (134, 134, 139)
KHAIR_D, KHAIR_L, KOR = (58, 58, 60), (210, 210, 215), (255, 107, 26)
KRED_D, KRED_L = (255, 69, 58), (255, 59, 48)
GM = 154                                          # 8 % side margin
GRID_W = W - 2 * GM
COL = (GRID_W - 11 * 24) / 12                     # 12 columns, 24 px gutters


def gx(c):
    """left edge of column c (0..12) of the 12-column grid."""
    return GM + c * (COL + 24) - (24 if c == 12 else 0)


CX0, CX1 = GM, int(gx(8) - 24)                 # content: columns 1-8
RX0, RX1 = int(gx(8) + 40), GM + GRID_W       # stats rail: columns 9-12
TOP, CAP_Y = 64, 1012                             # chrome baseline row, caption baseline


def ease3(x):
    """cubic in-out (the spec's slow, confident easing)."""
    x = min(max(x, 0.0), 1.0)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def appear(t, t0, d=0.6):
    return ease3((t - t0) / d)


_KF = {}


def kf(size, w=500):
    key = (int(size), w)
    if key not in _KF:
        from PIL import ImageFont
        name = {400: "Inter_400Regular.ttf", 500: "Inter_500Medium.ttf", 600: "Inter_600SemiBold.ttf"}[w]
        _KF[key] = ImageFont.truetype(str(ASSETS / "fonts" / name), int(size))
    return _KF[key]


class Spr:
    """premultiplied sprite: rgb float32 (h, w, 3) 0..255 times alpha, a float32 (h, w) 0..1; base = baseline y."""
    __slots__ = ("rgb", "a", "base")

    def __init__(self, rgb, a, base=0):
        self.rgb, self.a, self.base = rgb, a, base

    @property
    def w(self):
        return self.a.shape[1]

    @property
    def h(self):
        return self.a.shape[0]

    def scaled(self, k):
        import cv2
        w, h = max(1, int(round(self.w * k))), max(1, int(round(self.h * k)))
        return Spr(cv2.resize(self.rgb, (w, h), interpolation=cv2.INTER_LINEAR),
                   cv2.resize(self.a, (w, h), interpolation=cv2.INTER_LINEAR), self.base * k)


def spr_from_rgba(arr, base=0):
    a = arr[..., 3].astype(np.float32) / 255.0
    return Spr(arr[..., :3].astype(np.float32) * a[..., None], a, base)


_KT = {}


def ktext(s, size, w=500, col=KWH, track=0.0, tnum=False):
    """one line of Inter. track: extra px between glyphs (negative = tighter); tnum: tabular digits."""
    key = (s, int(size), w, col, round(track, 2), tnum)
    if key in _KT:
        return _KT[key]
    f = kf(size, w)
    asc, desc = f.getmetrics()
    pad = 4
    if track == 0 and not tnum:
        wd = int(math.ceil(f.getlength(s)))
        glyphs = None
    else:
        dw = f.getlength("0")
        glyphs, x = [], 0.0
        for ch in s:
            adv = dw if (tnum and ch.isdigit()) else f.getlength(ch)
            off = (dw - f.getlength(ch)) / 2 if (tnum and ch.isdigit()) else 0.0
            glyphs.append((x + off, ch))
            x += adv + track
        wd = int(math.ceil(x - track))
    im = Image.new("RGBA", (wd + 2 * pad, asc + desc + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if glyphs is None:
        d.text((pad, pad), s, font=f, fill=col + (255,))
    else:
        for x, ch in glyphs:
            d.text((pad + x, pad), ch, font=f, fill=col + (255,))
    sp = spr_from_rgba(np.asarray(im), base=pad + asc)
    if len(_KT) > 3000:
        _KT.clear()
    _KT[key] = sp
    return sp


def kwrap(s, size, w, maxw):
    f = kf(size, w)
    out, cur = [], ""
    for wd in s.split():
        t = (cur + " " + wd).strip()
        if f.getlength(t) <= maxw or not cur:
            cur = t
        else:
            out.append(cur)
            cur = wd
    if cur:
        out.append(cur)
    return out


def blit(cv, s, x, y, anchor="la", k=1.0, scale=1.0):
    """composite sprite s onto the uint8 canvas at (x, y); anchor = [l|m|r][a|m|b|s] (s = baseline)."""
    if k <= 0.004 or s is None:
        return
    if abs(scale - 1.0) > 1e-3:
        s = s.scaled(scale)
    ax = {"l": 0.0, "m": 0.5, "r": 1.0}[anchor[0]]
    oy = s.base if anchor[1] == "s" else {"a": 0.0, "m": 0.5, "b": 1.0}[anchor[1]] * s.h
    x0, y0 = int(round(x - ax * s.w)), int(round(y - oy))
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + s.w, cv.shape[1]), min(y0 + s.h, cv.shape[0])
    if X1 <= X0 or Y1 <= Y0:
        return
    a = s.a[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0, None] * k
    reg = cv[Y0:Y1, X0:X1].astype(np.float32)
    cv[Y0:Y1, X0:X1] = (reg * (1 - a) + s.rgb[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0] * k + 0.5).astype(np.uint8)


class Lyr:
    """full-frame vector layer drawn with cv2 anti-aliasing: premultiplied rgb uint8 + alpha uint8."""
    SH = 4

    def __init__(self, w=W, h=H):
        self.rgb = np.zeros((h, w, 3), np.uint8)
        self.a = np.zeros((h, w), np.uint8)
        self._bb = None

    def _p(self, p):
        return int(round(p[0] * 16)), int(round(p[1] * 16))

    def line(self, pts, col, th=2, al=1.0):
        import cv2
        pts = np.array([self._p(p) for p in pts], np.int32)
        if len(pts) < 2:
            return self
        c = tuple(float(v) * al for v in col)
        cv2.polylines(self.rgb, [pts], False, c, th, cv2.LINE_AA, self.SH)
        cv2.polylines(self.a, [pts], False, 255.0 * al, th, cv2.LINE_AA, self.SH)
        self._bb = None
        return self

    def dotted(self, p0, p1, col, th=2, on=4, off=7, al=1.0):
        L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        n = int(L // (on + off)) + 1
        for i in range(n):
            a0 = i * (on + off) / L
            a1 = min(1.0, (i * (on + off) + on) / L)
            if a0 >= 1:
                break
            self.line([(p0[0] + (p1[0] - p0[0]) * a0, p0[1] + (p1[1] - p0[1]) * a0),
                       (p0[0] + (p1[0] - p0[0]) * a1, p0[1] + (p1[1] - p0[1]) * a1)], col, th, al)
        return self

    def poly(self, pts, col, al=1.0):
        import cv2
        pts = np.array([self._p(p) for p in pts], np.int32)
        cv2.fillPoly(self.rgb, [pts], tuple(float(v) * al for v in col), cv2.LINE_AA, self.SH)
        cv2.fillPoly(self.a, [pts], 255.0 * al, cv2.LINE_AA, self.SH)
        self._bb = None
        return self

    def rect(self, x0, y0, x1, y1, col, al=1.0, r=0):
        if r <= 0:
            return self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], col, al)
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
        pts = []
        for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
            for j in range(7):
                ang = math.radians(a0 + 15 * j)
                pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        return self.poly(pts, col, al)

    def circle(self, c, r, col, th=-1, al=1.0):
        import cv2
        cc = self._p(c)
        rr_ = int(round(r * 16))
        cv2.circle(self.rgb, cc, rr_, tuple(float(v) * al for v in col), th, cv2.LINE_AA, self.SH)
        cv2.circle(self.a, cc, rr_, 255.0 * al, th, cv2.LINE_AA, self.SH)
        self._bb = None
        return self

    def bbox(self):
        if self._bb is None:
            ys, xs = np.nonzero(self.a.max(axis=1) > 0)[0], np.nonzero(self.a.max(axis=0) > 0)[0]
            self._bb = (0, 0, 0, 0) if not len(ys) else (int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1)
        return self._bb


def comp(cv, ly, k=1.0, xr=None, xl=None):
    """composite a layer; xr / xl reveal only columns left of xr (right of xl): charts drawing in left to right."""
    if k <= 0.004:
        return
    x0, y0, x1, y1 = ly.bbox()
    if xr is not None:
        x1 = min(x1, int(xr))
    if xl is not None:
        x0 = max(x0, int(xl))
    if x1 <= x0 or y1 <= y0:
        return
    a = ly.a[y0:y1, x0:x1, None].astype(np.float32) * (k / 255.0)
    reg = cv[y0:y1, x0:x1].astype(np.float32)
    cv[y0:y1, x0:x1] = (reg * (1 - a) + ly.rgb[y0:y1, x0:x1].astype(np.float32) * k + 0.5).astype(np.uint8)


def canvas(theme="dark"):
    return np.full((H, W, 3), 0 if theme == "dark" else 255, np.uint8)


NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def count_str(final, k):
    """the first number in `final` counted up to k (0..1), same decimals and thousands separators."""
    m = NUM_RE.search(final)
    if not m or k >= 0.999:
        return final
    tok = m.group(0)
    dec = len(tok.split(".")[1]) if "." in tok else 0
    v = float(tok.replace(",", "")) * ease3(k)
    s = f"{v:,.{dec}f}" if "," in tok else f"{v:.{dec}f}"
    return final[:m.start()] + s + final[m.end():]


class Rail:
    """the stats rail: right third on canvas scenes (mode 'right'), a lower band on full-bleed footage ('band').
    items: dict(v=final value string, lab=label, t=reveal time, sub=optional second label line)."""

    def __init__(self, items, theme="dark", mode="right", head=None, y0=196, gap=34, vsize=50, band_y=842):
        self.items, self.theme, self.mode, self.head = items, theme, mode, head
        self.y0, self.gap, self.vsize, self.band_y = y0, gap, vsize, band_y
        fg = KWH if theme == "dark" else KINK
        self.fg, self.sub = fg, KGREY
        self._lab = {}

    def events(self, t_off=0.0):
        return [(t_off + it["t"] + 0.05, "tick") for it in self.items if it.get("tick", True)]

    def lab_lines(self, it, maxw):
        key = (it["lab"], maxw)
        if key not in self._lab:
            self._lab[key] = kwrap(it["lab"], 19 if self.mode == "right" else 18, 400, maxw)
        return self._lab[key]

    def draw(self, cv, t, k_all=1.0):
        if self.mode == "right":
            y = self.y0
            if self.head:
                blit(cv, ktext(self.head, 17, 500, self.sub, track=0.6), RX0, y, "la", k_all * appear(t, self.items[0]["t"] - 0.2))
                y += 44
            for it in self.items:
                k = appear(t, it["t"], 0.6) * k_all
                if k <= 0.004:
                    y += self.vsize + 14 + 26 * len(self.lab_lines(it, RX1 - RX0)) + self.gap
                    continue
                q = (t - it["t"]) / 0.8
                cnt = it.get("count", True) and q < 1
                v = count_str(it["v"], q) if cnt else it["v"]
                sz = it.get("vsize", self.vsize)
                col = it.get("col", self.fg)
                blit(cv, ktext(v, sz, 600, col, track=-0.02 * sz, tnum=cnt), RX0, y + (1 - k) * 10, "la", k)
                yy = y + sz * 1.18 + 6
                for ln in self.lab_lines(it, RX1 - RX0):
                    blit(cv, ktext(ln, 19, 400, self.sub), RX0, yy + (1 - k) * 10, "la", k)
                    yy += 26
                y = yy + self.gap
        else:
            n = len(self.items)
            cw = (W - 2 * GM - (n - 1) * 32) / n
            for i, it in enumerate(self.items):
                k = appear(t, it["t"], 0.6) * k_all
                if k <= 0.004:
                    continue
                x = GM + i * (cw + 32)
                q = (t - it["t"]) / 0.8
                cnt = it.get("count", True) and q < 1
                v = count_str(it["v"], q) if cnt else it["v"]
                sz = it.get("vsize", 40)
                blit(cv, ktext(v, sz, 600, it.get("col", KWH), track=-0.02 * sz, tnum=cnt), x,
                     self.band_y + (1 - k) * 8, "la", k)
                yy = self.band_y + sz * 1.2 + 4
                for ln in self.lab_lines(it, cw):
                    blit(cv, ktext(ln, 18, 400, (200, 200, 205)), x, yy + (1 - k) * 8, "la", k)
                    yy += 24


_GRAD = {}


def bottom_grad(cv, y0=640, strength=0.82):
    """darkening gradient under the lower band and captions on full-bleed footage (subtle, no colour)."""
    key = (y0, strength)
    if key not in _GRAD:
        y = np.arange(H, dtype=np.float32)
        g = np.clip((y - y0) / (H - y0), 0, 1) ** 1.6 * strength
        _GRAD[key] = (1 - g)[:, None, None]
    cv[:] = (cv.astype(np.float32) * _GRAD[key]).astype(np.uint8)


_TOPG = {}


def top_grad(cv, h=190, strength=0.62):
    """darkening at the top of full-bleed footage so the chapter title and the label read (no colour)."""
    if (h, strength) not in _TOPG:
        y = np.arange(h, dtype=np.float32)
        _TOPG[(h, strength)] = (1 - strength * (1 - y / h) ** 1.4)[:, None, None]
    cv[:h] = (cv[:h].astype(np.float32) * _TOPG[(h, strength)]).astype(np.uint8)


_VIG = {}


def vignette(cv, strength=0.22):
    if strength not in _VIG:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
        _VIG[strength] = (1 - strength * np.clip(r, 0, 1) ** 2.2)[..., None]
    cv[:] = (cv.astype(np.float32) * _VIG[strength]).astype(np.uint8)


def chrome(cv, num, title, label, theme="dark", k=1.0, label2=None, footage=False):
    """small chapter title top-left and the honesty label top-right. On footage the label is a light grey
    (#86868b does not read over bright sky or curtains)."""
    fg, sub = (KWH, KGREY) if theme == "dark" else (KINK, KGREY)
    if footage:
        sub = (214, 214, 219)
    if num:
        a = ktext(f"{num}", 19, 500, sub)
        blit(cv, a, GM, TOP, "ls", k)
        blit(cv, ktext(title, 19, 500, fg), GM + a.w + 6, TOP, "ls", k)
    if label:
        lines = kwrap(label, 17, 400, 760)
        for i, ln in enumerate(lines):
            blit(cv, ktext(ln, 17, 400, sub), W - GM, TOP + i * 23, "rs", k)
    if label2:
        n = len(kwrap(label, 17, 400, 760)) if label else 0
        blit(cv, ktext(label2, 17, 500, fg), W - GM, TOP + n * 23 + 4, "rs", k)


# ----------------------------------------------------------------------------------------------------
# narration (Liam), one line per segment of the spec table; docs/video_script_60.md carries the same lines
# ----------------------------------------------------------------------------------------------------
# ctx: the neighbour lines an unchanged line's approved take was rendered with (ElevenLabs previous_text /
# next_text, part of the cache key). The QA pass rewrote two lines; their neighbours keep their approved takes.
_OLD_TENNIS_REAL = "Same tracker, real tennis."
_OLD_TEST = ("Here's months of backtest, on one real match: every fill on the real price path. 59 percent of "
             "traded matches made money.")
SEGS = [
    dict(id="coldopen", num="", title="", min=5.0, lead=0.35, tail=0.55,
         say="That ball's going out. The model called it 325 milliseconds early."),
    dict(id="strategy", num="1", title="The idea", min=6.2, lead=0.2, tail=0.5,
         say="Our computer vision calls the point before the ball lands, so we trade the Polymarket match price "
             "before it reprices."),
    dict(id="edge", num="2", title="The edge", min=8.0, lead=0.2, tail=1.0,
         say="Polymarket prices each match from zero to a dollar, a player's chance to win, and reprices about a "
             "second after each point. The fastest traders won eleven months of eleven."),
    dict(id="tt", num="3", title="The models · table tennis", min=12.5, lead=0.25, tail=0.4,
         say="Think it's a gimmick? Watch it call misses on real games it never saw. A miss call means it knows the "
             "ball is out before it lands. Not one was made on a ball labelled in.",
         ctx=(None, _OLD_TENNIS_REAL)),
    # QA (first-time viewer): "Same tracker" was wrong; the tennis trail comes from our tennis model, not the
    # table-tennis engine
    dict(id="tennis_real", num="3", title="The models · tennis", min=4.0, lead=0.3, tail=0.6,
         say="Real tennis, with our tennis tracker."),
    dict(id="tennis", num="3", title="The models · tennis", min=7.6, lead=0.2, tail=0.8,
         say="Add spin: landing error drops five to eight times. Out, called 200 milliseconds before the bounce.",
         ctx=(_OLD_TENNIS_REAL, None)),
    dict(id="pipeline", num="4", title="The pipeline", min=8.0, lead=0.2, tail=0.5,
         say="Here's the whole pipeline in milliseconds: our part, about fifty. Add a one-second feed and "
             "Polymarket's one-second delay: 2.1 seconds. Under three."),
    dict(id="speed", num="5", title="Speed", min=8.0, lead=0.2, tail=0.5,
         say="Here's what speed is worth: every second costs money; by three seconds, every version loses. "
             "The edge halves within a second.",
         ctx=(None, _OLD_TEST)),
    # QA (first-time viewer): "months of backtest, on one real match" read as one match being months long
    dict(id="test", num="6", title="The test", min=9.6, lead=0.25, tail=0.5,
         say="The test: months of backtest. One match: dots are paper trades on the real price. 59 percent of "
             "traded matches made money."),
    dict(id="profit", num="7", title="The result", min=9.5, lead=0.2, tail=0.5,
         say="And the profit, at a simulated one-second feed, post-hoc estimate: 94 dollars a day, Sharpe 12: "
             "return per unit of risk, above two is very good. On data it never saw: 57 a day.",
         ctx=(_OLD_TEST, None)),
    dict(id="endcard", num="", title="", min=3.6, lead=0.3, tail=1.6,
         say="Courtside. Paper trading only."),
]
TOTAL_MAX = 89.6
VOICE_TEMPO = 1.08          # narration sped up 8 % (ffmpeg atempo, pitch kept) after the pauses are tightened
VOICE_MAX_PAUSE = 0.26      # internal pauses longer than this are tightened (15 ms crossfades, v2.trim)


def tempo(a, r):
    if abs(r - 1.0) < 1e-3:
        return a
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(v2.SR), "-ac", "1", "-i", "-",
                          "-af", f"atempo={r}", "-f", "f32le", "-ar", str(v2.SR), "-ac", "1", "-"],
                         input=a.astype(np.float32).tobytes(), capture_output=True, check=True).stdout
    return np.frombuffer(out, np.float32).copy()


def words(s):
    return len(s.split())


def voice():
    """synthesise every line with Liam (cached by scripts/tts_elevenlabs.py), trim, measure; data/v60/final/voice."""
    FW.mkdir(parents=True, exist_ok=True)
    out = {}
    v2.WORK = FW
    for i, sg in enumerate(SEGS):
        prev = SEGS[i - 1]["say"] if i else None
        nxt = SEGS[i + 1]["say"] if i + 1 < len(SEGS) else None
        cp, cn = sg.get("ctx", (None, None))
        prev, nxt = cp or prev, cn or nxt
        mp3 = FW / "voice" / f"{i:02d}_{sg['id']}.mp3"
        mp3.parent.mkdir(parents=True, exist_ok=True)
        if v2.synth_line(sg["say"], prev, nxt, mp3) is None:
            raise SystemExit("ElevenLabs TTS failed: " + ", ".join(v2.TTSStats.errors))
        a = tempo(v2.trim(v2.decode(mp3), max_pause=VOICE_MAX_PAUSE), VOICE_TEMPO)
        out[sg["id"]] = dict(audio=a, dur=len(a) / v2.SR, gaps=v2.gaps(a), file=str(mp3))
    st = dict(chars_sent=v2.TTSStats.chars_sent, chars_cached=v2.TTSStats.chars_cached, calls=v2.TTSStats.calls)
    return out, st


_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
         "seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _spell(n):
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + _spell(n % 100))
    return " ".join(_ONES[int(d)] for d in str(n))


def wts_spoken(s):
    """spoken weight with numbers spelled out ("94" is said "ninety four", not two characters)."""
    def sp(m):
        a, _, b = m.group(0).partition(".")
        return _spell(int(a)) + ("" if not b else " point " + " ".join(_ONES[int(d)] for d in b))
    return v2.wts(re.sub(r"\d+(?:\.\d+)?", sp, s))


def speech_anchors(sg, vo):
    """where Liam actually pauses: every internal punctuation mark of the line aligned, in order, to the measured
    silent gaps of the take (dynamic programming on |gap - weighted estimate|; extra gaps may be skipped, a mark may
    stay unaligned). Character weights alone misplace spoken numbers ("2.1", "325", "94"); the gaps do not.
    Returns [(char position after the mark, gap start s, gap end s)], relative to the start of the take."""
    say, v = sg["say"], vo[sg["id"]]
    dur, gp = v["dur"], v["gaps"]
    marks = [m.end() for m in re.finditer(r"[,;:.?!](?=\s)", say)]
    tot = wts_spoken(say) or 1
    exp = [dur * wts_spoken(say[:m]) / tot for m in marks]
    mids = [(g[0] + g[1]) / 2 for g in gp]
    M, G = len(marks), len(gp)
    if M and G >= M:
        # every mark gets a pause; the extra pauses are breaths inside a clause. The words between two marks need
        # at least 55 % of their average speaking time, so a breath ("Sharpe | 12") cannot stand in for a comma.
        rate = dur / tot
        pos = [0] + marks + [len(say)]
        need = [0.55 * rate * wts_spoken(say[pos[k]:pos[k + 1]]) for k in range(M + 1)]

        def short(k, t0, t1):
            return 3.0 * max(0.0, need[k] - (t1 - t0))
        F = [[1e9] * G for _ in range(M)]
        B = [[-1] * G for _ in range(M)]
        for j in range(G):
            F[0][j] = abs(mids[j] - exp[0]) + short(0, 0.0, gp[j][0])
        for k in range(1, M):
            for j in range(k, G):
                for jp in range(k - 1, j):
                    c = F[k - 1][jp] + abs(mids[j] - exp[k]) + short(k, gp[jp][1], gp[j][0])
                    if c < F[k][j]:
                        F[k][j], B[k][j] = c, jp
        last = min(range(M - 1, G), key=lambda j: F[M - 1][j] + short(M, gp[j][1], dur))
        out, j = [], last
        for k in range(M - 1, -1, -1):
            out.append((marks[k], float(gp[j][0]), float(gp[j][1])))
            j = B[k][j]
        return sorted(out)
    f = [[0.0] * (G + 1)] + [[1e9] * (G + 1) for _ in range(M)]
    back = {}
    for i in range(1, M + 1):
        for j in range(G + 1):
            best, arg = f[i - 1][j] + 1.5, ("u", j)                 # mark i not aligned
            if j:
                if f[i][j - 1] + 0.1 < best:                         # gap j is a pause inside a clause
                    best, arg = f[i][j - 1] + 0.1, ("s", j - 1)
                c = f[i - 1][j - 1] + abs(mids[j - 1] - exp[i - 1])  # mark i at gap j
                if c < best:
                    best, arg = c, ("a", j - 1)
            f[i][j], back[(i, j)] = best, arg
    out, i, j = [], M, G
    while i > 0:
        kind, jj = back[(i, j)]
        if kind == "a":
            out.append((marks[i - 1], float(gp[jj][0]), float(gp[jj][1])))
            i -= 1
        elif kind == "u":
            i -= 1
        j = jj
    return sorted(out)


def t_said(p, say, pos):
    """time (s, from the start of the take) at which the text at character `pos` starts to be spoken: a gap end
    when a measured pause precedes it, else interpolated by spoken weight between the aligned pauses."""
    pts = [(0, 0.0, 0.0)] + list(p.get("anchors") or []) + [(len(say), p["speech_dur"], p["speech_dur"])]
    for pa, g0, g1 in pts:
        if pa <= pos and not say[pa:pos].strip():
            return g1
    a = max((q for q in pts if q[0] <= pos), key=lambda q: q[0])
    b = min((q for q in pts if q[0] > pos), key=lambda q: q[0])
    den = wts_spoken(say[a[0]:b[0]]) or 1
    return a[2] + (b[1] - a[2]) * wts_spoken(say[a[0]:pos]) / den


def plan_times(vo):
    """segment start / duration from the spec minimums and the measured narration; total capped at TOTAL_MAX."""
    durs = []
    for sg in SEGS:
        need = sg["lead"] + vo[sg["id"]]["dur"] + sg["tail"]
        durs.append(max(sg["min"], need))
    tot = sum(durs)
    if tot > TOTAL_MAX:          # take the excess out of the slack above each segment's narration need, pro rata
        slack = [d - (sg["lead"] + vo[sg["id"]]["dur"] + 0.25) for d, sg in zip(durs, SEGS)]
        ex = tot - TOTAL_MAX
        S_ = sum(max(0, s) for s in slack)
        if S_ < ex:
            raise SystemExit(f"narration too long for {TOTAL_MAX} s: {tot:.1f} s needed")
        durs = [d - max(0, s) * ex / S_ for d, s in zip(durs, slack)]
    durs = [round(d * FPS) / FPS for d in durs]
    t, plan = 0.0, []
    for sg, d in zip(SEGS, durs):
        plan.append(dict(id=sg["id"], start=t, dur=d, speech_at=t + sg["lead"], speech_dur=vo[sg["id"]]["dur"],
                         anchors=speech_anchors(sg, vo)))
        t += d
    return plan


def cap_chunks(s, maxc=60):
    """caption chunks: split at sentence / clause punctuation, then at commas, so a chunk fits one line."""
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", s) if p.strip()]
    out = []
    for p in parts:
        if len(p) <= maxc:
            out.append(p)
            continue
        sub = [q.strip() for q in re.split(r"(?<=[:;])\s+", p) if q.strip()]
        for q in sub:
            if len(q) <= maxc:
                out.append(q)
                continue
            cs = [c.strip() for c in re.split(r"(?<=,)\s+", q) if c.strip()]
            cur = ""
            for c in cs:
                if cur and len(cur) + 1 + len(c) > maxc:
                    out.append(cur)
                    cur = c
                else:
                    cur = (cur + " " + c).strip()
            if cur:
                out.append(cur)
    # balance: merge a tiny trailing piece into its neighbour when it still fits two lines
    merged = []
    for c in out:
        if merged and (len(c) < 14 or len(merged[-1]) < 14) and len(merged[-1]) + len(c) + 1 <= 2 * maxc - 10:
            merged[-1] = merged[-1] + " " + c
        else:
            merged.append(c)
    return merged


def cues_for(sg, p, vo):
    """caption cues for one line: each chunk ends at the measured pause aligned to its closing punctuation
    (speech_anchors); QA found weight-only placement up to 0.9 s late after spoken numbers."""
    say = sg["say"]
    chunks = cap_chunks(say)
    dur = vo[sg["id"]]["dur"]
    anc = {a[0]: (a[1], a[2]) for a in (p.get("anchors") or speech_anchors(sg, vo))}
    bounds, cur = [(0.0, 0.0)], 0
    for c in chunks[:-1]:
        cur = say.find(c, cur) + len(c)
        if cur in anc:
            bounds.append(anc[cur])
        else:
            tb = t_said(dict(p, anchors=list((k,) + v for k, v in anc.items()), speech_dur=dur), say, cur)
            bounds.append((tb, tb))
    bounds.append((dur, dur))
    out = []
    for i, c in enumerate(chunks):
        s = p["speech_at"] + bounds[i][1]
        e = p["speech_at"] + bounds[i + 1][0]
        out.append(dict(start=round(s, 3), end=round(max(e, s + 0.6), 3), text=c, seg=sg["id"]))
    return out


def write_srt(cues, path):
    lines = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{v2.srt_time(c['start'])} --> {v2.srt_time(c['end'])}", c["text"], ""]
    path.write_text("\n".join(lines))


class Captions60:
    """small, clean, bottom-centre, at most two lines, fade in / out (Inter 500, 30 px)."""
    SIZE = 30

    def __init__(self, cues):
        self.cues = cues
        self._c = {}

    def sprite(self, i, theme, shadow):
        key = (i, theme, shadow)
        if key not in self._c:
            import cv2
            txt = self.cues[i]["text"]
            lines = kwrap(txt, self.SIZE, 500, 1240)
            col = KWH if theme == "dark" else KINK
            sps = [ktext(ln, self.SIZE, 500, col) for ln in lines]
            wmax = max(s.w for s in sps)
            lh = 40
            hh = lh * (len(sps) - 1) + sps[0].h
            pad = 24
            rgb = np.zeros((hh + 2 * pad, wmax + 2 * pad, 3), np.float32)
            a = np.zeros((hh + 2 * pad, wmax + 2 * pad), np.float32)
            for j, s in enumerate(sps):
                x0 = pad + (wmax - s.w) // 2
                y0 = pad + j * lh
                a[y0:y0 + s.h, x0:x0 + s.w] = np.maximum(a[y0:y0 + s.h, x0:x0 + s.w], s.a)
                rgb[y0:y0 + s.h, x0:x0 + s.w] = np.maximum(rgb[y0:y0 + s.h, x0:x0 + s.w], s.rgb)
            if shadow:
                sh = cv2.GaussianBlur(a, (0, 0), 7) * 0.75
                a_out = a + sh * (1 - a)
                self._c[key] = Spr(rgb, a_out, base=pad + sps[-1].base + lh * (len(sps) - 1))
            else:
                self._c[key] = Spr(rgb, a, base=pad + sps[-1].base + lh * (len(sps) - 1))
        return self._c[key]

    def draw(self, cv, T, theme="dark", shadow=False):
        for i, c in enumerate(self.cues):
            if c["start"] - 0.05 <= T <= c["end"] + 0.15:
                k = min(1.0, (T - c["start"] + 0.05) / 0.18, (c["end"] + 0.15 - T) / 0.18)
                s = self.sprite(i, theme, shadow)
                blit(cv, s, W / 2, CAP_Y + 24, "ms", ease3(k))
                break


# ----------------------------------------------------------------------------------------------------
# every number on screen: registered (file + key + value) in the main process, handed to the renderers as text
# ----------------------------------------------------------------------------------------------------
def neg(s):
    return s.replace("-", "−")


def pct(x, dp=0):
    return f"{x:.{dp}f}%"


def values60(R):
    """registers every value the final cut shows (R.put / R.d mark file, key, value, segment) and returns
    {segment: {name: display}}. Nothing on screen is typed in by hand."""
    P = R.put
    S = {}
    # ---- cold open + table tennis (streaming engine, L4 real-time run) ----
    ovo = jload(OVO)
    run_, hd = ovo["runs"][RUN], ovo["headline"][RUN]
    c, em = run_["calls"], run_["calls"]["emitted"]
    sel = {x["id"]: x for x in jload(SELECTION)["chosen"]}
    x = sel["test_2_f2819_miss"]
    P("cold_lead_ms", x["lead_ms"], str(OVO), f"runs.{RUN}.flights_called_or_miss[test_2, f_net 2819]: (t_ref - "
      "engine_miss_frame) / 120 fps × 1000", fmt=f0,
      note="the streaming engine's own call; the spec's 408 ms is the offline evaluation's lead for this flight")
    P("pf_games", len(run_["population"]["videos"]), str(OVO), f"len(runs.{RUN}.population.videos)", fmt=f0)
    P("pf_frames", run_["timing"]["frames"], str(OVO), f"runs.{RUN}.timing.frames", fmt=f0)
    P("pf_dropped", run_["timing"]["frames_dropped"], str(OVO), f"runs.{RUN}.timing.frames_dropped", fmt=f0)
    P("pf_calls", em["MISS"] + em["BOUNCE"], str(OVO), f"runs.{RUN}.calls.emitted.MISS + .BOUNCE", fmt=f0)
    P("pf_miss", em["MISS"], str(OVO), f"runs.{RUN}.calls.emitted.MISS", fmt=f0)
    P("pf_lat", hd["stream"]["after_startup"]["emitted_call_latency_ms"]["p50"], str(OVO),
      f"headline.{RUN}.stream.after_startup.emitted_call_latency_ms.p50", fmt=f1)
    P("pf_miss_on_bounce", c["miss_calls_on_BOUNCE_flights"], str(OVO), f"runs.{RUN}.calls.miss_calls_on_BOUNCE_flights",
      fmt=f0)
    P("pf_in_right", c["bounce_calls_on_BOUNCE_flights"], str(OVO), f"runs.{RUN}.calls.bounce_calls_on_BOUNCE_flights",
      fmt=f0)
    P("pf_in_matched", c["bounce_calls_on_BOUNCE_flights"] + c["bounce_calls_on_MISS_flights"], str(OVO),
      f"runs.{RUN}.calls.bounce_calls_on_BOUNCE_flights + .bounce_calls_on_MISS_flights", fmt=f0)
    P("pf_recall_tp", run_["A_engine_calls"]["online"]["0ms"]["tp"], str(OVO),
      f"runs.{RUN}.A_engine_calls.online['0ms'].tp", fmt=f0)
    P("pf_n_miss_flights", run_["population"]["MISS"], str(OVO), f"runs.{RUN}.population.MISS", fmt=f0)
    P("pf_unmatched", c["unmatched"]["MISS"] + c["unmatched"]["BOUNCE"], str(OVO),
      f"runs.{RUN}.calls.unmatched.MISS + .BOUNCE", fmt=f0)
    assert R.v("pf_calls") == sum(1 for ln in EVENTS.read_text().splitlines() if ln.strip())
    R.scene = "coldopen"
    S["coldopen"] = dict(lead=R.d("cold_lead_ms"))
    R.scene = "tt"
    S["tt"] = dict(games=R.d("pf_games"), frames=R.d("pf_frames"), dropped=R.d("pf_dropped"), miss=R.d("pf_miss"),
                   mob=R.d("pf_miss_on_bounce"), lat=R.d("pf_lat"), inr=R.d("pf_in_right"), inm=R.d("pf_in_matched"),
                   rtp=R.d("pf_recall_tp"), nmf=R.d("pf_n_miss_flights"), unm=R.d("pf_unmatched"),
                   tp50=R.d("tp50"), n50=R.d("n50"), calls=R.d("pf_calls"))
    # ---- strategy ----
    e2 = "results/e2e/summary.json"
    if "reprice_band_s" not in R.entries:
        P("reprice_band_s", R.get(e2, "reprice_reference", "band_s"), e2, "reprice_reference.band_s",
          fmt=lambda b: f"{fmt(b[0], 1, keep0=True)}–{fmt(b[1], 1, keep0=True)}",
          note="inference: book vs official stamp measured (n = 482); stamp lag after the point not measured")
    R.scene = "strategy"
    rb = R.v("reprice_band_s")
    S["strategy"] = dict(band=R.d("reprice_band_s"), b0=rb[0], b1=rb[1], stale=R.d("stale_pre_usd"),
                         stale_n=R.d("stale_n"))
    # ---- edge ----
    ssr = "results/home_stream/sub_second_routes.json"
    setka = next((r for r in (R.get(ssr, "routes") or []) if r.get("id") == "setka_flussonic_public"), {})
    P("setka_s", ((setka.get("latency") or {}).get("measured_s") or {}).get("lo"), ssr,
      "routes[id=setka_flussonic_public].latency.measured_s.lo (WebRTC/WHEP median, preliminary)", fmt=f1)
    lt = "research/v2/latency/results.json"
    P("espn_lag_s", -R.get(lt, "summary", "m1", "espn:game", "lead_vs_book_s", "median"), lt,
      "-summary.m1['espn:game'].lead_vs_book_s.median", fmt=f0)
    P("wta_lag_s", -R.get(lt, "summary", "m1", "wta:point", "lead_vs_book_s", "median"), lt,
      "-summary.m1['wta:point'].lead_vs_book_s.median", fmt=f0)
    al = "results/alpha/alpha.json"
    months = [dict(month=m["month"], period=per, fast=m["fast_net30_c"], copy=m["copy_3s_later_net_to_resolution_c"])
              for per in ("IS", "OOS") for m in R.get(al, "A_source", per, "months")]
    P("alpha_months", months, al, "A_source.{IS,OOS}.months[]: month, fast_net30_c, copy_3s_later_net_to_resolution_c")
    P("oth_is_c", R.get(al, "headline", "others_net30_c_month_mean", "IS"), al,
      "headline.others_net30_c_month_mean.IS", fmt=lambda v: neg(f"{v:+.2f}¢"))
    R.scene = "edge"
    S["edge"] = dict(cam=R.v("band_cam"), vid=R.v("band_vid"), feed=R.v("band_feed"), tv=R.v("band_tv"),
                     setka=R.v("setka_s"), setka_d=R.d("setka_s"), espn=R.v("espn_lag_s"), espn_d=R.d("espn_lag_s"),
                     wta=R.v("wta_lag_s"), wta_d=R.d("wta_lag_s"), band=rb, months=R.v("alpha_months"),
                     ft_pos=R.d("ft_pos"), ft_n=R.d("ft_n"), fol_neg=R.d("fol_neg"), oth=R.d("oth_is_c"),
                     fac_t=R.d("fac_t"), r2=R.d("fac_r2"))
    # ---- tennis (simulated physics) ----
    kn = "results/spin/tennis/key_numbers.json"
    P("tn_prec_min", min(R.get(kn, "bls", "pout95_precision").values()) * 100, kn,
      "min over leads of bls.pout95_precision × 100", fmt=f0)
    P("tn_rec200", R.get(kn, "bls", "pout95_recall", "200") * 100, kn, 'bls.pout95_recall["200"] × 100', fmt=f1)
    sh = jload(TENNIS_JSON)
    P("tn_d_cm", sh["d_true_cm"], str(TENNIS_JSON), "d_true_cm (true landing, cm beyond the line)", fmt=f1)
    P("tn_call_lead", sh["called_at_eval_lead_ms"], str(TENNIS_JSON),
      "called_at_eval_lead_ms (first evaluation lead with bls P(out) >= 0.95; eval_grid_p_out)", fmt=f0)
    R.scene = "tennis"
    S["tennis"] = dict(xlo=R.d("spin_x_lo"), xhi=R.d("spin_x_hi"), rpm=R.d("spin_rpm"), prec=R.d("tn_prec_min"),
                       rec=R.d("tn_rec200"), d_cm=R.d("tn_d_cm"), lead=R.d("tn_call_lead"))
    # ---- real tennis ----
    S["tennis_real"] = dict(file=str(REAL_TENNIS))
    # ---- pipeline (results/e2e) ----
    st = {s_["stage"]: s_["ms"]["p50"] for s_ in (R.get(e2, "stage_ms") or [])}

    def sk(name):
        return f"stage_ms[stage='{name}'].ms.p50"
    bud = "budget_with_1s_simulated_feed"
    P("pp_feed", R.get(e2, bud, "feed_simulated_ms"), e2, f"{bud}.feed_simulated_ms", fmt=f0,
      note="simulated: licensed feed not purchased")
    P("pp_video", R.get(e2, "spans_ms", "capture_to_decoded", "p50"), e2, "spans_ms.capture_to_decoded.p50", fmt=f1)
    P("pp_cv_laptop", R.get(e2, "spans_ms", "decoded_to_call", "p50"), e2, "spans_ms.decoded_to_call.p50", fmt=f1)
    P("pp_cv_l4", R.get(e2, "production_gpu_reference", "online_vs_offline", "emitted_call_latency_ms", "p50"), e2,
      "production_gpu_reference.online_vs_offline.emitted_call_latency_ms.p50", fmt=f1)
    P("pp_fair", st.get("strategy rule (fair value, edge)"), e2, sk("strategy rule (fair value, edge)"), fmt=f2)
    P("pp_risk", st.get("risk check"), e2, sk("risk check"), fmt=f2)
    P("pp_order", st.get("unsigned order built"), e2, sk("unsigned order built"), fmt=f2)
    P("pp_net", st.get("network one-way (RTT/2)"), e2, sk("network one-way (RTT/2)"), fmt=f1)
    P("pp_venue", st.get("venue order delay (secondsDelay)"), e2, sk("venue order delay (secondsDelay)"), fmt=f0)
    P("pp_ours", R.get(e2, bud, "ours_capture_to_order_ready_ms", "p50"), e2,
      f"{bud}.ours_capture_to_order_ready_ms.p50", fmt=f0)
    P("pp_total", R.get(e2, bud, "total_ms", "p50"), e2, f"{bud}.total_ms.p50", fmt=f0)
    P("pp_req", R.get(e2, bud, "requirement_ms"), e2, f"{bud}.requirement_ms", fmt=f0)
    P("pp_margin", R.get(e2, bud, "margin_to_requirement_ms", "p50"), e2, f"{bud}.margin_to_requirement_ms.p50", fmt=f0)
    P("pp_under", R.get(e2, bud, "calls_under_requirement"), e2, f"{bud}.calls_under_requirement",
      fmt=lambda s_: s_.replace("/", " / "))
    P("pp_filled", R.get(e2, "fills", "timing_probe", "status", "filled"), e2, "fills.timing_probe.status.filled", fmt=f0)
    P("pp_traces", R.get(e2, "counts", "complete_order_traces"), e2, "counts.complete_order_traces", fmt=f0)
    wr = "results/webrtc/latency.json"
    P("webrtc_ms", R.get(wr, "headline", "measured_frame_send_to_emit_ms", "p50"), wr,
      "headline.measured_frame_send_to_emit_ms.p50 (loopback, engine fed 10 frames/s)", fmt=f0)
    R.scene = "pipeline"
    S["pipeline"] = {k: R.d(k) for k in ("pp_feed", "pp_video", "pp_cv_laptop", "pp_cv_l4", "pp_fair", "pp_risk",
                                         "pp_order", "pp_net", "pp_venue", "pp_ours", "pp_total", "pp_req", "pp_margin",
                                         "pp_under", "pp_filled", "pp_traces", "webrtc_ms")}
    S["pipeline"].update(feed_v=R.v("pp_feed"), ours_v=R.v("pp_ours"), net_v=R.v("pp_net"), venue_v=R.v("pp_venue"),
                         total_v=R.v("pp_total"), req_v=R.v("pp_req"))
    # ---- speed ----
    R.scene = "speed"
    sc = R.v("sweep_curves")
    curves = {rd: {per: [(float(V), sc[rd][V][per]["usd_per_day"]) for V in sorted(sc[rd], key=float)]
                   for per in ("IS", "burned_OOS")} for rd in ("tournament_lagcal", "tournament")}
    sh_ = {V: sc["tournament_lagcal"][V]["IS"]["sharpe_ann"] for V in ("0", "0.5", "1")}
    dd_ = {V: sc["tournament_lagcal"][V]["IS"]["usd_per_day"] for V in ("0", "0.5", "1")}
    S["speed"] = dict(curves=curves, be_lc=R.d("be_lc_is"), be_t=R.d("be_t_is"), be_lc_v=R.v("be_lc_is"),
                      be_t_v=R.v("be_t_is"), all_lose=R.d("all_lose_s"),
                      day3=" · ".join(f"${v:.0f}" for v in dd_.values()), sh3=" · ".join(f"{v:.0f}" for v in sh_.values()),
                      decay=R.v("decay_series"), d0=R.d("d0_is"), d1=R.d("d1_is"),
                      bands=dict(vid=R.v("band_vid"), feed=R.v("band_feed"), tv=R.v("band_tv"), stream=R.v("band_stream")))
    # ---- test: the showcase backtest match + the 1 s equity curve + rigor ----
    mj = str(EXAMPLE_MATCH_JSON)
    P("ex_pnl", R.get(mj, "summary", "pnl_usd"), mj, "summary.pnl_usd", fmt=lambda v: f"+${v:,.2f}" if v >= 0 else f"−${-v:,.2f}")
    P("ex_fills", R.get(mj, "summary", "fills"), mj, "summary.fills", fmt=f0)
    P("ex_misses", R.get(mj, "summary", "misses"), mj, "summary.misses", fmt=f0)
    ps = R.get(mj, "profitable_share")
    pooled = ps.get("pooled") or {}
    P("ex_share", (pooled.get("share_profitable") or (ps["IS"]["profitable_matches"] + ps["burned_OOS"]["profitable_matches"])
                   / (ps["IS"]["traded_matches"] + ps["burned_OOS"]["traded_matches"])) * 100, mj,
      "profitable_share.pooled.share_profitable × 100", fmt=f1)
    P("ex_traded", ps["IS"]["traded_matches"] + ps["burned_OOS"]["traded_matches"], mj,
      "profitable_share.{IS,burned_OOS}.traded_matches (sum)", fmt=f0)
    P("ex_prof", ps["IS"]["profitable_matches"] + ps["burned_OOS"]["profitable_matches"], mj,
      "profitable_share.{IS,burned_OOS}.profitable_matches (sum)", fmt=f0)
    P("ex_median", pooled.get("median_match_pnl_usd"), mj, "profitable_share.pooled.median_match_pnl_usd",
      fmt=lambda v: f"+${v:,.2f}")
    import csv as _csv
    eq = list(_csv.DictReader(open(EQUITY))) if EQUITY.exists() and jload(EQUITY_CHECK).get("all_seed_totals_match_committed") else []
    mpos = {}
    for rd in ("tournament_lagcal", "tournament"):
        by = {}
        for per in ("IS", "burned_OOS"):
            rows = [r for r in eq if r["reading"] == rd and r["period"] == per]
            last = 0.0
            for r in rows:
                v = float(r["cum_usd_mean"])
                mo = r["date"][:7]           # calendar month: a month split at the hold-out date counts once
                by[mo] = by.get(mo, 0.0) + (v - last)
                last = v
        mpos[rd] = (sum(1 for v in by.values() if v > 0), len(by))
    P("eq_months_pos", mpos["tournament_lagcal"], str(EQUITY),
      "calendar months (the IS and burned-OOS parts of August merged, as in the edge segment) with seed-mean P&L > 0, "
      "post-hoc reading",
      fmt=lambda t: f"{t[0]}/{t[1]}")
    P("eq_months_pos_pre", mpos["tournament"], str(EQUITY), "same, pre-registered reading", fmt=lambda t: f"{t[0]}/{t[1]}")
    bl = R.v("blind_rows")
    P("blind_pass", sum(1 for r in bl if r[1] == "PASS"), "several", "blind_rows verdict == PASS", fmt=f0)
    P("blind_fail", sum(1 for r in bl if r[1] == "FAIL"), "several", "blind_rows verdict == FAIL", fmt=f0)
    P("n_prereg", len(R.v("prereg_files")), "HYPOTHESIS*.md, research/**/PREREG.md, research/replay/PROTOCOL.md",
      "count of prereg_files", fmt=f0)
    rg = "results/rigor/rigor.json"
    P("pbo", R.get(rg, "pbo_cscv", "lowloss_24_sharpe", "pbo") * 100, rg, "pbo_cscv.lowloss_24_sharpe.pbo × 100", fmt=f0)
    R.scene = "test"
    S["test"] = dict(pnl=R.d("ex_pnl"), fills=R.d("ex_fills"), misses=R.d("ex_misses"), share=R.d("ex_share"),
                     traded=R.d("ex_traded"), prof=R.d("ex_prof"), median=R.d("ex_median"), eq=eq,
                     mpos=R.d("eq_months_pos"), mpos_pre=R.d("eq_months_pos_pre"), n_prereg=R.d("n_prereg"),
                     bpass=R.d("blind_pass"), bfail=R.d("blind_fail"), peeks=R.d("peeks"), trials=R.d("n_trials"),
                     dsr=R.d("dsr_is"), pbo=R.d("pbo"), is_days=R.d("lc_is_days"), oos_days=R.d("lc_oos_days"))
    # ---- profit ----
    cp = "results/capacity/capacity.json"

    def cap(key):
        g = [q for q in (R.get(cp, "growth", key) or []) if q.get("growth") == 1.0]
        return g[0]["capital_where_sharpe_halves_usd"] / 1000 if g else None
    for nm, key in (("cap_lc_is", "lagcal|cov10|IS"), ("cap_lc_oos", "lagcal|cov10|burned_OOS"),
                    ("cap_pr_is", "prereg|cov10|IS"), ("cap_pr_oos", "prereg|cov10|burned_OOS")):
        P(nm, cap(key), cp, f"growth['{key}'][growth=1.0].capital_where_sharpe_halves_usd / 1000", fmt=f0,
          note="capital where the seed-mean Sharpe halves along the size path; 10 covered matches a day")
    lc1 = sc["tournament_lagcal"]["1"]
    P("lc_is_c", lc1["IS"]["net_c_per_share"], "results/tier0/latency_sweep.json",
      'video_own120.tournament_lagcal["1"].IS.net_c_per_share', fmt=lambda v: f"+{v:.2f}¢")
    P("lc_is_ci", lc1["IS"]["net_c_per_share_ci95"], "results/tier0/latency_sweep.json",
      'video_own120.tournament_lagcal["1"].IS.net_c_per_share_ci95', fmt=lambda v: f"[{v[0]:.2f}, {v[1]:.2f}]")
    P("lc_oos_c", lc1["burned_OOS"]["net_c_per_share"], "results/tier0/latency_sweep.json",
      'video_own120.tournament_lagcal["1"].burned_OOS.net_c_per_share', fmt=lambda v: f"+{v:.2f}¢")
    P("lc_oos_ci", lc1["burned_OOS"]["net_c_per_share_ci95"], "results/tier0/latency_sweep.json",
      'video_own120.tournament_lagcal["1"].burned_OOS.net_c_per_share_ci95', fmt=lambda v: f"[{v[0]:.2f}, {v[1]:.2f}]")
    P("v2_sh_is", R.get(al, "headline", "v2_sharpe", "IS"), al, "headline.v2_sharpe.IS", fmt=f1)
    P("v2_sh_oos", R.get(al, "headline", "v2_sharpe", "OOS"), al, "headline.v2_sharpe.OOS", fmt=f1)
    R.scene = "profit"
    S["profit"] = {k: R.d(k) for k in ("lc_is_day", "lc_oos_day", "lc_is_sh", "lc_oos_sh", "t_is_day", "t_oos_day",
                                       "t_is_sh", "t_oos_sh", "lc_lag", "pre_lag", "lc_is_c", "lc_is_ci", "lc_oos_c",
                                       "lc_oos_ci", "lc_is_pnl", "lc_oos_pnl", "lc_is_days", "lc_oos_days", "cap_lc_is",
                                       "cap_lc_oos", "cap_pr_is", "cap_pr_oos", "v2_sh_is", "v2_sh_oos")}
    R.scene = "endcard"
    S["endcard"] = dict(repo=R.d("repo_url"))
    return S


# ----------------------------------------------------------------------------------------------------
# segment renderers (each: frame(t) -> uint8 canvas; events() -> sound cues; heavy setup in prepare())
# ----------------------------------------------------------------------------------------------------
class SegR:
    theme, bleed, chrome_on, label, fade_in, fade_out, still_t = "dark", False, True, None, 0.2, 0.2, None

    def __init__(self, p, D):
        self.p, self.D, self.dur = p, D, p["dur"]
        sg = next(s_ for s_ in SEGS if s_["id"] == p["id"])
        self.num, self.title = sg["num"], sg["title"]
        self.info = {}

    def events(self):
        return []

    def prepare(self):
        pass

    def label2(self, t):
        return None

    def label_at(self, t):
        """the honesty label at time t (a segment that changes subject mid-way changes its label with it)."""
        return self.label

    def t_say(self, phrase):
        """segment time at which Liam starts saying `phrase` (measured pauses, see speech_anchors)."""
        say = next(s_["say"] for s_ in SEGS if s_["id"] == self.p["id"])
        return self.p["speech_at"] - self.p["start"] + t_said(self.p, say, say.index(phrase))

    def close(self):
        pass


class Reader:
    """sequential RGB frame reader (ffmpeg), optional scale."""

    def __init__(self, path, size=(W, H), fps_out=None, crop=None):
        self.path, self.size = str(path), size
        vf = f"scale={size[0]}:{size[1]}:flags=lanczos"
        if crop:                                   # (w, h, x, y) in source pixels, applied before the scale
            vf = "crop={}:{}:{}:{},".format(*crop) + vf
        self.proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", self.path, "-vf", vf, "-f", "rawvideo",
                                      "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.i, self.buf = -1, None

    def get(self, idx):
        n = self.size[0] * self.size[1] * 3
        while self.i < idx:
            b = self.proc.stdout.read(n)
            if len(b) < n:
                break
            self.buf, self.i = b, self.i + 1
        return np.frombuffer(self.buf, np.uint8).reshape(self.size[1], self.size[0], 3).copy()

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()


def timemap(call, tref, a0, b0, t_call, dur, pre, post, rate_slow):
    """source frame per output frame: real time (4 source frames per output frame) outside the window
    [call - pre, max(call, tref) + post], rate_slow inside; the call frame lands at output time t_call."""
    n, c = int(round(dur * FPS)), int(round(t_call * FPS))
    lo, hi = call - pre, max(call, tref) + post

    def rate(s):
        return rate_slow if lo <= s <= hi else 4
    vals = {c: call}
    for k in range(c - 1, -1, -1):
        vals[k] = vals[k + 1] - rate(vals[k + 1] - 1)
    for k in range(c + 1, n):
        vals[k] = vals[k - 1] + rate(vals[k - 1] + 1)
    m = [vals[k] for k in range(n)]
    slow = [bool(lo <= s <= hi and rate_slow < 4) for s in m]
    return [min(max(s, a0), b0) for s in m], slow


class TTView:
    """one held-out OpenTTGames clip with the clean overlay drawn from the engine's own L4 log: thin ball trail,
    the engine's predicted path (orange), a small P(miss) bar, one call stamp at the exact call frame, every
    other call in the window at its own frame."""

    def __init__(self, cid, L, size=(W, H), small=False):
        x = next(q for q in jload(SELECTION)["chosen"] if q["id"] == cid)
        fl = load_flights()
        self.miss_type = (fl.get((x["video"], x["f_net"])) or {}).get("miss_type")
        self.x, self.v, self.L, self.size, self.small = x, x["video"], L, size, small
        self.a0, self.b0 = x["clip_src_frames"]
        self.call, self.tref = x["frame"], x["t_ref"]
        self.trk, self.tr = L.trk(self.v), L.trace(self.v)
        self.k = size[0] / W
        f = L.fit(self.v, self.call)
        assert f is not None and f["ok"], f"{cid}: call frame does not reproduce"
        self.call_arc = L.arc(self.v, f)
        self.tags = window_tags(x)
        self.reader = Reader(SRC / f"{cid}.mp4", size)
        self.t_call_seen = None
        self.t_ref_seen = None
        self.tag_seen = {}
        self.tag_pos = {}
        self._stamp = None
        self.n_arc = 0

    # ---- layout (QA): the stamp must not sit on the ball's path; call tags must never overlap ----
    def stamp_sprites(self):
        big = ktext("MISS" if self.x["call"] == "MISS" else "IN", 64 if not self.small else 40, 600, KOR, track=-1.0)
        sub = ktext(f"called {f0(self.x['lead_ms'])} ms early", 24 if not self.small else 17, 500, KWH)
        return big, sub

    def stamp_xy(self):
        """stamp position: the default (top, above the ball) unless the ball's observed track or the engine's
        predicted path runs through it; then the nearest candidate position the path leaves clear."""
        if self._stamp is None:
            big, sub = self.stamp_sprites()
            k, sw = self.k, self.size[0]
            half = max(big.w, sub.w) / 2
            m = 30 if self.small else 60
            px, _ = self.P(self.trk.get(self.call) or (W / 2, H / 2))
            lo_x, hi_x = m + half + (0 if self.small else 360), sw - m - half
            sx0 = min(max(px, lo_x), hi_x)
            sy0 = 236 if not self.small else 118
            obs = [self.P(self.trk[f]) for f in range(self.call - 90, self.tref + 40) if f in self.trk]
            ob, pr, _ = self.call_arc
            obs += [self.P(q) for q in list(ob) + list(pr)]
            obs = np.array(obs, float).reshape(-1, 2)
            pad = 10 * k + 4
            cands = []
            for sy in (sy0, sy0 + 150 * k):
                for fx in (None, 0.5, 0.36, 0.64, 0.24, 0.76):
                    sx = sx0 if fx is None else min(max(fx * sw, lo_x), hi_x)
                    bx0, bx1 = sx - half - pad, sx + half + pad
                    by0, by1 = sy - big.h - pad, sy + 2 + sub.h + pad
                    hits = int(np.sum((obs[:, 0] > bx0) & (obs[:, 0] < bx1) & (obs[:, 1] > by0) & (obs[:, 1] < by1)))
                    cands.append((hits, sy != sy0, abs(sx - sx0), sx, sy))
            best = min(cands)
            self._stamp = (best[3], best[4])
        return self._stamp

    def stamp_box(self):
        big, sub = self.stamp_sprites()
        sx, sy = self.stamp_xy()
        half = max(big.w, sub.w) / 2
        return (sx - half, sy - big.h, sx + half, sy + 2 + sub.h)

    def tag_place(self, tg, w1, w2, px, yy, tout):
        """first placement of a call tag, kept for its lifetime: shift up (then down) until it overlaps neither
        the call stamp, the P(miss) bar nor a tag still on screen."""
        if tg["frame"] in self.tag_pos:
            return self.tag_pos[tg["frame"]]
        sw, sh = self.size
        wmax = max(w1.w, w2.w)
        hh = w1.h + 4 + w2.h
        m = 8
        px = min(max(px, m + wmax / 2), sw - m - wmax / 2)
        boxes = [self.stamp_box(), (0, 0, (GM + 240) if not self.small else 190, (140 if not self.small else 40))]
        for f_, (qx, qy, qw, qh1, qh2) in self.tag_pos.items():
            t0 = self.tag_seen.get(f_)
            if t0 is not None and tout - t0 < 1.25:
                boxes.append((qx - qw / 2, qy - qh1, qx + qw / 2, qy + 4 + qh2))
        g = 4
        # the ball's own path while the tag is on screen (about 1.2 s; at most 150 source frames)
        path = np.array([self.P(self.trk[f]) for f in range(tg["frame"] - 6, tg["frame"] + 150) if f in self.trk],
                        float).reshape(-1, 2)

        def clear(y):
            b = (px - wmax / 2 - g, y - w1.h - g, px + wmax / 2 + g, y + 4 + w2.h + g)
            if len(path) and np.any((path[:, 0] > b[0] - 8) & (path[:, 0] < b[2] + 8) & (path[:, 1] > b[1] - 8) &
                                    (path[:, 1] < b[3] + 8)):
                return False
            return all(b[2] <= c[0] or b[0] >= c[2] or b[3] <= c[1] or b[1] >= c[3] for c in boxes)
        best = yy
        for step in (0, -1, -2, -3, 1, 2, 3, 4):
            y = yy + step * (hh + 2 * g)
            if w1.h + 4 <= y <= sh - w2.h - 8 and clear(y):
                best = y
                break
        self.tag_pos[tg["frame"]] = (px, best, wmax, w1.h, w2.h)
        return self.tag_pos[tg["frame"]]

    def P(self, pt):
        return pt[0] * self.k, pt[1] * self.k

    def outcome_word(self):
        if self.x["label"] == "BOUNCE":
            return "bounce"
        return "hits the net" if self.miss_type == "net" else "passes the end line"

    def render(self, s, tout):
        """frame for source frame s at output time tout (s); returns uint8 image of self.size."""
        img = self.reader.get(s - self.a0)
        k = self.k
        ly = Lyr(self.size[0], self.size[1])
        called = s >= self.call
        if called and self.t_call_seen is None:
            self.t_call_seen = tout
        if s >= self.tref and self.t_ref_seen is None:
            self.t_ref_seen = tout
        trn = self.tr.get(s)
        arc = None
        if not called and trn is not None and trn[3]:
            q = self.L.fit(self.v, s)
            if q is not None and q["ok"] and q["npts"] >= 10:
                arc, al = self.L.arc(self.v, q), 0.75
                self.n_arc += 1
        elif called:
            al = 1.0 if s <= self.tref + 12 else max(0.0, 1 - (s - self.tref - 12) / 24)
            arc = self.call_arc if al > 0 else None
        if arc is not None:
            ob, pr, land = arc
            ly.line([self.P(p_) for p_ in pr], KOR, max(1, int(round(3 * k))) if not self.small else 2, al * 0.95)
            if land is not None:
                ly.circle(self.P(land["px"]), 6 * k + 2, KOR, -1, al)
        hist = [(f_, self.trk[f_]) for f_ in range(s - 28, s + 1) if f_ in self.trk]
        for i in range(1, len(hist)):
            (fa, pa), (fb, pb) = hist[i - 1], hist[i]
            if fb - fa > 4:
                continue
            q = (s - fb) / 28.0
            ly.line([self.P(pa), self.P(pb)], KWH, max(1, int(round((1 + 3 * (1 - q)) * max(k, 0.5)))), (1 - q) ** 1.5 * 0.95)
        if s in self.trk:
            ly.circle(self.P(self.trk[s]), 12 * k + 3, KWH, 2, 0.9)
        if self.t_ref_seen is not None:
            q = (tout - self.t_ref_seen) / 0.5
            pt = self.trk.get(self.tref) or (hist[-1][1] if hist else None)
            if 0 <= q <= 1 and pt is not None:
                ly.circle(self.P(pt), (14 + 50 * ease3(q)) * k + 4, KWH, 2, 1 - q)
        comp(img, ly)
        # P(miss) bar (small), top-left of the view
        bx, by = (GM if not self.small else 26), (118 if not self.small else 22)
        bw = 220 if not self.small else 150
        pv = (self.tr.get(self.call) if called else trn)
        p = pv[2] if pv is not None else 0.0
        tau = self.L.tau_on
        sz = 17 if not self.small else 14
        blit(img, ktext("P(miss)", sz, 500, (200, 200, 205)), bx, by, "ls")
        blit(img, ktext(f"{p:.2f}" if pv is not None else "–", sz, 600, KWH, tnum=True), bx + bw, by, "rs")
        y0 = by + 10
        img[y0:y0 + 3, bx:bx + bw] = (img[y0:y0 + 3, bx:bx + bw].astype(np.float32) * 0.6 + 255 * 0.4 * 0.5).astype(np.uint8)
        fw = int(bw * max(0.0, min(1.0, p)))
        col = np.array(KOR if (called and self.x["call"] == "MISS") else KWH, np.uint8)
        if fw > 0:
            img[y0:y0 + 3, bx:bx + fw] = col
        tx = bx + int(bw * tau)
        img[y0 - 4:y0 + 7, tx:tx + 2] = 255
        # other calls the engine made in this window, at their own frames
        for tg in self.tags:
            if s >= tg["frame"] and tg["frame"] not in self.tag_seen:
                self.tag_seen[tg["frame"]] = tout
            t0 = self.tag_seen.get(tg["frame"])
            if t0 is None:
                continue
            a = min(1.0, (tout - t0) / 0.12) * (1 - ease3((tout - t0 - 0.9) / 0.3))
            if a <= 0.01:
                continue
            pt = self.trk.get(tg["frame"]) or tuple(tg["xy"] or (W / 2, H / 2))
            px, py = self.P(pt)
            w1 = ktext(tg["word"], 22 if not self.small else 16, 600, KWH)
            w2 = ktext(tg["sub"], 15 if not self.small else 12, 400, (205, 205, 210))
            yy = max(60 * k + 20, py - 40 * k - 30)
            px, yy = self.tag_place(tg, w1, w2, px, yy, t0)[:2]
            blit(img, w1, px, yy, "mb", a)
            blit(img, w2, px, yy + 4, "ma", a)
        # the call stamp
        if self.t_call_seen is not None:
            q = (tout - self.t_call_seen) / 0.2
            a, scl = min(1.0, max(q, 0.0)), 0.96 + 0.04 * ease3(q)
            big, sub = self.stamp_sprites()
            sx, sy = self.stamp_xy()
            blit(img, big, sx, sy, "mb", a, scl)
            blit(img, sub, sx, sy + 2, "ma", a, scl)
        if self.t_ref_seen is not None:
            q = min(1.0, (tout - self.t_ref_seen) / 0.25)
            pt = self.trk.get(self.tref) or (hist[-1][1] if hist else None)
            if pt is not None:
                px, py = self.P(pt)
                w_ = ktext(self.outcome_word(), 18 if not self.small else 13, 500, (220, 220, 225))
                ox = min(max(px, 40 + w_.w / 2), self.size[0] - 40 - w_.w / 2)
                oy = min(max(py + 30 * k + 12, 160 if not self.small else 60), self.size[1] - 40)
                sb = self.stamp_box()           # never beside or under the call stamp
                if not (ox + w_.w / 2 + 16 <= sb[0] or ox - w_.w / 2 - 16 >= sb[2] or oy + w_.h + 8 <= sb[1]
                        or oy - 8 >= sb[3]):
                    oy = sb[3] + 18 * k + 6
                blit(img, w_, ox, oy, "ma", q)
        return img

    def close(self):
        self.reader.close()


class SegColdOpen(SegR):
    bleed, chrome_on, label, fade_in = True, False, None, 0.0

    def prepare(self):
        L = EngineLog()
        self.view = TTView("test_2_f2819_miss", L)
        x = self.view.x
        self.t_call, self.t_foot = 1.4, 3.35
        self.map, self.slow = timemap(x["frame"], x["t_ref"], *x["clip_src_frames"], self.t_call, self.t_foot,
                                      pre=30, post=16, rate_slow=1)
        self.still_t = self.t_call + 0.9

    def events(self):
        return [(1.4, "hit")]

    def frame(self, t):
        i = int(round(t * FPS))
        if i < len(self.map):
            cv = self.view.render(self.map[i], t)
            vignette(cv)
            top_grad(cv)
            bottom_grad(cv, 760, 0.6)
            k = 1 - ease3((t - (self.t_foot - 0.35)) / 0.35)
            if k < 1:
                cv = (cv.astype(np.float32) * k).astype(np.uint8)
            chrome(cv, "", "", f"{LABEL_FOOT} · game {self.view.v}", "dark", 1.0,
                   label2="¼ speed" if self.slow[i] else "real time", footage=True)
            return cv
        cv = canvas()
        k = appear(t, self.t_foot + 0.05, 0.7)
        blit(cv, ktext("COURTSIDE", 132, 600, KWH, track=14), W / 2, H / 2 + 40, "ms", k, 0.96 + 0.04 * k)
        return cv

    def close(self):
        self.view.close()


class SegStrategy(SegR):
    LINES = [("Our computer vision", False), ("calls the point", False), ("before the ball lands,", True),
             ("so we trade the", False), ("Polymarket match price", False), ("before it reprices.", True)]

    def prepare(self):
        D = self.D
        self.t_line = [self.t_say(s_) - 0.15 for s_, _ in self.LINES]   # each line as Liam reaches it
        self.t_tl = self.t_line[3]
        self.rail = Rail([dict(v=f"{D['band']} s", lab=f"after each point, the price catches up (inferred; book vs "
                                                        f"official point stamp measured on {D['stale_n']} live points)",
                               t=self.t_line[3] + 0.2, count=False),
                          dict(v=f"${D['stale']}", lab="of orders still resting at the old price 250 ms before it "
                                                        "moves (median stale depth, one recorded day)",
                               t=self.t_line[4] + 0.4)],
                         head="The idea in numbers")
        x0, x1 = CX0, CX1
        self.X = lambda s_: x0 + (x1 - x0) * (s_ + 0.8) / 2.8   # noqa: E731  -0.8 .. 2.0 s around the bounce
        ly = Lyr()
        y = 820
        ly.line([(x0, y), (x1, y)], KHAIR_D, 2)
        ly.rect(self.X(D["b0"]), y - 5, self.X(D["b1"]), y + 5, KGREY, 1.0, r=5)
        self.tl = ly
        self.still_t = self.dur - 0.3

    def events(self):
        return self.rail.events()

    def frame(self, t):
        cv = canvas()
        y = 268
        for i, (s_, hot) in enumerate(self.LINES):
            k = appear(t, self.t_line[i], 0.5)
            blit(cv, ktext(s_, 60, 600, KOR if hot else KWH, track=-1.2), CX0, y + (1 - k) * 12, "ls", k)
            y += 74
        kt = appear(t, self.t_tl, 0.7)
        if kt > 0:
            comp(cv, self.tl, kt, xr=CX0 + (CX1 - CX0 + 4) * ease3((t - self.t_tl) / 0.9))
            yb = 820
            for xs, col, lab, tt in ((-0.3, KOR, "model calls it", 0.2), (0.0, KWH, "ball lands", 0.45),
                                     ((self.D["b0"] + self.D["b1"]) / 2, KGREY, f"price catches up, {self.D['band']} s", 0.7)):
                kk = appear(t, self.t_tl + tt, 0.5)
                X = self.X(xs)
                if col != KGREY:
                    cv_dot(cv, X, yb, 8, col, kk)
                blit(cv, ktext(lab, 19, 500, col if col != KGREY else (180, 180, 185)), X, yb + 48, "ms", kk)
            blit(cv, ktext("seconds around the bounce", 16, 400, KGREY), CX0, yb + 86, "ls", kt)
        self.rail.draw(cv, t)
        return cv


def cv_dot(cv, x, y, r, col, k=1.0):
    ly = Lyr(int(2 * r + 8), int(2 * r + 8)).circle((r + 4, r + 4), r, col)
    s_ = Spr(ly.rgb.astype(np.float32), ly.a.astype(np.float32) / 255.0, 0)
    blit(cv, s_, x, y, "mm", k)


def logx(v, x0, x1, lo=0.05, hi=60.0):
    return x0 + (x1 - x0) * (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))


class SegEdge(SegR):
    label = "Polymarket public tapes · wallets' own fills, not our trades"

    def prepare(self):
        D = self.D
        # the ladder (with the reprice band) stays up while Liam explains the reprice; the months chart comes in
        # with "The fastest traders"
        self.t2 = max(4.7, self.t_say("The fastest") - 0.4)
        self.rows = [("Venue camera", "fastest; not offered to traders", D["cam"]),
                     ("Licensed betting video", "vendor-stated", D["vid"]),
                     ("Official point feed", "umpire tablet; lag not measured", D["feed"]),
                     ("TV broadcast", "cited surveys", D["tv"]),
                     ("Public match stream", f"we measured {D['setka_d']} s (preliminary)", [D["setka"], D["setka"]]),
                     ("Public score feeds", f"measured: ESPN {D['espn_d']} s, WTA {D['wta_d']} s", [D["espn"], D["wta"]])]
        self.bx0, self.bx1 = 600, CX1
        X = lambda v: logx(v, self.bx0, self.bx1)  # noqa: E731
        ly = Lyr()
        y0, dy = 286, 88                      # below the title and its plain-language subtitle
        for i, (_, _, b) in enumerate(self.rows):
            y = y0 + i * dy + 26
            if b[1] - b[0] < 1e-6 or i == 5:
                for v in b:
                    ly.circle((X(v), y), 6, KGREY)
            else:
                ly.rect(X(b[0]), y - 4, max(X(b[1]), X(b[0]) + 8), y + 4, KGREY, 1.0, r=4)
        ya = y0 + 6 * dy + 2
        ly.line([(self.bx0, ya), (self.bx1, ya)], KHAIR_D, 2)
        self.ladder = ly
        band = Lyr()
        band.rect(X(D["band"][0]), y0 - 20, X(D["band"][1]), ya, KWH, 0.10)
        band.dotted((X(1.0), y0 - 30), (X(1.0), ya), KOR, 2, 4, 7)
        self.band, self.ya, self.y0, self.dy, self.X = band, ya, y0, dy, X
        # months chart
        ms = D["months"]
        self.cx0, self.cx1, self.cy0 = CX0, CX1, 560
        n = len(ms)
        bw = (self.cx1 - self.cx0) / n
        sc_ = 62.0   # px per cent
        ch = Lyr()
        oos = [i for i, m in enumerate(ms) if m["period"] == "OOS"]
        if oos:
            ch.rect(self.cx0 + bw * oos[0], self.cy0 - 230, self.cx1, self.cy0 + 230, KWH, 0.06)
        for i, m in enumerate(ms):
            xc = self.cx0 + bw * (i + 0.5)
            ch.rect(xc - bw * 0.36, self.cy0 - m["fast"] * sc_, xc - bw * 0.04, self.cy0, KWH, 1.0)
            ch.rect(xc + bw * 0.04, self.cy0, xc + bw * 0.36, self.cy0 - m["copy"] * sc_, KRED_D, 1.0)
        ch.line([(self.cx0, self.cy0), (self.cx1, self.cy0)], KHAIR_D, 2)
        self.chart, self.bw, self.ms, self.oos = ch, bw, ms, oos
        self.rail = Rail([dict(v=D["oth"], lab="per share, everyone slower than the fast tier (in-sample month mean)",
                               t=1.2, col=KRED_D),
                          dict(v=f"t = {D['fac_t']}", lab="t-stat of the fast tier's alpha after four risk factors "
                                                          "(Newey-West): far beyond chance", t=2.2),
                          dict(v=f"R² {D['r2']}%", lab="of it explained by risk factors", t=3.0),
                          dict(v=f"{D['ft_pos']}/{D['ft_n']}", lab="months the fast tier made money (traded within 3 s "
                                                                  "of a point; 30 s markout, after fees)", t=self.t2 + 0.6,
                               count=False),
                          dict(v=f"{D['fol_neg']}/{D['ft_n']}", lab="months copying them 3 s later lost money",
                               t=self.t2 + 1.4, col=KRED_D, count=False)],
                         head="The edge in numbers", vsize=44, gap=26)
        self.still_t = self.dur - 0.3

    def events(self):
        return self.rail.events()

    def frame(self, t):
        cv = canvas()
        D = self.D
        k1 = 1 - ease3((t - self.t2 + 0.5) / 0.5)
        if k1 > 0:
            blit(cv, ktext("Who learns the point first", 40, 600, KWH, track=-0.6), CX0, 150, "ls", k1 * appear(t, 0.1))
            blit(cv, ktext("Polymarket's price runs from 0 to $1: a player's chance to win. The first to learn the point "
                           "trades the old price.", 19, 400, KGREY), CX0, 188, "ls", k1 * appear(t, 0.2))
            for i, (nm, sub, _) in enumerate(self.rows):
                y = self.y0 + i * self.dy
                k = appear(t, 0.25 + 0.22 * i, 0.5) * k1
                blit(cv, ktext(nm, 22, 500, KWH), CX0, y + 26, "ls", k)
                blit(cv, ktext(sub, 16, 400, KGREY), CX0, y + 49, "ls", k)
            kl = appear(t, 0.4, 0.6) * k1
            comp(cv, self.ladder, kl, xr=self.bx0 + (self.bx1 - self.bx0 + 12) * ease3((t - 0.4) / 1.6))
            kb = appear(t, 1.6, 0.6) * k1
            comp(cv, self.band, kb)
            blit(cv, ktext("1 s licensed feed (our baseline)", 16, 500, KOR), self.X(1.0) - 8, self.y0 - 40, "rs", kb)
            blit(cv, ktext(f"price catches up {D['band'][0]:.1f}–{D['band'][1]:.1f} s after the point", 16, 400,
                           (190, 190, 195)), self.X(D["band"][1]) + 10, self.y0 - 40, "ls", kb)
            for v in (0.05, 0.1, 0.5, 1, 5, 10, 60):
                blit(cv, ktext(f"{v:g}" + (" s" if v in (1, 60) else ""), 15, 400, KGREY), self.X(v), self.ya + 26, "ms", kl)
            blit(cv, ktext("seconds after the point is over (log scale)", 15, 400, KGREY), self.bx0, self.ya + 52, "ls", kl)
        k2 = appear(t, self.t2, 0.6)
        if k2 > 0:
            blit(cv, ktext(f"{D['ft_pos']} of {D['ft_n']} months", 64, 600, KWH, track=-1.5), CX0, 200, "ls", k2)
            blit(cv, ktext("the fastest traders made money; copying them 3 s later lost every month", 21, 400, KGREY),
                 CX0, 240, "ls", k2)
            comp(cv, self.chart, k2, xr=self.cx0 + (self.cx1 - self.cx0 + 4) * ease3((t - self.t2 - 0.2) / 1.6))
            seen = set()
            for i, m in enumerate(self.ms):
                xc = self.cx0 + self.bw * (i + 0.5)
                mo = dt.date(int(m["month"][:4]), int(m["month"][5:7]), 1).strftime("%b")
                if m["month"] in seen:          # a month split at the hold-out date: its second bar is "late <month>"
                    mo = "late " + mo
                seen.add(m["month"])
                blit(cv, ktext(mo, 15, 400, KGREY), xc, self.cy0 + 250, "ms", k2)
            if self.oos:
                blit(cv, ktext("held out", 15, 500, KGREY), self.cx0 + self.bw * self.oos[0] + 8, self.cy0 - 210, "ls", k2)
                blit(cv, ktext("August split at the hold-out date", 14, 400, KGREY), self.cx0 + self.bw * self.oos[0] + 8,
                     self.cy0 - 190, "ls", k2)
            blit(cv, ktext("fast tier, ¢ per share", 16, 500, KWH), CX0, self.cy0 - 230, "ls", k2)
            blit(cv, ktext("copy 3 s later", 16, 500, KRED_D), CX0, self.cy0 + 222, "ls", k2)
        self.rail.draw(cv, t)
        return cv


class SegTT(SegR):
    bleed, label = True, LABEL_FOOT
    SHOTS = [("test_4_f5751_miss", 0.0, 3.3), ("test_4_f9837_miss", 3.3, 6.6)]
    GRID = [("test_1_f313_bounce", 0.9), ("test_3_f3442_bounce", 1.4), ("test_5_f4099_bounce", 1.9),
            ("test_6_f9190_bounce", 1.15), ("test_7_f7145_bounce", 3.1)]

    def prepare(self):
        D = self.D
        self.L = EngineLog()
        self.views, self.maps = {}, {}
        for cid, a, b in self.SHOTS:
            v = TTView(cid, self.L)
            x = v.x
            self.views[cid] = v
            self.maps[cid] = timemap(x["frame"], x["t_ref"], *x["clip_src_frames"], 1.3, b - a, pre=24, post=30,
                                     rate_slow=2)
        self.g0 = self.SHOTS[-1][2]
        gd = self.dur - self.g0
        cw, ch = 632, 356
        gx0 = (W - 2 * cw - 12) // 2
        gy0 = 100                   # below the two-line honesty label
        self.cells = [(gx0, gy0), (gx0 + cw + 12, gy0), (gx0, gy0 + ch + 12), (gx0 + cw + 12, gy0 + ch + 12)]
        for cid, tc in self.GRID:
            v = TTView(cid, self.L, (cw, ch), small=True)
            x = v.x
            self.views[cid] = v
            dd = gd if cid not in ("test_6_f9190_bounce", "test_7_f7145_bounce") else (2.3 if cid.startswith("test_6") else gd - 2.3)
            tcc = tc if not cid.startswith("test_7") else tc - 2.3
            self.maps[cid] = timemap(x["frame"], x["t_ref"], *x["clip_src_frames"], tcc, dd, pre=10, post=10, rate_slow=2)
        self.band1 = Rail([dict(v=D["games"], lab="held-out games, never seen in training", t=0.6),
                           dict(v=D["frames"], lab=f"frames streamed, {D['dropped']} dropped (NVIDIA L4, 120 fps, real time)",
                                t=1.0),
                           dict(v=D["miss"], lab=f"MISS calls in all; {D['mob']} on a ball labelled in", t=1.4),
                           dict(v=f"{D['lat']} ms", lab="frame to call, p50", t=1.8)], mode="band")
        self.band2 = Rail([dict(v=f"{D['inr']} / {D['inm']}", lab="IN calls right, on balls the dataset labelled",
                                t=self.g0 + 0.3),
                           dict(v=f"{D['rtp']} / {D['nmf']}", lab="labelled misses the live engine called before the "
                                                                   "ball got there", t=self.g0 + 0.7),
                           dict(v=D["unm"], lab=f"of {D['calls']} calls were on balls the dataset never labelled "
                                                "(cannot be scored)", t=self.g0 + 1.1),
                           dict(v=f"{D['tp50']} / {D['n50']}", lab="MISS calls right at 50 ms (offline test, "
                                                                     "pre-registered)", t=self.g0 + 1.5)], mode="band",
                          band_y=872)
        self.still_t = self.SHOTS[0][1] + 1.3 + 0.6

    def events(self):
        ev = [(a + 1.3, "hit") for _, a, _ in self.SHOTS]
        ev += [(self.g0 + tc, "hit") for _, tc in self.GRID]
        return ev + self.band1.events() + self.band2.events()

    def label2(self, t):
        for cid, a, b in self.SHOTS:
            if a <= t < b:
                i = min(int(round((t - a) * FPS)), len(self.maps[cid][1]) - 1)
                return f"game {self.views[cid].v} · " + ("½ speed" if self.maps[cid][1][i] else "real time")
        return "7 held-out games · real time, ½ speed at each call"

    def frame(self, t):
        for cid, a, b in self.SHOTS:
            if a <= t < b:
                m, _ = self.maps[cid]
                i = min(int(round((t - a) * FPS)), len(m) - 1)
                cv = self.views[cid].render(m[i], t - a)
                vignette(cv)
                top_grad(cv)
                bottom_grad(cv, 640, 0.85)
                self.band1.draw(cv, t)
                return cv
        cv = canvas()
        tg = t - self.g0
        for j, (cid, tc) in enumerate(self.GRID):
            cell = j if j < 4 else 3
            if cid.startswith("test_6") and tg >= 2.3:
                continue
            if cid.startswith("test_7") and tg < 2.3:
                continue
            m, _ = self.maps[cid]
            tl = tg - (2.3 if cid.startswith("test_7") else 0.0)
            i = min(max(int(round(tl * FPS)), 0), len(m) - 1)
            im = self.views[cid].render(m[i], tl)
            x0, y0 = self.cells[cell]
            cv[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] = im
            blit(cv, ktext(f"game {self.views[cid].v}", 14, 500, (210, 210, 215)), x0 + im.shape[1] - 20, y0 + 22, "rs")
        k = appear(tg, 0.0, 0.35)
        if k < 1:
            cv = (cv.astype(np.float32) * k).astype(np.uint8)
        # what to look at (first-time viewer QA)
        blit(cv, ktext("IN = the model says the ball will land on the table. Each stamp appears at the frame the "
                       "model made the call.", 18, 400, (200, 200, 205)), W / 2, 848, "ms", appear(tg, 0.3, 0.5))
        self.band2.draw(cv, t)
        return cv

    def close(self):
        for v in self.views.values():
            v.close()


class SegTennisReal(SegR):
    bleed, fade_in = True, 0.0

    def prepare(self):
        self.ok = REAL_TENNIS.exists()
        lic = REAL_TENNIS_LICENSE.read_text() if REAL_TENNIS_LICENSE.exists() else ""
        m = re.search(r'Tennis footage: "([^"]+)" by ([^,]+), Pexels \(Pexels License\)', lic)
        self.credit = (f"Real rally: “{m.group(1)}” by {m.group(2)}, Pexels (Pexels License)" if m else
                       "Real rally (licensed; see tennis_real/LICENSE.md)")
        self.label = "real licensed rally (Pexels License) · our tennis tracker's ball trail · no line calls on this clip"
        if self.ok:
            self.reader = Reader(REAL_TENNIS, (W, H))
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                                "-of", "csv=p=0", str(REAL_TENNIS)], capture_output=True, text=True).stdout.strip()
            a, b = (r.split("/") + ["1"])[:2]
            self.fps = float(a) / float(b or 1)
        self.still_t = 2.0

    def frame(self, t):
        if not self.ok:
            cv = canvas()
            blit(cv, ktext("real tennis clip pending", 30, 500, KGREY), W / 2, H / 2, "mm")
            return cv
        cv = self.reader.get(int(t * self.fps))
        top_grad(cv, 210, 0.8)          # the honesty label sits over bright sky
        bottom_grad(cv, 760, 0.6)
        return cv

    def close(self):
        if self.ok:
            self.reader.close()


class Cam:
    def __init__(self, pos, tgt, f=1150.0, cx=W / 2, cy=H / 2):
        self.pos, self.f, self.cx, self.cy = np.asarray(pos, float), f, cx, cy
        F = np.asarray(tgt, float) - self.pos
        F /= np.linalg.norm(F)
        Rr = np.cross(F, [0, 0, 1.0])
        Rr /= np.linalg.norm(Rr)
        self.F, self.R, self.U = F, Rr, np.cross(Rr, F)

    def p(self, X):
        d = np.asarray(X, float) - self.pos
        z = d @ self.F
        if z < 0.05:
            return None
        return self.cx + self.f * (d @ self.R) / z, self.cy - self.f * (d @ self.U) / z

    def seg(self, a, b, n=24):
        out = []
        for u in np.linspace(0, 1, n):
            q = self.p(np.asarray(a) + (np.asarray(b) - np.asarray(a)) * u)
            if q is not None:
                out.append(q)
        return out

    def scale(self, X, r):
        d = np.asarray(X, float) - self.pos
        z = d @ self.F
        return self.f * r / max(z, 0.05)


_FADE = {}


def fade_layer(ly, x0, x1, y0, y1):
    """soft edges for a full-frame layer: alpha 1 left of x0 / above y0, falling linearly to 0 at x1 / y1
    (no hard clip where a 3D court leaves the content columns or runs under the captions)."""
    key = (x0, x1, y0, y1)
    if key not in _FADE:
        cx = np.clip((x1 - np.arange(W, dtype=np.float32)) / (x1 - x0), 0, 1)
        ry = np.clip((y1 - np.arange(H, dtype=np.float32)) / (y1 - y0), 0, 1)
        _FADE[key] = ry[:, None] * cx[None, :]
    m = _FADE[key]
    ly.a = (ly.a.astype(np.float32) * m + 0.5).astype(np.uint8)
    ly.rgb = (ly.rgb.astype(np.float32) * m[..., None] + 0.5).astype(np.uint8)
    ly._bb = None
    return ly


class SegTennis(SegR):
    label = "simulated physics: Hawk-Eye-class camera model (340 fps, 3.6 mm noise) · not real footage"

    def prepare(self):
        from src import hawkeye as Hk
        D = self.D
        sh = jload(TENNIS_JSON)
        self.sh, self.Hk = sh, Hk
        self.traj, self.tt = np.array(sh["traj"]), np.array(sh["traj_t"])
        self.tland = sh["tland_s"]
        self.land = np.array(sh["land_true"])
        ev = {c["k"]: c for c in sh["eval_grid_check"]}
        self.fits = [f for f in sh["fits"] if f["k"] in ev]          # the evaluation's own decision frames
        for f in self.fits:
            f["lead_eval"] = ev[f["k"]]["lead_ms"]
        self.fits.sort(key=lambda f: f["t"])
        # flight shown from T0 to T1 in slow motion; the slow-motion rate is set so that the evaluation's decision
        # point with the call lands as Liam says "called 200 milliseconds" (QA: it came 1.5 s after him)
        f_call = next(f["t"] for f in self.fits if f["lead_eval"] == sh["called_at_eval_lead_ms"])
        self.T0 = 0.5
        self.T1 = min(6.0, max(3.6, self.T0 + (self.t_say("called 200") - self.T0) * self.tland / f_call))
        self.slow = (self.T1 - self.T0) / self.tland
        self.t_call = self.T0 + f_call * self.slow
        self.rail = Rail([dict(v=f"{D['xlo']}–{D['xhi']}×", lab="less landing error than the no-spin tracker, "
                                                                  "300–400 ms before the bounce", t=0.6, count=False),
                          dict(v=f"{D['prec']}%", lab="OUT calls right at P(out) ≥ 0.95, every lead (simulated)", t=1.4),
                          dict(v=f"{D['rec']}%", lab="of OUT balls called 200 ms before the bounce", t=2.2),
                          dict(v=f"~{D['rpm']} rpm", lab="spin error at 200 ms (shots spin 1,200–3,500 rpm)", t=3.0)],
                         head="Spin-aware tracker · simulated", vsize=46, gap=28)
        self.still_t = self.t_call + 0.8

    def events(self):
        return [(self.t_call, "hit")] + self.rail.events()

    def cam(self, t):
        lx, ly_ = self.land
        u = ease3((t - 1.2) / 5.0)
        p0, g0 = np.array([0.4, -9.5, 5.2]), np.array([0.0, 14.0, 0.0])
        p1, g1 = np.array([lx * 0.35, 9.5, 3.2]), np.array([lx * 0.8, 21.5, 0.0])
        return Cam(p0 + (p1 - p0) * u, g0 + (g1 - g0) * u, 1000.0, cx=470, cy=H / 2 + 120)

    # top view of the landing zone, to scale (Hawk-Eye style): 80 cm x 64 cm around the true landing
    IX0, IY0, IW, IH = 760, 250, 440, 352

    def top(self, x, y):
        lx, ly_ = self.land
        wx0, wy0 = lx - 0.40, ly_ - 0.40
        return self.IX0 + (x - wx0) / 0.80 * self.IW, self.IY0 + self.IH - (y - wy0) / 0.64 * self.IH

    def inset(self, cv, t, cur, landed):
        Hk = self.Hk
        k = appear(t, 0.9, 0.6)
        if k <= 0:
            return
        ly = Lyr()
        x0, y0, x1, y1 = self.IX0, self.IY0, self.IX0 + self.IW, self.IY0 + self.IH
        ly.rect(x0, y0, x1, y1, KHAIR_D, 1.0, r=10).rect(x0 + 2, y0 + 2, x1 - 2, y1 - 2, KBK, 1.0, r=9)
        lx, ly_ = self.land
        # baseline (y = 23.77) and singles sideline (x = -4.115), clipped to the window
        bx0, by0 = self.top(lx - 0.40, Hk.BASELINE)
        bx1, _ = self.top(min(lx + 0.40, 9), Hk.BASELINE)
        sx_, sy0 = self.top(-Hk.SIDELINE, ly_ - 0.40)
        _, sy1 = self.top(-Hk.SIDELINE, min(Hk.BASELINE, ly_ + 0.24))
        ly.line([(max(bx0, sx_), by0), (bx1 - 4, by0)], KWH, 3)
        if x0 < sx_ < x1:
            ly.line([(sx_, sy0 - 4), (sx_, by0)], KWH, 3)
        if cur is not None:
            mu, cov = np.array(cur["land"]), np.array(cur["cov"])
            ev_, evec = np.linalg.eigh(cov)
            ring = []
            for a in np.linspace(0, 2 * math.pi, 90):
                off = evec @ (np.sqrt(np.maximum(ev_, 1e-12)) * math.sqrt(5.991) * np.array([math.cos(a), math.sin(a)]))
                q = self.top(mu[0] + off[0], mu[1] + off[1])
                ring.append((min(max(q[0], x0 + 3), x1 - 3), min(max(q[1], y0 + 3), y1 - 3)))
            ly.poly(ring, KOR, 0.25)
            ly.line(ring + [ring[0]], KOR, 2)
            bq = self.top(*cur["baseline_land"])
            if x0 + 8 < bq[0] < x1 - 8 and y0 + 8 < bq[1] < y1 - 8:
                ly.circle(bq, 6, KGREY)
        if landed:
            c = self.top(lx, ly_)
            ly.circle(c, 0.033 / 0.80 * self.IW, KWH, 2, appear(t, self.T1, 0.3))
        comp(cv, ly, k)
        blit(cv, ktext("landing zone from above, to scale", 15, 500, (200, 200, 205)), x0, y0 - 14, "ls", k)
        blit(cv, ktext("baseline", 14, 400, KGREY), x1 - 12, by0 - 10, "rs", k)
        sbw = 0.10 / 0.80 * self.IW
        blit(cv, ktext("10 cm", 13, 400, KGREY), x1 - 16, y1 - 14, "rs", k)
        if k > 0.5:
            cv[int(y1 - 34):int(y1 - 32), int(x1 - 16 - sbw):int(x1 - 16)] = (134, 134, 139)
        if landed:
            c = self.top(lx, ly_)
            blit(cv, ktext(f"lands {self.D['d_cm']} cm out", 16, 600, KWH), c[0], c[1] - 34, "mb", appear(t, self.T1 + 0.2, 0.3))

    def frame(self, t):
        cv = canvas()
        Hk = self.Hk
        C_ = self.cam(t)
        ly = Lyr()
        kc = appear(t, 0.05, 0.6)
        BL, SL, DL, NY = Hk.BASELINE, Hk.SIDELINE, 5.485, Hk.NET_Y
        lines = [((-DL, 0, 0), (DL, 0, 0)), ((-DL, BL, 0), (DL, BL, 0)), ((-DL, 0, 0), (-DL, BL, 0)),
                 ((DL, 0, 0), (DL, BL, 0)), ((-SL, 0, 0), (-SL, BL, 0)), ((SL, 0, 0), (SL, BL, 0)),
                 ((-SL, NY - 6.40, 0), (SL, NY - 6.40, 0)), ((-SL, NY + 6.40, 0), (SL, NY + 6.40, 0)),
                 ((0, NY - 6.40, 0), (0, NY + 6.40, 0))]
        for a, b in lines:
            pts = C_.seg(a, b, 40)
            if len(pts) > 1:
                ly.line(pts, KWH, 2, 0.85)
        net = C_.seg((-DL - 0.9, NY, 0.914), (DL + 0.9, NY, 0.914), 30)
        if len(net) > 1:
            ly.line(net, KGREY, 2, 0.8)
        for xp in (-DL - 0.9, DL + 0.9):
            pts = C_.seg((xp, NY, 0), (xp, NY, 1.07), 4)
            if len(pts) > 1:
                ly.line(pts, KGREY, 2, 0.8)
        comp(cv, fade_layer(ly, CX1 - 110, CX1 + 30, 890, 975), kc, xr=CX1 + 40)
        tf = (t - self.T0) / self.slow
        lay = Lyr()
        cur = None
        if tf >= 0:
            m = self.tt <= min(tf, self.tland)
            pts = [C_.p(X) for X in self.traj[m]]
            pts = [q for q in pts if q is not None]
            if len(pts) > 1:
                lay.line(pts[-160:], KWH, 2, 0.55)
            if tf <= self.tland:
                Xb = np.array([np.interp(tf, self.tt, self.traj[:, j]) for j in range(3)])
            else:
                Xb = np.array([self.land[0], self.land[1], 0.0])
            q = C_.p(Xb)
            if q is not None:
                lay.circle(q, max(3.0, C_.scale(Xb, 0.033)), KWH, -1, 1.0)
            cur = next((f for f in reversed(self.fits) if f["t"] <= tf), None)
            if cur is not None and q is not None and tf <= self.tland:
                w = np.array(cur["w_hat"])
                wn = w / max(np.linalg.norm(w), 1e-9)
                q2 = C_.p(Xb + wn * 0.6)
                if q2 is not None:
                    lay.line([q, q2], KOR, 2, 0.9)
            if cur is not None:
                mu, cov = np.array(cur["land"]), np.array(cur["cov"])
                ev_, evec = np.linalg.eigh(cov)
                r95 = math.sqrt(5.991)
                ring = []
                for a in np.linspace(0, 2 * math.pi, 72):
                    off = evec @ (np.sqrt(np.maximum(ev_, 1e-12)) * r95 * np.array([math.cos(a), math.sin(a)]))
                    pp = C_.p((mu[0] + off[0], mu[1] + off[1], 0.0))
                    if pp is not None:
                        ring.append(pp)
                if len(ring) > 3:
                    lay.poly(ring, KOR, 0.22)
                    lay.line(ring + [ring[0]], KOR, 2, 1.0)
                bq = C_.p((cur["baseline_land"][0], cur["baseline_land"][1], 0.0))
                if bq is not None:
                    lay.circle(bq, 5, KGREY, -1, 0.9)
            if tf >= self.tland:
                kk = appear(t, self.T0 + self.tland * self.slow, 0.3)
                mk = []
                for a in np.linspace(0, 2 * math.pi, 48):
                    pp = C_.p((self.land[0] + 0.033 * math.cos(a), self.land[1] + 0.05 * math.sin(a), 0.0))
                    if pp is not None:
                        mk.append(pp)
                if len(mk) > 3:
                    lay.line(mk + [mk[0]], KWH, 2, kk)
        comp(cv, fade_layer(lay, CX1 - 110, CX1 + 30, 890, 975), 1.0, xr=CX1 + 40)
        self.inset(cv, t, cur, tf >= self.tland)
        # readouts
        x0, y0 = CX0, 150
        ka = appear(t, 0.3, 0.5)
        po = cur["p_out"] if cur else None
        rows = [("P(out)", f"{po:.3f}" if po is not None else "–", KOR if (po is not None and po >= 0.95) else KWH),
                ("spin, estimated", f"{cur['rpm_hat']:,.0f} rpm" if cur else "–", KWH),
                ("landing vs the line", (f"{abs(cur['d_hat_cm']):.1f} cm {'out' if cur['d_hat_cm'] > 0 else 'in'} "
                                        f"± {cur['sd_d_cm']:.1f}") if cur else "–", KWH)]
        for i, (a, b, col) in enumerate(rows):
            blit(cv, ktext(a, 17, 400, KGREY), x0 + i * 250, y0, "ls", ka)
            blit(cv, ktext(b, 30, 600, col, tnum=True), x0 + i * 250, y0 + 40, "ls", ka)
        if cur:
            blit(cv, ktext(f"true spin {cur['rpm_true']:,.0f} rpm · decision point {cur['lead_eval']} ms before the bounce",
                           15, 400, KGREY), x0, y0 + 72, "ls", ka)
        lg = appear(t, 1.2, 0.5)
        cv_dot(cv, x0 + 6, 960 - 20, 6, KOR, lg)
        blit(cv, ktext("our spin-aware tracker: 95% landing region, spin axis", 16, 400, (200, 200, 205)), x0 + 20, 960 - 14, "ls", lg)
        cv_dot(cv, x0 + 6, 960 + 8, 5, KGREY, lg)
        blit(cv, ktext("no-spin tracker's landing guess", 16, 400, (200, 200, 205)), x0 + 20, 960 + 14, "ls", lg)
        if t >= self.t_call:
            q = (t - self.t_call) / 0.25
            k, scl = min(1.0, q), 0.96 + 0.04 * ease3(q)
            blit(cv, ktext("OUT", 72, 600, KOR, track=-1.5), CX0, 330, "ls", k, scl)
            blit(cv, ktext(f"called {self.D['lead']} ms before the bounce", 26, 500, KWH), CX0, 372, "ls", k)
        self.rail.draw(cv, t)
        return cv


class SegPipeline(SegR):
    label = "paper: order built, never signed or sent · 1 s feed simulated (licensed feed not purchased)"

    def prepare(self):
        D = self.D
        self.rows = [("Licensed feed", "simulated: not purchased", f"{D['pp_feed']} ms", False),
                     ("WebRTC video in", "capture → decoded frame", f"{D['pp_video']} ms", True),
                     ("Computer vision → call", f"this laptop; {D['pp_cv_l4']} ms on an NVIDIA L4", f"{D['pp_cv_laptop']} ms", True),
                     ("Fair value", "Markov point leverage", f"{D['pp_fair']} ms", True),
                     ("Risk checks", "limits, kill switches", f"{D['pp_risk']} ms", True),
                     ("Order built", "unsigned", f"{D['pp_order']} ms", True),
                     ("Network to Polymarket", "one way (round trip / 2)", f"{D['pp_net']} ms", False),
                     ("Polymarket order delay", "the venue holds taker orders", f"{D['pp_venue']} ms", False),
                     ("Fill against the live book", f"paper: {D['pp_filled']} of {D['pp_traces']} filled", "paper", False)]
        self.t_rows = [0.3 + 0.42 * i for i in range(len(self.rows))]
        self.tb = self.t_rows[-1] + 0.7
        x0, x1, y = CX0, CX1, 868
        Xm = lambda ms: x0 + (x1 - x0) * ms / D["req_v"]  # noqa: E731
        ly = Lyr()
        a = 0.0
        for ms, col in ((D["feed_v"], KGREY), (D["ours_v"], KOR), (D["net_v"], (200, 200, 205)), (D["venue_v"], KGREY)):
            ly.rect(Xm(a) + (1 if a else 0), y - 7, Xm(a + ms), y + 7, col, 1.0)
            a += ms
        ly.line([(Xm(D["req_v"]) - 1, y - 22), (Xm(D["req_v"]) - 1, y + 22)], KWH, 2)
        self.bar, self.Xm, self.by = ly, Xm, y
        self.rail = Rail([dict(v=f"{D['pp_ours']} ms", lab=f"our part: frame captured → order ready (p50, {D['pp_traces']} traces)",
                               t=self.t_rows[5] + 0.3, col=KOR),
                          dict(v=f"{D['pp_total']} ms", lab="total with a 1 s feed and the 1 s venue delay (p50)", t=self.tb),
                          dict(v=f"{D['pp_margin']} ms", lab=f"inside the 3 s requirement ({D['pp_under']} calls)", t=self.tb + 0.6),
                          dict(v=f"{D['webrtc_ms']} ms", lab="WebRTC frame → call, our own stream over loopback "
                                                              "(engine fed 10 frames/s)", t=self.tb + 1.2)],
                         head="Measured, p50", vsize=46, gap=28)
        self.still_t = self.dur - 0.3

    def events(self):
        return [(t_ + 0.05, "tick") for t_ in self.t_rows] + [(self.tb, "hit")] + self.rail.events()[2:]

    def frame(self, t):
        cv = canvas()
        D = self.D
        blit(cv, ktext("From the frame to a fill", 40, 600, KWH, track=-0.6), CX0, 150, "ls", appear(t, 0.05))
        blit(cv, ktext("Orange is our code. White is the feed, the network and Polymarket's hold.", 19, 400, KGREY),
             CX0, 188, "ls", appear(t, 0.15))
        y0, dy = 214, 66
        for i, (nm, sub, ms, ours) in enumerate(self.rows):
            k = appear(t, self.t_rows[i], 0.45)
            y = y0 + i * dy
            blit(cv, ktext(nm, 22, 500, KWH), CX0 + (1 - k) * 10, y + 24, "ls", k)
            blit(cv, ktext(sub, 15, 400, KGREY), CX0 + (1 - k) * 10, y + 46, "ls", k)
            blit(cv, ktext(count_str(ms, (t - self.t_rows[i]) / 0.5), 26, 600, KOR if ours else KWH, tnum=True),
                 CX1, y + 30, "rs", k)
            if i:
                cv[y - 4:y - 3, CX0:CX1] = (cv[y - 4:y - 3, CX0:CX1].astype(np.float32) * (1 - 0.6 * k) +
                                            np.array(KHAIR_D, np.float32) * 0.6 * k).astype(np.uint8)
        kb = appear(t, self.tb, 0.6)
        if kb > 0:
            comp(cv, self.bar, kb, xr=CX0 + (CX1 - CX0 + 4) * ease3((t - self.tb) / 1.2))
            blit(cv, ktext(f"{D['pp_total']} ms", 22, 600, KWH, tnum=True), self.Xm(D["total_v"]), self.by - 22, "ms", kb)
            blit(cv, ktext("3 s requirement", 16, 500, KWH), self.Xm(D["req_v"]), self.by + 42, "rs", kb)
            blit(cv, ktext("feed 1 s", 15, 400, KGREY), CX0, self.by + 42, "ls", kb)
            blit(cv, ktext("ours", 15, 500, KOR), self.Xm(D["feed_v"]), self.by + 42, "ls", kb)
            blit(cv, ktext("venue 1 s", 15, 400, KGREY), self.Xm(D["feed_v"] + D["ours_v"] + D["net_v"]) + 6,
                 self.by + 42, "ls", kb)
        self.rail.draw(cv, t)
        return cv


class SegSpeed(SegR):
    theme, label = "light", "simulated feed delays in the backtest (paper) · decay panel: fast-tier fills, not our trades"

    def prepare(self):
        D = self.D
        self.t2 = 4.6
        x0, x1, y0, y1 = CX0 + 10, CX1 - 150, 200, 700
        self.X = lambda v: logx(v, x0, x1)  # noqa: E731
        ymin, ymax = -30.0, 210.0
        self.Y = lambda v: y1 - (y1 - y0) * (v - ymin) / (ymax - ymin)  # noqa: E731
        X, Y = self.X, self.Y
        ly = Lyr()
        ly.line([(x0, Y(0)), (x1, Y(0))], KHAIR_L, 2)
        styles = {("tournament_lagcal", "IS"): (KINK, 1.0), ("tournament_lagcal", "burned_OOS"): (KINK, 0.45),
                  ("tournament", "IS"): (KGREY, 1.0), ("tournament", "burned_OOS"): (KGREY, 0.5)}
        self.ends = []
        for (rd, per), (col, al) in styles.items():
            pts = [(X(v if v > 0 else 0.05), Y(u)) for v, u in D["curves"][rd][per] if v >= 0.05 or v == 0]
            pts = [(X(max(v, 0.05)), Y(u)) for v, u in D["curves"][rd][per] if v != 0]
            ly.line(pts, col, 3 if per == "IS" else 2, al)
            self.ends.append((rd, per, pts[0], col, al, D["curves"][rd][per][1][1]))
        ly.dotted((X(1.0), y0 + 4), (X(1.0), y1 + 10), KOR, 2, 4, 7)
        for v in (D["be_lc_v"], D["be_t_v"]):
            ly.circle((X(v), Y(0)), 6, KINK)
        by = y1 + 70
        self.bands = [("betting video", D["bands"]["vid"]), ("official feed", D["bands"]["feed"]), ("TV", D["bands"]["tv"]),
                      ("public stream", D["bands"]["stream"])]
        for i, (_, b) in enumerate(self.bands):
            ly.rect(X(b[0]), by + i * 22 - 3, X(b[1]), by + i * 22 + 3, KGREY, 0.55, r=3)
        self.chart, self.x0, self.x1, self.y0, self.y1, self.by = ly, x0, x1, y0, y1, by
        # direct labels at the line starts, placed where no other curve runs through them (QA: the pre-registered
        # in-sample line crossed the "held out" label)
        labs = {("tournament_lagcal", "IS"): "post-hoc, in sample", ("tournament_lagcal", "burned_OOS"): "post-hoc, held out",
                ("tournament", "IS"): "pre-registered, in sample", ("tournament", "burned_OOS"): "pre-registered, held out"}
        placed = []
        self.lab_xy = {}
        for rd, per, pt, col, al, v in self.ends:
            sp = ktext(labs[(rd, per)], 14, 500, KINK)
            best = None
            for dy_ in (-12, 22, -28, 38, -44, 54):
                bx0, by_ = int(pt[0] + 8), int(pt[1] + dy_)
                box = (bx0 - 3, by_ - sp.base - 2, bx0 + sp.w + 3, by_ + sp.h - sp.base + 2)
                ink = int(ly.a[max(box[1], 0):box[3], max(box[0], 0):box[2]].max(initial=0))
                hit = any(not (box[2] <= q[0] or box[0] >= q[2] or box[3] <= q[1] or box[1] >= q[3]) for q in placed)
                if ink < 40 and not hit:
                    best = (bx0, by_, box)
                    break
            if best is None:
                best = (int(pt[0] + 8), int(pt[1] - 12), None)
            self.lab_xy[(rd, per)] = best[:2]
            if best[2]:
                placed.append(best[2])
        # decay bars
        ds = D["decay"]
        n = len(ds["IS"])
        self.dbw = (CX1 - CX0) / n
        self.dy0 = 640
        dl = Lyr()
        sc_ = 260.0
        for i in range(n):
            xc = CX0 + self.dbw * (i + 0.5)
            v1, v2_ = ds["IS"][i][1], ds["OOS"][i][1]
            dl.rect(xc - self.dbw * 0.34, min(self.dy0, self.dy0 - v1 * sc_), xc - self.dbw * 0.03, max(self.dy0, self.dy0 - v1 * sc_), KINK)
            dl.rect(xc + self.dbw * 0.03, min(self.dy0, self.dy0 - v2_ * sc_), xc + self.dbw * 0.34, max(self.dy0, self.dy0 - v2_ * sc_), KGREY)
        dl.line([(CX0, self.dy0), (CX1, self.dy0)], KHAIR_L, 2)
        self.dchart = dl
        self.rail = Rail([dict(v=D["day3"], lab="$ a day at a 0 / 0.5 / 1 s feed (post-hoc estimate, in sample)", t=0.8,
                               vsize=40),
                          dict(v=D["sh3"], lab="Sharpe at 0 / 0.5 / 1 s (same reading)", t=1.5, vsize=40),
                          dict(v=f"{D['be_lc']} s", lab=f"break-even feed delay (post-hoc); pre-registered {D['be_t']} s",
                               t=2.3, vsize=40, count=False),
                          # a threshold must not count up: "1 s · every reading loses money" would be false on screen
                          dict(v=f"{D['all_lose']} s", lab="every reading loses money, in and out of sample", t=3.1, vsize=40,
                               col=KRED_L, count=False)],
                         theme="light", head="What speed is worth", gap=24)
        self.still_t = 4.2

    def events(self):
        return self.rail.events()

    def frame(self, t):
        cv = canvas("light")
        D = self.D
        k1 = appear(t, 0.05, 0.5) * (1 - ease3((t - self.t2 + 0.45) / 0.45))
        if k1 > 0:
            blit(cv, ktext("Paper profit vs how late the feed is", 40, 600, KINK, track=-0.6), CX0, 150, "ls", k1)
            comp(cv, self.chart, k1, xr=self.x0 + (self.x1 - self.x0 + 20) * ease3((t - 0.3) / 2.0))
            blit(cv, ktext("post-hoc: feed timing fitted after seeing the data · pre-registered: fixed before the test",
                           19, 400, KGREY), CX0, 186, "ls", k1)
            labs = {("tournament_lagcal", "IS"): "post-hoc, in sample", ("tournament_lagcal", "burned_OOS"): "post-hoc, held out",
                    ("tournament", "IS"): "pre-registered, in sample", ("tournament", "burned_OOS"): "pre-registered, held out"}
            for rd, per, pt, col, al, v in self.ends:
                c2 = tuple(int(255 - (255 - c_) * al) for c_ in col)
                lx, ly_ = self.lab_xy[(rd, per)]
                blit(cv, ktext(labs[(rd, per)], 14, 500, c2), lx, ly_, "ls", k1)
            blit(cv, ktext("1 s", 15, 600, KOR), self.X(1.0) + 6, self.y0 + 14, "ls", k1)
            blit(cv, ktext(f"break-even {D['be_lc']} s", 14, 500, KINK), self.X(D["be_lc_v"]) + 8, self.Y(0) - 10, "ls", k1)
            blit(cv, ktext(f"{D['be_t']} s", 14, 500, KINK), min(self.X(D["be_t_v"]), self.X(1.0)) - 10, self.Y(0) + 22,
                 "rs", k1)
            for v in (0.05, 0.1, 0.5, 1, 5, 10, 60):
                blit(cv, ktext(f"{v:g}" + (" s" if v in (1, 60) else ""), 14, 400, KGREY), self.X(v), self.y1 + 34, "ms", k1)
            for v in (0, 100, 200):
                blit(cv, ktext(f"${v}", 14, 400, KGREY), self.x0 - 10, self.Y(v) + 5, "rs", k1)
            blit(cv, ktext("feed delay, s (log) · $ per day, paper", 14, 400, KGREY), self.x0, self.y1 + 56, "ls", k1)
            for i, (nm, b) in enumerate(self.bands):
                blit(cv, ktext(nm, 13, 400, KGREY), self.X(b[1]) + 6, self.by + i * 22 + 5, "ls", k1)
        k2 = appear(t, self.t2, 0.6)
        if k2 > 0:
            blit(cv, ktext("The edge halves within a second", 40, 600, KINK, track=-0.6), CX0, 150, "ls", k2)
            blit(cv, ktext(f"fast tier's net ¢ per share by seconds after the point: {D['d0']}¢ at 0 s, {D['d1']}¢ at 1 s "
                           "(in sample)", 19, 400, KGREY), CX0, 186, "ls", k2)
            comp(cv, self.dchart, k2, xr=CX0 + (CX1 - CX0 + 4) * ease3((t - self.t2 - 0.1) / 1.2))
            for i, (lab, _) in enumerate(D["decay"]["IS"]):
                blit(cv, ktext(lab, 15, 400, KGREY), CX0 + self.dbw * (i + 0.5), self.dy0 + 200, "ms", k2)
            blit(cv, ktext("in sample", 15, 500, KINK), CX0, 300, "ls", k2)
            blit(cv, ktext("held out", 15, 500, KGREY), CX0 + 100, 300, "ls", k2)
        self.rail.draw(cv, t)
        return cv


class SegTest(SegR):
    label = ("example match from the backtest (selected for illustration) · simulated 1 s licensed-feed baseline · "
             "real Polymarket price path · paper")

    def prepare(self):
        D = self.D
        # the plate without its outer margin and its footer (the footer repeats the honesty label shown top-right)
        crop = (1728, 900, 96, 60)
        self.vw = int(CX1 - CX0) // 2 * 2
        self.vh = int(round(self.vw * crop[1] / crop[0])) // 2 * 2
        self.reader = Reader(EXAMPLE_MATCH, (self.vw, self.vh), crop=crop)
        self.t2 = 5.9
        self.t_end = 5.0           # the plate plays to its last frame (the match's final P&L) before the cut
        eq = D["eq"]
        self.has_eq = bool(eq)
        if eq:
            import datetime as _dt
            ser = {}
            for rd in ("tournament_lagcal", "tournament"):
                pts, off = [], 0.0
                for per in ("IS", "burned_OOS"):
                    rows = [r for r in eq if r["reading"] == rd and r["period"] == per]
                    for r in rows:
                        pts.append((_dt.date.fromisoformat(r["date"]), off + float(r["cum_usd_mean"]),
                                    off + float(r["cum_usd_p10"]), off + float(r["cum_usd_p90"]), per))
                    if rows:
                        off += float(rows[-1]["cum_usd_mean"])
                ser[rd] = pts
            d0, d1 = ser["tournament_lagcal"][0][0], ser["tournament_lagcal"][-1][0]
            x0, x1, y0, y1 = CX0 + 60, CX1 - 120, 230, 700
            ymax = max(p[3] for p in ser["tournament_lagcal"]) * 1.05
            ymin = min(0.0, min(p[2] for p in ser["tournament_lagcal"] + ser["tournament"]))
            X = lambda d: x0 + (x1 - x0) * (d - d0).days / max((d1 - d0).days, 1)  # noqa: E731
            Y = lambda v: y1 - (y1 - y0) * (v - ymin) / (ymax - ymin)  # noqa: E731
            ly = Lyr()
            oos0 = next(p[0] for p in ser["tournament_lagcal"] if p[4] == "burned_OOS")
            ly.rect(X(oos0), y0 - 20, x1, y1, KWH, 0.06)
            ly.line([(x0, Y(0)), (x1, Y(0))], KHAIR_D, 2)
            band = [(X(p[0]), Y(p[3])) for p in ser["tournament_lagcal"]] + [(X(p[0]), Y(p[2])) for p in ser["tournament_lagcal"]][::-1]
            ly.poly(band, KWH, 0.10)
            ly.line([(X(p[0]), Y(p[1])) for p in ser["tournament"]], KGREY, 2, 1.0)
            ly.line([(X(p[0]), Y(p[1])) for p in ser["tournament_lagcal"]], KWH, 3, 1.0)
            self.eqL, self.X, self.Y, self.ser, self.ex = ly, X, Y, ser, (x0, x1, y0, y1, oos0, d0, d1, ymin, ymax)
        pills = [f"{D['n_prereg']} pre-registrations", f"blind tests: {D['bpass']} pass · {D['bfail']} fail",
                 f"{D['peeks']} out-of-sample looks logged", f"{D['trials']} variants counted",
                 f"deflated Sharpe {D['dsr']} (v2, in sample)", f"PBO {D['pbo']}%"]
        self.pills = pills
        t_59 = self.t_say("59 percent")
        self.rail = Rail([dict(v=D["pnl"], lab=f"this match, final: {D['fills']} fills, {D['misses']} calls missed; "
                                                f"picked for its trade count", t=self.t_end - 0.4),
                          dict(v=f"{D['share']}%", lab=f"of {D['traded']} traded backtest matches were profitable "
                                                         f"({D['prof']}); median match {D['median']}",
                               t=max(self.t_end + 0.2, t_59 - 0.2)),
                          dict(v=D["mpos"], lab=f"calendar months with a profit, post-hoc reading (pre-registered "
                                                f"{D['mpos_pre']})", t=self.t2 + 0.8, count=False),
                          dict(v=f"{D['is_days']} + {D['oos_days']}", lab="days in sample + held out", t=self.t2 + 1.4,
                               count=False)],
                         head="The test, simulated 1 s feed", vsize=44, gap=26)
        self.still_t = self.dur - 0.4

    def events(self):
        return self.rail.events()

    def label_at(self, t):
        return self.label if t < self.t2 - 0.2 else f"{LABEL_RESULTS} · backtest, paper trading"

    def frame(self, t):
        cv = canvas()
        k1 = 1 - ease3((t - self.t2 + 0.4) / 0.4)
        if k1 > 0:
            ts = min(11.95, t * 11.95 / self.t_end)
            im = self.reader.get(int(round(ts * 30)))
            y0 = 178
            reg = cv[y0:y0 + im.shape[0], CX0:CX0 + im.shape[1]]
            reg[:] = (im.astype(np.float32) * k1 * appear(t, 0.0, 0.3)).astype(np.uint8)
            blit(cv, ktext("One match from the backtest: orange dots are our paper trades", 34, 600, KWH, track=-0.5),
                 CX0, 150, "ls", k1 * appear(t, 0.1))
        k2 = appear(t, self.t2, 0.6)
        if k2 > 0 and self.has_eq:
            x0, x1, y0, y1, oos0, d0, d1, ymin, ymax = self.ex
            blit(cv, ktext("Every day of the backtest, cumulative paper P&L", 34, 600, KWH, track=-0.5), CX0, 150, "ls", k2)
            comp(cv, self.eqL, k2, xr=x0 + (x1 - x0 + 30) * ease3((t - self.t2 - 0.1) / 2.2))
            kk = appear(t, self.t2 + 2.2, 0.5)
            last = self.ser["tournament_lagcal"][-1]
            blit(cv, ktext(f"post-hoc +${last[1] / 1000:.1f}k", 16, 600, KWH), x1 + 8, self.Y(last[1]) + 5, "ls", kk)
            lp = self.ser["tournament"][-1]
            blit(cv, ktext(f"pre-registered +${lp[1] / 1000:.1f}k", 16, 500, KGREY), x1 + 8, self.Y(lp[1]) + 5, "ls", kk)
            blit(cv, ktext("held out", 15, 500, KGREY), self.X(oos0) + 8, y0 - 2, "ls", k2)
            for d in (d0, oos0, d1):
                blit(cv, ktext(d.strftime("%-d %b %Y"), 14, 400, KGREY), self.X(d), y1 + 26, "ms", k2)
            blit(cv, ktext("mean of 20 seeds; band p10–p90", 14, 400, KGREY), x0, y1 + 50, "ls", k2)
            for i, s_ in enumerate(self.pills):
                kp = appear(t, self.t2 + 1.0 + 0.18 * i, 0.4)
                sp = ktext(s_, 15, 500, (215, 215, 220))
                if i % 3 == 0:
                    px = CX0
                yy = 790 + 48 * (i // 3)
                ly = Lyr(sp.w + 32, 38).rect(1, 1, sp.w + 30, 36, KHAIR_D, 1.0, r=18).rect(3, 3, sp.w + 28, 34, KBK, 1.0, r=16)
                blit(cv, Spr(ly.rgb.astype(np.float32), ly.a.astype(np.float32) / 255, 0), px, yy, "la", kp)
                blit(cv, sp, px + 16, yy + 19, "lm", kp)
                px += sp.w + 44
        self.rail.draw(cv, t)
        return cv

    def close(self):
        self.reader.close()


class SegProfit(SegR):
    label = "simulated 1 s licensed-feed baseline · paper trading · fills simulated against recorded books"

    def prepare(self):
        D = self.D
        self.t_day = self.t_say("94 dollars")         # the hero lands as Liam says it
        self.t_sh = self.t_say("Sharpe 12")
        self.t_oos = self.t_say("On data")
        # QA: the hero number counts up from the first word and lands when Liam says it; the rail (with the
        # pre-registered reading) fills in right after, so the frame never opens empty or on the rail
        self.t_hero = 0.5
        tr = self.t_sh + 0.7
        self.rail = Rail([dict(v=f"${D['t_is_day']} · ${D['t_oos_day']}", lab=f"a day, pre-registered reading (timing "
                                                                               f"fixed in advance, {D['pre_lag']} s), "
                                                                               f"in · out of sample; Sharpe "
                                                                               f"{D['t_is_sh']} · {D['t_oos_sh']}",
                               t=tr, vsize=38),
                          dict(v=f"{D['lc_is_c']} · {D['lc_oos_c']}", lab=f"net per share, in sample {D['lc_is_ci']}, out of "
                                                                         f"sample {D['lc_oos_ci']} (95% CI)", t=tr + 0.6, vsize=38),
                          dict(v=f"{D['lc_is_pnl']} · {D['lc_oos_pnl']}", lab=f"total paper P&L over {D['lc_is_days']} · "
                                                                             f"{D['lc_oos_days']} days", t=tr + 1.2, vsize=38),
                          dict(v=f"${D['cap_lc_oos']}k–${D['cap_lc_is']}k", lab=f"capital where Sharpe halves (post-hoc); "
                                                                                 f"${D['cap_pr_oos']}k–${D['cap_pr_is']}k "
                                                                                 "pre-registered", t=tr + 1.8, vsize=38),
                          dict(v=f"{D['v2_sh_is']} · {D['v2_sh_oos']}", lab="Sharpe at the fast tier's own fills (v2), "
                                                                           "in · out of sample", t=tr + 2.4, vsize=38)],
                         head="Both readings, 1 s feed", gap=22)
        self.still_t = self.dur - 0.4

    def events(self):
        return [(self.t_day + 0.1, "hit"), (self.t_sh, "tick"), (self.t_oos, "hit")] + self.rail.events()

    def frame(self, t):
        cv = canvas()
        D = self.D
        k = appear(t, self.t_hero, 0.6)
        x0 = CX0
        blit(cv, ktext("In sample · post-hoc estimate", 22, 500, KGREY), x0, 220, "ls", appear(t, 0.2))
        blit(cv, ktext(f"one timing setting (stamp lag {D['lc_lag']} s) was fitted after seeing the data", 17, 400, KGREY),
             x0, 248, "ls", appear(t, 0.3))
        v = count_str(f"${D['lc_is_day']}", (t - self.t_hero) / (self.t_day + 0.1 - self.t_hero))
        big = ktext(v, 210, 600, KWH, track=-6, tnum=True)
        blit(cv, big, x0 - 6, 470, "ls", k, 0.96 + 0.04 * k)
        blit(cv, ktext("a day", 48, 500, KWH), x0 + big.w + 10, 470, "ls", k)
        ks = appear(t, self.t_sh - 0.1, 0.6)
        blit(cv, ktext(count_str(f"Sharpe {D['lc_is_sh']}", (t - self.t_sh) / 0.8), 84, 600, KWH, track=-2, tnum=True),
             x0, 590, "ls", ks)
        blit(cv, ktext("return per unit of risk · above 2 is very good", 22, 400, KGREY), x0, 630, "ls", ks)
        ko = appear(t, self.t_oos - 0.1, 0.6)
        blit(cv, ktext(count_str(f"${D['lc_oos_day']} a day · Sharpe {D['lc_oos_sh']}", (t - self.t_oos) / 0.8), 60, 600,
                       KWH, track=-1.2, tnum=True), x0, 760, "ls", ko)
        blit(cv, ktext("out of sample: data the model never saw · same post-hoc reading", 22, 400, KGREY), x0, 798, "ls", ko)
        self.rail.draw(cv, t)
        return cv


class SegEnd(SegR):
    chrome_on, fade_out = False, 0.6

    def prepare(self):
        lic = REAL_TENNIS_LICENSE.read_text() if REAL_TENNIS_LICENSE.exists() else ""
        m = re.search(r'Tennis footage: "([^"]+)" by ([^,]+), Pexels \(Pexels License\)', lic)
        self.credit = f"Tennis footage: “{m.group(1)}” by {m.group(2)}, Pexels (Pexels License)" if m else ""
        self.still_t = 2.0
        self.logo = None
        lp = Path("docs/brand/gqh_wallie.png")
        if lp.exists():  # event mark on a small white rounded tile (the navy gator would vanish on black)
            from PIL import Image, ImageDraw
            g = Image.open(lp).convert("RGBA")
            side = 132
            g.thumbnail((side - 26, side - 26), Image.LANCZOS)
            tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            ImageDraw.Draw(tile).rounded_rectangle([0, 0, side - 1, side - 1], radius=30, fill=(255, 255, 255, 255))
            tile.alpha_composite(g, ((side - g.width) // 2, (side - g.height) // 2))
            self.logo = spr_from_rgba(np.asarray(tile))

    def frame(self, t):
        cv = canvas()
        k = appear(t, 0.05, 0.7)
        if self.logo is not None:
            blit(cv, self.logo, W / 2, 288, "mm", k)
            blit(cv, ktext("Gator Quant Hacks 2026 · Systematic Trading Track", 18, 500, KGREY), W / 2, 384, "ms", k)
        blit(cv, ktext("COURTSIDE", 120, 600, KWH, track=12), W / 2, 500, "ms", k, 0.96 + 0.04 * k)
        k2 = appear(t, 0.35, 0.6)
        blit(cv, ktext(TEAM, 22, 400, (210, 210, 215)), W / 2, 565, "ms", k2)
        blit(cv, ktext(self.D["repo"], 22, 500, KWH), W / 2, 612, "ms", k2)
        k3 = appear(t, 0.6, 0.6)
        blit(cv, ktext(END_LINE, 17, 400, KGREY), W / 2, 700, "ms", k3)
        if self.credit:
            blit(cv, ktext(self.credit, 15, 400, KGREY), W / 2, 728, "ms", k3)
        return cv


SEG_CLASSES = dict(coldopen=SegColdOpen, strategy=SegStrategy, edge=SegEdge, tt=SegTT, tennis_real=SegTennisReal,
                   tennis=SegTennis, pipeline=SegPipeline, speed=SegSpeed, test=SegTest, profit=SegProfit,
                   endcard=SegEnd)


# ----------------------------------------------------------------------------------------------------
# render (one process per segment, frames piped to ffmpeg, no frames on disk), mix, encode, manifest
# ----------------------------------------------------------------------------------------------------
def render_job(job):
    sid, p, D, cues, out, still = job
    try:
        os.nice(4)
    except OSError:
        pass
    S = SEG_CLASSES[sid](p, D)
    S.prepare()
    n = int(round(p["dur"] * FPS))
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
                            "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    cap = Captions60(cues)
    st_i = int(round((S.still_t if S.still_t is not None else p["dur"] / 2) * FPS))
    for i in range(n):
        t = i / FPS
        cv = S.frame(t)
        if S.chrome_on:
            kc = 1.0 if S.fade_in == 0 else appear(t, 0.0, 0.4)
            chrome(cv, S.num, S.title, S.label_at(t), "dark" if S.theme == "dark" else "light", kc, label2=S.label2(t),
                   footage=S.bleed)
        cap.draw(cv, p["start"] + t, "dark" if S.theme == "dark" else "light", shadow=S.bleed)
        k = 1.0
        if S.fade_in > 0:
            k = min(k, ease3(t / S.fade_in))
        if S.fade_out > 0:
            k = min(k, ease3((p["dur"] - t) / S.fade_out))
        if k < 0.999:
            cv = (cv.astype(np.float32) * k).astype(np.uint8)
        enc.stdin.write(cv.tobytes())
        if i == st_i and still:
            Image.fromarray(cv).save(still)
    enc.stdin.close()
    enc.wait()
    info = dict(S.info)
    if isinstance(S, (SegColdOpen, SegTT)):
        info["arc_frames_drawn"] = sum(v.n_arc for v in (S.views.values() if isinstance(S, SegTT) else [S.view]))
    evs = S.events()
    S.close()
    return sid, info, evs


def final(only=None, workers=5, keep=False):
    import multiprocessing as mp
    t_start = dt.datetime.now(dt.timezone.utc)
    if not TENNIS_JSON.exists():
        tennis_sim()
    check_doc()
    FW.mkdir(parents=True, exist_ok=True)
    vo, tts = voice()
    plan = plan_times(vo)
    total = round(plan[-1]["start"] + plan[-1]["dur"], 3)
    assert 75.0 <= total <= 90.0, total
    cues = [c for sg, p in zip(SEGS, plan) for c in cues_for(sg, p, vo)]
    R = v2.Reg()
    v2.build_values(R, dt.datetime.now(dt.timezone.utc))
    Dall = values60(R)
    stills = FW / "stills"
    stills.mkdir(parents=True, exist_ok=True)
    jobs = [(p["id"], p, Dall.get(p["id"], {}), cues, FW / f"seg_{p['id']}.mp4", stills / f"{p['id']}.png")
            for p in plan if not only or p["id"] in only]
    jobs.sort(key=lambda j: -j[1]["dur"] * (3 if j[0] in ("tt", "coldopen", "tennis") else 1))
    ctx = mp.get_context("spawn")
    infos = {}
    with ctx.Pool(workers) as pool:
        evmap = {}
        for sid, info, evs in pool.imap_unordered(render_job, jobs):
            infos[sid] = info
            evmap[sid] = evs
            print(f"  rendered {sid}", flush=True)
    if only:
        return
    # sound: Liam, the ElevenLabs music bed ducked under speech, one hit per call / hero number, soft ticks on reveals
    events = [(p["start"] + t, kd) for p in plan for t, kd in evmap[p["id"]] if 0 <= t <= p["dur"]]
    events.sort()
    thin = []
    for t, kd in events:                      # never two sounds closer than 0.18 s
        if thin and t - thin[-1][0] < 0.18:
            if kd == "hit" and thin[-1][1] == "tick":
                thin[-1] = (t, kd)
            continue
        thin.append((t, kd))
    placements = [(p["speech_at"], vo[p["id"]]["audio"]) for p in plan]
    spans = [(p["speech_at"], p["speech_at"] + p["speech_dur"]) for p in plan]
    v2.WORK = FW
    wav, ainfo = v2.mix_audio(total, placements, spans, thin, True)
    # concat (lossless intermediates) -> one H.264 + AAC encode, faststart, capped bitrate (< 40 MB)
    lst = FW / "concat.txt"
    lst.write_text("".join(f"file '{(FW / ('seg_' + p['id'] + '.mp4')).resolve()}'\n" for p in plan))
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    tmp = FINAL.with_suffix(".tmp.mp4")
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(wav),
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-maxrate", "3200k",
         "-bufsize", "6400k", "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart", str(tmp)])
    tmp.replace(FINAL)
    write_srt(cues, FINAL_SRT)
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                       "format=duration,size,bit_rate:stream=codec_name,width,height,r_frame_rate",
                                       "-of", "json", str(FINAL)], capture_output=True, text=True).stdout)
    size_mb = FINAL.stat().st_size / 1e6
    print(f"final: {FINAL} {float(probe['format']['duration']):.2f} s, {size_mb:.1f} MB")
    # manifest
    extra = dict(final=dict(
        file=str(FINAL), srt=str(FINAL_SRT), sha256=sha(FINAL), duration_s=float(probe["format"]["duration"]),
        size_mb=round(size_mb, 2), streams=probe["streams"], rendered_utc=t_start.isoformat(timespec="seconds"),
        spec="research/compliance/VIDEO_REQUIREMENTS.md: the 75-90 s table, DESIGN, stats rail, red-team addendum",
        script_doc=str(DOC), timeline=[dict(id=p["id"], start_s=round(p["start"], 3), dur_s=round(p["dur"], 3),
                                             speech_at_s=round(p["speech_at"], 3), speech_s=round(p["speech_dur"], 3),
                                             narration=next(s_["say"] for s_ in SEGS if s_["id"] == p["id"]))
                                        for p in plan],
        words=sum(words(s_["say"]) for s_ in SEGS), voice=dict(
            engine="ElevenLabs text-to-speech via scripts/tts_elevenlabs.synth (cached in data/tts_cache)",
            voice="Liam", model="eleven_multilingual_v2", tempo=VOICE_TEMPO, max_pause_s=VOICE_MAX_PAUSE,
            tts_calls=tts), audio=ainfo, sound_events=[(round(t, 3), kd) for t, kd in thin],
        captions=dict(n=len(cues), srt=str(FINAL_SRT)), renders=infos,
        tennis_sim=dict(file=str(TENNIS_JSON), rule=TENNIS_RULE),
        real_tennis=dict(file=str(REAL_TENNIS), present=REAL_TENNIS.exists(),
                         sha256=sha(REAL_TENNIS) if REAL_TENNIS.exists() else None,
                         license=str(REAL_TENNIS_LICENSE)),
        example_match=dict(file=str(EXAMPLE_MATCH), sha256=sha(EXAMPLE_MATCH), match_json=str(EXAMPLE_MATCH_JSON)),
        not_used=["results/replay (team decision: the 1:04 segment uses the backtest showcase match)",
                  "the earlier v2-style plates seg_*.mp4 (superseded by the keynote-design renderers in this script)"],
        labels=dict(footage=LABEL_FOOT, results=LABEL_RESULTS, tennis=LABEL_SIM, end_card=END_LINE),
        decisions=["cold open shows 325 ms: the streaming engine's own MISS call on test_2 flight 2819, measured to the "
                   "labelled outcome (the ball passing the end line). The spec's 'Called 408 ms before contact' is the "
                   "offline evaluation's lead for the same flight and is not shown.",
                   "tennis call: the evaluation grid's decision points (400 ... 0 ms); the first with P(out) >= 0.95 is "
                   "200 ms, so the stamp sits there. A per-frame re-run would already exceed 0.95 from about 252 ms; the "
                   "display uses the evaluation's own decision points only.",
                   "hero numbers use the post-hoc reading with its label on screen; the pre-registered reading stays on "
                   "the stats rail of the same frame."]))
    prev_assets = jload(MANIFEST).get("assets", {}) if MANIFEST.exists() else {}
    write_manifest(R, prev_assets, extra)
    if not keep:
        for p in plan:
            (FW / f"seg_{p['id']}.mp4").unlink(missing_ok=True)
        for f in ("mix_raw.wav", "_lufs.wav"):
            (FW / f).unlink(missing_ok=True)
    return FINAL


def stills(only=None):
    """QA: a few frames per segment as PNG (data/v60/final/qa), rendered in order, no video."""
    vo, _ = voice()
    plan = plan_times(vo)
    cues = [c for sg, p in zip(SEGS, plan) for c in cues_for(sg, p, vo)]
    R = v2.Reg()
    v2.build_values(R, dt.datetime.now(dt.timezone.utc))
    Dall = values60(R)
    out = FW / "qa"
    out.mkdir(parents=True, exist_ok=True)
    cap = Captions60(cues)
    for p in plan:
        if only and p["id"] not in only:
            continue
        S = SEG_CLASSES[p["id"]](p, Dall.get(p["id"], {}))
        S.prepare()
        ts = sorted({0.6, round(S.still_t or p["dur"] / 2, 2), round(p["dur"] * 0.5, 2), round(p["dur"] - 0.35, 2)})
        for t in ts:
            cv = S.frame(t)
            if S.chrome_on:
                chrome(cv, S.num, S.title, S.label_at(t), S.theme, 1.0, label2=S.label2(t), footage=S.bleed)
            cap.draw(cv, p["start"] + t, S.theme, shadow=S.bleed)
            Image.fromarray(cv).save(out / f"{p['id']}_{t:05.2f}.png")
        print(p["id"], ts, S.events()[:6])
        S.close()


def check_doc():
    """docs/video_script_60.md must carry every narration line verbatim (the script is the single source)."""
    if not DOC.exists():
        raise SystemExit(f"{DOC} missing")
    txt = re.sub(r"\s+", " ", DOC.read_text())
    missing = [s_["id"] for s_ in SEGS if s_["say"] not in txt]
    if missing:
        raise SystemExit(f"{DOC} is out of date for: {', '.join(missing)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["select", "cut", "overlays", "equity", "segments", "manifest", "all", "tennis", "voice",
                                     "final", "stills"])
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--keep", action="store_true", help="keep the per-segment renders in data/v60/final")
    ap.add_argument("--only", default=None, help="comma-separated clip ids / segment names")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    if a.what == "select":
        select()
    elif a.what == "cut":
        cut()
    elif a.what == "overlays":
        overlays(only)
    elif a.what == "equity":
        equity_1s()
    elif a.what == "tennis":
        tennis_sim()
    elif a.what == "voice":
        vo, st = voice()
        for p in plan_times(vo):
            print(f"  {p['id']:<12} {p['start']:6.2f} + {p['dur']:5.2f} s  speech {p['speech_dur']:.2f} s")
        print(st)
    elif a.what == "final":
        final(only, a.workers, a.keep)
    elif a.what == "stills":
        stills(only)
    elif a.what in ("segments", "manifest", "all"):
        if a.what == "all":
            if not SELECTION.exists():
                select()
            if not all((SRC / f"{x['id']}.mp4").exists() for x in jload(SELECTION)["chosen"]):
                cut()
            overlays()
            equity_1s()
        R, L, assets, extra = segments(None if a.what == "manifest" else only, dry=a.what == "manifest")
        prev = jload(MANIFEST).get("assets", {}) if MANIFEST.exists() else {}
        clips = {}
        for x in jload(SELECTION)["chosen"]:
            js = CLIPS / f"{x['id']}.json"
            if js.exists():
                d = jload(js)
                clips[x["id"]] = {k: d[k] for k in ("file", "file_cell", "duration_s", "call_out_t", "contact_out_t",
                                                    "label", "outcome_tick", "other_calls_in_window") if k in d}
        merged = {**prev, **assets}
        e2e = Path("results/e2e/summary.json")
        extra.update(
            selection=str(SELECTION), clips=clips,
            clips_total_mb=round(sum(p.stat().st_size for p in CLIPS.glob("*.mp4")) / 1e6, 1),
            engine_log=dict(pickle=str(RAW), hpg_source=HPG_RAW, sha256=sha(RAW) if RAW.exists() else None,
                            events_identical_to=str(EVENTS),
                            fit_reproduction_all_decision_frames_in_clip_windows=verify_fits(L)),
            equity=dict(csv=str(EQUITY), check=str(EQUITY_CHECK)),
            e2e=dict(file=str(e2e), state="present" if e2e.exists() else "pending",
                     run_id=(jload(e2e).get("run_id") if e2e.exists() else None),
                     mtime_utc=(dt.datetime.fromtimestamp(e2e.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")
                                if e2e.exists() else None)),
            replay=dict(file="results/replay/replay.json",
                        mtime_utc=dt.datetime.fromtimestamp(Path("results/replay/replay.json").stat().st_mtime,
                                                            dt.timezone.utc).isoformat(timespec="seconds")),
            flags=["cold open: the spec's 'Called 408 ms before contact' is the offline evaluation's first-call lead for "
                   "test_2 flight 2819 (results/tracking/demo/manifest.json); the streaming engine called the same flight "
                   "325 ms before its labelled outcome (the ball passing the end line). The assets show 325 ms.",
                   "for MISS flights the labelled outcome T_ref is the ball passing the end line (or the net); the stamps "
                   "read 'n ms early' and the timeline names the outcome instead of 'contact'.",
                   "capacity: results/capacity/ absent at render time -> 'capacity study pending' on screen, value pending "
                   "here" if not Path("results/capacity/capacity.json").exists() else
                   "capacity: results/capacity/capacity.json growth[...][1.0].capital_where_sharpe_halves_usd (10 covered "
                   "matches a day), both readings"])
        write_manifest(R, merged, extra)


if __name__ == "__main__":
    main()
