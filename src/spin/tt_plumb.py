"""Plumbing test of the spin-aware pipeline on raw video frames (laptop, CPU): no labels, no metric.

  video frames -> BlurBall (ONNX, the detector the frozen tracker uses, 3-in/3-out, step 1)
               -> engine.vision.stream.StreamingDetector / OnlineTracker (= detect.py + trajectories.py)
               -> camera from the video's table segmentation masks (tt_camera)
               -> the longest one-directional run of the track as a pseudo-flight
               -> anchor search + online spin-model fits at every decision frame (tt_features)

It reads no ball / event annotations and computes no accuracy of any kind; it only checks that every
stage runs on real pixels and returns finite features, and times the fits.

Usage: python src/spin/tt_plumb.py --video data/vision/test_2_copyts.mp4 --masks test_2 --frames 240
"""
import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (HERE, os.path.join(REPO, "src", "tracking"), REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def runs(trk, max_gap=4, min_len=12):
    """Split the track into pseudo-flights: one-directional runs (no gap > max_gap, no x reversal), also
    cut after every bounce (flights.last_bounce's local-maximum test), as real flights end at contact."""
    import tt_features as TF
    fr = sorted(trk)
    out, cur, d = [], [], 0.0
    for f in fr:
        if cur and (f - cur[-1] > max_gap or TF.is_bounce(trk, cur[-1])):
            out.append(cur)
            cur, d = [], 0.0
        if cur:
            dx = trk[f][0] - trk[cur[-1]][0]
            if d == 0.0 and abs(dx) > 2:
                d = np.sign(dx)
            elif d != 0.0 and dx * d < -2:
                out.append(cur)
                cur, d = [], 0.0
        cur.append(f)
    if cur:
        out.append(cur)
    return [r for r in out if len(r) >= min_len]


def main(a):
    import cv2
    from engine.vision import stream as ST
    import tt_camera
    import tt_features as TF
    import tt_early_call as EC
    M = ST.tracking_modules()
    D, T = M.D, M.T
    backend = ST.make_backend(f"onnx-{a.provider}", threads=a.threads)
    det = ST.StreamingDetector(backend, D)
    trkr = ST.OnlineTracker(T)
    cap = cv2.VideoCapture(a.video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, a.start)
    t_det = time.time()
    n = 0
    for i in range(a.start, a.start + a.frames):
        ok, bgr = cap.read()
        if not ok:
            break
        for idx, c in det.push(i, ST.preprocess(bgr, D)):
            trkr.update(idx, c)
        n += 1
    for idx, c in det.flush():
        trkr.update(idx, c)
    t_det = time.time() - t_det
    trk = trkr.trk
    print(f"detector {backend.name}: {n} frames in {t_det:.1f} s ({1000 * t_det / max(n, 1):.0f} ms/frame), "
          f"{len(trk)} frames with a tracked ball", flush=True)
    # camera from the segmentation masks (annotation source (a) of DEVIATIONS.md H3-D8; no ball/event labels)
    import common as C
    corners0 = C.table_geometry(a.masks)["corners"]
    cam, cinfo = tt_camera.camera_for_video(a.masks, C.MARKUP, corners0)
    print("camera", json.dumps(cinfo["edge_fit"]), flush=True)
    rs = runs(trk)
    report = {"note": "plumbing only: no labels read, no metric computed", "video": a.video,
              "frames": [a.start, a.start + n], "detector": backend.name,
              "detector_ms_per_frame": round(1000 * t_det / max(n, 1), 1), "tracked_frames": len(trk),
              "camera": cinfo["edge_fit"], "runs": [[r[0], r[-1], len(r)] for r in rs]}
    if not rs:
        report["result"] = "no run of >= 12 tracked frames in this window; try another --start"
        print(json.dumps(report, indent=1))
        return report
    r = max(rs, key=len)
    d = float(np.sign(trk[r[-1]][0] - trk[r[0]][0]))
    t0, t_end = r[0], r[-1]
    anchor, ainfo = TF.find_anchor(trk, t0, d, cam)
    fr = np.array([f for f in range(t0, t_end + 1) if f in trk])
    uv = np.array([trk[f] for f in fr], float)
    dec = list(range(t0 + TF.NMIN - 1 + TF.LAG, t_end + 1))
    t_fit = time.time()
    feats = TF.online_features(cam, fr, uv, d, dec, anchor, spin=True, prefix="ph_", t_s=t0)
    t_fit = time.time() - t_fit
    t_ns = time.time()
    ns = TF.online_features(cam, fr, uv, d, dec, anchor, spin=False, prefix="ns_", t_s=t0)
    t_ns = time.time() - t_ns
    got = [f for f in feats if f is not None]
    oks = [f for f in got if f["ph_ok"] == 1]
    want = [c for c in EC.PH_FEATS if c != "ph_anchor"]
    missing = sorted(set(want) - set(got[-1])) if got else want
    last = {k: round(float(v), 3) for k, v in oks[-1].items()} if oks else {}
    core = ["ph_top", "ph_side", "ph_speed", "ph_x_land", "ph_p_in", "ph_rms_px"]
    finite = all(np.isfinite(f[k]) for f in oks for k in core)
    report.update({
        "pseudo_flight": {"t0": t0, "t_end": t_end, "dir": d, "n_points": int(len(fr))}, "anchor": ainfo,
        "n_decision_frames": len(dec), "n_with_features": len(got), "n_fit_ok": len(oks),
        "n_nospin_ok": sum(1 for f in ns if f is not None and f["ns_ok"] == 1),
        "missing_feature_columns": missing, "core_features_finite": bool(finite),
        "ms_per_decision_frame_spin": round(1000 * t_fit / max(len(dec), 1), 1),
        "ms_per_decision_frame_nospin": round(1000 * t_ns / max(len(dec), 1), 1),
        "features_at_last_decision_frame": last,
        "result": "PASS" if (oks and not missing and finite) else "FAIL"})
    print(json.dumps(report, indent=1))
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump(report, open(a.out, "w"), indent=1)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=os.path.join(REPO, "data", "vision", "test_2_copyts.mp4"))
    ap.add_argument("--masks", default="test_2", help="OpenTTGames video whose segmentation masks give the table")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--frames", type=int, default=240)
    ap.add_argument("--provider", default="cpu", help="onnx provider: cpu | coreml | coreml-gpu16 | cuda ...")
    ap.add_argument("--threads", type=int, default=3)
    ap.add_argument("--out", default=None)
    main(ap.parse_args())
