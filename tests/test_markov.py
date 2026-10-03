import numpy as np
import pytest

from src.markov import Format, State, TennisModel, implied_serve_probs, simulate_match


def closed_form_game(p):
    q = 1 - p
    return p**4 * (1 + 4*q + 10*q*q) + 20 * p**3 * q**3 * p*p / (1 - 2*p*q)


@pytest.mark.parametrize("p", [0.55, 0.6, 0.65, 0.7])
def test_game_matches_closed_form(p):
    # A serving at 5-5 in the final set of a bo3: winning the game is worth ~ P(hold)
    m = TennisModel(p, 0.5)
    # value of a single game: compare P(A wins game) through the recursion directly
    W, L = 1.0, 0.0
    m._after_game = lambda *a, **k: W if a[-1] else L  # isolate one game
    assert m._game(0, 0, 0, 0, 0, 0, 0) == pytest.approx(closed_form_game(p), abs=1e-12)


def test_symmetry():
    for fmt in (Format(3), Format(5, final_tb_points=10)):
        m = TennisModel(0.63, 0.63, fmt)
        assert m.win_prob() == pytest.approx(0.5, abs=1e-12)
        assert m.win_prob(State(server=1)) == pytest.approx(0.5, abs=1e-12)


def test_monte_carlo_agrees():
    rng = np.random.default_rng(0)
    m = TennisModel(0.66, 0.61, Format(3))
    wins = [simulate_match(m, rng)[-1][3] for _ in range(4000)]
    # last point winner = match winner
    assert np.mean(wins) == pytest.approx(m.win_prob(), abs=0.025)


def test_terminal_and_leverage_bounds():
    m = TennisModel(0.64, 0.62)
    mp = State(sa=1, sb=0, ga=5, gb=4, pa=3, pb=0, server=0)  # A serving for the match at 40-0
    assert m.win_prob(mp) > 0.97
    assert 0 < m.leverage(mp) < 0.2
    bp = State(sa=1, sb=1, ga=5, gb=5, pa=0, pb=3, server=0)  # break points at 5-5 in the decider
    assert m.leverage(bp) > m.leverage(State())


def test_implied_serve_roundtrip():
    for price in (0.2, 0.5, 0.8):
        pa, pb = implied_serve_probs(price, "atp")
        assert TennisModel(pa, pb).win_prob() == pytest.approx(price, abs=1e-4)
