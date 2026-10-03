"""Small IS-only derived tables for the v2 research agents (no OOS rows, ever)."""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from src import fasttier, polymarket as pm, tiers
from src.tape import in_play, load_tape, universe

OUT = Path("data/derived")


def jumps(r):
    r = SimpleNamespace(**r)
    t = load_tape(r.cond)
    if t is None:
        return []
    t = in_play(t, r).reset_index(drop=True)
    if len(t) < 20:
        return []
    on = tiers.jump_onsets(t.timestamp.to_numpy().astype(float), t.p0.to_numpy(), t.usd.to_numpy())
    return [{"cond": r.cond, "onset_ts": o[0], "dir": o[1], "size": o[2], "detect_ts": o[3]} for o in on]


if __name__ == "__main__":
    u = universe()
    u_is = u[~u.oos]
    u_is[["cond", "slug", "title", "series", "league", "start", "end", "res0", "volume", "other_volume",
          "fee_rate", "delay", "tok0", "tok1", "out0", "out1", "event_id"]].to_parquet(OUT / "universe_is.parquet")
    p = pd.read_parquet("data/is_prints.parquet")
    assert p.cond.isin(u_is.cond).all()
    p[p.bucket == "0-3s"].to_parquet(OUT / "prints_0_3s_is.parquet")
    wf, sh, bb = fasttier.walk_forward(p)
    sh.to_parquet(OUT / "shadow_is_uncapped.parquet")
    wf.to_csv(OUT / "walkforward_is.csv", index=False)
    with ProcessPoolExecutor(8) as ex:
        js = [x for part in ex.map(jumps, u_is.to_dict("records"), chunksize=32) for x in part]
    pd.DataFrame(js).to_parquet(OUT / "jumps_is.parquet")
    for f in sorted(OUT.iterdir()):
        print(f.name, f.stat().st_size // 1024, "KB")
