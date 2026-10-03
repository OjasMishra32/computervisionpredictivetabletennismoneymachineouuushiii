"""Who gets paid around a score event? Markouts by seconds since the jump.

For every taker print we know which side it hit (see tape.load_tape). Its markout at
horizon h is the move of the mid from the print price to t+h, signed by the taker's
direction: what the taker made per share before fees. Prints are bucketed by the time
since the most recent jump onset in that match. If knowledge arrives in tiers, early
prints should earn and late prints should pay.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.tape import in_play, load_tape

BUCKETS = [(-1e9, 0), (0, 3), (3, 6), (6, 10), (10, 20), (20, 40), (40, 120), (120, 1e9)]
LABELS = ["no jump", "0-3s", "3-6s", "6-10s", "10-20s", "20-40s", "40-120s", ">120s"]
HORIZONS = (5, 15, 30, 60, 120)


def _mid_series(ts, p, at_ask, stale=30):
    """Mid proxy at each print: mean of the latest bid-side and ask-side prints (<= stale s old)."""
    n = len(ts)
    bid = np.full(n, np.nan)
    ask = np.full(n, np.nan)
    lb = la = None
    tb = ta = -1e18
    for i in range(n):
        if at_ask[i]:
            la, ta = p[i], ts[i]
        else:
            lb, tb = p[i], ts[i]
        if la is not None and ts[i] - ta <= stale:
            ask[i] = la
        if lb is not None and ts[i] - tb <= stale:
            bid[i] = lb
    mid = np.where(np.isfinite(bid) & np.isfinite(ask) & (ask >= bid), (bid + ask) / 2, p)
    return mid, ask - bid


def jump_onsets(ts, p, usd, J=0.04, short_w=10, long_w=60):
    """Times of jump onsets: same detector as H1, onset = first print of the short window."""
    pv, v = np.cumsum(p * usd), np.cumsum(usd)
    on, last = [], -1e18
    for i in range(len(ts)):
        now = ts[i]
        if now - last < long_w:
            continue
        a = np.searchsorted(ts, now - short_w, "left")
        b = np.searchsorted(ts, now - short_w - long_w, "left")
        if a <= b or a > i:
            continue
        s1 = pv[i] - (pv[a - 1] if a else 0); w1 = v[i] - (v[a - 1] if a else 0)
        s2 = (pv[a - 1] if a else 0) - (pv[b - 1] if b else 0); w2 = (v[a - 1] if a else 0) - (v[b - 1] if b else 0)
        if w1 <= 0 or w2 <= 0:
            continue
        d = s1 / w1 - s2 / w2
        if abs(d) >= J:
            last = now
            on.append((ts[a], np.sign(d), abs(d), now))  # onset, direction, size, detection time
    return on


def match_prints(row, J=0.04) -> pd.DataFrame | None:
    t = load_tape(row.cond)
    if t is None:
        return None
    t = in_play(t, row).reset_index(drop=True)
    if len(t) < 20:
        return None
    ts = t.timestamp.to_numpy().astype(float)
    p = t.p0.to_numpy()
    at_ask = t.at_ask.to_numpy()
    usd = t.usd.to_numpy()
    mid, spread = _mid_series(ts, p, at_ask)
    on = jump_onsets(ts, p, usd, J)
    on_t = np.array([o[0] for o in on]) if on else np.array([])
    on_d = np.array([o[1] for o in on]) if on else np.array([])
    k = np.searchsorted(on_t, ts, "right") - 1
    since = np.where(k >= 0, ts - on_t[np.maximum(k, 0)], -1.0)
    jdir = np.where(k >= 0, on_d[np.maximum(k, 0)], 0.0)
    d = np.where(at_ask, 1.0, -1.0)  # taker direction on outcome 0
    out = {"cond": row.cond, "ts": ts, "p": p, "dir": d, "usd": usd, "wallet": t.proxyWallet.to_numpy(),
           "since": since, "with_jump": d * jdir, "spread": spread,
           "fee_rate": row.fee_rate, "delay": row.delay, "res": row.res0}
    for h in HORIZONS:
        j = np.searchsorted(ts, ts + h, "left")
        valid = j < len(ts)
        m_h = np.where(valid, mid[np.minimum(j, len(ts) - 1)], np.nan)
        out[f"mo{h}"] = d * (m_h - p)
    out["mo_res"] = d * (row.res0 - p) if row.res0 in (0.0, 1.0) else np.full(len(ts), np.nan)
    df = pd.DataFrame(out)
    df["bucket"] = pd.cut(df.since, [b[0] for b in BUCKETS] + [1e9], labels=LABELS, right=False)
    return df
