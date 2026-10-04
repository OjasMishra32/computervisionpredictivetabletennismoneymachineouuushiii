"""Summarize simultaneous COURTSIDE London and Florida probe logs."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * p
    lower, upper = int(position), min(int(position) + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def corrected_feed_rows(rows: list[dict]) -> list[tuple[dict, float]]:
    metas = {row.get("phase"): row for row in rows if row.get("type") == "meta"}
    start, end = metas.get("start", {}), metas.get("end", {})
    start_offset = (start.get("clock") or {}).get("local_minus_ntp_ms")
    end_offset = (end.get("clock") or {}).get("local_minus_ntp_ms")
    try:
        start_ns = datetime.fromisoformat(start["at"]).timestamp() * 1e9
        end_ns = datetime.fromisoformat(end["at"]).timestamp() * 1e9
    except (KeyError, TypeError, ValueError):
        start_ns = end_ns = None
    output = []
    for row in rows:
        if row.get("type") != "ws" or row.get("feed_delay_raw_ms") is None:
            continue
        offset = start_offset
        if None not in (start_offset, end_offset, start_ns, end_ns) and end_ns > start_ns:
            fraction = min(1.0, max(0.0, (row["recv_wall_ns"] - start_ns) / (end_ns - start_ns)))
            offset = start_offset + fraction * (end_offset - start_offset)
        delay = float(row["feed_delay_raw_ms"]) - offset if offset is not None else float(row["feed_delay_raw_ms"])
        output.append((row, delay))
    return output


def read_probe(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    sites = {row.get("site") for row in rows if row.get("site")}
    if len(sites) != 1:
        raise ValueError(f"{path} must contain exactly one site")
    feed = [delay for _, delay in corrected_feed_rows(rows) if -1000 < delay < 60000]
    rest = [float(row["rtt_ms"]) for row in rows if row.get("type") == "rest"]
    start = next((row for row in rows if row.get("type") == "meta" and row.get("phase") == "start"), {})
    end = next((row for row in reversed(rows) if row.get("type") == "meta" and row.get("phase") == "end"), {})
    return {
        "site": sites.pop(), "source": path.name, "started_at": start.get("at"), "ended_at": end.get("at"),
        "token_count": start.get("token_count"), "clock_start": start.get("clock"), "clock_end": end.get("clock"),
        "feed_messages": len(feed), "rest_samples": len(rest),
        "feed_latency_ms": {f"p{int(p*100)}": round(percentile(feed, p), 3) if feed else None
                            for p in (0.5, 0.9, 0.99)},
        "rest_rtt_ms": {f"p{int(p*100)}": round(percentile(rest, p), 3) if rest else None
                        for p in (0.5, 0.9, 0.99)},
        "errors": sum(row.get("type") == "error" for row in rows),
    }


def paired_events(paths: list[Path]) -> dict:
    by_site: dict[str, dict[tuple, float]] = {}
    for path in paths:
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        site = next(row["site"] for row in rows if row.get("site"))
        events = {}
        for row, delay in corrected_feed_rows(rows):
            key = (row.get("server_ts_ms"), row.get("event_type"), row.get("asset_id"))
            if key[0] is not None:
                events.setdefault(key, delay)
        by_site[site] = events
    common = set(by_site.get("london", {})) & set(by_site.get("florida", {}))
    advantages = [by_site["florida"][key] - by_site["london"][key] for key in common]
    sample = []
    for key in sorted(common, key=lambda item: tuple(str(value) for value in item))[:10]:
        london, florida = by_site["london"][key], by_site["florida"][key]
        sample.append({"server_ts_ms": key[0], "event_type": key[1], "asset_id": key[2],
                       "london_delay_ms": round(london, 3), "florida_delay_ms": round(florida, 3),
                       "london_advantage_ms": round(florida - london, 3)})
    return {
        "matched_events": len(advantages),
        "london_first_percent": round(100 * sum(value > 0 for value in advantages) / len(advantages), 2)
                                if advantages else None,
        "london_arrival_advantage_ms": {
            f"p{int(p*100)}": round(percentile(advantages, p), 3) if advantages else None
            for p in (0.5, 0.9, 0.99)
        }, "deterministic_sample": sample,
    }


def compare(paths: list[Path]) -> dict:
    sites = {row["site"]: row for row in map(read_probe, paths)}
    if "london" not in sites or "florida" not in sites:
        raise ValueError("comparison requires sites named london and florida")
    improvement = {}
    for metric in ("feed_latency_ms", "rest_rtt_ms"):
        improvement[metric] = {}
        for pct in ("p50", "p90", "p99"):
            left, right = sites["florida"][metric][pct], sites["london"][metric][pct]
            improvement[metric][pct] = round(left - right, 3) if left is not None and right is not None else None
    paired = paired_events(paths)
    uncertainty = sum(max((site.get("clock_start") or {}).get("uncertainty_ms") or 0,
                          (site.get("clock_end") or {}).get("uncertainty_ms") or 0)
                      for site in sites.values())
    paired["combined_clock_uncertainty_ms"] = round(uncertainty, 3)
    median = paired["london_arrival_advantage_ms"]["p50"]
    paired["conservative_median_lower_bound_ms"] = round(median - uncertainty, 3) if median is not None else None
    try:
        starts = [datetime.fromisoformat(site["started_at"]).timestamp() for site in sites.values()]
        start_skew = round((max(starts) - min(starts)) * 1000, 3)
    except (TypeError, ValueError):
        start_skew = None
    return {"experiment": "COURTSIDE London", "paper_trading_only": True,
            "observed_probe_start_skew_ms": start_skew,
            "sites": sites, "paired_arrivals": paired,
            "london_improvement_ms": improvement}


def dashboard(summary: dict) -> str:
    london, florida = summary["sites"]["london"], summary["sites"]["florida"]
    improvement = summary["london_improvement_ms"]
    paired = summary["paired_arrivals"]
    def fmt(value): return "n/a" if value is None else f"{value:.1f} ms"
    rows = "".join(
        f"<tr><td>{label}</td><td>{fmt(london[key][pct])}</td><td>{fmt(florida[key][pct])}</td>"
        f"<td><strong>{fmt(improvement[key][pct])}</strong></td></tr>"
        for label, key, pct in (("Feed p50", "feed_latency_ms", "p50"),
                                ("Feed p90", "feed_latency_ms", "p90"),
                                ("Feed p99", "feed_latency_ms", "p99"),
                                ("REST RTT p50", "rest_rtt_ms", "p50"),
                                ("REST RTT p99", "rest_rtt_ms", "p99")))
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>COURTSIDE London · Vultr latency evidence</title><style>
body{{margin:0;background:#08111f;color:#edf5ff;font:16px/1.5 system-ui}}main{{max-width:980px;margin:auto;padding:48px 24px}}
.tag{{color:#56d6ff;font-weight:800;letter-spacing:.14em}}h1{{font-size:clamp(2.5rem,7vw,5.8rem);line-height:.95;margin:.15em 0}}
.lead{{max-width:760px;color:#a9bdd4;font-size:1.15rem}}.hero{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:32px 0}}
.card{{background:#101f34;border:1px solid #23405f;border-radius:16px;padding:22px}}.number{{font-size:2.2rem;font-weight:900;color:#71f5aa}}
table{{width:100%;border-collapse:collapse;background:#101f34;border-radius:14px;overflow:hidden}}th,td{{padding:14px;text-align:left;border-bottom:1px solid #23405f}}th{{color:#56d6ff}}
.note{{color:#a9bdd4}}code{{color:#ffd37a}}</style></head><body><main><div class=tag>MLH · BEST USE OF VULTR</div><h1>COURTSIDE London</h1>
<p class=lead>A simultaneous, read-only Polymarket CLOB experiment: the same tennis books observed from a Vultr London server and a Florida laptop, with NTP clock evidence and no trading credentials.</p>
<div class=hero><div class=card><div class=number>{fmt(paired['london_arrival_advantage_ms']['p50'])}</div><div>London paired-event advantage · median</div></div>
<div class=card><div class=number>{paired['london_first_percent'] if paired['london_first_percent'] is not None else 'n/a'}%</div><div>Matched updates London received first</div></div>
<div class=card><div class=number>{paired['matched_events']:,}</div><div>Identical updates paired across sites</div></div></div>
<table><thead><tr><th>Metric</th><th>Vultr London</th><th>Florida laptop</th><th>London improvement</th></tr></thead><tbody>{rows}</tbody></table>
<p class=note>The headline pairs identical updates by exchange timestamp, event type, and market, then compares clock-corrected arrival time. The {fmt(paired['combined_clock_uncertainty_ms'])} combined clock-uncertainty bound leaves a conservative median London advantage of {fmt(paired['conservative_median_lower_bound_ms'])}. Positive improvement means London was faster. REST RTT hits <code>/time</code> every two seconds. Paper trading only.</p>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("probes", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "out" / "summary.json")
    parser.add_argument("--dashboard", type=Path, default=Path(__file__).parent / "out" / "dashboard.html")
    args = parser.parse_args()
    result = compare(args.probes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    args.dashboard.write_text(dashboard(result))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
