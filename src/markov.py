"""Exact point-level Markov model of a tennis match.

Fair match-win probability for any score, and each point's leverage: how far fair
value moves between winning and losing that one point. Deuce and tiebreak ties are
solved in closed form, so the recursion has no cycles.

Players: A (outcome 0) and B. pa = P(A wins a point on A's serve),
pb = P(B wins a point on B's serve). server: 0 = A serves, 1 = B serves.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np


@dataclass(frozen=True)
class Format:
    best_of: int = 3
    tb_points: int = 7        # tiebreak at 6-6 in normal sets
    final_tb_points: int = 7  # 10 at the Slams since 2022

    @property
    def sets_to_win(self) -> int:
        return self.best_of // 2 + 1


@dataclass(frozen=True)
class State:
    sa: int = 0
    sb: int = 0
    ga: int = 0
    gb: int = 0
    pa: int = 0      # points in the current game or tiebreak
    pb: int = 0
    server: int = 0  # server of the current game; in a tiebreak, who served its first point


class TennisModel:
    def __init__(self, pa: float, pb: float, fmt: Format = Format()):
        self.p = (pa, pb)
        self.fmt = fmt
        self._game_start = lru_cache(maxsize=None)(self._game_start_impl)

    # P(A wins the point) when `srv` is serving
    def _pt(self, srv: int) -> float:
        return self.p[0] if srv == 0 else 1.0 - self.p[1]

    def _is_final_set(self, sa: int, sb: int) -> bool:
        k = self.fmt.sets_to_win - 1
        return sa == k and sb == k

    def _after_game(self, sa, sb, ga, gb, server, a_won: bool) -> float:
        """Value right after a (non-tiebreak) game ends, from A's side."""
        ga, gb = (ga + 1, gb) if a_won else (ga, gb + 1)
        nxt = 1 - server
        if (ga >= 6 and ga - gb >= 2) or (gb >= 6 and gb - ga >= 2) or ga == 7 or gb == 7:
            return self._after_set(sa, sb, ga > gb, nxt)
        return self._game_start(sa, sb, ga, gb, nxt)

    def _after_set(self, sa, sb, a_won: bool, next_server: int) -> float:
        sa, sb = (sa + 1, sb) if a_won else (sa, sb + 1)
        if sa == self.fmt.sets_to_win:
            return 1.0
        if sb == self.fmt.sets_to_win:
            return 0.0
        return self._game_start(sa, sb, 0, 0, next_server)

    def _game_start_impl(self, sa, sb, ga, gb, server) -> float:
        if ga == 6 and gb == 6:
            return self._tb(sa, sb, 0, 0, server)
        return self._game(sa, sb, ga, gb, 0, 0, server)

    # regular game, points (a, b) from A's side regardless of who serves
    def _game(self, sa, sb, ga, gb, a, b, server) -> float:
        win = lambda: self._after_game(sa, sb, ga, gb, server, True)
        lose = lambda: self._after_game(sa, sb, ga, gb, server, False)
        if a >= 4 and a - b >= 2:
            return win()
        if b >= 4 and b - a >= 2:
            return lose()
        x = self._pt(server)
        if a >= 3 and b >= 3:
            W, L = win(), lose()
            deuce = (x * x * W + (1 - x) ** 2 * L) / (x * x + (1 - x) ** 2)
            if a == b:
                return deuce
            if a > b:
                return x * W + (1 - x) * deuce
            return x * deuce + (1 - x) * L
        return x * self._game(sa, sb, ga, gb, a + 1, b, server) + \
            (1 - x) * self._game(sa, sb, ga, gb, a, b + 1, server)

    def _tb_server(self, k: int, first: int) -> int:
        """Server of tiebreak point k (0-indexed): first, then pairs alternating."""
        return first if ((k + 1) // 2) % 2 == 0 else 1 - first

    def _tb(self, sa, sb, a, b, first) -> float:
        T = self.fmt.final_tb_points if self._is_final_set(sa, sb) else self.fmt.tb_points
        nxt = 1 - first
        if a >= T and a - b >= 2:
            return self._after_set(sa, sb, True, nxt)
        if b >= T and b - a >= 2:
            return self._after_set(sa, sb, False, nxt)
        W = lambda: self._after_set(sa, sb, True, nxt)
        L = lambda: self._after_set(sa, sb, False, nxt)
        k = a + b
        if a >= T - 1 and b >= T - 1:
            def tie_value(kk: int) -> float:
                x1, x2 = self._pt(self._tb_server(kk, first)), self._pt(self._tb_server(kk + 1, first))
                ww, ll = x1 * x2, (1 - x1) * (1 - x2)
                return (ww * W() + ll * L()) / (ww + ll)
            if a == b:
                return tie_value(k)
            x = self._pt(self._tb_server(k, first))
            if a > b:
                return x * W() + (1 - x) * tie_value(k + 1)
            return x * tie_value(k + 1) + (1 - x) * L()
        x = self._pt(self._tb_server(k, first))
        return x * self._tb(sa, sb, a + 1, b, first) + (1 - x) * self._tb(sa, sb, a, b + 1, first)

    # public API ---------------------------------------------------------
    def win_prob(self, s: State = State()) -> float:
        if s.ga == 6 and s.gb == 6:
            return self._tb(s.sa, s.sb, s.pa, s.pb, s.server)
        return self._game(s.sa, s.sb, s.ga, s.gb, s.pa, s.pb, s.server)

    def point_server(self, s: State) -> int:
        if s.ga == 6 and s.gb == 6:
            return self._tb_server(s.pa + s.pb, s.server)
        return s.server

    def step(self, s: State, a_wins: bool) -> State | None:
        """Score after one point; None if the match is over."""
        sa, sb, ga, gb, pa, pb, srv = s.sa, s.sb, s.ga, s.gb, s.pa, s.pb, s.server
        pa, pb = (pa + 1, pb) if a_wins else (pa, pb + 1)
        tb = ga == 6 and gb == 6
        T = (self.fmt.final_tb_points if self._is_final_set(sa, sb) else self.fmt.tb_points) if tb else 4
        if not ((pa >= T and pa - pb >= 2) or (pb >= T and pb - pa >= 2)):
            return State(sa, sb, ga, gb, pa, pb, srv)
        a_game = pa > pb
        nxt = 1 - srv
        if tb:
            set_won, a_set = True, a_game
        else:
            ga, gb = (ga + 1, gb) if a_game else (ga, gb + 1)
            set_won = (ga >= 6 and ga - gb >= 2) or (gb >= 6 and gb - ga >= 2) or ga == 7 or gb == 7
            a_set = ga > gb
        if not set_won:
            return State(sa, sb, ga, gb, 0, 0, nxt)
        sa, sb = (sa + 1, sb) if a_set else (sa, sb + 1)
        if max(sa, sb) == self.fmt.sets_to_win:
            return None
        return State(sa, sb, 0, 0, 0, 0, nxt)

    def leverage(self, s: State) -> float:
        """Fair-value swing riding on the next point."""
        up, dn = self.step(s, True), self.step(s, False)
        vu = 1.0 if up is None else self.win_prob(up)
        vd = 0.0 if dn is None else self.win_prob(dn)
        return vu - vd


TOUR_SERVE = {"atp": 0.645, "challenger": 0.635, "wta": 0.565}


def implied_serve_probs(price_a: float, tour: str = "atp", fmt: Format = Format()) -> tuple[float, float]:
    """Invert a pre-match price into (pa, pb) around the tour-average serve-point win rate."""
    mu = TOUR_SERVE.get(tour, 0.62)
    lo, hi = -0.4, 0.4
    for _ in range(50):
        d = (lo + hi) / 2
        pa, pb = np.clip(mu + d / 2, 0.3, 0.95), np.clip(mu - d / 2, 0.3, 0.95)
        if TennisModel(pa, pb, fmt).win_prob() < price_a:
            lo = d
        else:
            hi = d
    d = (lo + hi) / 2
    return float(np.clip(mu + d / 2, 0.3, 0.95)), float(np.clip(mu - d / 2, 0.3, 0.95))


def simulate_match(model: TennisModel, rng: np.random.Generator):
    """One random match: list of (state, fair value before the point, leverage, A won point)."""
    s, out = State(), []
    while s is not None:
        a = rng.random() < model._pt(model.point_server(s))
        out.append((s, model.win_prob(s), model.leverage(s), a))
        s = model.step(s, a)
    return out
