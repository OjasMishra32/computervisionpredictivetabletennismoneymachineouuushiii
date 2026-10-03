"""Labelled flights (hit -> first bounce) of the TrackNet tennis dataset, with ground truth.

Labels (Label.csv per clip): visibility 0..3, x, y (pixel, 1280x720; the labelled point is the
latest end of the motion-blur trace), status 0 flying / 1 hit / 2 bounce. A hit or bounce is
sometimes marked on two consecutive frames; runs are merged into one event.

A flight = the segment from a hit to the next event, kept only if that next event is a bounce
(a "call"). The first hit of every clip is the serve (each clip is one rally "from serving to
score", dataset Readme).

Ground-truth bounce: the incoming (frames b-3..b-1) and outgoing (b+1..b+3) image tracks are
each fitted with a straight line in time; the bounce time is where the two lines are closest
(the ball position is continuous at contact, its velocity is not), clamped to b +- 1 frame,
falling back to the labelled frame. This removes the up-to-half-a-frame (~40 cm at 25 m/s)
quantisation of the labelled bounce frame. The image point is then back-projected to the plane
z = ball radius with the court camera.
"""
from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

from geometry import BALL_R, Camera, fit_homography, signed_out_distance

FPS = 30.0
TRAIN_GAMES = list(range(1, 8))
TEST_GAMES = [8, 9, 10]


def load_labels(data_dir: str) -> dict:
    out = {}
    for f in sorted(glob.glob(os.path.join(data_dir, "game*", "Clip*", "Label.csv"))):
        g = int(f.split(os.sep)[-3][4:])
        c = f.split(os.sep)[-2]
        d = pd.read_csv(f)
        d.columns = ["file", "vis", "x", "y", "status"]
        d["status"] = d["status"].fillna(0).astype(int)
        ok = d.vis.isin([1, 2, 3]) & d.x.notna()
        uv = np.where(ok.values[:, None], d[["x", "y"]].values.astype(float), np.nan)
        out[(g, c)] = {"uv": uv, "vis": d.vis.values, "status": d.status.values}
    return out


def merge_runs(status: np.ndarray):
    """-> list of (frame, kind) with kind 1 = hit, 2 = bounce; consecutive equal marks merged
    (the first frame of a hit run, the first frame of a bounce run)."""
    ev, prev = [], 0
    for k, s in enumerate(status):
        if s in (1, 2) and s != prev:
            ev.append((k, int(s)))
        prev = s
    return ev


def clip_camera(court_kps: np.ndarray):
    """Static-camera calibration for a clip: per-frame RANSAC homographies, reprojected
    keypoints, their per-clip median -> one homography + camera. Also returns the spread
    (median abs deviation, px) of the reprojected keypoints over the clip."""
    from geometry import COURT_KPS, apply_h
    proj = []
    for k in range(len(court_kps)):
        H, n, rms = fit_homography(court_kps[k])
        if H is not None and n >= 6 and rms < 4:
            proj.append(apply_h(H, COURT_KPS))
    if len(proj) < 5:
        return None
    proj = np.stack(proj)
    med = np.median(proj, 0)
    spread = float(np.median(np.abs(proj - med)))
    H, n, rms = fit_homography(med, thr_px=3.0)
    cam = Camera(H)
    cam_rms = cam.refine(med)
    return {"H": H, "cam": cam, "spread_px": spread, "n_frames": len(proj), "kps_rms": rms,
            "cam_rms": cam_rms, "kps_img": med}


def gt_bounce(uv: np.ndarray, b: int, nside: int = 3):
    """Sub-frame bounce time (frame units) and image point from the V-shaped image track."""
    n = len(uv)
    pre = [k for k in range(max(b - nside, 0), b) if np.isfinite(uv[k, 0])]
    post = [k for k in range(b + 1, min(b + 1 + nside, n)) if np.isfinite(uv[k, 0])]
    if len(pre) >= 2 and len(post) >= 2:
        A = np.polyfit(pre, uv[pre], 1)      # (2, 2): slope, intercept per axis
        B = np.polyfit(post, uv[post], 1)
        ds, di = A[0] - B[0], A[1] - B[1]
        if ds @ ds > 1e-9:
            t = float(np.clip(-(ds @ di) / (ds @ ds), b - 1.0, b + 1.0))
            p = 0.5 * (A[0] * t + A[1] + B[0] * t + B[1])
            return t, p, "vfit"
    if np.isfinite(uv[b, 0]):
        return float(b), uv[b].copy(), "label"
    return np.nan, np.full(2, np.nan), "none"


def build_flights(labels: dict, cams: dict) -> pd.DataFrame:
    rows = []
    for (g, c), L in labels.items():
        if (g, c) not in cams or cams[(g, c)] is None:
            continue
        cam = cams[(g, c)]["cam"]
        ev = merge_runs(L["status"])
        hits = [k for k, s in ev if s == 1]
        if not hits:
            continue
        first_hit = hits[0]
        for i, (k, s) in enumerate(ev):
            if s != 1 or i + 1 >= len(ev) or ev[i + 1][1] != 2:
                continue
            # hit run end (a hit may be marked on 2 frames): flight starts after the last hit frame
            k_end = k
            while k_end + 1 < len(L["status"]) and L["status"][k_end + 1] == 1:
                k_end += 1
            b = ev[i + 1][0]
            tb, uvb, how = gt_bounce(L["uv"], b)
            if not np.isfinite(tb):
                continue
            xyz = cam.backproject_to_z(uvb[None], BALL_R)[0]
            serve = k == first_hit
            # server side from the ball at the serve contact (approx. 2.7 m above the ground)
            uvh = L["uv"][k] if np.isfinite(L["uv"][k, 0]) else L["uv"][max(k - 1, 0)]
            hxyz = cam.backproject_to_z(uvh[None], 2.7)[0] if np.isfinite(uvh[0]) else np.full(3, np.nan)
            sx = np.sign(hxyz[0]) if np.isfinite(hxyz[0]) else 1.0
            sy = np.sign(hxyz[1]) if np.isfinite(hxyz[1]) else -np.sign(xyz[1])
            d = float(signed_out_distance(xyz[None, :2], np.array([serve]), np.array([sx]),
                                          np.array([sy]))[0])
            nvis = int(np.isfinite(L["uv"][k_end + 1:b + 1, 0]).sum())
            rows.append(dict(game=g, clip=c, hit=k, hit_end=k_end, bounce=b, tb=tb, gt_how=how,
                             u_b=uvb[0], v_b=uvb[1], x_b=xyz[0], y_b=xyz[1], serve=serve,
                             srv_sx=sx, srv_sy=sy, d_true=d, is_out=d > 0, n_vis=nvis,
                             flight_ms=1000 * (tb - k_end) / FPS,
                             split="train" if g in TRAIN_GAMES else "test"))
    return pd.DataFrame(rows)


def toss_gravity(labels: dict, cams: dict, nominal_fps: float = FPS) -> pd.DataFrame:
    """Apparent gravity of the serve toss, per clip, if the frames were `nominal_fps` apart.

    The ball before the first hit is the server's toss: nearly vertical, slow (no drag/Magnus to
    speak of). The server's spot is the ray through the ball at the serve frame, at 2.7 m height.
    Each toss frame's height is the point on the vertical line through that spot closest to
    the pixel ray. A parabola over the last 0.9 s before the hit gives the apparent g. If it is
    not 9.81, the real frame interval differs from 1/nominal_fps by sqrt(g_app / 9.81)."""
    rows = []
    for (g, c), L in labels.items():
        if cams.get((g, c)) is None:
            continue
        cam = cams[(g, c)]["cam"]
        hits = [k for k, s in merge_runs(L["status"]) if s == 1]
        if not hits:
            continue
        h, uv = hits[0], L["uv"]
        if not np.isfinite(uv[h, 0]):
            continue
        fr = np.array([k for k in range(h) if np.isfinite(uv[k, 0]) and k > h - 0.9 * nominal_fps])
        if len(fr) < 12:
            continue
        xs = cam.backproject_to_z(uv[h][None], 2.7)[0]
        if abs(xs[1]) < 9.5:          # not a serve from behind a baseline
            continue
        Kinv = np.linalg.inv(cam.K)
        z = []
        for k in fr:
            d = cam.R.T @ Kinv @ np.r_[uv[k], 1.0]
            A = np.c_[d, [0.0, 0.0, -1.0]]
            s, _ = np.linalg.lstsq(A, np.r_[xs[0], xs[1], 0.0] - cam.C, rcond=None)[0]
            z.append(cam.C[2] + s * d[2])
        p = np.polyfit(fr / nominal_fps, np.array(z), 2)
        rows.append(dict(game=g, clip=c, g_app=-2 * p[0], z_max=float(np.max(z)), y_server=xs[1], n=len(fr)))
    return pd.DataFrame(rows)
