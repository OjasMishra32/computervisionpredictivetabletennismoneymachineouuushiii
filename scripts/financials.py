"""COURTSIDE financials: P&L waterfall, unit economics, capital and returns, capacity, for every strategy.

    .venv/bin/python scripts/financials.py          # 20-60 s, 1 process

Re-runnable. It reads whatever result files exist; a strategy or period whose file is missing is reported
as "pending" and picked up on the next run. Outputs:
    results/financials/financials.json      every number below, plus the cost assumptions and their sources
    research/financials/FINANCIALS.md       the write-up (generated from the JSON)
    results/financials/fig_waterfall.png    one waterfall per strategy, IS and OOS side by side ($ per day)

Where the numbers come from
  * v2 / v2-safe: trade-level books. The frozen engine (research/v2/sizing/engine.py via src.v2) is re-run
    on the cached causal feature tables of scripts/lowloss_test.py (data/v2_lowloss/features_*.parquet).
    The 1x books must equal the canonical trade files (data/v2_trades_is_oos.parquet,
    data/v2_lowloss/trades_{a,b}_v2_safe.parquet, data/expand_v2_trades.parquet) or the script stops.
    The same engine at 0.5x / 2x / 5x size (every size cap scaled) and with no caps at all (we take every
    qualifying fast-tier print in full) is the capacity curve. The engine never takes more shares than
    the fast-tier print it copies; it has no price-impact model beyond that cap.
  * tier-0 CV edge (COUNTERFACTUAL, assumed licensed feed + courtside camera, not purchased):
    results/tier0/results.json, the verifier-corrected headline (key "headline"). If that key is
    missing the revision is still running and tier-0 is "pending". The refuted pre-registered primary is
    never used as an estimate.
  * maker v1 (side markets): the walk-forward IS book data/v2_crossmarket/wf_lean_maker.parquet;
    the blind OOS fill book research/v2/maker/oos/book_v1.csv with results/maker/oos.json (verdict, capital,
    stresses), and the live paper session from results/live/summary.json when they
    exist.
  * forward test (results/v2/forward.json) and table tennis (results/tt/results.json): when they exist.
External costs are ESTIMATES from cited public prices, or labelled ASSUMPTIONS where no public price
exists (COSTS below). Nothing here places orders or uses keys.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import v2  # noqa: E402

E = v2.E
OUT_JSON = ROOT / "results/financials/financials.json"
OUT_FIG = ROOT / "results/financials/fig_waterfall.png"
OUT_MD = ROOT / "research/financials/FINANCIALS.md"
CACHE = ROOT / "data/v2_lowloss"
CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")       # IS / OOS split by match start (all lenses)
SEED = 20261003
N_BOOT_DAYS = 10_000
N_BOOT_MATCH = 2_000
DPM = 365 / 12                                          # days per month
SCALES = [0.5, 1.0, 2.0, 5.0, "all"]
RETRIEVED = "2026-10-03"

# ------------------------------------------------------------------------------------------ costs
# Every external number has a URL. label: ESTIMATE = a public list price applied to our use;
# ASSUMPTION = no public price exists, the range is ours and says what it is anchored to.
TBILL = {"rate": 0.0400, "label": "ESTIMATE",
         "what": "3-month US Treasury bill, secondary market, discount basis, 2026-10-01 (FRED DTB3)",
         "url": "https://fred.stlouisfed.org/series/DTB3", "retrieved": RETRIEVED}

AWS_PRICE_LIST = ("https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/"
                  "ec2-ondemand-without-sec-sel/EU%20(London)/Linux/index.json")
AWS_H = {"t3.medium": 0.0472, "c7i.large": 0.10605, "c6in.large": 0.1344,       # $/h, EU (London), Linux,
         "g4dn.xlarge": 0.615, "g6.xlarge": 1.0216}                              # on demand, list 2026-09-25
HOURS_PER_MONTH = 730
# public launch list prices (retrieved 2026-10-03): GoPro press release (Sep 2024), NVIDIA developer blog (Dec 2024)
KIT_PRICES = {"gopro_hero13_black": 399.0, "jetson_orin_nano_super": 249.0}
KIT_LOW = sum(KIT_PRICES.values())

COSTS = {
    "feed_licence": {
        "name": "Official live ATP/WTA point-data feed licence",
        "label": "ASSUMPTION (no public price exists)",
        "unit": "$/month",
        "low": 1_250.0, "central": 5_000.0, "high": 10_000.0,
        "basis": ("No public price exists for an official low-latency ATP/WTA point feed (Sportradar / Tennis "
                  "Data Innovations for ATP and Challenger, Stats Perform RunningBall for WTA): access is by "
                  "sales quote. The range is anchored to reported figures: Sportradar API 'from $1,250/month' "
                  "(LSports guide, low); 'starter contracts typically $5,000 to $10,000/month' and '$10,000+/month' "
                  "for enterprise (SharpAPI, a competitor's unverified claim; central and high). Stats Perform "
                  "says its WTA feed is faster than the umpire feed on 80% of points; it lists no price."),
        "sources": ["https://www.lsports.eu/blog/sports-data-cost/",
                    "https://sharpapi.io/compare/sportradar-alternative",
                    "https://www.statsperform.com/products/official-wta-data-streaming/"]},
    "vps_london": {
        "name": "London gateway VPS (AWS eu-west-2, on-demand Linux)",
        "label": "ESTIMATE (public list price)",
        "unit": "$/month",
        "low": AWS_H["t3.medium"] * HOURS_PER_MONTH, "central": AWS_H["c7i.large"] * HOURS_PER_MONTH,
        "high": AWS_H["c6in.large"] * HOURS_PER_MONTH,
        "basis": ("t3.medium $0.0472/h (low), c7i.large $0.10605/h (central), c6in.large $0.1344/h "
                  "(network-optimised, high), x 730 h/month; AWS public price list for EU (London), published "
                  "2026-09-25. Hetzner has no London location (Germany, Finland, US, Singapore); its CX23 "
                  "(2 vCPU, 4 GB) lists at EUR 5.49 / $6.49 a month, a non-co-located reference only."),
        "sources": [AWS_PRICE_LIST, "https://www.hetzner.com/cloud/", "https://costgoat.com/pricing/hetzner"]},
    "polymarket_api": {
        "name": "Polymarket CLOB / data API", "label": "ESTIMATE (public documentation)", "unit": "$/month",
        "low": 0.0, "central": 0.0, "high": 0.0,
        "basis": ("No subscription, key or paid tier is documented; limits are IP-based Cloudflare throttling. "
                  "Trading fees are not infrastructure: they are in the waterfall (taker fee "
                  "C x feeRate x p(1-p), sports feeRate 0.05, 15% maker rebate)."),
        "sources": ["https://docs.polymarket.com/quickstart/introduction/rate-limits",
                    "https://docs.polymarket.com/polymarket-learn/trading/fees"]},
    "hipergator": {
        "name": "HiPerGator (training, backtests)", "label": "ESTIMATE ($0 marginal: university allocation)", "unit": "$/month",
        "low": 0.0, "central": 0.0, "high": 0.0,
        "basis": ("$0 marginal cost to the team (UF allocation). List-price equivalent if bought: $620 per GPU "
                  "(NGU) per year and $44 per CPU core (NCU) per year (UF Research Computing service rates), "
                  "about $52 per GPU-month."),
        "sources": ["https://it.ufl.edu/rc/get-started/price-list"]},
    "camera_operator": {
        "name": "Courtside camera operator (tier-0 only)", "label": "ESTIMATE", "unit": "$/hour",
        "low": 36.10, "central": 36.10, "high": 36.10,
        "basis": ("BLS Occupational Outlook Handbook: $36.10/h is the 2025 median hourly pay of the combined 'film and video "
                  "editors and camera operators' group; camera operators (television, video and film) alone earn a median "
                  "$74,990/yr (May 2025), about $36.05/h at 2,080 h. Wage only: no employer on-costs, travel or "
                  "agency margin."),
        "sources": ["https://www.bls.gov/ooh/media-and-communication/film-and-video-editors-and-camera-operators.htm"]},
    "gpu_inference": {
        "name": "Cloud GPU for CV inference, per covered event hour (tier-0 only)", "label": "ESTIMATE (public list price)",
        "unit": "$/hour", "low": AWS_H["g4dn.xlarge"], "central": AWS_H["g4dn.xlarge"], "high": AWS_H["g6.xlarge"],
        "basis": ("AWS EU (London) on demand: g4dn.xlarge (1x T4) $0.615/h; g6.xlarge (1x L4) $1.0216/h (high). "
                  "On-venue inference on our own hardware would replace this; HiPerGator is not a live venue."),
        "sources": [AWS_PRICE_LIST]},
    "event_hours": {
        "name": "Operator + GPU hours per covered match (tier-0 only)", "label": "ASSUMPTION", "unit": "hours/event",
        "low": 3.0, "central": 4.0, "high": 5.0,
        "basis": "A best-of-3 match plus set-up. Central = the repo's 4 h ex-ante capital lock per position (src/v2.py LOCK_S).",
        "sources": []},
    "venue_access": {
        "name": "Camera position / venue access fee per event (tier-0 only)", "label": "ASSUMPTION (no public price exists)",
        "unit": "$/event", "low": 0.0, "central": 250.0, "high": 500.0,
        "basis": ("A legal tier-0 needs the organiser's permission for a camera (courtsiding breaches ticket terms, "
                  "docs/NOTE.md section 5). No public price exists for that right. Range is ours; low = $0."),
        "sources": []},
    "camera_kit": {
        "name": "120 fps camera kit, amortised over 24 months (tier-0 only)",
        "label": "ESTIMATE (low: public list prices) / ASSUMPTION (central, high)",
        "unit": "$/kit", "low": KIT_LOW, "central": 1_000.0, "high": 2_000.0,
        "basis": (f"Hardware per covered court (camera, lens, mount, edge box). Low = public launch list prices of a "
                  f"consumer 120 fps camera (GoPro HERO13 Black, ${KIT_PRICES['gopro_hero13_black']:.0f}) plus an edge "
                  f"inference box (NVIDIA Jetson Orin Nano Super Developer Kit, ${KIT_PRICES['jetson_orin_nano_super']:.0f}), "
                  "no mount or cabling. Central and high are ours (no quote for a rugged or machine-vision kit was "
                  "obtained). An on-venue edge box would replace the cloud GPU hours above, so the stack counts "
                  "inference twice; that is conservative and small next to the operator."),
        "sources": ["https://investor.gopro.com/press-releases/press-release-details/2024/GoPro-Announces-Two-New-Cameras-The-399-HERO13-Black-and-the-199-HERO/default.aspx",
                    "https://developer.nvidia.com/blog/nvidia-jetson-orin-nano-developer-kit-gets-a-super-boost/"]},
}
CAMERA_LIFE_MONTHS = 24

# Which fixed costs each strategy carries, and why.
STACKS = {
    "v2": {"monthly": ["feed_licence", "vps_london", "polymarket_api", "hipergator"],
           "note": ("v2 trades at the fast tier's own fills, so running it means being in the fast tier. That needs a "
                    "signal about 2.5 s before the official stamp (docs/NOTE.md section 6); an official feed licence "
                    "is a necessary cost, not a sufficient one. The cost stack is a lower bound.")},
    "v2_safe": {"monthly": ["feed_licence", "vps_london", "polymarket_api", "hipergator"],
                "note": "Same infrastructure as v2."},
    "tier0": {"monthly": ["feed_licence", "vps_london", "polymarket_api", "hipergator"], "per_event": True,
              "note": "Feed licence + London gateway + one camera, operator and GPU per covered match (coverage from the scenario)."},
    "maker": {"monthly": ["vps_london", "polymarket_api", "hipergator"],
              "note": "Public moneyline websocket + quoting in side markets: no licensed data, no camera."},
    "tt": {"monthly": ["vps_london", "polymarket_api", "hipergator"], "note": "Same remote stack as the maker."},
}

PENDING = "pending"


# ---------------------------------------------------------------------------------------- helpers
def jload(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def clean(x):
    """JSON-safe: numpy -> python, NaN/inf -> None."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return x if math.isfinite(x) else None
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp, dt.date)):
        return str(x)[:10]
    return x


def cost_level(key: str, lvl: str) -> float:
    return float(COSTS[key][lvl])


def cost_stack(strategy: str, events_per_day: float | None = None) -> dict:
    """Fixed costs per month and per day, low / central / high, with the line items."""
    s = STACKS[strategy]
    out = {"note": s["note"], "items": {}, "monthly": {}, "daily": {}}
    for lvl in ("low", "central", "high"):
        tot = 0.0
        for k in s["monthly"]:
            v = cost_level(k, lvl)
            out["items"].setdefault(k, {})[lvl] = v
            tot += v
        if s.get("per_event"):
            if events_per_day is None:
                out["monthly"][lvl] = None
                continue
            h = cost_level("event_hours", lvl)
            per_event = h * (cost_level("camera_operator", lvl) + cost_level("gpu_inference", lvl)) + cost_level("venue_access", lvl)
            kits = events_per_day * cost_level("camera_kit", lvl) / CAMERA_LIFE_MONTHS
            ev_month = events_per_day * DPM * per_event + kits
            out["items"].setdefault("per_event_total", {})[lvl] = per_event
            out["items"].setdefault("events_per_day", {})[lvl] = events_per_day
            out["items"].setdefault("camera_operator_gpu_access_month", {})[lvl] = events_per_day * DPM * per_event
            out["items"].setdefault("camera_kits_amortised_month", {})[lvl] = kits
            tot += ev_month
        out["monthly"][lvl] = tot
        out["daily"][lvl] = tot / DPM
    return out


def daily_cal(b: pd.DataFrame) -> pd.Series:
    """Calendar-day, zero-filled daily P&L from the first to the last trade day (engine convention)."""
    return E.daily_series(b)


def peak_locked(b: pd.DataFrame) -> float:
    return E.peak_locked(b)


def drawdown(daily: pd.Series) -> dict:
    eq = daily.cumsum()
    eq0 = pd.concat([pd.Series([0.0], index=[daily.index[0] - pd.Timedelta(days=1)]), eq])
    peak = eq0.cummax()
    dd = eq0 - peak
    trough = dd.idxmin()
    mdd = float(dd.min())
    if mdd >= 0:
        return {"max_dd_usd": 0.0, "peak_date": None, "trough_date": None, "recovery_date": None,
                "days_trough_to_recovery": 0, "days_peak_to_recovery": 0, "recovered": True}
    pk_val = float(peak.loc[trough])
    pk_date = eq0.loc[:trough][eq0.loc[:trough] >= pk_val - 1e-9].index[-1]
    after = eq0.loc[trough:]
    rec = after[after >= pk_val - 1e-9]
    rec_date = rec.index[0] if len(rec) else None
    return {"max_dd_usd": mdd, "peak_date": pk_date, "trough_date": trough, "recovery_date": rec_date,
            "recovered": rec_date is not None,
            "days_trough_to_recovery": int((rec_date - trough).days) if rec_date is not None else None,
            "days_peak_to_recovery": int((rec_date - pk_date).days) if rec_date is not None else None,
            "days_since_trough_unrecovered": None if rec_date is not None else int((eq0.index[-1] - trough).days)}


def cluster_rate_ci(flag: np.ndarray, cond: np.ndarray, seed: int) -> list[float]:
    g = pd.DataFrame({"c": cond, "w": flag.astype(float)}).groupby("c").w.agg(["sum", "size"])
    W, N = g["sum"].to_numpy(), g["size"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (N_BOOT_MATCH, len(g)))
    r = W[idx].sum(1) / N[idx].sum(1)
    return [float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))]


# ------------------------------------------------------------------------------- book statistics
def book_stats(b: pd.DataFrame, cost: dict, label: str, source: str, lock_note: str,
               capital: float | None = None, ts_exact: bool = True) -> dict:
    """Everything for one trade-level book. b columns: cond, ts, date, month, shares, usd_in, pnl, pnl_ps,
    gross_ps, fee_ps, rebate_ps, slip_ps, hold_h, lock_end. pnl = shares*(gross - fee + rebate - slip)."""
    b = b[b.month >= E.EVAL_START].copy()
    m = E.metrics(b, capital=capital)                  # the repo's own metric function (CIs, capital)
    if capital is not None:                            # capital taken from the repo (timestamps not exact here)
        m["peak_locked_usd"] = capital / E.CAPITAL_BUFFER
    daily = daily_cal(b)
    T = len(daily)
    cap = float(m["capital_usd"])
    sh = b.shares.to_numpy()
    S = sh.sum()
    comp = {k: float((sh * b[c].to_numpy()).sum()) for k, c in
            (("gross", "gross_ps"), ("fee", "fee_ps"), ("rebate", "rebate_ps"), ("slip", "slip_ps"))}
    net = float(b.pnl.sum())
    resid = comp["gross"] - comp["fee"] + comp["rebate"] - comp["slip"] - net
    assert abs(resid) < 1e-6 * max(1.0, abs(net)) + 1e-6, f"{label}: waterfall does not add up ({resid})"
    wf_usd = {"gross_edge": comp["gross"], "taker_fees": -comp["fee"], "maker_rebates": comp["rebate"],
              "slippage_modelled": -comp["slip"], "net_trading": net}
    wf = {"per_share_c": {k: v / S * 100 for k, v in wf_usd.items()},
          "usd_period": wf_usd,
          "usd_per_day": {k: v / T for k, v in wf_usd.items()},
          "stress_half_tick_slippage": {"net_trading_usd": net - 0.005 * S, "net_per_share_c": (net - 0.005 * S) / S * 100,
                                        "net_usd_per_day": (net - 0.005 * S) / T}}
    # fixed costs and break-even
    per_usd = net / b.usd_in.sum()
    cc = {}
    for lvl in ("low", "central", "high"):
        cd = cost["daily"].get(lvl)
        if cd is None:
            continue
        cc[lvl] = {"fixed_cost_usd_per_day": cd, "fixed_cost_usd_period": cd * T,
                   "net_after_costs_usd_per_day": net / T - cd, "net_after_costs_usd_period": net - cd * T,
                   "breakeven_pnl_usd_per_day": cd,
                   "breakeven_notional_usd_per_day": cd / per_usd if per_usd > 0 else None,
                   "breakeven_notional_multiple_of_now": (cd / per_usd) / (b.usd_in.sum() / T) if per_usd > 0 else None}
    coc_reserved = cap * TBILL["rate"] * T / 365
    locked_dollar_hours = float((b.usd_in * b.hold_h).sum()) if ts_exact else float("nan")
    coc_locked = locked_dollar_hours / 8760 * TBILL["rate"]
    for lvl in cc:
        cc[lvl]["net_after_costs_and_cost_of_capital_usd_per_day"] = cc[lvl]["net_after_costs_usd_per_day"] - coc_reserved / T
    # break-even taker fee (PM_REVIEW P03): book held fixed, fee linear in the rate, so scaling every trade's rate by k
    # gives net = gross + rebate - slip - k * fees; k* = (that - fixed costs) / fees. As a rate when one rate applied.
    be_fee = None
    if comp["fee"] > 0:
        pre = comp["gross"] + comp["rebate"] - comp["slip"]
        rates = b["rate"].unique() if "rate" in b else []
        one = float(rates[0]) if len(rates) == 1 else None
        be_fee = {"fee_multiple_before_fixed_costs": pre / comp["fee"], "uniform_rate_charged": one,
                  "rate_before_fixed_costs": pre / comp["fee"] * one if one else None,
                  "fee_share_of_gross": comp["fee"] / comp["gross"] if comp["gross"] else None}
        for lvl in cc:
            k = (pre - cc[lvl]["fixed_cost_usd_per_day"] * T) / comp["fee"]
            be_fee[f"fee_multiple_after_{lvl}_fixed_costs"] = k
            be_fee[f"rate_after_{lvl}_fixed_costs"] = k * one if one else None
    # unit economics
    pnl = b.pnl.to_numpy()
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    g = b.groupby("cond").pnl.sum()
    act = b.groupby("date").pnl.sum()
    ue = {
        "n_trades": int(len(b)), "n_matches": int(b.cond.nunique()), "calendar_days": T, "active_days": int(len(act)),
        "per_trade_usd": float(pnl.mean()), "per_trade_median_usd": float(np.median(pnl)),
        "per_match_usd": float(g.mean()), "match_win_rate": float((g > 0).mean()),
        "per_day_usd": float(daily.mean()), "per_day_median_usd": float(daily.median()),
        "profitable_days_share": float((daily > 0).mean()), "profitable_active_days_share": float((act > 0).mean()),
        "trade_win_rate": float((pnl > 0).mean()),
        "trade_win_rate_ci95_match_clustered": cluster_rate_ci(pnl > 0, b.cond.to_numpy(), SEED),
        "trade_loss_rate": float((pnl < 0).mean()),
        "avg_win_usd": float(wins.mean()) if len(wins) else None,
        "avg_loss_usd": float(losses.mean()) if len(losses) else None,
        "win_loss_ratio": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) else None,
        "expectancy_usd_per_trade": float(pnl.mean()),
        "expectancy_c_per_share": net / S * 100,
        "net_c_per_usd_notional": per_usd * 100,
        "turnover_x_per_year": float(b.usd_in.sum() / cap * 365 / T),
        "hold_hours_to_resolution": ({"median": float(b.hold_h.median()), "p90": float(b.hold_h.quantile(0.9)),
                                      "mean": float(b.hold_h.mean())} if ts_exact else
                                     {"median": None, "p90": None, "mean": None,
                                      "note": "fill timestamps in the source CSV are rounded to 6 significant digits"}),
        "capital_lock_hours_in_capital_model": ({"median": float(((b.lock_end - b.ts) / 3600).median()),
                                                 "p90": float(((b.lock_end - b.ts) / 3600).quantile(0.9)),
                                                 "rule": lock_note} if ts_exact else
                                                {"median": None, "p90": None, "rule": lock_note}),
        "cost_of_capital": {"rate": TBILL["rate"],
                            "on_reserved_capital_usd_period": coc_reserved, "on_reserved_capital_usd_per_day": coc_reserved / T,
                            "on_dollars_actually_locked_usd_period": coc_locked,
                            "share_of_net_trading_pnl": coc_reserved / net if net > 0 else None},
    }
    # capital and returns
    rng = np.random.default_rng(SEED)
    x = daily.to_numpy()
    tot = x[rng.integers(0, T, (N_BOOT_DAYS, T))].sum(1)
    ret_ci = [float(np.percentile(tot, 2.5) / cap * 100), float(np.percentile(tot, 97.5) / cap * 100)]
    ddi = drawdown(daily)
    down = np.minimum(x, 0.0)
    sd = x.std(ddof=1)
    ann = net / cap * 100 * 365 / T
    weekly = daily.resample("W-SUN").sum()
    monthly = daily.groupby(daily.index.tz_localize(None).to_period("M")).sum()
    cr = {
        "capital_usd": cap, "capital_rule": "3 x peak dollars locked (repo convention)",
        "peak_locked_usd": float(m["peak_locked_usd"]),
        "pnl_usd": net, "pnl_ci95_usd_match_clustered": m["total_pnl_ci_usd"],
        "return_on_capital_pct": net / cap * 100,
        "return_on_capital_ci95_pct_day_bootstrap": ret_ci,
        "return_on_capital_ann_pct": ann,
        "return_on_capital_ann_ci95_pct_day_bootstrap": [r * 365 / T for r in ret_ci],
        "sharpe_ann": float(x.mean() / sd * np.sqrt(365)) if sd > 0 else None,
        "sortino_ann": float(x.mean() / np.sqrt((down ** 2).mean()) * np.sqrt(365)) if (down < 0).any() else None,
        "calmar": float(ann / abs(ddi["max_dd_usd"] / cap * 100)) if ddi["max_dd_usd"] < 0 else None,
        "max_dd_usd": ddi["max_dd_usd"], "max_dd_pct": ddi["max_dd_usd"] / cap * 100,
        "max_dd_dates": {k: (str(ddi[k])[:10] if ddi[k] is not None else None) for k in ("peak_date", "trough_date", "recovery_date")},
        "days_trough_to_recovery": ddi["days_trough_to_recovery"],
        "days_peak_to_recovery": ddi["days_peak_to_recovery"],
        "days_since_trough_unrecovered": ddi.get("days_since_trough_unrecovered"),
        "worst_day_usd": float(daily.min()), "worst_day_pct": float(daily.min() / cap * 100),
        "worst_week_usd": float(weekly.min()), "worst_week_pct": float(weekly.min() / cap * 100),
        "worst_month_usd": float(monthly.min()), "worst_month_pct": float(monthly.min() / cap * 100),
        "months_positive": int((monthly > 0).sum()), "months_total": int(len(monthly)),
        "skew_daily": float(st.skew(x, bias=False)), "kurtosis_daily_pearson": float(st.kurtosis(x, fisher=False, bias=False)),
    }
    capy = {"notional_usd_per_day_now": float(b.usd_in.sum() / T), "shares_per_day_now": float(S / T),
            "notional_usd_period": float(b.usd_in.sum())}
    return {"status": "ok", "label": label, "source": source,
            "calendar": [str(daily.index[0].date()), str(daily.index[-1].date())],
            "per_share_c": m["per_share_c"], "per_share_ci95_c_match_clustered": m["per_share_ci_c"],
            "per_fill_mean_c": m["per_print_c"], "per_fill_mean_ci95_c_match_clustered": m["per_print_ci_c"],
            "waterfall": wf, "fixed_costs": cc, "breakeven_taker_fee": be_fee, "unit_economics": ue,
            "capital_returns": cr, "capacity": capy, "_daily": daily}


def summary_block(m: dict, label: str, source: str, cost: dict, extra: dict | None = None) -> dict:
    """A period known only from a summary file (no trade-level data)."""
    def g(*ks):
        for k in ks:
            if k in m and m[k] is not None:
                return m[k]
        return None
    days = g("days", "calendar_days")
    pnl = g("total_pnl_usd", "pnl_usd")
    per_day = g("pnl_per_day_usd") or (pnl / days if pnl is not None and days else None)
    cap = g("capital_usd")
    ci = g("per_share_ci_c", "per_share_ci95_c")
    if ci is None and g("per_share_ci95_c_lo") is not None:
        ci = [g("per_share_ci95_c_lo"), g("per_share_ci95_c_hi")]
    usd_traded = g("usd_traded")
    out = {"status": "ok (summary file only)", "label": label, "source": source,
           "n_trades": g("n_trades"), "n_matches": g("n_matches"), "calendar_days": days,
           "per_share_c": g("per_share_c"), "per_share_ci95_c": ci,
           "pnl_usd": pnl, "pnl_usd_per_day": per_day, "usd_traded": usd_traded,
           "notional_usd_per_day_now": usd_traded / days if usd_traded and days else None,
           "capital_usd": cap, "sharpe_ann": g("sharpe_ann"), "max_dd_usd": g("max_dd_usd"),
           "max_dd_pct": g("max_dd_pct", "max_dd_pct_capital") if g("max_dd_pct", "max_dd_pct_capital") is not None
           else (g("max_dd_usd") / cap * 100 if g("max_dd_usd") is not None and cap else None),
           "worst_day_usd": g("worst_day_usd"),
           "return_on_capital_pct": g("return_on_capital_pct") if g("return_on_capital_pct") is not None
           else (pnl / cap * 100 if pnl is not None and cap else None)}
    if out["return_on_capital_pct"] is not None and days:
        out["return_on_capital_ann_pct"] = out["return_on_capital_pct"] * 365 / days
    cc = {}
    for lvl in ("low", "central", "high"):
        cd = cost["daily"].get(lvl)
        if cd is None or per_day is None:
            continue
        cc[lvl] = {"fixed_cost_usd_per_day": cd, "net_after_costs_usd_per_day": per_day - cd,
                   "breakeven_pnl_usd_per_day": cd}
        if pnl and usd_traded and pnl > 0:
            cc[lvl]["breakeven_notional_usd_per_day"] = cd / (pnl / usd_traded)
    out["fixed_costs"] = cc
    if extra:
        out.update(extra)
    return out


def pending(path: str, why: str) -> dict:
    return {"status": PENDING, "expected_file": path, "why": why}


# ---------------------------------------------------------------------------------- v2 / v2-safe
def std_engine_book(tr: pd.DataFrame) -> pd.DataFrame:
    fee = (tr.rate * tr.q * (1 - tr.q)).to_numpy()
    b = pd.DataFrame({"cond": tr.cond.to_numpy(), "ts": tr.ts.to_numpy(), "date": tr.date.to_numpy(),
                      "month": tr.month.astype(str).to_numpy(), "shares": tr.shares.to_numpy(),
                      "usd_in": tr.usd_in.to_numpy(), "pnl": tr.pnl.to_numpy(), "pnl_ps": tr.pnl_ps.to_numpy(),
                      "gross_ps": tr.gross_res.to_numpy(), "fee_ps": fee, "rebate_ps": 0.0, "slip_ps": 0.0,
                      "hold_h": ((tr.end_ts - tr.ts) / 3600).to_numpy(), "lock_end": tr.lock_end.to_numpy(),
                      "rate": tr.rate.to_numpy()})
    b["date"] = pd.to_datetime(b.date, utc=True)
    assert np.allclose(b.gross_ps - b.fee_ps, b.pnl_ps, atol=1e-12), "engine pnl_ps != gross - fee"
    return b


def same_trades(a: pd.DataFrame, ref: pd.DataFrame) -> bool:
    key = lambda d: d.sort_values(["cond", "ts", "shares"], kind="stable")[["shares", "pnl"]].to_numpy()  # noqa: E731
    return len(a) == len(ref) and np.allclose(key(a), key(ref), rtol=1e-9, atol=1e-9)


def scaled(pol, s):
    if s == "all":   # every qualifying fast-tier print in full: the depth ceiling of the repo's fill model
        return replace(pol, name=pol.name + "_allprints", deploy_frac=1e6, net_cap=np.inf, usd_cap=np.inf,
                       match_cap=np.inf)
    return replace(pol, name=f"{pol.name}_x{s:g}", deploy_frac=pol.deploy_frac * s, net_cap=pol.net_cap * s,
                   usd_cap=pol.usd_cap * s, match_cap=pol.match_cap * s)


def simulate(f, wh, pol):
    E._WCACHE.clear()
    return E.simulate(f, pol, "res", "actual", wh)


def scale_row(tr: pd.DataFrame) -> dict:
    tr = tr[tr.month >= E.EVAL_START]
    if tr.empty:
        return {"n_trades": 0}
    m = E.metrics(tr)
    T = m["days"]
    d = daily_cal(tr)
    dd = drawdown(d)["max_dd_usd"]
    return {"n_trades": m["n_trades"], "per_share_c": m["per_share_c"], "per_share_ci95_c": m["per_share_ci_c"],
            "pnl_usd": m["total_pnl_usd"], "pnl_usd_per_day": m["total_pnl_usd"] / T,
            "notional_usd_per_day": m["usd_traded"] / T, "sharpe_ann": m["sharpe_ann"],
            "capital_usd": m["capital_usd"], "return_on_capital_ann_pct": m["total_pnl_usd"] / m["capital_usd"] * 100 * 365 / T,
            "max_dd_usd": dd, "max_dd_pct": dd / m["capital_usd"] * 100, "days": T}


def v2_books(log) -> dict:
    """Trade-level books for v2 and v2-safe (IS, burned OOS, U2 blind), the capacity curve, reference checks."""
    from src.tape import universe
    u = universe()
    oos_c = set(u.loc[u.oos, "cond"])
    pols = {"v2": v2.POLICY, "v2_safe": replace(v2.POLICY, name="v2_safe_n50", net_cap=50)}
    refs_a = {"v2": ROOT / "data/v2_trades_is_oos.parquet", "v2_safe": CACHE / "trades_a_v2_safe.parquet"}
    refs_b = {"v2": ROOT / "data/expand_v2_trades.parquet", "v2_safe": CACHE / "trades_b_v2_safe.parquet"}
    out = {"books": {}, "scaling": {}, "ceiling": {}, "checks": {}}
    fa, fb = CACHE / "features_u1.parquet", CACHE / "features_u1u2.parquet"
    if not (fa.exists() and (CACHE / "whist_u1.parquet").exists()):
        log("feature cache missing: run scripts/lowloss_test.py first; v2 from its trade file only")
        tr = pd.read_parquet(refs_a["v2"])
        out["books"]["v2"] = {"IS": tr[~tr.cond.isin(oos_c)], "OOS": tr[tr.cond.isin(oos_c)]}
        return out
    f, wh = pd.read_parquet(fa), pd.read_parquet(CACHE / "whist_u1.parquet")
    for name, pol in pols.items():
        out["scaling"][name] = {}
        for s in SCALES:
            tr = simulate(f, wh, scaled(pol, s) if s != 1.0 else pol)
            if s == 1.0:
                ok = refs_a[name].exists() and same_trades(tr, pd.read_parquet(refs_a[name]))
                out["checks"][f"{name}_u1_equals_{refs_a[name].relative_to(ROOT)}"] = bool(ok)
                assert ok, f"{name}: 1x re-simulation differs from {refs_a[name]}"
                out["books"].setdefault(name, {})["IS"] = tr[~tr.cond.isin(oos_c)]
                out["books"][name]["OOS"] = tr[tr.cond.isin(oos_c)]
            key = "all prints" if s == "all" else f"{s:g}x"
            out["scaling"][name][key] = {"IS": scale_row(tr[~tr.cond.isin(oos_c)]), "OOS": scale_row(tr[tr.cond.isin(oos_c)])}
            log(f"  {name} {key}: IS {out['scaling'][name][key]['IS'].get('pnl_usd_per_day', 0):.0f} $/day, "
                f"OOS {out['scaling'][name][key]['OOS'].get('pnl_usd_per_day', 0):.0f} $/day")
    # outer ceiling: every qualifying fast-tier 0-3 s print (the shadow rows), at its full size, any wallet
    for per, mask in (("IS", ~f.cond.isin(oos_c)), ("OOS", f.cond.isin(oos_c))):
        g = f[mask & (f.month >= E.EVAL_START)]
        d = pd.to_datetime(g.ts, unit="s", utc=True).dt.floor("D")
        T = (d.max() - d.min()).days + 1
        out["ceiling"][per] = {"fast_tier_qualified_print_usd_per_day": float(g.usd.sum() / T), "days": int(T),
                               "rows": int(len(g))}
    del f, wh
    # U2 blind books: one joint U1+U2 walk-forward run, as in scripts/expand_test.py / lowloss_test.py
    up = ROOT / "data/expand_universe.parquet"
    if fb.exists() and (CACHE / "whist_u1u2.parquet").exists() and up.exists():
        f, wh = pd.read_parquet(fb), pd.read_parquet(CACHE / "whist_u1u2.parquet")
        u2 = pd.read_parquet(up, columns=["cond", "start", "oos"])
        u2_is, u2_oos = set(u2.loc[~u2.oos, "cond"]), set(u2.loc[u2.oos, "cond"])
        for name, pol in pols.items():
            tr = simulate(f, wh, pol)
            ok = refs_b[name].exists() and same_trades(tr, pd.read_parquet(refs_b[name]))
            out["checks"][f"{name}_u1u2_equals_{refs_b[name].relative_to(ROOT)}"] = bool(ok)
            assert ok, f"{name}: U1+U2 re-simulation differs from {refs_b[name]}"
            out["books"][name]["U2_IS_blind"] = tr[tr.cond.isin(u2_is)]
            out["books"][name]["U2_OOS_blind"] = tr[tr.cond.isin(u2_oos)]
        del f, wh
    return out


# ----------------------------------------------------------------------------------------- maker
def maker_book(which: str = "is") -> pd.DataFrame | None:
    """Maker fill book with resolution times. which='is': the lens's walk-forward book; 'oos': the blind OOS
    primary book (research/v2/maker/oos/book_v1.csv, written by research/v2/maker/oos_test.py)."""
    if which == "is":
        p, dd = ROOT / "data/v2_crossmarket/wf_lean_maker.parquet", ROOT / "data/v2_crossmarket"
        if not p.exists():
            return None
        m = pd.read_parquet(p)
        reb = -m.fee.to_numpy()                                 # the IS book stores the rebate as a negative fee
        mfee = np.zeros(len(m))
    else:
        p, dd = ROOT / "research/v2/maker/oos/book_v1.csv", ROOT / "data/v2_maker/oos"
        if not p.exists() or not (dd / "side_markets.parquet").exists():
            return None
        m = pd.read_csv(p)
        reb, mfee = m.rebate.to_numpy(), m.maker_fee.to_numpy()
    sm = pd.read_parquet(dd / "side_markets.parquet", columns=["event_id", "end"])
    ends = pd.to_datetime(sm.drop_duplicates("event_id").set_index("event_id").end).map(
        lambda x: x.timestamp() if pd.notna(x) else np.nan)
    pr = pd.read_parquet(dd / "side_prints.parquet", columns=["event_id", "ts"])
    ends = ends.fillna(pr.groupby("event_id").ts.max())       # analyze.py's rule, verbatim
    end = m.cond.map(ends).to_numpy(dtype=float)
    sh, pnl = m.shares.to_numpy(), m.pnl.to_numpy()
    pnl_ps = pnl / sh                                           # exact from the stored $ (the CSV rounds to 6 digits)
    b = pd.DataFrame({"cond": m.cond.to_numpy(), "ts": m.ts.to_numpy(), "date": pd.to_datetime(m.date, utc=True),
                      "month": m.month.astype(str).to_numpy(), "shares": sh, "usd_in": m.usd_in.to_numpy(),
                      "pnl": pnl, "pnl_ps": pnl_ps, "gross_ps": pnl_ps - reb + mfee,
                      "fee_ps": mfee, "rebate_ps": reb, "slip_ps": 0.0, "hold_h": (end - m.ts.to_numpy()) / 3600,
                      "lock_end": end, "regime": m.regime.to_numpy()})
    b["date"] = pd.to_datetime(b.date, utc=True)
    return b


# ---------------------------------------------------------------------------------------- tier-0
def tier0_block(cost_fn) -> dict:
    p = ROOT / "results/tier0/results.json"
    r = jload(p)
    lab = ("COUNTERFACTUAL WITH ASSUMED DATA: licensed live feed + courtside camera, not purchased; parameters "
           "from our measurements.")
    if not r or "headline" not in r:
        why = ("verifier-corrected headline not yet written (research/v2/tier0/DEVIATIONS.md V1-V10 in progress; "
               "results.json has no 'headline' key). The pre-registered primary's fill pricing was refuted (V1) "
               "and is not used.")
        return {"label": lab, "periods": {"IS": pending(str(p.relative_to(ROOT)), why),
                                          "OOS": pending(str(p.relative_to(ROOT)), why)},
                "cost": cost_fn((r or {}).get("primary_scenario", {}).get("coverage"))}
    scen = r.get("headline_scenario", {})
    cov = scen.get("coverage")
    cost = cost_fn(cov)
    dec = r.get("headline_by_size_and_decomposition", {})
    out = {"label": lab, "scenario": scen, "verified_marker": (ROOT / "results/tier0/VERIFIED").exists(),
           "cost": cost, "periods": {}}
    for per, key in (("IS", "IS"), ("OOS", "burned_OOS")):
        h = r["headline"].get(key)
        if not h:
            out["periods"][per] = pending(str(p.relative_to(ROOT)), f"no headline[{key}]")
            continue
        mm = h["mean"]
        extra = {"n_seeds": h.get("n_seeds"), "seed_sd": {k: h.get("sd", {}).get(k) for k in
                                                          ("per_share_c", "pnl_per_day_usd", "sharpe_ann")},
                 "capacity_stale_usd_per_day": mm.get("capacity_stale_usd_per_day"),
                 "fill_rate": mm.get("fill_rate"), "wrong_call_share_of_trades": mm.get("wrong_call_share_of_trades")}
        blk = summary_block(mm, f"tier-0 corrected headline, {per} (20-seed mean)", str(p.relative_to(ROOT)), cost, extra)
        # waterfall from the pooled per-share decomposition (correct / wrong fills)
        d = dec.get(key, {}).get("decomposition", {})
        net = mm.get("per_share_c")
        if d.get("correct") and d.get("wrong") and net is not None and mm.get("shares"):
            nc, nw = d["correct"]["net_c"], d["wrong"]["net_c"]
            w = min(1.0, max(0.0, (net - nw) / (nc - nw))) if nc != nw else 1.0   # share weight of correct fills, solved
            fee_c = w * d["correct"]["fee_c"] + (1 - w) * d["wrong"]["fee_c"]
            S, days = mm["shares"], mm["days"]
            ps = {"gross_edge": net + fee_c, "taker_fees": -fee_c, "maker_rebates": 0.0, "slippage_modelled": 0.0,
                  "net_trading": net}
            # dollars: scale so net trading equals the file's 20-seed mean P&L (the mean of per-seed P&L is not
            # mean ¢/share x mean shares), keeping the per-share decomposition's proportions
            sc = (mm["pnl_usd"] / (net / 100 * S)) if mm.get("pnl_usd") and net else 1.0
            blk["waterfall"] = {"per_share_c": ps,
                                "usd_period": {k: v / 100 * S * sc for k, v in ps.items()},
                                "usd_per_day": {k: v / 100 * S * sc / days for k, v in ps.items()},
                                "usd_scaled_to_seed_mean_pnl": sc,
                                "note": ("Fees split from the pooled 20-seed decomposition (correct vs wrong fills); the share "
                                         "weight of correct fills is solved from the net per share. Slippage is inside the "
                                         "book-priced fill (we pay the measured cost of walking the stale book, DEVIATIONS V1/V2)."),
                                "correct_fill_share_weight_derived": w}
        out["periods"][per] = blk
    gm = r.get("grid_corrected", {}).get("marginals", {})
    out["capacity_by_net_cap"] = {per: gm.get(key, {}).get("net_cap") for per, key in (("IS", "IS"), ("OOS", "burned_OOS"))}
    return out


# ------------------------------------------------------------------------------------ pending ones
def forward_block(cost) -> dict:
    p = ROOT / "results/v2/forward.json"
    r = jload(p)
    if not r:
        return pending("results/v2/forward.json", "blind forward window; scripts/forward_test.py runs once ~11:30 UTC Oct 4")
    m = r.get("secondary_res") or {}
    extra = {"primary_m30_per_share_c": r.get("primary_m30_per_share_c"), "verdicts": {k: v for k, v in r.items() if k.startswith("verdict")}}
    return summary_block(m, "v2 forward (blind)", "results/v2/forward.json", cost, extra) if m else \
        {"status": "ok (no secondary_res block)", "source": "results/v2/forward.json", **extra}


def tt_block() -> dict:
    """Table-tennis out-of-sport test (results/tt/results.json, research/tt): verdicts and trade count only."""
    path = "results/tt/results.json"
    r = jload(ROOT / path)
    if not r:
        return pending(path, "out-of-sport blind test still running (research/tt)")
    c, t3 = r.get("counts", {}), r.get("TT3", {})
    verdicts = {k: r.get(k, {}).get("verdict") for k in ("TT1", "TT2", "TT3")}
    return {"status": "ok (verdicts only)", "label": "table tennis TT1-TT4", "source": path,
            "n_trades": int(t3.get("shadow_rows") or 0), "n_matches": int(t3.get("shadow_matches") or 0),
            "verdicts": verdicts, "counts": {k: c.get(k) for k in ("utt_markets", "evaluable_matches", "print_rows")},
            "run": r.get("run", {}).get("utc"), "fixed_costs": {},
            "text": (f"Run {r.get('run', {}).get('utc', 'n/a')[:16]} UTC: {c.get('utt_markets') or 0:,} markets, "
                     f"{c.get('evaluable_matches')} evaluable matches. " + "; ".join(f"{k} {v}" for k, v in verdicts.items())
                     + f". {(lambda z: z[:1].upper() + z[1:])((t3.get('note') or '').rstrip('.'))}. No trades, so no P&L to put against costs; the books are untradable anyway "
                     "(PM_REVIEW P33).")}


def live_block(cost, conv_caps: list[float]) -> dict:
    """Maker live paper session (results/live/summary.json, written by scripts/live_paper.py while it runs).
    Reported as pending until the primary book has resolved fills; its capital convention is stated (PM P13)."""
    path = "results/live/summary.json"
    r = jload(ROOT / path)
    if not r:
        return pending(path, "live paper session on real markets not started (results/live/)")
    b1 = (r.get("books") or {}).get("B1", {})
    why = (f"session {r.get('run')} ({r.get('kind')}, mode {r.get('mode')}: live public market data, paper fills, no orders "
           f"sent) status '{r.get('status')}'; primary book B1: "
           f"{b1.get('fills', 0)} fills, {b1.get('resolved_fills', 0)} resolved. The session books "
           f"${r.get('capital_per_book', 0):,.0f} of paper capital per book, not the 3 × peak-locked convention "
           f"({'–'.join(f'${c:,.0f}' for c in sorted(conv_caps)) or 'n/a'} for the maker's IS and OOS books). It checks plumbing only: maker v1 already failed its blind OOS, and any rule "
           "change would be maker v2 with its own pre-registration")
    if not b1.get("resolved_fills"):
        return {**pending(path, why), "snapshot_utc": r.get("now")}
    return {"status": "ok (live paper, summary only)", "label": "maker v1 live paper session", "source": path,
            "n_trades": b1.get("fills"), "n_matches": b1.get("matches"), "pnl_usd": b1.get("pnl"),
            "per_share_c": b1.get("net_c_share_w"), "per_share_ci95_c": b1.get("ci95_c"),
            "capital_usd": r.get("capital_per_book"), "note": why, "fixed_costs": {}, "snapshot_utc": r.get("now")}


def generic_block(path: str, label: str, cost, why: str) -> dict:
    r = jload(ROOT / path)
    if not r:
        return pending(path, why)
    flat = {}

    def walk(x, pre=""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{pre}{k}.")
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            flat[pre[:-1]] = x
    walk(r)
    known = {}
    for k in ("n_trades", "n_matches", "days", "per_share_c", "total_pnl_usd", "pnl_usd", "pnl_per_day_usd",
              "usd_traded", "capital_usd", "sharpe_ann", "max_dd_usd", "worst_day_usd", "return_on_capital_pct"):
        hits = [v for kk, v in flat.items() if kk == k or kk.endswith("." + k)]
        if len(hits) == 1:
            known[k] = hits[0]
    blk = summary_block(known, label, path, cost) if known else {"status": "ok (schema not recognised)", "source": path}
    blk["note"] = "Parsed generically: only keys that appear exactly once in the file are used; read the file for context."
    return blk


# ------------------------------------------------------------------------------------------ figure
def _k(v: float, sign: bool = False) -> str:
    """Compact bar label: 1,234 -> 1.2k so side-by-side labels do not collide."""
    if abs(v) >= 1000:
        return f"{v / 1000:{'+' if sign else ''}.1f}k"
    return f"{v:{'+' if sign else ''},.0f}"


def _wrap(s: str, n: int) -> list[str]:
    import textwrap
    return textwrap.wrap(s, n)


def figure(S: dict, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    COL = {"IS": "#2a78d6", "OOS": "#eb6834"}
    steps = [("gross_edge", "Gross\nedge", "total"), ("taker_fees", "Taker\nfees", "delta"),
             ("maker_rebates", "Maker\nrebates", "delta"), ("slippage_modelled", "Slippage\n(modelled)", "delta"),
             ("net_trading", "Net\ntrading", "total"), ("infra", "Infra +\ndata", "delta"),
             ("after", "Net after\ncosts", "total")]
    panels = [("v2", "v2 (frozen fast-tier book)", ("IS", "OOS")), ("v2_safe", "v2-safe (net cap 50)", ("IS", "OOS")),
              ("tier0", "Tier-0 CV edge (COUNTERFACTUAL)", ("IS", "OOS")),
              ("maker", "Maker v1, side markets", ("IS", "OOS_blind"))]
    LEG = {"IS": "IS", "OOS": "OOS (burned, non-blind)", "OOS_blind": "OOS (blind, pre-registered)"}
    fig, axes = plt.subplots(2, 2, figsize=(15, 10.5), facecolor=SURF)
    for ax, (key, title, pkeys) in zip(axes.ravel(), panels):
        ax.set_facecolor(SURF)
        strat = S.get(key, {})
        pers = [p for p in pkeys if strat.get("periods", {}).get(p, {}).get("waterfall")]
        missing = [p for p in pkeys if p not in pers]
        col = {p: (COL["IS"] if i == 0 else COL["OOS"]) for i, p in enumerate(pkeys)}
        ax.set_title(title, loc="left", fontsize=13, color=INK, fontweight="bold", pad=10)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(GRID)
        if not pers:
            ax.set_xticks([]); ax.set_yticks([])
            blk = strat.get("periods", {}).get(pkeys[0], {})
            cd = strat.get("cost", {}).get("daily", {})
            txt = "PENDING\n\n" + "\n".join(_wrap(blk.get("why", ""), 70))
            if cd.get("central") is not None:
                txt += (f"\n\nFixed costs already known: ${cd['central']:,.0f}/day central "
                        f"(${cd['low']:,.0f}–${cd['high']:,.0f})")
            ax.text(0.5, 0.5, txt, ha="center", va="center", color=INK2, fontsize=10.5, transform=ax.transAxes)
            continue
        width = 0.38 if len(pers) == 2 else 0.6
        ymin, ymax = 0.0, 0.0
        for j, per in enumerate(pers):
            blk = strat["periods"][per]
            w = blk["waterfall"]["usd_per_day"]
            fc = blk.get("fixed_costs", {})
            cen = fc.get("central", {}).get("fixed_cost_usd_per_day", 0.0)
            lo = fc.get("low", {}).get("fixed_cost_usd_per_day", cen)
            hi = fc.get("high", {}).get("fixed_cost_usd_per_day", cen)
            vals = {**w, "infra": -cen, "after": w["net_trading"] - cen}
            off = (j - (len(pers) - 1) / 2) * width
            run = 0.0
            after_lo, after_hi = w["net_trading"] - hi, w["net_trading"] - lo
            for i, (k, _, kind) in enumerate(steps):
                v = vals[k]
                x = i + off
                if kind == "total":
                    lo_y, h = min(0, v), abs(v)
                    run = v
                    ax.bar(x, h, width * 0.92, bottom=lo_y, color=col[per], edgecolor=SURF, linewidth=2, zorder=3)
                    ty = v if k != "after" else (max(v, after_hi) if v >= 0 else min(v, after_lo))
                    ax.annotate(_k(v), (x, ty), xytext=(0, 4 if v >= 0 else -5), textcoords="offset points",
                                ha="center", va="bottom" if v >= 0 else "top", fontsize=9, color=INK, fontweight="bold")
                else:
                    a, bnd = run, run + v
                    ax.bar(x, abs(v), width * 0.92, bottom=min(a, bnd), color=col[per], alpha=0.38, edgecolor=col[per],
                           linewidth=1, zorder=3)
                    if abs(v) > 0.04 * max(1, abs(vals["gross_edge"])):
                        ax.annotate(_k(v, True), (x, min(a, bnd)), xytext=(0, -3), textcoords="offset points",
                                    ha="center", va="top", fontsize=8, color=INK2)
                    run = bnd
                ymin, ymax = min(ymin, run, v if kind == "total" else run), max(ymax, run, v if kind == "total" else run)
            # cost range whisker on the final bar
            xa = len(steps) - 1 + off
            ax.plot([xa, xa], [after_lo, after_hi], color=INK, lw=1.2, zorder=4)
            ax.plot([xa - width * 0.2, xa + width * 0.2], [after_lo] * 2, color=INK, lw=1.2, zorder=4)
            ax.plot([xa - width * 0.2, xa + width * 0.2], [after_hi] * 2, color=INK, lw=1.2, zorder=4)
            ymin, ymax = min(ymin, after_lo), max(ymax, after_hi)
        ax.axhline(0, color=INK2, lw=0.8, zorder=2)
        ax.set_xticks(range(len(steps)))
        ax.set_xticklabels([s[1] for s in steps], fontsize=9, color=INK2)
        ax.tick_params(axis="y", colors=INK2, labelsize=9)
        ax.yaxis.grid(True, color=GRID, lw=0.6, zorder=0)
        pad = 0.14 * (ymax - ymin if ymax > ymin else 1)
        ax.set_ylim(ymin - pad, ymax + pad)
        ax.set_ylabel("$ per calendar day", color=INK2, fontsize=10)
        handles = [plt.Rectangle((0, 0), 1, 1, color=col[p]) for p in pers]
        labs = []
        for p in pers:
            blk = strat["periods"][p]
            cal = blk.get("calendar") or [None, None]
            days = blk.get("unit_economics", {}).get("calendar_days") or blk.get("calendar_days")
            labs.append(f"{LEG.get(p, p)}: {days:g} days" + (f", {cal[0]} to {cal[1]}" if cal[0] else "")
                        + ("" if cal[0] else " (20-seed mean)" if key == "tier0" else ""))
        for p in missing:
            handles.append(plt.Rectangle((0, 0), 1, 1, color=GRID))
            labs.append(f"{LEG.get(p, p)}: pending")
        ax.legend(handles, labs, loc="upper left", bbox_to_anchor=(0.0, -0.13), ncol=1, fontsize=8.5, frameon=False,
                  labelcolor=INK2)
    fig.suptitle("P&L waterfall per strategy, $ per calendar day: trading P&L, then fixed infrastructure and data costs",
                 x=0.01, ha="left", fontsize=14, color=INK, fontweight="bold")
    fig.text(0.01, 0.008, ("Solid bars are totals; pale bars are the steps between them. Whisker on 'Net after costs' = low–high "
                           "fixed-cost range (central plotted). Infra + data: v2 and v2-safe carry a feed-licence ASSUMPTION;\n"
                           "tier-0 adds a camera, operator and GPU per covered match; the maker carries a London VPS only. "
                           "Numbers: results/financials/financials.json; write-up: research/financials/FINANCIALS.md."),
             fontsize=8.5, color=INK2)
    fig.tight_layout(rect=(0, 0.035, 1, 0.96), h_pad=3.5)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURF)
    plt.close(fig)


# -------------------------------------------------------------------------------------- markdown
def f_usd(x, d=0):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    x = 0.0 if round(x, d) == 0 else x
    return f"−${abs(x):,.{d}f}" if x < 0 else f"${x:,.{d}f}"


def f_num(x, d=2, sign=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    x = 0.0 if round(x, d) == 0 else x
    s = f"{x:+,.{d}f}" if sign else f"{x:,.{d}f}"
    return s.replace("-", "−")


def f_pct(x, d=1, sign=False):
    return "n/a" if x is None else f_num(x, d, sign) + "%"


def f_ci(ci, d=2, sign=True):
    return "n/a" if not ci or ci[0] is None else f"[{f_num(ci[0], d, sign)}, {f_num(ci[1], d, sign)}]"


PER_NAMES = {"IS": "IS", "OOS": "OOS (burned, non-blind)", "U2_IS_blind": "U2 unseen markets, IS period (blind)",
             "U2_OOS_blind": "U2 unseen markets, OOS period (blind)", "forward": "Forward (blind)",
             "IS_1s5": "IS, current 1 s / 5% regime only", "OOS_blind": "OOS (blind)", "live_paper": "Live paper session",
             "results": "Results"}
# per-strategy overrides where a period means something narrower than the v2 definition (set in main())
PER_NAMES_STRAT: dict = {}


def pname(k: str, p: str) -> str:
    return PER_NAMES_STRAT.get(k, {}).get(p, PER_NAMES.get(p, p))


def headline_rows(S: dict) -> list[dict]:
    rows = []
    order = [("v2", ["IS", "IS_1s5", "OOS", "U2_OOS_blind", "forward"]), ("v2_safe", ["IS", "IS_1s5", "OOS", "U2_OOS_blind"]),
             ("tier0", ["IS", "OOS"]), ("maker", ["IS", "IS_1s5", "OOS_blind", "live_paper"]), ("tt", ["results"])]
    for k, pers in order:
        for p in pers:
            blk = S[k]["periods"].get(p)
            if blk is None:
                continue
            r = {"strategy": S[k]["name"], "period": pname(k, p), "status": blk.get("status")}
            if blk.get("status", "").startswith("ok"):
                ue, cr = blk.get("unit_economics", {}), blk.get("capital_returns", {})
                fc = blk.get("fixed_costs", {})
                r.update({
                    "trades": ue.get("n_trades", blk.get("n_trades")),
                    "net_c_per_share": blk.get("per_share_c"),
                    "net_c_per_share_ci95": blk.get("per_share_ci95_c_match_clustered", blk.get("per_share_ci95_c")),
                    "net_trading_usd_per_day": (blk.get("waterfall", {}).get("usd_per_day", {}).get("net_trading")
                                                if blk.get("waterfall") else blk.get("pnl_usd_per_day")),
                    "fixed_cost_usd_per_day": {l: fc.get(l, {}).get("fixed_cost_usd_per_day") for l in ("low", "central", "high")},
                    "net_after_costs_usd_per_day": {l: fc.get(l, {}).get("net_after_costs_usd_per_day") for l in ("low", "central", "high")},
                    "capital_usd": cr.get("capital_usd", blk.get("capital_usd")),
                    "return_on_capital_ann_pct": cr.get("return_on_capital_ann_pct", blk.get("return_on_capital_ann_pct")),
                    "sharpe_ann": cr.get("sharpe_ann", blk.get("sharpe_ann")),
                    "max_dd_pct": cr.get("max_dd_pct", blk.get("max_dd_pct")),
                    "notional_usd_per_day": blk.get("capacity", {}).get("notional_usd_per_day_now", blk.get("notional_usd_per_day_now")),
                    "breakeven_notional_usd_per_day_central": fc.get("central", {}).get("breakeven_notional_usd_per_day"),
                })
            rows.append(r)
    return rows


def md(S: dict, R: dict) -> str:
    L = []
    a = L.append
    a("# COURTSIDE financials: what each strategy makes, what it costs, and how big it can get\n")
    a(f"Generated by `scripts/financials.py` ({R['generated_utc']}, {R['runtime_s']} s). Every number is read from a "
      "result file or computed from a trade file in this repo; external costs are cited ESTIMATES or labelled "
      "ASSUMPTIONS (section 1). Anything still running shows as **pending** and is filled in on the next run. "
      "Raw numbers: `results/financials/financials.json`; figure: `results/financials/fig_waterfall.png`.\n")
    a("Conventions: daily P&L is calendar-day and zero-filled, and each trade's P&L is booked on its **entry** date "
      "(research/v2/sizing/engine.py daily_series), not on the settlement date (entry-to-resolution hours are in each "
      "unit-economics table); Sharpe and Sortino are ×√365; capital is 3 × peak "
      "dollars locked (repo convention); annualised returns are simple (×365/days, no compounding); kurtosis is Pearson "
      "(normal = 3). IS = matches starting before 2026-08-25 14:15 UTC (trades from 2026-02); OOS = matches starting after "
      "it, **burned (non-blind)**. U2 = 11,307 markets never used in development (the blind test). "
      f"Cost of capital uses the 3-month T-bill at {TBILL['rate'] * 100:.2f}% ({TBILL['url']}, {TBILL['what']}).\n")
    # headline
    a("## Headline\n")
    a("| strategy | period | trades | net ¢/share [95% CI] | net trading $/day | fixed costs $/day, central [low to high] | net after costs $/day, central [high-cost to low-cost] | capital | return on capital, ann. | Sharpe | max DD % cap |")
    a("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in R["headline"]:
        if not r["status"].startswith("ok"):
            a(f"| {r['strategy']} | {r['period']} | **pending** | | | | | | | | |")
            continue
        fc, na = r["fixed_cost_usd_per_day"], r["net_after_costs_usd_per_day"]
        fcs = f"{f_usd(fc['central'])} [{f_usd(fc['low'])} to {f_usd(fc['high'])}]" if fc.get("central") is not None else "n/a"
        nas = f"**{f_usd(na['central'])}** [{f_usd(na['high'])} to {f_usd(na['low'])}]" if na.get("central") is not None else "n/a"
        tcell = ("n/a" if not isinstance(r["trades"], (int, float)) else f"{r['trades']:,}" if float(r["trades"]).is_integer()
                 else f"≈{round(r['trades']):,} (seed mean)")
        a(f"| {r['strategy']} | {r['period']} | {tcell} | {f_num(r['net_c_per_share'], 2, True)} {f_ci(r['net_c_per_share_ci95'])} | "
          f"{f_usd(r['net_trading_usd_per_day'])} | {fcs} | {nas} | {f_usd(r['capital_usd'])} | {f_pct(r['return_on_capital_ann_pct'], 0)} | "
          f"{f_num(r['sharpe_ann'], 1)} | {f_pct(r['max_dd_pct'], 1)} |")
    a("")
    a("How to read it:")
    for line in R["reading"]:
        a(f"- {line}")
    a("")
    a("![P&L waterfall](../../results/financials/fig_waterfall.png)\n")
    # costs
    a("## 1. Fixed infrastructure and data costs (external; cited)\n")
    a("| item | label | low | central | high | unit | basis | sources |")
    a("|---|---|---|---|---|---|---|---|")
    for k, c in COSTS.items():
        a(f"| {c['name']} | {c['label']} | {f_num(c['low'], 2)} | {f_num(c['central'], 2)} | {f_num(c['high'], 2)} | {c['unit']} | "
          f"{c['basis']} | {' '.join(f'<{u}>' for u in c['sources']) or '—'} |")
    a(f"| Cost of capital | {TBILL['label']} | | {TBILL['rate'] * 100:.2f}% | | per year | {TBILL['what']} | <{TBILL['url']}> |")
    a(f"\nAll sources retrieved {RETRIEVED}. Monthly figures convert to daily at 365/12 days per month.\n")
    a("| strategy | carries | fixed cost $/month, low / central / high | $/day, low / central / high |")
    a("|---|---|---|---|")
    for k in ("v2", "v2_safe", "tier0", "maker"):
        c = S[k]["cost"]
        mo, dy = c["monthly"], c["daily"]
        if mo.get("central") is None:
            a(f"| {S[k]['name']} | {c['note']} | pending (coverage unknown) | |")
            continue
        a(f"| {S[k]['name']} | {c['note']} | {f_usd(mo['low'])} / {f_usd(mo['central'])} / {f_usd(mo['high'])} | "
          f"{f_usd(dy['low'])} / {f_usd(dy['central'])} / {f_usd(dy['high'])} |")
    a("")
    # per strategy
    for n, k in enumerate(("v2", "v2_safe", "tier0", "maker", "tt"), start=2):
        s = S[k]
        a(f"## {n}. {s['name']}\n")
        a(s["about"] + "\n")
        okp = [(p, b) for p, b in s["periods"].items() if b.get("status", "").startswith("ok")]
        pend = [(p, b) for p, b in s["periods"].items() if not b.get("status", "").startswith("ok")]
        for p, b in pend:
            a(f"- **{pname(k, p)}: pending.** `{b.get('expected_file')}`: {b.get('why')}")
        if pend:
            a("")
        if s.get("extra_md"):
            a(s["extra_md"] + "\n")
        full = [(p, b) for p, b in okp if "unit_economics" in b]
        summ = [(p, b) for p, b in okp if "unit_economics" not in b]
        if full or any(b.get("waterfall") for _, b in summ):
            wfp = [(p, b) for p, b in okp if b.get("waterfall")]
            a(f"### {n}a. P&L waterfall\n")
            hdr = " | ".join(f"{pname(k, p)}: ¢/share | $ period | $/day" for p, _ in wfp)
            a(f"| step | {hdr} |")
            a("|---|" + "---|---|---|" * len(wfp))
            names = [("gross_edge", "Gross edge"), ("taker_fees", "− taker fees"), ("maker_rebates", "+ maker rebates"),
                     ("slippage_modelled", "− spread / slippage (as modelled)"), ("net_trading", "**= net trading P&L**")]
            for kk, lab in names:
                cells = " | ".join(f"{f_num(b['waterfall']['per_share_c'][kk], 3, True)} | {f_usd(b['waterfall']['usd_period'][kk])} | "
                                   f"{f_usd(b['waterfall']['usd_per_day'][kk], 1)}" for _, b in wfp)
                a(f"| {lab} | {cells} |")
            for lvl in ("central", "low", "high"):
                cells = " | ".join(f" | {f_usd(-b['fixed_costs'][lvl]['fixed_cost_usd_per_day'] * (b.get('unit_economics', {}).get('calendar_days') or b.get('calendar_days') or 0))} | "
                                   f"{f_usd(-b['fixed_costs'][lvl]['fixed_cost_usd_per_day'], 1)}" if lvl in b.get("fixed_costs", {}) else " | n/a | n/a"
                                   for _, b in wfp)
                a(f"| − infra + data ({lvl}) | {cells} |")
            for lvl in ("central", "low", "high"):
                cells = " | ".join(f" | {f_usd(b['fixed_costs'][lvl]['net_after_costs_usd_per_day'] * (b.get('unit_economics', {}).get('calendar_days') or b.get('calendar_days') or 0))} | "
                                   f"**{f_usd(b['fixed_costs'][lvl]['net_after_costs_usd_per_day'], 1)}**" if lvl in b.get("fixed_costs", {}) else " | n/a | n/a"
                                   for _, b in wfp)
                a(f"| **= net after costs ({lvl} costs)** | {cells} |")
            if any("stress_half_tick_slippage" in b["waterfall"] for _, b in wfp):
                cells = " | ".join(f"{f_num(b['waterfall']['stress_half_tick_slippage']['net_per_share_c'], 3, True)} | "
                                   f"{f_usd(b['waterfall']['stress_half_tick_slippage']['net_trading_usd'])} | "
                                   f"{f_usd(b['waterfall']['stress_half_tick_slippage']['net_usd_per_day'], 1)}"
                                   if "stress_half_tick_slippage" in b["waterfall"] else "n/a | n/a | n/a" for _, b in wfp)
                a(f"| *stress: net trading with +½ tick (0.5¢/share) slippage* | {cells} |")
            a("")
            for _, b in wfp:
                if b["waterfall"].get("note"):
                    a(f"*{b['waterfall']['note']}*\n")
                    break
            a(s.get("waterfall_note", "") + "\n")
            # break-even
            a(f"**Break-even.** P&L/day needed = fixed cost/day. Notional/day needed = fixed cost/day ÷ net P&L per $ traded.\n")
            a("| period | fixed cost $/day (central) | net trading $/day | notional $/day now | notional $/day to break even (central) | multiple of now | covered within the tested size range? |")
            a("|---|---|---|---|---|---|---|")
            for p, b in wfp:
                c = b.get("fixed_costs", {}).get("central", {})
                now = b.get("capacity", {}).get("notional_usd_per_day_now", b.get("notional_usd_per_day_now"))
                need = c.get("breakeven_notional_usd_per_day")
                cov = s.get("coverage", {}).get(p, "n/a")
                a(f"| {pname(k, p)} | {f_usd(c.get('fixed_cost_usd_per_day'))} | {f_usd(b['waterfall']['usd_per_day']['net_trading'])} | "
                  f"{f_usd(now)} | {f_usd(need) if need else 'never (net edge ≤ 0)'} | "
                  f"{f_num(need / now, 1) + '×' if need and now else 'n/a'} | {cov} |")
            a("")
            bef = [(p, b["breakeven_taker_fee"]) for p, b in wfp if b.get("breakeven_taker_fee")]
            if bef:
                def fee_cell(x, key):
                    k = x.get(f"fee_multiple_{key}")
                    r = x.get(f"rate_{key}")
                    return "n/a" if k is None else (f"{f_num(k, 2)}× ({f_pct(r * 100, 1)})" if r is not None else f"{f_num(k, 2)}×")
                a("**Break-even taker fee** (PM_REVIEW P03). Book held fixed, fee linear in the rate: every trade's fee "
                  "is scaled by k until net P&L is zero, before and after fixed costs. Shown as k × the schedule each trade "
                  "actually paid, and as a rate where every trade paid the same rate. Today's rate is 5%.\n")
                a("| period | taker fees as % of gross | rate charged | break-even before fixed costs | after low fixed costs | after central fixed costs | after high fixed costs |")
                a("|---|---|---|---|---|---|---|")
                for p, x in bef:
                    a(f"| {pname(k, p)} | {f_pct(x['fee_share_of_gross'] * 100, 1)} | "
                      f"{f_pct(x['uniform_rate_charged'] * 100, 0) if x['uniform_rate_charged'] is not None else 'mixed (0–5%)'} | "
                      f"{fee_cell(x, 'before_fixed_costs')} | {fee_cell(x, 'after_low_fixed_costs')} | "
                      f"{fee_cell(x, 'after_central_fixed_costs')} | {fee_cell(x, 'after_high_fixed_costs')} |")
                a("\nA negative multiple means the book loses money after fixed costs even with zero taker fees.\n")
        if full:
            a(f"### {n}b. Unit economics\n")
            a("| | " + " | ".join(pname(k, p) for p, _ in full) + " |")
            a("|---|" + "---|" * len(full))
            rows = [
                ("trades / matches / calendar days", lambda u, c, b: f"{u['n_trades']:,} / {u['n_matches']:,} / {u['calendar_days']}"),
                ("net per trade (mean / median)", lambda u, c, b: f"{f_usd(u['per_trade_usd'], 2)} / {f_usd(u['per_trade_median_usd'], 2)}"),
                ("net per match (mean); share of matches won", lambda u, c, b: f"{f_usd(u['per_match_usd'], 2)}; {f_pct(u['match_win_rate'] * 100)}"),
                ("net per calendar day (mean / median); profitable days", lambda u, c, b: f"{f_usd(u['per_day_usd'], 1)} / {f_usd(u['per_day_median_usd'], 1)}; {f_pct(u['profitable_days_share'] * 100)}"),
                ("trade win rate [95% CI, match-clustered]", lambda u, c, b: f"{f_pct(u['trade_win_rate'] * 100)} {f_ci([x * 100 for x in u['trade_win_rate_ci95_match_clustered']], 1, False)}"),
                ("average win / average loss ($ per trade); ratio", lambda u, c, b: f"{f_usd(u['avg_win_usd'], 2)} / {f_usd(u['avg_loss_usd'], 2)}; {f_num(u['win_loss_ratio'], 2)}"),
                ("profit factor", lambda u, c, b: f_num(u["profit_factor"], 3)),
                ("expectancy: $/trade; ¢/share; ¢ per $ traded", lambda u, c, b: f"{f_usd(u['expectancy_usd_per_trade'], 3)}; {f_num(u['expectancy_c_per_share'], 3, True)}; {f_num(u['net_c_per_usd_notional'], 3, True)}"),
                ("turnover (notional ÷ capital, per year)", lambda u, c, b: f"{f_num(u['turnover_x_per_year'], 0)}×"),
                ("hours from entry to resolution: median / p90", lambda u, c, b: f"{f_num(u['hold_hours_to_resolution']['median'], 2)} / {f_num(u['hold_hours_to_resolution']['p90'], 2)}"),
                ("hours locked in the capital model: median / p90", lambda u, c, b: f"{f_num(u['capital_lock_hours_in_capital_model']['median'], 2)} / {f_num(u['capital_lock_hours_in_capital_model']['p90'], 2)}"),
                (f"cost of capital at {TBILL['rate'] * 100:.2f}%: on reserved capital (period); on dollars actually locked", lambda u, c, b: f"{f_usd(u['cost_of_capital']['on_reserved_capital_usd_period'])}; {f_usd(u['cost_of_capital']['on_dollars_actually_locked_usd_period'], 2)}"),
            ]
            for lab, fn in rows:
                a(f"| {lab} | " + " | ".join(fn(b["unit_economics"], b["capital_returns"], b) for _, b in full) + " |")
            a(f"\nCapital-model lock: {full[0][1]['unit_economics']['capital_lock_hours_in_capital_model']['rule']}\n")
            a(f"### {n}c. Capital and returns\n")
            a("| | " + " | ".join(pname(k, p) for p, _ in full) + " |")
            a("|---|" + "---|" * len(full))
            rows = [
                ("capital (3 × peak locked) / peak locked", lambda c: f"{f_usd(c['capital_usd'])} / {f_usd(c['peak_locked_usd'])}"),
                ("net P&L [95% CI, match-clustered]", lambda c: f"{f_usd(c['pnl_usd'])} {f_ci(c['pnl_ci95_usd_match_clustered'], 0, False)}"),
                ("return on capital, period [95% CI, day bootstrap]", lambda c: f"{f_pct(c['return_on_capital_pct'])} {f_ci(c['return_on_capital_ci95_pct_day_bootstrap'], 1, False)}"),
                ("return on capital, annualised (simple) [95% CI]", lambda c: f"{f_pct(c['return_on_capital_ann_pct'], 0)} {f_ci(c['return_on_capital_ann_ci95_pct_day_bootstrap'], 0, False)}"),
                ("Sharpe / Sortino / Calmar", lambda c: f"{f_num(c['sharpe_ann'], 2)} / {f_num(c['sortino_ann'], 2)} / {f_num(c['calmar'], 1)}"),
                ("max drawdown $ / % of capital", lambda c: f"{f_usd(c['max_dd_usd'])} / {f_pct(c['max_dd_pct'], 2)}"),
                ("max DD: peak → trough → recovered", lambda c: f"{c['max_dd_dates']['peak_date']} → {c['max_dd_dates']['trough_date']} → {c['max_dd_dates']['recovery_date'] or 'not yet'}"),
                ("days to recover: from trough / from peak", lambda c: (f"{c['days_trough_to_recovery']} / {c['days_peak_to_recovery']}" if c["days_trough_to_recovery"] is not None else f"not recovered ({c['days_since_trough_unrecovered']} days since trough)")),
                ("worst day / week / month, $", lambda c: f"{f_usd(c['worst_day_usd'])} / {f_usd(c['worst_week_usd'])} / {f_usd(c['worst_month_usd'])}"),
                ("worst day / week / month, % of capital", lambda c: f"{f_pct(c['worst_day_pct'], 2)} / {f_pct(c['worst_week_pct'], 2)} / {f_pct(c['worst_month_pct'], 2)}"),
                ("months positive", lambda c: f"{c['months_positive']} / {c['months_total']}"),
                ("daily skew / kurtosis (Pearson)", lambda c: f"{f_num(c['skew_daily'], 2)} / {f_num(c['kurtosis_daily_pearson'], 2)}"),
            ]
            for lab, fn in rows:
                a(f"| {lab} | " + " | ".join(fn(b["capital_returns"]) for _, b in full) + " |")
            fx = [b["capital_returns"].get("fixed_capital") for _, b in full]
            if all(fx):
                for j, c0 in enumerate(fx[0]):
                    a(f"| return, annualised / max DD, on one capital fixed ex ante: {c0['what']} {f_usd(c0['capital_usd'])} | "
                      + " | ".join(f"{f_pct(c[j]['return_ann_pct'], 0)} / {f_pct(c[j]['max_dd_pct'], 2)}" for c in fx) + " |")
            a("\nWeeks are calendar weeks (Mon–Sun) and months calendar months; the first and last can be partial.")
            if all(fx):
                a("The rows 'on one capital fixed ex ante' use the same dollar capital for every period (PM_REVIEW P13): "
                  + "; ".join(f"{c0['what']} = {c0['source']}" for c0 in fx[0])
                  + ". The rows above them use each period's own 3 × peak locked, which a trader cannot know in advance.")
            a("")
        for p, b in summ:
            if b.get("text"):
                a(f"**{pname(k, p)}** (`{b.get('source')}`): {b['text']}\n")
                continue
            a(f"**{pname(k, p)}** (`{b.get('source')}`; summary file, no trade-level data): "
              f"{b.get('n_trades') or 'n/a'} trades, {f_num(b.get('per_share_c'), 2, True)}¢/share {f_ci(b.get('per_share_ci95_c'))}, "
              f"{f_usd(b.get('pnl_usd'))} ({f_usd(b.get('pnl_usd_per_day'), 1)}/day), capital {f_usd(b.get('capital_usd'))}, "
              f"Sharpe {f_num(b.get('sharpe_ann'), 1)}, max DD {f_usd(b.get('max_dd_usd'))} ({f_pct(b.get('max_dd_pct'), 2)}). "
              + (f"Win rate, profit factor, holding time and week/month tails need the trade file. " if True else ""))
            a("")
        if s.get("capacity_md"):
            a(f"### {n}d. Capacity\n")
            a(s["capacity_md"] + "\n")
        if s.get("caveats"):
            a("Caveats: " + " ".join(s["caveats"]) + "\n")
    a("## Reference checks\n")
    a("Each trade-level book was rebuilt and compared with the number already in the repo before use.\n")
    a("| check | ours | repo | match |")
    a("|---|---|---|---|")
    for c in R["checks"]:
        a(f"| {c['what']} | {c['ours']} | {c['repo']} | {'yes' if c['ok'] else '**NO**'} |")
    a("")
    a("## Reproduce\n")
    a("```bash\n.venv/bin/python scripts/financials.py   # 20-60 s, 1 process; re-run any time, pending items fill in\n```\n")
    a("Inputs: `data/v2_lowloss/{features,whist}_{u1,u1u2}.parquet` (built by `scripts/lowloss_test.py`), "
      "`data/v2_trades_is_oos.parquet`, `data/v2_lowloss/trades_{a,b}_v2_safe.parquet`, `data/expand_v2_trades.parquet`, "
      "`data/expand_universe.parquet`, `data/v2_crossmarket/{wf_lean_maker,side_markets,side_prints}.parquet`, "
      "`results/v2/{causal,cost_stress}.json`, `results/lowloss/results.json`, `results/expand/results.json`, "
      "`results/tier0/results.json`, `research/v2/crossmarket/verify_realism.json`, and when they exist "
      "`results/v2/forward.json`, `results/maker/oos.json`, `results/live/summary.json`, `results/tt/results.json`.\n")
    return "\n".join(L)


# ------------------------------------------------------------------------------------------- main
def main():
    t0 = time.time()

    def log(*a):
        print(time.strftime("%H:%M:%S"), *a, flush=True)

    first_run = not OUT_JSON.exists()
    S: dict = {}
    checks = []

    def chk(what, ours, repo, tol):
        ok = ours is not None and repo is not None and abs(ours - repo) <= tol * max(1.0, abs(repo))
        checks.append({"what": what, "ours": round(float(ours), 4) if ours is not None else None,
                       "repo": round(float(repo), 4) if repo is not None else None, "ok": bool(ok)})

    # ---- v2, v2-safe
    log("v2 / v2-safe: re-simulating the frozen engine on cached features (1x, 0.5x, 2x, 5x, all prints)")
    V = v2_books(log)
    cz = jload(ROOT / "results/v2/causal.json") or {}
    ll = jload(ROOT / "results/lowloss/results.json") or {}
    ex = jload(ROOT / "results/expand/results.json") or {}
    lock_v2 = "ex-ante 4 h per position from entry (src/v2.py LOCK_S), capital = 3 × peak of the dollars locked"
    for name, nice, about in (
            ("v2", "v2 (frozen fast-tier book)",
             "The frozen v2 rule: copy qualifying fast-tier prints 0–3 s after a detected jump, risk-parity size, wallet filter, "
             "0.05–0.95 zone, |net| ≤ 100 shares per match, hold to resolution. It fills at the fast tier's own print price, "
             "so it is the prize for fast-tier speed, not a remotely executable strategy (docs/NOTE.md sections 3 and 6)."),
            ("v2_safe", "v2-safe (net cap 50)",
             "v2 with the per-match net cap halved to 50 shares (pre-registered risk dial, research/v2/lowloss).")):
        cost = cost_stack(name)
        S[name] = {"name": nice, "about": about, "cost": cost, "periods": {}}
        bk = dict(V["books"].get(name, {}))
        if "IS" in bk and "regime" in bk["IS"]:   # PM_REVIEW P08: the only IS slice in today's venue regime (1 s / 5%)
            bk = {k: v for kk, vv in bk.items() for k, v in
                  ([(kk, vv), ("IS_1s5", vv[vv.regime == "1s/5%"])] if kk == "IS" else [(kk, vv)])}
        for per, tr in bk.items():
            if "gross_res" not in tr:
                continue
            S[name]["periods"][per] = book_stats(std_engine_book(tr), cost, f"{nice} {per}",
                                                 "engine re-simulation (verified equal to the repo trade file)", lock_v2)
        # PM_REVIEW P13: one capital, fixed ex ante (the IS figure), for every period
        P_ = S[name]["periods"]
        fixed = [("IS capital", P_["IS"]["capital_returns"]["capital_usd"], "this book's IS capital (3 x IS peak locked)")]
        if name == "v2":
            rl = (jload(ROOT / "results/risk/risk_stats.json") or {}).get("liquidity_capital", {}).get("is_eval", {})
            if rl.get("capital_usd_3x_peak_realised"):
                fixed.append(("realised-lock capital", rl["capital_usd_3x_peak_realised"],
                              "3 x IS peak locked with realised lock times (results/risk/risk_stats.json)"))
        for per, blk in P_.items():
            if blk.get("status") != "ok":
                continue
            T_ = blk["unit_economics"]["calendar_days"]
            blk["capital_returns"]["fixed_capital"] = [
                {"what": w, "capital_usd": c, "source": s_, "return_ann_pct": blk["capital_returns"]["pnl_usd"] / c * 100 * 365 / T_,
                 "max_dd_pct": blk["capital_returns"]["max_dd_usd"] / c * 100} for w, c, s_ in fixed]
        if name == "v2":
            S[name]["periods"]["forward"] = forward_block(cost)
        S[name]["waterfall_note"] = ("Slippage as modelled is zero: v2 fills at the fast tier's own print price (they already "
                                     "crossed the spread). Repo stresses: +½ tick in the table above; doubled fees in "
                                     "`results/v2/cost_stress.json` (OOS does not survive doubled fees).")
        cs = jload(ROOT / "results/v2/cost_stress.json") or {}
        if name == "v2" and cs:
            S[name]["cost_stress_repo"] = {k: {kk: cs[k].get(kk) for kk in ("per_share_c", "total_pnl_usd", "sharpe_ann")} for k in cs}
        # reference checks
        P = S[name]["periods"]
        if name == "v2":
            pmc = (jload(ROOT / "results/financials/pm_checks.json") or {}).get("current_regime_1s_5pct_is", {})
            if "IS_1s5" in P and pmc:
                chk("v2 IS 1 s/5% slice net P&L $ vs results/financials/pm_checks.json", P["IS_1s5"]["capital_returns"]["pnl_usd"], pmc["total_pnl_usd"], 1e-9)
                chk("v2 IS 1 s/5% slice capital $ vs results/financials/pm_checks.json", P["IS_1s5"]["capital_returns"]["capital_usd"], pmc["capital_usd_3x_own_peak"], 1e-9)
            for per, key in (("IS", "causal/is_eval/slip0.0"), ("OOS", "causal/burned_oos/slip0.0")):
                if per in P and key in cz:
                    chk(f"v2 {per} net P&L $ vs results/v2/causal.json", P[per]["capital_returns"]["pnl_usd"], cz[key]["total_pnl_usd"], 1e-9)
                    chk(f"v2 {per} Sharpe vs results/v2/causal.json", P[per]["capital_returns"]["sharpe_ann"], cz[key]["sharpe_ann"], 1e-9)
                    chk(f"v2 {per} capital $ vs results/v2/causal.json", P[per]["capital_returns"]["capital_usd"], cz[key]["capital_usd"], 1e-9)
            for per, key in (("U2_IS_blind", "u2_is"), ("U2_OOS_blind", "u2_oos")):
                if per in P and key in ex.get("books", {}):
                    chk(f"v2 {per} net P&L $ vs results/expand/results.json", P[per]["capital_returns"]["pnl_usd"], ex["books"][key]["slip0.0"]["total_pnl_usd"], 1e-9)
                    chk(f"v2 {per} Sharpe vs results/expand/results.json", P[per]["capital_returns"]["sharpe_ann"], ex["books"][key]["slip0.0"]["sharpe_ann"], 1e-9)
        else:
            A = ll.get("runs", {}).get("a_burned_oos_nonblind", {}).get("books", {})
            B = ll.get("runs", {}).get("b_u2_blind", {}).get("books", {})
            for per, src, key in (("IS", A, "u1_is"), ("OOS", A, "u1_oos"), ("U2_OOS_blind", B, "u2_oos"), ("U2_IS_blind", B, "u2_is")):
                r = src.get(key, {}).get("v2_safe")
                if per in P and r:
                    chk(f"v2-safe {per} net P&L $ vs results/lowloss/results.json", P[per]["capital_returns"]["pnl_usd"], r["pnl_usd"], 1e-9)
                    chk(f"v2-safe {per} capital $ vs results/lowloss/results.json", P[per]["capital_returns"]["capital_usd"], r["capital_usd"], 1e-9)
    for name in ("v2", "v2_safe"):
        S[name]["scaling"] = V["scaling"].get(name, {})
        S[name]["ceiling"] = V["ceiling"]

    # ---- tier-0
    log("tier-0: reading results/tier0/results.json")
    t0b = tier0_block(lambda cov: cost_stack("tier0", cov))
    S["tier0"] = {"name": "Tier-0 CV edge (COUNTERFACTUAL)", "cost": t0b["cost"], "periods": t0b["periods"],
                  "about": ("**" + t0b["label"] + "** A trader with a courtside 120 fps camera, our CV model, a licensed live "
                            "point feed and a London gateway, backtested on real Polymarket tapes (research/v2/tier0). "
                            "Only the verifier-corrected headline is used; the pre-registered primary's fill pricing was "
                            "refuted (DEVIATIONS V1) and is never shown as an estimate."),
                  "tier0_extra": {k: v for k, v in t0b.items() if k not in ("periods", "cost")}}
    # tier-0's IS is the 1 s-delay part of the IS only (its scenario has regime 'delay1'), not v2's 206-day IS
    t0is = t0b["periods"].get("IS", {})
    if t0b.get("scenario", {}).get("regime") == "delay1" and t0is.get("status", "").startswith("ok"):
        ndays = t0is.get("unit_economics", {}).get("calendar_days") or t0is.get("calendar_days") or t0is.get("days")
        PER_NAMES_STRAT["tier0"] = {"IS": f"IS, 1 s-delay matches only (trades from 2026-05-15{f', {ndays:.0f} d' if ndays else ''})"}

    # ---- maker
    log("maker: walk-forward IS book")
    mb = maker_book()
    mcost = cost_stack("maker")
    S["maker"] = {"name": "Maker v1, side markets", "cost": mcost, "periods": {},
                  "about": ("Leaning maker on the same match's side markets (set winner, handicaps, totals): quote only on the side "
                            "that gains from the moneyline's move, filled by takers trading against it; 0 fee + 15% rebate; "
                            "20% of each contrary print, ≤ $250 per fill, ≤ $2,000 per match; hold to resolution. "
                            "Remote-executable with public data. The idea is IS-generated (research/v2/crossmarket/RESULTS.md 5b).")}
    lock_mk = "until the side market's resolution (analyze.py capital_for: entry → match end), capital = 3 × peak locked"
    vr = jload(ROOT / "research/v2/crossmarket/verify_realism.json") or {}
    if mb is not None:
        S["maker"]["periods"]["IS"] = book_stats(mb, mcost, "maker IS (walk-forward, Feb–Aug 2026)",
                                                 "data/v2_crossmarket/wf_lean_maker.parquet", lock_mk)
        cur = mb[mb.regime == "1s/5%"]
        S["maker"]["periods"]["IS_1s5"] = book_stats(cur, mcost, "maker IS, 1 s / 5% regime",
                                                     "data/v2_crossmarket/wf_lean_maker.parquet (regime 1s/5%)", lock_mk)
        cl = vr.get("0_reproduce", {}).get("claimed", {})
        if cl:
            chk("maker IS net P&L $ vs crossmarket verify_realism.json", S["maker"]["periods"]["IS"]["capital_returns"]["pnl_usd"], cl["total_pnl_usd"], 1e-9)
            chk("maker IS per-fill mean ¢ vs verify_realism.json", S["maker"]["periods"]["IS"]["per_fill_mean_c"], cl["mean_pnl_per_share_c"], 1e-9)
            chk("maker IS capital $ vs verify_realism.json (3 × peak locked)", S["maker"]["periods"]["IS"]["capital_returns"]["capital_usd"], cl["capital"], 1e-6)
    mo = jload(ROOT / "results/maker/oos.json")
    mob = maker_book("oos") if mo else None
    if mo and mob is not None:
        blk = book_stats(mob, mcost, "maker OOS (blind, pre-registered)", "research/v2/maker/oos/book_v1.csv", lock_mk,
                         capital=mo.get("headline", {}).get("capital"), ts_exact=False)
        blk["capital_returns"]["capital_rule"] += " (taken from results/maker/oos.json: book_v1.csv rounds fill times)"
        pr_ = mo.get("primary", {})
        blk["verdict"] = {k: pr_.get(k) for k in ("statistic", "value_c", "ci95_c", "verdict", "n_fills", "n_matches")}
        blk["cost_label"] = mo.get("cost_label")
        blk["stresses_repo"] = {k: {"per_fill_c": v.get("value_c"), "ci95_c": v.get("ci95_c"),
                                    "pnl_usd": v.get("headline", {}).get("total_pnl_usd")} for k, v in mo.get("stresses", {}).items()}
        blk["derived_repo"] = mo.get("derived")
        S["maker"]["periods"]["OOS_blind"] = blk
        h = mo.get("headline", {})
        chk("maker OOS net P&L $ vs results/maker/oos.json", blk["capital_returns"]["pnl_usd"], h.get("total_pnl_usd"), 1e-5)
        chk("maker OOS per-fill mean ¢ vs results/maker/oos.json", blk["per_fill_mean_c"], h.get("mean_pnl_per_share_c"), 1e-4)
        chk("maker OOS Sharpe vs results/maker/oos.json", blk["capital_returns"]["sharpe_ann"], h.get("sharpe_ann"), 1e-4)
    else:
        S["maker"]["periods"]["OOS_blind"] = generic_block("results/maker/oos.json", "maker OOS (blind)", mcost,
                                                           "pre-registered blind OOS (research/v2/maker/PREREG.md) not run yet")
    S["maker"]["periods"]["live_paper"] = live_block(mcost, [b["capital_returns"]["capital_usd"] for k_, b in S["maker"]["periods"].items()
                                                                if k_ in ("IS", "OOS_blind") and b.get("status") == "ok"])
    S["maker"]["waterfall_note"] = ("Slippage as modelled is zero: we join the printed level and are filled at the print price. "
                                    "The realism verifier's combined conservative stress (VWAP fix + 1¢ step-ahead + no rebate) "
                                    "is in section 5d.")

    # ---- table tennis
    S["tt"] = {"name": "Table tennis (out-of-sport test)", "cost": cost_stack("tt"),
               "periods": {"results": tt_block()},
               "about": ("Out-of-sport test of the CV + book mechanism on every Polymarket table-tennis match. Liquidity "
                         "context from docs/NOTE.md section 6: 89¢ median spread, $23 at the touch, about $2 of volume per match.")}

    # ---- capacity text, coverage of costs within tested sizes
    for name in ("v2", "v2_safe"):
        s = S[name]
        sc, ce = s.get("scaling", {}), s.get("ceiling", {})
        if not sc:
            continue
        rows = ["| size | " + " | ".join(f"{p}: $/day | ¢/share | notional $/day | Sharpe | capital | max DD %" for p in ("IS", "OOS")) + " |",
                "|---|" + "---|---|---|---|---|---|" * 2]
        cov = {}
        for key, r in sc.items():
            cells = []
            for p in ("IS", "OOS"):
                x = r[p]
                cells.append(f"{f_usd(x['pnl_usd_per_day'], 1)} | {f_num(x['per_share_c'], 2, True)} | {f_usd(x['notional_usd_per_day'])} | "
                             f"{f_num(x['sharpe_ann'], 1)} | {f_usd(x['capital_usd'])} | {f_pct(x['max_dd_pct'], 1)}")
            rows.append(f"| {key} | " + " | ".join(cells) + " |")
        for p in ("IS", "OOS"):
            blk = s["periods"].get(p)
            if not blk:
                continue
            need = blk["fixed_costs"]["central"]["fixed_cost_usd_per_day"]
            hit = [k for k, r in sc.items() if r[p].get("pnl_usd_per_day", -1) >= need]
            cov[p] = (f"yes, from {hit[0]}" if hit else "no: not even with every qualifying print") + \
                     f" (central cost {f_usd(need)}/day)"
        s["coverage"] = cov
        isb, oob = s["periods"].get("IS"), s["periods"].get("OOS")
        txt = (f"**Now:** {f_usd(isb['capacity']['notional_usd_per_day_now'])} notional/day IS, "
               f"{f_usd(oob['capacity']['notional_usd_per_day_now'])} OOS. "
               f"**Outer ceiling (measured):** the qualifying fast tier's own 0–3 s prints total "
               f"{f_usd(ce['IS']['fast_tier_qualified_print_usd_per_day'])}/day IS and {f_usd(ce['OOS']['fast_tier_qualified_print_usd_per_day'])}/day OOS "
               "(walk-forward shadow rows, `src/fasttier.py`; every wallet, before v2's wallet filter and zone). "
               "**Ceiling for this rule:** the 'all prints' row below, where the engine takes every print that passes v2's "
               "wallet filter and zone, in full.\n\n"
               "Depth / impact model: the repo's engine (`research/v2/sizing/engine.py`) caps every trade at the fast-tier print "
               "it copies (the liquidity known to exist at that price) and has no price-impact model beyond that cap; a 1x "
               "book that is larger than the print is impossible by construction. The rows scale every size cap of the frozen "
               "rule (risk budget R, per-match net cap, $ per order, $ per match) by the factor, with the same walk-forward "
               "fitting. The OOS rows are new evaluations on the burned (non-blind) OOS.\n\n" + "\n".join(rows))
        # PM_REVIEW P04: what the causal curve says about capacity out of sample (derived from the rows above)
        oo = [(k, r["OOS"]) for k, r in sc.items() if r["OOS"].get("n_trades")]
        best = max(oo, key=lambda kv: kv[1]["pnl_usd_per_day"])
        pos = [(k, r) for k, r in oo if r["pnl_usd_per_day"] > 0 and r["sharpe_ann"] > 0]
        txt += (f"\n\n**Out-of-sample capacity on this evidence.** On the burned OOS, $/day peaks at {best[0]} "
                f"({f_usd(best[1]['pnl_usd_per_day'], 1)}/day, capital {f_usd(best[1]['capital_usd'])}); the largest size still "
                f"positive is {pos[-1][0]} ({f_usd(pos[-1][1]['pnl_usd_per_day'], 1)}/day, Sharpe {f_num(pos[-1][1]['sharpe_ann'], 1)}, "
                f"capital {f_usd(pos[-1][1]['capital_usd'])}), and every larger size loses money. So out-of-sample capacity is "
                f"about {f_usd(best[1]['capital_usd'])}–{f_usd(pos[-1][1]['capital_usd'])} of capital."
                + (" This replaces the sizing lens's '~$100k at Sharpe ~6' (research/v2/sizing/RESULTS.md §6), which used "
                   "onset-window labels (the D9 hindsight bug), was in-sample only, and whose $102k row is the "
                   "copy-everything Baseline, not v2." if name == "v2" else "")) if pos else ""
        s["capacity_md"] = txt
        s["caveats"] = ["IS is in-sample for the rule's selection; the OOS is burned (looked at before v2-safe was designed).",
                        "Per-share P&L moves with size because a bigger book takes a different mix of trades (more same-direction "
                        "stacking within a match once the net cap loosens; at 'all prints', every print at its full size instead of "
                        "risk-parity sizing). None of it is modelled price impact, which the engine does not have; real impact "
                        "would make the larger rows worse.",
                        "U2 has few markets before May 2026 (research/v2/expand/RESULTS.md, coverage facts), so U2-IS per-day "
                        "figures are spread over a mostly empty 201-day calendar."]
        if name == "v2_safe":
            stz = (jload(ROOT / "research/v2/lowloss/out/results.json") or {}).get("stitched_is", {})
            if stz:
                s["caveats"].append(
                    f"The IS Sharpe {f_num(s['periods']['IS']['capital_returns']['sharpe_ann'], 2)} is the frozen variant's "
                    "full-period figure and is in-sample for its own selection. The honest IS figure is the stitched "
                    f"walk-forward series: Sharpe {f_num(stz.get('sharpe_ann'), 2)}, {f_num(stz.get('per_share_c'), 2, True)}¢/share, "
                    f"{f_usd(stz.get('pnl_usd'))} (research/rigor/RESULTS.md verifier correction 4; "
                    "research/v2/lowloss/out/results.json stitched_is).")
                s["stitched_is_repo"] = {k: stz.get(k) for k in ("sharpe_ann", "per_share_c", "per_share_ci_c", "pnl_usd", "capital_usd")}
    # maker capacity
    mk = S["maker"]
    fs = vr.get("2_fill_stress", {})
    if mk["periods"].get("IS", {}).get("status") == "ok":
        b = mk["periods"]["IS"]
        T = b["unit_economics"]["calendar_days"]
        base = fs.get("base (lens fill model)", {})
        s02, s10 = fs.get("step_ahead_tick0.01_share0.2", {}), fs.get("step_ahead_tick0.01_share1.0", {})
        cons = vr.get("8_combined_conservative", {})
        mk["scaling"] = {
            "0.5x": {"pnl_usd": b["capital_returns"]["pnl_usd"] / 2, "pnl_usd_per_day": b["capital_returns"]["pnl_usd"] / 2 / T,
                     "notional_usd_per_day": b["capacity"]["notional_usd_per_day_now"] / 2,
                     "how": "exact: every cap halves with the queue share, so each fill halves and the per-match cap keeps the same fills"},
            "1x": {"pnl_usd": b["capital_returns"]["pnl_usd"], "pnl_usd_per_day": b["capital_returns"]["pnl_usd"] / T,
                   "notional_usd_per_day": b["capacity"]["notional_usd_per_day_now"], "how": "base book (20% of each contrary print)"},
            "2x": {"how": "not run by the repo; between the linear 2x and the 5x model below"},
            "5x_step_ahead_model": {"share": 1.0, "pnl_usd_all_months": s10.get("pnl_usd"), "pnl_usd_per_30d_1s5": s10.get("cur_pnl_per_30d"),
                                    "notional_usd_per_30d_1s5": s10.get("cur_notional_per_30d"),
                                    "same_model_at_1x": {"pnl_usd_all_months": s02.get("pnl_usd"), "pnl_usd_per_30d_1s5": s02.get("cur_pnl_per_30d"),
                                                         "notional_usd_per_30d_1s5": s02.get("cur_notional_per_30d")},
                                    "how": ("verify_realism.json 2_fill_stress: our quote one tick ahead of the printed level, "
                                            "filled for 100% (5x) vs 20% (1x) of each contrary print")},
            "conservative_combined": {k: cons.get(k) for k in ("per_fill_c", "pnl_usd", "notional_usd", "cur_pnl_per_30d", "cur_notional_per_30d")},
        }
        sc = mk["scaling"]
        need_ms = mk["cost"]["daily"]["central"] * 30
        mk["coverage"] = {p: (f"yes at 1x (central cost {f_usd(mk['cost']['daily']['central'], 2)}/day)"
                              if mk["periods"][p]["waterfall"]["usd_per_day"]["net_trading"] >= mk["cost"]["daily"]["central"]
                              else "no: net trading P&L is below the fixed cost") for p in ("IS", "IS_1s5", "OOS_blind")
                       if mk["periods"].get(p, {}).get("status") == "ok"}
        mk["capacity_md"] = (
            f"**Now:** {f_usd(b['capacity']['notional_usd_per_day_now'])} notional/day over Feb–Aug "
            f"({f_usd(mk['periods']['IS_1s5']['capacity']['notional_usd_per_day_now'])}/day in the 1 s / 5% regime). "
            f"**Ceiling (measured):** 100% of the contrary side-market flow, about {f_usd(s10.get('cur_notional_per_30d'))} notional per 30 days "
            f"in the current regime (verifier's step-ahead model), against {f_usd(s02.get('cur_notional_per_30d'))} at a 20% share in the same model "
            f"({f_usd(base.get('cur_notional_per_30d'))} in the base fill model). "
            "Side markets are 1.4–1.9% of moneyline in-play volume (crossmarket RESULTS.md section 1).\n\n"
            "| size | P&L | notional | model |\n|---|---|---|---|\n"
            f"| 0.5x | {f_usd(sc['0.5x']['pnl_usd'])} ({f_usd(sc['0.5x']['pnl_usd_per_day'], 1)}/day) | {f_usd(sc['0.5x']['notional_usd_per_day'])}/day | {sc['0.5x']['how']} |\n"
            f"| 1x | {f_usd(sc['1x']['pnl_usd'])} ({f_usd(sc['1x']['pnl_usd_per_day'], 1)}/day) | {f_usd(sc['1x']['notional_usd_per_day'])}/day | {sc['1x']['how']} |\n"
            f"| 2x | not run | | {sc['2x']['how']} |\n"
            f"| 1x, step-ahead model | {f_usd(s02.get('pnl_usd'))} Feb–Aug; {f_usd(s02.get('cur_pnl_per_30d'))} per 30 d at 1 s/5% | {f_usd(s02.get('cur_notional_per_30d'))} per 30 d | one tick ahead of the print, 20% share |\n"
            f"| 5x, step-ahead model | {f_usd(s10.get('pnl_usd'))} Feb–Aug; {f_usd(s10.get('cur_pnl_per_30d'))} per 30 d at 1 s/5% | {f_usd(s10.get('cur_notional_per_30d'))} per 30 d | one tick ahead, 100% of each contrary print |\n"
            f"| 1x, combined conservative | {f_usd(cons.get('pnl_usd'))} Feb–Aug ({f_num(cons.get('per_fill_c'), 2, True)}¢/fill); {f_usd(cons.get('cur_pnl_per_30d'))} per 30 d at 1 s/5% | {f_usd(cons.get('cur_notional_per_30d'))} per 30 d | VWAP fix + 1¢ step-ahead + no rebate (verifier) |\n\n"
            "The maker's depth model is the verifier's: fills are a share of the contrary taker prints that traded through our "
            "level, with a one-tick price penalty for stepping ahead of the queue; there is no historical book, so queue position "
            "is modelled, not observed (crossmarket RESULTS.md section 7).")
        pf = mk["periods"]["IS"]
        mk["caveats"] = ["The leaning-maker idea was formed on all IS months (post-hoc hypothesis); only the blind OOS can confirm it.",
                         "Hold-to-resolution variance on a tiny capital base makes the dollar series noisy (2 of 7 months negative in $).",
                         f"Per fill (the lens's own headline) the IS edge is {f_num(pf['per_fill_mean_c'], 2, True)}¢ "
                         f"{f_ci(pf['per_fill_mean_ci95_c_match_clustered'])}; share-weighted (used here, as for every strategy) it is "
                         f"{f_num(pf['per_share_c'], 2, True)}¢ {f_ci(pf['per_share_ci95_c_match_clustered'])}: the large fills earn less. "
                         "Both CIs here come from the engine's bootstrap (research/v2/sizing/engine.py metrics: 1,000 match "
                         "draws, seed 0); crossmarket RESULTS.md 5b's per-fill CI [+1.73, +3.70] comes from that lens's own "
                         "bootstrap. Same point estimate, different resampling draws.",
                         "Max drawdown here is measured against the capital base (equity starting at 0); crossmarket RESULTS.md's −44% "
                         "is measured against capital plus accumulated P&L, so the two differ."]
        mo_h = (jload(ROOT / "results/maker/oos.json") or {}).get("headline", {})
        if mo_h.get("max_dd_usd") and mo_h.get("max_dd_pct_capital"):
            den = mo_h["max_dd_usd"] / (mo_h["max_dd_pct_capital"] / 100)
            mk["caveats"].append(
                f"Same for the blind OOS: results/maker/oos.json reports {f_pct(mo_h['max_dd_pct_capital'], 1)} for the same "
                f"{f_usd(mo_h['max_dd_usd'])} drawdown, i.e. a denominator of {f_usd(den)} (capital {f_usd(mo_h.get('capital'))} "
                f"plus the equity peak); the table above divides by capital alone. Name the base when quoting either.")
    mo_ = S["maker"]["periods"].get("OOS_blind", {})
    if mo_.get("verdict"):
        v, sr = mo_["verdict"], mo_.get("stresses_repo", {})
        mk["extra_md"] = (
            f"**Blind OOS verdict (research/v2/maker/PREREG.md, primary = per-fill mean, match-clustered CI): "
            f"{f_num(v.get('value_c'), 2, True)}¢ {f_ci(v.get('ci95_c'))} over {v.get('n_fills')} fills / {v.get('n_matches')} matches: "
            f"{v.get('verdict')}.** Cost label: {mo_.get('cost_label')}. Pre-registered stresses, per fill (¢) and $: "
            + "; ".join(f"{k} {f_num(x.get('per_fill_c'), 2, True)} {f_ci(x.get('ci95_c'))}, {f_usd(x.get('pnl_usd'))}" for k, x in sr.items())
            + f". Break-even maker fee rate (derived in the repo): {f_num((mo_.get('derived_repo') or {}).get('breakeven_maker_fee_rate'), 3)}. "
            "Source: `results/maker/oos.json`; the fill book `research/v2/maker/oos/book_v1.csv` is what the tables below use.")
    # tier-0 cost breakdown (known even while the P&L is pending)
    t = S["tier0"]
    ci = t["cost"]["items"]
    if t["cost"]["daily"].get("central") is not None:
        t["extra_md"] = (
            f"**Fixed costs at the scenario's {ci['events_per_day']['central']:g} covered matches a day** (low / central / high): "
            f"per covered match {f_usd(ci['per_event_total']['low'])} / {f_usd(ci['per_event_total']['central'])} / "
            f"{f_usd(ci['per_event_total']['high'])} (operator and GPU hours plus venue access); camera kits "
            f"{f_usd(ci['camera_kits_amortised_month']['low'])} / {f_usd(ci['camera_kits_amortised_month']['central'])} / "
            f"{f_usd(ci['camera_kits_amortised_month']['high'])} a month; plus the feed licence and VPS. Total "
            f"**{f_usd(t['cost']['daily']['low'])} / {f_usd(t['cost']['daily']['central'])} / {f_usd(t['cost']['daily']['high'])} per day**, "
            "which is the trading P&L per day the counterfactual must clear to break even. With venue access at $0 and "
            f"everything else at its low value it is still {f_usd(t['cost']['daily']['low'])}/day.")
    # tier-0 capacity text
    if any(b.get("status", "").startswith("ok") for b in t["periods"].values()):
        ex2 = t["tier0_extra"]
        ncap = ex2.get("capacity_by_net_cap", {})
        lines = []
        for p in ("IS", "OOS"):
            b = t["periods"].get(p, {})
            if b.get("status", "").startswith("ok"):
                lines.append(f"{p}: reachable stale depth before caps {f_usd(b.get('capacity_stale_usd_per_day'))}/day; "
                             f"traded now {f_usd(b.get('notional_usd_per_day_now'))}/day.")
            if ncap.get(p):
                lines.append(f"{p}, corrected grid medians by net cap: " + "; ".join(
                    f"net cap {k}: {f_usd(v.get('pnl_per_day_median'))}/day, Sharpe {f_num(v.get('sharpe_median'), 1)}" for k, v in ncap[p].items()) + ".")
        t["capacity_md"] = (" ".join(lines) + "\n\nDepth model: fills are priced from the measured live book (the cost of the first n "
                            "stale shares at the same time before the reprice, src/tier0.py live_edge_curve), depth scaled by "
                            "match volume, never up. Dollar scale is set by the net cap, not by the edge.")
        for p in ("IS", "OOS"):
            b = t["periods"].get(p, {})
            if b.get("status", "").startswith("ok") and b.get("fixed_costs", {}).get("central"):
                t.setdefault("coverage", {})[p] = ("yes" if b["fixed_costs"]["central"]["net_after_costs_usd_per_day"] >= 0
                                                   else "no at the scenario's net cap")
        t["caveats"] = ["Counterfactual: the feed and the camera were not bought; every number depends on the assumptions in "
                        "research/v2/tier0/RESULTS.md section 6 and DEVIATIONS.md.",
                        "Tier-0's IS covers only the 1 s-delay matches (trades from 2026-05-15), about half of v2's 206-day IS, "
                        "so its IS dollars and per-day figures are not directly comparable with v2's IS row."]
        if (ROOT / "research/v2/tier0_v3").exists() or (ROOT / "results/tier0_v3").exists():
            t["caveats"].append("A second-round tier-0 workflow (research/v2/tier0_v3, an IS-only optimisation grid plus "
                                "verification) was still running when this was generated. Nothing from it is used here; the "
                                "numbers above are the verified revision in results/tier0/results.json and may be superseded.")

    # ---- reading notes (computed, not typed)
    reading = []
    v2i, v2o = S["v2"]["periods"].get("IS"), S["v2"]["periods"].get("OOS")
    if v2i and v2o:
        reading.append(
            f"v2 nets {f_usd(v2i['waterfall']['usd_per_day']['net_trading'])}/day IS and {f_usd(v2o['waterfall']['usd_per_day']['net_trading'])}/day "
            f"in the burned OOS before fixed costs. Taker fees take {f_num(-v2i['waterfall']['per_share_c']['taker_fees'], 2)}¢ of a "
            f"{f_num(v2i['waterfall']['per_share_c']['gross_edge'], 2)}¢ gross edge per share IS and {f_num(-v2o['waterfall']['per_share_c']['taker_fees'], 2)}¢ "
            f"of {f_num(v2o['waterfall']['per_share_c']['gross_edge'], 2)}¢ OOS.")
        c = S["v2"]["cost"]["daily"]
        reading.append(
            f"With a feed licence (ASSUMPTION, central {f_usd(COSTS['feed_licence']['central'])}/month) plus a London VPS, v2's fixed costs are "
            f"{f_usd(c['central'])}/day (range {f_usd(c['low'])}–{f_usd(c['high'])}). That leaves {f_usd(v2i['fixed_costs']['central']['net_after_costs_usd_per_day'])}/day IS "
            f"and {f_usd(v2o['fixed_costs']['central']['net_after_costs_usd_per_day'])}/day OOS at central costs.")
        v2c = S["v2"]["periods"].get("IS_1s5")
        if v2c:
            reading.append(
                f"Forecast-relevant IS row (PM_REVIEW P08): only {v2c['calendar'][0]} to {v2c['calendar'][1]} "
                f"({v2c['unit_economics']['calendar_days']} days) ran under today's 1 s delay and 5% fee. There v2 nets "
                f"{f_num(v2c['per_share_c'], 2, True)}¢ {f_ci(v2c['per_share_ci95_c_match_clustered'])} and "
                f"{f_usd(v2c['waterfall']['usd_per_day']['net_trading'], 1)}/day against {f_usd(c['central'], 1)}/day of central fixed "
                f"costs: {f_usd(v2c['fixed_costs']['central']['net_after_costs_usd_per_day'], 1)}/day. The full IS row blends fee and "
                "delay regimes that no longer exist.")
        bo = v2o.get("breakeven_taker_fee") or {}
        if bo.get("rate_before_fixed_costs") is not None:
            reading.append(
                f"Fees are the binding variable (PM_REVIEW P03). On the burned OOS taker fees are "
                f"{f_pct(bo['fee_share_of_gross'] * 100, 1)} of gross ({f_pct((v2i.get('breakeven_taker_fee') or {}).get('fee_share_of_gross', 0) * 100, 1)} IS). "
                f"With the book held fixed, the break-even taker fee rate is {f_pct(bo['rate_before_fixed_costs'] * 100, 1)} before fixed "
                f"costs and {f_pct(bo['rate_after_central_fixed_costs'] * 100, 1)} after central fixed costs; today's rate is "
                f"{f_pct(bo['uniform_rate_charged'] * 100, 0)}.")
    mi = S["maker"]["periods"].get("IS")
    mo_ = S["maker"]["periods"].get("OOS_blind", {})
    if mi and mi.get("status") == "ok":
        txt = (f"The maker is the only remote-executable book. It nets {f_usd(mi['waterfall']['usd_per_day']['net_trading'], 1)}/day IS "
               f"({f_usd(S['maker']['periods']['IS_1s5']['waterfall']['usd_per_day']['net_trading'], 1)}/day in the current 1 s / 5% regime) "
               f"against {f_usd(S['maker']['cost']['daily']['central'], 2)}/day of VPS")
        if mo_.get("verdict"):
            v = mo_["verdict"]
            txt += (f". Its pre-registered blind OOS verdict is {v.get('verdict')}: per fill {f_num(v.get('value_c'), 2, True)}¢ "
                    f"{f_ci(v.get('ci95_c'))}; in dollars it made {f_usd(mo_['waterfall']['usd_per_day']['net_trading'], 1)}/day "
                    f"({f_usd(mo_['capital_returns']['pnl_usd'])} over {mo_['unit_economics']['calendar_days']} days). The per-fill mean "
                    f"is {'positive' if (v.get('value_c') or 0) > 0 else 'not positive'} while the share-weighted mean is "
                    f"{f_num(mo_['per_share_c'], 2, True)}¢, so the larger fills did worse.")
        else:
            txt += ", but its OOS is still pending."
        reading.append(txt)
    if not any(b.get("status", "").startswith("ok") for b in S["tier0"]["periods"].values()):
        reading.append("Tier-0 is pending: the verifier-corrected headline has not been written yet. Its fixed costs are already "
                       f"known: {f_usd(S['tier0']['cost']['daily'].get('central'))}/day central "
                       f"({f_usd(S['tier0']['cost']['daily'].get('low'))}–{f_usd(S['tier0']['cost']['daily'].get('high'))}) "
                       f"for {S['tier0']['cost']['items'].get('events_per_day', {}).get('central', 'n/a')} covered matches a day.")
    else:
        tb = S["tier0"]["periods"]
        cdy = S["tier0"]["cost"]["daily"]
        reading.append("Tier-0 (counterfactual, verifier-corrected headline in results/tier0/results.json) at the scenario's net cap: " + "; ".join(
            f"{pname('tier0', p)} {f_usd(b.get('pnl_usd_per_day'), 1)}/day trading vs {f_usd(cdy['low'])} / {f_usd(cdy['central'])} / {f_usd(cdy['high'])} "
            f"per day fixed (low / central / high), so it would need {f_num(cdy['low'] / b['pnl_usd_per_day'], 1)}× its trading P&L "
            f"just to cover the low-cost case"
            for p, b in tb.items() if b.get("status", "").startswith("ok") and b.get("pnl_usd_per_day")) +
            ". Uneconomic at 10 covered matches a day in every cost case (PM_REVIEW P10).")
    stz = S["v2_safe"].get("stitched_is_repo")
    if stz:
        reading.append(f"v2-safe's honest IS Sharpe is the stitched walk-forward {f_num(stz['sharpe_ann'], 2)}, not the frozen "
                       f"variant's {f_num(S['v2_safe']['periods']['IS']['capital_returns']['sharpe_ann'], 2)} shown in the headline "
                       "(research/rigor/RESULTS.md verifier correction 4).")
    for name in ("v2", "v2_safe"):
        cov = S[name].get("coverage", {})
        if cov:
            reading.append(f"{S[name]['name']}: covers central fixed costs in IS: {cov.get('IS')}; in the burned OOS: {cov.get('OOS')} "
                           "(engine re-run at 0.5x–5x size and with every qualifying print; section "
                           f"{'2d' if name == 'v2' else '3d'}).")
    pend = [f"{S[k]['name']} {PER_NAMES.get(p, p)}" for k in S for p, b in S[k]["periods"].items() if b.get("status") == PENDING]
    if pend:
        reading.append("Pending: " + "; ".join(pend) + ".")

    R = {"generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "script": "scripts/financials.py",
         "runtime_s": None, "conventions": {
             "daily": "calendar-day zero-filled P&L from first to last trade day (research/v2/sizing/engine.py daily_series)",
             "sharpe_sortino": "x sqrt(365); Sortino denominator = RMS of negative days (scripts/lowloss_test.py)",
             "capital": "3 x peak dollars locked", "annualised": "simple x 365/days",
             "return_ci": f"iid day bootstrap, {N_BOOT_DAYS} draws, seed {SEED}",
             "win_rate_ci": f"match-clustered bootstrap, {N_BOOT_MATCH} draws",
             "per_share_ci": "match-clustered bootstrap, 1000 draws (engine metrics)",
             "max_dd": "equity path starting at 0, so a loss on day 1 counts",
             "days_per_month": DPM},
         "cost_assumptions": COSTS, "cost_of_capital": TBILL, "stacks": STACKS,
         "headline": headline_rows(S), "reading": reading, "checks": checks,
         "pending": pend}
    R["runtime_s"] = round(time.time() - t0, 1)
    # outputs
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    strip = {k: {kk: ({p: {x: y for x, y in b.items() if not x.startswith("_")} for p, b in vv.items()} if kk == "periods" else vv)
                 for kk, vv in s.items()} for k, s in S.items()}
    OUT_JSON.write_text(json.dumps(clean({**R, "strategies": strip}), indent=1, default=str))
    figure(S, OUT_FIG)
    OUT_MD.write_text(md(S, R))
    if first_run:   # the scaled books are new rule variants evaluated on the burned (non-blind) OOS
        with open(ROOT / "results/oos_peeks.log", "a") as fh:
            fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} financials: v2 / v2-safe size-scaled variants (0.5x, 2x, 5x, "
                     f"all prints) evaluated on burned OOS (non-blind, capacity curve only)\n")
    bad = [c for c in checks if not c["ok"]]
    log(f"done in {R['runtime_s']} s; {len(checks)} reference checks, {len(bad)} failed; pending: {len(pend)}")
    for c in bad:
        log("CHECK FAILED", c)
    for r in R["headline"]:
        if r["status"].startswith("ok"):
            log(f"{r['strategy']:32s} {r['period']:40s} {r['trades'] or 0:>7} {f_num(r['net_c_per_share'], 2, True):>7}c "
                f"{f_usd(r['net_trading_usd_per_day'], 1):>9}/d  after costs {f_usd(r['net_after_costs_usd_per_day']['central'], 1):>9}/d")
        else:
            log(f"{r['strategy']:32s} {r['period']:40s} pending")


if __name__ == "__main__":
    main()
