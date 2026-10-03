#!/usr/bin/env bash
# COURTSIDE: one command per thing a judge might want to run.   bash run.sh <cmd> [args]
# PAPER ONLY everywhere: nothing in this repo signs, sends or cancels a real order, and no key is read.
# Live commands read public, keyless Polymarket market data only.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PY=${PY:-.venv/bin/python}
PYTHON=${PYTHON:-python3}

usage() {
  cat <<'EOF'
bash run.sh <command> [args]                                  (times: laptop, after setup)

  setup [--full]      make .venv, pip install -r requirements.txt               ~1-3 min
                      --full also installs requirements-extra.txt (vision, deck: torch, onnxruntime...)
  tests               unit tests (pytest: tests/, engine/vision/tests/)          ~2-7 min (393 s on a loaded laptop)
  replay              10 min of recorded live Polymarket books (tests/fixtures/live_sample.jsonl.gz)
                      through the live paper trader and the engine's order books  ~15 s, no network
  live [args]         live paper session on live public Polymarket data, read-only, until Ctrl-C
                      (scripts/live_paper.py --test). Quoting starts after a warm-up of 50 public trades (the
                      pre-registered trade-side check), so on a quiet tape it can quote nothing for a while;
                      --minutes N counts from the start of quoting, not from launch (use Ctrl-C to stop earlier)
  data [--smoke DAY] [--parallel]
                      public Polymarket crawl into data/ (scripts/fetch_polymarket.py), no keys.
                      ETA ~1-2 h for ~13k tapes; resumable: every read is cached in data/raw, rerun to continue.
                      --smoke DAY: event list + tapes of the matches starting on DAY (default 2026-01-15, 38 in-sample matches), ~1-3 min
  reproduce           bash reproduce.sh: every number and figure in docs/NOTE.pdf (needs the full `data` crawl
                      first; one smoke day is not enough for the walk-forward tables)        ~15 min
  engine [demo|books|live]
                      COURTSIDE engine, paper only. demo: vision calls -> paper decisions on a recorded book
                      (needs data/live, data/vision, models/); books: engine order books on the committed
                      sample; live: 60 s of live books, read-only. Default: demo if its inputs exist, else
                      books, then live.
  cv                  ball-tracking call engine on the held-out OpenTTGames clip (needs setup --full;
                      fetches BlurBall weights via scripts/get_models.sh and the clip with ffmpeg). The point-end
                      calls need models/vision/frozen_call_model.pkl, which is not in git (rebuilt on HiPerGator by
                      sbatch hpg/engine_vision.sbatch); without it, cv detects and tracks with calls disabled
  dashboard [port]    status daemon + read-only dashboard at http://localhost:8765 (Ctrl-C stops both)
  money [args]        terminal replay of the v2 in-sample backtest with a running paper-money counter
                      (needs `data` then `reproduce`: reads data/v2_trades_is_oos.parquet; scripts/money_counter.py)
EOF
}

need_venv() {
  [ -x "$PY" ] || { echo "no $PY: run 'bash run.sh setup' first (or set PY=/path/to/python)"; exit 1; }
}

cmd=${1:-help}
[ $# -gt 0 ] && shift

case "$cmd" in
  setup)
    [ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
    if [ "${1:-}" = "--full" ]; then .venv/bin/python -m pip install -r requirements-extra.txt; fi
    .venv/bin/python -c "import numpy, pandas, pyarrow, scipy, websockets; print('setup ok:', __import__('sys').version.split()[0])"
    ;;

  tests)
    need_venv
    if "$PY" -c "import cv2, sklearn" 2>/dev/null; then
      "$PY" -m pytest -q tests engine/vision/tests "$@"
    else
      echo "(engine/vision/tests need opencv + scikit-learn: bash run.sh setup --full; running tests/ only)"
      "$PY" -m pytest -q tests "$@"
    fi
    ;;

  replay)
    need_venv
    echo "== 1/2 maker v1 live paper trader replaying 10 min of recorded live books (paper only)"
    "$PY" scripts/replay_sample.py paper --replay-pause "${REPLAY_PAUSE:-0.5}" "$@"
    echo
    echo "== 2/2 COURTSIDE engine order books on the same sample"
    "$PY" scripts/replay_sample.py engine
    ;;

  live)
    need_venv
    echo "live paper session: public Polymarket market data, read-only, PAPER ONLY (no orders). Ctrl-C to stop."
    "$PY" scripts/live_paper.py --test "$@"
    ;;

  data)
    need_venv
    smoke="" parallel=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --smoke) smoke=${2:-2026-01-15}; shift; [ $# -gt 0 ] && shift ;;
        --parallel) parallel=1; shift ;;
        *) echo "unknown data arg $1"; exit 2 ;;
      esac
    done
    if [ -n "$smoke" ]; then
      echo "smoke fetch: the full event list (~30 s, cached) and the trade tapes of singles starting on $smoke"
      "$PY" - "$smoke" <<'EOF'
import sys, time
sys.path.insert(0, ".")
from src import polymarket as pm
from src.tape import universe
t = time.time()
u = universe()                       # the same cached event list as the full crawl (data/raw/events_tennis_*)
day = u[u.start.dt.strftime("%Y-%m-%d") == sys.argv[1]]
print(f"{len(u)} singles >= $5k in the universe; {len(day)} start on {sys.argv[1]} "
      f"({'includes out-of-sample' if day.oos.any() else 'in-sample'}); fetching their tapes", flush=True)
pm.fetch_many_trades(day.cond.tolist())
print(f"smoke fetch done in {time.time() - t:.0f} s")
EOF
      exit 0
    fi
    echo "full crawl: ETA ~1-2 h (event list ~5-10 min, then ~13k trade tapes). Resumable: rerun to continue."
    progress() {
      local t0 n0 n
      t0=$(date +%s); n0=$(ls data/raw/trades 2>/dev/null | wc -l)
      while sleep 60; do
        n=$(ls data/raw/trades 2>/dev/null | wc -l)
        "$PY" - "$n" "$n0" "$t0" <<'EOF' || true
import glob, sys, time
import pandas as pd
n, n0, t0 = map(int, sys.argv[1:])
f = glob.glob("data/raw/events_tennis_2025-07-01_2026-10-03.parquet")
if not f:
    print(f"[data] enumerating events... {n} tapes cached", flush=True); raise SystemExit
ev = pd.read_parquet(f[0])
need = int((ev.series.isin(["atp", "wta", "challenger"]) & (ev.volume >= 5000)).sum())
rate = (n - n0) / max(time.time() - t0, 1)
eta = (need - n) / rate / 60 if rate > 0 else float("nan")
print(f"[data] {n}/{need} tapes cached, {rate * 60:.0f}/min, ETA {eta:.0f} min", flush=True)
EOF
      done
    }
    progress & PROG=$!
    trap 'kill $PROG 2>/dev/null || true' EXIT
    if [ -n "$parallel" ]; then
      "$PY" -c "import sys; sys.path.insert(0,'.'); from src import polymarket as pm; from scripts.fetch_polymarket import SINCE, UNTIL; pm.enumerate_events('tennis', SINCE, UNTIL)"
      "$PY" scripts/fetch_reverse.py & R1=$!
      "$PY" scripts/fetch_middle.py & R2=$!
      "$PY" scripts/fetch_polymarket.py
      wait $R1 $R2
    else   # Gamma rate-limits long crawls ("RuntimeError: GET failed"); every finished read stays cached
      for attempt in 1 2 3 4; do
        "$PY" scripts/fetch_polymarket.py && break
        [ "$attempt" = 4 ] && { echo "data: fetch failed 4 times; rerun 'bash run.sh data' to resume"; exit 1; }
        echo "data: fetch stopped (attempt $attempt); resuming from the cache in 60 s"; sleep 60
      done
    fi
    echo "data done: $(ls data/raw/trades | wc -l) tapes in data/raw/trades"
    ;;

  reproduce)
    need_venv
    if ! ls data/raw/events_tennis_*.parquet >/dev/null 2>&1 || [ "$(ls data/raw/trades 2>/dev/null | wc -l)" -lt 1000 ]; then
      echo "reproduce needs the full public crawl first: bash run.sh data (~1-2 h, resumable)."
      echo "found $(ls data/raw/trades 2>/dev/null | wc -l | tr -d ' ') trade tapes in data/raw/trades; the walk-forward tables need the whole year."
      [ "${FORCE:-0}" = 1 ] || { echo "(set FORCE=1 to run anyway)"; exit 1; }
    fi
    PY="$PY" bash reproduce.sh "$@"
    ;;

  engine)
    need_venv
    what=${1:-auto}
    if [ "$what" = auto ]; then
      if ls data/live/market_* >/dev/null 2>&1 && [ -f data/vision/test_2_copyts.mp4 ] && [ -d models/vision ]; then
        what=demo
      else
        echo "engine demo inputs not present (data/live/market_*, data/vision/test_2_copyts.mp4, models/vision):"
        echo "showing the engine's order books on the committed sample instead, then 60 s of live books."
        what=books
      fi
      bash "$HERE/run.sh" engine "$what"
      exec bash "$HERE/run.sh" engine live
    fi
    case "$what" in
      demo)  "$PY" -m engine.run --mode demo ;;
      books) "$PY" scripts/replay_sample.py engine ;;
      live)  "$PY" -m engine.run --mode live-market --seconds "${SECONDS_LIVE:-60}" ;;
      *) echo "engine demo|books|live"; exit 2 ;;
    esac
    ;;

  cv)
    need_venv
    "$PY" -c "import onnxruntime, cv2, av" 2>/dev/null || { echo "cv needs: bash run.sh setup --full"; exit 1; }
    if [ ! -f models/vision/frozen_call_model.pkl ]; then
      echo "note: models/vision/frozen_call_model.pkl is not in git, so this run detects and tracks the ball with"
      echo "      point-end calls disabled. Rebuild the model on HiPerGator with: sbatch hpg/engine_vision.sbatch"
    fi
    PY="$PY" bash scripts/get_models.sh
    if [ ! -f data/vision/test_2_copyts.mp4 ]; then
      command -v ffmpeg >/dev/null || { echo "cv needs ffmpeg to cut the held-out clip"; exit 1; }
      mkdir -p data/vision
      # OpenTTGames (Voeikov et al., CC BY-NC-SA 4.0): test_2 frames 2000-2999, held out from all training
      src=https://lab.osai.ai/datasets/openttgames/data/test_2.mp4
      if ! ffmpeg -hide_banner -protocols 2>/dev/null | grep -qw https; then   # ffmpeg built without TLS
        echo "ffmpeg has no https: downloading test_2.mp4 (225 MB) with curl first"
        curl -fL -C - -o data/vision/test_2.mp4 "$src"
        src=data/vision/test_2.mp4
      fi
      ffmpeg -loglevel error -ss 16.666667 -i "$src" -frames:v 1000 -c copy -an -copyts data/vision/test_2_copyts.mp4
    fi
    if ! ls data/openttgames/markup/test_2/segmentation_masks/*.png >/dev/null 2>&1; then
      echo "fetching the OpenTTGames test_2 markup (0.9 MB: ball labels, events, table masks)"
      mkdir -p data/openttgames/markup/test_2
      curl -fsSL -o data/openttgames/test_2.zip https://lab.osai.ai/datasets/openttgames/data/test_2.zip
      "$PY" -m zipfile -e data/openttgames/test_2.zip data/openttgames/markup/test_2
    fi
    export OTTG_ROOT="${OTTG_ROOT:-$HERE/data/openttgames}"
    if [ "$(uname)" = Darwin ]; then backend=onnx-coreml-gpu16; else backend=onnx-cpu; fi
    "$PY" -m engine.vision.run_demo --backend "${CV_BACKEND:-$backend}" --modes realtime --host "judge-$(uname -m)" \
          --out "${CV_OUT:-/tmp/courtside_vision_bench.json}" \
          --events-log "${CV_EVENTS:-/tmp/courtside_vision_events.jsonl}" "$@"
    ;;

  dashboard)
    need_venv
    port=${1:-8765}
    "$PY" scripts/status_daemon.py >/dev/null 2>&1 & D=$!
    trap 'kill $D 2>/dev/null || true' EXIT
    bash scripts/serve_live.sh "$port"
    ;;

  money)
    need_venv
    if [ ! -f data/v2_trades_is_oos.parquet ]; then
      echo "money needs data/v2_trades_is_oos.parquet, which bash run.sh reproduce writes (scripts/v2_causal.py)."
      echo "on a fresh clone: bash run.sh data (~1-2 h), then bash run.sh reproduce (~15 min), then bash run.sh money."
      exit 1
    fi
    "$PY" scripts/money_counter.py "$@"
    ;;

  help|-h|--help) usage ;;
  *) echo "unknown command: $cmd"; echo; usage; exit 2 ;;
esac
