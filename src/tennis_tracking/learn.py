"""Landing-point predictors on top of the tracked image trajectory, and their evaluation.

Predictors (all causal: only frames up to the decision frame are used)
  ground : the last observed ball position back-projected to the ground (z = ball radius).
           Exact at the bounce, and the error grows with the ball's height before it.
  phys3d : the monocular 3D ballistic fit (fit3d.py) extrapolated to the ground.
  learned: gradient-boosted correction. Targets are the landing offset from the `ground`
           point. Features are court-frame kinematics (ground projections at z = R and z = 1 m,
           their velocities, image velocity and acceleration), time since the hit, serve flag,
           the hit point, and the phys3d outputs (landing, time to land, spin, fit rms). Court
           coordinates are mirrored so the ball always travels towards -y. Trained on games
           1-7 only. Out-of-fold (leave-one-game-out) predictions on games 1-7 set the
           thresholds; one model fitted on all of 1-7 predicts games 8-10.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from geometry import BALL_R, ground_xy

FEATS = ["n_obs", "t_since", "serve", "gx", "gy", "hx", "hy", "vgx", "vgy", "vhx", "vhy", "du", "dv",
         "ddu", "ddv", "hitx", "hity", "p_dx", "p_dy", "p_tau", "p_c", "p_z0", "p_rms"]


def features(P, tracks, pr, skip=1):
    """One row per (flight, decision frame) of the physics prediction table `pr`."""
    fl = P["flights"]
    rows = []
    for fid, d in pr.groupby("fid"):
        r = fl.loc[fid]
        cam, H = P["cams"][(r.game, r["clip"])]["cam"], P["cams"][(r.game, r["clip"])]["H"]
        uv = tracks[(r.game, r["clip"])]
        F = r.fps
        k0 = r.hit_end + skip
        uvh = uv[r.hit_end] if np.isfinite(uv[r.hit_end, 0]) else None
        zh = 2.7 if r.serve else 1.0
        for _, q in d.iterrows():
            kd = int(q.kdec)
            fr = np.arange(k0, kd + 1)
            fr = fr[np.isfinite(uv[fr, 0])] if len(fr) else fr
            if len(fr) < 3:
                continue
            last = uv[fr[-1]]
            gR = ground_xy(H, cam, last[None])[0]
            g1 = cam.backproject_to_z(last[None], 1.0)[0]
            j = max(len(fr) - 4, 0)
            dtj = (fr[-1] - fr[j]) / F
            gRj = ground_xy(H, cam, uv[fr[j]][None])[0]
            g1j = cam.backproject_to_z(uv[fr[j]][None], 1.0)[0]
            m = fr[-6:]
            tt = (m - kd).astype(float)
            deg = 2 if len(m) >= 4 else 1
            cu = np.polyfit(tt, uv[m, 0], deg)
            cv = np.polyfit(tt, uv[m, 1], deg)
            hp = cam.backproject_to_z((uvh if uvh is not None else uv[fr[0]])[None], zh)[0]
            s = np.sign(hp[1]) if hp[1] != 0 else 1.0   # 180-degree turn so the hitter is at +y
            rec = dict(fid=fid, kdec=kd, lead_ms=q.lead_ms, mirror=s, n_obs=len(fr),
                       t_since=(kd - r.hit_end) / F, serve=float(r.serve),
                       gx=s * gR[0], gy=s * gR[1], hx=s * g1[0], hy=s * g1[1],
                       vgx=s * (gR[0] - gRj[0]) / dtj, vgy=s * (gR[1] - gRj[1]) / dtj,
                       vhx=s * (g1[0] - g1j[0]) / dtj, vhy=s * (g1[1] - g1j[1]) / dtj,
                       du=cu[-2], dv=cv[-2], ddu=cu[0] if deg == 2 else 0.0, ddv=cv[0] if deg == 2 else 0.0,
                       hitx=s * hp[0], hity=s * hp[1],
                       tx=s * r.x_b - s * gR[0], ty=s * r.y_b - s * gR[1])
            if np.isfinite(q.get("x_hat", np.nan)):
                rec.update(p_dx=s * q.x_hat - s * gR[0], p_dy=s * q.y_hat - s * gR[1],
                           p_tau=(q.t_land_err_ms + q.lead_ms) / 1000.0, p_c=q.c, p_z0=q.z0, p_rms=q.rms_px)
            else:
                rec.update(p_dx=np.nan, p_dy=np.nan, p_tau=np.nan, p_c=np.nan, p_z0=np.nan, p_rms=np.nan)
            rows.append(rec)
    X = pd.DataFrame(rows)
    return X.join(fl[["game", "split", "x_b", "y_b", "d_true", "is_out", "serve", "srv_sx", "srv_sy"]]
                  .rename(columns={"serve": "serve_flag"}), on="fid")


def _model():
    return HistGradientBoostingRegressor(loss="absolute_error", max_iter=300, learning_rate=0.05,
                                         max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                                         random_state=0)


def fit_predict(X):
    """-> X with columns lx, ly (learned landing, court frame): out-of-fold on train games,
    model-on-all-train for test games."""
    X = X.copy()
    X["lx"], X["ly"] = np.nan, np.nan
    tr = X.split == "train"
    for g in sorted(X.loc[tr, "game"].unique()):
        fit_m, pred_m = tr & (X.game != g), tr & (X.game == g)
        for t, col in (("tx", "lx"), ("ty", "ly")):
            m = _model().fit(X.loc[fit_m, FEATS], X.loc[fit_m, t])
            X.loc[pred_m, col] = m.predict(X.loc[pred_m, FEATS])
    te = X.split == "test"
    for t, col in (("tx", "lx"), ("ty", "ly")):
        m = _model().fit(X.loc[tr, FEATS], X.loc[tr, t])
        X.loc[te, col] = m.predict(X.loc[te, FEATS])
    # back to court coordinates
    X["lx"] = (X.gx + X.lx) * X.mirror
    X["ly"] = (X.gy + X.ly) * X.mirror
    return X
