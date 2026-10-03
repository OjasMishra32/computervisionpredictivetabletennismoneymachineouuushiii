"""The [COMPUTE-NOW] items of research/financials/PM_REVIEW.md, from data already in the repo.

    .venv/bin/python scripts/pm_compute.py quick   # P07, P14 bands, P24, P25, P26   (~30 s, 1 process)
    .venv/bin/python scripts/pm_compute.py sens    # P15 threshold surface + P14 point-in-time universe
                                                   # (IS prints only; ~20 IS rebuilds, 1 process)

Both write into results/financials/pm_compute.json (each mode replaces only its own keys).

No strategy rule changes and nothing is tuned: every variant below is a one-step perturbation REPORTED next to
the frozen v2, never selected. Inputs:
  data/v2_trades_is_oos.parquet            v2 causal trades (scripts/v2_causal.py), IS + burned OOS
  data/is_prints.parquet                   IS prints only (sens mode never opens data/locked/)
  data/derived/tier0_prestart_volume.parquet  $ traded before the scheduled start, per universe match (src/tier0.py)
  data/factors/*.csv                       Kenneth French daily factors (cached by scripts/factor_regression.py)
  data/v2_lowloss/trades_a_v2_safe.parquet v2-safe trades (P25 per-book calibration, IS rows only)
  data/v2_crossmarket/wf_lean_maker.parquet maker v1 IS book (P25 per-book calibration)
  results/v2/causal.json                   reference numbers that every IS rebuild must reproduce

Held-out data: only P07 reads burned-OOS rows (the wallet-clustered CI the note already quotes). The first run
appends one labelled line to results/oos_peeks.log. Every other item reads IS rows only.

Conventions are the engine's (research/v2/sizing/engine.py metrics): IS = U1 matches starting before the OOS
cutoff, trades from 2026-02; per-share = share-weighted net cents; CIs are 95% bootstrap, clustered as stated;
Sharpe = daily mean / sd x sqrt(365) on zero-filled calendar days; capital = 3 x peak locked.
"""
from __future__ import annotations

import datetime as dt
import gc
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import fasttier, tiers, v2  # noqa: E402
from src.tape import universe  # noqa: E402

E = v2.E
OUT = ROOT / "results/financials/pm_compute.json"
PEEKS = ROOT / "results/oos_peeks.log"
N_BOOT = 2000
REF = json.loads((ROOT / "results/v2/causal.json").read_text())


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def save(update: dict):
    cur = json.loads(OUT.read_text()) if OUT.exists() else {}
    cur.update(update)
    cur["script"] = "scripts/pm_compute.py"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cur, indent=1, default=float))


def cluster_ratio_ci(num: np.ndarray, den: np.ndarray, groups: np.ndarray, seed: int = 0, n: int = N_BOOT) -> list[float]:
    """95% CI of sum(num)/sum(den), resampling whole groups (matches or wallets)."""
    g = pd.DataFrame({"g": groups, "n": num, "d": den}).groupby("g")[["n", "d"]].sum()
    Nn, Dd = g.n.to_numpy(), g.d.to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n, len(g)))
    r = Nn[idx].sum(1) / Dd[idx].sum(1)
    return [float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))]


def load_trades():
    u = universe()
    oos_conds = set(u.loc[u.oos, "cond"])
    tr = pd.read_parquet(ROOT / "data/v2_trades_is_oos.parquet")
    is_mask = (tr.month >= E.EVAL_START) & ~tr.cond.isin(oos_conds)
    return u, oos_conds, tr, is_mask


# ============================================================================== quick: P07 P14 P24 P25 P26
def p07_wallet_ci(tr, is_mask, oos_conds) -> dict:
    """Wallet-clustered CI for both periods (method of research/financials/pm_checks.py section 2)."""
    out = {"method": "bootstrap over copied wallets, 2,000 draws, seed 0, share-weighted (pm_checks.py section 2)"}
    for name, part, ref in (("is", tr[is_mask], "causal/is_eval/slip0.0"),
                            ("burned_oos", tr[tr.cond.isin(oos_conds)], "causal/burned_oos/slip0.0")):
        assert abs(part.pnl.sum() - REF[ref]["total_pnl_usd"]) < 1e-6, f"{name}: P&L does not reproduce causal.json"
        g = part.groupby("wallet").agg(p=("pnl", "sum"), s=("shares", "sum"))
        P, S = g.p.to_numpy(), g.s.to_numpy()
        rng = np.random.default_rng(0)
        bs = [P[i].sum() / S[i].sum() * 100 for i in (rng.integers(0, len(g), len(g)) for _ in range(N_BOOT))]
        top = g.p.sort_values(ascending=False)
        out[name] = {"n_wallets": int(len(g)), "n_trades": int(len(part)), "per_share_c": float(P.sum() / S.sum() * 100),
                     "ci95_c_wallet_clustered": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                     "ci95_c_match_clustered_causal_json": REF[ref]["per_share_ci_c"],
                     "top1_share_of_pnl": float(top.iloc[0] / P.sum()), "top5_share_of_pnl": float(top.iloc[:5].sum() / P.sum())}
    out["note_md_table2_footnote_value"] = [-0.60, 2.11]
    lo, hi = out["burned_oos"]["ci95_c_wallet_clustered"]
    out["note_value_reproduced_to_2dp"] = bool(round(lo, 2) == -0.60 and round(hi, 2) == 2.11)
    return out


BANDS = [0, 1_000, 5_000, 20_000, 100_000, np.inf]
BAND_LAB = ["< $1k", "$1-5k", "$5-20k", "$20-100k", ">= $100k"]
LIFE_BANDS = [5_000, 20_000, 100_000, 1_000_000, np.inf]
LIFE_LAB = ["$5-20k", "$20-100k", "$0.1-1M", "> $1M"]


def band_table(part: pd.DataFrame, col: str, bins, labels) -> list[dict]:
    b = pd.cut(part[col], bins, labels=labels, right=False)
    rows = []
    for lab in labels:
        x = part[b == lab]
        if x.empty:
            rows.append({"band": lab, "n_trades": 0})
            continue
        rows.append({"band": lab, "n_matches": int(x.cond.nunique()), "n_trades": int(len(x)),
                     "share_of_shares": float(x.shares.sum() / part.shares.sum()), "pnl_usd": float(x.pnl.sum()),
                     "per_share_c": float(x.pnl.sum() / x.shares.sum() * 100),
                     "ci95_c_match_clustered": [100 * v for v in cluster_ratio_ci(x.pnl.to_numpy(), x.shares.to_numpy(), x.cond.to_numpy())]})
    return rows


def p14_bands(u, tr, is_mask) -> dict:
    pre = pd.read_parquet(ROOT / "data/derived/tier0_prestart_volume.parquet").set_index("cond").prestart_usd
    x = tr[is_mask].copy()
    x["prestart_usd"] = x.cond.map(pre)
    x["lifetime_usd"] = x.cond.map(u.set_index("cond").volume)
    assert x.prestart_usd.notna().all() and x.lifetime_usd.notna().all()
    um = u[~u.oos & (u.start >= pd.Timestamp("2026-02-01", tz="UTC"))].copy()
    um["prestart_usd"] = um.cond.map(pre)
    subset = {}
    for thr in (5_000, 20_000):   # the frozen book's own trades in matches a pre-start rule would keep (no re-fitting)
        sm = E.metrics(x[x.prestart_usd >= thr], n_boot=N_BOOT)
        subset[f"prestart>={thr}"] = {k: sm[k] for k in ("n_trades", "n_matches", "per_share_c", "per_share_ci_c",
                                                          "total_pnl_usd", "sharpe_ann", "capital_usd")}
    return {
        "frozen_book_subset_no_refit": subset,
        "scope": "IS v2 trades (data/v2_trades_is_oos.parquet, IS conds, months >= 2026-02)",
        "prestart_definition": "$ traded before the scheduled start (size x price on the public tape), src/tier0.py prestart_volume",
        "by_prestart_volume": band_table(x, "prestart_usd", BANDS, BAND_LAB),
        "by_lifetime_volume_reproduces_risk_stats": band_table(x, "lifetime_usd", LIFE_BANDS, LIFE_LAB),
        "is_universe_matches_feb_aug": int(len(um)),
        "is_universe_matches_prestart_ge_5k": int((um.prestart_usd >= 5_000).sum()),
        "is_universe_prestart_quantiles_usd": {q: float(um.prestart_usd.quantile(q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
        "spearman_prestart_vs_lifetime_is_universe": float(um.prestart_usd.rank().corr(um.volume.rank())),
    }


def french(name: str, cols: list[str]) -> pd.DataFrame:
    rows = []
    for line in (ROOT / "data/factors" / name).read_text(errors="ignore").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == len(cols) + 1 and parts[0].isdigit() and len(parts[0]) == 8:
            rows.append([pd.Timestamp(parts[0])] + [float(v) / 100 for v in parts[1:]])
    return pd.DataFrame(rows, columns=["date"] + cols).set_index("date")


def nw_ols(y: np.ndarray, X: np.ndarray, lags: int = 5) -> tuple[np.ndarray, np.ndarray, float]:
    """OLS with Newey-West (Bartlett, `lags`) standard errors, exactly as scripts/factor_regression.py."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        G = (X[L:] * resid[L:, None]).T @ (X[:-L] * resid[:-L, None])
        S += w * (G + G.T)
    se = np.sqrt(np.diag(XtX_inv @ S @ XtX_inv))
    return beta, se, float(1 - resid.var() / y.var())


def p24_factors(tr, is_mask) -> dict:
    ff = french("F-F_Research_Data_Factors_daily.csv", ["MktRF", "SMB", "HML", "RF"]).join(
        french("F-F_Momentum_Factor_daily.csv", ["Mom"]), how="inner")
    cap = REF["causal/is_eval/slip0.0"]["capital_usd"]
    part = tr[is_mask]
    daily = E.daily_series(part)                         # calendar-day, zero-filled, IS only (206 days)
    daily.index = daily.index.tz_localize(None)
    r = daily / cap
    names = ["alpha_daily", "MktRF", "SMB", "HML", "Mom"]
    out = {"capital_usd": cap, "factor_source": "Kenneth French data library, daily F-F 3 factors + momentum "
           "(https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html), cached in data/factors/",
           "newey_west_lags": 5}

    def fit(df: pd.DataFrame, excess: bool, ann: int) -> dict:
        y = (df.r - df.RF).to_numpy() if excess else df.r.to_numpy()
        X = np.column_stack([np.ones(len(df)), df[["MktRF", "SMB", "HML", "Mom"]].to_numpy()])
        b, se, r2 = nw_ols(y, X)
        return {"n_days": int(len(df)), "period": [str(df.index.min().date()), str(df.index.max().date())],
                "coef": dict(zip(names, map(float, b))), "t": dict(zip(names, map(float, b / se))), "r2": r2,
                "alpha_annualised_pct": float(b[0] * ann * 100), "annualisation": ann,
                "max_abs_factor_t": float(np.max(np.abs((b / se)[1:]))),
                "corr_with_market": float(np.corrcoef(df.r, df.MktRF)[0, 1])}

    cal = pd.DataFrame({"r": r}).join(ff, how="left")
    cal["weekend_or_holiday"] = cal.MktRF.isna()
    cal[["MktRF", "SMB", "HML", "RF", "Mom"]] = cal[["MktRF", "SMB", "HML", "RF", "Mom"]].fillna(0.0)
    out["calendar_days_excess_x365"] = {**fit(cal, True, 365),
                                        "spec": "IS only; every calendar day (zero-P&L days kept); factors and RF = 0 on "
                                                "weekends and US holidays; y = v2 return on IS capital minus RF; alpha x 365"}
    out["calendar_days_excess_x365"]["days_without_factor_data"] = int(cal.weekend_or_holiday.sum())
    wk = pd.DataFrame({"r": r}).join(ff, how="inner")
    out["weekdays_only_excess_x252"] = {**fit(wk, True, 252),
                                        "spec": "IS only; days with factor data only (weekend P&L dropped); excess of RF; alpha x 252"}
    # the committed script's spec, restricted to IS only, for a like-for-like comparison
    act = part.groupby(pd.to_datetime(part.ts, unit="s").dt.floor("D")).pnl.sum() / cap
    old = pd.DataFrame({"r": act}).join(ff, how="inner").dropna()
    out["committed_spec_is_only"] = {**fit(old, False, 252),
                                     "spec": "scripts/factor_regression.py as committed (active trade days joined to factor days, "
                                             "raw return, alpha x 252) but IS conds only"}
    out["committed_results_file"] = json.loads((ROOT / "results/v2/factor_regression.json").read_text())
    return out


def trailing_edge_rule(tr: pd.DataFrame, days: pd.DatetimeIndex, half_c=0.3, stop_c=0.0, window=30) -> pd.DataFrame:
    """Causal trailing-window net edge (cents/share) known at the START of each day: trades entered in the
    previous `window` days whose market had resolved before the day began (full-size book, so a stopped book
    keeps measuring). Size multiplier: 1 if edge >= half_c, 0.5 if stop_c < edge < half_c, 0 if edge <= stop_c."""
    ts, end = tr.ts.to_numpy(), tr.end_ts.to_numpy()
    sh, pnl = tr.shares.to_numpy(), tr.pnl.to_numpy()
    rows = []
    for d in days:
        t0 = d.timestamp()
        m = (ts >= t0 - window * 86400) & (ts < t0) & (end < t0)
        s = sh[m].sum()
        e = pnl[m].sum() / s * 100 if s > 0 else np.nan
        mult = 1.0 if (np.isnan(e) or e >= half_c) else (0.5 if e > stop_c else 0.0)
        rows.append({"date": d, "edge_c": e, "n_trades": int(m.sum()), "mult": mult})
    return pd.DataFrame(rows).set_index("date")


def series_stats(daily: pd.Series, cap: float) -> dict:
    eq = daily.cumsum()
    dd = float((eq - eq.cummax()).min())
    sd = daily.std()
    return {"pnl_usd": float(daily.sum()), "sharpe_ann": float(daily.mean() / sd * np.sqrt(365)) if sd > 0 else None,
            "max_dd_usd": dd, "max_dd_pct_of_capital": dd / cap * 100, "worst_day_usd": float(daily.min()),
            "sd_daily_usd": float(sd)}


def p25_kill_replay(tr, is_mask) -> dict:
    """Replay the policy-only kill rules of docs/RISK.md on IS daily series; calibrate the daily stop per book."""
    out = {}
    u = universe()
    oos_conds = set(u.loc[u.oos, "cond"])
    hist = tr[~tr.cond.isin(oos_conds)]                      # IS conds incl. Jan (rule history only)
    part = tr[is_mask]
    daily = E.daily_series(part)
    cap = REF["causal/is_eval/slip0.0"]["capital_usd"]
    rule = trailing_edge_rule(hist, daily.index)
    adj = daily * rule["mult"].reindex(daily.index).to_numpy()
    st = rule["mult"].value_counts().to_dict()
    below = rule[rule.edge_c < 0.3]
    out["trailing_30d_edge_rule_v2_is"] = {
        "rule": "docs/RISK.md kill table: trailing 30-day net edge < 0.3c/share -> half size; <= 0 -> stop. Edge known at "
                "the start of each UTC day from trades entered in the previous 30 days whose market had resolved; the "
                "full-size book is always measured, so a stopped book can restart",
        "days": int(len(daily)), "days_full": int(st.get(1.0, 0)), "days_half": int(st.get(0.5, 0)),
        "days_stopped": int(st.get(0.0, 0)),
        "trailing_edge_c_min": float(rule.edge_c.min()), "trailing_edge_c_median": float(rule.edge_c.median()),
        "trailing_edge_c_on_last_is_day": float(rule.edge_c.iloc[-1]),
        "first_day_below_0.3c": str(below.index.min().date()) if len(below) else None,
        "last_day_below_0.3c": str(below.index.max().date()) if len(below) else None,
        "base": series_stats(daily, cap), "with_rule": series_stats(adj, cap),
        "by_month_days_not_full": {str(k): int(v) for k, v in
                                   (rule.mult < 1).groupby(rule.index.tz_localize(None).to_period("M")).sum().items()},
    }
    eq = daily.cumsum()
    dd_pct = (eq - eq.cummax()) / cap * 100
    out["drawdown_5pct_stop_v2_is"] = {"fires": bool((dd_pct < -5).any()), "worst_dd_pct": float(dd_pct.min())}
    out["daily_stop_1000_v2_is"] = {"fires_days": int((daily < -1000).sum()), "worst_day_usd": float(daily.min())}
    # per-book daily-stop calibration: keep v2's ratio of stop to IS daily sd (1000 / sd)
    k = 1000.0 / daily.std()
    books = {"v2": (part, cap, "results/v2/causal.json")}
    ll = json.loads((ROOT / "results/lowloss/results.json").read_text())
    vs = pd.read_parquet(ROOT / "data/v2_lowloss/trades_a_v2_safe.parquet")
    vs_is = vs[(vs.month >= E.EVAL_START) & ~vs.cond.isin(oos_conds)]
    books["v2_safe"] = (vs_is, ll["runs"]["a_burned_oos_nonblind"]["books"]["u1_is"]["v2_safe"]["capital_usd"],
                        "results/lowloss/results.json")
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from financials import maker_book  # noqa: E402  (IS walk-forward book loader)
        mb = maker_book("is")
        if mb is not None:
            mcap = 3 * E.peak_locked(mb[mb.month >= E.EVAL_START])
            books["maker_v1"] = (mb, mcap, "3 x peak locked of data/v2_crossmarket/wf_lean_maker.parquet")
    except Exception as e:  # noqa: BLE001
        out["maker_book_error"] = repr(e)
    cal = {}
    for name, (b, c, src) in books.items():
        d = E.daily_series(b[b.month >= E.EVAL_START])
        sd = float(d.std())
        stop = k * sd
        eqb = d.cumsum()
        cal[name] = {"capital_usd": float(c), "capital_source": src, "is_daily_sd_usd": sd,
                     "worst_is_day_usd": float(d.min()), "max_is_dd_pct_of_capital": float(((eqb - eqb.cummax()) / c * 100).min()),
                     "daily_stop_at_same_sigma_multiple_usd": stop, "daily_stop_pct_of_capital": stop / c * 100,
                     "current_1000_stop_pct_of_capital": 1000 / c * 100,
                     "current_1000_stop_in_sigma": 1000 / sd,
                     "days_the_scaled_stop_would_fire_is": int((d < -stop).sum())}
    if "maker_v1" in books:   # docs/RISK.md R14 listed v2 vs maker correlation as unmeasured; IS only
        a = E.daily_series(part)
        m_ = E.daily_series(books["maker_v1"][0][books["maker_v1"][0].month >= E.EVAL_START])
        idx = a.index.union(m_.index)
        a, m_ = a.reindex(idx, fill_value=0.0), m_.reindex(idx, fill_value=0.0)
        out["v2_vs_maker_is_daily_corr"] = {"pearson": float(np.corrcoef(a, m_)[0, 1]), "days": int(len(idx)),
                                            "note": "calendar-day zero-filled IS daily P&L, Feb-Aug 2026; IS only"}
    out["daily_stop_per_book"] = {"sigma_multiple_from_v2": k, "books": cal,
                                  "rule": "daily stop = (1000 / v2 IS daily sd) x the book's own IS daily sd, so every book "
                                          "stops at the same sigma multiple as v2's $1,000"}
    return out


def p26_edge_split(tr, is_mask) -> dict:
    """Gross per-share edge split: fill vs mid 5 s / 30 s later, and drift from 30 s to resolution."""
    x = tr[is_mask]
    ok = np.isfinite(x.gross30.to_numpy()) & np.isfinite(x.mo5.to_numpy())
    y = x[ok]
    sh = y.shares.to_numpy()
    comps = {"gross_fill_to_resolution": y.gross_res.to_numpy(),
             "fill_vs_mid_5s": y.mo5.to_numpy(),
             "mid_5s_to_mid_30s": (y.gross30 - y.mo5).to_numpy(),
             "fill_vs_mid_30s (stale quote)": y.gross30.to_numpy(),
             "mid_30s_to_resolution (drift)": (y.gross_res - y.gross30).to_numpy(),
             "fee": (y.rate * y.q * (1 - y.q)).to_numpy(),
             "net": y.pnl_ps.to_numpy()}
    out = {"scope": "IS v2 trades with a 5 s and 30 s mid (mid = print-based proxy, src/tiers.py)",
           "rows_used": int(ok.sum()), "rows_total": int(len(x)),
           "share_of_shares_used": float(sh.sum() / x.shares.sum()),
           "method": "share-weighted cents/share; 95% CI bootstrap over matches, 2,000 draws, seed 0", "components": {}}
    for k, v in comps.items():
        out["components"][k] = {"c_per_share": float((sh * v).sum() / sh.sum() * 100),
                                "ci95_c_match_clustered": [100 * c for c in cluster_ratio_ci(sh * v, sh, y.cond.to_numpy())]}
    g = out["components"]
    out["share_of_gross_from_stale_quote_30s"] = g["fill_vs_mid_30s (stale quote)"]["c_per_share"] / g["gross_fill_to_resolution"]["c_per_share"]
    # current regime only (1 s / 5%)
    cur = y.regime.to_numpy() == "1s/5%"
    out["current_regime_1s_5pct"] = {}
    for k in ("gross_fill_to_resolution", "fill_vs_mid_30s (stale quote)", "mid_30s_to_resolution (drift)", "net"):
        v = comps[k][cur]
        out["current_regime_1s_5pct"][k] = {
            "c_per_share": float((sh[cur] * v).sum() / sh[cur].sum() * 100),
            "ci95_c_match_clustered": [100 * c for c in cluster_ratio_ci(sh[cur] * v, sh[cur], y.cond.to_numpy()[cur])]}
    return out


def quick():
    t0 = time.time()
    u, oos_conds, tr, is_mask = load_trades()
    m = E.metrics(tr[is_mask])
    assert abs(m["total_pnl_usd"] - REF["causal/is_eval/slip0.0"]["total_pnl_usd"]) < 1e-6
    assert abs(m["sharpe_ann"] - REF["causal/is_eval/slip0.0"]["sharpe_ann"]) < 1e-9
    first_oos_read = not (OUT.exists() and "p07_wallet_clustered_ci" in json.loads(OUT.read_text()))
    log("P07 wallet-clustered CIs (IS + burned OOS)")
    r = {"p07_wallet_clustered_ci": p07_wallet_ci(tr, is_mask, oos_conds)}
    if first_oos_read:
        with open(PEEKS, "a") as fh:
            fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} PM review P07: wallet-clustered bootstrap CI of the "
                     "frozen v2 causal book on burned OOS (non-blind, labelled; the CI the note already quotes, no rule or "
                     "parameter change; scripts/pm_compute.py)\n")
    log("P14 volume bands (IS)")
    r["p14_volume_bands_is"] = p14_bands(u, tr, is_mask)
    log("P24 factor regression (IS)")
    r["p24_factor_regression_is"] = p24_factors(tr, is_mask)
    log("P25 kill-rule replay (IS)")
    r["p25_kill_rules_is"] = p25_kill_replay(tr, is_mask)
    log("P26 gross edge split (IS)")
    r["p26_gross_edge_split_is"] = p26_edge_split(tr, is_mask)
    r["quick_meta"] = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                       "git_head": git_head(), "runtime_s": round(time.time() - t0, 1),
                       "reference_check": {"is_pnl_usd": m["total_pnl_usd"], "is_sharpe": m["sharpe_ann"], "pass": True}}
    save(r)
    log("wrote", OUT.relative_to(ROOT))
    print(json.dumps(r, indent=1, default=float)[:20000])


# ============================================================================== sens: P15 and P14 rebuild
COLS = ["cond", "ts", "p", "dir", "usd", "wallet", "spread", "fee_rate", "delay", "res", "mo5", "mo15", "mo30", "mo_res"]
BASE = {"J": 0.04, "short_w": 10, "long_w": 60, "window_s": 3, "min_prints": 30, "min_matches": 10, "min_t": 3.0,
        "wallet_n0": 200.0, "zone": "0.05-0.95"}


def since_detection(p: pd.DataFrame, J: float, short_w: float, long_w: float) -> np.ndarray:
    """src/tiers.add_causal_bucket with the detector's parameters exposed (same sort, same jump_onsets)."""
    out = np.full(len(p), -1.0)
    order = p.sort_values(["cond", "ts"], kind="stable")
    for _, g in order.groupby("cond", sort=False):
        ts, px, usd = g.ts.to_numpy(float), g.p.to_numpy(), g.usd.to_numpy()
        on = tiers.jump_onsets(ts, px, usd, J=J, short_w=short_w, long_w=long_w)
        if not on:          # no jump detected in this match (possible at a stricter threshold): never "after a jump"
            continue
        dt_ = np.array([o[3] for o in on])
        k = np.searchsorted(dt_, ts, "right") - 1
        out[g.index.to_numpy()] = np.where(k >= 0, ts - dt_[np.maximum(k, 0)], -1.0)
    return out


def run_is(p: pd.DataFrame, cond_u, wal_u, ends_c: pd.Series, since: np.ndarray, prm: dict, keep_conds=None) -> pd.DataFrame:
    """IS-only v2: the int-coded build of scripts/lowloss_test.py, then engine.simulate with the frozen policy
    (or one perturbed parameter). keep_conds restricts the universe (int codes) before anything is fitted."""
    fasttier.MIN_PRINTS, fasttier.MIN_MATCHES, fasttier.MIN_T = prm["min_prints"], prm["min_matches"], prm["min_t"]
    try:
        sel = np.ones(len(p), bool) if keep_conds is None else p.cond.isin(keep_conds).to_numpy()
        win = sel & (since >= 0) & (since < prm["window_s"])
        p03 = p.loc[win].copy()
        p03["bucket_c"] = "0-3s"     # the label walk_forward selects on; the window itself is prm["window_s"]
        wf, sh, _ = fasttier.walk_forward(p03, bucket="bucket_c")
        keep = sel & p.cond.isin(set(sh.cond)).to_numpy()
        f = v2.prepare(v2.build_features(sh, p.loc[keep, ["cond", "ts", "p", "dir", "usd", "wallet"]], ends_c))
        f["lock_end"] = f.ts + v2.LOCK_S
        whist = p03[["wallet", "ts", "mo30"]].copy()
        whist["month"] = pd.to_datetime(whist.ts, unit="s").dt.to_period("M").astype(str)
        whist = whist[["wallet", "month", "mo30"]]
        f["cond"] = cond_u[f.cond.to_numpy()]
        f["wallet"] = wal_u[f.wallet.to_numpy()]
        whist["wallet"] = wal_u[whist.wallet.to_numpy()]
        for c in f.columns:
            if isinstance(f[c].dtype, (pd.CategoricalDtype, pd.PeriodDtype)):
                f[c] = f[c].astype(str)
        pol = replace(v2.POLICY, zone=prm["zone"])
        orig = E.wallet_effect
        E.wallet_effect = lambda wh, m, n0=prm["wallet_n0"]: orig(wh, m, n0)   # noqa: E731
        E._WCACHE.clear()
        try:
            tr = E.simulate(f, pol, "res", "actual", whist)
        finally:
            E.wallet_effect = orig
            E._WCACHE.clear()
        return tr
    finally:
        fasttier.MIN_PRINTS, fasttier.MIN_MATCHES, fasttier.MIN_T = BASE["min_prints"], BASE["min_matches"], BASE["min_t"]


def summarise(tr: pd.DataFrame) -> dict:
    t = tr[tr.month >= E.EVAL_START]
    m = E.metrics(t, n_boot=1000)
    cur = t[t.regime == "1s/5%"]
    mc = E.metrics(cur, n_boot=1000) if len(cur) else {}
    return {"n_trades": m["n_trades"], "n_matches": m["n_matches"], "per_share_c": m["per_share_c"],
            "per_share_ci_c": m["per_share_ci_c"], "total_pnl_usd": m["total_pnl_usd"],
            "pnl_per_day_usd": m["total_pnl_usd"] / m["days"], "sharpe_ann": m["sharpe_ann"], "capital_usd": m["capital_usd"],
            "max_dd_pct": m["max_dd_pct"], "months_positive": m["months_positive"], "months_total": m["months_total"],
            "n_wallets": int(t.wallet.nunique()),
            "current_1s_5pct": {k: mc.get(k) for k in ("n_trades", "per_share_c", "per_share_ci_c", "total_pnl_usd", "sharpe_ann")}}


def sens(only: list[str] | None = None):
    t0 = time.time()
    u = universe()
    is_u = u[~u.oos]
    log("loading data/is_prints.parquet (IS only)")
    p = pd.read_parquet(ROOT / "data/is_prints.parquet", columns=COLS)
    cc, cond_u = pd.factorize(p.cond, sort=True)
    wc, wal_u = pd.factorize(p.wallet, sort=True)
    p["cond"], p["wallet"] = cc.astype(np.int32), wc.astype(np.int32)
    cond_u, wal_u = np.asarray(cond_u, dtype=object), np.asarray(wal_u, dtype=object)
    del cc, wc
    ends = is_u.set_index("cond").end
    ends_c = pd.Series(ends.reindex(pd.Index(cond_u)).to_numpy(), index=np.arange(len(cond_u), dtype=np.int32))
    log(f"{len(p):,} IS prints, {len(cond_u):,} matches; detecting jumps (base detector)")
    since0 = since_detection(p, BASE["J"], BASE["short_w"], BASE["long_w"])
    res = json.loads(OUT.read_text()).get("p15_sensitivity_is", {}) if OUT.exists() else {}
    runs = res.get("runs", {})

    def do(name, prm, since, keep=None):
        if only and name not in only and name != "base":
            return
        t1 = time.time()
        tr = run_is(p, cond_u, wal_u, ends_c, since, prm, keep)
        s = summarise(tr)
        s.update({"params": {k: v for k, v in prm.items() if v != BASE[k]} or "frozen v2",
                  "runtime_s": round(time.time() - t1, 1)})
        runs[name] = s
        log(f"{name:28s} {s['n_trades']:>6} trades  {s['per_share_c']:+.2f}c {np.round(s['per_share_ci_c'], 2)}  "
            f"${s['total_pnl_usd']:,.0f}  Sharpe {s['sharpe_ann']:.1f}  1s/5% {s['current_1s_5pct']['per_share_c']:+.2f}c  "
            f"({s['runtime_s']} s)")
        if name == "base":
            ref = REF["causal/is_eval/slip0.0"]
            assert abs(s["total_pnl_usd"] - ref["total_pnl_usd"]) < 1e-6, "IS rebuild does not reproduce causal.json P&L"
            assert abs(s["sharpe_ann"] - ref["sharpe_ann"]) < 1e-9, "IS rebuild does not reproduce causal.json Sharpe"
            s["reproduces_results_v2_causal_json_is"] = True
        res["runs"] = runs
        save({"p15_sensitivity_is": {**res, "base_params": BASE,
                                     "note": "Each run changes ONE threshold of the frozen v2 by one step and re-runs the whole "
                                             "walk-forward on IS prints only (data/is_prints.parquet). Nothing is selected: the "
                                             "frozen rule stays as registered. No OOS data is opened."}})
        gc.collect()

    do("base", dict(BASE), since0)
    for k, vals in (("window_s", (2, 4, 6)), ("min_prints", (20, 40)), ("min_matches", (5, 15)), ("min_t", (2.0, 4.0)),
                    ("wallet_n0", (100.0, 400.0)), ("zone", ("0.0-1.0", "0.1-0.9"))):
        for v in vals:
            do(f"{k}={v}", {**BASE, k: v}, since0)
    # P14: point-in-time universe (pre-start volume known at the start), IS only
    pre = pd.read_parquet(ROOT / "data/derived/tier0_prestart_volume.parquet").set_index("cond").prestart_usd
    code = pd.Series(np.arange(len(cond_u)), index=cond_u)
    for thr in (5_000, 20_000):
        keep = set(code[pre.reindex(cond_u).fillna(0).to_numpy() >= thr].to_numpy())
        do(f"universe_prestart>={thr}", dict(BASE), since0, keep)
        runs[f"universe_prestart>={thr}"]["universe_matches_kept_of_is"] = [int(len(keep)), int(len(cond_u))] \
            if f"universe_prestart>={thr}" in runs else None
    save({"p15_sensitivity_is": {**res, "runs": runs}})
    # detector perturbations (need a new jump table each)
    for k, vals in (("J", (0.03, 0.06)), ("short_w", (5, 20)), ("long_w", (30, 120))):
        for v in vals:
            name = f"{k}={v}"
            if only and name not in only:
                continue
            prm = {**BASE, k: v}
            log(f"detecting jumps for {name}")
            s = since_detection(p, prm["J"], prm["short_w"], prm["long_w"])
            do(name, prm, s)
            del s
    res = json.loads(OUT.read_text())["p15_sensitivity_is"]
    res["sens_meta"] = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                        "git_head": git_head(), "runtime_s": round(time.time() - t0, 1)}
    save({"p15_sensitivity_is": res})
    log(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "quick"
    if mode == "quick":
        quick()
    elif mode == "sens":
        sens(sys.argv[2:] or None)
    else:
        raise SystemExit(__doc__)
