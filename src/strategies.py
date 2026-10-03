"""H1 (staircase follow) and H2 (late favorite band) on real trade tapes.

Fills are taken only at prints on the side of the book we would hit: buying outcome 0
needs a print that lifted outcome 0's ask, buying outcome 1 needs a print that hit
outcome 0's bid (ask1 = 1 - bid0). Entry is at the first such print at or after
signal + venue delay + 1 s of our own latency. Every leg pays that match's taker fee.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.tape import in_play, load_tape, taker_fee

OUR_LATENCY_S = 1
FILL_WINDOW_S = 10          # no qualifying print within this window -> no trade
MAX_USD_PER_TRADE = 1_000
PRINT_SHARE = 0.5           # take at most half of the print we are matched against


def _first(t: pd.DataFrame, t0: int, at_ask: bool, window: int | None):
    m = (t.timestamp.to_numpy() >= t0) & (t.at_ask.to_numpy() == at_ask)
    if window is not None:
        m &= t.timestamp.to_numpy() <= t0 + window
    idx = np.flatnonzero(m)
    return None if len(idx) == 0 else t.iloc[idx[0]]


def _size(price: float, print_size: float) -> float:
    return float(min(MAX_USD_PER_TRADE / price, PRINT_SHARE * print_size))


def h1_trades(row, J: float = 0.04, H: int = 30, short_w: int = 10, long_w: int = 60) -> list[dict]:
    t = load_tape(row.cond)
    if t is None:
        return []
    t = in_play(t, row).reset_index(drop=True)
    if len(t) < 20:
        return []
    ts, p, usd = t.timestamp.to_numpy(), t.p0.to_numpy(), t.usd.to_numpy()
    out, last_sig = [], -10**12
    pv = np.cumsum(p * usd)
    v = np.cumsum(usd)
    for i in range(len(t)):
        now = ts[i]
        if now - last_sig < long_w:
            continue
        a = np.searchsorted(ts, now - short_w, "left")
        b = np.searchsorted(ts, now - short_w - long_w, "left")
        if a <= b or a > i:
            continue
        vw_s = (pv[i] - (pv[a - 1] if a else 0)) / max(v[i] - (v[a - 1] if a else 0), 1e-9)
        vw_l = ((pv[a - 1] if a else 0) - (pv[b - 1] if b else 0)) / max((v[a - 1] if a else 0) - (v[b - 1] if b else 0), 1e-9)
        d = vw_s - vw_l
        if abs(d) < J:
            continue
        last_sig = now
        up = d > 0
        t_e = now + int(row.delay) + OUR_LATENCY_S
        ent = _first(t, t_e, at_ask=up, window=FILL_WINDOW_S)
        if ent is None:
            continue
        px_in = ent.p0 if up else 1 - ent.p0           # price paid for the token we buy
        ex = _first(t, int(ent.timestamp) + H, at_ask=not up, window=None)
        if ex is None:                                  # nothing to sell into: ride to resolution
            px_out, fee_out, held = (row.res0 if up else 1 - row.res0), 0.0, "resolution"
        else:
            px_out = ex.p0 if up else 1 - ex.p0
            fee_out, held = taker_fee(px_out, row.fee_rate), "tape"
        fee_in = taker_fee(px_in, row.fee_rate)
        out.append({"cond": row.cond, "ts": int(ent.timestamp), "signal_ts": int(now), "dir": 1 if up else -1,
                    "jump": float(d), "px_in": float(px_in), "px_out": float(px_out),
                    "fee": float(fee_in + fee_out), "pnl_ps": float(px_out - px_in - fee_in - fee_out),
                    "shares": _size(px_in, ent["size"]), "exit": held})
    return out


def h2_trades(row, lo: float = 0.85, hi: float = 0.97) -> list[dict]:
    """First in-play entry of either player into the [lo, hi] favourite band from below."""
    if row.res0 not in (0.0, 0.5, 1.0):
        return []
    t = load_tape(row.cond)
    if t is None:
        return []
    t = in_play(t, row).reset_index(drop=True)
    if len(t) < 10:
        return []
    p = t.p0.to_numpy()
    fav = np.maximum(p, 1 - p)
    is0 = p >= 0.5
    below = np.maximum.accumulate(fav < lo)  # has been below the band at some point in play
    cand = np.flatnonzero(below & (fav >= lo) & (fav <= hi))
    if len(cand) == 0:
        return []
    i = cand[0]
    side0 = bool(is0[i])
    t_e = int(t.timestamp.iloc[i]) + int(row.delay) + OUR_LATENCY_S
    ent = _first(t, t_e, at_ask=side0, window=FILL_WINDOW_S)
    if ent is None:
        return []
    px_in = ent.p0 if side0 else 1 - ent.p0
    if px_in > hi + 0.01 or px_in < lo - 0.01:
        return []
    payout = row.res0 if side0 else 1 - row.res0
    fee = taker_fee(px_in, row.fee_rate)
    return [{"cond": row.cond, "ts": int(ent.timestamp), "signal_ts": int(t.timestamp.iloc[i]),
             "dir": 1 if side0 else -1, "px_in": float(px_in), "px_out": float(payout), "fee": float(fee),
             "pnl_ps": float(payout - px_in - fee), "shares": _size(px_in, ent["size"]), "exit": "resolution"}]


MAKER_SHARE = 0.2
MAKER_MAX_PRINT_USD = 250
MAKER_MAX_MATCH_USD = 2_000
REBATE_SHARE = 0.15


def h5_fills(row, J: float = 0.04, W: int = 30, always_on: bool = False) -> list[dict]:
    """Maker fills: quote both sides from jump detection + 1 s to + W s (or all match if always_on).

    We take MAKER_SHARE of each taker print that lands in the window, on the other side of it,
    and hold to resolution. Maker P&L per share = (payout - price paid for the token we got).
    """
    from src.tiers import jump_onsets
    if row.res0 not in (0.0, 0.5, 1.0):
        return []
    t = load_tape(row.cond)
    if t is None:
        return []
    t = in_play(t, row).reset_index(drop=True)
    if len(t) < 20:
        return []
    ts = t.timestamp.to_numpy().astype(float)
    p, at_ask, size = t.p0.to_numpy(), t.at_ask.to_numpy(), t["size"].to_numpy()
    if always_on:
        live = np.ones(len(t), bool)
    else:
        det = np.array([o[3] for o in jump_onsets(ts, p, t.usd.to_numpy(), J)])
        live = np.zeros(len(t), bool)
        for d in det:
            live |= (ts >= d + OUR_LATENCY_S) & (ts <= d + W)
    out, gross = [], 0.0
    for i in np.flatnonzero(live):
        # taker lifted outcome 0's ask -> we sold outcome 0 = bought outcome 1 at 1 - p
        long0 = not at_ask[i]
        px = p[i] if long0 else 1 - p[i]
        if px <= 0.005 or px >= 0.995:
            continue
        sh = min(MAKER_SHARE * size[i], MAKER_MAX_PRINT_USD / px)
        if gross + sh * px > MAKER_MAX_MATCH_USD:
            break
        gross += sh * px
        payout = row.res0 if long0 else 1 - row.res0
        rebate = REBATE_SHARE * taker_fee(p[i], row.fee_rate)
        out.append({"cond": row.cond, "ts": int(ts[i]), "dir": 1 if long0 else -1, "px_in": float(px),
                    "px_out": float(payout), "fee": float(-rebate),
                    "pnl_ps": float(payout - px + rebate), "shares": float(sh), "exit": "resolution"})
    return out
