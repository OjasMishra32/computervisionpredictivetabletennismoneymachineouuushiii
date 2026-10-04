"""LIQUIDITY AND PRICE IMPACT: a price-impact model for in-play tennis moneylines, a check of the CV trader's fill
assumption (phi = 0.5 of the stale depth) against the real order book, and the capacity curves of v2 and the CV
trader re-run with the impact model applied.

    paper only; public Polymarket data already on disk; no order is built or sent

    python scripts/impact_model.py                  # every stage: prints -> l2 -> fit -> capacity -> report
    python scripts/impact_model.py --stage fit      # one stage (prints | l2 | fit | capacity | report)

Outputs: results/liquidity/impact.json, results/liquidity/capacity_cells.csv, results/liquidity/impact_capacity.{png,pdf}.
Heavy intermediate tables go to results/liquidity/cache/ (git-ignored). Burned-OOS reads are logged, before they
happen, to results/liquidity/oos_peeks_pending.txt (this workflow may not write results/oos_peeks.log; the lines
are meant to be appended there by the integrator).

PLAN (written before any capacity number was computed; nothing below is tuned on a capacity result)
 1. Impact model, from the public Polymarket tapes (data/raw/trades: one row = one taker order with its average
    price; in-play window as src/tape.in_play). Mid before an order = the print-based mid proxy of src/tiers.py (latest
    ask-side and bid-side prints, both <= 30 s old), from strictly earlier seconds only.
    Temporary cost of a taker order of Q shares (price units, vs that mid):  C_b(Q) = a_b + k_b (Q/1000)^delta,
    delta common to all buckets (grid 0.10-1.00; see A1), a_b and k_b per liquidity quintile b of the match's Gamma volume
    (quintile edges from IS matches). Sample: IS orders, price in [0.05, 0.95], pre-trade spread <= 5c, cost
    winsorised at +-20c.
    Permanent impact (Kyle lambda): R_h = d (m_{t+h} - m_pre) = alpha_b + lambda_b(h) Q/1000, on "no-news" orders
    (no jump onset of src/tiers.jump_onsets in the 60 s before the order or until 10 s after the horizon),
    Q <= 20,000 shares, h in 5 / 30 / 60 / 120 / 300 / 600 s, R winsorised at +-30c.
    CIs: match-clustered bootstrap, 200 draws. Burned-OOS orders are fitted the same way, as a stability check only.
 2. Live order book (L2) checks, 2026-10-03, receive time < 14:00 UTC only (the forward window's matches start
    >= 14:00 UTC, HYPOTHESIS_V2.md A1.6; nothing at or after 14:00 is read). Singles moneylines with a known start.
    (a) Book-walk cost of Q shares vs the mid, sampled every 2 s in play: quiet samples (>= 30 s from any reprice)
        vs 1-3 s after a reprice on the with-move side (v2's window). Post-jump multiplier
        M = max(1, pooled mean post / mean quiet over Q = 100-2,500), match-clustered CI.
    (b) At every book reprice >= 3c (mid vs its value 2 s earlier, 20 s cool-down), the stale depth = shares resting
        at prices better than the mid 3 s after the reprice, on the side a with-move taker lifts, 2 / 1 / 0.25 s
        before the half-move time, and the with-move taker shares printed at stale prices from then to +0.5 s.
        phi_lo = 1 - printed / stale = the share of the stale depth that other takers leave (pooled by shares,
        match-clustered CI). The 482 officially stamped points of research/v2/latency/out are re-read the same way.
        Measured phi = the smallest of the three tau values; its lower bound = the smallest lower 95% bound.
 3. Capacity re-run (capacity_study.py's grid conventions, imported, not changed).
    v2: the frozen engine (capacity_study.v2_policy) on the same 28 size cells (net cap {50..5000} x order cap
        {$250, $1k, $5k, $25k}, phi_v2 = 1). Each trade then pays (i) the temporary cost of walking the book beyond
        the fast-tier print it copies, M [C_b(h + s) - C_b(h)] ("alongside": our s shares and the print's h shares
        walk the book together and pay one average price), and (ii) the permanent impact left by our own earlier
        trades in the same match, d_i sum_{j<i} d_j s_j lambda_b(t_i - t_j) / 1000 (lambda linear in log time between
        the measured horizons, lambda(5 s) below 5 s, flat beyond 600 s, floored at 0); the fee is re-computed at the
        worse price. Conservative variant: "behind" (our shares walk the book after the print's) with the upper 95%
        bounds of k_b, lambda_b and M.
    CV trader: its fills already walk the measured live stale book (src/tier0.py), which is its temporary impact. We
        add (ii) and use phi = min(0.5, measured lower bound), so the check can only lower the published capacity.
        The measured phi itself is run as a labelled sensitivity. Same 20 seeds, coverage 10 matches/day, $250 and
        $1k orders, both stamp-lag readings, both allocations of the stale depth.
    Reported for each: the capital where the seed-mean Sharpe halves along the size path ($250 orders for CV, $1k for
    v2; capacity_study.capacity_answer) and the cell with the highest $/day, IS and burned OOS (non-blind; logged).

AMENDMENT A1 (post hoc, written after the first fit and before any capacity number was computed)
 - The first temporary-cost fit put delta at the 0.10 edge of its grid (CI [0.10, 0.10]): realised costs barely
   rise with the size traders CHOSE. The grid now runs from 0.02. Nothing else in the fit changes.
 - Realised costs of chosen sizes understate the cost of a FORCED size (traders size to the depth they see), and v2
   must trade when the fast tier does. So a third v2 variant, "bookwalk", is added: the temporary cost is read off
   the live displayed book instead of the print fit. C_tour(Q) = the mean (over matches) of each ATP/WTA live match's
   quiet book-walk cost, live matches with >= $10k/h in-play taker volume; a historical match with in-play volume
   U_m walks the same book with depth scaled by (U_m / U_ref)^beta, never deeper than the reference (U_ref = median
   U of those live matches; beta = slope of log depth within 2c on log U across all live matches, clipped to
   [0.5, 1.5]); extra cost = M [C(s_m (h + s)) - C(s_m h)], s_m = max(1, (U_ref / U_m)^beta), plus the same carry
   term. It is reported next to the declared variants, labelled post hoc.
 - After the first capacity run: the carry term is symmetric, so a trade that cuts our exposure is credited with the
   displacement our earlier trades left (the CV trader's P&L rose by up to 2%). The conservative variants now credit
   no favourable displacement (carry cost floored at 0 per trade). This can only lower the conservative numbers.
"""
from __future__ import annotations

import argparse
import datetime as dtm
import gzip
import json
import math
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

OUT = ROOT / "results/liquidity"
CACHE = OUT / "cache"
PEEK = OUT / "oos_peeks_pending.txt"
LABEL = "paper only; public Polymarket data already on disk; no order built or sent"
H = (5, 30, 60, 120, 300, 600)
QREF = 1000.0
QBINS = [1, 10, 30, 100, 300, 1000, 3000, 10000, 1e9]
DELTAS = np.round(np.r_[0.02, 0.05, np.arange(0.10, 1.0001, 0.05)], 2)
NBOOT = 200
SEED = 20261004
CUT_MS = 1791036000000            # 2026-10-03 14:00:00 UTC: the forward window opens (HYPOTHESIS_V2.md A1.6)
L2_FILES = ["data/live/market_20261003_0946.jsonl.gz", "data/live/market_20261003_1003.jsonl.gz"]
L2_TOKENS = ["data/live/tokens_20261003_1003.jsonl.gz"]
QGRID = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000)
SNAP_OFF = (-2000, -1000, -250, 500, 1000, 2000, 3000)
GRID_MS = 2000
REP_D = 0.03
TAUS = (2.0, 1.0, 0.25)


def now() -> str:
    return dtm.datetime.now(dtm.timezone.utc).isoformat()


def log_oos(what: str) -> None:
    """Append a burned-OOS read to this workflow's own peek log BEFORE the read (format of results/oos_peeks.log)."""
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{now()} impact model (scripts/impact_model.py): {what}\n"
    with open(PEEK, "a") as fh:
        fh.write(line)
    print("[oos log]", line.strip())


def boot_idx(n: int, b: int, rng) -> np.ndarray:
    return rng.integers(0, n, (b, n))


# ============================================================================================ stage 1: tape orders
def _orders_one(r: dict) -> tuple[pd.DataFrame | None, dict | None]:
    from src.tape import load_tape
    from src.tiers import jump_onsets
    t = load_tape(r["cond"])
    if t is None:
        return None, None
    s = int(pd.Timestamp(r["start"]).timestamp())
    e = int(pd.Timestamp(r["end"]).timestamp()) if pd.notna(r["end"]) else s + 6 * 3600
    t = t[(t.timestamp >= s) & (t.timestamp <= e)].sort_values("timestamp", kind="stable")
    if len(t) < 20:
        return None, None
    ts = t.timestamp.to_numpy(np.int64)
    p = t.p0.to_numpy(float)
    ask = t.at_ask.to_numpy(bool)
    Q = t["size"].to_numpy(float)
    usd = t.usd.to_numpy(float)
    n = len(ts)
    idx = np.arange(n)
    ia = np.maximum.accumulate(np.where(ask, idx, -1))
    ib = np.maximum.accumulate(np.where(~ask, idx, -1))
    pa = np.where(ia >= 0, p[np.maximum(ia, 0)], np.nan)
    pb = np.where(ib >= 0, p[np.maximum(ib, 0)], np.nan)
    ta = np.where(ia >= 0, ts[np.maximum(ia, 0)], -10 ** 12)
    tb = np.where(ib >= 0, ts[np.maximum(ib, 0)], -10 ** 12)

    def state(j, tref):
        ok = (j >= 0) & (j < n)
        jj = np.clip(j, 0, n - 1)
        a, b = pa[jj], pb[jj]
        v = ok & (tref - ta[jj] <= 30) & (tref - tb[jj] <= 30) & np.isfinite(a) & np.isfinite(b) & (a >= b)
        return np.where(v, (a + b) / 2, np.nan), np.where(v, a - b, np.nan)

    jpre = np.searchsorted(ts, ts, "left") - 1          # last print in a strictly earlier second
    m_pre, sp_pre = state(jpre, ts)
    out = {"ts": ts, "d": np.where(ask, 1, -1).astype(np.int8), "Q": Q.astype(np.float32),
           "p": p.astype(np.float32), "m_pre": m_pre.astype(np.float32), "sp_pre": sp_pre.astype(np.float32)}
    for h in H:
        k = np.searchsorted(ts, ts + h, "left")
        tk = ts[np.clip(k, 0, n - 1)]
        m, _ = state(k, tk)
        out[f"m{h}"] = np.where((k < n) & (tk - (ts + h) <= 30), m, np.nan).astype(np.float32)
    on = jump_onsets(ts.astype(float), p, usd)
    on_t = np.array([o[0] for o in on], float) if on else np.array([], float)
    det_t = np.array([o[3] for o in on], float) if on else np.array([], float)
    k0 = np.searchsorted(on_t, ts, "right") - 1
    out["since"] = np.where(k0 >= 0, ts - on_t[np.maximum(k0, 0)], -1.0).astype(np.float32) if len(on_t) else \
        np.full(n, -1.0, np.float32)
    k1 = np.searchsorted(on_t, ts, "right")
    out["until"] = (np.where(k1 < len(on_t), on_t[np.minimum(k1, max(len(on_t) - 1, 0))] - ts, np.inf).astype(np.float32)
                    if len(on_t) else np.full(n, np.inf, np.float32))
    kd = np.searchsorted(det_t, ts, "right") - 1
    out["since_det"] = (np.where(kd >= 0, ts - det_t[np.maximum(kd, 0)], -1.0).astype(np.float32) if len(det_t)
                        else np.full(n, -1.0, np.float32))
    df = pd.DataFrame(out)
    df.insert(0, "cond", r["cond"])
    meta = {"cond": r["cond"], "oos": bool(r["oos"]), "volume": float(r["volume"]), "fee_rate": float(r["fee_rate"]),
            "delay": int(r["delay"]), "start": str(r["start"]), "n_orders": int(n), "inplay_usd": float(usd.sum()),
            "inplay_h": float((ts[-1] - ts[0]) / 3600), "n_onsets": int(len(on_t))}
    return df, meta


def stage_prints(workers: int) -> None:
    from src.tape import universe
    CACHE.mkdir(parents=True, exist_ok=True)
    u = universe()
    for split in ("IS", "OOS"):
        f = CACHE / f"orders_{split}.parquet"
        if f.exists():
            print(f"[prints] {f.name} exists, skipped")
            continue
        rows = u[u.oos == (split == "OOS")]
        if split == "OOS":
            log_oos("burned OOS raw tapes (data/raw/trades, 2,617 OOS matches) read to build the taker-order table "
                    "for the impact fit's stability check and the capacity re-run (non-blind, no parameter chosen)")
        recs = rows[["cond", "start", "end", "volume", "fee_rate", "delay", "oos"]].to_dict("records")
        t0 = time.time()
        parts, metas = [], []
        with ProcessPoolExecutor(workers) as ex:
            for df, m in ex.map(_orders_one, recs, chunksize=32):
                if df is not None:
                    parts.append(df)
                    metas.append(m)
        D = pd.concat(parts, ignore_index=True)
        D["cond"] = D.cond.astype("category")
        D.to_parquet(f, index=False)
        pd.DataFrame(metas).to_parquet(CACHE / f"matches_{split}.parquet", index=False)
        print(f"[prints] {split}: {len(D):,} orders in {len(metas):,} matches, {time.time() - t0:.0f} s")


# ============================================================================================ stage 2: live L2 book
def _l2_tokens() -> pd.DataFrame:
    """Singles tennis moneylines of the legacy recorder with outcome order and Gamma start (live_v2 clobmeta)."""
    import orjson
    sys.path.insert(0, str(ROOT / "research/v2/latency"))
    import load as L  # noqa: E402
    meta = L.load_meta()
    ml = meta[meta.smt == "moneyline"].drop_duplicates("tok")
    rows = {}
    for f in L2_TOKENS:
        with gzip.open(f, "rb") as fh:
            for line in fh:
                for tok, m in (orjson.loads(line).get("tokens") or {}).items():
                    if m.get("tag") == "tennis":
                        rows[tok] = m
    oi = dict(zip(ml.tok, ml.oi))
    st = dict(zip(ml.slug, ml.start_s))
    out = []
    for tok, m in rows.items():
        s = m["slug"]
        if "doubles" in s or not s.startswith(("atp-", "wta-", "itf-")) or tok not in oi or s not in st:
            continue
        out.append({"slug": s, "cond": m["cond"], "tok": tok, "oi": int(oi[tok]), "start_ms": float(st[s]) * 1000})
    T = pd.DataFrame(out)
    g = T.groupby("slug").oi.nunique()
    T = T[T.slug.isin(g[g == 2].index)]
    return T


def _read_l2(handle):
    import orjson
    for f in L2_FILES:
        try:
            with gzip.open(f, "rb") as fh:
                for line in fh:
                    try:
                        r = orjson.loads(line)
                    except orjson.JSONDecodeError:
                        continue
                    if r.get("rt", 0) >= CUT_MS:
                        break
                    handle(r)
        except EOFError:            # market_20261003_0946 ends without a gzip trailer (recorder restart at 10:03)
            continue


def _walk(levels, Q):
    """VWAP of the first Q shares of a sorted level list [(price, size)], nan if depth < Q."""
    rem, cost = Q, 0.0
    for px, sz in levels:
        take = min(rem, sz)
        cost += take * px
        rem -= take
        if rem <= 1e-9:
            return cost / Q
    return np.nan


def stage_l2() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    TK = _l2_tokens()
    tok0 = {r.tok: r.slug for r in TK[TK.oi == 0].itertuples()}
    tok1 = {r.tok: r.slug for r in TK[TK.oi == 1].itertuples()}
    start = dict(zip(TK.slug, TK.start_ms))
    # ---- pass 1: top of book (from the venue's own best_bid / best_ask fields) and trades
    top = {s: [] for s in start}
    trades = {s: [] for s in start}

    rec0 = {"t": np.inf}

    def h1(r):
        et = r.get("event_type")
        rt = r["rt"]
        if rt < rec0["t"]:
            rec0["t"] = rt
        if et == "price_change":
            for x in r.get("price_changes", []):
                s = tok0.get(x.get("asset_id"))
                if s is not None:
                    try:
                        top[s].append((rt, float(x.get("best_bid") or "nan"), float(x.get("best_ask") or "nan")))
                    except ValueError:
                        pass
        elif et == "best_bid_ask":
            s = tok0.get(r.get("asset_id"))
            if s is not None:
                top[s].append((rt, float(r.get("best_bid") or "nan"), float(r.get("best_ask") or "nan")))
        elif et == "book":
            s = tok0.get(r.get("asset_id"))
            if s is not None:
                b = [float(x["price"]) for x in r.get("bids", []) if float(x["size"]) > 0]
                a = [float(x["price"]) for x in r.get("asks", []) if float(x["size"]) > 0]
                top[s].append((rt, max(b) if b else np.nan, min(a) if a else np.nan))
        elif et == "last_trade_price":
            a = r.get("asset_id")
            s0, s1 = tok0.get(a), tok1.get(a)
            if s0 is None and s1 is None:
                return
            try:
                px, sz = float(r.get("price") or "nan"), float(r.get("size") or 0)
            except ValueError:
                return
            buy = (r.get("side") == "BUY")
            if s0 is not None:
                trades[s0].append((rt, px, sz, 1 if buy else -1, 0))
            else:
                trades[s1].append((rt, 1 - px, sz, -1 if buy else 1, 1))

    t0 = time.time()
    _read_l2(h1)
    print(f"[l2] pass 1 {time.time() - t0:.0f} s")
    # reprices from the event-level mid (spread <= 5c), in play only
    reps, tr_rows, keep = [], [], []
    dup_stats = {"raw": 0, "dropped": 0}
    for s in start:
        a = np.array(top[s], float) if top[s] else np.empty((0, 3))
        if len(a) < 50:
            continue
        a = a[np.argsort(a[:, 0], kind="stable")]
        ok = np.isfinite(a[:, 1]) & np.isfinite(a[:, 2]) & (a[:, 1] > 0) & (a[:, 2] < 1) & (a[:, 2] > a[:, 1]) & \
            (a[:, 2] - a[:, 1] <= 0.05)
        t, m = a[ok, 0], (a[ok, 1] + a[ok, 2]) / 2
        inp = t >= start[s]
        if inp.sum() < 50:
            continue
        keep.append(s)
        last = -1e18
        for i in np.flatnonzero(inp):
            if t[i] - last < 20_000:
                continue
            j = np.searchsorted(t, t[i] - 2000, "right") - 1
            if j < 0 or abs(m[i] - m[j]) < REP_D:
                continue
            ref = m[j]
            k = np.searchsorted(t, t[i] + 3000, "right") - 1
            if t[i] + 3000 >= CUT_MS:
                continue
            m_new = m[k]
            D = m_new - ref
            if abs(D) < REP_D or np.sign(D) != np.sign(m[i] - ref):
                continue
            w = np.flatnonzero((t >= t[i] - 2000) & (t <= t[i]) & ((m - ref) * np.sign(D) >= abs(D) / 2))
            t_half = t[w[0]] if len(w) else t[i]
            reps.append({"slug": s, "t_rep": t_half, "dir": int(np.sign(D)), "m_ref": ref, "m_new": m_new,
                         "D": abs(D), "p_mid": (ref + m_new) / 2})
            last = t[i]
        # trades: drop the mirror copy of a trade (same size and outcome-0 price within 100 ms on the other token)
        x = sorted(trades[s])
        dup_stats["raw"] += len(x)
        kept = []
        for rec in x:
            rt, p0, sz, d, src = rec
            dup = False
            for q in reversed(kept[-6:]):
                if rt - q[0] > 100:
                    break
                if abs(q[2] - sz) < 1e-6 and abs(q[1] - p0) < 1e-6 and q[4] != src:
                    dup = True
                    break
            if dup:
                dup_stats["dropped"] += 1
                continue
            kept.append(rec)
        tr_rows += [{"slug": s, "rt": r_[0], "p0": r_[1], "sh": r_[2], "d": r_[3], "src": r_[4]} for r_ in kept]
    R = pd.DataFrame(reps)
    TR = pd.DataFrame(tr_rows)
    print(f"[l2] {len(keep)} matches in play, {len(R)} reprices >= {REP_D:.2f}, {len(TR)} trades "
          f"({dup_stats['dropped']} mirror copies dropped)")
    # ---- pass 2: replay tok0's full book; snapshot on a 2 s grid in play and around every reprice
    queries = {}
    for s in keep:
        g = np.arange(math.ceil(start[s] / GRID_MS) * GRID_MS, CUT_MS, GRID_MS, dtype=float)
        qs = [(tq, "grid", -1, 0) for tq in g]
        if len(R):
            for i, r in R[R.slug == s].iterrows():
                qs += [(r.t_rep + off, "rep", i, off) for off in SNAP_OFF]
        queries[s] = sorted(qs)
    ptr = {s: 0 for s in keep}
    books = {s: ({}, {}) for s in keep}
    snaps = []
    chk = {"n": 0, "bid_mismatch": 0, "ask_mismatch": 0}
    keepset = set(keep)

    def snap(s, q):
        tq, kind, i, off = q
        bids, asks = books[s]
        bl = sorted(bids.items(), reverse=True)
        al = sorted(asks.items())
        if not bl or not al:
            return
        bb, ba = bl[0][0], al[0][0]
        mid = (bb + ba) / 2
        row = {"slug": s, "t": tq, "kind": kind, "rep": i, "off": off, "bb": bb, "ba": ba, "mid": mid}
        for Q in QGRID:
            row[f"cb{Q}"] = _walk(al, Q) - mid
            row[f"cs{Q}"] = mid - _walk(bl, Q)
        for c in (1, 2, 5):
            row[f"db{c}"] = sum(sz for px, sz in al if px <= mid + c / 100 + 1e-9)
            row[f"ds{c}"] = sum(sz for px, sz in bl if px >= mid - c / 100 - 1e-9)
        if kind == "rep":
            r = R.loc[i]
            if r.dir > 0:
                lv = [(px, sz) for px, sz in al if px < r.m_new]
                row["stale_sh"] = sum(sz for _, sz in lv)
                row["stale_edge_usd"] = sum(sz * (r.m_new - px) for px, sz in lv)
            else:
                lv = [(px, sz) for px, sz in bl if px > r.m_new]
                row["stale_sh"] = sum(sz for _, sz in lv)
                row["stale_edge_usd"] = sum(sz * (px - r.m_new) for px, sz in lv)
        snaps.append(row)

    def advance(s, rt):
        qs, i = queries[s], ptr[s]
        while i < len(qs) and qs[i][0] < rt:
            snap(s, qs[i])
            i += 1
        ptr[s] = i

    def h2(r):
        et = r.get("event_type")
        rt = r["rt"]
        if et == "price_change":
            for x in r.get("price_changes", []):
                s = tok0.get(x.get("asset_id"))
                if s is None or s not in keepset:
                    continue
                advance(s, rt)
                bids, asks = books[s]
                px, sz = float(x["price"]), float(x["size"])
                d = bids if x.get("side") == "BUY" else asks
                if sz > 0:
                    d[px] = sz
                else:
                    d.pop(px, None)
                try:
                    vb, va = float(x.get("best_bid") or "nan"), float(x.get("best_ask") or "nan")
                except ValueError:
                    continue
                if np.isfinite(vb) and np.isfinite(va) and vb > 0 and va < 1:
                    chk["n"] += 1
                    chk["bid_mismatch"] += int(abs(max(bids, default=0.0) - vb) > 1e-9)
                    chk["ask_mismatch"] += int(abs(min(asks, default=1.0) - va) > 1e-9)
        elif et == "book":
            s = tok0.get(r.get("asset_id"))
            if s is None or s not in keepset:
                return
            advance(s, rt)
            books[s] = ({float(x["price"]): float(x["size"]) for x in r.get("bids", []) if float(x["size"]) > 0},
                        {float(x["price"]): float(x["size"]) for x in r.get("asks", []) if float(x["size"]) > 0})

    t0 = time.time()
    _read_l2(h2)
    for s in keep:
        advance(s, CUT_MS)
    print(f"[l2] pass 2 {time.time() - t0:.0f} s, {len(snaps):,} snapshots; venue best-quote check "
          f"{chk['bid_mismatch']}/{chk['n']} bid and {chk['ask_mismatch']}/{chk['n']} ask mismatches")
    S = pd.DataFrame(snaps)
    S.to_parquet(CACHE / "l2_snaps.parquet", index=False)
    R.to_parquet(CACHE / "l2_reprices.parquet")
    TR.to_parquet(CACHE / "l2_trades.parquet", index=False)
    TK.to_parquet(CACHE / "l2_tokens.parquet", index=False)
    (CACHE / "l2_meta.json").write_text(json.dumps({"matches": keep, "dup": dup_stats, "best_quote_check": chk,
                                                    "rec_start_ms": float(rec0["t"]),
                                                    "cut_utc": "2026-10-03T14:00:00Z", "files": L2_FILES}, indent=1))


# ============================================================================================ stage 3: fits
def _buckets(M: pd.DataFrame, edges=None):
    if edges is None:
        edges = np.quantile(M.volume.to_numpy(float), [0.2, 0.4, 0.6, 0.8])
    return np.searchsorted(edges, M.volume.to_numpy(float), "right"), edges


def _load_orders(split: str, edges=None):
    D = pd.read_parquet(CACHE / f"orders_{split}.parquet")
    M = pd.read_parquet(CACHE / f"matches_{split}.parquet")
    b, edges = _buckets(M, edges)
    M["bucket"] = b
    D["bucket"] = D.cond.map(dict(zip(M.cond, M.bucket))).astype(np.int8)
    D["mcode"] = D.cond.cat.codes.astype(np.int32)
    return D, M, edges


def _temp_sample(D: pd.DataFrame) -> pd.DataFrame:
    m = (np.isfinite(D.m_pre) & (D.sp_pre <= 0.05) & (D.p >= 0.05) & (D.p <= 0.95) & (D.Q >= 1)).to_numpy()
    x = D.loc[m, ["mcode", "bucket", "Q"]].copy()
    x["y"] = np.clip(100 * D.d.to_numpy()[m] * (D.p.to_numpy()[m] - D.m_pre.to_numpy()[m]), -20, 20)
    return x


def _suff_stats(codes, y, X: np.ndarray, ncode: int) -> np.ndarray:
    """Per-match sufficient statistics for OLS y = a + k x (X: n x K candidate regressors) -> (ncode, K, 6):
    n, sum x, sum x^2, sum y, sum x y, sum y^2."""
    K = X.shape[1]
    S = np.zeros((ncode, K, 6))
    nn = np.bincount(codes, minlength=ncode).astype(float)
    sy = np.bincount(codes, weights=y, minlength=ncode)
    syy = np.bincount(codes, weights=y * y, minlength=ncode)
    for k in range(K):
        x = X[:, k]
        S[:, k, 0] = nn
        S[:, k, 1] = np.bincount(codes, weights=x, minlength=ncode)
        S[:, k, 2] = np.bincount(codes, weights=x * x, minlength=ncode)
        S[:, k, 3] = sy
        S[:, k, 4] = np.bincount(codes, weights=x * y, minlength=ncode)
        S[:, k, 5] = syy
    return S


def _ols(s: np.ndarray):
    """OLS from summed stats (..., 6) -> a, k, sse."""
    n, sx, sxx, sy, sxy, syy = (s[..., i] for i in range(6))
    den = n * sxx - sx * sx
    k = np.where(den > 0, (n * sxy - sx * sy) / np.where(den > 0, den, 1), np.nan)
    a = (sy - k * sx) / np.maximum(n, 1)
    sse = syy - 2 * a * sy - 2 * k * sxy + a * a * n + 2 * a * k * sx + k * k * sxx
    return a, k, sse


def fit_temporary(D: pd.DataFrame, nb: int, rng, boot: bool = True) -> dict:
    x = _temp_sample(D)
    codes = x.mcode.to_numpy()
    ncode = int(D.mcode.max()) + 1
    mb = np.full(ncode, -1)
    mb[codes] = x.bucket.to_numpy()
    X = np.column_stack([(x.Q.to_numpy() / QREF) ** dl for dl in DELTAS])
    S = _suff_stats(codes, x.y.to_numpy(float), X, ncode)       # (ncode, nD, 6)
    present = np.flatnonzero(S[:, 0, 0] > 0)

    def solve(sel):
        sse_tot = np.zeros(len(DELTAS))
        per = []
        for b in range(nb):
            mm = sel[mb[sel] == b]
            s = S[mm].sum(0)                                     # (nD, 6)
            a, k, sse = _ols(s)
            sse_tot += sse
            per.append((a, k))
        j = int(np.nanargmin(sse_tot))
        return j, [(float(per[b][0][j]), float(per[b][1][j])) for b in range(nb)]

    j, ab = solve(present)
    out = {"delta": float(DELTAS[j]), "n_orders": int(len(x)), "n_matches": int(len(present)),
           "a_c": [r[0] for r in ab], "k_c": [r[1] for r in ab]}
    if boot:
        bd, bk, ba = [], [], []
        groups = [present[mb[present] == b] for b in range(nb)]
        for _ in range(NBOOT):
            sel = np.concatenate([g[rng.integers(0, len(g), len(g))] for g in groups])
            jj, abb = solve(sel)
            bd.append(DELTAS[jj])
            bk.append([r[1] for r in abb])
            ba.append([r[0] for r in abb])
            # k at the point delta too (for a CI of k_b with delta fixed)
        bk, ba = np.array(bk), np.array(ba)
        out["delta_ci95"] = [float(np.percentile(bd, 2.5)), float(np.percentile(bd, 97.5))]
        # k_b CI with delta held at its point value (the model applied in the capacity re-run)
        kfix = []
        for _ in range(NBOOT):
            sel = np.concatenate([g[rng.integers(0, len(g), len(g))] for g in groups])
            kfix.append([float(_ols(S[sel[mb[sel] == b], j].sum(0))[1]) for b in range(nb)])
        kfix = np.array(kfix)
        out["k_c_ci95"] = [[float(np.percentile(kfix[:, b], 2.5)), float(np.percentile(kfix[:, b], 97.5))]
                           for b in range(nb)]
    # binned means with match-clustered CIs (figure + table)
    x["qb"] = np.searchsorted(QBINS, x.Q.to_numpy(), "right") - 1
    rows = []
    for b in range(nb):
        for qb in range(len(QBINS) - 1):
            g = x[(x.bucket == b) & (x.qb == qb)]
            if len(g) < 50:
                continue
            pm = g.groupby("mcode").y.agg(["sum", "size"])
            sm, nn = pm["sum"].to_numpy(), pm["size"].to_numpy()
            ci = [np.nan, np.nan]
            if boot and len(pm) >= 10:
                ii = rng.integers(0, len(pm), (NBOOT, len(pm)))
                bs = sm[ii].sum(1) / nn[ii].sum(1)
                ci = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
            rows.append({"bucket": b, "q_lo": QBINS[qb], "q_hi": QBINS[qb + 1], "q_median": float(g.Q.median()),
                         "n": int(len(g)), "n_matches": int(len(pm)), "mean_c": float(sm.sum() / nn.sum()),
                         "ci95_c": ci})
    out["bins"] = rows
    return out


def fit_permanent(D: pd.DataFrame, nb: int, rng, boot: bool = True) -> dict:
    base = (np.isfinite(D.m_pre) & (D.sp_pre <= 0.05) & (D.p >= 0.05) & (D.p <= 0.95) & (D.Q >= 1) &
            (D.Q <= 20000) & ((D.since < 0) | (D.since > 60))).to_numpy()
    ncode = int(D.mcode.max()) + 1
    out = {}
    for h in H:
        m = base & np.isfinite(D[f"m{h}"].to_numpy()) & (D.until.to_numpy() > h + 10)
        codes = D.mcode.to_numpy()[m]
        y = np.clip(100 * D.d.to_numpy()[m] * (D[f"m{h}"].to_numpy()[m] - D.m_pre.to_numpy()[m]), -30, 30)
        q = D.Q.to_numpy()[m] / QREF
        X = np.column_stack([q, np.sqrt(q)])
        S = _suff_stats(codes, y.astype(float), X, ncode)
        mb = np.full(ncode, -1)
        mb[codes] = D.bucket.to_numpy()[m]
        present = np.flatnonzero(S[:, 0, 0] > 0)
        groups = [present[mb[present] == b] for b in range(nb)]
        res = {"n_orders": int(m.sum()), "n_matches": int(len(present)), "lambda_c_per_1k": [], "sqrt_Y_c": [],
               "alpha_c": [], "lambda_ci95": [], "sqrt_ci95": []}
        for b in range(nb):
            s = S[groups[b]].sum(0)
            a, k, _ = _ols(s)
            res["alpha_c"].append(float(a[0]))
            res["lambda_c_per_1k"].append(float(k[0]))
            res["sqrt_Y_c"].append(float(k[1]))
            if boot:
                g = groups[b]
                bl, bs = [], []
                for _ in range(NBOOT):
                    ss = S[g[rng.integers(0, len(g), len(g))]].sum(0)
                    _, kk, _ = _ols(ss)
                    bl.append(kk[0])
                    bs.append(kk[1])
                res["lambda_ci95"].append([float(np.nanpercentile(bl, 2.5)), float(np.nanpercentile(bl, 97.5))])
                res["sqrt_ci95"].append([float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))])
        out[str(h)] = res
    return out


def l2_analysis(rng) -> dict:
    S = pd.read_parquet(CACHE / "l2_snaps.parquet")
    R = pd.read_parquet(CACHE / "l2_reprices.parquet")
    TR = pd.read_parquet(CACHE / "l2_trades.parquet")
    meta = json.loads((CACHE / "l2_meta.json").read_text())
    out = {"cut_utc": meta["cut_utc"], "files": meta["files"], "n_matches": len(meta["matches"]),
           "matches": meta["matches"], "mirror_trades_dropped": meta["dup"], "best_quote_check": meta["best_quote_check"],
           "n_reprices": int(len(R)), "n_trades": int(len(TR))}
    G = S[S.kind == "grid"].copy()
    G = G[(G.ba - G.bb <= 0.05) & (G.mid >= 0.05) & (G.mid <= 0.95)]
    # quiet = >= 30 s from any reprice of the same match
    G["quiet"] = True
    for s, g in R.groupby("slug"):
        tt = np.sort(g.t_rep.to_numpy())
        ix = G.slug == s
        t = G.loc[ix, "t"].to_numpy()
        j = np.searchsorted(tt, t)
        dl = np.where(j > 0, t - tt[np.maximum(j - 1, 0)], np.inf)
        dr = np.where(j < len(tt), tt[np.minimum(j, len(tt) - 1)] - t, np.inf)
        G.loc[ix, "quiet"] = (dl >= 30_000) & (dr >= 30_000)
    Gq = G[G.quiet]
    # side-averaged cost (buy and sell) per snapshot, cents
    curve_q = {}
    for Q in QGRID:
        v = 100 * np.nanmean(np.column_stack([Gq[f"cb{Q}"], Gq[f"cs{Q}"]]), axis=1)
        curve_q[str(Q)] = {"mean_c": float(np.nanmean(v)), "median_c": float(np.nanmedian(v)),
                           "share_fillable": float(np.isfinite(v).mean())}
    out["quiet_book_walk"] = {"n_snapshots": int(len(Gq)), "n_matches": int(Gq.slug.nunique()), "by_Q": curve_q,
                              "half_spread_median_c": float(100 * np.median((Gq.ba - Gq.bb) / 2)),
                              "depth_within_1c_median_sh": float(np.median((Gq.db1 + Gq.ds1) / 2)),
                              "depth_within_5c_median_sh": float(np.median((Gq.db5 + Gq.ds5) / 2))}
    # ---- book-walk model (amendment A1): per live match in-play taker $/h, depth within 2c, quiet book-walk cost
    TK = pd.read_parquet(CACHE / "l2_tokens.parquet")
    st = TK.drop_duplicates("slug").set_index("slug").start_ms
    pm_rows = []
    for s_, g in Gq.groupby("slug"):
        t0_ = max(st[s_], meta["rec_start_ms"])
        t = TR[(TR.slug == s_) & (TR.rt >= t0_)]
        t1_ = float(t.rt.max()) if len(t) else t0_
        hrs = max((t1_ - t0_) / 3.6e6, 0.25)
        usd = float((t.sh * np.where(t.d > 0, t.p0, 1 - t.p0)).sum())
        r = {"slug": s_, "inplay_h_recorded": hrs, "usd_per_h": usd / hrs, "n_trades": int(len(t)),
             "depth2c_median_sh": float(np.median((g.db2 + g.ds2) / 2)), "n_snapshots": int(len(g))}
        for Q in QGRID:
            v = 100 * np.r_[g[f"cb{Q}"].to_numpy(), g[f"cs{Q}"].to_numpy()]
            r[f"cost_{Q}_c"] = float(np.nanmean(v)) if np.isfinite(v).any() else np.nan
            r[f"fill_{Q}"] = float(np.isfinite(v).mean())
        pm_rows.append(r)
    PM = pd.DataFrame(pm_rows)
    ok = (PM.usd_per_h > 0) & (PM.depth2c_median_sh > 0)
    beta = float(np.polyfit(np.log(PM.usd_per_h[ok]), np.log(PM.depth2c_median_sh[ok]), 1)[0])
    tour = PM[PM.slug.str.startswith(("atp-", "wta-")) & (PM.usd_per_h >= 10_000)]
    out["bookwalk_model"] = {
        "definition": "amendment A1 (post hoc): quiet book-walk cost of the live ATP/WTA matches with >= $10k/h, depth "
                      "scaled to a historical match by (U_m / U_ref)^beta, never deeper than the reference",
        "Q": list(QGRID), "C_tour_c": [float(tour[f"cost_{Q}_c"].mean()) for Q in QGRID],
        "fill_share_tour": [float(tour[f"fill_{Q}"].mean()) for Q in QGRID],
        "U_ref_usd_per_h": float(tour.usd_per_h.median()), "beta_fit": beta, "beta": float(np.clip(beta, 0.5, 1.5)),
        "n_tour_matches": int(len(tour)), "tour_matches": tour.slug.tolist(), "n_live_matches_in_beta_fit": int(ok.sum()),
        "per_match": PM.round(4).to_dict("records")}
    # post-reprice snapshots (+1..+3 s), with-move side
    P = S[(S.kind == "rep") & S.off.isin([1000, 2000, 3000])].merge(
        R[["dir", "slug"]].reset_index().rename(columns={"index": "rep"}), on=["rep", "slug"])
    P = P[(P.ba - P.bb <= 0.10)]
    mult = {}
    per_match = []
    for Q in (100, 250, 500, 1000, 2500):
        pv = 100 * np.where(P.dir > 0, P[f"cb{Q}"], P[f"cs{Q}"])
        qv = 100 * np.nanmean(np.column_stack([Gq[f"cb{Q}"], Gq[f"cs{Q}"]]), axis=1)
        a = pd.DataFrame({"slug": P.slug.to_numpy(), "v": pv}).dropna().groupby("slug").v.agg(["sum", "size"])
        b = pd.DataFrame({"slug": Gq.slug.to_numpy(), "v": qv}).dropna().groupby("slug").v.agg(["sum", "size"])
        j = a.index.intersection(b.index)
        a, b = a.loc[j], b.loc[j]
        ratio = (a["sum"].sum() / a["size"].sum()) / (b["sum"].sum() / b["size"].sum())
        ii = rng.integers(0, len(j), (NBOOT, len(j)))
        bs = (a["sum"].to_numpy()[ii].sum(1) / a["size"].to_numpy()[ii].sum(1)) / \
             (b["sum"].to_numpy()[ii].sum(1) / b["size"].to_numpy()[ii].sum(1))
        mult[str(Q)] = {"post_mean_c": float(a["sum"].sum() / a["size"].sum()),
                        "quiet_mean_c": float(b["sum"].sum() / b["size"].sum()), "ratio": float(ratio),
                        "ratio_ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                        "n_matches": int(len(j))}
    # pooled multiplier over Q = 100..2,500 (plan: M = max(1, pooled ratio))
    num = sum(mult[k]["post_mean_c"] for k in mult)
    den = sum(mult[k]["quiet_mean_c"] for k in mult)
    rr = [mult[k]["ratio_ci95"] for k in mult]
    out["post_jump_multiplier"] = {"by_Q": mult, "pooled_ratio": float(num / den),
                                   "pooled_ratio_ci95_from_Q_cells": [float(min(r[0] for r in rr)),
                                                                     float(max(r[1] for r in rr))],
                                   "M_used": float(max(1.0, num / den)),
                                   "M_conservative": float(max(1.0, max(r[1] for r in rr)))}
    # ---- phi: stale depth vs with-move takes at stale prices
    rep = S[(S.kind == "rep")].pivot_table(index="rep", columns="off", values="stale_sh", aggfunc="first")
    Rr = R.copy()
    rows = []
    trs = {s: g.sort_values("rt") for s, g in TR.groupby("slug")}
    for i, r in Rr.iterrows():
        if i not in rep.index:
            continue
        g = trs.get(r.slug)
        row = {"rep": i, "slug": r.slug, "D": r.D, "dir": r.dir}
        for tau, off in zip(TAUS, (-2000, -1000, -250)):
            st = rep.loc[i].get(off, np.nan)
            if g is None:
                took = 0.0
            else:
                w = g[(g.rt >= r.t_rep - tau * 1000) & (g.rt <= r.t_rep + 500) & (g.d == r.dir)]
                w = w[(w.p0 < r.m_new) if r.dir > 0 else (w.p0 > r.m_new)]
                took = float(w.sh.sum())
            row[f"stale_{tau:g}"] = st
            row[f"took_{tau:g}"] = took
        row["stale_post"] = rep.loc[i].get(500, np.nan)
        rows.append(row)
    PH = pd.DataFrame(rows)
    out["phi_live_reprices"] = phi_summary(PH, rng, "slug")
    out["phi_live_reprices"]["definition"] = ("book reprices >= 3c (mid vs 2 s earlier) in play, 2026-10-03 before "
                                              "14:00 UTC; stale = shares at prices better than the mid 3 s after the "
                                              "reprice on the with-move side; took = deduplicated with-move taker shares "
                                              "printed at stale prices from t_rep - tau to t_rep + 0.5 s")
    PH.to_parquet(CACHE / "l2_phi_events.parquet", index=False)
    return out


def phi_summary(PH: pd.DataFrame, rng, cl: str) -> dict:
    out = {"n_events": int(len(PH)), "n_matches": int(PH[cl].nunique())}
    for tau in TAUS:
        st, tk = PH[f"stale_{tau:g}"].to_numpy(float), PH[f"took_{tau:g}"].to_numpy(float)
        ok = np.isfinite(st) & (st > 0)
        x = PH[ok]
        st, tk = st[ok], np.minimum(tk[ok], st[ok])
        per = 1 - tk / st
        g = pd.DataFrame({"c": x[cl].to_numpy(), "st": st, "tk": tk}).groupby("c").agg(st=("st", "sum"), tk=("tk", "sum"))
        ii = rng.integers(0, len(g), (NBOOT, len(g)))
        bs = 1 - g.tk.to_numpy()[ii].sum(1) / g.st.to_numpy()[ii].sum(1)
        out[f"tau_{tau:g}s"] = {"n_events_with_stale_depth": int(ok.sum()),
                                "share_events_with_stale_depth": float(ok.mean()) if len(ok) else np.nan,
                                "stale_sh_median": float(np.median(st)), "stale_sh_mean": float(np.mean(st)),
                                "took_share_pooled": float(tk.sum() / st.sum()),
                                "phi_lo_pooled": float(1 - tk.sum() / st.sum()),
                                "phi_lo_ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                                "phi_lo_event_median": float(np.median(per)),
                                "share_events_phi_lo_below_0.5": float((per < 0.5).mean())}
    return out


def phi_official(rng) -> dict:
    """The latency study's officially stamped points (research/v2/latency/out; recorded before 12:45 UTC)."""
    d = pd.read_csv(ROOT / "research/v2/latency/out/stale_depth.csv")
    t = pd.read_csv(ROOT / "research/v2/latency/out/trades_around_reprice.csv")
    t = t.sort_values(["slug", "n", "dt_s"]).reset_index(drop=True)
    # mirror copies: same point, size and outcome-0 price within 0.1 s (the trade is reported on both tokens)
    keep = np.ones(len(t), bool)
    prev = {}
    for i, r in enumerate(t.itertuples()):
        k = (r.slug, r.n, round(r.p0, 6), round(r.sh, 6))
        if k in prev and r.dt_s - prev[k] <= 0.1:
            keep[i] = False
        else:
            prev[k] = r.dt_s
    nd = int((~keep).sum())
    t = t[keep]
    rows = []
    for r in d.itertuples():
        w = t[(t.slug == r.slug) & (t.n == r.n) & t.with_move & (t.edge_vs_new_mid > 0)]
        row = {"slug": r.slug, "n": r.n, "D": r.D}
        for tau, col in zip(TAUS, ("sh_pre2s", "sh_pre1s", "sh_pre")):
            row[f"stale_{tau:g}"] = getattr(r, col)
            row[f"took_{tau:g}"] = float(w[(w.dt_s >= -tau) & (w.dt_s <= 0.5)].sh.sum())
        row["stale_post"] = r.sh_post
        rows.append(row)
    PH = pd.DataFrame(rows)
    out = {"all": phi_summary(PH, rng, "slug"), "D_ge_3c": phi_summary(PH[PH.D >= 0.03 - 1e-9], rng, "slug"),
           "mirror_trades_dropped": nd,
           "source": "research/v2/latency/out/stale_depth.csv + trades_around_reprice.csv (482 points, 9 WTA matches, "
                     "official point stamps, recorded 2026-10-03 before 12:45 UTC)"}
    return out


def stage_fit() -> dict:
    rng = np.random.default_rng(SEED)
    DI, MI, edges = _load_orders("IS")
    nb = len(edges) + 1
    out = {"buckets": {"by": "match Gamma volume (universe.volume), quintiles of IS matches with orders",
                       "edges_usd": [float(e) for e in edges],
                       "n_matches": [int((MI.bucket == b).sum()) for b in range(nb)],
                       "median_volume_usd": [float(MI.volume[MI.bucket == b].median()) for b in range(nb)]},
           "data": {"IS": {"n_orders": int(len(DI)), "n_matches": int(len(MI))}}}
    t0 = time.time()
    out["temporary_IS"] = fit_temporary(DI, nb, rng)
    out["permanent_IS"] = fit_permanent(DI, nb, rng)
    print(f"[fit] IS done {time.time() - t0:.0f} s")
    del DI
    log_oos("burned OOS taker-order table (results/liquidity/cache/orders_OOS.parquet, built from OOS raw tapes) read "
            "to refit the impact model as a stability check (non-blind, no parameter chosen)")
    DO, MO, _ = _load_orders("OOS", edges)
    out["data"]["OOS"] = {"n_orders": int(len(DO)), "n_matches": int(len(MO))}
    out["temporary_OOS"] = fit_temporary(DO, nb, rng)
    out["permanent_OOS"] = fit_permanent(DO, nb, rng)
    del DO
    out["l2"] = l2_analysis(rng)
    out["phi_official_points"] = phi_official(rng)
    # the model applied in the capacity re-run
    tmp, per = out["temporary_IS"], out["permanent_IS"]
    lam = {h: [max(0.0, v) for v in per[str(h)]["lambda_c_per_1k"]] for h in H}
    lam_hi = {h: [max(0.0, v[1]) for v in per[str(h)]["lambda_ci95"]] for h in H}
    live = out["l2"]["phi_live_reprices"]
    off = out["phi_official_points"]["D_ge_3c"]
    cand = [(live[f"tau_{t:g}s"]["phi_lo_pooled"], live[f"tau_{t:g}s"]["phi_lo_ci95"][0], f"live reprices, tau {t:g} s")
            for t in TAUS] + \
           [(off[f"tau_{t:g}s"]["phi_lo_pooled"], off[f"tau_{t:g}s"]["phi_lo_ci95"][0], f"official points D>=3c, tau {t:g} s")
            for t in TAUS]
    pt = min(cand, key=lambda c: c[0])
    lo = min(cand, key=lambda c: c[1])
    out["model"] = {"delta": tmp["delta"], "k_c": tmp["k_c"], "k_c_hi": [c[1] for c in tmp["k_c_ci95"]],
                    "a_c": tmp["a_c"], "lambda_c_per_1k": {str(h): lam[h] for h in H},
                    "lambda_c_per_1k_hi": {str(h): lam_hi[h] for h in H},
                    "M": out["l2"]["post_jump_multiplier"]["M_used"],
                    "M_hi": out["l2"]["post_jump_multiplier"]["M_conservative"],
                    "phi_measured": pt[0], "phi_measured_from": pt[2],
                    "phi_measured_lo95": lo[1], "phi_measured_lo95_from": lo[2],
                    "phi_used": float(min(0.5, lo[1])),
                    "bucket_edges_usd": out["buckets"]["edges_usd"],
                    "bookwalk": {k: out["l2"]["bookwalk_model"][k] for k in ("Q", "C_tour_c", "U_ref_usd_per_h", "beta")}}
    (CACHE / "fit.json").write_text(json.dumps(out, indent=1, default=float))
    print("[fit] model:", json.dumps(out["model"], default=float)[:1500])
    return out


# ============================================================================================ stage 4: capacity
_CS = {}


def _cs():
    if not _CS:
        from scripts import capacity_study as CS
        _CS["CS"] = CS
    return _CS["CS"]


def lam_at(lag_s: np.ndarray, lam_row: np.ndarray) -> np.ndarray:
    """lambda (c per 1k shares) at lag (s), per trade: linear in log time between H, lambda(5) below, flat beyond."""
    lh = np.log(np.array(H, float))
    x = np.log(np.clip(lag_s, H[0], H[-1]))
    j = np.clip(np.searchsorted(lh, x, "right") - 1, 0, len(H) - 2)
    w = (x - lh[j]) / (lh[j + 1] - lh[j])
    ar = np.arange(len(x))
    return lam_row[ar, j] + (lam_row[ar, j + 1] - lam_row[ar, j]) * w


def carry_cost(cond: np.ndarray, ts: np.ndarray, z: np.ndarray, lam_tab: np.ndarray, bucket: np.ndarray) -> np.ndarray:
    """Per trade (rows sorted by cond, ts): displacement of the outcome-0 price (price units) left by our own earlier
    trades in the same match, sum_{j<i} z_j lambda_b(t_i - t_j) / 1000 / 100; z = signed outcome-0 shares."""
    n = len(cond)
    out = np.zeros(n)
    if n == 0:
        return out
    codes = np.unique(cond, return_inverse=True)[1]
    first = np.r_[0, np.flatnonzero(np.diff(codes)) + 1]
    pos = np.arange(n) - np.repeat(first, np.diff(np.r_[first, n]))
    lam_row = lam_tab[bucket]                                   # (n, len(H)) c per 1k shares
    for r in range(1, int(pos.max()) + 1):
        i = np.flatnonzero(pos >= r)
        j = i - r
        lag = ts[i] - ts[j]
        out[i] += z[j] * lam_at(lag, lam_row[i]) / QREF / 100.0
    return out


def temp_extra(h: np.ndarray, s: np.ndarray, k_c: np.ndarray, delta: float, how: str) -> np.ndarray:
    """Extra price paid per share vs the copied print (price units). k_c in cents."""
    k = k_c / 100.0
    h = np.maximum(h, 0.0)
    if how == "alongside":
        return k * (((h + s) / QREF) ** delta - (h / QREF) ** delta)
    tc = lambda x: x * (x / QREF) ** delta  # noqa: E731
    return k * ((tc(h + s) - tc(h)) / np.maximum(s, 1e-12) - (h / QREF) ** delta)


def bw_cost_c(Qs: np.ndarray, bw: dict) -> np.ndarray:
    """Live tour book-walk cost (cents) at Q shares: linear in log Q on the grid, C(10) below, linear in Q beyond."""
    Qg, c = np.array(bw["Q"], float), np.array(bw["C_tour_c"], float)
    y = np.interp(np.log(np.clip(Qs, Qg[0], None)), np.log(Qg), c)
    slope = (c[-1] - c[-2]) / (Qg[-1] - Qg[-2])
    return np.where(Qs > Qg[-1], c[-1] + slope * (Qs - Qg[-1]), y)


def _inplay_rate(conds) -> np.ndarray:
    if "rate" not in _CS:
        M = pd.concat([pd.read_parquet(CACHE / f"matches_{s}.parquet") for s in ("IS", "OOS")])
        _CS["rate"] = dict(zip(M.cond, M.inplay_usd / np.maximum(M.inplay_h, 0.25)))
    return np.array([_CS["rate"].get(c, np.nan) for c in conds], float)


def _vol_bucket(conds, edges) -> np.ndarray:
    from src.tape import universe
    if "vol" not in _CS:
        u = universe()
        _CS["vol"] = dict(zip(u.cond, u.volume))
    v = np.array([_CS["vol"].get(c, np.nan) for c in conds], float)
    return np.searchsorted(np.asarray(edges, float), np.nan_to_num(v, nan=0.0), "right")


def apply_impact_v2(tr: pd.DataFrame, model: dict, variant: str) -> pd.DataFrame:
    if variant == "none" or tr.empty:
        return tr
    tr = tr.sort_values(["cond", "ts"], kind="stable").copy()
    b = _vol_bucket(tr.cond.to_numpy(), model["bucket_edges_usd"])
    cons = variant == "conservative"
    k = np.asarray(model["k_c_hi"] if cons else model["k_c"], float)[b]
    M = model["M_hi"] if cons else model["M"]
    lam_key = "lambda_c_per_1k_hi" if cons else "lambda_c_per_1k"
    lam_tab = np.array([[model[lam_key][str(h)][bb] for h in H] for bb in range(len(model["k_c"]))], float)
    s = tr.shares.to_numpy(float)
    d = tr.dir.to_numpy(float)
    h = np.maximum(tr.their_shares.to_numpy(float), 0.0)
    if variant == "bookwalk":
        bw = model["bookwalk"]
        U = _inplay_rate(tr.cond.to_numpy())
        sm = np.maximum(1.0, (bw["U_ref_usd_per_h"] / np.where(np.isfinite(U) & (U > 0), U, 1.0)) ** bw["beta"])
        e_t = M * (bw_cost_c(sm * (h + s), bw) - bw_cost_c(sm * h, bw)) / 100.0
    else:
        e_t = M * temp_extra(h, s, k, model["delta"], "behind" if cons else "alongside")
    disp = carry_cost(tr.cond.to_numpy(), tr.ts.to_numpy(float), d * s, lam_tab, b)
    e_c = d * disp                                               # our token's price is pushed by d * displacement
    if cons:
        e_c = np.maximum(e_c, 0.0)                               # A1: no credit for favourable displacement
    q0 = tr.q.to_numpy(float)
    e = e_t + e_c
    q1 = np.clip(q0 + e, 0.01, 0.99)
    e = q1 - q0
    rate = tr.rate.to_numpy(float)
    dfee = rate * (q1 * (1 - q1) - q0 * (1 - q0))
    tr["impact_temp_ps"] = e_t
    tr["impact_carry_ps"] = e_c
    tr["pnl"] = tr.pnl.to_numpy(float) - s * (e + dfee)
    tr["usd_in"] = s * q1
    tr["q"] = q1
    return tr


def v2_metrics(t: pd.DataFrame, days, x: dict) -> dict:
    CS = _cs()
    E = x["v2"].E
    r = {"n_trades": float(len(t)), "per_share_c": float(t.pnl.sum() / t.shares.sum() * 100) if len(t) else np.nan,
         "shares_per_day": float(t.shares.sum() / len(days))}
    r.update(CS.daily_risk(t, days))
    r.update(CS.book_stats(t, days, t.end_ts.to_numpy(float), peak_fn=E.peak_locked,
                           close_ts=x["close"].reindex(t.cond).to_numpy(float)))
    cap = r["capital_usd"]
    r["roc_ann_pct"] = r["pnl_per_day_usd"] * 365 / cap * 100 if cap else np.nan
    dly = t.groupby("date").pnl.sum().reindex(days, fill_value=0.0).to_numpy()
    bs = np.random.default_rng(0).choice(dly, (2000, len(dly))).mean(1)
    r["pnl_per_day_boot_lo"], r["pnl_per_day_boot_hi"] = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
    if "impact_temp_ps" in t:
        w = t.shares.to_numpy(float)
        r["impact_temp_c_per_share"] = float((t.impact_temp_ps * w).sum() / w.sum() * 100) if len(t) else np.nan
        r["impact_carry_c_per_share"] = float((t.impact_carry_ps * w).sum() / w.sum() * 100) if len(t) else np.nan
    return r


def run_v2(model: dict) -> pd.DataFrame:
    CS = _cs()
    x = CS._v2ctx()
    v2, f, wh, oos = x["v2"], x["f"], x["wh"], x["oos"]
    E = v2.E
    slices = CS.v2_slices(f, oos)
    rows = []
    for net in CS.NET_CAPS:
        for order in CS.ORDER_CAPS:
            E._WCACHE.clear()
            tr = E.simulate(f, CS.v2_policy(net, order), "res", "actual", wh)
            tr = tr[tr.month >= E.EVAL_START]
            for variant in ("none", "central", "conservative", "bookwalk"):
                ti = apply_impact_v2(tr, model, variant)
                for name in ("IS", "burned_OOS"):
                    _, days = slices[name]
                    t = ti[~ti.cond.isin(oos)] if name == "IS" else ti[ti.cond.isin(oos)]
                    t = t.assign(date=pd.to_datetime(t.date, utc=True))
                    t = t[t.date.isin(days)]
                    rows.append({"strategy": "v2", "variant": variant, "net_cap": net, "order_cap": order, "phi": 1.0,
                                 "period": name, **v2_metrics(t, days, x)})
    return pd.DataFrame(rows)


def _cv_init():
    warnings.filterwarnings("ignore")
    _cs().LS.ctx()


def _cv_job(job):
    rk, alloc, phi, net, order, period, seeds, model = job
    CS = _cs()
    T = CS.T
    c = CS.LS.ctx()
    sc, cvs = CS.cv_scenario(c, rk, phi, CS.BASE["coverage"], net, order, alloc, "fixed")
    P = c["per"][period]
    J = P["J"]
    days = T.period_days(J, sc.regime)
    ends = CS._ends(c)
    lam_c = np.array([[model["lambda_c_per_1k"][str(h)][bb] for h in H] for bb in range(len(model["k_c"]))], float)
    lam_h = np.array([[model["lambda_c_per_1k_hi"][str(h)][bb] for h in H] for bb in range(len(model["k_c"]))], float)
    out = []
    for s in range(seeds):
        dr = T.draws(len(J), P["seed"] + s, max(c["n_tour"], 1))
        calls = T.simulate(J, P["M"], sc, dr, CS._pools(c, 1.0), cvs, c["mix"])
        for variant, lam in (("none", None), ("central", lam_c), ("conservative", lam_h)):
            cl = calls
            extra = {}
            if lam is not None and len(calls):
                cl = calls.sort_values(["cond", "ts"], kind="stable").copy()
                live = cl.shares.to_numpy(float) > 1e-9
                b = _vol_bucket(cl.cond.to_numpy(), model["bucket_edges_usd"])
                z = np.where(live, cl.d0.to_numpy(float) * cl.shares.to_numpy(float), 0.0)
                disp = carry_cost(cl.cond.to_numpy(), cl.ts.to_numpy(float), z, lam, b)
                e = cl.d0.to_numpy(float) * disp
                if variant == "conservative":
                    e = np.maximum(e, 0.0)                       # A1: no credit for favourable displacement
                q0 = cl.q.to_numpy(float)
                q1 = np.clip(q0 + e, 0.01, 0.99)
                e = q1 - q0
                rate = cl.rate.to_numpy(float)
                dfee = rate * (q1 * (1 - q1) - q0 * (1 - q0))
                sh = cl.shares.to_numpy(float)
                cl["pnl"] = cl.pnl.to_numpy(float) - sh * (e + dfee)
                cl["usd_in"] = sh * q1
                cl["q"] = q1
                cl["pnl_ps"] = cl.payout - cl.q - cl.rate * cl.q * (1 - cl.q)
                extra["impact_carry_c_per_share"] = float((e * sh).sum() / sh.sum() * 100) if sh.sum() > 0 else np.nan
            m = CS.cv_metrics(cl, days, phi, ends)
            out.append({"strategy": f"cv_{rk}", "variant": variant, "alloc": alloc, "phi": phi, "net_cap": net,
                        "order_cap": order, "period": period, "seed": s, **m, **extra})
    return out


def run_cv(model: dict, workers: int, seeds: int) -> pd.DataFrame:
    CS = _cs()
    phis = sorted({0.5, float(model["phi_used"]), float(round(model["phi_measured"], 3))})
    jobs = []
    for period in CS.PERIODS:
        for rk in ("lagcal", "prereg"):
            for alloc in ("best", "prorata"):
                for phi in phis:
                    for net in CS.NET_CAPS:
                        for order in (250, 1000):
                            jobs.append((rk, alloc, phi, net, order, period, seeds, model))
    log_oos("burned OOS jump tables (src/tier0.jump_table('oos'), via tier0_backtest.context) read to re-run the CV "
            "capacity path with the impact model (non-blind, no parameter chosen)")
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor(workers, initializer=_cv_init) as ex:
        for i, r in enumerate(ex.map(_cv_job, jobs, chunksize=2)):
            rows += r
            if (i + 1) % 20 == 0:
                print(f"[cv] {i + 1}/{len(jobs)} jobs, {time.time() - t0:.0f} s", flush=True)
    return pd.DataFrame(rows)


def stage_capacity(workers: int, seeds: int) -> None:
    fit = json.loads((CACHE / "fit.json").read_text())
    model = fit["model"]
    log_oos("burned OOS v2 candidate trades (data/v2_lowloss/features_u1.parquet, OOS rows) re-simulated with the frozen "
            "rule and costed with the impact model (non-blind, no parameter chosen)")
    t0 = time.time()
    V = run_v2(model)
    V.to_parquet(CACHE / "cap_v2.parquet", index=False)
    print(f"[capacity] v2 {len(V)} rows {time.time() - t0:.0f} s")
    C = run_cv(model, workers, seeds)
    C.to_parquet(CACHE / "cap_cv_seeds.parquet", index=False)
    print(f"[capacity] cv {len(C)} rows {time.time() - t0:.0f} s")


# ============================================================================================ stage 5: report
def answers(D: pd.DataFrame, path_order: int) -> dict:
    CS = _cs()
    a = CS.capacity_answer(D, {}, path_order=path_order)
    if a.get("status"):
        return a
    keep = {"sharpe_ref_smallest_size": a["sharpe_ref_smallest_size"],
            "capital_where_sharpe_halves_usd": a["capital_where_sharpe_halves_usd"],
            "half_sharpe_reached_within_grid": a["at_half_sharpe"].get("reached_within_grid"),
            "pnl_per_day_at_half_sharpe_usd": a["at_half_sharpe"].get("pnl_per_day_usd"),
            "pnl_max": {k: a["pnl_max"].get(k) for k in ("net_cap", "order_cap", "capital_usd", "pnl_per_day_usd",
                                                         "sharpe_ann", "per_share_c", "pnl_per_day_usd_p2_5",
                                                         "pnl_per_day_usd_p97_5", "pnl_per_day_boot_lo",
                                                         "pnl_per_day_boot_hi")
                        if a["pnl_max"].get(k) is not None},
            "pnl_max_at_grid_edge": a["pnl_max_at_grid_edge"]}
    return keep


def agg_seeds(C: pd.DataFrame) -> pd.DataFrame:
    keys = ["strategy", "variant", "alloc", "phi", "net_cap", "order_cap", "period"]
    g = C.groupby(keys, sort=False)
    A = g.mean(numeric_only=True).drop(columns=["seed"])
    for col in ("pnl_per_day_usd", "sharpe_ann"):
        A[f"{col}_sd"] = g[col].std(ddof=0)
        A[f"{col}_p2_5"] = g[col].quantile(0.025)
        A[f"{col}_p97_5"] = g[col].quantile(0.975)
    return A.reset_index()


def figure(fit: dict, V: pd.DataFrame, A: pd.DataFrame, cap: dict, path: Path) -> list[str]:
    """2 x 2 at 6.5 in: (a) taker cost by order size (prints, three liquidity fifths) vs the live book walk; (b) share
    of the stale depth other takers leave (phi check); (c) v2 and (d) CV net $/day vs capital along the size path,
    as published vs with the impact model (central line, conservative shaded)."""
    sys.path.insert(0, str(ROOT / "docs/paper"))
    import figstyle as fs
    fs.apply()
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

    fig = plt.figure(figsize=(fs.FIG_W, 7.7))
    W = 2.5
    ax1 = fs.axes_in(fig, 0.78, 4.95, W, 2.2)
    ax2 = fs.axes_in(fig, 3.88, 4.95, W - 0.3, 2.2)
    ax3 = fs.axes_in(fig, 0.78, 1.42, W, 2.2)
    ax4 = fs.axes_in(fig, 3.88, 1.42, W - 0.3, 2.2)
    kusd = FuncFormatter(lambda v, _: (fs.MINUS if v < 0 else "") +
                         (f"${abs(v) / 1000:g}k" if abs(v) >= 1000 else f"${abs(v):g}"))
    # (a) realised cost by order size, three liquidity fifths, and the live displayed book (tour matches)
    tmp = fit["temporary_IS"]
    cols = {0: fs.GREY, 2: fs.INK, 4: fs.ORANGE}
    names = {0: "thinnest fifth", 2: "middle fifth", 4: "deepest fifth"}
    qq = np.logspace(0.5, 4.15, 60)
    hand = []
    for b in (0, 2, 4):
        bins = [r for r in tmp["bins"] if r["bucket"] == b]
        x = np.array([r["q_median"] for r in bins])
        y = np.array([r["mean_c"] for r in bins])
        lo = np.array([r["ci95_c"][0] for r in bins])
        hi = np.array([r["ci95_c"][1] for r in bins])
        ax1.plot(x, y, "o", ms=fs.MS + 0.4, color=cols[b], zorder=4)
        fs.whiskers(ax1, x, y, lo, hi, cols[b])
        ln, = ax1.plot(qq, tmp["a_c"][b] + tmp["k_c"][b] * (qq / QREF) ** tmp["delta"], color=cols[b], lw=fs.LW_2)
        hand.append((ln, names[b]))
    bw = fit["l2"]["bookwalk_model"]
    qg = np.array(bw["Q"], float)
    cg = np.array(bw["C_tour_c"], float)
    m = qg <= 10000
    ln, = ax1.plot(qg[m], cg[m], color=fs.INK, lw=fs.LW_2, ls=fs.DOT_LS)
    hand.append((ln, "live book walk, tour"))
    ax1.set_xscale("log")
    ax1.xaxis.set_major_locator(FixedLocator([10, 100, 1000, 10000]))
    ax1.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax1.xaxis.set_minor_locator(NullLocator())
    ax1.set_ylim(0.4, 2.0)
    ax1.yaxis.set_major_locator(FixedLocator([0.5, 1.0, 1.5, 2.0]))
    ax1.set_xlabel("taker order (shares)")
    ax1.set_ylabel("cost vs mid (¢/share)")
    fs.hgrid(ax1)
    fs.panel(ax1, "a", "Size costs little", fig=fig)
    ax1.legend([h for h, _ in hand], [n for _, n in hand], frameon=False, loc="upper left", fontsize=fs.FS_SMALL,
               handlelength=1.4, borderaxespad=0.1, labelspacing=0.25)
    # (b) share of the stale depth that other takers leave
    live = fit["l2"]["phi_live_reprices"]
    off = fit["phi_official_points"]["D_ge_3c"]
    for src, col, dx, lab in ((live, fs.ORANGE, -0.08, "book reprices"), (off, fs.INK, 0.08, "official points")):
        xs = np.arange(len(TAUS)) + dx
        r = [src[f"tau_{t:g}s"] for t in TAUS]
        ys = np.array([x["phi_lo_pooled"] for x in r])
        ax2.plot(xs, ys, "o", color=col, ms=fs.MS + 1.2, label=lab, zorder=4)
        fs.whiskers(ax2, xs, ys, np.array([x["phi_lo_ci95"][0] for x in r]), np.array([x["phi_lo_ci95"][1] for x in r]),
                    col)
    ax2.axhline(0.5, color=fs.MUTED, lw=fs.LW_REF, ls=fs.DOT_LS)
    ax2.text(2.45, 0.52, "assumed: 0.5", ha="right", va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED)
    ax2.set_xticks(range(len(TAUS)))
    ax2.set_xticklabels([f"{t:g} s" for t in TAUS])
    ax2.set_xlim(-0.5, 2.5)
    ax2.set_ylim(0, 1.05)
    ax2.yaxis.set_major_locator(FixedLocator([0, 0.2, 0.4, 0.6, 0.8, 1.0]))
    ax2.set_xlabel("time before the reprice")
    ax2.set_ylabel("stale depth others leave")
    fs.hgrid(ax2)
    ax2.legend(frameon=False, loc="lower left", fontsize=fs.FS_SMALL, handlelength=1.0, borderaxespad=0.1)
    fs.panel(ax2, "b", "Others take little of it", fig=fig)

    # (c) v2 and (d) CV along the size path: as published vs with impact (central line, conservative shaded)
    def size_path(D, period, variant, order):
        x = D[(D.period == period) & (D.variant == variant) & (D.order_cap == order)].sort_values("net_cap")
        return x.capital_usd.to_numpy(float), x.pnl_per_day_usd.to_numpy(float)

    Dcv = A[(A.strategy == "cv_lagcal") & (A.alloc == "best") & (A.phi == 0.5)]
    for ax, D, col, order, key, title, letter in ((ax3, V, fs.INK, 1000, "v2", "v2: impact trims P&L", "c"),
                                                  (ax4, Dcv, fs.ORANGE, 250, "cv_lagcal|best", "CV: no visible change",
                                                   "d")):
        for period, ls in (("IS", fs.IS_LS), ("burned_OOS", fs.OOS_LS)):
            x0, y0 = size_path(D, period, "none", order)
            x1, y1 = size_path(D, period, "central", order)
            x2, y2 = size_path(D, period, "conservative", order)
            ax.fill_between(x1, y2, y1, color=col, alpha=0.16, lw=0, zorder=1)
            ax.plot(x0, y0, color=fs.GREY, ls=ls, lw=fs.LW_2, zorder=2)
            ax.plot(x1, y1, color=col, ls=ls, lw=fs.LW, marker="o", ms=fs.MS, zorder=3)
            h = cap.get(f"{key}|central|{period}", {})
            if h.get("capital_where_sharpe_halves_usd"):
                ax.plot([h["capital_where_sharpe_halves_usd"]], [h["pnl_per_day_at_half_sharpe_usd"]], "o", mfc="white",
                        mec=col, mew=1.3, ms=6.5, zorder=5)
        ax.set_xscale("log")
        ax.set_xlim(7e3, 1.4e5)
        ax.xaxis.set_major_locator(FixedLocator([1e4, 3e4, 1e5]))
        ylo, yhi = ax.get_ylim()
        ax.set_ylim(ylo, yhi)
        ax.yaxis.set_major_locator(FixedLocator([t for t in ax.get_yticks() if ylo <= t <= yhi]))
        ax.xaxis.set_major_formatter(kusd)
        ax.xaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_major_formatter(kusd)
        ax.set_xlabel("capital required")
        fs.zero_line(ax)
        fs.hgrid(ax)
        fs.panel(ax, letter, title, fig=fig)
    ax3.set_ylabel("net $ per day")
    hs = [Line2D([], [], color=fs.GREY, lw=fs.LW_2, label="as published"),
          Line2D([], [], color=fs.INK, lw=fs.LW, marker="o", ms=fs.MS, label="v2, impact"),
          Line2D([], [], color=fs.ORANGE, lw=fs.LW, marker="o", ms=fs.MS, label="CV, impact"),
          Patch(color=fs.INK, alpha=0.16, lw=0, label="conservative"),
          Line2D([], [], color=fs.MUTED, lw=fs.LW_2, ls=fs.IS_LS, label="in sample"),
          Line2D([], [], color=fs.MUTED, lw=fs.LW_2, ls=fs.OOS_LS, label="burned OOS"),
          Line2D([], [], color=fs.INK, ls="none", marker="o", mfc="white", mew=1.3, ms=6.5, label="Sharpe halved")]
    fig.legend(handles=hs, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.005), fontsize=fs.FS_SMALL,
               handlelength=1.6, columnspacing=0.9, labelspacing=0.3)
    return fs.save_fig(fig, path.stem, path.parent, meta={"Creator": "scripts/impact_model.py", "Subject": LABEL})


def clean(o):
    """Strict JSON: numpy scalars to Python, NaN / inf to null."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def stage_report() -> dict:
    fit = json.loads((CACHE / "fit.json").read_text())
    V = pd.read_parquet(CACHE / "cap_v2.parquet")
    C = pd.read_parquet(CACHE / "cap_cv_seeds.parquet")
    A = agg_seeds(C)
    CS = _cs()
    cap = {}
    for variant in ("none", "central", "conservative", "bookwalk"):
        for period in CS.PERIODS:
            D = V[(V.variant == variant) & (V.period == period)]
            cap[f"v2|{variant}|{period}"] = answers(D, 1000)
            for rk in ("lagcal", "prereg"):
                for alloc in ("best", "prorata"):
                    for phi in sorted(A.phi.unique()):
                        D = A[(A.strategy == f"cv_{rk}") & (A.alloc == alloc) & (A.phi == phi) & (A.variant == variant) &
                              (A.period == period)]
                        if len(D):
                            k = f"cv_{rk}|{alloc}" + ("" if phi == 0.5 else f"|phi{phi:g}") + f"|{variant}|{period}"
                            cap[k] = answers(D, 250)
    # reproduction checks against results/capacity (the 'none' variant must equal the published grid)
    pub = json.loads((ROOT / "results/capacity/capacity.json").read_text())["answers"]
    chk = {}
    for period in CS.PERIODS:
        p = pub["v2"][f"phi1|{period}"]
        chk[f"v2|{period}"] = {"published_half_sharpe_capital": p["capital_where_sharpe_halves_usd"],
                               "rerun_half_sharpe_capital": cap[f"v2|none|{period}"]["capital_where_sharpe_halves_usd"],
                               "published_pnl_max": p["pnl_max"]["pnl_per_day_usd"],
                               "rerun_pnl_max": cap[f"v2|none|{period}"]["pnl_max"]["pnl_per_day_usd"]}
        for rk in ("lagcal", "prereg"):
            for alloc, name in (("best", "cv"), ("prorata", "cv_prorata")):
                p = pub[name].get(f"{rk}|phi0.5|cov10|g1|{period}")
                r = cap.get(f"cv_{rk}|{alloc}|none|{period}")
                if p and r and not r.get("status"):
                    chk[f"cv_{rk}|{alloc}|{period}"] = {
                        "published_half_sharpe_capital": p["capital_where_sharpe_halves_usd"],
                        "rerun_half_sharpe_capital": r["capital_where_sharpe_halves_usd"],
                        "published_sharpe_ref": p["sharpe_ref_smallest_size"], "rerun_sharpe_ref": r["sharpe_ref_smallest_size"],
                        "note": "re-run grid has order caps $250 and $1k only (the published P&L max may sit at another cap)"}
    cells = pd.concat([V.assign(alloc="n/a"), A], ignore_index=True)
    keep_cols = ["strategy", "variant", "alloc", "phi", "net_cap", "order_cap", "period", "capital_usd",
                 "pnl_per_day_usd", "pnl_per_day_usd_sd", "sharpe_ann", "sharpe_ann_sd", "per_share_c", "n_trades",
                 "notional_usd_per_day", "impact_temp_c_per_share", "impact_carry_c_per_share", "max_dd_usd",
                 "pnl_per_day_boot_lo", "pnl_per_day_boot_hi"]
    cells = cells[[c for c in keep_cols if c in cells.columns]]
    cells.to_csv(OUT / "capacity_cells.csv", index=False, float_format="%.6g")
    figs = figure(fit, V, A, cap, OUT / "impact_capacity.png")
    peeks = PEEK.read_text().splitlines() if PEEK.exists() else []
    out = {"label": LABEL, "generated_utc": now(), "script": "scripts/impact_model.py",
           "plan": __doc__.split("PLAN")[1].strip(),
           "oos_peek_lines_to_append_to_results_oos_peeks_log": peeks,
           **{k: v for k, v in fit.items()},
           "capacity": cap, "capacity_reproduction_checks": chk,
           "outputs": ["results/liquidity/impact.json", "results/liquidity/capacity_cells.csv"] + figs}
    (OUT / "impact.json").write_text(json.dumps(clean(out), indent=1, allow_nan=False))
    print("[report] wrote results/liquidity/impact.json,", ", ".join(figs))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["all", "prints", "l2", "fit", "capacity", "report"])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args()
    if a.stage in ("all", "prints"):
        stage_prints(a.workers)
    if a.stage in ("all", "l2"):
        stage_l2()
    if a.stage in ("all", "fit"):
        stage_fit()
    if a.stage in ("all", "capacity"):
        stage_capacity(a.workers, a.seeds)
    if a.stage in ("all", "report"):
        stage_report()


if __name__ == "__main__":
    main()
