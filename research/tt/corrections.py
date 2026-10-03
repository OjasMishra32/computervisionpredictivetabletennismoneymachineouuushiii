"""Post-run corrections to the table tennis TT2/TT3 labels (research/tt/DEVIATIONS.md TT-C1 to TT-C4).

    python research/tt/corrections.py     # -> results/tt/corrections.json, redraws results/tt/fig_*.png

It does not re-run TT1-TT4. results/tt/results.json stays the record of the single pre-registered run. This script
  * computes, from the match counts alone, whether the TT2 qualification bar and the TT2/TT3 "underpowered" bar
    could have been met on this sample (the verifier's point: they could not, so TT2/TT3 are structurally
    untestable here);
  * applies the pre-registered "underpowered" label that the first run left off TT3 (labels=[] on its
    empty-shadow path; fixed in scripts/tt_analyze.py);
  * records the liquidity count and the post-hoc wallet figures the verifier asked for, read from
    results/tt/audit_checks.json and results/tt/audit_tt3.json, and checks the wallet identity on the prints;
  * redraws results/tt/fig_fasttier.png and results/tt/fig_v2_equity.png with the corrected labels, using the
    figure functions in scripts/tt_analyze.py.
Reads data/tt/prints.parquet (already evaluated); the read is logged in results/tt/peeks.log first.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import tt_analyze as TA  # noqa: E402  (chdirs to ROOT)
from src import fasttier, tiers  # noqa: E402

RES = ROOT / "results/tt"
UNDERPOWERED = 30  # HYPOTHESIS_TT.md: fewer than 30 matches -> "underpowered" (TT2 and TT3)
STRUCT = "structurally untestable on this sample"


def git_ref() -> str:
    h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    d = subprocess.run(["git", "status", "--porcelain", "research/tt/corrections.py", "scripts/tt_analyze.py"],
                       cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return h + ("+uncommitted" if d else "")


def main():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    ref = git_ref()
    with open(RES / "peeks.log", "a") as f:
        f.write(f"{now} audit: TT2/TT3 label corrections (research/tt/corrections.py): match counts per month, "
                f"0-3 s wallet identity on data/tt/prints.parquet (already evaluated); redraws the two TT figures; no "
                f"re-run of TT1-TT4, no rule, parameter or verdict change commit={ref}\n")
    R = json.loads((RES / "results.json").read_text())
    A3 = json.loads((RES / "audit_tt3.json").read_text())
    AC = json.loads((RES / "audit_checks.json").read_text())

    # ---- structural testability from match counts (the walk_forward month = month of the print's ts)
    U = pd.read_parquet(ROOT / "data/tt/universe.parquet", columns=["cond", "oos"])
    P = pd.read_parquet(ROOT / "data/tt/prints.parquet")
    P["month"] = pd.to_datetime(P.ts, unit="s").dt.to_period("M").astype(str)
    months = sorted(P.month.unique())
    evaluated = months[2:]
    assert evaluated == R["TT2"]["evaluated_months"], (evaluated, R["TT2"]["evaluated_months"])
    per_month = P.groupby("month").cond.nunique().to_dict()
    rows = []
    for m in evaluated:
        prior = int(P[P.month < m].cond.nunique())
        rows.append({"month": m, "prior_matches": prior, "matches_in_month": int(per_month[m]),
                     "qualification_bar_reachable": prior >= fasttier.MIN_MATCHES})
    wf3 = {w["month"]: w["prior_matches"] for w in A3["walk_forward"]}
    assert all(wf3[r["month"]] == r["prior_matches"] for r in rows), "prior match counts differ from audit_tt3.json"
    reach = [r["month"] for r in rows if r["qualification_bar_reachable"]]
    max_fast_matches = int(P[P.month.isin(reach)].cond.nunique())
    oos = P.cond.map(U.set_index("cond").oos)
    assert oos.notna().all()
    period_matches = {"IS": int(P[~oos.astype(bool)].cond.nunique()), "OOS": int(P[oos.astype(bool)].cond.nunique())}
    struct = {
        "evaluated_months": rows,
        "min_matches_bar": fasttier.MIN_MATCHES,
        "months_where_a_wallet_could_qualify": reach,
        "max_matches_that_could_hold_fast_tier_prints": max_fast_matches,
        "underpowered_bar": UNDERPOWERED,
        "tt2_underpowered_certain": max_fast_matches < UNDERPOWERED,
        "evaluable_matches_by_period": period_matches,
        "tt3_underpowered_certain": {k: v < UNDERPOWERED or max_fast_matches < UNDERPOWERED for k, v in period_matches.items()},
        "note": ("TT3 trades only where the fast-tier shadow has rows, so at most in the months where a wallet could "
                 "qualify; the first such month is v2's empty-training month (TT-D6: trades hold ~0 shares)."),
    }

    # ---- the most active 0-3 s wallet: identity before 2026-09 and over all months (src.tiers / src.fasttier)
    Pc = tiers.add_causal_bucket(P.drop(columns=["since_det", "with_jump_det", "bucket_c"], errors="ignore"))
    B = Pc[Pc.bucket_c == "0-3s"]
    last = evaluated[-1]
    pre = B[B.month < last].groupby("wallet").agg(n=("mo30", "size"), nm=("cond", "nunique"))
    allm = B.groupby("wallet").agg(n=("mo30", "size"), nm=("cond", "nunique"))
    w_pre, w_all = pre.n.idxmax(), allm.n.idxmax()
    wallet = {"same_wallet_before_last_month_and_all_months": bool(w_pre == w_all), "wallet_prefix": str(w_all)[:6],
              "b03_prints_all_months": int(len(B)), "b03_wallets": int(B.wallet.nunique()),
              "before_last_month": {"month": last, "prints": int(pre.loc[w_pre, "n"]), "matches": int(pre.loc[w_pre, "nm"]),
                                    "t_mo30": A3["walk_forward"][-1]["most_active_wallet_t"]},
              "all_months": A3["posthoc"]["most_active_b03_wallet_all_months"],
              "share_of_tt2_others_prints": A3["posthoc"]["most_active_wallet_share_of_tt2_others_prints"],
              "t_bar": fasttier.MIN_T,
              "source": "results/tt/audit_tt3.json walk_forward[-1], posthoc (t = mean mo30 / (sd / sqrt(matches)))"}
    assert wallet["b03_prints_all_months"] == A3["b03_by_period"]["IS"]["prints"] + A3["b03_by_period"]["OOS"]["prints"]
    assert wallet["before_last_month"]["prints"] == A3["walk_forward"][-1]["most_active_wallet_prints"]

    g = AC["ge20_inplay"]
    liquidity = {"markets": AC["fees_delays"]["markets"], "ge20_inplay_prints": g["ge20_inplay_prints"],
                 "share": g["share"], "evaluable_with_jump": g["evaluable_ok"], "dropped_no_jump": g["dropped_no_jump"],
                 "dropped_no_jump_by_league": g["no_jump_by_league"],
                 "as_written": {"matches": R["counts"]["evaluable_matches"],
                                "share": R["counts"]["evaluable_matches"] / R["counts"]["utt_markets"]},
                 "tt1_inplay_with_the_12_posthoc": AC["tt1_inplay_with_no_jump_matches_posthoc"],
                 "source": "results/tt/audit_checks.json ge20_inplay"}

    tt2 = {"verdict": R["TT2"]["verdict"], "labels_as_run": R["TT2"]["labels"],
           "labels_corrected": R["TT2"]["labels"] + [STRUCT]}
    tt3 = {p: {"verdict": R["TT3"][p]["verdict"], "labels_as_run": R["TT3"][p]["labels"],
               "labels_corrected": (["underpowered"] if R["TT3"][p]["n_matches"] < UNDERPOWERED else []) + [STRUCT],
               "evaluable_matches": period_matches[p], "matches_with_trades": R["TT3"][p]["n_matches"]}
           for p in ("IS", "OOS")}
    assert all(A3["TT3_primary_independent"][p]["underpowered"] for p in ("IS", "OOS"))
    out = {"label": "post-run label corrections; results/tt/results.json (single pre-registered run) is not re-run",
           "run_utc": now, "commit": ref, "structural": struct, "TT2": tt2, "TT3": tt3,
           "tt3_code_fix": "scripts/tt_analyze.py tt3(): empty-shadow path now writes labels=['underpowered']",
           "liquidity_count": liquidity, "most_active_b03_wallet": wallet,
           "not_evidence_about_v2_generalising": True}
    (RES / "corrections.json").write_text(json.dumps(out, indent=1, default=float))

    # ---- figures, with the corrected labels
    tt2r = dict(R["TT2"])
    pm = {r["month"]: r["prior_matches"] for r in rows}
    tt2r["monthly"] = [dict(r, prior_matches=pm[r["month"]]) for r in R["TT2"]["monthly"]]
    tt2r["structural_note"] = (f"Qualifying needs ≥ {fasttier.MIN_MATCHES} prior matches; only "
                               f"{', '.join(reach) or 'no month'} had them.\nTT2: {STRUCT}")
    TA.fig_fasttier(tt2r, RES / "fig_fasttier.png")
    tt3r = {p: dict(R["TT3"][p], labels=tt3[p]["labels_corrected"][:-1],
                    structural_note=f"{period_matches[p]} evaluable matches; bar {UNDERPOWERED}.\n{STRUCT}")
            for p in ("IS", "OOS")}
    TA.fig_equity(tt3r, pd.DataFrame(), RES / "fig_v2_equity.png")
    print(json.dumps({k: out[k] for k in ("structural", "TT2", "TT3")}, indent=1, default=float))


if __name__ == "__main__":
    main()
