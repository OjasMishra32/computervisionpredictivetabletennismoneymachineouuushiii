"""Online physics/spin features for every (flight, decision frame) of the frozen H3 sample set.

For each flight (rows of the frozen WORK/flights.csv: same flights, same labels, same flight start t0)
and each decision frame t (the frozen rule: track points in [t0, t - LAG] only, LAG = 2), we

  1. look for a position anchor in the track before t0 (causal: it only uses frames <= t0 + 1):
       'bounce'   the flight starts right after a bounce (serve, or a ball that bounced on the
                  hitter's side and was not hit): the ball centre was at Z = R on the table plane
       'incoming' the incoming ball bounced on the hitter's half and then was hit at t0 - 1.5: a
                  short ballistic fit of the incoming segment (anchored at that bounce) gives the
                  contact point with its covariance
       none       weak position priors only
  2. fit the spin model to the prefix (tt_physics, warm-started from the previous decision frame, with
     fresh plane initialisations every REINIT frames) and a no-spin ablation (same model, spin = 0),
  3. extrapolate both with their uncertainty to the net, the far end line and the table plane.

Usage (from the repo root, on HiPerGator through hpg/spin_tt.sbatch):
  python src/spin/tt_features.py --split train --procs 8
"""
import argparse
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TRACKING = os.path.join(os.path.dirname(HERE), "tracking")
for _p in (HERE, TRACKING):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tt_physics as PH  # noqa: E402
from tt_camera import Camera  # noqa: E402

LAG = 2          # = early_call.LAG
NMIN = 5         # = early_call.NMIN
REINIT = 6       # fresh initialisations every REINIT decision frames
IN_LOOKBACK = 80  # frames searched before t0 for the incoming ball's bounce
BOUNCE_COV = np.diag([0.04, 0.06, 0.012]) ** 2


def is_bounce(trk, b):
    """flights.last_bounce's test at frame b: a local maximum of image y over +-2 frames with >= 2 px
    of descent before and ascent after."""
    ys = [trk.get(t) for t in range(b - 2, b + 3)]
    if any(p is None for p in ys):
        return False
    y = [p[1] for p in ys]
    return y[2] == max(y) and y[2] - y[0] >= 2 and y[2] - y[4] >= 2


def _on_hitter_half(P, d):
    return -PH.HALF_L - 0.08 <= d * P[0] <= 0.05 and abs(P[1]) <= PH.HALF_W + 0.08


def find_anchor(trk, t0, d, cam):
    """-> (tt_physics.Anchor or None, info dict). Uses track frames <= t0 + 1 only."""
    start = t0 - 1
    for b in (t0 - 1, t0 - 2):
        if is_bounce(trk, b):
            B = cam.backproject_z(np.array(trk[b], float), PH.R_BALL)
            if _on_hitter_half(B, d):
                return PH.Anchor("bounce", b, B, BOUNCE_COV), {"anchor": "bounce", "b": b}
    for b in range(start - 3, t0 - IN_LOOKBACK, -1):
        if not is_bounce(trk, b):
            continue
        B = cam.backproject_z(np.array(trk[b], float), PH.R_BALL)
        if not _on_hitter_half(B, d):
            return None, {"anchor": "none", "reason": "incoming bounce not on the hitter's half"}
        fr = np.array([f for f in range(b, start - 1) if f in trk])
        if len(fr) < 4:
            return None, {"anchor": "none", "reason": "incoming segment too short"}
        uv = np.array([trk[f] for f in fr], float)
        # the incoming ball moves against d all along the segment
        if np.any(np.diff(uv[:, 0]) * d > 2.0):
            return None, {"anchor": "none", "reason": "incoming segment not monotone"}
        a_b = PH.Anchor("bounce", b, B, BOUNCE_COV)
        prob = PH.FlightProblem(cam, fr, uv, -d, anchor=a_b, spin=False, t_s=b)
        fit = PH.fit_prefix(prob, fresh=True)
        if fit is None or fit.rms_px > 6.0:
            return None, {"anchor": "none", "reason": "incoming fit failed"}
        t_hit = start - 0.5
        n_h = t_hit - b
        k = int(np.ceil(n_h))
        SP = PH._sigma_points(fit.theta, fit.cov)
        P, _ = PH.integrate(SP[:, :3], SP[:, 3:6], PH.spin_vectors(SP), k)
        f = n_h - (k - 1)
        ph = (1 - f) * P[k - 1] + f * P[k]                       # (B, 3)
        mean = ph[0]
        cov = (ph[1:] - mean).T @ (ph[1:] - mean) / (len(ph) - 1) + np.diag([0.05, 0.05, 0.05]) ** 2
        if not (-0.3 <= mean[2] <= 1.2 and -3.5 <= d * mean[0] <= 0.3):
            return None, {"anchor": "none", "reason": "implausible contact point"}
        return PH.Anchor("incoming", t_hit, mean, cov), {"anchor": "incoming", "b": b,
                                                         "in_rms_px": round(fit.rms_px, 2)}
    return None, {"anchor": "none", "reason": "no bounce before the hit"}


def online_features(cam, frames, uv, d, dec_frames, anchor, spin=True, prefix="ph_", t_s=None):
    """Features for each decision frame (None where < NMIN points). frames/uv: the flight's track from
    its start (t0) to its end; only points <= t - LAG are used at decision frame t."""
    frames = np.asarray(frames, int)
    uv = np.asarray(uv, float)
    t_s = int(frames[0]) if t_s is None else int(t_s)
    out = []
    warm, last_n, last_fit, n_dec, prob = None, -1, None, 0, None
    for t in dec_frames:
        m = frames <= t - LAG
        nm = int(m.sum())
        if nm < NMIN or frames[m][-1] - frames[m][0] < NMIN - 1:
            out.append(None)
            continue
        if nm != last_n:
            prob = PH.FlightProblem(cam, frames[m], uv[m], d, anchor=anchor, spin=spin, t_s=t_s)
            fresh = (warm is None) or (n_dec % REINIT == 0)
            fit = PH.fit_prefix(prob, warm=warm, fresh=fresh)
            n_dec += 1
            last_n, last_fit = nm, fit
            if fit is not None:
                warm = fit.theta
        fit = last_fit
        if fit is None:
            out.append(PH.empty_features(spin, prefix))
            continue
        try:
            out.append(PH.predict(prob, fit, int(t - LAG - t_s), prefix=prefix))
        except Exception:
            out.append(PH.empty_features(spin, prefix))
    return out


def flight_job(job):
    """One flight -> list of feature rows (both the spin model 'ph_' and the no-spin ablation 'ns_')."""
    (key, trk, t0, t_ref, d, cam_d, ablation) = job
    cam = Camera.from_dict(cam_d)
    t_start = time.time()
    anchor, ainfo = find_anchor(trk, t0, d, cam)
    fr = np.array([f for f in range(t0, t_ref + 1) if f in trk], int)
    if len(fr) < NMIN:
        return key, [], ainfo, 0.0
    uv = np.array([trk[f] for f in fr], float)
    dec = list(range(t0 + NMIN - 1 + LAG, t_ref + 1))
    ph = online_features(cam, fr, uv, d, dec, anchor, spin=True, prefix="ph_", t_s=t0)
    ns = online_features(cam, fr, uv, d, dec, anchor, spin=False, prefix="ns_", t_s=t0) if ablation \
        else [None] * len(dec)
    akind = {"bounce": 1.0, "incoming": 2.0}.get(ainfo["anchor"], 0.0)
    rows = []
    for t, a, b in zip(dec, ph, ns):
        if a is None:
            continue
        r = {"t": t, "ph_anchor": akind}
        r.update(a)
        if b is not None:
            r.update(b)
        rows.append(r)
    return key, rows, ainfo, time.time() - t_start


def build(flights, tracks, cams, procs=1, ablation=True, log_every=50):
    """flights: DataFrame with video, f_net, dir, t0, t_ref. tracks: {video: {frame: (x, y)}}.
    -> (features keyed by (video, f_net, t), per-flight anchor info)."""
    jobs = []
    for r in flights.itertuples():
        trk = tracks[r.video]
        seg = {f: trk[f] for f in range(int(r.t0) - IN_LOOKBACK - 4, int(r.t_ref) + 1) if f in trk}
        jobs.append(((r.video, int(r.f_net)), seg, int(r.t0), int(r.t_ref), float(r.dir),
                     cams[r.video].to_dict(), ablation))
    rows, ainfos = [], []
    t0 = time.time()
    if procs > 1:
        import multiprocessing as mp
        # spawn, not fork: tt_early_call --final forks only after HGB has started OpenMP threads, and
        # forking an OpenMP process can deadlock the children
        ctx = mp.get_context("spawn")
        with ctx.Pool(procs) as pool:
            for i, res in enumerate(pool.imap_unordered(flight_job, jobs, chunksize=2)):
                _collect(res, rows, ainfos)
                if (i + 1) % log_every == 0:
                    print(f"  {i + 1}/{len(jobs)} flights, {time.time() - t0:.0f} s", flush=True)
    else:
        for i, j in enumerate(jobs):
            _collect(flight_job(j), rows, ainfos)
            if (i + 1) % log_every == 0:
                print(f"  {i + 1}/{len(jobs)} flights, {time.time() - t0:.0f} s", flush=True)
    return pd.DataFrame(rows), pd.DataFrame(ainfos)


def _collect(res, rows, ainfos):
    (video, f_net), rs, ainfo, sec = res
    for r in rs:
        r["video"], r["f_net"] = video, f_net
        rows.append(r)
    ainfos.append(dict(video=video, f_net=f_net, seconds=round(sec, 2), **ainfo))


if __name__ == "__main__":
    import common as C
    import tt_camera
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["train", "test"], required=True)
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--no-ablation", action="store_true")
    a = ap.parse_args()
    if a.split == "test":
        sys.exit("test features are built only inside tt_early_call.py --final (the single test evaluation)")
    WORK = os.environ.get("SPIN_WORK", os.path.join(C.WORK, "spin_tt"))
    os.makedirs(WORK, exist_ok=True)
    fl = pd.read_csv(os.path.join(C.WORK, "flights.csv"))
    fl = fl[fl.split == a.split].reset_index(drop=True)
    vids = sorted(fl.video.unique())
    cams, _ = tt_camera.cameras_all(vids, os.path.join(WORK, "cameras.json"))
    import early_call as E
    tracks = E.load_tracks(vids)
    F, A = build(fl, tracks, cams, procs=a.procs, ablation=not a.no_ablation)
    F.to_pickle(os.path.join(WORK, f"feats_{a.split}.pkl"))
    A.to_csv(os.path.join(WORK, f"anchors_{a.split}.csv"), index=False)
    print(a.split, len(F), "rows;", A.anchor.value_counts().to_dict())
