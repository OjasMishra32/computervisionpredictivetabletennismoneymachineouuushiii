"""Tier-0 FEED-LATENCY SWEEP: the tier-0 counterfactual without a courtside camera.

    assumed data: licensed feed/video not purchased; parameters measured.

    python scripts/tier0_latency_sweep.py --workers 64   # sweep -> results/tier0/latency_sweep.{json,csv},
                                                          #   latency_sweep_seeds.csv, fig_pnl_vs_feed_latency.png
    python scripts/tier0_latency_sweep.py --figures      # redraw the figure + print the tables from the CSVs
    python scripts/tier0_latency_sweep.py --smoke        # 2 seeds, 3 cells, print only (no files, no OOS)

The revised primary tier-0 counterfactual (src/tier0.py `CORRECTED`, research/v2/tier0/RESULTS.md) assumes our
own 120 fps camera at the court. We cannot put a camera in the court. This script re-runs that exact model with
information sources a trader could actually license or watch. src/tier0.py and scripts/tier0_backtest.py are
imported unchanged; the feed delay is added at call time by overriding the CV-system table passed to
`T.simulate` (the only place `simulate` reads it is the order's arrival time).

Sources
  video     licensed betting video / TV / a public stream, plus our CV on the frames. The call is delayed by the
            video delay V:  call = bounce - CV lead + V + inference, then the unchanged venue->London network,
            gateway and the venue's 1 s order delay. Implemented as t_inf -> t_inf + V. V = 0 reproduces the
            revised primary exactly (checked against results/tier0/results.json in the output).
  official  licensed official point data (umpire tablet), NO CV. Every point is known at the official stamp
            t_stamp = bounce + stamp lag, error-free (precision 1, no early calls), then the same network,
            gateway and 1 s venue delay. Timing, per reading of R = t_reprice - t_stamp (RESULTS.md section 2):
              tournament  t_reprice = t_stamp + R drawn once per tournament  -> tau = R_tournament - transit
              stamp       t_reprice - t_bounce is constant and R's spread is stamp noise, so the stamp the feed
                          delivers is t_reprice - R_point                    -> tau = R_point - transit
            In both readings the stamp lag cancels: the official feed's P&L does not depend on it.
  fastfeed  (extension, labelled) a licensed fast-scout point feed that beats the umpire stamp by D s, precision 1
            (generous: scouts make errors). Same as `official` with the call D s earlier (needs D < stamp lag).

Readings of the reprice timing (as RESULTS.md section 2): `tournament` (R drawn per tournament, the headline),
`stamp` (R's spread = umpire-stamp noise, t_reprice - t_bounce = median R + 2.0 s = 0.68 s), and, labelled as a
supplement, `stamp_calibrated` (t_reprice - t_bounce = 1.35 s, the fast-tier-print inference).

Nothing is fitted or chosen here: every parameter is the revised primary's. 20 seeds per cell (the backtest's
seeds, so V = 0 is the published headline draw for draw).
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import socket
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)                      # src.polymarket caches under the relative path data/raw
sys.path.insert(0, str(ROOT))
from scripts import tier0_backtest as B  # noqa: E402
from src import tier0 as T  # noqa: E402

LABEL = "assumed data: licensed feed/video not purchased; parameters measured"
NEVER = ("We did not buy a licensed feed or licensed video, we have no camera at any court, and no live ATP/WTA "
         "data was used. The tier-0 trader is simulated; its timing and fill inputs are our measurements.")
OUT = T.OUT
SEEDS = 20
PERIODS = B.PERIODS

V_MAIN = [0.05, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]   # the requested video-delay grid, s
V_CHECK = [0.0]                                                    # = the revised primary (our own camera)
V_EXT = [20.0, 40.0, 60.0]                                         # extension: TV / public-stream delays
V_DENSE = [round(0.05 * i, 2) for i in range(61)]                  # 0 .. 3 s step 0.05 (break-even search)
V_ALL = sorted(set(V_MAIN + V_CHECK + V_EXT + V_DENSE))
LAGS = [1.0, 2.0, 3.0]                                             # official stamp lag, s
FAST_D = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5]                         # fast feed's lead over the stamp, s (lag 2.0)
READINGS = ["tournament", "stamp", "stamp_calibrated"]
TRIM_POOL = "D>=3c_R<=3s"
READ_LABEL = {"tournament": "R drawn per tournament (headline reading)",
              "stamp": "R spread = umpire-stamp noise (t_reprice - t_bounce = 0.68 s)",
              "stamp_calibrated": "stamp-noise reading at the calibrated t_reprice - t_bounce = 1.35 s (inference)"}

# Latency bands of realistic sources (s). Figures are vendor claims or third-party measurements, cited; where a
# band edge is ours, it says so.
SOURCES = [
    {"key": "venue_camera", "name": "venue camera (not feasible)", "band_s": [0.0, 0.05], "source": "video",
     "read_at_s": [0.0, 0.05],
     "basis": "Our own 120 fps camera at the court (the revised primary): 20 ms inference, no video leg. "
              "Not feasible: we cannot put a camera in the court, and courtside data collection without the "
              "organiser's licence breaches tournament terms. 0.05 s = the task's upper bound for a venue camera.",
     "cites": []},
    {"key": "official_feed", "name": "licensed official point feed (umpire tablet), no CV", "band_s": [1.0, 3.0],
     "source": "official", "read_at_s": [1.0, 3.0],
     "basis": "Stamp lag t_stamp - t_bounce is not measured (model grid 1-3 s). The umpire enters the point after "
              "the line call and audio cue, which adds delay before the data reaches operators (Sportradar/TDI "
              "talk, 2026). The WTA's licensed fast feed beats the umpire feed on 80 % of points and by > 1 s on "
              "32 % (Stats Perform). In this model the stamp lag cancels; what matters is that the book reprices a "
              "median 1.32 s BEFORE the official stamp (measured, research/v2/latency).",
     "cites": ["https://regensports.substack.com/p/i-attended-sportradars-game-set-tech",
               "https://www.statsperform.com/products/official-wta-data-streaming/"]},
    {"key": "betting_video", "name": "licensed betting video", "band_s": [0.5, 8.0], "source": "video",
     "read_at_s": [0.5, 1.0, 2.0, 5.0, 8.0],
     "basis": "Low end 0.5 s: Stats Perform 'Realtime Streaming', '0.5 seconds glass-to-glass latency' (vendor "
              "claim, unverified). High end 8 s: Genius Sports BetVision, venue camera to device 'four to eight "
              "seconds'. Sportradar: trading streams 'up to eight seconds faster than any TV signal' (no absolute "
              "figure). IMG Arena: no public figure found. Genius: its live data is 'always 3-4 seconds ahead of "
              "video', i.e. betting video is kept behind the official data on purpose.",
     "cites": ["https://www.statsperform.com/industries/sportsbooks/",
               "https://www.statsperform.com/products/realtime-streaming/",
               "https://next.io/news/betting/matt-fleckenstein-raising-bar-in-play-betting/",
               "https://sportradar.com/betting-gaming/products/live-streams/",
               "https://ably.com/case-studies/genius-sports"]},
    {"key": "tv", "name": "TV broadcast", "band_s": [3.0, 20.0], "source": "video", "read_at_s": [3.0, 5.0, 10.0, 20.0],
     "basis": "Cable/satellite roughly 5 s behind live (GL Systemhaus 2018; Uswitch table via ISPreview 2021: "
              "satellite 0.9-2.2 s, cable ~5 s, relative to the fastest feed). US Super Bowl LX, spotters in the "
              "stadium: over-the-air 19 s, cable 38 s (Stats Perform / Phenix, Feb 2026). Band 3-20 s: the "
              "task's 3-10 s widened to the measured over-the-air figure; cable can be later.",
     "cites": ["https://www.gl-systemhaus.de/en/blog/who-cheers-first-about-latencies-in-sports-livestreaming",
               "https://www.ispreview.co.uk/index.php/2021/06/broadcast-lag-in-live-online-tv-sport-streaming-frustrates-fans.html",
               "https://thedesk.net/2026/02/stats-perform-phenix-latency-super-bowl-lx/"]},
    {"key": "stream", "name": "public online stream", "band_s": [10.0, 60.0], "source": "video",
     "read_at_s": [10.0, 20.0, 40.0, 60.0],
     "basis": "Streaming 10-45 s behind live (Uswitch via ISPreview 2021); HLS defaults ~30 s (GL Systemhaus); "
              "Super Bowl LX streams 48-60 s (Stats Perform / Phenix). Ours: the Polymarket book leads the ESPN "
              "score by a median 44.5 s (results/summary.json h4, n = 75) and every public score source is 28-44 s "
              "behind the book (research/v2/latency/RESULTS.md).",
     "cites": ["https://www.ispreview.co.uk/index.php/2021/06/broadcast-lag-in-live-online-tv-sport-streaming-frustrates-fans.html",
               "https://www.gl-systemhaus.de/en/blog/who-cheers-first-about-latencies-in-sports-livestreaming",
               "https://thedesk.net/2026/02/stats-perform-phenix-latency-super-bowl-lx/",
               "results/summary.json h4", "research/v2/latency/RESULTS.md"]},
]

KEEP = ["per_share_c", "per_share_ci95_c_lo", "per_share_ci95_c_hi", "pnl_per_day_usd", "pnl_usd", "sharpe_ann",
        "fill_rate", "calls_share_before_reprice", "calls_share_in_decay_window", "calls_share_too_late",
        "calls_median_tau_s", "n_calls", "n_trades", "wrong_call_share_of_trades", "pnl_correct_usd",
        "pnl_wrong_usd", "max_dd_usd", "worst_day_usd", "capital_usd", "days"]


# --------------------------------------------------------------------------------------------- cells
def reading_params(reading: str, c: dict) -> dict:
    med_r = float(np.median(c["pools"]["D>=3c"].R))
    if reading == "tournament":
        return {"r_mode": "tournament", "stamp_lag": T.CORRECTED.stamp_lag}
    if reading == "stamp":
        return {"r_mode": "stamp", "stamp_lag": T.CORRECTED.stamp_lag}
    if reading == "stamp_calibrated":
        b_cal = c["calib"]["central"]["t_reprice_minus_t_bounce_s"]
        return {"r_mode": "stamp", "stamp_lag": round(b_cal - med_r, 6)}
    raise ValueError(reading)


def cell(source: str, reading: str, x: float, cv: str, c: dict) -> tuple[T.Scenario, dict]:
    """Scenario + CV-system table for one cell. Only the arrival time (via t_inf) and, for the point feeds,
    the call accuracy and the reading's timing draw are changed; everything else is T.CORRECTED."""
    cvs = dict(c["cvs"])
    pool = T.CORRECTED.pool
    if source.endswith("_trimR"):            # robustness: live pool without the 3 points with R > 3 s
        source, pool = source[:-len("_trimR")], TRIM_POOL
    if source == "video":
        base = cvs[cv]
        cvs[cv] = {**base, "t_inf": base["t_inf"] + x}
        return replace(T.CORRECTED, cv=cv, pool=pool, **reading_params(reading, c)), cvs
    if source in ("official", "fastfeed"):
        if reading not in ("tournament", "stamp"):
            raise ValueError(reading)
        lag, d = (x, 0.0) if source == "official" else (2.0, x)
        assert d < lag
        cvs["point_feed"] = {"leads_ms": [0], "recall": [[0.0]], "precision": [1.0], "bins_w": [1.0],
                             "max_lead_ms": 0, "t_inf": lag - d}
        return replace(T.CORRECTED, cv="point_feed", p_event=1.0, stamp_lag=lag, pool=pool,
                       r_mode="tournament" if reading == "tournament" else "point"), cvs
    raise ValueError(source)


def ctx() -> dict:
    """tier0_backtest.context() plus the trimmed live pool (R <= 3 s) used by the *_trimR robustness cells."""
    c = B.context()
    if TRIM_POOL not in c["pools"]:
        p = c["pools"][T.CORRECTED.pool]
        c["pools"][TRIM_POOL] = p[p.R <= 3.0].reset_index(drop=True)
    return c


def _init():
    import warnings
    warnings.filterwarnings("ignore")
    ctx()


def _job(j):
    source, reading, x, cv, period, seed = j
    c = ctx()
    sc, cvs = cell(source, reading, x, cv, c)
    P = c["per"][period]
    J = P["J"]
    dr = T.draws(len(J), P["seed"] + seed, max(c["n_tour"], 1))
    calls = T.simulate(J, P["M"], sc, dr, c["pools"], cvs, c["mix"])
    m = B.flat(T.metrics(calls, T.period_days(J, sc.regime)))
    return {"source": source, "reading": reading, "x_s": x, "cv": cv, "period": period, "seed": seed,
            **{k: m.get(k, np.nan) for k in KEEP}}


def jobs(seeds: int) -> list[tuple]:
    out = []
    for p in PERIODS:
        for s in range(seeds):
            for rd in READINGS:
                for v in V_ALL:
                    out.append(("video", rd, v, "own120", p, s))
                for v in V_CHECK + V_MAIN + V_EXT:
                    out.append(("video", rd, v, "own120_pess", p, s))
            for rd in ("tournament", "stamp"):
                for lag in LAGS:
                    out.append(("official", rd, lag, "point_feed", p, s))
                for d in FAST_D:
                    out.append(("fastfeed", rd, d, "point_feed", p, s))
                out.append(("official_trimR", rd, 2.0, "point_feed", p, s))
            for v in V_CHECK + V_MAIN + V_EXT:
                out.append(("video_trimR", "tournament", v, "own120", p, s))
    return out


def grid_tag(source: str, x: float, cv: str) -> str:
    if source.endswith("_trimR"):
        return "robustness_pool_without_R_gt_3s"
    if source != "video":
        return "main" if source == "official" else "extension"
    if cv != "own120":
        return "sensitivity_cv_pessimistic"
    if x in V_CHECK:
        return "check_revised_primary"
    if x in V_MAIN:
        return "main"
    if x in V_EXT:
        return "extension"
    return "dense"


# ------------------------------------------------------------------------------------------ summaries
def summarise(S: pd.DataFrame) -> pd.DataFrame:
    keys = ["source", "reading", "cv", "x_s", "period"]
    g = S.groupby(keys, sort=False)
    mean = g[KEEP].mean()
    out = mean.rename(columns={"per_share_ci95_c_lo": "per_share_ci95_lo_c", "per_share_ci95_c_hi": "per_share_ci95_hi_c"})
    out["n_seeds"] = g.size()
    out["n_seeds_with_trades"] = g.n_trades.apply(lambda s: int((s > 0).sum()))
    out["pnl_per_day_usd_sd"] = g.pnl_per_day_usd.std(ddof=0)
    out["pnl_per_day_usd_seed_p2_5"] = g.pnl_per_day_usd.quantile(0.025)
    out["pnl_per_day_usd_seed_p97_5"] = g.pnl_per_day_usd.quantile(0.975)
    out["per_share_c_sd"] = g.per_share_c.std(ddof=0)
    out["sharpe_ann_sd"] = g.sharpe_ann.std(ddof=0)
    out = out.reset_index()
    out.insert(0, "label", LABEL)
    out["grid"] = [grid_tag(s, x, c) for s, x, c in zip(out.source, out.x_s, out.cv)]
    out["x_kind"] = out.source.str.replace("_trimR", "").map({"video": "video delay V (s)", "official": "stamp lag (s)",
                                    "fastfeed": "feed lead over the umpire stamp D (s), stamp lag 2.0"})
    return out


def first_crossing(xs: np.ndarray, ys: np.ndarray) -> float:
    """First x where y goes from > 0 to <= 0 (linear interpolation). -inf if y <= 0 at the first x,
    +inf if y stays > 0."""
    if not np.isfinite(ys[0]) or ys[0] <= 0:
        return -math.inf
    for i in range(1, len(xs)):
        if ys[i] <= 0:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return float(x0 + (x1 - x0) * y0 / (y0 - y1))
    return math.inf


def _fmt_be(v: float, xmax: float, what: str = "P&L") -> str | float:
    if v == -math.inf:
        return f"none: {what} <= 0 already at V = 0 (the venue camera)"
    if v == math.inf:
        return f"none: {what} > 0 at every V up to {xmax:g} s"
    return round(v, 3)


def breakeven(S: pd.DataFrame, Sm: pd.DataFrame, n_boot: int = 2000) -> dict:
    """Break-even video delay per reading and period: the V where $/day crosses 0 (first crossing, linear
    interpolation on the V grid 0-3 s at 0.05 s, then 5, 10, 20, 40, 60).
      seed-mean curve        the crossing of the 20-seed mean $/day curve (the estimate)
      seed_bootstrap_ci95    2.5-97.5 % of that crossing over 2,000 resamples of the 20 seeds (Monte Carlo
                             uncertainty of the 20-seed estimate; not data uncertainty)
      per_seed_range95       2.5-97.5 % of the 20 per-seed crossings (spread of single draws of the model);
                             a seed already <= 0 at V = 0 counts as 0, one never crossing as the grid max
    Also the V range where the per-share match-bootstrap CI (seed means) still contains 0."""
    out = {}
    rng = np.random.default_rng(0)
    for rd in READINGS:
        out[rd] = {}
        for p in PERIODS:
            s = S[(S.source == "video") & (S.cv == "own120") & (S.reading == rd) & (S.period == p)]
            piv = s.pivot_table(index="x_s", columns="seed", values="pnl_per_day_usd").sort_index()
            xs = piv.index.to_numpy(float)
            Y = piv.to_numpy(float)                                  # (n_x, n_seeds)
            per_seed = np.array([first_crossing(xs, Y[:, k]) for k in range(Y.shape[1])])
            m = Sm[(Sm.source == "video") & (Sm.cv == "own120") & (Sm.reading == rd) & (Sm.period == p)].sort_values("x_s")
            mx = m.x_s.to_numpy(float)
            be_mean = first_crossing(mx, m.pnl_per_day_usd.to_numpy(float))
            idx = rng.integers(0, Y.shape[1], (n_boot, Y.shape[1]))
            boot = np.array([first_crossing(xs, Y[:, i].mean(1)) for i in idx])
            rec = {"breakeven_V_s_seed_mean_curve": _fmt_be(be_mean, xs.max()),
                   "n_seeds": int(len(per_seed)),
                   "n_seeds_negative_at_V0": int((per_seed == -math.inf).sum()),
                   "n_seeds_never_cross": int((per_seed == math.inf).sum())}
            if np.isfinite(be_mean):
                bc = np.clip(boot, 0.0, xs.max())
                rec["breakeven_V_s_seed_bootstrap_ci95"] = [round(float(np.percentile(bc, 2.5)), 3),
                                                            round(float(np.percentile(bc, 97.5)), 3)]
                rec["bootstrap_share_no_crossing"] = round(float((~np.isfinite(boot)).mean()), 4)
            if rec["n_seeds_negative_at_V0"] < len(per_seed):
                ps = np.clip(per_seed, 0.0, xs.max())
                rec["breakeven_V_s_per_seed_median"] = round(float(np.median(ps)), 3)
                rec["breakeven_V_s_per_seed_range95"] = [round(float(np.percentile(ps, 2.5)), 3),
                                                         round(float(np.percentile(ps, 97.5)), 3)]
                rec["breakeven_V_s_per_seed_min_max"] = [round(float(ps.min()), 3), round(float(ps.max()), 3)]
            # sign determined by the per-share match-bootstrap CI (seed-mean bounds)
            lo, hi = m.per_share_ci95_lo_c.to_numpy(float), m.per_share_ci95_hi_c.to_numpy(float)
            v_sig_pos = first_crossing(mx, lo)            # edge significantly > 0 for V below this
            v_sig_neg = first_crossing(mx, hi)            # edge significantly < 0 from here on (if it stays)
            rec["per_share_ci_lower_bound_crosses_0_at_V_s"] = _fmt_be(v_sig_pos, xs.max(), "per-share CI lower bound")
            rec["per_share_ci_upper_bound_crosses_0_at_V_s"] = _fmt_be(v_sig_neg, xs.max(), "per-share CI upper bound")
            out[rd][p] = rec
    return out


def timing_diagnostics(c: dict) -> dict:
    """Two facts about the measured reprice timing that shape the curve (descriptive, live day only)."""
    m1 = pd.read_csv(T.LAT / "m1_points.csv")
    m1 = m1[m1.ok == True]  # noqa: E712
    ms = (m1.t_book % 1000).to_numpy()
    pool = c["pools"]["D>=3c"]
    R = pool.R.to_numpy()
    # a lead-0 call from a European venue arrives T_INF + 10 ms + gateway + 1 s after the bounce; under the
    # tournament reading it fills iff t_reprice = R + stamp lag >= that, i.e. R >= thr + V
    thr = round(T.T_INF + T.REGION_MS["Europe"] / 1000 + T.GATEWAY + 1.0 - T.CORRECTED.stamp_lag, 3)
    return {
        "reprice_ms_within_second": {
            "share_50_100ms": round(float(((ms >= 50) & (ms < 100)).mean()), 4),
            "uniform_expectation": 0.05, "n": int(len(ms)),
            "note": "A third of book reprices land 50-100 ms after a whole UTC second (all 482 live points). "
                    "Consistent with the venue releasing delayed orders on a 1 s clock (not verified). If so, an "
                    "order's real arrival is quantised to that clock and the continuous-delay model is only "
                    "approximate below ~1 s; it is why 50 ms of delay costs a third of the IS P&L here."},
        "R_cluster_just_above_threshold": {
            "threshold_R_s_lead0_europe_V0": thr,
            "share_pool_R_in_first_50ms_above": round(float(((R >= thr) & (R < thr + 0.05)).mean()), 4),
            "share_pool_R_above": round(float((R >= thr).mean()), 4),
            "note": f"Under the tournament reading at stamp lag 2.0 a lead-0 Europe call fills iff R >= {thr} s + V; "
                    "the share of the 265 pool points in the first 50 ms above that line is the drop seen at "
                    "V = 0.05 (the 1 s clock above)."},
        "R_outliers": {"R_gt_3s": sorted(round(float(x), 2) for x in R[R > 3]), "n_pool": int(len(R)),
                       "note": "Three pool points have R of 8-18 s (probably mismatched reprices). A tournament that "
                               "draws one fills even at V = 10 s; they drive the upper tail of the per-seed "
                               "break-evens, not the seed-mean curve."},
    }


def interp_log(m: pd.DataFrame, x: float, col: str) -> float:
    xs, ys = m.x_s.to_numpy(float), m[col].to_numpy(float)
    if x <= xs[0]:
        return float(ys[0])
    if x in xs:
        return float(ys[xs == x][0])
    xs1 = np.where(xs > 0, xs, np.nan)
    ok = np.isfinite(xs1)
    return float(np.interp(np.log(x), np.log(xs1[ok]), ys[ok]))


def source_readoff(Sm: pd.DataFrame) -> list[dict]:
    rows = []
    for src in SOURCES:
        rec = {k: src[k] for k in ("key", "name", "band_s", "basis", "cites")}
        rec["pnl"] = {}
        for rd in READINGS:
            if src["source"] == "official" and rd == "stamp_calibrated":
                continue
            rec["pnl"][rd] = {}
            for p in PERIODS:
                if src["source"] == "video":
                    m = Sm[(Sm.source == "video") & (Sm.cv == "own120") & (Sm.reading == rd) & (Sm.period == p)].sort_values("x_s")
                    pts = {f"{x:g}": {"usd_per_day": round(interp_log(m, x, "pnl_per_day_usd"), 1),
                                      "per_share_c": round(interp_log(m, x, "per_share_c"), 2)}
                           for x in src["read_at_s"]}
                    inb = m[(m.x_s >= src["band_s"][0]) & (m.x_s <= src["band_s"][1])]
                    rng = [round(float(inb.pnl_per_day_usd.min()), 1), round(float(inb.pnl_per_day_usd.max()), 1)]
                else:
                    m = Sm[(Sm.source == "official") & (Sm.reading == rd) & (Sm.period == p)].sort_values("x_s")
                    pts = {f"{r.x_s:g}": {"usd_per_day": round(r.pnl_per_day_usd, 1),
                                          "per_share_c": None if pd.isna(r.per_share_c) else round(r.per_share_c, 2)}
                           for r in m.itertuples()}
                    rng = [round(float(m.pnl_per_day_usd.min()), 1), round(float(m.pnl_per_day_usd.max()), 1)]
                rec["pnl"][rd][p] = {"at": pts, "usd_per_day_range_in_band": rng}
        rows.append(rec)
    return rows


# ------------------------------------------------------------------------------------------- tables
def _c(x, nd=2):
    return "n/a" if x is None or not np.isfinite(x) else f"{x:+.{nd}f}"


def _usd(x):
    return "n/a" if not np.isfinite(x) else ("−" if x < 0 else "") + f"${abs(x):,.0f}"


def md_tables(Sm: pd.DataFrame) -> str:
    lines = []

    def row_cells(r):
        ci = (f"[{r.per_share_ci95_lo_c:+.2f}, {r.per_share_ci95_hi_c:+.2f}]"
              if np.isfinite(r.per_share_ci95_lo_c) else "")
        sh = "n/a" if not np.isfinite(r.sharpe_ann) else f"{r.sharpe_ann:.1f}"
        return (f"{_c(r.per_share_c)} {ci} | {_usd(r.pnl_per_day_usd)} ± {r.pnl_per_day_usd_sd:,.0f} | {sh} | "
                f"{r.fill_rate * 100:.1f} % | {r.calls_share_before_reprice * 100:.1f} %")

    hdr = ("| V (s) | IS net c/share [CI] | IS $/day ± SD | IS Sharpe | IS fill | IS calls before reprice | "
           "OOS net c/share [CI] | OOS $/day ± SD | OOS Sharpe | OOS fill | OOS calls before reprice |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|")
    for cv in ("own120", "own120_pess"):
        for rd in READINGS:
            lines.append(f"\n### video + CV ({cv}), reading: {READ_LABEL[rd]}\n\n{hdr}")
            xs = V_CHECK + V_MAIN + V_EXT
            for x in xs:
                a = Sm[(Sm.source == "video") & (Sm.cv == cv) & (Sm.reading == rd) & (Sm.x_s == x)]
                ri, ro = a[a.period == "IS"].iloc[0], a[a.period == "burned_OOS"].iloc[0]
                tag = ((" (own camera: revised primary)" if (cv, rd) == ("own120", "tournament") else " (own camera)")
                       if x == 0 else (" (ext.)" if x in V_EXT else ""))
                lines.append(f"| {x:g}{tag} | {row_cells(ri)} | {row_cells(ro)} |")
    lines.append(f"\n### ROBUSTNESS video + CV (own120), pool without R > 3 s, reading: {READ_LABEL['tournament']}\n\n{hdr}")
    for x in V_CHECK + V_MAIN + V_EXT:
        a = Sm[(Sm.source == "video_trimR") & (Sm.x_s == x)]
        lines.append(f"| {x:g} | {row_cells(a[a.period == 'IS'].iloc[0])} | {row_cells(a[a.period == 'burned_OOS'].iloc[0])} |")
    for src, xl in (("official", "stamp lag (s)"), ("fastfeed", "feed lead D over the stamp (s), lag 2.0"),
                    ("official_trimR", "stamp lag (s), pool without R > 3 s")):
        for rd in ("tournament", "stamp"):
            lines.append(f"\n### {src}, reading: {READ_LABEL[rd]}\n\n" + hdr.replace("V (s)", xl))
            a0 = Sm[(Sm.source == src) & (Sm.reading == rd)]
            for x in sorted(a0.x_s.unique()):
                a = a0[a0.x_s == x]
                ri, ro = a[a.period == "IS"].iloc[0], a[a.period == "burned_OOS"].iloc[0]
                lines.append(f"| {x:g} | {row_cells(ri)} | {row_cells(ro)} |")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------- figure
def figure(Sm: pd.DataFrame, be: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    ink, ink2, grid_c, surf = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    col = {"IS": "#2a78d6", "burned_OOS": "#eb6834"}
    name = {"IS": "in sample", "burned_OOS": "burned OOS (not blind)"}
    plt.rcParams.update({"text.usetex": False, "font.size": 10, "axes.edgecolor": grid_c, "axes.labelcolor": ink2,
                         "xtick.color": ink2, "ytick.color": ink2, "figure.facecolor": surf,
                         "axes.facecolor": surf, "savefig.facecolor": surf})
    fig, (axb, ax) = plt.subplots(2, 1, figsize=(10.5, 6.9), sharex=True,
                                  gridspec_kw={"height_ratios": [1.0, 4], "hspace": 0.04})
    xlo, xhi = 0.04, 75.0
    # ---- source bands: a shaded ruler above the plot (the bands overlap, so one row each)
    bands = [(s["name"], s["band_s"]) for s in SOURCES if s["source"] == "video"]
    tints = ["#d9d8d3", "#cfe0f5", "#e6e1d3", "#efd9cf"]
    for i, ((nm, (a, b)), t) in enumerate(zip(bands, tints)):
        y = len(bands) - 1 - i
        a = max(a, xlo)
        axb.barh(y, b - a, left=a, height=0.78, color=t, edgecolor="none")
        rng = f"≤ {b:g} s" if a <= xlo else f"{a:g}–{b:g} s"
        axb.text(max(a, xlo) * 1.06, y, f"{nm}  {rng}", va="center", ha="left", fontsize=8.6, color=ink)
    axb.set_ylim(-0.6, len(bands) - 0.4)
    axb.set_yticks([])
    axb.tick_params(axis="x", length=0)
    for sp in axb.spines.values():
        sp.set_visible(False)
    axb.set_title("Tier-0 without a courtside camera: $/day vs feed delay (revised primary model)",
                  color=ink, loc="left", fontsize=11.5)
    # ---- P&L: headline reading (solid, ±1 SD band over 20 seeds); stamp-noise reading (dashed)
    sel = lambda rd, p: Sm[(Sm.source == "video") & (Sm.cv == "own120") & (Sm.reading == rd) & (Sm.period == p)  # noqa: E731
                           & (Sm.x_s >= 0.05)].sort_values("x_s")
    for p in PERIODS:
        m = sel("tournament", p)
        ax.fill_between(m.x_s, m.pnl_per_day_usd - m.pnl_per_day_usd_sd, m.pnl_per_day_usd + m.pnl_per_day_usd_sd,
                        color=col[p], alpha=0.13, lw=0)
        ax.plot(m.x_s, m.pnl_per_day_usd, color=col[p], lw=2.1)
        ms = sel("stamp", p)
        ax.plot(ms.x_s, ms.pnl_per_day_usd, color=col[p], lw=1.1, ls=(0, (4, 3)))
        mo = Sm[(Sm.source == "official") & (Sm.reading == "tournament") & (Sm.period == p)].sort_values("x_s")
        ax.plot(mo.x_s, mo.pnl_per_day_usd, ls="none", marker="D", ms=6.5, mfc=col[p], mec=surf, mew=1.5, zorder=4)
        b = be["tournament"][p]
        v = b["breakeven_V_s_seed_mean_curve"]
        if isinstance(v, float):
            ci = b.get("breakeven_V_s_seed_bootstrap_ci95", [v, v])
            ax.errorbar([v], [0], xerr=[[max(v - ci[0], 0)], [max(ci[1] - v, 0)]], fmt="o", ms=7, color=col[p],
                        mec=surf, mew=1.5, capsize=3, lw=1.6, zorder=5)
            ax.annotate(f"{name[p]}: break-even {v:.2f} s\n(95 % CI over seeds {ci[0]:.2f}–{ci[1]:.2f} s)",
                        (v, 0), xytext=(1.7, 46 if p == "IS" else 29), textcoords="data", fontsize=8.4,
                        color=ink, ha="left", va="center",
                        arrowprops=dict(arrowstyle="-", color=col[p], lw=0.8, shrinkA=2, shrinkB=5))
    ax.axhline(0, color=ink2, lw=0.9, zorder=1)
    ax.axvspan(xlo, 0.05, color="#d9d8d3", alpha=0.5, lw=0, zorder=0)
    ax.set_xscale("log")
    ax.set_xlim(xlo, xhi)
    ticks = [0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 40, 60]
    ax.set_xticks(ticks, [f"{t:g}" for t in ticks])
    ax.minorticks_off()
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.grid(axis="y", color=grid_c, lw=0.6)
    ax.set_xlabel("feed delay V (s, log scale): how long after the bounce our CV sees it")
    ax.set_ylabel("$ per day (20-seed mean)")
    handles = [Line2D([], [], color=col["IS"], lw=2.1, label="in sample"),
               Line2D([], [], color=col["burned_OOS"], lw=2.1, label="burned OOS (not blind)"),
               Line2D([], [], color=ink2, lw=2.1, label="reprice timing per tournament (headline); band ±1 SD"),
               Line2D([], [], color=ink2, lw=1.1, ls=(0, (4, 3)), label="timing spread = stamp noise (loses at every V)"),
               Line2D([], [], color=ink2, ls="none", marker="D", ms=6, label="official point feed, no CV (x = stamp lag)")]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="upper right")
    fig.text(0.01, 0.012, LABEL + ".\nCall = bounce − CV lead + V + 20 ms inference + venue→London network + 1 s "
             "venue order delay; fills priced from the measured live book. Own 120 fps CV model,\nstamp lag 2.0 s, "
             "φ 0.5, 10 matches/day, p_event 0.95, net cap 100. Source bands: cited vendor claims and measurements "
             "(research/v2/tier0/LATENCY_SWEEP.md).", color=ink2, fontsize=7.6, ha="left")
    fig.subplots_adjust(left=0.075, right=0.985, top=0.95, bottom=0.17)
    fig.savefig(path, dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------------------------------------- main
def headline_check(Sm: pd.DataFrame) -> dict:
    pub = json.loads((OUT / "results.json").read_text())["headline"]
    out = {}
    for p in PERIODS:
        r = Sm[(Sm.source == "video") & (Sm.cv == "own120") & (Sm.reading == "tournament") & (Sm.x_s == 0) & (Sm.period == p)].iloc[0]
        out[p] = {"sweep_V0_usd_per_day": round(float(r.pnl_per_day_usd), 4),
                  "published_headline_usd_per_day": pub[p]["mean"]["pnl_per_day_usd"],
                  "sweep_V0_per_share_c": round(float(r.per_share_c), 4),
                  "published_per_share_c": pub[p]["mean"]["per_share_c"]}
        out[p]["identical"] = bool(abs(out[p]["sweep_V0_usd_per_day"] - out[p]["published_headline_usd_per_day"]) < 1e-3)
    return out


def write_outputs(S: pd.DataFrame, meta: dict) -> dict:
    Sm = summarise(S)
    be = breakeven(S, Sm)
    order = {"video": 0, "official": 1, "fastfeed": 2}
    Sm = Sm.sort_values(["source", "cv", "reading", "period", "x_s"], key=lambda s: s.map(order) if s.name == "source" else s,
                        kind="stable").reset_index(drop=True)
    cols = ["label", "source", "x_kind", "x_s", "reading", "cv", "period", "grid", "n_seeds", "n_seeds_with_trades",
            "per_share_c", "per_share_ci95_lo_c", "per_share_ci95_hi_c", "per_share_c_sd", "pnl_per_day_usd",
            "pnl_per_day_usd_sd", "pnl_per_day_usd_seed_p2_5", "pnl_per_day_usd_seed_p97_5", "sharpe_ann",
            "sharpe_ann_sd", "fill_rate", "calls_share_before_reprice", "calls_share_in_decay_window",
            "calls_share_too_late", "calls_median_tau_s", "n_calls", "n_trades", "wrong_call_share_of_trades",
            "pnl_usd", "pnl_correct_usd", "pnl_wrong_usd", "max_dd_usd", "worst_day_usd", "capital_usd", "days"]
    Sm[cols].round(5).to_csv(OUT / "latency_sweep.csv", index=False)

    def cellrec(r):
        return {"net_c_per_share": round(r.per_share_c, 3) if np.isfinite(r.per_share_c) else None,
                "net_c_per_share_ci95": [round(r.per_share_ci95_lo_c, 3), round(r.per_share_ci95_hi_c, 3)]
                if np.isfinite(r.per_share_ci95_lo_c) else None,
                "usd_per_day": round(r.pnl_per_day_usd, 2), "usd_per_day_sd": round(r.pnl_per_day_usd_sd, 2),
                "usd_per_day_seed_ci95": [round(r.pnl_per_day_usd_seed_p2_5, 2), round(r.pnl_per_day_usd_seed_p97_5, 2)],
                "sharpe_ann": round(r.sharpe_ann, 2) if np.isfinite(r.sharpe_ann) else None,
                "fill_rate": round(r.fill_rate, 4), "share_calls_before_reprice": round(r.calls_share_before_reprice, 4),
                "n_trades": round(r.n_trades, 1), "wrong_call_share_of_trades": round(r.wrong_call_share_of_trades, 4)
                if np.isfinite(r.wrong_call_share_of_trades) else None}

    def table(source, cv, rd, xs):
        out = {}
        for x in xs:
            a = Sm[(Sm.source == source) & (Sm.cv == cv) & (Sm.reading == rd) & (Sm.x_s == x)]
            out[f"{x:g}"] = {p: cellrec(a[a.period == p].iloc[0]) for p in PERIODS}
        return out

    res = {
        "label": LABEL, "never_claim": NEVER,
        "what": "Revised primary tier-0 counterfactual (src/tier0.py CORRECTED) with the courtside camera replaced "
                "by realistic information sources: video + our CV delayed by V, or the official point feed with no "
                "CV. Nothing fitted or chosen; burned OOS is not blind.",
        "model": {"video": "call = bounce - CV lead + V + 20 ms inference; + venue->London network + 2 ms gateway "
                           "+ the venue's order delay (1 s). V = 0 is the revised primary.",
                  "official": "call at t_stamp = bounce + stamp lag, no CV, precision 1; tau = R - transit, R per "
                              "tournament (tournament reading) or per point (stamp reading); stamp lag cancels.",
                  "fastfeed": "official with the call D s before the stamp (extension; precision 1 is generous).",
                  "readings": READ_LABEL, "revised_primary": {k: (v if not isinstance(v, float) or np.isfinite(v) else str(v))
                                                               for k, v in asdict(T.CORRECTED).items()}},
        "grids": {"V_main_s": V_MAIN, "V_check_s": V_CHECK, "V_extension_s": V_EXT, "V_dense_s": "0-3 s step 0.05",
                  "stamp_lag_s": LAGS, "fastfeed_D_s": FAST_D, "seeds": SEEDS,
                  "cv_sensitivity": "own120_pess (no early calls, 50 ms inference): betting video is 25-50 fps, "
                                    "not 120 fps"},
        "check_V0_equals_published_headline": headline_check(Sm),
        "breakeven_video_delay": be,
        "video_own120": {rd: table("video", "own120", rd, V_CHECK + V_MAIN + V_EXT) for rd in READINGS},
        "video_cv_pessimistic": {rd: table("video", "own120_pess", rd, V_CHECK + V_MAIN + V_EXT) for rd in READINGS},
        "official_feed_no_cv": {rd: table("official", "point_feed", rd, LAGS) for rd in ("tournament", "stamp")},
        "fast_feed_extension": {rd: table("fastfeed", "point_feed", rd, FAST_D) for rd in ("tournament", "stamp")},
        "robustness_pool_without_R_gt_3s": {
            "note": "Live pool without its 3 points with R = 8.3 / 17.5 / 18.1 s (probably mismatched reprices); 262 "
                    "points. Official feed at stamp lag 2.0 (lag cancels); video at the headline reading.",
            "official_feed_no_cv": {rd: table("official_trimR", "point_feed", rd, [2.0]) for rd in ("tournament", "stamp")},
            "video_own120_tournament": table("video_trimR", "own120", "tournament", V_CHECK + V_MAIN + V_EXT)},
        "sources": source_readoff(Sm),
        "timing_diagnostics": timing_diagnostics(ctx()),
        "files": {"summary_csv": "results/tier0/latency_sweep.csv", "per_seed_csv": "results/tier0/latency_sweep_seeds.csv",
                  "figure": "results/tier0/fig_pnl_vs_feed_latency.png", "doc": "research/v2/tier0/LATENCY_SWEEP.md",
                  "script": "scripts/tier0_latency_sweep.py"},
        "run": meta,
    }
    (OUT / "latency_sweep.json").write_text(json.dumps(res, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    figure(Sm, be, OUT / "fig_pnl_vs_feed_latency.png")
    return {"Sm": Sm, "be": be, "res": res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 4)))
    ap.add_argument("--seeds", type=int, default=SEEDS)
    ap.add_argument("--figures", action="store_true", help="redraw + print tables from results/tier0/latency_sweep*")
    ap.add_argument("--smoke", action="store_true", help="2 seeds, IS only, a few cells; print, write nothing")
    a = ap.parse_args()
    print(LABEL)
    if a.figures:
        S = pd.read_csv(OUT / "latency_sweep_seeds.csv")
        meta = json.loads((OUT / "latency_sweep.json").read_text()).get("run", {})
        r = write_outputs(S, meta)
        print(md_tables(r["Sm"]))
        print(json.dumps(r["be"], indent=1))
        return
    if a.smoke:
        _init()
        for j in [("video", "tournament", 0.0, "own120", "IS", 0), ("video", "tournament", 1.0, "own120", "IS", 0),
                  ("official", "tournament", 2.0, "point_feed", "IS", 0), ("official", "stamp", 1.0, "point_feed", "IS", 0),
                  ("official", "stamp", 3.0, "point_feed", "IS", 0), ("fastfeed", "stamp", 1.0, "point_feed", "IS", 0)]:
            t0 = time.time()
            r = _job(j)
            print(j, {k: round(r[k], 3) for k in ("pnl_per_day_usd", "per_share_c", "fill_rate",
                                                  "calls_share_before_reprice", "n_trades")}, f"{time.time() - t0:.2f}s")
        return
    with open(ROOT / "results/oos_peeks.log", "a") as fh:
        fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} tier0 latency sweep on burned OOS "
                 f"(non-blind, labelled; no parameter chosen)\n")
    J = jobs(a.seeds)
    t0 = time.time()
    print(f"{len(J)} runs on {a.workers} workers", flush=True)
    with ProcessPoolExecutor(a.workers, mp_context=mp.get_context("spawn"), initializer=_init) as ex:
        rows = list(ex.map(_job, J, chunksize=8))
    S = pd.DataFrame(rows)
    S.insert(0, "label", LABEL)
    OUT.mkdir(parents=True, exist_ok=True)
    S.round(6).to_csv(OUT / "latency_sweep_seeds.csv", index=False)
    meta = {"host": socket.gethostname(), "workers": a.workers, "n_runs": len(J), "seconds": round(time.time() - t0, 1),
            "slurm_job": os.environ.get("SLURM_JOB_ID"), "utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "python": sys.version.split()[0]}
    r = write_outputs(S, meta)
    print(md_tables(r["Sm"]))
    print(json.dumps(r["be"], indent=1))
    print(json.dumps(r["res"]["check_V0_equals_published_headline"], indent=1))
    print("done", meta)


if __name__ == "__main__":
    main()
