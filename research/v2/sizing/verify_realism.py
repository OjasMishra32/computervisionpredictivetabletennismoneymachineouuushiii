"""Adversarial realism / statistics checks on the sizing lens's recommended policy (IS only).

    .venv/bin/python research/v2/sizing/verify_realism.py        # from the repo root; ~5 min fresh, 2 procs
      -> research/v2/sizing/out/verify_*.csv, out/verify_summary.json
    Simulations are cached in data/v2_sizing/verify_sims.pkl and verify_sims2.pkl; delete them to recompute.

Checks (every simulation reuses engine.py's walk-forward rules; nothing is fitted on OOS):
  1 reproduce   G_50pct_net100 and A0 (res, actual fee): overall and 1 s/5% per share, Sharpe, DD
  2 min order   venue minimum order is 5 shares: share of trades below 5 sh, and a re-simulation where
                a clip < 5 sh is skipped (and fast-tier prints < 5 sh are not copyable)
  3 copy lag    what a REMOTE trader could get: enter at the first same-side print >= ts+L s
                (L = 0 sanity, 1, 2, 3, 5), same shares, held to resolution, fee at the copy price
  4 concentration  P&L share of top wallets / matches / days; leave-top-wallet-out re-simulation
  5 plateau     net cap N in {25, 50, 100, 150, 250} x deploy fraction {0.35, 0.5, 0.65}
                (verification variants, not menu additions)
  6 trend       weekly per-share inside 1 s/5%; linear trend of the monthly per-share
  7 statistics  day-block bootstrap of 1 s/5% Sharpe and per-share; deflated Sharpe with N = 115;
                Bonferroni (Harvey-Liu style) haircut of the t-stat
  8 cost stress extra slippage per share (book walking if we are ADDITIONAL to the fast tier) and
                break-even fee rate in 1 s/5%
  9 intra-second  other same-side prints in the fast-tier print's own second vs their price
  10 window position  how much the net cap tilts the book toward first clips / since < 1 s (the
                window-contaminated features the lens excluded)
Verification variants run here (not menu additions): 11 policy re-simulations (N grid x deploy grid,
min-order, 3 leave-out runs). IS only: features.parquet and is_prints are IS-only; asserts check ts.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import engine as E  # noqa: E402
import walkforward as W  # noqa: E402

OUT = HERE / "out"
OOS_START = pd.Timestamp("2026-08-25 14:15", tz="UTC").timestamp()
REC = W.RECOMMENDED
POL = {p.name: p for p in W.POLICIES}
_F = _W = None


def _init():
    global _F, _W
    _F, _W = E.load(), E.load_wallet_hist()
    assert _F.ts.max() < OOS_START + 8 * 3600


# --------------------------------------------------------------- min-order variant of apply_caps
def apply_caps_min(df, tgt, pol, min_sh=5.0):
    """engine.apply_caps without stops, plus: a fill below min_sh shares is skipped, and a fast-tier
    print below min_sh shares is not copyable."""
    n = len(df)
    q = df.q.to_numpy(); d = df.dir.to_numpy(); cond = df.cond.to_numpy()
    their = df.their_shares.to_numpy()
    m_gross, m_net = {}, {}
    out = np.zeros(n)
    for i in range(n):
        t = tgt[i]
        if not (t > 0) or their[i] < min_sh:
            continue
        c = cond[i]
        room = pol.match_cap - m_gross.get(c, 0.0)
        if room <= 0:
            continue
        s = min(t, room / q[i])
        if np.isfinite(pol.net_cap):
            s = min(s, max(0.0, pol.net_cap - d[i] * m_net.get(c, 0.0)))
        s = np.floor(s * 100) / 100            # share precision 0.01
        if s < min_sh:
            continue
        out[i] = s
        m_gross[c] = m_gross.get(c, 0.0) + s * q[i]
        m_net[c] = m_net.get(c, 0.0) + d[i] * s
    return out


def simulate_min(f, pol, measure, fee_mode, whist):
    months = sorted(m for m in f.month.unique() if m >= E.RUN_START)
    parts = [E.month_targets(f[f.month == m], f[f.month < m], pol, fee_mode, whist, m, measure) for m in months]
    run = f[f.month >= E.RUN_START].reset_index(drop=True)
    tgt = np.concatenate(parts)
    pnl = np.nan_to_num(E.pnl_ps(run, measure, fee_mode))
    shares = apply_caps_min(run, tgt, pol)
    tr = run.assign(shares=shares, pnl_ps=pnl, target=tgt)
    tr = tr[tr.shares > 0].copy()
    tr["usd_in"] = tr.shares * tr.q
    tr["pnl"] = tr.shares * tr.pnl_ps
    return tr


def summ(tr, label, extra=None):
    tr = tr[tr.month >= E.EVAL_START]
    out = {"label": label, "n": len(tr), "matches": tr.cond.nunique(), "pnl_usd": tr.pnl.sum(),
           "usd_traded": tr.usd_in.sum(), "shares": tr.shares.sum()}
    for sub, t in (("all", tr), ("1s5", tr[tr.regime == "1s/5%"]), ("aug", tr[tr.month == "2026-08"])):
        if t.empty:
            continue
        d = E.daily_series(t)
        eq = d.cumsum()
        g = t.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
        rng = np.random.default_rng(0)
        P, S = g.p.to_numpy(), g.s.to_numpy()
        bs = [P[i].sum() / S[i].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(1000))]
        out[f"{sub}_per_share_c"] = t.pnl.sum() / t.shares.sum() * 100
        out[f"{sub}_ci_lo_c"] = np.percentile(bs, 2.5) * 100
        out[f"{sub}_ci_hi_c"] = np.percentile(bs, 97.5) * 100
        out[f"{sub}_sharpe"] = d.mean() / d.std() * np.sqrt(365) if d.std() > 0 else np.nan
        out[f"{sub}_pnl_usd"] = t.pnl.sum()
        out[f"{sub}_max_dd_usd"] = (eq - eq.cummax()).min()
    if extra:
        out.update(extra)
    return out


# ------------------------------------------------------------------------------- job runner
def job(args):
    kind, name, kw = args
    pol = replace(POL[name], **kw) if kw else POL[name]
    label = name + ("" if not kw else "|" + ",".join(f"{k}={v}" for k, v in kw.items()))
    if kind == "std":
        tr = E.simulate(_F, pol, "res", "actual", _W)
    elif kind == "min5":
        tr = simulate_min(_F, pol, "res", "actual", _W)
        label += "|min5"
    elif kind == "drop_wallets":
        f = _F[~_F.wallet.isin(kw_drop[name])]
        tr = E.simulate(f, pol, "res", "actual", _W)
        label += "|drop_top_wallets"
    elif kind.startswith("drop:"):
        key = kind.split(":", 1)[1]
        f = _F[~_F.wallet.isin(kw_drop[key])]
        tr = E.simulate(f, pol, "res", "actual", _W)
        label += "|" + key
    else:
        raise ValueError(kind)
    keep = ["cond", "ts", "dir", "q", "p", "wallet", "month", "regime", "date", "shares", "pnl", "pnl_ps",
            "usd_in", "rate", "gross_res", "gross30", "their_shares", "target"]
    return label, tr[keep].reset_index(drop=True)


kw_drop: dict = {}


# ------------------------------------------------------------------------------------- copy lag
def copy_lag(tr: pd.DataFrame, lags=(0, 1, 2, 3, 5), window=10.0) -> pd.DataFrame:
    conds = tr.cond.unique()
    t = pq.read_table(ROOT / "data/is_prints.parquet", columns=["cond", "ts", "p", "dir"],
                      read_dictionary=["cond"])
    pr = t.to_pandas(); del t
    pr = pr[pr.cond.isin(set(conds))]
    assert pr.ts.max() < OOS_START + 8 * 3600
    pr = pr.sort_values(["cond", "ts"], kind="stable")
    groups = {str(c): g for c, g in pr.groupby("cond", sort=False, observed=True)}
    del pr
    rows = []
    # res (outcome-0 payout) recovered from gross_res = dir*(res-p)
    tr = tr.assign(res0=np.where(tr.dir > 0, tr.gross_res + tr.p, tr.p - tr.gross_res))
    for L in lags:
        pf = np.full(len(tr), np.nan)
        for c, idx in tr.groupby("cond").indices.items():
            g = groups[c]
            ts_all, p_all, d_all = g.ts.to_numpy(), g.p.to_numpy(), g.dir.to_numpy()
            sub = tr.iloc[idx]
            for dd in (1.0, -1.0):
                m = d_all == dd
                ts_d, p_d = ts_all[m], p_all[m]
                sel = np.where(sub.dir.to_numpy() == dd)[0]
                if len(sel) == 0 or len(ts_d) == 0:
                    continue
                tt = sub.ts.to_numpy()[sel] + L
                j = np.searchsorted(ts_d, tt, "left")
                ok = j < len(ts_d)
                jj = np.minimum(j, len(ts_d) - 1)
                ok &= ts_d[jj] <= tt + window
                vals = np.where(ok, p_d[jj], np.nan)
                pf[idx[sel]] = vals
        d = tr.dir.to_numpy()
        qf = np.where(d > 0, pf, 1 - pf)
        fee = tr.rate.to_numpy() * qf * (1 - qf)
        pnl_ps = d * (tr.res0.to_numpy() - pf) - fee
        x = tr.assign(pnl_ps_f=pnl_ps, pnl_f=pnl_ps * tr.shares, slip=(qf - tr.q) * 100)
        for sub_name, s in (("all", x), ("1s5", x[x.regime == "1s/5%"]), ("aug", x[x.month == "2026-08"])):
            s = s[s.month >= E.EVAL_START]
            filled = s[np.isfinite(s.pnl_ps_f)]
            g = filled.groupby("cond").agg(p=("pnl_f", "sum"), s=("shares", "sum"))
            rng = np.random.default_rng(1)
            P, S = g.p.to_numpy(), g.s.to_numpy()
            bs = [P[i].sum() / S[i].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(1000))]
            shadow_same = filled.pnl.sum() / filled.shares.sum() * 100
            rows.append({"lag_s": L, "subset": sub_name, "fill_rate": len(filled) / max(len(s), 1),
                         "per_share_c": filled.pnl_f.sum() / filled.shares.sum() * 100,
                         "ci_lo_c": np.percentile(bs, 2.5) * 100, "ci_hi_c": np.percentile(bs, 97.5) * 100,
                         "shadow_per_share_same_rows_c": shadow_same,
                         "mean_slippage_c": float((filled.slip * filled.shares).sum() / filled.shares.sum()),
                         "pnl_usd": filled.pnl_f.sum()})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------- statistics
def block_boot_sharpe(daily: pd.Series, block=5, n=4000, seed=2):
    x = daily.to_numpy(); T = len(x)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(T / block))
    out = []
    for _ in range(n):
        st = rng.integers(0, T - block + 1, nb)
        s = np.concatenate([x[i:i + block] for i in st])[:T]
        out.append(s.mean() / s.std() * np.sqrt(365) if s.std() > 0 else np.nan)
    return np.nanpercentile(out, [2.5, 50, 97.5])


def day_cluster_ci(t: pd.DataFrame, n=2000, seed=3):
    g = t.groupby("date").agg(p=("pnl", "sum"), s=("shares", "sum"))
    rng = np.random.default_rng(seed)
    P, S = g.p.to_numpy(), g.s.to_numpy()
    bs = [P[i].sum() / S[i].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(n))]
    return np.percentile(bs, [2.5, 97.5]) * 100


def dsr(sr, trials_var, N, T, skew, kurt):
    g = 0.5772156649
    sr0 = np.sqrt(trials_var) * ((1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * np.e)))
    den = np.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    return float(norm.cdf((sr - sr0) * np.sqrt(T - 1) / den)), float(sr0)


def main():
    OUT.mkdir(exist_ok=True)
    pd.set_option("display.width", 250)
    _init()
    f = _F
    summary = {}

    # top wallets of the recommended policy (needed for the leave-out job); computed in this process
    rec = E.simulate(f, POL[REC], "res", "actual", _W)
    rec_e = rec[rec.month >= E.EVAL_START]
    top_w = rec_e.groupby("wallet").pnl.sum().sort_values(ascending=False)
    kw_drop[REC] = list(top_w.index[:1])
    kw_drop["__top3"] = list(top_w.index[:3])

    jobs = [("std", "A0_base_usd1k_match3k", None), ("min5", REC, None), ("drop_wallets", REC, None)]
    for N in (25, 50, 150):
        jobs.append(("std", REC, {"net_cap": float(N), "name": f"G_50pct_net{N}"}))
    for fr in (0.35, 0.65):
        for N in (50, 100, 250):
            jobs.append(("std", REC, {"deploy_frac": fr, "net_cap": float(N), "name": f"G_{int(fr*100)}pct_net{N}"}))
    # 'name' must not be passed to label twice; strip it for labels
    jobs = [(k, n, kw) for k, n, kw in jobs]
    results = {}
    results[REC] = rec[["cond", "ts", "dir", "q", "p", "wallet", "month", "regime", "date", "shares", "pnl", "pnl_ps",
                        "usd_in", "rate", "gross_res", "gross30", "their_shares", "target"]]
    cache = ROOT / "data/v2_sizing/verify_sims.pkl"
    if cache.exists():
        import pickle
        results.update(pickle.loads(cache.read_bytes()))
    else:
        with ProcessPoolExecutor(2, initializer=_init_with_drop, initargs=(kw_drop,)) as ex:
            for label, tr in ex.map(job, jobs):
                results[label] = tr
                print("done", label, flush=True)
        import pickle
        cache.write_bytes(pickle.dumps({k: v for k, v in results.items() if k != REC}))

    # extra leave-out jobs keyed on the 1 s/5% regime's own top wallets (separate cache)
    r5_top = rec_e[rec_e.regime == "1s/5%"].groupby("wallet").pnl.sum().sort_values(ascending=False)
    kw_drop["__top1_1s5"] = list(r5_top.index[:1]); kw_drop["__top3_1s5"] = list(r5_top.index[:3])
    cache2 = ROOT / "data/v2_sizing/verify_sims2.pkl"
    import pickle
    if cache2.exists():
        results.update(pickle.loads(cache2.read_bytes()))
    else:
        extra = {}
        with ProcessPoolExecutor(2, initializer=_init_with_drop, initargs=(kw_drop,)) as ex:
            for label, tr in ex.map(job, [("drop:__top1_1s5", REC, None), ("drop:__top3_1s5", REC, None)]):
                extra[label] = tr
                print("done", label, flush=True)
        cache2.write_bytes(pickle.dumps(extra))
        results.update(extra)

    # ---------------------------------------------------------------- 1 reproduce
    rows = [summ(results[REC], REC), summ(results["A0_base_usd1k_match3k"], "A0_base_usd1k_match3k")]
    rep = pd.DataFrame(rows)
    print(rep.round(3).T.to_string())
    summary["reproduce"] = rep.round(4).to_dict("records")

    # ---------------------------------------------------------------- 2 min order
    r = results[REC]
    re_ = r[r.month >= E.EVAL_START]
    r5 = re_[re_.regime == "1s/5%"]
    small = {
        "share_trades_lt5sh_all": float((re_.shares < 5).mean()),
        "share_trades_lt5sh_1s5": float((r5.shares < 5).mean()),
        "share_pnl_from_lt5sh_1s5": float(r5[r5.shares < 5].pnl.sum() / r5.pnl.sum()),
        "share_their_print_lt5sh_1s5": float((r5.their_shares < 5).mean()),
        "median_shares_1s5": float(r5.shares.median()), "median_usd_1s5": float(r5.usd_in.median()),
        "mean_usd_1s5": float(r5.usd_in.mean()),
        "share_trades_clipped_below_target_1s5": float((r5.shares < r5.target - 1e-6).mean()),
    }
    mn = [k for k in results if k.endswith("|min5")][0]
    small_sim = summ(results[mn], "min5")
    print("min order", small, "\n", pd.Series({k: v for k, v in small_sim.items() if k != "label"}).round(3).to_string())
    summary["min_order"] = {**small, "resim": {k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                                               for k, v in small_sim.items()}}

    # ---------------------------------------------------------------- 3 copy lag
    cl = copy_lag(results[REC])
    cl_base = copy_lag(results["A0_base_usd1k_match3k"], lags=(0, 1, 2))
    cl["policy"] = REC; cl_base["policy"] = "A0"
    clall = pd.concat([cl, cl_base])
    clall.round(4).to_csv(OUT / "verify_copy_lag.csv", index=False)
    print(clall.round(3).to_string(index=False))
    summary["copy_lag"] = clall.round(4).to_dict("records")

    # ---------------------------------------------------------------- 4 concentration
    conc = {}
    for sub, t in (("all", re_), ("1s5", r5)):
        tot = t.pnl.sum()
        w = t.groupby("wallet").pnl.sum().sort_values(ascending=False)
        mt = t.groupby("cond").pnl.sum().sort_values(ascending=False)
        dy = t.groupby("date").pnl.sum().sort_values(ascending=False)
        ws = t.groupby("wallet").shares.sum().sort_values(ascending=False)
        conc[sub] = {"n_wallets": int(len(w)), "top1_wallet_pnl_share": float(w.iloc[:1].sum() / tot),
                     "top3_wallet_pnl_share": float(w.iloc[:3].sum() / tot),
                     "top5_wallet_pnl_share": float(w.iloc[:5].sum() / tot),
                     "top1_wallet_share_of_shares": float(ws.iloc[:1].sum() / ws.sum()),
                     "top3_wallet_share_of_shares": float(ws.iloc[:3].sum() / ws.sum()),
                     "n_wallets_negative_pnl": int((w < 0).sum()),
                     "top10_match_pnl_share": float(mt.iloc[:10].sum() / tot),
                     "top50_match_pnl_share": float(mt.iloc[:50].sum() / tot),
                     "top5_day_pnl_share": float(dy.iloc[:5].sum() / tot),
                     "matches": int(len(mt)), "days": int(len(dy))}
    dw = [k for k in results if k.endswith("|drop_top_wallets")][0]
    conc["leave_top1_wallet_out"] = {k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                                     for k, v in summ(results[dw], "drop_top1_wallet").items()}
    conc["top_wallet_dropped"] = kw_drop[REC][0][:10] + "..."
    for key in ("__top1_1s5", "__top3_1s5"):
        lab = [k for k in results if k.endswith("|" + key)][0]
        sm = summ(results[lab], key)
        conc["leave_out" + key] = {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in sm.items()}
    print("leave-out 1s/5% top wallets:", {k: round(conc["leave_out" + k]["1s5_per_share_c"], 3) for k in ("__top1_1s5", "__top3_1s5")},
          {k: (round(conc["leave_out" + k]["1s5_ci_lo_c"], 3), round(conc["leave_out" + k]["1s5_ci_hi_c"], 3),
               round(conc["leave_out" + k]["1s5_sharpe"], 2)) for k in ("__top1_1s5", "__top3_1s5")})
    # per-wallet edge in 1s/5%
    pw = r5.groupby("wallet").agg(n=("pnl", "size"), shares=("shares", "sum"), pnl=("pnl", "sum"))
    pw["per_share_c"] = pw.pnl / pw.shares * 100
    pw = pw.sort_values("shares", ascending=False)
    pw.index = [i[:10] + "..." for i in pw.index]
    pw.round(3).to_csv(OUT / "verify_wallets_1s5.csv")
    print(json.dumps(conc, indent=1, default=float))
    print(pw.head(15).round(3).to_string())
    summary["concentration"] = conc

    # ---------------------------------------------------------------- 5 plateau
    rows = [summ(results[REC], "G_50pct_net100 (recommended)")]
    for k, v in results.items():
        if k.startswith(REC + "|"):
            if "min5" in k or "drop" in k:
                continue
            rows.append(summ(v, k.split("name=")[-1]))
    pol_csv = pd.read_csv(OUT / "policies.csv")
    pl = pd.DataFrame(rows)
    cols = ["label", "all_per_share_c", "all_sharpe", "pnl_usd", "1s5_per_share_c", "1s5_ci_lo_c", "1s5_ci_hi_c",
            "1s5_sharpe", "aug_per_share_c", "1s5_pnl_usd"]
    pl = pl[cols].sort_values("label")
    pl.round(3).to_csv(OUT / "verify_plateau.csv", index=False)
    print(pl.round(3).to_string(index=False))
    summary["plateau"] = pl.round(4).to_dict("records")

    # ---------------------------------------------------------------- 6 trend
    wk = r5.assign(week=pd.to_datetime(r5.ts, unit="s", utc=True).dt.to_period("W").astype(str)) \
        .groupby("week").agg(n=("pnl", "size"), pnl=("pnl", "sum"), shares=("shares", "sum"))
    wk["per_share_c"] = wk.pnl / wk.shares * 100
    m30w = r5.assign(week=pd.to_datetime(r5.ts, unit="s", utc=True).dt.to_period("W").astype(str),
                     m30=r5.shares * (r5.gross30.fillna(0) - r5.rate * r5.q * (1 - r5.q)))
    wk["m30_per_share_c"] = m30w.groupby("week").m30.sum() / wk.shares * 100
    mon = re_.groupby("month").agg(pnl=("pnl", "sum"), shares=("shares", "sum"))
    mon["per_share_c"] = mon.pnl / mon.shares * 100
    mon["m30_c"] = (re_.shares * (re_.gross30.fillna(0) - re_.rate * re_.q * (1 - re_.q))).groupby(re_.month).sum() \
        / mon.shares * 100
    x = np.arange(len(mon))
    b_res = np.polyfit(x, mon.per_share_c.to_numpy(), 1)
    b_m30 = np.polyfit(x, mon.m30_c.to_numpy(), 1)
    # extrapolate to Sep and Oct (x = 7, 8) - purely IS trend, no OOS data used
    trend = {"monthly": mon.round(3).reset_index().to_dict("records"), "weekly_1s5": wk.round(3).reset_index().to_dict("records"),
             "res_slope_c_per_month": float(b_res[0]), "res_fit_oct_c": float(np.polyval(b_res, 8)),
             "m30_slope_c_per_month": float(b_m30[0]), "m30_fit_oct_c": float(np.polyval(b_m30, 8))}
    print(mon.round(3).to_string()); print(wk.round(3).to_string()); print({k: v for k, v in trend.items() if "slope" in k or "fit" in k})
    summary["trend"] = trend

    # ---------------------------------------------------------------- 7 statistics
    d5 = E.daily_series(r5)
    dall = E.daily_series(re_)
    sr5 = d5.mean() / d5.std()
    srall = dall.mean() / dall.std()
    stats = {"days_1s5": len(d5), "sharpe_1s5": float(sr5 * np.sqrt(365)),
             "sharpe_1s5_block_boot_95": block_boot_sharpe(d5).tolist(),
             "sharpe_all_block_boot_95": block_boot_sharpe(dall).tolist(),
             "per_share_1s5_day_cluster_ci": day_cluster_ci(r5).tolist(),
             "per_share_all_day_cluster_ci": day_cluster_ci(re_).tolist(),
             "zero_days_1s5": int((d5 == 0).sum())}
    # DSR with N = 115 (111 claimed + 4-point net-cap probe that RESULTS.md mentions but does not count)
    ds = pd.read_csv(OUT / "deflated_sharpe.csv")
    ds = ds[(ds.measure == "res") & (ds.fee_mode == "actual")]
    v = float(np.var(ds.sr_daily, ddof=1))
    for N in (52, 115, 234):
        p, sr0 = dsr(srall, v, N, len(dall), float(dall.skew()), float(dall.kurt() + 3))
        stats[f"dsr_all_N{N}"] = p; stats[f"sr0_all_N{N}"] = sr0
    # 1s/5% sub-period DSR using the regime-level Sharpes of the clean menu (active days) as trials
    rg = pd.read_csv(OUT / "regime.csv")
    rg = rg[(rg.measure == "res") & (rg.fee_mode == "actual") & (rg.regime == "1s/5%") & (~rg.policy.str.contains(r"\*"))]
    v5 = float(np.var(rg.sharpe_ann_active_days / np.sqrt(365), ddof=1))
    for N in (52, 115, 234):
        p, sr0 = dsr(sr5, v5, N, len(d5), float(d5.skew()), float(d5.kurt() + 3))
        stats[f"dsr_1s5_N{N}"] = p; stats[f"sr0_1s5_N{N}"] = sr0
    # Bonferroni haircut of the 1s/5% t-stat (daily mean), Harvey-Liu style
    t5 = sr5 * np.sqrt(len(d5))
    p1 = 1 - norm.cdf(t5)
    for N in (52, 115, 234):
        padj = min(1.0, p1 * N)
        t_adj = norm.ppf(1 - padj) if padj < 1 else 0.0
        stats[f"haircut_sharpe_1s5_N{N}"] = float(max(t_adj, 0) / np.sqrt(len(d5)) * np.sqrt(365))
    stats["t_1s5"] = float(t5)
    print(json.dumps(stats, indent=1, default=float))
    summary["statistics"] = stats

    # ---------------------------------------------------------------- 8 cost stress
    gross = (r5.shares * r5.gross_res).sum()
    gross30 = (r5.shares * r5.gross30.fillna(0)).sum()
    qq = (r5.shares * r5.q * (1 - r5.q)).sum()
    cost = {"gross_res_per_share_c": float(gross / r5.shares.sum() * 100),
            "gross_m30_per_share_c": float(gross30 / r5.shares.sum() * 100),
            "fee_per_share_c_at_5pct": float(0.05 * qq / r5.shares.sum() * 100),
            "break_even_fee_rate_res": float(gross / qq), "break_even_fee_rate_m30": float(gross30 / qq)}
    for slip in (0.25, 0.5, 1.0):
        cost[f"res_per_share_c_slip{slip}c"] = float((r5.pnl.sum() - r5.shares.sum() * slip / 100) / r5.shares.sum() * 100)
        cost[f"m30_per_share_c_slip{slip}c"] = float(
            ((r5.shares * (r5.gross30.fillna(0) - r5.rate * r5.q * (1 - r5.q))).sum() - r5.shares.sum() * slip / 100)
            / r5.shares.sum() * 100)
    # share of 1s/5% shares and P&L in the tails of q (thinner books)
    tail = (r5.q < 0.2) | (r5.q > 0.8)
    cost["share_of_shares_q_tails"] = float(r5[tail].shares.sum() / r5.shares.sum())
    cost["share_of_pnl_q_tails"] = float(r5[tail].pnl.sum() / r5.pnl.sum())
    cost["per_usd_return_1s5_pct"] = float(r5.pnl.sum() / r5.usd_in.sum() * 100)
    print(json.dumps(cost, indent=1))
    summary["cost"] = cost

    # ---------------------------------------------------------------- 9 intra-second fill dispersion
    # Within the fast-tier print's own second: token price of the OTHER same-side prints vs theirs.
    # Positive = they got a better price than the rest of the same-side flow in that second, so a second
    # taker arriving with them (not displacing them) would pay more.
    t = pq.read_table(ROOT / "data/is_prints.parquet", columns=["cond", "ts", "p", "dir", "usd", "wallet"],
                      read_dictionary=["cond", "wallet"])
    pr = t.to_pandas(); del t
    pr = pr[pr.cond.isin(set(r5.cond.unique()))].copy()
    assert pr.ts.max() < OOS_START + 8 * 3600
    pr["cond"] = pr.cond.astype(str); pr["wallet"] = pr.wallet.astype(str)
    pr["q"] = np.where(pr.dir > 0, pr.p, 1 - pr.p)
    pr["sh"] = pr.usd / pr.q
    key = ["cond", "ts", "dir"]
    pr["qsh"] = pr.q * pr.sh
    agg = pr.groupby(key).agg(n_same=("q", "size"), sh_sum=("sh", "sum"), qsh_sum=("qsh", "sum"),
                              qmin=("q", "min"), qmax=("q", "max")).reset_index()
    x = r5.merge(agg, on=key, how="left")
    their_sh = x.their_shares
    others_sh = x.sh_sum - their_sh
    others_q = np.where(others_sh > 1e-6, (x.qsh_sum - x.q * their_sh) / np.where(others_sh > 1e-6, others_sh, 1), np.nan)
    x["others_minus_theirs_c"] = (others_q - x.q) * 100
    x["is_best"] = x.q <= x.qmin + 1e-9
    has = np.isfinite(x.others_minus_theirs_c)
    intra = {"share_with_other_same_side_prints_same_second": float(has.mean()),
             "mean_others_minus_theirs_c_shareweighted": float(np.average(x.others_minus_theirs_c[has], weights=x.shares[has])),
             "median_others_minus_theirs_c": float(np.median(x.others_minus_theirs_c[has])),
             "share_their_price_is_best_in_second": float(x.is_best.mean()),
             "mean_range_in_second_c": float(((x.qmax - x.qmin) * 100).mean())}
    # P&L of the 1 s/5% book if every trade were filled at the same-second same-side VWAP instead of their price
    vw = x.qsh_sum / x.sh_sum
    pnl_vw = x.shares * (x.pnl_ps - (vw - x.q))  # dir*(res-p) - fee: paying (vw-q) more per share; fee change ignored
    intra["per_share_c_if_filled_at_second_vwap"] = float(pnl_vw.sum() / x.shares.sum() * 100)
    print("intra-second:", json.dumps(intra, indent=1))
    summary["intra_second"] = intra

    # ---------------------------------------------------------------- 10 where in the window the net cap trades
    feat = pd.read_parquet(ROOT / "data/v2_sizing/features.parquet", columns=["cond", "ts", "wallet", "dir", "p", "since", "n_prior3", "clip_k"])
    win = {}
    for nm in (REC, "A0_base_usd1k_match3k"):
        t5 = results[nm]
        t5 = t5[(t5.regime == "1s/5%") & (t5.month >= E.EVAL_START)].merge(
            feat.drop_duplicates(["cond", "ts", "wallet", "dir", "p"]), on=["cond", "ts", "wallet", "dir", "p"], how="left")
        first = (t5.n_prior3 == 0) & (t5.clip_k == 0)
        win[nm] = {"share_of_shares_first_clip": float(t5.shares[first].sum() / t5.shares.sum()),
                   "share_of_shares_since_lt1s": float(t5.shares[t5.since < 1].sum() / t5.shares.sum()),
                   "per_share_c_first_clip": float(t5.pnl[first].sum() / t5.shares[first].sum() * 100),
                   "per_share_c_not_first": float(t5.pnl[~first].sum() / t5.shares[~first].sum() * 100),
                   "m30_c_first_clip": float((t5.shares * (t5.gross30.fillna(0) - t5.rate * t5.q * (1 - t5.q)))[first].sum()
                                             / t5.shares[first].sum() * 100),
                   "m30_c_not_first": float((t5.shares * (t5.gross30.fillna(0) - t5.rate * t5.q * (1 - t5.q)))[~first].sum()
                                            / t5.shares[~first].sum() * 100)}
    print("window position (1s/5%):", json.dumps(win, indent=1))
    summary["window_position_1s5"] = win

    (OUT / "verify_summary.json").write_text(json.dumps(summary, indent=1, default=float))


def _init_with_drop(drop):
    kw_drop.update(drop)
    _init()


if __name__ == "__main__":
    main()
