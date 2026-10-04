"""Paper generator fact checks: counts and labels from the experiment registry, executable results first, the risk
table's operated-vs-proposed split, and no phrase-count requirements. Fixtures only (tests/fixtures/paper/); no
market data, no held-out read, no compiler."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/paper"


def load():
    spec = importlib.util.spec_from_file_location("_paper_facts_test", ROOT / "scripts/build_paper.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def bp(monkeypatch):
    m = load()
    monkeypatch.delenv("COURTSIDE_STRICT", raising=False)
    monkeypatch.setattr(m, "REGISTRY", str(ROOT / "tests/fixtures/paper/__absent__.json"))
    monkeypatch.setattr(m, "CAUSAL_POINTS", str(ROOT / "tests/fixtures/paper/__absent__.json"))
    return m


TEMPLATE = (ROOT / "docs/paper/note.tex.j2").read_text()


def numbers(**extra):
    return {"numbers": {k: {"value": str(v), "raw": v} for k, v in extra.items()}, "registry": None}


# ------------------------------------------------------------------ labels and counts that the evidence does not support
def test_burned_is_never_printed_and_the_message_names_figure_or_text(bp):
    r = bp.fact_checks("plain text", TEMPLATE, numbers(), "Equity curve: In-sample, Burned OOS")
    assert any("figure text" in f for f in r["fail"])
    r = bp.fact_checks("the OOS is burned", TEMPLATE, numbers(), "the OOS is burned")
    assert any("paper text" in f for f in r["fail"])
    assert not bp.fact_checks("x", TEMPLATE, numbers(), "OOS, non-blind")["fail"]


def test_log_line_counts_and_invented_counts_fail(bp):
    r = bp.fact_checks("x", TEMPLATE, numbers(**{"peeks.n": 111}), "")
    assert any("log-line or invented counts" in f for f in r["fail"])
    r = bp.fact_checks("x", TEMPLATE, numbers(**{"peeks.rule_changes": 2, "t0.dev.n": 13}), "")
    assert any("peeks.rule_changes" in f for f in r["fail"])
    r = bp.fact_checks("x", TEMPLATE, numbers(), "we logged 111 reads of held-out data")
    assert any("log lines is printed as reads" in f for f in r["fail"])
    r = bp.fact_checks("x", TEMPLATE, numbers(), "this is the all-points version of the book")
    assert any("unsupported label" in f for f in r["fail"])


def test_no_check_demands_a_phrase_or_a_phrase_count(bp):
    # the old required phrases ('not ex ante', 'post hoc' x3, 'assumed feed latency' x3) are absent here: no failure
    r = bp.fact_checks("plain", TEMPLATE, numbers(), "a paper without any of the formerly required phrases")
    assert r["fail"] == []
    src = (ROOT / "scripts/build_paper.py").read_text()
    assert "'not ex ante' missing" not in src and "post_hoc_count_main" not in src and "cv_label_count_main" not in src


def test_builder_no_longer_counts_log_lines_or_deviation_headings(bp):
    src = (ROOT / "scripts/build_paper.py").read_text()
    assert '"peeks.n"' not in src and "rule_changes_after_a_look" not in src and '"t0.dev.n"' not in src
    assert "peeks.json" not in src.split("def write_numbers", 1)[1].split("def render_tex", 1)[0].replace(
        '(OUT / "peeks.json").unlink(missing_ok=True)', "")
    for bad in ("V('peeks.", "V('t0.dev", "rule_changes", "burned", "peeks_late"):
        assert bad not in TEMPLATE, bad


# ------------------------------------------------------------------ executable results lead every profit claim
def test_real_template_puts_an_executable_result_first(bp):
    for a, b in ((r"\begin{csabstract}", r"\end{csabstract}"), (r"\label{tab:head}", r"\end{tabular*}")):
        order = bp.profit_order(TEMPLATE, a, b)
        assert order and order[0][1] == "executable", order[:3]
    r = bp.fact_checks("x", TEMPLATE, numbers(), "")
    assert not [f for f in r["fail"] if "first profit number" in f]


def test_a_benchmark_leading_the_abstract_fails(bp):
    bad = TEMPLATE.replace(r"\begin{csabstract}", r"\begin{csabstract} v2 Sharpe << V('v2.is.sr') >>.", 1)
    r = bp.fact_checks("x", bad, numbers(), "")
    assert any("abstract: the first profit number is v2.is.sr" in f for f in r["fail"])


def test_registry_kinds_override_the_prefix_map(bp):
    assert bp.key_kind("copier.oos.c") == "executable"
    assert bp.key_kind("v2.oos.sr") == "others_fills"
    assert bp.key_kind("sc.pre.oos.v05.usd") == "conditional"
    assert bp.key_kind("v2.oos.sr", [("v2.oos.*", "event_study")]) == "event_study"


# ------------------------------------------------------------------ the experiment registry is the only source of counts
def test_missing_registry_is_tolerated_only_outside_strict_mode(bp, monkeypatch):
    assert bp.load_registry() is None
    monkeypatch.setenv("COURTSIDE_STRICT", "1")
    with pytest.raises(KeyError, match="strict"):
        bp.load_registry()
    assert any("missing (strict mode)" in f for f in bp.fact_checks("x", TEMPLATE, numbers(), "")["fail"])


def test_registry_counts_sentences_and_labels(bp, monkeypatch):
    monkeypatch.setattr(bp, "REGISTRY", str(FIX / "experiments.json"))
    N, extra = bp.Registry(), {}
    bp.collect_registry(N, extra)
    S = json.loads((FIX / "experiments.json").read_text())["summary"]
    assert N.raw("reg.n_decisions") == len(S["oos_informed_decisions"]) == 3
    assert N.raw("reg.n_decisions.v2") == 2 and N.raw("reg.n_decisions.cv") == 1
    assert N.raw("reg.n_fixes") == 1 and N.raw("reg.n_events") == sum(S["n_events_by_kind"].values())
    assert N.raw("reg.n_prereg") == 10 and N.raw("reg.n_repro") == 11
    assert N.d["reg.n_decisions"]["source"].startswith(str(FIX / "experiments.json") + "::summary.")
    reg = extra["registry"]
    assert reg["summary_sha256"] == bp.summary_sha(S)
    assert [r["id"] for r in reg["labels"]] == ["R_v2_is", "R_v2_oos", "R_cv_table2_pre", "R_cv_table2_post"]
    nums = {"numbers": {k: {"value": v["value"], "raw": v["raw"]} for k, v in N.d.items()},
            "registry": {"summary_sha256": reg["summary_sha256"]}}
    # a paper that prints every sentence (without its final period) and every label passes
    tex = " ".join(bp.tex(e["printed_text"].rstrip(".")) for e in reg["decisions"] + reg["fixes"])
    tex += " " + " ".join(bp.tex(r["label_text"]) for r in reg["labels"])
    ok = bp.fact_checks(tex, TEMPLATE, nums, "")
    assert ok["fail"] == [] and ok["registry_present"]
    # a missing sentence, a missing label, a stale summary and a wrong count each fail
    r = bp.fact_checks(tex.replace(bp.tex(reg["decisions"][0]["printed_text"].rstrip(".")), ""), TEMPLATE, nums, "")
    assert any("printed_text is not in the paper" in f and "F01" in f for f in r["fail"])
    r = bp.fact_checks(tex.replace(bp.tex(reg["labels"][1]["label_text"]), ""), TEMPLATE, nums, "")
    assert any("R_v2_oos" in f for f in r["fail"])
    stale = dict(nums, registry={"summary_sha256": "0" * 64})
    assert any("different registry summary" in f for f in bp.fact_checks(tex, TEMPLATE, stale, "")["fail"])
    wrong = json.loads(json.dumps(nums))
    wrong["numbers"]["reg.n_decisions"]["raw"] = 2
    assert any("reg.n_decisions printed 2" in f for f in bp.fact_checks(tex, TEMPLATE, wrong, "")["fail"])


def test_unmapped_log_lines_and_missing_printed_text_fail(bp, monkeypatch, tmp_path):
    R = json.loads((FIX / "experiments.json").read_text())
    R["summary"]["log_lines_unmapped"] = 3
    p = tmp_path / "experiments.json"
    p.write_text(json.dumps(R))
    monkeypatch.setattr(bp, "REGISTRY", str(p))
    assert any("map to no event" in f for f in bp.fact_checks("x", TEMPLATE, numbers(), "")["fail"])
    R["summary"]["oos_informed_decisions"][0]["printed_text"] = " "
    p.write_text(json.dumps(R))
    with pytest.raises(KeyError, match="printed_text"):
        bp.collect_registry(bp.Registry(), {})


# ------------------------------------------------------------------ risk table: operated in the backtest vs proposed
def _risk_registry(bp):
    N = bp.Registry()
    for k, v in (("risk.order_usd", "$1,000"), ("risk.netcap", "100"), ("risk.zone", "0.05–0.95"), ("risk.matchcap", "$3,000"),
                 ("risk.daily_stop", "$1,000"), ("pol.trail_half", "0.3"), ("pol.dd_stop", "5%"), ("risk.feed_stale", "2"),
                 ("risk.vision_stale", "1"), ("wcap.W", "$1,000")):
        N.add(k, v, v, "test")
    return N


def test_risk_table_separates_operated_from_proposed_with_code_evidence(bp):
    rows = bp.risk_controls(_risk_registry(bp), None)
    by = {r["control"].split()[0]: r for r in rows}
    assert any(r["backtest"].startswith("operated") for r in rows)
    halt = next(r for r in rows if "false CV call" in r["control"])
    assert halt["backtest"].startswith("not run") and halt["deploy"] == "proposed"
    stop = next(r for r in rows if "daily loss stop" in r["control"])
    assert "never fires" in stop["backtest"] and stop["deploy"] == "engine code"
    assert by["Trailing"]["deploy"] == "proposed"
    # once a causal CV block with the stated halts exists, the halts are reported as operated there
    rows_h = bp.risk_controls(_risk_registry(bp), {"halted": True})
    assert next(r for r in rows_h if "false CV call" in r["control"])["backtest"].startswith("operated")


def test_an_operated_claim_without_code_evidence_stops_the_build(bp, monkeypatch, tmp_path):
    for rel in ("research/v2/sizing/engine.py", "src/v2.py", "src/tier0.py", "engine/risk/limits.py", "docs/RISK.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    monkeypatch.setattr(bp, "ROOT", tmp_path)
    bp.risk_controls(_risk_registry(bp), None)                 # the real code carries the evidence
    t = tmp_path / "src/tier0.py"
    t.write_text(t.read_text().replace("net_cap: float = 100.0", "net_cap: float = 1e9"))
    with pytest.raises(KeyError, match="cv_caps"):
        bp.risk_controls(_risk_registry(bp), None)


# ------------------------------------------------------------------ the executable rows guard their sentences
def test_executable_rows_stop_the_build_if_the_loss_turns_into_a_profit(bp, monkeypatch):
    st = json.loads((ROOT / bp.STRICT).read_text())   # the corrected producer (results/v2/strict_causal.json)
    st["copier"]["central"]["IS"]["c_share"] = 0.5      # a copier that earned would contradict 'loses'
    st["copier"]["central"]["IS"]["usd_day"] = 5.0
    real_j = bp.J

    def fake(rel):
        return st if rel == bp.STRICT else real_j(rel)
    monkeypatch.setattr(bp, "J", fake)
    with pytest.raises(KeyError, match="copier loses"):
        bp.collect_executable(_risk_registry(bp), {})


def test_copier_rows_come_from_the_corrected_producer(bp):
    N = _risk_registry(bp)
    extra: dict = {}
    bp.collect_executable(N, extra)
    st = json.loads((ROOT / bp.STRICT).read_text())
    for per, P in (("is", "IS"), ("oos", "OOS")):
        assert N.raw(f"copier.{per}.c") == st["copier"]["central"][P]["c_share"]
        assert N.raw(f"copier.{per}.usd") == st["copier"]["central"][P]["usd_day"]
        assert N.d[f"copier.{per}.c"]["source"].startswith(bp.STRICT)
    assert extra["copier_oos_ci_spans0"] == (st["copier"]["central"]["OOS"]["c_share_ci95"][0] < 0
                                             < st["copier"]["central"]["OOS"]["c_share_ci95"][1])


# ------------------------------------------------------------------ the real template renders every new slot
def test_template_renders_registry_causal_block_and_risk_table(bp, monkeypatch, tmp_path):
    monkeypatch.setattr(bp, "REGISTRY", str(FIX / "experiments.json"))
    monkeypatch.setattr(bp, "CAUSAL_POINTS", str(FIX / "causal_points.json"))
    paper = tmp_path / "paper"
    paper.mkdir()
    shutil.copy(ROOT / "docs/paper/note.tex.j2", paper / "note.tex.j2")
    monkeypatch.setattr(bp, "PAPER", paper)
    N, extra = bp.collect()
    # the printed reading is the producer's own frozen primary cell; the false-call halt is not simulated there
    assert extra["causal"]["reading"] == "tournament_L2.0" and not extra["causal"]["halted"]
    assert extra["causal"]["stop_fired"] == 0
    tex = bp.render_tex(N, extra).read_text()
    assert r"\textbf{Causal selection}" in tex and "stated halts on" not in tex
    assert tex.index(r"\textbf{Executable}") < tex.index(r"\textbf{Causal selection}") < tex.index(r"\textbf{Benchmark: the fast tier")
    assert r"\label{tab:risk}" in tex and "causal CV: never fired" in tex and "not run (wrong calls kept)" in tex
    assert "burned" not in tex.lower()
    nums = {"numbers": {k: {"value": v["value"], "raw": v["raw"]} for k, v in N.d.items()},
            "registry": {"summary_sha256": extra["registry"]["summary_sha256"]}}
    r = bp.fact_checks(tex, (paper / "note.tex.j2").read_text(), nums, "rendered text without the forbidden word")
    assert r["fail"] == [], r["fail"]
