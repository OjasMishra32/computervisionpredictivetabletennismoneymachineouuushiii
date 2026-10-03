"""Visual spot check of the inferred MISS labels.

  python spotcheck.py              # training videos only (done before the test evaluation)
  python spotcheck.py --audit-test # POST-HOC audit of the test flights the frozen model called MISS
                                   # at the 50 ms lead (results/tracking/test_called_audit.png)


For a fixed random sample of MISS flights (and a few BOUNCE flights for contrast) we grab the
full-resolution frame 4 frames after T_ref, crop the half of the table the ball was heading to,
and overlay the tracked trajectory from t0 to T_ref + 15 frames.
Output: results/tracking/miss_spotcheck.png
"""
import json
import os

import av
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import OTTG, WORK, geometry_all

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RES = os.environ.get("TRACK_RESULTS", os.path.join(REPO, "results", "tracking"))


def grab_full(video, idx):
    c = av.open(os.path.join(OTTG, f"{video}.mp4"))
    s = c.streams.video[0]
    fps, tb = float(s.average_rate), float(s.time_base)
    c.seek(int(max(idx - 2, 0) / fps / tb), stream=s, backward=True, any_frame=False)
    for fr in c.decode(s):
        if int(round(fr.pts * tb * fps)) >= idx:
            img = fr.to_ndarray(format="rgb24")
            c.close()
            return img
    c.close()


def panel(ax, r, geo, frame_off=4, post=40):
    g = geo[r.video]
    t = pd.read_csv(os.path.join(WORK, "tracks", f"{r.video}_tracks.csv")).set_index("frame")
    img = grab_full(r.video, int(r.t_ref) + frame_off)
    tr = t.loc[r.t0:r.t_ref + post]
    x0 = int(g["x_net"] - 200) if r.dir > 0 else int(g["x_net"] - 760)
    x0 = int(np.clip(x0, 0, 1920 - 960))
    y0 = int(np.clip(g["far_line"][1] - 330, 0, 1080 - 540))
    ax.imshow(img[y0:y0 + 540, x0:x0 + 960], extent=(x0, x0 + 960, y0 + 540, y0))
    pre, aft = tr.loc[:r.t_ref], tr.loc[r.t_ref + 1:]
    col = "#ff4d6d" if r.label == "MISS" else "#4cc9f0"
    ax.plot(pre.x, pre.y, ".", ms=3, color=col)
    ax.plot(aft.x, aft.y, "x", ms=3, color="w")
    cx = np.r_[g["corners"][:, 0], g["corners"][0, 0]]
    cy = np.r_[g["corners"][:, 1], g["corners"][0, 1]]
    ax.plot(cx, cy, color="y", lw=0.6)
    ax.set_xlim(x0, x0 + 960)
    ax.set_ylim(y0 + 540, y0)
    ax.axis("off")


if __name__ == "__main__":
    import sys
    geo = geometry_all()
    os.makedirs(RES, exist_ok=True)
    if "--audit-test" in sys.argv:
        from common import load_events
        te = pd.read_csv(os.path.join(RES, "test_flights.csv"))
        tau = json.load(open(os.path.join(WORK, "early_call_final.json")))["tau_snapshot"]
        called = te[te.p_miss_at_50ms >= tau]
        n = len(called)
        fig, axes = plt.subplots(int(np.ceil(n / 3)), 3, figsize=(15, 3.1 * int(np.ceil(n / 3))))
        for ax, r in zip(axes.ravel(), called.itertuples()):
            panel(ax, r, geo, frame_off=4, post=60)
            ev = [(k - r.f_net, e) for k, e in load_events(r.video) if r.f_net < k <= r.f_net + 120 and e != "empty_event"]
            ax.set_title(f"{r.video} net@{r.f_net} {r.label}/{r.miss_type} p={r.p_miss_at_50ms:.2f}  "
                         f"next labelled events (frames after net): {ev[:3]}", fontsize=7)
        for ax in axes.ravel()[n:]:
            ax.axis("off")
        fig.suptitle("POST-HOC audit: test flights called MISS at the 50 ms lead (coloured = track t0..T_ref, "
                     "white x = 60 frames after T_ref)", fontsize=10)
        fig.tight_layout()
        fig.savefig(os.path.join(RES, "test_called_audit.png"), dpi=70)
        print("saved test_called_audit.png")
        sys.exit(0)
    fl = pd.read_csv(os.path.join(WORK, "flights.csv"))
    fl = fl[fl.split == "train"]
    rng = np.random.default_rng(0)
    miss = fl[fl.label == "MISS"]
    pick = list(rng.choice(miss.index, size=min(9, len(miss)), replace=False))
    pick += list(rng.choice(fl[fl.label == "BOUNCE"].index, size=3, replace=False))
    fig, axes = plt.subplots(4, 3, figsize=(15, 12))
    for ax, i in zip(axes.ravel(), pick):
        r = fl.loc[i]
        panel(ax, r, geo, frame_off=4, post=15)
        mt = f"/{r.miss_type}" if isinstance(r.miss_type, str) else ""
        ax.set_title(f"{r.video} net@{r.f_net} {r.label}{mt}  T_ref={r.t_ref}", fontsize=9)
    fig.suptitle("Spot check (train): coloured = track t0..T_ref, white x = after T_ref, "
                 "frame shown = T_ref + 4", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(RES, "miss_spotcheck.png"), dpi=70)
    print("saved", os.path.join(RES, "miss_spotcheck.png"))
