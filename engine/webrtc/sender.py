"""WHIP sender: our held-out OpenTTGames clip -> raw frames paced in real time -> ffmpeg (H.264, low latency)
-> WHIP -> MediaMTX. Every frame carries its identity in a code strip under the picture (framecode.py), and
the sender logs, per frame, when it was due and when ffmpeg took it.

Source: data/vision/test_2_copyts.mp4 (OpenTTGames test_2 frames 2000-2999, 1920x1080, 120 fps;
CC BY-NC-SA 4.0), decoded here with PyAV. No camera, no microphone, no third-party stream.

Pacing (the "-re" of this pipeline): a virtual camera. Sent frame n is due at t0 + n / fps (wall clock);
the sender sleeps until then and writes the frame into ffmpeg's stdin (rawvideo yuv420p). t_due is the
"capture" time every latency is measured from; if the sender is late, the lateness counts as latency.
  --step 1 --fps 120   native: every source frame, real time
  --step 2 --fps 60    decimated to 60 fps (every 2nd frame), real time
  --step 4 --fps 30    decimated to 30 fps, real time
  --step 1 --fps 30    slow motion: every source frame at 30 frames/s of wall time (the 120 fps content
                       plays 4x slower; the CV engine still sees every frame at its 120 fps time base)

Stream: lead-in (the first clip frame, flagged LEADIN) until the receiver has written --ready-file (it is
connected, decoding and warmed up) plus --leadin-after-ready-s, then the clip (CLIP), then a short END
trailer. Encoder: libx264 ultrafast + zerolatency, constrained baseline, no B-frames, closed GOP of
--gop-s seconds, CBR-ish VBV; or h264_videotoolbox (hardware) with realtime + prio_speed.

Usage (repo root; MediaMTX running with engine/webrtc/mediamtx.yml):
  python -m engine.webrtc.sender --step 1 --fps 120 --log /tmp/send.jsonl --ready-file /tmp/ready
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from . import framecode as FC

REPO = Path(__file__).resolve().parents[2]
CLIP = REPO / "data" / "vision" / "test_2_copyts.mp4"
SRC_FPS = 120.0
SPIN_S = 0.003


def ffmpeg_version(ff="ffmpeg"):
    try:
        return subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
    except Exception as e:     # noqa: BLE001
        return f"unknown ({e})"


def encoder_args(enc, fps, bitrate, gop):
    if enc == "x264":
        return ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-profile:v", "baseline",
                "-level:v", "5.2", "-bf", "0", "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
                "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", _half(bitrate)]
    if enc == "vt":
        return ["-c:v", "h264_videotoolbox", "-realtime", "1", "-prio_speed", "1", "-allow_sw", "0",
                "-profile:v", "constrained_baseline", "-level", "5.2", "-bf", "0", "-g", str(gop),
                "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", _half(bitrate)]
    raise SystemExit(f"unknown encoder {enc}")


def _half(rate):
    s = rate.strip().upper()
    mult = {"K": 1e3, "M": 1e6}.get(s[-1], 1.0)
    v = float(s[:-1]) if s[-1] in "KM" else float(s)
    return str(int(v * mult / 2))


class ClipReader(threading.Thread):
    """Decodes the clip (frame threading: the sender's own decode latency is hidden by the prefetch) and
    builds full output buffers (picture + strip, yuv420p) ahead of time."""

    def __init__(self, path, step, max_frames, size, prefetch=90):
        super().__init__(daemon=True)
        self.path, self.step, self.max_frames, self.size = path, step, max_frames, size
        self.q = queue.Queue(maxsize=prefetch)
        self.info = {}

    def run(self):
        import av
        try:
            c = av.open(str(self.path))
            st = c.streams.video[0]
            st.thread_type = "AUTO"
            tb = float(st.time_base)
            n = 0
            for fr in c.decode(st):
                src = int(round(fr.pts * tb * SRC_FPS))
                if self.max_frames is not None and n >= self.max_frames:
                    break
                n += 1
                if (n - 1) % self.step:
                    continue
                if self.size and (fr.width, fr.height) != self.size:
                    fr = fr.reformat(width=self.size[0], height=self.size[1], format="yuv420p", interpolation="AREA")
                self.info.setdefault("size", (fr.width, fr.height))
                self.q.put((src, build_buffer(fr)))
            self.info["decoded"] = n
            c.close()
        except Exception as e:      # noqa: BLE001
            self.info["error"] = repr(e)
        finally:
            self.q.put(None)


def build_buffer(fr):
    """yuv420p av.VideoFrame -> one contiguous yuv420p buffer of W x (H + STRIP_H), strip neutral."""
    a = fr.to_ndarray(format="yuv420p")             # (H*3/2, W): Y then U, V (each H/4 rows of W)
    w, h = fr.width, fr.height
    ho = h + FC.STRIP_H
    y_in = a[:h]
    u_in = a[h:h + h // 4].reshape(h // 2, w // 2)
    v_in = a[h + h // 4:].reshape(h // 2, w // 2)
    buf = np.empty(w * ho * 3 // 2, np.uint8)
    y = buf[:w * ho].reshape(ho, w)
    u = buf[w * ho:w * ho * 5 // 4].reshape(ho // 2, w // 2)
    v = buf[w * ho * 5 // 4:].reshape(ho // 2, w // 2)
    y[:h] = y_in
    y[h:] = FC.NEUTRAL
    u[:h // 2] = u_in
    u[h // 2:] = FC.NEUTRAL
    v[:h // 2] = v_in
    v[h // 2:] = FC.NEUTRAL
    return buf


def strip_view(buf, w, h):
    ho = h + FC.STRIP_H
    return buf[:w * ho].reshape(ho, w)[h:]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", default=str(CLIP))
    ap.add_argument("--step", type=int, default=1, help="send every step-th source frame")
    ap.add_argument("--fps", type=float, default=None, help="wall-clock send rate (default 120 / step)")
    ap.add_argument("--max-frames", type=int, default=None, help="source frames of the clip to use (before --step)")
    ap.add_argument("--size", default=None, help="WxH of the picture (default: native 1920x1080)")
    ap.add_argument("--encoder", default="x264", choices=["x264", "vt"])
    ap.add_argument("--bitrate", default="12M")
    ap.add_argument("--gop-s", type=float, default=0.5, help="keyframe interval (s)")
    ap.add_argument("--whip-url", default="http://127.0.0.1:8889/courtside/whip")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffmpeg-log", default=None)
    ap.add_argument("--log", required=True, help="per-frame send log (JSONL)")
    ap.add_argument("--ready-file", default=None, help="wait for this file (receiver ready) before the clip")
    ap.add_argument("--leadin-max-s", type=float, default=60.0)
    ap.add_argument("--leadin-after-ready-s", type=float, default=1.0)
    ap.add_argument("--trailer-s", type=float, default=0.5)
    a = ap.parse_args()

    fps = a.fps or SRC_FPS / a.step
    size = tuple(map(int, a.size.lower().split("x"))) if a.size else None
    rd = ClipReader(a.clip, a.step, a.max_frames, size)
    rd.start()
    first = rd.q.get()
    if first is None:
        raise SystemExit(f"clip reader failed: {rd.info}")
    src0, buf0 = first
    w, h = rd.info["size"]
    gop = max(1, int(round(a.gop_s * fps)))
    cmd = [a.ffmpeg, "-hide_banner", "-loglevel", "info", "-nostats",
           "-f", "rawvideo", "-pix_fmt", "yuv420p", "-video_size", f"{w}x{h + FC.STRIP_H}", "-framerate", f"{fps:g}",
           "-i", "pipe:0", *encoder_args(a.encoder, fps, a.bitrate, gop), "-an", "-f", "whip", a.whip_url]
    logf = open(a.ffmpeg_log, "w") if a.ffmpeg_log else subprocess.DEVNULL
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=logf, stderr=logf, bufsize=0)
    out = open(a.log, "w")
    meta = dict(type="meta", role="sender", clip=str(a.clip), clip_license="OpenTTGames, CC BY-NC-SA 4.0",
                step=a.step, fps=fps, size=[w, h], strip_h=FC.STRIP_H, encoder=a.encoder, bitrate=a.bitrate,
                gop_frames=gop, whip_url=a.whip_url, ffmpeg_cmd=" ".join(shlex.quote(c) for c in cmd),
                ffmpeg_version=ffmpeg_version(a.ffmpeg), python=sys.version.split()[0],
                host=platform.node(), machine=platform.machine(), load_avg=[round(x, 2) for x in os.getloadavg()])
    out.write(json.dumps(meta) + "\n")
    print(f"sender: {a.encoder} {w}x{h}+strip @ {fps:g} fps, step {a.step}, gop {gop} -> {a.whip_url}", flush=True)

    t0 = time.time() + 0.3
    seq = 0
    late = []
    stats = dict(leadin=0, clip=0, trailer=0)

    def send(buf, flags, src):
        nonlocal seq
        due = t0 + seq / fps
        dt = due - time.time()
        if dt > SPIN_S:            # macOS timer coalescing oversleeps by a few ms: sleep short, spin the rest
            time.sleep(dt - SPIN_S)
        while time.time() < due:
            pass
        FC.draw(strip_view(buf, w, h), seq, flags, src, int(round(due * 1000)))
        tw0 = time.time()
        proc.stdin.write(memoryview(buf))
        tw1 = time.time()
        out.write(json.dumps(dict(seq=seq, src=(None if src == FC.NO_SRC else src), flags=flags,
                                  t_due=round(due, 6), t_w0=round(tw0, 6), t_w1=round(tw1, 6))) + "\n")
        late.append((tw0 - due) * 1e3)
        seq += 1

    try:
        # lead-in: until the receiver is ready (plus a margin), first clip frame repeated
        t_ready = None
        lead = buf0.copy()
        t_start = time.time()
        while True:
            if t_ready is None and a.ready_file and os.path.exists(a.ready_file):
                t_ready = time.time()
            if a.ready_file is None and time.time() - t_start >= a.leadin_after_ready_s:
                break
            if t_ready is not None and time.time() - t_ready >= a.leadin_after_ready_s:
                break
            if time.time() - t_start > a.leadin_max_s:
                raise SystemExit("receiver never became ready (no --ready-file)")
            send(lead, FC.LEADIN, FC.NO_SRC)
            stats["leadin"] += 1
        # clip
        item = first
        while item is not None:
            src, buf = item
            send(buf, FC.CLIP, src)
            stats["clip"] += 1
            item = rd.q.get()
        # trailer
        last = buf.copy()
        for _ in range(max(1, int(a.trailer_s * fps))):
            send(last, FC.END, FC.NO_SRC)
            stats["trailer"] += 1
    except BrokenPipeError:
        stats["error"] = "ffmpeg closed its input (see --ffmpeg-log)"
    finally:
        try:
            proc.stdin.close()
        except Exception:       # noqa: BLE001
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
        lt = np.asarray(late)
        stats.update(type="end", ffmpeg_rc=proc.returncode, reader=rd.info, src_first=src0,
                     sender_late_ms=dict(p50=round(float(np.percentile(lt, 50)), 3),
                                         p99=round(float(np.percentile(lt, 99)), 3),
                                         max=round(float(lt.max()), 3)) if len(lt) else None)
        out.write(json.dumps(stats) + "\n")
        out.close()
        print(f"sender done: {stats}", flush=True)


if __name__ == "__main__":
    main()
