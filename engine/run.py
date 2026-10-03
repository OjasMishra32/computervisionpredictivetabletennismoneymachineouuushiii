"""COURTSIDE runner. PAPER ONLY: nothing here (or anywhere in engine/) can sign, send or place an order.

  python -m engine.run --mode live-market --seconds 60
      Real Polymarket websockets, read-only (public `market` channel + public sports scores). Shows the
      books of live tennis matches and, every --every seconds, what the strategy WOULD do if a vision
      call arrived now for either player. No vision, no orders (not even paper ones).

  python -m engine.run --mode demo
      End to end: the vision engine runs on a real held-out table-tennis clip and emits CallEvents; the
      clip's timeline is mapped onto a RECORDED Polymarket WTA book (data/live/market_*) so each call
      triggers a paper decision against the real book at the right time relative to a real point.
      ILLUSTRATIVE PAIRING (different sport, different point): it shows mechanics and timing, not P&L.
      Writes results/engine/demo_run.json and results/engine/demo_timeline.png.

  python -m engine.run --mode backtest [--recompute]
      The tier-0 COUNTERFACTUAL backtest (src/tier0.py, scripts/tier0_backtest.py; another workstream).
      Prints its stored results, or re-runs the primary scenario through its own code (--recompute).

Mapping used by the demo (all numbers are written to demo_run.json):
    t_end   = T_official - stamp_lag          physical end of the real WTA point (stamp lag is NOT
                                              measured: 2.0 s = tier-0 primary, 3.14 s = inferred)
    t_frame = t_end - (f_end - f_call) / 120  the clip's point end (labelled frame f_end of its last
                                              clean MISS flight) is placed on t_end
    t_dec   = t_frame + measured vision latency (CallEvent.t_emit - t_frame) + camera latency (0)
    t_exec  = t_dec + one-way (67 ms Florida / 2 ms London) + 1 s venue delay -> fill vs the book then
"""
from __future__ import annotations

import argparse
import asyncio
import heapq
import itertools
import json
import math
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from engine.execution.paper import FLORIDA_MS, LONDON_MS, VENUE_DELAY_MS, Ledger, PaperExecutor  # noqa: E402
from engine.fair.value import CallEvent as PointCall  # noqa: E402
from engine.fair.value import MatchFair, home_is_outcome0, parse_score  # noqa: E402
from engine.market.clob import LiveClobFeed, ReplayClobFeed, iter_recorded, load_token_meta  # noqa: E402
from engine.risk.limits import RiskConfig, RiskManager  # noqa: E402
from engine.strategy import (CourtsideStrategy, LiveTradingForbidden, StrategyConfig,  # noqa: E402
                             assert_paper_only, calibration_job, enable_live_trading, fair_from_job)
from src.markov import Format, State  # noqa: E402

assert_paper_only()

OUT = REPO / "results" / "engine"
CLIP = REPO / "data" / "vision" / "test_2_copyts.mp4"
M1 = REPO / "research" / "v2" / "latency" / "out" / "m1_points.csv"
LAT_SUMMARY = REPO / "research" / "v2" / "latency" / "out" / "summary.json"
TIER0 = REPO / "results" / "tier0" / "results.json"
VISION_BENCH = OUT / "vision_bench.json"
SPORTS_WS = "wss://sports-api.polymarket.com/ws"   # public, unauthenticated score feed (read-only)
FPS = 120.0
CAPITAL = 28_000.0                                  # v2 capital base
REFRESH_ON_BOUNCE = True                            # recalibrate fair value on every BOUNCE call (see run_scenario)
ILLUSTRATIVE = ("ILLUSTRATIVE PAIRING: table-tennis ball-tracking calls (OpenTTGames test_2, held-out frames) "
                "are mapped onto a real recorded Polymarket WTA order book. Different sport, different point: this "
                "shows the engine's mechanics and timing against a real book. It is not a backtest and its P&L is "
                "not evidence of an edge. Paper only: no order was sent anywhere.")


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _clean(x):
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return None if not math.isfinite(x) else x
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def tour_of(slug: str, league: str | None = None) -> str:
    s = (league or slug or "").lower()
    for t in ("challenger", "wta", "atp"):
        if s.startswith(t) or t in s.split("-")[:1]:
            return t
    return "wta" if "wta" in s else "atp"


# =====================================================================================================
# (a) live market, read-only
# =====================================================================================================
async def _sports_listener(scores: dict, info: dict, stop: asyncio.Event) -> None:
    """Public Polymarket sports score feed: gameId -> latest {home, away, score, league, status}."""
    import websockets
    while not stop.is_set():
        try:
            async with websockets.connect(SPORTS_WS, ping_interval=None, max_size=None, open_timeout=10) as ws:
                info["connected"] = True
                while not stop.is_set():
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=2)
                    except asyncio.TimeoutError:
                        continue
                    if msg in ("ping", "PING"):
                        await ws.send("pong")
                        continue
                    try:
                        d = json.loads(msg)
                    except ValueError:
                        continue
                    for it in d if isinstance(d, list) else [d]:
                        if isinstance(it, dict) and it.get("gameId") is not None:
                            info["msgs"] = info.get("msgs", 0) + 1
                            scores[int(it["gameId"])] = {**it, "rt": _now_ms()}
        except asyncio.CancelledError:
            raise
        except Exception as ex:  # reconnect
            info.setdefault("errors", []).append(repr(ex)[:200])
            await asyncio.sleep(2)


def _score_by_names(scores: dict, names) -> dict | None:
    from engine.fair.value import _norm
    a, b = (set(_norm(n)) for n in names)
    for sc in scores.values():
        h, w = set(_norm(sc.get("homeTeam", ""))), set(_norm(sc.get("awayTeam", "")))
        if (a & h and b & w) or (a & w and b & h):
            return sc
    return None


def _markets_from_meta(meta: dict) -> dict[str, dict]:
    """condition id -> {tokens [outcome 0, outcome 1], names, slug, gameId} (meta in clobTokenIds order)."""
    out: dict[str, dict] = {}
    for tok, m in meta.items():
        c = m.get("cond")
        if not c:
            continue
        r = out.setdefault(c, {"tokens": [], "names": [], "slug": m.get("slug", ""), "gameId": m.get("gameId")})
        if tok not in r["tokens"]:
            r["tokens"].append(tok)
            r["names"].append(m.get("outcome", "?"))
    return {c: r for c, r in out.items() if len(r["tokens"]) == 2}


def _fmt_c(x) -> str:
    return "  n/a" if x is None else f"{100 * x:+5.1f}c"


def _what_if_line(d) -> str:
    who = d.winner_name or "?"
    if d.action == "SEND":
        return (f"if {who[:16]:16s} wins it: WOULD BUY {d.shares:5.0f} @<= {d.limit:.3f} (ask {d.ask:.3f}) "
                f"E[move] {_fmt_c(d.expected_move)} edge {_fmt_c(d.edge)}  {d.reason}")
    extra = f"E[move] {_fmt_c(d.expected_move)} edge {_fmt_c(d.edge)}" if d.expected_move is not None else ""
    return f"if {who[:16]:16s} wins it: {d.action:8s} {d.reason:24s} {extra}"


async def live_market(a) -> dict:
    assert_paper_only()
    print("COURTSIDE live-market (read-only): public Polymarket market + sports websockets; no orders, "
          "not even paper ones. What-ifs assume a vision MISS call at confidence 0.95.", flush=True)
    feed = LiveClobFeed(auto_discover=True)
    risk = RiskManager(RiskConfig(require_vision=False), feed=feed)   # no camera on these matches: see note
    strat = CourtsideStrategy(feed, None, risk, StrategyConfig())
    scores: dict = {}
    sinfo: dict = {"connected": False}
    stop = asyncio.Event()
    sports = asyncio.create_task(_sports_listener(scores, sinfo, stop))
    tally: dict[str, int] = {}
    reports: list = []
    cal_key: dict[str, tuple] = {}

    async def report_loop():
        while True:
            await asyncio.sleep(a.every)
            await report()

    async def report(tag="live"):
        mk = _markets_from_meta(feed.meta)
        live = []
        for cond, r in mk.items():
            ta, tb = r["tokens"]
            ba, bb = feed.book(ta), feed.book(tb)
            if not (ba.has_snapshot and bb.has_snapshot):
                continue
            if ba.best_bid() is None or ba.best_ask() is None:
                continue
            live.append((ba.n_updates + bb.n_updates, cond, r))
        live.sort(key=lambda x: -x[0])
        s = feed.summary()
        lat = s["latency"]
        print(f"\n[{time.strftime('%H:%M:%S')}] connected={feed.connected} msgs={s['msgs']} tokens={s['assets']} "
              f"markets={len(mk)} with books={len(live)} | feed delay p50/p95/p99 {lat['p50_ms']}/{lat['p95_ms']}/"
              f"{lat['p99_ms']} ms | snapshot desync {s['snapshots_mismatched']}/{s['snapshots_checked']} | "
              f"sports msgs {sinfo.get('msgs', 0)}", flush=True)
        rows = []
        for _, cond, r in live[: a.max_matches]:
            ta, tb = r["tokens"]
            sc = scores.get(int(r["gameId"])) if r.get("gameId") is not None else None
            if sc is None:                    # no gameId (ITF): match both surnames against home/away
                sc = _score_by_names(scores, r["names"])
            state, score_src, tour = State(), "unknown (assume 0-0, sets 0-0)", tour_of(r["slug"])
            if sc and sc.get("score"):
                hia = home_is_outcome0(r["names"][0], sc.get("homeTeam", ""), sc.get("awayTeam", ""))
                if hia is not None:
                    sa, sb, ga, gb = parse_score(sc["score"], hia)
                    state = State(sa, sb, ga, gb, 0, 0, 0)
                    score_src = f"sports feed '{sc['score']}' (points unknown: 0-0 assumed)"
                tour = tour_of(r["slug"], sc.get("leagueAbbreviation"))
            if cond not in strat.matches:
                strat.add_match(cond, ta, tb, tour=tour, names=tuple(r["names"]), calibrate=False)
            ctx = strat.matches[cond]
            mid = strat.mid_a(ctx)
            if mid is None or not (0.02 < mid < 0.98):
                continue
            for _ in range(3):                # calibrate off the event loop, then swap in; again if the book
                key = (state, round(mid, 3))  # moved while the calibration ran
                if cal_key.get(cond) == key:
                    break
                try:   # in a worker process: a thread would hold the GIL and stall the feed
                    job = await asyncio.get_running_loop().run_in_executor(pool, calibration_job, mid, tour, state, 0.5)
                    mf = fair_from_job(job, state, 0.5, tour, Format(), cond, ta, tb)
                except Exception as ex:
                    print(f"  calibration failed for {r['slug']}: {ex!r}")
                    break
                strat.install_fair(cond, mf, mid, feed.now_ms())
                cal_key[cond] = key
                mid = strat.mid_a(ctx) or mid
            now = feed.now_ms()
            ba = feed.book(ta)
            dA = strat.evaluate(cond, PointCall(cond, now, winner=0, confidence=0.95, kind="point"), now, approve=True)
            dB = strat.evaluate(cond, PointCall(cond, now, winner=1, confidence=0.95, kind="point"), now, approve=True)
            for d in (dA, dB):
                k = d.action + ":" + (d.reason if d.action != "SEND" else "ok")
                if tag == "live":
                    tally[k] = tally.get(k, 0) + 1
            bd, _ = ba.depth("bid", within=0.0)
            ad, _ = ba.depth("ask", within=0.0)
            print(f"  {r['slug'][:38]:38s} {r['names'][0][:16]:>16s} {ba.best_bid():.3f} x {bd:7.0f} | "
                  f"{ba.best_ask():.3f} x {ad:<7.0f} mid {mid:.3f} | swing {_fmt_c(dA.leverage)} | {score_src}")
            print(f"      {_what_if_line(dA)}")
            print(f"      {_what_if_line(dB)}", flush=True)
            rows.append({"slug": r["slug"], "cond": cond, "names": r["names"], "tour": tour, "score": score_src,
                         "state": asdict(state), "bid_a": ba.best_bid(), "ask_a": ba.best_ask(), "mid_a": mid,
                         "touch_depth_a": [bd, ad], "if_a_wins": dA.to_dict(), "if_b_wins": dB.to_dict()})
        reports.append({"t": time.strftime("%H:%M:%S"), "tag": tag, "connected": feed.connected, "rows": rows})

    from concurrent.futures import ProcessPoolExecutor
    pool = ProcessPoolExecutor(1)
    rep = asyncio.create_task(report_loop())
    try:
        await feed.run(seconds=a.seconds)
    finally:
        rep.cancel()
        stop.set()
        sports.cancel()
    await asyncio.sleep(2.5)
    print("\n(socket closed 2.5 s ago: the feed-stale kill switch (> 2 s silent) must now reject every what-if the "
          "rule would SEND; what-ifs the rule already skips never reach the risk check)")
    await report("after_disconnect")
    pool.shutdown(cancel_futures=True)
    live_reps = [r for r in reports if r["tag"] == "live"]
    out = {"mode": "live-market", "paper_only": True, "orders_sent": 0, "seconds": a.seconds,
           "when": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "feed": feed.summary(), "reconnects": feed.n_connects - 1,
           "feed_errors": [e[1] for e in list(feed.errors)[-5:]], "markets_discovered": len(_markets_from_meta(feed.meta)),
           "sports_feed": {"connected": sinfo.get("connected"), "msgs": sinfo.get("msgs", 0),
                           "games_seen": len(scores), "errors": sinfo.get("errors", [])[-3:]},
           "what_if_tally": tally, "last_live_report": live_reps[-1] if live_reps else None,
           "after_disconnect_report": reports[-1] if reports else None, "n_reports": len(reports),
           "notes": ["What-ifs: a vision MISS call naming the point winner, confidence 0.95, evaluated by "
                     "engine/strategy.py against the live book; risk checked with require_vision=False because no "
                     "camera is attached to these matches (with a camera the vision kill switch applies).",
                     "Point score inside the game is not in the public feed: 0-0 assumed, so the swing shown is "
                     "the game-start swing; sets and games come from the sports feed when it covers the match."]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "live_market_run.json").write_text(json.dumps(_clean(out), indent=1))
    print(f"\nwhat-if tally over the run: {tally}\nwrote {OUT / 'live_market_run.json'}", flush=True)
    return out


# =====================================================================================================
# (b) demo: vision on a real clip -> recorded book
# =====================================================================================================
def _flights(video: str):
    import pandas as pd
    tf = pd.read_csv(REPO / "results" / "tracking" / "test_flights.csv")
    tf = tf[tf.video == video].copy()
    aud = pd.read_csv(REPO / "results" / "tracking" / "test_flights_audited.csv")
    aud = aud[aud.video == video][["f_net", "label", "audit"]].rename(columns={"label": "label_audited"})
    return tf.merge(aud, on="f_net", how="left")


def offline_schedule(video: str, tau_snap: float) -> dict[int, dict]:
    """The frozen model's own decisions on this held-out video (results/tracking/test_flights.csv):
    MISS at the online rule's first call (t_ref - first_call_lead), BOUNCE at the 50 ms snapshot when
    P(miss) < tau_snapshot. Used only when models/vision/frozen_call_model.pkl is absent."""
    out = {}
    for r in _flights(video).itertuples():
        if np.isfinite(r.first_call_lead_ms):
            f = int(r.t_ref - round(r.first_call_lead_ms * FPS / 1000.0))
            out[f] = dict(call="MISS", dir=float(np.sign(r.dir)), f_net=int(r.f_net), t_ref=int(r.t_ref),
                          offline_lead_ms=float(r.first_call_lead_ms), p50=float(r.p_miss_at_50ms))
        elif np.isfinite(r.p_miss_at_50ms) and r.p_miss_at_50ms < tau_snap:
            f = int(r.t_ref - round(0.050 * FPS))
            out[f] = dict(call="BOUNCE", dir=float(np.sign(r.dir)), f_net=int(r.f_net), t_ref=int(r.t_ref),
                          offline_lead_ms=50.0, p50=float(r.p_miss_at_50ms))
    return out


def _replay_caller_cls():
    from engine.vision.stream import FrozenCaller

    class ReplayedFrozenDecisions(FrozenCaller):
        """Runs the full online flight segmentation, features and classifier stage (stand-in HGB, so the
        stage is timed) on every decision frame, and emits the frozen model's OFFLINE decision for this
        held-out video at the frame it was made, provided the online engine is tracking a flight in the
        same direction at that frame. Never invents a call; p_miss is unknown (None)."""

        def __init__(self, proxy, geometry, schedule):
            super().__init__(proxy, geometry, FPS, emit_enabled=False)
            self.schedule = schedule
            self.not_reproduced = []

        def decide(self, t, trk):
            super().decide(t, trk)
            s = self.schedule.get(t)
            if s is None:
                return []
            last = self.trace[-1] if self.trace and self.trace[-1][0] == t else None
            if last is None or last[1] != s["dir"]:
                self.not_reproduced.append(dict(frame=t, **s, why="no online flight in that direction"))
                return []
            _, d, t0, _, gate = last
            F = self.E.Flight(SimpleNamespace(dir=d, t0=t0, t_ref=t - self.lag), trk, self.g)
            f = F.features(t)
            if f is None:
                self.not_reproduced.append(dict(frame=t, **s, why="no features"))
                return []
            lead = 1000 * (f["tau_mid"] if s["call"] == "BOUNCE" else
                           (f["tau_end"] if f["passed_net"] else min(f["tau_net"], f["tau_end"])))
            x_l, y_l = trk[F.fr[-1]]
            info = dict(p=float("nan"), d=d, t0=t0, gate_open=gate, tau_net_ms=1000 * f["tau_net"],
                        tau_end_ms=1000 * f["tau_end"], tau_mid_ms=1000 * f["tau_mid"], passed_net=f["passed_net"],
                        xy=(x_l, y_l), offline_lead_ms=s["offline_lead_ms"], offline_p_miss_at_50ms=s["p50"],
                        f_net=s["f_net"], t_ref=s["t_ref"])
            return [(s["call"], lead, info)]

    return ReplayedFrozenDecisions


def run_vision(a) -> dict:
    """The real streaming engine (engine/vision/stream.py) over the clip, paced at --vision-fps."""
    from engine.vision.run_demo import detection_check, timing_proxy_model
    from engine.vision.stream import (FrameSource, VisionCallEngine, load_frozen, load_geometry, make_backend,
                                      run_stream, summarize, tracking_modules)
    clip = Path(a.clip)
    if not clip.exists():
        raise SystemExit(f"{clip} missing. Cut it with:\n  ffmpeg -ss 16.666667 -i "
                         "https://lab.osai.ai/datasets/openttgames/data/test_2.mp4 -frames:v 1000 -c copy -an "
                         f"-copyts {clip}")
    M = tracking_modules()
    try:
        frozen = load_frozen(a.frozen)
        source = "frozen_model_live"
    except FileNotFoundError:
        frozen, source = None, "offline_frozen_decisions_replayed"
    tau_snap = 0.8854
    try:
        tau_snap = json.loads((REPO / "results/tracking/label_audit.json").read_text())["tau_snapshot_frozen"]
    except Exception:
        pass
    geo, geo_prov = load_geometry(a.video, frozen)
    proxy = None if frozen is not None else timing_proxy_model()
    schedule = offline_schedule(a.video, tau_snap) if frozen is None else {}
    printed = []

    def on_event(ev):
        if source != "frozen_model_live":
            ev.source = "table_tennis:offline_frozen_decision_replay"
            ev.rule = ("frozen H3 model's offline decision on this held-out frame (results/tracking/test_flights.csv: "
                       + ("online rule P>=tau_online x3, first call" if ev.call == "MISS" else
                          "50 ms snapshot P<tau_snapshot") + "); emitted when the online engine reaches the frame")
        printed.append(ev)
        print(f"  [vision] {ev.call:6s} frame {ev.frame}  t_clip {ev.media_t - a.frame_offset / FPS:6.3f}s  "
              f"dir {ev.direction:+d}  predicted lead {ev.lead_ms:5.0f} ms  frame->CallEvent {ev.latency_ms:6.1f} ms",
              flush=True)

    backend_spec = a.backend
    try:
        backend = make_backend(backend_spec, None, a.threads)
    except Exception as e:   # no CoreML: CPU (~5 fps on the laptop)
        print(f"backend {backend_spec} unavailable ({e!r}); falling back to onnx-cpu at 4 fps", flush=True)
        backend_spec, a.vision_fps = "onnx-cpu", min(a.vision_fps, 4.0)
        backend = make_backend(backend_spec, None, a.threads)
    eng = VisionCallEngine(backend, frozen if frozen is not None else proxy, geo, fps=FPS,
                           frame_offset=a.frame_offset, on_event=on_event, emit_enabled=frozen is not None)
    if frozen is None:
        eng.caller = _replay_caller_cls()(proxy, geo, schedule)
    x0 = np.zeros((1, 9, M.D.INP_H, M.D.INP_W), np.float32)
    for b in eng.det.backends:
        for _ in range(3):
            b(x0)
    print(f"vision: {clip.name} ({a.video} frames {a.frame_offset}+), detector {eng.det.name}, arrivals paced at "
          f"{a.vision_fps:g} fps (clip is 120 fps), calls: {source}", flush=True)
    src = FrameSource(str(clip), M.D, realtime=True, fps=a.vision_fps, max_frames=a.max_frames).start()
    t = time.time()
    rows, skipped = run_stream(eng, src)
    wall = time.time() - t
    if "error" in src.info:
        raise RuntimeError(f"reader failed: {src.info['error']}")
    summ = summarize(rows, wall, skipped, eng)
    n = src.info.get("read", 0)
    det = detection_check(eng.track_log, a.video)
    # queue wait of each frame (arrival -> dequeue). A call's processing latency = its end-to-end latency
    # minus the queue wait of its decision frame: what a host that keeps up with the arrivals would see.
    qwait = {r["i"] + a.frame_offset: r["qwait_ms"] for r in rows}
    proc = [ms - qwait.get(f, 0.0) for f, ms in eng.ready_ms.items()]
    summ["call_ready_processing_ms"] = {k: round(float(np.percentile(proc, q)), 2) for k, q in
                                        (("p50", 50), ("p90", 90), ("p99", 99))} if proc else {}
    summ["call_ready_processing_ms"]["max"] = round(float(np.max(proc)), 2) if proc else None
    events = [dict(ev.to_dict(), processing_latency_ms=ev.latency_ms - qwait.get(ev.frame, 0.0),
                   queue_wait_ms=qwait.get(ev.frame, 0.0)) for ev in eng.events]
    fl = _flights(a.video)
    fl = fl[(fl.t0 >= a.frame_offset) & (fl.t_ref < a.frame_offset + n)]
    for e in events:
        r = fl[(fl.t0 - 2 <= e["frame"]) & (fl.t_ref + 12 >= e["frame"]) & (np.sign(fl.dir) == e["direction"])]
        if len(r):
            r = r.iloc[(r.t_ref - e["frame"]).abs().argmin()]
            e.update(flight_f_net=int(r.f_net), label=r.label, label_audited=r.label_audited,
                     audit=(r.audit if isinstance(r.audit, str) else None),
                     actual_lead_ms=round(1000 * (r.t_ref - e["frame"]) / FPS, 1),
                     correct_vs_label=(r.label == "MISS") == (e["call"] == "MISS"))
    return dict(call_source=source, frozen_model=str(a.frozen) if frozen is not None else None,
                why_replayed=(None if frozen is not None else
                              "models/vision/frozen_call_model.pkl is not on this host (it is rebuilt on HiPerGator "
                              "from the game_1..5 training tracks; HPG was unreachable). The stream runs detection, "
                              "tracking, flight segmentation and the classifier stage live; the decision at each "
                              "frame is the frozen model's own offline decision for this held-out frame."),
                clip=str(clip.relative_to(REPO)), video=a.video, first_frame=a.frame_offset, frames=n,
                backend=backend_spec, detector=eng.det.name, arrival_fps=a.vision_fps, geometry=geo_prov,
                timing=summ, detection_vs_labels=det, events=events,
                not_reproduced=getattr(eng.caller, "not_reproduced", []),
                flights_in_clip=[dict(f_net=int(r.f_net), label=r.label, label_audited=r.label_audited,
                                      audit=r.audit if isinstance(r.audit, str) else None, t0=int(r.t0),
                                      t_ref=int(r.t_ref), dir=int(np.sign(r.dir)),
                                      offline_first_call_lead_ms=(None if not np.isfinite(r.first_call_lead_ms)
                                                                  else float(r.first_call_lead_ms)))
                                 for r in fl.itertuples()])


# ----------------------------------------------------------------------------------------------- market side
def match_points(slug: str):
    """Official WTA point-by-point for one recorded match with each point's book reprice
    (research/v2/latency/out/m1_points.csv) and the score / server belief BEFORE each point."""
    import pandas as pd
    P = pd.read_csv(M1)
    P = P[P.slug == slug].sort_values("n").reset_index(drop=True)
    if P.empty:
        raise SystemExit(f"no point-by-point for {slug} in {M1}")
    m0 = float(P.m0.dropna().iloc[0])
    mf = MatchFair.from_price(m0, "wta", Format(), State(), 0.5)
    pre, final = [], None
    for r in P.itertuples():
        pre.append((mf.state, mf.p_server0))
        if mf.state is not None:
            mf.apply_point(r.winner == 0)
    if mf.state is None:
        final = int(P.winner.iloc[-1])
    P["state_before"] = [s for s, _ in pre]
    P["p_server0_before"] = [p for _, p in pre]
    return P, final


def pick_anchors(P, k: int):
    """Pre-specified, P&L-blind rule: among the points with an official stamp, a covered book reprice of
    >= 3c (the tier-0 'D>=3c' pool) and a reprice lead inside the IQR of all 482 measured points (timing
    typical, neither lucky nor unlucky), take k evenly spaced over the match (early and late points)."""
    lo, hi = -1.93, -0.68
    try:
        q = json.loads(LAT_SUMMARY.read_text())["m1"]["book_vs_official_T_s"]
        lo, hi = q["p25"], q["p75"]
    except Exception:
        pass
    c = P[(P.ok == True) & (P.D >= 0.03) & P.t_book.notna() & P.book_vs_T_s.between(lo, hi)  # noqa: E712
          & P.state_before.notna()]
    if len(c) <= k:
        return c, (lo, hi)
    idx = np.unique(np.linspace(0, len(c) - 1, k).round().astype(int))   # spread over the whole match
    return c.iloc[idx], (lo, hi)


def _clone(feed) -> dict:
    return {"books": {a: b.copy() for a, b in feed.books.items()}, "market_of": dict(feed.market_of),
            "last_local_ms": feed.last_local_ms, "clock": feed._clock, "last_server_ms": feed.last_server_ms}


ALIVE = "_feed_alive"   # synthetic asset: carries the feed's liveness from markets the demo does not trade


def market_windows(files: str, wins: list[tuple[int, int, int]], tokens, cond: str, alive_ms: int = 200):
    """One streaming pass over the recordings, in arrival order. For each window (k, w0, w1): the books of
    the match's tokens just before w0, and the messages stamped in [w0, w1] that touch them. Messages of
    every other market are reduced to a liveness marker every `alive_ms` (so the feed-stale kill switch
    sees the whole feed, as it would live) instead of being replayed in full."""
    toks = set(tokens)
    pre = ReplayClobFeed(messages=[], one_way_ms=0, validate=False)
    pending = sorted(wins, key=lambda w: w[1])
    w1 = {k: e for k, _, e in wins}
    snaps, bufs, last_mark, active = {}, {}, {}, []
    last_any = 0

    def relevant(m):
        e = m.get("event_type")
        if e == "_gap":
            return m
        if e == "price_change":
            pcs = [c for c in m.get("price_changes") or () if c.get("asset_id") in toks]
            return {**m, "price_changes": pcs} if pcs else None
        if m.get("asset_id") in toks or (e == "market_resolved" and m.get("market") == cond):
            return m
        return None

    for m in iter_recorded(files):
        ts = int(m["timestamp"])
        r = relevant(m)
        while pending and ts >= pending[0][1]:
            k = pending.pop(0)[0]
            snaps[k], bufs[k], last_mark[k] = dict(_clone(pre), last_local_ms=last_any), [], 0
            active.append(k)
        for k in list(active):
            if ts > w1[k]:
                active.remove(k)
                yield k, snaps.pop(k), bufs.pop(k)
            elif r is not None:
                bufs[k].append(r)
            elif ts - last_mark[k] >= alive_ms:
                bufs[k].append({"event_type": "best_bid_ask", "asset_id": ALIVE, "market": "", "timestamp": str(ts)})
                last_mark[k] = ts
        if r is not None:
            pre._step(r)
        last_any = max(last_any, ts)
        if not pending and not active:
            break
    for k in active:
        yield k, snaps.pop(k), bufs.pop(k)


_CAL_CACHE: dict = {}


def _calibrated(mid: float, state: State, p0: float, cond: str, ta: str, tb: str):
    """MatchFair calibrated to `mid` at `state`, and the wall time that calibration took. Scenarios of one
    anchor see the same mids, so results are cached; a cache hit still reports the original compute time
    (the delay a live engine would pay before the refreshed model is installed)."""
    key = (round(mid, 6), state, round(p0, 9))
    hit = _CAL_CACHE.get(key)
    if hit is None:
        c0 = time.perf_counter()
        mf = MatchFair.from_price(mid, "wta", Format(), state, p0)
        hit = _CAL_CACHE[key] = (mf.serve_probs, (time.perf_counter() - c0) * 1000.0)
    (pa, pb), ms = hit
    return MatchFair(pa, pb, Format(), state, p0, "wta", cond, ta, tb), ms


def run_scenario(match: dict, anchor: dict, snap: dict, msgs: list, sc: dict, calls: list, series: list | None = None):
    """One paper run of the strategy over one anchored point. Returns everything it did."""
    ow = int(sc["one_way_ms"])
    feed = ReplayClobFeed(messages=msgs, one_way_ms=ow, validate=False)
    feed.books = {a: b.copy() for a, b in snap["books"].items()}
    feed.market_of = dict(snap["market_of"])
    feed.last_local_ms, feed._clock = snap["last_local_ms"] + ow, snap["clock"] + ow
    feed.last_server_ms = snap["last_server_ms"]
    risk = RiskManager(RiskConfig(), feed=feed)
    ledger = Ledger(cash=CAPITAL)
    ex = PaperExecutor(feed, one_way_ms=ow, venue_delay_ms=VENUE_DELAY_MS, risk=risk, ledger=ledger)
    risk.equity_fn = lambda: ledger.equity(ex.mark)
    st = CourtsideStrategy(feed, ex, risk, StrategyConfig())
    ta, tb = match["tokens"]
    st.add_match(match["cond"], ta, tb, state=anchor["state"], p_server0=anchor["p_server0"], tour="wta",
                 left_player=anchor["left_player"], names=tuple(match["names"]), calibrate=False)
    t_end = anchor["T_ms"] - sc["stamp_lag_s"] * 1000.0
    acts: list = []
    seq = itertools.count()

    def push(t, prio, kind, p):
        heapq.heappush(acts, (int(t), prio, next(seq), kind, p))
    push(anchor["t_cal"], 0, "calibrate", None)
    for i, c in enumerate(calls):
        lat = c["processing_latency_ms"] if sc["vision"] == "keep_up" else c["latency_ms"]
        t_frame = t_end - (anchor["f_end"] - c["frame"]) / FPS * 1000.0 + sc.get("camera_ms", 0.0)
        push(math.ceil(t_frame + lat), 1, "call",
             dict(c, t_frame_mapped=t_frame, latency_used_ms=lat + sc.get("camera_ms", 0.0)))
    for dt in (10_000, 60_000):
        push(t_end + dt, 2, "mark", dt)
    log = {"marks": [], "calls": [], "refresh": []}
    cal = {}

    def do(t, kind, p):
        if kind == "install":
            mf, m, ms = p
            st.install_fair(match["cond"], mf, m, t)
            log["refresh"].append(dict(t_rel_s=(t - t_end) / 1000, mid_a=m, compute_ms=ms, leverage=mf.jump().leverage))
            return
        if kind == "calibrate":
            cal["ok"] = st.calibrate(match["cond"], now_ms=t)
            cal["mid_a"] = st.matches[match["cond"]].cal_mid_a
            ctx = st.matches[match["cond"]]
            j = ctx.fair.jump()
            cal.update(t_rel_s=(t - t_end) / 1000, serve_probs=list(ctx.fair.serve_probs), v_now=j.v_now,
                       v_if_a=j.v_if_a, v_if_b=j.v_if_b, leverage=j.leverage, p_point_a=j.p_point_a)
        elif kind == "call":
            ev = SimpleNamespace(**{k: p[k] for k in ("call", "frame", "p_miss", "direction", "lead_ms")},
                                 latency_ms=p["latency_used_ms"])
            d = st.on_call(match["cond"], ev, t_ms=t)
            if d.reason == "no_point_decision" and REFRESH_ON_BOUNCE:
                # rally continues: the book cannot have priced this point yet, so refresh the pre-point
                # calibration at the current mid. Computed now, installed after its measured compute time
                # (live: in a worker thread), so the hot path never waits on it.
                ctx = st.matches[match["cond"]]
                m = st.mid_a(ctx)
                if m is not None and 0.0 < m < 1.0 and ctx.fair.state is not None:
                    mf, ms = _calibrated(m, ctx.fair.state, ctx.fair.p_server0, match["cond"], ta, tb)
                    push(t + math.ceil(ms), 0, "install", (mf, m, ms))
            o = next((o for o in ex.orders if o.id == d.order_id), None)
            log["calls"].append(dict(frame=p["frame"], call=p["call"], direction=p["direction"],
                                     t_frame_rel_s=(p["t_frame_mapped"] - t_end) / 1000,
                                     latency_ms=p["latency_used_ms"], t_dec_rel_s=(t - t_end) / 1000,
                                     decision=d.to_dict(),
                                     order=None if o is None else dict(id=o.id, t_arrive_rel_s=(o.t_arrive - t_end) / 1000,
                                                                       t_exec_rel_s=(o.t_exec - t_end) / 1000)))
        elif kind == "mark":
            ma, mb = feed.book(ta).mid(), feed.book(tb).mid()
            log["marks"].append(dict(after_s=p / 1000, mid_a=ma, mid_b=mb, equity=ledger.equity(ex.mark),
                                     pnl=ledger.pnl(ex.mark), pos=dict(ledger.pos)))

    def hook(ts):
        while acts and acts[0][0] <= ts + ow:
            t, _, _, kind, p = heapq.heappop(acts)
            do(t, kind, p)
    feed.on_clock(hook)
    if series is not None:
        def rec(ev):
            if ev.asset_id in (ta, tb) and ev.kind in ("price_change", "book"):
                series.append((ev.ts_server, ev.asset_id, ev.best_bid, ev.best_ask))
        feed.on(rec)
        for a_ in (ta, tb):
            b = feed.book(a_)
            series.append((snap["last_server_ms"], a_, b.best_bid(), b.best_ask()))
    feed.run_sync()
    while acts:                         # anything scheduled after the last message
        t, _, _, kind, p = heapq.heappop(acts)
        do(t, kind, p)
    ex.flush()
    fills = [dict(order_id=f.order_id, token=("A" if f.token == ta else "B"), name=match["names"][0 if f.token == ta else 1],
                  shares=f.shares, vwap=f.price, fee=f.fee, levels=f.levels, t_exec_rel_s=(f.t_exec - t_end) / 1000,
                  book_ts_rel_s=(f.book_ts - t_end) / 1000, slippage_vs_touch_at_decision=f.slippage,
                  cash_flow=f.cash_flow) for f in ex.fills]
    orders = [dict(id=o.id, token=("A" if o.token == ta else "B"), side=o.side, requested=o.requested, shares=o.shares,
                   limit=o.limit, status=o.status, reason=o.reason, filled=o.filled, vwap=o.vwap,
                   t_decision_rel_s=(o.t_decision - t_end) / 1000, t_arrive_rel_s=(o.t_arrive - t_end) / 1000,
                   t_exec_rel_s=(o.t_exec - t_end) / 1000, ask_at_decision=o.ask_at_decision) for o in ex.orders]
    pos = dict(ledger.pos)
    held = None
    if match.get("final_winner") is not None:
        win_tok = ta if match["final_winner"] == 0 else tb
        held = ledger.cash + sum(q * (1.0 if t == win_tok else 0.0) for t, q in pos.items()) - CAPITAL
    return dict(scenario=sc, t_end_ms=t_end, calibration=cal, bounce_refreshes=log["refresh"], calls=log["calls"],
                orders=orders, fills=fills,
                marks=log["marks"], position=pos, pnl_held_to_resolution=held,
                pnl_marked_10s=next((m["pnl"] for m in log["marks"] if m["after_s"] == 10), None),
                pnl_marked_60s=next((m["pnl"] for m in log["marks"] if m["after_s"] == 60), None),
                fees=ledger.fees, risk=risk.snapshot(), kill_log=risk.log, executor=ex.summary(),
                strategy=st.summary())


def bench_120fps_latency(backend: str) -> float | None:
    """This laptop at true 120 fps arrivals: call latency p50 incl. the backlog (vision_bench.json)."""
    try:
        S = json.loads(VISION_BENCH.read_text())["summary"]
    except Exception:
        return None
    rows = [r for r in S if r.get("realtime_120fps_call_latency_ms")]
    pick = [r for r in rows if f"|{backend}|" in r["config"]] or rows
    return float(pick[0]["realtime_120fps_call_latency_ms"]["p50"]) if pick else None


def demo(a) -> dict:
    assert_paper_only()
    print("=" * 100 + "\n" + ILLUSTRATIVE + "\n" + "=" * 100, flush=True)
    t_start = time.time()
    # --- 1. vision -----------------------------------------------------------------------------------
    if a.reuse_vision:   # development convenience: reuse the vision section of an earlier demo_run.json
        V = json.loads(Path(a.reuse_vision).read_text())["vision"]
        V["events"] = [dict(e, p_miss=float("nan") if e.get("p_miss") is None else e["p_miss"]) for e in V["events"]]
        V["reused_from"] = str(a.reuse_vision)
    else:
        V = run_vision(a)
    calls = [dict(call=e["call"], frame=e["frame"], p_miss=e["p_miss"], direction=e["direction"],
                  lead_ms=e["lead_ms"], latency_ms=e["latency_ms"], processing_latency_ms=e["processing_latency_ms"])
             for e in V["events"]]
    tm = V["timing"]
    print(f"vision done: {len(calls)} CallEvents "
          f"({sum(c['call'] == 'MISS' for c in calls)} MISS, {sum(c['call'] == 'BOUNCE' for c in calls)} BOUNCE); "
          f"sustained {tm['fps_sustained']} fps vs {V['arrival_fps']:g} fps arrivals; frame->call latency p50 "
          f"{tm['call_ready_ms'].get('p50')} ms as run (incl. queueing), processing only p50 "
          f"{tm['call_ready_processing_ms'].get('p50')} / p90 {tm['call_ready_processing_ms'].get('p90')} ms", flush=True)
    clean = [f for f in V["flights_in_clip"] if f["label"] == "MISS" and not f["audit"]]
    if not clean:
        raise SystemExit("no clean labelled MISS flight in the clip to anchor on")
    anchor_flight = clean[-1]
    f_end = anchor_flight["t_ref"]
    # --- 2. the recorded match ------------------------------------------------------------------------
    P, final = match_points(a.match)
    meta = load_token_meta()
    toks = sorted([(m["outcome_index"], t, m["outcome"], m["cond"]) for t, m in meta.items() if m.get("slug") == a.match])
    if len(toks) != 2:
        raise SystemExit(f"tokens for {a.match} not found in data/live/tokens_*")
    match = dict(slug=a.match, cond=toks[0][3], tokens=[toks[0][1], toks[1][1]], names=[toks[0][2], toks[1][2]],
                 final_winner=final)
    A, iqr = pick_anchors(P, a.anchors)
    if A.empty:
        raise SystemExit("no anchor point satisfies the rule")
    lag_cal = None
    try:
        lag_cal = json.loads(TIER0.read_text())["inputs"]["stamp_lag_calibration"]["central"]["stamp_lag_s"]
    except Exception:
        pass
    lags = [a.stamp_lag] + [x for x in (1.0, 2.0, lag_cal) if x is not None and abs(x - a.stamp_lag) > 1e-9]
    lat120 = bench_120fps_latency(V["backend"])
    one_way = {"florida": FLORIDA_MS, "london": LONDON_MS}
    scenarios = []
    for lag in lags:
        for loc in ([a.location] + [x for x in one_way if x != a.location]):
            scenarios.append(dict(stamp_lag_s=lag, location=loc, one_way_ms=one_way[loc], vision="keep_up",
                                  camera_ms=a.camera_ms))
    scenarios.append(dict(stamp_lag_s=a.stamp_lag, location=a.location, one_way_ms=one_way[a.location],
                          vision="as_run", camera_ms=a.camera_ms))
    primary = scenarios[0]
    clip_pre_ms = (f_end - a.frame_offset) / FPS * 1000.0
    anchors, wins = [], []
    for i, r in enumerate(A.itertuples()):
        prev = P[P.n == r.n - 1]
        prev_T = float(prev.T_ms.iloc[0]) if len(prev) else None
        earliest_clip = r.T_ms - max(lags) * 1000.0 - clip_pre_ms
        t_cal = min(prev_T + 3000.0, earliest_clip - 1000.0) if prev_T else earliest_clip - 1000.0
        winner = int(r.winner)
        loser = 1 - winner
        # the clip's anchor shot is hit by the player at the image's left if it travels left->right; that
        # hitter loses the point, so he stands in for the WTA point's loser (the call is right by construction)
        left = loser if anchor_flight["dir"] > 0 else winner
        anchors.append(dict(k=i, n=int(r.n), set=int(r.set), game=int(r.game), score_after=f"{r.ga}-{r.gb}",
                            game_end=bool(r.game_end), winner=winner, winner_name=match["names"][winner],
                            T_ms=float(r.T_ms), t_book_ms=float(r.t_book), t_book_first_ms=float(r.t_book_first),
                            book_vs_T_s=float(r.book_vs_T_s), D=float(r.D), m0=float(r.m0),
                            state=r.state_before, p_server0=float(r.p_server0_before), left_player=left,
                            t_cal=t_cal, f_end=f_end))
        wins.append((i, int(t_cal - 2000), int(r.T_ms + 65_000)))
    print(f"\nmarket: {a.match} ({match['names'][0]} = outcome 0 vs {match['names'][1]}), "
          f"{len(anchors)} anchor points by the pre-specified rule (D>=3c, reprice lead in the measured IQR "
          f"[{iqr[0]}, {iqr[1]}] s); clip point end = frame {f_end} (flight f_net {anchor_flight['f_net']})", flush=True)
    results = {k: [] for k in range(len(anchors))}
    series: dict[int, list] = {}
    t0 = time.time()
    for k, snap, msgs in market_windows(a.files, wins, match["tokens"], match["cond"]):
        an = anchors[k]
        for j, sc in enumerate(scenarios):
            res = run_scenario(match, an, snap, msgs, sc, calls, series.setdefault(k, []) if j == 0 else None)
            results[k].append(res)
        res = results[k][0]
        print(f"\n--- anchor {k}: WTA point {an['n']} (set {an['set']} game {an['game']}, score before "
              f"{an['state'].pa}-{an['state'].pb} pts, games {an['state'].ga}-{an['state'].gb}, sets "
              f"{an['state'].sa}-{an['state'].sb}); winner {an['winner_name']}; book reprice {an['D'] * 100:.1f}c, "
              f"{an['book_vs_T_s']:+.2f} s vs official stamp; {len(msgs)} messages in window", flush=True)
        cal = res["calibration"]
        print(f"    calibrated at {cal.get('t_rel_s', float('nan')):+.1f} s on mid {cal.get('mid_a')}: "
              f"swing {100 * (cal.get('leverage') or 0):.1f}c, model P(A wins point) {cal.get('p_point_a', 0):.3f}; "
              f"{len(res['bounce_refreshes'])} BOUNCE refreshes (last at "
              f"{res['bounce_refreshes'][-1]['t_rel_s'] if res['bounce_refreshes'] else float('nan'):+.2f} s, "
              f"calibration compute {res['bounce_refreshes'][-1]['compute_ms'] if res['bounce_refreshes'] else float('nan'):.0f} ms)",
              flush=True)
        for c in res["calls"]:
            d = c["decision"]
            o = c["order"]
            fill = next((f for f in res["fills"] if o and f["order_id"] == d["order_id"]), None)
            od = next((x for x in res["orders"] if o and x["id"] == d["order_id"]), None)
            msg = (f"    {c['call']:6s} f{c['frame']} frame@{c['t_frame_rel_s']:+.3f}s dec@{c['t_dec_rel_s']:+.3f}s "
                   f"-> {d['action']:8s} {d['reason'][:28]:28s}")
            if d["action"] == "SEND":
                msg += (f" BUY {d['shares']:.0f} {d['winner_name']} <= {d['limit']:.3f} (ask {d['ask']:.3f}, "
                        f"E[move] {100 * d['expected_move']:+.1f}c, edge {100 * d['edge']:+.1f}c) exec@{o['t_exec_rel_s']:+.3f}s: ")
                msg += (f"FILLED {fill['shares']:.0f} @ {fill['vwap']:.3f}" if fill else f"{od['status']} ({od['reason']})")
            elif d["expected_move"] is not None and d["call"] == "MISS":
                msg += (f" {d['winner_name']}: E[move] {100 * d['expected_move']:+.1f}c (swing {100 * d['leverage']:.1f}c x "
                        f"(c {d['confidence']:.2f} - p {d['p_point_winner']:.2f}))"
                        + (f", half spread {100 * d['half_spread']:.1f}c + tick + fee {100 * d['fee']:.1f}c -> edge "
                           f"{100 * d['edge']:+.1f}c" if d["edge"] is not None else
                           (f", book moved {100 * d['moved_toward_winner']:+.1f}c" if d["moved_toward_winner"] is not None else "")))
            if d["call"] == "MISS" or d["action"] != "SKIP":
                print(msg, flush=True)
        print(f"    reprice: first tick {(an['t_book_first_ms'] - res['t_end_ms']) / 1000:+.2f} s, half-move "
              f"{(an['t_book_ms'] - res['t_end_ms']) / 1000:+.2f} s, official stamp {primary['stamp_lag_s']:+.2f} s | "
              f"P&L marked +10 s {res['pnl_marked_10s']:+.2f}, +60 s {res['pnl_marked_60s']:+.2f}, held to "
              f"resolution {res['pnl_held_to_resolution'] if res['pnl_held_to_resolution'] is None else round(res['pnl_held_to_resolution'], 2)}",
              flush=True)
    print(f"\nmarket replays: {len(anchors)} anchors x {len(scenarios)} scenarios in {time.time() - t0:.1f} s", flush=True)
    # --- 3. summaries ----------------------------------------------------------------------------------
    def agg(j):
        rs = [results[k][j] for k in results]
        sent = sum(r["strategy"].get("send", 0) for r in rs)
        filled = sum(len(r["fills"]) for r in rs)
        return dict(scenario=scenarios[j], anchors=len(rs), calls=sum(r["strategy"]["calls"] for r in rs),
                    orders_sent=sent, orders_filled=filled,
                    shares_filled=sum(f["shares"] for r in rs for f in r["fills"]),
                    fees=sum(r["fees"] for r in rs),
                    pnl_marked_10s=sum(r["pnl_marked_10s"] or 0 for r in rs),
                    pnl_marked_60s=sum(r["pnl_marked_60s"] or 0 for r in rs),
                    pnl_held_to_resolution=(sum(r["pnl_held_to_resolution"] for r in rs)
                                            if all(r["pnl_held_to_resolution"] is not None for r in rs) else None),
                    skip_reasons={k: sum(r["strategy"]["skip_reasons"].get(k, 0) for r in rs)
                                  for k in {k for r in rs for k in r["strategy"]["skip_reasons"]}})
    sens = [agg(j) for j in range(len(scenarios))]
    lat_q = {}
    try:
        lat_q = json.loads(LAT_SUMMARY.read_text())["m1"]["book_vs_official_T_s"]
    except Exception:
        pass
    budget = latency_budget(V, primary, lat120, lat_q, lag_cal,
                            [c["decision"]["compute_us"] for k in results for r in results[k] for c in r["calls"]],
                            [c["decision"].get("total_us") for k in results for r in results[k] for c in r["calls"]])
    out = dict(label=ILLUSTRATIVE, paper_only=True, orders_sent_to_any_venue=0,
               when=time.strftime("%Y-%m-%d %H:%M:%S %Z"), runtime_s=round(time.time() - t_start, 1),
               mapping=dict(rule=("t_end = T_official - stamp_lag; clip frame f is placed at t_end - (f_end - f)/120 s; "
                                  "decision at t_frame + measured vision latency (+ camera_ms); order arrives one-way "
                                  "later and executes 1 s after that against the book then."),
                            f_end=f_end, anchor_flight=anchor_flight,
                            players=("The clip's anchor shot is hit by the player at the image's left when it travels "
                                     "left->right; that hitter stands in for the WTA point's loser, so the anchor call is "
                                     "right by construction (it was right on the table-tennis labels). Every other call "
                                     "follows from the same fixed mapping and can be wrong (the frame-2759 MISS was "
                                     "flagged 'rally_continues' by the label audit)."),
                            anchor_rule=(f"{len(anchors)} points spread evenly over the match (early and late) among "
                                         "those with a >= 3c covered reprice and a reprice lead inside the measured IQR "
                                         f"[{iqr[0]}, {iqr[1]}] s; chosen before any fill was seen"),
                            stamp_lag_note=("t_stamp - t_bounce is not measured: 2.0 s is the tier-0 primary; "
                                            f"{lag_cal} s is inferred from fast-tier prints (results/tier0)"),
                            camera_ms=a.camera_ms),
               vision=V, match=dict(match, recording=a.files, points_file=str(M1.relative_to(REPO))),
               strategy_config=asdict(StrategyConfig()), risk_config=asdict(RiskConfig()),
               primary_scenario=primary,
               anchors=[_anchor_out(an, results[an["k"]]) for an in anchors],
               sensitivity=sens, latency_budget=budget)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "demo_run.json").write_text(json.dumps(_clean(out), indent=1, default=str))
    # figure: the anchor where the rule sent the most orders (earliest on ties)
    fk = max(sorted(results), key=lambda k: (results[k][0]["strategy"].get("send", 0), -k))
    t_end = results[fk][0]["t_end_ms"]
    ta = match["tokens"][0]
    ser = sorted(series[fk])
    keep = [x for x in ser if -9000 <= x[0] - t_end <= 5000]
    first = [max((x for x in ser if x[1] == tok and x[0] - t_end < -9000), default=None) for tok in match["tokens"]]
    out["figure_anchor"] = fk
    out["figure_rule"] = "the anchor where the rule sent the most orders in the primary scenario (earliest on ties)"
    out["figure_series"] = [[(x[0] - t_end) / 1000, "A" if x[1] == ta else "B", x[2], x[3]]
                            for x in [f for f in first if f] + keep]
    (OUT / "demo_run.json").write_text(json.dumps(_clean(out), indent=1, default=str))
    timeline_figure(_clean(out), OUT / "demo_timeline.png")
    print("\nsensitivity (sum over anchors): stamp lag | location | vision -> sent / filled / P&L +10 s / held")
    for s in sens:
        sc = s["scenario"]
        hr = s["pnl_held_to_resolution"]
        print(f"  {sc['stamp_lag_s']:5.2f} s | {sc['location']:7s} | {sc['vision']:13s} -> {s['orders_sent']:2d} / "
              f"{s['orders_filled']:2d} / {s['pnl_marked_10s']:+8.2f} / {'n/a' if hr is None else f'{hr:+.2f}'}  "
              f"{s['skip_reasons']}")
    print("\n" + ILLUSTRATIVE)
    print(f"wrote {OUT / 'demo_run.json'} and {OUT / 'demo_timeline.png'}", flush=True)
    return out


def _anchor_out(an: dict, rs: list) -> dict:
    d = {k: v for k, v in an.items() if k not in ("state",)}
    d["state_before"] = asdict(an["state"])
    d["primary"] = rs[0]
    d["other_scenarios"] = [{k: r[k] for k in ("scenario", "orders", "fills", "pnl_marked_10s", "pnl_marked_60s",
                                                "pnl_held_to_resolution", "strategy")} for r in rs[1:]]
    return d


def latency_budget(V: dict, primary: dict, lat120, lat_q: dict, lag_cal, compute_us=(), total_us=()) -> list[dict]:
    tm = V["timing"]
    cu = [x for x in compute_us if x is not None]
    tu = [x for x in total_us if x is not None]
    return [
        dict(stage="camera -> frame available", ms=primary.get("camera_ms", 0.0),
             source="not measured; 0 in the demo (file paced). A courtside camera adds capture + encode + transport."),
        dict(stage="vision: frame -> CallEvent, processing only (a host that keeps up)",
             ms=tm.get("call_ready_processing_ms", {}).get("p50"), p90=tm.get("call_ready_processing_ms", {}).get("p90"),
             source=f"this demo run, {V['detector']}: end-to-end minus the decision frame's queue wait"),
        dict(stage="vision: frame -> CallEvent, as run on this shared laptop", ms=tm["call_ready_ms"].get("p50"),
             p90=tm["call_ready_ms"].get("p90"),
             source=f"this demo run: {tm.get('fps_sustained')} fps sustained vs {V['arrival_fps']} fps arrivals "
                    f"(load from other jobs), so frames queue"),
        dict(stage="vision on this laptop at true 120 fps", ms=lat120,
             source="results/engine/vision_bench.json realtime p50: the laptop sustains ~50 fps unloaded, so a "
                    "120 fps feed backs up without bound"),
        dict(stage="strategy rule (fair jump + rule, evaluate(); no risk check, no submit)",
             ms=(round(float(np.median(cu)) / 1000, 3) if cu else None),
             p90=(round(float(np.percentile(cu, 90)) / 1000, 3) if cu else None),
             source="this demo run, per call (decision.compute_us)"),
        dict(stage="strategy on_call end to end (rule + paper guard + risk + paper submit)",
             ms=(round(float(np.median(tu)) / 1000, 3) if tu else None),
             p90=(round(float(np.percentile(tu, 90)) / 1000, 3) if tu else None),
             source="this demo run, per call (decision.total_us)"),
        dict(stage="order one-way, laptop (Gainesville) -> venue", ms=FLORIDA_MS, source="src/paper.py FLORIDA_MS"),
        dict(stage="order one-way, London co-located", ms=LONDON_MS, source="src/paper.py LONDON_MS"),
        dict(stage="venue marketable-order delay", ms=VENUE_DELAY_MS, source="measured (1 s regime)"),
        dict(stage="market-data feed delay, venue -> laptop", ms=58, p95=102, p99=134,
             source="engine/market live measurement 2026-10-03"),
        dict(stage="book reprice vs official point stamp", ms=(lat_q.get("median") or -1.16) * 1000,
             p25=(lat_q.get("p25") or -1.93) * 1000, p75=(lat_q.get("p75") or -0.68) * 1000,
             source="research/v2/latency (482 live WTA points): the book moves before the stamp"),
        dict(stage="stamp lag t_stamp - t_bounce", ms=primary["stamp_lag_s"] * 1000,
             source=f"NOT measured: tier-0 primary 2.0 s; inferred {lag_cal} s"),
        dict(stage="stale depth after the reprice", ms=500,
             source="measured: median $222-565 per point before the reprice, ~$0 0.5 s after"),
    ]


def timeline_figure(out: dict, path: Path) -> None:
    """Timeline of one anchored point (primary scenario): clip frames and calls, orders, real book."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, ink2, muted, grid_c, surf = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"
    blue, orange = "#2a78d6", "#eb6834"
    plt.rcParams.update({"font.size": 9.5, "axes.edgecolor": grid_c, "axes.labelcolor": ink2, "xtick.color": ink2,
                         "ytick.color": ink2, "figure.facecolor": surf, "axes.facecolor": surf,
                         "savefig.facecolor": surf})
    fk = out["figure_anchor"]
    an = out["anchors"][fk]
    res = an["primary"]
    match = out["match"]
    t_end = res["t_end_ms"]
    w = an["winner"]
    wl = "A" if w == 0 else "B"
    name_w, name_l = match["names"][w], match["names"][1 - w]
    sur = lambda n: n.split()[-1]
    x0, x1 = -8.0, 4.0
    fig = plt.figure(figsize=(11.5, 7.8))
    gs = fig.add_gridspec(3, 1, height_ratios=[1.0, 0.9, 3.0], hspace=0.12)
    ax_v, ax_o, ax_p = (fig.add_subplot(gs[i]) for i in range(3))
    for ax in (ax_v, ax_o, ax_p):
        ax.set_xlim(x0, x1)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.axvline(0, color=ink, lw=1, zorder=1)
    for ax in (ax_v, ax_o):
        ax.set_yticks([])
        ax.tick_params(axis="x", labelbottom=False, length=0)
    # --- vision lane
    V = out["vision"]
    f0, nfr = V["first_frame"], V["frames"]
    c0, c1 = (f0 - an["f_end"]) / FPS, (f0 + nfr - 1 - an["f_end"]) / FPS
    ax_v.add_patch(plt.Rectangle((c0, 0.47), c1 - c0, 0.12, color=grid_c, lw=0))
    ax_v.text(c0, 1.02, f"table-tennis clip ({V['video']} frames {f0}-{f0 + nfr - 1}, 120 fps), placed so its point "
              f"end (frame {an['f_end']}) falls on the WTA point's physical end", color=ink2, fontsize=8.5, va="bottom")
    ax_v.text(c0, 0.72, "|  BOUNCE call: no trade, refreshes the fair-value calibration      ▼  MISS call: the hitter "
              "loses the point", color=muted, fontsize=8, va="bottom")
    ax_v.set_ylim(0, 1.35)
    misses = [c for c in res["calls"] if c["call"] == "MISS"]
    for c in res["calls"]:
        x = c["t_frame_rel_s"]
        if c["call"] != "MISS":
            ax_v.plot([x], [0.53], marker="|", ms=12, mew=2, color=muted, zorder=3)
            continue
        i = misses.index(c)
        right = c["decision"]["winner"] == w
        col = blue if right else orange
        ax_v.plot([x], [0.53], marker="v", ms=10, color=col, mec=surf, mew=1.5, zorder=4)
        ax_v.annotate(f"MISS f{c['frame']}: {sur(c['decision']['winner_name'])} wins"
                      + (" (right)" if right else " (wrong)"), (x, 0.47),
                      xytext=(-4 if i % 2 == 0 else 4, -12), textcoords="offset points",
                      ha="right" if i % 2 == 0 else "left", va="top", fontsize=8, color=ink)
    ax_v.set_title("COURTSIDE demo, ILLUSTRATIVE PAIRING (table-tennis calls on a WTA book; not a backtest): "
                   "vision call → paper order → fill", loc="left", color=ink, fontsize=11.5, pad=6)
    # --- orders lane
    sc = res["scenario"]
    ax_o.set_ylim(0, 1)
    ax_o.text(x0, 0.97, f"● decision / order sent    | arrives (+{sc['one_way_ms']} ms)    ■ executes (+1 s venue "
              f"delay)    × no order", fontsize=8, color=ink2, va="top")
    for i, c in enumerate(misses):
        y = 0.62 - 0.36 * i
        d = c["decision"]
        col = blue if d["winner"] == w else orange
        o = c["order"]
        if not o:
            ax_o.plot([c["t_dec_rel_s"]], [y], "x", color=col, ms=8, mew=2)
            why = d["reason"] + (f" (edge {100 * d['edge']:+.1f}¢)" if d.get("edge") is not None else "")
            ax_o.text(c["t_dec_rel_s"] - 0.15, y, f"f{c['frame']}: no order, {why}", va="center", ha="right",
                      fontsize=8, color=ink)
            continue
        od = next(x for x in res["orders"] if x["id"] == d["order_id"])
        ax_o.plot([c["t_dec_rel_s"], o["t_exec_rel_s"]], [y, y], color=col, lw=2, solid_capstyle="round")
        ax_o.plot([c["t_dec_rel_s"]], [y], "o", color=col, ms=8, mec=surf, mew=1.5)
        ax_o.plot([o["t_arrive_rel_s"]], [y], "|", color=ink, ms=10, mew=1.5)
        ax_o.plot([o["t_exec_rel_s"]], [y], "s", color=col, ms=8, mec=surf, mew=1.5)
        res_txt = (f"filled {od['filled']:.0f} @ {od['vwap']:.3f}" if od["filled"] else
                   f"{od['status']} ({od['reason'].replace('_', ' ')})")
        ax_o.text(c["t_dec_rel_s"] - 0.15, y, f"f{c['frame']}: BUY {od['shares']:.0f} {sur(d['winner_name'])} "
                  f"@ ≤{d['limit']:.2f} (edge {100 * d['edge']:+.1f}¢) → {res_txt}", va="center", ha="right",
                  fontsize=8, color=ink)
    # --- price panel
    ser = out["figure_series"]
    for tl, col, nm in ((wl, blue, f"{name_w} (won the point)"), ("B" if wl == "A" else "A", orange, name_l)):
        pts = [p for p in ser if p[1] == tl]
        if not pts:
            continue
        xs = [max(x0, min(x1, p[0])) for p in pts] + [x1]
        bids = [p[2] for p in pts] + [pts[-1][2]]
        asks = [p[3] for p in pts] + [pts[-1][3]]
        ax_p.step(xs, asks, where="post", color=col, lw=2, label=f"{nm}: best ask")
        ax_p.step(xs, bids, where="post", color=col, lw=1.2, ls=(0, (3, 2)), label=f"{nm}: best bid")
    for f in res["fills"]:
        col = blue if f["token"] == wl else orange
        ax_p.plot([f["t_exec_rel_s"]], [f["vwap"]], "s", color=col, ms=10, mec=ink, mew=1.2, zorder=5)
        ax_p.annotate(f"paper fill {f['shares']:.0f} @ {f['vwap']:.3f}", (f["t_exec_rel_s"], f["vwap"]),
                      xytext=(9, -3), textcoords="offset points", fontsize=8.5, color=ink, va="top")
    rb = (an["t_book_ms"] - t_end) / 1000
    for x, lab in ((rb, "book reprice"), ((an["T_ms"] - t_end) / 1000, "official stamp")):
        if x0 <= x <= x1:
            ax_p.axvline(x, color=muted, lw=1, ls=(0, (2, 2)), zorder=1)
            ax_p.text(x, 1.01, lab, transform=ax_p.get_xaxis_transform(), va="bottom", ha="left", fontsize=8,
                      color=ink2)
    ax_p.axvspan(rb, rb + 0.5, color=grid_c, alpha=0.6, lw=0, zorder=0)
    ax_p.text(-0.05, 1.01, "physical point end (t = 0)", transform=ax_p.get_xaxis_transform(), va="bottom",
              ha="right", fontsize=8, color=ink)
    ax_p.grid(axis="y", color=grid_c, lw=0.6)
    ax_p.set_ylabel("token price ($)")
    ax_p.set_xlabel(f"seconds relative to the WTA point's physical end (official stamp − {sc['stamp_lag_s']:g} s "
                    "assumed stamp lag)")
    ax_p.legend(loc="lower left", frameon=False, fontsize=8, ncol=2)
    st = an["state_before"]
    fig.text(0.01, 0.012, f"Book: {match['slug']}, point {an['n']} (set {an['set']}, games {st['ga']}-{st['gb']}, "
             f"points {st['pa']}-{st['pb']} before; {name_w} won it, the book moved {an['D'] * 100:.1f}¢). One-way "
             f"{sc['one_way_ms']} ms ({sc['location']}); vision latency: processing time measured this run. Shaded: "
             "the 0.5 s after the reprice, when stale depth disappears.\n" + ILLUSTRATIVE,
             color=ink2, fontsize=7.4, ha="left", va="bottom", wrap=True)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.95, bottom=0.17)
    fig.savefig(path, dpi=160)
    plt.close(fig)


# =====================================================================================================
# (c) backtest: tier-0 counterfactual (other workstream; imported, never modified)
# =====================================================================================================
def backtest(a) -> dict | None:
    assert_paper_only()
    need = [REPO / "src" / "tier0.py", REPO / "scripts" / "tier0_backtest.py"]
    if not all(p.exists() for p in need):
        print("The tier-0 counterfactual backtest is not in this checkout yet.\n"
              "  Expected: src/tier0.py, scripts/tier0_backtest.py (pre-registered in research/v2/tier0/PREREG.md)\n"
              "  Then:     python scripts/tier0_backtest.py            # full grid -> results/tier0/\n"
              "            python -m engine.run --mode backtest         # prints results/tier0/results.json")
        return None
    if a.recompute:
        import scripts.tier0_backtest as TB   # imports src.tier0 itself
        print(TB.T.ASSUMED, flush=True)
        # the corrected headline when the tier-0 code has one (results.json "headline"), else the pre-registered primary
        scs = [("headline (corrected)", TB.T.CORRECTED)] if hasattr(TB.T, "CORRECTED") else []
        scs.append(("pre-registered primary" + (" (superseded, record only)" if scs else ""), TB.T.PRIMARY))
        with open(REPO / "results" / "oos_peeks.log", "a") as fh:   # project convention: log every burned-OOS read
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} engine.run --mode backtest --recompute: tier0 "
                     f"{' + '.join(n for n, _ in scs)}, one seed, re-run on burned OOS (non-blind, labelled; no rule "
                     "or parameter chosen)\n")
        out = {}
        for name, sc in scs:
            for period in ("IS", "burned_OOS"):
                t = time.time()
                m = TB.slim(TB.run_one(sc, period))
                out[f"{name} | {period}"] = m
                print(f"{name} | {period} (one seed, recomputed in {time.time() - t:.0f} s): Sharpe {m.get('sharpe_ann')}, "
                      f"{m.get('per_share_c')} c/share, {m.get('n_trades')} trades, fill rate {m.get('fill_rate')}",
                      flush=True)
        return out
    if not TIER0.exists():
        print("results/tier0/results.json missing: run `python scripts/tier0_backtest.py` (or --recompute here)")
        return None
    r = json.loads(TIER0.read_text())
    keys = ("n_calls", "n_trades", "fill_rate", "calls_share_before_reprice", "per_share_c", "per_share_ci95_c",
            "pnl_per_day_usd", "sharpe_ann", "max_dd_usd", "worst_day_usd", "months_positive", "months_total",
            "capital_usd", "return_on_capital_ann_pct", "wrong_call_share_of_trades", "days")
    print(r["label"].upper())
    print(f"prereg: {r.get('prereg')}   deviations: {r.get('deviations')}   (file written "
          f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(TIER0.stat().st_mtime))})")
    if "headline" in r:   # schema after the tier-0 verifier corrections: corrected headline + pre-registered record
        print(f"headline scenario (corrected): {r.get('headline_scenario')}")
        for p in ("IS", "burned_OOS"):
            h = r["headline"][p]
            m, sd = h.get("mean", {}), h.get("sd", {})
            print(f"\nHEADLINE {p} (mean of {h.get('n_seeds')} seeds): "
                  + ", ".join(f"{k}={m.get(k)}" for k in keys if k in m)
                  + f"\n  seed sd: Sharpe {sd.get('sharpe_ann')}, c/share {sd.get('per_share_c')}, $/day {sd.get('pnl_per_day_usd')}")
        for p, v in (r.get("grid_corrected", {}).get("both_readings") or {}).items():
            print(f"{p} corrected grid ({v.get('n_scenarios')} scenarios): Sharpe min/median/max "
                  f"{v['sharpe_ann']['min']}/{v['sharpe_ann']['median']}/{v['sharpe_ann']['max']}, share with P&L > 0 "
                  f"{v.get('share_scenarios_positive_pnl')}")
        st = r.get("stresses_corrected") or {}
        if st:
            print("\nstresses (Sharpe IS / burned OOS, seed means):")
            for k, v in st.items():
                s = [(v.get(p) or {}).get("mean", {}).get("sharpe_ann") for p in ("IS", "burned_OOS")]
                print(f"  {k[:78]:78s} {s[0]} / {s[1]}")
        pr = r.get("prereg_record") or {}
        if pr.get("primary"):
            s = [((pr["primary"].get(p) or {}).get("mean") or pr["primary"].get(p) or {}).get("sharpe_ann")
                 for p in ("IS", "burned_OOS")]
            print(f"\npre-registered primary (record only: {pr.get('note', '')}): Sharpe IS {s[0]} / burned OOS {s[1]}")
    else:                 # original schema (pre-registered primary only)
        print(f"primary scenario: {r['primary_scenario']}")
        for p in ("IS", "burned_OOS"):
            print(f"\n{p}: " + ", ".join(f"{k}={r['primary'][p].get(k)}" for k in keys if k in r["primary"][p]))
        sp = r.get("primary_seed_spread", {})
        for p, v in sp.items():
            print(f"{p} Monte Carlo seed spread (20 seeds): Sharpe {v['sharpe_ann']['mean']} ± {v['sharpe_ann']['sd']}, "
                  f"$/day {v['pnl_per_day_usd']['mean']} ± {v['pnl_per_day_usd']['sd']}")
        gr = r.get("grid_ranges", {})
        for p, v in gr.items():
            print(f"{p} grid ({v.get('n_scenarios')} scenarios): Sharpe min/median/max {v['sharpe_ann']['min']}/"
                  f"{v['sharpe_ann']['median']}/{v['sharpe_ann']['max']}, share with P&L > 0 "
                  f"{v.get('share_scenarios_positive_pnl')}")
    v2 = REPO / "results" / "v2" / "burned_oos.json"
    if v2.exists():
        b = json.loads(v2.read_text())["burned_oos"]
        print(f"\nFor reference, NOT this strategy: v2 (book-only, no vision) burned OOS: {b['per_share_c']:.2f}c/share "
              f"CI [{b['per_share_ci_c'][0]:.2f}, {b['per_share_ci_c'][1]:.2f}], Sharpe {b['sharpe_ann']:.1f}, "
              f"{b['days']} days (results/v2/burned_oos.json)")
    return r


# =====================================================================================================
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=("live-market", "demo", "backtest"))
    ap.add_argument("--enable-live-trading", action="store_true", help=argparse.SUPPRESS)
    # live-market
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--every", type=float, default=15)
    ap.add_argument("--max-matches", type=int, default=12)
    # demo
    ap.add_argument("--clip", default=str(CLIP))
    ap.add_argument("--video", default="test_2")
    ap.add_argument("--frame-offset", type=int, default=2000, help="source frame number of the clip's first frame")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--backend", default="onnx-coreml-gpu16,onnx-coreml-ane16")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--vision-fps", type=float, default=30.0,
                    help="frame arrival rate for the clip (it is 120 fps video; the laptop sustains ~25-50 fps "
                         "depending on load, so 120 would only measure the backlog)")
    ap.add_argument("--frozen", default=str(REPO / "models" / "vision" / "frozen_call_model.pkl"))
    ap.add_argument("--match", default="wta-su-bucsa-2026-10-02")
    ap.add_argument("--files", default="data/live/market_*")
    ap.add_argument("--anchors", type=int, default=8)
    ap.add_argument("--stamp-lag", type=float, default=2.0)
    ap.add_argument("--location", default="florida", choices=("florida", "london"))
    ap.add_argument("--camera-ms", type=float, default=0.0)
    ap.add_argument("--reuse-vision", default=None, help="reuse the vision section of an earlier demo_run.json")
    ap.add_argument("--figure-only", action="store_true", help="redraw demo_timeline.png from demo_run.json")
    # backtest
    ap.add_argument("--recompute", action="store_true")
    a = ap.parse_args(argv)
    if a.enable_live_trading:
        enable_live_trading()          # always raises LiveTradingForbidden
    assert_paper_only()
    if a.mode == "live-market":
        asyncio.run(live_market(a))
    elif a.mode == "demo" and a.figure_only:
        timeline_figure(json.loads((OUT / "demo_run.json").read_text()), OUT / "demo_timeline.png")
    elif a.mode == "demo":
        a.files = str(REPO / a.files) if not Path(a.files).is_absolute() else a.files
        demo(a)
    else:
        backtest(a)


if __name__ == "__main__":
    try:
        main()
    except LiveTradingForbidden as e:
        raise SystemExit(f"REFUSED (paper only): {e}")
