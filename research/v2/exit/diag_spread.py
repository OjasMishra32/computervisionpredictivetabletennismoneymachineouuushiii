"""Diagnostic: tape spread proxy at each touch-model maker fill, and P&L by spread state.

Is "quote one tick inside" feasible (needs spread >= 2 ticks at the fill)? And does the improve1g gate
act as a hidden directional filter (crossed proxies = stale opposite print in a moving market)?

    .venv/bin/python research/v2/exit/diag_spread.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from research.v2.exit.sim_exit import _tape, SPREAD_STALE  # noqa: E402

CACHE = ROOT / "data" / "v2_exit"
HERE = Path(__file__).resolve().parent
CELLS = [(5, 60), (30, 300)]


def one(job):
    cond, f, start, end = job
    t = _tape(cond, start, end)
    if t is None:
        return None
    ts, p, ask = t.timestamp.to_numpy(), t.p0.to_numpy(), t.at_ask.to_numpy()
    out = []
    for s in (True, False):
        g = f[(f.dir > 0) == s]
        if g.empty:
            continue
        ot, op = ts[ask != s], p[ask != s]
        tf = (g.ts + g.dt).to_numpy()
        if len(ot) == 0:
            sp = np.full(len(g), np.nan)
            age = np.full(len(g), np.nan)
        else:
            k = np.searchsorted(ot, tf, "right") - 1
            age = np.where(k >= 0, tf - ot[np.maximum(k, 0)], np.nan)
            o = op[np.maximum(k, 0)]
            sp = np.where(k >= 0, (g.px - o) if s else (o - g.px), np.nan)
        out.append(pd.DataFrame({"eid": g.eid.to_numpy(), "H": g.H.to_numpy(), "T": g["T"].to_numpy(),
                                 "spread": sp, "age": age}))
    return pd.concat(out) if out else None


def main():
    ent = pd.read_parquet(CACHE / "entries.parquet")
    mk = pd.read_parquet(CACHE / "maker.parquet", filters=[("sizing", "==", 0), ("model", "==", 0)])
    mk = mk[mk.filled & mk[["H", "T"]].apply(tuple, axis=1).isin(CELLS)]
    e = ent[["eid", "cond", "ts", "dir", "p", "fee", "tick", "regime"]] if "regime" in ent else ent.assign(
        fee=ent.fee_rate * ent.p * (1 - ent.p),
        regime=ent.delay.astype(str) + "s/" + (ent.fee_rate * 100).round().astype(int).astype(str) + "%")[
        ["eid", "cond", "ts", "dir", "p", "fee", "tick", "regime"]]
    f = mk.merge(e, on="eid")
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["cond", "start", "end"]).set_index("cond")
    jobs = [(c, g, u.at[c, "start"], u.at[c, "end"]) for c, g in f.groupby("cond")]
    with ProcessPoolExecutor(2) as ex:
        parts = [x for x in ex.map(one, jobs, chunksize=16) if x is not None]
    d = pd.concat(parts).merge(f, on=["eid", "H", "T"])
    tk = d.tick
    d["state"] = np.select([d.spread.isna() | (d.age > SPREAD_STALE), d.spread < 0, d.spread < 2 * tk - 1e-9],
                           ["unknown/stale", "crossed", "narrow (<2 ticks)"], "room (>=2 ticks)")
    d["pnl_ps_touch_c"] = (d.dir * (d.px - d.p) - d.fee) * 100
    rows = []
    for (H, T), g in d.groupby(["H", "T"]):
        for reg, h in [("all", g), ("1s/5%", g[g.regime == "1s/5%"])]:
            for st, q in h.groupby("state"):
                rows.append({"H": H, "T": T, "regime": reg, "state": st, "share": len(q) / len(h), "n": len(q),
                             "touch_fill_pnl_c": q.pnl_ps_touch_c.mean(), "median_spread_ticks": (q.spread / q.tick).median()})
    out = pd.DataFrame(rows)
    (HERE / "tables").mkdir(exist_ok=True)
    out.to_csv(HERE / "tables" / "diag_spread_at_fill.csv", index=False)
    print(out.round(3).to_string())


if __name__ == "__main__":
    main()
