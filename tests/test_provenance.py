"""Tests for the experiment registry (results/provenance/experiments.json) and scripts/provenance.py."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import provenance as P

ROOT = Path(__file__).resolve().parents[1]
REG_PATH = ROOT / P.REGISTRY


def load_registry() -> dict:
    return json.loads(REG_PATH.read_text())


def _has_history() -> bool:
    return P.Git(ROOT).commit_time("7232986") is not None


def record_logs() -> dict:
    """The read logs as committed when the git history is present. `bash run.sh replay` (judge quick path) and other
    local runs append lines to the working-tree log that record that run; the registry maps the committed record."""
    return P.read_logs(ROOT, "HEAD" if _has_history() else None)


needs_git = pytest.mark.skipif(not _has_history(), reason="needs the repository's full git history")


# --------------------------------------------------------------------------- the committed registry
@needs_git
def test_committed_registry_passes_check():
    assert P.validate(load_registry(), ROOT, logs=record_logs()) == []


@needs_git
def test_cli_check_exits_zero(capsys):
    assert P.main(["check", "--committed"]) == 0
    assert "provenance: OK" in capsys.readouterr().out


def test_every_log_line_mapped_exactly_once():
    reg, logs = load_registry(), record_logs()
    for logname in (P.OOS_LOG, *P.AUX_LOGS):
        mapped = []
        for ev in reg["events"]:
            mapped += ev["oos_log_lines"] if logname == P.OOS_LOG else ev.get("aux_log_lines", {}).get(logname, [])
        assert sorted(mapped) == list(range(1, len(logs[logname]) + 1)), logname
    assert reg["summary"]["log_lines_unmapped"] == 0
    assert reg["summary"]["log_lines_total"] == len(logs[P.OOS_LOG])


def test_summary_and_log_lines_match_recomputation():
    reg, logs = load_registry(), record_logs()
    assert reg["log_lines"] == P.compute_log_lines(reg, logs)
    assert reg["summary"] == P.compute_summary(reg, logs)


def test_build_is_idempotent():
    reg, logs = load_registry(), record_logs()
    assert P.build(copy.deepcopy(reg), logs) == reg


def test_each_result_label_follows_label_rules():
    reg = load_registry()
    by_id = {e["id"]: e for e in reg["events"]}
    for r in reg["results"]:
        evs = [by_id[i] for i in r["events"]]
        assert r["label"] == P.derive_label(r, evs), r["id"]
        assert P.required_flags(evs) <= set(r.get("flags", [])), r["id"]


def test_printed_words_never_say_burned_and_stay_short():
    reg = load_registry()
    for ev in reg["events"]:
        if ev["kind"] in ("d", "e"):
            assert ev["printed_text"].strip() and ev["direction"].strip(), ev["id"]
        if "printed_text" in ev:
            assert "burned" not in ev["printed_text"].lower(), ev["id"]
            assert len(ev["printed_text"].split()) <= P.MAX_PRINTED_WORDS, ev["id"]
    for r in reg["results"]:
        assert "burned" not in r["label_text"].lower(), r["id"]


def test_known_decisions_are_registered():
    """The OOS-informed design choices verified against the evidence stay in the registry."""
    s = load_registry()["summary"]
    assert {"E06", "E10", "E16", "E22", "E41", "E45", "E50"} <= {d["id"] for d in s["oos_informed_decisions"]}
    assert {d["id"] for d in s["oos_informed_decisions"] if d["oos_selected"]} == {"E10", "E22", "E41", "E45"}


def test_log_timestamps_normalised_to_utc():
    assert P.log_line_utc("2026-10-03T17:16:15.5-04:00 x") == datetime(2026, 10, 3, 21, 16, 15, tzinfo=timezone.utc)
    assert P.log_line_utc("2026-10-03T10:57:29.950149Z y") == datetime(2026, 10, 3, 10, 57, 29, tzinfo=timezone.utc)
    with pytest.raises(P.RegistryError):
        P.log_line_utc("2026-10-03T10:57:29 no offset")


# --------------------------------------------------------------------------- synthetic fixtures
def T(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class FakeGit:
    def __init__(self, commits: dict[str, str], tracked: set[str], objects: set[str] = frozenset()):
        self.commits = {k: T(v) for k, v in commits.items()}
        self._tracked, self.objects = set(tracked), set(objects)

    def commit_time(self, rev):
        return self.commits.get(rev)

    def is_ancestor(self, rev):
        return rev in self.commits

    def object_exists(self, spec):
        return spec in self.objects

    def tracked(self, path):
        return path in self._tracked


COMMITS = {"aaaaaaa": "2026-10-03T09:00:00Z", "bbbbbbb": "2026-10-03T10:30:00Z",
           "ccccccc": "2026-10-03T11:30:00Z", "ddddddd": "2026-10-03T12:30:00Z"}


def fixture(tmp_path: Path):
    (tmp_path / "results").mkdir(exist_ok=True)
    (tmp_path / P.OOS_LOG).write_text(
        "2026-10-03T10:00:00.1+00:00 first OOS read\n"
        "2026-10-03T07:05:00-04:00 reproduction\n"
        "2026-10-03T12:00:00+00:00 blind read\n")
    (tmp_path / "NOTES.md").write_text("\n".join(f"line {i}" for i in range(1, 11)) + "\n")
    base = dict(time_source="log", decision=False, summary="s", evidence=["NOTES.md:1-5"], touches=[])
    events = [
        dict(base, id="E00", utc="2026-10-03T09:00:00Z", time_source="commit", commit="aaaaaaa", kind="protocol",
             family="v1", oos_log_lines=[]),
        dict(base, id="E01", utc="2026-10-03T10:00:00Z", commit="bbbbbbb", prereg_commit="aaaaaaa", kind="a",
             family="v1", data_state="clean", oos_log_lines=[1], touches=["R_oos"]),
        dict(base, id="E02", utc="2026-10-03T11:05:00Z", commit="ccccccc", kind="b", family="v1",
             data_state="burned", oos_log_lines=[2], touches=["R_oos"]),
        dict(base, id="E03", utc="2026-10-03T12:00:00Z", commit="ddddddd", prereg_commit="ccccccc", kind="f",
             family="v2", data_state="untouched", oos_log_lines=[3], touches=["R_blind"]),
    ]
    reg = {"schema": P.SCHEMA, "kinds": {}, "kind_labels": dict(P.KIND_LABELS), "data_states": {},
           "label_rules": [], "events": events,
           "results": [
               {"id": "R_oos", "paper": "p", "period": "OOS", "kind": "event_study", "label": "clean-oos",
                "label_text": "OOS, single pre-registered evaluation", "events": ["E01", "E02"]},
               {"id": "R_blind", "paper": "p", "period": "U2", "kind": "event_study", "label": "blind",
                "label_text": "Blind", "events": ["E03"]}],
           "log_lines": [], "summary": {}}
    git = FakeGit(COMMITS, {"NOTES.md"})
    logs = P.read_logs(tmp_path)
    return P.build(reg, logs), git, logs


def errors(reg, git, logs, tmp_path):
    return P.validate(reg, tmp_path, git, logs)


def rebuilt(reg, logs):
    return P.build(reg, logs)


def test_fixture_is_valid(tmp_path):
    reg, git, logs = fixture(tmp_path)
    assert errors(reg, git, logs, tmp_path) == []
    assert reg["log_lines"][1]["utc"] == "2026-10-03T11:05:00Z"  # -04:00 line normalised


@pytest.mark.parametrize("mutate, needle", [
    (lambda r: r["events"][1].pop("summary"), "field 'summary'"),
    (lambda r: r["events"][1].update(kind="z"), "unknown kind"),
    (lambda r: r["events"][1].update(family="nope"), "unknown family"),
    (lambda r: r["events"][1].update(utc="2026-10-03 10:00"), "utc must be"),
    (lambda r: r["events"][2].update(commit="eeeeeee"), "not found"),
    (lambda r: r["events"][2].update(commit="aaaaaaa"), "precedes the event"),
    (lambda r: r["events"][1].update(prereg_commit="ddddddd"), "is not before the read"),
    (lambda r: r["events"][3].pop("prereg_commit"), "need prereg_commit"),
    (lambda r: r["events"][2].update(evidence=["UNTRACKED.md"]), "not tracked"),
    (lambda r: r["events"][2].update(evidence=["local:x.log"]), "no verifiable evidence"),
    (lambda r: r["events"][2].update(evidence=["NOTES.md:40"]), "beyond end"),
    (lambda r: r["events"][2].update(oos_log_lines=[]), "line 2 is not mapped"),
    (lambda r: r["events"][2].update(oos_log_lines=[1, 2]), "mapped to 2 events"),
    (lambda r: r["events"][2].update(oos_log_lines=[2, 9]), "out of range"),
    (lambda r: r["events"][2].update(utc="2026-10-03T11:10:00Z"), "before the event start"),
    (lambda r: r["events"][2].update(touches=["R_missing"]), "unknown result"),
    (lambda r: r["events"][3].update(data_state="burned"), "untouched or partly_read"),
    (lambda r: r["results"][0].update(label="blind"), "label_rules give 'clean-oos'"),
    (lambda r: r["results"][0].update(label_text="burned OOS"), "must not say 'burned'"),
    (lambda r: r["results"][0].update(events=["E01"]), "differ from the events that touch it"),
], ids=lambda x: x if isinstance(x, str) else "")
def test_validator_rejects(tmp_path, mutate, needle):
    reg, git, logs = fixture(tmp_path)
    mutate(reg)
    errs = errors(reg, git, logs, tmp_path)
    assert any(needle in e for e in errs), errs


def test_decision_events_need_direction_and_printed_text(tmp_path):
    reg, git, logs = fixture(tmp_path)
    reg["events"].append(dict(id="E04", utc="2026-10-03T12:30:00Z", time_source="commit", commit="ddddddd",
                              kind="d", decision=True, family="v2", data_state="burned", summary="s",
                              evidence=["NOTES.md"], oos_log_lines=[], touches=["R_oos"]))
    reg["results"][0]["events"].append("E04")
    errs = errors(rebuilt(reg, logs), git, logs, tmp_path)
    assert any("need a direction" in e for e in errs) and any("need printed_text" in e for e in errs)
    reg["events"][-1].update(direction="up", printed_text="A burned look chose this.")
    errs = errors(rebuilt(reg, logs), git, logs, tmp_path)
    assert any("must not say 'burned'" in e for e in errs)
    reg["events"][-1].update(printed_text="A design choice was made after an OOS look.")
    errs = errors(rebuilt(reg, logs), git, logs, tmp_path)
    # the d event makes the OOS result non-blind and demands the flag
    assert any("label_rules give 'burned-non-blind'" in e for e in errs)
    reg["results"][0].update(label="burned-non-blind", flags=["oos_informed_design"])
    assert errors(rebuilt(reg, logs), git, logs, tmp_path) == []


def test_stale_derived_fields_fail(tmp_path):
    reg, git, logs = fixture(tmp_path)
    reg["summary"]["n_events"] = 99
    assert any("summary differs" in e for e in errors(reg, git, logs, tmp_path))
    reg, git, logs = fixture(tmp_path)
    reg["events"][2]["oos_informed"] = True
    assert any("oos_informed is True" in e for e in errors(reg, git, logs, tmp_path))


def test_prereg_after_run_must_be_disclosed_and_flagged(tmp_path):
    reg, git, logs = fixture(tmp_path)
    reg["events"][1].update(prereg_commit="ddddddd", prereg_commit_after_run=True)
    errs = errors(rebuilt(reg, logs), git, logs, tmp_path)
    assert any("flags missing ['prereg_committed_after_run']" in e for e in errs)
    reg["results"][0]["flags"] = ["prereg_committed_after_run"]
    assert errors(rebuilt(reg, logs), git, logs, tmp_path) == []


def test_derive_label_cases():
    a_clean = {"id": "E1", "kind": "a", "data_state": "clean"}
    b_burned = {"id": "E2", "kind": "b", "data_state": "burned"}
    d_burned = {"id": "E3", "kind": "d", "data_state": "burned"}
    f_clean = {"id": "E4", "kind": "f", "data_state": "untouched", "prereg_commit": "x"}
    f_partly = {"id": "E5", "kind": "f", "data_state": "partly_read", "prereg_commit": "x"}
    c_fwd = {"id": "E6", "kind": "c", "data_state": "forward"}
    d_fwd = {"id": "E7", "kind": "d", "data_state": "forward"}
    proto = {"id": "E8", "kind": "protocol"}
    oos = {"period": "OOS"}
    assert P.derive_label({"period": "IS"}, [d_burned]) == "in-sample"
    assert P.derive_label(oos, [a_clean, b_burned]) == "clean-oos"
    assert P.derive_label(oos, [a_clean, d_burned]) == "burned-non-blind"
    assert P.derive_label({"period": "U2"}, [d_burned, f_clean]) == "blind"
    assert P.derive_label({"period": "U2"}, [f_clean, f_partly]) == "post-freeze"
    assert P.derive_label({"period": "U2"}, [dict(f_clean, prereg_commit_after_run=True)]) == "post-freeze"
    assert P.derive_label({"period": "forward"}, [d_burned, proto]) == "not-run"
    assert P.derive_label({"period": "replay"}, [c_fwd, d_fwd]) == "exploratory"
    assert not P.oos_informed(d_fwd) and P.oos_informed(d_burned)
