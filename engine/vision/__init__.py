"""COURTSIDE vision engine: streaming ball tracking -> CallEvent (MISS / BOUNCE). Paper only.

events.py   CallEvent + the paper-only guard (shared by every call source)
stream.py   table-tennis engine: any cv2.VideoCapture source -> BlurBall detector (frozen, zero-shot)
            -> causal tracker (src/tracking/trajectories.py rules) -> frozen H3 early-call classifier
            (src/tracking/early_call.py features, HGB, gate, tau_online, 3-frame persistence) -> CallEvent
tennis.py   the same CallEvent interface for Hawk-Eye-class 3D tracks (src/hawkeye.predict_landing)
run_demo.py plays a held-out OpenTTGames test clip in real time and logs every CallEvent + latency
export_frozen.py  rebuilds models/vision/frozen_call_model.pkl on HiPerGator (asserts it reproduces the test)
bench_gpu.py      GPU benchmark matrix (precision x graph / compile x batch; real-time and max modes)
eval_online.py    held-out test_1..7 streamed through the engine, scored exactly as results/tracking/summary.json
"""
from .events import CallEvent, LiveTradingForbidden, assert_paper_only  # noqa: F401
