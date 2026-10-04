"""Does the fast-tier edge persist? Decay fits, competition elasticity, the profit pool, and venue-rule breaks.

Question (judges): the fast tier grew from 4 to 131 wallets while its net edge fell about 0.2c a month. Is the edge
dying, and if so, how fast and from what?

Inputs (read only; nothing here opens held-out prints or tapes):
  results/summary.json :: is.h6_walkforward, oos.h6_walkforward   published monthly fast-tier rows (run_all.py)
  results/summary.json :: is.h6_shadow.mean_fee_c, oos.h6_shadow.mean_fee_c   fee per share, IS / burned OOS
  results/alpha/alpha.json :: headline.fast_tier_slope_c_per_month           the slope the paper quotes (cross-check)
  data/is_prints.parquet        IS prints only (the walk-forward of src/fasttier.py is re-run on it, and must
                                reproduce every published IS row) -> gross edge, fee, $ P&L, cohorts, regime splits
  src.tape.universe()           match catalogue metadata only (start time, secondsDelay, fee rate, OOS flag),
                                the same call every script makes to define the split; no prices or outcomes

The burned-OOS months (Aug 25 - Oct 3 2026) enter only through their already-published monthly aggregates, so this
script makes no new out-of-sample read and adds nothing to results/oos_peeks.log.

Edge = net 30 s markout per print (c/share, after each match's taker fee), the published H6 measure. Gross = the same
before the fee. $ P&L = sum over prints of shares x net 30 s markout (shares = usd / price, as the shadow book).

Writes results/economics/persistence.json and results/economics/persistence.png (+ .pdf, paper house style).
Run from the repo root:  .venv/bin/python scripts/edge_persistence.py
"""
from __future__ import annotations

import datetime as dt
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs/paper"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

from src import fasttier  # noqa: E402
from src.tape import universe  # noqa: E402

T0 = time.time()
OUT = ROOT / "results/economics"
SUMMARY = "results/summary.json"
ALPHA = "results/alpha/alpha.json"
IS_PRINTS = "data/is_prints.parquet"
B = 2000          # bootstrap draws (match-clustered)
SEED = 20261004
T0_MONTH = pd.Period("2025-12", "M")     # t = 0 (first published fast-tier month)
LAST_FULL = pd.Period("2026-09", "M")    # last full calendar month in the data (Oct 2026 = 3 days)
INC_LAST = pd.Period("2026-04", "M")     # incumbents = wallets first qualified for a month <= Apr 2026
A_MONTHS = [str(m) for m in pd.period_range("2025-12", "2026-04", freq="M")]   # period A: 3 s delay months
B_MONTHS = ["2026-06", "2026-07", "2026-08"]                                    # period B: 1 s delay months (IS)

SRC: dict[str, str] = {}


def r(x, nd=4):
    if x is None:
        return None
    if isinstance(x, (list, tuple, np.ndarray)):
        return [r(v, nd) for v in x]
    x = float(x)
    if not math.isfinite(x):
        return None if math.isnan(x) else (1e308 if x > 0 else -1e308)
    return round(x, nd)


def jload(rel):
    return json.loads((ROOT / rel).read_text())


def tidx(month: str) -> int:
    return (pd.Period(month, "M") - T0_MONTH).n


# ------------------------------------------------------------------------------------------------ regression
def wls(X, y, w=None):
    """OLS / WLS with classical SEs and t-based 95% CIs. Returns a dict."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    n, k = X.shape
    w = np.ones(n) if w is None else np.asarray(w, float) / np.mean(w)
    sw = np.sqrt(w)
    Xw, yw = X * sw[:, None], y * sw
    beta, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
    e = yw - Xw @ beta
    dof = n - k
    s2 = float(e @ e) / dof
    cov = s2 * np.linalg.inv(Xw.T @ Xw)
    se = np.sqrt(np.diag(cov))
    tc = stats.t.ppf(0.975, dof)
    sse = float(e @ e)
    aicc = n * math.log(sse / n) + 2 * k + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else float("nan"))
    raw_e = y - X @ beta
    dw = float(np.sum(np.diff(raw_e) ** 2) / np.sum(raw_e ** 2))
    return {"coef": beta, "se": se, "cov": cov, "dof": dof, "tcrit": tc, "sse": sse, "aicc": aicc, "dw": dw,
            "t": beta / se, "p": 2 * stats.t.sf(np.abs(beta / se), dof), "n": n,
            "ci": np.c_[beta - tc * se, beta + tc * se]}


def fieller_root(fit, t_ref: float):
    """x where a + b x = 0, with Fieller's 95% interval (from the fit's own cov and t critical value).
    Returns (x0, lo, hi, bounded)."""
    a, b = fit["coef"][:2]
    V = fit["cov"]
    tc = fit["tcrit"]
    x0 = -a / b
    A = b * b - tc * tc * V[1, 1]
    Bq = 2 * (a * b - tc * tc * V[0, 1])
    C = a * a - tc * tc * V[0, 0]
    disc = Bq * Bq - 4 * A * C
    if A > 0 and disc >= 0:
        lo, hi = sorted([(-Bq - math.sqrt(disc)) / (2 * A), (-Bq + math.sqrt(disc)) / (2 * A)])
        return x0 - t_ref, lo - t_ref, hi - t_ref, True
    return x0 - t_ref, None, None, False


def fit_report(fit, names, label, extra=None):
    out = {"label": label, "n": fit["n"], "dof": fit["dof"], "aicc": r(fit["aicc"], 3),
           "durbin_watson": r(fit["dw"], 3)}
    for i, nm in enumerate(names):
        out[nm] = {"coef": r(fit["coef"][i]), "se": r(fit["se"][i]), "t": r(fit["t"][i], 3),
                   "p": r(fit["p"][i], 4), "ci95": r(fit["ci"][i])}
    if extra:
        out.update(extra)
    return out


# ------------------------------------------------------------------------------------------------ bootstrap
def multinom(k: int, rng) -> np.ndarray:
    return rng.multinomial(k, np.full(k, 1.0 / k), size=B).astype(float)


def boot_ratio(num: np.ndarray, den: np.ndarray, rng) -> tuple[float, list[float]]:
    W = multinom(len(num), rng)
    d = (W @ num) / (W @ den)
    return float(num.sum() / den.sum()), [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]


def per_match(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    g = df.groupby("cond", sort=False)
    out = pd.DataFrame({"n": g.size()})
    for c in cols:
        out[c] = g[c].sum()
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    S = jload(SUMMARY)
    AL = jload(ALPHA)
    is_rows = pd.DataFrame(S["is"]["h6_walkforward"])
    oos_rows = pd.DataFrame(S["oos"]["h6_walkforward"])
    SRC["is_rows"] = f"{SUMMARY}::is.h6_walkforward"
    SRC["oos_rows"] = f"{SUMMARY}::oos.h6_walkforward"

    # ============================================================================ 1. IS prints: reproduce + extend
    cols = ["cond", "ts", "p", "dir", "usd", "wallet", "spread", "fee_rate", "delay", "mo5", "mo15", "mo30",
            "mo_res", "bucket"]
    P = pd.read_parquet(ROOT / IS_PRINTS, columns=cols)
    P = P.assign(month=pd.to_datetime(P.ts, unit="s").dt.to_period("M"))
    P = fasttier.net_cols(P)
    months = sorted(P.month.unique())
    first_q: dict[str, pd.Period] = {}
    parts, rep = [], []
    for m in months[2:]:                                   # exactly src/fasttier.walk_forward (start_month = 2)
        sel = fasttier.qualify(P[P.month < m])
        for w in sel:
            first_q.setdefault(w, m)
        cur = P[(P.month == m) & (P.bucket == "0-3s") & P.wallet.isin(sel)]
        rep.append({"month": str(m), "n_wallets": len(sel), "n_prints": len(cur), "net30_c": cur.net30.mean() * 100,
                    "usd_k": cur.usd.sum() / 1e3})
        parts.append(cur)
    del P
    rep = pd.DataFrame(rep)
    chk = rep.merge(is_rows, on="month", suffixes=("", "_pub"))
    repro = {
        "rows": int(len(chk)), "rows_published": int(len(is_rows)),
        "max_abs_diff_net30_c": r((chk.net30_c - chk.net30_c_pub).abs().max(), 6),
        "n_wallets_equal": bool((chk.n_wallets == chk.n_wallets_pub).all()),
        "n_prints_equal": bool((chk.n_prints == chk.n_prints_pub).all()),
        "max_abs_diff_usd_k": r((chk.usd_k - chk.usd_k_pub).abs().max(), 4),
    }
    assert repro["rows"] == repro["rows_published"] and repro["n_wallets_equal"] and repro["n_prints_equal"] \
        and repro["max_abs_diff_net30_c"] < 1e-3, f"IS walk-forward does not reproduce the published rows: {repro}"

    F = pd.concat(parts, ignore_index=True)
    n_no_mark = int(F.mo30.isna().sum())          # prints too close to the tape end for a 30 s mark: pandas means
    F = F[F.mo30.notna()].reset_index(drop=True)   # skip them, so sums / counts below must drop them too
    repro["fast_prints_without_30s_mark_dropped_from_extras"] = n_no_mark
    F["month_s"] = F.month.astype(str)
    F["shares"] = F.usd / np.where(F.dir > 0, F.p, 1 - F.p)
    F["pnl30"] = F.shares * F.net30
    F["pnlres"] = F.shares * F.net_res
    F["cohort"] = F.wallet.map(first_q)
    F["incumbent"] = F.cohort <= INC_LAST
    F["first4"] = F.cohort == pd.Period("2025-12", "M")
    F["gross_c"], F["fee_c"], F["net_c"] = F.mo30 * 100, F.fee * 100, F.net30 * 100
    F["reg"] = F.delay.astype(str) + " s / " + (F.fee_rate * 100).round(0).astype(int).astype(str) + "%"

    # per-month IS extras (gross, fee, $ P&L, regime shares, cohort split, match-clustered CIs)
    ism = {}
    for m, d in F.groupby("month_s", sort=True):
        pm = per_match(d, ["net_c", "gross_c"])
        net, net_ci = boot_ratio(pm.net_c.to_numpy(), pm.n.to_numpy(float), rng)
        gro, gro_ci = boot_ratio(pm.gross_c.to_numpy(), pm.n.to_numpy(float), rng)
        inc, ent = d[d.incumbent], d[~d.incumbent]
        ism[m] = {
            "net30_c": net, "net30_ci95_c": net_ci, "gross30_c": gro, "gross30_ci95_c": gro_ci,
            "fee_c": float(d.fee_c.mean()), "net30_share_weighted_c": float(d.pnl30.sum() / d.shares.sum() * 100),
            "pnl30_usd": float(d.pnl30.sum()), "pnl_to_resolution_usd": float(d.pnlres.sum()),
            "shares": float(d.shares.sum()), "usd": float(d.usd.sum()), "active_wallets": int(d.wallet.nunique()),
            "share_fee_published": float((d.fee_rate > 0).mean()), "share_delay_1s": float((d.delay == 1).mean()),
            "share_fee_5pct": float((d.fee_rate >= 0.05 - 1e-9).mean()),
            "incumbents": {"n_prints": int(len(inc)), "gross30_c": r(inc.gross_c.mean()), "net30_c": r(inc.net_c.mean()),
                           "n_wallets_active": int(inc.wallet.nunique())},
            "entrants": {"n_prints": int(len(ent)), "gross30_c": r(ent.gross_c.mean()) if len(ent) else None,
                         "net30_c": r(ent.net_c.mean()) if len(ent) else None,
                         "n_wallets_active": int(ent.wallet.nunique())},
            "first4": {"n_prints": int(d.first4.sum()), "gross30_c": r(d.loc[d.first4, "gross_c"].mean()),
                       "net30_c": r(d.loc[d.first4, "net_c"].mean())},
        }
    SRC["is_extras"] = f"{IS_PRINTS} -> src/fasttier.py walk-forward re-run (reproduces {SUMMARY}::is.h6_walkforward)"

    # ============================================================================ 2. universe metadata: regimes
    u = universe()[["start", "delay", "fee_rate", "oos"]].copy()
    u["month"] = u.start.dt.strftime("%Y-%m")
    u["reg"] = u.delay.astype(str) + " s / " + (u.fee_rate * 100).round(0).astype(int).astype(str) + "%"
    reg_tab = pd.crosstab(u.month, u.reg)
    reg_dates = {}
    for k in sorted(u.reg.unique()):
        s = u.loc[u.reg == k, "start"]
        reg_dates[k] = {"first_match_start": str(s.min()), "last_match_start": str(s.max()), "matches": int(len(s))}
    matches_by_month = u.groupby("month").size()
    is_aug_matches = int(((u.month == "2026-08") & ~u.oos).sum())
    regime = {
        "source": "src.tape.universe() (data/raw/events_tennis_2025-07-01_2026-10-03.parquet): start, secondsDelay, "
                  "feeSchedule.rate per match; metadata only",
        "matches_by_month_and_regime": {m: {k: int(v) for k, v in row.items() if v} for m, row in reg_tab.iterrows()},
        "regime_first_last": reg_dates,
        "events": [
            {"what": "taker fee published (0% -> 3%)", "first_full_month": "2026-04",
             "first_match_start": reg_dates.get("3 s / 3%", {}).get("first_match_start"),
             "note": "the '0%' months are matches with no published fee schedule, charged 0 in every backtest "
                     "(results/v2/note_metrics.json::data_gaps.no_fee_schedule_matches); if the venue charged a fee "
                     "then, the early net edge is overstated and the decline is smaller"},
            {"what": "taker order delay 3 s -> 1 s", "first_full_month": "2026-06",
             "first_match_start": reg_dates.get("1 s / 3%", {}).get("first_match_start")},
            {"what": "taker fee 3% -> 5%", "first_full_month": "2026-08",
             "first_match_start": reg_dates.get("1 s / 5%", {}).get("first_match_start")},
        ],
        "burned_oos_months_regime": "every match from 2026-08 on is 1 s / 5% (metadata), so OOS rows carry one regime",
    }

    # ============================================================================ 3. calendar series (11 months)
    aug_is = is_rows[is_rows.month == "2026-08"].iloc[0]
    aug_all = oos_rows[oos_rows.month == "2026-08"].iloc[0]
    assert int(aug_all.n_wallets) == int(aug_is.n_wallets) and aug_all.n_prints > aug_is.n_prints
    n_only = int(aug_all.n_prints - aug_is.n_prints)
    aug_only_net = (aug_all.n_prints * aug_all.net30_c - aug_is.n_prints * aug_is.net30_c) / n_only
    o = oos_rows
    oos_pw_published = float((o.n_prints * o.net30_c).sum() / o.n_prints.sum())
    oos_pw_only = float(((o.n_prints * o.net30_c).sum() - aug_is.n_prints * aug_is.net30_c)
                        / (o.n_prints.sum() - aug_is.n_prints))
    aug_note = {
        "finding": "results/summary.json::oos.h6_walkforward[0] (2026-08) is computed by run_all.py (lines 110-115) on "
                   "IS and OOS prints together and kept for month >= 2026-08, so it holds ALL of August, including the "
                   f"{int(aug_is.n_prints):,} IS August prints in is.h6_walkforward[-1]. Same wallet set "
                   f"({int(aug_all.n_wallets)}); {int(aug_all.n_prints):,} prints vs {int(aug_is.n_prints):,}.",
        "aug_oos_only_n_prints": n_only,
        "aug_oos_only_net30_c_derived": r(aug_only_net),
        "oos_print_weighted_net30_c_as_published": r(oos_pw_published),
        "oos_print_weighted_net30_c_oos_prints_only_derived": r(oos_pw_only),
        "oos_n_prints_as_published": int(o.n_prints.sum()),
        "oos_n_prints_oos_only": int(o.n_prints.sum() - aug_is.n_prints),
        "how": "print-mean decomposition n_all*m_all = n_IS*m_IS + n_only*m_only (identical wallet set and IS prints in "
               "both runs). Exact up to prints with no 30 s mark, which n_prints counts but the mean skips "
               f"({n_no_mark:,} of {int(is_rows.n_prints.sum()):,} IS fast prints); no OOS print was read here",
        "consequence": "results/alpha/alpha.json::headline.fast_tier_net30_c_print_weighted.OOS (+0.75, paper key "
                       "ft.c.oos) mixes 38% IS prints; on OOS prints only it is the derived value above",
    }
    SRC["aug_note"] = "run_all.py lines 110-115 + results/summary.json::(is|oos).h6_walkforward (arithmetic)"

    oos_fee = float(S["oos"]["h6_shadow"]["mean_fee_c"])
    is_fee_shadow = float(S["is"]["h6_shadow"]["mean_fee_c"])
    is_fee_prints = float(F.fee_c.mean())
    SRC["oos_fee"] = f"{SUMMARY}::oos.h6_shadow.mean_fee_c"

    cal = []
    for _, row in pd.concat([is_rows[is_rows.month < "2026-08"], oos_rows]).iterrows():
        m = row.month
        rec = {"month": m, "t": tidx(m), "n_wallets": int(row.n_wallets), "n_prints": int(row.n_prints),
               "n_matches": int(row.n_matches), "usd_k": float(row.usd_k), "net30_c": float(row.net30_c),
               "others_net30_c": float(row.others_net30_c), "net_res_c": float(row.net_res_c),
               "universe_matches": int(matches_by_month.get(m, 0)),
               "period": "IS" if m < "2026-08" else ("IS+OOS (all of August)" if m == "2026-08" else "burned OOS"),
               "partial_month": m == "2026-10"}
        if m in ism and m < "2026-08":             # the calendar August row is all of August (IS + OOS)
            e = ism[m]
            rec.update(gross30_c=e["gross30_c"], fee_c=e["fee_c"], gross_kind="exact (IS prints)",
                       pnl30_usd=e["pnl30_usd"], net30_ci95_c=e["net30_ci95_c"], gross30_ci95_c=e["gross30_ci95_c"],
                       share_delay_1s=e["share_delay_1s"], share_fee_5pct=e["share_fee_5pct"],
                       share_fee_published=e["share_fee_published"])
        else:
            fee = (aug_is.n_prints * ism["2026-08"]["fee_c"] + n_only * oos_fee) / aug_all.n_prints if m == "2026-08" \
                else oos_fee
            rec.update(gross30_c=float(row.net30_c) + fee, fee_c=fee,
                       gross_kind="approx: net + fee, fee = burned-OOS shadow-book mean fee per trade"
                                  + (" (IS part exact)" if m == "2026-08" else ""),
                       pnl30_usd=None, share_delay_1s=1.0, share_fee_5pct=1.0, share_fee_published=1.0)
        rec["proxy_usd"] = rec["net30_c"] / 100 * rec["usd_k"] * 1e3      # edge x $ volume
        cal.append(rec)
    C = pd.DataFrame(cal)
    full = C[~C.partial_month].reset_index(drop=True)                   # Dec 2025 - Sep 2026

    # ============================================================================ 4. decay fits on the net edge
    def lin(df, ycol="net30_c", w=None):
        X = np.c_[np.ones(len(df)), df.t]
        return wls(X, df[ycol], None if w is None else df[w])

    fits = {}
    # (a) the paper's number, reproduced: OLS on the 9 IS rows (Aug = IS part), t = row index
    is9 = is_rows.assign(t=np.arange(len(is_rows)))
    f_is9 = lin(is9)
    fits["linear_ols_is9_paper"] = fit_report(f_is9, ["intercept", "slope_c_per_month"],
                                              "OLS, 9 IS rows (reproduces alpha.json headline slope)",
                                              {"published_slope": AL["headline"]["fast_tier_slope_c_per_month"]["IS"],
                                               "published_t": AL["headline"]["fast_tier_slope_c_per_month"]["IS_t"]})
    SRC["paper_slope"] = f"{ALPHA}::headline.fast_tier_slope_c_per_month.IS"
    f_ols11 = lin(C)
    f_wls11 = lin(C, w="n_matches")
    f_wls10 = lin(full, w="n_matches")
    fits["linear_ols_cal11"] = fit_report(f_ols11, ["intercept", "slope_c_per_month"], "OLS, 11 calendar months")
    fits["linear_wls_cal11"] = fit_report(f_wls11, ["intercept", "slope_c_per_month"],
                                          "WLS (weights = matches traded), 11 calendar months  [primary]")
    fits["linear_wls_full10"] = fit_report(f_wls10, ["intercept", "slope_c_per_month"],
                                           "WLS, 10 full months (drops Oct 2026, 3 days)")
    # (b) log-linear: constant % decay per month
    Xl = np.c_[np.ones(len(C)), C.t]
    f_log = wls(Xl, np.log(C.net30_c), C.n_matches)
    b, (blo, bhi) = f_log["coef"][1], f_log["ci"][1]
    fits["log_wls_cal11"] = fit_report(f_log, ["intercept", "slope_log_per_month"], "WLS of ln(net edge) on t", {
        "monthly_change_pct": r((math.exp(b) - 1) * 100, 2),
        "monthly_change_pct_ci95": r([(math.exp(blo) - 1) * 100, (math.exp(bhi) - 1) * 100], 2),
        "half_life_months": r(math.log(2) / -b, 2) if b < 0 else None,
        "half_life_months_ci95": [r(math.log(2) / -blo, 2) if blo < 0 else None,
                                  r(math.log(2) / -bhi, 2) if bhi < 0 else "unbounded (slope CI reaches 0)"]})
    # (c) competition elasticity: ln edge on ln wallets
    Xe = np.c_[np.ones(len(C)), np.log(C.n_wallets)]
    f_el = wls(Xe, np.log(C.net30_c), C.n_matches)
    fits["elasticity_edge_wrt_wallets"] = fit_report(
        f_el, ["intercept", "elasticity"], "WLS of ln(net edge) on ln(fast wallets): % change in edge per 1% more "
        "fast wallets", {"corr_ln_wallets_with_t": r(np.corrcoef(np.log(C.n_wallets), C.t)[0, 1], 3),
                         "caveat": "wallets grow almost log-linearly in time, so this elasticity cannot be told apart "
                                   "from a time trend in 11 points"})
    Xe2 = np.c_[np.ones(len(C)), np.log(C.n_wallets), C.t]
    f_el2 = wls(Xe2, np.log(C.net30_c), C.n_matches)
    fits["elasticity_with_trend"] = fit_report(f_el2, ["intercept", "elasticity", "trend_log_per_month"],
                                               "WLS of ln(net edge) on ln(wallets) and t together")
    # (d) gross (before fee): is the pre-fee edge decaying?
    f_g = lin(C, "gross30_c", "n_matches")
    fits["gross_linear_wls_cal11"] = fit_report(
        f_g, ["intercept", "slope_c_per_month"], "WLS of GROSS 30 s markout (before fee) on t; OOS gross approximate")
    is_cal = C[C.period == "IS"].reset_index(drop=True)                 # Dec 2025 - Jul 2026: gross exact
    is_cal = pd.concat([is_cal, pd.DataFrame([{"t": tidx("2026-08"), "gross30_c": ism["2026-08"]["gross30_c"],
                                               "n_matches": int(aug_is.n_matches)}])], ignore_index=True)
    fits["gross_linear_wls_is9_exact"] = fit_report(
        lin(is_cal, "gross30_c", "n_matches"), ["intercept", "slope_c_per_month"],
        "WLS of GROSS markout on t, 9 IS months only (Aug = IS part): every value exact from IS prints")
    f_elg = wls(Xe, np.log(C.gross30_c), C.n_matches)
    fits["elasticity_gross_wrt_wallets"] = fit_report(
        f_elg, ["intercept", "elasticity"], "WLS of ln(GROSS edge) on ln(fast wallets): competition elasticity of "
        "the pre-fee edge (OOS gross approximate)")
    f_fee = lin(C, "fee_c", "n_matches")
    fits["fee_linear_wls_cal11"] = fit_report(f_fee, ["intercept", "slope_c_per_month"], "WLS of fee per share on t")
    # (e) the gap to everyone else, and everyone else
    C["gap_c"] = C.net30_c - C.others_net30_c
    fits["gap_fast_minus_others_wls"] = fit_report(lin(C, "gap_c", "n_matches"), ["intercept", "slope_c_per_month"],
                                                   "WLS of (fast - other takers) net 30 s markout on t")
    fits["others_wls"] = fit_report(lin(C, "others_net30_c", "n_matches"), ["intercept", "slope_c_per_month"],
                                    "WLS of other takers' net 30 s markout on t")

    # ============================================================================ 5. breaks vs venue-rule dates
    def X_of(df, cols_):
        return np.c_[np.ones(len(df))] if not cols_ else np.c_[np.ones(len(df)), *[df[c] for c in cols_]]

    breaks = {}
    for ycol in ("net30_c", "gross30_c"):
        res = {}
        base_t = wls(X_of(C, ["t"]), C[ycol], C.n_matches)
        for dname, dcol in (("1 s delay", "share_delay_1s"), ("5% fee", "share_fee_5pct"),
                            ("fee published", "share_fee_published")):
            f_shift = wls(X_of(C, [dcol]), C[ycol], C.n_matches)
            f_both = wls(X_of(C, ["t", dcol]), C[ycol], C.n_matches)
            res[dname] = {
                "shift_only": fit_report(f_shift, ["intercept", "shift_c"], f"level shift at the {dname} "
                                         "(regressor = share of the month's fast-tier prints in the new regime)"),
                "trend_plus_shift": fit_report(f_both, ["intercept", "slope_c_per_month", "shift_c"],
                                               "trend + shift"),
                "aicc_trend_only": r(base_t["aicc"], 3), "aicc_shift_only": r(f_shift["aicc"], 3),
                "aicc_trend_plus_shift": r(f_both["aicc"], 3),
            }
        scan = []
        for k in range(2, len(C) - 1):
            d = (C.t >= C.t.iloc[k]).astype(float)
            f1 = wls(np.c_[np.ones(len(C)), d], C[ycol], C.n_matches)
            f2 = wls(np.c_[np.ones(len(C)), C.t, d], C[ycol], C.n_matches)
            scan.append({"break_at": C.month.iloc[k], "sse_shift_only": r(f1["sse"], 5),
                         "sse_trend_plus_shift": r(f2["sse"], 5), "shift_c": r(f1["coef"][1]),
                         "trend_given_shift": r(f2["coef"][1]), "trend_given_shift_ci95": r(f2["ci"][1])})
        best = min(scan, key=lambda z: z["sse_shift_only"])
        res["unknown_break_scan"] = {"rows": scan, "best_shift_only": best["break_at"],
                                     "note": "data-chosen break; its p-value is not valid as a test (search), shown only "
                                             "to see whether it lands on a venue-rule date"}
        breaks[ycol] = res

    # within-month natural experiments on IS prints (same wallet set, same month, different match regime)
    def contrast(month, reg_a, reg_b):
        d = F[F.month_s == month]
        A_, B_ = d[d.reg == reg_a], d[d.reg == reg_b]
        out = {"month": month, "a": reg_a, "b": reg_b, "n_prints": [int(len(A_)), int(len(B_))],
               "n_matches": [int(A_.cond.nunique()), int(B_.cond.nunique())]}
        for col, nm in (("net_c", "net30"), ("gross_c", "gross30"), ("fee_c", "fee")):
            pa, pb = per_match(A_, [col]), per_match(B_, [col])
            Wa, Wb = multinom(len(pa), rng), multinom(len(pb), rng)
            da = (Wa @ pa[col].to_numpy()) / (Wa @ pa.n.to_numpy(float))
            db = (Wb @ pb[col].to_numpy()) / (Wb @ pb.n.to_numpy(float))
            diff = db - da
            out[nm] = {"a_c": r(A_[col].mean()), "b_c": r(B_[col].mean()), "b_minus_a_c": r(B_[col].mean() - A_[col].mean()),
                       "ci95": r([np.percentile(diff, 2.5), np.percentile(diff, 97.5)])}
        return out

    natural = {
        "what": "Same month, same qualified wallets, matches under two venue regimes (regime is per match). Net / gross "
                "30 s markout per print, match-clustered bootstrap CI of the difference (b - a). IS prints only.",
        "fee_published_mar2026": contrast("2026-03", "3 s / 0%", "3 s / 3%"),
        "delay_3s_to_1s_may2026": contrast("2026-05", "3 s / 3%", "1 s / 3%"),
        "fee_3_to_5_jul2026": contrast("2026-07", "1 s / 3%", "1 s / 5%"),
    }

    # ============================================================================ 6. composition: incumbents vs entrants
    def comp_parts(df):
        return per_match(df.assign(gi=df.gross_c * df.incumbent, ge=df.gross_c * ~df.incumbent,
                                   ni=df.incumbent.astype(float), ne=(~df.incumbent).astype(float)),
                         ["gross_c", "fee_c", "net_c", "gi", "ge", "ni", "ne"])

    pA = comp_parts(F[F.month_s.isin(A_MONTHS)])
    pB = comp_parts(F[F.month_s.isin(B_MONTHS)])

    def decomp(sA, sB):
        gA, fA, nA = sA["gross_c"] / sA["n"], sA["fee_c"] / sA["n"], sA["net_c"] / sA["n"]
        gB, fB, nB = sB["gross_c"] / sB["n"], sB["fee_c"] / sB["n"], sB["net_c"] / sB["n"]
        g_inc_A = sA["gi"] / sA["ni"]
        g_inc_B, g_ent_B = sB["gi"] / sB["ni"], sB["ge"] / sB["ne"]
        w_ent = sB["ne"] / sB["n"]
        return {"net_A_c": nA, "net_B_c": nB, "delta_net_c": nB - nA,
                "fee_part_c": -(fB - fA),
                "incumbents_gross_change_c": (1 - w_ent) * (g_inc_B - g_inc_A),
                "entrant_dilution_c": w_ent * (g_ent_B - g_inc_A),
                "gross_A_c": gA, "gross_B_c": gB, "gross_inc_A_c": g_inc_A, "gross_inc_B_c": g_inc_B,
                "gross_ent_B_c": g_ent_B, "entrant_print_share_B": w_ent, "fee_A_c": fA, "fee_B_c": fB}

    def sums(pm, Wrow=None):
        if Wrow is None:
            return {c: float(pm[c].sum()) for c in pm.columns}
        return {c: Wrow @ pm[c].to_numpy(float) for c in pm.columns}

    point = decomp(sums(pA), sums(pB))
    WA, WB = multinom(len(pA), rng), multinom(len(pB), rng)
    bs = decomp(sums(pA, WA), sums(pB, WB))
    comp = {
        "what": "Shift-share of the fall in the fast tier's net edge between period A (Dec 2025 - Apr 2026, 3 s delay) "
                "and period B (Jun - Aug 2026 IS part, 1 s delay). Incumbents = wallets first qualified for a month up "
                "to Apr 2026; entrants = first qualified from May 2026. delta net = fee part + incumbents' gross change "
                "+ entrant dilution (exact identity, because in A every print is an incumbent's).",
        "period_A": A_MONTHS, "period_B": B_MONTHS,
        **{k: r(v) for k, v in point.items()},
        "ci95": {k: r([np.percentile(v, 2.5), np.percentile(v, 97.5)]) for k, v in bs.items()},
        "identity_check_c": r(point["delta_net_c"] - (point["fee_part_c"] + point["incumbents_gross_change_c"]
                                                      + point["entrant_dilution_c"]), 9),
    }
    # incumbents' gross trend, month by month (print-level OLS on month index, match-clustered bootstrap)
    def trend(df, col="gross_c"):
        d = df.assign(tt=df.month.map(lambda m: (m - T0_MONTH).n).astype(float))
        d = d.assign(ty=d.tt * d[col], t2=d.tt ** 2)
        pm = per_match(d, ["tt", col, "ty", "t2"])
        arr = {c: pm[c].to_numpy(float) for c in pm.columns}

        def slope(Wm=None):
            s = {c: (arr[c].sum() if Wm is None else Wm @ arr[c]) for c in arr}
            return (s["n"] * s["ty"] - s["tt"] * s[col]) / (s["n"] * s["t2"] - s["tt"] ** 2)
        bsl = slope(multinom(len(pm), rng))
        return {"slope_c_per_month": r(slope()), "ci95": r([np.percentile(bsl, 2.5), np.percentile(bsl, 97.5)]),
                "n_prints": int(len(d)), "n_matches": int(len(pm))}

    def month_trend(df, col="gross_c"):
        """Month-level WLS (monthly print means, weights = matches): months, not prints, are the units, so a common
        month shock (Feb 2026) counts as noise. This is the honest CI; the print-level one is shown beside it."""
        g = df.groupby("month_s").agg(y=(col, "mean"), nm=("cond", "nunique")).reset_index()
        g["t"] = g.month_s.map(tidx)
        f_ = wls(np.c_[np.ones(len(g)), g.t], g.y, g.nm)
        return {"slope_c_per_month": r(f_["coef"][1]), "ci95": r(f_["ci"][1]), "n_months": int(len(g)),
                "months": g.month_s.tolist(), "monthly_mean_c": r(g.y.tolist())}

    inc_jan = F[F.incumbent & (F.month >= pd.Period("2026-01", "M"))]
    f4_jan = F[F.first4 & (F.month >= pd.Period("2026-01", "M"))]
    all_jan = F[F.month >= pd.Period("2026-01", "M")]
    for nm_, df_ in (("incumbents", inc_jan), ("first4", f4_jan), ("all", all_jan)):
        comp[f"{nm_}_gross_trend_jan_aug"] = {"month_level_primary": month_trend(df_),
                                              "print_level_match_clustered": trend(df_)}
    comp["incumbents_net_trend_jan_aug"] = {"month_level_primary": month_trend(inc_jan, "net_c"),
                                            "print_level_match_clustered": trend(inc_jan, "net_c")}
    comp["definitions"] = {"incumbents": "wallets first qualified (walk-forward) for a month up to Apr 2026",
                           "first4": "the 4 wallets qualified for Dec 2025 (the paper's 'fast tier grew from 4')",
                           "entrants": "wallets first qualified from May 2026 on",
                           "survivorship": "a wallet that stops trading simply drops out of a month; no wallet is "
                                           "picked on the months it is scored on (walk-forward)"}
    comp["entrants_may2026"] = {"new_wallets": int(is_rows.set_index("month").n_wallets["2026-05"]
                                                   - is_rows.set_index("month").n_wallets["2026-04"]),
                                "share_of_may_prints": r(ism["2026-05"]["entrants"]["n_prints"]
                                                         / (ism["2026-05"]["entrants"]["n_prints"]
                                                            + ism["2026-05"]["incumbents"]["n_prints"])),
                                "gross30_c": ism["2026-05"]["entrants"]["gross30_c"],
                                "net30_c": ism["2026-05"]["entrants"]["net30_c"]}
    comp["by_month"] = {m: {"incumbents": e["incumbents"], "entrants": e["entrants"], "first4": e["first4"]}
                        for m, e in ism.items()}
    coh = (F.groupby(["cohort", "month_s"]).agg(n=("net_c", "size"), gross=("gross_c", "mean"), net=("net_c", "mean"))
           .reset_index())
    comp["by_cohort"] = [{"cohort": str(z.cohort), "month": z.month_s, "n_prints": int(z.n), "gross30_c": r(z.gross),
                          "net30_c": r(z.net)} for z in coh.itertuples()]

    # ============================================================================ 7. the profit pool
    ism_df = pd.DataFrame([{"month": m, "t": tidx(m), "pnl30_usd": e["pnl30_usd"], "pnl_res_usd": e["pnl_to_resolution_usd"],
                            "usd": e["usd"], "net30_c": e["net30_c"], "shares": e["shares"]} for m, e in ism.items()])
    ism_df = ism_df.merge(is_rows[["month", "n_wallets", "n_matches"]], on="month")
    ism_df["universe_matches"] = [is_aug_matches if m == "2026-08" else int(matches_by_month.get(m, 0))
                                  for m in ism_df.month]
    ism_df["proxy_usd"] = ism_df.net30_c / 100 * ism_df.usd
    ism_df["kappa"] = ism_df.pnl30_usd / ism_df.proxy_usd
    ism_df["pnl30_per_wallet"] = ism_df.pnl30_usd / ism_df.n_wallets
    ism_df["pnl30_per_universe_match"] = ism_df.pnl30_usd / ism_df.universe_matches
    prof = ism_df[ism_df.month >= "2026-01"].reset_index(drop=True)     # Dec 2025: 17 catalogue matches
    profit = {
        "what": "Fast-tier $ P&L per month at the 30 s mark after fees (sum of shares x net markout), IS prints. "
                "Dec 2025 is left out of the fits (17 catalogue matches that month, a coverage artefact).",
        "by_month_is": [{k: (r(v, 2) if isinstance(v, float) else v) for k, v in z.items()}
                        for z in ism_df.to_dict("records")],
        "kappa_note": "kappa = exact $ P&L / (print-mean edge x $ volume). It is ~2 because a dollar buys ~2 shares at "
                      "~50c and larger prints earn more per share; it moves month to month, so the proxy is a rough "
                      "guide for the OOS months only.",
    }
    for nm, col in (("total", "pnl30_usd"), ("per_wallet", "pnl30_per_wallet"),
                    ("per_catalogue_match", "pnl30_per_universe_match")):
        f_t = wls(np.c_[np.ones(len(prof)), prof.t], np.log(prof[col]))
        f_w = wls(np.c_[np.ones(len(prof)), np.log(prof.n_wallets)], np.log(prof[col]))
        profit[f"{nm}_log_trend"] = fit_report(f_t, ["intercept", "slope_log_per_month"],
                                               f"OLS of ln({col}) on t, Jan-Aug 2026 IS",
                                               {"monthly_change_pct": r((math.exp(f_t['coef'][1]) - 1) * 100, 2),
                                                "monthly_change_pct_ci95": r([(math.exp(v) - 1) * 100 for v in f_t["ci"][1]], 2)})
        profit[f"{nm}_elasticity_wrt_wallets"] = fit_report(f_w, ["intercept", "elasticity"],
                                                            f"OLS of ln({col}) on ln(fast wallets), Jan-Aug 2026 IS")
    # recent plateau: May-Aug (1 s delay era) totals, and the published-row proxy for all calendar months
    post = ism_df[ism_df.month.isin(["2026-05", "2026-06", "2026-07", "2026-08"])]
    profit["is_may_aug_mean_pnl30_usd_per_month"] = r(post.pnl30_usd.mean(), 0)
    profit["is_may_aug_cv_pnl30"] = r(post.pnl30_usd.std() / post.pnl30_usd.mean(), 3)
    jm = ism_df[ism_df.month.isin(["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"])]
    profit["per_wallet_jan_may_mean_usd"] = r(jm.pnl30_per_wallet.mean(), 0)
    profit["per_wallet_aug_is_usd"] = r(ism_df.set_index("month").pnl30_per_wallet["2026-08"], 0)
    k_recent = float(ism_df[ism_df.month.isin(B_MONTHS)].pnl30_usd.sum() / ism_df[ism_df.month.isin(B_MONTHS)].proxy_usd.sum())
    profit["kappa_jun_aug_is"] = r(k_recent, 3)
    profit["kappa_range_jan_aug_is"] = r([ism_df[ism_df.month >= "2026-01"].kappa.min(),
                                          ism_df[ism_df.month >= "2026-01"].kappa.max()], 3)
    profit["calendar_proxy"] = [{"month": z.month, "n_wallets": z.n_wallets, "proxy_usd": r(z.proxy_usd, 0),
                                 "proxy_x_kappa_usd": r(z.proxy_usd * k_recent, 0),
                                 "per_wallet_proxy_x_kappa_usd": r(z.proxy_usd * k_recent / z.n_wallets, 0),
                                 "pnl30_usd_exact": r(z.pnl30_usd, 0) if isinstance(z.pnl30_usd, float) and
                                 not math.isnan(z.pnl30_usd) else None, "partial_month": bool(z.partial_month)}
                                for z in C.itertuples()]
    fullp = C[(~C.partial_month) & (C.month >= "2026-01")].reset_index(drop=True)
    f_pt = wls(np.c_[np.ones(len(fullp)), fullp.t], np.log(fullp.proxy_usd))
    f_pw = wls(np.c_[np.ones(len(fullp)), fullp.t], np.log(fullp.proxy_usd / fullp.n_wallets))
    profit["proxy_total_log_trend_jan_sep"] = fit_report(
        f_pt, ["intercept", "slope_log_per_month"], "OLS of ln(edge x $ volume) on t, Jan-Sep 2026 (OOS rows proxy)",
        {"monthly_change_pct": r((math.exp(f_pt['coef'][1]) - 1) * 100, 2),
         "monthly_change_pct_ci95": r([(math.exp(v) - 1) * 100 for v in f_pt["ci"][1]], 2)})
    profit["proxy_per_wallet_log_trend_jan_sep"] = fit_report(
        f_pw, ["intercept", "slope_log_per_month"], "OLS of ln(edge x $ volume / wallets) on t, Jan-Sep 2026",
        {"monthly_change_pct": r((math.exp(f_pw['coef'][1]) - 1) * 100, 2),
         "monthly_change_pct_ci95": r([(math.exp(v) - 1) * 100 for v in f_pw["ci"][1]], 2)})
    sep = C[C.month == "2026-09"].iloc[0]
    profit["sep2026_proxy_x_kappa_usd"] = r(sep.proxy_usd * k_recent, 0)
    profit["sep2026_per_wallet_proxy_x_kappa_usd"] = r(sep.proxy_usd * k_recent / sep.n_wallets, 0)

    # ============================================================================ 8. projections
    t_sep = float(tidx(str(LAST_FULL)))
    proj = {"from_month": str(LAST_FULL), "note": "months after Sep 2026 (last full month) until the fitted line hits 0; "
            "Fieller 95% interval from each fit's own covariance. A straight line through a series that dropped "
            "Feb-May and then went flat is the pessimistic reading; the log fit never reaches zero."}
    for nm, f_ in (("linear_wls_cal11", f_wls11), ("linear_ols_cal11", f_ols11), ("linear_wls_full10", f_wls10),
                   ("linear_ols_is9_paper", None)):
        if f_ is None:
            x0, lo, hi, bd = fieller_root(f_is9, 8.0)     # IS row index 8 = Aug 2026; +1 to Sep
            x0, lo, hi = x0 - 1, (lo - 1 if lo is not None else None), (hi - 1 if hi is not None else None)
        else:
            x0, lo, hi, bd = fieller_root(f_, t_sep)
        proj[nm] = {"months_to_zero": r(x0, 2), "ci95": [r(lo, 2), r(hi, 2)] if bd else "unbounded",
                    "zero_month": str(LAST_FULL + int(math.ceil(x0))) if x0 > 0 else "already below 0"}
    # post-break only: the 1 s-delay months (Jun 2026 on, 4 full months + Oct)
    post_c = C[C.month >= "2026-06"].reset_index(drop=True)
    f_post = lin(post_c, w="n_matches")
    x0, lo, hi, bd = fieller_root(f_post, t_sep)
    proj["post_break_jun_oct"] = {"fit": fit_report(f_post, ["intercept", "slope_c_per_month"],
                                                    "WLS on Jun-Oct 2026 only (1 s / fee regime era)"),
                                  "months_to_zero": r(x0, 2), "ci95": [r(lo, 2), r(hi, 2)] if bd else "unbounded"}
    proj["log_half_life_months"] = fits["log_wls_cal11"]["half_life_months"]
    proj["log_half_life_ci95"] = fits["log_wls_cal11"]["half_life_months_ci95"]

    # break-even taker fee for the fast tier (what fee rate takes its net edge to zero)
    d5 = F[F.reg == "1 s / 5%"]
    pm5 = per_match(d5, ["gross_c", "fee_c"])
    be, be_ci = boot_ratio(pm5.gross_c.to_numpy() * 5.0, pm5.fee_c.to_numpy(), rng)
    oos_gross = oos_pw_only + oos_fee
    proj["breakeven_fee_rate_pct"] = {
        "is_1s_5pct_prints": r(be, 2), "ci95": r(be_ci, 2),
        "burned_oos_approx": r(5.0 * oos_gross / oos_fee, 2),
        "how": "5% x gross / fee at 5% (fee is linear in the rate). IS = Jul-Aug 2026 prints in the 1 s / 5% regime, "
               "match-clustered CI; OOS approx = 5% x (OOS-only print-weighted net + OOS mean fee) / OOS mean fee",
        "today_pct": 5.0,
    }

    # step model: one level shift in May 2026 (the best data-chosen break, and the month the 1 s hold and the big
    # entrant cohort both arrived) against the straight line, same y, same weights
    C["post_may"] = (C.t >= tidx("2026-05")).astype(float)
    f_step = wls(np.c_[np.ones(len(C)), C.post_may], C.net30_c, C.n_matches)
    f_step_t = wls(np.c_[np.ones(len(C)), C.t, C.post_may], C.net30_c, C.n_matches)
    post_lvl = f_step["coef"][0] + f_step["coef"][1]
    v_post = f_step["cov"][0, 0] + f_step["cov"][1, 1] + 2 * f_step["cov"][0, 1]
    proj["step_model_may2026"] = {
        "label": "WLS of net edge on a May-2026 step (weights = matches); compares with the straight line on AICc",
        "level_before_c": r(f_step["coef"][0]), "level_before_ci95": r(f_step["ci"][0]),
        "level_after_c": r(post_lvl), "level_after_ci95": r([post_lvl - f_step["tcrit"] * math.sqrt(v_post),
                                                             post_lvl + f_step["tcrit"] * math.sqrt(v_post)]),
        "step_c": r(f_step["coef"][1]), "step_ci95": r(f_step["ci"][1]),
        "aicc_step": r(f_step["aicc"], 3), "aicc_linear": r(f_wls11["aicc"], 3),
        "trend_given_step_c_per_month": r(f_step_t["coef"][1]), "trend_given_step_ci95": r(f_step_t["ci"][1]),
        "reading": "the step fits at least as well as the line (lower AICc); with the step in, no trend is left, so "
                   "on this reading the edge is not heading to zero at any measurable pace",
    }

    # ============================================================================ 9. economic reading (plain words)
    gw = fits["gross_linear_wls_cal11"]["slope_c_per_month"]
    gx = fits["gross_linear_wls_is9_exact"]["slope_c_per_month"]
    nw = fits["linear_wls_cal11"]["slope_c_per_month"]
    fw = fits["fee_linear_wls_cal11"]["slope_c_per_month"]
    el = fits["elasticity_edge_wrt_wallets"]["elasticity"]
    elg = fits["elasticity_gross_wrt_wallets"]["elasticity"]
    lg = fits["log_wls_cal11"]
    pz = proj["linear_wls_cal11"]
    st = proj["step_model_may2026"]
    inc = comp["incumbents_gross_trend_jan_aug"]["month_level_primary"]
    f4 = comp["first4_gross_trend_jan_aug"]["month_level_primary"]
    nat_d, nat_f = natural["delay_3s_to_1s_may2026"], natural["fee_3_to_5_jul2026"]
    pwe = profit["per_wallet_elasticity_wrt_wallets"]["elasticity"]
    toe = profit["total_elasticity_wrt_wallets"]["elasticity"]
    oth = (float(C.others_net30_c.min()), float(C.others_net30_c.max()))
    reading = {
        "who_pays": (f"The fast tier hits resting quotes that still show the pre-point price, so the maker on the other "
                     f"side loses the gross markout (about {point['gross_B_c']:.1f}c a share in Jun-Aug 2026). The venue "
                     f"keeps the taker fee ({nat_f['fee']['b_c']:.2f}c a share on 1 s / 5% prints in Jul 2026), and other "
                     f"takers trading in the same 0-3 s lose {-oth[1]:.1f}-{-oth[0]:.1f}c a share."),
        "what_the_decline_is": (f"The net edge fell {-nw['coef']:.2f}c a month (WLS, 11 calendar months, CI "
                                f"{nw['ci95'][0]:+.2f} to {nw['ci95'][1]:+.2f}). Over the same months the fee rose "
                                f"{fw['coef']:+.2f}c a month while the gross edge moved {gw['coef']:+.2f}c a month (CI "
                                f"{gw['ci95'][0]:+.2f} to {gw['ci95'][1]:+.2f}; IS-only exact {gx['coef']:+.2f}, CI "
                                f"{gx['ci95'][0]:+.2f} to {gx['ci95'][1]:+.2f}). From Dec-Apr to Jun-Aug the net edge fell "
                                f"{-point['delta_net_c']:.2f}c: {-point['fee_part_c']:.2f}c is the fee, "
                                f"{-point['entrant_dilution_c']:.2f}c is weaker wallets joining, and the early wallets' "
                                f"own gross edge moved {point['incumbents_gross_change_c']:+.2f}c."),
        "venue_rules": (f"Within May 2026, the same wallets earned {nat_d['net30']['b_minus_a_c']:+.2f}c (CI "
                        f"{nat_d['net30']['ci95'][0]:+.2f} to {nat_d['net30']['ci95'][1]:+.2f}) more on 1 s-hold matches "
                        f"than on 3 s ones, so the shorter hold did not hurt them. Within Jul 2026, 5%-fee matches paid "
                        f"{nat_f['net30']['b_minus_a_c']:+.2f}c (CI {nat_f['net30']['ci95'][0]:+.2f} to "
                        f"{nat_f['net30']['ci95'][1]:+.2f}) net with the same gross (difference "
                        f"{nat_f['gross30']['b_minus_a_c']:+.2f}c, CI {nat_f['gross30']['ci95'][0]:+.2f} to "
                        f"{nat_f['gross30']['ci95'][1]:+.2f}): the fee is passed straight through. The best single "
                        f"break in the net series is May 2026; a step there (AICc {st['aicc_step']:.1f}) fits at least as "
                        f"well as a straight line ({st['aicc_linear']:.1f}) and leaves a trend of "
                        f"{st['trend_given_step_c_per_month']:+.2f}c a month (CI {st['trend_given_step_ci95'][0]:+.2f} to "
                        f"{st['trend_given_step_ci95'][1]:+.2f})."),
        "why_it_can_persist": (f"Someone always sees the point before the book reprices (court, broadcast and data-feed "
                               f"delays are physical) and the 1 s hold only narrows that window. Wallets already fast by "
                               f"Apr 2026 kept their gross edge ({inc['slope_c_per_month']:+.2f}c a month, CI "
                               f"{inc['ci95'][0]:+.2f} to {inc['ci95'][1]:+.2f}) while the field grew from "
                               f"{int(C.n_wallets.iloc[0])} to {int(C.n_wallets.iloc[-1])} wallets; the first four slipped "
                               f"{-f4['slope_c_per_month']:.2f}c a month (CI {f4['ci95'][0]:+.2f} to {f4['ci95'][1]:+.2f}, not significant)."),
        "what_kills_it": (f"(1) A higher fee: the fast tier's gross edge covers a taker fee of up to {be:.1f}% (today "
                          f"5%). (2) A longer taker hold or makers on a faster official feed, which would remove the "
                          f"stale quotes. (3) More entrants: the monthly pool grew with wallets at elasticity "
                          f"{toe['coef']:.2f} (CI {toe['ci95'][0]:.2f} to {toe['ci95'][1]:.2f}), so each wallet's share "
                          f"fell at {pwe['coef']:.2f} (CI {pwe['ci95'][0]:.2f} to {pwe['ci95'][1]:.2f}) per 1% more "
                          f"wallets, from ${profit['per_wallet_jan_may_mean_usd']:,.0f} a month (Jan-May 2026 mean) to "
                          f"${profit['per_wallet_aug_is_usd']:,.0f} in Aug (IS part)."),
        "for_an_entrant": "The number that matters is the pool and one wallet's share of it, not the average edge per "
                          "share. The pool has been flat since May 2026 while wallets kept arriving.",
        "projection": (f"A straight line says zero in {pz['months_to_zero']:.1f} months after Sep 2026 (Fieller CI "
                       f"{pz['ci95'][0]:.1f} to {pz['ci95'][1]:.1f}); a constant % decline says {-lg['monthly_change_pct']:.0f}% "
                       f"less a month (half-life {lg['half_life_months']:.1f} months, CI {lg['half_life_months_ci95'][0]:.1f} to "
                       f"{lg['half_life_months_ci95'][1]:.1f}); the step model says flat at {st['level_after_c']:.2f}c. The "
                       f"data cannot tell these apart, and only the line reaches zero."),
    }

    # ============================================================================ 10. paper keys
    def K(v, nd=2, sign=False):
        s_ = f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"
        return s_.replace("-", "−")

    def CI(ci, nd=2):
        return f"[{K(ci[0], nd)}, {K(ci[1], nd)}]"

    keys = {
        "pers.slope.net": (K(nw["coef"]), "::fits.linear_wls_cal11.slope_c_per_month.coef"),
        "pers.slope.net.ci": (CI(nw["ci95"]), "::fits.linear_wls_cal11.slope_c_per_month.ci95"),
        "pers.slope.gross": (K(gw["coef"], sign=True), "::fits.gross_linear_wls_cal11.slope_c_per_month.coef"),
        "pers.slope.gross.ci": (CI(gw["ci95"]), "::fits.gross_linear_wls_cal11.slope_c_per_month.ci95"),
        "pers.slope.gross.is": (K(gx["coef"], sign=True), "::fits.gross_linear_wls_is9_exact.slope_c_per_month.coef"),
        "pers.slope.gross.is.ci": (CI(gx["ci95"]), "::fits.gross_linear_wls_is9_exact.slope_c_per_month.ci95"),
        "pers.slope.fee": (K(fw["coef"], sign=True), "::fits.fee_linear_wls_cal11.slope_c_per_month.coef"),
        "pers.logdecay.pct": (K(lg["monthly_change_pct"], 1), "::fits.log_wls_cal11.monthly_change_pct"),
        "pers.halflife": (K(lg["half_life_months"], 1), "::fits.log_wls_cal11.half_life_months"),
        "pers.halflife.ci": (CI(lg["half_life_months_ci95"], 1), "::fits.log_wls_cal11.half_life_months_ci95"),
        "pers.elast": (K(el["coef"]), "::fits.elasticity_edge_wrt_wallets.elasticity.coef"),
        "pers.elast.ci": (CI(el["ci95"]), "::fits.elasticity_edge_wrt_wallets.elasticity.ci95"),
        "pers.elast.gross": (K(elg["coef"], sign=True), "::fits.elasticity_gross_wrt_wallets.elasticity.coef"),
        "pers.elast.gross.ci": (CI(elg["ci95"]), "::fits.elasticity_gross_wrt_wallets.elasticity.ci95"),
        "pers.zero.months": (K(pz["months_to_zero"], 1), "::projections.linear_wls_cal11.months_to_zero"),
        "pers.zero.ci": (CI(pz["ci95"], 1), "::projections.linear_wls_cal11.ci95"),
        "pers.step.after": (K(st["level_after_c"]), "::projections.step_model_may2026.level_after_c"),
        "pers.step.trend": (K(st["trend_given_step_c_per_month"], sign=True),
                            "::projections.step_model_may2026.trend_given_step_c_per_month"),
        "pers.step.trend.ci": (CI(st["trend_given_step_ci95"]), "::projections.step_model_may2026.trend_given_step_ci95"),
        "pers.dnet": (K(point["delta_net_c"]), "::composition.delta_net_c"),
        "pers.dfee": (K(point["fee_part_c"]), "::composition.fee_part_c"),
        "pers.ddilution": (K(point["entrant_dilution_c"]), "::composition.entrant_dilution_c"),
        "pers.dincumbent": (K(point["incumbents_gross_change_c"], sign=True), "::composition.incumbents_gross_change_c"),
        "pers.inc.trend": (K(inc["slope_c_per_month"], sign=True),
                           "::composition.incumbents_gross_trend_jan_aug.month_level_primary.slope_c_per_month"),
        "pers.inc.trend.ci": (CI(inc["ci95"]), "::composition.incumbents_gross_trend_jan_aug.month_level_primary.ci95"),
        "pers.befee": (f"{be:.1f}%", "::projections.breakeven_fee_rate_pct.is_1s_5pct_prints"),
        "pers.pool.mayaug": (f"${profit['is_may_aug_mean_pnl30_usd_per_month'] / 1e3:.0f}k",
                             "::profit.is_may_aug_mean_pnl30_usd_per_month"),
        "pers.pool.elast": (K(toe["coef"]), "::profit.total_elasticity_wrt_wallets.elasticity.coef"),
        "pers.pool.elast.ci": (CI(toe["ci95"]), "::profit.total_elasticity_wrt_wallets.elasticity.ci95"),
        "pers.pool.perwallet.janmay": (f"${profit['per_wallet_jan_may_mean_usd']:,.0f}",
                                       "::profit.per_wallet_jan_may_mean_usd"),
        "pers.pool.perwallet.aug": (f"${profit['per_wallet_aug_is_usd']:,.0f}", "::profit.per_wallet_aug_is_usd"),
        "pers.pool.perwallet.elast.ci": (CI(pwe["ci95"]), "::profit.per_wallet_elasticity_wrt_wallets.elasticity.ci95"),
        "pers.pool.perwallet.elast": (K(pwe["coef"]), "::profit.per_wallet_elasticity_wrt_wallets.elasticity.coef"),
        "pers.delay.may": (K(nat_d["net30"]["b_minus_a_c"], sign=True),
                           "::regime.natural_experiments.delay_3s_to_1s_may2026.net30.b_minus_a_c"),
        "pers.delay.may.ci": (CI(nat_d["net30"]["ci95"]), "::regime.natural_experiments.delay_3s_to_1s_may2026.net30.ci95"),
        "pers.fee35.jul": (K(nat_f["net30"]["b_minus_a_c"], sign=True),
                           "::regime.natural_experiments.fee_3_to_5_jul2026.net30.b_minus_a_c"),
        "pers.fee35.jul.ci": (CI(nat_f["net30"]["ci95"]), "::regime.natural_experiments.fee_3_to_5_jul2026.net30.ci95"),
        "ft.c.oos.only": (f"{oos_pw_only:+.2f}", "::aug_overlap.oos_print_weighted_net30_c_oos_prints_only_derived"),
    }
    paper_keys = {k: {"value": v, "source": "results/economics/persistence.json" + s} for k, (v, s) in keys.items()}

    out = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": "scripts/edge_persistence.py",
        "git_head": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                   text=True).stdout.strip(),
        "labels": {
            "edge": "net 30 s markout per print, c/share, after each match's taker fee (published H6 measure)",
            "gross": "same, before the fee",
            "IS": "in sample (matches starting before 2026-08-25 14:15 UTC)",
            "OOS": "burned OOS months enter only as their published monthly aggregates; no OOS print read here",
            "t": "months since 2025-12",
        },
        "oos_rule": "No held-out print, tape or trade file is opened (HYPOTHESIS_V2.md; results/oos_peeks.log). The OOS "
                    "months are the rows already published in results/summary.json::oos.h6_walkforward.",
        "inputs": SRC,
        "checks": {"is_walkforward_reproduced": repro,
                   "fee_check_is_print_mean_vs_shadow": {"print_mean_fee_c": r(is_fee_prints),
                                                         "shadow_mean_fee_c": r(is_fee_shadow),
                                                         "note": "the OOS gross uses the shadow-book mean fee; in IS the "
                                                                 "two agree to the printed difference"}},
        "aug_overlap": aug_note,
        "series_calendar": [{k: (r(v) if isinstance(v, float) else v) for k, v in z.items()} for z in cal],
        "series_is_months": {m: {k: (r(v) if isinstance(v, float) else v) for k, v in e.items()} for m, e in ism.items()},
        "fits": fits,
        "regime": {**regime, "breaks": breaks, "natural_experiments": natural},
        "composition": comp,
        "profit": profit,
        "projections": proj,
        "reading": reading,
        "paper_keys": paper_keys,
        "runtime_s": None,
    }
    out["runtime_s"] = r(time.time() - T0, 1)
    (OUT / "persistence.json").write_text(json.dumps(out, indent=1, default=lambda x: r(x) if isinstance(
        x, (np.floating, float)) else (int(x) if isinstance(x, np.integer) else str(x))))
    print(json.dumps({k: v["value"] for k, v in paper_keys.items()}, indent=1, ensure_ascii=False))
    figure(C, ism, profit)
    print(f"done in {time.time() - T0:.1f}s")


# ================================================================================================ figure
def figure(C, ism, profit):
    import figstyle as fs
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    fs.apply()
    K, G = fs.INK, fs.GREY
    fig = plt.figure(figsize=(fs.FIG_W, 5.0))
    ax = fs.axes_in(fig, 0.62, 2.95, 5.05, 1.45)
    bx = fs.axes_in(fig, 0.62, 0.48, 2.0, 1.75)
    cx = fs.axes_in(fig, 4.0, 0.48, 1.9, 1.75)

    # a: net vs gross edge by calendar month, venue-rule dates
    x = C.t.to_numpy()
    is_m = (C.period == "IS").to_numpy()
    for col, colr, lab in (("gross30_c", G, "before fee"), ("net30_c", K, "after fee (published)")):
        y = C[col].to_numpy()
        ax.plot(x, y, color=colr, lw=fs.LW_2 if colr == G else fs.LW, zorder=3)
        ax.plot(x[is_m], y[is_m], "o", color=colr, ms=4, zorder=4)
        ax.plot(x[~is_m], y[~is_m], "o", mfc="white", mec=colr, mew=1.0, ms=4, zorder=4)
    for m, e in ism.items():
        if m in set(C.month[is_m]):
            t = tidx(m)
            fs.whiskers(ax, [t], [e["net30_c"]], [e["net30_ci95_c"][0]], [e["net30_ci95_c"][1]], K, lw=0.7)
    fs.zero_line(ax)
    fs.hgrid(ax)
    ax.set_xlim(-0.5, 10.5)
    ax.set_ylim(0, 3.2)
    ticks = list(range(0, 11))
    labs = [pd.Period("2025-12", "M") + i for i in ticks]
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: (labs[int(v)].strftime("%b") if int(v) % 2 == 0 else "")))
    ax.yaxis.set_major_locator(FixedLocator([0, 1, 2, 3]))
    ax.set_ylabel(f"c/share, 30{fs.THIN}s")
    fs.oos_shade(ax, tidx("2026-08") + 24.6 / 31 - 0.5, 10.5, label="OOS", y=0.97, va="top", pad_pt=3)
    fs.vref_labelled(ax, [(tidx("2026-04") - 0.5, "3% fee", 1), (tidx("2026-05") + 14 / 31 - 0.5, "1 s hold", 2),
                          (tidx("2026-07") + 10 / 31 - 0.5, "5% fee", 1)])
    fs.direct_label(ax, [{"x": 10, "y": C.gross30_c.iloc[-1], "text": "before fee", "color": G},
                         {"x": 10, "y": C.net30_c.iloc[-1], "text": "after fee", "color": K}], dx_pt=5)
    fs.panel(ax, "a", "Most of the fall is the taker fee", y_in=4.83, x_in=0.06)

    # b: incumbents vs entrants (IS months, gross before fee)
    ms_ = [m for m in ism if m >= "2026-01"]
    tb = np.array([tidx(m) for m in ms_])
    gi = np.array([ism[m]["incumbents"]["gross30_c"] for m in ms_], float)
    ge = np.array([np.nan if ism[m]["entrants"]["gross30_c"] is None else ism[m]["entrants"]["gross30_c"] for m in ms_])
    bx.plot(tb, gi, "-o", color=K, ms=4)
    ok = ~np.isnan(ge)
    bx.plot(tb[ok], ge[ok], "-o", color=G, ms=4, lw=fs.LW_2)
    fs.hgrid(bx)
    fs.zero_line(bx)
    bx.set_ylim(0, 3.2)
    bx.set_xlim(0.6, 8.4)
    bx.yaxis.set_major_locator(FixedLocator([0, 1, 2, 3]))
    bx.xaxis.set_major_locator(FixedLocator([1, 3, 5, 7]))
    bx.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: labs[int(v)].strftime("%b")))
    bx.set_ylabel("gross c/share (IS)")
    fs.direct_label(bx, [{"x": tb[-1], "y": gi[-1], "text": "in by\nApr", "color": K},
                         {"x": tb[-1], "y": ge[-1], "text": "from\nMay", "color": G}], dx_pt=4)
    fs.panel(bx, "b", "Early wallets kept their gross edge", y_in=2.43, x_in=0.06)

    # c: monthly $ pool and per wallet (IS exact), log $ axis
    pr = [z for z in profit["by_month_is"] if z["month"] >= "2026-01"]
    tc_ = np.array([tidx(z["month"]) for z in pr])
    tot = np.array([z["pnl30_usd"] for z in pr], float)
    pw = np.array([z["pnl30_per_wallet"] for z in pr], float)
    cx.plot(tc_, tot, "-o", color=K, ms=4)
    cx.plot(tc_, pw, "-o", color=G, ms=4, lw=fs.LW_2)
    cx.set_yscale("log")
    cx.set_ylim(150, 1.5e5)
    cx.yaxis.set_major_locator(FixedLocator([300, 1e3, 3e3, 1e4, 3e4, 1e5]))
    cx.yaxis.set_minor_locator(NullLocator())
    cx.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"${v / 1e3:g}k" if v >= 1e3 else f"${v:g}"))
    cx.set_xlim(0.6, 8.4)
    cx.xaxis.set_major_locator(FixedLocator([1, 3, 5, 7]))
    cx.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: labs[int(v)].strftime("%b")))
    fs.hgrid(cx)
    cx.set_ylabel(f"$ a month, 30{fs.THIN}s mark")
    fs.direct_label(cx, [{"x": tc_[-1], "y": tot[-1], "text": "all fast\nwallets", "color": K},
                         {"x": tc_[-1], "y": pw[-1], "text": "per\nwallet", "color": G}], dx_pt=4)
    fs.panel(cx, "c", "Pool flat since May, split more ways", y_in=2.43, x_in=3.34)
    meta = {"Creator": "scripts/edge_persistence.py", "Title": "persistence"}
    for p in fs.save_fig(fig, "persistence", OUT, meta=meta):
        print("wrote", p)


if __name__ == "__main__":
    main()
