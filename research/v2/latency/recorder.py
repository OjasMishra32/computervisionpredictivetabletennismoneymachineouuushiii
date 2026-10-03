"""Latency lens recorder: public tennis score sources + the Polymarket book, one local clock.

Every record carries "rt" = local receive time in ms (time.time()). Read-only: no orders,
no credentials, no API keys, polite polling (>= 2 s per endpoint, <= 4 concurrent requests).

Sources (pick with --sources, comma separated; default = all):
  pm_sports  Polymarket sports websocket wss://sports-api.polymarket.com/ws (game-level score)
  espn       ESPN public scoreboard JSON, ATP + WTA, each polled every 2 s (game-level + server)
  wta        WTA official public JSON (api.wtatennis.com, robots.txt allows all, no key):
               tournaments/<id>/<yr>/matches?states=L every 2 s  (point-level: PointA/PointB)
               .../matches/<mid>/score every 4 s per live singles match (point-level)
               .../matches/<mid>/point-by-point every 15 s (every point with its official timestamp)
  clob       Polymarket CLOB market websocket for ALL open markets (moneyline + every side market)
             of tennis events starting within [-10 h, +2 h] of now; rediscovered every 120 s.

Skipped (documented in RESULTS.md): atptour.com / app.atptour.com (Cloudflare challenge, 403),
protennislive.com (Cloudflare 503), sofascore (403 even on robots.txt), flashscore (ToS).

Output: data/live_v2/<stream>_<runtag>_<hour>.jsonl, line-buffered; hourly files are gzipped
after rotation. Book records are compacted (asset ids -> small ints, see clobmeta_*.jsonl).

    python research/v2/latency/recorder.py --hours 20                # everything
    python research/v2/latency/recorder.py --hours 20 --sources espn # one source
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gzip
import json
import os
import shutil
import signal
import threading
import time
from pathlib import Path

import requests
import websockets

UA = "courtside-research/0.1 (academic latency study; read-only)"
GAMMA = "https://gamma-api.polymarket.com/events"
SPORTS_WS = "wss://sports-api.polymarket.com/ws"
MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
ESPN = {"atp": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
        "wta": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"}
WTA = "https://api.wtatennis.com/tennis"
TENNIS_LEAGUE_HINTS = ("atp", "wta", "itf", "challenger", "tennis", "utr")
MAX_TOK_PER_CONN = 400


def now_ms() -> int:
    return int(time.time() * 1000)


# ----------------------------------------------------------------------------- output
class Sink:
    """Line-buffered JSONL with hourly rotation; closed hours are gzipped in a thread."""

    def __init__(self, out: Path, name: str, run: str):
        self.out, self.name, self.run = out, name, run
        out.mkdir(parents=True, exist_ok=True)
        self.hour = None
        self.f = None
        self.lock = threading.Lock()
        self._open()

    def _open(self) -> None:
        self.hour = time.strftime("%Y%m%d_%H", time.gmtime())
        self.path = self.out / f"{self.name}_{self.run}_{self.hour}.jsonl"
        self.f = open(self.path, "a", buffering=1)

    def write(self, rec: dict) -> None:
        line = json.dumps(rec, separators=(",", ":")) + "\n"
        with self.lock:
            if time.strftime("%Y%m%d_%H", time.gmtime()) != self.hour:
                old = self.path
                self.f.close()
                self._open()
                threading.Thread(target=_gzip, args=(old,), daemon=True).start()
            self.f.write(line)

    def close(self) -> None:
        with self.lock:
            self.f.close()


def _gzip(p: Path) -> None:
    try:
        with open(p, "rb") as src, gzip.open(str(p) + ".gz", "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        os.remove(p)
    except Exception:
        pass


# ----------------------------------------------------------------------------- http helper
class Http:
    def __init__(self, max_conc: int = 4):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json"})
        self.sem = asyncio.Semaphore(max_conc)

    async def get(self, url: str, params: dict | None = None, timeout: float = 10.0):
        async with self.sem:
            t0 = time.time()
            try:
                r = await asyncio.to_thread(self.s.get, url, params=params, timeout=timeout)
            except Exception as ex:
                return None, {"err": repr(ex)[:200], "ms": int((time.time() - t0) * 1000)}
            meta = {"code": r.status_code, "ms": int((time.time() - t0) * 1000),
                    "age": r.headers.get("age"), "xc": r.headers.get("x-cache"),
                    "cc": r.headers.get("cache-control"), "lm": r.headers.get("last-modified")}
            if r.status_code == 429:
                await asyncio.sleep(30)
            if r.status_code != 200:
                return None, meta
            try:
                return r.json(), meta
            except ValueError:
                return None, meta


async def pace(t0: float, period: float) -> None:
    await asyncio.sleep(max(0.05, period - (time.time() - t0)))


# ----------------------------------------------------------------------------- pm sports ws
def is_tennis_league(lg: str) -> bool:
    lg = (lg or "").lower()
    return any(h in lg for h in TENNIS_LEAGUE_HINTS)


IDLE_RECONNECT_S = 90   # a silently dead socket (seen after a DNS blip at 11:13 UTC) is replaced


async def pm_sports_loop(sink: Sink, stop: float) -> None:
    while time.time() < stop:
        try:
            async with websockets.connect(SPORTS_WS, ping_interval=20, ping_timeout=20, max_size=None) as ws:
                sink.write({"rt": now_ms(), "info": "connected"})
                last_msg = time.time()
                while time.time() < stop:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    except asyncio.TimeoutError:
                        if time.time() - last_msg > IDLE_RECONNECT_S:
                            sink.write({"rt": now_ms(), "info": "idle reconnect"})
                            break
                        continue
                    last_msg = time.time()
                    rt = now_ms()
                    if msg in ("ping", "PING"):
                        await ws.send("pong")
                        continue
                    try:
                        d = json.loads(msg)
                    except ValueError:
                        continue
                    for it in d if isinstance(d, list) else [d]:
                        if isinstance(it, dict) and is_tennis_league(it.get("leagueAbbreviation", "")):
                            sink.write({"rt": rt, **it})
        except Exception as ex:
            sink.write({"rt": now_ms(), "error": repr(ex)[:300]})
            await asyncio.sleep(2)


# ----------------------------------------------------------------------------- espn
def espn_state(c: dict) -> dict:
    comps = []
    for p in c.get("competitors", []):
        ath = p.get("athlete") or {}
        name = ath.get("displayName") or (p.get("roster") or {}).get("displayName") or ""
        ls = p.get("linescores") or []
        comps.append({"n": name, "ha": p.get("homeAway"), "srv": bool(p.get("possession")),
                      "ls": [x.get("value") for x in ls], "tb": [x.get("tiebreak") for x in ls],
                      "w": p.get("winner")})
    st = c.get("status", {})
    return {"id": c.get("id"), "st": st.get("type", {}).get("state"), "per": st.get("period"),
            "det": st.get("type", {}).get("detail"), "p": comps,
            "note": (c.get("notes") or [{}])[0].get("text")}


async def espn_loop(http: Http, sink: Sink, polls: Sink, stop: float, lg: str, period: float = 2.0) -> None:
    last: dict[str, str] = {}
    while time.time() < stop:
        t0 = time.time()
        d, meta = await http.get(ESPN[lg])
        rt = now_ms()
        nlive = nch = 0
        if d:
            for ev in d.get("events", []):
                for g in ev.get("groupings", []):
                    for c in g.get("competitions", []):
                        if "singles" not in (c.get("type", {}).get("slug") or ""):
                            continue
                        s = espn_state(c)
                        if s["st"] == "pre":
                            continue
                        nlive += s["st"] == "in"
                        key = json.dumps([s["st"], s["per"], s["p"]], separators=(",", ":"))
                        if last.get(s["id"]) != key:
                            nch += 1
                            first = s["id"] not in last
                            last[s["id"]] = key
                            sink.write({"rt": rt, "src": f"espn_{lg}", "first": first,
                                        "tn": ev.get("name"), "tid": c.get("tournamentId"), **s})
        polls.write({"rt": rt, "src": f"espn_{lg}", "t0": int(t0 * 1000), "nlive": nlive, "nch": nch, **meta})
        await pace(t0, period)


# ----------------------------------------------------------------------------- wta official
def wta_key(m: dict) -> str:
    keys = ("MatchState", "ScoreString", "PointA", "PointB", "Serve", "ScoreTbSet1", "ScoreTbSet2",
            "ScoreTbSet3", "Winner", "LastUpdated")
    return "|".join(str(m.get(k)) for k in keys)


def wta_compact(m: dict) -> dict:
    keep = ("EventID", "EventYear", "MatchID", "MatchState", "DrawMatchType", "PlayerNameFirstA",
            "PlayerNameLastA", "PlayerNameFirstB", "PlayerNameLastB", "ScoreString", "PointA", "PointB",
            "Serve", "ScoreSet1A", "ScoreSet1B", "ScoreSet2A", "ScoreSet2B", "ScoreSet3A", "ScoreSet3B",
            "ScoreTbSet1", "ScoreTbSet2", "ScoreTbSet3", "Winner", "LastUpdated", "NumSets")
    return {k: m.get(k) for k in keep}


class WtaState:
    def __init__(self):
        self.tourns: list[tuple[int, int, str]] = []
        self.live: dict[tuple, dict] = {}       # (tid, yr, mid) -> compact
        self.last: dict[tuple, str] = {}
        self.pbp_seen: dict[tuple, int] = {}


async def wta_tourn_loop(http: Http, st: WtaState, polls: Sink, stop: float) -> None:
    while time.time() < stop:
        t0 = time.time()
        today = dt.datetime.now(dt.timezone.utc).date()
        d, meta = await http.get(f"{WTA}/tournaments/", params={
            "page": 0, "pageSize": 50, "from": str(today - dt.timedelta(days=1)),
            "to": str(today + dt.timedelta(days=1)), "excludeLevels": "ITF"})
        if d:
            st.tourns = [(t["tournamentGroup"]["id"], t["year"], t["tournamentGroup"]["name"])
                         for t in d.get("content", []) if t.get("status") in ("live", "inProgress")]
        polls.write({"rt": now_ms(), "src": "wta_tourns", "tourns": st.tourns, **meta})
        await pace(t0, 600)


def wta_emit(sink: Sink, st: WtaState, src: str, rt: int, m: dict) -> None:
    if m.get("DrawMatchType") != "S":
        return
    k = (int(m.get("EventID") or 0), int(m.get("EventYear") or 0), m.get("MatchID"))
    key = wta_key(m)
    if st.last.get((src,) + k) != key:
        first = (src,) + k not in st.last
        st.last[(src,) + k] = key
        sink.write({"rt": rt, "src": src, "first": first, **wta_compact(m)})
    if m.get("MatchState") == "P":
        st.live[k] = wta_compact(m)
    else:
        st.live.pop(k, None)


async def wta_list_loop(http: Http, st: WtaState, sink: Sink, polls: Sink, stop: float, period: float = 2.0) -> None:
    while time.time() < stop:
        t0 = time.time()
        res = await asyncio.gather(*[http.get(f"{WTA}/tournaments/{tid}/{yr}/matches", params={"states": "L"})
                                     for tid, yr, _ in st.tourns])
        rt = now_ms()
        seen = set()
        for (tid, yr, _), (d, meta) in zip(st.tourns, res):
            for m in (d or {}).get("matches", []):
                wta_emit(sink, st, "wta_list", rt, m)
                seen.add((int(m.get("EventID") or 0), int(m.get("EventYear") or 0), m.get("MatchID")))
            polls.write({"rt": rt, "src": "wta_list", "tid": tid, "t0": int(t0 * 1000),
                         "lu": (d or {}).get("lastUpdated"), **meta})
        for k in list(st.live):  # matches that left the live list (finished) stop being polled
            if k[0] in {t for t, _, _ in st.tourns} and k not in seen and res:
                st.live.pop(k, None)
        await pace(t0, period)


async def wta_score_loop(http: Http, st: WtaState, sink: Sink, polls: Sink, stop: float, period: float = 4.0) -> None:
    while time.time() < stop:
        t0 = time.time()
        keys = list(st.live)
        res = await asyncio.gather(*[http.get(f"{WTA}/tournaments/{k[0]}/{k[1]}/matches/{k[2]}/score") for k in keys])
        rt = now_ms()
        for k, (d, meta) in zip(keys, res):
            for m in d if isinstance(d, list) else []:
                wta_emit(sink, st, "wta_score", rt, m)
            polls.write({"rt": rt, "src": "wta_score", "mid": k[2], "t0": int(t0 * 1000), **meta})
        await pace(t0, period)


async def wta_pbp_loop(http: Http, st: WtaState, sink: Sink, polls: Sink, stop: float, period: float = 15.0) -> None:
    while time.time() < stop:
        t0 = time.time()
        keys = list(st.live)
        res = await asyncio.gather(*[http.get(f"{WTA}/tournaments/{k[0]}/{k[1]}/matches/{k[2]}/point-by-point")
                                     for k in keys])
        rt = now_ms()
        for k, (d, meta) in zip(keys, res):
            pts = (d or {}).get("points") or []
            seen = st.pbp_seen.get(k, 0)
            first = k not in st.pbp_seen
            for p in pts:
                n = p.get("pointNumber") or 0
                if n > seen:
                    sink.write({"rt": rt, "src": "wta_pbp", "first": first, "tid": k[0], "yr": k[1], "mid": k[2],
                                "names": [(c.get("firstName"), c.get("lastName")) for c in d.get("contestants", [])],
                                **p})
            if pts:
                st.pbp_seen[k] = max(seen, max(p.get("pointNumber") or 0 for p in pts))
            polls.write({"rt": rt, "src": "wta_pbp", "mid": k[2], "t0": int(t0 * 1000), "npts": len(pts), **meta})
        await pace(t0, period)


# ----------------------------------------------------------------------------- clob books
def _ts(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def discover_tennis_markets(back_h: float = 10.0, fwd_h: float = 2.0) -> dict[str, dict]:
    """token -> meta for every open market of tennis events starting in [now-back_h, now+fwd_h]."""
    out: dict[str, dict] = {}
    t = time.time()
    s = requests.Session()
    s.headers["User-Agent"] = UA
    for off in range(0, 3000, 200):
        evs = s.get(GAMMA, params={"tag_slug": "tennis", "active": "true", "closed": "false",
                                   "limit": 200, "offset": off}, timeout=30).json()
        if not evs:
            break
        for e in evs:
            stt = e.get("startTime")
            if not stt or e.get("ended"):
                continue
            if not (-fwd_h * 3600 <= t - _ts(stt) <= back_h * 3600):
                continue
            for m in e.get("markets", []):
                if m.get("closed"):
                    continue
                toks = json.loads(m.get("clobTokenIds") or "[]")
                outs = json.loads(m.get("outcomes") or "[]")
                for i, tok in enumerate(toks):
                    out[tok] = {"slug": e["slug"], "event_id": e.get("id"), "gameId": e.get("gameId"),
                                "title": e.get("title"), "start": stt, "cond": m.get("conditionId"),
                                "smt": m.get("sportsMarketType"), "q": m.get("question"),
                                "git": m.get("groupItemTitle"), "line": m.get("line"),
                                "outcome": outs[i] if i < len(outs) else None, "oi": i,
                                "tick": m.get("orderPriceMinTickSize"),
                                "teams": [(x.get("name"), x.get("ordering")) for x in e.get("teams", [])]}
        if len(evs) < 200:
            break
    return out


class Clob:
    def __init__(self, sink: Sink, meta: Sink, stop: float):
        self.sink, self.meta, self.stop = sink, meta, stop
        self.idx: dict[str, int] = {}
        self.conns: list[dict] = []   # {"toks": [...], "pending": [...]}
        self.tasks: list[asyncio.Task] = []

    def add_tokens(self, mk: dict[str, dict]) -> None:
        new = [t for t in mk if t not in self.idx]
        if not new:
            return
        recs = {}
        for t in new:
            self.idx[t] = len(self.idx)
            recs[self.idx[t]] = {"tok": t, **mk[t]}
        self.meta.write({"rt": now_ms(), "tokens": recs})
        while new:
            if self.conns and len(self.conns[-1]["toks"]) < MAX_TOK_PER_CONN:
                c = self.conns[-1]
            else:
                c = {"toks": [], "pending": []}
                self.conns.append(c)
                self.tasks.append(asyncio.create_task(self.conn_loop(c, len(self.conns) - 1)))
            room = MAX_TOK_PER_CONN - len(c["toks"])
            take, new = new[:room], new[room:]
            c["toks"].extend(take)
            c["pending"].extend(take)

    def handle(self, it: dict, rt: int) -> None:
        et = it.get("event_type")
        if et == "price_change":
            ch = []
            for x in it.get("price_changes", []):
                a = self.idx.get(x.get("asset_id"))
                if a is None:
                    continue
                ch.append([a, float(x["price"]), float(x["size"]), (x.get("side") or "?")[0],
                           float(x.get("best_bid") or "nan"), float(x.get("best_ask") or "nan")])
            if ch:
                self.sink.write({"rt": rt, "e": "pc", "ts": int(it.get("timestamp") or 0), "c": ch})
        elif et == "book":
            a = self.idx.get(it.get("asset_id"))
            if a is None:
                return
            self.sink.write({"rt": rt, "e": "b", "a": a, "ts": int(it.get("timestamp") or 0),
                             "b": [[float(x["price"]), float(x["size"])] for x in it.get("bids", [])],
                             "k": [[float(x["price"]), float(x["size"])] for x in it.get("asks", [])]})
        elif et == "best_bid_ask":
            a = self.idx.get(it.get("asset_id"))
            if a is None:
                return
            self.sink.write({"rt": rt, "e": "bba", "a": a, "ts": int(it.get("timestamp") or 0),
                             "bb": float(it.get("best_bid") or "nan"), "ba": float(it.get("best_ask") or "nan")})
        elif et == "last_trade_price":
            a = self.idx.get(it.get("asset_id"))
            if a is None:
                return
            self.sink.write({"rt": rt, "e": "t", "a": a, "ts": int(it.get("timestamp") or 0),
                             "p": float(it.get("price") or "nan"), "s": float(it.get("size") or 0),
                             "side": it.get("side")})
        elif et in ("tick_size_change", "market_resolved"):
            a = self.idx.get(it.get("asset_id"))
            if a is not None or it.get("market"):
                self.sink.write({"rt": rt, "e": et, "a": a, "raw": {k: it.get(k) for k in
                                 ("market", "old_tick_size", "new_tick_size", "winning_asset_id", "timestamp")}})

    async def conn_loop(self, c: dict, k: int) -> None:
        while time.time() < self.stop:
            try:
                async with websockets.connect(MARKET_WS, ping_interval=None, max_size=None) as ws:
                    await ws.send(json.dumps({"assets_ids": list(c["toks"]), "type": "market",
                                              "custom_feature_enabled": True}))
                    c["pending"] = []
                    self.sink.write({"rt": now_ms(), "e": "conn", "k": k, "n": len(c["toks"])})
                    last_ping = last_msg = time.time()
                    while time.time() < self.stop:
                        if time.time() - last_msg > IDLE_RECONNECT_S:
                            self.sink.write({"rt": now_ms(), "e": "error", "k": k, "err": "idle reconnect"})
                            break
                        if c["pending"]:
                            add, c["pending"] = c["pending"], []
                            await ws.send(json.dumps({"assets_ids": add, "type": "market", "operation": "subscribe",
                                                      "custom_feature_enabled": True}))
                        if time.time() - last_ping > 10:
                            await ws.send("PING")
                            last_ping = time.time()
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=2)
                        except asyncio.TimeoutError:
                            continue
                        last_msg = time.time()
                        rt = now_ms()
                        if msg == "PONG":
                            continue
                        try:
                            d = json.loads(msg)
                        except ValueError:
                            continue
                        for it in d if isinstance(d, list) else [d]:
                            if isinstance(it, dict):
                                self.handle(it, rt)
            except Exception as ex:
                self.sink.write({"rt": now_ms(), "e": "error", "k": k, "err": repr(ex)[:300]})
                await asyncio.sleep(2)

    async def discover_loop(self) -> None:
        while time.time() < self.stop:
            t0 = time.time()
            try:
                mk = await asyncio.to_thread(discover_tennis_markets)
                self.add_tokens(mk)
            except Exception as ex:
                self.meta.write({"rt": now_ms(), "error": repr(ex)[:300]})
            await pace(t0, 120)


# ----------------------------------------------------------------------------- main
async def main(hours: float, out: Path, sources: set[str]) -> None:
    stop = time.time() + hours * 3600
    run = time.strftime("%Y%m%d_%H%M", time.gmtime())
    sinks: list[Sink] = []

    def mk(name: str) -> Sink:
        s = Sink(out, name, run)
        sinks.append(s)
        return s

    polls = mk("polls")
    tasks = []
    if "pm_sports" in sources:
        tasks.append(pm_sports_loop(mk("pmsports"), stop))
    http = Http(4)
    if "espn" in sources:
        es = mk("espn")
        tasks += [espn_loop(http, es, polls, stop, "atp"), espn_loop(http, es, polls, stop, "wta")]
    if "wta" in sources:
        ws_, st = mk("wta"), WtaState()
        tasks += [wta_tourn_loop(http, st, polls, stop), wta_list_loop(http, st, ws_, polls, stop),
                  wta_score_loop(http, st, ws_, polls, stop), wta_pbp_loop(http, st, ws_, polls, stop)]
    if "clob" in sources:
        clob = Clob(mk("clob"), mk("clobmeta"), stop)
        tasks.append(clob.discover_loop())
    polls.write({"rt": now_ms(), "src": "start", "pid": os.getpid(), "run": run, "sources": sorted(sources),
                 "hours": hours})
    try:
        await asyncio.gather(*tasks)
    finally:
        for s in sinks:
            s.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=20.0)
    ap.add_argument("--out", type=Path, default=Path("data/live_v2"))
    ap.add_argument("--sources", default="pm_sports,espn,wta,clob")
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    asyncio.run(main(a.hours, a.out, set(a.sources.split(","))))
