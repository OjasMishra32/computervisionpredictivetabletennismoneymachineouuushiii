"""Per-frame ball detection on OpenTTGames videos with a pretrained BlurBall / WASB detector.

We do not train our own detector. The model code and weights come from
BlurBall (Gossard et al., CVPRW 2026, MIT licence, https://github.com/cogsys-tuebingen/blurball),
which builds on WASB-SBDT (Tarashima et al., BMVC 2023, https://github.com/nttcom/WASB-SBDT).
This script only (1) streams frames from the 120 fps video with PyAV, (2) runs the 3-in/3-out
HRNet heatmap model, (3) averages the overlapping heatmaps (step=1) and (4) extracts up to K blobs
per frame (connected components above a threshold, heat-weighted centroid, like the BlurBall
post-processor). Association into trajectories happens later (trajectories.py).

Output: an .npz with, for every processed frame index, up to K candidates (x, y, score, peak, area)
in full-resolution 1920x1080 pixel coordinates.

Usage:
  python detect.py --video game_1.mp4 --out det/game_1 --start 0 --end 20000 --fp16
  python detect.py --video game_1.mp4 --out det/game_1 --ranges ranges.txt --fp16  # "start end" per line
"""
import argparse
import os
import sys
import time

import av
import cv2
import numpy as np
import torch

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
INP_W, INP_H = 512, 288
FULL_W, FULL_H = 1920, 1080
K = 3


def load_model(blurball_root, weights, model_name):
    sys.path.insert(0, os.path.join(blurball_root, "src"))
    from omegaconf import OmegaConf
    from models import build_model  # BlurBall / WASB model zoo

    mcfg = OmegaConf.load(os.path.join(blurball_root, "src/configs/model", f"{model_name}.yaml"))
    model = build_model({"model": mcfg})
    ckpt = torch.load(weights, map_location="cpu", weights_only=False)
    sd = ckpt.get("model_state_dict", ckpt)
    sd = {k.replace("module.", "", 1) if k.startswith("module.") else k: v for k, v in sd.items()}
    model.load_state_dict(sd)
    return model.eval().cuda()


def frame_iter(path, ranges, threads=8):
    """Yield (frame_index, rgb uint8 [INP_H, INP_W, 3]) for frames inside the given [s, e) ranges."""
    container = av.open(path)
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"
    stream.codec_context.thread_count = threads
    fps = float(stream.average_rate)
    tb = float(stream.time_base)
    for s, e in ranges:
        # seek to the keyframe at or before s, then decode forward
        container.seek(int(max(s - 2, 0) / fps / tb), stream=stream, backward=True, any_frame=False)
        for frame in container.decode(stream):
            idx = int(round(frame.pts * tb * fps))
            if idx < s:
                continue
            if idx >= e:
                break
            img = frame.to_ndarray(width=INP_W, height=INP_H, format="rgb24",
                                   interpolation="AREA")
            yield idx, img
    container.close()


def blobs(hm, thr):
    """Connected components of hm > thr; return up to K (x, y, score, peak, area) in input pixels."""
    if hm.max() <= thr:
        return []
    n, lab, stats, _ = cv2.connectedComponentsWithStats((hm > thr).astype(np.uint8), connectivity=8)
    out = []
    for m in range(1, n):
        x0, y0, w, h, area = stats[m]
        sub = hm[y0:y0 + h, x0:x0 + w] * (lab[y0:y0 + h, x0:x0 + w] == m)
        tot = sub.sum()
        ys, xs = np.mgrid[y0:y0 + h, x0:x0 + w]
        out.append(((xs * sub).sum() / tot, (ys * sub).sum() / tot, tot, sub.max(), area))
    out.sort(key=lambda r: -r[2])
    return out[:K]


def to_tensor(img):
    x = (img.astype(np.float32) / 255.0 - MEAN) / STD
    return torch.from_numpy(x).permute(2, 0, 1)  # [3, H, W]


@torch.no_grad()
def run(args):
    specs = [m.split("=", 1) for m in args.models.split(",")]
    models = [(name, load_model(args.blurball_root, w, name)) for name, w in specs]
    if args.ranges:
        ranges = [tuple(map(int, l.split()[:2])) for l in open(args.ranges) if l.strip()]
    else:
        ranges = [(args.start, args.end)]
    merged = []
    for s, e in sorted(ranges):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    ranges = merged
    sx, sy = FULL_W / INP_W, FULL_H / INP_H
    out_idx = []
    out_cand = {name: [] for name, _ in models}
    t0 = time.time()
    n = 0

    M = len(models)

    def infer(frames, starts):
        """-> [M, B, 3, H, W] sigmoid heatmaps, one per model"""
        inp = torch.stack([torch.cat(frames[i:i + 3], 0) for i in starts]).cuda(non_blocking=True)
        outs = []
        for _, model in models:
            with torch.autocast("cuda", dtype=torch.float16, enabled=args.fp16):
                pred = model(inp)
            pred = pred[0] if isinstance(pred, dict) else pred
            outs.append(torch.sigmoid(pred.float()).cpu().numpy())
        return np.stack(outs)

    def emit(idx, acc, c):
        out_idx.append(idx)
        for m, (name, _) in enumerate(models):
            hm = acc[m] / max(c, 1)
            cands = np.full((K, 5), np.nan, np.float32)
            for k, (bx, by, sc, pk, ar) in enumerate(blobs(hm, args.thr)):
                # pixel-centre aware mapping from 512x288 back to 1920x1080
                cands[k] = ((bx + 0.5) * sx - 0.5, (by + 0.5) * sy - 0.5, sc, pk, ar)
            out_cand[name].append(cands)

    for (s, e) in ranges:
        # Stream one contiguous range. Window starts are 0, step, 2*step, ... (+ a tail window).
        # A frame is final once every window that can cover it has run; we keep 2 extra frames
        # in the buffer so that a tail window can always be formed at the end of the range.
        st = {"base": 0, "next": 0}
        buf_idx, buf_x, acc, cnt = [], [], [], []

        def finalize(upto):
            k = max(0, min(upto - st["base"], len(buf_x)))
            for q in range(k):
                emit(buf_idx[q], acc[q], cnt[q])
            del buf_idx[:k], buf_x[:k], acc[:k], cnt[:k]
            st["base"] += k

        def run_windows(final):
            while True:
                end_pos = st["base"] + len(buf_x)
                avail, w = [], st["next"]
                while w + 3 <= end_pos and len(avail) < args.batch:
                    avail.append(w)
                    w += args.step
                if not avail or (len(avail) < args.batch and not final):
                    break
                hm = infer(buf_x, [a - st["base"] for a in avail])
                for j, a in enumerate(avail):
                    for q in range(3):
                        acc[a - st["base"] + q] += hm[:, j, q]
                        cnt[a - st["base"] + q] += 1
                st["next"] = w
                finalize(min(st["next"], end_pos - 2))
            if final:
                end_pos = st["base"] + len(buf_x)
                if len(buf_x) >= 3 and cnt[-1] == 0:
                    hm = infer(buf_x, [len(buf_x) - 3])
                    for q in range(3):
                        if cnt[len(buf_x) - 3 + q] == 0:
                            acc[len(buf_x) - 3 + q] += hm[:, 0, q]
                            cnt[len(buf_x) - 3 + q] += 1
                finalize(end_pos)

        pos, last = 0, None
        for idx, img in frame_iter(args.video, [(s, e)], threads=args.threads):
            if last is not None and idx != last + 1:
                print(f"warning: non-contiguous frames {last} -> {idx}", flush=True)
            last = idx
            buf_idx.append(idx)
            buf_x.append(to_tensor(img))
            acc.append(np.zeros((M, INP_H, INP_W), np.float32))
            cnt.append(0)
            pos += 1
            if len(buf_x) >= args.batch * args.step + 4:
                run_windows(final=False)
        run_windows(final=True)
        n += pos
        print(f"range {s}-{e}: {pos} frames, total {n}, {n / (time.time() - t0):.1f} fps", flush=True)
    order = np.argsort(out_idx, kind="stable")
    for name, w in specs:
        path = f"{args.out}_{name}.npz"
        np.savez_compressed(path, frame=np.array(out_idx, np.int32)[order],
                            cand=np.array(out_cand[name], np.float32).reshape(-1, K, 5)[order],
                            meta=np.array([name, w, str(args.step), str(args.thr)]))
        print("saved", path, len(out_idx), "frames in", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--out", required=True, help="output prefix; writes <out>_<model>.npz")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=10 ** 9)
    p.add_argument("--ranges", default=None)
    p.add_argument("--blurball_root", default="/blue/ai-workshop/ojasvamishra/courtside/ext/blurball")
    W = "/blue/ai-workshop/ojasvamishra/courtside/ext/blurball/weights"
    p.add_argument("--models", default=f"wasb={W}/wasb_midpoint_best,blurball={W}/blurball_best",
                   help="comma list of <config name in configs/model>=<weights path>")
    p.add_argument("--step", type=int, default=1)
    p.add_argument("--thr", type=float, default=0.3)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--fp16", action="store_true")
    run(p.parse_args())
