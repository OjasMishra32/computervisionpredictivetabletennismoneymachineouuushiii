#!/usr/bin/env python3
"""COURTSIDE pitch deck (Gator Quant Hacks 2026, Systematic Trading).

Rebuild from the repo root:

    .venv/bin/python docs/deck/build_deck.py

Writes docs/deck/courtside.pptx: 16:9, seven main slides for a five-minute talk, five backup
slides for Q&A, and a speaker script in every slide's notes.

Where the numbers come from
---------------------------
* Numbers that exist in results/*.json are read from those files at build time and formatted here
  (universe, v2 causal table, walk-forward months, leverage, tracking, H4, calibration).
* Numbers that only exist in the Markdown write-ups (latency, liquidity, risk limits) are literals,
  and every one is checked against its source file by need(...). If a source changes, the build
  stops instead of shipping a stale number.

The blind forward test has NOT run yet (it runs once, ~2026-10-04 11:30 UTC). Its cell on slide 5
shows a marked PLACEHOLDER and the pre-registered decision rule (HYPOTHESIS_V2 A1.5: Primary A and
Primary B, 30 s net markouts, pass iff the match-clustered 95% CI excludes 0), never a number. When
results/v2/forward.json exists, replace FORWARD_* and the [FWD_A] / [FWD_B] tokens by hand from that
file and rebuild. Resolution P&L is secondary for the forward window.

v2 is a paper book on the fast tier's own fills (docs/NOTE.md section 8); slides 5 and 6 say so.

Fonts: headings use Arial Narrow (bold), body Arial; both ship with Office and macOS. The Arial
Narrow runs carry its PANOSE class, so a machine without it substitutes a condensed sans
(e.g. Helvetica Neue Condensed, Liberation Sans Narrow) instead of a serif.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import (XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION,
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
# Sources
# --------------------------------------------------------------------------------------------
_TXT: dict[str, str] = {}


def _text(rel: str) -> str:
    if rel not in _TXT:
        _TXT[rel] = re.sub(r"\s+", " ", (ROOT / rel).read_text(encoding="utf-8"))
    return _TXT[rel]


def need(rel: str, *needles: str) -> None:
    """Fail the build unless every needle appears in the source file (whitespace-normalised)."""
    body = _text(rel)
    missing = [n for n in needles if re.sub(r"\s+", " ", n) not in body]
    if missing:
        sys.exit(f"[source check] {rel} no longer contains: {missing!r}")


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


SUMMARY = load("results/summary.json")
CAUSAL = load("results/v2/causal.json")
LEVER = load("results/leverage_stats.json")
TRACK = load("results/tracking/summary.json")
TENNIS_TRACK = load("results/tennis_tracking/summary.json")
DEMO = load("results/tracking/demo/manifest.json")
VIZ = load("results/viz/viz_data.json")

NOTE = "docs/NOTE.md"
DEVPOST = "docs/DEVPOST.md"
README = "README.md"
DEV = "DEVIATIONS.md"
HYP2 = "HYPOTHESIS_V2.md"
LAT = "research/v2/latency/RESULTS.md"
KAL = "research/v2/kalshi/RESULTS.md"
FILL = "research/v2/livefill/RESULTS.md"
XMKT = "research/v2/crossmarket/RESULTS.md"
TT_README = "src/tennis_tracking/README.md"


def signed(x: float, d: int = 2) -> str:
    return ("+" if x >= 0 else MINUS) + f"{abs(x):.{d}f}"


def num(x: float, d: int = 2) -> str:
    return (MINUS if x < 0 else "") + f"{abs(x):.{d}f}"


def ci(pair, d: int = 2) -> str:
    return f"[{num(pair[0], d)}, {num(pair[1], d)}]"


# ---- universe ----
U = SUMMARY["universe"]
N_MATCHES = f"{U['matches']:,}"
VOLUME = f"${U['volume_usd'] / 1e9:.2f}B"
assert (N_MATCHES, VOLUME) == ("13,084", "$2.84B"), (N_MATCHES, VOLUME)
need(NOTE, "13,084 matches, $2.84B traded", "≥$5k volume, Oct 2025–Oct 2026")

# ---- v2, causal window ----
V2 = {k.split("/", 1)[1]: v for k, v in CAUSAL.items() if k.startswith("causal/")}
ONSET = {k.split("/", 1)[1]: v for k, v in CAUSAL.items() if k.startswith("onset/")}
IS0, IS5, IS10 = (V2[f"is_eval/slip{s}"] for s in ("0.0", "0.005", "0.01"))
OS0, OS5, OS10 = (V2[f"burned_oos/slip{s}"] for s in ("0.0", "0.005", "0.01"))
assert signed(IS0["per_share_c"]) == "+1.38" and ci(IS0["per_share_ci_c"]) == "[1.17, 1.59]"
assert signed(OS0["per_share_c"]) == "+0.60" and ci(OS0["per_share_ci_c"]) == "[0.09, 1.13]"
need(NOTE, "+1.38¢ [1.17, 1.59]", "+0.60¢ [0.09, 1.13]", "14.5 / −2.0%", "6.7 / −2.1%")


def sharpe(r):
    return f"{r['sharpe_ann']:.1f}"


def dd(r):
    return f"{num(r['max_dd_pct'], 1)}%"


def months(r):
    return f"{r['months_positive']}/{r['months_total']}"


V1 = SUMMARY["oos"]["h6_shadow"]
V1_OOS_LOSS = V1["total_pnl_usd"]
assert round(V1_OOS_LOSS / 1000) == -36
V1_LOSS_TXT = f"{MINUS}${abs(V1_OOS_LOSS) / 1000:.1f}k"
V1_DD = f"{num(V1['max_dd'] * 100, 0)}%"
V1_WORST_DAY = f"{num(V1['worst_day_pct'], 1)}%"
assert (V1_LOSS_TXT, V1_DD, V1_WORST_DAY) == (f"{MINUS}$36.1k", f"{MINUS}75%", f"{MINUS}26.8%")
need(NOTE, "lost $36k out of sample")
CAPITAL_K = f"${IS0['capital_usd'] / 1000:.0f}k"
PEAK_K = f"${IS0['peak_locked_usd'] / 1000:.1f}k"
TRADED_M = f"${IS0['usd_traded'] / 1e6:.2f}M"
DAYS = IS0["days"]
PER_DAY = round(IS0["n_trades"] / DAYS, -1)
assert (CAPITAL_K, PEAK_K, TRADED_M, DAYS) == ("$28k", "$9.4k", "$1.48M", 206)
need(NOTE, "~$1.48M traded over 206 days on $28k capital", "peak locked $9.4k", "~270 small")
# Dollar P&L and return on the book's own capital (paper book at the fast tier's fills).
IS_PNL = f"+${IS0['total_pnl_usd'] / 1000:.1f}k"
IS_CAP = f"${IS0['capital_usd'] / 1000:.1f}k"
IS_ROC = f"+{IS0['return_on_capital_pct']:.0f}%"
OS_PNL = f"+${OS0['total_pnl_usd'] / 1000:.1f}k"
OS_CAP = f"${OS0['capital_usd'] / 1000:.1f}k"
OS_ROC = f"+{OS0['return_on_capital_pct']:.0f}%"
OS_DAYS = OS0["days"]
assert (IS_PNL, IS_CAP, IS_ROC, OS_PNL, OS_CAP, OS_ROC, OS_DAYS) == (
    "+$40.4k", "$28.3k", "+143%", "+$3.7k", "$22.8k", "+16%", 40)
need(NOTE, "+$40.4k / $28.3k", "+$3.7k / $22.8k")
WORST_DAY_IS, WORST_DAY_OS = f"{num(IS0['worst_day_pct'], 1)}%", f"{num(OS0['worst_day_pct'], 1)}%"
assert (WORST_DAY_IS, WORST_DAY_OS) == (f"{MINUS}1.9%", f"{MINUS}2.1%")
USD_PER_DAY = f"~${IS0['usd_traded'] / DAYS / 1000:.1f}k"
assert USD_PER_DAY == "~$7.2k"
N_VARIANTS = 44 + 3342
need(NOTE, "44 (H1–H6) plus 3,342")
# Worst match (−$205.76) is not in any results JSON: docs/NOTE.md section 6, and
# data/v2_trades_is_oos.parquet grouped by match (cond) and summed.
need(NOTE, "The worst historical match lost $206 (v1: $3,098)")

# ---- walk-forward fast tier (the 11 months plotted in fig3: IS Dec-Jul + OOS Aug-Oct) ----
WF = [m for m in SUMMARY["is"]["h6_walkforward"] if m["month"] < "2026-08"] + SUMMARY["oos"]["h6_walkforward"]
assert len(WF) == 11 and all(m["net30_c"] > 0 for m in WF) and all(m["others_net30_c"] < 0 for m in WF)
N_WF_IS = sum(m["month"] < "2026-08" for m in WF)
assert N_WF_IS == 8
WF_POS = f"{sum(m['net30_c'] > 0 for m in WF)}/{len(WF)}"
WF_OOS = WF[N_WF_IS:]
WF_OOS_RANGE = f"+{min(m['net30_c'] for m in WF_OOS):.1f} to +{max(m['net30_c'] for m in WF_OOS):.1f}¢"
assert WF_OOS_RANGE == "+0.4 to +0.8¢"
WF_DEC, WF_OCT = WF[0], WF[-1]
assert (WF_DEC["month"], WF_DEC["n_matches"], WF_DEC["n_wallets"]) == ("2025-12", 14, 4)
assert (WF_OCT["month"], WF_OCT["n_matches"]) == ("2026-10", 133)
AUG_IS = next(m for m in SUMMARY["is"]["h6_walkforward"] if m["month"] == "2026-08")  # Aug 1-24, not plotted
# Fast-tier 0-3 s volume per month, Jan 2026 on (Dec 2025 was only $8.8k).
FT_VOL = [m["usd_k"] for m in WF if m["month"] >= "2026-01"]
FT_VOL_TXT = f"${min(FT_VOL) / 1000:.1f}–{max(FT_VOL) / 1000:.1f}M"
assert FT_VOL_TXT == "$0.3–3.1M"
need(NOTE, "8/8 months > 0", "3/3 months > 0", "Copying the fast tier 3 s later | < 0 every month | < 0 every month")
need(DEVPOST, "11 of 11 months")
# H5 and H6 were written after in-sample results; only walk-forward / OOS counts.
need(DEV, "Because H5 was written after looking at in-sample data, only its OOS result counts as a test",
     "H6, formulated AFTER D4 (only its walk-forward / OOS result counts as a test)")
MONTH_ABBR = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun",
              "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}

# ---- OOS looks (results/oos_peeks.log): v1 once, then v2 twice on the burned window ----
PEEKS = [ln for ln in (ROOT / "results/oos_peeks.log").read_text(encoding="utf-8").splitlines() if ln.strip()]
assert len(PEEKS) == 3, PEEKS
need(HYP2, "is now burned: v2's design used knowledge of how v1 behaved there")

# ---- leverage (exact Markov model, simulated ATP best-of-3) ----
ATP = LEVER["atp"]
LEV_MEAN = f"{ATP['mean_abs_leverage'] * 100:.1f}%"
LEV_TRAVEL = f"${ATP['total_abs_move_per_match']:.1f}"
LEV_POINTS = f"{ATP['points_per_match']:.0f}"
assert (LEV_MEAN, LEV_TRAVEL, LEV_POINTS) == ("5.7%", "$4.2", "161")
need(NOTE, "mean |leverage| 5.7%", "~161 points")

# ---- tracking ----
EC = TRACK["early_call"]["precision_recall_test_snapshot"]["50ms"]
TT_CALLS = f"{EC['tp']}/{EC['tp'] + EC['fp']}"
TT_WILSON_LO = f"{EC['precision_wilson95'][0] * 100:.0f}%"
TT_N_MISS = EC["tp"] + EC["fn"]
TT_RECALL = f"{EC['recall'] * 100:.0f}%"
assert TT_CALLS == "11/11" and TT_WILSON_LO == "74%" and (TT_N_MISS, TT_RECALL) == (41, "27%")
TT_LEAD = TRACK["early_call"]["miss_first_call_lead_test_ms"]
TT_MED_LEAD = f"{TT_LEAD['median']:.0f} ms"
assert TT_MED_LEAD == "25 ms" and TT_LEAD["n_called"] == 8
need(DEV, "precision 8/8 at 50 ms (recall 0.38)")
PHYS = {r["lead_ms"]: r["pred_err_sd_cm"] for r in SUMMARY["tracking_tennis_physics"]}
HE_100 = f"±{PHYS[100]:.1f} cm"
HE_300 = f"±{PHYS[300]:.1f} cm"
assert (HE_100, HE_300) == ("±2.4 cm", "±10.7 cm")
need(NOTE, "a physics Monte Carlo of Hawk-Eye-class tracking (340 fps, ±3.6 mm)")
# Broadcast (25 fps) tennis: median landing error of the best predictor, 33-300 ms before the bounce.
# (docs/NOTE.md section 5 still says 0.6-1.2 m; results/tennis_tracking/summary.json gives 0.7-1.2 m.)
_BC = TENNIS_TRACK["headline"]["labels"]["median_landing_err_cm"]["learned"]
_BC = [v for k, v in _BC.items() if 33 <= int(k) <= 300]
BROADCAST_ERR = f"{min(_BC) / 100:.1f}–{max(_BC) / 100:.1f} m"
assert BROADCAST_ERR == "0.7–1.2 m", BROADCAST_ERR
need(TT_README, "about 0.7–1.2 m median from 33 to 300 ms before the bounce")
DEMO_LEADS = [c["call_lead_ms"] for c in DEMO["clips"] if c["label"] == "MISS"]
DEMO_LEADS_TXT = ", ".join(f"{MINUS}{x:.0f}" for x in DEMO_LEADS) + " ms"
assert DEMO_LEADS_TXT == f"{MINUS}408, {MINUS}83, {MINUS}25 ms"
assert DEMO["note"].startswith("presentation only")
need(NOTE, "11 of 11 calls correct", "±2.4 cm at 100 ms")

# ---- replay video on slide 1: a real tape beside a simulated shot ----
TAPE = VIZ["tape"]
TAPE_TXT = f"{TAPE['out0'].split()[-1]} v {TAPE['out1'].split()[-1]}, {TAPE['date']}"
assert TAPE_TXT == "Nakashima v Medvedev, 2026-08-18", TAPE_TXT
need("scripts/render_hawkeye_video.py", "a simulated groundstroke")

# ---- H4 (pre-registered live latency test) ----
H4 = SUMMARY["h4"]
H4_SHARE = f"{H4['share_book_first'] * 100:.0f}%"
H4_MED = f"{H4['median_lead_s']:.1f} s"
assert (H4_SHARE, H4_MED, H4["n"]) == ("93%", "44.5 s", 75)

# ---- calibration (in sample) ----
CAL_IS = SUMMARY["is"]["calibration"]
CAL_MAX = max(abs(b["edge_c"]) for b in CAL_IS)
CAL_MAX_TXT = f"{CAL_MAX:.1f}¢"
# Bands whose 95% CI on the realised win rate excludes the price (all are favourites priced rich).
CAL_RICH = [b for b in CAL_IS if b["hi"] < b["mean_price"] or b["lo"] > b["mean_price"]]
assert [b["bin"] for b in CAL_RICH] == ["[0.95, 0.97)", "[0.98, 0.99)", "[0.99, 1.0)"]
assert all(b["hi"] < b["mean_price"] for b in CAL_RICH)
H2_IS = SUMMARY["is"]["h2"]["lo0.85_hi0.97"]
H2_OOS = SUMMARY["oos"]["h2"]["lo0.85_hi0.97"]

# ---- markdown-only numbers, each checked against its source ----
need(NOTE, "−1.2 s (reprices before the official stamp)", "n = 482", "+27.5 s / +29.1 s / +43.3 s",
     "0 of 295 changes beat the book by > 1.3 s", "100–300 ms *before the bounce*",
     "6.1× its in-play volume", "hold every marketable order for 1 s (3 s before May 2026)",
     "fair value travels $4.20 per share")
need(LAT, "median 1.2 s before the official point timestamp", "28.2 s behind the book", "30.0 s behind the book",
     "may sit 1-3 s after the ball actually lands", "reacting about 0-2 s after the real point end",
     "| t_book - 2 s | $565 | $3,116 |", "| t_book - 1 s | $379 | $1,866 |",
     "| t_book - 0.25 s | $222 | $1,254 |",
     "an order has to be sent at least 1.3 s before the reprice to meet it",
     "98% with the move and earned +0.91c/share net", "submitted at least 1 s before they printed",
     "at least 1-1.5 s before the reprice", "mostly at Beijing WTA 1000")
need(KAL, "68.9%", "106,347", "6.1x Polymarket's in-play notional", "It is not an information gap",
     "0.07·p(1-p), i.e. 1.75c at p = 0.5", "+0.06c [-1.17, 1.48] on 119 trades")
need(NOTE, "Net |exposure| ≤ 100 shares per match; ≤ $1k per order; capital = 3× peak locked",
     "the worst day was −1.9% in sample and −2.1% out",
     "Kill switch on any feed or tracking dropout over 2 s", "on measured order latency beyond its 95th percentile",
     "Trade only calls with P ≥ 0.95",
     "We halve size if the trailing-month net edge falls below 0.3¢ and stop at ≤ 0",
     "Qualifying wallets grew 4 → 131",
     "Edge per share fell from ~2.4¢ to ~0.8¢ but stayed positive every month",
     "median 1¢ spread, $8.1k at the touch and $61k within 2¢", "89¢ median spread, $23 at the touch, ~$2 of volume per match",
     "2.9% of matches settled 50/50",
     "Polymarket's international venue restricts US persons", "A deployment needs licensed data, a permitted venue and legal review",
     "**The v2 book trades the fast tier's own fills.** It measures the opportunity at that speed, not our execution")
# Fee effect, in-sample shadow book by regime: 1 s/3% -> 1 s/5% is the fee alone (about halved).
need(DEV, "1 s/3% 1.19¢; 1 s/5% 0.54¢")
need(NOTE, "commit `7232986`", "opened once", "81% of the first v2 draft's OOS P&L",
     "filled only 35% of the time within a minute", "Side markets add only ~$2k/month",
     "Kalshi→Polymarket laggard trade nets ≈0 today", "Cloudflare's Miami edge", "67 ms median one-way",
     "saves ~130 ms per round trip", "The expected best Sharpe from luck over this many trials is ~4.8")
need(XMKT, "+0.93c/share (95% CI −2.8 to +4.7) and $472", "about $2.1k per 30 days")
need(DEVPOST, "chasing the move, favourite bias, maker exits, side-market sniping, and copying Kalshi")
need(NOTE, "1.98 s after the true match time", "5,472 trades", "P ≥ 0.95",
     "Courtsiding breaks most tournaments' ticket terms")
need(LAT, "9 WTA matches")
need(HYP2, "planned ~2026-10-04 11:30 UTC", "Window start moves to 2026-10-03 14:00 UTC",
     "**Primary A (economic claim):**", "**Primary B (strategy):**", "Pass if the 95% CI excludes 0",
     "With <1 day of matches a fail may be underpowered", "**Secondary:** v2 resolution P&L",
     "**Price zone:** token price q in [0.05, 0.95]")
need(DEV, "Burned-OOS v2 fell from +0.75¢ to +0.60¢")
need(FILL, "| 1 tick inside | 27% | 35% |")

FORWARD_STATUS = "PLACEHOLDER"
FORWARD_WHEN = "Runs once ~11:30 UTC, Oct 4 2026"
if (ROOT / "results/v2/forward.json").exists():
    print("NOTE: results/v2/forward.json exists. Replace the forward PLACEHOLDER cells by hand from it.")

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


def slide_title(prs):
    s = new_slide(prs, dark=True)
    eyebrow(s, "GATOR QUANT HACKS 2026  ·  SYSTEMATIC TRADING", dark=True)
    ph = set_title(s, "COURTSIDE", dark=True, size=60)
    ph.left, ph.top, ph.width, ph.height = Inches(M), Inches(0.98), Inches(5.1), Inches(1.12)
    text(s, M, 2.25, 5.1, 2.05, [
        P(R("Every point", 36, WHITE, bold=True, font=HEAD), line=0.95),
        P(R("moves a market.", 36, WHITE, bold=True, font=HEAD), line=0.95),
        P(R("Who gets paid?", 36, RED, bold=True, font=HEAD), line=0.95),
    ], name="Hook")
    text(s, M, 4.45, 5.1, 0.75, P(
        R(N_MATCHES, 38, WHITE, bold=True, font=HEAD), R(" matches   ", 18, MUTED_DK, font=HEAD),
        R(VOLUME, 38, WHITE, bold=True, font=HEAD), R(" traded", 18, MUTED_DK, font=HEAD)),
        anchor="b", name="Universe")
    text(s, M, 5.3, 5.0, 0.62, P(R("Every resolved Polymarket ATP/WTA singles moneyline ≥\u00a0$5k, "
                                   "Oct 2025 – Oct 2026", 13, MUTED_DK)), name="Universe caption")
    vx, vw = 6.05, SW - M - 6.05
    vh = vw * 9 / 16
    box(s, vx - 0.04, 1.05 - 0.04, vw + 0.08, vh + 0.08, fill=INK_2, radius=0.06, name="Video frame")
    video(s, "results/viz/courtside_replay.mp4", "results/viz/courtside_replay.png", vx, 1.05, vw, vh,
          13.0, loop=True, name="Video: Hawk-Eye-style replay")
    text(s, vx, 1.05 + vh + 0.12, vw, 0.5, P(R(
        f"Real Polymarket tape ({TAPE_TXT}) beside a simulated Hawk-Eye-style call", 12, MUTED_DK)),
        name="Video caption")
    text(s, M, 7.06, 6.0, 0.26, P(R("github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii", 11, MUTED_DK)), anchor="m", name="Repo")
    notes(s, f"""
[0:00 to 0:40]  TITLE + HOOK

Every tennis point moves a prediction market. An average point moves a player's fair value by about six cents; the biggest, by more than fifty.

So we asked: when the price jumps, who is on the other side, and who gets paid?

We took every resolved ATP and WTA moneyline on Polymarket for a year: {N_MATCHES} matches, 2.84 billion dollars traded, every print classified by side, net of its own fee.

The video: a real tape beside a simulated line call. Blue dots are the fast tier. This is COURTSIDE.

[Timing plan for the 5 minutes: about 40 s per slide for slides 1 to 7, 20 s spare. Backups 8 to 12 are for Q&A only.]
[PRE-FLIGHT, on the presenting machine: open the .pptx once in PowerPoint (not Keynote, Google Slides or a PDF; they may not autoplay the videos). Check that this video autoplays and loops, that the slide 4 video autoplays, and that the slide 5 table stays clear of the footer. Bring results/viz/courtside_replay.mp4 and results/tracking/demo/supercut.mp4 as separate files. If a video fails, talk over its poster frame.]
[The replay pairs the real {TAPE_TXT} tape with a simulated groundstroke (scripts/render_hawkeye_video.py); it is not that point's line call.]
[Sources: results/summary.json universe; results/leverage_stats.json (mean |leverage| {LEV_MEAN}, max {ATP['max_leverage'] * 100:.0f}%); results/viz/viz_data.json tape.]
""")


def slide_ladder(prs):
    s = new_slide(prs)
    eyebrow(s, "01  ·  ECONOMIC FOUNDATION")
    set_title(s, "A point ends in tiers. Slow tiers pay fast ones")
    # Rungs: (tag, who, sub, when, [when sub-lines], fill, fg, fg2). Tier 2's clock: the book reprices
    # 1.2 s before the official stamp, which is umpire-entered 1-3 s after landing (latency RESULTS 3a).
    rungs = [
        ("TIER 0", "Ball tracking", "in the venue", "100–300 ms", ["before the bounce"], RED, WHITE, "F6D3CC"),
        ("TIER 1", "Chair umpire", "", "at the bounce", [], INK, WHITE, MUTED_DK),
        ("TIER 2", "Market makers", "Kalshi (6.1× volume) reprices with them; PM lags ~2 s, mostly its own delay",
         f"{MINUS}1.2 s", ["vs the official stamp,", "≈ 0–2 s after landing"], BLUE, WHITE, "C9D9EA"),
        ("TIER 3", "Public feeds", "ESPN · PM score feed · WTA API", "+27 to +43 s", ["after the stamp"],
         "C9D5E1", INK, MUTED),
    ]
    x0, y0, step, rh, gap, right = M, 1.8, 0.5, 1.0, 0.12, 8.55
    for i, (tag, who, sub, when, when_sub, fill, fg, fg2) in enumerate(rungs):
        x, y = x0 + i * step, y0 + i * (rh + gap)
        w = right - x
        box(s, x, y, w, rh, fill=fill, radius=0.1, name=f"Ladder rung {i}")
        who_paras = [P(R(tag, 11, fg2, bold=True, spc=1.2)), P(R(who, 22, fg, bold=True, font=HEAD), line=0.9)]
        if sub:
            who_paras.append(P(R(sub, 11.5, fg2)))
        text(s, x + 0.25, y + 0.05, w - 2.95, rh - 0.1, who_paras, anchor="m", name=f"Ladder who {i}")
        when_paras = [P(R(when, 26, fg, bold=True, font=HEAD), align="r", line=0.9)]
        for ws in when_sub:
            when_paras.append(P(R(ws, 12, fg2), align="r"))
        text(s, x + w - 2.6, y + 0.05, 2.35, rh - 0.1, when_paras, anchor="m", name=f"Ladder when {i}")
    text(s, M, 6.3, right - M, 0.6, P(R(
        "Tier 0: physics simulation. Kalshi: in-sample tapes (106,347 repricings). Tiers 2–3: live books vs the "
        "WTA official point stamp (umpire-entered, may lag landing 1–3 s), 2026-10-03, 9 WTA matches, n = 482.",
        11, MUTED)), name="Ladder source")

    cx, cw = 9.05, SW - M - 9.05
    text(s, cx, 1.8, cw, 0.3, P(R("WHO PAYS WHOM", 12, BLUE, bold=True, spc=1.5)), name="Label")
    text(s, cx, 1.98, cw, 0.92, P(R(LEV_TRAVEL, 54, BLUE, bold=True, font=HEAD)), anchor="b", name="Stat leverage")
    text(s, cx, 2.92, cw, 0.7, P(R(f"total |fair-value move| per $1 share over a simulated ATP best-of-3 "
                                   f"({LEV_POINTS} points, {LEV_MEAN} mean per point)", 13, INK)),
         name="Stat leverage caption")
    text(s, cx, 3.62, cw, 0.92, P(R("1 s", 54, RED, bold=True, font=HEAD)), anchor="b", name="Stat delay")
    text(s, cx, 4.56, cw, 0.5, P(R("Polymarket holds every marketable sports order 1 s so makers can reprice",
                                   13, INK)), name="Stat delay caption")
    box(s, cx, 5.28, cw, 0.96, fill=INK, radius=0.1, name="Takeaway panel")
    text(s, cx + 0.22, 5.28, cw - 0.44, 0.96, P(R("The gaps are physical, so they persist.", 20, WHITE, bold=True,
                                                   font=HEAD)), anchor="m", name="Takeaway")
    footer(s, 2)
    notes(s, f"""
[0:40 to 1:20]  ECONOMIC FOUNDATION: THE INFORMATION LADDER

Why does anyone lose? Because a point ends in tiers.

Ball tracking knows the landing point mid-air. The umpire knows at the bounce. Market makers reprice Polymarket 1.2 seconds before the official stamp, typed in after the ball lands. Kalshi, six times bigger, reprices with them; Polymarket's lag is mostly its own order delay. Public feeds arrive 27 to 43 seconds late.

Over a match, a one-dollar share's fair value moves about four dollars in total, and whoever trades on an older tier sells to someone faster. The venue admits it: it holds every marketable order one second so makers can reprice.

[If asked "why not trade Kalshi, it is 6x bigger?": Kalshi's taker fee is 0.07·p(1−p), 1.75¢ at p = 0.5, and the hedged Polymarket-laggard trade nets +0.06¢ [−1.17, 1.48] on 119 trades in today's 1 s / 5% regime. Most of Polymarket's ~2 s lag is mechanical (its order delay plus ~2 s block-time stamps), not an information gap, and the fast tier trades at the same moment Kalshi reprices (research/v2/kalshi/RESULTS.md TL;DR 1, 2, 4, 6).]
[If asked about the clocks: the official WTA stamp has 1 s resolution and may sit 1–3 s after the ball lands, so the book probably reacts about 0–2 s after the real point end (research/v2/latency/RESULTS.md 3a). One day, 9 WTA matches, mostly Beijing; ATP has no public official point clock.]
[Sources: docs/NOTE.md sections 1 and 5; research/v2/latency/RESULTS.md (n = 482 points, 9 WTA matches; ESPN +27.5 s, PM feed +29.1 s, WTA API +43.3 s); research/v2/kalshi/RESULTS.md (68.9% of 106,347 in-sample repricings; ~2 s once block lag is removed; 6.1x in-play notional); results/leverage_stats.json ({LEV_TRAVEL} total travel, {LEV_POINTS} points, mean |leverage| {LEV_MEAN}; simulated ATP best-of-3 from the exact Markov model).]
""")


def slide_evidence(prs):
    s = new_slide(prs)
    eyebrow(s, "02  ·  EVIDENCE")
    set_title(s, "The fast tier wins every month. Copying it loses")
    figure(s, "results/figures/fig1_tiers.png", M, 1.85, 7.45, 4.0,
           caption="Fig. 1  30 s markout per taker print, net of fee. Onset-aligned ex-post event study; "
                   "tradable numbers (slide 5) use the causal window (D9).",
           name="Fig 1 tiers")
    cx = M + 7.45 + 0.35
    cw = SW - M - cx
    text(s, cx, 1.56, cw, 1.07, P(R(WF_POS, 62, BLUE, bold=True, font=HEAD)), anchor="b", name="Stat months")
    text(s, cx, 2.64, cw, 0.7, P(R(f"months > 0, walk-forward: {N_WF_IS} in sample + {len(WF_OOS)}/{len(WF_OOS)} "
                                   f"out of sample ({WF_OOS_RANGE}). H6 came after the in-sample wallet study, "
                                   "so only OOS is a test.", 13, INK)),
         name="Stat months caption")
    cd = CategoryChartData()
    cd.categories = [MONTH_ABBR[m["month"][5:]] for m in WF]
    cd.add_series("Fast tier", [round(m["net30_c"], 2) for m in WF])
    cd.add_series("Everyone else, same 0–3 s", [round(m["others_net30_c"], 2) for m in WF])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(cx - 0.05), Inches(3.36), Inches(cw + 0.05),
                            Inches(2.06), cd)
    gf.name = "Chart: walk-forward months"
    ch = gf.chart
    style_chart(ch)
    plot = ch.plots[0]
    plot.gap_width = 45
    plot.overlap = 0
    color_series(plot, [BLUE, RED])
    # Out-of-sample months (the only real test of H6) in a paler shade of each series colour.
    for ser, pale in zip(plot.series, ("9DB8D3", "EBA79C")):
        for k in range(N_WF_IS, len(WF)):
            pt = ser.points[k]
            pt.format.fill.solid()
            pt.format.fill.fore_color.rgb = rgb(pale)
            pt.format.line.fill.background()
    va = ch.value_axis
    va.maximum_scale, va.minimum_scale, va.major_unit = 2.5, -2.0, 1.0
    va.tick_labels.number_format = '0"¢"'
    va.tick_labels.number_format_is_linked = False
    text(s, cx, 5.43, cw, 0.5, P(R("30 s net ¢/share by month. Pale bars: out of sample "
                                   "(Aug = Aug 25–31 only; Oct = 3 days).", 11, MUTED)),
         name="Chart caption")
    box(s, M, 6.1, CW, 0.8, fill=INK, radius=0.1, name="Takeaway panel")
    text(s, M + 0.3, 6.1, CW - 0.6, 0.8, P(
        R("Copy the same trades 3 s later: negative every month.  ", 22, WHITE, bold=True, font=HEAD),
        R("The edge is speed.", 22, "F07A66", bold=True, font=HEAD)), anchor="m", name="Takeaway")
    footer(s, 3)
    lo_is = min(m["net30_c"] for m in WF[:8])
    hi_is = max(m["net30_c"] for m in WF[:8])
    notes(s, f"""
[1:20 to 2:00]  EVIDENCE: WHO GETS PAID

Every taker print, by seconds since the score event, marked out thirty seconds later, net of fees.

A small group of wallets, the fast tier, trades within three seconds and wins. Everyone else in that window loses about a cent a share.

Picked each month from earlier months only, it won eleven of eleven: eight in sample, where we found it, and three out of sample, the real test.

The control: copy their exact trades three seconds later and you lose, every month. So it is not who they are. The edge is speed.

[Honest framing if asked: H6 was written after the in-sample wallet study (DEVIATIONS D4, D5), so only the 3 out-of-sample months test it. Fig. 1 and the H6 months use onset-aligned windows, an ex-post event study; every tradable v2 number uses the causal window (D9). December 2025 is small ({WF_DEC['n_matches']} matches, {WF_DEC['n_wallets']} wallets, ${WF_DEC['usd_k']:.1f}k of fast-tier volume). The Aug bar is Aug 25-31 only (in-sample Aug 1-24 was {signed(AUG_IS['net30_c'])}¢); Oct is 3 days ({WF_OCT['n_matches']} matches), and its fast-tier P&L held to resolution was {signed(WF_OCT['net_res_c'])}¢ even though its 30 s markout was positive.]
[Sources: results/summary.json is/oos h6_walkforward (fast tier +{lo_is:.1f} to +{hi_is:.1f} ¢ in sample, {WF_OOS_RANGE} out of sample; everyone else negative every month); docs/NOTE.md Table 1 (copy 3 s later < 0 every month); results/figures/fig1_tiers.png.]
""")


def slide_tracking(prs):
    s = new_slide(prs)
    eyebrow(s, "03  ·  INNOVATION")
    set_title(s, "Tier 0 is measurable: call the point before it lands")
    vw = 7.55
    vh = vw * 9 / 16
    box(s, M - 0.04, 1.85 - 0.04, vw + 0.08, vh + 0.08, fill=INK, radius=0.06, name="Video frame")
    video(s, "results/tracking/demo/supercut.mp4", "results/tracking/demo/supercut.png", M, 1.85, vw, vh,
          DEMO["supercut"]["duration_s"], loop=False, name="Video: real-footage early calls")
    text(s, M, 1.85 + vh + 0.12, vw, 0.62, P(R(
        "Real 120 fps table-tennis footage (OpenTTGames, CC BY-NC-SA 4.0), frozen model, run on HiPerGator. "
        f"Selected clips: calls at {DEMO_LEADS_TXT}; median first-call lead on held-out misses {TT_MED_LEAD}.",
        11, MUTED)), name="Video caption")
    cx = M + vw + 0.45
    cw = SW - M - cx
    stats = [
        (TT_CALLS, RED, f"table-tennis miss calls correct, 50 ms before contact, held-out games. "
                        f"Called {EC['tp']} of {TT_N_MISS} misses (recall {TT_RECALL}); 95% lower bound {TT_WILSON_LO}"),
        (HE_100, BLUE, "simulated Hawk-Eye-class tracking (340 fps, ±3.6 mm): landing error, 1 SD, "
                       "100 ms before the bounce"),
        (BROADCAST_ERR, MUTED, "25 fps broadcast tennis, median landing error: useless"),
    ]
    y = 1.66
    for big, col, cap in stats:
        text(s, cx, y, cw, 0.82, P(R(big, 48, col, bold=True, font=HEAD)), anchor="b", name=f"Stat {big}")
        text(s, cx, y + 0.84, cw, 0.74, P(R(cap, 13, INK)), name=f"Stat caption {big}")
        y += 1.62
    footer(s, 4)
    notes(s, f"""
[2:00 to 2:40]  INNOVATION: BUILDING TIER 0

Can anyone reach the top rung? This is real 120-frame-per-second table-tennis footage, run on HiPerGator: OpenTTGames is the public labelled high-speed set, and table tennis itself isn't tradable.

On held-out games, all {EC['tp']} of our frozen model's miss calls, 50 milliseconds before contact, were right; it called {EC['tp']} of {TT_N_MISS} misses. Small sample: lower bound {TT_WILSON_LO}.

For tennis, simulated Hawk-Eye-class tracking has a 2.4-centimetre standard deviation 100 milliseconds before the bounce. Broadcast video at 25 frames a second is 70 centimetres to 1.2 metres off.

The lead comes from frame rate and cameras, so it lives in the venue.

[If asked "what recall?": {TT_RECALL} ({EC['tp']} of {TT_N_MISS} test misses called at 50 ms). Post-hoc label audit (DEVIATIONS H3-D10): the frozen model is 8/8 at 38% recall on corrected labels. The demo clips are selected for presentation (manifest: "presentation only", online rule); the median first-call lead on called held-out misses is {TT_MED_LEAD} (n = {TT_LEAD['n_called']}, p90 {TT_LEAD['p90']:.0f} ms). Tennis Hawk-Eye numbers are a physics Monte Carlo (340 fps, 3.6 mm noise), not a measurement.]
[Sources: results/summary.json tracking_table_tennis_video (test precision at 50 ms {TT_CALLS}, Wilson 95% lower bound {TT_WILSON_LO}; pre-registered H3) and tracking_tennis_physics (landing error SD {HE_100} at 100 ms, {HE_300} at 300 ms); results/tracking/summary.json; results/tracking/demo/manifest.json; results/tennis_tracking/summary.json (broadcast median landing error {BROADCAST_ERR}, 33 to 300 ms; docs/NOTE.md section 5 still says 0.6–1.2 m).]
""")


def slide_strategy(prs):
    s = new_slide(prs)
    eyebrow(s, "04  ·  PERFORMANCE")
    set_title(s, "v2: the same edge, a fraction of the noise")
    # Whose fills these are, said before anyone asks (NOTE section 8).
    box(s, M, 1.66, CW, 0.36, fill=RED_TINT, radius=0.06, name="Fills strip")
    text(s, M + 0.18, 1.66, CW - 0.36, 0.36, P(
        R("Paper book on the fast tier's own fills: ", 12, RED, bold=True),
        R("it prices the opportunity at their speed, not our execution (that needs in-venue tracking + a "
          "co-located gateway).", 12, INK)), anchor="m", name="Fills caveat")

    text(s, M, 2.1, 4.0, 0.3, P(R("FROZEN v2 RULES", 12, BLUE, bold=True, spc=1.5)), name="Rules label")
    rules = ["0–3 s fast-tier window, causal", "Wallet edge must beat today's fee", "Price 0.05–0.95; risk-parity size",
             "≤ $1k/order; ≤ 100 shares net/match", "Hold to resolution: no exits"]
    for i, r in enumerate(rules):
        y = 2.42 + i * 0.38
        badge(s, M, y + 0.04, 0.3, str(i + 1), size=13, name=f"Rule badge {i + 1}")
        text(s, M + 0.42, y, 3.75, 0.38, P(R(r, 14.5, INK)), anchor="m", name=f"Rule {i + 1}")

    # Fig 6 on a card, caption beside the image (the figure is wide and short).
    fx, fy, fw, fh, pad = 4.85, 2.1, SW - M - 4.85, 2.22, 0.12
    box(s, fx, fy, fw, fh, fill=FIGBG, line=LINE, radius=0.08, shadow=True, name="Card: Fig 6 v2")
    _, (ix, iy, iw, ih) = fit_picture(s, ROOT / "results/figures/fig6_v2.png", fx + pad, fy + pad, 5.0,
                                      fh - 2 * pad, name="Fig 6 v2")
    capx = ix + iw + 0.14
    text(s, capx, fy + pad, fx + fw - pad - capx, fh - 2 * pad, [
        P(R("Fig. 6  v1 vs v2: return on each book's own capital; v2 P&L by month (*Aug includes IS days).",
            10.5, MUTED), after=5),
        P(R(f"v1 OOS: {V1_LOSS_TXT}, max DD {V1_DD}, worst day {V1_WORST_DAY}.", 10.5, INK, bold=True), after=5),
        P(R(f"v2 burned OOS: {OS_PNL}, max DD {dd(OS0)}, worst day {WORST_DAY_OS}.", 10.5, BLUE, bold=True)),
    ], anchor="m", name="Caption: Fig 6 v2")

    def val(r, bold=False, size=14):
        c = RED if r["per_share_c"] < 0 else (BLUE if bold else INK)
        return [P(R(signed(r["per_share_c"]) + "¢", size, c, bold=True if bold else False, font=HEAD if bold else BODY),
                  R("  " + ci(r["per_share_ci_c"]), 11.5, MUTED))]

    def hdr(a, *b):
        return [P(R(a, 12.5, WHITE, bold=True))] + [P(R(t, 10.5, MUTED_DK)) for t in b]

    def lab(a, size=13.5):
        return [P(R(a, size, INK))]

    # Forward cell: the pre-registered decision rule (HYPOTHESIS_V2 A1.5), written before the result exists.
    fwd = [
        P(R(FORWARD_STATUS + ": blind test not run", 14, RED, bold=True, font=HEAD)),
        P(R(FORWARD_WHEN + "; reported either way.", 10.5, RED), after=3),
        P(R("Primary A: ", 10.5, INK, bold=True), R(f"fast tier {MINUS} others, 30 s net  ", 10.5, INK),
          R("[FWD_A]", 10.5, RED, bold=True)),
        P(R("Primary B: ", 10.5, INK, bold=True), R("v2 book, 30 s net per share  ", 10.5, INK),
          R("[FWD_B]", 10.5, RED, bold=True), after=3),
        P(R("Pass iff the match-clustered 95% CI excludes 0. Under 1 day of matches, a B fail may be "
            "underpowered (A1). Resolution P&L at left is secondary.", 10, MUTED)),
    ]
    rows = [
        [hdr("v2, causal window", "net of fees, held to resolution"), hdr("In sample", "Feb–Aug 2026"),
         hdr("Burned OOS (non-blind)", "Aug 25 – Oct 3; v2 built after", "v1 failed here"),
         hdr("Forward (blind)", "from Oct 3, 14:00 UTC")],
        [lab("Net per share, fast-tier fills"), val(IS0, True, 18), val(OS0, True, 18), fwd],
        [lab("… +½ tick worse entry"), val(IS5), val(OS5), None],
        [lab("… +1 tick worse entry"), val(IS10), val(OS10), None],
        [lab("Sharpe · max DD · months > 0", 13),
         [P(R(f"{sharpe(IS0)}  ·  {dd(IS0)}  ·  {months(IS0)}", 13.5, INK))],
         [P(R(f"{sharpe(OS0)}  ·  {dd(OS0)}  ·  {months(OS0)}", 13.5, INK), R("  (Oct = 3 days)", 10.5, MUTED))],
         None],
    ]
    fills = [None] + [[None, None, None, RED_TINT]] * 4
    tbl = table(s, M, 4.42, [2.85, 2.3, 2.85, CW - 8.0], [0.6, 0.42, 0.32, 0.32, 0.36], rows,
                "Table: v2 causal results", fills=fills)
    tbl.cell(1, 3).merge(tbl.cell(4, 3))
    tbl.cell(1, 3).vertical_anchor = MSO_ANCHOR.TOP
    text(s, M, 6.5, CW, 0.44, P(R(
        f"Why the Sharpe is so high: ~{PER_DAY:.0f} small bets a day ({IS0['n_trades']:,} in {DAYS} days), each held "
        f"to a binary outcome, net-capped per match. Best Sharpe from luck alone over {N_VARIANTS:,} tried variants "
        "≈ 4.8 (Bailey & López de Prado).", 11.5, MUTED)), name="Sharpe note")
    footer(s, 5)
    notes(s, f"""
[2:40 to 3:20]  STRATEGY v2 AND PERFORMANCE

Then we priced that opportunity as a paper strategy on the fast tier's own fills. Version one copied their tickets and lost 36 thousand dollars out of sample: big tickets on cheap tokens.

Version two adds five rules: a causal window, fee-beating wallets, risk-parity sizing, a net cap per match, and hold to resolution.

In sample: plus 1.38 cents a share, Sharpe 14.5, two percent max drawdown, positive even at a full tick. On the burned, non-blind out-of-sample: plus 0.60 cents, gone at half a tick. The blind forward test runs once on October 4th; its pass rule is already on the slide.

[FORWARD TEST: not run at build time; it runs once ~11:30 UTC Oct 4 2026. If results/v2/forward.json exists by talk time, read Primary A (fast tier minus others, 30 s net) and Primary B (v2 book, 30 s net per share) with their match-clustered 95% CIs; each passes only if its CI excludes 0 (HYPOTHESIS_V2.md A1.5). Then replace FORWARD_* and [FWD_A]/[FWD_B] in build_deck.py and rebuild. Resolution P&L in the left rows is secondary for the forward window.]
[If asked "whose fills are these?": the fast tier's. v2 is a paper book that measures the opportunity at their speed, not our execution (docs/NOTE.md section 8); out of sample the edge is gone at +½ tick ({signed(OS5['per_share_c'])}¢ {ci(OS5['per_share_ci_c'])}), so second place earns nothing. If asked "you redesigned after v1 failed OOS?": yes, HYPOTHESIS_V2.md says so, which is why that window is labelled burned; the hindsight fix (D9) lowered the burned-OOS number from +0.75 to +0.60¢, and the forward run is the only clean test.]
[Sources: results/v2/causal.json (IS {IS0['n_trades']:,} trades, {DAYS} days, P&L {IS_PNL} on {IS_CAP}; burned OOS {OS0['n_trades']:,} trades, {OS_DAYS} days, {OS_PNL} on {OS_CAP}); HYPOTHESIS_V2.md (frozen rule incl. price zone 0.05–0.95, amendment A1); results/summary.json oos h6_shadow (v1 OOS {V1_LOSS_TXT}, max DD {V1_DD}, worst day {V1_WORST_DAY}); results/figures/fig6_v2.png. About {PER_DAY:.0f} small bets a day, each held to an exogenous binary outcome: that is why the Sharpe is high; the expected best Sharpe from luck over {N_VARIANTS:,} variants is ~4.8 (docs/NOTE.md section 8).]
""")


def slide_risk(prs):
    s = new_slide(prs)
    eyebrow(s, "05  ·  RISK MANAGEMENT  ·  LIQUIDITY & CAPITAL")
    set_title(s, "Small by design, with hard limits, on a deep book")
    text(s, M, 1.72, 6.0, 0.3, P(R("LIMITS AND KILL SWITCHES", 12, BLUE, bold=True, spc=1.5)), name="Risk label")
    tiles = [
        ("100", "net shares per match, max", BLUE),
        ("$1k", "max per order", BLUE),
        ("> 2 s", "feed/tracking dropout, or order latency > p95: kill", BLUE),
        ("< 0.3¢", "trailing edge: halve; ≤ 0: stop", BLUE),
        ("5% fee", "alone halved the edge (1.19 → 0.54¢): venue risk", RED),
        ("4 → 131", "fast-tier wallets: crowding", RED),
    ]
    tw, th, gx, gy = 1.95, 1.34, 0.2, 0.14
    for i, (big, cap, col) in enumerate(tiles):
        x = M + (i % 3) * (tw + gx)
        y = 2.04 + (i // 3) * (th + gy)
        box(s, x, y, tw, th, fill=WHITE, line=LINE, radius=0.08, shadow=True, name=f"Risk tile {i}")
        text(s, x + 0.16, y + 0.06, tw - 0.32, 0.54, P(R(big, 28, col, bold=True, font=HEAD)), anchor="b",
             name=f"Risk tile big {i}")
        text(s, x + 0.16, y + 0.64, tw - 0.32, 0.64, P(R(cap, 11.5, INK)), name=f"Risk tile caption {i}")
    text(s, M, 4.98, 6.25, 1.0, [
        P(R("Worst backtest match ", 13, MUTED), R(f"{MINUS}$206", 13, INK, bold=True),
          R(f"  (v1: {MINUS}$3,098)  ·  capital = 3× peak locked", 13, MUTED)),
        P(R("Worst day ", 13, MUTED), R(f"{WORST_DAY_IS} IS / {WORST_DAY_OS} OOS", 13, INK, bold=True),
          R("  ·  trade calls only at ", 13, MUTED), R("P ≥ 0.95", 13, INK, bold=True), before=5),
    ], name="Worst case")

    cx = 7.25
    cw = SW - M - cx
    text(s, cx, 1.72, cw, 0.3, P(R("LIQUIDITY AND CAPACITY", 12, BLUE, bold=True, spc=1.5)), name="Liq label")
    box(s, cx, 2.04, cw, 2.2, fill=WHITE, line=LINE, radius=0.08, shadow=True, name="Liquidity card")
    half = cw / 2 - 0.45
    for j, (name, big, big_cap, rows_, col) in enumerate([
        ("TENNIS", "$61k", "within 2¢", ["1¢ median spread", "$8.1k at the touch", "live sample, one day (Oct 3)"],
         BLUE),
        ("TABLE TENNIS", "89¢", "median spread", ["$23 at the touch", "~$2 per match", "not tradable"], RED),
    ]):
        x = cx + 0.28 + j * cw / 2
        text(s, x, 2.14, half - 0.1, 0.28, P(R(name, 11, MUTED, bold=True, spc=1.2)), name=f"Liq head {j}")
        text(s, x, 2.36, half - 0.1, 0.7, P(R(big, 42, col, bold=True, font=HEAD)), anchor="b", name=f"Liq big {j}")
        text(s, x, 3.06, half - 0.1, 0.28, P(R(big_cap, 13, INK)), name=f"Liq big cap {j}")
        text(s, x, 3.38, half - 0.1, 0.82, [P(R(t, 12.5 if k < 2 else 11.5, INK if k < 2 else MUTED), after=2)
                                             for k, t in enumerate(rows_)], name=f"Liq rows {j}")
    line = s.shapes.add_connector(1, Inches(cx + cw / 2), Inches(2.2), Inches(cx + cw / 2), Inches(4.1))
    line.line.color.rgb = rgb(LINE)
    line.line.width = Pt(0.75)
    line.name = "Divider"
    box(s, cx, 4.36, cw, 1.92, fill=INK, radius=0.1, name="Capacity panel")
    text(s, cx + 0.25, 4.36, cw - 0.5, 1.92, [
        P(R("RETURN ON CAPITAL (PAPER, AT FAST-TIER FILLS) AND CAPACITY", 10, MUTED_DK, bold=True, spc=1.0)),
        P(R(f"{IS_PNL} on {IS_CAP} in {DAYS} IS days ({IS_ROC})", 18, WHITE, bold=True, font=HEAD), before=3),
        P(R(f"{OS_PNL} on {OS_CAP} in {OS_DAYS} burned-OOS days ({OS_ROC})", 13, WHITE)),
        P(R("Stale depth before a reprice: median $222–565, mean $1.3–3.1k per point (live, Oct 3)", 11.5,
            MUTED_DK), before=4),
        P(R(f"Whole prize: fast-tier 0–3 s volume {FT_VOL_TXT} a month (from Jan 2026); v2 trades "
            f"{USD_PER_DAY} a day of it ({TRADED_M} in {DAYS} days)", 11.5, MUTED_DK), before=3),
    ], anchor="m", name="Capacity")
    # Legal and access, full width (docs/NOTE.md section 6).
    box(s, M, 6.4, CW, 0.56, fill=BLUE_TINT, radius=0.06, name="Legal strip")
    text(s, M + 0.18, 6.4, CW - 0.36, 0.56, P(
        R("Legal and access: ", 12, BLUE, bold=True),
        R("deployment needs licensed data, a permitted venue (Polymarket's international venue restricts US persons) "
          "and legal review; courtsiding breaks most ticket terms. This repo only reads public data and never places "
          "an order.", 12, INK)),
        anchor="m", name="Legal")
    footer(s, 6)
    notes(s, f"""
[3:20 to 4:00]  RISK MANAGEMENT, LIQUIDITY AND CAPITAL

Net exposure is capped at a hundred shares a match, orders at a thousand dollars. The worst backtested match lost 206 dollars. Kill switches fire on dropouts or slow orders.

The biggest risk is the venue: the five percent fee alone halved the edge, and qualifying wallets grew from 4 to 131. So we halve size below 0.3 cents of trailing edge and stop at zero.

Tennis is deep: 61 thousand dollars within two cents. On paper, v2 made 40 thousand dollars on 28 thousand of capital in sample. Deploying it needs licensed data, a permitted venue and legal review.

[Also in the note if asked: only calls with P >= 0.95 are traded; the kill switch also fires when measured order latency exceeds its 95th percentile; 2.9% of matches settled 50/50 (retirements), included in all P&L. Legal: courtsiding breaks most tournaments' ticket terms, live tracking data is licensed, Polymarket's international venue restricts US persons. The repo only reads public data and never places orders. Peak locked {PEAK_K}.]
[Fee effect (DEVIATIONS D6, in-sample shadow book per share): 3 s/3% 1.64¢, 1 s/3% 1.19¢, 1 s/5% 0.54¢. The fee alone (1.19 to 0.54) is about −55%; fee plus the 3 s to 1 s delay change is about −67%, the "two-thirds" in docs/NOTE.md section 6.]
[Capacity: v2 traded {TRADED_M} of paper notional in {DAYS} in-sample days ({USD_PER_DAY} a day). Fast-tier 0–3 s volume was {FT_VOL_TXT} a month from Jan 2026 (Dec 2025: ${WF_DEC['usd_k']:.1f}k). Stale depth resting before a reprice: median $565 / $379 / $222 and mean $3,116 / $1,866 / $1,254 at 2 s / 1 s / 0.25 s before it (live, 2026-10-03, 482 points).]
[Sources: docs/NOTE.md sections 6 and 7; results/v2/causal.json (P&L, capital, worst day {WORST_DAY_IS} IS / {WORST_DAY_OS} OOS); worst match {MINUS}$205.76: docs/NOTE.md section 6 and data/v2_trades_is_oos.parquet grouped by match; research/v2/latency/RESULTS.md section 5; results/summary.json h6_walkforward usd_k.]
""")


def slide_integrity(prs):
    s = new_slide(prs, dark=True)
    eyebrow(s, "06  ·  INTEGRITY", dark=True)
    set_title(s, "Pre-registered, every look logged, failures reported", dark=True)
    text(s, M, 1.75, 5.8, 0.32, P(R("INTEGRITY TRAIL", 12, MUTED_DK, bold=True, spc=1.5)), name="Trail label")
    steps = [
        ("H1–H4 committed before any result",
         "commit 7232986 · H5, H6 written after in-sample results, frozen before OOS (DEVIATIONS D3, D5)"),
        ("OOS opened once, for v1",
         f"v2 was built knowing v1 lost $36k there, so it is burned: v2 is shown on it twice, labelled "
         f"non-blind ({len(PEEKS)} lines in oos_peeks.log)"),
        ("Verifiers caught onset hindsight", "81% of a draft's OOS P&L: fixed, re-run"),
        ("Blind forward test pre-registered", "runs once ~11:30 UTC Oct 4: the clean test"),
    ]
    for i, (a, b) in enumerate(steps):
        y = 2.12 + i * 0.82
        badge(s, M, y + 0.08, 0.4, str(i + 1), fill=BLUE, name=f"Trail badge {i + 1}")
        text(s, M + 0.58, y, 5.6, 0.76, [P(R(a, 15, WHITE, bold=True)), P(R(b, 11.5, MUTED_DK))], anchor="m",
             name=f"Trail step {i + 1}")
    cx = 7.05
    cw = SW - M - cx
    text(s, cx, 1.75, cw, 0.32, P(R("FIVE IDEAS THAT FAILED, ALL REPORTED", 12, MUTED_DK, bold=True, spc=1.5)),
         name="Failed label")
    fails = [
        ("Chasing the move", f"{MINUS}2.1¢ out of sample"),
        ("Favourite bias", "prices calibrated"),
        ("Maker exits", "adversely selected"),
        ("Side markets", "sniping ≈ 0; best maker only ~$2k/month"),
        ("Copying Kalshi", "≈ 0 net today"),
    ]
    for i, (a, b) in enumerate(fails):
        y = 2.15 + i * 0.64
        text(s, cx, y, 0.35, 0.56, P(R("×", 24, "F07A66", bold=True)), anchor="m", name=f"Fail mark {i}")
        text(s, cx + 0.42, y, cw - 0.42, 0.56, P(R(a + "  ", 16, WHITE, bold=True), R(b, 13, MUTED_DK)),
             anchor="m", name=f"Fail {i}")
    box(s, M, 5.5, CW, 1.42, fill=BLUE, radius=0.12, name="Punchline panel")
    text(s, M + 0.35, 5.5, CW - 0.7, 1.42, [
        P(R("The edge pays whoever is first.", 30, WHITE, bold=True, font=HEAD)),
        P(R("We showed what first requires: ", 20, "DCE7F2", font=HEAD),
          R("in-venue tracking + a gateway co-located with the matching engine.", 20, WHITE, bold=True, font=HEAD),
          before=2),
        P(R("Polymarket's API sits behind Cloudflare's Miami edge, origin consistent with London; "
            "co-locating saves ~130 ms per round trip.", 13, "DCE7F2"), before=3),
    ], anchor="m", name="Punchline")
    footer(s, 7, dark=True)
    notes(s, f"""
[4:00 to 4:40]  INTEGRITY, WHAT FAILED, AND THE PUNCHLINE

Why trust this? H1 to H4 were committed before any result; H5 and H6 came later, so only out-of-sample counts for them. Out-of-sample was opened once, for version one; version two came after, so we label it burned. Every look is logged.

Verifiers caught hindsight in our first v2 draft: 81 percent of its out-of-sample P&L came before our detector could fire. We fixed it and re-ran.

Five ideas failed; all are reported.

What is left held on the burned window only at the fast tier's own fills, under a tick; the blind test decides. We showed what first requires: in-venue tracking and a co-located gateway. Thank you.

[Then: "Happy to take questions." Backups: 8 calibration, 9 latency, 10 Table 1, 11 slippage and the hindsight fix, 12 reproduce.]
[Q&A CRIB (one line each; sources in brackets):
1. "These are someone else's fills." Yes: v2 is a paper book at the fast tier's fills; it prices the opportunity, not our execution, and out of sample it is gone at +½ tick, so second place earns nothing (docs/NOTE.md section 8; results/v2/causal.json).
2. "You redesigned after v1 failed OOS." Yes, and we say so (HYPOTHESIS_V2.md); that window is labelled burned, the D9 fix lowered its number from +0.75 to +0.60¢, and the blind forward run is the only clean test.
3. "Does a 50–300 ms call beat a 1 s hold?" To meet a stale quote an order must leave ≥ 1.3 s before the reprice; fast-tier prints already know ≥ 1–1.5 s before the book; tier 0 adds tens to hundreds of ms on top, not yet shown end to end (research/v2/latency/RESULTS.md section 5; backup slide 9).
4. "Is this courtsiding? Can US persons trade it?" Courtsiding breaks most ticket terms, tracking data is licensed, Polymarket's international venue restricts US persons; deployment needs licensed data, a permitted venue and legal review, and this repo only reads public data (docs/NOTE.md section 6).
5. "Sharpe 14.5?" ~{PER_DAY:.0f} small bets a day, each held to a binary outcome and net-capped per match; luck-only best Sharpe over {N_VARIANTS:,} variants ≈ 4.8; burned OOS 6.7.
6. "11/11 at 50 ms, but what recall?" {TT_RECALL} ({EC['tp']} of {TT_N_MISS}); post-hoc label audit: 8/8 at 38% recall (DEVIATIONS H3-D10).
7. "December has {WF_DEC['n_matches']} matches and {WF_DEC['n_wallets']} wallets." True; 11/11 includes a tiny month, and only the 3 OOS months test H6.
8. "Latency is one day." Yes: 9 WTA matches, mostly Beijing; ATP has no public official point clock (research/v2/latency/RESULTS.md section 8).
9. "Kalshi is 6x bigger; why not trade there?" Kalshi's taker fee is 1.75¢ at p = 0.5, and the hedged laggard trade nets +0.06¢ [−1.17, 1.48] in today's regime (research/v2/kalshi/RESULTS.md).
10. "Oct OOS fast-tier P&L to resolution?" {signed(WF_OCT['net_res_c'])}¢ over 3 days ({WF_OCT['n_matches']} matches); the 30 s markout was {signed(WF_OCT['net30_c'])}¢.
Known source inconsistencies (outside the deck): docs/NOTE.md section 2 and DEVIATIONS D8 still give the forward start as 13:00 UTC; HYPOTHESIS_V2.md A1.6 moved it to 14:00 (the deck uses 14:00). HYPOTHESIS.md says "written ~10:15 UTC" while DEVIATIONS dates commit 7232986 at 09:50 UTC: cite the hash only, and check it on GitHub before the talk. results/summary.json "v2" still holds the pre-fix onset numbers (Sharpe 16.8); the deck uses results/v2/causal.json.]
[Sources: HYPOTHESIS.md (commit 7232986; H1–H4); DEVIATIONS.md D3, D5 (H5, H6 after in-sample); results/oos_peeks.log ({len(PEEKS)} looks: v1 10:42 UTC, v2 13:24, v2-causal 13:53); DEVIATIONS.md D9 and HYPOTHESIS_V2.md A1 (81%); docs/NOTE.md Table 1 and sections 4 and 5; research/v2/livefill/RESULTS.md (35% within 60 s); research/v2/crossmarket/RESULTS.md (sniping +0.93¢ [−2.8, 4.7], $472 over six months; leaning maker ~$2.1k per 30 days); docs/DEVPOST.md Challenges.]
""")


# ---------------------------------- backups ----------------------------------


def slide_b_calibration(prs, n):
    s = new_slide(prs)
    eyebrow(s, "BACKUP  ·  CALIBRATION (H2)")
    set_title(s, "Live prices are calibrated: slow money has no edge")
    figure(s, "results/figures/fig2_calibration.png", M, 1.8, 5.2, 5.05, name="Fig 2 calibration",
           caption="Fig. 2  In-play favourite price vs realised win rate, in sample")
    cx = M + 5.2 + 0.6
    cw = SW - M - cx
    text(s, cx, 1.7, cw, 1.05, P(R(CAL_MAX_TXT, 60, BLUE, bold=True, font=HEAD)), anchor="b", name="Stat cal")
    text(s, cx, 2.8, cw, 0.6, P(R(f"largest gap between price and realised win rate, across all {len(CAL_IS)} bands "
                                  "from 0.50 to 1.00 (in sample)", 14, INK)), name="Stat cal caption")
    rows = [
        [[P(R("H2: buy favourites at 0.85–0.97, hold", 13, WHITE, bold=True))],
         [P(R("Net ¢/share [95% CI]", 13, WHITE, bold=True))]],
        [[P(R("In sample", 14, INK))],
         [P(R(signed(H2_IS["mean_pnl_per_share_c"]) + "¢  ", 15, INK, bold=True),
            R(ci(H2_IS["ci95_pnl_per_share_c"]), 12, MUTED))]],
        [[P(R("Out of sample (opened once)", 14, INK))],
         [P(R(signed(H2_OOS["mean_pnl_per_share_c"]) + "¢  ", 15, INK, bold=True),
            R(ci(H2_OOS["ci95_pnl_per_share_c"]), 12, MUTED))]],
    ]
    table(s, cx, 3.75, [cw - 2.6, 2.6], [0.48, 0.45, 0.45], rows, "Table: H2")
    box(s, cx, 5.55, cw, 1.3, fill=INK, radius=0.1, name="Takeaway panel")
    text(s, cx + 0.3, 5.55, cw - 0.6, 1.3, P(R("No favourite-longshot edge. The only edge left is speed.", 20, WHITE,
                                              bold=True, font=HEAD)), anchor="m", name="Takeaway")
    footer(s, n)
    notes(s, f"""
BACKUP: CALIBRATION (H2)

If asked "isn't there a favourite-longshot bias?": no. In-play prices of the favourite match realised win rates to within about {CAL_MAX_TXT} in every band from 0.50 to 1.00 across {len(CAL_IS)} bands in sample (results/summary.json is.calibration; the note rounds this to "within ~1¢").

The pre-registered H2 trade, buying favourites as they enter 0.85 to 0.97 and holding to resolution, earned {signed(H2_IS['mean_pnl_per_share_c'])}¢ {ci(H2_IS['ci95_pnl_per_share_c'])} in sample and {signed(H2_OOS['mean_pnl_per_share_c'])}¢ {ci(H2_OOS['ci95_pnl_per_share_c'])} out of sample. Both intervals include zero: no edge, reported as failed.

So slow money has no edge, which is why the economic story is about speed and not mispricing.

If pressed on the top bands: in {len(CAL_RICH)} of them ({', '.join(b['bin'] for b in CAL_RICH)}) the realised win rate's 95% CI sits below the price, by at most {CAL_MAX_TXT} (for example {CAL_RICH[-1]['bin']}: price {CAL_RICH[-1]['mean_price']:.3f}, won {CAL_RICH[-1]['win_rate']:.3f} [{CAL_RICH[-1]['lo']:.3f}, {CAL_RICH[-1]['hi']:.3f}]). Favourites are slightly rich, the opposite of a favourite-longshot bias, and H2's trade CI includes 0 both in and out of sample.
""")


def slide_b_latency(prs, n):
    s = new_slide(prs)
    eyebrow(s, "BACKUP  ·  LATENCY (H4)")
    set_title(s, "Public score feeds are the slow tier")
    figure(s, "results/figures/fig5_h4.png", M, 1.8, 5.6, 5.05, name="Fig 5 H4",
           caption=f"Fig. 5  Pre-registered H4: book moved first on {H4_SHARE} of {H4['n']} score changes, "
                   f"median lead {H4_MED}")
    cx = M + 5.6 + 0.45
    cw = SW - M - cx
    rows = [
        [[P(R("Source", 13, WHITE, bold=True))], [P(R("vs official stamp", 13, WHITE, bold=True), align="r")],
         [P(R("vs the book", 13, WHITE, bold=True), align="r")]],
        [[P(R("Polymarket book", 14, INK, bold=True))],
         [P(R(f"{MINUS}1.2 s", 16, BLUE, bold=True, font=HEAD), align="r")], [P(R("—", 14, MUTED), align="r")]],
        [[P(R("ESPN scoreboard", 14, INK))], [P(R("+27.5 s", 16, INK, font=HEAD), align="r")],
         [P(R("28.2 s behind", 14, RED), align="r")]],
        [[P(R("Polymarket sports feed", 14, INK))], [P(R("+29.1 s", 16, INK, font=HEAD), align="r")],
         [P(R("30.0 s behind", 14, RED), align="r")]],
        [[P(R("WTA public API", 14, INK))], [P(R("+43.3 s", 16, INK, font=HEAD), align="r")],
         [P(R("44 s behind", 14, RED), align="r")]],
    ]
    table(s, cx, 1.8, [cw - 3.6, 1.8, 1.8], [0.42, 0.42, 0.42, 0.42, 0.42], rows, "Table: latency")
    text(s, cx, 3.98, cw, 0.5, P(R("0 of 295 public score changes beat the book by more than 1.3 s "
                                   "(1 s venue delay + 0.3 s).", 13, INK)), name="Latency note")
    box(s, cx, 4.52, cw, 2.38, fill=WHITE, line=LINE, radius=0.08, shadow=True, name="Infra card")
    text(s, cx + 0.25, 4.52, cw - 0.5, 2.38, [
        P(R("WHAT FIRST REQUIRES", 11, BLUE, bold=True, spc=1.2)),
        P(R("To meet a stale quote, an order must leave ≥ 1.3 s before the reprice. Fast-tier prints landing "
            "0–0.5 s before it earned +0.91¢ and were sent ≥ 1 s earlier, so they know ≥ 1–1.5 s before the book. "
            "Tier 0 adds tens to hundreds of ms on top of that; not yet shown end to end.", 12, INK), before=3),
        P(R("API behind Cloudflare's Miami edge: 67 ms one-way from Gainesville; origin consistent with London.",
            12, INK), before=4),
        P(R("Co-locating saves ~130 ms per round trip: queue order behind the 1 s delay.", 12, INK), before=4),
    ], anchor="m", name="Infra")
    footer(s, n)
    notes(s, f"""
BACKUP: LATENCY

On the WTA's official point clock (umpire-entered timestamps), the Polymarket moneyline reprices a median 1.2 s before the official stamp (n = 482 points, 9 WTA matches, live 2026-10-03). ESPN reports a game 27.5 s after the stamp, Polymarket's own sports websocket 29.1 s, the WTA public API 43.3 s. Of 295 source-observed score changes matched to a book reprice, none led the book by more than 1.3 s.

Fig. 5 is the pre-registered H4 test: the book moved before Polymarket's public score feed on {H4_SHARE} of {H4['n']} score changes, median lead {H4_MED}. H4 holds. H4 (n = {H4['n']}, all matches, book vs feed message) and the official-clock table (PM sports feed 30.0 s behind the book, n = 61, WTA only) use different samples and methods; both put the feed tens of seconds behind.

Timing budget (research/v2/latency/RESULTS.md section 5): the stale depth is gone 0.5 s after the reprice, and with the 1 s order delay an order must be sent at least 1.3 s before the reprice, i.e. at least 2.5 s before the official stamp. Prints landing 0 to 0.5 s before the reprice were 98% with the move and earned +0.91¢/share net; they were submitted at least 1 s earlier, so those takers have the point at least 1 to 1.5 s before the book. Tier-0 tracking adds tens to hundreds of ms on top of whatever that signal is; we have not shown a tier-0 order reaching a stale quote end to end.

Tape timestamps are on-chain block times, a median 1.98 s after the true match time (5,472 trades joined by transaction hash), which is why every tape result charges the real delay.

Infrastructure: Polymarket's API sits behind Cloudflare's Miami edge, 67 ms median one-way from Gainesville, origin consistent with London; co-locating saves about 130 ms per round trip, which decides queue order behind the 1 s delay.

[Sources: research/v2/latency/RESULTS.md; docs/NOTE.md sections 2 and 5; results/summary.json h4.]
""")


def slide_b_table1(prs, n):
    s = new_slide(prs)
    eyebrow(s, "BACKUP  ·  EVERY TEST  ·  H1–H4 PRE-REGISTERED; H5, H6 ADDED AFTER IS (†)")
    set_title(s, "Table 1: every test, net of fees and traded spreads")

    def c(t, size=14, col=INK, bold=False, font=BODY):
        return [P(R(t, size, col, bold=bold, font=font))]

    def verdict(t, col):
        return [P(R(t, 15, col, bold=True, font=HEAD))]

    h = [[P(R(t, 13, WHITE, bold=True))] for t in ("Test", "In sample", "Out of sample (opened once)", "Verdict")]
    is_h1, oos_h1 = SUMMARY["is"]["h1"]["J0.04_H30"], SUMMARY["oos"]["h1"]["J0.04_H30"]
    is_h5, oos_h5 = SUMMARY["is"]["h5"]["J0.04_W30"], SUMMARY["oos"]["h5"]["J0.04_W30"]
    assert len(SUMMARY["is"]["h1"]) == 20 and all(v["mean_pnl_per_share_c"] < 0 for v in SUMMARY["is"]["h1"].values())
    tr50 = TRACK["early_call"]["precision_recall_train_oof_snapshot"]["50ms"]
    rows = [
        h,
        [c("H1  Follow the jump after the delay", bold=True),
         c(f"{signed(is_h1['mean_pnl_per_share_c'])} {ci(is_h1['ci95_pnl_per_share_c'])}; all 20 variants < 0"),
         c(f"{signed(oos_h1['mean_pnl_per_share_c'])} {ci(oos_h1['ci95_pnl_per_share_c'])}"), verdict("Fails", RED)],
        [c("H2  Buy favourites entering 0.85–0.97", bold=True),
         c(f"{signed(H2_IS['mean_pnl_per_share_c'])} {ci(H2_IS['ci95_pnl_per_share_c'])}; prices calibrated"),
         c(f"{signed(H2_OOS['mean_pnl_per_share_c'])} {ci(H2_OOS['ci95_pnl_per_share_c'])}"), verdict("No edge", RED)],
        [c("H5†  Maker quoting after jumps", bold=True),
         c(f"{signed(is_h5['mean_pnl_per_share_c'])} {ci(is_h5['ci95_pnl_per_share_c'])}"),
         c(f"{signed(oos_h5['mean_pnl_per_share_c'])} {ci(oos_h5['ci95_pnl_per_share_c'])}"),
         verdict("Inconclusive", MUTED)],
        [c("H6†  Fast tier, walk-forward, 30 s", bold=True, col=BLUE),
         c("+0.6 to +2.4; 8/8 months > 0", col=BLUE, bold=True), c("+0.4 to +0.8; 3/3 months > 0", col=BLUE, bold=True),
         verdict("Holds", BLUE)],
        [c("     Everyone else, same 0–3 s window"), c(f"{MINUS}0.5 to {MINUS}1.7, every month"),
         c(f"{MINUS}1.2 to {MINUS}1.9"), c("")],
        [c("     Copying the fast tier 3 s later"), c("< 0 every month"), c("< 0 every month"),
         verdict("Edge is speed", BLUE)],
        [c("H3  Miss called 50 ms early (video)", bold=True), c(f"train CV precision {tr50['precision']:.2f} (frozen model)"),
         c(f"{TT_CALLS} correct; recall {TT_RECALL}"), verdict("Holds", BLUE)],
        [c("H4  Book moves before public feed", bold=True), c("— (live test, 2026-10-03)"),
         c(f"book first: {H4_SHARE} of {H4['n']}"), verdict("Holds", BLUE)],
    ]
    fills = [None, None, None, None, [BLUE_TINT] * 4, None, None, None, None]
    table(s, M, 1.75, [3.85, 3.95, 2.85, CW - 10.65], [0.42] + [0.48] * 8, rows, "Table 1: hypotheses", fills=fills)
    text(s, M, 6.12, CW, 0.62, [
        P(R("¢/share, 95% CI clustered by match. H1–H4 pre-registered (commit 7232986). † Written after in-sample "
            "results (DEVIATIONS D3, D5) and frozen before OOS: only their walk-forward / OOS results count.", 11, MUTED)),
        P(R("H1–H6 use onset-aligned windows (ex-post event study); every tradable v2 number uses the causal window.",
            11, MUTED), before=2),
    ], name="Table 1 note")
    footer(s, n)
    tr = TRACK["early_call"]["precision_recall_train_oof_snapshot"]["50ms"]
    notes(s, f"""
BACKUP: TABLE 1, EVERY TEST

Rows H1, H2, H5 and H6 are the note's Table 1 (docs/NOTE.md); H3 and H4 come from results/summary.json. H1 to H4 are pre-registered (HYPOTHESIS.md, commit 7232986). H5 and H6 were added after the in-sample results (DEVIATIONS D3, D5) and frozen before OOS, so only their walk-forward and OOS results count as tests.

H1, chasing the move, fails in every one of its 20 variants and out of sample. H2 has no edge because prices are calibrated. H5, maker quoting after jumps, is inconclusive. H6 holds: the fast tier, selected each month on earlier months only, is positive in all 8 in-sample and all 3 out-of-sample months, while everyone else in the same window loses every month, and copying the fast tier 3 s later loses every month.

H3: the frozen model's out-of-fold train precision at 50 ms was {tr['precision']:.2f}; on held-out test games it was {TT_CALLS} (Wilson lower bound {TT_WILSON_LO}), calling {EC['tp']} of {TT_N_MISS} misses (recall {TT_RECALL}). A post-hoc label audit (DEVIATIONS H3-D10) found incomplete test labels; the frozen model is 8/8 at 38% recall on corrected labels. The pre-specified result is the one of record.

Multiple testing: 44 strategy variants for H1-H6 plus 3,342 across the six v2 lenses, all reported. The expected best Sharpe from luck over that many trials is about 4.8 (Bailey and Lopez de Prado); v2 shows 14.5 in sample and 6.7 on the burned OOS, and the blind forward test is the clean check.
""")


def slide_b_slippage(prs, n):
    s = new_slide(prs)
    eyebrow(s, "BACKUP  ·  SLIPPAGE AND THE HINDSIGHT FIX")
    set_title(s, "v2 survives a tick in sample; out of sample, only at the front")
    text(s, M, 1.75, 6.3, 0.32, P(R("NET ¢/SHARE BY ENTRY SLIPPAGE (CAUSAL WINDOW)", 12, BLUE, bold=True, spc=1.2)),
         name="Chart label")
    cd = CategoryChartData()
    cd.categories = ["Fast-tier fills", "+½ tick", "+1 tick"]
    cd.add_series("In sample, Feb–Aug 2026", [round(r["per_share_c"], 2) for r in (IS0, IS5, IS10)])
    cd.add_series("Burned OOS, Aug 25 – Oct 3", [round(r["per_share_c"], 2) for r in (OS0, OS5, OS10)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(M - 0.05), Inches(2.1), Inches(6.35),
                            Inches(4.1), cd)
    gf.name = "Chart: slippage"
    ch = gf.chart
    style_chart(ch)
    plot = ch.plots[0]
    plot.gap_width = 70
    plot.overlap = 0
    color_series(plot, [BLUE, RED])
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format = '+0.00;−0.00'
    dl.number_format_is_linked = False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size = Pt(12)
    dl.font.bold = True
    dl.font.color.rgb = rgb(INK)
    va = ch.value_axis
    va.maximum_scale, va.minimum_scale, va.major_unit = 1.6, -0.8, 0.4
    va.tick_labels.number_format = '0.0"¢"'
    va.tick_labels.number_format_is_linked = False
    text(s, M, 6.25, 6.25, 0.6, P(R(
        f"Sharpe by slippage: IS {sharpe(IS0)} / {sharpe(IS5)} / {sharpe(IS10)} (7/7 months each); "
        f"OOS {sharpe(OS0)} / {sharpe(OS5)} / {num(OS10['sharpe_ann'], 1)}", 12, MUTED)), name="Chart note")

    cx = 7.3
    cw = SW - M - cx
    text(s, cx, 1.75, cw, 0.32, P(R("CAUSAL WINDOW VS ONSET (HINDSIGHT)", 12, BLUE, bold=True, spc=1.2)),
         name="Table label")

    def cellv(r):
        return [P(R(signed(r["per_share_c"]) + "¢", 15, INK, bold=True)), P(R(ci(r["per_share_ci_c"]), 11, MUTED))]

    oi, oo = ONSET["is_eval/slip0.0"], ONSET["burned_oos/slip0.0"]
    DRAFT_IS, DRAFT_OOS = SUMMARY["v2"]["is_eval"], SUMMARY["v2"]["burned_oos_nonblind"]  # pre-fix draft
    rows = [
        [[P(R("Window", 13, WHITE, bold=True))], [P(R("In sample", 13, WHITE, bold=True))],
         [P(R("Burned OOS", 13, WHITE, bold=True))]],
        [[P(R("Onset (hindsight)", 14, INK)), P(R("re-run, draft's window", 11, MUTED))], cellv(oi), cellv(oo)],
        [[P(R("Causal window", 14, BLUE, bold=True)), P(R("from detection, frozen v2", 11, MUTED))], cellv(IS0), cellv(OS0)],
        [[P(R("Sharpe, causal", 14, INK))], [P(R(sharpe(IS0), 15, INK))], [P(R(sharpe(OS0), 15, INK))]],
        [[P(R("Trades, causal", 14, INK))], [P(R(f"{IS0['n_trades']:,}", 15, INK))],
         [P(R(f"{OS0['n_trades']:,}", 15, INK))]],
    ]
    fills = [None, None, [BLUE_TINT] * 3, None, None]
    table(s, cx, 2.1, [cw - 3.4, 1.7, 1.7], [0.46, 0.66, 0.66, 0.44, 0.44], rows, "Table: causal vs onset",
          fills=fills)
    box(s, cx, 5.0, cw, 1.85, fill=WHITE, line=LINE, radius=0.08, shadow=True, name="D9 card")
    text(s, cx + 0.25, 5.0, cw - 0.5, 1.85, [
        P(R("WHAT THE VERIFIERS FOUND (D9)", 11, BLUE, bold=True, spc=1.2)),
        P(R("The onset label is the first print of a 10 s window the detector confirms later. 81% of the draft's "
            "OOS P&L came before detection. Fixed before the forward window opened.", 14, INK), before=3),
    ], anchor="m", name="D9 note")
    footer(s, n)
    notes(s, f"""
BACKUP: SLIPPAGE AND THE HINDSIGHT FIX

Slippage stress, causal window, held to resolution (results/v2/causal.json):
In sample: {signed(IS0['per_share_c'])} {ci(IS0['per_share_ci_c'])} at fast-tier fills, {signed(IS5['per_share_c'])} {ci(IS5['per_share_ci_c'])} at +1/2 tick, {signed(IS10['per_share_c'])} {ci(IS10['per_share_ci_c'])} at +1 tick; positive in 7 of 7 months at every level; max DD {dd(IS0)} / {dd(IS5)} / {dd(IS10)}.
Burned OOS: {signed(OS0['per_share_c'])} {ci(OS0['per_share_ci_c'])}, {signed(OS5['per_share_c'])} {ci(OS5['per_share_ci_c'])}, {signed(OS10['per_share_c'])} {ci(OS10['per_share_ci_c'])}; months positive {months(OS0)}, {months(OS5)}, {months(OS10)}.

Reading: in today's regime (1 s delay, 5% fee, 131 qualifying wallets) the edge is positive only at the fast tier's own fill prices and gone at half a tick. It pays whoever is first to the stale quote. That is the case for in-venue tracking plus a co-located gateway, and the reason a remote copy cannot work.

Hindsight fix (DEVIATIONS D9, HYPOTHESIS_V2 A1): the first v2 draft measured the 0-3 s window from the jump onset, which the detector only confirms up to 10 s later. Re-run from detection, burned-OOS v2 fell from about +0.75 to +0.60 cents. The "Onset (hindsight)" row is causal.json's re-run of the onset window ({signed(oi['per_share_c'])} / {signed(oo['per_share_c'])}); the first draft's own numbers (results/summary.json "v2") were {signed(DRAFT_IS['per_share_c'])}¢ {ci(DRAFT_IS['per_share_ci_c'])} in sample and {signed(DRAFT_OOS['per_share_c'])}¢ {ci(DRAFT_OOS['per_share_ci_c'])} on the burned OOS, Sharpe {DRAFT_IS['sharpe_ann']:.1f} / {DRAFT_OOS['sharpe_ann']:.1f}. H1-H6 keep onset labels as an ex-post event study; every tradable number uses the causal window.
""")


def slide_b_repro(prs, n):
    s = new_slide(prs)
    eyebrow(s, "BACKUP  ·  REPRODUCE")
    set_title(s, "Reproduce the backtest")
    cmds = [
        ("pip install -r requirements.txt", "in a fresh venv"),
        (".venv/bin/python scripts/fetch_polymarket.py", "public APIs, no keys; ~1–2 h, cached in data/"),
        ("bash reproduce.sh", "H1–H6, v2, figures, leverage stats, PDF"),
        ("python run_all.py --oos", "H1–H6, calibration, tiers, fast tier"),
        ("python scripts/v2_causal.py", "v2 on IS + burned OOS -> results/v2/causal.json"),
        ("python scripts/forward_test.py", "blind forward test: one shot, logged"),
        ("pytest tests", "unit tests"),
    ]
    box(s, M, 1.8, 8.0, 4.4, fill=INK, radius=0.1, name="Terminal card")
    paras = []
    for i, (c, why) in enumerate(cmds):
        paras.append(P(R("$ ", 13, "F07A66", bold=True, font=MONO), R(c, 13, WHITE, font=MONO),
                       before=0 if i == 0 else 6))
        paras.append(P(R("  # " + why, 11.5, MUTED_DK, font=MONO)))
    text(s, M + 0.3, 1.8, 7.4, 4.4, paras, anchor="m", name="Commands")
    text(s, M, 6.3, 8.0, 0.62, [
        P(R("Tracking (H3): sbatch hpg/track_*.sbatch on HiPerGator; outputs cached in results/tracking/ "
              "(not in reproduce.sh).", 12, INK)),
        P(R("Live-book numbers (latency, liquidity, fills) come from 2026-10-03 recordings in data/ (not committed).",
            12, MUTED), before=2),
    ], name="Not in reproduce.sh")
    cx = M + 8.0 + 0.4
    cw = SW - M - cx
    text(s, cx, 1.8, cw, 0.32, P(R("INTEGRITY TRAIL", 12, BLUE, bold=True, spc=1.5)), name="Trail label")
    trail = [("HYPOTHESIS.md", "H1–H4 pre-registered, commit 7232986"),
             ("DEVIATIONS.md", "every change and why (H5, H6: D3, D5)"),
             ("HYPOTHESIS_V2.md", "v2 frozen before its forward test"),
             ("results/oos_peeks.log", f"every look at held-out data ({len(PEEKS)} lines)"),
             ("results/v2/forward.json", "forward result (after the run)")]
    trail_paras = []
    for a, b in trail:
        trail_paras.append(P(R(a, 14, INK, bold=True, font=MONO)))
        trail_paras.append(P(R(b, 13, MUTED), after=8))
    text(s, cx, 2.18, cw, 3.5, trail_paras, name="Trail files")
    text(s, cx, 5.75, cw, 0.8, P(R("Reads public data only and never places an order.", 14, INK, bold=True)),
         name="Read-only note")
    footer(s, n)
    notes(s, f"""
BACKUP: REPRODUCE

The backtest regenerates from public data with no API keys. scripts/fetch_polymarket.py pulls the Polymarket tapes (1 to 2 hours, cached in data/). bash reproduce.sh runs run_all.py --oos (H1-H6, calibration, tiers, the walk-forward fast tier), scripts/v2_causal.py (v2 on in-sample and burned OOS with slippage stress), the figures, the leverage stats and the PDF. scripts/v2_causal.py is the current script behind results/v2/causal.json, which every v2 number in this deck reads; the note's header still cites scripts/v2_burned_oos.py, the earlier onset-window run (results/v2/burned_oos.json). The forward test is a one-shot: scripts/forward_test.py, pre-registered window, and every run is logged. Tests: pytest tests.

Not in reproduce.sh: tracking (H3) runs on HiPerGator GPUs via sbatch hpg/track_*.sbatch (table tennis) and hpg/tennis_*.sbatch (broadcast tennis), with outputs cached in results/tracking/ and results/tennis_tracking/. Live-book numbers (latency, liquidity, live fills) come from the 2026-10-03 recordings: python -m src.live_recorder, research/v2/latency, research/v2/livefill; the recordings sit in data/, which is not committed. The worst-match figure ({MINUS}$206) is computed from data/v2_trades_is_oos.parquet, not written by any script.

Integrity trail: HYPOTHESIS.md (H1-H4 pre-registered, commit 7232986), DEVIATIONS.md (every change, including H5 and H6 being added after in-sample results, D3 and D5), HYPOTHESIS_V2.md (v2 frozen before its forward test), results/oos_peeks.log ({len(PEEKS)} looks: v1 once, then v2 twice on the burned window, labelled non-blind) and the forward log.

This deck rebuilds with: .venv/bin/python docs/deck/build_deck.py
[Source: README.md, reproduce.sh, hpg/.]
""")


def main() -> None:
    need(README, "bash reproduce.sh", "python scripts/forward_test.py", "pytest tests")
    prs = Presentation()
    setup_template(prs)
    prs.core_properties.title = "COURTSIDE: who gets paid in the seconds after a tennis point"
    prs.core_properties.subject = "Gator Quant Hacks 2026, Systematic Trading"
    prs.core_properties.author = "COURTSIDE"
    prs.core_properties.keywords = "tennis; Polymarket; latency; market microstructure"

    for build in (slide_title, slide_ladder, slide_evidence, slide_tracking, slide_strategy, slide_risk,
                  slide_integrity):
        build(prs)
    for i, build in enumerate((slide_b_calibration, slide_b_latency, slide_b_table1, slide_b_slippage,
                               slide_b_repro)):
        build(prs, 8 + i)
    add_sections(prs, [("Main talk (5 min)", 7), ("Backup for Q&A", 5)])
    prs.save(OUT)
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
