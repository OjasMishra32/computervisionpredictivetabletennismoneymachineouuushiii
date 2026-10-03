"""Book reconstruction, replay ordering/timing and the live client's reconnect (engine/market)."""
import asyncio
import gzip
import json
from pathlib import Path

import pytest

from engine.market.book import L2Book, LatencyTracker
from engine.market.clob import (BaseFeed, LiveClobFeed, ReadOnlyViolation, ReplayClobFeed, iter_recorded,
                                load_token_meta)
from src.paper import Book

ROOT = Path(__file__).resolve().parents[1]
A, B, MK = "tokA", "tokB", "0xmarket"


class Feed(BaseFeed):
    def __init__(self):
        super().__init__()
        self.t = 0

    def now_ms(self):
        return self.t


def snap(asset, ts, bids, asks):
    return {"event_type": "book", "asset_id": asset, "market": MK, "timestamp": str(ts),
            "bids": [{"price": str(p), "size": str(s)} for p, s in bids],
            "asks": [{"price": str(p), "size": str(s)} for p, s in asks], "tick_size": "0.01"}


def pc(ts, *changes):
    return {"event_type": "price_change", "market": MK, "timestamp": str(ts),
            "price_changes": [{"asset_id": a, "price": str(p), "size": str(s), "side": side}
                              for a, p, s, side in changes]}


# ------------------------------------------------------------------------------ L2Book
def test_book_top_cache_depth_and_sweep():
    b = L2Book("x", bids=[(0.40, 100), (0.39, 50)], asks=[(0.42, 50), (0.43, 100), (0.45, 10)])
    assert isinstance(b, Book)        # reuses src.paper.Book (walk etc.)
    assert (b.best_bid(), b.best_ask()) == (0.40, 0.42) and b.mid() == pytest.approx(0.41)
    b.set_level("SELL", 0.41, 5)      # better ask appears
    assert b.best_ask() == 0.41
    b.set_level("SELL", 0.41, 0)      # and is removed -> cache recomputed
    assert b.best_ask() == 0.42
    b.set_level("BUY", 0.40, 0)
    assert b.best_bid() == 0.39
    assert b.depth("ask") == (160, pytest.approx(0.42 * 50 + 0.43 * 100 + 0.45 * 10))
    assert b.depth("ask", within=0.01)[0] == 150
    assert b.depth("bid", n_levels=1) == (50, pytest.approx(19.5))
    assert b.available("BUY", 0.43) == 150
    # per-level sweep == src.paper walk, and respects our own consumed liquidity
    lv = b.sweep("BUY", 120, 0.45)
    got, vwap = b.walk("BUY", 120, 0.45)
    assert lv == [(0.42, 50), (0.43, 70)]
    assert got == 120 and vwap == pytest.approx(sum(p * s for p, s in lv) / 120)
    assert b.sweep("BUY", 120, 0.45, consumed={0.42: 50, 0.43: 60}) == [(0.43, 40), (0.45, 10)]
    assert b.sweep("SELL", 500, 0.39) == [(0.39, 50)]
    assert b.sweep("BUY", 10, 0.41) == []


def test_latency_tracker():
    lt = LatencyTracker(window=1000, recent=5)
    for i in range(100):
        lt.add(1000 * i, 1000 * i + 67 + (i % 10))
    assert lt.p50() == 71 and lt.p95() == 76 and lt.n == 100
    for _ in range(5):
        lt.add(0, 900)
    assert lt.recent() == 900 and lt.last == 900
    assert lt.p95() == 76            # the burst does not raise its own baseline


# ------------------------------------------------------------------------------ BaseFeed.handle
def test_handle_snapshot_deltas_events_and_hooks():
    f = Feed()
    ticks = []
    f.on_clock(ticks.append)
    evs = []
    f.on(evs.append)
    f._dispatch_sync(f.handle(snap(A, 1000, [(0.40, 100)], [(0.42, 50), (0.43, 100)]), 1067))
    f._dispatch_sync(f.handle(pc(1500, (A, 0.42, 0, "SELL"), (A, 0.41, 30, "BUY"), (B, 0.58, 30, "SELL")), 1567))
    b = f.book(A)
    assert b.asks == {0.43: 100.0} and b.bids == {0.40: 100.0, 0.41: 30.0}
    assert (b.best_bid(), b.best_ask()) == (0.41, 0.43)
    assert b.ts_server == 1500 and b.ts_local == 1567 and b.market == MK
    assert f.book(B).asks == {0.58: 30.0} and not f.book(B).has_snapshot
    assert ticks == [1000, 1500]                       # clock hooks see each venue stamp first
    assert [e.kind for e in evs] == ["book", "price_change", "price_change", "price_change"]
    assert evs[1].best_ask == 0.43 and evs[2].best_bid == 0.41   # top of book after each change
    assert f.latency.last == 67 and f.last_server_ms == 1500
    # trade + resolution
    f.handle({"event_type": "last_trade_price", "asset_id": A, "market": MK, "timestamp": "1600",
              "price": "0.43", "size": "10", "side": "BUY"}, 1667)
    assert f.book(A).last_trade == (0.43, 10.0, "BUY", 1600)
    f.handle({"event_type": "market_resolved", "market": MK, "timestamp": "9000", "winning_asset_id": A}, 9067)
    assert f.resolved[MK] == A
    # a later full snapshot that agrees with our reconstruction is not a desync ...
    f.handle(snap(A, 2000, [(0.41, 30), (0.40, 100)], [(0.43, 100)]), 2067)
    assert (f.snap_checked, f.snap_mismatch) == (1, 0)
    # ... one that disagrees is counted, and replaces the book
    f.handle(snap(A, 3000, [(0.30, 1)], [(0.70, 1)]), 3067)
    assert (f.snap_checked, f.snap_mismatch) == (2, 1) and f.book(A).best_bid() == 0.30


def test_non_book_messages_ignored():
    f = Feed()
    assert f.handle({"event_type": "new_market", "timestamp": "1"}, 1) == []
    assert f.handle({"foo": 1}, 1) == [] and f.n_msgs == 0


# ------------------------------------------------------------------------------ replay
def _write(path, rows, gz=False):
    op = gzip.open if gz else open
    with op(path, "wt") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_replay_merges_dedups_reorders_and_times(tmp_path):
    m1 = {"rt": 1067, **snap(A, 1000, [(0.40, 100)], [(0.42, 50)])}
    m2 = {"rt": 1700, **pc(1600, (A, 0.42, 0, "SELL"))}
    m3 = {"rt": 1690, **pc(1500, (A, 0.43, 70, "SELL"))}   # stamped earlier, arrived earlier... in file 2
    m4 = {"rt": 2100, **pc(2000, (B, 0.10, 5, "BUY"))}
    _write(tmp_path / "market_1.jsonl", [m1, m2, m4, {"rt": 2200, "error": "x"}, "garbage"])
    _write(tmp_path / "market_2.jsonl.gz", [m1, m3, m2], gz=True)    # overlapping recording
    data = lambda ms: [int(m["timestamp"]) for m in ms if m["event_type"] != "_gap"]
    msgs = list(iter_recorded(str(tmp_path / "market_*")))
    assert data(msgs) == [1000, 1500, 1600, 2000]                 # arrival order, deduped
    # gaps: end of file 2 (rt 1700), the recorder's error line (rt 2200), end of file 1
    assert [int(m["timestamp"]) for m in msgs if m["event_type"] == "_gap"] == [1701, 2200, 2201]
    assert data(iter_recorded(str(tmp_path / "market_*"), by="server")) == [1000, 1500, 1600, 2000]
    assert data(iter_recorded(str(tmp_path / "market_*"), assets=[A])) == [1000, 1500, 1600]

    seen = []
    feed = ReplayClobFeed(str(tmp_path / "market_*"), one_way_ms=67)
    feed.on(lambda ev: ev.kind != "gap" and seen.append((ev.ts_server, ev.ts_local, feed.now_ms())))
    feed.run_sync()
    assert seen[0] == (1000, 1067, 1067) and seen[-1] == (2000, 2067, 2067)
    assert feed.book(A).asks == {0.43: 70.0}

    rec = ReplayClobFeed(str(tmp_path / "market_*"), clock="recorded")
    loc = []
    rec.on(lambda ev: ev.kind != "gap" and loc.append(ev.ts_local))
    rec.run_sync()
    assert loc == [1067, 1690, 1700, 2100]          # our recorded arrival times
    assert rec.latency.summary()["n"] == 3     # snapshots excluded from the delay stats


def test_replay_original_timing_async():
    msgs = [snap(A, 1000, [(0.4, 1)], [(0.6, 1)]), pc(1200, (A, 0.5, 1, "BUY")), pc(1400, (A, 0.5, 0, "BUY"))]
    feed = ReplayClobFeed(messages=msgs, speed=1.0)
    loop_t = []

    async def go():
        feed.on(lambda ev: loop_t.append(asyncio.get_running_loop().time()))
        await feed.run()

    asyncio.run(go())
    assert loop_t[-1] - loop_t[0] == pytest.approx(0.4, abs=0.08)   # 400 ms of recorded time


REC = sorted(ROOT.glob("data/live/market_*.jsonl"))


@pytest.mark.skipif(not REC, reason="no plain-text live recording in data/live")
def test_reconstruction_matches_venue_snapshots_on_recorded_data():
    """Every full `book` snapshot the venue sends must equal the book we rebuilt from deltas."""
    feed = ReplayClobFeed(str(REC[0])).run_sync(limit=80_000)
    s = feed.summary()
    assert s["snapshots_checked"] > 50
    assert s["snapshots_mismatched"] == 0
    assert s["top_disagreements"] / max(1, s["top_checked"]) < 0.01


def test_token_meta_outcome_index(tmp_path):
    rows = [{"rt": 1, "tokens": {"t0": {"slug": "atp-x", "outcome": "Sinner", "cond": "c1"},
                                 "t1": {"slug": "atp-x", "outcome": "Alcaraz", "cond": "c1"}}}]
    _write(tmp_path / "tokens_1.jsonl", rows)
    meta = load_token_meta(str(tmp_path / "tokens_*"))
    assert meta["t0"]["outcome_index"] == 0 and meta["t1"]["outcome_index"] == 1
    assert meta["t0"]["other"] == "t1"


# ------------------------------------------------------------------------------ live client
def test_live_feed_is_read_only():
    for bad in ("wss://ws-subscriptions-clob.polymarket.com/ws/user", "https://clob.polymarket.com/order",
                "ws://evil.example/ws/market"):
        with pytest.raises(ReadOnlyViolation):
            LiveClobFeed([A], url=bad)
    LiveClobFeed([A])   # the public market channel is fine


def test_live_feed_reconnects_and_resubscribes():
    websockets = pytest.importorskip("websockets")
    subs = []

    async def scenario():
        conn_no = {"n": 0}

        async def handler(ws):
            conn_no["n"] += 1
            subs.append(json.loads(await ws.recv()))
            await ws.send(json.dumps([snap(A, 1000 * conn_no["n"], [(0.40, 10)], [(0.46 if conn_no["n"] == 1 else 0.47, 5)])]))
            if conn_no["n"] == 1:
                await ws.close()            # server drops us: client must come back
                return
            await ws.send(json.dumps(pc(5000, (A, 0.41, 7, "BUY"))))
            await ws.wait_closed()

        async with websockets.serve(handler, "127.0.0.1", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            feed = LiveClobFeed([A], url=f"ws://127.0.0.1:{port}/ws/market", ping_s=0.2)
            task = asyncio.create_task(feed.run(seconds=3))
            for _ in range(300):
                await asyncio.sleep(0.01)
                if feed.book(A).best_bid() == 0.41:
                    break
            feed.stop()
            await task
            return feed

    feed = asyncio.run(scenario())
    assert feed.n_connects >= 2
    assert len(subs) >= 2 and all(s["assets_ids"] == [A] and s["type"] == "market" for s in subs)
    assert all(s.get("custom_feature_enabled") is True for s in subs)
    b = feed.book(A)
    assert b.has_snapshot and b.best_ask() == 0.47 and b.best_bid() == 0.41   # second session's book
    assert feed.latency.n >= 1          # deltas only; snapshot stamps are not delays


def test_recording_holes_invalidate_books_and_stale_snapshots_are_skipped(tmp_path):
    rows = [{"rt": 1067, **snap(A, 1000, [(0.40, 100)], [(0.42, 50)])},
            {"rt": 1567, **pc(1500, (A, 0.41, 10, "BUY"))},
            {"rt": 2000, "error": "ConnectionClosedError(None, None, None)"},   # recorder lost the socket
            {"rt": 9067, **snap(A, 9000, [(0.30, 5)], [(0.70, 5)])},           # fresh snapshot on reconnect
            {"rt": 9100, **snap(A, 8990, [(0.10, 5)], [(0.90, 5)])}]           # generated before the last one
    _write(tmp_path / "market_x.jsonl", rows)
    feed = ReplayClobFeed(str(tmp_path / "market_*"))
    kinds, valid = [], []
    feed.on(lambda ev: (kinds.append(ev.kind), valid.append(feed.book(A).has_snapshot)))
    feed.run_sync()
    assert kinds == ["book", "price_change", "gap", "book", "gap"]       # last gap = end of recording
    assert valid == [True, True, False, True, False]
    s = feed.summary()
    assert s["gaps"] == 2 and s["snapshots_checked"] == 0 and s["stale_snapshots_skipped"] == 1
    assert feed.book(A).best_bid() == 0.30
