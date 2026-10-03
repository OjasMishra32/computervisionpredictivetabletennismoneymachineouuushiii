"""Build the per-print table (side, markouts, time since jump) for the IS or the locked OOS split."""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src import polymarket as pm, tiers
from src.tape import universe

PEEK_LOG = Path("results/oos_peeks.log")


def _one(r):
    try:
        return tiers.match_prints(SimpleNamespace(**r))
    except Exception:
        return None


def build(split: str, workers: int = 8) -> pd.DataFrame:
    assert split in ("is", "oos")
    out = Path("data/is_prints.parquet") if split == "is" else Path("data/locked/oos_prints.parquet")
    if out.exists():
        return pd.read_parquet(out)
    u = universe()
    if split == "oos":
        PEEK_LOG.parent.mkdir(exist_ok=True)
        with PEEK_LOG.open("a") as f:
            f.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} OOS prints built\n")
    have = {f.stem for f in (pm.RAW / "trades").glob("*.parquet")}
    rows = u[(u.oos == (split == "oos")) & u.cond.isin(have)]
    with ProcessPoolExecutor(workers) as ex:
        parts = [d for d in ex.map(_one, rows.to_dict("records"), chunksize=16) if d is not None]
    df = pd.concat(parts, ignore_index=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    return df
