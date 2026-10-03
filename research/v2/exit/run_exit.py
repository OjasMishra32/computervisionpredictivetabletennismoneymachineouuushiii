"""One command for every number in research/v2/exit/RESULTS.md (IS only; ~15 min on 2 cores).

    .venv/bin/python research/v2/exit/run_exit.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from research.v2.exit import analyze_exit, diag_spread, placebo_exit, report_exit, sim_exit  # noqa: E402

if __name__ == "__main__":
    sim_exit.main(workers=2)   # data/v2_exit/{entries,maker,fallback}.parquet
    analyze_exit.main()        # results_full.json, tables/wf_*, tables/baseline_*
    placebo_exit.main()        # placebo.json, tables/placebo_nonfast_0_3s.csv
    diag_spread.main()         # tables/diag_spread_at_fill.csv
    report_exit.main()         # results.json, tables/comparison_all_variants.csv, figures/
