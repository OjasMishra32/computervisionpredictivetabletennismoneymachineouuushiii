"""Archived inputs: the fresh holdout's stored window and the factor files, so a reproduction never refetches them.

    python scripts/repro/holdout_inputs.py archive    # authors, once: data/ -> results/repro/inputs/ (small, public)
    python scripts/repro/holdout_inputs.py restore    # reproduce.sh: results/repro/inputs/ -> data/ (sha256-checked)
    python scripts/repro/holdout_inputs.py run-fixed  # reproduce.sh: the completed fresh holdout, rerun on its stored
                                                      # inputs with the network disabled
    python scripts/repro/holdout_inputs.py new-fetch  # a NEW holdout: lists and downloads the matches finished since
                                                      # the window start NOW, into results/fresh_holdout_new/<utc>/

The fresh holdout (scripts/fresh_holdout.py, PREREG research/v2/tier0_v3/fresh/PREREG_FRESH.md) was fetched once, at
2026-10-04 05:44 UTC: 22 eligible matches. Its window listing, fetch metadata and the 22 public trade tapes (1.2 MB)
are archived under results/repro/inputs/fresh_holdout/, with sha256 in results/provenance/inputs_manifest.json.
`run-fixed` restores them and runs scripts/fresh_holdout.py's own run() and the per-seed paths on exactly those
inputs; the G1/G2 gate files it requires are the committed results/fresh_holdout/{history,equivalence_check}.json.
It is a reproduction of the completed evaluation. A refetch today lists more (and different) matches, so it is a
different holdout: `new-fetch` writes it to its own directory and labels it, and never touches the submitted
results/fresh_holdout/.

Factor files: scripts/factor_regression.py downloads the Ken French daily factors on a cache miss (a mutable source
that is revised over time). The authors' copies are archived under results/repro/inputs/factors/ and restored into
data/factors/ before that step, so the regression reads the snapshot's factors.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.repro.common import ARCHIVE, INPUTS_MANIFEST, sha256_file, utc_now, write_json  # noqa: E402

FH_ARCH = ARCHIVE / "fresh_holdout"
FACTOR_ARCH = ARCHIVE / "factors"
FH_DATA = Path("data/fresh")
FACTOR_DATA = Path("data/factors")
FH_FILES = ("window_universe.parquet", "window_meta.json", "unresolved_check.json")
FACTOR_FILES = ("F-F_Research_Data_Factors_daily.csv", "F-F_Momentum_Factor_daily.csv")


def pairs(root: Path = ROOT) -> list[tuple[Path, Path]]:
    """(archived path, data path) for every archived input; the window's tapes come from the archived listing."""
    out = [(FH_ARCH / f, FH_DATA / f) for f in FH_FILES]
    out += [(FACTOR_ARCH / f, FACTOR_DATA / f) for f in FACTOR_FILES]
    w = root / FH_ARCH / "window_universe.parquet"
    src = w if w.exists() else root / FH_DATA / "window_universe.parquet"
    if src.exists():
        import pandas as pd
        for c in sorted(pd.read_parquet(src, columns=["cond"]).cond.astype(str)):
            out.append((FH_ARCH / "trades" / f"{c}.parquet", FH_DATA / "raw" / "trades" / f"{c}.parquet"))
    return out


def archive(root: Path = ROOT) -> int:
    n = 0
    for arch, data in pairs(root):
        a, d = root / arch, root / data
        if not d.exists():
            raise SystemExit(f"archive: {data} missing; the archive must hold every stored input")
        a.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(d, a)
        n += 1
    print(f"archived {n} files under {ARCHIVE} (run `scripts/repro/manifest.py create` to record their sha256)")
    return 0


def expected(root: Path = ROOT) -> dict[str, str]:
    man = json.loads((root / INPUTS_MANIFEST).read_text())
    return {a["path"]: a["sha256"] for a in man["groups"].get("archived", [])}


def restore(root: Path = ROOT) -> int:
    """Copy archived inputs into data/ after checking their sha256 against the manifest. An existing data/ file
    with the same sha256 is left alone; one with a different sha256 is an error (never overwritten silently)."""
    want = expected(root)
    bad, copied, same = [], 0, 0
    for arch, data in pairs(root):
        a, d = root / arch, root / data
        if str(arch) not in want:
            bad.append(f"{arch}: not in the input manifest")
            continue
        if not a.exists() or sha256_file(a) != want[str(arch)]:
            bad.append(f"{arch}: missing or sha256 differs from the input manifest")
            continue
        if d.exists():
            if sha256_file(d) == want[str(arch)]:
                same += 1
                continue
            bad.append(f"{data}: exists with a different sha256 than the archived input (move it aside first)")
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a, d)
        copied += 1
    if bad:
        for b in bad:
            print(f"restore: {b}", file=sys.stderr)
        return 1
    print(f"restore: {copied} archived inputs copied into data/, {same} already identical")
    return 0


def block_network() -> None:
    """Any HTTP request from the fixed-data run is an error (the evaluation must use only the stored inputs)."""
    import requests

    from src import polymarket as pm

    def refuse(*a, **k):
        raise RuntimeError("network access refused: the fixed-data holdout run uses only the archived inputs")

    pm._get = refuse
    requests.get = requests.post = requests.request = refuse
    requests.Session.request = refuse


def run_fixed(root: Path = ROOT) -> int:
    if restore(root):
        return 1
    block_network()
    sys.path.insert(0, str(root / "scripts"))
    import fresh_holdout as FH
    import fresh_holdout_seed_paths as SP
    meta = json.loads((root / FH_DATA / "window_meta.json").read_text())
    print(f"fresh holdout, fixed data: the window fetched at {meta['fetch_time_utc']} "
          f"({meta['eligible_matches']} matches), frozen code, network disabled")
    FH.run()
    SP.main()
    return 0


def new_fetch(root: Path = ROOT) -> int:
    """A new, mutable evaluation: today's listing of the same window rule. Kept apart from the submitted holdout."""
    sys.path.insert(0, str(root / "scripts"))
    import fresh_holdout as FH
    stamp = utc_now().replace(":", "").replace("+0000", "Z")
    out = root / "results/fresh_holdout_new" / stamp
    data = root / "data/fresh_new" / stamp
    out.mkdir(parents=True, exist_ok=False)
    for f in ("history.json", "equivalence_check.json"):   # the code gates, computed once on already-read data
        shutil.copy2(root / "results/fresh_holdout" / f, out / f)
    FH.OUT, FH.DATA, FH.FRESH_RAW, FH.DER = out, data, data / "raw", data / "derived"
    write_json(out / "LABEL.json", {
        "label": "NEW holdout fetched at the time below: not the submitted evaluation (results/fresh_holdout/). "
                 "The window rule and frozen code are the same; the listing, matches and fetch time differ.",
        "fetched_utc": utc_now(), "data_dir": str(data.relative_to(root))})
    FH.fetch(refetch=True)
    FH.run()
    print(f"new holdout -> {out.relative_to(root)} (the submitted results/fresh_holdout/ is unchanged)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["archive", "restore", "run-fixed", "new-fetch"])
    a = ap.parse_args(argv)
    return {"archive": archive, "restore": restore, "run-fixed": run_fixed, "new-fetch": new_fetch}[a.cmd]()


if __name__ == "__main__":
    sys.exit(main())
