#!/usr/bin/env bash
# WebRTC latency demo (paper only; our own held-out OpenTTGames clip streamed by us over loopback).
#
#   MediaMTX (127.0.0.1, WHIP/WHEP)  <- sender: clip paced in real time -> ffmpeg H.264 zerolatency -> WHIP
#                                    -> receiver: aiortc WHEP -> decode -> frame code -> engine.vision.stream
#
# Usage (repo root):
#   scripts/webrtc_demo.sh                       # all presets, transport-only and engine runs
#   scripts/webrtc_demo.sh slowmo30 dec30        # some presets
#   MODES=engine ENCODER=vt scripts/webrtc_demo.sh native120
#
# Presets (step = send every step-th source frame; fps = wall-clock frames per second):
#   native120  step 1 @ 120 fps   every frame, real time (the clip's native rate)
#   dec60      step 2 @  60 fps   decimated, real time
#   dec30      step 4 @  30 fps   decimated, real time
#   slowmoN    step 1 @   N fps   every frame at N frames/s of wall time (slow motion, e.g. slowmo10 = 12x):
#                                 the engine sees the 120 fps clip frame by frame at its own time base, so its
#                                 calls are the validated ones, and with N below the engine's sustained fps
#                                 there is no backlog: call latency = video leg + per-frame processing.
#                                 Engine mode only, single backend (BACKEND_SLOWMO: a pool would hold each
#                                 frame until the next one arrives), bitrate SLOWMO_BITRATE.
# Real-time engine runs use run_stream's bounded mode (MAX_LAG_MS, default 100 ms: frames older than that
# are skipped) because the laptop engine does not sustain 30-120 fps; skipped frames are counted.
# Env: MODES (default "transport engine"), ENCODER (x264 | vt), BITRATE (12M), SLOWMO_BITRATE (4M = the
#      30 fps preset's bits per frame at 10 fps), BACKEND (onnx-coreml-gpu16,onnx-coreml-ane16),
#      BACKEND_SLOWMO (onnx-coreml-gpu16), MAX_FRAMES (all 1000), MAX_LAG_MS (100), STOCK_JITTER=1 (aiortc's
#      own next-frame completion, for comparison), WORK (scratch dir for logs; default $TMPDIR/courtside_webrtc),
#      REPS (default 1: repeat the whole preset list REPS times, interleaved; labels get _r<n>),
#      SAVE_FRAMES=1 (rep 1 of each slowmo run saves the frames fed to the engine for webrtc_render_demo.py),
#      SIZE (WxH of the sent picture; default the clip's 1920x1080; label suffix _<H>p),
#      BACKEND_30 / BACKEND_60 / BACKEND_120 (real-time engine backend per preset; default BACKEND),
#      GOP_S (keyframe interval in seconds of wall time, sender default 0.5) and VBV_BUFSIZE (encoder VBV buffer,
#      sender default bitrate / 2): GOP_S=6 SLOWMO_BITRATE=1M VBV_BUFSIZE=6M gives slowmo10 the bits per frame,
#      keyframe spacing and VBV buffer (in frames) of a real-time 120 fps stream at 12 Mb/s,
#      TAG (extra label suffix, e.g. TAG=enc120).
# Output: results/webrtc/run_<ts>.jsonl (every run's meta, frame, call and summary rows, tagged by run label)
#         and results/webrtc/summary_<ts>.json (+ a table on stdout), via scripts/webrtc_summary.py.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PY="$REPO/.venv/bin/python"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="${WORK:-${TMPDIR:-/tmp}/courtside_webrtc}/$TS"
OUT="$REPO/results/webrtc"
MODES="${MODES:-transport engine}"
ENCODER="${ENCODER:-x264}"
BITRATE="${BITRATE:-12M}"
SLOWMO_BITRATE="${SLOWMO_BITRATE:-4M}"
BACKEND="${BACKEND:-onnx-coreml-gpu16,onnx-coreml-ane16}"
BACKEND_SLOWMO="${BACKEND_SLOWMO:-onnx-coreml-gpu16}"
MAX_LAG_MS="${MAX_LAG_MS:-100}"
REPS="${REPS:-1}"
SIZE="${SIZE:-}"
PRESETS=("$@")
[ ${#PRESETS[@]} -eq 0 ] && PRESETS=(slowmo10 dec30 dec60 native120)
mkdir -p "$WORK" "$OUT"

[ -f "$REPO/data/vision/test_2_copyts.mp4" ] || { echo "missing data/vision/test_2_copyts.mp4 (see engine/vision/run_demo.py)"; exit 1; }
MTX="$(command -v mediamtx || true)"
[ -n "$MTX" ] || MTX="$HOME/.local/bin/mediamtx"
[ -x "$MTX" ] || { echo "mediamtx not found (brew install mediamtx)"; exit 1; }
if lsof -nP -iTCP:8889 -sTCP:LISTEN >/dev/null 2>&1; then echo "port 8889 busy (another MediaMTX?)"; exit 1; fi

# MediaMTX runs in WORK so nothing it writes lands in the repo
(cd "$WORK" && exec "$MTX" "$REPO/engine/webrtc/mediamtx.yml") > "$WORK/mediamtx.log" 2>&1 &
MTX_PID=$!
RECV_PID=""
cleanup() { [ -n "$RECV_PID" ] && kill "$RECV_PID" 2>/dev/null || true; kill "$MTX_PID" 2>/dev/null || true; }
trap cleanup EXIT
for _ in $(seq 1 50); do curl -s -o /dev/null "http://127.0.0.1:8889/" && break; sleep 0.1; done
echo "MediaMTX $("$MTX" --version 2>&1 | head -1) pid $MTX_PID; logs in $WORK"

run_one() {   # label step fps mode bitrate backend [receiver args...]
  local label="$1" step="$2" fps="$3" mode="$4" rate="$5" be="$6"; shift 6
  local path="cs_${label}"
  echo; echo "=== $label: step $step @ $fps fps, mode $mode, encoder $ENCODER $rate${be:+, backend $be}"
  rm -f "$WORK/$label.ready"
  "$PY" -m engine.webrtc.whep_reader --url "http://127.0.0.1:8889/$path/whep" --label "$label" --step "$step" \
      --mode "$mode" --backend "$be" --ready-file "$WORK/$label.ready" --sender-log "$WORK/$label.send.jsonl" \
      --out "$WORK/$label.run.jsonl" ${STOCK_JITTER:+--stock-jitter} "$@" > "$WORK/$label.recv.log" 2>&1 &
  RECV_PID=$!
  "$PY" -m engine.webrtc.sender --whip-url "http://127.0.0.1:8889/$path/whip" --step "$step" --fps "$fps" \
      --encoder "$ENCODER" --bitrate "$rate" ${MAX_FRAMES:+--max-frames "$MAX_FRAMES"} ${SIZE:+--size "$SIZE"} \
      ${GOP_S:+--gop-s "$GOP_S"} ${VBV_BUFSIZE:+--bufsize "$VBV_BUFSIZE"} \
      --log "$WORK/$label.send.jsonl" --ready-file "$WORK/$label.ready" --ffmpeg-log "$WORK/$label.ffmpeg.log" \
      > "$WORK/$label.send.log" 2>&1 || echo "sender failed (see $WORK/$label.send.log)"
  wait "$RECV_PID" || echo "receiver failed (see $WORK/$label.recv.log)"
  RECV_PID=""
  grep -v "^objc\[" "$WORK/$label.recv.log" | grep -E "^\[|^==|^frames|^capture|^calls|error" | tail -n 30 || true
  [ -f "$WORK/$label.run.jsonl" ] && "$PY" -c "import json,sys; [print(json.dumps(dict(json.loads(l), run='$label'))) for l in open(sys.argv[1])]" \
      "$WORK/$label.run.jsonl" >> "$OUT/run_${TS}.jsonl"
}

SFX0="${STOCK_JITTER:+_stockjb}"
[ "$ENCODER" != x264 ] && SFX0="${SFX0}_$ENCODER"
[ -n "$SIZE" ] && SFX0="${SFX0}_${SIZE#*x}p"
[ -n "${TAG:-}" ] && SFX0="${SFX0}_${TAG}"
for rep in $(seq 1 "$REPS"); do
  SFX="$SFX0"
  [ "$REPS" -gt 1 ] && SFX="${SFX0}_r$rep"
  for p in "${PRESETS[@]}"; do
    case "$p" in
      native120) step=1; fps=120; be_rt="${BACKEND_120:-$BACKEND}" ;;
      dec60)     step=2; fps=60;  be_rt="${BACKEND_60:-$BACKEND}" ;;
      dec30)     step=4; fps=30;  be_rt="${BACKEND_30:-$BACKEND}" ;;
      slowmo*)   step=1; fps="${p#slowmo}"
                 save=()
                 [ -n "${SAVE_FRAMES:-}" ] && [ "$rep" = 1 ] && save=(--save-frames "$WORK/${p}_engine$SFX.frames.u8")
                 run_one "${p}_engine$SFX" 1 "$fps" engine "$SLOWMO_BITRATE" "$BACKEND_SLOWMO" ${save[@]+"${save[@]}"}; continue ;;
      *) echo "unknown preset $p"; continue ;;
    esac
    for m in $MODES; do
      if [ "$m" = engine ]; then run_one "${p}_engine$SFX" "$step" "$fps" engine "$BITRATE" "$be_rt" --max-lag-ms "$MAX_LAG_MS"
      else run_one "${p}_transport$SFX" "$step" "$fps" transport "$BITRATE" ""; fi
    done
  done
done

"$PY" scripts/webrtc_summary.py "$OUT/run_${TS}.jsonl" --out "$OUT/summary_${TS}.json"
echo "wrote $OUT/run_${TS}.jsonl and $OUT/summary_${TS}.json"
