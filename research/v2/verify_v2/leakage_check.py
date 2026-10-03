"""Leakage audit of COURTSIDE v2 (src/v2.py + research/v2/sizing/engine.py) on IS + burned OOS.

    .venv/bin/python research/v2/verify_v2/leakage_check.py     # from the repo root, ~5-8 min, <= 2 processes
      -> research/v2/verify_v2/out/leakage_check.json (+ printed tables)

Reads only data/is_prints.parquet, data/locked/oos_prints.parquet, data/derived/jumps_is.parquet, the cached
event catalogue (via src.tape.universe) and, for the dry-run emulation, cached tapes of 2026-09-01..03 matches.
Never touches the network and never reads anything for matches starting on/after 2026-10-03 13:00 UTC
(all inputs end at 2026-10-03 07:10 UTC match start; asserted below).

Checks (each one re-runs the unchanged v2 pipeline with exactly one thing changed):
  T0 baseline: reproduce scripts/v2_burned_oos.py (13,184 trades, 0.753 c/share).
  T1 future blindness: for each burned-OOS month m, drop every month > m and scramble every outcome column
     (res, mo5, mo15, mo30, mo_res) of month m; month-m shares must not move. Plus a mid-month truncation.
  T2 wallet-filter history: engine.wallet_effect(whist, m) with whist = all 0-3 s prints (incl. m and later)
     vs whist restricted to months < m.
  T3 jump-onset lookahead: the 0-3 s bucket is measured from an onset that the detector only confirms up to
     10 s later. Jump detector recomputed for OOS (validated on IS vs data/derived/jumps_is.parquet).
     (a) share of burned-OOS book P&L from prints before detect_ts; (b) book masked to prints at/after
     detect_ts; (c) strictly after; (d) pre-detect rows removed from the opportunity set (k refitted);
     (e) fully causal relabel: bucket 0-3 s measured from detect_ts for every print (qualification, wallet
     filter and book all re-derived); (f) same with 0 < ts - detect <= 3; (g) book masked to prints strictly
     after the detecting print in tape order (same second allowed); (h) causal relabel in tape order.
  T4 forward_test.py dedup keys ["cond","ts","wallet","p","usd"] applied to IS+OOS.
  T5 50/50 resolutions (res == 0.5) removed from the burned-OOS book.
  T6 fee schedule facts (rate, exponent, NaN -> 0 fill).
  T7 end_ts / lock-up: replace the hindsight match end by ts + 4 h.
  T8 burned-OOS split by print time vs by match start (IS matches still in play after the cutoff).
  T9 forward_test.py dry-run emulation on 2026-09-01..03 (window universe filter, dedup, truncation),
     using cached tapes only and 2 worker processes.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from src import fasttier, tiers, v2  # noqa: E402
from src.tape import universe  # noqa: E402
from scripts.forward_test import cluster_ci as fwd_cluster_ci  # noqa: E402  (exact forward primary statistic)

E = v2.E
OUT = ROOT / "research/v2/verify_v2/out"
COLS = ["cond", "ts", "p", "dir", "usd", "wallet", "since", "fee_rate", "delay", "res", "mo5", "mo15", "mo30",
        "mo_res", "spread", "bucket"]
OUTCOME_COLS = ["res", "mo5", "mo15", "mo30", "mo_res"]
FWD_START = pd.Timestamp("2026-10-03 13:00", tz="UTC")
DEDUP_KEYS = ["cond", "ts", "wallet", "p", "usd"]
WORKERS = 2
T_START = time.time()


def log(*a):
    print(f"[{time.time() - T_START:6.0f}s]", *a, flush=True)


def month_str(ts) -> pd.Series:
    return pd.to_datetime(ts, unit="s").dt.to_period("M").astype(str)


# --------------------------------------------------------------------------------------- pipeline
def stages(p: pd.DataFrame, ends: pd.Series):
    """src/v2.run() split in two so the sizing step can be re-run with masks (same calls, same order)."""
    wf, sh, _ = fasttier.walk_forward(p)
    f = v2.prepare(v2.build_features(sh, p, ends))
    p03 = p[p.bucket == "0-3s"][["wallet", "ts", "mo30"]].copy()
    p03["month"] = pd.to_datetime(p03.ts, unit="s").dt.to_period("M").astype(str)
    return f, p03[["wallet", "month", "mo30"]], wf


def simulate(f: pd.DataFrame, whist: pd.DataFrame, allow=None) -> pd.DataFrame:
    """engine.simulate(f, POLICY, 'res', 'actual', whist) with an optional per-row allow mask on the targets."""
    E._WCACHE.clear()
    pol = v2.POLICY
    months = sorted(m for m in f.month.unique() if m >= E.RUN_START)
    parts = [E.month_targets(f[f.month == m], f[f.month < m], pol, "actual", whist, m, "res") for m in months]
    run = f[f.month >= E.RUN_START].reset_index(drop=True)
    tgt = np.concatenate(parts)
    if allow is not None:
        a = np.asarray(allow(run) if callable(allow) else allow, bool)
        tgt = np.where(a, tgt, 0.0)
    pnl = np.nan_to_num(E.pnl_ps(run, "res", "actual"))
    shares = E.apply_caps(run, tgt, pol, pnl, "res", None)
    tr = run.assign(shares=shares, pnl_ps=pnl, target=tgt)
    tr = tr[tr.shares > 0].copy()
    tr["usd_in"] = tr.shares * tr.q
    tr["pnl"] = tr.shares * tr.pnl_ps
    return tr


KEYS = ("n_trades", "n_matches", "per_share_c", "per_share_ci_c", "per_print_c", "total_pnl_usd", "sharpe_ann",
        "capital_usd", "max_dd_pct", "months_positive", "months_total")


def summarize(tr: pd.DataFrame, oos0: float, label: str, boot: int = 1000) -> dict:
    oos = tr[tr.ts >= oos0]
    out = {"label": label}
    m = E.metrics(oos, n_boot=boot)
    out["burned_oos"] = {k: m.get(k) for k in KEYS}
    if len(oos):
        x = oos.assign(m30_ps=oos.gross30 - (oos.gross_res - oos.pnl_ps)).dropna(subset=["m30_ps"])
        out["burned_oos"]["fwd_primary_m30_per_trade_c"] = [round(100 * v, 4) for v in fwd_cluster_ci(x, "m30_ps")]
        g = oos.groupby("month")
        out["burned_oos"]["by_month_per_share_c"] = (g.pnl.sum() / g.shares.sum() * 100).round(4).to_dict()
    ise = tr[(tr.month >= E.EVAL_START) & (tr.ts < oos0)]
    mi = E.metrics(ise, n_boot=200)
    out["is_eval"] = {k: mi.get(k) for k in ("n_trades", "per_share_c", "per_share_ci_c", "total_pnl_usd", "sharpe_ann")}
    b = out["burned_oos"]
    log(f"{label:<62} OOS n={b['n_trades']:>6} ps={b['per_share_c']:.3f}c CI={np.round(b['per_share_ci_c'], 2).tolist()} "
        f"${b['total_pnl_usd']:,.0f} SR={b['sharpe_ann']:.2f} fwdm30={b.get('fwd_primary_m30_per_trade_c')} | "
        f"IS ps={out['is_eval']['per_share_c']:.3f}c")
    return out


# ------------------------------------------------------------------------------------ jump detector
def _onsets(args):
    cond, ts, p, usd = args
    return [(cond, o[0], o[1], o[2], o[3]) for o in tiers.jump_onsets(ts, p, usd)]


def _onsets_idx(args, J=0.04, short_w=10, long_w=60):
    """Line-for-line copy of tiers.jump_onsets that also returns the tape index of the detecting print."""
    cond, ts, p, usd = args
    pv, v = np.cumsum(p * usd), np.cumsum(usd)
    on, last = [], -1e18
    for i in range(len(ts)):
        now = ts[i]
        if now - last < long_w:
            continue
        a = np.searchsorted(ts, now - short_w, "left")
        b = np.searchsorted(ts, now - short_w - long_w, "left")
        if a <= b or a > i:
            continue
        s1 = pv[i] - (pv[a - 1] if a else 0); w1 = v[i] - (v[a - 1] if a else 0)
        s2 = (pv[a - 1] if a else 0) - (pv[b - 1] if b else 0); w2 = (v[a - 1] if a else 0) - (v[b - 1] if b else 0)
        if w1 <= 0 or w2 <= 0:
            continue
        d = s1 / w1 - s2 / w2
        if abs(d) >= J:
            last = now
            on.append((cond, ts[a], np.sign(d), abs(d), now, i))
    return on


def detect_jumps(p: pd.DataFrame, conds, with_idx: bool = False) -> pd.DataFrame:
    """Jump detector on the in-play tape stored in the prints table (row order = tape order)."""
    sub = p[p.cond.isin(set(conds))]
    jobs = [(c, g.ts.to_numpy(float), g.p.to_numpy(float), g.usd.to_numpy(float))
            for c, g in sub.groupby("cond", sort=False)]
    fn = _onsets_idx if with_idx else _onsets
    with ProcessPoolExecutor(WORKERS) as ex:
        rows = [r for part in ex.map(fn, jobs, chunksize=16) for r in part]
    cols = ["cond", "onset_ts", "dir", "size", "detect_ts"] + (["detect_idx"] if with_idx else [])
    return pd.DataFrame(rows, columns=cols)


def causal_since_idx(p: pd.DataFrame, jumps: pd.DataFrame) -> np.ndarray:
    """Seconds since the latest jump whose DETECTING PRINT comes strictly earlier in the tape; -1 if none."""
    codes, _ = pd.factorize(pd.concat([p.cond, jumps.cond], ignore_index=True))
    cp, cj = codes[:len(p)].astype(np.int64), codes[len(p):].astype(np.int64)
    BIG = np.int64(10_000_000)
    kp = cp * BIG + p.pos.to_numpy().astype(np.int64)
    kj = cj * BIG + jumps.detect_idx.to_numpy().astype(np.int64)
    o = np.argsort(kj, kind="stable")
    kj_s, cj_s, dj_s = kj[o], cj[o], jumps.detect_ts.to_numpy()[o]
    i = np.searchsorted(kj_s, kp, "left") - 1          # detect_idx < pos
    ok = (i >= 0) & (cj_s[np.maximum(i, 0)] == cp)
    return np.where(ok, p.ts.to_numpy() - dj_s[np.maximum(i, 0)], -1.0)


def causal_since(p: pd.DataFrame, jumps: pd.DataFrame, strict: bool) -> np.ndarray:
    """Seconds since the latest jump DETECTION at or before (strict: before) each print; -1 if none."""
    codes, uniq = pd.factorize(pd.concat([p.cond, jumps.cond], ignore_index=True))
    cp, cj = codes[:len(p)].astype(np.int64), codes[len(p):].astype(np.int64)
    BIG = np.int64(10_000_000_000)
    kp = cp * BIG + p.ts.to_numpy().astype(np.int64)
    kj = cj * BIG + jumps.detect_ts.to_numpy().astype(np.int64)
    o = np.argsort(kj, kind="stable")
    kj_s, cj_s, dj_s = kj[o], cj[o], jumps.detect_ts.to_numpy()[o]
    i = np.searchsorted(kj_s, kp, "left" if strict else "right") - 1
    ok = (i >= 0) & (cj_s[np.maximum(i, 0)] == cp)
    return np.where(ok, p.ts.to_numpy() - dj_s[np.maximum(i, 0)], -1.0)


def relabel(p: pd.DataFrame, since_c: np.ndarray, strict: bool) -> pd.DataFrame:
    in03 = (since_c > 0) & (since_c <= 3) if strict else (since_c >= 0) & (since_c < 3)
    cats = p.bucket.cat.categories
    b = pd.Categorical(np.where(in03, "0-3s", "no jump"), categories=cats, ordered=True)
    return p.assign(bucket=b, since=since_c)


def _match_prints(r):
    try:
        return tiers.match_prints(SimpleNamespace(**r))
    except Exception:
        return None


# --------------------------------------------------------------------------------------------- main
def main():
    res = {}
    u = universe()
    assert u.start.max() < FWD_START, "universe reaches into the forward window"
    ends = u.set_index("cond").end
    oos0 = u.loc[u.oos, "start"].min().timestamp()
    oos_conds = set(u.loc[u.oos, "cond"])
    pi = pd.read_parquet("data/is_prints.parquet", columns=COLS)
    po = pd.read_parquet("data/locked/oos_prints.parquet", columns=COLS)
    p = pd.concat([pi, po], ignore_index=True)
    n_is = len(pi)
    del pi, po
    p["rid"] = np.arange(len(p))
    assert p.ts.max() < FWD_START.timestamp() and p.cond.isin(set(u.cond)).all()
    log("prints", len(p), "max ts", pd.to_datetime(p.ts.max(), unit="s", utc=True))

    # ---------------------------------------------------------------- T0 baseline
    f0, wh0, wf0 = stages(p, ends)
    tr0 = simulate(f0, wh0)
    v2.E._WCACHE.clear()
    tr_ref = E.simulate(f0, v2.POLICY, "res", "actual", wh0)
    assert np.allclose(tr_ref.shares.to_numpy(), tr0.shares.to_numpy()) and len(tr_ref) == len(tr0)
    res["T0_baseline"] = summarize(tr0, oos0, "T0 baseline (= scripts/v2_burned_oos.py)")
    assert res["T0_baseline"]["burned_oos"]["n_trades"] == 13184
    base_sh = pd.Series(0.0, index=f0.rid.to_numpy())
    base_sh.loc[tr0.rid.to_numpy()] = tr0.shares.to_numpy()
    base_tg = f0[["rid"]].assign(month=f0.month.to_numpy())

    # ---------------------------------------------------------------- T1 future blindness
    pm_ = month_str(p.ts)
    t1 = []
    rng = np.random.default_rng(7)
    for m in ("2026-08", "2026-09", "2026-10"):
        q = p[pm_ <= m].copy()
        cur = (pm_[pm_ <= m] == m).to_numpy()
        q.loc[cur, "res"] = np.where(q.loc[cur, "res"] == 0.5, 0.5, 1.0 - q.loc[cur, "res"])
        for c in ("mo5", "mo15", "mo30", "mo_res"):
            q.loc[cur, c] = -q.loc[cur, c] + rng.normal(0, 0.05, cur.sum())
        f1, wh1, _ = stages(q, ends)
        tr1 = simulate(f1, wh1)
        rows_m = f0.rid[f0.month == m].to_numpy()
        rows_m1 = f1.rid[f1.month == m].to_numpy()
        s1 = pd.Series(0.0, index=f1.rid.to_numpy())
        s1.loc[tr1.rid.to_numpy()] = tr1.shares.to_numpy()
        same_rows = set(rows_m) == set(rows_m1)
        d = (base_sh.loc[rows_m] - s1.reindex(rows_m).fillna(-1)).abs()
        t1.append({"month": m, "opportunity_rows_identical": bool(same_rows), "rows": int(len(rows_m)),
                   "rows_with_share_change": int((d > 1e-9).sum()), "max_abs_share_change": float(d.max()),
                   "trades_base": int((base_sh.loc[rows_m] > 0).sum()), "trades_scrambled": int((s1.reindex(rows_m) > 0).sum())})
        log("T1", t1[-1])
    # mid-month truncation: prints after 2026-09-15 00:00 removed; earlier September decisions must not move
    cut = pd.Timestamp("2026-09-15", tz="UTC").timestamp()
    f1, wh1, _ = stages(p[p.ts < cut], ends)
    tr1 = simulate(f1, wh1)
    rows = f0.rid[(f0.ts < cut) & (f0.month == "2026-09")].to_numpy()
    s1 = pd.Series(0.0, index=f1.rid.to_numpy()); s1.loc[tr1.rid.to_numpy()] = tr1.shares.to_numpy()
    d = (base_sh.loc[rows] - s1.reindex(rows).fillna(-1)).abs()
    t1.append({"month": "2026-09 truncated at 09-15", "rows": int(len(rows)), "rows_with_share_change": int((d > 1e-9).sum()),
               "max_abs_share_change": float(d.max())})
    log("T1", t1[-1])
    res["T1_future_blindness"] = t1

    # ---------------------------------------------------------------- T2 wallet-filter history
    t2 = []
    for m in ("2026-08", "2026-09", "2026-10"):
        E._WCACHE.clear()
        e_all, pool_all = E.wallet_effect(wh0, m)
        E._WCACHE.clear()
        e_past, pool_past = E.wallet_effect(wh0[wh0.month < m], m)
        E._WCACHE.clear()
        e_leak, pool_leak = E.wallet_effect(wh0.assign(month=np.where(wh0.month == m, "0000-00", wh0.month)), m)
        fm = f0[f0.month == m]
        fee = fm.rate * fm.q * (1 - fm.q)
        keep = lambda eff, pool: (pool + fm.wallet.map(eff).fillna(0.0) - fee) > 0  # noqa: E731
        t2.append({"month": m, "whist_rows_month_ge_m": int((wh0.month >= m).sum()),
                   "identical_to_past_only": bool(e_all == e_past and pool_all == pool_past),
                   "rows_passing_filter": int(keep(e_all, pool_all).sum()),
                   "rows_passing_if_month_m_leaked_in": int(keep(e_leak, pool_leak).sum())})
        log("T2", t2[-1])
    E._WCACHE.clear()
    res["T2_wallet_filter_history"] = t2

    # ---------------------------------------------------------------- T3 jump-onset lookahead
    jis = pd.read_parquet("data/derived/jumps_is.parquet")
    is_conds = p.cond.iloc[:n_is].unique()
    samp = np.random.default_rng(0).choice(is_conds, 300, replace=False)
    jv = detect_jumps(p.iloc[:n_is], samp)
    a = set(map(tuple, jv[["cond", "onset_ts", "detect_ts"]].to_numpy().tolist()))
    b = set(map(tuple, jis[jis.cond.isin(set(samp))][["cond", "onset_ts", "detect_ts"]].to_numpy().tolist()))
    val = {"is_conds_sampled": 300, "jumps_recomputed": len(a), "jumps_in_jumps_is": len(b), "identical": a == b}
    log("T3 detector validation", val)
    assert a == b
    jf = OUT / "leakage_jumps_all_idx.parquet"
    if jf.exists():
        jall = pd.read_parquet(jf)
    else:
        jall = detect_jumps(p, p.cond.unique(), with_idx=True)
        jall.to_parquet(jf)
    # the indexed copy must equal jumps_is.parquet on every IS match and tiers.jump_onsets on OOS
    ji = jall[jall.cond.isin(set(is_conds))]
    a2 = set(map(tuple, ji[["cond", "onset_ts", "detect_ts"]].to_numpy().tolist()))
    b2 = set(map(tuple, jis[["cond", "onset_ts", "detect_ts"]].to_numpy().tolist()))
    oos_samp = np.random.default_rng(1).choice(p.cond.iloc[n_is:].unique(), 200, replace=False)
    jo = detect_jumps(p.iloc[n_is:], oos_samp)
    a3 = set(map(tuple, jo[["cond", "onset_ts", "detect_ts"]].to_numpy().tolist()))
    b3 = set(map(tuple, jall[jall.cond.isin(set(oos_samp))][["cond", "onset_ts", "detect_ts"]].to_numpy().tolist()))
    val.update({"indexed_copy_equals_jumps_is_all_IS": a2 == b2, "indexed_copy_equals_tiers_on_200_oos": a3 == b3})
    assert a2 == b2 and a3 == b3
    p["pos"] = p.groupby("cond", sort=False).cumcount().to_numpy()
    log("jumps", len(ji), "IS +", len(jall) - len(ji), "OOS", val)

    # (a) where the burned-OOS book's prints sit relative to detection
    def with_detect(df):
        x = df.assign(onset_ts=df.ts - df.since).merge(jall[["cond", "onset_ts", "detect_ts", "detect_idx"]],
                                                       on=["cond", "onset_ts"], how="left", validate="many_to_one")
        assert len(x) == len(df) and x.detect_ts.notna().all()
        return x.detect_ts.to_numpy(), x.detect_idx.to_numpy()
    f0["detect_ts"], f0["detect_idx"] = with_detect(f0)
    f0["pos"] = p.pos.to_numpy()[f0.rid.to_numpy()]
    tr0 = tr0.merge(f0[["rid", "detect_ts", "detect_idx", "pos"]], on="rid", how="left")
    oos = tr0[tr0.ts >= oos0]
    pre = (oos.ts < oos.detect_ts).to_numpy()
    sec = (oos.ts == oos.detect_ts).to_numpy()
    after_print = (oos.pos > oos.detect_idx).to_numpy()   # strictly after the detecting print in tape order
    look = {"detector_validation": val,
            "share_trades_at_or_before_detecting_print": float((~after_print).mean()),
            "share_trades_in_detect_second_after_detecting_print": float((sec & after_print).mean()),
            "share_trades_that_are_the_detecting_print": float((oos.pos == oos.detect_idx).mean()),
            "pnl_at_or_before_detecting_print_usd": float(oos.pnl[~after_print].sum()),
            "pnl_after_detecting_print_usd": float(oos.pnl[after_print].sum()),
            "oos_book_trades": int(len(oos)),
            "share_trades_before_detect": float(pre.mean()),
            "share_trades_in_detect_second": float(sec.mean()),
            "share_shares_before_detect": float(oos.shares[pre].sum() / oos.shares.sum()),
            "pnl_before_detect_usd": float(oos.pnl[pre].sum()), "pnl_detect_second_usd": float(oos.pnl[sec].sum()),
            "pnl_after_detect_second_usd": float(oos.pnl[~pre & ~sec].sum()), "pnl_total_usd": float(oos.pnl.sum()),
            "per_share_c_before_detect": float(oos.pnl[pre].sum() / oos.shares[pre].sum() * 100),
            "per_share_c_at_or_after_detect": float(oos.pnl[~pre].sum() / oos.shares[~pre].sum() * 100),
            "m30_net_per_share_c_before_detect": float(((oos.gross30 - (oos.gross_res - oos.pnl_ps)) * oos.shares)[pre].sum()
                                                      / oos.shares[pre & oos.gross30.notna()].sum() * 100),
            "m30_net_per_share_c_at_or_after_detect": float(((oos.gross30 - (oos.gross_res - oos.pnl_ps)) * oos.shares)[~pre].sum()
                                                           / oos.shares[~pre & oos.gross30.notna()].sum() * 100),
            "detect_minus_onset_s_of_oos_trades": (oos.detect_ts - (oos.ts - oos.since)).describe().round(2).to_dict(),
            "ts_minus_detect_s_of_oos_trades": (oos.ts - oos.detect_ts).value_counts().sort_index().to_dict()}
    log("T3a", {k: v for k, v in look.items() if not isinstance(v, dict)})
    res["T3_jump_onset_lookahead"] = look
    res["T3b_mask_ts_ge_detect"] = summarize(simulate(f0, wh0, allow=lambda r: r.ts >= r.detect_ts), oos0,
                                             "T3b book masked to prints with ts >= detect_ts")
    res["T3c_mask_ts_gt_detect"] = summarize(simulate(f0, wh0, allow=lambda r: r.ts > r.detect_ts), oos0,
                                             "T3c book masked to prints with ts > detect_ts")
    res["T3g_mask_after_detecting_print"] = summarize(simulate(f0, wh0, allow=lambda r: r.pos > r.detect_idx), oos0,
                                                      "T3g book masked to prints after the detecting print (tape order)")
    fpost = f0[f0.ts >= f0.detect_ts].reset_index(drop=True)
    res["T3d_drop_pre_detect_rows"] = summarize(simulate(fpost, wh0), oos0,
                                                "T3d pre-detect rows dropped (k refit on post-detect)")
    for strict, key in ((False, "T3e_causal_bucket_from_detect"), (True, "T3f_causal_bucket_strict")):
        sc = causal_since(p, jall, strict)
        pc = relabel(p, sc, strict)
        fc, whc, wfc = stages(pc, ends)
        trc = simulate(fc, whc)
        res[key] = summarize(trc, oos0, f"{key} (qualification+filter+book re-derived)")
        res[key]["n_wallets_by_month"] = dict(zip(wfc.month, wfc.n_wallets.astype(int)))
        res[key]["n_0_3s_prints"] = int((pc.bucket == "0-3s").sum())
        del pc, fc, whc
    sc = causal_since_idx(p, jall)
    pc = relabel(p, sc, False)
    fc, whc, wfc = stages(pc, ends)
    res["T3h_causal_bucket_after_detecting_print"] = summarize(simulate(fc, whc), oos0,
                                                               "T3h causal 0-3 s after the detecting print (tape order)")
    res["T3h_causal_bucket_after_detecting_print"]["n_wallets_by_month"] = dict(zip(wfc.month, wfc.n_wallets.astype(int)))
    res["T3h_causal_bucket_after_detecting_print"]["n_0_3s_prints"] = int((pc.bucket == "0-3s").sum())
    del pc, fc, whc
    res["T3_baseline_n_wallets_by_month"] = dict(zip(wf0.month, wf0.n_wallets.astype(int)))
    res["T3_baseline_n_0_3s_prints"] = int((p.bucket == "0-3s").sum())

    # ---------------------------------------------------------------- T4 forward_test dedup
    dup = p.duplicated(DEDUP_KEYS, keep="first")
    full_dup = p.drop(columns=["rid", "pos"]).duplicated(keep="first")
    d_dir = p[p.duplicated(DEDUP_KEYS, keep=False)].groupby(DEDUP_KEYS, observed=True).dir.nunique()
    dd = {"rows_dropped": int(dup.sum()), "share_dropped": float(dup.mean()),
          "rows_dropped_identical_in_all_columns": int((dup & full_dup).sum()),
          "dup_groups_with_both_directions": int((d_dir > 1).sum()),
          "rows_dropped_in_0_3s_bucket": int((dup & (p.bucket == "0-3s")).sum()),
          "oos_book_trades_that_dedup_drops": int(dup.to_numpy()[tr0.rid[tr0.ts >= oos0].to_numpy()].sum())}
    log("T4", dd)
    pdd = p[~dup]
    fd, whd, _ = stages(pdd, ends)
    res["T4_forward_dedup"] = {"facts": dd, **summarize(simulate(fd, whd), oos0, "T4 IS+OOS with forward_test dedup")}
    del pdd, fd, whd

    # ---------------------------------------------------------------- T5 50/50 resolutions
    half = oos.res == 0.5
    res["T5_half_resolutions"] = {
        "oos_matches_res_half_traded": int(oos.cond[half].nunique()), "oos_trades": int(half.sum()),
        "oos_pnl_usd": float(oos.pnl[half].sum()), "oos_shares": float(oos.shares[half].sum()),
        "res_values_all_prints": sorted(map(float, p.res.dropna().unique())),
        **summarize(simulate(f0, wh0, allow=lambda r: r.res != 0.5), oos0, "T5 book without res=0.5 matches")}

    # ---------------------------------------------------------------- T6 fees
    ev = pd.read_parquet("data/raw/events_tennis_2025-07-01_2026-10-03.parquet", columns=["cond", "fee_rate", "fee_exp"])
    ev = ev[ev.cond.isin(set(u.cond))]
    ev = ev.merge(u[["cond", "start", "oos"]], on="cond")
    res["T6_fees"] = {
        "oos_fee_rate_counts": {str(k): int(v) for k, v in ev[ev.oos].fee_rate.value_counts(dropna=False).items()},
        "fee_exp_counts": {str(k): int(v) for k, v in ev.fee_exp.value_counts(dropna=False).items()},
        "nan_fee_rate_last_start": str(ev[ev.fee_rate.isna()].start.max()),
        "oos_book_fee_rates": sorted(map(float, oos.rate.unique())),
        "is_book_trades_with_rate_0": int(((tr0.ts < oos0) & (tr0.month >= E.EVAL_START) & (tr0.rate == 0)).sum())}
    log("T6", res["T6_fees"])

    # ---------------------------------------------------------------- T7 end_ts / lock-up
    f7 = f0.assign(lock_end=np.minimum(f0.ts + 4 * 3600, f0.ts + E.MAX_LOCK_S))
    tr7 = simulate(f7, wh0)
    res["T7_end_ts_no_hindsight"] = {"shares_identical": bool(np.array_equal(tr7.shares.to_numpy(), tr0.shares.to_numpy())),
                                     **summarize(tr7, oos0, "T7 lock_end = ts + 4 h (no match-end hindsight)")}

    # ---------------------------------------------------------------- T8 burned-OOS split
    is_match = ~oos.cond.isin(oos_conds)
    res["T8_split_by_time_vs_match"] = {
        "oos_trades_from_IS_matches": int(is_match.sum()), "their_pnl_usd": float(oos.pnl[is_match].sum()),
        "per_share_c_oos_matches_only": float(oos.pnl[~is_match].sum() / oos.shares[~is_match].sum() * 100),
        "n_trades_oos_matches_only": int((~is_match).sum())}
    log("T8", res["T8_split_by_time_vs_match"])

    # ---------------------------------------------------------------- T9 forward_test dry-run emulation
    ws, we = pd.Timestamp("2026-09-01", tz="UTC"), pd.Timestamp("2026-09-03", tz="UTC")
    evw = pd.read_parquet("data/raw/events_tennis_2025-07-01_2026-10-03.parquet")
    evw["start"] = pd.to_datetime(evw.start_time, utc=True, format="mixed")
    evw["end"] = pd.to_datetime(evw.finished.fillna(evw.closed_time), utc=True, format="mixed")
    w = evw[evw.series.isin(["atp", "wta", "challenger"]) & (evw.volume >= 5_000) & (evw.start >= ws) & (evw.start < we)
            & evw.res0.isin([0.0, 0.5, 1.0])].copy()          # forward_test.window_universe filters, minus gamma
    w["fee_rate"] = w.fee_rate.fillna(0.0)
    w["delay"] = w.seconds_delay.fillna(1).astype(int)
    w = w.reset_index(drop=True)
    uw = u[(u.start >= ws) & (u.start < we)]
    with ProcessPoolExecutor(WORKERS) as ex:
        fw = [d for d in ex.map(_match_prints, w.to_dict("records"), chunksize=4) if d is not None]
    fw = pd.concat(fw, ignore_index=True)[COLS]
    fw["rid"] = -1 - np.arange(len(fw))
    hist_keys = p[DEDUP_KEYS].assign(_h=1).drop_duplicates(DEDUP_KEYS)
    mk = fw[DEDUP_KEYS].merge(hist_keys, on=DEDUP_KEYS, how="left")._h.notna()
    allp = pd.concat([p, fw], ignore_index=True).drop_duplicates(DEDUP_KEYS)
    ends9 = pd.concat([ends, w.set_index("cond").end]); ends9 = ends9[~ends9.index.duplicated()]
    trunc = allp[pd.to_datetime(allp.ts, unit="s", utc=True) < we]
    lost = allp[(pd.to_datetime(allp.ts, unit="s", utc=True) >= we) & allp.cond.isin(set(w.cond))]
    out9 = {"window": [str(ws), str(we)], "w_matches": int(len(w)), "universe_matches_in_window": int(len(uw)),
            "w_equals_universe_window": set(w.cond) == set(uw.cond), "fw_rows": int(len(fw)),
            "fw_rows_with_history_duplicate": int(mk.sum()),
            "window_match_prints_lost_to_truncation": int(len(lost)),
            "window_match_0_3s_prints_lost_to_truncation": int((lost.bucket == "0-3s").sum())}
    ft = {}
    for name, data in (("dry_as_coded", trunc), ("dry_no_truncation", allp)):
        fz, whz, _ = stages(data, ends9)
        trz = simulate(fz, whz)
        x = trz[trz.cond.isin(set(w.cond))]
        ft[name] = {"n_trades": int(len(x)), "per_share_c": float(x.pnl.sum() / x.shares.sum() * 100) if len(x) else None,
                    "pnl_usd": float(x.pnl.sum())}
    xb = tr0[tr0.cond.isin(set(w.cond))]
    ft["burned_oos_run_same_matches"] = {"n_trades": int(len(xb)), "per_share_c": float(xb.pnl.sum() / xb.shares.sum() * 100),
                                         "pnl_usd": float(xb.pnl.sum())}
    out9["window_trades"] = ft
    res["T9_dry_run_emulation"] = out9
    log("T9", out9)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "leakage_check.json").write_text(json.dumps(res, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    log("wrote", OUT / "leakage_check.json")


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
