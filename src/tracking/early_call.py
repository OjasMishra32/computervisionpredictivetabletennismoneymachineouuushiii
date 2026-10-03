"""H3 early call: from the trajectory prefix, call MISS (out / net) vs TABLE BOUNCE before contact.

Decision at frame t uses only track points in [t0, t - LAG] (LAG = 2 frames: the detector
averages heatmaps of the triplets that contain a frame, so frame t's position needs frame t+2).

Features (all in table-normalised image coordinates so that different cameras are comparable:
u = position along the table in table lengths, 0 at the hitter's end line, 0.5 at the net, 1 at
the target end line; w = height above the table mid-line in table lengths):
  a robust quadratic fit u(tau), w(tau) to the last <= 30 prefix points, then
  - predicted landing position u where the extrapolated arc reaches the far-edge, mid and
    near-edge table level (the true bounce level lies between them, depending on depth),
    measured relative to the end line (> 0 = beyond the end = long)
  - predicted height at the net plane (if the net is still ahead), whether the net is passed
  - current u, w, velocities, vertical acceleration, fit residual, #points, time since t0
Models (chosen on game_1..5 only, leave-one-game-out CV):
  'physics'  : logistic regression on the 3 landing features + net-height + passed-net (6 coef.)
  'logreg'   : logistic regression on all features
  'hgb'      : sklearn HistGradientBoosting on all features
Call rule ('online', primary): a MISS is called by lead L if the score reached tau at any decision
frame t <= T_ref - L. 'snapshot' (secondary): score at exactly t = T_ref - L.
tau = smallest threshold whose out-of-fold train precision at the 50 ms lead is >= 95% and stays
>= 95% for every higher threshold that still makes >= 5 calls.

Usage:
  python early_call.py --dev            # train-only model selection + LOGO CV, never reads test
  python early_call.py --final          # fit on game_1..5, freeze tau, evaluate test_1..7 ONCE
"""
import argparse
import datetime
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import FPS, TRAIN, WORK, geometry_all

LAG = 2
NMIN = 5
NFIT = 30
MAX_LEAD = 36            # frames (300 ms) for the curves
LEADS_MS = [0, 25, 50, 100, 150, 200]
PREC_TARGET = 0.95
HORIZON = 1.0            # s, extrapolation horizon
FEATS_PHYS = ["u_far", "u_mid", "u_near", "w_net", "passed_net", "no_land"]
FEATS_ALL = FEATS_PHYS + ["u_now", "w_now", "du", "dw", "ddw", "ddu", "tau_mid", "resid",
                          "npts", "t_since", "hb", "speed"]
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RES = os.environ.get("TRACK_RESULTS", os.path.join(REPO, "results", "tracking"))


def ms(k):
    return 1000.0 * k / FPS


def k_of(ms_):
    return int(round(ms_ * FPS / 1000.0))


def robust_quadfit(t, z, it=2):
    w = np.ones_like(z)
    c = np.polyfit(t, z, 2)
    for _ in range(it):
        r = z - np.polyval(c, t)
        s = max(1.4826 * np.median(np.abs(r)), 1e-4)
        w = (np.abs(r) <= 3 * s).astype(float)
        if w.sum() < NMIN:
            break
        c = np.polyfit(t, z, 2, w=w)
    return c, w


def first_cross(c, level, horizon=HORIZON):
    """first tau in (0, horizon] where quadratic c(tau) goes below `level` (descending)."""
    a, b, c0 = c[0], c[1], c[2] - level
    if c0 <= 0:
        return 0.0
    if abs(a) < 1e-12:
        r = [-c0 / b] if b < 0 else []
    else:
        disc = b * b - 4 * a * c0
        if disc < 0:
            return None
        sq = np.sqrt(disc)
        r = sorted([(-b - sq) / (2 * a), (-b + sq) / (2 * a)])
    r = [x for x in r if 0 < x <= horizon]
    return r[0] if r else None


class Flight:
    """Track prefix of one flight in normalised coordinates."""

    def __init__(self, row, trk, g):
        self.row = row
        d = row.dir
        L = g["x_right"] - g["x_left"]
        fr = np.arange(row.t0, row.t_ref + 1)
        xy = np.array([trk.get(f, (np.nan, np.nan)) for f in fr], float)
        ok = np.isfinite(xy[:, 0])
        self.fr, x, y = fr[ok], xy[ok, 0], xy[ok, 1]
        af, bf = g["far_line"]
        an, bn = g["near_line"]
        ymid = 0.5 * ((af + an) * x + bf + bn)
        self.u = (x - g["x_left"]) / L if d > 0 else (g["x_right"] - x) / L
        self.w = (ymid - y) / L
        self.hb = float(np.median(((an - af) * x + bn - bf) / L)) if len(x) else 0.1
        self.L = L

    def features(self, t_dec):
        m = self.fr <= t_dec - LAG
        if m.sum() < NMIN:
            return None
        fr, u, w = self.fr[m][-NFIT:], self.u[m][-NFIT:], self.w[m][-NFIT:]
        tau = (fr - (t_dec - LAG)) / FPS
        if tau[-1] - tau[0] < (NMIN - 1) / FPS:
            return None
        cu, wu = robust_quadfit(tau, u)
        cw, ww = robust_quadfit(tau, w)
        res = np.sqrt(np.mean((w - np.polyval(cw, tau))[ww > 0] ** 2)) if (ww > 0).any() else 0.0
        f = {}
        no_land = 0
        for name, lev in (("u_far", self.hb / 2), ("u_mid", 0.0), ("u_near", -self.hb / 2)):
            tc = first_cross(cw, lev)
            if tc is None:
                tc, no_land = HORIZON, 1
            f[name] = float(np.clip(np.polyval(cu, tc) - 1.0, -1.5, 1.5))
            if name == "u_mid":
                f["tau_mid"] = tc
        f["no_land"] = no_land
        u_now = np.polyval(cu, 0.0)
        f["passed_net"] = float(u_now >= 0.5)
        tn = None
        if u_now < 0.5 and cu[1] > 0:
            r = np.roots([cu[0], cu[1], cu[2] - 0.5])
            r = [x.real for x in r if abs(x.imag) < 1e-9 and 0 < x.real <= HORIZON]
            tn = min(r) if r else None
        f["w_net"] = float(np.clip(np.polyval(cw, tn), -0.5, 0.5)) if tn is not None else 0.5
        f.update(u_now=u_now, w_now=np.polyval(cw, 0.0), du=cu[1], dw=cw[1], ddw=2 * cw[0],
                 ddu=2 * cu[0], resid=res, npts=len(fr), t_since=(t_dec - self.row.t0) / FPS,
                 hb=self.hb, speed=abs(cu[1]) * 2.74)
        return f


def build_samples(flights, tracks, geo):
    """One sample per (flight, decision frame) from t0 to T_ref."""
    rows = []
    objs = {}
    for r in flights.itertuples():
        F = Flight(r, tracks[r.video], geo[r.video])
        objs[r.Index] = F
        for t in range(r.t0 + NMIN - 1 + LAG, r.t_ref + 1):
            f = F.features(t)
            if f is None:
                continue
            f.update(fid=r.Index, video=r.video, t=t, k=r.t_ref - t, y=int(r.label == "MISS"))
            rows.append(f)
    return pd.DataFrame(rows), objs


def make_model(name):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if name == "hgb":
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                              min_samples_leaf=40, l2_regularization=1.0,
                                              class_weight="balanced", random_state=0)
    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000))


def feats_of(name):
    return FEATS_PHYS if name == "physics" else FEATS_ALL


def fit_predict(name, tr, te):
    m = make_model(name)
    X = feats_of(name)
    # weight every flight equally, whatever its length
    sw = 1.0 / tr.groupby("fid")["fid"].transform("size").values
    if name == "hgb":
        m.fit(tr[X].values, tr.y.values, sample_weight=sw)
    else:
        m.fit(tr[X].values, tr.y.values, logisticregression__sample_weight=sw)
    return m.predict_proba(te[X].values)[:, 1], m


def score_matrices(samples, score, flights):
    """Per flight (rows = flights.index order) and lead k = 0..MAX_LEAD:
       ON[i, k]   = max score over decision frames with lead >= k (online rule)
       SNAP[i, k] = score at lead exactly k (snapshot rule); -inf where no decision possible.
       FIRST[i]   = sorted (lead_frames, score) arrays for the first-call lead."""
    pos = {fid: i for i, fid in enumerate(flights.index)}
    n = len(flights)
    ON = np.full((n, MAX_LEAD + 1), -np.inf)
    SNAP = np.full((n, MAX_LEAD + 1), -np.inf)
    s = pd.DataFrame({"fid": samples.fid.values, "k": samples.k.values, "s": score})
    first = {}
    for fid, g in s.groupby("fid"):
        i = pos[fid]
        ks, ss = g.k.values, g.s.values
        first[i] = (ks, ss)
        for k, v in zip(ks, ss):
            if k <= MAX_LEAD:
                SNAP[i, k] = v
        # online: max over leads >= k
        order = np.argsort(-ks)
        ks_o, ss_o = ks[order], np.maximum.accumulate(ss[order])
        for k in range(MAX_LEAD + 1):
            j = np.searchsorted(-ks_o, -k, side="right") - 1  # last index with ks_o >= k
            if j >= 0:
                ON[i, k] = ss_o[j]
    return ON, SNAP, first


def per_flight_calls(samples, score, flights, tau, mode="online", mats=None):
    """-> DataFrame (fid, k, called, y) for k = 0..MAX_LEAD, and first-call lead (ms) per flight."""
    ON, SNAP, first = mats if mats is not None else score_matrices(samples, score, flights)
    M = ON if mode == "online" else SNAP
    called = M >= tau
    n = len(flights)
    c = pd.DataFrame({"fid": np.repeat(flights.index.values, MAX_LEAD + 1),
                      "k": np.tile(np.arange(MAX_LEAD + 1), n),
                      "called": called.ravel()})
    c["y"] = np.repeat((flights.label.values == "MISS"), MAX_LEAD + 1)
    lead = {}
    for i, fid in enumerate(flights.index):
        if i in first:
            ks, ss = first[i]
            a = ks[ss >= tau]
            lead[fid] = ms(a.max()) if len(a) else np.nan
        else:
            lead[fid] = np.nan
    return c, pd.Series(lead)


def pr_at(c, k):
    sub = c[c.k == k]
    tp = int((sub.called & sub.y).sum())
    fp = int((sub.called & ~sub.y).sum())
    fn = int((~sub.called & sub.y).sum())
    prec = tp / (tp + fp) if tp + fp else np.nan
    rec = tp / (tp + fn) if tp + fn else np.nan
    return prec, rec, tp, fp, fn


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)


def choose_tau(samples, score, flights, k50, mode="online"):
    ON, SNAP, _ = score_matrices(samples, score, flights)
    M = (ON if mode == "online" else SNAP)[:, k50]
    y = flights.label.values == "MISS"
    grid = np.unique(np.quantile(score, np.linspace(0.3, 0.9995, 600)))
    rows = []
    for tau in grid:
        cl = M >= tau
        tp, fp = int((cl & y).sum()), int((cl & ~y).sum())
        rows.append((tau, tp / (tp + fp) if tp + fp else np.nan, tp / max(y.sum(), 1), tp + fp))
    ok = pd.DataFrame(rows, columns=["tau", "prec", "rec", "ncalls"])
    valid = ok[ok.ncalls >= 5]
    good = valid.prec >= PREC_TARGET
    if not good.any():
        return float(valid.tau.max()), ok
    bad_taus = valid.tau[~good]
    lo = bad_taus.max() if len(bad_taus) else -np.inf
    cand = valid.tau[(valid.tau > lo) & good]
    return (float(cand.min()) if len(cand) else float(valid.tau.max())), ok


def load_tracks(videos):
    tr = {}
    for v in videos:
        t = pd.read_csv(os.path.join(WORK, "tracks", f"{v}_tracks.csv"))
        tr[v] = {int(f): (x, y) for f, x, y in zip(t.frame, t.x, t.y) if np.isfinite(x)}
    return tr


def logo_oof(name, S):
    oof = np.full(len(S), np.nan)
    for v in TRAIN:
        te = S.video == v
        oof[te.values], _ = fit_predict(name, S[~te], S[te])
    return oof


def summarize_curve(c):
    rows = []
    for k in range(MAX_LEAD + 1):
        p, r, tp, fp, fn = pr_at(c, k)
        lo, hi = wilson(tp, tp + fp)
        rows.append(dict(lead_ms=ms(k), precision=p, recall=r, tp=tp, fp=fp, fn=fn,
                         prec_lo95=lo, prec_hi95=hi))
    return pd.DataFrame(rows)


def dev(args):
    fl = pd.read_csv(os.path.join(WORK, "flights.csv"))
    fl = fl[fl.split == "train"].reset_index(drop=True)
    geo = geometry_all()
    S, _ = build_samples(fl, load_tracks(TRAIN), geo)
    print("train flights", fl.label.value_counts().to_dict(), "samples", len(S))
    k50 = k_of(50)
    rep = {}
    for name in args.models:
        oof = logo_oof(name, S)
        tau, grid = choose_tau(S, oof, fl, k50)
        c, lead = per_flight_calls(S, oof, fl, tau)
        cur = summarize_curve(c)
        p50 = cur.loc[cur.lead_ms.round() == 50].iloc[0]
        from sklearn.metrics import average_precision_score
        sel = S.k == k50
        ap = average_precision_score(S.y[sel], oof[sel.values])
        rep[name] = dict(tau=tau, prec50=p50.precision, rec50=p50.recall, tp=int(p50.tp),
                         fp=int(p50.fp), ap_snapshot50=ap)
        print(f"{name:8s} tau={tau:.3f}  OOF@50ms prec={p50.precision:.3f} rec={p50.recall:.3f} "
              f"tp={int(p50.tp)} fp={int(p50.fp)}  AP(snapshot@50)={ap:.3f}")
        print(cur.iloc[[0, 3, 6, 12, 18, 24, 36]][["lead_ms", "precision", "recall", "tp", "fp"]]
              .round(3).to_string(index=False))
    json.dump(rep, open(os.path.join(WORK, "dev_report.json"), "w"), indent=1)


def final(args):
    from plots import plot_examples, plot_precision_vs_lead
    log = os.path.join(RES, "test_peeks.log")
    os.makedirs(RES, exist_ok=True)
    with open(log, "a") as fh:
        fh.write(f"{datetime.datetime.utcnow().isoformat()}Z final evaluation on test_1..7 "
                 f"model={args.model}\n")
    fl = pd.read_csv(os.path.join(WORK, "flights.csv"))
    geo = geometry_all()
    tr_fl = fl[fl.split == "train"].reset_index(drop=True)
    te_fl = fl[fl.split == "test"].reset_index(drop=True)
    vids = sorted(fl.video.unique())
    tracks = load_tracks(vids)
    S_tr, _ = build_samples(tr_fl, tracks, geo)
    S_te, objs_te = build_samples(te_fl, tracks, geo)
    k50 = k_of(50)
    name = args.model
    # threshold frozen from leave-one-game-out predictions on the training games
    oof = logo_oof(name, S_tr)
    tau, _ = choose_tau(S_tr, oof, tr_fl, k50)
    c_tr, lead_tr = per_flight_calls(S_tr, oof, tr_fl, tau)
    # final model on all training games, applied once to test
    s_te, model = fit_predict(name, S_tr, S_te)
    out = {}
    for mode in ("online", "snapshot"):
        c_te, lead_te = per_flight_calls(S_te, s_te, te_fl, tau, mode)
        cur_te = summarize_curve(c_te)
        cur_te.to_csv(os.path.join(RES, f"test_precision_vs_lead_{mode}.csv"), index=False)
        out[mode] = (c_te, lead_te, cur_te)
    cur_tr = summarize_curve(c_tr)
    cur_tr.to_csv(os.path.join(RES, "train_oof_precision_vs_lead_online.csv"), index=False)
    c_te, lead_te, cur_te = out["online"]

    # per-flight table for test (lead, speed, landing distance)
    te_fl["lead_call_ms"] = te_fl.index.map(lead_te)
    tr_fl["lead_call_ms"] = tr_fl.index.map(lead_tr)
    for df, S in ((te_fl, S_te), (tr_fl, S_tr)):
        sp = S.groupby("fid").apply(lambda g: g.sort_values("k").speed.iloc[0] if len(g) else np.nan)
        df["speed_mps"] = df.index.map(sp)
    te_fl["dist_out_m"] = [hindsight_landing(objs_te[i]) for i in te_fl.index]
    te_fl.to_csv(os.path.join(RES, "test_flights.csv"), index=False)

    def stats_at(cur, lead):
        r = cur.loc[(cur.lead_ms - lead).abs() < 1e-6].iloc[0]
        return dict(precision=None if np.isnan(r.precision) else round(float(r.precision), 4),
                    recall=None if np.isnan(r.recall) else round(float(r.recall), 4),
                    tp=int(r.tp), fp=int(r.fp), fn=int(r.fn),
                    precision_wilson95=[None if np.isnan(x) else round(float(x), 4)
                                        for x in (r.prec_lo95, r.prec_hi95)])
    leads_test = {f"{l}ms": stats_at(cur_te, ms(k_of(l))) for l in LEADS_MS}
    leads_snap = {f"{l}ms": stats_at(out["snapshot"][2], ms(k_of(l))) for l in LEADS_MS}
    leads_train = {f"{l}ms": stats_at(cur_tr, ms(k_of(l))) for l in LEADS_MS}
    p50 = leads_test["50ms"]["precision"]
    verdict = "PASS" if (p50 is not None and p50 >= PREC_TARGET) else "FAIL"
    miss_te = te_fl[te_fl.label == "MISS"]
    lc = miss_te.lead_call_ms.dropna()
    outs = miss_te[(miss_te.miss_type == "out") & miss_te.lead_call_ms.notna()]
    def sp(a, b):
        if len(a) < 4:
            return None
        r = spearmanr(a, b)
        return dict(rho=round(float(r.statistic), 3), p=round(float(r.pvalue), 4), n=int(len(a)))
    summary = dict(
        hypothesis="H3", model=name, tau=round(tau, 4), call_rule="online (primary)",
        decision_lag_frames=LAG,
        precision_recall_test_online=leads_test,
        precision_recall_test_snapshot=leads_snap,
        precision_recall_train_oof_online=leads_train,
        verdict=verdict,
        verdict_rule="PASS iff test precision of MISS calls at the 50 ms lead (online rule) >= 0.95",
        miss_lead_test_ms=dict(
            n_miss=int(len(miss_te)), n_called=int(len(lc)),
            median=None if lc.empty else round(float(lc.median()), 1),
            p10=None if lc.empty else round(float(lc.quantile(0.1)), 1),
            p90=None if lc.empty else round(float(lc.quantile(0.9)), 1)),
        lead_vs_speed_spearman=sp(miss_te.dropna(subset=["lead_call_ms"]).speed_mps,
                                  miss_te.dropna(subset=["lead_call_ms"]).lead_call_ms),
        lead_vs_dist_out_spearman=sp(outs.dist_out_m, outs.lead_call_ms),
    )
    json.dump(summary, open(os.path.join(WORK, "early_call_final.json"), "w"), indent=1)
    plot_precision_vs_lead(cur_te, out["snapshot"][2], cur_tr, tau, os.path.join(RES, "precision_vs_lead.png"))
    plot_examples(te_fl, objs_te, model, name, geo, os.path.join(RES, "example_trajectories.png"))
    print(json.dumps(summary, indent=1))


def hindsight_landing(F):
    """Landing position relative to the end line (m, > 0 = long) from a fit to the whole
    observed flight (not causal; used only to describe 'how far out')."""
    if len(F.fr) < NMIN:
        return np.nan
    tau = (F.fr - F.fr[-1]) / FPS
    cu, _ = robust_quadfit(tau, F.u)
    cw, _ = robust_quadfit(tau, F.w)
    tc = first_cross(cw, 0.0, horizon=1.5)
    if tc is None:
        tc = 0.0
    return float((np.polyval(cu, tc) - 1.0) * 2.74)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--models", nargs="+", default=["physics", "logreg", "hgb"])
    ap.add_argument("--model", default="logreg", help="model used by --final")
    a = ap.parse_args()
    if a.dev:
        dev(a)
    elif a.final:
        final(a)
    else:
        sys.exit("use --dev or --final")
