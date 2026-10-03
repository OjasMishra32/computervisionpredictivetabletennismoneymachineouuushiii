"""Per-flight fitted 3D trajectories + spin readout for a handful of visually clear TEST flights (showcase).

Real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0). Run AFTER the single spin-model test
evaluation (src/spin/tt_early_call.py --final): this computes no metric and fits no classifier; it
re-runs the same online physics fit (src/spin/tt_features.online_features logic, same warm starts and
re-initialisations) on a few test flights and saves, for each one,

  * the observed track (pixels) from the flight start t0 to the reference frame t_ref,
  * every decision frame's fit: state, topspin / sidespin (rps and rpm, with 1-sigma), P(in/long/net/wide),
    predicted landing point, and a check against the features stored by the test run (feats_test.pkl),
  * three full trajectories (3D, metres, and projected to pixels): the fit at the 50 ms lead, at the
    spin model's first online call (if any) and at t_ref, each continued to landing, plus the same state
    with the spin switched off (counterfactual),
  * a QA still (the video frame at t_ref with the track and the fitted / predicted paths drawn on it).

Selection ("visually clear", post hoc, for display only): the track covers >= 90% of the frames of the
flight and stays >= 60 px inside the image, the fit at the last decision frame has reprojection rms
<= 2.5 px with <= 15% outlier points, and the 50 ms fit exists. Then up to 4 MISS flights that either model called online and whose MISS label the
post-hoc audit did not question (results/tracking/test_flights_audited.csv, DEVIATIONS H3-D10): spin-model
calls first, largest gain in first-call lead over the frozen model first; then 2 BOUNCE flights neither
model called (one topspin and one backspin, |spin| <= 150 rps, most confident readout first); filled by
clarity.

Usage (HiPerGator, repo layout of hpg/spin_tt.sbatch, after STAGE=final):
  python scripts/cv_showcase_tt_fits.py --n 6 --out results/spin/tt/test/showcase
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (os.path.join(REPO, "src", "spin"), os.path.join(REPO, "src", "tracking")):
    if p not in sys.path:
        sys.path.insert(0, p)

import common as C  # noqa: E402
import early_call as E  # noqa: E402
import tt_camera  # noqa: E402
import tt_features as TF  # noqa: E402
import tt_physics as PH  # noqa: E402

WORK = os.environ.get("SPIN_WORK", os.path.join(C.WORK, "spin_tt"))
RES = os.environ.get("SPIN_RESULTS", os.path.join(REPO, "results", "spin", "tt"))
TRACK_RES = os.environ.get("TRACK_RESULTS", os.path.join(REPO, "results", "tracking"))
LABEL = "real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0)"
K50 = E.k_of(50)


def completeness(trk, t0, t_ref):
    n = t_ref - t0 + 1
    return sum(1 for f in range(t0, t_ref + 1) if f in trk) / max(n, 1)


def margin(trk, t0, t_ref):
    """Smallest distance (px) of the flight's track points to the image border."""
    uv = np.array([trk[f] for f in range(t0, t_ref + 1) if f in trk], float)
    if len(uv) == 0:
        return 0.0
    return float(min(uv[:, 0].min(), 1919 - uv[:, 0].max(), uv[:, 1].min(), 1079 - uv[:, 1].max()))


def online_fits(cam, frames, uv, d, dec_frames, anchor, t_s):
    """Same loop as tt_features.online_features (spin model), returning the fit objects too."""
    out = []
    warm, last_n, last_fit, n_dec, prob = None, -1, None, 0, None
    for t in dec_frames:
        m = frames <= t - TF.LAG
        nm = int(m.sum())
        if nm < TF.NMIN or frames[m][-1] - frames[m][0] < TF.NMIN - 1:
            out.append((t, None, None, None))
            continue
        if nm != last_n:
            prob = PH.FlightProblem(cam, frames[m], uv[m], d, anchor=anchor, spin=True, t_s=t_s)
            fresh = (warm is None) or (n_dec % TF.REINIT == 0)
            fit = PH.fit_prefix(prob, warm=warm, fresh=fresh)
            n_dec += 1
            last_n, last_fit = nm, fit
            if fit is not None:
                warm = fit.theta
        fit = last_fit
        if fit is None:
            out.append((t, None, prob, None))
            continue
        try:
            feats = PH.predict(prob, fit, int(t - TF.LAG - t_s), prefix="ph_")
        except Exception:
            feats = None
        out.append((t, fit, prob, feats))
    return out


def trajectory(cam, fit, n_now, d, extra=150):
    """Mean-state trajectory from t_s to landing (or the end of the horizon), and the no-spin
    counterfactual from the state at n_now."""
    th = fit.theta[None]
    W = PH.spin_vectors(th)
    P, V = PH.integrate(th[:, :3], th[:, 3:6], W, n_now + extra)
    P = P[:, 0]
    Pn, _ = PH.integrate(P[n_now][None], V[n_now, 0][None], np.zeros((1, 3)), extra)
    Pn = np.concatenate([P[:n_now], Pn[:, 0]], 0)

    def cut(Q):
        z = Q[:, 2]
        k = np.flatnonzero((np.arange(len(Q)) > n_now) & (z <= PH.R_BALL))
        end = int(k[0]) + 1 if len(k) else len(Q)
        # also stop once the ball is well past the far end line
        far = np.flatnonzero((np.arange(len(Q)) > n_now) & (d * Q[:, 0] > PH.HALF_L + 1.2))
        if len(far):
            end = min(end, int(far[0]) + 1)
        return Q[:end]
    P, Pn = cut(P), cut(Pn)
    return P, Pn


def r3(a):
    return np.round(np.asarray(a, float), 4).tolist()


def pick(fl, per, feats, anchors, tracks, n, split="test"):
    rows = []
    for i, r in fl.iterrows():
        key = (r.video, int(r.f_net))
        g = feats[(feats.video == r.video) & (feats.f_net == r.f_net)]
        last = g[g.t == r.t_ref]
        at50 = g[g.t == r.t_ref - K50]
        a = anchors[(anchors.video == r.video) & (anchors.f_net == r.f_net)]
        p = per[(per.video == r.video) & (per.f_net == r.f_net)]
        if last.empty or at50.empty or p.empty:
            continue
        last, at50, p = last.iloc[0], at50.iloc[0], p.iloc[0]
        rows.append(dict(
            video=r.video, f_net=int(r.f_net), label=r.label, t0=int(r.t0), t_ref=int(r.t_ref),
            completeness=completeness(tracks[r.video], int(r.t0), int(r.t_ref)),
            rms_last=float(last.ph_rms_px), out_last=float(last.ph_out_frac), ok50=float(at50.ph_ok),
            top_last=float(last.ph_top), top_z_last=float(last.ph_top_z),
            anchor=str(a.anchor.iloc[0]) if not a.empty else "none",
            spin_called=bool(p.spin_online_call_any), frozen_called=bool(p.frozen_online_call_any),
            spin_lead=float(p.spin_first_call_lead_ms) if np.isfinite(p.spin_first_call_lead_ms) else np.nan,
            frozen_lead=float(p.frozen_first_call_lead_ms) if np.isfinite(p.frozen_first_call_lead_ms) else np.nan,
            n_frames=int(r.t_ref - r.t0 + 1), margin_px=margin(tracks[r.video], int(r.t0), int(r.t_ref))))
    R = pd.DataFrame(rows)
    aud_path = os.path.join(TRACK_RES, "test_flights_audited.csv")
    R["audit"] = ""
    if split == "test" and os.path.exists(aud_path):
        aud = pd.read_csv(aud_path)[["video", "f_net", "audit"]]
        R = R.drop(columns="audit").merge(aud, on=["video", "f_net"], how="left")
        R["audit"] = R.audit.fillna("")
    clear = R[(R.completeness >= 0.90) & (R.rms_last <= 2.5) & (R.out_last <= 0.15) & (R.ok50 == 1)
              & (R.margin_px >= 60)].copy()
    clear["gain"] = clear.spin_lead.fillna(0) - clear.frozen_lead.fillna(0)
    clear["clarity"] = clear.completeness - 0.05 * clear.rms_last + 0.002 * clear.n_frames
    miss = clear[(clear.label == "MISS") & (clear.audit == "") & (clear.spin_called | clear.frozen_called)]
    miss = miss.sort_values(["spin_called", "gain", "clarity"], ascending=False)
    chosen = list(miss.head(4).index)
    bnc = clear[(clear.label == "BOUNCE") & ~clear.spin_called & ~clear.frozen_called
                & (clear.top_last.abs() <= 150)].copy()
    bnc["conf"] = bnc.top_z_last.abs()
    top = bnc[bnc.top_last > 0].sort_values(["conf", "clarity"], ascending=False)
    back = bnc[bnc.top_last < 0].sort_values(["conf", "clarity"], ascending=False)
    for part in (top, back):
        if len(part):
            chosen.append(part.index[0])
    rest = clear.drop(index=chosen).sort_values("clarity", ascending=False)
    chosen += list(rest.index[:max(0, n - len(chosen))])
    return clear.loc[chosen[:n]], R


def video_frame(video, frame):
    import cv2
    cap = cv2.VideoCapture(os.path.join(C.OTTG, f"{video}.mp4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, img = cap.read()
    cap.release()
    return img[..., ::-1] if ok else None


def qa_still(path, rec, cam, img):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9.6, 5.4), dpi=110)
    if img is not None:
        ax.imshow(img)
    obs = np.array(rec["track_uv"], float)
    ax.plot(obs[:, 0], obs[:, 1], "o", ms=2.5, color="#ffd166", label="tracked ball (BlurBall)")
    styles = {"lead_50ms": ("#ef476f", "-", "fit at 50 ms lead -> predicted path"),
              "first_call": ("#06d6a0", "-", "fit at spin model's first call"),
              "t_ref": ("#118ab2", "-", "fit at t_ref (whole flight)")}
    for k, (c, ls, lab) in styles.items():
        tr = rec["trajectories"].get(k)
        if not tr:
            continue
        uv = np.array(tr["uv"], float)
        ax.plot(uv[:, 0], uv[:, 1], ls=ls, lw=1.6, color=c, label=f"{lab} ({tr['top_rpm']:+.0f} rpm top)")
        uvn = np.array(tr["uv_nospin"], float)
        ax.plot(uvn[:, 0], uvn[:, 1], ls=":", lw=1.2, color=c)
    ax.set_xlim(0, 1920)
    ax.set_ylim(1080, 0)
    ax.axis("off")
    ax.legend(loc="lower left", fontsize=7, framealpha=0.8)
    ax.set_title(f"{rec['video']} flight f_net={rec['f_net']} ({rec['label']}); dotted = same state, spin off\n"
                 f"{LABEL}", fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out", default=os.path.join(RES, "test", "showcase"))
    ap.add_argument("--no-stills", action="store_true")
    ap.add_argument("--split", default="test", choices=["test", "train"],
                    help="train = smoke test on the dev-stage outputs (LOGO OOF calls)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    fl_all = pd.read_csv(os.path.join(C.WORK, "flights.csv"))
    fl = fl_all[fl_all.split == a.split].reset_index(drop=True)
    per = pd.read_csv(os.path.join(RES, "test_flights_spin_vs_frozen.csv" if a.split == "test"
                                   else "train_flights_oof_spin_vs_frozen.csv"))
    feats = pd.read_pickle(os.path.join(WORK, f"feats_{a.split}.pkl"))
    anchors = pd.read_csv(os.path.join(WORK, f"anchors_{a.split}.csv"))
    vids = sorted(fl.video.unique())
    tracks = E.load_tracks(vids)
    cams, _ = tt_camera.cameras_all(vids, os.path.join(WORK, "cameras.json"))
    sel, R = pick(fl, per, feats, anchors, tracks, a.n, a.split)
    R.to_csv(os.path.join(a.out, "candidates.csv"), index=False)
    print(f"{len(R)} {a.split} flights scored, {len(sel)} chosen", flush=True)
    index = []
    for _, s in sel.iterrows():
        r = fl[(fl.video == s.video) & (fl.f_net == s.f_net)].iloc[0]
        trk = tracks[r.video]
        cam = cams[r.video]
        t0, t_ref, d = int(r.t0), int(r.t_ref), float(r.dir)
        anchor, ainfo = TF.find_anchor(trk, t0, d, cam)
        fr = np.array([f for f in range(t0, t_ref + 1) if f in trk], int)
        uv = np.array([trk[f] for f in fr], float)
        dec = list(range(t0 + TF.NMIN - 1 + TF.LAG, t_ref + 1))
        fits = online_fits(cam, fr, uv, d, dec, anchor, t0)
        g = feats[(feats.video == r.video) & (feats.f_net == r.f_net)].set_index("t")
        frames_out, max_dev = [], 0.0
        for t, fit, prob, f in fits:
            if fit is None or f is None:
                continue
            if t in g.index:
                max_dev = max(max_dev, abs(f["ph_top"] - g.loc[t, "ph_top"]), abs(f["ph_x_land"] - g.loc[t, "ph_x_land"])
                              if np.isfinite(f["ph_x_land"]) and np.isfinite(g.loc[t, "ph_x_land"]) else 0.0)
            frames_out.append(dict(
                t=int(t), lead_ms=round(1000 * (t_ref - t) / C.FPS, 1), n_points=int(f["ph_npts"]),
                rms_px=round(f["ph_rms_px"], 3),
                top_rps=round(f["ph_top"], 2), top_sd_rps=round(f["ph_top_sd"], 2),
                side_rps=round(f["ph_side"], 2), side_sd_rps=round(f["ph_side_sd"], 2),
                top_rpm=round(60 * f["ph_top"], 0), side_rpm=round(60 * f["ph_side"], 0),
                speed_mps=round(f["ph_speed"], 2), x_land_m=None if not np.isfinite(f["ph_x_land"]) else round(f["ph_x_land"], 3),
                x_land_nospin_m=None if not np.isfinite(f["ph_x_land_nospin"]) else round(f["ph_x_land_nospin"], 3),
                p_in=round(f["ph_p_in"], 3), p_long=round(f["ph_p_long"], 3), p_net=round(f["ph_p_net"], 3),
                p_wide=round(f["ph_p_wide"], 3)))
        byt = {t: (fit, prob) for (t, fit, prob, f) in fits if fit is not None and f is not None}
        want = {"lead_50ms": t_ref - K50, "t_ref": t_ref}
        if np.isfinite(s.spin_lead):
            want["first_call"] = t_ref - int(round(s.spin_lead * C.FPS / 1000.0))
        trajs = {}
        for name, t in want.items():
            if t not in byt:
                continue
            fit, prob = byt[t]
            n_now = int(t - TF.LAG - t0)
            P, Pn = trajectory(cam, fit, n_now, d)
            trajs[name] = dict(
                decision_frame=int(t), last_track_frame_used=int(t - TF.LAG), lead_ms=round(1000 * (t_ref - t) / C.FPS, 1),
                top_rps=round(float(fit.theta[6]), 2), side_rps=round(float(fit.theta[7] * d), 2),
                top_rpm=round(60 * float(fit.theta[6]), 0), side_rpm=round(60 * float(fit.theta[7] * d), 0),
                top_sd_rps=round(float(np.sqrt(max(fit.cov[6, 6], 0))), 2),
                first_frame=t0, xyz=r3(P), uv=np.round(cam.project(P), 1).tolist(),
                xyz_nospin=r3(Pn), uv_nospin=np.round(cam.project(Pn), 1).tolist())
        rec = dict(
            footage=LABEL, video=r.video, f_net=int(r.f_net), label=r.label,
            miss_type=None if pd.isna(r.miss_type) else r.miss_type, dir=d, t0=t0, t_ref=t_ref, fps=C.FPS,
            anchor=ainfo, camera=cam.to_dict(),
            table_corners_uv=np.round(cam.project(np.c_[tt_camera.CORNERS_W, np.zeros(4)]), 1).tolist(),
            track_frames=fr.tolist(), track_uv=np.round(uv, 1).tolist(),
            spin_model_first_call_lead_ms=None if not np.isfinite(s.spin_lead) else s.spin_lead,
            frozen_model_first_call_lead_ms=None if not np.isfinite(s.frozen_lead) else s.frozen_lead,
            selection=dict(completeness=round(s.completeness, 3), rms_last_px=round(s.rms_last, 3),
                           outlier_frac_last=round(s.out_last, 3), audit=s.audit or None),
            reproduction_max_abs_dev_vs_test_run=round(float(max_dev), 6),
            decision_frames=frames_out, trajectories=trajs,
            conventions="world: X along the table (+ towards image right), Y away from camera, Z up, m; "
                        "top_rps > 0 topspin, < 0 backspin; side_rps > 0 curves to the hitter's left; "
                        "uv = 1920x1080 pixels; trajectories start at t0 (first_frame), one sample per frame")
        name = f"{r.video}_{int(r.f_net)}"
        json.dump(rec, open(os.path.join(a.out, f"{name}.json"), "w"))
        if not a.no_stills:
            qa_still(os.path.join(a.out, f"{name}.png"), rec, cam, video_frame(r.video, t_ref))
        index.append(dict(file=f"{name}.json", video=r.video, f_net=int(r.f_net), label=r.label,
                          spin_lead_ms=rec["spin_model_first_call_lead_ms"],
                          frozen_lead_ms=rec["frozen_model_first_call_lead_ms"],
                          top_rpm_t_ref=trajs.get("t_ref", {}).get("top_rpm"),
                          side_rpm_t_ref=trajs.get("t_ref", {}).get("side_rpm"),
                          top_rpm_50ms=trajs.get("lead_50ms", {}).get("top_rpm"),
                          reproduction_max_abs_dev=rec["reproduction_max_abs_dev_vs_test_run"]))
        print(json.dumps(index[-1]), flush=True)
    json.dump(dict(footage=LABEL, note="post-hoc display selection; no metric computed", flights=index),
              open(os.path.join(a.out, "index.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
