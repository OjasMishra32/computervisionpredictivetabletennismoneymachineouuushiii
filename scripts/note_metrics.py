"""Derived metrics quoted in docs/NOTE.md that no other script prints (track rules: annualised return,
volatility, turnover, skew, worst month, cost in bps, holdout share, data gaps).

    .venv/bin/python scripts/note_metrics.py      # < 5 s -> results/v2/note_metrics.json

Analysis of EXISTING outputs only. It reads no prices, no prints and no P&L from data/, changes no rule,
and appends nothing to results/oos_peeks.log. Inputs:
  results/v2/causal.json       v2 causal book (scripts/v2_causal.py): P&L, capital, $ traded, days
  results/v2/cost_stress.json  fees / costs doubled (scripts/v2_cost_stress.py)
  results/rigor/rigor.json     daily sd, skew, kurtosis (scripts/rigor_pack.py)
  results/oos_peeks.log        every logged look at held-out data (the lines the experiment registry maps)
  data/raw (optional)          universe metadata (start, volume, fee schedule) and trade-file row counts
                               from parquet footers, for the holdout and missing-data figures

Conventions: capital = 3 x peak dollars locked (v2.E.metrics). Annualised return is arithmetic,
total return on capital x 365 / calendar days. Volatility = daily $ sd / capital x sqrt(365).
Turnover = $ traded / capital x 365 / days. Fee in bps of notional = fee per share x shares per $.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

causal = json.loads((ROOT / "results/v2/causal.json").read_text())
stress = json.loads((ROOT / "results/v2/cost_stress.json").read_text())
rigor = json.loads((ROOT / "results/rigor/rigor.json").read_text())

out: dict = {"inputs": ["results/v2/causal.json", "results/v2/cost_stress.json", "results/rigor/rigor.json"]}
for name, sk, rk in (("is", "is_eval", "v2_is"), ("burned_oos", "burned_oos", "v2_oos")):
    c, r = causal[f"causal/{sk}/slip0.0"], rigor["sharpe_moments"][rk]
    base, fee2, cost2 = (stress[f"{sk}/{s}"] for s in ("base", "fee_x2", "costs_x2"))
    days, cap = c["days"], c["capital_usd"]
    assert abs(base["per_share_c"] - c["per_share_c"]) < 1e-9, "cost_stress base != causal book"
    shares_per_usd = c["per_usd_c"] / c["per_share_c"]          # sum(shares) / sum($ in)
    fee_ps_c = base["per_share_c"] - fee2["per_share_c"]         # share-weighted fee, cents/share
    out[name] = {
        "days": days,
        "capital_usd": cap,
        "ann_return_pct": c["return_on_capital_pct"] * 365 / days,
        "ann_vol_pct": r["sd_daily_usd"] / cap * math.sqrt(365) * 100,
        "sharpe_ann": c["sharpe_ann"],
        "max_dd_pct": c["max_dd_pct"],
        "turnover_x_per_year": c["usd_traded"] / cap * 365 / days,
        "usd_traded_per_day": c["usd_traded"] / days,
        "skew": r["skew"],
        "kurtosis_pearson": r["kurtosis"],
        "worst_day_pct": c["worst_day_pct"],
        "worst_month_usd": c["worst_month_usd"],
        "avg_price_per_share": 1 / shares_per_usd,
        "fee_c_per_share": fee_ps_c,
        "fee_bps_of_notional": fee_ps_c * shares_per_usd * 100,
        "half_spread_0.5c_bps_of_notional": 0.5 * shares_per_usd * 100,
        "net_edge_bps_of_notional": c["per_usd_c"] * 100,
        "fees_x2_per_share_c": fee2["per_share_c"], "fees_x2_ci_c": fee2["per_share_ci_c"],
        "fees_x2_months_positive": f"{fee2['months_positive']}/{fee2['months_total']}",
        "costs_x2_per_share_c": cost2["per_share_c"], "costs_x2_ci_c": cost2["per_share_ci_c"],
        "costs_x2_sharpe": cost2["sharpe_ann"],
    }
out["fee_formula_bps_today"] = {f"q={q}": 10_000 * 0.05 * (1 - q) for q in (0.5, 0.9)}

# Only the lines the experiment registry maps (summary.log_lines_total): a replay or reproduction run in this
# checkout appends lines that record that run, so counting the file's length would change on every reproduction.
lines = [ln for ln in (ROOT / "results/oos_peeks.log").read_text().splitlines() if ln.strip()]
_reg = ROOT / "results/provenance/experiments.json"
if _reg.exists():
    lines = lines[:json.loads(_reg.read_text())["summary"]["log_lines_total"]]
out["oos_peeks_log"] = {"lines": len(lines), "non_blind_lines": sum("non-blind" in ln for ln in lines),
                        "tier0_lines": sum("tier0" in ln for ln in lines),
                        "source": "results/oos_peeks.log, the lines mapped by results/provenance/experiments.json"}

try:  # holdout and missing-data figures need the cached universe (scripts/fetch_polymarket.py)
    import pandas as pd
    import pyarrow.parquet as pq
    from src import polymarket as pm
    from src.tape import MIN_VOL, SINCE, UNTIL, universe

    u = universe()
    span = u.start.max() - u.start.min()
    oos_start = u.loc[u.oos, "start"].min()
    raw = pm.enumerate_events("tennis", SINCE, UNTIL)
    raw = raw[raw.series.isin(["atp", "wta", "challenger"]) & (raw.volume >= MIN_VOL)]
    nofee = pd.to_datetime(raw.loc[raw.fee_rate.isna(), "start_time"], utc=True)
    rows = [pq.read_metadata(pm.RAW / "trades" / f"{c}.parquet").num_rows
            if (pm.RAW / "trades" / f"{c}.parquet").exists() else None for c in u.cond]
    is_eval = u[(~u.oos) & (u.start >= pd.Timestamp("2026-02-01", tz="UTC"))]
    out["holdout"] = {
        "matches": int(len(u)), "oos_matches": int(u.oos.sum()), "oos_start": str(oos_start),
        "first_start": str(u.start.min()), "last_start": str(u.start.max()),
        "span_days": span.total_seconds() / 86400,
        "oos_days": (u.start.max() - oos_start).total_seconds() / 86400,
        "oos_share_of_time": (u.start.max() - oos_start) / span,
        "oos_share_of_volume": float(u.loc[u.oos, "volume"].sum() / u.volume.sum()),
        "time_based_20pct_start": str(u.start.min() + 0.8 * span),
    }
    out["data_gaps"] = {
        "tapes_missing": sum(r is None for r in rows),
        "tapes_at_offset_cap_10500_rows": sum(r == 10_500 for r in rows),
        "no_fee_schedule_matches": int(len(nofee)),
        "no_fee_schedule_last_start": str(nofee.max()) if len(nofee) else None,
    }
    out["is"]["v2_usd_traded_share_of_match_volume"] = (
        causal["causal/is_eval/slip0.0"]["usd_traded"] / float(is_eval.volume.sum()))
except Exception as e:  # noqa: BLE001
    out["holdout"] = out["data_gaps"] = f"skipped: {type(e).__name__}: {e}"

(ROOT / "results/v2/note_metrics.json").write_text(json.dumps(out, indent=2, default=float))
for k in ("is", "burned_oos"):
    m = out[k]
    print(f"{k:10} ann.ret {m['ann_return_pct']:.0f}%  vol {m['ann_vol_pct']:.1f}%  Sharpe {m['sharpe_ann']:.1f}  "
          f"maxDD {m['max_dd_pct']:.1f}%  turnover {m['turnover_x_per_year']:.0f}x/yr  skew {m['skew']:.2f}  "
          f"worst day {m['worst_day_pct']:.1f}%  worst month ${m['worst_month_usd']:,.0f}  "
          f"fee {m['fee_bps_of_notional']:.0f} bps  half-spread {m['half_spread_0.5c_bps_of_notional']:.0f} bps  "
          f"net edge {m['net_edge_bps_of_notional']:.0f} bps  $/day {m['usd_traded_per_day']:,.0f}")
print("fee formula, today's 5%:", out["fee_formula_bps_today"])
print("oos_peeks.log:", out["oos_peeks_log"])
print("holdout:", out["holdout"])
print("data gaps:", out["data_gaps"])
print("wrote results/v2/note_metrics.json")
