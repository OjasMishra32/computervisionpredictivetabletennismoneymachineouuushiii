"""Pick the UKF process noise on a tuning population that is NOT the evaluation population.

Tuning worlds: seed 11 (evaluation uses seed 7), conditions 'nominal' and 'dev' (Cd +-10 %,
spin decay 1 %/100 ms, 1 m/s wind on both horizontal axes: milder and differently shaped than
the evaluation's stress tests). Objective: mean log landing RMSE over leads 100/200/300 ms and both
worlds (scale-free, so the matched world counts as much as the mismatched one), single-model UKF
on [p, v, w, Cd]. Grid points already in ukf_tuning.csv are not rerun.

    .venv/bin/python scripts/spin_tennis_tune.py      # -> results/spin/tennis/ukf_tuning.{csv,json}
"""
from __future__ import annotations

import argparse
import itertools
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
LEADS = (100, 200, 300)


def main(qa_list, qw_list):
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / "ukf_tuning.csv"
    old = pd.read_csv(f) if f.exists() else pd.DataFrame(columns=["q_a", "q_w"])
    done = set(zip(old.q_a.round(12), old.q_w.round(12)))
    grid = [g for g in itertools.product(qa_list, qw_list) if (round(g[0], 12), round(g[1], 12)) not in done]
    worlds = {c: P.build_population(c, n=20000, seed=11) for c in ("nominal", "dev")} if grid else {}
    rows = []
    for q_a, q_w in grid:
        q = {"q_a": q_a, "q_w": q_w, "q_c": 1e-6}
        t0 = time.time()
        for c, pop in worlds.items():
            rec = {}
            for L in LEADS:
                k = np.floor((pop["tland"] - L / 1000) * H.FPS).astype(int)
                rec[L] = np.where(k >= P.W_FIT, k, -1)
            u = F.ukf_run(pop["meas"], rec, q=q)
            for L in LEADS:
                g = rec[L] >= 0
                ld = F.landing_distribution(u[L]["y"][g], u[L]["ycov"][g], u["active"], q_a=q_a)
                dh = H.signed_out_distance(ld["land"], pop["serve"][g])
                e = dh - pop["d"][g]
                sd = F.sd_signed_distance(ld["land"], ld["cov"], pop["serve"][g])
                rows.append({"q_a": q_a, "q_w": q_w, "world": c, "lead_ms": L,
                             "rmse_cm": float(np.sqrt(np.mean(e**2)) * 100), "z_sd": float(np.std(e / sd))})
        print(f"q_a {q_a:g} q_w {q_w:g}: {time.time() - t0:.0f}s", flush=True)
    df = pd.concat([old, pd.DataFrame(rows)], ignore_index=True) if rows else old
    df.to_csv(f, index=False)
    score = df.assign(lr=np.log(df.rmse_cm)).groupby(["q_a", "q_w"]).lr.mean().sort_values()
    print(np.exp(score).head(8).rename("geomean_rmse_cm"))
    best = score.index[0]
    (OUT / "ukf_tuning.json").write_text(json.dumps({"q_a": best[0], "q_w": best[1], "q_c": 1e-6,
                                                     "geomean_rmse_cm": float(np.exp(score.iloc[0])),
                                                     "objective": "mean log RMSE, leads 100/200/300, worlds nominal+dev, seed 11"}, indent=1))
    print("best", best)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", type=float, nargs="+", default=[1e-5, 1e-4, 1e-3, 1e-2])
    ap.add_argument("--qw", type=float, nargs="+", default=[0.1, 10, 100, 300, 1000, 3000, 10000])
    a = ap.parse_args()
    main(a.qa, a.qw)
