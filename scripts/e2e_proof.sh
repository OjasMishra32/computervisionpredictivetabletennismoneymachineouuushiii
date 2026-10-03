#!/usr/bin/env bash
# End-to-end timing proof (PAPER ONLY; no order is signed or sent).
#
#   our held-out clip -> sender (paced, x264 zerolatency, WHIP) -> MediaMTX (127.0.0.1) -> WHEP reader -> CV engine
#   -> CallEvent -> strategy on a LIVE Polymarket tennis book -> risk -> UNSIGNED order payload (order_ready)
#   -> + measured keep-alive RTT/2 to clob.polymarket.com -> + market secondsDelay -> paper fill vs the live book
#
# Label on every output: "paper; order not sent; CV call on our own streamed footage mapped to a live tennis market
# for timing (different sport); feed baseline 1 s is simulated (licensed feed not purchased)".
#
# Usage (repo root):
#   scripts/e2e_proof.sh                 # 12 passes (>= 20 MISS calls) over 2 markets, then figure + video (~25 min)
#   PASSES=1 MAX_PASSES=1 MIN_CALLS=0 scripts/e2e_proof.sh   # quick check (one pass)
#   RENDER_ONLY=1 scripts/e2e_proof.sh   # redraw fig_waterfall.png and e2e_timeline.mp4 from results/e2e/trace.jsonl
# Env: PASSES (12), MAX_PASSES (16), MIN_CALLS (20 complete MISS traces), MARKETS (2),
#      FPS (10: every source frame at 10 frames/s of wall time; the laptop engine cannot
#      keep up with 120 fps), NICE (10), WORK (logs; default $TMPDIR/courtside_e2e/<ts>).
# Needs: mediamtx (brew install mediamtx), ffmpeg with the WHIP muxer, data/vision/test_2_copyts.mp4,
#        models/vision/frozen_call_model.pkl, network access to the public Polymarket endpoints.
# Outputs: results/e2e/trace.jsonl, summary.json, fig_waterfall.png, e2e_timeline.mp4 (research/e2e/RESULTS.md).
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PY="$REPO/.venv/bin/python"
NICE="${NICE:-10}"
if [ -z "${RENDER_ONLY:-}" ]; then
  TS="$(date -u +%Y%m%dT%H%M%SZ)"
  WORK="${WORK:-${TMPDIR:-/tmp}/courtside_e2e}/$TS"
  mkdir -p "$WORK"
  [ -f data/vision/test_2_copyts.mp4 ] || { echo "missing data/vision/test_2_copyts.mp4"; exit 1; }
  [ -f models/vision/frozen_call_model.pkl ] || { echo "missing models/vision/frozen_call_model.pkl (copy from HPG)"; exit 1; }
  MTX="$(command -v mediamtx || true)"
  [ -n "$MTX" ] || { echo "mediamtx not found (brew install mediamtx)"; exit 1; }
  # engine/webrtc/mediamtx.yml with its own ports (WebRTC 8899, UDP 8199, RTSP 8564), so this run never collides
  # with scripts/webrtc_demo.sh on 8889; still loopback only
  sed -e 's/127.0.0.1:8889/127.0.0.1:8899/' -e 's/127.0.0.1:8189/127.0.0.1:8199/' -e 's/127.0.0.1:8554/127.0.0.1:8564/' \
      "$REPO/engine/webrtc/mediamtx.yml" > "$WORK/mediamtx_e2e.yml"
  if lsof -nP -iTCP:8899 -sTCP:LISTEN >/dev/null 2>&1; then echo "port 8899 busy (another e2e run?)"; exit 1; fi
  (cd "$WORK" && exec "$MTX" "$WORK/mediamtx_e2e.yml") > "$WORK/mediamtx.log" 2>&1 &
  MTX_PID=$!
  trap 'kill "$MTX_PID" 2>/dev/null || true' EXIT
  for _ in $(seq 1 50); do curl -s -o /dev/null "http://127.0.0.1:8899/" && break; sleep 0.1; done
  echo "MediaMTX $("$MTX" --version 2>&1 | head -1) pid $MTX_PID; logs in $WORK"
  nice -n "$NICE" "$PY" -m engine.e2e.e2e_run --passes "${PASSES:-12}" --max-passes "${MAX_PASSES:-16}" \
      --min-calls "${MIN_CALLS:-20}" --markets "${MARKETS:-2}" --fps "${FPS:-10}" \
      --mtx-base http://127.0.0.1:8899 --work "$WORK" 2>&1 | grep --line-buffered -v "^objc\[" | tee "$WORK/e2e_run.log"
  kill "$MTX_PID" 2>/dev/null || true
fi
nice -n "$NICE" "$PY" -m engine.e2e.render
