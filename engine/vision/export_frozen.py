"""Export the frozen H3 early-call classifier for the streaming engine (run on HiPerGator).

Nothing is retrained or retuned. Like src/tracking/render_demo.py:frozen_scores, this rebuilds the
model that `early_call.py --final` evaluated (HGB, random_state=0, fitted on the game_1..5 flights
with the same features, sample weights and gate, taus read from early_call_final.json) and ASSERTS that it
reproduces results/tracking/test_flights.csv (P(miss) at -50 ms and the online first-call leads) before
writing anything. Output: models/vision/frozen_call_model.pkl with
  model_pickle   the fitted HGB (pickled separately so a different local sklearn can fall back)
  train_X/y/w    the frozen training matrix (fallback refit if the pickle does not load locally)
  check_X/p      test decision samples and their raw scores (to verify any refit to 1e-6)
  feats, model_name, gate_h_s, tau_online, tau_snapshot, persist, lag, fps
  geometry       the table_geometry.json cache the evaluation used (all 12 videos)
  test_scores    per (video, f_net, t, k) gated score of every test decision frame (offline reference)
  test_tracks    accepted track points of the test videos (offline reference for the streaming tracker)
  test_flights   results/tracking/test_flights.csv rows

Usage (HPG, venv_track):  python engine/vision/export_frozen.py
"""
from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src", "tracking"))

import early_call as E  # noqa: E402
from common import WORK, geometry_all  # noqa: E402

RES = os.environ.get("TRACK_RESULTS", os.path.join(REPO, "results", "tracking"))
OUT = os.path.join(REPO, "models", "vision", "frozen_call_model.pkl")


def main():
    import sklearn
    fin = json.load(open(os.path.join(WORK, "early_call_final.json")))
    E.GATE_H = fin["gate_h_s"]
    fl = pd.read_csv(os.path.join(WORK, "flights.csv"))
    tr = fl[fl.split == "train"].reset_index(drop=True)
    te = fl[fl.split == "test"].reset_index(drop=True)
    geo = geometry_all()
    tracks = E.load_tracks(sorted(fl.video.unique()))
    S_tr, _ = E.build_samples(tr, tracks, geo)
    S_te, _ = E.build_samples(te, tracks, geo)
    s_te, model = E.fit_predict(fin["model"], S_tr, S_te)

    # ---- reproduce the frozen test evaluation exactly (as render_demo.frozen_scores does)
    te_o = pd.read_csv(os.path.join(RES, "test_flights.csv")).set_index(["video", "f_net"])
    k50 = E.k_of(50)
    _, lead = E.per_flight_calls(S_te, s_te, te, fin["tau_online"], "online")
    worst_p, worst_lead, n_cmp = 0.0, 0.0, 0
    for fid, r in te.iterrows():
        o = te_o.loc[(r.video, r.f_net)]
        sel = (S_te.fid == fid).values & (S_te.k == k50).values
        if sel.any() and np.isfinite(o.p_miss_at_50ms):
            worst_p = max(worst_p, abs(float(s_te[sel][0]) - o.p_miss_at_50ms))
            n_cmp += 1
        a, b = lead.get(fid, np.nan), o.first_call_lead_ms
        assert (np.isnan(a) and np.isnan(b)) or abs(a - b) < 1e-6, (r.video, r.f_net, a, b)
        if np.isfinite(a):
            worst_lead = max(worst_lead, abs(a - b))
    assert worst_p < 1e-9, worst_p
    print(f"reproduced test_flights.csv: {n_cmp} P(miss)@50ms max |diff| {worst_p:.1e}, online leads exact")

    X = E.feats_of(fin["model"])
    sw = 1.0 / S_tr.groupby("fid")["fid"].transform("size").values
    raw_te = model.predict_proba(S_te[X].values)[:, 1]
    ts = S_te[["fid", "video", "t", "k", "tau_end", "tau_net"]].copy()
    ts["f_net"] = te.f_net.values[ts.fid.values]
    ts["score"] = s_te
    test_videos = sorted(te.video.unique())
    frozen = dict(
        model_pickle=pickle.dumps(model), model_name=fin["model"], feats=list(X),
        gate_h_s=float(fin["gate_h_s"]), tau_online=float(fin["tau_online"]),
        tau_snapshot=float(fin["tau_snapshot"]), persist=E.PERSIST, lag=E.LAG, fps=E.FPS,
        sklearn=sklearn.__version__, numpy=np.__version__,
        train_X=S_tr[X].values.astype(np.float64), train_y=S_tr.y.values.astype(np.int64), train_w=sw,
        check_X=S_te[X].values.astype(np.float64), check_p=raw_te,
        geometry={v: {k: (np.asarray(x).tolist() if isinstance(x, (np.ndarray, tuple)) else float(x))
                      for k, x in g.items()} for v, g in geo.items()},
        # plain numpy / python containers only (pandas pickles do not travel across versions)
        test_scores={c: ts[c].to_numpy() for c in ts.columns},
        test_tracks={v: {int(f): (float(x), float(y)) for f, (x, y) in tracks[v].items()} for v in test_videos},
        test_flights=pd.read_csv(os.path.join(RES, "test_flights.csv")).to_dict("list"),
        provenance=dict(early_call_final=fin, n_train_samples=int(len(S_tr)), n_test_samples=int(len(S_te)),
                        reproduced_p50_max_abs_diff=worst_p, reproduced_online_leads="exact"),
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as fh:
        pickle.dump(frozen, fh, protocol=4)
    print("wrote", OUT, f"{os.path.getsize(OUT) / 1e6:.1f} MB", "sklearn", sklearn.__version__)


if __name__ == "__main__":
    main()
