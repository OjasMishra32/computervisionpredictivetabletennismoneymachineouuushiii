"""Paper execution: delay/latency fill timing, fee math, partial fills, guards (engine/execution)."""
import asyncio
import sys
import types

import pytest

import engine.execution.paper as P
from engine.execution.paper import (Decision, Ledger, LiveTradingForbidden, PaperExecutor, assert_paper,
                                    fee_for_levels)
from engine.market.clob import BaseFeed, ReplayClobFeed
from engine.risk.limits import RiskConfig, RiskManager
from src.paper import Engine, taker_fee

A, B, MK = "tokA", "tokB", "0xm"


def snap(asset, ts, bids, asks):
    return {"event_type": "book", "asset_id": asset, "market": MK, "timestamp": str(ts),
            "bids": [{"price": str(p), "size": str(s)} for p, s in bids],
            "asks": [{"price": str(p), "size": str(s)} for p, s in asks]}


def pc(ts, *changes):
    return {"event_type": "price_change", "market": MK, "timestamp": str(ts),
            "price_changes": [{"asset_id": a, "price": str(p), "size": str(s), "side": side}
                              for a, p, s, side in changes]}


def timeline():
    return [
        snap(A, 1000, [(0.40, 100)], [(0.42, 50), (0.43, 100), (0.44, 500)]),
        pc(1500, (A, 0.42, 0, "SELL")),        # stale 0.42 offer gone 0.5 s after the signal
        pc(2100, (A, 0.43, 40, "SELL")),       # 0.43 thinned before Florida's order lands (2134)
        pc(2134, (A, 0.43, 0, "SELL")),        # stamped exactly at t_exec: applied AFTER the fill
        pc(3000, (A, 0.41, 10, "BUY")),
    ]


def run(one_way, shares=80, limit=0.43, tif="FAK", msgs=None):
    feed = ReplayClobFeed(messages=msgs or timeline(), one_way_ms=one_way)
    ex = PaperExecutor(feed, one_way_ms=one_way, tif=tif)
    sent = []

    def strat(ev):
        if ev.kind == "book" and not sent:
            sent.append(ex.submit(Decision(A, "BUY", shares, limit, tag={"why": "test"})))

    feed.on(strat)
    feed.run_sync()
    ex.flush()
    return ex, sent[0]


def test_florida_timing_fills_against_book_at_t_exec():
    ex, o = run(67)
    assert (o.t_decision, o.t_arrive, o.t_exec) == (1067, 1134, 2134)
    f = ex.fills[0]
    # at 2134 the 0.42 level is gone and 0.43 holds 40 (the 2134 removal is not yet applied)
    assert f.t_exec == 2134 and f.book_ts == 2100
    assert f.levels == [(0.43, 40.0)] and f.shares == 40 and o.status == "partial"
    assert f.fee == pytest.approx(0.05 * 0.43 * 0.57 * 40)


def test_london_timing():
    ex, o = run(2)
    assert (o.t_decision, o.t_exec) == (1002, 2004)
    f = ex.fills[0]                                 # lands before the 2100 thinning
    assert f.levels == [(0.43, 80.0)] and f.price == 0.43 and o.status == "filled"


def test_zero_latency_and_delay_sees_the_stale_offer():
    feed = ReplayClobFeed(messages=timeline(), one_way_ms=0)
    ex = PaperExecutor(feed, one_way_ms=0, venue_delay_ms=0)
    feed.on(lambda ev: ev.kind == "book" and not ex.orders and ex.submit(Decision(A, "BUY", 80, 0.43)))
    feed.run_sync()
    assert ex.fills[0].levels == [(0.42, 50.0), (0.43, 30.0)]


def test_matches_research_engine():
    """Same orders through src.paper.Engine and the event-driven executor give the same fill."""
    msgs = timeline()
    sent = []

    def strat(eng, m, t_seen):
        if m["event_type"] == "book" and not sent:
            eng.send(t_seen, A, "BUY", 80, 0.44, {})
            sent.append(1)

    ref = Engine(one_way_ms=67, delay_ms=1000).run(strat, msgs).fills[0]
    ex, _ = run(67, shares=80, limit=0.44)
    f = ex.fills[0]
    assert (f.t_exec, f.shares) == (ref.t_exec, ref.shares) and f.price == pytest.approx(ref.price)
    # fee: the research engine charges the fee at the VWAP; we charge it per level (exact)
    assert f.fee == pytest.approx(fee_for_levels(f.levels))
    assert abs(f.fee - ref.fee) < 0.01


def test_limit_fok_and_misses():
    ex, o = run(67, shares=80, limit=0.42)          # nothing left at <= 0.42 at t_exec
    assert not ex.fills and o.status == "missed" and o.reason == "no_liquidity_in_limit"
    ex, o = run(67, shares=80, limit=0.43, tif="FOK")   # only 40 available -> all-or-nothing misses
    assert not ex.fills and o.reason == "fok_short"


def test_fee_math():
    for q in (0.05, 0.3, 0.5, 0.77, 0.95):
        assert fee_for_levels([(q, 1)]) == pytest.approx(0.05 * q * (1 - q)) == pytest.approx(taker_fee(q))
    assert fee_for_levels([(0.5, 100)]) == pytest.approx(1.25)            # max 1.25c/share at 50c
    lv = [(0.42, 50), (0.43, 30)]
    assert fee_for_levels(lv, 0.05) == pytest.approx(0.05 * (0.42 * 0.58 * 50 + 0.43 * 0.57 * 30))
    assert fee_for_levels(lv, 0.0) == 0


def test_own_fills_consume_liquidity():
    msgs = [snap(A, 1000, [(0.40, 100)], [(0.42, 100), (0.45, 1000)]), pc(5000, (A, 0.30, 1, "BUY"))]
    feed = ReplayClobFeed(messages=msgs, one_way_ms=67)
    ex = PaperExecutor(feed, one_way_ms=67)
    feed.on(lambda ev: ev.kind == "book" and [ex.submit(Decision(A, "BUY", 70, 0.42)) for _ in range(2)])
    feed.run_sync()
    assert [f.shares for f in ex.fills] == [70, 30]     # the same 100 shares cannot be taken twice


def test_ledger_and_settlement():
    msgs = [snap(A, 1000, [(0.40, 100)], [(0.42, 100)]), snap(B, 1000, [(0.57, 100)], [(0.60, 100)]),
            pc(3000, (A, 0.41, 5, "BUY")),
            {"event_type": "market_resolved", "market": MK, "timestamp": "9000", "winning_asset_id": A}]
    feed = ReplayClobFeed(messages=msgs)
    ex = PaperExecutor(feed, ledger=Ledger(cash=100.0))
    ex.register_market(MK, [A, B])
    feed.on(lambda ev: ev.kind == "book" and ev.asset_id == A and ex.submit(Decision(A, "BUY", 50, 0.42)))
    feed.run_sync()
    f = ex.fills[0]
    assert f.cash_flow == pytest.approx(-(50 * 0.42 + taker_fee(0.42) * 50))
    assert ex.ledger.pos == {} and ex.ledger.settled[A] == 1.0
    assert ex.ledger.cash == pytest.approx(100 + f.cash_flow + 50)      # paid $1 per winning share
    assert ex.ledger.pnl() == pytest.approx(50 * (1 - 0.42) - f.fee)


def test_risk_reservations_cover_in_flight_orders():
    msgs = [snap(A, 1000, [(0.40, 1000)], [(0.42, 1000)]), pc(5000, (A, 0.30, 1, "BUY"))]
    feed = ReplayClobFeed(messages=msgs)
    risk = RiskManager(RiskConfig(require_vision=False), feed=feed)
    risk.register_market(MK, A, B)
    ex = PaperExecutor(feed, risk=risk)
    orders = []
    feed.on(lambda ev: ev.kind == "book" and orders.extend(ex.submit(Decision(A, "BUY", 60, 0.45)) for _ in range(3)))
    feed.run_sync()
    assert [o.shares for o in orders] == [60, 40, 0]        # 100-share net cap incl. in-flight orders
    assert orders[2].status == "rejected" and orders[2].reason == "net_cap"
    assert sum(f.shares for f in ex.fills) == 100 and risk.net[MK] == 100 and not risk.pending


def test_live_timer_fills_on_a_quiet_feed():
    class QuietFeed(BaseFeed):
        def __init__(self):
            super().__init__()
            self.t = 0

        def now_ms(self):
            return self.t

    feed = QuietFeed()
    feed.handle(snap(A, 1000, [(0.40, 100)], [(0.42, 100)]), 1067)
    feed.handle(pc(1050, (A, 0.39, 5, "BUY")), 1117)      # one delta: feed delay sample = 67 ms
    feed.t = 1117
    ex = PaperExecutor(feed, one_way_ms=67)
    o = ex.submit(Decision(A, "BUY", 10, 0.42))
    assert o.t_exec == 2184

    async def go():
        task = asyncio.create_task(ex.run_timer(poll_ms=5))
        await asyncio.sleep(0.03)
        assert not ex.fills                       # not due yet
        feed.t = 2184 + 66
        await asyncio.sleep(0.03)
        assert not ex.fills                       # a message stamped <= t_exec could still arrive
        feed.t = 2184 + 67                        # local clock passes t_exec + p95 feed delay
        await asyncio.sleep(0.03)
        task.cancel()

    asyncio.run(go())
    assert ex.fills and ex.fills[0].t_exec == 2184 and ex.fills[0].price == pytest.approx(0.42)


# ------------------------------------------------------------------------------ guards
def test_paper_only_guards(monkeypatch):
    with pytest.raises(LiveTradingForbidden):
        PaperExecutor(live=True)
    for kw in ("private_key", "api_secret", "passphrase", "funder", "wallet_key"):
        with pytest.raises(LiveTradingForbidden):
            PaperExecutor(**{kw: "0xdeadbeef"})
    with pytest.raises(TypeError):
        PaperExecutor(foo=1)
    PaperExecutor(live=False)                     # explicit paper is fine
    assert_paper()
    monkeypatch.setenv("COURTSIDE_LIVE_TRADING", "1")
    with pytest.raises(LiveTradingForbidden):
        PaperExecutor()
    monkeypatch.delenv("COURTSIDE_LIVE_TRADING")
    monkeypatch.setitem(sys.modules, "py_clob_client", types.ModuleType("py_clob_client"))
    with pytest.raises(LiveTradingForbidden):
        PaperExecutor()


def test_submit_rechecks_paper_flag(monkeypatch):
    ex = PaperExecutor(ReplayClobFeed(messages=[]))
    monkeypatch.setattr(P, "PAPER_ONLY", False)
    with pytest.raises(LiveTradingForbidden):
        ex.submit(Decision(A, "BUY", 1, 0.5))


def test_no_network_or_signing_code_in_execution():
    src = open(P.__file__).read()
    for banned in ("import requests", "import websockets", "aiohttp", "httpx", "urllib", "py_clob_client.client",
                   "/order", "sign_order", "create_order", "post_order"):
        assert banned not in src.replace('SIGNING_MODULES = ("py_clob_client"', "")


def test_call_to_fill_end_to_end():
    """vision call -> fair jump -> fee-aware risk check -> paper fill 1,067 ms later (Florida)."""
    from engine.fair.value import CallEvent, MatchFair
    from src.markov import State

    msgs = [snap(A, 1000, [(0.48, 500)], [(0.50, 300), (0.51, 300)]),
            snap(B, 1000, [(0.50, 500)], [(0.52, 300)]),
            pc(1800, (A, 0.50, 120, "SELL")),            # someone else lifts part of the stale offer
            pc(2500, (A, 0.50, 0, "SELL"), (A, 0.55, 300, "SELL"))]   # full reprice after our fill
    feed = ReplayClobFeed(messages=msgs, one_way_ms=67)
    risk = RiskManager(RiskConfig(require_vision=True), feed=feed)
    risk.register_market(MK, A, B)
    ex = PaperExecutor(feed, one_way_ms=67, risk=risk)
    ex.register_market(MK, [A, B])
    # break point at 4-4 in the decider, A serving; model calibrated to the market mid (0.49)
    mf = MatchFair.from_price(0.49, "atp", state=State(1, 1, 4, 4, 2, 3, 0), p_server0=1.0, token_a=A, token_b=B)
    mf.prime()

    def on_book(ev):
        if ev.kind == "book" and ev.asset_id == B:        # both books are up: the call lands now
            now = feed.now_ms()
            risk.vision_heartbeat(now)
            j = mf.on_call(CallEvent(winner=0, confidence=0.97, t_ms=now))
            fair_a = j.expected_token(0)
            assert fair_a > 0.5 + 0.05 * 0.5 * 0.5        # the jump beats the stale ask + fee
            ex.submit(Decision(A, "BUY", 150, 0.51, match_id=MK, fair=fair_a))

    feed.on(on_book)
    feed.run_sync()
    ex.flush()
    (f,) = ex.fills
    o = ex.orders[0]
    assert o.requested == 150 and o.shares == 100 and o.reason == "net_cap"   # v2 cap: 100 net shares
    assert f.t_exec == 1067 + 67 + 1000
    assert f.levels == [(0.50, 100.0)]          # 120 of the stale 0.50 offer were still there at 2134
    assert risk.net[MK] == 100 and ex.ledger.pos[A] == 100


def test_orders_due_inside_a_feed_gap_miss():
    msgs = [snap(A, 1000, [(0.40, 100)], [(0.42, 100)]),
            {"event_type": "_gap", "timestamp": "1500", "error": "socket closed"},
            snap(A, 2600, [(0.40, 100)], [(0.42, 100)])]
    feed = ReplayClobFeed(messages=msgs)
    ex = PaperExecutor(feed)
    feed.on(lambda ev: ev.kind == "book" and not ex.orders and ex.submit(Decision(A, "BUY", 10, 0.42)))
    feed.run_sync()
    assert not ex.fills and ex.misses[0].reason == "no_book"     # t_exec 2134 falls in the hole
