"""Monocular 3D ballistic fit of a tennis-ball flight prefix, and extrapolation to the bounce.

Model (same physics family as src/hawkeye.py): gravity + quadratic drag (Cd 0.55) + a Magnus
term of unknown signed magnitude c about the horizontal axis perpendicular to the velocity
(c > 0 = topspin, < 0 = slice):  a = g - KD |v| v + c |v| (w_hat x v).
Parameters theta = (X0, V0, c) at the time of the (last) hit-labelled frame. The camera comes from
the court homography (geometry.Camera). Residuals: reprojection error / sigma_px over the prefix,
plus Gaussian priors on c and on the ball height at the hit (serve vs. rally; known in real time).
The fit is initialised by a linear (DLT-style) drag-free solve, then refined with scipy
least_squares (soft-L1 loss) and a numba finite-difference Jacobian.
"""
from __future__ import annotations

import numpy as np
from numba import njit
from scipy.optimize import least_squares

G = 9.81
M_BALL, R_BALL, RHO, CD = 0.0577, 0.0335, 1.21, 0.55
KD = 0.5 * RHO * np.pi * R_BALL ** 2 * CD / M_BALL
SUB = 4                     # RK4 substeps per video frame


@njit(cache=True)
def _acc(v, c, kd):
    sp = np.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    vh = np.sqrt(v[0] ** 2 + v[1] ** 2) + 1e-9
    wx, wy = -v[1] / vh, v[0] / vh
    # w x v with w = (wx, wy, 0)
    cx, cy, cz = wy * v[2], -wx * v[2], wx * v[1] - wy * v[0]
    a = np.empty(3)
    a[0] = -kd * sp * v[0] + c * sp * cx
    a[1] = -kd * sp * v[1] + c * sp * cy
    a[2] = -G - kd * sp * v[2] + c * sp * cz
    return a


@njit(cache=True)
def _step(p, v, c, kd, dt):
    k1v = _acc(v, c, kd)
    k1p = v
    k2v = _acc(v + 0.5 * dt * k1v, c, kd)
    k2p = v + 0.5 * dt * k1v
    k3v = _acc(v + 0.5 * dt * k2v, c, kd)
    k3p = v + 0.5 * dt * k2v
    k4v = _acc(v + dt * k3v, c, kd)
    k4p = v + dt * k3v
    return p + dt / 6 * (k1p + 2 * k2p + 2 * k3p + k4p), v + dt / 6 * (k1v + 2 * k2v + 2 * k3v + k4v)


@njit(cache=True)
def sim_frames(th, frames, kd, fps):
    """Positions at integer frame offsets `frames` (sorted, >= 0) from theta at offset 0."""
    p = th[0:3].copy()
    v = th[3:6].copy()
    c = th[6]
    dt = 1.0 / (fps * SUB)
    out = np.empty((len(frames), 3))
    k = 0
    j = 0
    while j < len(frames):
        while frames[j] * SUB > k:
            p, v = _step(p, v, c, kd, dt)
            k += 1
        out[j] = p
        j += 1
    return out


@njit(cache=True)
def landing(th, kd, t_max_frames, fps):
    """Integrate until the ball centre reaches z = R_BALL. -> (x, y, t_frames) or NaNs."""
    p = th[0:3].copy()
    v = th[3:6].copy()
    c = th[6]
    dt = 1.0 / (fps * SUB)
    res = np.full(3, np.nan)
    if p[2] <= R_BALL:
        res[0], res[1], res[2] = p[0], p[1], 0.0
        return res
    n = int(t_max_frames * SUB)
    for k in range(n):
        p2, v2 = _step(p, v, c, kd, dt)
        if p2[2] <= R_BALL:
            f = (p[2] - R_BALL) / (p[2] - p2[2])
            res[0] = p[0] + f * (p2[0] - p[0])
            res[1] = p[1] + f * (p2[1] - p[1])
            res[2] = (k + f) / SUB
            return res
        p, v = p2, v2
    return res


@njit(cache=True)
def _resid(th, frames, uv, P, kd, sig, prior_mu, prior_sd, fps):
    X = sim_frames(th, frames, kd, fps)
    n = len(frames)
    r = np.empty(2 * n + 2)
    for i in range(n):
        q0 = P[0, 0] * X[i, 0] + P[0, 1] * X[i, 1] + P[0, 2] * X[i, 2] + P[0, 3]
        q1 = P[1, 0] * X[i, 0] + P[1, 1] * X[i, 1] + P[1, 2] * X[i, 2] + P[1, 3]
        q2 = P[2, 0] * X[i, 0] + P[2, 1] * X[i, 1] + P[2, 2] * X[i, 2] + P[2, 3]
        if q2 < 1e-3:
            q2 = 1e-3
        r[2 * i] = (q0 / q2 - uv[i, 0]) / sig[i]
        r[2 * i + 1] = (q1 / q2 - uv[i, 1]) / sig[i]
    r[2 * n] = (th[6] - prior_mu[0]) / prior_sd[0]       # Magnus coefficient
    r[2 * n + 1] = (th[2] - prior_mu[1]) / prior_sd[1]   # height at the hit
    return r


@njit(cache=True)
def _jac(th, frames, uv, P, kd, sig, prior_mu, prior_sd, fps):
    r0 = _resid(th, frames, uv, P, kd, sig, prior_mu, prior_sd, fps)
    J = np.empty((len(r0), 7))
    h = np.array([1e-4, 1e-4, 1e-4, 1e-4, 1e-4, 1e-4, 1e-6])
    for j in range(7):
        t2 = th.copy()
        t2[j] += h[j]
        J[:, j] = (_resid(t2, frames, uv, P, kd, sig, prior_mu, prior_sd, fps) - r0) / h[j]
    return J


def linear_init(frames, uv, P, fps):
    """Drag- and spin-free ballistic fit, linear in (X0, V0): (p1 - u p3) . X(t) = 0."""
    t = frames / fps
    rows, rhs = [], []
    for ti, (u, v) in zip(t, uv):
        for a, w in ((P[0], u), (P[1], v)):
            l = a - w * P[2]
            rows.append(np.r_[l[:3], l[:3] * ti])
            rhs.append(-(l[3] + l[2] * (-0.5 * G * ti * ti)))
    sol, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    return sol


class Fitter:
    def __init__(self, sigma_px=2.0, c_mu=0.004, c_sd=0.006, z_rally=(1.0, 0.6),
                 z_serve=(2.7, 0.3), drag=True, loss="soft_l1", max_frames=None, hit_sigma=None):
        self.sig = sigma_px
        self.c_mu, self.c_sd = c_mu, c_sd
        self.z_rally, self.z_serve = z_rally, z_serve
        self.kd = KD if drag else 0.0
        self.loss = loss
        self.max_frames = max_frames
        self.hit_sigma = hit_sigma          # px; include the hit-frame position (offset 0) if set

    def fit(self, cam, frames, uv, serve, fps, uv_hit=None):
        """frames: int offsets (>0) from the hit frame; uv: (n,2) pixels; uv_hit: ball at the hit
        frame (offset 0) or None. -> dict or None."""
        frames = np.asarray(frames, np.int64)
        uv = np.asarray(uv, np.float64)
        if self.max_frames is not None and len(frames) > self.max_frames:
            frames, uv = frames[-self.max_frames:], uv[-self.max_frames:]
        if len(frames) < 3:
            return None
        sig = np.full(len(frames), self.sig)
        if self.hit_sigma is not None and uv_hit is not None and np.all(np.isfinite(uv_hit)):
            frames = np.r_[0, frames]
            uv = np.r_[np.asarray(uv_hit, float)[None], uv]
            sig = np.r_[self.hit_sigma, sig]
        P = cam.P
        zmu, zsd = self.z_serve if serve else self.z_rally
        pm = np.array([self.c_mu, zmu])
        ps = np.array([self.c_sd, zsd])
        x0 = linear_init(frames, uv, P, fps)
        th0 = np.r_[x0, self.c_mu]
        if not np.all(np.isfinite(th0)) or abs(th0[2]) > 20 or np.linalg.norm(th0[3:6]) > 120:
            th0 = np.r_[0.0, 0.0, zmu, 0.0, 0.0, 0.0, self.c_mu]
        args = (frames, uv, P, self.kd, sig, pm, ps, float(fps))
        try:
            res = least_squares(_resid, th0, jac=_jac, args=args, loss=self.loss, f_scale=1.0,
                                method="trf", max_nfev=80, x_scale=np.r_[1, 1, 1, 10, 10, 10, 0.005])
        except Exception:
            return None
        th = res.x
        land = landing(th, self.kd, 3.0 * fps, float(fps))
        r = res.fun[:-2].reshape(-1, 2) * sig[:, None]
        return {"theta": th, "land": land, "rms_px": float(np.sqrt(np.mean(r ** 2))), "n": len(frames)}
