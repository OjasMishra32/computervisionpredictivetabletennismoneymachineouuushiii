"""Live fair value for a tennis match from the exact point-level Markov model (src.markov).

    price (pre-match or current mid)  --calibrate-->  serve-point probabilities (pa, pb)
    score state + point winner        --MatchFair-->  fair-value jump, leverage
    CallEvent (vision: who won it)    --on_call---->  expected new fair value per token

Conventions follow src.markov: player A is outcome 0 (the market's first token), values are
P(A wins the match). `State.server` is the server of the current game (in a tiebreak: who
served its first point).

Server uncertainty. The public sports feed gives set and game scores, never the server. A
`MatchFair` therefore carries p_server0 = P(state.server == 0) and mixes the two hypotheses.
After each point the belief is updated by Bayes (the server wins most points), so fair value
stays an exact martingale: v_now = P(A wins point) * v_if_a + P(B wins point) * v_if_b.

Speed. Calibration solves for the serve split with Brent's method (~10 model builds, ~0.1-0.3 s;
src.markov.implied_serve_probs runs 50 bisection steps, ~1.8 s). Run it pre-match and, if you
recalibrate in play, between points (`await asyncio.to_thread(mf.recalibrate, mid)`). The hot
path, `jump()`/`on_call()`, only reads the model's cached values (~10-100 us) and is
pre-computed for the current state by `prime()`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

import numpy as np
from scipy.optimize import brentq

from src.markov import TOUR_SERVE, Format, State, TennisModel
from src.paper import FEE_RATE, taker_fee

P_LO, P_HI = 0.3, 0.95   # same clipping as src.markov.implied_serve_probs
D_LO, D_HI = -0.4, 0.4


def _serve_pair(mu: float, d: float) -> tuple[float, float]:
    return float(np.clip(mu + d / 2, P_LO, P_HI)), float(np.clip(mu - d / 2, P_LO, P_HI))


def _mix_value(model: TennisModel, s: State, p0: float) -> float:
    if p0 >= 1.0:
        return model.win_prob(replace(s, server=0))
    if p0 <= 0.0:
        return model.win_prob(replace(s, server=1))
    return p0 * model.win_prob(replace(s, server=0)) + (1 - p0) * model.win_prob(replace(s, server=1))


def calibrate(price_a: float, state: State = State(), tour: str = "atp", fmt: Format = Format(),
              p_server0: float = 1.0, xtol: float = 1e-6) -> tuple[float, float]:
    """(pa, pb) around the tour-average serve-point rate such that the model's P(A wins) at
    `state` equals price_a. Same parameterisation as src.markov.implied_serve_probs (which is
    the special case state = State(), p_server0 = 1), solved with Brent's method."""
    mu = TOUR_SERVE.get(tour, 0.62)
    f = lambda d: _mix_value(TennisModel(*_serve_pair(mu, d), fmt), state, p_server0) - price_a
    lo, hi = f(D_LO), f(D_HI)
    if lo >= 0:
        return _serve_pair(mu, D_LO)
    if hi <= 0:
        return _serve_pair(mu, D_HI)
    d = brentq(f, D_LO, D_HI, xtol=xtol, rtol=1e-10, maxiter=60)
    return _serve_pair(mu, d)


# --------------------------------------------------------------------------- call events
@dataclass(frozen=True)
class CallEvent:
    """Point-level call for the trading side. `call_winner` also accepts the vision engine's
    engine.vision.events.CallEvent (call="MISS"/"BOUNCE", p_miss, direction) and plain dicts.

    winner      0 = player A (outcome-0 token) won the point, 1 = player B; None = no point end
    confidence  P(the call is right), e.g. the early-call precision at this lead
    kind        "point" (winner known) | "out" | "net" | "in" (needs `hitter` for out/net)
    hitter      who struck the ball being called (0/1), used when winner is not given
    t_ms        local ms when the call was made"""
    match_id: str = ""
    t_ms: int = 0
    winner: int | None = None
    confidence: float = 1.0
    kind: str = "point"
    hitter: int | None = None
    source: str = "vision"


VISION_MISS_PRECISION = 0.95   # the early-call threshold's pre-registered precision target


def hitter_from_direction(direction: int, left_player: int) -> int | None:
    """Vision `direction` is the ball's image-x travel (+1 = left to right). The hitter is the
    player at the end it travels away from; `left_player` (0 = A, 1 = B) is who is at the
    image's left end right now (players change ends on odd games: the strategy tracks that)."""
    if not direction:
        return None
    return int(left_player) if direction > 0 else 1 - int(left_player)


def call_winner(call, hitter: int | None = None, left_player: int | None = None,
                confidence: float | None = None) -> tuple[int | None, float]:
    """(point winner 0/1 or None, confidence) from any CallEvent-like object or dict.

    winner / point_winner given -> used directly.
    kind or call in {out, net, miss, ...} -> the hitter loses the point; the hitter comes from the
        `hitter` argument, the event's `hitter`, or its `direction` with `left_player`.
    "in" / "BOUNCE" -> the rally goes on: (None, conf).
    confidence: argument > event `confidence` > `p` > VISION_MISS_PRECISION for vision MISS calls
        (p_miss is a classifier score, not a probability of being right) > 1.0."""
    g = (lambda k, d=None: call.get(k, d)) if isinstance(call, dict) else (lambda k, d=None: getattr(call, k, d))
    kind = str(g("kind", None) or g("call", "") or "").lower()
    if confidence is None:
        confidence = g("confidence", None)
    if confidence is None:
        confidence = g("p", None)
    if confidence is None:
        # "miss" is only ever a vision call (the trading-side kinds are point/out/net/in). Do not key this on
        # p_miss being present: a reloaded JSON event has p_miss null, which used to mean confidence 1.0.
        confidence = VISION_MISS_PRECISION if kind == "miss" else 1.0
    conf = float(min(1.0, max(0.0, confidence)))
    w = g("winner", None)
    if w is None:
        w = g("point_winner", None)
    if w is not None:
        return int(w), conf
    if kind in ("out", "net", "miss", "long", "wide", "fault"):
        h = hitter if hitter is not None else g("hitter", None)
        if h is None and left_player is not None:
            h = hitter_from_direction(int(g("direction", 0) or 0), left_player)
        if h is not None:
            return 1 - int(h), conf       # the hitter's ball is out -> the other player wins
    return None, conf


@dataclass
class FairJump:
    """Fair value (P(A wins)) now and after each outcome of the next point."""
    state: State | None
    p_server0: float
    v_now: float
    v_if_a: float
    v_if_b: float
    p_point_a: float                  # model P(A wins the next point)
    winner: int | None = None         # set by on_call
    confidence: float = 1.0
    v_expected: float | None = None   # E[fair after the call] = c*v_if_winner + (1-c)*v_if_loser

    @property
    def leverage(self) -> float:
        return self.v_if_a - self.v_if_b

    def token(self, outcome: int, v: float | None = None) -> float:
        """Fair price of the outcome-`outcome` token (A: v, B: 1 - v)."""
        v = self.v_now if v is None else v
        return v if outcome == 0 else 1.0 - v

    def expected_token(self, outcome: int) -> float:
        return self.token(outcome, self.v_expected if self.v_expected is not None else self.v_now)

    def move(self, outcome: int) -> float:
        """Expected fair-value change of the outcome token caused by the call."""
        return self.expected_token(outcome) - self.token(outcome)


def edge_after_fee(fair_token: float, price: float, side: str = "BUY", fee_rate: float = FEE_RATE) -> float:
    """Expected profit per share of a taker order at `price` against a fair value, net of the
    Polymarket taker fee rate*q*(1-q). BUY: fair - price - fee; SELL: price - fair - fee."""
    gross = fair_token - price if side == "BUY" else price - fair_token
    return gross - taker_fee(price, fee_rate)


# --------------------------------------------------------------------------- match state
class MatchFair:
    """Fair value tracker for one match."""

    def __init__(self, pa: float, pb: float, fmt: Format = Format(), state: State = State(),
                 p_server0: float = 0.5, tour: str = "atp", match_id: str = "",
                 token_a: str | None = None, token_b: str | None = None):
        self.fmt, self.tour, self.match_id = fmt, tour, match_id
        self.token_a, self.token_b = token_a, token_b
        self.model = TennisModel(pa, pb, fmt)
        self.state: State | None = state
        self.p_server0 = float(p_server0)
        self.final: float | None = None   # 1.0 / 0.0 once the match is over
        self._cache: dict = {}

    @classmethod
    def from_price(cls, price_a: float, tour: str = "atp", fmt: Format = Format(), state: State = State(),
                   p_server0: float = 0.5, **kw) -> "MatchFair":
        """Calibrate on a pre-match price (state = State()) or on the current mid at `state`."""
        pa, pb = calibrate(price_a, state, tour, fmt, p_server0)
        return cls(pa, pb, fmt, state, p_server0, tour, **kw)

    @property
    def serve_probs(self) -> tuple[float, float]:
        return self.model.p

    def recalibrate(self, mid_a: float, state: State | None = None) -> tuple[float, float]:
        """Refit (pa, pb) so that fair value at the current state equals the market mid."""
        if state is not None:
            self.state = state
        if self.state is None:
            return self.model.p
        pa, pb = calibrate(mid_a, self.state, self.tour, self.fmt, self.p_server0)
        self.model = TennisModel(pa, pb, self.fmt)
        self._cache.clear()
        return pa, pb

    # values ------------------------------------------------------------------------------
    def _v(self, s: State | None, a_won_last: bool) -> float:
        return (1.0 if a_won_last else 0.0) if s is None else self.model.win_prob(s)

    def value(self) -> float:
        if self.state is None:
            return float(self.final)
        return _mix_value(self.model, self.state, self.p_server0)

    def _branches(self):
        """Per server hypothesis h: (prior, P(A wins point), state if A wins, state if B wins)."""
        out = []
        for srv, w in ((0, self.p_server0), (1, 1.0 - self.p_server0)):
            if w <= 0:
                continue
            s = replace(self.state, server=srv)
            x = self.model._pt(self.model.point_server(s))
            out.append((srv, w, x, self.model.step(s, True), self.model.step(s, False)))
        return out

    def jump(self) -> FairJump:
        """Fair value now and after either outcome of the next point (cached per state)."""
        if self.state is None:
            v = float(self.final)
            return FairJump(None, self.p_server0, v, v, v, 0.5)
        key = (self.state, self.p_server0, self.model.p)
        j = self._cache.get(key)
        if j is not None:
            return replace(j)
        br = self._branches()
        pa_pt = sum(w * x for _, w, x, _, _ in br)
        # values after the point use the posterior over the server given who won it
        va = sum(w * x * self._v(sa, True) for _, w, x, sa, _ in br) / pa_pt if pa_pt > 0 else 0.0
        vb = sum(w * (1 - x) * self._v(sb, False) for _, w, x, _, sb in br) / (1 - pa_pt) if pa_pt < 1 else 0.0
        v = pa_pt * va + (1 - pa_pt) * vb
        j = FairJump(self.state, self.p_server0, v, va, vb, pa_pt)
        if len(self._cache) > 4096:
            self._cache.clear()
        self._cache[key] = j
        return replace(j)

    def prime(self) -> FairJump:
        """Pre-compute the jump for the current state (call after every state change)."""
        return self.jump()

    def leverage(self) -> float:
        return self.jump().leverage

    def on_call(self, call, hitter: int | None = None, left_player: int | None = None,
                confidence: float | None = None) -> FairJump:
        """Map a CallEvent to the expected new fair value. Does not advance the score: call
        `apply_point` when the point is confirmed (or apply it directly at confidence 1)."""
        j = self.jump()
        w, c = call_winner(call, hitter, left_player, confidence)
        j.confidence = c
        j.winner = w
        if w is None:
            j.v_expected = j.v_now
        else:
            v_w, v_l = (j.v_if_a, j.v_if_b) if w == 0 else (j.v_if_b, j.v_if_a)
            j.v_expected = c * v_w + (1 - c) * v_l
        return j

    def apply_point(self, a_won: bool) -> FairJump:
        """Advance the score by one point; returns the jump (v_now -> realised value)."""
        j = self.jump()
        if self.state is None:
            return j
        br = self._branches()
        post = {srv: w * (x if a_won else 1 - x) for srv, w, x, _, _ in br}
        tot = sum(post.values())
        nxt = {srv: (sa if a_won else sb) for srv, _, _, sa, sb in br}
        any_next = next(iter(nxt.values()))
        if any_next is None:
            self.state, self.final = None, 1.0 if a_won else 0.0
        else:
            # both hypotheses share the score; only the server label differs
            p0 = 0.0
            for srv, s in nxt.items():
                if s.server == 0:
                    p0 += post[srv] / tot if tot > 0 else 0.0
            self.state = replace(any_next, server=0)
            self.p_server0 = p0
        j.winner = 0 if a_won else 1
        j.v_expected = j.v_if_a if a_won else j.v_if_b
        return j

    def resync(self, sa: int, sb: int, ga: int, gb: int, pa: int = 0, pb: int = 0,
               server: int | None = None) -> None:
        """Reset the score (e.g. from the sports feed at a game boundary)."""
        self.state = State(sa, sb, ga, gb, pa, pb, 0)
        if server is not None:
            self.p_server0 = 1.0 if server == 0 else 0.0
        self.final = None

    def token(self, outcome: int) -> float:
        v = self.value()
        return v if outcome == 0 else 1.0 - v


# --------------------------------------------------------------------------- score parsing
_SET_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)")


def _set_done(a: int, b: int) -> bool:
    return (max(a, b) >= 6 and abs(a - b) >= 2) or (max(a, b) == 7 and min(a, b) >= 5)


def parse_score(score: str, home_is_a: bool = True) -> tuple[int, int, int, int]:
    """Polymarket sports-feed score ("6-7(4-7), 6-4, 2-1") -> (sa, sb, ga, gb) for A/B.
    Finished sets are counted, the last unfinished set gives the current games; points and
    the server are not in the feed."""
    sa = sb = ga = gb = 0
    parts = [p for p in (score or "").split(",") if p.strip()]
    for i, p in enumerate(parts):
        m = _SET_RE.match(p)
        if not m:
            continue
        h, a = int(m.group(1)), int(m.group(2))
        x, y = (h, a) if home_is_a else (a, h)
        if _set_done(x, y):
            sa, sb = (sa + 1, sb) if x > y else (sa, sb + 1)
            ga = gb = 0
        else:
            ga, gb = x, y
    return sa, sb, ga, gb


def _norm(s: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z ]", " ", (s or "").lower()).split() if len(w) > 1]


def home_is_outcome0(outcome0_name: str, home: str, away: str) -> bool | None:
    """Match the market's outcome-0 name to the sports feed's home/away player by surname."""
    o = set(_norm(outcome0_name))
    h, a = set(_norm(home)), set(_norm(away))
    sh, sa = len(o & h), len(o & a)
    if sh == sa:
        return None
    return sh > sa
