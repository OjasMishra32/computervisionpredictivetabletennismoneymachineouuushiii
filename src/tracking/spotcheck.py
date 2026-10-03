"""Visual spot check of the inferred MISS labels (training videos only).

For a fixed random sample of MISS flights (and a few BOUNCE flights for contrast) we grab the
full-resolution frame 4 frames after T_ref, crop the half of the table the ball was heading to,
and overlay the tracked trajectory from t0 to T_ref + 15 frames.
Output: results/tracking/miss_spotcheck.png
"""
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


if __name__ == "__main__":
    fl = pd.read_csv(os.path.join(WORK, "flights.csv"))
    fl = fl[fl.split == "train"]
    rng = np.random.default_rng(0)
    miss = fl[fl.label == "MISS"]
    pick = list(rng.choice(miss.index, size=min(9, len(miss)), replace=False))
    pick += list(rng.choice(fl[fl.label == "BOUNCE"].index, size=3, replace=False))
    geo = geometry_all()
    fig, axes = plt.subplots(4, 3, figsize=(15, 12))
    for ax, i in zip(axes.ravel(), pick):
        r = fl.loc[i]
        g = geo[r.video]
        t = pd.read_csv(os.path.join(WORK, "tracks", f"{r.video}_tracks.csv")).set_index("frame")
        img = grab_full(r.video, int(r.t_ref) + 4)
        tr = t.loc[r.t0:r.t_ref + 15]
        x0 = int(g["x_net"] - 200) if r.dir > 0 else int(g["x_net"] - 760)
        x0 = int(np.clip(x0, 0, 1920 - 960))
        y0 = int(np.clip(g["far_line"][1] - 330, 0, 1080 - 540))
        ax.imshow(img[y0:y0 + 540, x0:x0 + 960], extent=(x0, x0 + 960, y0 + 540, y0))
        pre, post = tr.loc[:r.t_ref], tr.loc[r.t_ref + 1:]
        col = "#ff4d6d" if r.label == "MISS" else "#4cc9f0"
        ax.plot(pre.x, pre.y, ".", ms=3, color=col)
        ax.plot(post.x, post.y, "x", ms=3, color="w")
        cx = np.r_[g["corners"][:, 0], g["corners"][0, 0]]
        cy = np.r_[g["corners"][:, 1], g["corners"][0, 1]]
        ax.plot(cx, cy, color="y", lw=0.6)
        ax.set_xlim(x0, x0 + 960)
        ax.set_ylim(y0 + 540, y0)
        mt = f"/{r.miss_type}" if isinstance(r.miss_type, str) else ""
        ax.set_title(f"{r.video} net@{r.f_net} {r.label}{mt}  T_ref={r.t_ref}", fontsize=9)
        ax.axis("off")
    fig.suptitle("Spot check (train): coloured = track t0..T_ref, white x = after T_ref, "
                 "frame shown = T_ref + 4", fontsize=11)
    fig.tight_layout()
    os.makedirs(RES, exist_ok=True)
    fig.savefig(os.path.join(RES, "miss_spotcheck.png"), dpi=70)
    print("saved", os.path.join(RES, "miss_spotcheck.png"))
