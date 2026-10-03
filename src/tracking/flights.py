"""Segment shots ("flights") and label how each one ends: TABLE BOUNCE or MISS.

Annotation semantics (checked on game_1..5 only, see DEVIATIONS.md): an OpenTTGames 'net' event
marks the frame where the ball reaches the net plane, for every shot (1,232 'net' vs 1,537
'bounce' events in game_1..5; in 92% of cases the next event is a bounce on the far side 8-50
frames later). So every shot that reaches the net is one flight, anchored at its 'net' frame f_n.

Label of the flight anchored at f_n (direction of travel `dir` = sign of dx in the labelled ball
positions f_n-4..f_n+8):
  BOUNCE  the next non-empty event is a 'bounce' within 60 frames (0.5 s) of f_n, and on the far
          side of the net (or the side is unknown because the ball label is missing).
          T_ref = the bounce frame.
  MISS    otherwise (no bounce follows: the next event is >= 80 frames later, i.e. the next rally,
          or the ball came back to the hitter's side).
          miss_type = 'net' if the ball never gets 25 px past the net-crossing x in the labelled /
          tracked frames f_n..f_n+12 (it hit the net); T_ref = f_n.
          miss_type = 'out' otherwise; T_ref = first tracked frame after f_n at which the ball
          passes the table end line (mean x of the two end corners), or drops below the near
          table edge (y > near edge + 10 px), or is lost for >= 6 frames (T_ref = last seen + 1).
          If none of these happens within 90 frames the flight is dropped (counted).
Flight start t0 = the last contact before f_n: the later of (last labelled bounce before f_n) and
(the last x-velocity reversal in the track before f_n, i.e. the racket hit), +1 frame.

Output: WORK/flights.csv
"""
import os

import numpy as np
import pandas as pd

from common import ALL, TEST, TRAIN, WORK, geometry_all, load_ball, load_events

W_BOUNCE = 60
MISS_SEARCH = 90
LOST = 6


def load_track(video):
    t = pd.read_csv(os.path.join(WORK, "tracks", f"{video}_tracks.csv"))
    return {int(f): (x, y) for f, x, y in zip(t.frame, t.x, t.y) if np.isfinite(x)}


def pos(f, ball, trk):
    """Position at frame f: label if available, else track."""
    p = ball.get(f)
    return p if p is not None else trk.get(f)


def flight_start(f_n, d, trk, b_prev):
    """Walk back from f_n while the ball keeps moving in direction d; stop at a reversal."""
    lo = max(f_n - 150, (b_prev + 1) if b_prev is not None else -10 ** 9)
    t, last, opp = f_n, None, 0
    start = f_n
    while t > lo:
        t -= 1
        p = trk.get(t)
        if p is None:
            if last is not None and last - t > 4:
                break
            continue
        if last is not None:
            dx = (trk[last][0] - p[0]) * d / (last - t)
            if dx < -1.0:      # moving against d -> before the racket hit
                opp += 1
                if opp >= 2:
                    break
            else:
                opp = 0
                start = t
        else:
            start = t
        last = t
    return max(start, lo)


def build(videos):
    geo = geometry_all()
    rows, dropped = [], []
    for v in videos:
        g = geo[v]
        ball = load_ball(v)
        trk = load_track(v)
        ev = [(f, e) for f, e in load_events(v) if e != "empty_event"]
        a_near, b_near = g["near_line"]
        for i, (f_n, e) in enumerate(ev):
            if e != "net":
                continue
            pts = [(t, ball[t]) for t in range(f_n - 4, f_n + 9) if ball.get(t)]
            if len(pts) < 3:
                pts = [(t, trk[t]) for t in range(f_n - 4, f_n + 9) if t in trk]
            if len(pts) < 3:
                dropped.append((v, f_n, "no direction"))
                continue
            d = float(np.sign(pts[-1][1][0] - pts[0][1][0]))
            p_n = pos(f_n, ball, trk) or pts[0][1]
            x_cross = p_n[0]
            nxt = ev[i + 1] if i + 1 < len(ev) else None
            b_prev = max([f for f, e2 in ev[:i] if e2 == "bounce" and f_n - f <= 150], default=None)
            label, mtype, t_ref = None, None, None
            if nxt and nxt[1] == "bounce" and nxt[0] - f_n <= W_BOUNCE:
                pb = pos(nxt[0], ball, trk)
                if pb is None or (pb[0] - x_cross) * d > 0:
                    label, t_ref = "BOUNCE", nxt[0]
                    land_x = pb[0] if pb is not None else np.nan
                else:
                    label, mtype, t_ref = "MISS", "net", f_n   # came back: net hit
            if label is None:
                label = "MISS"
                past = [(pos(t, ball, trk)[0] - x_cross) * d for t in range(f_n + 1, f_n + 13)
                        if pos(t, ball, trk) is not None]
                if not past or max(past) < 25:
                    mtype, t_ref = "net", f_n
                else:
                    mtype = "out"
                    x_end = g["x_right"] if d > 0 else g["x_left"]
                    last_seen = f_n
                    for t in range(f_n + 1, f_n + MISS_SEARCH + 1):
                        p = trk.get(t) or ball.get(t)
                        if p is None:
                            if t - last_seen >= LOST:
                                t_ref = last_seen + 1
                                break
                            continue
                        last_seen = t
                        if (p[0] - x_end) * d >= 0 or p[1] > a_near * p[0] + b_near + 10:
                            t_ref = t
                            break
            if label == "MISS":
                land_x = np.nan
                if t_ref is None:
                    dropped.append((v, f_n, "out: no end/lost within 90 frames"))
                    continue
            t0 = flight_start(f_n, d, trk, b_prev) + 1
            rows.append({
                "video": v, "split": "test" if v in TEST else "train", "f_net": f_n, "dir": d,
                "label": label, "miss_type": mtype, "t_ref": int(t_ref), "t0": int(t0),
                "b_prev": b_prev if b_prev is not None else -1, "x_cross": x_cross,
                "land_x": land_x, "next_event_gap": (nxt[0] - f_n) if nxt else -1,
            })
    return pd.DataFrame(rows), pd.DataFrame(dropped, columns=["video", "f_net", "reason"])


if __name__ == "__main__":
    import sys
    videos = sys.argv[1:] or ALL
    df, dr = build(videos)
    df.to_csv(os.path.join(WORK, "flights.csv"), index=False)
    dr.to_csv(os.path.join(WORK, "flights_dropped.csv"), index=False)
    for s in ["train", "test"]:
        sub = df[df.split == s]
        if len(sub):
            print(s, sub.groupby(["label", "miss_type"], dropna=False).size().to_dict(),
                  "dropped", int((dr.video.isin(TEST if s == "test" else TRAIN)).sum()))
