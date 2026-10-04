"""Tier-0 COUNTERFACTUAL backtest.

    ASSUMED: licensed live feed + courtside camera, NOT purchased; parameters from our measurements.

    python scripts/tier0_backtest.py            # everything -> results/tier0/ (~70 min, 3 workers)
    python scripts/tier0_backtest.py --primary  # corrected headline + pre-registered primary, 20 seeds, print only
    python scripts/tier0_backtest.py --figures  # redraw figures from results/tier0/*.csv / results.json

Two models are run:
  * PRE-REGISTERED (T.PRIMARY, research/v2/tier0/PREREG.md), kept as the record. Its fill price credits every
    stale share with the whole realised jump, which the verifiers showed roughly doubles the per-share edge.
  * CORRECTED (T.CORRECTED, research/v2/tier0/DEVIATIONS.md V1-V8), the headline: same pre-registered
    parameters; fills priced from the measured live book on both sides; limit-order fills; t_reprice drawn
    once per tournament; measured stale-price correction; literal coverage; 20-seed means.
Because t_reprice - t_bounce is not measured, the headline is reported next to the opposite reading of the
timing data (R's spread = umpire-stamp noise) and as a curve over t_reprice - t_bounce.

Historical prices, results, fees and delays are real (public Polymarket tapes); the tier-0 trader's timing,
fills and call accuracy are modelled (src/tier0.py). No live ATP/WTA data was used.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import tier0 as T  # noqa: E402

GRID = {
    "cv": ["own120", "own120_pess", "hawkeye340"],
    "stamp_lag": [1.0, 2.0, 3.0, None],     # None -> the data-calibrated value
    "phi": [0.25, 0.5, 1.0],
    "coverage": [3, 10, 30],
    "p_event": [0.95, 0.99],
    "net_cap": [100.0, 1000.0],
}
READINGS = ["tournament", "stamp"]          # corrected grid: both readings of the timing data (V3)
SEED = 0
SEEDS_HEAD = 20                             # headline, readings, stresses (V7)
SEEDS_GRID = 10                             # every grid cell and the B curve (V7)
B_GRID = [0.6, 0.8, 1.0, 1.1, 1.2, 1.3, 1.35, 1.4, 1.5, 1.75, 2.0, 2.5]
_CTX: dict = {}
PERIODS = ("IS", "burned_OOS")


def context() -> dict:
    """Load every input once per process (jump tables, draws, live pools, CV tables, point mix)."""
    if _CTX:
        return _CTX
    from src.tape import universe
    Ji, Jo = T.jump_table("is"), T.jump_table("oos")
    u = universe()
    v = T.prestart_volume(sorted(u.cond))
    u["prestart_usd"] = u.cond.map(v).fillna(0.0)
    tour = T.tournament_codes(u)
    per = {}
    for name, J, s, tag in (("IS", Ji, SEED, "is"), ("burned_OOS", Jo, SEED + 1000, "oos")):
        J = J.reset_index(drop=True)
        J["row"] = np.arange(len(J))
        J["post30"] = T.post_prices(tag, J)
        J["tour"] = J.cond.map(tour).astype(int)
        # DEVIATIONS V6: coverage ranks the whole universe per UTC date (both periods), as PREREG says
        per[name] = {"J": J, "M": u.reset_index(drop=True), "seed": s}
    _CTX.update(per=per, pools={p: T.live_points(p) for p in ("D>=3c", "all")}, cvs=T.cv_systems(),
                mix=T.point_mix(), calib=T.calibrate_stamp_lag(), n_tour=int(tour.max()) + 1)
    return _CTX


def run_one(sc: T.Scenario, period: str, seed_offset: int = 0, keep: bool = False):
    c = context()
    P = c["per"][period]
    J = P["J"]
    dr = T.draws(len(J), P["seed"] + seed_offset, max(c["n_tour"], 1))
    calls = T.simulate(J, P["M"], sc, dr, c["pools"], c["cvs"], c["mix"])
    m = T.metrics(calls, T.period_days(J, sc.regime))
    return (m, calls) if keep else m


SLIM = ["n_calls", "n_trades", "fill_rate", "calls_share_before_reprice", "calls_share_in_decay_window",
        "calls_share_too_late", "calls_median_tau_s", "correct_calls_blocked_by_net_cap",
        "median_usd_per_fill", "per_share_c", "per_share_ci95_c", "pnl_usd", "pnl_per_day_usd", "sharpe_ann",
        "max_dd_usd", "worst_day_usd", "months_positive", "months_total", "capital_usd", "return_on_capital_pct",
        "return_on_capital_ann_pct", "capacity_stale_usd_per_day", "share_fills_at_trade_cap",
        "pnl_correct_usd", "pnl_wrong_usd", "wrong_call_share_of_trades", "n_matches", "usd_traded", "days"]


def slim(m: dict) -> dict:
    out = {}
    for k in SLIM:
        if k not in m:
            continue
        v = m[k]
        if isinstance(v, (list, tuple)):
            out[k] = [round(float(x), 4) for x in v]
        elif isinstance(v, (float, np.floating)):
            out[k] = round(float(v), 4)
        else:
            out[k] = v
    return out


def flat(m: dict) -> dict:
    """Numeric metrics with list-valued ones split into _lo / _hi."""
    out = {}
    for k, v in m.items():
        if isinstance(v, (list, tuple)):
            out[f"{k}_lo"], out[f"{k}_hi"] = float(v[0]), float(v[1])
        elif isinstance(v, (int, float, np.integer, np.floating)):
            out[k] = float(v)
    return out


def seed_summary(ms: list[dict]) -> dict:
    """Mean and SD over seeds of every numeric metric, plus the seed-0 draw in full."""
    F = pd.DataFrame([flat(m) for m in ms])
    mean = F.mean().round(4).to_dict()
    sd = F.std(ddof=0).round(4).to_dict()
    return {"n_seeds": len(ms), "mean": mean, "sd": sd, "seed0": slim(ms[0])}


def _seed_job(args):
    sc_d, period, s = args
    return run_one(T.Scenario(**sc_d), period, seed_offset=s)


def run_seeds(scs: dict[str, T.Scenario], n_seeds: int, workers: int) -> dict:
    """{name: {period: seed_summary}} for each scenario, IS and burned OOS, seeds 0..n_seeds-1."""
    jobs = [(name, asdict(sc), p, s) for name, sc in scs.items() for p in PERIODS for s in range(n_seeds)]
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_seed_job, [j[1:] for j in jobs], chunksize=4))
    out: dict = {}
    for (name, _, p, s), m in zip(jobs, res):
        out.setdefault(name, {}).setdefault(p, [None] * n_seeds)[s] = m
    return {name: {p: seed_summary(v) for p, v in d.items()} for name, d in out.items()}


def _grid_job(args):
    sc_d, period, n_seeds = args
    sc = T.Scenario(**sc_d)
    ms = [run_one(sc, period, seed_offset=s) for s in range(n_seeds)]
    F = pd.DataFrame([flat(m) for m in ms])
    row = {**sc_d, "period": period, "n_seeds": n_seeds, **F.mean().to_dict()}
    row["pnl_per_day_usd_sd"] = float(F.pnl_per_day_usd.std(ddof=0))
    row["sharpe_ann_sd"] = float(F.sharpe_ann.std(ddof=0)) if "sharpe_ann" in F else float("nan")
    row["per_share_c_sd"] = float(F.per_share_c.std(ddof=0)) if "per_share_c" in F else float("nan")
    return row


def grid_scenarios(calib: float, base: T.Scenario, readings=(None,), stale: str = "ref") -> list[T.Scenario]:
    out = []
    for rd in readings:
        for cv, lag, phi, cov, pev, net in itertools.product(*GRID.values()):
            sc = replace(base, cv=cv, stamp_lag=calib if lag is None else lag, phi=phi, coverage=cov,
                         p_event=pev, net_cap=net, stale=stale)
            out.append(sc if rd is None else replace(sc, r_mode=rd))
    return out


def run_grid(scs: list[T.Scenario], n_seeds: int, workers: int) -> pd.DataFrame:
    jobs = [(asdict(sc), p, n_seeds) for sc in scs for p in PERIODS]
    with ProcessPoolExecutor(workers) as ex:
        G = pd.DataFrame(list(ex.map(_grid_job, jobs, chunksize=4)))
    G.insert(0, "label", T.ASSUMED)
    return G


def grid_summary(G: pd.DataFrame) -> dict:
    summ = {}
    for p in PERIODS:
        g = G[G.period == p]
        summ[p] = {k: {"min": round(float(g[k].min()), 3), "median": round(float(g[k].median()), 3),
                       "max": round(float(g[k].max()), 3)}
                   for k in ("sharpe_ann", "pnl_per_day_usd", "per_share_c", "fill_rate", "return_on_capital_ann_pct",
                             "max_dd_usd", "worst_day_usd", "capital_usd") if k in g}
        summ[p]["n_scenarios"] = int(len(g))
        summ[p]["share_scenarios_positive_pnl"] = round(float((g.pnl_usd > 0).mean()), 3)
        summ[p]["share_scenarios_ci_excludes_0"] = round(float((g.per_share_ci95_c_lo > 0).mean()), 3)
    return summ


def grid_marginals(G: pd.DataFrame, dims) -> dict:
    return {p: {d: G[G.period == p].groupby(d).agg(
        sharpe_median=("sharpe_ann", "median"), pnl_per_day_median=("pnl_per_day_usd", "median"),
        per_share_c_median=("per_share_c", "median"), fill_rate_median=("fill_rate", "median"),
        share_positive=("pnl_usd", lambda s: float((s > 0).mean())))
        .round(3).reset_index().astype({d: str}).set_index(d).to_dict("index") for d in dims} for p in PERIODS}


def median_scenario(G: pd.DataFrame, dims) -> dict:
    gi = G[G.period == "IS"].reset_index(drop=True)
    med = gi.pnl_per_day_usd.median()
    k = int((gi.pnl_per_day_usd - med).abs().idxmin())
    msc = {d: gi.loc[k, d] for d in dims}
    mo = G[G.period == "burned_OOS"]
    for d, v in msc.items():
        mo = mo[mo[d] == v]
    keys = ["n_calls", "n_trades", "fill_rate", "per_share_c", "per_share_ci95_c_lo", "per_share_ci95_c_hi",
            "pnl_usd", "pnl_per_day_usd", "pnl_per_day_usd_sd", "sharpe_ann", "max_dd_usd", "worst_day_usd",
            "capital_usd", "return_on_capital_ann_pct"]
    conv = lambda x: float(x) if isinstance(x, (np.floating, float, np.integer, int)) and not isinstance(x, bool) else x  # noqa: E731
    return {"rule": f"scenario whose IS $/day ({SEEDS_GRID}-seed mean) is the grid median (nearest)",
            "scenario": {kk: conv(vv) for kk, vv in msc.items()},
            "IS": {kk: round(conv(gi.loc[k, kk]), 4) for kk in keys if kk in gi},
            "burned_OOS": {kk: round(conv(mo.iloc[0][kk]), 4) for kk in keys if kk in mo}}


# ------------------------------------------------------------------------------------- scenario sets
def prereg_sensitivities(calib: float) -> dict[str, T.Scenario]:
    p = T.PRIMARY
    return {
        "primary (pre-registered model)": p,
        "slip_0 (literal: fill at the stale price)": replace(p, slip=0.0),
        "slip_1c": replace(p, slip=0.01),
        "pool_all_482_points": replace(p, pool="all"),
        "depth_scaling_off": replace(p, vol_scale="none"),
        "depth_scaling_symmetric_cap3": replace(p, vol_scale="sym3"),
        "latency_all_venues_100ms": replace(p, lat_map="all100"),
        "stale_price_vwap_33s_to_1s": replace(p, stale="ref_short"),
        "all_regimes_incl_3s_delay (timing extrapolated)": replace(p, regime="all"),
        "trade_cap_250": replace(p, trade_cap=250.0),
        "trade_cap_5000": replace(p, trade_cap=5000.0),
        "no_net_cap": replace(p, net_cap=np.inf),
        "no_net_cap_trade_cap_5000": replace(p, net_cap=np.inf, trade_cap=5000.0),
        "stamp_lag_calibrated": replace(p, stamp_lag=calib),
    }


def corrected_stresses(calib: float, med_r: float, b_cal: float) -> dict[str, T.Scenario]:
    c = T.CORRECTED
    return {
        "HEADLINE (corrected; timing drawn per tournament)": c,
        # --- readings of the timing data at the pre-registered stamp lag 2.0 (V3)
        "reading: R drawn per point (pre-registered timing model)": replace(c, r_mode="point"),
        "reading: R spread = umpire-stamp noise (t_reprice - t_bounce constant)": replace(c, r_mode="stamp"),
        # --- calibration (an inference): t_reprice - t_bounce = 1.35 s under the stamp reading; stamp lag
        #     3.14 s under the book readings
        "calibrated, stamp reading: t_reprice - t_bounce = 1.35 s": replace(c, r_mode="stamp", stamp_lag=b_cal - med_r),
        "calibrated, tournament reading: stamp lag 3.14 s": replace(c, stamp_lag=calib),
        # --- verifier stresses
        "official stamps truncated: R - 0.5 s": replace(c, r_shift=-0.5),
        "official stamps truncated, point reading": replace(c, r_shift=-0.5, r_mode="point"),
        "queue: fill only if >= 0.25 s before the reprice": replace(c, queue_s=0.25),
        "stamp lag 1.0 s": replace(c, stamp_lag=1.0),
        "stamp lag 1.0 s + queue 0.25 s": replace(c, stamp_lag=1.0, queue_s=0.25),
        "stamp truncation + queue 0.25 s": replace(c, r_shift=-0.5, queue_s=0.25),
        # --- pricing choices
        "wrong calls priced as pre-registered (lose the whole realised jump)": replace(c, wrong_price="ref"),
        "live edge scaled by historical size / live D (generous)": replace(c, edge_scale=True),
        "decay-window fills allowed (edge -> 0 over 0.5 s)": replace(c, order="decay"),
        "no stale-price correction (ref as is)": replace(c, stale_adj=0.0),
        "near stale price ref_short (VWAP [-33 s, -1 s))": replace(c, stale="ref_short", stale_adj=0.0),
        "live pool = all 482 points": replace(c, pool="all"),
        "all venues 100 ms": replace(c, lat_map="all100"),
        # --- pre-registered dimensions, one at a time
        "phi 0.25": replace(c, phi=0.25),
        "phi 1.0": replace(c, phi=1.0),
        "p_event 0.99": replace(c, p_event=0.99),
        "Hawk-Eye-class 340 fps": replace(c, cv="hawkeye340"),
        "own camera, pessimistic": replace(c, cv="own120_pess"),
        "coverage 3/day": replace(c, coverage=3),
        "coverage 30/day": replace(c, coverage=30),
        "net cap 1000": replace(c, net_cap=1000.0),
        "no net cap": replace(c, net_cap=np.inf),
    }


def b_curve_scenarios(med_r: float) -> dict[str, T.Scenario]:
    out = {}
    for rd in ("stamp", "tournament", "point"):
        for b in B_GRID:
            out[f"{rd}|{b:g}"] = replace(T.CORRECTED, r_mode=rd, stamp_lag=round(b - med_r, 6))
    return out


# ------------------------------------------------------------------------------------------ diagnostics
def by_size_and_decomposition(n_seeds: int) -> dict:
    """Corrected headline, all seeds pooled: per-share P&L by realised jump size, and the per-share
    decomposition of correct and wrong fills (measured book edge / cost, post-jump forecast error, fee)."""
    out = {}
    c = context()
    for p in PERIODS:
        n_days = len(T.period_days(c["per"][p]["J"], T.CORRECTED.regime))
        rows = []
        for s in range(n_seeds):
            _, cl = run_one(T.CORRECTED, p, seed_offset=s, keep=True)
            tr = cl[cl.shares > 1e-9].assign(seed=s)
            rows.append(tr)
        tr = pd.concat(rows)
        sb = pd.cut(tr["size"], [0.04, 0.05, 0.07, 0.10, 1.0], right=False)
        bucket = {}
        for k, z in tr.groupby(sb, observed=True):
            g = z[z.correct]
            bucket[str(k)] = {"share_of_shares": round(float(z.shares.sum() / tr.shares.sum()), 3),
                              "net_c_all": round(float(z.pnl.sum() / z.shares.sum() * 100), 3),
                              "net_c_correct": round(float(g.pnl.sum() / g.shares.sum() * 100), 3) if len(g) else None,
                              "pnl_per_day_usd": round(float(z.pnl.sum() / n_seeds / n_days), 2)}
        dec = {}
        for lab, z in (("correct", tr[tr.correct]), ("wrong", tr[~tr.correct])):
            w = z.shares.sum()
            sign = 1 if lab == "correct" else -1
            dec[lab] = {"share_of_trades": round(float(len(z) / len(tr)), 4),
                        "book_edge_c" if lab == "correct" else "book_cost_c":
                            round(float(sign * (z.edge_c * z.shares).sum() / w * 100), 3),
                        "payout_minus_post_jump_price_c": round(float(((z.payout - z.q - z.edge_c) * z.shares).sum() / w * 100), 3),
                        "fee_c": round(float((z.fee_ps * z.shares).sum() / w * 100), 3),
                        "net_c": round(float(z.pnl.sum() / w * 100), 3)}
        out[p] = {"per_share_by_jump_size": bucket, "decomposition": dec}
    return out


def equity_paths(n_seeds: int) -> dict[str, pd.DataFrame]:
    c = context()
    out = {}
    for p in PERIODS:
        days = T.period_days(c["per"][p]["J"], T.CORRECTED.regime)
        cols = {}
        for s in range(n_seeds):
            _, cl = run_one(T.CORRECTED, p, seed_offset=s, keep=True)
            tr = cl[cl.shares > 1e-9]
            cols[f"seed{s}"] = tr.groupby("date").pnl.sum().reindex(days, fill_value=0.0).cumsum()
        out[p] = pd.DataFrame(cols)
    return out


# ---------------------------------------------------------------------------------------------- figures
def figures(eq: dict, gridc: pd.DataFrame, bcurve: pd.DataFrame, calib: float, b_cal: float, med_r: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

    ink, ink2, grid_c, surf = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    blue, orange, grey = "#2a78d6", "#eb6834", "#a3a29e"
    plt.rcParams.update({"text.usetex": False, "font.size": 10, "axes.edgecolor": grid_c, "axes.labelcolor": ink2,
                         "xtick.color": ink2, "ytick.color": ink2, "figure.facecolor": surf,
                         "axes.facecolor": surf, "savefig.facecolor": surf})

    def clean(ax):
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.grid(axis="y", color=grid_c, lw=0.6)

    # --- equity curves, corrected headline: every seed (thin) and the seed mean (bold)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    for ax, (name, col) in zip(axes, (("IS", blue), ("burned_OOS", orange))):
        E = eq[name]
        for c_ in E.columns:
            ax.plot(E.index, E[c_].values, color=col, lw=0.6, alpha=0.25)
        mean = E.mean(axis=1)
        ax.plot(E.index, mean.values, color=col, lw=2.2, solid_capstyle="round")
        ax.axhline(0, color=grid_c, lw=1, zorder=0)
        clean(ax)
        ax.set_title({"IS": "In sample (1 s-delay regime)", "burned_OOS": "Burned OOS (not blind)"}[name],
                     color=ink, loc="left", fontsize=11)
        ax.set_ylabel("cumulative P&L, $")
        ax.tick_params(axis="x", rotation=30)
        usd = lambda x: ("−" if x < 0 else "") + f"\\${abs(x):,.0f}"  # noqa: E731
        ax.annotate(f"mean {usd(mean.iloc[-1])}\n(seeds {usd(E.iloc[-1].min())} to {usd(E.iloc[-1].max())})",
                    (E.index[-1], mean.iloc[-1]), xytext=(-4, 10), textcoords="offset points", color=ink,
                    fontsize=8.5, ha="right")
    fig.suptitle("Tier-0 counterfactual, corrected headline: fills priced from the live book, timing drawn per "
                 "tournament (20 seeds thin, mean bold)", color=ink, x=0.01, ha="left", fontsize=11)
    fig.text(0.01, 0.005, T.ASSUMED + ".\nOwn 120 fps camera, stamp lag 2.0 s, φ 0.5, 10 matches/day, p_event 0.95, "
             "net cap 100; fills priced from the measured live book.", color=ink2, fontsize=8, ha="left")
    fig.tight_layout(rect=(0, 0.06, 1, 0.93))
    fig.savefig(T.OUT / "equity_primary.png", dpi=160)
    plt.close(fig)

    # --- Sharpe heatmap: stamp lag x phi, corrected model, both readings, other dims at primary values
    p = T.CORRECTED
    sel = gridc[(gridc.cv == p.cv) & (gridc.coverage == p.coverage) & (gridc.p_event == p.p_event)
                & (gridc.net_cap == p.net_cap)]
    cmap = LinearSegmentedColormap.from_list("div", ["#e34948", "#f0efec", "#2a78d6"])
    lags = sorted(sel.stamp_lag.unique())
    phis = sorted(sel.phi.unique())
    panels = [(rd, per) for rd in READINGS for per in PERIODS]
    vals = []
    for rd, per in panels:
        s = sel[(sel.r_mode == rd) & (sel.period == per)]
        vals.append((s.pivot_table(index="stamp_lag", columns="phi", values="sharpe_ann").loc[lags, phis],
                     s.pivot_table(index="stamp_lag", columns="phi", values="pnl_per_day_usd").loc[lags, phis]))
    vmax = max(np.nanmax(np.abs(v[0].to_numpy())) for v in vals) or 1.0
    norm = TwoSlopeNorm(vcenter=0.0, vmin=-vmax, vmax=vmax)
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 8.2), sharey=True, layout="constrained")
    titles = {("tournament", "IS"): "Timing per tournament · in sample",
              ("tournament", "burned_OOS"): "Timing per tournament · burned OOS",
              ("stamp", "IS"): "R spread = stamp noise · in sample",
              ("stamp", "burned_OOS"): "R spread = stamp noise · burned OOS"}
    im = None
    for ax, (rd, per), (v, d) in zip(axes.ravel(), panels, vals):
        im = ax.imshow(v.to_numpy(), cmap=cmap, norm=norm, aspect="auto", origin="lower")
        for i in range(len(lags)):
            for j in range(len(phis)):
                x, y = v.to_numpy()[i, j], d.to_numpy()[i, j]
                ax.text(j, i, "n/a" if not np.isfinite(x) else f"{x:.1f}\n{'−' if y < 0 else ''}\\${abs(y):,.0f}/d",
                        ha="center", va="center",
                        color=ink, fontsize=9)
        ax.set_xticks(range(len(phis)), [f"{x:g}" for x in phis])
        ax.set_yticks(range(len(lags)), [f"{x:.2f}" + (" (calib.)" if abs(x - calib) < 1e-9 else "") for x in lags])
        ax.set_xlabel("φ, our share of stale depth")
        ax.set_ylabel("stamp lag t_stamp − t_bounce, s")
        ax.set_title(titles[(rd, per)], color=ink, loc="left", fontsize=10.5)
        for sp in ax.spines.values():
            sp.set_visible(False)
    fig.colorbar(im, ax=axes, shrink=0.8, label=f"daily Sharpe (√365), {SEEDS_GRID}-seed mean")
    fig.suptitle("Corrected model: daily Sharpe and $/day by stamp lag and φ", color=ink, x=0.01, ha="left", fontsize=11)
    fig.supxlabel(T.ASSUMED + ".\nOther dimensions at primary values (own 120 fps, 10 matches/day, p_event 0.95, "
                  "net cap 100). Daily Sharpe ignores model risk; read it as a ranking, not a forecast.",
                  color=ink2, fontsize=8, x=0.01, ha="left")
    fig.savefig(T.OUT / "sharpe_heatmap.png", dpi=160)
    plt.close(fig)

    # --- P&L vs t_reprice - t_bounce, three readings
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    styles = {"stamp": (ink, "-", "R spread = stamp noise (B constant)"),
              "tournament": (blue, "-", "R drawn per tournament (headline)"),
              "point": (grey, "--", "R drawn per point (pre-registered)")}
    for ax, per in zip(axes, PERIODS):
        for rd, (col, ls, lab) in styles.items():
            s = bcurve[(bcurve.reading == rd) & (bcurve.period == per)].sort_values("B")
            ax.plot(s.B, s.pnl_per_day_usd, color=col, ls=ls, lw=2, label=lab, marker="o", ms=3)
            if rd != "point":
                ax.fill_between(s.B, s.pnl_per_day_usd - s.pnl_per_day_usd_sd, s.pnl_per_day_usd + s.pnl_per_day_usd_sd,
                                color=col, alpha=0.10, lw=0)
        ax.axhline(0, color=grid_c, lw=1, zorder=0)
        for x, t in ((0.68, "pre-reg. primary\n(median, lag 2.0)"), (b_cal, "calibrated\n(inference)")):
            ax.axvline(x, color=ink2, lw=0.8, ls=":")
            ax.text(x + 0.02, 0.97, t, color=ink2, fontsize=8, ha="left", va="top", transform=ax.get_xaxis_transform())
        clean(ax)
        ax.set_xlabel("t_reprice − t_bounce, s (median for the drawn readings)")
        ax.set_title({"IS": "In sample", "burned_OOS": "Burned OOS (not blind)"}[per], color=ink, loc="left", fontsize=11)
    axes[0].set_ylabel(f"$/day ({SEEDS_GRID}-seed mean ± SD)")
    axes[1].legend(frameon=False, fontsize=8.5, loc="lower right")
    fig.suptitle("The unmeasured timing decides the sign: P&L vs how long after the bounce the book reprices",
                 color=ink, x=0.01, ha="left", fontsize=11)
    fig.text(0.01, 0.005, T.ASSUMED + f".\nOur order reaches the book ~1.03 s after the bounce (Europe). "
             f"Median measured t_reprice − t_stamp = {med_r:.2f} s.", color=ink2, fontsize=8, ha="left")
    fig.tight_layout(rect=(0, 0.06, 1, 0.93))
    fig.savefig(T.OUT / "pnl_vs_reprice_timing.png", dpi=160)
    plt.close(fig)


# ------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", action="store_true", help="headline + pre-registered primary; print, write nothing")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--figures", action="store_true", help="redraw figures from results/tier0/")
    a = ap.parse_args()
    c = context()
    calib = c["calib"]["central"]["stamp_lag_s"]
    b_cal = c["calib"]["central"]["t_reprice_minus_t_bounce_s"]
    med_r = float(np.median(c["pools"]["D>=3c"].R))
    if a.figures:
        eq = {p: pd.read_csv(T.OUT / f"equity_corrected_{p}.csv", index_col=0, parse_dates=True) for p in PERIODS}
        figures(eq, pd.read_csv(T.OUT / "grid_corrected.csv"), pd.read_csv(T.OUT / "pnl_vs_reprice_timing.csv"),
                calib, b_cal, med_r)
        return
    print(T.ASSUMED)
    if a.primary:
        r = run_seeds({"headline": T.CORRECTED, "pre-registered": T.PRIMARY}, SEEDS_HEAD, a.workers)
        for name, d in r.items():
            for p, s in d.items():
                m = s["mean"]
                print(f"{name:15s} {p:10s} c/sh {m['per_share_c']:6.3f} ± {s['sd']['per_share_c']:.3f}  "
                      f"$/day {m['pnl_per_day_usd']:7.1f} ± {s['sd']['pnl_per_day_usd']:5.1f}  "
                      f"Sharpe {m['sharpe_ann']:6.2f}  fill {m['fill_rate']:.3f}")
        return
    T.OUT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / "results/oos_peeks.log", "a") as fh:
        fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} tier0 counterfactual (verifier corrections) evaluated "
                 f"on burned OOS (non-blind, labelled)\n")
    res = {"label": T.ASSUMED, "trade_set": T.TRADE_SET_LABEL["jumps"],
           "prereg": "research/v2/tier0/PREREG.md", "deviations": "research/v2/tier0/DEVIATIONS.md",
           "never_claim": "No live ATP/WTA data was bought or used. Write: we simulate a trader that has a "
                          "licensed feed and a courtside camera; we did not buy them.",
           "headline_scenario": {k: (v if not isinstance(v, float) or np.isfinite(v) else str(v))
                                 for k, v in asdict(T.CORRECTED).items()},
           "timing": {"median_t_reprice_minus_t_stamp_s": med_r,
                      "pre_registered_primary_median_t_reprice_minus_t_bounce_s": round(med_r + 2.0, 3),
                      "calibrated_t_reprice_minus_t_bounce_s (inference)": b_cal,
                      "calibrated_stamp_lag_s (inference)": calib}}

    # 1. corrected headline + readings + stresses (20 seeds)
    stress = run_seeds(corrected_stresses(calib, med_r, b_cal), SEEDS_HEAD, a.workers)
    res["headline"] = stress["HEADLINE (corrected; timing drawn per tournament)"]
    res["stresses_corrected"] = stress
    print("headline", json.dumps({p: res["headline"][p]["mean"] for p in PERIODS}, indent=1)[:3000])

    # 2. B curve (10 seeds)
    bc = run_seeds(b_curve_scenarios(med_r), SEEDS_GRID, a.workers)
    rows = []
    for k, d in bc.items():
        rd, b = k.split("|")
        for p, s in d.items():
            rows.append({"label": T.ASSUMED, "reading": rd, "B": float(b), "period": p,
                         "stamp_lag": round(float(b) - med_r, 4),
                         **{kk: s["mean"].get(kk) for kk in ("pnl_per_day_usd", "per_share_c", "per_share_ci95_c_lo",
                                                              "per_share_ci95_c_hi", "sharpe_ann", "fill_rate",
                                                              "n_trades", "pnl_wrong_usd")},
                         "pnl_per_day_usd_sd": s["sd"].get("pnl_per_day_usd"), "sharpe_ann_sd": s["sd"].get("sharpe_ann")})
    BC = pd.DataFrame(rows)
    BC.to_csv(T.OUT / "pnl_vs_reprice_timing.csv", index=False)
    res["pnl_vs_t_reprice_minus_t_bounce"] = {
        p: {rd: {f"{r.B:g}": {"usd_per_day": round(r.pnl_per_day_usd, 1), "usd_per_day_sd": round(r.pnl_per_day_usd_sd, 1),
                               "per_share_c": round(r.per_share_c, 3) if pd.notna(r.per_share_c) else None,
                               "sharpe": round(r.sharpe_ann, 2) if pd.notna(r.sharpe_ann) else None}
                  for r in BC[(BC.period == p) & (BC.reading == rd)].sort_values("B").itertuples()}
            for rd in ("stamp", "tournament", "point")} for p in PERIODS}
    for p in PERIODS:
        s = BC[(BC.period == p) & (BC.reading == "stamp")].sort_values("B")
        pos = s[s.pnl_per_day_usd > 0]
        res["pnl_vs_t_reprice_minus_t_bounce"][p]["stamp_breakeven_B_s"] = float(pos.B.min()) if len(pos) else None

    # 3. size buckets + decomposition, equity paths (20 seeds)
    res["headline_by_size_and_decomposition"] = by_size_and_decomposition(SEEDS_HEAD)
    eq = equity_paths(SEEDS_HEAD)
    for p in PERIODS:
        eq[p].to_csv(T.OUT / f"equity_corrected_{p}.csv")
    pd.DataFrame({p: eq[p].mean(axis=1) for p in PERIODS}).to_csv(T.OUT / "equity_primary.csv")

    # 4. corrected grid: pre-registered dimensions x both readings (10 seeds per cell)
    Gc = run_grid(grid_scenarios(calib, T.CORRECTED, readings=READINGS), SEEDS_GRID, a.workers)
    Gc.to_csv(T.OUT / "grid_corrected.csv", index=False)
    dims = list(GRID) + ["r_mode"]
    res["grid_corrected"] = {
        "both_readings": grid_summary(Gc),
        **{f"reading_{rd}": grid_summary(Gc[Gc.r_mode == rd]) for rd in READINGS},
        "median_scenario": median_scenario(Gc, dims),
        "marginals": grid_marginals(Gc, dims)}
    print("corrected grid", json.dumps(res["grid_corrected"]["both_readings"], indent=1)[:2500])

    # 5. pre-registered record: primary + sensitivities (20 seeds), grid + ref_short grid (10 seeds)
    res["prereg_record"] = {"note": "Pre-registered model (stale + slip fill price), literal coverage. Superseded "
                                    "as an estimate by the corrected headline; kept as the record."}
    res["prereg_record"]["sensitivities"] = run_seeds(prereg_sensitivities(calib), SEEDS_HEAD, a.workers)
    res["prereg_record"]["primary"] = res["prereg_record"]["sensitivities"]["primary (pre-registered model)"]
    G = run_grid(grid_scenarios(calib, T.PRIMARY), SEEDS_GRID, a.workers)
    G.to_csv(T.OUT / "grid.csv", index=False)
    res["prereg_record"]["grid_ranges"] = grid_summary(G)
    res["prereg_record"]["median_scenario"] = median_scenario(G, list(GRID))
    res["prereg_record"]["grid_marginals"] = grid_marginals(G, list(GRID))
    G2 = run_grid(grid_scenarios(calib, T.PRIMARY, stale="ref_short"), SEEDS_GRID, a.workers)
    G2.to_csv(T.OUT / "grid_ref_short.csv", index=False)
    res["prereg_record"]["grid_ranges_ref_short (DEVIATIONS T2)"] = grid_summary(G2)

    # 6. inputs
    lp = c["pools"]["D>=3c"]
    cur = lp
    first100 = {lab: {"edge_c_mean": round(float(np.nanmean(np.where(cur[f"S_{lab}"] >= 100, cur[f"E_{lab}_100"] / 100, np.nan)) * 100), 3),
                      "wrong_cost_c_mean": round(float(np.nanmean(np.where(cur[f"SW_{lab}"] >= 100, cur[f"W_{lab}_100"] / 100, np.nan)) * 100), 3),
                      "all_stale_shares_edge_c": round(float(cur[f"E_{lab}_all"].sum() / cur[f"S_{lab}"].sum() * 100), 3)}
                for lab, _ in T.EDGE_SNAPS}
    res["inputs"] = {"stamp_lag_calibration": c["calib"], "point_mix": c["mix"],
                     "cv_systems": c["cvs"], "region_ms": T.REGION_MS,
                     "live_pool_sizes": {k: len(v) for k, v in c["pools"].items()},
                     "live_pool_D3c_quantiles": lp[["R", "usd_2", "usd_1", "usd_025", "usd_post"]]
                     .quantile([.1, .5, .9]).round(3).to_dict(),
                     "live_book_first_100_shares_D3c (snapshots 2 / 1 / 0.25 s before the reprice)": first100,
                     "live_D_mean_c": round(float(lp.D.mean() * 100), 3),
                     "stale_adj_measured": T.STALE_ADJ_MEASURED,
                     "n_tournaments": c["n_tour"],
                     "coverage_matches": {str(N): {"IS": int(((~c["per"]["IS"]["M"].oos) & c["per"]["IS"]["M"].cond.isin(
                         T.coverage_set(c["per"]["IS"]["M"], N, "delay1"))).sum()),
                         "burned_OOS": int((c["per"]["IS"]["M"].oos & c["per"]["IS"]["M"].cond.isin(
                             T.coverage_set(c["per"]["IS"]["M"], N, "delay1"))).sum())} for N in (3, 10, 30)}}
    (T.OUT / "results.json").write_text(json.dumps(res, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    figures(eq, Gc, BC, calib, b_cal, med_r)
    print("done")


if __name__ == "__main__":
    main()
