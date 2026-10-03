"""Fair value from the Markov model: calibration, jumps, calls, score parsing (engine/fair)."""
import time

import numpy as np
import pytest

from engine.fair.value import (CallEvent, MatchFair, calibrate, call_winner, edge_after_fee, hitter_from_direction,
                               home_is_outcome0, parse_score)
from src.markov import Format, State, TennisModel, implied_serve_probs


def test_calibrate_prematch_matches_markov():
    for price in (0.25, 0.5, 0.71):
        pa, pb = calibrate(price, State(), "atp", p_server0=1.0)
        assert TennisModel(pa, pb).win_prob() == pytest.approx(price, abs=1e-6)
    ra, rb = implied_serve_probs(0.71, "atp")       # the research inversion (slow: 50 bisections)
    assert (pa, pb) == pytest.approx((ra, rb), abs=1e-4)
    # who serves first does not change the pre-match value, so the 50/50 mixture agrees
    assert calibrate(0.71, State(), "atp", p_server0=0.5) == pytest.approx((pa, pb), abs=1e-6)


def test_calibrate_in_play_and_extremes():
    s = State(1, 0, 3, 4, 1, 2, 1)
    mf = MatchFair.from_price(0.66, "wta", state=s, p_server0=0.5)
    assert mf.value() == pytest.approx(0.66, abs=1e-6)
    mf.recalibrate(0.55)
    assert mf.value() == pytest.approx(0.55, abs=1e-6)
    pa, pb = calibrate(0.9999, State(), "atp")          # beyond reach: clipped, no exception
    assert 0.3 <= pb <= pa <= 0.95


def test_jump_is_a_martingale_with_server_uncertainty():
    rng = np.random.default_rng(3)
    mf = MatchFair.from_price(0.58, "atp", Format(3), p_server0=0.5)
    n = 0
    while mf.state is not None:
        j = mf.jump()
        assert j.v_now == pytest.approx(mf.value(), abs=1e-12)
        assert j.v_now == pytest.approx(j.p_point_a * j.v_if_a + (1 - j.p_point_a) * j.v_if_b, abs=1e-12)
        assert j.v_if_a >= j.v_now - 1e-12 >= j.v_if_b - 2e-12
        a = rng.random() < j.p_point_a
        r = mf.apply_point(a)
        assert mf.value() == pytest.approx(r.v_if_a if a else r.v_if_b, abs=1e-12)
        n += 1
    assert mf.final in (0.0, 1.0) and n > 50


def test_server_belief_updates():
    mf = MatchFair(0.70, 0.70, p_server0=0.5)
    for _ in range(3):
        mf.apply_point(True)                                 # A wins 3 straight points
    assert mf.p_server0 > 0.8 and mf.state.pa == 3           # A is probably serving
    mf.apply_point(True)                                     # game A: server flips
    assert mf.state.ga == 1 and mf.p_server0 < 0.2


def test_leverage_and_calls():
    mf = MatchFair(0.64, 0.62, state=State(1, 1, 5, 5, 0, 3, 0), p_server0=1.0)   # break points in the decider
    j = mf.jump()
    assert j.leverage > MatchFair(0.64, 0.62, p_server0=1.0).leverage()
    c = mf.on_call(CallEvent(winner=1, confidence=1.0))
    assert c.v_expected == pytest.approx(j.v_if_b)
    c = mf.on_call(CallEvent(winner=0, confidence=0.8))
    assert c.v_expected == pytest.approx(0.8 * j.v_if_a + 0.2 * j.v_if_b)
    assert c.expected_token(1) == pytest.approx(1 - c.v_expected)
    assert c.move(0) == pytest.approx(c.v_expected - j.v_now)
    # out call on B's shot -> A wins the point; "in" call -> no point decided
    assert call_winner(CallEvent(kind="out", hitter=1, confidence=0.95)) == (0, 0.95)
    assert call_winner({"call": "net", "hitter": 0}) == (1, 1.0)
    assert mf.on_call(CallEvent(kind="in", hitter=0)).v_expected == pytest.approx(j.v_now)
    assert mf.state == State(1, 1, 5, 5, 0, 3, 0)           # on_call never advances the score


def test_match_point_terminal():
    mf = MatchFair(0.64, 0.62, state=State(1, 0, 5, 4, 3, 0, 0), p_server0=1.0)
    j = mf.apply_point(True)
    assert mf.state is None and mf.final == 1.0 and j.v_if_a == 1.0
    assert mf.value() == 1.0 and mf.jump().leverage == 0


def test_hot_path_is_fast():
    mf = MatchFair.from_price(0.6, "atp", state=State(0, 0, 2, 3, 2, 1, 0))
    mf.prime()
    t = time.perf_counter()
    for _ in range(2000):
        mf.on_call(CallEvent(winner=0, confidence=0.97))
    assert (time.perf_counter() - t) / 2000 < 1e-3         # well under a millisecond per call


def test_edge_after_fee():
    assert edge_after_fee(0.60, 0.58) == pytest.approx(0.02 - 0.05 * 0.58 * 0.42)
    assert edge_after_fee(0.40, 0.45, "SELL") == pytest.approx(0.05 - 0.05 * 0.45 * 0.55)
    assert edge_after_fee(0.5, 0.5, fee_rate=0.0) == 0


def test_parse_sports_feed_scores():
    assert parse_score("6-7(4-7), 6-4, 2-1") == (1, 1, 2, 1)
    assert parse_score("2-6") == (0, 1, 0, 0)
    assert parse_score("7-5, 4-6, 0-0", home_is_a=False) == (1, 1, 0, 0)
    assert parse_score("7-5, 3-4", home_is_a=False) == (0, 1, 4, 3)
    assert parse_score("6-6") == (0, 0, 6, 6)
    assert parse_score("") == (0, 0, 0, 0)
    assert home_is_outcome0("Elena Rybakina", "Elena Rybakina", "Alina Charaeva") is True
    assert home_is_outcome0("Alina Charaeva", "Elena Rybakina", "Alina Charaeva") is False
    assert home_is_outcome0("X Y", "A B", "C D") is None


def test_vision_call_events_map_to_winners():
    vision = pytest.importorskip("engine.vision.events")
    miss = vision.CallEvent(call="MISS", frame=10, t_frame=1.0, t_emit=1.02, p_miss=0.9, lead_ms=50, direction=1)
    bounce = vision.CallEvent(call="BOUNCE", frame=11, t_frame=1.0, t_emit=1.02, p_miss=0.1, lead_ms=50, direction=1)
    # ball travelling left->right was hit by the player on the left; it is called out -> the other one wins
    assert call_winner(miss, left_player=0) == (1, 0.95)
    assert call_winner(miss, left_player=1) == (0, 0.95)
    assert call_winner(miss, hitter=1, confidence=0.99) == (0, 0.99)
    assert call_winner(miss) == (None, 0.95)                   # hitter unknown: no point decided
    assert call_winner(bounce, left_player=0)[0] is None
    assert hitter_from_direction(-1, 0) == 1 and hitter_from_direction(0, 0) is None
    mf = MatchFair(0.64, 0.62, state=State(0, 0, 2, 2, 1, 1, 0), p_server0=1.0)
    j = mf.on_call(miss, left_player=0)
    assert j.winner == 1 and j.v_expected == pytest.approx(0.95 * j.v_if_b + 0.05 * j.v_if_a)
