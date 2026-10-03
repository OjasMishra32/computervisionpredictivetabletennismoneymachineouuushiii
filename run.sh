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
  tests               unit tests (pytest: tests/, engine/vision/tests/)          ~1 min
  replay              10 min of recorded live Polymarket books (tests/fixtures/live_sample.jsonl.gz)
                      through the live paper trader and the engine's order books  ~15 s, no network
  live [args]         live paper session on live public Polymarket data, read-only, until Ctrl-C
                      (scripts/live_paper.py --test; e.g. bash run.sh live --minutes 10)
  data [--smoke DAY] [--parallel]
                      public Polymarket crawl into data/ (scripts/fetch_polymarket.py), no keys.
                      ETA ~1-2 h for ~13k tapes; resumable: every read is cached in data/raw, rerun to continue.
                      --smoke DAY: one day of tapes only (e.g. 2025-11-15), ~5-15 min (event list + 1 day)
  reproduce           bash reproduce.sh: every number and figure in docs/NOTE.pdf (needs `data` first)
  engine [demo|books|live]
                      COURTSIDE engine, paper only. demo: vision calls -> paper decisions on a recorded book
                      (needs data/live, data/vision, models/); books: engine order books on the committed
                      sample; live: 60 s of live books, read-only. Default: demo if its inputs exist, else
                      books, then live.
  cv                  ball-tracking call engine on the held-out OpenTTGames clip (needs setup --full;
                      fetches BlurBall weights via scripts/get_models.sh and the clip with ffmpeg)
  dashboard [port]    status daemon + read-only dashboard at http://localhost:8765 (Ctrl-C stops both)
  money [args]        terminal replay of the v2 in-sample backtest with a running paper-money counter
                      (needs `data`; scripts/money_counter.py)
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
    "$PY" -m pytest -q tests engine/vision/tests "$@"
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
        --smoke) smoke=${2:-2025-11-15}; shift; [ $# -gt 0 ] && shift ;;
        --parallel) parallel=1; shift ;;
        *) echo "unknown data arg $1"; exit 2 ;;
      esac
    done
    if [ -n "$smoke" ]; then
      echo "smoke fetch: closed tennis events created on $smoke and their trade tapes (cached in data/raw)"
      "$PY" - "$smoke" <<'EOF'
import datetime as dt, sys, time
sys.path.insert(0, ".")
from src import polymarket as pm
from scripts.fetch_polymarket import MIN_VOL
d0 = sys.argv[1]
d1 = (dt.date.fromisoformat(d0) + dt.timedelta(days=1)).isoformat()
t = time.time()
ev = pm.enumerate_events("tennis", d0, d1)
s = ev[ev.series.isin(["atp", "wta", "challenger"]) & (ev.volume >= MIN_VOL)]
print(f"{len(ev)} tennis moneylines, {len(s)} singles >= ${MIN_VOL:,}; fetching their tapes", flush=True)
pm.fetch_many_trades(s.cond.tolist())
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
    else
      "$PY" scripts/fetch_polymarket.py
    fi
    echo "data done: $(ls data/raw/trades | wc -l) tapes in data/raw/trades"
    ;;

  reproduce)
    need_venv
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
    PY="$PY" bash scripts/get_models.sh
    if [ ! -f data/vision/test_2_copyts.mp4 ]; then
      command -v ffmpeg >/dev/null || { echo "cv needs ffmpeg to cut the held-out clip"; exit 1; }
      mkdir -p data/vision
      # OpenTTGames (Voeikov et al., CC BY-NC-SA 4.0): test_2 frames 2000-2999, held out from all training
      ffmpeg -loglevel error -ss 16.666667 -i https://lab.osai.ai/datasets/openttgames/data/test_2.mp4 \
             -frames:v 1000 -c copy -an -copyts data/vision/test_2_copyts.mp4
    fi
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
    "$PY" scripts/money_counter.py "$@"
    ;;

  help|-h|--help) usage ;;
  *) echo "unknown command: $cmd"; echo; usage; exit 2 ;;
esac
