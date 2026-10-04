import json
from pathlib import Path

import pytest

import experiment
import probe
import summarize


def test_normalize_server_timestamp_units():
    assert probe.normalize_server_ms("1700000000000") == 1700000000000
    assert probe.normalize_server_ms(1700000000) == 1700000000000
    assert probe.normalize_server_ms(1700000000000000000) == 1700000000000
    assert probe.normalize_server_ms(None) is None


def test_summary_compares_london_and_florida(tmp_path: Path):
    paths = []
    for site, feed, rest in (("london", [10, 20, 30], [40, 50]), ("florida", [50, 60, 70], [90, 100])):
        path = tmp_path / f"probe_{site}.jsonl"
        rows = [{"type": "meta", "phase": "start", "site": site, "at": "start", "token_count": 2,
                 "clock": {"local_minus_ntp_ms": 0}}]
        rows += [{"type": "ws", "site": site, "feed_delay_ms": value, "feed_delay_raw_ms": value,
                  "recv_wall_ns": 1_500_000_000, "server_ts_ms": 1000 + i,
                  "event_type": "book", "asset_id": "a"} for i, value in enumerate(feed)]
        rows += [{"type": "rest", "site": site, "rtt_ms": value} for value in rest]
        rows += [{"type": "meta", "phase": "end", "site": site, "at": "end", "clock": {}}]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        paths.append(path)
    result = summarize.compare(paths)
    assert result["london_improvement_ms"]["feed_latency_ms"]["p50"] == 40
    assert result["london_improvement_ms"]["rest_rtt_ms"]["p50"] == 50
    assert result["paired_arrivals"]["matched_events"] == 3
    assert result["paired_arrivals"]["london_arrival_advantage_ms"]["p50"] == 40
    assert result["paired_arrivals"]["london_first_percent"] == 100
    assert result["paired_arrivals"]["combined_clock_uncertainty_ms"] == 0
    assert result["paired_arrivals"]["conservative_median_lower_bound_ms"] == 40
    assert len(result["paired_arrivals"]["deterministic_sample"]) == 3
    assert "Vultr London" in summarize.dashboard(result)


def test_vultr_create_encodes_cloud_init(monkeypatch):
    seen = {}
    class Response:
        status_code = 201
        def json(self): return {"instance": {"id": "i-1"}}
    def fake(method, url, **kwargs):
        seen.update(kwargs["json"])
        return Response()
    monkeypatch.setattr(experiment.requests, "request", fake)
    assert experiment.Vultr("secret").create("lhr", "vc2-1c-1gb")["id"] == "i-1"
    assert seen["region"] == "lhr" and seen["user_data"] != "#cloud-config"
    assert "secret" not in json.dumps(seen)


def test_experiment_requires_explicit_billable_flag(monkeypatch):
    monkeypatch.setattr("sys.argv", ["experiment.py"])
    with pytest.raises(SystemExit, match="refusing"):
        experiment.main()
