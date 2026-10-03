"""Streaming ball-tracking call engine for table tennis (paper only).

Reads any cv2.VideoCapture source (file path, RTSP/HTTP URL, webcam index), processes frames in arrival
order and emits a CallEvent the moment the frozen H3 classifier's online rule fires. Nothing here is
retrained or retuned; every stage reuses the offline pipeline in src/tracking/:

  stage        offline code (src/tracking)                    streaming here
  -----------  ---------------------------------------------  ------------------------------------------
  detector     detect.py: BlurBall, 3-in/3-out, step 1,       same model (ONNX export or PyTorch), same
               heatmaps of the 3 windows covering a frame     triplets; when frame n arrives the window
               averaged, blobs() thr 0.3, K = 3               (n-2, n-1, n) runs and frame n-2 is final
  tracker      trajectories.track: constant-velocity gate     same rules and constants, one frame at a time
  flight       flights.flight_start (track only, no labels)   called at the decision frame instead of the
                                                              labelled net frame; direction from the track
  features     early_call.Flight.features (LAG = 2)           the same function
  classifier   HGB fitted on game_1..5 (early_call --final),  the frozen model exported by export_frozen.py
               gate 0.10 s, tau_online, 3 consecutive frames  same gate / tau / persistence -> MISS call

Decision frame t uses ball positions up to t - 2 (detector look-ahead), so a call can be emitted as soon
as frame t has arrived and been processed; CallEvent.latency_ms = t_emit - t_frame(t).

What the offline evaluation never covered, and this engine must decide on its own:
  * which frames belong to a flight (offline: anchored on the labelled `net` event). Here a decision is
    made only while the causal track shows a flight that started on the hitter's side of the net
    (u(t0) < 0.5), has not passed the end line / dropped below the near edge, and has not been lost for
    >= flights.LOST frames. After a call, the next call needs a direction change (a new shot).
  * BOUNCE calls (offline: a snapshot at T_ref - 50 ms, T_ref from labels). Here: the first decision
    frame after the net where the horizon gate is open and the predicted table contact is <= 50 ms away;
    BOUNCE if P(miss) < tau_snapshot there.

Usage (repo root):
  python -m engine.vision.stream --source data/vision/test_2_copyts.mp4 --frame-offset 2000 --video test_2 --realtime
  python -m engine.vision.stream --source 0                         # webcam (needs --corners for a new camera)
  python -m engine.vision.stream --source rtsp://host/stream --corners "x,y;x,y;x,y;x,y"
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pickle
import queue
import sys
import threading
import time
import types
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from .events import CallEvent, assert_paper_only, now

REPO = Path(__file__).resolve().parents[2]
TRACKING_DIR = REPO / "src" / "tracking"
MODELS = REPO / "models" / "vision"
ONNX_PATH = MODELS / "blurball_best_b1.onnx"
FROZEN_PATH = MODELS / "frozen_call_model.pkl"
LIVE_PREFIXES = ("rtsp://", "rtsps://", "rtmp://", "udp://", "tcp://", "srt://")

_MODS = None


def tracking_modules():
    """Import the offline pipeline modules exactly as src/tracking uses them.

    detect.py imports PyAV (offline decoding only) at module level; the engine decodes with cv2, so a
    placeholder module is used for that import (PyAV and cv2 ship clashing libavdevice builds on macOS).
    Nothing that needs PyAV is called."""
    global _MODS
    if _MODS is not None:
        return _MODS
    if str(TRACKING_DIR) not in sys.path:
        sys.path.insert(0, str(TRACKING_DIR))
    stubs = []
    for name in ("av",) + (("torch",) if importlib.util.find_spec("torch") is None else ()):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
            stubs.append(name)
    try:
        import common  # noqa: F401
        import detect
        import early_call
        import flights
        import trajectories
    finally:
        for name in stubs:
            sys.modules.pop(name, None)
    _MODS = SimpleNamespace(C=common, D=detect, E=early_call, FL=flights, T=trajectories)
    return _MODS


# ----------------------------------------------------------------------------------- detector backends
ONNX_FP16_PATH = MODELS / "blurball_best_b1_fp16.onnx"
_CML = "CoreMLExecutionProvider"
PROVIDERS = {
    # name: (onnx file, providers)
    "cpu": (ONNX_PATH, ["CPUExecutionProvider"]),
    "coreml": (ONNX_PATH, [(_CML, {"ModelFormat": "MLProgram", "MLComputeUnits": "ALL"}), "CPUExecutionProvider"]),
    "coreml-gpu16": (ONNX_FP16_PATH, [(_CML, {"ModelFormat": "MLProgram", "MLComputeUnits": "CPUAndGPU"}),
                                      "CPUExecutionProvider"]),
    "coreml-ane16": (ONNX_FP16_PATH, [(_CML, {"ModelFormat": "MLProgram", "MLComputeUnits": "CPUAndNeuralEngine"}),
                                      "CPUExecutionProvider"]),
    "cuda": (ONNX_PATH, ["CUDAExecutionProvider", "CPUExecutionProvider"]),
    "cuda16": (ONNX_FP16_PATH, ["CUDAExecutionProvider", "CPUExecutionProvider"]),
}


class OnnxBackend:
    """BlurBall exported by export_onnx.py (static batch 1). fp16 variants run the fp16 graph (the offline
    detector also ran in fp16, torch autocast on CUDA)."""

    def __init__(self, provider="cpu", threads=4):
        import onnxruntime as ort
        path, prov = PROVIDERS[provider]
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(path), so, providers=prov)
        self.name = f"onnx-{provider}"
        self.inp = self.sess.get_inputs()[0].name

    def __call__(self, x):
        return self.sess.run(None, {self.inp: x})[0]


class TorchBackend:
    """BlurBall in PyTorch (needs the BlurBall source tree). device: cuda (fp16 autocast, as detect.py) | mps | cpu."""

    def __init__(self, blurball_root, weights=MODELS / "blurball_best", device="cuda", fp16=True):
        import torch
        from .export_onnx import SigmoidHeatmap, build_torch_model
        self.torch = torch
        self.dev = torch.device(device)
        self.fp16 = fp16 and device == "cuda"
        self.net = SigmoidHeatmap(build_torch_model(blurball_root, str(weights))).to(self.dev)
        if device == "cuda":
            torch.backends.cudnn.benchmark = True
        self.name = f"torch-{device}{'-fp16' if self.fp16 else ''}"

    def __call__(self, x):
        torch = self.torch
        with torch.no_grad(), torch.autocast(self.dev.type, dtype=torch.float16, enabled=self.fp16):
            y = self.net(torch.from_numpy(x).to(self.dev, non_blocking=True))
        return y.float().cpu().numpy()


def make_backend(spec, blurball_root=None, threads=4):
    """One backend, or a comma-separated pool (e.g. 'onnx-coreml-gpu16,onnx-coreml-ane16'): windows are
    dispatched round-robin to the pool and their heatmaps are folded in back in frame order."""
    if "," in spec:
        return [make_backend(s.strip(), blurball_root, threads) for s in spec.split(",")]
    if spec.startswith("onnx-"):
        return OnnxBackend(spec[5:], threads)
    if spec.startswith("torch-"):
        dev = spec[6:]
        root = blurball_root or os.environ.get("BLURBALL_ROOT")
        if not root:
            raise SystemExit("torch backends need --blurball_root (or BLURBALL_ROOT)")
        return TorchBackend(root, device=dev.replace("-fp32", ""), fp16=not dev.endswith("-fp32"))
    raise SystemExit(f"unknown backend {spec}")


# ----------------------------------------------------------------------------------- preprocessing
def resize_rgb(bgr, D):
    """BGR frame (any size) -> uint8 RGB [288, 512, 3]. detect.py resizes with swscale 'area' while
    decoding; cv2 INTER_AREA is the equivalent filter."""
    import cv2
    return cv2.resize(bgr, (D.INP_W, D.INP_H), interpolation=cv2.INTER_AREA)[..., ::-1]


def normalize(rgb, D):
    """uint8 RGB [288, 512, 3] -> float32 [3, 288, 512], ImageNet-normalised (detect.to_tensor)."""
    x = (rgb.astype(np.float32) * (1.0 / 255.0) - D.MEAN) / D.STD
    return np.ascontiguousarray(x.transpose(2, 0, 1))


def preprocess(bgr, D):
    return normalize(resize_rgb(bgr, D), D)


# ----------------------------------------------------------------------------------- streaming detector
class StreamingDetector:
    """detect.py's step-1 sliding triplets, one frame at a time.

    Frame q is covered by the windows starting at q-2, q-1 and q. When frame n arrives the window
    (n-2, n-1, n) runs, and frame n-2 has then received every window that covers it: its averaged
    heatmap goes through detect.blobs. At a stream start a frame gets fewer windows, exactly as at the
    start of a range in detect.py; a gap in frame numbers ends the range (flush).

    With a pool of backends, window n runs while windows n-1, n-2 may still be in flight on other
    accelerators; results are folded in strictly in window order, so the output is identical to the
    sequential path, only later by up to len(pool) - 1 windows."""

    def __init__(self, backend, D, thr=0.3, full_size=(1920, 1080)):
        from concurrent.futures import ThreadPoolExecutor
        self.backends = backend if isinstance(backend, list) else [backend]
        self.name = "+".join(b.name for b in self.backends)
        self.D, self.thr = D, thr
        self.sx, self.sy = full_size[0] / D.INP_W, full_size[1] / D.INP_H
        self.buf = deque()       # [idx, x, acc, cnt] not yet covered by their own window
        self.pending = deque()   # (future or heatmap, window entries)
        self.pools = ([ThreadPoolExecutor(1) for _ in self.backends] if len(self.backends) > 1 else None)
        self.k = 0
        self.t_infer = 0.0       # time the caller spent in (or blocked on) inference
        self.t_post = 0.0

    def _emit(self, e):
        t = time.perf_counter()
        hm = e[2] / max(e[3], 1)
        cands = np.full((self.D.K, 5), np.nan, np.float32)
        for k, (bx, by, sc, pk, ar) in enumerate(self.D.blobs(hm, self.thr)):
            cands[k] = ((bx + 0.5) * self.sx - 0.5, (by + 0.5) * self.sy - 0.5, sc, pk, ar)
        self.t_post += time.perf_counter() - t
        return e[0], cands

    def _fold(self, block_until):
        """Fold finished windows in order; block while more than `block_until` are in flight."""
        out = []
        while self.pending:
            r, w = self.pending[0]
            if not isinstance(r, np.ndarray):
                if not r.done() and len(self.pending) <= block_until:
                    break
                t = time.perf_counter()
                r = r.result()
                self.t_infer += time.perf_counter() - t
            self.pending.popleft()
            for q in range(3):
                w[q][2] += r[q]
                w[q][3] += 1
            out.append(self._emit(w[0]))      # the window's first frame is now final
        return out

    def flush(self):
        out = self._fold(0)
        out += [self._emit(e) for e in self.buf]
        self.buf.clear()
        return out

    def push(self, idx, x):
        """-> list of (frame_index, cands [K, 5]) that became final with this frame."""
        out = []
        if self.buf and idx != self.buf[-1][0] + 1:
            out += self.flush()
        self.buf.append([idx, x, np.zeros((self.D.INP_H, self.D.INP_W), np.float32), 0])
        if len(self.buf) >= 3:
            w = [self.buf[-3], self.buf[-2], self.buf[-1]]
            inp = np.concatenate([e[1] for e in w], 0)[None]
            if self.pools is None:
                t = time.perf_counter()
                r = self.backends[0](inp)[0]
                self.t_infer += time.perf_counter() - t
            else:
                j = self.k % len(self.backends)
                r = self.pools[j].submit(lambda b=self.backends[j], v=inp: b(v)[0])
                self.k += 1
            self.pending.append((r, w))
            self.buf.popleft()
        out += self._fold(len(self.backends) - 1)
        return out


# ----------------------------------------------------------------------------------- online tracker
class OnlineTracker:
    """trajectories.track, one frame at a time (same constants, same decisions)."""

    def __init__(self, T, keep=1500):
        self.T = T
        self.last_f = self.last_p = self.last_v = None
        self.trk = {}          # frame -> (x, y), accepted ball positions (what early_call.load_tracks keeps)
        self.keep = keep

    def update(self, f, c):
        T = self.T
        if f % 256 == 0:
            for k in [k for k in self.trk if k < f - self.keep]:
                del self.trk[k]
        ok = np.isfinite(c[:, 0]) & (c[:, 3] >= T.MIN_PEAK)
        if not ok.any():
            return None
        c = c[ok]
        gap = None if self.last_f is None else f - self.last_f
        if gap is None or gap > T.MAX_GAP:
            j = int(np.argmax(c[:, 2]))
            self.last_v = None
        else:
            pred = self.last_p + (self.last_v * gap if self.last_v is not None else 0.0)
            d = np.hypot(c[:, 0] - pred[0], c[:, 1] - pred[1])
            gate = T.GATE0 + T.GATE_V * gap
            if (d <= gate).any():
                j = int(np.argmin(np.where(d <= gate, d, np.inf)))
            elif c[:, 3].max() >= T.REACQ_PEAK:
                j = int(np.argmax(c[:, 2]))
                self.last_v = None
                gap = None
            else:
                return None
        p = c[j, :2].astype(float)
        if gap is not None and gap <= T.MAX_GAP:
            self.last_v = (p - self.last_p) / gap
        self.last_f, self.last_p = f, p
        self.trk[f] = (float(p[0]), float(p[1]))
        return (p[0], p[1], c[j, 3], c[j, 2])


# ----------------------------------------------------------------------------------- frozen model / geometry
def load_frozen(path=FROZEN_PATH):
    """The frozen H3 classifier written by export_frozen.py (on HiPerGator, from the frozen training
    flights). Contains the fitted HGB, FEATS_ALL, gate_h_s, tau_online, tau_snapshot, PERSIST, LAG and the
    table geometry cache the evaluation used."""
    if not Path(path).exists():
        raise FileNotFoundError(
            f"{path} not found. It is produced on HiPerGator by `sbatch hpg/engine_vision.sbatch` "
            "(engine/vision/export_frozen.py refits nothing new: it rebuilds the frozen early_call --final "
            "model and asserts it reproduces results/tracking/test_flights.csv).")
    with open(path, "rb") as fh:
        fz = pickle.load(fh)
    import sklearn
    fz["model_source"] = "pickle"
    try:
        if fz.get("sklearn") != sklearn.__version__:
            raise ValueError(f"sklearn {fz.get('sklearn')} (HPG) != {sklearn.__version__} (local)")
        fz["model"] = pickle.loads(fz["model_pickle"])
    except Exception as e:  # different sklearn: refit the same estimator on the same matrix, then verify
        print(f"frozen pickle not used ({e}); refitting the identical HGB from the frozen matrix", flush=True)
        fz["model"] = _refit_from_matrix(fz)
        fz["model_source"] = "refit_from_frozen_matrix"
    got = fz["model"].predict_proba(fz["check_X"])[:, 1]
    fz["check_max_abs_err"] = float(np.abs(got - fz["check_p"]).max())
    return fz


def _refit_from_matrix(fz):
    """Same estimator (early_call.make_model), same rows, same sample weights, same random_state."""
    E = tracking_modules().E
    m = E.make_model(fz["model_name"])
    m.fit(fz["train_X"], fz["train_y"], sample_weight=fz["train_w"])
    return m


def geometry_from_corners(corners):
    """Table geometry from 4 image corners (far-left, far-right, near-right, near-left), computed as the
    tail of common.table_geometry does. For a new camera: click the 4 table-top corners once."""
    far_left, far_right, near_right, near_left = [np.asarray(p, float) for p in corners]

    def line(p, q):
        a = (q[1] - p[1]) / (q[0] - p[0])
        return a, p[1] - a * p[0]
    left_end = 0.5 * (far_left[0] + near_left[0])
    right_end = 0.5 * (far_right[0] + near_right[0])
    return {"corners": np.array([far_left, far_right, near_right, near_left]),
            "far_line": line(far_left, far_right), "near_line": line(near_left, near_right),
            "x_left": left_end, "x_right": right_end,
            "x_left_outer": min(far_left[0], near_left[0]), "x_right_outer": max(far_right[0], near_right[0]),
            "x_left_inner": max(far_left[0], near_left[0]), "x_right_inner": min(far_right[0], near_right[0]),
            "x_net": 0.5 * (left_end + right_end), "px_per_m": (right_end - left_end) / 2.74}


def load_geometry(video=None, frozen=None, corners=None, path=None):
    """-> (geometry dict, provenance string)."""
    if corners is not None:
        return geometry_from_corners(corners), "corners"
    if path:
        g = json.load(open(path))
        g = g[video] if video and video in g else g
        return _fix_geo(g), f"file:{path}"
    if frozen is not None and video and video in frozen.get("geometry", {}):
        return _fix_geo(frozen["geometry"][video]), "frozen (HPG table_geometry.json used by the evaluation)"
    if video:
        os.environ.setdefault("OTTG_ROOT", str(REPO / "data" / "openttgames"))
        C = tracking_modules().C
        C.MARKUP = os.path.join(os.environ["OTTG_ROOT"], "markup")
        return C.table_geometry(video), "local masks (approximate: data/openttgames has a 12-mask sample)"
    raise SystemExit("no table geometry: pass --video (OpenTTGames), --geometry or --corners")


def _fix_geo(g):
    g = dict(g)
    g["corners"] = np.asarray(g["corners"], float)
    g["far_line"], g["near_line"] = tuple(g["far_line"]), tuple(g["near_line"])
    return g


# ----------------------------------------------------------------------------------- call logic
class FrozenCaller:
    """Online flight segmentation + frozen early-call features / classifier / rule."""

    BOUNCE_LEAD_MS = 50.0     # the snapshot lead of the offline BOUNCE decision

    def __init__(self, frozen, geometry, fps=120.0, emit_enabled=True):
        M = tracking_modules()
        self.E, self.FL = M.E, M.FL
        self.g = geometry
        self.fps = fps
        self.model = frozen["model"]
        self.feats = list(frozen.get("feats", self.E.FEATS_ALL))
        self.tau_on = float(frozen["tau_online"])
        self.tau_snap = float(frozen["tau_snapshot"])
        self.gate_h = float(frozen["gate_h_s"])
        self.persist = int(frozen.get("persist", self.E.PERSIST))
        self.lag = int(frozen.get("lag", self.E.LAG))
        self.E.GATE_H = self.gate_h          # as render_demo.frozen_scores does
        try:   # one-row HGB predict: OpenMP thread start-up costs ~7 ms, a single thread ~0.8 ms
            from threadpoolctl import threadpool_limits
            self._tp = threadpool_limits(limits=1, user_api="openmp")
        except ImportError:
            self._tp = None
        self.emit_enabled = emit_enabled
        a_near, b_near = geometry["near_line"]
        self.a_near, self.b_near = a_near, b_near
        self.key = None
        self.run = 0
        self.last_t = None
        self.called = set()
        self.block_dir = None       # after a call: no new call until the direction changes
        self.trace = []             # (t, key, p_gated, gate_open) per decision frame
        self.t_feat = self.t_clf = 0.0
        self.n_dec = 0

    def _direction(self, trk, t_last):
        pts = [(f, trk[f]) for f in range(t_last - 8, t_last + 1) if f in trk]
        if len(pts) < 2:
            return None
        dx = pts[-1][1][0] - pts[0][1][0]
        return None if abs(dx) < 2.0 else (1.0 if dx > 0 else -1.0)

    def decide(self, t, trk):
        """Decision at frame t (positions <= t - LAG are final). -> list of (call, info) to emit."""
        E, FL = self.E, self.FL
        tl = t - self.lag
        last_seen = next((f for f in range(tl, tl - FL.LOST - 1, -1) if f in trk), None)
        if last_seen is None:              # ball lost for >= LOST frames: flight over
            self.block_dir = None
            self._break()
            return []
        d = self._direction(trk, last_seen)
        if d is None:
            self._break()
            return []
        if self.block_dir is not None and d != self.block_dir:
            self.block_dir = None
        t_f = time.perf_counter()
        t0 = FL.flight_start(tl + 1, d, trk) + 1
        if t0 > tl - (E.NMIN - 1):                         # too few frames since the flight start
            self.t_feat += time.perf_counter() - t_f
            self._break()
            return []
        F = E.Flight(SimpleNamespace(dir=d, t0=t0, t_ref=tl), trk, self.g)
        if len(F.fr) < E.NMIN or F.u[0] >= 0.5 or F.u[-1] >= 1.0:
            self.t_feat += time.perf_counter() - t_f
            self._break()
            return []
        x_l, y_l = trk[F.fr[-1]]
        if y_l > self.a_near * x_l + self.b_near + 10:     # dropped below the near table edge
            self.t_feat += time.perf_counter() - t_f
            self._break()
            return []
        f = F.features(t)
        self.t_feat += time.perf_counter() - t_f
        if f is None:
            self._break()
            return []
        t_c = time.perf_counter()
        X = np.array([[f[k] for k in self.feats]], dtype=float)
        p_raw = float(self.model.predict_proba(X)[0, 1])
        gate_open = min(f["tau_end"], f["tau_net"]) <= self.gate_h
        p = p_raw if gate_open else 0.0                   # early_call.gated
        self.t_clf += time.perf_counter() - t_c
        self.n_dec += 1
        key = (d, t0)
        if key != self.key or self.last_t is None or t != self.last_t + 1:
            self.run = 0
        self.key, self.last_t = key, t
        self.run = self.run + 1 if p >= self.tau_on else 0
        self.trace.append((t, d, t0, p, gate_open))
        out = []
        if key in self.called or self.block_dir == d:
            return out
        info = dict(p=p, p_raw=p_raw, d=d, t0=t0, gate_open=gate_open, run=self.run,
                    tau_net_ms=1000 * f["tau_net"], tau_end_ms=1000 * f["tau_end"],
                    tau_mid_ms=1000 * f["tau_mid"], u_now=f["u_now"], w_now=f["w_now"],
                    passed_net=f["passed_net"], xy=(x_l, y_l))
        if self.run >= self.persist:
            # predicted lead: time to the next line that resolves the point (net plane if still ahead,
            # otherwise the end line). For an out ball called before the net this is a lower bound.
            lead = 1000 * (f["tau_end"] if f["passed_net"] else min(f["tau_net"], f["tau_end"]))
            out.append(("MISS", lead, info))
        elif (f["passed_net"] and gate_open and not f["no_land"] and
              1000 * f["tau_mid"] <= self.BOUNCE_LEAD_MS and p < self.tau_snap):
            out.append(("BOUNCE", 1000 * f["tau_mid"], info))
        if out:
            self.called.add(key)
            self.block_dir = d
        return out if self.emit_enabled else []

    def _break(self):
        self.run = 0
        self.last_t = None


# ----------------------------------------------------------------------------------- engine
class VisionCallEngine:
    """Feed frames in arrival order with process(); returns the CallEvents emitted by that frame.

    The decision for frame t needs ball positions up to t - LAG, i.e. it runs as soon as frame t - LAG is
    final (sequentially: right after frame t's window). ready_ms[t] = when that decision step finished,
    minus t_frame(t): the latency any call made at t would have had."""

    def __init__(self, backend, frozen=None, geometry=None, fps=120.0, frame_offset=0, thr=0.3,
                 full_size=(1920, 1080), on_event=None, emit_enabled=True):
        assert_paper_only()
        M = tracking_modules()
        self.D = M.D
        self.lag = M.E.LAG
        self.fps = fps
        self.offset = frame_offset
        self.det = StreamingDetector(backend, M.D, thr=thr, full_size=full_size)
        self.trk = OnlineTracker(M.T)
        self.caller = FrozenCaller(frozen, geometry, fps, emit_enabled) if frozen is not None else None
        self.on_event = on_event or (lambda ev: None)
        self.events = []
        self.track_log = []
        self.arrival = {}
        self.ready_ms = {}
        self.t_track = 0.0

    def process(self, i, x, t_frame):
        """i: frame index in arrival order (0-based); x: preprocess() output; t_frame: arrival wall clock."""
        idx = i + self.offset
        self.arrival[idx] = t_frame
        if len(self.arrival) > 256:
            for k in [k for k in self.arrival if k < idx - 128]:
                del self.arrival[k]
        return self._consume(self.det.push(idx, x))

    def _consume(self, fin):
        evs = []
        for fi, cands in fin:
            t = time.perf_counter()
            r = self.trk.update(fi, cands)
            self.track_log.append((fi,) + ((np.nan,) * 4 if r is None else tuple(map(float, r))))
            self.t_track += time.perf_counter() - t
            td = fi + self.lag                       # decision frame enabled by this final position
            if td not in self.arrival:
                continue                             # that frame never arrived (stream end / gap)
            if self.caller is not None:
                for call, lead, info in self.caller.decide(td, self.trk.trk):
                    ev = CallEvent(
                        call=call, frame=td, t_frame=self.arrival[td], t_emit=now(), p_miss=info["p"],
                        lead_ms=float(lead),
                        rule=(f"online P>={self.caller.tau_on:.4f} x{self.caller.persist}" if call == "MISS"
                              else f"tau_mid<=50ms, gate open, P<{self.caller.tau_snap:.4f}"),
                        media_t=td / self.fps, flight_t0=int(info["t0"]), direction=int(info["d"]),
                        extra={k: (float(v) if not isinstance(v, tuple) else list(map(float, v)))
                               for k, v in info.items() if k not in ("t0", "d")})
                    self.events.append(ev)
                    self.on_event(ev)
                    evs.append(ev)
            self.ready_ms[td] = (now() - self.arrival[td]) * 1e3
        return evs

    def finish(self):
        return self._consume(self.det.flush())


# ----------------------------------------------------------------------------------- source + loop
def parse_source(s):
    return int(s) if isinstance(s, str) and s.isdigit() else s


class FrameSource:
    """Video reader thread: decode + resize to 512x288 RGB uint8, frames queued in arrival order.

    reader='pyav': FFmpeg via PyAV, resized with swscale 'area' in the same call detect.py's frame_iter
               uses (identical input to the offline detector; ~1.7 ms/frame for 1080p on the laptop).
               Files, HTTP(S), RTSP/RTMP/UDP/SRT.
    reader='cv2':  cv2.VideoCapture + cv2.resize(INTER_AREA) (~6-12 ms/frame for 1080p); any source incl.
               webcam indices. 'auto' = pyav for everything except webcam indices.
    realtime=True paces a file at `fps` (frame i is due at start + i / fps; t_frame = that due time, so
    decode and resize count as engine latency). Live sources are never paced: t_frame = the moment the
    decoder returns the frame. If the queue is full when a frame arrives in realtime / live mode, the frame
    is dropped (what a live capture driver does); `dropped` counts them."""

    def __init__(self, src, D, realtime=False, fps=None, max_frames=None, start_frame=0, maxsize=1200,
                 reader="auto"):
        self.src = parse_source(src)
        self.D = D
        self.realtime = realtime
        self.fps_req = fps
        self.max_frames = max_frames
        self.start_frame = start_frame
        self.q = queue.Queue(maxsize=maxsize)
        self.live = isinstance(self.src, int) or str(self.src).startswith(LIVE_PREFIXES)
        if reader == "auto":
            reader = "cv2" if isinstance(self.src, int) or importlib.util.find_spec("av") is None else "pyav"
        self.reader = reader
        self.info = {"dropped": 0, "reader": reader}
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.stop = threading.Event()

    def start(self):
        self.thread.start()
        return self

    # -- decoders: generators of (bgr-or-rgb small uint8, decode_ms, resize_ms)
    def _frames_cv2(self):
        import cv2
        cv2.setNumThreads(2)
        cap = cv2.VideoCapture(self.src) if isinstance(self.src, int) else cv2.VideoCapture(self.src, cv2.CAP_FFMPEG)
        if self.live:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            raise IOError(f"cannot open {self.src}")
        if self.start_frame:
            cap.set(cv2.CAP_PROP_POS_FRAMES, self.start_frame)
        self.info.update(fps=self.fps_req or cap.get(cv2.CAP_PROP_FPS) or 30.0,
                         width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        try:
            while True:
                a = time.perf_counter()
                ok, bgr = cap.read()
                b = time.perf_counter()
                if not ok:
                    return
                small = resize_rgb(bgr, self.D)
                yield small, (b - a) * 1e3, (time.perf_counter() - b) * 1e3
        finally:
            cap.release()

    def _frames_pyav(self):
        import av
        opts = {"rtsp_transport": "tcp", "fflags": "nobuffer", "flags": "low_delay"} if self.live else {}
        c = av.open(str(self.src), options=opts)
        st = c.streams.video[0]
        st.thread_type = "SLICE" if self.live else "AUTO"
        fps = float(st.average_rate or st.guessed_rate or 30.0)
        tb = float(st.time_base) if st.time_base else None
        self.info.update(fps=self.fps_req or fps, width=st.codec_context.width, height=st.codec_context.height)
        s = self.start_frame
        if s and tb:   # as detect.frame_iter: seek to the keyframe at or before s, decode forward
            c.seek(int(max(s - 2, 0) / fps / tb), stream=st, backward=True, any_frame=False)
        t0_pts = None
        try:
            it = c.decode(st)
            while True:
                a = time.perf_counter()
                try:
                    fr = next(it)
                except StopIteration:
                    return
                if s and tb and fr.pts is not None:
                    if t0_pts is None:
                        t0_pts = float(st.start_time or 0) * tb
                    if int(round((fr.pts * tb - t0_pts) * fps)) < s:
                        continue
                b = time.perf_counter()
                small = fr.to_ndarray(width=self.D.INP_W, height=self.D.INP_H, format="rgb24", interpolation="AREA")
                yield small, (b - a) * 1e3, (time.perf_counter() - b) * 1e3
        finally:
            c.close()

    def _run(self):
        try:
            gen = self._frames_pyav() if self.reader == "pyav" else self._frames_cv2()
            pace = self.realtime and not self.live
            t_wall0 = time.time() + 0.05
            t_perf0 = time.perf_counter() + 0.05
            i = 0
            late = []
            fps = None
            while not self.stop.is_set() and (self.max_frames is None or i < self.max_frames):
                if pace:
                    fps = fps or self.fps_req or 120.0
                    due = t_perf0 + i / fps
                    dt = due - time.perf_counter()
                    if dt > 0:
                        time.sleep(dt)
                    late.append(max(0.0, -dt) * 1e3)
                    t_frame = t_wall0 + i / fps
                try:
                    small, dec_ms, rs_ms = next(gen)
                except StopIteration:
                    break
                if not pace:   # arrival = when the decoder handed the frame over (resize counts as engine time)
                    t_frame = time.time() - rs_ms / 1e3
                item = (i, np.ascontiguousarray(small), t_frame, dec_ms, rs_ms)
                if self.realtime or self.live:
                    try:
                        self.q.put_nowait(item)
                    except queue.Full:
                        self.info["dropped"] += 1
                else:
                    self.q.put(item)
                i += 1
            self.info["read"] = i
            if late:
                self.info["reader_late_ms"] = pct(late)
        except Exception as e:  # surface reader errors to the consumer
            self.info["error"] = repr(e)
        finally:
            self.q.put(None)


def run_stream(engine, source, max_lag_ms=None, on_frame=None):
    """Consume `source` until it ends. Returns per-frame timing rows and the number of skipped frames.

    max_lag_ms: if set and the dequeued frame is older than this, the engine jumps to the newest queued
    frame (everything older is skipped) and continues from there in order: bounded latency for a live feed,
    at the cost of gaps (a gap ends the detector's window range, as a range end does offline).
    Default: process every frame."""
    rows = []
    skipped = 0
    done = False
    while not done:
        item = source.q.get()
        if item is None:
            break
        if max_lag_ms is not None and (now() - item[2]) * 1e3 > max_lag_ms:
            while True:
                try:
                    nxt = source.q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    done = True
                    break
                skipped += 1
                item = nxt
        i, small, t_frame, dec_ms, prep_ms = item
        t_deq = now()
        t_n = time.perf_counter()
        x = normalize(small, engine.D)
        prep_ms += (time.perf_counter() - t_n) * 1e3
        ti0 = engine.det.t_infer
        tp0 = engine.det.t_post
        tt0 = engine.t_track
        c = engine.caller
        tf0, tc0 = (c.t_feat, c.t_clf) if c else (0.0, 0.0)
        evs = engine.process(i, x, t_frame)
        t_done = now()
        rows.append(dict(i=i, t_frame=t_frame, qwait_ms=(t_deq - t_frame) * 1e3, decode_ms=dec_ms, prep_ms=prep_ms,
                         infer_ms=(engine.det.t_infer - ti0) * 1e3, blobs_ms=(engine.det.t_post - tp0) * 1e3,
                         track_ms=(engine.t_track - tt0) * 1e3,
                         feat_ms=((c.t_feat - tf0) * 1e3 if c else 0.0), clf_ms=((c.t_clf - tc0) * 1e3 if c else 0.0),
                         proc_ms=(t_done - t_deq) * 1e3, e2e_ms=(t_done - t_frame) * 1e3, n_events=len(evs)))
        if on_frame:
            on_frame(i, evs)
    engine.finish()
    return rows, skipped


def pct(a, qs=(50, 90, 99)):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    if not len(a):
        return {}
    return {f"p{q}": round(float(np.percentile(a, q)), 2) for q in qs} | {"mean": round(float(a.mean()), 2),
                                                                          "max": round(float(a.max()), 2)}


def summarize(rows, wall_s, skipped=0, engine=None):
    """fps_sustained = frames processed / wall time. Per-frame stage times (ms): decode + prep run in the
    reader thread; infer (time the engine waited on the detector), blobs, track, feat, clf in the engine
    thread; proc = engine time per frame; qwait = arrival -> dequeue; e2e = arrival -> frame processed.
    call_ready_ms = arrival of frame t -> decision for t done (the latency of a call made at t)."""
    n = len(rows)
    keys = ["decode_ms", "prep_ms", "infer_ms", "blobs_ms", "track_ms", "feat_ms", "clf_ms", "proc_ms",
            "qwait_ms", "e2e_ms"]
    out = {"frames": n, "skipped": skipped, "wall_s": round(wall_s, 3),
           "fps_sustained": round(n / wall_s, 2) if wall_s > 0 else None,
           **{k: pct([r[k] for r in rows]) for k in keys}}
    if engine is not None:
        out["call_ready_ms"] = pct(list(engine.ready_ms.values()))
        out["detector"] = engine.det.name
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="file path, URL (rtsp/http) or webcam index")
    ap.add_argument("--backend", default="onnx-cpu",
                    help="onnx-cpu | onnx-coreml | onnx-coreml-gpu16 | onnx-coreml-ane16 | onnx-cuda | onnx-cuda16 | "
                         "torch-cuda | torch-mps | torch-cpu, or a comma-separated pool")
    ap.add_argument("--blurball_root", default=None)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--realtime", action="store_true", help="pace a file at --fps (as if live)")
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--frame-offset", type=int, default=0, help="source frame number of the first frame")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--max-lag-ms", type=float, default=None)
    ap.add_argument("--video", default=None, help="OpenTTGames video name (geometry)")
    ap.add_argument("--geometry", default=None)
    ap.add_argument("--corners", default=None, help="'x,y;x,y;x,y;x,y' far-left, far-right, near-right, near-left")
    ap.add_argument("--frozen", default=str(FROZEN_PATH))
    ap.add_argument("--log", default=None, help="CallEvent JSONL output")
    ap.add_argument("--reader", default="auto", help="auto | pyav | cv2")
    ap.add_argument("--track-only", action="store_true", help="no frozen model: detection + tracking only")
    a = ap.parse_args()
    assert_paper_only()
    M = tracking_modules()
    try:
        frozen = load_frozen(a.frozen)
    except FileNotFoundError as e:
        if not a.track_only:
            raise SystemExit(f"{e}\n(use --track-only to run detection + tracking without calls)")
        frozen = None
    corners = [tuple(map(float, p.split(","))) for p in a.corners.split(";")] if a.corners else None
    geo, prov = (load_geometry(a.video, frozen, corners, a.geometry) if frozen is not None else (None, "n/a"))
    print(f"geometry: {prov}", flush=True)
    fh = open(a.log, "a") if a.log else None

    def on_event(ev):
        print(f"[{ev.call}] frame {ev.frame} p_miss={ev.p_miss:.3f} lead~{ev.lead_ms:.0f} ms "
              f"latency {ev.latency_ms:.1f} ms", flush=True)
        if fh:
            fh.write(ev.to_json() + "\n")
            fh.flush()
    eng = VisionCallEngine(make_backend(a.backend, a.blurball_root, a.threads), frozen, geo,
                           fps=a.fps or 120.0, frame_offset=a.frame_offset, on_event=on_event)
    src = FrameSource(a.source, M.D, realtime=a.realtime, fps=a.fps, max_frames=a.max_frames,
                      reader=a.reader).start()
    t = time.time()
    rows, sk = run_stream(eng, src, a.max_lag_ms)
    print(json.dumps(summarize(rows, time.time() - t, sk, eng), indent=1))


if __name__ == "__main__":
    main()
