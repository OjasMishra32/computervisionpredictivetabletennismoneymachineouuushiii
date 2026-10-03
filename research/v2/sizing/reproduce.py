"""One command for the whole sizing lens (IS only; ~6 min on 2 processes).

    .venv/bin/python research/v2/sizing/reproduce.py

Steps: features.py -> explore.py -> mech_check.py -> allbucket_check.py -> walkforward.py -> report.py
"""
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for step in ("features", "explore", "mech_check", "allbucket_check", "walkforward", "report"):
    print(f"\n######## {step}.py", flush=True)
    runpy.run_path(str(HERE / f"{step}.py"), run_name="__main__")
