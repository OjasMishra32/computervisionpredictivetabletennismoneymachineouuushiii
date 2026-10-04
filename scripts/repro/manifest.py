"""Input manifest of the submitted snapshot: created once from the authors' inputs, verified before every reproduction.

    python scripts/repro/manifest.py create              # authors: hash the inputs -> results/provenance/inputs_manifest.json
    python scripts/repro/manifest.py verify              # reproduce.sh step s00: exit 0 only if the inputs are the snapshot's
    python scripts/repro/manifest.py verify --allow-drift  # record differences in results/repro/input_drift.json, exit 0

What is pinned
  universe  the event-list rows the pipeline uses (src.tape.universe(): ATP/WTA/Challenger singles >= $5k): frozen
            condition ids (results/universe_conds.txt.gz), the 80/20 split counts and the first OOS start, a hash of
            the split (cond, start, oos) and a hash of every universe field the pipeline reads
  tapes     one row per universe trade tape in results/provenance/inputs_tapes.tsv.gz: bytes, sha256 of the file,
            sha256 of its rows (independent of row order and parquet encoding), row count, first/last timestamp
  archived  the small public inputs committed under results/repro/inputs/ (fresh-holdout window, factor files)
  models    models/vision/frozen_call_model.pkl (committed; the camera engine's frozen call model)
  config    the OOS rule and cutoff, seeds as written in the code, Python version, requirements.lock

Hashing reads bytes and computes no statistic. It is not a held-out read and writes nothing to results/oos_peeks.log.

verify exit codes
  0  inputs match the snapshot (a tape whose bytes differ but whose rows are identical counts as a match)
  1  universe, split, cutoff or model mismatch, a missing event list, or an unreadable manifest (never allowed:
     the walk-forward tables and the locked split would be a different experiment)
  3  tape or archived-input drift (missing tapes, different rows); --allow-drift records it and returns 0, and the
     run manifest then labels the run "inputs differ from the submitted snapshot"
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import platform
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.repro.common import (ARCHIVE, INPUTS_MANIFEST, REPRO, TAPES_TSV, git_state, sha256_file,  # noqa: E402
                                  utc_now, write_json)

SCHEMA = "courtside.provenance.inputs/1"
MODEL = Path("models/vision/frozen_call_model.pkl")
UNIVERSE_CONDS = Path("results/universe_conds.txt.gz")
LOCK = Path("requirements.lock")
UNIVERSE_FIELDS = ["cond", "slug", "series", "start", "end", "res0", "volume", "fee_rate", "delay", "tok0", "tok1", "oos"]
# Seeds and frozen constants as written in the code (recorded so a reader sees them in one place; git pins the code).
CONFIG_PATTERNS = {
    "run_all.calibration_seed": ("run_all.py", r"def calibration\(.*seed=(\d+)"),
    "rigor_pack.SEED": ("scripts/rigor_pack.py", r"^SEED = (\d+)"),
    "impact_model.SEED": ("scripts/impact_model.py", r"^SEED = (\d+)"),
    "edge_persistence.SEED": ("scripts/edge_persistence.py", r"^SEED = (\d+)"),
    "psr_mintrl.CV_SEEDS": ("scripts/psr_mintrl.py", r"^CV_SEEDS, CV_BOOT_PER_SEED = (\d+), (\d+)"),
    "fresh_holdout.SHOW_SEED": ("scripts/fresh_holdout.py", r"^SHOW_SEED = (\d+)"),
    "tape.OOS_FRAC": ("src/tape.py", r"^OOS_FRAC = ([0-9.]+)"),
    "tape.MIN_VOL": ("src/tape.py", r"^MIN_VOL = ([0-9_]+)"),
    "tape.SINCE_UNTIL": ("src/tape.py", r'^SINCE, UNTIL = "([0-9-]+)", "([0-9-]+)"'),
}


# ----------------------------------------------------------------------------------------------- hashing
def rows_sha256(path: str) -> tuple[str, int, int | None, int | None]:
    """sha256 over the sorted per-row hashes (columns in name order): the same trades give the same digest whatever
    the row order or parquet writer."""
    import numpy as np
    import pandas as pd
    df = pd.read_parquet(path)
    if df.empty:
        return hashlib.sha256(b"").hexdigest(), 0, None, None
    cols = sorted(df.columns)
    hv = np.sort(pd.util.hash_pandas_object(df[cols], index=False).to_numpy())
    ts = df["timestamp"] if "timestamp" in df else None
    return (hashlib.sha256(hv.tobytes()).hexdigest(), len(df),
            int(ts.min()) if ts is not None else None, int(ts.max()) if ts is not None else None)


def _tape_row(args: tuple[str, str]) -> dict:
    cond, path = args
    if not os.path.exists(path):
        return {"cond": cond, "bytes": -1, "sha256": "", "rows_sha256": "", "rows": -1, "ts_min": "", "ts_max": ""}
    rs, n, t0, t1 = rows_sha256(path)
    return {"cond": cond, "bytes": os.path.getsize(path), "sha256": sha256_file(Path(path)), "rows_sha256": rs,
            "rows": n, "ts_min": "" if t0 is None else t0, "ts_max": "" if t1 is None else t1}


def merkle(pairs) -> str:
    return hashlib.sha256("\n".join(sorted(f"{a} {b}" for a, b in pairs)).encode()).hexdigest()


def frame_sha256(df) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False, date_format="%Y-%m-%dT%H:%M:%S%z", float_format="%.10g")
    return hashlib.sha256(buf.getvalue().encode()).hexdigest()


# ----------------------------------------------------------------------------------------------- inputs
def events_path() -> Path:
    from src import polymarket as pm
    from src.tape import SINCE, UNTIL
    return pm.RAW / f"events_tennis_{SINCE}_{UNTIL}.parquet"


def universe_block(root: Path = ROOT) -> dict:
    """Universe facts from the cached event list (never crawls: verify refuses when the cache is absent)."""
    import pandas as pd
    from src.tape import universe
    ev = events_path()
    if not ev.exists():
        raise SystemExit(f"manifest: {ev} is missing: run `bash run.sh data` first (the public crawl)")
    u = universe()
    cols = [c for c in UNIVERSE_FIELDS if c in u.columns]
    canon = u[cols].sort_values(["start", "cond"], kind="stable").reset_index(drop=True)
    split = canon[["cond", "start", "oos"]]
    frozen = sorted(gzip.open(root / UNIVERSE_CONDS, "rt").read().split())
    return {
        "events_file": str(ev), "events_sha256": sha256_file(ev),
        "n_matches": int(len(u)), "n_is": int((~u.oos).sum()), "n_oos": int(u.oos.sum()),
        "oos_start_utc": pd.Timestamp(u.loc[u.oos, "start"].min()).isoformat(),
        "oos_rule": "last 20% of matches by start time (track rule: latest 20% or latest two years, whichever is "
                    "shorter; 20% binds), src/tape.py",
        "conds_file": str(UNIVERSE_CONDS), "conds_sha256": sha256_file(root / UNIVERSE_CONDS),
        "conds_equal_frozen_list": sorted(u.cond.astype(str)) == frozen,
        "split_sha256": frame_sha256(split), "fields": cols, "fields_sha256": frame_sha256(canon),
        "_conds": u.cond.astype(str).tolist(),
    }


def pmap(fn, jobs: list, workers: int) -> list:
    if workers <= 1 or len(jobs) < 64:
        return [fn(j) for j in jobs]
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(fn, jobs, chunksize=64))


def tape_rows(conds: list[str], workers: int = 8) -> list[dict]:
    from src import polymarket as pm
    return pmap(_tape_row, [(c, str(pm.RAW / "trades" / f"{c}.parquet")) for c in conds], workers)


def archived_block(root: Path = ROOT) -> list[dict]:
    base = root / ARCHIVE
    if not base.exists():
        return []
    return [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": sha256_file(p)}
            for p in sorted(base.rglob("*")) if p.is_file()]


def config_block(root: Path = ROOT) -> dict:
    out = {}
    for key, (rel, pat) in CONFIG_PATTERNS.items():
        f = root / rel
        m = re.search(pat, f.read_text(errors="ignore"), re.M) if f.exists() else None
        out[key] = {"file": rel, "value": list(m.groups()) if m else None}
    return out


def write_tsv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = ["cond", "bytes", "sha256", "rows_sha256", "rows", "ts_min", "ts_max"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, keys, delimiter="\t", lineterminator="\n")
    w.writeheader()
    for r in sorted(rows, key=lambda r: r["cond"]):
        w.writerow({k: r[k] for k in keys})
    # gzip mtime 0 keeps the file byte-stable
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue().encode())


def read_tsv(path: Path) -> list[dict]:
    with gzip.open(path, "rt") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


# ----------------------------------------------------------------------------------------------- create
def create(root: Path = ROOT, workers: int = 8) -> dict:
    os.chdir(root)
    ub = universe_block(root)
    conds = ub.pop("_conds")
    rows = tape_rows(conds, workers)
    missing = [r["cond"] for r in rows if r["bytes"] < 0]
    if missing:
        raise SystemExit(f"manifest create: {len(missing)} universe tapes missing (first: {missing[:3]}); "
                         "the snapshot must be complete")
    write_tsv(rows, root / TAPES_TSV)
    model = root / MODEL
    man = {
        "schema": SCHEMA, "created_utc": utc_now(),
        "created_from": f"authors' cache at {git_state(root)['git_head']}",
        "note": "sha256 of every input the reproduction reads that is not in git; hashing computes no statistic and "
                "is not a held-out read",
        "universe": ub,
        "groups": {
            "tapes": {"dir": "data/raw/trades", "n": len(rows), "bytes": sum(int(r["bytes"]) for r in rows),
                      "rows": sum(int(r["rows"]) for r in rows),
                      "merkle_sha256": merkle((r["cond"], r["sha256"]) for r in rows),
                      "rows_merkle_sha256": merkle((r["cond"], r["rows_sha256"]) for r in rows),
                      "files_tsv_gz": str(TAPES_TSV), "files_tsv_gz_sha256": sha256_file(root / TAPES_TSV),
                      "n_at_data_api_offset_cap_10000": sum(int(r["rows"]) >= 10000 for r in rows)},
            "archived": archived_block(root),
            "models": [{"path": str(MODEL), "bytes": model.stat().st_size, "sha256": sha256_file(model)}]
            if model.exists() else [],
        },
        "config": config_block(root),
        "python": platform.python_version(),
        "requirements_lock_sha256": sha256_file(root / LOCK) if (root / LOCK).exists() else None,
    }
    write_json(root / INPUTS_MANIFEST, man)
    print(f"manifest: {len(rows):,} tapes ({man['groups']['tapes']['bytes'] / 1e9:.2f} GB), "
          f"{len(man['groups']['archived'])} archived inputs, universe {ub['n_matches']:,} = {ub['n_is']:,} IS + "
          f"{ub['n_oos']:,} OOS from {ub['oos_start_utc']} -> {INPUTS_MANIFEST}")
    return man


# ----------------------------------------------------------------------------------------------- verify
def verify(root: Path = ROOT, allow_drift: bool = False, quick: bool = False, workers: int = 8) -> int:
    """Compare the inputs on disk with the manifest; write results/repro/input_drift.json; return an exit code."""
    os.chdir(root)
    report = {"schema": "courtside.repro.input_drift/1", "checked_utc": utc_now(), "fatal": [], "drift": {},
              "notes": []}
    try:
        man = json.loads((root / INPUTS_MANIFEST).read_text())
        assert man.get("schema") == SCHEMA, f"schema {man.get('schema')!r}"
    except Exception as exc:  # noqa: BLE001  (any unreadable manifest is fatal)
        report["fatal"].append(f"cannot read {INPUTS_MANIFEST}: {exc}")
        return _finish(root, report, allow_drift)
    report["inputs_manifest_sha256"] = sha256_file(root / INPUTS_MANIFEST)

    # universe and split: fatal on any difference that changes the experiment
    try:
        ub = universe_block(root)
    except SystemExit as exc:
        report["fatal"].append(str(exc))
        return _finish(root, report, allow_drift)
    conds = ub.pop("_conds")
    want = man["universe"]
    for k in ("n_matches", "n_is", "n_oos", "oos_start_utc", "conds_sha256", "split_sha256"):
        if ub.get(k) != want.get(k):
            report["fatal"].append(f"universe.{k}: snapshot {want.get(k)!r}, here {ub.get(k)!r}")
    if not ub["conds_equal_frozen_list"]:
        report["fatal"].append("universe condition ids differ from results/universe_conds.txt.gz "
                               "(scripts/freeze_universe.py reports which)")
    if ub["fields_sha256"] != want.get("fields_sha256"):
        report["drift"]["universe_fields"] = ("universe rows have the snapshot's split but other fields differ "
                                              "(e.g. a later crawl's volume); results that read them can move")
    if ub["events_sha256"] != want.get("events_sha256"):
        report["notes"].append("events parquet bytes differ from the snapshot (expected for a later crawl; the "
                               "universe checks above decide)")

    # models: fatal (committed in git; a different file is a different engine)
    for m in man["groups"].get("models", []):
        p = root / m["path"]
        if not p.exists():
            report["fatal"].append(f"{m['path']} missing (it is committed: git checkout -- {m['path']})")
        elif sha256_file(p) != m["sha256"]:
            report["fatal"].append(f"{m['path']} sha256 differs from the manifest")

    # archived inputs: drift
    bad_arch = []
    for a in man["groups"].get("archived", []):
        p = root / a["path"]
        if not p.exists() or sha256_file(p) != a["sha256"]:
            bad_arch.append(a["path"])
    if bad_arch:
        report["drift"]["archived"] = bad_arch

    # tapes: drift (bytes first; rows hash only when the bytes differ)
    snap = {r["cond"]: r for r in read_tsv(root / man["groups"]["tapes"]["files_tsv_gz"])}
    from src import polymarket as pm
    missing, differ, same_rows = [], [], 0
    recheck = []
    for c in conds:
        r = snap.get(c)
        p = pm.RAW / "trades" / f"{c}.parquet"
        if r is None:
            continue                       # cannot happen when the split hash matched
        if not p.exists():
            missing.append(c)
        elif p.stat().st_size != int(r["bytes"]) or sha256_file(p) != r["sha256"]:
            recheck.append((c, str(p)))
    if recheck and not quick:
        for (c, _), row in zip(recheck, pmap(_tape_row, recheck, workers)):
            if row["rows_sha256"] == snap[c]["rows_sha256"]:
                same_rows += 1
            else:
                differ.append({"cond": c, "rows_snapshot": int(snap[c]["rows"]), "rows_here": row["rows"]})
    elif recheck:
        differ = [{"cond": c, "rows_snapshot": int(snap[c]["rows"]), "rows_here": None} for c, _ in recheck]
    if missing:
        report["drift"]["tapes_missing"] = missing
    if differ:
        report["drift"]["tapes_rows_differ"] = differ
    report["tapes"] = {"n": len(conds), "missing": len(missing), "rows_differ": len(differ),
                       "bytes_differ_rows_identical": same_rows}
    return _finish(root, report, allow_drift)


def _finish(root: Path, report: dict, allow_drift: bool) -> int:
    report["n_drift_groups"] = len(report["drift"])
    code = 1 if report["fatal"] else (3 if report["drift"] and not allow_drift else 0)
    report["exit"] = code
    report["snapshot_inputs"] = not report["fatal"] and not report["drift"]
    write_json(root / REPRO / "input_drift.json", report)
    for f in report["fatal"]:
        print(f"manifest verify FATAL: {f}", file=sys.stderr)
    if any(f.startswith("universe") for f in report["fatal"]):
        print("  (a later crawl lists matches resolved after ours: `python scripts/freeze_universe.py` pins the event "
              "list to the paper's 13,084; `bash run.sh data` runs it)", file=sys.stderr)
    if report["drift"]:
        print("=" * 100, file=sys.stderr)
        print("INPUTS DIFFER FROM THE SUBMITTED SNAPSHOT: " + "; ".join(
            f"{k}: {len(v) if isinstance(v, list) else v}" for k, v in report["drift"].items()), file=sys.stderr)
        print(f"details: {REPRO / 'input_drift.json'}" + ("" if allow_drift else
              "  (ALLOW_INPUT_DRIFT=1 runs anyway; the run is then labelled as not the submitted snapshot)"),
              file=sys.stderr)
        print("=" * 100, file=sys.stderr)
    if code == 0 and report["snapshot_inputs"]:
        t = report.get("tapes", {})
        print(f"manifest verify: inputs match the submitted snapshot ({t.get('n', 0):,} tapes"
              + (f", {t['bytes_differ_rows_identical']} with identical rows in different bytes"
                 if t.get("bytes_differ_rows_identical") else "") + ")")
    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["create", "verify"])
    ap.add_argument("--allow-drift", action="store_true")
    ap.add_argument("--quick", action="store_true", help="verify: byte hashes only (no row hashes on mismatch)")
    a = ap.parse_args(argv)
    if a.cmd == "create":
        create()
        return 0
    return verify(allow_drift=a.allow_drift, quick=a.quick)


if __name__ == "__main__":
    sys.exit(main())
