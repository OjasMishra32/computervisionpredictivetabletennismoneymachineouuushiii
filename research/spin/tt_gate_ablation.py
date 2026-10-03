"""TRAIN-ONLY gate ablation (verifier issue 3, research/spin/TT_RUN.md): is the spin model's extra recall
from the spin/physics features or from re-choosing the horizon gate (spin: none; frozen: 0.10 s)?

Leave-one-game-out on game_1..5 with the cached physics features of the dev stage; every (feature set,
gate) pair gets its own thresholds from the same rule (early_call.choose_tau on these OOF scores), so
the precisions are optimistic in the same way for every row. Never reads a test flight; nothing here
changes frozen_spec.json or the test evaluation.

  python research/spin/tt_gate_ablation.py      (HiPerGator, env of hpg/spin_tt.sbatch)
-> $SPIN_RESULTS/train_gate_ablation.json
"""
import json
import os
import sys

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src", "spin"))
import tt_early_call as T  # noqa: E402

LEADS = ["25ms", "50ms", "100ms", "200ms"]


def main():
    fl = T.load_flights("train")
    geo = T.C.geometry_all()
    tracks = T.E.load_tracks(sorted(fl.video.unique()))
    F = T.physics_features(fl, "train", 1, ablation=True)          # cache hit (dev stage)
    S, _ = T.samples(fl, F, geo, tracks)
    out = {"note": "train game_1..5 only, leave-one-game-out; thresholds re-chosen per row on the same OOF "
                   "scores (optimistic, equally for every row)", "rows": []}
    for name in ("frozen", "spin", "nospin"):
        raw = T.logo_oof_raw(T.MODELS[name], S)
        for h in T.GATES:
            rep = T.evaluate(S, T.E.gated(raw, S, h), fl)[0]
            row = dict(features=name, gate_h_s=h, tau_snapshot=rep["tau_snapshot"], tau_online=rep["tau_online"],
                       first_call=rep["first_call"])
            for rule in ("snapshot", "online"):
                for L in LEADS:
                    r = rep[rule][L]
                    row[f"{rule}_{L}"] = dict(precision=r["precision"], recall=r["recall"], tp=r["tp"], fp=r["fp"])
            out["rows"].append(row)
            s50, o50 = row["snapshot_50ms"], row["online_50ms"]
            print(f"{name:7s} gate={h:<5} snap50 {s50['tp']}/{s50['tp'] + s50['fp']} p={s50['precision']} r={s50['recall']} | "
                  f"snap100 r={row['snapshot_100ms']['recall']} p={row['snapshot_100ms']['precision']} | "
                  f"snap200 r={row['snapshot_200ms']['recall']} | online50 {o50['tp']}/{o50['tp'] + o50['fp']} | "
                  f"first-call {rep['first_call']['n_miss_called']} median {rep['first_call']['median_lead_ms']} ms",
                  flush=True)
    json.dump(out, open(os.path.join(T.RES, "train_gate_ablation.json"), "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
