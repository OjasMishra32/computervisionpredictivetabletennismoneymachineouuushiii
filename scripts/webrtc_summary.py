"""Summarise a scripts/webrtc_demo.sh output file (results/webrtc/run_<ts>.jsonl): one row per run.

Usage: python scripts/webrtc_summary.py results/webrtc/run_<ts>.jsonl [--out results/webrtc/summary_<ts>.json]
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

FILE_RUN = os.path.join(os.path.dirname(__file__), "..", "results", "engine", "demo_run.json")


def file_source_calls():
    """CallEvents of the same clip + frozen model read straight from the file (engine/vision demo run),
    for a WebRTC-vs-file comparison of the calls themselves (did the re-encode change any call?)."""
    try:
        v = json.load(open(FILE_RUN))["vision"]
        return [(e["call"], int(e["frame"]), round(float(e["p_miss"]), 4)) for e in v["events"]]
    except Exception:       # noqa: BLE001
        return None


def compare_calls(webrtc, ref, last_frame):
    if ref is None:
        return None
    ref = [r for r in ref if r[1] <= last_frame]
    got = [(c["call"], int(c["frame"]), round(float(c["p_miss"]), 4)) for c in webrtc]
    same = [g for g in got if any(g[0] == r[0] and abs(g[1] - r[1]) <= 2 for r in ref)]
    return dict(file_source_calls=len(ref), webrtc_calls=len(got), same_call_within_2_frames=len(same),
                only_file=[r for r in ref if not any(r[0] == g[0] and abs(r[1] - g[1]) <= 2 for g in got)],
                only_webrtc=[g for g in got if g not in same], reference="results/engine/demo_run.json (file source)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_file")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    meta, summ = {}, {}
    calls = defaultdict(list)
    for line in open(a.run_file):
        r = json.loads(line)
        t, run = r.get("type"), r.get("run")
        if t == "meta":
            meta[run] = r
        elif t == "summary":
            summ[run] = r
        elif t == "call":
            calls[run].append(r)
    rows = []
    ref_calls = file_source_calls()
    for run, s in summ.items():
        m = meta.get(run, {})
        L = s.get("latency_ms", {})
        eng = s.get("engine") or {}

        def g(name, q="p50"):
            d = L.get(name)
            return None if not d else d.get(q)
        row = dict(run=run, mode=m.get("mode"), step=m.get("step"), arrival_fps=m.get("arrival_fps"),
                   encoder=(m.get("sender") or {}).get("encoder"), calls_valid=m.get("calls_valid"),
                   max_lag_ms=m.get("max_lag_ms"), load_avg_start=m.get("load_avg_start"),
                   frames=s.get("frames"),
                   video_leg_ms={q: g("capture_to_handoff", q) for q in ("p50", "p90", "p99", "max")},
                   network_ms={q: g("capture_to_complete", q) for q in ("p50", "p90", "p99")},
                   decode_ms_p50=g("decode"), prep_ms_p50=g("prep"), sender_late_ms_p50=g("sender_late"),
                   engine_ready_ms={q: g("engine_ready", q) for q in ("p50", "p90", "p99")},
                   capture_to_decision_ms={q: g("capture_to_decision", q) for q in ("p50", "p90", "p99", "max")},
                   engine_fps=eng.get("fps_sustained"), engine_skipped=eng.get("skipped"),
                   detection_within_5px=(s.get("detection_vs_labels") or {}).get("within_5px"),
                   calls=[dict(call=c["call"], src=c.get("src"), capture_to_emit_ms=round(c["capture_to_emit_ms"], 1)
                               if c.get("capture_to_emit_ms") is not None else None,
                               video_leg_ms=round(c["capture_to_handoff_ms"], 1) if c.get("capture_to_handoff_ms") else None,
                               engine_ms=round(c["latency_ms"], 1), ood=c.get("out_of_distribution"))
                          for c in calls.get(run, [])],
                   events_vs_labels=s.get("events_vs_labels"))
        if m.get("calls_valid"):
            last = 2000 + (s.get("frames") or {}).get("received_clip", 0) - 1
            row["calls_vs_file_source"] = compare_calls(calls.get(run, []), ref_calls, last)
        rows.append(row)
    hdr = f"{'run':26s} {'fps':>4s} {'recv/sent':>10s} {'video leg p50/p90/p99 ms':>26s} {'capture->decision p50/p90/p99 ms':>34s} {'eng fps':>7s} {'skip':>5s}"
    print(hdr)
    for r in rows:
        f = r["frames"] or {}
        v = r["video_leg_ms"]
        c = r["capture_to_decision_ms"]
        fmt = (lambda d: "/".join("-" if d[q] is None else f"{d[q]:.0f}" for q in ("p50", "p90", "p99")))
        print(f"{r['run']:26s} {r['arrival_fps'] or 0:>4.0f} {str(f.get('received_clip')) + '/' + str(f.get('sent_clip')):>10s} "
              f"{fmt(v):>26s} {fmt(c):>34s} {r['engine_fps'] or 0:>7.1f} {r['engine_skipped'] or 0:>5d}")
        for cl in r["calls"]:
            print(f"    {cl['call']:6s} src {cl['src']}  capture->emit {cl['capture_to_emit_ms']} ms "
                  f"(video leg {cl['video_leg_ms']} + engine {cl['engine_ms']}){'  OOD' if cl['ood'] else ''}")
        if r.get("calls_vs_file_source"):
            c = r["calls_vs_file_source"]
            print(f"    calls vs file source: {c['same_call_within_2_frames']}/{c['file_source_calls']} reproduced, "
                  f"only file {c['only_file']}, only webrtc {c['only_webrtc']}")
    if a.out:
        json.dump(dict(source=a.run_file, runs=rows), open(a.out, "w"), indent=1, default=float)
        print("wrote", a.out)


if __name__ == "__main__":
    main()
