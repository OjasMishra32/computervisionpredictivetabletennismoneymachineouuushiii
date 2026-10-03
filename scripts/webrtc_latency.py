"""Aggregate a repeated WebRTC latency campaign (scripts/webrtc_demo.sh with REPS >= 5) into
results/webrtc/latency.json and results/webrtc/fig_webrtc_latency.png.

Paper only. Our own held-out OpenTTGames clip (test_2 frames 2000-2999, CC BY-NC-SA 4.0), streamed by us over
loopback WebRTC (MediaMTX on 127.0.0.1) into the unchanged vision engine. Not a match feed, no camera.

Settings (one per preset; every preset ran REPS times, interleaved, in one campaign file):
  30fps   dec30      every 4th source frame at 30 fps, real time; engine track-only (detector + tracker)
  60fps   dec60      every 2nd source frame at 60 fps, real time; engine track-only
  120fps  native120  every source frame at 120 fps, real time; engine with the frozen call model
  120fps_keepup  slowmo10  every source frame at 10 frames/s of wall time: the engine is never behind, so this
                 is the latency of the pipeline when compute keeps up (calls valid: 120 fps time base)

Per frame (report.py defines every stamp; all wall clock on one host):
  video leg (glass-to-glass proxy)   t_handoff - t_due      capture -> decoded frame in our process
  decode -> model                    t_decision - t_handoff decoded frame -> engine decision ready for this frame
     model part                      ... minus the call rule time on that frame (prep, queue, detector, tracker)
     call rule part                  feat_ms + clf_ms on that frame (flight features + frozen classifier)
  capture -> decision                t_decision - t_due     (frame-send -> detection in track-only runs)
  capture -> emit                    t_emit - t_due         per CallEvent (call runs)
Camera capture is NOT in the loop (virtual camera); it enters only as a labelled assumption (CAPTURE below).

Usage: python scripts/webrtc_latency.py results/webrtc/run_<campaign ts>.jsonl [--probe run_<ts>.jsonl ...]
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "results" / "webrtc"
FILE_RUN = REPO / "results" / "engine" / "demo_run.json"
FLIGHTS = REPO / "results" / "tracking" / "test_flights.csv"
SWEEP_JSON = REPO / "results" / "tier0" / "latency_sweep.json"
SWEEP_MD = REPO / "research" / "v2" / "feed_latency" / "LATENCY_SWEEP.md"
CLIP = "data/vision/test_2_copyts.mp4 (OpenTTGames test_2 frames 2000-2999, 120 fps, CC BY-NC-SA 4.0)"

SETTINGS = {   # key -> (preset, camera fps used for the capture assumption, label)
    "30fps": ("dec30", 30, "30 fps, real time"),
    "60fps": ("dec60", 60, "60 fps, real time"),
    "120fps": ("native120", 120, "120 fps, real time"),
    "120fps_keepup": ("slowmo10", 120, "120 fps content, engine keeps up (fed 10 frames/s)"),
}

# Camera-capture budget: an ASSUMPTION, not measured here (our loop has no physical camera).
#  - sampling: an event waits up to one frame period for the exposure that captures it; Bachhuber & Steinbach
#    model the camera sampling delay as uniform over one frame period (ICIP 2016, arXiv:1510.01134; their G2G
#    min/mean/max was 24.8/50.4/78.7 ms at 25 Hz and 8.1/15.5/23 ms at 300 Hz, IEEE 1394 camera + display).
#  - readout + transfer to the host: one more frame period (assumption for a USB3 / GigE machine-vision camera).
#  - sensitivity: a consumer 30 fps USB webcam, "the camera itself and the USB bus (~100 ms)" (Transitive
#    Robotics, 2026, a vendor measuring its own product; SUB_SECOND_ROUTES.md S4).
CAPTURE = dict(
    rule="2 frame periods: 1 for sampling (upper bound; mean 0.5) + 1 for sensor readout and USB3/GigE transfer",
    label="ASSUMED (literature), not measured: our loop starts at a virtual camera",
    sources=[
        "Bachhuber C., Steinbach E., 'A system for high precision glass-to-glass delay measurements in video "
        "communication', ICIP 2016, arXiv:1510.01134: camera sampling delay uniform over one frame period; G2G "
        "min/mean/max 24.8/50.4/78.7 ms at 25 Hz and 8.1/15.5/23 ms at 300 Hz",
        "Transitive Robotics, 'WebRTC latency breakdown' (2026-05-06, vendor): 'the camera itself and the USB bus "
        "(~100 ms)' for a 30 fps webcam (research/home_stream/SUB_SECOND_ROUTES.md S4)",
    ],
    webcam_30fps_sensitivity_ms=100.0,
)


def capture_ms(fps):
    return 2000.0 / fps


def pct(a, qs=(50, 90, 99)):
    a = np.asarray([x for x in a if x is not None], float)
    a = a[np.isfinite(a)]
    if not len(a):
        return None
    d = {f"p{q}": round(float(np.percentile(a, q)), 2) for q in qs}
    d.update(mean=round(float(a.mean()), 2), max=round(float(a.max()), 2), n=int(len(a)))
    return d


def load(paths):
    runs = defaultdict(lambda: dict(meta=None, frames=[], calls=[], summary=None, track=[], saved=None, file=None))
    for p in paths:
        for line in open(p):
            r = json.loads(line)
            run = r.get("run")
            R = runs[run]
            R["file"] = str(Path(p).relative_to(REPO)) if Path(p).is_absolute() else str(p)
            t = r.get("type")
            if t == "meta":
                R["meta"] = r
            elif t == "frame":
                if r.get("flags") is not None and r["flags"] & 2:
                    R["frames"].append(r)
            elif t == "call":
                R["calls"].append(r)
            elif t == "summary":
                R["summary"] = r
            elif t == "track":
                R["track"].append(r)
            elif t == "saved_frames":
                R["saved"] = r
    return runs


def ms(r, end, start):
    if r.get(end) is None or r.get(start) is None:
        return None
    return (r[end] - r[start]) * 1e3


def frame_legs(fr):
    """Per clip frame -> dict of legs (ms)."""
    out = []
    for r in fr:
        d = dict(video=ms(r, "t_handoff", "t_due"), net=ms(r, "t_complete", "t_due"), decode=ms(r, "t_dec1", "t_dec0"),
                 sender_late=ms(r, "t_w0", "t_due"), prep=ms(r, "t_ready", "t_handoff"),
                 eng=ms(r, "t_decision", "t_handoff"), c2d=ms(r, "t_decision", "t_due"),
                 qwait=r.get("qwait_ms"), infer=r.get("infer_ms"), key=r.get("key"))
        rule = None
        if r.get("feat_ms") is not None:
            rule = (r.get("feat_ms") or 0.0) + (r.get("clf_ms") or 0.0)
        d["rule"] = rule
        d["model"] = (d["eng"] - (rule or 0.0)) if d["eng"] is not None else None
        out.append(d)
    return out


def drops(R):
    s = R["summary"] or {}
    f = s.get("frames", {})
    eng = s.get("engine") or {}
    rec = s.get("receiver") or {}
    sent = f.get("sent_clip", 0)
    d = dict(sent=sent, received=f.get("received_clip"), lost_in_transport=f.get("lost_clip"),
             bad_code=f.get("bad_code"))
    if R["meta"] and R["meta"].get("mode") == "engine":
        d.update(skipped_before_prep=f.get("skipped_before_prep"), receiver_queue_full=rec.get("dropped"),
                 skipped_by_engine_bound=eng.get("skipped"), processed_by_engine=f.get("engine_processed"),
                 decisions=f.get("engine_decisions"))
        d["not_processed"] = sent - (f.get("engine_processed") or 0)
        d["not_processed_share"] = round(d["not_processed"] / sent, 4) if sent else None
    return d


def flights_offline(lo, hi):
    import pandas as pd
    tf = pd.read_csv(FLIGHTS)
    import pickle
    fz = pickle.load(open(REPO / "models" / "vision" / "frozen_call_model.pkl", "rb"))
    tau_snap = float(fz["tau_snapshot"])
    rows = []
    for r in tf[(tf.video == "test_2") & (tf.t0 >= lo) & (tf.t_ref < hi)].itertuples():
        if np.isfinite(r.first_call_lead_ms):
            call, frame = "MISS", int(round(r.t_ref - r.first_call_lead_ms * 120 / 1000))
        else:
            call = "BOUNCE" if r.p_miss_at_50ms < tau_snap else "MISS"
            frame = int(round(r.t_ref - 6))     # the offline snapshot at T_ref - 50 ms
        rows.append(dict(f_net=int(r.f_net), dir=int(r.dir), label=r.label, t0=int(r.t0), t_ref=int(r.t_ref),
                         offline_call=call, offline_frame=frame,
                         offline_rule=("online rule, first call" if np.isfinite(r.first_call_lead_ms)
                                       else f"snapshot at T_ref - 50 ms, P(miss) {r.p_miss_at_50ms:.3f} vs tau {tau_snap:.4f}")))
    return rows


def assign(calls, flights):
    """CallEvents -> {f_net: (call, frame)} with run_demo.match_events' window (t0 - 2 .. t_ref + 12, same direction)."""
    out, extra = {}, []
    for c in calls:
        d = c.get("direction")
        cand = [f for f in flights if f["t0"] - 2 <= c["frame"] <= f["t_ref"] + 12 and (d is None or np.sign(f["dir"]) == d)]
        if cand:
            f = min(cand, key=lambda f: abs(f["t_ref"] - c["frame"]))
            out.setdefault(f["f_net"], (c["call"], int(c["frame"])))
        else:
            extra.append((c["call"], int(c["frame"])))
    return out, extra


def file_source_calls():
    v = json.load(open(FILE_RUN))["vision"]
    return [dict(call=e["call"], frame=int(e["frame"]), direction=e.get("direction")) for e in v["events"]]


def compare_calls(R, flights, file_calls):
    got = [dict(call=c["call"], frame=int(c["frame"]), direction=c.get("direction")) for c in R["calls"]]
    last = 2000 + len(R["frames"]) - 1
    fc = [c for c in file_calls if c["frame"] <= last]
    same_file = [g for g in got if any(g["call"] == f["call"] and abs(g["frame"] - f["frame"]) <= 2 for f in fc)]
    on_flight, extra = assign(got, flights)
    per = []
    for f in flights:
        w = on_flight.get(f["f_net"])
        per.append(dict(f_net=f["f_net"], label=f["label"], offline=f["offline_call"], offline_frame=f["offline_frame"],
                        webrtc=(w[0] if w else None), webrtc_frame=(w[1] if w else None),
                        agree=(w is not None and w[0] == f["offline_call"])))
    miss_off = [f for f in flights if f["offline_call"] == "MISS"]
    return dict(calls=[(g["call"], g["frame"]) for g in got],
                n_calls=len(got), file_source_calls=len(fc), same_as_file_source_within_2_frames=len(same_file),
                identical_to_file_source=(len(same_file) == len(got) == len(fc)),
                only_webrtc=[(g["call"], g["frame"]) for g in got if g not in same_file],
                only_file=[(f["call"], f["frame"]) for f in fc
                           if not any(g["call"] == f["call"] and abs(g["frame"] - f["frame"]) <= 2 for g in got)],
                labelled_flights=len(flights), flights_called=sum(1 for p in per if p["webrtc"]),
                flights_agree_with_offline=sum(1 for p in per if p["agree"]),
                offline_miss_calls_reproduced=sum(1 for f in miss_off if on_flight.get(f["f_net"], ("",))[0] == "MISS"),
                offline_miss_calls=len(miss_off),
                calls_outside_labelled_flights=extra, per_flight=per)


def setting_block(key, runs_t, runs_e):
    preset, fps, label = SETTINGS[key]
    blk = dict(label=label, preset=preset, camera_fps=fps, capture_assumed_ms=round(capture_ms(fps), 2))
    if runs_t:
        L = [frame_legs(R["frames"]) for R in runs_t]
        allv = [x["video"] for l in L for x in l]
        blk["transport_only"] = dict(
            runs=[R["meta"]["label"] for R in runs_t], n_runs=len(runs_t),
            load_avg_start=[R["meta"]["load_avg_start"][0] for R in runs_t],
            video_leg_ms=pct(allv), video_leg_p50_per_run=[pct([x["video"] for x in l])["p50"] for l in L],
            capture_to_frame_complete_ms=pct([x["net"] for l in L for x in l]),
            decode_ms=pct([x["decode"] for l in L for x in l]),
            sender_late_ms=pct([x["sender_late"] for l in L for x in l]),
            video_leg_I_ms=pct([x["video"] for l in L for x in l if x["key"]]),
            video_leg_P_ms=pct([x["video"] for l in L for x in l if not x["key"]]),
            drops=[drops(R) for R in runs_t])
        tot = blk["transport_only"]["drops"]
        blk["transport_only"]["frames_lost_total"] = f"{sum(d['lost_in_transport'] or 0 for d in tot)}/{sum(d['sent'] for d in tot)}"
    if runs_e:
        L = [frame_legs(R["frames"]) for R in runs_e]
        fl = [x for l in L for x in l]
        dec = [x for x in fl if x["eng"] is not None]
        rule = [x["rule"] for x in dec if x["rule"]]       # frames on which the call rule ran (a flight was live)
        calls = [c for R in runs_e for c in R["calls"]]
        m0 = runs_e[0]["meta"]
        dr = [drops(R) for R in runs_e]
        sent = sum(d["sent"] for d in dr)
        notp = sum(d["not_processed"] for d in dr)
        blk["engine"] = dict(
            runs=[R["meta"]["label"] for R in runs_e], n_runs=len(runs_e), backend=m0.get("backend"),
            calls_on=m0.get("calls"), calls_valid=m0.get("calls_valid"), max_lag_ms=m0.get("max_lag_ms"),
            arrival_fps=m0.get("arrival_fps"), load_avg_start=[R["meta"]["load_avg_start"][0] for R in runs_e],
            video_leg_ms=pct([x["video"] for x in fl]),
            video_leg_p50_per_run=[(pct([x["video"] for x in l]) or {}).get("p50") for l in L],
            decode_to_model_ms=pct([x["eng"] for x in dec]),
            decode_to_model_parts_ms=dict(prep_crop_resize=pct([x["prep"] for x in dec]),
                                          queue_wait=pct([x["qwait"] for x in dec]),
                                          detector_call=pct([x["infer"] for x in dec]),
                                          model_excl_call_rule=pct([x["model"] for x in dec]),
                                          call_rule_on_flight_frames=pct(rule)),
            capture_to_decision_ms=pct([x["c2d"] for x in dec]),
            capture_to_decision_p50_per_run=[(pct([x["c2d"] for x in l if x["c2d"] is not None]) or {}).get("p50")
                                             for l in L],
            capture_to_emit_ms=pct([c.get("capture_to_emit_ms") for c in calls]) if calls else None,
            calls_per_run=[len(R["calls"]) for R in runs_e],
            drops=dr, frames_not_processed_total=f"{notp}/{sent}",
            frames_not_processed_share=round(notp / sent, 4) if sent else None)
        e = blk["engine"]
        c2x = e["capture_to_emit_ms"] if (calls and m0.get("calls_valid")) else e["capture_to_decision_ms"]
        blk["frame_send_to_result"] = dict(
            what=("frame-send (capture) -> CallEvent emit" if (calls and m0.get("calls_valid"))
                  else "frame-send (capture of frame k) -> decision ready for frame k (ball positions final through "
                       "k-2; NOT frame k's own detection, which needs frames k+1 and k+2)"),
            **{k: c2x[k] for k in ("p50", "p90", "p99", "n")})
        # frame k's own ball position is final at frame k+2's decision step (the detector's 3-frame windows):
        # the "capture -> detection of that frame" latency, 2 frame periods more than the decision-ready leg
        own = []
        for R in runs_e:
            step = R["meta"]["step"]
            by = {r["src"]: r for r in R["frames"]}
            for r in R["frames"]:
                g = by.get(r["src"] + 2 * step)
                if g is not None and g.get("t_decision") is not None and r.get("t_due") is not None:
                    own.append((g["t_decision"] - r["t_due"]) * 1e3)
        e["capture_to_own_position_final_ms"] = pct(own)
        e["capture_to_own_position_final_note"] = (
            "capture of frame k -> frame k's ball position final (window k, k+1, k+2 run); in the 10 frames/s "
            "keep-up setting k+1 and k+2 arrive 100 ms apart, so this leg is not meaningful there")
        e["decision_share_of_sent"] = round(len(dec) / sent, 4) if sent else None
        cap = capture_ms(fps)
        blk["camera_to_result_estimate_ms"] = dict(
            p50=round(cap + c2x["p50"], 1), p90=round(cap + c2x["p90"], 1), p99=round(cap + c2x["p99"], 1),
            note=f"assumed capture {cap:.1f} ms (2 frame periods at {fps} fps) + measured frame-send -> result")
        # stacked-bar parts (p50 of each leg over decision frames; call rule: p50 over frames where it ran)
        blk["stack_p50_ms"] = dict(capture_assumed=round(cap, 2),
                                   encode_network_decode=e["video_leg_ms"]["p50"],
                                   model=(pct([x["model"] for x in dec]) or {}).get("p50"),
                                   call_rule=(pct(rule) or {}).get("p50") if rule else None)
    return blk


def sweep_plug(keep, rt120=None):
    """How the measured pipeline enters the tier-0 latency sweep. The sweep's V is the delay from the event to the
    frame reaching our CV (camera + transport); its model then adds 20 ms of CV inference. So our measurement maps
    to V = capture (assumed) + WebRTC leg (measured), plus whatever our CV takes beyond the modelled 20 ms."""
    import pandas as pd
    d = json.load(open(SWEEP_JSON))
    be = d["breakeven_video_delay"]["tournament"]
    sw = pd.read_csv(REPO / "results" / "tier0" / "latency_sweep.csv")
    sw = sw[(sw.source == "video") & (sw.reading == "tournament") & (sw.cv == "own120")]
    curves = {per: sw[sw.period == per].drop_duplicates("x_s").sort_values("x_s") for per in ("IS", "burned_OOS")}

    def at(v):
        return {per: dict(usd_per_day=round(float(np.interp(v, c.x_s, c.pnl_per_day_usd)), 1),
                          c_per_share=round(float(np.interp(v, c.x_s, c.per_share_c)), 2)) for per, c in curves.items()}
    calls = [c for R in keep["_runs"] for c in R["calls"]]
    eng = float(np.median([c["latency_ms"] for c in calls])) / 1e3          # decoded frame -> CallEvent
    vid = float(np.median([c["capture_to_handoff_ms"] for c in calls])) / 1e3  # capture -> decoded frame
    cap = keep["capture_assumed_ms"] / 1e3
    extra = eng - 0.020
    rows = []
    for name, v_src, basis in (
            ("our own 120 fps camera, our WebRTC on one LAN (no relay)", cap + vid,
             f"capture {cap * 1e3:.1f} ms assumed + WebRTC leg {vid * 1e3:.1f} ms measured (loopback)"),
            ("our own camera through a public relay", 0.40, "about 0.4 s g2g via a public Broadcast Box server "
                                                             "(SUB_SECOND_ROUTES.md S2; others' setup, camera included)"),
            ("0.5 s row: licensed low-latency video at the best vendor claim", 0.50, "LATENCY_SWEEP.md row V = 0.5"),
            ("1 s row: licensed video / satellite TV low end", 1.00, "LATENCY_SWEEP.md row V = 1")):
        v_eff = v_src + extra
        rows.append(dict(source=name, V_source_s=round(v_src, 3), basis=basis,
                         V_effective_s=round(v_eff, 3), sweep_at_V_source=at(v_src), sweep_at_V_effective=at(v_eff)))
    return dict(
        source=str(SWEEP_JSON.relative_to(REPO)), doc=str(SWEEP_MD.relative_to(REPO)),
        model=d["model"]["video"], reading="tournament (headline), stamp lag 2.0 s; $/day interpolated on the 0.05 s grid",
        measured=dict(cv_decoded_to_call_s=round(eng, 4), cv_beyond_modelled_20ms_s=round(extra, 4),
                      webrtc_leg_s=round(vid, 4), capture_assumed_s=round(cap, 4),
                      from_runs=[R["meta"]["label"] for R in keep["_runs"]], n_calls=len(calls)),
        rows=rows,
        breakeven_V_s=dict(IS=be["IS"]["breakeven_V_s_seed_mean_curve"], OOS=be["burned_OOS"]["breakeven_V_s_seed_mean_curve"]),
        breakeven_source_delay_with_our_cv_s=dict(IS=round(be["IS"]["breakeven_V_s_seed_mean_curve"] - extra, 3),
                                                  OOS=round(be["burned_OOS"]["breakeven_V_s_seed_mean_curve"] - extra, 3)),
        caveats=["The sweep's own120 CV makes calls at 120 fps. Our laptop engine keeps up only at 30 fps "
                 "(track-only) or in slow motion; at 120 fps real time it did not process "
                 f"{(rt120 or {}).get('engine', {}).get('frames_not_processed_total', '?')} frames and made "
                 f"{sum((rt120 or {}).get('engine', {}).get('calls_per_run', [])) or 'no'} calls. "
                 "A host that sustains 120 fps is needed (the HiPerGator L4 sustained 194 fps in "
                 "results/engine/vision_bench_gpu.json).",
                 "We have no camera at any venue: V for a real match is set by whoever owns the camera, not by this "
                 "pipeline. The first row is a reference point, not an available route."])


def figure(blocks, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    plt.rcParams.update({"font.family": "Helvetica", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.edgecolor": "#8a8984", "axes.labelcolor": "#52514e",
                         "xtick.color": "#52514e", "ytick.color": "#52514e", "figure.facecolor": "#fcfcfb",
                         "axes.facecolor": "#fcfcfb"})
    C = dict(capture="#d9d8d3", video="#2a78d6", model="#eb6834", rule="#1baf7a")
    keys = [k for k in SETTINGS if "stack_p50_ms" in blocks[k]]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.6), gridspec_kw=dict(width_ratios=[1.15, 1]))
    xs = np.arange(len(keys))
    w = 0.56
    rule_ref = next((blocks[k]["stack_p50_ms"]["call_rule"] for k in ("120fps_keepup", "120fps")
                     if blocks.get(k, {}).get("stack_p50_ms", {}).get("call_rule")), None)
    tops = []
    for i, k in enumerate(keys):
        s = blocks[k]["stack_p50_ms"]
        rule = s["call_rule"]
        rule_hatch = rule is None
        parts = [(s["capture_assumed"], C["capture"], "////"), (s["encode_network_decode"], C["video"], None),
                 (s["model"], C["model"], None), ((rule if rule else (rule_ref or 0.0)), C["rule"], "xx" if rule_hatch else None)]
        y = 0.0
        for v, col, h in parts:
            ax.bar(xs[i], v, w, bottom=y, color=col, edgecolor="#fcfcfb", linewidth=2, hatch=h)
            y += v
        tops.append(y)
        e = blocks[k]["camera_to_result_estimate_ms"]
        dropped = blocks[k]["engine"]["frames_not_processed_share"]
        txt = f"{e['p50']:.0f} ms p50\n{e['p90']:.0f} ms p90"
        if dropped:
            txt += f"\n{dropped * 100:.0f}% frames\nnot processed"
        ax.text(xs[i], y + 3, txt, ha="center", va="bottom", fontsize=9, color="#0b0b0b")
    ax.set_xticks(xs, [blocks[k]["label"].replace(", ", ",\n").replace(" (", "\n(") for k in keys], fontsize=9)
    ax.set_ylabel("milliseconds (p50 of each leg)")
    ax.set_ylim(0, max(tops) * 1.75)
    ax.grid(axis="y", color="#e6e5e0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title("Where the time goes, camera to call (p50 per leg; labels: end-to-end p50 / p90)",
                 loc="left", fontsize=10.5, color="#0b0b0b")
    ax.legend(handles=[Patch(facecolor=C["capture"], hatch="////", edgecolor="#8a8984", label="camera capture (ASSUMED: 2 frame periods)"),
                       Patch(facecolor=C["video"], label="encode + WebRTC + decode (measured)"),
                       Patch(facecolor=C["model"], label="model: prep, queue, detector, tracker (measured)"),
                       Patch(facecolor=C["rule"], label="call rule: features + classifier (measured)"),
                       Patch(facecolor=C["rule"], hatch="xx", edgecolor="#fcfcfb",
                             label="call rule not run (track-only); cost from 120 fps runs")],
              loc="upper left", fontsize=8.2, frameon=False, ncol=2, columnspacing=1.2)
    # right: ECDF of measured frame-send -> decision ready, per setting
    grays = {"30fps": "#9b9a94", "60fps": "#6b6a65", "120fps": "#2f2e2b", "120fps_keepup": "#2a78d6"}
    styles = {"30fps": "-", "60fps": "-", "120fps": "-", "120fps_keepup": "--"}
    ends, lo, hi = [], 1e9, 0.0
    for k in keys:
        v = np.sort(np.asarray(blocks[k]["_c2d"], float))
        n_sent = sum(d["sent"] for d in blocks[k]["engine"]["drops"])
        yv = np.arange(1, len(v) + 1) / n_sent        # share of SENT frames: dropped frames never reach the curve
        ax2.plot(v, yv, styles[k], color=grays[k], linewidth=2)
        lo, hi = min(lo, v[0]), max(hi, v[-1])
        name = {"120fps_keepup": "120 fps content, keeps up"}.get(k, blocks[k]["label"].split(",")[0] + " real time")
        ends.append([float(np.percentile(v, 50)), yv[len(v) // 2], name, grays[k]])
    # direct labels at each curve's median, to its right, nudged apart vertically
    ends.sort(key=lambda e: e[1])
    for j in range(1, len(ends)):
        if ends[j][1] - ends[j - 1][1] < 0.07:
            ends[j][1] = ends[j - 1][1] + 0.07
    for x, y, name, col in ends:
        ax2.annotate(name, (x, y), xytext=(10, 0), textcoords="offset points", fontsize=8.5, color="#0b0b0b",
                     va="center", bbox=dict(boxstyle="round,pad=0.15", fc="#fcfcfb", ec="none", alpha=0.85))
    ax2.set_xscale("log")
    ax2.set_xlim(lo * 0.8, hi * 2.0)
    from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter
    ticks = [t for t in (20, 30, 50, 100, 200, 300, 500, 1000, 2000, 5000) if lo * 0.8 <= t <= hi * 2.0]
    ax2.xaxis.set_major_locator(FixedLocator(ticks))
    ax2.xaxis.set_major_formatter(ScalarFormatter())
    ax2.xaxis.set_minor_formatter(NullFormatter())
    ax2.set_ylim(0, 1.02)
    ax2.set_xlabel("frame capture (virtual camera) -> engine decision ready, ms (measured, log scale)")
    ax2.set_ylabel("share of frames SENT (frames dropped by the engine never arrive)")
    ax2.grid(color="#e6e5e0", linewidth=0.8)
    ax2.set_title("Measured latency distribution per frame, 5 runs pooled per setting", loc="left", fontsize=10.5,
                  color="#0b0b0b")
    fig.text(0.01, 0.012, "Our own clip (OpenTTGames test_2, CC BY-NC-SA 4.0) streamed by us over loopback WebRTC "
             "(x264 zerolatency -> MediaMTX -> aiortc) into the unchanged CV engine on one MacBook M4 shared with "
             "other jobs.\nNot a match feed. No physical camera: capture is an assumption (2 frame periods). "
             "30 / 60 fps: detector + tracker only. 120 fps real time: the engine bound (100 ms) skips frames, so no call "
             "survives; the keep-up bar carries the calls.", fontsize=8, color="#52514e")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def md_tables(out):
    """Markdown tables for research/webrtc/RESULTS.md, generated from latency.json (no hand transcription)."""
    f3 = lambda d: "n/a" if not d else f"{d['p50']:.1f} / {d['p90']:.1f} / {d['p99']:.1f}"
    f2 = lambda d: "n/a" if not d else f"{d['p50']:.1f} / {d['p90']:.1f}"
    L = ["| setting | runs (transport + engine) | load avg at start | video leg, transport only (p50 / p90 / p99 ms) | "
         "video leg with the engine running | decode -> model (p50 / p90) | frame-send -> result (p50 / p90 / p99) | "
         "result | frames not processed | calls per run | camera -> result, capture assumed (p50 / p90) |",
         "|" + "---|" * 11]
    for k, b in out["settings"].items():
        t, e = b.get("transport_only", {}), b.get("engine", {})
        loads = (t.get("load_avg_start") or []) + (e.get("load_avg_start") or [])
        res = b.get("frame_send_to_result", {})
        L.append(f"| {b['label']} | {t.get('n_runs', 0)} + {e.get('n_runs', 0)} | {min(loads):.1f}-{max(loads):.1f} | "
                 f"{f3(t.get('video_leg_ms'))} | {f3(e.get('video_leg_ms'))} | {f2(e.get('decode_to_model_ms'))} | "
                 f"{f3(res) if res else 'n/a'} (n = {res.get('n')}) | {res.get('what', '').replace('frame-send (capture) -> ', '')} | "
                 f"{e.get('frames_not_processed_total')} | {e.get('calls_per_run')} | "
                 f"{b['camera_to_result_estimate_ms']['p50']:.0f} / {b['camera_to_result_estimate_ms']['p90']:.0f} |")
    L += ["", "| setting | prep (crop, resize) | queue wait | detector call | model excl. call rule | call rule on flight frames | "
              "video leg I-frames / P-frames (transport only, p50) | transport losses |", "|" + "---|" * 7]
    for k, b in out["settings"].items():
        e = b.get("engine", {})
        P = e.get("decode_to_model_parts_ms", {})
        t = b.get("transport_only", {})
        ip = (f"{t['video_leg_I_ms']['p50']:.1f} / {t['video_leg_P_ms']['p50']:.1f}" if t.get("video_leg_I_ms") else "n/a")
        L.append(f"| {b['label']} | {f2(P.get('prep_crop_resize'))} | {f2(P.get('queue_wait'))} | {f2(P.get('detector_call'))} | "
                 f"{f2(P.get('model_excl_call_rule'))} | {f2(P.get('call_rule_on_flight_frames'))} | {ip} | "
                 f"{t.get('frames_lost_total', 'n/a')} |")
    cv = out.get("calls_vs_offline", {})
    if cv:
        runs = sorted(cv)
        L += ["", "| flight (f_net) | label | offline evaluation (test_flights.csv) | file-source online run | " +
              " | ".join(runs) + " |", "|" + "---|" * (4 + len(runs))]
        fsrc = {}
        for c in json.load(open(FILE_RUN))["vision"]["events"]:
            fsrc[int(c["frame"])] = c["call"]
        flights = out["calls_vs_offline_summary"]["offline_flights"]
        fs_map, _ = assign([dict(call=v, frame=k, direction=None) for k, v in sorted(fsrc.items())], flights)
        for fl in flights:
            cells = []
            for r in runs:
                p = next(x for x in cv[r]["per_flight"] if x["f_net"] == fl["f_net"])
                cells.append("none" if not p["webrtc"] else f"{p['webrtc']} @ {p['webrtc_frame']}")
            fs = fs_map.get(fl["f_net"])
            L.append(f"| {fl['f_net']} | {fl['label']} | {fl['offline_call']} @ {fl['offline_frame']} | "
                     f"{'none' if not fs else f'{fs[0]} @ {fs[1]}'} | " + " | ".join(cells) + " |")
        L.append("| outside labelled flights | | | " + ", ".join(f"{c} @ {f}" for f, c in sorted(fsrc.items())
                                                       if not any(v[1] == f for v in fs_map.values())) + " | " +
                 " | ".join(", ".join(f"{c} @ {f}" for c, f in cv[r]["calls_outside_labelled_flights"]) or "none"
                            for r in runs) + " |")
    sw = out.get("latency_sweep")
    if sw:
        L += ["", "| source | V of the source (s) | V with our CV's extra over the modelled 20 ms (s) | IS $/day at V_source | "
                  "IS $/day with our CV | burned OOS $/day at V_source | burned OOS $/day with our CV | basis |", "|" + "---|" * 8]
        for r in sw["rows"]:
            a, b = r["sweep_at_V_source"], r["sweep_at_V_effective"]
            L.append(f"| {r['source']} | {r['V_source_s']:.3f} | {r['V_effective_s']:.3f} | {a['IS']['usd_per_day']:+.1f} | "
                     f"{b['IS']['usd_per_day']:+.1f} | {a['burned_OOS']['usd_per_day']:+.1f} | {b['burned_OOS']['usd_per_day']:+.1f} | "
                     f"{r['basis']} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign", nargs="+", help="run_<ts>.jsonl file(s) of the REPS campaign")
    ap.add_argument("--probe", nargs="*", default=[], help="extra run files reported as backend probes only")
    ap.add_argument("--out", default=str(OUT / "latency.json"))
    ap.add_argument("--fig", default=str(OUT / "fig_webrtc_latency.png"))
    ap.add_argument("--md", default=None, help="also write markdown tables (for RESULTS.md) to this path")
    a = ap.parse_args()
    runs = load([Path(p).resolve() for p in a.campaign])
    byset = defaultdict(lambda: dict(t=[], e=[]))
    for lab, R in runs.items():
        if R["meta"] is None or R["summary"] is None:
            continue
        m = re.match(r"(dec30|dec60|native120|slowmo10)_(transport|engine)(_r\d+)?$", lab)
        if not m:
            continue
        key = next(k for k, v in SETTINGS.items() if v[0] == m.group(1))
        byset[key]["t" if m.group(2) == "transport" else "e"].append(R)
    blocks = {}
    for k in SETTINGS:
        if k in byset:
            blocks[k] = setting_block(k, sorted(byset[k]["t"], key=lambda R: R["meta"]["label"]),
                                      sorted(byset[k]["e"], key=lambda R: R["meta"]["label"]))
            if byset[k]["e"]:
                blocks[k]["_c2d"] = [x["c2d"] for R in byset[k]["e"] for x in frame_legs(R["frames"]) if x["c2d"] is not None]
    # calls vs the offline evaluation and the file-source run, per call run
    flights = flights_offline(2000, 3000)
    fcalls = file_source_calls()
    calls_cmp = {}
    for k in ("120fps_keepup", "120fps"):
        for R in byset.get(k, {}).get("e", []):
            calls_cmp[R["meta"]["label"]] = compare_calls(R, flights, fcalls)
    keep = blocks.get("120fps_keepup", {})
    head = keep.get("camera_to_result_estimate_ms")
    meas = keep.get("frame_send_to_result")
    figure(blocks, a.fig)
    for b in blocks.values():
        b.pop("_c2d", None)
    probes = {}
    for pf in a.probe:
        pr = load([Path(pf).resolve()])
        for lab, R in pr.items():
            if R["meta"] and R["summary"] and R["meta"].get("mode") == "engine":
                L = frame_legs(R["frames"])
                probes[f"{Path(R['file']).name}:{lab}"] = dict(
                    backend=R["meta"]["backend"], fps=R["meta"]["arrival_fps"],
                    capture_to_decision_ms=pct([x["c2d"] for x in L]), drops=drops(R))
    m0 = next(iter(runs.values()))["meta"]
    out = dict(
        what="Latency of OUR camera -> WebRTC -> CV -> call pipeline on OUR stream (paper only).",
        never_claim=("This is not a Polymarket match feed and not glass-to-glass: the source is our own held-out "
                     "OpenTTGames clip streamed by us, the camera is virtual (a paced sender), everything ran over "
                     "loopback on one laptop (no network, no relay). We have no camera at any venue."),
        clip=CLIP, campaign_files=[str(Path(p).resolve().relative_to(REPO)) for p in a.campaign],
        host=m0.get("machine"), versions=m0.get("versions"), sender=dict(encoder=m0["sender"].get("encoder"),
                                                                        ffmpeg=m0["sender"].get("ffmpeg_version")),
        transport="libx264 ultrafast zerolatency (no B-frames, GOP 0.5 s) -> WHIP -> MediaMTX v1.21.1 (127.0.0.1) "
                  "-> WHEP -> aiortc 1.15.0 (marker-bit frame completion patch) -> PyAV decode",
        relay=("local only: no second machine or network hop was available (a public relay or a HiPerGator service "
               "was not allowed). Others' relay figures: about 0.4 s via a public Broadcast Box server; MediaMTX p50 "
               "180 ms LAN-only, 520 ms cross-region (SUB_SECOND_ROUTES.md S2, S3)."),
        capture_assumption=CAPTURE,
        settings=blocks, calls_vs_offline=calls_cmp,
        calls_vs_offline_summary=dict(
            runs=len(calls_cmp),
            identical_to_file_source={lab: c["identical_to_file_source"] for lab, c in calls_cmp.items()},
            flights_agree_with_offline={lab: f"{c['flights_agree_with_offline']}/{c['labelled_flights']}"
                                        for lab, c in calls_cmp.items()},
            offline_miss_calls_reproduced={lab: f"{c['offline_miss_calls_reproduced']}/{c['offline_miss_calls']}"
                                           for lab, c in calls_cmp.items()},
            offline_flights=flights,
            file_source_reference=str(FILE_RUN.relative_to(REPO))),
        backend_probes=probes,
    )
    if head and meas:
        rt = blocks.get("120fps", {}).get("engine", {})
        rt_drop = rt.get("frames_not_processed_share")
        rt_calls = sum(rt.get("calls_per_run") or [])
        out["headline"] = dict(
            setting="120fps_keepup", measured_frame_send_to_emit_ms=dict(p50=meas["p50"], p90=meas["p90"], p99=meas["p99"], n=meas["n"]),
            measured_capture_to_decision_ms=keep["engine"]["capture_to_decision_ms"],
            camera_to_call_estimate_ms=head,
            realtime_120fps=dict(frames_not_processed_share=rt_drop, calls_total=rt_calls,
                                 runs=rt.get("n_runs")),
            # the measured number leads; the assumed camera time and the slow-motion condition travel with it
            sentence=(f"Measured on our own clip over loopback WebRTC: {meas['p50']:.0f} ms p50 / {meas['p90']:.0f} ms p90 "
                      f"from a frame leaving our virtual camera to the call, with the CV fed 10 frames/s so it keeps up "
                      f"({head['p50']:.0f} / {head['p90']:.0f} ms with an assumed 120 fps camera); at real-time 120 fps this "
                      f"laptop's CV skipped {100 * (rt_drop or 0):.0f}% of frames and made {rt_calls or 'no'} calls. "
                      f"Our pipeline, not a match feed."),
            footnote=(f"{meas['p50']:.0f} / {meas['p90']:.0f} ms measured from frame capture by our virtual camera (a paced "
                      f"file sender, no physical camera) to the CallEvent ({meas['n']} calls = the same 11 calls in each of "
                      f"{keep['engine']['n_runs']} runs; p99 of 55 values is close to their max), loopback on one shared "
                      f"laptop, engine fed 10 frames/s so it keeps up. The {head['p50']:.0f} / {head['p90']:.0f} ms adds "
                      f"{keep['capture_assumed_ms']:.1f} ms ASSUMED 120 fps camera capture (2 frame periods). No relay, "
                      f"no network hop, no display."))
        out["latency_sweep"] = sweep_plug(dict(keep, _runs=sorted(byset["120fps_keepup"]["e"],
                                                                   key=lambda R: R["meta"]["label"])), blocks.get("120fps"))
        for r in out["latency_sweep"]["rows"]:
            print(f"sweep: {r['source']}: V {r['V_source_s']} -> {r['V_effective_s']} s: IS ${r['sweep_at_V_effective']['IS']['usd_per_day']}"
                  f"/day, OOS ${r['sweep_at_V_effective']['burned_OOS']['usd_per_day']}/day "
                  f"(at V_source: ${r['sweep_at_V_source']['IS']['usd_per_day']} / ${r['sweep_at_V_source']['burned_OOS']['usd_per_day']})")
        print("sweep measured:", out["latency_sweep"]["measured"], out["latency_sweep"]["breakeven_source_delay_with_our_cv_s"])
    Path(a.out).write_text(json.dumps(out, indent=1, default=float))
    if a.md:
        Path(a.md).write_text(md_tables(out))
    print(f"wrote {a.out} and {a.fig}")
    for k, b in blocks.items():
        t = b.get("transport_only", {})
        e = b.get("engine", {})
        print(f"{k:15s} video leg (transport) {t.get('video_leg_ms')}")
        if e:
            print(f"{'':15s} engine video leg {e['video_leg_ms']}\n{'':15s} decode->model {e['decode_to_model_ms']}\n"
                  f"{'':15s} send->result {b['frame_send_to_result']}\n{'':15s} not processed {e['frames_not_processed_total']} "
                  f"calls/run {e['calls_per_run']}\n{'':15s} camera->result est {b['camera_to_result_estimate_ms']}")
    for lab, c in calls_cmp.items():
        print(f"{lab}: {c['n_calls']} calls, file-source identical {c['identical_to_file_source']} "
              f"({c['same_as_file_source_within_2_frames']}/{c['file_source_calls']}), offline agree "
              f"{c['flights_agree_with_offline']}/{c['labelled_flights']}, MISS {c['offline_miss_calls_reproduced']}/{c['offline_miss_calls']}"
              f", only_webrtc {c['only_webrtc']}, only_file {c['only_file']}")
    if "headline" in out:
        print(out["headline"]["sentence"])
        print(out["headline"]["footnote"])


if __name__ == "__main__":
    main()
