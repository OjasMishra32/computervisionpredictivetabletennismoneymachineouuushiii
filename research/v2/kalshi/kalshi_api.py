"""Keyless, read-only, cached Kalshi public market-data client (research/v2/kalshi).

Only public GET endpoints, no credentials. A global token bucket keeps the whole
process at <= RATE requests/second, and 429/5xx responses back off exponentially.
Every response used for research is cached under data/v2_kalshi/ so reruns never
hit the network twice.

OOS guard: every trade fetch is clamped to max_ts < OOS_CUTOFF and every market
listing uses settle-time filters that end before OOS_CUTOFF (or the historical
archive, which ends 2026-08-04 and is therefore entirely in-sample).
"""
from __future__ import annotations

import gzip
import json
import threading
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
CACHE = Path("data/v2_kalshi")
OOS_CUTOFF = pd.Timestamp("2026-08-25 14:15", tz="UTC")
OOS_TS = int(OOS_CUTOFF.timestamp())
RATE = 8.0  # requests per second, whole process (Kalshi basic read budget = 20 req/s)

_session = requests.Session()
_session.headers["User-Agent"] = "courtside-research/0.2 (read-only, academic)"
_lock = threading.Lock()
_next_slot = [0.0]


def _throttle() -> None:
    with _lock:
        now = time.monotonic()
        slot = max(now, _next_slot[0])
        _next_slot[0] = slot + 1.0 / RATE
    wait = slot - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def get(path: str, params: dict | None = None, tries: int = 8) -> dict:
    url = f"{BASE}{path}"
    for k in range(tries):
        _throttle()
        try:
            r = _session.get(url, params=params, timeout=40)
        except requests.RequestException:
            time.sleep(min(60, 2 ** k))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(60, 2 ** k))
            continue
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"GET failed after {tries} tries: {url} {params}")


def paginate(path: str, params: dict, key: str, max_pages: int = 10_000) -> list[dict]:
    out, cursor = [], None
    for _ in range(max_pages):
        q = dict(params)
        if cursor:
            q["cursor"] = cursor
        d = get(path, q)
        out += d.get(key, []) or []
        cursor = d.get("cursor")
        if not cursor:
            break
    return out


def cutoff() -> dict:
    f = CACHE / "historical_cutoff.json"
    if f.exists():
        return json.loads(f.read_text())
    d = get("/historical/cutoff")
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d))
    return d


def list_markets(series: str) -> pd.DataFrame:
    """All settled IS markets of a series: historical archive + live tier up to the OOS cutoff."""
    f = CACHE / f"markets_{series}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    hist = paginate("/historical/markets", {"series_ticker": series, "limit": 1000}, "markets")
    lo = int(pd.Timestamp(cutoff()["market_settled_ts"]).timestamp()) - 86400
    live = paginate("/markets", {"series_ticker": series, "limit": 1000,
                                 "min_settled_ts": lo, "max_settled_ts": OOS_TS}, "markets")
    rows = []
    for m, tier in [(m, "hist") for m in hist] + [(m, "live") for m in live]:
        rows.append({
            "ticker": m.get("ticker"), "event_ticker": m.get("event_ticker"), "tier": tier,
            "title": m.get("title"), "yes_name": m.get("yes_sub_title"), "no_name": m.get("no_sub_title"),
            "rules": m.get("rules_primary"), "open_time": m.get("open_time"),
            "close_time": m.get("close_time"), "occurrence": m.get("occurrence_datetime"),
            "expected_exp": m.get("expected_expiration_time"), "settlement_ts": m.get("settlement_ts"),
            "result": m.get("result"), "settle_value": m.get("settlement_value_dollars"),
            "volume": float(m.get("volume_fp") or m.get("volume") or 0),
            "status": m.get("status"), "tick_structure": m.get("price_level_structure"),
        })
    df = pd.DataFrame(rows).drop_duplicates("ticker").reset_index(drop=True)
    df["settle_value"] = pd.to_numeric(df.settle_value, errors="coerce")
    for c in ["open_time", "close_time", "occurrence", "expected_exp", "settlement_ts"]:
        df[c] = pd.to_datetime(df[c], utc=True, format="mixed", errors="coerce")
    # hard OOS guard: drop anything closing at/after the cutoff
    df = df[df.close_time < OOS_CUTOFF].reset_index(drop=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(f)
    return df


def fetch_trades(ticker: str, min_ts: int, max_ts: int) -> pd.DataFrame:
    """Every trade of a market in [min_ts, max_ts] (unix s), cached per ticker.

    Routes to /historical/trades for the part before the trades cutoff and
    /markets/trades for the rest. max_ts is clamped below the OOS cutoff.
    """
    f = CACHE / "trades" / f"{ticker}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    max_ts = min(max_ts, OOS_TS - 1)
    tcut = int(pd.Timestamp(cutoff()["trades_created_ts"]).timestamp())
    raw = []
    if min_ts < tcut:
        raw += paginate("/historical/trades", {"ticker": ticker, "limit": 1000, "min_ts": min_ts,
                                               "max_ts": min(max_ts, tcut)}, "trades")
    if max_ts >= tcut:
        raw += paginate("/markets/trades", {"ticker": ticker, "limit": 1000,
                                            "min_ts": max(min_ts, tcut - 60), "max_ts": max_ts}, "trades")
    rows = [{
        "trade_id": t.get("trade_id"), "created_time": t.get("created_time"),
        "yes_price": float(t.get("yes_price_dollars") or 0), "count": float(t.get("count_fp") or t.get("count") or 0),
        "taker_side": t.get("taker_side"), "taker_book_side": t.get("taker_book_side"),
        "block": bool(t.get("is_block_trade")),
    } for t in raw]
    df = pd.DataFrame(rows, columns=["trade_id", "created_time", "yes_price", "count", "taker_side",
                                     "taker_book_side", "block"])
    if len(df):
        df = df.drop_duplicates("trade_id")
        df["ts"] = (pd.to_datetime(df.created_time, utc=True, format="mixed")
                    - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()
        df = df[df.ts < OOS_TS].sort_values("ts", kind="stable").reset_index(drop=True)
        df = df.drop(columns=["created_time"])
    else:
        df["ts"] = pd.Series(dtype=float)
    f.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(f)
    return df
