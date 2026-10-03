#!/usr/bin/env python3
"""COURTSIDE live paper trader: maker v1 (frozen) on Polymarket tennis side markets, plus a taker control.

PAPER TRADING ONLY, ON LIVE MARKET DATA. Nothing here signs, sends or cancels a real order, and no wallet key
or API key is read or needed. Market data comes only from public, keyless Polymarket endpoints:
  gamma-api /events                    market discovery every 120 s (+ resolution polls)
  CLOB market websocket                order books, price changes, trades, resolutions
  data-api /trades                     in-match print history for matches already in play; trade-side check
                                       (<= 4 concurrent requests, exponential back-off on 429/5xx)

What runs (research/v2/maker/PREREG.md section 3, frozen before this file existed):
  B1          maker v1 as pre-registered: lean one-sided post-only bid on the side-market outcome that the
              moneyline-implied move favours (|impl| >= 4c), joined at the displayed best bid, filled only by
              contrary takers under a conservative queue model, held to resolution, no fee, 15% rebate
  B1-rt       as B1, information cut at seen time (no IS lag)
  B1-full     as B1, without the 20%-of-print cap
  B1-delay    as B1, but our placements also wait the venue delay d (cancels do not)
  CTRL-taker  control (descriptive, not pre-registered): the same signal traded as a TAKER at our real
              latency: marketable buy of the favoured outcome sent when the signal turns on, reaching the
              venue L later, held d = secondsDelay by the venue, then filled against the live book walking
              levels up to the implied fair price, paying the taker fee. Shows what the 1 s delay costs a taker.
Pre-session implementation decisions are in research/v2/maker/DEVIATIONS_LIVE.md.

Run it (from the repo root):
  .venv/bin/python scripts/live_paper.py                                  # live, dashboard, until Ctrl-C
  .venv/bin/python scripts/live_paper.py --minutes 30                     # live for 30 min of quoting
  .venv/bin/python scripts/live_paper.py --until 2026-10-04T11:30:00Z     # the pre-registered session
  .venv/bin/python scripts/live_paper.py --replay 'data/live_v2/clob_20261003_1123_20261003_12.jsonl.gz'
  .venv/bin/python scripts/live_paper.py --replay 'data/live_maker/raw_*.jsonl.gz'   # exact re-run (B2)
Outputs: results/live/<kind>_<run>.jsonl (every event and fill), results/live/summary.json (rolling),
data/live_maker/raw_<run>.jsonl.gz (every websocket message + every other input, replayable).
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import datetime as dt
import glob
import gzip
import hashlib
import heapq
import json
import math
import os
import re
import signal
import statistics
import subprocess
import sys
import time
import traceback
import zlib
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CM = ROOT / "research" / "v2" / "crossmarket"

# ============================================================================ frozen rule (PREREG section 1)
B_T = {
    "tennis_first_set_winner": 1.527875991592811,
    "tennis_set_winner": 1.0781295500280448,
    "tennis_set_handicap": 0.8171462571666066,
    "tennis_match_totals": 1.8243248664803704,
    "tennis_set_totals": 2.721259317541827,
    "tennis_first_set_totals": 3.514143233195978,
}
B_T_SHA256 = "f40c53f741d23fc911cfb42857af4b59d5c22cc54efa7fbfcc27d57fbd18466c"
assert hashlib.sha256(json.dumps({k: repr(v) for k, v in B_T.items()}, sort_keys=True,
                                 separators=(",", ":")).encode()).hexdigest() == B_T_SHA256, "b_T table changed"
FROZEN_SHA256 = {  # PREREG section 1, "Code at freeze"
    "research/v2/crossmarket/analyze.py": "3138af84d0be171c54082956d15f0669754f018223cd04364d80bb6d08a11bb4",
    "research/v2/crossmarket/model.py": "e7b091a941fbb9daa3a6eac19057fdd5dc27808617e5fc0203a30e2bec872f59",
    "research/v2/crossmarket/common.py": "20ca19acc8773cede70c8b63f2c68377de246476234c093e524d64fa2c8df115",
    "research/v2/crossmarket/build.py": "151202928d84a1e3308f7c3f695eded3e37abfeff53e5610f557162e0cf2644d",
    "research/v2/crossmarket/fetch_events.py": "85881cfbb4fc83562b400ef6a68dd11a424864613dd14ed70ac05a687c366275",
    "research/v2/crossmarket/beta_walkforward.csv": "df9196cc3fe7c5cdf97e1078a2921fa79212f5e0e13c2be70dc85ce8dd8dd99d",
    "src/tiers.py": "46a79d75409fd416fdfc2e026c25f02d9ebb3a188a9de1a6ac353561f656363e",
    "src/backtest.py": "dbf82b752942dcff7ba3e0d1fcde2603894d6066938ca1476e8b8f1467a98b46",
}
PLAYER_T = ("tennis_first_set_winner", "tennis_set_winner", "tennis_set_handicap")
TOTALS_T = ("tennis_match_totals", "tennis_set_totals", "tennis_first_set_totals")
PLAYER_ALL = PLAYER_T + ("tennis_game_handicap",)          # model.PLAYER
MIN_IMPL = 0.04
LAMBDA = 1.0
LO, HI = 0.03, 0.97                                         # model.LO / model.HI
MAX_REF_AGE_MS = 600_000
STALE_ML_MS, STALE_SIDE_MS = 30_000, 120_000
MAX_GAP_MS = 300_000
SHARE = 0.2
MAX_FILL_USD, MAX_MATCH_USD = 250.0, 2000.0
PX_LO, PX_HI = 0.02, 0.98
REBATE = 0.15
SERIES = {"atp", "wta", "challenger"}
INPLAY_MAX_MS = 6 * 3600 * 1000
L_FLOOR_MS = 67                                             # src/paper.py FLORIDA preset
TRADE_BOOK_WINDOW_MS = 500                                  # DEVIATIONS_LIVE.md L2
TEXEC_RETRY_MS = 500                                        # DEVIATIONS_LIVE.md L12: taker timer re-arm step
TEXEC_MAX_WAIT_MS = 600_000                                 # ... and the longest wait for the venue clock
TEXEC_SOCKET_MARGIN_MS = 1000                               # socket clock must pass t_exec by this much
LAG_EPISODE_MS, LAG_CLEAR_MS = 2000, 500                    # DEVIATIONS_LIVE.md L13: feed-lag episodes
EPS = 1e-9

GAMMA = "https://gamma-api.polymarket.com/events"
DATA_TRADES = "https://data-api.polymarket.com/trades"
MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
UA = "courtside-research/0.1 (read-only paper trader; no orders)"
MAX_TOK_PER_CONN = 400


def check_frozen() -> dict:
    out = {}
    for rel, want in FROZEN_SHA256.items():
        got = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        out[rel] = got == want
        if got != want:
            raise SystemExit(f"frozen file changed: {rel} ({got} != {want})")
    return out


# frozen helpers, imported from the frozen files (sha256 checked at start-up)
sys.path.insert(0, str(CM))
sys.path.insert(0, str(ROOT))


def _align():
    from fetch_events import align  # noqa: E402  (research/v2/crossmarket/fetch_events.py)
    return align


# ============================================================================ scalar versions of model.py
def logit(x: float) -> float:
    x = min(max(x, 0.005), 0.995)
    return math.log(x / (1 - x))


def expit(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def close(p: float) -> float:
    return 4 * p * (1 - p)


def implied_q0(q_ref, p_ref, p_now, smt, align0, b):
    """model.implied_q0 for one market."""
    pl = smt in PLAYER_ALL
    flip = pl and align0 == -1
    qa = 1 - q_ref if flip else q_ref
    dx = (logit(p_now) - logit(p_ref)) if pl else (close(p_now) - close(p_ref))
    qn = expit(logit(qa) + b * dx)
    return 1 - qn if flip else qn


def xy(smt, align0, m1, m2, p1, p2):
    """model.xy for one interval; None where model.xy gives NaN."""
    pl = smt in PLAYER_ALL
    if pl and align0 == -1:
        m1, m2 = 1 - m1, 1 - m2
    if any(v is None or not math.isfinite(v) for v in (m1, m2, p1, p2)):
        return None
    x = (logit(p2) - logit(p1)) if pl else (close(p2) - close(p1))
    y = logit(m2) - logit(m1)
    ok = LO < m1 < HI and LO < m2 < HI and LO < p1 < HI and LO < p2 < HI and math.isfinite(x) and math.isfinite(y)
    if pl and align0 == 0:
        ok = False
    return (x, y) if ok else None


def r6(x) -> float:
    return round(float(x), 6)


def now_ms() -> int:
    return int(time.time() * 1000)


def iso(ms) -> str:
    if ms is None:
        return "-"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_ts(s) -> int | None:
    if not s:
        return None
    try:
        s = str(s).replace("Z", "+00:00").replace(" ", "T")
        if re.search(r"[+-]\d\d$", s):
            s += ":00"
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp() * 1000)
    except ValueError:
        return None


# ============================================================================ prints and mid proxies
class Prints:
    """In-play taker prints of one market on its outcome-0 axis, with the src.tiers._mid_series proxy."""

    def __init__(self, stale_ms: int):
        self.stale = stale_ms
        self.ts, self.q0, self.ask, self.size, self.mid = [], [], [], [], []
        self.ver = 0
        self._la = self._lb = None
        self._ta = self._tb = -10 ** 18

    def _step(self, i):
        ts, q = self.ts[i], self.q0[i]
        if self.ask[i]:
            self._la, self._ta = q, ts
        else:
            self._lb, self._tb = q, ts
        a = self._la if (self._la is not None and ts - self._ta <= self.stale) else None
        b = self._lb if (self._lb is not None and ts - self._tb <= self.stale) else None
        return (a + b) / 2 if (a is not None and b is not None and a >= b) else q

    def add(self, ts, q0, at_ask, size):
        if not self.ts or ts >= self.ts[-1]:
            self.ts.append(ts), self.q0.append(q0), self.ask.append(bool(at_ask)), self.size.append(size)
            self.mid.append(self._step(len(self.ts) - 1))
            return
        i = bisect.bisect_right(self.ts, ts)
        self.ts.insert(i, ts), self.q0.insert(i, q0), self.ask.insert(i, bool(at_ask)), self.size.insert(i, size)
        self._recompute()

    def _recompute(self):
        self._la = self._lb = None
        self._ta = self._tb = -10 ** 18
        self.mid = [self._step(i) for i in range(len(self.ts))]
        self.ver += 1

    def truncate_after(self, t):
        i = bisect.bisect_right(self.ts, t)
        if i < len(self.ts):
            del self.ts[i:], self.q0[i:], self.ask[i:], self.size[i:]
            self._recompute()

    def clear(self):
        self.ts, self.q0, self.ask, self.size, self.mid = [], [], [], [], []
        self._recompute()

    def before(self, t) -> int:          # last index with ts < t
        return bisect.bisect_left(self.ts, t) - 1

    def upto(self, t) -> int:            # last index with ts <= t
        return bisect.bisect_right(self.ts, t) - 1

    def has_near(self, ts, q0, size, tol_ms=3000) -> bool:
        i = bisect.bisect_left(self.ts, ts - tol_ms)
        while i < len(self.ts) and self.ts[i] <= ts + tol_ms:
            if abs(self.size[i] - size) < 1e-6 and abs(self.q0[i] - q0) < 1e-6:
                return True
            i += 1
        return False


# ============================================================================ order books (L2, per token)
class OBook:
    __slots__ = ("bids", "asks", "empty_snap")

    def __init__(self):
        self.bids, self.asks, self.empty_snap = {}, {}, False

    def best_bid(self):
        return max(self.bids) if self.bids else None

    def best_ask(self):
        return min(self.asks) if self.asks else None

    def mid(self):
        b, a = self.best_bid(), self.best_ask()
        return None if b is None or a is None else (a + b) / 2


# ============================================================================ meta
@dataclass
class Market:
    cond: str
    eid: str
    smt: str
    toks: tuple
    outs: tuple
    align0: int = 0
    delay_ms: int = 1000
    fee_rate: float = 0.05
    rebate_rate: float = 0.15
    tick: float = 0.01
    min_size: float = 5.0
    quotable: bool = False
    why: str = ""
    closed: bool = False

    @property
    def is_ml(self):
        return self.smt == "moneyline"


@dataclass
class Event:
    eid: str
    title: str
    series: str
    start_ms: int | None
    end_ms: int | None = None
    ml_cond: str | None = None
    sides: list = field(default_factory=list)


# ============================================================================ variants and ledgers
@dataclass(frozen=True)
class Variant:
    name: str
    kind: str                  # maker | taker
    view: str                  # lag (IS information timing) | rt (seen time)
    share: float | None = SHARE
    place_wait: bool = False
    label: str = ""


VARIANTS = (
    Variant("B1", "maker", "lag", SHARE, False, "primary (pre-registered)"),
    Variant("B1-rt", "maker", "rt", SHARE, False, "info cut at seen time"),
    Variant("B1-full", "maker", "lag", None, False, "no 20% cap"),
    Variant("B1-delay", "maker", "lag", SHARE, True, "placements wait 1 s"),
    Variant("CTRL-taker", "taker", "rt", None, False, "control: taker at our latency"),
)


@dataclass
class MOrder:
    oid: int
    cond: str
    k: int
    P: float
    R0: float
    R: float
    v: int                     # venue time it becomes visible
    placed: int                # decision key
    impl: float
    c: int | None = None       # venue time a cancel takes effect
    status: str = "pending"    # pending active filled cancelled rejected
    q0: float = 0.0            # queue ahead at activation
    tq: float = 0.0            # traded volume at our price since activation
    cperm: float = 0.0         # settled cancels ahead
    prov: list = field(default_factory=list)   # provisional depletions (e, amount)
    why_end: str = ""

    def q(self):
        return max(0.0, self.q0 - self.tq - self.cperm - sum(a for _, a in self.prov))

    def settle(self, e):
        keep = []
        for te, a in self.prov:
            if te < e - TRADE_BOOK_WINDOW_MS:
                self.cperm += a
            else:
                keep.append((te, a))
        self.prov = keep

    def live(self):
        return self.status in ("pending", "active") and self.c is None


@dataclass
class TOrder:
    oid: int
    cond: str
    k: int
    limit: float
    shares: float
    t_exec: int
    placed: int
    px_seen: float | None
    impl: float
    status: str = "pending"


class Ledger:
    def __init__(self, v: Variant):
        self.v = v
        self.state: dict[str, dict] = {}
        self.orders: dict[str, list] = defaultdict(list)
        self.torders: dict[str, list] = defaultdict(list)
        self.fills: list[dict] = []
        self.used: dict[str, float] = defaultdict(float)
        self.n_place = self.n_cancel = self.n_reject = self.n_taker_miss = 0
        self.n_gap_cancel = self.n_taker_void = 0


# ============================================================================ normalisation of venue messages
def normalize(msg) -> tuple[list, int]:
    """Raw market-websocket frame -> list of ('book'|'pc'|'trade'|'resolved'|'tick', e, ...); count of bad items."""
    out, bad = [], 0
    for it in (msg if isinstance(msg, list) else [msg]):
        if not isinstance(it, dict):
            bad += 1
            continue
        et = it.get("event_type")
        try:
            e = int(it.get("timestamp") or 0)
            if et in ("best_bid_ask", "new_market"):
                continue
            if e <= 0:
                bad += 1
                continue
            if et == "book":
                out.append(("book", e, str(it["asset_id"]),
                            [(r6(x["price"]), float(x["size"])) for x in it.get("bids") or []],
                            [(r6(x["price"]), float(x["size"])) for x in it.get("asks") or []]))
            elif et == "price_change":
                if "price_changes" in it:
                    ch = [(str(c["asset_id"]), r6(c["price"]), float(c["size"]), c.get("side")) for c in it["price_changes"]]
                else:
                    ch = [(str(it["asset_id"]), r6(c["price"]), float(c["size"]), c.get("side")) for c in it.get("changes") or []]
                out.append(("pc", e, ch))
            elif et == "last_trade_price":
                out.append(("trade", e, str(it["asset_id"]), r6(it["price"]), float(it["size"]), it.get("side")))
            elif et == "market_resolved":
                out.append(("resolved", e, it.get("market"), str(it.get("winning_asset_id") or "")))
            elif et == "tick_size_change":
                out.append(("tick", e, str(it.get("asset_id")), it.get("new_tick_size")))
        except (KeyError, TypeError, ValueError):
            bad += 1
    return out, bad


# ============================================================================ the engine (shared by live and replay)
class Engine:
    """Deterministic event engine. Inputs carry a processing key (ms): for venue messages the time we see them,
    s(e) = max(e + L, drain time). Timers carry their own keys. Items are processed in (key, class, seq) order,
    so a live run and a replay of its raw log produce the same orders and fills."""

    def __init__(self, variants=VARIANTS, capital=10_000.0, sink=None, align_fn=None):
        self.L = L_FLOOR_MS
        self.heap = []
        self.iseq = self.tseq = 0
        self.markets: dict[str, Market] = {}
        self.tok: dict[str, tuple] = {}
        self.events: dict[str, Event] = {}
        self.ob: dict[str, OBook] = {}
        self.prints: dict[str, Prints] = {}
        self.payout0: dict[str, float] = {}
        self.last_trade: dict[str, float] = {}
        self.first_k: dict[str, int] = {}     # when we first saw a message for the market (subscription)
        self.ledgers = {v.name: Ledger(v) for v in variants}
        self.makers = [g for g in self.ledgers.values() if g.v.kind == "maker"]
        self.capital = capital
        self.quoting = False
        self.q_start = self.q_stop = None
        self.key = 0
        self.e_max = 0
        self.flip = False
        self.sink = sink or (lambda d: None)
        self.align = align_fn
        self.cache: dict = {}
        self.timers_set: set = set()
        self.rt_timers: set = set()
        self.lastdup: dict[str, tuple] = {}
        self.cnt = Counter()
        self.oid = 0
        self.sig_on: dict[str, dict] = {}   # cond -> last lag-view signal (for the dashboard)
        self.e_conn: dict = {}              # socket -> latest venue (server) timestamp processed from it
        self.e_mkt: dict[str, int] = {}     # market -> latest venue timestamp of a change or trade on it
        self.tok_conn: dict[str, object] = {}   # token -> socket it arrives on (None: recorder files, tests)
        self.gaps: list[dict] = []
        self.gap_open: dict = {}            # socket -> gap record while no data has come back on it
        self.errors: deque = deque(maxlen=20)

    # ------------------------------------------------------------------ queue
    def push(self, key, kind, payload):
        self.iseq += 1
        heapq.heappush(self.heap, (int(key), 0, self.iseq, kind, payload))

    def timer(self, key, kind, payload):
        self.tseq += 1
        heapq.heappush(self.heap, (int(key), 1, self.tseq, kind, payload))

    def run(self, upto=None):
        while self.heap and (upto is None or self.heap[0][0] < upto):
            key, cls, _, kind, payload = heapq.heappop(self.heap)
            self.key = max(self.key, key)
            try:
                if cls == 0:
                    self._input(key, kind, payload)
                else:
                    self._timer(key, kind, payload)
            except Exception as ex:  # never die on one bad item
                self.cnt["engine_errors"] += 1
                self.errors.append(f"{iso(key)} {kind}: {ex!r}")
                self.sink({"ev": "engine_error", "key": key, "kind": kind, "err": repr(ex)[:300],
                           "tb": traceback.format_exc(limit=3)[-600:]})

    def log(self, ev, **kw):
        self.sink({"ev": ev, "key": self.key, **kw})

    # ------------------------------------------------------------------ inputs
    def _input(self, K, kind, d):
        if kind == "ws":
            self._ws(K, d)
        elif kind == "wsc":                    # (socket index, normalised item)
            self._ws(K, d[1], d[0])
        elif kind == "gap":
            self._gap(K, d)
        elif kind == "meta":
            self._meta(K, d)
        elif kind == "boot":
            self._boot(K, d)
        elif kind == "res":
            self._resolve(K, d["cond"], float(d["p0"]), "gamma")
        elif kind == "lat":
            self.L = int(d["L"])
        elif kind == "flip":
            self.flip = bool(d["flip"])
            for p in self.prints.values():
                p.clear()
            self.log("side_convention", flip=self.flip)
        elif kind == "start":
            self.quoting, self.q_start = True, K
            if d.get("stop_ms"):
                self.q_stop = int(d["stop_ms"])
                self.timer(self.q_stop, "stop", {})
            self.log("session_start", **d)
            for cond, m in self.markets.items():
                if m.quotable:
                    self._eval_rt(K, [cond])
                    self._sched_lag(K, cond, K + self.L)
        elif kind == "stop":
            self._stop(K, d.get("why", "stop"))

    def _stop(self, K, why):
        if not self.quoting:
            return
        self.quoting = False
        for g in self.ledgers.values():
            for cond, lst in g.orders.items():
                for o in lst:
                    if o.live():
                        o.c = K
                        o.why_end = why
            for st in g.state.values():
                st["k"] = None
        self.log("quoting_stopped", why=why)

    def _timer(self, K, kind, d):
        if kind == "eval":
            self.timers_set.discard((d["cond"], d["T"]))
            self._eval_lag(K, d["cond"], d["T"])
        elif kind == "evalrt":
            self._eval_rt(K, [d["cond"]])
        elif kind == "texec":
            # Execute against the venue book at t_exec only once the socket carrying this market has delivered a
            # server timestamp >= t_exec: every book change stamped <= t_exec has then been applied (in-order
            # delivery per socket). Under feed lag, re-arm instead of pricing on a stale local book (L12).
            g = self.ledgers[d["book"]]
            for o in g.torders.get(d["cond"], []):
                if o.oid != d["oid"] or o.status != "pending":
                    continue
                conn = self.conn_of(o.cond)
                if conn is not None and self.e_conn.get(conn, 0) >= o.t_exec + TEXEC_SOCKET_MARGIN_MS:
                    self._taker_exec(g, o, "timer")
                elif K - o.t_exec > TEXEC_MAX_WAIT_MS:
                    if conn is None:     # recorder files: no socket id; the market was quiet since t_exec
                        self._taker_exec(g, o, "timer: market quiet 600 s")
                    else:
                        self._taker_void(g, o, "no venue timestamp >= t_exec within 600 s")
                else:
                    self.cnt["texec_rearm"] += 1
                    self.timer(K + TEXEC_RETRY_MS, "texec", d)
        elif kind == "stop":
            self._stop(K, "until")

    def in_gap(self, cond) -> bool:
        m = self.markets.get(cond)
        return bool(self.gap_open) and m is not None and self.tok_conn.get(m.toks[0], "?") in self.gap_open

    def conn_of(self, cond):
        m = self.markets.get(cond)
        return self.tok_conn.get(m.toks[0]) if m else None

    def server_clock(self, cond) -> int:
        """Latest venue timestamp processed from the socket that carries this market (live and own raw logs).
        Recorder files carry no socket id and mixed several sockets with different lags, so there the clock is
        the market's own: a change or trade on it stamped after t_exec executes the order before it is applied."""
        conn = self.conn_of(cond)
        return self.e_conn.get(conn, 0) if conn is not None else self.e_mkt.get(cond, 0)

    def _gap(self, K, d):
        """A market socket dropped (DEVIATIONS_LIVE.md L13). From the last venue timestamp seen on it we cannot
        observe the book or trades of its markets, so: every live maker quote on those markets is treated as
        pulled at that timestamp + 1 ms (no fill can be counted from an unobserved queue), and every pending taker
        order whose t_exec is not yet covered by that socket's clock is voided (the venue book at t_exec is
        unknown). Both are logged per order. On reconnect the strategy re-quotes from the fresh book."""
        conn = d.get("conn")
        toks = set(d.get("toks") or [])
        conds = {self.tok[t][0] for t in toks if t in self.tok}
        e0 = self.e_conn.get(conn, 0)
        c_at = e0 + 1
        cancelled, voided, executed = [], [], []
        for g in self.makers:
            for cond in conds:
                for o in g.orders.get(cond, []):
                    if o.live():
                        o.c, o.why_end = c_at, "feed gap"
                        g.n_cancel += 1
                        g.n_gap_cancel += 1
                        cancelled.append(o.oid)
                        self.log("cancel", book=g.v.name, oid=o.oid, cond=cond, P=o.P, c=c_at, why="feed gap",
                                 conn=conn)
        for g in self.ledgers.values():
            if g.v.kind != "taker":
                continue
            for cond in conds:
                for o in g.torders.get(cond, []):
                    if o.status != "pending":
                        continue
                    if e0 >= o.t_exec + TEXEC_SOCKET_MARGIN_MS:
                        self._taker_exec(g, o, "gap: clock covers t_exec")
                        executed.append(o.oid)
                    else:
                        self._taker_void(g, o, "feed gap before t_exec")
                        voided.append(o.oid)
        self.gap_open[conn] = {"last_e": e0, "key": K}
        rec = {"conn": conn, "phase": d.get("phase"), "last_e": e0, "markets": len(conds),
               "maker_cancelled": cancelled, "taker_voided": voided, "taker_executed": executed,
               "lo_rt": d.get("lo_rt"), "err": d.get("err")}
        self.gaps.append(rec)
        self.cnt["feed_gaps"] += 1
        self.log("feed_gap", **rec)

    # ------------------------------------------------------------------ meta
    def _meta(self, K, d):
        for eid, e in (d.get("events") or {}).items():
            ev = self.events.get(eid)
            if ev is None:
                ev = self.events[eid] = Event(eid, e.get("title", ""), e.get("series", ""), e.get("start_ms"))
                self.log("event_new", eid=eid, title=ev.title, series=ev.series, start=iso(ev.start_ms))
            ev.title = e.get("title", ev.title)
            if e.get("start_ms") and ev.start_ms != e["start_ms"]:
                ev.start_ms = e["start_ms"]
            end = e.get("end_ms")
            if end and ev.end_ms is None:
                self._set_end(K, ev, end, "gamma")
        for cond, mm in (d.get("markets") or {}).items():
            m = self.markets.get(cond)
            if m is None:
                m = Market(cond, mm["eid"], mm["smt"], tuple(mm["toks"]), tuple(mm["outs"]))
                self.markets[cond] = m
                for i, t in enumerate(m.toks):
                    self.tok[t] = (cond, i)
                    self.ob.setdefault(t, OBook())
                self.prints[cond] = Prints(STALE_ML_MS if m.is_ml else STALE_SIDE_MS)
            for f in ("delay_ms", "fee_rate", "rebate_rate", "tick", "min_size", "closed"):
                if mm.get(f) is not None:
                    setattr(m, f, mm[f])
            if mm.get("p0") is not None and cond not in self.payout0:
                self._resolve(K, cond, float(mm["p0"]), "gamma")
        for cond, m in self.markets.items():          # attach markets to their events (any payload order)
            ev = self.events.get(m.eid)
            if ev is None:
                continue
            if m.is_ml:
                ev.ml_cond = cond
            elif cond not in ev.sides:
                ev.sides.append(cond)
        # alignment and quotability need the moneyline names
        for cond, m in self.markets.items():
            if m.is_ml or (cond not in (d.get("markets") or {}) and m.quotable):
                continue
            ev = self.events.get(m.eid)
            ml = self.markets.get(ev.ml_cond) if ev and ev.ml_cond else None
            if m.smt not in B_T:
                m.quotable, m.why = False, "type not quoted"
            elif len(m.toks) != 2 or len(m.outs) != 2:
                m.quotable, m.why = False, "not two outcomes"
            elif m.smt in TOTALS_T and not str(m.outs[0]).lower().startswith("over"):
                m.quotable, m.why = False, "outcome 0 not Over"
            elif ml is None:
                m.quotable, m.why = False, "no moneyline"
            else:
                m.quotable, m.why = True, ""
                if m.smt in PLAYER_T and self.align is not None:
                    m.align0 = int(self.align(m.outs[0], ml.outs[0], ml.outs[1], m.smt))

    def _set_end(self, K, ev, end, src):
        ev.end_ms = int(end)
        self.log("event_end", eid=ev.eid, end=iso(ev.end_ms), src=src)
        for cond in [ev.ml_cond] + ev.sides:
            if cond in self.prints:
                self.prints[cond].truncate_after(ev.end_ms)
        for cond in ev.sides:
            self._eval_rt(K, [cond])
            self._sched_lag(K, cond, K + self.L)

    def _inplay(self, ev: Event, t) -> bool:
        if ev is None or ev.start_ms is None or t < ev.start_ms:
            return False
        if ev.end_ms is not None:
            return t <= ev.end_ms
        return t <= ev.start_ms + INPLAY_MAX_MS

    def _can_quote(self, cond, t) -> bool:
        m = self.markets.get(cond)
        if m is None or not m.quotable or m.closed or cond in self.payout0 or not self.quoting:
            return False
        if self.q_stop is not None and t >= self.q_stop:
            return False
        return self._inplay(self.events.get(m.eid), t)

    # ------------------------------------------------------------------ bootstrap / backfill prints (data-api)
    def _boot(self, K, d):
        cond = d["cond"]
        m = self.markets.get(cond)
        if m is None:
            return
        ev = self.events.get(m.eid)
        P = self.prints[cond]
        lo, hi = d.get("lo"), d.get("hi")
        if hi is None:
            hi = self.first_k.get(cond, K)
        n = 0
        for ts, q0, at_ask, size in d["prints"]:
            if (lo is not None and ts <= lo) or ts >= hi or not self._inplay(ev, ts):
                continue
            if P.has_near(ts, q0, size):
                continue
            P.add(ts, q0, at_ask, size)
            n += 1
        self.cnt["boot_prints"] += n
        self.log("boot", cond=cond, n=n, lo=iso(lo), hi=iso(hi))

    # ------------------------------------------------------------------ venue messages
    def _ws(self, K, ev, conn=None):
        t = ev[0]
        if conn in self.gap_open:
            g0 = self.gap_open.pop(conn)
            self.log("feed_gap_end", conn=conn, first_e=ev[1], last_e=g0["last_e"], since_key=g0["key"])
        self.cnt["msg_" + t] += 1
        self.e_max = max(self.e_max, ev[1])
        if t == "pc":
            for c in ev[2]:
                self.tok_conn[c[0]] = conn
        elif t in ("book", "trade", "tick"):
            self.tok_conn[ev[2]] = conn
        try:
            self._ws_apply(K, ev)
        finally:
            if t != "book":            # a book snapshot's timestamp is its last change, not the socket clock
                self.e_conn[conn] = max(self.e_conn.get(conn, 0), ev[1])
                if t == "pc":
                    for cd in {self.tok[c[0]][0] for c in ev[2] if c[0] in self.tok}:
                        self.e_mkt[cd] = max(self.e_mkt.get(cd, 0), ev[1])
                elif t == "trade" and ev[2] in self.tok:
                    cd = self.tok[ev[2]][0]
                    self.e_mkt[cd] = max(self.e_mkt.get(cd, 0), ev[1])

    def _ws_apply(self, K, ev):
        t = ev[0]
        if t == "pc":
            by = defaultdict(list)
            for tok, px, sz, side in ev[2]:
                if tok in self.tok:
                    by[self.tok[tok][0]].append((tok, px, sz, side))
            for cond, ch in by.items():
                self.first_k.setdefault(cond, K)
                self._venue_pre(cond, ev[1])
                touched = set()
                for tok, px, sz, side in ch:
                    b = self.ob[tok]
                    lv = b.bids if side == "BUY" else b.asks
                    if sz <= 0:
                        lv.pop(px, None)
                    else:
                        lv[px] = sz
                    b.empty_snap = False
                    touched.add(tok)
                self._venue_post(cond, ev[1])
                for tok in touched:
                    self._book_seen(K, cond, tok)
        elif t == "book":
            _, e, tok, bids, asks = ev
            if tok not in self.tok:
                return
            cond, i = self.tok[tok]
            self.first_k.setdefault(cond, K)
            self._venue_pre(cond, e)
            b = self.ob[tok]
            b.bids = {p: s for p, s in bids if s > 0}
            b.asks = {p: s for p, s in asks if s > 0}
            b.empty_snap = not b.bids and not b.asks
            m = self.markets[cond]
            if all(self.ob[x].empty_snap for x in m.toks):
                self._book_cleared(K, cond, e)
            self._venue_post(cond, e)
            self._book_seen(K, cond, tok)
        elif t == "trade":
            self._trade(K, *ev[1:])
        elif t == "resolved":
            _, e, cond, win = ev
            m = self.markets.get(cond)
            if m is not None and win in m.toks:
                self._resolve(K, cond, 1.0 if win == m.toks[0] else 0.0, "ws")
        elif t == "tick":
            _, e, tok, nt = ev
            if tok in self.tok:
                try:
                    self.markets[self.tok[tok][0]].tick = float(nt)
                except (TypeError, ValueError):
                    pass

    def _book_cleared(self, K, cond, e):
        for g in self.makers:
            for o in g.orders.get(cond, []):
                if o.status in ("pending", "active") and (o.c is None or o.c > e):
                    o.c = e
                    o.why_end = "book cleared by venue"
        self.log("book_cleared", cond=cond, e=e)

    def _venue_pre(self, cond, e):
        """Venue-side state at server time e, before this message is applied."""
        for g in self.makers:
            lst = g.orders.get(cond)
            if not lst:
                continue
            for o in lst:
                if o.status == "pending" and e > o.v:
                    if o.c is not None and o.c <= o.v:
                        o.status = "cancelled"
                        continue
                    b = self.ob[self.markets[cond].toks[o.k]]
                    ba = b.best_ask()
                    if ba is not None and ba <= o.P + EPS:
                        o.status, o.why_end = "rejected", "post-only would cross"
                        g.n_reject += 1
                        self.log("reject", book=g.v.name, oid=o.oid, cond=cond, P=o.P, ask=ba)
                        continue
                    o.status, o.q0 = "active", b.bids.get(o.P, 0.0)
                    self.log("visible", book=g.v.name, oid=o.oid, cond=cond, P=o.P, Q=o.q0, v=o.v)
                if o.status == "active" and o.c is not None and e >= o.c:
                    o.status = "cancelled"
            g.orders[cond] = [o for o in lst if o.status in ("pending", "active")]
        for g in self.ledgers.values():
            if g.v.kind != "taker":
                continue
            for o in g.torders.get(cond, []):
                if o.status == "pending" and e > o.t_exec:
                    self._taker_exec(g, o, "book")

    def _venue_post(self, cond, e):
        """Cancels ahead of us: the queue ahead can never exceed the displayed size at our price."""
        for g in self.makers:
            for o in g.orders.get(cond, []):
                if o.status != "active":
                    continue
                o.settle(e)
                D = self.ob[self.markets[cond].toks[o.k]].bids.get(o.P, 0.0)
                qc = o.q()
                if qc > D + EPS:
                    o.prov.append((e, qc - D))

    def _trade(self, K, e, tok, p, size, side):
        if tok not in self.tok:
            return
        cond, i = self.tok[tok]
        m = self.markets[cond]
        q0 = p if i == 0 else r6(1 - p)
        side = (side or "").upper()
        if self.flip:
            side = {"BUY": "SELL", "SELL": "BUY"}.get(side, side)
        if side not in ("BUY", "SELL"):
            self.cnt["trade_bad_side"] += 1
            return
        at_ask = (side == "BUY") == (i == 0)
        last = self.lastdup.get(cond)
        if last and last[0] == e and abs(last[1] - size) < 1e-9 and last[2] != i and abs(last[3] + p - 1) < 1e-9:
            self.cnt["trade_dup"] += 1
            return
        self.lastdup[cond] = (e, size, i, p)
        self.first_k.setdefault(cond, K)
        self._venue_pre(cond, e)
        self._maker_fills(K, e, cond, q0, at_ask, size)
        self.last_trade[m.toks[i]] = p
        self.last_trade[m.toks[1 - i]] = r6(1 - p)
        ev = self.events.get(m.eid)
        if not self._inplay(ev, e):
            return
        self.prints[cond].add(e, q0, at_ask, size)
        self.cnt["prints_ml" if m.is_ml else "prints_side"] += 1
        if m.is_ml:
            sides = [c for c in ev.sides if self.markets[c].quotable]
            self._eval_rt(K, sides)
            for c in sides:
                self._sched_lag(K, c, e + self.markets[c].delay_ms + 1)
        elif m.quotable:
            self._eval_rt(K, [cond])
            self._sched_lag(K, cond, e + m.delay_ms + 1)

    def _maker_fills(self, K, e, cond, q0, at_ask, V):
        m = self.markets[cond]
        for g in self.makers:
            for o in g.orders.get(cond, []):
                if o.status != "active":
                    continue
                if not ((o.k == 0 and not at_ask) or (o.k == 1 and at_ask)):
                    continue                          # only takers selling our token hit our bid
                x = q0 if o.k == 0 else r6(1 - q0)
                if x > o.P + EPS:
                    continue
                o.settle(e)
                eid = m.eid
                budget_sh = max(0.0, MAX_MATCH_USD - g.used[eid]) / o.P
                cap = g.v.share * V if g.v.share else V
                qb = max(0.0, o.q0 - o.tq - o.cperm)      # provisional depletions may be this trade's own
                if abs(x - o.P) <= EPS:
                    kind = "at"
                    f = min(max(0.0, V - qb), cap, o.R, budget_sh)
                    o.tq += V
                    rest = V
                    while o.prov and rest > 0:
                        te, a = o.prov[0]
                        use = min(a, rest)
                        rest -= use
                        if use >= a - 1e-12:
                            o.prov.pop(0)
                        else:
                            o.prov[0] = (te, a - use)
                else:
                    kind = "through"
                    f = min(cap, o.R, budget_sh)
                    o.tq, o.prov = o.q0 + 1e12, []
                f = math.floor(f * 1e6) / 1e6
                if f < 1e-6:
                    continue
                o.R = r6(o.R - f)
                g.used[eid] += f * o.P
                reb = REBATE * m.fee_rate * o.P * (1 - o.P)
                fill = {"book": g.v.name, "oid": o.oid, "eid": eid, "cond": cond, "smt": m.smt, "k": o.k,
                        "outcome": m.outs[o.k] if o.k < len(m.outs) else str(o.k), "px": o.P, "shares": f,
                        "usd": f * o.P, "e": e, "K": K, "V": V, "q_ahead": qb, "kind": kind, "impl": o.impl,
                        "rebate_ps": reb, "rebate_own_ps": m.rebate_rate * m.fee_rate * o.P * (1 - o.P),
                        "fee_ps": 0.0, "fee_rate": m.fee_rate}
                g.fills.append(fill)
                self.log("fill", **fill)
                if o.R < 0.01:
                    o.status, o.why_end = "filled", "filled"
                    st = g.state.get(cond)
                    if st and st.get("k") is not None and self._can_quote(cond, K + self.L):
                        self._place(g, cond, st["k"], K, K + self.L, st.get("impl", 0.0))

    # ------------------------------------------------------------------ strategy: book seen
    def _book_seen(self, K, cond, tok):
        m = self.markets[cond]
        for g in self.makers:
            st = g.state.get(cond)
            if not st or st.get("k") is None or m.toks[st["k"]] != tok:
                continue
            bb = self.ob[tok].best_bid()
            live = [o for o in g.orders.get(cond, []) if o.live()]
            for o in live:
                if bb is None or abs(bb - o.P) > EPS or not (PX_LO < bb < PX_HI):
                    o.c = K + self.L
                    o.why_end = "repeg"
                    g.n_cancel += 1
                    self.log("cancel", book=g.v.name, oid=o.oid, cond=cond, P=o.P, c=o.c, why="repeg", bb=bb)
            if not any(o.live() for o in g.orders.get(cond, [])) and self._can_quote(cond, K + self.L):
                self._place(g, cond, st["k"], K, K + self.L, st.get("impl", 0.0))

    def _place(self, g: Ledger, cond, k, D, T, impl):
        m = self.markets[cond]
        if self.in_gap(cond):                 # no quote on a market whose socket is down (L13)
            self.cnt["place_skipped_gap"] += 1
            return
        bb = self.ob[m.toks[k]].best_bid()
        if bb is None or not (PX_LO < bb < PX_HI):
            return
        rem = MAX_MATCH_USD - g.used[m.eid]
        R0 = math.floor(min(MAX_FILL_USD, rem) / bb * 100) / 100
        if R0 < m.min_size:
            return
        self.oid += 1
        v = T + (m.delay_ms if g.v.place_wait else 0)
        o = MOrder(self.oid, cond, k, bb, R0, R0, v, D, impl)
        g.orders[cond].append(o)
        g.n_place += 1
        self.log("place", book=g.v.name, oid=o.oid, cond=cond, smt=m.smt, k=k, P=bb, R=R0, v=v, impl=impl)

    # ------------------------------------------------------------------ strategy: the signal (PREREG 1.4)
    def _local_sums(self, cond, r, view):
        m = self.markets[cond]
        ev = self.events[m.eid]
        S, M = self.prints[cond], self.prints[ev.ml_cond]
        key = (cond, view)
        c = self.cache.get(key)
        if c is None or c["ver"] != S.ver or c["mver"] != M.ver:
            c = self.cache[key] = {"ver": S.ver, "mver": M.ver, "xy": [0.0], "xx": [0.0]}
        while len(c["xy"]) <= r:
            i = len(c["xy"])
            sxy, sxx = c["xy"][-1], c["xx"][-1]
            if S.ts[i] - S.ts[i - 1] <= MAX_GAP_MS:
                j1, j2 = M.upto(S.ts[i - 1]), M.upto(S.ts[i])
                if j1 >= 0 and j2 >= 0:
                    r_ = xy(m.smt, m.align0, S.mid[i - 1], S.mid[i], M.mid[j1], M.mid[j2])
                    if r_ is not None:
                        sxy += r_[0] * r_[1]
                        sxx += r_[0] * r_[0]
            c["xy"].append(sxy)
            c["xx"].append(sxx)
        return c["xy"][r], c["xx"][r]

    def signal(self, cond, cut, age_ref, view):
        """State for side market cond using prints with ts < cut (cut None: every print seen so far)."""
        m = self.markets[cond]
        ev = self.events.get(m.eid)
        out = {"k": None, "impl": 0.0}
        if ev is None or ev.ml_cond is None:
            out["why"] = "no moneyline"
            return out
        S, M = self.prints[cond], self.prints[ev.ml_cond]
        r = (len(S.ts) - 1) if cut is None else S.before(cut)
        if r < 0:
            out["why"] = "no side print"
            return out
        ts_r = S.ts[r]
        if age_ref - ts_r > MAX_REF_AGE_MS:
            out["why"] = "side reference > 600 s old"
            out["ts_r"] = ts_r
            return out
        i_ref = M.upto(ts_r)
        i_now = (len(M.ts) - 1) if cut is None else M.before(cut)
        if i_ref < 0 or i_now < 0:
            out["why"] = "no moneyline print"
            return out
        q_ref, p_ref, p_now = S.mid[r], M.mid[i_ref], M.mid[i_now]
        sxy, sxx = self._local_sums(cond, r, view)
        b = (sxy + LAMBDA * B_T[m.smt]) / (sxx + LAMBDA)
        qn = implied_q0(q_ref, p_ref, p_now, m.smt, m.align0, b)
        impl = qn - q_ref
        k = 0 if impl >= MIN_IMPL else (1 if impl <= -MIN_IMPL else None)
        out.update(k=k, impl=impl, q_ref=q_ref, p_ref=p_ref, p_now=p_now, b=b, ts_r=ts_r, qimp=qn,
                   why="" if k is not None else "|impl| < 4c")
        return out

    def _sched_lag(self, K, cond, T_min):
        """Lag view: a print at e takes effect at T = max(e + d + 1, s(e) + L); decided at T - L."""
        T = max(int(T_min), K + self.L)
        if (cond, T) in self.timers_set:
            return
        self.timers_set.add((cond, T))
        self.timer(T - self.L, "eval", {"cond": cond, "T": T})

    def _eval_lag(self, D, cond, T):
        m = self.markets.get(cond)
        if m is None:
            return
        cut = T - m.delay_ms
        sig = self.signal(cond, cut, cut, "lag")
        self.sig_on[cond] = {**sig, "T": T}
        for g in self.makers:
            if g.v.view == "lag":
                self._apply_state(g, cond, sig, D, T)
        if sig["k"] is not None and sig.get("ts_r") is not None:
            self._sched_lag(D, cond, sig["ts_r"] + MAX_REF_AGE_MS + m.delay_ms + 1)

    def _eval_rt(self, K, conds):
        for cond in conds:
            m = self.markets.get(cond)
            if m is None or not m.quotable:
                continue
            sig = self.signal(cond, None, K, "rt")
            for g in self.ledgers.values():
                if g.v.view != "rt":
                    continue
                if g.v.kind == "maker":
                    self._apply_state(g, cond, sig, K, K + self.L)
                else:
                    self._taker_state(g, cond, sig, K)
            if sig["k"] is not None and sig.get("ts_r") is not None and (cond, sig["ts_r"]) not in self.rt_timers:
                self.rt_timers.add((cond, sig["ts_r"]))
                self.timer(sig["ts_r"] + MAX_REF_AGE_MS + 1, "evalrt", {"cond": cond})

    def _apply_state(self, g: Ledger, cond, sig, D, T):
        st = g.state.setdefault(cond, {"k": None})
        k = sig["k"] if self._can_quote(cond, T) else None
        st["impl"] = sig["impl"]
        if k != st["k"]:
            for o in g.orders.get(cond, []):
                if o.live():
                    o.c = T
                    o.why_end = "state off" if k is None else "state flip"
                    g.n_cancel += 1
                    self.log("cancel", book=g.v.name, oid=o.oid, cond=cond, P=o.P, c=T, why=o.why_end)
            self.log("state", book=g.v.name, cond=cond, k=k, impl=round(sig["impl"], 5), T=T,
                     q_ref=sig.get("q_ref"), p_ref=sig.get("p_ref"), p_now=sig.get("p_now"), b=sig.get("b"))
            st["k"], st["since"] = k, T
            if k is not None:
                self._place(g, cond, k, D, T, sig["impl"])
        elif k is not None and not any(o.live() for o in g.orders.get(cond, [])):
            self._place(g, cond, k, D, T, sig["impl"])

    # ------------------------------------------------------------------ taker control
    def _taker_state(self, g: Ledger, cond, sig, K):
        st = g.state.setdefault(cond, {"k": None})
        k = sig["k"] if self._can_quote(cond, K) else None
        if k == st["k"]:
            return
        if k is not None and self.in_gap(cond):   # the book this order would meet cannot be observed (L13);
            self.cnt["taker_skipped_gap"] += 1     # the state is left unchanged, so it fires once data is back
            return
        st["k"], st["since"] = k, K
        if k is None:
            return
        m = self.markets[cond]
        limit = sig["qimp"] if k == 0 else 1 - sig["qimp"]
        limit = math.floor(limit * 100 + 1e-9) / 100      # a marketable limit on the 1c tick, at most fair
        if not (PX_LO < limit < PX_HI):
            return
        rem = MAX_MATCH_USD - g.used[m.eid]
        sh = math.floor(min(MAX_FILL_USD, rem) / limit * 100) / 100
        if sh < m.min_size:
            return
        self.oid += 1
        ba = self.ob[m.toks[k]].best_ask()
        o = TOrder(self.oid, cond, k, limit, sh, K + self.L + m.delay_ms, K, ba, sig["impl"])
        g.torders[cond].append(o)
        g.n_place += 1
        self.log("taker_send", book=g.v.name, oid=o.oid, cond=cond, smt=m.smt, k=k, limit=limit, shares=sh,
                 t_exec=o.t_exec, ask_seen=ba, impl=sig["impl"])
        self.timer(o.t_exec + 2000, "texec", {"book": g.v.name, "cond": cond, "oid": o.oid})

    def _taker_exec(self, g: Ledger, o: TOrder, how):
        m = self.markets[o.cond]
        b = self.ob[m.toks[o.k]]
        got = cost = fee = 0.0
        for px, sz in sorted(b.asks.items()):
            if px > o.limit + EPS or got >= o.shares - 1e-9:
                break
            take = min(sz, o.shares - got)
            got += take
            cost += take * px
            fee += take * m.fee_rate * px * (1 - px)
        o.status = "done"
        self.cnt["taker_exec_" + how.split(":")[0]] += 1
        if got < 1e-6:
            g.n_taker_miss += 1
            self.log("taker_miss", book=g.v.name, oid=o.oid, cond=o.cond, limit=o.limit, ask_seen=o.px_seen,
                     ask_exec=b.best_ask(), t_exec=o.t_exec, how=how)
            return
        vwap = cost / got
        g.used[m.eid] += cost
        fill = {"book": g.v.name, "oid": o.oid, "eid": m.eid, "cond": o.cond, "smt": m.smt, "k": o.k,
                "outcome": m.outs[o.k] if o.k < len(m.outs) else str(o.k), "px": vwap, "shares": got, "usd": cost,
                "e": o.t_exec, "K": o.placed, "V": None, "q_ahead": None, "kind": "taker", "impl": o.impl,
                "rebate_ps": 0.0, "rebate_own_ps": 0.0, "fee_ps": fee / got, "fee_rate": m.fee_rate,
                "ask_seen": o.px_seen, "slip_c": (vwap - o.px_seen) * 100 if o.px_seen else None,
                "limit": o.limit, "wanted": o.shares, "how": how, "clock_e": self.server_clock(o.cond)}
        g.fills.append(fill)
        self.log("fill", **fill)

    def _taker_void(self, g: Ledger, o: TOrder, why):
        o.status = "void"
        g.n_taker_void += 1
        self.log("taker_void", book=g.v.name, oid=o.oid, cond=o.cond, limit=o.limit, ask_seen=o.px_seen,
                 t_exec=o.t_exec, why=why)

    # ------------------------------------------------------------------ resolution and P&L
    def _resolve(self, K, cond, p0, src):
        if cond in self.payout0:
            return
        self.payout0[cond] = p0
        m = self.markets.get(cond)
        self.log("resolved", cond=cond, p0=p0, src=src, smt=m.smt if m else None)
        if m is None:
            return
        for g in self.makers:
            for o in g.orders.get(cond, []):
                if o.live():
                    o.c = K
                    o.why_end = "resolved"
        ev = self.events.get(m.eid)
        if m.is_ml and ev is not None and ev.end_ms is None:
            self._set_end(K, ev, min(K, self.e_max) if self.e_max else K, "moneyline resolved")

    def mark(self, cond, k):
        if cond in self.payout0:
            p0 = self.payout0[cond]
            return (p0 if k == 0 else 1 - p0), "resolved"
        m = self.markets[cond]
        b = self.ob.get(m.toks[k])
        if b is not None and b.mid() is not None:
            return b.mid(), "mid"
        lt = self.last_trade.get(m.toks[k])
        if lt is not None:
            return lt, "last"
        return None, "none"

    def book_stats(self, g: Ledger) -> dict:
        real = unreal = reb = fee = usd = sh = 0.0
        res_ps, res_w, res_rows = [], [], []
        nopen = 0
        for f in g.fills:
            mk, how = self.mark(f["cond"], f["k"])
            usd += f["usd"]
            sh += f["shares"]
            reb += f["rebate_ps"] * f["shares"]
            fee += f["fee_ps"] * f["shares"]
            if mk is None:
                mk = f["px"]
            pnl = f["shares"] * (mk - f["px"] + f["rebate_ps"] - f["fee_ps"])
            if how == "resolved":
                real += pnl
                ps = mk - f["px"] + f["rebate_ps"] - f["fee_ps"]
                res_ps.append(ps)
                res_w.append(f["shares"])
                res_rows.append((f["eid"], ps))
            else:
                unreal += pnl
                nopen += 1
        oq = sum(1 for lst in g.orders.values() for o in lst if o.live())
        out = {"fills": len(g.fills), "matches": len({f["eid"] for f in g.fills}), "usd_filled": usd, "shares": sh,
               "realised": real, "unrealised": unreal, "pnl": real + unreal, "rebate": reb, "fees": fee,
               "equity": self.capital + real + unreal, "open_quotes": oq, "open_fills": nopen,
               "resolved_fills": len(res_ps), "placed": g.n_place, "cancels": g.n_cancel, "rejects": g.n_reject,
               "taker_misses": g.n_taker_miss, "gap_cancels": g.n_gap_cancel, "taker_voids": g.n_taker_void,
               "net_c_per_share": (sum(res_ps) / len(res_ps) * 100) if res_ps else None,
               "net_c_share_w": (sum(p * w for p, w in zip(res_ps, res_w)) / sum(res_w) * 100) if res_ps else None}
        out["ci95_c"] = cluster_ci(res_rows) if len(res_rows) >= 2 else None
        if g.v.kind == "taker":
            sl = [f["slip_c"] for f in g.fills if f.get("slip_c") is not None]
            out["median_slip_c"] = statistics.median(sl) if sl else None
        return out


def cluster_ci(rows, n_boot=2000, seed=0):
    """Match-clustered bootstrap CI (c/share) of the fill-weighted mean of pnl_ps (PREREG 3.7)."""
    import numpy as np
    by = defaultdict(lambda: [0.0, 0])
    for eid, ps in rows:
        by[eid][0] += ps
        by[eid][1] += 1
    s = np.array([v[0] for v in by.values()])
    n = np.array([v[1] for v in by.values()])
    if len(s) < 2:
        return None
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(s), (n_boot, len(s)))
    bs = s[pick].sum(1) / n[pick].sum(1)
    return [float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)]


# ============================================================================ output
class Out:
    def __init__(self, kind: str, run: str, raw: bool):
        self.dir = ROOT / "results" / "live"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.kind, self.run = kind, run
        self.path = self.dir / f"{kind}_{run}.jsonl"
        self.f = open(self.path, "a", buffering=1)
        self.raw_path = None
        self.raw = None
        if raw:
            d = ROOT / "data" / "live_maker"
            d.mkdir(parents=True, exist_ok=True)
            self.raw_path = d / f"raw_{run}.jsonl.gz"
            self.raw = gzip.open(self.raw_path, "at", compresslevel=6)
            self.raw_flush = time.time()
        self.tape = deque(maxlen=40)

    def event(self, d):
        d = {"t": iso(d.get("key")), **d}
        try:
            self.f.write(json.dumps(d, separators=(",", ":"), default=str) + "\n")
        except (TypeError, ValueError):
            pass
        if d.get("ev") in ("fill", "taker_miss", "session_start", "quoting_stopped", "resolved", "engine_error",
                           "reconnect", "warmup"):
            self.tape.append(d)

    def rawrec(self, rec):
        if self.raw is None:
            return
        try:
            self.raw.write(json.dumps(rec, separators=(",", ":")) + "\n")
            if time.time() - self.raw_flush > 5:
                self.raw.flush()                   # GzipFile.flush uses Z_SYNC_FLUSH: readable up to here
                self.raw_flush = time.time()
        except Exception as ex:                    # a logging problem must never stop the trader
            self.raw_errors = getattr(self, "raw_errors", 0) + 1
            if self.raw_errors < 5:
                self.event({"ev": "raw_log_error", "err": repr(ex)[:200]})

    def close(self):
        self.f.close()
        if self.raw is not None:
            self.raw.close()


def git_head() -> str:
    try:
        h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "scripts/live_paper.py"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return h + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def peek(line: str):
    with open(ROOT / "results" / "oos_peeks.log", "a") as f:
        f.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} {line}\n")


def summary(eng: Engine, info: dict) -> dict:
    books = {}
    for name, g in eng.ledgers.items():
        books[name] = {"label": g.v.label, **eng.book_stats(g)}
    inplay = [ev for ev in eng.events.values() if eng._inplay(ev, eng.key)]
    q = [c for ev in inplay for c in ev.sides if eng.markets[c].quotable]
    on = [c for c in q if (eng.ledgers["B1"].state.get(c) or {}).get("k") is not None]
    fills = []
    for g in eng.ledgers.values():
        fills += g.fills
    fills = sorted(fills, key=lambda f: f["e"])[-15:]
    b1, tk = books.get("B1", {}), books.get("CTRL-taker", {})
    head = (f"{info.get('status', '')} · paper, live data · maker B1: {b1.get('fills', 0)} fills, "
            f"${b1.get('usd_filled', 0):,.0f} filled, P&L {b1.get('pnl', 0):+,.2f} (marked to mid) · "
            f"taker control: {tk.get('fills', 0)} fills, {tk.get('taker_misses', 0)} misses, P&L {tk.get('pnl', 0):+,.2f}")
    return {"headline": head, "label": "PAPER TRADING - LIVE MARKET DATA (public Polymarket feeds; no orders sent)",
            "strategy": "maker v1 (frozen, research/v2/maker/PREREG.md) + taker control", **info,
            "now": iso(eng.key), "L_ms": eng.L, "quoting": eng.quoting, "session_start": iso(eng.q_start),
            "quoting_until": iso(eng.q_stop), "capital_per_book": eng.capital,
            "matches_in_play": len(inplay), "side_markets_quotable": len(q), "signals_on_B1": len(on),
            "counters": dict(eng.cnt), "books": books,
            "last_fills": [{k: f.get(k) for k in ("book", "e", "smt", "outcome", "px", "shares", "usd", "kind")} for f in fills]}


# ============================================================================ dashboard (plain ANSI)
C = {"b": "\x1b[1m", "d": "\x1b[2m", "g": "\x1b[32m", "r": "\x1b[31m", "y": "\x1b[33m", "c": "\x1b[36m",
     "inv": "\x1b[7m", "x": "\x1b[0m"}


def money(x, sign=True):
    if x is None:
        return "-"
    col = C["g"] if x > 0.005 else (C["r"] if x < -0.005 else "")
    s = f"{x:+,.2f}" if sign else f"{x:,.2f}"
    return f"{col}${s}{C['x']}" if col else f"${s}"


def pad(s, n):
    vis = re.sub(r"\x1b\[[0-9;]*m", "", s)
    return s + " " * max(0, n - len(vis))


def rpad(s, n):
    vis = re.sub(r"\x1b\[[0-9;]*m", "", s)
    return " " * max(0, n - len(vis)) + s


def short_title(ev: Event | None, n=34):
    if ev is None:
        return "?"
    t = ev.title.split(": ", 1)[-1] if ": " in ev.title else ev.title
    return (t[: n - 1] + "~") if len(t) > n else t


def smt_short(smt):
    return {"tennis_first_set_winner": "1st-set winner", "tennis_set_winner": "set winner",
            "tennis_set_handicap": "set handicap", "tennis_match_totals": "match O/U games",
            "tennis_set_totals": "sets O/U", "tennis_first_set_totals": "1st-set O/U", "moneyline": "moneyline"}.get(smt, smt)


def render(eng: Engine, info: dict, out: Out) -> str:
    W = 118
    L = []
    mode = info.get("mode", "LIVE")
    L.append(f"{C['inv']}{C['b']} COURTSIDE  maker v1 (frozen)  {C['x']}{C['y']}{C['b']}  PAPER TRADING  {C['x']}"
             f"{C['c']}{C['b']}  {'LIVE MARKET DATA' if mode == 'LIVE' else 'REPLAY OF RECORDED LIVE DATA'}  {C['x']}"
             f"{C['d']} Polymarket public feeds, no orders are sent{C['x']}")
    now = eng.key or now_ms()
    st = info.get("status", "")
    L.append(f" {iso(now)[:19].replace('T', ' ')} UTC   {st}   latency L {eng.L} ms"
             + (f" (ping/2 median {info['ping_ms']:.0f} ms)" if info.get("ping_ms") else "")
             + (f"   quoting until {iso(eng.q_stop)[:16].replace('T', ' ')}" if eng.q_stop else ""))
    inplay = [ev for ev in eng.events.values() if eng._inplay(ev, now)]
    q = [c for ev in inplay for c in ev.sides if eng.markets[c].quotable]
    on = {c: eng.ledgers["B1"].state.get(c, {}) for c in q}
    non = sum(1 for s in on.values() if s.get("k") is not None)
    L.append(f" feed: {info.get('conns', 0)} sockets, {eng.cnt.get('msg_pc', 0) + eng.cnt.get('msg_book', 0):,} book msgs, "
             f"{eng.cnt.get('msg_trade', 0):,} trades, {info.get('reconnects', 0)} reconnects   in play: {len(inplay)} matches, "
             f"{len(q)} quotable side markets, signal on: {non}")
    L.append("")
    hdr = (f" {'book':<11}{'fills':>6}{'matches':>8}{'$ filled':>11}{'realised':>12}{'unrealised':>12}{'equity':>13}"
           f"{'quotes':>8}{'c/sh (res.)':>13}   note")
    L.append(C["b"] + hdr + C["x"])
    for name, g in eng.ledgers.items():
        s = eng.book_stats(g)
        net = f"{s['net_c_per_share']:+.2f}" if s["net_c_per_share"] is not None else "-"
        note = g.v.label
        if g.v.kind == "taker":
            ms = s.get("median_slip_c")
            note += f"; misses {s['taker_misses']}" + (f", median slip {ms:+.1f}c" if ms is not None else "")
        row = (f" {name:<11}{s['fills']:>6}{s['matches']:>8}{('$' + format(s['usd_filled'], ',.2f')):>11}"
               f"{rpad(money(s['realised']), 12)}{rpad(money(s['unrealised']), 12)}"
               f"{('$' + format(s['equity'], ',.2f')):>13}{s['open_quotes']:>8}{net:>13}   {C['d']}{note}{C['x']}")
        L.append(row)
    L.append(f" {C['d']}starting capital ${eng.capital:,.0f} per book; P&L marked to the token mid until resolution; "
             f"maker fills pay no fee and earn the 15% rebate; taker fills pay 0.05*p(1-p){C['x']}")
    L.append("")
    L.append(C["b"] + " Open quotes (B1)" + C["x"])
    rows = []
    for cond, lst in eng.ledgers["B1"].orders.items():
        for o in lst:
            if o.status in ("pending", "active") and (o.c is None or o.c > now):
                m = eng.markets[cond]
                rows.append((o, m))
    if not rows:
        L.append(f"   {C['d']}none (quotes appear when the moneyline-implied side move reaches 4c){C['x']}")
    for o, m in rows[:8]:
        ev = eng.events.get(m.eid)
        L.append(f"   {short_title(ev):<34} {smt_short(m.smt):<16} bid {str(m.outs[o.k])[:18]:<18} @ {o.P:.2f} x {o.R:>7.2f}"
                 f"  queue ahead {o.q():>8.1f}  impl {o.impl * 100:+.1f}c  {o.status}")
    L.append("")
    L.append(C["b"] + " Signals: moneyline-implied side moves (B1 view, largest first)" + C["x"])
    sigs = []
    for c in q:
        s = eng.sig_on.get(c)
        if s and s.get("impl") is not None and s.get("q_ref") is not None:
            sigs.append((abs(s["impl"]), c, s))
    sigs.sort(reverse=True)
    if not sigs:
        L.append(f"   {C['d']}waiting for in-play prints{C['x']}")
    for _, c, s in sigs[:6]:
        m = eng.markets[c]
        ev = eng.events.get(m.eid)
        flag = f"{C['g']}ON{C['x']}" if s["k"] is not None else f"{C['d']}off{C['x']}"
        L.append(f"   {short_title(ev):<34} {smt_short(m.smt):<16} side {s['q_ref']:.2f} -> implied {s['qimp']:.2f} "
                 f"({s['impl'] * 100:+5.1f}c)  moneyline {s['p_ref']:.2f}->{s['p_now']:.2f}  b {s['b']:.2f}  {flag}")
    L.append("")
    L.append(C["b"] + " Fills tape (all books)" + C["x"])
    tape = [d for d in out.tape if d.get("ev") in ("fill", "taker_miss")][-10:]
    if not tape:
        L.append(f"   {C['d']}no fills yet{C['x']}")
    for d in tape:
        ev = eng.events.get(d.get("eid") or eng.markets.get(d.get("cond"), Market("", "", "", (), ())).eid)
        if d["ev"] == "fill":
            L.append(f"   {iso(d['e'])[11:19]}  {d['book']:<10} {short_title(ev, 26):<26} {smt_short(d['smt']):<15} "
                     f"BUY {str(d['outcome'])[:16]:<16} {d['shares']:>8.2f} @ {d['px']:.3f} = ${d['usd']:>7.2f}  {d['kind']}")
        else:
            L.append(f"   {d['t'][11:19]}  {d['book']:<10} taker order missed: ask moved above the limit "
                     f"{d['limit']:.2f} during latency + 1 s venue delay (seen ask {d.get('ask_seen')})")
    errs = list(eng.errors)[-2:]
    if errs:
        L.append(f" {C['r']}engine errors (logged, not fatal): {errs}{C['x']}")
    L.append(f" {C['d']}log {out.path.relative_to(ROOT)}"
             + (f"   raw {out.raw_path.relative_to(ROOT)}" if out.raw_path else "") + f"{C['x']}")
    return "\n".join(x[: W + 60] for x in L)


# ============================================================================ discovery (gamma)
GAMMA_PAGE = 100          # Gamma caps /events pages at 100 rows whatever `limit` asks for (DEVIATIONS_LIVE.md L11)
GAMMA_MAX_PAGES = 100


def gamma_universe(sess, back_h=8.0, fwd_h=3.0, get=None, stats=None) -> tuple[dict, dict]:
    """Open ATP/WTA/Challenger singles events starting in [now - back_h, now + fwd_h]: meta dicts.

    Pages through every open tennis event: offset advances by the rows actually returned, and paging stops only on
    an empty page (or a page with no new event id), so a server-side cap on the page size cannot truncate the
    universe. A failed page raises, so discovery never updates from a partial list."""
    get = get or http_get
    t = time.time() * 1000
    evs, seen, off, pages = [], set(), 0, 0
    for _ in range(GAMMA_MAX_PAGES):
        page = get(sess, GAMMA, {"tag_slug": "tennis", "active": "true", "closed": "false",
                                 "limit": GAMMA_PAGE, "offset": off})
        if page is None:
            raise RuntimeError(f"gamma /events page at offset {off} failed")
        if not isinstance(page, list) or not page:
            break
        pages += 1
        new = [e for e in page if str(e.get("id")) not in seen]
        if not new:
            break
        for e in new:
            seen.add(str(e.get("id")))
        evs += new
        off += len(page)
    if stats is not None:
        stats.update(gamma_pages=pages, gamma_events=len(evs))
    return events_meta(evs, t, back_h, fwd_h)


def events_meta(evs, t, back_h=8.0, fwd_h=3.0, ids=None):
    E, M = {}, {}
    for e in evs:
        series = (e.get("seriesSlug") or "").lower()
        title = e.get("title") or ""
        if series not in SERIES or "doubles" in title.lower():
            continue
        st = parse_ts(e.get("startTime"))
        if st is None:
            continue
        if ids is None and not (-fwd_h * 3.6e6 <= t - st <= back_h * 3.6e6):
            continue
        eid = str(e.get("id"))
        end = parse_ts(e.get("finishedTimestamp")) or parse_ts(e.get("closedTime"))
        if end is None and e.get("ended") is True:
            end = int(t)
        E[eid] = {"title": title, "series": series, "start_ms": st, "end_ms": end, "slug": e.get("slug")}
        ml = next((m for m in e.get("markets") or [] if m.get("sportsMarketType") == "moneyline"), None)
        ml_fee = ((ml or {}).get("feeSchedule") or {}).get("rate")
        ml_delay = (ml or {}).get("secondsDelay")
        for m in e.get("markets") or []:
            smt = m.get("sportsMarketType")
            if smt != "moneyline" and smt not in B_T:
                continue
            try:
                toks = json.loads(m.get("clobTokenIds") or "[]")
                outs = json.loads(m.get("outcomes") or "[]")
                prices = json.loads(m.get("outcomePrices") or "[]")
            except (TypeError, ValueError):
                continue
            if len(toks) != 2:
                continue
            fs = m.get("feeSchedule") or {}
            fee = fs.get("rate", ml_fee)
            delay = m.get("secondsDelay", ml_delay)
            p0 = None
            if m.get("closed") and len(prices) == 2:
                try:
                    pr = (float(prices[0]), float(prices[1]))
                    if pr in ((1.0, 0.0), (0.0, 1.0), (0.5, 0.5)):
                        p0 = pr[0]
                except (TypeError, ValueError):
                    pass
            M[m.get("conditionId")] = {
                "eid": eid, "smt": smt, "toks": [str(x) for x in toks], "outs": outs,
                "delay_ms": int(float(delay if delay is not None else 1) * 1000),
                "fee_rate": float(fee) if fee is not None else 0.0,
                "rebate_rate": float(fs.get("rebateRate")) if fs.get("rebateRate") is not None else None,
                "tick": float(m.get("orderPriceMinTickSize") or 0.01), "min_size": float(m.get("orderMinSize") or 5),
                "closed": bool(m.get("closed")), "p0": p0}
    return E, M


def http_get(sess, url, params, tries=6):
    for k in range(tries):
        try:
            r = sess.get(url, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(30.0, 0.5 * 2 ** k))
                continue
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            time.sleep(min(30.0, 0.5 * 2 ** k))
    return None


def data_trades(sess, cond, max_pages=21):
    out = []
    for off in range(0, 500 * max_pages, 500):
        page = http_get(sess, DATA_TRADES, {"market": cond, "limit": 500, "offset": off})
        if not isinstance(page, list) or not page:
            break
        out += page
        if len(page) < 500:
            break
    return out


# ============================================================================ live runner
class Live:
    def __init__(self, a, eng: Engine, out: Out, kind: str, run: str):
        import requests
        self.a, self.eng, self.out, self.kind, self.run = a, eng, out, kind, run
        self.sess = requests.Session()
        self.sess.headers.update({"User-Agent": UA, "Accept": "application/json"})
        self.inq = []
        self.conns = []
        self.subscribed = set()
        self.reconnects = 0
        self.L_drain = L_FLOOR_MS
        self.half_rtt = deque()
        self.stopping = False
        self.http_sem = asyncio.Semaphore(4)
        self.ws_trades = []          # warm-up: (cond, tok, i, p, size, side, e)
        self.check = {"matched": 0, "agree": 0, "disagree": 0, "offset_ms": None, "passed": False,
                      "convention": None, "need": a.warmup_trades, "checked_conds": 0, "raw_2s": 0}
        self.status = "warm-up"
        self.started_ms = now_ms()
        self.booted = set()
        self.meta_E, self.meta_M = {}, {}
        self.res_polled = 0.0
        self.start_key = None
        self.stop_ms = None
        self.final_ms = None
        self.lag_win = defaultdict(list)      # socket -> [rt - e] over the current minute (pc and trade only)
        self.lag_t = time.time()
        self.lag_ep: dict = {}                # socket -> open lag episode
        self.lag_stats = {"episodes": 0, "max_ms": 0, "minutes": 0, "p99_max_ms": 0}
        self.gap_count = 0

    def post(self, kind, payload, rt=None, conn=None):
        self.inq.append((rt or now_ms(), kind, payload, conn))

    async def hget(self, fn, *args):
        async with self.http_sem:
            return await asyncio.to_thread(fn, self.sess, *args)

    # -------------------------------------------------------------- discovery and subscriptions
    async def discover_loop(self):
        while not self.stopping:
            t0 = time.time()
            try:
                gst = {}
                E, M = await self.hget(gamma_universe, 8.0, 3.0, None, gst)
                newE = {k: v for k, v in E.items() if self.meta_E.get(k) != v}
                newM = {k: v for k, v in M.items() if self.meta_M.get(k) != v}
                self.meta_E.update(E)
                self.meta_M.update(M)
                if newE or newM:
                    self.post("meta", {"events": newE, "markets": newM})
                toks = []
                for cond, m in M.items():
                    if not m["closed"]:
                        toks += [t for t in m["toks"] if t not in self.subscribed]
                if toks:
                    self.subscribe(toks)
                self.out.event({"ev": "discovery", "key": now_ms(), "events": len(E), "markets": len(M),
                                "new_events": len(newE), "new_tokens": len(toks), **gst})
                if self.check["passed"]:
                    await self.bootstrap_inplay()
            except Exception as ex:
                self.out.event({"ev": "discovery_error", "key": now_ms(), "err": repr(ex)[:300]})
            await asyncio.sleep(max(1.0, 120 - (time.time() - t0)))

    def subscribe(self, toks):
        # keep a market's two tokens on the same socket
        toks = list(dict.fromkeys(toks))
        while toks:
            c = self.conns[-1] if self.conns and len(self.conns[-1]["toks"]) < MAX_TOK_PER_CONN else None
            if c is None:
                c = {"idx": len(self.conns), "toks": [], "pending": [], "last_e": None, "gap_from": None}
                self.conns.append(c)
                asyncio.get_running_loop().create_task(self.conn_loop(c))
            room = MAX_TOK_PER_CONN - len(c["toks"])
            take, toks = toks[:room], toks[room:]
            c["toks"] += take
            c["pending"] += take
            self.subscribed.update(take)

    async def conn_loop(self, c):
        import websockets
        backoff = 1.0
        first = True
        while not self.stopping:
            try:
                async with websockets.connect(MARKET_WS, ping_interval=None, max_size=None, open_timeout=20,
                                              close_timeout=5) as ws:
                    await ws.send(json.dumps({"assets_ids": list(c["toks"]), "type": "market",
                                              "custom_feature_enabled": True}))
                    c["pending"] = []
                    if not first:
                        self.reconnects += 1
                        self.out.event({"ev": "reconnect", "key": now_ms(), "conn": c["idx"]})
                    first = False
                    backoff = 1.0
                    last_ping = 0.0
                    ping_t = None
                    last_msg = time.time()
                    gap_pending = c["gap_from"] is not None
                    while not self.stopping:
                        if c["pending"]:
                            add, c["pending"] = c["pending"], []
                            await ws.send(json.dumps({"assets_ids": add, "type": "market", "operation": "subscribe",
                                                      "custom_feature_enabled": True}))
                        if time.time() - last_ping > 10:
                            await ws.send("PING")
                            last_ping = ping_t = time.time()
                        if time.time() - last_msg > 45:
                            raise TimeoutError("idle socket")
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        rt = now_ms()
                        last_msg = time.time()
                        c["last_rt"] = rt
                        if msg == "PONG":
                            if ping_t:
                                self.on_rtt((time.time() - ping_t) * 1000)
                                ping_t = None
                            continue
                        try:
                            d = json.loads(msg)
                        except ValueError:
                            self.eng.cnt["ws_malformed"] += 1
                            continue
                        self.post("ws", d, rt, c["idx"])
                        if gap_pending:
                            gap_pending = False
                            self.schedule_backfill(c, rt)
            except Exception as ex:
                self.out.event({"ev": "socket_error", "key": now_ms(), "conn": c["idx"], "err": repr(ex)[:200]})
                if c["gap_from"] is None:
                    c["gap_from"] = now_ms()
                    # engine input (raw-logged, so a replay reproduces it): quotes on this socket's markets are
                    # pulled at the last venue timestamp seen on it; pending taker orders there are voided (L13)
                    self.gap_count += 1
                    self.post("gap", {"conn": c["idx"], "toks": list(c["toks"]), "phase": "socket_error",
                                      "lo_rt": c.get("last_rt"), "err": repr(ex)[:120]})
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 2)

    def on_rtt(self, rtt_ms):
        t = time.time()
        self.half_rtt.append((t, rtt_ms / 2))
        while self.half_rtt and self.half_rtt[0][0] < t - 600:
            self.half_rtt.popleft()
        med = statistics.median(x for _, x in self.half_rtt)
        L = max(L_FLOOR_MS, int(round(med)))
        self.ping_ms = med
        self.out.event({"ev": "latency", "key": now_ms(), "rtt_ms": round(rtt_ms, 1), "half_rtt_median": round(med, 1), "L": L})
        if L != self.L_drain:
            self.L_drain = L
            self.post("lat", {"L": L, "half_rtt_median": med})

    def schedule_backfill(self, c, rt):
        lo, hi = c["gap_from"], rt
        c["gap_from"] = None
        if not self.check["passed"] or hi - lo < 3000:
            return
        conds = {self.eng.tok[t][0] for t in c["toks"] if t in self.eng.tok}
        conds = [x for x in conds if self.eng._inplay(self.eng.events.get(self.eng.markets[x].eid), hi)]
        self.out.event({"ev": "backfill", "key": now_ms(), "conn": c["idx"], "lo": iso(lo), "hi": iso(hi), "markets": len(conds)})
        for cond in conds:
            asyncio.get_running_loop().create_task(self.boot_one(cond, lo - 5000, hi, 2))

    # -------------------------------------------------------------- data-api history
    def api_prints(self, rows, cond):
        m = self.eng.markets.get(cond)
        if m is None:
            return []
        off = self.check["offset_ms"] or 0
        out = []
        for r in rows:
            try:
                oi = int(r.get("outcomeIndex"))
                p = float(r.get("price"))
                q0 = r6(p if oi == 0 else 1 - p)
                at_ask = (r.get("side") == "BUY") == (oi == 0)
                out.append([int(r["timestamp"]) * 1000 - off, q0, at_ask, float(r.get("size"))])
            except (TypeError, ValueError, KeyError):
                continue
        out.sort(key=lambda x: x[0])
        return out

    async def boot_one(self, cond, lo=None, hi=None, pages=21):
        rows = await self.hget(data_trades, cond, pages)
        if rows is None:
            self.out.event({"ev": "boot_error", "key": now_ms(), "cond": cond})
            return
        self.post("boot", {"cond": cond, "prints": self.api_prints(rows, cond), "lo": lo, "hi": hi})

    async def bootstrap_inplay(self):
        tasks = []
        t = now_ms()
        for eid, e in self.meta_E.items():
            if eid in self.booted or e["start_ms"] > t:
                continue
            self.booted.add(eid)
            fe = [self.eng.first_k.get(c) for c, m in self.meta_M.items() if m["eid"] == eid]
            if fe and all(x is not None and x <= e["start_ms"] for x in fe):
                continue                                  # subscribed before the start: the socket has it all
            for cond, m in self.meta_M.items():
                if m["eid"] == eid and (m["smt"] == "moneyline" or m["smt"] in B_T):
                    tasks.append(self.boot_one(cond))
        if tasks:
            self.out.event({"ev": "bootstrap", "key": now_ms(), "markets": len(tasks)})
            await asyncio.gather(*tasks)

    # -------------------------------------------------------------- warm-up: trade-side convention (PREREG 3.1)
    async def warmup_loop(self):
        checked = {}
        while not self.stopping and not self.check["passed"]:
            await asyncio.sleep(30)
            t = now_ms()
            by = defaultdict(list)
            for tr in self.ws_trades:
                if t - tr["e"] > 20_000:
                    by[tr["cond"]].append(tr)
            todo = [c for c in by if checked.get(c, 0) < len(by[c])]
            if not todo:
                self.status = f"warm-up: waiting for trades ({len(self.ws_trades)} seen)"
                continue
            res = await asyncio.gather(*[self.hget(data_trades, c, 1) for c in todo])
            pairs = []
            for cond, rows in zip(todo, res):
                checked[cond] = len(by[cond])
                for tr in by[cond]:
                    for r in rows or []:
                        try:
                            if abs(float(r["size"]) - tr["size"]) > 1e-6:
                                continue
                            oi = int(r["outcomeIndex"])
                            p0_api = float(r["price"]) if oi == 0 else 1 - float(r["price"])
                            if abs(p0_api - tr["q0"]) > 1e-6:
                                continue
                            dts = int(r["timestamp"]) * 1000 - tr["e"]
                            if -5000 <= dts <= 15000:
                                pairs.append((tr, r, dts))
                        except (TypeError, ValueError, KeyError):
                            continue
            # one api record per ws trade: the closest in time; offset = median lag (block time vs match time)
            best = {}
            for tr, r, dts in pairs:
                k = id(tr)
                if k not in best or abs(dts) < abs(best[k][2]):
                    best[k] = (tr, r, dts)
            if not best:
                continue
            off = statistics.median(x[2] for x in best.values())
            agree = dis = raw2 = 0
            for tr, r, dts in best.values():
                if abs(dts) <= 2000:
                    raw2 += 1
                if abs(dts - off) > 2000:
                    continue
                oi = int(r["outcomeIndex"])
                at_api = (r.get("side") == "BUY") == (oi == 0)
                at_ws = (tr["side"] == "BUY") == (tr["i"] == 0)
                agree += at_api == at_ws
                dis += at_api != at_ws
            n = agree + dis
            self.check.update(matched=n, agree=agree, disagree=dis, offset_ms=int(off), checked_conds=len(checked),
                              raw_2s=raw2)
            self.status = f"warm-up: trade-side check {n}/{self.a.warmup_trades} matched, agree {agree}"
            self.out.event({"ev": "warmup", "key": now_ms(), **self.check})
            if n >= self.a.warmup_trades:
                if agree / n >= 0.95:
                    self.check.update(passed=True, convention="ws side = taker side (as data-api)")
                elif dis / n >= 0.95:
                    self.check.update(passed=True, convention="ws side = maker side (flipped)")
                    self.post("flip", {"flip": True})
                else:
                    self.status = "ABORT: neither side convention reaches 95% (PREREG 3.1); session not started"
                    self.out.event({"ev": "warmup_failed", "key": now_ms(), **self.check})
                    self.stopping = True
                    return
                self.out.event({"ev": "warmup", "key": now_ms(), **self.check})
                await self.bootstrap_inplay()
                await asyncio.sleep(3)                   # let the boot inputs drain first
                self.start_session()

    def start_session(self):
        a = self.a
        t = now_ms()
        stop = None
        if a.until:
            stop = parse_ts(a.until)
        if a.minutes:
            stop = min(stop or 10 ** 15, t + int(a.minutes * 60_000))
        self.stop_ms = stop
        head = git_head()
        info = {"run": self.run, "commit": head, "until": iso(stop), "warmup": dict(self.check),
                "variants": [v.name for v in VARIANTS], "stop_ms": stop, "kind": self.kind}
        self.post("start", info)
        self.start_key = t
        self.status = "QUOTING (paper)"
        label = "TEST run (not the pre-registered session)" if self.kind == "test" else "session (B)"
        peek(f"maker v1 live paper {label} START: run={self.run} commit={head} until={iso(stop)} "
             f"(PREREG research/v2/maker/PREREG.md section 3; paper only, public data)")

    def on_drained_ws(self, d):
        evs, bad = normalize(d)
        self.eng.cnt["ws_bad_items"] += bad
        if not self.check["passed"]:
            for ev in evs:
                if ev[0] == "trade" and ev[2] in self.eng.tok:
                    cond, i = self.eng.tok[ev[2]]
                    p = ev[3]
                    self.ws_trades.append({"cond": cond, "tok": ev[2], "i": i, "p": p, "q0": p if i == 0 else r6(1 - p),
                                           "size": ev[4], "side": (ev[5] or "").upper(), "e": ev[1]})
        return evs

    # -------------------------------------------------------------- feed lag (receive time - venue time)
    def on_lag(self, conn, lag, rt):
        """Per-socket feed lag, rt - e, on price changes and trades (L13). Logged as per-minute quantiles and as
        episodes (lag > 2 s until it is back under 0.5 s), with the paper orders live on that socket's markets."""
        self.lag_win[conn].append(lag)
        ep = self.lag_ep.get(conn)
        if ep is None and lag > LAG_EPISODE_MS:
            ep = self.lag_ep[conn] = {"conn": conn, "from_rt": rt, "max_ms": lag, "n": 1,
                                      "live_orders": self.live_orders_on(conn)}
            self.lag_stats["episodes"] += 1
            self.out.event({"ev": "lag_episode_start", "key": rt, **ep})
        elif ep is not None:
            ep["max_ms"] = max(ep["max_ms"], lag)
            ep["n"] += 1
            if lag < LAG_CLEAR_MS:
                self.out.event({"ev": "lag_episode_end", "key": rt, **ep, "to_rt": rt,
                                "dur_ms": rt - ep["from_rt"]})
                del self.lag_ep[conn]
        self.lag_stats["max_ms"] = max(self.lag_stats["max_ms"], lag)

    def live_orders_on(self, conn):
        conds = {self.eng.tok[t][0] for t, cc in self.eng.tok_conn.items() if cc == conn and t in self.eng.tok}
        mk = sum(1 for g in self.eng.makers for cd in conds for o in g.orders.get(cd, []) if o.live())
        tk = sum(1 for g in self.eng.ledgers.values() if g.v.kind == "taker" for cd in conds
                 for o in g.torders.get(cd, []) if o.status == "pending")
        return {"maker": mk, "taker_pending": tk}

    def flush_lag(self, tt):
        self.lag_t = tt
        for conn, xs in self.lag_win.items():
            if not xs:
                continue
            xs = sorted(xs)
            q = lambda f: xs[min(len(xs) - 1, int(f * len(xs)))]
            self.out.event({"ev": "lag", "key": now_ms(), "conn": conn, "n": len(xs), "p50_ms": q(0.5),
                            "p90_ms": q(0.9), "p99_ms": q(0.99), "max_ms": xs[-1]})
            self.lag_stats["p99_max_ms"] = max(self.lag_stats["p99_max_ms"], q(0.99))
        self.lag_stats["minutes"] += 1
        self.lag_win = defaultdict(list)

    # -------------------------------------------------------------- resolution polls
    async def resolution_loop(self):
        while not self.stopping:
            await asyncio.sleep(120)
            try:
                need = set()
                for g in self.eng.ledgers.values():
                    for f in g.fills:
                        if f["cond"] not in self.eng.payout0:
                            need.add(self.eng.markets[f["cond"]].eid)
                need = sorted(need)
                for i in range(0, len(need), 50):
                    evs = await self.hget(http_get, GAMMA, [("id", x) for x in need[i:i + 50]] + [("limit", 50)])
                    if not isinstance(evs, list):
                        continue
                    E, M = events_meta(evs, now_ms(), ids=True)
                    for cond, m in M.items():
                        if m.get("p0") is not None and cond not in self.eng.payout0 and cond in self.eng.markets:
                            self.post("res", {"cond": cond, "p0": m["p0"]})
                    endE = {k: {"end_ms": v["end_ms"], "title": v["title"]} for k, v in E.items() if v.get("end_ms")}
                    if endE:
                        self.post("meta", {"events": endE, "markets": {}})
            except Exception as ex:
                self.out.event({"ev": "resolution_poll_error", "key": now_ms(), "err": repr(ex)[:200]})

    # -------------------------------------------------------------- engine pump
    async def pump(self):
        eng = self.eng
        self.last_dash = self.last_sum = self.last_line = 0.0
        while True:
            await asyncio.sleep(0.02)
            try:
                if self.pump_once(eng):
                    break
            except Exception as ex:                # never crash: log and keep going
                eng.cnt["pump_errors"] += 1
                self.out.event({"ev": "pump_error", "key": now_ms(), "err": repr(ex)[:300],
                                "tb": traceback.format_exc(limit=4)[-800:]})
        self.write_summary(final=True)

    def pump_once(self, eng) -> bool:
        w = now_ms()
        batch, self.inq = self.inq, []
        for rt, kind, payload, conn in batch:
            if kind == "ws":
                evs = self.on_drained_ws(payload)
                self.out.rawrec({"w": w, "rt": rt, "L": self.L_drain, "c": conn, "m": payload})
                for ev in evs:
                    eng.push(max(ev[1] + self.L_drain, w), "wsc", (conn, ev))
                    if ev[0] in ("pc", "trade"):
                        self.on_lag(conn, rt - ev[1], rt)
            else:
                self.out.rawrec({"w": w, "kind": kind, "d": payload})
                eng.push(w, kind, payload)
        eng.run(upto=w)
        tt = time.time()
        if tt - self.lag_t >= 60:
            self.flush_lag(tt)
        if tt - self.last_sum > 10:
            self.last_sum = tt
            self.write_summary()
        if not self.a.no_dashboard and tt - self.last_dash > 1.0:
            self.last_dash = tt
            sys.stdout.write("\x1b[H\x1b[2J" + render(eng, self.dinfo(), self.out) + "\n")
            sys.stdout.flush()
        if self.a.no_dashboard and tt - self.last_line > 60:
            self.last_line = tt
            s = eng.book_stats(eng.ledgers["B1"])
            print(f"{iso(w)} {self.status} | L {eng.L} ms | msgs {sum(v for k, v in eng.cnt.items() if k.startswith('msg_')):,} "
                  f"| B1 fills {s['fills']} ${s['usd_filled']:.2f} pnl {s['pnl']:+.2f} quotes {s['open_quotes']}", flush=True)
        if self.stop_ms and w > self.stop_ms + 1000 and self.status.startswith("QUOTING"):
            self.status = "settling (quoting stopped)"
            self.final_ms = w + int(self.a.settle_hours * 3.6e6)
        if self.final_ms and (w >= self.final_ms or self.all_resolved()):
            return True
        if self.stopping and not self.check["passed"]:
            return True
        return False

    def all_resolved(self):
        for g in self.eng.ledgers.values():
            for f in g.fills:
                if f["cond"] not in self.eng.payout0:
                    return False
        return True

    def dinfo(self):
        return {"mode": "LIVE", "status": self.status, "conns": len(self.conns), "reconnects": self.reconnects,
                "ping_ms": getattr(self, "ping_ms", None)}

    def write_summary(self, final=False):
        info = {"mode": "LIVE", "kind": self.kind, "run": self.run, "status": "final" if final else self.status,
                "started_process": iso(self.started_ms), "warmup": self.check, "sockets": len(self.conns),
                "reconnects": self.reconnects, "feed_gaps": self.gap_count, "feed_lag": self.lag_stats,
                "raw_log": str(self.out.raw_path.relative_to(ROOT)),
                "event_log": str(self.out.path.relative_to(ROOT)), "settle_until": iso(self.final_ms)}
        s = summary(self.eng, info)
        txt = json.dumps(s, indent=1, default=str)
        p = self.out.dir / "summary.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(txt)
        tmp.replace(p)
        (self.out.dir / f"{self.kind}_{self.run}_summary.json").write_text(txt)
        if final and self.kind == "session":
            (self.out.dir / "FINAL").write_text(json.dumps({"run": self.run, "written": iso(now_ms())}) + "\n")

    async def main(self):
        loop = asyncio.get_running_loop()
        for sg in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sg, self.on_signal)
            except NotImplementedError:
                pass
        tasks = [loop.create_task(self.discover_loop()), loop.create_task(self.warmup_loop()),
                 loop.create_task(self.resolution_loop())]
        try:
            await self.pump()
        finally:
            self.stopping = True
            for t in tasks:
                t.cancel()

    def on_signal(self):
        if self.final_ms is None:
            self.status = "stopping (signal)"
            self.post("stop", {"why": "signal"})
            self.stop_ms = now_ms()
            self.final_ms = now_ms() + 1500
        else:
            self.final_ms = now_ms()


# ============================================================================ replay
def load_clobmeta(dirpath: Path) -> dict:
    """live_v2 recorder: run tag -> {int idx: token meta}."""
    out = defaultdict(dict)
    for f in sorted(dirpath.glob("clobmeta_*")):
        m = re.match(r"clobmeta_(\d{8}_\d{4})_", f.name)
        if not m:
            continue
        op = gzip.open if f.name.endswith(".gz") else open
        try:
            with op(f, "rt") as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    for k, v in (d.get("tokens") or {}).items():
                        out[m.group(1)][int(k)] = v
        except (EOFError, OSError):
            pass
    return out


def meta_from_tokens(toks: list[dict]) -> tuple[dict, dict]:
    """Build engine meta from recorder token meta. Venue parameters the recorders did not store are set to the
    values Gamma showed on every open tennis market on 2026-10-03 (VENUE_RULES.md): secondsDelay 1, fee 0.05,
    rebate 0.15, min size 5."""
    E, M = {}, {}
    by = defaultdict(dict)
    for t in toks:
        by[t.get("cond")][int(t.get("oi", 0))] = t
    for cond, d in by.items():
        if len(d) != 2 or cond is None:
            continue
        t0 = d[0]
        slug = t0.get("slug") or ""
        series = slug.split("-")[0]
        smt = t0.get("smt") or "moneyline"
        if series not in SERIES or "doubles" in slug or (smt != "moneyline" and smt not in B_T):
            continue
        eid = str(t0.get("event_id") or slug)
        E[eid] = {"title": t0.get("title") or slug, "series": series, "start_ms": parse_ts(t0.get("start")),
                  "end_ms": None}
        M[cond] = {"eid": eid, "smt": smt, "toks": [d[0]["tok"], d[1]["tok"]],
                   "outs": [d[0].get("outcome"), d[1].get("outcome")], "delay_ms": 1000, "fee_rate": 0.05,
                   "rebate_rate": 0.15, "tick": float(t0.get("tick") or 0.01), "min_size": 5.0, "closed": False}
    return E, M


def replay_items(files: list[str], clock: str, L0: int):
    """Yield (key, kind, payload) in file order for own raw logs and live_v2 / data/live recordings."""
    metas = {}
    for f in files:
        name = os.path.basename(f)
        op = gzip.open if f.endswith(".gz") else open
        p = Path(f)
        if name.startswith("clob_"):
            tag = re.match(r"clob_(\d{8}_\d{4})_", name).group(1)
            if p.parent not in metas:
                metas[p.parent] = load_clobmeta(p.parent)
            idx = metas[p.parent].get(tag, {})
            tokmeta = [{**v, "tok": v["tok"]} for v in idx.values()]
            E, M = meta_from_tokens(tokmeta)
            yield None, "meta", {"events": E, "markets": M}
            keep = {t for m in M.values() for t in m["toks"]}
            tokof = {i: v["tok"] for i, v in idx.items() if v["tok"] in keep}
            with op(f, "rt") as fh:
                try:
                    for line in fh:
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        e = d.get("e")
                        rt = d.get("rt") or 0
                        ts = d.get("ts") or (d.get("raw") or {}).get("timestamp")
                        try:
                            ts = int(ts)
                        except (TypeError, ValueError):
                            continue
                        if e == "pc":
                            ch = [(tokof[c[0]], r6(c[1]), float(c[2]), "BUY" if c[3] == "B" else "SELL")
                                  for c in d["c"] if c[0] in tokof]
                            ev = ("pc", ts, ch) if ch else None
                        elif e == "b":
                            ev = ("book", ts, tokof[d["a"]], [(r6(x), float(s)) for x, s in d["b"]],
                                  [(r6(x), float(s)) for x, s in d["k"]]) if d["a"] in tokof else None
                        elif e == "t":
                            ev = ("trade", ts, tokof[d["a"]], r6(d["p"]), float(d["s"]), d.get("side")) if d["a"] in tokof else None
                        elif e == "market_resolved":
                            raw = d.get("raw") or {}
                            ev = ("resolved", ts, raw.get("market"), str(raw.get("winning_asset_id")))
                        else:
                            ev = None
                        if ev is None:
                            continue
                        key = ts + L0 if clock == "server" else max(ts + L0, rt)
                        yield key, "ws", ev
                except (EOFError, OSError, zlib.error):
                    pass
        elif name.startswith("raw_"):
            with op(f, "rt") as fh:
                try:
                    for line in fh:
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        if "m" in d:
                            evs, _ = normalize(d["m"])
                            for ev in evs:
                                key = ev[1] + d["L"] if clock == "server" else max(ev[1] + d["L"], d["w"])
                                yield key, "wsc", (d.get("c"), ev)
                        else:
                            yield d["w"], d["kind"], d["d"]
                except (EOFError, OSError, zlib.error):
                    pass
        elif name.startswith("market_"):
            tf = sorted(p.parent.glob("tokens_*"))
            tokmeta = []
            for t in tf:
                top = gzip.open if t.name.endswith(".gz") else open
                try:
                    with top(t, "rt") as fh:
                        for line in fh:
                            try:
                                for tok, v in json.loads(line).get("tokens", {}).items():
                                    tokmeta.append({**v, "tok": tok, "smt": "moneyline"})
                            except ValueError:
                                continue
                except (EOFError, OSError):
                    pass
            # moneyline-only recorder (src/live_recorder.py): outcome index = order of appearance per market
            uniq, seen = {}, defaultdict(int)
            for v in tokmeta:
                if v["tok"] in uniq:
                    continue
                v["oi"] = seen[v["cond"]]
                seen[v["cond"]] += 1
                v["event_id"] = v.get("slug")
                uniq[v["tok"]] = v
            E, M = meta_from_tokens([v for v in uniq.values() if v["oi"] < 2])
            yield None, "meta", {"events": E, "markets": M}
            with op(f, "rt") as fh:
                try:
                    for line in fh:
                        try:
                            d = json.loads(line)
                        except ValueError:
                            continue
                        evs, _ = normalize(d)
                        for ev in evs:
                            key = ev[1] + L0 if clock == "server" else max(ev[1] + L0, d.get("rt") or 0)
                            yield key, "ws", ev
                except (EOFError, OSError, zlib.error):
                    pass


def last_w(files):
    w = None
    for f in files:
        op = gzip.open if f.endswith(".gz") else open
        try:
            with op(f, "rt") as fh:
                for line in fh:
                    try:
                        w = json.loads(line).get("w", w)
                    except ValueError:
                        continue
        except (EOFError, OSError, zlib.error):
            pass
    return w


def run_replay(a, kind, run):
    files = sorted(set(sum((glob.glob(g) for g in a.replay.split(",")), [])))
    if not files:
        raise SystemExit(f"no files match {a.replay}")
    out = Out(kind, run, raw=False)
    eng = Engine(capital=a.capital, sink=out.event, align_fn=_align())
    own = all(os.path.basename(f).startswith("raw_") for f in files)
    lo = parse_ts(a.replay_from) if a.replay_from else None
    hi = lo + int(a.replay_minutes * 60_000) if (lo and a.replay_minutes) else None
    items, first = [], None
    for key, k, payload in replay_items(files, a.clock, L_FLOOR_MS):
        if key is None:
            items.append((None, k, payload))
            continue
        if hi is not None and key > hi + int(a.settle_hours or 0) * 3_600_000:
            continue
        items.append((key, k, payload))          # messages before the window still build the in-match history
        if first is None or key < first:
            first = key
    if first is None:
        raise SystemExit("no messages in the selected window")
    for key, k, payload in items:
        eng.push(first if key is None else key, k, payload)
    q0 = max(first, lo) if lo else first
    if not own:
        stop = hi
        if a.minutes:
            stop = min(stop or 10 ** 15, q0 + int(a.minutes * 60_000))
        eng.push(q0, "start", {"run": run, "kind": kind, "replay": a.replay, "stop_ms": stop,
                               "note": "replay of recorded live data; no warm-up (offline); history from "
                                       f"{iso(first)}, quoting from {iso(q0)}"})
    peek(f"maker v1 live paper engine REPLAY ({'B2: own raw log' if own else 'recorded live data'}) on {a.replay}"
         f" window={iso(lo)}+{a.replay_minutes}min clock={a.clock}: run={run} commit={git_head()} "
         f"(engine test / descriptive; maker v1 frozen in PREREG c29734b, no rule change possible)")
    t0 = time.time()
    n = len(eng.heap)
    # an own raw log: the live engine never processed keys at or after its last drain time; neither do we
    end = last_w(files) if own else None
    if a.no_dashboard:
        eng.run(upto=end)
    else:
        while eng.heap and (end is None or eng.heap[0][0] < end):
            upto = eng.heap[0][0] + 60_000
            eng.run(upto=upto if end is None else min(upto, end))
            sys.stdout.write("\x1b[H\x1b[2J" + render(eng, {"mode": "REPLAY", "status": f"replay {iso(eng.key)[:19]}"}, out) + "\n")
            sys.stdout.flush()
            time.sleep(a.replay_pause)
    info = {"mode": "REPLAY", "kind": kind, "run": run, "replay": a.replay, "clock": a.clock, "items": n,
            "seconds": round(time.time() - t0, 1), "window_from": iso(first), "event_log": str(out.path.relative_to(ROOT))}
    s = summary(eng, info)
    (out.dir / f"{kind}_{run}_summary.json").write_text(json.dumps(s, indent=1, default=str))
    (out.dir / "replay_summary.json").write_text(json.dumps(s, indent=1, default=str))
    if a.no_dashboard:
        print(render(eng, {"mode": "REPLAY", "status": "replay finished"}, out))
    print(json.dumps({k: s[k] for k in ("now", "matches_in_play", "counters")}, default=str))
    for name, b in s["books"].items():
        print(f"{name:<11} fills {b['fills']:>4}  matches {b['matches']:>3}  $ {b['usd_filled']:>9.2f}  pnl {b['pnl']:+9.2f} "
              f"(realised {b['realised']:+.2f})  placed {b['placed']}  cancels {b['cancels']}  rejects {b['rejects']}")
    out.close()
    return eng, s


# ============================================================================ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--until", help="stop quoting at this UTC time, e.g. 2026-10-04T11:30:00Z")
    ap.add_argument("--minutes", type=float, help="stop quoting N minutes after the session starts")
    ap.add_argument("--capital", type=float, default=10_000.0, help="starting capital per paper book ($)")
    ap.add_argument("--no-dashboard", action="store_true", help="plain log lines instead of the terminal dashboard")
    ap.add_argument("--replay", help="glob(s), comma separated: data/live_maker/raw_*, data/live_v2/clob_*, data/live/market_*")
    ap.add_argument("--replay-from", help="replay window start (UTC ISO)")
    ap.add_argument("--replay-minutes", type=float, help="replay window length")
    ap.add_argument("--replay-pause", type=float, default=0.0, help="seconds to pause per replayed minute (dashboard)")
    ap.add_argument("--clock", choices=("recv", "server"), default="recv",
                    help="replay: seen time = max(e + L, receive time) (recv) or e + L (server)")
    ap.add_argument("--settle-hours", type=float, default=None,
                    help="after quoting stops, wait this long for resolutions (default 4.5 with --until, else 0)")
    ap.add_argument("--warmup-trades", type=int, default=50, help="trade-side check sample (PREREG: 50)")
    ap.add_argument("--test", action="store_true", help="label the run as a test (not the pre-registered session)")
    a = ap.parse_args(argv)
    check_frozen()
    run = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if a.replay:
        run_replay(a, "replay", run)
        return
    if a.settle_hours is None:
        a.settle_hours = 4.5 if a.until else 0.0
    kind = "test" if a.test else "session"
    out = Out(kind, run, raw=True)
    eng = Engine(capital=a.capital, sink=out.event, align_fn=_align())
    live = Live(a, eng, out, kind, run)
    out.event({"ev": "process_start", "key": now_ms(), "run": run, "pid": os.getpid(), "args": vars(a),
               "commit": git_head(), "frozen_files_ok": True, "b_t_sha256": B_T_SHA256})
    print(f"COURTSIDE live paper trader: PAPER ONLY, live public market data. run {run}, pid {os.getpid()}; "
          f"log {out.path.relative_to(ROOT)}", flush=True)
    try:
        asyncio.run(live.main())
    finally:
        live.write_summary(final=True)
        out.event({"ev": "process_end", "key": now_ms()})
        out.close()
        s = json.loads((out.dir / "summary.json").read_text())
        for name, b in s["books"].items():
            print(f"{name:<11} fills {b['fills']:>4}  matches {b['matches']:>3}  $ {b['usd_filled']:>9.2f}  "
                  f"pnl {b['pnl']:+9.2f} (realised {b['realised']:+.2f})", flush=True)


if __name__ == "__main__":
    main()
