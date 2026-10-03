"""v2-safe in the forward window: the secondary variant promised by HYPOTHESIS_V2.md Amendment A2 and
research/v2/lowloss/PREREG.md (c). REPORTED, NOT TESTED. Paper only. Run ONCE, AFTER the pinned forward test.

    python scripts/forward_test_safe.py --plan                      # preconditions only: reads no market data,
                                                                    #   writes nothing (safe any time)
    python scripts/forward_test_safe.py --end <window end>          # the one real run; --end must equal
                                                                    #   results/v2/forward.json "window"[1]
    python scripts/forward_test_safe.py --dry --start 2026-09-01T00:00 --end 2026-09-03T00:00
                                                                    # plumbing on an old, already-seen window;
                                                                    #   not logged, nothing written (heavy: loads
                                                                    #   the full print history, ~12 GB)

Same data path as scripts/forward_test.py, which is imported UNCHANGED (window_universe, _prints, cluster_ci,
FWD_START). The rule: V2_SAFE = dataclasses.replace(src.v2.POLICY, name="v2_safe_n50", net_cap=50); nothing
else changes. The features are built once (the body of src.v2.run, copied line for line) and both policies are
simulated on them; the frozen-v2 trades must equal the pinned run's data/v2_forward_trades.parquet before any
v2-safe statistic is computed, otherwise the run stops (as scripts/lowloss_test.py checks its reference).

Reported (PREREG (c)): per share held to resolution with a match-clustered CI, $ P&L, profitable matches %,
worst match, and the 30 s net markout (primary B's statistic), for the full window and for the blind
sub-window of matches starting at or after 2026-10-03 18:00 UTC (the full window is labelled "includes matches
that started before v2-safe was frozen").

Log: one line in results/forward_peeks.log BEFORE any data is read (real run only).
Outputs (real run only): results/v2/forward_safe.json, data/v2_safe_forward_trades.parquet.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

BLIND_START = "2026-10-03T18:00"
FORWARD_JSON = ROOT / "results/v2/forward.json"
OUT_JSON = ROOT / "results/v2/forward_safe.json"
OUT_TRADES = ROOT / "data/v2_safe_forward_trades.parquet"
REF_TRADES = ROOT / "data/v2_forward_trades.parquet"
LOG = ROOT / "results/forward_peeks.log"
LABEL = ("v2-safe (frozen v2 with net cap 50), forward window; REPORTED, NOT TESTED (HYPOTHESIS_V2.md A2, "
         "research/v2/lowloss/PREREG.md (c)); paper only")


def policies():
    from src import v2
    return v2.POLICY, replace(v2.POLICY, name="v2_safe_n50", net_cap=50)


def preconditions(end: str | None, real: bool) -> dict:
    """What must hold before the real run. Reads only small JSON/parquet metadata, never market data."""
    v2p, safe = policies()
    out = {"policy_v2": v2p.name, "policy_v2_safe": safe.name, "net_cap_v2": v2p.net_cap,
           "net_cap_v2_safe": safe.net_cap,
           "only_net_cap_differs": all(getattr(safe, k) == getattr(v2p, k) for k in v2p.__dataclass_fields__
                                       if k not in ("name", "net_cap")),
           "forward_json_exists": FORWARD_JSON.exists(), "reference_trades_exist": REF_TRADES.exists(),
           "already_run": OUT_JSON.exists(), "problems": []}
    if not out["only_net_cap_differs"] or safe.net_cap != 50:
        out["problems"].append("V2_SAFE differs from the frozen v2 in more than the net cap")
    if real:
        if not out["forward_json_exists"]:
            out["problems"].append("results/v2/forward.json does not exist: run the pinned scripts/forward_test.py first")
        else:
            win = json.loads(FORWARD_JSON.read_text())["window"]
            out["forward_window"] = win
            if end is None:
                out["problems"].append(f"--end is required and must equal forward.json window[1] = {win[1]!r}")
            elif end != win[1]:
                out["problems"].append(f"--end {end!r} != forward.json window[1] {win[1]!r}")
        if not out["reference_trades_exist"]:
            out["problems"].append("data/v2_forward_trades.parquet (written by the pinned run) is missing")
        if out["already_run"]:
            out["problems"].append("results/v2/forward_safe.json exists: this is a one-shot run")
    return out


def run_both(allp, ends):
    """src.v2.run's body, copied line for line, with the last step done for both policies."""
    import pandas as pd
    from src import fasttier, v2
    from src.tiers import add_causal_bucket
    E = v2.E
    prints = allp if "bucket_c" in allp else add_causal_bucket(allp)
    bucket = "bucket_c"
    wf, sh, _ = fasttier.walk_forward(prints, bucket=bucket)
    f = v2.prepare(v2.build_features(sh, prints, ends))
    f["lock_end"] = f.ts + v2.LOCK_S
    p03 = prints[prints[bucket] == "0-3s"][["wallet", "ts", "mo30"]].copy()
    p03["month"] = pd.to_datetime(p03.ts, unit="s").dt.to_period("M").astype(str)
    out = {}
    for name, pol in zip(("v2", "v2_safe"), policies()):
        E._WCACHE.clear()
        out[name] = E.simulate(f, pol, "res", "actual", p03[["wallet", "month", "mo30"]])
    return out


def same_trades(a, b) -> bool:
    import numpy as np
    key = lambda d: d.sort_values(["cond", "ts", "shares"], kind="stable")[["shares", "pnl"]].to_numpy()  # noqa: E731
    return len(a) == len(b) and np.allclose(key(a), key(b), rtol=1e-9, atol=1e-9)


def report(ft, F) -> dict:
    import numpy as np
    if not len(ft):
        return {"v2_safe_trades": 0, "v2_safe_matches": 0}
    ft = ft.copy()
    if "pnl" not in ft:
        ft["pnl"] = ft.shares * ft.pnl_ps
    ft["m30_ps"] = ft.gross30 - (ft.gross_res - ft.pnl_ps)
    by_match = ft.groupby("cond").pnl.sum()
    return {"v2_safe_trades": int(len(ft)), "v2_safe_matches": int(ft.cond.nunique()),
            "per_share_res_c_cluster_ci": [round(100 * x, 3) for x in F.cluster_ci(ft, "pnl_ps")],
            "pnl_usd": round(float(ft.pnl.sum()), 2),
            "profitable_matches_share": round(float((by_match > 0).mean()), 4),
            "worst_match_usd": round(float(by_match.min()), 2),
            "m30_net_per_share_c_cluster_ci": [round(100 * x, 3) for x in F.cluster_ci(ft.dropna(subset=["m30_ps"]), "m30_ps")],
            "n_matches_for_power_note": int(len(by_match)),
            "max_abs_net_shares_any_match": float(np.nanmax(np.abs(ft.groupby("cond").shares.sum()))) if "shares" in ft else None}


def main(start: str, end: str | None, dry: bool, plan: bool, workers: int) -> int:
    real = not (dry or plan)
    pre = preconditions(end, real or plan)
    if plan:   # report what the real run would check; exit 0 so a preflight can show it before the pinned run
        print(json.dumps({"plan_only": True, "real_run_ready": not pre["problems"], **pre}, indent=1))
        return 0
    if real and pre["problems"]:
        print(json.dumps(pre, indent=1))
        sys.exit("refusing to run: " + "; ".join(pre["problems"]))
    import forward_test as F   # unchanged, sha-pinned
    import pandas as pd
    from src import polymarket as pm
    from src.tape import universe
    if real:
        assert start == F.FWD_START, "the pre-registered window starts at " + F.FWD_START
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} v2-safe forward run (HYPOTHESIS_V2 A2, "
                     f"reported not tested), window [{start}, {end})\n")
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now(tz="UTC")
    w = F.window_universe(start_ts, end_ts)
    print(f"window matches: {len(w)}", flush=True)
    pm.fetch_many_trades(w.cond.tolist(), workers=workers)
    with ProcessPoolExecutor(workers) as ex:
        fw = [d for d in ex.map(F._prints, w.to_dict("records"), chunksize=4) if d is not None]
    fw = pd.concat(fw, ignore_index=True)
    u = universe()
    hist = [pd.read_parquet("data/is_prints.parquet"), pd.read_parquet("data/locked/oos_prints.parquet")]
    hist = [h[~h.cond.isin(set(w.cond))] for h in hist]
    allp = pd.concat(hist + [fw], ignore_index=True)
    del hist
    ends = pd.concat([u.set_index("cond").end, w.set_index("cond").end])
    ends = ends[~ends.index.duplicated()]
    trs = run_both(allp, ends)
    inwin = set(w.cond)
    ft_v2 = trs["v2"][trs["v2"].cond.isin(inwin)].copy()
    ft = trs["v2_safe"][trs["v2_safe"].cond.isin(inwin)].copy()
    ref_ok = None
    if REF_TRADES.exists() and not dry:
        ref = pd.read_parquet(REF_TRADES, columns=["cond", "ts", "shares", "pnl"])
        ref_ok = same_trades(ref, ft_v2[["cond", "ts", "shares", "pnl"]])
        if not ref_ok:
            sys.exit("frozen-v2 trades differ from data/v2_forward_trades.parquet: stopping before any v2-safe statistic")
    blind = set(w.loc[w.start >= pd.Timestamp(BLIND_START, tz="UTC"), "cond"])
    out = {"label": LABEL, "window": [start, str(end_ts)], "matches_in_window": int(len(w)),
           "v2_reference_check": ("equal to data/v2_forward_trades.parquet" if ref_ok else
                                  "not checked (dry run)" if dry else "reference missing"),
           "full_window": {"note": "includes matches that started before v2-safe was frozen", **report(ft, F)},
           "blind_subwindow": {"start": BLIND_START, "matches_in_subwindow": int(len(blind)),
                               **report(ft[ft.cond.isin(blind)], F)},
           "frozen_v2_same_run": {"trades": int(len(ft_v2)), "pnl_usd": round(float(ft_v2.pnl.sum()), 2) if len(ft_v2) else 0.0},
           "power": "less than about a day of matches: no profitable-days share is claimed (PREREG (c))"}
    print(json.dumps(out, indent=2))
    if real:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(out, indent=2))
        ft.to_parquet(OUT_TRADES)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-10-03T14:00")
    ap.add_argument("--end", default=None)
    ap.add_argument("--dry", action="store_true", help="plumbing check on an old (already-seen) window; not logged")
    ap.add_argument("--plan", action="store_true", help="check preconditions only; reads no market data")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    sys.exit(main(a.start, a.end, a.dry, a.plan, a.workers))
