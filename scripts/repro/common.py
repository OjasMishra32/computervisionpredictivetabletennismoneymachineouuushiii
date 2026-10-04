"""Shared helpers for scripts/repro (standard library only, so they run before any optional dependency)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPRO = Path("results/repro")                      # run outputs (gitignored except what the authors commit)
INPUTS_MANIFEST = Path("results/provenance/inputs_manifest.json")
TAPES_TSV = Path("results/provenance/inputs_tapes.tsv.gz")
ARCHIVE = Path("results/repro/inputs")             # small public inputs committed with the code
COMMITTED = Path("results/paper/committed_artifacts.json")
# Append-only logs that reproduction runs must not grow: lines a reproduction appends are moved to
# results/repro/reads.log (the run's own record of every held-out re-read) and the committed log is restored.
PROTECTED_LOGS = (Path("results/oos_peeks.log"), Path("results/liquidity/oos_peeks_pending.txt"))
READS_LOG = REPRO / "reads.log"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj) -> None:
    """Atomic JSON write (a crash never leaves half a manifest)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=False) + "\n")
    os.replace(tmp, path)


def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def git_state(root: Path) -> dict:
    status = git(root, "status", "--porcelain", "--untracked-files=no")
    return {"git_head": git(root, "rev-parse", "HEAD") or "unknown", "dirty": bool(status),
            "dirty_files": status.splitlines()[:50]}
