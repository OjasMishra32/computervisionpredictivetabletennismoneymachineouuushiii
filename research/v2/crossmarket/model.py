"""Sensitivity of each side market to its own moneyline, fitted walk-forward (months < m only).

Player markets (first-set winner, set winner, set handicap, game handicap): the side outcome
that names moneyline player 0 moves with the moneyline in log-odds,
    d logit(q') = b * d logit(p),           q' = q0 if align0 = +1 else 1 - q0.
Totals markets (match games O/U, sets O/U, first-set games O/U, set games O/U): "Over" gains
when the match gets closer, so it is driven by closeness c(p) = 4 p (1 - p):
    d logit(q_over) = b * d c(p).
b is OLS through the origin on consecutive in-play side prints <= 300 s apart (mid proxies),
pooled within a market type, using only months before the month it is applied to.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PLAYER = ("tennis_first_set_winner", "tennis_set_winner", "tennis_set_handicap", "tennis_game_handicap")
TOTALS = ("tennis_match_totals", "tennis_set_totals", "tennis_first_set_totals", "tennis_set_games_totals")
LO, HI = 0.03, 0.97
MIN_FIT_N = 200


def logit(x):
    x = np.clip(x, 0.005, 0.995)
    return np.log(x / (1 - x))


def expit(z):
    return 1 / (1 + np.exp(-z))


def close(p):
    return 4 * p * (1 - p)


def xy(iv: pd.DataFrame):
    """Regressor and response for the fits; NaN where an interval is unusable."""
    pl = iv.smt.isin(PLAYER).to_numpy()
    s = np.where(iv.align0.to_numpy() == -1, -1.0, 1.0)
    m1 = np.where(pl & (s < 0), 1 - iv.m1, iv.m1)
    m2 = np.where(pl & (s < 0), 1 - iv.m2, iv.m2)
    p1, p2 = iv.p1.to_numpy(), iv.p2.to_numpy()
    x = np.where(pl, logit(p2) - logit(p1), close(p2) - close(p1))
    y = logit(m2) - logit(m1)
    ok = ((m1 > LO) & (m1 < HI) & (m2 > LO) & (m2 < HI) & (p1 > LO) & (p1 < HI) & (p2 > LO) & (p2 < HI)
          & np.isfinite(x) & np.isfinite(y))
    ok &= ~(pl & (iv.align0.to_numpy() == 0))
    return np.where(ok, x, np.nan), np.where(ok, y, np.nan)


def fit_b(iv: pd.DataFrame) -> dict:
    x, y = xy(iv)
    out = {}
    for smt, idx in iv.groupby("smt").indices.items():
        xs, ys = x[idx], y[idx]
        ok = np.isfinite(xs) & np.isfinite(ys)
        if ok.sum() < MIN_FIT_N or (xs[ok] ** 2).sum() <= 0:
            continue
        out[smt] = float((xs[ok] * ys[ok]).sum() / (xs[ok] ** 2).sum())
    return out


def walk_forward_b(iv: pd.DataFrame, months: list[str]) -> pd.DataFrame:
    """b per (month, type) fitted on intervals of earlier months only."""
    rows = []
    for m in months:
        for smt, b in fit_b(iv[iv.month < m]).items():
            rows.append({"month": m, "smt": smt, "b": b})
    return pd.DataFrame(rows)


def implied_q0(q_ref, p_ref, p_new, smt, align0, b):
    """Side outcome-0 price implied by moving the moneyline from p_ref to p_new."""
    q_ref = np.asarray(q_ref, float)
    pl = np.isin(smt, PLAYER)
    s = np.where(np.asarray(align0) == -1, -1.0, 1.0)
    qa = np.where(pl & (s < 0), 1 - q_ref, q_ref)
    dx = np.where(pl, logit(p_new) - logit(p_ref), close(p_new) - close(p_ref))
    qa_new = expit(logit(qa) + b * dx)
    return np.where(pl & (s < 0), 1 - qa_new, qa_new)


# ------------------------------------------------------------------ local (in-match) sensitivity
LAMBDA_GRID = (0.05, 0.25, 1.0)


def local_sums(iv: pd.DataFrame) -> pd.DataFrame:
    """Per side market, cumulative sum(x*y) and sum(x^2) over its in-match intervals up to and
    including each interval end (ts). Merged as-of onto a reference print time, they give the
    sensitivity learned from this match only, strictly from data at or before the reference."""
    x, y = xy(iv)
    ok = np.isfinite(x) & np.isfinite(y)
    d = pd.DataFrame({"cond": iv.cond.to_numpy(), "ts": iv.ts.to_numpy(),
                      "sxy": np.where(ok, x * y, 0.0), "sxx": np.where(ok, x * x, 0.0)})
    d = d.sort_values(["cond", "ts"], kind="stable")
    d[["sxy", "sxx"]] = d.groupby("cond")[["sxy", "sxx"]].cumsum()
    return d.groupby(["cond", "ts"], as_index=False).last()


def attach_local(df: pd.DataFrame, sums: pd.DataFrame, ts_col: str, prefix: str) -> pd.DataFrame:
    """As-of join of cumulative sums at df[ts_col] (intervals ending at or before it)."""
    left = df[["cond", ts_col]].reset_index().rename(columns={ts_col: "ts"})
    left = left.dropna(subset=["ts"]).sort_values("ts", kind="stable")
    r = pd.merge_asof(left, sums.sort_values("ts", kind="stable"), on="ts", by="cond", direction="backward")
    r = r.set_index("index")
    df[prefix + "sxy"] = r.sxy.reindex(df.index).fillna(0.0)
    df[prefix + "sxx"] = r.sxx.reindex(df.index).fillna(0.0)
    return df


def shrunk_b(b_type, sxy, sxx, lam):
    return (np.asarray(sxy) + lam * np.asarray(b_type)) / (np.asarray(sxx) + lam)
