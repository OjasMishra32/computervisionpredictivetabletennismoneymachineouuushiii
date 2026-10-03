"""Rigor pack: overfitting and significance statistics on EXISTING v2 results (analysis only).

    .venv/bin/python scripts/rigor_pack.py          # ~1-2 min, 1 process
      -> results/rigor/rigor.json, results/rigor/rigor.png, research/rigor/RESULTS.md,
         research/rigor/out/{daily_series,sizing_daily_is_res_actual,sizing_daily_is_m30x_actual}.csv

Nothing here re-tunes or changes any strategy rule. Inputs:
  data/v2_trades_is_oos.parquet       v2 causal trades (scripts/v2_causal.py); IS = month >= 2026-02 and
                                      cond not in universe().oos; burned OOS = cond in universe().oos
  research/v2/lowloss/out/daily.csv   v2-safe 24-variant grid, zero-filled daily P&L (IS, Jan-Aug)
  results/lowloss/daily.csv           v2 / v2-safe daily books from scripts/lowloss_test.py (burned OOS, U2)
  research/v2/sizing/*                sizing lens grid: daily P&L is NOT saved, so it is rebuilt here by
                                      re-running engine.simulate on the IS features for the lens's own
                                      policies (~0.6 s each); every rebuilt Sharpe must equal policies.csv
  results/v2/causal.json, results/lowloss/results.json    capital (3 x peak locked) and reference Sharpes
Guard: rows of matches starting on/after 2026-10-03 13:00 UTC are dropped (there are none today).

Statistics (all on calendar-day, zero-filled daily P&L; Sharpe = mean/sd(ddof=1) x sqrt(365)):
  1. Sharpe, skew, kurtosis (bias-corrected sample moments; kurtosis is Pearson, normal = 3), lag-1 AC.
  2. PSR and DSR (Bailey & Lopez de Prado 2014). SR* = E[max SR of N trials]
       = sqrt(V) * ((1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N e))),  g = Euler-Mascheroni,
     with V from three sources: the null (V = 1/(T-1), the NOTE.md section 8 convention), the 24-variant
     v2-safe grid, and the 55-policy sizing grid (cross-variant variance of daily IS Sharpes).
  3. PBO by CSCV (Bailey, Borwein, Lopez de Prado & Zhu 2017), S = 16 blocks, all C(16, 8) = 12,870
     splits: logit of the OOS relative rank of the IS-best variant, PBO = P(logit <= 0), and the
     performance-degradation regression of OOS on IS performance of the IS-best variant.
  4. Stationary block bootstrap (Politis & Romano 1994), mean block 5 days, 10,000 draws: percentile
     95% CIs for annualised Sharpe and for mean daily P&L.
  5. Minimum track record length (Bailey & Lopez de Prado 2012) to reject SR <= 0 at 95%.
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research/v2/sizing"))
from src.tape import universe  # noqa: E402

CUTOFF = pd.Timestamp("2026-10-03 13:00", tz="UTC")       # never read matches starting on/after this
EVAL_START = "2026-02"
IS_CAL = pd.date_range("2026-02-01", "2026-08-25", freq="D", tz="UTC")
OOS_CAL = pd.date_range("2026-08-25", "2026-10-03", freq="D", tz="UTC")
ANN = np.sqrt(365)
SEED = 20261003
N_BOOT, MEAN_BLOCK, S_BLOCKS = 10_000, 5, 16
N_H = 44                      # H1-H6 variants (docs/NOTE.md section 8)
N_V2_LENSES = 3_342           # six v2 lenses (exit 902, sizing 111, selection 341, cross-market 68, latency 16, Kalshi 1,904)
N_ALL = N_H + N_V2_LENSES     # 3,386
N_WITH_LOWLOSS = N_ALL + 24   # + the v2-safe grid, which was run after NOTE section 8's count
EULER = 0.5772156649015329
Z95 = stats.norm.ppf(0.95)
V2_SAFE_COL = "n50_d50_z05-95_sinf"
LL_BASE_COL = "n100_d50_z05-95_sinf"

OUT_JSON = ROOT / "results/rigor/rigor.json"
OUT_PNG = ROOT / "results/rigor/rigor.png"
OUT_MD = ROOT / "research/rigor/RESULTS.md"
OUT_DIR = ROOT / "research/rigor/out"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------------------------- stats
def sharpe_d(x: np.ndarray) -> float:
    sd = x.std(ddof=1)
    return float(x.mean() / sd) if sd > 0 else float("nan")


def moments(x: np.ndarray) -> dict:
    x = np.asarray(x, float)
    sr = sharpe_d(x)
    return {
        "T_days": int(len(x)), "active_days": int((x != 0).sum()),
        "sharpe_ann": sr * ANN, "sharpe_daily": sr,
        "mean_daily_usd": float(x.mean()), "sd_daily_usd": float(x.std(ddof=1)),
        "skew": float(stats.skew(x, bias=False)),
        "kurtosis": float(stats.kurtosis(x, fisher=False, bias=False)),
        "ac1": float(np.corrcoef(x[:-1], x[1:])[0, 1]),
        "total_usd": float(x.sum()),
    }


def psr(sr: float, sr_star: float, T: int, skew: float, kurt: float) -> float:
    """Probabilistic Sharpe ratio, per-observation (daily) units."""
    den = np.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    return float(stats.norm.cdf((sr - sr_star) * np.sqrt(T - 1) / den))


def expected_max_sr(var_sr: float, n: int) -> float:
    """E[max of n trial Sharpes] under zero true skill, given cross-trial variance var_sr (daily units)."""
    return float(np.sqrt(var_sr) * ((1 - EULER) * stats.norm.ppf(1 - 1 / n)
                                    + EULER * stats.norm.ppf(1 - 1 / (n * np.e))))


def min_trl(sr: float, sr_star: float, skew: float, kurt: float, z: float = Z95) -> float:
    if not sr > sr_star:
        return float("inf")
    return float(1 + (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) * (z / (sr - sr_star)) ** 2)


def stationary_bootstrap_idx(T: int, B: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano: block lengths ~ Geometric(1/mean_block), random starts, circular wrap."""
    p = 1.0 / mean_block
    idx = np.empty((B, T), dtype=np.int32)
    idx[:, 0] = rng.integers(0, T, B)
    new = rng.random((B, T)) < p
    starts = rng.integers(0, T, (B, T))
    for t in range(1, T):
        idx[:, t] = np.where(new[:, t], starts[:, t], (idx[:, t - 1] + 1) % T)
    return idx


def bootstrap(x: np.ndarray, rng: np.random.Generator) -> dict:
    x = np.asarray(x, float)
    xb = x[stationary_bootstrap_idx(len(x), N_BOOT, MEAN_BLOCK, rng)]
    sd = xb.std(axis=1, ddof=1)
    sr = np.where(sd > 0, xb.mean(axis=1) / np.where(sd > 0, sd, 1), np.nan) * ANN
    mu = xb.mean(axis=1)
    q = lambda a: [float(np.nanpercentile(a, 2.5)), float(np.nanpercentile(a, 97.5))]  # noqa: E731
    return {"sharpe_ann_ci95": q(sr), "sharpe_ann_boot_median": float(np.nanmedian(sr)),
            "sharpe_ann_boot_se": float(np.nanstd(sr)), "p_sharpe_le_0": float(np.mean(sr <= 0)),
            "mean_daily_usd_ci95": q(mu), "p_mean_le_0": float(np.mean(mu <= 0)),
            "_sr_draws": sr}


# ------------------------------------------------------------------------------------- CSCV
def cscv(M: np.ndarray, names: list[str], S: int = S_BLOCKS, rule: str = "sharpe",
         base_idx: int | None = None) -> dict:
    """Combinatorially symmetric cross-validation on a T x N daily P&L matrix.

    rule="sharpe": IS-best = highest IS Sharpe; ranked OOS by Sharpe.
    rule="share_feasible": the v2-safe GRID.md rule applied to the IS half (highest share of profitable
      days among variants with mean >= 0.5 x baseline mean; ties -> higher mean -> earlier column;
      none feasible -> baseline); ranked OOS by share of profitable days.
    """
    T, N = M.shape
    blocks = np.array_split(np.arange(T), S)
    bn = np.array([len(b) for b in blocks], float)                       # S
    bs = np.stack([M[b].sum(0) for b in blocks])                          # S x N
    bss = np.stack([(M[b] ** 2).sum(0) for b in blocks])
    bpos = np.stack([(M[b] > 0).sum(0) for b in blocks]).astype(float)
    combos = np.array(list(itertools.combinations(range(S), S // 2)))
    A = np.zeros((len(combos), S))
    A[np.arange(len(combos))[:, None], combos] = 1.0

    def perf(W):
        n = (W @ bn)[:, None]
        s, ss, pos = W @ bs, W @ bss, W @ bpos
        mean = s / n
        var = np.maximum(ss - s ** 2 / n, 0) / (n - 1)
        sd = np.sqrt(var)
        sr = np.where(sd > 0, mean / np.where(sd > 0, sd, 1), -np.inf)
        return sr, mean, pos / n

    sr_is, mu_is, sh_is = perf(A)
    sr_oos, mu_oos, sh_oos = perf(1.0 - A)
    C = len(combos)
    if rule == "sharpe":
        sel = np.argmax(sr_is, axis=1)
        is_metric, oos_metric = sr_is, sr_oos
    elif rule == "share_feasible":
        feas = mu_is >= 0.5 * mu_is[:, [base_idx]]
        msh = np.where(feas, sh_is, -np.inf)
        best = msh.max(axis=1, keepdims=True)
        cand = feas & np.isclose(msh, best, rtol=0, atol=1e-12)
        sel = np.argmax(np.where(cand, mu_is, -np.inf), axis=1)
        sel = np.where(feas.any(axis=1), sel, base_idx)
        is_metric, oos_metric = sh_is, sh_oos
    else:
        raise ValueError(rule)
    rk = stats.rankdata(oos_metric, method="average", axis=1)[np.arange(C), sel]
    w = rk / (N + 1)
    lam = np.log(w / (1 - w))
    x, y = is_metric[np.arange(C), sel], oos_metric[np.arange(C), sel]
    if rule == "sharpe":
        x, y = x * ANN, y * ANN
    slope, intercept, r, _, _ = stats.linregress(x, y)
    picks = pd.Series(np.asarray(names)[sel]).value_counts()
    # control: the same regression for ONE fixed variant (the most frequent pick). IS and OOS halves are
    # complements of a fixed sample, so a fixed variant's half-sample metrics are negatively related by
    # construction; a pick slope close to this control slope is that artifact, not selection decay.
    ci = list(names).index(picks.index[0])
    sc = ANN if rule == "sharpe" else 1.0
    c_slope, _, c_r, _, _ = stats.linregress(is_metric[:, ci] * sc, oos_metric[:, ci] * sc)
    n_distinct = int(len({tuple(np.round(M[:, j], 9)) for j in range(N)}))
    return {
        "rule": rule, "N_variants": int(N), "N_distinct_series": n_distinct, "T_days": int(T),
        "S_blocks": S, "block_days": [int(bn.min()), int(bn.max())], "n_splits": int(C),
        "pbo": float(np.mean(lam <= 0)),
        "logit": {"mean": float(lam.mean()), "median": float(np.median(lam)), "sd": float(lam.std()),
                  "p05": float(np.percentile(lam, 5)), "p25": float(np.percentile(lam, 25)),
                  "p75": float(np.percentile(lam, 75)), "p95": float(np.percentile(lam, 95))},
        "oos_relative_rank_mean": float(w.mean()),
        "degradation": {"metric": "sharpe_ann" if rule == "sharpe" else "profitable_day_share",
                        "slope": float(slope), "intercept": float(intercept), "r2": float(r ** 2),
                        "is_mean": float(x.mean()), "oos_mean": float(y.mean()),
                        "p_oos_below_0": float(np.mean(y < 0)) if rule == "sharpe" else None,
                        "control_fixed_variant": str(picks.index[0]), "control_slope": float(c_slope),
                        "control_r2": float(c_r ** 2)},
        "is_best_pick_freq_top5": {k: int(v) for k, v in picks.head(5).items()},
        "_logits": lam, "_is": x, "_oos": y,
    }


# ------------------------------------------------------------------------------------- data
def daily(df: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.Series:
    d = df.groupby("date").pnl.sum()
    assert d.index.isin(cal).all(), "trade dates outside the calendar"
    return d.reindex(cal, fill_value=0.0)


def load_v2(causal: dict) -> tuple[pd.Series, pd.Series, dict]:
    t = pd.read_parquet(ROOT / "data/v2_trades_is_oos.parquet", columns=["cond", "ts", "date", "month", "pnl"])
    u = universe()
    oos = set(u.loc[u.oos, "cond"])
    start = t.cond.map(u.set_index("cond").start)
    assert start.notna().all(), "trade on a match outside the universe"
    late = start >= CUTOFF
    t = t[~late]
    is_ = t[(t.month >= EVAL_START) & ~t.cond.isin(oos)]
    oo = t[t.cond.isin(oos)]
    d_is, d_oos = daily(is_, IS_CAL), daily(oo, OOS_CAL)
    for d, k in ((d_is, "causal/is_eval/slip0.0"), (d_oos, "causal/burned_oos/slip0.0")):
        assert np.isclose(sharpe_d(d.to_numpy()) * ANN, causal[k]["sharpe_ann"], rtol=0, atol=1e-9), k
        assert np.isclose(d.sum(), causal[k]["total_pnl_usd"], rtol=0, atol=1e-6), k
    return d_is, d_oos, {"rows_dropped_cutoff": int(late.sum()), "n_trades_is": int(len(is_)),
                         "n_trades_oos": int(len(oo))}


def load_lowloss() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    g = pd.read_csv(ROOT / "research/v2/lowloss/out/daily.csv", parse_dates=["date"]).set_index("date")
    assert g.index.max() <= CUTOFF
    var = pd.read_csv(ROOT / "research/v2/lowloss/out/variants.csv").set_index("variant")
    assert list(var.index) == list(g.columns)
    g_is = g.reindex(IS_CAL)
    assert g_is.notna().all().all()
    for c in g.columns:   # every grid Sharpe must equal variants.csv
        assert np.isclose(sharpe_d(g_is[c].to_numpy()) * ANN, var.loc[c, "sharpe_ann"], rtol=0, atol=1e-9), c
    g_all = g.reindex(pd.date_range(g.index.min(), IS_CAL[-1], freq="D", tz="UTC"))
    books = pd.read_csv(ROOT / "results/lowloss/daily.csv", parse_dates=["date"])
    books["date"] = books.date.dt.tz_localize("UTC")
    assert books.date.max() <= CUTOFF
    return g_is, g_all, books


def book(books: pd.DataFrame, run: str, bk: str, pol: str) -> pd.Series:
    b = books[(books.run == run) & (books.book == bk) & (books.policy == pol)]
    s = b.set_index("date").pnl_usd.sort_index()
    assert s.index.is_unique and len(s) == (s.index.max() - s.index.min()).days + 1
    return s


def sizing_grid() -> tuple[dict[str, pd.DataFrame], dict]:
    """Rebuild IS daily P&L of the sizing lens policies with the lens's own engine (res & m30x, actual fee)."""
    import engine as E
    import walkforward as W
    ref = pd.read_csv(ROOT / "research/v2/sizing/out/policies.csv")
    F, Wh = E.load(), E.load_wallet_hist()
    assert pd.to_datetime(F.ts.max(), unit="s", utc=True) < CUTOFF
    out, worst, fam = {}, 0.0, {p.name: p.family for p in W.POLICIES}
    for measure, pols in (("res", W.POLICIES), ("m30x", [p for p in W.POLICIES if p.name in W.M30X_FOR])):
        cols = {}
        for pol in pols:
            sig = None
            if np.isfinite(pol.stop_k):
                sig = E.sigma_from_history(E.simulate(F, replace(pol, stop_k=np.inf), measure, "actual", Wh))
            tr = E.simulate(F, pol, measure, "actual", Wh, sig)
            ev = tr[tr.month >= E.EVAL_START]
            r = ref[(ref.policy == pol.name) & (ref.measure == measure) & (ref.fee_mode == "actual")].iloc[0]
            sr = sharpe_d(E.daily_series(ev).to_numpy()) * ANN          # engine.metrics convention
            worst = max(worst, abs(sr - r.sharpe_ann), abs(ev.pnl.sum() - r.total_pnl_usd) / 1e6)
            assert np.isclose(sr, r.sharpe_ann, rtol=0, atol=1e-9), (pol.name, measure, sr, r.sharpe_ann)
            cols[pol.name] = daily(ev, IS_CAL)
        out[measure] = pd.DataFrame(cols)
        log(f"sizing grid {measure}: {len(cols)} policies rebuilt, all match policies.csv")
    return out, {"families": fam, "max_abs_diff_vs_policies_csv": worst}


# ------------------------------------------------------------------------------------- main
def main():
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    causal = json.loads((ROOT / "results/v2/causal.json").read_text())
    llres = json.loads((ROOT / "results/lowloss/results.json").read_text())
    note = (ROOT / "docs/NOTE.md").read_text()
    assert "44 (H1–H6) plus 3,342" in note, "variant count in NOTE.md section 8 changed"
    assert json.loads((ROOT / "research/v2/lowloss/out/results.json").read_text())["frozen_v2_safe"] == V2_SAFE_COL

    log("v2 trades")
    v2_is, v2_oos, v2_meta = load_v2(causal)
    log("lowloss grid + books")
    g_is, g_all, books = load_lowloss()
    assert np.allclose(g_is[LL_BASE_COL].to_numpy(), v2_is.to_numpy(), atol=1e-6)
    safe_is = g_is[V2_SAFE_COL]
    assert np.allclose(book(books, "a", "u1_is", "v2_safe").reindex(IS_CAL).to_numpy(), safe_is.to_numpy(), atol=1e-6)
    safe_oos = book(books, "a", "u1_oos", "v2_safe").reindex(OOS_CAL)
    assert np.allclose(book(books, "a", "u1_oos", "v2").reindex(OOS_CAL).to_numpy(), v2_oos.to_numpy(), atol=1e-6)
    bk = llres["runs"]["a_burned_oos_nonblind"]["books"]
    bu = llres["runs"]["b_u2_blind"]["books"]
    series = {   # name -> (daily series, capital, label)
        "v2_is": (v2_is, causal["causal/is_eval/slip0.0"]["capital_usd"], "v2, IS (Feb 1 - Aug 25)"),
        "v2_oos": (v2_oos, causal["causal/burned_oos/slip0.0"]["capital_usd"], "v2, burned OOS (Aug 25 - Oct 3)"),
        "v2safe_is": (safe_is, bk["u1_is"]["v2_safe"]["capital_usd"], "v2-safe, IS"),
        "v2safe_oos": (safe_oos, bk["u1_oos"]["v2_safe"]["capital_usd"], "v2-safe, burned OOS"),
        "v2_u2oos_blind": (book(books, "b", "u2_oos", "v2"), bu["u2_oos"]["v2"]["capital_usd"],
                           "v2, U2-OOS blind (context)"),
        "v2safe_u2oos_blind": (book(books, "b", "u2_oos", "v2_safe"), bu["u2_oos"]["v2_safe"]["capital_usd"],
                               "v2-safe, U2-OOS blind (context)"),
    }
    for k, (s, _, _) in series.items():
        assert s.notna().all() and s.index.max() <= CUTOFF, k
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({k: s for k, (s, _, _) in series.items()}).to_csv(OUT_DIR / "daily_series.csv")

    log("sizing grid rebuild")
    sz, sz_meta = sizing_grid()
    sz["res"].to_csv(OUT_DIR / "sizing_daily_is_res_actual.csv")
    sz["m30x"].to_csv(OUT_DIR / "sizing_daily_is_m30x_actual.csv")

    # 1. Sharpe / moments ------------------------------------------------------------------
    mom = {}
    for k, (s, cap, lab) in series.items():
        m = moments(s.to_numpy())
        m.update(label=lab, capital_usd=float(cap), mean_daily_ret_pct=m["mean_daily_usd"] / cap * 100,
                 first_day=str(s.index.min().date()), last_day=str(s.index.max().date()))
        mom[k] = m
    log("moments done")

    # 2. PSR / DSR ---------------------------------------------------------------------------
    ll_sr = np.array([sharpe_d(g_is[c].to_numpy()) for c in g_is.columns])
    sz_sr = np.array([sharpe_d(sz["res"][c].to_numpy()) for c in sz["res"].columns])
    var_src = {"lowloss_grid_24": float(np.var(ll_sr, ddof=1)), "sizing_grid_55": float(np.var(sz_sr, ddof=1))}
    dsr = {"variance_sources": {
        "null_1_over_T_minus_1": "1/(T-1) of the series itself (zero skill; NOTE.md section 8 convention)",
        "lowloss_grid_24": {"var_daily_sr": var_src["lowloss_grid_24"],
                            "sd_sr_ann": float(np.sqrt(var_src["lowloss_grid_24"]) * ANN),
                            "sr_ann_range": [float(ll_sr.min() * ANN), float(ll_sr.max() * ANN)]},
        "sizing_grid_55": {"var_daily_sr": var_src["sizing_grid_55"],
                           "sd_sr_ann": float(np.sqrt(var_src["sizing_grid_55"]) * ANN),
                           "sr_ann_range": [float(sz_sr.min() * ANN), float(sz_sr.max() * ANN)]}},
        "N": {"H1_H6": N_H, "all_NOTE_s8": N_ALL, "all_plus_v2safe_grid": N_WITH_LOWLOSS}, "rows": []}
    for k in ("v2_is", "v2_oos", "v2safe_is", "v2safe_oos", "v2_u2oos_blind", "v2safe_u2oos_blind"):
        m = mom[k]
        row = {"series": k, "sharpe_ann": m["sharpe_ann"], "T": m["T_days"],
               "psr_vs_0": psr(m["sharpe_daily"], 0.0, m["T_days"], m["skew"], m["kurtosis"]), "dsr": {}}
        for nlab, n in (("N44", N_H), ("N3386", N_ALL), ("N3410", N_WITH_LOWLOSS)):
            for vlab, v in (("null", 1 / (m["T_days"] - 1)), *var_src.items()):
                s0 = expected_max_sr(v, n)
                row["dsr"][f"{nlab}/{vlab}"] = {
                    "sr0_ann": s0 * ANN, "dsr": psr(m["sharpe_daily"], s0, m["T_days"], m["skew"], m["kurtosis"])}
            row[f"dsr_min_{nlab}"] = min(v["dsr"] for kk, v in row["dsr"].items() if kk.startswith(nlab + "/"))
            row[f"sr0_ann_max_{nlab}"] = max(v["sr0_ann"] for kk, v in row["dsr"].items() if kk.startswith(nlab + "/"))
        dsr["rows"].append(row)
    log("PSR/DSR done")

    # 3. CSCV / PBO --------------------------------------------------------------------------
    clean = [c for c in sz["res"].columns if sz_meta["families"][c] != "B*"]
    pool62 = pd.concat([sz["res"], sz["m30x"].add_suffix("|m30x")], axis=1)
    grids = {
        "lowloss_24_sharpe": (g_is, "sharpe", None),
        "lowloss_24_selection_rule": (g_is, "share_feasible", list(g_is.columns).index(LL_BASE_COL)),
        "lowloss_24_sharpe_with_jan": (g_all, "sharpe", None),
        "sizing_55_res_actual_sharpe": (sz["res"], "sharpe", None),
        "sizing_52_clean_res_actual_sharpe": (sz["res"][clean], "sharpe", None),
        "sizing_62_res_plus_m30x_actual_sharpe": (pool62, "sharpe", None),
    }
    pbo = {}
    for k, (M, rule, base) in grids.items():
        pbo[k] = cscv(M.to_numpy(), list(M.columns), rule=rule, base_idx=base)
        pbo[k]["first_day"], pbo[k]["last_day"] = str(M.index.min().date()), str(M.index.max().date())
        log(f"CSCV {k}: PBO {pbo[k]['pbo']:.3f}, slope {pbo[k]['degradation']['slope']:.3f}")

    # 4. stationary bootstrap ----------------------------------------------------------------
    boot = {}
    for k, (s, cap, _) in series.items():
        boot[k] = bootstrap(s.to_numpy(), rng)
        boot[k]["mean_daily_ret_pct_ci95"] = [v / cap * 100 for v in boot[k]["mean_daily_usd_ci95"]]
    log("bootstrap done")

    # 5. MinTRL ------------------------------------------------------------------------------
    s0_null_ref = {}   # SR* for the "beat N=3,386 trials" variant, using the widest grid variance (IS-based)
    vmax = max(var_src.values())
    mtrl = {}
    for k in series:
        m = mom[k]
        sr_star = expected_max_sr(vmax, N_ALL)
        s0_null_ref[k] = sr_star * ANN
        mtrl[k] = {"sharpe_ann": m["sharpe_ann"], "T_days": m["T_days"],
                   "min_trl_days_vs_0": min_trl(m["sharpe_daily"], 0.0, m["skew"], m["kurtosis"]),
                   "min_trl_days_vs_sr0_N3386_gridvar": min_trl(m["sharpe_daily"], sr_star, m["skew"], m["kurtosis"]),
                   "sr0_ann_used": sr_star * ANN}
        mtrl[k]["track_long_enough_vs_0"] = bool(m["T_days"] >= mtrl[k]["min_trl_days_vs_0"])
    log("MinTRL done")

    # outputs --------------------------------------------------------------------------------
    strip = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}  # noqa: E731
    res = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/rigor_pack.py", "seed": SEED, "data_cutoff_utc": str(CUTOFF),
        "conventions": {"sharpe": "mean/sd(ddof=1) of calendar-day zero-filled daily P&L x sqrt(365)",
                        "kurtosis": "Pearson (normal = 3), bias-corrected", "skew": "bias-corrected",
                        "bootstrap": f"stationary (Politis-Romano), mean block {MEAN_BLOCK} d, {N_BOOT} draws, percentile CI",
                        "cscv": f"S = {S_BLOCKS} near-equal contiguous blocks, all C({S_BLOCKS},{S_BLOCKS // 2}) splits",
                        "is_calendar": [str(IS_CAL[0].date()), str(IS_CAL[-1].date())],
                        "oos_calendar": [str(OOS_CAL[0].date()), str(OOS_CAL[-1].date())]},
        "inputs": {"v2": v2_meta, "sizing_rebuild": {"max_abs_diff_vs_policies_csv": sz_meta["max_abs_diff_vs_policies_csv"],
                                                     "n_res": int(sz["res"].shape[1]), "n_m30x": int(sz["m30x"].shape[1])}},
        "sharpe_moments": mom, "psr_dsr": dsr, "pbo_cscv": {k: strip(v) for k, v in pbo.items()},
        "bootstrap": {k: strip(v) for k, v in boot.items()}, "min_trl": mtrl,
        "runtime_s": None,
    }
    res["runtime_s"] = round(time.time() - t0, 1)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(res, indent=2, default=float))
    figure(pbo, boot, mom)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(report(res))
    log(f"wrote {OUT_JSON.relative_to(ROOT)}, {OUT_PNG.relative_to(ROOT)}, {OUT_MD.relative_to(ROOT)} "
        f"in {res['runtime_s']} s")
    print(summary_text(res))


# ------------------------------------------------------------------------------------- figure
def figure(pbo: dict, boot: dict, mom: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    C1, C2, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                         "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
                         "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})
    fig, ax = plt.subplots(2, 2, figsize=(10.5, 7.2))
    for a, key, title in ((ax[0, 0], "lowloss_24_sharpe", "CSCV: v2-safe grid (24 variants)"),
                          (ax[0, 1], "sizing_55_res_actual_sharpe", "CSCV: sizing-lens grid (55 policies)")):
        p = pbo[key]
        lam = p["_logits"]
        bins = np.linspace(min(lam.min(), -1) - 0.1, max(lam.max(), 1) + 0.1, 41)
        a.hist(lam[lam > 0], bins=bins, color=C1, edgecolor="#fcfcfb", linewidth=0.8, label="IS-best ranks above OOS median")
        a.hist(lam[lam <= 0], bins=bins, color=C2, edgecolor="#fcfcfb", linewidth=0.8, label="IS-best ranks at/below OOS median")
        a.axvline(0, color=INK, lw=1)
        a.set_title(f"{title}\nPBO = {p['pbo']:.1%}, degradation slope {p['degradation']['slope']:+.2f}",
                    loc="left", fontsize=9.5, color=INK)
        a.set_xlabel("logit of the IS-best variant's OOS relative rank")
        a.set_ylabel(f"splits (of {p['n_splits']:,})")
        a.legend(frameon=False, fontsize=7.5, loc="upper left")
    for a, (k1, k2), title in ((ax[1, 0], ("v2_is", "v2safe_is"), "Bootstrap Sharpe, IS (206 days)"),
                               (ax[1, 1], ("v2_oos", "v2safe_oos"), "Bootstrap Sharpe, burned OOS (40 days)")):
        draws = [boot[k]["_sr_draws"] for k in (k1, k2)]
        allv = np.concatenate([d[np.isfinite(d)] for d in draws])
        bins = np.linspace(np.percentile(allv, 0.2), np.percentile(allv, 99.8), 60)
        for d, k, c, lab in ((draws[0], k1, C1, "v2"), (draws[1], k2, C2, "v2-safe")):
            lo, hi = boot[k]["sharpe_ann_ci95"]
            a.hist(d, bins=bins, histtype="step", color=c, lw=2,
                   label=f"{lab}: {mom[k]['sharpe_ann']:.1f} [{lo:.1f}, {hi:.1f}]")
            a.axvline(mom[k]["sharpe_ann"], color=c, lw=1, ls="--")
        a.axvline(0, color=INK, lw=1)
        a.set_title(f"{title}\nstationary bootstrap, mean block {MEAN_BLOCK} d, {N_BOOT:,} draws",
                    loc="left", fontsize=9.5, color=INK)
        a.set_xlabel("annualised Sharpe (daily, x sqrt(365))")
        a.set_ylabel("draws")
        a.legend(frameon=False, fontsize=7.5, loc="upper left", title="observed [95% CI]", title_fontsize=7.5)
    fig.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=150)
    plt.close(fig)


# ------------------------------------------------------------------------------------- report
def f1(x, n=1):
    return "inf" if x == float("inf") else f"{x:,.{n}f}"


def report(r: dict) -> str:
    M, D, P, B, T = r["sharpe_moments"], r["psr_dsr"], r["pbo_cscv"], r["bootstrap"], r["min_trl"]
    L = []
    w = L.append
    w("# Rigor pack: how much of v2's Sharpe survives overfitting checks")
    w("")
    w(f"Generated by `scripts/rigor_pack.py` ({r['generated_utc']}, {r['runtime_s']} s, seed {r['seed']}). "
      "Analysis of existing results only: no strategy rule was changed or re-tuned, and no data on matches "
      f"starting on or after {r['data_cutoff_utc']} was read. Raw numbers: `results/rigor/rigor.json`; "
      "figure: `results/rigor/rigor.png`.")
    w("")
    w("Every statistic uses calendar-day, zero-filled daily P&L. Sharpe = mean / sd (ddof 1) × √365. "
      "IS = 2026-02-01 to 08-25 (206 days); burned OOS = 2026-08-25 to 10-03 (40 days, non-blind, last day "
      "partial). Each daily series was checked against the number already in the repo before use "
      "(v2 vs `results/v2/causal.json`, the 24 grid variants vs `variants.csv`, v2-safe vs "
      "`results/lowloss/daily.csv`). The sizing-lens daily P&L was rebuilt with the lens's own `engine.simulate`, "
      f"and all {r['inputs']['sizing_rebuild']['n_res'] + r['inputs']['sizing_rebuild']['n_m30x']} rebuilt Sharpes equal "
      "`policies.csv` to 1e-9.")
    w("")
    # headline
    v2i, v2o = D["rows"][0], D["rows"][1]
    w("## Headline")
    w(f"- **v2 IS** Sharpe {M['v2_is']['sharpe_ann']:.1f}. The deflated Sharpe ratio (DSR) is "
      f"{v2i['dsr_min_N3386']:.3f} at N = 3,386 trials, under the most conservative variance. The bootstrap 95% CI is "
      f"[{B['v2_is']['sharpe_ann_ci95'][0]:.1f}, {B['v2_is']['sharpe_ann_ci95'][1]:.1f}].")
    w(f"- **v2 burned OOS** Sharpe {M['v2_oos']['sharpe_ann']:.1f}. PSR vs 0 is {v2o['psr_vs_0']:.3f}. DSR is "
      f"{v2o['dsr_min_N44']:.3f} at N = 44 and {v2o['dsr_min_N3386']:.3f} at N = 3,386 (worst case over variance "
      f"sources). The bootstrap 95% CI is [{B['v2_oos']['sharpe_ann_ci95'][0]:.1f}, "
      f"{B['v2_oos']['sharpe_ann_ci95'][1]:.1f}].")
    w(f"- **PBO (CSCV, S = 16)** is {P['lowloss_24_sharpe']['pbo']:.1%} on the 24-variant v2-safe grid when picking "
      f"by Sharpe, and {P['lowloss_24_selection_rule']['pbo']:.1%} under GRID.md's own profitable-day rule. It is "
      f"{P['sizing_55_res_actual_sharpe']['pbo']:.1%} on the 55-policy sizing grid.")
    w(f"- **MinTRL** to reject SR ≤ 0 at 95%: v2 needs {T['v2_is']['min_trl_days_vs_0']:.0f} days at its IS Sharpe and "
      f"{T['v2_oos']['min_trl_days_vs_0']:.0f} days at its OOS Sharpe. The OOS has {T['v2_oos']['T_days']} days.")
    w("")
    # 1
    w("## 1. Daily Sharpe, skew, kurtosis")
    w("| series | days (active) | Sharpe | mean $/day | mean % of capital/day | skew | kurtosis | lag-1 AC | capital |")
    w("|---|---|---|---|---|---|---|---|---|")
    for k, m in M.items():
        w(f"| {m['label']} | {m['T_days']} ({m['active_days']}) | {m['sharpe_ann']:.2f} | {m['mean_daily_usd']:,.1f} | "
          f"{m['mean_daily_ret_pct']:.3f} | {m['skew']:.2f} | {m['kurtosis']:.2f} | {m['ac1']:+.2f} | ${m['capital_usd']:,.0f} |")
    w("")
    w("Kurtosis is Pearson (normal = 3). Capital is 3 × peak locked: v2 comes from `results/v2/causal.json`, "
      "v2-safe from `results/lowloss/results.json`. Sharpe is the same in $ and in % of capital, because "
      "capital is a constant per book. The U2 rows are the blind out-of-universe books, shown for context.")
    w("")
    # 2
    w("## 2. PSR and DSR (Bailey & López de Prado 2014)")
    vs = D["variance_sources"]
    w("SR\\* is the expected maximum Sharpe of N zero-skill trials, √V · ((1−γ) Φ⁻¹(1−1/N) + γ Φ⁻¹(1−1/(N·e))). "
      "Three choices of V, the cross-trial variance of daily Sharpe:")
    w(f"- **null:** V = 1/(T−1) of the series being tested (the NOTE.md §8 convention; gives SR\\* = "
      f"{v2i['dsr']['N3386/null']['sr0_ann']:.1f} at T = 206, N = 3,386).")
    w(f"- **lowloss grid:** variance across the 24 v2-safe variants' IS Sharpes: sd {vs['lowloss_grid_24']['sd_sr_ann']:.2f} "
      f"annualised, range {vs['lowloss_grid_24']['sr_ann_range'][0]:.1f} to {vs['lowloss_grid_24']['sr_ann_range'][1]:.1f}.")
    w(f"- **sizing grid:** variance across the 55 sizing policies (res, actual fee): sd {vs['sizing_grid_55']['sd_sr_ann']:.2f} "
      f"annualised, range {vs['sizing_grid_55']['sr_ann_range'][0]:.1f} to {vs['sizing_grid_55']['sr_ann_range'][1]:.1f}.")
    w("")
    w("N = 44 is H1–H6. N = 3,386 is H1–H6 plus the six v2 lenses, per NOTE.md §8. N = 3,410 adds the 24 "
      "v2-safe grid variants, which were run after that count was taken.")
    w("")
    w("| series | Sharpe | T | PSR(0) | SR\\* null / lowloss / sizing, N=44 | DSR, N=44 | SR\\* null / lowloss / sizing, N=3,386 | DSR, N=3,386 | DSR min, N=3,410 |")
    w("|---|---|---|---|---|---|---|---|---|")
    for row in D["rows"]:
        d = row["dsr"]

        def trip(n):
            return " / ".join(f"{d[f'{n}/{v}']['sr0_ann']:.1f}" for v in ("null", "lowloss_grid_24", "sizing_grid_55"))

        def trip_d(n):
            return " / ".join(f"{d[f'{n}/{v}']['dsr']:.3f}" for v in ("null", "lowloss_grid_24", "sizing_grid_55"))
        w(f"| {M[row['series']]['label']} | {row['sharpe_ann']:.2f} | {row['T']} | {row['psr_vs_0']:.4f} | {trip('N44')} | "
          f"{trip_d('N44')} | {trip('N3386')} | {trip_d('N3386')} | {row['dsr_min_N3410']:.3f} |")
    w("")
    w("How to read the table:")
    w(f"- **The IS DSRs are high under every variance source.** A daily Sharpe of {M['v2_is']['sharpe_daily']:.2f} "
      f"over 206 days clears even the largest SR\\* ({v2i['sr0_ann_max_N3386']:.1f} annualised, from the sizing "
      "grid's variance).")
    w(f"- **The burned-OOS DSR depends on V.** With the null variance at T = 40, the expected best of 3,386 "
      f"zero-skill trials is {v2o['dsr']['N3386/null']['sr0_ann']:.1f} annualised, above v2's "
      f"{M['v2_oos']['sharpe_ann']:.1f}, so 40 days cannot rule out luck at that N. With the v2-safe grid's "
      f"variance, SR\\* is {v2o['dsr']['N3386/lowloss_grid_24']['sr0_ann']:.1f} and the DSR is "
      f"{v2o['dsr']['N3386/lowloss_grid_24']['dsr']:.2f}.")
    w("- **The sizing-grid variance is the most conservative source.** Its spread mostly reflects real "
      "design differences (G against A0), not luck, so it inflates SR\\*.")
    w("- **Applying N = 3,386 to the OOS is conservative.** v2 was frozen before the OOS was evaluated, so the "
      "selection was not made on these 40 days. But the OOS was later looked at (it is burned), so the "
      "conservative reading is kept alongside the N = 44 one.")
    w("")
    # 3
    w("## 3. PBO by CSCV (Bailey, Borwein, López de Prado & Zhu 2017)")
    w("Each grid's IS daily P&L matrix (T × N) is cut into S = 16 contiguous blocks of 12–13 days. Every one of "
      "the C(16, 8) = 12,870 half/half splits is used:")
    w("- The variant with the best IS-half performance is picked.")
    w("- λ = logit(ω), where ω is that variant's relative rank in the other half, rank / (N+1), with ties "
      "averaged.")
    w("- PBO = P(λ ≤ 0).")
    w("- The degradation line is a regression of the pick's OOS-half performance on its IS-half performance.")
    w("- The control slope is the same regression for one fixed variant (the most frequent pick), with no "
      "selection at all.")
    w("")
    w("| grid | rule | N (distinct) | days | PBO | λ mean / median / sd | λ p5 / p95 | mean OOS rank ω | degradation slope (R²) | control slope, fixed variant | IS → OOS mean of pick | P(pick OOS < 0) |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, p in P.items():
        g, dg = p["logit"], p["degradation"]
        unit = "" if dg["metric"] == "sharpe_ann" else " (share)"
        pl = "n/a" if dg["p_oos_below_0"] is None else f"{dg['p_oos_below_0']:.3f}"
        w(f"| `{k}` | {p['rule']} | {p['N_variants']} ({p['N_distinct_series']}) | {p['T_days']} | **{p['pbo']:.3f}** | "
          f"{g['mean']:.2f} / {g['median']:.2f} / {g['sd']:.2f} | {g['p05']:.2f} / {g['p95']:.2f} | "
          f"{p['oos_relative_rank_mean']:.2f} | {dg['slope']:+.3f} ({dg['r2']:.2f}) | {dg['control_slope']:+.3f} | "
          f"{dg['is_mean']:.2f} → {dg['oos_mean']:.2f}{unit} | {pl} |")
    w("")
    w("Grids:")
    w("- `lowloss_24_*`: the v2-safe grid of `research/v2/lowloss/GRID.md`, Feb–Aug.")
    w("  - `_selection_rule` replays GRID.md's own rule on each IS half: max profitable-day share subject "
      "to mean ≥ 0.5 × baseline. It is scored by OOS-half share.")
    w("  - `_with_jan` adds January, the selection-history month (237 days).")
    w("  - Variants with `stop_k = 1.5` often never trigger, so some columns are exact twins of their "
      "`sinf` partner. The distinct count is in brackets.")
    w("- `sizing_*`: the sizing lens's policies, rebuilt with its engine. These are onset-window features (the "
      "lens predates the D9 causal fix; `G_50pct_net100` has IS Sharpe 16.8 there against 14.5 causal).")
    w("  - `55` is every policy under hold-to-resolution and actual fees.")
    w("  - `52_clean` drops the three window-contaminated `B*` filters.")
    w("  - `62` adds the seven executable 30 s-exit (`m30x`) runs.")
    w("")
    ll, sz5 = P["lowloss_24_sharpe"], P["sizing_55_res_actual_sharpe"]
    w("How to read the table:")
    w(f"- **The degradation slopes are mostly the complement artifact.** They are strongly negative "
      f"({ll['degradation']['slope']:+.2f} and {sz5['degradation']['slope']:+.2f}), but the control slope for a "
      f"fixed variant is almost the same ({ll['degradation']['control_slope']:+.2f} and "
      f"{sz5['degradation']['control_slope']:+.2f}). The two halves split one fixed sample, so when a half gets the "
      "good days, the other half gets the rest. Selection decay shows up instead as the gap between the pick's "
      f"IS and OOS means: {ll['degradation']['is_mean']:.1f} → {ll['degradation']['oos_mean']:.1f} on the v2-safe "
      f"grid and {sz5['degradation']['is_mean']:.1f} → {sz5['degradation']['oos_mean']:.1f} on the sizing grid.")
    w(f"- **Sizing grid, PBO {sz5['pbo']:.0%}.** The G family (risk-parity sizing, wallet filter, 0.05–0.95 "
      "zone, per-match net cap) beats the rest of the menu by a margin that no 103-day half can reverse. The "
      "IS-best is a G policy in every split, and it lands in the OOS top ranks. This says the choice of G over "
      "A–F is not a fluke of the sample. It says nothing about the onset-to-causal gap.")
    w(f"- **v2-safe grid, PBO {ll['pbo']:.0%} on Sharpe.** The 24 variants are close (sd of IS Sharpe "
      f"{vs['lowloss_grid_24']['sd_sr_ann']:.1f}), so their ranking is noisy. Even so, the IS-best Sharpe variant ranks "
      f"above the OOS median {1 - ll['pbo']:.0%} of the time. GRID.md's own rule (most profitable days, subject to the feasibility "
      f"floor) has a PBO of {P['lowloss_24_selection_rule']['pbo']:.0%}, close to a coin flip. That matches "
      "`research/v2/lowloss/RESULTS.md`: the net cap reliably cuts the size of losses but does not reliably make "
      "losing days rarer.")
    w("")
    for k in ("lowloss_24_sharpe", "sizing_55_res_actual_sharpe"):
        w(f"IS-best picks, top 5, `{k}`: " + ", ".join(f"{n} ({c:,})" for n, c in P[k]["is_best_pick_freq_top5"].items()))
        w("")
    # 4
    w("## 4. Stationary block bootstrap (Politis & Romano), mean block 5 days, 10,000 draws")
    w("| series | Sharpe | Sharpe 95% CI | bootstrap SE | P(Sharpe ≤ 0) | mean $/day | mean $/day 95% CI | mean % cap/day 95% CI |")
    w("|---|---|---|---|---|---|---|---|")
    for k, b in B.items():
        m = M[k]
        w(f"| {m['label']} | {m['sharpe_ann']:.2f} | [{b['sharpe_ann_ci95'][0]:.2f}, {b['sharpe_ann_ci95'][1]:.2f}] | "
          f"{b['sharpe_ann_boot_se']:.2f} | {b['p_sharpe_le_0']:.4f} | {m['mean_daily_usd']:,.1f} | "
          f"[{b['mean_daily_usd_ci95'][0]:,.1f}, {b['mean_daily_usd_ci95'][1]:,.1f}] | "
          f"[{b['mean_daily_ret_pct_ci95'][0]:.3f}, {b['mean_daily_ret_pct_ci95'][1]:.3f}] |")
    w("")
    w("The percentile CI for Sharpe from a 40-day resample is wide and skewed. A short block bootstrap "
      "keeps some serial dependence, but it cannot add information that 40 days do not contain.")
    w("")
    # 5
    w("## 5. Minimum track record length (Bailey & López de Prado 2012)")
    w("MinTRL = 1 + (1 − γ₃·SR + (γ₄−1)/4·SR²) · (z₀.₉₅ / (SR − SR\\*))², with SR the observed daily Sharpe, γ₃ the skew "
      "and γ₄ the Pearson kurtosis.")
    w("")
    w("| series | Sharpe | days observed | MinTRL vs SR\\* = 0 (days) | long enough? | MinTRL vs SR\\* = expected max of 3,386 (grid V, days) |")
    w("|---|---|---|---|---|---|")
    for k, t in T.items():
        w(f"| {M[k]['label']} | {t['sharpe_ann']:.2f} | {t['T_days']} | {f1(t['min_trl_days_vs_0'])} | "
          f"{'yes' if t['track_long_enough_vs_0'] else 'no'} | {f1(t['min_trl_days_vs_sr0_N3386_gridvar'])} "
          f"(SR\\* {t['sr0_ann_used']:.1f}) |")
    w("")
    w("The last column uses SR\\* = E[max] over 3,386 trials, with V from the wider of the two IS grid variances. "
      "That is how long a track would have to run at the observed Sharpe to beat the best of 3,386 lucky trials.")
    w("")
    w("## Caveats")
    w("- **Daily P&L is not iid.** PSR, DSR and MinTRL assume iid daily returns. The lag-1 autocorrelations are "
      "in table 1, and the stationary bootstrap is the check that is robust to short-range dependence.")
    w("- **The burned OOS is non-blind.** Its 40 days were looked at before v2-safe was designed, and the last day "
      "(2026-10-03) is partial. The clean test is still the forward window.")
    w("- **The sizing grid is not the causal book.** It runs on onset-window features. Its PBO measures the "
      "lens's selection step, not the causal book.")
    w("- **CSCV halves are calendar blocks.** Each half spans different months and different fast-tier "
      "wallet sets. Some of what CSCV calls overfitting is regime change across months.")
    w("- **The DSR trial count is a count of configurations, not of independent trials.** Many of the 3,386 "
      "variants are near-duplicates, and most were scored on other metrics or other books. The effective number "
      "of independent trials is smaller, so N = 3,386 overstates the deflation.")
    return "\n".join(L) + "\n"


def summary_text(r: dict) -> str:
    M, D, P, B, T = r["sharpe_moments"], r["psr_dsr"], r["pbo_cscv"], r["bootstrap"], r["min_trl"]
    out = ["== Sharpe (daily x sqrt365), skew, Pearson kurtosis, AC1"]
    for k, m in M.items():
        out.append(f"{k:20s} T={m['T_days']:3d} SR={m['sharpe_ann']:6.2f} skew={m['skew']:+.2f} kurt={m['kurtosis']:.2f} ac1={m['ac1']:+.2f}")
    out.append("== PSR(0) / DSR (min over V sources) N=44, N=3386; SR* range")
    for row in D["rows"]:
        out.append(f"{row['series']:20s} PSR0={row['psr_vs_0']:.4f} DSR44={row['dsr_min_N44']:.3f} "
                   f"DSR3386={row['dsr_min_N3386']:.3f} | " + ", ".join(f"{k}: SR*={v['sr0_ann']:.1f} DSR={v['dsr']:.3f}"
                                                                        for k, v in row["dsr"].items() if not k.startswith("N3410")))
    out.append("== PBO (CSCV S=16)")
    for k, p in P.items():
        out.append(f"{k:40s} PBO={p['pbo']:.3f} logit mean={p['logit']['mean']:+.2f} med={p['logit']['median']:+.2f} "
                   f"sd={p['logit']['sd']:.2f} slope={p['degradation']['slope']:+.3f} R2={p['degradation']['r2']:.2f} "
                   f"IS->OOS {p['degradation']['is_mean']:.2f}->{p['degradation']['oos_mean']:.2f}")
    out.append("== Bootstrap 95% CI (Sharpe; mean $/day)")
    for k, b in B.items():
        out.append(f"{k:20s} SR [{b['sharpe_ann_ci95'][0]:.2f}, {b['sharpe_ann_ci95'][1]:.2f}] P(SR<=0)={b['p_sharpe_le_0']:.4f} "
                   f"mean [{b['mean_daily_usd_ci95'][0]:.1f}, {b['mean_daily_usd_ci95'][1]:.1f}]")
    out.append("== MinTRL (days) vs SR*=0 ; vs E[max] N=3386 grid V")
    for k, t in T.items():
        out.append(f"{k:20s} T={t['T_days']} minTRL0={t['min_trl_days_vs_0']:.1f} minTRL_sr0={t['min_trl_days_vs_sr0_N3386_gridvar']:.1f} "
                   f"(SR*={t['sr0_ann_used']:.2f})")
    return "\n".join(out)


if __name__ == "__main__":
    main()
