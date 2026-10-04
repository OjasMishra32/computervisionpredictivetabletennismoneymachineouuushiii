"""Real tennis footage with OUR tennis tracker's output, for the video (segment 3c, before the 3D replay).

    # 1. detectors on HiPerGator (GPU): TrackNet ball + TennisCourtDetector keypoints on every frame
    VIDEO=$ROOT/data/real_footage/rally_pexels_10378830_t1.4-11.4s.mp4 sbatch hpg/tennis_detect_video.sbatch
    #    -> copy work/detect_video/<clip>.npz to results/viz/v60_assets/tennis_real/tennis_detect_raw.npz
    python scripts/tennis_real_tracked.py process   # npz + clip -> tennis_detections.json
    python scripts/tennis_real_tracked.py qa        # -> tennis_spotcheck.jpg (48 random tracked positions, by-eye check)
    python scripts/tennis_real_tracked.py render    # -> tennis_tracked.mp4 (1920x1080, 30 fps, 10 s),
                                                    #    tennis_tracked.png (300 dpi still), tennis_tracked_onscreen.json
    python scripts/tennis_real_tracked.py render --at 4.0 --out f.png   # one preview frame (QA)

Footage: "Tennis Players Playing Match" by Gelato Prod, Pexels (Pexels License); source, licence and trim
in results/viz/v60_assets/tennis_real/LICENSE.md. No in/out call is drawn: single-camera 3D error is
0.7-1.2 m (results/tennis_tracking), so this clip shows tracking only.

`process` turns the detector output into one ball position and one court homography per frame:
  * ball: src/tennis_tracking/link.py. TrackNet heatmap blobs, minus blobs of balls lying still on the
    court, linked into flight tracklets. The repo's one-blob-per-frame pick
    (BallDetector.postprocess) locks onto the still balls on this clip; its picks are kept in the JSON
    for comparison.
  * court: src/tennis_tracking/court_lines.py. The detector keypoint positions without their labels
    (several are mislabelled on this oblique view), matched to the court model and fitted to the
    painted line pixels of each frame.
All coordinates in the JSON are pixels of the 1920x1080 rally clip. The detectors ran on frames resized
to 1280x720, so their output is multiplied by 1.5.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src/tennis_tracking"))
import court_lines as CL  # noqa: E402
from geometry import COURT_KPS, apply_h  # noqa: E402
from link import ball_track  # noqa: E402
from scripts.backtest_example_match import Canvas, Face  # noqa: E402  (Inter + GPOS kerning, 2x supersampling)

ASSET = ROOT / "results/viz/v60_assets/tennis_real"
RALLY = ASSET / "rally_pexels_10378830_t1.4-11.4s.mp4"
RAW = ASSET / "tennis_detect_raw.npz"
DET_JSON = ASSET / "tennis_detections.json"
MP4, PNG, ONSCREEN = ASSET / "tennis_tracked.mp4", ASSET / "tennis_tracked.png", ASSET / "tennis_tracked_onscreen.json"
TRIM_T0 = 1.4                      # trim start in the Pexels source (s); LICENSE.md
W, H, FPS = 1920, 1080, 30
S = 1.5                            # detector frame (1280x720) -> clip pixels
LINK_KW = dict(min_area=5, min_len=4, still_px=6.0, still_win=8, still_min=8, max_gap=3, gate_px=80.0)

ATTRIBUTION = 'Tennis footage: "Tennis Players Playing Match" by Gelato Prod, Pexels (Pexels License)'
ATTR_LINES = ('Tennis footage: "Tennis Players Playing Match"', "by Gelato Prod, Pexels (Pexels License)")
MODEL_LINE = "Ball tracking: our tennis model"
C_WHITE, C_ORANGE = (245, 245, 247), (255, 107, 26)   # #FF6B1A
C_GREY_FOOT = (174, 174, 178)      # grey type over footage (#86868b is too dark on the dark fence)
# Type block: right third, right-aligned at the 8% margin, over the dark windscreen right of the court (the
# only dark, line-free area of this shot that stays clear of the players and the ball for all 300 frames, and
# away from the bottom-centre captions of the final edit). Baselines in layout px.
X_RIGHT = 1766
Y_COUNTER, Y_MODEL, Y_ATTR = 530, 556, (580, 600)
PX_BIG, PX_SMALL = 22, 15
TRAIL = 10                         # trail length in frames (0.33 s)
T_IN0, T_IN1, T_CNT0, T_CNT1 = 0.15, 0.75, 0.30, 1.10
T_LINES, LINE_DUR, LINE_STAGGER, T_LINES_REST = 0.10, 0.55, 0.05, 1.6   # court lines draw in, then settle
A_LINE_DRAW, A_LINE_REST = 0.70, 0.30


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_frames(path: Path, size=None):
    cap = cv2.VideoCapture(str(path))
    while True:
        ok, f = cap.read()
        if not ok:
            break
        yield f if size is None else cv2.resize(f, size, interpolation=cv2.INTER_AREA)
    cap.release()


# ------------------------------------------------------------------------------------------ process
def process():
    d = np.load(RAW)
    assert str(d["video_sha256"]) == sha256(RALLY), "detector output is not from this clip"
    n = len(d["ball_xy"])
    blobs = [d["cand_xya"][d["cand_frame"] == i] for i in range(n)]
    xy, link_info = ball_track(blobs, **LINK_KW)
    pick = d["ball_xy"]

    Hs, cinfo, Hp = [], [], None
    for i, f in enumerate(read_frames(RALLY, (1280, 720))):
        Hw, info = CL.register(f, d["court_kps"][i], Hp)
        Hs.append(Hw)
        cinfo.append(info)
        Hp = Hw if Hw is not None else Hp
    assert len(Hs) == n
    Sm = np.diag([S, S, 1.0])

    def px(a):
        return None if not np.isfinite(a).all() else [round(float(a[0]) * S, 1), round(float(a[1]) * S, 1)]

    frames = []
    for i in range(n):
        Hc = None if Hs[i] is None else Sm @ Hs[i]
        frames.append({
            "i": i, "t": round(i / FPS, 4), "t_source": round(TRIM_T0 + i / FPS, 4),
            "ball_xy": px(xy[i]),
            "repo_pick_xy": px(pick[i]),
            "court_kps_detector": [px(k) for k in d["court_kps"][i]],
            "court_H": None if Hc is None else [[float(v) for v in r] for r in (Hc / Hc[2, 2])],
            "court_line_fit_px": None if Hs[i] is None else round(cinfo[i]["chamfer_px"] * S, 3),
            "court_search": bool(cinfo[i]["searched"]),
        })
    det = np.isfinite(xy[:, 0])
    pk = np.isfinite(pick[:, 0])
    agree = det & pk & (np.hypot(*(xy - pick).T) < 5)
    still_pick = pk & ~agree
    ch = np.array([c.get("chamfer_px", np.nan) for c in cinfo]) * S
    P = np.array([apply_h(Sm @ Hw, COURT_KPS) for Hw in Hs if Hw is not None])
    kps_det = np.isfinite(d["court_kps"][..., 0])
    # how many detector keypoints sit within 12 px (clip pixels) of the court point their label names, and of any
    lab_ok = any_ok = n_kp = 0
    for i in range(n):
        if Hs[i] is None:
            continue
        Pm = apply_h(Sm @ Hs[i], COURT_KPS)
        for j in np.where(kps_det[i])[0]:
            dd = np.hypot(*(Pm - d["court_kps"][i, j] * S).T)
            n_kp += 1
            lab_ok += dd[j] < 12
            any_ok += dd.min() < 12
    seg = [{"first": int(a), "last": int(b), "detections": int(c)} for a, b, c in sorted(link_info["tracklets_kept"])]
    stats = {
        "frames": n, "fps": FPS, "duration_s": n / FPS,
        "ball_frames_detected": int(det.sum()),
        "ball_detected_share": round(float(det.mean()), 4),
        "ball_detected_share_of_frames_with_3_frame_input": round(float(det[2:].mean()), 4),
        "ball_detected_pct_on_screen": int(round(100 * det.mean())),
        "longest_gap_frames": int(max(len(g) for g in "".join("1" if v else "0" for v in det).split("1"))),
        "flight_segments": seg,
        "repo_pick": {
            "frames_with_a_pick": int(pk.sum()), "share": round(float(pk.mean()), 4),
            "picks_on_the_tracked_ball_within_5px": int(agree.sum()),
            "picks_elsewhere": int(still_pick.sum()),
            "note": "BallDetector.postprocess keeps one heatmap blob per frame and stays within 80 px of its previous "
                    "pick, so on this clip it sits on balls lying still on the court for whole stretches "
                    "(frames 32-42, 63-72, 135-156 and 248-259, among others). Its 93% is therefore not a ball-detection rate.",
        },
        "heatmap_blobs": {k: link_info[k] for k in ("blobs", "still_blobs", "moving_blobs")},
        "court": {
            "detector_keypoints_per_frame_median": float(np.median(kps_det.sum(1))),
            "detector_keypoints_total": int(n_kp),
            "detector_keypoints_within_12px_of_their_labelled_court_point": int(lab_ok),
            "detector_keypoints_within_12px_of_any_court_point": int(any_ok),
            "frames_registered": int(sum(h is not None for h in Hs)),
            "full_search_frames": int(sum(c["searched"] for c in cinfo)),
            "line_fit_px_median_p90_max": [round(float(np.nanpercentile(ch, q)), 3) for q in (50, 90, 100)],
            "camera_drift_px_first_to_last": [round(float(v), 1) for v in (P[-1] - P[0]).mean(0)],
            "frame_to_frame_motion_px_median_max": [round(float(v), 2) for v in
                                                    np.percentile(np.abs(np.diff(P, axis=0)).max(axis=(1, 2)), [50, 100])],
        },
    }
    out = {
        "about": "OUR tennis tracker on a freely licensed real rally: per-frame ball position and court "
                 "homography. Pixels of the 1920x1080 rally clip, t in seconds from the clip start "
                 "(t_source = t + 1.4 s in the Pexels source). No in/out call is made on this clip "
                 "(single-camera 3D error 0.7-1.2 m, results/tennis_tracking).",
        "clip": {"file": str(RALLY.relative_to(ROOT)), "sha256": sha256(RALLY), "size": [W, H], "fps": FPS,
                 "frames": n, "licence": "Pexels License; see LICENSE.md", "attribution": ATTRIBUTION},
        "detectors": {
            "ball": "TrackNet (yastrebksv/TrackNet weights, BallDetector from yastrebksv/TennisProject @ b7552e9), "
                    "the same model and heatmap threshold as src/tennis_tracking/detect.py (README: precision 0.97, "
                    "recall 0.94 within 5 px on the broadcast test games)",
            "court": "TennisCourtDetector (yastrebksv @ e5cd4f1) 14 keypoints + refine_kps, as in detect.py",
            "input": "every frame resized 1920x1080 -> 1280x720 (the detectors' native size); outputs x 1.5",
            "run": {"where": "HiPerGator, SLURM job 44630137, " + str(d["device"]),
                    "code": "src/tennis_tracking/detect_video.py via hpg/tennis_detect_video.sbatch",
                    "seconds_read_ball_court": [round(float(s), 1) for s in d["seconds"]],
                    "torch": str(d["torch_version"]), "opencv": str(d["cv2_version"]),
                    "raw_output": str(RAW.relative_to(ROOT)), "raw_output_sha256": sha256(RAW)},
        },
        "postprocessing": {
            "ball": "src/tennis_tracking/link.py (offline: uses past and future frames). Heatmap blobs of balls "
                    "lying still on the court are removed, the rest linked into flight tracklets, at most one ball "
                    "per frame. Positions are blob centroids: no smoothing, no interpolation. Parameters: "
                    + json.dumps(LINK_KW),
            "court": "src/tennis_tracking/court_lines.py. On this oblique view few detector keypoints sit on the court "
                     "point their label names (stats.court), so a labelled fit is meaningless. The keypoint positions "
                     "are matched to the court model without labels, "
                     "the hypotheses ranked by how well all nine painted lines fit, and the homography fitted to "
                     "the line pixels of every frame (started from the previous frame). court_line_fit_px = mean "
                     "distance from the drawn lines to the nearest painted-line pixel.",
        },
        "stats": stats,
        "fields": {"ball_xy": "our tracked ball centre (null = no ball this frame)",
                   "repo_pick_xy": "BallDetector.postprocess's own one-blob pick, for comparison (not used)",
                   "court_kps_detector": "raw TennisCourtDetector keypoints in its label order (not used as labelled)",
                   "court_H": "3x3 homography, court metres (x across, y towards the far baseline, origin at the "
                              "centre) -> clip pixels"},
        "run": {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "script": "scripts/tennis_real_tracked.py process"},
        "frames": frames,
    }
    DET_JSON.write_text(json.dumps(out, indent=1))
    print(json.dumps(stats, indent=1))


# ------------------------------------------------------------------------------------------ qa
QA_SEED, QA_N = 7, 48
QA_RESULT = ("48 of 48 sampled tracked positions are on the ball in play (checked by eye on the contact sheet, "
             "2026-10-03; one, frame 172, sits about 10 px off the ball centre). Frame 39 shows a ball lying still "
             "next to the tracked ball; the tracked one is the ball in flight.")


def qa():
    """Contact sheet of QA_N random tracked positions (96 px crops, 2x, ring = our position) for a by-eye check;
    the result is recorded in tennis_detections.json under qa."""
    det = json.loads(DET_JSON.read_text())
    fr = det["frames"]
    idx = [f["i"] for f in fr if f["ball_xy"] is not None]
    pick = sorted(int(v) for v in np.random.default_rng(QA_SEED).choice(idx, QA_N, replace=False))
    R, tiles, want = 48, {}, set(pick)
    for k, f in enumerate(read_frames(RALLY)):
        if k in want:
            x, y = fr[k]["ball_xy"]
            g = cv2.copyMakeBorder(f, R, R, R, R, cv2.BORDER_CONSTANT)
            c = cv2.resize(g[int(y):int(y) + 2 * R, int(x):int(x) + 2 * R], (192, 192), interpolation=cv2.INTER_NEAREST)
            cv2.circle(c, (96, 96), 22, (26, 107, 255), 1, cv2.LINE_AA)
            cv2.putText(c, str(k), (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            tiles[k] = c
    rows = [np.hstack([tiles[k] for k in pick[r * 8:(r + 1) * 8]]) for r in range(QA_N // 8)]
    sheet = ASSET / "tennis_spotcheck.jpg"
    cv2.imwrite(str(sheet), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
    det["qa"] = {"spotcheck_sheet": str(sheet.relative_to(ROOT)), "seed": QA_SEED, "frames": pick,
                 "result_by_eye": QA_RESULT,
                 "limits": "no ground-truth labels exist for this clip, so no precision/recall in pixels; "
                           "the 89% counts frames with a tracked ball, not verified-correct frames"}
    DET_JSON.write_text(json.dumps(det, indent=1))
    print(sheet, pick)


# ------------------------------------------------------------------------------------------ render
def _ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def _vignette():
    """Subtle: corners down to -20% brightness (the only gradient the spec allows on footage)."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)) / np.sqrt(2)
    return (1 - 0.20 * np.clip((r - 0.45) / 0.55, 0, 1) ** 1.5)[..., None]


def lines_px(Hc):
    return [apply_h(Hc, np.array([a, b])) for a, b in CL.COURT_LINES.values()]


def _type(cv, pct_shown, pct_final, a):
    """Counter (white, 22 px) and three grey 15 px lines, right-aligned at X_RIGHT. While the counter counts up
    (during the fade-in) its line stays anchored where the final line starts, so the text never jumps left."""
    line = "Ball detected in {}% of frames"
    x0 = X_RIGHT - cv.width(line.format(pct_final), "500", PX_BIG)
    cv.text(x0, Y_COUNTER, line.format(pct_shown), "500", PX_BIG, C_WHITE, a=a)
    cv.text(X_RIGHT, Y_MODEL, MODEL_LINE, "400", PX_SMALL, C_GREY_FOOT, a=a, align="right")
    for y, s in zip(Y_ATTR, ATTR_LINES):
        cv.text(X_RIGHT, y, s, "400", PX_SMALL, C_GREY_FOOT, a=a, align="right")


SHADOW: dict = {}


def _shadow(faces, scale, pct):
    """Soft dark halo under the type (blurred, dilated text mask), so it reads over the fence's light seams."""
    from PIL import ImageFilter
    if scale not in SHADOW:
        c = Canvas(faces, scale)
        _type(c, pct, pct, 1.0)
        K = 2 * scale
        m = c.im.convert("L").point(lambda v: 255 if v > 20 else 0)
        m = m.filter(ImageFilter.MaxFilter(2 * (3 * K // 2) + 1)).filter(ImageFilter.GaussianBlur(7 * K))
        SHADOW[scale] = m
    return SHADOW[scale]


def draw(faces, base_rgb, det, i, t, scale=1, still_from=None):
    """One frame. base_rgb: the clip frame (H x W x 3, uint8, vignette applied). still_from: draw the trail
    from this frame on (the still) and every overlay at its resting state."""
    from PIL import Image
    K = 2 * scale
    img = Image.fromarray(base_rgb)
    img = img.resize((W * K, H * K), Image.NEAREST if scale == 1 else Image.LANCZOS)
    st = det["stats"]
    pct = st["ball_detected_pct_on_screen"]
    rest = still_from is not None
    a_t = 1.0 if rest else _ease((t - T_IN0) / (T_IN1 - T_IN0))
    if a_t > 0:
        sh = _shadow(faces, scale, pct).point(lambda v: int(v * 0.55 * a_t))
        img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, sh)
    cv = Canvas(faces, scale, img)
    fr = det["frames"]
    # court lines: draw in along each line (0.10-1.0 s), then settle to a faint white
    if fr[i]["court_H"] is not None:
        settle = 1.0 if rest else _ease((t - (T_LINES + LINE_DUR + 8 * LINE_STAGGER)) /
                                        (T_LINES_REST - T_LINES - LINE_DUR - 8 * LINE_STAGGER))
        a_line = A_LINE_DRAW + (A_LINE_REST - A_LINE_DRAW) * settle
        for j, p in enumerate(lines_px(np.array(fr[i]["court_H"]))):
            u = 1.0 if rest else _ease((t - T_LINES - j * LINE_STAGGER) / LINE_DUR)
            if u > 0:
                cv.line([tuple(p[0]), tuple(p[0] + u * (p[1] - p[0]))], C_WHITE, 1.5 + 1.5 * (1 - settle), a=a_line)
    # ball trail: detections of the last TRAIL frames (or of the whole shot for the still)
    lo = (i - TRAIL + 1) if not rest else still_from
    pts = [(k, fr[k]["ball_xy"]) for k in range(max(0, lo), i + 1) if fr[k]["ball_xy"] is not None]
    span = max(1, i - lo + 1)
    for (k0, p0), (k1, p1) in zip(pts, pts[1:]):
        if k1 - k0 > 3:
            continue
        age = (i - k1) / span
        a = (1 - age) ** (1.4 if not rest else 0.5)
        w = 1.4 + 2.2 * (1 - age)
        col = tuple(int(round(c0 + (c1 - c0) * max(0.0, 1 - age * 4) * 0.55)) for c0, c1 in zip(C_ORANGE, C_WHITE))
        cv.line([tuple(p0), tuple(p1)], col, w, a=0.95 * a)
    if fr[i]["ball_xy"] is not None:
        x, y = fr[i]["ball_xy"]
        cv.ring(x, y, 9.0, C_ORANGE, a=0.95, w=1.6)
    shown = pct if rest else int(round(pct * _ease((t - T_CNT0) / (T_CNT1 - T_CNT0))))
    _type(cv, shown, pct, a_t)
    return cv.out()


def render(argv):
    ap = argparse.ArgumentParser(prog="tennis_real_tracked.py render")
    ap.add_argument("--at", type=float, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--still-only", action="store_true")
    a = ap.parse_args(argv)
    det = json.loads(DET_JSON.read_text())
    assert det["clip"]["sha256"] == sha256(RALLY)
    faces = {w: Face(f"Inter_{n}.ttf") for w, n in (("400", "400Regular"), ("500", "500Medium"),
                                                     ("600", "600SemiBold"))}
    vig = _vignette()
    n = det["clip"]["frames"]

    def base(f_bgr):
        return np.clip(cv2.cvtColor(f_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) * vig, 0, 255).astype(np.uint8)

    if a.at is not None:
        i = min(n - 1, int(round(a.at * FPS)))
        f = next(f for k, f in enumerate(read_frames(RALLY)) if k == i)
        draw(faces, base(f), det, i, a.at).save(a.out or str(ASSET / f"preview_{a.at:.2f}.png"))
        return
    still_i, still_from = STILL
    still_frame = None
    if not a.still_only:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(FPS), "-i", "-", "-i", str(RALLY), "-map", "0:v", "-map", "1:a", "-c:a", "copy", "-shortest",
               "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
               "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-movflags", "+faststart", "-tag:v", "avc1", str(MP4)]
        pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        k = -1
        for k, f in enumerate(read_frames(RALLY)):
            assert f.shape[:2] == (H, W)
            if k == still_i:
                still_frame = f
            pr.stdin.write(draw(faces, base(f), det, k, k / FPS).tobytes())
            if k % 60 == 0:
                print(f"frame {k}/{n}", flush=True)
        pr.stdin.close()
        assert pr.wait() == 0 and k == n - 1
    if still_frame is None:
        still_frame = next(f for k, f in enumerate(read_frames(RALLY)) if k == still_i)
    # 300 dpi still: 3840 x 2160 px (12.8 x 7.2 in), one whole shot's detections as the trail
    still = draw(faces, base(still_frame), det, still_i, n / FPS, scale=2, still_from=still_from)
    still.save(PNG, dpi=(300, 300), optimize=True)
    st = det["stats"]
    onscreen = {
        "outputs": {"video": str(MP4.relative_to(ROOT)), "still": str(PNG.relative_to(ROOT)),
                    "video_spec": f"{W}x{H}, {FPS} fps, {n / FPS:g} s ({n} frames), real speed (no slow motion), "
                                  "H.264 yuv420p bt709 CRF 16, the clip's own AAC audio",
                    "still_spec": f"{still.size[0]}x{still.size[1]} px, 300 dpi, clip frame {still_i} "
                                  f"(t = {still_i / FPS:.2f} s), trail = every tracked position of frames "
                                  f"{still_from}-{still_i} (one shot)"},
        "on_screen": {"counter": f"Ball detected in {st['ball_detected_pct_on_screen']}% of frames",
                      "counter_value": st["ball_detected_pct_on_screen"],
                      "counter_source": f"tennis_detections.json stats.ball_detected_share = "
                                        f"{st['ball_frames_detected']}/{st['frames']} frames",
                      "counter_animation": f"counts up 0 -> {st['ball_detected_pct_on_screen']} over "
                                           f"{T_CNT0}-{T_CNT1} s, then fixed",
                      "model_line": MODEL_LINE, "attribution": ATTRIBUTION,
                      "type": f"Inter 500 {PX_BIG} px white (counter, counts up 0 -> final during the fade-in); Inter 400 {PX_SMALL} px grey #aeaeb2 (model "
                              f"line, two-line attribution); right-aligned at x = {X_RIGHT} (8% margin), baselines "
                              f"y = {Y_COUNTER}, {Y_MODEL}, {Y_ATTR[0]}, {Y_ATTR[1]}, over the dark windscreen right of "
                              "the court; soft dark halo under the type; fades in "
                              f"{T_IN0}-{T_IN1} s",
                      "no_call": "no in/out call, no landing point, no speed or spin readout"},
        "what_is_drawn": {
            "trail": f"our tracked ball positions (tennis_detections.json ball_xy) of the last {TRAIL} frames "
                     "(0.33 s), #FF6B1A fading with age and whitening towards the newest point; consecutive "
                     "detections are joined only if at most 3 frames apart; frames without a detection draw "
                     "no ring and add no point",
            "ring": "thin #FF6B1A ring (r = 9 px) around the ball in frames where it was tracked",
            "court_lines": f"the nine painted court lines projected with that frame's court_H; each draws in along "
                           f"its length from {T_LINES} s (white {A_LINE_DRAW:.0%}, 3 px), then settles by "
                           f"{T_LINES_REST} s to white {A_LINE_REST:.0%}, 1.5 px for the rest of the clip",
            "vignette": "subtle radial vignette, corners down to -20% brightness",
        },
        "source": {"detections": str(DET_JSON.relative_to(ROOT)), "detections_sha256": sha256(DET_JSON),
                   "clip_sha256": det["clip"]["sha256"]},
        "run": {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "script": "scripts/tennis_real_tracked.py render"},
    }
    ONSCREEN.write_text(json.dumps(onscreen, indent=1))
    print(json.dumps(onscreen["outputs"], indent=1))


STILL = (206, 187)   # (frame, first frame of the shot): far-side hit -> bounce -> near player about to hit


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "render":
        render(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "process":
        process()
    elif len(sys.argv) > 1 and sys.argv[1] == "qa":
        qa()
    else:
        print(__doc__)
