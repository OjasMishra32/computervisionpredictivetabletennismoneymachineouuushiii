# Test fixtures

`live_sample.jsonl.gz` (2.1 MB): the first 10 minutes (11:23:25-11:33:25 UTC, 2026-10-03) of a recording of the
public, unauthenticated Polymarket CLOB `market` websocket, made read-only by our recorder into
`data/live_v2/clob_20261003_1123_20261003_11.jsonl.gz` (not in git). Public market data only: no orders, no keys.
Cut by `scripts/make_live_sample.py` to the 14 ATP / WTA / Challenger singles events that started before
13:00 UTC (so none is in the v2 forward-test window), moneyline plus six side-market types; 140,805 lines
(992 book snapshots, 139,437 price changes, 366 trades, 6 resolutions); best_bid_ask lines dropped. Line 1 is
the recorder's token index. Replay: `bash run.sh replay` (`scripts/replay_sample.py`). It is a mechanics demo of
recorded live data, not evidence of an edge.
