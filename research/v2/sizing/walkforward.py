"""Run every sizing / filter / cap / stop variant walk-forward and write the tables.

    python research/v2/sizing/walkforward.py      # ~5 min on 2 processes
      -> research/v2/sizing/out/{policies,monthly,regime,meta}.csv, out/fig_*.png, results.json

Every policy is scored under 2 P&L measures (res = hold to resolution, m30 = exit at the 30 s mid)
x 2 fee modes (actual = each match's own fee; 5pct = every match re-priced at today's 5% schedule).
Evaluation months: 2026-02 .. 2026-08 (IS only; Aug stops at the OOS boundary 2026-08-25 14:15 UTC).
The 'meta' rows pick, each month, the policy with the best Sharpe over earlier evaluation months
(walk-forward selection across ALL variants), so the variant search itself is evaluated honestly.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine as E  # noqa: E402

OUT = HERE / "out"
P = E.Policy
INF = np.inf

POLICIES = [
    # A: baseline and sizing SHAPE (A1-A7 at 50% of baseline deployment, so shapes are comparable)
    P("A0_base_usd1k_match3k", family="A"),
    P("A1_usd_half", deploy_frac=.5, family="A"),
    P("A2_share_mirror", sizing="share_mirror", deploy_frac=.5, family="A"),
    P("A3_risk_parity", sizing="risk_parity", deploy_frac=.5, family="A"),
    P("A4_kelly_mo30", sizing="kelly", deploy_frac=.5, family="A"),
    P("A5_kelly_mores", sizing="kelly", edge_src="mo_res", deploy_frac=.5, family="A"),
    P("A6_kelly_mo30_var30", sizing="kelly", var_src="m30", deploy_frac=.5, family="A"),
    P("A7_kelly_mo30_wallet", sizing="kelly", wallet="kelly", deploy_frac=.5, family="A"),
    # B: decision-time filters on the baseline (* = window-contaminated feature, see allbucket_check)
    P("B1_zone_wf", zone="wf", family="B"),
    P("B2_zone_05_95", zone="0.05-0.95", family="B"),
    P("B3_zone_10_90", zone="0.10-0.90", family="B"),
    P("B4_wallet_filter", wallet="filter", family="B"),
    P("B5_min_ticket_5usd", filt=("min5",), family="B"),
    P("B6_first_clip_only*", filt=("first_only",), family="B*"),
    P("B7_no_fade*", filt=("no_fade",), family="B*"),
    P("B8_fill_move_wf*", filt=("fill_wf",), family="B*"),
    # C: concentration caps on the baseline
    P("C1_match1k", match_cap=1_000, family="C"),
    P("C2_match10k", match_cap=10_000, family="C"),
    P("C3_match_none", match_cap=INF, family="C"),
    P("C4_net2000_match10k", match_cap=10_000, net_cap=2_000, family="C"),
    P("C5_net5000_match10k", match_cap=10_000, net_cap=5_000, family="C"),
    P("C6_net2000_match3k", net_cap=2_000, family="C"),
    P("C7_wallet_day5k", wallet_day_cap=5_000, family="C"),
    P("C8_wallet_day15k", wallet_day_cap=15_000, family="C"),
    P("C9_day50k", day_cap=50_000, family="C"),
    P("C10_day100k", day_cap=100_000, family="C"),
    # D: scale (per-trade cap X, per-match cap 3X) -> capacity curve
    P("D1_trade100_match300", usd_cap=100, match_cap=300, family="D"),
    P("D2_trade250_match750", usd_cap=250, match_cap=750, family="D"),
    P("D3_trade500_match1500", usd_cap=500, match_cap=1_500, family="D"),
    P("D4_trade2500_match7500", usd_cap=2_500, match_cap=7_500, family="D"),
    P("D5_trade5000_match15k", usd_cap=5_000, match_cap=15_000, family="D"),
    # E: daily stop rules (sigma of daily P&L from earlier months only)
    P("E1_stop2sigma", stop_k=2, family="E"),
    P("E2_stop3sigma", stop_k=3, family="E"),
    P("E3_rp_stop2sigma", sizing="risk_parity", deploy_frac=.5, stop_k=2, family="E"),
    # F: combinations and shape-at-scale
    P("F1_rp_zonewf_wallet", sizing="risk_parity", deploy_frac=.5, zone="wf", wallet="filter", family="F"),
    P("F2_rp_wallet_net2000", sizing="risk_parity", deploy_frac=.5, wallet="filter", net_cap=2_000, family="F"),
    P("F3_kelw_zonewf_net2000", sizing="kelly", wallet="kelly", deploy_frac=.5, zone="wf", net_cap=2_000, family="F"),
    P("F4_rp_25pct", sizing="risk_parity", deploy_frac=.25, family="F"),
    P("F5_rp_75pct", sizing="risk_parity", deploy_frac=.75, family="F"),
    P("F6_usd_25pct", deploy_frac=.25, family="F"),
    P("F7_usd_75pct", deploy_frac=.75, family="F"),
    P("F8_rp_zone05_wallet_net2000", sizing="risk_parity", deploy_frac=.5, zone="0.05-0.95", wallet="filter",
      net_cap=2_000, family="F"),
    # added after the first full run (counted): stop and scale checks on F8
    P("F9_F8_stop2sigma", sizing="risk_parity", deploy_frac=.5, zone="0.05-0.95", wallet="filter",
      net_cap=2_000, stop_k=2, family="F"),
    P("F10_F8_25pct", sizing="risk_parity", deploy_frac=.25, zone="0.05-0.95", wallet="filter",
      net_cap=2_000, family="F"),
    P("F11_F8_75pct", sizing="risk_parity", deploy_frac=.75, zone="0.05-0.95", wallet="filter",
      net_cap=2_000, family="F"),
    P("F12_F8_100pct", sizing="risk_parity", deploy_frac=1.0, zone="0.05-0.95", wallet="filter",
      net_cap=2_000, family="F"),
    # added after the second run (counted): tighter per-match net-exposure caps x scale (G grid)
    *[P(f"G_{int(fr*100)}pct_net{nc}", sizing="risk_parity", deploy_frac=fr, zone="0.05-0.95", wallet="filter",
        net_cap=nc, family="G") for fr in (0.25, 0.5, 1.0) for nc in (500, 250, 100)],
]
RECOMMENDED = "G_50pct_net100"   # = what the clean walk-forward meta-selector holds from 2026-03 on (res, actual fee)
M30X_FOR = ("A0_base_usd1k_match3k", "F8_rp_zone05_wallet_net2000", "F10_F8_25pct", "G_25pct_net100",
            "G_50pct_net100", "G_50pct_net250", "G_100pct_net250")
MEASURES = ("res", "m30")
FEE_MODES = ("actual", "5pct")
INNER_GRID = {"zone_wf": len(E.ZONE_GRID), "fill_wf": len(E.FILL_GRID)}

_F = _W = None


def _init():
    global _F, _W
    _F, _W = E.load(), E.load_wallet_hist()


def run_one(args):
    pol, measure, fee_mode = args
    sig = None
    if np.isfinite(pol.stop_k):
        base = E.simulate(_F, replace(pol, stop_k=INF), measure, fee_mode, _W)
        sig = E.sigma_from_history(base)
    tr = E.simulate(_F, pol, measure, fee_mode, _W, sig)
    m = E.metrics(tr)
    mon = tr.groupby("month").agg(n=("pnl", "size"), pnl_usd=("pnl", "sum"), shares=("shares", "sum"),
                                  usd=("usd_in", "sum")).reset_index()
    mon["per_share_c"] = mon.pnl_usd / mon.shares * 100
    reg = E.by_group(tr, "regime")
    daily = E.daily_series(tr)                       # from RUN_START (Jan = warm-up, used only for scaling)
    usd_daily = tr.groupby("date").usd_in.sum().reindex(daily.index, fill_value=0.0)
    return pol.name, measure, fee_mode, m, mon, reg, (daily, usd_daily)


def _ret(daily: pd.Series, usd: pd.Series | None = None) -> pd.Series:
    """Vol-normalised daily P&L: month-m days divided by the std of the policy's daily P&L on all
    earlier days (from RUN_START = Jan 2026, itself walk-forward). Makes policies of different scale
    comparable and gives every month roughly unit risk."""
    mon = np.asarray(daily.index.tz_localize(None).to_period("M").astype(str))
    out = pd.Series(np.nan, index=daily.index)
    for m in sorted(set(mon)):
        prev = daily[mon < m]
        if len(prev) >= 10 and prev.std() > 0:
            out[mon == m] = daily[mon == m] / prev.std()
    return out


def meta_select(series: dict[str, tuple[pd.Series, pd.Series]]) -> tuple[pd.DataFrame, pd.Series]:
    """Each evaluation month, pick the policy with the best Sharpe of its vol-normalised daily P&L on
    all earlier days (Jan 2026 warm-up included; every day of it is itself walk-forward)."""
    rets = {n: _ret(d) for n, (d, u) in series.items()}
    any_s = next(iter(rets.values()))
    months = sorted(m for m in set(np.asarray(any_s.index.tz_localize(None).to_period("M").astype(str)))
                    if m >= E.EVAL_START)
    picks, parts = [], []
    for m in months:
        best, arg = -np.inf, "A0_base_usd1k_match3k"
        for name, (d, _) in series.items():
            mon = np.asarray(d.index.tz_localize(None).to_period("M").astype(str))
            prev = d[mon < m]
            if len(prev) >= 20 and prev.std() > 0 and prev.mean() / prev.std() > best:
                best, arg = prev.mean() / prev.std(), name
        r = rets[arg]
        mon = np.asarray(r.index.tz_localize(None).to_period("M").astype(str))
        parts.append(r[mon == m])
        picks.append({"month": m, "picked": arg, "ret_sum": float(r[mon == m].sum()),
                      "pnl_usd": float(series[arg][0][mon == m].sum())})
    return pd.DataFrame(picks), pd.concat(parts)


def deflated_sharpe(sr_daily: float, sr_trials: np.ndarray, T: int, skew: float, kurt: float) -> float:
    """Bailey & Lopez de Prado deflated Sharpe ratio (probability the true SR > the max-of-N null)."""
    from scipy.stats import norm
    N = len(sr_trials)
    v = np.var(sr_trials, ddof=1)
    g = 0.5772156649
    sr0 = np.sqrt(v) * ((1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * np.e)))
    den = np.sqrt(max(1 - skew * sr_daily + (kurt - 1) / 4 * sr_daily ** 2, 1e-12))
    return float(norm.cdf((sr_daily - sr0) * np.sqrt(T - 1) / den)), float(sr0)


def main(workers: int = 2):
    OUT.mkdir(exist_ok=True)
    jobs = [(p, me, fm) for p in POLICIES for me in MEASURES for fm in FEE_MODES]
    jobs += [(p, "m30x", fm) for p in POLICIES if p.name in M30X_FOR for fm in FEE_MODES]
    with ProcessPoolExecutor(workers, initializer=_init) as ex:
        res = list(ex.map(run_one, jobs, chunksize=2))
    rows, mons, regs, dailies = [], [], [], {}
    fam = {p.name: p.family for p in POLICIES}
    for name, me, fm, m, mon, reg, daily in res:
        rows.append({"policy": name, "family": fam[name], "measure": me, "fee_mode": fm,
                     **{k: (json.dumps(v) if isinstance(v, list) else v) for k, v in m.items()}})
        mons.append(mon.assign(policy=name, measure=me, fee_mode=fm))
        regs.append(reg.assign(policy=name, measure=me, fee_mode=fm))
        dailies[(name, me, fm)] = daily
    pol_df = pd.DataFrame(rows)
    pol_df.to_csv(OUT / "policies.csv", index=False)
    pd.concat(mons).to_csv(OUT / "monthly.csv", index=False)
    pd.concat(regs).to_csv(OUT / "regime.csv", index=False)
    pd.DataFrame([{"policy": p.name, **{k: (str(v) if not isinstance(v, (int, float, str)) else v)
                                         for k, v in asdict(p).items() if k != "name"}} for p in POLICIES]
                 ).to_csv(OUT / "policy_definitions.csv", index=False)
    meta_rows, dsr_rows = [], []
    eligible = [p.name for p in POLICIES if p.family != "B*"]       # contaminated filters excluded
    for me in MEASURES:
        for fm in FEE_MODES:
            for label, names in (("clean", eligible), ("all_incl_contaminated", [p.name for p in POLICIES])):
                picks, series = meta_select({n: dailies[(n, me, fm)] for n in names})
                sd = series.std()
                base_r = _ret(*dailies[("A0_base_usd1k_match3k", me, fm)])
                base_r = base_r[np.asarray(base_r.index.tz_localize(None).to_period("M").astype(str)) >= E.EVAL_START]
                meta_rows.append({"measure": me, "fee_mode": fm, "menu": label, "n_menu": len(names),
                                  "sharpe_ann_ret_units": float(series.mean() / sd * np.sqrt(365)) if sd > 0 else np.nan,
                                  "baseline_sharpe_ann_ret_units": float(base_r.mean() / base_r.std() * np.sqrt(365)),
                                  "pnl_usd_of_picks": float(picks.pnl_usd.sum()),
                                  "months_positive": int((picks.pnl_usd > 0).sum()), "months_total": len(picks),
                                  "picks": "; ".join(f"{r.month}:{r.picked}" for r in picks.itertuples())})
            # deflated Sharpe of every clean policy vs the clean menu (daily SR, eval days only)
            srs, stats_ = {}, {}
            for n in eligible:
                d = dailies[(n, me, fm)][0]
                d = d[np.asarray(d.index.tz_localize(None).to_period("M").astype(str)) >= E.EVAL_START]
                srs[n] = d.mean() / d.std()
                stats_[n] = (len(d), float(d.skew()), float(d.kurt() + 3))
            arr = np.array(list(srs.values()))
            for n in eligible:
                T, sk, ku = stats_[n]
                dsr, sr0 = deflated_sharpe(srs[n], arr, T, sk, ku)
                dsr_rows.append({"policy": n, "measure": me, "fee_mode": fm, "sr_daily": srs[n],
                                 "sr0_daily_null_max": sr0, "deflated_sharpe_prob": dsr, "n_trials": len(arr)})
    pd.DataFrame(meta_rows).to_csv(OUT / "meta.csv", index=False)
    pd.DataFrame(dsr_rows).to_csv(OUT / "deflated_sharpe.csv", index=False)
    n_pol = len(POLICIES)
    n_configs = n_pol + INNER_GRID["zone_wf"] * sum(p.zone == "wf" for p in POLICIES) \
        + INNER_GRID["fill_wf"] * sum("fill_wf" in p.filt for p in POLICIES)
    (OUT / "variant_count.json").write_text(json.dumps({
        "policies": n_pol, "policy_x_measure_x_feemode_runs": len(jobs),
        "configs_including_inner_walkforward_grids": int(n_configs),
        "inner_grids": INNER_GRID}, indent=2))
    print(pol_df[["policy", "measure", "fee_mode", "per_share_c", "total_pnl_usd", "sharpe_ann", "max_dd_pct",
                  "worst_day_usd", "months_positive"]].round(2).to_string(index=False))
    print(pd.DataFrame(meta_rows).drop(columns="picks").round(2).to_string(index=False))
    dd = pd.DataFrame(dsr_rows)
    print(dd[dd.policy.isin(["A0_base_usd1k_match3k", RECOMMENDED])].round(3).to_string(index=False))


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
