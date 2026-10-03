"""Adversarial check of the "exit" lens: independent re-simulation + leakage probes (IS only).

Independent of sim_exit.py / analyze_exit.py (own tape matching, own FIFO fill loop, own walk-forward).

  1. Reproduce the headline: sh500 entries, maker exit 1 tick inside the touch (improve1), taker
     fallback B, no rebate, (H, T) walk-forward on past months over the 5x4 grid.
  2. Probe A, fill-price peek: the touch model fills at the price of the very print that fills us.
     A resting order's price must be set before that print exists. "nopeek" keeps every touch fill
     but prices it at the last same-side print strictly before the fill second (<= 30 s old), i.e.
     min(q, L_prev) - tick for a sell of outcome 0 (max(q, L_prev) + tick for a bid on outcome 0).
     nopeek5 / nopeek2: same with L_prev at most 5 s / 2 s old. slow5: symmetric slow re-peg (our
     level = L_prev(<=5 s) -/+ 1 tick; a print fills us only if it reaches that level; fill at it).
  3. Probe B, all-or-nothing size skip: the touch model skips exit-side prints smaller than our
     order and fills whole on the first big one. "partial" fills progressively on every exit-side
     print in the window (FIFO consumption across our orders), remainder to the taker fallback.
  4. Probe C, entry lookahead: entries are fast-tier prints in [onset, onset+3 s) of a jump whose
     detector fires at detect_ts (up to 10 s after onset, using later prints). Split P&L by whether
     the jump was detectable at the entry second.

    .venv/bin/python research/v2/exit/verify_leakage.py
Writes research/v2/exit/verify_leakage.json. Reads no OOS data (asserts it).
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OOS = pd.Timestamp("2026-08-25 14:15", tz="UTC")
HS, TS = (2, 5, 10, 20, 30), (30, 60, 120, 300)
CAP_SH, CAP_MATCH, LAT, STALE = 500.0, 3000.0, 1, 30
HERE = Path(__file__).resolve().parent


def one(job):
    cond, e, start, end = job
    f = ROOT / "data/raw/trades" / f"{cond}.parquet"
    if not f.exists():
        return None
    t = pd.read_parquet(f, columns=["timestamp", "side", "outcomeIndex", "price", "size", "proxyWallet", "p0"])
    s0 = int(start.timestamp())
    e0 = int(end.timestamp()) if pd.notna(end) else s0 + 6 * 3600
    t = t[(t.timestamp >= s0) & (t.timestamp <= e0)].sort_values("timestamp", kind="stable").reset_index(drop=True)
    if t.empty:
        return None
    ts = t.timestamp.to_numpy(np.int64)
    p0 = t.p0.to_numpy(float)
    ask = (((t.side == "BUY") & (t.outcomeIndex == 0)) | ((t.side == "SELL") & (t.outcomeIndex == 1))).to_numpy()
    size = t["size"].to_numpy(float)
    usd = size * t.price.to_numpy(float)
    wal = t.proxyWallet.to_numpy()
    tick = 0.01 if np.all(np.abs(p0 * 100 - np.round(p0 * 100)) < 1e-6) else 0.001
    # --- own matching of entries to tape rows: (ts, wallet, dir, p, usd) in order of appearance
    idx = defaultdict(list)
    for k in range(len(t)):
        idx[(int(ts[k]), wal[k], 1 if ask[k] else -1, round(p0[k], 6), round(usd[k], 3))].append(k)
    e = e.sort_values("ts", kind="stable").reset_index(drop=True)
    row = np.full(len(e), -1)
    for i, r in enumerate(e.itertuples()):
        lst = idx.get((int(r.ts), r.wallet, int(r.dir), round(r.p, 6), round(r.usd, 3)))
        if lst:
            row[i] = lst.pop(0)
    matched = row >= 0
    own = np.zeros(len(t), bool)
    own[row[matched]] = True
    edir = e.dir.to_numpy(float)
    ep = e.p.to_numpy(float)
    pp = np.where(edir > 0, ep, 1 - ep)
    sh = np.where(matched, np.minimum(size[np.maximum(row, 0)], CAP_SH), np.nan)
    cum = np.cumsum(np.nan_to_num(sh * pp))
    acc = matched & (cum <= CAP_MATCH)
    ets = e.ts.to_numpy(np.int64)
    delay = int(e.delay.iloc[0])
    rate = float(e.fee_rate.iloc[0])
    res = float(e.res.iloc[0])
    fee_in = rate * ep * (1 - ep)
    # exit-side (non-own) arrays and all-print arrays per side
    sid = {s: np.flatnonzero((ask == s) & ~own) for s in (True, False)}
    allid = {s: np.flatnonzero(ask == s) for s in (True, False)}

    def prev_level(s, tsec, stale=STALE):
        """last same-side print (any) strictly before second tsec, <= stale s old, else nan"""
        a = allid[s]
        k = np.searchsorted(ts[a], tsec, "left") - 1
        if k < 0 or tsec - ts[a][k] > stale:
            return np.nan
        return p0[a][k]

    def fallback(i, H, T):
        s = edir[i] < 0  # long o0 sells o0 -> hits bid (at_ask False); long o1 -> at_ask True
        a = allid[s]
        tx = ets[i] + H + T + delay + LAT
        k = np.searchsorted(ts[a], tx, "left")
        if k >= len(a):
            return edir[i] * (res - ep[i]) - fee_in[i], "res"
        px = p0[a][k]
        return edir[i] * (px - ep[i]) - fee_in[i] - rate * px * (1 - px), "taker"

    ai = np.flatnonzero(acc)
    out = []
    for H in HS:
        for T in TS:
            rem = size.copy()
            remP = size.copy()
            remS = size.copy()
            for i in ai:
                s = edir[i] > 0
                cand = sid[s]
                lo = np.searchsorted(ts[cand], ets[i] + H, "left")
                hi = np.searchsorted(ts[cand], ets[i] + H + T, "right")
                fb_pnl, fb_how = fallback(i, H, T)
                # touch / improve1 / nopeek
                j = -1
                for c in cand[lo:hi]:
                    if rem[c] >= sh[i] - 1e-9:
                        j = c
                        break
                if j >= 0:
                    rem[j] -= sh[i]
                    q = p0[j]
                    touch = edir[i] * (q - ep[i]) - fee_in[i]
                    imp1 = edir[i] * (q - edir[i] * tick - ep[i]) - fee_in[i]
                    nps = []
                    for st_ in (30, 5, 2):
                        L = prev_level(s, ts[j], st_)
                        qn = q if not np.isfinite(L) else (min(q, L) if s else max(q, L))
                        nps.append(edir[i] * (qn - edir[i] * tick - ep[i]) - fee_in[i])
                        if st_ == 30:
                            peek = (q - qn) * edir[i]
                    nop, nop5, nop2 = nps
                    how, dt = "maker", ts[j] - ets[i]
                else:
                    touch = imp1 = nop = nop5 = nop2 = fb_pnl
                    how, dt, peek = fb_how, np.nan, 0.0
                # symmetric slow re-peg: our level = last same-side print (<= 5 s old, strictly earlier
                # second) -/+ 1 tick, else the print itself -/+ 1 tick; a print fills us only if it
                # reaches our level; fill at our level.
                slow = fb_pnl
                for c in cand[lo:hi]:
                    if remS[c] < sh[i] - 1e-9:
                        continue
                    L = prev_level(s, ts[c], 5)
                    L = p0[c] if not np.isfinite(L) else L
                    lvl = L - tick if s else L + tick
                    if (s and p0[c] >= lvl - 1e-9) or ((not s) and p0[c] <= lvl + 1e-9):
                        remS[c] -= sh[i]
                        slow = edir[i] * (lvl - ep[i]) - fee_in[i]
                        break
                # partial-fill model (touch price - 1 tick, i.e. improve1 with progressive fills)
                need, got, val = sh[i], 0.0, 0.0
                if (H, T) in ((5, 60), (5, 30), (5, 300), (30, 300)):
                    for c in cand[lo:hi]:
                        if remP[c] <= 1e-9:
                            continue
                        f_ = min(remP[c], need - got)
                        remP[c] -= f_
                        got += f_
                        val += f_ * (edir[i] * (p0[c] - edir[i] * tick - ep[i]) - fee_in[i])
                        if got >= need - 1e-9:
                            break
                    part = (val + (need - got) * fb_pnl) / need
                else:
                    part = np.nan
                out.append((e.eid.iloc[i], H, T, touch, imp1, nop, nop5, nop2, slow, part, how, dt, peek))
    if not out:
        return None
    df = pd.DataFrame(out, columns=["eid", "H", "T", "touch", "improve1", "nopeek", "nopeek5", "nopeek2", "slow5", "partial",
                                    "how", "dt", "peek"])
    meta = pd.DataFrame({"eid": e.eid.to_numpy()[ai], "cond": cond, "ts": ets[ai], "shares": sh[ai],
                         "month": e.month.to_numpy()[ai], "delay": delay, "rate": rate,
                         "hold_res": edir[ai] * (res - ep[ai]) - fee_in[ai]})
    return df, meta, int(matched.sum()), len(e)


def cluster_ci(g, col, n=1000, seed=1):
    a = g.groupby("cond")[col].agg(["sum", "size"])
    s, k = a["sum"].to_numpy(), a["size"].to_numpy()
    rng = np.random.default_rng(seed)
    b = [s[i].sum() / k[i].sum() for i in (rng.integers(0, len(a), len(a)) for _ in range(n))]
    return [float(x * 100) for x in np.percentile(b, [2.5, 97.5])]


def wf(grid: pd.DataFrame, col: str, months):
    """grid: per (eid,H,T) rows with column col and dollars; pick per month the max summed $ over past months."""
    g = grid.assign(usd=grid[col] * grid.shares)
    sums = g.groupby(["month", "H", "T"]).usd.sum().unstack(["H", "T"]).reindex(months).fillna(0)
    cnt = g[(g.H == HS[0]) & (g["T"] == TS[0])].groupby("month").size().reindex(months).fillna(0)
    parts, picks = [], []
    for k, m in enumerate(months):
        past = months[:k]
        pick = (5, 60) if cnt[past].sum() < 1000 else sums.loc[past].sum().idxmax()
        picks.append((m, int(pick[0]), int(pick[1])))
        parts.append(g[(g.month == m) & (g.H == pick[0]) & (g["T"] == pick[1])])
    return pd.concat(parts), picks


def summ(x, col):
    r = {"n": int(len(x)), "ps_c": float(x[col].mean() * 100), "ci": cluster_ci(x, col),
         "usd": float((x[col] * x.shares).sum())}
    return r


def main():
    u = pd.read_parquet("data/derived/universe_is.parquet", columns=["cond", "start", "end"])
    assert (u.start < OOS).all(), "universe_is contains OOS matches"
    s = pd.read_parquet("data/derived/shadow_is_uncapped.parquet",
                        columns=["cond", "ts", "p", "dir", "usd", "wallet", "fee_rate", "delay", "res", "month"])
    assert s.cond.isin(u.cond).all(), "shadow rows outside universe_is"
    s["month"] = s.month.astype(str)
    s = s.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    s["eid"] = np.arange(len(s))
    us = u.set_index("cond")
    jobs = [(c, g, us.at[c, "start"], us.at[c, "end"]) for c, g in s.groupby("cond", sort=False)]
    res, metas, nm, ne = [], [], 0, 0
    with ProcessPoolExecutor(2) as ex:
        for k, r in enumerate(ex.map(one, jobs, chunksize=16)):
            if r is not None:
                res.append(r[0]); metas.append(r[1]); nm += r[2]; ne += r[3]
            if k % 1000 == 0:
                print(k, len(jobs), flush=True)
    grid = pd.concat(res, ignore_index=True)
    meta = pd.concat(metas, ignore_index=True)
    grid = grid.merge(meta, on="eid")
    grid["regime"] = grid.delay.astype(str) + "s/" + (grid.rate * 100).round().astype(int).astype(str) + "%"
    months = sorted(meta.month.unique())
    out = {"entries_shadow": ne, "matched_to_tape": nm, "accepted_sh500": int(len(meta)), "months": months}

    # 1. headline reproduction + probes on the identical WF machinery
    grid.to_parquet(ROOT / "data/v2_exit_verify/grid.parquet")
    for col in ("touch", "improve1", "nopeek", "nopeek5", "nopeek2", "slow5", "partial"):
        if col == "partial":
            # partial computed only on the reported WF cells; reuse improve1's picks
            _, picks = wf(grid, "improve1", months)
            parts = [grid[(grid.month == m) & (grid.H == h) & (grid["T"] == t)] for m, h, t in picks]
            w = pd.concat(parts).assign(usd=lambda d: d.partial * d.shares)
        else:
            w, picks = wf(grid, col, months)
        r1 = w[w.regime == "1s/5%"]
        out[col] = {"picks": picks, "all": summ(w, col), "1s5": summ(r1, col),
                    "by_month_c": {m: float(g[col].mean() * 100) for m, g in w.groupby("month")}}
        print(col, out[col]["all"], out[col]["1s5"], picks, flush=True)

    w, _ = wf(grid, "improve1", months)
    mk = w[w.how == "maker"]
    out["peek"] = {"maker_fills": int(len(mk)),
                   "peek_quantiles_c": {str(q): float(mk.peek.quantile(q) * 100) for q in (0.5, 0.75, 0.9, 0.95, 0.99)},
                   "frac_fills_print_better_than_prior_touch": float((mk.peek > 1e-9).mean()),
                   "mean_peek_c_per_maker_fill": float(mk.peek.mean() * 100),
                   "mean_peek_c_per_entry_1s5": float(w[w.regime == "1s/5%"].peek.mean() * 100)}
    out["hold_to_res"] = {"all": summ(meta.assign(x=meta.hold_res), "x"),
                          "1s5": summ(meta[(meta.delay == 1) & (meta.rate == 0.05)].assign(x=lambda d: d.hold_res), "x")}

    # 4. entry lookahead: was the jump detectable at the entry second?
    j = pd.read_parquet("data/derived/jumps_is.parquet", columns=["cond", "onset_ts", "detect_ts"]).sort_values("onset_ts")
    w2 = w.sort_values("ts").assign(ts=lambda d: d.ts.astype(float))
    w2 = pd.merge_asof(w2, j, left_on="ts", right_on="onset_ts", by="cond", direction="backward")
    w2["lag"] = w2.ts - w2.detect_ts
    lk = {}
    for name, m in (("before_detection(lag<0)", w2.lag < 0), ("same_second(lag=0)", w2.lag == 0),
                    ("after_detection(lag>=1)", w2.lag >= 1)):
        for reg, g in (("all", w2[m]), ("1s5", w2[m & (w2.regime == "1s/5%")])):
            lk[f"{name}/{reg}"] = summ(g, "improve1") if len(g) else {"n": 0}
    out["entry_vs_detection"] = lk
    print(json.dumps(out["peek"], indent=1), json.dumps(lk, indent=1))
    (HERE / "verify_leakage.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
