"""L2 order book and feed-latency tracker shared by the live and replay CLOB feeds.

`L2Book` extends `src.paper.Book` (same `bids`/`asks` dicts of price -> size and the same
`walk`), so a book built here can be handed to anything written against the research engine.
On top it keeps a cached top of book (O(1) on the hot path; recomputed only when the best level
is removed), depth queries, a per-level sweep used by the paper executor, and the server/local
timestamps of the last update.

Polymarket conventions: in `price_change` messages side "BUY" is a bid level and "SELL" an ask
level; size 0 removes the level. Prices are decimal strings ("0.63"); float() of the same
string always gives the same key, so the dicts never hold two keys for one tick.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Iterable

from src.paper import Book

BID, ASK = "BUY", "SELL"   # level sides as the venue names them


def _pairs(levels: Iterable) -> Iterable[tuple[float, float]]:
    for x in levels or ():
        if isinstance(x, dict):
            yield float(x["price"]), float(x["size"])
        else:
            yield float(x[0]), float(x[1])


class L2Book(Book):
    """Full-depth book for one outcome token."""

    def __init__(self, asset_id: str = "", bids=None, asks=None):
        super().__init__(bids={}, asks={})
        self.asset_id = asset_id
        self.market = ""
        self.tick_size = 0.01
        self.ts_server = 0          # server ms of the last update applied
        self.ts_local = 0           # local ms at which that update was received / replayed
        self.n_updates = 0
        self.has_snapshot = False   # False until a full `book` snapshot arrived (after (re)connect)
        self.last_trade: tuple | None = None   # (price, size, taker side, server ms)
        self._bb: float | None = None
        self._ba: float | None = None
        self._bb_dirty = self._ba_dirty = False
        if bids or asks:
            self.snapshot(bids or [], asks or [], 0, 0)

    # updates ---------------------------------------------------------------------------
    def snapshot(self, bids, asks, ts_server: int, ts_local: int) -> None:
        self.bids = {p: s for p, s in _pairs(bids) if s > 0}
        self.asks = {p: s for p, s in _pairs(asks) if s > 0}
        self._bb_dirty = self._ba_dirty = True
        self.has_snapshot = True
        self._stamp(ts_server, ts_local)

    def set_level(self, side: str, price: float, size: float, ts_server: int = 0, ts_local: int = 0) -> None:
        """Absolute level update (Polymarket price_change semantics: size is the new total)."""
        if side == BID:
            if size <= 0:
                if self.bids.pop(price, None) is not None and price == self._bb:
                    self._bb_dirty = True
            else:
                self.bids[price] = size
                if not self._bb_dirty and (self._bb is None or price > self._bb):
                    self._bb = price
        else:
            if size <= 0:
                if self.asks.pop(price, None) is not None and price == self._ba:
                    self._ba_dirty = True
            else:
                self.asks[price] = size
                if not self._ba_dirty and (self._ba is None or price < self._ba):
                    self._ba = price
        self._stamp(ts_server, ts_local)

    def _stamp(self, ts_server: int, ts_local: int) -> None:
        if ts_server:
            self.ts_server = max(self.ts_server, ts_server)
        if ts_local:
            self.ts_local = max(self.ts_local, ts_local)
        self.n_updates += 1

    # top of book -------------------------------------------------------------------------
    def best_bid(self) -> float | None:
        if self._bb_dirty:
            self._bb = max(self.bids) if self.bids else None
            self._bb_dirty = False
        return self._bb

    def best_ask(self) -> float | None:
        if self._ba_dirty:
            self._ba = min(self.asks) if self.asks else None
            self._ba_dirty = False
        return self._ba

    def spread(self) -> float | None:
        b, a = self.best_bid(), self.best_ask()
        return None if b is None or a is None else a - b

    def crossed(self) -> bool:
        b, a = self.best_bid(), self.best_ask()
        return b is not None and a is not None and b >= a

    def microprice(self) -> float | None:
        b, a = self.best_bid(), self.best_ask()
        if b is None or a is None:
            return None
        qb, qa = self.bids[b], self.asks[a]
        return (a * qb + b * qa) / (qb + qa)

    # depth -------------------------------------------------------------------------------
    def levels(self, side: str, n: int | None = None) -> list[tuple[float, float]]:
        """Levels from the best outward. side: "bid"/"BUY" = bids, "ask"/"SELL" = asks."""
        if side in ("bid", BID):
            lv = sorted(self.bids.items(), reverse=True)
        else:
            lv = sorted(self.asks.items())
        return lv if n is None else lv[:n]

    def depth(self, side: str, within: float | None = None, n_levels: int | None = None) -> tuple[float, float]:
        """(shares, dollars) resting on one side, optionally only within `within` of the best
        price or over the best `n_levels` levels."""
        lv = self.levels(side, n_levels)
        if not lv:
            return 0.0, 0.0
        if within is not None:
            best = lv[0][0]
            lv = [(p, s) for p, s in lv if abs(p - best) <= within + 1e-9]
        return sum(s for _, s in lv), sum(p * s for p, s in lv)

    def available(self, taker_side: str, limit: float) -> float:
        """Shares a taker could take right now inside `limit` (BUY lifts asks <= limit)."""
        if taker_side == BID:
            return sum(s for p, s in self.asks.items() if p <= limit + 1e-12)
        return sum(s for p, s in self.bids.items() if p >= limit - 1e-12)

    def sweep(self, taker_side: str, shares: float, limit: float, consumed: dict | None = None
              ) -> list[tuple[float, float]]:
        """Per-level fills for a marketable order: [(price, shares), ...] best first.
        `consumed` maps price -> shares already taken by our own earlier paper fills, which
        are subtracted from the displayed size (we cannot take the same liquidity twice)."""
        out, left = [], shares
        for px, sz in self.levels("ask" if taker_side == BID else "bid"):
            if (taker_side == BID and px > limit + 1e-12) or (taker_side != BID and px < limit - 1e-12):
                break
            if consumed:
                sz = sz - consumed.get(px, 0.0)
            if sz <= 1e-12:
                continue
            take = min(sz, left)
            out.append((px, take))
            left -= take
            if left <= 1e-9:
                break
        return out

    def copy(self) -> "L2Book":
        b = L2Book(self.asset_id)
        b.bids, b.asks = dict(self.bids), dict(self.asks)
        b._bb_dirty = b._ba_dirty = True
        b.market, b.tick_size, b.ts_server, b.ts_local = self.market, self.tick_size, self.ts_server, self.ts_local
        b.has_snapshot, b.last_trade, b.n_updates = self.has_snapshot, self.last_trade, self.n_updates
        return b

    def __repr__(self) -> str:
        return (f"L2Book({self.asset_id[:10]}.. bid={self.best_bid()} ask={self.best_ask()} "
                f"levels={len(self.bids)}/{len(self.asks)} ts={self.ts_server})")


class LatencyTracker:
    """Local receive time minus server stamp, per message (ms).

    Includes any local-vs-venue clock offset, so it is a feed-delay measure, not a pure network
    one-way. `recent()` is the median of the last `recent` samples; the percentiles are over the
    long window of samples OLDER than those, so a burst of slow messages cannot raise its own
    baseline. The latency kill switch trips when recent() > p95()."""

    def __init__(self, window: int = 5000, recent: int = 25):
        self.samples: deque[int] = deque(maxlen=window)
        self.recent_samples: deque[int] = deque(maxlen=recent)
        self._sorted: list[int] | None = None
        self.n = 0
        self.last: int | None = None

    def add(self, ts_server: int, ts_local: int) -> None:
        d = int(ts_local) - int(ts_server)
        rs = self.recent_samples
        if len(rs) == rs.maxlen:
            self.samples.append(rs[0])
            self._sorted = None
        rs.append(d)
        self.n += 1
        self.last = d

    def pct(self, q: float) -> float | None:
        if not self.samples:
            if not self.recent_samples:
                return None
            s = sorted(self.recent_samples)   # warm-up: too few samples for a separate baseline
        else:
            if self._sorted is None:
                self._sorted = sorted(self.samples)
            s = self._sorted
        i = min(len(s) - 1, max(0, int(math.ceil(q / 100.0 * len(s))) - 1))
        return float(s[i])

    def p50(self) -> float | None:
        return self.pct(50)

    def p95(self) -> float | None:
        return self.pct(95)

    def p99(self) -> float | None:
        return self.pct(99)

    def recent(self) -> float | None:
        if not self.recent_samples:
            return None
        s = sorted(self.recent_samples)
        return float(s[len(s) // 2])

    def summary(self) -> dict:
        return {"n": self.n, "last_ms": self.last, "p50_ms": self.p50(), "p95_ms": self.p95(),
                "p99_ms": self.p99(), "recent_ms": self.recent()}
