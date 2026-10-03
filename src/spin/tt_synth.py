"""Synthetic check of the spin-aware fitter (no real data): can a monocular 120 fps track recover spin
and the landing point, and how much does the spin term change the landing call?

Truth flights are simulated with model mismatch the fitter does not know about: per-shot drag scale
U(0.85, 1.15), spin decay 2 %/100 ms, sub-frame start time, 2 px pixel noise, 2 % outlier detections
(up to 40 px off) and 3 % missed frames. They are projected with an OpenTTGames-like camera (f = 1370 px,
3.9 m from the side line, 0.95 m above the table; the calibrated train cameras are 1320-1385 px,
3.8-4.1 m, 0.94-1.67 m). Every flight is fitted online exactly as tt_features does for real flights.

Usage: python src/spin/tt_synth.py --n 120 --out results/spin/tt/synthetic_check.json
"""
import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tt_features as TF  # noqa: E402
import tt_physics as PH  # noqa: E402
from tt_camera import Camera  # noqa: E402


def look_at_camera(C, target, f=1370.0, roll_deg=0.0):
    C, target = np.asarray(C, float), np.asarray(target, float)
    z = target - C
    z /= np.linalg.norm(z)
    x = np.cross(z, [0, 0, 1.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z])
    if roll_deg:
        a = np.radians(roll_deg)
        Rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
        R = Rz @ R
    return Camera(f, R, -R @ C)


def simulate_truth(p0, v0, w0, drag_scale, lam, dt=1.0 / 1200, tmax=1.6):
    """Fine RK4 with spin decay; returns times, positions (N, 3) until Z <= R (landing) or tmax."""
    p, v, w = np.array(p0, float), np.array(v0, float), np.array(w0, float)
    ts, ps = [0.0], [p.copy()]
    t = 0.0

    def acc(v, w):
        sp = np.linalg.norm(v)
        wperp = np.linalg.norm(w - (w @ v) * v / sp ** 2)
        return (np.array([0, 0, -PH.G]) - drag_scale * PH.KD * sp * v
                + PH.KM * np.cross(w, v) / (1 + 2 * PH.R_BALL * wperp / sp))
    while t < tmax:
        a1 = acc(v, w)
        a2 = acc(v + 0.5 * dt * a1, w * np.exp(-lam * dt / 2))
        a3 = acc(v + 0.5 * dt * a2, w * np.exp(-lam * dt / 2))
        a4 = acc(v + dt * a3, w * np.exp(-lam * dt))
        p = p + dt * (v + dt / 6 * (a1 + a2 + a3))
        v = v + dt / 6 * (a1 + 2 * a2 + 2 * a3 + a4)
        w = w * np.exp(-lam * dt)
        t += dt
        ts.append(t)
        ps.append(p.copy())
        if p[2] <= PH.R_BALL and v[2] < 0:
            break
    return np.array(ts), np.array(ps)


def sample_shot(rng):
    d = rng.choice([-1.0, 1.0])
    p0 = np.array([-d * (PH.HALF_L + rng.uniform(0.0, 1.4)), rng.uniform(-0.7, 0.7), rng.uniform(0.05, 0.6)])
    u = rng.random()
    top = rng.uniform(15, 120) if u < 0.55 else (rng.uniform(-60, -10) if u < 0.8 else rng.uniform(-10, 10))
    side = rng.normal(0, 15)
    sx = rng.uniform(5, 17)
    yt = rng.uniform(-0.9, 0.9)
    xt = d * rng.uniform(0.3, 2.0)
    head = np.array([xt - p0[0], yt - p0[1]])
    head /= np.linalg.norm(head)
    vz = rng.uniform(-1.0, 3.5)
    v0 = np.array([head[0] * sx, head[1] * sx, vz])
    eh = v0[:2] / np.linalg.norm(v0[:2])
    w0 = PH.TWO_PI * np.array([-eh[1] * top, eh[0] * top, side])
    return d, p0, v0, w0, top, side * d


def run(n, seed=0, verbose=True, anchor_mode="none"):
    rng = np.random.default_rng(seed)
    cam = look_at_camera([0.05, -3.9, 0.95], [0.0, 0.0, 0.0], roll_deg=1.0)
    rows, kept, t_fit, n_dec = [], 0, 0.0, 0
    while kept < n:
        d, p0, v0, w0, top, side = sample_shot(rng)
        ts, ps = simulate_truth(p0, v0, w0, rng.uniform(0.85, 1.15), -np.log(0.98) / 0.1)
        if ps[-1, 2] > PH.R_BALL:
            continue
        land = ps[-1]
        xr = d * ps[:, 0]
        if xr.max() < 0.05:
            continue
        kn = np.argmax(xr >= 0)
        if ps[kn, 2] < PH.R_BALL + PH.NET_H:     # keep net-clearing shots (the net is a separate case)
            continue
        xl = d * land[0]
        if not (-0.1 <= xl <= 2.6) or ts[-1] < 0.2:
            continue
        is_in = (0 < xl <= PH.HALF_L) and abs(land[1]) <= PH.HALF_W
        # balance in / out
        n_in = sum(r["in"] for r in rows if r["lead_ms"] == 50)
        n_out = sum(not r["in"] for r in rows if r["lead_ms"] == 50)
        if is_in and n_in >= n // 2 or (not is_in) and n_out >= n - n // 2:
            continue
        # frames: the first frame comes 0-1 frame after the hit
        off = rng.uniform(0, 1.0 / PH.FPS)
        tf = np.arange(off, ts[-1], 1.0 / PH.FPS)
        P = np.stack([np.interp(tf, ts, ps[:, i]) for i in range(3)], 1)
        cross_end = np.flatnonzero(d * P[:, 0] >= PH.HALF_L)
        k_ref = len(tf) - 1 if len(cross_end) == 0 else min(len(tf) - 1, int(cross_end[0]))
        uv = cam.project(P) + rng.normal(0, 2.0, (len(P), 2))
        out = rng.random(len(P)) < 0.02
        uv[out] += rng.uniform(-40, 40, (out.sum(), 2))
        keep = rng.random(len(P)) >= 0.03
        keep[:2] = True
        frames = np.arange(len(P))[keep] + 1000
        uv = uv[keep]
        t0, t_ref = 1000, 1000 + k_ref
        anchor = None
        if anchor_mode == "incoming":
            ph = p0 + rng.normal(0, 0.06, 3)
            anchor = PH.Anchor("incoming", t0 - off * PH.FPS, ph, np.eye(3) * 0.08 ** 2)
        leads = {k_ref - TF.LAG * 0 - int(round(L * PH.FPS / 1000)): L for L in (50, 100, 200)}
        dec = sorted(t for t in (t0 + k for k in leads) if t >= t0 + TF.NMIN - 1 + TF.LAG)
        if not dec:
            continue
        # the online loop runs over every decision frame (warm starts), we keep the three leads
        all_dec = list(range(t0 + TF.NMIN - 1 + TF.LAG, t_ref + 1))
        tt = time.time()
        fs = TF.online_features(cam, frames, uv, d, all_dec, anchor, spin=True, prefix="ph_", t_s=t0)
        gs = TF.online_features(cam, frames, uv, d, all_dec, anchor, spin=False, prefix="ns_", t_s=t0)
        t_fit += time.time() - tt
        n_dec += len(all_dec)
        kept += 1
        for t in dec:
            f, g = fs[all_dec.index(t)], gs[all_dec.index(t)]
            if f is None or g is None:
                continue
            rows.append(dict(lead_ms=leads[t - t0], **{"in": bool(is_in)}, true_top=top, true_side=side,
                             true_x_land=xl - PH.HALF_L, true_y_land=abs(land[1]) - PH.HALF_W,
                             speed=float(np.linalg.norm(v0)), **f, **g))
        if verbose and kept % 20 == 0:
            print(f"  {kept}/{n} flights, {1000 * t_fit / max(n_dec, 1):.1f} ms per decision frame "
                  f"(spin + no-spin fits)", flush=True)
    return rows, 1000 * t_fit / max(n_dec, 1)


def auc(y, s):
    y, s = np.asarray(y, bool), np.asarray(s, float)
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    if y.all() or (~y).all():
        return np.nan
    from scipy.stats import rankdata
    r = rankdata(s)
    return float((r[y].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (~y).sum()))


def summarize(rows, ms_per_frame):
    import pandas as pd
    df = pd.DataFrame(rows)
    out = {"ms_per_decision_frame_both_fits": round(ms_per_frame, 1), "n_flights": int((df.lead_ms == 50).sum())}
    for L, g in df.groupby("lead_ms"):
        strong = g[np.abs(g.true_top) >= 20]
        r = {
            "n": int(len(g)),
            "topspin_corr": round(float(np.corrcoef(g.ph_top, g.true_top)[0, 1]), 3),
            "topspin_sign_acc_|true|>=20rps": round(float((np.sign(strong.ph_top) == np.sign(strong.true_top)).mean()), 3),
            "topspin_mae_rps": round(float(np.abs(g.ph_top - g.true_top).median()), 1),
            "sidespin_corr": round(float(np.corrcoef(g.ph_side, g.true_side)[0, 1]), 3),
            "x_land_mae_m_spin": round(float(np.nanmedian(np.abs(g.ph_x_land - g.true_x_land))), 3),
            "x_land_mae_m_nospin_fit": round(float(np.nanmedian(np.abs(g.ns_x_land - g.true_x_land))), 3),
            "auc_out_vs_in_1-p_in_spin": round(auc(~g["in"], 1 - g.ph_p_in), 3),
            "auc_out_vs_in_1-p_in_nospin_fit": round(auc(~g["in"], 1 - g.ns_p_in), 3),
            "call_flips_spin_vs_nospin(in_mean)": int((g.ph_in_mean != g.ns_in_mean).sum()),
            "flip_correct": int(((g.ph_in_mean != g.ns_in_mean) & ((g.ph_in_mean == 1) == g["in"])).sum()),
            "x_land_sd_median": round(float(np.nanmedian(g.ph_x_land_sd)), 3),
            "x_land_z_score_sd": round(float(np.nanstd((g.ph_x_land - g.true_x_land) / g.ph_x_land_sd)), 2),
        }
        out[f"lead_{L}ms"] = r
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--anchor", default="none", choices=["none", "incoming"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows, msf = run(a.n, a.seed, anchor_mode=a.anchor)
    s = summarize(rows, msf)
    s["anchor_mode"] = a.anchor
    print(json.dumps(s, indent=1))
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump(s, open(a.out, "w"), indent=1)
