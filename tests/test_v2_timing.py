"""Executable timing of v2 (D1): hand-built event sequences for the strict detection labels and the copier.

The frozen rule (strict=False) labels every print in the detection second, including the print that fires the
detector and prints that came before it, as 0-3 s after the jump. The strict labels and the copier may only use
prints known to come after the trigger print, and the copier acts only after the fast print has been seen plus
network leg, taker hold and block lag.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import tiers, v2  # noqa: E402

LAG, NET = 1.976, 0.067      # results/decay/decay.json latency_inputs: block lag median, net_florida_s


# ------------------------------------------------------------------------------------------------ fixtures
def _row(i, ts, p, ask, usd=100.0, cond="m1", seq=None):
    return {"id": i, "cond": cond, "ts": float(ts), "p": p, "usd": usd, "dir": 1.0 if ask else -1.0,
            "seq": i if seq is None else seq}


def jump_tape(cond="m1"):
    """Flat 0.50 tape, then a jump fired inside second 1103 by the big print X2.

    Second 1103 in true order: X1 (before the trigger), X2 (the trigger), X3 (after the trigger)."""
    rows, i = [], 0
    for t in range(1000, 1101, 5):
        rows.append(_row(i, t, 0.50, ask=(t // 5) % 2 == 0, cond=cond)); i += 1
    rows.append(_row(i, 1103, 0.50, ask=False, cond=cond)); i += 1            # X1
    rows.append(_row(i, 1103, 0.62, ask=True, usd=500.0, cond=cond)); i += 1  # X2: fires the detector
    rows.append(_row(i, 1103, 0.62, ask=True, cond=cond)); i += 1             # X3
    for t in (1104, 1105, 1106, 1107, 1115):
        rows.append(_row(i, t, 0.62, ask=True, cond=cond)); i += 1
    return pd.DataFrame(rows)


def _by_id(df, col):
    return df.set_index("id")[col]


def random_tapes(seed=0, n_cond=6, n=1500):
    rng = np.random.default_rng(seed)
    parts = []
    for c in range(n_cond):
        ts = np.sort(rng.integers(0, 4 * 3600, n)).astype(float)
        steps = rng.choice([0, 0, 0, 0.01, -0.01, 0.06, -0.06], n, p=[.5, .1, .1, .12, .12, .03, .03])
        p = np.clip(0.5 + np.cumsum(steps), 0.02, 0.98)
        parts.append(pd.DataFrame({"cond": f"c{c}", "ts": ts, "p": p, "usd": rng.exponential(80, n) + 1,
                                   "dir": rng.choice([-1.0, 1.0], n)}))
    return pd.concat(parts, ignore_index=True)


# ------------------------------------------------------------------------------------------------ labels
def test_detector_fires_on_the_big_print_in_second_1103():
    t = jump_tape()
    on = v2._detections(t.ts.to_numpy(), t.p.to_numpy(), t.usd.to_numpy())
    assert len(on) == 1
    assert on[0][0] == 1103.0 and on[0][1] == 1.0
    assert t.id.iloc[on[0][2]] == t.id[(t.ts == 1103) & (t.usd == 500.0)].item()


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_detector_copy_equals_the_frozen_detector(seed):
    for c, g in random_tapes(seed=seed).sort_values(["cond", "ts"], kind="stable").groupby("cond"):
        ts, p, usd = g.ts.to_numpy(), g.p.to_numpy(), g.usd.to_numpy()
        ref = tiers.jump_onsets(ts, p, usd)
        mine = v2._detections(ts, p, usd)
        assert len(ref) > 0
        assert [(o[3], o[1]) for o in ref] == [(o[0], o[1]) for o in mine]
        assert all(ts[o[2]] == o[0] for o in mine)


def test_frozen_detector_file_is_untouched():
    import hashlib
    got = hashlib.sha256((ROOT / "src/tiers.py").read_bytes()).hexdigest()
    assert got == "46a79d75409fd416fdfc2e026c25f02d9ebb3a188a9de1a6ac353561f656363e"   # maker / tier0_v3 PREREG


def test_frozen_labels_put_the_whole_detection_second_in_0_3s():
    lab = tiers.add_causal_bucket(jump_tape())
    b = _by_id(lab, "bucket_c")
    det_second = lab.id[lab.ts == 1103]
    assert (b[det_second] == "0-3s").all()           # X1 (before the trigger), X2 (the trigger), X3
    assert b[lab.id[lab.ts == 1104].item()] == "0-3s" and b[lab.id[lab.ts == 1105].item()] == "0-3s"
    assert b[lab.id[lab.ts == 1106].item()] == "3-6s"


def test_strict_excludes_trigger_earlier_prints_and_the_whole_unordered_second():
    lab = v2.strict_causal_bucket(jump_tape())
    b, s, d = _by_id(lab, "bucket_cs"), _by_id(lab, "since_det_s"), _by_id(lab, "det_ts_s")
    for i in lab.id[lab.ts <= 1103]:                  # the trigger, X1, X3 and the flat tape before
        assert b[i] == "no jump" and s[i] == -1.0 and np.isnan(d[i])
    for t in (1104, 1105, 1106):                      # 0 < ts - detect <= 3
        i = lab.id[lab.ts == t].item()
        assert b[i] == "0-3s" and s[i] == t - 1103 and d[i] == 1103.0
    assert b[lab.id[lab.ts == 1107].item()] == "3-6s"
    assert b[lab.id[lab.ts == 1115].item()] == "10-20s"
    assert (lab.with_jump_det_s[lab.bucket_cs == "0-3s"] == 1.0).all()   # ask prints, up-jump


def test_strict_with_reliable_order_keeps_only_prints_after_the_trigger():
    lab = v2.strict_causal_bucket(jump_tape(), order_col="seq")
    b = _by_id(lab, "bucket_cs")
    sec = lab[lab.ts == 1103].sort_values("seq")
    x1, x2, x3 = sec.id.tolist()
    assert b[x1] == "no jump" and b[x2] == "no jump"  # before the trigger, and the trigger itself
    assert b[x3] == "0-3s" and _by_id(lab, "since_det_s")[x3] == 0.0
    assert b[lab.id[lab.ts == 1104].item()] == "0-3s"


def test_strict_labels_do_not_depend_on_row_order_within_a_second():
    base = v2.strict_causal_bucket(jump_tape())
    rng = np.random.default_rng(1)
    for _ in range(5):
        t = jump_tape()
        sec = t.index[t.ts == 1103].to_numpy()
        t.loc[sec] = t.loc[rng.permutation(sec)].to_numpy()          # shuffle rows inside second 1103
        lab = v2.strict_causal_bucket(t)
        pd.testing.assert_series_equal(_by_id(lab, "bucket_cs").sort_index(), _by_id(base, "bucket_cs").sort_index())
        pd.testing.assert_series_equal(_by_id(lab, "since_det_s").sort_index(), _by_id(base, "since_det_s").sort_index())


def test_strict_never_labels_a_print_at_or_before_its_detection_second():
    lab = v2.strict_causal_bucket(random_tapes())
    known = lab.since_det_s >= 0
    assert known.sum() > 0
    assert (lab.ts[known] > lab.det_ts_s[known]).all()
    assert (lab.bucket_cs[~known] == "no jump").all()
    w = lab.bucket_cs == "0-3s"
    assert ((lab.since_det_s[w] > 0) & (lab.since_det_s[w] <= 3)).all()


def test_strict_labels_leave_the_frozen_labels_untouched():
    p = random_tapes(seed=3)
    frozen = tiers.add_causal_bucket(p)
    both = v2.strict_causal_bucket(frozen)
    pd.testing.assert_frame_equal(both[frozen.columns], frozen)
    # where the frozen label says 0-3 s inside the detection second, the strict label never does
    det_second = both.since_det == 0
    assert det_second.sum() > 0
    assert (both.bucket_cs[det_second] != "0-3s").all()


def test_match_without_any_jump_does_not_crash():
    flat = pd.DataFrame([_row(i, 1000 + 5 * i, 0.5, ask=i % 2 == 0) for i in range(40)])
    assert (v2.strict_causal_bucket(flat).bucket_cs == "no jump").all()


# ------------------------------------------------------------------------------------------------ copier
def copier_tape():
    """ts, p0, at_ask. The fast print is the ask print at 100; the detection fired in second 99."""
    ts = np.array([95, 99, 100, 101, 102, 103, 104, 110], float)
    p = np.array([0.50, 0.58, 0.60, 0.61, 0.58, 0.63, 0.65, 0.60])
    ask = np.array([False, True, True, True, False, True, True, False])
    return ts, p, ask


def test_copier_arrives_after_fast_print_plus_network_hold_and_block_lag():
    tau = v2.copier_arrival([100.0], [99.0], [1.0], LAG, NET)
    assert tau[0] == pytest.approx(100 + NET + 1 + LAG)
    tau = v2.copier_arrival([100.0], [102.0], [1.0], LAG, NET)          # detection known later than the print
    assert tau[0] == pytest.approx(102 + NET + 1 + LAG)
    tau = v2.copier_arrival([100.0], [np.nan], [3.0], LAG, NET)         # 3 s taker hold before May 2026
    assert tau[0] == pytest.approx(100 + NET + 3 + LAG)


def test_central_copier_takes_the_first_same_side_print_at_or_after_arrival():
    ts, p, ask = copier_tape()
    f = v2.copier_fill(ts, p, ask, [100.0], [1.0], [99.0], [1.0], LAG, NET, "next_same")
    # tau = 103.043: the ask at 103 (0.63) is before the copier arrives; it pays the ask print at 104
    assert f["tau"][0] == pytest.approx(103.043)
    assert f["fill_ts"][0] == 104.0 and f["c0"][0] == pytest.approx(0.65) and f["same"][0]
    assert f["fill_ts"][0] > 100.0                                         # never the fast print or earlier


def test_harsh_copier_falls_back_to_mid_plus_half_spread():
    ts, p, ask = copier_tape()
    f = v2.copier_fill(ts, p, ask, [100.0], [1.0], [99.0], [1.0], 2.974, NET, "next_same")
    # tau = 104.041: no ask print at/after it; first print at/after tau is the bid at 110:
    # mid = (0.65 + 0.60) / 2, spread 0.05 -> + 0.025
    assert np.isnan(f["fill_ts"][0]) and not f["same"][0] and not f["beyond"][0]
    assert f["c0"][0] == pytest.approx(0.65)


def test_sell_side_copier_and_tape_end():
    ts, p, ask = copier_tape()
    f = v2.copier_fill(ts, p, ask, [102.0], [-1.0], [99.0], [1.0], LAG, NET, "next_same")
    # sell copier of the bid print at 102: tau = 105.043, first bid print at/after it is 110 (0.60)
    assert f["fill_ts"][0] == 110.0 and f["c0"][0] == pytest.approx(0.60)
    f = v2.copier_fill(ts, p, ask, [109.0], [1.0], [108.0], [1.0], LAG, NET, "next_same")
    assert f["beyond"][0] and not f["same"][0]
    assert np.isnan(f["c0"][0]) and np.isnan(f["fill_ts"][0])              # no evidence of an executable fill


def test_optimistic_bound_uses_last_same_side_print_before_arrival():
    ts, p, ask = copier_tape()
    f = v2.copier_fill(ts, p, ask, [100.0], [1.0], [99.0], [1.0], LAG, NET, "prev_same")
    assert f["fill_ts"][0] == 103.0 and f["c0"][0] == pytest.approx(0.63)
    f = v2.copier_fill(ts, p, ask, [100.0], [1.0], [99.0], [1.0], 0.0, 0.0, "prev_same")
    # even with zero latency (tau = 101) it is never earlier than the fast print itself
    assert f["fill_ts"][0] >= 100.0


def test_copier_book_pnl_identity():
    tr = pd.DataFrame({"dir": [1.0, -1.0], "res": [1.0, 1.0], "rate": [0.05, 0.05], "shares": [10.0, 20.0],
                       "c0_central": [0.65, 0.40], "beyond_central": [False, False]})
    b = v2.copier_book(tr, "central")
    q = np.array([0.65, 0.60])
    ps = np.array([1 - 0.65, -(1 - 0.40)]) - 0.05 * q * (1 - q)
    np.testing.assert_allclose(b.q, q)
    np.testing.assert_allclose(b.pnl_ps, ps)
    np.testing.assert_allclose(b.pnl, tr.shares * ps)
    np.testing.assert_allclose(b.usd_in, tr.shares * q)


@pytest.mark.parametrize("price", ["next_same", "prev_same"])
def test_order_after_tape_end_has_no_fill_even_for_the_optimistic_bound(price):
    ts, p, ask = copier_tape()
    f = v2.copier_fill(ts, p, ask, [109.0], [1.0], [108.0], [1.0], LAG, NET, price)
    assert f["tau"][0] > ts[-1]
    assert f["beyond"][0] and not f["same"][0]
    assert np.isnan(f["c0"][0]) and np.isnan(f["fill_ts"][0])


def test_empty_recorded_tape_cannot_supply_an_execution_price():
    f = v2.copier_fill([], [], [], [100.0], [1.0], [99.0], [1.0], LAG, NET, "next_same")
    assert f["beyond"].tolist() == [True]
    assert np.isnan(f["c0"][0]) and np.isnan(f["fill_ts"][0])


def test_copier_book_excludes_unsupported_attempts_from_every_economic_total():
    tr = pd.DataFrame({"dir": [1.0, 1.0, 1.0], "res": [1.0, 1.0, 1.0], "rate": [0.05] * 3,
                       "shares": [10.0, 100000.0, 100000.0], "c0_central": [0.65, 0.01, np.nan],
                       "beyond_central": [False, True, False]})
    b = v2.copier_book(tr, "central")
    assert b.index.tolist() == [0]
    assert b.shares.sum() == 10.0
    assert b.usd_in.sum() == pytest.approx(6.5)
    assert b.pnl.sum() == pytest.approx(10 * (0.35 - 0.05 * 0.65 * 0.35))


def test_copier_book_requires_execution_coverage():
    with pytest.raises(ValueError, match="execution coverage"):
        v2.copier_book(pd.DataFrame({"c0_central": [0.01]}), "central")


def test_copier_reprice_uses_strict_detection_and_in_play_tape():
    ts, p, ask = copier_tape()
    tape = pd.DataFrame({"timestamp": ts.astype(int), "p0": p, "at_ask": ask, "size": 1.0, "usd": 1.0,
                         "proxyWallet": "w"})
    u = pd.DataFrame({"start": [pd.Timestamp(90, unit="s", tz="UTC")], "end": [pd.Timestamp(200, unit="s", tz="UTC")]},
                     index=["m1"])
    trades = pd.DataFrame({"cond": ["m1"], "ts": [100.0], "dir": [1.0], "det_ts_s": [99.0], "delay": [1]})
    r = v2.copier_reprice(trades, u, {"median": LAG, "p90": 2.974, "net_s": NET}, tape_loader=lambda c: tape)
    assert r.c0_central.iloc[0] == pytest.approx(0.65) and r.fill_ts_central.iloc[0] == 104.0
    assert r.c0_optimistic.iloc[0] == pytest.approx(0.63)
    assert r.c0_harsh.iloc[0] == pytest.approx(0.65) and not r.same_harsh.iloc[0]


def test_mid_path_matches_the_repo_mid_series():
    rng = np.random.default_rng(5)
    ts = np.sort(rng.integers(0, 3000, 800)).astype(float)
    p = np.clip(0.5 + np.cumsum(rng.normal(0, 0.01, 800)), 0.01, 0.99)
    ask = rng.random(800) < 0.5
    m1, s1 = v2.mid_path(ts, p, ask)
    m2, s2 = tiers._mid_series(ts, p, ask)
    np.testing.assert_allclose(m1, m2)
    np.testing.assert_allclose(s1, s2, equal_nan=True)


# ------------------------------------------------------------------------------------------------ v2 wiring
class _Stop(Exception):
    pass


@pytest.mark.parametrize("strict,expect", [(False, "bucket_c"), (True, "bucket_cs")])
def test_v2_run_qualifies_and_trades_on_the_requested_labels(monkeypatch, strict, expect):
    seen = {}

    def fake_walk_forward(prints, start_month=2, bucket="bucket"):
        seen["bucket"], seen["cols"] = bucket, set(prints.columns)
        raise _Stop

    monkeypatch.setattr(v2.fasttier, "walk_forward", fake_walk_forward)
    with pytest.raises(_Stop):
        v2.run(jump_tape(), pd.Series(dtype=object), strict=strict)
    assert seen["bucket"] == expect and expect in seen["cols"]
    if strict:
        assert "det_ts_s" in seen["cols"]


def test_v2_run_rejects_strict_without_causal():
    with pytest.raises(ValueError):
        v2.run(jump_tape(), pd.Series(dtype=object), causal=False, strict=True)
