"""PM-review spot checks on v2, IN-SAMPLE ONLY (no burned-OOS, U2 or forward data is read for new analysis).

    .venv/bin/python research/financials/pm_checks.py   ->  results/financials/pm_checks.json   (~10 s, 1 process)

Reads data/v2_trades_is_oos.parquet (written by scripts/v2_causal.py) and keeps only IS evaluation trades
(match start before the OOS cutoff, months >= 2026-02), exactly as scripts/v2_causal.py does. It first checks
that this subset reproduces results/v2/causal.json (IS P&L and Sharpe) and stops if it does not.

Checks:
  1. v2 restricted to the venue regime in force today (1 s order delay, 5% fee), IS only.
  2. IS per-share CI clustered by copied wallet (the note gives this only for the burned OOS).
  3. IS per-share by entry price bucket (favourite / longshot exposure).
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
import pandas as pd
from src import v2
from src.tape import universe

E = v2.E
ref = json.loads(Path("results/v2/causal.json").read_text())["causal/is_eval/slip0.0"]

u = universe()
oos_conds = set(u.loc[u.oos, "cond"])
tr = pd.read_parquet("data/v2_trades_is_oos.parquet")
is_tr = tr[(tr.month >= E.EVAL_START) & ~tr.cond.isin(oos_conds)].copy()
del tr  # nothing below touches burned-OOS rows

m_all = E.metrics(is_tr)
assert abs(m_all["total_pnl_usd"] - ref["total_pnl_usd"]) < 1e-6, "IS P&L does not reproduce causal.json"
assert abs(m_all["sharpe_ann"] - ref["sharpe_ann"]) < 1e-9, "IS Sharpe does not reproduce causal.json"
out = {"inputs": ["data/v2_trades_is_oos.parquet", "results/v2/causal.json"],
       "scope": "in-sample evaluation trades only (match start < OOS cutoff, months >= 2026-02)",
       "reference_check": {"is_pnl_usd": [m_all["total_pnl_usd"], ref["total_pnl_usd"]],
                           "is_sharpe": [m_all["sharpe_ann"], ref["sharpe_ann"]], "pass": True}}

# 1. Today's regime only
cur = is_tr[is_tr.regime == "1s/5%"]
m = E.metrics(cur, n_boot=2000)
days = m["days"]
out["current_regime_1s_5pct_is"] = {
    "first_trade_date": str(cur.date.min().date()), "last_trade_date": str(cur.date.max().date()),
    "calendar_days": days, "n_trades": m["n_trades"], "n_matches": m["n_matches"],
    "per_share_c": m["per_share_c"], "per_share_ci_c": m["per_share_ci_c"],
    "total_pnl_usd": m["total_pnl_usd"], "pnl_per_day_usd": m["total_pnl_usd"] / days,
    "usd_traded_per_day": m["usd_traded"] / days, "sharpe_ann": m["sharpe_ann"],
    "capital_usd_3x_own_peak": m["capital_usd"], "max_dd_pct": m["max_dd_pct"],
    "worst_day_usd": m["worst_day_usd"], "months_positive": m["months_positive"], "months_total": m["months_total"],
    "annualised_pnl_usd": m["total_pnl_usd"] / days * 365,
}

# 2. Wallet-clustered CI, IS
g = is_tr.groupby("wallet").agg(p=("pnl", "sum"), s=("shares", "sum"))
P, S = g.p.to_numpy(), g.s.to_numpy()
rng = np.random.default_rng(0)
bs = []
for _ in range(2000):
    i = rng.integers(0, len(g), len(g))
    bs.append(P[i].sum() / S[i].sum() * 100)
top = g.p.sort_values(ascending=False)
out["wallet_clustered_is"] = {
    "n_wallets": int(len(g)), "per_share_c": float(P.sum() / S.sum() * 100),
    "ci95_c": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
    "method": "bootstrap over copied wallets, 2,000 draws, seed 0, share-weighted",
    "top1_share_of_pnl": float(top.iloc[0] / P.sum()), "top5_share_of_pnl": float(top.iloc[:5].sum() / P.sum()),
}

# 3. Entry price buckets (q = price paid for the token bought)
bins = [0.05, 0.2, 0.4, 0.6, 0.8, 0.95]
is_tr["qbin"] = pd.cut(is_tr.q, bins, include_lowest=True).astype(str)
rows = []
for b, part in is_tr.groupby("qbin"):
    gm = part.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
    Pm, Sm = gm.p.to_numpy(), gm.s.to_numpy()
    rb = np.random.default_rng(0)
    bb = [Pm[i].sum() / Sm[i].sum() * 100 for i in (rb.integers(0, len(gm), len(gm)) for _ in range(1000))]
    rows.append({"q_bucket": b, "n_trades": int(len(part)), "share_of_shares": float(part.shares.sum() / is_tr.shares.sum()),
                 "pnl_usd": float(part.pnl.sum()), "per_share_c": float(Pm.sum() / Sm.sum() * 100),
                 "ci95_c_match_clustered": [float(np.percentile(bb, 2.5)), float(np.percentile(bb, 97.5))]})
out["by_entry_price_is"] = rows

# 4. Fee-assumption stress: matches with no published fee schedule (all before Apr 2026) are charged 0% in the
#    backtest. Charge them 3% (the first published tennis rate) instead, book held fixed (as v2_cost_stress.py does:
#    no re-selection of wallets), fee per share = rate * q * (1 - q).
nf = is_tr.rate == 0
stress = is_tr.assign(pnl=is_tr.pnl - nf * is_tr.shares * 0.03 * is_tr.q * (1 - is_tr.q))
stress = stress.assign(pnl_ps=stress.pnl / stress.shares)
ms = E.metrics(stress, n_boot=2000)
out["null_fee_charged_3pct_is"] = {
    "trades_with_zero_fee": int(nf.sum()), "share_of_is_trades": float(nf.mean()),
    "months_with_zero_fee_trades": sorted(is_tr.loc[nf, "month"].unique().tolist()),
    "per_share_c": ms["per_share_c"], "per_share_ci_c": ms["per_share_ci_c"],
    "total_pnl_usd": ms["total_pnl_usd"], "sharpe_ann": ms["sharpe_ann"],
    "base_per_share_c": m_all["per_share_c"], "base_total_pnl_usd": m_all["total_pnl_usd"],
}

Path("results/financials").mkdir(parents=True, exist_ok=True)
Path("results/financials/pm_checks.json").write_text(json.dumps(out, indent=2, default=float))
print(json.dumps(out, indent=2, default=float))
