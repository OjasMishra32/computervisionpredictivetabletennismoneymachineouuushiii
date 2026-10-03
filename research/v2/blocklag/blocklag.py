"""How far do Polymarket's data-api trade timestamps (block time) lag the real match time?

Joins live CLOB websocket trades (last_trade_price: matching-engine ms timestamp + tx hash)
to the data-api trade records (block timestamp, seconds) by transaction hash, for today's
tennis moneylines. Forward data, used only to measure a latency; no rule is tuned on it.
"""
import glob, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import requests

meta = {}
for f in sorted(glob.glob("data/live/tokens_*.jsonl")):
    for line in open(f):
        meta.update(json.loads(line)["tokens"])
ws = []
f = sorted(glob.glob("data/live/market_*.jsonl"))[-1]
with open(f) as fh:
    for line in fh:
        if '"last_trade_price"' not in line:
            continue
        m = json.loads(line)
        if meta.get(m.get("asset_id"), {}).get("tag") != "tennis":
            continue
        ws.append({"tx": m.get("transaction_hash"), "ws_ms": int(m["timestamp"]), "rt": m["rt"],
                   "cond": meta[m["asset_id"]]["cond"]})
ws = pd.DataFrame(ws).dropna()
conds = ws.cond.value_counts().index[:25]
rows = []
for c in conds:
    r = requests.get("https://data-api.polymarket.com/trades", params={"market": c, "limit": 500}, timeout=30).json()
    rows += [{"tx": t["transactionHash"], "api_s": t["timestamp"]} for t in r]
api = pd.DataFrame(rows).drop_duplicates("tx")
j = ws.merge(api, on="tx")
j["lag_s"] = j.api_s - j.ws_ms / 1000
print("matched trades", len(j), "of", len(ws[ws.cond.isin(conds)]))
print(j.lag_s.describe(percentiles=[.1, .25, .5, .75, .9]).round(3))
Path("research/v2/blocklag/results.json").write_text(json.dumps(
    {"n": int(len(j)), "median_lag_s": float(j.lag_s.median()), "p10": float(j.lag_s.quantile(.1)),
     "p90": float(j.lag_s.quantile(.9))}, indent=2))
