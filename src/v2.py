"""COURTSIDE v2: the frozen rule in HYPOTHESIS_V2.md, runnable on any period.

Pipeline (each month m only ever learns from months < m):
  prints (all periods) -> walk-forward fast-tier shadow (src.fasttier) -> decision-time features
  -> sizing policy G_50pct_net100 (research/v2/sizing/engine.py, used unchanged) -> trades.

The feature builder is the one in research/v2/sizing/features.py, made period-agnostic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src import fasttier

ROOT = Path(__file__).resolve().parents[1]
# The verified sizing engine, loaded by path under a private name: the top-level `engine/` package
# (the live paper-trading engine) would otherwise shadow it as `engine`.
_spec = importlib.util.spec_from_file_location("courtside_sizing_engine", ROOT / "research/v2/sizing/engine.py")
E = importlib.util.module_from_spec(_spec)
sys.modules["courtside_sizing_engine"] = E
_spec.loader.exec_module(E)

POLICY = E.Policy("G_50pct_net100", sizing="risk_parity", deploy_frac=0.5, zone="0.05-0.95",
                  wallet="filter", net_cap=100, family="G")


def build_features(sh: pd.DataFrame, prints: pd.DataFrame, ends: pd.Series) -> pd.DataFrame:
    """Decision-time features for shadow rows; only earlier-second prints are used (see features.py)."""
    sh = sh.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    pr = prints[prints.cond.isin(set(sh.cond))][["cond", "ts", "p", "dir", "usd", "wallet"]]
    pr = pr.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    feats = {k: np.full(len(sh), np.nan) for k in ("ref", "last", "bid0", "ask0", "n_prior3", "usd_prior3", "clip_k")}
    groups = {c: g for c, g in pr.groupby("cond", sort=False)}
    for c, g in sh.groupby("cond", sort=False):
        P = groups[c]
        ts, p, usd, d, wal = P.ts.to_numpy(), P.p.to_numpy(), P.usd.to_numpy(), P.dir.to_numpy(), P.wallet.to_numpy()
        pv = np.concatenate([[0.0], np.cumsum(p * usd)]); vv = np.concatenate([[0.0], np.cumsum(usd)])
        idx = np.arange(len(ts))
        ask_i = np.maximum.accumulate(np.where(d > 0, idx, -1))
        bid_i = np.maximum.accumulate(np.where(d < 0, idx, -1))
        st, rows = g.ts.to_numpy(), g.index.to_numpy()
        a = np.searchsorted(ts, st - 63, "left"); b = np.searchsorted(ts, st - 3, "left")
        w = vv[b] - vv[a]
        feats["ref"][rows] = np.where(w > 0, (pv[b] - pv[a]) / np.where(w > 0, w, 1), np.nan)
        e = np.searchsorted(ts, st, "left")
        l10 = np.searchsorted(ts, st - 10, "left")
        has = (e - 1 >= l10) & (e > 0)
        feats["last"][rows] = np.where(has, p[np.maximum(e - 1, 0)], np.nan)
        for side_i, key in ((ask_i, "ask0"), (bid_i, "bid0")):
            j = np.where(e > 0, side_i[np.maximum(e - 1, 0)], -1)
            ok = (j >= 0) & (st - ts[np.maximum(j, 0)] <= 30)
            feats[key][rows] = np.where(ok, p[np.maximum(j, 0)], np.nan)
        s3 = np.searchsorted(ts, st - 3, "left")
        feats["n_prior3"][rows] = e - s3
        feats["usd_prior3"][rows] = vv[e] - vv[s3]
        gw = g.wallet.to_numpy()
        feats["clip_k"][rows] = [np.count_nonzero(wal[s3[k]:e[k]] == gw[k]) if e[k] > s3[k] else 0 for k in range(len(st))]
    for k, v in feats.items():
        sh[k] = v
    sh["q"] = np.where(sh.dir > 0, sh.p, 1 - sh.p)
    sh["fee5"] = 0.05 * sh.q * (1 - sh.q)
    sh["pre_move"] = (sh["last"] - sh.ref) * sh.dir
    sh["fill_move"] = (sh.p - sh.ref) * sh.dir
    sh["spread0"] = sh.ask0 - sh.bid0
    sh["end_ts"] = sh.cond.map(ends).map(lambda x: x.timestamp() if pd.notna(x) else np.nan)
    sh["end_ts"] = np.maximum(sh.end_ts.fillna(sh.ts + 4 * 3600), sh.ts)
    sh["mo_res_all"] = sh.dir * (sh.res - sh.p)
    sh["date"] = pd.to_datetime(sh.ts, unit="s", utc=True).dt.floor("D")
    sh["month"] = sh.month.astype(str)
    sh["regime"] = sh.delay.astype(int).astype(str) + "s/" + (sh.fee_rate * 100).round().astype(int).astype(str) + "%"
    return sh.sort_values("ts", kind="stable").reset_index(drop=True)


def prepare(f: pd.DataFrame) -> pd.DataFrame:
    """Same column prep as engine.load(), on an in-memory feature table."""
    f = f[f.month >= "2025-12"].sort_values("ts", kind="stable").reset_index(drop=True)
    f["rate"] = f.fee_rate.astype(float)
    f["gross_res"] = f.mo_res_all
    f["gross30"] = f.mo30
    f["qb"] = np.clip(np.searchsorted(E.QB, f.q.to_numpy(), "right") - 1, 0, len(E.QB) - 2)
    f["lock_end"] = np.minimum(f.end_ts, f.ts + E.MAX_LOCK_S)
    f["their_shares"] = f.usd / f.q
    f["exit_q"] = np.clip(f.q + f.mo30.fillna(0), 0.001, 0.999)
    return f


LOCK_S = 4 * 3600  # ex-ante capital lock per position (a scheduled best-of-3 rarely runs longer)


def run(prints: pd.DataFrame, ends: pd.Series, measure: str = "res", causal: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """v2 trades over every month present in `prints` (walk-forward throughout).

    causal=True (the frozen rule after D9): the 0-3 s window is measured from jump DETECTION, so the
    opportunity set, wallet qualification and wallet filter use only information available at the time.
    causal=False reproduces the original onset-labelled v2 (kept for comparison)."""
    bucket = "bucket"
    if causal:
        from src.tiers import add_causal_bucket
        if "bucket_c" not in prints:
            prints = add_causal_bucket(prints)
        bucket = "bucket_c"
    wf, sh, _ = fasttier.walk_forward(prints, bucket=bucket)
    f = prepare(build_features(sh, prints, ends))
    if causal:  # ex-ante capital lock instead of the realised match end (affects capital/drawdown only)
        f["lock_end"] = f.ts + LOCK_S
    p03 = prints[prints[bucket] == "0-3s"][["wallet", "ts", "mo30"]].copy()
    p03["month"] = pd.to_datetime(p03.ts, unit="s").dt.to_period("M").astype(str)
    E._WCACHE.clear()
    tr = E.simulate(f, POLICY, measure, "actual", p03[["wallet", "month", "mo30"]])
    return tr, wf
