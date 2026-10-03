"""Do passive exits actually fill? Measured on today's live tennis order books (forward data).

After each live moneyline jump (mid moves >= J within 10 s), assume we hold the side that
gained, from t = jump + 1 s (our delayed taker entry). We rest a SELL of that token either
(a) one tick inside the current ask (alone at a new level, queue ahead = 0), or
(b) at the current ask, behind the visible size there (queue ahead = Q; no cancels ahead).
Filled when takers trade through our price: a BUY of this token at >= our price, or a SELL
of the twin token at <= 1 - our price (Polymarket matches complementary orders). In (b) the
traded size at our price must first exhaust Q. Reports fill rate by timeout and the exit
price relative to the entry-time mid. Streams the recording; never sends an order.

    .venv/bin/python research/v2/livefill/livefill.py
"""
from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

J = 0.03
FROM_MS, UNTIL_MS = 1791021780000, 1791030060000   # the published run: 2026-10-03 10:03-12:21 UTC
WIN_MS = 10_000
TIMEOUTS = (30, 60, 120, 300)
OUT = Path(__file__).parent


def tennis_pairs():
    meta = {}
    for f in sorted(glob.glob("data/live/tokens_*.jsonl")):
        for line in open(f):
            meta.update(json.loads(line)["tokens"])
    by_cond = defaultdict(list)
    for tok, m in meta.items():
        if m.get("tag") == "tennis":
            by_cond[m["cond"]].append(tok)
    twin = {}
    for toks in by_cond.values():
        if len(toks) == 2:
            twin[toks[0]], twin[toks[1]] = toks[1], toks[0]
    return twin


def main():
    twin = tennis_pairs()
    books = defaultdict(lambda: {"b": {}, "a": {}})
    mids = defaultdict(list)        # token -> [(ts, mid)] rolling 10 s window
    hist = defaultdict(list)        # token -> full (ts, mid) history for markouts
    orders = []                     # open simulated orders
    done = []
    last_sig = {}
    import gzip

    def lines():  # plain and gzipped recordings in time order; a truncated gzip ends cleanly
        for f in sorted(glob.glob("data/live/market_*.jsonl*")):
            with (gzip.open(f, "rt") if f.endswith(".gz") else open(f)) as fh:
                try:
                    yield from fh
                except EOFError:
                    pass
    if True:
        for line in lines():
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            e = m.get("event_type")
            if e not in ("book", "price_change", "last_trade_price"):
                continue
            ts = int(m.get("timestamp") or 0)
            if ts < FROM_MS or ts > UNTIL_MS:
                continue
            if e == "book":
                a = m["asset_id"]
                if a not in twin:
                    continue
                books[a]["b"] = {float(x["price"]): float(x["size"]) for x in m.get("bids", []) if float(x["size"]) > 0}
                books[a]["a"] = {float(x["price"]): float(x["size"]) for x in m.get("asks", []) if float(x["size"]) > 0}
                touched = [a]
            elif e == "price_change":
                touched = []
                for c in m.get("price_changes", []):
                    a = c["asset_id"]
                    if a not in twin:
                        continue
                    side = books[a]["b"] if c["side"] == "BUY" else books[a]["a"]
                    px, sz = float(c["price"]), float(c["size"])
                    if sz <= 0:
                        side.pop(px, None)
                    else:
                        side[px] = sz
                    touched.append(a)
            else:  # trade: advance simulated passive orders
                a = m["asset_id"]
                if a not in twin:
                    continue
                px, sz, side = float(m["price"]), float(m["size"]), m.get("side")
                for o in orders:
                    if o["filled"] or ts < o["t0"]:
                        continue
                    hit = (a == o["tok"] and side == "BUY" and px >= o["px"] - 1e-9) or \
                          (a == twin[o["tok"]] and side == "SELL" and px <= 1 - o["px"] + 1e-9)
                    if hit:
                        o["through"] += sz
                        if o["through"] > o["queue"]:
                            o["filled"], o["t_fill"] = True, ts
                continue
            for a in set(touched):
                bk = books[a]
                if not bk["b"] or not bk["a"]:
                    continue
                bb, ba = max(bk["b"]), min(bk["a"])
                if ba - bb > 0.05:
                    continue
                mid = (bb + ba) / 2
                ser = mids[a]
                ser.append((ts, mid))
                hist[a].append((ts, mid))
                while ser and ts - ser[0][0] > WIN_MS:
                    ser.pop(0)
                move = mid - ser[0][1]
                if move >= J and ts - last_sig.get(a, 0) > 60_000:   # this token just gained
                    last_sig[a] = ts
                    tick = 0.001 if min(ba, 1 - ba) < 0.1 else 0.01 if (round(ba * 100) == ba * 100 and ba - bb >= 0.01) else 0.001
                    t0 = ts + 1000
                    for mode in ("inside", "join"):
                        px = round(ba - tick, 3) if (mode == "inside" and ba - tick > bb + 1e-9) else ba
                        q = 0.0 if px < ba else bk["a"].get(ba, 0.0)
                        orders.append({"tok": a, "mode": mode, "t_sig": ts, "t0": t0, "px": px, "queue": q,
                                       "mid0": mid, "spread": ba - bb, "move": move, "through": 0.0,
                                       "filled": False, "t_fill": None})
    H = {a: (np.array([h[0] for h in v]), np.array([h[1] for h in v])) for a, v in hist.items()}

    def mid_at(tok, t):
        ts_, md = H[tok]
        i = np.searchsorted(ts_, t, "right") - 1
        return md[i] if i >= 0 else np.nan
    for o in orders:
        o["fill_s"] = (o["t_fill"] - o["t0"]) / 1000 if o["filled"] else np.nan
        # seller's markout 30 s after the fill: positive = price fell back after we sold (good for us)
        o["post_fill_30s_c"] = (o["px"] - mid_at(o["tok"], o["t_fill"] + 30_000)) * 100 if o["filled"] else np.nan
        # what holding would have done instead: mid drift from entry over 300 s
        o["drift_300s_c"] = (mid_at(o["tok"], o["t0"] + 300_000) - o["mid0"]) * 100
    df = pd.DataFrame(orders)
    df.to_csv(OUT / "orders.csv", index=False)
    rows = []
    for mode, g in df.groupby("mode"):
        r = {"mode": mode, "n": len(g), "median_queue_shares": float(g.queue.median()),
             "edge_vs_mid_c": float(((g.px - g.mid0) * 100).mean())}
        for T in TIMEOUTS:
            r[f"fill_{T}s"] = float((g.fill_s <= T).mean())
        r["post_fill_30s_c"] = float(g.post_fill_30s_c.mean())
        r["drift_300s_filled_c"] = float(g.loc[g.filled, "drift_300s_c"].mean())
        r["drift_300s_unfilled_c"] = float(g.loc[~g.filled, "drift_300s_c"].mean())
        rows.append(r)
    res = pd.DataFrame(rows)
    print(f"{df.t_sig.nunique()} live jumps on {df.tok.nunique()} tennis tokens")
    print(res.round(3).to_string(index=False))
    (OUT / "results.json").write_text(json.dumps({"jumps": int(df.t_sig.nunique()), "tokens": int(df.tok.nunique()),
                                                  "by_mode": res.round(4).to_dict("records")}, indent=2))


if __name__ == "__main__":
    main()
