"""Causality of the CV trader's trade set (review fix D2, src/tier0.point_table / simulate / daily_stop).

A decision is which point an order is sent on, when it arrives, which token it buys and whether the call is right.
None of them may change when prices at or after the decision are shifted or shuffled. Fills (shares, fill price,
P&L) may: they are execution, priced off the post-point price. The jump-set benchmark fails the same test, which
is why it is labelled a conditional benchmark. Synthetic data only, except the last test, which reproduces one
committed IS cell of the jump-set benchmark when the IS data files are present (no OOS file is read).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import tier0 as T
from src.tiers import jump_onsets

ROOT = Path(__file__).resolve().parents[1]
DECISION = ["cond", "ts", "d0", "correct", "tau", "early", "phantom"]


# ------------------------------------------------------------------------------------------ fixtures
def _universe(n: int = 3) -> pd.DataFrame:
    start = pd.Timestamp("2026-06-01 10:00", tz="UTC")
    return pd.DataFrame({
        "cond": [f"c{i}" for i in range(n)], "slug": [f"s{i}" for i in range(n)],
        "title": ["A vs B"] * n, "series": ["atp"] * n, "league": ["Wimbledon"] * n,
        "start": [start + pd.Timedelta(hours=3 * i) for i in range(n)],
        "end": [start + pd.Timedelta(hours=3 * i + 2) for i in range(n)],
        "res0": [1.0, 0.0, 1.0][:n], "volume": [2e5] * n, "fee_rate": [0.05] * n, "delay": [1] * n,
        "oos": [False] * n, "prestart_usd": [3e4, 2e4, 1e4][:n]})


def _prints(U: pd.DataFrame, seed: int = 0, n: int = 1500) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for r in U.itertuples():
        t0 = r.start.timestamp()
        ts = np.sort(t0 + rng.uniform(0, 7200, n))
        p = np.clip(0.5 + np.cumsum(rng.normal(0, 0.004, n)), 0.1, 0.9)
        out.append(pd.DataFrame({"cond": r.cond, "ts": ts, "p": p, "usd": rng.uniform(5, 200, n)}))
    return pd.concat(out, ignore_index=True)


def _perturb_after(pr: pd.DataFrame, cut: float, how: str, seed: int = 1) -> pd.DataFrame:
    q = pr.copy()
    m = q.ts.to_numpy() >= cut
    if how == "shift":
        q.loc[m, "p"] = np.clip(q.loc[m, "p"] + 0.2, 0.01, 0.99)
    elif how == "shuffle":
        rng = np.random.default_rng(seed)
        q.loc[m, "p"] = rng.permutation(q.loc[m, "p"].to_numpy())
        q.loc[m, "usd"] = rng.permutation(q.loc[m, "usd"].to_numpy())
    else:
        raise ValueError(how)
    return q


def _pool(n: int = 8, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        row = {"slug": "live", "n": i, "D": rng.uniform(0, 0.08), "R": rng.uniform(-2.0, 0.5),
               "usd_2": 3000.0, "usd_1": 2000.0, "usd_025": 1200.0, "usd_post": 100.0, "V_live": 4e5}
        for lab, _ in T.EDGE_SNAPS:
            S = rng.uniform(2e3, 3e4)
            row[f"S_{lab}"] = row[f"SW_{lab}"] = S
            e, w = rng.uniform(0.002, 0.03), rng.uniform(0.002, 0.03)
            for N in T.EDGE_N:
                row[f"E_{lab}_{N}"] = e * min(N, S)
                row[f"W_{lab}_{N}"] = w * min(N, S)
            row[f"E_{lab}_all"], row[f"W_{lab}_all"] = e * S, w * S
        rows.append(row)
    return pd.DataFrame(rows)


CVS = {"cam": {"leads_ms": [0, 50], "recall": [[0.3], [0.1]], "precision": [1.0, 1.0], "bins_w": [1.0],
               "max_lead_ms": 50, "t_inf": 0.52}}
MIX = {"men": {"out": 0.3}, "women": {"out": 0.3}}
SC = T.replace(T.CORRECTED, cv="cam", pool="all", vol_src="prestart", depth_cap=True, extrap="linear")


def _table(pr, U, seed=0, phantom=10.0):
    P = T.point_table(pr, U, 45.0, seed, phantom, vol_mult=5.0)
    P["tour"] = np.arange(len(P)) % 3
    return P


def _sim(P, U, seed=0):
    return T.simulate(P, U, SC, T.draws(len(P), seed, 8), {"all": _pool()}, CVS, MIX)


def _decisions(calls: pd.DataFrame) -> pd.DataFrame:
    return calls[DECISION].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)


# ------------------------------------------------------------------------------------------ tests
@pytest.mark.parametrize("how", ["shift", "shuffle"])
def test_point_table_uses_no_price_at_or_after_the_point(how):
    U = _universe()
    pr = _prints(U)
    cut = float(np.median(pr.ts))
    P0, P1 = _table(pr, U), _table(_perturb_after(pr, cut, how), U)
    # the points, their times, the called winner and the false calls never depend on any price
    for c in ("cond", "onset_ts", "dir", "phantom"):
        assert (P0[c].to_numpy() == P1[c].to_numpy()).all(), c
    # the stale price the order sees uses prints before tp - 1 s only
    before = (P0.onset_ts.to_numpy() <= cut)
    for c in ("ref", "ref_short"):
        assert np.allclose(P0[c].to_numpy()[before], P1[c].to_numpy()[before], equal_nan=True), c
    # the post-point price is the only column that looks forward (pricing only)
    assert not np.allclose(P0.post30.to_numpy(), P1.post30.to_numpy(), equal_nan=True)


@pytest.mark.parametrize("how", ["shift", "shuffle"])
def test_simulated_orders_do_not_depend_on_future_prices(how):
    U = _universe()
    pr = _prints(U)
    cut = float(np.median(pr.ts))
    P0 = _table(pr, U)
    a = _sim(P0, U)
    assert len(a) > 50 and a.phantom.any() and (~a.correct).any() and a.correct.any()
    # (1) every future price an order is priced off replaced: identical orders, different fills
    P2 = P0.copy()
    P2["post30"] = np.random.default_rng(9).uniform(0.05, 0.95, len(P2))
    b = _sim(P2, U)
    pd.testing.assert_frame_equal(_decisions(a), _decisions(b))
    assert not np.allclose(a.q.to_numpy(), b.q.to_numpy())
    # (2) every print after a cut shifted / shuffled: identical orders up to the cut
    c = _sim(_table(_perturb_after(pr, cut, how), U), U)
    da, dc = _decisions(a), _decisions(c)
    pd.testing.assert_frame_equal(da[da.ts <= cut].reset_index(drop=True), dc[dc.ts <= cut].reset_index(drop=True))


def test_jump_benchmark_does_look_ahead():
    """Negative control: the >= 4c jump set trades at the jump onset, but whether that onset exists is decided by
    prints after it. Flat at 50c until the cut, 60c after: the jump's onset is before the cut, and it disappears
    when only the prices after the cut are flattened."""
    ts = np.arange(0.0, 400.0, 1.0)
    cut = 200.0
    p = np.where(ts < cut, 0.5, 0.6)
    usd = np.full(len(ts), 50.0)
    on = jump_onsets(ts, p, usd)
    assert len(on) == 1 and on[0][0] < cut
    assert jump_onsets(ts, np.full(len(ts), 0.5), usd) == []
    # the point book's orders before the cut are unchanged by the same perturbation
    U = _universe(1)
    t0 = U.start.iloc[0].timestamp()
    pr = pd.DataFrame({"cond": "c0", "ts": t0 + ts * 10, "p": p, "usd": usd})
    flat = pr.assign(p=0.5)
    P0, P1 = _table(pr, U, phantom=0.0), _table(flat, U, phantom=0.0)
    m = P0.onset_ts.to_numpy() <= t0 + cut * 10
    assert m.any()
    assert np.allclose(P0.ref.to_numpy()[m], P1.ref.to_numpy()[m], equal_nan=True)
    assert (P0.dir.to_numpy() == P1.dir.to_numpy()).all()


def test_false_calls_buy_the_called_token_at_stale_plus_slip():
    U = _universe()
    P = _table(_prints(U), U, phantom=60.0)
    calls = _sim(P, U)
    f = calls[calls.phantom]
    assert len(f) > 10
    assert not f.correct.any()
    X = P[P.phantom].set_index(["cond", "onset_ts"])
    k = list(zip(f.cond, f.ts))
    ref = X.loc[k, "ref"].to_numpy()
    d = X.loc[k, "dir"].to_numpy()
    assert (f.d0.to_numpy() == np.where(d > 0, 1.0, -1.0)).all()
    stale = np.where(d > 0, ref, 1 - ref)
    assert np.allclose(f.q.to_numpy(), np.clip(stale + SC.slip, 0.01, 0.99))
    assert np.allclose(f.edge_q.to_numpy(), stale - f.q.to_numpy())
    # same points with or without false calls (separate random stream)
    P0 = _table(_prints(U), U, phantom=0.0)
    assert np.allclose(P0.onset_ts.to_numpy(), P[~P.phantom].onset_ts.to_numpy())
    assert (P0.dir.to_numpy() == P[~P.phantom].dir.to_numpy()).all()


def test_point_book_metrics_split_false_calls():
    U = _universe()
    P = _table(_prints(U), U, phantom=30.0)
    calls = _sim(P, U)
    days = T.period_days(P, "delay1")
    m = T.metrics(calls, days)
    tr = calls[calls.shares > 1e-9]
    assert m["n_trades_phantom"] == int(tr.phantom.sum())
    assert np.isclose(m["pnl_phantom_usd"] + m["pnl_wrong_usd"] + m["pnl_correct_usd"], m["pnl_usd"])
    real = calls[~calls.phantom]
    assert np.isclose(m["calls_share_before_reprice"], float((real.tau >= 0).mean()))


def test_daily_stop_latches_on_marked_pnl_seen_at_the_time():
    day = pd.Timestamp("2026-06-01", tz="UTC")
    ts = 1_780_000_000.0 + np.array([0, 100, 200, 210, 300, 400], float)
    calls = pd.DataFrame({"ts": ts, "date": [day] * 5 + [day + pd.Timedelta(days=1)],
                          "shares": [100.0] * 6, "q": [0.5] * 6, "fee_ps": [0.0] * 6,
                          "mark_px": [0.5, -5.5, 0.5, 0.5, 0.5, -20.0]})
    kept, fired = T.daily_stop(calls, usd=500.0, mark_delay=30.0)
    # day 1: cumulative mark 0, -600 at ts[1] -> orders from ts[1] + 30 s on are dropped; ts[1] itself is kept
    assert fired == 2
    assert list(kept.ts) == [ts[0], ts[1], ts[5]]
    k2, f2 = T.daily_stop(calls, usd=1e9)
    assert f2 == 0 and len(k2) == len(calls)


def test_exante_volume_multiplier_uses_is_matches_only():
    U = pd.DataFrame({"oos": [False, False, True], "prestart_usd": [1.0, 2.0, 1.0], "volume": [10.0, 40.0, 1e6]})
    m = T.exante_volume_multiplier(U)
    assert m == 15.0
    U.loc[2, "volume"] = 3.0
    assert T.exante_volume_multiplier(U) == m


def test_engine_call_model_is_the_measured_held_out_behaviour():
    import json
    sysd = T.engine_cv_system("2")
    run = json.loads(T.ENGINE_CALLS.read_text())["runs"][T.ENGINE_RUN]["A_engine_calls"]["online"]
    g = json.loads(T.ENGINE_GATE.read_text())["results"]["emit"]["2"]
    keep = g["correct_early_kept"] / g["correct_early_total"]
    assert sysd["recall"][0][0] == pytest.approx(run["0ms"]["recall"] * keep)
    assert sysd["phantom_per_h"] == g["outside_flights_per_hour_gated"]
    assert T.engine_cv_system("none")["phantom_per_h"] == g["outside_flights_per_hour_ungated"]
    if T.FROZEN_MODEL.exists():
        assert sysd["inputs"]["models/vision/frozen_call_model.pkl"] == \
            "b798f138c9f36ba44a8898c78a3ef40c3405ce948f5c7458adf4e4fa8d599ed3"


@pytest.mark.skipif(not (ROOT / "data/derived/tier0_jumps_is.parquet").exists()
                    or not (ROOT / "data/derived/tier0_post30_is.parquet").exists(),
                    reason="IS jump table not built (data/ is not in git)")
def test_jump_benchmark_reproduces_a_committed_is_cell():
    """The jump-set benchmark is unchanged by the D2 edits: video V = 0.5 s, tournament reading, own120, IS seed 0
    equals results/tier0/latency_sweep_seeds.csv. IS files only."""
    import os
    import sys
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    from scripts import tier0_latency_sweep as LS
    from src.tape import universe
    S = pd.read_csv(ROOT / "results/tier0/latency_sweep_seeds.csv")
    row = S[(S.source == "video") & (S.reading == "tournament") & (S.x_s == 0.5) & (S.cv == "own120")
            & (S.period == "IS") & (S.seed == 0)].iloc[0]
    J = T.jump_table("is").reset_index(drop=True)
    J["row"] = np.arange(len(J))
    J["post30"] = T.post_prices("is", J)
    u = universe()
    u["prestart_usd"] = u.cond.map(T.prestart_volume(sorted(u.cond))).fillna(0.0)
    tour = T.tournament_codes(u)
    J["tour"] = J.cond.map(tour).astype(int)
    c = {"pools": {p: T.live_points(p) for p in ("D>=3c", "all")}, "cvs": T.cv_systems(), "mix": T.point_mix(),
         "calib": T.calibrate_stamp_lag()}
    sc, cvs = LS.cell("video", "tournament", 0.5, "own120", c)
    calls = T.simulate(J, u.reset_index(drop=True), sc, T.draws(len(J), 0, int(tour.max()) + 1), c["pools"], cvs,
                       c["mix"])
    m = T.metrics(calls, T.period_days(J, sc.regime))
    for k in ("pnl_per_day_usd", "per_share_c", "sharpe_ann", "n_trades", "n_calls"):
        assert m[k] == pytest.approx(float(row[k]), rel=1e-6, abs=1e-6), k
