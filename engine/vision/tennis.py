"""Tennis variant (stub): Hawk-Eye-class 3D ball tracks -> the same CallEvent interface. Paper only.

Input: per-shot streams of 3D ball samples (t, x, y, z) in court metres (src/hawkeye.py frame: y from the
hitter's baseline to the far baseline, x across, z up), e.g. ~340 Hz from a multi-camera tracker. No
video model here: the tracker vendor supplies the 3D points.

At each evaluated sample the last 150 ms are passed to src/hawkeye.predict_landing (local quadratic fit,
spin backed out of the acceleration, drag + Magnus integrated to the bounce), and the landing point goes
through hawkeye.signed_out_distance. Frozen numbers, nothing tuned here:
  threshold_m   from results/hawkeye_tennis_calls.csv (the 95%-precision threshold picked on the
                calibration half by hawkeye.calls_at_precision; -0.05 m at every lead)
  max_lead_ms   400, the longest lead hawkeye.simulate evaluated (calls earlier than that are outside
                the measured range and are not made)
Rule: MISS (out) at the first evaluation with predicted out-distance > threshold_m; BOUNCE (in) at the
first evaluation <= 50 ms before the predicted bounce with out-distance <= threshold_m. One call per shot.

predict_landing costs ~15-20 ms per call on a laptop core (RK4 at 0.5 ms steps), so the stub evaluates
every `every`-th sample (default 6, ~57 Hz at 340 Hz input); `lead_ms` is the predicted time to the bounce.

Self-test (simulated shots from hawkeye.sample_shots; this is a physics simulation, not tracking data):
  python -m engine.vision.tennis --shots 120
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import deque
from pathlib import Path

import numpy as np

from .events import CallEvent, assert_paper_only, now

REPO = Path(__file__).resolve().parents[2]
CALLS_CSV = REPO / "results" / "hawkeye_tennis_calls.csv"


def frozen_threshold(lead_ms=50, path=CALLS_CSV):
    """threshold_m at the given lead from the frozen hawkeye results (default -0.05 m)."""
    try:
        with open(path) as fh:
            for r in csv.DictReader(fh):
                if int(float(r["lead_ms"])) == lead_ms and r["threshold_m"] not in ("", "nan"):
                    return float(r["threshold_m"])
    except FileNotFoundError:
        pass
    return -0.05


class TennisCallEngine:
    def __init__(self, fps=None, window_s=0.15, threshold_m=None, max_lead_ms=400.0, bounce_lead_ms=50.0,
                 every=6, serve=False, on_event=None):
        assert_paper_only()
        from src import hawkeye as H
        self.H = H
        self.fps = fps or H.FPS
        self.W = int(window_s * self.fps)
        if self.fps != H.FPS:
            raise ValueError(f"hawkeye.predict_landing assumes {H.FPS} Hz samples")
        self.thr = frozen_threshold() if threshold_m is None else threshold_m
        self.max_lead_ms, self.bounce_lead_ms = max_lead_ms, bounce_lead_ms
        self.every, self.serve = every, serve
        self.on_event = on_event or (lambda ev: None)
        self.eval_ms = []
        self.start_shot()

    def start_shot(self, shot_id=None):
        self.buf = deque(maxlen=self.W)
        self.n = 0
        self.called = False
        self.shot_id = shot_id

    def _time_to_land(self, win):
        """Predicted time (s) until z reaches the ball radius, from a quadratic fit of z(t) (lead only)."""
        tt = np.arange(-len(win) + 1, 1) / self.fps
        a, b, c = np.polyfit(tt, win[:, 2] - self.H.R, 2)
        r = np.roots([a, b, c]) if abs(a) > 1e-9 else np.array([-c / b])
        r = r[np.isreal(r)].real
        r = r[r > 0]
        return float(r.min()) if len(r) else float("nan")

    def push(self, xyz, t_frame=None, frame=None):
        """One 3D sample. Returns a CallEvent or None."""
        t_frame = now() if t_frame is None else t_frame
        self.buf.append(np.asarray(xyz, float))
        self.n += 1
        if self.called or len(self.buf) < self.W or self.n % self.every:
            return None
        win = np.stack(self.buf)
        lead = 1000 * self._time_to_land(win)          # cheap check first: inside the evaluated range?
        if not np.isfinite(lead) or lead > self.max_lead_ms:
            return None
        t0 = time.perf_counter()
        land = self.H.predict_landing(win[None])[0]
        d_hat = float(self.H.signed_out_distance(land[None], np.array([self.serve]))[0])
        self.eval_ms.append((time.perf_counter() - t0) * 1e3)
        call = None
        if d_hat > self.thr:
            call = "MISS"
        elif lead <= self.bounce_lead_ms:
            call = "BOUNCE"
        if call is None:
            return None
        self.called = True
        ev = CallEvent(call=call, frame=self.n - 1 if frame is None else frame, t_frame=t_frame, t_emit=now(),
                       p_miss=float("nan"), lead_ms=lead, source="tennis_3d",
                       rule=f"hawkeye.predict_landing out-distance > {self.thr:+.2f} m (lead <= {self.max_lead_ms:.0f} ms)",
                       media_t=(self.n - 1) / self.fps,
                       extra=dict(d_hat_m=d_hat, land_x=float(land[0]), land_y=float(land[1]),
                                  shot_id=self.shot_id))
        self.on_event(ev)
        return ev


def selftest(n_shots=120, seed=11, every=6):
    """Stream simulated near-line groundstrokes through the engine; precision / lead of the first call."""
    from src import hawkeye as H
    rng = np.random.default_rng(seed)
    s = H.sample_shots(n_shots * 25, rng)
    acc_t = lambda v, a: H._accel_truth(v, s["w_hat"][a], s["omega"][a])
    land, tland, traj = H._integrate(s["p0"], s["v0"], acc_t, record_every=1 / H.FPS)
    y = traj[..., 1]
    cross = np.argmax(np.nan_to_num(y, nan=-1) >= H.NET_Y, axis=1)
    zc = traj[np.arange(len(traj)), cross, 2]
    d = H.signed_out_distance(land, s["serve"])
    ok = np.isfinite(tland) & (zc > H.NET_H + H.R) & (tland > 0.25) & (np.abs(d) < 1.0)
    ins, outs = np.flatnonzero(ok & (d <= 0)), np.flatnonzero(ok & (d > 0))
    k = min(len(ins), len(outs), n_shots // 2)
    idx = np.sort(np.concatenate([rng.choice(ins, k, replace=False), rng.choice(outs, k, replace=False)]))
    eng = TennisCallEngine(every=every)
    rows = []
    for i in idx:
        meas = traj[i] + rng.normal(0, H.NOISE, traj[i].shape)
        n_land = int(np.floor(tland[i] * H.FPS))
        eng.start_shot(int(i))
        ev = None
        for j in range(n_land + 1):
            ev = eng.push(meas[j], frame=j)
            if ev is not None:
                break
        true_lead = None if ev is None else 1000 * (tland[i] - ev.frame / H.FPS)
        rows.append(dict(shot=int(i), d_true_m=float(d[i]), call=None if ev is None else ev.call,
                         lead_true_ms=true_lead, lead_pred_ms=None if ev is None else ev.lead_ms,
                         latency_ms=None if ev is None else ev.latency_ms))
    miss = [r for r in rows if r["call"] == "MISS"]
    bnc = [r for r in rows if r["call"] == "BOUNCE"]
    n_out = sum(r["d_true_m"] > 0 for r in rows)
    lat = np.array(eng.eval_ms)
    res = dict(
        note="simulated Hawk-Eye-class tracks (src/hawkeye.py physics + 3.6 mm noise at 340 Hz), not real data",
        shots=len(rows), outs=n_out, threshold_m=eng.thr, every=every,
        miss_calls=len(miss), miss_precision=(sum(r["d_true_m"] > 0 for r in miss) / len(miss)) if miss else None,
        miss_recall=(sum(r["d_true_m"] > 0 for r in miss) / n_out) if n_out else None,
        miss_lead_true_ms=dict(p10=float(np.percentile([r["lead_true_ms"] for r in miss], 10)),
                               median=float(np.median([r["lead_true_ms"] for r in miss])),
                               p90=float(np.percentile([r["lead_true_ms"] for r in miss], 90))) if miss else None,
        bounce_calls=len(bnc),
        bounce_precision=(sum(r["d_true_m"] <= 0 for r in bnc) / len(bnc)) if bnc else None,
        predict_landing_ms=dict(p50=float(np.median(lat)), p90=float(np.percentile(lat, 90)),
                                max=float(lat.max())) if len(lat) else None,
    )
    return res, rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", type=int, default=120)
    ap.add_argument("--every", type=int, default=6)
    ap.add_argument("--out", default=None, help="merge the result into this JSON under 'tennis_stub'")
    a = ap.parse_args()
    res, _ = selftest(a.shots, every=a.every)
    print(json.dumps(res, indent=1))
    if a.out:
        import os
        d = json.load(open(a.out)) if os.path.exists(a.out) else {}
        d["tennis_stub"] = res
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump(d, open(a.out, "w"), indent=1, default=float)
