"""The end-to-end demo with the live frozen classifier, plus a per-frame log of the vision engine. PAPER ONLY.

  python -m engine.vision.demo_live [any `engine.run --mode demo` option]
  python -m engine.vision.demo_live --l4-variant      # market replay again with the L4 run's calls + latencies

Runs `python -m engine.run --mode demo` unchanged (engine/run.py demo(): the real streaming engine on the
held-out clip, then paper orders against the recorded WTA book) and also records what the vision engine
did on every frame, for engine/vision/render_demo_video.py. It refuses to start without
models/vision/frozen_call_model.pkl, so every CallEvent comes from the live classifier (no replayed
decisions). Writes, next to run.py's demo_run.json and demo_timeline.png:

  results/engine/demo_vision_trace.json
    frames     [frame, x, y, peak, blob_score] per frame: the online tracker's accepted ball position in
               1920x1080 pixels (null when the tracker accepted nothing)
    decisions  [frame, direction, flight_t0, p_miss_gated, gate_open, ready_ms] per scored decision frame
               (ready_ms = frame arrival -> decision done, queueing included)
    timing     [frame, arrival_s, qwait_ms, proc_ms, e2e_ms] per frame (arrival_s from the first frame)
    events     every CallEvent as emitted (to_dict)

run.py's `mapping.players` text names the wrong MISS of the earlier replayed-decision run (frame 2759).
That sentence is rewritten here from this run's own events; `mapping.players_amended_by` says so.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from . import stream as S
from .events import assert_paper_only

OUT = S.REPO / "results" / "engine"
TRACE = OUT / "demo_vision_trace.json"
_cap: dict = {}


def _tap(engine, source, *a, **k):
    rows, skipped = _run_stream(engine, source, *a, **k)
    _cap.update(engine=engine, rows=rows)
    return rows, skipped


_run_stream = S.run_stream


def _num(x, nd=2):
    x = float(x)
    return None if not np.isfinite(x) else round(x, nd)


def write_trace(path: Path, argv: list[str]) -> dict:
    eng, rows = _cap["engine"], _cap["rows"]
    off = eng.offset
    t0 = rows[0]["t_frame"] if rows else 0.0
    trace = dict(
        what="per-frame log of the vision engine during the demo run (engine/vision/demo_live.py)",
        when=time.strftime("%Y-%m-%d %H:%M:%S %Z"), argv=argv, frame_offset=off, fps=eng.fps,
        detector=eng.det.name, lag_frames=eng.lag,
        frames=[[int(f), _num(x), _num(y), _num(pk, 4), _num(sc, 4)] for f, x, y, pk, sc in eng.track_log],
        decisions=[[int(t), int(d), int(t0_), round(float(p), 5), bool(g), _num(eng.ready_ms.get(t, np.nan))]
                   for t, d, t0_, p, g in eng.caller.trace],
        timing=[[int(r["i"]) + off, round(r["t_frame"] - t0, 4), _num(r["qwait_ms"]), _num(r["proc_ms"]),
                 _num(r["e2e_ms"])] for r in rows],
        events=[ev.to_dict() for ev in eng.events])
    path.write_text(json.dumps(trace, default=float))
    return trace


def amend_players_text(demo_path: Path) -> None:
    """Replace run.py's hardcoded 'frame-2759' example with this run's own wrong MISS call(s)."""
    out = json.loads(demo_path.read_text())
    mp = out["mapping"]
    anchor = mp["anchor_flight"]["f_net"]
    others = [e for e in out["vision"]["events"] if e["call"] == "MISS" and e.get("flight_f_net") != anchor]
    s = mp["players"]
    cut = s.find(" (the frame-2759")
    if cut < 0:
        return
    if others:
        ex = "; ".join(f"the frame-{e['frame']} MISS" + (f" was flagged '{e['audit']}' by the label audit"
                                                        if e.get("audit") else
                                                        (" is on a labelled flight" if e.get("label") else
                                                         " is outside the labelled flights")) for e in others)
        s = s[:cut] + f" (in this run, {ex})."
    else:
        s = s[:cut] + " (in this run every MISS was on the anchor flight)."
    mp["players"] = s
    mp["players_amended_by"] = ("engine/vision/demo_live.py: run.py's sentence named the replayed-decision run's "
                                "frame 2759; rewritten from this run's events")
    demo_path.write_text(json.dumps(out, indent=1, default=str))


L4_EVENTS = OUT / "online_events_L4.jsonl"
L4_EVAL = OUT / "online_vs_offline.json"
L4_RUN = "fp16_cl_fuse_compile_b1_realtime"


def l4_vision(V: dict) -> dict:
    """The demo's vision section with the CallEvents the NVIDIA L4 run emitted on the same frames.

    Source: eval_online's primary run (job 44607191), which streamed all of test_2 through the same engine at
    a real 120 fps with nothing dropped (fp16 + channels-last + folded BN + torch.compile, batch 1). Its
    events inside the clip's frame range are taken as they were logged (online_events_L4.jsonl), with their
    measured latency. On the L4 the engine keeps up, so latency as run = processing latency (queue wait
    included). The clip's flights and the labels come from the laptop run (same video, same labels)."""
    lo, hi = V["first_frame"], V["first_frame"] + V["frames"]
    ev = [json.loads(line) for line in L4_EVENTS.read_text().splitlines() if line.strip()]
    ev = [e for e in ev if e.get("video") == V["video"] and lo <= e["frame"] < hi]
    lab = {(e["call"], e["frame"]): e for e in V["events"]}
    keep = ("flight_f_net", "label", "label_audited", "audit", "actual_lead_ms", "correct_vs_label")
    events = []
    for e in ev:
        e = dict(e, processing_latency_ms=e["latency_ms"], queue_wait_ms=None)
        e.update({k: lab[(e["call"], e["frame"])][k] for k in keep if (e["call"], e["frame"]) in lab
                  and k in lab[(e["call"], e["frame"])]})
        events.append(e)
    run = json.loads(L4_EVAL.read_text())["runs"][L4_RUN]
    hd = json.loads(L4_EVAL.read_text())["headline"][L4_RUN]["stream"]
    same = [(e["call"], e["frame"], e["direction"]) for e in events] == \
           [(e["call"], e["frame"], e["direction"]) for e in V["events"]]
    W = {k: v for k, v in V.items() if k not in ("events", "timing", "not_reproduced")}
    W.update(call_source="frozen_model_live",
             host=f"NVIDIA L4, HiPerGator job {run['run']['env']['slurm_job']} (eval_online: test_2 streamed whole)",
             backend="torch-cuda-cl-fuse-compile", detector=run["run"]["backend"], arrival_fps=120.0,
             events=events, same_calls_as_laptop_run=same,
             source_files=[str(L4_EVENTS.relative_to(S.REPO)), str(L4_EVAL.relative_to(S.REPO))],
             timing=dict(fps_sustained=hd["fps"], frames_dropped=hd["dropped"],
                         call_ready_ms=hd["after_startup"]["call_ready_ms"],
                         call_ready_processing_ms=hd["after_startup"]["call_ready_ms"],
                         emitted_call_latency_ms=hd["after_startup"]["emitted_call_latency_ms"],
                         note="whole test set at 120 fps; first 4 s of test_1 (start-up) excluded"))
    return W


def l4_variant(argv: list[str]) -> Path:
    """Same market replay as the demo, with the L4's calls and latencies: results/engine/demo_run_L4.json."""
    import tempfile
    from engine import run as R
    demo = json.loads((OUT / "demo_run.json").read_text())
    if demo["vision"].get("call_source") != "frozen_model_live":
        raise SystemExit("run the live demo first (python -m engine.vision.demo_live)")
    W = l4_vision(demo["vision"])
    dst = OUT / "demo_run_L4.json"
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "vision_L4.json"
        src.write_text(json.dumps({"vision": W}, default=float))
        out0 = R.OUT
        R.OUT = Path(td)
        try:
            R.main(["--mode", "demo", "--reuse-vision", str(src), *argv])
        finally:
            R.OUT = out0
        out = json.loads((Path(td) / "demo_run.json").read_text())
    out["vision"]["reused_from"] = W["source_files"]
    out["variant"] = ("L4 vision: the CallEvents and latencies of the NVIDIA L4 120 fps run on the same clip frames "
                      "(online_events_L4.jsonl, job 44607191), market side replayed exactly as in demo_run.json. "
                      f"Same calls as the laptop run: {W['same_calls_as_laptop_run']}.")
    dst.write_text(json.dumps(out, indent=1, default=str))
    amend_players_text(dst)     # run.py's sentence names frame 2759; the L4 run's wrong MISS is f2766 too
    print(f"wrote {dst}", flush=True)
    return dst


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    assert_paper_only()
    if "--l4-variant" in argv:
        argv.remove("--l4-variant")
        l4_variant(argv)
        return
    frozen = argv[argv.index("--frozen") + 1] if "--frozen" in argv else str(S.FROZEN_PATH)
    if not Path(frozen).exists():
        raise SystemExit(f"{frozen} missing: this runner only runs the live classifier (copy it from HPG "
                         "models/vision/, see hpg/engine_vision.sbatch)")
    if any(x in argv for x in ("--reuse-vision", "--figure-only")):
        raise SystemExit("--reuse-vision / --figure-only do not run the vision engine; use engine.run directly")
    S.run_stream = _tap                   # run_vision imports run_stream from the module at call time
    from engine import run as R
    try:
        R.main(["--mode", "demo", *argv])
    finally:
        S.run_stream = _run_stream
    demo_path = OUT / "demo_run.json"
    V = json.loads(demo_path.read_text())["vision"]
    if V.get("call_source") != "frozen_model_live":
        raise SystemExit(f"demo ran with call_source={V.get('call_source')}, expected frozen_model_live")
    amend_players_text(demo_path)
    tr = write_trace(TRACE, argv)
    print(f"wrote {TRACE} ({len(tr['frames'])} frames, {len(tr['decisions'])} decision frames, "
          f"{len(tr['events'])} CallEvents)", flush=True)


if __name__ == "__main__":
    main()
