"""Regression cases for paper drift, missing assets and stale PDF provenance."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import reproduction_contract as C


@pytest.fixture
def published(tmp_path):
    (tmp_path / "results/paper").mkdir(parents=True)
    (tmp_path / "models/vision").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "models/vision/frozen_call_model.pkl").write_bytes(b"fixed model")
    (tmp_path / "results/universe_conds.txt.gz").write_bytes(b"fixed universe")
    (tmp_path / "docs/NOTE.pdf").write_bytes(b"compiled PDF")
    numbers = {"generated_utc": "not compared", "numbers": {
        "trades": {"value": "100", "raw": 100},
        "edge": {"value": "+0.60", "raw": 0.603456},
        "ci": {"value": "[0.09, 1.13]", "raw": [0.093456, 1.13456]},
        "label": {"value": "counterfactual", "raw": {"host": "original"}},
    }}
    (tmp_path / "results/paper/numbers.json").write_text(json.dumps(numbers))
    refresh_checks(tmp_path)
    return tmp_path


def refresh_checks(root, ok=True):
    checks = {"ok": ok, "fail": [] if ok else ["six main pages"], "build": {
        "numbers_sha256": C.sha256_file(root / "results/paper/numbers.json"),
        "pdf_sha256": C.sha256_file(root / "docs/NOTE.pdf"),
    }}
    (root / "results/paper/checks.json").write_text(json.dumps(checks))


def change_number(root, key, **fields):
    path = root / "results/paper/numbers.json"
    data = json.loads(path.read_text())
    data["numbers"][key].update(fields)
    path.write_text(json.dumps(data))
    refresh_checks(root)


def test_identical_reference_passes(published):
    report = C.verify(C.capture(published), published)
    assert report["ok"] and report["printed_values_checked"] == 4
    assert report["raw_scalar_list_metrics_checked"] == 3
    assert report["value_only_keys"] == ["label"]


def test_changed_count_fails_even_with_large_float_tolerance(published):
    ref = C.capture(published)
    change_number(published, "trades", raw=101)
    report = C.verify(ref, published, atol=100, rtol=100)
    assert not report["ok"]
    assert any(e["kind"] == "raw_metric" and e["key"] == "trades" for e in report["errors"])


def test_unchanged_rounding_does_not_hide_changed_metric(published):
    ref = C.capture(published)
    change_number(published, "edge", raw=0.600001)
    assert not C.verify(ref, published)["ok"]


def test_small_float_noise_can_pass_but_printed_values_are_exact(published):
    ref = C.capture(published)
    change_number(published, "edge", raw=0.6034560001)
    assert C.verify(ref, published)["ok"]
    change_number(published, "edge", value="+0.61")
    assert not C.verify(ref, published)["ok"]


def test_ci_length_and_nonfinite_metrics_fail(published):
    ref = C.capture(published)
    change_number(published, "ci", raw=[0.093456])
    assert not C.verify(ref, published)["ok"]
    change_number(published, "edge", raw=float("nan"))
    assert not C.verify(ref, published)["ok"]


def test_missing_and_extra_registry_keys_fail(published):
    ref = C.capture(published)
    path = published / "results/paper/numbers.json"
    data = json.loads(path.read_text())
    data["numbers"].pop("trades")
    data["numbers"]["new"] = {"value": "1", "raw": 1}
    path.write_text(json.dumps(data))
    refresh_checks(published)
    kinds = {e["kind"] for e in C.verify(ref, published)["errors"]}
    assert {"missing_number", "unexpected_number"} <= kinds


@pytest.mark.parametrize("mode", ["missing", "different"])
def test_model_artifact_must_exist_and_match(published, mode):
    ref = C.capture(published)
    model = published / "models/vision/frozen_call_model.pkl"
    if mode == "missing":
        model.unlink()
    else:
        model.write_bytes(b"new model")
    assert not C.verify(ref, published)["ok"]


def test_unchecked_or_stale_pdf_cannot_pass(published):
    ref = C.capture(published)
    refresh_checks(published, ok=False)
    assert not C.verify(ref, published)["ok"]
    refresh_checks(published)
    (published / "docs/NOTE.pdf").write_bytes(b"different PDF")
    assert any(e["kind"] == "paper_pdf_provenance" for e in C.verify(ref, published)["errors"])


def test_changed_registry_requires_new_pdf_build_provenance(published):
    ref = C.capture(published)
    path = published / "results/paper/numbers.json"
    # Even a metadata-only update must belong to the specific completed PDF build.
    data = json.loads(path.read_text())
    data["generated_utc"] = "another build"
    path.write_text(json.dumps(data))
    assert any(e["kind"] == "paper_registry_provenance" for e in C.verify(ref, published)["errors"])


def test_reference_cannot_escape_checkout(published):
    ref = C.capture(published)
    ref["asset_sha256"]["../outside"] = "ignored"
    with pytest.raises(ValueError, match="escapes"):
        C.verify(ref, published)


def test_copy_failure_preserves_submitted_pdf(tmp_path, monkeypatch):
    src, dest = tmp_path / "new.pdf", tmp_path / "NOTE.pdf"
    src.write_bytes(b"new PDF")
    dest.write_bytes(b"submitted PDF")
    def fail_copy(source, target):
        Path(target).write_bytes(b"partial")
        raise OSError("disk full")
    monkeypatch.setattr(C.shutil, "copyfile", fail_copy)
    with pytest.raises(OSError, match="disk full"):
        C.atomic_copy(src, dest)
    assert dest.read_bytes() == b"submitted PDF"
    assert not list(tmp_path.glob(".NOTE.pdf-*"))


def test_cli_refuses_to_replace_reference_and_exits_nonzero_on_drift(published, tmp_path):
    cli = ROOT / "scripts/check_paper_reproduction.py"
    ref = tmp_path / "reference.json"
    def run(*args):
        return subprocess.run([sys.executable, str(cli), "--root", str(published), *args],
                              capture_output=True, text=True)
    assert run("--capture", str(ref)).returncode == 0
    original = ref.read_bytes()
    assert run("--capture", str(ref)).returncode == 1
    assert ref.read_bytes() == original
    change_number(published, "trades", value="101", raw=101)
    report = tmp_path / "report.json"
    assert run("--reference", str(ref), "--report", str(report)).returncode == 1
    assert json.loads(report.read_text())["ok"] is False
