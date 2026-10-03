"""Portfolio accounting and statistics for a list of trades."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from types import SimpleNamespace

import numpy as np
import pandas as pd

CAPITAL = 50_000


def run(fn, rows: pd.DataFrame, workers: int = 8, **kw) -> pd.DataFrame:
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(_call, [(fn, r, kw) for r in rows.to_dict("records")], chunksize=32))
    tr = pd.DataFrame([x for part in parts for x in part])
    if len(tr):
        tr["usd_in"] = tr.shares * tr.px_in
        tr["pnl"] = tr.shares * tr.pnl_ps
        tr["date"] = pd.to_datetime(tr.ts, unit="s", utc=True).dt.floor("D")
    return tr


def _call(args):
    fn, r, kw = args
    r = SimpleNamespace(**r)
    try:
        return fn(r, **kw)
    except Exception as e:  # one bad tape must not kill the run; it is counted below
        return [{"cond": r.cond, "error": repr(e)}]


def stats(tr: pd.DataFrame, n_boot: int = 2000, seed: int = 0, capital: float = CAPITAL) -> dict:
    if "error" in tr:
        errs = int(tr.error.notna().sum())
        tr = tr[tr.error.isna()]
    else:
        errs = 0
    if tr.empty:
        return {"n_trades": 0, "errors": errs}
    daily = tr.groupby("date").pnl.sum()
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC")
    daily = daily.reindex(idx, fill_value=0.0)
    ret = daily / capital
    eq = capital + daily.cumsum()
    dd = (eq / eq.cummax() - 1).min()
    years = max(len(idx) / 365.0, 1e-9)
    # cluster bootstrap over matches for mean P&L per share
    g = tr.groupby("cond").agg(s=("pnl_ps", "sum"), n=("pnl_ps", "size"))
    rng = np.random.default_rng(seed)
    k = len(g)
    bs = []
    for _ in range(n_boot):
        pick = rng.integers(0, k, k)
        bs.append(g.s.to_numpy()[pick].sum() / g.n.to_numpy()[pick].sum())
    lo, hi = np.percentile(bs, [2.5, 97.5])
    monthly = tr.groupby(tr.date.dt.tz_localize(None).dt.to_period("M")).pnl.sum()
    return {
        "n_trades": int(len(tr)), "n_matches": int(k), "errors": errs,
        "mean_pnl_per_share_c": float(tr.pnl_ps.mean() * 100),
        "ci95_pnl_per_share_c": [float(lo * 100), float(hi * 100)],
        "hit_rate": float((tr.pnl_ps > 0).mean()),
        "mean_fee_c": float(tr.fee.mean() * 100),
        "total_pnl_usd": float(tr.pnl.sum()),
        "sharpe_ann": float(ret.mean() / ret.std() * np.sqrt(365)) if ret.std() > 0 else float("nan"),
        "max_dd": float(dd), "turnover_x_per_yr": float(tr.usd_in.sum() * (2 if (tr.get("exit") == "tape").any() else 1) / capital / years),
        "capital": float(capital),
        "skew_daily": float(ret.skew()), "worst_day_pct": float(ret.min() * 100),
        "worst_month_usd": float(monthly.min()), "best_month_share": float(monthly.max() / max(monthly.sum(), 1e-9)),
        "days": int(len(idx)),
    }
