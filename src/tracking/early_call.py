"""H3 early call: from the trajectory prefix, call MISS (out / net) vs TABLE BOUNCE before contact.

Decision at frame t uses only track points in [t0, t - LAG] (LAG = 2 frames: the detector
averages heatmaps of the triplets that contain a frame, so frame t's position needs frame t+2).

Features (all in table-normalised image coordinates so that different cameras are comparable:
u = position along the table in table lengths, 0 at the hitter's end line, 0.5 at the net, 1 at
the target end line; w = height above the table mid-line in table lengths):
  a robust quadratic fit u(tau), w(tau) to the last <= 30 prefix points (u then extrapolated
  linearly with the fitted velocity, w with its quadratic), then
  - predicted landing position u where the extrapolated arc reaches the far-edge, mid and
    near-edge table level (the true bounce level lies between them, depending on depth),
    measured relative to the end line (> 0 = beyond the end = long)
  - predicted height at the net plane (if the net is still ahead), whether the net is passed
  - predicted height above the far-edge level when the ball reaches the end line (w_end > 0:
    the arc clears the whole table) and the time until then
  - current u, w, velocities, vertical acceleration, fit residual, #points, time since t0
Models (chosen on game_1..5 only, leave-one-game-out CV):
  'physics'  : logistic regression on the 3 landing features + net-height + passed-net (6 coef.)
  'logreg'   : logistic regression on all features
  'hgb'      : sklearn HistGradientBoosting on all features
Call rules:
  'snapshot' (primary, the literal "precision at a 50 ms lead"): MISS is called at lead L if the
             score at decision frame t = T_ref - L is >= tau.
  'online'   (secondary, what a trader acting on the first call experiences): MISS is called by
             lead L if, at some decision frame t <= T_ref - L, the score was >= tau on PERSIST = 3
             consecutive frames. The first such frame gives the per-flight call lead.
tau = smallest threshold whose out-of-fold train precision at the 50 ms lead is >= 95% and stays
>= 95% for every higher threshold that still makes >= 5 calls; chosen separately for the snapshot
rule (verdict) and the online rule (first-call leads).

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
PERSIST = 3              # consecutive decision frames >= tau for an online call
GATE_H = float(os.environ.get("GATE_H", "0.10"))  # s; a call is allowed only when the ball is
                         # predicted to reach the net or end line within GATE_H (short extrapolation);
                         # chosen on game_1..5 (LOGO) from {inf, 0.25, 0.15, 0.10}
HORIZON = 1.0            # s, extrapolation horizon
FEATS_PHYS = ["u_far", "u_mid", "u_near", "w_net", "passed_net", "no_land", "w_end", "tau_end"]
FEATS_ALL = FEATS_PHYS + ["u_now", "w_now", "du", "dw", "ddw", "ddu", "tau_mid", "resid",
                          "npts", "t_since", "hb", "speed", "dir", "w_max", "u_wmax"]
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
        # along the table the ball moves at nearly constant speed (drag is small over 0.3 s), so the
        # landing position is extrapolated linearly from the fitted position and velocity at tau=0;
        # the height keeps its quadratic (gravity + spin) term
        u_now, du_now = cu[2], cu[1]
        ulin = lambda t: u_now + du_now * t
        no_land = 0
        for name, lev in (("u_far", self.hb / 2), ("u_mid", 0.0), ("u_near", -self.hb / 2)):
            tc = first_cross(cw, lev)
            if tc is None:          # the fitted arc does not come down within the horizon
                no_land = 1
                f[name] = 0.0
                if name == "u_mid":
                    f["tau_mid"] = HORIZON
                continue
            f[name] = float(np.clip(ulin(tc) - 1.0, -1.5, 1.5))
            if name == "u_mid":
                f["tau_mid"] = tc
        f["no_land"] = no_land
        f["passed_net"] = float(u_now >= 0.5)
        tn = (0.5 - u_now) / du_now if (u_now < 0.5 and du_now > 0) else None
        tn = tn if (tn is not None and tn <= HORIZON) else None
        f["w_net"] = float(np.clip(np.polyval(cw, tn), -0.5, 0.5)) if tn is not None else 0.5
        f["tau_net"] = tn if tn is not None else HORIZON
        # predicted height (relative to the far-edge level) when the ball reaches the end line
        te = 0.0 if u_now >= 1.0 else ((1.0 - u_now) / du_now if du_now > 0 else None)
        te = te if (te is not None and te <= HORIZON) else None
        f["tau_end"] = te if te is not None else HORIZON
        f["w_end"] = float(np.clip(np.polyval(cw, te) - self.hb / 2, -0.5, 0.5)) if te is not None else -0.5
        allw = self.w[m]
        j = int(np.argmax(allw))
        f.update(dir=float(self.row.dir), w_max=float(allw[j]), u_wmax=float(self.u[m][j]))
        f.update(u_now=u_now, w_now=cw[2], du=cu[1], dw=cw[1], ddw=2 * cw[0],
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


def gated(score, S, h=None):
    """Zero the score unless the ball is predicted to reach the net (if still ahead) or the end
    line within GATE_H seconds, i.e. only short extrapolations may trigger a call."""
    out = np.asarray(score, float).copy()
    h = GATE_H if h is None else h
    out[(np.minimum(S.tau_end, S.tau_net) > h).values] = 0.0
    return out


def fit_predict(name, tr, te):
    m = make_model(name)
    X = feats_of(name)
    # weight every flight equally, whatever its length
    sw = 1.0 / tr.groupby("fid")["fid"].transform("size").values
    if name == "hgb":
        m.fit(tr[X].values, tr.y.values, sample_weight=sw)
    else:
        m.fit(tr[X].values, tr.y.values, logisticregression__sample_weight=sw)
    return gated(m.predict_proba(te[X].values)[:, 1], te), m


def score_matrices(samples, score, flights):
    """Per flight (rows = flights.index order) and lead k = 0..MAX_LEAD:
       SNAP[i, k] = score at lead exactly k (snapshot rule)
       ON[i, k]   = max over decision frames with lead >= k of the PERSIST-frame rolling minimum
                    of the score (online rule: called iff ON >= tau)
       first[i]   = (lead_frames, persistent score) arrays for the first-call lead.
       -inf where no decision is possible."""
    pos = {fid: i for i, fid in enumerate(flights.index)}
    n = len(flights)
    ON = np.full((n, MAX_LEAD + 1), -np.inf)
    SNAP = np.full((n, MAX_LEAD + 1), -np.inf)
    s = pd.DataFrame({"fid": samples.fid.values, "k": samples.k.values, "s": score})
    first = {}
    for fid, g in s.groupby("fid"):
        i = pos[fid]
        kmax = int(g.k.max())
        arr = np.full(kmax + 1, -np.inf)       # index = lead in frames
        arr[g.k.values] = g.s.values
        for k in range(min(kmax, MAX_LEAD) + 1):
            SNAP[i, k] = arr[k]
        # persistent score at lead k: min over leads k, k+1, ..., k+PERSIST-1 (this frame and the
        # PERSIST-1 frames before it)
        pers = np.full(kmax + 1, -np.inf)
        for k in range(kmax + 1):
            if k + PERSIST - 1 <= kmax:
                pers[k] = arr[k:k + PERSIST].min()
        first[i] = (np.arange(kmax + 1), pers)
        run = np.maximum.accumulate(pers[::-1])[::-1]   # run[k] = max over leads >= k
        for k in range(min(kmax, MAX_LEAD) + 1):
            ON[i, k] = run[k]
    return ON, SNAP, first


def per_flight_calls(samples, score, flights, tau, mode="snapshot", mats=None):
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


def choose_tau(samples, score, flights, k50, mode="snapshot"):
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
        if te.any():
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


def curves(S, score, fl, tau):
    mats = score_matrices(S, score, fl)
    out = {}
    for mode in ("snapshot", "online"):
        c, lead = per_flight_calls(S, score, fl, tau, mode, mats=mats)
        out[mode] = (c, lead, summarize_curve(c))
    return out


def stats_at(cur, lead_ms):
    r = cur.loc[(cur.lead_ms - lead_ms).abs() < 1e-6].iloc[0]
    nan = lambda x: None if not np.isfinite(x) else round(float(x), 4)
    return dict(precision=nan(r.precision), recall=nan(r.recall), tp=int(r.tp), fp=int(r.fp),
                fn=int(r.fn), precision_wilson95=[nan(r.prec_lo95), nan(r.prec_hi95)])


def lead_table(cur):
    return {f"{l}ms": stats_at(cur, ms(k_of(l))) for l in LEADS_MS}


def dev(args):
    """Model / gate selection on game_1..5 only (leave-one-game-out). Never reads test flights."""
    global GATE_H
    from sklearn.metrics import average_precision_score
    fl = pd.read_csv(os.path.join(WORK, "flights.csv"))
    fl = fl[fl.split == "train"].reset_index(drop=True)
    geo = geometry_all()
    S, _ = build_samples(fl, load_tracks(sorted(fl.video.unique())), geo)
    print("train flights", fl.label.value_counts().to_dict(), "samples", len(S))
    k50 = k_of(50)
    rep = {}
    keep = GATE_H
    for name in args.models:
        GATE_H = np.inf
        raw = logo_oof(name, S)
        GATE_H = keep
        for h in (np.inf, 0.25, 0.15, 0.10):
            oof = gated(raw, S, h)
            tau, grid = choose_tau(S, oof, fl, k50)
            tau_on, _ = choose_tau(S, oof, fl, k50, mode="online")
            snap = curves(S, oof, fl, tau)["snapshot"][2]
            onl = curves(S, oof, fl, tau_on)["online"][2]
            sel = (S.k == k50).values
            ap = average_precision_score(S.y[sel], oof[sel])
            key = f"{name}|gate={h}"
            rep[key] = dict(tau_snapshot=round(tau, 4), tau_online=round(tau_on, 4),
                            ap_snapshot_50ms=round(ap, 4),
                            snapshot=lead_table(snap), online=lead_table(onl))
            p, q = stats_at(snap, ms(k50)), stats_at(onl, ms(k50))
            q100 = stats_at(onl, ms(k_of(100)))
            print(f"{key:20s} tau={tau:.3f}/{tau_on:.3f} AP@50={ap:.3f} | snapshot@50 prec={p['precision']} "
                  f"rec={p['recall']} ({p['tp']}/{p['tp'] + p['fp']}) | online@50 prec={q['precision']} "
                  f"rec={q['recall']} ({q['tp']}/{q['tp'] + q['fp']}) | online@100 prec={q100['precision']} "
                  f"rec={q100['recall']}", flush=True)
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
    tracks = load_tracks(sorted(fl.video.unique()))
    S_tr, objs_tr = build_samples(tr_fl, tracks, geo)
    S_te, objs_te = build_samples(te_fl, tracks, geo)
    k50 = k_of(50)
    name = args.model
    # threshold frozen from leave-one-game-out predictions on the training games
    oof = logo_oof(name, S_tr)
    tau, _ = choose_tau(S_tr, oof, tr_fl, k50)                      # snapshot rule (verdict)
    tau_on, _ = choose_tau(S_tr, oof, tr_fl, k50, mode="online")    # online first-call rule
    cv_tr = {"snapshot": curves(S_tr, oof, tr_fl, tau)["snapshot"],
             "online": curves(S_tr, oof, tr_fl, tau_on)["online"]}
    # final model on all training games, applied once to test
    s_te, model = fit_predict(name, S_tr, S_te)
    cv_te = {"snapshot": curves(S_te, s_te, te_fl, tau)["snapshot"],
             "online": curves(S_te, s_te, te_fl, tau_on)["online"]}
    for mode in ("snapshot", "online"):
        cv_te[mode][2].to_csv(os.path.join(RES, f"test_precision_vs_lead_{mode}.csv"), index=False)
        cv_tr[mode][2].to_csv(os.path.join(WORK, f"train_oof_precision_vs_lead_{mode}.csv"), index=False)
    # per-flight tables (first-call lead, speed at the end of the flight, landing distance)
    def per_flight(df, S, score, objs, lead):
        df = df.copy()
        sel = (S.k == k50).values
        s50 = pd.Series(score[sel], index=S.fid[sel].values)
        df["p_miss_at_50ms"] = df.index.map(s50)
        df["first_call_lead_ms"] = df.index.map(lead)
        last = S.sort_values("k").groupby("fid").first()
        df["speed_mps"] = df.index.map(last.speed)
        df["dist_out_m"] = [hindsight_landing(objs[i]) for i in df.index]
        return df
    te_fl = per_flight(te_fl, S_te, s_te, objs_te, cv_te["online"][1])
    tr_fl = per_flight(tr_fl, S_tr, oof, objs_tr, cv_tr["online"][1])
    te_fl.to_csv(os.path.join(RES, "test_flights.csv"), index=False)
    tr_fl.to_csv(os.path.join(WORK, "train_flights_oof.csv"), index=False)

    snap_te = lead_table(cv_te["snapshot"][2])
    p50 = snap_te["50ms"]["precision"]
    verdict = "PASS" if (p50 is not None and p50 >= PREC_TARGET) else "FAIL"
    def sp(a, b):
        ok = np.isfinite(a.values) & np.isfinite(b.values)
        if ok.sum() < 4:
            return None
        r = spearmanr(a.values[ok], b.values[ok])
        return dict(rho=round(float(r.statistic), 3), p=round(float(r.pvalue), 4), n=int(ok.sum()))

    def lead_stats(df):
        miss = df[df.label == "MISS"]
        lc = miss.first_call_lead_ms.dropna()
        called = miss[miss.first_call_lead_ms.notna()]
        outs = miss[miss.miss_type == "out"]
        # recall-by-bin views: a miss that is never called has lead 0 for the bins below
        lead0 = miss.first_call_lead_ms.fillna(0.0)
        bins = {}
        for col in ("speed_mps", "dist_out_m"):
            sub = miss if col == "speed_mps" else outs
            if sub[col].notna().sum() >= 6:
                q = pd.qcut(sub[col], 3, duplicates="drop")
                g = lead0.loc[sub.index].groupby(q, observed=True)
                bins[col] = [dict(bin=str(k), n=int(len(v)), called=int((v > 0).sum()),
                                  median_lead_ms_called=(None if (v > 0).sum() == 0 else
                                                         round(float(v[v > 0].median()), 1)))
                             for k, v in g]
        return dict(
            n_miss=int(len(miss)), n_called=int(len(lc)),
            median=None if lc.empty else round(float(lc.median()), 1),
            p10=None if lc.empty else round(float(lc.quantile(0.1)), 1),
            p90=None if lc.empty else round(float(lc.quantile(0.9)), 1),
            spearman_lead_vs_speed_called=sp(called.speed_mps, called.first_call_lead_ms),
            spearman_lead_vs_dist_out_called_out=sp(called[called.miss_type == "out"].dist_out_m,
                                                    called[called.miss_type == "out"].first_call_lead_ms),
            spearman_lead0_vs_speed_all_miss=sp(miss.speed_mps, lead0),
            spearman_lead0_vs_dist_out_all_out=sp(outs.dist_out_m, lead0.loc[outs.index]),
            by_bin=bins)
    # lead at which snapshot precision on test stays >= 95% (largest lead L such that precision
    # >= 0.95 for every lead in [0, L] with at least one call)
    cur = cv_te["snapshot"][2]
    okL = [r.lead_ms for r in cur.itertuples() if (r.tp + r.fp) > 0 and r.precision >= PREC_TARGET]
    summary = dict(
        hypothesis="H3", model=name, tau_snapshot=round(tau, 4), tau_online=round(tau_on, 4),
        primary_rule="snapshot",
        decision_lag_frames=LAG, online_persistence_frames=PERSIST,
        precision_recall_test_snapshot=snap_te,
        precision_recall_test_online=lead_table(cv_te["online"][2]),
        precision_recall_train_oof_snapshot=lead_table(cv_tr["snapshot"][2]),
        precision_recall_train_oof_online=lead_table(cv_tr["online"][2]),
        verdict=verdict,
        verdict_rule="PASS iff test precision of MISS calls at the 50 ms lead (snapshot rule) >= 0.95",
        gate_h_s=GATE_H,
        miss_first_call_lead_test_ms=lead_stats(te_fl),
        miss_first_call_lead_train_oof_ms=lead_stats(tr_fl),
        test_snapshot_leads_ms_with_precision_ge_95=okL,
    )
    json.dump(summary, open(os.path.join(WORK, "early_call_final.json"), "w"), indent=1)
    plot_precision_vs_lead(cv_te["snapshot"][2], cv_te["online"][2], cv_tr["snapshot"][2], tau,
                           os.path.join(RES, "precision_vs_lead.png"), tau_on=tau_on)
    plot_examples(te_fl, objs_te, model, name, geo, os.path.join(RES, "example_trajectories.png"))
    print(json.dumps(summary, indent=1))


def hindsight_landing(F):
    """Landing position relative to the end line (m, > 0 = long) from a fit to the last 30 points
    of the whole observed flight (not causal; only used to describe 'how far out'): where the arc
    reaches the table mid-level, with u extrapolated linearly. NaN if it does not come down
    within 0.5 s."""
    if len(F.fr) < NMIN:
        return np.nan
    fr, u, w = F.fr[-NFIT:], F.u[-NFIT:], F.w[-NFIT:]
    tau = (fr - fr[-1]) / FPS
    cu, _ = robust_quadfit(tau, u)
    cw, _ = robust_quadfit(tau, w)
    tc = first_cross(cw, 0.0, horizon=0.5)
    if tc is None:
        return np.nan
    return float((cu[2] + cu[1] * tc - 1.0) * 2.74)


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
