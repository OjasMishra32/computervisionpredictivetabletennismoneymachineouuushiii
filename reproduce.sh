#!/usr/bin/env bash
# Reproduce the submitted snapshot: every recomputed result, figure, results/paper/numbers.json, docs/NOTE.pdf and the
# docs, from the verified public inputs (bash run.sh data first), offline, failing on the first error.
#
#   bash run.sh reproduce          (or: bash reproduce.sh)            ~1-1.5 h on a laptop after `run.sh data`
#
# - s00 checks the inputs against results/provenance/inputs_manifest.json (universe, 80/20 split, OOS start, every
#   tape's sha256, the frozen call model). A universe/split/model mismatch stops the run. Tape drift (a later crawl
#   returning different trades) stops it too, unless ALLOW_INPUT_DRIFT=1, which labels the run "not the submitted
#   snapshot" in results/repro/run_manifest.json.
# - Each step runs through scripts/repro/run_step.py: its log goes to results/repro/logs/<id>.log, a nonzero exit
#   stops the run, and every declared --out must be rewritten by the step (a skipped computation cannot pass).
# - Python processes run with COURTSIDE_OFFLINE=1 (scripts/repro/offline/sitecustomize.py): no mutable API is
#   refetched. The fresh holdout is rerun on its archived inputs; `bash run.sh fresh-fetch` is the separate,
#   mutable path that fetches a NEW holdout.
# - Held-out re-reads of already-frozen evaluations go to results/repro/reads.log; results/oos_peeks.log (the
#   authors' record) is left unchanged.
# - The last steps check that every source file of results/paper/numbers.json was rewritten by this run or is a
#   listed committed artifact with an unchanged sha256 (results/paper/committed_artifacts.json lists each one with
#   its producer and why it is not recomputed: HiPerGator jobs, recorded live books, blind tests evaluated once),
#   and write results/repro/run_manifest.json.
# - Proving the numbers match the paper is a separate comparison against a reference captured outside the checkout:
#   scripts/check_paper_reproduction.py --reference <file> (README, "Reproduction").
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-.venv/bin/python}
export COURTSIDE_STRICT=1 COURTSIDE_REPRO=1 COURTSIDE_OFFLINE=1
export PYTHONPATH="$PWD/scripts/repro/offline${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$PWD/.venv/bin:$PATH"                  # bash run.sh setup links a tectonic here when it has to
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct 2>/dev/null || date +%s)}

if [ "${FRESH:-0}" = 1 ]; then
  echo "reproduce.sh reproduces the submitted snapshot, so it never refetches the fresh holdout (a refetch is a new"
  echo "holdout). Run the mutable fetch on its own: bash run.sh fresh-fetch"
  exit 2
fi
command -v tectonic >/dev/null || { echo "reproduce: no tectonic on PATH (needed for docs/NOTE.pdf): bash run.sh setup"; exit 2; }
$PY -c "import duckdb, cv2" 2>/dev/null || { echo "reproduce: duckdb / opencv missing: bash run.sh setup (requirements-repro.txt)"; exit 2; }

step() { $PY scripts/repro/run_step.py "$@"; }
$PY scripts/repro/run_manifest.py start
trap 'rc=$?; set +e; if [ $rc -ne 0 ]; then $PY scripts/repro/run_manifest.py finish --status failed >/dev/null 2>&1; fi; exit $rc' EXIT

# ---- s00 inputs
step s00_universe -- $PY scripts/freeze_universe.py --check   # the event list holds the paper's 13,084 matches
step s00_inputs -- $PY scripts/repro/manifest.py verify ${ALLOW_INPUT_DRIFT:+--allow-drift}
step s00_archived -- $PY scripts/repro/holdout_inputs.py restore      # fresh-holdout window, factor files

# ---- s01 prints and v1 (H1-H6, calibration, tiers, fast tier); first step that re-reads the OOS prints
step s01_run_all --out results/summary.json -- $PY run_all.py --oos
# ---- s02 private caches the later steps read (IS jumps, lowloss feature tables); before every consumer
step s02_inputs -- $PY scripts/reproduce_inputs.py

# ---- s03 v2 economics: frozen T3e event study (fast tier's own fills), cost stress, note metrics
step s03_v2_causal --out results/v2/causal.json -- $PY scripts/v2_causal.py
step s03_v2_cost --out results/v2/cost_stress.json -- $PY scripts/v2_cost_stress.py
step s03_note_metrics --out results/v2/note_metrics.json -- $PY scripts/note_metrics.py
# ---- corrected headline producers (executable v2 copier timing, causal camera policy cells) are added here, each
# ---- with --out for every file the paper cites; scripts/repro/artifacts.py check fails the run otherwise.

# ---- s04 descriptive tables and figures
step s04_v2_figures -- $PY scripts/v2_figures.py
step s04_factors --out results/v2/factor_regression.json -- $PY scripts/factor_regression.py
step s04_leverage --out results/leverage_stats.json -- $PY scripts/leverage_stats.py
step s04_paper_figures -- $PY scripts/paper_figures.py
step s04_rally_gate --out results/engine/rally_gate_eval.json -- $PY scripts/rally_gate_eval.py
step s04_coverage --out results/data_coverage.json -- $PY scripts/data_coverage.py

# ---- s05 risk and capacity
step s05_wallet_cap_is --out results/v2/risk/wallet_cap_is.json -- $PY scripts/v2_wallet_cap.py --is
step s05_wallet_cap_oos --out results/v2/risk/wallet_cap.json --out results/v2/risk/per_match_loss.json \
  -- $PY scripts/v2_wallet_cap.py --oos --repro
step s05_impact --out results/liquidity/impact.json --skip-unless data/live/market_20261003_1003.jsonl.gz \
  --skip-reason "the live order-book recordings are not distributed" -- $PY scripts/impact_model.py
step s05_persistence --out results/economics/persistence.json -- $PY scripts/edge_persistence.py

# ---- s06 performance statistics: PSR / MinTRL and the copier fill stress; CV cost and turnover per cell
step s06_psr --out results/rigor/psr.json -- $PY scripts/psr_mintrl.py
step s06_cv_cost --out results/tier0/cost_turnover.json -- $PY scripts/cv_cost_turnover.py

# ---- s07 sponsor evidence (fails unless the SQL recheck and the Vultr unit tests ran), vision teaser
step s07_sponsors --out results/sponsors/evidence.json -- $PY scripts/sponsor_evidence.py
step s07_sponsors_parts -- $PY scripts/repro/expect.py results/sponsors/evidence.json snowflake.recheck.status=ran \
  vultr.tests.returncode=0
step s07_cv_teaser --out results/cv_teaser/teaser_numbers.json -- $PY scripts/cv_teaser_fig.py

# ---- s08 fresh holdout: the completed evaluation, rerun on its archived inputs with the network disabled
step s08_fresh_holdout --out results/fresh_holdout/results.json --out results/fresh_holdout/seed_daily_paths.csv \
  -- $PY scripts/repro/holdout_inputs.py run-fixed
step s08_firm_fig --out results/scenario/fig_firm_05s_numbers.json -- $PY scripts/firm_scenario_fig.py

# ---- s09 red-team numbers the paper cites (no held-out read)
step s09_stamp_lag --out results/redteam/stamp_lag.json -- $PY scripts/redteam_stamp_lag.py
step s09_derived --out results/redteam/derived.json -- $PY scripts/redteam_derived.py

# ---- s10 paper and docs (build_paper.py fails on a missing compiler or a failed check and never keeps an old PDF)
step s10_paper --out results/paper/numbers.json --out results/paper/policy.json --out results/paper/variants.json \
  --out docs/NOTE.pdf -- $PY scripts/build_paper.py
step s10_docs -- $PY scripts/build_docs.py

# ---- s11 every paper source recomputed here or a listed committed artifact; run manifest
$PY scripts/repro/run_manifest.py finish --status ok >/dev/null
step s11_artifacts -- $PY scripts/repro/artifacts.py check
trap - EXIT
$PY scripts/repro/run_manifest.py finish --status ok
