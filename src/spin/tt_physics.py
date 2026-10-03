"""Table-tennis ball flight with spin, fitted to a monocular image track (spin-aware early call).

Physics (world frame of tt_camera: X along the table, Y away from the camera, Z up; metres, seconds):

    dv/dt = -g z  -  KD |v| v  +  KM (w x v) / (1 + 2 S),      S = R |w_perp| / |v|

  * ball: 40 mm, 2.7 g; air 1.20 kg/m^3; drag Cd = 0.45 -> KD = rho Cd A / (2 m) = 0.126 1/m
  * Magnus lift with the saturating lift curve CL = S / (1 + 2 S) (small-S slope 1, CL -> 0.5), written
    for a general spin vector: KM = rho A R / (2 m) = 5.6e-3. Spin is constant over a flight (decay is
    a few %/100 ms, well inside what a monocular fit can resolve).
  * only the spin components perpendicular to the flight produce a force, so the fitted spin has two
    components in a frame tied to the launch direction:
        w = 2 pi ( top * e_lat + side * z ),   e_lat = z x (horizontal launch direction)
    top > 0 is topspin (dips), top < 0 backspin (floats); side > 0 curves the ball to the hitter's left.

Fit (per flight, refitted online at every decision frame, warm-started): MAP estimate of
theta = (p0[3], v0[3], top, side) at the first track frame, by robust (soft-L1) least squares on the
reprojection error of every track point from the flight start to the decision frame (minus the detector
look-ahead), plus priors:
  * spin ~ N(0, 60 rps) topspin, N(0, 40 rps) sidespin
  * lateral velocity ~ N(0, (0.35 max(|vx|, 3 m/s))^2)  (shots go roughly along the table)
  * position: either an anchor from the track (a bounce just before the flight start, which puts the
    ball on the table plane, or the incoming ball's bounce on the hitter's side, which pins the racket
    contact point through a short ballistic fit of the incoming segment), or a weak prior
    Y ~ N(0, 0.6 m), Z ~ N(0.25, 0.4 m)
Uncertainty: Laplace covariance of theta (inflated by the reprojection chi^2 when > 1), propagated to the
landing point / net / end line with 2n symmetric sigma points (unscented transform).

Monocular depth: with a camera ~4 m from the side line and 13-22 deg above the table, depth (Y) moves the
image point by only sin(elevation) as much as height (Z) does. Depth is pinned mainly by the anchors and
the priors; the Laplace covariance carries what is left, and the classifier sees it (ph_*_sd features).
"""
import numpy as np

G = 9.81
R_BALL = 0.020
MASS = 0.0027
RHO = 1.20
AREA = np.pi * R_BALL ** 2
CD = 0.45
KD = 0.5 * RHO * CD * AREA / MASS
KM = 0.5 * RHO * AREA * R_BALL / MASS
FPS = 120.0
DT = 1.0 / FPS
HALF_L, HALF_W, NET_H, NET_HALF_W = 1.37, 0.7625, 0.1525, 0.7625 + 0.1525
TWO_PI = 2 * np.pi

SIGMA_PX = 2.0                  # track noise (94% of tracked frames within 5 px of the labels)
LOSS_SCALE = 1.5                # soft-L1 knee, in units of SIGMA_PX (outlier blobs are down-weighted)
PRIOR = dict(top_sd=60.0, side_sd=40.0, vy_frac=0.35, vy_min=3.0, vz_sd=6.0, vx_mu=9.0, vx_sd=9.0,
             y_mu=0.0, y_sd=0.6, z_mu=0.25, z_sd=0.4)
X_SCALE = np.array([0.05, 0.05, 0.05, 0.5, 0.5, 0.5, 10.0, 10.0])
FD_STEP = np.array([1e-4, 1e-4, 1e-4, 1e-4, 1e-4, 1e-4, 1e-2, 1e-2])
HORIZON_FRAMES = 150            # 1.25 s of extrapolation


# ---------------------------------------------------------------------------------------- dynamics
def spin_vectors(theta, nspin=2):
    """theta (B, 6|8) -> w (B, 3) rad/s (zeros without spin parameters)."""
    B = theta.shape[0]
    if theta.shape[1] < 8 or nspin == 0:
        return np.zeros((B, 3))
    vx, vy = theta[:, 3], theta[:, 4]
    h = np.hypot(vx, vy)
    h = np.where(h < 1e-6, 1.0, h)
    ex, ey = vx / h, vy / h
    top, side = theta[:, 6], theta[:, 7]
    # e_lat = z x e_h = (-ey, ex, 0)
    return TWO_PI * np.stack([-ey * top, ex * top, side], 1)


def _acc(vx, vy, vz, wx, wy, wz, w2, kd=KD, km=KM):
    sp2 = vx * vx + vy * vy + vz * vz + 1e-12
    sp = np.sqrt(sp2)
    wv = wx * vx + wy * vy + wz * vz
    wperp = np.sqrt(np.maximum(w2 - wv * wv / sp2, 0.0))
    k = km / (1.0 + (2.0 * R_BALL) * wperp / sp)
    d = kd * sp
    return (k * (wy * vz - wz * vy) - d * vx,
            k * (wz * vx - wx * vz) - d * vy,
            k * (wx * vy - wy * vx) - d * vz - G)


def _acc_nospin(vx, vy, vz, kd=KD):
    d = kd * np.sqrt(vx * vx + vy * vy + vz * vz)
    return (-d * vx, -d * vy, -d * vz - G)


def magnus(v, w, km=KM):
    """Magnus acceleration (3,) for one velocity v (3,) and spin w (3,) rad/s."""
    sp = np.linalg.norm(v) + 1e-12
    wperp = np.linalg.norm(w - (w @ v) * v / sp ** 2)
    return km * np.cross(w, v) / (1.0 + 2.0 * R_BALL * wperp / sp)


def integrate(p0, v0, w, n, h=DT, kd=KD, km=KM, sub=3):
    """RK4 with steps of `sub` frames; the frames in between come from cubic Hermite interpolation of
    position and velocity (vs. 0.8 ms steps: < 1e-6 m, < 1e-4 m/s over 1 s). p0, v0, w: (B, 3).
    Returns P, V of shape (n+1, B, 3), one sample per frame."""
    px, py, pz = (np.array(p0[:, i], float) for i in range(3))
    vx, vy, vz = (np.array(v0[:, i], float) for i in range(3))
    spin = bool(np.any(w))
    wx, wy, wz = w[:, 0], w[:, 1], w[:, 2]
    w2 = wx * wx + wy * wy + wz * wz
    acc = (lambda a, b, c: _acc(a, b, c, wx, wy, wz, w2, kd, km)) if spin else \
        (lambda a, b, c: _acc_nospin(a, b, c, kd))
    B = len(px)
    m = -(-n // sub)
    Ps = np.empty((m + 1, 3, B))
    Vs = np.empty((m + 1, 3, B))
    Ps[0] = (px, py, pz)
    Vs[0] = (vx, vy, vz)
    H = sub * h
    h2, h6 = 0.5 * H, H / 6.0
    for k in range(m):
        a1 = acc(vx, vy, vz)
        b2 = (vx + h2 * a1[0], vy + h2 * a1[1], vz + h2 * a1[2])
        a2 = acc(*b2)
        b3 = (vx + h2 * a2[0], vy + h2 * a2[1], vz + h2 * a2[2])
        a3 = acc(*b3)
        b4 = (vx + H * a3[0], vy + H * a3[1], vz + H * a3[2])
        a4 = acc(*b4)
        px = px + h6 * (vx + 2 * b2[0] + 2 * b3[0] + b4[0])
        py = py + h6 * (vy + 2 * b2[1] + 2 * b3[1] + b4[1])
        pz = pz + h6 * (vz + 2 * b2[2] + 2 * b3[2] + b4[2])
        vx = vx + h6 * (a1[0] + 2 * a2[0] + 2 * a3[0] + a4[0])
        vy = vy + h6 * (a1[1] + 2 * a2[1] + 2 * a3[1] + a4[1])
        vz = vz + h6 * (a1[2] + 2 * a2[2] + 2 * a3[2] + a4[2])
        Ps[k + 1] = (px, py, pz)
        Vs[k + 1] = (vx, vy, vz)
    if sub == 1:
        P, V = Ps, Vs
    else:
        # cubic Hermite on each step, at fractions j / sub
        P = np.empty((m * sub + 1, 3, B))
        V = np.empty((m * sub + 1, 3, B))
        P[::sub], V[::sub] = Ps, Vs
        p0_, p1_, v0_, v1_ = Ps[:-1], Ps[1:], Vs[:-1], Vs[1:]
        for j in range(1, sub):
            s = j / sub
            h00, h10, h01, h11 = 2 * s ** 3 - 3 * s ** 2 + 1, s ** 3 - 2 * s ** 2 + s, -2 * s ** 3 + 3 * s ** 2, s ** 3 - s ** 2
            P[j::sub] = h00 * p0_ + h10 * H * v0_ + h01 * p1_ + h11 * H * v1_
            d00, d10, d01, d11 = 6 * s ** 2 - 6 * s, 3 * s ** 2 - 4 * s + 1, -6 * s ** 2 + 6 * s, 3 * s ** 2 - 2 * s
            V[j::sub] = (d00 * p0_ + d01 * p1_) / H + d10 * v0_ + d11 * v1_
        P, V = P[:n + 1], V[:n + 1]
    return P.transpose(0, 2, 1), V.transpose(0, 2, 1)


# ---------------------------------------------------------------------------------------- fitting
def _unrobust(r, f=LOSS_SCALE):
    """Map a residual r to r' such that the soft-L1 loss of r' equals r^2 exactly: the robust loss is
    meant for the pixel residuals (outlier blobs), not for the priors and physical constraints."""
    r = np.asarray(r, float)
    return np.sign(r) * f * np.sqrt(np.maximum((r * r / (2 * f * f) + 1.0) ** 2 - 1.0, 0.0))


class Anchor:
    """Gaussian prior on the ball position at frame t_a (before or at the first fitted frame)."""

    def __init__(self, kind, t_a, mean, cov):
        self.kind, self.t_a = kind, float(t_a)
        self.mean = np.asarray(mean, float)
        self.cov = np.asarray(cov, float)
        L = np.linalg.cholesky(self.cov + 1e-10 * np.eye(3))
        self.W = np.linalg.inv(L)          # whitening: W (p - mean) ~ N(0, I)


class FlightProblem:
    """Reprojection + prior residuals for one flight prefix."""

    def __init__(self, cam, frames, uv, d, anchor=None, spin=True, t_s=None, prior=PRIOR):
        self.cam = cam
        self.frames = np.asarray(frames, int)
        self.uv = np.asarray(uv, float)
        self.d = float(d)
        self.t_s = int(self.frames[0] if t_s is None else t_s)
        self.idx = self.frames - self.t_s
        self.n = int(self.idx.max())
        self.anchor = anchor
        self.spin = spin
        self.npar = 8 if spin else 6
        self.prior = prior
        # visibility: a ball seen inside the table's image quadrilateral lies on a ray that meets the
        # table top behind it, so it is in front of (above) the table plane, Z >= 0
        pt = cam.backproject_z(self.uv, 0.0)
        self.vis_tab = (np.abs(pt[:, 0]) <= HALF_L) & (np.abs(pt[:, 1]) <= HALF_W) & \
            (cam.depth(pt) > 0)

    def positions(self, theta):
        """theta (B, npar) -> positions at the observed frames (B, m, 3)."""
        P, _ = integrate(theta[:, :3], theta[:, 3:6], spin_vectors(theta), self.n)
        return P[self.idx].transpose(1, 0, 2)

    def residuals(self, theta):
        """theta (B, npar) -> (B, m_res) whitened residuals."""
        pr = self.prior
        X = self.positions(theta)
        uvp = self.cam.project(X)
        r_px = ((uvp - self.uv[None]) / SIGMA_PX).reshape(len(theta), -1)
        vx, vy, vz = theta[:, 3], theta[:, 4], theta[:, 5]
        out = [r_px,
               (vy / (pr["vy_frac"] * np.maximum(np.abs(vx), pr["vy_min"])))[:, None],
               (vz / pr["vz_sd"])[:, None],
               ((self.d * vx - pr["vx_mu"]) / pr["vx_sd"])[:, None]]
        if self.spin:
            out += [(theta[:, 6] / pr["top_sd"])[:, None], (theta[:, 7] / pr["side_sd"])[:, None]]
        out += self.physical(X)
        if self.anchor is not None:
            dt = (self.t_s - self.anchor.t_a) * DT
            pa = theta[:, :3] - theta[:, 3:6] * dt           # linear back-extrapolation (<= a few frames)
            out.append((pa - self.anchor.mean) @ self.anchor.W.T)
        else:
            out += [((theta[:, 1] - pr["y_mu"]) / pr["y_sd"])[:, None],
                    ((theta[:, 2] - pr["z_mu"]) / pr["z_sd"])[:, None]]
        return np.concatenate([out[0]] + [_unrobust(r) for r in out[1:]], 1)

    def physical(self, X):
        """Hinge residuals for facts the track itself establishes (causal: observed frames only):
        no contact happens inside the window, so a ball over the table top is above it; a ball seen
        inside the table's image quadrilateral is above the table plane (else the table would hide it);
        a ball seen >= 10 cm past the net plane went over the net (or round the post, which is rare)."""
        x, y, z = X[..., 0], X[..., 1], X[..., 2]
        over = (np.abs(x) <= HALF_L - 0.02) & (np.abs(y) <= HALF_W - 0.02)
        r_tab = np.where(over, np.maximum(0.0, R_BALL - z) / 0.01, 0.0)
        r_vis = np.where(self.vis_tab[None], np.maximum(0.0, -z) / 0.01, 0.0)
        xr = self.d * x
        B, m = xr.shape
        r_net = np.zeros((B, 1))
        r_post = np.zeros((B, 1))
        seen = (xr[:, 0] < 0) & (xr[:, -1] > 0.10)
        if seen.any():
            k = np.argmax(xr >= 0, axis=1)
            k = np.clip(k, 1, m - 1)
            i = np.arange(B)
            x0, x1 = xr[i, k - 1], xr[i, k]
            f = np.clip(-x0 / np.where(x1 - x0 == 0, 1e-9, x1 - x0), 0, 1)
            yc = (1 - f) * y[i, k - 1] + f * y[i, k]
            zc = (1 - f) * z[i, k - 1] + f * z[i, k]
            inside = np.abs(yc) <= NET_HALF_W
            r_net[:, 0] = np.where(seen & inside, np.maximum(0.0, R_BALL + NET_H - zc) / 0.02, 0.0)
            r_post[:, 0] = np.where(seen, np.maximum(0.0, np.abs(yc) - NET_HALF_W) / 0.05, 0.0)
        return [r_tab, r_vis, r_net, r_post]

    @property
    def n_px(self):
        return 2 * len(self.frames)

    # -- initialisation ----------------------------------------------------------------------
    def init_theta(self, y_plane):
        """Back-project the track onto the vertical plane Y = y_plane, then fit X linear and
        Z = Z0 + vz t - g t^2 / 2 by least squares (no drag, no spin)."""
        t = self.idx * DT
        p = self.cam.backproject_y(self.uv, y_plane)
        A = np.c_[np.ones_like(t), t]
        cx = np.linalg.lstsq(A, p[:, 0], rcond=None)[0]
        cz = np.linalg.lstsq(A, p[:, 2] + 0.5 * G * t ** 2, rcond=None)[0]
        vx = cx[1]
        if self.d * vx < 1.0:
            vx = self.d * max(abs(vx), 3.0)
        th = np.array([cx[0], y_plane, cz[0], vx, 0.0, cz[1]] + ([0.0, 0.0] if self.spin else []))
        return th


class Fit:
    def __init__(self, theta, cov, cost, rms_px, n_px, ok, nfev):
        self.theta, self.cov, self.cost, self.rms_px = theta, cov, cost, rms_px
        self.n_px, self.ok, self.nfev = n_px, ok, nfev


def solve(prob, theta0, max_nfev=40):
    """Robust MAP fit from theta0 (scipy trf, soft-L1; batched finite-difference Jacobian)."""
    from scipy.optimize import least_squares
    n = prob.npar
    steps = FD_STEP[:n]
    cache = {}

    def batch(x):
        key = x.tobytes()
        if key not in cache:
            Th = np.repeat(x[None], n + 1, 0)
            Th[1:] += np.diag(steps)
            R = prob.residuals(Th)
            cache.clear()
            cache[key] = (R[0], ((R[1:] - R[0]) / steps[:, None]).T)
        return cache[key]

    try:
        sol = least_squares(lambda x: batch(x)[0], theta0, jac=lambda x: batch(x)[1], method="trf",
                            loss="soft_l1", f_scale=LOSS_SCALE, x_scale=X_SCALE[:n], max_nfev=max_nfev,
                            ftol=1e-5, xtol=1e-5, gtol=1e-6)
    except Exception:
        return None
    th = sol.x
    if not np.all(np.isfinite(th)):
        return None
    r, _ = batch(th)
    rpx = np.hypot(r[:prob.n_px:2], r[1:prob.n_px:2])          # per-point reprojection error / sigma
    inl = rpx < 3.0
    rms = float(np.sqrt(np.mean(rpx[inl] ** 2 / 2))) * SIGMA_PX if inl.any() else np.inf
    J = sol.jac
    try:
        cov = np.linalg.inv(J.T @ J + 1e-9 * np.eye(n))
    except np.linalg.LinAlgError:
        cov = np.linalg.pinv(J.T @ J)
    infl = max(1.0, (rms / SIGMA_PX) ** 2) if np.isfinite(rms) else 10.0
    f = Fit(th, cov * infl, float(sol.cost), rms, prob.n_px, bool(sol.status > 0), int(sol.nfev))
    f.out_frac = float(1.0 - inl.mean())
    return f


def fit_prefix(prob, warm=None, y_planes=(-0.35, 0.0, 0.35), fresh=True, max_nfev=40):
    """Best of a warm start and (optionally) fresh plane initialisations."""
    cands = []
    if warm is not None:
        f = solve(prob, warm, max_nfev)
        if f is not None:
            cands.append(f)
    if fresh or not cands:
        planes = [prob.anchor.mean[1]] if prob.anchor is not None else list(y_planes)
        for yp in planes:
            f = solve(prob, prob.init_theta(yp), max_nfev)
            if f is not None:
                cands.append(f)
    if not cands:
        return None
    return min(cands, key=lambda f: f.cost)


# ---------------------------------------------------------------------------------------- prediction
def _sigma_points(theta, cov):
    n = len(theta)
    c = 0.5 * (cov + cov.T)
    try:
        L = np.linalg.cholesky(c + 1e-12 * np.eye(n))
    except np.linalg.LinAlgError:
        w, U = np.linalg.eigh(c)
        L = U * np.sqrt(np.maximum(w, 0))
    S = np.sqrt(n) * L.T
    return np.vstack([theta[None], theta[None] + S, theta[None] - S])


def _first_cross(a, level, start, rising=True):
    """First fractional index >= start where a crosses `level` (upwards if rising). a: (K,)."""
    s = a[start:] - level
    if rising:
        hit = np.flatnonzero((s[:-1] < 0) & (s[1:] >= 0))
    else:
        hit = np.flatnonzero((s[:-1] > 0) & (s[1:] <= 0))
    if len(hit) == 0:
        return None
    k = hit[0]
    f = s[k] / (s[k] - s[k + 1]) if s[k] != s[k + 1] else 0.0
    return start + k + f


def _interp(P, x):
    k = int(np.floor(x))
    f = x - k
    if k + 1 >= len(P):
        return P[-1]
    return (1 - f) * P[k] + f * P[k + 1]


def outcome_of(P, n_now, d):
    """Events of one trajectory P (K, 3) after frame index n_now: net clearance, end line, landing."""
    xr = d * P[:, 0]
    out = {}
    kn = _first_cross(xr, 0.0, 0, rising=True)
    if kn is not None:
        pn = _interp(P, kn)
        out["z_net"] = pn[2] - R_BALL - NET_H
        out["net_past"] = kn <= n_now
        out["net_hit"] = (not out["net_past"]) and out["z_net"] < 0 and abs(pn[1]) < NET_HALF_W
        out["tau_net"] = max(kn - n_now, 0.0) * DT
    else:
        out.update(z_net=np.nan, net_past=bool(xr[n_now] >= 0), net_hit=False, tau_net=np.nan)
    if P[n_now, 2] <= R_BALL:
        kl = float(n_now)
    else:
        kl = _first_cross(P[:, 2], R_BALL, n_now, rising=False)
    ke = _first_cross(xr, HALF_L, n_now, rising=True) if xr[n_now] < HALF_L else float(n_now)
    if ke is not None and (kl is None or ke <= kl):
        out["z_end"] = _interp(P, ke)[2] - R_BALL
        out["tau_end"] = (ke - n_now) * DT
    else:
        out["z_end"] = -0.5
        out["tau_end"] = np.nan
    if kl is not None:
        pl = _interp(P, kl)
        out["x_land"] = d * pl[0] - HALF_L          # > 0: beyond the far end line (long)
        out["y_land"] = abs(pl[1]) - HALF_W         # > 0: outside the side line (wide)
        out["t_land"] = (kl - n_now) * DT
        out["landed"] = True
    else:
        out.update(x_land=np.nan, y_land=np.nan, t_land=np.nan, landed=False)
    # outcome class
    if out["net_hit"]:
        c = "net"
    elif not out["landed"]:
        c = "long" if xr[-1] > HALF_L else "unknown"
    elif out["x_land"] > R_BALL:
        c = "long"
    elif out["y_land"] > R_BALL:
        c = "wide"
    elif d * _interp(P, kl)[0] <= 0:
        c = "short"
    else:
        c = "in"
    out["cls"] = c
    return out


def predict(prob, fit, n_now, horizon=HORIZON_FRAMES, prefix="ph_"):
    """Features at decision index n_now (frames after t_s, the last usable track frame) from a fit."""
    th, cov = fit.theta, fit.cov
    SP = _sigma_points(th, cov)
    W = spin_vectors(SP)
    P1, V1 = integrate(SP[:, :3], SP[:, 3:6], W, n_now)
    # continue all sigma points, plus the mean state with the spin switched off (counterfactual)
    p_now = np.vstack([P1[-1], P1[-1, :1]])
    v_now = np.vstack([V1[-1], V1[-1, :1]])
    w_now = np.vstack([W, np.zeros((1, 3))])
    P2, V2 = integrate(p_now, v_now, w_now, horizon)
    B = len(SP)
    P = np.concatenate([P1[:-1], P2[:, :B]], 0)            # (K+1, B, 3)
    res = [outcome_of(P[:, b], n_now, prob.d) for b in range(B)]
    ns = outcome_of(np.concatenate([P1[:-1, :1], P2[:, B:]], 0)[:, 0], n_now, prob.d)
    m = res[0]
    d = prob.d
    pn, vn = P1[-1, 0], V1[-1, 0]
    sp = float(np.linalg.norm(vn))
    mag = magnus(vn, W[0])                                                 # Magnus acceleration now
    y_sd = float(np.sqrt(np.mean((P1[-1, 1:, 1] - pn[1]) ** 2)))
    z_sd = float(np.sqrt(np.mean((P1[-1, 1:, 2] - pn[2]) ** 2)))

    def sd(key):
        x = np.array([r[key] for r in res[1:]], float)
        x0 = m[key]
        ok = np.isfinite(x)
        if not np.isfinite(x0) or ok.sum() < 2:
            return np.nan
        return float(np.sqrt(np.mean((x[ok] - x0) ** 2)))

    cls = [r["cls"] for r in res]
    f = {
        "ok": 1.0,
        "rms_px": fit.rms_px, "out_frac": fit.out_frac, "npts": fit.n_px / 2, "nfev": fit.nfev,
        "x": d * pn[0], "y": pn[1], "z": pn[2],
        "vx": d * vn[0], "vy": vn[1], "vz": vn[2], "speed": sp,
        "y_sd": y_sd, "z_sd": z_sd,
        "x_land": m["x_land"], "y_land": m["y_land"], "t_land": m["t_land"],
        "x_land_sd": sd("x_land"), "y_land_sd": sd("y_land"),
        "z_net": m["z_net"], "z_net_sd": sd("z_net"), "net_past": float(m["net_past"]),
        "z_end": m["z_end"], "tau_end": m["tau_end"],
        "p_in": cls.count("in") / B, "p_long": cls.count("long") / B, "p_net": cls.count("net") / B,
        "p_wide": cls.count("wide") / B, "p_unknown": cls.count("unknown") / B,
        "in_mean": float(m["cls"] == "in"),
    }
    if prob.spin:
        f.update({
            "top": th[6], "side": th[7] * d,
            "top_sd": float(np.sqrt(max(cov[6, 6], 0))), "side_sd": float(np.sqrt(max(cov[7, 7], 0))),
            "top_z": th[6] / max(np.sqrt(max(cov[6, 6], 0)), 1e-6),
            "mag_z": float(mag[2]), "mag_lat": float(np.hypot(mag[0], mag[1])),
            "x_land_nospin": ns["x_land"], "spin_shift": (m["x_land"] - ns["x_land"])
            if np.isfinite(m["x_land"]) and np.isfinite(ns["x_land"]) else np.nan,
            "in_nospin": float(ns["cls"] == "in"),
        })
    return {prefix + k: (float(v) if v is not None else np.nan) for k, v in f.items()}


def empty_features(spin=True, prefix="ph_"):
    keys = ["ok", "rms_px", "out_frac", "npts", "nfev", "x", "y", "z", "vx", "vy", "vz", "speed", "y_sd", "z_sd", "x_land",
            "y_land",
            "t_land", "x_land_sd", "y_land_sd", "z_net", "z_net_sd", "net_past", "z_end", "tau_end", "p_in",
            "p_long", "p_net", "p_wide", "p_unknown", "in_mean"]
    if spin:
        keys += ["top", "side", "top_sd", "side_sd", "top_z", "mag_z", "mag_lat", "x_land_nospin",
                 "spin_shift", "in_nospin"]
    f = {prefix + k: np.nan for k in keys}
    f[prefix + "ok"] = 0.0
    return f
