"""Headline table for results/engine/vision_bench.json (recomputed from the stored runs).

  python -m engine.vision.bench_summary [results/engine/vision_bench.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "engine" / "vision_bench.json"
SOURCE_FPS = 120.0


def _g(d, *ks):
    for k in ks:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def summarize(path=OUT):
    res = json.load(open(path))
    rows = []
    for key, r in res.get("runs", {}).items():
        runs = r["runs"]
        mx, rt, bd = runs.get("max", {}), runs.get("realtime", {}), runs.get("bounded", {})
        fps = mx.get("fps_sustained")
        rows.append(dict(
            config=key, host=r.get("host"), detector=_g(mx, "detector") or _g(rt, "detector"), reader=r.get("reader"),
            frames=mx.get("frames") or rt.get("frames"),
            fps_sustained=fps, keeps_up_with_120fps=(fps is not None and fps >= SOURCE_FPS),
            realtime_factor=(round(fps / SOURCE_FPS, 3) if fps else None),
            infer_ms_p50=_g(mx, "infer_ms", "p50"), engine_ms_per_frame_p50=_g(mx, "proc_ms", "p50"),
            decode_resize_ms_p50=(None if _g(mx, "decode_ms", "p50") is None else
                                  round(_g(mx, "decode_ms", "p50") + _g(mx, "prep_ms", "p50"), 2)),
            features_ms_p50=_g(mx, "feat_ms", "p50"), classifier_ms_p90=_g(mx, "clf_ms", "p90"),
            realtime_120fps_call_latency_ms=dict(p50=_g(rt, "call_ready_ms", "p50"), p90=_g(rt, "call_ready_ms", "p90"),
                                          max=_g(rt, "call_ready_ms", "max")) if rt else None,
            unloaded_call_latency_ms=next((dict(arrival_fps=v.get("arrival_fps"), p50=_g(v, "call_ready_ms", "p50"),
                                                 p90=_g(v, "call_ready_ms", "p90"), p99=_g(v, "call_ready_ms", "p99"))
                                            for m, v in runs.items() if m.startswith("realtime@")), None),
            bounded_call_latency_ms=dict(p50=_g(bd, "call_ready_ms", "p50"), p90=_g(bd, "call_ready_ms", "p90"),
                                         frames_skipped=bd.get("skipped"), max_lag_ms=bd.get("max_lag_ms"),
                                         within_5px=_g(bd, "detection_vs_labels", "within_5px")) if bd else None,
            detection_within_5px=_g(mx, "detection_vs_labels", "within_5px") or _g(rt, "detection_vs_labels", "within_5px"),
            segmentation_t0_exact=_g(mx, "segmentation_vs_offline", "t0_exact"),
            segmentation_coverage=_g(mx, "segmentation_vs_offline", "mean_coverage"),
            calls_enabled=r.get("calls_enabled"), load_avg=r.get("load_avg_1_5_15")))
    res["summary"] = rows
    json.dump(res, open(path, "w"), indent=1, default=float)
    return rows


if __name__ == "__main__":
    rows = summarize(sys.argv[1] if len(sys.argv) > 1 else OUT)
    for r in rows:
        print(json.dumps(r))
