#!/usr/bin/env bash
# Every number and figure in docs/NOTE.pdf, from cached public data (run scripts/fetch_polymarket.py first).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-.venv/bin/python}
$PY run_all.py --oos            # H1-H6, calibration, tiers, fast tier (v1)
$PY scripts/v2_causal.py        # v2 (causal window) on IS + burned OOS, slippage stress
$PY scripts/v2_figures.py
$PY scripts/factor_regression.py
$PY scripts/leverage_stats.py
$PY scripts/make_pdf.py
