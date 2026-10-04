"""How much real tennis sits behind each result.

Counts the real matches each part of the study uses and writes results/data_coverage.json:
  * Polymarket ATP/WTA match markets in the backtest universe (prices, fills, fees, delays are real),
    with the Grand Slam share by event;
  * the 1 s taker-delay pool the Tier-0 CV counterfactual trades in, and the matches it actually traded;
  * the v2 copy-trading backtest (IS / burned OOS);
  * Jeff Sackmann's Match Charting Project points (how points end: out / net / winner);
  * the TrackNet broadcast tennis set our ball tracker and landing predictor were tuned and tested on;
  * the real rally clip (Pexels) the tracker was run on end to end.

Inputs: data/raw/events_tennis_*.parquet (Gamma API listing, from scripts in src/), the tier0_v3
bundle, and committed result files. Run: python scripts/data_coverage.py
"""
import glob
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/data_coverage.json"
SLAMS = {"australian_open": "australian open", "roland_garros": "roland garros", "us_open": "us open",
         "wimbledon": "wimbledon"}


def load(p):
    return json.loads((ROOT / p).read_text())


def slam_counts(D):
    t = (D.title.fillna("") + " " + D.league.fillna("")).str.lower()
    qual = t.str.contains("qualif")
    out = {}
    for k, pat in SLAMS.items():
        hit = t.str.contains(pat)
        out[k] = {"all": int(hit.sum()), "main_draw": int((hit & ~qual).sum()), "qualifying": int((hit & qual).sum())}
    hit = t.str.contains("|".join(SLAMS.values()))
    out["total"] = {"all": int(hit.sum()), "main_draw": int((hit & ~qual).sum()), "qualifying": int((hit & qual).sum())}
    return out


def universe(D, label):
    return {"label": label, "n_matches": int(len(D)),
            "by_series": {k: int(v) for k, v in D.series.value_counts().items()},
            "first_start": str(D.start.min()), "last_start": str(D.start.max()),
            "grand_slam": slam_counts(D),
            "top_events": {k: int(v) for k, v in D.league.value_counts().head(12).items()}}


def main():
    raw = sorted(glob.glob(str(ROOT / "data/raw/events_tennis_*.parquet")))[-1]
    E = pd.read_parquet(raw)
    M = pd.read_parquet(ROOT / "results/tier0_v3/is/inputs/bundle/M.parquet")
    X = M.merge(E[["cond", "title", "series", "league"]].drop_duplicates("cond"), on="cond", how="left")
    assert X.title.notna().all(), "every backtest match must map to a Polymarket listing"

    t0_is = load("results/tier0_v3/is/results.json")
    t0_oos = load("results/tier0_v3/burned_oos/results.json")
    causal = load("results/v2/causal.json")
    mix = load("results/tier0/inputs/point_mix.json")
    tt = load("results/tennis_tracking/summary.json")

    raw_listing = {"file": Path(raw).name, "n_events": int(len(E)),
                   "by_series": {k: int(v) for k, v in E.series.value_counts().items()},
                   "note": "Wimbledon is listed under its own series and is outside the ATP/WTA backtest universe."}
    out = {
        "polymarket_backtest_universe": universe(X, "ATP/WTA singles match markets with in-play trades "
                                                    "(real prices, fills, fees, taker delays)"),
        "tier0_pool_1s_delay": universe(X[X.delay == 1], "matches in the 1 s taker-delay regime "
                                                         "(the Tier-0 CV counterfactual's pool)"),
        "tier0_traded_matches": {"IS_mean": t0_is["stitched_IS"]["n_matches"],
                                 "burned_OOS_mean": t0_oos["burned_oos"]["primary"]["n_matches"],
                                 "note": "mean over seeds of matches with at least one simulated CV trade "
                                         "(stitched IS; burned OOS primary)"},
        "v2_backtest_matches": {"IS": causal["causal/is_eval/slip0.0"]["n_matches"],
                                "burned_OOS": causal["causal/burned_oos/slip0.0"]["n_matches"],
                                "note": "matches with at least one copied fast-tier fill (results/v2/causal.json)"},
        "match_charting_project": {"source": mix["source"],
                                   "men": {k: mix["men"][k] for k in ("n_matches", "n_points", "years")},
                                   "women": {k: mix["women"][k] for k in ("n_matches", "n_points", "years")},
                                   "n_matches": mix["men"]["n_matches"] + mix["women"]["n_matches"],
                                   "n_points": mix["men"]["n_points"] + mix["women"]["n_points"]},
        "tracknet_broadcast_tennis": {"source": tt["dataset"]["name"], "matches": tt["dataset"]["matches"],
                                      "clips": tt["dataset"]["clips"],
                                      "frames_labelled": tt["dataset"]["frames_labelled"],
                                      "split": tt["dataset"].get("split"),
                                      "bounces_evaluated": tt["n_bounces_evaluated"], "outs": tt["n_out"],
                                      "note": "ball detector = pretrained TrackNet weights (yastrebksv); landing "
                                              "predictors and call thresholds tuned by us on games 1-7, tested once on 8-10"},
        "real_rally_clip": {"source": "Pexels video 10378830 (licence in results/viz/v60_assets/tennis_real/LICENSE.md)",
                            "files": "results/viz/v60_assets/tennis_real/"},
        "polymarket_listing_raw": raw_listing,
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    u, p = out["polymarket_backtest_universe"], out["tier0_pool_1s_delay"]
    print(f"backtest universe {u['n_matches']} matches, Grand Slam {u['grand_slam']['total']}")
    print(f"1 s pool {p['n_matches']} matches, Grand Slam {p['grand_slam']['total']}")
    print(f"MCP {out['match_charting_project']['n_matches']} matches / {out['match_charting_project']['n_points']} points")
    print(f"TrackNet {out['tracknet_broadcast_tennis']['matches']} matches, {out['tracknet_broadcast_tennis']['clips']} clips")
    print("->", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
