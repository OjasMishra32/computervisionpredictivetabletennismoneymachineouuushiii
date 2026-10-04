"""Red-team scripts and the v2-safe forward runner: plumbing only. No market data, no held-out read, no network."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(f"_rt_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def fts(tmp_path, monkeypatch):
    m = load("forward_test_safe")
    monkeypatch.setattr(m, "FORWARD_JSON", tmp_path / "forward.json")
    monkeypatch.setattr(m, "REF_TRADES", tmp_path / "v2_forward_trades.parquet")
    monkeypatch.setattr(m, "OUT_JSON", tmp_path / "forward_safe.json")
    return m


def test_v2_safe_differs_from_v2_only_in_net_cap(fts):
    v2p, safe = fts.policies()
    assert safe.net_cap == 50 and v2p.net_cap == 100 and safe.name == "v2_safe_n50"
    assert fts.preconditions(None, real=False)["only_net_cap_differs"]


def test_v2_safe_refuses_before_the_pinned_run(fts):
    pre = fts.preconditions("2026-10-04 11:30:00+00:00", real=True)
    assert any("forward.json does not exist" in p for p in pre["problems"])
    assert any("v2_forward_trades.parquet" in p for p in pre["problems"])


def test_v2_safe_end_must_equal_the_pinned_window(fts):
    fts.FORWARD_JSON.write_text(json.dumps({"window": ["2026-10-03T14:00", "2026-10-04 11:30:31+00:00"]}))
    fts.REF_TRADES.write_bytes(b"x")
    assert any("!=" in p for p in fts.preconditions("2026-10-04 11:30:00+00:00", real=True)["problems"])
    assert any("required" in p for p in fts.preconditions(None, real=True)["problems"])
    assert fts.preconditions("2026-10-04 11:30:31+00:00", real=True)["problems"] == []
    fts.OUT_JSON.write_text("{}")
    assert any("one-shot" in p for p in fts.preconditions("2026-10-04 11:30:31+00:00", real=True)["problems"])


def test_v2_safe_plan_mode_reads_no_data_and_writes_nothing(fts, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fts, "LOG", tmp_path / "forward_peeks.log")
    assert fts.main("2026-10-03T14:00", None, dry=False, plan=True, workers=1) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["plan_only"] and out["real_run_ready"] is False
    assert not (tmp_path / "forward_peeks.log").exists() and not fts.OUT_JSON.exists()


def test_stamp_lag_reproduces_the_published_inference(tmp_path, monkeypatch):
    m = load("redteam_stamp_lag")
    monkeypatch.setattr(m, "OUT", tmp_path / "stamp_lag.json")
    m.main()
    r = json.loads((tmp_path / "stamp_lag.json").read_text())
    assert r["base"]["reproduces_published"]
    lo, hi = r["bootstrap"]["median_L_ci95_s"]
    assert lo <= r["base"]["stamp_lag_median_s"] <= hi
    pp = r["per_point_reading_V1"]
    # the per-point reading cannot fill a correct call at V = 1: the latest reprice precedes the earliest arrival
    assert pp["correct_calls_that_can_fill_at_V1"] == 0
    assert pp["t_reprice_minus_t_bounce_s"]["max"] < pp["earliest_arrival_after_bounce_at_V1_s"]
    # linear in reaction time and network (the inference's own form)
    g = {(x["react_s"], x["net_s"]): x["stamp_lag_median_s"] for x in r["reaction_time"]}
    assert abs((g[(0.25, 0.067)] - g[(0.02, 0.002)]) - (0.23 + 0.065)) < 2e-3


def test_derived_numbers_follow_their_formulas(tmp_path, monkeypatch):
    m = load("redteam_derived")
    monkeypatch.setattr(m, "OUT", tmp_path / "derived.json")
    m.main()
    K = {k: v["value"] for k, v in json.loads((tmp_path / "derived.json").read_text())["keys"].items()}
    fin = json.loads((ROOT / "results/financials/financials.json").read_text())
    vps = fin["cost_assumptions"]["vps_london"]["central"]
    for r in ("pre", "cal"):
        for p in ("is", "oos"):
            assert abs(K[f"cv.{r}.{p}.maxlic"] - (K[f"cv.{r}.{p}.usd"] * 30.42 - vps)) <= 1
    assert abs(K["cv.cal.shift"] - (K["cv.cal.lag"] - 3.0)) < 0.01
    # a stamp lag that covers the cheapest data stack must exceed the break-even lag
    assert K["cv.L_breakeven.oos"] < K["cv.L_for_low.oos"] <= 3.0
    assert K["eng.tp"] <= K["eng.nmiss"]


def test_acceptance_checker_runs_read_only(tmp_path, monkeypatch, capsys):
    m = load("redteam_acceptance")
    monkeypatch.setattr(m, "OUT", tmp_path / "acceptance.json")
    monkeypatch.setattr(sys, "argv", ["redteam_acceptance.py"])
    assert m.main() == 0
    checks = json.loads((tmp_path / "acceptance.json").read_text())["checks"]
    assert checks and all(c["status"] in ("PASS", "FAIL", "WARN", "PENDING", "KNOWN", "NOT RUN") for c in checks)
