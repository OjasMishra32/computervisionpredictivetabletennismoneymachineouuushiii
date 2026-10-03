"""Public, keyless Polymarket endpoints: event catalogue, trade tapes, price history.

All reads are cached to data/raw so a rerun never hits the network twice.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

GAMMA = "https://gamma-api.polymarket.com/events"
TRADES = "https://data-api.polymarket.com/trades"
HISTORY = "https://clob.polymarket.com/prices-history"
RAW = Path("data/raw")

_session = requests.Session()
_session.headers["User-Agent"] = "courtside-research/0.1"


def _get(url: str, params: dict, tries: int = 5):
    for k in range(tries):
        try:
            r = _session.get(url, params=params, timeout=40)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(1.5 * (k + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"GET failed: {url} {params}")


def _slim(e: dict) -> list[dict]:
    """One row per moneyline market with the event fields we need."""
    rows = []
    other_vol = sum(float(m.get("volume") or 0) for m in e.get("markets", [])
                    if m.get("sportsMarketType") != "moneyline")
    for m in e.get("markets", []):
        if m.get("sportsMarketType") != "moneyline":
            continue
        outcomes = json.loads(m.get("outcomes") or "[]")
        prices = json.loads(m.get("outcomePrices") or "[]")
        toks = json.loads(m.get("clobTokenIds") or "[]")
        if len(outcomes) != 2 or len(toks) != 2:
            continue
        fs = m.get("feeSchedule") or {}
        rows.append({
            "slug": e.get("slug"), "title": e.get("title"), "series": e.get("seriesSlug"),
            "league": (e.get("eventMetadata") or {}).get("league"),
            "start_time": e.get("startTime"), "finished": e.get("finishedTimestamp"),
            "closed_time": e.get("closedTime"), "score": e.get("score"), "game_id": e.get("gameId"),
            "cond": m["conditionId"], "tok0": toks[0], "tok1": toks[1],
            "out0": outcomes[0], "out1": outcomes[1],
            "res0": float(prices[0]) if prices else None,
            "volume": float(m.get("volume") or 0), "other_volume": other_vol,
            "fee_rate": fs.get("rate"), "fee_exp": fs.get("exponent"),
            "seconds_delay": m.get("secondsDelay"), "tick": m.get("orderPriceMinTickSize"),
        })
    return rows


def _window(tag: str, lo: str, hi: str) -> list[dict]:
    rows = []
    for offset in range(0, 2000, 100):  # gamma serves 100 per page and caps the offset
        evs = _get(GAMMA, {"tag_slug": tag, "closed": "true", "limit": 100, "offset": offset,
                           "start_date_min": lo, "start_date_max": hi})
        for e in evs:
            rows += [{**r, "event_id": e["id"]} for r in _slim(e)]
        if len(evs) < 100:
            break
    return rows


def enumerate_events(tag: str, since: str, until: str, workers: int = 6) -> pd.DataFrame:
    """Closed events for a tag, walked in one-day creation-date windows."""
    cache = RAW / f"events_{tag}_{since}_{until}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    d0, d1 = dt.date.fromisoformat(since), dt.date.fromisoformat(until)
    days = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days)]
    rows = []
    with ThreadPoolExecutor(workers) as ex:
        for part in ex.map(lambda d: _window(tag, d.isoformat(), (d + dt.timedelta(days=1)).isoformat()), days):
            rows += part
    df = pd.DataFrame(rows).drop_duplicates("cond").reset_index(drop=True)
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def fetch_trades(cond: str) -> pd.DataFrame:
    """Every taker fill for a market (data-api caps the offset at 10000)."""
    cache = RAW / "trades" / f"{cond}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    out = []
    for offset in range(0, 10001, 500):
        page = _get(TRADES, {"market": cond, "limit": 500, "offset": offset})
        if not isinstance(page, list) or not page:
            break
        out += [{k: r.get(k) for k in ("timestamp", "side", "outcomeIndex", "price", "size",
                                        "proxyWallet", "transactionHash")} for r in page]
        if len(page) < 500:
            break
    df = pd.DataFrame(out)
    if len(df):
        df = df.drop_duplicates().sort_values("timestamp", kind="stable").reset_index(drop=True)
        # one probability axis: price of outcome 0
        df["p0"] = df["price"].where(df["outcomeIndex"] == 0, 1 - df["price"])
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def fetch_many_trades(conds: list[str], workers: int = 8) -> None:
    todo = [c for c in conds if not (RAW / "trades" / f"{c}.parquet").exists()]
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch_trades, c): c for c in todo}
        for i, f in enumerate(as_completed(futs)):
            try:
                f.result()
            except Exception as err:  # keep going; a missing tape is logged, not fatal
                print("trade fetch failed", futs[f], err)
            if i % 100 == 0:
                print(f"trades {i}/{len(todo)}", flush=True)


def price_history(token: str, start: int, end: int, fidelity: int = 1) -> pd.DataFrame:
    d = _get(HISTORY, {"market": token, "startTs": start, "endTs": end, "fidelity": fidelity})
    return pd.DataFrame(d.get("history", []))
