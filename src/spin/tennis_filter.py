"""Spin-aware tennis ball-flight estimation: batch physics fit and a recursive unscented filter.

Both estimate the full flight state  y = [p(3), v(3), w(3), c, lam, wind_x, wind_y]
(position, velocity, spin vector in rad/s, drag scale Cd/0.55, spin decay rate 1/s, horizontal
wind m/s) under the physics in src/spin/physics.py, then push the estimate and its covariance
to the ground (z = ball radius) to get a landing distribution and P(out).

Methods
  bls       batch nonlinear least squares from contact (frame 0) to the decision frame.
            Unknowns p0, v0, w0 and (est_cd) c, (est_decay) lam, (est_wind) wind_xy.
            Levenberg-Marquardt, forward-difference Jacobians, Gaussian priors on the
            physical parameters (w: 0 +- 400 rad/s per axis, c: 1 +- 0.10, lam: 0 +- 0.3 /s,
            wind: 0 +- 3 m/s). The spin component along v is unobservable and stays at its prior.
            Posterior covariance = inverse Gauss-Newton Hessian x max(1, reduced chi^2).
  ukf       per-frame cubature/unscented Kalman filter on the same state, with random-walk
            process noise on v (unmodelled acceleration), w, c (and lam, wind when estimated).
  baseline  src/hawkeye.py's predictor (local quadratic over 150 ms, spin backed out of the
            acceleration), re-implemented here only to also return its implied spin.

Landing: cubature transform of the decision-time state through RK4 (2 ms steps) to z = R,
giving the landing mean and 2x2 covariance; P(out) by Monte Carlo over that Gaussian with
common random numbers. Court geometry and signed distance come from src/hawkeye.py.

Vectorised across shots; arrays of physical states are component-major (dims, N).
"""
from __future__ import annotations

import numpy as np

from src import hawkeye as H
from src.spin import physics as P

R, FPS, NOISE = P.R, P.FPS, P.NOISE
DT = 1.0 / FPS
NY = 13  # [p0 p1 p2 v0 v1 v2 w0 w1 w2 c lam wx wy]
I_C, I_LAM, I_WX, I_WY = 9, 10, 11, 12
PRIOR_MEAN = np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 1.0, 0.0, 0.0, 0.0])
PRIOR_SD = np.array([np.inf] * 6 + [400.0] * 3 + [0.10, 0.30, 3.0, 3.0])
FD_STEP = np.array([1e-5] * 6 + [1e-2] * 3 + [1e-5, 1e-4, 1e-4, 1e-4])


def active_dims(est_cd=True, est_decay=False, est_wind=False) -> np.ndarray:
    a = list(range(9))
    if est_cd:
        a.append(I_C)
    if est_decay:
        a.append(I_LAM)
    if est_wind:
        a += [I_WX, I_WY]
    return np.array(a)


def _split(Y: np.ndarray):
    """Y (13, N) -> x (9, N), c, lam, wind (3, N)."""
    wind = np.stack([Y[I_WX], Y[I_WY], np.zeros(Y.shape[1])])
    return Y[0:9], Y[I_C], Y[I_LAM], wind


def _psd_sqrt(C: np.ndarray) -> np.ndarray:
    """Batched matrix square root L with L L^T = C for symmetric PSD C (..., d, d)."""
    C = 0.5 * (C + np.swapaxes(C, -1, -2))
    try:
        d = C.shape[-1]
        scale = np.maximum(np.einsum("...ii->...i", C).max(-1), 1e-300)[..., None, None]
        return np.linalg.cholesky(C + 1e-13 * scale * np.eye(d))
    except np.linalg.LinAlgError:
        lam, V = np.linalg.eigh(C)
        return V * np.sqrt(np.maximum(lam, 0.0))[..., None, :]


# ------------------------------------------------------------------ propagation to the ground

def fly_to_ground(Y: np.ndarray, h: float = 2e-3, tmax: float = 2.0):
    """Integrate states Y (13, N) until z <= R. Returns landing (N, 3), time to land (N,),
    landing velocity (N, 3). A state already at or below R is extrapolated linearly."""
    x, c, lam, wind = _split(Y)
    x = x.copy()
    N = x.shape[1]
    land = np.full((N, 3), np.nan)
    vland = np.full((N, 3), np.nan)
    tl = np.full(N, np.nan)
    below = x[2] <= R
    if below.any():
        f = (x[2, below] - R) / np.minimum(x[5, below], -1e-3)
        land[below] = (x[0:3, below] - f * x[3:6, below]).T
        vland[below] = x[3:6, below].T
        tl[below] = -f
    alive = ~below
    t = 0.0
    while alive.any() and t < tmax:
        ia = np.flatnonzero(alive)
        xa = x[:, ia]
        nx = P.rk4(xa, h, c[ia], lam[ia], wind[:, ia])
        hit = nx[2] <= R
        if hit.any():
            f = (xa[2, hit] - R) / (xa[2, hit] - nx[2, hit])
            land[ia[hit]] = (xa[0:3, hit] + f * (nx[0:3, hit] - xa[0:3, hit])).T
            vland[ia[hit]] = (xa[3:6, hit] + f * (nx[3:6, hit] - xa[3:6, hit])).T
            tl[ia[hit]] = t + f * h
            alive[ia[hit]] = False
        x[:, ia] = nx
        t += h
    return land, tl, vland


def landing_distribution(ymean: np.ndarray, ycov: np.ndarray, active: np.ndarray, q_a: float = 0.0):
    """Cubature transform of the decision-time state to the landing point.

    ymean (n, 13), ycov (n, 13, 13); only `active` dims are uncertain. q_a (m^2/s^3) adds the
    filter's white-noise-acceleration model over the remaining flight time.
    Returns dict: land (n, 3) from the mean state, cov (n, 2, 2) in (x, y), t_go (n,)."""
    n = len(ymean)
    Da = len(active)
    L = _psd_sqrt(ycov[:, active[:, None], active[None, :]]) * np.sqrt(Da)   # (n, Da, Da)
    pts = np.repeat(ymean[None], 2 * Da + 1, 0)                               # (2Da+1, n, 13)
    for j in range(Da):
        pts[1 + j][:, active] += L[:, :, j]
        pts[1 + Da + j][:, active] -= L[:, :, j]
    land, tl, vl = fly_to_ground(pts.reshape(-1, NY).T)
    land = land.reshape(2 * Da + 1, n, 3)
    xy = land[1:, :, :2]
    mu = xy.mean(0)
    dev = xy - mu
    cov = np.einsum("kni,knj->nij", dev, dev) / (2 * Da)
    tgo = tl.reshape(2 * Da + 1, n)[0]
    if q_a > 0:
        v0 = vl.reshape(2 * Da + 1, n, 3)[0]
        s = v0[:, :2] / np.minimum(v0[:, 2:3], -1e-3)                          # dx/dz at landing
        cov = cov + (q_a * tgo**3 / 3)[:, None, None] * (np.eye(2) + s[:, :, None] * s[:, None, :])
    return {"land": land[0], "cov": cov, "t_go": tgo}


_EPS = None


def p_out(land: np.ndarray, cov: np.ndarray, serve: np.ndarray, m: int = 4000, chunk: int = 512):
    """P(signed out distance > 0) for a Gaussian landing (mean land[:, :2], cov (n, 2, 2))."""
    global _EPS
    if _EPS is None or len(_EPS) != m:
        e = np.random.default_rng(12345).standard_normal((m // 2, 2))
        _EPS = np.concatenate([e, -e])
    L = _psd_sqrt(cov)
    out = np.empty(len(land))
    for a in range(0, len(land), chunk):
        b = slice(a, a + chunk)
        pts = land[b, None, :2] + np.einsum("nij,mj->nmi", L[b], _EPS)
        x, y = pts[..., 0], pts[..., 1]
        sv = serve[b, None]
        d_long = np.where(sv, y - (H.NET_Y + 6.40), y - H.BASELINE)
        d_side = np.where(sv, np.maximum(x - H.SIDELINE, -x), np.abs(x) - H.SIDELINE)
        out[b] = (np.maximum(d_long, d_side) > 0).mean(1)
    return out


def sd_signed_distance(land: np.ndarray, cov: np.ndarray, serve: np.ndarray) -> np.ndarray:
    """1-sigma of the signed out distance, linearised at the nearest line."""
    x, y = land[:, 0], land[:, 1]
    d_long = np.where(serve, y - (H.NET_Y + 6.40), y - H.BASELINE)
    d_side = np.where(serve, np.maximum(x - H.SIDELINE, -x), np.abs(x) - H.SIDELINE)
    g = np.where((d_long >= d_side)[:, None], np.array([[0.0, 1.0]]),
                 np.stack([np.sign(x), np.zeros_like(x)], 1))
    return np.sqrt(np.einsum("ni,nij,nj->n", g, cov, g))


# ------------------------------------------------------------------ baseline (src/hawkeye.py)

def baseline_predict(win: np.ndarray):
    """hawkeye.predict_landing plus the spin it implies. win (n, W, 3).
    Returns land (n, 3), spin vector (n, 3) rad/s, v_now (n, 3)."""
    W = win.shape[1]
    tt = np.arange(-W + 1, 1) / FPS
    X = np.stack([np.ones_like(tt), tt, 0.5 * tt**2], 1)
    coef = np.einsum("jw,nwc->njc", np.linalg.pinv(X), win)
    p_now, v_now, a_now = coef[:, 0], coef[:, 1], coef[:, 2]
    sp = np.linalg.norm(v_now, axis=1, keepdims=True)
    a_mag = a_now - H.G + H.KD * sp * v_now
    a_perp = a_mag - (np.sum(a_mag * v_now, 1, keepdims=True) / sp**2) * v_now
    w_est = np.cross(v_now, a_perp)
    w_est /= np.maximum(np.linalg.norm(w_est, axis=1, keepdims=True), 1e-9)
    cmag = np.linalg.norm(a_perp, axis=1) / np.maximum(sp[:, 0] ** 2, 1e-9)
    land_hat, _, _ = H._integrate(p_now, v_now, lambda v, a: H._accel_pred(v, w_est[a], cmag[a]))
    CL = np.clip(cmag / H.KL, 0.0, 0.49)            # invert CL = 1/(2 + 1/S)
    S = CL / (1 - 2 * CL)
    spin = (S * sp[:, 0] / R)[:, None] * w_est
    return land_hat, spin, v_now


# ------------------------------------------------------------------ batch nonlinear least squares

def _init_theta(meas: np.ndarray, kmax: np.ndarray, nfit: int = 50) -> np.ndarray:
    """Start values at contact (frame 0): quadratic fit to the first ~150 ms, spin backed out of
    the residual acceleration as in the hawkeye predictor."""
    n = len(meas)
    th = np.tile(PRIOR_MEAN, (n, 1))
    for i in range(n):
        k = min(int(kmax[i]), nfit)
        z = meas[i, : k + 1]
        ok = np.isfinite(z[:, 0])
        t = np.arange(k + 1)[ok] / FPS
        X = np.stack([np.ones_like(t), t, 0.5 * t**2], 1)
        coef = np.linalg.lstsq(X, z[ok], rcond=None)[0]
        th[i, 0:3], th[i, 3:6] = coef[0], coef[1]
        a = coef[2]
        v = coef[1]
        sp = np.linalg.norm(v)
        am = a - H.G + H.KD * sp * v
        ap = am - (am @ v) / sp**2 * v
        w_hat = np.cross(v, ap)
        w_hat /= max(np.linalg.norm(w_hat), 1e-9)
        CL = np.clip(np.linalg.norm(ap) / (H.KL * sp**2), 0.0, 0.45)
        th[i, 6:9] = CL / (1 - 2 * CL) * sp / R * w_hat
    return th


def _bls_pass(theta, act, measT, valid, kmax, jac: bool, record: bool):
    """One integration from contact over all frames <= kmax.
    measT (K, 3, n), valid (K, n). Returns cost_data (n,), nobs (n,), and if jac the normal
    equations JtJ (n, P, P), Jtr (n, P); if record the decision-frame state (n, 13) and its
    sensitivity to theta (n, 13, P)."""
    n, Pn = theta.shape[0], len(act)
    M = 1 + (Pn if jac else 0)
    Th = np.repeat(theta[None], M, 0)
    if jac:
        for q, j in enumerate(act):
            Th[1 + q, :, j] += FD_STEP[j]
    Y = Th.reshape(-1, NY).T.copy()
    x, c, lam, wind = _split(Y)
    x = x.copy()
    cost = np.zeros(n)
    nobs = np.zeros(n)
    JtJ = np.zeros((Pn, Pn, n)) if jac else None
    Jtr = np.zeros((Pn, n)) if jac else None
    ydec = np.zeros((NY, n)) if record else None
    Phi = np.zeros((NY, Pn, n)) if record else None
    step = FD_STEP[act][:, None]
    for j in range(int(kmax.max()) + 1):
        if j > 0:
            x = P.rk4(x, DT, c, lam, wind)
        m = (j <= kmax) & valid[j]
        pb = x[0:3, :n]
        if m.any():
            r = np.where(m, measT[j] - pb, 0.0)
            cost += (r * r).sum(0)
            nobs += 3 * m
            if jac:
                Jq = (x[0:3, n:].reshape(3, Pn, n) - pb[:, None, :]) / step * m
                JtJ += np.einsum("kpn,kqn->pqn", Jq, Jq)
                Jtr += np.einsum("kpn,kn->pn", Jq, r)
        if record:
            hit = kmax == j
            if hit.any():
                ydec[0:9, hit] = x[:, :n][:, hit]
                ydec[9:, hit] = theta[hit, 9:].T
                if jac:
                    Phi[0:9, :, hit] = ((x[:, n:].reshape(9, Pn, n) - x[:, None, :n]) / step)[:, :, hit]
    out = {"cost": cost, "nobs": nobs}
    if jac:
        out["JtJ"], out["Jtr"] = np.moveaxis(JtJ, -1, 0), Jtr.T
    if record:
        for q, j in enumerate(act):
            if j >= 9:
                Phi[j, q] = 1.0
        out["ydec"], out["Phi"] = ydec.T, np.moveaxis(Phi, -1, 0)
    return out


def bls_fit(meas: np.ndarray, kmax: np.ndarray, est_cd=True, est_decay=False, est_wind=False,
            theta0=None, sigma: float = NOISE, max_iter: int = 15, tol: float = 1e-2, verbose=False,
            fixed: np.ndarray | None = None, prior_sd: np.ndarray | None = None, mu0: float = 1e-4):
    """Batch MAP fit of the full flight from contact (frame 0) to frame kmax (per shot).

    meas (n, K, 3) with NaN for missing frames. Parameters not estimated are held at
    `fixed[:, j]` (n, 13) if given, else at the prior mean (c = 1, lam = 0, wind = 0).
    Stops when every shot's Newton decrement (chi^2 a further Gauss-Newton step would remove)
    is below tol. Returns dict with theta (n, 13), cov_theta (n, P, P), y (n, 13) state at kmax
    and its covariance ycov (n, 13, 13), chi2r, iters."""
    n = len(meas)
    act = active_dims(est_cd, est_decay, est_wind)
    Pn = len(act)
    measT = np.ascontiguousarray(np.moveaxis(meas, 0, -1))      # (K, 3, n)
    valid = np.isfinite(measT[:, 0, :])
    measT = np.nan_to_num(measT)
    theta = (_init_theta(meas, kmax) if theta0 is None else theta0.copy())
    inact = np.setdiff1d(np.arange(NY), act)
    theta[:, inact] = PRIOR_MEAN[inact] if fixed is None else fixed[:, inact]
    pm, psd = PRIOR_MEAN[act], (PRIOR_SD if prior_sd is None else prior_sd)[act]
    prec = np.where(np.isfinite(psd), 1.0 / psd**2, 0.0)

    def total(cost_d, th):
        return cost_d / sigma**2 + ((th[:, act] - pm) ** 2 * prec).sum(1)

    mu = np.full(n, mu0)
    it = 0
    for it in range(1, max_iter + 1):
        o = _bls_pass(theta, act, measT, valid, kmax, jac=True, record=False)
        Hn = o["JtJ"] / sigma**2 + (prec * np.eye(Pn))[None]
        g = o["Jtr"] / sigma**2 + (pm - theta[:, act]) * prec
        f0 = total(o["cost"], theta)
        dH = np.einsum("npp->np", Hn)
        # Newton decrement g' H^-1 g: the cost reduction a full Gauss-Newton step would buy
        dec = np.einsum("np,np->n", g, np.linalg.solve(Hn, g[..., None])[..., 0])
        if it > 1 and (dec < tol).all():
            break
        A = Hn + (mu[:, None] * dH)[:, :, None] * np.eye(Pn)[None]
        delta = np.linalg.solve(A, g[..., None])[..., 0]
        cand = theta.copy()
        cand[:, act] += delta
        f1 = total(_bls_pass(cand, act, measT, valid, kmax, jac=False, record=False)["cost"], cand)
        acc = f1 <= f0
        theta[acc] = cand[acc]
        mu = np.where(acc, np.maximum(mu * 0.3, 1e-12), mu * 10)
        if verbose:
            print(f"  bls iter {it}: median cost {np.median(np.minimum(f0, f1)):.1f}, "
                  f"accepted {acc.mean():.3f}, max decrement {dec.max():.2e}", flush=True)
    o = _bls_pass(theta, act, measT, valid, kmax, jac=True, record=True)
    Hn = o["JtJ"] / sigma**2 + (prec * np.eye(Pn))[None]
    chi2r = (o["cost"] / sigma**2) / np.maximum(o["nobs"] - Pn, 1)
    cov_th = np.linalg.inv(Hn) * np.maximum(chi2r, 1.0)[:, None, None]
    Phi = o["Phi"]
    ycov = Phi @ cov_th @ np.swapaxes(Phi, 1, 2)
    return {"theta": theta, "cov_theta": cov_th, "y": o["ydec"], "ycov": ycov, "chi2r": chi2r,
            "iters": it, "active": act, "rss": o["cost"], "nobs": o["nobs"], "JtJ": o["JtJ"]}


def log_evidence(fit: dict, sigma_hat: np.ndarray) -> np.ndarray:
    """Laplace log marginal likelihood of a bls_fit result (up to a constant shared by all
    models), with the noise level fixed at sigma_hat (n,) for every model so they compare
    on the same scale. Parameters with flat priors (p0, v0) are shared by all models."""
    act = fit["active"]
    pm, psd = PRIOR_MEAN[act], PRIOR_SD[act]
    fin = np.isfinite(psd)
    prec = np.where(fin, 1.0 / psd**2, 0.0)
    s2 = sigma_hat[:, None, None] ** 2
    Hn = fit["JtJ"] / s2 + (prec * np.eye(len(act)))[None]
    f = fit["rss"] / sigma_hat**2 + ((fit["theta"][:, act] - pm) ** 2 * prec).sum(1)
    return -0.5 * f - 0.5 * np.linalg.slogdet(Hn)[1] + 0.5 * np.log(prec[fin]).sum()


# ------------------------------------------------------------------ shared environment (session calibration)

ENV = np.array([I_LAM, I_WX, I_WY])


def calibrate_environment(meas: np.ndarray, kmax: np.ndarray, theta0: np.ndarray | None = None,
                          sigma: float = NOISE, n_outer: int = 3, verbose: bool = False):
    """Joint fit of the parameters every shot shares (spin decay rate, horizontal wind) with each
    shot's own p0, v0, w0, Cd, from complete flights.

    A single flight cannot separate a crosswind from a little sidespin (both push sideways about
    in proportion to speed), so per-shot estimates are prior-dominated. Shared across shots,
    the environment is identified: per-shot sidespin averages out, wind does not. This is
    Gauss-Newton on the joint problem, done by Schur complements: refit every shot with the
    environment fixed, reduce each shot's normal equations onto the 3 shared parameters, sum
    and step. Flat priors on the shared parameters; shots with reduced chi^2 > 3x the median
    are left out. Returns env (3,) = [lam, wind_x, wind_y], its covariance (3, 3), theta."""
    n = len(meas)
    env = np.zeros(3)
    theta = theta0
    act = active_dims(True, True, True)
    measT = np.nan_to_num(np.ascontiguousarray(np.moveaxis(meas, 0, -1)))
    valid = np.isfinite(np.moveaxis(meas, 0, -1)[:, 0, :])
    psd = PRIOR_SD.copy()
    psd[ENV] = np.inf
    prec = np.where(np.isfinite(psd), 1.0 / psd**2, 0.0)
    E, T = ENV, np.setdiff1d(act, ENV)
    for it in range(n_outer):
        fixed = np.tile(PRIOR_MEAN, (n, 1))
        fixed[:, ENV] = env
        fit = bls_fit(meas, kmax, theta0=theta, fixed=fixed, sigma=sigma)
        theta = fit["theta"]
        o = _bls_pass(theta, act, measT, valid, kmax, jac=True, record=False)
        Hn = o["JtJ"] / sigma**2 + (prec * np.eye(len(act)))[None]
        g = o["Jtr"] / sigma**2 + (PRIOR_MEAN - theta) * prec
        HTT_inv_HTE = np.linalg.solve(Hn[:, T[:, None], T[None, :]], Hn[:, T[:, None], E[None, :]])
        HTT_inv_gT = np.linalg.solve(Hn[:, T[:, None], T[None, :]], g[:, T, None])[..., 0]
        S = Hn[:, E[:, None], E[None, :]] - np.einsum("nte,ntf->nef", Hn[:, T[:, None], E[None, :]], HTT_inv_HTE)
        r = g[:, E] - np.einsum("nte,nt->ne", Hn[:, T[:, None], E[None, :]], HTT_inv_gT)
        ok = fit["chi2r"] < 3 * np.median(fit["chi2r"])
        Ssum = S[ok].sum(0)
        step = np.linalg.solve(Ssum, r[ok].sum(0))
        env = env + step
        if verbose:
            print(f"  env iter {it + 1}: lam {env[0]:.4f} wind ({env[1]:.3f}, {env[2]:.3f}) step {step}", flush=True)
    cov = np.linalg.inv(Ssum) * max(float(np.median(fit["chi2r"])), 1.0)
    return env, cov, theta


# ------------------------------------------------------------------ recursive filter (UKF)

UKF_DEFAULT = {"q_a": 1e-3, "q_w": 10.0, "q_c": 1e-5, "q_lam": 1e-4, "q_wind": 1e-3}


def ukf_run(meas: np.ndarray, record: dict, est_cd=True, est_decay=False, est_wind=False,
            sigma: float = NOISE, q: dict | None = None, init: str = "bls", j0: int | None = None,
            fixed: np.ndarray | None = None):
    """Cubature (unscented, kappa = 0) Kalman filter, one predict/update per frame.

    record: {key: frame index per shot (n,)}; the filtered mean (n, 13) and covariance
    (n, 13, 13) after the update at that frame are returned under the same key, with the
    running innovation statistics (sum of NIS, sum of log det S, count) used to weigh models.
    init='bls' starts the filter from a batch fit of frames 0..j0 (default 40, about 120 ms;
    this is what removes the start-up linearisation loss of a cold-started filter);
    init='poly' starts from a quadratic fit of frames 0..j0 (default 10) with the spin prior.
    fixed (n, 13): values for the parameters that are not estimated (e.g. a session-calibrated
    spin decay rate and wind), as in bls_fit.
    Process noise (continuous-time PSDs): q_a on velocity (white acceleration, m^2/s^3),
    q_w on spin (rad^2/s^3), q_c on drag scale, q_lam on decay, q_wind on wind."""
    q = {**UKF_DEFAULT, **(q or {})}
    n, K, _ = meas.shape
    act = active_dims(est_cd, est_decay, est_wind)
    Da = len(act)
    if init == "bls":
        j0 = 40 if j0 is None else j0
        b = bls_fit(meas, np.full(n, j0), est_cd, est_decay, est_wind, sigma=sigma, fixed=fixed)
        y, C = b["y"].copy(), b["ycov"].copy()
    else:
        j0 = 10 if j0 is None else j0
        t = (np.arange(j0 + 1) - j0) / FPS
        X = np.stack([np.ones_like(t), t, 0.5 * t**2], 1)
        z0 = meas[:, : j0 + 1]
        if not np.isfinite(z0).all():
            raise ValueError("missing frames in the initialisation window")
        coef = np.einsum("jw,nwc->njc", np.linalg.pinv(X), z0)
        y = np.tile(PRIOR_MEAN, (n, 1)) if fixed is None else fixed.copy()
        y[:, 0:3], y[:, 3:6] = coef[:, 0], coef[:, 1]
        y[:, 6:9] = 0.0
        if est_cd:
            y[:, I_C] = PRIOR_MEAN[I_C]
        covX = np.linalg.inv(X.T @ X) * sigma**2
        C = np.zeros((n, NY, NY))
        for k in range(3):
            C[:, k, k] = covX[0, 0] * 4
            C[:, 3 + k, 3 + k] = covX[1, 1] * 4
            C[:, k, 3 + k] = C[:, 3 + k, k] = covX[0, 1] * 4
        for j in range(6, NY):
            C[:, j, j] = PRIOR_SD[j] ** 2 if j in act else 0.0
    # discrete process noise for one frame
    Qd = np.zeros((NY, NY))
    for k in range(3):
        Qd[k, k] = q["q_a"] * DT**3 / 3
        Qd[3 + k, 3 + k] = q["q_a"] * DT
        Qd[k, 3 + k] = Qd[3 + k, k] = q["q_a"] * DT**2 / 2
        Qd[6 + k, 6 + k] = q["q_w"] * DT
    Qd[I_C, I_C] = q["q_c"] * DT
    Qd[I_LAM, I_LAM] = q["q_lam"] * DT
    Qd[I_WX, I_WX] = Qd[I_WY, I_WY] = q["q_wind"] * DT
    inact = np.setdiff1d(np.arange(NY), act)
    Qd[inact, :] = 0
    Qd[:, inact] = 0
    Rm = sigma**2 * np.eye(3)
    jlast = max(int(np.max(v)) for v in record.values())
    out = {key: {"y": np.zeros((n, NY)), "ycov": np.zeros((n, NY, NY)), "nis": np.zeros(n),
                 "ldet": np.zeros(n), "cnt": np.zeros(n)} for key in record}
    nis, ldet, cnt = np.zeros(n), np.zeros(n), np.zeros(n)
    a_idx = act
    for j in range(j0 + 1, jlast + 1):
        # predict: cubature points through one RK4 frame step
        L = _psd_sqrt(C[:, a_idx[:, None], a_idx[None, :]]) * np.sqrt(Da)   # (n, Da, Da)
        pts = np.repeat(y[None], 2 * Da, 0)
        for k in range(Da):
            pts[k][:, a_idx] += L[:, :, k]
            pts[Da + k][:, a_idx] -= L[:, :, k]
        Y = pts.reshape(-1, NY).T
        x, c, lam, wind = _split(Y)
        Y[0:9] = P.rk4(x, DT, c, lam, wind)
        pts = Y.T.reshape(2 * Da, n, NY)
        y = pts.mean(0)
        dev = pts - y
        C = np.einsum("kni,knj->nij", dev, dev) / (2 * Da) + Qd
        # update (the measurement is linear: z = p + noise)
        z = meas[:, j]
        ok = np.isfinite(z[:, 0])
        if ok.any():
            S = C[ok, 0:3, 0:3] + Rm
            nu = z[ok] - y[ok, 0:3]
            Sinv_nu = np.linalg.solve(S, nu[..., None])[..., 0]
            nis[ok] += np.einsum("ni,ni->n", nu, Sinv_nu)
            ldet[ok] += np.linalg.slogdet(S)[1]
            cnt[ok] += 1
            Kg = np.linalg.solve(S, C[ok, 0:3, :]).transpose(0, 2, 1)       # (m, 13, 3)
            y[ok] += np.einsum("nij,nj->ni", Kg, nu)
            C[ok] -= Kg @ S @ Kg.transpose(0, 2, 1)
            C[ok] = 0.5 * (C[ok] + C[ok].transpose(0, 2, 1))
        for key, kk in record.items():
            hit = kk == j
            if hit.any():
                o = out[key]
                o["y"][hit], o["ycov"][hit] = y[hit], C[hit]
                o["nis"][hit], o["ldet"][hit], o["cnt"][hit] = nis[hit], ldet[hit], cnt[hit]
    return out | {"active": act, "q": q}


# ------------------------------------------------------------------ model averaging

def model_weights(logliks: list, prior=None) -> np.ndarray:
    """Posterior model probabilities (M, n) from per-model log evidences (each (n,))."""
    lz = np.stack(logliks)
    if prior is not None:
        lz = lz + np.log(np.asarray(prior))[:, None]
    w = np.exp(lz - lz.max(0))
    return w / w.sum(0)


def mixture(lds: list, w: np.ndarray, pouts: list | None = None) -> dict:
    """Moment-matched mixture of landing Gaussians (each dict from landing_distribution)."""
    mu = sum(w[m][:, None] * lds[m]["land"][:, :2] for m in range(len(lds)))
    cov = sum(w[m][:, None, None] * (lds[m]["cov"] + np.einsum("ni,nj->nij", lds[m]["land"][:, :2] - mu,
                                                                lds[m]["land"][:, :2] - mu))
              for m in range(len(lds)))
    land = np.c_[mu, np.full(len(mu), R)]
    out = {"land": land, "cov": cov}
    if pouts is not None:
        out["p_out"] = sum(w[m] * pouts[m] for m in range(len(lds)))
    return out
