"""GPU benchmark of the streaming call engine on a real 120 fps OpenTTGames test clip (paper only).

Every run streams the same clip (default test_2 frames 2000-2999, 1920x1080 H.264, decoded with PyAV as
detect.py did) through the full engine: decode + resize (reader thread), normalise + upload, BlurBall,
blobs, causal tracker, online flight segmentation, features, frozen HGB, call rule. Nothing is retrained.

  decode      the reader alone, as fast as it goes (the ceiling any engine config can reach)
  max         frames as fast as the engine takes them: sustained fps of the whole pipeline
  realtime    frames arrive at 120 fps (paced as a live feed); call_ready_ms = arrival of frame t ->
              decision for t done. If the engine keeps up there is no backlog and this is the call latency.
  realtime@N  arrivals at N fps < sustained fps (only for configs that cannot keep up with 120 fps):
              the no-backlog call latency of that config

Configs: precision fp16 (torch autocast, as the offline detector ran) and fp32 (strict, TF32 off), eager
or CUDA-graph replay, detector batch B (B windows per call; B > 1 waits for B frames) and dynamic batching
(up to B: run whatever is queued, so batch 1 while keeping up). The best batch is the B with the highest
max-mode fps for that precision / graph setting.

Usage (HiPerGator, repo root, after export_frozen.py):
  python -m engine.vision.bench_gpu --blurball_root $ROOT/ext/blurball --source $ROOT/openttgames/test_2.mp4 \\
      --video test_2 --start-frame 2000 --max-frames 1000 --out results/engine/vision_bench_gpu.json \\
      [--specs "torch-cuda;torch-cuda-cl-fuse-compile;..."]      # backend specs: see stream.make_backend
  python -m engine.vision.bench_gpu --merge a.json b.json --out results/engine/vision_bench_gpu.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from .events import assert_paper_only
from .run_demo import detection_check, match_events, offline_comparison, segmentation_check
from .stream import (FROZEN_PATH, REPO, FrameSource, VisionCallEngine, load_frozen, load_geometry, make_backend,
                     pct, run_stream, summarize, tracking_modules)

OUT = REPO / "results" / "engine" / "vision_bench_gpu.json"
SOURCE_FPS = 120.0


def env_info():
    import torch
    info = dict(host=socket.gethostname(), slurm_job=os.environ.get("SLURM_JOB_ID"),
                cpus=len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count(),
                python=platform.python_version(), torch=torch.__version__, cuda=torch.version.cuda,
                cudnn=torch.backends.cudnn.version())
    try:
        import av
        info["pyav"] = av.__version__
    except ImportError:
        pass
    try:
        info["cpu_model"] = next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except (OSError, StopIteration):
        info["cpu_model"] = platform.processor()
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        info.update(gpu=torch.cuda.get_device_name(0), gpu_mem_gb=round(p.total_memory / 2 ** 30, 1),
                    gpu_sm=f"{p.major}.{p.minor}", gpu_count_visible=torch.cuda.device_count())
        try:
            info["nvidia_smi"] = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,driver_version,clocks.max.sm,power.limit,pcie.link.gen.current",
                 "--format=csv,noheader"], capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return info


def decode_only(a, D):
    src = FrameSource(a.source, D, realtime=False, max_frames=a.max_frames, start_frame=a.start_frame).start()
    t = time.time()
    dec, rs, n = [], [], 0
    while True:
        it = src.q.get()
        if it is None:
            break
        dec.append(it[3])
        rs.append(it[4])
        n += 1
    wall = time.time() - t
    if "error" in src.info:
        raise RuntimeError(src.info["error"])
    return dict(frames=n, fps=round(n / wall, 1), decode_ms=pct(dec), resize_ms=pct(rs),
                pts_index_mismatch=src.info.get("pts_index_mismatch"))


def one_run(backend, frozen, geo, a, D, mode, batch, dynamic, checks=False):
    eng = VisionCallEngine(backend, frozen, geo, fps=SOURCE_FPS, frame_offset=a.start_frame, batch=batch)
    pace = None if mode == "max" else (float(mode.split("@")[1]) if "@" in mode else SOURCE_FPS)
    src = FrameSource(a.source, D, realtime=pace is not None, fps=pace, max_frames=a.max_frames,
                      start_frame=a.start_frame).start()
    t = time.time()
    rows, skipped = run_stream(eng, src, None, dynamic=dynamic)
    wall = time.time() - t
    if "error" in src.info:
        raise RuntimeError(f"reader failed: {src.info['error']}")
    s = summarize(rows, wall, skipped, eng)
    s.update(mode=mode, arrival_fps=pace, dynamic=dynamic, frames_read=src.info.get("read", 0),
             source_dropped=src.info.get("dropped", 0), reader_late_ms=src.info.get("reader_late_ms"),
             pts_index_mismatch=src.info.get("pts_index_mismatch"),
             graph_error=getattr(backend, "graph_error", None))
    s["events"] = [dict(call=e.call, frame=e.frame, p_miss=round(e.p_miss, 4), lead_pred_ms=round(e.lead_ms, 1),
                        latency_ms=round(e.latency_ms, 2)) for e in eng.events]
    s["event_latency_ms"] = pct([e.latency_ms for e in eng.events])
    if checks:
        f_lo, f_hi = a.start_frame, a.start_frame + s["frames_read"]
        s["detection_vs_labels"] = detection_check(eng.track_log, a.video)
        s["vs_offline"] = offline_comparison(eng, frozen, a.video, f_lo, f_hi)
        s["segmentation_vs_offline"] = segmentation_check(eng, a.video, f_lo, f_hi, geo)
        s["events_vs_labels"], s["flights_in_clip"] = match_events(eng.events, frozen, a.video, f_lo, f_hi)
    return s


DYN_MAX = 8


def reset_graphs(be):
    """Free captured CUDA graphs (each holds its own memory pool) before switching batch size."""
    if getattr(be, "graphs", None):
        be.graphs.clear()
        import torch
        torch.cuda.empty_cache()


def keeps_up(rt):
    """No growing backlog at 120 fps arrivals: nothing dropped, every frame processed, and the queue wait stays
    below 4 frame intervals at the 99th percentile."""
    return bool(rt and rt["source_dropped"] == 0 and rt["frames"] == rt["frames_read"]
                and (rt["qwait_ms"].get("p99", 1e9) <= 4 * 1000 / SOURCE_FPS))


def g(d, *ks):
    for k in ks:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def headline(runs):
    """One row per (precision, graph, batch label): the numbers the README quotes."""
    rows = []
    for key, r in runs.items():
        if r["mode"] != "realtime":
            continue
        cfg = r["config"]
        mx = runs.get(f"{cfg['spec']}|B{cfg['batch']}|max")
        nb = r if keeps_up(r) else next((v for k, v in runs.items()
                                          if k.startswith(f"{cfg['spec']}|B{cfg['batch']}{'d' if cfg['dynamic'] else ''}|realtime@")), None)
        rows.append(dict(
            spec=cfg["spec"], backend=cfg.get("backend"), job=cfg.get("job"),
            precision=cfg["precision"], cuda_graph=cfg["graph"], batch=cfg["batch"], dynamic=cfg["dynamic"],
            pool=cfg.get("pool", 1), best_batch_for_config=cfg.get("is_best", False),
            fps_sustained_max=(mx["fps_sustained"] if mx else None),
            keeps_up_with_120fps=keeps_up(r),
            realtime_dropped=r["source_dropped"], realtime_qwait_ms_p99=g(r, "qwait_ms", "p99"),
            stage_ms_p50=dict(decode=g(r, "decode_ms", "p50"), resize=g(r, "resize_ms", "p50"),
                              normalize_upload=g(r, "norm_ms", "p50"), detect=g(r, "detect_ms", "p50"),
                              detector_call_full_batch=g(r, "detector_call_ms", str(cfg["batch"]), "p50"),
                              track=g(r, "track_ms", "p50"),
                              features_per_decision=g(r, "per_decision_ms", "features", "p50"),
                              classify_per_decision=g(r, "per_decision_ms", "classifier", "p50")),
            stage_ms_mean_per_frame=dict(decode=g(r, "decode_ms", "mean"), resize=g(r, "resize_ms", "mean"),
                                         normalize_upload=g(r, "norm_ms", "mean"), detect=g(r, "detect_ms", "mean"),
                                         track=g(r, "track_ms", "mean"), features=g(r, "feat_ms", "mean"),
                                         classify=g(r, "clf_ms", "mean"), engine_total=g(r, "proc_ms", "mean")),
            call_latency_no_backlog_ms=(None if nb is None else dict(
                arrival_fps=nb["arrival_fps"], p50=g(nb, "call_ready_ms", "p50"), p90=g(nb, "call_ready_ms", "p90"),
                p99=g(nb, "call_ready_ms", "p99"), max=g(nb, "call_ready_ms", "max"))),
            call_latency_at_120fps_ms=dict(p50=g(r, "call_ready_ms", "p50"), p90=g(r, "call_ready_ms", "p90"),
                                           max=g(r, "call_ready_ms", "max")),
            emitted_calls=len(r["events"]), emitted_call_latency_ms=r.get("event_latency_ms")))
    return rows


def merge(paths, out):
    """One file from several benchmark jobs: a backend spec measured in a later file replaces all of its earlier
    runs; each job's environment is kept under `jobs`; the headline is recomputed."""
    res = None
    for p in paths:
        d = json.load(open(p))
        job = d["env"].get("slurm_job")
        if res is None:
            res = d
            res["jobs"] = {}
        else:   # a spec measured again replaces every earlier run of that spec (realtime@N keys can differ)
            again = {k.split("|")[0] for k in d["runs"]}
            gone = {k: v for k, v in res["runs"].items() if k.split("|")[0] in again}
            for k, v in gone.items():   # keep a trace of what was replaced: job, fps, call latency
                j = res["jobs"].setdefault(str((v.get("config") or {}).get("job")), {})
                j.setdefault("replaced_runs", {})[k] = dict(fps_sustained=v.get("fps_sustained"),
                                                             call_ready_ms=v.get("call_ready_ms"),
                                                             replaced_by_job=str(job))
            res["runs"] = {k: v for k, v in res["runs"].items() if k not in gone}
            res["runs"].update(d["runs"])
        res["jobs"].setdefault(str(job), {}).update(env=d["env"], decode_only=d.get("decode_only"), when=d.get("when"))
    res["headline"] = headline(res["runs"])
    json.dump(res, open(out, "w"), indent=1, default=float)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if len(sys.argv) > 1 and sys.argv[1] == "--merge":
        ap.add_argument("--merge", nargs="+", required=True, help="benchmark JSONs, later ones win")
        ap.add_argument("--out", required=True)
        a = ap.parse_args()
        for r in merge(a.merge, a.out)["headline"]:
            print(json.dumps(r))
        return
    ap.add_argument("--source", required=True)
    ap.add_argument("--video", default="test_2")
    ap.add_argument("--start-frame", type=int, default=2000)
    ap.add_argument("--max-frames", type=int, default=1000)
    ap.add_argument("--blurball_root", default=os.environ.get("BLURBALL_ROOT"))
    ap.add_argument("--precisions", default="fp16,fp32")
    ap.add_argument("--graphs", default="0,1", help="CUDA-graph settings to run (0 eager, 1 graph)")
    ap.add_argument("--batches", default="1,2,4,8,16,32")
    ap.add_argument("--frozen", default=str(FROZEN_PATH))
    ap.add_argument("--device", default="cuda", help="cuda (mps / cpu only for a local smoke test)")
    ap.add_argument("--specs", default=None, help="';'-separated backend specs instead of precisions x graphs, "
                    "e.g. 'torch-cuda-cl-fuse;torch-cuda-cl-fuse-graph;torch-cuda-cl,torch-cuda-cl' (a ',' pool "
                    "pipelines windows over two model copies on the same GPU, batch 1)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    assert_paper_only()
    M = tracking_modules()
    D = M.D
    frozen = load_frozen(a.frozen)
    geo, geo_prov = load_geometry(a.video, frozen)
    res = dict(what="engine.vision streaming call engine on one GPU, real 120 fps OpenTTGames clip (paper only)",
               when=datetime.datetime.now().isoformat(timespec="seconds"), env=env_info(),
               clip=dict(source=a.source, video=a.video, first_frame=a.start_frame, frames=a.max_frames,
                         fps=SOURCE_FPS, resolution="1920x1080"),
               frozen_model=dict(path=a.frozen, source=frozen["model_source"], check_max_abs_err=frozen["check_max_abs_err"],
                                 tau_online=frozen["tau_online"], tau_snapshot=frozen["tau_snapshot"]),
               geometry=geo_prov, runs={})
    print(json.dumps(res["env"], indent=1), flush=True)
    res["decode_only"] = decode_only(a, D)
    print("decode only:", res["decode_only"], flush=True)

    def save():
        res["headline"] = headline(res["runs"])
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump(res, open(a.out, "w"), indent=1, default=float)

    batches = [int(b) for b in a.batches.split(",")]
    if a.specs:
        specs = a.specs.split(";")
    else:
        specs = [f"torch-{a.device}" + ("-fp32" if prec == "fp32" else "") + ("-graph" if graph else "")
                 for prec in a.precisions.split(",") for graph in [bool(int(g)) for g in a.graphs.split(",")]]
    for spec in specs:
        be = make_backend(spec, a.blurball_root)
        bes = be if isinstance(be, list) else [be]
        pool = len(bes) > 1
        prec = "fp32" if "fp32" in spec else ("tf32" if "tf32" in spec else "fp16")
        graph = "graph" in spec
        name = "+".join(b.name for b in bes)
        errs = {k: getattr(bes[0], k, None) for k in ("fuse_error", "compile_error")}

        def cfg(B, dyn):
            return dict(spec=spec, precision=prec, graph=graph, batch=B, dynamic=dyn, backend=name,
                        pool=len(bes), job=os.environ.get("SLURM_JOB_ID"), gpu=res["env"].get("gpu"),
                        **{k: v for k, v in errs.items() if v}, graph_error=getattr(bes[0], "graph_error", None))

        def warm(sizes):
            for x in bes:
                reset_graphs(x)
                x.warmup(sizes)
        best = (None, -1.0)
        for B in ([1] if pool else batches):
            try:
                t_w = time.time()
                warm((B,))
                t_w = time.time() - t_w
                s = one_run(be, frozen, geo, a, D, "max", B, False, checks=(B == 1))
            except RuntimeError as e:    # e.g. out of memory at a large batch
                print(f"{spec} B{B} max failed: {e!r}", flush=True)
                res["runs"][f"{spec}|B{B}|max"] = dict(error=repr(e), config=cfg(B, False))
                break
            s["config"] = cfg(B, False)
            s["warmup_s"] = round(t_w, 1)
            res["runs"][f"{spec}|B{B}|max"] = s
            print(f"{spec:24s} B{B:<3d} max  fps {s['fps_sustained']:7.1f}  detector call p50 "
                  f"{s['detector_call_ms'].get(str(B), {}).get('p50')} ms  engine/frame mean {s['proc_ms'].get('mean')} ms"
                  f"  (warmup {t_w:.1f} s{', ' + str(errs) if any(errs.values()) else ''})", flush=True)
            if s["fps_sustained"] > best[1]:
                best = (B, s["fps_sustained"])
            save()
        Bb = best[0]
        if Bb is None:
            continue
        res["runs"][f"{spec}|B{Bb}|max"]["config"]["is_best"] = True
        # dynamic batching up to min(best, DYN_MAX): a CUDA graph per possible group size is captured
        cfgs = [(1, False)] + ([(Bb, False)] if Bb > 1 else []) + ([(min(Bb, DYN_MAX), True)] if Bb > 1 else [])
        for B, dyn in cfgs:
            warm(tuple(range(1, B + 1)) if dyn else (B,))
            lab = f"{spec}|B{B}{'d' if dyn else ''}"
            s = one_run(be, frozen, geo, a, D, "realtime", B, dyn, checks=(B == 1))
            s["config"] = dict(cfg(B, dyn), is_best=(B == Bb))
            res["runs"][f"{lab}|realtime"] = s
            print(f"{lab:28s} realtime fps {s['fps_sustained']:6.1f} dropped {s['source_dropped']} qwait p99 "
                  f"{s['qwait_ms'].get('p99')} call_ready p50/p90 {s['call_ready_ms'].get('p50')}/"
                  f"{s['call_ready_ms'].get('p90')} ms, keeps up: {keeps_up(s)}", flush=True)
            if not keeps_up(s):     # no-backlog latency at an arrival rate this config sustains
                mx = res["runs"].get(f"{spec}|B{B}|max", {}).get("fps_sustained") or 60.0
                n = max(1, int(0.8 * mx))
                s2 = one_run(be, frozen, geo, a, D, f"realtime@{n}", B, dyn)
                s2["config"] = s["config"]
                res["runs"][f"{lab}|realtime@{n}"] = s2
                print(f"{lab:28s} realtime@{n} call_ready p50/p90 {s2['call_ready_ms'].get('p50')}/"
                      f"{s2['call_ready_ms'].get('p90')} ms", flush=True)
            save()
        del be, bes
        import torch
        torch.cuda.empty_cache()
    save()
    for r in res["headline"]:
        print(json.dumps(r), flush=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
