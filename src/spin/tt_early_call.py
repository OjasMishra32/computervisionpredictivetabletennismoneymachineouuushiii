"""Spin-aware early call for table tennis (OpenTTGames, 120 fps): the frozen H3 classifier family plus
the online physics/spin features of tt_features.py. Train-only CV first, then ONE test evaluation.

What changes and what does not, relative to the frozen model (src/tracking/early_call.py --final):
  same   flights, labels, T_ref, flight start t0 (WORK/flights.csv), tracks (WORK/tracks), decision
         frames and the 2-frame look-ahead offset, HGB estimator and hyper-parameters, per-flight sample
         weights, horizon-gate definition (a call is allowed only when the frozen tau_end / tau_net
         says the ball reaches the net or end line within GATE_H s), the threshold rule
         (smallest tau whose OOF train precision at 50 ms is >= 95% and stays >= 95% for every higher tau
         with >= 5 calls, chosen separately for the snapshot and the online rule), PERSIST = 3
  re-chosen on train  GATE_H for the new feature sets, from the H3-D5 candidates {inf, 0.25, 0.15, 0.10} s
         with the H3-D5 criterion (largest snapshot + online recall at 50 ms among gates whose OOF
         precision is >= 95% under both rules; ties -> the smaller gate; none qualifies -> 0.10 s).
         The frozen model keeps its frozen 0.10 s.
  new    the features: FEATS_ALL (23, frozen) + PH_FEATS (spin-model fit: fitted topspin / sidespin and
         their uncertainty, Magnus acceleration, 3D state, predicted landing point / net clearance / end-
         line height with sigma-point spreads, P(in / long / net / wide), the no-spin counterfactual
         landing point from the same state, fit quality, anchor type)

Models compared on game_1..5 (leave-one-game-out). Only 'spin' is evaluated on test (pre-specified):
  frozen     FEATS_ALL                      (the frozen model, refitted exactly as early_call does)
  spin       FEATS_ALL + PH_FEATS           <- evaluated on test_1..7 once
  nospin     FEATS_ALL + NS_FEATS           (ablation: same physics with spin fixed at 0; train only)
  phys_only  1 - P(in) of the spin fit, no learning, same gate   (diagnostic; train only)

Usage (repo root; on HiPerGator through hpg/spin_tt.sbatch):
  python src/spin/tt_early_call.py --dev   --procs 8   # train only; never reads a test flight
  python src/spin/tt_early_call.py --final --procs 8   # ONE test evaluation -> appends to test_peeks.log
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TRACKING = os.path.join(os.path.dirname(HERE), "tracking")
for _p in (HERE, TRACKING):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common as C  # noqa: E402
import early_call as E  # noqa: E402
import tt_camera  # noqa: E402
import tt_features as TF  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
WORK = os.environ.get("SPIN_WORK", os.path.join(C.WORK, "spin_tt"))
RES = os.environ.get("SPIN_RESULTS", os.path.join(REPO, "results", "spin", "tt"))
TRACK_RES = os.environ.get("TRACK_RESULTS", os.path.join(REPO, "results", "tracking"))
PEEKS = os.path.join(TRACK_RES, "test_peeks.log")
MARK = "[spin_tt]"

_PH = ["ok", "rms_px", "out_frac", "npts", "x", "y", "z", "vx", "vy", "vz", "speed", "y_sd", "z_sd", "x_land", "y_land",
       "t_land", "x_land_sd", "y_land_sd", "z_net", "z_net_sd", "net_past", "z_end", "tau_end", "p_in",
       "p_long", "p_net", "p_wide", "p_unknown", "in_mean"]
_SPIN = ["top", "side", "top_sd", "side_sd", "top_z", "mag_z", "mag_lat", "x_land_nospin", "spin_shift",
         "in_nospin"]
PH_FEATS = ["ph_" + k for k in _PH + _SPIN] + ["ph_anchor"]
NS_FEATS = ["ns_" + k for k in _PH] + ["ph_anchor"]
MODELS = {"frozen": E.FEATS_ALL, "spin": E.FEATS_ALL + PH_FEATS, "nospin": E.FEATS_ALL + NS_FEATS}
TEST_MODEL = "spin"
K50 = E.k_of(50)
FROZEN_GATE = E.GATE_H          # 0.10 s (DEVIATIONS.md H3-D5)
GATES = (np.inf, 0.25, 0.15, 0.10)


# ---------------------------------------------------------------------------------------- data
def load_flights(split):
    fl = pd.read_csv(os.path.join(C.WORK, "flights.csv"))
    return fl[fl.split == split].reset_index(drop=True)


def physics_features(fl, split, procs, ablation=True, rebuild=False):
    """Cached per split: WORK/feats_<split>.pkl (keyed by video, f_net, t) + anchors_<split>.csv (one row
    per flight). The cache is reused only if it covers every flight with the same t0 / t_ref."""
    path = os.path.join(WORK, f"feats_{split}.pkl")
    apath = os.path.join(WORK, f"anchors_{split}.csv")
    if os.path.exists(path) and os.path.exists(apath) and not rebuild:
        A = pd.read_csv(apath)
        if {"t0", "t_ref"} <= set(A.columns):
            have = set(zip(A.video, A.f_net, A.t0, A.t_ref))
            if all(k in have for k in zip(fl.video, fl.f_net, fl.t0, fl.t_ref)):
                return pd.read_pickle(path)
    vids = sorted(fl.video.unique())
    cams, _ = tt_camera.cameras_all(vids, os.path.join(WORK, "cameras.json"))
    tracks = E.load_tracks(vids)
    print(f"physics fits for {len(fl)} {split} flights on {procs} processes ...", flush=True)
    F, A = TF.build(fl, tracks, cams, procs=procs, ablation=ablation)
    A = A.merge(fl[["video", "f_net", "t0", "t_ref"]], on=["video", "f_net"], how="left")
    os.makedirs(WORK, exist_ok=True)
    F.to_pickle(path)
    A.to_csv(apath, index=False)
    print(split, len(F), "physics rows; anchors", A.anchor.value_counts().to_dict(),
          f"; median {A.seconds.median():.1f} s per flight", flush=True)
    return F


def samples(fl, F, geo, tracks):
    """Frozen samples (one per flight x decision frame) with the physics features merged in."""
    S, objs = E.build_samples(fl, tracks, geo)
    S["f_net"] = fl.f_net.values[S.fid.values]
    S = S.merge(F, on=["video", "f_net", "t"], how="left", validate="one_to_one")
    for c in set(PH_FEATS + NS_FEATS) - set(S.columns):
        S[c] = np.nan
    return S, objs


# ---------------------------------------------------------------------------------------- models
def fit_model(feats, tr):
    """early_call.fit_predict for a given feature list: HGB, every flight weighted equally."""
    m = E.make_model("hgb")
    sw = 1.0 / tr.groupby("fid")["fid"].transform("size").values
    m.fit(tr[feats].values, tr.y.values, sample_weight=sw)
    return m


def raw_score(m, feats, S):
    """Ungated P(miss); E.gated(raw, S, h) applies the horizon gate."""
    return m.predict_proba(S[feats].values)[:, 1]


def logo_oof_raw(feats, S):
    """Leave-one-game-out predictions on game_1..5, before the gate (the gate does not affect fitting)."""
    oof = np.full(len(S), np.nan)
    for v in C.TRAIN:
        te = (S.video == v).values
        if te.any():
            oof[te] = raw_score(fit_model(feats, S[~te]), feats, S[te])
    return oof


def phys_only_raw(S):
    return np.nan_to_num(1.0 - S.ph_p_in.values, nan=0.0)


def select_gate(S, raw, fl, gates=GATES):
    """H3-D5 rule on OOF train scores -> (gate, {gate: summary}, evaluate() output at the chosen gate)."""
    rows = {}
    for h in gates:
        out = evaluate(S, E.gated(raw, S, h), fl)
        s50, o50 = out[0]["snapshot"]["50ms"], out[0]["online"]["50ms"]
        ok = (s50["precision"] or 0) >= E.PREC_TARGET and (o50["precision"] or 0) >= E.PREC_TARGET
        crit = (s50["recall"] or 0) + (o50["recall"] or 0)
        rows[h] = (ok, crit, out)
    good = [h for h in gates if rows[h][0]]
    best = max(good, key=lambda h: (rows[h][1], -h)) if good else FROZEN_GATE
    if best not in rows:
        rows[best] = (False, 0.0, evaluate(S, E.gated(raw, S, best), fl))
    table = {str(h): dict(qualifies=bool(rows[h][0]), recall_sum_50ms=round(rows[h][1], 4),
                          snapshot_50ms=rows[h][2][0]["snapshot"]["50ms"], online_50ms=rows[h][2][0]["online"]["50ms"],
                          tau_snapshot=rows[h][2][0]["tau_snapshot"], tau_online=rows[h][2][0]["tau_online"],
                          first_call=rows[h][2][0]["first_call"]) for h in rows}
    return best, table, rows[best][2]


def evaluate(S, score, fl, tau_snap=None, tau_on=None):
    """Thresholds (if not given: chosen on this score), curves, per-flight calls and first-call leads."""
    if tau_snap is None:
        tau_snap, _ = E.choose_tau(S, score, fl, K50)
        tau_on, _ = E.choose_tau(S, score, fl, K50, mode="online")
    ON, SNAP, first = E.score_matrices(S, score, fl)
    c_snap, lead_snap = E.per_flight_calls(S, score, fl, tau_snap, "snapshot", mats=(ON, SNAP, first))
    c_on, lead_on = E.per_flight_calls(S, score, fl, tau_on, "online", mats=(ON, SNAP, first))
    cur_snap, cur_on = E.summarize_curve(c_snap), E.summarize_curve(c_on)
    y = fl.label.values == "MISS"
    per = pd.DataFrame({
        "video": fl.video.values, "f_net": fl.f_net.values, "label": fl.label.values,
        "miss_type": fl.miss_type.values,
        "p_at_50ms": SNAP[:, K50], "snap_call_50ms": SNAP[:, K50] >= tau_snap,
        "online_call_by_50ms": ON[:, K50] >= tau_on, "online_call_any": ON[:, 0] >= tau_on,
        "first_call_lead_ms": lead_on.reindex(fl.index).values})
    from sklearn.metrics import average_precision_score
    sel = (S.k == K50).values
    ap = float(average_precision_score(S.y[sel], score[sel])) if sel.any() and S.y[sel].nunique() > 1 else None
    lc = per.loc[y & per.first_call_lead_ms.notna(), "first_call_lead_ms"]
    fa = per.loc[~y & per.first_call_lead_ms.notna(), "first_call_lead_ms"]
    rep = dict(
        tau_snapshot=round(float(tau_snap), 4), tau_online=round(float(tau_on), 4),
        ap_snapshot_50ms=None if ap is None else round(ap, 4),
        snapshot=E.lead_table(cur_snap), online=E.lead_table(cur_on),
        first_call=dict(n_miss=int(y.sum()), n_miss_called=int(len(lc)),
                        median_lead_ms=None if lc.empty else round(float(lc.median()), 1),
                        p10_lead_ms=None if lc.empty else round(float(lc.quantile(0.1)), 1),
                        p90_lead_ms=None if lc.empty else round(float(lc.quantile(0.9)), 1),
                        n_bounce_called_any_lead=int(len(fa)),
                        online_precision_any_lead=None if len(lc) + len(fa) == 0
                        else round(len(lc) / (len(lc) + len(fa)), 4)))
    return rep, per, cur_snap, cur_on


def flips(per_a, per_b, name_a, name_b):
    """How often model a's call differs from model b's, per rule, split by the true label."""
    out = {}
    y = per_a.label.values == "MISS"
    for col in ("snap_call_50ms", "online_call_by_50ms", "online_call_any"):
        a, b = per_a[col].values.astype(bool), per_b[col].values.astype(bool)
        out[col] = {
            f"{name_a}_only_true_miss": int((a & ~b & y).sum()),       # a adds a correct MISS call
            f"{name_a}_only_true_bounce": int((a & ~b & ~y).sum()),    # a adds a false MISS call
            f"{name_b}_only_true_miss": int((~a & b & y).sum()),       # a drops a correct call
            f"{name_b}_only_true_bounce": int((~a & b & ~y).sum()),    # a drops a false call
            "both": int((a & b).sum()), "n_flights": int(len(a)),
            "flip_rate": round(float((a != b).mean()), 4),
        }
    return out


def spin_diagnostics(S, fl):
    """Fitted spin at the 50 ms decision frame, per label (and fit health), train or test."""
    sel = S[(S.k == K50)].copy()
    sel["label"] = fl.label.values[sel.fid.values]
    out = {"n_flights_with_fit_at_50ms": int(sel.ph_ok.fillna(0).astype(bool).sum()),
           "n_flights": int(len(fl))}
    for lab, g in sel.groupby("label"):
        g = g[g.ph_ok == 1]
        if g.empty:
            continue
        out[lab] = {k: round(float(np.nanmedian(g[c])), 3) for k, c in (
            ("median_top_rps", "ph_top"), ("median_side_rps", "ph_side"), ("median_top_sd_rps", "ph_top_sd"),
            ("median_mag_z_mps2", "ph_mag_z"), ("median_rms_px", "ph_rms_px"), ("median_speed_mps", "ph_speed"),
            ("median_x_land_m", "ph_x_land"), ("median_p_in", "ph_p_in"))}
        out[lab]["share_topspin_z>2"] = round(float((g.ph_top_z > 2).mean()), 3)
        out[lab]["share_backspin_z<-2"] = round(float((g.ph_top_z < -2).mean()), 3)
    out["anchor_share"] = {str(k): round(float(v), 3) for k, v in
                           S.groupby("fid").ph_anchor.first().value_counts(normalize=True).items()}
    return out


def _utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hash_df(df, cols):
    h = hashlib.sha256(pd.util.hash_pandas_object(df[cols].round(6), index=False).values.tobytes())
    return h.hexdigest()[:16]


def plot(curves, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharex=True)
    for (lab, cur, style) in curves:
        axes[0].plot(cur.lead_ms, cur.precision, **style, label=lab)
        axes[1].plot(cur.lead_ms, cur.recall, **style, label=lab)
    for ax, yl in zip(axes, ("precision of MISS calls", "recall of MISS flights")):
        ax.axvline(50, color="k", lw=0.8, ls=":")
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("lead before contact / table end (ms)")
        ax.set_ylabel(yl)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=0.25, lw=0.5)
    axes[0].axhline(0.95, color="k", lw=0.8, ls=":")
    axes[0].legend(fontsize=8, loc="lower left", frameon=False)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------------------- stages
def train_cv(procs, ablation=True):
    fl = load_flights("train")
    geo = C.geometry_all()
    tracks = E.load_tracks(sorted(fl.video.unique()))
    F = physics_features(fl, "train", procs, ablation=ablation)
    S, objs = samples(fl, F, geo, tracks)
    print("train flights", fl.label.value_counts().to_dict(), "samples", len(S),
          "with physics", int(S.ph_ok.notna().sum()), flush=True)
    res, pers, curs, gates = {}, {}, {}, {}
    raws = {name: logo_oof_raw(feats, S) for name, feats in MODELS.items() if ablation or name != "nospin"}
    raws["phys_only"] = phys_only_raw(S)
    for name, raw in raws.items():
        if name == "frozen":
            h, table, out = FROZEN_GATE, None, evaluate(S, E.gated(raw, S, FROZEN_GATE), fl)
        else:
            h, table, out = select_gate(S, raw, fl)
        res[name], pers[name], cs, co = out
        res[name]["gate_h_s"] = h
        if table is not None:
            res[name]["gate_selection"] = table
        curs[name] = (cs, co)
        gates[name] = h
    return fl, S, res, pers, curs, gates


def dev(a):
    os.makedirs(RES, exist_ok=True)
    fl, S, res, pers, curs, gates = train_cv(a.procs, ablation=not a.no_ablation)
    rep = {"stage": "dev (train game_1..5 only, leave-one-game-out)", "gate_h_s": gates,
           "models": res, "test_model": TEST_MODEL,
           "flips_spin_vs_frozen": flips(pers["spin"], pers["frozen"], "spin", "frozen"),
           "spin_diagnostics_train": spin_diagnostics(S, fl),
           "n_train_flights": {k: int(v) for k, v in fl.label.value_counts().items()},
           "n_samples": int(len(S)), "n_samples_with_physics": int(S.ph_ok.notna().sum())}
    if "nospin" in pers:
        rep["flips_spin_vs_nospin_physics"] = flips(pers["spin"], pers["nospin"], "spin", "nospin")
    for name in res:
        r = res[name]
        s50, o50 = r["snapshot"]["50ms"], r["online"]["50ms"]
        print(f"{name:10s} gate={r['gate_h_s']} tau={r['tau_snapshot']:.3f}/{r['tau_online']:.3f} "
              f"AP@50={r['ap_snapshot_50ms']} | "
              f"snapshot@50 prec={s50['precision']} rec={s50['recall']} ({s50['tp']}/{s50['tp'] + s50['fp']}) | "
              f"online@50 prec={o50['precision']} rec={o50['recall']} ({o50['tp']}/{o50['tp'] + o50['fp']}) | "
              f"first-call median {r['first_call']['median_lead_ms']} ms", flush=True)
        curs[name][0].to_csv(os.path.join(RES, f"train_oof_precision_vs_lead_{name}_snapshot.csv"), index=False)
        curs[name][1].to_csv(os.path.join(RES, f"train_oof_precision_vs_lead_{name}_online.csv"), index=False)
    print("flips spin vs frozen:", json.dumps(rep["flips_spin_vs_frozen"]), flush=True)
    per = pers["spin"].rename(columns=lambda c: c if c in ("video", "f_net", "label", "miss_type") else f"spin_{c}")
    fro = pers["frozen"].drop(columns=["video", "f_net", "label", "miss_type"]).add_prefix("frozen_")
    pd.concat([per, fro], axis=1).to_csv(os.path.join(RES, "train_flights_oof_spin_vs_frozen.csv"), index=False)
    spec = {"model": TEST_MODEL, "estimator": "sklearn HistGradientBoostingClassifier (early_call.make_model('hgb'))",
            "features": MODELS[TEST_MODEL], "gate_h_s": gates[TEST_MODEL], "frozen_gate_h_s": FROZEN_GATE,
            "tau_snapshot": res[TEST_MODEL]["tau_snapshot"], "tau_online": res[TEST_MODEL]["tau_online"],
            "frozen_tau_snapshot_reproduced": res["frozen"]["tau_snapshot"],
            "frozen_tau_online_reproduced": res["frozen"]["tau_online"],
            "train_feature_hash": _hash_df(S, ["fid", "t"] + PH_FEATS),
            "written_utc": _utc()}
    json.dump(spec, open(os.path.join(RES, "frozen_spec.json"), "w"), indent=1)
    json.dump(rep, open(os.path.join(RES, "dev_report.json"), "w"), indent=1, default=float)
    plot([("frozen (LOGO, snapshot)", curs["frozen"][0], dict(color="#6c757d", lw=1.5)),
          ("spin (LOGO, snapshot)", curs["spin"][0], dict(color="#d1495b", lw=2)),
          ("frozen (LOGO, online)", curs["frozen"][1], dict(color="#6c757d", lw=1.2, ls="--")),
          ("spin (LOGO, online)", curs["spin"][1], dict(color="#d1495b", lw=1.2, ls="--"))],
         os.path.join(RES, "train_oof_precision_vs_lead.png"),
         "Train game_1..5, leave-one-game-out: frozen vs spin-aware model")
    print("wrote", RES)


def final(a):
    os.makedirs(RES, exist_ok=True)
    if os.path.exists(PEEKS) and MARK in open(PEEKS).read() and not os.environ.get("SPIN_TT_ALLOW_REPEAT"):
        sys.exit(f"{PEEKS} already records a {MARK} test evaluation; refusing to evaluate test again "
                 "(set SPIN_TT_ALLOW_REPEAT=1 only if the first run crashed before computing anything)")
    spec_path = os.path.join(RES, "frozen_spec.json")
    if not os.path.exists(spec_path):
        sys.exit("run --dev first (thresholds are frozen from the train CV)")
    spec = json.load(open(spec_path))
    # 1. train side: the same OOF scores and thresholds as the dev stage (asserted)
    fl_tr, S_tr, res_tr, pers_tr, curs_tr, gates = train_cv(a.procs, ablation=False)
    for k in ("tau_snapshot", "tau_online", "gate_h_s"):
        if abs(float(spec[k]) - float(res_tr[TEST_MODEL][k])) > 1e-4:
            sys.exit(f"train CV no longer reproduces the frozen {k} ({spec[k]} vs {res_tr[TEST_MODEL][k]}); "
                     "not evaluating test")
    tau_s, tau_o, gate = spec["tau_snapshot"], spec["tau_online"], float(spec["gate_h_s"])
    tauf_s, tauf_o = res_tr["frozen"]["tau_snapshot"], res_tr["frozen"]["tau_online"]
    # 2. the single test evaluation
    with open(PEEKS, "a") as fh:
        fh.write(f"{_utc()} final evaluation on test_1..7 model=hgb_spin (SECOND model evaluated on test: "
                 f"spin-aware physics features + frozen HGB family, src/spin/tt_early_call.py, "
                 f"tau={tau_s}/{tau_o}, gate={gate}) {MARK}\n")
    fl_te = load_flights("test")
    geo = C.geometry_all()
    tracks = E.load_tracks(sorted(set(fl_tr.video) | set(fl_te.video)))
    # post-hoc audited labels (DEVIATIONS.md H3-D10) move T_ref of relabelled flights; the physics
    # features are computed up to the later of the two so that both labellings can be scored
    aud_path = os.path.join(TRACK_RES, "test_flights_audited.csv")
    fl_aud = None
    if os.path.exists(aud_path):
        t = pd.read_csv(aud_path)[["video", "f_net", "label", "miss_type", "t_ref", "audit"]]
        fl_aud = fl_te.drop(columns=["label", "miss_type", "t_ref"]).merge(t, on=["video", "f_net"], how="left")
        if fl_aud.label.isna().any():
            fl_aud = None
    fl_feat = fl_te.copy()
    if fl_aud is not None:
        fl_feat["t_ref"] = np.maximum(fl_te.t_ref.values, fl_aud.t_ref.values.astype(int))
    F_te = physics_features(fl_feat, "test", a.procs, ablation=False)
    S_te, _ = samples(fl_te, F_te, geo, tracks)
    m_spin = fit_model(MODELS[TEST_MODEL], S_tr)
    m_froz = fit_model(MODELS["frozen"], S_tr)          # the frozen model, already evaluated once
    score_spin = lambda S: E.gated(raw_score(m_spin, MODELS[TEST_MODEL], S), S, gate)
    score_froz = lambda S: E.gated(raw_score(m_froz, MODELS["frozen"], S), S, FROZEN_GATE)
    s_spin, s_frozen = score_spin(S_te), score_froz(S_te)
    r_spin, per_spin, cs, co = evaluate(S_te, s_spin, fl_te, tau_s, tau_o)
    r_froz, per_froz, fcs, fco = evaluate(S_te, s_frozen, fl_te, tauf_s, tauf_o)
    # reproduction check of the frozen model against its published test table
    repro = None
    pub = os.path.join(TRACK_RES, "test_flights.csv")
    if os.path.exists(pub):
        t = pd.read_csv(pub)
        m = per_froz.merge(t[["video", "f_net", "p_miss_at_50ms"]], on=["video", "f_net"], how="inner")
        ok = np.isfinite(m.p_at_50ms) & np.isfinite(m.p_miss_at_50ms)
        repro = dict(n=int(ok.sum()), max_abs_diff_p50=float(np.abs(m.p_at_50ms - m.p_miss_at_50ms)[ok].max())
                     if ok.any() else None)
    out = {
        "stage": "final: ONE evaluation of the spin-aware model on test_1..7 (second model evaluated on test)",
        "model": TEST_MODEL, "gate_h_s": gate, "frozen_gate_h_s": FROZEN_GATE,
        "tau_snapshot": tau_s, "tau_online": tau_o,
        "test_spin": r_spin, "test_frozen_reproduced": r_froz, "frozen_reproduction_check": repro,
        "flips_spin_vs_frozen_test": flips(per_spin, per_froz, "spin", "frozen"),
        "train_oof_spin": res_tr[TEST_MODEL], "train_oof_frozen": res_tr["frozen"],
        "flips_spin_vs_frozen_train_oof": flips(pers_tr["spin"], pers_tr["frozen"], "spin", "frozen"),
        "spin_diagnostics_test": spin_diagnostics(S_te, fl_te),
        "n_test_flights": {k: int(v) for k, v in fl_te.label.value_counts().items()},
    }
    if fl_aud is not None:
        # secondary, post-hoc labels (as audit_labels.py): same fitted models, same thresholds
        for nm, fa in (("audited_relabelled", fl_aud),
                       ("audited_drop_rally_continues",
                        fl_aud[fl_aud.audit.fillna("") != "rally_continues"].reset_index(drop=True))):
            S_a, _ = samples(fa, F_te, geo, tracks)
            out[f"test_spin_{nm}_posthoc"] = evaluate(S_a, score_spin(S_a), fa, tau_s, tau_o)[0]
            out[f"test_frozen_{nm}_posthoc"] = evaluate(S_a, score_froz(S_a), fa, tauf_s, tauf_o)[0]
    cs.to_csv(os.path.join(RES, "test_precision_vs_lead_spin_snapshot.csv"), index=False)
    co.to_csv(os.path.join(RES, "test_precision_vs_lead_spin_online.csv"), index=False)
    per = per_spin.rename(columns=lambda c: c if c in ("video", "f_net", "label", "miss_type") else f"spin_{c}")
    fro = per_froz.drop(columns=["video", "f_net", "label", "miss_type"]).add_prefix("frozen_")
    pd.concat([per, fro], axis=1).to_csv(os.path.join(RES, "test_flights_spin_vs_frozen.csv"), index=False)
    json.dump(out, open(os.path.join(RES, "test_summary.json"), "w"), indent=1, default=float)
    plot([("frozen, test (snapshot)", fcs, dict(color="#6c757d", lw=1.5)),
          ("spin, test (snapshot)", cs, dict(color="#d1495b", lw=2)),
          ("frozen, test (online)", fco, dict(color="#6c757d", lw=1.2, ls="--")),
          ("spin, test (online)", co, dict(color="#d1495b", lw=1.2, ls="--")),
          ("spin, train LOGO (snapshot)", curs_tr["spin"][0], dict(color="#2e86ab", lw=1.0))],
         os.path.join(RES, "test_precision_vs_lead_spin.png"),
         "test_1..7 (evaluated once): spin-aware vs frozen model")
    print(json.dumps({k: out[k] for k in ("test_spin", "flips_spin_vs_frozen_test", "frozen_reproduction_check")},
                     indent=1, default=float))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--no-ablation", action="store_true", help="skip the no-spin physics ablation fits")
    a = ap.parse_args()
    if a.dev:
        dev(a)
    elif a.final:
        final(a)
    else:
        sys.exit("use --dev or --final")
