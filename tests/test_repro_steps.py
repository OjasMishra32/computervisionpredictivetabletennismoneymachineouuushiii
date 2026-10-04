"""Step runner, run manifest, committed-artifact listing and check, archived inputs, offline guard."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.repro import artifacts as A  # noqa: E402
from scripts.repro import expect as E  # noqa: E402
from scripts.repro import holdout_inputs as H  # noqa: E402
from scripts.repro import run_manifest as RM  # noqa: E402
from scripts.repro import run_step as S  # noqa: E402
from scripts.repro.common import sha256_file, write_json  # noqa: E402

PY = sys.executable


def steps(root):
    f = root / "results/repro/steps.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


# ------------------------------------------------------------------------------------------------ run_step
def test_step_passes_and_records_outputs(tmp_path):
    out = "results/x.json"
    (tmp_path / "results").mkdir()
    code = S.run("s1", [PY, "-c", f"open('{out}','w').write('1')"], [out], None, "", root=tmp_path)
    assert code == 0
    rec = steps(tmp_path)[0]
    assert rec["exit"] == 0 and rec["outputs"][0]["path"] == out and rec["outputs"][0]["sha256"]
    assert (tmp_path / "results/repro/logs/s1.log").exists()


def test_step_failure_propagates(tmp_path):
    assert S.run("s1", [PY, "-c", "import sys; sys.exit(7)"], [], None, "", root=tmp_path) == 7
    assert steps(tmp_path)[0]["exit"] == 7


def test_declared_output_not_rewritten_fails(tmp_path):
    (tmp_path / "results").mkdir()
    old = tmp_path / "results/old.json"
    old.write_text("{}")
    past = time.time() - 3600
    os.utime(old, (past, past))
    assert S.run("s1", [PY, "-c", "pass"], ["results/old.json"], None, "", root=tmp_path) == 4   # silent skip
    assert steps(tmp_path)[0]["stale_outputs"] == ["results/old.json"]
    assert S.run("s2", [PY, "-c", "pass"], ["results/missing.json"], None, "", root=tmp_path) == 4


def test_skip_unless_records_reason(tmp_path):
    assert S.run("s1", [PY, "-c", "import sys; sys.exit(9)"], ["results/i.json"], "data/live/x.gz", "not distributed",
                 root=tmp_path) == 0
    rec = steps(tmp_path)[0]
    assert rec["skipped"] is True and "not distributed" in rec["reason"]


def test_heldout_log_lines_move_to_reads_log(tmp_path):
    (tmp_path / "results").mkdir()
    log = tmp_path / "results/oos_peeks.log"
    log.write_text("line 1\n")
    before = log.read_bytes()
    cmd = [PY, "-c", "open('results/oos_peeks.log','a').write('a re-read\\n')"]
    assert S.run("s1", cmd, [], None, "", root=tmp_path) == 0
    assert log.read_bytes() == before                                   # the authors' record is unchanged
    assert "s1\tresults/oos_peeks.log\ta re-read" in (tmp_path / "results/repro/reads.log").read_text()
    assert steps(tmp_path)[0]["reads_moved"] == 1


def test_rewritten_log_is_restored_and_flagged(tmp_path):
    (tmp_path / "results").mkdir()
    log = tmp_path / "results/oos_peeks.log"
    log.write_text("line 1\nline 2\n")
    assert S.run("s1", [PY, "-c", "open('results/oos_peeks.log','w').write('x\\n')"], [], None, "",
                 root=tmp_path) == 0
    assert log.read_text() == "line 1\nline 2\n"
    assert "rewritten (not appended)" in (tmp_path / "results/repro/reads.log").read_text()


# ------------------------------------------------------------------------------------------------ run manifest
def test_run_manifest_start_finish(tmp_path, monkeypatch):
    monkeypatch.setattr(RM, "pip_freeze", lambda: ["x==1"])
    (tmp_path / "results").mkdir()
    RM.start(tmp_path)
    S.run("s1", [PY, "-c", "open('results/a.json','w').write('1')"], ["results/a.json"], None, "", root=tmp_path)
    S.run("s2", [PY, "-c", "pass"], ["results/b.json"], "data/live", "absent", root=tmp_path)
    man = RM.finish("ok", tmp_path)
    assert man["status"] == "ok" and [s["id"] for s in man["steps"]] == ["s1"]
    assert man["skipped"][0]["id"] == "s2" and "results/a.json" in man["outputs"]
    assert man["pip_freeze"] == ["x==1"]
    S.run("s3", [PY, "-c", "import sys; sys.exit(1)"], [], None, "", root=tmp_path)
    assert RM.finish("ok", tmp_path)["status"] == "failed"               # any failed step fails the run


# ------------------------------------------------------------------------------------------------ artifacts
REPRO_SH = """#!/usr/bin/env bash
step s01 --out results/a.json -- $PY make_a.py   # comment
step s02 --out results/live.json --skip-unless data/live/x.gz \\
  --skip-reason "not distributed" -- $PY make_live.py
"""


@pytest.fixture
def paper(tmp_path):
    (tmp_path / "results/paper").mkdir(parents=True)
    (tmp_path / "results/tier0").mkdir(parents=True)
    for f, body in {"results/a.json": "{}", "results/live.json": "{}", "results/tier0/latency_sweep.json": "{}"}.items():
        (tmp_path / f).write_text(body)
    (tmp_path / "reproduce.sh").write_text(REPRO_SH)
    numbers = {"numbers": {
        "k1": {"value": "1", "raw": 1, "source": "results/a.json::x"},
        "k2": {"value": "2", "raw": 2, "source": "results/live.json::y"},
        "k3": {"value": "3", "raw": 3, "source": "results/tier0/latency_sweep.json::z"},
        "k4": {"value": "4", "raw": 4, "source": "HYPOTHESIS_V2.md::A5 (results/v2/forward.json absent at build time)"},
        "k5": {"value": "5", "raw": 5, "source": "src/markov.py TennisModel"}}}
    write_json(tmp_path / "results/paper/numbers.json", numbers)
    return tmp_path


def run_manifest_with(root, outs):
    write_json(root / "results/repro/run_manifest.json",
               {"steps": [{"id": "s01", "exit": 0, "declared_outputs": outs, "stale_outputs": []}]})


def test_parse_steps_handles_continuations():
    st = A.steps(REPRO_SH)
    assert [s["id"] for s in st] == ["s01", "s02"]
    assert st[1]["outs"] == ["results/live.json"] and st[1]["skip_unless"] == "data/live/x.gz"


def test_write_lists_committed_with_reasons(paper):
    assert A.write(paper) == 0
    d = json.loads((paper / "results/paper/committed_artifacts.json").read_text())
    assert [r["path"] for r in d["recomputed"]] == ["results/a.json"]
    com = {c["path"]: c for c in d["committed"]}
    assert set(com) == {"results/live.json", "results/tier0/latency_sweep.json"}
    assert com["results/live.json"]["recompute_step"] == "s02"
    assert "HiPerGator" in com["results/tier0/latency_sweep.json"]["why_not_recomputed"]
    assert com["results/tier0/latency_sweep.json"]["sha256"] == sha256_file(paper / "results/tier0/latency_sweep.json")
    assert [x["path"] for x in d["cited_as_absent"]] == ["results/v2/forward.json"]
    assert {x["path"] for x in d["documents_and_code"]} == {"HYPOTHESIS_V2.md", "src/markov.py"}


def test_write_refuses_unclassified_source(paper):
    (paper / "results/mystery.json").write_text("{}")
    n = json.loads((paper / "results/paper/numbers.json").read_text())
    n["numbers"]["k6"] = {"value": "6", "raw": 6, "source": "results/mystery.json::q"}
    write_json(paper / "results/paper/numbers.json", n)
    assert A.write(paper) == 1


def test_check_passes_then_catches_changed_committed_artifact(paper):
    assert A.write(paper) == 0
    run_manifest_with(paper, ["results/a.json"])
    assert A.check(paper) == 0
    (paper / "results/tier0/latency_sweep.json").write_text('{"changed": 1}')
    assert A.check(paper) == 1


def test_check_catches_source_neither_recomputed_nor_listed(paper):
    assert A.write(paper) == 0
    run_manifest_with(paper, [])                       # s01 did not rewrite results/a.json in this run
    assert A.check(paper) == 1
    rep = json.loads((paper / "results/repro/artifact_check.json").read_text())
    assert any("results/a.json" in p for p in rep["problems"])


def test_committed_listing_covers_the_current_paper():
    """Every source of the committed numbers.json is recomputed by reproduce.sh or listed with a reason."""
    d = json.loads((ROOT / "results/paper/committed_artifacts.json").read_text())
    src = A.sources(json.loads((ROOT / "results/paper/numbers.json").read_text()))
    listed = ({r["path"] for r in d["recomputed"]} | {c["path"] for c in d["committed"]}
              | {x["path"] for x in d["documents_and_code"]} | {x["path"] for x in d["cited_as_absent"]})
    assert set(src) <= listed, sorted(set(src) - listed)
    for c in d["committed"]:
        assert c["producer"] and c["why_not_recomputed"], c["path"]


# ------------------------------------------------------------------------------------------------ archived inputs
def test_restore_checks_sha_and_never_overwrites(tmp_path, monkeypatch):
    arch = tmp_path / "results/repro/inputs/factors"
    arch.mkdir(parents=True)
    for f in H.FACTOR_FILES:
        (arch / f).write_text(f"{f}\n")
    man = {"groups": {"archived": [{"path": f"results/repro/inputs/factors/{f}", "sha256": sha256_file(arch / f)}
                                   for f in H.FACTOR_FILES]}}
    write_json(tmp_path / "results/provenance/inputs_manifest.json", man)
    monkeypatch.setattr(H, "FH_FILES", ())
    assert H.restore(tmp_path) == 0
    assert (tmp_path / "data/factors" / H.FACTOR_FILES[0]).read_text() == f"{H.FACTOR_FILES[0]}\n"
    assert H.restore(tmp_path) == 0                                   # identical files: left alone
    (tmp_path / "data/factors" / H.FACTOR_FILES[0]).write_text("someone else's file\n")
    assert H.restore(tmp_path) == 1                                   # different data file: refused
    (arch / H.FACTOR_FILES[1]).write_text("tampered\n")
    assert H.restore(tmp_path) == 1


def test_fixed_holdout_run_has_no_network(monkeypatch):
    from src import polymarket as pm
    import requests
    monkeypatch.setattr(pm, "_get", pm._get)
    monkeypatch.setattr(requests, "get", requests.get)
    monkeypatch.setattr(requests.Session, "request", requests.Session.request)
    H.block_network()
    with pytest.raises(RuntimeError, match="network access refused"):
        pm._get("https://gamma-api.polymarket.com/events", {})
    with pytest.raises(RuntimeError, match="network access refused"):
        requests.get("https://example.com")


def test_archived_holdout_window_is_complete():
    import pandas as pd
    w = pd.read_parquet(ROOT / "results/repro/inputs/fresh_holdout/window_universe.parquet")
    meta = json.loads((ROOT / "results/repro/inputs/fresh_holdout/window_meta.json").read_text())
    assert len(w) == meta["eligible_matches"] == 22
    for c in w.cond:
        assert (ROOT / f"results/repro/inputs/fresh_holdout/trades/{c}.parquet").exists()


# ------------------------------------------------------------------------------------------------ offline, expect
def test_offline_guard_blocks_remote_hosts_only():
    code = ("import socket\n"
            "try:\n    socket.getaddrinfo('gamma-api.polymarket.com', 443)\n    print('OPEN')\n"
            "except OSError as e:\n    print('BLOCKED' if 'COURTSIDE_OFFLINE' in str(e) else 'OTHER')\n"
            "socket.getaddrinfo('localhost', 80)\nprint('LOCAL_OK')\n")
    env = dict(os.environ, COURTSIDE_OFFLINE="1", PYTHONPATH=str(ROOT / "scripts/repro/offline"))
    out = subprocess.run([PY, "-c", code], env=env, capture_output=True, text=True, timeout=60).stdout.split()
    assert out == ["BLOCKED", "LOCAL_OK"]


def test_expect(tmp_path):
    f = tmp_path / "e.json"
    f.write_text(json.dumps({"snowflake": {"recheck": {"status": "skipped"}}, "vultr": {"tests": {"returncode": 0}}}))
    assert E.main([str(f), "vultr.tests.returncode=0"]) == 0
    assert E.main([str(f), "snowflake.recheck.status=ran"]) == 1
    assert E.main([str(f), "nope.key=1"]) == 1
