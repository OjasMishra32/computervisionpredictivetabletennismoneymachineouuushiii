"""Step 3: fetch Kalshi trade tapes (both player markets) for matched IS matches.

Window: [PM start - 15 min, min(PM end, Kalshi close) + 5 min], clamped < OOS cutoff.
4 threads sharing a 4 req/s global throttle; everything cached in data/v2_kalshi/trades/.
"""
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kalshi_api as ka


def job(r, tk):
    lo = int(r.start.timestamp()) - 900
    hi = int(min(r.end, r.k_close).timestamp()) + 300
    assert r.start < ka.OOS_CUTOFF
    return len(ka.fetch_trades(tk, lo, hi))


if __name__ == "__main__":
    m = pd.read_parquet(ka.CACHE / "matched.parquet")
    m = m[m.start < ka.OOS_CUTOFF]
    todo = [(r, tk) for r in m.itertuples() for tk in (r.k_tk0, r.k_tk1)
            if not (ka.CACHE / "trades" / f"{tk}.parquet").exists()]
    print("to fetch", len(todo), flush=True)
    n = 0
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(job, r, tk): tk for r, tk in todo}
        for i, f in enumerate(as_completed(futs)):
            try:
                n += f.result()
            except Exception as e:
                print("fail", futs[f], e, flush=True)
            if i % 200 == 0:
                print(i, len(todo), n, flush=True)
    print("done", n)
