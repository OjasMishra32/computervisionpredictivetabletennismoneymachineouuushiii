"""Court geometry, homography and a pinhole camera recovered from the court homography.

World frame (metres): origin at the centre of the court on the ground, x along the baselines
(to the right in the broadcast image), y along the court towards the FAR baseline, z up.
Singles sidelines at |x| = 4.115, baselines at |y| = 11.885, service lines at |y| = 6.40.
Lines are taken at the keypoints the detector returns (line intersections); the 5 cm line
width is below the resolution of anything measured here.
"""
from __future__ import annotations

import cv2
import numpy as np

HALF_LEN, SINGLES_HALF_W, DOUBLES_HALF_W, SERVICE_Y = 11.885, 4.115, 5.485, 6.40
BALL_R = 0.0335
IMG_W, IMG_H = 1280, 720

# keypoint order of yastrebksv/TennisCourtDetector (court_reference.key_points)
COURT_KPS = np.array([
    [-DOUBLES_HALF_W, HALF_LEN], [DOUBLES_HALF_W, HALF_LEN],        # far baseline, doubles corners
    [-DOUBLES_HALF_W, -HALF_LEN], [DOUBLES_HALF_W, -HALF_LEN],      # near baseline, doubles corners
    [-SINGLES_HALF_W, HALF_LEN], [-SINGLES_HALF_W, -HALF_LEN],      # left singles sideline ends
    [SINGLES_HALF_W, HALF_LEN], [SINGLES_HALF_W, -HALF_LEN],        # right singles sideline ends
    [-SINGLES_HALF_W, SERVICE_Y], [SINGLES_HALF_W, SERVICE_Y],      # far service line ends
    [-SINGLES_HALF_W, -SERVICE_Y], [SINGLES_HALF_W, -SERVICE_Y],    # near service line ends
    [0.0, SERVICE_Y], [0.0, -SERVICE_Y],                            # centre service line ends (T)
])


def fit_homography(img_pts: np.ndarray, thr_px: float = 4.0):
    """World (x, y) -> image homography from detected keypoints (NaN = missing).
    Returns (H, n_inliers, rms_px) or (None, 0, nan)."""
    ok = np.isfinite(img_pts).all(1)
    if ok.sum() < 5:
        return None, 0, np.nan
    H, mask = cv2.findHomography(COURT_KPS[ok].astype(np.float64), img_pts[ok].astype(np.float64),
                                 cv2.RANSAC, thr_px)
    if H is None:
        return None, 0, np.nan
    inl = mask.ravel().astype(bool)
    if inl.sum() >= 4:
        H, _ = cv2.findHomography(COURT_KPS[ok][inl], img_pts[ok][inl], 0)
    proj = apply_h(H, COURT_KPS[ok][inl])
    rms = float(np.sqrt(np.mean(np.sum((proj - img_pts[ok][inl]) ** 2, 1))))
    return H, int(inl.sum()), rms


def apply_h(H, pts):
    p = np.c_[pts, np.ones(len(pts))] @ H.T
    return p[:, :2] / p[:, 2:3]


class Camera:
    """Pinhole camera (square pixels, principal point at the image centre) from a ground-plane
    homography H (world x,y,0 -> image), via the two orthonormality constraints on r1, r2."""

    def __init__(self, H: np.ndarray, cx: float = IMG_W / 2, cy: float = IMG_H / 2):
        T = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1.0]])
        Hc = T @ H
        h1, h2 = Hc[:, 0], Hc[:, 1]
        A = np.array([h1[0] * h2[0] + h1[1] * h2[1], h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2])
        b = np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
        a = -(A @ b) / (A @ A)          # a = 1/f^2
        self.ok = bool(a > 0)
        f = 1.0 / np.sqrt(a) if self.ok else 1500.0
        K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]])
        M = np.linalg.inv(K) @ H
        lam = 2.0 / (np.linalg.norm(M[:, 0]) + np.linalg.norm(M[:, 1]))
        if M[2, 2] * lam < 0:            # court must be in front of the camera
            lam = -lam
        r1, r2, t = lam * M[:, 0], lam * M[:, 1], lam * M[:, 2]
        R = np.c_[r1, r2, np.cross(r1, r2)]
        U, _, Vt = np.linalg.svd(R)
        R = U @ Vt
        self._set(K, R, t)

    def _set(self, K, R, t):
        self.f, self.K, self.R, self.t = K[0, 0], K, R, t
        self.C = -R.T @ t
        self.P = K @ np.c_[R, t]

    def refine(self, img_pts: np.ndarray):
        """Refine f, R, t on the keypoints (principal point fixed, no distortion) with OpenCV's
        planar calibration, starting from the homography decomposition."""
        ok = np.isfinite(img_pts).all(1)
        obj = np.c_[COURT_KPS[ok], np.zeros(ok.sum())].astype(np.float32)
        img = img_pts[ok].astype(np.float32)
        flags = (cv2.CALIB_USE_INTRINSIC_GUESS | cv2.CALIB_FIX_PRINCIPAL_POINT | cv2.CALIB_FIX_ASPECT_RATIO
                 | cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3)
        rms, K, dist, rv, tv = cv2.calibrateCamera([obj], [img], (IMG_W, IMG_H), self.K.copy(), np.zeros(5),
                                                   flags=flags)
        R, _ = cv2.Rodrigues(rv[0])
        self._set(K, R, tv[0].ravel())
        return float(rms)

    def project(self, X: np.ndarray) -> np.ndarray:
        """(..., 3) world -> (..., 2) pixels."""
        Xh = np.concatenate([X, np.ones(X.shape[:-1] + (1,))], -1)
        p = Xh @ self.P.T
        return p[..., :2] / p[..., 2:3]

    def backproject_to_z(self, uv: np.ndarray, z: float = 0.0) -> np.ndarray:
        """(..., 2) pixels -> (..., 3) world point on the horizontal plane at height z."""
        uv1 = np.concatenate([uv, np.ones(uv.shape[:-1] + (1,))], -1)
        d = uv1 @ np.linalg.inv(self.K).T @ self.R          # ray directions in world frame
        s = (z - self.C[2]) / d[..., 2]
        return self.C + s[..., None] * d

    def reproj_rms(self, H) -> float:
        g = np.c_[COURT_KPS, np.zeros(len(COURT_KPS))]
        return float(np.sqrt(np.mean(np.sum((self.project(g) - apply_h(H, COURT_KPS)) ** 2, 1))))


def ground_xy(H: np.ndarray, cam: "Camera", uv: np.ndarray, z: float = BALL_R) -> np.ndarray:
    """(n,2) pixels -> (n,2) court point under a ball centre at height z. The ground-plane
    homography H (exact on the court, ~0.1 px keypoint rms) does the mapping; the camera only
    supplies the small shift between the z = 0 and z = BALL_R intersections (a few cm), so the
    camera's own reprojection error (up to a few px on some clips) does not leak in."""
    uv = np.atleast_2d(uv)
    p0 = apply_h(np.linalg.inv(H), uv)
    corr = cam.backproject_to_z(uv, z)[:, :2] - cam.backproject_to_z(uv, 0.0)[:, :2]
    return p0 + corr


def signed_out_distance(xy: np.ndarray, serve: np.ndarray, srv_x_sign: np.ndarray,
                        srv_y_sign: np.ndarray) -> np.ndarray:
    """Positive = out (m beyond the nearest line it crossed), negative = in (distance inside).

    Rally balls: singles court. Serves: the service box diagonally opposite the server
    (y on the receiver's half, x on the opposite side of the centre line from the server)."""
    x, y = xy[..., 0], xy[..., 1]
    d_rally = np.maximum(np.abs(x) - SINGLES_HALF_W, np.abs(y) - HALF_LEN)
    yr = -srv_y_sign * y            # > 0 on the receiver's half
    xr = -srv_x_sign * x            # > 0 on the correct side of the centre service line
    d_serve = np.maximum.reduce([-yr, yr - SERVICE_Y, -xr, xr - SINGLES_HALF_W])
    return np.where(serve, d_serve, d_rally)
