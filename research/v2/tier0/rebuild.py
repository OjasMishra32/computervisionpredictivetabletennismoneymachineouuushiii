"""Independent rebuild of the tier-0 PRIMARY scenario, written from research/v2/tier0/PREREG.md only.

    .venv/bin/python research/v2/tier0/rebuild.py            # primary + stress tests + seeds 1-20
    .venv/bin/python research/v2/tier0/rebuild.py --quick    # primary + stress tests only

COUNTERFACTUAL WITH ASSUMED DATA. Assumed: licensed live feed + courtside camera, not purchased;
parameters from our measurements. No live ATP/WTA point feed was bought or used, and there is no camera
footage of these matches. Real inputs: public Polymarket tapes (prices, results, fees, venue delays).
Modelled inputs: timing, fills and call accuracy. The OOS period is the BURNED OOS (opened before; not blind).

This file deliberately does NOT import src/tier0.py or scripts/tier0_backtest.py, and does not read any
file they wrote (data/derived/tier0_*, results/tier0/*), except results/tier0/inputs/{point_mix.json,
live_match_volumes.csv}, which hold the frozen non-P&L inputs quoted in PREREG.md (re-checked below).
Everything else is rebuilt from the raw tapes, data/derived/jumps_is.parquet, data/is_prints.parquet,
data/locked/oos_prints.parquet (burned OOS), research/v2/latency/out/* and results/tracking/summary.json.

Outputs: research/v2/tier0/rebuild_out/rebuild.json (+ cached inputs in research/v2/tier0/rebuild_out/cache/).
"""
from __future__ import annotations

import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from src.tape import universe  # noqa: E402
from src.tiers import jump_onsets  # noqa: E402

LABEL = ("COUNTERFACTUAL WITH ASSUMED DATA. assumed: licensed live feed + courtside camera, not purchased; "
         "parameters from our measurements. OOS = burned OOS (not blind).")
OUT = ROOT / "research/v2/tier0/rebuild_out"
CACHE = OUT / "cache"
CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")

# ----------------------------------------------------------------- frozen primary parameters (PREREG.md)
PRIMARY = dict(
    stamp_lag=2.0,       # t_stamp - t_bounce, s (ASSUMPTION, unmeasured)
    phi=0.5,             # our share of the stale depth vs the existing fast tier
    coverage=10,         # matches per UTC start date, top pre-start volume
    p_event=0.95,        # precision of an at-the-event (lead 0) call by CV event detection
    net_cap=100.0,       # |net outcome-0 shares| per match
    trade_cap=1000.0,    # $ per order
    slip=0.005,          # taker slippage over the stale mid (half the measured 1c spread)
    inference=0.020,     # CV inference latency, s
    gateway=0.002,       # London co-located gateway, s
    zone=(0.05, 0.95),
    need_lead=0.0,       # stress (ii): our arrival must beat the reprice by this much (s)
    shift=0.0,           # stress (ii-b): extra latency added to arrival (s)
)
# own camera, 120 fps (results/tracking/summary.json): usable leads <= 100 ms
LEADS_MS = np.array([0, 25, 50, 100])
# PREREG.md quotes these; they are recomputed from summary.json in load_cv() and asserted equal.
REGION_MS = {"Europe": 10, "Americas": 40, "Asia": 100, "Oceania": 140, "MiddleEast": 50, "Africa": 80,
             "unmapped": 100}

# Venue -> region, my own keyword list (league first, then title). Turkey and North Africa count as Europe.
REGION_KEYS = {
    "Europe": [
        "roland garros", "wimbledon", "eastbourne", "birmingham", "nottingham", "ilkley", "roehampton",
        "queen", "hsbc championships", "halle", "stuttgart", "libema", "s-hertogenbosch", "mallorca",
        "bad homburg", "hamburg", "augsburg", "tulln", "genoa", "seville", "szczecin", "sion", "porto",
        "plovdiv", "istanbul", "biella", "como", "manacor", "cassis", "bari", "valencia", "iasi",
        "prague", "parma", "vicenza", "cattolica", "lyon", "bratislava", "brescia", "poznan", "troyes",
        "athens", "zug", "segovia", "san marino", "warsaw", "hagen", "todi", "caldas da rainha", "ankara",
        "lalla meryem", "rabat", "cervia", "perugia", "heilbronn", "foggia", "prostejov", "modena",
        "figueira", "royan", "milan", "bastad", "swedish open", "contrexeville", "trieste", "braunschweig",
        "rome", "internazionali", "kitzbuehel", "kitzbuhel", "generali open", "bunschoten", "tampere",
        "palermo", "liberec", "bonn", "antalya", "montreux", "ljubljana", "tolentino", "st. tropez",
        "saint tropez", "kosice", "dublin", "liege", "cordenons", "grodzisk", "chisinau", "brasov",
        "pozoblanco", "strasbourg", "geneva", "makarska", "grass court championships", "croatia open",
        "umag", "estoril", "samsun", "adana", "mouilleron", "swiss open", "gstaad", "bordeaux", "paris",
        "zagreb", "tunis", "oeiras", "targu mures", "rennes", "budapest", "marbella", "oeiras", "madrid",
        "barcelona", "munich", "monte carlo", "lugano", "luxembourg", "linz", "vienna", "basel", "metz",
        "rotterdam", "amsterdam", "berlin", "london", "lisbon", "helsinki", "stockholm", "copenhagen",
        "oslo", "belgrade", "bucharest", "sofia", "cluj", "maribor", "portoroz", "parma", "kozerki", "verona", "napoli", "naples", "cagliari", "turin", "florence", "firenze", "bergamo",
        "mestre", "trento", "francavilla", "ostrava", "prerov", "liberec", "pilsen", "plzen", "zadar",
        "split", "skopje", "tbilisi", "batumi", "yerevan",
    ],
    "Americas": [
        "us open", "cincinnati", "national bank open", "canadian open", "toronto", "montreal",
        "mubadala citi dc", "washington", "newport", "vancouver", "winston-salem", "tiburon", "columbus",
        "kingston", "san diego", "buenos aires", "curitiba", "quebec", "cancun", "bloomfield hills",
        "sao paulo", "tucuman", "brownsburg", "little rock", "bogota", "lexington", "philadelphia",
        "barranquilla", "asuncion", "quito", "cary", "granby", "winnipeg", "memphis", "piracicaba",
        "los cabos", "monterrey", "guadalajara", "tyler", "cordoba", "chicago", "atlanta", "los angeles",
        "indian wells", "miami", "houston", "charleston", "austin", "acapulco", "santiago", "lima",
        "rio de janeiro", "medellin", "cali", "guayaquil", "montevideo", "puerto vallarta", "mexico",
        "san francisco", "new york", "boston", "dallas", "phoenix", "orlando", "sarasota", "tallahassee",
        "savannah", "charlottesville", "knoxville", "champaign", "fairfield", "calgary", "toronto",
        "saguenay", "rancho santa fe", "evansville", "lincoln", "santa cruz", "concepcion", "campinas",
        "florianopolis", "porto alegre", "salvador", "brasilia", "rosario", "temuco",
    ],
    "Asia": [
        "china open", "jingshan", "guangzhou", "phan thiet", "shanghai", "zhangjiagang", "bengaluru",
        "astana", "korea open", "seoul", "singapore", "chengdu", "hangzhou", "japan open", "tokyo",
        "osaka", "wuhan", "ningbo", "beijing", "zhuhai", "shenzhen", "hong kong", "kaohsiung", "taipei",
        "jinan", "nanchang", "pune", "chennai", "new delhi", "mumbai", "manila", "jakarta", "bangkok",
        "nonthaburi", "kuala lumpur", "almaty", "busan", "gwangju", "yokohama", "kobe", "matsuyama",
        "hua hin",
    ],
    "Oceania": ["australian open", "brisbane", "adelaide", "auckland", "hobart", "canberra", "sydney",
                "perth", "melbourne", "darwin", "playford", "traralgon", "burnie"],
    "MiddleEast": ["dubai", "doha", "qatar", "abu dhabi", "riyadh", "jeddah", "bahrain", "manama",
                   "tel aviv", "jerusalem"],
    "Africa": ["centurion", "johannesburg", "pretoria", "cape town", "nairobi", "lagos", "abidjan",
               "kigali"],
}


def region_of(league: str, title: str) -> str:
    for text in (str(league).lower(), str(title).lower()):
        for reg, keys in REGION_KEYS.items():
            for k in keys:
                if k in text:
                    return reg
    return "unmapped"


# ----------------------------------------------------------------- inputs
def _prestart_one(args):
    cond, start_s = args
    f = ROOT / "data/raw/trades" / f"{cond}.parquet"
    if not f.exists():
        return cond, 0.0, False
    t = pd.read_parquet(f, columns=["timestamp", "price", "size"])
    pre = t[t.timestamp < start_s]
    return cond, float((pre["price"] * pre["size"]).sum()), True


def load_universe() -> pd.DataFrame:
    u = universe()
    u = u[u.delay == 1].copy()  # primary regime: 1 s venue delay (all matches from 2026-05-15 08:30)
    u["period"] = np.where(u.start < CUT, "IS", "burned_OOS")
    u["date"] = u.start.dt.floor("D")
    u["men"] = u.series.isin(["atp", "challenger"])
    u["region"] = [region_of(lg, ti) for lg, ti in zip(u.league, u.title)]
    f = CACHE / "prestart.parquet"
    if f.exists():
        pv = pd.read_parquet(f)
    else:
        args = [(c, int(s.timestamp())) for c, s in zip(u.cond, u.start)]
        with Pool(3) as pool:
            res = pool.map(_prestart_one, args, chunksize=50)
        pv = pd.DataFrame(res, columns=["cond", "prestart_usd", "has_tape"])
        pv.to_parquet(f)
    u = u.merge(pv, on="cond", how="left")
    return u.reset_index(drop=True)


def covered_per_period(u: pd.DataFrame, n: int) -> pd.DataFrame:
    """Variant (diagnosis): rank within each period separately, so the split day 2026-08-25 gets n IS + n OOS."""
    return pd.concat([covered(u[u.period == p], n) for p in ("IS", "burned_OOS")])


def covered(u: pd.DataFrame, n: int) -> pd.DataFrame:
    """Top-n matches per UTC start date by pre-start volume, among ALL regime universe matches (ex-ante)."""
    s = u.sort_values(["date", "prestart_usd", "start", "cond"], ascending=[True, False, True, True],
                      kind="stable")
    return s.groupby("date", sort=False).head(n)


def _prints(path: str, conds: set) -> pd.DataFrame:
    t = pq.read_table(path, columns=["cond", "ts", "p", "usd"], read_dictionary=["cond"]).to_pandas()
    t["cond"] = t.cond.astype(str)
    t = t[t.cond.isin(conds)]
    return t


def build_jumps(u: pd.DataFrame, cov_conds: set) -> pd.DataFrame:
    f = CACHE / "jumps_cov.parquet"
    if f.exists():
        return pd.read_parquet(f)
    is_conds = set(u.loc[u.period == "IS", "cond"]) & cov_conds
    oos_conds = set(u.loc[u.period == "burned_OOS", "cond"]) & cov_conds
    ji = pd.read_parquet(ROOT / "data/derived/jumps_is.parquet")
    ji = ji[ji.cond.isin(is_conds)].copy()
    pi = _prints("data/is_prints.parquet", is_conds)
    po = _prints("data/locked/oos_prints.parquet", oos_conds)  # BURNED OOS
    with open(ROOT / "results/oos_peeks.log", "a") as fh:
        fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} tier0 independent rebuild: OOS prints read for "
                 f"jump onsets + stale price (burned OOS, non-blind, labelled)\n")
    # check: jump_onsets on the IS print table reproduces jumps_is on a sample of covered IS matches
    rng = np.random.default_rng(123)
    chk = rng.choice(sorted(is_conds), 30, replace=False)
    n_ok = 0
    for c in chk:
        g = pi[pi.cond == c]
        on = jump_onsets(g.ts.to_numpy(float), g.p.to_numpy(), g.usd.to_numpy())
        a = np.array([o[0] for o in on]) if on else np.array([])
        b = np.sort(ji.loc[ji.cond == c, "onset_ts"].to_numpy())
        n_ok += int(len(a) == len(b) and np.allclose(np.sort(a), b))
    print(f"jump detector check: {n_ok}/30 IS matches reproduce jumps_is exactly")
    rows = []
    for c, g in po.groupby("cond", sort=False):
        on = jump_onsets(g.ts.to_numpy(float), g.p.to_numpy(), g.usd.to_numpy())
        rows += [(c, o[0], o[1], o[2], o[3]) for o in on]
    jo = pd.DataFrame(rows, columns=["cond", "onset_ts", "dir", "size", "detect_ts"])
    j = pd.concat([ji, jo], ignore_index=True)
    # stale price: VWAP of outcome-0 prints in [onset-63, onset-3)
    pr = pd.concat([pi, po], ignore_index=True)
    ref = np.full(len(j), np.nan)
    ref_s = np.full(len(j), np.nan)
    pr_g = {c: g for c, g in pr.groupby("cond", sort=False)}
    for c, idx in j.groupby("cond").groups.items():
        g = pr_g.get(c)
        if g is None:
            continue
        ts = g.ts.to_numpy(float); p = g.p.to_numpy(); w = g.usd.to_numpy()
        o = np.argsort(ts, kind="stable"); ts, p, w = ts[o], p[o], w[o]
        pv = np.concatenate([[0.0], np.cumsum(p * w)]); vv = np.concatenate([[0.0], np.cumsum(w)])
        on = j.loc[idx, "onset_ts"].to_numpy(float)
        for arr, (lo, hi) in ((ref, (63, 3)), (ref_s, (33, 1))):
            a = np.searchsorted(ts, on - lo, "left"); b = np.searchsorted(ts, on - hi, "left")
            vol = vv[b] - vv[a]
            arr[np.asarray(idx)] = np.where(vol > 0, (pv[b] - pv[a]) / np.where(vol > 0, vol, 1), np.nan)
    j["ref"] = ref
    j["ref_short"] = ref_s
    j.to_parquet(f)
    return j


def load_live_pool() -> pd.DataFrame:
    """Live points (2026-10-03, 1 s regime) with a book move >= 3c: timing + stale depth, sampled jointly."""
    m = pd.read_csv(ROOT / "research/v2/latency/out/m1_points.csv")
    s = pd.read_csv(ROOT / "research/v2/latency/out/stale_depth.csv")
    m = m[m.book_vs_T_s.notna()]
    p = s.merge(m[["slug", "n", "book_vs_T_s"]], on=["slug", "n"], how="inner")
    p = p[p.D >= 0.03 - 1e-9].reset_index(drop=True)
    v = pd.read_csv(ROOT / "results/tier0/inputs/live_match_volumes.csv")[["slug", "volume"]]
    p = p.merge(v.rename(columns={"volume": "v_live"}), on="slug", how="left")
    assert len(p) == 265 and p.v_live.notna().all(), (len(p), p.v_live.isna().sum())
    assert abs(p.book_vs_T_s.median() - (-1.32)) < 0.01
    assert abs(p.usd_pre2s.median() - 810) < 1 and abs(p.usd_pre.median() - 353) < 1
    return p


def load_cv() -> tuple[np.ndarray, np.ndarray]:
    """Own 120 fps camera: test recall (snapshot rule) and pooled test + train-OOF precision, leads 0-100 ms."""
    d = json.load(open(ROOT / "results/tracking/summary.json"))["early_call"]
    te, tr = d["precision_recall_test_snapshot"], d["precision_recall_train_oof_snapshot"]
    rec, prec = [], []
    for L in LEADS_MS:
        k = f"{L}ms"
        rec.append(te[k]["recall"])
        tp = te[k]["tp"] + tr[k]["tp"]; fp = te[k]["fp"] + tr[k]["fp"]
        prec.append(tp / (tp + fp))
    rec = np.minimum.accumulate(np.array(rec))  # monotone: callable at L => callable at any shorter lead
    prec = np.array(prec)
    assert np.allclose(rec, [0.585, 0.463, 0.268, 0.146], atol=6e-4), rec
    assert np.allclose(prec, [0.888, 0.945, 0.959, 0.971], atol=6e-4), prec
    return rec, prec


def load_mix() -> dict:
    mix = json.load(open(ROOT / "results/tier0/inputs/point_mix.json"))
    return {True: mix["men"]["out"], False: mix["women"]["out"]}


# ----------------------------------------------------------------- simulation
def depth_at(tau, d2, d1, d025, dpost):
    """Stale $ reachable when arriving tau s before the reprice (tau<0: after)."""
    pre = np.where(tau >= 2, d2,
          np.where(tau >= 1, d1 + (d2 - d1) * (tau - 1),
          np.where(tau >= 0.25, d025 + (d1 - d025) * (tau - 0.25) / 0.75, d025)))
    post = d025 + (dpost - d025) * np.clip(-tau / 0.5, 0, 1)
    return np.where(tau >= 0, pre, post)


def simulate(J: pd.DataFrame, pool: pd.DataFrame, rec, prec, out_share, prm: dict, seed: int = 0,
             ext_draws: dict | None = None) -> pd.DataFrame:
    """One row per call (covered jump, stale token price in zone). Returns the call table with fills.
    ext_draws (diagnosis only): {'end','rec','prec','k'} arrays aligned with J, replacing the RNG."""
    rng = np.random.default_rng(seed)
    n = len(J)
    u_end, u_rec, u_prec = rng.random(n), rng.random(n), rng.random(n)
    k = rng.integers(0, len(pool), n)
    if ext_draws is not None:
        u_end, u_rec, u_prec, k = ext_draws["end"], ext_draws["rec"], ext_draws["prec"], ext_draws["k"]
    q = np.where(J.dir.to_numpy() > 0, J.ref.to_numpy(), 1 - J.ref.to_numpy())
    size = J["size"].to_numpy()
    is_out = u_end < out_share
    # longest usable lead with recall >= u (recall is decreasing in lead); none -> called at the event
    callable_ = u_rec[:, None] <= rec[None, :]
    has = is_out & callable_[:, 0]
    li = np.where(has, callable_.sum(1) - 1, -1)
    lead = np.where(li >= 0, LEADS_MS[np.maximum(li, 0)] / 1000.0, 0.0)
    precision = np.where(li >= 0, prec[np.maximum(li, 0)], prm["p_event"])
    correct = u_prec < precision
    arrival = -lead + prm["inference"] + J.lat_s.to_numpy() + prm["gateway"] + J.delay.to_numpy() + prm["shift"]
    t_rep = pool.book_vs_T_s.to_numpy()[k] + prm["stamp_lag"]
    tau = t_rep - arrival
    scale = np.minimum(1.0, J.volume.to_numpy() / pool.v_live.to_numpy()[k])
    d2, d1, d025, dpost = (pool[c].to_numpy()[k] * scale for c in ("usd_pre2s", "usd_pre1s", "usd_pre", "usd_post"))
    frac = np.minimum(0.5 + np.abs(np.minimum(tau, 0)), 1.0)  # share of the jump already printed after reprice
    # correct call: buy the favoured token
    dep_c = prm["phi"] * depth_at(tau, d2, d1, d025, dpost)
    late = tau < 0
    px_c = q + np.where(late, frac * size, 0.0) + prm["slip"]
    if prm["need_lead"] > 0:
        # stress (ii): the existing fast tier is ahead of us in the queue; we fill only if we arrive
        # need_lead s or more before the reprice (no fills in [0, need_lead) or in the decay window)
        ok_c = tau >= prm["need_lead"]
    else:
        ok_c = tau >= -0.5  # never chase beyond the 0.5 s decay window
    sh_c = np.where(ok_c & (px_c < 1), np.minimum(prm["trade_cap"] / px_c, dep_c / px_c), 0.0)
    # wrong call: buy the other token; no competition (no phi); always taken; price moved toward us if late
    qw = 1 - q
    px_w = qw - np.where(late, frac * size, 0.0) + prm["slip"]
    dep_w = depth_at(np.maximum(tau, 0), d2, d1, d025, dpost)
    sh_w = np.where(px_w > 0, np.minimum(prm["trade_cap"] / px_w, dep_w / px_w), 0.0)
    out = J[["cond", "onset_ts", "dir", "size", "res0", "fee_rate", "period", "region"]].copy()
    out["q"] = q
    out["correct"] = correct
    out["lead"] = lead
    out["early"] = li >= 0
    out["tau"] = tau
    out["px"] = np.where(correct, px_c, px_w)
    out["sh_want"] = np.where(correct, sh_c, sh_w)
    out["d0"] = np.where(correct, 1.0, -1.0) * J.dir.to_numpy()  # +1: buys outcome-0 token
    return apply_net_cap(out, prm["net_cap"])


def apply_net_cap(c: pd.DataFrame, cap: float) -> pd.DataFrame:
    c = c.sort_values(["cond", "onset_ts"], kind="stable").reset_index(drop=True)
    sh = c.sh_want.to_numpy().copy(); d = c.d0.to_numpy(); cond = c.cond.to_numpy()
    net, prev = 0.0, None
    for i in range(len(c)):
        if cond[i] != prev:
            net, prev = 0.0, cond[i]
        if sh[i] <= 0:
            sh[i] = 0.0
            continue
        s = min(sh[i], max(0.0, cap - d[i] * net)) if np.isfinite(cap) else sh[i]
        if s < 1e-9:  # float dust left by the cap arithmetic is no fill
            s = 0.0
        sh[i] = s
        net += d[i] * s
    c["shares"] = sh
    payout = np.where(c.d0 > 0, c.res0, 1 - c.res0)
    c["pnl"] = sh * (payout - c.px) - sh * c.fee_rate * c.px * (1 - c.px)
    return c


# ----------------------------------------------------------------- metrics
def metrics(c: pd.DataFrame, period: str, boot: int = 1000) -> dict:
    lo, hi = {"IS": ("2026-05-15", "2026-08-25"), "burned_OOS": ("2026-08-25", "2026-10-03")}[period]
    days = pd.date_range(lo, hi, freq="D", tz="UTC")
    t = c[c.shares > 1e-9].copy()
    t["date"] = pd.to_datetime(t.onset_ts, unit="s", utc=True).dt.floor("D")
    daily = t.groupby("date").pnl.sum().reindex(days, fill_value=0.0)
    cum = daily.cumsum()
    dd = (cum - np.maximum.accumulate(np.maximum(cum, 0))).min()
    sharpe = daily.mean() / daily.std(ddof=1) * np.sqrt(365)
    month = daily.groupby(daily.index.strftime("%Y-%m")).sum()
    # per share, match-clustered bootstrap
    g = t.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
    rng = np.random.default_rng(1)
    idx = rng.integers(0, len(g), (boot, len(g)))
    ps = g.p.to_numpy()[idx].sum(1) / g.s.to_numpy()[idx].sum(1) * 100
    # capital: each position locks shares*price for 4 h
    ev = np.concatenate([t.onset_ts.to_numpy(), t.onset_ts.to_numpy() + 4 * 3600])
    amt = np.concatenate([(t.shares * t.px).to_numpy(), -(t.shares * t.px).to_numpy()])
    o = np.lexsort((amt, ev))  # at equal times release before lock
    peak = np.cumsum(amt[o]).max()
    pnl = t.pnl.sum()
    cap_usd = 3 * peak
    n_calls = len(c)
    fills_c = int(((c.shares > 1e-9) & c.correct).sum())
    want = c.correct & (c.sh_want > 0)
    blocked = (want & (c.shares <= 1e-9)).sum() / max(1, c.correct.sum())  # fully blocked; denominator = all correct calls
    clipped = (want & (c.shares < c.sh_want - 1e-9)).sum() / max(1, want.sum())  # blocked or partly cut
    return {
        "n_calls": n_calls, "n_trades": int(len(t)), "fill_rate": round(fills_c / n_calls, 4),
        "calls_before_reprice": round(float((c.tau >= 0).mean()), 4),
        "calls_in_decay": round(float(((c.tau < 0) & (c.tau >= -0.5)).mean()), 4),
        "calls_too_late": round(float((c.tau < -0.5).mean()), 4),
        "median_tau_s": round(float(c.tau.median()), 3),
        "early_out_call_share": round(float(c.early.mean()), 4),
        "correct_calls_blocked_by_net_cap": round(float(blocked), 4),
        "correct_calls_blocked_or_cut_by_net_cap": round(float(clipped), 4),
        "per_share_c": round(pnl / t.shares.sum() * 100, 3),
        "per_share_ci95_c": [round(float(np.percentile(ps, 2.5)), 3), round(float(np.percentile(ps, 97.5)), 3)],
        "pnl_usd": round(pnl, 1), "days": len(days), "pnl_per_day": round(pnl / len(days), 1),
        "sharpe_ann": round(float(sharpe), 2), "max_dd_usd": round(float(min(dd, 0)), 1),
        "worst_day_usd": round(float(daily.min()), 1),
        "months_positive": f"{int((month > 0).sum())}/{len(month)}",
        "capital_usd": round(cap_usd, 0), "roc_pct": round(pnl / cap_usd * 100, 1),
        "roc_ann_pct": round(pnl / cap_usd * 100 * 365 / len(days), 1),
        "pnl_wrong_usd": round(float(t.loc[~t.correct, "pnl"].sum()), 1),
        "wrong_share_of_trades": round(float((~t.correct).mean()), 4),
        "n_matches": int(t.cond.nunique()), "median_usd_per_fill": round(float((t.shares * t.px).median()), 1),
    }


def run(J, pool, rec, prec, mix, prm, seed=0, boot=1000):
    out_share = np.where(J.men.to_numpy(), mix[True], mix[False])
    c = simulate(J, pool, rec, prec, out_share, prm, seed)
    return {p: metrics(c[c.period == p], p, boot) for p in ("IS", "burned_OOS")}, c


def main():
    quick = "--quick" in sys.argv
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True); CACHE.mkdir(parents=True, exist_ok=True)
    u = load_universe()
    print(f"universe 1 s regime: {len(u)} matches ({(u.period == 'IS').sum()} IS, "
          f"{(u.period != 'IS').sum()} burned OOS); tapes missing {(~u.has_tape).sum()}")
    cov = covered(u, PRIMARY["coverage"])
    cov_pp = covered_per_period(u, PRIMARY["coverage"])
    print("covered:", cov.groupby("period").size().to_dict(),
          "| per-period ranking:", cov_pp.groupby("period").size().to_dict(),
          "| median final volume:", cov.groupby("period").volume.median().round(0).to_dict())
    j = build_jumps(u, set(cov.cond) | set(cov_pp.cond))

    def calls_for(cv, verbose=False, stale="ref"):
        J = j.copy()
        J["ref"] = J[stale]
        J = J.merge(cv[["cond", "res0", "fee_rate", "delay", "volume", "men", "region", "period", "league",
                        "title"]], on="cond", how="inner")
        J["lat_s"] = J.region.map(REGION_MS) / 1000.0
        if verbose:
            print("covered jumps:", J.groupby("period").size().to_dict(), "ref missing:", int(J.ref.isna().sum()))
        J = J[J.ref.notna()]
        q = np.where(J.dir > 0, J.ref, 1 - J.ref)  # stale price of the point-winner's token
        J = J[(q >= PRIMARY["zone"][0]) & (q <= PRIMARY["zone"][1])].reset_index(drop=True)
        if verbose:
            print("calls (in zone):", J.groupby("period").size().to_dict())
            print("calls by region:", J.groupby(["period", "region"]).size().to_dict())
            print("unmapped leagues among calls:", sorted(J.loc[J.region == "unmapped", "league"].unique()))
        return J

    J = calls_for(cov, verbose=True)
    J_pp = calls_for(cov_pp)
    J_rs = calls_for(cov, stale="ref_short")
    pool = load_live_pool(); rec, prec = load_cv(); mix = load_mix()

    res = {"label": LABEL, "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in PRIMARY.items()}}
    prim, calls = run(J, pool, rec, prec, mix, PRIMARY)
    res["primary"] = prim
    calls.to_parquet(CACHE / "primary_calls.parquet")
    stress = {
        "i_stamp_lag_1.0": dict(PRIMARY, stamp_lag=1.0),
        "ii_beat_reprice_by_0.25s": dict(PRIMARY, need_lead=0.25),
        "ii_b_add_0.25s_latency": dict(PRIMARY, shift=0.25),
        "i+ii_lag1.0_and_beat_by_0.25s": dict(PRIMARY, stamp_lag=1.0, need_lead=0.25),
    }
    res["stress"] = {k: run(J, pool, rec, prec, mix, p)[0] for k, p in stress.items()}
    res["variant_coverage_ranked_per_period"] = run(J_pp, pool, rec, prec, mix, PRIMARY)[0]
    # supplementary (not pre-registered as primary): near stale price VWAP [onset-33, onset-1), see DEVIATIONS T2
    res["supp_ref_short"] = {"primary": run(J_rs, pool, rec, prec, mix, PRIMARY)[0]}
    res["supp_ref_short"].update({k: run(J_rs, pool, rec, prec, mix, p)[0] for k, p in stress.items()})
    if not quick:  # Monte Carlo spread of the stress tests (seeds 1-20)
        sp = {}
        for name, (JJ, p) in {**{k: (J, v) for k, v in stress.items()},
                              **{f"ref_short|{k}": (J_rs, v) for k, v in
                                 {"primary": PRIMARY, **stress}.items()}}.items():
            vals = {q_: [] for q_ in ("IS", "burned_OOS")}
            for s_ in range(1, 21):
                r, _ = run(JJ, pool, rec, prec, mix, p, seed=s_, boot=10)
                for q_ in vals:
                    vals[q_].append((r[q_]["pnl_per_day"], r[q_]["sharpe_ann"], r[q_]["per_share_c"]))
            sp[name] = {q_: {"pnl_per_day": [round(float(np.mean([x[0] for x in v])), 1),
                                             round(float(np.std([x[0] for x in v], ddof=1)), 1)],
                             "sharpe": [round(float(np.mean([x[1] for x in v])), 2),
                                        round(float(np.std([x[1] for x in v], ddof=1)), 2)],
                             "per_share_c": [round(float(np.mean([x[2] for x in v])), 3),
                                             round(float(np.std([x[2] for x in v], ddof=1)), 3)]}
                        for q_, v in vals.items()}
        res["stress_seeds_1_20_mean_sd"] = sp
    if not quick:
        seeds = {p: [] for p in ("IS", "burned_OOS")}
        for s in range(1, 21):
            r, _ = run(J, pool, rec, prec, mix, PRIMARY, seed=s, boot=50)
            for p in seeds:
                seeds[p].append((r[p]["pnl_per_day"], r[p]["sharpe_ann"], r[p]["per_share_c"], r[p]["fill_rate"]))
        res["seeds_1_20"] = {p: {"pnl_per_day_mean_sd": [round(float(np.mean([x[0] for x in v])), 1),
                                                         round(float(np.std([x[0] for x in v], ddof=1)), 1)],
                                 "sharpe_mean_sd": [round(float(np.mean([x[1] for x in v])), 2),
                                                    round(float(np.std([x[1] for x in v], ddof=1)), 2)],
                                 "per_share_c_mean_sd": [round(float(np.mean([x[2] for x in v])), 3),
                                                         round(float(np.std([x[2] for x in v], ddof=1)), 3)],
                                 "fill_rate_mean_sd": [round(float(np.mean([x[3] for x in v])), 4),
                                                       round(float(np.std([x[3] for x in v], ddof=1)), 4)]}
                             for p, v in seeds.items()}
    json.dump(res, open(OUT / "rebuild.json", "w"), indent=1, default=float)
    print(json.dumps(res, indent=1, default=float))
    print(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
