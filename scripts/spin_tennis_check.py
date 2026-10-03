"""Check that the spin study evaluates on exactly the hawkeye population.

1. src/spin/physics.integrate_truth reproduces hawkeye._integrate (positions, landing times).
2. build_population('nominal', n=60000, seed=7) + hawkeye.predict_landing + hawkeye.calls_at_precision
   reproduces results/hawkeye_tennis_calls.csv.
3. tennis_filter.baseline_predict returns the same landing points as hawkeye.predict_landing.

    .venv/bin/python scripts/spin_tennis_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import hawkeye as H  # noqa: E402
from src.spin import physics as P, tennis_filter as F  # noqa: E402


def main():
    # 1. integrator equivalence on the raw 20k shots
    rng = np.random.default_rng(7)
    s = H.sample_shots(20000, rng)
    land, tl, traj = H._integrate(s["p0"], s["v0"], lambda v, a: H._accel_truth(v, s["w_hat"][a], s["omega"][a]),
                                  record_every=1 / H.FPS)
    w0 = s["omega"][:, None] * s["w_hat"]
    land2, tl2, traj2, _ = P.integrate_truth(s["p0"], s["v0"], w0, 1.0, 0.0, np.zeros(3))
    dpos = np.nanmax(np.abs(traj - traj2))
    print(f"integrator: max |dp| {dpos:.2e} m, max |dt_land| {np.nanmax(np.abs(tl - tl2)):.2e} s")
    assert dpos < 1e-9 and np.array_equal(np.isnan(traj), np.isnan(traj2))

    # 2. the published table
    pop = P.build_population("nominal", n=60000, seed=7)
    W = P.W_FIT
    rows = []
    for L in (0, 25, 50, 100, 150, 200, 300, 400):
        k = np.floor((pop["tland"] - L / 1000.0) * H.FPS).astype(int)
        good = k >= W
        win = np.stack([pop["meas"][i, kk - W + 1:kk + 1] for i, kk in zip(np.flatnonzero(good), k[good])])
        lh = H.predict_landing(win)
        if L == 100:
            lb, _, _ = F.baseline_predict(win)
            print(f"baseline_predict vs hawkeye.predict_landing: max |d| {np.nanmax(np.abs(lb - lh)):.1e} m")
            assert np.allclose(lb, lh, equal_nan=True)
        rows.append({"lead_ms": L, "d": pop["d"][good], "d_hat": H.signed_out_distance(lh, pop["serve"][good]),
                     "serve": pop["serve"][good]})
    mine = pd.DataFrame(H.calls_at_precision(rows))
    ref = pd.read_csv(ROOT / "results/hawkeye_tennis_calls.csv")
    diff = (mine[ref.columns] - ref).abs().max()
    print("max |difference| vs results/hawkeye_tennis_calls.csv per column:")
    print(diff.to_string())
    assert np.nanmax(diff.to_numpy()) < 1e-9
    print(f"OK: {len(pop['d'])} shots, identical to the published table")


if __name__ == "__main__":
    main()
