"""Render results/webrtc/webrtc_demo.mp4 from the LOGS of one WebRTC engine run (nothing re-computed or invented).

Paper only. Our own held-out OpenTTGames clip (test_2, CC BY-NC-SA 4.0) streamed by us over loopback WebRTC; not a
match feed. Inputs, all written by the run itself (scripts/webrtc_demo.sh with SAVE_FRAMES=1):
  * the 512x288 RGB frames exactly as the receiver handed them to the CV engine (--save-frames, raw uint8);
  * the per-frame rows (capture t_due, decoded t_handoff, decision t_decision), the engine's track rows (ball
    position per source frame, full-resolution pixels) and the CallEvent rows (capture -> emit).
Per displayed frame f the overlay shows only what the engine knew at f's decision: track points up to f - 2 (the
detector's look-ahead), the latencies logged for f, and calls emitted at frames <= f.

Usage: python scripts/webrtc_render_demo.py results/webrtc/run_<ts>.jsonl --run slowmo10_engine_r1
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
W, H = 1280, 720
VX, VY, VW, VH = 16, 70, 896, 504          # video area (512x288 upscaled 1.75x)
PX = VX + VW + 20                           # right panel x
CY, CH = VY + VH + 14, H - (VY + VH + 14) - 12   # rolling chart
BG, INK, MUTED, FAINT = (17, 17, 16), (245, 245, 242), (176, 175, 168), (70, 70, 66)
BLUE, ORANGE, AQUA, RED = (57, 135, 229), (235, 104, 52), (27, 175, 122), (230, 103, 103)


def font(size, mono=False, bold=False):
    cands = (["/System/Library/Fonts/Menlo.ttc"] if mono else
             ["/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc"])
    for c in cands:
        try:
            return ImageFont.truetype(c, size, index=(1 if bold and not mono else 0))
        except OSError:
            continue
    return ImageFont.load_default()


def load(run_file, run):
    frames, calls, track, saved, meta, summ = [], [], {}, None, None, None
    for line in open(run_file):
        r = json.loads(line)
        if r.get("run") != run:
            continue
        t = r.get("type")
        if t == "frame" and r.get("flags") is not None and r["flags"] & 2 and r.get("saved") is not None:
            frames.append(r)
        elif t == "call":
            calls.append(r)
        elif t == "track":
            track[r["f"]] = r["xy"]
        elif t == "saved_frames":
            saved = r
        elif t == "meta":
            meta = r
        elif t == "summary":
            summ = r
    frames.sort(key=lambda r: r["saved"])
    return frames, calls, track, saved, meta, summ


def ms(r, a, b):
    return None if r.get(a) is None or r.get(b) is None else (r[a] - r[b]) * 1e3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_file")
    ap.add_argument("--run", default="slowmo10_engine_r1")
    ap.add_argument("--frames", default=None, help="raw frame file (default: the path logged by the run)")
    ap.add_argument("--fps", type=float, default=40.0, help="playback rate (40 = 1/3 of the clip's 120 fps)")
    ap.add_argument("--out", default=str(REPO / "results" / "webrtc" / "webrtc_demo.mp4"))
    ap.add_argument("--still", type=int, nargs="*", default=None, help="write these frame numbers as PNGs next to --out "
                                                                       "instead of the video (layout check)")
    a = ap.parse_args()
    frames, calls, track, saved, meta, summ = load(a.run_file, a.run)
    path = a.frames or saved["path"]
    h, w, c = saved["shape"]
    raw = np.memmap(path, np.uint8, "r", shape=(saved["n"], h, w, c))
    calls_by_frame = {int(e["frame"]): e for e in calls}
    send_fps = meta["arrival_fps"]
    load_avg = meta["load_avg_start"][0]
    sx = VW / 1920.0

    F = dict(t=font(22, bold=True), s=font(14), m=font(15, mono=True), big=font(30, mono=True), lab=font(13),
             call=font(26, bold=True), tiny=font(12))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", f"{a.fps:g}", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-threads", "2", "-movflags", "+faststart",
           "-metadata", "title=COURTSIDE WebRTC -> CV -> call, our own stream (not a match feed)",
           "-metadata", "comment=OpenTTGames test_2 (CC BY-NC-SA 4.0); rendered from logged data by scripts/webrtc_render_demo.py",
           a.out]
    ff = None if a.still is not None else subprocess.Popen(cmd, stdin=subprocess.PIPE)
    hist_c2d, hist_vid = [], []
    shown_calls = []
    banner = None
    c2d_all = []
    for n, r in enumerate(frames):
        f = int(r["src"])
        vid = ms(r, "t_handoff", "t_due")
        eng = ms(r, "t_decision", "t_handoff")
        c2d = ms(r, "t_decision", "t_due")
        if c2d is not None:
            c2d_all.append(c2d)
        hist_c2d.append(c2d)
        hist_vid.append(vid)
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        # header
        d.text((VX, 12), "Our virtual camera -> WebRTC -> CV -> call: per-frame latency, measured", font=F["t"], fill=INK)
        d.text((VX, 42), f"Our own clip (OpenTTGames test_2, CC BY-NC-SA 4.0), loopback WebRTC on one laptop, fed at "
                         f"{send_fps:g} frames/s ({120 / send_fps:g}x slow motion) so the CV keeps up. Not a match feed.",
               font=F["s"], fill=MUTED)
        # video: the frame the engine received, upscaled for display
        fr = Image.fromarray(np.asarray(raw[r["saved"]])).resize((VW, VH), Image.BICUBIC)
        img.paste(fr, (VX, VY))
        # ball track known at this decision: positions up to f - 2
        pts = [(g, track.get(g)) for g in range(f - 2 - 36, f - 1)]
        pts = [(g, xy) for g, xy in pts if xy and xy[0] is not None]
        for j, (g, xy) in enumerate(pts):
            x, y = VX + xy[0] * sx, VY + xy[1] * sx
            age = (f - 2) - g
            rad = 3 if age else 7
            alpha = max(0.25, 1 - age / 36)
            col = tuple(int(c0 * alpha + 0 * (1 - alpha)) for c0 in (255, 214, 10))
            if age == 0:
                d.ellipse([x - rad, y - rad, x + rad, y + rad], outline=(255, 214, 10), width=3)
            else:
                d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=col)
        d.rectangle([VX, VY, VX + VW, VY + VH], outline=FAINT, width=1)
        d.text((VX + 10, VY + VH - 26), f"frames as the CV engine received them (512x288, shown 1.75x)  |  ball track "
                                        f"up to frame {f - 2}", font=F["tiny"], fill=INK)
        # call banner
        if f in calls_by_frame:
            e = calls_by_frame[f]
            banner = (e, 60)
            shown_calls.append(e)
        if banner:
            e, left = banner
            col = RED if e["call"] == "MISS" else AQUA
            txt = f"{e['call']} call at frame {int(e['frame'])}   capture -> emit {e['capture_to_emit_ms']:.1f} ms"
            tw = d.textlength(txt, font=F["call"])
            d.rounded_rectangle([VX + 14, VY + 14, VX + 34 + tw, VY + 58], radius=8, fill=(17, 17, 16), outline=col, width=3)
            d.text((VX + 24, VY + 20), txt, font=F["call"], fill=INK)
            banner = (e, left - 1) if left > 1 else None
        # right panel: readouts for this frame
        y = VY
        d.text((PX, y), f"source frame {f}   clip t = {(f - 2000) / 120:5.2f} s", font=F["m"], fill=MUTED)
        y += 30

        def row(label, val, col, y):
            d.text((PX, y), label, font=F["lab"], fill=MUTED)
            d.text((PX, y + 16), "  n/a" if val is None else f"{val:6.1f} ms", font=F["big"], fill=col)
            return y + 58
        y = row("capture -> decoded frame (WebRTC leg)", vid, BLUE, y)
        y = row("decoded -> decision ready (CV engine)", eng, ORANGE, y)
        y = row("capture -> decision ready (total)", c2d, INK, y)
        med = float(np.median(c2d_all)) if c2d_all else None
        d.text((PX, y), f"running median so far: {med:5.1f} ms" if med else "", font=F["m"], fill=MUTED)
        y += 26
        d.text((PX, y), "+ ~17 ms camera capture at 120 fps", font=F["tiny"], fill=MUTED)
        d.text((PX, y + 15), "  (assumed, 2 frame periods; no camera in loop)", font=F["tiny"], fill=MUTED)
        y += 40
        d.text((PX, y), "calls emitted (capture -> emit)", font=F["lab"], fill=MUTED)
        y += 18
        for e in shown_calls[-6:]:
            col = RED if e["call"] == "MISS" else AQUA
            d.text((PX, y), f"{e['call']:6s} f{int(e['frame'])}  {e['capture_to_emit_ms']:5.1f} ms", font=F["m"], fill=col)
            y += 19
        # rolling chart: last 240 frames
        x0, x1, y0, y1 = VX, W - 16, CY, CY + CH
        ymax = 80.0
        d.rectangle([x0, y0, x1, y1], outline=FAINT)
        for gv in (20, 40, 60):
            gy = y1 - (gv / ymax) * CH
            d.line([x0, gy, x1, gy], fill=(40, 40, 37))
            d.text((x0 + 4, gy - 14), f"{gv} ms", font=F["tiny"], fill=FAINT)
        span = 240
        lo = max(0, len(hist_c2d) - span)
        for series, col in ((hist_vid, BLUE), (hist_c2d, ORANGE)):
            ptsl = []
            for i in range(lo, len(series)):
                v = series[i]
                if v is None:
                    if len(ptsl) > 1:
                        d.line(ptsl, fill=col, width=2)
                    ptsl = []
                    continue
                xx = x1 - (len(series) - 1 - i) / span * (x1 - x0)
                yy = y1 - min(v, ymax) / ymax * CH
                ptsl.append((xx, yy))
            if len(ptsl) > 1:
                d.line(ptsl, fill=col, width=2)
        lx = x1 - 470
        d.text((lx, y0 + 5), "last 240 frames (2 s of clip):", font=F["tiny"], fill=MUTED)
        lx += 178
        for name, col in (("capture -> decision", ORANGE), ("capture -> decoded", BLUE)):
            d.line([lx, y0 + 12, lx + 18, y0 + 12], fill=col, width=3)
            d.text((lx + 23, y0 + 5), name, font=F["tiny"], fill=MUTED)
            lx += 23 + d.textlength(name, font=F["tiny"]) + 14
        d.text((PX, VY + VH - 46), f"sender: {send_fps:g} frames/s of wall time, so the", font=F["tiny"], fill=MUTED)
        d.text((PX, VY + VH - 31), f"engine keeps up; playback {a.fps:g} fps = {a.fps / 120:.2f}x speed", font=F["tiny"], fill=MUTED)
        d.text((PX, VY + VH - 16), f"run {a.run}, load avg {load_avg:.1f}", font=F["tiny"], fill=MUTED)
        if ff is None:
            if f in a.still:
                img.save(str(Path(a.out).with_suffix("")) + f"_still_{f}.png")
            continue
        ff.stdin.write(np.asarray(img).tobytes())
    if ff is None:
        return
    ff.stdin.close()
    ff.wait()
    print(f"wrote {a.out}: {len(frames)} frames at {a.fps:g} fps = {len(frames) / a.fps:.1f} s; "
          f"{len(calls)} calls; median capture->decision {np.median(c2d_all):.1f} ms")


if __name__ == "__main__":
    main()
