"""How early can ball tracking call a tennis ball out? A physics Monte Carlo.

Truth: a tennis ball with drag and Magnus lift (Cross & Lindsey style lift curve),
integrated with RK4. Measurement: Hawk-Eye-class tracking, 340 samples/s with
isotropic 3D noise. Predictor: what a tracker can do mid-flight. Fit position,
velocity and acceleration over the last 150 ms, back out the spin term from the
acceleration, and integrate the physics forward to the bounce.

The output is the lead time (ms before the bounce) at which an "out" call reaches a
given precision, as a function of how far out the ball lands. This is a model
estimate under stated assumptions, not measured Hawk-Eye data (which is proprietary).

Court: y runs from the hitter's baseline (0) to the far baseline (23.77 m), x across
the court (singles sidelines at +-4.115 m), z up. Net 0.914 m at y = 11.885.
"""
from __future__ import annotations

import numpy as np

G = np.array([0.0, 0.0, -9.81])
M, R, RHO, CD = 0.0577, 0.0335, 1.21, 0.55
AREA = np.pi * R * R
KD = 0.5 * RHO * AREA * CD / M        # drag accel = -KD |v| v
KL = 0.5 * RHO * AREA / M             # lift accel = KL CL |v|^2 (w_hat x v_hat)
BASELINE, SIDELINE, NET_Y, NET_H = 23.77, 4.115, 11.885, 0.914

FPS, NOISE = 340.0, 0.0036            # assumed tracking rate (Hz) and 1-sigma 3D error (m)


def _accel_truth(v: np.ndarray, w_hat: np.ndarray, omega: np.ndarray) -> np.ndarray:
    sp = np.linalg.norm(v, axis=1, keepdims=True)
    S = R * omega[:, None] / np.maximum(sp, 1e-6)
    CL = 1.0 / (2.0 + 1.0 / np.maximum(S, 1e-6))
    lift = KL * CL * sp**2 * np.cross(w_hat, v / np.maximum(sp, 1e-6))
    return G - KD * sp * v + lift


def _accel_pred(v: np.ndarray, w_hat: np.ndarray, cmag: np.ndarray) -> np.ndarray:
    sp = np.linalg.norm(v, axis=1, keepdims=True)
    return G - KD * sp * v + cmag[:, None] * sp**2 * np.cross(w_hat, v / np.maximum(sp, 1e-6))


def _integrate(p, v, acc, dt=5e-4, tmax=2.5, record_every=None):
    """RK4 until z <= R. Returns landing points, flight times and (optionally) samples."""
    p, v = p.copy(), v.copy()
    n = len(p)
    t = np.zeros(n)
    alive = np.ones(n, bool)
    land = np.full((n, 3), np.nan)
    tl = np.full(n, np.nan)
    samples, k, next_rec = [], 0, 0.0
    while alive.any() and t.max() < tmax:
        a = alive.copy()
        if record_every is not None and k * dt >= next_rec - 1e-12:
            samples.append(np.where(a[:, None], p, np.nan))
            next_rec += record_every
        k1v, k1p = acc(v[a], a), v[a]
        k2v, k2p = acc(v[a] + 0.5 * dt * k1v, a), v[a] + 0.5 * dt * k1v
        k3v, k3p = acc(v[a] + 0.5 * dt * k2v, a), v[a] + 0.5 * dt * k2v
        k4v, k4p = acc(v[a] + dt * k3v, a), v[a] + dt * k3v
        newp = p[a] + dt / 6 * (k1p + 2 * k2p + 2 * k3p + k4p)
        newv = v[a] + dt / 6 * (k1v + 2 * k2v + 2 * k3v + k4v)
        hit = newp[:, 2] <= R
        idx = np.flatnonzero(a)
        if hit.any():
            # linear interpolation to the contact height
            f = (p[a][hit, 2] - R) / (p[a][hit, 2] - newp[hit, 2])
            land[idx[hit]] = p[a][hit] + f[:, None] * (newp[hit] - p[a][hit])
            tl[idx[hit]] = t[idx[hit]] + f * dt
            alive[idx[hit]] = False
        p[a], v[a] = newp, newv
        t[a] += dt
        k += 1
    return land, tl, (np.stack(samples, 1) if samples else None)


def sample_shots(n: int, rng: np.random.Generator) -> dict:
    """Groundstrokes aimed near the lines: the population where calls matter.

    Serves are left out (their box geometry adds code, not insight); `serve` stays in the
    schema so they can be added later."""
    serve = np.zeros(n, bool)
    p0 = np.stack([rng.uniform(-3, 3, n), rng.uniform(-1.0, 0.5, n),
                   np.where(serve, rng.uniform(2.6, 2.9, n), rng.uniform(0.7, 1.2, n))], 1)
    speed = np.where(serve, rng.uniform(45, 62, n), rng.uniform(24, 40, n))
    elev = np.where(serve, rng.uniform(-8, -2, n), rng.uniform(2, 12, n)) * np.pi / 180
    tx = rng.uniform(-SIDELINE - 0.5, SIDELINE + 0.5, n)
    azim = np.arctan2(tx - p0[:, 0], BASELINE - p0[:, 1]) + rng.normal(0, 0.01, n)
    v0 = speed[:, None] * np.stack([np.cos(elev) * np.sin(azim), np.cos(elev) * np.cos(azim), np.sin(elev)], 1)
    rpm = np.where(serve, rng.uniform(1500, 3000, n), rng.uniform(1200, 3500, n))
    omega = rpm * 2 * np.pi / 60
    # topspin axis: horizontal, perpendicular to the direction of travel
    w_hat = np.stack([-np.cos(azim), np.sin(azim), np.zeros(n)], 1)
    return {"p0": p0, "v0": v0, "omega": omega, "w_hat": w_hat, "serve": serve}


def signed_out_distance(land: np.ndarray, serve: np.ndarray) -> np.ndarray:
    """Positive = out (m beyond the nearest line it crossed), negative = in.

    Serves use the service box (service line at y = 18.285, centre line at x = 0, box on x > 0)."""
    x, y = land[:, 0], land[:, 1]
    d_long = np.where(serve, y - (NET_Y + 6.40), y - BASELINE)
    d_side = np.where(serve, np.maximum(x - SIDELINE, -x), np.abs(x) - SIDELINE)
    return np.maximum(d_long, d_side)


def simulate(n: int = 20000, seed: int = 7, leads_ms=(0, 25, 50, 100, 150, 200, 300, 400)):
    rng = np.random.default_rng(seed)
    s = sample_shots(n, rng)
    acc_t = lambda v, a: _accel_truth(v, s["w_hat"][a], s["omega"][a])
    land, tland, traj = _integrate(s["p0"], s["v0"], acc_t, record_every=1 / FPS)
    ok = np.isfinite(tland)
    # must clear the net: height when crossing NET_Y
    y = traj[..., 1]
    cross = np.argmax(np.nan_to_num(y, nan=-1) >= NET_Y, axis=1)
    zc = traj[np.arange(n), cross, 2]
    ok &= (zc > NET_H + R) & (tland > 0.25)
    d = signed_out_distance(land, s["serve"])
    ok &= np.abs(d) < 1.0  # near-line population
    # balance in/out so precision is not inflated by the base rate
    ins, outs = np.flatnonzero(ok & (d <= 0)), np.flatnonzero(ok & (d > 0))
    k = min(len(ins), len(outs))
    idx = np.sort(np.concatenate([rng.choice(ins, k, replace=False), rng.choice(outs, k, replace=False)]))
    traj, tland, d, serve = traj[idx], tland[idx], d[idx], s["serve"][idx]
    w_true = s["w_hat"][idx]
    meas = traj + rng.normal(0, NOISE, traj.shape)

    W = int(0.15 * FPS)  # 150 ms fitting window
    rows = []
    for L in leads_ms:
        t_dec = tland - L / 1000.0
        k_dec = np.floor(t_dec * FPS).astype(int)
        good = k_dec >= W
        kk = k_dec[good]
        m = meas[good]
        # local quadratic fit over the window ending at the decision sample
        tt = (np.arange(-W + 1, 1) / FPS)
        X = np.stack([np.ones_like(tt), tt, 0.5 * tt**2], 1)
        pinv = np.linalg.pinv(X)
        win = np.stack([m[i, k - W + 1:k + 1] for i, k in enumerate(kk)])  # (n, W, 3)
        coef = np.einsum("jw,nwc->njc", pinv, win)
        p_now, v_now, a_now = coef[:, 0], coef[:, 1], coef[:, 2]
        sp = np.linalg.norm(v_now, axis=1, keepdims=True)
        a_mag = a_now - G + KD * sp * v_now
        a_perp = a_mag - (np.sum(a_mag * v_now, 1, keepdims=True) / sp**2) * v_now
        w_est = np.cross(v_now, a_perp)
        w_est /= np.maximum(np.linalg.norm(w_est, axis=1, keepdims=True), 1e-9)
        cmag = np.linalg.norm(a_perp, axis=1) / np.maximum(sp[:, 0] ** 2, 1e-9)
        acc_p = lambda v, a: _accel_pred(v, w_est[a], cmag[a])
        land_hat, _, _ = _integrate(p_now, v_now, acc_p)
        d_hat = signed_out_distance(land_hat, serve[good])
        rows.append({"lead_ms": L, "d": d[good], "d_hat": d_hat, "serve": serve[good]})
    return rows


def calls_at_precision(rows, target=0.95, bins=(0.0, 0.02, 0.05, 0.10, 0.20, 0.40, 1.0), seed=0):
    """Pick the out-threshold on half the shots to hit `target` precision; score the other half."""
    rng = np.random.default_rng(seed)
    out = []
    for r in rows:
        d, dh = r["d"], r["d_hat"]
        n = len(d)
        cal = rng.random(n) < 0.5
        thr = None
        for t in np.linspace(-0.05, 0.5, 221):
            sel = cal & (dh > t)
            if sel.sum() >= 30 and (d[sel] > 0).mean() >= target:
                thr = t
                break
        rec = {"lead_ms": r["lead_ms"], "threshold_m": thr, "n": int(n),
               "pred_err_sd_cm": float(np.std(dh - d) * 100)}
        if thr is None:
            rec.update(precision=np.nan, recall=np.nan)
        else:
            te = ~cal
            called = te & (dh > thr)
            rec["precision"] = float((d[called] > 0).mean()) if called.any() else np.nan
            rec["recall"] = float((called & (d > 0)).sum() / max((te & (d > 0)).sum(), 1))
            for lo, hi in zip(bins[:-1], bins[1:]):
                grp = te & (d > lo) & (d <= hi)
                rec[f"recall_out_{int(lo*100)}_{int(hi*100)}cm"] = float(called[grp].mean()) if grp.any() else np.nan
        out.append(rec)
    return out
