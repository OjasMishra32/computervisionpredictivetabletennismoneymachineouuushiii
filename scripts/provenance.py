#!/usr/bin/env python3
"""Experiment registry: validate and summarise results/provenance/experiments.json.

    python scripts/provenance.py check      # validate; exit 1 on any error (default)
    python scripts/provenance.py build      # recompute derived fields, write them, then check
    python scripts/provenance.py summary    # print the derived summary as JSON

The registry lists every out-of-sample (OOS) or held-out read, every decision taken after such a
read, every pre-registration and every reproduction, each tied to a git commit, to lines of the
read logs and to committed evidence. Events and results are written by hand. These fields are
derived and must never be edited by hand: events[].oos_informed, log_lines, summary. `build`
writes them; `check` fails if they differ from a recomputation.

`check` fails on a malformed event (missing or ill-typed field, unknown kind or state), on an
unsupported event (commit missing or not an ancestor of HEAD, evidence file not in git, log line
out of range or out of time order, pre-registration committed after the read without saying so),
on any line of the read logs that is not mapped to exactly one event, on a result whose label
cannot be derived from its events, and on a stale summary. See docs/PROVENANCE.md.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "results/provenance/experiments.json"
SCHEMA = "courtside.provenance.experiments/1"
OOS_LOG = "results/oos_peeks.log"
AUX_LOGS = ("results/tracking/test_peeks.log", "results/tt/peeks.log")

KINDS = ("a", "b", "c", "d", "e", "f", "protocol")
KIND_LABELS = {
    "a": "pre-registered evaluation",
    "b": "reproduction",
    "c": "replay-diagnostic",
    "d": "design/headline choice after an OOS look",
    "e": "defect fix after an OOS look",
    "f": "blind or post-freeze evaluation",
    "protocol": "protocol change (no data read)",
}
DATA_STATES = ("clean", "burned", "untouched", "partly_read", "forward", "test_used")
# Data states whose look counts as an out-of-sample / held-out look for oos_informed.
OOS_STATES = ("clean", "burned", "untouched", "partly_read", "test_used")
FAMILIES = ("v1", "v2", "tracking", "forward", "cv", "maker", "capacity", "tt", "replay")
TIME_SOURCES = ("log", "commit", "mtime", "document")
PERIODS = ("IS", "OOS", "U2", "fresh", "test", "side_markets", "tt", "forward", "replay", "mixed")
RESULT_KINDS = ("executable", "sim_upper_bound", "others_fills", "conditional", "event_study",
                "descriptive", "diagnostic")
LABELS = ("in-sample", "clean-oos", "blind", "post-freeze", "burned-non-blind", "exploratory", "not-run")
FORBIDDEN_WORDS = re.compile(r"\bburned\b", re.I)  # never printed (paper rule)
UTC_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
EVENT_ID_RE = re.compile(r"^E\d{2}[a-z]?$")
RESULT_ID_RE = re.compile(r"^R_[a-z0-9_]+$")
RECORD_SLACK = timedelta(seconds=120)  # a recording commit may not precede its event by more
MAX_PRINTED_WORDS = 25


class RegistryError(Exception):
    pass


# --------------------------------------------------------------------------- git access
class Git:
    """Read-only git queries against the repo, cached."""

    def __init__(self, repo: Path):
        self.repo = Path(repo)
        self._time: dict[str, datetime | None] = {}
        self._anc: dict[str, bool] = {}
        self._obj: dict[str, bool] = {}
        self._tracked: set[str] | None = None

    def _run(self, *args: str) -> str | None:
        r = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    def commit_time(self, rev: str) -> datetime | None:
        if rev not in self._time:
            out = self._run("log", "-1", "--format=%cI", f"{rev}^{{commit}}", "--")
            self._time[rev] = datetime.fromisoformat(out).astimezone(timezone.utc) if out else None
        return self._time[rev]

    def is_ancestor(self, rev: str) -> bool:
        if rev not in self._anc:
            r = subprocess.run(["git", "-C", str(self.repo), "merge-base", "--is-ancestor", rev, "HEAD"],
                               capture_output=True)
            self._anc[rev] = r.returncode == 0
        return self._anc[rev]

    def object_exists(self, spec: str) -> bool:
        if spec not in self._obj:
            self._obj[spec] = self._run("cat-file", "-e", spec) is not None
        return self._obj[spec]

    def tracked(self, path: str) -> bool:
        if self._tracked is None:
            out = self._run("ls-files", "-z") or ""
            self._tracked = set(p for p in out.split("\0") if p)
        return path in self._tracked


# --------------------------------------------------------------------------- helpers
def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fmt_utc(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_line_utc(raw: str) -> datetime:
    """First field of a read-log line; any ISO offset (Z, +00:00, -04:00) normalised to UTC, floored to 1 s."""
    ts = raw.split()[0]
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    d = datetime.fromisoformat(ts)
    if d.tzinfo is None:
        raise RegistryError(f"log timestamp without offset: {raw[:40]!r}")
    return d.astimezone(timezone.utc).replace(microsecond=0)


def read_logs(repo: Path) -> dict[str, list[str]]:
    logs = {}
    for rel in (OOS_LOG, *AUX_LOGS):
        p = Path(repo) / rel
        logs[rel] = [l for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
    return logs


def word_count(s: str) -> int:
    return len(s.split())


def oos_informed(ev: dict) -> bool:
    return ev.get("kind") in ("d", "e") and ev.get("data_state") in OOS_STATES


def derive_label(result: dict, evs: list[dict]) -> str:
    """The result label from label_rules, computed from the result's period and its events."""
    if result.get("period") == "IS":
        return "in-sample"
    kinds = {e["kind"] for e in evs}
    if not kinds & {"a", "b", "c", "f"}:
        return "not-run"
    fs = [e for e in evs if e["kind"] == "f"]
    if fs:
        clean = all(e.get("data_state") == "untouched" and e.get("prereg_commit")
                    and not e.get("prereg_commit_after_run") for e in fs)
        return "blind" if clean else "post-freeze"
    if any(e["kind"] == "a" and e.get("data_state") == "clean" for e in evs) and not kinds & {"d", "e"}:
        return "clean-oos"
    if any(oos_informed(e) for e in evs) or any(
            e.get("data_state") in ("burned", "test_used") for e in evs if e["kind"] != "protocol"):
        return "burned-non-blind"
    return "exploratory"


def required_flags(evs: list[dict]) -> set[str]:
    req = set()
    if any(e.get("oos_selected") for e in evs):
        req.add("oos_selected")
    if any(e["kind"] == "d" and oos_informed(e) for e in evs):
        req.add("oos_informed_design")
    if any(e["kind"] == "e" and oos_informed(e) for e in evs):
        req.add("defect_fix_after_oos")
    if any(e.get("prereg_commit_after_run") and e["kind"] in ("a", "f") for e in evs):
        req.add("prereg_committed_after_run")
    return req


def compute_log_lines(reg: dict, logs: dict[str, list[str]]) -> list[dict]:
    owner = {}
    for ev in reg.get("events", []):
        for n in ev.get("oos_log_lines", []):
            owner.setdefault(n, []).append(ev.get("id"))
    out = []
    for i, raw in enumerate(logs.get(OOS_LOG, []), start=1):
        ids = owner.get(i, [])
        out.append({"line": i, "raw_ts": raw.split()[0], "utc": fmt_utc(log_line_utc(raw)),
                    "event": ids[0] if len(ids) == 1 else None})
    return out


def compute_summary(reg: dict, logs: dict[str, list[str]]) -> dict:
    evs = reg.get("events", [])
    by_time = sorted(evs, key=lambda e: (e.get("utc", ""), e.get("id", "")))
    mapped = Counter(n for e in evs for n in e.get("oos_log_lines", []))
    n_lines = len(logs.get(OOS_LOG, []))
    aux_total = {k: len(logs.get(k, [])) for k in AUX_LOGS}
    res_by_label: dict[str, list[str]] = {}
    for r in reg.get("results", []):
        res_by_label.setdefault(r.get("label"), []).append(r.get("id"))
    return {
        "n_events": len(evs),
        "n_events_by_kind": {k: sum(1 for e in evs if e.get("kind") == k) for k in KINDS},
        "oos_informed_decisions": [
            {"id": e["id"], "utc": e["utc"], "family": e["family"], "kind": e["kind"],
             "kind_label": KIND_LABELS[e["kind"]], "direction": e.get("direction"),
             "oos_selected": bool(e.get("oos_selected")), "printed_text": e.get("printed_text")}
            for e in by_time if oos_informed(e)],
        "design_choices_after_oos": [e["id"] for e in by_time if e["kind"] == "d" and oos_informed(e)],
        "defect_fixes_after_oos": [
            {"id": e["id"], "family": e["family"], "direction": e.get("direction"),
             "printed_text": e.get("printed_text")}
            for e in by_time if e["kind"] == "e" and oos_informed(e)],
        "decisions_after_non_oos_look": [e["id"] for e in by_time
                                         if e["kind"] in ("d", "e") and not oos_informed(e)],
        "preregistered_evaluations": [
            {"id": e["id"], "family": e["family"], "data_state": e.get("data_state"),
             "prereg_commit": e.get("prereg_commit"),
             "prereg_committed_after_run": bool(e.get("prereg_commit_after_run"))}
            for e in by_time if e["kind"] == "a"],
        "blind_or_post_freeze_evaluations": [
            {"id": e["id"], "family": e["family"], "data_state": e.get("data_state"),
             "prereg_commit": e.get("prereg_commit")}
            for e in by_time if e["kind"] == "f"],
        "reproductions": [e["id"] for e in by_time if e["kind"] == "b"],
        "diagnostics": [e["id"] for e in by_time if e["kind"] == "c"],
        "protocol_events": [e["id"] for e in by_time if e["kind"] == "protocol"],
        "unlogged_reads": [e["id"] for e in by_time if e.get("logged") is False],
        "log_lines_total": n_lines,
        "log_lines_unmapped": sum(1 for i in range(1, n_lines + 1) if mapped.get(i, 0) != 1),
        "aux_log_lines_total": aux_total,
        "results_by_label": {k: res_by_label[k] for k in sorted(res_by_label, key=str)},
    }


def build(reg: dict, logs: dict[str, list[str]]) -> dict:
    for ev in reg.get("events", []):
        if ev.get("kind") != "protocol":
            ev["oos_informed"] = oos_informed(ev)
    reg["log_lines"] = compute_log_lines(reg, logs)
    reg["summary"] = compute_summary(reg, logs)
    return reg


# --------------------------------------------------------------------------- validation
_EVID_PATH = re.compile(r"^(?P<path>[A-Za-z0-9_./-]+?)(?::(?P<rng>[0-9][0-9,\- ]*))?(?:\s+\(.*\))?$")


def check_evidence(item: str, repo: Path, git: Git) -> tuple[bool, str | None]:
    """Return (verifiable, error). local: items are allowed but never count as support."""
    if not isinstance(item, str) or not item.strip():
        return False, "empty evidence item"
    if item.startswith("local:"):
        return False, None
    if item.startswith("commit:"):
        rev = item.split(":", 1)[1].split()[0]
        return (True, None) if git.commit_time(rev) else (False, f"evidence commit {rev} not found")
    if item.startswith("git:"):
        spec = item[4:].split()[0]
        return (True, None) if git.object_exists(spec) else (False, f"evidence object {spec} not in git")
    m = _EVID_PATH.match(item)
    if not m:
        return False, f"unparseable evidence {item!r}"
    path, rng = m.group("path"), m.group("rng")
    if not git.tracked(path):
        return False, f"evidence file {path} is not tracked in git (use local: for untracked files)"
    if rng:
        nums = [int(x) for x in re.findall(r"\d+", rng)]
        n = len((Path(repo) / path).read_text(errors="replace").splitlines())
        if max(nums) > n:
            return False, f"evidence {item!r}: line {max(nums)} beyond end of {path} ({n} lines)"
    return True, None


def validate(reg: dict, repo: Path = ROOT, git: Git | None = None,
             logs: dict[str, list[str]] | None = None) -> list[str]:
    git = git or Git(repo)
    logs = read_logs(repo) if logs is None else logs
    errs: list[str] = []
    E = errs.append

    if reg.get("schema") != SCHEMA:
        E(f"schema must be {SCHEMA!r}")
    for key in ("kinds", "kind_labels", "data_states", "label_rules", "events", "results",
                "log_lines", "summary"):
        if key not in reg:
            E(f"missing top-level key {key!r}")
    if reg.get("kind_labels") not in (None, KIND_LABELS):
        E("kind_labels differ from scripts/provenance.py KIND_LABELS")
    if errs:
        return errs

    events, results = reg["events"], reg["results"]
    ids = [e.get("id") for e in events]
    for d in {i for i in ids if ids.count(i) > 1}:
        E(f"duplicate event id {d}")
    rids = [r.get("id") for r in results]
    for d in {i for i in rids if rids.count(i) > 1}:
        E(f"duplicate result id {d}")
    rset = set(rids)
    log_utc = {OOS_LOG: [log_line_utc(l) for l in logs.get(OOS_LOG, [])]}
    for k in AUX_LOGS:
        log_utc[k] = [log_line_utc(l) for l in logs.get(k, [])]

    for ev in events:
        eid = ev.get("id", "?")
        p = f"event {eid}: "
        if not isinstance(eid, str) or not EVENT_ID_RE.match(eid):
            E(p + "id must match E<2 digits>[letter]")
        for key, typ in (("utc", str), ("time_source", str), ("commit", str), ("kind", str),
                         ("decision", bool), ("family", str), ("summary", str), ("evidence", list),
                         ("oos_log_lines", list), ("touches", list)):
            if not isinstance(ev.get(key), typ):
                E(p + f"field {key!r} missing or not {typ.__name__}")
        if any(not isinstance(ev.get(k), t) for k, t in (("utc", str), ("kind", str), ("commit", str),
                                                          ("evidence", list), ("oos_log_lines", list),
                                                          ("touches", list))):
            continue
        kind = ev["kind"]
        if kind not in KINDS:
            E(p + f"unknown kind {kind!r}")
            continue
        if ev.get("family") not in FAMILIES:
            E(p + f"unknown family {ev.get('family')!r}")
        if not ev.get("summary", "").strip():
            E(p + "empty summary")
        if not str(ev.get("time_source", "")).split(" ")[0] in TIME_SOURCES:
            E(p + f"time_source must start with one of {TIME_SOURCES}")
        if not UTC_RE.match(ev["utc"]):
            E(p + "utc must be YYYY-MM-DDTHH:MM:SSZ")
            continue
        t0 = parse_utc(ev["utc"])
        t1 = None
        if "utc_end" in ev:
            if not isinstance(ev["utc_end"], str) or not UTC_RE.match(ev["utc_end"]):
                E(p + "utc_end must be YYYY-MM-DDTHH:MM:SSZ")
            else:
                t1 = parse_utc(ev["utc_end"])
                if t1 < t0:
                    E(p + "utc_end before utc")
        # data state and decision consistency
        if kind == "protocol":
            if ev.get("decision"):
                E(p + "protocol events read no data and are not decisions")
        else:
            if ev.get("data_state") not in DATA_STATES:
                E(p + f"data_state {ev.get('data_state')!r} not in {DATA_STATES}")
            if ev.get("decision") != (kind in ("d", "e")):
                E(p + "decision must be true exactly for kinds d and e")
            if ev.get("oos_informed") is not None and ev.get("oos_informed") != oos_informed(ev):
                E(p + f"oos_informed is {ev.get('oos_informed')}, recomputed {oos_informed(ev)} (run build)")
            if "oos_informed" not in ev:
                E(p + "oos_informed missing (run build)")
        if kind in ("d", "e"):
            if not str(ev.get("direction", "")).strip():
                E(p + "kinds d and e need a direction")
            if not str(ev.get("printed_text", "")).strip():
                E(p + "kinds d and e need printed_text")
        if "oos_selected" in ev and (not isinstance(ev["oos_selected"], bool) or kind not in ("d", "e")):
            E(p + "oos_selected must be a bool on a kind d or e event")
        if "printed_text" in ev:
            pt = ev["printed_text"]
            if not isinstance(pt, str) or word_count(pt) > MAX_PRINTED_WORDS:
                E(p + f"printed_text must be a string of at most {MAX_PRINTED_WORDS} words")
            elif FORBIDDEN_WORDS.search(pt):
                E(p + "printed_text must not say 'burned'")
        if kind == "a" and ev.get("data_state") not in ("clean", "burned", "test_used"):
            E(p + "a pre-registered evaluation reads clean, burned or test_used data")
        if kind == "f" and ev.get("data_state") not in ("untouched", "partly_read"):
            E(p + "a blind or post-freeze evaluation reads untouched or partly_read data")
        # commits
        commit = ev["commit"]
        role = ev.get("commit_role", "record")
        ct = git.commit_time(commit) if SHA_RE.match(commit) else None
        if ct is None:
            E(p + f"commit {commit!r} not found")
        else:
            if not git.is_ancestor(commit):
                E(p + f"commit {commit} is not an ancestor of HEAD")
            if role == "record" and ct < t0 - RECORD_SLACK:
                E(p + f"recording commit {commit} ({fmt_utc(ct)}) precedes the event ({ev['utc']}); "
                      "set commit_role 'code' or use the commit that records it")
            elif role == "code" and ct > t0:
                E(p + f"code commit {commit} ({fmt_utc(ct)}) is after the event ({ev['utc']})")
            elif role not in ("record", "code"):
                E(p + "commit_role must be 'record' or 'code'")
            if str(ev.get("time_source", "")).startswith("commit") and fmt_utc(ct) != ev["utc"]:
                E(p + f"time_source commit but utc != commit time {fmt_utc(ct)}")
        for key in ("subject_commit",):
            if key in ev and git.commit_time(str(ev[key])) is None:
                E(p + f"{key} {ev[key]!r} not found")
        if kind in ("a", "f") and not ev.get("prereg_commit"):
            E(p + "kinds a and f need prereg_commit (the commit that froze the rule)")
        if ev.get("prereg_commit"):
            pc = git.commit_time(str(ev["prereg_commit"]))
            if pc is None:
                E(p + f"prereg_commit {ev['prereg_commit']!r} not found")
            elif pc > t0 and not ev.get("prereg_commit_after_run"):  # 1 s resolution: same second allowed
                E(p + f"prereg_commit {ev['prereg_commit']} ({fmt_utc(pc)}) is not before the read "
                      f"({ev['utc']}); set prereg_commit_after_run and disclose it")
            elif pc <= t0 and ev.get("prereg_commit_after_run"):
                E(p + "prereg_commit_after_run is set but the commit precedes the read")
        # evidence
        support = 0
        for item in ev["evidence"]:
            ok, err = check_evidence(item, repo, git)
            if err:
                E(p + err)
            support += ok
        if support == 0:
            E(p + "no verifiable evidence (a tracked file, git:<rev>:<path> or commit:<rev>)")
        # log lines
        late = set(ev.get("logged_after_lines", []))
        own = [(OOS_LOG, n) for n in ev["oos_log_lines"]]
        aux = ev.get("aux_log_lines", {})
        if not isinstance(aux, dict) or any(k not in AUX_LOGS for k in aux):
            E(p + f"aux_log_lines keys must be in {AUX_LOGS}")
            aux = {}
        own += [(k, n) for k, ns in aux.items() for n in ns]
        times = []
        for logname, n in own:
            if not isinstance(n, int) or not 1 <= n <= len(log_utc[logname]):
                E(p + f"{logname} line {n} out of range")
                continue
            lt = log_utc[logname][n - 1]
            times.append(lt)
            if lt < t0:
                E(p + f"{logname} line {n} ({fmt_utc(lt)}) is before the event start {ev['utc']}")
            if logname == OOS_LOG and n in late:
                continue
            if t1 is not None and lt > t1:
                E(p + f"{logname} line {n} ({fmt_utc(lt)}) is after utc_end {ev['utc_end']}")
            if t1 is None and lt != t0:
                E(p + f"line {n} ({fmt_utc(lt)}) differs from utc and the event has no utc_end")
        if times and str(ev.get("time_source", "")) == "log" and fmt_utc(min(times)) != ev["utc"]:
            E(p + f"time_source log but utc != earliest log line {fmt_utc(min(times))}")
        for r in ev["touches"]:
            if r not in rset:
                E(p + f"touches unknown result {r!r}")

    # every log line mapped exactly once
    for logname, key in [(OOS_LOG, None)] + [(k, k) for k in AUX_LOGS]:
        cnt = Counter()
        for ev in events:
            ns = ev.get("oos_log_lines", []) if key is None else ev.get("aux_log_lines", {}).get(key, [])
            cnt.update(ns if isinstance(ns, list) else [])
        for i in range(1, len(logs.get(logname, [])) + 1):
            if cnt.get(i, 0) == 0:
                E(f"{logname} line {i} is not mapped to any event")
            elif cnt[i] > 1:
                E(f"{logname} line {i} is mapped to {cnt[i]} events")

    # results
    by_id = {e.get("id"): e for e in events}
    for r in results:
        rid = r.get("id", "?")
        p = f"result {rid}: "
        if not isinstance(rid, str) or not RESULT_ID_RE.match(rid):
            E(p + "id must match R_<lowercase>")
        for key, typ in (("paper", str), ("period", str), ("kind", str), ("label", str),
                         ("label_text", str), ("events", list)):
            if not isinstance(r.get(key), typ):
                E(p + f"field {key!r} missing or not {typ.__name__}")
        if not isinstance(r.get("events"), list):
            continue
        if r.get("period") not in PERIODS:
            E(p + f"period {r.get('period')!r} not in {PERIODS}")
        if r.get("kind") not in RESULT_KINDS:
            E(p + f"kind {r.get('kind')!r} not in {RESULT_KINDS}")
        if r.get("label") not in LABELS:
            E(p + f"label {r.get('label')!r} not in {LABELS}")
        lt = r.get("label_text", "")
        if not str(lt).strip() or FORBIDDEN_WORDS.search(str(lt)):
            E(p + "label_text must be non-empty and must not say 'burned'")
        touching = sorted((e["id"] for e in events if rid in e.get("touches", [])), key=ids.index)
        if sorted(r["events"]) != sorted(touching):
            E(p + f"events {r['events']} differ from the events that touch it {touching}")
        evs = [by_id[i] for i in r["events"] if i in by_id]
        if not evs:
            E(p + "no events")
            continue
        try:
            want = derive_label(r, evs)
        except KeyError as exc:
            E(p + f"cannot derive label ({exc})")
            continue
        if r.get("label") != want:
            E(p + f"label {r.get('label')!r} but label_rules give {want!r}")
        missing = required_flags(evs) - set(r.get("flags", []))
        if missing:
            E(p + f"flags missing {sorted(missing)}")
        if "paper_keys" in r and not (isinstance(r["paper_keys"], list)
                                      and all(isinstance(g, str) for g in r["paper_keys"])):
            E(p + "paper_keys must be a list of glob strings")

    te = reg.get("test_eligibility")
    if te is not None:
        for eid in te.get("events", []):
            if eid not in by_id:
                E(f"test_eligibility cites unknown event {eid}")

    # derived fields
    if not errs:
        if reg["log_lines"] != compute_log_lines(reg, logs):
            E("log_lines differ from a recomputation (run build)")
        if reg["summary"] != compute_summary(reg, logs):
            E("summary differs from a recomputation (run build)")
    return errs


def paper_key_coverage(reg: dict, numbers_path: Path) -> dict:
    """Informational: how many numbers.json keys each result's paper_keys globs match."""
    if not numbers_path.exists():
        return {}
    keys = list(json.loads(numbers_path.read_text()).get("numbers", {}))
    return {r["id"]: sum(len(fnmatch.filter(keys, g)) for g in r.get("paper_keys", []))
            for r in reg.get("results", []) if r.get("paper_keys")}


# --------------------------------------------------------------------------- CLI
def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"provenance: cannot read {path}: {exc}")


def write(path: Path, reg: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", nargs="?", default="check", choices=("check", "build", "summary"))
    ap.add_argument("--registry", default=REGISTRY)
    ap.add_argument("--repo", default=str(ROOT))
    a = ap.parse_args(argv)
    repo = Path(a.repo)
    path = repo / a.registry
    reg = load(path)
    logs = read_logs(repo)
    if a.cmd == "build":
        write(path, build(reg, logs))
    if a.cmd == "summary":
        print(json.dumps(compute_summary(reg, logs), indent=1, ensure_ascii=False))
        return 0
    errs = validate(reg, repo, Git(repo), logs)
    for e in errs:
        print(f"provenance: ERROR {e}", file=sys.stderr)
    if errs:
        print(f"provenance: FAIL ({len(errs)} errors) {path}", file=sys.stderr)
        return 1
    s = reg["summary"]
    cov = paper_key_coverage(reg, repo / "results/paper/numbers.json")
    unmatched = sorted(k for k, v in cov.items() if v == 0)
    print(f"provenance: OK {len(reg['events'])} events, {len(reg['results'])} results, "
          f"{s['log_lines_total']} log lines mapped, {len(s['oos_informed_decisions'])} decisions after an OOS look"
          + (f"; paper_keys with no match in numbers.json: {', '.join(unmatched)}" if unmatched else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
