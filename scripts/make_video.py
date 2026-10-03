"""Narrated COURTSIDE video (~4:30 at the 2026-10-03 render), every number read from results files at render time.

    .venv/bin/python scripts/make_video.py                 # full render
    .venv/bin/python scripts/make_video.py --stills        # one PNG per scene (end state) for review
    .venv/bin/python scripts/make_video.py --scenes S06,S09 --stills

Outputs
    results/viz/courtside_video.mp4     1920x1080, 30 fps, H.264 + AAC, faststart, captions burned in
    results/viz/courtside_video.srt     sidecar captions
    results/viz/video_manifest.json     every number on screen or in the narration -> source file + key

The narration lives in docs/video_script.md (one caption per '>' line, {names} filled from build_values()).
Voice: macOS `say` (Samantha). Each caption is rendered to AIFF, so captions are timed to the audio exactly.
A result whose file does not exist yet renders as "pending". Tier-0 is always labelled a counterfactual.
Everything is paper trading. We bought no official ATP/WTA data feed and no trading result uses one; free public
score pages (WTA website, ESPN) were recorded only to time how far they lag the book.
Dates are printed instead of "tonight"/"tomorrow", so a render stays true after the forward test.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

W, H, FPS = 1920, 1080, 30
XF = 0.3            # crossfade length (s)
LEAD = 0.3          # silence before the narration in each scene; the same again after it (scene = narration + 0.6 s)
HOLD = {"backtest": 1.5, "scoreboard": 1.5, "risk": 1.5, "close": 3.0}   # extra seconds on dense scenes / end card
GAP = 0.12          # pause between captions inside a scene
SR = 48000
VOICE, RATE = "Samantha", 215
OUT = Path("results/viz/courtside_video.mp4")
SRT = Path("results/viz/courtside_video.srt")
MANIFEST = Path("results/viz/video_manifest.json")
SCRIPT = Path("docs/video_script.md")
WORK = Path("data/v2_video_frames/video")      # cache (data/ is never committed)
TIER0_LABEL = ("counterfactual: assumes a licensed live feed + courtside camera (not purchased); "
               "parameters measured")
CREDIT = "Footage: OpenTTGames (OSAI), adapted (overlays added), CC BY-NC-SA 4.0"

# palette and type
BG, PANEL, PANEL2, GRID = "#07111b", "#0d1b29", "#112336", "#1f3346"
INK, MUTED, DIM = "#e8eef4", "#8fa2b5", "#5d6f82"
BLUE, CYAN, CORAL, AMBER, GREEN, GREY = "#3987e5", "#7fd1e8", "#f06a52", "#e8b04b", "#4cc38a", "#7d8fa3"
AV = "/System/Library/Fonts/Avenir Next.ttc"
AV_IDX = {"bold": 0, "demi": 2, "medium": 5, "regular": 7, "heavy": 8}
MX = 120            # 16:9 safe margin (title-safe ~6%)
KICKERS = {"economics": "the economics", "evidence": "evidence", "vision": "computer vision",
           "tennis": "computer vision, tennis", "backtest": "the backtest", "overfitting": "overfitting checks",
           "scoreboard": "blind tests", "tier0": "tier-0 counterfactual", "live": "live, paper only",
           "risk": "risk, liquidity, financials"}


def rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, k):
    """k=1 -> a, k=0 -> b."""
    a, b = rgb(a) if isinstance(a, str) else a, rgb(b) if isinstance(b, str) else b
    return tuple(int(round(a[i] * k + b[i] * (1 - k))) for i in range(3))


_FONTS: dict = {}


def F(size, w="regular"):
    key = (size, w)
    if key not in _FONTS:
        try:
            _FONTS[key] = ImageFont.truetype(AV, size, index=AV_IDX[w])
        except OSError:  # non-mac fallback
            name = "DejaVuSans-Bold.ttf" if w in ("bold", "demi", "heavy") else "DejaVuSans.ttf"
            _FONTS[key] = ImageFont.truetype(str(Path(matplotlib.get_data_path()) / "fonts/ttf" / name), size)
    return _FONTS[key]


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def disp(s: str) -> str:
    """Typographic minus for on-screen numbers."""
    return re.sub(r"(?<![\w.])-(?=\$?\d)", "−", s)


def spoken(s: str) -> str:
    s = s.replace("−", "-")
    s = re.sub(r"(?<![\w.])-(?=\d)", "minus ", s)
    return s.replace("%", " percent").replace("¢", " cents")


# ----------------------------------------------------------------------------------------------------
# results registry + manifest
# ----------------------------------------------------------------------------------------------------
class Results:
    def __init__(self):
        self.files: dict = {}
        self.entries: dict = {}
        self.scene = "global"

    def load(self, f):
        if f not in self.files:
            p = Path(f)
            if not p.exists():
                self.files[f] = None
            elif p.suffix == ".json":
                self.files[f] = json.loads(p.read_text())
            elif p.suffix == ".csv":
                with p.open() as fh:
                    self.files[f] = list(csv.DictReader(fh))
            else:
                self.files[f] = p.read_text()
        return self.files[f]

    def get(self, f, *keys):
        d = self.load(f)
        for k in keys:
            if d is None:
                return None
            try:
                d = d[k]
            except (KeyError, IndexError, TypeError):
                return None
        return d

    def put(self, name, value, file, key, say=None, note=None):
        self.entries[name] = {"value": value, "file": file, "key": key, "say": say, "note": note,
                              "pending": value is None, "used_in": []}
        return value

    def __getitem__(self, name):
        e = self.entries[name]
        if self.scene not in e["used_in"]:
            e["used_in"].append(self.scene)
        return e["value"]

    def pending(self, name):
        return self.entries[name]["value"] is None

    def say(self, name):
        e = self.entries[name]
        if self.scene not in e["used_in"]:
            e["used_in"].append(self.scene)
        if e["value"] is None:
            return "pending"
        fmt = e["say"] or "{}"
        return fmt(e["value"]) if callable(fmt) else fmt.format(e["value"])


def floor2(x):
    return f"{math.floor(x * 100) / 100:.2f}"


def valid_mp4(path) -> bool:
    """True only for a complete video (another workflow may still be writing it)."""
    if not Path(path).exists():
        return False
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                        str(path)], capture_output=True, text=True)
    try:
        return r.returncode == 0 and float(r.stdout.strip()) > 1.0
    except ValueError:
        return False


def live_state(sm, path="results/live/summary.json"):
    """State of the live paper session from its rolling summary. Never says 'running' for a stopped,
    stale or warming-up session: a STOPPED_<run> marker or a status mentioning stopped/error/killed means
    stopped; 'now' at the epoch (1970) or empty counters means warming up; no write for 15 min means no update."""
    import datetime as _dt
    out = {"state": None, "status": None, "since": None, "asof": None, "sentence": "The live paper session is pending."}
    if sm is None:
        return out
    status = str(sm.get("status", ""))
    run = sm.get("run") or ""
    since = str(sm.get("started_process") or sm.get("session_start") or "")[:16].replace("T", " ")
    now = str(sm.get("now") or "")
    p = Path(path)
    mtime = _dt.datetime.fromtimestamp(p.stat().st_mtime, _dt.timezone.utc)
    asof = now[:16].replace("T", " ") if now and not now.startswith("1970") else mtime.strftime("%Y-%m-%d %H:%M")
    age_min = (_dt.datetime.now(_dt.timezone.utc) - mtime).total_seconds() / 60
    low = status.lower()
    if (run and (p.parent / f"STOPPED_{run}").exists()) or re.search(r"\b(stopped|error|killed|crash\w*)\b", low):
        state = "stopped"
    elif re.search(r"\b(ended|done|complete|completed|final|settled|finished)\b", low):
        state = "finished"
    elif age_min > 15:
        state = "no update"
    elif now.startswith("1970") or not sm.get("counters") or low.startswith("warm"):
        state = "warming up"
    else:
        state = "running"
    out.update(state=state, status=status or None, since=since or None, asof=asof)
    day = since[:10] if since else "today"
    if state == "warming up":
        out["sentence"] = (f"A live paper session started on {day} at {since[11:16]} UTC; at render time it was still "
                           f"warming up, so it had not quoted yet.")
    elif state == "running":
        out["sentence"] = (f"A live paper session started on {day} at {since[11:16]} UTC; at render time it was "
                           f"quoting, with {sm.get('books', {}).get('B1', {}).get('fills')} fills on the "
                           f"pre-registered book.")
    elif state == "stopped":
        out["sentence"] = f"The live paper session of {day} was stopped before it finished."
    elif state == "finished":
        out["sentence"] = (f"The live paper session of {day} finished with "
                           f"{sm.get('books', {}).get('B1', {}).get('fills')} fills on the pre-registered book.")
    else:
        out["sentence"] = f"The live paper session of {day} had not written an update for {age_min:.0f} minutes at render time."
    return out


def build_values(R: Results):
    P = R.put
    # S01 / S04: real footage, frozen model (results/tracking)
    dm = "results/tracking/demo/manifest.json"
    clips = R.get(dm, "clips") or []
    for i, c in enumerate(clips):
        P(f"clip{i}_lead_ms", c.get("call_lead_ms"), dm, f"clips[{i}].call_lead_ms",
          note=f"embedded in {c.get('file')} overlay")
        P(f"clip{i}_pmiss", c.get("p_miss_at_50ms"), dm, f"clips[{i}].p_miss_at_50ms",
          note=f"embedded in {c.get('file')} overlay")
    P("tt_lead_ms", R.get(dm, "clips", 0, "call_lead_ms"), dm, "clips[0].call_lead_ms", say="{:.0f}")
    ts = "results/tracking/summary.json"
    ld = ("early_call", "miss_first_call_lead_test_ms")
    P("lead_med_ms", R.get(ts, *ld, "median"), ts, "early_call.miss_first_call_lead_test_ms.median", say="{:.0f}")
    P("lead_p90_ms", R.get(ts, *ld, "p90"), ts, "early_call.miss_first_call_lead_test_ms.p90")
    P("lead_n_called", R.get(ts, *ld, "n_called"), ts, "early_call.miss_first_call_lead_test_ms.n_called", say="{}")
    P("lead_n_miss", R.get(ts, *ld, "n_miss"), ts, "early_call.miss_first_call_lead_test_ms.n_miss", say="{}")
    led = [c.get("call_lead_ms") for c in clips if c.get("label") == "MISS"]
    P("hook_is_longest", None if not led or R.get(ts, *ld, "n_called") is None else
      bool(led[0] is not None and abs(led[0] - max(led)) < 1e-9), dm,
      "clips[0].call_lead_ms == max(call_lead_ms of MISS clips); the clips were picked from the test calls",
      note="the hook clip is the longest online call on held-out games")
    k50 = ("early_call", "precision_recall_test_snapshot", "50ms")
    P("tp50", R.get(ts, *k50, "tp"), ts, "early_call.precision_recall_test_snapshot.50ms.tp", say="{}")
    P("fp50", R.get(ts, *k50, "fp"), ts, "early_call.precision_recall_test_snapshot.50ms.fp")
    tp, fp = R.get(ts, *k50, "tp"), R.get(ts, *k50, "fp")
    P("calls50_phrase", None if tp is None else (f"it made {tp} calls, all correct" if fp == 0
                                                 else f"it made {tp + fp} calls, {tp} correct"), ts,
      "early_call.precision_recall_test_snapshot.50ms.tp, .fp", say="{}")
    P("prec50", R.get(ts, *k50, "precision"), ts, "early_call.precision_recall_test_snapshot.50ms.precision")
    P("n50", None if tp is None else tp + fp, ts, "early_call.precision_recall_test_snapshot.50ms.tp + .fp")
    wl = R.get(ts, *k50, "precision_wilson95")
    P("wil50", None if wl is None else wl[0] * 100, ts,
      "early_call.precision_recall_test_snapshot.50ms.precision_wilson95[0]", say="{:.0f}")
    rc = R.get(ts, *k50, "recall")
    P("recall50", None if rc is None else rc * 100, ts, "early_call.precision_recall_test_snapshot.50ms.recall",
      say="{:.0f}")
    P("verdict_h3", R.get(ts, "verdict"), ts, "verdict")
    P("n_test_miss", R.get(ts, "n_flights", "test", "MISS"), ts, "n_flights.test.MISS")
    P("n_test_bounce", R.get(ts, "n_flights", "test", "BOUNCE"), ts, "n_flights.test.BOUNCE")
    det = [d for d in (R.get(ts, "detection_accuracy_pooled") or []) if d["split"] == "test" and d["source"] == "tracked"]
    P("det_recall", det[0]["recall"] * 100 if det else None, ts, "detection_accuracy_pooled[split=test,source=tracked].recall")
    P("det_w5", det[0]["within5"] * 100 if det else None, ts,
      "detection_accuracy_pooled[split=test,source=tracked].within5")
    P("det_n", det[0]["n_visible"] if det else None, ts, "detection_accuracy_pooled[split=test,source=tracked].n_visible")

    # S02: latency tiers (same rungs, sources and latency as deck slides 2 and 4)
    sm_ = "results/summary.json"
    he = [r for r in (R.get(sm_, "tracking_tennis_physics") or []) if r.get("lead_ms") == 100]
    P("he100_cm", he[0]["pred_err_sd_cm"] if he else None, sm_, "tracking_tennis_physics[lead_ms=100].pred_err_sd_cm",
      note="simulated Hawk-Eye-class physics")
    ed = "results/engine/demo_run.json"
    vb = [r for r in (R.get(ed, "latency_budget") or []) if str(r.get("stage", "")).startswith("vision")]
    P("vis_ms", vb[0]["ms"] if vb else None, ed, "latency_budget[stage 'vision…'][0].ms (processing only)", say="{:.0f}",
      note="laptop benchmark; no courtside camera")
    P("vis_p90_ms", vb[0].get("p90") if vb else None, ed, "latency_budget[stage 'vision…'][0].p90")
    t0f = "results/tier0/results.json"
    P("book_vs_stamp_s", R.get(t0f, "timing", "median_t_reprice_minus_t_stamp_s"), t0f,
      "timing.median_t_reprice_minus_t_stamp_s", say=lambda v: f"{abs(v):.1f} seconds {'before' if v < 0 else 'after'}")
    P("stamp_lag_s", R.get(t0f, "timing", "calibrated_stamp_lag_s (inference)"), t0f,
      "timing.calibrated_stamp_lag_s (inference)", note="inference, not a measurement")
    dc = "results/decay/decay.json"
    P("espn_s", R.get(dc, "latency_inputs", "espn_behind_book_s"), dc, "latency_inputs.espn_behind_book_s", say="{:.0f}",
      note="recorded from the free ESPN scoreboard, research/v2/latency/RESULTS.md")
    P("h4_s", R.get(sm_, "h4", "median_lead_s"), sm_, "h4.median_lead_s", say="{:.0f}")
    hs = R.get(sm_, "h4", "share_book_first")
    P("h4_share", None if hs is None else hs * 100, sm_, "h4.share_book_first")
    P("h4_n", R.get(sm_, "h4", "n"), sm_, "h4.n")
    sd = R.get(dc, "latency_inputs", "stream_delay_s_assumed")
    P("stream_lo", sd[0] if sd else None, dc, "latency_inputs.stream_delay_s_assumed[0]", note="ASSUMPTION")
    P("stream_hi", sd[1] if sd else None, dc, "latency_inputs.stream_delay_s_assumed[1]", note="ASSUMPTION")
    fn = "results/financials/financials.json"
    P("feed_month", R.get(fn, "cost_assumptions", "feed_licence", "central"), fn,
      "cost_assumptions.feed_licence.central", note="ASSUMPTION (no public price)")
    P("vps_month", R.get(fn, "cost_assumptions", "vps_london", "central"), fn, "cost_assumptions.vps_london.central")
    nm = "results/v2/note_metrics.json"
    P("notional_day", R.get(nm, "is", "usd_traded_per_day"), nm, "is.usd_traded_per_day")
    P("share_of_volume", R.get(nm, "is", "v2_usd_traded_share_of_match_volume"), nm,
      "is.v2_usd_traded_share_of_match_volume")

    # S03: fast tier by month, walk-forward: in-sample months before the OOS start + OOS months (= deck slide 3)
    wis = R.get(sm_, "is", "h6_walkforward") or []
    wos = R.get(sm_, "oos", "h6_walkforward") or []
    om = (R.get(sm_, "universe", "oos_start") or "9999-99")[:7]
    rows = [dict(r, period="IS") for r in wis if r["month"] < om] + [dict(r, period="OOS") for r in wos]
    wsrc = "results/summary.json"
    wkey = "is.h6_walkforward (months before universe.oos_start) + oos.h6_walkforward"
    P("ft_rows", rows or None, wsrc, wkey + ": month, net30_c, others_net30_c, follow_res_c")
    P("ft_n", len(rows) or None, wsrc, "count(months) in " + wkey, say="{}")
    P("ft_n_oos", sum(r["period"] == "OOS" for r in rows) or None, wsrc, "count(oos.h6_walkforward)", say="{}")
    P("ft_pos", sum(r["net30_c"] > 0 for r in rows), wsrc, "count(net30_c > 0)", say="{}")
    P("ft_pos_oos", sum(r["net30_c"] > 0 for r in rows if r["period"] == "OOS"), wsrc,
      "count(oos.h6_walkforward net30_c > 0)", say="{}")
    P("oth_neg", sum(r["others_net30_c"] < 0 for r in rows), wsrc, "count(others_net30_c < 0)", say="{}")
    P("fol_neg", sum(r["follow_res_c"] < 0 for r in rows), wsrc, "count(follow_res_c < 0)", say="{}")
    P("ft_wallets_last", int(rows[-1]["n_wallets"]) if rows else None, wsrc, "n_wallets (last month)")

    # S05: tennis replay (simulated physics) + spin (simulation)
    vz = "results/viz/viz_data.json"
    preds = R.get(vz, "shot", "preds") or []
    lead = None
    for p in sorted(preds, key=lambda p: p["lead_ms"]):
        if p["p_out"] >= 0.95:
            lead = p["lead_ms"]
        else:
            break
    P("tennis_lead_ms", lead, vz, "shot.preds: largest lead_ms with p_out >= 0.95 at every shorter lead", say="{}")
    P("tennis_out_cm", R.get(vz, "shot", "out_cm"), vz, "shot.out_cm", note="embedded in courtside_replay.mp4")
    P("tennis_fps", R.get(vz, "shot", "fps"), vz, "shot.fps", say="{:.0f}")
    P("tape_title", R.get(vz, "tape", "title"), vz, "tape.title")
    P("tape_date", R.get(vz, "tape", "date"), vz, "tape.date")
    sp = "results/spin/tennis/metrics_v2.csv"
    srows = R.load(sp) or []

    def spin(method, col):
        r = [x for x in srows if x["method"] == method and x["lead_ms"] == "100" and x["cond"] == "nominal"]
        return float(r[0][col]) if r else None
    P("spin_bls_rpm", spin("bls", "rpm_err_med_abs"), sp, "cond=nominal,method=bls,lead_ms=100: rpm_err_med_abs")
    P("spin_base_rpm", spin("baseline", "rpm_err_med_abs"), sp,
      "cond=nominal,method=baseline,lead_ms=100: rpm_err_med_abs")
    P("spin_bls_axis", spin("bls", "axis_err_med_deg"), sp, "cond=nominal,method=bls,lead_ms=100: axis_err_med_deg")

    # S06: backtest
    ca = "results/v2/causal.json"
    for tag, k in (("is", "causal/is_eval/slip0.0"), ("oos", "causal/burned_oos/slip0.0")):
        P(f"{tag}_c", R.get(ca, k, "per_share_c"), ca, f"{k}.per_share_c", say="{:.2f}")
        ci = R.get(ca, k, "per_share_ci_c") or [None, None]
        P(f"{tag}_lo", ci[0], ca, f"{k}.per_share_ci_c[0]")
        P(f"{tag}_hi", ci[1], ca, f"{k}.per_share_ci_c[1]")
        P(f"{tag}_sh", R.get(ca, k, "sharpe_ann"), ca, f"{k}.sharpe_ann", say="{:.1f}")
        P(f"{tag}_dd", R.get(ca, k, "max_dd_pct"), ca, f"{k}.max_dd_pct", say=lambda v: f"{abs(v):.1f}")
        P(f"{tag}_cap", R.get(ca, k, "capital_usd"), ca, f"{k}.capital_usd")
        P(f"{tag}_pnl", R.get(ca, k, "total_pnl_usd"), ca, f"{k}.total_pnl_usd")
        P(f"{tag}_days", R.get(ca, k, "days"), ca, f"{k}.days")
        P(f"{tag}_trades", R.get(ca, k, "n_trades"), ca, f"{k}.n_trades")
        P(f"{tag}_mpos", R.get(ca, k, "months_positive"), ca, f"{k}.months_positive")
        P(f"{tag}_mtot", R.get(ca, k, "months_total"), ca, f"{k}.months_total")
        per = "IS" if tag == "is" else "OOS"
        ue = ("strategies", "v2", "periods", per, "unit_economics")
        P(f"{tag}_win", (R.get(fn, *ue, "trade_win_rate") or 0) * 100 or None, fn,
          f"strategies.v2.periods.{per}.unit_economics.trade_win_rate", say="{:.0f}")
        wci = R.get(fn, *ue, "trade_win_rate_ci95_match_clustered") or [None, None]
        P(f"{tag}_win_lo", wci[0] and wci[0] * 100, fn,
          f"strategies.v2.periods.{per}.unit_economics.trade_win_rate_ci95_match_clustered[0]")
        P(f"{tag}_win_hi", wci[1] and wci[1] * 100, fn,
          f"strategies.v2.periods.{per}.unit_economics.trade_win_rate_ci95_match_clustered[1]")
    cs = "results/v2/cost_stress.json"
    P("is_fee2_c", R.get(cs, "is_eval/fee_x2", "per_share_c"), cs, "is_eval/fee_x2.per_share_c")
    P("oos_fee2_c", R.get(cs, "burned_oos/fee_x2", "per_share_c"), cs, "burned_oos/fee_x2.per_share_c", say="{:.2f}")
    ci = R.get(cs, "burned_oos/fee_x2", "per_share_ci_c") or [None, None]
    P("oos_fee2_lo", ci[0], cs, "burned_oos/fee_x2.per_share_ci_c[0]")
    P("oos_fee2_hi", ci[1], cs, "burned_oos/fee_x2.per_share_ci_c[1]")
    P("oos_cost2_c", R.get(cs, "burned_oos/costs_x2", "per_share_c"), cs, "burned_oos/costs_x2.per_share_c")
    P("is_cost2_c", R.get(cs, "is_eval/costs_x2", "per_share_c"), cs, "is_eval/costs_x2.per_share_c")
    dl = "results/lowloss/daily.csv"
    drows = R.load(dl) or []
    P("eq_is", [(r["date"], float(r["pnl_usd"])) for r in drows if r["run"] == "a" and r["policy"] == "v2"
                and r["book"] == "u1_is"] or None, dl, "run=a,policy=v2,book=u1_is: date,pnl_usd")
    P("eq_oos", [(r["date"], float(r["pnl_usd"])) for r in drows if r["run"] == "a" and r["policy"] == "v2"
                 and r["book"] == "u1_oos"] or None, dl, "run=a,policy=v2,book=u1_oos: date,pnl_usd")

    # S07: rigor
    rg = "results/rigor/rigor.json"
    rr = {r["series"]: r for r in (R.get(rg, "psr_dsr", "rows") or [])}
    # DSR: lowest across the variance sources (dsr_min), at N = all trials incl. the v2-safe grid; 3 dp in deck and video
    for s in ("v2_is", "v2_oos", "v2_u2oos_blind"):
        for n in ("N44", "N3410"):
            P(f"dsr_{s}_{n}", rr.get(s, {}).get(f"dsr_min_{n}"), rg, f"psr_dsr.rows[series={s}].dsr_min_{n}")
    P("dsr_is", rr.get("v2_is", {}).get("dsr_min_N3410"), rg, "psr_dsr.rows[series=v2_is].dsr_min_N3410", say="{:.3f}")
    P("dsr_oos", rr.get("v2_oos", {}).get("dsr_min_N3410"), rg, "psr_dsr.rows[series=v2_oos].dsr_min_N3410",
      say="{:.3f}")
    P("oos_days", rr.get("v2_oos", {}).get("T"), rg, "psr_dsr.rows[series=v2_oos].T", say="{}")
    P("n_trials", R.get(rg, "psr_dsr", "N", "all_plus_v2safe_grid"), rg, "psr_dsr.N.all_plus_v2safe_grid", say="{:,}",
      note="NOTE section 8 counts 3,386; plus the 24-variant v2-safe grid")
    P("n_trials_small", R.get(rg, "psr_dsr", "N", "H1_H6"), rg, "psr_dsr.N.H1_H6")
    pb = R.get(rg, "pbo_cscv", "lowloss_24_sharpe", "pbo")
    P("pbo24", None if pb is None else pb * 100, rg, "pbo_cscv.lowloss_24_sharpe.pbo", say="{:.0f}")
    pb = R.get(rg, "pbo_cscv", "lowloss_24_selection_rule", "pbo")
    P("pbo24_sel", None if pb is None else pb * 100, rg, "pbo_cscv.lowloss_24_selection_rule.pbo", say="{:.0f}")
    P("pbo24_n", R.get(rg, "pbo_cscv", "lowloss_24_sharpe", "N_variants"), rg, "pbo_cscv.lowloss_24_sharpe.N_variants")
    P("cscv_blocks", R.get(rg, "pbo_cscv", "lowloss_24_sharpe", "S_blocks"), rg, "pbo_cscv.lowloss_24_sharpe.S_blocks")
    P("cscv_splits", R.get(rg, "pbo_cscv", "lowloss_24_sharpe", "n_splits"), rg, "pbo_cscv.lowloss_24_sharpe.n_splits")
    pb = R.get(rg, "pbo_cscv", "sizing_55_res_actual_sharpe", "pbo")
    P("pbo55", None if pb is None else pb * 100, rg, "pbo_cscv.sizing_55_res_actual_sharpe.pbo")
    P("pbo55_n", R.get(rg, "pbo_cscv", "sizing_55_res_actual_sharpe", "N_variants"), rg,
      "pbo_cscv.sizing_55_res_actual_sharpe.N_variants")
    P("boot_oos_p", R.get(rg, "bootstrap", "v2_oos", "p_sharpe_le_0"), rg, "bootstrap.v2_oos.p_sharpe_le_0")
    P("boot_is_p", R.get(rg, "bootstrap", "v2_is", "p_sharpe_le_0"), rg, "bootstrap.v2_is.p_sharpe_le_0")

    # S08: scoreboard
    ex = "results/expand/results.json"
    for tag in ("u2_is", "u2_oos"):
        P(f"{tag}_c", R.get(ex, "primary", tag, "per_share_c"), ex, f"primary.{tag}.per_share_c")
        ci = R.get(ex, "primary", tag, "per_share_ci_c") or [None, None]
        P(f"{tag}_lo", ci[0], ex, f"primary.{tag}.per_share_ci_c[0]")
        P(f"{tag}_hi", ci[1], ex, f"primary.{tag}.per_share_ci_c[1]")
        P(f"{tag}_label", R.get(ex, "primary", tag, "label"), ex, f"primary.{tag}.label")
    mk = "results/maker/oos.json"
    P("mk_c", R.get(mk, "primary", "value_c"), mk, "primary.value_c")
    ci = R.get(mk, "primary", "ci95_c") or [None, None]
    P("mk_lo", ci[0], mk, "primary.ci95_c[0]")
    P("mk_hi", ci[1], mk, "primary.ci95_c[1]")
    P("mk_verdict", R.get(mk, "primary", "verdict"), mk, "primary.verdict")
    P("mk_usd", R.get(mk, "headline", "total_pnl_usd"), mk, "headline.total_pnl_usd")
    v1s = "results/summary.json"
    P("v1_usd", R.get(v1s, "oos", "h6_shadow", "total_pnl_usd"), v1s, "oos.h6_shadow.total_pnl_usd",
      say=lambda v: f"{abs(v) / 1000:.0f} thousand")
    P("v1_dd", R.get(v1s, "oos", "h6_shadow", "max_dd"), v1s, "oos.h6_shadow.max_dd")
    t3 = "results/tier0_v3/blind.json"
    for tag, k in (("t3_u2is", "u2_is"), ("t3_u2oos", "u2_oos"), ("t3_boos", "burned_oos")):
        P(f"{tag}_c", R.get(t3, "sets", k, "primary", "per_share_c"), t3, f"sets.{k}.primary.per_share_c",
          say="{:.2f}", note="COUNTERFACTUAL (tier-0 v3, frozen)")
        P(f"{tag}_lo", R.get(t3, "sets", k, "primary", "per_share_ci95_c_lo"), t3, f"sets.{k}.primary.per_share_ci95_c_lo")
        P(f"{tag}_hi", R.get(t3, "sets", k, "primary", "per_share_ci95_c_hi"), t3, f"sets.{k}.primary.per_share_ci95_c_hi")
        P(f"{tag}_verdict", R.get(t3, "sets", k, "reading", "verdict"), t3, f"sets.{k}.reading.verdict")
    lab3 = R.get(t3, "label")
    if lab3 is not None and "COUNTERFACTUAL" not in str(lab3).upper():
        sys.exit(f"{t3} label lost its COUNTERFACTUAL marker")
    P("t3_overall", R.get(t3, "verdicts", "U2 (primary, test b)", "overall"), t3, "verdicts['U2 (primary, test b)'].overall")
    hv = R.load("HYPOTHESIS_V2.md") or ""
    mfw = re.search(r"planned ~?(\d{4}-\d\d-\d\d \d\d:\d\d UTC)", hv)
    P("fwd_when", mfw.group(1) if mfw else None, "HYPOTHESIS_V2.md", "Forward test: 'planned ~<date> UTC'", say="{}")
    tt = "results/tt/results.json"
    P("tt2_verdict", R.get(tt, "TT2", "verdict"), tt, "TT2.verdict")
    P("tt3_verdict", R.get(tt, "TT3", "verdict"), tt, "TT3.verdict")
    fw2 = "results/v2/forward.json"
    fwd = R.load(fw2)
    fv = None
    if fwd is not None:
        fv = fwd.get("verdict") or (fwd.get("primary") or {}).get("verdict") or "done"
    P("fwd_verdict", fv, fw2, "verdict | primary.verdict")
    when = R.entries["fwd_when"]["value"]
    P("forward_sentence", (f"The blind forward test runs once, planned for {when}." if when else
                           "The blind forward test has not run yet.") if fv is None
      else f"The blind forward test is done. Its verdict is {str(fv).lower()}.", fw2,
      "derived from verdict (absent: not run yet) + HYPOTHESIS_V2.md planned date", say="{}")
    peeks = R.load("results/oos_peeks.log")
    def verdict_word(v):
        v = str(v or "").upper()
        return "passed" if v.startswith("PASS") else "failed" if v.startswith("FAIL") else "is pending"
    ui, uo = R.entries["u2_is_label"]["value"], R.entries["u2_oos_label"]["value"]
    v1v = R.entries["v1_usd"]["value"]
    P("s08_sentence", f"Unseen markets {verdict_word(ui)} in sample and {verdict_word(uo)} out of sample. "
      + ("" if v1v is None else f"The original copy strategy {'lost' if v1v < 0 else 'made'} {abs(v1v) / 1000:.0f} "
         f"thousand dollars on its blind window, and ")
      + f"the market-making variant {verdict_word(R.entries['mk_verdict']['value'])} its blind test.",
      ex, "derived: expand primary.u2_is/u2_oos.label; summary.json oos.h6_shadow.total_pnl_usd; maker primary.verdict",
      say="{}")
    t3o = R.entries["t3_overall"]["value"]
    P("s08_sentence2", (f"The frozen tier-zero version {verdict_word(t3o)} its blind tests too. " if t3o else "")
      + ("In table tennis markets we detected no fast tier." if "no fast tier" in str(R.entries["tt2_verdict"]["value"]).lower()
         else f"Table tennis: {R.entries['tt2_verdict']['value'] or 'pending'}."),
      "results/tier0_v3/blind.json; results/tt/results.json", "derived: verdicts overall; TT2.verdict", say="{}")
    P("peeks", None if peeks is None else sum(1 for ln in peeks.splitlines() if ln.strip()), "results/oos_peeks.log",
      "count(non-empty lines) at render time", say="{}")

    # S09: tier-0 counterfactual
    t0 = "results/tier0/results.json"
    for tag, k in (("t0_is", "IS"), ("t0_oos", "burned_OOS")):
        P(f"{tag}_c", R.get(t0, "headline", k, "mean", "per_share_c"), t0, f"headline.{k}.mean.per_share_c",
          say="{:.2f}")
        P(f"{tag}_lo", R.get(t0, "headline", k, "mean", "per_share_ci95_c_lo"), t0,
          f"headline.{k}.mean.per_share_ci95_c_lo")
        P(f"{tag}_hi", R.get(t0, "headline", k, "mean", "per_share_ci95_c_hi"), t0,
          f"headline.{k}.mean.per_share_ci95_c_hi")
        P(f"{tag}_sh", R.get(t0, "headline", k, "mean", "sharpe_ann"), t0, f"headline.{k}.mean.sharpe_ann",
          say="{:.1f}")
        P(f"{tag}_day", R.get(t0, "headline", k, "mean", "pnl_per_day_usd"), t0, f"headline.{k}.mean.pnl_per_day_usd")
        P(f"{tag}_seeds", R.get(t0, "headline", k, "n_seeds"), t0, f"headline.{k}.n_seeds")
    P("t0_be", R.get(t0, "pnl_vs_t_reprice_minus_t_bounce", "IS", "stamp_breakeven_B_s"), t0,
      "pnl_vs_t_reprice_minus_t_bounce.IS.stamp_breakeven_B_s", say="{:.1f}")
    P("t0_calB", R.get(t0, "timing", "calibrated_t_reprice_minus_t_bounce_s (inference)"), t0,
      "timing.calibrated_t_reprice_minus_t_bounce_s (inference)")
    P("t0_preB", R.get(t0, "timing", "pre_registered_primary_median_t_reprice_minus_t_bounce_s"), t0,
      "timing.pre_registered_primary_median_t_reprice_minus_t_bounce_s")
    P("t0_curves", R.get(t0, "pnl_vs_t_reprice_minus_t_bounce"), t0,
      "pnl_vs_t_reprice_minus_t_bounce.{IS,burned_OOS}.{stamp,tournament,point}[B].per_share_c")
    P("t0_mode", R.get(t0, "headline_scenario", "r_mode"), t0, "headline_scenario.r_mode")
    pre, be_ = R.entries["t0_preB"]["value"], R.entries["t0_be"]["value"]
    P("t0_pre_sentence", None if pre is None or be_ is None else
      (f"Our pre-registered estimate, {pre:.2f} seconds, falls in that zone." if pre < be_ else
       f"Our pre-registered estimate, {pre:.2f} seconds, is above it."), t0,
      "timing.pre_registered_primary_median_t_reprice_minus_t_bounce_s vs pnl_vs_t_reprice_minus_t_bounce.IS.stamp_breakeven_B_s",
      say="{}")
    ov = R.entries["t3_overall"]["value"]
    P("t3_sentence", None if ov is None else
      ("A frozen version then failed its blind tests on unseen markets." if str(ov).upper().startswith("FAIL") else
       f"A frozen version was then tested blind on unseen markets: {str(ov).split('(')[0].strip().lower()}."),
      "results/tier0_v3/blind.json", "derived from verdicts['U2 (primary, test b)'].overall", say="{}")

    # S10: live
    lm = "results/engine/live_market_run.json"
    P("live_secs", R.get(lm, "seconds"), lm, "seconds", say="{:.0f}")
    P("live_msgs", R.get(lm, "feed", "msgs"), lm, "feed.msgs", say="{:,}")
    P("live_mkts", R.get(lm, "markets_discovered"), lm, "markets_discovered", say="{}")
    for q in ("p50", "p95", "p99"):
        P(f"live_{q}", R.get(lm, "feed", "latency", f"{q}_ms"), lm, f"feed.latency.{q}_ms", say="{:.0f}")
    P("live_mismatch", R.get(lm, "feed", "snapshots_mismatched"), lm, "feed.snapshots_mismatched")
    P("live_snap", R.get(lm, "feed", "snapshots_checked"), lm, "feed.snapshots_checked")
    P("live_gaps", R.get(lm, "feed", "gaps"), lm, "feed.gaps")
    P("live_orders", R.get(lm, "orders_sent"), lm, "orders_sent")
    P("live_paper", R.get(lm, "paper_only"), lm, "paper_only")
    P("live_when", R.get(lm, "when"), lm, "when")
    ls = "results/live/summary.json"
    st_ = live_state(R.load(ls), ls)
    sm = R.load(ls)
    P("sess_status", st_["status"], ls, "status (+ STOPPED_<run> marker, file age, 1970/empty-counter warm-up guard)")
    P("sess_label", None if sm is None else sm.get("label"), ls, "label")
    P("sess_strategy", None if sm is None else sm.get("strategy"), ls, "strategy")
    P("sess_fills", R.get(ls, "books", "B1", "fills"), ls, "books.B1.fills")
    P("sess_pnl", R.get(ls, "books", "B1", "pnl"), ls, "books.B1.pnl")
    P("sess_state", st_["state"], ls, "derived: pending / warming up / running / stopped / finished / no update")
    P("sess_since", st_["since"], ls, "started_process (UTC)")
    P("sess_asof", st_["asof"], ls, "now, or the file's modification time when now is unset (1970)")
    P("live_sentence", st_["sentence"], ls, "derived from status, started_process, books.B1.fills", say="{}")
    P("engine_video", "results/engine/engine_live_demo.mp4" if valid_mp4("results/engine/engine_live_demo.mp4")
      else None, "results/engine/engine_live_demo.mp4", "file exists and ffprobe reads a duration (not mid-write)")

    # S11: financials, capacity, kill switches
    wf = ("strategies", "v2", "periods")
    for tag, per in (("is", "IS"), ("oos", "OOS")):
        for k in ("gross_edge", "taker_fees", "net_trading"):
            P(f"{tag}_{k}_day", R.get(fn, *wf, per, "waterfall", "usd_per_day", k), fn,
              f"strategies.v2.periods.{per}.waterfall.usd_per_day.{k}")
        P(f"{tag}_fixed_day", R.get(fn, *wf, per, "fixed_costs", "central", "fixed_cost_usd_per_day"), fn,
          f"strategies.v2.periods.{per}.fixed_costs.central.fixed_cost_usd_per_day")
        P(f"{tag}_after_day", R.get(fn, *wf, per, "fixed_costs", "central", "net_after_costs_usd_per_day"), fn,
          f"strategies.v2.periods.{per}.fixed_costs.central.net_after_costs_usd_per_day")
    for a, b in (("gross_day", "is_gross_edge_day"), ("fees_day", "is_taker_fees_day"), ("net_day", "is_net_trading_day"),
                 ("fixed_day", "is_fixed_day"), ("after_day", "is_after_day")):
        e = R.entries[b]
        P(a, None if e["value"] is None else abs(e["value"]), e["file"], e["key"] + " (absolute value)", say="{:.0f}")
    sc = R.get(fn, "strategies", "v2", "scaling") or {}
    sizes = [s for s in ("0.5x", "1x", "2x", "5x") if s in sc]
    P("scaling", {s: {"oos_day": sc[s]["OOS"]["pnl_usd_per_day"], "oos_cap": sc[s]["OOS"]["capital_usd"],
                      "is_day": sc[s]["IS"]["pnl_usd_per_day"]} for s in sizes} or None, fn,
      "strategies.v2.scaling.{0.5x,1x,2x,5x}.{IS,OOS}.{pnl_usd_per_day,capital_usd}")
    pos = [s for s in sizes if sc[s]["OOS"]["pnl_usd_per_day"] > 0]
    P("cap_k", sc[pos[-1]]["OOS"]["capital_usd"] / 1000 if pos else None, fn,
      f"strategies.v2.scaling.{pos[-1] if pos else '?'}.OOS.capital_usd / 1000 (largest size with OOS P&L > 0)",
      say="{:.0f}")
    neg = [s for s in sizes if sc[s]["OOS"]["pnl_usd_per_day"] <= 0]
    P("cap_neg_k", sc[neg[0]]["OOS"]["capital_usd"] / 1000 if neg else None, fn,
      f"strategies.v2.scaling.{neg[0] if neg else '?'}.OOS.capital_usd / 1000 (smallest size with OOS P&L <= 0)",
      say="{:.0f}")
    risk = R.load("docs/RISK.md") or ""
    kills = []
    m = re.search(r"## Daily kill-switch rules.*?\n\n(.*?)(\n\n|\Z)", risk, re.S)
    if m:
        for ln in m.group(1).splitlines()[2:]:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 2:
                trig = re.sub(r"\s*\([^)]*\)", "", cells[0]).split(". ")[0].strip()
                kills.append((trig, cells[1].split(";")[0].strip()))
    want = ("Day P&L", "No market data", "Drawdown", "fee rate")
    kills = [k for w in want for k in kills if w.lower() in k[0].lower()][:4]
    P("kills", kills or None, "docs/RISK.md", "## Daily kill-switch rules (summary): Trigger, Action (first clause)")


# ----------------------------------------------------------------------------------------------------
# narration
# ----------------------------------------------------------------------------------------------------
def parse_script(R: Results):
    text = SCRIPT.read_text()
    scenes = []
    for block in re.split(r"\n(?=## S\d\d )", text)[1:]:
        head = block.splitlines()[0]
        m = re.match(r"## (S\d\d) (\w+) \| (.+)", head)
        sid, key, title = m.group(1), m.group(2), m.group(3).strip()
        R.scene = sid
        lines = []
        for ln in block.splitlines():
            if ln.startswith("> "):
                s = re.sub(r"\{(\w+)\}", lambda mm: R.say(mm.group(1)), ln[2:].strip())
                lines.append(s)
        scenes.append({"id": sid, "key": key, "title": title, "lines": lines})
    return scenes


def tts(text: str) -> np.ndarray:
    WORK.mkdir(parents=True, exist_ok=True)
    say_text = spoken(text)
    h = hashlib.sha1(f"{VOICE}|{RATE}|{say_text}".encode()).hexdigest()[:16]
    aiff = WORK / f"tts_{h}.aiff"
    if not aiff.exists():
        subprocess.run(["say", "-v", VOICE, "-r", str(RATE), "-o", str(aiff), say_text], check=True)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(aiff), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32).copy()
    nz = np.flatnonzero(np.abs(a) > 1e-3)          # trim say's leading/trailing silence
    if len(nz):
        a = a[max(nz[0] - int(0.02 * SR), 0): nz[-1] + int(0.05 * SR)]
    return a


# ----------------------------------------------------------------------------------------------------
# drawing primitives
# ----------------------------------------------------------------------------------------------------
def text(d, xy, s, size, w="regular", fill=INK, anchor="la", spacing=0):
    s = disp(str(s))
    if spacing:
        x, y = xy
        f = F(size, w)
        total = sum(f.getlength(ch) + spacing for ch in s) - spacing
        if anchor[0] == "m":
            x -= total / 2
        elif anchor[0] == "r":
            x -= total
        for ch in s:
            d.text((x, y), ch, font=f, fill=fill, anchor="l" + anchor[1])
            x += f.getlength(ch) + spacing
        return
    d.text(xy, s, font=F(size, w), fill=fill, anchor=anchor)


def wrap(s, size, w, maxw):
    f = F(size, w)
    out, cur = [], ""
    for word in disp(s).split():
        t = (cur + " " + word).strip()
        if f.getlength(t) <= maxw or not cur:
            cur = t
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out


def rrect(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def header(img, sid, kicker, title):
    d = ImageDraw.Draw(img)
    text(d, (MX, 84), f"{int(sid[1:]):02d}  ·  {kicker.upper()}", 22, "demi", BLUE, "lm", spacing=3)
    text(d, (MX, 142), title, 52, "demi", INK, "lm")


def src_note(d, xy, s, anchor="la"):
    """Sources go top-right, level with the kicker, clear of the captions."""
    text(d, (W - MX, 84), "Source: " + s, 16, "regular", DIM, "rm")


class Elem:
    t0 = 0.0
    t_end = 0.0
    live = False      # changes every frame (video)

    def draw(self, img, d, t):
        pass


class Txt(Elem):
    def __init__(self, xy, s, size, w="regular", fill=INK, anchor="la", t0=0.0, fade=0.45, bg=BG, rise=10,
                 maxw=None, lh=1.3, spacing=0):
        self.xy, self.s, self.size, self.w, self.fill, self.anchor = xy, s, size, w, fill, anchor
        self.t0, self.fade, self.bg, self.rise, self.maxw, self.lh, self.spacing = t0, fade, bg, rise, maxw, lh, spacing
        self.t_end = t0 + fade

    def draw(self, img, d, t):
        k = ease((t - self.t0) / self.fade) if self.fade else float(t >= self.t0)
        if k <= 0:
            return
        col = mix(self.fill, self.bg, k)
        x, y = self.xy[0], self.xy[1] + (1 - k) * self.rise
        lines = wrap(self.s, self.size, self.w, self.maxw) if self.maxw else [self.s]
        for i, ln in enumerate(lines):
            text(d, (x, y + i * self.size * self.lh), ln, self.size, self.w, col, self.anchor, self.spacing)


class Num(Elem):
    """Count-up number. fmt(v) -> str."""

    def __init__(self, xy, value, fmt, size, w="demi", fill=INK, anchor="la", t0=0.0, dur=1.3, bg=BG):
        self.xy, self.value, self.fmt, self.size, self.w, self.fill, self.anchor = xy, value, fmt, size, w, fill, anchor
        self.t0, self.dur, self.bg = t0, dur, bg
        self.t_end = t0 + dur

    def draw(self, img, d, t):
        if t < self.t0:
            return
        if self.value is None:
            text(d, self.xy, "pending", self.size, self.w, AMBER, self.anchor)
            return
        k = ease((t - self.t0) / self.dur)
        col = mix(self.fill, self.bg, min(1.0, (t - self.t0) / 0.25))
        text(d, self.xy, self.fmt(self.value * k if k < 1 else self.value), self.size, self.w, col, self.anchor)


class Box(Elem):
    def __init__(self, box, fill=PANEL, r=18, outline=None, width=2, t0=0.0, fade=0.4, bg=BG):
        self.box, self.fill, self.r, self.outline, self.width, self.t0, self.fade, self.bg = \
            box, fill, r, outline, width, t0, fade, bg
        self.t_end = t0 + fade

    def draw(self, img, d, t):
        k = ease((t - self.t0) / self.fade) if self.fade else float(t >= self.t0)
        if k <= 0:
            return
        rrect(d, self.box, self.r, fill=mix(self.fill, self.bg, k) if self.fill else None,
              outline=mix(self.outline, self.bg, k) if self.outline else None, width=self.width)


class Layer(Elem):
    """RGBA layer; mode 'fade', 'wipe' (left to right) or 'grow' (out from a baseline row y0)."""

    def __init__(self, full, xy, t0=0.0, dur=1.0, mode="fade", base=None, y0=None):
        self.full, self.xy, self.t0, self.dur, self.mode, self.base, self.y0 = full, xy, t0, dur, mode, base, y0
        self.t_end = t0 + dur

    def draw(self, img, d, t):
        k = ease((t - self.t0) / self.dur)
        x, y = self.xy
        if self.base is not None and t >= self.t0 - 0.5:
            img.paste(self.base, (x, y), self.base)
        if k <= 0:
            return
        w, h = self.full.size
        if k >= 1:
            img.paste(self.full, (x, y), self.full)
        elif self.mode == "fade":
            lay = self.full.copy()
            lay.putalpha(lay.getchannel("A").point(lambda a: int(a * k)))
            img.paste(lay, (x, y), lay)
        elif self.mode == "wipe":
            cw = max(1, int(w * k))
            crop = self.full.crop((0, 0, cw, h))
            img.paste(crop, (x, y), crop)
        elif self.mode == "grow":
            y0 = self.y0 if self.y0 is not None else h
            top, bot = int(y0 - k * y0), int(y0 + k * (h - y0))
            crop = self.full.crop((0, top, w, max(bot, top + 1)))
            img.paste(crop, (x, y + top), crop)


class Fn(Elem):
    def __init__(self, fn, t_end, live=False):
        self.fn, self.t_end, self.live = fn, t_end, live

    def draw(self, img, d, t):
        self.fn(img, d, t)


class Clip:
    """Sequential frames of one or more videos at FPS, scaled to size; holds the last frame."""

    def __init__(self, paths, size):
        self.paths, self.size = [p for p in paths if Path(p).exists()], size
        self.proc, self.i, self.n, self.last = None, 0, -1, None

    def _open(self):
        if self.i >= len(self.paths):
            return False
        w, h = self.size
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-i", str(self.paths[self.i]), "-vf",
             f"fps={FPS},scale={w}:{h}:flags=lanczos,format=rgb24", "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE)
        return True

    def frame(self, idx):
        w, h = self.size
        while self.n < idx:
            if self.proc is None and not self._open():
                break
            buf = self.proc.stdout.read(w * h * 3)
            if len(buf) < w * h * 3:
                self.proc.wait()
                self.proc = None
                self.i += 1
                continue
            self.last = Image.frombytes("RGB", (w, h), buf)
            self.n += 1
        if self.last is None:
            self.last = Image.new("RGB", (w, h), rgb(PANEL))
        return self.last

    def close(self):
        if self.proc:
            self.proc.kill()


class VideoEl(Elem):
    live = True

    def __init__(self, clip, xy, t0=0.0):
        self.clip, self.xy, self.t0 = clip, xy, t0

    def draw(self, img, d, t):
        img.paste(self.clip.frame(max(0, int((t - self.t0) * FPS))), self.xy)


# ----------------------------------------------------------------------------------------------------
# matplotlib charts -> (axes-only layer, full layer)
# ----------------------------------------------------------------------------------------------------
_MPL = False


def mpl_setup():
    global _MPL
    if _MPL:
        return
    try:
        font_manager.fontManager.addfont(AV)
        plt.rcParams["font.family"] = "Avenir Next"
    except Exception:
        plt.rcParams["font.family"] = "DejaVu Sans"
    plt.rcParams.update({"text.color": MUTED, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.edgecolor": GRID, "font.size": 15, "axes.unicode_minus": True})
    _MPL = True


def mpl_chart(w, h, plot, rect=(0.08, 0.12, 0.9, 0.84)):
    """plot(ax) -> list of data artists. Returns (axes layer, full layer, ax-to-pixel transform)."""
    mpl_setup()
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    fig.patch.set_alpha(0)
    ax = fig.add_axes(rect)
    ax.set_facecolor("none")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(length=0, labelsize=15, pad=8)
    ax.grid(axis="y", color=GRID, lw=1)
    ax.set_axisbelow(True)
    arts = plot(ax)

    def grab():
        fig.canvas.draw()
        return Image.frombuffer("RGBA", fig.canvas.get_width_height(), bytes(fig.canvas.buffer_rgba())).copy()
    for a in arts:
        a.set_visible(False)
    axes_only = grab()
    for a in arts:
        a.set_visible(True)
    full = grab()

    def to_px(x, y):
        X, Y = ax.transData.transform((x, y))
        return X, h - Y
    plt.close(fig)
    return axes_only, full, to_px


# ----------------------------------------------------------------------------------------------------
# scenes
# ----------------------------------------------------------------------------------------------------
class Scene:
    def __init__(self, meta):
        self.id, self.key, self.title = meta["id"], meta["key"], meta["title"]
        self.lines = meta["lines"]
        self.els: list[Elem] = []
        self.bg = Image.new("RGB", (W, H), rgb(BG))
        self.clips: list[Clip] = []
        self.dur = 10.0
        self._cache = None

    def kicker(self):
        return KICKERS.get(self.key, self.key)

    def head(self):
        header(self.bg, self.id, self.kicker(), self.title)

    def static_after(self):
        if any(e.live for e in self.els):
            return math.inf
        return max([e.t_end for e in self.els] + [0.0])

    def render(self, t):
        t = min(max(t, 0.0), self.dur)
        sa = self.static_after()
        if t >= sa and self._cache is not None:
            return self._cache
        img = self.bg.copy()
        d = ImageDraw.Draw(img)
        for e in self.els:
            e.draw(img, d, t)
        if t >= sa:
            self._cache = img
        return img

    def close(self):
        for c in self.clips:
            c.close()


def fmt_c(v, d=2, sign=True):
    return (f"{v:+.{d}f}" if sign else f"{v:.{d}f}") + "¢"


def usd(v, d=0, sign=False):
    s = f"{abs(v):,.{d}f}"
    return ("-" if v < 0 else ("+" if sign and v > 0 else "")) + "$" + s


def ci_txt(lo, hi, d=2):
    if lo is None or hi is None:
        return "CI pending"
    return f"[{lo:+.{d}f}, {hi:+.{d}f}]"


def build_scene(meta, R: Results) -> Scene:
    S = Scene(meta)
    R.scene = S.id
    getattr(sys.modules[__name__], "scene_" + S.key)(S, R)
    return S


def scene_hook(S, R):
    vw, vh = 1440, 810                     # leaves room for the credit and the call note above the captions
    x0, y0 = (W - vw) // 2, 30
    clip = Clip(["results/tracking/demo/01_miss_test_2_f2819_lead408ms.mp4",
                 "results/tracking/demo/02_miss_test_4_f5750_lead83ms.mp4"], (vw, vh))
    S.clips.append(clip)
    S.els.append(VideoEl(clip, (x0, y0)))
    R["clip0_lead_ms"], R["clip0_pmiss"], R["clip1_lead_ms"], R["clip1_pmiss"]   # embedded in the clips' overlays

    def title(img, d, t):
        k = 1.0 if t < 2.4 else max(0.0, 1 - (t - 2.4) / 0.6)
        if k <= 0:
            return
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        od.rectangle((0, 0, W, H), fill=rgb(BG) + (int(150 * k),))
        a = int(255 * k)
        od.text((W / 2, 430), "COURTSIDE", font=F(120, "bold"), fill=rgb(INK) + (a,), anchor="mm")
        od.text((W / 2, 545), "Call the point before the ball lands.", font=F(46, "medium"),
                fill=rgb(INK) + (a,), anchor="mm")
        od.text((W / 2, 615), "Gator Quant Hacks 2026  ·  Systematic Trading", font=F(26, "medium"),
                fill=rgb(BLUE) + (a,), anchor="mm")
        img.paste(ov, (0, 0), ov)
    S.els.append(Fn(title, 3.0, live=True))
    d = ImageDraw.Draw(S.bg)
    longest = "our longest call on held-out games" if R["hook_is_longest"] else "one held-out call"
    if R.pending("lead_med_ms"):
        note = f"First clip: {longest}."
    else:
        note = (f"First clip: {longest}. Median lead {R['lead_med_ms']:.0f} ms (p90 {R['lead_p90_ms']:.0f} ms); "
                f"{R['lead_n_called']} of {R['lead_n_miss']} test misses called early.")
    text(d, (x0, y0 + vh + 12), note, 19, "demi", AMBER)
    text(d, (x0, y0 + vh + 40), "MISS CALLED latches at the first crossing; P(miss) is per frame.", 17, "regular",
         MUTED)
    text(d, (x0 + vw, y0 + vh + 12), "real held-out test game", 18, "regular", MUTED, "ra")
    text(d, (x0 + vw, y0 + vh + 40), CREDIT, 17, "regular", MUTED, "ra")


def scene_economics(S, R):
    S.head()
    vis = "pending" if R.pending("vis_ms") else f"~{R['vis_ms']:.0f} ms"
    he = "pending" if R.pending("he100_cm") else f"±{R['he100_cm']:.1f} cm"
    tiers = [
        ("TIER 0", "Ball tracking", "before the bounce",
         f"{he} at 100 ms (simulated); our vision {vis}/call (laptop, no courtside camera)", CORAL),
        ("TIER 1", "Chair umpire", "at the bounce", "", GREY),
        ("TIER 2", "Market makers", f"{R['book_vs_stamp_s']:+.2f} s",
         "the book reprices, vs the official point stamp (median)", BLUE),
        ("TIER 3", "Official feed", f"≈{R['stamp_lag_s']:.1f} s",
         "umpire-entered point stamp; lag after the bounce inferred, not measured", "#3f6e9c"),
        ("TIER 4", "TV and public scores", f"+{R['espn_s']:.1f} s",
         f"ESPN vs the book (measured); book first on {R['h4_share']:.0f}% of {R['h4_n']} points, "
         f"median {R['h4_s']:.1f} s", GREY),
        ("TIER 5", "Streams", f"+{R['stream_lo']:.0f}–{R['stream_hi']:.0f} s", "the slowest money; assumed, not measured",
         DIM),
    ]
    y = 236
    for i, (tag, name, val, sub, col) in enumerate(tiers):
        t0 = 0.4 + i * 0.45
        yy = y + i * 102
        indent = i * 34
        S.els += [Box((MX + indent, yy, 1140, yy + 90), PANEL, 14, t0=t0),
                  Box((MX + indent, yy, MX + indent + 8, yy + 90), col, 3, t0=t0),
                  Txt((MX + indent + 30, yy + 18), tag, 17, "demi", col, t0=t0, bg=PANEL, spacing=2),
                  Txt((MX + indent + 130, yy + 12), name, 30, "demi", INK, t0=t0, bg=PANEL)]
        if sub:
            S.els.append(Txt((MX + indent + 130, yy + 54), sub, 18, "regular", MUTED, t0=t0, bg=PANEL))
        S.els.append(Txt((1112, yy + 14), val, 30, "demi", col if col not in (GREY, DIM) else INK, "ra", t0=t0 + 0.2,
                         bg=PANEL))
    R["vis_p90_ms"]
    # right column: who is on the other side, why it persists
    cx = 1210
    S.els += [Box((cx, 236, W - MX, 526), PANEL2, 18, t0=3.4),
              Txt((cx + 36, 268), "WHO IS ON THE OTHER SIDE", 18, "demi", AMBER, t0=3.5, bg=PANEL2, spacing=2),
              Txt((cx + 36, 312), "Slow takers: traders reacting to TV, streams and score apps, and resting quotes "
                  "not pulled in time. They trade against prices the fast tier already knows are stale.",
                  24, "regular", INK, t0=3.6, bg=PANEL2, maxw=W - MX - cx - 72),
              Box((cx, 552, W - MX, 856), PANEL2, 18, t0=4.4),
              Txt((cx + 36, 584), "WHY IT PERSISTS", 18, "demi", AMBER, t0=4.5, bg=PANEL2, spacing=2),
              Txt((cx + 36, 628), f"Speed costs money: a licensed feed (central {usd(R['feed_month'])}/month, our "
                  f"assumption) and a London gateway ({usd(R['vps_month'])}/month). The pool is small: our book "
                  f"trades {usd(R['notional_day'])}/day.", 24, "regular", INK, t0=4.6, bg=PANEL2,
                  maxw=W - MX - cx - 72)]
    d = ImageDraw.Draw(S.bg)
    src_note(d, (MX, 860), "results/summary.json (h4, tracking_tennis_physics); results/tier0/results.json (timing); "
             "results/decay/decay.json; results/engine/demo_run.json (latency_budget)")


def scene_evidence(S, R):
    S.head()
    rows = R["ft_rows"]
    months = [r["month"] for r in rows]
    oos = [r["period"] == "OOS" for r in rows]
    a = [float(r["net30_c"]) for r in rows]
    b = [float(r["others_net30_c"]) for r in rows]
    c = [float(r["follow_res_c"]) for r in rows]
    import datetime as _dt
    labels = [_dt.date(int(m[:4]), int(m[5:]), 1).strftime("%b\n%Y" if m.endswith("-01") or i == 0 else "%b")
              for i, m in enumerate(months)]
    n_is = len(rows) - sum(oos)

    def pale(col):
        return "#" + "".join(f"{v:02x}" for v in mix(col, BG, 0.45))

    def plot(ax):
        x = np.arange(len(months))
        bw = 0.27
        arts = []
        for off, vals, col in ((-bw, a, BLUE), (0, b, GREY), (bw, c, CORAL)):
            arts += list(ax.bar(x + off, vals, bw * 0.92, color=[pale(col) if o else col for o in oos]))
        ax.axhline(0, color=MUTED, lw=1.2)
        ax.axvline(n_is - 0.5, color=MUTED, lw=1, ls=(0, (4, 4)))
        ax.set_xticks(x, labels)
        ax.set_ylabel("cents per share, net of fees", fontsize=15)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: disp(f"{v:+.0f}¢") if v else "0"))
        lim = max(map(abs, a + b + c)) * 1.15
        ax.set_ylim(-lim, lim)
        return arts
    w, h = 1680, 540
    ax_l, full, to_px = mpl_chart(w, h, plot, rect=(0.07, 0.13, 0.92, 0.84))
    y0 = to_px(0, 0)[1]
    S.els.append(Layer(full, (MX, 300), t0=0.6, dur=1.6, mode="grow", base=ax_l, y0=y0))
    xd = MX + to_px(n_is - 0.5, 0)[0]
    S.els += [Txt((xd - 12, 304), "in sample (walk-forward)", 18, "demi", BLUE, "ra", t0=1.2),
              Txt((xd + 12, 304), "out of sample (faded)", 18, "demi", CYAN, "la", t0=1.4)]
    lx = MX + 120
    for i, (col, lab) in enumerate([(BLUE, "fast-tier wallets, first 3 s after a point (marked 30 s later)"),
                                    (GREY, "everyone else (marked 30 s later)"),
                                    (CORAL, "copying the fast tier 3 s later (held to resolution)")]):
        S.els += [Box((lx, 248, lx + 18, 266), col, 3, t0=0.3 + 0.15 * i)]
        S.els += [Txt((lx + 28, 246), lab, 19, "regular", MUTED, t0=0.3 + 0.15 * i)]
        lx += 28 + F(19).getlength(lab) + 40
    # chips
    S.els += [Box((1110, 104, 1470, 176), PANEL2, 16, t0=2.2), Box((1490, 104, W - MX, 176), PANEL2, 16, t0=2.5),
              Num((1290, 140), R["ft_pos"], lambda v, n=R["ft_n"]: f"up {v:.0f}/{n} months", 28, "demi", BLUE, "mm",
                  t0=2.3, dur=0.9, bg=PANEL2),
              Num((1490 + (W - MX - 1490) / 2, 140), R["fol_neg"], lambda v, n=R["ft_n"]: f"copy: down {v:.0f}/{n}", 28,
                  "demi", CORAL, "mm", t0=2.6, dur=0.9, bg=PANEL2)]
    R["oth_neg"], R["ft_wallets_last"], R["ft_pos_oos"], R["ft_n_oos"]
    d = ImageDraw.Draw(S.bg)
    src_note(d, (MX, 860), f"results/summary.json (is/oos h6_walkforward; {months[0]} to {months[-1]}, "
             f"{n_is} in-sample + {sum(oos)} out-of-sample months; wallets picked from earlier months only)")


def scene_vision(S, R):
    S.head()
    vw, vh = 1152, 648
    clip = Clip(["results/tracking/demo/03_miss_test_6_f1484_lead25ms.mp4",
                 "results/tracking/demo/04_bounce_test_6_f1299_at50ms.mp4"], (vw, vh))
    S.clips.append(clip)
    S.els.append(VideoEl(clip, (MX, 222)))
    R["clip2_lead_ms"], R["clip2_pmiss"], R["clip3_lead_ms"], R["clip3_pmiss"]
    d = ImageDraw.Draw(S.bg)
    text(d, (MX, 222 + vh + 12), "Held-out test games  ·  " + CREDIT, 18, "regular", MUTED)
    px = MX + vw + 48
    pw = W - MX - px
    S.els += [Box((px, 222, W - MX, 222 + vh), PANEL, 18, t0=0.2)]
    S.els += [Txt((px + 36, 254), "MISS CALLS 50 MS BEFORE CONTACT", 18, "demi", MUTED, t0=0.3, bg=PANEL, spacing=2),
              Num((px + 36, 290), R["tp50"], lambda v, n=R["tp50"] + R["fp50"]: f"{v:.0f} / {n}", 96, "bold", INK,
                  t0=0.6, bg=PANEL),
              Txt((px + 36, 408), "correct on held-out test games", 22, "regular", MUTED, t0=0.8, bg=PANEL),
              Txt((px + 36, 460), "95% lower bound on precision", 22, "regular", MUTED, t0=1.2, bg=PANEL),
              Num((pw + px - 36, 452), R["wil50"], lambda v: f"{v:.0f}%", 36, "demi", BLUE, "ra", t0=1.2, bg=PANEL),
              Txt((px + 36, 512), "Recall at 50 ms", 22, "regular", MUTED, t0=1.6, bg=PANEL),
              Num((pw + px - 36, 504), R["recall50"], lambda v: f"{v:.0f}%", 36, "demi", INK, "ra", t0=1.6, bg=PANEL),
              Box((px + 36, 572, W - MX - 36, 574), GRID, 0, t0=2.0, bg=PANEL),
              Txt((px + 36, 596), f"BALL DETECTION, {R['det_n']:,} TEST FRAMES", 18, "demi", MUTED, t0=2.0, bg=PANEL,
                  spacing=2),
              Txt((px + 36, 636), "ball found", 22, "regular", MUTED, t0=2.2, bg=PANEL),
              Num((pw + px - 36, 628), R["det_recall"], lambda v: f"{v:.1f}%", 32, "demi", INK, "ra", t0=2.2, bg=PANEL),
              Txt((px + 36, 684), "within 5 px of the label", 22, "regular", MUTED, t0=2.4, bg=PANEL),
              Num((pw + px - 36, 676), R["det_w5"], lambda v: f"{v:.1f}%", 32, "demi", INK, "ra", t0=2.4, bg=PANEL),
              Txt((px + 36, 748), f"Test flights: {R['n_test_miss']} misses, {R['n_test_bounce']} bounces. "
                  f"Pre-registered rule: precision ≥ 95% at 50 ms. Verdict: {R['verdict_h3']} on the point "
                  f"estimate (n = {R['n50']}).", 19, "regular", MUTED, t0=2.6, bg=PANEL, maxw=pw - 72)]
    R["prec50"]
    src_note(d, (MX, 902), "results/tracking/summary.json (early_call.precision_recall_test_snapshot.50ms, "
             "detection_accuracy_pooled)")


def scene_tennis(S, R):
    S.head()
    vw, vh = 1120, 630
    vy = 236
    clip = Clip(["results/viz/courtside_replay.mp4"], (vw, vh))
    S.clips.append(clip)
    S.els.append(VideoEl(clip, (MX, vy)))
    R["tennis_out_cm"]
    split = MX + int(vw * 820 / 1280)        # the replay's own split between the court and the tape
    d = ImageDraw.Draw(S.bg)
    rrect(d, (MX, 186, split - 12, 226), 10, fill=rgb(AMBER))
    text(d, ((MX + split - 12) / 2, 206), "SIMULATED PHYSICS", 22, "bold", BG, "mm", spacing=2)
    rrect(d, (split, 186, MX + vw, 226), 10, fill=rgb(BLUE))
    text(d, ((split + MX + vw) / 2, 206), "REAL POLYMARKET TAPE", 20, "bold", INK, "mm", spacing=1)
    text(d, (MX, vy + vh + 12), f"Left: simulated {R['tennis_fps']:.0f} fps tracking (no licensed tennis footage). "
         f"Right: real tape, {R['tape_title']}, {R['tape_date']}.", 18, "regular", MUTED)
    px = MX + vw + 48
    pw = W - MX - px
    S.els += [Box((px, 222, W - MX, 222 + vh), PANEL, 18, t0=0.2),
              Txt((px + 36, 254), "OUT CALL, SIMULATED TENNIS", 18, "demi", AMBER, t0=0.3, bg=PANEL, spacing=2),
              Num((px + 36, 290), R["tennis_lead_ms"], lambda v: f"{v:.0f} ms", 84, "bold", INK, t0=0.6, bg=PANEL),
              Txt((px + 36, 398), "before the bounce, at P(out) ≥ 0.95", 22, "regular", MUTED, t0=0.8, bg=PANEL),
              Box((px + 36, 460, W - MX - 36, 462), GRID, 0, t0=1.4, bg=PANEL),
              Txt((px + 36, 484), "SPIN READOUT (SIMULATION)", 18, "demi", AMBER, t0=1.4, bg=PANEL, spacing=2),
              Txt((px + 36, 526), "median spin error, 100 ms before bounce", 22, "regular", MUTED, t0=1.6, bg=PANEL),
              Txt((px + 36, 572), "batch physics fit", 22, "regular", INK, t0=1.8, bg=PANEL),
              Num((pw + px - 36, 566), R["spin_bls_rpm"], lambda v: f"{v:.1f} rpm", 30, "demi", BLUE, "ra", t0=1.8,
                  bg=PANEL),
              Txt((px + 36, 620), "baseline curve fit", 22, "regular", INK, t0=2.0, bg=PANEL),
              Num((pw + px - 36, 614), R["spin_base_rpm"], lambda v: f"{v:,.0f} rpm", 30, "demi", MUTED, "ra",
                  t0=2.0, bg=PANEL),
              Txt((px + 36, 680), "In simulation only: the filter's physics matches the simulator's. "
                  "Not measured on real tennis.", 19, "regular", MUTED, t0=2.3, bg=PANEL, maxw=pw - 72)]
    R["spin_bls_axis"]
    src_note(d, (MX, 902), "results/viz/viz_data.json (shot.preds); results/spin/tennis/metrics_v2.csv")


def scene_backtest(S, R):
    S.head()
    eis, eoos = R["eq_is"], R["eq_oos"]
    vals = np.cumsum([v for _, v in eis] + [v for _, v in eoos])
    n_is = len(eis)
    dates = [d for d, _ in eis] + [d for d, _ in eoos]

    def plot(ax):
        x = np.arange(len(vals))
        l1, = ax.plot(x[:n_is], vals[:n_is], color=BLUE, lw=3)
        l2, = ax.plot(x[n_is - 1:], vals[n_is - 1:], color=CYAN, lw=3)
        f1 = ax.fill_between(x[:n_is], 0, vals[:n_is], color=BLUE, alpha=0.12, lw=0)
        f2 = ax.fill_between(x[n_is - 1:], 0, vals[n_is - 1:], color=CYAN, alpha=0.12, lw=0)
        ax.axvline(n_is - 0.5, color=MUTED, lw=1, ls=(0, (4, 4)))
        ticks = [i for i, d in enumerate(dates) if d.endswith("-01")]
        import datetime as _dt
        ax.set_xticks(ticks, [_dt.date.fromisoformat(dates[i]).strftime("%b") for i in ticks])
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v / 1000:.0f}k"))
        ax.set_ylabel("cumulative P&L, paper", fontsize=15)
        ax.set_xlim(0, len(vals) - 1)
        ax.set_ylim(min(0, vals.min()) - 1000, vals.max() * 1.2)
        return [l1, l2, f1, f2]
    w, h = 990, 520
    ax_l, full, to_px = mpl_chart(w, h, plot, rect=(0.11, 0.1, 0.87, 0.86))
    S.els.append(Layer(full, (MX - 20, 250), t0=0.5, dur=2.6, mode="wipe", base=ax_l))
    xd = to_px(n_is - 0.5, 0)[0] + MX - 20
    xr = to_px(len(vals) - 1, 0)[0] + MX - 20
    S.els += [Txt((xd - 14, 262), f"in sample  ·  {R['is_days']} days", 19, "demi", BLUE, "ra", t0=0.6),
              Txt((xr, 292), f"out of sample (burned)  ·  {R['oos_days']} days", 19, "demi", CYAN, "ra",
                  t0=2.6)]
    # money counters
    cx, cw = 1130, W - MX - 1130
    for j, (tag, col, lab, t0) in enumerate((("is", BLUE, "IN SAMPLE  ·  FEB–AUG", 0.8),
                                             ("oos", CYAN, "OUT OF SAMPLE  ·  BURNED, NON-BLIND", 2.6))):
        y = 240 + j * 280
        cap, pnl = R[f"{tag}_cap"], R[f"{tag}_pnl"]
        S.els += [Box((cx, y, W - MX, y + 262), PANEL, 18, t0=t0 - 0.2),
                  Txt((cx + 30, y + 24), lab, 17, "demi", col, t0=t0, bg=PANEL, spacing=2),
                  Txt((cx + 30, y + 62), "capital (3× peak locked)", 19, "regular", MUTED, t0=t0, bg=PANEL),
                  Num((cx + 30, y + 88), cap, lambda v: usd(v), 38, "demi", INK, t0=t0, bg=PANEL),
                  Txt((cx + cw - 30, y + 62), "end value (paper)", 19, "regular", MUTED, "ra", t0=t0, bg=PANEL),
                  Num((cx + cw - 30, y + 88), cap + pnl, lambda v: usd(v), 38, "demi", col, "ra", t0=t0, dur=2.0,
                      bg=PANEL)]
        stats = [("per share", R[f"{tag}_c"], lambda v: fmt_c(v)),
                 ("Sharpe", R[f"{tag}_sh"], lambda v: f"{v:.1f}"),
                 ("max DD", R[f"{tag}_dd"], lambda v: f"{v:.1f}%"),
                 ("win rate", R[f"{tag}_win"], lambda v: f"{v:.1f}%")]
        for i, (lab2, v, f) in enumerate(stats):
            sx = cx + 30 + i * (cw - 60) / 4
            S.els += [Txt((sx, y + 160), lab2, 18, "regular", MUTED, t0=t0 + 0.3, bg=PANEL),
                      Num((sx, y + 186), v, f, 32, "demi", INK, t0=t0 + 0.3, bg=PANEL)]
        S.els += [Txt((cx + 30, y + 228), f"95% CI per share {ci_txt(R[f'{tag}_lo'], R[f'{tag}_hi'])}¢  ·  "
                      f"win rate [{R[f'{tag}_win_lo']:.1f}, {R[f'{tag}_win_hi']:.1f}]%  ·  "
                      f"{R[f'{tag}_trades']:,} trades", 17, "regular", MUTED, t0=t0 + 0.6, bg=PANEL)]
    R["is_mpos"], R["is_mtot"]
    # stress strip
    y = 800
    S.els += [Box((MX, y, W - MX, y + 70), PANEL2, 14, t0=3.6),
              Txt((MX + 30, y + 22), "FEES ×2", 18, "demi", CORAL, t0=3.7, bg=PANEL2, spacing=2),
              Txt((MX + 170, y + 18), f"in sample {fmt_c(R['is_fee2_c'])}   ·   out of sample "
                  f"{fmt_c(R['oos_fee2_c'])} {ci_txt(R['oos_fee2_lo'], R['oos_fee2_hi'])}, negative   ·   "
                  f"all costs ×2: in sample {fmt_c(R['is_cost2_c'])}, out of sample {fmt_c(R['oos_cost2_c'])}",
                  24, "demi", INK, t0=3.8, bg=PANEL2)]
    d = ImageDraw.Draw(S.bg)
    src_note(d, (MX, 884), "results/v2/causal.json, results/v2/cost_stress.json, results/lowloss/daily.csv, "
             "results/financials/financials.json (unit_economics). Paper P&L only.")


def scene_overfitting(S, R):
    S.head()
    groups = [("v2 in sample", "v2_is"), ("v2 out of sample", "v2_oos"), ("unseen markets,\nblind OOS", "v2_u2oos_blind")]
    v44 = [R[f"dsr_{s}_N44"] for _, s in groups]
    v33 = [R[f"dsr_{s}_N3410"] for _, s in groups]
    nt, ns = R["n_trials"], R["n_trials_small"]

    def plot(ax):
        x = np.arange(len(groups))
        bw = 0.34
        b1 = ax.bar(x - bw / 2, v44, bw * 0.9, color="#9fb4c8")
        b2 = ax.bar(x + bw / 2, v33, bw * 0.9, color=BLUE)
        ax.axhline(0.95, color=AMBER, lw=1.6, ls=(0, (5, 4)))
        ax.text(len(groups) - 0.5, 0.965, "0.95", color=AMBER, ha="right", va="bottom", fontsize=15)
        ax.set_xticks(x, [g for g, _ in groups])
        ax.set_ylim(0, 1.08)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.set_ylabel("deflated Sharpe ratio (probability)", fontsize=15)
        labs = []
        for bars, vv in ((b1, v44), (b2, v33)):
            for b, v in zip(bars, vv):
                labs.append(ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.3f}",
                                    ha="center", va="bottom", color=INK, fontsize=16, fontweight="demibold"))
        return list(b1) + list(b2) + labs
    w, h = 1060, 540
    ax_l, full, to_px = mpl_chart(w, h, plot, rect=(0.1, 0.13, 0.88, 0.83))
    S.els.append(Layer(full, (MX - 20, 290), t0=0.6, dur=1.6, mode="grow", base=ax_l, y0=to_px(0, 0)[1]))
    lx = MX + 90
    for col, lab in (("#9fb4c8", f"deflated for {ns} pre-registered trials"), (BLUE, f"deflated for all {nt:,} trials")):
        S.els += [Box((lx, 250, lx + 18, 268), col, 3, t0=0.3), Txt((lx + 28, 247), lab, 19, "regular", MUTED, t0=0.3)]
        lx += 28 + F(19).getlength(disp(lab)) + 40
    # PBO meters
    cx = 1190
    S.els += [Box((cx, 250, W - MX, 850), PANEL, 18, t0=1.6),
              Txt((cx + 32, 280), "PROBABILITY OF BACKTEST OVERFITTING", 17, "demi", AMBER, t0=1.7, bg=PANEL, spacing=2),
              Txt((cx + 32, 312), f"CSCV, {R['cscv_blocks']} blocks, all {R['cscv_splits']:,} splits", 19, "regular",
                  MUTED, t0=1.7, bg=PANEL)]
    mw = W - MX - cx - 64
    for i, (lab, val) in enumerate(((f"{R['pbo24_n']}-variant grid, picked by Sharpe", R["pbo24"]),
                                    (f"{R['pbo24_n']}-variant grid, picked by our rule", R["pbo24_sel"]),
                                    (f"sizing grid, {R['pbo55_n']} variants", R["pbo55"]))):
        y = 366 + i * 108
        S.els += [Txt((cx + 32, y), lab, 22, "regular", INK, t0=1.9 + 0.3 * i, bg=PANEL),
                  Num((W - MX - 32, y - 6), val, lambda v: f"{v:.0f}%", 40, "demi", BLUE, "ra", t0=1.9 + 0.3 * i,
                      bg=PANEL)]

        def meter(img, d, t, y=y, val=val, t0=1.9 + 0.3 * i):
            k = ease((t - t0) / 1.3)
            if t < t0:
                return
            rrect(d, (cx + 32, y + 56, cx + 32 + mw, y + 72), 8, fill=rgb(GRID))
            if val:
                rrect(d, (cx + 32, y + 56, cx + 32 + max(16, mw * val / 100 * k), y + 72), 8, fill=rgb(BLUE))
        S.els.append(Fn(meter, 1.9 + 0.3 * i + 1.3))
    S.els += [Box((cx + 32, 708, W - MX - 32, 710), GRID, 0, t0=2.6, bg=PANEL),
              Txt((cx + 32, 730), "STATIONARY BOOTSTRAP, P(SHARPE ≤ 0)", 17, "demi", MUTED, t0=2.7, bg=PANEL,
                  spacing=2),
              Txt((cx + 32, 766), f"in sample {R['boot_is_p']:.4f}   ·   out of sample {R['boot_oos_p']:.4f}", 24,
                  "demi", INK, t0=2.8, bg=PANEL)]
    d = ImageDraw.Draw(S.bg)
    src_note(d, (MX, 860), "results/rigor/rigor.json (psr_dsr.rows dsr_min_N44 / dsr_min_N3410, pbo_cscv, bootstrap); "
             "lowest DSR across the variance sources")


def scene_scoreboard(S, R):
    S.head()

    def chip_for(label):
        lab = str(label).upper()
        if lab.startswith("FAIL"):
            return "FAIL", CORAL
        if lab.startswith("PASS"):
            return "PASS", GREEN
        return lab, GREY

    def sign_chip(v):
        return ("POSITIVE", BLUE) if v is not None and v > 0 else ("NEGATIVE", CORAL)
    tt2 = str(R["tt2_verdict"] or "pending")
    rows = [
        ("v2, in sample", "in sample", f"{fmt_c(R['is_c'])} {ci_txt(R['is_lo'], R['is_hi'])}", sign_chip(R["is_c"])),
        ("v2, out of sample", "burned (seen before), not blind",
         f"{fmt_c(R['oos_c'])} {ci_txt(R['oos_lo'], R['oos_hi'])}", sign_chip(R["oos_c"])),
        ("v2, fees doubled", "stress, out of sample",
         f"{fmt_c(R['oos_fee2_c'])} {ci_txt(R['oos_fee2_lo'], R['oos_fee2_hi'])}", sign_chip(R["oos_fee2_c"])),
        ("v2, all costs doubled", "stress, out of sample", f"{fmt_c(R['oos_cost2_c'])}", sign_chip(R["oos_cost2_c"])),
        ("Unseen markets (U2)", "blind, in sample", f"{fmt_c(R['u2_is_c'])} {ci_txt(R['u2_is_lo'], R['u2_is_hi'])}",
         chip_for(R["u2_is_label"])),
        ("Unseen markets (U2)", "blind, out of sample",
         f"{fmt_c(R['u2_oos_c'])} {ci_txt(R['u2_oos_lo'], R['u2_oos_hi'])}", chip_for(R["u2_oos_label"])),
        ("v1, copy the fast tier", "held-out window, opened once, blind",
         f"{usd(R['v1_usd'] / 1000, 1)}k, max DD {R['v1_dd'] * 100:.0f}%" if not R.pending("v1_usd") else "pending",
         ("FAIL", CORAL) if (R["v1_usd"] or 0) < 0 else ("PASS", GREEN)),
        ("Maker v1", "pre-registered, blind out of sample",
         f"{fmt_c(R['mk_c'])} {ci_txt(R['mk_lo'], R['mk_hi'])}  ·  {usd(R['mk_usd'])}", chip_for(R["mk_verdict"])),
        ("Tier-0 v3, frozen*", "blind, unseen markets: IS / OOS period",
         "pending" if R.pending("t3_u2is_c") else f"{fmt_c(R['t3_u2is_c'])} / {fmt_c(R['t3_u2oos_c'])}",
         ("PENDING", AMBER) if R.pending("t3_overall") else chip_for(R["t3_overall"])),
        ("Tier-0 v3, frozen*", "burned out of sample, not blind",
         "pending" if R.pending("t3_boos_c") else f"{fmt_c(R['t3_boos_c'])} {ci_txt(R['t3_boos_lo'], R['t3_boos_hi'])}",
         ("PENDING", AMBER) if R.pending("t3_boos_verdict") else chip_for(R["t3_boos_verdict"])),
        ("Table tennis markets", "pre-registered TT1–TT3",
         "; ".join(v.split("(")[-1].rstrip(")") for v in (tt2, str(R["tt3_verdict"] or "")) if "(" in v) or tt2,
         chip_for(tt2)),
        ("v2, blind forward test", "frozen rule, unseen days",
         (f"runs once, {R['fwd_when']}" if R["fwd_when"] else "not run yet") if R["fwd_verdict"] is None
         else str(R["fwd_verdict"]),
         ("PENDING", AMBER) if R["fwd_verdict"] is None else chip_for(R["fwd_verdict"])),
    ]
    R["tt3_verdict"], R["t3_u2is_verdict"], R["t3_u2oos_verdict"], R["t3_boos_verdict"]
    y0, rh = 238, 52
    S.els.append(Txt((MX, 186), "* Tier-0 rows: " + TIER0_LABEL, 17, "demi", AMBER, t0=0.0, fade=0.0))
    d = ImageDraw.Draw(S.bg)
    for j, (lab, x) in enumerate((("TEST", MX + 24), ("KIND", MX + 470), ("RESULT, ¢/SHARE [95% CI]", MX + 960))):
        text(d, (x, y0 - 6), lab, 16, "demi", DIM, "ls", spacing=2)
    text(d, (W - MX - 24, y0 - 6), "VERDICT", 16, "demi", DIM, "rs", spacing=2)
    for i, (name, kind, res, (chip, col)) in enumerate(rows):
        y = y0 + 12 + i * rh
        t0 = 0.4 + i * 0.24
        bgc = PANEL if i % 2 == 0 else PANEL2
        S.els += [Box((MX, y, W - MX, y + rh - 7), bgc, 12, t0=t0),
                  Txt((MX + 24, y + 9), name, 22, "demi", INK, t0=t0, bg=bgc),
                  Txt((MX + 470, y + 11), kind, 19, "regular", MUTED, t0=t0, bg=bgc),
                  Txt((MX + 960, y + 9), res, 22, "demi", INK, t0=t0, bg=bgc),
                  Box((W - MX - 210, y + 6, W - MX - 20, y + rh - 13), col, 10, t0=t0 + 0.15, bg=bgc),
                  Txt((W - MX - 115, y + (rh - 7) / 2), chip, 17, "bold", BG if col != CORAL else INK, "mm",
                      t0=t0 + 0.15, bg=col, rise=0, spacing=1)]
    yb = y0 + 12 + len(rows) * rh + 4
    S.els += [Txt((MX, yb), f"Every look at out-of-sample data is logged: {R['peeks']} entries in "
                  f"results/oos_peeks.log at render time.", 21, "demi", AMBER, t0=0.4 + len(rows) * 0.24)]
    src_note(d, (W - MX, yb + 6), "results/v2/causal.json, cost_stress.json, expand/results.json, maker/oos.json, "
             "summary.json (v1), tier0_v3/blind.json, tt/results.json, v2/forward.json", anchor="ra")


def scene_tier0(S, R):
    S.head()
    S.els += [Box((MX, 196, W - MX, 252), None, 12, outline=AMBER, width=3, t0=0.0, fade=0.0),
              Txt((W / 2, 224), TIER0_LABEL.upper(), 21, "demi", AMBER, "mm", t0=0.0, fade=0.0, spacing=1)]
    for j, (tag, col, lab, t0) in enumerate((("t0_is", BLUE, "IN SAMPLE", 0.6), ("t0_oos", CYAN, "OUT OF SAMPLE (BURNED)", 1.2))):
        y = 290 + j * 280
        S.els += [Box((MX, y, MX + 560, y + 256), PANEL, 18, t0=t0 - 0.2),
                  Txt((MX + 30, y + 24), lab, 17, "demi", col, t0=t0, bg=PANEL, spacing=2),
                  Num((MX + 30, y + 56), R[f"{tag}_c"], lambda v: fmt_c(v) + " / share", 56, "bold", INK, t0=t0,
                      bg=PANEL),
                  Txt((MX + 30, y + 140), f"95% CI {ci_txt(R[f'{tag}_lo'], R[f'{tag}_hi'])}¢", 21, "regular",
                      MUTED, t0=t0 + 0.3, bg=PANEL),
                  Txt((MX + 30, y + 186), "Sharpe", 21, "regular", MUTED, t0=t0 + 0.3, bg=PANEL),
                  Num((MX + 130, y + 178), R[f"{tag}_sh"], lambda v: f"{v:.1f}", 32, "demi", col, t0=t0 + 0.3, bg=PANEL),
                  Txt((MX + 250, y + 186), f"{usd(R[f'{tag}_day'], 0)}/day  ·  {R[f'{tag}_seeds']}-seed mean", 21,
                      "regular", MUTED, t0=t0 + 0.3, bg=PANEL)]
    cv = R["t0_curves"]
    Bs = sorted(cv["IS"]["tournament"], key=float)
    xs = [float(b) for b in Bs]
    be, calB, preB = R["t0_be"], R["t0_calB"], R["t0_preB"]
    mode = R["t0_mode"]

    def plot(ax):
        arts = []
        for reading, col in (("stamp", AMBER), ("tournament", BLUE), ("point", GREY)):
            ys = [cv["IS"][reading][b]["per_share_c"] for b in Bs]
            arts += ax.plot(xs, ys, color=col, lw=3, marker="o", ms=5)
        ys = [cv["burned_OOS"][mode][b]["per_share_c"] for b in Bs]
        arts += ax.plot(xs, ys, color=CYAN, lw=2.4, ls=(0, (5, 4)))
        ax.axhline(0, color=MUTED, lw=1.2)
        for xv, lab, c in ((preB, "pre-registered\nmedian", MUTED), (be, "break-even\n(stamp)", AMBER),
                           (calB, "calibrated\n(inference)", BLUE)):
            ax.axvline(xv, color=c, lw=1.2, ls=(0, (3, 4)))
        ax.set_xlabel("seconds from bounce to market reprice (not measured directly)", fontsize=15)
        ax.set_ylabel("cents per share", fontsize=15)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: disp(f"{v:+.0f}¢") if v else "0"))
        lo, hi = ax.get_ylim()
        ax.set_ylim(lo, hi + 1.6)
        return arts
    w, h = 1060, 520
    ax_l, full, to_px = mpl_chart(w, h, plot, rect=(0.09, 0.15, 0.89, 0.79))
    gx, gy = MX + 600, 296
    S.els.append(Layer(full, (gx, gy), t0=1.8, dur=2.2, mode="wipe", base=ax_l))
    for xv, lab, c, row in ((preB, f" pre-registered estimate {preB:.2f} s", MUTED, 0),
                            (be, f" break-even {be:.1f} s (stamp)", AMBER, 1),
                            (calB, f" calibrated {calB:.2f} s (inference)", BLUE, 2)):
        px = gx + to_px(xv, 0)[0]      # each label starts at its own line, one row each
        S.els.append(Txt((px, gy + 34 + 24 * row), lab, 16, "demi", c, "la", t0=2.4))
    lx, ly = gx + to_px(1.62, 0)[0], gy + to_px(0, 0)[1] + 40
    S.els += [Txt((lx, ly), "TIMING READING", 15, "demi", DIM, t0=2.0, spacing=2)]
    for i, (col, lab) in enumerate(((AMBER, "stamp"), (BLUE, f"{mode} (headline), in sample"), (GREY, "point"),
                                    (CYAN, f"{mode}, out of sample"))):
        yy = ly + 34 + i * 32
        S.els += [Box((lx, yy + 4, lx + 18, yy + 22), col, 3, t0=2.0 + 0.1 * i),
                  Txt((lx + 28, yy), lab, 19, "regular", MUTED, t0=2.0 + 0.1 * i)]
    if not R.pending("t3_u2is_c"):
        S.els.append(Txt((MX, 846), f"A frozen version (v3) then FAILED its blind tests: unseen markets "
                         f"{fmt_c(R['t3_u2is_c'])} (IS period), {fmt_c(R['t3_u2oos_c'])} (OOS period); burned out of "
                         f"sample {fmt_c(R['t3_boos_c'])}, CI {ci_txt(R['t3_boos_lo'], R['t3_boos_hi'])}¢ includes 0.",
                         21, "demi", CORAL, t0=3.0))
    d = ImageDraw.Draw(S.bg)
    src_note(d, (MX, 870), "results/tier0/results.json (headline, pnl_vs_t_reprice_minus_t_bounce, timing); "
             "results/tier0_v3/blind.json. Readings: in sample unless marked.")


def scene_live(S, R):
    S.head()
    ev = None                      # S10 keeps the session card; the engine demo video is on deck slide 4
    lx = MX
    if ev:
        clip = Clip([ev], (1152, 648))
        S.clips.append(clip)
        S.els.append(VideoEl(clip, (MX, 222)))
        lx = MX + 1152 + 40
    cw = (1180 - MX) if not ev else (W - MX - lx)
    S.els += [Box((lx, 222, lx + cw, 860), PANEL, 18, t0=0.2),
              Txt((lx + 32, 252), f"LIVE BOOK CHECK  ·  {R['live_when']}", 17, "demi", BLUE, t0=0.3, bg=PANEL,
                  spacing=2),
              Txt((lx + 32, 284), "paper only: read-only public feeds, no orders", 20, "regular", MUTED, t0=0.3,
                  bg=PANEL)]
    stats = [("seconds live", R["live_secs"], "{:.0f}"), ("book messages", R["live_msgs"], "{:,.0f}"),
             ("markets", R["live_mkts"], "{:.0f}"), ("snapshot mismatches", R["live_mismatch"], "{:.0f}"),
             ("feed gaps", R["live_gaps"], "{:.0f}"), ("orders sent", R["live_orders"], "{:.0f}")]
    for i, (lab, v, f) in enumerate(stats):
        cxx = lx + 32 + (i % 3) * (cw - 64) / 3
        y = 340 + (i // 3) * 130
        S.els += [Num((cxx, y), v, lambda x, f=f: f.format(x), 50, "demi", INK if i < 3 else GREEN, t0=0.5 + 0.12 * i,
                      bg=PANEL),
                  Txt((cxx, y + 64), lab, 19, "regular", MUTED, t0=0.5 + 0.12 * i, bg=PANEL)]
    R["live_snap"], R["live_paper"]
    S.els.append(Txt((lx + 32, 818), "Live: market data, risk and the paper executor. The full chain, from vision "
                     "call to paper order, ran on a recorded book.", 17, "regular", MUTED, t0=1.8, bg=PANEL,
                     maxw=cw - 64))
    # latency bars
    y = 620
    S.els += [Txt((lx + 32, y), "FEED LATENCY", 17, "demi", MUTED, t0=1.4, bg=PANEL, spacing=2)]
    mx = max(R["live_p99"], 1)
    for i, q in enumerate(("p50", "p95", "p99")):
        yy = y + 44 + i * 58
        v = R[f"live_{q}"]
        S.els += [Txt((lx + 32, yy), q, 22, "demi", INK, t0=1.5 + 0.15 * i, bg=PANEL),
                  Num((lx + cw - 32, yy - 2), v, lambda x: f"{x:.0f} ms", 26, "demi", INK, "ra", t0=1.5 + 0.15 * i,
                      bg=PANEL)]

        def bar(img, d, t, yy=yy, v=v, t0=1.5 + 0.15 * i):
            if t < t0:
                return
            k = ease((t - t0) / 1.1)
            bw = (cw - 64 - 220) * v / mx * k
            rrect(d, (lx + 100, yy + 6, lx + 100 + max(bw, 10), yy + 26), 6, fill=rgb(BLUE if i == 0 else "#2b5d9c"))
        S.els.append(Fn(bar, 1.5 + 0.15 * i + 1.1))
    # session card
    sx = 1220 if not ev else lx
    if not ev:
        state = R["sess_state"] or "pending"
        col = {"running": GREEN, "finished": BLUE, "stopped": CORAL, "no update": CORAL}.get(state, AMBER)
        since = R["sess_since"]
        S.els += [Box((sx, 222, W - MX, 860), PANEL2, 18, t0=0.8),
                  Txt((sx + 32, 252), "LIVE PAPER SESSION" + (f"  ·  {since[:10]}" if since else ""), 17, "demi",
                      AMBER, t0=0.9, bg=PANEL2, spacing=2)]

        def pulse(img, d, t):
            if t < 1.0:
                return
            a = 0.55 + 0.45 * math.cos((t - 1.0) * 2 * math.pi / 1.6)
            c = mix(col, PANEL2, a if state == "running" else 1.0)
            d.ellipse((sx + 32, 302, sx + 60, 330), fill=c)
            text(d, (sx + 76, 316), state.upper(), 40, "bold", col, "lm", spacing=2)
        S.els.append(Fn(pulse, 0.0, live=state == "running"))
        lines = [("status", R["sess_status"] or "pending"),
                 ("started  ·  as of", f"{since or 'pending'} UTC  ·  {R['sess_asof'] or 'pending'} UTC"),
                 ("strategy", R["sess_strategy"] or "pending"),
                 ("fills, pre-registered book", "pending" if R["sess_fills"] is None else f"{R['sess_fills']}"),
                 ("P&L, marked to mid", "pending" if R["sess_pnl"] is None else usd(R["sess_pnl"], 2, sign=True))]
        y = 362
        for lab, val in lines:
            S.els += [Txt((sx + 32, y), lab.upper(), 15, "demi", DIM, t0=1.2, bg=PANEL2, spacing=2),
                      Txt((sx + 32, y + 26), val, 21, "regular", INK, t0=1.2, bg=PANEL2, maxw=W - MX - sx - 64)]
            y += 26 + 28 * len(wrap(val, 21, "regular", W - MX - sx - 64)) + 16
        S.els += [Txt((sx + 32, 790), R["sess_label"] or "", 16, "regular", MUTED, t0=1.4, bg=PANEL2,
                      maxw=W - MX - sx - 64)]
    d = ImageDraw.Draw(S.bg)
    src_note(d, (MX, 880), "results/engine/live_market_run.json; results/live/summary.json (re-read at every render)")


def scene_risk(S, R):
    S.head()
    labels = ["gross edge", "taker fees", "net trading", "fixed costs\n(central)", "net after\ncosts"]
    g, f_, n_, fx, af = (R["is_gross_edge_day"], R["is_taker_fees_day"], R["is_net_trading_day"], -R["is_fixed_day"],
                         R["is_after_day"])
    bottoms = [0, g + f_, 0, n_ + fx, 0]
    heights = [g, -f_, n_, -fx, af]
    vals = [g, f_, n_, fx, af]
    cols = [BLUE, CORAL, BLUE, CORAL, BLUE if af >= 0 else CORAL]

    def plot(ax):
        x = np.arange(5)
        bars = ax.bar(x, heights, 0.62, bottom=bottoms, color=cols)
        labs = []
        for i, (b, v) in enumerate(zip(bars, vals)):
            top = bottoms[i] + heights[i]
            labs.append(ax.text(i, top + 8, disp(usd(v, 0, sign=i in (1, 3))), ha="center", va="bottom", color=INK,
                                fontsize=17, fontweight="demibold"))
        ax.set_xticks(x, labels)
        ax.set_ylim(min(0, af) - 20, g * 1.18)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:.0f}"))
        ax.set_ylabel("dollars per day, in sample", fontsize=15)
        return list(bars) + labs
    w, h = 880, 520
    ax_l, full, to_px = mpl_chart(w, h, plot, rect=(0.12, 0.15, 0.86, 0.8))
    S.els.append(Layer(full, (MX - 20, 236), t0=0.5, dur=1.8, mode="grow", base=ax_l, y0=to_px(0, 0)[1]))
    S.els += [Txt((MX, 770), f"Out of sample: {usd(R['oos_gross_edge_day'])} gross, {usd(R['oos_net_trading_day'])} "
                  f"after fees, {usd(R['oos_after_day'])}/day after central fixed costs.", 22, "demi", CORAL, t0=2.4,
                  maxw=860)]
    R["oos_taker_fees_day"], R["oos_fixed_day"]
    # capacity
    sc = R["scaling"]
    cx = 1010
    S.els += [Box((cx, 236, W - MX, 540), PANEL, 18, t0=1.0),
              Txt((cx + 30, 262), "CAPACITY: OUT-OF-SAMPLE $/DAY BY SIZE", 17, "demi", AMBER, t0=1.1, bg=PANEL, spacing=2)]
    mxv = max(abs(v["oos_day"]) for v in sc.values())
    bw = (W - MX - cx - 60) / len(sc)
    zy = 420
    for i, (s, v) in enumerate(sc.items()):
        bx = cx + 30 + i * bw
        t0 = 1.3 + 0.15 * i

        def bar(img, d, t, bx=bx, v=v, t0=t0):
            if t < t0:
                return
            k = ease((t - t0) / 1.0)
            hh = 90 * v["oos_day"] / mxv * k
            c = rgb(BLUE if v["oos_day"] > 0 else CORAL)
            d.rectangle((bx + 24, min(zy, zy - hh), bx + bw - 24, max(zy, zy - hh)), fill=c)
        S.els += [Fn(bar, t0 + 1.0),
                  Txt((bx + bw / 2, 300), usd(v["oos_day"], 0, sign=True), 21, "demi", INK, "ma", t0=t0 + 0.6, bg=PANEL),
                  Txt((bx + bw / 2, 470), s, 21, "demi", INK, "ma", t0=t0, bg=PANEL),
                  Txt((bx + bw / 2, 500), f"capital {usd(v['oos_cap'] / 1000, 0)}k", 16, "regular", MUTED, "ma",
                      t0=t0, bg=PANEL)]
    S.els.append(Box((cx + 30, zy, W - MX - 30, zy + 2), GRID, 0, t0=1.2, bg=PANEL))
    R["cap_k"]
    # kill switches
    ky = 560
    S.els += [Box((cx, ky, W - MX, 870), PANEL2, 18, t0=2.0),
              Txt((cx + 30, ky + 24), "KILL SWITCHES (docs/RISK.md)", 17, "demi", AMBER, t0=2.1, bg=PANEL2, spacing=2)]
    for i, (trig, act) in enumerate(R["kills"] or []):
        y = ky + 62 + i * 60
        S.els += [Txt((cx + 30, y), trig, 20, "demi", INK, t0=2.2 + 0.15 * i, bg=PANEL2),
                  Txt((cx + 30, y + 28), act, 17, "regular", MUTED, t0=2.2 + 0.15 * i, bg=PANEL2)]
    d = ImageDraw.Draw(S.bg)
    src_note(d, (MX, 880), "results/financials/financials.json (waterfall, fixed_costs.central, scaling); fixed costs "
             "are estimates, the feed licence an assumption")


def scene_close(S, R):
    url = "https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii"
    try:
        u = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
        if u.startswith("https://github.com/"):
            url = u[:-4] if u.endswith(".git") else u
    except OSError:
        pass
    vision_model = Path("models/vision/frozen_call_model.pkl")
    in_git = subprocess.run(["git", "ls-files", "--error-unmatch", str(vision_model)],
                            capture_output=True).returncode == 0
    R.put("vision_model_in_git", in_git, str(vision_model), "git ls-files --error-unmatch (tracked?)")
    R["vision_model_in_git"]
    S.els += [Txt((W / 2, 200), "COURTSIDE", 96, "bold", INK, "mm", t0=0.2),
              Txt((W / 2, 284), "Call the point before the ball lands.", 34, "medium", MUTED, "mm", t0=0.4),
              Box((W / 2 - 700, 334, W / 2 + 700, 404), PANEL, 16, t0=0.7),
              Txt((W / 2, 369), url.replace("https://", ""), 28, "demi", BLUE, "mm", t0=0.8, bg=PANEL),
              Box((W / 2 - 560, 422, W / 2 + 560, 582), PANEL2, 16, t0=1.1),
              Txt((W / 2 - 520, 440), "$ bash run.sh replay", 30, "demi", INK, "la", t0=1.2, bg=PANEL2),
              Txt((W / 2 + 520, 448), "paper engine on recorded live books, in seconds", 20, "regular", MUTED, "ra",
                  t0=1.2, bg=PANEL2),
              Txt((W / 2 - 520, 498), "$ bash run.sh data && bash run.sh reproduce", 30, "demi", INK, "la", t0=1.3,
                  bg=PANEL2),
              Txt((W / 2 - 520, 542), "public crawl (no keys, ~1–2 h), then every table and figure in the note", 18,
                  "regular", MUTED, "la", t0=1.3, bg=PANEL2),
              Txt((W / 2, 606), "Vision calls need models/vision/frozen_call_model.pkl, which is not in git "
                  "(rebuilt by hpg/engine_vision.sbatch)." if not in_git else "", 18, "regular", MUTED, "mm", t0=1.5),
              Txt((W / 2, 652), "Paper trading only. No real money was traded.", 24, "regular", INK, "mm", t0=1.6),
              Txt((W / 2, 690), "We bought no official ATP/WTA data feed and no trading result uses one; free public "
                  "score pages were recorded only to time their lag.", 20, "regular", INK, "mm", t0=1.7),
              Txt((W / 2, 726), "Tier-0 figures are a counterfactual: " + TIER0_LABEL.split(": ", 1)[1] + ".", 20,
                  "regular", AMBER, "mm", t0=1.8),
              Txt((W / 2, 762), "Every number on screen is listed with its source file and key in "
                  "results/viz/video_manifest.json.", 18, "regular", MUTED, "mm", t0=1.9),
              Txt((W / 2, 796), CREDIT + "  ·  narration: synthetic voice (macOS say, " + VOICE + ")", 18,
                  "regular", MUTED, "mm", t0=2.0)]


# ----------------------------------------------------------------------------------------------------
# captions
# ----------------------------------------------------------------------------------------------------
def caption_img(s):
    lines = wrap(s, 36, "medium", 1500)
    if len(lines) == 2:                       # balance two-line captions (no one-word orphans)
        f, words = F(36, "medium"), disp(s).split()
        k = min(range(1, len(words)), key=lambda i: max(f.getlength(" ".join(words[:i])),
                                                         f.getlength(" ".join(words[i:]))))
        lines = [" ".join(words[:k]), " ".join(words[k:])]
    lh = 48
    tw = max(F(36, "medium").getlength(ln) for ln in lines)
    bw, bh = int(tw + 64), int(len(lines) * lh + 30)
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=14, fill=rgb(BG) + (215,))
    for i, ln in enumerate(lines):
        d.text((bw / 2, 15 + lh / 2 + i * lh), ln, font=F(36, "medium"), fill=rgb(INK) + (255,), anchor="mm")
    return im, ((W - bw) // 2, H - 40 - bh)


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


# ----------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", action="store_true", help="write one PNG per scene (end state) and stop")
    ap.add_argument("--scenes", default="", help="comma-separated scene ids for --stills")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    try:
        os.nice(10)
    except OSError:
        pass
    if shutil.which("say") is None and not args.stills:
        sys.exit("macOS 'say' is required for narration")
    R = Results()
    build_values(R)
    metas = parse_script(R)
    if args.scenes:
        keep = set(args.scenes.split(","))
        metas = [m for m in metas if m["id"] in keep]

    # narration -> scene durations, caption cues, audio
    from concurrent.futures import ThreadPoolExecutor
    all_lines = [ln for m in metas for ln in m["lines"]]
    with ThreadPoolExecutor(2) as ex:
        audio = dict(zip(all_lines, ex.map(tts, all_lines))) if not args.stills else {}
    scenes, cues, t = [], [], 0.0
    for m in metas:
        S = build_scene(m, R)
        if args.stills:
            S.dur = min(max(S.static_after(), 4.0), 6.0) + 0.5
        else:
            tt = t + LEAD
            for ln in m["lines"]:
                n = len(audio[ln]) / SR
                cues.append((tt, tt + n, ln, audio[ln]))
                tt += n + GAP
            S.dur = (tt - GAP - t) + LEAD + HOLD.get(m["key"], 0.0)
            S.start = t
            t += S.dur
        scenes.append(S)
    if args.stills:
        outdir = WORK / "stills"
        outdir.mkdir(parents=True, exist_ok=True)
        for S in scenes:
            p = outdir / f"{S.id}_{S.key}.png"
            S.render(S.dur).save(p)
            print("still", p)
            S.close()
        return
    total = t
    nfr = int(round(total * FPS))

    # audio track
    WORK.mkdir(parents=True, exist_ok=True)
    a = np.zeros(int(total * SR) + SR, dtype=np.float32)
    for s, e, ln, au in cues:
        i = int(s * SR)
        a[i:i + len(au)] += au
    a = np.clip(a / max(1e-6, np.abs(a).max()) * 0.89, -1, 1)
    wav = WORK / "narration.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((a * 32767).astype("<i2").tobytes())

    # captions: SRT + burned
    with SRT.open("w") as fh:
        for i, (s, e, ln, _) in enumerate(cues, 1):
            fh.write(f"{i}\n{srt_time(s)} --> {srt_time(e + 0.1)}\n{disp(ln)}\n\n")
    cap_imgs = [caption_img(ln) for _, _, ln, _ in cues]

    out = Path(args.out)
    tmp = out.with_suffix(".tmp.mp4")
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-threads", "4", "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-movflags", "+faststart",
         "-shortest", str(tmp)], stdin=subprocess.PIPE)
    last_key, last_bytes, ci = None, None, 0
    for fi in range(nfr):
        T = fi / FPS
        i = next(k for k, S in enumerate(scenes) if T < S.start + S.dur or k == len(scenes) - 1)
        S = scenes[i]
        lt = T - S.start
        while ci < len(cues) and T > cues[ci][1] + GAP:
            ci += 1
        cap = ci if ci < len(cues) and cues[ci][0] <= T else None
        fade = None
        if lt > S.dur - XF / 2 and i + 1 < len(scenes):
            fade = (scenes[i + 1], lt - S.dur, 0.5 - (S.dur - lt) / XF)
        elif lt < XF / 2 and i > 0:
            fade = (scenes[i - 1], scenes[i - 1].dur + lt, 0.5 - lt / XF)
        key = (i, cap) if (fade is None and lt >= S.static_after()) else None
        if key is not None and key == last_key:
            enc.stdin.write(last_bytes)
            continue
        img = S.render(lt)
        if fade is not None:
            other, ot, k = fade
            img = Image.blend(img, other.render(ot), max(0.0, min(1.0, k)))
        else:
            img = img.copy()
        if cap is not None:
            ci_img, pos = cap_imgs[cap]
            img.paste(ci_img, pos, ci_img)
        b = img.tobytes()
        enc.stdin.write(b)
        last_key, last_bytes = key, b
        if fi % 300 == 0:
            print(f"  frame {fi}/{nfr}  ({S.id})", flush=True)
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("ffmpeg failed")
    tmp.replace(out)
    for S in scenes:
        S.close()

    # manifest
    man = {"video": str(out), "srt": str(SRT), "script": str(SCRIPT), "duration_s": round(total, 2),
           "voice": VOICE, "rate_wpm": RATE,
           "scenes": [{"id": S.id, "key": S.key, "title": S.title, "start_s": round(S.start, 2),
                       "dur_s": round(S.dur, 2)} for S in scenes],
           "captions": [{"start_s": round(s, 2), "end_s": round(e, 2), "text": disp(ln)} for s, e, ln, _ in cues],
           "values": {}}
    for name, e in R.entries.items():
        if not e["used_in"]:
            continue
        v = e["value"]
        if isinstance(v, (list, dict)) and len(json.dumps(v, default=str)) > 400:
            v = f"<series: {len(v)} items>"
        man["values"][name] = {"value": v, "file": e["file"], "key": e["key"], "pending": e["pending"],
                               "shown_in": e["used_in"], **({"note": e["note"]} if e["note"] else {})}
    man["pending"] = sorted(n for n, e in man["values"].items() if e["pending"])
    import datetime as _dt
    srcs = sorted({e["file"] for e in man["values"].values() if e["file"] and Path(e["file"]).exists()})
    untracked = [f for f in srcs if subprocess.run(["git", "ls-files", "--error-unmatch", f],
                                                     capture_output=True).returncode != 0]
    man["rendered_utc"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    man["git_head_at_render"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                               text=True).stdout.strip()
    man["source_files"] = srcs
    man["source_files_not_in_git_at_render"] = untracked
    man["source_files_modified_vs_head_at_render"] = [
        f for f in srcs if f not in untracked and subprocess.run(["git", "diff", "--quiet", "HEAD", "--", f]).returncode]
    if untracked:
        print("NOTE: source files not tracked by git at render time:", ", ".join(untracked))
    man["embedded_in_assets"] = [
        {"asset": "results/tracking/demo/0[1-4]_*.mp4", "text": "MISS CALLED -<lead> ms, P(miss), frame, t",
         "source": "results/tracking/demo/manifest.json clips[i] (call_lead_ms, p_miss_at_50ms); rendered by "
                   "src/tracking/render_demo.py from the frozen model"},
        {"asset": "results/viz/courtside_replay.mp4", "text": "CALLED 200 MS EARLY; OUT 13.7 cm; P(out) 100%",
         "source": "results/viz/viz_data.json shot.preds / shot.out_cm (simulated physics)"},
        {"asset": "results/viz/courtside_replay.mp4", "text": "everyone else pays ~1\u00a2 a share",
         "source": "hard-coded caption in scripts/render_hawkeye_video.py; compare "
                   "results/fasttier_walkforward_is.csv others_net30_c (all months negative)"},
        {"asset": "results/viz/courtside_replay.mp4", "text": "real tape prices and wallet dots",
         "source": "results/viz/viz_data.json tape.prints"}]
    MANIFEST.write_text(json.dumps(man, indent=1, default=str) + "\n")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {total:.1f} s), {SRT}, {MANIFEST}")


if __name__ == "__main__":
    main()
