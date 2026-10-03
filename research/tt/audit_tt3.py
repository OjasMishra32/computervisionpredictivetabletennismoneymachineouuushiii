"""Audit: independent recompute of the TT3 primary (frozen v2, causal) on table tennis, IS and OOS.

    python research/tt/audit_tt3.py      # -> results/tt/audit_tt3.json (logged in results/tt/peeks.log)

Independent of the builder's code path: it does NOT import scripts/tt_analyze.py, scripts/tt_build.py,
src.tiers or src.fasttier. The universe, in-play window, jump detector (J = 0.04, 10 s / 60 s windows,
60 s refractory), causal 0-3 s bucket (seconds since the latest DETECTION), mid proxy, 30 s markout and the
walk-forward H6 wallet qualification (>= 30 prints, >= 10 matches, t > 3, months[2:] of print months) are
re-implemented from HYPOTHESIS_TT.md / HYPOTHESIS_V2.md and read straight from the catalogue and the raw tapes.

Afterwards, separately, it (a) checks the rebuilt prints against data/tt/prints.parquet + add_causal_bucket and
(b) calls src.v2.run(P, ends, causal=True) unchanged, to record what the frozen rule does on this input.
Post-hoc diagnostics are labelled as such; none is a rule or changes a verdict.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CAT = ROOT / "data/raw/events_table-tennis_2025-07-01_2026-10-03.parquet"
TR = ROOT / "data/raw/trades"
OUT = ROOT / "results/tt/audit_tt3.json"


def universe() -> pd.DataFrame:
    assert hashlib.sha256(CAT.read_bytes()).hexdigest().startswith("daa48f2c")
    c = pd.read_parquet(CAT)
    u = c[(c.volume > 0) & c.res0.isin([0.0, 0.5, 1.0])].copy()
    u["start"] = pd.to_datetime(u.start_time, utc=True)
    u["end"] = pd.to_datetime(u.finished.fillna(u.closed_time), utc=True, format="mixed")
    u["fee_rate"] = u.fee_rate.fillna(0.0)
    u["delay"] = u.seconds_delay.fillna(1).astype(int)
    u = u.sort_values("start", kind="stable").reset_index(drop=True)
    u["oos"] = u.start >= u.start.iloc[int(len(u) * 0.8)]
    s = u.series.fillna("").str.lower()
    u["league"] = np.where(s.str.startswith("wtt"), "WTT", np.where(s.str.startswith("setka"), "Setka", "other"))
    return u


def detections(ts, p, usd, J=0.04, sw=10, lw=60):
    """Detection times: VWAP of prints in [t-sw, t] (up to this print) vs VWAP in [t-sw-lw, t-sw); refractory lw."""
    out, last, idx = [], -np.inf, np.arange(len(ts))
    for i in range(len(ts)):
        t = ts[i]
        if t - last < lw:
            continue
        sm = (ts >= t - sw) & (idx <= i)
        lm = (ts >= t - sw - lw) & (ts < t - sw)
        if not lm.any():
            continue
        w1, w2 = usd[sm].sum(), usd[lm].sum()
        if w1 <= 0 or w2 <= 0:
            continue
        d = (p[sm] * usd[sm]).sum() / w1 - (p[lm] * usd[lm]).sum() / w2
        if abs(d) >= J:
            last = t
            out.append((t, np.sign(d)))
    return out


def mid_proxy(ts, p, at_ask, stale=30):
    mid = p.copy()
    la = lb = None
    ta = tb = -np.inf
    for i in range(len(ts)):
        if at_ask[i]:
            la, ta = p[i], ts[i]
        else:
            lb, tb = p[i], ts[i]
        if la is not None and lb is not None and ts[i] - ta <= stale and ts[i] - tb <= stale and la >= lb:
            mid[i] = (la + lb) / 2
    return mid


def rebuild(u: pd.DataFrame):
    rows, status = [], []
    for r in u.itertuples():
        f = TR / f"{r.cond}.parquet"
        if not f.exists():
            status.append("no_tape"); continue
        t = pd.read_parquet(f)
        if t.empty:
            status.append("empty_tape"); continue
        t = t[(t.timestamp >= int(r.start.timestamp())) & (t.timestamp <= int(r.end.timestamp()))].reset_index(drop=True)
        if len(t) < 20:
            status.append("lt20_inplay"); continue
        ts = t.timestamp.to_numpy(float)
        p = np.where(t.outcomeIndex == 0, t.price, 1 - t.price).astype(float)
        at_ask = (((t.side == "BUY") & (t.outcomeIndex == 0)) | ((t.side == "SELL") & (t.outcomeIndex == 1))).to_numpy()
        usd = (t["size"] * t["price"]).to_numpy(float)
        det = detections(ts, p, usd)
        if not det:  # tennis builders drop >= 20-print matches with no jump (onsets and detections are empty together)
            status.append("no_jump"); continue
        status.append("ok")
        dts = np.array([d[0] for d in det])
        k = np.searchsorted(dts, ts, "right") - 1
        since = np.where(k >= 0, ts - dts[np.maximum(k, 0)], -1.0)
        d = np.where(at_ask, 1.0, -1.0)
        mid = mid_proxy(ts, p, at_ask)
        j = np.searchsorted(ts, ts + 30, "left")
        mo30 = np.where(j < len(ts), d * (mid[np.minimum(j, len(ts) - 1)] - p), np.nan)
        rows.append(pd.DataFrame({"cond": r.cond, "ts": ts, "p": p, "dir": d, "usd": usd, "wallet": t.proxyWallet.to_numpy(),
                                  "since_det": since, "mo30": mo30, "fee_rate": r.fee_rate, "delay": r.delay,
                                  "res": r.res0, "oos": r.oos, "league": r.league, "start": r.start}))
    X = pd.concat(rows, ignore_index=True)
    X["b03"] = (X.since_det >= 0) & (X.since_det < 3)
    X["month"] = pd.to_datetime(X.ts, unit="s").dt.to_period("M").astype(str)
    return X, pd.Series(status).value_counts().to_dict()


def tstats(past: pd.DataFrame) -> pd.DataFrame:
    g = past.groupby("wallet").agg(n=("mo30", "size"), nm=("cond", "nunique"), mean=("mo30", "mean"), sd=("mo30", "std"))
    g["t"] = g["mean"] / (g.sd / np.sqrt(g.nm))
    return g


def walk_forward(X: pd.DataFrame):
    months = sorted(X.month.unique())
    rows, shadow = [], []
    for m in months[2:]:
        past = X[(X.month < m) & X.b03]
        g = tstats(past)
        q = g[(g.n >= 30) & (g.nm >= 10) & (g.sd > 0) & (g.t > 3)]
        top = g.sort_values("n", ascending=False).head(1)
        rows.append({"month": m, "prior_matches": int(X[X.month < m].cond.nunique()),
                     "count_bar_reachable": bool(X[X.month < m].cond.nunique() >= 10),
                     "prior_b03_prints": int(len(past)), "prior_b03_wallets": int(len(g)),
                     "most_active_wallet_prints": int(top.n.iloc[0]) if len(top) else 0,
                     "most_active_wallet_matches": int(top.nm.iloc[0]) if len(top) else 0,
                     "most_active_wallet_t": float(top.t.iloc[0]) if len(top) and np.isfinite(top.t.iloc[0]) else None,
                     "qualified": int(len(q)), "month_b03_prints": int((X[X.month == m].b03).sum())})
        shadow.append(X[(X.month == m) & X.b03 & X.wallet.isin(q.index)])
    return rows, pd.concat(shadow) if shadow else X.iloc[:0]


def cluster(d: pd.DataFrame, col: str, w: str | None = None, n_boot: int = 2000):
    d = d.assign(_w=1.0 if w is None else d[w])
    g = d.assign(_x=d[col] * d._w).groupby("cond")[["_x", "_w"]].sum()
    x, ww, k = g._x.to_numpy(), g._w.to_numpy(), len(g)
    rng = np.random.default_rng(0)
    bs = [x[i].sum() / ww[i].sum() for i in (rng.integers(0, k, k) for _ in range(n_boot))]
    return {"c": 100 * x.sum() / ww.sum(), "ci_c": [100 * np.percentile(bs, 2.5), 100 * np.percentile(bs, 97.5)], "matches": k}


def main():
    u = universe()
    X, status = rebuild(u)
    wf, sh = walk_forward(X)
    res = {"universe": {"markets": len(u), "is": int((~u.oos).sum()), "oos": int(u.oos.sum()),
                        "cut": str(u[u.oos].start.min())},
           "build_status": status,
           "evaluable": {f"{lg}/{'OOS' if o else 'IS'}": int(g.cond.nunique()) for (lg, o), g in X.groupby(["league", "oos"])},
           "print_rows": int(len(X)),
           "b03_by_period": {("OOS" if o else "IS"): {"prints": int(g.b03.sum()), "matches": int(g[g.b03].cond.nunique()),
                                                      "usd": float(g[g.b03].usd.sum())} for o, g in X.groupby("oos")},
           "walk_forward": wf, "shadow_rows": int(len(sh))}
    prim = {}
    for name, flag in (("IS", False), ("OOS", True)):
        s = sh[sh.oos == flag]
        n_m = int(s.cond.nunique())
        prim[name] = {"opportunity_rows": int(len(s)), "matches_with_trades": n_m,
                      "evaluable_matches_in_period": int(X[X.oos == flag].cond.nunique()),
                      "verdict": "FAIL (no trades)" if s.empty else "needs v2 sizing (shadow non-empty)",
                      "underpowered": n_m < 30}
    res["TT3_primary_independent"] = prim

    # (a) parity with the builder's prints + causal bucket (code path of the study)
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from src import tiers, v2  # noqa: E402
    P = pd.read_parquet(ROOT / "data/tt/prints.parquet")
    Pc = tiers.add_causal_bucket(P).sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    A = X.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    par = {"rows_equal": len(A) == len(Pc), "conds_equal": set(A.cond) == set(Pc.cond)}
    if par["rows_equal"]:
        for col in ("p", "dir", "usd", "since_det", "mo30"):
            a, b = A[col].to_numpy(float), Pc[col].to_numpy(float)
            par[f"{col}_max_abs_diff"] = float(np.nanmax(np.abs(a - b)))
            par[f"{col}_nan_mismatch"] = int((np.isnan(a) != np.isnan(b)).sum())
        par["b03_equal"] = bool((A.b03.to_numpy() == (Pc.bucket_c == "0-3s").to_numpy()).all())
    res["parity_with_data_tt_prints"] = par
    # (b) the frozen rule itself, unchanged
    U = pd.read_parquet(ROOT / "data/tt/universe.parquet")
    try:
        tr, _ = v2.run(P, U.set_index("cond").end, causal=True)
        res["src_v2_run"] = {"ok": True, "trades": int(len(tr))}
    except Exception as err:
        frames = [f for f in traceback.extract_tb(err.__traceback__) if f.filename.endswith("src/v2.py")]
        res["src_v2_run"] = {"ok": False, "error": repr(err),
                             "where": [f"src/v2.py:{f.lineno} {f.name}: {f.line}" for f in frames]}

    # post-hoc diagnostics (NOT pre-registered; change no verdict)
    B = X[X.b03].copy()
    g_all = tstats(B)
    top = g_all.sort_values("n", ascending=False).index[0]
    B["q"] = np.where(B.dir > 0, B.p, 1 - B.p)
    B["net_res"] = B.dir * (B.res - B.p) - B.fee_rate * B.p * (1 - B.p)
    B["sh"] = np.minimum(B.usd, 1000) / B.q
    days = (u.start.max().normalize() - u.start.min().normalize()).days + 1
    res["posthoc"] = {
        "label": "post-hoc diagnostics, not pre-registered, no verdict change",
        "most_active_b03_wallet_all_months": {"prints": int(g_all.loc[top, "n"]), "matches": int(g_all.loc[top, "nm"]),
                                              "t_mo30": float(g_all.loc[top, "t"]),
                                              "share_of_b03_prints": float(g_all.loc[top, "n"] / len(B)),
                                              "share_of_all_print_rows": float((X.wallet == top).mean())},
        "copy_every_b03_print_net_res": {
            ("OOS" if o else "IS"): {"prints": int(len(d)), "usd": float(d.usd.sum()),
                                     "print_weighted": cluster(d, "net_res"), "share_weighted": cluster(d, "net_res", "sh")}
            for o, d in B.groupby("oos")},
        "copy_every_b03_print_note": "upper bound on v2's opportunity set (every 0-3 s print, any wallet, hold to resolution, "
                                     "net of each market's fee); OOS has 3 clusters, so its CI is not interpretable",
        "most_active_wallet_share_of_tt2_others_prints": float(
            (B[B.month.isin([w["month"] for w in wf]) & B.mo30.notna()].wallet == top).mean()),
        "b03_prints_with_fav_ge_095": int((np.maximum(B.p, 1 - B.p) >= 0.95).sum()),
        "b03_prints_outside_v2_zone_005_095": int(((B.q < 0.05) | (B.q > 0.95)).sum()),
        "calendar_days_in_window": int(days),
        "b03_usd_per_calendar_day_all_wallets": float(B.usd.sum() / days),
    }
    res["run_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    res["commit"] = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    OUT.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
