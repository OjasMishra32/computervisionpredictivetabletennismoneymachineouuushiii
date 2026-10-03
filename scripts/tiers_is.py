import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from src.tape import universe
from src import tiers, polymarket as pm


def one(r):
    try:
        return tiers.match_prints(SimpleNamespace(**r))
    except Exception as e:
        return None


if __name__ == "__main__":
    u = universe()
    have = {f.stem for f in (pm.RAW / "trades").glob("*.parquet")}
    u_is = u[(~u.oos) & u.cond.isin(have)]
    with ProcessPoolExecutor(8) as ex:
        parts = [d for d in ex.map(one, u_is.to_dict("records"), chunksize=16) if d is not None]
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet("data/is_prints.parquet")
    print("prints", len(df), "matches", df.cond.nunique())
    pd.set_option("display.width", 250)
    for side, lab in ((1, "WITH jump"), (-1, "AGAINST jump"), (0, "no jump yet")):
        g = df[df.with_jump == side] if side else df[df.bucket == "no jump"]
        agg = g.groupby("bucket", observed=True).apply(lambda x: pd.Series({
            "n": len(x), "usd_k": x.usd.sum() / 1e3,
            **{f"mo{h}_c": np.average(x[f"mo{h}"].fillna(0), weights=x.usd) * 100 for h in tiers.HORIZONS},
            "mo_res_c": np.nanmean(x.mo_res) * 100, "med_spread_c": np.nanmedian(x.spread) * 100}), include_groups=False)
        print("\n==", lab); print(agg.round(2).to_string())
