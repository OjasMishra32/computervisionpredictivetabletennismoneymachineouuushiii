"""Red-team derived numbers: every number the Q&A sheet and the integration TODO derive by arithmetic, computed
from the results files so the paper, deck and video can read ONE file instead of retyping them.

    python scripts/redteam_derived.py        # -> results/redteam/derived.json (seconds, no network, no OOS read)

No simulation is run and no held-out data is read: every input is an existing results file (already-computed
cells, including burned-OOS cells that were logged when they were computed). Each key carries its value, its
source (file::key) and, for derived values, the formula. Keys follow INTEGRATION_TODO P-13.

Model identity used (research/v2/feed_latency/LATENCY_SWEEP.md §3; latency_sweep.json::model): under the
tournament reading only t_reprice - t_bounce enters the race, so video(V, lag L) = video(V - (L - 2.0), lag 2.0).
Reading a cell "at V = 1, lag L" therefore means reading the dense lag-2.0 curve at V' = 3.0 - L.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/redteam/derived.json"
SW = "results/tier0/latency_sweep.json"
SWC = "results/tier0/latency_sweep.csv"
T0 = "results/tier0/results.json"
FIN = "results/financials/financials.json"
ENG = "results/engine/online_vs_offline.json"
ALPHA = "results/alpha/alpha.json"
LAGJ = "results/redteam/stamp_lag.json"
DAYS_PER_MONTH = 30.42
RUN = "fp16_cl_fuse_compile_b1_realtime"


def j(p):
    return json.loads((ROOT / p).read_text())


def rnd(x, nd=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return int(round(float(x))) if nd == 0 else round(float(x), nd)


def curve(S: pd.DataFrame, period: str, reading: str = "tournament", cv: str = "own120") -> pd.DataFrame:
    m = S[(S.source == "video") & (S.cv == cv) & (S.reading == reading) & (S.period == period) & (S.x_s <= 3.0)]
    return m.sort_values("x_s")


def at_v(c: pd.DataFrame, v: float, col: str = "pnl_per_day_usd") -> float:
    return float(np.interp(v, c.x_s.to_numpy(float), c[col].to_numpy(float)))


def first_below(c: pd.DataFrame, level: float) -> float:
    """First V (linear interpolation) where $/day drops below `level`."""
    xs, ys = c.x_s.to_numpy(float), c.pnl_per_day_usd.to_numpy(float) - level
    if ys[0] <= 0:
        return 0.0
    for i in range(1, len(xs)):
        if ys[i] <= 0:
            return float(xs[i - 1] + (xs[i] - xs[i - 1]) * ys[i - 1] / (ys[i - 1] - ys[i]))
    return math.inf


def main():
    sw, t0, fin, eng = j(SW), j(T0), j(FIN), j(ENG)
    S = pd.read_csv(ROOT / SWC)
    v = sw["video_own120"]
    P = {"is": "IS", "oos": "burned_OOS"}
    K: dict[str, dict] = {}

    def put(key, value, source, formula=None, nd=2):
        K[key] = {"value": value if isinstance(value, (str, list, dict)) or value is None else rnd(value, nd),
                  "source": source}
        if formula:
            K[key]["formula"] = formula

    cal_lag = t0["timing"]["calibrated_stamp_lag_s (inference)"]
    pre_lag = 2.0
    put("cv.cal.lag", cal_lag, f"{T0}::timing[\"calibrated_stamp_lag_s (inference)\"]", nd=3)
    put("cv.pre.lag", pre_lag, "src/tier0.py::CORRECTED.stamp_lag (pre-registered)")
    put("cv.cal.shift", cal_lag - pre_lag - 1.0, "derived", "cv.cal.lag - cv.pre.lag - 1.0 (V = 1 at L = cal == "
        "camera this many s AHEAD of the bounce at L = 2.0)")

    for k, p in P.items():
        put(f"cv.pre.{k}.usd", v["tournament"]["1"][p]["usd_per_day"], f"{SW}::video_own120.tournament[\"1\"].{p}.usd_per_day")
        put(f"cv.cal.{k}.usd", v["tournament_lagcal"]["1"][p]["usd_per_day"], f"{SW}::video_own120.tournament_lagcal[\"1\"].{p}.usd_per_day")
        put(f"cv.stc.{k}.usd", v["stamp_calibrated"]["1"][p]["usd_per_day"], f"{SW}::video_own120.stamp_calibrated[\"1\"].{p}.usd_per_day")
        put(f"cv.stn.{k}.usd", v["stamp"]["1"][p]["usd_per_day"], f"{SW}::video_own120.stamp[\"1\"].{p}.usd_per_day")
        be = sw["breakeven_video_delay"]
        put(f"cv.pre.be.{k}", be["tournament"][p]["breakeven_V_s_seed_mean_curve"], f"{SW}::breakeven_video_delay.tournament.{p}.breakeven_V_s_seed_mean_curve")
        put(f"cv.cal.be.{k}", be["tournament_lagcal"][p]["breakeven_V_s_seed_mean_curve"], f"{SW}::breakeven_video_delay.tournament_lagcal.{p}.breakeven_V_s_seed_mean_curve")
        put(f"cv.stc.be.{k}", be["stamp_calibrated"][p]["breakeven_V_s_seed_mean_curve"], f"{SW}::breakeven_video_delay.stamp_calibrated.{p}.breakeven_V_s_seed_mean_curve")
        pess = sw["video_cv_pessimistic"]["tournament"]
        put(f"cv.pess.pre.{k}.usd", pess["1"][p]["usd_per_day"], f"{SW}::video_cv_pessimistic.tournament[\"1\"].{p}.usd_per_day")
        put(f"cv.pess.l3.{k}.usd", pess["0"][p]["usd_per_day"], f"{SW}::video_cv_pessimistic.tournament[\"0\"].{p}.usd_per_day",
            "= pessimistic CV at V = 1, L = 3.0 by the model identity")
    be_is = sw["breakeven_video_delay"]["tournament"]["IS"]["breakeven_V_s_seed_mean_curve"]
    put("cv.call_before_stamp", pre_lag - be_is - 0.02, "derived", "cv.pre.lag - cv.pre.be.is - 0.02 s inference "
        "(how far before the umpire's stamp the CV call must be made, pre-registered reading)", nd=1)
    put("cv.pre.oos.c", v["tournament"]["1"]["burned_OOS"]["net_c_per_share"], f"{SW}::video_own120.tournament[\"1\"].burned_OOS.net_c_per_share", nd=3)
    put("cv.pre.oos.ci", v["tournament"]["1"]["burned_OOS"]["net_c_per_share_ci95"], f"{SW}::video_own120.tournament[\"1\"].burned_OOS.net_c_per_share_ci95")
    put("cv.cal.oos.c", v["tournament_lagcal"]["1"]["burned_OOS"]["net_c_per_share"], f"{SW}::video_own120.tournament_lagcal[\"1\"].burned_OOS.net_c_per_share", nd=3)

    vps = fin["cost_assumptions"]["vps_london"]["central"]
    low_day = fin["strategies"]["v2"]["cost"]["daily"]["low"]
    cen_day = fin["strategies"]["v2"]["cost"]["daily"]["central"]
    put("fin.feed.low", fin["cost_assumptions"]["feed_licence"]["low"], f"{FIN}::cost_assumptions.feed_licence.low (ASSUMPTION)")
    put("fin.feed.high", fin["cost_assumptions"]["feed_licence"]["high"], f"{FIN}::cost_assumptions.feed_licence.high (ASSUMPTION)")
    put("fin.cost.low_day", low_day, f"{FIN}::strategies.v2.cost.daily.low")
    put("fin.cost.central_day", cen_day, f"{FIN}::strategies.v2.cost.daily.central")
    for r in ("pre", "cal"):
        for k in P:
            usd = K[f"cv.{r}.{k}.usd"]["value"]
            put(f"cv.{r}.{k}.maxlic", usd * DAYS_PER_MONTH - vps, "derived",
                f"cv.{r}.{k}.usd x {DAYS_PER_MONTH} - {FIN}::cost_assumptions.vps_london.central ({vps:.2f}); "
                "the most the book can pay for data per month", nd=0)
            put(f"cv.{r}.{k}.net_low", usd - low_day, "derived", f"cv.{r}.{k}.usd - fin.cost.low_day")
            put(f"cv.{r}.{k}.net_central", usd - cen_day, "derived", f"cv.{r}.{k}.usd - fin.cost.central_day")
            put(f"cv.{r}.{k}.annual_gross", usd * 365, "derived", f"cv.{r}.{k}.usd x 365", nd=0)

    # stamp lag needed at V = 1 (identity on the dense lag-2.0 tournament curve)
    for k, p in P.items():
        c = curve(S, p)
        vb = first_below(c, 0.0)
        put(f"cv.L_breakeven.{k}", 3.0 - vb, "derived", f"3.0 - V* where V* = first V with $/day < 0 on {SWC} "
            f"(video, own120, tournament, {p}, x_s <= 3)", nd=2)
        vl = first_below(c, low_day)
        put(f"cv.L_for_low.{k}", 3.0 - vl, "derived", f"3.0 - V* where V* = first V with $/day < fin.cost.low_day "
            f"on {SWC} (video, own120, tournament, {p})", nd=2)
        vc = first_below(c, cen_day)
        put(f"cv.L_for_central.{k}", (3.0 - vc) if vc > 0 else "not covered at any L <= 3.0", "derived",
            "as cv.L_for_low with fin.cost.central_day", nd=2)
        for rd, key in (("tournament", "pre"), ("tournament_lagcal", "cal")):
            row = S[(S.source == "video") & (S.cv == "own120") & (S.reading == rd) & (S.period == p) & (np.isclose(S.x_s, 1.0))]
            put(f"cv.{key}.{k}.cap", float(row.capital_usd.iloc[0]), f"{SWC}::capital_usd (video, own120, {rd}, {p}, x_s = 1.0)", nd=0)

    # reaction-time and bootstrap readings through the identity
    lagj = j(LAGJ) if (ROOT / LAGJ).exists() else None
    if lagj:
        L_bot = lagj["machines_20ms_london"]["stamp_lag_median_s"]
        lo, hi = lagj["bootstrap"]["median_L_ci95_s"]
        put("cv.L_bot", L_bot, f"{LAGJ}::machines_20ms_london.stamp_lag_median_s (react 20 ms, London 2 ms)", nd=3)
        put("cv.L_boot_ci", [lo, hi], f"{LAGJ}::bootstrap.median_L_ci95_s")
        put("cv.L_boot_share_below_2_5", lagj["bootstrap"]["share_of_resamples_L_below_2_5"], f"{LAGJ}::bootstrap.share_of_resamples_L_below_2_5", nd=3)
        for name, L in (("bot", L_bot), ("boot_lo", lo)):
            for k, p in P.items():
                c = curve(S, p)
                put(f"cv.at_L_{name}.{k}.usd", at_v(c, 3.0 - L), "derived",
                    f"$/day at V = 1, L = {L} = lag-2.0 tournament curve at V' = {3.0 - L:.3f} ({SWC}, linear "
                    "interpolation on the 0.05 s grid; a model statement, not new evidence)", nd=1)
        put("cv.stc.max_tb", lagj["per_point_reading_V1"]["t_reprice_minus_t_bounce_s"]["max"], f"{LAGJ}::per_point_reading_V1")
        put("cv.stc.arrival_min_v1", lagj["per_point_reading_V1"]["earliest_arrival_after_bounce_at_V1_s"], f"{LAGJ}::per_point_reading_V1")
        put("venue.reprices_0_100ms_after_second", lagj["whole_second_clock"]["reprices_share_0_100ms_after_second"], f"{LAGJ}::whole_second_clock", nd=3)
        put("venue.first_prints_0_100ms_after_second", lagj["whole_second_clock"]["first_prints_share_0_100ms_after_second"], f"{LAGJ}::whole_second_clock", nd=3)

    st = t0["stresses_corrected"]
    pool = st["live pool = all 482 points"]["burned_OOS"]["mean"]
    put("cv.pool482.oos.c", pool["per_share_c"], f"{T0}::stresses_corrected[\"live pool = all 482 points\"].burned_OOS.mean.per_share_c (V = 0)", nd=2)
    put("cv.pool482.oos.ci", [rnd(pool["per_share_ci95_c_lo"]), rnd(pool["per_share_ci95_c_hi"])], f"{T0}::stresses_corrected[\"live pool = all 482 points\"].burned_OOS.mean.per_share_ci95_c_*")
    nc = st["net cap 1000"]["burned_OOS"]["mean"]
    put("cv.netcap1000.oos.usd", nc["pnl_per_day_usd"], f"{T0}::stresses_corrected[\"net cap 1000\"].burned_OOS.mean.pnl_per_day_usd (V = 0)", nd=0)

    # live causal engine
    A = eng["runs"][RUN]["A_engine_calls"]
    put("eng.tp", A["online"]["50ms"]["tp"], f"{ENG}::runs.{RUN}.A_engine_calls.online[\"50ms\"].tp", nd=0)
    put("eng.nmiss", A["miss_first_call_lead_ms"]["n_miss"], f"{ENG}::runs.{RUN}.A_engine_calls.miss_first_call_lead_ms.n_miss", nd=0)
    put("eng.wil_lo", 100 * A["online"]["50ms"]["precision_wilson95"][0], f"{ENG}::runs.{RUN}.A_engine_calls.online[\"50ms\"].precision_wilson95[0] (x100, %)", nd=0)
    put("eng.lead_med", A["miss_first_call_lead_ms"]["median"], f"{ENG}::runs.{RUN}.A_engine_calls.miss_first_call_lead_ms.median (ms)", nd=1)
    hook = [f for f in eng["runs"][RUN]["flights_called_or_miss"] if f["video"] == "test_2" and f["f_net"] == 2819]
    if hook:
        put("eng.hook_lead_ms", hook[0]["lead_engine_call_ms"], f"{ENG}::runs.{RUN}.flights_called_or_miss[video=test_2,f_net=2819].lead_engine_call_ms", nd=0)
        put("eng.hook_lead_offline_ms", hook[0]["lead_offline_ms"], f"{ENG}::runs.{RUN}.flights_called_or_miss[video=test_2,f_net=2819].lead_offline_ms", nd=0)
    hs = eng["headline"][RUN]["stream"]["after_startup"]
    put("eng.call_ready_p50_ms", hs["call_ready_ms"]["p50"], f"{ENG}::headline.{RUN}.stream.after_startup.call_ready_ms.p50")
    put("eng.call_ready_p99_ms", hs["call_ready_ms"]["p99"], f"{ENG}::headline.{RUN}.stream.after_startup.call_ready_ms.p99")
    put("eng.frames", eng["headline"][RUN]["stream"]["frames"], f"{ENG}::headline.{RUN}.stream.frames", nd=0)
    put("eng.dropped", eng["headline"][RUN]["stream"]["dropped"], f"{ENG}::headline.{RUN}.stream.dropped", nd=0)

    # phantom MISS calls (no rally-state gate): what a gate must achieve, as a requirement, not a prediction
    calls = eng["runs"][RUN]["calls"]
    video_s = eng["headline"][RUN]["stream"]["video_s"]
    off = calls["unmatched"]["MISS"]
    between = calls["unmatched"]["MISS_outside_rally_ranges"]
    rate_h = off / video_s * 3600
    fee_c = 100 * 0.05 * 0.25          # 5 % fee x q(1 - q) at q = 0.5, cents/share (the 2026 fee regime)
    slip_c = 0.5                       # src/tier0.py Scenario.slip (half the measured 1c spread)
    cost_per_call = (fee_c + slip_c) / 100 * 100     # $ for 100 shares (the per-match net cap), entry only
    put("eng.phantom_miss_per_hour", rate_h, f"{ENG}::runs.{RUN}.calls.unmatched.MISS ({off}) / stream.video_s "
        f"({video_s}) x 3600; {between} of them between rallies", nd=1)
    put("eng.phantom_cost_per_call_usd", cost_per_call, "derived", "100 shares x (fee 5 % x 0.25 + half spread "
        "0.5c), entry only, mark-to-mid; no move on a phantom point", nd=2)
    for r in ("pre", "cal"):
        usd = K[f"cv.{r}.oos.usd"]["value"]
        put(f"eng.phantom_budget_per_day.{r}", usd / cost_per_call, "derived",
            f"cv.{r}.oos.usd / eng.phantom_cost_per_call_usd: phantom trades a day that erase the OOS 1 s P&L", nd=1)

    # capacity (v2) from alpha.json, for the deck/video before results/capacity lands
    try:
        a = j(ALPHA)
        cap = a["headline"]["oos_capital_capacity_usd"]
        put("v2.oos.capacity_usd", cap, f"{ALPHA}::headline.oos_capital_capacity_usd")
    except Exception as e:  # noqa: BLE001
        put("v2.oos.capacity_usd", f"unavailable: {e}", ALPHA)

    res = {"label": "DERIVED from existing results files; no simulation, no new held-out read. SIMULATED cells are "
                    "labelled in their source files (assumed licensed feed, not purchased; parameters measured).",
           "script": "scripts/redteam_derived.py", "keys": K}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    w = max(len(k) for k in K)
    for k, d in K.items():
        print(f"{k:<{w}}  {d['value']}")


if __name__ == "__main__":
    main()
