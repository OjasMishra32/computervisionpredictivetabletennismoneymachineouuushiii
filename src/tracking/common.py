"""Shared paths, markup loading and table geometry for the OpenTTGames tracking analysis (H3)."""
import glob
import json
import os

import numpy as np

FPS = 120.0
TRAIN = [f"game_{i}" for i in range(1, 6)]
TEST = [f"test_{i}" for i in range(1, 8)]
ALL = TRAIN + TEST

# HiPerGator layout (override with COURTSIDE_ROOT / OTTG_ROOT env vars when running elsewhere)
ROOT = os.environ.get("COURTSIDE_ROOT", "/blue/ai-workshop/ojasvamishra/courtside")
OTTG = os.environ.get("OTTG_ROOT", os.path.join(ROOT, "openttgames"))
MARKUP = os.path.join(OTTG, "markup")
WORK = os.environ.get("TRACK_WORK", os.path.join(ROOT, "work", "tracking"))


def load_events(video):
    e = json.load(open(os.path.join(MARKUP, video, "events_markup.json")))
    return sorted((int(k), v) for k, v in e.items())


def load_ball(video):
    """dict frame -> (x, y) or None for frames labelled as 'ball absent' (-1, -1)."""
    b = json.load(open(os.path.join(MARKUP, video, "ball_markup.json")))
    out = {}
    for k, v in b.items():
        out[int(k)] = None if (v["x"] < 0 or v["y"] < 0) else (float(v["x"]), float(v["y"]))
    return out


def table_mask(video):
    """Table mask pooled over the segmentation masks of the video (fixed camera).

    Masks are 320x128 RGB with channel-wise encoding: R = table, G = humans, B = scoreboard
    (verified visually). Returned at mask resolution, plus the scale to 1920x1080."""
    fs = sorted(glob.glob(os.path.join(MARKUP, video, "segmentation_masks", "*.png")))
    import cv2
    stack = []
    for f in fs[:: max(1, len(fs) // 300)]:
        m = cv2.imread(f)[..., ::-1]  # -> RGB
        stack.append(m[..., 0] > 127)
    # a pixel is table if labelled table in >= 25% of masks (players occlude corners for long spells)
    t = np.mean(np.stack(stack), 0) >= 0.25
    return t, (1920 / t.shape[1], 1080 / t.shape[0])


def _intersect(p1, p2, p3, p4):
    """Intersection of line p1-p2 with line p3-p4."""
    A = np.array([[p2[0] - p1[0], p3[0] - p4[0]], [p2[1] - p1[1], p3[1] - p4[1]]])
    s = np.linalg.solve(A, np.array([p3[0] - p1[0], p3[1] - p1[1]]))
    return np.array(p1) + s[0] * (np.array(p2) - np.array(p1))


def table_geometry(video):
    """Table-top quadrilateral in 1920x1080 pixels from the pooled segmentation mask.

    Returns dict with corners (far-left, far-right, near-right, near-left), the end-line x at
    each end (mean of the far and near corner x), net x (midpoint), the far/near edge lines
    y = a*x + b, and the pixel length of the table (for a rough px -> metre scale: 2.74 m)."""
    import cv2
    t, (sx, sy) = table_mask(video)
    cnts, _ = cv2.findContours(t.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    c[:, 0] = (c[:, 0] + 0.5) * sx - 0.5
    c[:, 1] = (c[:, 1] + 0.5) * sy - 0.5
    # four corners of the trapezoid: extreme left/right points of the top and bottom bands
    y0, y1 = c[:, 1].min(), c[:, 1].max()
    band = 0.2 * (y1 - y0)
    top, bot = c[c[:, 1] <= y0 + band], c[c[:, 1] >= y1 - band]
    far_left, far_right = top[np.argmin(top[:, 0])], top[np.argmax(top[:, 0])]
    near_left, near_right = bot[np.argmin(bot[:, 0])], bot[np.argmax(bot[:, 0])]
    # A player standing at a corner for most of a clip can hide it in the masks. The near edge
    # overhangs the far edge by similar amounts on both sides (camera roughly level with the
    # net), so a hidden corner is restored from the opposite overhang.
    ov_l, ov_r = far_left[0] - near_left[0], near_right[0] - far_right[0]
    if ov_l < 0.5 * ov_r:
        near_left = np.array([far_left[0] - ov_r, near_left[1]])
    elif ov_r < 0.5 * ov_l:
        near_right = np.array([far_right[0] + ov_l, near_right[1]])
    def line(p, q):
        a = (q[1] - p[1]) / (q[0] - p[0])
        return a, p[1] - a * p[0]
    far = line(far_left, far_right)
    near = line(near_left, near_right)
    left_end = 0.5 * (far_left[0] + near_left[0])
    right_end = 0.5 * (far_right[0] + near_right[0])
    return {
        "corners": np.array([far_left, far_right, near_right, near_left]),
        "far_line": far, "near_line": near,
        "x_left": left_end, "x_right": right_end,
        "x_left_outer": min(far_left[0], near_left[0]), "x_right_outer": max(far_right[0], near_right[0]),
        "x_left_inner": max(far_left[0], near_left[0]), "x_right_inner": min(far_right[0], near_right[0]),
        # net x: midpoint of the two end lines (matches the annotated net-crossing x of the
        # training videos to ~20 px; the diagonal intersection was less stable)
        "x_net": 0.5 * (left_end + right_end),
        "px_per_m": (right_end - left_end) / 2.74,
    }


def rally_ranges(video, gap=600, pre=180, post=300):
    """Frame ranges covering every annotated rally: non-empty events closer than `gap` frames are
    merged; each cluster is padded by `pre` frames before and `post` after."""
    ev = [f for f, e in load_events(video) if e in ("bounce", "net")]
    out = []
    for f in ev:
        if out and f - out[-1][1] <= gap:
            out[-1][1] = f
        else:
            out.append([f, f])
    return [(max(0, s - pre), e + post) for s, e in out]


def geometry_all(cache=None):
    """Table geometry for all videos, cached as JSON (computed from masks on first use)."""
    cache = cache or os.path.join(WORK, "table_geometry.json")
    if os.path.exists(cache):
        g = json.load(open(cache))
    else:
        g = {}
        for v in ALL:
            d = table_geometry(v)
            g[v] = {k: (np.asarray(x).tolist() if isinstance(x, (np.ndarray, tuple)) else float(x))
                    for k, x in d.items()}
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump(g, open(cache, "w"), indent=1)
    for v in g:
        g[v]["corners"] = np.array(g[v]["corners"])
        g[v]["far_line"] = tuple(g[v]["far_line"])
        g[v]["near_line"] = tuple(g[v]["near_line"])
    return g
