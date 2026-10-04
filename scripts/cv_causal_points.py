"""CAUSAL EVERY-POINT CV BOOK (review fix D2, 2026-10-04).

    assumed data: licensed feed/video not purchased; parameters measured.

    python scripts/cv_causal_points.py                  # IS only -> results/tier0/causal_points.json
    python scripts/cv_causal_points.py --oos            # IS + OOS (reads data/locked/oos_prints.parquet once; logged)
    python scripts/cv_causal_points.py --smoke          # 2 seeds, IS, print only
    add --workers N to run seeds in parallel (same results)

WHY. Every CV P&L number before this script came from src/tier0.simulate on jump_table(): only the historical
>= 4c jumps, selected on the realised future move and traded in its realised direction. That is a conditional
benchmark, not a book anyone could trade. Those results are kept unchanged and labelled as such
(src/tier0.TRADE_SET_LABEL['jumps']). This script runs the SAME simulator (src/tier0.py, same timing, fees, fills,
net cap, coverage) on the causal trade set src/tier0.point_table():

  * every point of every covered match, including points that do not move the price and calls that lose;
  * which matches: the 10 per UTC day with the highest PRE-START volume (coverage_set, ex-ante);
  * the call: the frozen call model's MEASURED held-out streaming behaviour (src/tier0.engine_cv_system:
    recall/precision by lead from results/engine/online_vs_offline.json, false calls per hour after the a-priori
    2 s rally gate from results/engine/rally_gate_eval.json; models/vision/frozen_call_model.pkl is hashed, not
    refit). Missed early calls are called at the event with precision p_event, as in the committed model. False
    calls are traded as phantom orders that buy the called token at its stale price + half the spread;
  * direction: the classifier's call of the point winner; historical point winners are unknown, so the winner is
    a fair coin independent of every price, and the call is right with the measured precision;
  * size: $1,000 orders, depth scaled by the ex-ante match size (pre-start volume x the IS median final/pre-start
    ratio), share cap at the resting depth (capacity verifier's fix), net cap 100 shares a match;
  * latency: licensed video delay V = 0.5 s (first, the main scenario), 1 s, 3 s, plus CV inference, the
    venue->London network, the gateway and the venue's 1 s order delay (unchanged tier-0 timing model);
  * live pool = all 482 measured live points (non-moving points included), not only the >= 3c ones.

No price at or after a point selects, signs or sizes an order (tests/test_cv_causal.py). Fills are still priced
off the post-point price and the measured live book, so the P&L is an UPPER BOUND on fills.

Readings of the reprice timing (as the latency sweep): tournament_L2.0 (Table 1's reading, stamp lag 2.0 s),
point_L2.0 (the fully pre-registered timing: R drawn per point), tournament_L3.14 (post hoc: the calibrated stamp
lag 3.14 s). Sensitivities on tournament_L2.0: the committed fill model, no false calls, the ungated engine, and
the offline own120 call table without false calls (the reviewers' IS approximation).

Halts: the paper states the false-call halt as a rule but does not claim it ran in the backtest, so it is NOT
simulated here (a proposed deployment control). The paper does say the daily stop never fired in sample, so
every cell reports how often a $1,000 daily stop on marked P&L (src/tier0.daily_stop) would fire, and the
metrics with it applied.

Frozen before any OOS run by the commit of this file: cells, seeds (0..19), metrics and the primary cell
(tournament_L2.0, V = 0.5 s, engine call model with the 2 s gate). Nothing is tuned on its results.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from scripts import tier0_latency_sweep as LS  # noqa: E402
from src import tier0 as T  # noqa: E402

LABEL = "assumed data: licensed feed/video not purchased; parameters measured"
OUT = T.OUT / "causal_points.json"
SEEDS = 20
SEED_BASE = {"IS": 0, "OOS": 1000}       # as tier0_backtest (IS 0, OOS 1000)
V_LIST = [0.5, 1.0, 3.0]                # 0.5 s first: the main licensed-feed scenario
READINGS = {"tournament_L2.0": ("tournament", None), "point_L2.0": ("tournament", "point"),
            "tournament_L3.14": ("tournament_lagcal", None)}
PRIMARY = "engine|tournament_L2.0|V0.5"
CV = "engine_online"
SENS = {   # name -> (cv table, false-call rate key, Scenario overrides)
    "engine": (CV, "gated", {}),
    "committed_fills": (CV, "gated", {"depth_cap": False, "extrap": "all", "vol_src": "final"}),
    "no_false_calls": (CV, "none", {}),
    "ungated": ("engine_online_ungated", "ungated", {}),
    "own120_ref": ("own120", "none", {"depth_cap": False, "extrap": "all", "vol_src": "final"}),
}
BASE = {"pool": "all", "vol_src": "prestart", "depth_cap": True, "extrap": "linear"}
DAILY_STOP_USD = 1000.0


def cells() -> list[tuple[str, str, float]]:
    out = [("engine", rd, v) for rd in READINGS for v in V_LIST]
    out += [(s, "tournament_L2.0", v) for s in SENS if s != "engine" for v in V_LIST]
    return out


def _log_read(desc: str) -> None:
    try:
        from src.readlog import log_read  # added by the reproduction workstream
        log_read(desc)
        return
    except ImportError:
        pass
    f = ROOT / ("results/repro/reads.log" if os.environ.get("COURTSIDE_REPRO") == "1" else "results/oos_peeks.log")
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a") as fh:
        fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} {desc}\n")


def context(periods: list[str], log: bool = True) -> dict:
    """Universe, coverage and covered in-play prints per period. Only IS files unless 'OOS' is in periods."""
    from src.tape import universe
    u = universe()
    v = T.prestart_volume(sorted(u.cond))
    u["prestart_usd"] = u.cond.map(v).fillna(0.0)
    tour = T.tournament_codes(u)
    M = u.reset_index(drop=True)
    cov = T.coverage_set(M, T.CORRECTED.coverage, T.CORRECTED.regime)
    vmult = T.exante_volume_multiplier(u)
    eng = T.engine_cv_system(T.ENGINE_GATE_S)
    eng_u = T.engine_cv_system("none")
    cvs = dict(T.cv_systems())
    cvs[CV] = eng
    cvs["engine_online_ungated"] = eng_u
    c = {"u": u, "M": M, "tour": tour, "cov": cov, "vmult": vmult, "gap_s": T.point_gap_s(),
         "pools": {p: T.live_points(p) for p in ("D>=3c", "all")}, "cvs": cvs, "mix": T.point_mix(),
         "calib": T.calibrate_stamp_lag(), "n_tour": int(tour.max()) + 1,
         "phantom": {"gated": eng["phantom_per_h"], "ungated": eng_u["phantom_per_h"], "none": 0.0}, "prints": {}}
    for per in periods:
        oos = per == "OOS"
        conds = set(u.cond[(u.oos == oos) & u.cond.isin(cov)])
        if oos:
            if log:     # spawned workers re-load the file the main process already logged
                _log_read("cv_causal_points: OOS in-play prints of covered matches read for the causal every-point "
                          "CV book (review fix D2; non-blind period; frozen code)")
            path = ROOT / "data/locked/oos_prints.parquet"
        else:
            path = ROOT / "data/is_prints.parquet"
        pr = pd.read_parquet(path, columns=["cond", "ts", "p", "usd"])
        pr["cond"] = pr.cond.astype(str)
        c["prints"][per] = pr[pr.cond.isin(conds)].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    return c


def scenario(sens: str, reading: str, V: float, c: dict) -> tuple[T.Scenario, dict]:
    cv, _, over = SENS[sens]
    base_rd, r_mode = READINGS[reading]
    sc, cvs = LS.cell("video", base_rd, V, cv, c)
    sc = replace(sc, **BASE)
    if r_mode:
        sc = replace(sc, r_mode=r_mode)
    return replace(sc, **over), cvs


def extra(calls: pd.DataFrame, days: pd.DatetimeIndex, m: dict) -> dict:
    """Return/vol/turnover/fees-x2 on top of tier0.metrics (same daily series)."""
    tr = calls[calls.shares > 1e-9]
    if tr.empty:
        return {}
    daily = tr.groupby("date").pnl.sum().reindex(days, fill_value=0.0)
    cap = m.get("capital_usd") or np.nan
    n_days = len(days)
    fee = float((tr.shares * tr.fee_ps).sum())
    return {"vol_ann_usd": float(daily.std() * np.sqrt(365)),
            "vol_ann_pct_capital": float(daily.std() * np.sqrt(365) / cap * 100) if cap else np.nan,
            "turnover_x_per_year": float(tr.usd_in.sum() / cap * 365 / n_days) if cap else np.nan,
            "fees_usd": fee, "per_share_c_fees_x2": float((tr.pnl.sum() - fee) / tr.shares.sum() * 100),
            "pnl_per_day_usd_fees_x2": float((tr.pnl.sum() - fee) / n_days)}


def run_seed(c: dict, per: str, seed: int, todo: list[tuple[str, str, float]]) -> list[dict]:
    s = SEED_BASE[per] + seed
    tables = {}
    rows = []
    for sens, rd, V in todo:
        ph_key = SENS[sens][1]
        if ph_key not in tables:
            P = T.point_table(c["prints"][per], c["u"], c["gap_s"], s, c["phantom"][ph_key], vol_mult=c["vmult"])
            P["tour"] = P.cond.map(c["tour"]).astype(int)
            tables[ph_key] = (P, T.point_draws(P, s, max(c["n_tour"], 1)), T.period_days(P, "delay1"))
        P, dr, days = tables[ph_key]
        sc, cvs = scenario(sens, rd, V, c)
        calls = T.simulate(P, c["M"], sc, dr, c["pools"], cvs, c["mix"])
        m = T.metrics(calls, days)
        m.update(extra(calls, days, m))
        kept, fired = T.daily_stop(calls, DAILY_STOP_USD)
        ms = T.metrics(kept, days) if fired else m
        row = {"sens": sens, "reading": rd, "V": V, "period": per, "seed": seed,
               "n_points": int((~P.phantom).sum()), "n_phantom_calls": int(P.phantom.sum()),
               "n_matches": int(P.cond.nunique()),
               "daily_stop_days_fired": fired, "stop_pnl_per_day_usd": ms.get("pnl_per_day_usd", 0.0),
               "stop_sharpe_ann": ms.get("sharpe_ann", np.nan), "stop_per_share_c": ms.get("per_share_c", np.nan)}
        for k, val in m.items():
            if isinstance(val, (list, tuple)):
                row[f"{k}_lo"], row[f"{k}_hi"] = float(val[0]), float(val[1])
            elif isinstance(val, (int, float, np.integer, np.floating)):
                row[k] = float(val)
        rows.append(row)
    return rows


SUMMARY = ["pnl_per_day_usd", "sharpe_ann", "per_share_c", "n_trades", "n_calls", "wrong_call_share_of_trades",
           "n_trades_phantom", "pnl_phantom_usd", "pnl_correct_usd", "pnl_wrong_usd", "max_dd_usd", "worst_day_usd",
           "capital_usd", "return_on_capital_ann_pct", "vol_ann_usd", "vol_ann_pct_capital", "turnover_x_per_year",
           "per_share_c_fees_x2", "pnl_per_day_usd_fees_x2", "calls_share_before_reprice", "calls_median_tau_s",
           "fill_rate", "days", "n_points", "n_phantom_calls", "n_matches", "daily_stop_days_fired",
           "stop_pnl_per_day_usd", "stop_sharpe_ann", "stop_per_share_c"]


def summarise(rows: list[dict]) -> dict:
    S = pd.DataFrame(rows)
    out = {}
    for (sens, rd, V, per), g in S.groupby(["sens", "reading", "V", "period"], sort=False):
        g = g.sort_values("seed")
        mean = {k: round(float(g[k].mean()), 4) for k in SUMMARY if k in g}
        sd = {k: round(float(g[k].std(ddof=0)), 4) for k in ("pnl_per_day_usd", "sharpe_ann", "per_share_c") if k in g}
        s0 = g.iloc[0]
        days = float(s0.get("days", np.nan))
        ci = {"per_share_c_ci95_seed0": [round(float(s0.get("per_share_ci95_c_lo", np.nan)), 4),
                                         round(float(s0.get("per_share_ci95_c_hi", np.nan)), 4)],
              "pnl_per_day_usd_ci95_seed0": [round(float(s0.get("pnl_ci95_usd_lo", np.nan)) / days, 4),
                                             round(float(s0.get("pnl_ci95_usd_hi", np.nan)) / days, 4)],
              "ci_note": "95 % match bootstrap of the seed-0 draw (data uncertainty); sd = spread over the 20 seeds"}
        out[f"{sens}|{rd}|V{V:g}|{per}"] = {"sens": sens, "reading": rd, "V_s": V, "period": per,
                                             "n_seeds": int(len(g)), "mean": mean, "sd": sd, **ci}
    return out


_C: dict = {}


def _init(periods: list[str]) -> None:
    # spawned worker: load its own copy (pyarrow-backed pandas is not fork-safe)
    import warnings
    warnings.filterwarnings("ignore")
    _C.update(context(periods, log=False))


def _job(args: tuple[str, int]) -> list[dict]:
    per, s = args
    return run_seed(_C, per, s, cells())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oos", action="store_true", help="also run the OOS period (one logged read)")
    ap.add_argument("--smoke", action="store_true", help="2 seeds, IS, print only")
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--workers", type=int, default=1, help="seeds in parallel (spawned processes, ~1.5 GB each); "
                    "results do not depend on it")
    a = ap.parse_args()
    periods = ["IS", "OOS"] if a.oos else ["IS"]
    seeds = 2 if a.smoke else a.seeds
    t0 = time.time()
    c = context(periods)            # logs the one OOS read (workers re-load the same files without re-logging)
    _C.update(c)
    jobs = [(per, s) for per in periods for s in range(seeds)]
    rows = []
    if a.workers > 1:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(a.workers, mp_context=mp.get_context("spawn"), initializer=_init,
                                 initargs=(periods,)) as ex:
            for j, r in zip(jobs, ex.map(_job, jobs)):
                rows += r
                print(f"{j[0]} seed {j[1]} done ({time.time() - t0:.0f} s)", flush=True)
    else:
        for j in jobs:
            rows += _job(j)
            print(f"{j[0]} seed {j[1]} done ({time.time() - t0:.0f} s)", flush=True)
    res = summarise(rows)
    for k, v in res.items():
        m = v["mean"]
        print(f"{k:45s} $/day {m['pnl_per_day_usd']:9.2f}  Sharpe {m.get('sharpe_ann', np.nan):6.2f}  "
              f"c/share {m.get('per_share_c', np.nan):7.3f}  trades {m.get('n_trades', 0):8.0f}  "
              f"wrong {m.get('wrong_call_share_of_trades', np.nan):.3f}  stops {m['daily_stop_days_fired']:.1f}")
    if a.smoke:
        return
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        head = None
    eng = c["cvs"][CV]
    out = {
        "schema": "courtside.cv.points/1", "label": LABEL, "trade_set": T.TRADE_SET_LABEL["points"],
        "kind": "sim_upper_bound",
        "fills": "priced off the post-point 30 s VWAP and the measured live book (an upper bound on fills)",
        "git_head": head, "generated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "periods": periods, "seeds": seeds, "seed_base": SEED_BASE, "primary_cell": PRIMARY,
        "gap_s": round(c["gap_s"], 3), "vol_exante_multiplier_is": round(c["vmult"], 4),
        "base_scenario": asdict(scenario("engine", "tournament_L2.0", 0.5, c)[0]),
        "sensitivities": {k: {"cv": v[0], "false_calls": v[1], "overrides": v[2]} for k, v in SENS.items()},
        "readings": {k: {"latency_sweep_reading": v[0], "r_mode": v[1] or "tournament"} for k, v in READINGS.items()},
        "call_model": {"source": "frozen call model, measured held-out streaming behaviour (engine_cv_system)",
                       "gate": eng["gate"], "recall_by_lead": dict(zip(map(str, eng["leads_ms"]),
                                                                       [r[0] for r in eng["recall"]])),
                       "precision_by_lead": dict(zip(map(str, eng["leads_ms"]), eng["precision"])),
                       "precision_n": eng["precision_n"], "false_calls_per_h": eng["phantom_per_h"],
                       "false_calls_n": eng["phantom_n"], "false_calls_video_s": eng["phantom_video_s"],
                       "false_calls_per_h_ci95_poisson": eng["phantom_per_h_ci95"],
                       "false_calls_per_h_ungated": c["phantom"]["ungated"], "p_event_lead0": T.CORRECTED.p_event,
                       "inputs_sha256": eng["inputs"]},
        "halts": {"false_call_halt": "not simulated: the paper states it as a rule but does not claim it ran in the "
                                     "backtest; a proposed deployment control",
                  "daily_stop": f"${DAILY_STOP_USD:,.0f} on marked day P&L (src/tier0.daily_stop); "
                                "days fired and metrics with the stop are in every cell"},
        "benchmark": {"trade_set": T.TRADE_SET_LABEL["jumps"],
                      "files": ["results/tier0/results.json", "results/tier0/latency_sweep.json",
                                "results/tier0/latency_sweep.csv", "results/tier0/cost_turnover.json"],
                      "note": "committed jump-set results, unchanged; conditional benchmark only"},
        "cells": res,
        "seconds": round(time.time() - t0, 1),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1, default=float))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
