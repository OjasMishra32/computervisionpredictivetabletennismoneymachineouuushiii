"""PAPER execution against live or recorded Polymarket books. Nothing is ever sent anywhere.

Timing (same model as src.paper.Engine, now event-driven and usable live):
    t_decision  local ms when the strategy decided (feed.now_ms() by default)
    t_arrive  = t_decision + one_way_ms        (FLORIDA 67 ms, LONDON 2 ms, or any value)
    t_exec    = t_arrive + venue_delay_ms      (Polymarket's 1 s marketable-order delay)
At t_exec (venue clock) the order walks the book AS IT STANDS THEN: every level inside the limit,
best first, minus liquidity our own earlier paper fills already took. Unfilled remainder is
killed (FAK; FOK = all or nothing). Each level pays the taker fee rate*q*(1-q) per share.

How "the book at t_exec" is found: the executor registers a clock hook on the feed, which runs
with the venue stamp of each incoming message BEFORE it is applied; orders with t_exec <= that
stamp fill against the pre-message book. Replay is therefore exact, and live is exact up to
feed reordering. Live, a quiet feed is covered by `run_timer()`, which fills once local time
passes t_exec + the feed's p95 delay with no newer message (the book has not changed).

SAFETY: paper only. There is no signing, no key handling and no HTTP/websocket client in this
module. `PaperExecutor` refuses credential-like arguments, `live=True`, and refuses to start if an
order-signing client library (py_clob_client, py_order_utils, eth_account) is loaded in the
process; `submit` re-checks PAPER_ONLY, the signing libraries and the environment on every call.
"""
from __future__ import annotations

import asyncio
import heapq
import itertools
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Callable

from src.paper import FEE_RATE, FLORIDA_MS, LONDON_MS, taker_fee

VENUE_DELAY_MS = 1000
PAPER_ONLY = True
LATENCY_PRESETS = {"florida": FLORIDA_MS, "london": LONDON_MS}
SIGNING_MODULES = ("py_clob_client", "py_order_utils", "eth_account")
# same list as engine/vision/events.py: a set (non-empty, non-false) variable is a request to go live
# PK / CLOB_* are the names py-clob-client's own examples read; the POLY_* forms are its L2 header names.
LIVE_ENV_FLAGS = ("COURTSIDE_LIVE_TRADING", "LIVE_TRADING", "ENABLE_LIVE_TRADING", "POLYMARKET_PRIVATE_KEY",
                  "PRIVATE_KEY", "PK", "WALLET_PRIVATE_KEY", "POLY_PRIVATE_KEY", "CLOB_API_KEY", "CLOB_SECRET",
                  "CLOB_PASS_PHRASE", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE", "POLY_API_KEY", "POLY_SECRET",
                  "POLY_PASSPHRASE")
_CREDENTIAL_HINTS = ("key", "secret", "pass", "mnemonic", "seed", "sign", "wallet", "funder", "private",
                     "auth", "token_secret", "credential")


class LiveTradingForbidden(RuntimeError):
    """Raised whenever anything tries to enable real trading or hand this engine credentials."""


def assert_paper(**kwargs) -> None:
    if PAPER_ONLY is not True:
        raise LiveTradingForbidden("PAPER_ONLY was modified; this engine never trades for real")
    for k, v in kwargs.items():
        kl = k.lower()
        if kl in ("live", "live_trading", "real", "send_orders") and v:
            raise LiveTradingForbidden(f"{k}={v!r}: live trading is not supported, paper only")
        if any(h in kl for h in _CREDENTIAL_HINTS):
            raise LiveTradingForbidden(f"refusing credential-like argument {k!r}: paper engine takes no keys")
        if kl not in ("live", "live_trading", "real", "send_orders"):
            raise TypeError(f"unexpected argument {k!r}")


def assert_no_signing_client() -> None:
    loaded = [m for m in SIGNING_MODULES if m in sys.modules]
    if loaded:
        raise LiveTradingForbidden(f"order-signing libraries loaded in this process: {loaded}; "
                                   "the paper engine refuses to run next to them")
    bad = [k for k in LIVE_ENV_FLAGS if os.environ.get(k, "").strip() not in ("", "0", "false", "False")]
    if bad:   # only checked for emptiness; values are never used
        raise LiveTradingForbidden(f"live-trading / credential variables set: {bad}; this engine is paper only")


# ======================================================================================
@dataclass
class Decision:
    token: str
    side: str                    # "BUY" | "SELL" of this outcome token
    shares: float
    limit: float                 # worst acceptable price
    t_decision: int | None = None   # local ms; default: feed.now_ms()
    match_id: str | None = None
    fair: float | None = None    # strategy's fair value of the token (for the risk edge filter)
    tag: dict = field(default_factory=dict)


@dataclass
class PaperOrder:
    id: int
    token: str
    side: str
    shares: float
    limit: float
    t_decision: int
    t_arrive: int
    t_exec: int
    match_id: str | None = None
    tag: dict = field(default_factory=dict)
    status: str = "pending"      # pending | filled | partial | missed | rejected
    reason: str = ""
    requested: float = 0.0       # shares asked before risk clipping
    filled: float = 0.0
    vwap: float | None = None
    fee: float = 0.0
    bid_at_decision: float | None = None
    ask_at_decision: float | None = None


@dataclass
class PaperFill:
    order_id: int
    token: str
    side: str
    shares: float
    price: float                 # VWAP over the levels taken
    fee: float
    levels: list                 # [(price, shares), ...]
    t_decision: int
    t_arrive: int
    t_exec: int
    book_ts: int                 # venue stamp of the book state we filled against
    match_id: str | None = None
    tag: dict = field(default_factory=dict)

    @property
    def cash_flow(self) -> float:
        """Signed cash change: BUY pays shares*price + fee, SELL receives shares*price - fee."""
        gross = self.shares * self.price
        return -(gross + self.fee) if self.side == "BUY" else gross - self.fee

    @property
    def slippage(self) -> float | None:
        """Price paid vs the touch the strategy saw at decision time (positive = worse)."""
        ref = self.tag.get("_touch")
        if ref is None:
            return None
        return self.price - ref if self.side == "BUY" else ref - self.price


def fee_for_levels(levels, rate: float = FEE_RATE) -> float:
    return sum(taker_fee(px, rate) * sz for px, sz in levels)


# ======================================================================================
class Ledger:
    """Cash, positions and marked equity of the paper book."""

    def __init__(self, cash: float = 0.0):
        self.start_cash = cash
        self.cash = cash
        self.pos: dict[str, float] = {}
        self.fees = 0.0
        self.last_px: dict[str, float] = {}
        self.settled: dict[str, float] = {}     # token -> settlement price (1 or 0)

    def on_fill(self, f: PaperFill) -> None:
        self.cash += f.cash_flow
        self.fees += f.fee
        sgn = 1.0 if f.side == "BUY" else -1.0
        self.pos[f.token] = self.pos.get(f.token, 0.0) + sgn * f.shares
        self.last_px[f.token] = f.price

    def settle(self, winning_token: str, market_tokens) -> float:
        """Resolve a market: winning token pays $1/share, others $0. Returns the cash paid."""
        paid = 0.0
        for t in market_tokens:
            v = 1.0 if t == winning_token else 0.0
            q = self.pos.pop(t, 0.0)
            paid += q * v
            self.settled[t] = v
        self.cash += paid
        return paid

    def equity(self, mark: Callable[[str], float | None] | None = None) -> float:
        eq = self.cash
        for t, q in self.pos.items():
            if abs(q) < 1e-12:
                continue
            px = mark(t) if mark else None
            if px is None or (isinstance(px, float) and math.isnan(px)):
                px = self.last_px.get(t, 0.0)
            eq += q * px
        return eq

    def pnl(self, mark=None) -> float:
        return self.equity(mark) - self.start_cash


# ======================================================================================
class PaperExecutor:
    """Simulated taker execution. `feed` is a BaseFeed (live or replay) or anything with
    book(token), now_ms(), on_clock(fn) and on(fn)."""

    def __init__(self, feed=None, one_way_ms: int = FLORIDA_MS, venue_delay_ms: int = VENUE_DELAY_MS,
                 fee_rate: float = FEE_RATE, tif: str = "FAK", risk=None, ledger: Ledger | None = None,
                 consume_ttl_ms: int = 10_000, clock: Callable[[], int] | None = None,
                 on_fill: Callable[[PaperFill], None] | None = None, **kwargs):
        assert_paper(**kwargs)
        assert_no_signing_client()
        if tif not in ("FAK", "FOK"):
            raise ValueError("tif must be FAK or FOK")
        self.one_way_ms, self.venue_delay_ms, self.fee_rate, self.tif = one_way_ms, venue_delay_ms, fee_rate, tif
        self.risk = risk
        self.ledger = ledger if ledger is not None else Ledger()
        self.consume_ttl_ms = consume_ttl_ms
        self._clock = clock
        self._on_fill = on_fill
        self.feed = None
        self.queue: list = []
        self.orders: list[PaperOrder] = []
        self.fills: list[PaperFill] = []
        self.misses: list[PaperOrder] = []
        self.rejects: list[PaperOrder] = []
        self._ids = itertools.count(1)
        self._consumed: dict[tuple[str, str], dict[float, list]] = {}   # (token, side) -> px -> [shares, expiry]
        self.market_tokens: dict[str, list[str]] = {}                   # condition id -> tokens
        if feed is not None:
            self.attach(feed)

    # wiring -------------------------------------------------------------------------------
    def attach(self, feed) -> "PaperExecutor":
        self.feed = feed
        feed.on_clock(self.on_clock)
        feed.on(self._on_market_event)
        return self

    def now_ms(self) -> int:
        if self._clock is not None:
            return int(self._clock())
        return int(self.feed.now_ms()) if self.feed is not None else 0

    def register_market(self, market: str, tokens) -> None:
        self.market_tokens[market] = list(tokens)

    def _on_market_event(self, ev) -> None:
        if ev.kind == "resolved" and ev.asset_id:
            toks = self.market_tokens.get(ev.market) or [t for t, m in self.feed.market_of.items() if m == ev.market]
            self.flush(ev.ts_server)
            self.ledger.settle(ev.asset_id, toks)
            if self.risk is not None:
                for m in {self.risk.token_info[t][0] for t in toks if t in self.risk.token_info}:
                    self.risk.settle(m)

    # orders -------------------------------------------------------------------------------
    def submit(self, d: Decision) -> PaperOrder:
        if PAPER_ONLY is not True:
            raise LiveTradingForbidden("PAPER_ONLY was modified")
        assert_no_signing_client()   # a signing library or credential loaded after construction (~15 us)
        if d.side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {d.side!r}")
        t_dec = int(d.t_decision if d.t_decision is not None else self.now_ms())
        o = PaperOrder(next(self._ids), d.token, d.side, float(d.shares), float(d.limit), t_dec,
                       t_dec + self.one_way_ms, t_dec + self.one_way_ms + self.venue_delay_ms,
                       d.match_id, dict(d.tag), requested=float(d.shares))
        if self.feed is not None:
            b = self.feed.book(d.token)
            o.bid_at_decision, o.ask_at_decision = b.best_bid(), b.best_ask()
            o.tag["_touch"] = o.ask_at_decision if d.side == "BUY" else o.bid_at_decision
        self.orders.append(o)
        if not (0.0 < o.limit < 1.0) or not (o.shares > 0):
            return self._reject(o, "bad_order")
        if self.risk is not None:
            ap = self.risk.approve(d.token, d.side, o.shares, o.limit, now_ms=t_dec, fair=d.fair,
                                   match_id=d.match_id)
            if not ap.ok:
                return self._reject(o, ap.reason)
            o.shares = ap.shares
            if ap.reason:
                o.reason = ap.reason
            self.risk.on_submit(o)
        heapq.heappush(self.queue, (o.t_exec, o.id, o))
        return o

    def _reject(self, o: PaperOrder, reason: str) -> PaperOrder:
        o.status, o.reason, o.shares = "rejected", reason, 0.0
        self.rejects.append(o)
        return o

    # execution ----------------------------------------------------------------------------
    def on_clock(self, ts_server: int) -> None:
        """Feed hook: fill every order due at or before this venue stamp (pre-message book)."""
        q = self.queue
        while q and q[0][0] <= ts_server:
            self._execute(heapq.heappop(q)[2])

    def flush(self, upto: int | None = None) -> None:
        """Fill due orders against current books (end of a replay, or upto a venue time)."""
        q = self.queue
        while q and (upto is None or q[0][0] <= upto):
            self._execute(heapq.heappop(q)[2])

    async def run_timer(self, poll_ms: int = 20, default_grace_ms: int = 1000, max_grace_ms: int = 2000) -> None:
        """Live fallback for quiet feeds (see module doc). Cancel the task to stop it."""
        while True:
            await asyncio.sleep(poll_ms / 1000)
            if not self.queue or self.feed is None:
                continue
            p95 = self.feed.latency.p95()
            grace = min(max_grace_ms, p95 if p95 is not None else default_grace_ms)
            now = self.now_ms()
            while self.queue and self.queue[0][0] + grace <= now:
                self._execute(heapq.heappop(self.queue)[2])

    def _consumed_map(self, token: str, side: str, t: int) -> dict[float, float]:
        m = self._consumed.get((token, side))
        if not m:
            return {}
        for px in [px for px, (_, exp) in m.items() if exp <= t]:
            del m[px]
        return {px: v[0] for px, v in m.items()}

    def _execute(self, o: PaperOrder) -> None:
        if self.feed is None:
            raise RuntimeError("executor has no feed attached")
        book = self.feed.book(o.token)
        if not getattr(book, "has_snapshot", True):
            return self._miss(o, "no_book")
        consumed = self._consumed_map(o.token, o.side, o.t_exec)
        levels = book.sweep(o.side, o.shares, o.limit, consumed)
        got = sum(s for _, s in levels)
        if self.tif == "FOK" and got < o.shares - 1e-9:
            return self._miss(o, "fok_short")
        if got <= 1e-12:
            return self._miss(o, "no_liquidity_in_limit")
        fee = fee_for_levels(levels, self.fee_rate)
        vwap = levels[0][0] if len(levels) == 1 else sum(p * s for p, s in levels) / got
        f = PaperFill(o.id, o.token, o.side, got, vwap, fee, levels, o.t_decision, o.t_arrive, o.t_exec,
                      getattr(book, "ts_server", 0), o.match_id, o.tag)
        o.filled, o.vwap, o.fee = got, vwap, fee
        o.status = "filled" if got >= o.shares - 1e-9 else "partial"
        cm = self._consumed.setdefault((o.token, o.side), {})
        exp = o.t_exec + self.consume_ttl_ms
        for px, s in levels:
            cur = cm.get(px)
            cm[px] = [s + (cur[0] if cur and cur[1] > o.t_exec else 0.0), exp]
        self.fills.append(f)
        self.ledger.on_fill(f)
        if self.risk is not None:
            self.risk.on_result(o, got, f)
        if self._on_fill is not None:
            self._on_fill(f)

    def _miss(self, o: PaperOrder, reason: str) -> None:
        o.status, o.reason = "missed", reason
        self.misses.append(o)
        if self.risk is not None:
            self.risk.on_result(o, 0.0, None)

    # reporting ----------------------------------------------------------------------------
    def mark(self, token: str) -> float | None:
        return self.feed.book(token).mid() if self.feed is not None else None

    def summary(self) -> dict:
        sent = [o for o in self.orders if o.status != "rejected"]
        sh = sum(f.shares for f in self.fills)
        slip = [f.slippage for f in self.fills if f.slippage is not None]
        return {
            "orders": len(self.orders), "sent": len(sent), "rejected": len(self.rejects),
            "filled": sum(o.status == "filled" for o in sent), "partial": sum(o.status == "partial" for o in sent),
            "missed": len(self.misses), "pending": len(self.queue),
            "fill_rate_shares": sh / max(1e-9, sum(o.shares for o in sent if o.status != "pending")),
            "shares": sh, "notional": sum(f.shares * f.price for f in self.fills), "fees": self.ledger.fees,
            "avg_slippage": (sum(s * f.shares for s, f in zip(slip, self.fills)) / max(sh, 1e-9)) if slip else None,
            "equity_pnl_marked_mid": self.ledger.pnl(self.mark),
            "one_way_ms": self.one_way_ms, "venue_delay_ms": self.venue_delay_ms, "tif": self.tif,
        }


# ======================================================================================
def _demo(argv=None) -> None:
    """Replay a recording and fire a 100-share FAK at the stale touch after every >= 2c mid jump,
    once per preset, to show how much stale depth survives the 1 s delay from each location."""
    import argparse
    import json

    from engine.market.clob import ReplayClobFeed

    ap = argparse.ArgumentParser()
    ap.add_argument("--files", default="data/live/market_20261003_1501.jsonl")
    ap.add_argument("--limit", type=int, default=300_000, help="messages to replay")
    ap.add_argument("--jump", type=float, default=0.02)
    ap.add_argument("--shares", type=float, default=100)
    a = ap.parse_args(argv)
    out = {}
    for name, ow in (("florida", FLORIDA_MS), ("london", LONDON_MS), ("instant", 0)):
        feed = ReplayClobFeed(a.files, one_way_ms=ow)
        ex = PaperExecutor(feed, one_way_ms=ow, venue_delay_ms=VENUE_DELAY_MS if name != "instant" else 0)
        last_mid: dict[str, float] = {}

        def strat(ev, feed=feed, ex=ex, last_mid=last_mid):
            if ev.kind not in ("price_change", "book") or ev.best_bid is None or ev.best_ask is None:
                return
            mid = (ev.best_bid + ev.best_ask) / 2
            prev = last_mid.get(ev.asset_id)
            last_mid[ev.asset_id] = mid
            if prev is None or ev.best_ask - ev.best_bid > 0.05:
                return
            if mid - prev >= a.jump:         # price went up: lift whatever is left near the old touch
                ex.submit(Decision(ev.asset_id, "BUY", a.shares, min(0.99, round(prev + 0.01, 2))))

        feed.on(strat)
        feed.run_sync(limit=a.limit)
        ex.flush()
        out[name] = ex.summary()
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    _demo()
