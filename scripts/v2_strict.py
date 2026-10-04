"""v2 with executable timing (defect D1), plus the executable copier.

    .venv/bin/python scripts/v2_strict.py                 # IS only (data/is_prints.parquet); no held-out data
    .venv/bin/python scripts/v2_strict.py --oos           # IS + burned OOS; ONE run, in Recompute only
      -> results/v2/strict_causal.json (schema courtside.v2.strict/1); --out to write elsewhere

What it computes
  0. The frozen rule T3e (src.v2.run causal=True, strict=False) is re-run and checked against
     results/v2/causal.json (n_trades and per-share of every period run): the frozen path is unchanged.
  1. Strict labels (src.v2.strict_causal_bucket): a print counts as after a detection only if it
     is known to come after the print that fired the detector. Tape timestamps are whole-second block times
     and the public tapes carry no block, transaction or log index, so the order inside a second is unknown
     and the whole detection second is excluded (0 < ts - detect <= 3 s; the verifiers' T3f definition).
     Wallet qualification, wallet filter and book are re-derived on these labels.
  2. IS / OOS blocks: the strict book priced at the fast tier's OWN fills. Observational event study, not
     attainable by anyone who reacts to the fast print.
  3. copier block: the same strict trades and share counts re-priced as a copier that learns of the fast
     print from the chain at its block time, sends a taker order over the network leg, waits the taker hold
     and meets the book block-lag later: tau = max(ts_f, detect second) + N + D + L (src.v2.copier_fill).
     Latency inputs are the repo's measurements (results/decay/decay.json::latency_inputs): block lag
     median / p90 and the Florida network leg. central = median lag, first same-side print at/after tau;
     harsh = p90 lag; optimistic = last same-side print at/before tau (upper bound). Copier price impact is
     ignored (generous).
  4. same_second_share_of_old_pnl: the share of the frozen T3e P&L (and trades) in the detection second.
No parameter, threshold or rule is chosen here; the frozen sizing policy G_50pct_net100 is used unchanged.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)                                    # src.polymarket reads tapes under the relative path data/raw
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore", category=RuntimeWarning)

from src import v2  # noqa: E402
from src.tape import universe  # noqa: E402
from src.tiers import add_causal_bucket  # noqa: E402

SCHEMA = "courtside.v2.strict/1"
RULE = ("prints with ts > detection second (the print that fires the detector, prints before it and the rest of "
        "its second are excluded because second-resolution block times cannot order them); 0-3 s window = "
        "0 < ts - detect <= 3; qualification, filter and book re-derived")
LABEL_EVENT = ("event study at the fast tier's own fills on strict labels (observational; a copier cannot get "
               "these prices)")
LABEL_COPIER = ("executable copier on the strict trades: acts after the fast print plus network leg, taker hold "
                "and block lag; same shares; copier price impact ignored")
KEEP = ("n_trades", "n_matches", "c_share", "c_share_ci95", "usd_day", "sharpe", "ret_ann", "vol_ann",
        "max_dd_usd", "turnover_x", "fees_x2_c_share", "total_pnl_usd", "total_pnl_ci_usd", "usd_traded",
        "capital_usd", "max_dd_pct", "worst_day_usd", "months_positive", "months_total", "days")


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except Exception:
        return "unknown"


def log_oos_read(desc: str) -> None:
    """One UTC line per held-out read, before the read (COURTSIDE_REPRO=1 -> results/repro/reads.log)."""
    try:
        from src.readlog import log_read  # shared helper, when present
        log_read(desc)
        return
    except ImportError:
        pass
    path = ROOT / ("results/repro/reads.log" if os.environ.get("COURTSIDE_REPRO") == "1" else "results/oos_peeks.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} {desc}\n")


def pick(m: dict) -> dict:
    return {k: m[k] for k in KEEP if k in m}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos", action="store_true", help="also read the burned OOS prints (Recompute only, once)")
    ap.add_argument("--out", default="results/v2/strict_causal.json")
    ap.add_argument("--trades", default=None, help="optional parquet path for the strict trades + copier prices")
    a = ap.parse_args()

    u = universe()
    oos_conds = set(u.loc[u.oos, "cond"])
    ends = u.set_index("cond").end
    p = pd.read_parquet("data/is_prints.parquet")
    periods = {"IS": lambda t: t[~t.cond.isin(oos_conds)]}
    if a.oos:
        log_oos_read(f"v2_strict.py (HEAD {git_head()[:7]}): v2 strict executable timing + copier on burned OOS "
                     "(non-blind; defect fix D1 after review)")
        p = pd.concat([p, pd.read_parquet("data/locked/oos_prints.parquet")], ignore_index=True)
        periods["OOS"] = lambda t: t[t.cond.isin(oos_conds)]
    print(f"prints {len(p):,}", flush=True)

    p = add_causal_bucket(p)                       # frozen labels (T3e)
    p = v2.strict_causal_bucket(p)                 # executable labels
    print("labels done", flush=True)

    # 0. frozen rule reproduction
    tr0, _ = v2.run(p, ends, causal=True)
    ref = json.loads((ROOT / "results/v2/causal.json").read_text())
    ref_key = {"IS": "causal/is_eval/slip0.0", "OOS": "causal/burned_oos/slip0.0"}
    frozen, old_share = {}, {}
    for per, sel in periods.items():
        part = sel(tr0)
        m = v2.E.metrics(part)
        r = ref[ref_key[per]]
        frozen[per] = {"n_trades": m["n_trades"], "per_share_c": m["per_share_c"],
                       "reference_n_trades": r["n_trades"], "reference_per_share_c": r["per_share_c"],
                       "equal": bool(m["n_trades"] == r["n_trades"]
                                     and abs(m["per_share_c"] - r["per_share_c"]) < 1e-9)}
        ev = part[part.month >= v2.E.EVAL_START]
        same = ev.since_det == 0
        old_share[per] = {"pnl": float(ev.pnl[same].sum() / ev.pnl.sum()),
                          "trades": float(same.mean()),
                          "pnl_usd_detection_second": float(ev.pnl[same].sum()),
                          "pnl_usd_total": float(ev.pnl.sum())}
        print(f"frozen T3e {per}: {frozen[per]}", flush=True)
        print(f"  share of T3e P&L in the detection second {per}: {old_share[per]}", flush=True)

    # 1-2. strict book at the fast tier's own fills
    tr1, wf1 = v2.run(p, ends, causal=True, strict=True)
    out_periods = {}
    for per, sel in periods.items():
        m = v2.table1_metrics(sel(tr1))
        out_periods[per] = {"label": LABEL_EVENT, **pick(m), "same_second_share_of_old_pnl": old_share[per]["pnl"],
                            "same_second_share_of_old_trades": old_share[per]["trades"]}
        print(f"strict event study {per}: {pick(m)}", flush=True)
    assert (tr1.ts > tr1.det_ts_s).all(), "a strict trade sits at or before its detection second"

    # 3. executable copier
    lat_in = json.loads((ROOT / "results/decay/decay.json").read_text())["latency_inputs"]
    blk = lat_in["block_lag_s"]
    lat = {"median": float(blk["median"]), "p90": float(blk["p90"]), "net_s": float(lat_in["net_florida_s"])}
    ev1 = tr1[tr1.month >= v2.E.EVAL_START].copy()
    cp = v2.copier_reprice(ev1, u.set_index("cond"), lat)
    ev1 = ev1.join(cp)
    for r, spec in v2.COPIER_RULES.items():
        if spec["price"] == "next_same":
            ok = ev1[f"same_{r}"]
            assert (ev1.loc[ok, f"fill_ts_{r}"] > ev1.loc[ok, "ts"]).all(), r
    copier = {}
    for r, spec in v2.COPIER_RULES.items():
        copier[r] = {"what": spec["what"]}
        for per, sel in periods.items():
            b = v2.copier_book(sel(ev1), r)
            m = v2.table1_metrics(b)
            cost = (b.dir * (b[f"c0_{r}"] - b.p) * b.shares).sum() / b.shares.sum() * 100
            copier[r][per] = {**pick(m),
                              "entry_cost_vs_fast_fill_c_share_weighted": float(cost),
                              "share_same_side_print": float(b[f"same_{r}"].mean()),
                              "share_beyond_tape_end": float(b[f"beyond_{r}"].mean()),
                              "median_tau_minus_fast_print_s": float((b[f"tau_{r}"] - b.ts).median())}
            print(f"copier {r} {per}: {copier[r][per]}", flush=True)
    if a.trades:
        ev1.to_parquet(a.trades)

    raw_cols = list(pd.read_parquet(next((ROOT / "data/raw/trades").glob("*.parquet"))).columns)
    res = {
        "schema": SCHEMA,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git_head": git_head(),
        "periods_run": list(periods),
        "rule": RULE,
        "labels": {"IS": LABEL_EVENT, "OOS": LABEL_EVENT, "copier": LABEL_COPIER,
                   "frozen_T3e": "unchanged frozen rule at the fast tier's own fills (event study); reproduced here"},
        "tape_order": {"raw_tape_columns": raw_cols, "order_col": None,
                       "note": "no block, transaction or log index in the public tapes, so prints inside one "
                               "second cannot be ordered; the whole detection second is excluded"},
        "timing": {"tau": "max(fast print block time, detection second) + network leg + taker hold (trade delay) "
                          "+ block lag", "block_lag_s": {"median": lat["median"], "p90": lat["p90"], "n": blk["n"]},
                   "net_s": lat["net_s"], "taker_hold_s": "trade's own `delay` (3 s before May 2026, 1 s after)",
                   "source": "results/decay/decay.json::latency_inputs (block_lag_s, net_florida_s)"},
        "frozen_T3e_reproduction": frozen,
        "same_second_share_of_old": old_share,
        **out_periods,
        "copier": copier,
        "n_wallets_by_month_strict": dict(zip(wf1.month, wf1.n_wallets.astype(int))),
    }
    if "OOS" not in periods:
        res["OOS_status"] = "not run: IS-only invocation (the held-out run is one --oos invocation in Recompute)"
    out = ROOT / a.out if not Path(a.out).is_absolute() else Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, default=float))
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
