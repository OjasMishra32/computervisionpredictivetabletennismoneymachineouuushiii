"""CAPITAL CAPACITY STUDY: how much capital the CV strategy (at the simulated 1 s feed baseline) and v2 can run.

    paper; order not sent; CV call on our own streamed footage mapped to a live tennis market for timing
    (different sport); feed baseline 1 s is simulated (licensed feed not purchased)

    python scripts/capacity_study.py --grid --workers 64   # HiPerGator: every simulation ->
                                                            #   results/capacity/{cv_seeds.parquet, v2_grid.csv,
                                                            #   market_daily.csv, market.json}
    python scripts/capacity_study.py --report               # local, light: results/capacity/capacity.json,
                                                            #   cv_cells.csv, fig_capacity.{png,pdf},
                                                            #   research/capacity/CAPACITY.md
    python scripts/capacity_study.py --smoke                # 2 seeds, a few IS cells, print only (no files, no OOS)

What is simulated (nothing is fitted or chosen here; every grid cell is reported)
  CV strategy  src/tier0.py CORRECTED, the verifier-corrected tier-0 model, with the courtside camera replaced by the
               simulated 1 s licensed-feed baseline: the CV call is delayed by a 1.0 s video leg, then the unchanged
               venue->London network, gateway and the venue's 1 s order delay (scripts/tier0_latency_sweep.py
               cell('video', reading, 1.0, 'own120'), imported unchanged). Two readings of the unmeasured stamp lag:
                 lagcal   R drawn per tournament, calibrated stamp lag 3.14 s (an inference from fast-tier prints)
                 prereg   R drawn per tournament, pre-registered stamp lag 2.0 s
               20 seeds, the sweep's seeds: the cell (net 100 sh, $1k/order, phi 0.5, 10 matches/day) reproduces the
               sweep's V = 1.0 s cells draw for draw (checked in capacity.json).
               Impact. Every correct-call fill walks the MEASURED live book: the cumulative edge of the first N stale
               shares 2 / 1 / 0.25 s before the reprice (results/tier0/inputs/live_edge_curve.csv, 2026-10-03 public
               CLOB websocket), interpolated at our arrival time tau and scaled to the match's volume; we get a share
               phi of the stale depth (the fast tier takes the rest); a wrong call walks the opposite side of the book.
               So per-share edge falls as size grows, and fills stop at phi x stale depth.
  v2           the frozen fast-tier copy rule (src/v2.py POLICY via research/v2/sizing/engine.py, imported
               unchanged) re-run on the cached causal feature table (data/v2_lowloss/features_u1.parquet).
               Size dials: $/order cap c scales the walk-forward ticket target with it (deploy_frac = 0.5 x c/$1k) and
               the per-match net cap N scales the per-match gross cap with it (match_cap = $3k x N/100); (100, $1k)
               is the frozen v2 and (500, $5k) is scripts/financials.py's "5x" row. phi_v2 = the share of each copied
               fast-tier print we can also fill (the frozen engine assumes 1). The engine never fills beyond the print
               it copies and has no other impact model: at the fast tier's own fills.

Grid: net cap per match {50, 100, 200, 500, 1000, 2000, 5000} shares x $/order cap {250, 1k, 5k, 25k} x phi
{0.25, 0.5, 1} x coverage {3, 10, 20, 30, all with books} matches/day (CV) x 2 readings x IS / burned OOS x 20 seeds;
plus volume-growth cells (stale depth x g, g = 1.5 / 2 / 3; phi 0.5; coverage 10 and all).
Capital = 3 x peak dollars locked with the repo's 4 h ex-ante lock; also reported with the realised lock until
resolution. Cost of capital = 4.00 % 3-month T-bill (results/financials/financials.json).

Burned OOS: logged in results/oos_peeks.log before it is evaluated. No order is built or sent anywhere in this file.
The committed grid ran on HiPerGator (32 CPUs, ~17 min) with hpg/run.sh's srun mechanics; only results/capacity/ was
synced back, so files other workflows were writing at the same time were not overwritten.
"""
from __future__ import annotations

import argparse
import datetime as dtm
import json
import math
import os
import socket
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)                      # src.polymarket caches under the relative path data/raw
sys.path.insert(0, str(ROOT))
from scripts import tier0_latency_sweep as LS  # noqa: E402
from src import tier0 as T  # noqa: E402

LABEL = ("paper; order not sent; CV call on our own streamed footage mapped to a live tennis market for timing "
         "(different sport); feed baseline 1 s is simulated (licensed feed not purchased)")
ASSUMED = LS.LABEL                  # assumed data: licensed feed/video not purchased; parameters measured
V2_LABEL = "v2 numbers are at the fast tier's own fills (frozen rule; no impact model beyond the copied print)"
NEVER = LS.NEVER
OOS_LINE = "capacity study: burned OOS size/cap/coverage grid (non-blind, no parameter chosen)"
OUT = ROOT / "results/capacity"
DOC = ROOT / "research/capacity/CAPACITY.md"

V_FEED = 1.0
READINGS = {"lagcal": "tournament_lagcal", "prereg": "tournament"}
READ_NAME = {"lagcal": "calibrated stamp lag 3.14 s (inference)", "prereg": "pre-registered stamp lag 2.0 s"}
NET_CAPS = [50, 100, 200, 500, 1000, 2000, 5000]
ORDER_CAPS = [250, 1000, 5000, 25000]
PHIS = [0.25, 0.5, 1.0]
ALL = 1_000_000                     # "all with books": every delay-1 universe match that day
COVS = [3, 10, 20, 30, ALL]
GROWTH = [1.5, 2.0, 3.0]
GROWTH_COVS = [10, ALL]
SEEDS = 20
PERIODS = ("IS", "burned_OOS")
BASE = {"phi": 0.5, "coverage": 10, "net_cap": 100, "order_cap": 1000}   # T.CORRECTED's sizing
T_BILL = 0.04
PATH_ORDER = 250                    # figure / table path: the $250 order cap, the efficient path (most frontier cells)


def cov_name(c) -> str:
    return "all" if int(c) >= ALL else str(int(c))


def log_oos(what: str = "") -> None:
    with open(ROOT / "results/oos_peeks.log", "a") as fh:
        fh.write(f"{dtm.datetime.now(dtm.timezone.utc).isoformat()} {OOS_LINE}{what}\n")


# ================================================================================================ shared metrics
def book_stats(tr: pd.DataFrame, days: pd.DatetimeIndex, end_ts: np.ndarray, peak_fn=T.peak_locked) -> dict:
    """Capital and lock-up facts of one trade book (rows with shares > 0): cond, ts, usd_in, pnl, date, lock_end.
    end_ts = resolution time (s) per row. Peak locked uses the book's ex-ante lock (4 h); the 'resolution' variant
    locks every position until its match resolves."""
    if tr.empty:
        return {"peak_locked_usd": 0.0, "capital_usd": 0.0, "peak_locked_resolution_usd": 0.0,
                "hold_h_median": np.nan, "hold_h_p90": np.nan, "hold_h_median_usd_w": np.nan,
                "share_trades_resolve_gt_24h": np.nan, "max_concurrent_positions": 0.0,
                "median_daily_max_concurrent_positions": 0.0, "notional_usd_per_day": 0.0}
    ts = tr.ts.to_numpy(float)
    usd = tr.usd_in.to_numpy(float)
    end = np.where(np.isfinite(end_ts), np.maximum(end_ts, ts), ts + 4 * 3600)
    hold = (end - ts) / 3600
    o = np.argsort(hold)
    cw = np.cumsum(usd[o]) / usd.sum()
    peak = peak_fn(tr)
    ev = pd.DataFrame({"t": np.concatenate([ts, end]), "d": np.concatenate([usd, -usd])})
    peak_res = float(ev.sort_values(["t", "d"], kind="stable").d.cumsum().max())
    # matches with an open position: first fill -> resolution
    g = pd.DataFrame({"cond": tr.cond.to_numpy(), "ts": ts, "end": end}).groupby("cond").agg(a=("ts", "min"), b=("end", "max"))
    ev2 = pd.DataFrame({"t": np.concatenate([g.a.to_numpy(), g.b.to_numpy()]),
                        "d": np.concatenate([np.ones(len(g)), -np.ones(len(g))])}).sort_values(["t", "d"], kind="stable")
    ev2["n"] = ev2.d.cumsum()
    ev2["day"] = pd.to_datetime(ev2.t, unit="s", utc=True).dt.floor("D")
    dmax = ev2.groupby("day").n.max()
    return {"peak_locked_usd": peak, "capital_usd": T.CAPITAL_MULT * peak, "peak_locked_resolution_usd": peak_res,
            "hold_h_median": float(np.median(hold)), "hold_h_p90": float(np.quantile(hold, 0.9)),
            "hold_h_median_usd_w": float(hold[o][np.searchsorted(cw, 0.5)]),
            "share_trades_resolve_gt_24h": float((hold > 24).mean()),
            "max_concurrent_positions": float(ev2.n.max()),
            "median_daily_max_concurrent_positions": float(dmax.median()),
            "notional_usd_per_day": float(usd.sum() / len(days))}


def daily_risk(tr: pd.DataFrame, days: pd.DatetimeIndex) -> dict:
    daily = tr.groupby("date").pnl.sum().reindex(days, fill_value=0.0) if len(tr) else pd.Series(0.0, index=days)
    eq = np.concatenate([[0.0], daily.cumsum().to_numpy()])
    sd = daily.std()
    return {"pnl_per_day_usd": float(daily.mean()), "sharpe_ann": float(daily.mean() / sd * np.sqrt(365)) if sd > 0 else np.nan,
            "max_dd_usd": float((eq - np.maximum.accumulate(eq)).min()), "worst_day_usd": float(daily.min()),
            "days": float(len(days))}


# ================================================================================================ CV strategy
_POOLS: dict = {}
_ENDS: dict = {}


def grow_pool(pool: pd.DataFrame, g: float) -> pd.DataFrame:
    """Live pool with every resting level g times larger (stale depth $ x g; the cumulative edge of the first N shares
    becomes g x E(N / g)), i.e. the model's depth scale x g in every match. Used only for the volume-growth cells.
    Between the EDGE_N grid points the cumulative edge stays piecewise linear (approximation)."""
    if g == 1.0:
        return pool
    p = pool.copy()
    for c in ("usd_2", "usd_1", "usd_025", "usd_post"):
        p[c] = pool[c] * g
    grid = np.array((0,) + T.EDGE_N, float)
    for side, sh in (("E", "S"), ("W", "SW")):
        for lab, _ in T.EDGE_SNAPS:
            S = pool[f"{sh}_{lab}"].to_numpy(float)
            G = np.column_stack([np.zeros(len(pool))] + [pool[f"{side}_{lab}_{N}"].to_numpy(float) for N in T.EDGE_N])
            Gall = pool[f"{side}_{lab}_all"].to_numpy(float)
            ar = np.arange(len(pool))
            for N in T.EDGE_N:
                m = N / g
                k = int(np.clip(np.searchsorted(grid, m, "right") - 1, 0, len(grid) - 2))
                Gm = G[ar, k] + (G[ar, k + 1] - G[ar, k]) * (m - grid[k]) / (grid[k + 1] - grid[k])
                p[f"{side}_{lab}_{N}"] = g * np.where(m > S, Gall, Gm)
            p[f"{sh}_{lab}"] = S * g
            p[f"{side}_{lab}_all"] = Gall * g
    return p


def _pools(c: dict, g: float) -> dict:
    if g not in _POOLS:
        _POOLS[g] = {**c["pools"], T.CORRECTED.pool: grow_pool(c["pools"][T.CORRECTED.pool], g)}
    return _POOLS[g]


def _ends(c: dict) -> pd.Series:
    if "e" not in _ENDS:
        M = c["per"]["IS"]["M"]
        _ENDS["e"] = pd.Series(M.end.map(lambda x: x.timestamp() if pd.notna(x) else np.nan).to_numpy(float),
                               index=M.cond.to_numpy())
    return _ENDS["e"]


def cv_scenario(c: dict, rk: str, phi: float, cov: int, net: float, order: float):
    sc, cvs = LS.cell("video", READINGS[rk], V_FEED, "own120", c)
    return replace(sc, phi=float(phi), coverage=int(cov), net_cap=float(net), trade_cap=float(order)), cvs


def cv_metrics(calls: pd.DataFrame, days: pd.DatetimeIndex, phi: float, ends: pd.Series) -> dict:
    m = LS.B.flat(T.metrics(calls, days, n_boot=400))
    tr = calls[calls.shares > 1e-9] if len(calls) else calls
    out = {k: m.get(k, np.nan) for k in ("per_share_c", "per_share_ci95_c_lo", "per_share_ci95_c_hi", "fill_rate",
                                         "n_calls", "n_trades", "n_matches", "pnl_correct_usd", "pnl_wrong_usd",
                                         "wrong_call_share_of_trades", "median_usd_per_fill", "share_fills_at_trade_cap")}
    out.update(daily_risk(tr, days))
    out.update(book_stats(tr, days, ends.reindex(tr.cond).to_numpy(float) if len(tr) else np.array([])))
    out["shares_per_day"] = float(tr.shares.sum() / len(days)) if len(tr) else 0.0
    if len(calls):
        ok = (calls.correct & (calls.tau >= 0)).to_numpy()            # correct calls that arrive before the reprice
        out["stale_reach_usd_per_day"] = float(calls.dep_c.to_numpy()[ok].sum() / phi / len(days))
        out["stale_ours_usd_per_day"] = float(calls.dep_c.to_numpy()[ok].sum() / len(days))
        live = ok & (calls.sh_raw.to_numpy() > 1e-9)
        netb = live & (calls.shares.to_numpy() < calls.sh_raw.to_numpy() - 1e-9)
        ordb = live & ~netb & calls.at_cap.to_numpy()
        n_live = max(int(live.sum()), 1)
        out["bind_net_cap"] = float(netb.sum() / n_live)
        out["bind_order_cap"] = float(ordb.sum() / n_live)
        out["bind_depth"] = float((live & ~netb & ~ordb).sum() / n_live)
    if len(tr):
        cor = tr[tr.correct]
        wr = tr[~tr.correct]
        out["edge_correct_c"] = float((cor.edge_c * cor.shares).sum() / cor.shares.sum() * 100) if len(cor) else np.nan
        out["loss_wrong_c"] = float((-wr.edge_c * wr.shares).sum() / wr.shares.sum() * 100) if len(wr) else np.nan
        out["pnl_per_share_correct_c"] = float(cor.pnl.sum() / cor.shares.sum() * 100) if len(cor) else np.nan
        out["pnl_per_share_wrong_c"] = float(wr.pnl.sum() / wr.shares.sum() * 100) if len(wr) else np.nan
    cap = out.get("capital_usd", 0.0)
    out["roc_ann_pct"] = out["pnl_per_day_usd"] * 365 / cap * 100 if cap else np.nan
    out["coc_usd_per_day"] = cap * T_BILL / 365
    return out


def _cv_init():
    import warnings
    warnings.filterwarnings("ignore")
    LS.ctx()


def _cv_job(job):
    rk, phi, cov, net, order, g, period, seeds = job
    c = LS.ctx()
    sc, cvs = cv_scenario(c, rk, phi, cov, net, order)
    pools = _pools(c, g)
    P = c["per"][period]
    J = P["J"]
    days = T.period_days(J, sc.regime)
    ends = _ends(c)
    rows = []
    for s in range(seeds):
        dr = T.draws(len(J), P["seed"] + s, max(c["n_tour"], 1))
        calls = T.simulate(J, P["M"], sc, dr, pools, cvs, c["mix"])
        rows.append({"reading": rk, "phi": phi, "coverage": cov_name(cov), "net_cap": net, "order_cap": order,
                     "growth": g, "period": period, "seed": s, **cv_metrics(calls, days, phi, ends)})
    return rows


def cv_jobs(seeds: int, periods=PERIODS) -> list[tuple]:
    out = []
    for p in periods:
        for rk in READINGS:
            for phi in PHIS:
                for cov in COVS:
                    for net in NET_CAPS:
                        for order in ORDER_CAPS:
                            out.append((rk, phi, cov, net, order, 1.0, p, seeds))
            for g in GROWTH:
                for cov in GROWTH_COVS:
                    for net in NET_CAPS:
                        for order in ORDER_CAPS:
                            out.append((rk, BASE["phi"], cov, net, order, g, p, seeds))
    # big cells first (coverage 'all' is ~3x slower) so the pool finishes evenly
    return sorted(out, key=lambda j: -(j[2] >= ALL))


# ================================================================================================ v2
_V2: dict = {}


def _v2ctx() -> dict:
    if not _V2:
        from src import v2
        from src.tape import universe
        cache = ROOT / "data/v2_lowloss"
        u = universe()
        _V2.update(v2=v2, f=pd.read_parquet(cache / "features_u1.parquet"), wh=pd.read_parquet(cache / "whist_u1.parquet"),
                   oos=set(u.loc[u.oos, "cond"]))
    return _V2


def v2_policy(net: float, order: float):
    v2 = _v2ctx()["v2"]
    return replace(v2.POLICY, name=f"v2_cap_n{net:g}_o{order:g}", net_cap=float(net), usd_cap=float(order),
                   deploy_frac=v2.POLICY.deploy_frac * order / 1000.0, match_cap=3000.0 * net / 100.0)


def v2_slices(f: pd.DataFrame, oos: set) -> dict:
    """Calendar per v2 slice: every day from the first to the last candidate row (month >= EVAL_START)."""
    E = _v2ctx()["v2"].E
    g = f[f.month >= E.EVAL_START]
    out = {}
    for name, m in (("IS", ~g.cond.isin(oos)), ("burned_OOS", g.cond.isin(oos)),
                    ("IS_1s5pct", ~g.cond.isin(oos) & (g.regime == "1s/5%"))):
        d = pd.to_datetime(g[m].ts, unit="s", utc=True).dt.floor("D")
        out[name] = (m, pd.date_range(d.min(), d.max(), freq="D", tz="UTC"))
    return out


def _v2_job(job):
    net, order, phi = job
    x = _v2ctx()
    v2, f, wh, oos = x["v2"], x["f"], x["wh"], x["oos"]
    E = v2.E
    ff = f if phi == 1.0 else f.assign(their_shares=f.their_shares * phi)
    E._WCACHE.clear()
    tr = E.simulate(ff, v2_policy(net, order), "res", "actual", wh)
    tr = tr[tr.month >= E.EVAL_START]
    rows = []
    for name, (_, days) in v2_slices(f, oos).items():
        if name == "IS":
            t = tr[~tr.cond.isin(oos)]
        elif name == "burned_OOS":
            t = tr[tr.cond.isin(oos)]
        else:
            t = tr[~tr.cond.isin(oos) & (tr.regime == "1s/5%")]
        t = t.assign(date=pd.to_datetime(t.date, utc=True))
        t = t[t.date.isin(days)]
        r = {"net_cap": net, "order_cap": order, "phi": phi, "period": name, "n_trades": float(len(t)),
             "n_matches": float(t.cond.nunique()),
             "per_share_c": float(t.pnl.sum() / t.shares.sum() * 100) if len(t) else np.nan,
             "shares_per_day": float(t.shares.sum() / len(days))}
        r.update(daily_risk(t, days))
        r.update(book_stats(t, days, t.end_ts.to_numpy(float), peak_fn=E.peak_locked))
        cap = r["capital_usd"]
        r["roc_ann_pct"] = r["pnl_per_day_usd"] * 365 / cap * 100 if cap else np.nan
        r["coc_usd_per_day"] = cap * T_BILL / 365
        # day-bootstrap 95 % band of $/day (v2 is deterministic: no seeds)
        dly = t.groupby("date").pnl.sum().reindex(days, fill_value=0.0).to_numpy()
        bs = np.random.default_rng(0).choice(dly, (2000, len(dly))).mean(1)
        r["pnl_per_day_boot_lo"], r["pnl_per_day_boot_hi"] = float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))
        rows.append(r)
    return rows


def v2_jobs() -> list[tuple]:
    return [(n, o, p) for p in PHIS for n in NET_CAPS for o in ORDER_CAPS]


# ================================================================================================ market data
def _market_job(_=None) -> dict:
    """Polymarket tennis volume facts (public tapes): daily in-play volume, the 0-3 s window, the qualifying fast
    tier, matches with books, covered-match concurrency per coverage level, and the monthly trend."""
    c = LS.ctx()
    M = c["per"]["IS"]["M"]                                   # whole universe, both periods
    cols = ["cond", "ts", "usd", "delay", "bucket"]
    pr = pd.concat([pd.read_parquet(ROOT / "data/is_prints.parquet", columns=cols),
                    pd.read_parquet(ROOT / "data/locked/oos_prints.parquet", columns=cols)], ignore_index=True)
    pr["day"] = pd.to_datetime(pr.ts, unit="s", utc=True).dt.floor("D")
    d1 = pr.delay == 1
    w03 = pr.bucket == "0-3s"
    daily = pd.DataFrame({
        "inplay_usd": pr.groupby("day").usd.sum(),
        "inplay_usd_delay1": pr[d1].groupby("day").usd.sum(),
        "w03_usd": pr[w03].groupby("day").usd.sum(),
        "w03_usd_delay1": pr[w03 & d1].groupby("day").usd.sum()})
    ex = ROOT / "data/expand_prints.parquet"
    if ex.exists():
        e = pd.read_parquet(ex, columns=["ts", "usd"])
        daily["inplay_usd_u2"] = e.groupby(pd.to_datetime(e.ts, unit="s", utc=True).dt.floor("D")).usd.sum()
    f = pd.read_parquet(ROOT / "data/v2_lowloss/features_u1.parquet", columns=["ts", "usd", "delay"])
    fd = pd.to_datetime(f.ts, unit="s", utc=True).dt.floor("D")
    daily["fasttier_q_usd"] = f.groupby(fd).usd.sum()
    daily["fasttier_q_usd_delay1"] = f[f.delay == 1].groupby(fd[f.delay == 1]).usd.sum()
    md = M.assign(day=M.start.dt.floor("D"))
    daily["n_matches"] = md.groupby("day").cond.size()
    daily["n_matches_delay1"] = md[md.delay == 1].groupby("day").cond.size()
    daily["gamma_volume_usd_by_start"] = md.groupby("day").volume.sum()
    daily = daily.fillna(0.0).sort_index()
    daily.index.name = "day"
    # monthly trend (full months only)
    pr["month"] = pr.day.dt.strftime("%Y-%m")
    mon = pd.DataFrame({"inplay_usd": pr.groupby("month").usd.sum(),
                        "inplay_usd_delay1": pr[d1].groupby("month").usd.sum(),
                        "days_with_prints": pr.groupby("month").day.nunique()})
    mm = md.assign(month=md.start.dt.strftime("%Y-%m"))
    mon["n_matches"] = mm.groupby("month").cond.size()
    mon["gamma_volume_usd"] = mm.groupby("month").volume.sum()
    mon = mon.fillna(0.0)
    # covered-match concurrency (cameras / streams needed) per coverage level and period
    conc = {}
    ends = M.end.where(M.end.notna(), M.start + pd.Timedelta(hours=4))
    for per in PERIODS:
        J = c["per"][per]["J"]
        days = T.period_days(J, "delay1")
        for cov in COVS:
            cs = T.coverage_set(M, cov, "delay1")
            x = M[M.cond.isin(cs) & M.start.dt.floor("D").isin(days)]
            a = x.start.map(pd.Timestamp.timestamp).to_numpy(float)
            b = ends[x.index].map(pd.Timestamp.timestamp).to_numpy(float)
            b = np.maximum(b, a)
            ev = pd.DataFrame({"t": np.concatenate([a, b]), "d": np.concatenate([np.ones(len(a)), -np.ones(len(a))])})
            ev = ev.sort_values(["t", "d"], kind="stable")
            ev["n"] = ev.d.cumsum()
            ev["day"] = pd.to_datetime(ev.t, unit="s", utc=True).dt.floor("D")
            dmax = ev.groupby("day").n.max()
            hrs = (b - a) / 3600
            conc[f"{per}|{cov_name(cov)}"] = {
                "covered_matches_per_day": float(len(x) / len(days)), "max_simultaneous": float(ev.n.max()),
                "median_daily_max_simultaneous": float(dmax.median()), "p90_daily_max_simultaneous": float(dmax.quantile(0.9)),
                "match_hours_median": float(np.median(hrs)), "match_hours_p90": float(np.quantile(hrs, 0.9)),
                "covered_match_hours_per_day": float(np.minimum(hrs, 8).sum() / len(days))}
    return {"daily": daily.reset_index().assign(day=lambda d: d.day.dt.strftime("%Y-%m-%d")).to_dict("list"),
            "monthly": mon.reset_index().rename(columns={"index": "month"}).to_dict("list"),
            "concurrency": conc,
            "period_days": {p: [str(T.period_days(c["per"][p]["J"], "delay1").min().date()),
                                str(T.period_days(c["per"][p]["J"], "delay1").max().date())] for p in PERIODS}}


# ================================================================================================ grid driver
def compact(S: pd.DataFrame) -> pd.DataFrame:
    """Per-seed metrics as float32 (7 significant digits; keeps the committed file small). Grid keys stay exact.
    Carries the label as a categorical column."""
    keys = {"phi", "net_cap", "order_cap", "growth", "seed"}
    S = S.astype({c: np.float32 for c in S.columns if S[c].dtype == np.float64 and c not in keys})
    if "label" not in S:
        S.insert(0, "label", pd.Categorical([LABEL] * len(S)))
    return S


def run_grid(workers: int, seeds: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log_oos(f" [scripts/capacity_study.py --grid on {socket.gethostname()}; logged before the run]")
    jobs = cv_jobs(seeds)
    print(f"CV jobs {len(jobs)} x {seeds} seeds, v2 jobs {len(v2_jobs())}, workers {workers}", flush=True)
    with ProcessPoolExecutor(workers, initializer=_cv_init) as ex:
        fm = ex.submit(_market_job)
        fv = [ex.submit(_v2_job, j) for j in v2_jobs()]
        rows, done = [], 0
        for part in ex.map(_cv_job, jobs, chunksize=1):
            rows.extend(part)
            done += 1
            if done % 200 == 0:
                print(f"  cv {done}/{len(jobs)}  {time.time() - t0:.0f} s", flush=True)
        S = compact(pd.DataFrame(rows))
        S.to_parquet(OUT / "cv_seeds.parquet", index=False, compression="zstd", compression_level=19)
        print(f"CV grid saved ({len(S)} rows, {time.time() - t0:.0f} s)", flush=True)
        mk = fm.result()
        v2rows = [r for f in fv for r in f.result()]
    V = pd.DataFrame(v2rows)
    V.insert(0, "label", f"{LABEL}; {V2_LABEL}")
    V.to_csv(OUT / "v2_grid.csv", index=False, float_format="%.6g")
    daily = pd.DataFrame(mk.pop("daily"))
    daily.insert(0, "label", f"{LABEL}; public Polymarket tapes (market volume only)")
    daily.to_csv(OUT / "market_daily.csv", index=False, float_format="%.6g")
    mk = {"label": LABEL, **mk}
    mk["monthly"] = pd.DataFrame(mk["monthly"]).to_dict("records")
    mk["run"] = {"host": socket.gethostname(), "workers": workers, "seeds": seeds, "runtime_s": round(time.time() - t0, 1),
                 "utc": dtm.datetime.now(dtm.timezone.utc).isoformat(timespec="seconds"),
                 "slurm_job": os.environ.get("SLURM_JOB_ID")}
    (OUT / "market.json").write_text(json.dumps(mk, indent=1, default=float))
    print(f"grid done in {time.time() - t0:.0f} s: {len(S)} CV rows, {len(V)} v2 rows", flush=True)


def smoke() -> None:
    t0 = time.time()
    c = LS.ctx()
    for rk in READINGS:
        for net, order in ((100, 1000), (5000, 25000)):
            r = _cv_job((rk, 0.5, 10, net, order, 1.0, "IS", 2))
            m = pd.DataFrame(r).mean(numeric_only=True)
            print(f"{rk} net {net} order {order}: $/day {m.pnl_per_day_usd:.1f} sharpe {m.sharpe_ann:.2f} "
                  f"capital {m.capital_usd:,.0f} notional/day {m.notional_usd_per_day:,.0f} stale reach/day "
                  f"{m.stale_reach_usd_per_day:,.0f} bind net/order/depth {m.bind_net_cap:.2f}/{m.bind_order_cap:.2f}/"
                  f"{m.bind_depth:.2f} edge {m.edge_correct_c:.2f}c hold {m.hold_h_median:.2f}h", flush=True)
    p = c["pools"][T.CORRECTED.pool]
    assert grow_pool(p, 1.0) is p
    r = _cv_job(("lagcal", 0.5, 10, 5000, 25000, 2.0, "IS", 2))
    print("growth x2, net 5000 / $25k:", round(pd.DataFrame(r).pnl_per_day_usd.mean(), 1), "$/day")
    print(f"smoke {time.time() - t0:.0f} s")


# ================================================================================================ report
def agg_cv(S: pd.DataFrame) -> pd.DataFrame:
    keys = ["reading", "phi", "coverage", "net_cap", "order_cap", "growth", "period"]
    S = S.drop(columns=["label"], errors="ignore")
    g = S.groupby(keys, sort=False)
    A = g.mean(numeric_only=True).drop(columns=["seed"])
    for col in ("pnl_per_day_usd", "sharpe_ann", "capital_usd", "per_share_c"):
        A[f"{col}_sd"] = g[col].std(ddof=0)
        A[f"{col}_p2_5"] = g[col].quantile(0.025)
        A[f"{col}_p97_5"] = g[col].quantile(0.975)
    A["n_seeds"] = g.size()
    return A.reset_index()


def frontier(D: pd.DataFrame, x: str = "capital_usd", y: str = "pnl_per_day_usd") -> pd.DataFrame:
    """Cells sorted by capital that earn more $/day than every cheaper cell (the efficient size path)."""
    D = D.sort_values([x, y], ascending=[True, False])
    keep, best = [], -np.inf
    for i, r in D.iterrows():
        if r[y] > best + 1e-9:
            keep.append(i)
            best = r[y]
    return D.loc[keep]


def interp_x(xs, ys, level, log=True) -> float:
    """First x where ys reaches `level` going up the path (linear in log x); nan if never."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    for i in range(len(xs)):
        if ys[i] >= level:
            if i == 0:
                return float(xs[0])
            a, b = (np.log(xs[i - 1]), np.log(xs[i])) if log else (xs[i - 1], xs[i])
            t = (level - ys[i - 1]) / (ys[i] - ys[i - 1])
            v = a + t * (b - a)
            return float(np.exp(v) if log else v)
    return float("nan")


def cell_brief(r: pd.Series, extra=()) -> dict:
    keys = ["net_cap", "order_cap", "capital_usd", "peak_locked_usd", "peak_locked_resolution_usd", "pnl_per_day_usd",
            "pnl_per_day_usd_p2_5", "pnl_per_day_usd_p97_5", "pnl_per_day_boot_lo", "pnl_per_day_boot_hi", "sharpe_ann",
            "sharpe_ann_sd", "per_share_c", "notional_usd_per_day", "roc_ann_pct", "max_dd_usd", "worst_day_usd",
            "coc_usd_per_day", "hold_h_median", "hold_h_p90", "max_concurrent_positions",
            "stale_reach_usd_per_day", "edge_correct_c", "bind_net_cap", "bind_order_cap", "bind_depth"] + list(extra)
    out = {}
    for k in keys:
        if k in r and pd.notna(r[k]):
            v = r[k]
            out[k] = int(v) if k in ("net_cap", "order_cap") else round(float(v), 4 if abs(float(v)) < 10 else 1)
    return out


def capacity_answer(D: pd.DataFrame, costs: dict, path_order: int = PATH_ORDER) -> dict:
    """Capacity of one configuration (the 28 size cells of a fixed reading / period / phi / coverage / growth).

    at_half_sharpe   along the size path (net cap 50 -> 5,000 shares at the smallest order cap, $250 for the CV strategy,
                     whose cells make up the efficient frontier; the frozen $1k ticket for v2), the capital where the
                     seed-mean Sharpe falls to half the smallest size's, linear in log capital, with the $/day there: the
                     risk-adjusted capacity ("runs up to $X at Sharpe >= Y")
    pnl_max          the cell with the highest seed-mean $/day (where marginal $/day hits zero within the grid)
    robust_pnl_max   the highest seed-mean $/day among cells whose lower band is > 0 (CV: 2.5 % of the 20 seeds;
                     v2: day-bootstrap 2.5 %)
    frontier         cells sorted by capital that earn more $/day than every cheaper cell (marginal $/day per $1k)"""
    D = D.copy()
    D = D[D.capital_usd > 0]
    if D.empty:
        return {"status": "no trades"}
    F = frontier(D)
    imax = D.pnl_per_day_usd.idxmax()
    best = D.loc[imax]
    P = D[D.order_cap == path_order].sort_values("net_cap")
    s_ref = float(P.sharpe_ann.iloc[0])
    xs, sh, pn = F.capital_usd.to_numpy(), F.sharpe_ann.to_numpy(), F.pnl_per_day_usd.to_numpy()
    px, ps, pp = P.capital_usd.to_numpy(), P.sharpe_ann.to_numpy(), P.pnl_per_day_usd.to_numpy()
    half = {"sharpe_threshold": round(s_ref / 2, 3), "path": f"net cap {NET_CAPS[0]}-{NET_CAPS[-1]} sh at ${path_order:,}/order"}
    below = np.flatnonzero(ps <= s_ref / 2) if s_ref > 0 else np.array([0])
    if len(below) == 0:
        half.update({"reached_within_grid": False, "capital_usd": round(float(px[-1]), 0),
                     "pnl_per_day_usd": round(float(pp[-1]), 1), "sharpe_ann": round(float(ps[-1]), 3),
                     "last_cell_above": cell_brief(P.iloc[-1])})
    elif below[0] == 0:
        half.update({"reached_within_grid": True, "capital_usd": round(float(px[0]), 0),
                     "pnl_per_day_usd": round(float(pp[0]), 1), "sharpe_ann": round(float(ps[0]), 3),
                     "last_cell_above": None})
    else:
        i = below[0]
        t = (s_ref / 2 - ps[i - 1]) / (ps[i] - ps[i - 1])
        lx = np.log(px[i - 1]) + t * (np.log(px[i]) - np.log(px[i - 1]))
        half.update({"reached_within_grid": True, "capital_usd": round(float(np.exp(lx)), 0),
                     "pnl_per_day_usd": round(float(pp[i - 1] + t * (pp[i] - pp[i - 1])), 1),
                     "sharpe_ann": round(s_ref / 2, 3), "last_cell_above": cell_brief(P.iloc[i - 1]),
                     "first_cell_below": cell_brief(P.iloc[i])})
    lo_col = "pnl_per_day_usd_p2_5" if "pnl_per_day_usd_p2_5" in D else "pnl_per_day_boot_lo"
    R = D[D[lo_col] > 0]
    # marginal $/day per extra $1k of capital along the frontier; net of the T-bill cost of capital
    seg = []
    for i in range(1, len(F)):
        dc = xs[i] - xs[i - 1]
        dp = pn[i] - pn[i - 1]
        seg.append({"from_capital_usd": round(float(xs[i - 1]), 0), "to_capital_usd": round(float(xs[i]), 0),
                    "to_cell": f"{int(F.net_cap.iloc[i])} sh / ${int(F.order_cap.iloc[i])}",
                    "marginal_usd_per_day_per_1k": round(float(dp / dc * 1000), 4),
                    "marginal_net_coc_usd_per_day_per_1k": round(float(dp / dc * 1000 - T_BILL / 365 * 1000), 4)})
    zero_net = next((s_["from_capital_usd"] for s_ in seg if s_["marginal_net_coc_usd_per_day_per_1k"] <= 0), None)
    out = {"n_cells": int(len(D)),
           "sharpe_ref_smallest_size": round(s_ref, 3),
           "at_half_sharpe": half,
           "capital_where_sharpe_halves_usd": half["capital_usd"] if half.get("reached_within_grid") else None,
           "pnl_max": cell_brief(best),
           "pnl_max_lower_band_positive": bool(best[lo_col] > 0),
           "pnl_max_at_grid_edge": bool(best.net_cap == max(NET_CAPS)),
           "robust_pnl_max": cell_brief(R.loc[R.pnl_per_day_usd.idxmax()]) if len(R) else None,
           "sharpe_at_largest_frontier_size": round(float(sh[-1]), 3),
           "marginal_usd_per_day_hits_zero_at_capital_usd": round(float(xs[-1]), 0) if zero_net is None else zero_net,
           "marginal_note": ("frontier = cells that earn more $/day than every cheaper cell; past its last point (the P&L "
                             "maximum) every extra dollar of capital earns <= 0 $/day within the grid"),
           "frontier": [cell_brief(r) for _, r in F.iterrows()],
           "frontier_marginal": seg}
    # fixed costs: smallest frontier capital whose $/day covers the cost (linear in log capital)
    cov = {}
    for k, v in costs.items():
        x = interp_x(xs, pn, v)
        j = int(np.argmax(pn >= v)) if (pn >= v).any() else None
        cov[k] = {"cost_usd_per_day": round(v, 2), "capital_needed_usd": None if not np.isfinite(x) else round(x, 0),
                  "sharpe_there": None if j is None else round(float(sh[j]), 3),
                  "net_after_cost_at_pnl_max_usd_per_day": round(float(best.pnl_per_day_usd - v), 1),
                  "net_after_cost_at_half_sharpe_usd_per_day": round(float(half["pnl_per_day_usd"] - v), 1)}
    out["fixed_costs"] = cov
    return out


def adv_shares(r, den: dict) -> dict:
    """Our notional as % of the market's daily volumes (period means)."""
    n = float(r["notional_usd_per_day"])
    out = {"share_of_inplay_volume_pct": round(n / den["inplay_usd"] * 100, 4),
           "share_of_03s_window_volume_pct": round(n / den["w03_usd"] * 100, 3),
           "share_of_fasttier_03s_volume_pct": round(n / den["fasttier_q_usd"] * 100, 3)}
    sr = r.get("stale_reach_usd_per_day", np.nan)
    if pd.notna(sr) and sr > 0:
        out["share_of_stale_depth_reach_pct"] = round(n / float(sr) * 100, 2)
    return out


def report() -> dict:
    S = pd.read_parquet(OUT / "cv_seeds.parquet")
    V = pd.read_csv(OUT / "v2_grid.csv")
    daily = pd.read_csv(OUT / "market_daily.csv", parse_dates=["day"]).drop(columns=["label"], errors="ignore").set_index("day")
    daily.index = daily.index.tz_localize("UTC")
    mk = json.loads((OUT / "market.json").read_text())
    fin = json.loads((ROOT / "results/financials/financials.json").read_text())
    sweep = pd.read_csv(ROOT / "results/tier0/latency_sweep.csv")
    sweep = sweep[(sweep.source == "video") & (sweep.cv == "own120") & (sweep.x_s == V_FEED)]
    A = agg_cv(S)
    A.insert(0, "label", f"{LABEL}; {ASSUMED}")
    A.to_csv(OUT / "cv_cells.csv", index=False, float_format="%.6g")
    ca = fin["cost_assumptions"]
    dpm = 365 / 12

    # ---------------- checks: the base cell reproduces the latency sweep's V = 1.0 s cells
    checks = {}
    for rk, rd in READINGS.items():
        for p in PERIODS:
            b = A[(A.reading == rk) & (A.period == p) & (A.growth == 1.0) & (A.phi == BASE["phi"]) &
                  (A.coverage == str(BASE["coverage"])) & (A.net_cap == BASE["net_cap"]) & (A.order_cap == BASE["order_cap"])]
            refv = float(sweep[(sweep.reading == rd) & (sweep.period == p)].pnl_per_day_usd.iloc[0])
            checks[f"{rk}|{p}"] = {"capacity_base_cell_usd_per_day": round(float(b.pnl_per_day_usd.iloc[0]), 4),
                                   "latency_sweep_V1_usd_per_day": refv,
                                   "identical": bool(abs(float(b.pnl_per_day_usd.iloc[0]) - refv) < 1e-3)}
    v2b = V[(V.net_cap == 100) & (V.order_cap == 1000) & (V.phi == 1.0)].set_index("period")
    fsc = fin["strategies"]["v2"]["scaling"]
    for p, fk in (("IS", "IS"), ("burned_OOS", "OOS")):
        checks[f"v2_1x|{p}"] = {"capacity_usd_per_day": round(float(v2b.loc[p, "pnl_per_day_usd"]), 3),
                                "financials_usd_per_day": round(fsc["1x"][fk]["pnl_usd_per_day"], 3),
                                "capacity_capital_usd": round(float(v2b.loc[p, "capital_usd"]), 1),
                                "financials_capital_usd": round(fsc["1x"][fk]["capital_usd"], 1)}
    v25 = V[(V.net_cap == 500) & (V.order_cap == 5000) & (V.phi == 1.0)].set_index("period")
    checks["v2_5x|IS"] = {"capacity_usd_per_day": round(float(v25.loc["IS", "pnl_per_day_usd"]), 3),
                          "financials_usd_per_day": round(fsc["5x"]["IS"]["pnl_usd_per_day"], 3)}

    # ---------------- market denominators per period (CV: delay-1 calendar of the tier-0 periods; v2: its slices)
    def window(a, b):
        return daily[(daily.index >= pd.Timestamp(a, tz="UTC")) & (daily.index <= pd.Timestamp(b, tz="UTC"))]
    den = {}
    for p in PERIODS:
        w = window(*mk["period_days"][p])
        den[p] = {k: float(w[k].mean()) for k in w.columns}
        den[p]["days"] = int(len(w))
        den[p]["window"] = mk["period_days"][p]
    v2win = {"IS": ("2026-02-01", "2026-08-25"), "burned_OOS": ("2026-08-25", mk["period_days"]["burned_OOS"][1])}
    den_v2 = {p: {k: float(window(*v2win[p])[k].mean()) for k in daily.columns} for p in v2win}

    # ---------------- capacity answers
    def _adv(a: dict, D: pd.DataFrame, dn: dict) -> None:
        def cell(net, order):
            return D[(D.net_cap == net) & (D.order_cap == order)].iloc[0]
        a["pnl_max"].update(adv_shares(cell(a["pnl_max"]["net_cap"], a["pnl_max"]["order_cap"]), dn))
        la = a["at_half_sharpe"].get("last_cell_above")
        if la:
            la.update(adv_shares(cell(la["net_cap"], la["order_cap"]), dn))
        if a.get("robust_pnl_max"):
            rp = a["robust_pnl_max"]
            rp.update(adv_shares(cell(rp["net_cap"], rp["order_cap"]), dn))

    answers: dict = {"cv": {}, "v2": {}}
    cov_hours = {p: {cv: mk["concurrency"][f"{p}|{cv}"]["covered_match_hours_per_day"] for cv in map(cov_name, COVS)}
                 for p in PERIODS}
    for (rk, phi, cov, g, p), D in A.groupby(["reading", "phi", "coverage", "growth", "period"], sort=False):
        costs = {}
        for lvl in ("low", "central", "high"):
            lic = (ca["feed_licence"][lvl] + ca["vps_london"][lvl]) / dpm
            # cloud GPU per covered match-hour (event hours from the data, capped at 8 h per match)
            gpu = ca["gpu_inference"][lvl] * cov_hours[p][cov]
            costs[f"licence_{lvl}"] = lic
            costs[f"camera_free_{lvl}"] = lic + gpu
        a = capacity_answer(D, costs)
        if "pnl_max" in a:
            _adv(a, D, den[p])
        answers["cv"][f"{rk}|phi{phi:g}|cov{cov}|g{g:g}|{p}"] = a
    for (phi, p), D in V.groupby(["phi", "period"], sort=False):
        costs = {f"licence_{lvl}": (ca["feed_licence"][lvl] + ca["vps_london"][lvl]) / dpm for lvl in ("low", "central", "high")}
        a = capacity_answer(D, costs, path_order=1000)
        if "pnl_max" in a and p in den_v2:
            _adv(a, D, den_v2[p])
        answers["v2"][f"phi{phi:g}|{p}"] = a

    # ---------------- volume trend (the tapes start mid-October 2025; December is the tour's off-season)
    mon = pd.DataFrame(mk["monthly"])
    mon = mon[(mon.month >= "2025-10") & (mon.month <= "2026-09")].copy()
    mon["days_in_month"] = pd.to_datetime(mon.month + "-01").dt.days_in_month
    mon["inplay_usd_per_day"] = mon.inplay_usd / mon.days_in_month
    mon["inplay_usd_per_match"] = mon.inplay_usd / mon.n_matches.where(mon.n_matches > 0)

    def fit(d: pd.DataFrame, col: str = "inplay_usd_per_day") -> dict:
        b, _ = np.polyfit(np.arange(len(d), dtype=float), np.log(d[col].to_numpy(float)), 1)
        return {"window": [d.month.iloc[0], d.month.iloc[-1]], "months": int(len(d)),
                "growth_per_month_pct": round((math.exp(b) - 1) * 100, 2),
                "doubling_months": round(math.log(2) / b, 1) if b > 0 else None, "slope_log": float(b)}
    season = mon[mon.month >= "2026-01"]
    fits = {"season_2026_jan_sep": fit(season), "last6_apr_sep": fit(season.tail(6)),
            "per_match_season_2026": fit(season, "inplay_usd_per_match")}
    b6 = fits["last6_apr_sep"]["slope_log"]
    trend = {"monthly": mon[["month", "inplay_usd", "inplay_usd_per_day", "inplay_usd_per_match", "inplay_usd_delay1",
                             "days_with_prints", "n_matches", "gamma_volume_usd"]].round(1).to_dict("records"),
             "fits": fits,
             "q2_vs_q3_2026_inplay_usd_per_day_ratio": round(float(
                 mon[mon.month.isin(["2026-07", "2026-08", "2026-09"])].inplay_usd.sum() / 92 /
                 (mon[mon.month.isin(["2026-04", "2026-05", "2026-06"])].inplay_usd.sum() / 91)), 3),
             "note": "Polymarket tennis moneyline universe (ATP / WTA / Challenger, volume >= $5k), in-play prints of the "
                     "public tapes (data/is_prints.parquet + data/locked/oos_prints.parquet), $ per calendar day by month; "
                     "log-linear least squares. The tapes start mid-October 2025 and December is the off-season, so the "
                     "2026 season (January-September) is the main window. Part of the growth is more markets listed "
                     "(n_matches), not more volume per match. Descriptive, not a forecast."}
    growth = {}
    for rk in READINGS:
        for cov in map(cov_name, GROWTH_COVS):
            for p in PERIODS:
                rows = []
                for g in [1.0] + GROWTH:
                    a = answers["cv"].get(f"{rk}|phi{BASE['phi']:g}|cov{cov}|g{g:g}|{p}", {})
                    if "pnl_max" in a:
                        rows.append({"growth": g, "pnl_max_usd_per_day": a["pnl_max"]["pnl_per_day_usd"],
                                     "capital_at_pnl_max_usd": a["pnl_max"]["capital_usd"],
                                     "sharpe_at_pnl_max": a["pnl_max"]["sharpe_ann"],
                                     "capital_where_sharpe_halves_usd": a["capital_where_sharpe_halves_usd"],
                                     "usd_per_day_where_sharpe_halves": a["at_half_sharpe"]["pnl_per_day_usd"],
                                     "sharpe_ref_smallest_size": a["sharpe_ref_smallest_size"],
                                     "months_to_reach_at_last6_trend": (round(math.log(g) / b6, 1) if b6 > 0 else None) if g > 1 else 0})
                growth[f"{rk}|cov{cov}|{p}"] = rows

    out = {"label": LABEL, "assumed": ASSUMED, "v2_label": V2_LABEL, "never_claim": NEVER,
           "what": "Capital capacity of the CV strategy at the simulated 1 s feed baseline (both stamp-lag readings, 20 seeds) "
                   "and of v2, from walking the measured live book; grid of net cap x $/order cap x phi x coverage.",
           "grid": {"net_cap_shares": NET_CAPS, "order_cap_usd": ORDER_CAPS, "phi": PHIS,
                    "coverage_matches_per_day": [cov_name(c) for c in COVS], "growth": GROWTH, "seeds": SEEDS,
                    "readings": READ_NAME, "feed_delay_s": V_FEED, "base": BASE,
                    "v2_size_map": "deploy_frac = 0.5 x order_cap/$1k; match_cap = $3k x net_cap/100; phi_v2 = share of each copied print"},
           "conventions": {"capital": "3 x peak dollars locked, 4 h ex-ante lock per position (repo convention); "
                                      "peak_locked_resolution_usd locks each position until its match resolves",
                           "sharpe": "daily calendar P&L, zero-filled, x sqrt(365)", "cost_of_capital": f"{T_BILL:.2%} 3-month T-bill",
                           "frontier": "cells sorted by capital that earn more $/day than every cheaper cell",
                           "sharpe_halves": "along the size path (net cap 50 -> 5,000 sh at $250/order for CV, $1k for v2), "
                                            "the capital where the seed-mean Sharpe reaches half the smallest size's, linear "
                                            "in log capital",
                           "seed_band": "2.5-97.5 % of the 20 per-seed values (model draws, not data uncertainty)"},
           "checks": checks, "market_denominators": {"cv_periods": den, "v2_periods": den_v2},
           "concurrency_covered_matches": mk["concurrency"], "answers": answers, "volume_trend": trend,
           "growth": growth, "market_run": mk.get("run")}
    return out


# ------------------------------------------------------------------------------------------------ figure
def figure(out: dict, A: pd.DataFrame, V: pd.DataFrame, path: Path) -> None:
    """Paper figure, 2 x 2 at 6.5 in: (a) $/day and (b) Sharpe vs capital required along the efficient size path
    ($250 orders, net cap 50 -> 5,000 shares), CV at both stamp-lag readings (seed band +-1 SD) and v2 ($1k orders, frozen
    tickets); (c) capital required and lock-up vs net cap; (d) our notional as % of daily volume."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter, NullFormatter

    fdir = ROOT / "docs/paper/fonts"
    fam = "DejaVu Sans"
    for fnm in ("SourceSans3-Regular.ttf", "SourceSans3-Semibold.ttf", "SourceSans3-It.ttf"):
        if (fdir / fnm).exists():
            font_manager.fontManager.addfont(str(fdir / fnm))
            fam = "Source Sans 3"
    ORANGE, BLACK, DGREY, MGREY, GRID = "#F26B21", "#000000", "#555555", "#9A9A9A", "#E5E5E5"
    plt.rcParams.update({"font.family": fam, "font.size": 11, "axes.labelsize": 11, "xtick.labelsize": 11,
                         "ytick.labelsize": 11, "legend.fontsize": 11, "axes.linewidth": 0.6, "axes.edgecolor": "#333333",
                         "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42, "font.weight": "normal",
                         "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"})
    fig, axs = plt.subplots(2, 2, figsize=(6.5, 7.7))
    (a1, a2), (a3, a4) = axs
    col = {"lagcal": ORANGE, "prereg": DGREY}
    ls = {"IS": "-", "burned_OOS": (0, (4, 2))}
    kusd = FuncFormatter(lambda v, _: ("−" if v < 0 else "") + (f"${abs(v) / 1000:g}k" if abs(v) >= 1000 else f"${abs(v):g}"))

    def path_cv(rk, p, cov="10"):
        D = A[(A.reading == rk) & (A.period == p) & (A.growth == 1.0) & (A.phi == BASE["phi"]) &
              (A.coverage == cov) & (A.order_cap == PATH_ORDER)]
        return D.sort_values("net_cap")

    def path_v2(p):
        return V[(V.period == p) & (V.phi == 1.0) & (V.order_cap == 1000)].sort_values("net_cap")

    for rk in READINGS:
        for p in PERIODS:
            D = path_cv(rk, p)
            x = D.capital_usd.to_numpy(float)
            m, sd = D.pnl_per_day_usd.to_numpy(float), D.pnl_per_day_usd_sd.to_numpy(float)
            a1.fill_between(x, m - sd, m + sd, color=col[rk], alpha=0.16, lw=0)
            a1.plot(x, m, color=col[rk], ls=ls[p], lw=1.6)
            m2, sd2 = D.sharpe_ann.to_numpy(float), D.sharpe_ann_sd.to_numpy(float)
            a2.fill_between(x, m2 - sd2, m2 + sd2, color=col[rk], alpha=0.16, lw=0)
            a2.plot(x, m2, color=col[rk], ls=ls[p], lw=1.6)
            if rk == "lagcal":            # open circle: where the Sharpe has halved (risk-adjusted capacity)
                h = out["answers"]["cv"][f"lagcal|phi0.5|cov10|g1|{p}"]["at_half_sharpe"]
                if h.get("reached_within_grid"):
                    a1.plot([h["capital_usd"]], [h["pnl_per_day_usd"]], "o", mfc="white", mec=ORANGE, mew=1.3, ms=6, zorder=5)
                    a2.plot([h["capital_usd"]], [h["sharpe_ann"]], "o", mfc="white", mec=ORANGE, mew=1.3, ms=6, zorder=5)
    for p in PERIODS:
        W = path_v2(p)
        a1.plot(W.capital_usd, W.pnl_per_day_usd, color=BLACK, ls=ls[p], lw=1.1, marker="o", ms=2.6)
        a2.plot(W.capital_usd, W.sharpe_ann, color=BLACK, ls=ls[p], lw=1.1, marker="o", ms=2.6)
    for ax in (a1, a2):
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(kusd)
        ax.set_xticks([1e4, 3e4, 1e5])
        ax.axhline(0, color=BLACK, lw=0.6)
        ax.grid(axis="y", color=GRID, lw=0.4)
        ax.set_xlabel("capital required")
    a1.set_ylabel("net $ per day")
    a1.yaxis.set_major_formatter(kusd)
    a2.set_ylabel("Sharpe (annualised)")
    # (c) capital required and lock-up vs net cap (calibrated reading, IS, $250 orders; 10 and all matches a day)
    for cov, lsx in (("10", "-"), ("all", (0, (1, 1.5)))):
        D = path_cv("lagcal", "IS", cov)
        a3.plot(D.net_cap, D.capital_usd, color=ORANGE, ls=lsx, lw=1.6)
        a3.plot(D.net_cap, D.peak_locked_resolution_usd * T.CAPITAL_MULT, color=ORANGE, ls=lsx, lw=0.8, alpha=0.55)
        a3.annotate(f"{cov}/day", (D.net_cap.iloc[-1], D.capital_usd.iloc[-1]), xytext=(-4, 7), textcoords="offset points",
                    fontsize=11, color=ORANGE, ha="right", va="bottom")
    W = path_v2("IS")
    a3.plot(W.net_cap, W.capital_usd, color=BLACK, lw=1.1, marker="o", ms=2.6)
    a3.set_xscale("log")
    a3.set_yscale("log")
    a3.set_xticks(NET_CAPS)
    a3.set_xticklabels(["50", "", "200", "", "1k", "", "5k"])
    a3.set_yticks([2e4, 5e4, 1e5, 2e5])
    a3.yaxis.set_major_formatter(kusd)
    a3.yaxis.set_minor_formatter(NullFormatter())
    a3.set_xlabel("net cap per match (shares)")
    a3.set_ylabel("capital required")
    a3.grid(axis="y", color=GRID, lw=0.4)
    D10 = path_cv("lagcal", "IS")
    hm, h9 = float(D10.hold_h_median.median()), float(D10.hold_h_p90.median())
    a3.text(0.97, 0.04, f"held to resolution:\nmedian {hm:.1f} h, p90 {h9:.1f} h", transform=a3.transAxes, va="bottom",
            ha="right", fontsize=11, color=DGREY)
    # (d) ADV share: our notional / in-play tennis volume (solid) and / the fast tier's 0-3 s volume (dotted)
    for rk in READINGS:
        D = path_cv(rk, "IS")
        dn = out["market_denominators"]["cv_periods"]["IS"]
        a4.plot(D.capital_usd, D.notional_usd_per_day / dn["inplay_usd"] * 100, color=col[rk], lw=1.6)
        a4.plot(D.capital_usd, D.notional_usd_per_day / dn["fasttier_q_usd"] * 100, color=col[rk], lw=1.6, ls=(0, (1, 1.5)))
    W = path_v2("IS")
    dv = out["market_denominators"]["v2_periods"]["IS"]
    a4.plot(W.capital_usd, W.notional_usd_per_day / dv["inplay_usd"] * 100, color=BLACK, lw=1.1, marker="o", ms=2.6)
    a4.plot(W.capital_usd, W.notional_usd_per_day / dv["fasttier_q_usd"] * 100, color=BLACK, lw=1.1, ls=(0, (1, 1.5)),
            marker="o", ms=2.6)
    a4.set_xscale("log")
    a4.set_yscale("log")
    a4.xaxis.set_major_formatter(kusd)
    a4.set_xticks([1e4, 3e4, 1e5])
    a4.set_xlabel("capital required")
    a4.set_ylabel("our notional, % of daily volume")
    a4.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}%"))
    a4.yaxis.set_minor_formatter(NullFormatter())
    a4.grid(axis="y", color=GRID, lw=0.4)
    a4.text(0.02, 0.99, "dotted: of fast tier 0–3 s", transform=a4.transAxes, ha="left", va="top",
            fontsize=11, color=DGREY)
    a4.text(0.98, 0.02, "solid: of all in-play volume", transform=a4.transAxes, ha="right", va="bottom", fontsize=11,
            color=DGREY)
    for ax, lab in zip((a1, a2, a3, a4), "abcd"):
        ax.text(-0.02, 1.03, f"({lab})", transform=ax.transAxes, fontweight="semibold", fontsize=11, ha="right", va="bottom")
    hs = [Line2D([], [], color=ORANGE, lw=1.6, label="CV, stamp lag 3.14 s"),
          Line2D([], [], color=DGREY, lw=1.6, label="CV, stamp lag 2.0 s"),
          Line2D([], [], color=BLACK, lw=1.1, marker="o", ms=2.6, label="v2, fast tier's fills"),
          Line2D([], [], color=MGREY, lw=1.4, ls="-", label="in sample"),
          Line2D([], [], color=MGREY, lw=1.4, ls=(0, (4, 2)), label="burned OOS"),
          Line2D([], [], color=ORANGE, ls="none", marker="o", mfc="white", mew=1.3, ms=6, label="Sharpe halved")]
    fig.legend(handles=hs, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 0.062), fontsize=11,
               handlelength=2.0, columnspacing=1.0)
    cut = LABEL.index("for timing")
    fig.text(0.5, 0.004, LABEL[:cut].strip() + "\n" + LABEL[cut:], ha="center", va="bottom", fontsize=11, color=DGREY,
             linespacing=1.15)
    fig.tight_layout(rect=(0, 0.15, 1, 1), h_pad=1.2, w_pad=1.0)
    meta = {"Title": "Capital capacity", "Subject": LABEL, "Description": LABEL}
    fig.savefig(path, dpi=220, metadata={"Title": meta["Title"], "Description": LABEL})
    fig.savefig(path.with_suffix(".pdf"), metadata={"Title": meta["Title"], "Subject": LABEL})
    plt.close(fig)


# ------------------------------------------------------------------------------------------------ markdown
def fu(x, nd=0) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    x = float(x)
    s = f"{abs(x):,.{nd}f}"
    return ("−$" if x < 0 else "$") + s


def fs(x, nd=1) -> str:
    """Plain number with a true minus sign (Sharpe, percentages)."""
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{float(x):.{nd}f}".replace("-", "−")


def fn(x, nd=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{float(x):+.{nd}f}".replace("-", "−") if nd else f"{float(x):,.0f}"


PER = {"IS": "IS", "burned_OOS": "burned OOS", "IS_1s5pct": "IS, 1 s / 5 % regime"}


def _cv(A: pd.DataFrame, rk: str, p: str, cov: str = "10", phi: float = 0.5, g: float = 1.0) -> pd.DataFrame:
    return A[(A.reading == rk) & (A.period == p) & (A.growth == g) & (A.phi == phi) & (A.coverage == cov)]


def _cap(x) -> str:
    return fu(x) if x else "not within grid"


def write_md(out: dict, A: pd.DataFrame, V: pd.DataFrame) -> str:
    ans = out["answers"]
    L = []
    a = L.append
    a("# Capital capacity: how much money the CV strategy and v2 can run\n")
    a(f"**Label.** {LABEL}. CV-strategy numbers: {ASSUMED}. {V2_LABEL}. {NEVER} Paper only: no order was built, "
      "signed or sent; every number is a simulation on public Polymarket tapes.\n")
    run = out.get("market_run") or {}
    a(f"Generated by `scripts/capacity_study.py` (grid on HiPerGator: 47,040 CV simulations + 84 v2 runs, SLURM job "
      f"{run.get('slurm_job', 'n/a')}, {run.get('workers', 'n/a')} CPUs, {run.get('runtime_s', 0) / 60:.0f} min; report "
      "locally). Raw numbers: `results/capacity/capacity.json`; per-cell table `results/capacity/cv_cells.csv` (seed "
      "mean, SD, 2.5/97.5 %); per-seed rows `results/capacity/cv_seeds.parquet`; v2 grid `results/capacity/v2_grid.csv`; "
      "market volumes `results/capacity/market_daily.csv`, `market.json`; figure `results/capacity/fig_capacity.png` "
      "(vector `.pdf`). The burned OOS was logged in `results/oos_peeks.log` before it was evaluated; no parameter was "
      "chosen on it. The base cell (net 100 sh, $1k/order, phi 0.5, 10 matches/day) reproduces the latency sweep's "
      "V = 1.0 s cells to the cent, and v2's (100 sh, $1k) and (500 sh, $5k) cells reproduce scripts/financials.py's 1x "
      "and 5x rows (Checks).\n")
    a("## The answer (one paragraph for the paper)\n")
    a(out["paragraph"] + "\n")
    a("**How to read 'capacity'.** Three numbers per configuration, over the 28 size cells (net cap × $/order cap): "
      "(i) *Sharpe halves*: walking up the size path (net cap 50 → 5,000 shares with $250 orders for the CV strategy, "
      "whose cells form the efficient frontier; the frozen $1k ticket for v2), the capital where the seed-mean Sharpe has "
      "fallen to half the smallest size's, interpolated in log capital: the risk-adjusted capacity; (ii) "
      "*P&L-max*: the cell with the highest seed-mean $/day, which is where the marginal $/day of extra capital hits "
      "zero within the grid (the T-bill cost of capital, 4 % a year, is ≤ $0.11/day per $1k and moves nothing); (iii) "
      "*robust P&L-max*: the best cell whose 2.5 % seed band is still above zero. Capital = 3 × peak dollars locked with "
      "the repo's 4 h ex-ante lock.\n")
    # ---------------------------------------------------------------- 1
    a("## 1. P&L, Sharpe, per-share and drawdown vs size\n")
    a("CV strategy at the simulated 1 s feed baseline, 10 covered matches a day, phi 0.5 (the revised primary's "
      "settings), along the efficient path: $250 orders, net cap 50 → 5,000 shares. 20 seeds: mean [2.5–97.5 % of "
      "seeds]. 'Edge' = gross edge per share of correct-call fills vs the post-reprice mid (falls as fills walk the "
      "measured book); 'wrong loss' = loss per share of wrong-call fills.\n")
    for rk in READINGS:
        a(f"\n**{READ_NAME[rk]}**\n")
        a("| net cap (sh) | period | $/day [seed band] | Sharpe | net ¢/sh | edge ¢/sh | wrong loss ¢/sh | max DD | capital | ROC ann. | notional $/day | fills bound by net cap / order cap / depth |")
        a("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for net in NET_CAPS:
            for p in PERIODS:
                r = _cv(A, rk, p)
                r = r[(r.order_cap == PATH_ORDER) & (r.net_cap == net)]
                if r.empty:
                    continue
                r = r.iloc[0]
                a(f"| {net:,} | {PER[p]} | {fu(r.pnl_per_day_usd, 1)} [{fu(r.pnl_per_day_usd_p2_5)}, {fu(r.pnl_per_day_usd_p97_5)}] | "
                  f"{fs(r.sharpe_ann)} | {fn(r.per_share_c)} | {fn(r.edge_correct_c)} | {fn(r.loss_wrong_c)} | {fu(r.max_dd_usd)} | "
                  f"{fu(r.capital_usd)} | {fs(r.roc_ann_pct, 0)}% | {fu(r.notional_usd_per_day)} | "
                  f"{r.bind_net_cap:.0%} / {r.bind_order_cap:.0%} / {r.bind_depth:.0%} |")
    a("\n**Order size is the impact dial.** Seed-mean $/day and Sharpe by net cap × $/order cap (calibrated reading, phi "
      "0.5, 10 matches/day). Up to 100 shares the order cap never binds (100 shares at ~50¢ is under $250). Above it, big "
      "orders walk the stale book into worse prices and make wrong calls costlier: from 500 shares up, $1k+ orders need "
      "1.4–3.5× the capital of $250 orders for less $/day and a lower Sharpe in sample, and in the burned OOS they lose "
      "money from 1,000-share positions, while $250 orders stay positive (at a falling Sharpe).\n")
    for p in PERIODS:
        D = _cv(A, "lagcal", p)
        a(f"\n{PER[p]}: $/day (Sharpe)\n")
        a("| net cap \\ $/order | " + " | ".join(f"${o:,}" for o in ORDER_CAPS) + " |")
        a("|---|" + "---|" * len(ORDER_CAPS))
        for net in NET_CAPS:
            cells = []
            for o in ORDER_CAPS:
                r = D[(D.order_cap == o) & (D.net_cap == net)]
                cells.append(f"{fu(r.pnl_per_day_usd.iloc[0])} ({fs(r.sharpe_ann.iloc[0])})" if len(r) else "n/a")
            a(f"| {net:,} | " + " | ".join(cells) + " |")
    a("\n**Our share of the stale depth (phi)**, calibrated reading, 10 matches/day:\n")
    a("| phi | period | Sharpe at smallest size | Sharpe halves at capital ($/day there) | P&L-max: $/day [seed band], Sharpe, capital, cell |")
    a("|---|---|---|---|---|")
    for phi in PHIS:
        for p in PERIODS:
            x = ans["cv"].get(f"lagcal|phi{phi:g}|cov10|g1|{p}")
            if x and "pnl_max" in x:
                m, h = x["pnl_max"], x["at_half_sharpe"]
                a(f"| {phi:g} | {PER[p]} | {x['sharpe_ref_smallest_size']:.1f} | {_cap(x['capital_where_sharpe_halves_usd'])} "
                  f"({fu(h['pnl_per_day_usd'])}) | {fu(m['pnl_per_day_usd'])} [{fu(m.get('pnl_per_day_usd_p2_5'))}, "
                  f"{fu(m.get('pnl_per_day_usd_p97_5'))}], {m['sharpe_ann']:.1f}, {fu(m['capital_usd'])}, "
                  f"{m['net_cap']:,} sh / ${m['order_cap']:,} |")
    a("\n**v2** (frozen copy rule at the fast tier's own fills; phi_v2 = 1; the order cap scales the ticket target; "
      "deterministic, band = day bootstrap). $/day (Sharpe) by net cap × $/order cap:\n")
    for p in ("IS", "burned_OOS"):
        D = V[(V.period == p) & (V.phi == 1.0)]
        a(f"\n{PER[p]}\n")
        a("| net cap \\ $/order | " + " | ".join(f"${o:,}" for o in ORDER_CAPS) + " |")
        a("|---|" + "---|" * len(ORDER_CAPS))
        for net in NET_CAPS:
            cells = []
            for o in ORDER_CAPS:
                r = D[(D.order_cap == o) & (D.net_cap == net)]
                cells.append(f"{fu(r.pnl_per_day_usd.iloc[0])} ({fs(r.sharpe_ann.iloc[0])})" if len(r) else "n/a")
            a(f"| {net:,} | " + " | ".join(cells) + " |")
    # ---------------------------------------------------------------- 2
    a("\n## 2. Coverage and concurrency\n")
    a("Matches covered per day are chosen ex ante (highest pre-start volume per UTC day, delay-1 matches only); 'all' = "
      "every delay-1 match with a book. 'Simultaneous' = covered matches in play at the same moment (CV streams needed). "
      "Calibrated reading, phi 0.5:\n")
    a("| coverage /day | period | covered matches/day | max simultaneous (median daily max) | covered match-hours/day | Sharpe at smallest size | Sharpe halves at capital ($/day) | P&L-max $/day [seed band] (Sharpe, capital) | max open positions at P&L-max |")
    a("|---|---|---|---|---|---|---|---|---|")
    for cov in map(cov_name, COVS):
        for p in PERIODS:
            x = ans["cv"].get(f"lagcal|phi0.5|cov{cov}|g1|{p}")
            cc = out["concurrency_covered_matches"][f"{p}|{cov}"]
            if x and "pnl_max" in x:
                m, h = x["pnl_max"], x["at_half_sharpe"]
                a(f"| {cov} | {PER[p]} | {cc['covered_matches_per_day']:.1f} | {cc['max_simultaneous']:.0f} "
                  f"({cc['median_daily_max_simultaneous']:.0f}) | {cc['covered_match_hours_per_day']:.0f} | "
                  f"{x['sharpe_ref_smallest_size']:.1f} | {_cap(x['capital_where_sharpe_halves_usd'])} ({fu(h['pnl_per_day_usd'])}) | "
                  f"{fu(m['pnl_per_day_usd'])} [{fu(m.get('pnl_per_day_usd_p2_5'))}, {fu(m.get('pnl_per_day_usd_p97_5'))}] "
                  f"({m['sharpe_ann']:.1f}, {fu(m['capital_usd'])}) | {m.get('max_concurrent_positions', 0):.0f} |")
    a("\nMore coverage is the cheapest capacity there is: covering every match roughly doubles the risk-adjusted capacity "
      "of 10 matches a day, because the extra matches are independent bets (Sharpe at the smallest size rises too).\n")
    # ---------------------------------------------------------------- 3
    a("## 3. Capital: peak locked, capital required, lock-up, return, cost of capital\n")
    a("At the half-Sharpe point's last cell and at the P&L-max. Capital = 3 × peak locked under the 4 h ex-ante lock; "
      "'3× peak, to resolution' locks every position until its match resolves (shorter, since a median position resolves "
      "within about an hour). Lock-up = hours from fill to resolution. Cost of capital at the 4.00 % T-bill.\n")
    a("| strategy | config | period | point | cell | peak locked | capital (3×) | 3× peak, to resolution | lock-up h median / p90 | $/day | ROC ann. | cost of capital $/day |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|")

    def caprow(name, cfg, p, lab, m):
        a(f"| {name} | {cfg} | {PER[p]} | {lab} | {m['net_cap']:,} sh / ${m['order_cap']:,} | {fu(m['peak_locked_usd'])} | "
          f"{fu(m['capital_usd'])} | {fu(m.get('peak_locked_resolution_usd', np.nan) * T.CAPITAL_MULT)} | "
          f"{m.get('hold_h_median', np.nan):.2f} / {m.get('hold_h_p90', np.nan):.2f} | {fu(m['pnl_per_day_usd'], 1)} | "
          f"{fs(m.get('roc_ann_pct', np.nan), 0)}% | {fu(m['coc_usd_per_day'], 2)} |")
    for rk in READINGS:
        for cov in ("10", "all"):
            for p in PERIODS:
                x = ans["cv"].get(f"{rk}|phi0.5|cov{cov}|g1|{p}")
                if not x or "pnl_max" not in x:
                    continue
                if x["at_half_sharpe"].get("last_cell_above"):
                    caprow(f"CV, {READ_NAME[rk]}", f"{cov}/day, phi 0.5", p, "before Sharpe halves", x["at_half_sharpe"]["last_cell_above"])
                caprow(f"CV, {READ_NAME[rk]}", f"{cov}/day, phi 0.5", p, "P&L-max", x["pnl_max"])
    for p in ("IS", "burned_OOS"):
        x = ans["v2"].get(f"phi1|{p}")
        if x and "pnl_max" in x:
            caprow("v2 (fast tier's fills)", "phi_v2 1", p, "P&L-max", x["pnl_max"])
    # ---------------------------------------------------------------- 4
    a("\n## 4. The capacity answer in dollars\n")
    a("| strategy | config | period | Sharpe at smallest size | Sharpe halves at capital | $/day there | marginal $/day hits 0 at capital | P&L-max $/day [band] | its Sharpe | its cell | robust P&L-max $/day (capital) |")
    a("|---|---|---|---|---|---|---|---|---|---|---|")
    for rk in READINGS:
        for phi in PHIS:
            for cov in ("10", "all"):
                for p in PERIODS:
                    x = ans["cv"].get(f"{rk}|phi{phi:g}|cov{cov}|g1|{p}")
                    if not x or "pnl_max" not in x:
                        continue
                    m, h, rb = x["pnl_max"], x["at_half_sharpe"], x.get("robust_pnl_max")
                    a(f"| CV, {READ_NAME[rk]} | phi {phi:g}, {cov}/day | {PER[p]} | {x['sharpe_ref_smallest_size']:.1f} | "
                      f"{_cap(x['capital_where_sharpe_halves_usd'])} | {fu(h['pnl_per_day_usd'])} | "
                      f"{fu(x['marginal_usd_per_day_hits_zero_at_capital_usd'])} | {fu(m['pnl_per_day_usd'])} "
                      f"[{fu(m.get('pnl_per_day_usd_p2_5'))}, {fu(m.get('pnl_per_day_usd_p97_5'))}] | {fs(m['sharpe_ann'])} | "
                      f"{m['net_cap']:,} / ${m['order_cap']:,} | "
                      + (f"{fu(rb['pnl_per_day_usd'])} ({fu(rb['capital_usd'])})" if rb else "none") + " |")
    for phi in PHIS:
        for p in ("IS", "burned_OOS", "IS_1s5pct"):
            x = ans["v2"].get(f"phi{phi:g}|{p}")
            if not x or "pnl_max" not in x:
                continue
            m, h, rb = x["pnl_max"], x["at_half_sharpe"], x.get("robust_pnl_max")
            a(f"| v2 (fast tier's fills) | phi_v2 {phi:g} | {PER[p]} | {x['sharpe_ref_smallest_size']:.1f} | "
              f"{_cap(x['capital_where_sharpe_halves_usd'])} | {fu(h['pnl_per_day_usd'])} | "
              f"{fu(x['marginal_usd_per_day_hits_zero_at_capital_usd'])} | {fu(m['pnl_per_day_usd'])} "
              f"[{fu(m.get('pnl_per_day_boot_lo'))}, {fu(m.get('pnl_per_day_boot_hi'))}] | {fs(m['sharpe_ann'])} | "
              f"{m['net_cap']:,} / ${m['order_cap']:,} | " + (f"{fu(rb['pnl_per_day_usd'])} ({fu(rb['capital_usd'])})" if rb else "none") + " |")
    a("\nThe CV P&L-max sits at the grid's largest net cap with $250 orders in most configurations, so in sample $/day "
      "is still creeping up there; its Sharpe is 1–4 and its seed band is wide, which is why the half-Sharpe point is "
      "the capacity we quote. Marginal $/day per extra $1k of capital along the efficient path is in "
      "`answers.*.frontier_marginal`.\n")
    # ---------------------------------------------------------------- 5
    d = out["market_denominators"]["cv_periods"]
    a("## 5. Share of the market (ADV fraction)\n")
    a(f"Polymarket tennis in-play volume (moneyline universe, public tapes): {fu(d['IS']['inplay_usd'])}/day in the IS "
      f"window ({d['IS']['window'][0]} to {d['IS']['window'][1]}), {fu(d['burned_OOS']['inplay_usd'])}/day in the burned "
      f"OOS. All prints in the 0–3 s window after a detected jump: {fu(d['IS']['w03_usd'])} / "
      f"{fu(d['burned_OOS']['w03_usd'])} a day; the qualifying fast tier's own 0–3 s prints: {fu(d['IS']['fasttier_q_usd'])} "
      f"/ {fu(d['burned_OOS']['fasttier_q_usd'])} a day. 'Stale depth we reach' = the resting stale $ (before the fast "
      "tier's share) at our arrival on correct calls that arrive before the reprice.\n")
    a("| strategy | config | period | point | notional $/day | % of in-play volume | % of 0–3 s window | % of fast tier 0–3 s | notional / stale depth we reach |")
    a("|---|---|---|---|---|---|---|---|---|")
    for rk in READINGS:
        for cov in ("10", "all"):
            for p in PERIODS:
                x = ans["cv"].get(f"{rk}|phi0.5|cov{cov}|g1|{p}")
                if not x or "pnl_max" not in x:
                    continue
                for lab, m in (("before Sharpe halves", x["at_half_sharpe"].get("last_cell_above")), ("P&L-max", x["pnl_max"])):
                    if m:
                        a(f"| CV, {READ_NAME[rk]} | {cov}/day | {PER[p]} | {lab} | {fu(m['notional_usd_per_day'])} | "
                          f"{m['share_of_inplay_volume_pct']:.3f}% | {m['share_of_03s_window_volume_pct']:.2f}% | "
                          f"{m['share_of_fasttier_03s_volume_pct']:.2f}% | {m.get('share_of_stale_depth_reach_pct', 0):.1f}% |")
    for p in ("IS", "burned_OOS"):
        m = ans["v2"].get(f"phi1|{p}", {}).get("pnl_max")
        if m:
            a(f"| v2 (fast tier's fills) | phi_v2 1 | {PER[p]} | P&L-max | {fu(m['notional_usd_per_day'])} | "
              f"{m['share_of_inplay_volume_pct']:.3f}% | {m['share_of_03s_window_volume_pct']:.2f}% | "
              f"{m['share_of_fasttier_03s_volume_pct']:.2f}% | n/a |")
    # ---------------------------------------------------------------- 6
    a("\n## 6. After fixed costs\n")
    a("Data licence = the official feed licence ASSUMPTION ($1,250 / $5,000 / $10,000 a month; no public price) + London "
      "VPS (results/financials/financials.json): $42 / $167 / $332 a day. Camera-free deployment = that licence (a licensed "
      "betting-video feed is ASSUMED to cost the same; no public price) + VPS + a cloud GPU per covered match-hour (match "
      "hours from the data, capped at 8 h); no camera, operator or venue fee. 'Capital needed' = the smallest capital on "
      "the efficient frontier (cells that earn more $/day than every cheaper cell) whose seed-mean $/day covers the cost, "
      "interpolated in log capital (Sharpe of the first cell that covers it in brackets).\n")
    a("| strategy | config | period | capital needed: licence low / central / high | camera-free central: $/day, capital needed | net after central licence at half-Sharpe point / at P&L-max |")
    a("|---|---|---|---|---|---|")

    def cn(fc, k):
        c = fc[k]
        return f"{fu(c['capital_needed_usd'])} (Sharpe {fs(c['sharpe_there'])})" if c["capital_needed_usd"] else "not reached"
    for rk in READINGS:
        for cov in ("10", "all"):
            for p in PERIODS:
                x = ans["cv"].get(f"{rk}|phi0.5|cov{cov}|g1|{p}")
                if not x or "fixed_costs" not in x:
                    continue
                fc = x["fixed_costs"]
                a(f"| CV, {READ_NAME[rk]} | {cov}/day, phi 0.5 | {PER[p]} | {cn(fc, 'licence_low')} / {cn(fc, 'licence_central')} / "
                  f"{cn(fc, 'licence_high')} | {fu(fc['camera_free_central']['cost_usd_per_day'])}: {cn(fc, 'camera_free_central')} | "
                  f"{fu(fc['licence_central']['net_after_cost_at_half_sharpe_usd_per_day'])} / "
                  f"{fu(fc['licence_central']['net_after_cost_at_pnl_max_usd_per_day'])} |")
    for p in ("IS", "burned_OOS"):
        x = ans["v2"].get(f"phi1|{p}")
        if x and "fixed_costs" in x:
            fc = x["fixed_costs"]
            a(f"| v2 (fast tier's fills) | phi_v2 1 | {PER[p]} | {cn(fc, 'licence_low')} / {cn(fc, 'licence_central')} / "
              f"{cn(fc, 'licence_high')} | n/a (no CV) | {fu(fc['licence_central']['net_after_cost_at_half_sharpe_usd_per_day'])} / "
              f"{fu(fc['licence_central']['net_after_cost_at_pnl_max_usd_per_day'])} |")
    # ---------------------------------------------------------------- 7
    tr = out["volume_trend"]
    ft_s, ft_6, ft_m = tr["fits"]["season_2026_jan_sep"], tr["fits"]["last6_apr_sep"], tr["fits"]["per_match_season_2026"]
    a("\n## 7. Scaling outlook: if tennis in-play volume grows\n")
    a(f"In-play volume of the tennis universe grew {ft_s['growth_per_month_pct']:+.1f}% a month (log-linear) over the 2026 "
      f"season ({ft_s['window'][0]} to {ft_s['window'][1]}; doubling every {ft_s['doubling_months'] or 'n/a'} months), but only "
      f"{ft_6['growth_per_month_pct']:+.1f}% a month over the last six full months ({ft_6['window'][0]} to {ft_6['window'][1]}; "
      f"doubling every {ft_6['doubling_months'] or 'n/a'} months); Q3 2026 averaged {tr['q2_vs_q3_2026_inplay_usd_per_day_ratio']:.2f}× "
      f"Q2's $/day. Volume per listed match grew {ft_m['growth_per_month_pct']:+.1f}% a month over the season, so much of "
      "the growth is more markets listed. Descriptive, not a forecast. The tapes start mid-October 2025; December is the "
      "off-season.\n")
    a("| month | in-play $/day | in-play $ per match | matches listed | days with prints |")
    a("|---|---|---|---|---|")
    for r in tr["monthly"]:
        a(f"| {r['month']} | {fu(r['inplay_usd_per_day'])} | {fu(r['inplay_usd_per_match'])} | {int(r['n_matches']):,} | "
          f"{int(r['days_with_prints'])} |")
    a("\nModel: every resting level of the measured live book is g × larger (stale depth and the cumulative-edge curve "
      "scale together on both sides of the book; phi, timing and the fast tier's share unchanged). Calibrated reading, "
      "phi 0.5:\n")
    a("| coverage | period | g | Sharpe at smallest size | Sharpe halves at capital ($/day there) | P&L-max $/day (capital, Sharpe) | months to g at the last-6 trend |")
    a("|---|---|---|---|---|---|---|")
    for k, rows in out["growth"].items():
        rk, cov, p = k.split("|")
        if rk != "lagcal":
            continue
        for r in rows:
            a(f"| {cov[3:]}/day | {PER[p]} | {r['growth']:g} | {r['sharpe_ref_smallest_size']:.1f} | "
              f"{_cap(r['capital_where_sharpe_halves_usd'])} ({fu(r['usd_per_day_where_sharpe_halves'])}) | "
              f"{fu(r['pnl_max_usd_per_day'])} ({fu(r['capital_at_pnl_max_usd'])}, {r['sharpe_at_pnl_max']:.1f}) | "
              f"{r['months_to_reach_at_last6_trend'] if r['months_to_reach_at_last6_trend'] is not None else 'n/a'} |")
    a("\nCapital capacity grows more slowly than depth: doubling every level of the book raises the half-Sharpe capital "
      "by roughly a third to a half and the P&L ceiling by about a third to a half, while the $/day earned at the half-Sharpe "
      "point nearly doubles. The wrong-call side of the book deepens too and per-match outcome risk does not shrink. (The "
      "pre-registered 2.0 s reading's growth rows are in capacity.json `growth`.)\n")
    a("## Checks\n")
    for k, v in out["checks"].items():
        a(f"- `{k}`: {json.dumps(v)}")
    a("\n## Caveats\n")
    for c in out["caveats"]:
        a(f"- {c}")
    a("\n![capacity](../../results/capacity/fig_capacity.png)\n")
    a("**Figure.** (a) Net $/day and (b) annualised Sharpe against capital required (3 × peak locked, log scale) along the "
      "efficient size path ($250 orders, net cap 50 → 5,000 shares; 10 matches/day; phi 0.5), CV strategy at the "
      "calibrated 3.14 s (orange) and pre-registered 2.0 s (grey) stamp lag, in sample (solid) and burned OOS (dashed), "
      "band ±1 SD over 20 seeds; open circles = where the Sharpe has halved. v2 (black) at the fast tier's own fills, $1k "
      "orders, net cap 50 → 5,000. (c) Capital required vs net cap (calibrated, in sample; thick = 4 h lock, thin = lock to "
      "resolution) at 10 and all matches a day, and v2. (d) Our notional as % of all in-play tennis volume (solid) and of "
      "the fast tier's 0–3 s volume (dotted), in sample. " + f"{LABEL}. Source: Polymarket public tapes; "
      "results/capacity/capacity.json.\n")
    return "\n".join(L) + "\n"


def paragraph(out: dict) -> str:
    ans = out["answers"]["cv"]
    x = {p: ans[f"lagcal|phi0.5|cov10|g1|{p}"] for p in PERIODS}
    y = {p: ans[f"prereg|phi0.5|cov10|g1|{p}"] for p in PERIODS}
    z = {p: ans[f"lagcal|phi0.5|covall|g1|{p}"] for p in PERIODS}
    v = out["answers"]["v2"]["phi1|burned_OOS"]
    hi, ho = x["IS"]["at_half_sharpe"], x["burned_OOS"]["at_half_sharpe"]
    smin = min(hi["sharpe_ann"], ho["sharpe_ann"])
    big_i = _cv_cell(out, "lagcal", "IS", 5000, 1000)
    big_o = _cv_cell(out, "lagcal", "burned_OOS", 5000, 1000)
    sml = _cv_cell(out, "lagcal", "IS", 50, 250)
    m_i = x["IS"]["pnl_max"]
    adv = hi.get("last_cell_above") or {}
    lic_i = x["IS"]["fixed_costs"]["licence_central"]
    lic_o = x["burned_OOS"]["fixed_costs"]["licence_central"]
    cf_i, cf_o = z["IS"]["fixed_costs"]["camera_free_central"], z["burned_OOS"]["fixed_costs"]["camera_free_central"]
    g2 = {p: next(r for r in out["growth"][f"lagcal|cov10|{p}"] if r["growth"] == 2.0) for p in PERIODS}
    f6 = out["volume_trend"]["fits"]["last6_apr_sep"]
    r0 = lambda v_: fu(round(v_, -3))  # noqa: E731
    lic_txt = (f"from about {r0(lic_i['capital_needed_usd'])} in sample" if lic_i["capital_needed_usd"] else "at no size in sample")
    lic_txt += (f" but in the burned OOS only at the noisy largest size ({r0(lic_o['capital_needed_usd'])}, Sharpe "
                f"{lic_o['sharpe_there']:.1f})" if lic_o["capital_needed_usd"] and (lic_o["sharpe_there"] or 0) < smin
                else (f" and from {r0(lic_o['capital_needed_usd'])} in the burned OOS" if lic_o["capital_needed_usd"]
                      else " and at no size in the burned OOS"))
    cf_txt = (f"covering every match, the camera-free deployment (licence plus cloud GPUs, {fu(cf_i['cost_usd_per_day'])}–"
              f"{fu(cf_o['cost_usd_per_day'])} a day) breaks even from about "
              + (r0(cf_i["capital_needed_usd"]) if cf_i["capital_needed_usd"] else "no size") + " in sample and "
              + (r0(cf_o["capital_needed_usd"]) if cf_o["capital_needed_usd"] else "no size") + " in the burned OOS")
    return (
        f"Simulated at a 1 s licensed-feed baseline ({ASSUMED}; paper only, no order sent), the CV strategy runs up to "
        f"about {r0(ho['capital_usd'])}–{r0(hi['capital_usd'])} of capital at Sharpe ≥ {smin:.0f}. With 10 covered "
        f"matches a day, half the stale depth and the calibrated 3.14 s stamp lag, its Sharpe halves at "
        f"{r0(ho['capital_usd'])} in the burned OOS (about {fu(ho['pnl_per_day_usd'])}/day) and {r0(hi['capital_usd'])} in "
        f"sample (about {fu(hi['pnl_per_day_usd'])}/day); capital is 3 × peak dollars locked, and a median position resolves "
        f"in {adv.get('hold_h_median', float('nan')):.1f} h. Beyond that, impact and match risk take over: fills walk the "
        f"measured book (correct-call edge {sml['edge_correct_c']:.1f}¢ a share at the smallest size, "
        f"{big_i['edge_correct_c']:.1f}¢ at 5,000-share positions with $1k orders), wrong calls cost more "
        f"({sml['loss_wrong_c']:.1f}¢ to {big_i['loss_wrong_c']:.1f}¢ a share), and larger net positions per match add "
        f"outcome variance faster than edge. Large orders lose money in the burned OOS ({fu(big_o['pnl_per_day_usd'])}/day "
        f"at 5,000 shares with $1k orders); $250 orders keep adding dollars in sample, up to {fu(m_i['pnl_per_day_usd'])}/day "
        f"on {r0(m_i['capital_usd'])}, but at Sharpe {m_i['sharpe_ann']:.1f} with a seed band of "
        f"{fu(m_i.get('pnl_per_day_usd_p2_5'))} to {fu(m_i.get('pnl_per_day_usd_p97_5'))}. Covering every match with a "
        f"book raises the half-Sharpe capacity to {r0(z['burned_OOS']['at_half_sharpe']['capital_usd'])} (burned OOS) and "
        f"{r0(z['IS']['at_half_sharpe']['capital_usd'])} (in sample). At the pre-registered 2.0 s stamp lag the Sharpe is "
        f"{y['IS']['sharpe_ref_smallest_size']:.1f} in sample and {y['burned_OOS']['sharpe_ref_smallest_size']:.1f} in the "
        f"burned OOS even at the smallest size, so there is no capacity to speak of. Just below the half-Sharpe size our "
        f"notional is {adv.get('share_of_inplay_volume_pct', float('nan')):.2f}% of Polymarket's in-play tennis volume but "
        f"{adv.get('share_of_fasttier_03s_volume_pct', float('nan')):.0f}% of the fast tier's 0–3 s volume: the binding "
        f"constraint is the seconds after each point, not the market. A central $167/day data licence is covered "
        f"{lic_txt}; {cf_txt}. If in-play volume keeps its last-six-month trend ({f6['growth_per_month_pct']:+.1f}% a month), "
        f"the book doubles in about {f6['doubling_months']:.0f} months, which in the model lifts the half-Sharpe capital to "
        f"{r0(g2['burned_OOS']['capital_where_sharpe_halves_usd'])}–{r0(g2['IS']['capital_where_sharpe_halves_usd'])}. For "
        f"comparison, v2 at the fast tier's own fills peaks in the burned OOS at {fu(v['pnl_max']['pnl_per_day_usd'])}/day "
        f"on {r0(v['pnl_max']['capital_usd'])}.")


def _cv_cell(out: dict, rk: str, p: str, net: int, order: int, cov: str = "10", phi: float = 0.5) -> dict:
    A = out["_A"]
    r = _cv(A, rk, p, cov, phi)
    return r[(r.net_cap == net) & (r.order_cap == order)].iloc[0].to_dict()


CAVEATS = [
    "The CV strategy is a simulation: no licensed feed or video was bought, no camera is at any court, and the 1 s feed "
    "baseline is simulated. Its timing rests on an unmeasured stamp lag; the two readings bracket it and give very "
    "different answers.",
    "Impact is the measured live book of one day (2026-10-03, 9 WTA matches, 265 points with a >= 3c move), scaled down "
    "to smaller matches and never up (except in the growth cells). Depth on other days, at other tournaments or after we "
    "start trading may differ; the fast tier may react to us (phi fixed).",
    "Capital uses the repo's 4 h ex-ante lock. Positions are held to resolution: a median of about 1 h and a p90 of "
    "2-3.5 h, so locking each until its match resolves needs about a quarter less capital (median ratio 0.75 across the "
    "grid); 0.1-0.8 % of fills sit in markets that resolve more than 24 h later, which ties up a little capital the "
    "4 h model does not charge for.",
    "v2 has no price-impact model: it never fills beyond the print it copies, so its larger rows are upper bounds; phi_v2 "
    "< 1 is the only competition dial.",
    "The burned OOS is non-blind (looked at before); it is reported, never used to choose a size. Seed bands are model "
    "draws, not data uncertainty.",
    "The volume trend is a log-linear fit to 9 (2026 season) and 6 (last six) full months of one venue's tennis tapes, "
    "descriptive only; the growth cells assume stale depth scales with volume.",
]


def run_report() -> None:
    out = report()
    A = pd.read_csv(OUT / "cv_cells.csv")
    A["coverage"] = A.coverage.astype(str)
    out["_A"] = A
    out["paragraph"] = paragraph(out)
    del out["_A"]
    out["caveats"] = CAVEATS
    out["generated_utc"] = dtm.datetime.now(dtm.timezone.utc).isoformat(timespec="seconds")
    V = pd.read_csv(OUT / "v2_grid.csv")
    (OUT / "capacity.json").write_text(json.dumps(out, indent=1, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o)))
    figure(out, A, V, OUT / "fig_capacity.png")
    DOC.parent.mkdir(parents=True, exist_ok=True)
    DOC.write_text(write_md(out, A, V))
    print(out["paragraph"])
    print(json.dumps(out["checks"], indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("COURTSIDE_WORKERS", 2)))
    ap.add_argument("--seeds", type=int, default=SEEDS)
    a = ap.parse_args()
    if a.smoke:
        smoke()
    if a.grid:
        run_grid(a.workers, a.seeds)
    if a.report:
        run_report()


if __name__ == "__main__":
    main()
