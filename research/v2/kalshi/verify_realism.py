"""Adversarial execution-realism and statistics check of the Kalshi lens (in-sample data only).

What it checks (every number is IS: matches starting before 2026-08-25 14:15 UTC; no OOS, no live data):
  A. Reproduce the headline walk-forward numbers from the lens's own trade files.
  B. Concentration: how much of the $ P&L and of the per-share mean comes from a handful of trades /
     matches / months, and from "anomalous dislocations" (signal gap > 20c: stale abandoned quotes at
     match end, Kalshi flash-crash sweeps) that are not "Kalshi leads by a few seconds" repricings.
  C. Fill realism, recomputed from the raw tapes for every gap / gaprob signal:
       - Polymarket min order 5 shares (sub-5-share fills dropped)
       - VWAP of the sized PM fill (the lens sizes on ALL qualifying volume in the 3 s window but prices
         every share at the FIRST print)
       - queue: a remote laggard is behind whoever printed in the first block -> fill only from
         qualifying prints in LATER blocks (no later qualifying print -> no fill)
       - competition evidence: qualifying snipes on the same side BEFORE our fill block, wallets per block
  D. Hedge realism on Kalshi:
       - adverse of (first hedge-side print after T, last hedge-side print <= T): the lens waits up to
         3 s for the first print while Kalshi keeps drifting in the signal direction (favourable)
       - size-aware: our hedge consumes Kalshi hedge-side prints in [T, T+3] (100% of each); the rest is
         hedged 2c worse than the worst printed price; Kalshi per-order fee rounded up to the cent
  E. Fixed WF-chosen cell (G = 6c, E = 3c, which the lens's walk-forward picked in every month for both
     variants) in the current 1 s / 5% regime, cumulative haircuts, at B = 0 / 2 / 4 s.
  F. Walk-forward re-run (same 30-cell grid, same rules: months < m, >= 150 training trades, stand aside
     if best training mean <= 0) under the conservative execution model, B = 2.
  G. Lead-lag share after removing the block-time allowance B from Polymarket's timestamps.
  H. Multiple testing: deflated Sharpe ratio (Bailey & Lopez de Prado) and Bonferroni haircut.
  I. Parameter surface: is (6c, 3c) a plateau or the grid corner?

Run (repo root): .venv/bin/python research/v2/kalshi/verify_realism.py      (~5-10 min, 2 workers)
Outputs: research/v2/kalshi/out/verify_realism.json ; cache data/v2_kalshi/verify_aug.pkl
"""
from __future__ import annotations

import itertools
import json
import math
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy import stats as sst

sys.path.insert(0, str(Path(__file__).resolve().parent))
from k_common import CACHE, OUT, ROOT, load_k, load_matched, window  # noqa: E402
from src.backtest import stats  # noqa: E402
from src.tape import load_tape  # noqa: E402

L, W = 0.25, 3.0
CAP_TRADE, CAP_MATCH = 1000.0, 3000.0
MIN_SHARES = 5.0
ANOM_GAP = 0.20
GS = [0.0, 0.01, 0.02, 0.03, 0.04, 0.06]
ES = [-9.0, 0.0, 0.01, 0.02, 0.03]
MIN_TRAIN = 150
AUG = CACHE / "verify_aug.pkl"
N_VARIANTS = {"count": 0}


def is_cur(df):
    return (df.fee_rate == 0.05) & (df.delay == 1)


# --------------------------------------------------------------------------------------------- A / B
def reproduce_and_concentration(res: dict) -> dict:
    out = {}
    for name, tag, key in (("primary", "pm_gap_curfee_ps_hedge", "primary_taker"),
                           ("best", "pm_gaprob_curfee_ps_hedge", "best_taker")):
        t = pd.read_parquet(OUT / f"trades_wf_{tag}.parquet")
        cols = ["cond", "pnl_ps", "pnl", "fee", "usd_in", "exit", "date"]
        a, c = stats(t[cols]), stats(t[is_cur(t)][cols])
        claim_a = res[key]["wf"]["mean_pnl_per_share_c"]
        claim_c = res[key]["wf_1s5pct"]["mean_pnl_per_share_c"]
        cur = t[is_cur(t)].copy()
        r = {"reproduced_all_c": a["mean_pnl_per_share_c"], "claimed_all_c": claim_a,
             "reproduced_cur_c": c["mean_pnl_per_share_c"], "claimed_cur_c": claim_c,
             "ci_all": a["ci95_pnl_per_share_c"], "ci_cur": c["ci95_pnl_per_share_c"],
             "n_all": a["n_trades"], "n_cur": c["n_trades"],
             "match": bool(abs(a["mean_pnl_per_share_c"] - claim_a) < 1e-6 and abs(c["mean_pnl_per_share_c"] - claim_c) < 1e-6)}
        for lab, x in (("all", t), ("cur", cur)):
            pnl = x.pnl.sort_values(ascending=False)
            g = x.groupby("cond").pnl.sum().sort_values(ascending=False)
            anom = x.gap > ANOM_GAP
            ps = x.pnl_ps
            r[lab] = {
                "n": int(len(x)), "usd_pnl": float(x.pnl.sum()), "usd_in": float(x.usd_in.sum()),
                "eqwt_c": float(100 * ps.mean()), "median_c": float(100 * ps.median()),
                "sharewt_c": float(100 * x.pnl.sum() / x.shares.sum()),
                "trim10_c": float(100 * sst.trim_mean(ps, 0.10)),
                "winsor10c_c": float(100 * ps.clip(-0.10, 0.10).mean()),
                "hit_rate": float((ps > 0).mean()),
                "top1_trade_share_of_usd": float(pnl.iloc[0] / x.pnl.sum()),
                "top10_trades_share_of_usd": float(pnl.iloc[:10].sum() / x.pnl.sum()),
                "top1pct_trades_share_of_usd": float(pnl.iloc[:max(1, len(x) // 100)].sum() / x.pnl.sum()),
                "top5_matches_share_of_usd": float(g.iloc[:5].sum() / g.sum()),
                "n_anomalous_gap_gt20c": int(anom.sum()),
                "usd_pnl_from_anomalous": float(x.pnl[anom].sum()),
                "eqwt_c_ex_anomalous": float(100 * ps[~anom].mean()),
                "usd_pnl_ex_anomalous": float(x.pnl[~anom].sum()),
                "eqwt_c_ex_top1_usd_trade": float(100 * ps.drop(pnl.index[0]).mean()),
                "eqwt_c_ex_top2_usd_trades": float(100 * ps.drop(pnl.index[:2]).mean()),
                "usd_pnl_ex_top2": float(x.pnl.drop(pnl.index[:2]).sum()),
                "by_month_usd": {k: float(v) for k, v in x.groupby("month").pnl.sum().items()},
                "by_month_eqwt_c": {k: float(100 * v) for k, v in x.groupby("month").pnl_ps.mean().items()},
                "top3_trades": x.loc[pnl.index[:3], ["cond", "month", "d", "fair", "own", "gap", "p_f", "hedge_px",
                                                      "shares", "pnl_ps", "pnl"]].to_dict("records"),
            }
        out[name] = r
    return out


# --------------------------------------------------------------------------------------------- C / D: tapes
def _work(args):
    row, sig = args
    t = load_tape(row.cond)
    k = load_k(row)
    if t is None or k is None or len(k) == 0:
        return []
    s, e = window(row)
    t = t[(t.timestamp >= s) & (t.timestamp <= e)]
    P = {}
    for side in (1, -1):
        msk = t.at_ask.to_numpy() if side > 0 else ~t.at_ask.to_numpy()
        P[side] = (t.timestamp.to_numpy(float)[msk], t.p0.to_numpy(float)[msk], t["size"].to_numpy(float)[msk],
                   t.proxyWallet.to_numpy()[msk])
    K = {}
    for side in (1, -1):
        msk = k.ask.to_numpy() if side > 0 else ~k.ask.to_numpy()
        K[side] = (k.ts.to_numpy(float)[msk], k.p.to_numpy(float)[msk], k.q.to_numpy(float)[msk])
    out = []
    for r in sig.itertuples():
        d = int(r.d)
        pts, pp, pq, pwal = P[d]
        i0 = np.searchsorted(pts, r.ts_f, "left")
        j0 = np.searchsorted(pts, r.ts_f + W, "right")
        ok_first = i0 < len(pts) and pts[i0] == r.ts_f
        wt, wp, wq, ww = pts[i0:j0] - r.ts_f, pp[i0:j0], pq[i0:j0], pwal[i0:j0]
        q3 = d * (r.fair - wp) >= 0.03 - 1e-9
        blk0 = wt == 0
        # qualifying (edge >= 3c) same-side prints in [t_s - 10, ts_f): somebody sniping the stale level before us
        ip = np.searchsorted(pts, r.t_s - 10.0, "left")
        pre_p, pre_q, pre_w = pp[ip:i0], pq[ip:i0], pwal[ip:i0]
        pre_ok = d * (r.fair - pre_p) >= 0.03 - 1e-9
        # Kalshi hedge, side -d, at T = t_s + L + delay + 0.5
        T = r.t_s + L + r.delay + 0.5
        kts, kp, kq = K[-d]
        ki = np.searchsorted(kts, T, "left")
        kj = np.searchsorted(kts, T + W, "right")
        h_first = kp[ki] if ki < len(kts) and kts[ki] <= T + W else np.nan
        h_prev = kp[ki - 1] if ki - 1 >= 0 and T - kts[ki - 1] <= 5.0 else np.nan
        kd = np.searchsorted(kts, T + 1.0, "left")
        h_first_d1 = kp[kd] if kd < len(kts) and kts[kd] <= T + 1.0 + W else np.nan
        # touch proxy as in k05: other side's last print (<= 5 s old) -/+ 2c
        ots, op_, _ = K[d]
        oi = np.searchsorted(ots, T, "right") - 1
        h_proxy = (op_[oi] + (-d) * 0.02) if oi >= 0 and T - ots[oi] <= 5.0 else np.nan
        out.append({
            "idx": r.Index, "pm_ok_first": bool(ok_first),
            "pm_t": wt.astype(np.float32), "pm_p": wp.astype(np.float32), "pm_q": wq.astype(np.float32),
            "nw_blk0_q3": int(len(set(ww[blk0 & q3]))), "nw_win_q3": int(len(set(ww[q3]))),
            "pre_snipe_n": int(pre_ok.sum()), "pre_snipe_q": float(pre_q[pre_ok].sum()),
            "pre_snipe_nw": int(len(set(pre_w[pre_ok]))),
            "k_t": (kts[ki:kj] - T).astype(np.float32), "k_p": kp[ki:kj].astype(np.float32),
            "k_q": kq[ki:kj].astype(np.float32),
            "h_first": float(h_first), "h_prev": float(h_prev), "h_first_d1": float(h_first_d1),
            "h_proxy": float(h_proxy),
        })
    return out


def load_signals() -> pd.DataFrame:
    cols = ["cond", "month", "fee_rate", "delay", "res0", "k_settle0", "fam", "t_s", "d", "B", "fair", "own", "gap",
            "ts_f", "p_f", "edge_f", "hedge_px", "hedge_px_strict", "pw", "qw"]
    s = pd.read_parquet(CACHE / "signals_pm.parquet", columns=cols)
    s = s[s.fam.isin(["gap", "gaprob"])]
    keep = (s.B == 2) | (is_cur(s) & s.B.isin([0, 4]))
    s = s[keep & s.p_f.between(0.05, 0.95)].reset_index(drop=True)
    return s


def augment(s: pd.DataFrame) -> pd.DataFrame:
    if AUG.exists():
        with open(AUG, "rb") as f:
            a = pickle.load(f)
        if len(a) == len(s):
            return a
    m = load_matched().set_index("cond")
    jobs = []
    for cond, g in s.groupby("cond"):
        row = m.loc[cond].to_dict()
        row["cond"] = cond
        jobs.append((SimpleNamespace(**row), g[["t_s", "d", "ts_f", "fair", "delay"]]))
    with ProcessPoolExecutor(2) as ex:
        res = list(ex.map(_work, jobs, chunksize=16))
    a = pd.DataFrame([x for part in res for x in part]).set_index("idx").sort_index()
    with open(AUG, "wb") as f:
        pickle.dump(a, f)
    return a


# --------------------------------------------------------------------------------------------- execution models
def pm_fee(p):
    return 0.05 * p * (1 - p)


def k_fee(p):
    return 0.07 * p * (1 - p)


def k_fee_order(p, c):
    """Kalshi taker fee per contract with the per-order round-up to the cent."""
    c = np.maximum(c, 1e-9)
    return np.ceil(np.round(0.07 * c * p * (1 - p) * 100, 6)) / 100 / c


def pm_fill(pt, pp, pq, d, fair, E, queue: bool, vwap: bool, p_first: float):
    """Returns (shares, fill_price) under the lens sizing rule min($1000/p, 50% of qualifying volume)."""
    # float32 comparison exactly as k06.size_trades does it (python float - float32 array -> float32)
    q_ok = (d * (float(fair) - pp.astype(np.float32)) >= E - 1e-9) if E > -1 else np.ones(len(pp), bool)
    if queue:
        q_ok = q_ok & (pt > 0)
    if not q_ok.any():
        return 0.0, np.nan
    p_use, q_use = pp[q_ok].astype(float), pq[q_ok]
    p0 = float(p_use[0]) if queue else p_first
    target = CAP_TRADE / p0
    avail = 0.5 * q_use
    sh = float(min(target, avail.sum()))
    if not vwap:
        return sh, p0
    cum = np.cumsum(avail)
    take = np.minimum(avail, np.maximum(0.0, sh - (cum - avail)))
    return sh, float((take * p_use).sum() / max(take.sum(), 1e-12))


def hedge_fill(r, d, shares, mode: str):
    """Kalshi hedge price (per share, o0 axis) for side -d.
    'lens'         first hedge-side print at/after T (touch proxy -/+2c if none), as in k05
    'adverse'      worse of that and the last hedge-side print <= T (a pessimistic bound: min of two noisy prices)
    'size1'/'size2' size-aware on the lens price: consume printed hedge-side volume in [T, T+3] (100% of each
                   print), remainder 1c / 2c worse than the worst price consumed
    'size_adverse' size-aware (2c) starting from the 'adverse' price"""
    base = r.h_first if np.isfinite(r.h_first) else r.h_proxy
    if mode == "lens":
        return base
    if mode in ("size1", "size2"):
        return _size_aware(r, d, shares, base, 0.01 if mode == "size1" else 0.02)
    # d > 0: we SELL o0 on Kalshi (lower is worse); d < 0: we BUY o0 on Kalshi (higher is worse)
    cands = [v for v in (base, r.h_prev) if np.isfinite(v)]
    adv = (min(cands) if d > 0 else max(cands)) if cands else np.nan
    if mode == "adverse":
        return adv
    return _size_aware(r, d, shares, adv, 0.02)


def _size_aware(r, d, shares, ref, pen):
    """Hedge VWAP for `shares`: consume Kalshi hedge-side prints in [T, T+3] (100% of each print); any remainder
    is hedged `pen` worse than the worst price consumed; never better than the single reference price `ref`."""
    if not np.isfinite(ref):
        return np.nan
    kp, kq = r.k_p.astype(float), r.k_q.astype(float)
    if len(kp) == 0:  # no print on the hedge side within 3 s: the lens already uses the touch proxy (-/+2c)
        return ref
    cum = np.cumsum(kq)
    take = np.minimum(kq, np.maximum(0.0, shares - (cum - kq)))
    filled = take.sum()
    worst = (kp[take > 0].min() if d > 0 else kp[take > 0].max()) if filled > 0 else ref
    worst = min(worst, ref) if d > 0 else max(worst, ref)
    rest = max(0.0, shares - filled)
    vw = ((take * kp).sum() + rest * (worst - d * pen)) / max(shares, 1e-12)
    return min(vw, ref) if d > 0 else max(vw, ref)


CONFIGS = {
    # name: (min5, vwap, queue, hedge_mode, fee_roundup, drop_anomalous)
    "lens": (False, False, False, "lens", False, False),
    "min5": (True, False, False, "lens", False, False),
    "min5_vwap": (True, True, False, "lens", False, False),
    "min5_vwap_fee": (True, True, False, "lens", True, False),
    "central": (True, True, False, "size1", True, False),            # realistic-but-fair execution
    "central_noanom": (True, True, False, "size1", True, True),       # + no anomalous dislocations (gap > 20c)
    "central_queue": (True, True, True, "size1", True, False),        # + behind the first block of snipers
    "central_queue_noanom": (True, True, True, "size1", True, True),
    "pess_hadv": (True, True, False, "adverse", True, False),          # worst-of-two hedge print (bound)
    "pess_all": (True, True, True, "size_adverse", True, True),       # every pessimistic choice at once
}


def build_trades(s: pd.DataFrame, a: pd.DataFrame, G: float, E: float, cfg: str, cap_match: bool) -> pd.DataFrame:
    min5, vwap, queue, hmode, fround, noanom = CONFIGS[cfg]
    x = s[(s.gap >= G - 1e-9) & ((s.edge_f >= E - 1e-9) if E > -1 else True)]
    if noanom:
        x = x[x.gap <= ANOM_GAP]
    # the lens drops signals without any hedge price BEFORE sizing (k06: dropna then size_trades)
    x = x[np.isfinite(np.where(np.isfinite(a.loc[x.index].h_first), a.loc[x.index].h_first, a.loc[x.index].h_proxy))]
    if x.empty:
        return x.assign(shares=[], p_fill=[], h=[], pnl_ps=[], usd_in=[], pnl=[])
    ax = a.loc[x.index]
    sh, pf = [], []
    for r, (pt, pp, pq) in zip(x.itertuples(), zip(ax.pm_t, ax.pm_p, ax.pm_q)):
        q_, p_ = pm_fill(pt.astype(float), pp, pq.astype(float), int(r.d), r.fair, E, queue, vwap, r.p_f)
        sh.append(q_)
        pf.append(p_)
    x = x.assign(shares=np.array(sh), p_fill=np.array(pf))
    x = x[(x.shares > 0) & np.isfinite(x.p_fill)]
    if cap_match and len(x):
        x = x.sort_values("ts_f", kind="stable")
        usd = x.shares * x.p_fill
        cum = usd.groupby(x.cond).cumsum()
        prev = cum - usd
        usd2 = np.where(cum > CAP_MATCH, np.maximum(0.0, CAP_MATCH - prev), usd)
        x = x.assign(shares=usd2 / x.p_fill)
        x = x[x.shares > 0]
    if min5:
        x = x[x.shares >= MIN_SHARES]
    if x.empty:
        return x.assign(h=[], pnl_ps=[], usd_in=[], pnl=[])
    ax = a.loc[x.index]
    h = np.array([hedge_fill(r, int(dd), float(q_), hmode) for r, dd, q_ in zip(ax.itertuples(), x.d, x.shares)])
    d, p = x.d.to_numpy(), x.p_fill.to_numpy()
    fee_h = k_fee_order(h, x.shares.to_numpy()) if fround else k_fee(h)
    basis = d * (x.res0.to_numpy() - x.k_settle0.to_numpy())
    pnl_ps = d * (h - p) + basis - pm_fee(p) - fee_h
    x = x.assign(h=h, pnl_ps=pnl_ps, fee=pm_fee(p), usd_in=x.shares * p)
    x = x[np.isfinite(x.pnl_ps)]
    x = x.assign(pnl=x.pnl_ps * x.shares, exit="hedge",
                 date=pd.to_datetime(x.ts_f, unit="s", utc=True).dt.floor("D"))
    return x


def summ(x: pd.DataFrame) -> dict:
    if x is None or len(x) == 0:
        return {"n": 0}
    st = stats(x[["cond", "pnl_ps", "pnl", "fee", "usd_in", "exit", "date"]])
    return {"n": st["n_trades"], "eqwt_c": st["mean_pnl_per_share_c"], "ci95_c": st["ci95_pnl_per_share_c"],
            "median_c": float(100 * x.pnl_ps.median()), "trim10_c": float(100 * sst.trim_mean(x.pnl_ps, 0.1)),
            "sharewt_c": float(100 * x.pnl.sum() / x.shares.sum()), "usd_pnl": st["total_pnl_usd"],
            "usd_in": float(x.usd_in.sum()), "hit": st["hit_rate"], "sharpe_ann": st["sharpe_ann"]}


def fixed_cell_current(s, a) -> dict:
    out = {}
    for fam in ("gap", "gaprob"):
        for B in (0, 2, 4):
            sb = s[(s.fam == fam) & (s.B == B) & is_cur(s)]
            for cfg in CONFIGS:
                N_VARIANTS["count"] += 1
                x = build_trades(sb, a, 0.06, 0.03, cfg, cap_match=True)
                out[f"{fam}:B{B}:{cfg}"] = summ(x)
                print("FIXED", fam, B, cfg, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out[f'{fam}:B{B}:{cfg}'].items()}, flush=True)
    return out


def walk_forward(s, a, fam: str, cfg: str) -> dict:
    sb = s[(s.fam == fam) & (s.B == 2)]
    months = sorted(sb.month.unique())
    cells = [(G, E) for G, E in itertools.product(GS, ES)]
    N_VARIANTS["count"] += len(cells)
    # unique cells (G <= 2c are identical: every gap/gaprob signal has gap >= 2c by construction)
    cache = {}
    for G, E in cells:
        key = (max(G, 0.02), E)
        if key not in cache:
            cache[key] = build_trades(sb, a, key[0], E, cfg, cap_match=False)
    picks, outs = [], []
    for i, m in enumerate(months):
        if i < 2:
            continue
        best = None
        for G, E in cells:
            x = cache[(max(G, 0.02), E)]
            tr = x[x.month < m].pnl_ps
            if len(tr) < MIN_TRAIN:
                continue
            k = (tr.mean(), len(tr))
            if best is None or k > best[0]:
                best = (k, G, E)
        if best is None or best[0][0] <= 0:
            picks.append({"month": m, "G": None, "E": None, "train_c": 100 * best[0][0] if best else None, "n": 0})
            continue
        _, G, E = best
        te = build_trades(sb[sb.month == m], a, G, E, cfg, cap_match=True)
        picks.append({"month": m, "G": G, "E": E, "train_c": 100 * best[0][0], "n": int(len(te)),
                      "c": float(100 * te.pnl_ps.mean()) if len(te) else None, "usd": float(te.pnl.sum()) if len(te) else 0.0})
        outs.append(te)
    tr = pd.concat(outs) if outs else pd.DataFrame()
    r = {"all": summ(tr), "cur": summ(tr[is_cur(tr)]) if len(tr) else {"n": 0}, "picks": picks}
    if len(tr):
        r["months_pos_usd"] = int((tr.groupby("month").pnl.sum() > 0).sum())
        r["months_traded"] = int(tr.month.nunique())
        r["by_regime"] = {f"{fr}/{dl}s": summ(g) for (fr, dl), g in tr.groupby(["fee_rate", "delay"])}
    print("WF", fam, cfg, json.dumps({k: r[k] for k in ("all", "cur")}, default=float)[:400], flush=True)
    return r


def competition(s, a) -> dict:
    out = {}
    for fam in ("gap", "gaprob"):
        x = s[(s.fam == fam) & (s.B == 2) & (s.gap >= 0.06 - 1e-9) & (s.edge_f >= 0.03 - 1e-9)]
        ax = a.loc[x.index]
        for lab, msk in (("all", np.ones(len(x), bool)), ("cur", is_cur(x).to_numpy())):
            y = ax[msk]
            later = np.array([bool(((d * (f - pp) >= 0.03 - 1e-9) & (pt > 0)).any())
                              for pt, pp, d, f in zip(y.pm_t, y.pm_p, x.d[msk], x.fair[msk])])
            sh = np.array([pm_fill(pt, pp, pq.astype(float), int(d), f, 0.03, False, False, pf)[0]
                           for pt, pp, pq, d, f, pf in zip(y.pm_t, y.pm_p, y.pm_q, x.d[msk], x.fair[msk], x.p_f[msk])])
            kvol = np.array([float(q.sum()) for q in y.k_q])
            first_blk_q = np.array([float(pq[(pt == 0) & (d * (f - pp) >= 0.03 - 1e-9)].sum())
                                    for pt, pp, pq, d, f in zip(y.pm_t, y.pm_p, y.pm_q, x.d[msk], x.fair[msk])])
            out[f"{fam}:{lab}"] = {
                "n_signals_cell_6_3": int(len(y)),
                "pm_first_print_found": float(y.pm_ok_first.mean()),
                "share_with_qualifying_snipes_before_our_block": float((y.pre_snipe_n > 0).mean()),
                "median_pre_snipe_wallets": float(y.pre_snipe_nw.median()),
                "share_first_block_ge2_wallets": float((y.nw_blk0_q3 >= 2).mean()),
                "share_with_qualifying_print_in_a_later_block": float(later.mean()),
                "share_hedge_first_missing": float(np.mean(~np.isfinite(y.h_first.to_numpy()))),
                "median_lens_shares": float(np.median(sh)),
                "share_lens_size_gt_kalshi_printed_hedge_vol_3s": float(np.mean(sh > kvol)),
                "share_lens_size_gt_first_block_qualifying_pm_vol": float(np.mean(sh > first_blk_q)),
                # > 0: the first hedge-side print AFTER T is better for us than the last one before T
                "median_drift_first_vs_prev_c": float(100 * np.nanmedian(
                    x.d[msk].to_numpy() * (y.h_first.to_numpy() - y.h_prev.to_numpy()))),
                "mean_drift_first_vs_prev_c": float(100 * np.nanmean(
                    x.d[msk].to_numpy() * (y.h_first.to_numpy() - y.h_prev.to_numpy()))),
            }
    return out


# --------------------------------------------------------------------------------------------- G / H / I
def leadlag_B() -> dict:
    ev = pd.read_parquet(OUT / "leadlag_events.parquet")
    b = ev[(ev.move_pm >= 0.02) & (ev.move_k >= 0.02) & ev.t50_pm.notna() & ev.t50_k.notna()].copy()
    b["lead"] = b.t50_pm - b.t50_k
    out = {"n": int(len(b))}
    for lab, g in [("all", b)] + [(f"delay{d}", g) for d, g in b.groupby("delay")] + \
                  [("cur", b[(b.fee_rate == 0.05) & (b.delay == 1)])]:
        out[lab] = {"p_lead_gt0": float((g.lead > 0).mean()), "p_lead_gt2_Bcorrected": float((g.lead > 2).mean()),
                    "p_lead_gt3": float((g.lead > 3).mean()), "p_lead_lt_minus2": float((g.lead < -2).mean()),
                    "median_lead_minus_B2": float(g.lead.median() - 2)}
    return out


def dsr(res: dict) -> dict:
    """Deflated Sharpe ratio of the headline variants' daily P&L, trials = all reported WF series."""
    sr_ann = []
    for grp in ("all_taker_variants_wf", "all_maker_variants_wf"):
        for v in res[grp].values():
            if v.get("sharpe_ann") is not None and v.get("n_trades", 0) > 0 and np.isfinite(v["sharpe_ann"]):
                sr_ann.append(v["sharpe_ann"])
    for v in res["latency_sensitivity_taker"].values():
        if v.get("sharpe_ann") is not None and v.get("n_trades", 0):
            sr_ann.append(v["sharpe_ann"])
    sr_d = np.array(sr_ann) / np.sqrt(365)
    var_sr = float(np.var(sr_d, ddof=1))
    out = {"n_reported_wf_series": len(sr_d), "sd_daily_sr_across_series": float(np.sqrt(var_sr))}
    g = 0.5772156649
    for name, tag in (("primary", "pm_gap_curfee_ps_hedge"), ("best", "pm_gaprob_curfee_ps_hedge")):
        t = pd.read_parquet(OUT / f"trades_wf_{tag}.parquet")
        for lab, x in (("all", t), ("cur", t[is_cur(t)])):
            daily = x.groupby("date").pnl.sum()
            idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC")
            r = (daily.reindex(idx, fill_value=0.0) / 50_000).to_numpy()
            T = len(r)
            sr = r.mean() / r.std(ddof=1)
            sk, ku = sst.skew(r), sst.kurtosis(r, fisher=False)
            rr = {"T_days": T, "sr_daily": float(sr), "sr_ann": float(sr * np.sqrt(365)), "skew": float(sk), "kurt": float(ku)}
            for N in (1904, len(sr_d)):
                sr0 = math.sqrt(var_sr) * ((1 - g) * sst.norm.ppf(1 - 1 / N) + g * sst.norm.ppf(1 - 1 / (N * math.e)))
                z = (sr - sr0) * math.sqrt(T - 1) / math.sqrt(max(1e-12, 1 - sk * sr + (ku - 1) / 4 * sr ** 2))
                rr[f"N{N}"] = {"sr0_daily": float(sr0), "sr0_ann": float(sr0 * np.sqrt(365)), "DSR": float(sst.norm.cdf(z))}
            # per-share t-stat (cluster by match) and Bonferroni at N = 1904
            gm = x.groupby("cond").agg(s=("pnl_ps", "sum"), n=("pnl_ps", "size"))
            mu = gm.s.sum() / gm.n.sum()
            resid = (x.pnl_ps - mu).groupby(x.cond).sum()
            se = math.sqrt((resid ** 2).sum()) / gm.n.sum()
            rr["per_share_t_cluster"] = float(mu / se)
            rr["bonferroni_z_crit_N1904_one_sided_5pct"] = float(sst.norm.ppf(1 - 0.05 / 1904))
            rr["haircut_per_share_c_N1904"] = float(100 * max(0.0, mu - sst.norm.ppf(1 - 0.05 / 1904) * se))
            out[f"{name}:{lab}"] = rr
    return out


def surface(s) -> dict:
    """Plain IS means (NOT selection) of the lens P&L over the grid, all IS vs current regime, ex anomalies."""
    out = {}
    for fam in ("gap", "gaprob"):
        sb = s[(s.fam == fam) & (s.B == 2)].copy()
        d, p = sb.d.to_numpy(), sb.p_f.to_numpy()
        h = sb.hedge_px.to_numpy()
        sb["ps"] = d * (h - p) + d * (sb.res0 - sb.k_settle0) - pm_fee(p) - k_fee(h)
        rows = []
        for G, E in itertools.product([0.02, 0.03, 0.04, 0.06, 0.08, 0.10], [0.0, 0.01, 0.02, 0.03, 0.04, 0.05]):
            x = sb[(sb.gap >= G - 1e-9) & (sb.edge_f >= E - 1e-9)]
            c = x[is_cur(x)]
            rows.append({"G": G, "E": E, "n_all": len(x), "all_c": 100 * x.ps.mean(),
                         "all_c_ex_anom": 100 * x[x.gap <= ANOM_GAP].ps.mean(),
                         "n_cur": len(c), "cur_c": 100 * c.ps.mean() if len(c) else np.nan,
                         "cur_c_ex_anom": 100 * c[c.gap <= ANOM_GAP].ps.mean() if len(c) else np.nan,
                         "cur_median_c": 100 * c.ps.median() if len(c) else np.nan})
        out[fam] = rows
    return out


def main():
    res = json.loads((ROOT / "research/v2/kalshi/results.json").read_text())
    out = {"note": "IS only. Robustness checks, not selection. Variant count below counts every configuration evaluated here."}
    out["A_B_reproduce_concentration"] = reproduce_and_concentration(res)
    print(json.dumps(out["A_B_reproduce_concentration"], indent=1, default=str)[:6000], flush=True)
    out["G_leadlag_B"] = leadlag_B()
    print(json.dumps(out["G_leadlag_B"], indent=1), flush=True)
    out["H_multiple_testing"] = dsr(res)
    print(json.dumps(out["H_multiple_testing"], indent=1), flush=True)
    s = load_signals()
    print("signals", len(s), flush=True)
    out["I_surface"] = surface(s)
    a = augment(s)
    # sanity: recomputed first-print window equals the lens's pw arrays; recomputed hedge equals lens hedge
    chk = s.loc[a.index]
    same_pw = np.mean([len(x) == len(y) and np.allclose(x, y, atol=1e-6) for x, y in zip(chk.pw, a.pm_p)])
    hl = np.where(np.isfinite(a.h_first), a.h_first, a.h_proxy)
    same_h = np.mean(np.isclose(hl, chk.hedge_px.to_numpy(), atol=1e-6) | (np.isnan(hl) & np.isnan(chk.hedge_px.to_numpy())))
    out["sanity"] = {"pm_window_matches_lens": float(same_pw), "hedge_matches_lens": float(same_h)}
    print("SANITY", out["sanity"], flush=True)
    out["C_competition"] = competition(s, a)
    print(json.dumps(out["C_competition"], indent=1), flush=True)
    out["E_fixed_cell_current"] = fixed_cell_current(s, a)
    out["F_walk_forward"] = {}
    for fam in ("gap", "gaprob"):
        for cfg in ("lens", "central", "central_noanom", "central_queue_noanom", "pess_all"):
            out["F_walk_forward"][f"{fam}:{cfg}"] = walk_forward(s, a, fam, cfg)
    out["n_variants_evaluated_here"] = N_VARIANTS["count"]
    (OUT / "verify_realism.json").write_text(json.dumps(out, indent=1, default=float))
    print("variants evaluated here:", N_VARIANTS["count"])


if __name__ == "__main__":
    main()
