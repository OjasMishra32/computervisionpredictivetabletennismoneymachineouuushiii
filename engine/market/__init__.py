"""Polymarket CLOB market data: L2 books, live websocket feed, recorded replay (read-only)."""
# Lazy exports (PEP 562) so `python -m engine.<pkg>.<module>` runs without a double import.
import importlib

_EXPORTS = {
    "L2Book": "engine.market.book",
    "LatencyTracker": "engine.market.book",
    "FLORIDA_MS": "engine.market.clob",
    "LONDON_MS": "engine.market.clob",
    "MARKET_WS": "engine.market.clob",
    "BaseFeed": "engine.market.clob",
    "LiveClobFeed": "engine.market.clob",
    "MarketEvent": "engine.market.clob",
    "ReadOnlyViolation": "engine.market.clob",
    "ReplayClobFeed": "engine.market.clob",
    "iter_recorded": "engine.market.clob",
    "load_token_meta": "engine.market.clob",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(name)
