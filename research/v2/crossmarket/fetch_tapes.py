"""Step 2: trade tapes of IS side markets (public data-api, <= 4 concurrent, back-off on 429).

Fetches every side market of an IS match with lifetime volume >= MIN_VOL (default $250, which is
95% of side-market volume), most recent months first. Cached to data/v2_crossmarket/trades/.
Run: .venv/bin/python research/v2/crossmarket/fetch_tapes.py [--min-vol 250]
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OOS_CUT, TRADES, TRADES_DIR, get, side_markets  # noqa: E402

FIELDS = ("timestamp", "side", "outcomeIndex", "price", "size", "proxyWallet", "transactionHash")


def fetch(cond: str) -> int:
    f = TRADES_DIR / f"{cond}.parquet"
    if f.exists():
        return -1
    out = []
    for offset in range(0, 10001, 500):
        page = get(TRADES, {"market": cond, "limit": 500, "offset": offset})
        if not isinstance(page, list) or not page:
            break
        out += [{k: r.get(k) for k in FIELDS} for r in page]
        if len(page) < 500:
            break
    df = pd.DataFrame(out, columns=list(FIELDS))
    if len(df):
        df = df.drop_duplicates().sort_values("timestamp", kind="stable").reset_index(drop=True)
    tmp = f.with_suffix(".tmp")
    df.to_parquet(tmp)
    tmp.rename(f)
    return len(df)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-vol", type=float, default=250.0)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    assert a.workers <= 4
    sm = side_markets()
    sm = sm[(sm.volume >= a.min_vol) & (sm.start < OOS_CUT)]
    sm = sm.sort_values("start", ascending=False)
    todo = [c for c in sm.cond if not (TRADES_DIR / f"{c}.parquet").exists()]
    print(f"{len(sm)} markets >= ${a.min_vol:.0f}; {len(todo)} to fetch", flush=True)
    TRADES_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(fetch, c): c for c in todo}
        for i, fu in enumerate(as_completed(futs)):
            try:
                fu.result()
            except Exception as err:  # logged, not fatal
                print("fail", futs[fu], err, flush=True)
            if i % 500 == 0:
                print(f"{i}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
