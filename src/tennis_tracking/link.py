"""Offline ball track from TrackNet heatmap blobs when other, still balls lie on the court.

TrackNet's three-frame input does not suppress balls lying still on the court: they make heatmap blobs
as strong as the ball in play. BallDetector.postprocess keeps one blob per frame (the first within
80 px of its previous pick), so once it picks a still ball it can stay on it for a second or more.
This replaces that one-blob pick, offline (it uses past and future frames):

1. Still blobs. A blob is "still" if blobs lie within `still_px` of it in at least `still_min` of
   the 2*`still_win` neighbouring frames. A ball in flight moves at least about 2 px per frame at
   1280x720 even near the far baseline, so it is never near the same spot that often.
2. Tracklets. The remaining blobs are linked frame to frame (gaps up to `max_gap` frames). The match
   is the nearest blob to the constant-velocity prediction, within `gate_px` + the gap.
3. Selection. Tracklets shorter than `min_len` detections are dropped. Where tracklets overlap in
   time, the longer one is kept, so there is at most one ball per frame.

Positions stay the blob centroids (no smoothing or interpolation): a frame without a kept blob has
no ball.
"""
from __future__ import annotations

import numpy as np


def still_flags(blobs: list[np.ndarray], still_px=6.0, still_win=8, still_min=8) -> list[np.ndarray]:
    n = len(blobs)
    out = []
    for i in range(n):
        f = np.zeros(len(blobs[i]), bool)
        for j, p in enumerate(blobs[i]):
            cnt = 0
            for k in range(max(0, i - still_win), min(n, i + still_win + 1)):
                if k != i and len(blobs[k]) and (np.hypot(blobs[k][:, 0] - p[0], blobs[k][:, 1] - p[1]) < still_px).any():
                    cnt += 1
            f[j] = cnt >= still_min
        out.append(f)
    return out


def tracklets(pts: list[np.ndarray], max_gap=3, gate_px=60.0) -> list[list[tuple[int, np.ndarray]]]:
    """Greedy constant-velocity linking. pts[i] is an (m,2) array of candidate positions in frame i."""
    active, done = [], []
    for i, P in enumerate(pts):
        used = np.zeros(len(P), bool)
        for tr in sorted(active, key=len, reverse=True):
            fi, pi = tr[-1]
            gap = i - fi
            if len(tr) >= 2:
                fj, pj = tr[-2]
                v = (pi - pj) / (fi - fj)
                pred = pi + v * gap
            else:
                pred = pi
            if len(P) == 0:
                continue
            d = np.hypot(P[:, 0] - pred[0], P[:, 1] - pred[1])
            d[used] = np.inf
            j = int(np.argmin(d))
            if d[j] < gate_px + 10.0 * (gap - 1):
                tr.append((i, P[j]))
                used[j] = True
        for j in np.where(~used)[0]:
            active.append([(i, P[j])])
        still = []
        for tr in active:
            (done if i - tr[-1][0] >= max_gap else still).append(tr)
        active = still
    return done + active


def ball_track(blobs: list[np.ndarray], min_area=5, min_len=4, **kw) -> tuple[np.ndarray, dict]:
    """blobs[i]: (m,3) x, y, area for frame i. Returns (n,2) positions (NaN = none) and counts."""
    n = len(blobs)
    blobs = [b[b[:, 2] >= min_area] if len(b) else b.reshape(0, 3) for b in blobs]
    still = still_flags(blobs, **{k: v for k, v in kw.items() if k.startswith("still_")})
    moving = [b[~s, :2] for b, s in zip(blobs, still)]
    trs = tracklets(moving, **{k: v for k, v in kw.items() if k in ("max_gap", "gate_px")})
    trs = sorted([t for t in trs if len(t) >= min_len], key=len, reverse=True)
    xy = np.full((n, 2), np.nan)
    owner = np.full(n, -1)
    kept = []
    for t in trs:
        fr = [f for f, _ in t]
        if (owner[fr[0]:fr[-1] + 1] >= 0).any():
            continue
        owner[fr[0]:fr[-1] + 1] = len(kept)
        for f, p in t:
            xy[f] = p
        kept.append((fr[0], fr[-1], len(t)))
    info = {"blobs": int(sum(len(b) for b in blobs)), "still_blobs": int(sum(s.sum() for s in still)),
            "moving_blobs": int(sum(len(m) for m in moving)), "tracklets_kept": kept,
            "tracklets_dropped": int(len([t for t in trs]) - len(kept))}
    return xy, info
