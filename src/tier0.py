"""TIER-0 COUNTERFACTUAL. What would a courtside camera + our own CV model + a licensed live point
feed + a London-colocated gateway have earned on Polymarket tennis moneylines?

    ASSUMED: licensed live feed + courtside camera, NOT purchased; parameters from our measurements.

No live ATP/WTA feed was bought or used, and no footage of these matches exists in this repo. The
historical prices, outcomes, fees and venue delays are real (Polymarket public tapes). Everything that
describes the tier-0 trader (when it knows the point, how fast its order reaches the book, how much
stale depth it gets) is a model built from our own measurements plus the stated assumptions:

  * timing   research/v2/latency/out/{m1_points,stale_depth}.csv: book reprice minus the official WTA
             point stamp, and stale depth before the reprice, per live point (2026-10-03, 1 s / 5 % regime)
  * stamp    t_stamp - t_bounce is NOT measured: a grid, plus a calibration inferred from the fast tier's
             prints (calibrate_stamp_lag)
  * CV       results/tracking/summary.json (real 120 fps table-tennis video) and
             results/hawkeye_tennis_calls.csv (340 fps physics Monte Carlo)
  * endings  Jeff Sackmann's Match Charting Project, 2020s point files (CC BY-NC-SA 4.0)
  * network  London one-way latency by venue region: an assumption (REGION_MS)

TRADE SET (selected on realised market moves). The calls are the historical >= 4c jumps found by
src.tiers.jump_onsets, which compares the VWAP of the NEXT 10 s with the previous 60 s. A tier-0 trader
with the point outcome and a Markov fair value (src/markov.py) would pick a DIFFERENT set: on the live day
only 63 % of detector jumps map to one same-direction official point, 42 % of detector windows hold 2+
points, and a third of matched single-point moves are < 4c (research/v2/tier0/verify_out). So the trade
set is not ex-ante; per-share P&L is reported by jump-size bucket to show how much rides on large moves.

The parameters are pre-registered in research/v2/tier0/PREREG.md; nothing is fitted to P&L. The verifier
corrections (live-book fill price, limit-order fills, timing readings, literal coverage, stale-price
correction, multi-seed reporting) are logged in research/v2/tier0/DEVIATIONS.md and selected with
Scenario fields; `CORRECTED` is the headline configuration, `PRIMARY` the pre-registered one.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ASSUMED = ("COUNTERFACTUAL - assumed: licensed live feed + courtside camera, not purchased; "
           "parameters from our measurements")
OUT = ROOT / "results" / "tier0"
INPUTS = OUT / "inputs"
LAT = ROOT / "research/v2/latency/out"
MCP_DIR = ROOT / "data/external/mcp"
MCP_URL = "https://github.com/JeffSackmann/tennis_MatchChartingProject"
OOS_START = pd.Timestamp("2026-08-25 14:15", tz="UTC")

# ------------------------------------------------------------------------------------------ fixed
T_INF = 0.020          # CV inference latency, s (assumption from the task)
T_INF_PESS = 0.050     # pessimistic-camera inference latency, s
GATEWAY = 0.002        # London co-located gateway, s (inferred; see docs/NOTE.md)
LOCK_S = 4 * 3600      # capital lock per position (as v2)
CAPITAL_MULT = 3       # capital = 3 x peak locked (as v2)
ZONE = (0.05, 0.95)    # trade only when the token's stale price is in this band (as v2)
DECAY_S = 0.5          # stale depth is gone 0.5 s after the reprice (measured: ~$0 at +0.5 s)
JUMP_MIN = 0.04        # the historical jump detector's threshold (src.tiers.jump_onsets)
# Cumulative-edge grid (shares) for the live-book fill price: E(N) = $ edge vs the post-reprice mid of the
# first N resting stale shares, per live point and snapshot (DEVIATIONS V1).
EDGE_N = (25, 50, 100, 200, 400, 800, 1600, 3200, 6400, 12800)
EDGE_SNAPS = (("2", 2000), ("1", 1000), ("025", 250))
# Measured stale-price correction (DEVIATIONS V4): on the 102 live detector jumps matched to an official
# point, `ref` overstates the edge vs the true quote mid just before the point by +0.56c mean / +0.49c median.
STALE_ADJ_MEASURED = 0.005
POST_W = 30.0          # post-jump price = VWAP of outcome-0 prints in [detect, detect + 30 s) (pricing only)

# One-way latency from the venue to London, ms. ASSUMPTION (not measured).
REGION_MS = {"Europe": 10, "Americas": 40, "Asia": 100, "Oceania": 140, "Africa": 80, "MiddleEast": 50,
             "unmapped": 100}
REGION_KEYS = {
    "Asia": ["china open", "jingshan", "guangzhou", "shanghai", "zhangjiagang", "korea open", "chengdu",
             "singapore", "hangzhou", "japan open", "japan women", "phan thiet", "bengaluru", "astana",
             "wuhan", "ningbo", "tokyo", "osaka", "almaty", "hong kong", "kaohsiung", "seoul", "busan",
             "jinan", "shenzhen", "zhuhai", "beijing", "pune", "chennai", "mumbai", "delhi", "taipei",
             "yokohama", "nonthaburi", "bangkok", "kuala lumpur", "manila", "jakarta", "tashkent",
             "ho chi minh", "hanoi", "jiujiang", "nanchang", "suzhou", "kyoto", "matsuyama", "kobe",
             "chongqing", "wuxi", "xi'an", "tianjin", "huzhou", "luzhou", "shymkent", "wuning", "jiangxi",
             "gwangju", "miyazaki", "pan pacific"],
    "Oceania": ["australian open", "brisbane", "adelaide", "auckland", "hobart", "sydney", "canberra",
                "perth", "melbourne", "playford", "bendigo", "traralgon", "burnie", "united cup", "asb classic"],
    "MiddleEast": ["doha", "dubai", "abu dhabi", "qatar", "jeddah", "riyadh"],
    "Africa": ["centurion", "johannesburg", "cape town", "pretoria", "abidjan"],
    "Americas": ["us open", "cincinnati", "national bank open", "canadian open", "citi", "winston-salem",
                 "vancouver", "newport", "tiburon", "columbus", "kingston", "sao paulo", "san diego",
                 "buenos aires", "curitiba", "memphis", "los cabos", "monterrey", "guadalajara", "quebec",
                 "cancun", "bloomfield", "tucuman", "brownsburg", "little rock", "lexington", "bogota",
                 "philadelphia", "barranquilla", "asuncion", "quito", "cary", "granby", "winnipeg",
                 "piracicaba", "tyler", "lincoln", "cordoba", "indian wells", "bnp paribas open", "miami",
                 "atlanta", "washington", "chicago", "cleveland", "charleston", "houston", "dallas",
                 "delray", "acapulco", "rio open", "santiago", "lima", "medellin", "cali", "mexico",
                 "toronto", "montreal", "champaign", "knoxville", "fairfield", "charlottesville", "austin",
                 "san francisco", "new york", "orlando", "boston", "denver", "phoenix", "rome, ga",
                 "puerto vallarta", "san luis potosi", "campinas", "florianopolis", "santa cruz",
                 "porto alegre", "salinas", "morelos", "concepcion", "guayaquil", "punta del este",
                 "sarasota", "tallahassee", "savannah", "drummondville", "calgary", "saguenay", "rancho santa fe",
                 "evansville", "edmond", "templeton", "spartanburg", "macon", "norman", "sao leopoldo", "santos",
                 "mexican open", "metepec", "merida", "atx open", "clay court championships", "colsanitas",
                 "argentina open", "chile open", "tigre", "midland"],
    # everything checked below that is not one of the above and is a European name
    "Europe": ["roland garros", "wimbledon", "hamburg", "eastbourne", "hsbc championships", "queen",
               "porto", "libema", "istanbul", "targu mures", "birmingham", "ilkley", "nottingham", "iasi",
               "prague", "augsburg", "rennes", "roehampton", "tulln", "genoa", "seville", "szczecin",
               "athens", "sion", "plovdiv", "biella", "como", "bari", "manacor", "cassis", "halle",
               "strasbourg", "grass court championships", "croatia open", "estoril", "geneva",
               "bad homburg", "mallorca", "swedish open", "generali open", "valencia", "swiss open",
               "stuttgart", "parma", "vicenza", "cattolica", "lyon", "bratislava", "brescia", "poznan",
               "troyes", "zug", "segovia", "san marino", "warsaw", "hagen", "todi", "caldas da rainha",
               "ankara", "cervia", "perugia", "heilbronn", "foggia", "prostejov", "modena", "figueira",
               "royan", "milan", "bastad", "contrexeville", "trieste", "braunschweig", "rome",
               "kitzbuehel", "kitzbuhel", "bunschoten", "tampere", "palermo", "liberec", "bonn", "antalya",
               "montreux", "ljubljana", "tolentino", "tropez", "kosice", "dublin", "liege", "cordenons",
               "grodzisk", "chisinau", "brasov", "pozoblanco", "makarska", "samsun", "adana", "mouilleron",
               "bordeaux", "paris", "internazionali", "zagreb", "oeiras", "madrid", "monte carlo",
               "barcelona", "munich", "rotterdam", "marseille", "montpellier", "vienna", "basel",
               "antwerp", "stockholm", "metz", "gijon", "sofia", "linz", "lugano", "budapest", "bucharest",
               "belgrade", "banja luka", "cluj", "hertogenbosch", "rosmalen", "nordic open",
               "european open", "gstaad", "umag", "tunis", "lalla meryem", "rabat", "marrakech", "berlin",
               "bad gastein", "lausanne", "helsinki", "copenhagen", "oslo", "eckental", "ismaning",
               "mauthausen", "split", "zadar", "maia", "lisbon", "braga", "murcia", "alicante", "girona",
               "sanxenxo", "bergamo", "napoli", "cagliari", "turin", "verona", "florence", "olbia",
               "orleans", "brest", "quimper", "pau", "saint-brieuc", "aix-en-provence", "lille",
               "vitoria", "bilbao", "ortisei", "koblenz", "lugano", "andorra", "glasgow", "manchester",
               "surbiton", "shrewsbury", "loughborough", "sheffield", "luxembourg", "le neubourg",
               "francavilla", "monza", "sardegna", "torino", "erste bank", "sables", "saint-malo", "bmw open",
               "bisbal", "transylvania", "rouen", "ostrava", "hellenic", "menorca", "barletta", "st. brieuc",
               "aix en provence", "sud de france", "porsche", "hassan ii"],
}
# "Laver Cup" moves every year; left unmapped (conservative 100 ms).


def region_of(league: str | None, title: str | None) -> str:
    s = f"{league or ''} | {(title or '').split(':')[0]}".lower()
    for reg in ("Asia", "Oceania", "MiddleEast", "Africa", "Americas", "Europe"):
        if any(k in s for k in REGION_KEYS[reg]):
            return reg
    return "unmapped"


# ================================================================================ measured inputs
def live_volumes(refresh: bool = False) -> pd.DataFrame:
    """Final Polymarket volume of the 9 live-day matches behind stale_depth.csv (public Gamma API,
    cached). Used only to scale the measured depth to each historical match's size."""
    f = INPUTS / "live_match_volumes.csv"
    if f.exists() and not refresh:
        return pd.read_csv(f)
    from src import polymarket as pm
    d = pd.read_csv(LAT / "stale_depth.csv")
    rows = []
    for s in d.slug.unique():
        for e in pm._get(pm.GAMMA, {"slug": s}):
            for r in pm._slim(e):
                rows.append({"slug": s, "title": r["title"], "volume": r["volume"], "start": r["start_time"],
                             "delay": r["seconds_delay"], "fee_rate": r["fee_rate"]})
    INPUTS.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(rows)
    out.to_csv(f, index=False)
    return out


def live_points(pool: str = "D>=3c") -> pd.DataFrame:
    """Measured per-point timing and stale depth (live 2026-10-03, 1 s delay / 5 % fee).

    R          t_reprice - t_stamp (s): book half-move reprice minus the official WTA point stamp
    usd_2/1/025/post  $ resting at prices better than the post-reprice mid, 2 s / 1 s / 0.25 s before
               and 0.5 s after the reprice (the side a point-winner buyer would lift)
    V_live     that match's final Polymarket volume (for depth scaling)"""
    d = pd.read_csv(LAT / "stale_depth.csv")
    m = pd.read_csv(LAT / "m1_points.csv", usecols=["slug", "n", "ok", "book_vs_T_s"])
    m = m[m.ok == True]  # noqa: E712
    x = d.merge(m[["slug", "n", "book_vs_T_s"]], on=["slug", "n"], how="left", validate="one_to_one")
    assert x.book_vs_T_s.notna().all() and len(x) == 482
    v = live_volumes().set_index("slug").volume
    x = x.assign(R=x.book_vs_T_s, usd_2=x.usd_pre2s, usd_1=x.usd_pre1s, usd_025=x.usd_pre, usd_post_=x.usd_post,
                 V_live=x.slug.map(v))
    assert x.V_live.notna().all()
    if pool == "D>=3c":
        x = x[x.D >= 0.03 - 1e-9]
    elif pool != "all":
        raise ValueError(pool)
    cols = ["slug", "n", "D", "R", "usd_2", "usd_1", "usd_025", "usd_post_", "V_live"]
    x = x[cols].rename(columns={"usd_post_": "usd_post"}).reset_index(drop=True)
    cur = live_edge_curve()
    ecols = [c for c in cur.columns if c.startswith(("S_", "E_", "SW_", "W_"))]
    x = x.merge(cur[["slug", "n"] + ecols], on=["slug", "n"], how="left", validate="one_to_one")
    assert x[ecols].notna().all().all()
    return x


def calibrate_stamp_lag(react=(0.20, 0.25, 0.30), net=(0.010, 0.067, 0.150), delay: float = 1.0) -> dict:
    """INFERENCE, not a measurement. Prints landing 0-0.5 s before the reprice were 98 % with the move.
    If they come from courtside humans who react `react` s after the ball lands, and whose orders pay the
    1 s venue delay plus `net` s of network, then for each such print
        t_reprice - t_bounce = (t_reprice - t_print) + delay + net + react
    and the unmeasured stamp lag is t_stamp - t_bounce = (t_reprice - t_bounce) - (t_reprice - t_stamp).
    Per point we use the EARLIEST with-move print in [-0.5, 0) s (the first informed order to land)."""
    t = pd.read_csv(LAT / "trades_around_reprice.csv")
    m = pd.read_csv(LAT / "m1_points.csv", usecols=["slug", "n", "ok", "book_vs_T_s"])
    m = m[m.ok == True]  # noqa: E712
    w = t[(t.dt_s >= -0.5) & (t.dt_s < 0)]
    share_with = float((w.usd * w.with_move).sum() / w.usd.sum())
    ww = w[w.with_move]
    first = ww.groupby(["slug", "n"]).dt_s.min().rename("dt_first").reset_index()
    first = first.merge(m[["slug", "n", "book_vs_T_s"]], on=["slug", "n"], how="inner")
    out = {"label": "INFERENCE (not measured): implied by fast-tier prints under the stated human-reaction "
                    "and network assumptions",
           "n_prints_with_move_in_[-0.5,0)": int(len(ww)), "share_usd_with_move": round(share_with, 3),
           "n_points": int(len(first)),
           "median_t_reprice_minus_first_print_s": round(float(-first.dt_first.median()), 3),
           "median_t_reprice_minus_t_stamp_s_these_points": round(float(first.book_vs_T_s.median()), 3),
           "grid": []}
    for r in react:
        for nt in net:
            tb = -first.dt_first + delay + nt + r          # t_reprice - t_bounce per point
            lag = tb - first.book_vs_T_s                    # t_stamp - t_bounce per point
            out["grid"].append({"react_s": r, "net_s": nt,
                                "t_reprice_minus_t_bounce_median_s": round(float(tb.median()), 3),
                                "stamp_lag_median_s": round(float(lag.median()), 3),
                                "stamp_lag_iqr_s": [round(float(lag.quantile(.25)), 3),
                                                    round(float(lag.quantile(.75)), 3)]})
    c = next(g for g in out["grid"] if g["react_s"] == 0.25 and g["net_s"] == 0.067)
    out["central"] = {"react_s": 0.25, "net_s": 0.067, "stamp_lag_s": c["stamp_lag_median_s"],
                      "t_reprice_minus_t_bounce_s": c["t_reprice_minus_t_bounce_median_s"]}
    lags = [g["stamp_lag_median_s"] for g in out["grid"]]
    out["range_over_assumptions_s"] = [min(lags), max(lags)]
    return out


def live_edge_curve(refresh: bool = False) -> pd.DataFrame:
    """MEASURED fill prices (DEVIATIONS V1, V2), from the live book replay of research/v2/latency (public
    CLOB websocket, 2026-10-03), for every live point with m1_points ok == True, 2 s / 1 s / 0.25 s before
    the reprice. m_new = mid at t_reprice + 3 s (as stale_depth.csv).
      correct side  levels a buyer of the point-WINNER's token lifts at prices better than m_new:
                    S_<snap> = all such shares, E_<snap>_<N> = $ gross edge vs m_new of the first min(N, S)
                    shares, E_<snap>_all = all of them (= stale_depth.csv edge_usd, checked).
      wrong side    levels a buyer of the point-LOSER's token takes (the winner token's bids, best first):
                    SW_<snap> = shares in the book, W_<snap>_<N> = $ loss vs m_new of the first min(N, SW).
    The verifier's first-100/200 numbers (verify_out/live_first_shares.csv) are a subset and match."""
    f = INPUTS / "live_edge_curve.csv"
    if f.exists() and not refresh:
        cur = pd.read_csv(f)
        if "W_2_100" in cur:
            return cur
    import sys
    sys.path.insert(0, str(ROOT / "research/v2/latency"))
    import load as L  # noqa: E402
    m1 = pd.read_csv(LAT / "m1_points.csv")
    meta = L.load_meta()
    ev = L.events_table(meta)
    e = ev[ev.slug.isin(set(m1.slug))].drop_duplicates("slug").set_index("slug")
    books = L.Books(set(e.tok0) | set(e.tok1), set(e.tok0), dict(zip(meta.ra, meta.tok)))
    P = m1[m1.ok == True]  # noqa: E712

    def cum(lv, N_grid):
        ed = np.array([x for x, _ in lv], float)
        sh = np.array([s for _, s in lv], float)
        cs = np.concatenate([[0.0], np.cumsum(sh)])
        ce = np.concatenate([[0.0], np.cumsum(sh * ed)])
        return float(cs[-1]), float(ce[-1]), [float(np.interp(min(N, cs[-1]), cs, ce)) if len(lv) else 0.0
                                              for N in N_grid]

    rows = []
    for r in P.itertuples():
        tok = e.loc[r.slug].tok0
        t, mid, _, _ = books.mid_series(tok)
        d = 1 if r.winner == 0 else -1
        j = np.searchsorted(t, r.t_book + 3000, "right") - 1
        m_new = mid[j] if j >= 0 else np.nan
        row = {"slug": r.slug, "n": r.n, "D": r.D, "m_new": m_new}
        for lab, dt in EDGE_SNAPS:
            bids, asks = books.book_at(tok, r.t_book - dt)
            if not np.isfinite(m_new):
                good, bad = [], []
            elif d > 0:   # winner = outcome 0: correct buys its asks; wrong sells into its bids
                good = [(m_new - p, s_) for p, s_ in sorted(asks.items()) if p < m_new]
                bad = [(m_new - p, s_) for p, s_ in sorted(bids.items(), reverse=True)]
            else:         # winner = outcome 1: correct sells outcome-0 bids above m_new; wrong lifts its asks
                good = [(p - m_new, s_) for p, s_ in sorted(bids.items(), reverse=True) if p > m_new]
                bad = [(p - m_new, s_) for p, s_ in sorted(asks.items())]
            S, Eall, Eg = cum(good, EDGE_N)
            SW, Wall, Wg = cum(bad, EDGE_N)
            row[f"S_{lab}"], row[f"E_{lab}_all"] = S, Eall
            row[f"SW_{lab}"], row[f"W_{lab}_all"] = SW, Wall
            for N, x, w in zip(EDGE_N, Eg, Wg):
                row[f"E_{lab}_{N}"] = x
                row[f"W_{lab}_{N}"] = w
        rows.append(row)
    out = pd.DataFrame(rows)
    INPUTS.mkdir(parents=True, exist_ok=True)
    out.to_csv(f, index=False)
    return out


def curve_per_share(curve: pd.DataFrame, side: str, idx: np.ndarray, n: np.ndarray, scale: np.ndarray,
                    tau: np.ndarray, after: str) -> np.ndarray:
    """Average per-share value (price units, vs the post-reprice mid) of the first n shares we take on
    sampled live point idx, its book scaled by `scale` (volume), tau s before the reprice.
    side 'E': gross edge of a correct call; side 'W': loss of a wrong call. Cumulative value is linear
    between the EDGE_N grid points. tau is interpolated across the 2 / 1 / 0.25 s snapshots like _depth.
    After the reprice (tau < 0): after='zero' -> 0; 'decay' -> linear from the 0.25 s value to 0 at +0.5 s;
    'spread' -> linear from the 0.25 s value to half the 1c spread at +0.5 s, then half the spread (a late
    wrong call buys the loser at its repriced quote)."""
    grid = np.array((0,) + EDGE_N, float)
    m = np.maximum(n / np.maximum(scale, 1e-9), 1e-6)          # shares in the live (unscaled) book
    k = np.clip(np.searchsorted(grid, m, "right") - 1, 0, len(grid) - 2)
    ar = np.arange(len(idx))
    sh_col = "S" if side == "E" else "SW"
    v = {}
    for lab, _ in EDGE_SNAPS:
        S = curve[f"{sh_col}_{lab}"].to_numpy()[idx]
        G = np.column_stack([np.zeros(len(idx))] + [curve[f"{side}_{lab}_{N}"].to_numpy()[idx] for N in EDGE_N])
        Gall = curve[f"{side}_{lab}_all"].to_numpy()[idx]
        lo, hi = grid[k], grid[k + 1]
        Gm = G[ar, k] + (G[ar, k + 1] - G[ar, k]) * (m - lo) / (hi - lo)
        Gm = np.where((m > S) | (m >= grid[-1]), Gall, Gm)
        v[lab] = np.where(S > 0, Gm / np.minimum(m, np.maximum(S, 1e-9)), 0.0)
    out = np.zeros(len(tau))
    a = tau >= 2.0
    out[a] = v["2"][a]
    b = (tau >= 1.0) & (tau < 2.0)
    out[b] = v["1"][b] + (v["2"][b] - v["1"][b]) * (tau[b] - 1.0)
    c = (tau >= 0.25) & (tau < 1.0)
    out[c] = v["025"][c] + (v["1"][c] - v["025"][c]) * (tau[c] - 0.25) / 0.75
    d = (tau >= 0) & (tau < 0.25)
    out[d] = v["025"][d]
    g = (tau >= -DECAY_S) & (tau < 0)
    h = tau < -DECAY_S
    if after == "decay":
        out[g] = v["025"][g] * (1 + tau[g] / DECAY_S)
    elif after == "spread":
        out[g] = v["025"][g] + (0.005 - v["025"][g]) * (-tau[g] / DECAY_S)
        out[h] = 0.005
    return np.maximum(out, 0.0) if side == "E" else out


def edge_per_share(curve, idx, n, scale, tau, decay_to_zero: bool) -> np.ndarray:
    """Correct-call gross edge per share (see curve_per_share)."""
    return curve_per_share(curve, "E", idx, n, scale, tau, "decay" if decay_to_zero else "zero")


# ---------------------------------------------------------------------------- point-ending mix
_SERVE = re.compile(r"^c*[0456]\+?")


def _classify(first: str, second: str) -> str:
    """Terminal category of one charted point (Match Charting Project codes).

    out      rally error typed w / d / x (wide, deep, wide+deep), or a double fault typed w / d / x
    net      rally error typed n, or a double fault into the net
    winner   ace, unreturnable serve, or rally winner
    other    shanks, unknown error types, foot faults, penalties, malformed strings"""
    first = (first or "").strip()
    second = (second or "").strip()
    s = second if second else first
    if not s:
        return "other"
    end = s[-1]
    if end == "*":
        return "winner"
    if end in "#@":
        prev = s[-2] if len(s) >= 2 else ""
        if prev == "n":
            return "net"
        if prev in "wdx":
            return "out"
        body = _SERVE.sub("", s[:-1])
        if body == "" and end == "#":      # serve followed directly by '#': unreturnable serve
            return "winner"
        return "other"
    if second:  # second serve did not end in a terminal mark -> double fault (fault type is the last char)
        if end == "n":
            return "net"
        if end in "wdx":
            return "out"
    return "other"


def point_mix(refresh: bool = False) -> dict:
    """Share of points ending in each category, men and women, 2020s charted matches."""
    f = INPUTS / "point_mix.json"
    if f.exists() and not refresh:
        return json.loads(f.read_text())
    out = {"source": f"Jeff Sackmann, Match Charting Project ({MCP_URL}), charting-{{m,w}}-points-2020s.csv, "
                     "CC BY-NC-SA 4.0. Crowd-charted, mostly tour-level and Grand Slam matches.",
           "distance_out": "not recorded by the MCP; out-ball distances use the physics model's near-line "
                           "population (ASSUMPTION)"}
    for g in ("m", "w"):
        p = pd.read_csv(MCP_DIR / f"charting-{g}-points-2020s.csv", usecols=["match_id", "1st", "2nd"],
                        dtype=str, encoding="latin-1", keep_default_na=False)
        cat = np.array([_classify(a, b) for a, b in zip(p["1st"], p["2nd"])])
        sec = p["2nd"].str.strip()
        df = (sec != "") & ~sec.str[-1:].isin(list("*#@")) & (cat != "other")
        vc = pd.Series(cat).value_counts(normalize=True)
        out["men" if g == "m" else "women"] = {
            "n_points": int(len(p)), "n_matches": int(p.match_id.nunique()),
            "years": [int(p.match_id.str[:4].min()), int(p.match_id.str[:4].max())],
            "out": round(float(vc.get("out", 0)), 4), "net": round(float(vc.get("net", 0)), 4),
            "winner": round(float(vc.get("winner", 0)), 4), "other": round(float(vc.get("other", 0)), 4),
            "double_fault": round(float(df.mean()), 4),
            "double_fault_out": round(float((df & (cat == "out")).mean()), 4),
        }
    INPUTS.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=1))
    return out


# ------------------------------------------------------------------------------------ CV systems
def physics_out_bins(n: int = 20000, seed: int = 7) -> dict:
    """Distance-out distribution of the OUT balls in src/hawkeye.py's near-line population (|d| < 1 m),
    same shot generator, seed and filters as hawkeye.simulate. ASSUMPTION: real out balls follow it."""
    f = INPUTS / "physics_out_bins.json"
    if f.exists():
        return json.loads(f.read_text())
    from src import hawkeye as H
    rng = np.random.default_rng(seed)
    s = H.sample_shots(n, rng)
    acc_t = lambda v, a: H._accel_truth(v, s["w_hat"][a], s["omega"][a])  # noqa: E731
    land, tland, traj = H._integrate(s["p0"], s["v0"], acc_t, record_every=1 / H.FPS)
    ok = np.isfinite(tland)
    y = traj[..., 1]
    cross = np.argmax(np.nan_to_num(y, nan=-1) >= H.NET_Y, axis=1)
    zc = traj[np.arange(n), cross, 2]
    ok &= (zc > H.NET_H + H.R) & (tland > 0.25)
    d = H.signed_out_distance(land, s["serve"])
    ok &= np.abs(d) < 1.0
    dout = d[ok & (d > 0)]
    edges = [0.0, 0.02, 0.05, 0.10, 0.20, 0.40, 1.0]
    cnt = np.histogram(dout, edges)[0]
    out = {"edges_m": edges, "weights": (cnt / cnt.sum()).round(5).tolist(), "n_out": int(len(dout)),
           "source": "src/hawkeye.py sample_shots/_integrate, seed 7, n 20000, near-line filter |d|<1 m"}
    INPUTS.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=1))
    return out


def _wilson_lo(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return float("nan")
    p = k / n
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    return (c - z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den


def cv_systems() -> dict:
    """Recall-vs-lead and precision-vs-lead tables for out calls.

    own120       real 120 fps table-tennis video (results/tracking/summary.json). Recall = test, snapshot
                 rule; precision = test + train out-of-fold pooled, snapshot rule. Usable leads are those
                 with pooled precision >= 0.95 (decided on precision only). ASSUMPTION: tennis out calls are
                 at least as easy as table-tennis misses at the same frame rate.
    own120_pess  same camera, pessimistic: no early calls (lead 0 only), recall at the bounce = the test
                 ONLINE rule, precision = the worst measured lead-0 precision (train OOF snapshot), 50 ms
                 inference.
    hawkeye340   physics Monte Carlo, 340 fps multi-camera (results/hawkeye_tennis_calls.csv): recall by
                 lead and distance-out bin; precision per lead (balanced near-line population).
    Out balls not called early, and every other ending, are called at the event (lead 0) by CV event
    detection with precision p_event (a grid)."""
    tr = json.loads((ROOT / "results/tracking/summary.json").read_text())["early_call"]
    te, oof = tr["precision_recall_test_snapshot"], tr["precision_recall_train_oof_snapshot"]
    leads = [0, 25, 50, 100, 150, 200]
    rec = [te[f"{L}ms"]["recall"] for L in leads]
    tp = [te[f"{L}ms"]["tp"] + oof[f"{L}ms"]["tp"] for L in leads]
    fp = [te[f"{L}ms"]["fp"] + oof[f"{L}ms"]["fp"] for L in leads]
    prec = [a / (a + b) for a, b in zip(tp, fp)]
    usable = [L for L, p in zip(leads, prec) if p >= 0.95]
    lmax = max(usable) if usable else 0
    own = {"leads_ms": leads, "recall": [[r] for r in rec], "precision": prec, "bins_w": [1.0],
           "max_lead_ms": lmax, "t_inf": T_INF,
           "precision_n": [a + b for a, b in zip(tp, fp)]}
    on = tr["precision_recall_test_online"]
    p0_oof = oof["0ms"]["precision"]
    pess = {"leads_ms": [0], "recall": [[on["0ms"]["recall"]]], "precision": [p0_oof], "bins_w": [1.0],
            "max_lead_ms": 0, "t_inf": T_INF_PESS}
    hk = pd.read_csv(ROOT / "results/hawkeye_tennis_calls.csv")
    bcols = ["recall_out_0_2cm", "recall_out_2_5cm", "recall_out_5_10cm", "recall_out_10_20cm",
             "recall_out_20_40cm", "recall_out_40_100cm"]
    hawk = {"leads_ms": hk.lead_ms.tolist(), "recall": hk[bcols].to_numpy().tolist(),
            "precision": hk.precision.tolist(), "bins_w": physics_out_bins()["weights"],
            "max_lead_ms": int(hk.lead_ms.max()), "t_inf": T_INF}
    return {"own120": own, "own120_pess": pess, "hawkeye340": hawk}


def lead_and_precision(sysd: dict, u_lead: np.ndarray, u_bin: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For out balls: monotone coupling. recall_mono(L) = max over L' >= L of recall(L') (a ball callable at
    L ms is callable at any shorter lead). Ball is called at lead L* = max{L <= max_lead : recall_mono(L) >= u}.
    Returns (lead_s, precision, called_early)."""
    leads = np.array(sysd["leads_ms"], float)
    R = np.array(sysd["recall"], float)            # (n_leads, n_bins)
    keep = leads <= sysd["max_lead_ms"]
    leads, R = leads[keep], R[keep]
    P = np.array(sysd["precision"], float)[keep]
    Rm = np.maximum.accumulate(R[::-1], axis=0)[::-1]  # running max from the long-lead end
    cw = np.cumsum(sysd["bins_w"])
    b = np.minimum(np.searchsorted(cw, u_bin * cw[-1], "right"), len(cw) - 1)
    r = Rm[:, b]                                   # (n_leads, n)
    ok = r >= u_lead[None, :]
    called = ok[0]
    # index of the longest lead that is still callable (Rm is non-increasing in lead)
    k = ok.sum(0) - 1
    lead = np.where(called, leads[np.maximum(k, 0)] / 1000.0, 0.0)
    prec = np.where(called, P[np.maximum(k, 0)], np.nan)
    return lead, prec, called


# ========================================================================= historical jump table
def prestart_volume(conds, refresh: bool = False) -> pd.Series:
    """$ traded before the scheduled start (ex-ante match size), from the raw public tapes."""
    f = ROOT / "data/derived/tier0_prestart_volume.parquet"
    if f.exists() and not refresh:
        s = pd.read_parquet(f).set_index("cond").prestart_usd
        if set(conds) <= set(s.index):
            return s
    from src import polymarket as pm
    from src.tape import universe
    u = universe().set_index("cond")
    rows = []
    for c in conds:
        fp = pm.RAW / "trades" / f"{c}.parquet"
        v = 0.0
        if fp.exists():
            t = pd.read_parquet(fp, columns=["timestamp", "size", "price"])
            st = int(u.loc[c, "start"].timestamp())
            pre = t[t.timestamp < st]
            v = float((pre["size"] * pre["price"]).sum())
        rows.append({"cond": c, "prestart_usd": v})
    s = pd.DataFrame(rows)
    s.to_parquet(f)
    return s.set_index("cond").prestart_usd


def _oos_jumps_one(args):
    from src.tiers import jump_onsets
    c, ts, p, usd = args
    return [{"cond": c, "onset_ts": o[0], "dir": o[1], "size": o[2], "detect_ts": o[3]}
            for o in jump_onsets(ts, p, usd)]


def oos_jumps(workers: int = 3) -> pd.DataFrame:
    """Burned-OOS jumps: src.tiers.jump_onsets on data/locked/oos_prints.parquet (in-play tapes), per cond."""
    f = ROOT / "data/derived/tier0_jumps_burned_oos.parquet"
    if f.exists():
        return pd.read_parquet(f)
    from concurrent.futures import ProcessPoolExecutor
    pr = pd.read_parquet(ROOT / "data/locked/oos_prints.parquet", columns=["cond", "ts", "p", "usd"])
    pr = pr.sort_values(["cond", "ts"], kind="stable")
    args = [(c, g.ts.to_numpy(float), g.p.to_numpy(), g.usd.to_numpy()) for c, g in pr.groupby("cond", sort=False)]
    with ProcessPoolExecutor(workers) as ex:
        js = [x for part in ex.map(_oos_jumps_one, args, chunksize=16) for x in part]
    out = pd.DataFrame(js)
    out.to_parquet(f)
    with open(ROOT / "results/oos_peeks.log", "a") as fh:
        fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} tier0 counterfactual: OOS jump table built "
                 f"(burned OOS, non-blind)\n")
    return out


def _refs(prints: pd.DataFrame, J: pd.DataFrame) -> pd.DataFrame:
    """Stale price: VWAP of outcome-0 prints in [onset-63, onset-3) (research/v2/sizing/features.py 'ref').
    Sensitivity: ref_short = VWAP in [onset-33, onset-1) (closer to the point; the detector's onset is the
    first print of its 10 s window, so a shorter window is often empty)."""
    J = J.sort_values(["cond", "onset_ts"], kind="stable").reset_index(drop=True)
    ref = np.full(len(J), np.nan)
    ref_s = np.full(len(J), np.nan)
    groups = {c: g for c, g in prints.groupby("cond", sort=False)}
    for c, g in J.groupby("cond", sort=False):
        P = groups.get(c)
        if P is None:
            continue
        ts, p, usd = P.ts.to_numpy(), P.p.to_numpy(), P.usd.to_numpy()
        pv = np.concatenate([[0.0], np.cumsum(p * usd)]); vv = np.concatenate([[0.0], np.cumsum(usd)])
        on = g.onset_ts.to_numpy()
        for lo, hi, arr in ((63, 3, ref), (33, 1, ref_s)):
            a = np.searchsorted(ts, on - lo, "left"); b = np.searchsorted(ts, on - hi, "left")
            w = vv[b] - vv[a]
            arr[g.index.to_numpy()] = np.where(w > 0, (pv[b] - pv[a]) / np.where(w > 0, w, 1), np.nan)
    return J.assign(ref=ref, ref_short=ref_s)


def jump_table(period: str) -> pd.DataFrame:
    """Every historical >= 4c jump of `period` ('is' or 'oos') with its stale prices and match facts."""
    f = ROOT / f"data/derived/tier0_jumps_{period}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    from src.tape import universe
    u = universe()
    if period == "is":
        J = pd.read_parquet(ROOT / "data/derived/jumps_is.parquet")
        pr = pd.read_parquet(ROOT / "data/is_prints.parquet", columns=["cond", "ts", "p", "usd"])
    else:
        J = oos_jumps()
        pr = pd.read_parquet(ROOT / "data/locked/oos_prints.parquet", columns=["cond", "ts", "p", "usd"])
    pr = pr[pr.cond.isin(set(J.cond))]
    pr["cond"] = pr.cond.astype(str)
    pr = pr.sort_values(["cond", "ts"], kind="stable")
    J = _refs(pr, J)
    del pr
    keep = ["cond", "slug", "title", "series", "league", "start", "end", "res0", "volume", "fee_rate", "delay", "oos"]
    J = J.merge(u[keep], on="cond", how="left", validate="many_to_one")
    assert J.start.notna().all()
    assert (J.oos == (period == "oos")).all() and ((J.start >= OOS_START) == (period == "oos")).all()
    J["region"] = [region_of(a, b) for a, b in zip(J.league, J.title)]
    J["men"] = J.series.isin(["atp", "challenger"])
    J.to_parquet(f)
    return J


def post_prices(period: str, J: pd.DataFrame) -> np.ndarray:
    """Post-jump outcome-0 price per jump of jump_table(period) (row-aligned): VWAP of prints in
    [detect, detect + POST_W). Used ONLY to price a live-book fill (fill = post-jump token price minus the
    measured edge of the stale shares we take); no decision uses it. Cached."""
    f = ROOT / f"data/derived/tier0_post30_{period}.parquet"
    if f.exists():
        s = pd.read_parquet(f)
        if len(s) == len(J) and (s.cond.to_numpy() == J.cond.to_numpy()).all() \
                and np.allclose(s.onset_ts.to_numpy(), J.onset_ts.to_numpy()):
            return s.post30.to_numpy()
    path = ROOT / ("data/is_prints.parquet" if period == "is" else "data/locked/oos_prints.parquet")
    pr = pd.read_parquet(path, columns=["cond", "ts", "p", "usd"])
    pr["cond"] = pr.cond.astype(str)
    pr = pr[pr.cond.isin(set(J.cond))].sort_values(["cond", "ts"], kind="stable")
    groups = {c: g for c, g in pr.groupby("cond", sort=False)}
    out = np.full(len(J), np.nan)
    Jr = J.reset_index(drop=True)
    for c, g in Jr.groupby("cond", sort=False):
        P = groups.get(c)
        if P is None:
            continue
        ts, p, usd = P.ts.to_numpy(), P.p.to_numpy(), P.usd.to_numpy()
        pv = np.concatenate([[0.0], np.cumsum(p * usd)]); vv = np.concatenate([[0.0], np.cumsum(usd)])
        det = g.detect_ts.to_numpy(float)
        a = np.searchsorted(ts, det, "left"); b = np.searchsorted(ts, det + POST_W, "left")
        w = vv[b] - vv[a]
        out[g.index.to_numpy()] = np.where(w > 0, (pv[b] - pv[a]) / np.where(w > 0, w, 1), np.nan)
    pd.DataFrame({"cond": Jr.cond, "onset_ts": Jr.onset_ts, "post30": out}).to_parquet(f)
    if period != "is":
        with open(ROOT / "results/oos_peeks.log", "a") as fh:
            fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} tier0 corrections: OOS post-jump prices built "
                     f"(burned OOS, non-blind, labelled)\n")
    return out


def tournament_codes(u: pd.DataFrame, gap_days: float = 4.0) -> pd.Series:
    """Tournament id per universe match (for timing regimes drawn once per tournament, DEVIATIONS V3):
    league with ', Qualification' and a trailing ATP/WTA stripped, split where the gap between consecutive
    match starts exceeds gap_days. Returns an int code indexed by cond."""
    lg = (u.league.fillna("?").str.replace(r",\s*Qualification.*$", "", regex=True)
          .str.replace(r"\s+(ATP|WTA)$", "", regex=True).str.strip().str.lower())
    x = pd.DataFrame({"cond": u.cond.to_numpy(), "lg": lg.to_numpy(), "start": u.start.to_numpy()})
    x = x.sort_values(["lg", "start"], kind="stable")
    new = (x.lg != x.lg.shift()) | (x.start.diff() > pd.Timedelta(days=gap_days))
    x["tour"] = new.cumsum() - 1
    return x.set_index("cond").tour


# ===================================================================================== simulation
@dataclass(frozen=True)
class Scenario:
    cv: str = "own120"            # own120 | own120_pess | hawkeye340
    stamp_lag: float = 2.0        # t_stamp - t_bounce, s (UNMEASURED: grid + calibration)
    phi: float = 0.5              # our share of the stale depth vs the existing fast tier
    coverage: int = 10            # matches per UTC day with a camera (top pre-start volume)
    p_event: float = 0.95         # precision of CV event calls at lead 0 (winners, net errors, ...)
    net_cap: float = 100.0        # per-match |net outcome-0 shares| cap (risk-reducing trades allowed)
    trade_cap: float = 1000.0     # $ per order
    slip: float = 0.005           # taker pays half the measured 1c live moneyline spread over the stale mid
    lat_map: str = "region"       # region | all100
    pool: str = "D>=3c"           # live points sampled for timing + depth: D>=3c | all
    vol_scale: str = "cap1"       # depth x min(1, V_match/V_live) | none | sym3 (ratio capped at 3)
    stale: str = "ref"            # ref | ref_short
    regime: str = "delay1"        # delay1 (the regime the latency was measured in) | all
    # ---- verifier corrections (DEVIATIONS V1-V5); defaults = the pre-registered model
    price: str = "ref"            # ref: correct fill at stale + slip (pre-registered; double-counts the edge)
    #                               live: post-jump price minus the measured edge of the first n stale shares
    order: str = "decay"          # decay: correct calls also fill in the 0.5 s after the reprice at a moved
    #                               price (pre-registered) | limit: correct calls fill only before the reprice
    r_mode: str = "point"         # how t_reprice - t_bounce varies. point: R drawn per point + constant
    #                               stamp lag (pre-registered: all of R's spread is book timing) | tournament:
    #                               R drawn ONCE per tournament (persistent regime) | stamp: R's spread is
    #                               umpire-stamp noise, t_reprice - t_bounce = median(R) + stamp_lag constant
    r_shift: float = 0.0          # added to R (s); -0.5 = official 1 s stamps truncated, not rounded
    queue_s: float = 0.0          # correct calls fill only if we arrive >= queue_s before the reprice
    stale_adj: float = 0.0        # added to the point-winner token's stale price (measured: +0.005)
    edge_scale: bool = False      # live price: scale the live edge by historical size / live D (generous)
    wrong_price: str = "ref"      # ref: a wrong call pays the loser's stale price + slip, i.e. loses the whole
    #                               realised historical jump (pre-registered) | live: loses the measured
    #                               per-share cost of the first n shares on the opposite side of the book

    def key(self) -> str:
        k = (f"{self.cv}|lag{self.stamp_lag:g}|phi{self.phi:g}|cov{self.coverage}|pev{self.p_event:g}|"
             f"net{self.net_cap:g}")
        if self.price != "ref" or self.order != "decay" or self.r_mode != "point" or self.wrong_price != "ref":
            k += f"|{self.price}|{self.order}|{self.r_mode}|w{self.wrong_price}"
        return k


PRIMARY = Scenario()
# Headline configuration after the verifiers' fixes: same pre-registered parameters, plus the live-book
# fill price, limit-order fills, timing drawn once per tournament and the measured stale-price correction.
CORRECTED = Scenario(price="live", order="limit", r_mode="tournament", stale_adj=STALE_ADJ_MEASURED,
                     wrong_price="live")


def coverage_set(M: pd.DataFrame, n_per_day: int, regime: str) -> set:
    """Matches with a camera: per UTC start date, the n with the highest PRE-START volume (ex-ante).
    M = every universe match of BOTH periods (cond, start, delay, prestart_usd), whether or not it later
    produced a jump, so the choice never looks ahead and the IS/OOS split day gets n cameras, not 2n
    (DEVIATIONS V6; the first runs ranked within each period)."""
    m = M[["cond", "start", "delay", "prestart_usd"]]
    if regime == "delay1":
        m = m[m.delay == 1]
    m = m.assign(day=m.start.dt.floor("D")).sort_values(["day", "prestart_usd", "cond"],
                                                        ascending=[True, False, True], kind="stable")
    return set(m.groupby("day").head(n_per_day).cond)


def draws(n: int, seed: int, n_tour: int = 4096) -> dict:
    """Uniforms per jump row (pool point, ending, CV lead, distance bin, precision) and, from a separate
    stream so the per-jump draws are unchanged, one per tournament code (timing regime)."""
    rng = np.random.default_rng(seed)
    out = {k: rng.random(n) for k in ("pool", "end", "lead", "bin", "prec")}
    out["tour"] = np.random.default_rng([seed, 99]).random(n_tour)
    return out


def _depth(pool: pd.DataFrame, idx: np.ndarray, tau: np.ndarray) -> np.ndarray:
    """$ of stale depth at tau s before the reprice, per sampled live point (piecewise linear between the
    measured snapshots at 2, 1, 0.25 s before and 0.5 s after; flat beyond 2 s and between 0.25 and 0)."""
    u2, u1, u025, upost = (pool[c].to_numpy()[idx] for c in ("usd_2", "usd_1", "usd_025", "usd_post"))
    out = np.zeros(len(tau))
    a = tau >= 2.0
    out[a] = u2[a]
    b = (tau >= 1.0) & (tau < 2.0)
    out[b] = u1[b] + (u2[b] - u1[b]) * (tau[b] - 1.0)
    c = (tau >= 0.25) & (tau < 1.0)
    out[c] = u025[c] + (u1[c] - u025[c]) * (tau[c] - 0.25) / 0.75
    d = (tau >= 0) & (tau < 0.25)
    out[d] = u025[d]
    e = (tau >= -DECAY_S) & (tau < 0)
    out[e] = u025[e] + (upost[e] - u025[e]) * (-tau[e] / DECAY_S)
    return np.maximum(out, 0.0)


def simulate(J: pd.DataFrame, M: pd.DataFrame, sc: Scenario, dr: dict, pools: dict, cvs: dict,
             mix: dict) -> pd.DataFrame:
    """One scenario on one period. J = the period's jumps, carrying 'row' (index into the draws);
    M = the period's universe matches with 'prestart_usd' (coverage choice).
    Returns one row per CALL (every covered in-zone jump we would send an order for); `shares` is 0 when
    the order does not fill or the net cap blocks it.

    Corrections (Scenario.price / order / r_mode / r_shift / queue_s / stale_adj; DEVIATIONS V1-V5):
      price='live'   a correct fill pays post-jump token price - e, where e = average edge vs the new mid
                     of the first n shares resting on the sampled live point at the same tau (measured
                     book; see live_edge_curve). Pre-registered 'ref' paid stale + slip, which credits every
                     stale share with the whole jump.
      order='limit'  correct calls fill only if they arrive >= queue_s before the reprice (a 1 s-delayed
                     order cannot see the book, so it cannot 'never chase' and also fill at a moved price).
                     Wrong calls are unchanged: their book moves toward the order, so they fill late too.
      r_mode         point (pre-registered) / tournament / stamp: see Scenario."""
    cov = coverage_set(M, sc.coverage, sc.regime)
    X = J[J.cond.isin(cov)]
    ref = X[sc.stale].to_numpy()
    dirn = X["dir"].to_numpy()
    q_c0 = np.where(dirn > 0, ref, 1 - ref) + sc.stale_adj     # stale price of the point-winner's token
    ok = np.isfinite(ref) & (q_c0 >= ZONE[0]) & (q_c0 <= ZONE[1])
    X = X[ok]
    q_c0 = q_c0[ok]
    dirn = dirn[ok]
    r = X.row.to_numpy()
    n = len(X)
    if n == 0:
        return pd.DataFrame()
    pool = pools[sc.pool]
    pidx = np.minimum((dr["pool"][r] * len(pool)).astype(int), len(pool) - 1)
    # point ending
    men = X.men.to_numpy()
    p_out = np.where(men, mix["men"]["out"], mix["women"]["out"])
    is_out = dr["end"][r] < p_out
    cvd = cvs[sc.cv]
    lead, prec_cv, called = lead_and_precision(cvd, dr["lead"][r], dr["bin"][r])
    early = is_out & called
    lead = np.where(early, lead, 0.0)
    prec = np.where(early, prec_cv, sc.p_event)
    # timing (seconds, origin = ball landing / point end)
    lat = (np.full(n, 0.100) if sc.lat_map == "all100"
           else X.region.map(REGION_MS).to_numpy(float) / 1000.0)
    arrival = -lead + cvd["t_inf"] + lat + GATEWAY + X.delay.to_numpy(float)
    R = pool.R.to_numpy()
    if sc.r_mode == "point":
        t_rep = R[pidx] + sc.stamp_lag + sc.r_shift
    elif sc.r_mode == "tournament":
        tu = dr["tour"][X.tour.to_numpy()]
        t_rep = R[np.minimum((tu * len(pool)).astype(int), len(pool) - 1)] + sc.stamp_lag + sc.r_shift
    elif sc.r_mode == "stamp":
        t_rep = np.full(n, float(np.median(R)) + sc.stamp_lag + sc.r_shift)
    else:
        raise ValueError(sc.r_mode)
    tau = t_rep - arrival
    # depth scaled to the historical match's size
    ratio = X.volume.to_numpy(float) / pool.V_live.to_numpy()[pidx]
    scale = {"cap1": np.minimum(1.0, ratio), "none": np.ones(n), "sym3": np.minimum(3.0, ratio)}[sc.vol_scale]
    correct = dr["prec"][r] < prec
    size = X["size"].to_numpy()
    # move already made by the book at arrival, as a fraction of the jump (0 before the reprice,
    # half at the reprice, all of it 0.5 s later)
    mfrac = np.where(tau >= 0, 0.0, np.where(tau >= -DECAY_S, 0.5 + (-tau), 1.0))
    # correct call: compete with the fast tier (phi) for the stale depth; never chase
    lo = -DECAY_S if (sc.order == "decay" and sc.queue_s == 0) else sc.queue_s
    fill_ok = tau >= lo
    dep_c = _depth(pool, pidx, tau) * scale * sc.phi
    if sc.price == "ref":
        q_c = q_c0 + size * mfrac + sc.slip
        e_c = np.full(n, np.nan)
    elif sc.price == "live":
        post = X["post30"].to_numpy(float) if "post30" in X else np.full(n, np.nan)
        post_tok = np.where(dirn > 0, post, 1 - post)
        post_tok = np.where(np.isfinite(post_tok), post_tok, q_c0 + size)   # fallback: stale + jump
        escl = (size / pool.D.to_numpy()[pidx]) if sc.edge_scale else np.ones(n)
        dz = sc.order == "decay"
        e_c = edge_per_share(pool, pidx, np.full(n, 100.0), scale, tau, dz) * escl
        for _ in range(2):          # shares depend on price, price on shares: two fixed-point passes
            q_c = np.clip(post_tok - e_c, 0.01, 0.99)
            n_sh = np.minimum(sc.trade_cap, dep_c) / q_c
            e_c = edge_per_share(pool, pidx, n_sh, scale, tau, dz) * escl
        q_c = np.clip(post_tok - e_c, 0.01, 0.99)
    else:
        raise ValueError(sc.price)
    sh_c = np.where(fill_ok, np.minimum(sc.trade_cap / q_c, dep_c / q_c), 0.0)
    # wrong call: we buy the loser's token; nobody competes for it and the book moves our way to fill
    dep_w = _depth(pool, pidx, np.maximum(tau, 0.0)) * scale
    if sc.wrong_price == "ref":
        q_w = np.clip((1 - q_c0) - size * mfrac, 0.01, 0.99) + sc.slip
    elif sc.wrong_price == "live":
        post = X["post30"].to_numpy(float) if "post30" in X else np.full(n, np.nan)
        post_l = np.where(dirn > 0, 1 - post, post)                        # loser token, post-jump
        post_l = np.where(np.isfinite(post_l), post_l, (1 - q_c0) - size)
        w = curve_per_share(pool, "W", pidx, np.full(n, 100.0), scale, tau, "spread")
        for _ in range(2):
            q_w = np.clip(post_l + w, 0.01, 0.99)
            w = curve_per_share(pool, "W", pidx, np.minimum(sc.trade_cap, dep_w) / q_w, scale, tau, "spread")
        q_w = np.clip(post_l + w, 0.01, 0.99)
    else:
        raise ValueError(sc.wrong_price)
    sh_w = np.minimum(sc.trade_cap / q_w, dep_w / q_w)
    q = np.where(correct, q_c, q_w)
    sh = np.where(correct, sh_c, sh_w)
    tok0 = np.where(correct, dirn > 0, dirn < 0)           # did we buy outcome 0's token?
    res0 = X.res0.to_numpy(float)
    payout = np.where(tok0, res0, 1 - res0)
    rate = X.fee_rate.to_numpy(float)
    T = pd.DataFrame({"cond": X.cond.to_numpy(), "ts": X.onset_ts.to_numpy(), "start": X.start.to_numpy(),
                      "q": q, "sh_raw": sh, "d0": np.where(tok0, 1.0, -1.0), "payout": payout,
                      "fee_ps": rate * q * (1 - q), "correct": correct, "tau": tau, "early": early,
                      "is_out": is_out, "region": X.region.to_numpy(), "delay": X.delay.to_numpy(),
                      "dep_c": dep_c, "size": size, "rate": rate, "edge_c": e_c, "i": np.arange(n),
                      "at_cap": np.where(correct, dep_c >= sc.trade_cap, dep_w >= sc.trade_cap)})
    T = T.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    T["shares"] = _net_cap(T, sc.net_cap)
    # re-price live fills for the shares actually sent after the net cap (fewer shares -> the better
    # levels of the book); shares are unchanged
    if sc.price == "live":
        m = (T.correct & (T.shares > 1e-9)).to_numpy()
        i = T.i.to_numpy()[m]
        e2 = edge_per_share(pool, pidx[i], T.shares.to_numpy()[m], scale[i], tau[i], sc.order == "decay") * escl[i]
        qn = np.clip(post_tok[i] - e2, 0.01, 0.99)
        T.loc[m, "q"] = qn
        T.loc[m, "edge_c"] = e2
        T.loc[m, "fee_ps"] = T.rate.to_numpy()[m] * qn * (1 - qn)
    if sc.wrong_price == "live":
        m = (~T.correct & (T.shares > 1e-9)).to_numpy()
        i = T.i.to_numpy()[m]
        w2 = curve_per_share(pool, "W", pidx[i], T.shares.to_numpy()[m], scale[i], tau[i], "spread")
        qn = np.clip(post_l[i] + w2, 0.01, 0.99)
        T.loc[m, "q"] = qn
        T.loc[m, "edge_c"] = -w2
        T.loc[m, "fee_ps"] = T.rate.to_numpy()[m] * qn * (1 - qn)
    T["pnl_ps"] = T.payout - T.q - T.fee_ps
    T["pnl"] = T.shares * T.pnl_ps
    T["usd_in"] = T.shares * T.q
    T["lock_end"] = T.ts + LOCK_S
    T["date"] = pd.to_datetime(T.ts, unit="s", utc=True).dt.floor("D")
    T["month"] = T.date.dt.strftime("%Y-%m")
    return T


def _net_cap(T: pd.DataFrame, cap: float) -> np.ndarray:
    """Per-match |net outcome-0 shares| <= cap, trades in time order; a trade may always reduce exposure
    (engine.apply_caps semantics: s <= max(0, cap - d * net)). Lockstep over the k-th trade of every match."""
    s = T.sh_raw.to_numpy().copy()
    if not np.isfinite(cap):
        return s
    d = T.d0.to_numpy()
    codes, first = np.unique(T.cond.to_numpy(), return_index=True)
    grp = np.searchsorted(codes, T.cond.to_numpy())
    k = np.arange(len(T)) - first[grp]
    net = np.zeros(len(codes))
    for j in range(int(k.max()) + 1 if len(k) else 0):
        i = np.flatnonzero(k == j)
        g = grp[i]
        allow = np.maximum(0.0, cap - d[i] * net[g])
        s[i] = np.minimum(s[i], allow)
        net[g] += d[i] * s[i]
    return s


# ======================================================================================== metrics
def peak_locked(tr: pd.DataFrame) -> float:
    if tr.empty:
        return 0.0
    ev = pd.concat([pd.DataFrame({"t": tr.ts, "d": tr.usd_in}), pd.DataFrame({"t": tr.lock_end, "d": -tr.usd_in})])
    return float(ev.sort_values(["t", "d"], kind="stable").d.cumsum().max())


def metrics(calls: pd.DataFrame, days: pd.DatetimeIndex, n_boot: int = 1000, seed: int = 0) -> dict:
    """Per-period statistics from simulate()'s call table. `days` = every calendar day of the period
    (zero-filled for the daily Sharpe)."""
    n_calls = len(calls)
    tr = calls[calls.shares > 1e-9] if n_calls else calls
    if tr.empty:
        return {"n_trades": 0, "n_calls": n_calls, "fill_rate": 0.0, "pnl_usd": 0.0, "pnl_per_day_usd": 0.0,
                "sharpe_ann": float("nan")}
    daily = tr.groupby("date").pnl.sum().reindex(days, fill_value=0.0)
    eq = daily.cumsum()
    dd = float((eq - eq.cummax()).min())
    peak = peak_locked(tr)
    cap = CAPITAL_MULT * peak
    g = tr.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
    P, S = g.p.to_numpy(), g.s.to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n_boot, len(g)))
    ps = P[idx].sum(1) / S[idx].sum(1) * 100
    tot = P[idx].sum(1)
    monthly = tr.groupby("month").pnl.sum()
    sd = daily.std()
    good = tr[tr.correct]
    n_days = len(days)
    return {
        "n_calls": int(n_calls), "n_trades": int(len(tr)), "n_trades_correct": int(len(good)),
        "n_matches": int(len(g)), "fill_rate": float(len(good) / n_calls) if n_calls else float("nan"),
        "wrong_call_share_of_trades": float(1 - len(good) / len(tr)),
        "calls_share_before_reprice": float((calls.tau >= 0).mean()),
        "calls_share_in_decay_window": float(((calls.tau < 0) & (calls.tau >= -DECAY_S)).mean()),
        "calls_share_too_late": float((calls.tau < -DECAY_S).mean()),
        "calls_median_tau_s": float(calls.tau.median()),
        "fills_median_tau_s": float(tr.tau.median()),
        "correct_calls_blocked_by_net_cap": float(((calls.correct) & (calls.sh_raw > 1e-9) & (calls.shares <= 1e-9)).sum()
                                                  / max(int(calls.correct.sum()), 1)),
        "median_usd_per_fill": float(tr.usd_in.median()),
        "shares": float(tr.shares.sum()), "usd_traded": float(tr.usd_in.sum()),
        "per_share_c": float(tr.pnl.sum() / tr.shares.sum() * 100),
        "per_share_ci95_c": [float(np.percentile(ps, 2.5)), float(np.percentile(ps, 97.5))],
        "pnl_usd": float(tr.pnl.sum()), "pnl_ci95_usd": [float(np.percentile(tot, 2.5)), float(np.percentile(tot, 97.5))],
        "pnl_correct_usd": float(good.pnl.sum()), "pnl_wrong_usd": float(tr[~tr.correct].pnl.sum()),
        "days": n_days, "pnl_per_day_usd": float(tr.pnl.sum() / n_days),
        "sharpe_ann": float(daily.mean() / sd * np.sqrt(365)) if sd > 0 else float("nan"),
        "max_dd_usd": dd, "worst_day_usd": float(daily.min()), "best_day_usd": float(daily.max()),
        "months_positive": int((monthly > 0).sum()), "months_total": int(len(monthly)),
        "peak_locked_usd": peak, "capital_usd": cap,
        "return_on_capital_pct": float(tr.pnl.sum() / cap * 100) if cap else float("nan"),
        "return_on_capital_ann_pct": float(tr.pnl.sum() / cap * 100 * 365 / n_days) if cap else float("nan"),
        "max_dd_pct_capital": float(dd / cap * 100) if cap else float("nan"),
        "share_fills_at_trade_cap": float(tr.at_cap.mean()),
        "capacity_stale_usd_per_day": float(calls[calls.correct].dep_c.sum() / n_days),
    }


def period_days(J: pd.DataFrame, regime: str) -> pd.DatetimeIndex:
    m = J if regime == "all" else J[J.delay == 1]
    d = pd.to_datetime(m.onset_ts, unit="s", utc=True).dt.floor("D")
    return pd.date_range(d.min(), d.max(), freq="D", tz="UTC")


def as_dict(sc: Scenario) -> dict:
    return asdict(sc)


__all__ = ["ASSUMED", "Scenario", "PRIMARY", "CORRECTED", "simulate", "metrics", "jump_table", "live_points",
           "live_edge_curve", "post_prices", "tournament_codes", "calibrate_stamp_lag", "point_mix", "cv_systems",
           "draws", "region_of", "replace"]
