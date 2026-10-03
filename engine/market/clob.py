"""Polymarket CLOB market-data feeds: live websocket and recorded replay, one interface.

Both feeds keep full L2 books per token (book snapshots + price_change deltas), expose best
bid/ask/mid/depth, track server-vs-local latency, and push `MarketEvent`s to listeners. Book
reconstruction is the same code (`BaseFeed.handle`) in both, so a backtest exercises exactly
the path the live engine runs.

PUBLIC MARKET DATA ONLY. The live feed connects to the unauthenticated `market` channel; it
never opens the `user` channel, never sends credentials, and has no order code. Anything that
tries to point it elsewhere raises `ReadOnlyViolation`.

Clocks
  ts_server  the venue's ms stamp on the message
  ts_local   live: our wall-clock receive time; replay: ts_server + one_way_ms (default 67 ms,
             Gainesville -> Miami edge), so a strategy "sees" a message one-way after the venue
             stamped it, exactly like src.paper.Engine (or the recorded receive time, clock=
             "recorded").
Feed delay (local - server) is tracked on deltas only; snapshots sent on (re)subscribe carry old
stamps. Measured live from this laptop on 2026-10-03: p50 58 ms, p95 102 ms, p99 134 ms.
Clock hooks (`on_clock`) run with ts_server BEFORE a message is applied. The paper executor uses
this to fill an order due at server time t against the book as it stood at t.

Read-only live feed (prints top of book and latency):
    python -m engine.market.clob live --auto --seconds 60
    python -m engine.market.clob live --assets <token_id> <token_id> --seconds 30
Replay (as fast as possible with --speed 0, original timing with --speed 1):
    python -m engine.market.clob replay --files 'data/live/market_20261003_1501.jsonl'
    python -m engine.market.clob replay --files 'data/live/market_*' --start-ms 1791040000000 --minutes 10 --speed 1
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import gzip
import heapq
import inspect
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

try:  # ~3x faster parsing on the hot path; plain json works too
    import orjson as _orjson

    def _loads(s):
        return _orjson.loads(s)
except Exception:  # pragma: no cover
    _orjson = None

    def _loads(s):
        return json.loads(s)

from engine.market.book import ASK, BID, L2Book, LatencyTracker
from src.paper import FLORIDA_MS, LONDON_MS

MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
LATENCY_PRESETS = {"florida": FLORIDA_MS, "london": LONDON_MS}   # Gainesville->Miami edge / co-located
BOOK_EVENTS = ("book", "price_change", "best_bid_ask", "last_trade_price", "tick_size_change",
               "market_resolved")
GAP = "_gap"   # synthetic: connection lost / hole in a recording


class ReadOnlyViolation(RuntimeError):
    """Raised if the market-data client is asked to do anything but read public data."""


def _assert_public_market_url(url: str) -> None:
    """Only the unauthenticated market channel (or a local test server serving that path)."""
    local = url.startswith(("ws://127.0.0.1", "ws://localhost"))
    if not (url.startswith("wss://") or local) or not url.rstrip("/").endswith("/ws/market"):
        raise ReadOnlyViolation(f"only the public market channel is allowed, got {url!r}")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(slots=True)
class MarketEvent:
    kind: str            # book | price_change | best_bid_ask | trade | tick_size | resolved | gap
    asset_id: str
    market: str
    ts_server: int
    ts_local: int
    price: float | None = None    # level price (price_change), trade price (trade)
    size: float | None = None     # new level size (price_change), trade size (trade)
    side: str | None = None       # BUY/SELL level side (price_change) or taker side (trade)
    best_bid: float | None = None  # top of book AFTER the event (our reconstruction)
    best_ask: float | None = None
    raw: dict | None = field(default=None, repr=False)


Listener = Callable[[MarketEvent], Any]


def load_token_meta(pattern: str = "data/live/tokens_*.jsonl*") -> dict[str, dict]:
    """token_id -> {slug, gameId, tag, outcome, cond, outcome_index} from recorder metadata.
    outcome_index is the token's position in the market's clobTokenIds (0 = outcome 0)."""
    meta: dict[str, dict] = {}
    for f in sorted(glob.glob(pattern)):
        op = gzip.open if f.endswith(".gz") else open
        try:
            with op(f, "rt") as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    for tok, m in (d.get("tokens") or {}).items():
                        meta.setdefault(tok, dict(m))
        except (OSError, EOFError):
            continue
    by_cond: dict[str, list[str]] = {}
    for tok, m in meta.items():   # insertion order = clobTokenIds order within a market
        by_cond.setdefault(m.get("cond", ""), []).append(tok)
    for toks in by_cond.values():
        for i, t in enumerate(toks):
            meta[t]["outcome_index"] = i
            meta[t]["other"] = toks[1 - i] if len(toks) == 2 else None
    return meta


# ======================================================================================
class BaseFeed:
    """Book state + event fan-out common to the live and replay feeds."""

    def __init__(self, validate: bool = True):
        self.books: dict[str, L2Book] = {}
        self.latency = LatencyTracker()
        self.listeners: list[Listener] = []
        self.clock_hooks: list[Callable[[int], None]] = []
        self.market_of: dict[str, str] = {}       # asset -> condition id
        self.resolved: dict[str, str] = {}        # condition id -> winning asset
        self.last_server_ms = 0
        self.last_local_ms = 0                    # last message of any kind (incl. PONG)
        self.n_msgs = 0
        self.n_events = 0
        self.validate = validate
        self.n_checked = 0
        self.mismatches: dict[str, int] = {}      # asset -> per-change top-of-book disagreements
        self.snap_checked = 0                     # snapshots compared with our reconstruction
        self.snap_mismatch = 0                    # ... that differed (true desync)
        self.n_gaps = 0                           # disconnects / recording holes
        self.n_stale_snapshots = 0                # snapshots older than applied deltas (skipped)
        self._queues: list[asyncio.Queue] = []

    # clock -------------------------------------------------------------------------------
    def now_ms(self) -> int:  # pragma: no cover - overridden
        raise NotImplementedError

    def stale_ms(self, now: int | None = None) -> int:
        """ms since the feed last delivered anything (inf-like if never)."""
        if not self.last_local_ms:
            return 10**12
        return (self.now_ms() if now is None else now) - self.last_local_ms

    # book access -------------------------------------------------------------------------
    def book(self, asset: str) -> L2Book:
        b = self.books.get(asset)
        if b is None:
            b = self.books[asset] = L2Book(asset)
        return b

    def best_bid(self, asset: str):
        return self.book(asset).best_bid()

    def best_ask(self, asset: str):
        return self.book(asset).best_ask()

    def mid(self, asset: str):
        return self.book(asset).mid()

    def depth(self, asset: str, side: str, within: float | None = None, n_levels: int | None = None):
        return self.book(asset).depth(side, within, n_levels)

    # subscriptions -----------------------------------------------------------------------
    def on(self, fn: Listener) -> Listener:
        """Register fn(MarketEvent); may be a coroutine function. Returns fn (decorator use)."""
        self.listeners.append(fn)
        return fn

    def on_clock(self, fn: Callable[[int], None]) -> None:
        """fn(ts_server) runs before each message is applied (used to fill due paper orders)."""
        self.clock_hooks.append(fn)

    async def events(self, maxsize: int = 100_000):
        """Async iterator over events (alternative to callbacks)."""
        q: asyncio.Queue = asyncio.Queue(maxsize)
        self._queues.append(q)
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    return
                yield ev
        finally:
            self._queues.remove(q)

    # core: one venue message -> book updates + events ---------------------------------
    def handle(self, m: dict, ts_local: int) -> list[MarketEvent]:
        e = m.get("event_type")
        if e == GAP:
            return self._gap(int(m.get("timestamp") or 0), ts_local, m.get("error", ""))
        if e not in BOOK_EVENTS:
            return []
        try:
            ts = int(m.get("timestamp") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts:
            for h in self.clock_hooks:
                h(ts)
            if e != "book":   # snapshots sent on (re)subscribe carry old stamps: not a delay
                self.latency.add(ts, ts_local)
            self.last_server_ms = max(self.last_server_ms, ts)
        self.last_local_ms = max(self.last_local_ms, ts_local)
        self.n_msgs += 1
        mk = m.get("market", "")
        out: list[MarketEvent] = []
        if e == "price_change":
            for c in m.get("price_changes") or ():
                a = c["asset_id"]
                b = self.book(a)
                px, sz = float(c["price"]), float(c["size"])
                b.set_level(BID if c["side"] == BID else ASK, px, sz, ts, ts_local)
                if mk:
                    b.market = mk
                    self.market_of[a] = mk
                bb, ba = b.best_bid(), b.best_ask()
                if self.validate and b.has_snapshot and "best_bid" in c:
                    self._check(a, bb, ba, c.get("best_bid"), c.get("best_ask"))
                out.append(MarketEvent("price_change", a, mk, ts, ts_local, px, sz, c["side"], bb, ba, m))
        elif e == "book":
            a = m["asset_id"]
            b = self.book(a)
            if b.has_snapshot and ts and ts < b.ts_server:
                self.n_stale_snapshots += 1   # generated before deltas we already applied
                return out
            if self.validate and b.has_snapshot:
                self._check_snapshot(a, b, m)
            b.snapshot(m.get("bids") or (), m.get("asks") or (), ts, ts_local)
            if m.get("tick_size"):
                b.tick_size = float(m["tick_size"])
            b.market = mk
            self.market_of[a] = mk
            out.append(MarketEvent("book", a, mk, ts, ts_local, None, None, None, b.best_bid(), b.best_ask(), m))
        elif e == "best_bid_ask":
            a = m["asset_id"]
            b = self.book(a)
            bb, ba = b.best_bid(), b.best_ask()   # best_bid_ask can arrive before its deltas: no check
            out.append(MarketEvent("best_bid_ask", a, mk, ts, ts_local, None, None, None, bb, ba, m))
        elif e == "last_trade_price":
            a = m["asset_id"]
            b = self.book(a)
            px, sz = float(m.get("price") or 0), float(m.get("size") or 0)
            b.last_trade = (px, sz, m.get("side"), ts)
            out.append(MarketEvent("trade", a, mk, ts, ts_local, px, sz, m.get("side"),
                                   b.best_bid(), b.best_ask(), m))
        elif e == "tick_size_change":
            a = m["asset_id"]
            self.book(a).tick_size = float(m.get("new_tick_size") or 0.01)
            out.append(MarketEvent("tick_size", a, mk, ts, ts_local, raw=m))
        elif e == "market_resolved":
            win = m.get("winning_asset_id") or ""
            self.resolved[mk] = win
            out.append(MarketEvent("resolved", win, mk, ts, ts_local, raw=m))
        self.n_events += len(out)
        return out

    def _gap(self, ts: int, ts_local: int, why: str = "") -> list[MarketEvent]:
        """The connection dropped (live) or the recording has a hole (replay): every book is
        unknown until the venue re-sends its snapshot. Orders due before the gap still fill
        against the old book; orders due during it miss ("no_book")."""
        if ts:
            for h in self.clock_hooks:
                h(ts)
        for b in self.books.values():
            b.has_snapshot = False
        self.n_gaps += 1
        return [MarketEvent("gap", "", "", ts, ts_local, raw={"error": why})]

    def _check_snapshot(self, a: str, b: L2Book, m: dict) -> None:
        """Strong desync test: our reconstructed book vs the venue's next full snapshot."""
        self.snap_checked += 1
        sb = {float(x["price"]): float(x["size"]) for x in m.get("bids") or () if float(x["size"]) > 0}
        sa = {float(x["price"]): float(x["size"]) for x in m.get("asks") or () if float(x["size"]) > 0}
        if sb != b.bids or sa != b.asks:
            self.snap_mismatch += 1

    def _check(self, a: str, bb, ba, vb, va) -> None:
        """Compare our top of book with the venue's per-change best_bid/best_ask fields
        (custom_feature_enabled). Informational: ~0.2% disagree transiently on recorded data
        even though every full snapshot matches our book exactly."""
        self.n_checked += 1
        try:
            vb = float(vb) if vb not in (None, "", "0") else None
            va = float(va) if va not in (None, "", "0", "1") else None
        except (TypeError, ValueError):
            return
        ours_b = bb if bb is not None else None
        ours_a = ba if ba is not None else None
        if (vb is not None and (ours_b is None or abs(ours_b - vb) > 1e-9)) or \
           (va is not None and (ours_a is None or abs(ours_a - va) > 1e-9)):
            self.mismatches[a] = self.mismatches.get(a, 0) + 1

    async def _dispatch(self, evs: list[MarketEvent]) -> None:
        for ev in evs:
            for fn in self.listeners:
                r = fn(ev)
                if inspect.isawaitable(r):
                    await r
            for q in self._queues:
                if not q.full():
                    q.put_nowait(ev)

    def _dispatch_sync(self, evs: list[MarketEvent]) -> None:
        for ev in evs:
            for fn in self.listeners:
                fn(ev)

    def _close_queues(self) -> None:
        for q in self._queues:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    def summary(self) -> dict:
        return {"msgs": self.n_msgs, "events": self.n_events, "assets": len(self.books),
                "latency": self.latency.summary(), "snapshots_checked": self.snap_checked,
                "snapshots_mismatched": self.snap_mismatch, "stale_snapshots_skipped": self.n_stale_snapshots,
                "gaps": self.n_gaps, "top_checked": self.n_checked,
                "top_disagreements": sum(self.mismatches.values())}


# ======================================================================================
class LiveClobFeed(BaseFeed):
    """Async websocket client for the public market channel. Auto-reconnects with backoff;
    every (re)connect re-subscribes all assets and waits for fresh snapshots."""

    def __init__(self, assets: Iterable[str] = (), url: str = MARKET_WS, ping_s: float = 10.0,
                 auto_discover: bool = False, discover_every_s: float = 600.0, window_h: float = 6.0,
                 compression: str | None = "deflate", validate: bool = True):
        super().__init__(validate)
        _assert_public_market_url(url)
        self.url = url
        self.assets: set[str] = set(assets)
        self.meta: dict[str, dict] = {}
        self.ping_s = ping_s
        self.auto_discover = auto_discover
        self.discover_every_s = discover_every_s
        self.window_h = window_h
        self.compression = compression
        self.connected = False
        self.n_connects = 0
        self.errors: deque = deque(maxlen=100)
        self.last_pong_ms = 0
        self._ws = None
        self._stop = asyncio.Event()

    def now_ms(self) -> int:
        return now_ms()

    async def subscribe(self, assets: Iterable[str]) -> list[str]:
        new = [a for a in assets if a not in self.assets]
        self.assets.update(new)
        if new and self._ws is not None and self.connected:
            await self._ws.send(json.dumps({"assets_ids": new, "type": "market", "operation": "subscribe",
                                            "custom_feature_enabled": True}))
        return new

    def stop(self) -> None:
        """Stop run(); closes the socket so a pending recv wakes up immediately."""
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                asyncio.get_running_loop().create_task(ws.close())
            except RuntimeError:   # no running loop: run() will notice the flag within 5 s
                pass

    async def _pinger(self, ws) -> None:
        while True:
            await asyncio.sleep(self.ping_s)
            await ws.send("PING")

    async def _discoverer(self) -> None:
        from src.live_recorder import live_markets  # public Gamma API, no keys
        while True:
            try:
                mk = await asyncio.to_thread(live_markets, self.window_h)
                self.meta.update(mk)
                await self.subscribe(list(mk))
            except Exception as ex:  # discovery failures must not kill the feed
                self.errors.append((now_ms(), f"discover: {ex!r}"))
            await asyncio.sleep(self.discover_every_s)

    async def run(self, seconds: float | None = None) -> None:
        import websockets

        stop_at = time.time() + seconds if seconds else None
        disc = asyncio.create_task(self._discoverer()) if self.auto_discover else None
        backoff = 0.5
        try:
            while not self._stop.is_set() and (stop_at is None or time.time() < stop_at):
                pinger = None
                try:
                    async with websockets.connect(self.url, ping_interval=None, max_size=None,
                                                  compression=self.compression, open_timeout=10) as ws:
                        self._ws, self.connected = ws, True
                        self.n_connects += 1
                        backoff = 0.5
                        for b in self.books.values():   # fresh snapshots come after subscribing
                            b.has_snapshot = False
                        if self.assets:
                            await ws.send(json.dumps({"assets_ids": sorted(self.assets), "type": "market",
                                                      "custom_feature_enabled": True}))
                        pinger = asyncio.create_task(self._pinger(ws))
                        while not self._stop.is_set():
                            timeout = 5.0 if stop_at is None else max(0.01, min(5.0, stop_at - time.time()))
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                            except asyncio.TimeoutError:
                                if stop_at is not None and time.time() >= stop_at:
                                    break
                                continue
                            t = now_ms()
                            self.last_local_ms = t
                            if raw == "PONG":
                                self.last_pong_ms = t
                                continue
                            try:
                                d = _loads(raw)
                            except ValueError:
                                continue
                            for m in d if isinstance(d, list) else (d,):
                                if isinstance(m, dict) and m.get("event_type") != "new_market":
                                    evs = self.handle(m, t)
                                    if evs:
                                        await self._dispatch(evs)
                except asyncio.CancelledError:
                    raise
                except Exception as ex:   # drop, DNS, 5xx, timeout: back off and reconnect
                    if self._stop.is_set():
                        break
                    self.errors.append((now_ms(), repr(ex)))
                    t = now_ms()
                    await self._dispatch(self.handle({"event_type": GAP, "timestamp": t, "error": repr(ex)}, t))
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                finally:
                    self.connected = False
                    self._ws = None
                    if pinger:
                        pinger.cancel()
        finally:
            if disc:
                disc.cancel()
            self._close_queues()


# ======================================================================================
def _rt_prefix(line: str) -> int | None:
    """Fast path: the recorder writes {"rt":<ms>, ...} first; read it without a JSON parse."""
    if line.startswith('{"rt":'):
        j = line.find(",", 6)
        try:
            return int(line[6:j])
        except ValueError:
            return None
    return None


def _file_stream(path: str, needles: tuple[str, ...], start_ms: int | None, end_ms: int | None,
                 reorder_ms: int, by: str = "arrival") -> Iterator[tuple[int, int, dict]]:
    """(key_ms, seq, msg) from one recording. by="server": re-sorted by the server stamp within
    reorder_ms; by="arrival": file order, keyed by our recorded receive time `rt`."""
    op = gzip.open if path.endswith(".gz") else open
    heap: list = []
    seq = 0
    hi = 0
    last_key = 0
    lo_rt = (start_ms - 60_000) if start_ms else None
    hi_rt = (end_ms + 60_000) if end_ms else None
    try:
        with op(path, "rt") as fh:
            for line in fh:
                rt = _rt_prefix(line)
                if rt is not None:
                    if lo_rt is not None and rt < lo_rt:
                        continue
                    if hi_rt is not None and rt > hi_rt:
                        break
                if needles and '"error"' not in line[:40] and not any(n in line for n in needles):
                    continue
                try:
                    m = _loads(line)
                except ValueError:
                    continue
                if not isinstance(m, dict):
                    continue
                if "error" in m and m.get("rt"):   # src.live_recorder: any error = the socket closed
                    m = {"event_type": GAP, "timestamp": str(m["rt"]), "rt": m["rt"], "error": m["error"]}
                ts = m.get("timestamp")
                if ts is None or (m.get("event_type") not in BOOK_EVENTS and m.get("event_type") != GAP):
                    continue
                ts = int(ts)
                if (start_ms and ts < start_ms) or (end_ms and ts > end_ms):
                    continue
                seq += 1
                if by == "arrival":
                    last_key = int(m.get("rt") or ts)
                    yield (last_key, seq, m)
                    continue
                heapq.heappush(heap, (ts, seq, m))
                hi = last_key = max(hi, ts)
                while heap and heap[0][0] <= hi - reorder_ms:
                    yield heapq.heappop(heap)
    except (EOFError, OSError, gzip.BadGzipFile):   # truncated .gz from a live recorder
        pass
    while heap:
        yield heapq.heappop(heap)
    if seq and not (end_ms and last_key >= end_ms):   # the recording stops: nothing is known after it
        yield (last_key + 1, seq + 1, {"event_type": GAP, "timestamp": str(last_key + 1), "error": f"end of {path}"})


def iter_recorded(files: str | Iterable[str] = "data/live/market_*", assets: Iterable[str] | None = None,
                  markets: Iterable[str] | None = None, start_ms: int | None = None,
                  end_ms: int | None = None, reorder_ms: int = 3000, by: str = "arrival") -> Iterator[dict]:
    """Recorded CLOB messages merged across files and de-duplicated, in the order they arrived
    (by="arrival", the venue's own sequencing) or re-sorted by server stamp within reorder_ms
    (by="server", src.paper's order). Streaming, bounded memory (src.paper.iter_messages loads
    everything into RAM). On today's 1.02M-message recording the rebuilt books disagree with
    the venue's next snapshot 0 times in arrival order and 4-18 times in server order: stamps
    are not a perfect sequence."""
    paths = sorted(glob.glob(files)) if isinstance(files, str) else sorted(files)
    needles = tuple(assets or ()) + tuple(markets or ())
    streams = [_file_stream(p, needles, start_ms, end_ms, reorder_ms, by) for p in paths]
    aset = set(assets) if assets is not None else None
    recent: deque = deque()
    seen: set = set()
    for _, _, m in heapq.merge(*streams, key=lambda r: (r[0], r[1])):
        ts = int(m["timestamp"])
        while recent and recent[0][0] < ts - 10_000:
            seen.discard(recent.popleft()[1])
        key = (ts, m.get("event_type"), m.get("asset_id"),
               m.get("hash") or str(m.get("price_changes"))[:160])
        if key in seen:
            continue
        seen.add(key)
        recent.append((ts, key))
        if aset is not None and m.get("event_type") == "price_change":
            pcs = [c for c in m.get("price_changes") or () if c.get("asset_id") in aset]
            if not pcs:
                continue
            m = {**m, "price_changes": pcs}
        elif aset is not None and m.get("asset_id") and m.get("asset_id") not in aset \
                and m.get("event_type") != "market_resolved":
            continue
        yield m


class ReplayClobFeed(BaseFeed):
    """Replays recorded market_* files through the same book code as the live feed.

    speed = 0  : as fast as possible (virtual clock; backtests)
    speed = 1  : original timing (sleeps to keep the recorded inter-message gaps)
    speed = k  : k x real time
    order = "arrival"  : messages in the order the recorder received them (default; exact books)
    order = "server"   : re-sorted by venue stamp within reorder_ms (src.paper.Engine's order)
    clock = "model"    : ts_local = ts_server + one_way_ms (deterministic)
    clock = "recorded" : ts_local = the recorded receive time `rt`, so the strategy also suffers
                         the real feed-delay tail of that session
    Recorder error lines (socket closed) become "gap" events: books are invalid until the venue
    re-sends snapshots, and paper orders due inside the hole miss instead of filling stale."""

    def __init__(self, files: str | Iterable[str] = "data/live/market_*", assets: Iterable[str] | None = None,
                 markets: Iterable[str] | None = None, start_ms: int | None = None, end_ms: int | None = None,
                 speed: float = 0.0, one_way_ms: int = FLORIDA_MS, reorder_ms: int = 3000,
                 messages: Iterable[dict] | None = None, validate: bool = True, clock: str = "model",
                 order: str = "arrival"):
        super().__init__(validate)
        if clock not in ("model", "recorded") or order not in ("arrival", "server"):
            raise ValueError((clock, order))
        self.order = order
        self.files, self.start_ms, self.end_ms = files, start_ms, end_ms
        self.assets = list(assets) if assets is not None else None
        self.markets = list(markets) if markets is not None else None
        self.speed, self.one_way_ms, self.reorder_ms = speed, one_way_ms, reorder_ms
        self.clock = clock
        self._messages = messages
        self._clock = 0
        self.done = False

    def now_ms(self) -> int:
        return self._clock

    def advance(self, t_ms: int) -> None:
        """Move the virtual clock forward (e.g. an external event stream merged into the replay)."""
        self._clock = max(self._clock, int(t_ms))

    def messages(self) -> Iterator[dict]:
        if self._messages is not None:
            return iter(self._messages)
        return iter_recorded(self.files, self.assets, self.markets, self.start_ms, self.end_ms, self.reorder_ms,
                             self.order)

    def _local(self, m: dict) -> int:
        if self.clock == "recorded" and m.get("rt"):
            return int(m["rt"])
        return int(m.get("timestamp") or 0) + self.one_way_ms

    def _step(self, m: dict) -> list[MarketEvent]:
        t_local = self._local(m)
        self._clock = max(self._clock, t_local)
        return self.handle(m, t_local)

    def run_sync(self, limit: int | None = None) -> "ReplayClobFeed":
        """Fastest path for backtests: no event loop, listeners must be plain functions."""
        for i, m in enumerate(self.messages()):
            if limit is not None and i >= limit:
                break
            evs = self._step(m)
            if evs:
                self._dispatch_sync(evs)
        self.done = True
        return self

    async def run(self, limit: int | None = None) -> None:
        wall0 = t0 = None
        for i, m in enumerate(self.messages()):
            if limit is not None and i >= limit:
                break
            ts = self._local(m)
            if self.speed > 0:
                if t0 is None:
                    t0, wall0 = ts, time.monotonic()
                wait = wall0 + (ts - t0) / 1000.0 / self.speed - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
            elif i % 2000 == 0:
                await asyncio.sleep(0)   # let other tasks (strategy, vision replay) run
            evs = self._step(m)
            if evs:
                await self._dispatch(evs)
        self.done = True
        self._close_queues()


# ======================================================================================
def _fmt_book(feed: BaseFeed, a: str, meta: dict) -> str:
    b = feed.book(a)
    name = (meta.get(a) or {}).get("outcome", a[:10])
    slug = (meta.get(a) or {}).get("slug", "")
    bd, _ = b.depth("bid", within=0.0)
    ad, _ = b.depth("ask", within=0.0)
    return f"{slug[:34]:34s} {name[:18]:18s} {b.best_bid()!s:>5} x {bd:>8.0f} | {b.best_ask()!s:<5} x {ad:<8.0f}"


async def _cli_live(args) -> None:
    feed = LiveClobFeed(args.assets or (), auto_discover=args.auto)
    meta = load_token_meta()

    async def report():
        while True:
            await asyncio.sleep(args.every)
            feed.meta and meta.update(feed.meta)
            s = feed.summary()
            print(f"\n[{time.strftime('%H:%M:%S')}] connected={feed.connected} reconnects={feed.n_connects - 1} "
                  f"msgs={s['msgs']} assets={s['assets']} stale={feed.stale_ms()} ms "
                  f"latency p50/p95/recent={s['latency']['p50_ms']}/{s['latency']['p95_ms']}/"
                  f"{s['latency']['recent_ms']} ms snapshot desync={s['snapshots_mismatched']}/"
                  f"{s['snapshots_checked']}")
            active = sorted(feed.books, key=lambda a: -feed.books[a].n_updates)[: args.top]
            for a in active:
                print("  " + _fmt_book(feed, a, meta))

    rep = asyncio.create_task(report())
    try:
        await feed.run(seconds=args.seconds)
    finally:
        rep.cancel()
    print(json.dumps(feed.summary(), indent=1))
    if feed.errors:
        print("errors:", list(feed.errors)[-5:])


def _cli_replay(args) -> None:
    start = int(args.start_ms) if args.start_ms else None
    end = start + int(args.minutes * 60_000) if (start and args.minutes) else None
    feed = ReplayClobFeed(args.files, assets=args.assets or None, start_ms=start, end_ms=end, speed=args.speed,
                          clock=args.clock, order=args.order)
    t = time.perf_counter()
    if args.speed > 0:
        asyncio.run(feed.run(limit=args.limit))
    else:
        feed.run_sync(limit=args.limit)
    dt = time.perf_counter() - t
    s = feed.summary()
    print(json.dumps(s, indent=1))
    print(f"replayed {s['msgs']} messages in {dt:.1f} s ({s['msgs'] / max(dt, 1e-9):,.0f} msg/s)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Polymarket CLOB market data (read-only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lv = sub.add_parser("live", help="connect to the public market websocket (read-only)")
    lv.add_argument("--assets", nargs="*", default=[])
    lv.add_argument("--auto", action="store_true", help="discover live tennis moneyline tokens via Gamma")
    lv.add_argument("--seconds", type=float, default=60)
    lv.add_argument("--every", type=float, default=10)
    lv.add_argument("--top", type=int, default=8)
    rp = sub.add_parser("replay", help="replay recorded market_* files")
    rp.add_argument("--files", default="data/live/market_*")
    rp.add_argument("--assets", nargs="*", default=[])
    rp.add_argument("--start-ms", default=None)
    rp.add_argument("--minutes", type=float, default=None)
    rp.add_argument("--limit", type=int, default=None)
    rp.add_argument("--speed", type=float, default=0.0)
    rp.add_argument("--clock", choices=("model", "recorded"), default="model")
    rp.add_argument("--order", choices=("arrival", "server"), default="arrival")
    args = ap.parse_args(argv)
    if args.cmd == "live":
        if not args.assets and not args.auto:
            ap.error("give --assets or --auto")
        asyncio.run(_cli_live(args))
    else:
        _cli_replay(args)


if __name__ == "__main__":
    main()
