"""Equivalence and safety tests for the streaming vision engine (no video, no model files needed).

  pytest engine/vision/tests -q
"""
import os
from types import SimpleNamespace

import numpy as np
import pytest

from engine.vision import events
from engine.vision.stream import (FrozenCaller, OnlineTracker, StreamingDetector, geometry_from_corners,
                                  tracking_modules)

M = tracking_modules()


# --------------------------------------------------------------------------------------------- safety
def test_paper_only_guard(monkeypatch):
    events.assert_paper_only()
    monkeypatch.setenv("COURTSIDE_LIVE_TRADING", "1")
    with pytest.raises(events.LiveTradingForbidden):
        events.assert_paper_only()
    monkeypatch.delenv("COURTSIDE_LIVE_TRADING")
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0xabc")
    with pytest.raises(events.LiveTradingForbidden):
        events.assert_paper_only()
    monkeypatch.delenv("POLYMARKET_PRIVATE_KEY")
    with pytest.raises(events.LiveTradingForbidden):
        events.enable_live_trading()


# --------------------------------------------------------------------------------------------- tracker
def test_online_tracker_matches_trajectories_track():
    rng = np.random.default_rng(0)
    n = 3000
    frames = np.cumsum(rng.choice([1, 1, 1, 1, 2, 5, 12], n))
    cands = np.full((n, M.D.K, 5), np.nan, np.float32)
    pos = np.array([500.0, 400.0])
    vel = np.array([12.0, -3.0])
    for i in range(n):
        if rng.random() < 0.02:
            pos = rng.uniform([0, 0], [1920, 1080])
            vel = rng.normal(0, 15, 2)
        pos = pos + vel
        k = rng.integers(0, M.D.K + 1)
        for j in range(k):
            jitter = rng.normal(0, 3 if j == 0 else 200, 2)
            cands[i, j] = (*(pos + jitter), rng.uniform(1, 50), rng.uniform(0.1, 1.0), 20)
    ref = M.T.track(frames, cands)
    tr = OnlineTracker(M.T)
    got = np.full_like(ref, np.nan)
    for i, (f, c) in enumerate(zip(frames, cands)):
        r = tr.update(int(f), c)
        if r is not None:
            got[i] = r
    assert np.array_equal(np.isnan(ref), np.isnan(got))
    np.testing.assert_allclose(got[np.isfinite(got)], ref[np.isfinite(ref)], rtol=0, atol=1e-4)


# --------------------------------------------------------------------------------------------- detector
class FakeBackend:
    """Deterministic stand-in for BlurBall: heatmap q of a window = squashed channel (3q) of the input."""
    name = "fake"

    def __call__(self, x):
        hm = np.stack([1 / (1 + np.exp(-x[0, 3 * q])) for q in range(3)])
        return hm[None].astype(np.float32)


def _frames(n, rng):
    H, W = M.D.INP_H, M.D.INP_W
    yy, xx = np.mgrid[0:H, 0:W]
    out = []
    for i in range(n):
        x = rng.normal(-4, 0.3, (3, H, W)).astype(np.float32)
        cx, cy = 40 + 7 * i % (W - 80), 60 + (3 * i) % (H - 120)
        x[0] += 8 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / 18.0)
        out.append(x)
    return out


def _offline_reference(frames, thr=0.3, full=(1920, 1080)):
    """detect.py's averaging for one contiguous range: frame q gets the windows w in [q-2, q] that fit."""
    n = len(frames)
    be = FakeBackend()
    hms = [be(np.concatenate(frames[w:w + 3], 0)[None])[0] for w in range(n - 2)]
    sx, sy = full[0] / M.D.INP_W, full[1] / M.D.INP_H
    out = []
    for q in range(n):
        ws = [w for w in range(q - 2, q + 1) if 0 <= w <= n - 3]
        acc = sum(hms[w][q - w] for w in ws) if ws else np.zeros_like(frames[0][0])
        hm = acc / max(len(ws), 1)
        c = np.full((M.D.K, 5), np.nan, np.float32)
        for k, (bx, by, sc, pk, ar) in enumerate(M.D.blobs(hm, thr)):
            c[k] = ((bx + 0.5) * sx - 0.5, (by + 0.5) * sy - 0.5, sc, pk, ar)
        out.append(c)
    return out


@pytest.mark.parametrize("pool", [1, 3])
def test_streaming_detector_matches_offline_averaging(pool):
    rng = np.random.default_rng(1)
    frames = _frames(14, rng)
    ref = _offline_reference(frames)
    det = StreamingDetector([FakeBackend() for _ in range(pool)] if pool > 1 else FakeBackend(), M.D)
    got = []
    for i, x in enumerate(frames):
        got += det.push(100 + i, x)
    got += det.flush()
    assert [g[0] for g in got] == list(range(100, 114))
    for (f, c), r in zip(got, ref):
        np.testing.assert_allclose(c, r, rtol=1e-5, atol=1e-4, equal_nan=True)


def test_streaming_detector_gap_starts_new_range():
    rng = np.random.default_rng(2)
    frames = _frames(10, rng)
    det = StreamingDetector(FakeBackend(), M.D)
    got = []
    for i, x in enumerate(frames[:5]):
        got += det.push(i, x)
    for i, x in enumerate(frames[5:]):
        got += det.push(50 + i, x)
    got += det.flush()
    ref = _offline_reference(frames[:5]) + _offline_reference(frames[5:])
    assert [g[0] for g in got] == list(range(5)) + list(range(50, 55))
    for (f, c), r in zip(got, ref):
        np.testing.assert_allclose(c, r, rtol=1e-5, atol=1e-4, equal_nan=True)


# --------------------------------------------------------------------------------------------- geometry
def test_geometry_from_corners_matches_common():
    os.environ.setdefault("OTTG_ROOT", os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "openttgames"))
    M.C.MARKUP = os.path.join(os.environ["OTTG_ROOT"], "markup")
    if not os.path.isdir(os.path.join(M.C.MARKUP, "test_2", "segmentation_masks")):
        pytest.skip("no local OpenTTGames masks")
    g = M.C.table_geometry("test_2")
    h = geometry_from_corners(g["corners"])
    for k, v in g.items():
        np.testing.assert_allclose(np.asarray(h[k], float), np.asarray(v, float), rtol=0, atol=1e-9, err_msg=k)


# --------------------------------------------------------------------------------------------- call rule
class ConstModel:
    def __init__(self, p):
        self.p = p

    def predict_proba(self, X):
        return np.array([[1 - self.p, self.p]])


def _table():
    # far-left, far-right, near-right, near-left (image px)
    return geometry_from_corners([(560, 560), (1360, 560), (1440, 680), (480, 680)])


def _long_ball(n=60):
    """A ball hit left -> right, flying over the net and well past the far end line, 120 fps."""
    g = _table()
    trk = {}
    for i in range(n):
        x = 470 + 22.0 * i
        y = 470 + 0.06 * (i - 25) ** 2
        trk[1000 + i] = (x, y)
    return g, trk


def _frozen(p):
    return dict(model=ConstModel(p), feats=M.E.FEATS_ALL, gate_h_s=0.10, tau_online=0.9799, tau_snapshot=0.8854,
                persist=3, lag=2)


def test_gate_matches_early_call_gated():
    import pandas as pd
    rng = np.random.default_rng(3)
    S = pd.DataFrame({"tau_end": rng.uniform(0, 1, 200), "tau_net": rng.uniform(0, 1, 200)})
    s = rng.uniform(0, 1, 200)
    M.E.GATE_H = 0.10
    ref = M.E.gated(s, S)
    got = np.where(np.minimum(S.tau_end, S.tau_net) <= 0.10, s, 0.0)
    np.testing.assert_array_equal(ref, got)


def test_online_rule_fires_after_three_gated_frames():
    g, trk = _long_ball()
    c = FrozenCaller(_frozen(0.99), g)
    fired, gated_run = [], 0
    for t in range(1000, 1062):
        sub = {f: p for f, p in trk.items() if f <= t - 2}
        out = c.decide(t, sub)
        if c.trace and c.trace[-1][0] == t:
            gated_run = gated_run + 1 if c.trace[-1][3] >= c.tau_on else 0
        if out:
            fired.append((t, out[0][0], gated_run))
    assert fired, "no call"
    t, call, run = fired[0]
    assert call == "MISS" and run == 3
    assert len(fired) == 1          # one call per shot


def test_no_call_below_threshold():
    g, trk = _long_ball()
    c = FrozenCaller(_frozen(0.97), g)       # below tau_online = 0.9799
    calls = []
    for t in range(1000, 1062):
        calls += [o[0] for o in c.decide(t, {f: p for f, p in trk.items() if f <= t - 2})]
    assert "MISS" not in calls
