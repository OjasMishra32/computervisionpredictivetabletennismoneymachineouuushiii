"""Rebuild the private data caches that later reproduce.sh steps read but no earlier step writes.

    .venv/bin/python scripts/reproduce_inputs.py      # each cache is reused only when its sidecar matches
    .venv/bin/python scripts/reproduce_inputs.py --rebuild   # rebuild all three caches

reproduce.sh runs this right after run_all.py --oos (which writes the prints tables the lowloss builders read) and
before every consumer (scripts/v2_wallet_cap.py, scripts/psr_mintrl.py, scripts/cv_cost_turnover.py and the CV
scripts that read src/tier0.jump_table('is')).

A cache is reused only if its sidecar (<cache>.inputs.json) records the same sha256 of the builder's source files and
of its inputs (the prints tables, or the input manifest's universe split and tape-row hashes). A cache from older
code (for example before a change to src/tiers.py) or from other inputs is rebuilt, never silently reused.

The authors' machine had these tables from the research runs; a clean clone (bash run.sh data, then
reproduce.sh up to scripts/v2_causal.py) does not, so scripts/v2_wallet_cap.py, scripts/psr_mintrl.py and
scripts/cv_cost_turnover.py stopped with FileNotFoundError on a clean clone (2026-10-04).

  data/derived/jumps_is.parquet                 IS >= 4c jump onsets: scripts/derive_is.py's jumps(), unchanged
                                                (read by src/tier0.jump_table('is'))
  data/v2_lowloss/{features,whist}_is.parquet   IS causal v2 feature table: scripts/lowloss_select.py's build(),
                                                unchanged (read by scripts/v2_wallet_cap.py --is)
  data/v2_lowloss/{features,whist}_u1.parquet   IS + OOS feature table: scripts/lowloss_test.py's
  (+ features_u1.json)                          build('u1'), unchanged (read by scripts/v2_wallet_cap.py --oos --repro)

Only the authors' builders are called: no grid, test or selection runs and nothing is chosen. The u1 table reads
the OOS prints, the same table the logged run of scripts/lowloss_test.py built. Under reproduce.sh, any line a step
appends to results/oos_peeks.log is moved to results/repro/reads.log (scripts/repro/run_step.py), so a reproduction
never adds to the authors' record of held-out reads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


REBUILD = False
# Source files each builder's output depends on (the builder itself and the src modules it calls).
CODE = {
    "jumps_is": ["scripts/derive_is.py", "src/tiers.py", "src/fasttier.py", "src/tape.py", "src/polymarket.py"],
    "lowloss_is": ["scripts/lowloss_select.py", "src/tiers.py", "src/v2.py", "src/fasttier.py", "src/tape.py"],
    "lowloss_u1": ["scripts/lowloss_test.py", "src/tiers.py", "src/v2.py", "src/fasttier.py", "src/tape.py"],
}
PRINTS = {"is": "data/is_prints.parquet", "oos": "data/locked/oos_prints.parquet"}


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), "[reproduce_inputs]", msg, flush=True)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stamp(name: str, inputs: list[str]) -> dict:
    """What the cache `name` was built from: builder source hashes and input hashes."""
    st = {"code": {f: _sha(ROOT / f) for f in CODE[name] if (ROOT / f).exists()},
          "inputs": {f: _sha(ROOT / f) for f in inputs}}
    man = ROOT / "results/provenance/inputs_manifest.json"
    if name == "jumps_is" and man.exists():   # the tapes: the verified input manifest stands for them
        m = json.loads(man.read_text())
        st["inputs"]["universe.split_sha256"] = m["universe"]["split_sha256"]
        st["inputs"]["tapes.rows_merkle_sha256"] = m["groups"]["tapes"]["rows_merkle_sha256"]
    return st


def fresh(sidecar: Path, st: dict, outs: list[Path]) -> bool:
    if REBUILD or not all(o.exists() for o in outs) or not sidecar.exists():
        return False
    try:
        return json.loads(sidecar.read_text()) == st
    except ValueError:
        return False


def seal(sidecar: Path, st: dict) -> None:
    sidecar.write_text(json.dumps(st, indent=1, sort_keys=True) + "\n")


def jumps_is() -> None:
    out = ROOT / "data/derived/jumps_is.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)   # src/tier0 caches its tables here too
    side = out.with_name(out.name + ".inputs.json")
    st = stamp("jumps_is", [])
    if fresh(side, st, [out]):
        log(f"{out.relative_to(ROOT)} up to date (sidecar matches), reused")
        return
    if out.exists():
        log(f"{out.relative_to(ROOT)} exists without a matching sidecar: rebuilding")
    from scripts.derive_is import jumps
    from src.tape import universe
    t0 = time.time()
    u = universe()
    u_is = u[~u.oos]
    with ProcessPoolExecutor(8) as ex:   # as scripts/derive_is.py (ex.map keeps the input order)
        js = [x for part in ex.map(jumps, u_is.to_dict("records"), chunksize=32) for x in part]
    pd.DataFrame(js).to_parquet(out)
    seal(side, st)
    log(f"wrote {out.relative_to(ROOT)}: {len(js):,} jumps, {time.time() - t0:.0f} s")


def lowloss_is() -> None:
    cache = ROOT / "data/v2_lowloss"
    outs = [cache / "features_is.parquet", cache / "whist_is.parquet"]
    side = cache / "features_is.inputs.json"
    st = stamp("lowloss_is", [PRINTS["is"]])
    if fresh(side, st, outs):
        log("data/v2_lowloss/{features,whist}_is.parquet up to date (sidecar matches), reused")
        return
    for o in outs:   # lowloss_select.build() reuses whatever files exist: move stale ones aside so it rebuilds
        if o.exists():
            log(f"{o.relative_to(ROOT)} exists without a matching sidecar: moved to {o.name}.stale, rebuilding")
            o.replace(o.with_name(o.name + ".stale"))
    from scripts import lowloss_select
    t0 = time.time()
    f, wh = lowloss_select.build()
    if not all(o.exists() for o in outs):
        raise SystemExit("lowloss_select.build() did not write data/v2_lowloss/{features,whist}_is.parquet")
    seal(side, st)
    log(f"wrote data/v2_lowloss/{{features,whist}}_is.parquet: {len(f):,} feature rows, {time.time() - t0:.0f} s")


def lowloss_u1() -> None:
    from scripts import lowloss_test
    from src.tape import universe
    t0 = time.time()
    u1 = universe()
    assert (u1.oos == (u1.start >= lowloss_test.CUT)).all(), "U1 oos flag must equal start >= cutoff"
    ends1 = u1.set_index("cond").end
    cache = ROOT / "data/v2_lowloss"
    side = cache / "features_u1.inputs.json"
    st = stamp("lowloss_u1", [PRINTS["is"], PRINTS["oos"]])
    outs = [cache / "features_u1.parquet", cache / "whist_u1.parquet"]
    # build() also checks its own json (prints only); the sidecar adds the builder code, so new code rebuilds
    rebuild = not fresh(side, st, outs)
    f, wh = lowloss_test.build("u1", [PRINTS["is"], PRINTS["oos"]], ends1, rebuild)
    seal(side, st)
    log(f"data/v2_lowloss/{{features,whist}}_u1.parquet {'rebuilt' if rebuild else 'up to date'}: {len(f):,} "
        f"feature rows, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", action="store_true", help="rebuild every cache whatever its sidecar says")
    REBUILD = ap.parse_args().rebuild
    for name, p in PRINTS.items():
        if not (ROOT / p).exists():
            raise SystemExit(f"{p} missing: run `run_all.py --oos` first (reproduce.sh step s01)")
    jumps_is()
    lowloss_is()
    lowloss_u1()
