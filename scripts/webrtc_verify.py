"""Independent check of a WebRTC latency campaign (paper only; our own held-out OpenTTGames clip, our own stream).

Recomputes every headline number of research/webrtc/RESULTS.md from the RAW per-frame timestamps in
results/webrtc/run_<ts>.jsonl, without importing scripts/webrtc_latency.py or engine/webrtc/report.py, and checks:

  1. frame identity   the in-band code (seq, source frame, capture ms; CRC16) against the sender's own log
                      (t_due) and the arithmetic src = 2000 + (seq - seq_first_clip) * step; engine index k;
                      optional (--pixels): every frame the receiver handed to the CV engine (--save-frames file)
                      against the clip's own frames at offsets -2..+2, on the pixels that move between frames
  2. clocks           every stamp is time.time() on one host (no cross-host offset). time.time() is NOT
                      monotonic: backward steps are detected where the sender wrote a frame before it was due
                      (impossible on a monotonic clock) and, for runs logged with it, from the receiver's
                      per-frame wall-minus-monotonic offset ("wm"); affected frames are listed and the
                      percentiles are recomputed without them
  3. WebRTC           per run: the SDP answer's H264 rtpmap line, frames assembled from RTP packets by the
                      patched jitter buffer, packets per frame; with --work: MediaMTX's own session log (one
                      WebRTC publisher and one WebRTC reader per run, ICE pair host/udp 127.0.0.1, no RTSP
                      reader) and ffmpeg's WHIP handshake (ICE, DTLS, SRTP) per run
  4. latency          per setting, pooled over runs: video leg, decoded -> decision, capture -> decision,
                      capture of frame k -> frame k's own ball position final (the detector's 2-frame
                      look-ahead included), capture -> CallEvent emit (t_emit - t_due joined by source frame);
                      compared with results/webrtc/latency.json
  5. calls            per call run against the file-source run (results/engine/demo_run.json): same call on
                      the same flight (same direction, within 12 frames) and exact-frame matches

Usage (repo root):
  python scripts/webrtc_verify.py results/webrtc/run_20261003T221601Z.jsonl \
      [--work $TMPDIR/courtside_webrtc/20261003T221601Z] [--pixels] [--out results/webrtc/verify.json]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SRC0 = 2000
SETTINGS = {"dec30": "30 fps, real time", "dec60": "60 fps, real time", "native120": "120 fps, real time",
            "slowmo10": "120 fps content fed at 10 frames/s (engine keeps up)"}


def pct(a, qs=(50, 90, 99)):
    a = np.asarray([x for x in a if x is not None], float)
    a = a[np.isfinite(a)]
    if not len(a):
        return None
    return {**{f"p{q}": round(float(np.percentile(a, q)), 2) for q in qs}, "n": int(len(a))}


def load(path):
    runs = collections.defaultdict(lambda: dict(meta=None, frames=[], calls=[], summary=None))
    for line in open(path):
        r = json.loads(line)
        R = runs[r["run"]]
        t = r.get("type")
        if t == "meta":
            R["meta"] = r
        elif t == "frame":
            R["frames"].append(r)
        elif t == "call":
            R["calls"].append(r)
        elif t == "summary":
            R["summary"] = r
    return runs


def ms(r, a, b):
    return None if r.get(a) is None or r.get(b) is None else (r[a] - r[b]) * 1e3


# ------------------------------------------------------------------------------------------------ 1. identity
def identity(R):
    m = R["meta"]
    step = m["step"]
    clip = [f for f in R["frames"] if f.get("flags") is not None and f["flags"] & 2]
    bad = sum(1 for f in R["frames"] if f.get("seq") is None)
    seqs = [f["seq"] for f in clip]
    s0 = seqs[0] if seqs else 0
    arith = sum(1 for f in clip if f["src"] != SRC0 + (f["seq"] - s0) * step)
    kbad = sum(1 for f in clip if f.get("k") is not None and f["k"] != (f["src"] - SRC0) // step)
    code_vs_log = [abs(f["t_cap_code"] - f["t_due"]) * 1e3 for f in clip if f.get("t_due") is not None]
    expected = len(range(SRC0, SRC0 + 1000, step))
    srcs = sorted(f["src"] for f in clip)
    return dict(step=step, clip_frames_received=len(clip), clip_frames_expected=expected,
                missing_source_frames=sorted(set(range(SRC0, SRC0 + 1000, step)) - set(srcs)),
                duplicate_seqs=len(seqs) - len(set(seqs)), out_of_order=sum(1 for a, b in zip(seqs, seqs[1:]) if b <= a),
                bad_crc_frames=bad, src_vs_seq_arithmetic_mismatches=arith, engine_index_mismatches=kbad,
                frames_without_sender_row=sum(1 for f in clip if f.get("t_due") is None),
                code_time_vs_sender_log_ms_max=round(max(code_vs_log), 3) if code_vs_log else None)


def pixel_identity(R, frames_path, clip_path):
    """Saved engine-input frames vs the clip's frames at offsets -2..+2 (motion-masked mean abs difference)."""
    import av
    rows = [f for f in R["frames"] if f.get("flags") and f["flags"] & 2 and f.get("saved") is not None]
    raw = np.memmap(frames_path, np.uint8, "r").reshape(-1, 288, 512, 3)
    c = av.open(str(clip_path))
    st = c.streams.video[0]
    tb = float(st.time_base)
    S = {}
    for fr in c.decode(st):
        S[int(round(fr.pts * tb * 120))] = fr.to_ndarray(width=512, height=288, format="rgb24",
                                                          interpolation="AREA").astype(np.int16)
    c.close()
    best = collections.Counter()
    static = 0
    for r in rows:
        s = r["src"]
        if s - 2 not in S or s + 2 not in S:
            continue
        w = raw[r["saved"]].astype(np.int16)
        mask = (np.abs(S[s] - S[s - 1]).max(-1) > 12) | (np.abs(S[s] - S[s + 1]).max(-1) > 12)
        if mask.sum() < 50:
            static += 1
            continue
        d = {o: float(np.abs(w - S[s + o])[mask].mean()) for o in (-2, -1, 0, 1, 2)}
        best[min(d, key=d.get)] += 1
    return dict(frames_compared=int(sum(best.values())), static_frames_skipped=static,
                best_matching_offset_counts={str(k): v for k, v in sorted(best.items())},
                exact=(set(best) == {0}))


# ------------------------------------------------------------------------------------------------ 2. clocks
def clock_steps(R, send_log):
    """Backward wall-clock steps: a frame written before it was due (t_w0 < t_due) cannot happen on a monotonic
    clock (the sender spins until time.time() >= due). Receiver side: jumps in wall - monotonic, if logged."""
    out = dict(clock="time.time() (CLOCK_REALTIME) in sender, receiver and engine, one host: no cross-host offset")
    if send_log and os.path.exists(send_log):
        rows = [json.loads(x) for x in open(send_log)]
        neg = [dict(seq=r["seq"], src=r.get("src"), step_ms=round((r["t_w0"] - r["t_due"]) * 1e3, 3))
               for r in rows if "seq" in r and r["t_w0"] < r["t_due"] - 1e-6]
        out["sender_backward_steps"] = neg
        swm = [(r["seq"], r["wm"]) for r in rows if "seq" in r and r.get("wm") is not None]
        if len(swm) > 1:
            out["sender_wall_minus_monotonic_jumps"] = [dict(seq=b[0], step_ms=round((b[1] - a[1]) * 1e3, 3))
                                                        for a, b in zip(swm, swm[1:]) if abs(b[1] - a[1]) > 0.5e-3]
    wm = [(f["seq"], f["wm"]) for f in R["frames"] if f.get("wm") is not None]
    if len(wm) > 1:
        jumps = [dict(seq=b[0], step_ms=round((b[1] - a[1]) * 1e3, 3)) for a, b in zip(wm, wm[1:])
                 if abs(b[1] - a[1]) > 0.5e-3]
        out["receiver_wall_minus_monotonic_jumps"] = jumps
    return out


# ------------------------------------------------------------------------------------------------ 4. latency
def latency(Rs, exclude=None):
    exclude = exclude or set()
    vid, dec, c2d, own, emit, emit_eng, emit_vid = [], [], [], [], [], [], []
    sent = processed = 0
    for lab, R in Rs:
        step = R["meta"]["step"]
        clip = [f for f in R["frames"] if f.get("flags") and f["flags"] & 2 and (lab, f["seq"]) not in exclude]
        by = {f["src"]: f for f in clip}
        sent += len(clip)
        for f in clip:
            vid.append(ms(f, "t_handoff", "t_due"))
            processed += bool(f.get("engine_done"))
            if f.get("t_decision") is not None:
                dec.append(ms(f, "t_decision", "t_handoff"))
                c2d.append(ms(f, "t_decision", "t_due"))
            # frame k's own ball position is final when the window (k, k+1, k+2) has run, i.e. at frame k+2's
            # decision step (LAG = 2). In slow motion k+1 and k+2 arrive 100 ms apart each, so this leg is
            # meaningful for the real-time settings only.
            g = by.get(f["src"] + 2 * step)
            if g is not None and g.get("t_decision") is not None:
                own.append((g["t_decision"] - f["t_due"]) * 1e3)
        for c in R["calls"]:
            f = by.get(int(c["frame"]))
            if f is None:
                continue
            emit.append((c["t_emit"] - f["t_due"]) * 1e3)
            emit_eng.append((c["t_emit"] - c["t_frame"]) * 1e3)
            emit_vid.append(ms(f, "t_handoff", "t_due"))
    out = dict(runs=len(Rs), video_leg_ms=pct(vid))
    if any(R["meta"]["mode"] == "engine" for _, R in Rs):
        out.update(decoded_to_decision_ms=pct(dec), capture_to_decision_ms=pct(c2d),
                   capture_to_own_position_final_ms=pct(own),
                   frames_sent=sent, frames_processed=processed, frames_with_decision=len(c2d),
                   not_processed_share=round(1 - processed / sent, 4) if sent else None,
                   decision_share_of_sent=round(len(c2d) / sent, 4) if sent else None)
        if emit:
            out.update(capture_to_emit_ms=pct(emit), decoded_to_emit_ms=pct(emit_eng),
                       video_leg_of_call_frames_p50_ms=round(float(np.median(emit_vid)), 2),
                       calls_per_run=[len(R["calls"]) for _, R in Rs])
    return out


# ------------------------------------------------------------------------------------------------ 5. calls
def calls_vs_file(R):
    fc = [(e["call"], int(e["frame"]), e.get("direction")) for e in json.load(open(REPO / "results/engine/demo_run.json"))["vision"]["events"]]
    got = [(c["call"], int(c["frame"]), c.get("direction")) for c in R["calls"]]
    same_flight = exact = 0
    shifts = []
    for call, fr, d in fc:
        m = [g for g in got if g[0] == call and abs(g[1] - fr) <= 12 and (d is None or g[2] is None or g[2] == d)]
        if m:
            same_flight += 1
            g = min(m, key=lambda g: abs(g[1] - fr))
            exact += g[1] == fr
            if g[1] != fr:
                shifts.append(dict(call=call, file_frame=fr, webrtc_frame=g[1], shift_frames=g[1] - fr))
    return dict(file_source_calls=len(fc), webrtc_calls=len(got), same_call_same_flight=same_flight,
                exact_frame=exact, shifted=shifts)


# ------------------------------------------------------------------------------------------------ 3. WebRTC
def webrtc_evidence(R):
    s = R["summary"] or {}
    rec = s.get("receiver") or {}
    clip = [f for f in R["frames"] if f.get("flags") and f["flags"] & 2]
    npk = [f.get("n_packets") for f in clip if f.get("n_packets")]
    w = rec.get("webrtc") or {}
    return dict(sdp_answer_h264=rec.get("codec"), whep_connect_s=rec.get("whep_connect_s"),
                frames_assembled_from_rtp=(rec.get("jitter") or {}).get("marker"),
                rtp_packets_per_clip_frame=dict(p50=float(np.median(npk)), max=int(max(npk))) if npk else None,
                aiortc_patch=R["meta"].get("aiortc_patch"),
                sdp_logged=bool(w.get("answer_sdp")), ice_pair=w.get("ice_nominated"))


def mediamtx_sessions(work):
    p = Path(work) / "mediamtx.log"
    if not p.exists():
        return None
    txt = p.read_text()
    pub = re.findall(r"\[WebRTC\] \[session (\w+)\] is publishing to path '([^']+)'", txt)
    rd = re.findall(r"\[WebRTC\] \[session (\w+)\] is reading from path '([^']+)'", txt)
    pairs = re.findall(r"peer connection established, local candidate: (\S+), remote candidate: (\S+)", txt)
    rtsp_readers = re.findall(r"\[RTSP\] \[(?:conn|session)[^\]]*\].*(?:is reading|is publishing)", txt)
    return dict(log=str(p), webrtc_publish_sessions=len(pub), webrtc_read_sessions=len(rd),
                paths_read=sorted({x[1] for x in rd}),
                ice_local_candidates=sorted({a.rsplit("/", 1)[0] for a, _ in pairs}),
                ice_remote_candidate_types=sorted({b.split("/")[0] for _, b in pairs}),
                ice_remote_hosts=sorted({b.split("/")[2] for _, b in pairs}),
                rtsp_sessions=len(rtsp_readers), text=txt)


def whip_handshakes(work):
    out = {}
    for p in sorted(glob.glob(str(Path(work) / "*.ffmpeg.log"))):
        m = re.search(r"\[WHIP muxer[^\]]*\] Muxer state=\d+.*elapsed=([\d.]+)ms\(([^)]*)\)", open(p).read())
        if m:
            out[Path(p).name.replace(".ffmpeg.log", "")] = dict(total_ms=float(m.group(1)), phases=m.group(2))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign")
    ap.add_argument("--work", default=None, help="the run's scratch dir (sender logs, MediaMTX / ffmpeg logs, saved frames)")
    ap.add_argument("--pixels", action="store_true", help="pixel identity check on the saved engine-input frames")
    ap.add_argument("--latency-json", default=str(REPO / "results/webrtc/latency.json"))
    ap.add_argument("--out", default=str(REPO / "results/webrtc/verify.json"))
    ap.add_argument("--evidence", default=None, help="write MediaMTX session log + WHIP handshakes here (text)")
    a = ap.parse_args()
    runs = load(a.campaign)
    ts = re.search(r"run_(\w+)\.jsonl", a.campaign).group(1)
    out = dict(what="independent recomputation of the WebRTC campaign from raw per-frame timestamps (our own clip, "
                    "our own loopback stream; not a match feed)", campaign=a.campaign)

    # 1 + 2 + 3 per run
    ident, clocks, rtc = {}, {}, {}
    for lab, R in sorted(runs.items()):
        ident[lab] = identity(R)
        clocks[lab] = clock_steps(R, (Path(a.work) / f"{lab}.send.jsonl") if a.work else None)
        rtc[lab] = webrtc_evidence(R)
    out["identity"] = dict(
        all_clip_frames_received=all(v["clip_frames_received"] == v["clip_frames_expected"] for v in ident.values()),
        any_bad_crc=any(v["bad_crc_frames"] for v in ident.values()),
        any_arith_mismatch=any(v["src_vs_seq_arithmetic_mismatches"] or v["engine_index_mismatches"] for v in ident.values()),
        code_time_vs_sender_log_ms_max=max(v["code_time_vs_sender_log_ms_max"] for v in ident.values()),
        per_run=ident)
    if a.pixels and a.work:
        for lab, R in sorted(runs.items()):
            fp = Path(a.work) / f"{lab}.frames.u8"
            if fp.exists():
                out["identity"].setdefault("pixels", {})[lab] = pixel_identity(R, fp, REPO / "data/vision/test_2_copyts.mp4")
    steps = {(lab, s["seq"]) for lab, c in clocks.items() for s in c.get("sender_backward_steps", [])}
    out["clocks"] = dict(per_run={k: v for k, v in clocks.items() if v.get("sender_backward_steps") or
                                  v.get("receiver_wall_minus_monotonic_jumps") or v.get("sender_wall_minus_monotonic_jumps")},
                         sender_backward_steps_total=len(steps),
                         largest_backward_step_ms=min([s["step_ms"] for c in clocks.values()
                                                       for s in c.get("sender_backward_steps", [])], default=0.0),
                         note="frames whose sender row shows a backward step are excluded in latency_excluding_clock_steps")
    out["webrtc"] = dict(per_run=rtc)
    if a.work:
        mm = mediamtx_sessions(a.work)
        if mm:
            text = mm.pop("text")
            out["webrtc"]["mediamtx"] = mm
            hs = whip_handshakes(a.work)
            out["webrtc"]["whip_handshakes"] = hs
            if a.evidence:
                with open(a.evidence, "w") as fh:
                    fh.write(f"# WebRTC session evidence for campaign {ts} (our own clip over loopback; not a match feed)\n")
                    fh.write("# 1. MediaMTX v1.21.1 log, verbatim: every run = one WebRTC (WHIP) publisher + one WebRTC (WHEP) reader,\n")
                    fh.write("#    ICE pair host/udp 127.0.0.1:8189 <-> 127.0.0.1:<ephemeral>; no RTSP session.\n")
                    fh.write(text if text.endswith("\n") else text + "\n")
                    fh.write("\n# 2. ffmpeg WHIP muxer handshake per run (sender side): ICE, DTLS, SRTP phases in ms\n")
                    for k, v in hs.items():
                        fh.write(f"{k}: elapsed {v['total_ms']} ms ({v['phases']})\n")

    # 4 latency per setting
    groups = collections.defaultdict(list)
    for lab, R in runs.items():
        m = re.match(r"(dec30|dec60|native120|slowmo10)_(transport|engine)(_.+)?$", re.sub(r"_r\d+$", "", lab))
        if m:
            groups[(m.group(1), m.group(2), m.group(3) or "")].append((lab, R))
    lat, lat_x = {}, {}
    for (p, mode, tag), Rs in sorted(groups.items()):
        key = f"{p}_{mode}{tag}"
        lat[key] = dict(label=SETTINGS[p] + (f" [{tag[1:]}]" if tag else ""), **latency(sorted(Rs, key=lambda x: x[0])))
        lat_x[key] = latency(sorted(Rs, key=lambda x: x[0]), exclude=steps)
    out["latency"] = lat
    out["latency_excluding_clock_steps"] = {k: {kk: v.get(kk) for kk in ("video_leg_ms", "capture_to_decision_ms",
                                                                      "capture_to_emit_ms") if v.get(kk)}
                                            for k, v in lat_x.items()}

    # compare with latency.json (what RESULTS.md cites)
    cmp = {}
    if os.path.exists(a.latency_json):
        L = json.load(open(a.latency_json))
        name = {"dec30": "30fps", "dec60": "60fps", "native120": "120fps", "slowmo10": "120fps_keepup"}
        for (p, mode, tag) in groups:
            if tag or os.path.basename(a.campaign) not in " ".join(L.get("campaign_files", [])):
                continue          # latency.json covers the standard labels of its own campaign file only
            blk = L["settings"].get(name[p], {})
            mine = lat[f"{p}_{mode}"]
            pairs = []
            if mode == "transport":
                pairs.append(("video_leg_ms", blk.get("transport_only", {}).get("video_leg_ms"), mine["video_leg_ms"]))
            else:
                e = blk.get("engine", {})
                pairs += [("video_leg_ms", e.get("video_leg_ms"), mine["video_leg_ms"]),
                          ("decode_to_model_ms", e.get("decode_to_model_ms"), mine["decoded_to_decision_ms"]),
                          ("capture_to_decision_ms", e.get("capture_to_decision_ms"), mine["capture_to_decision_ms"])]
                if mine.get("capture_to_emit_ms"):
                    pairs.append(("capture_to_emit_ms", e.get("capture_to_emit_ms"), mine["capture_to_emit_ms"]))
            for nm, theirs, ours in pairs:
                if theirs and ours:
                    d = max(abs(theirs[q] - ours[q]) for q in ("p50", "p90", "p99"))
                    cmp[f"{p}_{mode}.{nm}"] = dict(latency_json=[theirs[q] for q in ("p50", "p90", "p99")],
                                                   recomputed=[ours[q] for q in ("p50", "p90", "p99")],
                                                   max_abs_diff_ms=round(d, 3), n_match=theirs.get("n") == ours.get("n"))
    out["latency_json_check"] = dict(max_abs_diff_ms=max([v["max_abs_diff_ms"] for v in cmp.values()], default=None),
                                     all_n_match=all(v["n_match"] for v in cmp.values()), items=cmp)

    # 5 calls
    out["calls_vs_file_source"] = {lab: calls_vs_file(R) for lab, R in sorted(runs.items()) if R["meta"].get("calls")}

    Path(a.out).write_text(json.dumps(out, indent=1, default=float))
    # console digest
    I = out["identity"]
    print(f"identity: all clip frames received {I['all_clip_frames_received']}, bad CRC {I['any_bad_crc']}, "
          f"arithmetic mismatch {I['any_arith_mismatch']}, code vs sender log max {I['code_time_vs_sender_log_ms_max']} ms")
    for lab, v in I.get("pixels", {}).items():
        print(f"pixels {lab}: {v}")
    print(f"clock: {out['clocks']['sender_backward_steps_total']} backward wall-clock steps seen by the sender, largest "
          f"{out['clocks']['largest_backward_step_ms']} ms")
    if "mediamtx" in out["webrtc"]:
        mm = out["webrtc"]["mediamtx"]
        print(f"MediaMTX: {mm['webrtc_publish_sessions']} WebRTC publishers, {mm['webrtc_read_sessions']} WebRTC readers, "
              f"local {mm['ice_local_candidates']}, remote types {mm['ice_remote_candidate_types']} hosts "
              f"{mm['ice_remote_hosts']}, RTSP sessions {mm['rtsp_sessions']}")
    for k, v in lat.items():
        line = f"{k:20s} video {v['video_leg_ms']}"
        if v.get("capture_to_decision_ms"):
            line += (f"\n{'':20s} dec->decision {v['decoded_to_decision_ms']} cap->decision {v['capture_to_decision_ms']}"
                     f"\n{'':20s} cap(k)->own position final {v['capture_to_own_position_final_ms']} "
                     f"not processed {v['not_processed_share']} decisions/sent {v['decision_share_of_sent']}")
        if v.get("capture_to_emit_ms"):
            line += f"\n{'':20s} cap->emit {v['capture_to_emit_ms']} dec->emit {v['decoded_to_emit_ms']} calls {v['calls_per_run']}"
        print(line)
    print(f"latency.json check: max |diff| {out['latency_json_check']['max_abs_diff_ms']} ms, n match "
          f"{out['latency_json_check']['all_n_match']}")
    for lab, c in out["calls_vs_file_source"].items():
        print(f"calls {lab}: {c['same_call_same_flight']}/{c['file_source_calls']} same call same flight, "
              f"{c['exact_frame']} exact frame, shifted {[(s['file_frame'], s['webrtc_frame']) for s in c['shifted']]}")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
