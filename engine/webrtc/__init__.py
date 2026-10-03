"""COURTSIDE WebRTC latency pipeline (paper only, our own stream only).

Our held-out OpenTTGames clip -> sender.py (paced raw frames + frame code, ffmpeg H.264 low latency, WHIP)
-> MediaMTX on 127.0.0.1 (mediamtx.yml) -> whep_reader.py (aiortc WHEP, decode, frame code read back)
-> engine.vision.stream (unchanged online loop) -> CallEvents / detections with capture, send, receive,
model-done and emit times. scripts/webrtc_demo.sh runs the whole thing; report.py defines the legs.
"""
