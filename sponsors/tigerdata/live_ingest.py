"""Stream live tennis order books and wallet-level trades from Polymarket into Tiger Data. Read-only.

    python sponsors/tigerdata/live_ingest.py --minutes 60          # stream into Tiger Data
    python sponsors/tigerdata/live_ingest.py --minutes 2 --dry-run # no database: parse and count only

Three loops on one asyncio clock:
  market  public CLOB websocket for every moneyline of a tennis match starting within +-3 h:
          book snapshots, level changes (with best bid/ask) and trades -> in-memory buffers
  flush   every 250 ms, COPY the buffers into book_updates / trades and record how long each tick
          took from the exchange's timestamp to a committed row (ingest_lag)
  wallets every 5 s, for the matches that are moving, poll the public Data API for trades with the wallet
          that made them -> wallet_trades. Inside Tiger Data a scheduled job finds the points, and the
          markouts / who_gets_paid / fast_tier views score every wallet's trade live.
Nothing here signs or sends an order. The connection string is read from .env and never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
import websockets

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ingest import COLS, db_url, utc  # noqa: E402

GAMMA = "https://gamma-api.polymarket.com/events"
MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
DATA_TRADES = "https://data-api.polymarket.com/trades"
WINDOW_H = 3.0          # matches starting within +-3 h of now
WALLET_EVERY_S = 5.0
ACTIVE_S = 120          # a match is "moving" if its book changed in the last 2 minutes
MAX_CONCURRENT = 4      # Data API etiquette
FLUSH_S = 0.25          # COPY to Tiger Data four times a second


def discover(window_h: float = WINDOW_H) -> dict[str, dict]:
    """Moneyline outcome tokens of tennis events starting within +-window_h of now."""
    out, now = {}, time.time()
    for offset in range(0, 1000, 200):
        evs = requests.get(GAMMA, params={"tag_slug": "tennis", "active": "true", "closed": "false",
                                          "limit": 200, "offset": offset}, timeout=30).json()
        if not evs:
            break
        for e in evs:
            st = e.get("startTime")
            if not st:
                continue
            start = datetime.fromisoformat(st.replace("Z", "+00:00"))
            if abs(start.timestamp() - now) > window_h * 3600:
                continue
            for m in e.get("markets", []):
                if m.get("sportsMarketType") != "moneyline" or m.get("closed"):
                    continue
                for tok, outcome in zip(json.loads(m.get("clobTokenIds") or "[]"), json.loads(m["outcomes"])):
                    out[tok] = {"cond": m["conditionId"], "slug": e["slug"], "title": e.get("title"),
                                "outcome": outcome, "start": start}
    return out


class State:
    def __init__(self):
        self.book: list[tuple] = []
        self.trades: list[tuple] = []
        self.tokens: dict[str, dict] = {}
        self.new_markets: list[tuple] = []
        self.last_move: dict[str, float] = {}       # condition id -> last book change (wall s)
        self.counts = defaultdict(int)


def parse(st: State, it: dict, rt: datetime) -> None:
    ev = it.get("event_type")
    if ev == "book":
        a, m, ts = it["asset_id"], it["market"], utc(int(it["timestamp"]))
        bids = [(float(x["price"]), float(x["size"])) for x in it.get("bids", [])]
        asks = [(float(x["price"]), float(x["size"])) for x in it.get("asks", [])]
        bb, ba = max((p for p, _ in bids), default=None), min((p for p, _ in asks), default=None)
        st.book += [(ts, rt, a, m, "bid", p, s, "snapshot", bb, ba) for p, s in bids]
        st.book += [(ts, rt, a, m, "ask", p, s, "snapshot", bb, ba) for p, s in asks]
        st.counts["snapshots"] += 1
    elif ev == "price_change":
        m, ts = it["market"], utc(int(it["timestamp"]))
        for c in it.get("price_changes", []):
            st.book.append((ts, rt, c["asset_id"], m, "bid" if c["side"] == "BUY" else "ask", float(c["price"]),
                            float(c["size"]), "change", _f(c.get("best_bid")), _f(c.get("best_ask"))))
        st.last_move[m] = time.time()
        st.counts["changes"] += 1
    elif ev == "last_trade_price":
        st.trades.append((utc(int(it["timestamp"])), rt, it["asset_id"], it["market"], float(it["price"]),
                          float(it["size"]), it.get("side"), "live"))
        st.counts["trades"] += 1


def _f(x):
    return float(x) if x not in (None, "") else None


async def market_loop(st: State, stop: float) -> None:
    while time.time() < stop:
        try:
            async with websockets.connect(MARKET_WS, ping_interval=None, max_size=None) as ws:
                subscribed, last_disc, last_ping = set(), 0.0, time.time()
                while time.time() < stop:
                    if time.time() - last_disc > 300:
                        found = await asyncio.to_thread(discover)
                        new = [t for t in found if t not in subscribed]
                        if new:
                            await ws.send(json.dumps({"assets_ids": new, "type": "market", "operation": "subscribe",
                                                      "custom_feature_enabled": True}))
                            subscribed.update(new)
                            for t in new:
                                v = found[t]
                                st.tokens[t] = v
                                st.new_markets.append((t, v["cond"], v["slug"], v["title"], v["outcome"],
                                                       "moneyline", v["start"], None, "live"))
                            print(f"subscribed to {len(new)} tokens ({len(subscribed)} total)", flush=True)
                        last_disc = time.time()
                    if time.time() - last_ping > 9:
                        await ws.send("PING")
                        last_ping = time.time()
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    if msg == "PONG":
                        continue
                    rt = datetime.now(timezone.utc)
                    try:
                        d = json.loads(msg)
                    except ValueError:
                        continue
                    for it in d if isinstance(d, list) else [d]:
                        parse(st, it, rt)
        except Exception as ex:  # reconnect on any drop
            print("market websocket:", repr(ex), flush=True)
            await asyncio.sleep(2)


def lag_ms(rows: list[tuple], committed: datetime) -> tuple[float, float]:
    lags = sorted((committed - r[0]).total_seconds() * 1e3 for r in rows)
    return statistics.median(lags), lags[min(len(lags) - 1, int(0.99 * len(lags)))]


async def flush_loop(st: State, stop: float, conn) -> None:
    last_print = time.time()
    while time.time() < stop + 1:
        await asyncio.sleep(FLUSH_S)
        book, trades, mk = st.book, st.trades, st.new_markets
        st.book, st.trades, st.new_markets = [], [], []
        if conn is not None:
            async with conn.cursor() as cur:
                if mk:
                    await cur.executemany(f"INSERT INTO courtside.markets ({COLS['markets']}) "
                                          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", mk)
                for table, rows in (("book_updates", book), ("trades", trades)):
                    if rows:
                        async with cur.copy(f"COPY courtside.{table} ({COLS[table]}) FROM STDIN") as cp:
                            for r in rows:
                                await cp.write_row(r)
                committed = datetime.now(timezone.utc)
                lag_rows = [(committed, s, len(r), *lag_ms(r, committed)) for s, r in (("book", book), ("trade", trades)) if r]
                if lag_rows:
                    await cur.executemany("INSERT INTO courtside.ingest_lag (ts, stream, n, p50_ms, p99_ms) "
                                          "VALUES (%s,%s,%s,%s,%s)", lag_rows)
        st.counts["book_rows"] += len(book)
        st.counts["trade_rows"] += len(trades)
        if time.time() - last_print > 10:
            lag = f", exchange->row p50 {lag_ms(book, datetime.now(timezone.utc))[0]:.0f} ms" if book else ""
            print(f"{datetime.now():%H:%M:%S} rows: book {st.counts['book_rows']:,}, trades {st.counts['trade_rows']:,}, "
                  f"wallet trades {st.counts['wallet_rows']:,}; moving matches {len(moving(st))}{lag}", flush=True)
            last_print = time.time()


def moving(st: State) -> list[str]:
    return [c for c, t in st.last_move.items() if time.time() - t < ACTIVE_S]


def fetch_trades(cond: str) -> list[dict]:
    """Recent trades for one match; [] on rate limits or network errors (the next poll catches up)."""
    for wait in (0, 2, 5):
        time.sleep(wait)
        try:
            r = requests.get(DATA_TRADES, params={"market": cond, "limit": 200}, timeout=20)
        except requests.RequestException:
            continue
        if r.status_code != 429:
            return r.json() if r.ok else []
    return []


async def wallet_loop(st: State, stop: float, conn) -> None:
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def one(cond: str) -> list[tuple]:
        async with sem:
            got = await asyncio.to_thread(fetch_trades, cond)
        return [(utc(int(t["timestamp"]) * 1000), t["asset"], t["conditionId"], t["proxyWallet"], t["side"],
                 float(t["price"]), float(t["size"]), t["transactionHash"]) for t in got]

    while time.time() < stop:
        await asyncio.sleep(WALLET_EVERY_S)
        conds = moving(st)
        if not conds:
            continue
        try:
            rows = [r for part in await asyncio.gather(*(one(c) for c in conds)) for r in part]
        except Exception as ex:  # never let one bad poll stop the stream
            print("wallet poll:", repr(ex)[:200], flush=True)
            continue
        if conn is not None and rows:
            async with conn.cursor() as cur:
                before = (await (await cur.execute("SELECT count(*) FROM courtside.wallet_trades")).fetchone())[0]
                await cur.executemany(f"INSERT INTO courtside.wallet_trades (ts, asset_id, market, wallet, side, price, size, tx) "
                                      "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
                after = (await (await cur.execute("SELECT count(*) FROM courtside.wallet_trades")).fetchone())[0]
            st.counts["wallet_rows"] += after - before
        else:
            st.counts["wallet_rows"] = len({r[-1] + r[3] for r in rows}) if rows else st.counts["wallet_rows"]


async def main(minutes: float, dry_run: bool) -> None:
    stop = time.time() + minutes * 60
    st = State()
    conn = wconn = None
    if not dry_run:
        import psycopg
        conn = await psycopg.AsyncConnection.connect(db_url(), autocommit=True)
        wconn = await psycopg.AsyncConnection.connect(db_url(), autocommit=True)
    print(f"streaming for {minutes:g} min{' (dry run, no database)' if dry_run else ' into Tiger Data'}", flush=True)
    await asyncio.gather(market_loop(st, stop), flush_loop(st, stop, conn), wallet_loop(st, stop, wconn))
    for c in (conn, wconn):
        if c is not None:
            await c.close()
    print(f"done: {dict(st.counts)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--dry-run", action="store_true", help="parse and count only; no database")
    a = ap.parse_args()
    asyncio.run(main(a.minutes, a.dry_run))
