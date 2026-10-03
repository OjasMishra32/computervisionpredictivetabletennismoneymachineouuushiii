"""Summarise recorded live books: spreads, top-of-book and 2c depth, repricing rate, by sport."""
import collections, glob, gzip, json, sys
import numpy as np
import pandas as pd


def load():
    meta = {}
    for f in sorted(glob.glob("data/live/tokens_*.jsonl")):
        for line in open(f):
            meta.update(json.loads(line)["tokens"])
    msgs = []
    for f in sorted(glob.glob("data/live/market_*")):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt") as fh:
            try:
                for line in fh:
                    msgs.append(json.loads(line))
            except (EOFError, json.JSONDecodeError):
                pass
    return meta, msgs


if __name__ == "__main__":
    meta, msgs = load()
    tag = lambda a: meta.get(a, {}).get("tag", "?")
    rows = []
    for m in msgs:
        if m.get("event_type") != "book":
            continue
        bids = sorted(((float(x["price"]), float(x["size"])) for x in m.get("bids", [])), reverse=True)
        asks = sorted((float(x["price"]), float(x["size"])) for x in m.get("asks", []))
        if not bids or not asks:
            rows.append({"tag": tag(m["asset_id"]), "asset": m["asset_id"], "no_book": True}); continue
        bb, ba = bids[0][0], asks[0][0]
        rows.append({"tag": tag(m["asset_id"]), "asset": m["asset_id"], "no_book": False, "spread": ba - bb,
                     "top_usd": bb * bids[0][1] + ba * asks[0][1],
                     "depth2c_usd": sum(p * s for p, s in bids if p >= bb - 0.02) + sum(p * s for p, s in asks if p <= ba + 0.02)})
    df = pd.DataFrame(rows)
    print(df.groupby("tag").agg(books=("asset", "size"), assets=("asset", "nunique"), no_book=("no_book", "mean")).round(2))
    ok = df[df.no_book == False]
    print(ok.groupby("tag")[["spread", "top_usd", "depth2c_usd"]].median().round(3))
    bba = [m for m in msgs if m.get("event_type") == "best_bid_ask"]
    b = pd.DataFrame([{"tag": tag(m["asset_id"]), "asset": m["asset_id"], "rt": m["rt"],
                       "bid": float(m.get("best_bid") or 0), "ask": float(m.get("best_ask") or 0)} for m in bba])
    if len(b):
        span = (b.rt.max() - b.rt.min()) / 60000
        g = b.groupby(["tag", "asset"]).size().groupby("tag").median()
        print("minutes recorded", round(span, 1)); print("median best_bid_ask updates per asset:"); print(g)
    print(json.dumps(bba[0])[:300] if bba else "")
