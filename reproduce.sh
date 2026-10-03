#!/usr/bin/env bash
# Every number and figure in docs/NOTE.pdf, from cached public data (run scripts/fetch_polymarket.py first).
# On a fresh clone, step 1 builds the locked OOS prints and appends one line to results/oos_peeks.log:
# that line records your run, not ours. Re-running on an existing checkout appends nothing.
# Not run here (cached outputs are committed): scripts/rigor_pack.py (DSR, PBO, bootstrap; it rewrites
# research/rigor/RESULTS.md), HiPerGator tracking (hpg/), live order-book recordings (src/live_recorder.py).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-.venv/bin/python}
$PY run_all.py --oos            # H1-H6, calibration, tiers, fast tier (v1)               -> Table 1
$PY scripts/v2_causal.py        # v2 (causal window) on IS + burned OOS, slippage stress  -> Table 2
$PY scripts/v2_cost_stress.py   # v2 with fees / all costs doubled                        -> Table 2
$PY scripts/note_metrics.py     # ann. return, vol, turnover, skew, bps, holdout, gaps    -> Table 2, sections 2-3, 6
$PY scripts/v2_figures.py       # Fig. 1
$PY scripts/factor_regression.py
$PY scripts/leverage_stats.py
$PY scripts/make_pdf.py         # needs Chrome or Chromium; skipped (exit 0) if neither is installed
