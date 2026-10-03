"""Tennis early in/out calls from broadcast video (TrackNet dataset), end to end.

Stages
  prep   : court camera per clip, effective frame interval per game, labelled flights (+ GT)
  detacc : TrackNet detector accuracy vs labels (train / test games)
  tune   : choose fitter hyper-parameters on TRAIN games only (games 1-7)
  final  : frozen config -> predictions for all flights and decision frames; thresholds from
           train, evaluated ONCE on test games 8-10; summary.json + figures

Usage
  python run_eval.py --labels DATA/Dataset --detect WORK/detect --work WORK/eval \
      --out results/tennis_tracking --stage prep tune final
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import os
import pickle
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from events import TEST_GAMES, TRAIN_GAMES, build_flights, clip_camera, load_labels, toss_gravity  # noqa: E402
from fit3d import Fitter  # noqa: E402
from geometry import BALL_R, ground_xy, signed_out_distance  # noqa: E402

LEADS_MS = [0, 33, 67, 100, 150, 200, 300]
NMIN = 4                      # min. observations after the hit before any prediction
PREC = 0.95
HAWKEYE_SD_CM = {25: 0.72, 100: 2.37, 200: 5.76, 300: 10.66}   # results/hawkeye_tennis_calls.csv

# ----------------------------------------------------------------------------------------- prep


def prep(a):
    labels = load_labels(a.labels)
    cams = {}
    for f in sorted(glob.glob(os.path.join(a.detect, "*.npz"))):
        g, c = os.path.basename(f)[:-4].split("_")
        z = np.load(f)
        cams[(int(g[4:]), c)] = clip_camera(z["court_kps"])
    labels = {k: v for k, v in labels.items() if k in cams}
    # effective frame interval per game from the serve toss (no outcome information used)
    tg = toss_gravity(labels, cams)
    ok = tg[(tg.g_app > 5) & (tg.g_app < 25) & (tg.z_max > 2.3) & (tg.z_max < 4.5)]
    fps = {}
    for g in range(1, 11):
        v = ok[ok.game == g].g_app
        raw = 30.0 * np.sqrt(9.81 / v.median()) if len(v) else np.nan
        fps[g] = {"n_toss": int(len(v)), "g_app_at_30fps": float(v.median()) if len(v) else None,
                  "fps_raw": None if np.isnan(raw) else float(raw),
                  "fps": 25.0 if (np.isnan(raw) or abs(raw - 25) < abs(raw - 30)) else 30.0}
    fl = build_flights(labels, cams)
    fl["fps"] = fl.game.map(lambda g: fps[g]["fps"])
    fl["flight_ms"] = 1000 * (fl.tb - fl.hit_end) / fl.fps
    camq = pd.DataFrame([dict(game=k[0], clip=k[1], f=v["cam"].f, Cx=v["cam"].C[0], Cy=v["cam"].C[1],
                              Cz=v["cam"].C[2], cam_rms=v["cam_rms"], spread_px=v["spread_px"])
                         for k, v in cams.items() if v is not None])
    # clips whose court calibration is unreliable (camera moving or keypoints off) are dropped
    bad = camq[(camq.cam_rms > 5.0) | (camq.spread_px > 3.0)][["game", "clip"]]
    badset = set(map(tuple, bad.values))
    fl["cam_ok"] = [(g, c) not in badset for g, c in zip(fl.game, fl["clip"])]
    os.makedirs(a.work, exist_ok=True)
    with open(os.path.join(a.work, "prep.pkl"), "wb") as f:
        pickle.dump({"labels": labels, "cams": cams, "fps": fps, "flights": fl, "camq": camq, "toss": tg}, f)
    print(fl.groupby("split").agg(n=("is_out", "size"), outs=("is_out", "sum"), serves=("serve", "sum"),
                                  cam_ok=("cam_ok", "sum")))
    print("fps", {g: (v["fps"], v["fps_raw"] and round(v["fps_raw"], 1), v["n_toss"]) for g, v in fps.items()})
    return


def load_prep(a):
    with open(os.path.join(a.work, "prep.pkl"), "rb") as f:
        return pickle.load(f)


# ------------------------------------------------------------------------------------- tracks


def detector_tracks(detect_dir):
    out = {}
    for f in sorted(glob.glob(os.path.join(detect_dir, "*.npz"))):
        g, c = os.path.basename(f)[:-4].split("_")
        out[(int(g[4:]), c)] = np.load(f)["ball_xy"]
    return out


def detacc(a):
    P = load_prep(a)
    det = detector_tracks(a.detect)
    rows = []
    for (g, c), L in P["labels"].items():
        d = det[(g, c)]
        vis = L["vis"]
        has_lab = np.isfinite(L["uv"][:, 0])
        has_det = np.isfinite(d[:, 0])
        err = np.hypot(*(d - L["uv"]).T)
        for k in range(2, len(vis)):
            rows.append((g, vis[k], has_lab[k], has_det[k], err[k]))
    D = pd.DataFrame(rows, columns=["game", "vis", "lab", "det", "err"])
    res = {}
    for name, games in (("train_games_1_7", TRAIN_GAMES), ("test_games_8_10", TEST_GAMES)):
        x = D[D.game.isin(games)]
        tp = ((x.lab & x.det) & (x.err < 5)).sum()
        fp = (x.det & (~x.lab | (x.err >= 5))).sum()
        fn = (x.lab & (~x.det | (x.err >= 5))).sum()
        both = x[x.lab & x.det]
        res[name] = {"frames": int(len(x)), "precision_5px": float(tp / max(tp + fp, 1)),
                     "recall_5px": float(tp / max(tp + fn, 1)),
                     "median_err_px_when_both": float(both.err.median()),
                     "p90_err_px_when_both": float(both.err.quantile(0.9)),
                     "share_err_gt_20px": float((both.err > 20).mean())}
    res["note"] = ("TrackNet weights (yastrebksv/TrackNet) were trained on a random 70% of FRAMES from all 10 "
                   "games (gt_gen.py create_gt_labels), so games 8-10 are not unseen by the detector; "
                   "these are in-distribution numbers, an upper bound for new broadcasts.")
    with open(os.path.join(a.work, "detacc.json"), "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1))
    return res


# -------------------------------------------------------------------------------- predictions

_G = {}


def _init(P, tracks, cfg):
    _G.update(P=P, tracks=tracks, cfg=cfg)


def _predict_flight(i, all_frames=False, leads=LEADS_MS):
    P, tracks, cfg = _G["P"], _G["tracks"], _G["cfg"]
    r = P["flights"].loc[i]
    cam, H = P["cams"][(r.game, r["clip"])]["cam"], P["cams"][(r.game, r["clip"])]["H"]
    uv = tracks[(r.game, r["clip"])]
    F = r.fps * cfg.get("fps_mult", 1.0)          # frame rate used for leads (ms) and physics
    fitter = Fitter(**{k: v for k, v in cfg.items() if k != "skip"})
    k_first = r.hit_end + cfg.get("skip", 1)
    if all_frames:
        kdecs = list(range(k_first + NMIN - 1, int(np.floor(r.tb + 1e-6)) + 1))
    else:
        kdecs = sorted({int(np.floor(r.tb - L * F / 1000.0 + 1e-6)) for L in leads})
    out = []
    for kd in kdecs:
        fr = np.arange(k_first, kd + 1)
        fr = fr[np.isfinite(uv[fr, 0])] if len(fr) else fr
        lead = 1000.0 * (r.tb - kd) / F
        rec = dict(fid=i, kdec=kd, lead_ms=lead, n_obs=len(fr))
        if len(fr) >= NMIN:
            res = fitter.fit(cam, fr - r.hit_end, uv[fr], bool(r.serve), r.fps,
                             uv_hit=uv[r.hit_end] if np.isfinite(uv[r.hit_end, 0]) else None)
            if res is not None and np.isfinite(res["land"][0]):
                lx, ly, lt = res["land"]
                # express the 3D landing in the homography's court frame (camera rms can be a few px)
                uvl = cam.project(np.array([[lx, ly, BALL_R]]))
                lx, ly = ground_xy(H, cam, uvl)[0]
                d_hat = float(signed_out_distance(np.array([[lx, ly]]), np.array([bool(r.serve)]),
                                                  np.array([r.srv_sx]), np.array([r.srv_sy]))[0])
                rec.update(x_hat=lx, y_hat=ly, t_land_err_ms=1000 * (lt + r.hit_end - r.tb) / F,
                           d_hat=d_hat, rms_px=res["rms_px"], c=res["theta"][6], z0=res["theta"][2])
        out.append(rec)
    return out


def predict(P, tracks, cfg, fids, all_frames=False, procs=10):
    with Pool(procs, initializer=_init, initargs=(P, tracks, cfg)) as pool:
        parts = pool.starmap(_predict_flight, [(i, all_frames) for i in fids])
    pr = pd.DataFrame([x for p in parts for x in p])
    fl = P["flights"]
    pr = pr.join(fl[["game", "split", "x_b", "y_b", "d_true", "is_out", "serve", "fps"]], on="fid")
    pr["err_cm"] = 100 * np.hypot(pr.x_hat - pr.x_b, pr.y_hat - pr.y_b)
    pr["ex_cm"] = 100 * (pr.x_hat - pr.x_b)
    pr["ey_cm"] = 100 * (pr.y_hat - pr.y_b)
    return pr


def at_leads(pr, leads=LEADS_MS):
    """For each flight and fixed lead L: the decision frame floor(tb - L) row."""
    rows = []
    for L in leads:
        # decision frame = the latest frame with lead >= L
        x = pr[pr.lead_ms >= L - 1e-6].sort_values("lead_ms").groupby("fid").head(1).copy()
        x["lead"] = L
        rows.append(x)
    return pd.concat(rows, ignore_index=True)


def err_table(x):
    g = x.groupby("lead")
    t = g.agg(n_flights=("fid", "nunique"), n_pred=("err_cm", lambda s: int(s.notna().sum())),
              median_cm=("err_cm", "median"), p75_cm=("err_cm", lambda s: s.quantile(0.75)),
              p90_cm=("err_cm", lambda s: s.quantile(0.9)),
              sd_x_cm=("ex_cm", "std"), sd_y_cm=("ey_cm", "std"),
              robust_sd_signed_cm=("dd", lambda s: 1.4826 * np.nanmedian(np.abs(s - np.nanmedian(s)))),
              sd_signed_cm=("dd", "std"))
    return t.reset_index()


# ------------------------------------------------------------------------------------- tuning

GRID = {
    "sigma_px": [2.0, 4.0],
    "hit_sigma": [None, 4.0],
    "kd_mult": [1.0, 1.5],
    "z_rally": [(1.0, 0.3), (1.0, 0.8)],
}


def tune(a):
    P = load_prep(a)
    fl = P["flights"]
    fids = fl.index[(fl.split == "train") & fl.cam_ok].tolist()
    tracks = {k: v["uv"] for k, v in P["labels"].items()}
    rows = []
    keys = list(GRID)
    for vals in itertools.product(*[GRID[k] for k in keys]):
        cfg = dict(zip(keys, vals))
        t0 = time.time()
        pr = predict(P, tracks, cfg, fids, procs=a.procs)
        x = at_leads(pr)
        x["dd"] = 100 * (x.d_hat - x.d_true)
        t = err_table(x)
        score = float(np.mean(0.5 * (t.median_cm + t.p75_cm)))
        rows.append({**{k: str(v) for k, v in cfg.items()}, "score": score,
                     **{f"med_{L}": m for L, m in zip(t.lead, t.median_cm)},
                     "cover": float(x.err_cm.notna().mean()), "sec": time.time() - t0})
        print(rows[-1], flush=True)
    T = pd.DataFrame(rows).sort_values("score")
    T.to_csv(os.path.join(a.out, "tuning_train_only.csv"), index=False)
    best = T.iloc[0]
    cfg = {k: eval(best[k]) for k in keys}
    with open(os.path.join(a.work, "best_cfg.json"), "w") as f:
        json.dump(cfg, f)
    print("best", cfg, best.score)


# -------------------------------------------------------------------------------------- calls


def choose_tau(d_hat, y, target=PREC, min_calls=3):
    """Smallest threshold whose precision is >= target and stays >= target for every higher
    threshold with >= min_calls calls. None if impossible."""
    cand = np.unique(np.round(d_hat[np.isfinite(d_hat)], 3))
    ok_from = None
    for t in cand[::-1]:
        sel = d_hat > t
        if sel.sum() < min_calls:
            continue
        p = y[sel].mean()
        if p >= target:
            ok_from = t
        else:
            break
    return ok_from


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (float(c - h), float(c + h))


def calls_table(x, taus):
    rows = []
    for L, d in x.groupby("lead"):
        tau = taus.get(L)
        y = d.is_out.values.astype(bool)
        dh = d.d_hat.values
        called = np.isfinite(dh) & (dh > tau) if tau is not None else np.zeros(len(d), bool)
        tp, fp = int((called & y).sum()), int((called & ~y).sum())
        rows.append(dict(lead_ms=L, tau_m=tau, n=len(d), n_out=int(y.sum()), calls=int(called.sum()), tp=tp, fp=fp,
                         precision=tp / (tp + fp) if tp + fp else np.nan,
                         precision_ci95=wilson(tp, tp + fp), recall=tp / max(y.sum(), 1)))
    return pd.DataFrame(rows)


def online_calls(pr, tau):
    """First decision frame (going forward in time) where d_hat > tau: the call is made there.
    Only frames after the ball has crossed the net (its pixel ray at 1 m height is on the
    receiver's half; `hy` < 0 in the mirrored frame) are eligible: a causal rule, no lead used."""
    out = {}
    for fid, d in pr.groupby("fid"):
        d = d[(d.hy < 0) & np.isfinite(d.d_hat)].sort_values("kdec")
        hit = d[d.d_hat > tau]
        out[fid] = float(hit.lead_ms.iloc[0]) if len(hit) else np.nan
    return pd.Series(out)


# -------------------------------------------------------------------------------------- final


PREDICTORS = ("ground", "phys3d", "learned")


def combined_table(P, pr, X):
    """(fid, kdec) rows with the landing estimate of every predictor and its signed out-distance."""
    from learn import fit_predict
    X = fit_predict(X)
    T = X[["fid", "kdec", "lead_ms", "n_obs", "game", "split", "x_b", "y_b", "d_true", "is_out", "serve_flag",
           "srv_sx", "srv_sy", "mirror", "gx", "gy", "hy", "lx", "ly"]].copy()
    T = T.merge(pr[["fid", "kdec", "x_hat", "y_hat"]], on=["fid", "kdec"], how="left")
    est = {"ground": (T.gx * T.mirror, T.gy * T.mirror), "phys3d": (T.x_hat, T.y_hat), "learned": (T.lx, T.ly)}
    for k, (x, y) in est.items():
        T[f"{k}_x"], T[f"{k}_y"] = x.values, y.values
        T[f"{k}_err_cm"] = 100 * np.hypot(x - T.x_b, y - T.y_b)
        T[f"{k}_d"] = signed_out_distance(np.c_[x, y], T.serve_flag.values.astype(bool), T.srv_sx.values,
                                          T.srv_sy.values)
    return T


def err_summary(x, k):
    g = x.groupby("lead")
    dd = 100 * (x[f"{k}_d"] - x.d_true)
    x = x.assign(dd=dd)
    t = x.groupby("lead").agg(n=("fid", "size"), median_cm=(f"{k}_err_cm", "median"),
                              p75_cm=(f"{k}_err_cm", lambda s: s.quantile(0.75)),
                              p90_cm=(f"{k}_err_cm", lambda s: s.quantile(0.9)),
                              sd_signed_out_dist_cm=("dd", "std"),
                              robust_sd_signed_out_dist_cm=("dd", lambda s: 1.4826 * np.nanmedian(np.abs(s - s.median()))))
    t["within_50cm"] = g[f"{k}_err_cm"].apply(lambda s: float((s < 50).mean())).values
    t["within_100cm"] = g[f"{k}_err_cm"].apply(lambda s: float((s < 100).mean())).values
    for q in (5, 50, 95):
        t[f"signed_out_dist_err_p{q}_cm"] = x.groupby("lead").dd.apply(lambda s: float(np.nanpercentile(s, q))).values
    return t.reset_index()


def margin_calls(x, k):
    """Margin rule: tau(L) = 95th percentile of (d_hat - d_true) over ALL train bounces at lead L
    (uses every bounce, not just the few outs). Call OUT if d_hat > tau. On test: false-call rate
    among IN balls, and precision/recall of the calls."""
    rows = []
    xt = x[x.split == "train"]
    for L, d in x.groupby("lead"):
        e = (xt[xt.lead == L][f"{k}_d"] - xt[xt.lead == L].d_true).dropna()
        tau = float(np.percentile(e, 95))
        te = d[(d.split == "test") & d[f"{k}_d"].notna()]
        y = te.is_out.values.astype(bool)
        c = te[f"{k}_d"].values > tau
        tp, fp = int((c & y).sum()), int((c & ~y).sum())
        rows.append(dict(lead_ms=L, tau_m=tau, test_n=len(te), test_n_out=int(y.sum()), calls=int(c.sum()), tp=tp,
                         fp=fp, false_call_rate_on_ins=fp / max(int((~y).sum()), 1),
                         precision=tp / (tp + fp) if tp + fp else None, precision_ci95=wilson(tp, tp + fp),
                         recall=tp / max(int(y.sum()), 1),
                         test_err_exceeds_tau=float(((te[f"{k}_d"] - te.d_true) > tau).mean())))
    return rows


def final(a):
    from learn import features
    P = load_prep(a)
    fl = P["flights"]
    with open(os.path.join(a.work, "best_cfg.json")) as f:
        cfg = json.load(f)
    if isinstance(cfg.get("z_rally"), list):
        cfg["z_rally"] = tuple(cfg["z_rally"])
    use = fl.index[fl.cam_ok].tolist()
    sources = {"labels": {k: v["uv"] for k, v in P["labels"].items()}, "tracknet": detector_tracks(a.detect)}
    summary = {}
    tables = {}
    for src, tracks in sources.items():
        cache = os.path.join(a.work, f"pred_{src}.pkl")
        if os.path.exists(cache) and not a.redo:
            pr = pd.read_pickle(cache)
        else:
            pr = predict(P, tracks, cfg, use, all_frames=True, procs=a.procs)
            pr.to_pickle(cache)
        X = features(P, tracks, pr, skip=cfg.get("skip", 1))
        T = combined_table(P, pr, X)
        T.to_pickle(os.path.join(a.work, f"table_{src}.pkl"))
        tables[src] = T
        x = at_leads(T)
        out = {"landing_error": {}, "calls": {}}
        # primary predictor: lowest mean (over leads) median error on TRAIN (out-of-fold for learned)
        xt = x[x.split == "train"]
        train_score = {k: float(xt.groupby("lead")[f"{k}_err_cm"].median().mean()) for k in PREDICTORS}
        primary = min(train_score, key=train_score.get)
        out["train_mean_median_err_cm"] = train_score
        out["primary_predictor_chosen_on_train"] = primary
        for k in PREDICTORS:
            out["landing_error"][k] = {sp: err_summary(x[x.split == sp], k).to_dict(orient="records")
                                       for sp in ("train", "test")}
            taus = {L: choose_tau(d[f"{k}_d"].values, d.is_out.values.astype(bool)) for L, d in xt.groupby("lead")}
            cx = x.rename(columns={f"{k}_d": "d_hat"})
            out["calls"][k] = {"tau_m_by_lead_from_train": {str(L): t for L, t in taus.items()},
                               "train": calls_table(cx[cx.split == "train"], taus).to_dict(orient="records"),
                               "test": calls_table(cx[cx.split == "test"], taus).to_dict(orient="records")}
            # online rule (first decision frame with d_hat > tau), one tau chosen on train
            on = {"tau_m_from_train": None}
            pt = T.rename(columns={f"{k}_d": "d_hat"})
            for t in np.arange(0.0, 4.01, 0.05):
                lead = online_calls(pt[pt.split == "train"], t)
                y = fl.loc[lead.index, "is_out"].values.astype(bool)
                c = lead.notna().values
                if c.sum() >= 3 and y[c].mean() >= PREC:
                    on["tau_m_from_train"] = float(t)
                    break
            if on["tau_m_from_train"] is not None:
                for sp in ("train", "test"):
                    lead = online_calls(pt[pt.split == sp], on["tau_m_from_train"])
                    y = fl.loc[lead.index, "is_out"].values.astype(bool)
                    c = lead.notna().values
                    tp, fp = int((c & y).sum()), int((c & ~y).sum())
                    Ltp = lead.values[c & y]
                    on[sp] = {"n_flights": int(len(lead)), "n_out": int(y.sum()), "calls": int(c.sum()), "tp": tp,
                              "fp": fp, "precision": tp / (tp + fp) if tp + fp else None,
                              "precision_ci95": wilson(tp, tp + fp), "recall": tp / max(int(y.sum()), 1),
                              "call_lead_ms_of_true_outs": None if not len(Ltp) else
                              {"median": float(np.median(Ltp)), "p10": float(np.percentile(Ltp, 10)),
                               "p90": float(np.percentile(Ltp, 90)), "n": int(len(Ltp))}}
            out["calls"][k]["online_first_call"] = on
            out["calls"][k]["margin_rule_test"] = margin_calls(x, k)
            out["calls"][k]["margin_rule_first_call"] = first_call_leads(x, k)
        summary[src] = out
    with open(os.path.join(a.work, "final_partial.json"), "w") as f:
        json.dump({"config": cfg, "sources": summary}, f, indent=1, default=float)
    write_summary(a, P, cfg, summary)
    cols = ["game", "clip", "split", "hit", "hit_end", "bounce", "tb", "gt_how", "u_b", "v_b", "x_b", "y_b", "serve",
            "d_true", "is_out", "fps", "flight_ms", "cam_ok"]
    fl[cols].round(4).to_csv(os.path.join(a.out, "flights.csv"), index_label="fid")
    parts = []
    for src, T in tables.items():
        x = at_leads(T)
        keep = ["fid", "lead", "lead_ms", "n_obs", "split", "is_out", "d_true"] + \
               [f"{k}_{c}" for k in PREDICTORS for c in ("x", "y", "d", "err_cm")]
        parts.append(x[keep].assign(source=src))
    pd.concat(parts).round(4).to_csv(os.path.join(a.out, "predictions_at_leads.csv"), index=False)
    import plots
    plots.lead_vs_error(tables, summary, os.path.join(a.out, "lead_vs_error.png"))
    plots.example(P, tables["labels"], sources, os.path.join(a.out, "example_trajectory.png"))


def first_call_leads(x, k):
    """Per true-out bounce: the largest fixed lead at which the margin rule calls it OUT (calls at
    every lead use that lead's train tau). Reported for test, with each lead's test precision so
    the reader can see where calls stop being reliable."""
    xt = x[x.split == "train"]
    taus = {}
    for L in LEADS_MS:
        e = (xt[xt.lead == L][f"{k}_d"] - xt[xt.lead == L].d_true).dropna()
        taus[L] = float(np.percentile(e, 95))
    res = {}
    for sp in ("train", "test"):
        d = x[(x.split == sp)].copy()
        d["called"] = d[f"{k}_d"] > d.lead.map(taus)
        outs = d[d.is_out]
        lead = outs[outs.called].groupby("fid").lead.max()
        n_out = int(outs.fid.nunique())
        v = lead.values
        res[sp] = {"n_out": n_out, "n_called_at_some_lead": int(len(v)),
                   "first_call_lead_ms": None if not len(v) else
                   {"median": float(np.median(v)), "p10": float(np.percentile(v, 10)), "p90": float(np.percentile(v, 90))},
                   "per_lead_precision": {str(L): (lambda g: None if g.called.sum() == 0 else
                                                   float((g.called & g.is_out).sum() / g.called.sum()))(d[d.lead == L])
                                          for L in LEADS_MS},
                   "per_lead_calls": {str(L): int(d[d.lead == L].called.sum()) for L in LEADS_MS}}
    # restricted version: only leads where the rule reached >= 95% precision with >= 3 calls on TRAIN
    tp_, tc_ = res["train"]["per_lead_precision"], res["train"]["per_lead_calls"]
    ok = [L for L in LEADS_MS if tp_[str(L)] is not None and tp_[str(L)] >= PREC and tc_[str(L)] >= 3]
    for sp in ("train", "test"):
        d = x[(x.split == sp) & x.lead.isin(ok)].copy()
        d["called"] = d[f"{k}_d"] > d.lead.map(taus)
        v = d[d.is_out & d.called].groupby("fid").lead.max().values
        res[sp]["first_call_lead_ms_at_train_95pct_leads"] = {
            "leads_allowed": ok, "n_called": int(len(v)),
            "median": float(np.median(v)) if len(v) else None,
            "p10": float(np.percentile(v, 10)) if len(v) else None,
            "p90": float(np.percentile(v, 90)) if len(v) else None}
    return res


def headline(summary):
    """Compact read-out (test games unless stated). All thresholds/choices come from train."""
    H = {}
    for src in summary:
        R = summary[src]
        le = {k: {int(r["lead"]): round(r["median_cm"], 1) for r in R["landing_error"][k]["test"]} for k in PREDICTORS}
        p95 = {k: {int(r["lead"]): round(r["signed_out_dist_err_p95_cm"], 1) for r in R["landing_error"][k]["test"]}
               for k in PREDICTORS}
        calls = {}
        for k in PREDICTORS:
            fc = R["calls"][k]["margin_rule_first_call"]
            tr_prec = fc["train"]["per_lead_precision"]
            tr_calls = fc["train"]["per_lead_calls"]
            ok_leads = [int(L) for L, p in tr_prec.items() if p is not None and p >= PREC and tr_calls[L] >= 3]
            mr = {int(r["lead_ms"]): r for r in R["calls"][k]["margin_rule_test"]}
            calls[k] = {
                "max_lead_ms_with_train_precision_ge_95_and_3plus_calls": max(ok_leads) if ok_leads else None,
                "test_by_lead": {L: {"calls": mr[L]["calls"], "tp": mr[L]["tp"], "fp": mr[L]["fp"],
                                     "precision": mr[L]["precision"], "precision_ci95": mr[L]["precision_ci95"],
                                     "recall": mr[L]["recall"], "tau_cm": round(100 * mr[L]["tau_m"], 1)}
                                 for L in sorted(mr)},
                "first_call_lead_ms_test_true_outs_any_lead": fc["test"]["first_call_lead_ms"],
                "first_call_lead_ms_test_true_outs_at_train_95pct_leads": fc["test"]["first_call_lead_ms_at_train_95pct_leads"],
                "snapshot_rule_tau_from_train": R["calls"][k]["tau_m_by_lead_from_train"],
                "online_rule_tau_from_train": R["calls"][k]["online_first_call"]["tau_m_from_train"]}
        H[src] = {"primary_predictor_by_train_landing_error": R["primary_predictor_chosen_on_train"],
                  "median_landing_err_cm": le, "callable_margin_p95_signed_err_cm": p95,
                  "hawkeye_callable_margin_1.645sd_cm": {L: round(1.645 * v, 1) for L, v in HAWKEYE_SD_CM.items()},
                  "out_calls_margin_rule": calls}
    return H


def comparison(summary):
    """Same metric as results/hawkeye_tennis_calls.csv pred_err_sd_cm: SD of the predicted signed
    out-distance error. Broadcast: robust SD (1.4826 MAD) on TEST, primary predictor."""
    out = {}
    for src in summary:
        k = summary[src]["primary_predictor_chosen_on_train"]
        rows = {r["lead"]: r for r in summary[src]["landing_error"][k]["test"]}
        tab = []
        for L in LEADS_MS:
            r = rows.get(L)
            if r is None:
                continue
            hk = HAWKEYE_SD_CM.get(L if L != 33 else 25)
            tab.append({"lead_ms": L, "hawkeye_lead_ms": (L if L != 33 else 25) if hk else None,
                        "hawkeye_sd_cm": hk, "broadcast_robust_sd_cm": r["robust_sd_signed_out_dist_cm"],
                        "broadcast_sd_cm": r["sd_signed_out_dist_cm"],
                        "broadcast_median_landing_err_cm": r["median_cm"], "broadcast_p90_landing_err_cm": r["p90_cm"],
                        "ratio_robust_sd_vs_hawkeye": (r["robust_sd_signed_out_dist_cm"] / hk) if hk else None})
        out[src] = {"predictor": k, "table": tab}
    return out


def write_summary(a, P, cfg, summary):
    fl = P["flights"]
    det = json.load(open(os.path.join(a.work, "detacc.json")))
    use = fl[fl.cam_ok]
    S = {
        "question": "How many ms before the bounce can a broadcast (single camera, 25-30 fps) ball track call a "
                    "tennis ball IN/OUT, and how far off is its landing-point prediction, vs Hawk-Eye class?",
        "dataset": {"name": "TrackNet tennis dataset (Huang et al. 2019, NCTU)",
                    "frames_labelled": 19835, "matches": 10, "clips": int(len(P["labels"])),
                    "resolution": "1280x720", "nominal_fps": 30,
                    "effective_fps_from_serve_toss": {str(g): v for g, v in P["fps"].items()},
                    "split": {"train_tuning": TRAIN_GAMES, "test_once": TEST_GAMES}},
        "ground_truth": "labelled bounce frames (status=2); sub-frame bounce point from the V-shaped labelled image "
                        "track (+-3 frames), back-projected to z = ball radius with the court camera. Serves (first "
                        "hit of each clip) judged against the diagonal service box, rally balls against singles lines.",
        "court_calibration": "yastrebksv/TennisCourtDetector keypoints per frame -> per-clip median -> homography "
                             "(used for all ground-plane mapping) + pinhole camera (f, R, t; principal point fixed; "
                             "used for the 3D fit and the ball-radius correction) via cv2.calibrateCamera. "
                             f"Clips with camera rms > 5 px or keypoint drift > 3 px (moving camera) dropped: "
                             f"{int((~fl.cam_ok).sum())} of {len(fl)} flights.",
        "detector_accuracy_vs_labels": det,
        "n_bounces_evaluated": {sp: int((use.split == sp).sum()) for sp in ("train", "test")},
        "out_base_rate": {sp: float(use[use.split == sp].is_out.mean()) for sp in ("train", "test")},
        "n_out": {sp: int(use[use.split == sp].is_out.sum()) for sp in ("train", "test")},
        "n_serves": {sp: int(use[use.split == sp].serve.sum()) for sp in ("train", "test")},
        "fitter_config_chosen_on_train": {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.items()},
        "hawkeye_class_physics_mc": {"source": "results/hawkeye_tennis_calls.csv (340 fps, 3.6 mm noise)",
                                     "landing_err_sd_cm_by_lead_ms": HAWKEYE_SD_CM},
        "headline": headline(summary),
        "comparison_to_hawkeye": comparison(summary),
        "results": summary,
    }
    with open(os.path.join(a.out, "summary.json"), "w") as f:
        json.dump(S, f, indent=1, default=float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--detect", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", nargs="+", default=["prep", "detacc", "tune", "final"])
    ap.add_argument("--procs", type=int, default=10)
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for s in a.stage:
        {"prep": prep, "detacc": detacc, "tune": tune, "final": final}[s](a)


if __name__ == "__main__":
    main()
