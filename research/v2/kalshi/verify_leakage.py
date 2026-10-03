"""Adversarial verification of the Kalshi lens (independent re-implementation; does not import k_common/k05/k06).

What it does (all IS only; never touches data/locked or any OOS match):
  0. OOS hygiene: matched-match start dates, every cached Kalshi trade timestamp, signal/fill timestamps.
  1. Re-derives the 'gap' and 'gaprob' Kalshi-led signals, the Polymarket fill proxy (B = 2 s) and the Kalshi
     hedge from the raw tapes with independent code, and compares row-by-row with data/v2_kalshi/signals_pm.parquet.
  2. Re-runs the walk-forward (G x E grid, >= 150 training trades, stand-aside, 5% PM fee everywhere) with my own loop
     and reproduces the headline (+1.06c primary, +1.22c gaprob; 1 s/5% rows).
  3. Look-ahead probes on the hedge leg: the lens prices the hedge at the FIRST Kalshi print on the hedge side up to
     3 s AFTER the decision time T = t_s + 0.25 + D + 0.5. Alternatives that use only information at T:
       h_now_mid  : Kalshi mid proxy at T (prints <= T) -/+ 0.5c (half the 1c minimum spread)
       h_now_last : last Kalshi print on the hedge side at or before T (<= 5 s old), else the lens' own proxy
     and a VWAP fill for the Polymarket leg (50% of each within-limit print, time order) instead of the first print.
  4. Concentration: $ P&L from match-end trades (hedge at <= 3c or >= 97c) and the top-20 trades.
  5. Lead-lag: share of events where Kalshi leads by more than the mechanical part (PM block offset ~2 s + delay).
Run (repo root): .venv/bin/python research/v2/kalshi/verify_leakage.py
Writes: research/v2/kalshi/out/verify_leakage.json, data/v2_kalshi/verify_signals.parquet
"""
from __future__ import annotations

import glob
import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.tape import load_tape  # noqa: E402

CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")
CUT_TS = CUT.timestamp()
KC = ROOT / "data/v2_kalshi"
OUT = ROOT / "research/v2/kalshi/out"
L, B, W = 0.25, 2, 3.0
GS = [0.0, 0.01, 0.02, 0.03, 0.04, 0.06]
ES = [None, 0.0, 0.01, 0.02, 0.03]


# ----------------------------------------------------------------------------------------------- tapes
def my_kalshi(row):
    out = []
    for tk, is_p1 in ((row["k_tk0"], False), (row["k_tk1"], True)):
        f = KC / "trades" / f"{tk}.parquet"
        if not f.exists():
            return None
        t = pd.read_parquet(f, columns=["yes_price", "count", "taker_side", "block", "ts"])
        t = t[~t.block.astype(bool)]
        if not len(t):
            continue
        y = t.yes_price.to_numpy(float)
        # player-1 market: P(o0) = 1 - yes1; a taker buying NO on player 1 is buying outcome 0 (o0 ask side)
        p0 = 1.0 - y if is_p1 else y
        lifts_o0_ask = (t.taker_side.to_numpy() == ("no" if is_p1 else "yes"))
        out.append(pd.DataFrame({"ts": t.ts.to_numpy(float), "p": p0, "ask": lifts_o0_ask, "q": t["count"].to_numpy(float)}))
    if not out:
        return None
    k = pd.concat(out).sort_values("ts", kind="mergesort").reset_index(drop=True)
    return k


def win(row):
    s = row["start"].timestamp()
    e = min(row["end"], row["k_close"]).timestamp() if pd.notna(row["end"]) else row["k_close"].timestamp()
    return s, e


def side_last(ts, p, T, maxage):
    """price of the last print with ts <= T and age <= maxage (NaN otherwise)"""
    j = np.searchsorted(ts, T, side="right") - 1
    jj = np.clip(j, 0, max(len(ts) - 1, 0))
    if len(ts) == 0:
        return np.full(len(T), np.nan)
    ok = (j >= 0) & (T - ts[jj] <= maxage)
    return np.where(ok, p[jj], np.nan)


def mid_now(ts, p, ask, T, stale=30.0):
    """latest ask-side and bid-side prints <= T, both <= stale s old and not crossed -> their mean; else last print"""
    T = np.asarray(T, float)
    a = side_last(ts[ask], p[ask], T, stale)
    b = side_last(ts[~ask], p[~ask], T, stale)
    j = np.searchsorted(ts, T, side="right") - 1
    last = np.where(j >= 0, p[np.clip(j, 0, len(p) - 1)], np.nan)
    good = np.isfinite(a) & np.isfinite(b) & (a >= b)
    return np.where(good, 0.5 * (a + b), last)


def robust_now(ts, p, ask, T, win_s=5.0):
    """5 s rolling-median per side anchored at that side's last print <= T (valid if <= 5 s old); fallback mid_now"""
    T = np.asarray(T, float)
    base = mid_now(ts, p, ask, T)
    meds = []
    for sd in (True, False):
        tt, pp = ts[ask == sd], p[ask == sd]
        if len(tt) == 0:
            return base
        roll = pd.Series(pp, index=pd.DatetimeIndex(pd.to_datetime(tt, unit="s"))).rolling(
            pd.Timedelta(seconds=win_s), closed="right").median().to_numpy()
        j = np.searchsorted(tt, T, side="right") - 1
        jj = np.clip(j, 0, len(tt) - 1)
        meds.append(np.where((j >= 0) & (T - tt[jj] <= win_s), roll[jj], np.nan))
    a, b = meds
    good = np.isfinite(a) & np.isfinite(b) & (a >= b)
    out = base.copy()
    out[good] = 0.5 * (a[good] + b[good])
    return out


def triggers(kt, kp, ka, pt, pp, pa, robust):
    f = robust_now if robust else mid_now
    km = f(kt, kp, ka, kt)
    kprev = f(kt, kp, ka, kt - 10.0)
    pmm = mid_now(pt, pp, pa, kt)
    mv, gp = km - kprev, km - pmm
    idx = np.flatnonzero(np.isfinite(mv) & np.isfinite(gp) & (np.abs(mv) >= 0.02) & (np.abs(gp) >= 0.02)
                         & (np.sign(mv) == np.sign(gp)))
    out, last = [], -np.inf
    for i in idx:
        if kt[i] - last < 20.0:
            continue
        last = kt[i]
        out.append((kt[i], int(np.sign(mv[i])), km[i]))
    return out


def first_on_side(ts, p, T, w=W):
    i = np.searchsorted(ts, T, side="left")
    if i >= len(ts) or ts[i] > T + w:
        return None
    return i


# ----------------------------------------------------------------------------------------------- per match
def one(row):
    pmt = load_tape(row["cond"])
    k = my_kalshi(row)
    if pmt is None or k is None:
        return []
    s, e = win(row)
    pmt = pmt[(pmt.timestamp >= s) & (pmt.timestamp <= e)]
    k = k[(k.ts >= s) & (k.ts <= e)].reset_index(drop=True)
    if len(pmt) < 20 or len(k) < 20:
        return []
    pt, pp, pa, pq_ = (pmt.timestamp.to_numpy(float), pmt.p0.to_numpy(float), pmt.at_ask.to_numpy(bool),
                       pmt["size"].to_numpy(float))
    kt, kp, ka = k.ts.to_numpy(), k.p.to_numpy(), k.ask.to_numpy(bool)
    rows = []
    for fam, robust in (("gap", False), ("gaprob", True)):
        for t_s, d, km in triggers(kt, kp, ka, pt, pp, pa, robust):
            fair = km if robust else mid_now(kt, kp, ka, [t_s])[0]
            own = mid_now(pt, pp, pa, [t_s])[0]
            t_exec = np.ceil(t_s + L + row["delay"] + B)
            side = pa if d > 0 else ~pa
            st, sp, sq = pt[side], pp[side], pq_[side]
            i = first_on_side(st, sp, t_exec)
            if i is None:
                continue
            ts_f, p_f = st[i], sp[i]
            j = np.searchsorted(st, ts_f + W, side="right")
            pw, qw = sp[i:j], sq[i:j]
            T = t_s + L + row["delay"] + 0.5
            hs = ka if (-d) > 0 else ~ka          # hedge side: -d (d=+1 -> sell o0 on Kalshi -> bid side)
            ht, hp = kt[hs], kp[hs]
            oth_t, oth_p = kt[~hs], kp[~hs]
            jh = first_on_side(ht, hp, T)
            proxy = side_last(oth_t, oth_p, np.array([T]), 5.0)[0] + (-d) * 0.02
            h_strict = hp[jh] if jh is not None else np.nan
            h_base = h_strict if jh is not None else proxy
            h_wait = ht[jh] - T if jh is not None else np.nan
            last_h = side_last(ht, hp, np.array([T]), 5.0)[0]
            h_now_last = last_h if np.isfinite(last_h) else proxy
            kmT = mid_now(kt, kp, ka, [T])[0]
            h_now_mid = kmT - d * 0.005
            rec = dict(cond=row["cond"], month=row["month"], fee_rate=row["fee_rate"], delay=row["delay"],
                       res0=row["res0"], k_settle0=row["k_settle0"], fam=fam, t_s=t_s, d=d, fair=fair, own=own,
                       gap=d * (fair - own), ts_f=ts_f, p_f=p_f, edge_f=d * (fair - p_f), h_base=h_base,
                       h_strict=h_strict, h_wait=h_wait, h_now_last=h_now_last, h_now_mid=h_now_mid, kmid_T=kmT,
                       k_end=float(kp[-1]))
            for E in ES:
                ok = np.ones(len(pw), bool) if E is None else (d * (fair - pw) >= E - 1e-9)
                lv = qw[ok].sum()
                tgt = min(1000.0 / p_f, 0.5 * lv)
                # VWAP of the shares actually taken: 50% of each within-limit print, in time order, up to tgt
                take = 0.5 * qw[ok]
                cum = np.cumsum(take)
                tk = np.clip(np.minimum(cum, tgt) - np.concatenate([[0.0], np.minimum(cum, tgt)[:-1]]), 0, None)
                vw = (tk * pw[ok]).sum() / tk.sum() if tk.sum() > 0 else np.nan
                key = "none" if E is None else f"{int(round(E * 100))}"
                rec[f"lv_{key}"] = lv
                rec[f"vw_{key}"] = vw
            rows.append(rec)
    return rows


# ----------------------------------------------------------------------------------------------- walk-forward
def pnl_cols(t, hcol, pcol="p_f"):
    p = t[pcol].to_numpy()
    h = t[hcol].to_numpy()
    d = t.d.to_numpy()
    return d * (h - p) + d * (t.res0.to_numpy() - t.k_settle0.to_numpy()) - 0.05 * p * (1 - p) - 0.07 * h * (1 - h)


def sel(t, G, E):
    m = t.gap >= G - 1e-9
    if E is not None:
        m &= t.edge_f >= E - 1e-9
    return t[m]


def size(te, E):
    key = "none" if E is None else f"{int(round(E * 100))}"
    te = te.sort_values("ts_f", kind="mergesort").copy()
    sh = np.minimum(1000.0 / te.p_f.to_numpy(), 0.5 * te[f"lv_{key}"].to_numpy())
    usd = sh * te.p_f.to_numpy()
    out_usd = np.zeros(len(te))
    spent = {}
    for n, (c, u) in enumerate(zip(te.cond.to_numpy(), usd)):
        room = max(0.0, 3000.0 - spent.get(c, 0.0))
        out_usd[n] = min(u, room)
        spent[c] = spent.get(c, 0.0) + u   # lens caps on cumulative REQUESTED usd (prev = cum - usd_in)
    te["usd_in"] = out_usd
    te["shares"] = out_usd / te.p_f.to_numpy()
    te["vw"] = te[f"vw_{key}"]
    return te[te.shares > 0]


def wf(t, col):
    months = sorted(t.month.unique())
    res, picks = [], []
    for i, m in enumerate(months):
        if i < 2:
            continue
        tr = t[t.month < m]
        best = None
        for G, E in itertools.product(GS, ES):
            x = sel(tr, G, E)[col].dropna()
            if len(x) < 150:
                continue
            key = (x.mean(), len(x))
            if best is None or key > best[0]:
                best = (key, G, E)
        if best is None or best[0][0] <= 0:
            picks.append((m, None, None))
            continue
        _, G, E = best
        picks.append((m, G, E))
        te = size(sel(t[t.month == m], G, E).dropna(subset=[col]), E)
        te = te.assign(pnl_ps=te[col], pnl=te[col] * te.shares)
        res.append(te)
    return (pd.concat(res, ignore_index=True) if res else pd.DataFrame()), picks


def boot(tr, n=2000, seed=0):
    g = tr.groupby("cond").pnl_ps.agg(["sum", "size"])
    rng = np.random.default_rng(seed)
    s, c = g["sum"].to_numpy(), g["size"].to_numpy()
    bs = [s[ix].sum() / c[ix].sum() for ix in (rng.integers(0, len(g), len(g)) for _ in range(n))]
    return [round(100 * float(np.percentile(bs, 2.5)), 3), round(100 * float(np.percentile(bs, 97.5)), 3)]


def summ(tr):
    if tr is None or not len(tr):
        return {"n": 0}
    cur = tr[(tr.fee_rate == 0.05) & (tr.delay == 1)]
    o = {"n": int(len(tr)), "c": round(100 * tr.pnl_ps.mean(), 3), "ci": boot(tr), "usd": round(float(tr.pnl.sum()), 1),
         "months_usd_pos": int((tr.groupby("month").pnl.sum() > 0).sum()),
         "months_c_pos": int((tr.groupby("month").pnl_ps.mean() > 0).sum()), "months": int(tr.month.nunique()),
         "n_1s5": int(len(cur))}
    if len(cur):
        o.update({"c_1s5": round(100 * cur.pnl_ps.mean(), 3), "ci_1s5": boot(cur), "usd_1s5": round(float(cur.pnl.sum()), 1)})
    return o


def main():
    R = {}
    # ---- 0. OOS hygiene
    m = pd.read_parquet(KC / "matched.parquet")
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["cond", "start"])
    kmax, nrows = -np.inf, 0
    for f in glob.glob(str(KC / "trades" / "*.parquet")):
        tcol = pq.read_table(f, columns=["ts"]).column("ts").to_numpy()
        nrows += len(tcol)
        if len(tcol):
            kmax = max(kmax, float(np.nanmax(tcol)))
    sp = pd.read_parquet(KC / "signals_pm.parquet", columns=["t_s", "ts_f"])
    R["oos"] = {"matched_n": int(len(m)), "matched_start_max": str(m.start.max()),
                "matched_all_in_universe_is": bool(m.cond.isin(u.cond).all()),
                "n_matched_start_ge_cut": int((m.start >= CUT).sum()),
                "kalshi_trade_rows": int(nrows), "kalshi_max_ts": str(pd.to_datetime(kmax, unit="s", utc=True)),
                "kalshi_rows_ge_cut": int(kmax >= CUT_TS),
                "signals_max_ts_f": str(pd.to_datetime(sp.ts_f.max(), unit="s", utc=True)),
                "code_reads_data_locked": False}
    print("OOS", R["oos"], flush=True)

    # ---- 1. independent signal/fill/hedge rebuild
    cache = KC / "verify_signals.parquet"
    if cache.exists():
        v = pd.read_parquet(cache)
    else:
        m2 = m[m.start < CUT].copy()
        m2["month"] = m2.start.dt.strftime("%Y-%m")
        rows = m2.to_dict("records")
        with ProcessPoolExecutor(2) as ex:
            parts = list(ex.map(one, rows, chunksize=16))
        v = pd.DataFrame([r for p in parts for r in p])
        v.to_parquet(cache)
    print("rebuilt rows", len(v), v.groupby("fam").size().to_dict(), flush=True)

    lens = pd.read_parquet(KC / "signals_pm.parquet",
                           columns=["cond", "fam", "B", "t_s", "d", "fair", "gap", "ts_f", "p_f", "edge_f", "hedge_px",
                                    "hedge_px_strict"])
    lens = lens[(lens.B == 2) & lens.fam.isin(["gap", "gaprob"])]
    lens["key"] = lens.t_s.round(4)
    v["key"] = v.t_s.round(4)
    mg = lens.merge(v, on=["cond", "fam", "key"], how="outer", suffixes=("_l", "_v"), indicator=True)
    both = mg[mg._merge == "both"]
    R["row_match"] = {
        "lens_rows": int(len(lens)), "verify_rows": int(len(v)), "both": int(len(both)),
        "lens_only": int((mg._merge == "left_only").sum()), "verify_only": int((mg._merge == "right_only").sum()),
        "d_agree": float((both.d_l == both.d_v).mean()),
        "p_f_maxabs": float((both.p_f_l - both.p_f_v).abs().max()),
        "fair_maxabs": float((both.fair_l - both.fair_v).abs().max()),
        "gap_maxabs": float((both.gap_l - both.gap_v).abs().max()),
        "hedge_px_maxabs": float((both.hedge_px - both.h_base).abs().max()),
        "hedge_px_mismatch_share": float(((both.hedge_px - both.h_base).abs() > 1e-6).mean()),
    }
    print("ROWMATCH", R["row_match"], flush=True)

    # ---- 2/3. walk-forward with alternative hedge / fill prices
    v = v[v.p_f.between(0.05, 0.95)].copy()
    v["ps_base"] = pnl_cols(v, "h_base")
    v["ps_strict"] = pnl_cols(v, "h_strict")
    v["ps_now_mid"] = pnl_cols(v, "h_now_mid")
    v["ps_now_last"] = pnl_cols(v, "h_now_last")
    v["hedge_drift_c"] = 100 * v.d * (v.h_base - v.h_now_mid)
    R["wf"] = {}
    for fam in ("gap", "gaprob"):
        t = v[v.fam == fam]
        for col in ("ps_base", "ps_strict", "ps_now_mid", "ps_now_last"):
            tr, picks = wf(t, col)
            R["wf"][f"{fam}:{col}"] = summ(tr)
            R["wf"][f"{fam}:{col}"]["picks"] = [(a, b, c) for a, b, c in picks]
            print(fam, col, R["wf"][f"{fam}:{col}"], flush=True)
            if col == "ps_base":
                # VWAP fill for the PM leg instead of the first print (same trades, same hedge)
                vwp = tr.copy()
                vwp["pnl_ps"] = (vwp.d * (vwp.h_base - vwp.vw) + vwp.d * (vwp.res0 - vwp.k_settle0)
                                 - 0.05 * vwp.vw * (1 - vwp.vw) - 0.07 * vwp.h_base * (1 - vwp.h_base))
                vwp["pnl"] = vwp.pnl_ps * vwp.shares
                R["wf"][f"{fam}:ps_base_vwapfill"] = summ(vwp)
                # concentration
                endm = (tr.h_base <= 0.03) | (tr.h_base >= 0.97)
                R["wf"][f"{fam}:ps_base_concentration"] = {
                    "share_wtd_c": round(float(100 * tr.pnl.sum() / tr.shares.sum()), 3),
                    "usd_total": round(float(tr.pnl.sum()), 1),
                    "usd_top20": round(float(tr.pnl.nlargest(20).sum()), 1),
                    "n_match_end_hedges": int(endm.sum()), "usd_match_end": round(float(tr.pnl[endm].sum()), 1),
                    "c_excl_match_end": round(float(100 * tr.pnl_ps[~endm].mean()), 3),
                    "usd_excl_top20": round(float(tr.pnl.sum() - tr.pnl.nlargest(20).sum()), 1),
                    "mean_hedge_drift_c(h_base vs mid@T)": round(float(tr.hedge_drift_c.mean()), 3),
                    "median_hedge_drift_c": round(float(tr.hedge_drift_c.median()), 3),
                    "mean_hedge_drift_c_1s5": round(float(tr[(tr.fee_rate == 0.05) & (tr.delay == 1)].hedge_drift_c.mean()), 3),
                }
                print("  vwap", R["wf"][f"{fam}:ps_base_vwapfill"], "\n  conc", R["wf"][f"{fam}:ps_base_concentration"],
                      flush=True)

    # baseline claim: G=0, E=none hedge mean in 1 s/5% months vs all months
    g = v[v.fam == "gap"]
    cur = g[(g.fee_rate == 0.05) & (g.delay == 1)]
    R["baseline_G0_Enone_hedge_c"] = {"all_IS": round(float(100 * g.ps_base.mean()), 3),
                                      "only_1s5pct_months": round(float(100 * cur.ps_base.mean()), 3),
                                      "lens_reported": -2.978}

    # ---- 5. lead-lag beyond the mechanical offset
    ev = pd.read_parquet(OUT / "leadlag_events.parquet")
    b = ev[(ev.move_pm >= 0.02) & (ev.move_k >= 0.02) & ev.t50_pm.notna() & ev.t50_k.notna()].copy()
    b["lead"] = b.t50_pm - b.t50_k
    R["leadlag"] = {"n": int(len(b)), "p_kalshi_first": round(float((b.lead > 0).mean()), 4),
                    "p_lead_gt_2s(block offset)": round(float((b.lead > 2).mean()), 4),
                    "p_lead_gt_2s_plus_delay": round(float((b.lead > 2 + b.delay).mean()), 4),
                    "median_lead_minus_2s_minus_delay": float((b.lead - 2 - b.delay).median())}
    R["leadlag"]["median_lead_by_delay"] = {int(k): float(x.lead.median()) for k, x in b.groupby("delay")}
    print("LEADLAG", R["leadlag"])

    # ---- 6. float32 sizing bug in k06.size_trades: pw stored as float32 in k05, so a fill exactly at the limit
    #         fails d*(fair - pw) >= E - 1e-9 and gets lim_vol = 0 -> shares = 0 -> silently dropped from the test month
    lpw = pd.read_parquet(KC / "signals_pm.parquet", columns=["cond", "fam", "B", "t_s", "pw", "qw"])
    lpw = lpw[(lpw.B == 2) & lpw.fam.isin(["gap", "gaprob"])]
    lpw["key"] = lpw.t_s.round(4)
    R["float32_bug"] = {}
    for fam, lens_name in (("gap", "pm_gap_curfee_ps_hedge"), ("gaprob", "pm_gaprob_curfee_ps_hedge")):
        tr, _ = wf(v[v.fam == fam], "ps_base")
        tr["key"] = tr.t_s.round(4)
        tr = tr.merge(lpw[lpw.fam == fam][["cond", "key", "pw", "qw"]], on=["cond", "key"], how="left")
        lv32 = np.array([q[(d * (f - pw)) >= 0.03 - 1e-9].sum() for pw, q, d, f in zip(tr.pw, tr.qw, tr.d, tr.fair)])
        tr["dropped_by_lens_float32"] = lv32 <= 0
        keep = tr[~tr.dropped_by_lens_float32]
        lens_tr = pd.read_parquet(OUT / f"trades_wf_{lens_name}.parquet", columns=["pnl_ps"])
        R["float32_bug"][fam] = {"my_wf_float64": summ(tr.drop(columns=["pw", "qw"])),
                                 "my_wf_with_lens_float32_drop": summ(keep.drop(columns=["pw", "qw"])),
                                 "lens_reported_n": int(len(lens_tr)),
                                 "lens_reported_c": round(float(100 * lens_tr.pnl_ps.mean()), 3),
                                 "n_dropped": int(tr.dropped_by_lens_float32.sum()),
                                 "dropped_mean_c": round(float(100 * tr[tr.dropped_by_lens_float32].pnl_ps.mean()), 3)}
        print("FLOAT32", fam, R["float32_bug"][fam])

    # ---- 7. hedge priced at a print that occurred after a large post-T Kalshi move (look-ahead outliers)
    out7 = {}
    for fam in ("gap", "gaprob"):
        tr, _ = wf(v[v.fam == fam], "ps_base")
        jump_after_T = (tr.h_base - tr.kmid_T).abs() > 0.10
        out7[fam] = {"n": int(jump_after_T.sum()), "usd": round(float(tr.pnl[jump_after_T].sum()), 1),
                     "c_contrib": round(float(100 * tr.pnl_ps[jump_after_T].sum() / len(tr)), 3),
                     "rows": tr.loc[jump_after_T, ["month", "d", "fair", "p_f", "kmid_T", "h_base", "pnl_ps", "pnl"]]
                     .round(3).to_dict("records")}
    R["hedge_after_T_jumps"] = out7
    print("HEDGE>T JUMPS", {k: {kk: vv for kk, vv in x.items() if kk != "rows"} for k, x in out7.items()})

    # ---- 8. B sensitivity in the CURRENT regime (strict and base hedge), using the lens' own B=0/4 signal rows
    #         (B=2 rows were verified identical above). RESULTS.md quotes +2.29/+0.19/-0.48c (gap strict) and
    #         +3.06/+0.99/-0.28c (gaprob strict) but no script in the lens writes these numbers.
    sp = pd.read_parquet(KC / "signals_pm.parquet")
    sp = sp[sp.fam.isin(["gap", "gaprob"]) & sp.p_f.between(0.05, 0.95)]
    out8 = {}
    for fam in ("gap", "gaprob"):
        for Bv in (0, 2, 4):
            t = sp[(sp.fam == fam) & (sp.B == Bv)].copy()
            t["h_base"], t["h_strict"] = t.hedge_px, t.hedge_px_strict
            t["ps_base"] = pnl_cols(t, "h_base")
            t["ps_strict"] = pnl_cols(t, "h_strict")
            for E in ES:  # lens-equivalent limit volume (float64)
                key = "none" if E is None else f"{int(round(E * 100))}"
                t[f"lv_{key}"] = [q[(d * (f - pw.astype(np.float64))) >= E - 1e-6].sum() if E is not None else q.sum()
                                  for pw, q, d, f in zip(t.pw, t.qw, t.d, t.fair)]
                t[f"vw_{key}"] = np.nan
            for col in ("ps_base", "ps_strict"):
                trB, _ = wf(t, col)
                s_ = summ(trB)
                out8[f"{fam}:{col}:B{Bv}"] = {k: s_.get(k) for k in ("n", "c", "ci", "n_1s5", "c_1s5", "ci_1s5")}
                print("BSENS", fam, col, Bv, out8[f"{fam}:{col}:B{Bv}"], flush=True)
    R["B_sensitivity_current_regime"] = out8
    (OUT / "verify_leakage.json").write_text(json.dumps(R, indent=1, default=str))


if __name__ == "__main__":
    main()
