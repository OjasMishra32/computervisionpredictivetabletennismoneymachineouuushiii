"""Run every tennis landing predictor on one simulated world and save per-shot predictions.

    .venv/bin/python scripts/spin_tennis_eval.py --cond nominal          # seed 7, n 60000 (4948 shots)
    .venv/bin/python scripts/spin_tennis_eval.py --cond decay --max-shots 500   # quick look

Worlds (src/spin/physics.py CONDITIONS): nominal (exactly hawkeye.simulate), exact_t (truth sampled
on the exact frame clock), cd15, decay, wind, noise2x, all (the four together), spin_mix
(slice / sidespin / gyro spin). Population: hawkeye.sample_shots, seed 7, n 60000, same filters,
in/out balancing and noise stream as results/hawkeye_tennis_calls.csv. aero: 10 % less lift than the
filters assume plus spin-dependent drag (a stand-in for not knowing the aerodynamic curves exactly).

Methods
  baseline     src/hawkeye.py predictor (150 ms local quadratic + backed-out spin)
  bls          batch fit from contact, unknowns p0 v0 w0 Cd                     (model M0)
  bls_decay    ... plus spin decay rate                                          (M1)
  bls_wind     ... plus horizontal wind                          (M2, only with --models M0 M1 M2)
  bls_bma      Bayesian model average of the models run (default M0/M1; Laplace evidence,
               common noise scale)
  ukf          cubature Kalman filter on [p v w Cd], per frame                   (M0)
  ukf_decay, ukf_wind  the same filter with decay / wind states
  ukf_mm       multiple-model bank of the filters weighted by their innovation likelihoods
  bls_cal, ukf_cal   M0 with spin decay and wind held at a session calibration pooled from the
               complete flights of the other half of the shots (2-fold cross-fit), i.e. what a
               tracker learns from earlier rallies in the same air with the same balls
Output: results/spin/tennis/raw/<cond>_s<seed>.parquet (one row per method x lead x shot).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import hawkeye as H  # noqa: E402
from src.spin import physics as P, tennis_filter as F  # noqa: E402

OUT = ROOT / "results/spin/tennis"
LEADS = (0, 25, 50, 100, 150, 200, 250, 300, 350, 400)
HK_LEADS = (0, 25, 50, 100, 150, 200, 300, 400)     # results/hawkeye_tennis_calls.csv leads
ALL_MODELS = {"M0": {}, "M1": {"est_decay": True}, "M2": {"est_wind": True}}
MODELS = {m: ALL_MODELS[m] for m in ("M0", "M1")}
BLS_NAME = {"M0": "bls", "M1": "bls_decay", "M2": "bls_wind"}
UKF_NAME = {"M0": "ukf", "M1": "ukf_decay", "M2": "ukf_wind"}


def decision_frames(pop: dict, L: int):
    """Last frame at or before t_land - L (hawkeye's rule) and the shots with a full 150 ms
    baseline window. Frames the recorder stamped after the bounce (NaN) are stepped over."""
    meas = pop["meas"]
    K = meas.shape[1]
    k = np.floor((pop["tland"] - L / 1000.0) * H.FPS).astype(int)
    good = k >= P.W_FIT
    ku = np.clip(k, 0, K - 1)
    i = np.arange(len(k))
    for _ in range(4):
        bad = good & ~np.isfinite(meas[i, ku, 0])
        ku = np.where(bad, ku - 1, ku)
    return k, ku, good


def load_q() -> dict:
    f = OUT / "ukf_tuning.json"
    if f.exists():
        j = json.loads(f.read_text())
        return {"q_a": j["q_a"], "q_w": j["q_w"], "q_c": j["q_c"]}
    return dict(F.UKF_DEFAULT)


def rows(method, L, pop, sel, ku, land, cov=None, pout=None, w_est=None, extra=None):
    d = pop["d"][sel]
    serve = pop["serve"][sel]
    dh = H.signed_out_distance(land, serve)
    out = {"method": method, "lead_ms": L, "shot": np.flatnonzero(sel), "kind": pop["kind"][sel],
           "d": d, "d_hat": dh,
           "ex": land[:, 0] - pop["land"][sel, 0], "ey": land[:, 1] - pop["land"][sel, 1]}
    out["sd_d"] = F.sd_signed_distance(land, cov, serve) if cov is not None else np.nan
    out["p_out"] = pout if pout is not None else np.nan
    if w_est is not None:
        wt = P.true_spin_at(pop, sel, ku[sel])
        vt = P.true_vel_at(pop, sel, ku[sel])
        for j, a in enumerate("xyz"):
            out[f"w_hat_{a}"] = w_est[:, j]
            out[f"w_true_{a}"] = wt[:, j]
            out[f"v_true_{a}"] = vt[:, j]
    for kk, v in (extra or {}).items():
        out[kk] = v
    return pd.DataFrame(out)


def run(cond: str, seed: int = 7, n: int = 60000, max_shots: int | None = None, methods=None, leads=None):
    LEADS = tuple(leads or (globals()["LEADS"] if cond == "nominal" else HK_LEADS))
    t_all = time.time()
    pop = P.build_population(cond, n=n, seed=seed)
    if max_shots:
        keep = np.sort(np.random.default_rng(0).choice(len(pop["d"]), min(max_shots, len(pop["d"])), replace=False))
        for key in ("traj", "meas", "land", "tland", "d", "serve", "p0", "v0", "w0", "c", "lam", "wind", "kind", "idx"):
            pop[key] = pop[key][keep]
    meas, serve = pop["meas"], pop["serve"]
    ns = len(pop["d"])
    print(f"[{cond}] {ns} shots, K={meas.shape[1]} frames, built in {time.time() - t_all:.0f}s", flush=True)
    fr = {L: decision_frames(pop, L) for L in LEADS}
    methods = methods or ["baseline", "bls", "ukf"]
    out, timing = [], {}

    # ---------------- baseline
    if "baseline" in methods:
        t0 = time.time()
        for L in LEADS:
            k, ku, good = fr[L]
            idx = np.flatnonzero(good)
            win = np.stack([meas[i, ku[i] - P.W_FIT + 1: ku[i] + 1] for i in idx])
            land, spin, _ = F.baseline_predict(win)
            out.append(rows("baseline", L, pop, good, ku, land, w_est=spin))
        timing["baseline"] = time.time() - t0

    # ---------------- batch fits (warm-started from the previous, shorter arc)
    if "bls" in methods:
        t0 = time.time()
        th = {m: F._init_theta(meas, np.full(ns, 50)) for m in MODELS}
        for L in sorted(LEADS, reverse=True):
            k, ku, good = fr[L]
            fits, lds, pos = {}, {}, {}
            for m, kw in MODELS.items():
                r = F.bls_fit(meas[good], ku[good], theta0=th[m][good], max_iter=15 if m != "M2" else 8, **kw)
                th[m][good] = r["theta"]
                ld = F.landing_distribution(r["y"], r["ycov"], r["active"])
                po = F.p_out(ld["land"], ld["cov"], serve[good])
                fits[m], lds[m], pos[m] = r, ld, po
                y = r["y"]
                out.append(rows(BLS_NAME[m], L, pop, good, ku, ld["land"], ld["cov"], po, y[:, 6:9],
                                {"c_hat": y[:, 9], "lam_hat": y[:, 10], "wind_x_hat": y[:, 11],
                                 "wind_y_hat": y[:, 12], "chi2r": r["chi2r"], "iters": r["iters"],
                                 "t_go": ld["t_go"]}))
            s_hat = P.NOISE * np.sqrt(np.maximum(fits["M0"]["chi2r"], 1.0))
            w = F.model_weights([F.log_evidence(fits[m], s_hat) for m in MODELS])
            mix = F.mixture([lds[m] for m in MODELS], w, [pos[m] for m in MODELS])
            w_est = sum(w[i][:, None] * fits[m]["y"][:, 6:9] for i, m in enumerate(MODELS))
            ext = {f"w_{m}": w[i] for i, m in enumerate(MODELS)}
            ext["c_hat"] = sum(w[i] * fits[m]["y"][:, 9] for i, m in enumerate(MODELS))
            ext["lam_hat"] = sum(w[i] * fits[m]["y"][:, 10] for i, m in enumerate(MODELS))
            out.append(rows("bls_bma", L, pop, good, ku, mix["land"], mix["cov"], mix["p_out"], w_est, ext))
            print(f"[{cond}] bls lead {L}: iters " + " ".join(f"{m}:{fits[m]['iters']}" for m in MODELS)
                  + f", {time.time() - t0:.0f}s", flush=True)
        timing["bls_all_models"] = time.time() - t0

        # session calibration: spin decay rate and wind are properties of the ball and the air,
        # shared by every shot. Estimate them jointly over the complete flights of the OTHER half
        # of the shots (2-fold cross-fit; tennis_filter.calibrate_environment), then refit every
        # shot with them held fixed.
        t0 = time.time()
        k, ku, good = fr[0]
        fold = np.arange(ns) % 2
        fixed = np.tile(F.PRIOR_MEAN, (ns, 1))
        timing["env_cal"] = {}
        for f in (0, 1):
            src = good & (fold != f)
            env, env_cov, _ = F.calibrate_environment(meas[src], ku[src], th["M0"][src])
            fixed[np.ix_(fold == f, F.ENV)] = env
            sd = np.sqrt(np.diag(env_cov))
            timing["env_cal"][f"fold{f}"] = {"lam": float(env[0]), "wind_x": float(env[1]), "wind_y": float(env[2]),
                                             "sd": [float(x) for x in sd], "n_src": int(src.sum())}
        print(f"[{cond}] session calibration: {timing['env_cal']}", flush=True)
        thc = th["M0"].copy()
        for L in sorted(LEADS, reverse=True):
            k, ku, good = fr[L]
            r = F.bls_fit(meas[good], ku[good], theta0=thc[good], fixed=fixed[good], max_iter=15)
            thc[good] = r["theta"]
            ld = F.landing_distribution(r["y"], r["ycov"], r["active"])
            po = F.p_out(ld["land"], ld["cov"], serve[good])
            y = r["y"]
            out.append(rows("bls_cal", L, pop, good, ku, ld["land"], ld["cov"], po, y[:, 6:9],
                            {"c_hat": y[:, 9], "lam_hat": y[:, 10], "wind_x_hat": y[:, 11],
                             "wind_y_hat": y[:, 12], "chi2r": r["chi2r"], "iters": r["iters"], "t_go": ld["t_go"]}))
        timing["bls_cal"] = time.time() - t0

    # ---------------- recursive filters (one causal pass records every lead)
    if "ukf" in methods:
        t0 = time.time()
        q = load_q()
        rec = {L: np.where(fr[L][2], fr[L][1], -1) for L in LEADS}
        U = {}
        for m, kw in MODELS.items():
            t1 = time.time()
            U[m] = F.ukf_run(meas, rec, q=q, **kw)
            timing[f"ukf_{m}_pass"] = time.time() - t1
        if "bls" in methods:   # same session calibration, recursive filter
            Uc = F.ukf_run(meas, rec, q=q, fixed=fixed)
            for L in LEADS:
                k, ku, good = fr[L]
                u = Uc[L]
                ld = F.landing_distribution(u["y"][good], u["ycov"][good], Uc["active"], q_a=q["q_a"])
                po = F.p_out(ld["land"], ld["cov"], serve[good])
                y = u["y"][good]
                out.append(rows("ukf_cal", L, pop, good, ku, ld["land"], ld["cov"], po, y[:, 6:9],
                                {"c_hat": y[:, 9], "lam_hat": y[:, 10], "wind_x_hat": y[:, 11],
                                 "wind_y_hat": y[:, 12], "t_go": ld["t_go"]}))
        for L in LEADS:
            k, ku, good = fr[L]
            lds, pos = {}, {}
            for m in MODELS:
                u = U[m][L]
                ld = F.landing_distribution(u["y"][good], u["ycov"][good], U[m]["active"], q_a=q["q_a"])
                po = F.p_out(ld["land"], ld["cov"], serve[good])
                lds[m], pos[m] = ld, po
                y = u["y"][good]
                out.append(rows(UKF_NAME[m], L, pop, good, ku, ld["land"], ld["cov"], po, y[:, 6:9],
                                {"c_hat": y[:, 9], "lam_hat": y[:, 10], "wind_x_hat": y[:, 11],
                                 "wind_y_hat": y[:, 12],
                                 "nis": U[m][L]["nis"][good] / np.maximum(3 * U[m][L]["cnt"][good], 1),
                                 "t_go": ld["t_go"]}))
            u0 = U["M0"][L]
            tau = np.maximum(u0["nis"][good] / np.maximum(3 * u0["cnt"][good], 1), 1.0)
            ll = [-0.5 * (U[m][L]["nis"][good] / tau + U[m][L]["ldet"][good]) for m in MODELS]
            w = F.model_weights(ll)
            mix = F.mixture([lds[m] for m in MODELS], w, [pos[m] for m in MODELS])
            w_est = sum(w[i][:, None] * U[m][L]["y"][good, 6:9] for i, m in enumerate(MODELS))
            ext = {f"w_{m}": w[i] for i, m in enumerate(MODELS)}
            ext["c_hat"] = sum(w[i] * U[m][L]["y"][good, 9] for i, m in enumerate(MODELS))
            ext["lam_hat"] = sum(w[i] * U[m][L]["y"][good, 10] for i, m in enumerate(MODELS))
            out.append(rows("ukf_mm", L, pop, good, ku, mix["land"], mix["cov"], mix["p_out"], w_est, ext))
        timing["ukf_all_models"] = time.time() - t0
        timing["ukf_q"] = q

    df = pd.concat(out, ignore_index=True)
    df.insert(0, "cond", cond)
    df.insert(1, "seed", seed)
    df["c_true"] = pop["c"][df.shot.to_numpy()]
    raw = OUT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    tag = f"{cond}_s{seed}" + (f"_m{max_shots}" if max_shots else "")
    df.to_parquet(raw / f"{tag}.parquet", index=False)
    timing["total_s"] = time.time() - t_all
    timing["n_shots"] = ns
    (raw / f"{tag}_timing.json").write_text(json.dumps(timing, indent=1, default=float))
    print(f"[{cond}] wrote {raw / (tag + '.parquet')} ({len(df)} rows) in {timing['total_s']:.0f}s", flush=True)
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", nargs="+", default=["nominal"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n", type=int, default=60000)
    ap.add_argument("--max-shots", type=int, default=None)
    ap.add_argument("--methods", nargs="+", default=["baseline", "bls", "ukf"])
    ap.add_argument("--models", nargs="+", default=["M0", "M1"], help="physics models in the BMA / multi-model banks")
    ap.add_argument("--leads", type=int, nargs="+", default=None,
                    help="default: 0..400 in 25-50 ms steps for nominal, the hawkeye table's 8 leads otherwise")
    a = ap.parse_args()
    MODELS = {m: ALL_MODELS[m] for m in a.models}
    for c in a.cond:
        d = run(c, a.seed, a.n, a.max_shots, a.methods, a.leads)
        if a.max_shots:
            g = d.assign(e=d.d_hat - d.d).groupby(["method", "lead_ms"]).e
            print((g.apply(lambda e: np.sqrt(np.mean(e**2))) * 100).unstack().round(2).to_string())
