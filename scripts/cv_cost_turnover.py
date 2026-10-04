"""Turnover, cost in bps and the fees-doubled result for the CV trader's published Table-2 cells (analysis only;
no rule, parameter or threshold is chosen here).

    .venv/bin/python scripts/cv_cost_turnover.py      # ~5 min, 1 process -> results/tier0/cost_turnover.json

SIMULATED, assumed feed latency (licensed feed not purchased); parameters measured. Trades are past points where the
price later moved >= 4c: selected on outcomes, not ex ante.

What it does
  The paper prints a Sharpe ratio for the CV trader at feed delays V = 0.5 / 1 / 3 s under two stamp-lag readings
  (pre-registered `tournament`, 2.0 s; post hoc `tournament_lagcal`, 3.14 s), in sample and on the burned OOS. The
  organizers ask, for every such book, for annualised return, volatility, max drawdown, TURNOVER and the result with
  costs doubled. The latency sweep (scripts/tier0_latency_sweep.py) kept P&L, Sharpe, drawdown and capital per seed
  but not the dollars traded or the fees paid. This script re-runs exactly those 12 cells x 20 seeds with the sweep's
  own code (tier0_latency_sweep.cell, src/tier0.simulate) and asserts every seed's P&L, Sharpe, max drawdown and
  capital equal results/tier0/latency_sweep_seeds.csv. Then, per seed:
    annual return  = P&L / days x 365 / capital          (capital = 3 x peak dollars locked, as the paper)
                     (the paper prints ratio_of_seed_means: seed-mean dollars over seed-mean capital, so the sign of
                     the return follows the sign of the mean $ a day; per-seed ratios are kept as well)
    volatility     = sd(daily P&L, every calendar day, zero-filled) x sqrt(365) / capital
    max drawdown   = max_dd_usd / capital
    turnover       = dollars traded / capital x 365 / days                (x capital a year)
    fee bps        = taker fees / dollars traded x 10,000                (fee r q (1 - q) a share, the venue's
                                                                          published per-match rate)
    fees x 2       = P&L - taker fees (each fill pays its fee twice); also as cents a share and a Sharpe ratio
  and reports the mean over the 20 seeds (the paper's convention for every CV number). The fill price itself walks
  the measured stale book (src/tier0.py, DEVIATIONS V1/V2), so there is no separate spread charge to double.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)                                   # src.polymarket reads tapes under the relative path data/raw
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")

OUT = ROOT / "results/tier0/cost_turnover.json"
READINGS = {"pre": "tournament", "cal": "tournament_lagcal"}
DELAYS = {"v05": 0.5, "v1": 1.0, "v3": 3.0}
PERIODS = {"is": "IS", "oos": "burned_OOS"}
SEEDS = 20
ANN = np.sqrt(365)
LABEL = "SIMULATED: assumed feed latency (licensed feed not purchased); parameters measured; trades selected on outcomes, not ex ante"


def log_read() -> None:
    """One line in results/oos_peeks.log BEFORE the burned-OOS cells are re-run (the repo's rule for every held-out read)."""
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(ROOT / "results/oos_peeks.log", "a") as f:
        f.write(f"{ts} CV cost and turnover (scripts/cv_cost_turnover.py): RE-RUN of the 12 published Table-2 cells on IS "
                "and burned OOS (reproduction of results/tier0/latency_sweep_seeds.csv; burned OOS, non-blind; no rule or "
                "parameter chosen) [logged before the run]\n")


def main() -> int:
    t0 = time.time()
    log_read()
    from scripts import tier0_latency_sweep as LS
    from src import tier0 as T
    S = pd.read_csv(ROOT / "results/tier0/latency_sweep_seeds.csv")
    S = S[(S.source == "video") & (S.cv == "own120")]
    c = LS.ctx()
    cells, chk = {}, {"seeds_checked": 0, "max_abs_pnl_diff_usd": 0.0, "max_abs_sharpe_diff": 0.0,
                      "max_abs_dd_diff_usd": 0.0, "max_abs_capital_diff_usd": 0.0}
    for rk, reading in READINGS.items():
        for vk, V in DELAYS.items():
            sc, cvs = LS.cell("video", reading, V, "own120", c)
            for pk, P in PERIODS.items():
                per = c["per"][P]
                J = per["J"]
                days = T.period_days(J, sc.regime)
                nd = len(days)
                rows = []
                for seed in range(SEEDS):
                    dr = T.draws(len(J), per["seed"] + seed, max(c["n_tour"], 1))
                    calls = T.simulate(J, per["M"], sc, dr, c["pools"], cvs, c["mix"])
                    tr = calls[calls.shares > 1e-9]
                    fee = tr.shares * tr.fee_ps
                    d = tr.groupby("date").pnl.sum().reindex(days, fill_value=0.0)
                    d2 = (tr.pnl - fee).groupby(tr.date).sum().reindex(days, fill_value=0.0)
                    eq = d.cumsum()
                    dd = float((eq - eq.cummax()).min())
                    cap = T.CAPITAL_MULT * T.peak_locked(tr)
                    pnl, sh, usd, fees = float(tr.pnl.sum()), float(tr.shares.sum()), float(tr.usd_in.sum()), float(fee.sum())
                    sr = float(d.mean() / d.std() * ANN)
                    ref = S[(S.reading == reading) & (np.isclose(S.x_s, V)) & (S.period == P) & (S.seed == seed)]
                    assert len(ref) == 1, (reading, V, P, seed)
                    r = ref.iloc[0]
                    diffs = (abs(pnl - r.pnl_usd), abs(sr - r.sharpe_ann), abs(dd - r.max_dd_usd), abs(cap - r.capital_usd))
                    assert diffs[0] < 1e-3 and diffs[1] < 1e-5 and diffs[2] < 1e-3 and diffs[3] < 1e-3, (rk, vk, pk, seed, diffs)
                    for k_, v_ in zip(("max_abs_pnl_diff_usd", "max_abs_sharpe_diff", "max_abs_dd_diff_usd", "max_abs_capital_diff_usd"), diffs):
                        chk[k_] = max(chk[k_], float(v_))
                    chk["seeds_checked"] += 1
                    rows.append({
                        "seed": seed, "pnl_usd": pnl, "shares": sh, "usd_traded": usd, "fees_usd": fees, "capital_usd": cap,
                        "pnl_per_day_usd": pnl / nd, "sharpe_ann": sr, "max_dd_usd": dd, "sd_daily_usd": float(d.std()),
                        "ann_return_pct": pnl / nd * 365 / cap * 100, "ann_vol_pct": float(d.std() * ANN / cap * 100),
                        "max_dd_pct": dd / cap * 100, "turnover_x_per_year": usd / cap * 365 / nd,
                        "fee_bps_of_notional": fees / usd * 1e4, "fee_c_per_share": fees / sh * 100,
                        "per_share_c": pnl / sh * 100,
                        "fx2_pnl_per_day_usd": (pnl - fees) / nd, "fx2_per_share_c": (pnl - fees) / sh * 100,
                        "fx2_sharpe_ann": float(d2.mean() / d2.std() * ANN),
                        "usd_per_trade": usd / len(tr), "n_trades": int(len(tr)),
                    })
                df = pd.DataFrame(rows)
                mean = {k: float(df[k].mean()) for k in df.columns if k != "seed"}
                pooled = {"per_share_c": float(df.pnl_usd.sum() / df.shares.sum() * 100),
                          "fx2_per_share_c": float((df.pnl_usd - df.fees_usd).sum() / df.shares.sum() * 100),
                          "fee_bps_of_notional": float(df.fees_usd.sum() / df.usd_traded.sum() * 1e4)}
                cap_m = mean["capital_usd"]
                ratio = {"ann_return_pct": mean["pnl_per_day_usd"] * 365 / cap_m * 100,
                         "ann_vol_pct": mean["sd_daily_usd"] * ANN / cap_m * 100,
                         "max_dd_pct": mean["max_dd_usd"] / cap_m * 100,
                         "turnover_x_per_year": mean["usd_traded"] * 365 / nd / cap_m}
                cells[f"{rk}|{vk}|{pk}"] = {"reading": reading, "V_s": V, "period": P, "days": nd, "seed_mean": mean,
                                            "ratio_of_seed_means": ratio, "pooled_over_seeds": pooled,
                                            "per_seed": df.round(6).to_dict(orient="records"),
                                            "seeds_fx2_pnl_positive": int((df.fx2_pnl_per_day_usd > 0).sum())}
                print(f"{rk} {vk} {pk}: $/day {mean['pnl_per_day_usd']:+.2f}, Sharpe {mean['sharpe_ann']:.2f}, "
                      f"turnover {mean['turnover_x_per_year']:.0f}x, fee {mean['fee_bps_of_notional']:.0f} bps, "
                      f"fees x2 $/day {mean['fx2_pnl_per_day_usd']:+.2f} ({time.time() - t0:.0f}s)", flush=True)
    J_ = json.loads((ROOT / "results/tier0/latency_sweep.json").read_text())
    for key, cell in cells.items():   # the seed means equal the published cells (stored there to 2 decimals)
        pub = J_["video_own120"][cell["reading"]][f"{cell['V_s']:g}"][cell["period"]]
        assert abs(cell["seed_mean"]["pnl_per_day_usd"] - pub["usd_per_day"]) < 0.0051, (key, pub["usd_per_day"])
        assert abs(cell["seed_mean"]["sharpe_ann"] - pub["sharpe_ann"]) < 0.0051, (key, pub["sharpe_ann"])
    out = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "script": "scripts/cv_cost_turnover.py", "label": LABEL,
           "conventions": {"capital": "3 x peak dollars locked (src/tier0.py CAPITAL_MULT, LOCK_S 4 h)",
                           "statistics": "per seed, then the mean over 20 seeds (the paper's CV convention); ratio_of_seed_means divides seed-mean dollars by seed-mean capital (the paper's table uses these, so a cell's return has the sign of its mean $ a day)",
                           "fees_x2": "P&L minus the taker fees once more; the fill price already walks the measured stale book, so there is no separate spread charge",
                           "fee": "taker fee r q (1 - q) a share at the match's published fee rate (0 where no schedule was published)"},
           "check": {**chk, "note": "every seed's P&L, Sharpe, max drawdown and capital equal results/tier0/latency_sweep_seeds.csv; seed means equal results/tier0/latency_sweep.json"},
           "cells": cells, "runtime_s": round(time.time() - t0, 1)}
    OUT.write_text(json.dumps(out, indent=1))
    print(f"wrote {OUT.relative_to(ROOT)} ({chk['seeds_checked']} seeds checked, {time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
