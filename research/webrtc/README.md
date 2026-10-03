# WebRTC latency of our own pipeline (route A1 of SUB_SECOND_ROUTES.md, measured)

Paper only. This measures **our** pipeline on **our** stream: the held-out OpenTTGames clip
`data/vision/test_2_copyts.mp4` (test_2 frames 2000-2999, 1920x1080, 120 fps, CC BY-NC-SA 4.0), streamed by us
through a MediaMTX on 127.0.0.1 and read back over WebRTC. No camera, microphone or third-party stream was used.
It is **not** a Polymarket match feed. For the legal sources of match video, see `research/home_stream/SUB_SECOND_ROUTES.md`.

## Bottom line (2026-10-03, MacBook M4, shared with other jobs)

- **Capture to call: about 41 ms**, over loopback WebRTC, when the CV engine keeps up. Run `slowmo10_engine`
  streamed all 1000 clip frames at 10 frames/s of wall time, so the laptop engine was never behind. The 11
  CallEvents took 39-45 ms from capture to emit (p50 41.5 ms). Of that, the video leg was 4-11 ms and the engine
  34-37 ms. Over all 998 decision frames, capture to decision-ready was p50 40.7, p99 53.9, max 85.4 ms.
  Ten of the 11 calls match the file-source run of the same clip and model (`results/engine/demo_run.json`).
  The eleventh is the same MISS flight called 6 frames (50 ms) earlier: frame 2760 here, 2766 from the file.
  Both MISS calls are correct against the labels, with actual leads of 117 ms and 325 ms.
- **The video leg alone** (capture to a decoded frame in our process, x264 zerolatency, MediaMTX, aiortc) is
  p50 3.8 / p90 5.1 / p99 9.5 ms at native 1080p120 and 7.7 / 11.3 / 15.8 ms at 30 fps (load average 4,
  run 215353Z). The other quiet runs agree: 4.6 / 5.5 / 12.2 at 120 fps, 7.9 / 28.6 / 63.3 at 60 fps and
  9.0 / 14.1 / 18.0 at 30 fps (load 4-12). When other jobs push the load to 11-17, the sender itself falls
  behind its pacing clock (`sender_late`), and the same configuration reaches 111 ms p50 at 120 fps.
- **The laptop engine cannot run the CV in real time at 30-120 fps.** It sustained 9-18 fps here, against 50 fps
  on an idle laptop in `results/engine/vision_bench.json`. With the engine running at 60-120 fps the whole host
  saturates. The sender falls behind its own clock (sender_late p50 147 ms at 60 fps and 1.19 s at 120 fps), and
  aiortc's Python receive loop, which shares a process with the engine, loses frames (up to 106/1000). The video
  leg grows to 0.3-1.3 s p50. The real-time engine runs (bounded lag, 100 ms) are in the table as failure modes,
  not as latency figures.
- **Two things that matter for anyone reproducing this.**
  - VideoToolbox (`h264_videotoolbox`, realtime, prio_speed, no B-frames) holds about 10 frames inside the
    encoder. At 30 fps the video leg was 345 ms p50 against 7.7 ms with x264, with the sender on time
    (sender_late 2 ms) and 338 ms from capture to the first RTP packet. libx264 `-tune zerolatency` holds none.
    An earlier 120 fps VT test (not kept) gave 92 ms, also about 11 frames.
  - Stock aiortc releases a frame only when the first packet of the next frame arrives, which adds one frame
    interval. Back to back at 30 fps, the video leg was 41.9 ms p50 with stock aiortc against 7.7 ms patched.
    First-to-last packet spread was 33.5 ms against 0.9 ms. At 120 fps the spread was 8.0 ms against 0.24 ms.
    Stock aiortc's 128-packet video buffer also cannot hold a 1080p keyframe: frames here reached 268 packets
    (311 KB).
  - Both behaviours are patched on the receiver side (`engine/webrtc/aiortc_patch.py`). `STOCK_JITTER=1`
    reproduces stock aiortc.

All of this is **loopback on one host**: no network, no relay, no camera exposure or readout, no display.
"Capture" is the moment the paced sender (a virtual camera) produced the frame. Not measured here: a remote relay
(we have no server of our own outside this laptop) and glass-to-glass. Others' figures for those are in
SUB_SECOND_ROUTES.md A1: 42 ms local and about 0.4 s through a public Broadcast Box server (S1, S2), and
MediaMTX p50 180 ms LAN-only and 520 ms cross-region (S3).

## Pipeline

```
data/vision clip --PyAV decode--> sender.py: virtual camera, frame n due at t0 + n/fps (t_due = "capture")
   |  appends a 56-row code strip under the picture (framecode.py): seq, source frame, capture ms, CRC16
   v  raw yuv420p 1920x1136 into ffmpeg stdin (t_w0..t_w1), wall clock logged per frame
ffmpeg 8.1: libx264 ultrafast, zerolatency, constrained baseline, no B-frames, GOP 0.5 s, 12 Mb/s VBV -> WHIP muxer
   v
MediaMTX v1.21.1 on 127.0.0.1 (engine/webrtc/mediamtx.yml): WHIP in, WHEP out
   v
whep_reader.py: aiortc 1.15 WHEP client, loopback ICE
   |  aiortc_patch: frame completes on the RTP marker bit (t_first, t_complete); decode stamped (t_dec0, t_dec1)
   |  track.recv() -> t_handoff; prep thread reads the code, crops the strip, resizes to 512x288 RGB with
   |  swscale 'area' (t_ready)
   v  queue items laid out as engine.vision.stream.FrameSource (i, rgb, t_frame = t_handoff, decode_ms, resize_ms)
engine.vision.stream.run_stream (unchanged): BlurBall (CoreML) -> tracker -> flight segmentation -> frozen
call rule -> CallEvent; decision-ready time per frame = VisionCallEngine.ready_ms
```

Each CallEvent row carries `t_send` (capture / paced send), `t_send_done` (ffmpeg took the frame), `t_rx_complete`
(last RTP packet in), `t_recv` (decoded frame handed to us), `t_model_done` (decision step for that frame done) and
`t_emit`. All are wall clock on one host. `engine/webrtc/report.py` defines every leg.

The engine sees source frame numbers only when every frame is sent (step 1: native 120 fps or slow motion).
Only then is the frozen call model in distribution. The 60 and 30 fps streams (every 2nd or 4th frame) run
detection and tracking only (`--calls auto`), because the detector windows, tracker gates and call model were all
built for 120 fps.

## How to run

```
brew install mediamtx                       # v1.21.1; ffmpeg 8.1 (Homebrew) has the WHIP muxer; aiortc is in .venv
scripts/webrtc_demo.sh                      # slowmo10 (engine) + dec30, dec60, native120 (transport and engine)
scripts/webrtc_demo.sh slowmo10             # just the valid capture-to-call run (~2 min)
MODES=transport scripts/webrtc_demo.sh native120
STOCK_JITTER=1 MODES=transport scripts/webrtc_demo.sh dec30      # stock aiortc frame completion
ENCODER=vt MODES=transport scripts/webrtc_demo.sh dec30          # VideoToolbox instead of x264
```

Output: `results/webrtc/run_<ts>.jsonl` holds the meta, per-frame, call and summary rows of every run, tagged
`run`. `results/webrtc/summary_<ts>.json` holds the per-run table from `scripts/webrtc_summary.py`. Logs (ffmpeg,
MediaMTX, sender, receiver) go to `$TMPDIR/courtside_webrtc/<ts>/`. MediaMTX runs from there, so nothing lands
in the repo. The pieces can also run by hand: `python -m engine.webrtc.sender --help` and
`python -m engine.webrtc.whep_reader --help`.

## Measurements

Every run streamed the whole clip (1000 source frames). Latencies are in ms (p50 / p90 / p99). Video leg =
capture to decoded frame in our process. Decision = capture to engine decision ready. Load = 1-min load average at
the start of the run. Other jobs were running on the laptop throughout.

| file (run_<ts>) | run | fps | load | recv/sent | video leg | decision | engine fps | engine skipped |
|---|---|---|---|---|---|---|---|---|
| 20261003T212750Z | **slowmo10_engine** (calls valid) | 10 | 5.8 | 1000/1000 | **6.4 / 9.9 / 14.6** | **40.7 / 45.1 / 53.9** | 9.3 (= arrival) | 0 |
| 20261003T215353Z | native120_transport | 120 | 4.0 | 1000/1000 | **3.8 / 5.1 / 9.5** | | | |
| 20261003T215353Z | dec30_transport | 30 | 3.8 | 250/250 | **7.7 / 11.3 / 15.8** | | | |
| 20261003T214101Z | native120_transport | 120 | 11.8 | 1000/1000 | 4.6 / 5.5 / 12.2 | | | |
| 20261003T214101Z | dec60_transport | 60 | 5.7 | 500/500 | 7.9 / 28.6 / 63.3 | | | |
| 20261003T214101Z | dec30_transport | 30 | 4.1 | 250/250 | 9.0 / 14.1 / 18.0 | | | |
| 20261003T212750Z | dec30_transport | 30 | 4.7 | 250/250 | 6.3 / 9.9 / 46.3 | | | |
| 20261003T212750Z | dec60_transport | 60 | 6.1 | 500/500 | 4.6 / 6.1 / 66.0 | | | |
| 20261003T212750Z | native120_transport | 120 | 13.8 | 1000/1000 | 111 / 375 / 472 (sender late p50 69 ms) | | | |
| 20261003T214101Z | dec30_engine (track only, 100 ms bound) | 30 | 4.6 | 250/250 | 17 / 53 / 256 | 89 / 187 / 457 | 13.8 | 37 |
| 20261003T214101Z | dec60_engine (track only, 100 ms bound) | 60 | 9.7 | 412/500 | 307 / 525 / 775 | 501 / 793 / 1119 | 9.6 | 81 + 183 before prep |
| 20261003T214101Z | native120_engine (calls, 100 ms bound) | 120 | 9.9 | 995/1000 | 1228 / 5443 / 6511 | 1486 / 5861 / 6667 | 14.1 | 145 + 550 before prep |
| 20261003T215723Z | dec30_transport, stock aiortc | 30 | 6.5 | 250/250 | 41.9 / 44.6 / 51.9 | | | |
| 20261003T215723Z | native120_transport, stock aiortc | 120 | 7.1 | 932/1000 | 415 / 1033 / 1993 (sender late p50 205 ms: host saturated, not the jitter buffer) | | | |
| 20261003T215804Z | dec30_transport, VideoToolbox | 30 | 12.2 | 250/250 | 345 / 354 / 432 | | | |
| 20261003T215804Z | native120_transport, VideoToolbox | 120 | 11.4 | 1000/1000 | 2682 / 4586 / 4701 (sender late p50 2.3 s: host saturated) | | | |

Where the time goes (p50, ms):

| leg | slowmo10_engine (212750Z) | native120_transport (214101Z) |
|---|---|---|
| sender late (pacing) | 1.9 | 0.07 |
| capture to first RTP packet in (x264 encode, WHIP, MediaMTX) | 5.0 | 3.8 |
| first to last packet of the frame | 0.6 | 0.3 |
| capture to frame complete | 5.7 | 4.1 |
| decode (libavcodec via PyAV) | 0.5 | 0.4 |
| **capture to decoded frame in our process** | **6.4** | **4.6** |
| code read, crop, 512x288 resize | 1.7 | (not on the path) |
| engine: detector (CoreML GPU, 29.5 ms per window), tracker, features 0.4, classifier 1.1 | 34.2 | |
| **capture to decision ready** | **40.7** | |

Keyframes cost more: in slowmo10 the video leg was I 9.5 ms p50 against P 6.0 ms p50 (200 I-frames, 800 P-frames).

Fidelity through the re-encode (slowmo10, every frame, the same model):
- Detection: 98.05% of labelled ball positions within 5 px (file source: 97.72%), median error 1.44 px.
- Track: agreement with the frozen offline test tracks within 2 px on 99.1% of 701 frames.
- Calls: 10/11 identical to the file-source run. The other MISS came 6 frames earlier (see the bottom line).
- The receiver's resize matches FrameSource's to max 12 / mean 0.21 grey levels on identical input. Building the
  cropped frame loses the decoder's chroma-siting flag, which shifts chroma slightly; the x264 re-encode itself
  changes pixels by more than that.

## What the failures say

- **Engine throughput.** The laptop detector took 29.5 ms per window (single CoreML GPU, slow motion) and
  37-77 ms p50 (GPU+ANE pool, real-time runs under contention). Sustained throughput was 9-18 fps, so real-time
  30-120 fps builds a backlog. Bounded mode keeps the lag finite by skipping frames, and every skipped frame
  breaks the detector's 3-frame windows, so neither `native120_engine` run emitted a call. A host that keeps up
  is needed. On the HiPerGator L4 (`results/engine/vision_bench_gpu.json`), plain torch fp16 sustains 93-95 fps,
  short of 120 fps. fp16 with channels-last, fused BN, torch.compile and a CUDA graph sustains 194 fps.
- **One host and one Python process for everything.** aiortc parses every RTP packet in Python, in the same
  process (and GIL) as the engine. Our own Python sender and x264 encoder compete with both for CPU. At 60-120
  fps with the engine on, frames were lost (dec60: 24 and 88; native120: 106 and 5), and the sender ran late
  (above). A production receiver needs the CV on its own GPU host, and the receive loop in its own process or a
  native receiver (libwebrtc or GStreamer). We did not add another heavy process here (limit of 2 on this shared
  laptop).
- **Sender under load.** At load average 14-17, the Python sender plus x264 at 1080p120 cannot hold its pacing
  clock: `sender_late` reached p50 69 ms. That lateness counts as latency here, as it would for a real camera
  whose frames queue.

## Versions

MediaMTX v1.21.1 (Homebrew bottle), ffmpeg 8.1 (Homebrew; libx264, WHIP muxer), Python 3.14.0, aiortc 1.15.0,
aioice 0.10.2, PyAV 17.1.0 (libav 8.1.1), onnxruntime 1.30.0 (CoreML EP), numpy 2.5.3. The frozen call model
`models/vision/frozen_call_model.pkl` loaded from its pickle (sklearn version match, check error 5.6e-17).
