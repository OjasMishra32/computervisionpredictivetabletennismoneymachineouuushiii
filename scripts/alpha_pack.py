"""Alpha pack: where the edge comes from, how big it is, where it lives, how it decays, who carries it,
what it is worth by tier, how much it holds, and what failed next to it.

Inputs: committed results files (read, never recomputed) and the already-computed frozen v2 trades in
data/v2_trades_is_oos.parquet (written by scripts/v2_causal.py). The only new computation is descriptive
splits of those trades (IS and burned OOS, kept separate); no rule, parameter or variant is chosen here.

Labels used throughout:
  IS          = in sample. v2 IS = months >= 2026-02 on matches starting before 2026-08-25 14:15 UTC.
  burned OOS  = held-out matches (start >= 2026-08-25 14:15 UTC), looked at before v2 was designed,
                so NON-BLIND for v2.
  v2 numbers are measured at the fast tier's own fill prices: the opportunity at the fast tier's
  speed, not our execution.
  tier-0      = counterfactual: assumes licensed feed + courtside camera (not purchased); parameters measured.

Writes results/alpha/alpha.json (every number carries a source under "sources") and PNGs in
results/alpha/. Appends one line to results/oos_peeks.log on the first run only.

Run from the repo root:  nice -n 10 .venv/bin/python scripts/alpha_pack.py
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

T0 = time.time()
OUT = ROOT / "results/alpha"
OUT.mkdir(parents=True, exist_ok=True)
TRADES = "data/v2_trades_is_oos.parquet"
EVAL_START = "2026-02"   # research/v2/sizing/engine.py EVAL_START (Dec 2025 + Jan 2026 are training only)
B = 1000                 # bootstrap draws (match-clustered), seed 0
PEEK_TEXT = "alpha breakdown: descriptive splits of existing v2 trades incl. burned OOS (no parameter change)"

LBL = {
    "IS": "in sample (IS)",
    "OOS": "burned OOS (non-blind for v2; held-out matches from 2026-08-25 14:15 UTC)",
    "v2_fills": "measured at the fast tier's own fill prices: the opportunity at their speed, not our execution",
    "tier0": "counterfactual: assumes licensed feed + courtside camera (not purchased); parameters measured",
}

# ------------------------------------------------------------------------------------ sources
SOURCES: dict[str, str] = {}
_JS: dict[str, dict] = {}


def J(f: str) -> dict:
    if f not in _JS:
        _JS[f] = json.loads((ROOT / f).read_text())
    return _JS[f]


def pick(key: str, f: str, *path):
    """Read a value from a results JSON and record where it came from under `key`."""
    v = J(f)
    for p in path:
        v = v[p]
    SOURCES[key] = f"{f} :: " + ".".join(str(p) for p in path)
    return v


def computed(key: str, how: str) -> None:
    SOURCES[key] = f"computed in scripts/alpha_pack.py: {how}"


def r(x, n=4):
    if x is None:
        return None
    if isinstance(x, (list, tuple, np.ndarray)):
        return [r(v, n) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if not np.isfinite(x) else round(float(x), n)
    return x


# ----------------------------------------------------------------------------- bootstrap helpers
def boot_ratio(df: pd.DataFrame, num: str, den: str, seed: int = 0, n_boot: int = B) -> list:
    """95% percentile CI of sum(num)/sum(den), resampling matches (cond) with replacement."""
    g = df.groupby("cond", sort=True)[[num, den]].sum()
    N, D = g[num].to_numpy(float), g[den].to_numpy(float)
    k = len(g)
    if k < 2 or D.sum() == 0:
        return [np.nan, np.nan]
    rng = np.random.default_rng(seed)
    out = []
    for s in range(0, n_boot, 200):
        b = min(200, n_boot - s)
        idx = rng.integers(0, k, (b, k))
        d = D[idx].sum(1)
        out.append(np.where(d != 0, N[idx].sum(1) / np.where(d != 0, d, 1), np.nan))
    v = np.concatenate(out)
    return [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))]


def group_table(df: pd.DataFrame, col: str, order=None, total_pnl=None) -> list[dict]:
    """Per-group v2 stats: share-weighted net c/share with match-clustered CI, P&L, win rate."""
    total_pnl = df.pnl.sum() if total_pnl is None else total_pnl
    rows = []
    keys = order if order is not None else sorted(df[col].dropna().unique())
    for i, k in enumerate(keys):
        g = df[df[col] == k]
        if g.empty:
            rows.append({"group": str(k), "n_trades": 0})
            continue
        ps = g.pnl.sum() / g.shares.sum() * 100
        ci = boot_ratio(g.assign(p100=g.pnl * 100), "p100", "shares", seed=i)
        rows.append({
            "group": str(k), "n_trades": int(len(g)), "n_matches": int(g.cond.nunique()),
            "shares": r(g.shares.sum(), 1), "usd_traded": r(g.usd_in.sum(), 1),
            "gross_c_per_share": r((g.shares * g.gross_res).sum() / g.shares.sum() * 100),
            "fee_c_per_share": r((g.shares * g.fee_ps).sum() / g.shares.sum() * 100),
            "net_c_per_share": r(ps), "net_ci95_c_match_clustered": r(ci),
            "pnl_usd": r(g.pnl.sum(), 2), "share_of_period_pnl": r(g.pnl.sum() / total_pnl),
            "win_rate": r((g.pnl_ps > 0).mean()),
        })
    return rows


def ols_slope(x: np.ndarray, y: np.ndarray) -> dict:
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    X = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    s2 = resid @ resid / (n - 2) if n > 2 else np.nan
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return {"slope_c_per_month": r(beta[1]), "intercept_c": r(beta[0]), "slope_t": r(beta[1] / se[1], 2),
            "n_points": n}


# ======================================================================================= data
def load_trades() -> tuple[pd.DataFrame, dict]:
    from src.tape import universe  # reads the cached event list (data/raw/events_tennis_*.parquet)
    u = universe()
    oos = set(u.loc[u.oos, "cond"])
    oos_start = str(u.loc[u.oos, "start"].min())
    tr = pd.read_parquet(ROOT / TRADES)
    n_all = len(tr)
    tr["fee_ps"] = tr.rate * tr.q * (1 - tr.q)
    tr["win"] = (tr.pnl_ps > 0).astype(float)
    tr["hour"] = pd.to_datetime(tr.ts, unit="s", utc=True).dt.hour
    tr["tod"] = (tr.hour // 4 * 4).map(lambda h: f"{h:02d}-{h + 4:02d} UTC")
    tr["since_det_s"] = tr.since_det.astype(int).astype(str) + " s"
    tr["side"] = np.where(tr.with_jump_det > 0, "with the jump", "against the jump")
    tr["period"] = np.where(tr.cond.isin(oos), "OOS", np.where(tr.month >= EVAL_START, "IS", "training"))
    meta = {"rows_in_file": n_all, "rows_training_only_excluded": int((tr.period == "training").sum()),
            "oos_start_utc": oos_start, "split": "IS = month >= 2026-02 and match not in OOS; "
            "OOS = match start >= OOS start (src/tape.py universe().oos), as scripts/v2_causal.py"}
    return tr[tr.period != "training"].copy(), meta


# ====================================================================================== main
def main() -> dict:
    tr, tmeta = load_trades()
    P = {"IS": tr[tr.period == "IS"], "OOS": tr[tr.period == "OOS"]}
    CAUSAL = "results/v2/causal.json"
    ck = {"IS": "causal/is_eval", "OOS": "causal/burned_oos"}
    NM = "results/v2/note_metrics.json"
    nmk = {"IS": "is", "OOS": "burned_oos"}
    SUM = "results/summary.json"
    checks = []

    # reproduction check: the trade file reproduces the committed causal.json headline
    for p, d in P.items():
        ref = J(CAUSAL)[f"{ck[p]}/slip0.0"]
        ours = d.pnl.sum() / d.shares.sum() * 100
        checks.append({"what": f"v2 {p} net c/share from {TRADES} vs {CAUSAL} {ck[p]}/slip0.0",
                       "ours": r(ours, 6), "repo": r(ref["per_share_c"], 6),
                       "n_trades_ours": int(len(d)), "n_trades_repo": ref["n_trades"],
                       "ok": bool(abs(ours - ref["per_share_c"]) < 1e-6 and len(d) == ref["n_trades"])})
    if not all(c["ok"] for c in checks):
        raise SystemExit(f"trade file does not reproduce causal.json: {checks}")

    out: dict = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": "scripts/alpha_pack.py",
        "git_head": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                   text=True).stdout.strip(),
        "labels": LBL,
        "trade_file": {"path": TRADES, **tmeta},
    }

    # ------------------------------------------------------------------------- A. SOURCE
    A: dict = {"what": "Fast tier (walk-forward qualified wallets) vs every other taker, prints 0-3 s after a "
               "detected jump, net 30 s markout after the match's taker fee (c/share), by month. "
               "'Copy 3 s later' = the same prints entered ~delay+3 s later at the then-mid plus half the "
               "spread, fee paid, held to resolution (src/fasttier.py net_cols follow_res).",
               "note": "Aug 2026 appears in both periods: IS matches started before 2026-08-25 14:15 UTC, "
               "OOS after. Oct 2026 is 3 days. The fast tier's own prints are not v2 and not ours."}
    for p, key in (("IS", "is"), ("OOS", "oos")):
        rows = pick(f"A.{p}.months", SUM, key, "h6_walkforward")
        mrows = [{"month": m["month"], "n_wallets": m["n_wallets"], "n_prints": m["n_prints"],
                  "n_matches": m["n_matches"], "volume_usd_k": r(m["usd_k"], 1),
                  "fast_net30_c": r(m["net30_c"]), "others_net30_c": r(m["others_net30_c"]),
                  "fast_minus_others_c": r(m["net30_c"] - m["others_net30_c"]),
                  "fast_net_to_resolution_c": r(m["net_res_c"]),
                  "copy_3s_later_net_to_resolution_c": r(m["follow_res_c"])} for m in rows]
        w = np.array([m["n_prints"] for m in rows], float)

        def pw(c):
            return float(np.sum(w * np.array([m[c] for m in rows])) / w.sum())

        def um(c):
            return float(np.mean([m[c] for m in rows]))
        A[p] = {
            "label": LBL[p] if p == "IS" else "OOS (held-out matches; the fast-tier test H6 was frozen before "
                     "it was opened, so OOS is the H6 out-of-sample read)",
            "months": mrows,
            "months_fast_positive": f"{sum(m['net30_c'] > 0 for m in rows)}/{len(rows)}",
            "months_fast_positive_to_resolution": f"{sum(m['net_res_c'] > 0 for m in rows)}/{len(rows)}",
            "fast_to_resolution_c_negative_months": {m["month"]: r(m["net_res_c"]) for m in rows if m["net_res_c"] <= 0},
            "months_others_positive": f"{sum(m['others_net30_c'] > 0 for m in rows)}/{len(rows)}",
            "months_copy_3s_later_positive": f"{sum(m['follow_res_c'] > 0 for m in rows)}/{len(rows)}",
            "fast_net30_c_range": [r(min(m["net30_c"] for m in rows)), r(max(m["net30_c"] for m in rows))],
            "others_net30_c_range": [r(min(m["others_net30_c"] for m in rows)),
                                     r(max(m["others_net30_c"] for m in rows))],
            "copy_3s_later_c_range": [r(min(m["follow_res_c"] for m in rows)),
                                      r(max(m["follow_res_c"] for m in rows))],
            "print_weighted": {"fast_net30_c": r(pw("net30_c")),
                               "copy_3s_later_net_to_resolution_c": r(pw("follow_res_c")),
                               "fast_net_to_resolution_c": r(pw("net_res_c")),
                               "others_net30_c_unweighted_month_mean": r(um("others_net30_c"))},
            "unweighted_month_mean": {"fast_net30_c": r(um("net30_c")), "others_net30_c": r(um("others_net30_c")),
                                      "copy_3s_later_net_to_resolution_c": r(um("follow_res_c"))},
            "fast_tier_volume_usd_k": r(sum(m["usd_k"] for m in rows), 1),
            "fast_tier_prints": int(sum(m["n_prints"] for m in rows)),
        }
        computed(f"A.{p}.print_weighted", f"pooled = n_prints-weighted mean of {SUM} {key}.h6_walkforward monthly "
                 "means (copy-3s is computed on the same fast-tier prints, so the weights are exact); others: "
                 "unweighted month mean (the file has no per-month count of other takers' prints)")
    A["copy_3s_later_note"] = ("NOTE.md Table 1 'Copying the fast tier 3 s later: < 0 every month' is the "
                               "follow_res_c column above.")
    SOURCES["A.copy_3s_later_note"] = "docs/NOTE.md Table 1; src/fasttier.py net_cols"
    SOURCES["A.unseen.universe"] = "results/expand/results.json :: universe.(u2_markets, u2_series.itf)"
    A["note_md_month_count"] = (f"docs/NOTE.md Table 1 says the fast tier was positive in 8/8 IS months; "
                                f"{SUM} is.h6_walkforward has {len(A['IS']['months'])} IS rows (it includes "
                                f"{A['IS']['months'][0]['month']}, {A['IS']['months'][0]['n_prints']} prints), "
                                f"all positive. This page uses the results file.")
    SOURCES["A.months_to_resolution"] = f"{SUM} :: (is|oos).h6_walkforward[].net_res_c (count > 0)"
    SOURCES["A.note_md_month_count"] = f"docs/NOTE.md Table 1 (H6 row) vs {SUM} :: is.h6_walkforward (row count)"
    EXP = "results/expand/results.json"
    A["unseen_markets_check"] = {
        "label": (f"{J(EXP)['universe']['u2_markets']:,} never-examined markets "
                  f"({J(EXP)['universe']['u2_series']['itf']:,} ITF), pre-registered; per print, net 30 s"),
        "IS_fast_minus_others_c": r(pick("A.unseen.IS", EXP, "fast_minus_others_u2", "u2_is", "fast_minus_others_c")),
        "IS_ci95_c": r(J(EXP)["fast_minus_others_u2"]["u2_is"]["ci_c"]),
        "OOS_fast_minus_others_c": r(pick("A.unseen.OOS", EXP, "fast_minus_others_u2", "u2_oos",
                                          "fast_minus_others_c")),
        "OOS_ci95_c": r(J(EXP)["fast_minus_others_u2"]["u2_oos"]["ci_c"]),
        "OOS_fast_net30_c": r(J(EXP)["fast_minus_others_u2"]["u2_oos"]["fast_net30_c"]),
        "OOS_others_net30_c": r(J(EXP)["fast_minus_others_u2"]["u2_oos"]["others_net30_c"]),
    }
    out["A_source"] = A

    # --------------------------------------------------------------------------- B. SIZE
    Bsec: dict = {"label": LBL["v2_fills"],
                  "what": "Frozen v2 book, causal window, held to resolution. Per share and per $ of notional "
                          "(bps). Gross = payout minus fill price; fee = rate x q(1-q) of the match's own "
                          "taker fee; no slippage is modelled at fast-tier fills (they already crossed the "
                          "spread), so +0.5c and +1c worse-entry rows are shown from the committed stress."}
    for p, d in P.items():
        sh, usd = d.shares.sum(), d.usd_in.sum()
        gross = (d.shares * d.gross_res).sum()
        fee = (d.shares * d.fee_ps).sum()
        net = d.pnl.sum()
        dd = d.assign(g100=d.shares * d.gross_res * 100, f100=d.shares * d.fee_ps * 100, n100=d.pnl * 100)
        ref = J(CAUSAL)
        rows = [
            {"step": "gross edge (fill to resolution)", "c_per_share": r(gross / sh * 100),
             "bps_of_notional": r(gross / usd * 1e4, 1), "ci95_c_match_clustered": r(boot_ratio(dd, "g100", "shares", 1)),
             "usd": r(gross, 2)},
            {"step": "taker fee", "c_per_share": r(-fee / sh * 100), "bps_of_notional": r(-fee / usd * 1e4, 1),
             "usd": r(-fee, 2)},
            {"step": "slippage modelled at fast-tier fills", "c_per_share": 0.0, "bps_of_notional": 0.0, "usd": 0.0},
            {"step": "net (at fast-tier fills)", "c_per_share": r(net / sh * 100),
             "bps_of_notional": r(net / usd * 1e4, 1),
             "ci95_c_match_clustered": r(ref[f"{ck[p]}/slip0.0"]["per_share_ci_c"]), "usd": r(net, 2)},
        ]
        for slip in ("0.005", "0.01"):
            s = pick(f"B.{p}.slip{slip}", CAUSAL, f"{ck[p]}/slip{slip}")
            rows.append({"step": f"net with +{float(slip) * 100:g}c worse entry (stress)",
                         "c_per_share": r(s["per_share_c"]),
                         "bps_of_notional": r(s["per_usd_c"] * 100, 1),
                         "ci95_c_match_clustered": r(s["per_share_ci_c"]), "usd": r(s["total_pnl_usd"], 2),
                         "sharpe_ann": r(s["sharpe_ann"], 2),
                         "months_positive": f"{s['months_positive']}/{s['months_total']}"})
        computed(f"B.{p}.decomposition", f"{TRADES}: share-weighted gross_res, rate*q*(1-q), pnl; bps = / usd_in")
        SOURCES[f"B.{p}.net_ci"] = f"{CAUSAL} :: {ck[p]}/slip0.0.per_share_ci_c"
        nm = J(NM)[nmk[p]]
        cz = J(CAUSAL)[f"{ck[p]}/slip0.0"]
        Bsec[p] = {
            "label": LBL[p],
            "n_trades": int(len(d)), "n_matches": int(d.cond.nunique()), "shares": r(sh, 0),
            "usd_traded": r(usd, 0), "avg_price_per_share": r(usd / sh),
            "waterfall": rows,
            "per_print_mean_c": r(cz["per_print_c"]), "per_print_ci95_c": r(cz["per_print_ci_c"]),
            "pnl_usd": r(cz["total_pnl_usd"], 2), "pnl_ci95_usd": r(cz["total_pnl_ci_usd"], 0),
            "days": nm["days"], "capital_usd": r(nm["capital_usd"], 0),
            "capital_rule": "3 x peak dollars locked, 4 h ex-ante lock per position",
            "ann_return_pct": r(nm["ann_return_pct"], 1), "ann_vol_pct": r(nm["ann_vol_pct"], 1),
            "sharpe_ann": r(nm["sharpe_ann"], 2), "max_dd_pct": r(nm["max_dd_pct"], 2),
            "worst_day_pct": r(nm["worst_day_pct"], 2), "skew": r(nm["skew"], 2),
            "turnover_x_per_year": r(nm["turnover_x_per_year"], 1),
            "usd_traded_per_day": r(nm["usd_traded_per_day"], 0),
            "fee_bps_of_notional_note_metrics": r(nm["fee_bps_of_notional"], 1),
            "net_edge_bps_of_notional_note_metrics": r(nm["net_edge_bps_of_notional"], 1),
            "months_positive": f"{cz['months_positive']}/{cz['months_total']}",
        }
        SOURCES[f"B.{p}.annualised"] = f"{NM} :: {nmk[p]}.(ann_return_pct, ann_vol_pct, sharpe_ann, max_dd_pct, ...)"
        SOURCES[f"B.{p}.pnl"] = f"{CAUSAL} :: {ck[p]}/slip0.0"
        checks.append({"what": f"B {p} fee bps (ours vs note_metrics)", "ours": r(fee / usd * 1e4, 3),
                       "repo": r(nm["fee_bps_of_notional"], 3), "ok": abs(fee / usd * 1e4 - nm["fee_bps_of_notional"]) < 0.01})
    RIG = "results/rigor/rigor.json"
    rig = {row["series"]: row for row in J(RIG)["psr_dsr"]["rows"]}
    Bsec["luck"] = {
        "IS_sharpe_ci95_block_bootstrap": r(pick("B.luck.IS", RIG, "bootstrap", "v2_is", "sharpe_ann_ci95"), 2),
        "OOS_sharpe_ci95_bootstrap": r(pick("B.luck.OOS", RIG, "bootstrap", "v2_oos", "sharpe_ann_ci95"), 2),
        "IS_deflated_sharpe_N3386": r(rig["v2_is"]["dsr_min_N3386"]),
        "OOS_deflated_sharpe_N3386": r(rig["v2_oos"]["dsr_min_N3386"]),
        "OOS_expected_best_of_3386_null_sharpe": r(rig["v2_oos"]["sr0_ann_max_N3386"], 2),
        "dsr_N3386_by_variance_assumption": {
            p: {k.split("/", 1)[1]: r(v["dsr"]) for k, v in rig[s]["dsr"].items() if k.startswith("N3386/")}
            for p, s in (("IS", "v2_is"), ("OOS", "v2_oos"))},
        "dsr_note": "The deflated Sharpe shown is the lowest of three assumptions for the variance of the trials' "
                    "Sharpe ratios (results/rigor/rigor.json psr_dsr.variance_sources); the other two are listed.",
        "reading": (f"{J(NM)['burned_oos']['days']} OOS days cannot rule out luck: the expected best of 3,386 zero-skill trials "
                    "beats v2's OOS Sharpe."),
    }
    SOURCES["B.luck.dsr"] = (f"{RIG} :: psr_dsr.rows[series=v2_is|v2_oos].dsr_min_N3386, sr0_ann_max_N3386, "
                             "dsr.N3386/*.dsr")
    PMC = "results/financials/pm_compute.json"
    p26 = pick("B.gross_split_IS", PMC, "p26_gross_edge_split_is")
    Bsec["gross_split_IS_only"] = {
        "label": "IS only (not computed for OOS); mid = print-based proxy",
        "gross_fill_to_resolution_c": r(p26["components"]["gross_fill_to_resolution"]["c_per_share"]),
        "stale_quote_fill_vs_mid_30s_c": r(p26["components"]["fill_vs_mid_30s (stale quote)"]["c_per_share"]),
        "of_which_fill_vs_mid_5s_c": r(p26["components"]["fill_vs_mid_5s"]["c_per_share"]),
        "of_which_mid_5s_to_mid_30s_c": r(p26["components"]["mid_5s_to_mid_30s"]["c_per_share"]),
        "drift_mid_30s_to_resolution_c": r(p26["components"]["mid_30s_to_resolution (drift)"]["c_per_share"]),
        "drift_ci95_c": r(p26["components"]["mid_30s_to_resolution (drift)"]["ci95_c_match_clustered"]),
        "share_of_gross_from_stale_quote": r(p26["share_of_gross_from_stale_quote_30s"]),
    }
    out["B_size"] = Bsec

    # ------------------------------------------------------------------- C. FACTOR-NEUTRAL
    FR = "results/v2/factor_regression.json"
    fr = J(FR)
    p24 = J(PMC)["p24_factor_regression_is"]["calendar_days_excess_x365"]
    p24c = J(PMC)["p24_factor_regression_is"]["committed_spec_is_only"]
    # which weekdays of the committed regression window carry burned-OOS P&L (descriptive, from the trade file)
    lo_d, hi_d = pd.Timestamp(fr["period"][0]), pd.Timestamp(fr["period"][1])
    day = lambda d: pd.to_datetime(d.ts, unit="s").dt.floor("D")
    oos_days = sorted({x for x in day(P["OOS"]) if lo_d <= x <= hi_d and x.weekday() < 5})
    is_days = {x for x in day(P["IS"]) if lo_d <= x <= hi_d}
    mixed = [x for x in oos_days if x in is_days]
    oos_w = {"n_weekdays_with_oos_pnl": len(oos_days), "n_oos_only": len(oos_days) - len(mixed),
             "dates": [str(x.date()) for x in oos_days], "mixed_dates": [str(x.date()) for x in mixed]}
    computed("C.committed.oos_weekdays", f"{TRADES}: weekdays in {FR} period with burned-OOS trades (UTC days)")
    mix_txt = (f"{oos_w['n_weekdays_with_oos_pnl']} of its weekdays ({oos_w['dates'][0][5:]} to "
               f"{oos_w['dates'][-1][5:]}) carry burned-OOS P&L, {oos_w['n_oos_only']} of them OOS only")
    out["C_factor_neutral"] = {
        "IS_committed_spec": {
            "label": f"IS only: {p24c['spec']}; Newey-West 5 lags; {p24c['period'][0]} to {p24c['period'][1]}",
            "n_days": p24c["n_days"], "alpha_pct_per_day": r(p24c["coef"]["alpha_daily"] * 100, 3),
            "alpha_t": r(p24c["t"]["alpha_daily"], 2), "alpha_annualised_pct": r(p24c["alpha_annualised_pct"], 1),
            "betas": {k: r(v, 6) for k, v in p24c["coef"].items()}, "betas_t": {k: r(v, 4) for k, v in p24c["t"].items()},
            "r2": r(p24c["r2"]), "corr_with_market": r(p24c["corr_with_market"], 3),
            "max_abs_factor_t": r(p24c["max_abs_factor_t"], 2),
        },
        "committed": {
            "label": "File as committed (results/v2/factor_regression.json): Fama-French 3 + momentum on v2 "
                     f"daily returns, weekdays with factor data, {fr['period'][0]} to {fr['period'][1]}; NOT IS only: "
                     + mix_txt,
            "oos_weekdays_in_window": oos_w,
            "n_days": fr["n_days"], "alpha_pct_per_day": r(fr["coef"]["alpha_daily"] * 100, 3),
            "alpha_t": fr["t"]["alpha_daily"], "alpha_annualised_pct": fr["alpha_annualised_pct"],
            "betas": fr["coef"], "betas_t": fr["t"], "r2": fr["r2"], "corr_with_market": fr["corr_with_market"],
            "max_abs_factor_t": max(abs(v) for k, v in fr["t"].items() if k != "alpha_daily"),
        },
        "IS_only_calendar_days": {
            "label": "IS only, every calendar day (zero days kept), Newey-West 5 lags",
            "n_days": p24["n_days"], "alpha_pct_per_day": r(p24["coef"]["alpha_daily"] * 100, 3),
            "alpha_t": r(p24["t"]["alpha_daily"], 2), "r2": r(p24["r2"]), "corr_with_market": r(p24["corr_with_market"]),
            "max_abs_factor_t": r(p24["max_abs_factor_t"], 2),
        },
        "reading": (f"No factor explains the IS P&L: largest factor |t| = {p24c['max_abs_factor_t']:.2f}, "
                    f"R2 = {p24c['r2'] * 100:.1f}% (IS-only calendar-day spec {p24['r2'] * 100:.1f}%; committed file, "
                    f"which includes {oos_w['n_weekdays_with_oos_pnl']} burned-OOS weekdays, "
                    f"{fr['r2'] * 100:.1f}%)."),
    }
    SOURCES["C.IS_committed_spec"] = f"{PMC} :: p24_factor_regression_is.committed_spec_is_only"
    SOURCES["C.committed"] = f"{FR} :: (all keys); OOS weekdays in its window from {TRADES}"
    SOURCES["C.IS_only_calendar_days"] = f"{PMC} :: p24_factor_regression_is.calendar_days_excess_x365"

    # ------------------------------------------------------------------- D. WHERE IN THE BOOK
    qs = np.unique(np.quantile(P["IS"].q, np.linspace(0, 1, 11)))
    qs[0], qs[-1] = min(qs[0], tr.q.min()) - 1e-9, max(qs[-1], tr.q.max()) + 1e-9
    qlab = [f"{max(qs[i], 0.05):.2f}-{min(qs[i + 1], 0.95):.2f}" for i in range(len(qs) - 1)]
    tr["q_decile"] = pd.cut(tr.q, qs, labels=qlab, include_lowest=True).astype(str)
    P = {"IS": tr[tr.period == "IS"], "OOS": tr[tr.period == "OOS"]}
    D: dict = {"label": LBL["v2_fills"],
               "what": "Descriptive splits of the frozen v2 trades. Net c/share is share-weighted; 95% CI = "
                       "match-clustered bootstrap (1,000 draws). Price deciles use IS decile edges for both periods "
                       "(intervals open on the left, prices are on a 1c tick so deciles are not equal-count).",
               "side_market_type": "n/a: v2 trades only the match-winner moneyline (side markets were traded "
                                   "only by maker v1, which failed its blind OOS test; see I)."}
    order = {"q_decile": qlab, "regime": ["3s/0%", "3s/3%", "1s/3%", "1s/5%"],
             "tod": [f"{h:02d}-{h + 4:02d} UTC" for h in range(0, 24, 4)], "since_det_s": ["0 s", "1 s", "2 s"],
             "side": ["with the jump", "against the jump"]}
    for p, d in P.items():
        tot = d.pnl.sum()
        wins, losses = d[d.pnl_ps > 0], d[d.pnl_ps < 0]
        wr_ci = boot_ratio(d.assign(one=1.0), "win", "one", seed=7)
        D[p] = {
            "label": LBL[p],
            "by_price_decile_q": group_table(d, "q_decile", order["q_decile"], tot),
            "by_regime_delay_fee": group_table(d, "regime", [k for k in order["regime"] if (d.regime == k).any()], tot),
            "by_time_of_day_utc": group_table(d, "tod", order["tod"], tot),
            "by_month": group_table(d, "month", None, tot),
            "by_seconds_since_detection": group_table(d, "since_det_s", order["since_det_s"], tot),
            "by_direction_vs_jump": group_table(d, "side", order["side"], tot),
            "trade_win_rate": r(d.win.mean()), "trade_win_rate_ci95_match_clustered": r(wr_ci),
            "share_weighted_win_rate": r((d.win * d.shares).sum() / d.shares.sum()),
            "avg_win_usd": r(wins.pnl.mean(), 3), "avg_loss_usd": r(losses.pnl.mean(), 3),
            "avg_win_c_per_share": r(wins.pnl.sum() / wins.shares.sum() * 100, 2),
            "avg_loss_c_per_share": r(losses.pnl.sum() / losses.shares.sum() * 100, 2),
            "payoff_ratio_usd": r(wins.pnl.mean() / -losses.pnl.mean(), 3),
            "n_wins": int(len(wins)), "n_losses": int(len(losses)), "n_flat": int((d.pnl_ps == 0).sum()),
            "net_c_per_share": r(tot / d.shares.sum() * 100),
            "net_ci95_c_match_clustered": r(J(CAUSAL)[f"{ck[p]}/slip0.0"]["per_share_ci_c"]),
            "reading_win_rate": (f"Held to resolution each trade pays 0 or 1: the share-weighted win rate "
                                 f"{(d.win * d.shares).sum() / d.shares.sum() * 100:.1f}% vs an average price paid of "
                                 f"{d.usd_in.sum() / d.shares.sum() * 100:.1f}c is the gross edge; wins and losses are "
                                 "about the same size per share."),
        }
        computed(f"D.{p}", f"{TRADES}, period {p}; groupby splits; match bootstrap seed per group")
    out["D_where"] = D

    # ----------------------------------------------------------------------------- E. DECAY
    DEC = "results/decay/decay.json"
    dj = J(DEC)
    bins = ["0-0.25", "1-2", "2-3", "3-5", "5-10", "10-30", "baseline"]
    blab = {"0-0.25": "0 s (same block second as detection)", "1-2": "1 s", "2-3": "2 s", "3-5": "3-4 s",
            "5-10": "5-9 s", "10-30": "10-29 s", "baseline": "baseline (no detection in last 30 s)"}
    E: dict = {"within_a_point": {
        "what": "Net 30 s markout (c/share, after fee) by seconds since jump DETECTION, tennis moneylines, "
                "match-clustered 95% CI. From the committed TT5 decay run.",
        "resolution_note": "Tape timestamps are block times in whole seconds (median 1.98 s after the true trade), "
                           "so the 0.25-1 s bins are empty by construction; '0 s' = same block second as "
                           "detection. The requested 0-0.5/0.5-1 s split is not resolvable on these tapes.",
        "empty_bins": dj["empty_by_construction"],
    }}
    SOURCES["E.within_a_point"] = (f"{DEC} :: tennis.subsets.(IS|burned_OOS).curves.(fast|others|all|with_jump).net30, "
                                  "prints, matches, decay_test; empty_by_construction")
    for p, sk in (("IS", "IS"), ("OOS", "burned_OOS")):
        sub = dj["tennis"]["subsets"][sk]
        E["within_a_point"][p] = {
            "label": LBL[p] if p == "IS" else "burned OOS (non-blind; read by scripts/signal_decay.py, already logged)",
            "prints": sub["prints"], "matches": sub["matches"],
            "rows": [{"bin": blab[b], **{g: {"net30_c": r(sub["curves"][g]["net30"][b]["mean_c"]),
                                             "ci95_c": r(sub["curves"][g]["net30"][b]["ci_c"]),
                                             "n": sub["curves"][g]["net30"][b]["n"]}
                                         for g in ("fast", "others", "all", "with_jump")}} for b in bins],
            "decay_test_prereg": sub["decay_test"],
        }
    SOURCES["E.within_a_point.v2_by_seconds_since_detection"] = "section D (computed from " + TRADES + ")"
    E["within_a_point"]["v2_by_seconds_since_detection"] = {
        p: D[p]["by_seconds_since_detection"] for p in ("IS", "OOS")}
    fi = [rw["fast"]["net30_c"] for rw in E["within_a_point"]["IS"]["rows"]]
    fo = [rw["fast"]["net30_c"] for rw in E["within_a_point"]["OOS"]["rows"]]
    oth = [rw["others"]["net30_c"] for p in ("IS", "OOS") for rw in E["within_a_point"][p]["rows"]]
    E["within_a_point"]["reading"] = (
        f"The fast tier earns most in the detection second ({fi[0]:+.2f}c IS, {fo[0]:+.2f}c OOS) and about half "
        f"that one second later ({fi[1]:+.2f}c IS, {fo[1]:+.2f}c OOS). OOS its 2-9 s bins are "
        f"{fo[2]:+.2f} / {fo[3]:+.2f} / {fo[4]:+.2f}c. Everyone else is below zero in every bin "
        f"(max {max(oth):+.2f}c).")
    # (ii) calendar time
    rows_is = J(SUM)["is"]["h6_walkforward"]
    rows_oos = J(SUM)["oos"]["h6_walkforward"]
    mi = lambda m: (int(m[:4]) - 2025) * 12 + int(m[5:7]) - 12  # months since 2025-12
    x_is = np.array([mi(m["month"]) for m in rows_is])
    y_is = np.array([m["net30_c"] for m in rows_is])
    x_all = np.concatenate([x_is, [mi(m["month"]) for m in rows_oos]])
    y_all = np.concatenate([y_is, [m["net30_c"] for m in rows_oos]])
    E["over_calendar_time"] = {
        "what": "Fast-tier net 30 s markout by month (A), OLS on month index (0 = 2025-12), unweighted. The IS fit "
                "uses the IS months only; the pooled fit adds the 3 H6 OOS rows and is descriptive, not a test.",
        "IS_months": ols_slope(x_is, y_is),
        "IS_plus_OOS_rows": {**ols_slope(x_all, y_all), "note": "OOS rows appended in calendar order; Aug has an "
                             "IS and an OOS row; Oct is 3 days"},
        "first3_IS_months_mean_c": r(y_is[:3].mean()), "last3_rows_mean_c": r(y_all[-3:].mean()),
        "wallets_first_to_last": [rows_is[0]["n_wallets"], rows_oos[-1]["n_wallets"]],
        "v2_monthly_net_c": {p: [{"month": g["group"], "net_c_per_share": g["net_c_per_share"],
                                  "ci95": g["net_ci95_c_match_clustered"]} for g in D[p]["by_month"]]
                             for p in ("IS", "OOS")},
        "reading": (f"The edge is shrinking: in sample the fast tier's net 30 s markout averaged "
                    f"{y_is[:4].mean():.2f}c over Dec-Mar and {y_is[-4:].mean():.2f}c over May-Aug, a fitted "
                    f"{ols_slope(x_is, y_is)['slope_c_per_month']:+.2f}c per month over the {len(y_is)} IS months "
                    f"(t = {ols_slope(x_is, y_is)['slope_t']:.2f}); the 3 H6 OOS rows average "
                    f"{y_all[len(y_is):].mean():.2f}c (pooled fit {ols_slope(x_all, y_all)['slope_c_per_month']:+.2f}c "
                    f"per month), while qualifying wallets grew "
                    f"from {rows_is[0]['n_wallets']} to {rows_oos[-1]['n_wallets']} and the venue moved from a "
                    "3 s delay / no fee to 1 s / 5% (docs/NOTE.md section 1). The 30 s markout stayed positive "
                    "every month; held to resolution it was "
                    + ("below zero in " + ", ".join(f"{m} {p} ({v:+.2f}c)" for p in ("IS", "OOS")
                                                    for m, v in A[p]["fast_to_resolution_c_negative_months"].items())
                       if any(A[p]["fast_to_resolution_c_negative_months"] for p in ("IS", "OOS"))
                       else "also positive every month") + "."),
    }
    computed("E.over_calendar_time", f"OLS of {SUM} (is|oos).h6_walkforward net30_c on month index")
    out["E_decay"] = E

    # ------------------------------------------------------------------------ F. CONCENTRATION
    F: dict = {"label": LBL["v2_fills"],
               "what": "Share of v2 P&L carried by the top 1/5/10 copied wallets, matches and days (sum of the "
                       "top-k units' P&L / period P&L; above 100% means the rest lost money)."}
    curves = {}
    for p, d in P.items():
        tot = d.pnl.sum()
        F[p] = {"label": LBL[p], "total_pnl_usd": r(tot, 2)}
        for unit, col in (("wallets", "wallet"), ("matches", "cond"), ("days", "date")):
            s = d.groupby(col).pnl.sum().sort_values(ascending=False)
            cum = s.cumsum().to_numpy()
            F[p][unit] = {"n": int(len(s)), "n_positive": int((s > 0).sum()),
                          **{f"top{k}_share_of_pnl": r(s.iloc[:k].sum() / tot) for k in (1, 5, 10)},
                          "top1_pnl_usd": r(s.iloc[0], 2),
                          "fewest_units_reaching_100pct_of_pnl": int(np.argmax(cum >= tot) + 1) if (cum >= tot).any() else None}
            if unit == "wallets":
                curves[p] = cum / tot
                top5 = set(s.index[:5])
                rest = d[~d.wallet.isin(top5)]
                F[p]["wallets"]["ex_top5_wallets"] = {
                    "n_trades": int(len(rest)), "pnl_usd": r(rest.pnl.sum(), 2),
                    "net_c_per_share": r(rest.pnl.sum() / rest.shares.sum() * 100),
                    "ci95_c_match_clustered": r(boot_ratio(rest.assign(p100=rest.pnl * 100), "p100", "shares", 11)),
                    "share_of_trades": r(len(rest) / len(d)),
                }
        computed(f"F.{p}", f"{TRADES}: groupby wallet / cond / date, sorted P&L")
    pmc7 = J(PMC)["p07_wallet_clustered_ci"]
    F["wallet_clustered_ci95_c"] = {"IS": r(pmc7["is"]["ci95_c_wallet_clustered"]),
                                    "OOS": r(pmc7["burned_oos"]["ci95_c_wallet_clustered"])}
    SOURCES["F.wallet_clustered_ci95_c"] = f"{PMC} :: p07_wallet_clustered_ci.(is|burned_oos).ci95_c_wallet_clustered"
    for p, k in (("IS", "is"), ("OOS", "burned_oos")):
        checks.append({"what": f"F {p} top-5 wallet share vs pm_compute p07", "ours": F[p]["wallets"]["top5_share_of_pnl"],
                       "repo": r(pmc7[k]["top5_share_of_pnl"]),
                       "ok": abs(F[p]["wallets"]["top5_share_of_pnl"] - pmc7[k]["top5_share_of_pnl"]) < 1e-3})
    F["reading"] = (f"OOS is concentrated: the top 5 of {F['OOS']['wallets']['n']} copied wallets carry "
                    f"{F['OOS']['wallets']['top5_share_of_pnl'] * 100:.0f}% of OOS P&L (IS "
                    f"{F['IS']['wallets']['top5_share_of_pnl'] * 100:.0f}%); without them OOS v2 earns "
                    f"{F['OOS']['wallets']['ex_top5_wallets']['net_c_per_share']:+.2f}c/share. Clustered by "
                    "wallet, the OOS CI includes zero.")
    out["F_concentration"] = F

    # ------------------------------------------------------------------------ G. TIER LADDER
    T0J, VR = "results/tier0/results.json", "research/v2/tier0/verify_out/verify_realism.json"
    t0 = J(T0J)
    dec_is = t0["headline_by_size_and_decomposition"]["IS"]["decomposition"]
    dec_oos = t0["headline_by_size_and_decomposition"]["burned_OOS"]["decomposition"]
    hi, ho = t0["headline"]["IS"]["mean"], t0["headline"]["burned_OOS"]["mean"]
    ft = J(VR)["3c_fast_tier_vs_model"]["measured_fast_tier_prints_landing_[-0.5,0)_with_move"]
    cal = J(SUM)["is"]["calibration"]
    cal_o = J(SUM)["oos"]["calibration"]
    inside = lambda rows: sum(1 for b in rows if b["lo"] <= b["mean_price"] <= b["hi"])
    # committed tier-0 feed-latency sweep (f5ff9ff): the same trader without our own courtside camera
    LS = "results/tier0/latency_sweep.json"
    ls = J(LS)
    lsv = ls["video_own120"]["tournament"]["0.5"]
    lsb = ls["breakeven_video_delay"]["tournament"]
    lsc = ls["check_V0_equals_published_headline"]
    no_cam = {
        "label": LBL["tier0"] + "; " + ls["label"],
        "what": "Same tier-0 trader with the courtside camera replaced by licensed betting video delayed V seconds "
                "(own CV on the video), headline (tournament) timing reading; 20 seeds. A courtside camera is not "
                "feasible for us (research/v2/tier0/LATENCY_SWEEP.md).",
        "V0_reproduces_headline": bool(lsc["IS"]["identical"] and lsc["burned_OOS"]["identical"]),
        "video_0p5s": {p: {"c": r(lsv[k]["net_c_per_share"]), "ci95": r(lsv[k]["net_c_per_share_ci95"]),
                           "usd_per_day": r(lsv[k]["usd_per_day"], 2)} for p, k in (("IS", "IS"), ("OOS", "burned_OOS"))},
        "breakeven_video_delay_s": {p: {"s": lsb[k]["breakeven_V_s_seed_mean_curve"],
                                        "ci95_s": lsb[k]["breakeven_V_s_seed_bootstrap_ci95"]}
                                    for p, k in (("IS", "IS"), ("OOS", "burned_OOS"))},
    }
    SOURCES["G.tier0_no_camera"] = (f"{LS} :: video_own120.tournament.0.5.(IS|burned_OOS); "
                                    "breakeven_video_delay.tournament; check_V0_equals_published_headline (commit f5ff9ff)")
    stamp = t0["stresses_corrected"]["reading: R spread = umpire-stamp noise (t_reprice - t_bounce constant)"]
    ladder = [
        {"tier": "Tier-0: courtside camera + own CV + licensed feed + London gateway", "label": LBL["tier0"],
         "horizon": "to resolution",
         "gross_c_correct_calls_vs_new_mid": {"IS": dec_is["correct"]["book_edge_c"], "OOS": dec_oos["correct"]["book_edge_c"]},
         "net_c_correct_calls": {"IS": dec_is["correct"]["net_c"], "OOS": dec_oos["correct"]["net_c"]},
         "net_c_all_calls": {"IS": hi["per_share_c"], "OOS": ho["per_share_c"]},
         "net_ci95_c_all_calls": {"IS": [hi["per_share_ci95_c_lo"], hi["per_share_ci95_c_hi"]],
                                  "OOS": [ho["per_share_ci95_c_lo"], ho["per_share_ci95_c_hi"]]},
         "wrong_call_share_of_trades": {"IS": hi["wrong_call_share_of_trades"], "OOS": ho["wrong_call_share_of_trades"]},
         "usd_per_day": {"IS": hi["pnl_per_day_usd"], "OOS": ho["pnl_per_day_usd"]},
         "sign_flip": "Under the stamp-noise reading of the book's reprice timing, the same trader loses: "
                      f"{stamp['IS']['mean']['per_share_c']:+.2f}c IS"
                      + (f", {stamp['burned_OOS']['mean']['per_share_c']:+.2f}c burned OOS."
                         if "burned_OOS" in stamp else "."),
         "no_courtside_camera": no_cam,
         "no_camera_warning": (f"A courtside camera is not feasible for us, and without one the edge needs video "
                               f"under about 1 s: break-even video delay "
                               f"{no_cam['breakeven_video_delay_s']['IS']['s']:.2f} s IS / "
                               f"{no_cam['breakeven_video_delay_s']['OOS']['s']:.2f} s burned OOS; licensed betting "
                               f"video at 0.5 s nets {no_cam['video_0p5s']['IS']['c']:+.2f}c IS / "
                               f"{no_cam['video_0p5s']['OOS']['c']:+.2f}c OOS (OOS CI "
                               f"[{no_cam['video_0p5s']['OOS']['ci95'][0]:.2f}, {no_cam['video_0p5s']['OOS']['ci95'][1]:.2f}])."),
         "sources": f"{T0J} :: headline.(IS|burned_OOS).mean; headline_by_size_and_decomposition.*.decomposition.correct; "
                    f"stresses_corrected; research/v2/tier0/RESULTS.md section 1; {LS} (no-camera rows)"},
        {"tier": "Real fast tier, live day: prints landing 0-0.5 s before the book reprices", "label":
         "measured on one live day (482 official WTA points); 52 prints on points with a >= 3c move",
         "horizon": "vs the new mid", "gross_c": ft["D>=3c"]["gross_c"], "net_c": ft["D>=3c"]["net_c"],
         "n_prints": ft["D>=3c"]["n_prints"],
         "all_points": {"gross_c": ft["all_points"]["gross_c"], "net_c": ft["all_points"]["net_c"],
                        "n_prints": ft["all_points"]["n_prints"]},
         "sources": f"{VR} :: 3c_fast_tier_vs_model.measured_fast_tier_prints_landing_[-0.5,0)_with_move; "
                    "482 live points: research/v2/tier0/RESULTS.md (intro)"},
        {"tier": "Fast tier (walk-forward wallets), 0-3 s after detection", "label": "IS and OOS (H6); weighted by prints",
         "horizon": "30 s markout", "net_c": {"IS": A["IS"]["print_weighted"]["fast_net30_c"],
                                              "OOS": A["OOS"]["print_weighted"]["fast_net30_c"]},
         "net_c_to_resolution": {"IS": A["IS"]["print_weighted"]["fast_net_to_resolution_c"],
                                 "OOS": A["OOS"]["print_weighted"]["fast_net_to_resolution_c"]},
         "sources": "section A print-weighted (results/summary.json h6_walkforward)"},
        {"tier": "v2: copy the fast tier's prints at their fills (risk-sized, capped)", "label": LBL["v2_fills"],
         "horizon": "to resolution",
         "gross_c": {"IS": Bsec["IS"]["waterfall"][0]["c_per_share"], "OOS": Bsec["OOS"]["waterfall"][0]["c_per_share"]},
         "net_c": {"IS": Bsec["IS"]["waterfall"][3]["c_per_share"], "OOS": Bsec["OOS"]["waterfall"][3]["c_per_share"]},
         "net_ci95_c": {"IS": Bsec["IS"]["waterfall"][3]["ci95_c_match_clustered"],
                        "OOS": Bsec["OOS"]["waterfall"][3]["ci95_c_match_clustered"]},
         "sources": "section B (data/v2_trades_is_oos.parquet; results/v2/causal.json)"},
        {"tier": "Copy the fast tier 3 s later (mid + half spread, fee)", "label": "IS and OOS; what our speed gets today",
         "horizon": "to resolution", "net_c": {"IS": A["IS"]["print_weighted"]["copy_3s_later_net_to_resolution_c"],
                                               "OOS": A["OOS"]["print_weighted"]["copy_3s_later_net_to_resolution_c"]},
         "months_positive": {"IS": A["IS"]["months_copy_3s_later_positive"], "OOS": A["OOS"]["months_copy_3s_later_positive"]},
         "sources": "section A (results/summary.json h6_walkforward follow_res_c)"},
        {"tier": "Everyone else trading 0-3 s after detection", "label": "IS and OOS (H6); mean of monthly values, not print-weighted (no per-month print counts in the results file)", "horizon": "30 s markout",
         "net_c": {"IS": A["IS"]["print_weighted"]["others_net30_c_unweighted_month_mean"], "OOS": A["OOS"]["print_weighted"]["others_net30_c_unweighted_month_mean"]},
         "sources": "section A (results/summary.json h6_walkforward others_net30_c)"},
        {"tier": "Chase the jump after the venue delay (H1)", "label": "IS and OOS (pre-registered, failed)",
         "horizon": "30 s", "net_c": {"IS": r(J(SUM)["is"]["h1"]["J0.04_H30"]["mean_pnl_per_share_c"]),
                                      "OOS": r(J(SUM)["oos"]["h1"]["J0.04_H30"]["mean_pnl_per_share_c"])},
         "ci95_c": {"IS": r(J(SUM)["is"]["h1"]["J0.04_H30"]["ci95_pnl_per_share_c"]),
                    "OOS": r(J(SUM)["oos"]["h1"]["J0.04_H30"]["ci95_pnl_per_share_c"])},
         "sources": f"{SUM} :: (is|oos).h1.J0.04_H30"},
        {"tier": "Public score-feed traders (ESPN / widgets / streams)", "label": "IS (lead), IS and OOS (calibration)",
         "book_leads_public_score_median_s": J(SUM)["h4"]["median_lead_s"], "n_points": J(SUM)["h4"]["n"],
         "share_book_first": r(J(SUM)["h4"]["share_book_first"], 3),
         "calibration_bins_with_price_inside_win_rate_ci": {"IS": f"{inside(cal)}/{len(cal)}", "OOS": f"{inside(cal_o)}/{len(cal_o)}"},
         "calibration_max_abs_edge_c": {"IS": r(max(abs(b["edge_c"]) for b in cal), 2),
                                        "OOS": r(max(abs(b["edge_c"]) for b in cal_o), 2)},
         "reading": (f"By the time a public score arrives the book has already moved (median "
                     f"{J(SUM)['h4']['median_lead_s']} s earlier). Prices are close to calibrated: the bin's mean "
                     f"price lies inside the win-rate CI in {inside(cal)}/{len(cal)} IS and {inside(cal_o)}/{len(cal_o)} "
                     "OOS bins; the favourite-bias test (H2) found no edge after fees."),
         "sources": f"{SUM} :: h4; (is|oos).calibration"},
    ]
    out["G_tier_ladder"] = {"what": "Who earns what per share, fastest to slowest. Horizons differ by row and are stated.",
                            "rows": ladder}
    for i, row in enumerate(ladder):
        SOURCES[f"G.rows[{i}]"] = row["sources"]

    # ------------------------------------------------------------------------- H. CAPACITY
    FIN = "results/financials/financials.json"
    fin = J(FIN)["strategies"]["v2"]
    sc = fin["scaling"]
    sizes = ["0.5x", "1x", "2x", "5x", "all prints"]
    o_day = {k: sc[k]["OOS"]["pnl_usd_per_day"] for k in sizes}
    peak = max(sizes, key=o_day.get)
    pos = [k for k in sizes if o_day[k] > 0]
    largest_pos = pos[-1] if pos else None
    k_usd = lambda k: f"${sc[k]['OOS']['capital_usd'] / 1e3:.0f}k"
    cap_statement = (f"On the burned OOS, $/day peaks at {peak} and the largest size still positive is {largest_pos}; "
                     + ("every larger size loses. " if all(o_day[k] <= 0 for k in sizes[sizes.index(largest_pos) + 1:])
                        else "")
                     + f"Capacity is about {k_usd(peak)}-{k_usd(largest_pos)} of capital.")
    H = {"label": "IS and burned OOS (the size-scaled OOS rows are non-blind evaluations already logged)",
         "what": "Frozen v2 with every size cap scaled by the multiplier, same walk-forward fitting; no price-impact "
                 "model beyond never taking more than the copied print (larger rows would be worse in reality).",
         "financials_generated_utc": J(FIN)["generated_utc"],
         "rows": [{"size": k, **{p: {f: r(sc[k][p][f], 4) for f in ("n_trades", "per_share_c", "per_share_ci95_c",
                                                                      "pnl_usd_per_day", "notional_usd_per_day",
                                                                      "sharpe_ann", "capital_usd", "max_dd_pct")}
                                 for p in ("IS", "OOS")}} for k in ("0.5x", "1x", "2x", "5x", "all prints")],
         "capacity_estimate": {
             "OOS_capital_usd_range": [r(sc[peak]["OOS"]["capital_usd"], 0), r(sc[largest_pos]["OOS"]["capital_usd"], 0)],
             "OOS_peak_size": peak, "OOS_largest_positive_size": largest_pos,
             "statement": cap_statement,
             "superseded": "The sizing lens's '~$100k at Sharpe ~6' (docs/NOTE.md section 6) used onset labels, "
                           "was IS only, and its $102k row was the copy-everything baseline.",
             "outer_ceiling_fast_tier_print_usd_per_day": {"IS": r(fin["ceiling"]["IS"]["fast_tier_qualified_print_usd_per_day"], 0),
                                                           "OOS": r(fin["ceiling"]["OOS"]["fast_tier_qualified_print_usd_per_day"], 0)},
             "v2_share_of_match_volume_IS": r(J(NM)["is"]["v2_usd_traded_share_of_match_volume"], 5),
             "source": f"{FIN} :: strategies.v2.capacity_md, scaling, ceiling; {NM} :: is.v2_usd_traded_share_of_match_volume",
         }}
    SOURCES["H.rows"] = f"{FIN} :: strategies.v2.scaling (generated {J(FIN)['generated_utc']})"
    SOURCES["H.capacity_estimate"] = H["capacity_estimate"]["source"]
    out["H_capacity"] = H

    # ------------------------------------------------------------------------- I. FAILURES
    CS = "results/v2/cost_stress.json"
    cs = J(CS)
    MK = "results/maker/oos.json"
    mk = J(MK)
    ex = J(EXP)
    I = {"what": "What failed, shown next to the alpha.", "rows": [
        {"test": "v2, taker fees x2 (book fixed)", "IS": {"c": r(cs["is_eval/fee_x2"]["per_share_c"]), "ci95": r(cs["is_eval/fee_x2"]["per_share_ci_c"]),
                                                          "months_positive": f"{cs['is_eval/fee_x2']['months_positive']}/{cs['is_eval/fee_x2']['months_total']}"},
         "OOS": {"c": r(cs["burned_oos/fee_x2"]["per_share_c"]), "ci95": r(cs["burned_oos/fee_x2"]["per_share_ci_c"]),
                 "months_positive": f"{cs['burned_oos/fee_x2']['months_positive']}/{cs['burned_oos/fee_x2']['months_total']}"},
         "verdict": "OOS edge gone", "source": f"{CS} :: (is_eval|burned_oos)/fee_x2"},
        {"test": "v2, all costs x2 (fee x2 + half a 1c spread)", "IS": {"c": r(cs["is_eval/costs_x2"]["per_share_c"]), "ci95": r(cs["is_eval/costs_x2"]["per_share_ci_c"])},
         "OOS": {"c": r(cs["burned_oos/costs_x2"]["per_share_c"]), "ci95": r(cs["burned_oos/costs_x2"]["per_share_ci_c"])},
         "verdict": "OOS negative, CI excludes 0", "source": f"{CS} :: (is_eval|burned_oos)/costs_x2"},
        {"test": "v2, +1c worse entry", "IS": {"c": Bsec["IS"]["waterfall"][5]["c_per_share"]},
         "OOS": {"c": Bsec["OOS"]["waterfall"][5]["c_per_share"]}, "verdict": "OOS negative",
         "source": f"{CAUSAL} :: causal/*/slip0.01"},
        {"test": f"v2 blind test on {ex['universe']['u2_markets']:,} never-examined markets (U2, pre-registered)",
         "IS": {"c": r(ex["primary"]["u2_is"]["per_share_c"]), "ci95": r(ex["primary"]["u2_is"]["per_share_ci_c"]), "verdict": ex["primary"]["u2_is"]["label"]},
         "OOS": {"c": r(ex["primary"]["u2_oos"]["per_share_c"]), "ci95": r(ex["primary"]["u2_oos"]["per_share_ci_c"]), "verdict": ex["primary"]["u2_oos"]["label"]},
         "verdict": ex["primary"]["verdict"], "source": f"{EXP} :: primary"},
        {"test": "Maker v1 in side markets (blind OOS, pre-registered)",
         "OOS": {"c_per_fill": r(mk["primary"]["value_c"]), "ci95": r(mk["primary"]["ci95_c"]),
                 "share_weighted_c": r(mk["headline"]["share_weighted_net_c"]), "pnl_usd": r(mk["headline"]["total_pnl_usd"], 2),
                 "n_fills": mk["primary"]["n_fills"]},
         "verdict": mk["primary"]["verdict"], "source": f"{MK} :: primary, headline",
         "note": "The plotted value is the pre-registered primary: the unweighted mean per fill. Weighted by "
                 "shares it is negative and the P&L is a loss."},
        {"test": "v1 (fast-tier trades at full size, <= $1k) out of sample, blind",
         "OOS": {"c": r(J(SUM)["oos"]["h6_shadow"]["mean_pnl_per_share_c"]), "pnl_usd": r(J(SUM)["oos"]["h6_shadow"]["total_pnl_usd"], 0)},
         "verdict": "lost money", "source": f"{SUM} :: oos.h6_shadow",
         "note": "The plotted value is the unweighted mean per trade; the dollar P&L is a loss (big tickets on "
                 "cheap tokens)."},
        {"test": "v2 at 5x size", "OOS": {"c": r(sc["5x"]["OOS"]["per_share_c"]), "usd_per_day": r(sc["5x"]["OOS"]["pnl_usd_per_day"], 1)},
         "IS": {"c": r(sc["5x"]["IS"]["per_share_c"])}, "verdict": "OOS negative", "source": f"{FIN} :: strategies.v2.scaling.5x"},
        {"test": "v2 OOS clustered by copied wallet", "OOS": {"ci95": F["wallet_clustered_ci95_c"]["OOS"]},
         "verdict": "CI includes 0", "source": f"{PMC} :: p07_wallet_clustered_ci.burned_oos"},
        {"test": "v2 OOS deflated Sharpe at N = 3,386 trials", "OOS": {"dsr": Bsec["luck"]["OOS_deflated_sharpe_N3386"]},
         "verdict": "40 days cannot rule out luck", "source": f"{RIG} :: psr_dsr.rows[v2_oos]"},
        {"test": "H1 chase the jump after the delay", "IS": {"c": r(J(SUM)["is"]["h1"]["J0.04_H30"]["mean_pnl_per_share_c"])},
         "OOS": {"c": r(J(SUM)["oos"]["h1"]["J0.04_H30"]["mean_pnl_per_share_c"])}, "verdict": "Fails",
         "source": f"{SUM} :: (is|oos).h1.J0.04_H30"},
        {"test": "Tier-0 without our own courtside camera: licensed betting video at 0.5 s (counterfactual)",
         "label": LBL["tier0"],
         "IS": {"c": no_cam["video_0p5s"]["IS"]["c"], "ci95": no_cam["video_0p5s"]["IS"]["ci95"],
                "usd_per_day": no_cam["video_0p5s"]["IS"]["usd_per_day"]},
         "OOS": {"c": no_cam["video_0p5s"]["OOS"]["c"], "ci95": no_cam["video_0p5s"]["OOS"]["ci95"],
                 "usd_per_day": no_cam["video_0p5s"]["OOS"]["usd_per_day"]},
         "verdict": "OOS about zero, CI includes 0", "source": SOURCES["G.tier0_no_camera"],
         "note": (f"Break-even video delay {no_cam['breakeven_video_delay_s']['IS']['s']:.2f} s IS, "
                  f"{no_cam['breakeven_video_delay_s']['OOS']['s']:.2f} s burned OOS (non-blind). Tier-0 rows are "
                  "counterfactual: assumes licensed feed + courtside camera (not purchased); parameters measured.")},
        {"test": "Forward test (blind, matches from 2026-10-03 14:00 UTC)", "verdict": "pending",
         "source": "results/v2/forward.json (not yet written)"},
    ]}
    for i, row in enumerate(I["rows"]):
        SOURCES[f"I.rows[{i}]"] = row["source"]
    out["I_failures"] = I

    # ------------------------------------------------------------------------- headline
    out["headline"] = {
        "one_line": "The edge is real at the fast tier's speed and shrinking; v2 (measured at their fills, not "
                    "our execution) is positive IS and on the burned OOS, but fragile to costs and concentrated.",
        "fast_tier_net30_c_months_positive": {"IS": A["IS"]["months_fast_positive"], "OOS": A["OOS"]["months_fast_positive"]},
        "fast_tier_net30_c_print_weighted": {"IS": A["IS"]["print_weighted"]["fast_net30_c"], "OOS": A["OOS"]["print_weighted"]["fast_net30_c"]},
        "others_net30_c_month_mean": {"IS": A["IS"]["print_weighted"]["others_net30_c_unweighted_month_mean"], "OOS": A["OOS"]["print_weighted"]["others_net30_c_unweighted_month_mean"]},
        "copy_3s_later_c": {"IS": A["IS"]["print_weighted"]["copy_3s_later_net_to_resolution_c"],
                            "OOS": A["OOS"]["print_weighted"]["copy_3s_later_net_to_resolution_c"]},
        "v2_gross_fee_net_c": {p: [Bsec[p]["waterfall"][0]["c_per_share"], Bsec[p]["waterfall"][1]["c_per_share"],
                                   Bsec[p]["waterfall"][3]["c_per_share"]] for p in ("IS", "OOS")},
        "v2_net_ci95_c": {p: Bsec[p]["waterfall"][3]["ci95_c_match_clustered"] for p in ("IS", "OOS")},
        "v2_net_bps": {p: Bsec[p]["waterfall"][3]["bps_of_notional"] for p in ("IS", "OOS")},
        "v2_sharpe": {p: Bsec[p]["sharpe_ann"] for p in ("IS", "OOS")},
        "v2_pnl_usd": {p: Bsec[p]["pnl_usd"] for p in ("IS", "OOS")},
        "factor_alpha_IS_committed_spec": {k: out["C_factor_neutral"]["IS_committed_spec"][k]
                                           for k in ("alpha_pct_per_day", "alpha_t", "n_days")},
        "factor_alpha_t_committed_file_incl_oos_weekdays": fr["t"]["alpha_daily"],
        "fast_tier_slope_c_per_month": {
            "IS": out["E_decay"]["over_calendar_time"]["IS_months"]["slope_c_per_month"],
            "IS_t": out["E_decay"]["over_calendar_time"]["IS_months"]["slope_t"],
            "IS_plus_OOS_rows_pooled": out["E_decay"]["over_calendar_time"]["IS_plus_OOS_rows"]["slope_c_per_month"]},
        "fast_tier_months_positive_to_resolution": {p: A[p]["months_fast_positive_to_resolution"] for p in ("IS", "OOS")},
        "v2_oos_dsr_N3386_range": [min(Bsec["luck"]["dsr_N3386_by_variance_assumption"]["OOS"].values()),
                                   max(Bsec["luck"]["dsr_N3386_by_variance_assumption"]["OOS"].values())],
        "top5_wallet_share_of_pnl": {p: F[p]["wallets"]["top5_share_of_pnl"] for p in ("IS", "OOS")},
        "tier0_net_c_counterfactual": {"IS": hi["per_share_c"], "OOS": ho["per_share_c"]},
        "oos_capital_capacity_usd": H["capacity_estimate"]["OOS_capital_usd_range"],
        "fees_x2_OOS_c": I["rows"][0]["OOS"]["c"],
        "labels": [LBL["v2_fills"], "OOS = " + LBL["OOS"], "tier-0 = " + LBL["tier0"]],
    }
    SOURCES["headline"] = "copied from sections A-I (see their sources)"
    out["checks"] = checks
    out["sources"] = SOURCES
    out["figures"] = figures(out, P, curves)
    out["runtime_s"] = round(time.time() - T0, 1)
    return out


# ===================================================================================== figures
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
C_IS, C_OOS = "#2a78d6", "#eb6834"             # IS blue / OOS orange (repo convention, scripts/financials.py)
C_FAST, C_OTH, C_COPY = "#2a78d6", "#eb6834", "#1baf7a"
GRAY = "#8a8984"


def _ax(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.axhline(0, color=INK2, lw=0.8)


def figures(out: dict, P: dict, curves: dict) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"text.parse_math": False, "font.size": 10, "text.color": INK, "axes.labelcolor": INK2, "font.family": "DejaVu Sans"})
    files = []

    def save(fig, name, foot):
        fig.text(0.01, 0.01, foot, fontsize=7.5, color=INK2, ha="left", va="bottom", wrap=True)
        p = OUT / name
        fig.savefig(p, dpi=150, facecolor=SURF)
        plt.close(fig)
        files.append(str(p.relative_to(ROOT)))

    # 1. source: fast vs others vs copy, by month, IS then OOS
    A = out["A_source"]
    rows = [(m, "IS") for m in A["IS"]["months"]] + [(m, "OOS") for m in A["OOS"]["months"]]
    x = np.arange(len(rows))
    lab = [pd.Period(m["month"]).strftime("%b") + ("\nIS" if p == "IS" and m["month"] == "2026-08" else "")
           + ("\nOOS" if p == "OOS" and m["month"] == "2026-08" else "") + ("*" if m["month"] == "2026-10" else "")
           for m, p in rows]
    fig, ax = plt.subplots(figsize=(11, 5.6), facecolor=SURF)
    _ax(ax)
    n_is = len(A["IS"]["months"])
    ax.axvspan(n_is - 0.5, len(rows) - 0.5, color="#f0efec", zorder=0)
    ax.text(n_is - 0.35, 2.55, "held-out (OOS)", color=INK2, fontsize=9, va="top")
    ax.text(-0.35, 2.55, "in sample", color=INK2, fontsize=9, va="top")
    series = [("fast_net30_c", "Fast tier, net 30 s", C_FAST, "o"),
              ("others_net30_c", "Everyone else, same 0-3 s window, net 30 s", C_OTH, "s"),
              ("copy_3s_later_net_to_resolution_c", "Copy the fast tier 3 s later, net to resolution", C_COPY, "D")]
    for col, name, c, mk in series:
        y = [m[col] for m, _ in rows]
        ax.plot(x[:n_is], y[:n_is], color=c, lw=2, marker=mk, ms=6, label=name, zorder=3)
        ax.plot(x[n_is:], y[n_is:], color=c, lw=2, marker=mk, ms=6, zorder=3)
    ax.set_xticks(x, lab)
    ax.set_ylabel("c per share, after taker fee")
    ax.set_ylim(-2.8, 2.7)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, frameon=False, fontsize=9)
    ax.set_title("Who wins in the 3 s after a tennis point: only the fastest traders", loc="left", fontsize=13,
                 color=INK, pad=28)
    fig.subplots_adjust(top=0.85, bottom=0.16)
    save(fig, "fig_alpha_source.png",
         f"Fast tier > 0 in {A['IS']['months_fast_positive']} IS and {A['OOS']['months_fast_positive']} OOS months; "
         f"everyone else and the 3 s-late copy < 0 every month. *Oct = 3 days. Source: results/summary.json h6_walkforward.")

    # 2. waterfall IS vs OOS
    Bs = out["B_size"]
    steps = ["gross edge", "taker fee", "net at fast-tier fills", "net, +0.5c worse entry", "net, +1c worse entry"]
    idx = [0, 1, 3, 4, 5]
    fig, ax = plt.subplots(figsize=(11, 5.6), facecolor=SURF)
    _ax(ax)
    w = 0.38
    for j, (p, c) in enumerate((("IS", C_IS), ("OOS", C_OOS))):
        v = [Bs[p]["waterfall"][i]["c_per_share"] for i in idx]
        xs = np.arange(len(steps)) + (j - 0.5) * w
        bars = ax.bar(xs, v, w - 0.04, color=c, label=("in sample (Feb 1-Aug 25)" if p == "IS" else
                                                       "burned OOS (Aug 25-Oct 3, non-blind)"))
        for xi, vi, i in zip(xs, v, idx):
            ci = Bs[p]["waterfall"][i].get("ci95_c_match_clustered")
            if ci:
                ax.plot([xi, xi], ci, color=INK, lw=1.2)
            top = max(vi, ci[1]) if ci else vi
            bot = min(vi, ci[0]) if ci else vi
            ax.text(xi, top + 0.05 if vi >= 0 else bot - 0.05, f"{vi:+.2f}", ha="center",
                    va="bottom" if vi >= 0 else "top", fontsize=9, color=INK)
    ax.set_xticks(np.arange(len(steps)), steps)
    ax.set_ylabel("c per share (bars: 95% CI clustered by match)")
    ax.set_ylim(-1.15, 2.45)
    ax.legend(frameon=False, loc="upper right")
    ax.set_title("v2 per share: gross edge, fee, net, and what half a tick of slippage does", loc="left", fontsize=13)
    fig.subplots_adjust(bottom=0.14)
    save(fig, "fig_alpha_waterfall.png",
         "v2 is measured at the fast tier's own fills: the opportunity at their speed, not our execution. "
         f"Net {Bs['IS']['waterfall'][3]['bps_of_notional']:.0f} bps IS / {Bs['OOS']['waterfall'][3]['bps_of_notional']:.0f} bps OOS of notional. "
         "Source: data/v2_trades_is_oos.parquet, results/v2/causal.json.")

    # 3. tier ladder (net c/share)
    G = out["G_tier_ladder"]["rows"]
    lad = [("Tier-0 camera + CV (counterfactual)", G[0]["net_c_all_calls"]["IS"], G[0]["net_c_all_calls"]["OOS"], None),
           ("Real fast tier, live day, 0-0.5 s pre-reprice", None, None, G[1]["net_c"]),
           ("Fast tier, 0-3 s after detection (30 s)", G[2]["net_c"]["IS"], G[2]["net_c"]["OOS"], None),
           ("v2 at fast-tier fills (to resolution)", G[3]["net_c"]["IS"], G[3]["net_c"]["OOS"], None),
           ("Copy fast tier 3 s later (to resolution)", G[4]["net_c"]["IS"], G[4]["net_c"]["OOS"], None),
           ("Everyone else, 0-3 s (30 s)", G[5]["net_c"]["IS"], G[5]["net_c"]["OOS"], None),
           ("Chase the jump after the delay (H1)", G[6]["net_c"]["IS"], G[6]["net_c"]["OOS"], None)]
    fig, ax = plt.subplots(figsize=(11, 6), facecolor=SURF)
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.xaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.axvline(0, color=INK2, lw=0.8)
    yy = np.arange(len(lad))[::-1]
    h = 0.36
    for y, (name, vi, vo, live) in zip(yy, lad):
        if live is not None:
            ax.barh(y, live, h * 1.6, color=GRAY, label="one live day (52 prints)")
            ax.text(live + 0.05, y, f"{live:+.2f}", va="center", fontsize=9)
            continue
        hatch = "//" if name.startswith("Tier-0") else None
        ax.barh(y + h / 2, vi, h - 0.03, color=C_IS, hatch=hatch, edgecolor=SURF,
                label="in sample" if y == yy[2] else None)
        ax.barh(y - h / 2, vo, h - 0.03, color=C_OOS, hatch=hatch, edgecolor=SURF,
                label="held-out / burned OOS" if y == yy[2] else None)
        for v, dy in ((vi, h / 2), (vo, -h / 2)):
            ax.text(v + (0.05 if v >= 0 else -0.05), y + dy, f"{v:+.2f}", va="center",
                    ha="left" if v >= 0 else "right", fontsize=8.5)
    ax.set_yticks(yy, [n for n, *_ in lad], fontsize=9.5)
    ax.tick_params(colors=INK2)
    ax.set_xlabel("net c per share after taker fee")
    ax.set_xlim(-2.6, 2.0)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.set_title("The tier ladder: who earns what per share", loc="left", fontsize=13)
    fig.subplots_adjust(left=0.33, bottom=0.14)
    save(fig, "fig_alpha_ladder.png",
         "Hatched = counterfactual: assumes licensed feed + courtside camera (not purchased); parameters measured. "
         f"Public score feeds trail the book by a median {G[7]['book_leads_public_score_median_s']} s; prices are close to calibrated. "
         "Horizons differ by row (stated).")

    # 4. where: price decile, regime, time of day, month
    Dd = out["D_where"]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.4), facecolor=SURF)
    panels = [("by_price_decile_q", "price paid q (IS deciles)"), ("by_regime_delay_fee", "venue regime (order delay / fee)"),
              ("by_time_of_day_utc", "time of day (UTC)"), ("by_month", "month")]
    for ax, (key, title) in zip(axes.flat, panels):
        _ax(ax)
        groups = list(dict.fromkeys([g["group"] for p in ("IS", "OOS") for g in Dd[p][key] if g.get("n_trades")]))
        if key == "by_month":
            groups = sorted(groups)
        xg = np.arange(len(groups))
        for j, (p, c) in enumerate((("IS", C_IS), ("OOS", C_OOS))):
            m = {g["group"]: g for g in Dd[p][key] if g.get("n_trades")}
            xs = [i + (j - 0.5) * 0.3 for i, g in enumerate(groups) if g in m]
            vs = [m[g]["net_c_per_share"] for g in groups if g in m]
            cis = [m[g]["net_ci95_c_match_clustered"] for g in groups if g in m]
            for xi, ci in zip(xs, cis):
                if ci and ci[0] is not None:
                    ax.plot([xi, xi], ci, color=c, lw=1.4, alpha=0.8)
            ax.plot(xs, vs, ls="none", marker="o", ms=7, color=c, mec=SURF, mew=1.5,
                    label="in sample" if p == "IS" else "burned OOS")
        lbl = [g.replace(" UTC", "") if key != "by_month" else pd.Period(g).strftime("%b") for g in groups]
        ax.set_xticks(xg, lbl, fontsize=8, rotation=30 if key == "by_price_decile_q" else 0)
        ax.set_title(title, loc="left", fontsize=11)
        ax.set_ylabel("net c/share, 95% CI")
    axes[0, 0].legend(frameon=False, fontsize=9)
    fig.suptitle("Where v2's edge lives in the book (measured at fast-tier fills)", x=0.01, ha="left", fontsize=13)
    fig.subplots_adjust(hspace=0.38, bottom=0.1, top=0.9)
    save(fig, "fig_alpha_where.png", "Descriptive splits of the frozen v2 trades; CIs clustered by match. "
         "Source: data/v2_trades_is_oos.parquet.")

    # 5. decay within a point
    Ew = out["E_decay"]["within_a_point"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), facecolor=SURF, sharey=True)
    for ax, p in zip(axes, ("IS", "OOS")):
        _ax(ax)
        rows = Ew[p]["rows"][:-1]
        xb = np.arange(len(rows))
        for g, name, c, mk in (("fast", "Fast tier", C_FAST, "o"), ("others", "Everyone else", C_OTH, "s")):
            v = [rw[g]["net30_c"] for rw in rows]
            lo = [rw[g]["ci95_c"][0] for rw in rows]
            hi = [rw[g]["ci95_c"][1] for rw in rows]
            ax.fill_between(xb, lo, hi, color=c, alpha=0.15, lw=0)
            ax.plot(xb, v, color=c, lw=2, marker=mk, ms=6, label=name)
        ax.set_xticks(xb, ["0 s", "1 s", "2 s", "3-4 s", "5-9 s", "10-29 s"])
        ax.set_xlabel("seconds since jump detection (block time)")
        ax.set_title("in sample" if p == "IS" else "burned OOS (non-blind)", loc="left", fontsize=11)
    axes[0].set_ylabel("net 30 s markout, c/share (95% CI)")
    axes[0].legend(frameon=False)
    fig.suptitle("Decay within a point: the edge is in the first second", x=0.01, ha="left", fontsize=13)
    fig.subplots_adjust(bottom=0.2, top=0.86)
    save(fig, "fig_alpha_decay.png", "Block-time tapes resolve whole seconds only; '0 s' = same block second as detection. "
         "Source: results/decay/decay.json (tennis IS / burned_OOS).")

    # 6. concentration: cumulative share of P&L by copied wallet rank
    fig, ax = plt.subplots(figsize=(9, 5.4), facecolor=SURF)
    _ax(ax)
    for p, c in (("IS", C_IS), ("OOS", C_OOS)):
        cv = curves[p]
        ax.plot(np.arange(1, len(cv) + 1), cv * 100, color=c, lw=2,
                label=("in sample" if p == "IS" else "burned OOS") + f": top 5 = {cv[4] * 100:.0f}%")
    ax.axhline(100, color=INK2, lw=0.8, ls="--")
    ax.set_xscale("log")
    ax.set_xlabel("copied wallets, ranked by P&L contribution (log)")
    ax.set_ylabel("cumulative share of v2 P&L, %")
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("Concentration: a few wallets carry the P&L, more so out of sample", loc="left", fontsize=13)
    fig.subplots_adjust(bottom=0.18)
    k100 = int(np.argmax(curves["OOS"] >= 1) + 1)
    save(fig, "fig_alpha_concentration.png", f"Above 100% = the remaining wallets lost money in total. OOS, the top {k100} "
         "wallets already exceed 100%. "
         "Source: data/v2_trades_is_oos.parquet.")

    # 7. capacity
    Hall = out["H_capacity"]["rows"]
    H = [h for h in Hall if h["size"] != "all prints"]
    allp = [h for h in Hall if h["size"] == "all prints"][0]
    usd = lambda v: ("-" if v < 0 else "") + f"${abs(v):,.0f}"
    fig, ax = plt.subplots(figsize=(9, 5.2), facecolor=SURF)
    _ax(ax)
    xs = np.arange(len(H))
    for j, (p, c) in enumerate((("IS", C_IS), ("OOS", C_OOS))):
        v = [h[p]["pnl_usd_per_day"] for h in H]
        ax.bar(xs + (j - 0.5) * 0.38, v, 0.34, color=c, label="in sample" if p == "IS" else "burned OOS")
        for xi, vi in zip(xs + (j - 0.5) * 0.38, v):
            ax.text(xi, vi + (8 if vi >= 0 else -8), usd(vi), ha="center",
                    va="bottom" if vi >= 0 else "top", fontsize=8)
    ax.set_xticks(xs, [h["size"] for h in H])
    ax.set_ylabel("v2 P&L per day, $ (before fixed costs)")
    ax.set_xlabel("every size cap scaled by")
    ax.legend(frameon=False)
    ax.set_title("Capacity: out of sample, bigger is not better past 1-2x", loc="left", fontsize=13)
    fig.subplots_adjust(bottom=0.2)
    save(fig, "fig_alpha_capacity.png", "No price-impact model beyond never exceeding the copied print. Taking every "
         f"qualifying print in full: {usd(allp['IS']['pnl_usd_per_day'])}/day IS, {usd(allp['OOS']['pnl_usd_per_day'])}/day OOS. "
         "Source: results/financials/financials.json strategies.v2.scaling.")
    return files


def log_peek():
    log = ROOT / "results/oos_peeks.log"
    txt = log.read_text() if log.exists() else ""
    if PEEK_TEXT in txt:  # re-running the same descriptive read is not a new look
        return False
    with open(log, "a") as f:
        f.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} {PEEK_TEXT}\n")
    return True


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


if __name__ == "__main__":
    res = clean(main())
    logged = log_peek()
    (OUT / "alpha.json").write_text(json.dumps(res, indent=1, default=float, allow_nan=False))
    print(json.dumps(res["headline"], indent=1))
    print("checks ok:", all(c["ok"] for c in res["checks"]), "| peek logged:", logged, "| runtime", res["runtime_s"], "s")
