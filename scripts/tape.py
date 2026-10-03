"""Live trading tape in the terminal: every Polymarket tennis price move, with point calls.

    .venv/bin/python scripts/tape.py

Read-only (public websocket). A point is called when a player's win probability moves >= 2c within 3 s.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque

import requests
import websockets

GAMMA = "https://gamma-api.polymarket.com/events"
WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
R, G, Y, B, D, X, INV = "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[2m", "\033[0m", "\033[1;97;41m"
JUMP, WIN_MS, COOL_MS = 0.02, 3000, 6000


def short(name: str) -> str:
    parts = (name or "").split()
    return (parts[-1] if parts else "?")[:12]


def discover() -> dict:
    now, out = time.time(), {}
    for off in (0, 200, 400):
        try:
            evs = requests.get(GAMMA, params={"tag_slug": "tennis", "active": "true", "closed": "false",
                                              "limit": 200, "offset": off}, timeout=20).json()
        except Exception:
            break
        if not evs:
            break
        for e in evs:
            try:
                st = time.mktime(time.strptime(e.get("startTime", "")[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
            except ValueError:
                st = 0
            if e.get("ended") or not (e.get("live") or (now - 5 * 3600 < st < now + 600)):
                continue
            mk = next((m for m in e.get("markets", []) if m.get("sportsMarketType") == "moneyline" and not m.get("closed")), None)
            if not mk:
                continue
            toks, outs = json.loads(mk.get("clobTokenIds") or "[]"), json.loads(mk.get("outcomes") or "[]")
            if len(toks) == 2:
                lg = (e.get("eventMetadata") or {}).get("league") or e.get("seriesSlug") or ""
                m = {"p0": outs[0], "p1": outs[1], "league": lg, "hist": deque(), "last": None, "ev": 0}
                out[toks[0]] = (m, 0)
                out[toks[1]] = (m, 1)
    return out


async def main():
    toks = discover()
    matches = {id(m): m for m, _ in toks.values()}
    print(f"{B}COURTSIDE tape{X}  {len(matches)} live tennis matches, {len(toks)} tokens  {D}(read-only; Ctrl-C to stop){X}")
    for m in matches.values():
        print(f"  {D}{m['league'][:28]:28}{X} {m['p0']} v {m['p1']}")
    n, lat, t_hdr, calls = 0, deque(maxlen=300), time.time(), 0
    async with websockets.connect(WS, ping_interval=None, max_size=None) as ws:
        await ws.send(json.dumps({"assets_ids": list(toks), "type": "market", "custom_feature_enabled": True}))
        last_ping = time.time()
        while True:
            if time.time() - last_ping > 9:
                await ws.send("PING"); last_ping = time.time()
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if raw == "PONG":
                continue
            now_ms = int(time.time() * 1000)
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            for it in d if isinstance(d, list) else [d]:
                if not isinstance(it, dict):
                    continue
                n += 1
                if it.get("timestamp"):
                    lat.append(now_ms - int(it["timestamp"]))
                ev, tok = it.get("event_type"), it.get("asset_id")
                if tok not in toks:
                    continue
                m, side = toks[tok]
                ts = int(it.get("timestamp") or now_ms)
                stamp = time.strftime("%H:%M:%S", time.localtime(ts / 1000)) + f".{ts % 1000:03d}"
                name = f"{short(m['p0'])} v {short(m['p1'])}"
                if ev == "last_trade_price":
                    px = float(it["price"]); p0 = px if side == 0 else 1 - px
                    buy0 = (it.get("side") == "BUY") == (side == 0)
                    col = G if buy0 else R
                    usd = float(it.get("size", 0)) * px
                    print(f"{D}{stamp}{X}  {name:26} {col}TRADE {'▲' if buy0 else '▼'} {short(m['p0'])} {p0*100:5.1f}%{X}  ${usd:,.0f}")
                    continue
                if ev != "best_bid_ask":
                    continue
                bid, ask = float(it.get("best_bid") or 0), float(it.get("best_ask") or 0)
                if not (ask > 0 and ask - bid <= 0.05):
                    continue
                mid = (bid + ask) / 2
                p0 = mid if side == 0 else 1 - mid
                h = m["hist"]
                h.append((ts, p0))
                while h and ts - h[0][0] > WIN_MS:
                    h.popleft()
                prev = m["last"]
                m["last"] = p0
                if prev is not None and abs(p0 - prev) >= 0.002:
                    col = G if p0 > prev else R
                    print(f"{D}{stamp}{X}  {name:26} {col}{short(m['p0'])} {p0*100:5.1f}% ({(p0-prev)*100:+.1f}){X}  {D}bid {bid:.3f} ask {ask:.3f}{X}")
                lo, hi = min(x for _, x in h), max(x for _, x in h)
                if ts - m["ev"] > COOL_MS and (p0 - lo >= JUMP or hi - p0 >= JUMP):
                    m["ev"] = ts
                    calls += 1
                    up = p0 - lo >= JUMP
                    win = m["p0"] if up else m["p1"]
                    print(f"{INV} {stamp}  POINT CALLED → {win}  ({(p0 - lo if up else hi - p0)*100:.1f}¢ in <3 s)  {name} {X}")
            if time.time() - t_hdr > 30:
                t_hdr = time.time()
                med = sorted(lat)[len(lat) // 2] if lat else 0
                print(f"{Y}── {time.strftime('%H:%M:%S')}  {n} msgs/30s  feed latency {med} ms  points called {calls} ──{X}")
                n = 0


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
