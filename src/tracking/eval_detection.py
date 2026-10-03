"""Detection accuracy against the OpenTTGames ball labels.

For each labelled frame we compare (a) the raw top-scoring detector blob and (b) the tracked
position after trajectory association (if a tracks file is given).
  recall    = labelled-visible frames with a prediction / labelled-visible frames
  precision = predictions within 10 px of the label / all predictions on labelled frames
              (a prediction on a frame labelled 'ball absent' counts as a false positive)
  within5/within10 = fraction of labelled-visible frames whose prediction is within 5 / 10 px
  rmse / median error over visible frames with a prediction (errors > 50 px excluded from RMSE)
Usage: python eval_detection.py --det-dir DIR --videos game_1 ... [--tracks-dir DIR] [--shift 0]
"""
import argparse
import os

import numpy as np
import pandas as pd

from common import load_ball


def metrics(gt, pred):
    """gt: dict f -> (x,y) | None ; pred: dict f -> (x,y) | None, evaluated on frames in both."""
    vis = n_pred_vis = tp = fp_abs = n_abs = 0
    errs = []
    w5 = w10 = 0
    for f, g in gt.items():
        if f not in pred:
            continue
        p = pred[f]
        if g is None:
            n_abs += 1
            if p is not None:
                fp_abs += 1
            continue
        vis += 1
        if p is None:
            continue
        n_pred_vis += 1
        d = float(np.hypot(p[0] - g[0], p[1] - g[1]))
        errs.append(d)
        w5 += d <= 5
        w10 += d <= 10
        tp += d <= 10
    errs = np.array(errs)
    n_pred = n_pred_vis + fp_abs
    return {
        "n_visible": vis, "n_absent": n_abs,
        "recall": n_pred_vis / max(vis, 1),
        "precision@10px": tp / max(n_pred, 1),
        "within5": w5 / max(vis, 1), "within10": w10 / max(vis, 1),
        "median_err_px": float(np.median(errs)) if len(errs) else np.nan,
        "rmse_px(<50)": float(np.sqrt(np.mean(errs[errs < 50] ** 2))) if (errs < 50).any() else np.nan,
        "fp_rate_absent": fp_abs / max(n_abs, 1),
    }


def det_top1(path, min_peak=0.5):
    d = np.load(path)
    out = {}
    for f, c in zip(d["frame"], d["cand"]):
        ok = np.isfinite(c[:, 0]) & (c[:, 3] >= min_peak)
        out[int(f)] = tuple(c[np.argmax(np.where(ok, c[:, 2], -1))][:2]) if ok.any() else None
    return out


def tracks_pred(path):
    t = pd.read_csv(path)
    return {int(f): (None if not np.isfinite(x) else (x, y)) for f, x, y in zip(t.frame, t.x, t.y)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--det-dir", required=True)
    ap.add_argument("--tracks-dir", default=None)
    ap.add_argument("--videos", nargs="+", required=True)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--min-peak", type=float, default=0.5)
    ap.add_argument("--shift", type=int, default=0, help="label frame offset check")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = []
    for v in a.videos:
        gt = {f + a.shift: p for f, p in load_ball(v).items()}
        p = os.path.join(a.det_dir, f"{v}{a.suffix}.npz")
        if os.path.exists(p):
            rows.append({"video": v, "source": "detector_top1", **metrics(gt, det_top1(p, a.min_peak))})
        if a.tracks_dir:
            q = os.path.join(a.tracks_dir, f"{v}_tracks.csv")
            if os.path.exists(q):
                rows.append({"video": v, "source": "tracked", **metrics(gt, tracks_pred(q))})
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(df.round(3).to_string(index=False))
    if a.out:
        df.to_csv(a.out, index=False)
