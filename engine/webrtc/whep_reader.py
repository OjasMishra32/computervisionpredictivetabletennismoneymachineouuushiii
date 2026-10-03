"""WHEP receiver: MediaMTX (WebRTC) -> aiortc -> engine.vision.stream (unchanged), with per-frame timing.

Paper only, our own stream only: the source is the sender in engine/webrtc/sender.py playing our held-out
OpenTTGames clip into a MediaMTX on 127.0.0.1. Nothing here touches a camera, a microphone or a third-party
stream, and nothing trades (engine.vision.events.assert_paper_only is enforced).

Per frame:
  1. aiortc receives the RTP packets (WHEP, H.264), assembles the frame (marker bit; aiortc_patch.py) and
     decodes it; aiortc_patch stamps first / last packet arrival and decode start / end.
  2. track.recv() hands the decoded frame to us (t_handoff). A prep thread reads the frame code under the
     picture (framecode.py: send sequence number, source frame number, capture time), crops the code strip
     off and resizes the 1920x1080 picture to 512x288 RGB with swscale 'area' (as FrameSource's PyAV reader).
  3. The frame goes into a queue with the same item layout as engine.vision.stream.FrameSource:
     (i, rgb, t_frame, decode_ms, resize_ms) with t_frame = t_handoff, so the unchanged online loop
     engine.vision.stream.run_stream() consumes it exactly as it consumes a live RTSP feed. A WebRTC loss
     shows up as a gap in i (the detector ends its window range there, as at any gap).
  4. CallEvents (call mode) or decision-ready times (track-only mode) are joined, after the run, with the
     sender's per-frame log: capture (t_due) -> send -> RTP in -> decoded -> engine done -> emit.

Engine indexing: i = (source frame - src0) / step. With step 1 (every source frame, native 120 fps or slow
motion) the engine sees the source numbering (frame_offset = src0) at the frozen model's 120 fps time base:
calls are the validated ones. With step 2 / 4 (60 / 30 fps) the engine sees consecutive indices of a
decimated stream: the detector's 3-frame windows, the tracker gates and the call model were all built for
120 fps, so by default only detection + tracking run (track-only) and calls are off (--calls on forces
them; such calls are out of distribution and are flagged so).

Usage (repo root; MediaMTX + sender running):
  python -m engine.webrtc.whep_reader --step 1 --out results/webrtc/run_x.jsonl --sender-log /tmp/send.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import platform
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from engine.vision import stream as VS
from engine.vision.events import assert_paper_only

from . import aiortc_patch
from . import framecode as FC
from . import report

REPO = Path(__file__).resolve().parents[2]
DEFAULT_URL = "http://127.0.0.1:8889/courtside/whep"


def crop_resize(frame, y, h, w, D):
    """Decoded yuv420p frame (picture + code strip) -> uint8 RGB [288, 512, 3] of the picture only,
    swscale 'area' (FrameSource's PyAV reader does the same on the original file's frames)."""
    import av
    u = np.frombuffer(frame.planes[1], np.uint8).reshape(-1, frame.planes[1].line_size)
    v = np.frombuffer(frame.planes[2], np.uint8).reshape(-1, frame.planes[2].line_size)
    arr = np.empty((h * 3 // 2, w), np.uint8)
    flat = arr.reshape(-1)
    flat[:h * w] = y[:h, :w].reshape(-1)
    flat[h * w:h * w * 5 // 4] = u[:h // 2, :w // 2].reshape(-1)
    flat[h * w * 5 // 4:] = v[:h // 2, :w // 2].reshape(-1)
    f2 = av.VideoFrame.from_ndarray(arr, format="yuv420p")
    return f2.to_ndarray(width=D.INP_W, height=D.INP_H, format="rgb24", interpolation="AREA")


def webrtc_evidence(pc, offer_sdp, answer_sdp):
    """What proves the frames came over WebRTC: the WHEP offer / answer SDP, ICE (states, candidates, nominated
    pair) and DTLS-SRTP (state, role, SRTP profile) of the receiving transport, read once the first frame is in.
    Uses a few private aiortc / aioice attributes, for evidence only: any failure is recorded, never raised."""
    ev = dict(offer_sdp=offer_sdp, answer_sdp=answer_sdp, ice_connection_state=getattr(pc, "iceConnectionState", None),
              connection_state=getattr(pc, "connectionState", None))
    try:
        for t in pc.getTransceivers():
            dtls = t.receiver.transport
            ice = dtls.transport
            cand = lambda c: f"{c.type}/{c.protocol}/{c.ip}/{c.port}"
            ev.update(mid=t.mid, kind=t.kind, dtls_state=dtls.state, dtls_role=getattr(dtls, "_role", None),
                      ice_state=ice.state, ice_role=ice.role,
                      ice_local_candidates=[cand(c) for c in ice.iceGatherer.getLocalCandidates()],
                      ice_remote_candidates=[cand(c) for c in ice.getRemoteCandidates()],
                      ice_nominated=[repr(p) for p in getattr(ice._connection, "_nominated", {}).values()])
            try:
                prof = dtls._ssl.get_selected_srtp_profile()
                ev["srtp_profile"] = prof.decode() if isinstance(prof, bytes) else str(prof)
            except Exception as e:      # noqa: BLE001
                ev["srtp_profile"] = f"n/a ({e!r})"
            break
    except Exception as e:      # noqa: BLE001
        ev["evidence_error"] = repr(e)
    return ev


class WhepFrameSource:
    """Drop-in for engine.vision.stream.FrameSource (run_stream reads only `.q`)."""

    def __init__(self, url, D, src0=2000, step=1, maxsize=1200, drop_when_full=True, ready_file=None,
                 warm=None, idle_s=3.0, max_s=900.0, connect_s=60.0, feed=True, stale_ms=None, save_frames=None):
        self.url, self.D, self.src0, self.step = url, D, src0, step
        self.q = queue.Queue(maxsize=maxsize)
        self.drop_when_full = drop_when_full
        self.ready_file, self.warm = ready_file, warm
        self.idle_s, self.max_s, self.connect_s, self.feed = idle_s, max_s, connect_s, feed
        self.stale_ms = stale_ms      # bounded mode: frames already older than this are not prepared at all
        # --save-frames: the exact 512x288 RGB frames handed to the engine, appended raw (uint8, in arrival
        # order) for scripts/webrtc_render_demo.py; row["saved"] = index in that file. One memcpy + write.
        self.save_fh = open(save_frames, "wb") if save_frames else None
        self.n_saved = 0
        self._pq = queue.Queue()
        self.rows = []
        self.by_k = {}
        self.info = dict(reader="whep-aiortc", dropped=0, bad_code=0, leadin=0, clip=0, end=0, decoded=0, prep_skipped=0)
        self.stop_ev = threading.Event()
        self._ended = False
        self._clip_started = False
        self._lock = threading.Lock()

    def start(self):
        self._t_loop = threading.Thread(target=self._run_loop, daemon=True)
        self._t_prep = threading.Thread(target=self._prep, daemon=True)
        self._t_prep.start()
        self._t_loop.start()
        return self

    # ------------------------------------------------------------------ WHEP / aiortc (asyncio thread)
    def _post(self, sdp):
        deadline = time.time() + self.connect_s
        last = None
        while time.time() < deadline:
            req = urllib.request.Request(self.url, data=sdp.encode(), method="POST",
                                         headers={"Content-Type": "application/sdp"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    loc = r.headers.get("Location")
                    return r.read().decode(), loc
            except urllib.error.HTTPError as e:      # 404 until the sender publishes
                last = f"HTTP {e.code}"
            except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
                last = repr(e)
            time.sleep(0.25)
        raise RuntimeError(f"WHEP {self.url}: no answer within {self.connect_s}s ({last})")

    def _run_loop(self):
        try:
            asyncio.run(self._main())
        except Exception as e:      # noqa: BLE001
            self.info["error"] = repr(e)
        finally:
            self._pq.put(None)

    async def _main(self):
        from aiortc import RTCPeerConnection, RTCRtpReceiver, RTCSessionDescription
        from aiortc.mediastreams import MediaStreamError
        loop = asyncio.get_running_loop()
        pc = RTCPeerConnection()
        tr = pc.addTransceiver("video", direction="recvonly")
        caps = RTCRtpReceiver.getCapabilities("video").codecs
        tr.setCodecPreferences([c for c in caps if c.mimeType.lower() in ("video/h264", "video/rtx")])
        fut = loop.create_future()

        @pc.on("track")
        def _on_track(t):
            if t.kind == "video" and not fut.done():
                fut.set_result(t)
        await pc.setLocalDescription(await pc.createOffer())
        offer_sdp = pc.localDescription.sdp
        t_post = time.time()
        answer, loc = await loop.run_in_executor(None, self._post, offer_sdp)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer, type="answer"))
        self.info.update(whep_connect_s=round(time.time() - t_post, 3),
                         codec=next((ln for ln in answer.splitlines() if "rtpmap" in ln and "H264" in ln), None))
        track = await asyncio.wait_for(fut, 10)
        t_start = time.time()
        while not self.stop_ev.is_set():
            try:
                frame = await asyncio.wait_for(track.recv(), timeout=self.idle_s)
            except asyncio.TimeoutError:
                if self._clip_started or time.time() - t_start > self.max_s:
                    self.info["stopped_by"] = "idle"
                    break
                continue
            except MediaStreamError:
                self.info["stopped_by"] = "track ended"
                break
            t_h = time.time()
            # wall - monotonic at hand-off: time.time() can be slewed / stepped (observed: backward steps up to
            # 1.6 ms in the 2026-10-03 campaign); a change in this offset between frames shows such a step
            self._pq.put((frame, t_h, t_h - time.monotonic()))
            if "webrtc" not in self.info:
                self.info["webrtc"] = webrtc_evidence(pc, offer_sdp, answer)
            if time.time() - t_start > self.max_s:
                self.info["stopped_by"] = "max_s"
                break
        try:
            await pc.close()
        finally:
            if loc:
                try:
                    url = loc if loc.startswith("http") else self.url.split("/", 3)[0] + "//" + \
                        self.url.split("/", 3)[2] + loc
                    urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=2).close()
                except Exception:   # noqa: BLE001
                    pass

    # ------------------------------------------------------------------ prep thread
    def _end(self):
        with self._lock:
            if self._ended:
                return
            self._ended = True
        self.q.put(None)

    def _prep(self):
        D = self.D
        while True:
            it = self._pq.get()
            if it is None:
                break
            frame, t_h, wm = it
            self.info["decoded"] += 1
            w, hh = frame.width, frame.height
            h = hh - FC.STRIP_H
            y = np.frombuffer(frame.planes[0], np.uint8).reshape(-1, frame.planes[0].line_size)
            code = FC.read(y[h:h + FC.STRIP_H, :w])
            st = aiortc_patch.STAMPS.pop(frame.pts, None) or {}
            row = dict(pts=frame.pts, key=bool(frame.key_frame), pict=str(getattr(frame.pict_type, "name", frame.pict_type)),
                       t_first=st.get("t_first"), t_complete=st.get("t_complete"), t_dec0=st.get("t_dec0"),
                       t_dec1=st.get("t_dec1"), n_packets=st.get("n_packets"), nbytes=st.get("nbytes"), t_handoff=t_h,
                       wm=wm)
            if code is None:
                self.info["bad_code"] += 1
                row["seq"] = None
                self.rows.append(row)
                continue
            src = None if code["src"] == FC.NO_SRC else code["src"]
            row.update(seq=code["seq"], flags=code["flags"], src=src, t_cap_code=FC.unwrap_ms(code["t_ms"], t_h))
            if code["flags"] & FC.CLIP:
                self.info["clip"] += 1
                self._clip_started = True
                k = (src - self.src0) // self.step
                row["k"] = k
                if self.feed and self.stale_ms is not None and (time.time() - t_h) * 1e3 > self.stale_ms:
                    # run_stream's bounded mode would skip it anyway (older than max_lag_ms when dequeued);
                    # not resizing it saves the CPU a backlogged receiver lacks. Counted, never silent.
                    self.info["prep_skipped"] += 1
                    row["fed"] = False
                    row["prep_skipped"] = True
                elif self.feed:
                    small = crop_resize(frame, y, h, w, D)
                    t_r = time.time()
                    row["t_ready"] = t_r
                    dec_ms = ((st["t_dec1"] - st["t_dec0"]) * 1e3) if st.get("t_dec0") else float("nan")
                    item = (k, np.ascontiguousarray(small), t_h, dec_ms, (t_r - t_h) * 1e3)
                    if self.save_fh is not None:
                        self.save_fh.write(item[1].tobytes())
                        row["saved"] = self.n_saved
                        self.n_saved += 1
                    try:
                        if self.drop_when_full:
                            self.q.put_nowait(item)
                        else:
                            self.q.put(item)
                        row["fed"] = True
                    except queue.Full:
                        self.info["dropped"] += 1
                        row["fed"] = False
                else:
                    small = crop_resize(frame, y, h, w, D)
                    row["t_ready"] = time.time()
                self.by_k[k] = row
            elif code["flags"] & FC.END:
                self.info["end"] += 1
                if self._clip_started:
                    self.rows.append(row)
                    self._end()
                    continue
            elif code["flags"] & FC.LEADIN:
                self.info["leadin"] += 1
                if (self.ready_file and self.info["leadin"] >= 10 and (self.warm is None or self.warm.is_set())
                        and not os.path.exists(self.ready_file)):
                    Path(self.ready_file).write_text(f"{time.time():.6f}\n")
                    self.info["ready_at"] = time.time()
            self.rows.append(row)
        self._end()

    def stop(self):
        self.stop_ev.set()


# ---------------------------------------------------------------------------------------------- main
def read_sender_log(path, wait_s=20.0):
    """-> (meta, {seq: row}, end-row). Waits for the sender's end marker."""
    deadline = time.time() + wait_s
    while True:
        lines = open(path).read().splitlines() if os.path.exists(path) else []
        rows = [json.loads(x) for x in lines if x.strip()]
        end = next((r for r in rows if r.get("type") == "end"), None)
        if end is not None or time.time() > deadline:
            break
        time.sleep(0.25)
    meta = next((r for r in rows if r.get("type") == "meta"), {})
    by_seq = {r["seq"]: r for r in rows if "seq" in r}
    return meta, by_seq, end


def versions():
    import aioice
    import aiortc
    import av
    import onnxruntime
    return dict(python=sys.version.split()[0], aiortc=aiortc.__version__, aioice=getattr(aioice, "__version__", None),
                pyav=av.__version__, libav=str(getattr(av, "ffmpeg_version_info", None)),
                onnxruntime=onnxruntime.__version__, numpy=np.__version__)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--label", default="run")
    ap.add_argument("--step", type=int, default=1, help="the sender's decimation step (1 = every source frame)")
    ap.add_argument("--src0", type=int, default=2000, help="source frame number of the clip's first frame")
    ap.add_argument("--video", default="test_2")
    ap.add_argument("--mode", default="engine", choices=["engine", "transport"],
                    help="engine: feed the CV engine; transport: decode + prep only (the video leg alone)")
    ap.add_argument("--calls", default="auto", choices=["auto", "on", "off"],
                    help="auto: frozen call model when step == 1, track-only otherwise")
    ap.add_argument("--backend", default="onnx-coreml-gpu16,onnx-coreml-ane16")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--max-lag-ms", type=float, default=None,
                    help="run_stream's bounded mode: skip to the newest frame when the dequeued one is older")
    ap.add_argument("--frozen", default=str(VS.FROZEN_PATH))
    ap.add_argument("--stock-jitter", action="store_true", help="aiortc's own frame completion (next-frame)")
    ap.add_argument("--jb-capacity", type=int, default=1024)
    ap.add_argument("--no-loopback", action="store_true", help="let aioice offer LAN candidates (remote relay)")
    ap.add_argument("--ready-file", default=None)
    ap.add_argument("--sender-log", default=None)
    ap.add_argument("--idle-s", type=float, default=3.0)
    ap.add_argument("--save-frames", default=None,
                    help="engine mode: append the 512x288 RGB frames fed to the engine (raw uint8) to this file, "
                         "and write the engine's per-frame track rows, for scripts/webrtc_render_demo.py")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    assert_paper_only()
    sys.setswitchinterval(0.001)      # the asyncio/RTP thread must not wait 5 ms for the engine thread's GIL
    aiortc_patch.apply(use_marker=not a.stock_jitter, video_capacity=a.jb_capacity, loopback_only=not a.no_loopback)
    M = VS.tracking_modules()
    calls = a.mode == "engine" and (a.calls == "on" or (a.calls == "auto" and a.step == 1))
    frozen, geo, geo_prov = None, None, "n/a"
    if calls:
        frozen = VS.load_frozen(a.frozen)
        geo, geo_prov = VS.load_geometry(a.video, frozen)
    offset = a.src0 if a.step == 1 else 0
    live = {}
    emit_wm = {}      # id(CallEvent) -> wall - monotonic right after the engine stamped t_emit (clock-step check)

    def on_event(ev):
        emit_wm[id(ev)] = time.time() - time.monotonic()
        r = live.get(ev.frame - offset, {})
        cap = r.get("t_cap_code")
        tag = "" if a.step == 1 else " [OUT OF DISTRIBUTION: decimated stream]"
        msg = f"[{ev.call}] frame {ev.frame} p_miss={ev.p_miss:.3f} engine {ev.latency_ms:.1f} ms"
        if cap:
            msg += f" | capture->emit {(ev.t_emit - cap) * 1e3:.1f} ms (video leg {(r['t_handoff'] - cap) * 1e3:.1f} ms)"
        print(msg + tag, flush=True)

    eng = None
    warm = threading.Event()
    if a.mode == "engine":
        eng = VS.VisionCallEngine(VS.make_backend(a.backend, None, a.threads), frozen, geo,
                                  fps=120.0 / a.step, frame_offset=offset, on_event=on_event)
        x0 = np.zeros((1, 9, M.D.INP_H, M.D.INP_W), np.float32)
        t = time.time()
        for b in eng.det.backends:      # first CoreML call compiles; not part of the stream
            for _ in range(3):
                b(x0)
        print(f"receiver: engine warm ({eng.det.name}, {time.time() - t:.1f}s), calls={'on' if calls else 'off'}",
              flush=True)
    warm.set()
    src = WhepFrameSource(a.url, M.D, src0=a.src0, step=a.step, ready_file=a.ready_file, warm=warm,
                          idle_s=a.idle_s, feed=(a.mode == "engine"), stale_ms=a.max_lag_ms,
                          save_frames=(a.save_frames if a.mode == "engine" else None))
    live = src.by_k
    load0 = [round(x, 2) for x in os.getloadavg()]
    src.start()
    t0 = time.time()
    erows, skipped = [], 0
    if eng is not None:
        erows, skipped = VS.run_stream(eng, src, a.max_lag_ms)
    else:
        while src.q.get() is not None:
            pass
    wall = time.time() - t0
    src.stop()
    src._t_loop.join(timeout=10)
    if src.save_fh is not None:
        src.save_fh.close()
    load1 = [round(x, 2) for x in os.getloadavg()]
    if "error" in src.info:
        print(f"receiver error: {src.info['error']}", flush=True)

    # ---- join with the sender's log and the engine's per-frame results
    smeta, sent, send_end = read_sender_log(a.sender_log) if a.sender_log else ({}, {}, None)
    done = {r["i"]: r for r in erows}
    frames = []
    for r in src.rows:
        s = sent.get(r.get("seq"))
        if s:
            r.update(t_due=s["t_due"], t_w0=s["t_w0"], t_w1=s["t_w1"])
        k = r.get("k")
        if k is not None and eng is not None:
            idx = k + offset
            if k in done:
                d = done[k]
                # engine stage times while processing this frame's arrival (it finalises frame k-2 and makes
                # the decision for frame k): detector, blob extraction, tracker, call rule (features + classifier)
                r.update(engine_done=True, **{n: round(d[n], 3) for n in ("qwait_ms", "proc_ms", "infer_ms", "blobs_ms",
                                                                         "track_ms", "feat_ms", "clf_ms")})
            if idx in eng.ready_ms:
                r["t_decision"] = r["t_handoff"] + eng.ready_ms[idx] / 1e3
        frames.append(r)
    by_k = {r["k"]: r for r in frames if r.get("k") is not None}
    events = []
    if eng is not None:
        for ev in eng.events:
            d = ev.to_dict()
            r = by_k.get(ev.frame - offset, {})
            # the four times the task asks for, by name: send (capture = paced send due time; send_done = ffmpeg
            # took the frame), receive (decoded frame handed to us; rx_complete = last RTP packet in), model done
            # (the decision step for this frame finished: detector + tracker + features + classifier), emit
            d.update(type="call", seq=r.get("seq"), src=r.get("src"), t_send=r.get("t_due"), t_send_done=r.get("t_w1"),
                     t_rx_complete=r.get("t_complete"), t_recv=r.get("t_handoff"), t_model_done=r.get("t_decision"),
                     t_due=r.get("t_due"), t_handoff=r.get("t_handoff"),
                     capture_to_emit_ms=((ev.t_emit - r["t_due"]) * 1e3 if r.get("t_due") else None),
                     capture_to_handoff_ms=((r["t_handoff"] - r["t_due"]) * 1e3 if r.get("t_due") else None),
                     wm_emit=emit_wm.get(id(ev)), wm_handoff=r.get("wm"),
                     out_of_distribution=(a.step != 1))
            events.append(d)
    sent_clip = [q for q, s in sent.items() if s.get("flags", 0) & FC.CLIP]
    extra = dict(engine=None)
    if eng is not None:
        es = VS.summarize(erows, wall, skipped, eng)
        extra["engine"] = {k: es.get(k) for k in ("frames", "skipped", "fps_sustained", "infer_ms", "proc_ms",
                                                  "qwait_ms", "call_ready_ms", "detector", "detector_call_ms",
                                                  "per_decision_ms")}
        from engine.vision.run_demo import detection_check, match_events, offline_comparison
        tl = [(r[0] if a.step == 1 else a.src0 + int(r[0]) * a.step,) + tuple(r[1:]) for r in eng.track_log]
        extra["detection_vs_labels"] = detection_check(tl, a.video)
        if calls and a.step == 1:
            f_lo = a.src0
            f_hi = a.src0 + (max(by_k) + 1 if by_k else 0)
            extra["vs_offline"] = offline_comparison(eng, frozen, a.video, f_lo, f_hi)
            extra["events_vs_labels"], extra["flights_in_clip"] = match_events(eng.events, frozen, a.video, f_lo, f_hi)
    summ = report.summarize(frames, events, sent_clip, extra)
    summ.update(receiver=dict(src.info, jitter=dict(aiortc_patch.COUNTERS)), sender_end=send_end)

    meta = dict(type="meta", role="receiver", label=a.label, when=datetime.datetime.now().isoformat(timespec="seconds"),
                url=a.url, mode=a.mode, step=a.step, arrival_fps=smeta.get("fps"), calls=calls,
                calls_valid=(calls and a.step == 1), backend=(a.backend if eng is not None else None),
                max_lag_ms=a.max_lag_ms, frozen=(a.frozen if calls else None), geometry=geo_prov,
                aiortc_patch=aiortc_patch.state(), versions=versions(), sender=smeta,
                host=platform.node(), machine=f"{platform.system()} {platform.machine()}",
                load_avg_start=load0, load_avg_end=load1, wall_s=round(wall, 3),
                note="our own clip streamed by us over loopback WebRTC (MediaMTX); not a match feed. "
                     "No camera / display: capture = the paced sender's due time.")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write(json.dumps(meta, default=str) + "\n")
        for r in frames:
            fh.write(json.dumps(dict(type="frame", **{k: (round(v, 6) if isinstance(v, float) else v)
                                                      for k, v in r.items()})) + "\n")
        for e in events:
            fh.write(json.dumps(e, default=float) + "\n")
        if a.save_frames and eng is not None:
            meta_sf = dict(type="saved_frames", path=a.save_frames, n=src.n_saved, shape=[M.D.INP_H, M.D.INP_W, 3],
                           dtype="uint8", order="arrival (row 'saved' of each frame row)")
            fh.write(json.dumps(meta_sf) + "\n")
            for f, *rest in eng.track_log:      # (source frame, x, y, ...) in full-resolution pixels; NaN = no ball
                fh.write(json.dumps(dict(type="track", f=int(f), xy=[None if not np.isfinite(v) else round(float(v), 2)
                                                                        for v in rest[:2]])) + "\n")
        fh.write(json.dumps(dict(type="summary", **summ), default=float) + "\n")
    L = summ["latency_ms"]

    def p(name):
        d = L.get(name)
        return "n/a" if not d else f"p50 {d['p50']:.1f} / p90 {d['p90']:.1f} / p99 {d['p99']:.1f} ms (n={d['n']})"
    print(f"\n== {a.label}: step {a.step} @ {smeta.get('fps')} fps, mode {a.mode}, calls {calls}")
    print(f"frames: {summ['frames']}")
    print(f"capture -> decoded frame in our process (video leg): {p('capture_to_handoff')}")
    print(f"capture -> engine decision ready:                    {p('capture_to_decision')}")
    if summ.get("calls"):
        print(f"calls: {summ['calls']}")
    print(f"wrote {a.out}", flush=True)


if __name__ == "__main__":
    main()
