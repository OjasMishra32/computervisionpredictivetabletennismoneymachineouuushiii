"""Capture an approved paper reference, or check a completed clean reproduction.

python scripts/check_paper_reproduction.py --capture /tmp/courtside-reference.json
python scripts/check_paper_reproduction.py --reference /tmp/courtside-reference.json --report /tmp/courtside-check.json

Capture before running the pipeline. Keep the reference outside the reproduction
checkout so rebuilding results cannot replace the expected answers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reproduction_contract import capture, verify


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture", type=Path)
    mode.add_argument("--reference", type=Path)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--report", type=Path)
    ap.add_argument("--atol", type=float, default=1e-8)
    ap.add_argument("--rtol", type=float, default=1e-10)
    a = ap.parse_args(argv)
    root = a.root.resolve()
    try:
        if a.capture:
            contract = capture(root)
            a.capture.parent.mkdir(parents=True, exist_ok=True)
            # Refuse to replace an existing reference with newly generated answers.
            with a.capture.open("x") as f:
                json.dump(contract, f, indent=2, allow_nan=False)
                f.write("\n")
            print(f"Captured {len(contract['paper_values'])} paper values in {a.capture}")
            return 0
        reference = json.loads(a.reference.read_text())
        result = verify(reference, root, a.atol, a.rtol)
        if a.report:
            a.report.parent.mkdir(parents=True, exist_ok=True)
            a.report.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if result["ok"] else 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Reproduction check failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
