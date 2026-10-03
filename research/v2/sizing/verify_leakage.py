"""Adversarial reviewer check of the sizing lens (IS only, independent of engine.py).

    .venv/bin/python research/v2/sizing/verify_leakage.py      # ~2-4 min, 1 process
      -> research/v2/sizing/out/verify_leakage.json (+ printed tables)

Re-implements the recommended policy G_50pct_net100 from the raw IS tables (shadow_is_uncapped,
universe_is, prints_0_3s_is) without importing engine.py, then runs leakage / sign / unit probes:

  0. integrity: OOS boundary, month = month(ts), per-row fee_rate / delay / res == universe_is
  1. the walk-forward fast-tier wallet set of month m is reproducible from months < m only
  2. independent recomputation of the headline (per-share, Sharpe, DD, months+, 1s/5% per share)
  3. within-second order shuffle (net cap is path dependent)
  4. jump-window lookahead: the 0-3 s bucket is defined from an onset that the detector confirms up
     to 10 s later. (a) share of the book's prints that occur BEFORE the jump is detectable;
     (b) the policy restricted to prints at/after detect_ts; (c) the same policy (same monthly R,
     same wallet gate, same caps) on ALL prints of the same walk-forward fast-tier wallets, i.e. an
     opportunity set that does not condition on a future >= 4c move.
  5. units: is_prints.usd = size * traded-token price, so usd/q is not the share count of taker
     SELL prints. Measured on the tapes of the 1 s/5% matches.
  6. grid-edge diagnostic: N = 50 / 25 (NOT used to choose anything; shows the chosen N=100 sits at
     the edge of the grid and the trend continues).
No OOS row is read: every input is IS-only and the script asserts it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src import fasttier  # noqa: E402  (qualify() only)

OUT = Path(__file__).resolve().parent / "out"
OOS_START = pd.Timestamp("2026-08-25 14:15", tz="UTC")
EVAL0, RUN0, TRAIN0 = "2026-02", "2026-01", "2025-12"
R_DEPLOY, NET_CAP, USD_CAP, MATCH_CAP, N0_W = 0.5, 100.0, 1000.0, 3000.0, 200.0
QLO, QHI = 0.05, 0.95


def month_of(ts):
    return pd.to_datetime(ts, unit="s").dt.to_period("M").astype(str)


# ------------------------------------------------------------------------------------------ data
def load_universe():
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet",
                        columns=["cond", "start", "end", "res0", "fee_rate", "delay"])
    assert (u.start < OOS_START).all()
    u["end_ts"] = u.end.map(lambda x: x.timestamp() if pd.notna(x) else np.nan)
    return u.set_index("cond")


def prep(df, u):
    df = df.copy()
    df["q"] = np.where(df.dir > 0, df.p, 1 - df.p)
    df["gross_res"] = df.dir * (df.res - df.p)
    df["fee"] = df.fee_rate * df.q * (1 - df.q)
    df["month"] = month_of(df.ts)
    e = df.cond.map(u.end_ts)
    e = e.fillna(df.ts + 4 * 3600)
    df["lock_end"] = np.minimum(np.maximum(e, df.ts), df.ts + 8 * 3600)
    df["regime"] = df.delay.astype(int).astype(str) + "s/" + (df.fee_rate * 100).round().astype(int).astype(str) + "%"
    df["date"] = pd.to_datetime(df.ts, unit="s", utc=True).dt.floor("D")
    return df


def load_shadow(u):
    sh = pd.read_parquet(ROOT / "data/derived/shadow_is_uncapped.parquet",
                         columns=["cond", "ts", "p", "dir", "usd", "wallet", "since", "fee_rate", "delay", "res",
                                  "mo30", "month"])
    chk = {}
    chk["shadow_rows"] = len(sh)
    chk["all_conds_in_universe_is"] = bool(sh.cond.isin(u.index).all())
    chk["max_match_start"] = str(u.loc[sh.cond.unique(), "start"].max())
    chk["max_print_ts"] = str(pd.to_datetime(sh.ts.max(), unit="s", utc=True))
    chk["month_col_equals_month_of_ts"] = bool((sh.month.astype(str) == month_of(sh.ts)).all())
    chk["fee_rate_matches_universe"] = bool(np.allclose(sh.fee_rate, sh.cond.map(u.fee_rate)))
    chk["delay_matches_universe"] = bool((sh.delay == sh.cond.map(u.delay)).all())
    chk["res_matches_universe"] = bool(np.allclose(sh.res, sh.cond.map(u.res0)))
    chk["res_half_rows"] = int((sh.res == 0.5).sum())
    sh = prep(sh.drop(columns="month"), u)
    # reproduce the lens' row order: sorted by (cond, ts) then stably by ts
    sh = sh.sort_values(["cond", "ts"], kind="stable").sort_values("ts", kind="stable").reset_index(drop=True)
    return sh, chk


def load_p03():
    w = pd.read_parquet(ROOT / "data/derived/prints_0_3s_is.parquet", columns=["cond", "ts", "wallet", "mo30"])
    w["month"] = month_of(w.ts)
    return w


# ------------------------------------------------------------------------------- walk-forward fits
def qualified_by_month(p03, months):
    out = {}
    for m in months:
        past = p03[p03.month < m]
        out[m] = set(fasttier.qualify(past.assign(bucket="0-3s")))
    return out


def wallet_gate_tables(p03, months):
    out = {}
    for m in months:
        d = p03[p03.month < m]
        pool = float(d.mo30.mean())
        g = d.groupby("wallet").mo30.agg(["sum", "size"])
        out[m] = (((g["sum"] + N0_W * pool) / (g["size"] + N0_W)).to_dict(), pool)
    return out


def cap_shares(q, usd, k):
    return np.minimum(np.minimum(k * USD_CAP / np.sqrt(q * (1 - q)), usd / q), USD_CAP / q)


def fit_k(train):
    q, usd = train.q.to_numpy(), train.usd.to_numpy()
    target = R_DEPLOY * np.minimum(usd, USD_CAP).mean()
    lo, hi = 1e-8, 1e8
    for _ in range(100):
        mid = np.sqrt(lo * hi)
        if (cap_shares(q, usd, mid) * q).mean() < target:
            lo = mid
        else:
            hi = mid
    return np.sqrt(lo * hi)


def targets(df, ks, gates, allow=None):
    tgt = np.zeros(len(df))
    for m, idx in df.groupby("month").indices.items():
        if m < RUN0:
            continue
        t = df.iloc[idx]
        q = t.q.to_numpy()
        sh = cap_shares(q, t.usd.to_numpy(), ks[m])
        shrunk, pool = gates[m]
        w = t.wallet.map(shrunk).fillna(pool).to_numpy()
        ok = (w > t.fee.to_numpy()) & (q >= QLO) & (q <= QHI)
        tgt[idx] = np.where(ok, sh, 0.0)
    if allow is not None:
        tgt = np.where(allow, tgt, 0.0)
    return tgt


def apply_caps(df, tgt, net_cap=NET_CAP, order=None):
    n = len(df)
    order = np.arange(n) if order is None else order
    q = df.q.to_numpy(); d = df.dir.to_numpy(); c = df.cond.to_numpy()
    gross, net = {}, {}
    out = np.zeros(n)
    for i in order:
        t = tgt[i]
        if t <= 0:
            continue
        ci = c[i]
        room = MATCH_CAP - gross.get(ci, 0.0)
        if room <= 0:
            continue
        s = min(t, room / q[i], max(0.0, net_cap - d[i] * net.get(ci, 0.0)))
        if s <= 1e-9:
            continue
        out[i] = s
        gross[ci] = gross.get(ci, 0.0) + s * q[i]
        net[ci] = net.get(ci, 0.0) + d[i] * s
    return out


# ------------------------------------------------------------------------------------------ metrics
def summarize(df, shares, label, boot=2000):
    t = df.assign(shares=shares)
    t = t[(t.shares > 0) & (t.month >= EVAL0)].copy()
    if t.empty:
        return {"label": label, "n": 0}
    t["pnl"] = t.shares * (t.gross_res - t.fee)
    t["usd_in"] = t.shares * t.q
    daily = t.groupby("date").pnl.sum()
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC"), fill_value=0.0)
    eq = daily.cumsum()
    ev = pd.concat([pd.DataFrame({"t": t.ts, "d": t.usd_in}), pd.DataFrame({"t": t.lock_end, "d": -t.usd_in})])
    cap = 3 * float(ev.sort_values("t", kind="stable").d.cumsum().max())
    g = t.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
    rng = np.random.default_rng(0)
    P, S = g.p.to_numpy(), g.s.to_numpy()
    bs = [P[i].sum() / S[i].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(boot))]
    mon = t.groupby("month").pnl.sum()
    out = {"label": label, "n": int(len(t)), "matches": int(len(g)),
           "per_share_c": float(t.pnl.sum() / t.shares.sum() * 100),
           "ci_c": [float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)],
           "pnl_usd": float(t.pnl.sum()), "usd_traded": float(t.usd_in.sum()),
           "sharpe_ann": float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else np.nan,
           "max_dd_usd": float((eq - eq.cummax()).min()), "capital_usd": cap,
           "max_dd_pct": float((eq - eq.cummax()).min() / cap * 100) if cap else np.nan,
           "months_pos": f"{int((mon > 0).sum())}/{len(mon)}",
           "monthly_per_share_c": {m: float(x.pnl.sum() / x.shares.sum() * 100) for m, x in t.groupby("month")}}
    r5 = t[t.regime == "1s/5%"]
    if len(r5):
        g5 = r5.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
        P5, S5 = g5.p.to_numpy(), g5.s.to_numpy()
        bs5 = [P5[i].sum() / S5[i].sum() for i in (rng.integers(0, len(g5), len(g5)) for _ in range(boot))]
        out["r1s5_per_share_c"] = float(r5.pnl.sum() / r5.shares.sum() * 100)
        out["r1s5_ci_c"] = [float(np.percentile(bs5, 2.5) * 100), float(np.percentile(bs5, 97.5) * 100)]
        out["r1s5_pnl_usd"] = float(r5.pnl.sum())
        out["r1s5_n"] = int(len(r5))
    return out


def show(r):
    keys = ["label", "n", "per_share_c", "ci_c", "pnl_usd", "sharpe_ann", "max_dd_pct", "months_pos",
            "r1s5_per_share_c", "r1s5_ci_c", "r1s5_pnl_usd"]
    print({k: (np.round(r[k], 3).tolist() if isinstance(r.get(k), list) else
               (round(r[k], 3) if isinstance(r.get(k), float) else r.get(k))) for k in keys})


# ---------------------------------------------------------------------------------------------- main
def main():
    res = {}
    u = load_universe()
    sh, chk = load_shadow(u)
    res["integrity"] = chk
    print("integrity", chk)
    assert chk["all_conds_in_universe_is"] and pd.Timestamp(chk["max_match_start"]) < OOS_START
    p03 = load_p03()
    assert p03.cond.isin(u.index).all()
    months = sorted(m for m in sh.month.unique() if m >= RUN0)

    # 1. fast-tier wallet set of month m reproducible from months < m only
    qual = qualified_by_month(p03, sorted(set(sh.month)))
    q_rows = []
    for m in sorted(set(sh.month)):
        ws = set(sh.loc[sh.month == m, "wallet"])
        exp = p03[(p03.month == m) & p03.wallet.isin(qual[m])]
        q_rows.append({"month": m, "shadow_wallets": len(ws), "requalified": len(qual[m]),
                       "shadow_subset_of_requalified": ws <= qual[m],
                       "shadow_rows": int((sh.month == m).sum()), "requalified_rows": int(len(exp))})
    res["wallet_requalification"] = q_rows
    print(pd.DataFrame(q_rows).to_string(index=False))

    # 2. independent recomputation of G_50pct_net100
    gates = wallet_gate_tables(p03, months)
    ks = {m: fit_k(sh[(sh.month >= TRAIN0) & (sh.month < m)]) for m in months}
    res["R_usd_by_month"] = {m: k * USD_CAP for m, k in ks.items()}
    run = sh[sh.month >= RUN0].reset_index(drop=True)
    tgt = targets(run, ks, gates)
    shares = apply_caps(run, tgt)
    rec = summarize(run, shares, "G_50pct_net100 (independent)")
    res["recomputed_headline"] = rec
    show(rec)
    res["claimed"] = {"per_share_c": 1.58, "ci": [1.36, 1.80], "sharpe": 16.77, "pnl": 43268, "max_dd_pct": -3.98,
                      "months_pos": "7/7", "r1s5_per_share_c": 0.89, "r1s5_ci": [0.47, 1.31]}

    # 3. within-second order shuffle
    shuf = []
    key = run.cond + "|" + run.ts.astype(int).astype(str)
    for seed in range(5):
        rng = np.random.default_rng(seed)
        r = rng.random(len(run))
        order = np.lexsort((r, run.ts.to_numpy()))  # by ts, random within second (across all conds)
        s = apply_caps(run, tgt, order=order)
        x = summarize(run, s, f"shuffle_seed{seed}", boot=200)
        shuf.append({k: x[k] for k in ("per_share_c", "pnl_usd", "sharpe_ann", "r1s5_per_share_c")})
    res["within_second_shuffle"] = shuf
    res["prints_sharing_a_second_with_same_match"] = float(key.duplicated(keep=False).mean())
    print("shuffle", pd.DataFrame(shuf).round(3).to_dict("list"))

    # 4. jump-window lookahead
    j = pd.read_parquet(ROOT / "data/derived/jumps_is.parquet", columns=["cond", "onset_ts", "detect_ts", "size"])
    run["onset_ts"] = run.ts - run.since
    run2 = run.merge(j, on=["cond", "onset_ts"], how="left", validate="many_to_one")
    assert len(run2) == len(run)
    matched = run2.detect_ts.notna()
    pre = (run2.ts < run2.detect_ts).to_numpy()
    taken = shares > 0
    ev = (run.month >= EVAL0).to_numpy()
    pnl_ps = (run.gross_res - run.fee).to_numpy()
    look = {"jump_matched_share": float(matched.mean()),
            "share_of_book_prints_before_detect": float(pre[taken & ev].mean()),
            "share_of_book_shares_before_detect": float(shares[taken & ev & pre].sum() / shares[taken & ev].sum()),
            "book_pnl_from_prints_before_detect_usd": float((shares * pnl_ps)[taken & ev & pre].sum()),
            "book_pnl_total_usd": float((shares * pnl_ps)[taken & ev].sum())}
    r5 = (run.regime == "1s/5%").to_numpy()
    look["r1s5_share_of_book_prints_before_detect"] = float(pre[taken & r5].mean())
    look["r1s5_pnl_before_detect_usd"] = float((shares * pnl_ps)[taken & r5 & pre].sum())
    look["r1s5_pnl_at_or_after_detect_usd"] = float((shares * pnl_ps)[taken & r5 & ~pre].sum())
    # (b) the policy run only on prints whose jump window is known at print time
    s_post = apply_caps(run, targets(run, ks, gates, allow=~pre))
    look["policy_on_post_detect_prints_only"] = summarize(run, s_post, "post-detect only")
    show(look["policy_on_post_detect_prints_only"])
    res["jump_window_lookahead"] = look
    print({k: v for k, v in look.items() if not isinstance(v, dict)})

    # (c) clean opportunity set: ALL prints of the same walk-forward fast-tier wallets (no jump conditioning)
    all_w = sorted(set().union(*[qual[m] for m in months]))
    t = pq.read_table(ROOT / "data/is_prints.parquet",
                      columns=["cond", "ts", "p", "dir", "usd", "wallet", "fee_rate", "delay", "res", "mo30", "bucket"],
                      filters=[("wallet", "in", all_w)])
    ap = t.to_pandas(); del t
    ap["cond"] = ap.cond.astype(str); ap["wallet"] = ap.wallet.astype(str); ap["bucket"] = ap.bucket.astype(str)
    assert ap.cond.isin(u.index).all()
    ap = prep(ap, u)
    ap = ap[ap.month >= RUN0]
    keep = np.zeros(len(ap), bool)
    for m in months:
        keep |= ((ap.month == m) & ap.wallet.isin(qual[m])).to_numpy()
    ap = ap[keep].sort_values(["cond", "ts"], kind="stable").sort_values("ts", kind="stable").reset_index(drop=True)
    tg = targets(ap, ks, gates)
    s_all = apply_caps(ap, tg)
    clean = {"rows_all_buckets": int(len(ap)), "rows_0_3s": int((ap.bucket == "0-3s").sum())}
    clean["all_buckets"] = summarize(ap, s_all, "all prints of WF fast-tier wallets (same R, gate, caps)")
    show(clean["all_buckets"])
    no03 = (ap.bucket != "0-3s").to_numpy()
    s_out = apply_caps(ap, np.where(no03, tg, 0.0))
    clean["outside_0_3s_only"] = summarize(ap, s_out, "outside 0-3 s only")
    show(clean["outside_0_3s_only"])
    # gross / net per print, unweighted, 1s/5%
    a5 = ap[(ap.regime == "1s/5%")]
    clean["r1s5_unweighted_gross30_c"] = a5.groupby(a5.bucket == "0-3s").mo30.mean().mul(100).rename(
        {True: "in_0_3s", False: "outside"}).to_dict()
    clean["r1s5_unweighted_net_res_c"] = (a5.gross_res - a5.fee).groupby(a5.bucket == "0-3s").mean().mul(100).rename(
        {True: "in_0_3s", False: "outside"}).to_dict()
    res["clean_opportunity_set"] = clean
    print({k: v for k, v in clean.items() if not isinstance(v, dict) or k.startswith("r1s5")})

    # 5. units: usd/q vs tape share count, on the 1 s/5% matches
    c5 = run.loc[run.regime == "1s/5%", "cond"].unique()
    rows = []
    for c in c5:
        f = ROOT / "data/raw/trades" / f"{c}.parquet"
        if not f.exists():
            continue
        tp = pd.read_parquet(f, columns=["timestamp", "side", "outcomeIndex", "price", "size", "proxyWallet", "p0"])
        tp["usd"] = tp["size"] * tp["price"]
        tp["cond"] = c
        rows.append(tp)
    tp = pd.concat(rows, ignore_index=True)
    tp["k_usd"] = tp.usd.round(4); tp["k_p"] = tp.p0.round(6)
    s5 = run[run.regime == "1s/5%"].copy()
    s5["row"] = s5.index
    s5["k_usd"] = s5.usd.round(4); s5["k_p"] = s5.p.round(6)
    mm = s5.merge(tp.drop_duplicates(["cond", "timestamp", "proxyWallet", "k_p", "k_usd"]),
                  left_on=["cond", "ts", "wallet", "k_p", "k_usd"],
                  right_on=["cond", "timestamp", "proxyWallet", "k_p", "k_usd"], how="left")
    mm = mm.drop_duplicates("row").set_index("row").reindex(s5.index)
    ok = mm["size"].notna()
    ratio = (s5.usd / s5.q) / mm["size"]
    units = {"r1s5_rows": int(len(s5)), "matched_to_tape": float(ok.mean()),
             "share_taker_SELL": float((mm.side[ok] == "SELL").mean()),
             "usd_over_q_div_true_size_median_SELL": float(ratio[ok & (mm.side == "SELL")].median()),
             "usd_over_q_div_true_size_p90_SELL": float(ratio[ok & (mm.side == "SELL")].quantile(.9)),
             "usd_over_q_div_true_size_max_BUY_abs_dev": float((ratio[ok & (mm.side == "BUY")] - 1).abs().max())}
    # book trades that exceed the TRUE print size (liquidity constraint violated)
    taken5 = pd.Series(shares, index=run.index)[s5.index]
    viol = ok & (taken5 > mm["size"] * 1.0001)
    units["book_trades_exceeding_true_print_size"] = int(viol.sum())
    units["book_trades_r1s5"] = int((taken5 > 0).sum())
    # re-run 1s/5% matches with their_shares = true tape size (caps are per-match, so this is exact)
    fixed_usd = s5.usd.where(~ok, mm["size"] * s5.q)
    run_fx = run.copy()
    run_fx.loc[s5.index, "usd"] = fixed_usd
    s_fx = apply_caps(run_fx, targets(run_fx, ks, gates))
    fx = summarize(run_fx, s_fx, "their_shares = tape size (1s/5% matches corrected)")
    units["r1s5_per_share_c_corrected"] = fx.get("r1s5_per_share_c")
    units["r1s5_ci_c_corrected"] = fx.get("r1s5_ci_c")
    units["r1s5_pnl_corrected"] = fx.get("r1s5_pnl_usd")
    res["units_usd_over_q"] = units
    print(units)

    # 6. grid-edge diagnostic (not a selection)
    edge = []
    for nc in (500, 250, 100, 50, 25, 10):
        x = summarize(run, apply_caps(run, tgt, net_cap=nc), f"net{nc}", boot=200)
        edge.append({"net_cap": nc, "sharpe": x["sharpe_ann"], "pnl": x["pnl_usd"], "per_share_c": x["per_share_c"],
                     "r1s5_per_share_c": x.get("r1s5_per_share_c"), "max_dd_pct": x["max_dd_pct"]})
    res["net_cap_grid_edge"] = edge
    print(pd.DataFrame(edge).round(3).to_string(index=False))

    OUT.mkdir(exist_ok=True)
    (OUT / "verify_leakage.json").write_text(json.dumps(res, indent=2, default=lambda o: o if not isinstance(o, (np.floating, np.integer, np.bool_)) else o.item()))
    print("wrote", OUT / "verify_leakage.json")


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
