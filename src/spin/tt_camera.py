"""Metric camera for an OpenTTGames video from the table segmentation masks (table tennis, spin model).

The frozen tracker (src/tracking/common.table_geometry) takes the four table corners from the extreme
points of the pooled table mask. That is enough for its image-plane features, but a 3D physics fit
needs a metric camera, and the extreme-point corners are quantised to the 320x128 mask grid (a far edge
that is tilted by camera roll comes out level). Here we

  1. pool the table channel (R) of the segmentation masks into a probability map (as common.table_mask),
  2. find the sub-pixel 0.5 crossing of that map along every mask column (far and near edges) and every
     mask row (the two end lines), and fit the four table-top sides with a robust (Huber IRLS) line fit,
     using the frozen corners only to pick which crossings belong to which side,
  3. intersect the sides -> corners, and the plane homography H (world table plane -> image),
  4. calibrate a pinhole camera from H alone: square pixels, principal point at the image centre and
     zero skew leave one unknown intrinsic (focal length f), which the two orthonormality constraints
     on K^-1 H fix (Zhang 2000 with one plane); then (f, R, t) are refined by least squares on the four
     corners with a weak prior on f.

World frame (metres): origin at the centre of the table top, X along the table towards the image right
end, Y across the table away from the camera, Z up. Table top: |X| <= 1.37, |Y| <= 0.7625, Z = 0. Net:
X = 0, top at Z = 0.1525.

All pixel coordinates are 1920x1080 with integer coordinates at pixel centres (the convention of
detect.py / common.py).
"""
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TRACKING = os.path.join(os.path.dirname(HERE), "tracking")
for _p in (HERE, TRACKING):
    if _p not in sys.path:
        sys.path.insert(0, _p)

IMG_W, IMG_H = 1920, 1080
CX, CY = (IMG_W - 1) / 2.0, (IMG_H - 1) / 2.0
HALF_L, HALF_W = 1.37, 0.7625
NET_H = 0.1525
# far-left, far-right, near-right, near-left (the corner order of common.table_geometry)
CORNERS_W = np.array([[-HALF_L, HALF_W], [HALF_L, HALF_W], [HALF_L, -HALF_W], [-HALF_L, -HALF_W]], float)


class Camera:
    """Pinhole camera x_img ~ K (R X + t)."""

    def __init__(self, f, R, t, cx=CX, cy=CY):
        self.f, self.cx, self.cy = float(f), float(cx), float(cy)
        self.R = np.asarray(R, float)
        self.t = np.asarray(t, float).reshape(3)
        self.K = np.array([[self.f, 0, self.cx], [0, self.f, self.cy], [0, 0, 1.0]])
        self.P = self.K @ np.hstack([self.R, self.t[:, None]])
        self.C = -self.R.T @ self.t                       # camera centre in the world frame

    # -- projection --------------------------------------------------------------------------
    def project(self, X):
        """X (..., 3) world -> (..., 2) pixels."""
        X = np.asarray(X, float)
        P = self.P
        den = X[..., 0] * P[2, 0] + X[..., 1] * P[2, 1] + X[..., 2] * P[2, 2] + P[2, 3]
        u = (X[..., 0] * P[0, 0] + X[..., 1] * P[0, 1] + X[..., 2] * P[0, 2] + P[0, 3]) / den
        v = (X[..., 0] * P[1, 0] + X[..., 1] * P[1, 1] + X[..., 2] * P[1, 2] + P[1, 3]) / den
        return np.stack([u, v], -1)

    def depth(self, X):
        X = np.asarray(X, float)
        return X @ self.R[2] + self.t[2]

    def ray(self, uv):
        """Unit ray directions (..., 3) in the world frame through pixels uv (..., 2)."""
        uv = np.asarray(uv, float)
        d_cam = np.stack([(uv[..., 0] - self.cx) / self.f, (uv[..., 1] - self.cy) / self.f,
                          np.ones(uv.shape[:-1])], -1)
        d = d_cam @ self.R            # R^T d_cam, row-vector form
        return d / np.linalg.norm(d, axis=-1, keepdims=True)

    def backproject_z(self, uv, z):
        """Intersection of the pixel rays with the horizontal plane Z = z."""
        d = self.ray(uv)
        s = (z - self.C[2]) / d[..., 2]
        return self.C + s[..., None] * d

    def backproject_y(self, uv, y):
        """Intersection of the pixel rays with the vertical plane Y = y (parallel to the table length)."""
        d = self.ray(uv)
        s = (y - self.C[1]) / d[..., 1]
        return self.C + s[..., None] * d

    def to_dict(self):
        return {"f": self.f, "cx": self.cx, "cy": self.cy, "R": self.R.tolist(), "t": self.t.tolist()}

    @classmethod
    def from_dict(cls, d):
        return cls(d["f"], d["R"], d["t"], d.get("cx", CX), d.get("cy", CY))


# ---------------------------------------------------------------------------------------- masks
def pooled_table_prob(markup_dir, video, nmax=300):
    """Mean of the table channel over (a subsample of) the video's segmentation masks, (128, 320)."""
    import cv2
    fs = sorted(glob.glob(os.path.join(markup_dir, video, "segmentation_masks", "*.png")))
    if not fs:
        raise FileNotFoundError(f"no segmentation masks for {video} in {markup_dir}")
    acc, n = None, 0
    for f in fs[:: max(1, len(fs) // nmax)]:
        m = cv2.imread(f)
        if m is None:
            continue
        t = (m[..., 2] > 127).astype(np.float32)   # BGR -> R channel = table
        acc = t if acc is None else acc + t
        n += 1
    return acc / max(n, 1), n


def _crossings_1d(p, level=0.5):
    """Sub-pixel positions (in pixel-centre coordinates) where the 1-D profile p crosses `level`."""
    s = p >= level
    idx = np.flatnonzero(s[1:] != s[:-1])
    out = []
    for i in idx:
        a, b = p[i], p[i + 1]
        out.append(i + (level - a) / (b - a) if b != a else i + 0.5)
    return np.array(out, float)


def _huber_line(x, y, delta=1.5, it=20):
    """Robust fit y = a x + b (Huber IRLS, scale from the MAD)."""
    A = np.stack([x, np.ones_like(x)], 1)
    w = np.ones_like(x)
    c = np.linalg.lstsq(A, y, rcond=None)[0]
    for _ in range(it):
        r = y - A @ c
        s = max(1.4826 * np.median(np.abs(r)), 0.25)
        u = np.abs(r) / (delta * s)
        w = np.where(u <= 1, 1.0, 1.0 / np.maximum(u, 1e-9))
        c_new = np.linalg.lstsq(A * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)[0]
        if np.allclose(c_new, c, atol=1e-9):
            c = c_new
            break
        c = c_new
    r = y - A @ c
    return c, float(np.sqrt(np.mean((r[w >= 0.99]) ** 2)) if (w >= 0.99).any() else np.nan), int((w >= 0.99).sum())


def refine_corners(prob, corners0, img_w=IMG_W, img_h=IMG_H, max_shift=60.0):
    """Sub-pixel table corners from the pooled table-probability map.

    corners0: (4, 2) frozen corners (far-left, far-right, near-right, near-left) in image pixels, used
    only to decide which mask crossings belong to which side. Returns (corners (4, 2), info)."""
    H, W = prob.shape
    sx, sy = img_w / W, img_h / H
    to_img_x = lambda c: (c + 0.5) * sx - 0.5      # mask pixel-centre coordinate -> image
    to_img_y = lambda r: (r + 0.5) * sy - 0.5
    c0 = np.asarray(corners0, float)
    fl, fr, nr, nl = c0
    info = {}

    def y_on(p, q, x):
        return p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0])

    def x_on(p, q, y):
        return p[0] + (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1])

    # far (top) and near (bottom) edges: one crossing per mask column
    lines, pts = {}, {}
    for side, (p, q), pick in (("far", (fl, fr), "first"), ("near", (nl, nr), "last")):
        xs, ys = [], []
        lo, hi = p[0] + 0.12 * (q[0] - p[0]), q[0] - 0.12 * (q[0] - p[0])
        for col in range(W):
            xi = to_img_x(col)
            if not lo <= xi <= hi:
                continue
            cr = _crossings_1d(prob[:, col])
            if len(cr) == 0:
                continue
            yi = to_img_y(cr)
            yexp = y_on(p, q, xi)
            yi = yi[np.abs(yi - yexp) <= 5.0 * sy]
            if len(yi) == 0:
                continue
            xs.append(xi)
            ys.append(yi[0] if pick == "first" else yi[-1])
        pts[side] = np.c_[xs, ys] if xs else np.zeros((0, 2))
        if len(xs) >= 8:
            (a, b), rms, n = _huber_line(np.array(xs), np.array(ys))
            lines[side] = ("y", a, b)
            info[f"{side}_edge"] = dict(n=n, rms_px=round(rms, 2), slope=round(a, 5))
        else:
            a = (q[1] - p[1]) / (q[0] - p[0])
            lines[side] = ("y", a, p[1] - a * p[0])
            info[f"{side}_edge"] = "fallback (too few crossings)"
    # end lines: one crossing per mask row, x = c y + e
    for side, (p, q), pick in (("left", (fl, nl), "first"), ("right", (fr, nr), "last")):
        xs, ys = [], []
        for row in range(H):
            yi = to_img_y(row)
            # rows strictly between the far and near edges, away from the corners
            if not (p[1] + 0.15 * (q[1] - p[1]) <= yi <= q[1] - 0.15 * (q[1] - p[1])):
                continue
            cr = _crossings_1d(prob[row, :])
            if len(cr) == 0:
                continue
            xi = to_img_x(cr)
            xexp = x_on(p, q, yi)
            xi = xi[np.abs(xi - xexp) <= 5.0 * sx]
            if len(xi) == 0:
                continue
            ys.append(yi)
            xs.append(xi[0] if pick == "first" else xi[-1])
        pts[side] = np.c_[xs, ys] if xs else np.zeros((0, 2))
        if len(xs) >= 4:
            (c, e), rms, n = _huber_line(np.array(ys), np.array(xs))
            lines[side] = ("x", c, e)
            info[f"{side}_end"] = dict(n=n, rms_px=round(rms, 2))
        else:
            c = (q[0] - p[0]) / (q[1] - p[1])
            lines[side] = ("x", c, p[0] - c * p[1])
            info[f"{side}_end"] = "fallback (too few crossings)"

    def meet(ly, lx):
        # y = a x + b and x = c y + e
        _, a, b = ly
        _, c, e = lx
        y = (a * e + b) / (1 - a * c)
        return np.array([c * y + e, y])

    new = np.array([meet(lines["far"], lines["left"]), meet(lines["far"], lines["right"]),
                    meet(lines["near"], lines["right"]), meet(lines["near"], lines["left"])])
    shift = np.linalg.norm(new - c0, axis=1)
    bad = shift > max_shift
    new[bad] = c0[bad]
    info["corner_shift_px"] = np.round(shift, 1).tolist()
    info["corners_kept_from_frozen"] = bad.tolist()
    return new, info, pts


# ---------------------------------------------------------------------------------------- calibration
def homography(corners_img):
    """World table plane (X, Y) -> image, from the 4 corners (DLT, exact for 4 points)."""
    A = []
    for (X, Y), (u, v) in zip(CORNERS_W, corners_img):
        A.append([X, Y, 1, 0, 0, 0, -u * X, -u * Y, -u])
        A.append([0, 0, 0, X, Y, 1, -v * X, -v * Y, -v])
    _, _, Vt = np.linalg.svd(np.asarray(A, float))
    H = Vt[-1].reshape(3, 3)
    return H / H[2, 2]


def focal_from_h(H, cx=CX, cy=CY, f0=2000.0):
    """Closed-form focal length from one plane homography (principal point known, square pixels)."""
    h1, h2 = H[:, 0], H[:, 1]
    g1 = np.array([h1[0] - cx * h1[2], h1[1] - cy * h1[2]])
    g2 = np.array([h2[0] - cx * h2[2], h2[1] - cy * h2[2]])
    # q = (f0 / f)^2 ; equations c_i q + d_i = 0
    rows = [((g1 @ g2) / f0 ** 2, h1[2] * h2[2]),
            ((g1 @ g1 - g2 @ g2) / f0 ** 2, h1[2] ** 2 - h2[2] ** 2)]
    num = den = 0.0
    for c, d in rows:
        nrm = np.hypot(c, d) or 1.0
        c, d = c / nrm, d / nrm
        num += c * d
        den += c * c
    q = -num / den if den > 0 else -1
    return f0 / np.sqrt(q) if q > 0 else None


def pose_from_h(H, f, cx=CX, cy=CY):
    K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]])
    A = np.linalg.solve(K, H)
    lam = 2.0 / (np.linalg.norm(A[:, 0]) + np.linalg.norm(A[:, 1]))
    if (lam * A[:, 2])[2] < 0:          # the table must be in front of the camera
        lam = -lam
    r1, r2, t = lam * A[:, 0], lam * A[:, 1], lam * A[:, 2]
    R = np.stack([r1, r2, np.cross(r1, r2)], 1)
    U, _, Vt = np.linalg.svd(R)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        R = U @ np.diag([1, 1, -1]) @ Vt
    return R, t


def _rodrigues(rv):
    th = np.linalg.norm(rv)
    if th < 1e-12:
        return np.eye(3)
    k = rv / th
    Kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * Kx + (1 - np.cos(th)) * Kx @ Kx


def _rotvec(R):
    th = np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))
    if th < 1e-12:
        return np.zeros(3)
    return th / (2 * np.sin(th)) * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])


def calibrate(corners_img, f_prior=None, f_prior_sd_log=0.5):
    """-> (Camera, info). Closed-form f from H, then (log f, rotation, translation) refined on the
    corners with a weak log-normal prior on f (centred on the closed form, or f_prior if given)."""
    from scipy.optimize import least_squares
    corners_img = np.asarray(corners_img, float)
    H = homography(corners_img)
    f_lin = focal_from_h(H)
    f_init = f_lin if (f_lin is not None and 300 < f_lin < 30000) else (f_prior or 2000.0)
    f_c = f_prior or f_init
    R0, t0 = pose_from_h(H, f_init)
    Xw = np.c_[CORNERS_W, np.zeros(4)]

    def res(p):
        f = np.exp(p[0])
        cam = Camera(f, _rodrigues(p[1:4]), p[4:7])
        r = (cam.project(Xw) - corners_img).ravel()
        return np.r_[r, (p[0] - np.log(f_c)) / f_prior_sd_log]

    p0 = np.r_[np.log(f_init), _rotvec(R0), t0]
    sol = least_squares(res, p0, method="lm", max_nfev=2000)
    f = float(np.exp(sol.x[0]))
    cam = Camera(f, _rodrigues(sol.x[1:4]), sol.x[4:7])
    rep = np.linalg.norm(cam.project(Xw) - corners_img, axis=1)
    info = dict(f_closed_form=None if f_lin is None else round(float(f_lin), 1), f=round(f, 1),
                corner_reproj_px=np.round(rep, 2).tolist(),
                camera_centre_m=np.round(cam.C, 3).tolist(),
                dist_to_table_centre_m=round(float(np.linalg.norm(cam.C)), 3),
                elevation_deg=round(float(np.degrees(np.arctan2(cam.C[2], np.hypot(cam.C[0], cam.C[1])))), 2))
    if cam.C[2] <= 0 or cam.C[1] >= 0:
        info["warning"] = "camera not above / in front of the near side: check the corner order"
    return cam, info


SIDES = {"far": (0, 1), "right": (1, 2), "near": (2, 3), "left": (3, 0)}


def refine_on_edges(cam, pts, f_prior_sd_log=0.5, f_scale=3.0):
    """Model-based refinement: (log f, rotation, translation) so that the projected table-top sides pass
    through all the mask edge crossings (perpendicular distance, Huber loss, each side weighted
    equally). Straight 3D edges project to straight image lines, so this enforces the perspective
    consistency that four independent line fits do not."""
    from scipy.optimize import least_squares
    Xw = np.c_[CORNERS_W, np.zeros(4)]
    use = {s: np.asarray(p, float) for s, p in pts.items() if len(p) >= 3}
    if len(use) < 4:
        return cam, {"edge_refine": "skipped (a side has < 3 crossings)"}
    n_avg = np.mean([len(p) for p in use.values()])
    wts = {s: np.sqrt(n_avg / len(p)) / np.sqrt(len(use)) for s, p in use.items()}
    f_c = cam.f

    def res(p):
        c = Camera(np.exp(p[0]), _rodrigues(p[1:4]), p[4:7])
        q = c.project(Xw)
        out = []
        for s, P in use.items():
            a, b = q[SIDES[s][0]], q[SIDES[s][1]]
            e = b - a
            out.append(wts[s] * (e[0] * (P[:, 1] - a[1]) - e[1] * (P[:, 0] - a[0])) / np.hypot(*e))
        out.append(np.atleast_1d((p[0] - np.log(f_c)) / f_prior_sd_log))
        return np.concatenate(out)

    p0 = np.r_[np.log(cam.f), _rotvec(cam.R), cam.t]
    sol = least_squares(res, p0, loss="huber", f_scale=f_scale / np.sqrt(len(use)), max_nfev=500)
    new = Camera(np.exp(sol.x[0]), _rodrigues(sol.x[1:4]), sol.x[4:7])
    q = new.project(Xw)
    rms = {}
    for s, P in use.items():
        a, b = q[SIDES[s][0]], q[SIDES[s][1]]
        e = b - a
        d = (e[0] * (P[:, 1] - a[1]) - e[1] * (P[:, 0] - a[0])) / np.hypot(*e)
        rms[s] = round(float(np.sqrt(np.median(d ** 2))), 2)
    return new, {"edge_rms_px": rms, "f": round(new.f, 1), "corners": np.round(q, 2).tolist(),
                 "camera_centre_m": np.round(new.C, 3).tolist(),
                 "elevation_deg": round(float(np.degrees(np.arctan2(new.C[2], np.hypot(new.C[0], new.C[1])))), 2)}


# ---------------------------------------------------------------------------------------- per video
def camera_for_video(video, markup_dir, corners0, nmax=300):
    prob, n = pooled_table_prob(markup_dir, video, nmax)
    corners, rinfo, pts = refine_corners(prob, corners0)
    cam0, cinfo = calibrate(corners)
    cam, einfo = refine_on_edges(cam0, pts)
    return cam, dict(n_masks=n, corners=np.round(corners, 2).tolist(), refine=rinfo, calib=cinfo,
                     edge_fit=einfo)


def cameras_all(videos, cache, markup_dir=None, geo=None, rebuild=False):
    """{video: Camera}, cached as JSON (with the diagnostics)."""
    if os.path.exists(cache) and not rebuild:
        d = json.load(open(cache))
        if all(v in d for v in videos):
            return {v: Camera.from_dict(d[v]["camera"]) for v in videos}, d
    d = json.load(open(cache)) if os.path.exists(cache) else {}
    if geo is None or markup_dir is None:
        import common as C
        geo = geo or C.geometry_all()
        markup_dir = markup_dir or C.MARKUP
    for v in videos:
        if v in d and not rebuild:
            continue
        cam, info = camera_for_video(v, markup_dir, np.asarray(geo[v]["corners"], float))
        d[v] = dict(camera=cam.to_dict(), **info)
        e = info["edge_fit"]
        print(f"camera {v}: f={e.get('f')} C={e.get('camera_centre_m')} elev={e.get('elevation_deg')} deg, "
              f"edge rms {e.get('edge_rms_px')}, corner-only f={info['calib']['f']}", flush=True)
    os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
    json.dump(d, open(cache, "w"), indent=1)
    return {v: Camera.from_dict(d[v]["camera"]) for v in videos}, d


if __name__ == "__main__":
    import argparse
    import common as C
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", nargs="+", default=C.TRAIN)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    geo = {v: {"corners": C.table_geometry(v)["corners"]} for v in a.videos}
    cams, d = cameras_all(a.videos, a.cache or os.path.join(C.WORK, "spin_tt", "cameras.json"),
                          markup_dir=C.MARKUP, geo=geo, rebuild=a.rebuild)
    for v in a.videos:
        print(v, json.dumps({k: d[v][k] for k in ("corners", "refine", "calib", "edge_fit")}))
