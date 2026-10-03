"""Save single video frames (960x540 JPEG) for figures and visual spot checks.

python extract_frames.py                      # one background frame per video -> WORK/frames/<video>.jpg
python extract_frames.py game_1:2192 game_2:900 ...   # -> WORK/frames/<video>_<frame>.jpg
"""
import os
import sys

import av
import cv2

from common import ALL, OTTG, WORK, load_events


def grab(video, idx):
    c = av.open(os.path.join(OTTG, f"{video}.mp4"))
    s = c.streams.video[0]
    fps, tb = float(s.average_rate), float(s.time_base)
    c.seek(int(max(idx - 2, 0) / fps / tb), stream=s, backward=True, any_frame=False)
    for fr in c.decode(s):
        if int(round(fr.pts * tb * fps)) >= idx:
            img = fr.to_ndarray(width=960, height=540, format="bgr24")
            c.close()
            return img
    c.close()


if __name__ == "__main__":
    os.makedirs(os.path.join(WORK, "frames"), exist_ok=True)
    if len(sys.argv) > 1:
        for a in sys.argv[1:]:
            v, f = a.split(":")
            cv2.imwrite(os.path.join(WORK, "frames", f"{v}_{f}.jpg"), grab(v, int(f)), [cv2.IMWRITE_JPEG_QUALITY, 88])
    else:
        for v in ALL:
            f = [f for f, e in load_events(v) if e == "bounce"][0] - 60
            cv2.imwrite(os.path.join(WORK, "frames", f"{v}.jpg"), grab(v, f), [cv2.IMWRITE_JPEG_QUALITY, 88])
            print(v, f)
