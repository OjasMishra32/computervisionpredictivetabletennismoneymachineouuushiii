"""Run one reproduce.sh step, log it, and fail loudly.

    python scripts/repro/run_step.py <id> [--out PATH]... [--skip-unless PATH --skip-reason TEXT] -- <command...>

- The command's stdout/stderr go to the console and to results/repro/logs/<id>.log.
- A nonzero exit fails the step (the step's exit code is returned; reproduce.sh stops under `set -e`).
- Every --out must exist and have been rewritten during the step, otherwise exit 4: a step that silently skipped its
  work (a cache hit, a swallowed error) cannot pass as a recomputation.
- --skip-unless PATH: when PATH is absent the step is NOT run and is recorded as skipped with --skip-reason; its
  --out files then have to be listed in results/paper/committed_artifacts.json (scripts/repro/artifacts.py check).
- Lines the command appends to results/oos_peeks.log (or results/liquidity/oos_peeks_pending.txt) are moved to
  results/repro/reads.log, prefixed with the step id, and the committed log is restored byte for byte: a
  reproduction re-reads frozen evaluations, it does not add held-out reads to the authors' record.
- One JSON line per step goes to results/repro/steps.jsonl (read by scripts/repro/run_manifest.py).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.repro.common import PROTECTED_LOGS, READS_LOG, REPRO, sha256_file, utc_now  # noqa: E402

WATCH_DIRS = ("results", "docs", "data/derived", "data/v2_lowloss", "data/fresh")


def new_files(root: Path, since: float) -> list[str]:
    out = []
    for d in WATCH_DIRS:
        base = root / d
        if not base.exists():
            continue
        for dirpath, dirnames, files in os.walk(base):
            if Path(dirpath).resolve() == (root / REPRO).resolve():
                dirnames[:] = []
                continue
            for f in files:
                p = Path(dirpath) / f
                try:
                    if p.stat().st_mtime >= since:
                        out.append(str(p.relative_to(root)))
                except OSError:
                    pass
    return sorted(out)


def snapshot_logs(root: Path) -> dict:
    return {str(p): (root / p).read_bytes() if (root / p).exists() else None for p in PROTECTED_LOGS}


def restore_logs(root: Path, before: dict, step_id: str) -> int:
    """Move appended lines to results/repro/reads.log and restore the committed logs. Returns lines moved."""
    moved = 0
    for rel, old in before.items():
        p = root / rel
        now = p.read_bytes() if p.exists() else None
        if now == old:
            continue
        if old is not None and now is not None and now.startswith(old):
            extra = now[len(old):].decode(errors="replace").splitlines()
        elif old is None and now is not None:
            extra = now.decode(errors="replace").splitlines()
        else:   # rewritten, not appended: never silently accept a rewrite of the authors' record
            extra = [f"!! {rel} was rewritten (not appended) by this step; restored"]
        (root / READS_LOG).parent.mkdir(parents=True, exist_ok=True)
        with open(root / READS_LOG, "a") as fh:
            for line in extra:
                fh.write(f"{step_id}\t{rel}\t{line}\n")
        moved += len(extra)
        if old is None:
            p.unlink()
        else:
            p.write_bytes(old)
    return moved


def record(root: Path, rec: dict) -> None:
    f = root / REPRO / "steps.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def run(step_id: str, cmd: list[str], outs: list[str], skip_unless: str | None, skip_reason: str,
        root: Path = ROOT) -> int:
    rec = {"id": step_id, "cmd": " ".join(cmd), "started_utc": utc_now(), "declared_outputs": outs}
    if skip_unless and not (root / skip_unless).exists():
        rec.update({"skipped": True, "reason": f"{skip_unless} absent: {skip_reason}", "exit": 0, "seconds": 0.0,
                    "outputs": [], "new_files": [], "reads_moved": 0})
        record(root, rec)
        print(f"[repro] {step_id}: SKIPPED ({rec['reason']}); its outputs must be listed committed artifacts",
              flush=True)
        return 0
    log = root / REPRO / "logs" / f"{step_id}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    before = snapshot_logs(root)
    t0 = time.time()
    since = t0 - 1.0                              # coarse filesystem mtimes
    print(f"[repro] {step_id}: {' '.join(cmd)}", flush=True)
    with open(log, "w") as fh:
        proc = subprocess.Popen(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                bufsize=1, errors="replace")
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            fh.write(line)
        code = proc.wait()
    secs = round(time.time() - t0, 1)
    moved = restore_logs(root, before, step_id)
    outputs, stale = [], []
    for o in outs:
        p = root / o
        if not p.exists() or p.stat().st_mtime < since:
            stale.append(o)
        else:
            outputs.append({"path": o, "sha256": sha256_file(p), "bytes": p.stat().st_size})
    rec.update({"exit": code, "seconds": secs, "outputs": outputs, "stale_outputs": stale,
                "new_files": new_files(root, since), "reads_moved": moved, "log": str(log.relative_to(root))})
    if code == 0 and stale:
        rec["exit"] = 4
    record(root, rec)
    if code != 0:
        print(f"[repro] {step_id}: FAILED with exit {code} after {secs} s (log: {log.relative_to(root)})",
              file=sys.stderr, flush=True)
        return code
    if stale:
        print(f"[repro] {step_id}: FAILED: declared output(s) not rewritten by this step: {', '.join(stale)}",
              file=sys.stderr, flush=True)
        return 4
    print(f"[repro] {step_id}: ok in {secs} s" + (f"; {moved} held-out re-read line(s) -> {READS_LOG}" if moved
                                                    else ""), flush=True)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("usage: run_step.py <id> [--out PATH]... [--skip-unless PATH --skip-reason TEXT] -- <command...>",
              file=sys.stderr)
        return 2
    i = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--out", action="append", default=[])
    ap.add_argument("--skip-unless")
    ap.add_argument("--skip-reason", default="optional input")
    a = ap.parse_args(argv[:i])
    cmd = argv[i + 1:]
    if not cmd:
        print("run_step.py: empty command", file=sys.stderr)
        return 2
    return run(a.id, cmd, a.out, a.skip_unless, a.skip_reason)


if __name__ == "__main__":
    sys.exit(main())
