"""Red-team C3 + C4: how solid is the post hoc 3.14 s stamp lag, and why does the per-point reading lose?

    python scripts/redteam_stamp_lag.py      # -> results/redteam/stamp_lag.json (seconds, no network)

DESCRIPTIVE ONLY. Inputs are the live-day snapshot of 2026-10-03 that `src/tier0.py::calibrate_stamp_lag` reads
(research/v2/latency/out/{trades_around_reprice,m1_points}.csv, recorded before the forward window opened at
14:00 UTC), so no held-out or forward data is read and no peek-log line is needed. Nothing here changes a rule or a
published number; it asks how much the inference moves when its own choices move.

The inference (src/tier0.py, unchanged, re-implemented here so its choices can be varied):
    per point, take the EARLIEST with-move print in a window before the reprice; assume it was sent by a courtside
    human `react` s after the bounce, over `net` s of network, and held by the venue `delay` = 1 s; then
        t_reprice - t_bounce = (t_reprice - t_print) + delay + net + react
        stamp lag L          = (t_reprice - t_bounce) - (t_reprice - t_stamp)
    and L is the median over points.

Checks (INTEGRATION_TODO C3, C4; reviewer attacks U2, U3, U7):
  base         reproduces results/tier0/results.json::inputs.stamp_lag_calibration (3.142 s, n = 49)
  bootstrap    2,000 resamples of the points (seed 0): CI of the median L
  windows      [-0.25, 0) and [-1, 0) instead of [-0.5, 0)
  exclusion    drop prints <= 100 ms before the reprice (a print that close may BE the reprice, not a reaction)
  reaction     machines: L for react 0.02-0.30 s and net 0.002-0.15 s (linear in both)
  clock        share of reprices and of first prints within 100 ms after a whole UTC second (uniform: 10 %)
  per-point    C4 as an exact bound: under the per-point reading every reprice is at most max(t_reprice - t_bounce)
               after the bounce; compare with the earliest possible arrival of a 1 s-feed order.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LAT = ROOT / "research/v2/latency/out"
OUT = ROOT / "results/redteam/stamp_lag.json"
DELAY, NET, REACT = 1.0, 0.067, 0.25
T_INF, GATEWAY = 0.020, 0.002          # src/tier0.py T_INF, GATEWAY
MIN_REGION_NET = 0.010                 # src/tier0.py REGION_MS["Europe"] (the smallest region latency)
MAX_OFFLINE_LEAD = 0.200               # longest CV lead in any call table (own120 / engine), s


def load():
    t = pd.read_csv(LAT / "trades_around_reprice.csv")
    m = pd.read_csv(LAT / "m1_points.csv")
    m = m[m.ok == True]  # noqa: E712
    return t, m


def first_prints(t, m, lo=-0.5, hi=0.0, exclude_last_s=0.0):
    w = t[(t.dt_s >= lo) & (t.dt_s < hi - exclude_last_s)]
    ww = w[w.with_move]
    share = float((w.usd * w.with_move).sum() / w.usd.sum()) if len(w) else float("nan")
    f = ww.groupby(["slug", "n"]).dt_s.min().rename("dt_first").reset_index()
    f = f.merge(m[["slug", "n", "book_vs_T_s", "t_book"]], on=["slug", "n"], how="inner")
    return f, share


def lag_of(f, react=REACT, net=NET, delay=DELAY):
    tb = -f.dt_first + delay + net + react
    return tb, tb - f.book_vs_T_s


def r3(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 3)


def main():
    t, m = load()
    pub = json.loads((ROOT / "results/tier0/results.json").read_text())["inputs"]["stamp_lag_calibration"]
    f, share = first_prints(t, m)
    tb, L = lag_of(f)
    base = {"n_points": int(len(f)), "share_usd_with_move": r3(share), "stamp_lag_median_s": r3(L.median()),
            "t_reprice_minus_t_bounce_median_s": r3(tb.median()),
            "published": {"n_points": pub["n_points"], "stamp_lag_s": pub["central"]["stamp_lag_s"]}}
    base["reproduces_published"] = (base["n_points"] == pub["n_points"]
                                    and abs(base["stamp_lag_median_s"] - pub["central"]["stamp_lag_s"]) < 0.002)
    assert base["reproduces_published"], base

    rng = np.random.default_rng(0)
    Lv = L.to_numpy()
    bs = np.array([np.median(Lv[rng.integers(0, len(Lv), len(Lv))]) for _ in range(2000)])
    boot = {"median_L_ci95_s": [r3(np.percentile(bs, 2.5)), r3(np.percentile(bs, 97.5))],
            "share_of_resamples_L_below_3_0": r3((bs < 3.0).mean()),
            "share_of_resamples_L_below_2_5": r3((bs < 2.5).mean()),
            "per_point_L_quantiles_s": {q: r3(np.quantile(Lv, float(q))) for q in ("0.1", "0.25", "0.5", "0.75", "0.9")},
            "note": "per-point L is bimodal because the official stamp has 1 s resolution (T_ms mod 1000 = 0 on "
                    "every point): book_vs_T_s carries up to 1 s of rounding, so the median is the robust summary"}

    windows = {}
    for name, lo, hi, ex in (("[-0.5,0) base", -0.5, 0.0, 0.0), ("[-0.25,0)", -0.25, 0.0, 0.0),
                             ("[-1,0)", -1.0, 0.0, 0.0), ("[-0.5,-0.1) exclude last 100 ms", -0.5, 0.0, 0.1),
                             ("[-1,-0.1) exclude last 100 ms", -1.0, 0.0, 0.1)):
        g, sh = first_prints(t, m, lo, hi, ex)
        tbg, Lg = lag_of(g)
        windows[name] = {"n_points": int(len(g)), "share_usd_with_move": r3(sh),
                         "stamp_lag_median_s": r3(Lg.median()) if len(g) else None,
                         "t_reprice_minus_t_bounce_median_s": r3(tbg.median()) if len(g) else None}

    reaction = []
    for react in (0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        for net in (0.002, 0.010, 0.067, 0.150):
            _, Lr = lag_of(f, react, net)
            reaction.append({"react_s": react, "net_s": net, "stamp_lag_median_s": r3(Lr.median())})
    bot = next(r for r in reaction if r["react_s"] == 0.02 and r["net_s"] == 0.002)

    # whole-second clock: reprices (all 482 ok points) and the first with-move prints (49 points)
    rep_ms = (m.t_book % 1000).to_numpy()
    fp_ms = ((f.t_book + 1000 * f.dt_first) % 1000).to_numpy()
    clock = {"reprices_n": int(len(rep_ms)),
             "reprices_share_0_100ms_after_second": r3(((rep_ms >= 0) & (rep_ms < 100)).mean()),
             "reprices_share_50_100ms_after_second": r3(((rep_ms >= 50) & (rep_ms < 100)).mean()),
             "first_prints_n": int(len(fp_ms)),
             "first_prints_share_0_100ms_after_second": r3(((fp_ms >= 0) & (fp_ms < 100)).mean()),
             "uniform_share_per_100ms": 0.1,
             "official_stamps_whole_second_share": r3((m.T_ms % 1000 == 0).mean()),
             "reading": "Reprices and the prints that cause them cluster just after whole UTC seconds, consistent "
                        "with the venue releasing delayed orders on a 1 s clock (not verified). The simulation "
                        "treats the hold as a continuous 1.000 s per order. If release is batched with time priority "
                        "inside a batch, the race is unchanged; if priority inside a batch is not by send time, a "
                        "later order can still fill and the model is conservative for us; neither was measured."}

    # C4: exact bound for the per-point reading at V = 1
    tb_max = float(tb.max())
    arrival_min_v1 = -MAX_OFFLINE_LEAD + T_INF + 1.0 + MIN_REGION_NET + GATEWAY + DELAY
    v_needed = tb_max - (-MAX_OFFLINE_LEAD + T_INF + MIN_REGION_NET + GATEWAY + DELAY)
    per_point = {"t_reprice_minus_t_bounce_s": {"min": r3(tb.min()), "median": r3(tb.median()), "max": r3(tb_max)},
                 "earliest_arrival_after_bounce_at_V1_s": r3(arrival_min_v1),
                 "assumptions": "call 200 ms before the bounce (longest lead in any call table), 20 ms inference, "
                                "10 ms network (Europe, the closest region), 2 ms gateway, 1 s venue hold",
                 "correct_calls_that_can_fill_at_V1": int((tb > arrival_min_v1).sum()),
                 "largest_V_where_any_point_can_fill_s": r3(v_needed),
                 "statement": "Read per point, the inference itself puts every reprice at most "
                              f"{tb_max:.2f} s after the bounce. A 1 s-feed order cannot land before "
                              f"{arrival_min_v1:.2f} s even with a 200 ms early call, so at V = 1 no correct call "
                              "fills on any of the 49 points; only wrong calls fill, which is why the stamp-"
                              "calibrated cell loses about $17/day (latency_sweep.json::video_own120."
                              "stamp_calibrated[\"1\"]). Same data, same inference: the constant-lag reading moves "
                              "the median reprice to about 1.8 s after the bounce, the per-point reading keeps it at "
                              f"{tb.median():.2f} s."}

    res = {"label": "DESCRIPTIVE (live-day snapshot 2026-10-03, pre-forward-window); INFERENCE robustness, not a "
                    "measurement of the stamp lag", "script": "scripts/redteam_stamp_lag.py",
           "inputs": ["research/v2/latency/out/trades_around_reprice.csv", "research/v2/latency/out/m1_points.csv"],
           "base": base, "bootstrap": boot, "windows": windows, "reaction_time": reaction,
           "machines_20ms_london": bot, "whole_second_clock": clock, "per_point_reading_V1": per_point,
           "bottom_line": None}
    lo, hi = boot["median_L_ci95_s"]
    ws = [v["stamp_lag_median_s"] for v in windows.values() if v["stamp_lag_median_s"] is not None]
    res["bottom_line"] = (f"Median stamp lag {base['stamp_lag_median_s']} s (n = {base['n_points']}), but the "
                          f"bootstrap 95 % CI is [{lo}, {hi}] s and {boot['share_of_resamples_L_below_2_5']:.0%} of "
                          f"resamples fall below 2.5 s: per-point lags are bimodal because the official stamp has "
                          f"1 s resolution. Across the five print windows the median runs {min(ws)}-{max(ws)} s. "
                          f"Bots instead of humans: {bot['stamp_lag_median_s']} s. So the post hoc 3.14 s is one "
                          "mode of a two-mode estimate, not a tight number. It also rests on the untested premise "
                          "that the first informed prints react to the bounce. Read per point, the same inference "
                          "cannot fill a correct call at V = 1.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("base", "bootstrap", "windows", "machines_20ms_london",
                                          "whole_second_clock", "per_point_reading_V1", "bottom_line")}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
