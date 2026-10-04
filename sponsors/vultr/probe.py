"""Read-only Polymarket feed/REST latency probe for the COURTSIDE Vultr experiment."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websockets

GAMMA = "https://gamma-api.polymarket.com/events"
MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
CLOB_TIME = "https://clob.polymarket.com/time"


def now_ns() -> int:
    return time.time_ns()


def discover_tennis_tokens(window_hours: float = 8.0) -> dict[str, dict]:
    """Discover active tennis moneyline tokens close enough to receive live updates."""
    found: dict[str, dict] = {}
    now = datetime.now(timezone.utc).timestamp()
    for offset in range(0, 1000, 200):
        response = requests.get(GAMMA, params={"tag_slug": "tennis", "active": "true", "closed": "false",
                                                "limit": 200, "offset": offset}, timeout=30)
        response.raise_for_status()
        events = response.json()
        if not events:
            break
        for event in events:
            start = event.get("startTime")
            if not start:
                continue
            start_ts = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()
            if abs(start_ts - now) > window_hours * 3600:
                continue
            for market in event.get("markets", []):
                if market.get("sportsMarketType") != "moneyline" or market.get("closed"):
                    continue
                tokens = json.loads(market.get("clobTokenIds") or "[]")
                outcomes = json.loads(market.get("outcomes") or "[]")
                for index, token in enumerate(tokens):
                    found[str(token)] = {
                        "event": event.get("slug"), "condition_id": market.get("conditionId"),
                        "outcome": outcomes[index] if index < len(outcomes) else str(index),
                    }
    return found


def clock_tracking() -> dict:
    """Capture chrony's local-minus-NTP clock estimate; retain raw proof for audit."""
    try:
        proc = subprocess.run(["chronyc", "tracking"], text=True, capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        proc = None
    if proc is None:
        try:
            sntp = subprocess.run(["sntp", "-t", "5", "time.cloudflare.com"], text=True,
                                  capture_output=True, timeout=10)
            raw = (sntp.stdout or sntp.stderr).strip()
            match = re.search(r"^([+-]?[0-9.]+)\s+\+/-\s+([0-9.]+)", raw)
            if match:
                # sntp reports the correction to add to local time, so invert it for local-minus-NTP.
                return {"source": "sntp", "local_minus_ntp_ms": -float(match.group(1)) * 1000,
                        "uncertainty_ms": float(match.group(2)) * 1000, "raw": raw}
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        return {"source": "unavailable", "local_minus_ntp_ms": None, "raw": ""}
    raw = proc.stdout.strip()
    match = re.search(r"System time\s*:\s*([+-]?[0-9.]+) seconds (fast|slow) of NTP time", raw)
    offset = None
    if match:
        magnitude = float(match.group(1)) * 1000
        offset = magnitude if match.group(2) == "fast" else -magnitude
    return {"source": "chronyc", "local_minus_ntp_ms": offset, "raw": raw}


def normalize_server_ms(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1e15:
        return number / 1e6
    if number < 1e11:
        return number * 1000
    return number


class JsonlSink:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("w", buffering=1)

    def write(self, row: dict) -> None:
        self.file.write(json.dumps(row, separators=(",", ":")) + "\n")

    def close(self) -> None:
        self.file.close()


async def rest_loop(site: str, sink: JsonlSink, stop: float, interval: float) -> None:
    while time.monotonic() < stop:
        start_wall, start_mono = now_ns(), time.perf_counter_ns()
        try:
            response = await asyncio.to_thread(requests.get, CLOB_TIME, timeout=10)
            end_mono, end_wall = time.perf_counter_ns(), now_ns()
            response.raise_for_status()
            sink.write({"type": "rest", "site": site, "recv_wall_ns": end_wall,
                        "rtt_ms": (end_mono - start_mono) / 1e6,
                        "server_time": response.text.strip()[:100], "status": response.status_code})
        except Exception as exc:
            sink.write({"type": "error", "site": site, "at_wall_ns": start_wall,
                        "source": "rest", "error": type(exc).__name__})
        await asyncio.sleep(max(0.0, interval - (time.perf_counter_ns() - start_mono) / 1e9))


async def websocket_loop(site: str, sink: JsonlSink, stop: float, tokens: dict[str, dict],
                         local_minus_ntp_ms: float | None) -> None:
    token_ids = list(tokens)
    while time.monotonic() < stop:
        try:
            async with websockets.connect(MARKET_WS, ping_interval=None, max_size=None, open_timeout=20) as ws:
                await ws.send(json.dumps({"assets_ids": token_ids, "type": "market",
                                          "operation": "subscribe", "custom_feature_enabled": True}))
                last_ping = time.monotonic()
                while time.monotonic() < stop:
                    if time.monotonic() - last_ping > 9:
                        await ws.send("PING")
                        last_ping = time.monotonic()
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=3)
                    except asyncio.TimeoutError:
                        continue
                    receive_wall_ns, receive_mono_ns = now_ns(), time.perf_counter_ns()
                    if message == "PONG":
                        continue
                    try:
                        decoded = json.loads(message)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    for event in decoded if isinstance(decoded, list) else [decoded]:
                        if not isinstance(event, dict) or event.get("event_type") == "new_market":
                            continue
                        server_ms = normalize_server_ms(event.get("timestamp"))
                        raw_delay = receive_wall_ns / 1e6 - server_ms if server_ms is not None else None
                        adjusted = (raw_delay - local_minus_ntp_ms
                                    if raw_delay is not None and local_minus_ntp_ms is not None else raw_delay)
                        sink.write({"type": "ws", "site": site, "recv_wall_ns": receive_wall_ns,
                                    "recv_mono_ns": receive_mono_ns, "server_ts_ms": server_ms,
                                    "feed_delay_ms": adjusted, "feed_delay_raw_ms": raw_delay,
                                    "clock_local_minus_ntp_ms": local_minus_ntp_ms,
                                    "event_type": event.get("event_type"),
                                    "asset_id": event.get("asset_id") or event.get("market")})
        except Exception as exc:
            sink.write({"type": "error", "site": site, "at_wall_ns": now_ns(),
                        "source": "websocket", "error": type(exc).__name__})
            await asyncio.sleep(2)


async def run(site: str, minutes: float, output: Path, rest_interval: float,
              token_file: Path | None = None) -> None:
    sink = JsonlSink(output)
    clock_start = clock_tracking()
    try:
        tokens = (json.loads(token_file.read_text()) if token_file
                  else await asyncio.to_thread(discover_tennis_tokens))
        if not tokens:
            raise RuntimeError("no active tennis moneyline tokens found within the discovery window")
        sink.write({"type": "meta", "phase": "start", "site": site,
                    "at": datetime.now(timezone.utc).isoformat(), "duration_minutes": minutes,
                    "token_count": len(tokens), "clock": clock_start})
        stop = time.monotonic() + minutes * 60
        await asyncio.gather(
            websocket_loop(site, sink, stop, tokens, clock_start["local_minus_ntp_ms"]),
            rest_loop(site, sink, stop, rest_interval),
        )
        sink.write({"type": "meta", "phase": "end", "site": site,
                    "at": datetime.now(timezone.utc).isoformat(), "clock": clock_tracking()})
    finally:
        sink.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True)
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--rest-interval", type=float, default=2)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--tokens-file", type=Path,
                        help="frozen token manifest shared by both experimental sites")
    args = parser.parse_args()
    output = args.out or Path(__file__).parent / "out" / f"probe_{args.site}.jsonl"
    asyncio.run(run(args.site, args.minutes, output, args.rest_interval, args.tokens_file))


if __name__ == "__main__":
    main()
