"""Post-hoc diagnostics after the single TT1-TT4 run. NOT pre-registered; changes no verdict.

    python research/tt/posthoc.py     # -> results/tt/posthoc.json (logged in results/tt/peeks.log and results/oos_peeks.log)

1. TT1 closing test: what the "closing" observation is. Size (USD) of the last pre-start fill, how long
   before the start it printed, and whether the taker bought the favourite or sold the underdog, by
   favourite-price group and league.
2. TT2: how far table tennis is from the fast-tier thresholds (>= 30 causal 0-3 s prints over >= 10
   matches before the month): the most active wallet in that bucket, before each evaluated month and
   over all months.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import tt_analyze as A  # noqa: E402  (chdir to ROOT, same loaders)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import tiers  # noqa: E402
from src.tape import load_tape  # noqa: E402


def closing_detail(U: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in U[U.res0.isin([0.0, 1.0])].itertuples():
        t = load_tape(r.cond)
        if t is None:
            continue
        s = int(r.start.timestamp())
        w = t[(t.timestamp >= s - 86_400) & (t.timestamp < s)]
        if len(w):
            x = w.iloc[-1]
            p = float(x.p0)
            fav0 = p >= 0.5
            rows.append({"cond": r.cond, "league": r.league, "p": p, "fav": max(p, 1 - p),
                         "won": float(r.res0) if fav0 else 1 - float(r.res0), "usd": float(x.usd),
                         "secs_before_start": s - int(x.timestamp),
                         "taker_bought_fav": bool(x.at_ask) == fav0, "prestart_fills": int(len(w)),
                         "prestart_usd": float(w.usd.sum())})
    return pd.DataFrame(rows)


def summarise(g: pd.DataFrame) -> dict:
    return {"matches": int(len(g)), "mean_fav": float(g.fav.mean()), "win_rate": float(g.won.mean()),
            "closing_print_usd_median": float(g.usd.median()), "closing_print_usd_p90": float(g.usd.quantile(0.9)),
            "share_closing_print_lt_5usd": float((g.usd < 5).mean()),
            "secs_before_start_median": float(g.secs_before_start.median()),
            "share_taker_bought_fav": float(g.taker_bought_fav.mean()),
            "prestart_fills_median": float(g.prestart_fills.median()),
            "prestart_usd_median": float(g.prestart_usd.median())}


def main():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    ref = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    what = "table tennis post-hoc diagnostics after TT1-TT4 (closing-print size, fast-tier distance; not pre-registered, no verdict change)"
    with A.LOG_TRACK.open("a") as f:
        f.write(f"{now} {what}\n")
    with A.LOG_TT.open("a") as f:
        f.write(f"{now} {what} commit={ref}\n")
    U, P = A.load()
    C = closing_detail(U)
    C["group"] = np.where(C.fav >= 0.8, "fav >= 0.80", "fav < 0.80")
    out = {"closing": {"ALL": summarise(C)}}
    for (lg, gr), g in C.groupby(["league", "group"]):
        out["closing"][f"{lg} / {gr}"] = summarise(g)
    for gr, g in C.groupby("group"):
        out["closing"][f"ALL / {gr}"] = summarise(g)
    Pc = tiers.add_causal_bucket(P)
    Pc["month"] = pd.to_datetime(Pc.ts, unit="s").dt.to_period("M").astype(str)
    b = Pc[Pc.bucket_c == "0-3s"]
    months = sorted(Pc.month.unique())
    dist = {}
    for m in months[2:]:
        past = b[b.month < m]
        g = past.groupby("wallet").agg(n=("ts", "size"), nm=("cond", "nunique"))
        dist[m] = {"bucket_prints_before": int(len(past)), "wallets": int(len(g)),
                   "max_prints_one_wallet": int(g.n.max()) if len(g) else 0,
                   "max_matches_one_wallet": int(g.nm.max()) if len(g) else 0}
    g = b.groupby("wallet").agg(n=("ts", "size"), nm=("cond", "nunique"))
    out["fast_tier_distance"] = {
        "thresholds": {"prints": 30, "matches": 10, "t": 3.0},
        "bucket_0_3s_prints_all_months": int(len(b)), "bucket_0_3s_matches_all_months": int(b.cond.nunique()),
        "wallets_in_bucket_all_months": int(len(g)),
        "max_prints_one_wallet_all_months": int(g.n.max()) if len(g) else 0,
        "max_matches_one_wallet_all_months": int(g.nm.max()) if len(g) else 0,
        "before_each_evaluated_month": dist}
    out["run"] = {"utc": now, "commit": ref, "label": "post-hoc, not pre-registered; no TT verdict changes"}
    (A.OUT / "posthoc.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
