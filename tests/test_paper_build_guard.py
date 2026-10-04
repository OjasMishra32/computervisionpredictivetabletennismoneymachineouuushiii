"""Exercise the real builder's publish/failure paths without market reads."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def builder(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("_paper_guard_test", ROOT / "scripts/build_paper.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    out, docs = tmp_path / "results/paper", tmp_path / "docs"
    out.mkdir(parents=True)
    docs.mkdir()
    (docs / "NOTE.pdf").write_bytes(b"submitted PDF")
    compiler = tmp_path / "tectonic"
    compiler.write_text("#!/bin/sh\nexit 0\n")
    compiler.chmod(0o755)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "OUT", out)
    monkeypatch.setattr(m, "TECTONIC", str(compiler))
    monkeypatch.setattr(sys, "argv", ["build_paper.py", "--no-figures"])
    state = {"collect_calls": 0, "companion_calls": 0}
    def collect():
        state["collect_calls"] += 1
        return SimpleNamespace(d={"one": 1}), {}
    def write_numbers(n, extra):
        (out / "numbers.json").write_text('{"numbers":{"one":{"value":"1","raw":1}}}')
    def compile_tex(path):
        pdf = tmp_path / "new.pdf"
        pdf.write_bytes(b"new compiled PDF")
        return pdf, "clean log"
    def companion(n, extra):
        state["companion_calls"] += 1
    monkeypatch.setattr(m, "collect", collect)
    monkeypatch.setattr(m, "write_numbers", write_numbers)
    monkeypatch.setattr(m, "prepare_logo", lambda: None)
    monkeypatch.setattr(m, "render_tex", lambda n, e: tmp_path / "note.tex")
    monkeypatch.setattr(m, "compile_tex", compile_tex)
    monkeypatch.setattr(m, "write_companion", companion)
    result = {"ok": True, "fail": [], "main_pages": 5, "total_pages": 15,
              "smallest_span_pt": 11, "cv_label_count_main": 3, "overfull_hbox_pt": []}
    monkeypatch.setattr(m, "checks", lambda pdf, log: dict(result))
    return m, state, result, tmp_path


def test_missing_compiler_fails_before_overwriting_results(builder, monkeypatch):
    m, state, result, root = builder
    monkeypatch.setattr(m, "TECTONIC", str(root / "missing"))
    assert m.main() == 2
    assert state["collect_calls"] == 0
    assert (root / "docs/NOTE.pdf").read_bytes() == b"submitted PDF"


def test_nonexecutable_compiler_fails(builder):
    m, state, result, root = builder
    Path(m.TECTONIC).chmod(0o644)
    assert m.main() == 2 and state["collect_calls"] == 0


def test_check_bypass_is_rejected(builder, monkeypatch):
    m, state, result, root = builder
    monkeypatch.setattr(sys, "argv", ["build_paper.py", "--no-figures", "--no-checks-fail"])
    assert m.main() == 2 and state["collect_calls"] == 0


def test_failed_checks_preserve_submission_and_write_failure_report(builder):
    m, state, result, root = builder
    result.update(ok=False, fail=["six main pages"])
    assert m.main() == 1
    assert (root / "docs/NOTE.pdf").read_bytes() == b"submitted PDF"
    assert state["companion_calls"] == 0
    assert json.loads((m.OUT / "checks.json").read_text())["ok"] is False


def test_success_records_provenance_and_publishes_new_pdf(builder):
    m, state, result, root = builder
    assert m.main() == 0
    pdf = root / "docs/NOTE.pdf"
    assert pdf.read_bytes() == b"new compiled PDF" and state["companion_calls"] == 1
    build = json.loads((m.OUT / "checks.json").read_text())["build"]
    assert build["pdf_sha256"] == m.sha256_file(pdf)
    assert build["numbers_sha256"] == m.sha256_file(m.OUT / "numbers.json")


def test_compilation_failure_preserves_existing_submission(builder, monkeypatch):
    m, state, result, root = builder
    def fail(path):
        raise RuntimeError("compile failed")
    monkeypatch.setattr(m, "compile_tex", fail)
    with pytest.raises(RuntimeError, match="compile failed"):
        m.main()
    assert (root / "docs/NOTE.pdf").read_bytes() == b"submitted PDF"
