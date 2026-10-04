"""Court registration for footage where the keypoint detector's labels are unreliable.

TennisCourtDetector returns 14 labelled keypoints. On broadcast-like views the labels are right
and geometry.fit_homography uses them as given. On an oblique handheld view (the Pexels rally in
results/viz/v60_assets/tennis_real/) many keypoints sit on real line intersections but carry the
wrong label, so a labelled RANSAC fit is meaningless. This module keeps the detector's keypoint
POSITIONS, drops its labels, and registers the court model in three steps:

1. Hypotheses. Every 4 detected keypoints (no 3 collinear) are matched to every ordered 4-tuple of
   model keypoints. Only proper views are kept: far baseline above the near one, +x to the right, all
   court points in front of the camera. Each hypothesis is scored by how many detected keypoints
   land within `kp_tol` px of some projected model keypoint.
2. Line check. The best keypoint hypotheses are re-ranked by a one-sided chamfer score: the mean
   distance (truncated) from points sampled along every projected court line to the nearest white
   line pixel in the frame. A wrong label assignment can match 5-6 keypoints. It cannot put all nine
   court lines on painted lines.
3. Refinement. The 8 homography parameters are fitted to the line pixels (robust least squares on
   the same truncated distance). Later frames start from the previous frame's fit and only redo the
   search when the chamfer score degrades.
"""
from __future__ import annotations

import itertools

import cv2
import numpy as np
from scipy.optimize import least_squares

from geometry import COURT_KPS, DOUBLES_HALF_W, HALF_LEN, SERVICE_Y, SINGLES_HALF_W, apply_h

# painted court lines (world metres, ground plane): baselines, sidelines, service lines, centre line
COURT_LINES = {
    "far_baseline": ((-DOUBLES_HALF_W, HALF_LEN), (DOUBLES_HALF_W, HALF_LEN)),
    "near_baseline": ((-DOUBLES_HALF_W, -HALF_LEN), (DOUBLES_HALF_W, -HALF_LEN)),
    "left_doubles": ((-DOUBLES_HALF_W, -HALF_LEN), (-DOUBLES_HALF_W, HALF_LEN)),
    "right_doubles": ((DOUBLES_HALF_W, -HALF_LEN), (DOUBLES_HALF_W, HALF_LEN)),
    "left_singles": ((-SINGLES_HALF_W, -HALF_LEN), (-SINGLES_HALF_W, HALF_LEN)),
    "right_singles": ((SINGLES_HALF_W, -HALF_LEN), (SINGLES_HALF_W, HALF_LEN)),
    "far_service": ((-SINGLES_HALF_W, SERVICE_Y), (SINGLES_HALF_W, SERVICE_Y)),
    "near_service": ((-SINGLES_HALF_W, -SERVICE_Y), (SINGLES_HALF_W, -SERVICE_Y)),
    "centre_service": ((0.0, -SERVICE_Y), (0.0, SERVICE_Y)),
}
TRUNC = 12.0


def line_samples(n_per_m: float = 3.0) -> np.ndarray:
    pts = []
    for a, b in COURT_LINES.values():
        a, b = np.array(a), np.array(b)
        n = max(2, int(np.linalg.norm(b - a) * n_per_m))
        pts.append(a + np.linspace(0, 1, n)[:, None] * (b - a))
    return np.concatenate(pts)


SAMPLES = line_samples()


def line_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """Thin bright low-saturation structures (painted lines): white-ish pixels that are brighter than
    their 15 px neighbourhood (top-hat). Players' shirts and tents pass too, but the chamfer score
    only measures model->image distances, so extra white pixels cost little."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    tophat = cv2.morphologyEx(v, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
    return ((v > 150) & (hsv[..., 1] < 80) & (tophat > 25)).astype(np.uint8)


def distance_map(mask: np.ndarray) -> np.ndarray:
    return np.minimum(cv2.distanceTransform((1 - mask).astype(np.uint8), cv2.DIST_L2, 5), TRUNC).astype(np.float32)


def _sample(dt: np.ndarray, uv: np.ndarray) -> np.ndarray:
    h, w = dt.shape
    x, y = uv[..., 0], uv[..., 1]
    inside = np.isfinite(x) & np.isfinite(y) & (x >= 0) & (x <= w - 2) & (y >= 0) & (y <= h - 2)
    xi = np.clip(np.nan_to_num(x), 0, w - 2)
    yi = np.clip(np.nan_to_num(y), 0, h - 2)
    x0, y0 = xi.astype(int), yi.astype(int)
    fx, fy = xi - x0, yi - y0
    v = (dt[y0, x0] * (1 - fx) * (1 - fy) + dt[y0, x0 + 1] * fx * (1 - fy)
         + dt[y0 + 1, x0] * (1 - fx) * fy + dt[y0 + 1, x0 + 1] * fx * fy)
    return np.where(inside, v, np.nan)


def chamfer(dt: np.ndarray, H: np.ndarray) -> tuple[float, float]:
    """(mean truncated distance over in-frame samples, share of samples in frame)."""
    v = _sample(dt, apply_h(H, SAMPLES))
    ok = np.isfinite(v)
    return (float(v[ok].mean()) if ok.any() else TRUNC), float(ok.mean())


def _basis(q):
    Q = np.concatenate([q, np.ones(q.shape[:-1] + (1,))], -1)
    M3 = np.swapaxes(Q[:, :3], 1, 2)
    lam = np.linalg.solve(M3, Q[:, 3][..., None])[..., 0]
    return M3 * lam[:, None, :]


def _h4(src, dst):
    return _basis(dst) @ np.linalg.inv(_basis(src))


def _tri(a, b, c):
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _general(q):
    return min(_tri(*q[list(t)]) for t in itertools.combinations(range(4), 3))


_MODEL_TUPLES = np.array([q for q in itertools.permutations(range(14), 4) if _general(COURT_KPS[list(q)]) > 1e-3])
_MH = np.c_[COURT_KPS, np.ones(14)]


def keypoint_hypotheses(kps: np.ndarray, kp_tol: float = 8.0, keep: int = 400):
    """Label-free 4-point hypotheses from the detected keypoint positions (NaN rows ignored).
    Returns a list of (n_inliers, H) for the `keep` best proper views."""
    P = kps[np.isfinite(kps).all(1)]
    out = []
    for ds in itertools.combinations(range(len(P)), 4):
        if _general(P[list(ds)]) < 200:
            continue
        H = _h4(COURT_KPS[_MODEL_TUPLES], np.broadcast_to(P[list(ds)], (len(_MODEL_TUPLES), 4, 2)))
        pr = np.einsum("nij,kj->nki", H, _MH)
        w = pr[..., 2]
        pr = pr[..., :2] / w[..., None]
        front = (w > 0).all(1) | (w < 0).all(1)
        far_up = (pr[:, 0, 1] + pr[:, 1, 1]) < (pr[:, 2, 1] + pr[:, 3, 1])
        x_right = (pr[:, 1, 0] > pr[:, 0, 0]) & (pr[:, 3, 0] > pr[:, 2, 0])
        dmin = np.linalg.norm(pr[:, None] - P[None, :, None], axis=-1).min(2)
        inl = np.where(front & far_up & x_right, (dmin < kp_tol).sum(1), 0)
        top = np.argsort(-inl)[:50]
        out += [(int(inl[j]), H[j]) for j in top if inl[j] >= 5]
    out.sort(key=lambda t: -t[0])
    return out[:keep]


def refine(dt: np.ndarray, H0: np.ndarray) -> np.ndarray:
    """Fit the 8 homography parameters to the line pixels (soft-L1 on truncated distances)."""
    H0 = H0 / H0[2, 2]
    S = np.diag([1 / 100.0, 1 / 100.0, 1.0])     # condition: world metres -> ~0.1 units

    def res(p):
        H = np.append(p, 1.0).reshape(3, 3) @ np.linalg.inv(S)
        v = _sample(dt, apply_h(H, SAMPLES))
        return np.where(np.isfinite(v), v, TRUNC)

    G0 = H0 @ S
    G0 = G0 / G0[2, 2]
    r = least_squares(res, G0.ravel()[:8], loss="soft_l1", f_scale=3.0, x_scale="jac", max_nfev=200)
    H = np.append(r.x, 1.0).reshape(3, 3) @ np.linalg.inv(S)
    return H / H[2, 2]


def register(frame_bgr: np.ndarray, kps: np.ndarray, H_prev: np.ndarray | None = None,
             redo_above: float = 2.5):
    """Court homography (world x,y -> image px) for one frame. Returns (H, info)."""
    dt = distance_map(line_mask(frame_bgr))
    info = {"searched": False}
    if H_prev is not None:
        H = refine(dt, H_prev)
        c, cov = chamfer(dt, H)
        if c <= redo_above:
            info.update(chamfer_px=c, in_frame=cov, n_hyp=0)
            return H, info
    hyps = keypoint_hypotheses(kps)
    info["searched"] = True
    info["n_hyp"] = len(hyps)
    if not hyps:
        return None, info
    scored = sorted(((chamfer(dt, H)[0], n, H) for n, H in hyps), key=lambda t: t[0])
    best = None
    for c0, n, H in scored[:8]:
        Hr = refine(dt, H)
        c, cov = chamfer(dt, Hr)
        if cov > 0.6 and (best is None or c < best[0]):
            best = (c, cov, n, Hr)
    if best is None:
        return None, info
    info.update(chamfer_px=best[0], in_frame=best[1], kp_inliers=best[2])
    return best[3], info
