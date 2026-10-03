"""Independent rebuild of COURTSIDE v2 (sizing lens policy G_50pct_net100).

Written from HYPOTHESIS_V2.md and research/v2/sizing/RESULTS.md only. It does NOT import
src/v2.py, src/fasttier.py, src/tiers.py or anything under research/v2/sizing/. The only repo
import is src.tape.universe() (match start/end, OOS cutoff), which reads the cached event file.

Rule, as written:
 1. opportunity set: 0-3 s post-jump-onset prints (0 <= since < 3) of wallets qualified on
    months < m: >= 30 such prints over >= 10 matches, t-stat of mean 30 s markout > 3.
 2. wallet filter: (sum mo30_w + 200*pool)/(n_w + 200) > rate*q(1-q), stats over 0-3 s prints < m,
    pool = mean mo30 of all takers' 0-3 s prints < m. HYPOTHESIS_V2 writes rate = 0.05 ('fixed');
    the published IS numbers are only reproduced with rate = each match's own fee ('match'). The
    two are identical on the burned OOS and the forward window (all matches at 5%).
 3. price zone: 0.05 <= q <= 0.95 (q = price of the token bought).
 4. size: shares = min(their shares, R/sqrt(q(1-q)), $1000/q); R refitted each month on the
    shadow rows of months < m so that the mean ticket is 50% of the v1 shadow book's
    (v1 ticket = min(their usd, $1000)).
 5. per match |net outcome-0 shares| <= 100 (clip risk-increasing trades), gross <= $3k.
 6. hold to resolution; pnl = shares*(dir*(res-p) - rate*p(1-p)), 50/50 resolutions included.
Metrics: per-share = sum pnl / sum shares, match-cluster bootstrap CI; Sharpe from daily P&L
(calendar days, zero days included); capital = 3 x peak gross $ locked, lock to min(end, +8 h).

Stress tests on the burned OOS:
 (i)  1 extra tick (0.01) of entry slippage per share;
 (ii) only prints at or after the jump detector's detect_ts (detector recomputed here from the
      full tape in the prints file, validated against data/derived/jumps_is.parquet).

Run from repo root:  .venv/bin/python research/v2/verify_v2/rebuild.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.tape import universe  # noqa: E402  (match start/end only)

OUT = ROOT / "research/v2/verify_v2/out"
IS_PATH = ROOT / "data/is_prints.parquet"
OOS_PATH = ROOT / "data/locked/oos_prints.parquet"
COLS = ["cond", "ts", "p", "dir", "usd", "wallet", "since", "fee_rate", "res", "mo30"]

MIN_PRINTS, MIN_MATCHES, MIN_T = 30, 10, 3.0
N0, TODAY_RATE = 200, 0.05
QLO, QHI = 0.05, 0.95
TRADE_MAX, MATCH_GROSS_MAX, NET_CAP = 1000.0, 3000.0, 100.0
DEPLOY = 0.50
LOCK_MAX_S = 8 * 3600
EVAL_START = pd.Period("2026-02", "M")
FIRST_WF = 2  # walk-forward starts at the 3rd month of data (Dec 2025)


# ----------------------------------------------------------------------------- data
def load_03(path: Path, tag: str) -> pd.DataFrame:
    t = pq.read_table(path, columns=COLS)
    t = t.filter(pc.and_(pc.greater_equal(t["since"], 0.0), pc.less(t["since"], 3.0)))
    d = t.to_pandas()
    d["src"] = tag
    return d


def prep(d: pd.DataFrame) -> pd.DataFrame:
    d = d.reset_index(drop=True)
    d["row"] = np.arange(len(d))
    d["month"] = pd.to_datetime(d.ts, unit="s").dt.to_period("M")
    d["q"] = np.where(d.dir > 0, d.p, 1 - d.p)
    return d


# ----------------------------------------------------------------------------- rule pieces
def qualify(past: pd.DataFrame, tdenom: str) -> pd.Index:
    g = past.groupby("wallet", observed=True).agg(
        n=("mo30", "size"), k=("mo30", "count"), nm=("cond", "nunique"), m=("mo30", "mean"), sd=("mo30", "std"))
    g = g[(g.n >= MIN_PRINTS) & (g.nm >= MIN_MATCHES) & (g.sd > 0)]
    den = np.sqrt(g.nm) if tdenom == "matches" else np.sqrt(g.k)
    return g.index[(g.m / (g.sd / den)) > MIN_T]


def fit_R(train: pd.DataFrame, frac: float = DEPLOY) -> float:
    """R such that mean(min(usd, R*sqrt(q/(1-q)), 1000)) = frac * mean(min(usd, 1000))."""
    if len(train) == 0:
        return np.nan
    usd = train.usd.to_numpy()
    q = train.q.to_numpy()
    r = np.sqrt(q / (1 - q))
    target = frac * np.minimum(usd, TRADE_MAX).mean()
    lo, hi = 0.0, 1e7
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if np.minimum(np.minimum(usd, mid * r), TRADE_MAX).mean() < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def build_candidates(d: pd.DataFrame, tdenom: str = "matches", filter_rate: str = "fixed") -> tuple[pd.DataFrame, pd.DataFrame]:
    """filter_rate: 'fixed' = 0.05 (HYPOTHESIS_V2 / RESULTS sec. 7 wording); 'match' = the match's own
    published fee rate; 'month_max' = the highest fee rate among month m's matches."""
    months = sorted(d.month.unique())
    shadow, info = [], []
    for m in months[FIRST_WF:]:
        sel = qualify(d[d.month < m], tdenom)
        cur = d[(d.month == m) & d.wallet.isin(sel)]
        shadow.append(cur)
    sh = pd.concat(shadow, ignore_index=True)
    cands = []
    for m in months[FIRST_WF:]:
        past = d[d.month < m]
        pool = past.mo30.mean()
        ws = past.groupby("wallet", observed=True).mo30.agg(["sum", "count"])
        shrunk = (ws["sum"] + N0 * pool) / (ws["count"] + N0)
        R = fit_R(sh[sh.month < m])
        cur = sh[sh.month == m].copy()
        cur["R"] = R
        cur["shrunk"] = cur.wallet.map(shrunk).astype(float)
        qq = cur.q * (1 - cur.q)
        if filter_rate == "fixed":
            rate = TODAY_RATE
        elif filter_rate == "match":
            rate = cur.fee_rate
        else:
            rate = d.loc[d.month == m, "fee_rate"].max()
        cur["pass_wallet"] = cur.shrunk > rate * qq
        cur["pass_zone"] = (cur.q >= QLO) & (cur.q <= QHI)
        their = cur.usd / cur.q
        cur["want"] = np.minimum(np.minimum(their, R / np.sqrt(qq)), TRADE_MAX / cur.q)
        info.append({"month": str(m), "n_qualified": len(qualify(past, tdenom)), "R": R, "pool_c": pool * 100,
                     "shadow_rows": len(cur), "pass_wallet": int(cur.pass_wallet.sum()),
                     "pass_both": int((cur.pass_wallet & cur.pass_zone).sum())})
        cands.append(cur)
    return pd.concat(cands, ignore_index=True), pd.DataFrame(info)


def sequential(c: pd.DataFrame, eligible: np.ndarray | None = None, net_cap: float = NET_CAP) -> pd.DataFrame:
    ok = c.pass_wallet.to_numpy() & c.pass_zone.to_numpy() & np.isfinite(c.want.to_numpy())
    if eligible is not None:
        ok &= eligible
    x = c[ok].sort_values(["ts", "row"], kind="stable")
    net, gross = {}, {}
    out = np.zeros(len(x))
    for i, (cond, d, q, w) in enumerate(zip(x.cond.to_numpy(), x.dir.to_numpy(), x.q.to_numpy(), x.want.to_numpy())):
        n0 = net.get(cond, 0.0)
        s = min(w, max(0.0, net_cap - d * n0))  # never past +-net_cap; risk-reducing up to the other side
        g0 = gross.get(cond, 0.0)
        s = min(s, max(0.0, (MATCH_GROSS_MAX - g0) / q))
        if s > 1e-9:
            out[i] = s
            net[cond] = n0 + d * s
            gross[cond] = g0 + s * q
    x = x.assign(shares=out)
    x = x[x.shares > 1e-9].copy()
    x["fee_ps"] = x.fee_rate * x.p * (1 - x.p)
    x["pnl_ps"] = x.dir * (x.res - x.p) - x.fee_ps
    x["pnl"] = x.shares * x.pnl_ps
    x["cost"] = x.shares * x.q
    return x


# ----------------------------------------------------------------------------- metrics
def cluster_ci(tr: pd.DataFrame, pnl_col: str = "pnl", n_boot: int = 2000, seed: int = 0):
    g = tr.groupby("cond", observed=True).agg(s=(pnl_col, "sum"), w=("shares", "sum"))
    s, w = g.s.to_numpy(), g.w.to_numpy()
    rng = np.random.default_rng(seed)
    k = len(g)
    idx = rng.integers(0, k, (n_boot, k))
    bs = s[idx].sum(1) / w[idx].sum(1)
    return float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)


def metrics(tr: pd.DataFrame, end_ts: pd.Series, day0=None, day1=None, pnl_col: str = "pnl") -> dict:
    if len(tr) == 0:
        return {"n_trades": 0}
    day = pd.to_datetime(tr.ts, unit="s", utc=True).dt.floor("D")
    d0 = min(pd.Timestamp(day0, tz="UTC"), day.min()) if day0 else day.min()
    d1 = max(pd.Timestamp(day1, tz="UTC"), day.max()) if day1 else day.max()  # never drop a trade day
    daily = tr.groupby(day)[pnl_col].sum().reindex(pd.date_range(d0, d1, freq="D"), fill_value=0.0)
    sr = daily.mean() / daily.std(ddof=1)
    # capital: 3 x peak gross $ locked from entry to min(match end, entry + 8 h)
    e = tr.cond.map(end_ts).to_numpy(dtype=float)
    lock_end = np.minimum(np.where(np.isfinite(e), e, tr.ts + LOCK_MAX_S), tr.ts + LOCK_MAX_S)
    lock_end = np.maximum(lock_end, tr.ts.to_numpy())
    ev = pd.DataFrame({"t": np.r_[tr.ts.to_numpy(), lock_end], "v": np.r_[tr.cost.to_numpy(), -tr.cost.to_numpy()],
                       "o": np.r_[np.ones(len(tr)), np.zeros(len(tr))]}).sort_values(["t", "o"])  # releases first
    peak = ev.v.cumsum().max()
    capital = 3 * peak
    cum = daily.cumsum()
    dd = (cum - np.maximum(cum.cummax(), 0)).min()
    lo, hi = cluster_ci(tr, pnl_col)
    mon = tr.groupby("month")[pnl_col].sum()
    return {"n_trades": int(len(tr)), "n_matches": int(tr.cond.nunique()), "shares": float(tr.shares.sum()),
            "per_share_c": float(tr[pnl_col].sum() / tr.shares.sum() * 100), "ci95_c": [round(lo, 3), round(hi, 3)],
            "total_pnl": float(tr[pnl_col].sum()), "days": int(len(daily)),
            "sharpe_365": float(sr * np.sqrt(365)), "sharpe_252": float(sr * np.sqrt(252)),
            "capital": float(capital), "max_dd_pct": float(dd / capital * 100),
            "worst_day_pct": float(daily.min() / capital * 100),
            "months_pos": f"{int((mon > 0).sum())}/{len(mon)}", "hit_rate": float((tr[pnl_col] > 0).mean())}


# ----------------------------------------------------------------------------- jump detector
def detect_jumps(ts: np.ndarray, p: np.ndarray, usd: np.ndarray, J=0.04, short_w=10.0, long_w=60.0):
    """H1 signal as written: VWAP over the last 10 s minus VWAP over the 60 s before that, |d| >= J,
    evaluated at every print; re-armed 60 s after a detection. Onset = first print of the 10 s window."""
    pv = np.r_[0.0, np.cumsum(p * usd)]
    v = np.r_[0.0, np.cumsum(usd)]
    a_all = np.searchsorted(ts, ts - short_w, "left")
    b_all = np.searchsorted(ts, ts - short_w - long_w, "left")
    onset, det = [], []
    last = -np.inf
    for i in range(len(ts)):
        if ts[i] - last < long_w:
            continue
        a, b = a_all[i], b_all[i]
        if a <= b or a > i:
            continue
        w1 = v[i + 1] - v[a]
        w2 = v[a] - v[b]
        if w1 <= 0 or w2 <= 0:
            continue
        dlt = (pv[i + 1] - pv[a]) / w1 - (pv[a] - pv[b]) / w2
        if abs(dlt) >= J:
            last = ts[i]
            onset.append(ts[a])
            det.append(ts[i])
    return np.array(onset), np.array(det)


def jumps_for(path: Path, conds: set | None = None) -> pd.DataFrame:
    t = pq.read_table(path, columns=["cond", "ts", "p", "usd"])
    if conds is not None:
        import pyarrow as pa
        t = t.filter(pc.is_in(t["cond"], value_set=pa.array(sorted(conds), type=t.schema.field("cond").type)))
    d = t.to_pandas()
    rows = []
    for cond, g in d.groupby("cond", sort=False):
        ts = g.ts.to_numpy()
        assert np.all(np.diff(ts) >= 0), cond
        on, de = detect_jumps(ts, g.p.to_numpy(), g.usd.to_numpy())
        rows.append(pd.DataFrame({"cond": cond, "onset_ts": on, "detect_ts": de}))
    return pd.concat(rows, ignore_index=True)


def attach_detect(c: pd.DataFrame, jumps: pd.DataFrame) -> pd.DataFrame:
    """For each candidate print, the detect_ts of the latest onset <= ts (the onset 'since' refers to)."""
    det = np.full(len(c), np.nan)
    ons = np.full(len(c), np.nan)
    jg = {k: g for k, g in jumps.groupby("cond", sort=False)}
    for cond, idx in c.groupby("cond", sort=False).indices.items():
        g = jg.get(cond)
        if g is None:
            continue
        on, de = g.onset_ts.to_numpy(), g.detect_ts.to_numpy()
        ts = c.ts.to_numpy()[idx]
        k = np.searchsorted(on, ts, "right") - 1
        okk = k >= 0
        det[idx[okk]] = de[k[okk]]
        ons[idx[okk]] = on[k[okk]]
    return c.assign(detect_ts=det, onset_rebuilt=ons)


# ----------------------------------------------------------------------------- main
IS_D0, IS_D1, OOS_D0, OOS_D1 = "2026-02-01", "2026-08-25", "2026-08-25", "2026-10-03"


def by_month(tr: pd.DataFrame, col: str = "pnl") -> list:
    g = tr.groupby(tr.month.astype(str)).agg(n=(col, "size"), pnl=(col, "sum"), shares=("shares", "sum"))
    return g.assign(ps_c=g.pnl / g.shares * 100).round(3).reset_index().to_dict("records")


def show(tag: str, m: dict):
    keys = ("n_trades", "n_matches", "per_share_c", "ci95_c", "total_pnl", "sharpe_365", "capital", "max_dd_pct",
            "worst_day_pct", "months_pos", "days")
    print(f"[{tag}]", {k: (round(m[k], 3) if isinstance(m.get(k), float) else m.get(k)) for k in keys}, flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    u = universe()
    end_ts = pd.Series(u.end.map(lambda x: x.timestamp()).to_numpy(), index=u.cond.to_numpy())
    start_ts = pd.Series(u.start.map(lambda x: x.timestamp()).to_numpy(), index=u.cond.to_numpy())
    cut = u.loc[u.oos, "start"].min()
    cut_ts = cut.timestamp()
    rep = {"oos_cutoff": str(cut), "notes": "filter_rate: match = each match's own fee (what reproduces the "
           "published numbers); fixed = 0.05 for every match (HYPOTHESIS_V2 wording)"}

    d_is = load_03(IS_PATH, "is")
    d_oos = load_03(OOS_PATH, "oos")
    print("0-3s prints IS", len(d_is), "OOS", len(d_oos), flush=True)

    # ---------------- (a) IS-only run, IS eval (Feb..Aug 2026)
    a = {}
    dI = prep(d_is.copy())
    for fr, td in (("match", "matches"), ("fixed", "matches"), ("match", "prints")):
        c, info = build_candidates(dI, td, fr)
        tr = sequential(c)
        ev = tr[tr.month >= EVAL_START]
        tag = f"IS-only filter_rate={fr} tstat_denom={td}"
        a[tag] = metrics(ev, end_ts, IS_D0, IS_D1)
        a[tag]["shadow_rows_eval"] = int((c.month >= EVAL_START).sum())
        a[tag]["monthly"] = by_month(ev)
        show(tag, a[tag])
        if (fr, td) == ("match", "matches"):
            print(info.to_string(), flush=True)
            info.to_csv(OUT / "is_month_info.csv", index=False)
            ev.to_parquet(OUT / "is_trades.parquet")
    rep["a_is_only"] = a

    # ---------------- (b) IS + burned OOS run
    b = {}
    d = prep(pd.concat([d_is, d_oos], ignore_index=True))
    runs = {}
    for fr in ("match", "fixed"):
        c, info = build_candidates(d, "matches", fr)
        c["mstart"] = c.cond.map(start_ts)
        tr = sequential(c)
        tr["mstart"] = tr.cond.map(start_ts)
        runs[fr] = (c, tr)
        b[f"is_eval_by_ts[{fr}]"] = metrics(tr[(tr.month >= EVAL_START) & (tr.ts < cut_ts)], end_ts, IS_D0, IS_D1)
        b[f"oos_by_ts[{fr}]"] = metrics(tr[tr.ts >= cut_ts], end_ts, OOS_D0, OOS_D1)
        b[f"oos_by_match_start[{fr}]"] = metrics(tr[tr.mstart >= cut_ts], end_ts, OOS_D0, OOS_D1)
        if fr == "match":
            print(info.to_string(), flush=True)
            info.to_csv(OUT / "isoos_month_info.csv", index=False)
            tr.to_parquet(OUT / "isoos_trades.parquet")
            b["oos_monthly_by_match_start"] = by_month(tr[tr.mstart >= cut_ts])
    for k, v in b.items():
        if isinstance(v, dict):
            show(k, v)
    print("OOS monthly:", b["oos_monthly_by_match_start"], flush=True)
    c, tr = runs["match"]
    oos_ts, oos_ms = tr[tr.ts >= cut_ts].copy(), tr[tr.mstart >= cut_ts].copy()
    b["is_matches_with_prints_after_cutoff"] = int(tr.loc[(tr.ts >= cut_ts) & (tr.mstart < cut_ts), "cond"].nunique())

    # ---------------- stress (i): one extra tick (0.01) at entry
    s1 = {}
    for name, sub in (("oos_by_ts", oos_ts), ("oos_by_match_start", oos_ms),
                      ("is_eval", tr[(tr.month >= EVAL_START) & (tr.ts < cut_ts)].copy())):
        sub["pnl_slip"] = sub.pnl - 0.01 * sub.shares
        qs = np.minimum(sub.q + 0.01, 0.99)  # same, but fee charged at the slipped price
        sub["pnl_slip_fee"] = sub.shares * (sub.dir * (sub.res - sub.p) - 0.01 - sub.fee_rate * qs * (1 - qs))
        d0, d1 = (IS_D0, IS_D1) if name == "is_eval" else (OOS_D0, OOS_D1)
        s1[name] = metrics(sub, end_ts, d0, d1, "pnl_slip")
        s1[name + "_fee_at_slipped_price"] = metrics(sub, end_ts, d0, d1, "pnl_slip_fee")
        if name != "is_eval":
            s1[name]["monthly"] = by_month(sub, "pnl_slip")
    for k, v in s1.items():
        show("stress(i) tick " + k, v)

    # ---------------- stress (ii): only prints at/after the detector's detect_ts
    j_is = jumps_for(IS_PATH, set(c.loc[c.src == "is", "cond"].unique()))
    j_oos = jumps_for(OOS_PATH, set(c.loc[c.src == "oos", "cond"].unique()))
    jumps = pd.concat([j_is, j_oos], ignore_index=True)
    jumps.to_parquet(OUT / "jumps_rebuilt.parquet")
    # validate the rebuilt detector against the repo's IS jump table
    ref = pd.read_parquet(ROOT / "data/derived/jumps_is.parquet", columns=["cond", "onset_ts", "detect_ts"])
    ref = ref[ref.cond.isin(set(j_is.cond))]
    mm = j_is.merge(ref, on=["cond", "onset_ts"], how="outer", suffixes=("", "_ref"), indicator=True)
    val = {"rebuilt_is_jumps": len(j_is), "ref_is_jumps_same_conds": len(ref),
           "onset_matched": int((mm._merge == "both").sum()),
           "detect_ts_equal": int(((mm._merge == "both") & (mm.detect_ts == mm.detect_ts_ref)).sum())}
    c = attach_detect(c, jumps)
    val["since_reproduced_frac"] = float(((c.ts - c.onset_rebuilt - c.since).abs() < 1e-6).mean())
    print("detector validation:", val, flush=True)
    elig = (c.ts >= c.detect_ts).to_numpy()
    tr2 = sequential(c, eligible=elig)
    tr2["mstart"] = tr2.cond.map(start_ts)
    s2 = {"detector_validation": val}
    s2["oos_by_ts"] = metrics(tr2[tr2.ts >= cut_ts], end_ts, OOS_D0, OOS_D1)
    s2["oos_by_match_start"] = metrics(tr2[tr2.mstart >= cut_ts], end_ts, OOS_D0, OOS_D1)
    s2["oos_by_match_start"]["monthly"] = by_month(tr2[tr2.mstart >= cut_ts])
    s2["is_eval"] = metrics(tr2[(tr2.month >= EVAL_START) & (tr2.ts < cut_ts)], end_ts, IS_D0, IS_D1)
    # stricter: strictly after the detection second (timestamps are whole seconds)
    tr2s = sequential(c, eligible=(c.ts > c.detect_ts).to_numpy())
    tr2s["mstart"] = tr2s.cond.map(start_ts)
    s2["oos_by_match_start_strict_gt"] = metrics(tr2s[tr2s.mstart >= cut_ts], end_ts, OOS_D0, OOS_D1)
    show("stress(ii) detect strict ts>detect_ts oos_by_match_start", s2["oos_by_match_start_strict_gt"])
    # post-hoc variant: v2's own book, minus its pre-detection trades (cap room not re-used)
    lab = tr.merge(c[["row", "detect_ts"]], on="row", how="left")
    pre = lab.ts < lab.detect_ts
    s2["oos_by_match_start_posthoc_drop"] = metrics(lab[~pre & (lab.mstart >= cut_ts)], end_ts, OOS_D0, OOS_D1)
    s2["oos_pre_detect_only"] = metrics(lab[pre & (lab.mstart >= cut_ts)], end_ts, OOS_D0, OOS_D1)
    s2["share_of_v2_oos_trades_pre_detect"] = float(pre[lab.mstart >= cut_ts].mean())
    s2["share_of_v2_oos_shares_pre_detect"] = float(lab.shares[pre & (lab.mstart >= cut_ts)].sum()
                                                    / lab.shares[lab.mstart >= cut_ts].sum())
    s2["share_of_v2_is_trades_pre_detect"] = float(pre[(lab.month >= EVAL_START) & (lab.ts < cut_ts)].mean())
    lag = (lab.detect_ts - (lab.ts - lab.since))[lab.mstart >= cut_ts]
    s2["oos_detect_minus_onset_s_quantiles"] = {str(k): float(v) for k, v in lag.quantile([.1, .25, .5, .75, .9]).items()}
    for k in ("oos_by_ts", "oos_by_match_start", "is_eval", "oos_by_match_start_posthoc_drop", "oos_pre_detect_only"):
        show("stress(ii) detect " + k, s2[k])
    print("share of v2 OOS trades (shares) printed before detect_ts:",
          round(s2["share_of_v2_oos_trades_pre_detect"], 4), round(s2["share_of_v2_oos_shares_pre_detect"], 4),
          "| IS:", round(s2["share_of_v2_is_trades_pre_detect"], 4), flush=True)

    # ---------------- both stresses
    t3 = tr2[tr2.mstart >= cut_ts].copy()
    t3["pnl_slip"] = t3.pnl - 0.01 * t3.shares
    s3 = {"oos_by_match_start": metrics(t3, end_ts, OOS_D0, OOS_D1, "pnl_slip")}
    show("stress(i+ii) oos_by_match_start", s3["oos_by_match_start"])

    rep["b_is_plus_oos"] = b
    rep["stress_i_tick"] = s1
    rep["stress_ii_detect"] = s2
    rep["stress_both"] = s3
    (OUT / "rebuild_report.json").write_text(json.dumps(rep, indent=2, default=str))


if __name__ == "__main__":
    main()
