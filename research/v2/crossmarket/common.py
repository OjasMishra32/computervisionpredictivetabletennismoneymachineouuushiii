"""Shared helpers for the crossmarket lens (side markets of the same tennis match).

Everything here is in-sample only: the universe is data/derived/universe_is.parquet, which
stops before the locked OOS cutoff (2026-08-25 14:15 UTC). A guard re-checks this on load.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "v2_crossmarket"
TRADES_DIR = CACHE / "trades"
OUT = Path(__file__).resolve().parent
OOS_CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")

GAMMA = "https://gamma-api.polymarket.com/events"
TRADES = "https://data-api.polymarket.com/trades"

_session = requests.Session()
_session.headers["User-Agent"] = "courtside-research/0.1 (read-only, crossmarket lens)"


def get(url: str, params, tries: int = 6, timeout: int = 60):
    """Polite GET with exponential back-off on 429 / 5xx."""
    for k in range(tries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2.0 * (2 ** k))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(2.0 * (2 ** k))
    raise RuntimeError(f"GET failed: {url} {params}")


def universe_is() -> pd.DataFrame:
    u = pd.read_parquet(ROOT / "data" / "derived" / "universe_is.parquet")
    assert (u.start < OOS_CUT).all(), "universe_is contains OOS matches"
    return u


def side_markets() -> pd.DataFrame:
    sm = pd.read_parquet(CACHE / "side_markets.parquet")
    assert (sm.start < OOS_CUT).all()
    return sm


def taker_fee(p, rate):
    return rate * p * (1 - p)


def load_side_tape(cond: str) -> pd.DataFrame | None:
    """Side-market tape on one axis: q0 = price of the side market's outcome 0.

    at_ask True = the taker bought outcome 0 (or sold outcome 1): lifted outcome 0's ask.
    """
    f = TRADES_DIR / f"{cond}.parquet"
    if not f.exists():
        return None
    t = pd.read_parquet(f)
    if t.empty:
        return None
    buy0 = ((t.side == "BUY") & (t.outcomeIndex == 0)) | ((t.side == "SELL") & (t.outcomeIndex == 1))
    t = t.assign(at_ask=buy0.to_numpy(), usd=t["size"] * t["price"],
                 q0=np.where(t.outcomeIndex == 0, t.price, 1 - t.price))
    return t[["timestamp", "q0", "at_ask", "size", "usd", "proxyWallet"]].sort_values(
        "timestamp", kind="stable").reset_index(drop=True)


def month_of(ts) -> pd.Series:
    return pd.to_datetime(ts, unit="s", utc=True).dt.tz_localize(None).dt.to_period("M").astype(str)


def regime(delay, fee_rate) -> str:
    return f"{int(delay)}s/{int(round(fee_rate * 100))}%"
