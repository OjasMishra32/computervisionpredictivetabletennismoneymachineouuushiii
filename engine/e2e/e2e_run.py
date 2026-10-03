"""End-to-end timing proof: our streamed frame -> CV call -> live Polymarket book -> UNSIGNED order -> paper fill.

PAPER ONLY. Nothing here signs, sends or places an order, holds a key, or opens an authenticated channel. The
"order" is a plain dict in the CLOB order schema with no signature, built only so that the moment it would be
ready to send can be timestamped. Market data is the public, keyless `market` websocket; the network leg is
MEASURED with a read-only keep-alive GET https://clob.polymarket.com/time (the venue's clock endpoint).
Every output carries LABEL: "paper; order not sent; CV call on our own streamed footage mapped to a live tennis
market for timing (different sport); feed baseline 1 s is simulated (licensed feed not purchased)".

Pipeline per pass (one pass = the held-out clip streamed once):
  data/vision/test_2_copyts.mp4 (OpenTTGames test_2 frames 2000-2999, our own held-out clip)
  -> engine.webrtc.sender (paced virtual camera, frame code, x264 zerolatency, WHIP) -> MediaMTX (127.0.0.1)
  -> engine.webrtc.whep_reader.WhepFrameSource (aiortc WHEP, decode, frame code read back)
  -> engine.vision.stream.run_stream + VisionCallEngine (CoreML GPU on this laptop, frozen call model)
  -> CallEvent -> engine.strategy rule on a LIVE Polymarket tennis book (fair-value jump + edge test)
  -> engine.risk RiskManager.approve -> unsigned order payload (order_ready)
  -> + measured RTT/2 (network_arrival) -> + the market's secondsDelay (executable)
  -> engine.execution.paper fill against the live book at the executable instant (walk levels, taker fee)

The stream is paced at 10 frames/s of wall time with every source frame (slow motion, as research/webrtc's
`slowmo10_engine`): this laptop's engine sustains 9-18 fps, so a real-time 120 fps stream would queue
without bound. At 10 fps no frame waits, so each stage time is processing time. The production reference
for the CV stage is the NVIDIA L4 at a real 120 fps (results/engine/online_vs_offline.json,
results/engine/vision_bench_gpu.json), recorded next to the laptop numbers.

Clock: one clock, time.monotonic(). Stamps written by the imported modules (sender, WHEP reader, vision
engine, market feed) are wall clock (time.time()); they are mapped onto the monotonic clock with the
wall-minus-monotonic offset sampled at 10 Hz (`Clock`); its drift over the run is reported.

Stages logged per call (seconds on the monotonic clock):
  capture          t_due: the paced sender (virtual camera) produced the frame
  frame_sent       t_w1: the sender handed the frame to ffmpeg (x264 zerolatency -> WHIP)
  frame_received   t_complete: last RTP packet of the frame in at our receiver (marker bit)
  decoded          t_dec1: H.264 decode done; handoff = the decoded frame reached our code
  detected         the detector window ending at this frame finished (engine.det.push returned)
  call_emitted     CallEvent.t_emit (tracker + features + frozen classifier + call rule)
  decision         strategy rule done on the live book (fair-value jump + edge test)
  risk_checked     RiskManager.approve done
  order_ready      unsigned order payload built (never signed, never sent)
  network_arrival  order_ready + RTT/2, RTT measured right then (keep-alive GET /time)
  executable       network_arrival + the market's secondsDelay (Gamma `secondsDelay`, 1 s on tennis)
  fill             the paper fill is priced at the executable instant against the book as the venue had it
                   (last update stamped <= executable); fill_computed = when our process could compute it

Market rule (fixed before the run; the timing is the point, not P&L): Gamma tennis events, singles moneylines
of ATP / WTA / Challenger (slug prefix atp- / wta- / challenger-, no doubles: the fair-value model is the
singles Markov model) that accept orders. In play = Gamma event `live` and not `ended`. Liquidity = the
market's Gamma `liquidityClob`. Rank: in-play first, then upcoming (start within 24 h), each by liquidity;
take the first markets whose outcome-0 book is two-sided on the websocket. Passes alternate between them.

Usage (repo root; MediaMTX running with engine/webrtc/mediamtx.yml; scripts/e2e_proof.sh does all of it):
  python -m engine.e2e.e2e_run --passes 12 --markets 2
  python -m engine.e2e.e2e_run --summarize-only          # recompute summary.json from trace.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import datetime as dt
import http.client
import json
import math
import os
import platform
import queue
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from engine.e2e import LABEL  # noqa: E402
from engine.execution.paper import Decision, PaperExecutor  # noqa: E402
from engine.market.clob import LiveClobFeed  # noqa: E402
from engine.risk.limits import V2_NET_CAP_SHARES, RiskConfig, RiskManager, risk_parity_shares  # noqa: E402
from engine.strategy import (CourtsideStrategy, StrategyConfig, assert_paper_only, calibration_job,  # noqa: E402
                             fair_from_job)
from src.markov import Format, State  # noqa: E402

assert_paper_only()

OUT = REPO / "results" / "e2e"
CLIP = REPO / "data" / "vision" / "test_2_copyts.mp4"
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
TIME_HOST, TIME_PATH = "clob.polymarket.com", "/time"     # public, read-only venue clock endpoint
SRC0 = 2000                                               # source frame number of the clip's first frame
ZERO_ADDR = "0x" + "0" * 40
TOURS = ("atp", "wta", "challenger")
FEED_BASELINE_S = 1.0          # simulated licensed feed (not purchased)
REQUIREMENT_S = 3.0            # the organisers' "< 3 s"
REPRICE_BAND_S = (1.0, 1.5)    # market reprice after the point (see summary.reprice_reference)
L4_ONLINE = REPO / "results" / "engine" / "online_vs_offline.json"
L4_BENCH = REPO / "results" / "engine" / "vision_bench_gpu.json"
SWEEP = REPO / "results" / "tier0" / "latency_sweep.json"
V2_LAT = REPO / "research" / "v2" / "latency" / "out" / "summary.json"


# ============================================================================================ one clock
class Clock:
    """time.monotonic() is the clock. Wall stamps (time.time(), written by imported modules and by the sender
    process on this host) map onto it with the wall-minus-monotonic offset, sampled at `hz` (each sample is
    the tightest of three back-to-back reads)."""

    def __init__(self, hz: float = 10.0):
        self._m: list[float] = []
        self._o: list[float] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.sample()
        self._t = threading.Thread(target=self._run, args=(1.0 / hz,), daemon=True)
        self._t.start()

    def sample(self) -> None:
        best = None
        for _ in range(3):
            w0 = time.time()
            m = time.monotonic()
            w1 = time.time()
            if best is None or (w1 - w0) < best[0]:
                best = (w1 - w0, m, (w0 + w1) / 2.0 - m)
        with self._lock:
            self._m.append(best[1])
            self._o.append(best[2])

    def _run(self, period: float) -> None:
        while not self._stop.wait(period):
            self.sample()

    def stop(self) -> None:
        self._stop.set()
        self.sample()

    def _off_at(self, m: float) -> float:
        with self._lock:
            i = bisect.bisect_left(self._m, m)
            js = [j for j in (i - 1, i) if 0 <= j < len(self._m)]
            j = min(js, key=lambda j: abs(self._m[j] - m))
            return self._o[j]

    def to_mono(self, w):
        if w is None:
            return None
        try:
            w = float(w)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(w):
            return None
        return w - self._off_at(w - self._o[-1])

    def wall(self, m: float) -> float:
        return m + self._off_at(m)

    def wall_ms(self, m: float) -> int:
        return int(round(self.wall(m) * 1000.0))

    def stats(self) -> dict:
        with self._lock:
            o = np.asarray(self._o)
        info = time.get_clock_info("monotonic")
        return dict(clock="time.monotonic()", implementation=info.implementation, resolution_s=info.resolution,
                    wall_offset_samples=int(len(o)), wall_offset_range_us=round(float((o.max() - o.min()) * 1e6), 1),
                    wall_offset_sd_us=round(float(o.std() * 1e6), 2),
                    note="wall-clock stamps (time.time()) from the sender, WHEP reader, vision engine and market "
                         "feed are mapped onto time.monotonic() with the nearest offset sample (10 Hz)")


# ============================================================================================ market side
class LockedFeed(LiveClobFeed):
    """The public market-channel feed (read-only) with one lock around book updates: the engine thread reads a
    consistent book while the websocket thread applies messages."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.lock = threading.RLock()

    def handle(self, m, ts_local):
        with self.lock:
            return super().handle(m, ts_local)


class TracedExecutor(PaperExecutor):
    """PaperExecutor that also reports misses (the base class reports fills only)."""

    def __init__(self, *a, on_miss=None, **k):
        self._on_miss_cb = on_miss
        super().__init__(*a, **k)

    def _miss(self, o, reason):
        super()._miss(o, reason)
        if self._on_miss_cb is not None:
            self._on_miss_cb(o)


class MarketThread(threading.Thread):
    """asyncio loop for the live feed, the fill timer (quiet books) and the per-token book ticker."""

    def __init__(self, feed: LockedFeed, want_sports: bool = False):
        super().__init__(daemon=True, name="market")
        self.feed = feed
        self.executors: list[PaperExecutor] = []
        self.loop = None
        self.started = threading.Event()
        self.in_timer = False
        self.ticker: dict[str, deque] = {}
        self.want_sports = want_sports
        self.scores: dict = {}
        self.sinfo: dict = {"connected": False}

    def run(self):
        asyncio.run(self._main())

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self.feed.on(self._on_event)
        timer = asyncio.create_task(self._fill_timer())
        sampler = asyncio.create_task(self._sampler())
        stop = asyncio.Event()
        sports = None
        if self.want_sports:
            from engine.run import _sports_listener   # public score feed, read-only
            sports = asyncio.create_task(_sports_listener(self.scores, self.sinfo, stop))
        self.started.set()
        try:
            await self.feed.run()
        finally:
            timer.cancel()
            sampler.cancel()
            stop.set()
            if sports is not None:
                sports.cancel()

    def _on_event(self, ev):
        dq = self.ticker.get(ev.asset_id)
        if dq is None or ev.kind not in ("book", "price_change", "trade", "best_bid_ask"):
            return
        b = self.feed.book(ev.asset_id)
        bb, ba = b.best_bid(), b.best_ask()
        dq.append((time.monotonic(), ev.ts_server, ev.ts_local, bb, ba, b.bids.get(bb) if bb is not None else None,
                   b.asks.get(ba) if ba is not None else None, ev.kind,
                   ev.price if ev.kind == "trade" else None, ev.size if ev.kind == "trade" else None))

    async def _sampler(self, period_s: float = 0.05):
        """Top of book of every watched token at 20 Hz (a quiet pre-match book sends few messages; the ticker
        still needs a continuous series). Same thread as the book updates, so no lock is needed."""
        while True:
            await asyncio.sleep(period_s)
            t = time.monotonic()
            for tok, dq in list(self.ticker.items()):
                b = self.feed.book(tok)
                if not b.has_snapshot:
                    continue
                bb, ba = b.best_bid(), b.best_ask()
                dq.append((t, b.ts_server, b.ts_local, bb, ba, b.bids.get(bb) if bb is not None else None,
                           b.asks.get(ba) if ba is not None else None, "sample", None, None))

    async def _fill_timer(self, poll_s: float = 0.02):
        """Quiet book: no venue message after t_exec. Fill once local time passes t_exec + the feed's p95 delay
        (the book has not changed, so the current book is the book at t_exec). Same rule as
        PaperExecutor.run_timer, under the feed lock."""
        while True:
            await asyncio.sleep(poll_s)
            with self.feed.lock:
                p95 = self.feed.latency.p95()
                grace = min(2000.0, p95 if p95 is not None else 1000.0)
                upto = int(time.time() * 1000 - grace)
                self.in_timer = True
                try:
                    for ex in self.executors:
                        if ex.queue and ex.queue[0][0] <= upto:
                            ex.flush(upto)
                finally:
                    self.in_timer = False

    def watch(self, tokens):
        for t in tokens:
            self.ticker.setdefault(t, deque(maxlen=400_000))

    def ticker_rows(self, token):
        dq = self.ticker.get(token)
        for _ in range(5):
            try:
                return list(dq) if dq is not None else []
            except RuntimeError:
                time.sleep(0.001)
        return []

    def subscribe(self, tokens, timeout=15):
        return asyncio.run_coroutine_threadsafe(self.feed.subscribe(list(tokens)), self.loop).result(timeout)

    def stop(self):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.feed.stop)


def book_view(b, n=5) -> dict:
    return dict(bid=b.best_bid(), ask=b.best_ask(), bids=[[p, round(s, 2)] for p, s in b.levels("bid", n)],
                asks=[[p, round(s, 2)] for p, s in b.levels("ask", n)], ts_server_ms=b.ts_server,
                tick=b.tick_size)


def gamma_candidates(horizon_h: float = 24.0) -> tuple[list[dict], dict]:
    """Every eligible market under the fixed rule, ranked (in-play first, then upcoming; liquidityClob)."""
    import requests
    now = time.time()
    rows, n_events, seen = [], 0, set()
    for off in range(0, 5000, 100):
        r = requests.get(GAMMA_EVENTS, params=dict(tag_slug="tennis", active="true", closed="false", limit=100,
                                                   offset=off), timeout=30)
        evs = r.json()
        if not evs:
            break
        n_events += len(evs)
        for e in evs:
            slug = e.get("slug") or ""
            tour = slug.split("-")[0]
            if tour not in TOURS or "-doubles-" in slug:
                continue
            st = e.get("startTime")
            try:
                t_start = dt.datetime.fromisoformat(st.replace("Z", "+00:00")).timestamp() if st else None
            except ValueError:
                t_start = None
            in_play = bool(e.get("live")) and not bool(e.get("ended"))
            upcoming = (not in_play) and t_start is not None and 0 < t_start - now <= horizon_h * 3600
            for m in e.get("markets") or []:
                if m.get("sportsMarketType") != "moneyline" or m.get("closed") or not m.get("acceptingOrders"):
                    continue
                if m.get("enableOrderBook") is False or m.get("conditionId") in seen:
                    continue
                toks = json.loads(m.get("clobTokenIds") or "[]")
                outs = json.loads(m.get("outcomes") or "[]")
                if len(toks) != 2 or not (in_play or upcoming):
                    continue
                seen.add(m["conditionId"])
                rows.append(dict(slug=slug, title=e.get("title"), cond=m["conditionId"], tokens=toks, names=outs,
                                 tour=tour, in_play=in_play, start=st, game_id=e.get("gameId"),
                                 liquidity_clob=float(m.get("liquidityClob") or 0.0),
                                 volume24hr=float(m.get("volume24hr") or 0.0),
                                 seconds_delay=m.get("secondsDelay"), tick=m.get("orderPriceMinTickSize"),
                                 neg_risk=bool(m.get("negRisk")), fee_schedule=m.get("feeSchedule"),
                                 score=e.get("score"), period=e.get("period")))
    rows.sort(key=lambda r: (not r["in_play"], -r["liquidity_clob"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows, dict(n_events=n_events, n_eligible=len(rows), n_in_play=sum(r["in_play"] for r in rows),
                      queried_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))


def unsigned_order(token: str, price: float, shares: float, tick: float, mkt: dict) -> dict:
    """The order a taker would send, in the CLOB order schema, UNSIGNED: no maker key, no signature, no API owner.
    It is never signed and never sent; it exists so that `order_ready` marks the moment it would be ready."""
    size = math.floor(shares * 100) / 100.0
    return {
        "order": {"salt": str(secrets.randbits(31)), "maker": ZERO_ADDR, "signer": ZERO_ADDR, "taker": ZERO_ADDR,
                  "tokenId": token, "makerAmount": str(int(round(price * size * 1e6))),
                  "takerAmount": str(int(round(size * 1e6))), "expiration": "0", "nonce": "0", "feeRateBps": "0",
                  "side": "BUY", "signatureType": 0, "signature": None},
        "owner": None, "orderType": "FAK",
        "_paper": {"unsigned": True, "sent": False, "limit_price": price, "size": size, "tick": tick,
                   "neg_risk": bool(mkt.get("neg_risk")), "label": LABEL},
    }


# ============================================================================================ network leg
class RttProber:
    """Network leg, measured: keep-alive GET https://clob.polymarket.com/time (public, read-only). A background
    series on one connection (every bg_s) and, on a second warm connection, a probe the moment an order is
    ready. A probe on a freshly opened connection (TCP + TLS inside the RTT) is repeated on the now-warm one."""

    def __init__(self, bg_s: float = 1.0, warm_s: float = 8.0):
        self.bg_s, self.warm_s = bg_s, warm_s
        self.series: list[dict] = []
        self.q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._conns: dict[str, http.client.HTTPSConnection] = {}
        self._last_od = 0.0
        self._warm_pending = False
        self.errors: list[str] = []

    def start(self):
        threading.Thread(target=self._bg, daemon=True, name="rtt-bg").start()
        threading.Thread(target=self._od, daemon=True, name="rtt-od").start()
        self.q.put(("warm", None, None))
        return self

    def stop(self):
        self._stop.set()
        self.q.put(None)

    def _get(self, name: str):
        for _ in range(4):
            c = self._conns.get(name)
            if c is None:
                c = self._conns[name] = http.client.HTTPSConnection(TIME_HOST, 443, timeout=5)
            reused = c.sock is not None
            t0 = time.monotonic()
            try:
                c.request("GET", TIME_PATH, headers={"Connection": "keep-alive"})
                r = c.getresponse()
                body = r.read()
                t1 = time.monotonic()
            except Exception as e:      # noqa: BLE001 - dropped keep-alive, DNS, timeout: reconnect
                self.errors.append(f"{time.strftime('%H:%M:%S')} {e!r}"[:200])
                c.close()
                self._conns.pop(name, None)
                continue
            if r.status != 200:
                self.errors.append(f"{time.strftime('%H:%M:%S')} HTTP {r.status}")
                continue
            if reused:
                return t0, t1, int(body.strip() or 0)
        return None

    def _bg(self):
        while not self._stop.wait(self.bg_s):
            r = self._get("bg")
            if r:
                self.series.append(dict(t=r[0], rtt_ms=round((r[1] - r[0]) * 1e3, 3), kind="bg", venue_s=r[2]))
            if time.monotonic() - self._last_od > self.warm_s and not self._warm_pending:
                self._warm_pending = True
                self.q.put(("warm", None, None))

    def _od(self):
        while True:
            it = self.q.get()
            if it is None:
                return
            kind, rid, cb = it
            t_deq = time.monotonic()
            r = self._get("od")
            self._last_od = time.monotonic()
            if kind == "warm":
                self._warm_pending = False
                if r:
                    self.series.append(dict(t=r[0], rtt_ms=round((r[1] - r[0]) * 1e3, 3), kind="warm", venue_s=r[2]))
                continue
            if r:
                self.series.append(dict(t=r[0], rtt_ms=round((r[1] - r[0]) * 1e3, 3), kind="order", venue_s=r[2]))
            cb(rid, r, t_deq)

    def probe(self, rid, cb):
        self.q.put(("probe", rid, cb))


# ============================================================================================ the run
class E2E:
    def __init__(self, a):
        self.a = a
        self.clock = Clock()
        self.recs: dict[int, dict] = {}
        self.next_rid = 0
        self.rec_lock = threading.Lock()
        self.ctx: dict | None = None
        self.det_done: dict[int, float] = {}
        self.passes: list[dict] = []
        self.run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.work = Path(a.work or (Path(os.environ.get("TMPDIR", "/tmp")) / "courtside_e2e" / self.run_id))
        self.work.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- setup
    def setup_vision(self):
        from engine.vision import stream as VS
        from engine.webrtc import aiortc_patch
        sys.setswitchinterval(0.001)     # the RTP / websocket threads must not wait 5 ms for the engine's GIL
        aiortc_patch.apply(use_marker=True, video_capacity=1024, loopback_only=True)
        self.VS = VS
        self.M = VS.tracking_modules()
        self.frozen = VS.load_frozen()
        self.geo, self.geo_prov = VS.load_geometry("test_2", self.frozen)
        self.backend = VS.make_backend(self.a.backend, None, 4)
        x0 = np.zeros((1, 9, self.M.D.INP_H, self.M.D.INP_W), np.float32)
        t = time.time()
        for b in (self.backend if isinstance(self.backend, list) else [self.backend]):
            for _ in range(3):
                b(x0)
        print(f"vision: {self.a.backend} warm in {time.time() - t:.1f}s; frozen model {self.frozen.get('model_source')} "
              f"(check err {self.frozen.get('check_max_abs_err'):.1e}); geometry {self.geo_prov}", flush=True)

    def setup_market(self):
        cands, qinfo = gamma_candidates()
        self.gamma_info = qinfo
        top = cands[: self.a.candidates]
        print(f"gamma: {qinfo['n_events']} tennis events, {qinfo['n_eligible']} eligible singles moneylines "
              f"({qinfo['n_in_play']} in play); subscribing the top {len(top)}", flush=True)
        self.feed = LockedFeed(assets=[t for r in top for t in r["tokens"]], ping_s=1.0)
        self.mt = MarketThread(self.feed, want_sports=any(r["in_play"] for r in top))
        self.mt.start()
        self.mt.started.wait(10)
        deadline = time.time() + self.a.book_wait_s
        while time.time() < deadline:
            with self.feed.lock:
                ok = sum(self.feed.book(r["tokens"][0]).has_snapshot for r in top)
            if ok == len(top):
                break
            time.sleep(0.25)
        time.sleep(1.0)
        chosen = []
        with self.feed.lock:
            for r in top:
                b = self.feed.book(r["tokens"][0])
                bb, ba = b.best_bid(), b.best_ask()
                r["book_check"] = dict(snapshot=b.has_snapshot, bid=bb, ask=ba,
                                       two_sided=(bb is not None and ba is not None), tick=b.tick_size)
                if b.has_snapshot and bb is not None and ba is not None and 0.02 < (bb + ba) / 2 < 0.98 \
                        and len(chosen) < self.a.markets:
                    r["chosen"] = True
                    chosen.append(r)
        if len(chosen) < self.a.markets:
            raise SystemExit(f"only {len(chosen)} eligible markets have a live two-sided book")
        self.candidates, self.markets = top, chosen
        for r in chosen:
            if r.get("seconds_delay") is None:
                r["seconds_delay_source"] = "missing in Gamma: 1 s used (the value on every open tennis market)"
                r["seconds_delay"] = 1
            else:
                r["seconds_delay_source"] = "Gamma market secondsDelay"
        print("chosen: " + "; ".join(f"#{r['rank']} {r['slug']} ({'in play' if r['in_play'] else 'upcoming ' + r['start']}, "
                                     f"liquidityClob ${r['liquidity_clob']:,.0f}, secondsDelay {r['seconds_delay']})"
                                     for r in chosen), flush=True)
        self.risk = RiskManager(RiskConfig(), feed=self.feed)
        self.strat = CourtsideStrategy(self.feed, None, self.risk, StrategyConfig())
        self.ex_send = TracedExecutor(self.feed, risk=self.risk, on_fill=lambda f: self._on_fill(f, "send"),
                                      on_miss=lambda o: self._on_miss(o, "send"))
        self.ex_probe = TracedExecutor(self.feed, risk=None, consume_ttl_ms=0,
                                       on_fill=lambda f: self._on_fill(f, "probe"),
                                       on_miss=lambda o: self._on_miss(o, "probe"))
        self.mt.executors = [self.ex_send, self.ex_probe]
        for r in chosen:
            self.mt.watch(r["tokens"])
            with self.feed.lock:
                self.strat.add_match(r["cond"], r["tokens"][0], r["tokens"][1], tour=r["tour"],
                                     names=tuple(r["names"]), calibrate=False)
                self.ex_probe.register_market(r["cond"], r["tokens"])
        self.pool = ProcessPoolExecutor(1)
        self.prober = RttProber(bg_s=1.0).start()

    def state_of(self, m: dict) -> tuple[State, str]:
        if not m["in_play"]:
            return State(), "upcoming: 0-0 pre-match"
        from engine.fair.value import home_is_outcome0, parse_score
        from engine.run import _score_by_names
        sc = self.mt.scores.get(int(m["game_id"])) if m.get("game_id") is not None else None
        sc = sc or _score_by_names(self.mt.scores, m["names"])
        if sc and sc.get("score"):
            hia = home_is_outcome0(m["names"][0], sc.get("homeTeam", ""), sc.get("awayTeam", ""))
            if hia is not None:
                sa, sb, ga, gb = parse_score(sc["score"], hia)
                return State(sa, sb, ga, gb, 0, 0, 0), f"sports feed '{sc['score']}' (points 0-0 assumed)"
        return State(), "in play, score unknown: 0-0 assumed"

    def calibrate(self, m: dict) -> dict:
        state, src = self.state_of(m)
        with self.feed.lock:
            mid = self.strat.mid_a(self.strat.matches[m["cond"]])
        if mid is None or not (0.0 < mid < 1.0):
            return dict(skipped="no mid on the book: previous calibration kept", score_source=src)
        t0 = time.monotonic()
        job = self.pool.submit(calibration_job, mid, m["tour"], state, 0.5).result(timeout=120)
        mf = fair_from_job(job, state, 0.5, m["tour"], Format(), m["cond"], m["tokens"][0], m["tokens"][1])
        with self.feed.lock:
            self.strat.install_fair(m["cond"], mf, mid, int(time.time() * 1000))
            j = mf.prime()
        return dict(mid_a=mid, state=asdict(state), score_source=src,
                    serve_probs=list(mf.serve_probs), v_now=j.v_now, v_if_a=j.v_if_a, v_if_b=j.v_if_b,
                    calibration_ms=round((time.monotonic() - t0) * 1e3, 1), off_hot_path=True)

    # ---------------------------------------------------------------- hot path (engine thread)
    def on_event(self, ev):
        t_cb = time.monotonic()
        c = self.ctx
        m = c["mkt"]
        with self.rec_lock:
            rid = self.next_rid
            self.next_rid += 1
        rec = dict(type="call", label=LABEL, rid=rid, pass_idx=c["k"], call=ev.call, frame=int(ev.frame),
                   p_miss=float(ev.p_miss), direction=int(ev.direction), lead_ms_predicted=float(ev.lead_ms),
                   flight_t0=int(ev.flight_t0), engine_latency_ms=round(ev.latency_ms, 3),
                   market=dict(slug=m["slug"], cond=m["cond"], names=m["names"], tour=m["tour"], in_play=m["in_play"],
                               seconds_delay=m["seconds_delay"], liquidity_clob=m["liquidity_clob"], rank=m["rank"]),
                   t={}, order=None)
        T = rec["t"]
        T["call_emitted"] = self.clock.to_mono(ev.t_emit)
        T["callback"] = t_cb
        T["detected"] = self.det_done.get(int(ev.frame))
        with self.feed.lock:
            now_ms = int(time.time() * 1000)
            self.risk.vision_heartbeat(now_ms)
            d = self.strat.evaluate(m["cond"], ev, t_ms=now_ms)
            T["decision"] = time.monotonic()
            if ev.call == "MISS" and d.winner is not None:
                tok = d.token
                b = self.feed.book(tok)
                ask = b.best_ask()
                tick = float(b.tick_size or 0.01)
                limit = d.limit if d.limit is not None else (round(ask + tick, 6) if ask is not None else None)
                if limit is not None and 0.0 < limit < 1.0:
                    if d.action == "SEND" and d.shares:
                        shares = float(d.shares)
                    else:     # timing probe: the rule's own sizing (v2 risk parity, stale depth inside the limit)
                        vis = b.available("BUY", limit)
                        shares = min(risk_parity_shares(limit, self.strat.cfg.k, visible=vis if vis > 0 else None),
                                     V2_NET_CAP_SHARES)
                    ap = self.risk.approve(tok, "BUY", shares, limit, now_ms=now_ms, fair=d.fair_after,
                                           match_id=m["cond"])
                    T["risk_checked"] = time.monotonic()
                    kind = "rule_send" if (d.action == "SEND" and ap.ok) else "timing_probe"
                    if kind == "rule_send":
                        shares = ap.shares
                    payload = unsigned_order(tok, limit, shares, tick, m)
                    T["order_ready"] = time.monotonic()
                    rec["order"] = dict(kind=kind, token=tok, outcome=d.winner, outcome_name=d.winner_name,
                                        side="BUY", limit=limit, shares=round(shares, 4), fair=d.fair_after,
                                        payload=payload, signed=False, sent=False)
                    rec["risk"] = dict(ok=ap.ok, shares=round(ap.shares, 4), reason=ap.reason,
                                       kills=dict(ap.kills or {}))
                    rec["book_at_order_ready"] = book_view(b)
                else:
                    rec["no_order"] = "no ask on the winner's token (nothing to buy)"
        rec["decision"] = {k: v for k, v in d.to_dict().items()
                           if k in ("action", "reason", "winner", "winner_name", "confidence", "state", "v_now",
                                    "v_if_a", "v_if_b", "leverage", "p_point_winner", "expected_move", "bid", "ask",
                                    "mid", "half_spread", "tick", "limit", "fee", "edge_at_ask", "edge",
                                    "fair_after", "moved_toward_winner", "visible_shares", "shares", "compute_us")}
        with self.rec_lock:
            self.recs[rid] = rec
        if rec["order"] is not None:
            self.prober.probe(rid, self._on_rtt)

    # ---------------------------------------------------------------- network leg -> paper order (prober thread)
    def _on_rtt(self, rid, r, t_deq):
        rec = self.recs[rid]
        T, o = rec["t"], rec["order"]
        if r is None:
            rec["network"] = dict(error="no keep-alive RTT sample", errors=self.prober.errors[-3:])
            return
        t0, t1, venue_s = r
        ow = (t1 - t0) / 2.0
        delay = float(rec["market"]["seconds_delay"])
        T["probe_start"], T["probe_end"] = t0, t1
        T["network_arrival"] = T["order_ready"] + ow
        T["executable"] = T["network_arrival"] + delay
        rec["network"] = dict(rtt_ms=round((t1 - t0) * 1e3, 3), one_way_ms=round(ow * 1e3, 3),
                              probe_start_lag_ms=round((t0 - T["order_ready"]) * 1e3, 3),
                              probe=f"keep-alive GET https://{TIME_HOST}{TIME_PATH}", venue_time_s=venue_s)
        rec["venue"] = dict(seconds_delay=delay, source=self.ctx["mkt"].get("seconds_delay_source"))
        ex = self.ex_send if o["kind"] == "rule_send" else self.ex_probe
        with self.feed.lock:
            ex.one_way_ms = int(round(ow * 1000))
            ex.venue_delay_ms = int(round(delay * 1000))
            po = ex.submit(Decision(o["token"], "BUY", o["shares"], o["limit"],
                                    t_decision=self.clock.wall_ms(T["order_ready"]), match_id=rec["market"]["cond"],
                                    fair=o["fair"], tag={"rid": rid}))
        rec["paper_order"] = dict(executor=("send" if ex is self.ex_send else "probe"), id=po.id, status=po.status,
                                  reason=po.reason, t_decision_ms=po.t_decision, t_arrive_ms=po.t_arrive,
                                  t_exec_ms=po.t_exec, shares=po.shares)

    def _on_fill(self, f, exname):
        rec = self.recs.get(f.tag.get("rid"))
        if rec is None:
            return
        t_now = time.monotonic()
        T = rec["t"]
        rec["fill"] = dict(status="filled" if f.shares >= rec["order"]["shares"] - 1e-9 else "partial",
                           shares=round(f.shares, 4), vwap=f.price, fee=round(f.fee, 6),
                           levels=[[p, round(s, 4)] for p, s in f.levels], cost=round(f.shares * f.price + f.fee, 4),
                           book_ts_server_ms=f.book_ts, t_exec_ms=f.t_exec,
                           via="timer (no venue message after t_exec)" if self.mt.in_timer else "venue clock")
        T["fill"] = T.get("executable")
        T["fill_computed"] = t_now
        T["book_state_stamp"] = self.clock.to_mono(f.book_ts / 1000.0) if f.book_ts else None
        rec["book_at_fill"] = book_view(self.feed.book(f.token))

    def _on_miss(self, o, exname):
        rec = self.recs.get(o.tag.get("rid"))
        if rec is None:
            return
        T = rec["t"]
        b = self.feed.book(o.token)
        rec["fill"] = dict(status="missed", reason=o.reason, shares=0.0, vwap=None, fee=0.0, levels=[],
                           book_ts_server_ms=b.ts_server, t_exec_ms=o.t_exec,
                           via="timer (no venue message after t_exec)" if self.mt.in_timer else "venue clock")
        T["fill"] = T.get("executable")
        T["fill_computed"] = time.monotonic()
        T["book_state_stamp"] = self.clock.to_mono(b.ts_server / 1000.0) if b.ts_server else None
        rec["book_at_fill"] = book_view(b)

    # ---------------------------------------------------------------- one pass of the clip
    def run_pass(self, k: int) -> dict:
        from engine.webrtc import report as WR
        from engine.webrtc.whep_reader import WhepFrameSource, read_sender_log
        VS = self.VS
        m = self.markets[k % len(self.markets)]
        cal = self.calibrate(m)
        path = f"cs_e2e_{self.run_id}_p{k}"
        base = self.a.mtx_base.rstrip("/")
        ready, slog = self.work / f"p{k}.ready", self.work / f"p{k}.send.jsonl"
        for p in (ready, slog):
            if p.exists():
                p.unlink()
        self.ctx = dict(k=k, mkt=m)
        self.det_done = {}
        eng = VS.VisionCallEngine(self.backend, self.frozen, self.geo, fps=120.0, frame_offset=SRC0,
                                  on_event=self.on_event)
        orig_push = eng.det.push

        def push(idx, x, run=True, _orig=orig_push):
            out = _orig(idx, x, run=run)
            self.det_done[idx] = time.monotonic()
            return out
        eng.det.push = push
        warm = threading.Event()
        warm.set()
        src = WhepFrameSource(f"{base}/{path}/whep", self.M.D, src0=SRC0, step=1, ready_file=str(ready), warm=warm,
                              idle_s=3.0, max_s=900.0, feed=True, stale_ms=None)
        load0 = [round(x, 2) for x in os.getloadavg()]
        n_before = self.next_rid
        src.start()
        sender = subprocess.Popen(
            [sys.executable, "-m", "engine.webrtc.sender", "--whip-url", f"{base}/{path}/whip", "--step", "1",
             "--fps", f"{self.a.fps:g}", "--encoder", "x264", "--bitrate", self.a.bitrate, "--log", str(slog),
             "--ready-file", str(ready), "--ffmpeg-log", str(self.work / f"p{k}.ffmpeg.log")],
            cwd=str(REPO), stdout=open(self.work / f"p{k}.send.log", "w"), stderr=subprocess.STDOUT)
        t0 = time.time()
        rows, skipped = VS.run_stream(eng, src, None)
        wall = time.time() - t0
        src.stop()
        src._t_loop.join(timeout=10)
        try:
            sender.wait(timeout=30)
        except subprocess.TimeoutExpired:
            sender.terminate()
        smeta, sent, send_end = read_sender_log(str(slog))
        # wait for every order of this pass to fill or miss
        mine = [r for i, r in self.recs.items() if i >= n_before]
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and any(r["order"] is not None and "fill" not in r and
                                                  "error" not in r.get("network", {}) for r in mine):
            time.sleep(0.1)
        # join the WebRTC / engine per-frame stamps onto each call
        frames = []
        for r in src.rows:
            s = sent.get(r.get("seq"))
            if s:
                r.update(t_due=s["t_due"], t_w0=s["t_w0"], t_w1=s["t_w1"])
            frames.append(r)
        erow = {int(r["i"]): r for r in rows}
        track = {int(t[0]): (t[1], t[2]) for t in eng.track_log}
        for rec in mine:
            kf = rec["frame"] - SRC0
            fr = src.by_k.get(kf) or {}
            T = rec["t"]
            for key, src_key in (("capture", "t_due"), ("send_start", "t_w0"), ("frame_sent", "t_w1"),
                                 ("rx_first_packet", "t_first"), ("frame_received", "t_complete"),
                                 ("decode_start", "t_dec0"), ("decoded", "t_dec1"), ("handoff", "t_handoff"),
                                 ("prepped", "t_ready")):
                T[key] = self.clock.to_mono(fr.get(src_key))
            rec["frame_meta"] = dict(seq=fr.get("seq"), keyframe=fr.get("key"), n_packets=fr.get("n_packets"),
                                     nbytes=fr.get("nbytes"))
            if kf in erow:      # run_stream's per-frame engine stage times for the call's frame
                rec["frame_meta"].update({f"engine_{n}": round(float(erow[kf][n]), 3) for n in
                                          ("qwait_ms", "norm_ms", "infer_ms", "blobs_ms", "track_ms", "feat_ms",
                                           "clf_ms", "proc_ms") if n in erow[kf]})
            rec["track"] = [[f, round(track[f][0], 1), round(track[f][1], 1)] for f in
                            range(rec["frame"] - 110, rec["frame"] + 25) if f in track and np.isfinite(track[f][0])]
            if rec["order"] is not None and T.get("order_ready") is not None:
                t_lo = T["order_ready"] - 3.0
                t_hi = (T.get("executable") or T["order_ready"] + 1.2) + 3.0
                tick = [x for x in self.mt.ticker_rows(rec["order"]["token"]) if t_lo <= x[0] <= t_hi]
                rec["ticker"] = dict(token=rec["order"]["token"], cols=["t_mono", "ts_server_ms", "ts_local_ms",
                                                                         "bid", "ask", "bid_size", "ask_size",
                                                                         "kind", "trade_px", "trade_size"],
                                     rows=tick)
                pre = [x for x in self.mt.ticker_rows(rec["order"]["token"]) if x[0] <= T["order_ready"]]
                if pre:
                    rec["ticker"]["last_before"] = pre[-1]
        clip = [r for r in frames if r.get("flags") is not None and r["flags"] & 2]
        sent_clip = [q for q, s in sent.items() if s.get("flags", 0) & 2]
        es = VS.summarize(rows, wall, skipped, eng)
        p = dict(type="pass", label=LABEL, pass_idx=k, market=m["slug"], cond=m["cond"], calibration=cal,
                 whep_path=path, load_avg_start=load0, load_avg_end=[round(x, 2) for x in os.getloadavg()],
                 wall_s=round(wall, 2), sender=dict(meta={kk: smeta.get(kk) for kk in ("fps", "step", "size", "encoder",
                                                                                     "bitrate", "gop_frames")},
                                                     end=send_end),
                 receiver=dict(src.info), frames=WR.summarize(frames, [], sent_clip)["frames"],
                 video_leg_ms=WR.legs(clip),
                 engine={kk: es.get(kk) for kk in ("frames", "skipped", "fps_sustained", "infer_ms", "proc_ms",
                                                   "qwait_ms", "call_ready_ms", "detector")},
                 calls=[dict(rid=r["rid"], call=r["call"], frame=r["frame"]) for r in mine])
        self.passes.append(p)
        n_miss = sum(r["call"] == "MISS" for r in mine)
        print(f"pass {k}: {m['slug']} | {len(mine)} calls ({n_miss} MISS) | engine {es.get('fps_sustained')} fps, "
              f"skipped {skipped} | lost {p['frames'].get('lost_clip')} | load {load0}", flush=True)
        for r in mine:
            if r["order"] is not None:
                T = r["t"]
                print(f"   MISS f{r['frame']}: capture->order_ready {ms(T, 'capture', 'order_ready')} ms, "
                      f"RTT/2 {r.get('network', {}).get('one_way_ms')} ms, capture->executable "
                      f"{ms(T, 'capture', 'executable')} ms | {r['order']['kind']} ({r['decision']['reason'] or 'SEND'}) "
                      f"| fill {r.get('fill', {}).get('status')} {r.get('fill', {}).get('shares')} @ "
                      f"{r.get('fill', {}).get('vwap')}", flush=True)
        return p

    # ---------------------------------------------------------------- driver
    def run(self):
        assert_paper_only()
        self.setup_vision()
        self.setup_market()
        k = 0
        try:
            while k < self.a.max_passes:
                if k >= self.a.passes and self.complete_miss() >= self.a.min_calls:
                    break
                try:
                    self.run_pass(k)
                except Exception as e:      # noqa: BLE001 - keep the run; the failure is in the trace
                    import traceback
                    traceback.print_exc()
                    self.passes.append(dict(type="pass", label=LABEL, pass_idx=k, error=repr(e)[:500]))
                k += 1
        finally:
            self.prober.stop()
            self.mt.stop()
            self.pool.shutdown(cancel_futures=True)
            self.clock.stop()
            self.write()

    def complete_miss(self):
        return sum(1 for r in self.recs.values() if r["order"] is not None and "fill" in r and
                   r["t"].get("capture") is not None)

    def write(self):
        OUT.mkdir(parents=True, exist_ok=True)
        import aiortc
        import onnxruntime
        meta = dict(type="meta", label=LABEL, run_id=self.run_id,
                    when_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    host=platform.node(), machine=f"{platform.system()} {platform.machine()}",
                    python=sys.version.split()[0], aiortc=aiortc.__version__, onnxruntime=onnxruntime.__version__,
                    clock=self.clock.stats(), clip=str(CLIP.relative_to(REPO)), clip_license="OpenTTGames, CC BY-NC-SA 4.0",
                    stream=dict(step=1, fps=self.a.fps, encoder="x264 zerolatency", bitrate=self.a.bitrate,
                                note="every source frame at 10 frames/s of wall time (slow motion): the laptop engine "
                                     "sustains 9-18 fps, so 120 fps real time would queue; production reference for "
                                     "the CV stage = NVIDIA L4 at 120 fps"),
                    vision=dict(backend=self.a.backend, frozen_model_source=self.frozen.get("model_source"),
                                frozen_check_err=self.frozen.get("check_max_abs_err"), geometry=self.geo_prov),
                    market_rule=("Gamma tennis events; singles moneylines of ATP / WTA / Challenger accepting orders; "
                                 "in play (Gamma live, not ended) first, then upcoming within 24 h, each by Gamma "
                                 "liquidityClob; first markets with a two-sided outcome-0 book on the public "
                                 "websocket; passes alternate between them"),
                    gamma=self.gamma_info, candidates=self.candidates,
                    markets=[{k: r.get(k) for k in ("slug", "title", "cond", "tokens", "names", "tour", "in_play",
                                                    "start", "liquidity_clob", "volume24hr", "seconds_delay",
                                                    "seconds_delay_source", "tick", "neg_risk", "rank", "book_check")}
                             for r in self.markets],
                    risk=dict(config=self.risk.cfg.__dict__, snapshot=self.risk.snapshot()),
                    feed=self.feed.summary(), rtt_errors=self.prober.errors[-10:],
                    paper_only=True, orders_sent=0, orders_signed=0)
        path = OUT / "trace.jsonl"
        with open(path, "w") as fh:
            fh.write(json.dumps(clean(meta)) + "\n")
            for rid in sorted(self.recs):
                fh.write(json.dumps(clean(self.recs[rid])) + "\n")
            for p in self.passes:
                fh.write(json.dumps(clean(p)) + "\n")
            for s in self.prober.series:
                fh.write(json.dumps(clean(dict(type="rtt", **s))) + "\n")
            fh.write(json.dumps(dict(type="end", label=LABEL, n_calls=len(self.recs), n_passes=len(self.passes))) + "\n")
        print(f"wrote {path}", flush=True)
        summarize(path, OUT / "summary.json")


# ============================================================================================ summary
def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return None if not math.isfinite(x) else x
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if hasattr(x, "__dataclass_fields__"):
        return clean(x.__dict__)
    return x


def ms(T, a, b):
    if T.get(a) is None or T.get(b) is None:
        return None
    return round((T[b] - T[a]) * 1e3, 3)


def pct(a, qs=(50, 90, 99)):
    a = np.asarray([x for x in a if x is not None], float)
    a = a[np.isfinite(a)]
    if not len(a):
        return None
    d = {f"p{q}": round(float(np.percentile(a, q)), 3) for q in qs}
    d.update(mean=round(float(a.mean()), 3), min=round(float(a.min()), 3), max=round(float(a.max()), 3), n=int(len(a)))
    return d


# stage -> (start, end), in pipeline order
STAGES = [("sender: frame into encoder", "capture", "frame_sent"),
          ("encode + WHIP + MediaMTX + RTP in", "frame_sent", "frame_received"),
          ("H.264 decode + handoff", "frame_received", "handoff"),
          ("prep + queue + detector", "handoff", "detected"),
          ("tracker + features + classifier", "detected", "call_emitted"),
          ("strategy rule (fair value, edge)", "call_emitted", "decision"),
          ("risk check", "decision", "risk_checked"),
          ("unsigned order built", "risk_checked", "order_ready"),
          ("network one-way (RTT/2)", "order_ready", "network_arrival"),
          ("venue order delay (secondsDelay)", "network_arrival", "executable")]
SPANS = [("capture_to_call", "capture", "call_emitted"), ("capture_to_decoded", "capture", "handoff"),
         ("decoded_to_call", "handoff", "call_emitted"), ("call_to_order_ready", "call_emitted", "order_ready"),
         ("capture_to_order_ready", "capture", "order_ready"), ("capture_to_network_arrival", "capture", "network_arrival"),
         ("capture_to_executable", "capture", "executable"), ("executable_to_fill_computed", "executable", "fill_computed"),
         ("probe_start_lag", "order_ready", "probe_start"), ("rtt", "probe_start", "probe_end")]


def l4_reference() -> dict:
    out = {}
    try:
        h = json.load(open(L4_ONLINE))["headline"]["fp16_cl_fuse_compile_b1_realtime"]["stream"]
        a = h["after_startup"]
        out["online_vs_offline"] = dict(file=str(L4_ONLINE.relative_to(REPO)), gpu="NVIDIA L4", fps=h["fps"],
                                        frames=a["frames"], dropped=h["dropped"],
                                        frame_to_decision_ms=a["call_ready_ms"],
                                        emitted_call_latency_ms=a["emitted_call_latency_ms"], calls=a["calls"],
                                        note="whole held-out test set (test_1..7) at 120 fps, first 4 s excluded")
    except Exception as e:      # noqa: BLE001
        out["online_vs_offline"] = f"unavailable: {e!r}"
    try:
        for h in json.load(open(L4_BENCH))["headline"]:
            if h["spec"] == "torch-cuda-cl-fuse-compile" and h["batch"] == 1 and not h["dynamic"]:
                out["vision_bench_gpu"] = dict(file=str(L4_BENCH.relative_to(REPO)), spec=h["spec"], job=h["job"],
                                               keeps_up_with_120fps=h["keeps_up_with_120fps"],
                                               fps_sustained_max=h["fps_sustained_max"],
                                               frame_to_decision_ms=h["call_latency_no_backlog_ms"],
                                               emitted_call_latency_ms=h["emitted_call_latency_ms"],
                                               note="the demo clip (test_2 frames 2000-2999) at a real 120 fps")
    except Exception as e:      # noqa: BLE001
        out["vision_bench_gpu"] = f"unavailable: {e!r}"
    return out


def reprice_reference() -> dict:
    out = dict(band_s=list(REPRICE_BAND_S),
               basis="the book reprices a median 1.16 s BEFORE the official point stamp (482 live WTA points, "
                     "measured: research/v2/latency); the stamp's own lag after the physical point end is NOT "
                     "measured (2.0 s assumed in tier-0, 3.14 s inferred), and the calibrated stamp reading puts "
                     "the reprice 1.35 s after the bounce (inference). 1.0-1.5 s is the band used here.")
    try:
        s = json.load(open(V2_LAT))["m1"]["book_vs_official_T_s"]
        out["book_vs_official_stamp_s"] = s
        out["implied_after_point_s"] = {"stamp_lag_2.0_assumed": round(2.0 + s["median"], 2),
                                        "stamp_lag_3.14_inferred": round(3.14 + s["median"], 2),
                                        "calibrated_stamp_reading": 1.35}
    except Exception as e:      # noqa: BLE001
        out["book_vs_official_stamp_s"] = f"unavailable: {e!r}"
    try:
        sw = json.load(open(SWEEP))
        out["tier0_at_1s_video_delay"] = {
            "label": sw.get("label"),
            "video_own120.tournament_lagcal.V=1.0": sw["video_own120"]["tournament_lagcal"]["1"],
            "video_own120.tournament.V=1.0": sw["video_own120"]["tournament"]["1"],
            "note": "stored tier-0 counterfactual cells (results/tier0/latency_sweep.json), quoted, not re-run: "
                    "assumed data, licensed feed/video not purchased; burned OOS is not blind"}
    except Exception as e:      # noqa: BLE001
        out["tier0_at_1s_video_delay"] = f"unavailable: {e!r}"
    return out


def summarize(trace_path: Path, out_path: Path) -> dict:
    rows = [json.loads(x) for x in open(trace_path) if x.strip()]
    meta = next(r for r in rows if r["type"] == "meta")
    calls = [r for r in rows if r["type"] == "call"]
    passes = [r for r in rows if r["type"] == "pass"]
    rtt = [r for r in rows if r["type"] == "rtt"]
    full = [r for r in calls if r.get("order") and r.get("fill") and r["t"].get("capture") is not None
            and r["t"].get("executable") is not None]
    Ts = [r["t"] for r in full]
    stages = [dict(stage=n, start=a, end=b, ms=pct([ms(T, a, b) for T in Ts])) for n, a, b in STAGES]
    spans = {n: pct([ms(T, a, b) for T in Ts]) for n, a, b in SPANS}
    all_calls = {n: pct([ms(r["t"], a, b) for r in calls]) for n, a, b in
                 (("capture_to_call", "capture", "call_emitted"), ("call_to_decision", "call_emitted", "decision"),
                  ("capture_to_decision", "capture", "decision"))}
    # the budget with the simulated 1 s feed, per call
    feed_ms = FEED_BASELINE_S * 1e3
    tot = [feed_ms + ms(T, "capture", "executable") for T in Ts]
    ours = [ms(T, "capture", "order_ready") for T in Ts]
    net = [ms(T, "order_ready", "network_arrival") for T in Ts]
    ven = [ms(T, "network_arrival", "executable") for T in Ts]
    l4 = l4_reference()
    l4_call = None
    if isinstance(l4.get("online_vs_offline"), dict):
        l4_call = l4["online_vs_offline"]["emitted_call_latency_ms"]["p50"]
    p50 = lambda xs: float(np.percentile([x for x in xs if x is not None], 50)) if xs else None  # noqa: E731
    ours_l4 = None
    if l4_call is not None and Ts:
        ours_l4 = (p50([ms(T, "capture", "handoff") for T in Ts]) + l4_call +
                   p50([ms(T, "call_emitted", "order_ready") for T in Ts]))
    rep = reprice_reference()
    budget = dict(
        feed_simulated_ms=feed_ms,
        ours_capture_to_order_ready_ms=pct(ours), network_one_way_ms=pct(net), venue_delay_ms=pct(ven),
        total_ms=pct(tot),
        total_p50_formula=(f"{feed_ms:.0f} feed + {p50(ours):.1f} ours + {p50(net):.1f} network + {p50(ven):.0f} venue "
                           f"= {p50(tot):.0f} ms" if Ts else None),
        requirement_ms=REQUIREMENT_S * 1e3,
        margin_to_requirement_ms=pct([REQUIREMENT_S * 1e3 - x for x in tot]),
        calls_under_requirement=f"{sum(x < REQUIREMENT_S * 1e3 for x in tot)}/{len(tot)}",
        reprice_band_ms=[REPRICE_BAND_S[0] * 1e3, REPRICE_BAND_S[1] * 1e3],
        executable_after_reprice_ms=(dict(vs_band_start=round(p50(tot) - REPRICE_BAND_S[0] * 1e3, 1),
                                          vs_band_end=round(p50(tot) - REPRICE_BAND_S[1] * 1e3, 1)) if Ts else None),
        order_arrival_after_point_ms=pct([feed_ms + ms(T, "capture", "network_arrival") for T in Ts]),
        with_l4_vision=(dict(ours_ms=round(ours_l4, 1),
                             total_ms=round(feed_ms + ours_l4 + p50(net) + p50(ven), 1),
                             basis="measured video leg (capture -> decoded) + L4 emitted-call latency p50 "
                                   f"{l4_call} ms (120 fps real time) + measured call -> order_ready, p50s")
                        if ours_l4 is not None else None),
        without_feed_delay_ms=pct([ms(T, "capture", "executable") for T in Ts]))
    if Ts:
        tp = p50(tot)
        budget["what_the_budget_means"] = (
            f"With the simulated 1 s feed the order is ready {feed_ms + p50(ours):.0f} ms after the point and "
            f"executable {tp:.0f} ms after it (p50): {REQUIREMENT_S * 1e3 - tp:.0f} ms inside the < 3 s requirement, "
            f"but {tp - REPRICE_BAND_S[1] * 1e3:.0f}-{tp - REPRICE_BAND_S[0] * 1e3:.0f} ms after the book's typical "
            f"reprice ({REPRICE_BAND_S[0]:.1f}-{REPRICE_BAND_S[1]:.1f} s after the point). Our own pipeline is "
            f"{p50(ours):.0f} ms of it; the feed (1 s) and the venue's order delay ({p50(ven):.0f} ms) are "
            f"{(feed_ms + p50(ven)) / tp * 100:.0f}% of the total.")
    fills = {}
    for kind in ("rule_send", "timing_probe"):
        rs = [r for r in full if r["order"]["kind"] == kind]
        if not rs:
            continue
        st = {}
        for r in rs:
            st[r["fill"]["status"]] = st.get(r["fill"]["status"], 0) + 1
        filled = [r for r in rs if r["fill"]["shares"] > 0]
        fills[kind] = dict(n=len(rs), status=st, shares_requested=round(sum(r["order"]["shares"] for r in rs), 2),
                           shares_filled=round(sum(r["fill"]["shares"] for r in rs), 2),
                           fees=round(sum(r["fill"]["fee"] or 0 for r in rs), 4),
                           vwap_minus_ask_at_order_ready_c=pct([100 * (r["fill"]["vwap"] - r["book_at_order_ready"]["ask"])
                                                                for r in filled
                                                                if r["book_at_order_ready"].get("ask") is not None]),
                           ask_move_order_ready_to_fill_c=pct([100 * (r["book_at_fill"]["ask"] - r["book_at_order_ready"]["ask"])
                                                               for r in rs if r.get("book_at_fill", {}).get("ask") is not None
                                                               and r["book_at_order_ready"].get("ask") is not None]),
                           via={v: sum(r["fill"]["via"] == v for r in rs) for v in {r["fill"]["via"] for r in rs}},
                           rule_reasons={x: sum((r["decision"]["reason"] or "SEND") == x for r in rs)
                                         for x in {(r["decision"]["reason"] or "SEND") for r in rs}})
    by_mkt = {}
    for r in full:
        by_mkt.setdefault(r["market"]["slug"], 0)
        by_mkt[r["market"]["slug"]] += 1
    out = dict(
        label=LABEL, run_id=meta.get("run_id"), when_utc=meta.get("when_utc"), host=meta.get("host"),
        what=("End-to-end timing proof: our held-out table-tennis clip streamed over WebRTC (MediaMTX, loopback) "
              "into the laptop CV engine; every MISS CallEvent drives the strategy on a LIVE Polymarket tennis book, "
              "an unsigned order payload is built, the measured keep-alive RTT/2 to clob.polymarket.com and the "
              "market's secondsDelay are added, and the order is paper-filled against the live book at the "
              "executable instant. Nothing was signed or sent."),
        counts=dict(passes=len(passes), calls=len(calls), miss_calls=sum(r["call"] == "MISS" for r in calls),
                    bounce_calls=sum(r["call"] == "BOUNCE" for r in calls), complete_order_traces=len(full),
                    markets=by_mkt, orders_sent=0, orders_signed=0),
        markets=meta.get("markets"), market_rule=meta.get("market_rule"), clock=meta.get("clock"),
        stream=meta.get("stream"),
        stage_ms=stages, spans_ms=spans, all_calls_ms=all_calls,
        our_pipeline_frame_to_order_ready_ms=spans.get("capture_to_order_ready"),
        total_frame_to_executable_ms=spans.get("capture_to_executable"),
        rtt_background_ms=pct([r["rtt_ms"] for r in rtt if r["kind"] == "bg"]),
        rtt_at_orders_ms=pct([r["network"]["rtt_ms"] for r in full]),
        budget_with_1s_simulated_feed=budget,
        production_gpu_reference=l4,
        reprice_reference=rep,
        fills=fills,
        webrtc_video_leg_capture_to_decoded_ms=pct([ms(T, "capture", "handoff") for T in Ts]),
        engine_stage_ms_at_call_frames={n: pct([r.get("frame_meta", {}).get(f"engine_{n}") for r in calls])
                                        for n in ("qwait_ms", "norm_ms", "infer_ms", "blobs_ms", "track_ms", "feat_ms",
                                                  "clf_ms", "proc_ms")},
        pass_engine_fps=[p.get("engine", {}).get("fps_sustained") for p in passes],
        pass_frames_lost=[p.get("frames", {}).get("lost_clip") for p in passes],
        pass_load_avg=[p.get("load_avg_start") for p in passes],
        pass_errors=[p.get("error") for p in passes if p.get("error")],
        caveats=[
            "Paper only: the order payload is unsigned and was never sent; fills are simulated against the live "
            "public book (walk levels, taker fee 0.05*q*(1-q)).",
            "The CV call is on our own table-tennis footage (OpenTTGames test_2, held out), mapped onto a live tennis "
            "market for timing only: different sport, the call has nothing to do with that match's points.",
            "The 1 s feed is simulated: no licensed feed was purchased. 'capture' is the paced sender's frame time, "
            "so camera exposure, a real relay and the feed's own delay are not in the measured part.",
            "The laptop engine ran on a stream paced at 10 frames/s of wall time (every frame, slow motion) because "
            "it cannot keep up with 120 fps; at a real 120 fps the CV stage is the L4 reference.",
            "Network leg = RTT/2 of a keep-alive GET /time measured at order-ready (Gainesville laptop -> Cloudflare "
            "-> venue); an order POST would also carry the venue's matching-engine time, not measured.",
            "The fill is priced against the venue's book as of its last update stamped <= the executable instant, "
            "which assumes our wall clock and the venue's agree (NTP); our process computes it a feed delay later.",
            "Markets were upcoming / in play as recorded in `markets`; pre-match books are quieter than in-play ones.",
        ],
    )
    out_path.write_text(json.dumps(clean(out), indent=1))
    print(f"wrote {out_path}", flush=True)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--passes", type=int, default=12)
    ap.add_argument("--max-passes", type=int, default=16)
    ap.add_argument("--min-calls", type=int, default=20, help="complete MISS order traces required")
    ap.add_argument("--markets", type=int, default=2)
    ap.add_argument("--candidates", type=int, default=10, help="top-ranked markets subscribed for the book check")
    ap.add_argument("--book-wait-s", type=float, default=15.0)
    ap.add_argument("--fps", type=float, default=10.0, help="wall-clock send rate, every source frame")
    ap.add_argument("--bitrate", default="4M")
    ap.add_argument("--backend", default="onnx-coreml-gpu16")
    ap.add_argument("--mtx-base", default="http://127.0.0.1:8889")
    ap.add_argument("--work", default=None)
    ap.add_argument("--summarize-only", action="store_true")
    a = ap.parse_args(argv)
    assert_paper_only()
    if a.summarize_only:
        summarize(OUT / "trace.jsonl", OUT / "summary.json")
        return
    if not CLIP.exists():
        raise SystemExit(f"missing {CLIP}")
    try:
        urllib.request.urlopen(a.mtx_base + "/", timeout=2)
    except urllib.error.HTTPError:
        pass
    except Exception as e:      # noqa: BLE001
        raise SystemExit(f"MediaMTX not reachable at {a.mtx_base} ({e!r}); scripts/e2e_proof.sh starts it")
    print(f"COURTSIDE e2e timing proof. {LABEL}", flush=True)
    E2E(a).run()


if __name__ == "__main__":
    main()
