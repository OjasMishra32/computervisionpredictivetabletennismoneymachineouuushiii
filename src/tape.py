"""Universe, the locked out-of-sample split, and trade-tape preprocessing."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src import polymarket as pm

SINCE, UNTIL = "2025-07-01", "2026-10-03"
MIN_VOL = 5_000
OOS_FRAC = 0.20  # track rule: last 20% or last 2 years, whichever is shorter -> 20% binds


def universe() -> pd.DataFrame:
    ten = pm.enumerate_events("tennis", SINCE, UNTIL)
    u = ten[ten.series.isin(["atp", "wta", "challenger"]) & (ten.volume >= MIN_VOL)].copy()
    u["start"] = pd.to_datetime(u.start_time, utc=True)
    u["end"] = pd.to_datetime(u.finished.fillna(u.closed_time), utc=True, format="mixed")
    u["fee_rate"] = u.fee_rate.fillna(0.0)
    u["delay"] = u.seconds_delay.fillna(1).astype(int)
    u = u.sort_values("start", kind="stable").reset_index(drop=True)
    cut = u.start.iloc[int(len(u) * (1 - OOS_FRAC))]
    u["oos"] = u.start >= cut
    return u


def oos_cutoff() -> pd.Timestamp:
    u = universe()
    return u.loc[u.oos, "start"].min()


def load_tape(cond: str) -> pd.DataFrame | None:
    f = pm.RAW / "trades" / f"{cond}.parquet"
    if not f.exists():
        return None
    t = pd.read_parquet(f)
    if t.empty:
        return None
    # Every print sits on one side of outcome 0's book:
    # BUY o0 / SELL o1 lift outcome 0's ask; SELL o0 / BUY o1 hit its bid.
    buy0 = ((t.side == "BUY") & (t.outcomeIndex == 0)) | ((t.side == "SELL") & (t.outcomeIndex == 1))
    t["at_ask"] = buy0.to_numpy()
    t["usd"] = t["size"] * t["price"]
    return t[["timestamp", "p0", "at_ask", "size", "usd", "proxyWallet"]].reset_index(drop=True)


def in_play(t: pd.DataFrame, row) -> pd.DataFrame:
    s = int(row.start.timestamp())
    e = int(row.end.timestamp()) if pd.notna(row.end) else s + 6 * 3600
    return t[(t.timestamp >= s) & (t.timestamp <= e)]


def taker_fee(p: np.ndarray | float, rate: float) -> np.ndarray | float:
    """Polymarket taker fee per share: rate * p * (1 - p)."""
    return rate * p * (1 - p)
