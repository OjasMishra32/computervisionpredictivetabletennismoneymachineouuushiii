"""Assets for scripts/cv_showcase.py, pulled from the HiPerGator project directory (presentation only).

Real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0). This script computes no metric and
fits nothing new. For the three test MISS flights in results/tracking/demo and the demo BOUNCE flight it
writes:

  * the raw video frames around each flight (PyAV decode, frame index = round(pts * fps), the same
    indexing as src/tracking/render_demo.py), re-encoded near-losslessly (H.264 CRF 10, 120 fps) as
    <out>/<video>_<f_net>_<first>.mp4;
  * the BlurBall track points (work/tracking/tracks) in those frame ranges;
  * the FROZEN tier-0 model's per-frame P(MISS) and horizon-gate state, from
    src/tracking/render_demo.frozen_scores(), which refits the frozen HGB exactly as early_call.py --final
    did and asserts that its scores and online first-call leads reproduce results/tracking/test_flights.csv.

Usage (HiPerGator, project dir, venv_track):
  python scripts/cv_showcase_assets.py --out work/cv_showcase
"""
import argparse
import json
import os
import sys

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "src", "tracking"))

import av  # noqa: E402

import early_call as E  # noqa: E402
import render_demo as RD  # noqa: E402
from common import OTTG  # noqa: E402

# (video, f_net, first frame, last frame): ~1.8 s of lead-in before the flight start, ~0.6 s after T_ref
CLIPS = [("test_2", 2819, 2560, 2940), ("test_4", 5750, 5560, 5840), ("test_6", 1484, 1300, 1580),
         ("test_6", 1299, 1150, 1400)]


def cut(video, s, e, path):
    c = av.open(os.path.join(OTTG, f"{video}.mp4"))
    st = c.streams.video[0]
    st.thread_type = "AUTO"
    fps, tb = float(st.average_rate), float(st.time_base)
    c.seek(int(max(s - 2, 0) / fps / tb), stream=st, backward=True, any_frame=False)
    o = av.open(path, "w")
    vs = o.add_stream("libx264", rate=120)
    vs.width, vs.height, vs.pix_fmt = 1920, 1080, "yuv420p"
    vs.options = {"crf": "10", "preset": "medium"}
    got = []
    for fr in c.decode(st):
        i = int(round(fr.pts * tb * fps))
        if i < s:
            continue
        if i > e:
            break
        if got and i != got[-1] + 1:
            raise RuntimeError(f"{video}: frame gap {got[-1]} -> {i}")
        img = fr.to_ndarray(format="rgb24")
        for p in vs.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            o.mux(p)
        got.append(i)
    for p in vs.encode():
        o.mux(p)
    o.close()
    c.close()
    return got[0], got[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work/cv_showcase")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    fin, te, S, objs, tracks, geo = RD.frozen_scores()          # asserts exact reproduction
    out = {"footage": "real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0)",
           "model": "frozen tier-0 HGB (early_call_final.json)", "tau_online": fin["tau_online"],
           "tau_snapshot": fin["tau_snapshot"], "gate_h_s": fin["gate_h_s"], "persist_frames": E.PERSIST,
           "clips": []}
    for video, f_net, s, e in CLIPS:
        fid = te.index[(te.video == video) & (te.f_net == f_net)]
        assert len(fid) == 1, (video, f_net)
        fid = fid[0]
        r = te.loc[fid]
        g = S[S.fid == fid]
        lead_k = None if r.online_lead_frames is None or not np.isfinite(r.online_lead_frames) \
            else int(r.online_lead_frames)
        path = os.path.join(a.out, f"{video}_{f_net}_{s}.mp4")
        f0, f1 = cut(video, s, e, path)
        trk = {int(f): [float(u), float(v)] for f, (u, v) in tracks[video].items() if s <= f <= e}
        out["clips"].append(dict(
            video=video, f_net=int(f_net), label=r.label, miss_type=r.miss_type if isinstance(r.miss_type, str)
            else None, dir=float(r.dir), t0=int(r.t0), t_ref=int(r.t_ref), first_frame=f0, last_frame=f1,
            file=os.path.basename(path), online_lead_frames=lead_k,
            online_lead_ms=None if lead_k is None else E.ms(lead_k),
            call_frame=None if lead_k is None else int(r.t_ref) - lead_k,
            p_miss_at_50ms=float(r.p50) if np.isfinite(r.p50) else None,
            table_corners_px=np.asarray(geo[video]["corners"], float).round(2).tolist(),
            score={int(t): round(float(x), 6) for t, x in zip(g.t.values, g.score.values)},
            gated={int(t): bool(x) for t, x in zip(g.t.values, (np.minimum(g.tau_end, g.tau_net) > E.GATE_H).values)},
            track=trk))
        print(video, f_net, "frames", f0, f1, "lead", out["clips"][-1]["online_lead_ms"], flush=True)
    json.dump(out, open(os.path.join(a.out, "assets.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
