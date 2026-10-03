"""Data build for the U2 out-of-universe test (research/v2/expand/PREREG.md).

Stages (run from the repo root):
  python research/v2/expand/build_u2.py universe   # select U2 from the catalogue, save expand_universe
  python research/v2/expand/build_u2.py fetch      # fetch U2 trade tapes (<= 6 HTTP workers)
  python research/v2/expand/build_u2.py prints     # build per-print tables (<= 3 processes)

No P&L, markout summary or strategy statistic is computed here.
"""
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src import polymarket as pm, tiers  # noqa: E402
from src.tape import universe  # noqa: E402

CATALOGUE = pm.RAW / "events_tennis_2025-07-01_2026-10-03.parquet"
U_OUT = Path("data/expand_universe.parquet")
P_OUT = Path("data/expand_prints.parquet")
SERIES = {"atp", "wta", "challenger", "itf"}
MIN_VOL = 1_000
END = pd.Timestamp("2026-10-03 07:10", tz="UTC")       # latest U1 match start
OOS_CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")   # U1 OOS cutoff
COLS = ["slug", "title", "series", "league", "start_time", "finished", "closed_time", "cond",
        "res0", "volume", "fee_rate", "seconds_delay", "tick", "event_id"]


def select_u2() -> pd.DataFrame:
    ev = pd.read_parquet(CATALOGUE, columns=COLS)
    ev["start"] = pd.to_datetime(ev.start_time, utc=True, format="mixed")
    u1 = set(universe().cond)
    m = (ev.series.isin(SERIES) & ~ev.series.fillna("").str.contains("doubles")
         & (ev.volume >= MIN_VOL) & ev.res0.isin([0.0, 0.5, 1.0])
         & (ev.start < END) & ~ev.cond.isin(u1))
    u = ev[m].copy()
    u["end"] = pd.to_datetime(u.finished.fillna(u.closed_time), utc=True, format="mixed")
    u["fee_rate"] = u.fee_rate.fillna(0.0)
    u["delay"] = u.seconds_delay.fillna(1).astype(int)
    u = u.sort_values("start", kind="stable").reset_index(drop=True)
    u["oos"] = u.start >= OOS_CUT
    return u


def _one(r):
    try:
        return tiers.match_prints(SimpleNamespace(**r))
    except Exception:
        return None


def main(stage: str) -> None:
    if stage == "universe":
        u = select_u2()
        U_OUT.parent.mkdir(parents=True, exist_ok=True)
        u.to_parquet(U_OUT)
        print("U2", len(u), u.groupby("series").size().to_dict(), "oos", int(u.oos.sum()), flush=True)
    elif stage == "fetch":
        u = pd.read_parquet(U_OUT, columns=["cond"])
        pm.fetch_many_trades(u.cond.tolist(), workers=6)
        have = {f.stem for f in (pm.RAW / "trades").glob("*.parquet")}
        miss = [c for c in u.cond if c not in have]
        print("fetched", len(u) - len(miss), "missing", len(miss), flush=True)
        Path("data/expand_fetch_missing.txt").write_text("\n".join(miss))
    elif stage == "prints":
        u = pd.read_parquet(U_OUT)
        have = {f.stem for f in (pm.RAW / "trades").glob("*.parquet")}
        rows = u[u.cond.isin(have)][["cond", "start", "end", "res0", "fee_rate", "delay"]]
        with ProcessPoolExecutor(3) as ex:
            parts = [d for d in ex.map(_one, rows.to_dict("records"), chunksize=32) if d is not None]
        df = pd.concat(parts, ignore_index=True)
        df.to_parquet(P_OUT)
        print("prints rows", len(df), "matches", df.cond.nunique(), "of", len(rows), "with tapes", flush=True)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1])
