"""Run the same pretrained ball (TrackNet) and court-keypoint detectors as detect.py on one video file.

detect.py works on the TrackNet dataset's 1280x720 JPEG folders. This runs the same functions
(`run_ball`, `run_court`, unchanged) on every frame of an .mp4. Each frame is first resized to
1280x720, the resolution the detectors and their post-processing were built for. The ball
post-processing scales heatmap coordinates by 2 from 640x360 to 1280x720, and the court refinement
crops 40 px windows at that scale. Results are saved in 1280x720 pixels, together with
`work_size` and `src_size` so callers can rescale.

Output .npz: ball_xy (N,2) and court_kps (N,14,2), float, NaN = no detection, 1280x720 px;
cand_frame (M,) and cand_xya (M,3): every blob (centroid x, y; area) of the heatmap the ball post-processing searches
(ball_xy keeps one per frame, see detect.heatmap_candidates); plus fps, src_size, work_size,
video_sha256, device and timings.

Usage (GPU node):
  python detect_video.py --video clip.mp4 --ext $ROOT/ext/TennisProject --weights $ROOT/weights \
      --out $ROOT/work/detect_video/clip.npz
"""
import argparse
import hashlib
import os
import sys
import time

import cv2
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detect import run_ball, run_court  # noqa: E402

WORK_W, WORK_H = 1280, 720


def read_video(path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames, src_size = [], None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        src_size = (f.shape[1], f.shape[0])
        if src_size != (WORK_W, WORK_H):
            f = cv2.resize(f, (WORK_W, WORK_H), interpolation=cv2.INTER_AREA)
        frames.append(f)
    cap.release()
    return frames, fps, src_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--ext", required=True, help="path to the TennisProject clone")
    ap.add_argument("--weights", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.path.insert(0, a.ext)
    from ball_detector import BallDetector
    from postprocess import refine_kps
    from tracknet import BallTrackerNet

    device = "cuda" if torch.cuda.is_available() else "cpu"
    gpu = torch.cuda.get_device_name(0) if device == "cuda" else ""
    print("device", device, gpu, flush=True)
    ball = BallDetector(os.path.join(a.weights, "tracknet_ball.pt"), device)
    court = BallTrackerNet(out_channels=15).to(device)
    court.load_state_dict(torch.load(os.path.join(a.weights, "court_kps.pt"), map_location=device))
    court.eval()

    t0 = time.time()
    frames, fps, src_size = read_video(a.video)
    t_read = time.time() - t0
    if device == "cuda":
        torch.cuda.synchronize()
    t1 = time.time()
    cands = {}
    bxy = run_ball(ball, frames, device, candidates=cands)
    if device == "cuda":
        torch.cuda.synchronize()
    t2 = time.time()
    kps = run_court(court, frames, device, refine_kps)
    t3 = time.time()
    sha = hashlib.sha256(open(a.video, "rb").read()).hexdigest()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    cf = np.concatenate([np.full(len(c), k) for k, c in sorted(cands.items())]).astype(np.int32)
    cxyr = np.concatenate([c for _, c in sorted(cands.items())])
    np.savez_compressed(a.out, ball_xy=bxy, court_kps=kps, cand_frame=cf, cand_xya=cxyr,
                        fps=fps, src_size=np.array(src_size),
                        work_size=np.array([WORK_W, WORK_H]), video_sha256=sha, device=f"{device} {gpu}".strip(),
                        seconds=np.array([t_read, t2 - t1, t3 - t2]),
                        torch_version=torch.__version__, cv2_version=cv2.__version__)
    print(f"{os.path.basename(a.video)}: {len(frames)} frames at {fps:g} fps, src {src_size}, "
          f"ball det {np.isfinite(bxy[:, 0]).mean():.3f}, court kps {np.isfinite(kps[..., 0]).mean():.3f}, "
          f"read {t_read:.1f}s ball {t2 - t1:.1f}s court {t3 - t2:.1f}s", flush=True)


if __name__ == "__main__":
    main()
