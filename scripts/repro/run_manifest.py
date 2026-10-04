"""results/repro/run_manifest.json: what one reproduce.sh run did, on which code and inputs.

    python scripts/repro/run_manifest.py start            # first thing reproduce.sh does (clears the previous run's log)
    python scripts/repro/run_manifest.py finish --status ok|failed

The manifest records the git commit (and whether the tree was dirty), Python and platform, the tectonic version, the
input manifest's sha256 and the input check (results/repro/input_drift.json), every step with its command, exit
code, seconds, declared outputs (sha256) and the other files it wrote, skipped steps with their reason, and the
held-out re-reads the run made (results/repro/reads.log). It is evidence that steps ran, not proof that their
numbers are right: compare them with scripts/check_paper_reproduction.py against a reference captured elsewhere.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.repro.common import INPUTS_MANIFEST, READS_LOG, REPRO, git_state, sha256_file, utc_now, write_json  # noqa: E402

SCHEMA = "courtside.repro.run/1"
RUN = REPRO / "run_manifest.json"


def tectonic_version() -> str | None:
    exe = shutil.which("tectonic")
    if not exe:
        return None
    try:
        return subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def pip_freeze() -> list[str]:
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], capture_output=True, text=True,
                           timeout=120)
        return r.stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []


def start(root: Path = ROOT) -> dict:
    rd = root / REPRO
    rd.mkdir(parents=True, exist_ok=True)
    prev = rd / "prev"
    for name in ("steps.jsonl", "reads.log", "run_manifest.json", "artifact_check.json"):
        f = rd / name
        if f.exists():
            prev.mkdir(exist_ok=True)
            os.replace(f, prev / name)
    if (rd / "logs").exists():
        shutil.rmtree(rd / "logs")
    gs = git_state(root)
    man = {
        "schema": SCHEMA, "status": "running", "run_id": f"{utc_now()}-{gs['git_head'][:8]}",
        **gs, "started_utc": utc_now(), "finished_utc": None,
        "mode": "snapshot reproduction (fixed inputs, offline)",
        "python": platform.python_version(), "platform": platform.platform(), "tectonic": tectonic_version(),
        "pip_freeze": pip_freeze(),
        "env": {k: os.environ.get(k) for k in ("COURTSIDE_STRICT", "COURTSIDE_REPRO", "COURTSIDE_OFFLINE",
                                               "ALLOW_INPUT_DRIFT", "SOURCE_DATE_EPOCH")},
        "inputs_manifest": str(INPUTS_MANIFEST),
        "inputs_manifest_sha256": sha256_file(root / INPUTS_MANIFEST) if (root / INPUTS_MANIFEST).exists() else None,
    }
    write_json(root / RUN, man)
    return man


def finish(status: str, root: Path = ROOT) -> dict:
    man = json.loads((root / RUN).read_text()) if (root / RUN).exists() else {"schema": SCHEMA}
    steps = []
    f = root / REPRO / "steps.jsonl"
    if f.exists():
        steps = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    outputs = {}
    for s in steps:
        for o in s.get("outputs", []):
            outputs[o["path"]] = {"sha256": o["sha256"], "bytes": o["bytes"], "step": s["id"], "declared": True}
        for p in s.get("new_files", []):
            if p not in outputs and (root / p).is_file():
                outputs[p] = {"sha256": sha256_file(root / p), "bytes": (root / p).stat().st_size, "step": s["id"],
                              "declared": False}
    drift = {}
    df = root / REPRO / "input_drift.json"
    if df.exists():
        d = json.loads(df.read_text())
        drift = {"snapshot_inputs": d.get("snapshot_inputs"), "fatal": d.get("fatal"),
                 "drift_groups": sorted(d.get("drift", {})), "tapes": d.get("tapes"),
                 "list": str(REPRO / "input_drift.json")}
    reads = (root / READS_LOG).read_text().splitlines() if (root / READS_LOG).exists() else []
    failed = [s["id"] for s in steps if s.get("exit", 0) != 0]
    man.update({
        "status": status if not failed else "failed", "finished_utc": utc_now(),
        "input_check": drift,
        "inputs_are_submitted_snapshot": bool(drift.get("snapshot_inputs")),
        "steps": [{k: s.get(k) for k in ("id", "cmd", "exit", "seconds", "declared_outputs", "stale_outputs",
                                          "reads_moved", "log")} for s in steps if not s.get("skipped")],
        "skipped": [{"id": s["id"], "reason": s.get("reason")} for s in steps if s.get("skipped")],
        "failed_steps": failed,
        "heldout_rereads": {"n_lines": len(reads), "log": str(READS_LOG),
                            "note": "re-reads of already-frozen evaluations by this reproduction; the committed "
                                    "results/oos_peeks.log is left unchanged"},
        "outputs": dict(sorted(outputs.items())),
        "total_seconds": round(sum(float(s.get("seconds") or 0) for s in steps), 1),
    })
    write_json(root / RUN, man)
    print(f"run manifest: {man['status']}, {len(man['steps'])} steps ran, {len(man['skipped'])} skipped, "
          f"{len(outputs)} files written, {man['total_seconds']:.0f} s -> {RUN}")
    return man


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["start", "finish"])
    ap.add_argument("--status", default="ok", choices=["ok", "failed"])
    a = ap.parse_args(argv)
    if a.cmd == "start":
        start()
        return 0
    man = finish(a.status)
    return 0 if man["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
