"""COURTSIDE decision rule (engine/strategy.py): edge formula, token choice, skips, risk, paper guard."""
import pytest

from engine.execution.paper import Ledger, LiveTradingForbidden, PaperExecutor
from engine.market.clob import ReplayClobFeed
from engine.risk.limits import RiskConfig, RiskManager
from engine.strategy import CourtsideStrategy, StrategyConfig, assert_paper_only, enable_live_trading
from engine.vision.events import CallEvent as VisionCall
from src.markov import State
from src.paper import taker_fee

A, B, MK = "tokA", "tokB", "0xm"


def snap(asset, ts, bids, asks):
    return {"event_type": "book", "asset_id": asset, "market": MK, "timestamp": str(ts),
            "bids": [{"price": str(p), "size": str(s)} for p, s in bids],
            "asks": [{"price": str(p), "size": str(s)} for p, s in asks]}


def pc(ts, *changes):
    return {"event_type": "price_change", "market": MK, "timestamp": str(ts),
            "price_changes": [{"asset_id": a, "price": str(p), "size": str(s), "side": side}
                              for a, p, s, side in changes]}


def miss(direction, frame=100):
    return VisionCall(call="MISS", frame=frame, t_frame=0.0, t_emit=0.0, p_miss=0.99, lead_ms=100.0,
                      direction=direction)


def setup(msgs, state=State(0, 0, 4, 4, 2, 2), cfg=None, risk=True):
    feed = ReplayClobFeed(messages=msgs, one_way_ms=67)
    rk = RiskManager(RiskConfig(require_vision=True), feed=feed) if risk else None
    led = Ledger(cash=10_000)
    ex = PaperExecutor(feed, one_way_ms=67, risk=rk, ledger=led)
    st = CourtsideStrategy(feed, ex, rk, cfg or StrategyConfig())
    return feed, ex, rk, st, state


def book_msgs():
    return [snap(A, 1000, [(0.48, 300)], [(0.50, 300), (0.51, 500)]),
            snap(B, 1000, [(0.50, 300)], [(0.52, 300), (0.53, 500)]),
            pc(2000, (A, 0.48, 310, "BUY")),
            pc(4000, (A, 0.50, 0, "SELL"), (A, 0.60, 50, "SELL"), (A, 0.58, 200, "BUY"),    # reprice toward A
               (B, 0.50, 0, "BUY"), (B, 0.52, 0, "SELL"), (B, 0.40, 50, "BUY"), (B, 0.42, 200, "SELL")),
            pc(9000, (A, 0.58, 210, "BUY"))]


def run_with_call(call, at_ms=2500, state=State(0, 0, 4, 4, 2, 2), cfg=None, left=0):
    feed, ex, rk, st, state = setup(book_msgs(), state, cfg)
    out = {}

    def hook(ts):
        if "d" not in out and ts + 67 > at_ms:
            if "m" not in st.matches:
                st.add_match("m", A, B, state=state, tour="wta", left_player=left, now_ms=at_ms)
            out["d"] = st.on_call("m", call, t_ms=at_ms)
    feed.on_clock(hook)
    feed.run_sync()
    ex.flush()
    return out["d"], ex, st


def test_miss_buys_the_winner_token_at_stale_ask_plus_tick():
    # direction +1: ball travels left -> right, hitter = left player (A, left=0) -> B wins
    d, ex, _ = run_with_call(miss(+1), left=1)        # left player is B -> hitter B -> A wins
    assert d.winner == 0 and d.token == A and d.action == "SEND"
    assert d.ask == 0.50 and d.limit == pytest.approx(0.51)
    # edge = E[move] - half spread - 1 tick - fee(limit)
    assert d.edge == pytest.approx(d.expected_move - d.half_spread - 0.01 - taker_fee(0.51))
    # E[move] = (c - p_w) * leverage
    assert d.expected_move == pytest.approx((d.confidence - d.p_point_winner) * d.leverage, abs=1e-9)
    o = ex.orders[0]
    assert o.t_decision == 2500 and o.t_exec == 2500 + 67 + 1000
    assert ex.fills and ex.fills[0].price <= 0.51
    assert d.shares <= 100 + 1e-9                     # v2 net cap


def test_miss_other_direction_buys_b():
    d, ex, _ = run_with_call(miss(+1), left=0)        # hitter A -> B wins -> buy B
    assert d.winner == 1 and d.token == B and d.ask == 0.52 and d.limit == pytest.approx(0.53)


def test_bounce_is_not_traded():
    c = VisionCall(call="BOUNCE", frame=1, t_frame=0, t_emit=0, p_miss=0.1, lead_ms=40, direction=1)
    d, ex, _ = run_with_call(c)
    assert d.action == "SKIP" and d.reason == "no_point_decision" and not ex.orders


def test_low_leverage_point_is_skipped():
    # first point of the match: ~3.7c swing, E[move] ~1.7c < half spread + tick + fee
    d, ex, _ = run_with_call(miss(+1), state=State(), left=1)
    assert d.action == "SKIP" and d.reason == "edge_below_cost" and not ex.orders
    assert d.leverage < 0.05 and d.edge < 0


def test_call_after_reprice_is_skipped():
    # calibrated between points (2500), call arrives after the book repriced toward A (4000)
    feed, ex, rk, st, state = setup(book_msgs())
    out = {}

    def hook(ts):
        if "cal" not in out and ts + 67 > 2500:
            st.add_match("m", A, B, state=state, tour="wta", left_player=1, now_ms=2500)
            out["cal"] = True
        if "d" not in out and ts + 67 > 6000:
            out["d"] = st.on_call("m", miss(+1), t_ms=6000)
    feed.on_clock(hook)
    feed.run_sync()
    assert out["d"].action == "SKIP" and out["d"].reason == "book_already_repriced"


def test_stale_call_is_skipped():
    c = miss(+1)
    c.t_emit = 1.5                                    # emitted 1.5 s after its frame (a backed-up engine)
    d, ex, _ = run_with_call(c, left=1)
    assert d.action == "SKIP" and d.reason == "stale_call" and not ex.orders


def test_call_against_the_repriced_book_is_skipped():
    # the book repriced toward A at 4000; a late call naming B must not buy B at the new price
    feed, ex, rk, st, state = setup(book_msgs())
    out = {}

    def hook(ts):
        if "cal" not in out and ts + 67 > 2500:
            st.add_match("m", A, B, state=state, tour="wta", left_player=0, now_ms=2500)
            out["cal"] = True
        if "d" not in out and ts + 67 > 6000:
            out["d"] = st.on_call("m", miss(+1), t_ms=6000)
    feed.on_clock(hook)
    feed.run_sync()
    assert out["d"].winner == 1 and out["d"].reason == "book_moved_against_call" and not ex.orders


def test_risk_kill_rejects_without_vision_heartbeat_age():
    feed, ex, rk, st, state = setup(book_msgs())
    st.add_match("m", A, B, state=state, tour="wta", left_player=1, calibrate=False)
    feed.run_sync(limit=2)
    st.calibrate("m", now_ms=1100)
    rk.vision_heartbeat(0)                  # vision silent for 1.1 s before the call ...
    d = st.evaluate("m", miss(+1), t_ms=1100, approve=True)
    assert d.action == "REJECTED" and "vision_stale" in d.reason
    d2 = st.on_call("m", miss(+1), t_ms=1100)   # ... but a call itself is a heartbeat
    assert d2.action == "SEND"


def test_paper_only_guards(monkeypatch):
    with pytest.raises(LiveTradingForbidden):
        enable_live_trading()
    feed = ReplayClobFeed(messages=[])
    with pytest.raises(LiveTradingForbidden):
        CourtsideStrategy(feed, live=True)
    with pytest.raises(LiveTradingForbidden):
        CourtsideStrategy(feed, private_key="0xabc")
    with pytest.raises(LiveTradingForbidden):
        CourtsideStrategy(feed, executor=object())
    monkeypatch.setenv("COURTSIDE_LIVE_TRADING", "1")
    with pytest.raises(LiveTradingForbidden):
        assert_paper_only()
    with pytest.raises(LiveTradingForbidden):
        CourtsideStrategy(feed)


def test_strategy_module_has_no_order_endpoints():
    import engine.strategy as S
    import engine.run as R
    for mod in (S, R):
        src = open(mod.__file__).read().lower()
        for bad in ("post_order", "create_order", "py_clob_client", "clob.polymarket.com/order", "/order\"",
                    "sign_order", "private_key ="):
            assert bad not in src, (mod.__name__, bad)
