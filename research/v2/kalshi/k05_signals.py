"""Step 5: build laggard-strategy signal/fill tables (parameter-free; parameters applied in k06).

S_PM  "Kalshi leads -> take Polymarket":  two signal families, both real time on Kalshi prints:
      'jump' = src.tiers.jump_onsets detector (J = 4c) fired at Kalshi print time t_s (prints <= t_s only);
      'gap'  = stale-laggard trigger: Kalshi mid moved >= 2c in the last 10 s and sits >= 2c away from the
               Polymarket mid in the same direction (k_common.gap_triggers; 20 s refractory);
      'gaprob' = same trigger, Kalshi fair = sweep-resistant 5 s rolling-median mid (k_common.robust_mid_at).
      Fill = first Polymarket print on the signal side (ask-side prints for buys of outcome 0, bid-side
      for sells) with block timestamp >= ceil(t_s + L + D + B), L = 0.25 s network latency, D = the
      match's Polymarket taker delay (3 s or 1 s), B = block-timestamp allowance (2 s base; 0/4 tested),
      and no later than 3 s after that; no print -> no fill.
S_K   "Polymarket leads -> take Kalshi":  signal = Polymarket jump detect_ts (jumps_is; block time, so
      already conservative). Fill = first Kalshi print on the signal side with ts >= t_s + L + D_K,
      D_K = assumed Kalshi order delay (1 s base; 0/3 tested), within 3 s.

For every fill we record the fair value at signal on the leading venue, the laggard's own mid at signal,
fill price, the 3 s side volume after the fill, marks at +15/+60/+120 s on both venues, the opposite-side
price at +60 s (taker exit), the resolution payoff, and a cross-venue hedge price (first opposite-side print
on the OTHER venue at the earliest time the fill can be known: Kalshi at t_s + L + D + 0.5 s;
Polymarket at ceil(ts_f + L + D + 2); when nobody printed on that side within 3 s, the touch is proxied as the
last (<= 5 s old) print on the other side -/+ 2c (hedge_px); hedge_px_strict keeps only real prints).
Output: data/v2_kalshi/signals_pm.parquet, signals_k.parquet
Run: .venv/bin/python research/v2/kalshi/k05_signals.py
"""
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from k_common import (CACHE, ROOT, gap_triggers, gap_triggers_robust, load_k, load_matched, load_pm,  # noqa: E402
                      mid_grid, window)
from src.tiers import jump_onsets  # noqa: E402

L = 0.25
PM_B = (0, 2, 4)
K_D = (0, 1, 3)
W = 3
HS = (15, 60, 120)
_J = None


def _init():
    global _J
    j = pd.read_parquet(ROOT / "data/derived/jumps_is.parquet", columns=["cond", "detect_ts", "dir", "size"])
    _J = {c: g for c, g in j.groupby("cond")}


def state_at(ts, p, ask, t, stale=30.0):
    """Mid proxy using prints with ts <= t only."""
    i_a = np.searchsorted(ts[ask], t, "right") - 1
    i_b = np.searchsorted(ts[~ask], t, "right") - 1
    ta, pa, tb, pb = ts[ask], p[ask], ts[~ask], p[~ask]
    a = pa[i_a] if i_a >= 0 and t - ta[i_a] <= stale else np.nan
    b = pb[i_b] if i_b >= 0 and t - tb[i_b] <= stale else np.nan
    if np.isfinite(a) and np.isfinite(b) and a >= b:
        return (a + b) / 2
    i = np.searchsorted(ts, t, "right") - 1
    return p[i] if i >= 0 else np.nan


def first_fill(ts, p, ask, q, d, t_exec):
    """First print on side d (d=+1: ask-side) with ts >= t_exec and <= t_exec + W."""
    side = ask if d > 0 else ~ask
    tsd, pd_, qd = ts[side], p[side], q[side]
    i = np.searchsorted(tsd, t_exec, "left")
    if i >= len(tsd) or tsd[i] > t_exec + W:
        return None
    j = np.searchsorted(tsd, tsd[i] + W, "right")
    return tsd[i], pd_[i], pd_[i:j], qd[i:j]


def touch_proxy(ts, p, ask, s, T, tick=0.02, stale=5.0):
    """When nobody printed on side s in the hedge window, estimate the touch we would hit from the last print
    on the OTHER side, conservatively assuming a 2c spread: hitting the bid (s=-1) ~ last ask-side print - 2c;
    lifting the ask (s=+1) ~ last bid-side print + 2c. NaN if that print is older than `stale` s."""
    other = ask if s < 0 else ~ask
    to, po = ts[other], p[other]
    i = np.searchsorted(to, T, "right") - 1
    if i < 0 or T - to[i] > stale:
        return np.nan
    return po[i] + s * tick


def hedge_price(ts, p, ask, q, s, T):
    h = first_fill(ts, p, ask, q, s, T)
    if h is not None:
        return h[1], h[1], h[0] - T
    return touch_proxy(ts, p, ask, s, T), np.nan, np.nan


def one(row):
    pm, k = load_pm(row), load_k(row)
    if pm is None or k is None or len(pm) < 20 or len(k) < 20:
        return [], []
    s, e = window(row)
    grid = np.arange(int(s), int(e) + 400, dtype=float)
    mp, ap, bp = mid_grid(pm.ts.values, pm.p.values, pm.ask.values, grid)
    mk, ak, bk = mid_grid(k.ts.values, k.p.values, k.ask.values, grid)
    P = (pm.ts.values, pm.p.values, pm.ask.values, pm.q.values)
    K = (k.ts.values, k.p.values, k.ask.values, k.q.values)

    def marks(t, d, pref):
        out = {}
        i0 = int(np.floor(t) - grid[0])
        for h in HS:
            i = i0 + h
            ok = 0 <= i < len(grid) and grid[i] <= e
            out[f"pm_mid_{h}"] = mp[i] if ok else np.nan
            out[f"k_mid_{h}"] = mk[i] if ok else np.nan
        i = i0 + 60
        ok = 0 <= i < len(grid) and grid[i] <= e
        # taker exit at +60: sell into the bid (d=+1) / buy back at the ask (d=-1) on the traded venue
        if pref == "pm":
            out["exit_px_60"] = (bp[i] if d > 0 else ap[i]) if ok else np.nan
        else:
            out["exit_px_60"] = (bk[i] if d > 0 else ak[i]) if ok else np.nan
        return out

    base = {"cond": row.cond, "month": row.month, "fee_rate": row.fee_rate, "delay": row.delay,
            "res0": row.res0, "k_settle0": row.k_settle0, "series": row.series}
    out_pm, out_k = [], []
    # S_PM: Kalshi-led signals -> trade Polymarket.  family 'jump' = src jump detector on Kalshi prints;
    # family 'gap' = stale-laggard trigger (k_common.gap_triggers)
    sigs = [("jump", t_s, int(d), size, None) for onset, d, size, t_s in jump_onsets(k.ts.values, k.p.values, k.usd.values)]
    sigs += [("gap", t_s, int(d), size, None) for t_s, d, size in gap_triggers(k, pm)]
    # 'gaprob': same trigger with a sweep-resistant Kalshi fair (5 s rolling medians per side)
    sigs += [("gaprob", t_s, int(d), size, kf) for t_s, d, size, kf in gap_triggers_robust(k, pm)]
    for fam, t_s, d, size, kf in sigs:
        fair = state_at(*K[:3], t_s) if kf is None else kf
        own = state_at(*P[:3], t_s)
        for B in PM_B:
            t_exec = np.ceil(t_s + L + row.delay + B)
            f = first_fill(*P, d, t_exec)
            if f is None:
                continue
            ts_f, p_f, pw, qw = f
            rec = {**base, "fam": fam, "t_s": t_s, "d": d, "jsize": size, "B": B, "fair": fair, "own": own,
                   "gap": d * (fair - own), "ts_f": ts_f, "p_f": p_f, "wait": ts_f - t_s,
                   "edge_f": d * (fair - p_f), "pw": pw.astype(np.float32), "qw": qw.astype(np.float32)}
            rec.update(marks(ts_f, d, "pm"))
            # hedge: take the opposite side on Kalshi at the EARLIEST time we can know the PM fill
            # (order executes at t_s + L + D; +0.5 s for the fill notification). Hedging later than this
            # would flatter the hedge because Kalshi keeps drifting in the signal direction.
            # if no Kalshi print on the hedge side within 3 s, the touch is proxied from the other side +- 2c
            rec["hedge_px"], rec["hedge_px_strict"], rec["hedge_wait"] = hedge_price(*K, -d, t_s + L + row.delay + 0.5)
            out_pm.append(rec)
    # S_K: Polymarket-detected jumps -> trade Kalshi
    pj = _J.get(row.cond)
    if pj is not None:
        for x in pj.itertuples():
            t_s, d = float(x.detect_ts), int(x.dir)
            if t_s < s or t_s > e:
                continue
            fair = state_at(*P[:3], t_s)
            own = state_at(*K[:3], t_s)
            for D in K_D:
                f = first_fill(*K, d, t_s + L + D)
                if f is None:
                    continue
                ts_f, p_f, pw, qw = f
                rec = {**base, "fam": "jump", "t_s": t_s, "d": d, "jsize": float(x.size), "B": D, "fair": fair, "own": own,
                       "gap": d * (fair - own), "ts_f": ts_f, "p_f": p_f, "wait": ts_f - t_s,
                       "edge_f": d * (fair - p_f), "pw": pw.astype(np.float32), "qw": qw.astype(np.float32)}
                rec.update(marks(ts_f, d, "k"))
                # hedge on Polymarket (B = 2); touch proxy +- 2c if no print on that side within 3 s
                rec["hedge_px"], rec["hedge_px_strict"], rec["hedge_wait"] = hedge_price(
                    *P, -d, np.ceil(ts_f + L + row.delay + 2))
                out_k.append(rec)
    return out_pm, out_k


def main():
    m = load_matched()
    rows = [SimpleNamespace(**r) for r in m.to_dict("records")]
    with ProcessPoolExecutor(2, initializer=_init) as ex:
        res = list(ex.map(one, rows, chunksize=8))
    spm = pd.DataFrame([x for a, _ in res for x in a])
    sk = pd.DataFrame([x for _, b in res for x in b])
    spm.to_parquet(CACHE / "signals_pm.parquet")
    sk.to_parquet(CACHE / "signals_k.parquet")
    print("S_PM signals", len(spm), spm.cond.nunique() if len(spm) else 0,
          "S_K signals", len(sk), sk.cond.nunique() if len(sk) else 0)


if __name__ == "__main__":
    main()
