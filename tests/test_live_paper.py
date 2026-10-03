"""Unit tests for scripts/live_paper.py: the maker v1 signal and the paper fill engine.

Every message below is a hand-written test fixture, never market data.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research" / "v2" / "crossmarket"))

import model  # noqa: E402
from scripts import live_paper as lp  # noqa: E402
from src.tiers import _mid_series  # noqa: E402

L = lp.L_FLOOR_MS


# ------------------------------------------------------------------ frozen pieces
def test_frozen_files_and_table():
    lp.check_frozen()
    assert lp.B_T_SHA256.startswith("f40c53f7")


def test_mid_proxy_matches_tiers():
    rng = np.random.default_rng(1)
    for stale in (30, 120):
        ts = np.sort(rng.integers(0, 2000, 300)).astype(float)
        p = rng.uniform(0.05, 0.95, 300).round(2)
        a = rng.random(300) < 0.5
        want, _ = _mid_series(ts, p, a, stale=stale)
        P = lp.Prints(stale * 1000)
        for t, q, x in zip(ts, p, a):
            P.add(int(t * 1000), float(q), bool(x), 1.0)
        assert np.allclose(P.mid, want)
        # out-of-order insert recomputes to the same answer
        P2 = lp.Prints(stale * 1000)
        order = list(range(300))
        order[10], order[200] = order[200], order[10]
        for i in order:
            P2.add(int(ts[i] * 1000), float(p[i]), bool(a[i]), 1.0)
        assert np.allclose(P2.mid, want)


def test_scalar_model_matches_frozen_model():
    rng = np.random.default_rng(2)
    rows = []
    for _ in range(400):
        smt = rng.choice(list(lp.B_T))
        al = int(rng.choice([-1, 0, 1]))
        q, p1, p2 = rng.uniform(0.01, 0.99, 3)
        b = float(lp.B_T[smt])
        want = float(model.implied_q0(np.array([q]), np.array([p1]), np.array([p2]), np.array([smt]),
                                      np.array([al]), np.array([b]))[0])
        assert abs(lp.implied_q0(q, p1, p2, smt, al, b) - want) < 1e-12
        m1, m2 = rng.uniform(0.0, 1.0, 2)
        rows.append({"smt": smt, "align0": al, "m1": m1, "m2": m2, "p1": p1, "p2": p2})
    iv = pd.DataFrame(rows)
    x, y = model.xy(iv)
    for i, r in iv.iterrows():
        got = lp.xy(r.smt, r.align0, r.m1, r.m2, r.p1, r.p2)
        if np.isfinite(x[i]):
            assert got is not None and abs(got[0] - x[i]) < 1e-12 and abs(got[1] - y[i]) < 1e-12
        else:
            assert got is None


# ------------------------------------------------------------------ fixture market
def engine(variants=lp.VARIANTS):
    eng = lp.Engine(variants=variants, align_fn=lambda *a: 1)
    E = {"ev": {"title": "Test Open: A vs B", "series": "atp", "start_ms": 0, "end_ms": None}}
    M = {"ML": {"eid": "ev", "smt": "moneyline", "toks": ["m0", "m1"], "outs": ["A", "B"], "delay_ms": 1000,
                "fee_rate": 0.05, "rebate_rate": 0.15, "tick": 0.01, "min_size": 5, "closed": False},
         "S": {"eid": "ev", "smt": "tennis_first_set_winner", "toks": ["s0", "s1"], "outs": ["A", "B"],
               "delay_ms": 1000, "fee_rate": 0.05, "rebate_rate": 0.15, "tick": 0.01, "min_size": 5, "closed": False}}
    eng.push(1, "meta", {"events": E, "markets": M})
    eng.push(2, "start", {})
    return eng


def ws(eng, e, ev, key=None):
    eng.push(key if key is not None else e + L, "ws", ev)


def book(tok, bids, asks):
    return ("book", None, tok, bids, asks)


def setup_signal(eng):
    """Moneyline 0.50 -> 0.70 after one side print at 0.45: the implied first-set move is about +30c (bid s0)."""
    ws(eng, 100, ("book", 100, "s0", [(0.40, 100.0)], [(0.50, 100.0)]))
    ws(eng, 100, ("book", 100, "s1", [(0.50, 100.0)], [(0.60, 100.0)]))
    ws(eng, 500, ("trade", 500, "m0", 0.50, 10.0, "BUY"))
    ws(eng, 1000, ("trade", 1000, "s0", 0.45, 10.0, "BUY"))
    ws(eng, 3000, ("trade", 3000, "m0", 0.70, 10.0, "BUY"))


def fills(eng, name):
    return eng.ledgers[name].fills


def test_signal_value_and_timing():
    eng = engine()
    setup_signal(eng)
    eng.run()
    sig = eng.signal("S", 3001, 3001, "lag")
    b = lp.B_T["tennis_first_set_winner"]
    want = lp.expit(lp.logit(0.45) + b * (lp.logit(0.7) - lp.logit(0.5))) - 0.45
    assert sig["k"] == 0 and abs(sig["impl"] - want) < 1e-12
    # IS information timing: the moneyline print at 3000 is usable only for t - d > 3000, so B1's order is
    # visible at 3000 + 1000 + 1; B1-delay waits another d; B1-rt acts at seen time + L
    o = eng.ledgers["B1"].orders["S"][0]
    assert (o.k, o.P, o.v, o.R) == (0, 0.40, 4001, 625.0)
    assert eng.ledgers["B1-delay"].orders["S"][0].v == 5001
    assert eng.ledgers["B1-rt"].orders["S"][0].v == 3000 + 2 * L


def test_queue_ahead_and_trade_before_book():
    eng = engine()
    setup_signal(eng)
    # the book update for a trade arrives ~25 ms BEFORE the trade message (as on the venue)
    ws(eng, 4975, ("pc", 4975, [("s0", 0.40, 40.0, "BUY")]))
    ws(eng, 5000, ("trade", 5000, "s0", 0.40, 60.0, "SELL"))          # all 60 go to the 100 ahead of us
    ws(eng, 5975, ("pc", 5975, [("s0", 0.40, 0.0, "BUY")]))
    ws(eng, 6000, ("trade", 6000, "s0", 0.40, 100.0, "SELL"))         # 40 ahead, then us
    eng.run()
    f1 = fills(eng, "B1")
    assert len(f1) == 1 and f1[0]["q_ahead"] == 40.0 and abs(f1[0]["shares"] - 20.0) < 1e-9   # 0.2 x 100
    ff = fills(eng, "B1-full")
    assert len(ff) == 1 and abs(ff[0]["shares"] - 60.0) < 1e-9        # 100 - 40 ahead, not 100 (no double count)
    assert ff[0]["px"] == 0.40 and ff[0]["fee_ps"] == 0.0
    assert abs(ff[0]["rebate_ps"] - 0.15 * 0.05 * 0.4 * 0.6) < 1e-12


def test_cancels_ahead_shrink_queue():
    eng = engine()
    setup_signal(eng)
    ws(eng, 4500, ("pc", 4500, [("s0", 0.40, 10.0, "BUY")]))          # 90 ahead of us cancel (no trade)
    ws(eng, 6000, ("trade", 6000, "s0", 0.40, 50.0, "SELL"))          # > 500 ms later: the cancel is settled
    eng.run()
    ff = fills(eng, "B1-full")
    assert len(ff) == 1 and ff[0]["q_ahead"] == 10.0 and abs(ff[0]["shares"] - 40.0) < 1e-9


def test_through_price_and_wrong_side():
    eng = engine()
    setup_signal(eng)
    ws(eng, 5000, ("trade", 5000, "s0", 0.47, 500.0, "BUY"))          # taker bought s0: does not hit our bid
    ws(eng, 5100, ("trade", 5100, "s1", 0.55, 500.0, "BUY"))          # = s0 sold at 0.45 > our 0.40: not reached
    ws(eng, 5200, ("trade", 5200, "s1", 0.62, 50.0, "BUY"))           # = s0 sold at 0.38 < 0.40: through us
    eng.run()
    f = fills(eng, "B1")
    assert len(f) == 1 and f[0]["kind"] == "through" and f[0]["px"] == 0.40 and abs(f[0]["shares"] - 10.0) < 1e-9


def test_trade_before_visible_or_after_cancel_does_not_fill():
    eng = engine()
    setup_signal(eng)
    # before v = 4001: no fill. It is also a side print: the side has caught up (mid 0.425 with the moneyline
    # unchanged since), so the state goes off at 3990 + 1000 + 1 and the quote is cancelled then
    ws(eng, 3990, ("trade", 3990, "s0", 0.40, 500.0, "SELL"))
    ws(eng, 4500, ("trade", 4500, "s0", 0.38, 50.0, "SELL"))          # visible, cancel not yet effective: fills
    ws(eng, 5500, ("trade", 5500, "s0", 0.38, 50.0, "SELL"))          # after the cancel: no fill
    eng.run()
    f = fills(eng, "B1")
    assert [x["e"] for x in f] == [4500]
    o = [x for x in eng.ledgers["B1"].orders["S"]] or []
    assert not any(x.live() for x in o)
    assert eng.signal("S", 5000, 5000, "lag")["k"] is None


def test_post_only_reject_and_repeg():
    eng = engine()
    setup_signal(eng)
    # ask collapses to our price before we become visible: post-only rejected at activation
    ws(eng, 3950, ("pc", 3950, [("s0", 0.40, 5.0, "SELL")]))
    ws(eng, 4100, ("pc", 4100, [("s0", 0.40, 0.0, "SELL"), ("s0", 0.41, 30.0, "BUY")]))
    eng.run(upto=10_000)
    g = eng.ledgers["B1"]
    assert g.n_reject == 1
    live = [o for o in g.orders["S"] if o.live()]
    assert len(live) == 1 and live[0].P == 0.41 and live[0].v == 4100 + 2 * L   # retried at the new best bid


def test_budget_cap_per_match():
    eng = engine([lp.Variant("B1-full", "maker", "lag", None)])
    setup_signal(eng)
    eng.run(upto=4500)
    g = eng.ledgers["B1-full"]
    assert g.orders["S"][0].R * g.orders["S"][0].P <= 250 + 1e-9          # $250 per order
    g.used["ev"] = 1900.0                                                  # $100 of the $2,000 match budget left
    ws(eng, 5000, ("trade", 5000, "s0", 0.40, 10_000.0, "SELL"))
    eng.run(upto=20_000)
    f = g.fills
    assert len(f) == 1 and abs(f[0]["usd"] - 100.0) < 1e-6 and abs(g.used["ev"] - 2000.0) < 1e-6
    assert not any(o.live() for o in g.orders["S"])                        # no budget, no new quote


def test_taker_control_pays_latency_and_delay():
    eng = engine([lp.Variant("CTRL-taker", "taker", "rt", None)])
    setup_signal(eng)
    # the ask moves from 0.50 to 0.60 / 0.70 during our latency + the 1 s venue delay
    ws(eng, 3500, ("book", 3500, "s0", [(0.40, 100.0)], [(0.60, 100.0), (0.70, 1000.0)]))
    ws(eng, 7000, ("pc", 7000, [("s1", 0.30, 10.0, "BUY")]))       # the market's clock passes t_exec
    eng.run()
    f = fills(eng, "CTRL-taker")
    assert len(f) == 1
    x = f[0]
    assert x["e"] == 3000 + 2 * L + 1000 and x["ask_seen"] == 0.50 and x["how"] == "book"
    want_sh = math.floor(250 / x["limit"] * 100) / 100
    vwap = (100 * 0.60 + (want_sh - 100) * 0.70) / want_sh
    assert abs(x["shares"] - want_sh) < 1e-9 and abs(x["px"] - vwap) < 1e-12
    fee = (100 * 0.05 * 0.6 * 0.4 + (want_sh - 100) * 0.05 * 0.7 * 0.3) / want_sh
    assert abs(x["fee_ps"] - fee) < 1e-12 and x["slip_c"] > 15


def test_resolution_and_pnl():
    eng = engine()
    setup_signal(eng)
    ws(eng, 6000, ("trade", 6000, "s0", 0.38, 100.0, "SELL"))
    ws(eng, 9000, ("resolved", 9000, "S", "s0"))
    eng.run()
    s = eng.book_stats(eng.ledgers["B1"])
    reb = 0.15 * 0.05 * 0.4 * 0.6
    assert s["resolved_fills"] == 1 and abs(s["realised"] - 20 * (1 - 0.40 + reb)) < 1e-9


def test_deterministic_live_vs_replay():
    """Processing in drain rounds (live) and all at once (replay) gives the same fills."""
    def build():
        eng = engine()
        setup_signal(eng)
        ws(eng, 4975, ("pc", 4975, [("s0", 0.40, 40.0, "BUY")]))
        ws(eng, 5000, ("trade", 5000, "s0", 0.40, 60.0, "SELL"))
        ws(eng, 5200, ("trade", 5200, "s1", 0.62, 50.0, "BUY"))
        ws(eng, 7000, ("trade", 7000, "m0", 0.55, 10.0, "BUY"))
        ws(eng, 7500, ("trade", 7500, "s0", 0.39, 50.0, "SELL"))
        return eng
    a = build()
    a.run()
    b = build()
    for w in range(0, 20_000, 20):
        b.run(upto=w)
    b.run()
    for name in a.ledgers:
        assert [(f["e"], f["shares"], f["px"]) for f in a.ledgers[name].fills] == \
               [(f["e"], f["shares"], f["px"]) for f in b.ledgers[name].fills]


def test_bootstrap_history_before_subscription_only():
    eng = engine()
    ws(eng, 100, ("book", 100, "s0", [(0.40, 100.0)], [(0.50, 100.0)]), key=50_000)   # first seen at 50 s
    ws(eng, 49_000, ("trade", 49_000, "s0", 0.45, 7.0, "BUY"), key=50_100)
    eng.push(60_000, "boot", {"cond": "S", "prints": [[1_000, 0.44, True, 3.0], [48_500, 0.45, True, 7.0],
                                                      [49_500, 0.46, False, 2.0], [55_000, 0.47, True, 1.0]]})
    eng.run()
    # 1000 and 49500 are before the subscription (50 s): kept. 48500 is the socket print at 49000 seen through
    # data-api (same size and price within 3 s): dropped. 55000 is after the subscription: dropped
    assert eng.prints["S"].ts == [1_000, 49_000, 49_500]


def test_normalize_survives_malformed():
    evs, bad = lp.normalize([{"event_type": "book"}, "x", {"event_type": "last_trade_price", "timestamp": "5",
                                                            "asset_id": "a", "price": "0.5", "size": "2", "side": "BUY"}])
    assert bad == 2 and evs == [("trade", 5, "a", 0.5, 2.0, "BUY")]


# ------------------------------------------------------------------ verifier fixes (DEVIATIONS_LIVE.md L11-L13)
def test_taker_timer_waits_for_venue_clock_under_feed_lag():
    """A book change stamped before t_exec that we receive late must be in the book the taker order meets."""
    eng = engine([lp.Variant("CTRL-taker", "taker", "rt", None)])
    for e, ev in ((100, ("book", 100, "s0", [(0.40, 100.0)], [(0.50, 100.0)])),
                  (100, ("book", 100, "s1", [(0.50, 100.0)], [(0.60, 100.0)])),
                  (500, ("trade", 500, "m0", 0.50, 10.0, "BUY")), (1000, ("trade", 1000, "s0", 0.45, 10.0, "BUY")),
                  (3000, ("trade", 3000, "m0", 0.70, 10.0, "BUY")),
                  (3500, ("book", 3500, "s0", [(0.40, 100.0)], [(0.60, 100.0), (0.70, 1000.0)]))):
        eng.push(e + L, "wsc", (0, ev))                                # all on socket 0
    t_exec = 3000 + 2 * L + 1000
    # stamped 4000 (< t_exec) but received 20 s late: the venue had a 0.55 ask at t_exec
    eng.push(24_000, "wsc", (0, ("pc", 4000, [("s0", 0.55, 1000.0, "SELL")])))
    eng.push(24_001, "wsc", (0, ("pc", t_exec + 999, [("m0", 0.69, 10.0, "BUY")])))   # within the margin
    eng.run(upto=30_000)
    assert fills(eng, "CTRL-taker") == []
    eng.push(30_000, "wsc", (0, ("pc", t_exec + 1000, [("m0", 0.68, 10.0, "BUY")])))  # socket clock passes it
    eng.run()
    x = fills(eng, "CTRL-taker")[0]
    assert x["e"] == t_exec and abs(x["px"] - 0.55) < 1e-12 and x["how"] == "timer"
    assert eng.cnt["texec_rearm"] > 0


def test_taker_timer_live_socket_dead_voids_and_recorder_quiet_executes():
    eng = engine([lp.Variant("CTRL-taker", "taker", "rt", None)])
    setup_signal(eng)                     # recorder-style input (no socket id), market quiet after t_exec
    eng.run()
    x = fills(eng, "CTRL-taker")[0]
    assert x["how"] == "timer: market quiet 600 s" and x["px"] == 0.50
    eng = engine([lp.Variant("CTRL-taker", "taker", "rt", None)])
    for e, ev in ((100, ("book", 100, "s0", [(0.40, 100.0)], [(0.50, 100.0)])),
                  (500, ("trade", 500, "m0", 0.50, 10.0, "BUY")), (1000, ("trade", 1000, "s0", 0.45, 10.0, "BUY")),
                  (3000, ("trade", 3000, "m0", 0.70, 10.0, "BUY"))):
        eng.push(e + L, "wsc", (0, ev))
    eng.run()                             # live socket never passes t_exec: void, never priced on a stale book
    g = eng.ledgers["CTRL-taker"]
    assert g.fills == [] and g.n_taker_void == 1


def test_feed_gap_pulls_quotes_and_voids_takers():
    eng = engine()
    setup_signal(eng)
    eng.run(upto=4500)
    o = eng.ledgers["B1"].orders["S"][0]
    assert o.live()
    pend = [t for t in eng.ledgers["CTRL-taker"].torders["S"] if t.status == "pending"]
    eng.push(4600, "gap", {"conn": None, "toks": ["s0", "s1", "m0", "m1"], "phase": "socket_error"})
    eng.run(upto=4700)
    assert o.c == 3001 and o.why_end == "feed gap" and eng.ledgers["B1"].n_gap_cancel == 1
    assert all(t.status == "void" for t in pend) and eng.ledgers["CTRL-taker"].n_taker_void == len(pend)
    assert eng.in_gap("S")
    # data comes back: the pulled quote is gone, and the next book update re-quotes from the fresh book
    ws(eng, 9000, ("pc", 9000, [("s0", 0.39, 50.0, "BUY")]), key=9100)
    eng.run(upto=9150)
    assert not eng.in_gap("S") and o.status == "cancelled"
    live = [x for x in eng.ledgers["B1"].orders["S"] if x.live()]
    assert len(live) == 1 and live[0].P == 0.40 and live[0].oid != o.oid
    # a trade through our old price fills only the new quote, from its own queue position
    ws(eng, 12000, ("trade", 12000, "s0", 0.38, 100.0, "SELL"), key=12100)
    eng.run(upto=20_000)
    assert all(f["oid"] != o.oid for f in fills(eng, "B1"))


def test_gamma_universe_pages_past_a_100_row_cap():
    """Gamma returns at most 100 rows per page; discovery must read every page."""
    now = lp.now_ms()
    allev = []
    for i in range(455):
        allev.append({"id": i, "seriesSlug": "atp", "title": f"T: P{i} vs Q{i}",
                      "startTime": lp.iso(now + 3600_000 if i % 2 else now - 3600_000),
                      "markets": [{"sportsMarketType": "moneyline", "conditionId": f"c{i}",
                                   "clobTokenIds": f'["a{i}", "b{i}"]', "outcomes": '["P", "Q"]',
                                   "outcomePrices": '["0.5", "0.5"]'}]})
    calls = []

    def get(sess, url, params):
        calls.append(dict(params))
        off, lim = params["offset"], min(params["limit"], 100)     # the server-side cap
        return allev[off:off + lim]
    st = {}
    E, M = lp.gamma_universe(None, 8.0, 3.0, get, st)
    assert len(E) == 455 and len(M) == 455 and st == {"gamma_pages": 5, "gamma_events": 455}
    assert [c["offset"] for c in calls] == [0, 100, 200, 300, 400, 455]

    def get_dup(sess, url, params):                                # a server that ignores offset
        return allev[:100]
    E2, _ = lp.gamma_universe(None, 8.0, 3.0, get_dup, None)
    assert len(E2) == 100

    def get_fail(sess, url, params):
        return None if params["offset"] == 200 else allev[params["offset"]:params["offset"] + 100]
    try:
        lp.gamma_universe(None, 8.0, 3.0, get_fail, None)
        assert False, "a failed page must not yield a partial universe"
    except RuntimeError:
        pass


def test_wsc_socket_clock_and_raw_replay_keep_conn():
    eng = engine()
    eng.push(10, "wsc", (3, ("pc", 10, [("s0", 0.40, 5.0, "BUY")])))
    eng.push(11, "wsc", (3, ("book", 5, "s1", [(0.5, 1.0)], [(0.6, 1.0)])))
    eng.run()
    assert eng.tok_conn["s0"] == 3 and eng.e_conn[3] == 10 and eng.server_clock("S") == 10
    assert eng.e_mkt["S"] == 10
