"""The capacity verifier's fixes to the tier-0 impact model (src/tier0.py), on a synthetic book.

paper; order not sent; CV call on our own streamed footage mapped to a live tennis market for timing (different sport);
feed baseline 1 s is simulated (licensed feed not purchased). No data files are read.
"""
import numpy as np
import pandas as pd

from src import tier0 as T


def _book(S: float = 400_000.0, edge_per_share: float = 0.02, tail_edge: float = 0.001) -> pd.DataFrame:
    """One live point: the first 12,800 shares carry `edge_per_share` each, the rest of the side `tail_edge` each."""
    row = {"usd_2": 1000.0, "usd_1": 800.0, "usd_025": 500.0, "usd_post": 0.0}
    for lab, _ in T.EDGE_SNAPS:
        row[f"S_{lab}"] = S
        row[f"SW_{lab}"] = S
        for N in T.EDGE_N:
            row[f"E_{lab}_{N}"] = edge_per_share * min(N, S)
            row[f"W_{lab}_{N}"] = edge_per_share * min(N, S)
        top = edge_per_share * min(T.EDGE_N[-1], S)
        row[f"E_{lab}_all"] = top + tail_edge * max(S - T.EDGE_N[-1], 0)
        row[f"W_{lab}_all"] = row[f"E_{lab}_all"]
    return pd.DataFrame([row])


def _ps(curve, n, extrap, side="E", tau=1.5):
    idx = np.zeros(len(n), int)
    return T.curve_per_share(curve, side, idx, np.asarray(n, float), np.ones(len(n)), np.full(len(n), tau), "zero",
                             extrap)


def test_default_is_the_committed_model():
    c = _book()
    n = np.array([100.0, 5_000.0, 20_000.0, 300_000.0])
    assert np.allclose(_ps(c, n, "all"), T.curve_per_share(c, "E", np.zeros(4, int), n, np.ones(4), np.full(4, 1.5), "zero"))


def test_linear_extrapolation_is_continuous_and_bounded():
    c = _book()
    below = _ps(c, [12_799.0], "linear")[0]
    at = _ps(c, [12_800.0], "linear")[0]
    above = _ps(c, [12_801.0], "linear")[0]
    assert abs(below - 0.02) < 1e-9 and abs(at - 0.02) < 1e-9
    assert abs(above - at) < 1e-5                      # no jump at the last grid point (committed: +0.03)
    whole = _ps(c, [400_000.0], "linear")[0]
    S, top = 400_000.0, 0.02 * 12_800
    assert abs(whole - (top + 0.001 * (S - 12_800)) / S) < 1e-9
    # the committed model's jump: 20,000 shares get the WHOLE side's value spread over 20,000 shares
    committed = _ps(c, [20_000.0], "all")[0]
    fixed = _ps(c, [20_000.0], "linear")[0]
    assert committed > 0.03 and fixed < 0.014          # 0.0132 after the fix vs 0.0322 before (whole side / 20,000)


def test_shares_resting_interpolates_like_the_dollar_depth():
    c = _book()
    for col in ("S_2", "S_1", "S_025"):
        c[col] = {"S_2": 3000.0, "S_1": 2000.0, "S_025": 500.0}[col]
    tau = np.array([3.0, 2.0, 1.5, 1.0, 0.625, 0.25, 0.1])
    got = T.shares_resting(c, "E", np.zeros(len(tau), int), tau)
    assert np.allclose(got, [3000, 3000, 2500, 2000, 1250, 500, 500])


def test_scenario_defaults_unchanged():
    sc = T.CORRECTED
    assert (sc.depth_cap, sc.extrap, sc.alloc) == (False, "all", "best")
    assert "dcap" not in sc.key()
