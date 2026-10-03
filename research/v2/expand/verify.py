"""Adversarial, independent verification of the U2 out-of-universe test (research/v2/expand/PREREG.md).

    python research/v2/expand/verify.py rerun  OUT.parquet   # re-run frozen v2 on the same inputs (~2 min)
    python research/v2/expand/verify.py check  [RERUN.parquet] [OUT.json]

`check` does NOT call v2.run, E.metrics, fasttier.qualify, tiers.add_causal_bucket or build_u2.select_u2.
It re-derives, with code written here:
  * U2 from the raw catalogue, its overlap with U1 (cond, event_id, player pair +-2 days) and doubles;
  * provenance: PREREG commit time vs U2 tape creation times and result files; code unchanged vs HEAD;
  * per-trade P&L from the catalogue's res0 / fee_rate and the trade's own price and side;
  * the period split from the catalogue start_time;
  * the primary per-share number and its match-clustered CI (same algorithm and seed as E.metrics, plus a
    10,000-draw / different-seed version and a wallet-clustered version);
  * Sharpe, $ P&L, drawdown from its own daily series;
  * causal jump detection (own two-pointer detector), walk-forward wallet qualification and the wallet
    filter, checking that every U2 trade is consistent with information from months < m only;
  * concentration of U2 P&L by match, wallet and day.
Nothing here writes into data/ or changes any result file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

CAT = ROOT / "data/raw/events_tennis_2025-07-01_2026-10-03.parquet"
OOS_CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")
END_CUT = pd.Timestamp("2026-10-03 07:10", tz="UTC")
PREREG_COMMIT = "337bf7c"
EVAL_START = "2026-02"
FROZEN_FILES = ["src/v2.py", "research/v2/sizing/engine.py", "src/fasttier.py", "src/tiers.py", "src/tape.py",
                "src/polymarket.py", "scripts/forward_test.py", "research/v2/expand/PREREG.md"]
PRINT_FILES = ["data/is_prints.parquet", "data/locked/oos_prints.parquet", "data/expand_prints.parquet"]


def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True, cwd=ROOT).stdout.strip()


def sha16(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()[:16]


# ------------------------------------------------------------------------------------------ rerun
def rerun(out: str):
    """Reproduce the saved trade list with the frozen code on the same inputs (not independent; it checks
    that data/expand_v2_trades.parquet is what frozen v2 produces from unchanged inputs)."""
    from src import v2
    from src.tape import universe
    cols = ["cond", "ts", "p", "dir", "usd", "wallet", "spread", "fee_rate", "delay", "res",
            "mo5", "mo15", "mo30", "mo_res"]
    u1 = universe()
    u2 = pd.read_parquet("data/expand_universe.parquet")
    P = pd.concat([pd.read_parquet(f, columns=cols) for f in PRINT_FILES], ignore_index=True)
    ends = pd.concat([u1.set_index("cond").end, u2.set_index("cond").end])
    t0 = time.time()
    tr, wf = v2.run(P, ends, causal=True)
    tr.to_parquet(out)
    print("rerun trades", len(tr), f"{time.time() - t0:.0f}s", flush=True)


# ------------------------------------------------------------------------------- independent pieces
def u1_conds_independent(ev):
    """U1 as defined in src.tape.universe(), re-derived here: atp/wta/challenger series, volume >= 5k."""
    return ev[ev.series.isin(["atp", "wta", "challenger"]) & (ev.volume >= 5000)]


def norm_name(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s).strip()


def pair_of(title):
    parts = re.split(r"\s+vs\.?\s+", title.split(":")[-1])
    return tuple(sorted(norm_name(x) for x in parts)) if len(parts) == 2 else None


def detect(ts, p, usd, J=0.04, short_w=10.0, long_w=60.0):
    """Own implementation of the jump detector: two moving pointers instead of searchsorted.
    At print i (time now) outside a 60 s refractory period after the last detection, compare the
    usd-weighted mean price of prints in [now-10, now] (up to and including i) with that of prints in
    [now-70, now-10). |diff| >= J -> detection at `now`."""
    n = len(ts)
    pv = np.concatenate([[0.0], np.cumsum(p * usd)]).tolist()
    vv = np.concatenate([[0.0], np.cumsum(usd)]).tolist()
    ts = ts.tolist()
    out = []
    a = b = 0
    last = -np.inf
    for i in range(n):
        now = ts[i]
        while a < n and ts[a] < now - short_w:
            a += 1
        while b < n and ts[b] < now - short_w - long_w:
            b += 1
        if now - last < long_w:
            continue
        if a <= b:
            continue
        w1 = vv[i + 1] - vv[a]
        w2 = vv[a] - vv[b]
        if w1 <= 0 or w2 <= 0:
            continue
        d = (pv[i + 1] - pv[a]) / w1 - (pv[a] - pv[b]) / w2
        if abs(d) >= J:
            last = now
            out.append(now)
    return np.array(out)


def causal_03(P):
    """Boolean per print: 0 <= ts - (latest detection time <= ts) < 3, detection per match."""
    P0 = P
    P = P.sort_values(["cond", "ts"], kind="stable")
    flag = np.zeros(len(P), bool)
    since = np.full(len(P), np.nan)
    ts_all, p_all, u_all = P.ts.to_numpy(float), P.p.to_numpy(float), P.usd.to_numpy(float)
    codes = P.cond.cat.codes.to_numpy() if hasattr(P.cond, "cat") else pd.factorize(P.cond)[0]
    bounds = np.flatnonzero(np.diff(codes)) + 1
    starts = np.concatenate([[0], bounds]); ends = np.concatenate([bounds, [len(P)]])
    for s, e in zip(starts, ends):
        ts = ts_all[s:e]
        det = detect(ts, p_all[s:e], u_all[s:e])
        if len(det) == 0:
            continue
        k = np.searchsorted(det, ts, "right") - 1
        sd = np.where(k >= 0, ts - det[np.maximum(k, 0)], np.nan)
        since[s:e] = sd
        flag[s:e] = (sd >= 0) & (sd < 3)
    return (pd.Series(flag, index=P.index).reindex(P0.index), pd.Series(since, index=P.index).reindex(P0.index))


def qualified(past03: pd.DataFrame) -> set:
    """Walk-forward fast-tier rule, re-implemented: >= 30 prints, >= 10 matches, t = mean/(sd/sqrt(n_matches)) > 3
    on 30 s markout of 0-3 s-after-detection prints."""
    rows = past03.groupby("wallet", observed=True)
    n = rows.size()
    nm = rows.cond.nunique()
    m = rows.mo30.mean()
    sd = rows.mo30.std()
    ok = (n >= 30) & (nm >= 10) & (sd > 0)
    t = m / (sd / np.sqrt(nm))
    return set(n.index[ok & (t > 3)])


def cluster_boot(df, key, n_boot, seed, num="pnl", den="shares"):
    g = df.groupby(key, observed=True)[[num, den]].sum()
    x, w = g[num].to_numpy(), g[den].to_numpy()
    rng = np.random.default_rng(seed)
    k = len(g)
    bs = np.empty(n_boot)
    for j in range(n_boot):
        i = rng.integers(0, k, k)
        bs[j] = x[i].sum() / w[i].sum()
    return [float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)]


def daily(df, lo=None, hi=None):
    d = df.groupby(df.date_own).pnl.sum()
    lo = lo if lo is not None else d.index.min()
    hi = hi if hi is not None else d.index.max()
    return d.reindex(pd.date_range(lo, hi, freq="D", tz="UTC"), fill_value=0.0)


def sharpe(d):
    return float(d.mean() / d.std() * np.sqrt(365)) if d.std() > 0 else float("nan")


def book(df, label, rep=None):
    d = daily(df)
    eq = d.cumsum()
    out = {"n_trades": int(len(df)), "n_matches": int(df.cond.nunique()),
           "per_share_c": float(df.pnl.sum() / df.shares.sum() * 100),
           "ci_seed0_1000_c": cluster_boot(df, "cond", 1000, 0),
           "ci_seed12345_10000_c": cluster_boot(df, "cond", 10000, 12345),
           "ci_wallet_clustered_c": cluster_boot(df, "wallet", 10000, 7),
           "ci_day_clustered_c": cluster_boot(df, "date_own", 10000, 11),
           "total_pnl_usd": float(df.pnl.sum()), "sharpe_ann": sharpe(d), "days": int(len(d)),
           "max_dd_usd": float((eq - eq.cummax()).min()), "worst_day_usd": float(d.min()),
           "months_positive": int((df.groupby("month_own").pnl.sum() > 0).sum()),
           "months_total": int(df.month_own.nunique())}
    if rep is not None:
        cmp = {"per_share_c": (out["per_share_c"], rep["per_share_c"]),
               "ci_lo_c": (out["ci_seed0_1000_c"][0], rep["per_share_ci_c"][0]),
               "ci_hi_c": (out["ci_seed0_1000_c"][1], rep["per_share_ci_c"][1]),
               "total_pnl_usd": (out["total_pnl_usd"], rep["total_pnl_usd"]),
               "sharpe_ann": (out["sharpe_ann"], rep["sharpe_ann"]),
               "n_trades": (out["n_trades"], rep["n_trades"]), "n_matches": (out["n_matches"], rep["n_matches"])}
        out["vs_reported"] = {k: {"mine": a, "reported": b,
                                  "rel_diff": (abs(a - b) / abs(b) if b else float(a != b))} for k, (a, b) in cmp.items()}
        out["max_rel_diff_vs_reported"] = max(v["rel_diff"] for v in out["vs_reported"].values())
    print(label, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items()
                  if k not in ("vs_reported",)}, flush=True)
    return out


# ------------------------------------------------------------------------------------------ check
def check(rerun_path: str | None, out_json: str | None):
    R = {}
    rep = json.load(open("results/expand/results.json"))

    # ---- 1. provenance -------------------------------------------------------------------------
    commit_t = pd.Timestamp(sh("git", "show", "-s", "--format=%cI", PREREG_COMMIT)).tz_convert("UTC")
    prov = {"prereg_commit_utc": str(commit_t),
            "prereg_unchanged_since_commit": sh("git", "diff", PREREG_COMMIT, "--", "research/v2/expand/PREREG.md") == "",
            "frozen_code_diff_vs_HEAD": {f: sh("git", "diff", "HEAD", "--", f) != "" for f in FROZEN_FILES},
            "frozen_code_diff_prereg_to_HEAD": {f: sh("git", "diff", PREREG_COMMIT, "HEAD", "--", f) != "" for f in FROZEN_FILES},
            "frozen_code_untracked": sh("git", "status", "--porcelain", "--", *FROZEN_FILES)}
    mt = {str(p): pd.Timestamp(os.stat(p).st_mtime, unit="s", tz="UTC") for p in
          list(Path("results/expand").glob("*")) + [Path("data/expand_prints.parquet"), Path("data/expand_universe.parquet"),
                                                     Path("data/expand_v2_trades.parquet"), Path("research/v2/expand/expand_test.py")]}
    prov["file_mtimes_utc"] = {k: str(v) for k, v in mt.items()}
    prov["all_u2_outputs_after_prereg_commit"] = all(v > commit_t for v in mt.values())
    prov["inputs_sha_match_results_json"] = {f: sha16(f) == h for f, h in rep["inputs_sha256_16"].items()}
    prov["run_started_utc"] = rep["run_started_utc"]
    R["provenance"] = prov

    # ---- 2. universe ---------------------------------------------------------------------------
    ev = pd.read_parquet(CAT, columns=["title", "series", "start_time", "finished", "closed_time", "cond", "res0",
                                       "volume", "fee_rate", "seconds_delay", "event_id"])
    ev["start"] = pd.to_datetime(ev.start_time, utc=True, format="mixed")
    u1 = u1_conds_independent(ev)
    sel = (ev.series.isin(["atp", "wta", "challenger", "itf"]) & ~ev.series.fillna("").str.contains("doubles")
           & (ev.volume >= 1000) & ev.res0.isin([0.0, 0.5, 1.0]) & (ev.start < END_CUT) & ~ev.cond.isin(set(u1.cond)))
    u2 = ev[sel].copy()
    u2_saved = pd.read_parquet("data/expand_universe.parquet", columns=["cond", "start", "end", "oos", "event_id"])
    u2["oos"] = u2.start >= OOS_CUT
    uni = {"u2_n_independent": int(len(u2)), "u2_n_saved": int(len(u2_saved)),
           "u2_cond_sets_equal": set(u2.cond) == set(u2_saved.cond),
           "u2_oos_flags_equal": bool((u2.set_index("cond").oos.reindex(u2_saved.cond).to_numpy() == u2_saved.oos.to_numpy()).all()),
           "u1_n_independent": int(len(u1)),
           "u1_u2_shared_cond": len(set(u1.cond) & set(u2.cond)),
           "u1_u2_shared_event_id": len(set(u1.event_id) & set(u2.event_id)),
           "u2_doubles_series": int(u2.series.str.contains("doubles").sum()),
           "u2_titles_with_doubles_or_slash": int(u2.title.str.upper().str.contains("DOUBLE|/|&", regex=True).sum()),
           "u2_series": u2.series.value_counts().to_dict(), "u2_is": int((~u2.oos).sum()), "u2_oos": int(u2.oos.sum())}
    u1p = u1.assign(pair=u1.title.map(pair_of))[["pair", "start", "cond", "title"]]
    u2p = u2.assign(pair=u2.title.map(pair_of))[["pair", "start", "cond", "title"]]
    x = u2p.merge(u1p, on="pair", suffixes=("", "_u1"))
    x = x[(x.start - x.start_u1).abs() < pd.Timedelta("2D")]
    y = u2p.merge(u2p, on="pair", suffixes=("", "_b"))
    y = y[(y.cond < y.cond_b) & ((y.start - y.start_b).abs() < pd.Timedelta("2D"))]
    uni["same_match_in_u1_and_u2"] = x[["title", "start", "title_u1", "start_u1"]].astype(str).to_dict("records")
    uni["same_match_twice_in_u2"] = y[["title", "start", "title_b", "start_b"]].astype(str).to_dict("records")
    # U2 tape creation times vs the pre-registration commit
    births = np.array([os.stat(f"data/raw/trades/{c}.parquet").st_birthtime for c in u2.cond])
    uni["u2_tapes_created_min_utc"] = str(pd.Timestamp(births.min(), unit="s", tz="UTC"))
    uni["u2_tapes_created_before_prereg_commit"] = int((births < commit_t.timestamp()).sum())
    R["universe"] = uni
    print("universe", {k: v for k, v in uni.items() if not k.startswith("same_")}, flush=True)

    # ---- 3. trades: saved vs rerun, then own P&L ----------------------------------------------
    tr = pd.read_parquet("data/expand_v2_trades.parquet")
    if rerun_path:
        rr = pd.read_parquet(rerun_path)
        key = ["cond", "ts", "p", "dir", "wallet", "usd"]
        a = tr[key + ["shares", "pnl"]].sort_values(key, kind="stable").reset_index(drop=True)
        b = rr[key + ["shares", "pnl"]].sort_values(key, kind="stable").reset_index(drop=True)
        same_rows = len(a) == len(b) and a[key].equals(b[key])
        R["rerun"] = {"n_saved": int(len(a)), "n_rerun": int(len(b)), "identical_rows": bool(same_rows),
                      "max_abs_share_diff": float((a.shares - b.shares).abs().max()) if same_rows else None,
                      "max_abs_pnl_diff": float((a.pnl - b.pnl).abs().max()) if same_rows else None}
        print("rerun", R["rerun"], flush=True)

    meta = ev.set_index("cond")
    tr["start_own"] = tr.cond.map(meta.start)
    assert tr.start_own.notna().all(), "every traded cond must be in the catalogue"
    tr["is_u2"] = tr.cond.isin(set(u2.cond))
    tr["is_u1"] = tr.cond.isin(set(u1.cond))
    assert not (tr.is_u1 & tr.is_u2).any() and (tr.is_u1 | tr.is_u2).all()
    tr["oos_own"] = tr.start_own >= OOS_CUT
    tr["month_own"] = pd.to_datetime(tr.ts, unit="s").dt.to_period("M").astype(str)
    tr["date_own"] = pd.to_datetime(tr.ts, unit="s", utc=True).dt.floor("D")
    res0 = tr.cond.map(meta.res0).to_numpy(float)
    rate = tr.cond.map(meta.fee_rate.fillna(0.0)).to_numpy(float)
    q = np.where(tr.dir > 0, tr.p, 1 - tr.p)
    pnl_ps_own = tr.dir.to_numpy() * (res0 - tr.p.to_numpy()) - rate * q * (1 - q)
    tchk = {"month_matches_saved": bool((tr.month_own == tr.month).all()),
            "max_abs_pnl_ps_diff_vs_saved": float(np.abs(pnl_ps_own - tr.pnl_ps.to_numpy()).max()),
            "zone_ok": bool(((q >= 0.05 - 1e-12) & (q <= 0.95 + 1e-12)).all()),
            "shares_le_their_print": bool((tr.shares <= tr.usd / q + 1e-6).all()),
            "usd_le_1000": bool((tr.shares * q <= 1000 + 1e-6).all())}
    # per-match running |net outcome-0 shares| <= 100 unless the trade reduces exposure
    viol = 0
    for c, g in tr.sort_values("ts", kind="stable").groupby("cond", sort=False):
        net = 0.0
        for d_, s_ in zip(g.dir.to_numpy(), g.shares.to_numpy()):
            new = net + d_ * s_
            if abs(new) > 100 + 1e-6 and abs(new) > abs(net) + 1e-9:
                viol += 1
            net = new
    tchk["net_cap_violations"] = viol
    # every U2 trade is a real U2 print
    p2 = pd.read_parquet("data/expand_prints.parquet", columns=["cond", "ts", "p", "dir", "usd", "wallet", "mo30"])
    key = ["cond", "ts", "p", "dir", "usd", "wallet"]
    t2 = tr[tr.is_u2]
    tchk["u2_trades_found_in_u2_prints"] = float(t2[key].merge(p2[key].drop_duplicates(), on=key, how="left",
                                                               indicator=True)._merge.eq("both").mean())
    R["trade_checks"] = tchk
    print("trade checks", tchk, flush=True)

    tr["pnl"] = tr.shares * pnl_ps_own
    ev_tr = tr[tr.month_own >= EVAL_START]
    B = rep["books"]
    books = {"u2_is": ev_tr[ev_tr.is_u2 & ~ev_tr.oos_own], "u2_oos": ev_tr[ev_tr.is_u2 & ev_tr.oos_own],
             "combined_is": ev_tr[~ev_tr.oos_own], "combined_oos": ev_tr[ev_tr.oos_own],
             "u1_is_context": ev_tr[ev_tr.is_u1 & ~ev_tr.oos_own], "u1_oos_context": ev_tr[ev_tr.is_u1 & ev_tr.oos_own]}
    R["books"] = {k: book(v, k, B[k]["slip0.0"]) for k, v in books.items()}
    for slip in (0.005, 0.01):
        for k in ("u2_is", "u2_oos", "combined_oos"):
            v = books[k].assign(pnl=books[k].pnl - books[k].shares * slip)
            R["books"][k][f"slip{slip}"] = {"per_share_c": float(v.pnl.sum() / v.shares.sum() * 100),
                                             "ci_seed0_1000_c": cluster_boot(v, "cond", 1000, 0)}
    # Sharpe variants (descriptive): U2-IS from the ITF bulk (May), and U2-OOS over the full calendar window
    u2is = books["u2_is"]
    R["sharpe_variants"] = {
        "u2_is_from_2026-05-01": sharpe(daily(u2is[u2is.date_own >= pd.Timestamp("2026-05-01", tz="UTC")])),
        "u2_oos_cutoff_to_2026-10-03": sharpe(daily(books["u2_oos"], pd.Timestamp("2026-08-25", tz="UTC"),
                                                    pd.Timestamp("2026-10-03", tz="UTC"))),
        "u2_oos_days_in_series": int(len(daily(books["u2_oos"]))),
        "sharpe_se_approx_u2_oos": float(np.sqrt((1 + 0.5 * (R["books"]["u2_oos"]["sharpe_ann"] / np.sqrt(365)) ** 2)
                                                 / len(daily(books["u2_oos"]))) * np.sqrt(365))}
    # U1 vs U2 daily correlation
    def corr(a, b):
        lo = min(a.date_own.min(), b.date_own.min()); hi = max(a.date_own.max(), b.date_own.max())
        return float(np.corrcoef(daily(a, lo, hi), daily(b, lo, hi))[0, 1])
    mid_may = pd.Timestamp("2026-05-15", tz="UTC")
    R["u1_u2_daily_corr"] = {"is_from_2026-05-15": corr(books["u1_is_context"][books["u1_is_context"].date_own >= mid_may],
                                                         u2is[u2is.date_own >= mid_may]),
                             "is_all": corr(books["u1_is_context"], u2is),
                             "oos": corr(books["u1_oos_context"], books["u2_oos"])}
    print("sharpe variants", R["sharpe_variants"], "corr", R["u1_u2_daily_corr"], flush=True)

    # ---- 4. concentration -----------------------------------------------------------------------
    conc = {}
    for k in ("u2_is", "u2_oos"):
        g = books[k]
        tot = g.pnl.sum()
        bym = g.groupby("cond").pnl.sum().sort_values(ascending=False)
        byw = g.groupby("wallet").agg(pnl=("pnl", "sum"), shares=("shares", "sum"), n=("pnl", "size"),
                                      nm=("cond", "nunique")).sort_values("pnl", ascending=False)
        byd = g.groupby("date_own").pnl.sum().sort_values(ascending=False)
        ps = lambda d: float(d.pnl.sum() / d.shares.sum() * 100)
        conc[k] = {"total_pnl_usd": float(tot), "n_matches": int(len(bym)), "n_wallets": int(len(byw)),
                   "top10_matches_pnl_usd": float(bym.head(10).sum()), "top10_matches_share": float(bym.head(10).sum() / tot),
                   "bottom10_matches_pnl_usd": float(bym.tail(10).sum()),
                   "per_share_ex_top10_matches_c": ps(g[~g.cond.isin(bym.head(10).index)]),
                   "per_share_ex_top10_matches_ci_c": cluster_boot(g[~g.cond.isin(bym.head(10).index)], "cond", 1000, 0),
                   "top1_wallet_pnl_share": float(byw.pnl.iloc[0] / tot),
                   "top1_wallet_shares_share": float(byw.shares.iloc[0] / byw.shares.sum()),
                   "top5_wallets_pnl_share": float(byw.pnl.head(5).sum() / tot),
                   "top10_wallets_pnl_share": float(byw.pnl.head(10).sum() / tot),
                   "per_share_ex_top1_wallet_c": ps(g[~g.wallet.isin(byw.index[:1])]),
                   "per_share_ex_top5_wallets_c": ps(g[~g.wallet.isin(byw.index[:5])]),
                   "top_wallets": {w[:10]: {kk: round(float(vv), 2) for kk, vv in r.items()} for w, r in byw.head(5).iterrows()},
                   "top5_days_pnl_share": float(byd.head(5).sum() / tot),
                   "top5_days": {str(d.date()): round(float(v), 1) for d, v in byd.head(5).items()}}
        print("concentration", k, {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in conc[k].items()
                                   if kk != "top_wallets"}, flush=True)
    R["concentration"] = conc

    # ---- 5. leakage: own causal detector + walk-forward qualification + wallet filter ------------
    t0 = time.time()
    cols = ["cond", "ts", "p", "usd", "wallet", "mo30"]
    P = pd.concat([pd.read_parquet(PRINT_FILES[0], columns=cols), pd.read_parquet(PRINT_FILES[1], columns=cols),
                   p2[cols]], ignore_index=True)
    P["cond"] = P.cond.astype("category")
    flag, since = causal_03(P)
    P03 = P[flag.to_numpy()].copy()
    P03["month"] = pd.to_datetime(P03.ts, unit="s").dt.to_period("M").astype(str)
    print("own causal 0-3s prints", len(P03), f"{time.time() - t0:.0f}s", flush=True)
    t2 = tr[tr.is_u2 & (tr.month_own >= EVAL_START)].copy()
    # each U2 trade must be a print my detector labels 0-3 s after a detection
    k3 = ["cond", "ts", "p", "wallet"]
    P03k = P03[k3].astype({"cond": str}).drop_duplicates()
    t2["in_own_03"] = t2[k3].merge(P03k.assign(_x=1), on=k3, how="left")._x.eq(1).to_numpy()
    lk = {"u2_eval_trades": int(len(t2)), "u2_trades_in_own_causal_0_3s": float(t2.in_own_03.mean()),
          "u2_trades_since_det_eq_0_frac": float((t2.since_det == 0).mean())}
    q_by_m, wf_ok, filt_ok = {}, 0, 0
    w_cache = {}
    for m in sorted(t2.month_own.unique()):
        past = P03[P03.month < m]
        sel_w = qualified(past)
        q_by_m[m] = len(sel_w)
        ix = t2.month_own == m
        wf_ok += int(t2.loc[ix, "wallet"].isin(sel_w).sum())
        pool = float(past.mo30.mean())
        g = past.groupby("wallet").mo30.agg(["sum", "size"])
        eff = ((g["sum"] + 200 * pool) / (g["size"] + 200)) - pool
        tm = t2[ix]
        qq = np.where(tm.dir > 0, tm.p, 1 - tm.p)
        fee = tm.cond.map(meta.fee_rate.fillna(0.0)).to_numpy() * qq * (1 - qq)
        filt_ok += int(((pool + tm.wallet.map(eff).fillna(0.0).to_numpy() - fee) > 0).sum())
        w_cache[m] = (len(past), past.ts.max())
    lk["u2_trades_wallet_qualified_on_months_lt_m"] = wf_ok / len(t2)
    lk["u2_trades_pass_wallet_filter_months_lt_m"] = filt_ok / len(t2)
    lk["own_qualified_wallets_by_month"] = q_by_m
    lk["reported_qualified_wallets_by_month"] = rep["fast_minus_others_u2"]["qualified_wallets_by_month"]
    lk["max_print_ts_used_for_month_lt_first_trade"] = {m: str(pd.Timestamp(v[1], unit="s")) for m, v in w_cache.items()}
    # trades never precede their match start or follow the market close used as `end`
    u2s = pd.read_parquet("data/expand_universe.parquet", columns=["cond", "start", "end"]).set_index("cond")
    lk["u2_trades_before_start"] = int((t2.ts < t2.cond.map(u2s.start).map(lambda v: v.timestamp())).sum())
    lk["u2_trades_after_end"] = int((t2.ts > t2.cond.map(u2s.end).map(lambda v: v.timestamp())).sum())
    R["leakage"] = lk
    print("leakage", {k: v for k, v in lk.items() if "by_month" not in k and "max_print" not in k}, flush=True)
    print("qualified by month own vs reported", q_by_m, rep["fast_minus_others_u2"]["qualified_wallets_by_month"], flush=True)

    # ---- 6. verdict on the reported primary ----------------------------------------------------
    prim = {}
    for k in ("u2_is", "u2_oos"):
        b = R["books"][k]
        prim[k] = {"per_share_c": b["per_share_c"], "ci_c": b["ci_seed0_1000_c"],
                   "ci_10000_c": b["ci_seed12345_10000_c"], "pass": b["ci_seed0_1000_c"][0] > 0,
                   "max_rel_diff_vs_reported": b["max_rel_diff_vs_reported"]}
    prim["verdict_independent"] = "PASS" if prim["u2_is"]["pass"] and prim["u2_oos"]["pass"] else "FAIL"
    prim["verdict_reported"] = rep["primary"]["verdict"]
    R["primary"] = prim
    print("PRIMARY", json.dumps(prim), flush=True)
    if out_json:
        Path(out_json).write_text(json.dumps(R, indent=2, default=str))


if __name__ == "__main__":
    if sys.argv[1] == "rerun":
        rerun(sys.argv[2])
    elif sys.argv[1] == "check":
        check(sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None,
              sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        raise SystemExit(__doc__)
