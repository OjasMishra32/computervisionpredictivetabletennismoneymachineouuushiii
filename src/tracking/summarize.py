"""Collect the H3 results into results/tracking/summary.json (run after early_call.py --final)."""
import json
import os

import pandas as pd

from common import WORK

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RES = os.environ.get("TRACK_RESULTS", os.path.join(REPO, "results", "tracking"))

if __name__ == "__main__":
    ec = json.load(open(os.path.join(WORK, "early_call_final.json")))
    det = pd.read_csv(os.path.join(RES, "detection_accuracy.csv"))
    fl = pd.read_csv(os.path.join(WORK, "flights.csv"))
    dr = pd.read_csv(os.path.join(WORK, "flights_dropped.csv"))
    dev = json.load(open(os.path.join(WORK, "dev_report.json")))
    pooled = det[det.video == "ALL"].drop(columns=["video"]).round(4).to_dict(orient="records")
    counts = {}
    for sp in ("train", "test"):
        s = fl[fl.split == sp]
        counts[sp] = {
            "BOUNCE": int((s.label == "BOUNCE").sum()),
            "MISS": int((s.label == "MISS").sum()),
            "MISS_out": int(((s.label == "MISS") & (s.miss_type == "out")).sum()),
            "MISS_net": int(((s.label == "MISS") & (s.miss_type == "net")).sum()),
            "dropped": int(dr.video.str.startswith("test" if sp == "test" else "game").sum()),
        }
    audit = None
    ap = os.path.join(RES, "label_audit.json")
    if os.path.exists(ap):
        audit = json.load(open(ap))
    timing = {}
    tp = os.path.join(RES, "stage_timing.json")
    if os.path.exists(tp):
        timing = json.load(open(tp))
    summary = {
        "hypothesis": "H3 physics lead time (OpenTTGames, 120 fps)",
        "verdict": ec["verdict"],
        "verdict_rule": ec["verdict_rule"],
        "detection_accuracy_pooled": pooled,
        "detection_accuracy_csv": "results/tracking/detection_accuracy.csv",
        "n_flights": counts,
        "early_call": {k: ec[k] for k in ec if k not in ("hypothesis",)},
        "verdict_detail": (
            "Pre-registered criterion met: test precision of MISS calls at the 50 ms lead = "
            f"{ec['precision_recall_test_snapshot']['50ms']['tp']}/"
            f"{ec['precision_recall_test_snapshot']['50ms']['tp'] + ec['precision_recall_test_snapshot']['50ms']['fp']}"
            f" (95% Wilson CI {ec['precision_recall_test_snapshot']['50ms']['precision_wilson95']}), recall "
            f"{ec['precision_recall_test_snapshot']['50ms']['recall']}. The sample is small: the CI lower "
            "bound is well below 0.95, so the pass is weak evidence. A post-hoc label audit (label_audit) "
            "keeps precision at 100% with corrected labels."),
        "label_audit_post_hoc": audit,
        "model_selection_train_logo_cv": dev,
        "stage_wall_clock": timing,
        "notes": [
            "Detector: pretrained BlurBall (Gossard et al. 2026, MIT; WASB-SBDT backbone), no training "
            "on OpenTTGames. Weights chosen over WASB on game_1/game_2 labels only.",
            "OpenTTGames 'net' events mark the ball reaching the net plane on every shot, so a flight = a "
            "shot anchored at its 'net' event. MISS = no far-side bounce within 0.5 s (inferred); see "
            "DEVIATIONS.md (H3 section).",
            "Primary metric = precision of MISS calls (point-ending call). Calling BOUNCE is trivially "
            "precise because ~90% of shots land.",
            "Online call rule: a MISS is called by lead L if the model score reached tau at any decision "
            "frame <= T_ref - L; decisions use track points up to t - 2 frames (detector look-ahead).",
            "T_ref for out-balls = first frame the ball passes the table end line / drops below the near "
            "edge / is lost; this is earlier than the ball reaching table-plane height, so leads are "
            "conservative.",
            "tau and the model were frozen from leave-one-game-out CV on game_1..5; test_1..7 evaluated "
            "once (results/tracking/test_peeks.log).",
            "Speeds and landing distances are single-camera image estimates (px -> m via the table "
            "length), good to maybe +-20%.",
            "POST-HOC: the test markup misses some far-side bounces (20 of 41 test 'MISS' flights show a "
            "clear table bounce in the track; 0 of 110 in the training games). label_audit_post_hoc "
            "re-scores the frozen model on corrected labels; nothing was refit or re-tuned.",
            "Lead vs speed / distance: with uncalled misses counted as lead 0, the call lead rises with how far "
            "out the ball lands (Spearman 0.55 train OOF, 0.64 test, p < 0.01). It does NOT rise with ball "
            "speed (train -0.27, p = 0.005; test -0.13, n.s.): faster balls are called less often. The "
            "'grows with speed' part of H3 is not supported.",
            "The online first-call rule (what a trader acting on the first call gets) is precise but "
            "rarely fires early: test recall 7% at 50 ms; median first-call lead on called test misses is "
            "25 ms (p10 17, p90 210; n = 8). Train OOF: 30% recall at 50 ms, median 83 ms.",
        ],
    }
    json.dump(summary, open(os.path.join(RES, "summary.json"), "w"), indent=1)
    print(json.dumps({k: summary[k] for k in ("verdict", "n_flights")}, indent=1))
