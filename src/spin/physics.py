"""Tennis-ball flight physics with a full spin vector, plus the simulated shot populations.

Aerodynamics are the ones in src/hawkeye.py: drag Cd = 0.55 (scaled per shot by `c`) and
Magnus lift with the Cross & Lindsey curve CL = 1/(2 + 1/S), S = R |w_perp| / |v_air|.
Written for a general spin vector w (rad/s), the lift acceleration is

    a_L = KL |v|^2 CL(S) (w_hat x v_hat) = KL R (w x v) / (1 + 2 S)

which equals hawkeye._accel_truth when w is perpendicular to v (true for every hawkeye shot),
and is smooth through w = 0. The spin component along v (gyro spin) produces no force.

Model-mismatch knobs (the truth can have them, the filters may or may not model them):
  c     per-shot drag scale (Cd = 0.55 c)
  lam   spin decay rate, dw/dt = -lam w (1/s); 2 %/100 ms is lam = -ln(0.98)/0.1 = 0.202
  wind  air velocity (m/s); drag and lift act on v - wind

Arrays are component-major, x has shape (9, N): rows p(3), v(3), w(3).
"""
from __future__ import annotations

import numpy as np

from src import hawkeye as H

G_Z = H.G[2]
R, KD, KL, CD0 = H.R, H.KD, H.KL, H.CD
FPS, NOISE = H.FPS, H.NOISE
W_FIT = int(0.15 * FPS)  # the hawkeye baseline's 150 ms window (51 frames)


def deriv(x: np.ndarray, c, lam, wind, cl_scale: float = 1.0, cd_s: float = 0.0) -> np.ndarray:
    """dx/dt for x (9, N); c, lam (N,) or scalars; wind (3, N) or None.
    cl_scale, cd_s: truth-only aerodynamic mismatch (lift x cl_scale, Cd x (1 + cd_s (S - 0.25)))."""
    vx, vy, vz, wx, wy, wz = x[3], x[4], x[5], x[6], x[7], x[8]
    if wind is not None:
        ux, uy, uz = vx - wind[0], vy - wind[1], vz - wind[2]
    else:
        ux, uy, uz = vx, vy, vz
    sp2 = ux * ux + uy * uy + uz * uz
    sp = np.sqrt(sp2)
    wu = wx * ux + wy * uy + wz * uz
    w2 = wx * wx + wy * wy + wz * wz
    wperp = np.sqrt(np.maximum(w2 - wu * wu / np.maximum(sp2, 1e-12), 0.0))
    S = R * wperp / np.maximum(sp, 1e-6)
    k = (cl_scale * KL * R) / (1.0 + 2.0 * S)
    kd = KD * c * sp if cd_s == 0.0 else KD * c * sp * (1.0 + cd_s * (S - 0.25))
    out = np.empty_like(x)
    out[0], out[1], out[2] = vx, vy, vz
    out[3] = -kd * ux + k * (wy * uz - wz * uy)
    out[4] = -kd * uy + k * (wz * ux - wx * uz)
    out[5] = G_Z - kd * uz + k * (wx * uy - wy * ux)
    out[6], out[7], out[8] = -lam * wx, -lam * wy, -lam * wz
    return out


def rk4(x: np.ndarray, h: float, c, lam, wind, **aero) -> np.ndarray:
    k1 = deriv(x, c, lam, wind, **aero)
    k2 = deriv(x + 0.5 * h * k1, c, lam, wind, **aero)
    k3 = deriv(x + 0.5 * h * k2, c, lam, wind, **aero)
    k4 = deriv(x + h * k3, c, lam, wind, **aero)
    return x + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)


def integrate_truth(p0, v0, w0, c, lam, wind, dt=5e-4, tmax=2.5, exact_frames=False, **aero):
    """Truth flights, mirroring hawkeye._integrate (RK4 at 0.5 ms, record the first step at or
    after each 1/FPS tick, linear interpolation to z = R).

    exact_frames=True instead uses dt = 1/(6 FPS) so samples sit exactly on the frame clock
    (hawkeye's recorder lands up to 0.5 ms late, a timing jitter the trackers do not know about).
    Returns land (n,3), tland (n,), traj (n,K,3) with NaN after landing, sample times (K,)."""
    n = len(p0)
    x = np.concatenate([p0.T, v0.T, w0.T]).astype(float)
    c = np.broadcast_to(np.asarray(c, float), (n,)).copy()
    lam = np.broadcast_to(np.asarray(lam, float), (n,)).copy()
    wind = np.broadcast_to(np.asarray(wind, float).reshape(3, -1), (3, n)).copy()
    if exact_frames:
        dt = 1.0 / (6 * FPS)
    t = np.zeros(n)
    alive = np.ones(n, bool)
    land = np.full((n, 3), np.nan)
    tl = np.full(n, np.nan)
    samples, stimes = [], []
    k, next_rec = 0, 0.0
    while alive.any() and t.max() < tmax:
        a = alive.copy()
        rec = (k % 6 == 0) if exact_frames else (k * dt >= next_rec - 1e-12)
        if rec:
            samples.append(np.where(a[:, None], x[0:3].T, np.nan))
            stimes.append(k * dt)
            next_rec += 1.0 / FPS
        ia = np.flatnonzero(a)
        xa = x[:, ia]
        nx = rk4(xa, dt, c[ia], lam[ia], wind[:, ia], **aero)
        hit = nx[2] <= R
        if hit.any():
            f = (xa[2, hit] - R) / (xa[2, hit] - nx[2, hit])
            land[ia[hit]] = (xa[0:3, hit] + f * (nx[0:3, hit] - xa[0:3, hit])).T
            tl[ia[hit]] = t[ia[hit]] + f * dt
            alive[ia[hit]] = False
        x[:, ia] = nx
        t[ia] += dt
        k += 1
    return land, tl, np.stack(samples, 1), np.array(stimes)


# ---------------------------------------------------------------- shot populations

LAM_2PCT = -np.log(0.98) / 0.1  # 2 % spin loss per 100 ms

CONDITIONS = {
    # name: dict of truth perturbations (all default to the hawkeye world)
    "nominal": {},
    "exact_t": {"exact_frames": True},
    "cd15": {"cd_spread": 0.15},
    "decay": {"lam": LAM_2PCT},
    "wind": {"wind": (2.0, 0.0, 0.0)},
    "noise2x": {"noise_mult": 2.0},
    "all": {"cd_spread": 0.15, "lam": LAM_2PCT, "wind": (2.0, 0.0, 0.0), "noise_mult": 2.0},
    "spin_mix": {"spin_mix": True},
    # aerodynamic-model mismatch: 10 % less lift than Cross & Lindsey, spin-dependent drag
    "aero": {"cl_scale": 0.9, "cd_s": 0.5},
    # tuning-only world (used with a different seed): milder, differently shaped mismatch
    "dev": {"cd_spread": 0.10, "lam": -np.log(0.99) / 0.1, "wind": (1.0, 1.0, 0.0)},
}


def _spin_mix(s: dict, prng: np.random.Generator):
    """General spin: 55 % topspin, 25 % slice (backspin, slower, flatter), 20 % flat-ish,
    every axis tilted about the launch direction by up to 40 deg (sidespin) and given a
    gyro component of up to 30 % (which produces no Magnus force)."""
    n = len(s["omega"])
    v0 = s["v0"].copy()
    u = prng.random(n)
    slice_ = u < 0.25
    flat = (u >= 0.25) & (u < 0.45)
    rpm = s["omega"] * 60 / (2 * np.pi)
    rpm = np.where(slice_, prng.uniform(500, 1800, n), np.where(flat, prng.uniform(300, 1200, n), rpm))
    # slices: 20-30 m/s, 0-8 deg elevation, same aim
    sp = np.linalg.norm(v0, axis=1)
    azim = np.arctan2(v0[:, 0], v0[:, 1])
    elev = np.arcsin(v0[:, 2] / sp)
    sp = np.where(slice_, prng.uniform(20, 30, n), sp)
    elev = np.where(slice_, prng.uniform(0, 8, n) * np.pi / 180, elev)
    v0 = sp[:, None] * np.stack([np.cos(elev) * np.sin(azim), np.cos(elev) * np.cos(azim), np.sin(elev)], 1)
    vh = v0 / np.linalg.norm(v0, axis=1, keepdims=True)
    w_hat = s["w_hat"] * np.where(slice_, -1.0, 1.0)[:, None]
    # Rodrigues rotation of the axis about the flight direction (sidespin tilt)
    a = prng.uniform(-40, 40, n) * np.pi / 180
    w_hat = (w_hat * np.cos(a)[:, None] + np.cross(vh, w_hat) * np.sin(a)[:, None]
             + vh * np.sum(vh * w_hat, 1, keepdims=True) * (1 - np.cos(a))[:, None])
    mag = rpm * 2 * np.pi / 60
    w0 = mag[:, None] * w_hat + (prng.uniform(-0.3, 0.3, n) * mag)[:, None] * vh
    kind = np.where(slice_, "slice", np.where(flat, "flat", "topspin"))
    return v0, w0, kind


def build_population(cond: str = "nominal", n: int = 20000, seed: int = 7) -> dict:
    """The hawkeye.simulate population (same generator, filters, in/out balancing and noise
    stream), optionally in a perturbed world. With cond='nominal' and seed=7 it reproduces
    hawkeye.simulate exactly (checked in scripts/spin_tennis_check.py)."""
    cfg = CONDITIONS[cond]
    rng = np.random.default_rng(seed)
    s = H.sample_shots(n, rng)
    prng = np.random.default_rng(seed + 1000)  # perturbation stream, keeps `rng` in lockstep
    v0, w0 = s["v0"], s["omega"][:, None] * s["w_hat"]
    kind = np.full(n, "topspin")
    if cfg.get("spin_mix"):
        v0, w0, kind = _spin_mix(s, prng)
    spread = cfg.get("cd_spread", 0.0)
    c = prng.uniform(1 - spread, 1 + spread, n) if spread else np.ones(n)
    lam = np.full(n, cfg.get("lam", 0.0))
    wind = np.asarray(cfg.get("wind", (0.0, 0.0, 0.0)), float)[:, None] * np.ones(n)
    aero = {k: cfg[k] for k in ("cl_scale", "cd_s") if k in cfg}
    land, tland, traj, stimes = integrate_truth(s["p0"], v0, w0, c, lam, wind,
                                                exact_frames=cfg.get("exact_frames", False), **aero)
    ok = np.isfinite(tland)
    y = traj[..., 1]
    cross = np.argmax(np.nan_to_num(y, nan=-1) >= H.NET_Y, axis=1)
    zc = traj[np.arange(n), cross, 2]
    ok &= (zc > H.NET_H + R) & (tland > 0.25)
    d = H.signed_out_distance(land, s["serve"])
    ok &= np.abs(d) < 1.0
    ins, outs = np.flatnonzero(ok & (d <= 0)), np.flatnonzero(ok & (d > 0))
    k = min(len(ins), len(outs))
    idx = np.sort(np.concatenate([rng.choice(ins, k, replace=False), rng.choice(outs, k, replace=False)]))
    traj = traj[idx]
    meas = traj + rng.normal(0, NOISE * cfg.get("noise_mult", 1.0), traj.shape)
    return {
        "cond": cond, "seed": seed, "idx": idx, "traj": traj, "meas": meas, "stimes": stimes,
        "land": land[idx], "tland": tland[idx], "d": d[idx], "serve": s["serve"][idx],
        "p0": s["p0"][idx], "v0": v0[idx], "w0": w0[idx], "c": c[idx], "lam": lam[idx],
        "wind": wind[:, idx].T, "kind": kind[idx], "noise": NOISE * cfg.get("noise_mult", 1.0),
    }


def true_spin_at(pop: dict, sel, k: np.ndarray) -> np.ndarray:
    """True spin vector (m,3) of shots `sel` at their sample index k (m,): w0 exp(-lam t)."""
    t = pop["stimes"][k]
    return pop["w0"][sel] * np.exp(-pop["lam"][sel] * t)[:, None]


def true_vel_at(pop: dict, sel, k: np.ndarray) -> np.ndarray:
    """Truth velocity (m,3) of shots `sel` at sample k from a central difference of the
    noiseless track (one-sided at the ends)."""
    tr, st = pop["traj"][sel], pop["stimes"]
    K = tr.shape[1]
    i = np.arange(len(k))
    k0 = np.maximum(k - 1, 0)
    k1 = np.minimum(k + 1, K - 1)
    k1 = np.where(np.isfinite(tr[i, k1, 0]), k1, k)
    return (tr[i, k1] - tr[i, k0]) / (st[k1] - st[k0])[:, None]
