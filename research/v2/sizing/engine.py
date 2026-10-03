"""Walk-forward sizing engine for the fast-tier shadow book (IS only).

A policy maps each fast-tier print (the opportunity) to the number of token shares WE take.
For every evaluation month m, everything the policy estimates (edge by price bucket, wallet
quality, deployment normalisation, price-zone choice, stop thresholds) is fitted on rows with
month < m only, and the fitted rule is applied to month m. Concentration caps and the daily stop
are then applied sequentially in time order, using only trades already taken.

We never take more shares than the fast-tier print itself (that is the liquidity we know existed
at that price), and every trade is capped at usd_cap dollars.

Fees: estimates are made on GROSS markouts and turned into a net edge with the fee rate of the
match being traded (rate * q * (1-q) per share; the rate is published per market, so it is known
at decision time). fee_mode="5pct" re-prices every match at today's 5% schedule, to judge rules
over all months as if today's fee had applied (the gross edge is still the historical one,
earned under 3 s or 1 s order delays).

P&L measures (per share):
  res  : dir*(res-p) - fee            hold to resolution (50/50 resolutions included)
  m30  : mo30 - fee                   exit at the mid 30 s later (optimistic: assumes a maker exit
                                      at the mid with no extra fee)
  m30x : mo30 - fee - exit_fee - 0.5c exit 30 s later as a taker paying a second fee and a half
                                      spread of 0.5c (pessimistic)
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
FEAT = ROOT / "data/v2_sizing/features.parquet"
P03 = ROOT / "data/derived/prints_0_3s_is.parquet"
EVAL_START = "2026-02"   # first evaluation month (Dec 2025 + Jan 2026 are training only)
RUN_START = "2026-01"    # Jan is simulated only to give the daily-stop rule a sigma history
QB = np.array([0, .05, .1, .2, .3, .4, .5, .6, .7, .8, .9, .95, 1.0])
MAX_LOCK_S = 8 * 3600    # capital lock-up per position: until match end, at most 8 h
BASE_USD_CAP = 1_000
BASE_MATCH_CAP = 3_000
CAPITAL_BUFFER = 3


@dataclass(frozen=True)
class Policy:
    name: str
    sizing: str = "usd_mirror"     # usd_mirror | share_mirror | risk_parity | kelly
    edge_src: str = "mo30"         # kelly edge estimator: mo30 | mo_res
    var_src: str = "res"           # kelly variance: res (q(1-q)) | m30 (bucket var of mo30)
    wallet: str = "none"           # none | filter (skip wallets with predicted net <= 0) | kelly (wallet effect in edge)
    zone: str = "none"             # none | wf (walk-forward choice from ZONE_GRID) | "lo-hi" fixed, e.g. "0.05-0.95"
    usd_cap: float = BASE_USD_CAP  # per-trade dollar cap
    match_cap: float = BASE_MATCH_CAP   # per-match gross dollar cap (inf = none)
    net_cap: float = np.inf        # per-match |net outcome-0 shares| cap (risk-reducing trades always allowed)
    day_cap: float = np.inf        # per-UTC-day gross dollar cap
    wallet_day_cap: float = np.inf  # per (wallet, day) gross dollar cap
    stop_k: float = np.inf         # daily stop at -k * sigma(daily P&L), sigma from earlier months
    deploy_frac: float = 1.0       # scale so the training-period mean dollar ticket = deploy_frac x baseline's
                                   # (1.0 with usd_mirror = the baseline itself; <1 compares sizing SHAPES
                                   # at equal deployment, because no rule may exceed the baseline's
                                   # min(their print, usd_cap) on any single trade)
    filt: tuple = ()               # extra decision-time filters
    kelly_max_mult: float = 3.0    # kelly shares capped at this multiple of 2000 shares
    family: str = ""


ZONE_GRID = [(lo, hi) for lo in (0.0, 0.05, 0.1, 0.15) for hi in (1.0, 0.95, 0.9, 0.85)]
FILL_GRID = [0.03, 0.04, 0.05, 0.07, np.inf]


# ----------------------------------------------------------------------------------- data
def load() -> pd.DataFrame:
    f = pd.read_parquet(FEAT)
    f = f[f.month >= "2025-12"].sort_values("ts", kind="stable").reset_index(drop=True)
    f["rate"] = f.fee_rate.astype(float)
    f["gross_res"] = f.mo_res_all
    f["gross30"] = f.mo30
    f["qb"] = np.clip(np.searchsorted(QB, f.q.to_numpy(), "right") - 1, 0, len(QB) - 2)
    f["lock_end"] = np.minimum(f.end_ts, f.ts + MAX_LOCK_S)
    f["their_shares"] = f.usd / f.q
    f["exit_q"] = np.clip(f.q + f.mo30.fillna(0), 0.001, 0.999)
    return f


def load_wallet_hist() -> pd.DataFrame:
    w = pd.read_parquet(P03, columns=["wallet", "ts", "p", "dir", "mo30"])
    w["month"] = pd.to_datetime(w.ts, unit="s").dt.to_period("M").astype(str)
    return w[["wallet", "month", "mo30"]]


def fee_of(df: pd.DataFrame, fee_mode: str, rate_override: float | None = None):
    if rate_override is not None:
        rate = np.full(len(df), rate_override)
    elif fee_mode == "5pct":
        rate = np.full(len(df), 0.05)
    else:
        rate = df.rate.to_numpy()
    q = df.q.to_numpy()
    return rate * q * (1 - q), rate


def pnl_ps(df: pd.DataFrame, measure: str, fee_mode: str) -> np.ndarray:
    fee, rate = fee_of(df, fee_mode)
    if measure == "res":
        return df.gross_res.to_numpy() - fee
    if measure == "m30":
        return df.gross30.to_numpy() - fee
    if measure == "m30x":
        eq = df.exit_q.to_numpy()
        return df.gross30.to_numpy() - fee - rate * eq * (1 - eq) - 0.005
    raise ValueError(measure)


# ----------------------------------------------------------------------------- estimators
def shrunk_bucket_mean(train: pd.DataFrame, col: str, n0: float = 500.0) -> np.ndarray:
    d = train[["qb", col]].dropna()
    pool = d[col].mean() if len(d) else 0.0
    g = d.groupby("qb")[col].agg(["sum", "size"]).reindex(range(len(QB) - 1), fill_value=0)
    return ((g["sum"] + n0 * pool) / (g["size"] + n0)).to_numpy()


def bucket_var(train: pd.DataFrame, col: str, n0: float = 500.0) -> np.ndarray:
    d = train[["qb", col]].dropna()
    pool = d[col].var() if len(d) > 2 else 0.0025
    g = d.groupby("qb")[col].agg(["var", "size"]).reindex(range(len(QB) - 1))
    g["var"] = g["var"].fillna(pool); g["size"] = g["size"].fillna(0)
    return ((g["var"] * g["size"] + n0 * pool) / (g["size"] + n0)).to_numpy()


_WCACHE: dict = {}


def wallet_effect(whist: pd.DataFrame, m: str, n0: float = 200.0) -> tuple[dict, float]:
    """Shrunk gross 30 s markout per wallet on all of its 0-3 s prints before month m."""
    if m in _WCACHE:
        return _WCACHE[m]
    d = whist[whist.month < m]
    pool = float(d.mo30.mean())
    g = d.groupby("wallet").mo30.agg(["sum", "size"])
    eff = ((g["sum"] + n0 * pool) / (g["size"] + n0)) - pool
    _WCACHE[m] = (eff.to_dict(), pool)
    return _WCACHE[m]


# ------------------------------------------------------------------------------- targets
def raw_cap(df: pd.DataFrame, pol: Policy, train: pd.DataFrame, fee_mode: str, whist, m,
            rate_override=None) -> np.ndarray:
    """Unscaled per-trade share cap implied by the sizing rule (inf = no rule-specific cap)."""
    q = df.q.to_numpy()
    if pol.sizing == "usd_mirror":
        return np.minimum(df.usd.to_numpy(), BASE_USD_CAP) / q
    if pol.sizing == "share_mirror":
        return np.full(len(df), 2.0 * BASE_USD_CAP)            # 2000 shares = $1k at q = 0.5
    if pol.sizing == "risk_parity":
        return BASE_USD_CAP / np.sqrt(q * (1 - q))           # = 2000 shares at q = 0.5
    if pol.sizing == "kelly":
        e_g = shrunk_bucket_mean(train, "gross30" if pol.edge_src == "mo30" else "gross_res")[df.qb.to_numpy()]
        if pol.wallet == "kelly":
            eff, _ = wallet_effect(whist, m)
            e_g = e_g + df.wallet.map(eff).fillna(0.0).to_numpy()
        fee, _ = fee_of(df, fee_mode, rate_override)
        e_n = e_g - fee
        v = q * (1 - q) if pol.var_src == "res" else bucket_var(train, "gross30")[df.qb.to_numpy()]
        return np.maximum(e_n, 0) / v
    raise ValueError(pol.sizing)


def filter_mask(df: pd.DataFrame, pol: Policy, train: pd.DataFrame, fee_mode: str, whist, m, measure: str,
                rate_now: float) -> np.ndarray:
    """True = allowed to trade."""
    ok = np.ones(len(df), bool)
    q = df.q.to_numpy()
    if pol.zone == "wf":
        lo, hi = choose_zone(train, rate_now, measure)
        ok &= (q >= lo) & (q <= hi)
    elif pol.zone != "none":
        lo, hi = map(float, pol.zone.split("-"))
        ok &= (q >= lo) & (q <= hi)
    if pol.wallet == "filter":
        eff, pool = wallet_effect(whist, m)
        fee, _ = fee_of(df, fee_mode)
        ok &= (pool + df.wallet.map(eff).fillna(0.0).to_numpy() - fee) > 0
    if "first_only" in pol.filt:      # window-contaminated (see allbucket_check)
        ok &= (df.n_prior3.to_numpy() == 0) & (df.clip_k.to_numpy() == 0)
    if "no_fade" in pol.filt:         # window-contaminated
        ok &= np.nan_to_num(df.fill_move.to_numpy(), nan=0.0) > -0.02
    if "fill_wf" in pol.filt:         # window-contaminated
        x = choose_fill(train, rate_now, measure)
        fm = np.nan_to_num(df.fill_move.to_numpy(), nan=0.0)
        ok &= (fm > 0) & (fm <= x)
    if "min5" in pol.filt:
        ok &= df.usd.to_numpy() >= 5
    return ok


def _train_score(train: pd.DataFrame, mask: np.ndarray, rate: float, measure: str) -> float:
    """Daily Sharpe of a $100-ticket book on training rows re-priced at the current fee rate."""
    t = train[mask]
    if len(t) < 200:
        return -np.inf
    fee = rate * t.q * (1 - t.q)
    g = (t.gross_res if measure == "res" else t.gross30) - fee
    daily = ((100.0 / t.q) * g).groupby(t.date).sum()
    return float(daily.mean() / daily.std()) if daily.std() > 0 else -np.inf


def choose_zone(train, rate, measure):
    best, arg = -np.inf, (0.0, 1.0)
    q = train.q.to_numpy()
    for lo, hi in ZONE_GRID:
        s = _train_score(train, (q >= lo) & (q <= hi), rate, "res" if measure == "res" else "m30")
        if s > best:
            best, arg = s, (lo, hi)
    return arg


def choose_fill(train, rate, measure):
    fm = np.nan_to_num(train.fill_move.to_numpy(), nan=0.0)
    best, arg = -np.inf, np.inf
    for x in FILL_GRID:
        s = _train_score(train, (fm > 0) & (fm <= x), rate, "res" if measure == "res" else "m30")
        if s > best:
            best, arg = s, x
    return arg


def shares_from(raw, k, df, pol):
    q = df.q.to_numpy()
    sh = np.minimum(k * raw, df.their_shares.to_numpy())
    if pol.sizing == "kelly":
        sh = np.minimum(sh, pol.kelly_max_mult * 2.0 * BASE_USD_CAP)
    return np.minimum(sh, pol.usd_cap / q)


def month_targets(test, train, pol, fee_mode, whist, m, measure):
    rate_now = 0.05 if fee_mode == "5pct" else float(test.rate.max())
    raw = raw_cap(test, pol, train, fee_mode, whist, m)
    k = 1.0
    if not (pol.sizing == "usd_mirror" and pol.deploy_frac == 1.0):
        # deployment normalisation, fitted on TRAIN only and at the current fee rate
        tr_raw = raw_cap(train, pol, train, fee_mode, whist, m, rate_override=rate_now)
        target_usd = pol.deploy_frac * np.minimum(train.usd.to_numpy(), BASE_USD_CAP).mean()
        tq = train.q.to_numpy()
        lo, hi = 1e-8, 1e8
        for _ in range(90):
            mid = np.sqrt(lo * hi)
            if (shares_from(tr_raw, mid, train, pol) * tq).mean() < target_usd:
                lo = mid
            else:
                hi = mid
        k = np.sqrt(lo * hi)
    sh = shares_from(raw, k, test, pol)
    sh[~filter_mask(test, pol, train, fee_mode, whist, m, measure, rate_now)] = 0
    return sh


# --------------------------------------------------------------------------- sequential caps
def apply_caps(df: pd.DataFrame, tgt: np.ndarray, pol: Policy, pnl: np.ndarray, measure: str,
               sigma_by_month: dict | None) -> np.ndarray:
    n = len(df)
    q = df.q.to_numpy(); d = df.dir.to_numpy(); ts = df.ts.to_numpy()
    cond = df.cond.to_numpy(); wal = df.wallet.to_numpy()
    day = (ts // 86400).astype(np.int64); month = df.month.to_numpy()
    lock_end = df.lock_end.to_numpy()
    g30 = np.nan_to_num(df.gross30.to_numpy())
    fee_i = df.gross_res.to_numpy() - pnl if measure == "res" else None
    m_gross, m_net, d_gross, wd_gross = {}, {}, {}, {}
    out = np.zeros(n)
    use_stop = np.isfinite(pol.stop_k) and sigma_by_month is not None
    heap: list = []
    cur_day, day_mark, stopped = -1, 0.0, False
    for i in range(n):
        if day[i] != cur_day:
            cur_day, day_mark, stopped, heap = day[i], 0.0, False, []
        if use_stop:
            while heap and heap[0][0] <= ts[i]:
                day_mark += heapq.heappop(heap)[1]
            if not stopped and day_mark < -pol.stop_k * sigma_by_month.get(month[i], np.inf):
                stopped = True
            if stopped:
                continue
        t = tgt[i]
        if not (t > 0):
            continue
        c = cond[i]; k = (wal[i], day[i])
        room = min(pol.match_cap - m_gross.get(c, 0.0), pol.day_cap - d_gross.get(day[i], 0.0),
                   pol.wallet_day_cap - wd_gross.get(k, 0.0))
        if room <= 0:
            continue
        s = min(t, room / q[i])
        if np.isfinite(pol.net_cap):
            s = min(s, max(0.0, pol.net_cap - d[i] * m_net.get(c, 0.0)))
        if s <= 1e-9:
            continue
        out[i] = s
        u = s * q[i]
        m_gross[c] = m_gross.get(c, 0.0) + u
        m_net[c] = m_net.get(c, 0.0) + d[i] * s
        d_gross[day[i]] = d_gross.get(day[i], 0.0) + u
        wd_gross[k] = wd_gross.get(k, 0.0) + u
        if use_stop:   # mark-to-market: 30 s markout at ts+30, rest realised at match end
            if measure == "res":
                m30v = s * (g30[i] - fee_i[i])
                heapq.heappush(heap, (ts[i] + 30, m30v))
                heapq.heappush(heap, (lock_end[i], s * pnl[i] - m30v))
            else:
                heapq.heappush(heap, (ts[i] + 30, s * pnl[i]))
    return out


# --------------------------------------------------------------------------------- driver
def simulate(f: pd.DataFrame, pol: Policy, measure: str, fee_mode: str, whist, sigma_by_month=None) -> pd.DataFrame:
    months = sorted(m for m in f.month.unique() if m >= RUN_START)
    parts = [month_targets(f[f.month == m], f[f.month < m], pol, fee_mode, whist, m, measure) for m in months]
    run = f[f.month >= RUN_START].reset_index(drop=True)
    tgt = np.concatenate(parts)
    pnl = np.nan_to_num(pnl_ps(run, measure, fee_mode))
    shares = apply_caps(run, tgt, pol, pnl, measure, sigma_by_month)
    tr = run.assign(shares=shares, pnl_ps=pnl, target=tgt)
    tr = tr[tr.shares > 0].copy()
    tr["usd_in"] = tr.shares * tr.q
    tr["pnl"] = tr.shares * tr.pnl_ps
    return tr


def sigma_from_history(tr_nostop: pd.DataFrame) -> dict:
    """Walk-forward sigma of daily P&L: for month m, std over all days of earlier months."""
    daily = tr_nostop.groupby("date").pnl.sum()
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC")
    daily = daily.reindex(idx, fill_value=0.0)
    mon = np.asarray(daily.index.tz_localize(None).to_period("M").astype(str))
    out = {}
    for m in sorted(set(mon)):
        prev = daily[mon < m]
        out[m] = float(prev.std()) if len(prev) >= 10 else np.inf
    nxt = pd.Period(max(mon), "M") + 1
    out[str(nxt)] = float(daily.std())
    return out


def peak_locked(tr: pd.DataFrame) -> float:
    if tr.empty:
        return 0.0
    ev = pd.concat([pd.DataFrame({"t": tr.ts, "d": tr.usd_in}), pd.DataFrame({"t": tr.lock_end, "d": -tr.usd_in})])
    return float(ev.sort_values("t", kind="stable").d.cumsum().max())


def daily_series(tr: pd.DataFrame) -> pd.Series:
    daily = tr.groupby("date").pnl.sum()
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC")
    return daily.reindex(idx, fill_value=0.0)


def metrics(tr: pd.DataFrame, n_boot: int = 1000, seed: int = 0, capital: float | None = None) -> dict:
    tr = tr[tr.month >= EVAL_START]
    if tr.empty:
        return {"n_trades": 0}
    daily = daily_series(tr)
    peak = peak_locked(tr)
    cap = capital if capital else CAPITAL_BUFFER * peak
    eq = daily.cumsum()
    dd_usd = float((eq - eq.cummax()).min())
    g = tr.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"), e=("pnl_ps", "sum"), n=("pnl_ps", "size"))
    rng = np.random.default_rng(seed)
    k = len(g)
    P, S, E, N = (g[c].to_numpy() for c in ("p", "s", "e", "n"))
    bs_sw, bs_pp, bs_tot = [], [], []
    for _ in range(n_boot):
        i = rng.integers(0, k, k)
        bs_sw.append(P[i].sum() / S[i].sum()); bs_pp.append(E[i].sum() / N[i].sum()); bs_tot.append(P[i].sum())
    monthly = tr.groupby("month").pnl.sum()
    sd = daily.std()
    return {
        "n_trades": int(len(tr)), "n_matches": int(k),
        "per_share_c": float(tr.pnl.sum() / tr.shares.sum() * 100),
        "per_share_ci_c": [float(np.percentile(bs_sw, 2.5) * 100), float(np.percentile(bs_sw, 97.5) * 100)],
        "per_print_c": float(tr.pnl_ps.mean() * 100),
        "per_print_ci_c": [float(np.percentile(bs_pp, 2.5) * 100), float(np.percentile(bs_pp, 97.5) * 100)],
        "per_usd_c": float(tr.pnl.sum() / tr.usd_in.sum() * 100),
        "total_pnl_usd": float(tr.pnl.sum()),
        "total_pnl_ci_usd": [float(np.percentile(bs_tot, 2.5)), float(np.percentile(bs_tot, 97.5))],
        "usd_traded": float(tr.usd_in.sum()),
        "sharpe_ann": float(daily.mean() / sd * np.sqrt(365)) if sd > 0 else float("nan"),
        "peak_locked_usd": peak, "capital_usd": cap,
        "return_on_capital_pct": float(tr.pnl.sum() / cap * 100) if cap else float("nan"),
        "max_dd_usd": dd_usd, "max_dd_pct": float(dd_usd / cap * 100) if cap else float("nan"),
        "worst_day_usd": float(daily.min()), "worst_day_pct": float(daily.min() / cap * 100) if cap else float("nan"),
        "months_positive": int((monthly > 0).sum()), "months_total": int(len(monthly)),
        "worst_month_usd": float(monthly.min()), "days": int(len(daily)),
    }


def by_group(tr: pd.DataFrame, col: str) -> pd.DataFrame:
    tr = tr[tr.month >= EVAL_START]
    g = tr.groupby(col)
    out = pd.DataFrame({
        "n": g.size(), "matches": g.cond.nunique(), "usd_k": g.usd_in.sum() / 1e3, "pnl_usd": g.pnl.sum(),
        "per_share_c": g.pnl.sum() / g.shares.sum() * 100, "per_print_c": g.pnl_ps.mean() * 100,
    })
    dd = tr.groupby([col, "date"]).pnl.sum()
    out["sharpe_ann_active_days"] = dd.groupby(level=0).apply(
        lambda x: x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else np.nan)
    out["worst_day_usd"] = dd.groupby(level=0).min()
    return out.reset_index()
