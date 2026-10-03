"""Latency legs of one WebRTC run, from the joined per-frame rows (whep_reader.py writes them).

All times are wall clock (time.time()) on ONE host, so sender and receiver stamps are directly comparable.
"Capture" = t_due, when the virtual camera (the paced sender) produced the frame; there is no physical
camera or display in this loop, so camera exposure / readout and display scan-out are NOT included.

  sender_late          t_w0 - t_due         sender started writing the frame late (pacing / CPU)
  capture_to_first_pkt t_first - t_due      ffmpeg encode + WHIP packetize + MediaMTX relay + first RTP packet in
  capture_to_complete  t_complete - t_due   ... + last packet of the frame in (frame assembled, marker bit)
  pkt_spread           t_complete - t_first first -> last packet of the frame (large keyframes)
  decoder_wait         t_dec0 - t_complete  queue to aiortc's decoder thread
  decode               t_dec1 - t_dec0      H.264 decode (libavcodec via PyAV)
  handoff              t_handoff - t_dec1   decoder thread -> asyncio track.recv() -> our code
  capture_to_handoff   t_handoff - t_due    THE VIDEO LEG: a decoded frame in our process (what a WebRTC
                                            player has right before it renders)
  prep                 t_ready - t_handoff  read the frame code, crop the strip, resize to 512x288 RGB
  engine_ready         t_decision - t_handoff  engine.vision.stream: detector (2-frame look-ahead) + tracker
                                            (+ features + classifier in call mode) done for this decision
                                            frame = VisionCallEngine.ready_ms
  capture_to_decision  t_decision - t_due   frame captured -> everything a call at this frame needs is done
  capture_to_emit      t_emit - t_due       per CallEvent
"""
from __future__ import annotations

import numpy as np

LEGS = [("sender_late", "t_w0", "t_due"), ("capture_to_first_pkt", "t_first", "t_due"),
        ("capture_to_complete", "t_complete", "t_due"), ("pkt_spread", "t_complete", "t_first"),
        ("decoder_wait", "t_dec0", "t_complete"), ("decode", "t_dec1", "t_dec0"),
        ("handoff", "t_handoff", "t_dec1"), ("capture_to_handoff", "t_handoff", "t_due"),
        ("prep", "t_ready", "t_handoff"), ("engine_ready", "t_decision", "t_handoff"),
        ("capture_to_decision", "t_decision", "t_due")]


def pct(a, qs=(50, 90, 99)):
    a = np.asarray([x for x in a if x is not None], float)
    a = a[np.isfinite(a)]
    if not len(a):
        return None
    d = {f"p{q}": round(float(np.percentile(a, q)), 2) for q in qs}
    d.update(mean=round(float(a.mean()), 2), max=round(float(a.max()), 2), min=round(float(a.min()), 2), n=int(len(a)))
    return d


def leg(rows, end, start):
    return [(r[end] - r[start]) * 1e3 for r in rows if r.get(end) is not None and r.get(start) is not None]


def legs(rows):
    return {name: pct(leg(rows, e, s)) for name, e, s in LEGS}


def summarize(frames, events, sent_clip_seqs, extra=None):
    clip = [r for r in frames if r.get("flags") is not None and r["flags"] & 2]
    got = {r["seq"] for r in clip}
    out = dict(
        frames=dict(sent_clip=len(sent_clip_seqs), received_clip=len(clip),
                    lost_clip=len(set(sent_clip_seqs) - got),
                    bad_code=sum(1 for r in frames if r.get("seq") is None),
                    keyframes_clip=sum(1 for r in clip if r.get("key")),
                    fed_to_engine=sum(1 for r in clip if r.get("fed")),
                    skipped_before_prep=sum(1 for r in clip if r.get("prep_skipped")),
                    engine_processed=sum(1 for r in clip if r.get("engine_done")),
                    engine_decisions=sum(1 for r in clip if r.get("t_decision") is not None),
                    code_time_mismatch_ms_max=(round(max(abs(r["t_cap_code"] - r["t_due"]) * 1e3 for r in clip
                                                         if r.get("t_due") is not None), 3) if clip else None)),
        latency_ms=legs(clip),
        capture_to_handoff_by_type={t: pct(leg([r for r in clip if (r.get("key") is True) == (t == "I")],
                                               "t_handoff", "t_due")) for t in ("I", "P")},
    )
    if events:
        out["calls"] = dict(n=len(events),
                            capture_to_emit_ms=pct([e.get("capture_to_emit_ms") for e in events]),
                            transport_ms=pct([e.get("capture_to_handoff_ms") for e in events]),
                            engine_ms=pct([e.get("latency_ms") for e in events]))
    if extra:
        out.update(extra)
    return out
