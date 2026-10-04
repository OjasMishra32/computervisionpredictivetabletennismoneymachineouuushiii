#!/usr/bin/env python3
"""COURTSIDE pitch deck (Gator Quant Hacks 2026, Systematic Trading). Data-driven.

Rebuild from the repo root:

    .venv/bin/python docs/deck/build_deck.py            # writes docs/deck/courtside.pptx (+ .pdf if soffice exists)

What it writes
--------------
* docs/deck/courtside.pptx: 16:9. Ten main slides for a 4:45 talk (timed script in every slide's notes),
  fourteen Q&A backup slides (the ten hardest questions in research/compliance/JUDGE.md plus four from
  docs/QA_PREP.md, two of them the organizers' own: latency under 3 s and capital capacity), each with its
  honest answer and the evidence, then hidden manifest slides.
* docs/deck/courtside_manifest.json: every number on every slide, with the results file and key it was
  read from. The same list is on the hidden slides at the end of the deck.
* docs/deck/courtside.pdf: only when LibreOffice (soffice) is on PATH.

Honesty rules the builder enforces
----------------------------------
* Every number on a slide is read from a results file at build time (V(...) below) and recorded in the
  manifest with its source key. The only numerals typed by hand are definitions, not results: the 0–3 s
  window, the 30 s markout, the stress cases (+½ tick, ×2), the footage frame rates, and the 3× capital
  convention.
* A results file or key that does not exist yet renders as "pending" (never a guess). Pending items are
  listed at the end of the build log and on the closing slide.
* The build FAILS LOUDLY only on internal contradictions: two results files that should agree but do not,
  the note quoting a headline number that differs from the JSON, a counterfactual that lost its label, or
  a paper-only run that reports an order sent. Known, documented discrepancies print a WARNING.
* The tier-0 CV-edge result is always labelled TIER0_LABEL. Paper only: no slide says real money was traded.
  We bought no official ATP/WTA data feed and no trading result uses one; free public score pages (WTA website,
  ESPN) were recorded only to time their lag, and the slides say exactly that.
* No "tonight"/"tomorrow": dates are read from the files (HYPOTHESIS_V2.md, results/live/summary.json), and the
  live-session card says "warming up" or "stopped" instead of printing a 1970 timestamp or "running".

Fonts: headings Arial Narrow (bold), body Arial; both ship with Office and macOS.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import (XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE,
                             XL_TICK_LABEL_POSITION, XL_TICK_MARK)
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

DECK_DIR = Path(__file__).resolve().parent
ROOT = DECK_DIR.parents[1]
OUT = DECK_DIR / "courtside.pptx"
OUT_PDF = DECK_DIR / "courtside.pdf"
OUT_MANIFEST = DECK_DIR / "courtside_manifest.json"

REPO_URL = "https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii"
REPO_SHORT = REPO_URL.removeprefix("https://")

# --------------------------------------------------------------------------------------------
# Palette and type
# --------------------------------------------------------------------------------------------
BLUE = "27598B"      # court blue
RED = "D1432F"       # line-call red
INK = "0C1A28"       # ink
OFF = "F2F5F8"       # off-white (light slide background)
WHITE = "FFFFFF"
FIGBG = "FCFCFB"     # background baked into results/figures/*.png
MUTED = "566676"     # secondary text on light backgrounds (5.2:1 on OFF)
MUTED_DK = "9FB3C8"  # secondary text on ink (8:1 on INK)
LINE = "D3DCE5"      # hairlines, card borders
BLUE_TINT = "E4ECF4"
RED_TINT = "FBEAE6"
INK_2 = "17293B"     # raised panels on ink

HEAD = "Arial Narrow"
BODY = "Arial"
MONO = "Courier New"
PANOSE = {"Arial Narrow": "020B0606020202030204", "Arial": "020B0604020202020204"}

SW, SH = 13.333, 7.5   # slide, inches
M = 0.6                # side margin
CW = SW - 2 * M        # content width

MINUS = "−"

# --------------------------------------------------------------------------------------------
# Sources. Every number on a slide goes through V() or D(), which read a results file at build time
# and record (slide, text, file :: key) in MANIFEST. A missing file or key renders as "pending".
# --------------------------------------------------------------------------------------------
PENDING = "pending"
_JSON: dict = {}
MANIFEST: list[dict] = []
PENDING_ITEMS: list[tuple[str, str]] = []
WARNINGS: list[str] = []
_SLIDE = ["setup"]

# Result files (paths only; nothing is read until a slide asks).
F_SUM = "results/summary.json"
F_CAUSAL = "results/v2/causal.json"
F_COST = "results/v2/cost_stress.json"
F_NM = "results/v2/note_metrics.json"
F_FWD = "results/v2/forward.json"
F_RIGOR = "results/rigor/rigor.json"
F_EXP = "results/expand/results.json"
F_LOW = "results/lowloss/results.json"
F_T0 = "results/tier0/results.json"
F_T0_VERIFIED = "results/tier0/VERIFIED"
F_MAKER = "results/maker/oos.json"
F_FIN = "results/financials/financials.json"
F_PMC = "results/financials/pm_compute.json"
F_RISK = "results/risk/risk_stats.json"
F_ENG_LIVE = "results/engine/live_market_run.json"
F_ENG_DEMO = "results/engine/demo_run.json"
F_ENG_BENCH = "results/engine/vision_bench.json"
F_TRACK = "results/tracking/summary.json"
F_TRACK_DEMO = "results/tracking/demo/manifest.json"
F_TENNIS = "results/tennis_tracking/summary.json"
F_LEVER = "results/leverage_stats.json"
F_VIZ = "results/viz/viz_data.json"
F_TT = "results/tt/results.json"
F_DECAY = "results/decay/decay.json"
F_LIVE = "results/live/summary.json"
F_PEEKS = "results/oos_peeks.log"
F_T0V3 = "results/tier0_v3/blind.json"
F_HYP2 = "HYPOTHESIS_V2.md"
F_SWEEP = "results/tier0/latency_sweep.json"
F_OVO = "results/engine/online_vs_offline.json"
F_RT = "results/redteam/derived.json"
F_REPLAY = "results/replay/replay.json"
F_E2E = "results/e2e/summary.json"
F_CAP = "results/capacity/capacity.json"
F_ALPHA = "results/alpha/alpha.json"
OVO_RUN = "fp16_cl_fuse_compile_b1_realtime"
NOTE = "docs/NOTE.md"
README = "README.md"

# The CV trader at the 1 s licensed-feed baseline always carries this label, verbatim, wherever it appears.
TIER0_LABEL = ("SIMULATED: assumed 1 s licensed feed (not purchased); parameters measured; trade set = points "
               "that later moved ≥ 4¢ (selected on outcomes, not ex ante)")
# The older courtside-camera reading (V = 0) is only shown as a counterfactual row.
CAMERA_LABEL = "camera counterfactual: courtside camera at V = 0, not feasible (no camera at any court)"

# Keys into results/v2/causal.json (the frozen v2 book, causal window).
IS0, IS5, IS10 = (f"causal/is_eval/slip{s}" for s in ("0.0", "0.005", "0.01"))
OS0, OS5, OS10 = (f"causal/burned_oos/slip{s}" for s in ("0.0", "0.005", "0.01"))


class Missing(Exception):
    pass


def _load(rel: str):
    if rel not in _JSON:
        p = ROOT / rel
        if not p.exists():
            raise Missing(rel)
        _JSON[rel] = json.loads(p.read_text(encoding="utf-8"))
    return _JSON[rel]


def raw(rel: str, *keys):
    """The value at rel :: keys; raises Missing if the file or any key does not exist."""
    d = _load(rel)
    for k in keys:
        if isinstance(d, list) and isinstance(k, int) and -len(d) <= k < len(d):
            d = d[k]
        elif isinstance(d, dict) and k in d:
            d = d[k]
        else:
            raise Missing(f"{rel} :: {' > '.join(map(str, keys))}")
    if d is None or (isinstance(d, float) and math.isnan(d)):
        raise Missing(f"{rel} :: {' > '.join(map(str, keys))} is null")
    return d


def opt(rel: str, *keys, default=None):
    try:
        return raw(rel, *keys)
    except Missing:
        return default


def key_str(rel: str, *keys) -> str:
    return f"{rel} :: {' > '.join(map(str, keys))}" if keys else rel


def _record(text: str, source: str) -> str:
    MANIFEST.append({"slide": _SLIDE[0], "text": text, "source": source})
    if text == PENDING:
        PENDING_ITEMS.append((_SLIDE[0], source))
    return text


def V(rel: str, *keys, f=None, how: str | None = None) -> str:
    """A number for a slide: read rel :: keys, format with f, record in the manifest. Missing -> 'pending'."""
    try:
        x = raw(rel, *keys)
        text = f(x) if f else str(x)
    except Missing:
        text = PENDING
    return _record(text, key_str(rel, *keys) + (f"  [{how}]" if how else ""))


def D(fn, source: str) -> str:
    """A derived number: fn() computes the text from results files; source says which and how."""
    try:
        text = fn()
    except Missing:
        text = PENDING
    return _record(text, source)


def slide_ctx(label: str) -> None:
    _SLIDE[0] = label


# ---- number formats ----
def signed(x: float, d: int = 2) -> str:
    return ("+" if x >= 0 else MINUS) + f"{abs(x):.{d}f}"


def num(x: float, d: int = 2) -> str:
    return (MINUS if x < 0 else "") + f"{abs(x):.{d}f}"


def ci(pair, d: int = 2) -> str:
    return f"[{num(pair[0], d)}, {num(pair[1], d)}]"


def cents(x):
    return signed(x) + "¢"


def cents1(x):
    return signed(x, 1) + "¢"


def sh1(x):
    return num(x, 1)


def pct0(x):
    return f"{num(x, 0)}%"


def pct1(x):
    return f"{num(x, 1)}%"


def frac_pct0(x):
    return f"{num(100 * x, 0)}%"


def frac_pct1(x):
    return f"{num(100 * x, 1)}%"


def usd0(x):
    return (MINUS if x < 0 else "") + f"${abs(x):,.0f}"


def usd1(x):
    return (MINUS if x < 0 else "") + f"${abs(x):,.1f}"


def usd_k(x):
    return (MINUS if x < 0 else "") + f"${abs(x) / 1000:.1f}k"


def usd_signed_k(x):
    return ("+" if x >= 0 else MINUS) + f"${abs(x) / 1000:.1f}k"


def usd_signed0(x):
    return ("+" if x >= 0 else MINUS) + f"${abs(x):,.0f}"


def usd_m(x):
    return f"${x / 1e6:.2f}M"


def usd_b(x):
    return f"${x / 1e9:.2f}B"


def intc(x):
    return f"{int(round(x)):,}"


def sec1(x):
    return f"{signed(x, 1)} s"


def sec2(x):
    return f"{signed(x, 2)} s"


def ms0(x):
    return f"{x:.0f} ms"


def dsr3(x):
    return f"{x:.3f}"            # 3 dp everywhere (0.997, not a rounded-up 1.00); the video uses the same


def ascii_signed(x: float, d: int = 2) -> str:
    return ("+" if x >= 0 else "-") + f"{abs(x):.{d}f}"


# ---- the financials headline is a list of rows; find one by (strategy prefix, period) ----
def fin_row(strategy: str, period: str) -> int:
    rows = raw(F_FIN, "headline")
    mine = [(i, r) for i, r in enumerate(rows) if r.get("strategy", "").startswith(strategy)]
    for i, r in mine:  # exact period label first, then a label that extends it ("IS, 1 s-delay matches ...")
        if r.get("period") == period:
            return i
    for i, r in mine:
        if str(r.get("period", "")).startswith(period + ","):
            return i
    raise Missing(f"{F_FIN} :: headline row {strategy!r} / {period!r}")


def FIN(strategy: str, period: str, *keys, f=None) -> str:
    try:
        i = fin_row(strategy, period)
    except Missing:
        return _record(PENDING, f"{F_FIN} :: headline row {strategy!r} / {period!r}")
    return V(F_FIN, "headline", i, *keys, f=f, how=f"row {strategy} / {period}")


# ---- walk-forward fast tier (results/summary.json): IS months before the OOS start, then OOS months ----
def wf_months():
    s = raw(F_SUM, "is", "h6_walkforward")
    o = raw(F_SUM, "oos", "h6_walkforward")
    oos_month = raw(F_SUM, "universe", "oos_start")[:7]
    return [m for m in s if m["month"] < oos_month], list(o)


WF_SRC = f"{F_SUM} :: is > h6_walkforward (months before universe > oos_start) + oos > h6_walkforward"


def peeks() -> list[str]:
    p = ROOT / F_PEEKS
    if not p.exists():
        raise Missing(F_PEEKS)
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def fwd_when() -> str:
    """The forward test's planned run time, quoted from HYPOTHESIS_V2.md (never 'tomorrow')."""
    m = re.search(r"planned ~?(\d{4}-\d\d-\d\d \d\d:\d\d UTC)", (ROOT / F_HYP2).read_text(encoding="utf-8")
                  if (ROOT / F_HYP2).exists() else "")
    if not m:
        raise Missing(F_HYP2 + " :: planned forward date")
    return m.group(1)


FWD_WHEN_SRC = F_HYP2 + " :: Forward test 'planned ~<date> UTC'"


def live_state() -> dict:
    """State of the live paper session (same rules as scripts/make_video.py). Never 'running' for a stopped,
    stale or warming-up session: a STOPPED_<run> marker or stopped/error/killed in the status means stopped;
    'now' at the epoch (1970) or empty counters means warming up; no write for 15 min means no update."""
    import datetime as _dt
    sm = opt(F_LIVE)
    if not sm:
        raise Missing(F_LIVE)
    p = ROOT / F_LIVE
    status, run = str(sm.get("status", "")), sm.get("run") or ""
    now = str(sm.get("now") or "")
    since = str(sm.get("started_process") or sm.get("session_start") or "")[:16].replace("T", " ")
    mtime = _dt.datetime.fromtimestamp(p.stat().st_mtime, _dt.timezone.utc)
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
    asof = now[:16].replace("T", " ") if now and not now.startswith("1970") else mtime.strftime("%Y-%m-%d %H:%M")
    return {"state": state, "status": status, "since": since, "asof": asof, "run": run}


LIVE_STATE_SRC = (F_LIVE + " :: status, run, started_process, now, counters  [+ STOPPED_<run> marker and file age; "
                  "1970 'now' or empty counters = warming up]")


def valid_mp4(path: Path) -> bool:
    """True only for a complete video (another workflow may still be writing it)."""
    if not path.exists() or not shutil.which("ffprobe"):
        return path.exists() and not shutil.which("ffprobe") and path.stat().st_size > 0
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                        str(path)], capture_output=True, text=True, timeout=30)
    try:
        return r.returncode == 0 and float(r.stdout.strip()) > 1.0
    except ValueError:
        return False


def video_duration(path: Path, fallback: float) -> float:
    """Clip length for the autoplay timing node only (never shown on a slide)."""
    if shutil.which("ffprobe"):
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                  "default=nw=1:nk=1", str(path)], capture_output=True, text=True, timeout=30)
            return float(out.stdout.strip())
        except (ValueError, subprocess.SubprocessError):
            pass
    return fallback


# --------------------------------------------------------------------------------------------
# Consistency checks: fail loudly on internal contradictions only; missing files are "pending".
# --------------------------------------------------------------------------------------------


def fail(msg: str) -> None:
    for w in WARNINGS:
        print(f"WARNING: {w}")
    sys.exit(f"[CONTRADICTION] {msg}")


def warn(msg: str) -> None:
    WARNINGS.append(msg)  # printed once, at the end of the build


def _agree(a, b, tol=1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def run_checks() -> None:
    # 1. Files that must agree to rounding (each pair: two results files computing the same quantity).
    pairs = [
        ((F_CAUSAL, IS0, "per_share_c"), (F_COST, "is_eval/base", "per_share_c")),
        ((F_CAUSAL, OS0, "per_share_c"), (F_COST, "burned_oos/base", "per_share_c")),
        ((F_CAUSAL, IS0, "total_pnl_usd"), (F_COST, "is_eval/base", "total_pnl_usd")),
        ((F_CAUSAL, OS0, "total_pnl_usd"), (F_COST, "burned_oos/base", "total_pnl_usd")),
        ((F_CAUSAL, IS0, "sharpe_ann"), (F_NM, "is", "sharpe_ann")),
        ((F_CAUSAL, OS0, "sharpe_ann"), (F_NM, "burned_oos", "sharpe_ann")),
        ((F_CAUSAL, IS0, "sharpe_ann"), (F_RIGOR, "sharpe_moments", "v2_is", "sharpe_ann")),
        ((F_CAUSAL, OS0, "sharpe_ann"), (F_RIGOR, "sharpe_moments", "v2_oos", "sharpe_ann")),
        ((F_COST, "is_eval/fee_x2", "per_share_c"), (F_NM, "is", "fees_x2_per_share_c")),
        ((F_COST, "burned_oos/fee_x2", "per_share_c"), (F_NM, "burned_oos", "fees_x2_per_share_c")),
        ((F_COST, "burned_oos/costs_x2", "per_share_c"), (F_NM, "burned_oos", "costs_x2_per_share_c")),
        ((F_EXP, "primary", "u2_is", "per_share_c"), (F_EXP, "books", "u2_is", "slip0.0", "per_share_c")),
        ((F_EXP, "primary", "u2_oos", "per_share_c"), (F_EXP, "books", "u2_oos", "slip0.0", "per_share_c")),
        ((F_EXP, "books", "u2_oos", "slip0.0", "total_pnl_usd"),
         (F_RIGOR, "sharpe_moments", "v2_u2oos_blind", "total_usd")),
        ((F_MAKER, "primary", "value_c"), (F_MAKER, "headline", "mean_pnl_per_share_c")),
        ((F_PMC, "p07_wallet_clustered_ci", "burned_oos", "per_share_c"), (F_CAUSAL, OS0, "per_share_c")),
    ]
    for a, b in pairs:
        try:
            va, vb = raw(*a), raw(*b)
        except Missing as e:
            print(f"  check skipped (pending): {e}")
            continue
        if not _agree(va, vb):
            fail(f"{key_str(*a)} = {va} but {key_str(*b)} = {vb}")
    try:
        rows = raw(F_FIN, "headline")
        for strat, per, other in (("v2 (", "IS", (F_CAUSAL, IS0, "per_share_c")),
                                  ("v2 (", "OOS (burned, non-blind)", (F_CAUSAL, OS0, "per_share_c")),
                                  ("Tier-0", "IS", (F_T0, "headline", "IS", "mean", "per_share_c")),
                                  ("Tier-0", "OOS (burned, non-blind)", (F_T0, "headline", "burned_OOS", "mean",
                                                                         "per_share_c")),
                                  ("Maker", "OOS (blind)", (F_MAKER, "headline", "share_weighted_net_c"))):
            try:
                r = rows[fin_row(strat, per)]
            except Missing as e:
                print(f"  check skipped (pending): {e}")
                continue
            if not _agree(r["net_c_per_share"], raw(*other), tol=1e-3):
                fail(f"financials {strat} / {per} net_c_per_share {r['net_c_per_share']} != {key_str(*other)}")
        bad = [c["what"] for c in raw(F_FIN, "checks") if not c.get("ok")]
        if bad:
            fail(f"results/financials/financials.json self-checks failed: {bad}")
    except Missing as e:
        print(f"  check skipped (pending): {e}")
    if opt(F_RISK, "reproduction_check", "ok") is False:
        fail("results/risk/risk_stats.json reproduction_check.ok is false")

    # 2. Verdicts must match their own confidence intervals (pass iff the 95% CI excludes 0).
    for per in ("u2_is", "u2_oos"):
        r = opt(F_EXP, "primary", per)
        if r and r["pass"] != (r["per_share_ci_c"][0] > 0):
            fail(f"{F_EXP} primary {per}: pass={r['pass']} but CI {r['per_share_ci_c']}")
    r = opt(F_MAKER, "primary")
    if r and (r["verdict"] == "FAILURE") != (r["ci95_c"][0] <= 0):
        fail(f"{F_MAKER} primary verdict {r['verdict']} disagrees with CI {r['ci95_c']}")
    fw = opt(F_FWD)
    if fw:
        for vk, ck in (("verdict_A_fast_tier", "primary_A_fast_minus_others_c"),
                       ("verdict_B_v2_book", "primary_m30_per_share_c")):
            if vk in fw and ck in fw and fw[vk].startswith("PASS") != (fw[ck][1] > 0):
                fail(f"{F_FWD} {vk}={fw[vk]} disagrees with {ck}={fw[ck]}")

    # 3. Paper only, and the counterfactual keeps its label.
    if opt(F_ENG_LIVE, "paper_only") is False or (opt(F_ENG_LIVE, "orders_sent", default=0) or 0) != 0:
        fail(f"{F_ENG_LIVE} reports a non-paper run or an order sent")
    if opt(F_ENG_DEMO, "paper_only") is False or (opt(F_ENG_DEMO, "orders_sent_to_any_venue", default=0) or 0) != 0:
        fail(f"{F_ENG_DEMO} reports a non-paper run or an order sent")
    lab = opt(F_LIVE, "label")
    if lab is not None and "PAPER" not in lab.upper():
        fail(f"{F_LIVE} label does not say PAPER: {lab!r}")
    lab = opt(F_T0, "label")
    if lab is not None and "COUNTERFACTUAL" not in lab.upper():
        fail(f"{F_T0} label lost the COUNTERFACTUAL marker: {lab!r}")
    if not ("SIMULATED" in TIER0_LABEL and "not ex ante" in TIER0_LABEL and "not purchased" in TIER0_LABEL):
        fail(f"TIER0_LABEL lost a marker (SIMULATED / not ex ante / not purchased): {TIER0_LABEL!r}")
    lab = opt(F_SWEEP, "label")
    if lab is not None and "assumed" not in lab.lower():
        fail(f"{F_SWEEP} label lost the 'assumed' marker: {lab!r}")
    rt = opt(F_RT, "keys", "cv.pre.oos.usd", "value")
    if rt is not None and not _agree(rt, raw(F_SWEEP, "video_own120", "tournament", "1", "burned_OOS", "usd_per_day"), tol=0.01):
        fail(f"{F_RT} cv.pre.oos.usd {rt} != {F_SWEEP} video_own120.tournament['1'].burned_OOS.usd_per_day")
    lab = opt(F_T0V3, "label")
    if lab is not None and "COUNTERFACTUAL" not in lab.upper():
        fail(f"{F_T0V3} label lost the COUNTERFACTUAL marker: {lab!r}")
    for k in ("u2_is", "u2_oos", "burned_oos"):  # a v3 verdict must match its own match-clustered CI
        r = opt(F_T0V3, "sets", k)
        if r and (r["reading"]["verdict"] == "PASS") and r["primary"]["per_share_ci95_c_lo"] <= 0:
            fail(f"{F_T0V3} {k}: PASS but match-CI low {r['primary']['per_share_ci95_c_lo']}")

    # 4. Prose that quotes a JSON headline must quote it correctly (note vs JSON).
    vpath = ROOT / F_T0_VERIFIED
    try:
        h = raw(F_T0, "headline")
        if vpath.exists():
            vt = vpath.read_text(encoding="utf-8")
            for per, tag in (("IS", "IS"), ("burned_OOS", "burned OOS")):
                m = h[per]["mean"]
                want = (f"{tag} {ascii_signed(m['per_share_c'])}c "
                        f"[{m['per_share_ci95_c_lo']:.2f},{m['per_share_ci95_c_hi']:.2f}] "
                        f"Sharpe {m['sharpe_ann']:.1f}+/-{h[per]['sd']['sharpe_ann']:.1f}")
                if want not in vt:
                    fail(f"{F_T0_VERIFIED} does not quote the JSON headline: expected {want!r}")
        else:
            warn(f"{F_T0_VERIFIED} missing: tier-0 headline not marked verified")
    except Missing as e:
        print(f"  check skipped (pending): {e}")
    note = (ROOT / NOTE).read_text(encoding="utf-8") if (ROOT / NOTE).exists() else ""
    num_re = r"([+−-]?\d+\.\d+)"
    m = re.search(r"Net ¢/share at fast-tier fills\**\s*\|\s*\**" + num_re + r" \[" + num_re + ", " + num_re
                  + r"\]\**\s*\|\s*\**" + num_re + r" \[" + num_re + ", " + num_re + r"\]", note)
    if m:
        got = [float(g.replace("−", "-")) for g in m.groups()]
        want = [raw(F_CAUSAL, IS0, "per_share_c"), *raw(F_CAUSAL, IS0, "per_share_ci_c"),
                raw(F_CAUSAL, OS0, "per_share_c"), *raw(F_CAUSAL, OS0, "per_share_ci_c")]
        if any(abs(g - round(w, 2)) > 0.0051 for g, w in zip(got, want)):
            fail(f"{NOTE} Table 2 quotes {got}, results/v2/causal.json gives {[round(w, 2) for w in want]}")
    else:
        warn(f"{NOTE}: Table 2 'Net ¢/share at fast-tier fills' row not found; note-vs-JSON check skipped")
    m = re.search(r"Sharpe / max drawdown \|\s*([\d.]+) / ([−-]?[\d.]+)% \|\s*([\d.]+) / ([−-]?[\d.]+)%", note)
    if m:
        got = [float(g.replace("−", "-")) for g in m.groups()]
        want = [raw(F_CAUSAL, IS0, "sharpe_ann"), raw(F_CAUSAL, IS0, "max_dd_pct"),
                raw(F_CAUSAL, OS0, "sharpe_ann"), raw(F_CAUSAL, OS0, "max_dd_pct")]
        if any(abs(g - round(w, 1)) > 0.051 for g, w in zip(got, want)):
            fail(f"{NOTE} Sharpe/max DD row quotes {got}, results/v2/causal.json gives {want}")
    else:
        warn(f"{NOTE}: 'Sharpe / max drawdown' row not found; note-vs-JSON check skipped")

    # 5. Known, documented differences: printed, not fatal (the log is append-only; NOTE is not ours to edit).
    m = re.search(r"results/oos_peeks\.log`?,\s*(\d+) lines", note)
    try:
        n = len(peeks())
        if m and int(m.group(1)) != n:
            warn(f"{NOTE} says oos_peeks.log has {m.group(1)} lines; the log now has {n} (append-only; "
                 "the deck shows the live count)")
    except Missing:
        pass
    if opt(F_PMC, "p07_wallet_clustered_ci", "note_value_reproduced_to_2dp") is False:
        warn("results/financials/pm_compute.json p07: the note's wallet-clustered CI does not reproduce to 2 dp; "
             "the deck quotes pm_compute's value")
    readme = (ROOT / README).read_text(encoding="utf-8") if (ROOT / README).exists() else ""
    for cmd in ("bash run.sh replay", "bash run.sh data", "bash run.sh reproduce"):
        if cmd not in readme:
            fail(f"README.md no longer documents `{cmd}`, which the closing slide shows")

# --------------------------------------------------------------------------------------------
# Low-level helpers
# --------------------------------------------------------------------------------------------


def rgb(hex6: str) -> RGBColor:
    return RGBColor.from_string(hex6)


class R:
    """One text run."""

    def __init__(self, text, size=16, color=INK, bold=False, font=BODY, italic=False, spc=None):
        self.text, self.size, self.color, self.bold = text, size, color, bold
        self.font, self.italic, self.spc = font, italic, spc


class P:
    """One paragraph: runs plus paragraph options."""

    def __init__(self, *runs, align="l", before=0, after=0, line=None):
        self.runs = [r if isinstance(r, R) else R(r) for r in runs]
        self.align, self.before, self.after, self.line = align, before, after, line


ALIGN = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}
ANCHOR = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}


def style_run(run, r: R) -> None:
    f = run.font
    f.size = Pt(r.size)
    f.bold = r.bold
    f.italic = r.italic
    f.color.rgb = rgb(r.color)
    f.name = r.font
    latin = run._r.get_or_add_rPr().find(qn("a:latin"))
    if latin is not None and r.font in PANOSE:
        latin.set("panose", PANOSE[r.font])
        latin.set("pitchFamily", "34")
        latin.set("charset", "0")
    if r.spc:
        run._r.get_or_add_rPr().set("spc", str(int(r.spc * 100)))


def fill_frame(tf, paras, anchor="t", inset=(0, 0, 0, 0), wrap=True) -> None:
    tf.word_wrap = wrap
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = ANCHOR[anchor]
    tf.margin_left, tf.margin_top, tf.margin_right, tf.margin_bottom = (Inches(v) for v in inset)
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = ALIGN[p.align]
        if p.before:
            para.space_before = Pt(p.before)
        if p.after:
            para.space_after = Pt(p.after)
        if p.line:
            para.line_spacing = p.line
        for r in p.runs:
            run = para.add_run()
            run.text = r.text
            style_run(run, r)


def text(slide, x, y, w, h, paras, anchor="t", name=None, inset=(0, 0, 0, 0), wrap=True):
    if isinstance(paras, (P, R, str)):
        paras = [paras]
    paras = [p if isinstance(p, P) else P(p) for p in paras]
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    fill_frame(box.text_frame, paras, anchor, inset, wrap)
    if name:
        box.name = name
    return box


def _no_shadow(shape) -> None:
    shape.shadow.inherit = False


def _soft_shadow(shape, dark=False) -> None:
    spPr = shape._element.spPr
    eff = spPr.find(qn("a:effectLst"))
    if eff is None:
        eff = etree.SubElement(spPr, qn("a:effectLst"))
    for child in list(eff):
        eff.remove(child)
    sh = etree.SubElement(eff, qn("a:outerShdw"), blurRad="63500", dist="12700", dir="5400000",
                          algn="t", rotWithShape="0")
    clr = etree.SubElement(sh, qn("a:srgbClr"), val="000000" if dark else INK)
    etree.SubElement(clr, qn("a:alpha"), val="30000" if dark else "10000")


def box(slide, x, y, w, h, fill=WHITE, line=None, line_w=0.75, radius=0.0, shadow=False,
        name=None, dash=False, shape=None, dark=False):
    kind = shape or (MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE)
    shp = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if radius and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        shp.adjustments[0] = min(0.5, radius / min(w, h))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = rgb(fill)
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = rgb(line)
        shp.line.width = Pt(line_w)
        if dash:
            shp.line.dash_style = MSO_LINE.DASH
    if shadow:
        _soft_shadow(shp, dark)
    else:
        _no_shadow(shp)
    if name:
        shp.name = name
    return shp


def badge(slide, x, y, d, label, fill=RED, color=WHITE, size=14, name=None):
    """Filled circle with a centred label (numbers in lists)."""
    shp = box(slide, x, y, d, d, fill=fill, shape=MSO_SHAPE.OVAL, name=name)
    fill_frame(shp.text_frame, [P(R(label, size, color, bold=True, font=HEAD), align="c")], anchor="m")
    return shp


def fit_picture(slide, path, x, y, w, h, name=None):
    """Largest picture with the image's aspect ratio that fits in the box, centred."""
    from PIL import Image

    with Image.open(path) as im:
        ar = im.width / im.height
    pw, ph = (w, w / ar) if w / h <= ar else (h * ar, h)
    pic = slide.shapes.add_picture(str(path), Inches(x + (w - pw) / 2), Inches(y + (h - ph) / 2),
                                   Inches(pw), Inches(ph))
    if name:
        pic.name = name
    return pic, (x + (w - pw) / 2, y + (h - ph) / 2, pw, ph)


def figure(slide, rel, x, y, w, h, caption=None, name=None, cap_h=0.42):
    """A figure from results/figures on a quiet card, with a caption inside the card."""
    pad = 0.12
    box(slide, x, y, w, h, fill=FIGBG, line=LINE, radius=0.08, shadow=True, name=f"Card: {name or rel}")
    inner_h = h - 2 * pad - (cap_h if caption else 0)
    fit_picture(slide, ROOT / rel, x + pad, y + pad, w - 2 * pad, inner_h, name=name or rel)
    if caption:
        text(slide, x + 0.2, y + h - pad - cap_h, w - 0.4, cap_h, P(R(caption, 11, MUTED)),
             anchor="m", name=f"Caption: {name or rel}")


def eyebrow(slide, label, dark=False):
    """The deck's motif: a line-call red ball before a small-caps section label."""
    box(slide, M, 0.50, 0.15, 0.15, fill=RED, shape=MSO_SHAPE.OVAL, name="Motif: ball")
    text(slide, M + 0.27, 0.40, CW - 0.27, 0.34,
         P(R(label, 12, MUTED_DK if dark else BLUE, bold=True, spc=1.5)), anchor="m", name="Eyebrow")


def set_title(slide, title, dark=False, size=None):
    ph = slide.shapes.title
    tf = ph.text_frame
    tf.paragraphs[0].text = ""
    run = tf.paragraphs[0].add_run()
    run.text = title
    style_run(run, R(title, size or 36, WHITE if dark else INK, bold=True, font=HEAD))
    bp = tf._txBody.bodyPr
    for k in ("lIns", "tIns", "rIns", "bIns"):
        bp.set(k, "0")
    return ph


def footer(slide, n, dark=False):
    col = MUTED_DK if dark else MUTED
    text(slide, M, 7.06, 6.0, 0.26, P(R("COURTSIDE  ·  Gator Quant Hacks 2026  ·  Systematic Trading", 10, col)),
         anchor="m", name="Footer")
    tb = text(slide, SW - M - 1.0, 7.06, 1.0, 0.26, P(R("", 10, col), align="r"), anchor="m", name="Slide number")
    # replace the empty run with a live slide-number field
    p = tb.text_frame.paragraphs[0]._p
    for r in p.findall(qn("a:r")):
        p.remove(r)
    fld = etree.SubElement(p, qn("a:fld"), id="{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}", type="slidenum")
    rpr = etree.SubElement(fld, qn("a:rPr"), lang="en-US", sz="1000", dirty="0")
    sf = etree.SubElement(rpr, qn("a:solidFill"))
    etree.SubElement(sf, qn("a:srgbClr"), val=col)
    etree.SubElement(rpr, qn("a:latin"), typeface=BODY, panose=PANOSE[BODY], pitchFamily="34", charset="0")
    t = etree.SubElement(fld, qn("a:t"))
    t.text = str(n)


def notes(slide, script: str) -> None:
    slide.notes_slide.notes_text_frame.text = script.strip()


def autoplay_video(slide, pic, dur_ms: int, loop: bool) -> None:
    """Start the video automatically when the slide appears (optionally looping).

    python-pptx's add_movie only registers click-to-play; this writes the timing tree PowerPoint
    itself writes for Start: Automatically.
    """
    sld = slide._element
    old = sld.find(qn("p:timing"))
    spid = pic.shape_id
    rep = ' repeatCount="indefinite"' if loop else ""
    xml = f"""<p:timing xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:tnLst><p:par>
<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>
<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>
<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>
<p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>
<p:par><p:cTn id="5" presetID="1" presetClass="mediacall" presetSubtype="0" fill="hold" nodeType="afterEffect"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>
<p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr><p:cTn id="6" dur="{dur_ms}" fill="hold"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:cmd>
</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>
</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>
<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>
<p:video><p:cMediaNode vol="80000"><p:cTn id="7"{rep} fill="hold" display="0"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn>
<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cMediaNode></p:video>
</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"""
    new = etree.fromstring(re.sub(r">\s+<", "><", xml))
    if old is not None:
        old.addprevious(new)
        sld.remove(old)
    else:  # p:timing goes after p:transition / p:clrMapOvr, before p:extLst
        ext = sld.find(qn("p:extLst"))
        if ext is not None:
            ext.addprevious(new)
        else:
            sld.append(new)


def video(slide, rel_mp4, rel_poster, x, y, w, h, dur_s, loop, name):
    pic = slide.shapes.add_movie(str(ROOT / rel_mp4), Inches(x), Inches(y), Inches(w), Inches(h),
                                 poster_frame_image=str(ROOT / rel_poster), mime_type="video/mp4")
    pic.name = name
    autoplay_video(slide, pic, int(round(dur_s * 1000)), loop)
    return pic


def cell_borders(cell, bottom=None, top=None, w=0.75):
    """Hairline rules only: no verticals. Borders must precede the fill inside a:tcPr."""
    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        for el in tcPr.findall(qn(tag)):
            tcPr.remove(el)
    for i, (tag, col) in enumerate((("a:lnL", None), ("a:lnR", None), ("a:lnT", top), ("a:lnB", bottom))):
        ln = etree.Element(qn(tag), w=str(int(w * 12700)))
        if col:
            sf = etree.SubElement(ln, qn("a:solidFill"))
            etree.SubElement(sf, qn("a:srgbClr"), val=col)
        else:
            etree.SubElement(ln, qn("a:noFill"))
        tcPr.insert(i, ln)


def table(slide, x, y, col_w, row_h, rows, name, fills=None, header_fill=INK, rule=LINE):
    """rows: list of rows; each cell is a list of P (or a str). Row 0 is the header."""
    n_r, n_c = len(rows), len(col_w)
    gf = slide.shapes.add_table(n_r, n_c, Inches(x), Inches(y), Inches(sum(col_w)), Inches(sum(row_h)))
    gf.name = name
    tbl = gf.table
    tbl.first_row = False
    tbl.horz_banding = False
    sid = tbl._tbl.tblPr.find(qn("a:tableStyleId"))
    if sid is not None:
        sid.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # No Style, No Grid
    for j, cw in enumerate(col_w):
        tbl.columns[j].width = Inches(cw)
    for i, rh in enumerate(row_h):
        tbl.rows[i].height = Inches(rh)
    for i, row in enumerate(rows):
        for j, content in enumerate(row):
            cell = tbl.cell(i, j)
            if content is None:
                continue
            paras = content if isinstance(content, list) else [P(R(content, 14, WHITE if i == 0 else INK))]
            cell.text_frame.word_wrap = True
            for k, p in enumerate(paras):
                para = cell.text_frame.paragraphs[0] if k == 0 else cell.text_frame.add_paragraph()
                para.alignment = ALIGN[p.align]
                if p.after:
                    para.space_after = Pt(p.after)
                if p.before:
                    para.space_before = Pt(p.before)
                for r in p.runs:
                    run = para.add_run()
                    run.text = r.text
                    style_run(run, r)
            cell.margin_left = cell.margin_right = Inches(0.10)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell_borders(cell, bottom=rule if i < n_r - 1 else None)
            fill = header_fill if i == 0 else (fills[i][j] if fills and fills[i] and fills[i][j] else None)
            if fill:
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(fill)
            else:
                cell.fill.background()
    return tbl


def style_chart(ch, legend=True):
    ch.font.size = Pt(11)
    ch.font.name = BODY
    ch.font.color.rgb = rgb(MUTED)
    ch.has_title = False
    ch.has_legend = legend
    if legend:
        ch.legend.position = XL_LEGEND_POSITION.TOP
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(11)
        ch.legend.font.color.rgb = rgb(INK)
    va, ca = ch.value_axis, ch.category_axis
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = rgb(LINE)
    va.major_gridlines.format.line.width = Pt(0.5)
    va.format.line.fill.background()
    va.major_tick_mark = XL_TICK_MARK.NONE
    va.tick_labels.font.size = Pt(11)
    va.tick_labels.font.color.rgb = rgb(MUTED)
    ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW
    ca.major_tick_mark = XL_TICK_MARK.NONE
    ca.format.line.color.rgb = rgb(MUTED)
    ca.format.line.width = Pt(0.75)
    ca.tick_labels.font.size = Pt(11)
    ca.tick_labels.font.color.rgb = rgb(MUTED)


def color_series(plot, colors):
    for s, c in zip(plot.series, colors):
        s.format.fill.solid()
        s.format.fill.fore_color.rgb = rgb(c)
        s.format.line.fill.background()
        s.invert_if_negative = False


# --------------------------------------------------------------------------------------------
# Template: 16:9, theme colours and fonts, master title style
# --------------------------------------------------------------------------------------------


def setup_template(prs: Presentation) -> None:
    old_w = prs.slide_width
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    sx = prs.slide_width / old_w

    # Re-flow master and layout shapes that carry explicit positions (template is 4:3).
    for owner in [prs.slide_master, *prs.slide_layouts]:
        for shp in owner.shapes:
            if shp._element.xpath("./p:spPr/a:xfrm"):
                shp.left, shp.width = int(shp.left * sx), int(shp.width * sx)

    m = prs.slide_master
    m.background.fill.solid()
    m.background.fill.fore_color.rgb = rgb(OFF)
    for ph in m.placeholders:
        if ph.placeholder_format.type == PP_PLACEHOLDER.TITLE:
            ph.left, ph.top, ph.width, ph.height = Inches(M), Inches(0.80), Inches(CW), Inches(0.80)
            bp = ph.text_frame._txBody.bodyPr
            for k, v in (("lIns", "0"), ("tIns", "0"), ("rIns", "0"), ("bIns", "0"), ("anchor", "ctr")):
                bp.set(k, v)
    title_lvl = m._element.find(qn("p:txStyles")).find(qn("p:titleStyle")).find(qn("a:lvl1pPr"))
    title_lvl.set("algn", "l")
    d = title_lvl.find(qn("a:defRPr"))
    d.set("sz", "3600")
    d.set("b", "1")

    # Theme: palette + fonts (major = Arial Narrow, minor = Arial).
    theme = m.part.part_related_by(RT.THEME)
    root = etree.fromstring(theme.blob)
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    root.set("name", "Courtside")
    cs = root.find(f"{a}themeElements/{a}clrScheme")
    cs.set("name", "Courtside")
    scheme = {"dk1": INK, "lt1": WHITE, "dk2": BLUE, "lt2": OFF, "accent1": BLUE, "accent2": RED,
              "accent3": INK, "accent4": "7D8FA3", "accent5": "8FB0D1", "accent6": "E39A8C",
              "hlink": BLUE, "folHlink": "566676"}
    for k, v in scheme.items():
        slot = cs.find(f"{a}{k}")
        for child in list(slot):
            slot.remove(child)
        etree.SubElement(slot, f"{a}srgbClr", val=v)
    fs = root.find(f"{a}themeElements/{a}fontScheme")
    fs.set("name", "Courtside")
    for which, face in (("majorFont", HEAD), ("minorFont", BODY)):
        latin = fs.find(f"{a}{which}/{a}latin")
        latin.attrib.clear()
        latin.set("typeface", face)
        latin.set("panose", PANOSE[face])
    theme._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def add_sections(prs: Presentation, sections: list[tuple[str, int]]) -> None:
    """PowerPoint sections (p14:sectionLst). sections = [(name, number_of_slides), ...]."""
    p14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
    pres = prs.part._element
    ids = [s.get("id") for s in pres.find(qn("p:sldIdLst"))]
    assert sum(n for _, n in sections) == len(ids)
    ext_lst = pres.find(qn("p:extLst"))
    if ext_lst is None:
        ext_lst = etree.SubElement(pres, qn("p:extLst"))
    ext = etree.SubElement(ext_lst, qn("p:ext"), uri="{521415D9-36F7-43E2-AB2F-B90AF26B5E84}")
    lst = etree.SubElement(ext, f"{{{p14}}}sectionLst", nsmap={"p14": p14})
    k = 0
    for i, (name, n) in enumerate(sections):
        sec = etree.SubElement(lst, f"{{{p14}}}section", name=name,
                               id="{%08X-5D1E-4C2B-9A11-C0A7F1D0%04X}" % (0xC0DE0000 + i, i))
        sl = etree.SubElement(sec, f"{{{p14}}}sldIdLst")
        for sid in ids[k:k + n]:
            etree.SubElement(sl, f"{{{p14}}}sldId", id=sid)
        k += n


# --------------------------------------------------------------------------------------------
# Slides
# --------------------------------------------------------------------------------------------


def new_slide(prs, dark=False):
    layout = next(l for l in prs.slide_layouts if l.name == "Title Only")
    s = prs.slides.add_slide(layout)
    if dark:
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = rgb(INK)
    return s



# --------------------------------------------------------------------------------------------
# Talk timing: ten main slides, 4:45 in total. Every slide's notes start with its time window.
# --------------------------------------------------------------------------------------------
DUR_S = [25, 30, 30, 40, 35, 30, 35, 25, 25, 10]
TALK_S = 4 * 60 + 45
assert sum(DUR_S) == TALK_S, sum(DUR_S)


def window(i: int) -> str:
    a, b = sum(DUR_S[:i]), sum(DUR_S[:i + 1])
    return f"[{a // 60}:{a % 60:02d} to {b // 60}:{b % 60:02d}, {DUR_S[i]} s]"


MONTH_ABBR = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun",
              "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}


def month_year(s: str) -> str:
    return f"{MONTH_ABBR[s[5:7]]} {s[:4]}"


def rx(rel: str, keys: tuple, pattern: str, fmt=lambda g: g):
    """A number quoted inside a string field of a results file."""
    m = re.search(pattern, str(raw(rel, *keys)))
    if not m:
        raise Missing(f"{key_str(rel, *keys)} ~ /{pattern}/")
    return fmt(m.group(1))


def VR(rel: str, *keys, f=cents, how=None):
    """(float or None, text): a value for a chart, recorded in the manifest like any other number."""
    t = V(rel, *keys, f=f, how=how)
    return (opt(rel, *keys), t)


def stat(slide, x, y, w, big, cap, col=BLUE, big_size=44, cap_size=13, big_h=0.78, cap_h=0.72, name="Stat"):
    text(slide, x, y, w, big_h, P(R(big, big_size, col, bold=True, font=HEAD)), anchor="b", name=f"{name} value")
    text(slide, x, y + big_h + 0.02, w, cap_h, P(R(cap, cap_size, INK)), name=f"{name} caption")


def label(slide, x, y, w, t, col=BLUE, dark=False):
    text(slide, x, y, w, 0.3, P(R(t, 12, MUTED_DK if dark else col, bold=True, spc=1.4)), anchor="m",
         name=f"Label: {t[:24]}")


def verdict_fill(v: str):
    v = v.upper()
    if v.startswith("PASS"):
        return BLUE_TINT
    if v.startswith(("FAIL", "NEG")):
        return RED_TINT
    return None


def verdict_color(v: str):
    v = v.upper()
    if v.startswith("PASS"):
        return BLUE
    if v.startswith(("FAIL", "NEG")):
        return RED
    return MUTED


def poster_for(mp4: Path) -> Path | None:
    """A poster frame for a video: <name>.png beside it, else one frame extracted with ffmpeg."""
    png = mp4.with_suffix(".png")
    if png.exists():
        return png
    if shutil.which("ffmpeg"):
        out = Path(tempfile.mkdtemp()) / (mp4.stem + "_poster.png")
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(mp4), "-frames:v", "1", str(out)],
                           capture_output=True, timeout=60)
        if r.returncode == 0 and out.exists():
            return out
    return None


# --------------------------------------------------------------------------------------------
# Main slides
# --------------------------------------------------------------------------------------------


def s01_title(prs, n):
    slide_ctx(f"{n} Title")
    s = new_slide(prs, dark=True)
    eyebrow(s, "GATOR QUANT HACKS 2026  ·  SYSTEMATIC TRADING", dark=True)
    ph = set_title(s, "COURTSIDE", dark=True, size=60)
    ph.left, ph.top, ph.width, ph.height = Inches(M), Inches(0.98), Inches(5.1), Inches(1.12)
    text(s, M, 2.25, 5.1, 2.05, [
        P(R("Every point", 36, WHITE, bold=True, font=HEAD), line=0.95),
        P(R("moves a market.", 36, WHITE, bold=True, font=HEAD), line=0.95),
        P(R("Who gets paid?", 36, RED, bold=True, font=HEAD), line=0.95),
    ], name="Hook")
    matches = V(F_SUM, "universe", "matches", f=intc)
    vol = V(F_SUM, "universe", "volume_usd", f=usd_b)
    text(s, M, 4.45, 5.1, 0.75, P(
        R(matches, 38, WHITE, bold=True, font=HEAD), R(" matches   ", 18, MUTED_DK, font=HEAD),
        R(vol, 38, WHITE, bold=True, font=HEAD), R(" traded", 18, MUTED_DK, font=HEAD)),
        anchor="b", name="Universe")
    thr = D(lambda: rx(F_RISK, ("universe_volume_filter", "note"), r">= (\$\d+k)"),
            key_str(F_RISK, "universe_volume_filter", "note") + "  [volume threshold quoted in the note field]")
    first = V(F_NM, "holdout", "first_start", f=month_year)
    last = V(F_NM, "holdout", "last_start", f=month_year)
    text(s, M, 5.3, 5.0, 0.62, P(R(f"Every resolved Polymarket ATP/WTA singles moneyline with lifetime volume "
                                   f"≥ {thr}, {first} – {last}", 13, MUTED_DK)), name="Universe caption")
    box(s, M, 6.1, 4.3, 0.4, fill=INK_2, radius=0.08, name="Paper chip")
    text(s, M, 6.1, 4.3, 0.4, P(R("PAPER ONLY  ·  PUBLIC DATA  ·  NO ORDERS SENT", 11.5, "F07A66", bold=True,
                                  spc=1.2), align="c"), anchor="m", name="Paper only")
    vx, vw = 6.05, SW - M - 6.05
    vh = vw * 9 / 16
    box(s, vx - 0.04, 1.05 - 0.04, vw + 0.08, vh + 0.08, fill=INK_2, radius=0.06, name="Video frame")
    mp4 = ROOT / "results/viz/courtside_replay.mp4"
    video(s, "results/viz/courtside_replay.mp4", "results/viz/courtside_replay.png", vx, 1.05, vw, vh,
          video_duration(mp4, 13.0), loop=True, name="Video: Hawk-Eye-style replay")
    o0 = V(F_VIZ, "tape", "out0", f=lambda x: x.split()[-1])
    o1 = V(F_VIZ, "tape", "out1", f=lambda x: x.split()[-1])
    tdate = V(F_VIZ, "tape", "date")
    text(s, vx, 1.05 + vh + 0.12, vw, 0.5, P(R(
        f"Real Polymarket tape ({o0} v {o1}, {tdate}) beside a simulated Hawk-Eye-style call", 12, MUTED_DK)),
        name="Video caption")
    text(s, M, 7.0, SW - 2 * M, 0.34, P(R(REPO_SHORT, 12, MUTED_DK, font=MONO)), anchor="m", name="Repo")
    move = D(lambda: f"{100 * raw(F_LEVER, 'atp', 'total_abs_move_per_match') / raw(F_LEVER, 'atp', 'points_per_match'):.1f}¢",
             key_str(F_LEVER, "atp") + "  [total_abs_move_per_match / points_per_match, per $1 share]")
    swing = V(F_LEVER, "atp", "mean_abs_leverage", f=lambda x: f"{100 * x:.1f}¢",
              how="swing in fair value between winning and losing the point")
    notes(s, f"""
{window(0)}  TITLE + HOOK

Every tennis point moves a prediction market: on average a one-dollar share moves about {move} per point, and the point is worth a {swing} swing between winning and losing it.

So we asked: when the price jumps, who is on the other side, and who gets paid?

We took every resolved ATP and WTA moneyline on Polymarket for a year: {matches} matches, {vol} traded, every print classified by side, net of its own fee. Everything you will see is public data and paper trading. No order was ever sent.

[The video pairs a real tape ({o0} v {o1}, {tdate}) with a simulated groundstroke; it is not that point's line call. Blue dots are the fast tier.]
[PRE-FLIGHT: open the .pptx in PowerPoint (not Keynote, Google Slides or the PDF) so the videos autoplay. Bring results/viz/courtside_replay.mp4 and the slide 4 video as separate files; if a video fails, talk over its poster frame.]
[Every number in this deck is read from a results file at build time; the hidden slides at the end list each one with its source key.]
""")


def s02_tiers(prs, n):
    slide_ctx(f"{n} Economics")
    s = new_slide(prs)
    eyebrow(s, "01  ·  ECONOMIC FOUNDATION")
    set_title(s, "A point ends in tiers. Slow tiers pay fast ones")

    def he(lead):
        def fn():
            row = next(r for r in raw(F_SUM, "tracking_tennis_physics") if r["lead_ms"] == lead)
            return f"±{row['pred_err_sd_cm']:.1f} cm"
        return D(fn, f"{F_SUM} :: tracking_tennis_physics > [lead_ms={lead}] > pred_err_sd_cm")

    he100 = he(100)
    vis = D(lambda: ms0(next(r for r in raw(F_ENG_DEMO, "latency_budget") if r["stage"].startswith("vision"))["ms"]),
            f"{F_ENG_DEMO} :: latency_budget > [stage 'vision…'] > ms  [processing only; laptop benchmark]")
    book = V(F_T0, "timing", "median_t_reprice_minus_t_stamp_s", f=sec2)
    lag = V(F_T0, "timing", "calibrated_stamp_lag_s (inference)", f=lambda x: f"≈{x:.1f} s",
            how="post hoc inference; assumes courtside humans")
    espn = V(F_DECAY, "latency_inputs", "espn_behind_book_s", f=lambda x: f"+{x:.1f} s")
    h4_share = V(F_SUM, "h4", "share_book_first", f=frac_pct0)
    h4_n = V(F_SUM, "h4", "n", f=intc)
    h4_med = V(F_SUM, "h4", "median_lead_s", f=lambda x: f"{x:.1f} s")
    streams = V(F_DECAY, "latency_inputs", "stream_delay_s_assumed", f=lambda p: f"+{p[0]:.0f}–{p[1]:.0f} s")
    rungs = [
        ("TIER 0", "Ball tracking", f"our vision ~{vis}/call (laptop; no courtside camera)", "before the bounce",
         f"{he100} at 100 ms (simulated)", RED, WHITE, "F6D3CC"),
        ("TIER 1", "Chair umpire", "", "at the bounce", "", INK, WHITE, MUTED_DK),
        ("TIER 2", "Market makers", "the book reprices", book, "vs the official stamp (median)", BLUE, WHITE,
         "C9D9EA"),
        ("TIER 3", "Official feed", "umpire-entered point stamp", "reference",
         f"1–3 s after the bounce, unmeasured (post hoc inference {lag})",
         "3F6E9C", WHITE, "C9D9EA"),
        ("TIER 4", "TV and public scores", f"book first on {h4_share} of {h4_n} points, median {h4_med}", espn,
         "ESPN behind the book", "C9D5E1", INK, MUTED),
        ("TIER 5", "Streams", "the slowest money", streams, "assumed, not measured", "E4EAF0", INK, MUTED),
    ]
    x0, y0, step, rh, gap, right = M, 1.74, 0.3, 0.66, 0.08, 8.55
    for i, (tag, who, sub, when, when_sub, fill, fg, fg2) in enumerate(rungs):
        x, y = x0 + i * step, y0 + i * (rh + gap)
        w = right - x
        box(s, x, y, w, rh, fill=fill, radius=0.08, name=f"Ladder rung {i}")
        paras = [P(R(tag + "  ", 10.5, fg2, bold=True, spc=1.2), R(who, 19, fg, bold=True, font=HEAD), line=0.9)]
        if sub:
            paras.append(P(R(sub, 11, fg2)))
        text(s, x + 0.2, y + 0.02, w - 3.1, rh - 0.04, paras, anchor="m", name=f"Ladder who {i}")
        wp = [P(R(when, 19, fg, bold=True, font=HEAD), align="r", line=0.9)]
        if when_sub:
            wp.append(P(R(when_sub, 10.5, fg2), align="r"))
        text(s, x + w - 3.0, y + 0.02, 2.82, rh - 0.04, wp, anchor="m", name=f"Ladder when {i}")
    text(s, M, 6.25, right - M, 0.7, P(R(
        "Tier 0: physics simulation of Hawk-Eye-class tracking. Tiers 2–4: live books vs the WTA's public "
        "point log, read after the fact (stamp-to-bounce lag is unmeasured; the post hoc inference assumes "
        "courtside humans). Streams: assumption.",
        10.5, MUTED)), name="Ladder source")

    cx, cw = 9.05, SW - M - 9.05
    label(s, cx, 1.74, cw, "WHO PAYS WHOM")
    travel = V(F_LEVER, "atp", "total_abs_move_per_match", f=lambda x: f"${x:.1f}")
    pts = V(F_LEVER, "atp", "points_per_match", f=lambda x: f"{x:.0f}")
    move = D(lambda: f"{100 * raw(F_LEVER, 'atp', 'total_abs_move_per_match') / raw(F_LEVER, 'atp', 'points_per_match'):.1f}¢",
             key_str(F_LEVER, "atp") + "  [total_abs_move_per_match / points_per_match, per $1 share]")
    swing = V(F_LEVER, "atp", "mean_abs_leverage", f=lambda x: f"{100 * x:.1f}¢",
              how="swing in fair value between winning and losing the point")
    stat(s, cx, 1.95, cw, travel, f"total |fair-value move| per $1 share over a simulated ATP best-of-3 ({pts} "
                                  f"points): {move} realised move per point on average ({swing} swing between "
                                  f"winning and losing it)", big_size=50, big_h=0.85, cap_h=0.75, name="Leverage")
    reg = D(lambda: next(iter(raw(F_RISK, "regime", "burned_oos"))),
            key_str(F_RISK, "regime", "burned_oos") + "  [regime key: order delay / taker fee rate]")
    delay, fee = (reg.split("/") + [PENDING])[:2] if reg != PENDING else (PENDING, PENDING)
    delay = delay.replace("s", " s")
    stat(s, cx, 3.62, cw, f"{delay} · {fee}", "Polymarket's order delay on every marketable sports order (so "
                                             "makers can reprice) and its taker fee rate, × p(1−p)",
         col=RED, big_size=50, big_h=0.85, cap_h=0.75, name="Venue")
    box(s, cx, 5.3, cw, 0.95, fill=INK, radius=0.1, name="Takeaway panel")
    text(s, cx + 0.22, 5.3, cw - 0.44, 0.95, P(R("The gaps are physical, so they persist.", 19, WHITE, bold=True,
                                                 font=HEAD)), anchor="m", name="Takeaway")
    footer(s, n)
    notes(s, f"""
{window(1)}  ECONOMIC FOUNDATION: THE INFORMATION LADDER

Why does anyone lose? Because a point ends in tiers.

Ball tracking knows where the ball lands before it bounces. The umpire knows at the bounce. Market makers reprice the book {book} relative to the official stamp, which an umpire types in after the ball lands. TV and public scores trail the book: ESPN by {espn}; in our pre-registered live test the book moved first on {h4_share} of {h4_n} points. Streams are slower still.

Over a match a one-dollar share's fair value travels {travel} in total, about {move} per point. Whoever trades on an older tier sells to someone faster. The venue admits it: it holds every marketable order {delay} so makers can reprice, and charges takers {fee} times p(1−p).

[If asked how ESPN's lag was measured: we bought no official ATP/WTA data feed and no trading result uses one; the free WTA website and ESPN scoreboard were recorded on 2026-10-03 only to time their lag (research/v2/latency/RESULTS.md).]
[If asked about the clocks: the WTA stamp is the public point log, 1 s resolution, read after the fact; its lag to the bounce is unmeasured. The post hoc inference from fast-tier prints ({lag}) assumes courtside humans with a 0.25 s reaction; it is not a measurement. ATP has no public official point clock.]
[Sources: {F_T0} timing; {F_DECAY} latency_inputs; {F_SUM} h4 and tracking_tennis_physics; {F_LEVER} atp; {F_RISK} regime.]
""")


def s03_evidence(prs, n):
    slide_ctx(f"{n} Evidence")
    s = new_slide(prs)
    eyebrow(s, "02  ·  EVIDENCE")
    try:
        wf_is, wf_oos = wf_months()
        WF = wf_is + wf_oos
    except Missing:
        wf_is, wf_oos, WF = [], [], []
    every = WF and all(m["net30_c"] > 0 for m in WF) and all(m["follow_res_c"] < 0 for m in WF)
    set_title(s, "The fast tier wins every month. 3 s later loses" if every else
              "The fast tier vs a copy 3 s later, by month")
    n_is, n_oos = len(wf_is), len(wf_oos)
    pos = D(lambda: f"{sum(m['net30_c'] > 0 for m in WF)}/{len(WF)}" if WF else PENDING,
            WF_SRC + "  [months with fast-tier net30_c > 0]")
    pos_oos = D(lambda: f"{sum(m['net30_c'] > 0 for m in wf_oos)}/{n_oos}" if WF else PENDING,
                f"{F_SUM} :: oos > h6_walkforward  [months with net30_c > 0]")
    copy_neg = D(lambda: f"{sum(m['follow_res_c'] < 0 for m in WF)}/{len(WF)}" if WF else PENDING,
                 WF_SRC + "  [months with follow_res_c < 0: same trades entered ~3 s later, held]")
    oth_neg = D(lambda: f"{sum(m['others_net30_c'] < 0 for m in WF)}/{len(WF)}" if WF else PENDING,
                WF_SRC + "  [months with others_net30_c < 0]")
    for per, months_ in (("is", wf_is), ("oos", wf_oos)):  # every bar value is a number on the slide
        for m in months_:
            for k in ("net30_c", "others_net30_c", "follow_res_c"):
                _record(cents(m[k]), f"{F_SUM} :: {per} > h6_walkforward > [month={m['month']}] > {k}")

    cw_chart = 7.75
    label(s, M, 1.72, cw_chart, "30 S NET ¢/SHARE BY MONTH, WALK-FORWARD (PALE = OUT OF SAMPLE)")
    if WF:
        cd = CategoryChartData()
        cd.categories = [MONTH_ABBR[m["month"][5:]] for m in WF]
        cd.add_series("Fast tier (0–3 s)", [round(m["net30_c"], 2) for m in WF])
        cd.add_series("Everyone else, same 0–3 s", [round(m["others_net30_c"], 2) for m in WF])
        cd.add_series("Fast tier's trades copied ~3 s later", [round(m["follow_res_c"], 2) for m in WF])
        gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(M - 0.05), Inches(2.02),
                                Inches(cw_chart), Inches(3.55), cd)
        gf.name = "Chart: walk-forward months"
        ch = gf.chart
        style_chart(ch)
        plot = ch.plots[0]
        plot.gap_width = 55
        plot.overlap = 0
        color_series(plot, [BLUE, "7D8FA3", RED])
        for ser, pale in zip(plot.series, ("9DB8D3", "C3CCD6", "EBA79C")):
            for k in range(n_is, len(WF)):
                pt = ser.points[k]
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = rgb(pale)
                pt.format.line.fill.background()
        va = ch.value_axis
        va.tick_labels.number_format = '0"¢"'
        va.tick_labels.number_format_is_linked = False
    else:
        text(s, M, 2.5, cw_chart, 1.0, P(R("Walk-forward months: pending", 20, MUTED)), name="Chart pending")
    text(s, M, 5.6, cw_chart, 0.45, P(R(
        "30 s markout per taker print, net of its fee. Wallets picked each month from earlier months only. "
        "Onset-aligned event study; tradable numbers (slide 5) use the causal window.", 10.5, MUTED)),
        name="Chart caption")

    cx = M + cw_chart + 0.35
    cw = SW - M - cx
    stat(s, cx, 1.62, cw, pos, f"months the fast tier made money: {n_is} in sample + {pos_oos} out of sample. "
                               "H6 came after the in-sample wallet study, so only the out-of-sample months test it",
         big_size=54, big_h=0.92, cap_h=1.0, name="Months")
    stat(s, cx, 3.6, cw, copy_neg, f"months copying their exact trades ~3 s later lost money "
                                   f"(everyone else in the window: {oth_neg} negative)",
         col=RED, big_size=54, big_h=0.92, cap_h=0.62, name="Copy")
    u2_is = V(F_EXP, "fast_minus_others_u2", "u2_is", "fast_minus_others_c", f=cents)
    u2_oos = V(F_EXP, "fast_minus_others_u2", "u2_oos", "fast_minus_others_c", f=cents)
    u2_oos_ci = V(F_EXP, "fast_minus_others_u2", "u2_oos", "ci_c", f=ci)
    u2_n = V(F_EXP, "universe", "u2_markets", f=intc)
    text(s, cx, 5.25, cw, 0.8, [
        P(R("BLIND, ON UNSEEN MARKETS", 10.5, BLUE, bold=True, spc=1.2)),
        P(R(f"Fast tier minus everyone else on {u2_n} never-examined markets: {u2_is} in sample, "
            f"{u2_oos} {u2_oos_ci} out of sample.", 12, INK)),
    ], name="U2 gap")
    box(s, M, 6.15, CW, 0.78, fill=INK, radius=0.1, name="Takeaway panel")
    text(s, M + 0.3, 6.15, CW - 0.6, 0.78, P(
        R("Same wallets, same trades, 3 s later: negative.  ", 21, WHITE, bold=True, font=HEAD),
        R("The edge is speed.", 21, "F07A66", bold=True, font=HEAD)), anchor="m", name="Takeaway")
    footer(s, n)
    notes(s, f"""
{window(2)}  EVIDENCE: WHO GETS PAID

Every taker print, by seconds since the point, marked out 30 seconds later, net of fees.

A small group of wallets, the fast tier, trades within three seconds and wins. Picked each month from earlier months only, it made money in {pos} months: {n_is} in sample, where we found it, and {pos_oos} out of sample, the real test. Everyone else in the same window lost in {oth_neg} months.

The control: copy their exact trades about three seconds later and you lose in {copy_neg} months. So it is not who they are. The edge is speed.

And it replicates blind on {u2_n} markets we had never looked at: fast tier minus everyone else {u2_is} in sample, {u2_oos} out of sample.

[Honest framing if asked: H6 was written after the in-sample wallet study (DEVIATIONS D4, D5), so only the out-of-sample months test it. These are onset-aligned windows, an ex-post event study; every tradable v2 number uses the causal window (D9).]
[Sources: {WF_SRC}; {F_EXP} fast_minus_others_u2.]
""")


def s04_cv(prs, n):
    slide_ctx(f"{n} CV in action")
    s = new_slide(prs)
    eyebrow(s, "03  ·  INNOVATION")
    set_title(s, "Our CV calls the point before the ball lands")
    eng = ROOT / "results/engine/engine_live_demo.mp4"
    poster = poster_for(eng) if valid_mp4(eng) else None
    vw = 7.55
    vh = vw * 9 / 16
    box(s, M - 0.04, 1.85 - 0.04, vw + 0.08, vh + 0.08, fill=INK, radius=0.06, name="Video frame")
    if valid_mp4(eng) and poster:
        pic = s.shapes.add_movie(str(eng), Inches(M), Inches(1.85), Inches(vw), Inches(vh),
                                 poster_frame_image=str(poster), mime_type="video/mp4")
        pic.name = "Video: COURTSIDE engine demo"
        autoplay_video(s, pic, int(round(video_duration(eng, 30.0) * 1000)), loop=False)
        which = ("COURTSIDE engine demo (results/engine/engine_live_demo.mp4): streaming vision on held-out "
                 "frames → paper order. Paper only.")
    else:
        dur = opt(F_TRACK_DEMO, "supercut", "duration_s", default=None) or \
            video_duration(ROOT / "results/tracking/demo/supercut.mp4", 15.0)
        video(s, "results/tracking/demo/supercut.mp4", "results/tracking/demo/supercut.png", M, 1.85, vw, vh,
              dur, loop=False, name="Video: real-footage early calls")
        which = "Held-out games, frozen model, run on HiPerGator; clips selected for presentation."
    text(s, M, 1.85 + vh + 0.1, vw, 0.66, [
        P(R("Real 120 fps table-tennis footage: OpenTTGames (lab.osai.ai), adapted (overlays added), "
            "CC BY-NC-SA 4.0. ", 11, INK, bold=True),
          R(which, 11, MUTED)),
    ], name="Video caption and credit")

    ec = ("early_call", "precision_recall_test_snapshot", "50ms")
    tp_t = V(F_TRACK, *ec, "tp", f=intc)
    calls = D(lambda: f"{raw(F_TRACK, *ec, 'tp')}/{raw(F_TRACK, *ec, 'tp') + raw(F_TRACK, *ec, 'fp')}",
              key_str(F_TRACK, *ec) + "  [tp/(tp+fp)]")
    n_miss = D(lambda: intc(raw(F_TRACK, *ec, "tp") + raw(F_TRACK, *ec, "fn")), key_str(F_TRACK, *ec) + "  [tp+fn]")
    recall = V(F_TRACK, *ec, "recall", f=frac_pct0)
    lb = V(F_TRACK, *ec, "precision_wilson95", f=lambda p: frac_pct0(p[0]))
    # Ball detection: one source for deck and video, the held-out test set (tracking/summary.json, tracked)
    def det(field, f):
        def fn():
            row = next(r for r in raw(F_TRACK, "detection_accuracy_pooled")
                       if r["split"] == "test" and r["source"] == "tracked")
            return f(row[field])
        return D(fn, f"{F_TRACK} :: detection_accuracy_pooled > [split=test, source=tracked] > {field}")
    det5 = det("within5", frac_pct1)
    det_rec = det("recall", frac_pct1)
    det_n = det("n_visible", intc)
    lead_med = V(F_TRACK, "early_call", "miss_first_call_lead_test_ms", "median", f=ms0)
    lead_max = V(F_TRACK_DEMO, "clips", 0, "call_lead_ms", f=ms0)

    def vis_lat(field):
        def fn():
            row = next(r for r in raw(F_ENG_DEMO, "latency_budget") if r["stage"].startswith("vision"))
            return ms0(row[field])
        return D(fn, f"{F_ENG_DEMO} :: latency_budget > [stage 'vision…'] > {field}")
    lat50, lat90 = vis_lat("ms"), vis_lat("p90")
    fps = V(F_ENG_BENCH, "summary", 0, "fps_sustained", f=lambda x: f"{x:.0f} fps")
    # The deployable numbers are the LIVE CAUSAL engine's (results/engine/online_vs_offline.json); the offline
    # evaluation above used a look-ahead feature (engine/README.md, Known gaps) and is shown only as such.
    A = ("runs", OVO_RUN, "A_engine_calls")
    e_tp = V(F_OVO, *A, "online", "50ms", "tp", f=intc)
    e_calls = D(lambda: f"{raw(F_OVO, *A, 'online', '50ms', 'tp')}/"
                        f"{raw(F_OVO, *A, 'online', '50ms', 'tp') + raw(F_OVO, *A, 'online', '50ms', 'fp')}",
                key_str(F_OVO, *A, "online", "50ms") + "  [tp/(tp+fp), live causal engine]")
    e_nmiss = V(F_OVO, *A, "miss_first_call_lead_ms", "n_miss", f=intc)
    e_lead = V(F_OVO, *A, "miss_first_call_lead_ms", "median", f=lambda x: f"{x:g} ms")
    e_lb = V(F_OVO, *A, "online", "50ms", "precision_wilson95", f=lambda p: frac_pct0(p[0]))
    hook = D(lambda: ms0(next(f_ for f_ in raw(F_OVO, "runs", OVO_RUN, "flights_called_or_miss")
                              if f_["video"] == "test_2" and f_["f_net"] == 2819)["lead_engine_call_ms"]),
             key_str(F_OVO, "runs", OVO_RUN, "flights_called_or_miss") + "  [video=test_2, f_net=2819] > lead_engine_call_ms")
    H = ("headline", OVO_RUN, "stream")
    g50 = V(F_OVO, *H, "after_startup", "call_ready_ms", "p50", f=lambda x: f"{x:.1f} ms")
    g99 = V(F_OVO, *H, "after_startup", "call_ready_ms", "p99", f=lambda x: f"{x:.1f} ms")
    gfr = V(F_OVO, *H, "frames", f=intc)
    gdr = V(F_OVO, *H, "dropped", f=intc)
    cx = M + vw + 0.45
    cw = SW - M - cx
    stat(s, cx, 1.5, cw, e_calls, f"live causal engine on held-out games: every miss call it made was right. It called "
                                  f"{e_tp} of {e_nmiss} misses before contact (median lead {e_lead}); 95% lower bound "
                                  f"{e_lb}. The offline {calls} used a look-ahead feature (engine/README.md)",
         col=RED, big_size=48, big_h=0.8, cap_h=1.15, name="Calls")
    stat(s, cx, 3.55, cw, det5, f"of {det_n} labelled held-out test frames within 5 px (ball found in {det_rec})",
         big_size=44, big_h=0.78, cap_h=0.55, name="Tracking")
    stat(s, cx, 4.95, cw, g50, f"GPU call-ready, median (p99 {g99}), 120 fps on one L4; {gdr} of {gfr} frames "
                               f"dropped. Laptop: {fps}",
         col=INK, big_size=44, big_h=0.78, cap_h=0.85, name="Latency")
    footer(s, n)
    notes(s, f"""
{window(3)}  INNOVATION: CALLING THE POINT BEFORE IT LANDS

Can anyone reach tier zero? This is real 120-frame-per-second table-tennis footage, OpenTTGames, a public labelled high-speed set; table tennis itself is not tradable on a liquid book, tennis video at this frame rate is not public.

Our tracker finds the ball within five pixels on {det5} of labelled held-out frames. Run live and causally on one GPU, at 120 frames a second with {gdr} frames dropped, the engine is call-ready in {g50}. On held-out games it called {e_tp} of {e_nmiss} misses before contact, a median {e_lead} early, and every call was right; with four calls the lower bound on precision is {e_lb}. It is cautious.

The offline evaluation said {calls} at fifty milliseconds, but it used a feature that looked ahead over the whole flight. The live engine is the deployable number, and our engine README documents the gap. The lead comes from frame rate and cameras, so it lives in the venue.

[If asked about the laptop: it sustains {fps}, not 120, under load; HiPerGator GPU timing is in hpg/engine_vision.sbatch. Footage credit: OpenTTGames, adapted (overlays added), CC BY-NC-SA 4.0 (non-commercial; credited on the slide).]
[If asked about the offline numbers ({calls} at 50 ms, recall {recall}, lower bound {lb}; the {lead_max} clip): offline, with a look-ahead feature. The live causal engine's call on that clip came {hook} early (online_vs_offline.json flights_called_or_miss test_2/2819). Laptop vision processing: {lat50} per call (p90 {lat90}).]
[Reproducing the calls needs models/vision/frozen_call_model.pkl, which is not in git; hpg/engine_vision.sbatch rebuilds it.]
[Sources: {F_OVO} runs.{OVO_RUN}.A_engine_calls and headline; {F_TRACK} early_call (offline); {F_ENG_DEMO} vision + latency_budget; {F_ENG_BENCH} summary.]
""")


def s05_backtest(prs, n):
    slide_ctx(f"{n} Backtest")
    s = new_slide(prs)
    eyebrow(s, "04  ·  PERFORMANCE")
    set_title(s, "v2: in sample vs out of sample, and costs doubled")
    box(s, M, 1.66, CW, 0.38, fill=RED_TINT, radius=0.06, name="Fills strip")
    text(s, M + 0.18, 1.66, CW - 0.36, 0.38, P(
        R("Paper book on the fast tier's own fills: ", 12, RED, bold=True),
        R("it prices the opportunity at their speed, not our execution. Out of sample is burned (v2 was designed "
          "after v1 failed there) and labelled non-blind.", 12, INK)), anchor="m", name="Fills caveat")

    cats = ["Fast-tier fills", "+½ tick", "+1 tick", "Fees ×2", "All costs ×2"]
    srcs_is = [(F_CAUSAL, IS0, "per_share_c"), (F_CAUSAL, IS5, "per_share_c"), (F_CAUSAL, IS10, "per_share_c"),
               (F_COST, "is_eval/fee_x2", "per_share_c"), (F_COST, "is_eval/costs_x2", "per_share_c")]
    srcs_os = [(F_CAUSAL, OS0, "per_share_c"), (F_CAUSAL, OS5, "per_share_c"), (F_CAUSAL, OS10, "per_share_c"),
               (F_COST, "burned_oos/fee_x2", "per_share_c"), (F_COST, "burned_oos/costs_x2", "per_share_c")]
    vis = [VR(*a) for a in srcs_is]
    vos = [VR(*a) for a in srcs_os]
    label(s, M, 2.16, 5.6, "NET ¢/SHARE, HELD TO RESOLUTION, BY COST CASE")
    if all(v[0] is not None for v in vis + vos):
        cd = CategoryChartData()
        cd.categories = cats
        cd.add_series("In sample", [round(v[0], 2) for v in vis])
        cd.add_series("Burned OOS (non-blind)", [round(v[0], 2) for v in vos])
        gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(M - 0.05), Inches(2.45), Inches(5.65),
                                Inches(3.75), cd)
        gf.name = "Chart: v2 by cost case"
        ch = gf.chart
        style_chart(ch)
        plot = ch.plots[0]
        plot.gap_width = 60
        plot.overlap = 0
        color_series(plot, [BLUE, RED])
        plot.has_data_labels = True
        dl = plot.data_labels
        dl.number_format = '+0.00;−0.00'
        dl.number_format_is_linked = False
        dl.position = XL_LABEL_POSITION.OUTSIDE_END
        dl.font.size = Pt(11)
        dl.font.bold = True
        dl.font.color.rgb = rgb(INK)
        va = ch.value_axis
        va.tick_labels.number_format = '0.0"¢"'
        va.tick_labels.number_format_is_linked = False
    else:
        text(s, M, 3.0, 5.6, 1.0, P(R("Cost-case chart: pending", 20, MUTED)), name="Chart pending")
    days_is = V(F_CAUSAL, IS0, "days", f=intc)
    days_os = V(F_CAUSAL, OS0, "days", f=intc)
    # The series names above are display text; record the day counts they carry.
    text(s, M, 6.25, 5.6, 0.7, P(R(
        f"In sample {days_is} days, burned OOS {days_os} days. Fees ×2: each match's own fee rate doubled. "
        "All costs ×2: fees doubled plus half a tick of spread. Book held fixed.", 10.5, MUTED)),
        name="Chart note")

    cx = 6.45
    cw = SW - M - cx

    def hdr(a, b):
        return [P(R(a, 12.5, WHITE, bold=True)), P(R(b, 10, MUTED_DK))]

    def cell(t, size=13.5, col=INK, bold=False):
        return [P(R(t, size, col, bold=bold))]

    fw = opt(F_FWD)
    if fw:
        fa = V(F_FWD, "primary_A_fast_minus_others_c", f=lambda p: f"A {cents(p[0])} {ci(p[1:])}")
        fb = V(F_FWD, "primary_m30_per_share_c", f=lambda p: f"B {cents(p[0])} {ci(p[1:])}")
        fva = V(F_FWD, "verdict_A_fast_tier")
        fvb = V(F_FWD, "verdict_B_v2_book")
        fwd_cells = [[P(R(fa, 11, INK)), P(R(fb, 11, INK))], cell(f"A {fva} · B {fvb}", 11, verdict_color(fva), True),
                     cell("", 11), cell("", 11), cell("", 11)]
    else:
        fwd = _record(PENDING, F_FWD + "  [blind forward test: one run, pre-registered in HYPOTHESIS_V2.md]")
        when = D(fwd_when, FWD_WHEN_SRC)
        fwd_cells = [cell(fwd, 14, RED, True), cell(f"runs once, planned {when}", 10.5, RED),
                     cell("reported either way", 10.5, MUTED), cell("", 10), cell("", 10)]
    rows = [
        [hdr("v2, causal window", "net of fees"), hdr("In sample", "frozen rules"), hdr("Burned OOS", "non-blind"),
         hdr("Forward", "blind")],
        [cell("Net ¢/share", 12.5),
         [P(R(V(F_CAUSAL, IS0, "per_share_c", f=cents), 17, BLUE, True, font=HEAD)),
          P(R(V(F_CAUSAL, IS0, "per_share_ci_c", f=ci), 10.5, MUTED))],
         [P(R(V(F_CAUSAL, OS0, "per_share_c", f=cents), 17, BLUE, True, font=HEAD)),
          P(R(V(F_CAUSAL, OS0, "per_share_ci_c", f=ci), 10.5, MUTED))], fwd_cells[0]],
        [cell("Sharpe · DD", 12.5),
         cell(f"{V(F_CAUSAL, IS0, 'sharpe_ann', f=sh1)} · {V(F_CAUSAL, IS0, 'max_dd_pct', f=pct1)}"),
         cell(f"{V(F_CAUSAL, OS0, 'sharpe_ann', f=sh1)} · {V(F_CAUSAL, OS0, 'max_dd_pct', f=pct1)}"), fwd_cells[1]],
        [cell("Months > 0", 12.5),
         cell(f"{V(F_CAUSAL, IS0, 'months_positive')}/{V(F_CAUSAL, IS0, 'months_total')}"),
         cell(f"{V(F_CAUSAL, OS0, 'months_positive')}/{V(F_CAUSAL, OS0, 'months_total')}"), fwd_cells[2]],
        [cell("P&L", 12.5),
         [P(R(V(F_CAUSAL, IS0, 'total_pnl_usd', f=usd_signed_k), 13.5, INK)),
          P(R(f"on {V(F_CAUSAL, IS0, 'capital_usd', f=usd_k)} capital", 10, MUTED))],
         [P(R(V(F_CAUSAL, OS0, 'total_pnl_usd', f=usd_signed_k), 13.5, INK)),
          P(R(f"on {V(F_CAUSAL, OS0, 'capital_usd', f=usd_k)} capital", 10, MUTED))],
         fwd_cells[3]],
        [cell("Fees ×2", 12.5),
         cell(V(F_COST, "is_eval/fee_x2", "per_share_c", f=cents)),
         cell(V(F_COST, "burned_oos/fee_x2", "per_share_c", f=cents), 13.5, RED, True), fwd_cells[4]],
    ]
    fills = [None, [None, None, None, RED_TINT if not fw else None]] + [[None, None, None, RED_TINT if not fw else None]] * 4
    tbl = table(s, cx, 2.16, [1.5, 1.6, 1.6, cw - 4.7], [0.62, 0.7, 0.42, 0.42, 0.55, 0.42], rows,
                "Table: v2 IS vs OOS", fills=fills)
    if not fw:
        tbl.cell(1, 3).merge(tbl.cell(5, 3))
        tbl.cell(1, 3).vertical_anchor = MSO_ANCHOR.MIDDLE
    v1 = V(F_SUM, "oos", "h6_shadow", "total_pnl_usd", f=lambda x: ("lost " if x < 0 else "made ") + usd_k(abs(x)))
    v1dd = V(F_SUM, "oos", "h6_shadow", "max_dd", f=lambda x: pct0(100 * x))
    box(s, cx, 5.4, cw, 1.5, fill=WHITE, line=LINE, radius=0.08, shadow=True, name="v1 card")
    text(s, cx + 0.25, 5.4, cw - 0.5, 1.5, [
        P(R("WHY v2 EXISTS", 11, BLUE, bold=True, spc=1.2)),
        P(R(f"v1 copied the fast tier's tickets and {v1} out of sample (max DD {v1dd}): big tickets on "
            "cheap tokens. v2 adds a causal window, fee-beating wallets, risk-parity size, a net cap per match "
            "and hold-to-resolution. " + ("With fees doubled, out of sample it loses."
                                          if opt(F_COST, "burned_oos/fee_x2", "per_share_c", default=0) < 0 else
                                          "It stays positive out of sample with fees doubled."), 12.5, INK), before=3),
    ], anchor="m", name="v1 note")
    footer(s, n)
    notes(s, f"""
{window(4)}  BACKTEST: IN SAMPLE VS OUT OF SAMPLE, AND COSTS DOUBLED

We priced that opportunity as a paper strategy on the fast tier's own fills. It measures their speed, not our execution.

Version one copied their tickets and {v1} out of sample. Version two adds five rules. In sample: {vis[0][1]} a share, Sharpe {V(F_CAUSAL, IS0, 'sharpe_ann', f=sh1)}. Out of sample, on a window we had already seen, so we call it burned: {vos[0][1]}, Sharpe {V(F_CAUSAL, OS0, 'sharpe_ann', f=sh1)}.

Now the stress. Half a tick worse and the out-of-sample edge is {vos[1][1]}. Double the fees and it is {vos[3][1]}: negative. Double all costs: {vos[4][1]}. In today's fee regime it does not survive doubled costs, and we say so.

The blind forward test runs once, planned for {D(fwd_when, FWD_WHEN_SRC)}; at build time it is {"in" if fw else "pending"}, and it will be reported either way.

[If asked "whose fills?": the fast tier's. Second place earns nothing out of sample (+1/2 tick: {vos[1][1]}).]
[Sources: {F_CAUSAL} (slippage cases), {F_COST} (fees x2, all costs x2), {F_SUM} oos h6_shadow (v1), {F_FWD} (forward).]
""")


def s06_rigor(prs, n):
    slide_ctx(f"{n} Rigor")
    s = new_slide(prs)
    eyebrow(s, "05  ·  RIGOR AND BLIND TESTS")
    set_title(s, "Every test we ran, including the ones we failed")

    def rig_row(series):
        return next(i for i, r in enumerate(raw(F_RIGOR, "psr_dsr", "rows")) if r["series"] == series)

    def dsr(series, key):
        def fn():
            return dsr3(raw(F_RIGOR, "psr_dsr", "rows", rig_row(series), "dsr", key, "dsr"))
        return D(fn, f"{F_RIGOR} :: psr_dsr > rows > [series={series}] > dsr > {key} > dsr")

    n_all = V(F_RIGOR, "psr_dsr", "N", "all_plus_v2safe_grid", f=intc,
              how="NOTE section 8 counts 3,386; plus the 24-variant v2-safe grid")
    n_h = V(F_RIGOR, "psr_dsr", "N", "H1_H6", f=intc)

    def dsr_min(series, n_key):     # lowest DSR across the variance sources, as in the video
        return D(lambda: dsr3(raw(F_RIGOR, "psr_dsr", "rows", rig_row(series), f"dsr_min_{n_key}")),
                 f"{F_RIGOR} :: psr_dsr > rows > [series={series}] > dsr_min_{n_key}")
    dsr_is = dsr_min("v2_is", "N3410")
    dsr_os_all = dsr_min("v2_oos", "N3410")
    dsr_os_h = dsr_min("v2_oos", "N44")
    pbo_safe = V(F_RIGOR, "pbo_cscv", "lowloss_24_sharpe", "pbo", f=frac_pct1)
    pbo_size = V(F_RIGOR, "pbo_cscv", "sizing_55_res_actual_sharpe", "pbo", f=frac_pct1)
    boot = V(F_RIGOR, "bootstrap", "v2_oos", "sharpe_ann_ci95", f=lambda p: ci(p, 1))
    t_os = V(F_RIGOR, "sharpe_moments", "v2_oos", "T_days", f=intc)
    label(s, M, 1.72, 5.0, "RIGOR PACK (results/rigor/rigor.json)")
    tiles = [
        (dsr_is, f"deflated Sharpe, in sample, N = {n_all} trials", BLUE),
        (dsr_os_all, f"deflated Sharpe, burned OOS at N = {n_all} ({dsr_os_h} at N = {n_h}): {t_os} days can't rule "
                     "out luck", RED),
        (pbo_safe, f"probability of backtest overfitting, v2-safe grid ({pbo_size} on the sizing grid)", BLUE),
        (boot, "block-bootstrap 95% CI of the burned-OOS Sharpe", INK),
    ]
    tw, th = 2.4, 2.25
    for i, (big, cap, col) in enumerate(tiles):
        x = M + (i % 2) * (tw + 0.15)
        y = 2.08 + (i // 2) * (th + 0.15)
        box(s, x, y, tw, th, fill=WHITE, line=LINE, radius=0.08, shadow=True, name=f"Rigor tile {i}")
        text(s, x + 0.18, y + 0.12, tw - 0.36, 0.8, P(R(big, 34 if len(big) < 8 else 24, col, bold=True, font=HEAD)),
             anchor="b", name=f"Rigor value {i}")
        text(s, x + 0.18, y + 0.98, tw - 0.36, th - 1.08, P(R(cap, 12, INK)), name=f"Rigor caption {i}")

    cx = M + 2 * tw + 0.15 + 0.4
    cw = SW - M - cx
    label(s, cx, 1.72, cw, "TESTS, IN THE ORDER WE RAN THEM")
    try:
        _, wf_oos = wf_months()
    except Missing:
        wf_oos = []
    tt1 = V(F_TT, "TT1", "verdict")
    tt2 = V(F_TT, "TT2", "verdict")
    tt3 = V(F_TT, "TT3", "verdict")
    u2v_is = V(F_EXP, "primary", "u2_is", "label")
    u2v_os = V(F_EXP, "primary", "u2_oos", "label")
    mkv = V(F_MAKER, "primary", "verdict")
    fwd_v = (V(F_FWD, "verdict_B_v2_book") if opt(F_FWD) else
             _record(PENDING, F_FWD + "  [verdict_B_v2_book]"))
    t3 = {k: opt(F_T0V3, "sets", k) for k in ("u2_is", "u2_oos", "burned_oos")}
    t3_res = D(lambda: f"{cents(raw(F_T0V3, 'sets', 'u2_is', 'primary', 'per_share_c'))} / "
                       f"{cents(raw(F_T0V3, 'sets', 'u2_oos', 'primary', 'per_share_c'))}; burned "
                       f"{cents(raw(F_T0V3, 'sets', 'burned_oos', 'primary', 'per_share_c'))} "
                       f"{ci((raw(F_T0V3, 'sets', 'burned_oos', 'primary', 'per_share_ci95_c_lo'), raw(F_T0V3, 'sets', 'burned_oos', 'primary', 'per_share_ci95_c_hi')))}",
               f"{F_T0V3} :: sets > u2_is|u2_oos|burned_oos > primary > per_share_c (+ burned CI)")
    t3_v = (D(lambda: "FAIL" if str(raw(F_T0V3, "verdicts", "U2 (primary, test b)", "overall")).startswith("FAIL")
              and raw(F_T0V3, "sets", "burned_oos", "reading", "verdict") == "FAIL" else
              str(raw(F_T0V3, "verdicts", "U2 (primary, test b)", "overall")).split(" ")[0],
              f"{F_T0V3} :: verdicts > U2 (primary, test b) > overall; sets > burned_oos > reading > verdict")
            if all(t3.values()) else _record(PENDING, F_T0V3))
    wf_v = ("PASS" if wf_oos and all(m["net30_c"] > 0 for m in wf_oos) else "FAIL") if wf_oos else PENDING
    os_v = ("POSITIVE" if opt(F_CAUSAL, OS0, "per_share_ci_c", default=[0])[0] > 0 else "CI INCLUDES 0") \
        if opt(F_CAUSAL, OS0) else PENDING
    f2_v = ("NEGATIVE" if opt(F_COST, "burned_oos/fee_x2", "per_share_c", default=0) < 0 else "POSITIVE") \
        if opt(F_COST, "burned_oos/fee_x2") else PENDING
    tests = [
        ("Fast tier, walk-forward, OOS months",
         D(lambda: f"{sum(m['net30_c'] > 0 for m in wf_oos)}/{len(wf_oos)} months > 0" if wf_oos else PENDING,
           f"{F_SUM} :: oos > h6_walkforward  [months net30_c > 0]"), wf_v),
        ("v2, burned OOS (non-blind)",
         f"{V(F_CAUSAL, OS0, 'per_share_c', f=cents)} {V(F_CAUSAL, OS0, 'per_share_ci_c', f=ci)}", os_v),
        ("v2, burned OOS, fees ×2",
         f"{V(F_COST, 'burned_oos/fee_x2', 'per_share_c', f=cents)} {V(F_COST, 'burned_oos/fee_x2', 'per_share_ci_c', f=ci)}",
         f2_v),
        ("Blind: v2 on unseen markets, IS period",
         f"{V(F_EXP, 'primary', 'u2_is', 'per_share_c', f=cents)} {V(F_EXP, 'primary', 'u2_is', 'per_share_ci_c', f=ci)}",
         "PASS" if u2v_is == "PASS" else u2v_is),
        ("Blind: v2 on unseen markets, OOS period",
         f"{V(F_EXP, 'primary', 'u2_oos', 'per_share_c', f=cents)} {V(F_EXP, 'primary', 'u2_oos', 'per_share_ci_c', f=ci)}",
         "FAIL" if u2v_os == "FAILURE" else u2v_os),
        ("Blind: maker v1, side markets, OOS",
         f"{V(F_MAKER, 'primary', 'value_c', f=cents)} {V(F_MAKER, 'primary', 'ci95_c', f=ci)}, "
         f"{V(F_MAKER, 'headline', 'total_pnl_usd', f=usd_signed0)}",
         "FAIL" if mkv == "FAILURE" else mkv),
        ("Tier-0 v3, frozen (counterfactual*): unseen markets IS / OOS; burned OOS", t3_res, t3_v),
        ("Table tennis, same mechanism (TT1–TT3)", "no fast tier, no trades",
         "FAIL" if all(v.startswith("FAIL") for v in (tt1, tt2, tt3)) else f"{tt1}/{tt2}/{tt3}"),
        ("Blind forward test (run once)", fwd_v if fwd_v != PENDING else f"planned {D(fwd_when, FWD_WHEN_SRC)}", fwd_v),
    ]
    rows = [[[P(R("Test", 12, WHITE, bold=True))], [P(R("Result (¢/share, 95% CI)", 12, WHITE, bold=True))],
             [P(R("Verdict", 12, WHITE, bold=True))]]]
    fills = [None]
    for t, r, v in tests:
        rows.append([[P(R(t, 11, INK))], [P(R(r, 11, INK))], [P(R(v, 11, verdict_color(v), bold=True))]])
        fills.append([None, None, verdict_fill(v)])
    table(s, cx, 2.0, [cw - 3.85, 2.6, 1.25], [0.36] + [0.43] * len(tests), rows, "Table: tests", fills=fills)
    n_peeks = D(lambda: intc(len(peeks())), F_PEEKS + "  [non-empty lines at build time]")
    text(s, cx, 6.36, cw, 0.62, [
        P(R(f"Every look at held-out data is logged ({n_peeks} lines at build time). Failures stay in the record.",
            10.5, MUTED)),
        P(R("* " + TIER0_LABEL, 9.5, RED))], name="Peeks note")
    footer(s, n)
    notes(s, f"""
{window(5)}  RIGOR AND BLIND TESTS, INCLUDING THE FAILURES

We tried {n_all} variants, and we count all of them. In sample the deflated Sharpe is {dsr_is}. On the burned {t_os} days it is {dsr_os_all} at the full trial count: {t_os} days cannot rule out luck, and we say that. Overfitting probability on our risk grid: {pbo_safe}.

Then the blind tests, which we could not tune. Run frozen on markets we had never opened, v2 passed in the in-sample period and failed out of sample: its interval includes zero. Our side-market maker, pre-registered, failed its blind test. The frozen tier-0 v3 counterfactual failed its blind tests on unseen markets in both periods, and its burned out-of-sample run failed too because the interval includes zero. In table tennis we detected no fast tier. Fees doubled: negative.

The one clean test left is the forward run, planned for {D(fwd_when, FWD_WHEN_SRC)}. Every look is logged ({n_peeks} lines in the peek log at build time).

[NOTE section 8 counts 3,386 trials; the deck and video deflate at N = {n_all}, which adds the 24-variant v2-safe grid. DSR is the lowest across the variance sources (dsr_min).]

[Sources: {F_RIGOR} (psr_dsr, pbo_cscv, bootstrap); {F_EXP} primary; {F_MAKER} primary; {F_T0V3} (tier-0 v3, counterfactual); {F_TT} TT1-TT3; {F_COST}; {F_PEEKS}.]
""")


def s07_tier0(prs, n):
    slide_ctx(f"{n} The 1 s baseline")
    s = new_slide(prs)
    eyebrow(s, "06  ·  WHAT SPEED IS WORTH (SIMULATED)")
    set_title(s, "The 1 s baseline: break-even, and one unmeasured number")
    box(s, M, 1.62, CW, 0.5, fill=RED, radius=0.06, name="Simulated banner")
    text(s, M + 0.2, 1.62, CW - 0.4, 0.5, P(R(TIER0_LABEL, 11.5, WHITE, bold=True)), anchor="m",
         name="Simulated label")
    _record("SIMULATED label", "build_deck.py TIER0_LABEL  [must contain SIMULATED, not ex ante, not purchased; "
                               "checked at build]")
    vo = ("video_own120",)
    day = lambda x: ("+" if x >= 0 else MINUS) + f"${abs(x):.0f}"  # noqa: E731
    RT = lambda k, f=None: V(F_RT, "keys", k, "value", f=f)  # noqa: E731
    su = lambda x: f"{x:.2f} s" if isinstance(x, (int, float)) else str(x)  # noqa: E731

    def cell(rd, per, k, f):
        return V(F_SWEEP, *vo, rd, "1", per, k, f=f)
    pre_is, pre_os = cell("tournament", "IS", "usd_per_day", day), cell("tournament", "burned_OOS", "usd_per_day", day)
    pre_c = cell("tournament", "burned_OOS", "net_c_per_share", cents)
    pre_ci = cell("tournament", "burned_OOS", "net_c_per_share_ci95", ci)
    be = ("breakeven_video_delay",)
    pre_be_is = V(F_SWEEP, *be, "tournament", "IS", "breakeven_V_s_seed_mean_curve", f=su)
    pre_be_os = V(F_SWEEP, *be, "tournament", "burned_OOS", "breakeven_V_s_seed_mean_curve", f=su)
    cal_is, cal_os = cell("tournament_lagcal", "IS", "usd_per_day", day), cell("tournament_lagcal", "burned_OOS", "usd_per_day", day)
    lag = V(F_T0, "timing", "calibrated_stamp_lag_s (inference)", f=lambda x: f"{x:.2f} s")
    lag_ci = RT("cv.L_boot_ci", f=lambda p: f"[{p[0]:.2f}, {p[1]:.2f}] s")
    stc_is, stc_os = cell("stamp_calibrated", "IS", "usd_per_day", day), cell("stamp_calibrated", "burned_OOS", "usd_per_day", day)
    stc_be_is = V(F_SWEEP, *be, "stamp_calibrated", "IS", "breakeven_V_s_seed_mean_curve", f=su)
    stc_be_os = V(F_SWEEP, *be, "stamp_calibrated", "burned_OOS", "breakeven_V_s_seed_mean_curve", f=su)
    hv = ("headline_by_V", "V1", "all")
    rp_c = V(F_REPLAY, *hv, "per_share_mark_c", f=cents)
    rp_ci = V(F_REPLAY, *hv, "per_share_mark_ci95_c", f=ci)
    rp_neg = D(lambda: f"{sum(c['all']['per_share_mark_c'] < 0 for c in raw(F_REPLAY, 'cells').values())}/"
                       f"{len(raw(F_REPLAY, 'cells'))}", key_str(F_REPLAY, "cells") + "  [cells with per_share_mark_c < 0]")
    cards = [
        ("1  PRE-REGISTERED · STAMP LAG 2.0 s", f"{pre_os}/day", "held out", BLUE,
         f"{pre_c} a share {pre_ci}; {pre_is}/day in sample. Break-even feed delay {pre_be_os}–{pre_be_is}"),
        (f"2  POST HOC · LAG {lag}, ASSUMES COURTSIDE HUMANS", f"{cal_os}/day", "held out", "3F6E9C",
         f"{cal_is}/day in sample. The lag's own bootstrap CI: {lag_ci}"),
        ("3  SAME INFERENCE, READ PER POINT", f"{stc_os}/day", "held out", RED,
         f"{stc_is}/day in sample. Break-even feed delay {stc_be_os}–{stc_be_is}"),
        ("4  REPLAY · 9 REAL BOOKS · EVERY POINT, EX ANTE", f"{rp_c}", "a share", RED,
         f"{rp_ci} at V = 1 s, lag 2 s; {rp_neg} delay × lag cells lose"),
    ]
    for i, (title, big, unit, col, cap) in enumerate(cards):
        y = 2.27 + i * 1.18
        box(s, M, y, 4.55, 1.12, fill=WHITE, line=LINE, radius=0.08, shadow=True, name=f"Reading card {i}")
        text(s, M + 0.2, y + 0.05, 4.2, 1.02, [
            P(R(title, 9.5, col if col != RED else MUTED, bold=True, spc=1.0)),
            P(R(big, 22, col, bold=True, font=HEAD), R("  " + unit, 11, INK), before=0, line=0.95),
            P(R(cap, 10, MUTED), before=1),
        ], anchor="m", name=f"Reading text {i}")

    cx = M + 4.85
    cw = SW - M - cx
    label(s, cx, 2.27, cw, "$/DAY HELD OUT (BURNED OOS) VS ASSUMED FEED DELAY V, 20-SEED MEANS")
    cd = XyChartData()
    spec = [("Pre-registered (lag 2.0 s)", "tournament"), ("Post hoc (lag 3.14 s)", "tournament_lagcal"),
            ("Same inference, per point", "stamp_calibrated")]
    ys, n_ser = [], 0
    for name_, rd in spec:
        cur = opt(F_SWEEP, *vo, rd)
        if not cur:
            continue
        ser = cd.add_series(name_)
        n_ser += 1
        for vk, row in sorted(cur.items(), key=lambda kv: float(kv[0])):
            if float(vk) <= 3.0 and row.get("burned_OOS", {}).get("usd_per_day") is not None:
                y_ = row["burned_OOS"]["usd_per_day"]
                ser.add_data_point(float(vk), y_)
                ys.append(y_)
                _record(day(y_), key_str(F_SWEEP, *vo, rd, vk, "burned_OOS", "usd_per_day"))
    if ys:
        lo_y, hi_y = 20 * math.floor(min(ys) / 20), 20 * math.ceil(max(ys) / 20)
        ser = cd.add_series("assumed licensed feed: V = 1 s")
        ser.add_data_point(1.0, lo_y)
        ser.add_data_point(1.0, hi_y)
        zs = cd.add_series("zero")
        zs.add_data_point(0.0, 0.0)
        zs.add_data_point(3.0, 0.0)
        gf = s.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER_LINES, Inches(cx - 0.05), Inches(2.52), Inches(cw + 0.05),
                                Inches(2.95), cd)
        gf.name = "Chart: $/day vs feed delay"
        ch = gf.chart
        style_chart(ch)
        ch.legend.font.size = Pt(10)
        cols = [BLUE, "3F6E9C", RED, MUTED, "B8C4D0"]
        for i, ser in enumerate(ch.plots[0].series):
            ser.smooth = False
            ln = ser.format.line
            ln.color.rgb = rgb(cols[i])
            ln.width = Pt(2.25 if i < n_ser else 1.0)
            if i == 1 or i >= n_ser:
                ln.dash_style = MSO_LINE.DASH
            ser.marker.style = XL_MARKER_STYLE.NONE
        va = ch.value_axis
        va.minimum_scale, va.maximum_scale = lo_y, hi_y
        va.tick_labels.number_format = '"$"0'
        va.tick_labels.number_format_is_linked = False
        xa = ch.category_axis
        xa.minimum_scale, xa.maximum_scale = 0.0, 3.0
        xa.tick_labels.number_format = '0.0" s"'
        xa.tick_labels.number_format_is_linked = False
    else:
        text(s, cx, 3.0, cw, 1.0, P(R("Latency sweep: pending", 20, MUTED)), name="Chart pending")
    L_be = RT("cv.L_breakeven.oos", f=su)
    L_low = RT("cv.L_for_low.oos", f=su)
    mx_cal = RT("cv.cal.oos.maxlic", f=usd0)
    mx_pre = RT("cv.pre.oos.maxlic", f=usd0)
    lic_lo = V(F_FIN, "cost_assumptions", "feed_licence", "low", f=usd0)
    lic_hi = V(F_FIN, "cost_assumptions", "feed_licence", "high", f=usd0)
    v3_u2is = V(F_T0V3, "sets", "u2_is", "primary", "per_share_c", f=cents)
    v3_u2os = V(F_T0V3, "sets", "u2_oos", "primary", "per_share_c", f=cents)
    v3_all = V(F_T0V3, "verdicts", "U2 (primary, test b)", "overall", f=lambda v: v.split(" ")[0])
    text(s, cx, 5.55, cw, 1.4, [
        P(R("The sign turns on the unmeasured stamp lag L: ", 12, INK, bold=True),
          R(f"at 1 s the book breaks even only if L ≥ {L_be}, and covers the cheapest data quote only if "
            f"L ≥ {L_low}. It can pay at most {mx_cal}/month for data (post hoc) or {mx_pre} (pre-registered); "
            f"quotes run {lic_lo}–{lic_hi}/month (ASSUMPTION).", 12, INK)),
        P(R(f"A frozen tier-0 v3 rule failed its blind tests on unseen markets ({v3_u2is}, {v3_u2os}: {v3_all}).",
            11, RED), before=3),
    ], name="Reading")
    footer(s, n)
    notes(s, f"""
{window(6)}  WHAT SPEED IS WORTH: THE 1 s BASELINE (SIMULATED)

We don't own a fast feed. We assume a one-second licensed feed and ask what it is worth. This slide carries the label {TIER0_LABEL}. We bought no official ATP/WTA data feed and no result here uses one.

Pre-registered first: it breaks even, {pre_os} a day held out, {pre_c} a share, and the break-even feed delay is {pre_be_os} to {pre_be_is}. So the call has to beat the umpire's stamp by about nine-tenths of a second.

A post hoc reading of the umpire's lag ({lag}, which assumes the fast traders are courtside humans) gives {cal_os} a day; its own bootstrap interval for the lag is {lag_ci}. Read the same clocks point by point and it loses: {stc_os} a day. A replay on nine real recorded books, calling every point ex ante, gives {rp_c} a share and {rp_neg} cells lose.

The simulated trader only trades points that later moved four cents or more, so every number here is an upper bound. One second is the decision point for buying a feed. It is not a profit claim.

[If asked "isn't 1 s at L = 3.14 s just the camera counterfactual?": in the model, yes; only bounce-to-reprice time enters, so V = 1 at L = 3.14 equals a camera 0.14 s ahead of the bounce at L = 2.0 (QA_PREP Q8).]
[If asked about machines instead of humans: a 20 ms bot in London still gives L of about 2.85 s, because the 1 s venue hold dominates the inference (results/redteam/stamp_lag.json; QA_PREP Q9).]
[Sources: {F_SWEEP} video_own120 and breakeven_video_delay; {F_REPLAY} headline_by_V and cells; {F_RT} keys; {F_FIN} cost_assumptions; {F_T0V3}.]
""")


def s08_engine(prs, n):
    slide_ctx(f"{n} Live engine")
    s = new_slide(prs)
    eyebrow(s, "07  ·  THE ENGINE (PAPER ONLY)")
    set_title(s, "Live books, paper orders; full chain on a recorded book")
    lw = 4.25
    label(s, M, 1.72, lw, "LIVE BOOKS, READ-ONLY RUN")
    secs = V(F_ENG_LIVE, "seconds", f=lambda x: f"{x:.0f} s")
    rows = [
        ("Messages · assets", f"{V(F_ENG_LIVE, 'feed', 'msgs', f=intc)} · {V(F_ENG_LIVE, 'feed', 'assets', f=intc)}"),
        ("Markets discovered", V(F_ENG_LIVE, "markets_discovered", f=intc)),
        ("Feed delay p50/95/99",
         f"{V(F_ENG_LIVE, 'feed', 'latency', 'p50_ms', f=lambda x: f'{x:.0f}')} / "
         f"{V(F_ENG_LIVE, 'feed', 'latency', 'p95_ms', f=lambda x: f'{x:.0f}')} / "
         f"{V(F_ENG_LIVE, 'feed', 'latency', 'p99_ms', f=lambda x: f'{x:.0f}')} ms"),
        ("Snapshots mismatched",
         f"{V(F_ENG_LIVE, 'feed', 'snapshots_mismatched', f=intc)} of {V(F_ENG_LIVE, 'feed', 'snapshots_checked', f=intc)}"),
        ("Gaps · reconnects", f"{V(F_ENG_LIVE, 'feed', 'gaps', f=intc)} · {V(F_ENG_LIVE, 'reconnects', f=intc)}"),
        ("What-if: send / skip",
         D(lambda: f"{sum(v for k, v in raw(F_ENG_LIVE, 'what_if_tally').items() if k.startswith('SEND'))} / "
                   f"{sum(v for k, v in raw(F_ENG_LIVE, 'what_if_tally').items() if k.startswith('SKIP'))}",
           key_str(F_ENG_LIVE, "what_if_tally") + "  [sum SEND* / SKIP*]")),
        ("Orders sent", V(F_ENG_LIVE, "orders_sent", f=intc)),
    ]
    trs = [[[P(R(f"{secs} live window", 12, WHITE, bold=True))], [P(R("", 12, WHITE))]]]
    for a, b in rows:
        trs.append([[P(R(a, 11.5, INK))], [P(R(b, 11.5, INK, bold=True), align="r")]])
    table(s, M, 2.05, [lw - 1.75, 1.75], [0.38] + [0.42] * len(rows), trs, "Table: live engine")

    mx = M + lw + 0.3
    mw = 3.6
    try:
        ls_ = live_state()
    except Missing:
        ls_ = None
    label(s, mx, 1.72, mw, "LIVE PAPER SESSION" + (f" ({ls_['since'][:10]})" if ls_ and ls_["since"] else ""))
    live = opt(F_LIVE)
    box(s, mx, 2.05, mw, 3.75, fill=INK, radius=0.1, name="Session card")
    if live and ls_:
        lab = V(F_LIVE, "label")
        st = _record(ls_["state"].upper(), LIVE_STATE_SRC)
        status = V(F_LIVE, "status")
        run = V(F_LIVE, "run")
        since = _record(ls_["since"] + " UTC", key_str(F_LIVE, "started_process"))
        asof = _record(ls_["asof"] + " UTC", key_str(F_LIVE, "now") + "  [file modification time when now is 1970]")
        b1f = V(F_LIVE, "books", "B1", "fills", f=intc)
        b1p = V(F_LIVE, "books", "B1", "pnl", f=lambda x: ("+" if x >= 0 else MINUS) + f"${abs(x):,.2f}")
        ctf = V(F_LIVE, "books", "CTRL-taker", "fills", f=intc)
        cap = V(F_LIVE, "capital_per_book", f=usd0)
        st_col = {"RUNNING": "7FD1A0", "FINISHED": "8FB0D1"}.get(st, "F07A66")
        paras = [
            P(R(lab, 11, "F07A66", bold=True)),
            P(R("Strategy: maker v1 (frozen, pre-registered) + taker control", 11.5, WHITE), before=6),
            P(R(st, 20, st_col, bold=True, font=HEAD), before=8),
            P(R(f"Run {run}  ·  started {since}  ·  as of {asof}", 10.5, MUTED_DK), before=2),
            P(R("Status: ", 11.5, MUTED_DK), R(status, 11.5, WHITE), before=6),
        ]
        if ls_["state"] == "warming up":
            paras.append(P(R("No quotes yet: quoting starts after a warm-up check on 50 public trades. Fills and P&L "
                             "appear once it quotes.", 11.5, WHITE), before=8))
        else:
            msgs = D(lambda: intc(sum(v for k, v in raw(F_LIVE, "counters").items() if k.startswith("msg_"))),
                     key_str(F_LIVE, "counters") + "  [sum msg_*]")
            inplay = V(F_LIVE, "matches_in_play", f=intc)
            paras += [P(R(f"Primary book: {b1f} fills, P&L {b1p} on {cap} paper capital", 12.5, WHITE, bold=True),
                        before=8),
                      P(R(f"Taker control: {ctf} fills", 11.5, WHITE), before=3),
                      P(R(f"{msgs} book messages · {inplay} match(es) in play", 11, MUTED_DK), before=6)]
        paras.append(P(R("Plumbing check, not evidence of edge: maker v1 already failed its blind OOS.", 10.5,
                         MUTED_DK), before=8))
    else:
        status = _record(PENDING, F_LIVE)
        st = PENDING
        b1f = b1p = PENDING
        paras = [P(R("Live paper session: pending", 18, WHITE, bold=True))]
    text(s, mx + 0.22, 2.12, mw - 0.44, 3.62, paras, anchor="t", name="Session text")

    fx = mx + mw + 0.3
    fw_ = SW - M - fx
    figure(s, "results/engine/demo_timeline.png", fx, 1.72, fw_, 4.08,
           caption="Illustrative: table-tennis calls on a recorded WTA book. Timing only.",
           name="Engine demo timeline", cap_h=0.5)

    # Organizer question 1: can the pipeline trade inside 3 s? Frame -> executable order, measured (e2e run).
    bg = ("budget_with_1s_simulated_feed",)
    e_feed = opt(F_E2E, *bg, "feed_simulated_ms")
    e_ours = opt(F_E2E, *bg, "ours_capture_to_order_ready_ms", "p50")
    e_net = opt(F_E2E, *bg, "network_one_way_ms", "p50")
    e_ven = opt(F_E2E, *bg, "venue_delay_ms", "p50")
    e_tot = opt(F_E2E, *bg, "total_ms", "p50")
    e_req = opt(F_E2E, *bg, "requirement_ms", default=3000.0)
    e_n = opt(F_E2E, "our_pipeline_frame_to_order_ready_ms", "n")
    e_fps = opt(F_E2E, *bg, "conditions", "stream_fps")          # e2e verifier: the conditions travel with the numbers
    e_slow = opt(F_E2E, *bg, "conditions", "slow_motion")
    g50_ = V(F_OVO, "headline", OVO_RUN, "stream", "after_startup", "call_ready_ms", "p50", f=lambda x: f"{x:.1f} ms")
    ys_ = 6.2
    if None not in (e_feed, e_ours, e_net, e_ven, e_tot):
        for k_, v_ in (("feed_simulated_ms", e_feed), ("ours_capture_to_order_ready_ms > p50", e_ours),
                       ("network_one_way_ms > p50", e_net), ("venue_delay_ms > p50", e_ven), ("total_ms > p50", e_tot)):
            _record(f"{v_:,.0f} ms", key_str(F_E2E, *bg) + " > " + k_)
        n_tr = _record(f"{e_n}", key_str(F_E2E, "our_pipeline_frame_to_order_ready_ms", "n"))
        label(s, M, 5.88, CW, f"CAN WE TRADE INSIDE 3 s? FRAME → EXECUTABLE PAPER ORDER, MEASURED END TO END "
                              f"({n_tr} TIMING PROBES; ORDER NOT SENT)")
        scale = CW / max(e_req, e_tot)
        segs = [(e_feed, "simulated 1 s licensed feed", "B8C4D0", INK), (e_ours, "", BLUE, WHITE),
                (e_net, "", "3F6E9C", WHITE), (e_ven, "venue holds every order 1 s", RED, WHITE)]
        x_ = M
        for i, (ms, lab_, fill_, fg_) in enumerate(segs):
            w_ = max(ms * scale, 0.04)
            box(s, x_, ys_, w_, 0.42, fill=fill_, radius=0.0, name=f"Latency seg {i}")
            if lab_:
                text(s, x_ + 0.08, ys_, w_ - 0.16, 0.42, P(R(f"{lab_}: {ms:,.0f} ms", 11, fg_, bold=True)),
                     anchor="m", name=f"Latency seg label {i}")
            x_ += w_
        box(s, x_, ys_, M + e_req * scale - x_, 0.42, fill=WHITE, line=LINE, radius=0.0, name="Latency margin")
        text(s, x_ + 0.08, ys_, M + e_req * scale - x_ - 0.16, 0.42,
             P(R(f"margin to 3 s: {e_req - e_tot:,.0f} ms", 11, BLUE, bold=True)), anchor="m", name="Latency margin label")
        cond_ = (f"CV fed at {e_fps:g} frames/s, every frame ({e_slow} slow motion; the laptop cannot run 120 fps "
                 f"in real time); all {n_tr} orders were timing probes: the rule and the risk check declined every "
                 "call on pre-match books. " if e_fps else "")
        if e_fps:
            _record(cond_.strip(), key_str(F_E2E, *bg, "conditions"))
        text(s, M, ys_ + 0.44, CW, 0.42, P(
            R(f"Ours, video in → paper order ready: {e_ours:,.0f} ms (laptop) · network to the venue {e_net:,.0f} ms · "
              f"total {e_tot:,.0f} ms. {cond_}GPU vision call-ready {g50_}. Timing margin is not trading margin: the "
              "call must beat the umpire's stamp by ~0.9 s (slide 7).", 9.5, MUTED)), name="Latency caption")
    else:
        label(s, M, 5.88, CW, "CAN WE TRADE INSIDE 3 s? FRAME → EXECUTABLE PAPER ORDER")
        _record(PENDING, F_E2E + "  [end-to-end timing proof]")
        text(s, M, ys_, CW, 0.8, P(R(f"End-to-end run: pending. Measured parts: GPU vision call-ready {g50_}; the "
                                     "venue holds every order 1 s; a simulated 1 s feed.", 12, INK)),
             name="Latency pending")
    footer(s, n)
    notes(s, f"""
{window(7)}  THE ENGINE RUNS END TO END, PAPER ONLY

This is not just a backtest. The market-data and paper-trading legs run on live Polymarket order books, read-only: {rows[0][1]} messages and assets in a {secs} window, feed delay (p50/95/99) {rows[2][1]}, no gaps, and zero orders sent, by construction.

On the right, the full chain runs on a real recorded WTA book: vision call, paper order, the one-second venue delay, the fill, then the reprice. It is an illustrative pairing of table-tennis calls with a tennis book, so it shows timing, not edge.

The strip at the bottom answers the organizers' first question, whether we can trade inside three seconds. It is measured end to end in one process: our own footage streamed over WebRTC into the vision engine, a call, a paper order built against a live tennis book, the measured network time to the venue, and the venue's one-second hold, plus a simulated one-second feed. Our own part is tens of milliseconds; the feed and the venue hold dominate. Two conditions go with it: the laptop vision engine was fed ten frames a second, every frame, twelve times slower than real time, because it cannot run 120 frames a second live; and every order was a timing probe, because the rule and the risk check declined every call on the pre-match books. Three seconds is not the real bar, though: the call has to beat the umpire's stamp by about nine-tenths of a second.

[Engine: streaming vision → fair value → strategy → risk → paper executor. The executor refuses to start if a live-trading flag or wallet key is present. The e2e run maps table-tennis calls onto a live tennis market for timing only (different sport); the order payload is unsigned and never sent ({F_E2E}).]

The live paper session (our pre-registered maker plus a taker control) was {st.lower()} at build time. Status: {status}. Primary book: {b1f} fills, P&L {b1p}. It is a plumbing check; that strategy already failed its blind test.

[Paper only: TERMS 5.3 forbids funded accounts; the executor raises LiveTradingForbidden if keys or live flags exist. If the session summary updates before the talk, rebuild the deck and re-render the video together: both read it at build time.]
[Sources: {F_ENG_LIVE}; {F_LIVE}; results/engine/demo_timeline.png from {F_ENG_DEMO}; {F_E2E} budget_with_1s_simulated_feed; {F_OVO} headline.]
""")


def s09_risk(prs, n):
    slide_ctx(f"{n} Risk + liquidity + financials")
    s = new_slide(prs)
    eyebrow(s, "08  ·  RISK  ·  LIQUIDITY & CAPITAL  ·  FINANCIALS")
    set_title(s, "Small, hard-limited, and it barely pays its costs")
    rc = ("risk_config",)
    lw = 3.9
    label(s, M, 1.72, lw, "HARD LIMITS (ENGINE RiskConfig)")
    tiles = [
        (V(F_ENG_DEMO, *rc, "max_order_usd", f=usd0), "per order"),
        (V(F_ENG_DEMO, *rc, "net_cap_shares", f=intc), "shares net per match"),
        (V(F_ENG_DEMO, *rc, "zone", f=lambda z: f"{z[0]:.2f}–{z[1]:.2f}"), "price zone only"),
        (V(F_ENG_DEMO, *rc, "daily_stop_usd", f=usd0), "daily stop (latches)"),
        (V(F_ENG_DEMO, *rc, "feed_stale_ms", f=lambda x: f"{x / 1000:.0f} s"), "no data → reduce only"),
        (V(F_ENG_DEMO, *rc, "vision_stale_ms", f=lambda x: f"{x / 1000:.0f} s"), "no vision → reduce only"),
    ]
    tw, th = (lw - 0.15) / 2, 1.3
    for i, (big, cap) in enumerate(tiles):
        x = M + (i % 2) * (tw + 0.15)
        y = 2.05 + (i // 2) * (th + 0.12)
        box(s, x, y, tw, th, fill=WHITE, line=LINE, radius=0.08, shadow=True, name=f"Limit tile {i}")
        text(s, x + 0.15, y + 0.1, tw - 0.3, 0.72, P(R(big, 28 if len(big) <= 6 else 22, RED if i >= 3 else BLUE, bold=True, font=HEAD)),
             anchor="b", name=f"Limit value {i}")
        text(s, x + 0.15, y + 0.8, tw - 0.3, 0.45, P(R(cap, 11.5, INK)), name=f"Limit caption {i}")

    mx = M + lw + 0.3
    mw = 3.45
    label(s, mx, 1.72, mw, "LIQUIDITY & CAPITAL")
    lc = ("liquidity_capital", "is_eval")
    med = V(F_RISK, *lc, "usd_per_trade_quantiles", "0.5", f=lambda x: f"${x:.2f}")
    cap = V(F_CAUSAL, IS0, "capital_usd", f=usd_k)
    peak = V(F_CAUSAL, IS0, "peak_locked_usd", f=usd_k)
    per_day = V(F_NM, "is", "usd_traded_per_day", f=usd_k)
    share = D(lambda: pct1(max(raw(F_RISK, "liquidity_capital", "v2_share_of_fast_tier_usd_is_pct").values())),
              key_str(F_RISK, "liquidity_capital", "v2_share_of_fast_tier_usd_is_pct") + "  [max over months]")
    ceil_ = V(F_FIN, "strategies", "v2", "ceiling", "IS", "fast_tier_qualified_print_usd_per_day", f=usd_k)
    top1 = V(F_RISK, "concentration", "is_eval", "wallet", "top1_share_of_net_pct", f=pct1)
    v2cap = V(F_ALPHA, "headline", "oos_capital_capacity_usd", f=lambda p: f"{usd_k(p[0])}–{usd_k(p[1])}")
    cvcap = D(lambda: f"{usd_k(raw(F_RT, 'keys', 'cv.pre.oos.cap', 'value'))}–{usd_k(raw(F_RT, 'keys', 'cv.cal.oos.cap', 'value'))}",
              key_str(F_RT, "keys", "cv.pre.oos.cap / cv.cal.oos.cap") + "  [latency_sweep.csv capital_usd at V = 1]")
    items = [(med, "median v2 trade"), (f"{per_day}/day", f"v2 notional on {cap} capital (3× peak locked {peak})"),
             (f"≤ {share}", "of the fast tier's own 0–3 s volume in any month"),
             (v2cap, "capital where v2's held-out edge still holds (1–2× its frozen size); 5× loses"),
             (cvcap, "capital the CV book uses at 1 s (100-share cap, 10 matches a day; results/capacity has the grid)"),
             (top1, "of in-sample P&L from the top wallet: concentration risk")]
    paras = []
    for big, cap_ in items:
        paras.append(P(R(big + "  ", 17, BLUE, bold=True, font=HEAD), R(cap_, 11, INK), after=5))
    text(s, mx, 2.05, mw, 4.4, paras, name="Liquidity list")

    fx = mx + mw + 0.3
    fw_ = SW - M - fx
    label(s, fx, 1.72, fw_, "$/DAY AFTER CENTRAL FIXED COSTS")

    def frow(strat, per, lab_):
        tr = FIN(strat, per, "net_trading_usd_per_day", f=usd_signed0)
        fx_ = FIN(strat, per, "fixed_cost_usd_per_day", "central", f=usd0)
        net = FIN(strat, per, "net_after_costs_usd_per_day", "central", f=usd_signed0)
        col = RED if net.startswith(MINUS) else BLUE
        return [[P(R(lab_, 11, INK))], [P(R(tr, 11.5, INK), align="r")], [P(R(fx_, 11.5, MUTED), align="r")],
                [P(R(net, 12, col, bold=True), align="r")]]

    def cv_row():
        rk = lambda k: raw(F_RT, "keys", k, "value")  # noqa: E731
        sg = lambda x: ("+" if x >= 0 else MINUS) + f"{abs(x):.0f}"  # noqa: E731
        tr = D(lambda: f"{sg(rk('cv.pre.oos.usd'))} / {sg(rk('cv.cal.oos.usd'))}",
               key_str(F_RT, "keys", "cv.pre.oos.usd / cv.cal.oos.usd"))
        fx_ = D(lambda: usd0(rk("fin.cost.central_day")), key_str(F_RT, "keys", "fin.cost.central_day"))
        net = D(lambda: f"{sg(rk('cv.pre.oos.net_central'))} / {sg(rk('cv.cal.oos.net_central'))}",
                key_str(F_RT, "keys", "cv.pre.oos.net_central / cv.cal.oos.net_central"))
        return [[P(R("CV @ 1 s, OOS: pre-reg / post hoc", 10, INK))], [P(R(tr, 10.5, INK), align="r")],
                [P(R(fx_, 11, MUTED), align="r")], [P(R(net, 11, RED, bold=True), align="r")]]

    trs = [[[P(R("Book", 11, WHITE, bold=True))], [P(R("Trading", 11, WHITE, bold=True), align="r")],
            [P(R("Fixed", 11, WHITE, bold=True), align="r")], [P(R("Net", 11, WHITE, bold=True), align="r")]],
           frow("v2 (", "IS", "v2, IS"),
           frow("v2 (", "IS, current 1 s / 5% regime only", "v2, IS, today's fees"),
           frow("v2 (", "OOS (burned, non-blind)", "v2, burned OOS"),
           frow("Maker", "OOS (blind)", "Maker, blind OOS"),
           cv_row()]
    table(s, fx, 2.05, [fw_ - 2.55, 0.85, 0.75, 0.95], [0.38] + [0.5] * 5, trs, "Table: financials")
    lic = V(F_FIN, "cost_assumptions", "feed_licence", "central", f=usd0)
    mx_cal = V(F_RT, "keys", "cv.cal.oos.maxlic", "value", f=usd0)
    mx_pre = V(F_RT, "keys", "cv.pre.oos.maxlic", "value", f=usd0)
    lic_lo = V(F_FIN, "cost_assumptions", "feed_licence", "low", f=usd0)
    lic_hi = V(F_FIN, "cost_assumptions", "feed_licence", "high", f=usd0)
    text(s, fx, 5.0, fw_, 1.4, [
        P(R(f"The CV book at 1 s can pay at most {mx_cal}/month for data (post hoc) or {mx_pre} (pre-registered), "
            f"against quotes of {lic_lo}–{lic_hi}/month (ASSUMPTION; {lic} central). It prices speed; it is not yet "
            "a business.", 10.5, INK, bold=True)),
        P(R("CV @ 1 s: " + TIER0_LABEL + ".", 9.5, RED), before=3),
    ], name="Financials note")
    box(s, M, 6.42, CW, 0.52, fill=INK, radius=0.08, name="Risk strip")
    text(s, M + 0.25, 6.42, CW - 0.5, 0.52, P(
        R("Top risks (docs/RISK.md): ", 12, "F07A66", bold=True),
        R("fee/delay regime change (R11) · crowding for the same stale quote (R6) · wallet concentration (R2) · "
          "venue access and data rights (R16)", 12, WHITE)), anchor="m", name="Risk register")
    footer(s, n)
    notes(s, f"""
{window(8)}  RISK, LIQUIDITY AND CAPITAL, FINANCIALS

Small by design. Every order goes through hard limits: {tiles[0][0]} per order, {tiles[1][0]} shares net per match, a {tiles[3][0]} daily stop, and kill switches when data or vision goes stale.

Liquidity: the median trade is {med}; at most {share} of the fast tier's own volume in any month; capital is three times peak locked, {cap}.

Capacity, the organizers' second question: v2's held-out edge holds only up to about {v2cap} of capital, one to two times its frozen size, and five times the size loses. The CV book at one second uses {cvcap}; the binding limit is the stale depth on each point, not our capital.

Financials, honestly: before fixed costs v2 makes money. After a data licence and a London server, it is about break-even in sample and negative on the burned out-of-sample. The CV book at one second can pay at most {mx_cal} a month for data under the post hoc reading and {mx_pre} pre-registered, against quotes of {lic_lo} to {lic_hi}. So this prices speed; it is not a business yet.

[Biggest risk is the venue: one fee or delay change moves the edge more than any parameter (R11). Wallet concentration: top wallet {top1} of IS P&L (R2).]
[Sources: {F_ENG_DEMO} risk_config; {F_RISK} liquidity_capital, concentration; {F_CAUSAL}; {F_FIN} headline rows and cost_assumptions; {F_ALPHA} headline.oos_capital_capacity_usd; {F_RT} keys (derived by scripts/redteam_derived.py); results/capacity/capacity.json (capacity grid); docs/RISK.md.]
""")


def s10_close(prs, n):
    slide_ctx(f"{n} Close")
    s = new_slide(prs, dark=True)
    eyebrow(s, "REPRODUCE IT", dark=True)
    set_title(s, "Public code. Public data. Paper only.", dark=True, size=40)
    box(s, M, 1.9, 8.6, 2.3, fill=INK_2, radius=0.1, name="Terminal card")
    model_in_git = subprocess.run(["git", "ls-files", "--error-unmatch", "models/vision/frozen_call_model.pkl"],
                                  cwd=ROOT, capture_output=True).returncode == 0
    cmd_lines = [
        P(R("$ ", 15, "F07A66", bold=True, font=MONO), R("bash run.sh replay", 19, WHITE, bold=True, font=MONO)),
        P(R("  # paper engine on recorded live books, in seconds, no network", 11.5, MUTED_DK, font=MONO)),
        P(R("$ ", 15, "F07A66", bold=True, font=MONO),
          R("bash run.sh data && bash run.sh reproduce", 19, WHITE, bold=True, font=MONO), before=6),
        P(R("  # public crawl, no keys (~1-2 h), then every table and figure in the note", 11.5, MUTED_DK,
            font=MONO)),
        P(R("  # this deck: .venv/bin/python docs/deck/build_deck.py", 11.5, MUTED_DK, font=MONO), before=4),
    ]
    if not model_in_git:
        cmd_lines.append(P(R("  # vision calls need models/vision/frozen_call_model.pkl (not in git; rebuilt by "
                             "hpg/engine_vision.sbatch)", 11.5, MUTED_DK, font=MONO)))
    text(s, M + 0.3, 1.9, 8.1, 2.3, cmd_lines, anchor="m", name="Command")
    text(s, M, 4.35, SW - 2 * M, 0.55, P(R(REPO_URL, 14, WHITE, bold=True, font=MONO)), anchor="m", name="Repo URL")
    fwd = "results in" if opt(F_FWD) else PENDING
    when = D(fwd_when, FWD_WHEN_SRC)
    if not opt(F_FWD):
        _record(PENDING, F_FWD + "  [forward test]")
    try:
        ls_ = live_state()
        live_status = _record(f"{ls_['state']} (started {ls_['since']} UTC)", LIVE_STATE_SRC)
    except Missing:
        live_status = _record(PENDING, F_LIVE)
    pend_fin = D(lambda: "; ".join(raw(F_FIN, "pending")) or "none", key_str(F_FIN, "pending"))
    text(s, M, 5.0, SW - 2 * M, 1.8, [
        P(R("NEXT: ", 13, "F07A66", bold=True),
          R("one licensed-feed session to measure the stamp lag; an ex-ante point filter; then decide whether to buy "
            "a feed.", 13, WHITE)),
        P(R("STILL OPEN AT BUILD TIME", 12, MUTED_DK, bold=True, spc=1.4), before=6),
        P(R(f"Blind forward test (run once, planned {when}): ", 14, WHITE, bold=True),
          R(fwd, 14, "F07A66", bold=True), before=4),
        P(R("Live paper session: ", 14, WHITE, bold=True), R(live_status, 14, MUTED_DK)),
        P(R(f"Financials still pending: {pend_fin}", 12, MUTED_DK), before=2),
    ], name="Pending")
    text(s, M, 6.86, SW - 2 * M, 0.5, P(R("No real money was traded. We bought no official ATP/WTA data feed and no "
                                          "trading result uses one; free public score pages were recorded only to "
                                          "time their lag. The CV trader is simulated (assumed 1 s licensed feed, not purchased).", 11, MUTED_DK)),
         anchor="m", name="Disclaimer")
    notes(s, f"""
{window(9)}  CLOSE

The code is public and the failures are in it. bash run.sh replay reruns the paper engine on recorded books in seconds; bash run.sh data, then bash run.sh reproduce, rebuilds every table and figure from public data in one to two hours; bash run.sh redteam reruns the checks we ran against ourselves. The blind forward test runs once, planned for {when}.

Next: one session with a licensed feed measures the stamp lag. If the umpire lags about three seconds and data costs less than the book can pay, it pays; if not, the speed belongs to someone else. Thank you.

[Status at build time: forward test {fwd}; live session {live_status}.]
[If asked about reproducing the CV calls: the frozen call model (models/vision/frozen_call_model.pkl) is not in git; hpg/engine_vision.sbatch rebuilds it on HiPerGator.]
""")


# --------------------------------------------------------------------------------------------
# Q&A backup: the ten hardest questions (research/compliance/JUDGE.md section 5), honest answers
# --------------------------------------------------------------------------------------------


N_BACKUP = 14


def slide_q(prs, n, q, short, full, bullets, evidence, sources, ref="research/compliance/JUDGE.md"):
    slide_ctx(f"{n} Q{q}")
    s = new_slide(prs)
    eyebrow(s, f"Q&A BACKUP  ·  Q{q} OF {N_BACKUP}  ·  {ref}")
    set_title(s, short, size=30)
    text(s, M, 1.68, 7.6, 0.75, P(R(f"“{full}”", 13, MUTED, italic=True)), name="Question")
    paras = []
    for i, b in enumerate(bullets):
        runs = [R("•  ", 14, RED, bold=True)] + [r if isinstance(r, R) else R(r, 14, INK) for r in
                                                  (b if isinstance(b, list) else [b])]
        paras.append(P(*runs, before=0 if i == 0 else 8))
    text(s, M, 2.5, 7.6, 4.35, paras, name="Answer")
    cx = M + 7.6 + 0.4
    cw = SW - M - cx
    box(s, cx, 1.68, cw, 5.2, fill=WHITE, line=LINE, radius=0.08, shadow=True, name="Evidence card")
    ep = [P(R("EVIDENCE", 11, BLUE, bold=True, spc=1.4))]
    for big, cap in evidence:
        ep.append(P(R(big, 24, RED if big.startswith(MINUS) or "FAIL" in big else BLUE, bold=True, font=HEAD),
                    before=8))
        ep.append(P(R(cap, 11.5, INK)))
    ep.append(P(R("Sources: " + "; ".join(sources), 9.5, MUTED, font=MONO), before=10))
    text(s, cx + 0.22, 1.78, cw - 0.44, 5.0, ep, name="Evidence")
    footer(s, n)
    notes(s, f"BACKUP Q{q}: {full}\n\nAnswer in this order:\n" + "\n".join(
        "- " + ("".join(r.text if isinstance(r, R) else r for r in b) if isinstance(b, list) else b)
        for b in bullets) + "\n\n[Sources: " + "; ".join(sources) + "]")


def appendix(prs, n0):
    B = lambda t: R(t, 14, INK, bold=True)  # noqa: E731
    wf = lambda: wf_months()[0] + wf_months()[1]  # noqa: E731

    # Q1
    n = n0
    slide_ctx(f"{n} Q1")
    os5 = V(F_CAUSAL, OS5, "per_share_c", f=cents)
    os5ci = V(F_CAUSAL, OS5, "per_share_ci_c", f=ci)
    copy = D(lambda: f"{sum(m['follow_res_c'] < 0 for m in wf())}/{len(wf())}", WF_SRC + "  [follow_res_c < 0]")
    slide_q(prs, n, 1, "Isn't filling at the fast tier's print lookahead?",
            "Table 2 fills at the fast tier's own print. You only know that print exists because it happened. "
            "Isn't that lookahead, and isn't this someone else's P&L?",
            [[B("Yes, it is their speed, and we say so. "), "v2 measures the opportunity for a trader as fast as "
              "the fast tier, not our execution."],
             "What gets counted uses no future information: wallets qualify on past months only, the fee filter "
             "uses the fee at the time, and the 0–3 s window runs from detection, not hindsight onset (D9).",
             [B("The executable lagged copy loses: "), f"the same trades ~3 s later lose in {copy} months."],
             [B("Out of sample, second place earns nothing: "), f"+½ tick gives {os5} {os5ci}."],
             "Our own route to first place is tier 0, which we only model as a labelled counterfactual."],
            [(copy, "months the 3 s-late copy lost money"), (os5, f"burned OOS at +½ tick {os5ci}")],
            [F_SUM, F_CAUSAL])

    # Q2
    n += 1
    slide_ctx(f"{n} Q2")
    v1 = V(F_SUM, "oos", "h6_shadow", "total_pnl_usd", f=usd_signed_k)
    first_peek = D(lambda: peeks()[0][:16].replace("T", " ") + " UTC", F_PEEKS + "  [first line timestamp]")
    u2is = V(F_EXP, "primary", "u2_is", "per_share_c", f=cents)
    u2isci = V(F_EXP, "primary", "u2_is", "per_share_ci_c", f=ci)
    u2os = V(F_EXP, "primary", "u2_oos", "per_share_c", f=cents)
    u2osci = V(F_EXP, "primary", "u2_oos", "per_share_ci_c", f=ci)
    u2n = V(F_EXP, "universe", "u2_markets", f=intc)
    npk = D(lambda: intc(len(peeks())), F_PEEKS + "  [non-empty lines]")
    slide_q(prs, n, 2, "Isn't v2 tuned on the out-of-sample window?",
            f"You built v2 after v1 lost {v1.lstrip('+' + MINUS)} out of sample. Isn't that tuning on the "
            "out-of-sample period?",
            [[B("The OOS was opened once, blind, for v1 "), f"({first_peek}); v1's {v1} loss is reported."],
             "v2's rules were tuned on in-sample data only, but its motivation came from how v1 failed. So that "
             "window is burned, and every v2 number on it is labelled non-blind.",
             [B("v2's clean tests are pre-registered. "), f"Blind, on {u2n} never-examined markets: {u2is} {u2isci} "
              f"in the in-sample period (pass); {u2os} {u2osci} out of sample: a fail by our rule."],
             f"The forward window is run once, planned for {D(fwd_when, FWD_WHEN_SRC)}, and reported either way.",
             f"All {npk} looks at held-out data are in results/oos_peeks.log."],
            [(v1, "v1 on the held-out window, opened once"), (f"{u2os} FAIL", f"blind U2 OOS {u2osci}"),
             (npk, "logged looks at held-out data")],
            [F_SUM, F_EXP, F_PEEKS])

    # Q3
    n += 1
    slide_ctx(f"{n} Q3")
    sh_old = V(F_SUM, "v2_onset_superseded", "is_eval", "sharpe_ann", f=sh1)
    sh_is = V(F_CAUSAL, IS0, "sharpe_ann", f=sh1)
    per_day = D(lambda: intc(raw(F_CAUSAL, IS0, "n_trades") / raw(F_CAUSAL, IS0, "days")),
                key_str(F_CAUSAL, IS0) + "  [n_trades / days]")
    skew = V(F_NM, "is", "skew", f=lambda x: f"{x:.2f}")
    kurt = V(F_NM, "is", "kurtosis_pearson", f=lambda x: f"{x:.1f}")
    wd = V(F_NM, "is", "worst_day_pct", f=pct1)
    s5 = V(F_CAUSAL, IS5, "sharpe_ann", f=sh1)
    s10 = V(F_CAUSAL, IS10, "sharpe_ann", f=sh1)
    sc2 = V(F_NM, "is", "costs_x2_sharpe", f=sh1)
    so = V(F_CAUSAL, OS0, "sharpe_ann", f=sh1)
    soci = V(F_RIGOR, "bootstrap", "v2_oos", "sharpe_ann_ci95", f=lambda p: ci(p, 1))
    netcap = V(F_ENG_DEMO, "risk_config", "net_cap_shares", f=intc)
    slide_q(prs, n, 3, f"A Sharpe of {sh_is} on daily data? Assume a bug",
            f"A Sharpe of {sh_is} on daily data. The brief says above 3, assume a bug.",
            [[B("We assumed one and found one: "), f"the onset hindsight (D9). Fixing it cut the in-sample Sharpe "
              f"from {sh_old} to {sh_is}."],
             [B("What remains is structural: "), f"about {per_day} small bets a day, each settled by an exogenous "
              f"binary outcome, net exposure capped at {netcap} shares per match."],
             f"Tails are mild: skew {skew}, kurtosis {kurt}, worst day {wd}.",
             [B("It falls fast with costs: "), f"Sharpe {s5} at +½ tick, {s10} at +1 tick, {sc2} with all costs "
              f"doubled; burned OOS {so} (bootstrap {soci})."]],
            [(f"{sh_old} → {sh_is}", "in-sample Sharpe before / after the D9 fix"),
             (sc2, "in-sample Sharpe, all costs doubled"), (so, f"burned-OOS Sharpe, CI {soci}")],
            [F_SUM, F_CAUSAL, F_NM, F_RIGOR])

    # Q4
    n += 1
    slide_ctx(f"{n} Q4")
    bps_is = V(F_NM, "is", "fee_bps_of_notional", f=lambda x: f"{x:.0f} bps")
    bps_os = V(F_NM, "burned_oos", "fee_bps_of_notional", f=lambda x: f"{x:.0f} bps")
    f2is = V(F_COST, "is_eval/fee_x2", "per_share_c", f=cents)
    f2ism = D(lambda: f"{raw(F_COST, 'is_eval/fee_x2', 'months_positive')}/{raw(F_COST, 'is_eval/fee_x2', 'months_total')}",
              key_str(F_COST, "is_eval/fee_x2") + "  [months_positive/months_total]")
    f2os = V(F_COST, "burned_oos/fee_x2", "per_share_c", f=cents)
    f2osci = V(F_COST, "burned_oos/fee_x2", "per_share_ci_c", f=ci)
    f2osm = D(lambda: f"{raw(F_COST, 'burned_oos/fee_x2', 'months_positive')}/{raw(F_COST, 'burned_oos/fee_x2', 'months_total')}",
              key_str(F_COST, "burned_oos/fee_x2") + "  [months_positive/months_total]")
    c2is = V(F_COST, "is_eval/costs_x2", "per_share_c", f=cents)
    c2os = V(F_COST, "burned_oos/costs_x2", "per_share_c", f=cents)
    be = D(lambda: frac_pct1(raw(F_FIN, "strategies", "v2", "periods", "OOS", "breakeven_taker_fee",
                                 "rate_before_fixed_costs")),
           key_str(F_FIN, "strategies", "v2", "periods", "OOS", "breakeven_taker_fee", "rate_before_fixed_costs"))
    slide_q(prs, n, 4, "What happens when costs double?",
            "What happens when costs double? What is your cost in bps?",
            [[B("Fees: "), f"each match's own rate × q(1−q): about {bps_is} of notional in sample (mixed fee "
              f"regimes) and {bps_os} out of sample (all at today's rate)."],
             [B("Fees doubled: "), f"{f2is} in sample ({f2ism} months), but {f2os} {f2osci} out of sample "
              f"({f2osm} months)."],
             [B("All costs doubled: "), f"{c2is} in sample and {c2os} out of sample."],
             [B("So in today's regime the edge does not survive doubled costs, "), f"and we say so. Break-even "
              f"taker fee rate on the burned OOS, before fixed costs: {be}."],
             "That is why venue rules are risk R11 and why the halve/stop rule exists."],
            [(f2os, f"burned OOS with fees doubled {f2osci}"), (c2os, "burned OOS with all costs doubled"),
             (be, "break-even taker fee rate (OOS, before fixed costs)")],
            [F_NM, F_COST, F_FIN])

    # Q5
    n += 1
    slide_ctx(f"{n} Q5")
    vol = V(F_SUM, "universe", "volume_usd", f=usd_b)
    sent = V(F_ENG_LIVE, "orders_sent", f=intc)
    slide_q(prs, n, 5, "Is Polymarket allowed here, and from the US?",
            "Is Polymarket even allowed in this track, and can you trade it from the US?",
            [[B("The track allows any liquid, publicly traded market. "), f"Polymarket tennis has a public order "
              f"book, keyless public data, and {vol} traded in our universe."],
             [B("The international venue restricts US persons, "), "and we say so. TERMS 5.3 forbids funded accounts "
              "during the event, so everything here is paper."],
             [B("The repo only reads public data. "), f"The engine is paper-only by construction (orders sent in the "
              f"live run: {sent}); it refuses to start if a key or live flag exists."],
             "A deployment needs a permitted venue, licensed data and legal review (docs/RISK.md R16).",
             "Kalshi, the regulated alternative, leads most repricings, but its fee leaves the hedged laggard "
             "trade at about zero (research/v2/kalshi/RESULTS.md)."],
            [(vol, "traded in the study universe (public data)"), (sent, "orders sent by the engine")],
            [F_SUM, F_ENG_LIVE, "docs/RISK.md R16"])

    # Q6
    n += 1
    slide_ctx(f"{n} Q6")
    pos = D(lambda: f"{sum(m['net30_c'] > 0 for m in wf())}/{len(wf())}", WF_SRC + "  [net30_c > 0]")
    w0 = D(lambda: intc(wf()[0]["n_wallets"]), WF_SRC + "  [first month n_wallets]")
    w1 = D(lambda: intc(wf()[-1]["n_wallets"]), WF_SRC + "  [last month n_wallets]")
    e0 = D(lambda: cents1(wf()[0]["net30_c"]), WF_SRC + "  [first month net30_c]")
    e1 = D(lambda: cents1(wf()[-1]["net30_c"]), WF_SRC + "  [last month net30_c]")
    g_is = V(F_EXP, "fast_minus_others_u2", "u2_is", "fast_minus_others_c", f=cents)
    g_os = V(F_EXP, "fast_minus_others_u2", "u2_oos", "fast_minus_others_c", f=cents)
    g_osci = V(F_EXP, "fast_minus_others_u2", "u2_oos", "ci_c", f=ci)
    lag = V(F_T0, "timing", "calibrated_stamp_lag_s (inference)", f=lambda x: f"{x:.1f} s")
    slide_q(prs, n, 6, "Who is the fast tier, and why does the edge survive?",
            "Who is the fast tier, and why hasn't competition killed the edge?",
            [[B("We can't identify them; we can characterize them: "), f"they trade within 3 s of a detected point, "
              f"and selected walk-forward they made money in {pos} months."],
             [B("They replicate blind: "), f"on unseen markets they beat everyone else by {g_is} in sample and "
              f"{g_os} {g_osci} out of sample."],
             f"Someone knows the point before the book. Courtside humans would imply an official-stamp lag of "
             f"about {lag}, but that is an inference, not a measurement.",
             [B("Competition is biting: "), f"the 30 s edge went from {e0} in the first month to {e1} in the last; "
              f"qualifying wallets grew from {w0} to {w1}. It shrank but stayed positive."]],
            [(pos, "months the fast tier made money, walk-forward"), (g_os, f"fast minus others, blind OOS {g_osci}"),
             (f"{e0} → {e1}", "edge per share, first vs last month")],
            [F_SUM, F_EXP, F_T0])

    # Q7
    n += 1
    slide_ctx(f"{n} Q7")

    def dsr_q(series, key):
        def fn():
            rows = raw(F_RIGOR, "psr_dsr", "rows")
            i = next(i for i, r in enumerate(rows) if r["series"] == series)
            return dsr3(raw(F_RIGOR, "psr_dsr", "rows", i, "dsr", key, "dsr"))
        return D(fn, f"{F_RIGOR} :: psr_dsr > rows > [series={series}] > dsr > {key} > dsr")
    nall = V(F_RIGOR, "psr_dsr", "N", "all_plus_v2safe_grid", f=intc,
             how="NOTE section 8 counts 3,386; plus the 24-variant v2-safe grid")
    nh = V(F_RIGOR, "psr_dsr", "N", "H1_H6", f=intc)
    t_os7 = V(F_RIGOR, "sharpe_moments", "v2_oos", "T_days", f=intc)

    def dsr_mq(series, n_key):
        def fn():
            rows = raw(F_RIGOR, "psr_dsr", "rows")
            i = next(i for i, r in enumerate(rows) if r["series"] == series)
            return dsr3(raw(F_RIGOR, "psr_dsr", "rows", i, f"dsr_min_{n_key}"))
        return D(fn, f"{F_RIGOR} :: psr_dsr > rows > [series={series}] > dsr_min_{n_key}")
    d_is = dsr_mq("v2_is", "N3410")
    d_os_h = dsr_mq("v2_oos", "N44")
    d_os_all = dsr_mq("v2_oos", "N3410")
    pbo_sz = V(F_RIGOR, "pbo_cscv", "sizing_55_res_actual_sharpe", "pbo", f=frac_pct1)
    pbo_sf = V(F_RIGOR, "pbo_cscv", "lowloss_24_sharpe", "pbo", f=frac_pct1)
    pbo_sel = V(F_RIGOR, "pbo_cscv", "lowloss_24_selection_rule", "pbo", f=frac_pct1)
    slide_q(prs, n, 7, "With this many variants, isn't it the luckiest draw?",
            f"You tried {nall} or more variants. Why isn't this the luckiest draw?",
            [[B("Every variant is counted and reported: "), f"N = {nall}."],
             [B("In sample the deflated Sharpe at that N is "), f"{d_is}, even with the most conservative variance."],
             [B(f"On the {t_os7}-day burned OOS it is "), f"{d_os_h} at N = {nh} and {d_os_all} at N = {nall}. "
              f"{t_os7} days cannot rule out luck at the full trial count, and we say that."],
             f"Probability of backtest overfitting: {pbo_sz} on the sizing grid, {pbo_sf} by Sharpe on the v2-safe "
             f"grid, {pbo_sel} by its selection rule.",
             "Many variants are near-duplicates, so N overstates independent trials. The real answer is the "
             "forward test."],
            [(d_is, f"DSR in sample, N = {nall}"), (d_os_all, f"DSR burned OOS, N = {nall}"),
             (pbo_sf, "PBO, v2-safe grid by Sharpe")],
            [F_RIGOR])

    # Q8
    n += 1
    slide_ctx(f"{n} Q8")
    om = V(F_NM, "holdout", "oos_matches", f=intc)
    tm = V(F_NM, "holdout", "matches", f=intc)
    ov = V(F_NM, "holdout", "oos_share_of_volume", f=frac_pct0)
    od = V(F_NM, "holdout", "oos_days", f=lambda x: f"{x:.1f}")
    od_utc = V(F_CAUSAL, OS0, "days", f=intc, how="UTC dates with trades in the burned OOS window")
    sd = V(F_NM, "holdout", "span_days", f=lambda x: f"{x:.0f}")
    t20 = V(F_NM, "holdout", "time_based_20pct_start", f=lambda s_: s_[:10])
    thr_pnl = V(F_RISK, "universe_volume_filter", "burned_oos", "$5-20k", "per_share_c", f=cents)
    u2n = V(F_EXP, "universe", "u2_markets", f=intc)
    share_m = D(lambda: frac_pct0(raw(F_NM, "holdout", "oos_matches") / raw(F_NM, "holdout", "matches")),
                key_str(F_NM, "holdout") + "  [oos_matches / matches]")
    thr = D(lambda: rx(F_RISK, ("universe_volume_filter", "note"), r">= (\$\d+k)"),
            key_str(F_RISK, "universe_volume_filter", "note") + "  [volume threshold quoted in the note field]")
    slide_q(prs, n, 8, "Is the holdout survivorship-biased?",
            f"Your OOS is {share_m} of matches but only {od} of {sd} days, and your universe keeps matches with at "
            f"least {thr} of lifetime volume, which you only know afterwards. Isn't that survivorship and lookahead?",
            [[B(f"We read “{share_m}” as a share of observations: "), f"{om} of {tm} matches, {ov} of volume. By calendar time "
              f"it is {od} of {sd} days ({od_utc} UTC dates, the count slides 5 and 6 use); a time-based 20% would "
              f"start {t20}."],
             [B("The volume filter is ex-post. "), f"It drops thin markets a live trader would see. The OOS trades "
              f"nearest the threshold made {thr_pnl} a share."],
             [B("Our check is the blind test on "), f"{u2n} other markets (mostly ITF): the fast-tier gap holds there; "
              "v2's out-of-sample interval includes zero."],
             "H1–H6 use onset-aligned windows: an ex-post event study, labelled as such. Every tradable v2 number "
             "uses the causal window."],
            [(f"{om}/{tm}", f"matches held out ({ov} of volume)"), (f"{od} of {sd}", "days held out"),
             (u2n, "unseen markets in the blind test")],
            [F_NM, F_RISK, F_EXP])

    # Q9
    n += 1
    slide_ctx(f"{n} Q9")
    pdx = V(F_NM, "is", "usd_traded_per_day", f=usd_k)
    trd = V(F_CAUSAL, IS0, "usd_traded", f=usd_m)
    dys = V(F_CAUSAL, IS0, "days", f=intc)
    capq = V(F_CAUSAL, IS0, "capital_usd", f=usd_k)
    medq = V(F_RISK, "liquidity_capital", "is_eval", "usd_per_trade_quantiles", "0.5", f=lambda x: f"${x:.2f}")
    cis = V(F_FIN, "strategies", "v2", "ceiling", "IS", "fast_tier_qualified_print_usd_per_day", f=usd_k)
    cos = V(F_FIN, "strategies", "v2", "ceiling", "OOS", "fast_tier_qualified_print_usd_per_day", f=usd_k)
    t1is = V(F_RISK, "concentration", "is_eval", "wallet", "top1_share_of_net_pct", f=pct1)
    t1os = V(F_RISK, "concentration", "burned_oos", "wallet", "top1_share_of_net_pct", f=pct1)
    wci = V(F_PMC, "p07_wallet_clustered_ci", "burned_oos", "ci95_c_wallet_clustered", f=ci)
    covo = V(F_FIN, "strategies", "v2", "coverage", "OOS")
    slide_q(prs, n, 9, "How much capital could this run?",
            "How much capital could this run, and doesn't it hang on a handful of wallets?",
            [[B("Not much. "), f"v2 ran about {pdx} a day of notional ({trd} in {dys} days) on {capq} of capital; "
              f"median trade {medq}."],
             [B("Capacity is bounded by the fast tier's own prints, "), f"not book depth: every qualifying print "
              f"totals {cis}/day in sample and {cos}/day out of sample."],
             [B("Concentration is real: "), f"the top wallet carries {t1is} of in-sample P&L and {t1os} out of sample. "
              f"Clustered by wallet, the burned-OOS CI is {wci}."],
             f"Does it cover central fixed costs out of sample? {covo[0].upper() + covo[1:] if covo else covo}. That is why we say “positive but not proven”."],
            [(pdx, "notional per day, in sample"), (cis, "outer ceiling per day (IS)"),
             (wci, "burned-OOS ¢/share, wallet-clustered CI")],
            [F_NM, F_CAUSAL, F_RISK, F_FIN, F_PMC])

    # Q10 (live causal engine first; the offline evaluation only with its look-ahead caveat)
    n += 1
    slide_ctx(f"{n} Q10")
    ec = ("early_call", "precision_recall_test_snapshot", "50ms")
    calls = D(lambda: f"{raw(F_TRACK, *ec, 'tp')}/{raw(F_TRACK, *ec, 'tp') + raw(F_TRACK, *ec, 'fp')}",
              key_str(F_TRACK, *ec) + "  [tp/(tp+fp), OFFLINE, look-ahead feature]")
    A = ("runs", OVO_RUN, "A_engine_calls")
    e_tp = V(F_OVO, *A, "online", "50ms", "tp", f=intc)
    e_nmiss = V(F_OVO, *A, "miss_first_call_lead_ms", "n_miss", f=intc)
    e_lead = V(F_OVO, *A, "miss_first_call_lead_ms", "median", f=lambda x: f"{x:g} ms")
    e_lb = V(F_OVO, *A, "online", "50ms", "precision_wilson95", f=lambda p: frac_pct0(p[0]))
    e_calls = D(lambda: f"{raw(F_OVO, *A, 'online', '50ms', 'tp')}/"
                        f"{raw(F_OVO, *A, 'online', '50ms', 'tp') + raw(F_OVO, *A, 'online', '50ms', 'fp')}",
                key_str(F_OVO, *A, "online", "50ms") + "  [tp/(tp+fp), live causal engine]")
    F_CCV = "results/redteam/causal_cv.json"
    usd = lambda x: ("+" if x >= 0 else MINUS) + f"${abs(x):.0f}"  # noqa: E731
    c_is = V(F_CCV, "cells_V1", "tournament", "IS", "usd_per_day", f=usd)
    c_os = V(F_CCV, "cells_V1", "tournament", "burned_OOS", "usd_per_day", f=usd)
    p_is = V(F_SWEEP, "video_cv_pessimistic", "tournament", "1", "IS", "usd_per_day", f=usd)
    p_os = V(F_SWEEP, "video_cv_pessimistic", "tournament", "1", "burned_OOS", "usd_per_day", f=usd)
    ph = V(F_RT, "keys", "eng.phantom_miss_per_hour", "value", f=lambda x: f"{x:.0f}")
    ph_b = V(F_RT, "keys", "eng.phantom_budget_per_day.cal", "value", f=lambda x: f"{x:.0f}")
    slide_q(prs, n, 10, "What does the computer vision actually add?",
            "Your call model was scored with a look-ahead feature. Causally, how good is it, and what does it add?",
            [[B("The live engine is causal; the offline evaluation was not. "), f"Streamed at 120 fps on one GPU, it "
              f"called {e_tp} of {e_nmiss} held-out misses before contact, all correct (lower bound {e_lb}), median "
              f"lead {e_lead}. The offline {calls} at 50 ms used a look-ahead feature."],
             [B("At a 1 s feed the lead barely matters: "), f"with the live engine's own call table the pre-registered "
              f"1 s cell is {c_is}/day in sample and {c_os} held out; with no early calls at all, {p_is} and {p_os}."],
             [B("It also fires between rallies: "), f"about {ph} MISS calls an hour on balls outside the scored set; "
              f"the post hoc 1 s P&L survives only ~{ph_b} phantom trades a day. A rally-state gate is now in "
              "the strategy (off by default, not yet evaluated on the event log); it comes before any live trade."],
             [B("The contribution is the time budget: "), "where a lead comes from (frame rate, cameras, being in the "
              "venue), and proof that the call fits easily inside the venue's 1 s hold."]],
            [(e_calls, f"live causal engine, held-out misses called correctly ({e_tp} of {e_nmiss})"),
             (c_os, "pre-registered 1 s cell, held out, engine call table"),
             (ph, "phantom MISS calls per hour, ungated")],
            [F_OVO, F_CCV, F_SWEEP, F_RT], ref="docs/QA_PREP.md Q10")

    # Q11-Q14 (docs/QA_PREP.md): the attacks that can cap Performance, and the organizers' two questions
    usd2 = lambda x: ("+" if x >= 0 else MINUS) + f"${abs(x):.0f}"  # noqa: E731
    vo = ("video_own120",)
    pre_os = V(F_SWEEP, *vo, "tournament", "1", "burned_OOS", "usd_per_day", f=usd2)
    pre_c = V(F_SWEEP, *vo, "tournament", "1", "burned_OOS", "net_c_per_share", f=cents)
    cal_os = V(F_SWEEP, *vo, "tournament_lagcal", "1", "burned_OOS", "usd_per_day", f=usd2)
    stc_os = V(F_SWEEP, *vo, "stamp_calibrated", "1", "burned_OOS", "usd_per_day", f=usd2)
    RTv = lambda k, f=None: V(F_RT, "keys", k, "value", f=f)  # noqa: E731
    lag_ci = RTv("cv.L_boot_ci", f=lambda p_: f"[{p_[0]:.2f}, {p_[1]:.2f}] s")
    below = RTv("cv.L_boot_share_below_2_5", f=frac_pct0)
    max_tb = RTv("cv.stc.max_tb", f=lambda x: f"{x:.2f} s")
    arr = RTv("cv.stc.arrival_min_v1", f=lambda x: f"{x:.2f} s")
    hv = ("headline_by_V", "V1", "all")
    rp_c = V(F_REPLAY, *hv, "per_share_mark_c", f=cents)
    rp_ci = V(F_REPLAY, *hv, "per_share_mark_ci95_c", f=ci)
    rp_neg = D(lambda: f"{sum(c['all']['per_share_mark_c'] < 0 for c in raw(F_REPLAY, 'cells').values())} of "
                       f"{len(raw(F_REPLAY, 'cells'))}", key_str(F_REPLAY, "cells") + "  [per_share_mark_c < 0]")
    p482 = RTv("cv.pool482.oos.c", f=cents)
    p482ci = RTv("cv.pool482.oos.ci", f=ci)

    n += 1
    slide_ctx(f"{n} Q11")
    slide_q(prs, n, 11, "Isn't the CV trade set chosen on outcomes?",
            "Your simulated CV trader only trades points the market later moved by 4¢ or more. How would a live "
            "trader know which points those are? Isn't that lookahead?",
            [[B("Yes, and we label it: "), "the sweep trades only points the market later repriced by ≥ 4¢, so it "
              "prices speed given a point worth trading. It is not yet a deployable rule, and every number from it is "
              "an upper bound."],
             [B("Our ex-ante test is the replay: "), f"on nine books recorded live, calling every point, {rp_neg} "
              f"delay × lag cells lose; {rp_c} a share {rp_ci} at V = 1 s."],
             [B("Widening the pool to all 482 live points "), f"roughly halves the edge: {p482} {p482ci} held out, "
              "even with our own camera (V = 0)."],
             "Next: an ex-ante filter from the Markov point leverage, its threshold fixed at the detector's 4¢, run "
             "once on the replay with a logged look."],
            [(rp_neg, "replay cells that lose (every point called ex ante)"), (rp_c, f"replay at V = 1 s {rp_ci}"),
             (p482, "all-482-point pool, held out, V = 0")],
            [F_REPLAY, F_RT, "research/v2/tier0/RESULTS.md §8"], ref="docs/QA_PREP.md Q4")

    n += 1
    slide_ctx(f"{n} Q12")
    slide_q(prs, n, 12, "Why headline a post hoc lag? The same inference loses",
            "The 3.14 s stamp lag was inferred after the pre-registered 2.0 s gave a held-out Sharpe of 0.3, and read "
            "point by point the same inference loses. Isn't that tuning on the out-of-sample period?",
            [[B("We lead with the pre-registered reading: "), f"at 1 s it breaks even, {pre_os}/day held out, "
              f"{pre_c} a share."],
             [B("The 3.14 s lag is post hoc: "), f"inferred from fast-tier prints assuming courtside humans; "
              f"{cal_os}/day held out. Its bootstrap CI is {lag_ci}, and {below} of resamples fall below 2.5 s."],
             [B("Read per point, the same inference loses "), f"{stc_os}/day: every reprice lands at most {max_tb} "
              f"after the bounce, before a 1 s order can arrive ({arr})."],
             "Both readings use the per-tournament timing adopted after the first P&L run (DEVIATIONS V3); the "
             "headline lag and the 1 s baseline were chosen after looking, and we count them as post hoc trials."],
            [(pre_os, "pre-registered, held out, $/day"), (cal_os, "post hoc lag, held out, $/day"),
             (stc_os, "same inference per point, held out, $/day")],
            [F_SWEEP, F_RT, "results/redteam/stamp_lag.json", "DEVIATIONS.md V3"], ref="docs/QA_PREP.md Q5, Q6")

    n += 1
    slide_ctx(f"{n} Q13")
    bg = ("budget_with_1s_simulated_feed",)
    e_ours = V(F_E2E, *bg, "ours_capture_to_order_ready_ms", "p50", f=lambda x: f"{x:,.0f} ms")
    e_net = V(F_E2E, *bg, "network_one_way_ms", "p50", f=lambda x: f"{x:,.0f} ms")
    e_tot = V(F_E2E, *bg, "total_ms", "p50", f=lambda x: f"{x:,.0f} ms")
    e_n = V(F_E2E, "our_pipeline_frame_to_order_ready_ms", "n", f=intc)
    e_cnd = V(F_E2E, *bg, "conditions", "sentence")
    H = ("headline", OVO_RUN, "stream")
    g50 = V(F_OVO, *H, "after_startup", "call_ready_ms", "p50", f=lambda x: f"{x:.1f} ms")
    g99 = V(F_OVO, *H, "after_startup", "call_ready_ms", "p99", f=lambda x: f"{x:.1f} ms")
    gdr = V(F_OVO, *H, "dropped", f=intc)
    cbs = RTv("cv.call_before_stamp", f=lambda x: f"{x:.1f} s")
    slide_q(prs, n, 13, "Prove you can trade inside 3 s",
            "You need sub-3-second data. Prove the pipeline can actually trade that fast, frame to order.",
            [[B("Measured end to end, in one process: "), f"our footage over WebRTC into the vision engine, a call, a "
              f"paper order on a live tennis book. Video in → order ready: {e_ours} on a laptop ({e_n} traces). With "
              f"a simulated 1 s feed, the network ({e_net}) and the venue's 1 s hold: {e_tot}, under 3,000 ms. "
              f"Conditions: {e_cnd}."],
             [B("On a GPU the vision call is ready in "), f"{g50} (p99 {g99}) at 120 fps, {gdr} frames dropped."],
             [B("3 s is not the real bar: "), f"the call must beat the umpire's stamp by about {cbs}; from a 3 s "
              "feed delay every reading loses."],
             "Paper only: the order payload is unsigned and never sent; table-tennis calls are mapped onto a tennis "
             "market for timing only (different sport)."],
            [(e_tot, "frame → executable order, p50, incl. simulated 1 s feed and 1 s venue hold (timing probes; "
                     "CV fed at 10 frames/s)"),
             (e_ours, "our part: video in → paper order ready"), (g50, "GPU vision call-ready, p50")],
            [F_E2E, F_OVO, F_RT], ref="organizer question 1 · docs/QA_PREP.md Q1")

    n += 1
    slide_ctx(f"{n} Q14")
    v2cap = V(F_ALPHA, "headline", "oos_capital_capacity_usd", f=lambda p_: f"{usd_k(p_[0])}–{usd_k(p_[1])}")

    def _half(name, key):       # capital where the Sharpe halves (capacity study, results/capacity/capacity.json)
        return raw(F_CAP, "answers", name, key, "capital_where_sharpe_halves_usd")

    def _krng(name_a, name_b, key):
        lo_, hi_ = sorted([_half(name_a, key), _half(name_b, key)])
        return f"{usd_k(lo_)}–{usd_k(hi_)}"
    k10o, k10i = "lagcal|phi0.5|cov10|g1|burned_OOS", "lagcal|phi0.5|cov10|g1|IS"
    kalo = "lagcal|phi0.5|covall|g1|burned_OOS"
    cvcap = D(lambda: _krng("cv_prorata", "cv", k10o),
              key_str(F_CAP, "answers", "cv_prorata / cv", k10o, "capital_where_sharpe_halves_usd"))
    cvcap_is = D(lambda: _krng("cv_prorata", "cv", k10i),
                 key_str(F_CAP, "answers", "cv_prorata / cv", k10i, "capital_where_sharpe_halves_usd"))
    cvcap_all = D(lambda: _krng("cv_prorata", "cv", kalo),
                  key_str(F_CAP, "answers", "cv_prorata / cv", kalo, "capital_where_sharpe_halves_usd"))
    pre_sh = V(F_CAP, "answers", "cv", "prereg|phi0.5|cov10|g1|burned_OOS", "sharpe_ref_smallest_size",
               f=lambda x: f"{x:.1f}")
    mx_cal = RTv("cv.cal.oos.maxlic", f=usd0)
    mx_pre = RTv("cv.pre.oos.maxlic", f=usd0)
    lic_lo = V(F_FIN, "cost_assumptions", "feed_licence", "low", f=usd0)
    lic_hi = V(F_FIN, "cost_assumptions", "feed_licence", "high", f=usd0)
    netc = RTv("cv.cal.oos.net_central", f=usd2)
    slide_q(prs, n, 14, "How much capital, and what's left after data?",
            "How much capital can this run, and after paying for the data, what do you make?",
            [[B("Capital: small. "), f"v2's held-out edge holds up to about {v2cap} of capital (1–2× its frozen "
              "size); five times the size loses."],
             [B("The CV book at 1 s "), f"(post hoc 3.14 s lag, 10 matches a day) runs up to {cvcap} held out ({cvcap_is} "
              f"in sample) before its Sharpe halves; the range is how we share stale depth with the fast tier. Every "
              f"match: {cvcap_all}. Pre-registered lag: Sharpe {pre_sh} held out, no capacity."],
             [B("Data: "), f"the 1 s book can pay at most {mx_cal}/month (post hoc) or {mx_pre} (pre-registered); "
              f"quotes run {lic_lo}–{lic_hi}/month (ASSUMPTION). Net of the central stack it is {netc}/day post hoc."],
             "At today's 5% fee COURTSIDE prices speed. It is not yet a business, and the paper says so."],
            [(v2cap, "capital where v2's held-out edge still holds"), (cvcap, "capital where the CV book's held-out "
              "Sharpe halves (1 s feed, post hoc lag)"), (mx_cal, "most the 1 s book can pay for data a month (post hoc)")],
            [F_ALPHA, F_RT, F_FIN, F_CAP], ref="organizer question 2 · docs/QA_PREP.md Q2, Q12")
    return n


def manifest_slides(prs, n0) -> int:
    """Hidden slides: every number on every slide, with the file and key it was read from."""
    seen, rows = set(), []
    for m in MANIFEST:
        k = (m["slide"], m["text"], m["source"])
        if k not in seen:
            seen.add(k)
            rows.append(m)
    per = 34
    pages = [rows[i:i + per] for i in range(0, len(rows), per)]
    for p, page in enumerate(pages):
        s = new_slide(prs)
        s._element.set("show", "0")
        eyebrow(s, f"HIDDEN MANIFEST  ·  PAGE {p + 1} OF {len(pages)}")
        set_title(s, "Every number on screen, and where it was read", size=26)
        lines = []
        for m in page:
            ln = f"{m['slide'][:26]:<26} {m['text'][:24]:<24} {m['source']}"
            lines.append(P(R(ln if len(ln) <= 178 else ln[:177] + "…", 7, INK, font=MONO)))
        text(s, M, 1.7, CW, 5.3, lines, name="Manifest")
        footer(s, n0 + p)
    return len(pages)


def export_pdf() -> str:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if not soffice and mac.exists():
        soffice = str(mac)
    if not soffice:
        return "PDF skipped: LibreOffice (soffice) not found"
    r = subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(DECK_DIR), str(OUT)],
                       capture_output=True, text=True, timeout=600)
    return f"wrote {OUT_PDF.relative_to(ROOT)}" if r.returncode == 0 and OUT_PDF.exists() else \
        f"PDF export failed: {r.stderr.strip()[:300]}"


def main() -> None:
    print("consistency checks ...")
    run_checks()
    prs = Presentation()
    setup_template(prs)
    prs.core_properties.title = "COURTSIDE: who gets paid in the seconds after a tennis point"
    prs.core_properties.subject = "Gator Quant Hacks 2026, Systematic Trading"
    prs.core_properties.author = "COURTSIDE"
    prs.core_properties.keywords = "tennis; Polymarket; latency; computer vision; paper trading"
    main_slides = (s01_title, s02_tiers, s03_evidence, s04_cv, s05_backtest, s06_rigor, s07_tier0, s08_engine,
                   s09_risk, s10_close)
    for i, build in enumerate(main_slides):
        build(prs, i + 1)
    last = appendix(prs, len(main_slides) + 1)
    n_q = last - len(main_slides)
    n_man = manifest_slides(prs, last + 1)
    add_sections(prs, [("Main talk (4:45)", len(main_slides)), ("Q&A backup", n_q), ("Manifest (hidden)", n_man)])
    prs.save(OUT)
    OUT_MANIFEST.write_text(json.dumps({
        "deck": str(OUT.relative_to(ROOT)), "talk_seconds": TALK_S, "slide_seconds": DUR_S,
        "numbers": MANIFEST, "pending": [{"slide": a, "source": b} for a, b in PENDING_ITEMS],
        "warnings": WARNINGS}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(prs.slides)} slides: {len(main_slides)} main, {n_q} backup, "
          f"{n_man} hidden manifest)")
    print(f"wrote {OUT_MANIFEST.relative_to(ROOT)}  ({len(MANIFEST)} numbers recorded)")
    print(export_pdf())
    if PENDING_ITEMS:
        print("PENDING (rendered as 'pending'):")
        for a, b in dict.fromkeys(PENDING_ITEMS):
            print(f"  slide {a}: {b}")
    for w in WARNINGS:
        print(f"WARNING: {w}")


if __name__ == "__main__":
    main()
