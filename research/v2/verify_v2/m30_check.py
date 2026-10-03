"""Burned-OOS 30 s markout (the forward test's primary metric) for the rebuilt v2 book, split by
whether the print came before / in the same second as / after the jump detector fired, plus the
two stress tests. Uses rebuild.py outputs (run rebuild.py first). Burned OOS = match start >= cutoff.

    .venv/bin/python research/v2/verify_v2/m30_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rebuild as R  # noqa: E402  (this folder's own rebuild, not src/v2.py)

CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC").timestamp()


def ci(x: pd.DataFrame, col: str, weighted: bool, n_boot=2000, seed=0):
    x = x.dropna(subset=[col])
    w = x.shares if weighted else pd.Series(1.0, index=x.index)
    g = pd.DataFrame({"s": x[col] * w, "w": w, "cond": x.cond}).groupby("cond")[["s", "w"]].sum()
    s, ww = g.s.to_numpy(), g.w.to_numpy()
    idx = np.random.default_rng(seed).integers(0, len(g), (n_boot, len(g)))
    bs = s[idx].sum(1) / ww[idx].sum(1)
    return [round(100 * s.sum() / ww.sum(), 3), round(100 * np.percentile(bs, 2.5), 3), round(100 * np.percentile(bs, 97.5), 3)]


def summarize(x: pd.DataFrame, col: str = "net30") -> dict:
    return {"n": int(x[col].notna().sum()), "share_weighted_c": ci(x, col, True), "per_print_c": ci(x, col, False)}


def main():
    tr = pd.read_parquet(HERE / "out/isoos_trades.parquet")
    jumps = pd.read_parquet(HERE / "out/jumps_rebuilt.parquet")
    o = tr[tr.mstart >= CUT].reset_index(drop=True)
    o = R.attach_detect(o, jumps)
    o["net30"] = o.mo30 - o.fee_ps
    o["net30_tick"] = o.net30 - 0.01
    rel = np.sign(o.ts - o.detect_ts)
    out = {"v2_burned_oos": summarize(o),
           "pre_detect": summarize(o[rel < 0]), "same_second": summarize(o[rel == 0]), "after_detect": summarize(o[rel > 0]),
           "at_or_after_detect_posthoc": summarize(o[rel >= 0]),
           "stress_i_tick": summarize(o, "net30_tick")}
    # stress (ii) as a policy: re-run the sequential caps with only at/after-detect prints eligible
    u = R.universe()
    start_ts = pd.Series(u.start.map(lambda x: x.timestamp()).to_numpy(), index=u.cond.to_numpy())
    d = R.prep(pd.concat([R.load_03(R.IS_PATH, "is"), R.load_03(R.OOS_PATH, "oos")], ignore_index=True))
    c, _ = R.build_candidates(d, "matches", "match")
    c = R.attach_detect(c, jumps)
    for name, elig in (("stress_ii_policy_at_or_after", c.ts >= c.detect_ts), ("stress_ii_policy_strict_after", c.ts > c.detect_ts)):
        t2 = R.sequential(c, eligible=elig.to_numpy())
        t2 = t2[t2.cond.map(start_ts) >= CUT].copy()
        t2["net30"] = t2.mo30 - t2.fee_ps
        out[name] = summarize(t2)
        t2["net30_tick"] = t2.net30 - 0.01
        out[name + "_plus_tick"] = summarize(t2, "net30_tick")
    for k, v in out.items():
        print(f"{k:40s}", v)
    (HERE / "out/m30_check.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
