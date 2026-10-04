"""PSR, MinTRL, Harvey-Liu-Zhu haircut and block bootstrap for the books the paper reports, plus a COPIER fill
stress of v2 (analysis only; no rule, parameter or threshold is chosen here).

    .venv/bin/python scripts/psr_mintrl.py      # ~1-2 min, 1 process
      -> results/rigor/psr.json, results/rigor/psr_daily.csv; appends a line to results/rigor/psr_oos_reads.log

Series (calendar-day, zero-filled daily P&L, Sharpe = mean / sd(ddof 1) x sqrt(365), the rigor-pack convention)
  v2_is, v2_oos        the frozen v2 causal book at the fast tier's own fills (rebuilt exactly as
                       scripts/rigor_pack.py::load_v2; asserted equal to results/v2/causal.json and to
                       research/rigor/out/daily_series.csv)
  cv_pre_{is,oos}      CV trader, pre-registered reading (tier-0 latency sweep: video, own120, V = 1 s, reading
                       `tournament`, stamp lag 2.0 s), 20 seeds
  cv_cal_{is,oos}      CV trader, post hoc reading (`tournament_lagcal`, calibrated stamp lag 3.14 s), 20 seeds
                       Both CV cells are re-run with the sweep's own code (scripts/tier0_latency_sweep.py `cell`,
                       src/tier0.py `simulate`) and every seed's Sharpe and $ P&L are asserted equal to
                       results/tier0/latency_sweep_seeds.csv. The paper's CV Sharpe is the mean over seeds of the
                       per-seed Sharpe, so the CV statistics below are per seed (median, range, count passing).
  copier_*_{is,oos}    v2 re-priced as a COPIER that can only act after it sees the fast wallet's print.

Statistics
  PSR(SR*) Bailey & Lopez de Prado (2012), with sample skew and Pearson kurtosis, SR* in {0, 2 annualised}.
  MinTRL   days needed to reject SR <= SR* at 95% (same paper), SR* in {0, 2}.
  HLZ      Harvey & Liu (2015) / Harvey, Liu & Zhu (2016) haircut Sharpe: t = SR_daily x sqrt(T), two-sided
           p, Bonferroni (equal to Holm for the top-ranked test) and Sidak adjustment for N = 4,219 variants
           (results/paper/variants.json::total, the paper's var.total), then the adjusted p inverted to a Sharpe.
           BHY is not computed: it needs the other 4,218 p-values, and daily series exist for only a few dozen.
  Bootstrap stationary (Politis & Romano 1994), mean block 5 days, 10,000 draws: the block length of
           scripts/rigor_pack.py (MEAN_BLOCK). For v2 the rigor pack's seed and order are reused, so its
           published CIs are reproduced exactly (asserted). For CV, 500 draws per seed x 20 seeds are pooled, so
           the interval carries both day-sampling and simulation-seed noise.

Copier stress (the judges' point: v2 is measured at the fast tier's own fills, which a copier cannot get)
  Print timestamps in the tapes are block times (whole seconds; research/v2/maker/DEVIATIONS_LIVE.md L1).
  A copier learns the wallet's fill at block time ts, sends a taker order, waits the market's venue delay D
  (the trade's own `delay`: 3 s before May 2026, 1 s after) and is matched at real time ts + D. The tape runs
  L s behind real time (block lag: median 1.976 s, p90 2.974 s, n = 5,472 trades matched by tx hash;
  results/decay/decay.json::latency_inputs.block_lag_s), so the book the copier meets is the tape's state at
  tau = ts + D + L. Per-trade block lags were not saved, so the measured median and p90 are used.
  Price path: the print tape itself (src/tape.py, in-play window) and the repo's mid proxy (src/tiers.py
  `_mid_series`, mean of the latest bid-side and ask-side prints <= 30 s old), re-built here and asserted to
  reproduce the stored mo5 / mo15 / mo30 markouts of every v2 trade. Same trades, same share counts as v2; only
  the entry price c (outcome-0 scale) changes:  per share = dir x (res - c) - rate x c(1 - c).
  Variants
    central        L = median; c = price of the first SAME-SIDE print at/after tau (what a taker on the copier's
                   side actually paid then); if none within 30 s, mid at the first print at/after tau + proxy
                   half-spread (count reported)
    mid_next       L = median; c = mid at the first print at/after tau (the repo's markout convention) + dir x
                   proxy half-spread at that print, spread clipped to [1c, 10c]
    same_prev      L = median; c = the last same-side print at/before tau (the fast print itself if nobody else
                   took that side in between). Optimistic bound: the fast wallet just lifted that level, so a
                   copier can rarely do better than the latest same-side fill
    floor          L = 0 (the copier knows the wallet at match time: not feasible); same-side rule as central
    harsh          L = p90; same-side rule as central
    mid_prev_tick  L = median; mid carried forward from the last print at/before tau + 0.5c. Upper bound, biased
                   toward the copier: right after a jump the carried-forward mid averages the fresh fast print with
                   a stale opposite-side print, so it lags the move (see share_price_better_than_fast_fill)
  The copier's own price impact is ignored (generous). Diagnostic: the central per-share result on the trades whose
  same-side print lands within 2 s of tau (so the price is close to the copier's arrival time; a subset chosen with
  hindsight, not a tradeable book).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)                                   # src.polymarket reads tapes under the relative path data/raw
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from scripts import rigor_pack as R  # noqa: E402
from src.tape import in_play, load_tape, universe  # noqa: E402

OUT_JSON = ROOT / "results/rigor/psr.json"
OUT_CSV = ROOT / "results/rigor/psr_daily.csv"
PEEK_LOG = ROOT / "results/rigor/psr_oos_reads.log"

ANN = R.ANN
Z95 = R.Z95
SR_STARS_ANN = (0.0, 2.0)
N_BOOT, MEAN_BLOCK, SEED = R.N_BOOT, R.MEAN_BLOCK, R.SEED
CV_SEEDS, CV_BOOT_PER_SEED = 20, 500
CV_CELLS = {"cv_pre": ("tournament", "CV trader, pre-registered reading (stamp lag 2.0 s), V = 1 s"),
            "cv_cal": ("tournament_lagcal", "CV trader, post hoc calibrated reading (stamp lag 3.14 s), V = 1 s")}
PERIOD_TAG = {"IS": "is", "burned_OOS": "oos"}
COPIER = {
    "central": {"L": "median", "price": "same", "hs": "proxy",
                "what": "block lag median; first same-side print at/after tau (fallback: mid + proxy half-spread)"},
    "same_prev": {"L": "median", "price": "same_prev", "hs": "proxy",
                  "what": "block lag median; last same-side print at/before tau (optimistic bound)"},
    "mid_next": {"L": "median", "price": "next", "hs": "proxy",
                 "what": "block lag median; mid at first print at/after tau + proxy half-spread clipped [1c, 10c]/2"},
    "floor": {"L": "zero", "price": "same", "hs": "proxy",
              "what": "no block lag (wallet known at match time; infeasible); same-side rule"},
    "harsh": {"L": "p90", "price": "same", "hs": "proxy",
              "what": "block lag p90; same-side rule"},
    "mid_prev_tick": {"L": "median", "price": "prev", "hs": "tick",
                      "what": "block lag median; mid carried forward from last print at/before tau + 0.5c "
                              "(upper bound, biased toward the copier)"},
}
SAME_SIDE_MAX_S = 30.0


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


# ------------------------------------------------------------------------------------------------ statistics
def hlz(sr_d: float, T: int, n: int) -> dict:
    """Harvey-Liu haircut Sharpe from a daily Sharpe over T days, n tests (normal approximation, two-sided)."""
    t = sr_d * np.sqrt(T)
    p1 = float(2 * stats.norm.sf(abs(t)))
    p_bonf = min(1.0, n * p1)
    p_sidak = float(-np.expm1(n * np.log1p(-p1))) if p1 < 1 else 1.0
    out = {"N": n, "t_stat": float(t), "t_ge_3": bool(t >= 3.0), "p_single_two_sided": p1,
           "p_bonferroni": p_bonf, "p_sidak": p_sidak}
    for k, p in (("bonferroni", p_bonf), ("sidak", p_sidak)):
        if sr_d <= 0 or p >= 1:
            sr_hc = 0.0
        else:
            sr_hc = float(stats.norm.isf(p / 2) / np.sqrt(T)) * ANN
        out[f"sr_haircut_ann_{k}"] = sr_hc
        out[f"haircut_pct_{k}"] = float(1 - sr_hc / (sr_d * ANN)) * 100 if sr_d > 0 else None
    out["survives_bonferroni_5pct"] = bool(sr_d > 0 and p_bonf < 0.05)
    t_req = float(stats.norm.isf(0.05 / (2 * n)))         # |t| needed for Bonferroni p < 5% with n tests
    out["t_required_bonferroni_5pct"] = t_req
    out["sr_ann_required_at_this_T"] = t_req / np.sqrt(T) * ANN
    out["days_required_at_this_sr"] = float((t_req / sr_d) ** 2) if sr_d > 0 else float("inf")
    return out


def boot_sr(x: np.ndarray, B: int, rng: np.random.Generator) -> np.ndarray:
    xb = x[R.stationary_bootstrap_idx(len(x), B, MEAN_BLOCK, rng)]
    sd = xb.std(axis=1, ddof=1)
    return np.where(sd > 0, xb.mean(axis=1) / np.where(sd > 0, sd, 1), np.nan) * ANN


def boot_summary(sr: np.ndarray) -> dict:
    return {"sharpe_ann_ci95": [float(np.nanpercentile(sr, 2.5)), float(np.nanpercentile(sr, 97.5))],
            "sharpe_ann_boot_median": float(np.nanmedian(sr)), "p_sharpe_le_0": float(np.nanmean(sr <= 0)),
            "p_sharpe_le_2": float(np.nanmean(sr <= 2)), "n_draws": int(np.isfinite(sr).sum())}


def series_stats(x: np.ndarray, n_tests: int) -> dict:
    m = R.moments(x)
    sr, T, sk, ku = m["sharpe_daily"], m["T_days"], m["skew"], m["kurtosis"]
    out = {"T_days": T, "active_days": m["active_days"], "sharpe_ann": m["sharpe_ann"], "skew": sk,
           "kurtosis_pearson": ku, "ac1": m["ac1"], "mean_daily_usd": m["mean_daily_usd"],
           "total_usd": m["total_usd"]}
    for s in SR_STARS_ANN:
        k = f"{s:g}"
        out[f"psr_sr{k}"] = R.psr(sr, s / ANN, T, sk, ku)
        mt = R.min_trl(sr, s / ANN, sk, ku)
        out[f"mintrl_days_sr{k}"] = mt
        out[f"track_long_enough_sr{k}"] = bool(T >= mt)
    out["hlz"] = hlz(sr, T, n_tests)
    return out


# ------------------------------------------------------------------------------------------------ v2 + copier
def mid_path(ts: np.ndarray, p: np.ndarray, at_ask: np.ndarray, stale: float = 30.0):
    """Vectorised src/tiers.py::_mid_series (asserted equal on a sample)."""
    n = len(ts)
    idx = np.arange(n)
    la = np.maximum.accumulate(np.where(at_ask, idx, -1))
    lb = np.maximum.accumulate(np.where(~at_ask, idx, -1))
    ask = np.where((la >= 0) & (ts - ts[np.maximum(la, 0)] <= stale), p[np.maximum(la, 0)], np.nan)
    bid = np.where((lb >= 0) & (ts - ts[np.maximum(lb, 0)] <= stale), p[np.maximum(lb, 0)], np.nan)
    mid = np.where(np.isfinite(bid) & np.isfinite(ask) & (ask >= bid), (bid + ask) / 2, p)
    return mid, ask - bid


def copier_prices(trades: pd.DataFrame, u: pd.DataFrame, lags: dict) -> tuple[pd.DataFrame, dict]:
    """For each v2 trade and copier variant: copier entry price on outcome 0 and realised tape delay."""
    from src.tiers import _mid_series
    out = {f"c0_{v}": np.full(len(trades), np.nan) for v in COPIER}
    out.update({f"dt_{v}": np.full(len(trades), np.nan) for v in COPIER})
    out.update({f"hs_{v}": np.full(len(trades), np.nan) for v in COPIER})
    out.update({f"mid_{v}": np.full(len(trades), np.nan) for v in COPIER})
    out.update({f"same_{v}": np.zeros(len(trades), bool) for v in COPIER})
    out.update({f"gap_{v}": np.full(len(trades), np.nan) for v in COPIER})
    beyond = {v: 0 for v in COPIER}
    chk = {"markouts_checked": 0, "markout_mismatch": 0, "mid_series_checked_matches": 0, "missing_tape": 0}
    pos = pd.Series(np.arange(len(trades)), index=trades.index)
    for i, (cond, g) in enumerate(trades.groupby("cond", sort=False)):
        tp = load_tape(cond)
        if tp is None:
            chk["missing_tape"] += 1
            continue
        tp = in_play(tp, u.loc[cond]).reset_index(drop=True)
        ts, p, aa = tp.timestamp.to_numpy().astype(float), tp.p0.to_numpy(), tp.at_ask.to_numpy()
        mid, spr = mid_path(ts, p, aa)
        if i % 250 == 0:                                   # vectorised mid == the repo's loop, on a sample
            m2, s2 = _mid_series(ts, p, aa)
            assert np.allclose(mid, m2, equal_nan=True) and np.allclose(spr, s2, equal_nan=True), cond
            chk["mid_series_checked_matches"] += 1
        tt, d, p0 = g.ts.to_numpy(float), g.dir.to_numpy(float), g.p.to_numpy(float)
        n = len(ts)
        for h in (5, 15, 30):                              # the price path reproduces the stored markouts
            j = np.searchsorted(ts, tt + h, "left")
            mo = np.where(j < n, d * (mid[np.minimum(j, n - 1)] - p0), np.nan)
            ok = np.isclose(mo, g[f"mo{h}"].to_numpy(float), equal_nan=True, rtol=0, atol=1e-12)
            chk["markouts_checked"] += len(ok)
            chk["markout_mismatch"] += int((~ok).sum())
        rows = pos.loc[g.index].to_numpy()
        ask_i, bid_i = np.flatnonzero(aa), np.flatnonzero(~aa)
        for v, spec in COPIER.items():
            tau = tt + g.delay.to_numpy(float) + lags[spec["L"]]
            if spec["price"] in ("next", "same", "same_prev"):
                j = np.searchsorted(ts, tau, "left")
                beyond[v] += int((j >= n).sum())
                j = np.minimum(j, n - 1)                   # past the tape end: the last state of the book
            else:
                j = np.searchsorted(ts, tau, "right") - 1  # always >= the fast print itself
                assert (j >= 0).all()
            m = mid[j]
            if spec["hs"] == "proxy":
                s = spr[j]
                hs = np.where(np.isfinite(s) & (s > 0), np.clip(s, 0.01, 0.10), 0.01) / 2
            else:
                hs = np.full(len(j), 0.005)
            c0 = m + d * hs
            dtv = ts[j] - tt
            used_same = np.zeros(len(j), bool)
            gap = np.full(len(j), np.nan)
            if spec["price"] == "same_prev":                 # the fast print is same-side, so k >= 0 always
                for side_idx, sel in ((ask_i, d > 0), (bid_i, d < 0)):
                    if not sel.any():
                        continue
                    k = np.searchsorted(ts[side_idx], tau[sel], "right") - 1
                    assert (k >= 0).all()
                    kk = side_idx[k]
                    w = np.flatnonzero(sel)
                    c0[w] = p[kk]
                    dtv[w] = ts[kk] - tt[w]
                    used_same[w] = True
            if spec["price"] == "same":
                for side_idx, sel in ((ask_i, d > 0), (bid_i, d < 0)):
                    if not sel.any() or len(side_idx) == 0:
                        continue
                    k = np.searchsorted(ts[side_idx], tau[sel], "left")
                    okk = k < len(side_idx)
                    kk = side_idx[np.minimum(k, len(side_idx) - 1)]
                    okk &= (ts[kk] - tau[sel]) <= SAME_SIDE_MAX_S
                    w = np.flatnonzero(sel)[okk]
                    gap[w] = ts[kk[okk]] - tau[sel][okk]
                    c0[w] = p[kk[okk]]
                    dtv[w] = ts[kk[okk]] - tt[w]
                    used_same[w] = True
            out[f"c0_{v}"][rows] = np.clip(c0, 0.001, 0.999)
            out[f"dt_{v}"][rows] = dtv
            out[f"hs_{v}"][rows] = np.where(used_same, np.nan, hs)
            out[f"mid_{v}"][rows] = m
            out[f"same_{v}"][rows] = used_same
            out[f"gap_{v}"][rows] = gap
    chk["beyond_tape_end"] = beyond
    return pd.DataFrame(out, index=trades.index), chk


def copier_book(t: pd.DataFrame, v: str) -> pd.Series:
    c0 = t[f"c0_{v}"]
    ps = t.dir * (t.res - c0) - t.fee_rate * c0 * (1 - c0)
    return (t.shares * ps).where(t.pnl.notna())


def cluster_ps_ci(t: pd.DataFrame, col: str, rng: np.random.Generator, B: int = 2000) -> list[float]:
    g = t.assign(_x=t[col]).dropna(subset=["_x"]).groupby("cond").agg(p=("_x", "sum"), s=("shares", "sum"))
    P, S = g.p.to_numpy(), g.s.to_numpy()
    idx = rng.integers(0, len(g), (B, len(g)))
    ps = P[idx].sum(1) / S[idx].sum(1) * 100
    return [float(np.percentile(ps, 2.5)), float(np.percentile(ps, 97.5))]


def daily(df: pd.DataFrame, col: str, cal: pd.DatetimeIndex) -> pd.Series:
    d = df.groupby("date")[col].sum()
    assert d.index.isin(cal).all()
    return d.reindex(cal, fill_value=0.0)


# ------------------------------------------------------------------------------------------------ CV trader
def cv_daily() -> tuple[dict, dict]:
    from scripts import tier0_latency_sweep as LS
    from src import tier0 as T
    S = pd.read_csv(ROOT / "results/tier0/latency_sweep_seeds.csv")
    J = json.loads((ROOT / "results/tier0/latency_sweep.json").read_text())
    c = LS.ctx()
    out, chk = {}, {"seeds_checked": 0, "max_abs_sharpe_diff": 0.0, "max_abs_pnl_diff_usd": 0.0}
    for key, (reading, _) in CV_CELLS.items():
        sc, cvs = LS.cell("video", reading, 1.0, "own120", c)
        for per, tag in PERIOD_TAG.items():
            P = c["per"][per]
            Jt = P["J"]
            days = T.period_days(Jt, sc.regime)
            cols = {}
            for seed in range(CV_SEEDS):
                dr = T.draws(len(Jt), P["seed"] + seed, max(c["n_tour"], 1))
                calls = T.simulate(Jt, P["M"], sc, dr, c["pools"], cvs, c["mix"])
                tr = calls[calls.shares > 1e-9]
                d = tr.groupby("date").pnl.sum().reindex(days, fill_value=0.0)
                ref = S[(S.source == "video") & (S.reading == reading) & (S.x_s == 1.0) & (S.cv == "own120")
                        & (S.period == per) & (S.seed == seed)]
                assert len(ref) == 1
                sr = d.mean() / d.std() * ANN
                dsr, dp = abs(sr - ref.sharpe_ann.iloc[0]), abs(d.sum() - ref.pnl_usd.iloc[0])
                assert dsr < 1e-5 and dp < 1e-4, (key, per, seed, sr, ref.sharpe_ann.iloc[0])
                chk["seeds_checked"] += 1
                chk["max_abs_sharpe_diff"] = max(chk["max_abs_sharpe_diff"], float(dsr))
                chk["max_abs_pnl_diff_usd"] = max(chk["max_abs_pnl_diff_usd"], float(dp))
                cols[seed] = d
            df = pd.DataFrame(cols)
            pub = J["video_own120"][reading]["1"][per]["sharpe_ann"]
            assert abs(df.apply(lambda s: s.mean() / s.std() * ANN).mean() - pub) < 0.01, (key, per, pub)
            out[f"{key}_{tag}"] = df
            log(f"CV {key} {per}: {len(days)} days x {CV_SEEDS} seeds reproduced (published Sharpe {pub})")
    return out, chk


def cv_summary(df: pd.DataFrame, n_tests: int, rng: np.random.Generator) -> dict:
    per_seed = [series_stats(df[s].to_numpy(float), n_tests) for s in df.columns]
    q = lambda k: [r[k] for r in per_seed]  # noqa: E731
    med = lambda a: float(np.median(a))  # noqa: E731
    draws = np.concatenate([boot_sr(df[s].to_numpy(float), CV_BOOT_PER_SEED, rng) for s in df.columns])
    hc = [r["hlz"]["sr_haircut_ann_bonferroni"] for r in per_seed]
    res = {"T_days": int(len(df)), "n_seeds": int(df.shape[1]),
           "sharpe_ann_seed_mean": float(np.mean(q("sharpe_ann"))),
           "sharpe_ann_seed_median": med(q("sharpe_ann")),
           "sharpe_ann_seed_range": [float(min(q("sharpe_ann"))), float(max(q("sharpe_ann")))],
           "skew_seed_median": med(q("skew")), "kurtosis_seed_median": med(q("kurtosis_pearson"))}
    for s in SR_STARS_ANN:
        k = f"{s:g}"
        res[f"psr_sr{k}_seed_median"] = med(q(f"psr_sr{k}"))
        res[f"psr_sr{k}_seed_range"] = [float(min(q(f"psr_sr{k}"))), float(max(q(f"psr_sr{k}")))]
        res[f"psr_sr{k}_seeds_ge_0.95"] = int(sum(v >= 0.95 for v in q(f"psr_sr{k}")))
        mt = np.array(q(f"mintrl_days_sr{k}"), float)
        res[f"mintrl_days_sr{k}_seed_median"] = float(np.median(mt))
        res[f"mintrl_sr{k}_seeds_track_long_enough"] = int(sum(q(f"track_long_enough_sr{k}")))
    res["hlz"] = {"N": n_tests, "t_stat_seed_median": med([r["hlz"]["t_stat"] for r in per_seed]),
                  "t_required_bonferroni_5pct": per_seed[0]["hlz"]["t_required_bonferroni_5pct"],
                  "sr_ann_required_at_this_T": per_seed[0]["hlz"]["sr_ann_required_at_this_T"],
                  "sr_haircut_ann_bonferroni_seed_median": med(hc),
                  "seeds_surviving_bonferroni_5pct": int(sum(r["hlz"]["survives_bonferroni_5pct"] for r in per_seed))}
    res["bootstrap_pooled_over_seeds"] = boot_summary(draws)
    mean_series = df.mean(axis=1).to_numpy(float)
    res["seed_mean_series"] = {
        "label": "daily P&L averaged over the 20 seeds (expected P&L; averaging removes simulation noise, so its "
                 "Sharpe is above the per-seed mean; context only)",
        **{k: v for k, v in series_stats(mean_series, n_tests).items() if k != "hlz"}}
    res["per_seed"] = [{"seed": int(s), "sharpe_ann": r["sharpe_ann"], "psr_sr0": r["psr_sr0"],
                        "psr_sr2": r["psr_sr2"], "mintrl_days_sr0": r["mintrl_days_sr0"]}
                       for s, r in zip(df.columns, per_seed)]
    return res


# ------------------------------------------------------------------------------------------------ main
def _json_default(o):
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    return str(o)


def main():
    t0 = time.time()
    PEEK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PEEK_LOG.open("a") as fh:
        fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} rigor E run START (scripts/psr_mintrl.py, "
                 f"HEAD {git_head()}): reads v2 IS + burned-OOS trades and print tapes (copier stress, non-blind, "
                 "labelled) and re-runs published tier-0 sweep cells on IS + burned OOS; no rule or parameter "
                 "chosen\n")
    variants = json.loads((ROOT / "results/paper/variants.json").read_text())
    N_TESTS = int(variants["total"])
    assert N_TESTS == 4219, N_TESTS
    numbers = json.loads((ROOT / "results/paper/numbers.json").read_text())["numbers"]
    assert numbers["var.total"]["raw"] == N_TESTS
    blk = json.loads((ROOT / "results/decay/decay.json").read_text())["latency_inputs"]["block_lag_s"]
    lags = {"zero": 0.0, "median": float(blk["median"]), "p90": float(blk["p90"])}
    causal = json.loads((ROOT / "results/v2/causal.json").read_text())
    rig = json.loads((ROOT / "results/rigor/rigor.json").read_text())

    # ---- v2 daily series (rigor pack's own loader) --------------------------------------------------------
    log("v2 daily series")
    v2_is, v2_oos, v2_meta = R.load_v2(causal)
    ds = pd.read_csv(ROOT / "research/rigor/out/daily_series.csv", index_col=0, parse_dates=True)
    assert np.allclose(ds["v2_is"].dropna().to_numpy(), v2_is.to_numpy(), atol=1e-6)
    assert np.allclose(ds["v2_oos"].dropna().to_numpy(), v2_oos.to_numpy(), atol=1e-6)
    series = {"v2_is": v2_is, "v2_oos": v2_oos}

    # ---- copier stress --------------------------------------------------------------------------------------
    log("copier stress: loading tapes")
    t = pd.read_parquet(ROOT / "data/v2_trades_is_oos.parquet")
    u = universe()
    oos = set(u.loc[u.oos, "cond"])
    start = t.cond.map(u.set_index("cond").start)
    t = t[start < R.CUTOFF]
    t = t[((t.month >= R.EVAL_START) & ~t.cond.isin(oos)) | t.cond.isin(oos)].copy()
    t["period"] = np.where(t.cond.isin(oos), "oos", "is")
    assert (t.period == "is").sum() == v2_meta["n_trades_is"] and (t.period == "oos").sum() == v2_meta["n_trades_oos"]
    cp, cp_chk = copier_prices(t, u.set_index("cond"), lags)
    assert cp_chk["markout_mismatch"] == 0 and cp_chk["missing_tape"] == 0, cp_chk
    t = t.join(cp)
    log(f"copier prices done: {cp_chk['markouts_checked']:,} stored markouts reproduced")
    rng_c = np.random.default_rng(SEED + 11)
    copier = {"definition": {"tau": "ts (block time of the fast print) + D (trade's venue delay) + L (block lag)",
                             "block_lag_s": {**lags, "n": int(blk["n"]),
                                             "source": "results/decay/decay.json::latency_inputs.block_lag_s"},
                             "variants": {k: v["what"] for k, v in COPIER.items()},
                             "same_trades_same_shares_as_v2": True, "own_price_impact": "ignored (generous)"},
              "checks": cp_chk}
    for per, cal in (("is", R.IS_CAL), ("oos", R.OOS_CAL)):
        tp = t[t.period == per]
        base = tp.pnl.sum() / tp.shares[tp.pnl.notna()].sum() * 100
        assert abs(base - causal[f"causal/{'is_eval' if per == 'is' else 'burned_oos'}/slip0.0"]["per_share_c"]) < 1e-9
        rows = {"n_trades": int(len(tp)), "n_matches": int(tp.cond.nunique()), "v2_per_share_c": float(base),
                "v2_pnl_usd": float(tp.pnl.sum())}
        for v in COPIER:
            col = f"pnl_copier_{v}"
            tp = tp.assign(**{col: copier_book(tp, v)})
            ok = tp[col].notna()
            w = tp.shares[ok]
            adv = (tp.dir * (tp[f"c0_{v}"] - tp.p))[ok]          # copier price minus the fast fill, signed
            hsv = tp[f"hs_{v}"][ok]
            rows[v] = {
                "per_share_c": float(tp[col].sum() / w.sum() * 100),
                "per_share_ci95_c_match_clustered": cluster_ps_ci(tp, col, rng_c),
                "pnl_usd": float(tp[col].sum()),
                "entry_cost_vs_fast_fill_c_share_weighted": float((adv * w).sum() / w.sum() * 100),
                "share_price_better_than_fast_fill": float((adv < 0).mean()),
                "share_priced_from_same_side_print": float(tp[f"same_{v}"][ok].mean()),
                "half_spread_c_share_weighted_where_mid_used": (float((hsv * w).sum() / w[hsv.notna()].sum() * 100)
                                                                if hsv.notna().any() else None),
                "realised_tape_delay_s_median": float(np.median(tp[f"dt_{v}"][ok])),
                "realised_tape_delay_s_p90": float(np.percentile(tp[f"dt_{v}"][ok], 90)),
                "months_positive": f"{int((tp.groupby('month')[col].sum() > 0).sum())}/{tp.month.nunique()}",
            }
            if COPIER[v]["price"] == "same":
                near = ok & (tp[f"gap_{v}"] <= 2.0)
                rows[v]["diag_same_side_print_within_2s_of_tau"] = {
                    "share_of_trades": float(near.mean()),
                    "per_share_c": float(tp.loc[near, col].sum() / tp.shares[near].sum() * 100),
                    "per_share_ci95_c_match_clustered": cluster_ps_ci(tp[near], col, rng_c),
                    "v2_per_share_c_same_trades": float(tp.pnl[near].sum() / tp.shares[near].sum() * 100)}
            series[f"copier_{v}_{per}"] = daily(tp, col, cal)
        copier[per] = rows
        log(f"copier {per}: v2 {base:+.2f}c -> central {rows['central']['per_share_c']:+.2f}c, "
            f"floor {rows['floor']['per_share_c']:+.2f}c, mid_prev_tick {rows['mid_prev_tick']['per_share_c']:+.2f}c")

    # ---- statistics on the deterministic books -------------------------------------------------------------
    log("statistics")
    res_series = {}
    rng = np.random.default_rng(SEED)                    # rigor pack's seed and order: v2_is then v2_oos
    for k, s in series.items():
        x = s.to_numpy(float)
        st = series_stats(x, N_TESTS)
        if k in ("v2_is", "v2_oos"):
            sr = boot_sr(x, N_BOOT, rng)
            st["bootstrap"] = boot_summary(sr)
            for a, b in zip(st["bootstrap"]["sharpe_ann_ci95"], rig["bootstrap"][k]["sharpe_ann_ci95"]):
                assert abs(a - b) < 1e-9, (k, a, b)
            row = next(r for r in rig["psr_dsr"]["rows"] if r["series"] == k)
            assert abs(st["psr_sr0"] - row["psr_vs_0"]) < 1e-12
            assert abs(st["mintrl_days_sr0"] - rig["min_trl"][k]["min_trl_days_vs_0"]) < 1e-9
        else:
            st["bootstrap"] = boot_summary(boot_sr(x, N_BOOT, rng_c))
        res_series[k] = st
    assert abs(res_series["v2_is"]["sharpe_ann"] - numbers["v2.is.sr"]["raw"]) < 1e-9
    assert abs(res_series["v2_oos"]["sharpe_ann"] - numbers["v2.oos.sr"]["raw"]) < 1e-9

    # ---- CV trader ------------------------------------------------------------------------------------------
    log("CV trader cells")
    cv, cv_chk = cv_daily()
    rng_v = np.random.default_rng(SEED + 23)
    cv_res = {k: {"label": CV_CELLS[k.rsplit("_", 1)[0]][1] + (", IS" if k.endswith("_is") else ", burned OOS"),
                  **cv_summary(df, N_TESTS, rng_v)} for k, df in cv.items()}
    for k, num in (("cv_pre_is", "cv.pre.is.sr"), ("cv_pre_oos", "cv.pre.oos.sr"), ("cv_cal_is", "cv.cal.is.sr"),
                   ("cv_cal_oos", "cv.cal.oos.sr")):
        assert abs(cv_res[k]["sharpe_ann_seed_mean"] - numbers[num]["raw"]) < 0.01, (k, numbers[num])

    # ---- what survives --------------------------------------------------------------------------------------
    surv = []
    for k, st in res_series.items():
        surv.append({"series": k, "sharpe_ann": st["sharpe_ann"], "T_days": st["T_days"],
                     "psr_sr0": st["psr_sr0"], "psr_sr2": st["psr_sr2"],
                     "mintrl_days_sr0": st["mintrl_days_sr0"], "mintrl_days_sr2": st["mintrl_days_sr2"],
                     "hlz_sr_haircut_ann": st["hlz"]["sr_haircut_ann_bonferroni"],
                     "boot_ci95": st["bootstrap"]["sharpe_ann_ci95"],
                     "passes": {"psr0_ge_0.95": st["psr_sr0"] >= 0.95, "psr2_ge_0.95": st["psr_sr2"] >= 0.95,
                                "track_ge_mintrl0": st["track_long_enough_sr0"],
                                "track_ge_mintrl2": st["track_long_enough_sr2"],
                                "hlz_bonferroni_N4219": st["hlz"]["survives_bonferroni_5pct"],
                                "boot_ci_excludes_0": st["bootstrap"]["sharpe_ann_ci95"][0] > 0}})
    for k, st in cv_res.items():
        bci = st["bootstrap_pooled_over_seeds"]["sharpe_ann_ci95"]
        surv.append({"series": k, "sharpe_ann": st["sharpe_ann_seed_mean"], "T_days": st["T_days"],
                     "psr_sr0": st["psr_sr0_seed_median"], "psr_sr2": st["psr_sr2_seed_median"],
                     "mintrl_days_sr0": st["mintrl_days_sr0_seed_median"],
                     "mintrl_days_sr2": st["mintrl_days_sr2_seed_median"],
                     "hlz_sr_haircut_ann": st["hlz"]["sr_haircut_ann_bonferroni_seed_median"],
                     "boot_ci95": bci, "note": "per-seed medians; Sharpe = seed mean (the paper's convention)",
                     "passes": {"psr0_ge_0.95": st["psr_sr0_seed_median"] >= 0.95,
                                "psr2_ge_0.95": st["psr_sr2_seed_median"] >= 0.95,
                                "track_ge_mintrl0": st["mintrl_sr0_seeds_track_long_enough"] > CV_SEEDS / 2,
                                "track_ge_mintrl2": st["mintrl_sr2_seeds_track_long_enough"] > CV_SEEDS / 2,
                                "hlz_bonferroni_N4219": st["hlz"]["seeds_surviving_bonferroni_5pct"] > CV_SEEDS / 2,
                                "boot_ci_excludes_0": bci[0] > 0}})
    for r in surv:
        r["n_pass_of_6"] = int(sum(r["passes"].values()))

    # ---- headline (what the paper quotes) ----------------------------------------------------------------------
    S_, C_ = res_series, copier
    head = {
        "N_tests": N_TESTS,
        "v2_oos_psr_sr0": S_["v2_oos"]["psr_sr0"], "v2_oos_psr_sr2": S_["v2_oos"]["psr_sr2"],
        "v2_oos_mintrl_days_sr0": S_["v2_oos"]["mintrl_days_sr0"],
        "v2_oos_mintrl_days_sr2": S_["v2_oos"]["mintrl_days_sr2"], "v2_oos_T_days": S_["v2_oos"]["T_days"],
        "v2_oos_hlz_t": S_["v2_oos"]["hlz"]["t_stat"], "v2_oos_hlz_p_single": S_["v2_oos"]["hlz"]["p_single_two_sided"],
        "v2_oos_hlz_sr_haircut_ann": S_["v2_oos"]["hlz"]["sr_haircut_ann_bonferroni"],
        "v2_oos_hlz_days_required": S_["v2_oos"]["hlz"]["days_required_at_this_sr"],
        "hlz_t_required": S_["v2_oos"]["hlz"]["t_required_bonferroni_5pct"],
        "v2_is_hlz_sr_haircut_ann": S_["v2_is"]["hlz"]["sr_haircut_ann_bonferroni"],
        "v2_is_hlz_haircut_pct": S_["v2_is"]["hlz"]["haircut_pct_bonferroni"],
        "v2_oos_boot_ci95": S_["v2_oos"]["bootstrap"]["sharpe_ann_ci95"],
        "copier_central_is_c": C_["is"]["central"]["per_share_c"],
        "copier_central_is_ci95_c": C_["is"]["central"]["per_share_ci95_c_match_clustered"],
        "copier_central_oos_c": C_["oos"]["central"]["per_share_c"],
        "copier_central_oos_ci95_c": C_["oos"]["central"]["per_share_ci95_c_match_clustered"],
        "copier_same_prev_is_c": C_["is"]["same_prev"]["per_share_c"],
        "copier_same_prev_oos_c": C_["oos"]["same_prev"]["per_share_c"],
        "copier_same_prev_oos_ci95_c": C_["oos"]["same_prev"]["per_share_ci95_c_match_clustered"],
        "copier_central_is_sr": S_["copier_central_is"]["sharpe_ann"],
        "copier_central_oos_sr": S_["copier_central_oos"]["sharpe_ann"],
        "copier_same_prev_oos_sr": S_["copier_same_prev_oos"]["sharpe_ann"],
        "copier_central_entry_cost_is_c": C_["is"]["central"]["entry_cost_vs_fast_fill_c_share_weighted"],
        "copier_central_entry_cost_oos_c": C_["oos"]["central"]["entry_cost_vs_fast_fill_c_share_weighted"],
        "cv_pre_is_psr_sr0_seed_median": cv_res["cv_pre_is"]["psr_sr0_seed_median"],
        "cv_pre_oos_psr_sr0_seed_median": cv_res["cv_pre_oos"]["psr_sr0_seed_median"],
        "cv_cal_oos_psr_sr0_seed_median": cv_res["cv_cal_oos"]["psr_sr0_seed_median"],
        "cv_cal_oos_boot_ci95": cv_res["cv_cal_oos"]["bootstrap_pooled_over_seeds"]["sharpe_ann_ci95"],
        "cv_cal_oos_hlz_seeds_surviving": cv_res["cv_cal_oos"]["hlz"]["seeds_surviving_bonferroni_5pct"],
        "oos_series_passing_all_6": [r["series"] for r in surv if r["series"].endswith("_oos") and r["n_pass_of_6"] == 6],
        "is_series_passing_all_6": [r["series"] for r in surv if r["series"].endswith("_is") and r["n_pass_of_6"] == 6],
    }

    # ---- outputs ----------------------------------------------------------------------------------------------
    long = [s.rename("pnl_usd").rename_axis("date").reset_index().assign(series=k, seed=-1)
            for k, s in series.items()]
    for k, df in cv.items():
        for s in df.columns:
            long.append(df[s].rename("pnl_usd").rename_axis("date").reset_index().assign(series=k, seed=int(s)))
    pd.concat(long)[["series", "seed", "date", "pnl_usd"]].to_csv(OUT_CSV, index=False)
    res = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/psr_mintrl.py", "git_head": git_head(),
        "label": "analysis of existing books; burned OOS is non-blind; CV trader = counterfactual (assumed feed "
                 "latency, licensed feed not purchased; parameters measured); copier = labelled stress, no rule "
                 "or parameter chosen",
        "conventions": {"sharpe": "mean/sd(ddof=1) of calendar-day zero-filled daily P&L x sqrt(365)",
                        "psr": "Bailey & Lopez de Prado (2012), skew + Pearson kurtosis, sqrt(T-1)",
                        "sr_star_ann": list(SR_STARS_ANN), "mintrl": "95% one-sided, days",
                        "hlz": "Harvey & Liu (2015): t = SR_daily sqrt(T), two-sided normal p, Bonferroni (= Holm "
                               "for the top test) and Sidak; BHY not computed (needs all 4,219 p-values)",
                        "N_tests": N_TESTS, "N_tests_source": "results/paper/variants.json::total (= numbers.json var.total)",
                        "bootstrap": f"stationary, mean block {MEAN_BLOCK} d (scripts/rigor_pack.py MEAN_BLOCK), "
                                     f"{N_BOOT} draws; CV: {CV_BOOT_PER_SEED} per seed x {CV_SEEDS} seeds pooled"},
        "headline": head, "series": res_series, "cv": cv_res, "copier": copier, "survives": surv,
        "checks": {"v2_daily_equals_rigor_daily_series_csv": True, "v2_bootstrap_ci_equals_rigor_json": True,
                   "v2_psr0_and_mintrl0_equal_rigor_json": True, "cv": cv_chk,
                   "copier_markouts_reproduced": cp_chk["markouts_checked"]},
        "oos_reads": {"note": "burned-OOS reads by this script; results/rigor/psr_oos_reads.log is git-ignored (*.log) "
                              "and this agent may not edit results/oos_peeks.log, so the integrator appends the first "
                              "line below to results/oos_peeks.log",
                      "lines": PEEK_LOG.read_text().splitlines()},
        "runtime_s": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(res, indent=2, default=_json_default))
    log(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_CSV.relative_to(ROOT)} in {res['runtime_s']} s")
    print(f"{'series':22s} {'SR':>6s} {'T':>4s} {'PSR0':>6s} {'PSR2':>6s} {'MinTRL0':>8s} {'MinTRL2':>8s} "
          f"{'HLZ SR':>7s} {'boot CI':>16s} pass")
    for r in surv:
        print(f"{r['series']:22s} {r['sharpe_ann']:6.2f} {r['T_days']:4d} {r['psr_sr0']:6.3f} {r['psr_sr2']:6.3f} "
              f"{r['mintrl_days_sr0']:8.1f} {r['mintrl_days_sr2']:8.1f} {r['hlz_sr_haircut_ann']:7.2f} "
              f"[{r['boot_ci95'][0]:6.2f},{r['boot_ci95'][1]:6.2f}] {r['n_pass_of_6']}/6")


if __name__ == "__main__":
    main()
