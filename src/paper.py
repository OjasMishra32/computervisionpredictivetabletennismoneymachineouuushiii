"""Paper trading against recorded live Polymarket order books.

Replays the CLOB websocket recording (book snapshots + per-level price_change updates)
in server-time order and rebuilds every asset's L2 book. A strategy sees the book
`one_way_ms` after the server stamped it, its marketable order reaches the engine
`one_way_ms` later, waits the venue's `delay_ms`, and then fills against the book as it
stands at that moment, walking levels for size and paying the taker fee. Read-only: it
never sends an order anywhere.

Latency presets: FLORIDA = 67 ms one-way (measured median from Gainesville through the
Cloudflare Miami edge), LONDON = 2 ms (co-located with the matching engine; inferred).
"""
from __future__ import annotations

import glob
import gzip
import heapq
import json
from dataclasses import dataclass, field
from typing import Callable, Iterator

FLORIDA_MS, LONDON_MS = 67, 2
FEE_RATE = 0.05


def taker_fee(p: float, rate: float = FEE_RATE) -> float:
    return rate * p * (1 - p)


def iter_messages(pattern: str = "data/live*/market_*") -> Iterator[dict]:
    """All recorded CLOB messages, merged across files and sorted by server timestamp."""
    rows = []
    for f in sorted(glob.glob(pattern)):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt") as fh:
            try:
                for line in fh:
                    try:
                        m = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = m.get("timestamp")
                    if ts is None or m.get("event_type") not in ("book", "price_change", "last_trade_price",
                                                                   "market_resolved"):
                        continue
                    rows.append((int(ts), m))
            except EOFError:
                pass
    rows.sort(key=lambda r: r[0])
    seen = set()
    for ts, m in rows:  # the same message can sit in two overlapping recordings
        key = (ts, m.get("event_type"), m.get("asset_id"), m.get("hash") or json.dumps(m.get("price_changes"))[:80])
        if key in seen:
            continue
        seen.add(key)
        yield m


@dataclass
class Book:
    bids: dict = field(default_factory=dict)  # price -> size
    asks: dict = field(default_factory=dict)

    def best_bid(self):
        return max(self.bids) if self.bids else None

    def best_ask(self):
        return min(self.asks) if self.asks else None

    def mid(self):
        b, a = self.best_bid(), self.best_ask()
        return None if b is None or a is None else (a + b) / 2

    def walk(self, side: str, shares: float, limit: float):
        """Fill up to `shares` against the book within `limit`; returns (filled, vwap)."""
        levels = sorted(self.asks.items()) if side == "BUY" else sorted(self.bids.items(), reverse=True)
        got, cost = 0.0, 0.0
        for px, sz in levels:
            if (side == "BUY" and px > limit) or (side == "SELL" and px < limit):
                break
            take = min(sz, shares - got)
            got += take
            cost += take * px
            if got >= shares - 1e-9:
                break
        return got, (cost / got if got else None)


@dataclass
class Order:
    t_exec: int
    asset: str
    side: str          # BUY or SELL of this asset
    shares: float
    limit: float
    tag: dict


@dataclass
class Fill:
    t_signal: int
    t_exec: int
    asset: str
    side: str
    shares: float
    price: float
    fee: float
    tag: dict


class Engine:
    def __init__(self, one_way_ms: int = FLORIDA_MS, delay_ms: int = 1000, fee_rate: float = FEE_RATE):
        self.one_way, self.delay, self.fee_rate = one_way_ms, delay_ms, fee_rate
        self.books: dict[str, Book] = {}
        self.queue: list = []
        self.fills: list[Fill] = []
        self.misses: list[dict] = []
        self.winners: dict[str, str] = {}   # market -> winning asset
        self.now = 0

    # strategy API --------------------------------------------------------
    def send(self, t_seen: int, asset: str, side: str, shares: float, limit: float, tag: dict | None = None):
        """Called by a strategy at the time it saw the data (server ts + one-way)."""
        t_exec = t_seen + self.one_way + self.delay
        heapq.heappush(self.queue, (t_exec, id(tag), Order(t_exec, asset, side, shares, limit,
                                                           {**(tag or {}), "t_signal": t_seen})))

    def book(self, asset: str) -> Book:
        return self.books.setdefault(asset, Book())

    # replay ----------------------------------------------------------------
    def _execute_due(self, upto: int):
        while self.queue and self.queue[0][0] <= upto:
            _, _, o = heapq.heappop(self.queue)
            got, vwap = self.book(o.asset).walk(o.side, o.shares, o.limit)
            if got > 0:
                fee = taker_fee(vwap, self.fee_rate) * got
                self.fills.append(Fill(o.tag["t_signal"], o.t_exec, o.asset, o.side, got, vwap, fee, o.tag))
            else:
                self.misses.append({"t_exec": o.t_exec, "asset": o.asset, "side": o.side, **o.tag})

    def _apply(self, m: dict):
        e = m["event_type"]
        if e == "book":
            b = self.book(m["asset_id"])
            b.bids = {float(x["price"]): float(x["size"]) for x in m.get("bids", []) if float(x["size"]) > 0}
            b.asks = {float(x["price"]): float(x["size"]) for x in m.get("asks", []) if float(x["size"]) > 0}
        elif e == "price_change":
            for c in m.get("price_changes", []):
                b = self.book(c["asset_id"])
                side = b.bids if c["side"] == "BUY" else b.asks
                px, sz = float(c["price"]), float(c["size"])
                if sz <= 0:
                    side.pop(px, None)
                else:
                    side[px] = sz
        elif e == "market_resolved":
            self.winners[m["market"]] = m.get("winning_asset_id")

    def run(self, on_event: Callable[["Engine", dict, int], None], messages=None):
        for m in messages if messages is not None else iter_messages():
            ts = int(m["timestamp"])
            self._execute_due(ts)          # orders due before this update see the old book
            self._apply(m)
            self.now = ts
            on_event(self, m, ts + self.one_way)  # the strategy sees it one-way later
        self._execute_due(10**15)
        return self
