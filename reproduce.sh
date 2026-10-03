#!/usr/bin/env bash
# Every number and figure in docs/NOTE.pdf, from cached public data (run scripts/fetch_polymarket.py first).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-.venv/bin/python}
$PY run_all.py --oos
$PY scripts/v2_figures.py
$PY scripts/leverage_stats.py
$PY scripts/make_pdf.py
