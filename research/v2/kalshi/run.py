"""Run the whole Kalshi lens in order (from the repo root):

    .venv/bin/python research/v2/kalshi/run.py            # everything (network steps are cached)
    .venv/bin/python research/v2/kalshi/run.py --offline  # skip k01-k03 (needs data/v2_kalshi already filled)
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["k01_enumerate.py", "k02_match.py", "k03_fetch.py",  # network (cached under data/v2_kalshi)
         "k04_leadlag.py", "k05_signals.py", "k06_backtest.py", "k08_maker.py", "k09_report.py"]

if __name__ == "__main__":
    steps = STEPS[3:] if "--offline" in sys.argv else STEPS
    for s in steps:
        print(f"=== {s}", flush=True)
        subprocess.run([sys.executable, "-W", "ignore", str(HERE / s)], check=True)
