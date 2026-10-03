"""Pre-trade risk for the paper engine: the frozen v2 limits plus a daily stop and kill switches.

v2 rule (HYPOTHESIS_V2.md; research/v2/sizing `G_50pct_net100`, used by src/v2.py):
  * risk-parity size  shares = k * $1,000 / sqrt(q(1-q)), never over $1,000 per order
  * price zone        q in [0.05, 0.95]
  * fee-aware filter  trade only if the expected edge beats the taker fee rate*q*(1-q)
  * per-match cap     |net outcome-0 shares| <= 100; risk-reducing trades are always allowed
                      (an order may reduce, and even flip, up to the cap on the other side:
                      allowed = cap - d * net, exactly as research/v2/sizing/engine.apply_caps)
Added for live running:
  * daily stop        marked P&L since 00:00 UTC below -daily_stop_usd latches until next day
  * kill switches     feed stale > 2 s, vision stale, feed delay above its p95 baseline, manual
                      While any is active only risk-reducing orders pass, clipped to flat (no flip
                      into new exposure); manual halts all.
  * no naked shorts   SELL only up to held shares (Polymarket cannot short; buy the other token)
  * in-flight orders  reserved against the net cap until they fill or miss (1 s venue delay
                      means several orders can be in flight at once)

The constants are checked against the v2 source by tests/test_engine_risk.py. This module
deliberately does not import src.v2: that module does `import engine` for the sizing code
(research/v2/sizing/engine.py), which collides with this `engine` package in one process.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from src.paper import FEE_RATE, taker_fee

V2_MAX_ORDER_USD = 1_000.0
V2_NET_CAP_SHARES = 100.0
V2_ZONE = (0.05, 0.95)
V2_K = 0.10            # deployment factor: 0.092 / 0.098 / 0.101 fitted walk-forward for Jun/Jul/Aug 2026
DAY_MS = 86_400_000


def risk_parity_shares(q: float, k: float = V2_K, usd_cap: float = V2_MAX_ORDER_USD,
                       visible: float | None = None) -> float:
    """v2 size: k * $1k / sqrt(q(1-q)), capped at usd_cap/q and at the visible liquidity."""
    if not (0.0 < q < 1.0):
        return 0.0
    s = min(k * V2_MAX_ORDER_USD / math.sqrt(q * (1.0 - q)), usd_cap / q)
    return s if visible is None else min(s, visible)


@dataclass
class RiskConfig:
    max_order_usd: float = V2_MAX_ORDER_USD
    net_cap_shares: float = V2_NET_CAP_SHARES
    zone: tuple[float, float] = V2_ZONE
    min_shares: float = 5.0              # Polymarket's usual minimum order size
    fee_rate: float = FEE_RATE
    min_edge: float = 0.0                # required edge per share AFTER fee (when fair is given)
    require_fair: bool = False           # reject risk-increasing orders that carry no fair value
    daily_stop_usd: float | None = 1_000.0   # ~2x the worst in-sample v2 day ($-551 on $28k)
    feed_stale_ms: int = 2_000
    vision_stale_ms: int = 1_000
    require_vision: bool = True          # vision-driven strategies: no heartbeat = stale
    latency_limit_ms: float | None = None    # None: the feed's own rolling p95 is the baseline
    latency_min_samples: int = 200
    latency_floor_ms: float = 150.0      # never trip below this (67 vs 70 ms is noise)
    latency_abs_ms: float = 2_000.0      # always trip above this, whatever the baseline
    allow_reducing_when_killed: bool = True


@dataclass
class Approval:
    ok: bool
    shares: float
    reason: str = ""                     # rejection reason, or the clips applied ("usd_cap,net_cap")
    reducing: bool = False
    kills: dict = field(default_factory=dict)


class RiskManager:
    def __init__(self, cfg: RiskConfig | None = None, feed=None, clock: Callable[[], int] | None = None,
                 equity_fn: Callable[[], float] | None = None):
        self.cfg = cfg or RiskConfig()
        self.feed = feed
        self._clock = clock
        self.equity_fn = equity_fn
        self.token_info: dict[str, tuple[str, int]] = {}   # token -> (match_id, outcome index)
        self.net: dict[str, float] = {}                    # match -> filled net outcome-0 shares
        self.pending: dict[int, tuple[str, float, str, str, float]] = {}  # order id -> (match, d*shares, token, side, shares)
        self.held: dict[str, float] = {}                   # token -> shares held
        self.manual: dict[str, str] = {}                   # latched manual kills
        self.last_vision_ms: int | None = None
        self._day: int | None = None
        self._day_open: float | None = None
        self._stopped_day: int | None = None
        self.log: list[tuple[int, str, str]] = []          # (t, kind, detail) for kill transitions
        self._active: set[str] = set()

    # registry --------------------------------------------------------------------------
    def register(self, token: str, match_id: str, outcome: int) -> None:
        self.token_info[token] = (match_id, int(outcome))

    def register_market(self, match_id: str, token0: str, token1: str) -> None:
        self.register(token0, match_id, 0)
        self.register(token1, match_id, 1)

    def direction(self, token: str, side: str) -> int:
        """+1 if the order adds outcome-0 exposure (BUY token0 / SELL token1), else -1."""
        _, oc = self.token_info[token]
        buy = side == "BUY"
        return 1 if (buy and oc == 0) or (not buy and oc == 1) else -1

    def exposure(self, match_id: str) -> float:
        """Filled net outcome-0 shares plus every in-flight order's signed size."""
        return self.net.get(match_id, 0.0) + sum(v[1] for v in self.pending.values() if v[0] == match_id)

    def now_ms(self) -> int:
        if self._clock is not None:
            return int(self._clock())
        return int(self.feed.now_ms()) if self.feed is not None else 0

    # health ----------------------------------------------------------------------------
    def vision_heartbeat(self, t_ms: int) -> None:
        self.last_vision_ms = max(self.last_vision_ms or 0, int(t_ms))

    def kill(self, reason: str = "manual", detail: str = "") -> None:
        self.manual[reason] = detail or reason

    def clear(self, reason: str = "manual") -> None:
        self.manual.pop(reason, None)

    def daily_pnl(self, now_ms: int) -> float | None:
        if self.equity_fn is None:
            return None
        eq = float(self.equity_fn())
        day = now_ms // DAY_MS
        if day != self._day:
            self._day, self._day_open = day, eq
        return eq - self._day_open

    def kills(self, now_ms: int | None = None) -> dict[str, str]:
        """Active kill switches -> human-readable detail."""
        c = self.cfg
        now = self.now_ms() if now_ms is None else int(now_ms)
        out = dict(self.manual)
        if self.feed is not None:
            st = self.feed.stale_ms(now)
            if st > c.feed_stale_ms:
                out["feed_stale"] = f"no market data for {st} ms"
            lat = self.feed.latency
            recent = lat.recent()
            base = c.latency_limit_ms
            if base is None and lat.n >= c.latency_min_samples:
                base = lat.p95()
            if recent is not None and base is not None and recent > max(base, c.latency_floor_ms):
                out["latency"] = f"feed delay {recent:.0f} ms > p95 baseline {base:.0f} ms"
            elif recent is not None and recent > c.latency_abs_ms:
                out["latency"] = f"feed delay {recent:.0f} ms > {c.latency_abs_ms:.0f} ms"
        if c.require_vision or self.last_vision_ms is not None:
            if self.last_vision_ms is None:
                out["vision_stale"] = "no vision heartbeat yet"
            elif now - self.last_vision_ms > c.vision_stale_ms:
                out["vision_stale"] = f"vision silent for {now - self.last_vision_ms} ms"
        if c.daily_stop_usd is not None:
            pnl = self.daily_pnl(now)
            day = now // DAY_MS
            if pnl is not None and pnl < -c.daily_stop_usd:
                self._stopped_day = day
            if self._stopped_day == day:
                out["daily_stop"] = f"day P&L {pnl:.2f} hit -{c.daily_stop_usd:.0f}" if pnl is not None else "daily stop"
        cur = set(out)
        for k in cur - self._active:
            self.log.append((now, "kill_on", f"{k}: {out[k]}"))
        for k in self._active - cur:
            self.log.append((now, "kill_off", k))
        self._active = cur
        return out

    # pre-trade -------------------------------------------------------------------------
    def approve(self, token: str, side: str, shares: float, limit: float, now_ms: int | None = None,
                fair: float | None = None, match_id: str | None = None) -> Approval:
        c = self.cfg
        now = self.now_ms() if now_ms is None else int(now_ms)
        if side not in ("BUY", "SELL") or not (0.0 < limit < 1.0) or not (shares > 0):
            return Approval(False, 0.0, "bad_order")
        if token not in self.token_info:
            return Approval(False, 0.0, "unknown_token")
        mid, _ = self.token_info[token]
        if match_id is not None and match_id != mid:
            return Approval(False, 0.0, "match_mismatch")
        d = self.direction(token, side)
        expo = self.exposure(mid)
        reducing = d * expo < 0
        clips = []
        if side == "SELL":   # can only sell what we hold (minus sells already in flight)
            inflight = sum(v[4] for v in self.pending.values() if v[2] == token and v[3] == "SELL")
            avail = self.held.get(token, 0.0) - inflight
            if avail <= 1e-9:
                return Approval(False, 0.0, "no_inventory", reducing)
            if shares > avail:
                shares, clips = avail, clips + ["inventory"]
        kills = self.kills(now)
        if kills:
            if "manual" in kills or not (reducing and c.allow_reducing_when_killed):
                return Approval(False, 0.0, "kill:" + ",".join(sorted(kills)), reducing, kills)
        if not reducing:
            lo, hi = c.zone
            if not (lo <= limit <= hi):
                return Approval(False, 0.0, "zone", reducing, kills)
            if fair is None and c.require_fair:
                return Approval(False, 0.0, "no_fair_value", reducing, kills)
            if fair is not None:
                gross = fair - limit if side == "BUY" else limit - fair
                if gross - taker_fee(limit, c.fee_rate) <= c.min_edge:
                    return Approval(False, 0.0, "edge_below_fee", reducing, kills)
        cap_usd = c.max_order_usd / limit
        if shares > cap_usd:
            shares, clips = cap_usd, clips + ["usd_cap"]
        room = max(0.0, c.net_cap_shares - d * expo)
        if shares > room:
            shares, clips = room, clips + ["net_cap"]
        if kills and shares > abs(expo):   # killed: a reducing order may flatten, never flip into new exposure
            shares, clips = abs(expo), clips + ["kill_flatten_only"]
        if shares < c.min_shares - 1e-9:
            return Approval(False, 0.0, "net_cap" if room < c.min_shares else "below_min", reducing, kills)
        return Approval(True, shares, ",".join(clips), reducing, kills)

    # order lifecycle (called by the executor) -------------------------------------------
    def on_submit(self, order) -> None:
        mid, _ = self.token_info[order.token]
        d = self.direction(order.token, order.side)
        self.pending[order.id] = (mid, d * order.shares, order.token, order.side, order.shares)

    def on_result(self, order, filled: float, fill=None) -> None:
        """Release the reservation and book the filled shares (0 for a miss)."""
        rec = self.pending.pop(order.id, None)
        if order.token not in self.token_info:
            return
        mid, _ = self.token_info[order.token]
        d = self.direction(order.token, order.side)
        if filled > 0:
            self.net[mid] = self.net.get(mid, 0.0) + d * filled
            sgn = 1.0 if order.side == "BUY" else -1.0
            self.held[order.token] = self.held.get(order.token, 0.0) + sgn * filled
        del rec

    def settle(self, match_id: str) -> None:
        """Market resolved: exposure is gone."""
        self.net.pop(match_id, None)
        for t, (m, _) in self.token_info.items():
            if m == match_id:
                self.held.pop(t, None)

    def snapshot(self) -> dict:
        return {"net": dict(self.net), "pending": len(self.pending), "held": dict(self.held),
                "kills": sorted(self._active), "day_open_equity": self._day_open}
