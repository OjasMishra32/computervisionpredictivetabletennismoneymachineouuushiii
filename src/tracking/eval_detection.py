"""Detection accuracy against the OpenTTGames ball labels.

For each labelled frame we compare (a) the raw top-scoring detector blob and (b) the tracked
position after trajectory association (if a tracks file is given).
  recall    = labelled-visible frames with a prediction / labelled-visible frames
  precision = predictions within 10 px of the label / all predictions on labelled frames
              (a prediction on a frame labelled 'ball absent' counts as a false positive)
  within5/within10 = fraction of labelled-visible frames whose prediction is within 5 / 10 px
  rmse / median error over visible frames with a prediction (errors > 50 px excluded from RMSE)
Usage: python eval_detection.py --videos game_1 ... [--model blurball] [--shift 0] [--out csv]
       (reads WORK/det/<video>_<chunk>_<model>.npz and WORK/tracks/<video>_tracks.csv)
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd

from common import TEST, WORK, load_ball


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
    ap.add_argument("--videos", nargs="+", required=True)
    ap.add_argument("--model", default="blurball")
    ap.add_argument("--min-peak", type=float, default=0.3)
    ap.add_argument("--shift", type=int, default=0, help="label frame offset check")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = []
    for v in a.videos:
        gt = {f + a.shift: p for f, p in load_ball(v).items()}
        split = "test" if v in TEST else "train"
        pred = {}
        for p in sorted(glob.glob(os.path.join(WORK, "det", f"{v}_*_{a.model}.npz"))):
            pred.update(det_top1(p, a.min_peak))
        if pred:
            rows.append({"video": v, "split": split, "source": f"{a.model}_top1", **metrics(gt, pred)})
        q = os.path.join(WORK, "tracks", f"{v}_tracks.csv")
        if os.path.exists(q):
            rows.append({"video": v, "split": split, "source": "tracked", **metrics(gt, tracks_pred(q))})
    df = pd.DataFrame(rows)
    # pooled rows per split and source (frame-weighted)
    pooled = []
    for (sp, src), g in df.groupby(["split", "source"]):
        nv, na = g.n_visible.sum(), g.n_absent.sum()
        w = g.n_visible / nv
        rec = (g.recall * w).sum()
        pooled.append({"video": "ALL", "split": sp, "source": src, "n_visible": nv, "n_absent": na,
                       "recall": rec,
                       "precision@10px": np.nan, "within5": (g.within5 * w).sum(),
                       "within10": (g.within10 * w).sum(),
                       "median_err_px": np.nan, "rmse_px(<50)": np.nan,
                       "fp_rate_absent": (g.fp_rate_absent * g.n_absent).sum() / max(na, 1)})
        # pooled precision: predictions within 10 px / all predictions
        npred_vis = (g.recall * g.n_visible).sum()
        npred_abs = (g.fp_rate_absent * g.n_absent).sum()
        tp = (g.within10 * g.n_visible).sum()
        pooled[-1]["precision@10px"] = tp / max(npred_vis + npred_abs, 1)
    df = pd.concat([df, pd.DataFrame(pooled)], ignore_index=True)
    pd.set_option("display.width", 250)
    print(df.round(4).to_string(index=False))
    if a.out:
        df.to_csv(a.out, index=False, float_format="%.4f")
