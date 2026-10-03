from src.paper import Book, Engine


def msgs():
    a = "A"
    yield {"event_type": "book", "asset_id": a, "timestamp": "1000",
           "bids": [{"price": "0.40", "size": "100"}], "asks": [{"price": "0.42", "size": "50"}, {"price": "0.43", "size": "100"}]}
    # ask at 0.42 is lifted away 500 ms later; our order (sent at t_seen) must not get it
    yield {"event_type": "price_change", "timestamp": "1500",
           "price_changes": [{"asset_id": a, "price": "0.42", "size": "0", "side": "SELL"}]}
    yield {"event_type": "price_change", "timestamp": "3000",
           "price_changes": [{"asset_id": a, "price": "0.41", "size": "10", "side": "BUY"}]}


def test_walk_and_delay():
    b = Book(bids={0.40: 100}, asks={0.42: 50, 0.43: 100})
    got, vwap = b.walk("BUY", 80, 0.43)
    assert got == 80 and abs(vwap - (50 * 0.42 + 30 * 0.43) / 80) < 1e-12
    sent = []

    def strat(eng, m, t_seen):
        if m["event_type"] == "book" and not sent:
            eng.send(t_seen, "A", "BUY", 80, 0.43, {"why": "test"})
            sent.append(1)

    e = Engine(one_way_ms=67, delay_ms=1000).run(strat, msgs())
    f = e.fills[0]
    # executes at 1000 + 67 + 67 + 1000 = 2134, after the 0.42 level vanished at 1500
    assert f.t_exec == 2134 and f.price == 0.43 and f.shares == 80
    assert abs(f.fee - 0.05 * 0.43 * 0.57 * 80) < 1e-12
