"""Compare paper values and frozen assets, and publish a checked PDF atomically.

This comparison is an acceptance check after a clean reproduction, not evidence
that the computations ran. The caller must run the real pipeline in a clean clone.
Only the Python standard library is required.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path

ASSETS = ("models/vision/frozen_call_model.pkl", "results/universe_conds.txt.gz")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_copy(source: Path, destination: Path) -> None:
    """Do not truncate the submitted PDF if copying fails or the disk is full."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + destination.name + "-", dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def registry(path: Path) -> dict:
    data = json.loads(path.read_text())
    numbers = data.get("numbers")
    if not isinstance(numbers, dict) or not numbers:
        raise ValueError(f"{path}: expected a nonempty 'numbers' object")
    for key, entry in numbers.items():
        if not isinstance(entry, dict) or "value" not in entry or "raw" not in entry:
            raise ValueError(f"{path}: invalid registry entry {key}")
    return numbers


def numeric_tree(value) -> bool:
    """Raw scalar/list metrics can be compared without opaque run metadata."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return isinstance(value, list) and bool(value) and all(numeric_tree(v) for v in value)


def capture(root: Path) -> dict:
    numbers = registry(root / "results/paper/numbers.json")
    return {
        "schema": 1,
        "scope": "all printed registry values, finite raw scalar/list metrics, and listed frozen assets",
        "paper_values": {k: v["value"] for k, v in numbers.items()},
        "numeric_raw": {k: v["raw"] for k, v in numbers.items() if numeric_tree(v["raw"])},
        "value_only_keys": [k for k, v in numbers.items() if not numeric_tree(v["raw"])],
        "asset_sha256": {rel: sha256_file(root / rel) for rel in ASSETS},
    }


def _numeric_equal(expected, actual, atol: float, rtol: float) -> bool:
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(expected) == len(actual)
                and all(_numeric_equal(a, b, atol, rtol) for a, b in zip(expected, actual)))
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    if not math.isfinite(actual):
        return False
    # Counts and other integer-valued references never receive a tolerance.
    if isinstance(expected, int):
        return expected == actual
    return math.isclose(expected, actual, abs_tol=atol, rel_tol=rtol)


def verify(reference: dict, root: Path, atol: float = 1e-8, rtol: float = 1e-10) -> dict:
    if reference.get("schema") != 1 or not reference.get("paper_values"):
        raise ValueError("invalid or empty reproduction reference")
    if not math.isfinite(atol) or not math.isfinite(rtol) or atol < 0 or rtol < 0:
        raise ValueError("numeric tolerances must be finite and nonnegative")
    numbers = registry(root / "results/paper/numbers.json")
    errors = []
    expected = reference["paper_values"]
    for key in sorted(set(expected) | set(numbers)):
        if key not in numbers:
            errors.append({"kind": "missing_number", "key": key})
        elif key not in expected:
            errors.append({"kind": "unexpected_number", "key": key})
        elif expected[key] != numbers[key]["value"]:
            errors.append({"kind": "printed_value", "key": key,
                           "expected": expected[key], "actual": numbers[key]["value"]})
    for key, raw in reference.get("numeric_raw", {}).items():
        if key in numbers and not _numeric_equal(raw, numbers[key]["raw"], atol, rtol):
            errors.append({"kind": "raw_metric", "key": key,
                           "expected": raw, "actual": numbers[key]["raw"]})
    for rel, digest in reference.get("asset_sha256", {}).items():
        path = root / rel
        # A reference file must not redirect checks outside the reproduction checkout.
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"asset path escapes the checkout: {rel}")
        if not path.is_file():
            errors.append({"kind": "missing_asset", "path": rel})
        elif sha256_file(path) != digest:
            errors.append({"kind": "asset_hash", "path": rel})

    checks_path = root / "results/paper/checks.json"
    pdf_path = root / "docs/NOTE.pdf"
    if not checks_path.is_file():
        errors.append({"kind": "missing_paper_checks"})
    else:
        checks = json.loads(checks_path.read_text())
        if checks.get("ok") is not True:
            errors.append({"kind": "paper_checks_failed", "fail": checks.get("fail", [])})
        build = checks.get("build", {})
        if build.get("numbers_sha256") != sha256_file(root / "results/paper/numbers.json"):
            errors.append({"kind": "paper_registry_provenance"})
        if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            errors.append({"kind": "missing_paper_pdf"})
        elif build.get("pdf_sha256") != sha256_file(pdf_path):
            errors.append({"kind": "paper_pdf_provenance"})
    return {
        "ok": not errors,
        "printed_values_checked": len(expected),
        "raw_scalar_list_metrics_checked": len(reference.get("numeric_raw", {})),
        "value_only_keys": reference.get("value_only_keys", []),
        "assets_checked": sorted(reference.get("asset_sha256", {})),
        "numeric_tolerances": {"absolute": atol, "relative": rtol, "integer_counts": "exact"},
        "scope": reference.get("scope"),
        "limitation": "Equality does not prove computation. Run the full pipeline in a clean clone first.",
        "errors": errors,
    }
