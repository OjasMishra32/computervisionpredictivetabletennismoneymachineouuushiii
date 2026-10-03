"""One command for the U2 out-of-universe test of frozen v2 (research/v2/expand/PREREG.md).

    python scripts/expand_test.py

The implementation lives in research/v2/expand/expand_test.py (the pre-registration says the test is
run by a script in that folder); this entry point just runs it.
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "research/v2/expand/expand_test.py"), run_name="__main__")
