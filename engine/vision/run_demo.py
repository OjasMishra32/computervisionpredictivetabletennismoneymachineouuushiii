"""Play a held-out OpenTTGames test clip through the streaming call engine and benchmark it.

Default clip: test_2 frames 2000-2999 (8.3 s at 120 fps, 1920x1080), cut by stream copy (bit-exact
frames) from the public OpenTTGames test video into data/vision/ (gitignored):
  ffmpeg -ss 16.666667 -i https://lab.osai.ai/datasets/openttgames/data/test_2.mp4 -frames:v 1000 \\
         -c copy -an -copyts data/vision/test_2_copyts.mp4
It contains 9 test flights, including the two test_2 misses the frozen model calls early offline
(f_net 2760: 125 ms, f_net 2819: 408 ms) and one it does not (2402).

Modes (each run is one pass over the clip):
  realtime   frames arrive at 120 fps (paced as a live feed); every CallEvent is printed with its
             latency; the backlog shows whether the host keeps up
  max        frames as fast as the engine takes them: sustained fps of the whole pipeline
  bounded    realtime, but frames older than --max-lag-ms are skipped (bounded latency, track gaps)
  realtime@N frames arrive at N fps (frame numbering and the model's 120 fps time base unchanged): with
             N below the host's sustained fps there is no backlog, so call latency = pure processing
             latency, i.e. what a host that keeps up with the feed would see per call

Checks: detection vs the OpenTTGames ball labels in the clip; if the frozen model is present, every
decision-frame score vs the offline test scores, and every CallEvent vs the labelled flights (actual
lead = labelled contact frame - call frame).

Without models/vision/frozen_call_model.pkl (made on HiPerGator, see hpg/engine_vision.sbatch) the
engine still runs detection, tracking, flight segmentation and features, and times the classifier stage
with a stand-in HGB of the frozen hyperparameters fitted on random numbers; it then emits no calls.

Usage (repo root):
  python -m engine.vision.run_demo --backend onnx-coreml-gpu16 --modes realtime,max
  python -m engine.vision.run_demo --backend torch-cuda --blurball_root $ROOT/ext/blurball \\
         --source $ROOT/openttgames/test_2.mp4 --frame-offset 0 --start-frame 2000 --max-frames 1000 --host hpg-l4
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import time
from pathlib import Path

import numpy as np

from .events import assert_paper_only
from .stream import (FROZEN_PATH, REPO, FrameSource, VisionCallEngine, load_frozen, load_geometry,
                     make_backend, pct, run_stream, summarize, tracking_modules)

CLIP = REPO / "data" / "vision" / "test_2_copyts.mp4"
OUT = REPO / "results" / "engine" / "vision_bench.json"
MARKUP = next((p for p in (REPO / "data" / "openttgames" / "markup",
                           Path(os.environ.get("OTTG_ROOT", "/nonexistent")) / "markup",
                           REPO / "openttgames" / "markup") if p.is_dir()), REPO / "data" / "openttgames" / "markup")


def timing_proxy_model():
    """Stand-in classifier for TIMING ONLY: early_call.make_model('hgb') (frozen hyperparameters) fitted on
    random numbers with the frozen feature count. Never used to emit a call."""
    M = tracking_modules()
    rng = np.random.default_rng(0)
    X = rng.standard_normal((4000, len(M.E.FEATS_ALL)))
    y = (X[:, 0] + rng.standard_normal(4000) > 1.5).astype(int)
    m = M.E.make_model("hgb").fit(X, y)
    return dict(model=m, feats=M.E.FEATS_ALL, gate_h_s=0.10, tau_online=0.9799, tau_snapshot=0.8854,
                persist=M.E.PERSIST, lag=M.E.LAG, timing_proxy=True)


def detection_check(track_log, video):
    path = MARKUP / video / "ball_markup.json"
    if not path.exists():
        return None
    ball = json.load(open(path))
    err, n_lab, n_absent, fp_absent = [], 0, 0, 0
    for f, x, y, *_ in track_log:
        b = ball.get(str(int(f)))
        if b is None:
            continue
        if b["x"] < 0:
            n_absent += 1
            fp_absent += int(np.isfinite(x))
            continue
        n_lab += 1
        if np.isfinite(x):
            err.append(float(np.hypot(x - b["x"], y - b["y"])))
    err = np.array(err)
    return dict(labelled_frames=n_lab, tracked=int(len(err)), recall=round(len(err) / max(n_lab, 1), 4),
                within_5px=round(float((err <= 5).sum() / max(n_lab, 1)), 4),
                within_10px=round(float((err <= 10).sum() / max(n_lab, 1)), 4),
                median_err_px=round(float(np.median(err)), 2) if len(err) else None,
                offline_reference="test 94.0% within 5 px, 96.0% within 10 px, recall 0.967 (src/tracking README)")


def offline_comparison(eng, frozen, video, f_lo, f_hi):
    """Streaming vs offline: track points and decision-frame scores inside the clip."""
    out = {}
    tt = frozen.get("test_tracks", {}).get(video)
    if tt:
        on = {int(r[0]): (r[1], r[2]) for r in eng.track_log if np.isfinite(r[1])}
        common_f = [f for f in range(f_lo + 4, f_hi - 2) if f in tt or f in on]
        same = sum(1 for f in common_f if f in tt and f in on and np.hypot(tt[f][0] - on[f][0], tt[f][1] - on[f][1]) <= 2)
        out["track_agreement_2px"] = round(same / max(len(common_f), 1), 4)
        out["track_frames_compared"] = len(common_f)
    ts = frozen.get("test_scores")
    if ts is not None and eng.caller is not None:
        sel = (np.asarray(ts["video"]) == video) & (np.asarray(ts["t"]) >= f_lo + 4) & (np.asarray(ts["t"]) < f_hi)
        off = dict(zip(np.asarray(ts["t"])[sel].astype(int), np.asarray(ts["score"])[sel]))
        on = {int(t): p for t, d, t0, p, g in eng.caller.trace}
        both = [t for t in off if t in on]
        diffs = np.array([abs(off[t] - on[t]) for t in both])
        out["scores_compared"] = len(both)
        out["offline_decision_frames_in_clip"] = len(off)
        out["online_decision_frames_in_clip"] = len(on)
        if len(diffs):
            out["score_abs_diff"] = pct(diffs, (50, 90, 99))
    return out


def match_events(events, frozen, video, f_lo, f_hi):
    """Each CallEvent vs the labelled flights (results/tracking/test_flights.csv)."""
    tf = frozen.get("test_flights") if frozen else None
    if tf is None:
        import pandas as pd
        tf = pd.read_csv(REPO / "results" / "tracking" / "test_flights.csv").to_dict("list")
    rows = [dict(zip(tf.keys(), v)) for v in zip(*tf.values())]
    fl = [r for r in rows if r["video"] == video and r["t0"] >= f_lo and r["t_ref"] < f_hi]
    aud = {}
    ap = REPO / "results" / "tracking" / "test_flights_audited.csv"
    if ap.exists():   # post-hoc label audit (src/tracking/audit_labels.py): relabelled / unresolved flights
        import pandas as pd
        for r in pd.read_csv(ap).itertuples():
            aud[(r.video, int(r.f_net))] = (r.label, r.audit if isinstance(r.audit, str) else None)
    for r in fl:
        r["label_audited"], r["audit"] = aud.get((r["video"], int(r["f_net"])), (r["label"], None))
    out, matched = [], set()
    for ev in events:
        cand = [r for r in fl if r["t0"] - 2 <= ev.frame <= r["t_ref"] + 12 and np.sign(r["dir"]) == ev.direction]
        r = min(cand, key=lambda r: abs(r["t_ref"] - ev.frame)) if cand else None
        o = dict(call=ev.call, frame=ev.frame, p_miss=round(ev.p_miss, 4), lead_pred_ms=round(ev.lead_ms, 1),
                 latency_ms=round(ev.latency_ms, 2))
        if r is None:
            o.update(flight=None, correct=None, note="no labelled flight (outside the evaluated population)")
        else:
            matched.add(r["f_net"])
            o.update(flight=int(r["f_net"]), label=r["label"], label_audited=r["label_audited"], audit=r["audit"],
                     actual_lead_ms=round(1000 * (r["t_ref"] - ev.frame) / 120, 1),
                     correct=(r["label"] == "MISS") == (ev.call == "MISS"),
                     correct_audited=(r["label_audited"] == "MISS") == (ev.call == "MISS"),
                     offline_first_call_lead_ms=(None if not np.isfinite(r["first_call_lead_ms"]) else
                                                 round(float(r["first_call_lead_ms"]), 1)))
        out.append(o)
    flights = [dict(f_net=int(r["f_net"]), label=r["label"], label_audited=r["label_audited"], audit=r["audit"],
                    t0=int(r["t0"]), t_ref=int(r["t_ref"]),
                    offline_first_call_lead_ms=(None if not np.isfinite(r["first_call_lead_ms"]) else
                                                round(float(r["first_call_lead_ms"]), 1)),
                    called_online=int(r["f_net"]) in matched) for r in fl]
    return out, flights


def segmentation_check(eng, video, f_lo, f_hi, geo):
    """Model-independent: does the online flight segmentation score the frames the frozen evaluation
    scored? For each labelled flight in the clip (results/tracking/test_flights.csv), the offline decision
    frames are those where early_call.Flight(labelled t0, t_ref, dir).features(t) exists (computed on the
    streaming track); online = frames the engine scored with the same direction. Also: does the online
    flight start equal the offline t0 (both from flights.flight_start, offline anchored at the net frame)."""
    import pandas as pd
    from types import SimpleNamespace
    E = tracking_modules().E
    tf = pd.read_csv(REPO / "results" / "tracking" / "test_flights.csv")
    tf = tf[(tf.video == video) & (tf.t0 >= f_lo + 4) & (tf.t_ref < f_hi)]
    tr = {t: (d, t0) for t, d, t0, p, g in eng.caller.trace}
    trk = eng.trk.trk
    rows = []
    for r in tf.itertuples():
        F = E.Flight(SimpleNamespace(dir=float(np.sign(r.dir)), t0=int(r.t0), t_ref=int(r.t_ref)), trk, geo)
        off = [t for t in range(int(r.t0) + E.NMIN - 1 + E.LAG, int(r.t_ref) + 1) if F.features(t) is not None]
        on = [t for t in off if t in tr and tr[t][0] == np.sign(r.dir)]
        missed = [t for t in off if t not in on]
        t0s = sorted({tr[t][1] for t in on})
        rows.append(dict(f_net=int(r.f_net), label=r.label, offline_frames=len(off), online_scored=len(on),
                         coverage=round(len(on) / max(len(off), 1), 3), not_scored_online=missed,
                         offline_t0=int(r.t0), online_t0=t0s[:3]))
    cov = [x["coverage"] for x in rows]
    return dict(flights=rows, mean_coverage=round(float(np.mean(cov)), 3) if cov else None,
                t0_exact=f"{sum(1 for x in rows if x['online_t0'] == [x['offline_t0']])}/{len(rows)}")


def one_run(mode, a, frozen, geo, M, use_frozen):
    events_printed = []

    def on_event(ev):
        tag = f"{ev.call:6s} frame {ev.frame} (t={ev.media_t:7.3f}s) P(miss)={ev.p_miss:.3f} " \
              f"predicted lead {ev.lead_ms:5.0f} ms | latency frame->emit {ev.latency_ms:8.1f} ms"
        print(f"  [{mode}] CallEvent {tag}", flush=True)
        events_printed.append(ev)
    eng = VisionCallEngine(make_backend(a.backend, a.blurball_root, a.threads), frozen, geo, fps=120.0,
                           frame_offset=a.frame_offset + a.start_frame, on_event=on_event,
                           emit_enabled=use_frozen)
    # warm-up (first CoreML / CUDA call compiles); not part of the stream
    x0 = np.zeros((1, 9, M.D.INP_H, M.D.INP_W), np.float32)
    for b in eng.det.backends:
        for _ in range(3):
            b(x0)
    pace_fps = float(mode.split("@")[1]) if "@" in mode else 120.0     # realtime@N: arrivals at N fps
    src = FrameSource(a.source, M.D, realtime=(mode != "max"), fps=pace_fps, max_frames=a.max_frames,
                      start_frame=a.start_frame, reader=a.reader).start()
    t = time.time()
    rows, skipped = run_stream(eng, src, a.max_lag_ms if mode == "bounded" else None)
    wall = time.time() - t
    s = summarize(rows, wall, skipped, eng)
    s["frames_read"] = src.info.get("read", 0)
    s["reader"] = src.info.get("reader")
    if "error" in src.info:
        raise RuntimeError(f"reader failed: {src.info['error']}")
    s["source_dropped"] = src.info.get("dropped", 0)
    s["reader_late_ms"] = src.info.get("reader_late_ms")
    s["mode"] = mode
    s["arrival_fps"] = None if mode == "max" else pace_fps
    if mode == "bounded":
        s["max_lag_ms"] = a.max_lag_ms
    return eng, s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(CLIP))
    ap.add_argument("--video", default="test_2")
    ap.add_argument("--frame-offset", type=int, default=2000, help="source frame number of the file's first frame")
    ap.add_argument("--start-frame", type=int, default=0, help="seek this many frames into the file first")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--backend", default="onnx-coreml-gpu16")
    ap.add_argument("--blurball_root", default=None)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--modes", default="realtime,max")
    ap.add_argument("--reader", default="auto", help="auto (pyav for files/URLs, cv2 for webcams) | pyav | cv2")
    ap.add_argument("--max-lag-ms", type=float, default=100.0)
    ap.add_argument("--frozen", default=str(FROZEN_PATH))
    ap.add_argument("--host", default=f"laptop-{platform.machine()}")
    ap.add_argument("--merge", action="store_true", help="add these modes to an existing entry for the same config")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--events-log", default=None, help="JSONL of all CallEvents (default results/engine/vision_events_<host>.jsonl)")
    a = ap.parse_args()
    assert_paper_only()
    M = tracking_modules()
    try:
        frozen = load_frozen(a.frozen)
        use_frozen = True
        print(f"frozen model: {a.frozen} ({frozen['model_source']}, check vs frozen scores "
              f"max |diff| {frozen['check_max_abs_err']:.1e}); tau_online={frozen['tau_online']} "
              f"gate={frozen['gate_h_s']} s, persistence {frozen['persist']} frames", flush=True)
    except FileNotFoundError as e:
        print(f"NOTE: {e}\n-> calls disabled; classifier stage timed with a stand-in (timing only)", flush=True)
        frozen, use_frozen = timing_proxy_model(), False
    geo, geo_prov = load_geometry(a.video, frozen if use_frozen else None)
    print(f"geometry: {geo_prov}", flush=True)

    f_lo = a.frame_offset + a.start_frame
    runs = {}
    ev_path = Path(a.events_log or (REPO / "results" / "engine" / f"vision_events_{a.host}.jsonl"))
    ev_path.parent.mkdir(parents=True, exist_ok=True)
    for mode in a.modes.split(","):
        print(f"\n== {mode}: {a.source} via {a.backend}", flush=True)
        eng, s = one_run(mode, a, frozen, geo, M, use_frozen)
        f_hi = f_lo + s["frames_read"]
        s["detection_vs_labels"] = detection_check(eng.track_log, a.video)
        s["segmentation_vs_offline"] = segmentation_check(eng, a.video, f_lo, f_hi, geo)
        if use_frozen:
            s["vs_offline"] = offline_comparison(eng, frozen, a.video, f_lo, f_hi)
            s["events"], s["flights_in_clip"] = match_events(eng.events, frozen, a.video, f_lo, f_hi)
            with open(ev_path, "a") as fh:
                for ev in eng.events:
                    fh.write(json.dumps(dict(ev.to_dict(), host=a.host, mode=mode, backend=a.backend)) + "\n")
        else:
            s["events"] = "calls disabled (frozen model not available on this host)"
            s["decision_frames_scored"] = eng.caller.n_dec
        runs[mode] = s
        print(json.dumps({k: s[k] for k in ("frames", "fps_sustained", "infer_ms", "proc_ms", "call_ready_ms",
                                            "source_dropped", "skipped")}, indent=1), flush=True)

    res = json.load(open(a.out)) if os.path.exists(a.out) else {}
    res.setdefault("runs", {})
    key = f"{a.host}|{a.backend}|{a.reader}"
    prev = res["runs"].get(key, {}).get("runs", {}) if a.merge else {}
    runs = {**prev, **runs}
    res["runs"][key] = dict(load_avg_1_5_15=[round(x, 2) for x in os.getloadavg()],
        when=datetime.datetime.now().isoformat(timespec="seconds"), host=a.host,
        machine=f"{platform.system()} {platform.machine()} {platform.processor()}", backend=a.backend,
        source=a.source, reader=a.reader, video=a.video, first_frame=f_lo, frozen_model=(a.frozen if use_frozen else None),
        calls_enabled=use_frozen, geometry=geo_prov, runs=runs)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, default=float)
    from .bench_summary import summarize as _summ
    _summ(a.out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
