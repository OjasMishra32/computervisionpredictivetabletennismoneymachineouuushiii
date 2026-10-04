"""Run the pretrained yastrebksv detectors on every frame of the TrackNet tennis dataset.

  * ball: TrackNet (yastrebksv/TrackNet weights, model + post-processing taken from
    yastrebksv/TennisProject `ball_detector.BallDetector`). Causal: frame t uses frames t, t-1, t-2.
  * court: 14 court keypoints (yastrebksv/TennisCourtDetector weights; model, heatmap
    post-processing and `refine_kps` from TennisProject `court_detection_net.CourtDetectorNet`).
    We keep the raw (refined) keypoints and fit our own metric homography later
    (geometry.py), instead of the repo's 4-point best configuration.

Output: one .npz per clip in --out with
  ball_xy (N,2) float (NaN = no detection), court_kps (N,14,2) float (NaN = missing).

Usage (GPU node):
  python detect.py --data $ROOT/data/tracknet_unz/Dataset --ext $ROOT/ext/TennisProject \
      --weights $ROOT/weights --out $ROOT/work/detect --games 1 2 3
"""
import argparse
import glob
import os
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as F


def load_frames(clip_dir):
    files = sorted(glob.glob(os.path.join(clip_dir, "*.jpg")))
    return files, [cv2.imread(f) for f in files]


def heatmap_candidates(det, fmap, scale=2):
    """Every blob of the binary heatmap BallDetector.postprocess searches (same uint8 wrap and
    threshold), as (k,3) centroid x, y in the 2x (1280x720) frame and area in heatmap pixels.
    postprocess runs Hough circles on this map and keeps one circle per frame (the first within
    80 px of the previous pick), so with several balls in view it can lock onto a still one."""
    fm = (fmap.astype(np.int64) * 255).reshape((det.height, det.width)).astype(np.uint8)
    _, hm = cv2.threshold(fm, 127, 255, cv2.THRESH_BINARY)
    n, _, stats, cent = cv2.connectedComponentsWithStats(hm, connectivity=8)
    if n <= 1:
        return np.zeros((0, 3))
    return np.c_[cent[1:] * scale, stats[1:, cv2.CC_STAT_AREA]].astype(np.float64)


@torch.no_grad()
def run_ball(det, frames, device, bs=16, candidates=None):
    """Same input construction and post-processing as BallDetector.infer_model, batched.
    If `candidates` is a dict, candidates[k] gets every heatmap blob of frame k (heatmap_candidates)."""
    W, H = det.width, det.height
    small = [cv2.resize(f, (W, H)) for f in frames]
    n = len(frames)
    out_xy = np.full((n, 2), np.nan)
    maps = []
    idx = list(range(2, n))
    for s in range(0, len(idx), bs):
        chunk = idx[s:s + bs]
        inp = np.stack([np.concatenate((small[k], small[k - 1], small[k - 2]), axis=2) for k in chunk])
        inp = np.rollaxis(inp.astype(np.float32) / 255.0, 3, 1)
        out = det.model(torch.from_numpy(inp).to(device))
        maps.append(out.argmax(dim=1).cpu().numpy())
    maps = np.concatenate(maps) if maps else np.zeros((0, H, W))
    prev = [None, None]
    for j, k in enumerate(idx):
        if candidates is not None:
            candidates[k] = heatmap_candidates(det, maps[j])
        x, y = det.postprocess(maps[j].astype(np.int64), prev)  # int64 as in the repo (its *255 -> uint8 wrap is part of the tuned post-processing)
        prev = [x, y]
        if x is not None:
            out_xy[k] = (x, y)
    return out_xy


@torch.no_grad()
def run_court(model, frames, device, refine_kps, bs=16):
    """Heatmap -> keypoint exactly as CourtDetectorNet.infer_model, but keep raw points."""
    n = len(frames)
    kps = np.full((n, 14, 2), np.nan)
    for s in range(0, n, bs):
        imgs = frames[s:s + bs]
        inp = np.stack([cv2.resize(im, (640, 360)).astype(np.float32) / 255.0 for im in imgs])
        inp = torch.from_numpy(np.rollaxis(inp, 3, 1)).to(device)
        pred = torch.sigmoid(model(inp)).cpu().numpy()
        for j, im in enumerate(imgs):
            for kn in range(14):
                hm = (pred[j, kn] * 255).astype(np.uint8)
                _, hm = cv2.threshold(hm, 170, 255, cv2.THRESH_BINARY)
                c = cv2.HoughCircles(hm, cv2.HOUGH_GRADIENT, dp=1, minDist=20, param1=50, param2=2,
                                     minRadius=10, maxRadius=25)
                if c is None:
                    continue
                x, y = c[0][0][0] * 2, c[0][0][1] * 2
                if kn not in (8, 12, 9):
                    try:
                        x, y = refine_kps(im, int(y), int(x), crop_size=40)
                    except Exception:
                        pass
                kps[s + j, kn] = (x, y)
    return kps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--ext", required=True, help="path to the TennisProject clone")
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--games", type=int, nargs="+", default=list(range(1, 11)))
    a = ap.parse_args()
    sys.path.insert(0, a.ext)
    from ball_detector import BallDetector
    from postprocess import refine_kps
    from tracknet import BallTrackerNet

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print("device", device, flush=True)
    ball = BallDetector(os.path.join(a.weights, "tracknet_ball.pt"), device)
    court = BallTrackerNet(out_channels=15).to(device)
    court.load_state_dict(torch.load(os.path.join(a.weights, "court_kps.pt"), map_location=device))
    court.eval()
    os.makedirs(a.out, exist_ok=True)
    for g in a.games:
        for clip_dir in sorted(glob.glob(os.path.join(a.data, f"game{g}", "Clip*"))):
            name = f"game{g}_{os.path.basename(clip_dir)}"
            dst = os.path.join(a.out, name + ".npz")
            if os.path.exists(dst):
                continue
            t0 = time.time()
            files, frames = load_frames(clip_dir)
            bxy = run_ball(ball, frames, device)
            kps = run_court(court, frames, device, refine_kps)
            np.savez_compressed(dst, ball_xy=bxy, court_kps=kps,
                                files=np.array([os.path.basename(f) for f in files]))
            print(f"{name}: {len(frames)} frames, ball det {np.isfinite(bxy[:, 0]).mean():.2f}, "
                  f"court kps {np.isfinite(kps[..., 0]).mean():.2f}, {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
