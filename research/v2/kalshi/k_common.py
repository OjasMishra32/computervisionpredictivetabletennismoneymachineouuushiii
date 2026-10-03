"""Shared loaders for the Kalshi lens: matched matches, aligned PM / Kalshi tapes, 1 s mid grids."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.tape import load_tape  # noqa: E402
import kalshi_api as ka  # noqa: E402

OUT = ROOT / "research/v2/kalshi/out"
CACHE = ROOT / "data/v2_kalshi"


def kalshi_fee(p, mult: float = 1.0):
    """Kalshi taker fee per contract, quadratic: 0.07 * p * (1-p) (rounded up to the cent per ORDER;
    for orders of >= ~100 contracts the rounding is < 0.01c/contract so we use the exact value)."""
    return mult * 0.07 * p * (1 - p)


def kalshi_maker_fee(p):
    """quadratic_with_maker_fees series (KXATPMATCH/KXWTAMATCH since 2025-11-15): 0.0175 * p * (1-p)."""
    return 0.0175 * p * (1 - p)


def load_matched() -> pd.DataFrame:
    m = pd.read_parquet(CACHE / "matched.parquet")
    m = m[m.start < ka.OOS_CUTOFF].reset_index(drop=True)
    m["month"] = m.start.dt.strftime("%Y-%m")
    return m


def window(row) -> tuple[float, float]:
    s = row.start.timestamp()
    e = min(row.end, row.k_close).timestamp() if pd.notna(row.end) else row.k_close.timestamp()
    return float(s), float(e)


def load_pm(row) -> pd.DataFrame | None:
    t = load_tape(row.cond)
    if t is None:
        return None
    s, e = window(row)
    t = t[(t.timestamp >= s) & (t.timestamp <= e)].reset_index(drop=True)
    return pd.DataFrame({"ts": t.timestamp.to_numpy(float), "p": t.p0.to_numpy(float),
                         "ask": t.at_ask.to_numpy(bool), "q": t["size"].to_numpy(float),
                         "usd": t.usd.to_numpy(float)})


def load_k(row) -> pd.DataFrame | None:
    """Both Kalshi player markets on the outcome-0 probability axis.
    tk0: p0 = yes price, taker 'yes' lifts o0 ask.  tk1: p0 = 1 - yes price, taker 'no' lifts o0 ask."""
    parts = []
    for tk, flip in ((row.k_tk0, False), (row.k_tk1, True)):
        f = CACHE / "trades" / f"{tk}.parquet"
        if not f.exists():
            return None
        t = pd.read_parquet(f)
        if t.empty:
            continue
        t = t[~t.block]
        y = t.yes_price.to_numpy(float)
        parts.append(pd.DataFrame({
            "ts": t.ts.to_numpy(float), "p": 1 - y if flip else y,
            "ask": (t.taker_side == ("no" if flip else "yes")).to_numpy(bool),
            "q": t["count"].to_numpy(float), "mkt": int(flip)}))
    if not parts:
        return None
    k = pd.concat(parts).sort_values("ts", kind="stable").reset_index(drop=True)
    s, e = window(row)
    k = k[(k.ts >= s) & (k.ts <= e)].reset_index(drop=True)
    k["usd"] = k.q * np.where(k.ask, k.p, 1 - k.p)
    return k


def mid_grid(ts: np.ndarray, p: np.ndarray, ask: np.ndarray, grid: np.ndarray, stale: float = 30.0):
    """Mid proxy at the END of each grid second g (state after all prints with ts < g + 1):
    mean of latest ask-side and bid-side prints if both <= stale s old and ask >= bid, else last print."""
    out = np.full(len(grid), np.nan)
    if len(ts) == 0:
        return out, out.copy(), out.copy()
    edge = grid + 1.0
    i_all = np.searchsorted(ts, edge, "left") - 1
    ta, pa = ts[ask], p[ask]
    tb, pb = ts[~ask], p[~ask]
    ia = np.searchsorted(ta, edge, "left") - 1
    ib = np.searchsorted(tb, edge, "left") - 1
    a = np.where(ia >= 0, pa[np.maximum(ia, 0)] if len(pa) else np.nan, np.nan)
    b = np.where(ib >= 0, pb[np.maximum(ib, 0)] if len(pb) else np.nan, np.nan)
    a_age = np.where(ia >= 0, edge - (ta[np.maximum(ia, 0)] if len(ta) else 0), np.inf)
    b_age = np.where(ib >= 0, edge - (tb[np.maximum(ib, 0)] if len(tb) else 0), np.inf)
    last = np.where(i_all >= 0, p[np.maximum(i_all, 0)], np.nan)
    ok = (a_age <= stale) & (b_age <= stale) & (a >= b)
    out = np.where(ok, (a + b) / 2, last)
    a = np.where(a_age <= stale, a, np.nan)
    b = np.where(b_age <= stale, b, np.nan)
    return out, a, b


def mid_at(ts: np.ndarray, p: np.ndarray, ask: np.ndarray, T: np.ndarray, stale: float = 30.0) -> np.ndarray:
    """Vectorised mid proxy using only prints with ts <= T (same rule as mid_grid)."""
    T = np.asarray(T, float)
    if len(ts) == 0:
        return np.full(len(T), np.nan)
    ta, pa, tb, pb = ts[ask], p[ask], ts[~ask], p[~ask]
    ia = np.searchsorted(ta, T, "right") - 1
    ib = np.searchsorted(tb, T, "right") - 1
    i = np.searchsorted(ts, T, "right") - 1
    a = np.where((ia >= 0) & (len(ta) > 0), pa[np.clip(ia, 0, max(len(pa) - 1, 0))] if len(pa) else np.nan, np.nan)
    b = np.where((ib >= 0) & (len(tb) > 0), pb[np.clip(ib, 0, max(len(pb) - 1, 0))] if len(pb) else np.nan, np.nan)
    a_age = np.where(ia >= 0, T - (ta[np.clip(ia, 0, max(len(ta) - 1, 0))] if len(ta) else 0), np.inf)
    b_age = np.where(ib >= 0, T - (tb[np.clip(ib, 0, max(len(tb) - 1, 0))] if len(tb) else 0), np.inf)
    last = np.where(i >= 0, p[np.maximum(i, 0)], np.nan)
    ok = (a_age <= stale) & (b_age <= stale) & (a >= b)
    return np.where(ok, (a + b) / 2, last)


def gap_triggers(k: pd.DataFrame, pm: pd.DataFrame, g_trig: float = 0.02, fresh: float = 0.02,
                 look: float = 10.0, refractory: float = 20.0):
    """Real-time 'stale laggard' trigger evaluated at every Kalshi print t (Kalshi prints <= t,
    Polymarket prints with block ts <= t): fire when Kalshi's mid moved >= `fresh` over the last `look`
    seconds AND Kalshi's mid is >= g_trig away from Polymarket's mid in the same direction."""
    ts, p, ask = k.ts.values, k.p.values, k.ask.values
    km = mid_at(ts, p, ask, ts)
    km_prev = mid_at(ts, p, ask, ts - look)
    pmm = mid_at(pm.ts.values, pm.p.values, pm.ask.values, ts)
    mv = km - km_prev
    gap = km - pmm
    out, last = [], -1e18
    cand = np.nonzero(np.isfinite(mv) & np.isfinite(gap) & (np.abs(mv) >= fresh) & (np.abs(gap) >= g_trig)
                      & (np.sign(mv) == np.sign(gap)))[0]
    for i in cand:
        if ts[i] - last < refractory:
            continue
        last = ts[i]
        out.append((ts[i], int(np.sign(mv[i])), abs(mv[i])))
    return out


def robust_mid_at(ts: np.ndarray, p: np.ndarray, ask: np.ndarray, T: np.ndarray, win: float = 5.0) -> np.ndarray:
    """Sweep-resistant Kalshi fair value at times T (prints with ts <= T only): mean of the rolling-median
    ask-side print price and the rolling-median bid-side print price over the last `win` seconds; falls back
    to mid_at when a side has no print in the window or the medians cross."""
    T = np.asarray(T, float)
    base = mid_at(ts, p, ask, T)
    out = base.copy()
    meds = []
    for side in (True, False):
        tt, pp = ts[ask == side], p[ask == side]
        if len(tt) == 0:
            return base
        s = pd.Series(pp, index=pd.to_datetime(tt, unit="s"))
        med = s.rolling(f"{int(win)}s").median().to_numpy()
        i = np.searchsorted(tt, T, "right") - 1
        ok = (i >= 0) & (T - tt[np.maximum(i, 0)] <= win)
        meds.append(np.where(ok, med[np.maximum(i, 0)], np.nan))
    a, b = meds
    good = np.isfinite(a) & np.isfinite(b) & (a >= b)
    out[good] = (a[good] + b[good]) / 2
    return out


def gap_triggers_robust(k: pd.DataFrame, pm: pd.DataFrame, g_trig: float = 0.02, fresh: float = 0.02,
                        look: float = 10.0, refractory: float = 20.0):
    """Same as gap_triggers but Kalshi's mid is the sweep-resistant robust_mid_at (5 s rolling medians)."""
    ts, p, ask = k.ts.values, k.p.values, k.ask.values
    km = robust_mid_at(ts, p, ask, ts)
    km_prev = robust_mid_at(ts, p, ask, ts - look)
    pmm = mid_at(pm.ts.values, pm.p.values, pm.ask.values, ts)
    mv, gap = km - km_prev, km - pmm
    out, last = [], -1e18
    cand = np.nonzero(np.isfinite(mv) & np.isfinite(gap) & (np.abs(mv) >= fresh) & (np.abs(gap) >= g_trig)
                      & (np.sign(mv) == np.sign(gap)))[0]
    for i in cand:
        if ts[i] - last < refractory:
            continue
        last = ts[i]
        out.append((ts[i], int(np.sign(mv[i])), abs(mv[i]), km[i]))
    return out
