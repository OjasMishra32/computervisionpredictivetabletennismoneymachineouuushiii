"""Sponsor evidence: check our teammates' sponsor results and put the measured network legs into the 3 s budget.

Three parts, all read-only, writing only results/sponsors/evidence.json:

1. Vultr (sponsors/vultr, Yoan). Every number in the README is checked against out/summary.json, the
   internal arithmetic of summary.json is re-done (improvements, the clock-bound subtraction, the start skew),
   the run manifest is checked, and sponsors/vultr/test_vultr.py is run. The raw probe JSONL files are gitignored,
   so the paired-arrival statistics themselves cannot be recomputed here; the file says so.
2. Snowflake (sponsors/snowflake, Ian). Ian's SQL (queries.sql) is re-run on in-memory DuckDB, his offline route,
   against the CURRENT results/paper/numbers.json, using his own check.compare(). Nothing is written into
   sponsors/snowflake/out/. Keys whose paper value moved since his committed run are listed.
3. The 3 s budget. results/e2e/summary.json adds a 1 s simulated feed, our measured pipeline, a network one-way
   leg (half of a keep-alive GET /time round trip measured from the Florida laptop during that run) and the
   venue's 1 s taker hold. Here the network leg is swapped for the Vultr probe's measured public REST round trip
   (London server and Florida laptop, p50 / p90 / p99), both as half the round trip (the paper's convention) and
   as the full round trip (conservative), and the margin under 3,000 ms is recomputed.

These are public-feed and public REST latencies. No order was signed or sent anywhere, so authenticated order
latency and the venue's matching time are NOT measured by anything here.

Run:
    .venv/bin/python scripts/sponsor_evidence.py
Parts 1 (tests) and 2 need paramiko==5.0.0 and duckdb==1.5.6 (pinned in sponsors/*/requirements.txt), which the
main .venv does not carry; put them on PYTHONPATH, e.g. `uv pip install --target /tmp/sp duckdb==1.5.6
paramiko==5.0.0 tabulate==0.10.0` then `PYTHONPATH=/tmp/sp .venv/bin/python scripts/sponsor_evidence.py`.
Without them those parts are recorded as skipped and the rest still runs.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True   # do not leave __pycache__ in the teammates' folders

import hashlib
import json
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VULTR = ROOT / "sponsors/vultr"
SNOW = ROOT / "sponsors/snowflake"
NUMBERS = ROOT / "results/paper/numbers.json"
E2E = ROOT / "results/e2e/summary.json"
DECAY = ROOT / "results/decay/decay.json"
OUT = ROOT / "results/sponsors/evidence.json"
REQUIREMENT_MS = 3000.0


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def load(p: Path):
    return json.loads(p.read_text())


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def r(x, nd=3):
    return None if x is None else round(float(x), nd)


def comma(x: float, nd: int = 0) -> str:
    return f"{x:,.{nd}f}"


# ---------------------------------------------------------------------------------------------- 1. Vultr

def chrony_field(raw: str, name: str) -> float | None:
    m = re.search(rf"^{re.escape(name)}\s*:\s*([+-]?[0-9.]+) seconds", raw or "", re.M)
    return float(m.group(1)) * 1000 if m else None


def vultr_part() -> dict:
    S = load(VULTR / "out/summary.json")
    M = load(VULTR / "out/run_manifest.json")
    readme = (VULTR / "README.md").read_text()
    deploy = (VULTR / "deploy.md").read_text()
    dash = (VULTR / "out/dashboard.html").read_text()
    lon, fl, pa = S["sites"]["london"], S["sites"]["florida"], S["paired_arrivals"]
    src = "sponsors/vultr/out/summary.json::"

    def dur_min(site):
        a, b = (datetime.fromisoformat(site[k]) for k in ("started_at", "ended_at"))
        return (b - a).total_seconds() / 60

    # (claim, text that must appear in README, value from the evidence file, its key, rounding the README uses)
    claims = [
        ("30-minute run, London", "30-minute run", dur_min(lon), src + "sites.london.{started_at,ended_at}", 0),
        ("30-minute run, Florida", "30-minute run", dur_min(fl), src + "sites.florida.{started_at,ended_at}", 0),
        ("370 tokens, London", "370 tennis outcome tokens", lon["token_count"], src + "sites.london.token_count", 0),
        ("370 tokens, Florida", "370 tennis outcome tokens", fl["token_count"], src + "sites.florida.token_count", 0),
        ("probe-start skew 38.3 ms", "38.3 ms probe-start", S["observed_probe_start_skew_ms"],
         src + "observed_probe_start_skew_ms", 1),
        ("zero capture errors", "zero capture errors", lon["errors"] + fl["errors"],
         src + "sites.{london,florida}.errors", 0),
        ("287,577 matched updates", "287,577", pa["matched_events"], src + "paired_arrivals.matched_events", 0),
        ("London first 99.74%", "99.74%", pa["london_first_percent"], src + "paired_arrivals.london_first_percent", 2),
        ("median advantage 70.2 ms", "70.2 ms", pa["london_arrival_advantage_ms"]["p50"],
         src + "paired_arrivals.london_arrival_advantage_ms.p50", 1),
        ("p90 advantage 162.2 ms", "162.2 ms", pa["london_arrival_advantage_ms"]["p90"],
         src + "paired_arrivals.london_arrival_advantage_ms.p90", 1),
        ("clock bound 30.3 ms", "30.3 ms", pa["combined_clock_uncertainty_ms"],
         src + "paired_arrivals.combined_clock_uncertainty_ms", 1),
        ("conservative median 39.9 ms", "39.9 ms", pa["conservative_median_lower_bound_ms"],
         src + "paired_arrivals.conservative_median_lower_bound_ms", 1),
        ("REST RTT London 69.7 ms", "69.7 ms", lon["rest_rtt_ms"]["p50"], src + "sites.london.rest_rtt_ms.p50", 1),
        ("REST RTT Florida 184.4 ms", "184.4 ms", fl["rest_rtt_ms"]["p50"], src + "sites.florida.rest_rtt_ms.p50", 1),
        ("REST improvement 114.7 ms", "114.7 ms", S["london_improvement_ms"]["rest_rtt_ms"]["p50"],
         src + "london_improvement_ms.rest_rtt_ms.p50", 1),
    ]
    expected = {"30-minute run, London": 30, "30-minute run, Florida": 30, "370 tokens, London": 370,
                "370 tokens, Florida": 370, "zero capture errors": 0, "287,577 matched updates": 287577}
    rows = []
    for name, text, value, key, nd in claims:
        shown = round(float(value), nd)
        want = expected.get(name)
        if want is None:   # the number is inside the README text
            want = float(re.search(r"[0-9][0-9,]*\.?[0-9]*", text).group(0).replace(",", ""))
        rows.append({"claim": name, "readme_text": text, "in_readme": text in readme, "value": r(value, 3),
                     "source": key, "rounds_to_claim": abs(shown - want) < 1e-9})
    tail = {"claim": "p99 has multi-second Florida tail stalls", "in_readme": "multi-second Florida tail" in readme,
            "value": fl["feed_latency_ms"]["p99"], "source": src + "sites.florida.feed_latency_ms.p99",
            "rounds_to_claim": fl["feed_latency_ms"]["p99"] >= 1000}
    rows.append(tail)
    dash_checks = {s: s in dash for s in ("70.2 ms", "99.74%", "287,577", "30.3 ms", "39.9 ms")}

    # the arithmetic inside summary.json, redone
    starts = [datetime.fromisoformat(s["started_at"]).timestamp() for s in (lon, fl)]
    arith = {
        "start_skew_ms": {"recomputed": r((max(starts) - min(starts)) * 1000), "stored": S["observed_probe_start_skew_ms"]},
        "conservative_median_ms": {"recomputed": r(pa["london_arrival_advantage_ms"]["p50"]
                                                   - pa["combined_clock_uncertainty_ms"]),
                                   "stored": pa["conservative_median_lower_bound_ms"]},
        "combined_bound_ms": {"recomputed": r(max(fl["clock_start"].get("uncertainty_ms") or 0,
                                                  fl["clock_end"].get("uncertainty_ms") or 0)
                                              + max(lon["clock_start"].get("uncertainty_ms") or 0,
                                                    lon["clock_end"].get("uncertainty_ms") or 0)),
                              "stored": pa["combined_clock_uncertainty_ms"]},
    }
    for metric in ("feed_latency_ms", "rest_rtt_ms"):
        for p in ("p50", "p90", "p99"):
            arith[f"improvement.{metric}.{p}"] = {"recomputed": r(fl[metric][p] - lon[metric][p]),
                                                 "stored": S["london_improvement_ms"][metric][p]}
    sample_ok = all(abs((x["florida_delay_ms"] - x["london_delay_ms"]) - x["london_advantage_ms"]) < 0.01
                    for x in pa["deterministic_sample"])
    for v in arith.values():
        v["ok"] = abs(v["recomputed"] - v["stored"]) < 0.002

    # London's own clock bound, which the 30.3 ms figure leaves out (chrony: max error ~ root delay / 2 + dispersion)
    lon_bound = {}
    for when in ("clock_start", "clock_end"):
        raw = lon[when].get("raw", "")
        rd, disp = chrony_field(raw, "Root delay"), chrony_field(raw, "Root dispersion")
        lon_bound[when] = {"root_delay_ms": r(rd), "root_dispersion_ms": r(disp),
                           "max_error_ms": r(rd / 2 + disp) if None not in (rd, disp) else None}
    strict_lb = pa["london_arrival_advantage_ms"]["p50"] - pa["combined_clock_uncertainty_ms"] \
        - lon_bound["clock_end"]["max_error_ms"]

    # run manifest vs the committed runner
    exp_src = (VULTR / "experiment.py").read_text()
    literal = re.search(r"manifest = \{(.*?)\}\n", exp_src, re.S)
    runner_keys = set(re.findall(r'manifest\["([a-z_]+)"\]', exp_src))
    runner_keys |= set(re.findall(r'"([a-z_]+)":', literal.group(1))) if literal else set()
    runner_keys = sorted(runner_keys - {"delete_error"})   # written only when the teardown fails
    manifest_keys = sorted(M)

    raw_files = sorted(p.name for p in (VULTR / "out").glob("probe_*.jsonl"))
    smoke = {}
    for p in sorted((VULTR / "out").glob("probe_*.json")):
        d = load(p)
        smoke[d.get("label", p.stem)] = {
            "n": d.get("n"),
            "clob_rest_ttfb_ms": {k: r(v, 1) for k, v in d["https"]["clob_rest"]["ttfb"].items()},
            "ws_ping_pong_ms": {k: r(v, 1) for k, v in d["ws"]["market"]["ping_pong"].items()},
            "source": f"{rel(p)}::https.clob_rest.ttfb, ws.market.ping_pong"}

    # unit tests
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        t = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                            str(VULTR / "test_vultr.py")], cwd=ROOT, env=env, text=True, capture_output=True,
                           timeout=300)
        last = [ln for ln in t.stdout.strip().splitlines() if ln.strip()][-1:] or [t.stderr.strip()[-300:]]
        tests = {"command": "python -m pytest -p no:cacheprovider -q sponsors/vultr/test_vultr.py",
                 "returncode": t.returncode, "summary": last[0]}
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        tests = {"returncode": None, "summary": f"not run: {type(exc).__name__}"}

    return {
        "readme_claims": rows,
        "readme_claims_ok": sum(x["in_readme"] and x["rounds_to_claim"] for x in rows),
        "readme_claims_n": len(rows),
        "dashboard_shows": dash_checks,
        "summary_arithmetic": arith,
        "summary_arithmetic_ok": all(v["ok"] for v in arith.values()) and sample_ok,
        "deterministic_sample_consistent": sample_ok,
        "deterministic_sample_note": (
            "all 10 sample pairs are 'book' snapshots whose exchange stamp is hours before the run (london_delay_ms "
            f"~{pa['deterministic_sample'][0]['london_delay_ms'] / 3.6e6:.2f} h): they are re-sent on subscribe, so "
            f"their {pa['deterministic_sample'][0]['london_advantage_ms']} ms 'advantage' is the gap between the two "
            "sites' subscriptions, not network latency. summarize.py filters such rows out of the per-site feed "
            "percentiles (-1 s < delay < 60 s) but not out of the paired statistics; with ~370 tokens per "
            "(re)subscription against 287,577 pairs they can only touch the far tail, not the median."),
        "clock": {
            "florida_sntp_local_minus_ntp_ms": {"start": fl["clock_start"]["local_minus_ntp_ms"],
                                                "end": fl["clock_end"]["local_minus_ntp_ms"]},
            "florida_offset_moved_ms": r(fl["clock_end"]["local_minus_ntp_ms"] - fl["clock_start"]["local_minus_ntp_ms"]),
            "florida_sntp_uncertainty_ms": {"start": fl["clock_start"]["uncertainty_ms"],
                                            "end": fl["clock_end"]["uncertainty_ms"]},
            "london_chrony": lon_bound,
            "combined_bound_used_by_summary_ms": pa["combined_clock_uncertainty_ms"],
            "median_lower_bound_incl_london_end_bound_ms": r(strict_lb),
            "note": ("The 30.3 ms 'combined' bound is Florida's sntp uncertainty alone; London's chrony gives no "
                     "uncertainty_ms field, so it counts as 0. Taking London's end-of-run chrony bound (root delay/2 + "
                     "root dispersion) as well leaves the stricter median lower bound above. London's start-of-run "
                     "reading was taken while chrony was still settling (reference time 18 s before the start, "
                     "skew 1,000,000 ppm, root dispersion "
                     f"{lon_bound['clock_start']['root_dispersion_ms']:,.0f} ms), so it bounds nothing. Florida's "
                     "offset moved more over the run than its own sntp uncertainty and is interpolated linearly. The "
                     "REST round trips are timed with perf_counter (one clock), so they need no clock correction."),
        },
        "rest_rtt_method": ("probe.py rest_loop: requests.get(clob.polymarket.com/time) every 2 s with no Session, so "
                            "every sample opens a new TCP + TLS connection (a cold request); timed with "
                            "time.perf_counter_ns. results/e2e's network leg is a keep-alive GET /time."),
        "run_manifest": {"instance_deleted": M.get("instance_deleted"), "region": M.get("region"),
                         "plan": M.get("plan"), "deleted_at": M.get("deleted_at"),
                         "deploy_md_says_deleted_04_47_31": "04:47:31" in deploy,
                         "keys_in_manifest_not_written_by_committed_runner": sorted(set(manifest_keys) - set(runner_keys)),
                         "keys_committed_runner_writes_but_manifest_lacks": sorted(set(runner_keys) - set(manifest_keys))},
        "raw_probe_files_present": raw_files,
        "raw_probe_note": ("probe_london.jsonl / probe_florida.jsonl are gitignored (sponsors/vultr/.gitignore) and are "
                           "not in this checkout, so matched-event counts and percentiles are checked against "
                           "summary.json only, not recomputed from rows."),
        "smoke_probes_secondary": smoke,
        "smoke_note": ("Earlier 30-sample smoke runs from Vultr Amsterdam / Newark / Los Angeles. The script that wrote "
                       "this format is not in the repo; listed for context only and not used in the budget."),
        "tests": tests,
    }


# ---------------------------------------------------------------------------------------------- 2. Snowflake

def snowflake_part() -> dict:
    committed = load(SNOW / "out/checks_offline.json")
    committed_sf = load(SNOW / "out/checks.json")
    sha_before = sha256(NUMBERS)
    cur = load(NUMBERS)
    head_rev = (git("rev-parse", "HEAD") or "").strip() or None
    head_txt = git("show", "HEAD:results/paper/numbers.json")
    head = json.loads(head_txt)["numbers"] if head_txt else {}
    cn = cur["numbers"]
    changed_since_head = sorted(k for k in cn if k in head and (cn[k].get("value") != head[k].get("value")
                                                                or cn[k].get("raw") != head[k].get("raw")))
    out = {
        "numbers_json": {"path": rel(NUMBERS), "generated_utc": cur.get("generated_utc"), "n_keys": len(cn),
                         "sha256": sha_before, "git_head": head_rev, "n_keys_at_head": len(head),
                         "added_since_head": len([k for k in cn if k not in head]),
                         "removed_since_head": len([k for k in head if k not in cn]),
                         "changed_since_head": changed_since_head},
        "committed_runs": {"duckdb": {"reproduced": committed["reproduced"], "checked": committed["checked"],
                                      "source": "sponsors/snowflake/out/checks_offline.json::reproduced,checked"},
                           "snowflake": {"reproduced": committed_sf["reproduced"], "checked": committed_sf["checked"],
                                         "source": "sponsors/snowflake/out/checks.json::reproduced,checked"}},
    }
    try:
        import duckdb  # noqa: F401
        sys.path.insert(0, str(SNOW))
        import check  # Ian's module: same SQL, same comparison rule
        import common
    except ImportError as exc:
        out["recheck"] = {"status": "skipped", "reason": f"{exc}; install duckdb==1.5.6 (see module docstring)"}
        return out
    blocks = common.read_queries()
    res = check.run_duckdb(blocks)
    cmp = check.compare(res)
    sha_after = sha256(NUMBERS)
    old = {x["paper_key"]: x for x in committed["rows"]}
    moved, failing = [], []
    for row in cmp.itertuples(index=False):
        o = old.get(row.paper_key)
        src_now = None if row.source_value is None or row.source_value != row.source_value else float(row.source_value)
        src_then = None if o is None else o.get("source_value")
        if o is None or o.get("printed") != row.printed or (
                (src_now is None) != (src_then is None) or (src_now is not None and abs(src_now - src_then) > 1e-6)):
            moved.append({"paper_key": row.paper_key, "printed_then": None if o is None else o.get("printed"),
                          "printed_now": row.printed, "source_then": src_then, "source_now": src_now})
        if not row.ok:
            failing.append({"paper_key": row.paper_key, "printed": row.printed, "source_value": src_now,
                            "sql_value": float(row.sql_value)})
    kinds = cmp.groupby("kind").ok.agg(["sum", "count"])
    out["recheck"] = {
        "status": "ran", "engine": f"DuckDB {sys.modules['duckdb'].__version__} (Ian's offline route, check.run_duckdb)",
        "rule": "check.compare(): SQL value within the paper source value's precision (2 dp max), or rounds to the "
                "printed number",
        "reproduced": int(cmp.ok.sum()), "checked": int(len(cmp)),
        "recomputed_ok": int(kinds.loc["recomputed", "sum"]), "recomputed_n": int(kinds.loc["recomputed", "count"]),
        "lookup_ok": int(kinds.loc["lookup", "sum"]), "lookup_n": int(kinds.loc["lookup", "count"]),
        "matched_on_printed_only": sorted(cmp[cmp.match == "printed"].paper_key.tolist()),
        "failing": failing,
        "keys_moved_since_committed_run": moved,
        "numbers_json_unchanged_during_check": sha_after == sha_before,
        "share_of_paper_keys_checked": r(len(cmp) / len(cn), 4),
    }
    return out


# ---------------------------------------------------------------------------------------------- 3. Budget

def budget_part(vultr_summary: dict) -> dict:
    E = load(E2E)
    B = E["budget_with_1s_simulated_feed"]
    feed, venue = B["feed_simulated_ms"], B["venue_delay_ms"]["p50"]
    ours = B["ours_capture_to_order_ready_ms"]
    net_paper = B["network_one_way_ms"]
    rtt_paper = E["rtt_at_orders_ms"]
    lon = vultr_summary["sites"]["london"]["rest_rtt_ms"]
    fl = vultr_summary["sites"]["florida"]["rest_rtt_ms"]
    e2e = "results/e2e/summary.json::"
    vs = "sponsors/vultr/out/summary.json::"

    legs = {
        "paper_florida_keepalive_half_rtt": ({p: net_paper[p] for p in ("p50", "p90", "p99")},
                                             e2e + "budget_with_1s_simulated_feed.network_one_way_ms",
                                             "paper's leg: RTT/2 of keep-alive GET /time, Florida laptop, e2e run"),
        "vultr_london_cold_half_rtt": ({p: lon[p] / 2 for p in lon}, vs + "sites.london.rest_rtt_ms / 2",
                                       "Vultr London server, cold public GET /time, half the round trip"),
        "vultr_london_cold_full_rtt": (dict(lon), vs + "sites.london.rest_rtt_ms",
                                       "Vultr London server, cold public GET /time, full round trip"),
        "vultr_florida_cold_half_rtt": ({p: fl[p] / 2 for p in fl}, vs + "sites.florida.rest_rtt_ms / 2",
                                        "Florida laptop, cold public GET /time, half the round trip"),
        "vultr_florida_cold_full_rtt": (dict(fl), vs + "sites.florida.rest_rtt_ms",
                                        "Florida laptop, cold public GET /time, full round trip"),
    }
    scen = {}
    for name, (leg, src, what) in legs.items():
        scen[name] = {"what": what, "network_source": src}
        for p in ("p50", "p90", "p99"):
            total = feed + ours[p] + leg[p] + venue
            scen[name][p] = {"network_ms": r(leg[p]), "ours_ms": ours[p], "total_ms": r(total),
                             "margin_to_3s_ms": r(REQUIREMENT_MS - total),
                             "max_feed_delay_for_3s_ms": r(REQUIREMENT_MS - (ours[p] + leg[p] + venue))}
    worst = min(((n, p, s[p]["margin_to_3s_ms"]) for n, s in scen.items() for p in ("p50", "p90", "p99")),
                key=lambda x: x[2])
    li = load(DECAY)["latency_inputs"]
    return {
        "method": ("total = 1,000 ms simulated feed + our pipeline (capture -> order ready) + network leg + 1,000 ms "
                   "venue taker hold; at p50 each leg's p50, at p90 / p99 each leg's p90 / p99 added (stacking tails "
                   "this way is conservative). Margin = 3,000 - total. Only the network leg changes between rows."),
        "inputs": {"feed_simulated_ms": feed, "venue_delay_ms": venue, "ours_ms": {p: ours[p] for p in ("p50", "p90", "p99")},
                   "requirement_ms": B["requirement_ms"],
                   "sources": [e2e + "budget_with_1s_simulated_feed.{feed_simulated_ms,venue_delay_ms.p50,"
                               "ours_capture_to_order_ready_ms,requirement_ms}"]},
        "paper_as_printed": {"total_p50_ms": B["total_ms"]["p50"], "margin_p50_ms": B["margin_to_requirement_ms"]["p50"],
                             "network_p50_ms": net_paper["p50"], "rtt_at_orders_p50_ms": rtt_paper["p50"],
                             "note": ("the paper's total is the median of 24 per-call totals; the sum of the leg "
                                      "medians here differs from it by "
                                      f"{abs(feed + ours['p50'] + net_paper['p50'] + venue - B['total_ms']['p50']):.3f} ms"),
                             "source": e2e + "budget_with_1s_simulated_feed.{total_ms,margin_to_requirement_ms}.p50"},
        "scenarios": scen,
        "worst_case": {"scenario": worst[0], "percentile": worst[1], "margin_to_3s_ms": worst[2]},
        "london_saving_vs_florida_ms": {
            "half_rtt_p50": r((fl["p50"] - lon["p50"]) / 2), "full_rtt_p50": r(fl["p50"] - lon["p50"]),
            "half_rtt_p90": r((fl["p90"] - lon["p90"]) / 2), "full_rtt_p90": r(fl["p90"] - lon["p90"])},
        "feed_plus_hold_share_of_p50_total_london_half_rtt": r((feed + venue) / (feed + ours["p50"] + lon["p50"] / 2 + venue), 4),
        "economic_limit_not_timing": {
            "tier0_breakeven_feed_delay_s": B["tier0_breakeven_feed_delay_s"],
            "source": e2e + "budget_with_1s_simulated_feed.tier0_breakeven_feed_delay_s",
            "note": ("every scenario allows a feed delay of at least "
                     f"{min(s[p]['max_feed_delay_for_3s_ms'] for s in scen.values() for p in ('p50', 'p90', 'p99')):,.0f}"
                     " ms under 3 s, above the pre-registered break-even feed delay (1.01-1.09 s): the 3 s bar is not "
                     "the binding limit; the strategy's break-even is.")},
        "paper_inputs_to_compare": {
            "lat.net_ldn_inferred_ms": li["net_london_s"] * 1000, "lat.net_fl_ms": li["net_florida_s"] * 1000,
            "source": "results/decay/decay.json::latency_inputs.{net_london_s,net_florida_s}",
            "measured_london_feed_one_way_ms": vultr_summary["sites"]["london"]["feed_latency_ms"],
            "measured_florida_feed_one_way_ms": vultr_summary["sites"]["florida"]["feed_latency_ms"],
            "measured_source": vs + "sites.{london,florida}.feed_latency_ms",
            "note": ("scripts/signal_decay.py sets London to a 2 ms inferred gateway constant. The probe measures "
                     "London's public websocket one-way (exchange stamp -> receive, clock-corrected) at 4.2 ms p50 / "
                     "7.4 ms p90; a cold public REST round trip from London is 69.7 ms p50."),
        },
        "not_measured": ("authenticated order latency: EIP-712 signing, L2 auth headers, the POST itself and the "
                         "venue's matching time; no order was signed or sent from any site. The REST numbers are a "
                         "public GET /time; the feed numbers are the public market websocket. The 1 s feed is "
                         "simulated (no licensed feed bought)."),
    }


# ---------------------------------------------------------------------------------------------- paper keys

def paper_keys(v: dict, s: dict, b: dict, S: dict) -> dict:
    vs = "sponsors/vultr/out/summary.json::"
    ev = "results/sponsors/evidence.json::"
    lon, fl, pa = S["sites"]["london"], S["sites"]["florida"], S["paired_arrivals"]
    sc = b["scenarios"]
    k = {
        "vultr.minutes": (f"{v['readme_claims'][0]['value']:.0f}", v["readme_claims"][0]["value"],
                          vs + "sites.london.{started_at,ended_at}"),
        "vultr.tokens": ("370", lon["token_count"], vs + "sites.london.token_count"),
        "vultr.matched": (comma(pa["matched_events"]), pa["matched_events"], vs + "paired_arrivals.matched_events"),
        "vultr.lon_first": (f"{pa['london_first_percent']:.2f}%", pa["london_first_percent"],
                            vs + "paired_arrivals.london_first_percent"),
        "vultr.adv.p50": (f"{pa['london_arrival_advantage_ms']['p50']:.0f}", pa["london_arrival_advantage_ms"]["p50"],
                          vs + "paired_arrivals.london_arrival_advantage_ms.p50"),
        "vultr.adv.p90": (f"{pa['london_arrival_advantage_ms']['p90']:.0f}", pa["london_arrival_advantage_ms"]["p90"],
                          vs + "paired_arrivals.london_arrival_advantage_ms.p90"),
        "vultr.clock": (f"{pa['combined_clock_uncertainty_ms']:.0f}", pa["combined_clock_uncertainty_ms"],
                        vs + "paired_arrivals.combined_clock_uncertainty_ms"),
        "vultr.adv.lb": (f"{pa['conservative_median_lower_bound_ms']:.0f}", pa["conservative_median_lower_bound_ms"],
                         vs + "paired_arrivals.conservative_median_lower_bound_ms"),
        "vultr.lon.feed": (f"{lon['feed_latency_ms']['p50']:.1f}", lon["feed_latency_ms"]["p50"],
                           vs + "sites.london.feed_latency_ms.p50"),
        "vultr.fl.feed.p99": (comma(fl["feed_latency_ms"]["p99"]), fl["feed_latency_ms"]["p99"],
                              vs + "sites.florida.feed_latency_ms.p99"),
        "vultr.lon.rtt": (f"{lon['rest_rtt_ms']['p50']:.0f}", lon["rest_rtt_ms"]["p50"], vs + "sites.london.rest_rtt_ms.p50"),
        "vultr.fl.rtt": (f"{fl['rest_rtt_ms']['p50']:.0f}", fl["rest_rtt_ms"]["p50"], vs + "sites.florida.rest_rtt_ms.p50"),
        "vultr.lon.rtt.p90": (f"{lon['rest_rtt_ms']['p90']:.0f}", lon["rest_rtt_ms"]["p90"], vs + "sites.london.rest_rtt_ms.p90"),
        "vultr.fl.rtt.p90": (f"{fl['rest_rtt_ms']['p90']:.0f}", fl["rest_rtt_ms"]["p90"], vs + "sites.florida.rest_rtt_ms.p90"),
        "e2e.lon.total": (comma(sc["vultr_london_cold_half_rtt"]["p50"]["total_ms"]),
                          sc["vultr_london_cold_half_rtt"]["p50"]["total_ms"],
                          ev + "budget.scenarios.vultr_london_cold_half_rtt.p50.total_ms"),
        "e2e.lon.margin": (comma(sc["vultr_london_cold_half_rtt"]["p50"]["margin_to_3s_ms"]),
                           sc["vultr_london_cold_half_rtt"]["p50"]["margin_to_3s_ms"],
                           ev + "budget.scenarios.vultr_london_cold_half_rtt.p50.margin_to_3s_ms"),
        "e2e.fl.total": (comma(sc["vultr_florida_cold_half_rtt"]["p50"]["total_ms"]),
                         sc["vultr_florida_cold_half_rtt"]["p50"]["total_ms"],
                         ev + "budget.scenarios.vultr_florida_cold_half_rtt.p50.total_ms"),
        "e2e.fl.margin": (comma(sc["vultr_florida_cold_half_rtt"]["p50"]["margin_to_3s_ms"]),
                          sc["vultr_florida_cold_half_rtt"]["p50"]["margin_to_3s_ms"],
                          ev + "budget.scenarios.vultr_florida_cold_half_rtt.p50.margin_to_3s_ms"),
        "e2e.worst.total": (comma(REQUIREMENT_MS - b["worst_case"]["margin_to_3s_ms"]),
                            r(REQUIREMENT_MS - b["worst_case"]["margin_to_3s_ms"]),
                            ev + f"budget.scenarios.{b['worst_case']['scenario']}.{b['worst_case']['percentile']}.total_ms"),
        "e2e.worst.margin": (comma(b["worst_case"]["margin_to_3s_ms"]), b["worst_case"]["margin_to_3s_ms"],
                             ev + "budget.worst_case.margin_to_3s_ms"),
    }
    rc = s.get("recheck", {})
    if rc.get("status") == "ran":
        k["snow.repro"] = (f"{rc['reproduced']}/{rc['checked']}", rc["reproduced"], ev + "snowflake.recheck.reproduced")
        k["snow.recomputed"] = (str(rc["recomputed_ok"]), rc["recomputed_ok"], ev + "snowflake.recheck.recomputed_ok")
    return {key: {"value": val, "raw": raw, "source": src} for key, (val, raw, src) in k.items()}


def main() -> int:
    S = load(VULTR / "out/summary.json")
    v = vultr_part()
    s = snowflake_part()
    b = budget_part(S)
    result = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/sponsor_evidence.py",
        "label": ("read-only check of committed sponsor results; public-feed / public REST latency only; no order "
                  "signed or sent; paper trading only"),
        "env": {"python": platform.python_version(), "git_head": (git("rev-parse", "HEAD") or "").strip() or None},
        "inputs_sha256": {rel(p): sha256(p) for p in (VULTR / "out/summary.json", VULTR / "out/run_manifest.json",
                                                      VULTR / "README.md", E2E, DECAY)},
        "vultr": v,
        "snowflake": s,
        "budget": b,
        "paper_keys": paper_keys(v, s, b, S),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")

    print(f"Vultr README claims: {v['readme_claims_ok']}/{v['readme_claims_n']} match summary.json; "
          f"arithmetic ok: {v['summary_arithmetic_ok']}; tests: {v['tests']['summary']}")
    rc = s.get("recheck", {})
    if rc.get("status") == "ran":
        print(f"Snowflake SQL on DuckDB vs current numbers.json: {rc['reproduced']}/{rc['checked']} "
              f"({rc['recomputed_ok']}/{rc['recomputed_n']} recomputed); keys moved since Ian's run: "
              f"{len(rc['keys_moved_since_committed_run'])}")
    else:
        print(f"Snowflake recheck skipped: {rc.get('reason')}")
    for name, sc in b["scenarios"].items():
        print(f"  {name:36s} " + "  ".join(f"{p} total {sc[p]['total_ms']:8.1f} margin {sc[p]['margin_to_3s_ms']:6.1f}"
                                          for p in ("p50", "p90", "p99")))
    print(f"wrote {rel(OUT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
