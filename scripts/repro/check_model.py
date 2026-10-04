"""Exit 1 unless models/vision/frozen_call_model.pkl matches the sha256 in results/provenance/inputs_manifest.json.

    python scripts/repro/check_model.py        # bash run.sh cv runs it before the engine loads the pickle
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.repro.common import INPUTS_MANIFEST, sha256_file  # noqa: E402

MODEL = "models/vision/frozen_call_model.pkl"


def main(root: Path = ROOT) -> int:
    want = {m["path"]: m["sha256"] for m in json.loads((root / INPUTS_MANIFEST).read_text())["groups"]["models"]}
    p = root / MODEL
    if not p.exists():
        print(f"{MODEL} is missing (git checkout -- {MODEL})", file=sys.stderr)
        return 1
    got = sha256_file(p)
    if got != want.get(MODEL):
        print(f"{MODEL}: sha256 {got[:12]}... differs from {INPUTS_MANIFEST} ({str(want.get(MODEL))[:12]}...)",
              file=sys.stderr)
        return 1
    print(f"{MODEL}: sha256 matches the input manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
