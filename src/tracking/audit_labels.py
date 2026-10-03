"""POST-HOC label audit (written after the single test evaluation; see DEVIATIONS.md H3-D10).

The visual audit of the test flights the frozen model called MISS showed that some test flights
labelled MISS actually bounce on the table: the bounce is not annotated in the test markup, and
the rally continues. The MISS rule (no annotated far-side bounce within 0.5 s) cannot see such a
gap in the annotation. This script finds those cases from the TRACK and re-scores the FROZEN
model (same features, same HGB fitted on game_1..5, same gate and tau) on corrected labels. It
does not refit or re-tune anything.

A MISS flight is relabelled BOUNCE ("unannotated bounce") if the tracked ball, between the net
frame and T_ref + 6, shows a bounce signature on the far half of the table: a local maximum of
image y (>= 2 px descent before and ascent after, over +-2 frames) inside the table quadrilateral
grown by one ball radius (the track is the ball centre) + 5 px, beyond the net-crossing x in the
direction of travel. T_ref becomes that frame. (A first version used a 5 px margin and missed a
far-edge bounce in test_1 whose ball centre sat 8 px above the far edge; the margin was then set
to the ball radius + 5 px. Both versions are post-hoc.)
We also flag MISS flights whose rally visibly continues (the next annotated event comes within 80
frames of the net frame).

Outputs: results/tracking/label_audit.json, results/tracking/test_flights_audited.csv
"""
import json
import os

import numpy as np
import pandas as pd

import early_call as E
from common import WORK, geometry_all, load_events

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RES = os.environ.get("TRACK_RESULTS", os.path.join(REPO, "results", "tracking"))


def inside(p, quad, margin=5.0):
    """Point in convex quadrilateral (corners in order), with an outward margin in px."""
    sgn = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        sgn.append(cross / np.hypot(b[0] - a[0], b[1] - a[1]))
    sgn = np.array(sgn)
    return bool((sgn >= -margin).all() or (sgn <= margin).all())


def unannotated_bounce(r, trk, g):
    for b in range(r.f_net + 1, r.t_ref + 7):
        ys = [trk.get(t) for t in range(b - 2, b + 3)]
        if any(p is None for p in ys):
            continue
        y = [p[1] for p in ys]
        if not (y[2] == max(y) and y[2] - y[0] >= 2 and y[2] - y[4] >= 2):
            continue
        p = trk[b]
        # the detector gives the ball centre; the contact point is one ball radius (20 mm) lower,
        # so the table quadrilateral is grown by the radius in px plus 5 px of detection noise
        margin = 0.02 * g["px_per_m"] + 5.0
        if (p[0] - r.x_cross) * r.dir > 0 and inside(p, g["corners"], margin):
            return b
    return None


def audit(fl, tracks, geo):
    fl = fl.copy()
    fl["audit"] = ""
    for i, r in fl[fl.label == "MISS"].iterrows():
        b = unannotated_bounce(r, tracks[r.video], geo[r.video])
        ev = [k for k, e in load_events(r.video) if k > r.f_net and e != "empty_event"]
        cont = bool(ev) and ev[0] - r.f_net < 80
        if b is not None:
            fl.loc[i, ["label", "miss_type", "t_ref", "audit"]] = ["BOUNCE", np.nan, b, "unannotated_bounce"]
        elif cont:
            fl.loc[i, "audit"] = "rally_continues"
    return fl


if __name__ == "__main__":
    fin = json.load(open(os.path.join(WORK, "early_call_final.json")))
    E.GATE_H = fin["gate_h_s"]
    tau = fin["tau_snapshot"]
    fl = pd.read_csv(os.path.join(WORK, "flights.csv"))
    geo = geometry_all()
    tracks = E.load_tracks(sorted(fl.video.unique()))
    tr = fl[fl.split == "train"].reset_index(drop=True)
    te = fl[fl.split == "test"].reset_index(drop=True)
    tr_a, te_a = audit(tr, tracks, geo), audit(te, tracks, geo)
    # frozen model: identical fit to early_call.py --final (HGB, random_state=0, training games only,
    # ORIGINAL training labels)
    S_tr, _ = E.build_samples(tr, tracks, geo)
    k50 = E.k_of(50)
    out = {"tau_snapshot_frozen": tau, "gate_h_s": E.GATE_H}
    for name, df in (("test_original_labels", te), ("test_audited_relabelled", te_a),
                     ("test_audited_drop_rally_continues", te_a[te_a.audit != "rally_continues"].reset_index(drop=True))):
        S, _ = E.build_samples(df, tracks, geo)
        s, _ = E.fit_predict("hgb", S_tr, S)
        cur = E.curves(S, s, df, tau)["snapshot"][2]
        out[name] = {"n_bounce": int((df.label == "BOUNCE").sum()), "n_miss": int((df.label == "MISS").sum()),
                     "snapshot": E.lead_table(cur)}
        if name == "test_audited_relabelled":
            sel = (S.k == k50).values
            p50 = pd.Series(s[sel], index=S.fid[sel].values)
            te_a["p_miss_at_50ms"] = te_a.index.map(p50)
    out["n_relabelled"] = {"train": int((tr_a.audit == "unannotated_bounce").sum()),
                           "test": int((te_a.audit == "unannotated_bounce").sum())}
    out["n_rally_continues_unresolved"] = {"train": int((tr_a.audit == "rally_continues").sum()),
                                           "test": int((te_a.audit == "rally_continues").sum())}
    te_a.to_csv(os.path.join(RES, "test_flights_audited.csv"), index=False)
    json.dump(out, open(os.path.join(RES, "label_audit.json"), "w"), indent=1)
    for k in ("test_original_labels", "test_audited_relabelled", "test_audited_drop_rally_continues"):
        v = out[k]
        print(k, "bounce", v["n_bounce"], "miss", v["n_miss"],
              {l: (x["precision"], x["recall"], x["tp"], x["fp"]) for l, x in v["snapshot"].items()})
    print("relabelled", out["n_relabelled"], "rally continues (unresolved)", out["n_rally_continues_unresolved"])
