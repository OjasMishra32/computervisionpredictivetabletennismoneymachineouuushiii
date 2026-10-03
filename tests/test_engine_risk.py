"""Risk caps, daily stop and kill switches (engine/risk)."""
import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.market.book import LatencyTracker
from engine.risk.limits import (V2_K, V2_MAX_ORDER_USD, V2_NET_CAP_SHARES, V2_ZONE, RiskConfig, RiskManager,
                                risk_parity_shares)

ROOT = Path(__file__).resolve().parents[1]
A, B, M = "tokA", "tokB", "match1"


class FakeFeed:
    def __init__(self):
        self.t = 0
        self.last = 0
        self.latency = LatencyTracker()

    def now_ms(self):
        return self.t

    def stale_ms(self, now=None):
        return (self.t if now is None else now) - self.last


class O:   # minimal order record
    def __init__(self, id, token, side, shares):
        self.id, self.token, self.side, self.shares = id, token, side, shares


def rm(**cfg):
    feed = FakeFeed()
    r = RiskManager(RiskConfig(**{"require_vision": False, **cfg}), feed=feed)
    r.register_market(M, A, B)
    return r, feed


def fill(r, i, token, side, shares):
    o = O(i, token, side, shares)
    r.on_submit(o)
    r.on_result(o, shares)


def test_v2_constants_match_frozen_rule():
    src = (ROOT / "src/v2.py").read_text()
    pol = re.search(r"POLICY = E\.Policy\((.*?)\)\n", src, re.S).group(1)
    assert 'sizing="risk_parity"' in pol and "deploy_frac=0.5" in pol
    assert f"net_cap={int(V2_NET_CAP_SHARES)}" in pol
    assert f'zone="{V2_ZONE[0]}-{V2_ZONE[1]}"' in pol
    # load the sizing engine under a private name (the module is called `engine`, like our package)
    spec = importlib.util.spec_from_file_location("_v2_sizing_engine", ROOT / "research/v2/sizing/engine.py")
    E = importlib.util.module_from_spec(spec)
    sys.modules["_v2_sizing_engine"] = E
    try:
        spec.loader.exec_module(E)
        assert E.BASE_USD_CAP == V2_MAX_ORDER_USD
        df = pd.DataFrame({"q": [0.1, 0.5, 0.8]})
        raw = E.raw_cap(df, E.Policy("x", sizing="risk_parity"), None, "5pct", None, None)
        ours = [risk_parity_shares(q, k=1.0, usd_cap=1e12) for q in df.q]
        assert np.allclose(raw, ours)
    finally:
        sys.modules.pop("_v2_sizing_engine", None)


def test_risk_parity_size():
    assert risk_parity_shares(0.5) == pytest.approx(V2_K * 2000)
    assert risk_parity_shares(0.5, k=1.0) == pytest.approx(2000)          # $1k cap at q = 0.5
    assert risk_parity_shares(0.9, k=1.0) == pytest.approx(1000 / 0.9)    # usd cap binds
    assert risk_parity_shares(0.5, visible=37) == 37
    assert risk_parity_shares(0.0) == 0


def test_order_usd_cap():
    r, _ = rm(net_cap_shares=1e9)
    ap = r.approve(A, "BUY", 3000, 0.5)
    assert ap.ok and ap.shares == pytest.approx(2000) and "usd_cap" in ap.reason
    ap = r.approve(A, "BUY", 100, 0.5)
    assert ap.ok and ap.shares == 100 and ap.reason == ""


def test_net_cap_and_risk_reducing():
    r, _ = rm()
    fill(r, 1, A, "BUY", 80)
    ap = r.approve(A, "BUY", 50, 0.5)
    assert ap.ok and ap.shares == 20 and "net_cap" in ap.reason
    fill(r, 2, A, "BUY", 20)
    assert not r.approve(A, "BUY", 10, 0.5).ok                     # at +100
    # buying the other token is risk-reducing: allowed up to the cap on the other side
    ap = r.approve(B, "BUY", 150, 0.5)
    assert ap.ok and ap.reducing and ap.shares == 150
    ap = r.approve(B, "BUY", 500, 0.5)
    assert ap.shares == 200                                         # 100 + 100
    # selling what we hold is reducing too
    ap = r.approve(A, "SELL", 30, 0.5)
    assert ap.ok and ap.reducing and ap.shares == 30


def test_in_flight_orders_are_reserved():
    r, _ = rm()
    o1 = O(1, A, "BUY", 70)
    r.on_submit(o1)
    ap = r.approve(A, "BUY", 70, 0.5)
    assert ap.shares == 30
    r.on_result(o1, 0.0)                                            # missed: reservation released
    assert r.approve(A, "BUY", 70, 0.5).shares == 70 and r.exposure(M) == 0


def test_no_naked_shorts():
    r, _ = rm()
    assert r.approve(A, "SELL", 10, 0.5).reason == "no_inventory"
    fill(r, 1, A, "BUY", 10)
    assert r.approve(A, "SELL", 25, 0.5).shares == 10


def test_zone_and_fee_aware_filter():
    r, _ = rm()
    assert r.approve(A, "BUY", 10, 0.97).reason == "zone"
    assert r.approve(A, "BUY", 10, 0.03).reason == "zone"
    # fee at 0.58 = 0.05*0.58*0.42 = 1.218c
    assert r.approve(A, "BUY", 10, 0.58, fair=0.60).ok                 # 2c gross > 1.2c fee
    assert r.approve(A, "BUY", 10, 0.58, fair=0.59).reason == "edge_below_fee"
    assert r.approve(B, "SELL", 10, 0.58, fair=0.56).reason == "no_inventory"
    r2, _ = rm(require_fair=True)
    assert r2.approve(A, "BUY", 10, 0.5).reason == "no_fair_value"
    # risk-reducing orders skip zone/edge filters (always allowed)
    fill(r, 1, A, "BUY", 50)
    ap = r.approve(B, "BUY", 20, 0.97)
    assert ap.ok and ap.reducing
    assert r.approve(A, "BUY", 2, 0.5).reason == "below_min"


def test_unknown_token_and_bad_orders():
    r, _ = rm()
    assert r.approve("zzz", "BUY", 10, 0.5).reason == "unknown_token"
    assert r.approve(A, "BUY", 10, 1.2).reason == "bad_order"
    assert r.approve(A, "HOLD", 10, 0.5).reason == "bad_order"


def test_feed_stale_kill_switch():
    r, feed = rm()
    feed.t, feed.last = 10_000, 8_500
    assert r.approve(A, "BUY", 10, 0.5).ok                         # 1.5 s: fine
    feed.t = 10_600                                                 # 2.1 s without data
    ap = r.approve(A, "BUY", 10, 0.5)
    assert not ap.ok and "feed_stale" in ap.reason
    fill(r, 1, A, "BUY", 40)
    assert r.approve(A, "SELL", 10, 0.5).ok                         # reducing still allowed
    feed.last = 10_600
    assert r.approve(A, "BUY", 10, 0.5).ok                          # clears when data resumes
    assert [k for _, k, _ in r.log] == ["kill_on", "kill_off"]


def test_vision_stale_kill_switch():
    r, feed = rm(require_vision=True)
    feed.t = feed.last = 5_000
    assert "vision_stale" in r.approve(A, "BUY", 10, 0.5).reason   # never heard from vision
    r.vision_heartbeat(4_500)
    assert r.approve(A, "BUY", 10, 0.5).ok
    feed.t = feed.last = 5_600
    assert "vision_stale" in r.approve(A, "BUY", 10, 0.5).reason   # 1.1 s silent


def test_latency_kill_switch():
    r, feed = rm()
    feed.t = feed.last = 1
    for i in range(300):
        feed.latency.add(0, 67 + i % 20)                            # p95 ~ 85 ms, floor 150 ms
    assert r.approve(A, "BUY", 10, 0.5).ok
    for _ in range(25):
        feed.latency.add(0, 900)                                    # recent median 900 ms
    assert "latency" in r.approve(A, "BUY", 10, 0.5).reason
    r2, f2 = rm(latency_limit_ms=1000)
    f2.latency = feed.latency
    f2.t = f2.last = 1
    assert r2.approve(A, "BUY", 10, 0.5).ok                          # explicit threshold


def test_daily_stop_latches_until_next_utc_day():
    eq = {"v": 10_000.0}
    feed = FakeFeed()
    r = RiskManager(RiskConfig(require_vision=False, daily_stop_usd=1000), feed=feed, equity_fn=lambda: eq["v"])
    r.register_market(M, A, B)
    day = 86_400_000
    feed.t = feed.last = 3 * day + 1000
    assert r.approve(A, "BUY", 10, 0.5).ok                          # day opens at 10,000
    eq["v"] = 8_900.0
    feed.t = feed.last = 3 * day + 5000
    ap = r.approve(A, "BUY", 10, 0.5)
    assert not ap.ok and "daily_stop" in ap.reason
    eq["v"] = 9_500.0                                               # recovers: still stopped today
    assert "daily_stop" in r.approve(A, "BUY", 10, 0.5).reason
    fill(r, 1, A, "BUY", 20)
    assert r.approve(A, "SELL", 20, 0.5).ok                         # flattening is allowed
    feed.t = feed.last = 4 * day + 10
    assert r.approve(A, "BUY", 10, 0.5).ok                          # new UTC day


def test_manual_kill_halts_everything():
    r, _ = rm()
    fill(r, 1, A, "BUY", 40)
    r.kill("manual", "operator")
    assert "manual" in r.approve(A, "SELL", 10, 0.5).reason          # even reducing
    r.clear("manual")
    assert r.approve(A, "SELL", 10, 0.5).ok
