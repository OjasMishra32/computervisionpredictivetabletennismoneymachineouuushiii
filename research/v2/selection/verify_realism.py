"""Adversarial review of the selection lens: execution realism and statistics (IS only).

    .venv/bin/python research/v2/selection/verify_realism.py     (from the repo root; needs run.py outputs)

Reads only IS inputs (data/derived/*_is.parquet, data/is_prints.parquet, data/v2_selection/*) and the lens's own
out/ files. Never reads data/locked/, OOS prints, or live recordings. Writes out/verify_realism.json.

Checks
  C1  reproduce the 1 s / 5% headline; unweighted (per-print) vs share-weighted (per-share-traded) edge, dollars
  C2  minimum order (5 shares) and dust prints
  C3  paired nested-minus-baseline difference: match-cluster (as reported) vs WALLET-cluster and day-block bootstraps
  C4  concentration: wallets, matches, days; leave-top-k-wallets-out
  C5  hindsight in the 0-3 s bucket: same wallets, ALL their prints (no onset conditioning), nested vs baseline
  C6  second-mover realism: other wallets trading the same direction in the same jump, by lag
  C7  realisable 30 s exit (cross half the pre-trade spread + pay the fee again) vs hold to resolution
  C8  ticket size vs visible depth; share of fills at the $1k clip; per-jump demand
  C9  deflated Sharpe (Bailey & Lopez de Prado) with N = 341 trials; Bonferroni/Holm haircut on the daily t-stat
  C10 plateau vs spike; "all 288 beat baseline" claim
  C11 month split inside the 1 s / 5% regime
  C12 fee sensitivity: break-even fee rate; alternative fee formula rate * min(p, 1-p)
  C13 follower (copy after delay) P&L for the nested-selected trades
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy import stats as sps

from common import BASELINE, CACHE, HERE, OOS_START, ROOT, Engine, jsonable
from qualify_grid import GRID

OUT = HERE / "out"
N_TRIALS = 341
TOUCH_USD = 8_100      # live sample median depth at the touch (task brief), used only as a fixed constant
RNG = np.random.default_rng(12345)


def pct(a, q):
    return [float(np.percentile(a, q[0])), float(np.percentile(a, q[1]))]


def uw_sw(t: pd.DataFrame, col: str) -> tuple[float, float]:
    ok = t[col].notna()
    uw = float(t.loc[ok, col].mean() * 100)
    sw = float((t.shares[ok] * t.loc[ok, col]).sum() / t.shares[ok].sum() * 100)
    return uw, sw


def basic(t: pd.DataFrame) -> dict:
    n30u, n30s = uw_sw(t, "net30")
    nru, nrs = uw_sw(t, "net_res")
    g30u, g30s = uw_sw(t, "mo30")
    return {"n": int(len(t)), "wallets": int(t.wid.nunique()), "matches": int(t.cond.nunique()),
            "net30_uw_c": n30u, "net30_sw_c": n30s, "net_res_uw_c": nru, "net_res_sw_c": nrs,
            "gross30_uw_c": g30u, "gross30_sw_c": g30s,
            "fee_uw_c": float(t.fee.mean() * 100), "fee_sw_c": float((t.shares * t.fee).sum() / t.shares.sum() * 100),
            "pnl30_usd": float((t.shares * t.net30.fillna(0)).sum()), "pnl_res_usd": float((t.shares * t.net_res.fillna(0)).sum()),
            "usd_in": float(t.usd_in.sum()), "shares": float(t.shares.sum())}


# ---------------------------------------------------------------------------------------------- bootstraps
def _ratio_boot(groups_a, groups_b, n_boot, weight):
    """groups_*: DataFrame indexed by cluster with columns s (sum of x*w) and n (sum of w). Paired over the union."""
    j = groups_a.join(groups_b, lsuffix="_a", rsuffix="_b", how="outer").fillna(0.0)
    S = j[["s_a", "n_a", "s_b", "n_b"]].to_numpy()
    k = len(S)
    pt = S[:, 0].sum() / S[:, 1].sum() - S[:, 2].sum() / S[:, 3].sum()
    bs = np.empty(n_boot)
    for i in range(n_boot):
        x = S[RNG.integers(0, k, k)]
        bs[i] = x[:, 0].sum() / max(x[:, 1].sum(), 1e-12) - x[:, 2].sum() / max(x[:, 3].sum(), 1e-12)
    return float(pt * 100), pct(bs * 100, (2.5, 97.5)), k


def grp(t: pd.DataFrame, key: str, col: str, weighted: bool) -> pd.DataFrame:
    ok = t[col].notna()
    t = t[ok]
    w = t.shares if weighted else pd.Series(1.0, index=t.index)
    return pd.DataFrame({"s": (t[col] * w).groupby(t[key]).sum(), "n": w.groupby(t[key]).sum()})


def single_boot(t: pd.DataFrame, key: str, col: str, weighted: bool, n_boot=2000):
    g = grp(t, key, col, weighted)
    S, N = g.s.to_numpy(), g.n.to_numpy()
    k = len(g)
    bs = np.empty(n_boot)
    for i in range(n_boot):
        ix = RNG.integers(0, k, k)
        bs[i] = S[ix].sum() / N[ix].sum()
    return float(S.sum() / N.sum() * 100), pct(bs * 100, (2.5, 97.5)), k


def day_block_dollar_diff(a: pd.DataFrame, b: pd.DataFrame, col: str, days, block=5, n_boot=4000):
    da = (a.shares * a[col].fillna(0)).groupby(a.date).sum().reindex(days, fill_value=0.0).to_numpy()
    db = (b.shares * b[col].fillna(0)).groupby(b.date).sum().reindex(days, fill_value=0.0).to_numpy()
    d = da - db
    T = len(d)
    nb = int(np.ceil(T / block))
    bs = np.empty(n_boot)
    for i in range(n_boot):
        st = RNG.integers(0, T - block + 1, nb)
        idx = (st[:, None] + np.arange(block)).ravel()[:T]
        bs[i] = d[idx].sum()
    return float(d.sum()), pct(bs, (2.5, 97.5))


# ------------------------------------------------------------------------------------------- Sharpe stats
def psr(sr, T, skew, kurt, sr0=0.0):
    """Probabilistic Sharpe ratio (non-annualised daily SR)."""
    den = np.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    return float(sps.norm.cdf((sr - sr0) * np.sqrt(T - 1) / den))


def dsr_threshold(var_sr, n_trials):
    g = 0.5772156649
    return float(np.sqrt(var_sr) * ((1 - g) * sps.norm.ppf(1 - 1 / n_trials) + g * sps.norm.ppf(1 - 1 / (n_trials * np.e))))


def sharpe_block(daily: np.ndarray, var_sr_daily: float, label: str) -> dict:
    T = len(daily)
    sr = daily.mean() / daily.std(ddof=1)
    sk = float(sps.skew(daily))
    ku = float(sps.kurtosis(daily, fisher=False))
    sr0 = dsr_threshold(var_sr_daily, N_TRIALS)
    tstat = sr * np.sqrt(T)
    p1 = float(sps.t.sf(tstat, T - 1))
    se_ann = float(np.sqrt((1 - sk * sr + (ku - 1) / 4 * sr ** 2) / (T - 1)) * np.sqrt(365))
    return {"label": label, "T_days": T, "sr_ann": float(sr * np.sqrt(365)), "sr_ann_se": se_ann, "skew": sk,
            "kurtosis": ku, "psr_vs_0": psr(sr, T, sk, ku, 0.0), "sr0_ann_deflation_N341": float(sr0 * np.sqrt(365)),
            "dsr": psr(sr, T, sk, ku, sr0), "t_daily": float(tstat), "p_one_sided": p1,
            "p_bonferroni_N341": float(min(1.0, p1 * N_TRIALS)),
            "haircut_sr_ann_bonferroni": float(max(0.0, sps.t.isf(min(0.5, p1 * N_TRIALS), T - 1)) / np.sqrt(T) * np.sqrt(365))}


# ------------------------------------------------------------------------------------------------- main
def main():
    E = Engine()
    res = {"note": "IS only. uw = unweighted mean over prints (the lens's 'c/share'); sw = share-weighted "
                   "(dollar P&L / shares traded), the economically meaningful per-share edge."}
    rj = json.loads((HERE / "results.json").read_text())
    rule_of = {r.name: r for r in GRID}
    ch = {m: rule_of[rj["nested_choices_stage1"][str(m)]] for m in E.eval_months}
    nest = E.trades(lambda m: ch[m])
    base = E.trades(BASELINE)
    cached = pd.read_parquet(CACHE / "stage1_nested_pnl30_now_all_trades.parquet")
    assert len(cached) == len(nest) and np.isclose(cached.net30.mean(), nest.net30.mean())
    n5, b5 = nest[nest.regime == "1s/5%"], base[base.regime == "1s/5%"]
    days5 = pd.date_range(pd.Timestamp("2026-07-01", tz="UTC"), E.eval_days[-1], freq="D")

    # ---- C1 reproduce + weighting
    res["C1_reproduce_1s5"] = {"nested": basic(n5), "baseline": basic(b5),
                               "claimed": {"nested_net30_c": 1.17, "nested_net_res_c": 1.34,
                                           "baseline_net30_c": 0.62, "baseline_net_res_c": 0.54}}
    nb, bb = res["C1_reproduce_1s5"]["nested"], res["C1_reproduce_1s5"]["baseline"]
    res["C1_reproduce_1s5"]["diff_uw_net30_c"] = nb["net30_uw_c"] - bb["net30_uw_c"]
    res["C1_reproduce_1s5"]["diff_sw_net30_c"] = nb["net30_sw_c"] - bb["net30_sw_c"]
    res["C1_reproduce_1s5"]["diff_pnl30_usd"] = nb["pnl30_usd"] - bb["pnl30_usd"]
    res["C1_reproduce_1s5"]["diff_pnl_res_usd"] = nb["pnl_res_usd"] - bb["pnl_res_usd"]
    # by size band (share-weighted net30) to show why uw and sw differ
    sz = pd.cut(n5.usd, [0, 5, 50, 250, 1000, np.inf], right=False, labels=["<$5", "$5-50", "$50-250", "$250-1k", ">=$1k"])
    res["C1_size_bands_nested_1s5"] = n5.assign(band=sz).groupby("band", observed=True).apply(
        lambda t: pd.Series({"n": len(t), "share_of_trades": len(t) / len(n5), "share_of_shares": t.shares.sum() / n5.shares.sum(),
                             "net30_uw_c": t.net30.mean() * 100,
                             "net30_sw_c": (t.shares * t.net30).sum() / t.shares[t.net30.notna()].sum() * 100,
                             "net_res_sw_c": (t.shares * t.net_res).sum() / t.shares[t.net_res.notna()].sum() * 100}),
        include_groups=False)

    # ---- C2 minimum order
    def minord(t):
        small = t.shares < 5
        k = t[~small]
        return {"share_trades_lt5sh": float(small.mean()), "share_shares_lt5sh": float(t.shares[small].sum() / t.shares.sum()),
                "share_trades_usd_lt1": float((t.usd < 1).mean()),
                "net30_uw_c_drop_lt5": uw_sw(k, "net30")[0], "net30_sw_c_drop_lt5": uw_sw(k, "net30")[1],
                "net_res_uw_c_drop_lt5": uw_sw(k, "net_res")[0]}
    res["C2_min_order_1s5"] = {"nested": minord(n5), "baseline": minord(b5)}
    res["C2_min_order_1s5"]["diff_uw_net30_drop_lt5"] = (res["C2_min_order_1s5"]["nested"]["net30_uw_c_drop_lt5"]
                                                         - res["C2_min_order_1s5"]["baseline"]["net30_uw_c_drop_lt5"])

    # ---- C3 paired difference under different clusterings
    c3 = {}
    for col in ("net30", "net_res"):
        for wt in (False, True):
            tag = f"{col}_{'sw' if wt else 'uw'}"
            c3[f"{tag}_match_cluster"] = _ratio_boot(grp(n5, "cond", col, wt), grp(b5, "cond", col, wt), 2000, wt)
            c3[f"{tag}_wallet_cluster"] = _ratio_boot(grp(n5, "wid", col, wt), grp(b5, "wid", col, wt), 2000, wt)
    c3["pnl30_usd_diff_dayblock5"] = day_block_dollar_diff(n5, b5, "net30", days5)
    c3["pnl_res_usd_diff_dayblock5"] = day_block_dollar_diff(n5, b5, "net_res", days5)
    # levels with wallet clusters
    for col in ("net30", "net_res"):
        for wt in (False, True):
            c3[f"nested_level_{col}_{'sw' if wt else 'uw'}_wallet_cluster"] = single_boot(n5, "wid", col, wt)
            c3[f"baseline_level_{col}_{'sw' if wt else 'uw'}_wallet_cluster"] = single_boot(b5, "wid", col, wt)
    res["C3_paired_and_levels_1s5"] = c3

    # ---- C4 concentration
    def conc(t):
        p30 = (t.shares * t.net30.fillna(0)).groupby(t.wid).sum().sort_values(ascending=False)
        pr = (t.shares * t.net_res.fillna(0)).groupby(t.wid).sum().sort_values(ascending=False)
        ntr = t.groupby("wid").size().sort_values(ascending=False)
        sh = t.groupby("wid").shares.sum()
        hhi = float(((sh / sh.sum()) ** 2).sum())
        out = {"n_wallets": int(t.wid.nunique()), "eff_n_wallets_by_shares": 1 / hhi,
               "top1_share_trades": float(ntr.iloc[0] / len(t)), "top5_share_trades": float(ntr.iloc[:5].sum() / len(t)),
               "top1_share_pnl30": float(p30.iloc[0] / p30.sum()), "top5_share_pnl30": float(p30.iloc[:5].sum() / p30.sum()),
               "top10_share_pnl30": float(p30.iloc[:10].sum() / p30.sum()),
               "top5_share_pnl_res": float(pr.iloc[:5].sum() / pr.sum()),
               "wallets_negative_pnl30": int((p30 < 0).sum())}
        for k in (1, 3, 5, 10):
            drop = p30.index[:k]
            r = t[~t.wid.isin(drop)]
            out[f"drop_top{k}_by_pnl30_net30_uw_c"], out[f"drop_top{k}_by_pnl30_net30_sw_c"] = uw_sw(r, "net30")
            out[f"drop_top{k}_by_pnl30_net_res_sw_c"] = uw_sw(r, "net_res")[1]
            out[f"drop_top{k}_by_pnl30_pnl30_usd"] = float((r.shares * r.net30.fillna(0)).sum())
        mp = (t.shares * t.net_res.fillna(0)).groupby(t.cond).sum().sort_values(ascending=False)
        dp = (t.shares * t.net_res.fillna(0)).groupby(t.date).sum().sort_values(ascending=False)
        out["top10_matches_share_pnl_res"] = float(mp.iloc[:10].sum() / mp.sum())
        out["top5_days_share_pnl_res"] = float(dp.iloc[:5].sum() / dp.sum())
        out["pnl_res_without_top10_matches_usd"] = float(mp.iloc[10:].sum())
        out["pnl_res_without_top5_days_usd"] = float(dp.iloc[5:].sum())
        return out
    res["C4_concentration_1s5"] = {"nested": conc(n5), "baseline": conc(b5)}
    # the difference set: wallets only in baseline / only in nested
    wn, wb = set(n5.wid), set(b5.wid)
    only_b = b5[~b5.wid.isin(wn)]
    only_n = n5[~n5.wid.isin(wb)]
    res["C4_difference_sets_1s5"] = {
        "wallets_only_baseline": len(wb - wn), "wallets_only_nested": len(wn - wb), "wallets_both": len(wn & wb),
        "only_baseline": basic(only_b) if len(only_b) else None, "only_nested": basic(only_n) if len(only_n) else None}
    ob = only_b.groupby("wid").size().sort_values(ascending=False)
    res["C4_difference_sets_1s5"]["only_baseline_top1_share_trades"] = float(ob.iloc[0] / ob.sum()) if len(ob) else None
    res["C4_difference_sets_1s5"]["only_baseline_top3_share_trades"] = float(ob.iloc[:3].sum() / ob.sum()) if len(ob) else None

    # ---- C5 hindsight: same wallets, all buckets
    wallet_of = E.d.drop_duplicates("wid").set_index("wid").wallet
    sel_n = {m: set(wallet_of.loc[E.selected(ch[m], m)]) for m in E.eval_months}
    sel_b = {m: set(wallet_of.loc[E.selected(BASELINE, m)]) for m in E.eval_months}
    union = set().union(*sel_n.values(), *sel_b.values())
    cols = ["cond", "ts", "p", "dir", "usd", "wallet", "fee_rate", "delay", "mo30", "mo_res", "bucket", "with_jump"]
    pf = pq.ParquetFile(ROOT / "data/is_prints.parquet")
    parts = []
    for bt in pf.iter_batches(batch_size=500_000, columns=cols):
        x = bt.to_pandas()
        x = x[x.wallet.isin(union)]
        if len(x):
            parts.append(x)
    x = pd.concat(parts, ignore_index=True)
    st = E.u.set_index("cond").start
    assert (x.cond.map(st) < OOS_START).all()
    x["month"] = pd.to_datetime(x.ts, unit="s").dt.to_period("M")
    x["pq"] = x.p * (1 - x.p)
    x["fee"] = x.fee_rate * x.pq
    x["net30"], x["net_res"] = x.mo30 - x.fee, x.mo_res - x.fee
    x["px"] = np.where(x.dir > 0, x.p, 1 - x.p)
    x["shares"] = np.minimum(x.usd, 1000) / x.px
    x["is5"] = (x.delay < 3) & (x.fee_rate >= 0.04)
    inn = np.zeros(len(x), bool)
    inb = np.zeros(len(x), bool)
    for m in E.eval_months:
        mm = (x.month == m).to_numpy()
        inn |= mm & x.wallet.isin(sel_n[m]).to_numpy()
        inb |= mm & x.wallet.isin(sel_b[m]).to_numpy()
    c5 = {}
    for lab, mask in (("nested", inn), ("baseline", inb)):
        y = x[mask & x.is5.to_numpy()]
        y = y.assign(wid=y.wallet)
        c5[lab] = {"all_buckets": basic(y.assign(usd_in=np.minimum(y.usd, 1000))),
                   "excluding_0_3s": basic(y[y.bucket != "0-3s"].assign(usd_in=lambda z: np.minimum(z.usd, 1000))),
                   "only_0_3s": basic(y[y.bucket == "0-3s"].assign(usd_in=lambda z: np.minimum(z.usd, 1000))),
                   "share_prints_in_0_3s": float((y.bucket == "0-3s").mean())}
        z = y[y.bucket == "0-3s"]
        c5[lab]["0_3s_with_jump_share"] = float((z.with_jump > 0).mean())
        c5[lab]["0_3s_with_jump_net30_c"] = float(z[z.with_jump > 0].net30.mean() * 100)
        c5[lab]["0_3s_against_jump_net30_c"] = float(z[z.with_jump < 0].net30.mean() * 100)
    for k in ("all_buckets", "excluding_0_3s"):
        c5[f"diff_{k}_net30_uw_c"] = c5["nested"][k]["net30_uw_c"] - c5["baseline"][k]["net30_uw_c"]
        c5[f"diff_{k}_net30_sw_c"] = c5["nested"][k]["net30_sw_c"] - c5["baseline"][k]["net30_sw_c"]
    # wallet-cluster bootstrap of the all-bucket paired difference (uncapped, so per-print not per-match cap)
    yn = x[inn & x.is5.to_numpy()].assign(wid=lambda z: z.wallet)
    yb = x[inb & x.is5.to_numpy()].assign(wid=lambda z: z.wallet)
    c5["diff_all_buckets_net30_sw_wallet_cluster"] = _ratio_boot(grp(yn, "wid", "net30", True), grp(yb, "wid", "net30", True), 2000, True)
    c5["diff_all_buckets_net30_uw_wallet_cluster"] = _ratio_boot(grp(yn, "wid", "net30", False), grp(yb, "wid", "net30", False), 2000, False)
    c5["nested_level_all_buckets_net30_sw_wallet_cluster"] = single_boot(yn, "wid", "net30", True)
    c5["nested_level_excl_0_3s_net30_sw_wallet_cluster"] = single_boot(yn[yn.bucket != "0-3s"], "wid", "net30", True)
    res["C5_hindsight_all_buckets_1s5"] = c5
    del x, parts

    # ---- C6 second mover: everyone's 0-3 s prints in the same jump as a nested-selected print
    d = E.d[E.d.regime == "1s/5%"].copy()
    d["sel"] = False
    for m in E.eval_months:
        mm = d.month == m
        d.loc[mm, "sel"] = d.loc[mm, "wid"].isin(E.selected(ch[m], m)).to_numpy()
    d["jump"] = d.cond + ":" + (d.ts - d.since).astype(np.int64).astype(str)
    s = d[d.sel]
    first = s.sort_values("ts").groupby("jump").agg(t_first=("ts", "first"), dir_sel=("dir", lambda v: np.sign(v.sum())))
    dj = d.join(first, on="jump", how="inner")
    dj["lag"] = (dj.ts - dj.t_first).clip(lower=-3, upper=3).astype(int)
    dj["same_dir"] = dj.dir == dj.dir_sel
    g = dj.groupby(["sel", "same_dir", "lag"]).apply(
        lambda t: pd.Series({"n": len(t), "net30_uw_c": t.net30.mean() * 100,
                             "net30_sw_c": (t.shares * t.net30).sum() / t.shares[t.net30.notna()].sum() * 100,
                             "net_res_sw_c": (t.shares * t.net_res).sum() / t.shares[t.net_res.notna()].sum() * 100,
                             "mean_px": t.px.mean()}), include_groups=False)
    res["C6_second_mover_1s5"] = g.reset_index()
    # same-second competitors: price paid by non-selected vs selected same-direction prints in the same jump-second
    same = dj[(dj.lag == 0) & dj.same_dir]
    res["C6_same_second_summary"] = {
        "selected_net30_sw_c": uw_sw(same[same.sel], "net30")[1], "others_net30_sw_c": uw_sw(same[~same.sel], "net30")[1],
        "selected_n": int(same.sel.sum()), "others_n": int((~same.sel).sum())}

    # ---- C7 realisable 30 s exit vs hold
    def exit30(t):
        sp = t.pre_spread.fillna(0.01).clip(upper=0.10)
        p30 = (t.p + t.mo30 * t.dir).clip(0.001, 0.999)
        fee_exit = t.fee_rate * p30 * (1 - p30)
        r = t.net30 - sp / 2 - fee_exit
        tt = t.assign(r=r)
        return {"exit30_uw_c": float(r.mean() * 100), "exit30_sw_c": uw_sw(tt, "r")[1],
                "median_pre_spread_c": float(t.pre_spread.median() * 100), "mean_fee_exit_c": float(fee_exit.mean() * 100)}
    res["C7_exit_at_30s_1s5"] = {"nested": exit30(n5), "baseline": exit30(b5)}

    # ---- C8 size vs depth
    jn = n5.assign(jump=n5.cond + ":" + (n5.ts - n5.since).astype(np.int64).astype(str))
    per_jump = jn.groupby("jump").usd.sum()
    res["C8_size_depth_1s5"] = {
        "print_usd_median": float(n5.usd.median()), "print_usd_p90": float(n5.usd.quantile(0.9)),
        "share_prints_at_1k_clip": float((n5.usd >= 1000).mean()),
        "share_usd_in_from_clipped_prints": float(n5.usd_in[n5.usd >= 1000].sum() / n5.usd_in.sum()),
        "selected_usd_per_jump_median": float(per_jump.median()), "selected_usd_per_jump_p90": float(per_jump.quantile(0.9)),
        "share_jumps_selected_usd_gt_touch": float((per_jump > TOUCH_USD).mean()),
        "n_jumps": int(len(per_jump)),
        "turnover_usd_per_month": {str(k): float(v) for k, v in n5.groupby("month").usd_in.sum().items()}}

    # ---- C9 deflated Sharpe
    grid = pd.read_csv(OUT / "stage1_grid_summary.csv", index_col=0)
    var_sr_daily = float((grid.sharpe_1s5 / np.sqrt(365)).var())
    dn = (n5.shares * n5.net_res.fillna(0)).groupby(n5.date).sum().reindex(days5, fill_value=0.0).to_numpy()
    dn30 = (n5.shares * n5.net30.fillna(0)).groupby(n5.date).sum().reindex(days5, fill_value=0.0).to_numpy()
    dbb = (b5.shares * b5.net_res.fillna(0)).groupby(b5.date).sum().reindex(days5, fill_value=0.0).to_numpy()
    ddiff = dn - dbb
    var_all = float((grid.sharpe / np.sqrt(365)).var())
    dall = (nest.shares * nest.net_res.fillna(0)).groupby(nest.date).sum().reindex(E.eval_days, fill_value=0.0).to_numpy()
    res["C9_sharpe"] = {"var_sr_daily_across_288_variants_1s5": var_sr_daily,
                        "nested_1s5_res": sharpe_block(dn, var_sr_daily, "nested 1s/5% dollar P&L to resolution"),
                        "nested_1s5_mark30": sharpe_block(dn30, var_sr_daily, "nested 1s/5% dollar P&L at 30 s mark"),
                        "nested_minus_baseline_1s5_res": sharpe_block(ddiff, var_sr_daily, "daily P&L difference nested - baseline"),
                        "nested_all_res": sharpe_block(dall, var_all, "nested whole IS"),
                        "note": "Variants are highly correlated (same wallets), so the cross-variant SR variance is small "
                                "and N=341 overstates independent trials; DSR here is a stress test, not exact."}

    # ---- C10 plateau
    b_net = float(grid.loc[BASELINE.name, "net30_1s5_c"])
    fz = grid[(grid.score == "eb") & (np.isclose(grid.thr, 0.005))]
    res["C10_plateau"] = {
        "n_variants": int(len(grid)), "variants_beating_baseline_net30_1s5": int((grid.net30_1s5_c > b_net).sum()),
        "variants_beating_baseline_net_res_1s5": int((grid.net_res_1s5_c > grid.loc[BASELINE.name, "net_res_1s5_c"]).sum()),
        "variants_beating_baseline_pnl_res_1s5": int((grid.pnl_1s5 > grid.loc[BASELINE.name, "pnl_1s5"]).sum()),
        "variants_beating_baseline_pnl30_1s5": int((grid.pnl30_1s5 > grid.loc[BASELINE.name, "pnl30_1s5"]).sum()),
        "net30_1s5_quantiles": {str(q): float(grid.net30_1s5_c.quantile(q)) for q in (0, .1, .25, .5, .75, .9, 1)},
        "pnl30_1s5_quantiles": {str(q): float(grid.pnl30_1s5.quantile(q)) for q in (0, .1, .25, .5, .75, .9, 1)},
        "baseline_pnl30_1s5": float(grid.loc[BASELINE.name, "pnl30_1s5"]),
        "eb0.5c_family_net30_1s5": fz.net30_1s5_c.round(3).to_dict(),
        "eb0.5c_family_pnl30_1s5": fz.pnl30_1s5.round(0).to_dict()}

    # ---- C11 month split
    def mon(t):
        return {str(m): basic(g) for m, g in t.groupby("month")}
    res["C11_month_split_1s5"] = {"nested": mon(n5), "baseline": mon(b5)}

    # ---- C12 fee sensitivity
    def fee_sens(t):
        ok = t.mo30.notna()
        tt = t[ok]
        w = tt.shares
        g30 = (w * tt.mo30).sum() / w.sum()
        gpq = (w * tt.pq).sum() / w.sum()
        gmin = (w * np.minimum(tt.p, 1 - tt.p)).sum() / w.sum()
        return {"gross30_sw_c": float(g30 * 100), "breakeven_rate_pq": float(g30 / gpq),
                "net30_sw_c_alt_fee_min_p": float((g30 - 0.05 * gmin) * 100),
                "net30_uw_c_alt_fee_min_p": float((tt.mo30 - 0.05 * np.minimum(tt.p, 1 - tt.p)).mean() * 100)}
    res["C12_fee_sensitivity_1s5"] = {"nested": fee_sens(n5), "baseline": fee_sens(b5)}

    # ---- C13 follower
    raw = pd.read_parquet(ROOT / "data/derived/prints_0_3s_is.parquet", columns=["mo5", "mo30", "spread"])
    raw = raw.reset_index(drop=True)
    def follow(t):
        mo5 = raw.mo5.to_numpy()[t.index.to_numpy()]
        spd = raw.spread.to_numpy()[t.index.to_numpy()]
        fr = t.mo_res - mo5 - np.nan_to_num(spd, nan=0.01) / 2 - t.fee
        tt = t.assign(fr=fr)
        return {"follow_res_uw_c": float(np.nanmean(fr) * 100), "follow_res_sw_c": uw_sw(tt, "fr")[1],
                "follow_30_uw_c": float(np.nanmean(t.net30 - mo5 - np.nan_to_num(spd, nan=0.01) / 2) * 100)}
    assert np.allclose(raw.mo30.to_numpy()[n5.index.to_numpy()], n5.mo30.to_numpy(), equal_nan=True)
    res["C13_follower_1s5"] = {"nested": follow(n5), "baseline": follow(b5)}

    # ---- C14 single-wallet attribution of the 1 s / 5% improvement
    only_b_w = b5[~b5.wid.isin(set(n5.wid))].groupby("wid").size().sort_values(ascending=False)
    top_excl = only_b_w.index[0]
    b5_minus = b5[b5.wid != top_excl]
    res["C14_single_wallet_attribution_1s5"] = {
        "top_excluded_wallet_trades": int(only_b_w.iloc[0]), "top_excluded_share_of_baseline_trades": float(only_b_w.iloc[0] / len(b5)),
        "top_excluded_net30_uw_c": uw_sw(b5[b5.wid == top_excl], "net30")[0],
        "top_excluded_net30_sw_c": uw_sw(b5[b5.wid == top_excl], "net30")[1],
        "baseline_minus_that_wallet": basic(b5_minus),
        "remaining_gap_uw_net30_c": res["C1_reproduce_1s5"]["nested"]["net30_uw_c"] - uw_sw(b5_minus, "net30")[0],
        "remaining_gap_sw_net30_c": res["C1_reproduce_1s5"]["nested"]["net30_sw_c"] - uw_sw(b5_minus, "net30")[1],
        "note": "Approximate: the match cap interacts, but removing one wallet from the baseline closes most of the gap."}

    # ---- C15 August only (the only 1 s / 5% month where the nested choice was the recommended EB rule)
    na, ba = n5[n5.month == pd.Period("2026-08", "M")], b5[b5.month == pd.Period("2026-08", "M")]
    res["C15_august_only_paired"] = {
        "nested_choice_jul": rj["nested_choices_stage1"]["2026-07"], "nested_choice_aug": rj["nested_choices_stage1"]["2026-08"],
        "net30_sw_wallet_cluster": _ratio_boot(grp(na, "wid", "net30", True), grp(ba, "wid", "net30", True), 2000, True),
        "net30_uw_wallet_cluster": _ratio_boot(grp(na, "wid", "net30", False), grp(ba, "wid", "net30", False), 2000, False),
        "net_res_sw_wallet_cluster": _ratio_boot(grp(na, "wid", "net_res", True), grp(ba, "wid", "net_res", True), 2000, True),
        "net_res_uw_match_cluster": _ratio_boot(grp(na, "cond", "net_res", False), grp(ba, "cond", "net_res", False), 2000, False)}

    (OUT / "verify_realism.json").write_text(json.dumps(jsonable(res), indent=1))
    pd.set_option("display.width", 250)
    for k, v in res.items():
        print("==", k)
        if isinstance(v, pd.DataFrame):
            print(v.round(3).to_string())
        else:
            print(json.dumps(jsonable(v), indent=1)[:6000])


if __name__ == "__main__":
    sys.exit(main())
