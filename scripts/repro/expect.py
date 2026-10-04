"""Fail a reproduction when a step recorded a skipped or failed part in its output instead of exiting nonzero.

    python scripts/repro/expect.py results/sponsors/evidence.json snowflake.recheck.status=ran

Each argument after the file is dotted.key=value; exit 1 (naming the key and the value found) on any mismatch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def get(obj, dotted: str):
    for part in dotted.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return "<missing>"
        obj = obj[part]
    return obj


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(argv[0])
    data = json.loads(path.read_text())
    bad = []
    for cond in argv[1:]:
        key, want = cond.split("=", 1)
        got = get(data, key)
        if str(got) != want:
            bad.append(f"{path}::{key} is {got!r}, expected {want!r}")
    for b in bad:
        print(f"expect: {b}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
