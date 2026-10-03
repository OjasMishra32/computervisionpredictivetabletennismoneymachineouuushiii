"""Held-out test set (test_1..test_7) through the STREAMING engine, scored exactly as the offline evaluation.

Each full test video (1920x1080, 120 fps, every frame from the first to the last, rallies and the gaps
between them) is decoded and paced in real time at 120 fps (FrameSource realtime, no frame dropped:
drop_when_full=False, so a backlog would show up as latency, never as different decisions) and streamed
through engine.vision.stream.VisionCallEngine on the GPU: BlurBall -> causal tracker -> online flight
segmentation -> features -> frozen HGB -> call rule -> CallEvents. Nothing from src/tracking's offline
detections, tracks or labelled flight boundaries is used to make a decision.

Scoring (src/tracking/early_call.py code, so the definitions are the ones behind
results/tracking/summary.json): the population is the 171 labelled test flights of
results/tracking/test_flights.csv (130 BOUNCE, 41 MISS), lead L in {0, 25, 50, 100, 150, 200} ms.

  A  engine_calls      the CallEvents the engine emitted. A flight is called MISS by lead L if the engine
                       emitted a MISS for it (same video and direction, frame within the flight) at least
                       L before T_ref. precision = MISS-labelled / all called flights, recall = called /
                       MISS flights (early_call.pr_at). First-call lead = T_ref - first MISS frame.
  B  engine_scores     the engine's own per-frame P(miss) (what it computed live), put through the offline
                       rules: snapshot (score at T_ref - L >= tau_snapshot) and online (3 consecutive
                       frames >= tau_online by T_ref - L) via early_call.curves.
  C  offline           the frozen model's offline test scores (export_frozen.py test_scores) through the
                       same code: must equal summary.json (checked).
A differs from B only through the engine's call logic (one call per flight, a BOUNCE call blocks a later
MISS in that direction, persistence resets when the online flight start moves); B differs from C only
through the streaming track and flight segmentation.

Usage (HiPerGator, repo root):
  python -m engine.vision.eval_online --backend torch-cuda --batch 8 --dynamic \\
      --blurball_root $ROOT/ext/blurball --out results/engine/online_vs_offline.json
  python -m engine.vision.eval_online --from-raw <raw.pkl>      # rescore a saved run (laptop)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pickle
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .events import assert_paper_only
from .stream import (FROZEN_PATH, REPO, FrameSource, VisionCallEngine, load_frozen, load_geometry, make_backend,
                     pct, run_stream, summarize, tracking_modules)

OUT = REPO / "results" / "engine" / "online_vs_offline.json"
RES = REPO / "results" / "tracking"
VIDEOS = [f"test_{i}" for i in range(1, 8)]
SOURCE_FPS = 120.0
STARTUP_FRAMES = 480


# --------------------------------------------------------------------------------------------- streaming
def stream_video(backend, frozen, video, a, D):
    geo, prov = load_geometry(video, frozen)
    path = os.path.join(a.ottg_root, f"{video}.mp4")
    eng = VisionCallEngine(backend, frozen, geo, fps=SOURCE_FPS, frame_offset=a.frame_offset, batch=a.batch)
    src = FrameSource(path, D, realtime=a.realtime, fps=SOURCE_FPS, max_frames=a.max_frames,
                      drop_when_full=False).start()
    t = time.time()
    rows, skipped = run_stream(eng, src, None, dynamic=a.dynamic)
    wall = time.time() - t
    if "error" in src.info:
        raise RuntimeError(f"{video}: reader failed: {src.info['error']}")
    s = summarize(rows, wall, skipped, eng)
    s.update(frames_read=src.info.get("read"), source_dropped=src.info.get("dropped", 0),
             reader_late_ms=src.info.get("reader_late_ms"), pts_index_mismatch=src.info.get("pts_index_mismatch"),
             geometry=prov, realtime=a.realtime)
    from .run_demo import detection_check
    s["detection_vs_labels"] = detection_check(eng.track_log, video)
    raw = dict(video=video, summary=s,
               events=[e.to_dict() for e in eng.events],
               trace=np.array(eng.caller.trace, dtype=float).reshape(-1, 5),      # t, dir, t0, p_gated, gate_open
               track=np.array(eng.track_log, dtype=float).reshape(-1, 5),         # frame, x, y, peak, score
               ready_ms=np.array(sorted(eng.ready_ms.items()), dtype=float).reshape(-1, 2),
               ranges=rally_ranges(video))
    return raw


def rally_ranges(video):
    """The rally frame ranges the offline detector ran on (work/tracking/ranges), for labelling calls made
    outside them; None where that file is not available."""
    try:
        C = tracking_modules().C
        p = Path(C.WORK) / "ranges" / f"{video}_0.txt"
        if p.exists():
            return [tuple(map(int, l.split()[:2])) for l in open(p) if l.strip()]
        return [tuple(r) for r in C.rally_ranges(video)]
    except Exception:
        return None


class _OfflineDetections:
    name = "offline-detections"


def replay_video(frozen, video, det_dir):
    """Diagnostic: the OFFLINE detector's candidates (work/tracking/det/<video>_*_blurball.npz, what
    src/tracking/detect.py wrote) fed frame by frame through the engine's own tracker, online flight
    segmentation, features, classifier and call rule (VisionCallEngine._consume). Separates the engine's
    decision logic from the detector's numerics: if this reproduces the offline evaluation, any gap of the
    GPU run comes from the detector (heatmap float rounding -> track -> score)."""
    import glob
    geo, prov = load_geometry(video, frozen)
    fr, ca = [], []
    for f in sorted(glob.glob(os.path.join(det_dir, f"{video}_*_blurball.npz"))):
        d = np.load(f)
        fr.append(d["frame"])
        ca.append(d["cand"])
    fr, ca = np.concatenate(fr), np.concatenate(ca)
    o = np.argsort(fr, kind="stable")
    fr, ca = fr[o], ca[o]
    eng = VisionCallEngine(_OfflineDetections(), frozen, geo, fps=SOURCE_FPS)
    eng.arrival = {int(f): 0.0 for f in fr}
    for f, c in zip(fr, ca):
        eng._consume([(int(f), c)])
    rp = os.path.join(det_dir, f"{video}_0.txt")
    ranges = ([tuple(map(int, l.split()[:2])) for l in open(rp) if l.strip()] if os.path.exists(rp)
              else rally_ranges(video))
    return dict(video=video, summary=dict(frames=int(len(fr)), geometry=prov, source="offline detections"),
                events=[e.to_dict() for e in eng.events],
                trace=np.array(eng.caller.trace, dtype=float).reshape(-1, 5),
                track=np.array(eng.track_log, dtype=float).reshape(-1, 5),
                ready_ms=np.zeros((0, 2)), ranges=ranges)


# --------------------------------------------------------------------------------------------- scoring
def _flights():
    te = pd.read_csv(RES / "test_flights.csv")          # row order = early_call --final te (fid = index)
    au = pd.read_csv(RES / "test_flights_audited.csv")
    assert (te.f_net.values == au.f_net.values).all() and (te.video.values == au.video.values).all()
    return te, au


def samples_in_window(fl, scores_by_video, E):
    """(fid, k) samples for the offline decision window of every flight [t0 + NMIN - 1 + LAG, T_ref], from a
    per-video {t: (dir, score)} map; only frames scored in the flight's direction."""
    rows = []
    for fid, r in fl.iterrows():
        sv = scores_by_video.get(r.video, {})
        d = float(np.sign(r.dir))
        for t in range(int(r.t0) + E.NMIN - 1 + E.LAG, int(r.t_ref) + 1):
            v = sv.get(t)
            if v is not None and v[0] == d:
                rows.append((fid, int(r.t_ref) - t, t, v[1]))
    S = pd.DataFrame(rows, columns=["fid", "k", "t", "score"])
    return S


_CAUSAL = {}


def causal_offline_scores(frozen, te, E):
    """The offline evaluation's own decision samples (offline tracks, labelled-flight t0 / direction / window),
    rescored with the one look-ahead removed: early_call.Flight.__init__ computes the table half-depth `hb`
    (a feature, and the level of the u_far / u_near / w_end crossings) as a median over ALL track points of
    the flight up to the labelled T_ref, i.e. including points after the decision frame. Here hb uses only
    points up to t - LAG, as a live engine must (stream.FrozenCaller builds the Flight on the prefix).
    -> {video: {t: (dir, gated score)}}"""
    key = id(frozen)
    if key in _CAUSAL:
        return _CAUSAL[key]
    from types import SimpleNamespace as NS
    feats, model = list(frozen["feats"]), frozen["model"]
    rows, Xs = [], []
    for fid, r in te.iterrows():
        trk = frozen["test_tracks"][r.video]
        geo, _ = load_geometry(r.video, frozen)
        for t in range(int(r.t0) + E.NMIN - 1 + E.LAG, int(r.t_ref) + 1):
            f = E.Flight(NS(dir=r.dir, t0=int(r.t0), t_ref=t - E.LAG), trk, geo).features(t)
            if f is None:
                continue
            rows.append((r.video, t, float(np.sign(r.dir)), min(f["tau_end"], f["tau_net"]) <= E.GATE_H))
            Xs.append([f[k] for k in feats])
    p = model.predict_proba(np.asarray(Xs, float))[:, 1] if Xs else np.zeros(0)
    out = {}
    for (v, t, d, g), pi in zip(rows, p):
        out.setdefault(v, {})[t] = (d, float(pi) if g else 0.0)
    _CAUSAL[key] = out
    return out


def rule_tables(S, fl, E, tau_snap, tau_on):
    cs = E.curves(S, S.score.values, fl, tau_snap)["snapshot"]
    co = E.curves(S, S.score.values, fl, tau_on)["online"]
    return dict(snapshot=E.lead_table(cs[2]), online=E.lead_table(co[2])), co[1]


def lead_stats(fl, lead):
    miss = fl[fl.label == "MISS"]
    lc = lead.reindex(miss.index).dropna()
    return dict(n_miss=int(len(miss)), n_called=int(len(lc)),
                median=None if lc.empty else round(float(lc.median()), 1),
                p10=None if lc.empty else round(float(lc.quantile(0.1)), 1),
                p90=None if lc.empty else round(float(lc.quantile(0.9)), 1))


def assign_events(events, fl, slack=12):
    """Engine CallEvents -> labelled flights: same video and direction, frame in [t0 - slack, T_ref + slack];
    the flight whose T_ref is nearest at or after the frame wins. -> (per-flight first MISS / first BOUNCE
    frame, unmatched events)."""
    by_v = {v: g for v, g in fl.groupby("video")}
    first_miss, first_bounce, unmatched, matched = {}, {}, [], []
    for e in sorted(events, key=lambda e: (e["video"], e["frame"])):
        g = by_v.get(e["video"])
        cand = [] if g is None else [(fid, r) for fid, r in g.iterrows()
                                     if np.sign(r.dir) == e["direction"] and r.t0 - slack <= e["frame"] <= r.t_ref + slack]
        if not cand:
            unmatched.append(e)
            continue
        fid, r = min(cand, key=lambda c: (0 if c[1].t_ref >= e["frame"] else 1, abs(c[1].t_ref - e["frame"])))
        matched.append((fid, e))
        tgt = first_miss if e["call"] == "MISS" else first_bounce
        if fid not in tgt or e["frame"] < tgt[fid]["frame"]:
            tgt[fid] = e
    return first_miss, first_bounce, unmatched, matched


def engine_call_tables(fl, first_miss, E):
    """early_call.per_flight_calls semantics for the emitted calls: called at lead k iff the first MISS call
    came >= k frames before T_ref."""
    n = len(fl)
    K = E.MAX_LEAD + 1
    lead_fr = np.array([fl.t_ref[f] - first_miss[f]["frame"] if f in first_miss else -10 ** 9 for f in fl.index])
    called = lead_fr[:, None] >= np.arange(K)[None, :]
    c = pd.DataFrame({"fid": np.repeat(fl.index.values, K), "k": np.tile(np.arange(K), n), "called": called.ravel()})
    c["y"] = np.repeat(fl.label.values == "MISS", K)
    lead = pd.Series({f: (E.ms(lead_fr[i]) if lead_fr[i] >= 0 else np.nan) for i, f in enumerate(fl.index)})
    return E.lead_table(E.summarize_curve(c)), lead


def evaluate(raws, frozen):
    E = tracking_modules().E
    E.GATE_H = float(frozen["gate_h_s"])
    tau_s, tau_o = float(frozen["tau_snapshot"]), float(frozen["tau_online"])
    te, au = _flights()
    summ = json.load(open(RES / "summary.json"))
    vids = [r["video"] for r in raws]
    full = sorted(vids) == VIDEOS
    events = [dict(e, video=r["video"]) for r in raws for e in r["events"]]

    # C: offline frozen scores through the same code (must equal summary.json)
    ts = frozen["test_scores"]
    off_by_v = {}
    for v, t, fid, sc in zip(ts["video"], ts["t"], ts["fid"], ts["score"]):
        off_by_v.setdefault(str(v), {})[int(t)] = (float(np.sign(te.dir[int(fid)])), float(sc))
    # B: the engine's live per-frame scores
    on_by_v = {r["video"]: {int(t): (float(d), float(p)) for t, d, t0, p, g in r["trace"]} for r in raws}
    on_t0 = {r["video"]: {int(t): int(t0) for t, d, t0, p, g in r["trace"]} for r in raws}

    out = dict(population=dict(flights=int(len(te)), BOUNCE=int((te.label == "BOUNCE").sum()),
                               MISS=int((te.label == "MISS").sum()), videos=vids, complete_test_set=full),
               taus=dict(tau_snapshot=tau_s, tau_online=tau_o, gate_h_s=E.GATE_H, persistence=E.PERSIST, lag=E.LAG))
    fl = te if full else te[te.video.isin(vids)]
    S_off = samples_in_window(fl, off_by_v, E)
    S_on = samples_in_window(fl, on_by_v, E)
    tabC, leadC = rule_tables(S_off, fl, E, tau_s, tau_o)
    tabB, leadB = rule_tables(S_on, fl, E, tau_s, tau_o)
    first_miss, first_bounce, unmatched, matched = assign_events(events, fl)
    tabA, leadA = engine_call_tables(fl, first_miss, E)
    cz_by_v = causal_offline_scores(frozen, te, E)
    S_cz = samples_in_window(fl, cz_by_v, E)
    tabCz, leadCz = rule_tables(S_cz, fl, E, tau_s, tau_o)

    out["summary_json"] = dict(snapshot=summ["early_call"]["precision_recall_test_snapshot"],
                               online=summ["early_call"]["precision_recall_test_online"],
                               miss_first_call_lead_ms=summ["early_call"]["miss_first_call_lead_test_ms"])
    out["C_offline_recomputed"] = dict(**tabC, miss_first_call_lead_ms=lead_stats(fl, leadC))
    if full:
        out["C_offline_recomputed"]["equals_summary_json"] = bool(
            tabC["snapshot"] == out["summary_json"]["snapshot"] and tabC["online"] == out["summary_json"]["online"])
    out["C_causal_offline"] = dict(**tabCz, miss_first_call_lead_ms=lead_stats(fl, leadCz),
                                   note="offline tracks and labelled flight windows, hb from points up to the decision "
                                        "frame only (see causal_offline_scores); not in summary.json")
    out["B_engine_scores_offline_rules"] = dict(**tabB, miss_first_call_lead_ms=lead_stats(fl, leadB))
    out["A_engine_calls"] = dict(online=tabA, miss_first_call_lead_ms=lead_stats(fl, leadA),
                                 rule=f"MISS CallEvent = P(miss) >= {tau_o} on {E.PERSIST} consecutive decision "
                                      "frames of one online flight; first call per flight")

    # ---- agreement, flight by flight
    rows = []
    for fid, r in fl.iterrows():
        a_, b_, c_ = leadA.get(fid, np.nan), leadB.get(fid, np.nan), leadC.get(fid, np.nan)
        if (r.label == "MISS" or np.isfinite(a_) or np.isfinite(b_) or np.isfinite(c_)
                or np.isfinite(leadCz.get(fid, np.nan)) or fid in first_bounce):
            rows.append(dict(video=r.video, f_net=int(r.f_net), label=r.label, audit=au.audit[fid] if isinstance(au.audit[fid], str) else None,
                             t0=int(r.t0), t_ref=int(r.t_ref),
                             lead_offline_ms=None if not np.isfinite(c_) else round(float(c_), 1),
                             lead_causal_offline_ms=(None if not np.isfinite(leadCz.get(fid, np.nan))
                                                     else round(float(leadCz.get(fid)), 1)),
                             lead_engine_scores_ms=None if not np.isfinite(b_) else round(float(b_), 1),
                             lead_engine_call_ms=None if not np.isfinite(a_) else round(float(a_), 1),
                             engine_miss_frame=(first_miss[fid]["frame"] if fid in first_miss else None),
                             engine_miss_latency_ms=(round(first_miss[fid]["latency_ms"], 2) if fid in first_miss else None),
                             engine_bounce_frame=(first_bounce[fid]["frame"] if fid in first_bounce else None)))
    out["flights_called_or_miss"] = rows
    same = lambda x, y: (np.isnan(x) and np.isnan(y)) or (np.isfinite(x) and np.isfinite(y) and abs(x - y) < 1e-6)
    ids = list(fl.index)
    out["agreement"] = dict(
        flights=len(ids),
        first_call_lead_identical_B_vs_C=int(sum(same(leadB.get(f, np.nan), leadC.get(f, np.nan)) for f in ids)),
        first_call_lead_identical_A_vs_C=int(sum(same(leadA.get(f, np.nan), leadC.get(f, np.nan)) for f in ids)),
        called_status_identical_A_vs_C=int(sum(np.isfinite(leadA.get(f, np.nan)) == np.isfinite(leadC.get(f, np.nan)) for f in ids)),
        first_call_lead_identical_B_vs_C_causal=int(sum(same(leadB.get(f, np.nan), leadCz.get(f, np.nan)) for f in ids)),
        first_call_lead_identical_A_vs_C_causal=int(sum(same(leadA.get(f, np.nan), leadCz.get(f, np.nan)) for f in ids)))
    mz = S_cz.merge(S_on, on=["fid", "k"], suffixes=("_cz", "_on"))
    dz = (mz.score_cz - mz.score_on).abs().values
    out["agreement"]["scores_engine_vs_causal_offline"] = dict(
        compared=int(len(mz)), abs_diff=pct(dz, (50, 90, 99)) if len(dz) else None,
        frac_abs_diff_le_1e_9=round(float((dz <= 1e-9).mean()), 4) if len(dz) else None,
        note="remaining differences: the offline tracks were stored with 2 decimals (trajectories.py "
             "float_format=%.2f), the engine keeps full precision")
    # scores at the same (flight, decision frame)
    m = S_off.merge(S_on, on=["fid", "k"], suffixes=("_off", "_on"))
    d = (m.score_off - m.score_on).abs().values
    k50 = E.k_of(50)
    m50 = m[m.k == k50]
    t0_same = []
    for fid, r in fl.iterrows():
        o = [on_t0.get(r.video, {}).get(t) for t in range(int(r.t0) + E.NMIN - 1 + E.LAG, int(r.t_ref) + 1)
             if on_by_v.get(r.video, {}).get(t, (0,))[0] == float(np.sign(r.dir))]
        if o:
            t0_same.append(np.mean([x == int(r.t0) for x in o]))
    out["scores"] = dict(
        offline_decision_samples=int(len(S_off)), engine_scored_same_frame_and_direction=int(len(m)),
        coverage=round(len(m) / max(len(S_off), 1), 4),
        engine_samples_in_offline_windows=int(len(S_on)),
        abs_diff=pct(d, (50, 90, 99)) if len(d) else None,
        frac_abs_diff_le_1e_6=round(float((d <= 1e-6).mean()), 4) if len(d) else None,
        frac_abs_diff_le_0_01=round(float((d <= 0.01).mean()), 4) if len(d) else None,
        p_miss_at_50ms_flights_compared=int(len(m50)),
        p_miss_at_50ms_abs_diff=pct((m50.score_off - m50.score_on).abs().values, (50, 90, 99)) if len(m50) else None,
        online_flight_start_equals_offline_t0=round(float(np.mean(t0_same)), 4) if t0_same else None)
    # streaming track vs the offline track of the same frames
    agree, n_cmp = 0, 0
    for r in raws:
        tt = frozen.get("test_tracks", {}).get(r["video"], {})
        on = {int(f): (x, y) for f, x, y, *_ in r["track"] if np.isfinite(x)}
        fr = [f for f in set(tt) | set(on) if f in tt or (r["ranges"] and any(s <= f < e for s, e in r["ranges"]))]
        n_cmp += len(fr)
        agree += sum(1 for f in fr if f in tt and f in on and np.hypot(tt[f][0] - on[f][0], tt[f][1] - on[f][1]) <= 2)
    out["track_agreement_2px_in_rally_ranges"] = dict(frames=n_cmp, fraction=round(agree / max(n_cmp, 1), 4))

    # ---- every emitted call
    n_miss = sum(e["call"] == "MISS" for e in events)
    n_b = sum(e["call"] == "BOUNCE" for e in events)
    fb = [(fid, e) for fid, e in first_bounce.items()]
    in_range = lambda e: next((bool(r["ranges"]) and any(s <= e["frame"] < t for s, t in r["ranges"])
                               for r in raws if r["video"] == e["video"]), None)
    late_miss = [(fid, e) for fid, e in first_miss.items() if e["frame"] > fl.t_ref[fid]]
    out["calls"] = dict(
        emitted=dict(MISS=n_miss, BOUNCE=n_b),
        matched_to_labelled_flights=len(matched),
        miss_calls_on_MISS_flights=int(sum(fl.label[f] == "MISS" for f in first_miss)),
        miss_calls_on_BOUNCE_flights=int(sum(fl.label[f] == "BOUNCE" for f in first_miss)),
        miss_calls_after_T_ref=len(late_miss),
        bounce_calls_on_BOUNCE_flights=int(sum(fl.label[f] == "BOUNCE" for f, _ in fb)),
        bounce_calls_on_MISS_flights=int(sum(fl.label[f] == "MISS" for f, _ in fb)),
        bounce_call_precision=(round(sum(fl.label[f] == "BOUNCE" for f, _ in fb) / len(fb), 4) if fb else None),
        bounce_call_lead_ms=pct([E.ms(fl.t_ref[f] - e["frame"]) for f, e in fb], (10, 50, 90)) if fb else None,
        unmatched=dict(MISS=sum(e["call"] == "MISS" for e in unmatched), BOUNCE=sum(e["call"] == "BOUNCE" for e in unmatched),
                       MISS_inside_rally_ranges=sum(e["call"] == "MISS" and in_range(e) is True for e in unmatched),
                       MISS_outside_rally_ranges=sum(e["call"] == "MISS" and in_range(e) is False for e in unmatched),
                       note="calls on balls that are not one of the 171 labelled flights (serve tosses, rally-ending "
                            "balls after T_ref, practice / pick-up between rallies): not in the evaluated population, "
                            "but a live engine makes them; every MISS and the first 20 BOUNCE listed",
                       first=[dict(video=e["video"], frame=e["frame"], call=e["call"], p_miss=round(e["p_miss"], 4),
                                   direction=e["direction"], inside_rally_range=in_range(e))
                              for e in [u for u in unmatched if u["call"] == "MISS"]
                              + [u for u in unmatched if u["call"] != "MISS"][:20]]))

    # ---- post-hoc audited labels (summary.json label_audit_post_hoc, snapshot rule)
    flA = au if full else au[au.video.isin(vids)]
    SoA, SnA = samples_in_window(flA, off_by_v, E), samples_in_window(flA, on_by_v, E)
    fmA, _, _, _ = assign_events(events, flA)
    out["label_audit_post_hoc"] = dict(
        n_bounce=int((flA.label == "BOUNCE").sum()), n_miss=int((flA.label == "MISS").sum()),
        summary_json_snapshot=summ["label_audit_post_hoc"]["test_audited_relabelled"]["snapshot"],
        C_offline_snapshot=rule_tables(SoA, flA, E, tau_s, tau_o)[0]["snapshot"],
        B_engine_scores_snapshot=rule_tables(SnA, flA, E, tau_s, tau_o)[0]["snapshot"],
        B_engine_scores_online=rule_tables(SnA, flA, E, tau_s, tau_o)[0]["online"],
        A_engine_calls_online=engine_call_tables(flA, fmA, E)[0])
    return out


def timing(raws):
    allready = np.concatenate([r["ready_ms"][:, 1] for r in raws if len(r["ready_ms"])])
    lat = [e["latency_ms"] for r in raws for e in r["events"]]
    fr = sum(r["summary"]["frames"] for r in raws)
    wall = sum(r["summary"]["wall_s"] for r in raws)
    per = {r["video"]: {k: r["summary"].get(k) for k in ("frames", "frames_read", "wall_s", "fps_sustained",
                                                          "source_dropped", "skipped", "pts_index_mismatch")}
           | dict(call_ready_ms=r["summary"]["call_ready_ms"], qwait_ms_p99=r["summary"]["qwait_ms"].get("p99"),
                  detection_within_5px=(r["summary"].get("detection_vs_labels") or {}).get("within_5px"),
                  detection_recall=(r["summary"].get("detection_vs_labels") or {}).get("recall"))
           for r in raws}
    dets = [r["summary"].get("detection_vs_labels") or {} for r in raws]
    nl = sum(d.get("labelled_frames", 0) for d in dets)
    w5 = sum(d.get("within_5px", 0) * d.get("labelled_frames", 0) for d in dets)
    # the first seconds of the first video carry a one-off start-up transient (first real inputs through the
    # compiled detector / classifier); reported separately, nothing is dropped from the totals above
    skip = STARTUP_FRAMES
    r0 = raws[0]
    ready_ss = np.concatenate([r["ready_ms"][r["ready_ms"][:, 0] >= skip, 1] if r is r0 else r["ready_ms"][:, 1]
                               for r in raws if len(r["ready_ms"])])
    lat_ss = [e["latency_ms"] for r in raws for e in r["events"] if r is not r0 or e["frame"] >= skip]
    return dict(frames=fr, video_seconds=round(fr / SOURCE_FPS, 1), wall_s=round(wall, 1),
                fps_sustained=round(fr / wall, 2) if wall else None,
                frames_dropped=sum(r["summary"]["source_dropped"] for r in raws),
                call_ready_ms_all_frames=pct(allready, (50, 90, 99, 99.9)),
                emitted_call_latency_ms=pct(lat, (50, 90, 99)),
                after_startup=dict(excluded=f"frames < {skip} ({skip / SOURCE_FPS:.0f} s) of {r0['video']}, the first video "
                                            "streamed", frames=int(len(ready_ss)),
                                   call_ready_ms=pct(ready_ss, (50, 90, 99, 99.9)), calls=len(lat_ss),
                                   emitted_call_latency_ms=pct(lat_ss, (50, 90, 99))),
                detection_within_5px_pooled=round(w5 / max(nl, 1), 4), labelled_ball_frames=nl,
                per_video=per)


def headline(r):
    """The comparison in one place: A (engine calls), B (engine scores), C (offline) vs summary.json."""
    tab = lambda t: {l: dict(precision=v["precision"], recall=v["recall"], tp=v["tp"], fp=v["fp"]) for l, v in t.items()}
    t = r["timing"] or {}
    return dict(
        config=dict(backend=r["run"]["backend"], batch=r["run"]["batch"], dynamic=r["run"]["dynamic"],
                    pacing=r["run"]["pacing"], gpu=r["run"].get("env", {}).get("gpu")),
        stream=(dict(frames=t["frames"], video_s=t["video_seconds"], wall_s=t["wall_s"], fps=t["fps_sustained"],
                     dropped=t["frames_dropped"], call_ready_ms=t["call_ready_ms_all_frames"],
                     emitted_call_latency_ms=t["emitted_call_latency_ms"], after_startup=t.get("after_startup"),
                     detection_within_5px=t["detection_within_5px_pooled"]) if t else None),
        online_rule_precision_recall=dict(summary_json=tab(r["summary_json"]["online"]),
                                          C_offline_recomputed=tab(r["C_offline_recomputed"]["online"]),
                                          C_causal_offline=tab(r["C_causal_offline"]["online"]),
                                          B_engine_scores=tab(r["B_engine_scores_offline_rules"]["online"]),
                                          A_engine_calls=tab(r["A_engine_calls"]["online"])),
        snapshot_rule_precision_recall=dict(summary_json=tab(r["summary_json"]["snapshot"]),
                                            C_offline_recomputed=tab(r["C_offline_recomputed"]["snapshot"]),
                                            C_causal_offline=tab(r["C_causal_offline"]["snapshot"]),
                                            B_engine_scores=tab(r["B_engine_scores_offline_rules"]["snapshot"])),
        miss_first_call_lead_ms=dict(
            summary_json={k: r["summary_json"]["miss_first_call_lead_ms"][k] for k in ("n_miss", "n_called", "median", "p10", "p90")},
            C_offline_recomputed=r["C_offline_recomputed"]["miss_first_call_lead_ms"],
            C_causal_offline=r["C_causal_offline"]["miss_first_call_lead_ms"],
            B_engine_scores=r["B_engine_scores_offline_rules"]["miss_first_call_lead_ms"],
            A_engine_calls=r["A_engine_calls"]["miss_first_call_lead_ms"]),
        C_equals_summary_json=r["C_offline_recomputed"].get("equals_summary_json"),
        agreement=r["agreement"], scores=r["scores"],
        calls={k: v for k, v in r["calls"].items() if k != "unmatched"} | dict(
            unmatched={k: v for k, v in r["calls"]["unmatched"].items() if k not in ("first", "note")}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="torch-cuda")
    ap.add_argument("--blurball_root", default=os.environ.get("BLURBALL_ROOT"))
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--dynamic", action="store_true")
    ap.add_argument("--no-realtime", dest="realtime", action="store_false", help="process as fast as possible")
    ap.add_argument("--videos", default=",".join(VIDEOS))
    ap.add_argument("--max-frames", type=int, default=None, help="per video (smoke tests)")
    ap.add_argument("--frame-offset", type=int, default=0, help="source frame number of each file's first frame "
                    "(0 for the full OpenTTGames videos; smoke tests on a cut clip)")
    ap.add_argument("--ottg_root", default=os.environ.get("OTTG_ROOT", str(REPO / "openttgames")))
    ap.add_argument("--frozen", default=str(FROZEN_PATH))
    ap.add_argument("--raw", default=None, help="pickle of the raw streaming output (default next to --out)")
    ap.add_argument("--from-raw", default=None, help="rescore a saved raw pickle instead of streaming")
    ap.add_argument("--replay-detections", default=None, help="diagnostic: directory with the offline detector's "
                    "<video>_*_blurball.npz (+ <video>_0.txt ranges); replays them through the engine logic, no video")
    ap.add_argument("--host", default=None)
    ap.add_argument("--label", default=None, help="key of this run in the output file (default: backend name)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    assert_paper_only()
    frozen = load_frozen(a.frozen)
    if a.from_raw:
        blob = pickle.load(open(a.from_raw, "rb"))
        raws, meta = blob["raws"], blob["meta"]
    elif a.replay_detections:
        raws = [replay_video(frozen, v, a.replay_detections) for v in a.videos.split(",")]
        meta = dict(backend="offline detections (detect.py npz) -> engine tracker / segmentation / classifier / rule",
                    batch=None, dynamic=None, realtime=False, pacing="replay, no video decoded", env={})
    else:
        D = tracking_modules().D
        be = make_backend(a.backend, a.blurball_root)
        if hasattr(be, "warmup"):
            be.warmup(tuple(range(1, a.batch + 1)) if a.dynamic else (a.batch,))
        from .bench_gpu import env_info
        meta = dict(backend=be.name, batch=a.batch, dynamic=a.dynamic, realtime=a.realtime,
                    pacing=(f"{SOURCE_FPS:.0f} fps, no frame dropped" if a.realtime else "as fast as possible"),
                    env=env_info(), started=datetime.datetime.now().isoformat(timespec="seconds"))
        raws = []
        raw_path = a.raw or str(Path(a.out).with_suffix("")) + "_raw.pkl"
        os.makedirs(os.path.dirname(os.path.abspath(raw_path)), exist_ok=True)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        for v in a.videos.split(","):
            r = stream_video(be, frozen, v, a, D)
            raws.append(r)
            s = r["summary"]
            print(f"{v}: {s['frames']} frames {s['wall_s']} s ({s['fps_sustained']} fps), dropped {s['source_dropped']}, "
                  f"qwait p99 {s['qwait_ms'].get('p99')} ms, call_ready p50/p90 {s['call_ready_ms'].get('p50')}/"
                  f"{s['call_ready_ms'].get('p90')} ms, {len(r['events'])} calls, det within 5px "
                  f"{(s.get('detection_vs_labels') or {}).get('within_5px')}", flush=True)
            pickle.dump(dict(raws=raws, meta=meta), open(raw_path, "wb"), protocol=4)
        meta["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
        pickle.dump(dict(raws=raws, meta=meta), open(raw_path, "wb"), protocol=4)
        with open(Path(a.out).parent / f"online_events_{a.host or meta['env'].get('gpu', 'gpu').replace(' ', '_')}.jsonl", "w") as fh:
            for r in raws:
                for e in r["events"]:
                    fh.write(json.dumps(dict(e, video=r["video"]), default=float) + "\n")
    res = dict(run=meta, timing=(None if a.replay_detections or "wall_s" not in raws[0]["summary"] else timing(raws)),
               **evaluate(raws, frozen))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    label = a.label or meta.get("backend", "run")
    doc = json.load(open(a.out)) if os.path.exists(a.out) else {}
    if "runs" not in doc:      # one file, one entry per engine config (label)
        doc = dict(what="held-out test_1..test_7 streamed through engine.vision (online) vs the offline evaluation "
                        "(results/tracking/summary.json); paper only", definitions=__doc__.split("Usage")[0].strip(),
                   runs={})
    doc["runs"][label] = res
    doc["headline"] = {k: headline(v) for k, v in doc["runs"].items()}
    json.dump(doc, open(a.out, "w"), indent=1, default=float)
    print(json.dumps(doc["headline"][label], indent=1, default=float))
    show = {k: res[k] for k in ("timing", "agreement", "scores", "calls")}
    show["timing"] = {k: v for k, v in (show["timing"] or {}).items() if k != "per_video"}
    print(json.dumps(show, indent=1, default=float))
    for k in ("summary_json", "C_offline_recomputed", "B_engine_scores_offline_rules", "A_engine_calls"):
        print(k, json.dumps({m: {l: (x["precision"], x["recall"], x["tp"], x["fp"]) for l, x in t.items()}
                             for m, t in res[k].items() if m in ("snapshot", "online")}),
              res[k].get("miss_first_call_lead_ms"))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
