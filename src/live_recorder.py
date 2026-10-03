"""Record Polymarket's live sports score feed and the CLOB order book side by side.

Two websockets, one clock. Every message is written with our local receive time
in ms, so a score change on the sports feed can be lined up against the first
book reprice on the market feed. Read-only: this never places an order.

    python -m src.live_recorder --hours 6
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import requests
import websockets

GAMMA = "https://gamma-api.polymarket.com/events"
SPORTS_WS = "wss://sports-api.polymarket.com/ws"
MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
TAGS = ("tennis", "table-tennis")
RACKET_LEAGUES = {"atp", "wta", "challenger", "itf", "tennis", "tt", "tabletennis", "table-tennis", "setka"}


def now_ms() -> int:
    return int(time.time() * 1000)


def live_markets(window_h: float = 6.0) -> dict[str, dict]:
    """Moneyline tokens for racket-sport events starting within +-window_h of now."""
    out: dict[str, dict] = {}
    t = time.time()
    for tag in TAGS:
        for offset in range(0, 1000, 200):
            r = requests.get(GAMMA, params={"tag_slug": tag, "active": "true", "closed": "false",
                                            "limit": 200, "offset": offset}, timeout=30)
            evs = r.json()
            if not evs:
                break
            for e in evs:
                st = e.get("startTime")
                if not st:
                    continue
                ts = time.mktime(time.strptime(st[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
                if abs(ts - t) > window_h * 3600:
                    continue
                for m in e.get("markets", []):
                    if m.get("sportsMarketType") != "moneyline" or m.get("closed"):
                        continue
                    toks = json.loads(m.get("clobTokenIds") or "[]")
                    for i, tok in enumerate(toks):
                        out[tok] = {"slug": e["slug"], "gameId": e.get("gameId"), "tag": tag,
                                    "outcome": json.loads(m["outcomes"])[i], "cond": m["conditionId"]}
    return out


class Sink:
    """Plain JSONL, line-buffered, so a crash never loses buffered records."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "a", buffering=1)

    def write(self, rec: dict) -> None:
        self.f.write(json.dumps(rec, separators=(",", ":")) + "\n")


async def sports_loop(sink: Sink, stop: float) -> None:
    while time.time() < stop:
        try:
            async with websockets.connect(SPORTS_WS, ping_interval=None, max_size=None) as ws:
                while time.time() < stop:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        continue
                    rt = now_ms()
                    if msg in ("ping", "PING"):
                        await ws.send("pong")
                        continue
                    try:
                        d = json.loads(msg)
                    except ValueError:
                        continue
                    for it in d if isinstance(d, list) else [d]:
                        if str(it.get("leagueAbbreviation", "")).lower() in RACKET_LEAGUES:
                            sink.write({"rt": rt, **it})
        except Exception as ex:  # reconnect on any drop
            sink.write({"rt": now_ms(), "error": repr(ex)})
            await asyncio.sleep(2)


async def market_loop(sink: Sink, meta_sink: Sink, stop: float) -> None:
    subscribed: set[str] = set()
    while time.time() < stop:
        try:
            async with websockets.connect(MARKET_WS, ping_interval=None, max_size=None) as ws:
                subscribed.clear()
                last_refresh = 0.0
                last_ping = time.time()
                while time.time() < stop:
                    if time.time() - last_refresh > 600:
                        mk = await asyncio.to_thread(live_markets)
                        new = [t for t in mk if t not in subscribed]
                        if new:
                            await ws.send(json.dumps({"assets_ids": new, "type": "market",
                                                      "operation": "subscribe",
                                                      "custom_feature_enabled": True}))
                            subscribed.update(new)
                            meta_sink.write({"rt": now_ms(), "tokens": {t: mk[t] for t in new}})
                        last_refresh = time.time()
                    if time.time() - last_ping > 9:
                        await ws.send("PING")
                        last_ping = time.time()
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    rt = now_ms()
                    if msg == "PONG":
                        continue
                    try:
                        d = json.loads(msg)
                    except ValueError:
                        continue
                    for it in d if isinstance(d, list) else [d]:
                        sink.write({"rt": rt, **it})
        except Exception as ex:
            sink.write({"rt": now_ms(), "error": repr(ex)})
            await asyncio.sleep(2)


async def main(hours: float, out: Path) -> None:
    stop = time.time() + hours * 3600
    day = time.strftime("%Y%m%d_%H%M", time.gmtime())
    sports = Sink(out / f"sports_{day}.jsonl")
    market = Sink(out / f"market_{day}.jsonl")
    meta = Sink(out / f"tokens_{day}.jsonl")
    await asyncio.gather(sports_loop(sports, stop), market_loop(market, meta, stop))
    for s in (sports, market, meta):
        s.f.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--out", type=Path, default=Path("data/live"))
    a = ap.parse_args()
    asyncio.run(main(a.hours, a.out))
