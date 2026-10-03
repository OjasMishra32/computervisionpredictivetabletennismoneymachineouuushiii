"""Associate per-frame detector blobs into one ball track per video (causal, online).

For every frame we keep up to K blobs from detect.py. The tracker is a constant-velocity gate:
the blob closest to the predicted position (last position + last velocity * dt) is accepted if it
lies within a gate radius; otherwise the strongest blob is accepted only if its heat peak is high
(a re-acquisition, e.g. after an occlusion). Only past frames are used, so the track is causal
(apart from the detector's own 2-frame look-ahead, which early_call.py accounts for).

Output: WORK/tracks/<video>_tracks.csv  (frame, x, y, peak, score) for every processed frame;
x, y are NaN where no ball was accepted.
Usage: python trajectories.py --model wasb [--videos game_1 ...]
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd

from common import ALL, WORK

MIN_PEAK = 0.3      # blob must reach this heat to be considered at all (chosen on game_1)
REACQ_PEAK = 0.6    # a blob outside the gate is accepted only if this strong
GATE0 = 60.0        # px, gate radius for one frame step (+ GATE_V per frame of gap)
GATE_V = 60.0
MAX_GAP = 8         # frames without a ball after which the motion model is reset


def load_det(video, model):
    fs = sorted(glob.glob(os.path.join(WORK, "det", f"{video}_*_{model}.npz")))
    fr, ca = [], []
    for f in fs:
        d = np.load(f)
        fr.append(d["frame"])
        ca.append(d["cand"])
    fr = np.concatenate(fr)
    ca = np.concatenate(ca)
    o = np.argsort(fr, kind="stable")
    fr, ca = fr[o], ca[o]
    keep = np.r_[True, fr[1:] != fr[:-1]]
    return fr[keep], ca[keep]


def track(frames, cands):
    out = np.full((len(frames), 4), np.nan)
    last_f = last_p = last_v = None
    for i, (f, c) in enumerate(zip(frames, cands)):
        ok = np.isfinite(c[:, 0]) & (c[:, 3] >= MIN_PEAK)
        if not ok.any():
            continue
        c = c[ok]
        gap = None if last_f is None else f - last_f
        if gap is None or gap > MAX_GAP:
            j = int(np.argmax(c[:, 2]))  # strongest blob starts a new track
            last_v = None
        else:
            pred = last_p + (last_v * gap if last_v is not None else 0.0)
            d = np.hypot(c[:, 0] - pred[0], c[:, 1] - pred[1])
            gate = GATE0 + GATE_V * gap
            if (d <= gate).any():
                j = int(np.argmin(np.where(d <= gate, d, np.inf)))
            elif c[:, 3].max() >= REACQ_PEAK:
                j = int(np.argmax(c[:, 2]))
                last_v = None
                gap = None
            else:
                continue
        p = c[j, :2].astype(float)
        if gap is not None and gap <= MAX_GAP:
            last_v = (p - last_p) / gap
        last_f, last_p = f, p
        out[i] = (p[0], p[1], c[j, 3], c[j, 2])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="wasb")
    ap.add_argument("--videos", nargs="+", default=ALL)
    a = ap.parse_args()
    os.makedirs(os.path.join(WORK, "tracks"), exist_ok=True)
    for v in a.videos:
        fr, ca = load_det(v, a.model)
        t = track(fr, ca)
        df = pd.DataFrame({"frame": fr, "x": t[:, 0], "y": t[:, 1], "peak": t[:, 2], "score": t[:, 3]})
        df.to_csv(os.path.join(WORK, "tracks", f"{v}_tracks.csv"), index=False, float_format="%.2f")
        print(v, len(df), "frames,", int(np.isfinite(t[:, 0]).sum()), "with ball")
