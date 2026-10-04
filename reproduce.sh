#!/usr/bin/env bash
# Every number and figure in docs/NOTE.pdf (the LaTeX paper) and the docs, from cached public data (bash run.sh data first).
# On a fresh clone, step 1 builds the locked OOS prints and appends one line to results/oos_peeks.log:
# that line records your run, not ours. Re-running on an existing checkout appends nothing.
# Not run here (cached outputs are committed): scripts/rigor_pack.py (DSR, PBO, bootstrap; it rewrites
# research/rigor/RESULTS.md), HiPerGator tracking (hpg/), live order-book recordings (src/live_recorder.py).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-.venv/bin/python}
$PY run_all.py --oos            # H1-H6, calibration, tiers, fast tier (v1)               -> Table 3, Fig. 2a
$PY scripts/v2_causal.py        # v2 (causal window) on IS + burned OOS, slippage stress  -> Table 1
$PY scripts/v2_cost_stress.py   # v2 with fees / all costs doubled                        -> Table 1, Fig. 2b
$PY scripts/note_metrics.py     # ann. return, vol, turnover, skew, bps, holdout, gaps    -> Table 1, sections 3-4
$PY scripts/v2_figures.py       # results/figures (earlier note figure, kept for the deck)
$PY scripts/factor_regression.py
$PY scripts/leverage_stats.py
$PY scripts/paper_figures.py    # earlier figure set (results/paper/*.pdf; its loaders are shared with v2)
$PY scripts/build_paper.py      # the paper's figures (results/paper/v2, scripts/paper_figures_v2.py), numbers.json +
                                # LaTeX via tectonic -> docs/NOTE.pdf (+ NOTE.md); fails on > 5 main pages, < 11 pt
                                # text, margins, honesty grep; keeps the committed PDF (exit 0) if tectonic is missing
$PY scripts/build_docs.py       # README.md, docs/DEVPOST.md, docs/COMPLIANCE.md from results/paper/numbers.json
