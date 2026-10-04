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

Judge quick path (~10 min, no data download, no keys):  setup, replay, redteam, tests
Reproduce the submitted snapshot (~2-3 h, no keys):      all  (= setup, data, reproduce)
Fresh, mutable API fetch (a NEW evaluation, not ours):   fresh-fetch

  all                 setup + data (public crawl) + reproduce: every recomputed result, figure, the paper and
                      the docs from the verified inputs                                         ~2-3 h
  setup [--locked] [--full]
                      make .venv; pip install -r requirements-repro.txt (requirements.txt + duckdb, paramiko,
                      tabulate, opencv for reproduce)                                            ~1-2 min
                      --locked installs the exact versions in requirements.lock instead
                      --full also installs requirements-extra.txt (vision, deck: torch, onnxruntime...)
                      Paper compiler: uses tectonic from PATH, or TECTONIC=/path/to/tectonic (linked into
                      .venv/bin); INSTALL_TECTONIC=1 downloads the official tectonic 0.17.0 release binary
                      from GitHub into .venv/bin. Warns on a Python other than 3.14 (the lock's).
  verify-inputs       check data/ against results/provenance/inputs_manifest.json (universe, 80/20 split, OOS
                      start, sha256 of every tape, archived inputs, frozen call model); exit 0 = the snapshot  ~1 min
  tests               unit tests (pytest: tests/, engine/vision/tests/)          ~2-7 min (393 s on a loaded laptop)
  replay              10 min of recorded live Polymarket books (tests/fixtures/live_sample.jsonl.gz)
                      through the live paper trader and the engine's order books  ~15 s, no network
                      (like every replay it appends one line to results/oos_peeks.log; git checkout undoes it)
  live [args]         the paper trader on live public Polymarket data, read-only, until Ctrl-C (a tool:
                      scripts/live_paper.py --test; the pre-registered live session was stopped by a team decision
                      and is not used, DEVIATIONS_LIVE.md L15). Quoting starts after a warm-up of 50 public trades,
                      so on a quiet tape it can quote nothing for a while; --minutes N counts from the start of
                      quoting, not from launch (use Ctrl-C to stop earlier)
  data [--smoke DAY] [--parallel]
                      public Polymarket crawl into data/ (scripts/fetch_polymarket.py), no keys.
                      ETA ~1-2 h for ~13k tapes; resumable: every read is cached in data/raw, rerun to continue.
                      --smoke DAY: event list + tapes of the matches starting on DAY (default 2026-01-15, 38 in-sample matches), ~1-3 min
                      Both pin the event list to the paper's 13,084 matches (scripts/freeze_universe.py,
                      results/universe_conds.txt.gz): a later crawl also returns matches resolved after ours.
                      The full crawl ends with verify-inputs (a report; reproduce enforces it)
  reproduce           bash reproduce.sh: reproduce the SUBMITTED SNAPSHOT, offline. Checks the inputs against
                      the manifest (stops on a universe/split mismatch or tape drift; ALLOW_INPUT_DRIFT=1 runs
                      anyway and labels the run), reruns every step from the prints up (incl. the fresh holdout
                      on its archived inputs), rebuilds results/paper/numbers.json, docs/NOTE.pdf and the docs,
                      and writes results/repro/run_manifest.json. Fails on the first error. Paper sources it does
                      not recompute are listed with reasons in results/paper/committed_artifacts.json
                      (needs the full `data` crawl first)                                          ~1-1.5 h
  fresh-fetch         a NEW fresh holdout: today's public listing under the same window rule and frozen code,
                      fetched now (network), into results/fresh_holdout_new/<utc>/; the submitted
                      results/fresh_holdout/ is not touched. A new fetch is a new evaluation, not ours ~5 min
  docs [--check]      README.md, docs/DEVPOST.md, docs/COMPLIANCE.md from docs/templates/,
                      results/paper/numbers.json and the paper's label map (docs/paper/note.aux, or
                      results/paper/labels.json on a clone); writes nothing if a placeholder does not resolve;
                      --check: exit 1 if stale                                                   ~1 s
  engine [demo|books|live]
                      COURTSIDE engine, paper only. demo: vision calls -> paper decisions on a recorded book
                      (needs data/live, data/vision, models/); books: engine order books on the committed
                      sample; live: 60 s of live books, read-only. Default: demo if its inputs exist, else
                      books, then live.
  cv                  ball-tracking call engine on the held-out OpenTTGames clip (needs setup --full;
                      fetches BlurBall weights via scripts/get_models.sh and the clip with ffmpeg). The point-end
                      calls use models/vision/frozen_call_model.pkl (12 MB, committed; rebuilt on HiPerGator by
                      sbatch hpg/engine_vision.sbatch); cv stops if it is missing or its sha256 differs from the
                      input manifest (ALLOW_NO_CALL_MODEL=1: detect and track with calls disabled)
  dashboard [port]    status daemon + read-only dashboard at http://localhost:8765 (Ctrl-C stops both)
  money [args]        terminal replay of the v2 in-sample backtest with a running paper-money counter
                      (needs `data` then `reproduce`: reads data/v2_trades_is_oos.parquet; scripts/money_counter.py)
  redteam             the checks we ran against ourselves (results/redteam/): stamp-lag robustness, every
                      derived Q&A number from its results file, claim/acceptance checks on the public text.
                      No network, no held-out read, nothing re-simulated. Expected: 0 FAIL; KNOWN = a gap in the
                      final video (not re-rendered); NOT RUN = the forward test (HYPOTHESIS_V2.md A5)   ~10 s
  preflight           read-only readiness check (owner use, macOS; the forward test was not run, A5):
                      clock, disk, swap, power, heavy jobs, pinned forward code unmodified, forward outputs,
                      v2-safe plan, docs up to date, untracked results, local commits not yet pushed
EOF
}

need_venv() {
  [ -x "$PY" ] || { echo "no $PY: run 'bash run.sh setup' first (or set PY=/path/to/python)"; exit 1; }
}

TECTONIC_VERSION=0.17.0
ensure_tectonic() {   # the paper compiler: PATH, then $TECTONIC, then (opt-in) the official release binary
  local exe="" plat url tmp
  if [ -x .venv/bin/tectonic ]; then exe=.venv/bin/tectonic
  elif command -v tectonic >/dev/null; then exe=$(command -v tectonic)
  elif [ -n "${TECTONIC:-}" ] && [ -x "$TECTONIC" ]; then ln -sf "$TECTONIC" .venv/bin/tectonic; exe=.venv/bin/tectonic
  elif [ "${INSTALL_TECTONIC:-0}" = 1 ]; then
    case "$(uname -s)-$(uname -m)" in
      Darwin-arm64) plat=aarch64-apple-darwin ;;
      Darwin-x86_64) plat=x86_64-apple-darwin ;;
      Linux-x86_64) plat=x86_64-unknown-linux-musl ;;
      *) echo "setup: no tectonic release binary for $(uname -s)-$(uname -m); install tectonic $TECTONIC_VERSION yourself"; return 1 ;;
    esac
    url="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40$TECTONIC_VERSION/tectonic-$TECTONIC_VERSION-$plat.tar.gz"
    tmp=$(mktemp -d)
    echo "setup: downloading tectonic $TECTONIC_VERSION ($plat) from the official GitHub release"
    curl -fsSL -o "$tmp/t.tgz" "$url"
    .venv/bin/python -c "import hashlib,sys; print('setup: tectonic tarball sha256', hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$tmp/t.tgz"
    tar -xzf "$tmp/t.tgz" -C .venv/bin tectonic
    rm -rf "$tmp"
    exe=.venv/bin/tectonic
  fi
  if [ -z "$exe" ]; then
    echo "setup: WARNING no tectonic found. replay/redteam/tests do not need it; reproduce (docs/NOTE.pdf) does."
    echo "       install tectonic $TECTONIC_VERSION (macOS: brew install tectonic; conda: conda install -c conda-forge tectonic),"
    echo "       or rerun with TECTONIC=/path/to/tectonic or INSTALL_TECTONIC=1 bash run.sh setup"
    return 0
  fi
  echo "setup: paper compiler $("$exe" --version 2>/dev/null | head -1) ($exe; the paper was built with $TECTONIC_VERSION)"
}

cmd=${1:-help}
[ $# -gt 0 ] && shift

case "$cmd" in
  all)
    bash "$HERE/run.sh" setup
    bash "$HERE/run.sh" data
    bash "$HERE/run.sh" reproduce "$@"
    ;;

  verify-inputs)
    need_venv
    "$PY" scripts/repro/manifest.py verify "$@"
    ;;

  fresh-fetch)
    need_venv
    echo "fresh-fetch: a NEW holdout fetched now from the public Polymarket APIs (network, no keys); it is a new"
    echo "evaluation with a new fetch time, written to results/fresh_holdout_new/<utc>/, not the submitted one."
    "$PY" scripts/repro/holdout_inputs.py new-fetch
    ;;

  docs)
    need_venv
    "$PY" scripts/build_docs.py "$@"
    ;;

  setup)
    locked="" full=""
    for a in "$@"; do
      case "$a" in
        --locked) locked=1 ;;
        --full) full=1 ;;
        *) echo "unknown setup arg $a"; exit 2 ;;
      esac
    done
    [ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
    .venv/bin/python -m pip install -q --upgrade pip
    if [ -n "$locked" ]; then .venv/bin/python -m pip install -r requirements.lock
    else .venv/bin/python -m pip install -r requirements-repro.txt; fi
    if [ -n "$full" ]; then .venv/bin/python -m pip install -r requirements-extra.txt; fi
    .venv/bin/python -c "import numpy, pandas, pyarrow, scipy, websockets, duckdb, cv2; print('setup ok:', __import__('sys').version.split()[0])"
    .venv/bin/python -c "import sys; v = sys.version_info[:2]; v == (3, 14) or print(f'setup: WARNING Python {v[0]}.{v[1]}; requirements.lock was made on 3.14.0 (the run manifest records the version)')"
    ensure_tectonic
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
      "$PY" scripts/freeze_universe.py
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
    mkdir -p data/raw/trades   # the progress meter counts files here (under pipefail a missing dir ended it)
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
    "$PY" scripts/freeze_universe.py   # event list first (cached), pinned to the paper's 13,084 matches
    progress & PROG=$!
    trap 'kill $PROG 2>/dev/null || true' EXIT
    if [ -n "$parallel" ]; then
      "$PY" -c "import sys; sys.path.insert(0,'.'); from src import polymarket as pm; from scripts.fetch_polymarket import SINCE, UNTIL; pm.enumerate_events('tennis', SINCE, UNTIL)"
      "$PY" scripts/fetch_reverse.py & R1=$!
      "$PY" scripts/fetch_middle.py & R2=$!
      "$PY" scripts/fetch_polymarket.py
      wait "$R1" || { echo "data: scripts/fetch_reverse.py failed"; exit 1; }   # each crawler's own exit status
      wait "$R2" || { echo "data: scripts/fetch_middle.py failed"; exit 1; }
    else   # Gamma rate-limits long crawls ("RuntimeError: GET failed"); every finished read stays cached
      for attempt in 1 2 3 4; do
        "$PY" scripts/fetch_polymarket.py && break
        [ "$attempt" = 4 ] && { echo "data: fetch failed 4 times; rerun 'bash run.sh data' to resume"; exit 1; }
        echo "data: fetch stopped (attempt $attempt); resuming from the cache in 60 s"; sleep 60
      done
    fi
    echo "data done: $(ls data/raw/trades | wc -l) tapes in data/raw/trades; checking them against the submitted snapshot"
    "$PY" scripts/repro/manifest.py verify --allow-drift
    ;;

  reproduce)
    need_venv
    if ! ls data/raw/events_tennis_*.parquet >/dev/null 2>&1; then
      echo "reproduce needs the full public crawl first: bash run.sh data (~1-2 h, resumable)."
      exit 1
    fi
    PY="$PY" bash reproduce.sh "$@"   # its first steps check every input against the manifest
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
      echo "models/vision/frozen_call_model.pkl (committed) is missing: git checkout -- models/vision/frozen_call_model.pkl"
      echo "(sbatch hpg/engine_vision.sbatch rebuilds it on HiPerGator). ALLOW_NO_CALL_MODEL=1 runs detection and"
      echo "tracking with point-end calls disabled."
      [ "${ALLOW_NO_CALL_MODEL:-0}" = 1 ] || exit 1
    else
      "$PY" scripts/repro/check_model.py
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

  redteam)
    need_venv
    "$PY" scripts/redteam_stamp_lag.py >/dev/null   # under set -e a failure stops here (no `&&` that hides it)
    echo "wrote results/redteam/stamp_lag.json"
    "$PY" scripts/redteam_derived.py >/dev/null
    echo "wrote results/redteam/derived.json"
    "$PY" scripts/redteam_acceptance.py "$@"
    ;;

  preflight)
    need_venv
    ok() { printf '  ok    %s\n' "$1"; }
    bad() { printf '  CHECK %s\n' "$1"; }
    now=$(date -u +%H:%M); echo "preflight at $now UTC (forward test not run: HYPOTHESIS_V2.md A5; hard stop 15:00 UTC)"
    free_g=$(df -g . | awk 'NR==2 {print $4}')
    [ "${free_g:-0}" -ge 15 ] && ok "disk: ${free_g} GB free" || bad "disk: ${free_g} GB free (< 15 GB; the forward run loads ~12 GB of prints; gzip data/live/*.jsonl first)"
    if command -v sysctl >/dev/null && sysctl -n vm.swapusage >/dev/null 2>&1; then
      echo "  info  swap: $(sysctl -n vm.swapusage)"
    fi
    if command -v pmset >/dev/null; then
      pmset -g batt | grep -q "AC Power" && ok "power: on AC" || bad "power: on battery (plug in; keep the lid open)"
      pgrep -x caffeinate >/dev/null && ok "caffeinate running" || bad "no caffeinate (nohup caffeinate -dims -w <live_paper pid> &)"
    fi
    lp=$(pgrep -f "scripts/live_paper.py" | head -1 || true)
    [ -z "$lp" ] && ok "no live paper session (stopped by team decision, DEVIATIONS_LIVE.md L15)" || echo "  info  a live_paper.py process is running (pid $lp); its results are not used"
    pgrep -f "src.live_recorder" >/dev/null && ok "live recorder running" || echo "  info  live recorder not running"
    heavy=$(pgrep -fl "make_video|e2e_run|engine.webrtc|capacity_study|cv_showcase|ffmpeg|latexmk|tier0_latency_sweep" | cut -c1-90 || true)
    [ -z "$heavy" ] && ok "no heavy jobs running" || { bad "heavy jobs running (stop them 11:25-11:50 UTC):"; echo "$heavy" | sed 's/^/          /'; }
    pinned="scripts/forward_test.py scripts/tier0_v3_forward.py src/v2.py src/tiers.py src/fasttier.py src/tape.py src/polymarket.py research/v2/sizing/engine.py"
    # shellcheck disable=SC2086
    [ -z "$(git status --porcelain -- $pinned)" ] && ok "pinned forward pipeline unmodified vs HEAD" || bad "pinned forward files modified: $(git status --porcelain -- $pinned | tr '\n' ' ')"
    [ -f results/v2/forward.json ] && echo "  info  results/v2/forward.json exists (forward test already ran)" || ok "results/v2/forward.json absent (forward test not run: HYPOTHESIS_V2.md A5)"
    [ -f results/tier0_v3/forward/results.json ] && echo "  info  tier-0 v3 forward result exists" || ok "tier-0 v3 forward result absent (not run: A5)"
    "$PY" scripts/forward_test_safe.py --plan | "$PY" -c "import json,sys; d=json.load(sys.stdin); print('  info  v2-safe (C9) ready for its one run:', d['real_run_ready'], '|', '; '.join(d['problems']) or 'no problems')"
    "$PY" scripts/build_docs.py --check >/dev/null 2>&1 && ok "README/DEVPOST/COMPLIANCE up to date with numbers.json" || bad "docs stale or a docs check failed: bash run.sh docs"
    unt=$(git status --porcelain --untracked-files=all -- results/live results/e2e results/capacity results/redteam results/v2 2>/dev/null | wc -l | tr -d ' ')
    echo "  info  $unt uncommitted file(s) under results/{live,e2e,capacity,redteam,v2} (commit when their owners finish; never data/ or models/)"
    ahead=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "?")
    echo "  info  local commits not on origin/main (last fetched): $ahead (push before 15:00 UTC; CLEAN_CLONE N13)"
    ;;

  help|-h|--help) usage ;;
  *) echo "unknown command: $cmd"; echo; usage; exit 2 ;;
esac
