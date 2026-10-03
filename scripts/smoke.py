import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.tape import universe
from src import backtest as bt, strategies as st, polymarket as pm

if __name__ == "__main__":
    u = universe()
    have = {f.stem for f in (pm.RAW / "trades").glob("*.parquet")}
    u_is = u[(~u.oos) & u.cond.isin(have)]
    print("IS matches with tapes:", len(u_is))
    for name, fn in (("h1", st.h1_trades), ("h2", st.h2_trades)):
        t0 = time.time()
        tr = bt.run(fn, u_is.head(int(sys.argv[1]) if len(sys.argv) > 1 else 600))
        print(name, round(time.time() - t0, 1), "s")
        print(pd.Series(bt.stats(tr)).to_string())
