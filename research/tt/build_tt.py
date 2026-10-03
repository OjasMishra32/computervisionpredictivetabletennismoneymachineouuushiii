"""Fetch and prints for the table tennis study (the script HYPOTHESIS_TT.md names). No statistic.

    python research/tt/build_tt.py

Runs scripts/tt_fetch.py trades (tapes, resumable), then scripts/tt_build.py universe and prints.
The gamma completeness walk, the zero-volume check and the liquidity table are separate commands
(see research/tt/DATA.md).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import tt_build, tt_fetch  # noqa: E402

if __name__ == "__main__":
    tt_fetch.OUT.mkdir(parents=True, exist_ok=True)
    tt_fetch.trades()
    tt_build.write_universe()
    tt_build.prints()
