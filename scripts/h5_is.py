import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.tape import universe
from src import backtest as bt, strategies as st, polymarket as pm

if __name__ == "__main__":
    u = universe()
    have = {f.stem for f in (pm.RAW / "trades").glob("*.parquet")}
    u_is = u[(~u.oos) & u.cond.isin(have)]
    print("IS matches:", len(u_is))
    res = {}
    res["always_on"] = bt.stats(bt.run(st.h5_fills, u_is, always_on=True))
    res["window_J0.04_W30"] = bt.stats(bt.run(st.h5_fills, u_is, J=0.04, W=30))
    print(pd.DataFrame(res).to_string())
