"""COURTSIDE decision rule: a vision CallEvent becomes (at most) one PAPER taker order.

    CallEvent (vision) --fair/value.MatchFair.on_call--> FairJump (v_now, v_if_a, v_if_b, P(point))
                       --this module-------------------> edge after fee, half spread and 1 tick
                       --risk/limits.RiskManager-------> v2 size, caps, kill switches
                       --execution/paper.PaperExecutor-> simulated fill at t + one-way + 1 s

The rule, per call on match M (player A = outcome-0 token):

    w        = predicted point winner (MISS: the hitter loses; BOUNCE: no decision -> no trade)
    c        = P(call is right) (0.95 for vision MISS calls: the pre-registered precision target)
    lev      = v_if_a - v_if_b                   fair-value swing riding on this point (Markov model,
                                                  calibrated to the book mid at the current score)
    E[move]  = c * v_w + (1 - c) * v_l - v_now   expected change of the w-token's fair value
             = (c - p_w) * lev                   p_w = model P(w wins the point): the book already
                                                  prices that, so the edge is (c - p_w), not c
    limit    = stale best ask of the w-token + 1 tick
    edge     = E[move] - half_spread - (limit - ask) - fee(limit)      fee = 0.05 * q * (1 - q)
    trade iff edge > min_edge (0), the call is fresh (frame -> decision <= 1 s), and the book has not
             already moved >= half a point-jump since the pre-point calibration (toward w: the call is
             late; against w: the market says the point went the other way)
    size     = v2 risk parity k * $1k / sqrt(q(1-q)), capped by the stale depth inside the limit,
               then by RiskManager ($1k per order, |net| <= 100 shares per match, kills)

The order is a BUY of the w-token (to bet against A, buy B: Polymarket has no naked shorts),
limit = stale ask + 1 tick, FAK. Fair value of the order (`Decision.fair`) is the anchored
post-call fair, mid_w + E[move], so the risk manager's own fee-aware filter applies the same test.

PAPER ONLY. This module never signs, sends or places a real order: it hands `Decision`s to
`engine.execution.paper.PaperExecutor`, which simulates fills against live or recorded books. It
refuses any other executor, refuses credential-like or live arguments, refuses to start when
live-trading flags or wallet/CLOB credentials are in the environment or an order-signing library
is loaded, and `enable_live_trading()` always raises.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from engine.execution.paper import (Decision, LiveTradingForbidden, PaperExecutor, assert_no_signing_client,
                                    assert_paper)
from engine.execution import paper as _paper_mod
from engine.fair.value import MatchFair, call_winner
from engine.risk.limits import V2_K, risk_parity_shares
from engine.vision import events as _vision_events
from src.markov import Format, State
from src.paper import FEE_RATE, taker_fee

PAPER_ONLY = True


def enable_live_trading(*_a, **_k):
    """There is no live mode. This always raises."""
    raise LiveTradingForbidden("COURTSIDE is paper only: there is no live-trading mode to enable")


def assert_paper_only(**kwargs) -> None:
    """Every guard in the engine, in one call: this module's flag, the vision guard (environment
    flags and credentials), the execution guard (signing libraries, environment), and the
    keyword-argument check (live=True or credential-like names raise)."""
    if PAPER_ONLY is not True or _paper_mod.PAPER_ONLY is not True or _vision_events.PAPER_ONLY is not True:
        raise LiveTradingForbidden("a PAPER_ONLY flag was modified; COURTSIDE never trades for real")
    try:
        _vision_events.assert_paper_only()
    except _vision_events.LiveTradingForbidden as e:   # one exception type for callers
        raise LiveTradingForbidden(str(e)) from e
    assert_no_signing_client()
    if kwargs:
        assert_paper(**kwargs)


def calibration_job(mid_a: float, tour: str, state: State, p_server0: float, fmt: Format = Format()):
    """Picklable calibration for a worker PROCESS (it is pure-Python CPU work: in a thread it holds the
    GIL and stalls the event loop that owns the books). Returns ((pa, pb), primed FairJump)."""
    mf = MatchFair.from_price(mid_a, tour, fmt, state, p_server0)
    return mf.serve_probs, mf.prime()


def fair_from_job(result, state: State, p_server0: float, tour: str, fmt: Format = Format(), match_id: str = "",
                  token_a: str | None = None, token_b: str | None = None) -> MatchFair:
    """Rebuild the MatchFair of `calibration_job` in this process (0.1 ms) with its jump pre-seeded, so the
    first on_call is a cache hit (MatchFair caches jumps by (state, p_server0, serve probs))."""
    (pa, pb), j = result
    mf = MatchFair(pa, pb, fmt, state, p_server0, tour, match_id, token_a, token_b)
    mf._cache[(mf.state, mf.p_server0, mf.model.p)] = j
    return mf


@dataclass
class StrategyConfig:
    confidence: float | None = None   # None: call_winner's default (0.95 for vision MISS calls)
    min_edge: float = 0.0             # required edge per share after fee, half spread and the tick
    limit_ticks: int = 1              # limit = stale ask + this many ticks
    tick: float | None = None         # None: the book's tick size
    k: float = V2_K                   # v2 risk-parity deployment factor
    cap_at_visible: bool = True       # never ask for more than the stale depth inside the limit
    max_spread: float = 0.10          # skip books wider than this (no reliable mid)
    moved_frac: float = 0.5           # skip if the book already moved this share of the jump (either way)
    max_call_latency_ms: float | None = 1000.0   # skip calls older than this (frame -> decision): the
                                                 # stale depth is gone ~0.5 s after the reprice
    fee_rate: float = FEE_RATE
    rally_gate_s: float | None = None  # rally-state gate: a MISS/OUT call is traded only if a BOUNCE/IN call on
    #                                    the same match came at most this long before it (2.0 s for any live use;
    #                                    off by default so the committed demo and e2e runs reproduce). The live
    #                                    engine made 7 MISS calls on balls outside the scored flights in 851 s of
    #                                    held-out video, 5 between rallies (results/engine/online_vs_offline.json).


@dataclass
class MatchCtx:
    match_id: str
    token_a: str
    token_b: str
    fair: MatchFair
    left_player: int = 0              # outcome index of the player at the image's left end
    names: tuple = ("A", "B")
    cal_ms: int | None = None         # when MatchFair was last calibrated
    cal_mid_a: float | None = None    # outcome-0 mid used for that calibration (pre-point reference)


@dataclass
class StrategyDecision:
    """Everything the rule looked at, for one call. action: SEND | SKIP | REJECTED (by risk)."""
    match_id: str
    t_ms: int
    call: str
    action: str = "SKIP"
    reason: str = ""
    winner: int | None = None
    winner_name: str | None = None
    confidence: float | None = None
    token: str | None = None
    state: dict | None = None
    p_server0: float | None = None
    v_now: float | None = None
    v_if_a: float | None = None
    v_if_b: float | None = None
    leverage: float | None = None
    p_point_winner: float | None = None
    expected_move: float | None = None
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    half_spread: float | None = None
    tick: float | None = None
    limit: float | None = None
    fee: float | None = None
    edge_at_ask: float | None = None
    edge: float | None = None         # at the limit: the trading test
    fair_after: float | None = None
    moved_toward_winner: float | None = None
    visible_shares: float | None = None
    shares: float | None = None
    order_id: int | None = None
    order_status: str | None = None
    compute_us: float | None = None   # evaluate() only: fair jump + rule (no risk check, no submit)
    total_us: float | None = None     # on_call() end to end: heartbeat + rule + guard + risk + paper submit

    def to_dict(self) -> dict:
        return asdict(self)


class CourtsideStrategy:
    """Per-match fair value + the decision rule. Plug into any feed (live or replay)."""

    def __init__(self, feed, executor: PaperExecutor | None = None, risk=None, cfg: StrategyConfig | None = None,
                 clock=None, **kwargs):
        assert_paper_only(**kwargs)
        if executor is not None and not isinstance(executor, PaperExecutor):
            raise LiveTradingForbidden(f"executor must be engine.execution.paper.PaperExecutor, got "
                                       f"{type(executor).__name__}: COURTSIDE only simulates fills")
        self.feed, self.ex, self.risk = feed, executor, risk
        self.cfg = cfg or StrategyConfig()
        self._clock = clock
        self.matches: dict[str, MatchCtx] = {}
        self.decisions: list[StrategyDecision] = []
        self._last_bounce_ms: dict[str, int] = {}   # rally-state gate: last BOUNCE/IN call per match

    # ------------------------------------------------------------------------------ setup
    def now_ms(self) -> int:
        if self._clock is not None:
            return int(self._clock())
        return int(self.feed.now_ms())

    def add_match(self, match_id: str, token_a: str, token_b: str, *, state: State = State(),
                  p_server0: float = 0.5, tour: str = "atp", fmt: Format = Format(), left_player: int = 0,
                  names=("A", "B"), fair: MatchFair | None = None, calibrate: bool = True,
                  now_ms: int | None = None) -> MatchCtx:
        mf = fair or MatchFair(0.62, 0.62, fmt, state, p_server0, tour, match_id, token_a, token_b)
        ctx = MatchCtx(match_id, token_a, token_b, mf, int(left_player), tuple(names))
        self.matches[match_id] = ctx
        if self.risk is not None and token_a not in self.risk.token_info:
            self.risk.register_market(match_id, token_a, token_b)
        if self.ex is not None:
            self.ex.register_market(match_id, [token_a, token_b])
        if calibrate:
            self.calibrate(match_id, now_ms)
        return ctx

    def mid_a(self, ctx: MatchCtx) -> float | None:
        """Outcome-0 mid from A's book, else the complement of B's (one binary book, two views)."""
        ba = self.feed.book(ctx.token_a)
        if ba.has_snapshot and ba.mid() is not None:
            return ba.mid()
        bb = self.feed.book(ctx.token_b)
        if bb.has_snapshot and bb.mid() is not None:
            return 1.0 - bb.mid()
        return None

    def calibrate(self, match_id: str, now_ms: int | None = None, mid_a: float | None = None) -> bool:
        """Refit the serve split so fair value at the current score equals the book mid. Run it
        between points (0.1-0.5 s; live: `await asyncio.to_thread(strategy.calibrate, m)`)."""
        ctx = self.matches[match_id]
        m = self.mid_a(ctx) if mid_a is None else mid_a
        if m is None or not (0.0 < m < 1.0) or ctx.fair.state is None:
            return False
        ctx.fair.recalibrate(m)
        ctx.fair.prime()
        ctx.cal_ms = self.now_ms() if now_ms is None else int(now_ms)
        ctx.cal_mid_a = m
        return True

    def install_fair(self, match_id: str, mf: MatchFair, mid_a: float, now_ms: int) -> None:
        """Swap in a MatchFair calibrated elsewhere (e.g. in a worker thread, so the event loop that
        owns the books never blocks on calibration)."""
        ctx = self.matches[match_id]
        mf.prime()
        ctx.fair, ctx.cal_mid_a, ctx.cal_ms = mf, float(mid_a), int(now_ms)

    def apply_point(self, match_id: str, a_won: bool) -> None:
        self.matches[match_id].fair.apply_point(a_won)
        self.matches[match_id].fair.prime()

    def set_left_player(self, match_id: str, left_player: int) -> None:
        self.matches[match_id].left_player = int(left_player)

    # ------------------------------------------------------------------------------ the rule
    def evaluate(self, match_id: str, call, t_ms: int | None = None, hitter: int | None = None,
                 approve: bool = False) -> StrategyDecision:
        """Apply the rule to one call without sending anything. approve=True also asks the risk
        manager (no state change) and records its verdict in `reason`."""
        t0 = time.perf_counter()
        cfg = self.cfg
        ctx = self.matches[match_id]
        now = self.now_ms() if t_ms is None else int(t_ms)
        kind = str(getattr(call, "call", None) or getattr(call, "kind", None) or
                   (call.get("call") or call.get("kind") if isinstance(call, dict) else "") or "")
        d = StrategyDecision(match_id, now, kind.upper())
        lat = call.get("latency_ms") if isinstance(call, dict) else getattr(call, "latency_ms", None)
        if lat is not None and cfg.max_call_latency_ms is not None and lat > cfg.max_call_latency_ms:
            return self._done(d, t0, "stale_call")
        if cfg.rally_gate_s is not None and kind.upper() not in ("BOUNCE", "IN"):
            lb = self._last_bounce_ms.get(match_id)
            if lb is None or not (0 <= now - lb <= cfg.rally_gate_s * 1000.0):
                return self._done(d, t0, "no_rally_in_progress")
        mf = ctx.fair
        if mf.state is None:
            return self._done(d, t0, "match_over")
        d.state = asdict(mf.state)
        d.p_server0 = mf.p_server0
        j = mf.on_call(call, hitter=hitter, left_player=ctx.left_player, confidence=cfg.confidence)
        d.v_now, d.v_if_a, d.v_if_b, d.leverage = j.v_now, j.v_if_a, j.v_if_b, j.leverage
        d.confidence = j.confidence
        if j.winner is None:
            return self._done(d, t0, "no_point_decision" if kind.upper() in ("BOUNCE", "IN") else "unknown_winner")
        w = d.winner = int(j.winner)
        d.winner_name = ctx.names[w]
        d.p_point_winner = j.p_point_a if w == 0 else 1.0 - j.p_point_a
        d.expected_move = j.move(w)
        tok = d.token = ctx.token_a if w == 0 else ctx.token_b
        b = self.feed.book(tok)
        if not b.has_snapshot:
            return self._done(d, t0, "no_book")
        bid, ask = b.best_bid(), b.best_ask()
        d.bid, d.ask = bid, ask
        if ask is None or bid is None:
            return self._done(d, t0, "one_sided_book")
        d.mid = (bid + ask) / 2.0
        d.half_spread = (ask - bid) / 2.0
        if ask - bid > cfg.max_spread:
            return self._done(d, t0, "wide_spread")
        tick = d.tick = float(cfg.tick or b.tick_size or 0.01)
        limit = d.limit = round(ask + cfg.limit_ticks * tick, 6)
        if limit >= 1.0:
            return self._done(d, t0, "limit_at_or_above_1")
        # late-call guard: the book already moved half a point-jump since the pre-point calibration
        if ctx.cal_mid_a is not None:
            ref = ctx.cal_mid_a if w == 0 else 1.0 - ctx.cal_mid_a
            jump_up = j.token(w, j.v_if_a if w == 0 else j.v_if_b) - j.token(w)
            jump_dn = j.token(w) - j.token(w, j.v_if_b if w == 0 else j.v_if_a)
            d.moved_toward_winner = d.mid - ref
            if jump_up > 0 and d.moved_toward_winner >= cfg.moved_frac * jump_up:
                return self._done(d, t0, "book_already_repriced")
            if jump_dn > 0 and -d.moved_toward_winner >= cfg.moved_frac * jump_dn:
                return self._done(d, t0, "book_moved_against_call")
        d.fair_after = d.mid + d.expected_move
        d.fee = taker_fee(limit, cfg.fee_rate)
        d.edge_at_ask = d.fair_after - ask - taker_fee(ask, cfg.fee_rate)
        d.edge = d.fair_after - limit - d.fee
        if d.edge <= cfg.min_edge:
            return self._done(d, t0, "edge_below_cost")
        d.visible_shares = b.available("BUY", limit)
        d.shares = risk_parity_shares(limit, cfg.k, visible=d.visible_shares if cfg.cap_at_visible else None)
        if d.shares <= 0:
            return self._done(d, t0, "no_stale_depth")
        d.action = "SEND"
        if approve and self.risk is not None:
            ap = self.risk.approve(tok, "BUY", d.shares, limit, now_ms=now, fair=d.fair_after, match_id=match_id)
            if not ap.ok:
                d.action, d.reason = "REJECTED", f"risk:{ap.reason}"
            else:
                d.shares, d.reason = ap.shares, (f"risk clip: {ap.reason}" if ap.reason else "")
        d.compute_us = (time.perf_counter() - t0) * 1e6
        return d

    def on_call(self, match_id: str, call, t_ms: int | None = None, hitter: int | None = None) -> StrategyDecision:
        """Evaluate one call and, if the rule says so, submit the PAPER order."""
        t0 = time.perf_counter()
        now = self.now_ms() if t_ms is None else int(t_ms)
        if self.risk is not None:
            self.risk.vision_heartbeat(now)   # a call is proof that the vision engine is alive
        self.note_call(match_id, call, now)
        d = self.evaluate(match_id, call, now, hitter)
        if d.action == "SEND" and self.ex is not None:
            assert_paper_only()
            o = self.ex.submit(Decision(d.token, "BUY", d.shares, d.limit, t_decision=now, match_id=match_id,
                                        fair=d.fair_after,
                                        tag={"call": d.call, "winner": d.winner, "edge": d.edge}))
            d.order_id, d.order_status = o.id, o.status
            if o.status == "rejected":
                d.action, d.reason = "REJECTED", f"risk:{o.reason}"
            else:
                d.shares = o.shares
                if o.reason:
                    d.reason = f"risk clip: {o.reason}"
        d.total_us = (time.perf_counter() - t0) * 1e6
        self.decisions.append(d)
        return d

    def note_call(self, match_id: str, call, t_ms: int) -> None:
        """Rally state for the gate: remember the time of the last BOUNCE/IN call on this match."""
        kind = str(getattr(call, "call", None) or getattr(call, "kind", None) or
                   (call.get("call") or call.get("kind") if isinstance(call, dict) else "") or "")
        if kind.upper() in ("BOUNCE", "IN"):
            self._last_bounce_ms[match_id] = int(t_ms)

    @staticmethod
    def _done(d: StrategyDecision, t0: float, reason: str) -> StrategyDecision:
        d.action, d.reason = "SKIP", reason
        d.compute_us = (time.perf_counter() - t0) * 1e6
        return d

    def summary(self) -> dict:
        out = {"calls": len(self.decisions)}
        for a in ("SEND", "SKIP", "REJECTED"):
            out[a.lower()] = sum(d.action == a for d in self.decisions)
        out["skip_reasons"] = {}
        for d in self.decisions:
            if d.action != "SEND":
                out["skip_reasons"][d.reason] = out["skip_reasons"].get(d.reason, 0) + 1
        return out


__all__ = ["PAPER_ONLY", "CourtsideStrategy", "calibration_job", "fair_from_job", "MatchCtx", "StrategyConfig", "StrategyDecision",
           "assert_paper_only", "enable_live_trading", "LiveTradingForbidden"]
