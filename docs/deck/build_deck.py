#!/usr/bin/env python3
"""COURTSIDE investment-committee deck for the 5-minute talk (Gator Quant Hacks 2026, Systematic Trading).

Rebuild from the repo root:

    .venv/bin/python docs/deck/build_deck.py             # deck + manifest + checks
    .venv/bin/python docs/deck/render_thumbs.py          # slide thumbnails (docs/deck/thumbs/)

Writes
------
* docs/deck/courtside.pptx: 16:9, ten main slides (timed 4:45 script in every slide's notes), then backup slides with
  the top questions from docs/QA_PREP.md and their answers.
* docs/deck/courtside_manifest.json: every number on every slide with the file and key it was read from.
* docs/deck/assets/: the money-counter scorecard capture, the CV clip cut from the final video, its poster frame.

Where the numbers come from
---------------------------
* results/paper/numbers.json (written by scripts/build_paper.py): every paper number, read at build time, so a later
  rebuild picks up the final paper. Keys missing from it stop the build (no guesses, no "pending").
* results/viz/v60_assets/manifest.json (the final video's own value table) for the few numbers only the video shows
  (the 325 ms cold-open call, the reprice band, the stale depth), so the deck and the video say the same thing.
* scripts/money_counter.py --speed 50, run non-interactively; its SCORECARD is parsed and must agree with the paper.
* Paper locations (Table 1, Fig. A1, Appendix D) from the paper's label map at build time (scripts/paper_refs.py:
  docs/paper/note.aux, or the committed results/paper/labels.json on a clone), never typed by hand.
* The ONE forward-test slot (slide 8) fills from results/v2/forward.json (and results/tier0_v3/forward*/results.json)
  when those exist; otherwise it follows the last HYPOTHESIS_V2.md amendment on the forward test. A5 (final): "Blind
  forward test: pre-registered but not run within the hackathon window (HYPOTHESIS_V2.md A5)".

Honesty rules the build enforces (run_checks)
---------------------------------------------
* The pre-registered reading (break-even near a 1 s feed, +$4 a day held out) always comes first; the post hoc stamp-lag
  reading follows it with its label, and the per-point reading of the same data (it loses) is shown too.
* The CV strategy is simulated at an assumed feed latency (licensed feed not purchased); its trade set is points that
  later repriced >= 4c, selected on outcomes (not ex ante). Tennis is simulated physics. No real money, no match video,
  no licensed feed, no live-session numbers (the live paper session was stopped by a team decision).
* No deploy-day promises: the close says what a licensed feed would let us test, never that the strategy is live.

Style: black or white slides, Inter, one orange accent (#E8601C, the paper's figure orange).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

DECK = Path(__file__).resolve().parent
ROOT = DECK.parents[1]
OUT = DECK / "courtside.pptx"
OUT_MANIFEST = DECK / "courtside_manifest.json"
ASSETS = DECK / "assets"

F_NUM = "results/paper/numbers.json"
F_VID = "results/viz/v60_assets/manifest.json"
F_VIDEO = "results/viz/courtside_60.mp4"
F_FWD = "results/v2/forward.json"
F_HYP2 = "HYPOTHESIS_V2.md"
F_TEAM = "research/compliance/TEAM.md"
REPO = "github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii"

# ------------------------------------------------------------------------------------------------ palette and type
BLACK, WHITE, ORANGE = "000000", "FFFFFF", "E8601C"
INK = "1D1D1F"          # text on white
GREY_D = "A1A1A6"       # secondary text on black
GREY_L = "6E6E73"       # secondary text on white
CARD_D = "161618"       # card on black
CARD_L = "F5F5F7"       # card on white
RULE_D = "2C2C2E"
RULE_L = "D2D2D7"
FONT = "Inter"
MONO = "Menlo"

SW, SH = 13.333, 7.5
M = 0.7
CW = SW - 2 * M
MINUS = "−"

# ------------------------------------------------------------------------------------------------ data access
MANIFEST: list[dict] = []
_SLIDE = ["setup"]


class Missing(Exception):
    pass


def _json(rel):
    return json.loads((ROOT / rel).read_text())


NUM = _json(F_NUM)["numbers"]
VID = _json(F_VID)["values"]
VID_FINAL = _json(F_VID)["final"]
VID_LABELS = _json(F_VID).get("labels", {})
sys.path.insert(0, str(ROOT))
from scripts.paper_refs import forward_amendment, load as load_refs  # noqa: E402
REFS = load_refs()
F_REFS = REFS.get("from", "docs/paper/note.aux")
F_TENNIS_LIC = "results/viz/v60_assets/tennis_real/LICENSE.md"


def PR(label: str) -> str:
    """The paper's number for a LaTeX label (Table 'A1', Fig. '2', Section '7'), read at build time."""
    if label not in REFS["labels"]:
        raise Missing(f"the paper has no label '{label}' ({F_REFS}): rebuild the paper or fix the deck's label")
    v = REFS["labels"][label][0]
    MANIFEST.append({"slide": _SLIDE[0], "shown": v, "key": f"label:{label}", "from": F_REFS, "source": F_REFS})
    return v


def APPX(title: str) -> str:
    """The letter of the paper's appendix with this title (e.g. 'Records' -> 'D')."""
    if title not in REFS["appendix"]:
        raise Missing(f"the paper has no appendix titled '{title}' ({F_REFS})")
    v = REFS["appendix"][title]
    MANIFEST.append({"slide": _SLIDE[0], "shown": v, "key": f"appendix:{title}", "from": F_REFS, "source": F_REFS})
    return v


def tennis_credit() -> str:
    t = (ROOT / F_TENNIS_LIC).read_text() if (ROOT / F_TENNIS_LIC).exists() else ""
    m = re.search(r'Tennis footage: "([^"]+)" by ([^,]+), Pexels \(Pexels License\)', t)
    if not m:
        raise Missing(f"{F_TENNIS_LIC}: no attribution line")
    return rec(f"tennis rally: “{m.group(1)}” by {m.group(2)}, Pexels (Pexels License)", F_TENNIS_LIC)


def N(key: str) -> str:
    """A paper number, exactly as the paper prints it."""
    if key not in NUM:
        raise Missing(f"{F_NUM} has no key '{key}' (rebuild the paper numbers or fix the deck key)")
    e = NUM[key]
    MANIFEST.append({"slide": _SLIDE[0], "shown": e["value"], "key": key, "from": F_NUM, "source": e["source"]})
    return e["value"]


def NR(key: str):
    if key not in NUM:
        raise Missing(f"{F_NUM} has no key '{key}'")
    return NUM[key]["raw"]


def VV(key: str, shown: str | None = None) -> str:
    """A number only the final video shows, as the video shows it."""
    if key not in VID:
        raise Missing(f"{F_VID} has no value '{key}'")
    e = VID[key]
    s = shown if shown is not None else e.get("shown")
    MANIFEST.append({"slide": _SLIDE[0], "shown": s, "key": key, "from": F_VID, "source": f"{e['file']} :: {e['key']}"})
    return s


def rec(shown: str, source: str) -> str:
    MANIFEST.append({"slide": _SLIDE[0], "shown": shown, "key": None, "from": source, "source": source})
    return shown


def dollars(s: str) -> str:
    """'+$15' -> '+$15' ; the paper already signs dollars with a real minus."""
    return s


# ------------------------------------------------------------------------------------------------ forward-test slot
def forward_slot() -> tuple[str, str]:
    """(text, source). ONE slot in the deck. Fills from results/v2/forward.json when the one-shot run has written it."""
    fwd = ROOT / F_FWD
    if fwd.exists():
        F = json.loads(fwd.read_text())

        def tri(v):
            if isinstance(v, list) and len(v) >= 3:
                s = f"{v[0]:+.2f}".replace("-", MINUS)
                return f"{s} [{v[1]:.2f}, {v[2]:.2f}]".replace("-", MINUS)
            return str(v)
        parts = []
        if "primary_A_fast_minus_others_c" in F:
            parts.append(f"A {tri(F['primary_A_fast_minus_others_c'])}¢ {F.get('verdict_A_fast_tier', '')}".strip())
        if "primary_m30_per_share_c" in F:
            parts.append(f"B {tri(F['primary_m30_per_share_c'])}¢ {F.get('verdict_B_v2_book', '')}".strip())
        if "v2_trades" in F:
            parts.append(f"n = {int(F['v2_trades']):,}")
        src = F_FWD
        for v3 in sorted(ROOT.glob("results/tier0_v3/forward*/results.json")) + sorted(ROOT.glob("results/tier0_v3/forward*.json")):
            if "forward_dry" in str(v3):
                continue
            try:
                R3 = json.loads(v3.read_text())["results"]["frozen_v3"]["primary (lag 2.0 | tournament | trunc 0 | queue 0)"]["full_window"]
                c = f"{R3['per_share_c']:+.2f}".replace("-", MINUS)
                parts.append(f"v3 {c}¢ [{R3['per_share_ci95_c_lo']:.2f}, {R3['per_share_ci95_c_hi']:.2f}]".replace("-", MINUS))
                src += f" ; {v3.relative_to(ROOT)}"
            except (KeyError, TypeError, json.JSONDecodeError):
                pass
            break
        return "blind forward test (pre-registered, run once): " + (" · ".join(parts) or f"see {F_FWD}"), src
    am = forward_amendment((ROOT / F_HYP2).read_text())
    if am is None:
        raise Missing("no forward.json and no HYPOTHESIS_V2 amendment on the forward test: cannot word the forward slot")
    a, _, what = am
    if what.startswith("reinstated"):
        cell = "runs 2026-10-04 11:30 UTC (pre-registered)"
    else:
        cell = f"pre-registered but not run within the hackathon window (HYPOTHESIS_V2.md {a})"
    return f"blind forward test: {cell}", f"HYPOTHESIS_V2.md {a} (forward test {what}); results/v2/forward.json absent"


def forward_ran() -> bool:
    return (ROOT / F_FWD).exists()


# ------------------------------------------------------------------------------------------------ money counter
SCORE_RE = re.compile(
    r"^\s*(IN SAMPLE|OUT OF SAMPLE)\s+start \$([\d,]+) → \$([\d,]+)\s+\(([+−-]\$[\d,.]+), ([+−-][\d.]+%)\)\s+·\s+"
    r"(\d+) days · ([\d,]+) fills · win ([\d.]+)% · profitable days (\d+)% · Sharpe ([\d.]+) · max DD ([+−-]\$[\d,.]+)")


def money_counter() -> dict:
    """Run scripts/money_counter.py --speed 50 non-interactively; keep its final SCORECARD."""
    ASSETS.mkdir(exist_ok=True)
    cap = ASSETS / "money_counter_scorecard.txt"
    cmd = ["nice", "-n", "10", sys.executable, "scripts/money_counter.py", "--speed", "50"]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        out = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)
        if r.returncode != 0 or "SCORECARD" not in out:
            raise RuntimeError((r.stderr or out)[-400:])
        block = out[out.index("SCORECARD"):].rstrip() + "\n"
        cap.write_text("$ .venv/bin/python scripts/money_counter.py --speed 50\n...\n" + block)
        fresh = True
    except Exception as e:  # noqa: BLE001  (clean clone without data: fall back to the committed capture)
        if not cap.exists():
            raise
        print(f"WARNING: money counter not run ({str(e)[:120]}); using the committed capture {cap.relative_to(ROOT)}")
        block = cap.read_text()
        fresh = False
    rows = {}
    for line in block.splitlines():
        m = SCORE_RE.match(line)
        if m:
            k = "is" if m.group(1) == "IN SAMPLE" else "oos"
            rows[k] = dict(zip(["label", "start", "end", "pnl", "ret", "days", "fills", "win", "pdays", "sharpe", "mdd"],
                               m.groups()))
            rows[k]["line"] = line.strip()
    head = next((x for x in block.splitlines() if x.startswith("SCORECARD")), "SCORECARD")
    if set(rows) != {"is", "oos"}:
        raise RuntimeError("could not parse the money counter SCORECARD")
    return {"rows": rows, "head": head, "fresh": fresh, "file": str(cap.relative_to(ROOT))}


# ------------------------------------------------------------------------------------------------ video clip
def cv_clip() -> tuple[Path, Path, float, str]:
    """The models segment of the final video (table tennis -> real tennis -> tennis spin), muted, for slide 4."""
    tl = {t["id"]: t for t in VID_FINAL["timeline"]}
    t0 = tl["tt"]["start_s"]
    t1 = tl["tennis"]["start_s"] + tl["tennis"]["dur_s"]
    src = ROOT / F_VIDEO
    ASSETS.mkdir(exist_ok=True)
    clip, poster, stamp = ASSETS / "cv_models_clip.mp4", ASSETS / "cv_models_poster.png", ASSETS / "cv_models_clip.sha"
    key = hashlib.sha256(src.read_bytes()).hexdigest()[:16] + f"|{t0:.3f}|{t1:.3f}"
    if not (clip.exists() and poster.exists() and stamp.exists() and stamp.read_text() == key):
        ff = shutil.which("ffmpeg")
        if not ff and clip.exists() and poster.exists():
            print("WARNING: ffmpeg not found; using the committed clip docs/deck/assets/cv_models_clip.mp4")
            return clip, poster, t1 - t0, f"{F_VIDEO} [{t0:.1f}–{t1:.1f} s] (committed cut)"
        if not ff:
            raise RuntimeError("ffmpeg not found: cannot cut the CV clip from the final video")
        subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", str(src), "-an",
                        "-vf", "scale=1280:-2", "-c:v", "libx264", "-crf", "26", "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(clip)], check=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "2.0", "-i", str(clip), "-frames:v", "1", str(poster)], check=True)
        stamp.write_text(key)
    return clip, poster, t1 - t0, f"{F_VIDEO} [{t0:.1f}–{t1:.1f} s] (segments tt, tennis_real, tennis of final.timeline)"


# ------------------------------------------------------------------------------------------------ drawing helpers
def rgb(h):
    return RGBColor.from_string(h)


class R:
    def __init__(self, text, size=16, color=INK, bold=False, font=FONT, italic=False, spc=None):
        self.text, self.size, self.color, self.bold, self.font, self.italic, self.spc = text, size, color, bold, font, italic, spc


class P:
    def __init__(self, *runs, align="l", before=0, after=0, line=None):
        self.runs = [r if isinstance(r, R) else R(r) for r in runs]
        self.align, self.before, self.after, self.line = align, before, after, line


ALIGN = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}
ANCHOR = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}


def style_run(run, r: R):
    f = run.font
    f.size, f.bold, f.italic, f.name = Pt(r.size), r.bold, r.italic, r.font
    f.color.rgb = rgb(r.color)
    if r.spc:
        run._r.get_or_add_rPr().set("spc", str(int(r.spc * 100)))


def fill_frame(tf, paras, anchor="t", inset=(0, 0, 0, 0), wrap=True):
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
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    fill_frame(tb.text_frame, paras, anchor, inset, wrap)
    if name:
        tb.name = name
    return tb


def box(slide, x, y, w, h, fill=CARD_L, line=None, line_w=0.75, radius=0.0, name=None, dash=False, shape=None):
    kind = shape or (MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE)
    s = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if radius and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = min(0.5, radius / min(w, h))
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(line_w)
        if dash:
            s.line.dash_style = MSO_LINE.DASH
    s.shadow.inherit = False
    if name:
        s.name = name
    return s


def hline(slide, x, y, w, color, weight=0.75, dash=False, name=None, vertical=False):
    x2, y2 = (x, y + w) if vertical else (x + w, y)
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y), Inches(x2), Inches(y2))
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(weight)
    if dash:
        c.line.dash_style = MSO_LINE.ROUND_DOT
    if name:
        c.name = name
    return c


def fit_picture(slide, path, x, y, w, h, name=None, align="c"):
    from PIL import Image

    with Image.open(path) as im:
        ar = im.width / im.height
    pw, ph = (w, w / ar) if w / h <= ar else (h * ar, h)
    px = x + (w - pw) / 2 if align == "c" else x
    pic = slide.shapes.add_picture(str(path), Inches(px), Inches(y + (h - ph) / 2), Inches(pw), Inches(ph))
    if name:
        pic.name = name
    return pic, (px, y + (h - ph) / 2, pw, ph)


def autoplay_video(slide, pic, dur_ms: int, loop: bool, mute: bool):
    """Start the movie when the slide appears (PowerPoint's 'Start: Automatically'), optionally looping and muted."""
    sld = slide._element
    old = sld.find(qn("p:timing"))
    spid = pic.shape_id
    rep = ' repeatCount="indefinite"' if loop else ""
    mut = ' mute="1"' if mute else ""
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
<p:video><p:cMediaNode vol="{0 if mute else 80000}"{mut}><p:cTn id="7"{rep} fill="hold" display="0"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn>
<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cMediaNode></p:video>
</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>"""
    new = etree.fromstring(re.sub(r">\s+<", "><", xml))
    if old is not None:
        old.addprevious(new)
        sld.remove(old)
    else:
        ext = sld.find(qn("p:extLst"))
        (ext.addprevious(new) if ext is not None else sld.append(new))


def cell_borders(cell, bottom=None, w=0.75):
    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        for el in tcPr.findall(qn(tag)):
            tcPr.remove(el)
    for i, (tag, col) in enumerate((("a:lnL", None), ("a:lnR", None), ("a:lnT", None), ("a:lnB", bottom))):
        ln = etree.Element(qn(tag), w=str(int(w * 12700)))
        if col:
            sf = etree.SubElement(ln, qn("a:solidFill"))
            etree.SubElement(sf, qn("a:srgbClr"), val=col)
        else:
            etree.SubElement(ln, qn("a:noFill"))
        tcPr.insert(i, ln)


def table(slide, x, y, col_w, row_h, rows, name, dark=False, size=13, header_size=11, first_bold=False, rule=None):
    """Hairline table: header row in small grey caps, rows separated by a thin rule. Cells: str or list[P]."""
    fg, sub = (WHITE, GREY_D) if dark else (INK, GREY_L)
    rule = rule or (RULE_D if dark else RULE_L)
    gf = slide.shapes.add_table(len(rows), len(col_w), Inches(x), Inches(y), Inches(sum(col_w)), Inches(sum(row_h)))
    gf.name = name
    tbl = gf.table
    tbl.first_row = tbl.horz_banding = False
    sid = tbl._tbl.tblPr.find(qn("a:tableStyleId"))
    if sid is not None:
        sid.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"
    for j, w in enumerate(col_w):
        tbl.columns[j].width = Inches(w)
    for i, h in enumerate(row_h):
        tbl.rows[i].height = Inches(h)
    for i, row in enumerate(rows):
        for j, content in enumerate(row):
            cell = tbl.cell(i, j)
            if isinstance(content, str):
                if i == 0:
                    content = [P(R(content, header_size, sub, bold=True), align="l" if j == 0 else "r")]
                else:
                    content = [P(R(content, size, fg, bold=first_bold and j == 0), align="l" if j == 0 else "r")]
            tf = cell.text_frame
            tf.word_wrap = True
            for k, p in enumerate(content):
                para = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                para.alignment = ALIGN[p.align]
                for r in p.runs:
                    run = para.add_run()
                    run.text = r.text
                    style_run(run, r)
            cell.margin_left = cell.margin_right = Inches(0.06)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell_borders(cell, bottom=rule if i < len(rows) - 1 else None)
            cell.fill.background()
    return tbl


# ------------------------------------------------------------------------------------------------ template
def setup_template(prs):
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    m = prs.slide_master
    m.background.fill.solid()
    m.background.fill.fore_color.rgb = rgb(WHITE)
    theme = m.part.part_related_by(RT.THEME)
    root = etree.fromstring(theme.blob)
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    root.set("name", "Courtside")
    cs = root.find(f"{a}themeElements/{a}clrScheme")
    cs.set("name", "Courtside")
    scheme = {"dk1": BLACK, "lt1": WHITE, "dk2": INK, "lt2": CARD_L, "accent1": ORANGE, "accent2": "6E6E73",
              "accent3": "A1A1A6", "accent4": "1D1D1F", "accent5": "D2D2D7", "accent6": "F4AE88",
              "hlink": ORANGE, "folHlink": GREY_L}
    for k, v in scheme.items():
        slot = cs.find(f"{a}{k}")
        for child in list(slot):
            slot.remove(child)
        etree.SubElement(slot, f"{a}srgbClr", val=v)
    fs = root.find(f"{a}themeElements/{a}fontScheme")
    fs.set("name", "Courtside")
    for which in ("majorFont", "minorFont"):
        latin = fs.find(f"{a}{which}/{a}latin")
        latin.attrib.clear()
        latin.set("typeface", FONT)
    theme._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def new_slide(prs, dark):
    layout = next(lo for lo in prs.slide_layouts if lo.name == "Title Only")
    s = prs.slides.add_slide(layout)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb(BLACK if dark else WHITE)
    return s


def set_title(s, title, dark, y=0.78, size=34, w=None, h=0.75):
    ph = s.shapes.title
    ph.left, ph.top, ph.width, ph.height = Inches(M), Inches(y), Inches(w or CW), Inches(h)
    tf = ph.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.paragraphs[0].text = ""
    tf.paragraphs[0].alignment = PP_ALIGN.LEFT
    run = tf.paragraphs[0].add_run()
    run.text = title
    style_run(run, R(title, size, WHITE if dark else INK, bold=True))
    bp = tf._txBody.bodyPr
    for k in ("lIns", "tIns", "rIns", "bIns"):
        bp.set(k, "0")
    return ph


def chrome(s, n, chapter, dark, label=None, backup=False):
    """Chapter label top left, honesty label top right, wordmark + slide number bottom."""
    sub = GREY_D if dark else GREY_L
    text(s, M, 0.36, 5.5, 0.28, P(R(f"{n:02d}" if not backup else "Q&A", 10.5, ORANGE, bold=True, spc=1),
                                  R("   " + chapter.upper(), 10.5, sub, bold=True, spc=1.5)), anchor="m", name="Chapter")
    if label:
        text(s, SW - M - 6.6, 0.36, 6.6, 0.28, P(R(label, 10, sub), align="r"), anchor="m", name="Label")
    hline(s, M, 7.02, CW, RULE_D if dark else RULE_L, 0.5, name="Footer rule")
    text(s, M, 7.08, 6.0, 0.24, P(R("COURTSIDE", 9, sub, bold=True, spc=2.5),
                                  R("   Gator Quant Hacks 2026 · Systematic Trading · paper trading only", 9, sub)),
         anchor="m", name="Footer")
    text(s, SW - M - 1.0, 7.08, 1.0, 0.24, P(R(str(n), 9, sub), align="r"), anchor="m", name="Slide number")


def stat(s, x, y, w, big, cap, dark, color=None, big_size=40, cap_size=12, name="Stat", cap_h=0.6):
    col = color or (WHITE if dark else INK)
    text(s, x, y, w, big_size / 72 * 1.25, P(R(big, big_size, col, bold=True)), anchor="b", name=f"{name}: value")
    text(s, x, y + big_size / 72 * 1.3, w, cap_h, P(R(cap, cap_size, GREY_D if dark else GREY_L), line=1.1),
         name=f"{name}: caption")


def notes(s, window: str, script: str, extra: str = ""):
    body = f"[{window}]\n{script.strip()}"
    if extra:
        body += "\n\n" + extra.strip()
    s.notes_slide.notes_text_frame.text = body


# ------------------------------------------------------------------------------------------------ timing
DUR_S = [15, 30, 30, 40, 30, 35, 35, 25, 30, 15]
TALK_S = 4 * 60 + 45
assert sum(DUR_S) == TALK_S


def window(i: int) -> str:
    a = sum(DUR_S[:i])
    b = a + DUR_S[i]
    return f"{a // 60}:{a % 60:02d}–{b // 60}:{b % 60:02d} · {DUR_S[i]} s"


SCRIPTS: dict[int, str] = {}


# ================================================================================================ slides
def team() -> list[str]:
    t = (ROOT / F_TEAM).read_text()
    line = next(x for x in t.splitlines() if "University of Florida" in x and "," in x)
    names = line.split("(")[0].strip()
    return [n.strip() for n in names.split(",")]


def s01_title(prs):
    _SLIDE[0] = "1 title"
    s = new_slide(prs, dark=True)
    names = team()
    rec(", ".join(names), F_TEAM)
    set_title(s, "COURTSIDE", True, y=1.9, size=80, h=1.4)
    text(s, M, 3.35, CW, 1.1, [
        P(R("Computer vision calls table-tennis points before the ball lands.", 24, WHITE)),
        P(R("We priced that speed for Polymarket tennis, in simulation.", 24, GREY_D))], name="Tagline")
    hline(s, M, 4.75, 1.2, ORANGE, 2.5, name="Accent rule")
    text(s, M, 4.95, 11, 0.4, P(R("   ·   ".join(names), 17, WHITE, bold=True)), name="Team")
    text(s, M, 5.38, 11, 0.35, P(R("University of Florida  ·  Gator Quant Hacks 2026  ·  Systematic Trading", 14, GREY_D)),
         name="Event")
    text(s, M, 6.62, CW, 0.3, P(R("Paper trading only. No real money. CV strategy results are simulated at an assumed feed "
                                  "latency (licensed feed not purchased).", 10.5, GREY_D)), name="Disclosure")
    SCRIPTS[1] = ("We're COURTSIDE, four of us from the University of Florida. Polymarket reprices live tennis about a second "
                  "after every point. Our computer vision calls table-tennis points before the ball lands; in simulation, we "
                  "priced that speed for tennis.")
    notes(s, window(0), SCRIPTS[1], "Click: slide 2 (the strategy in one sentence).")
    return s


def race_axis_x(t, x0, w, lo=0.02, hi=60.0):
    import math
    return x0 + (math.log10(t) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * w


def s02_strategy(prs):
    _SLIDE[0] = "2 strategy + race"
    s = new_slide(prs, dark=True)
    chrome(s, 2, "The strategy", True, label="public Polymarket books · stamp lag not measured · CV calls: table tennis (tennis simulated)")
    set_title(s, "Whoever learns the point first takes the stale price", True)
    text(s, M, 1.62, CW, 0.95, P(
        R("Our computer vision calls the point ", 24, WHITE), R("before the ball lands", 24, ORANGE, bold=True),
        R(", so we trade the Polymarket match price ", 24, WHITE), R("before it reprices", 24, ORANGE, bold=True), R(".", 24, WHITE),
        line=1.1), name="One sentence")

    # the information race on a log time axis (seconds after the point ends)
    x0, w, y0 = M + 2.55, 5.45, 3.05
    lo_b, hi_b = VID["reprice_band_s"]["value"]
    band = VV("reprice_band_s", f"{lo_b:.1f}–{hi_b:.1f}")
    bx1, bx2 = race_axis_x(lo_b, x0, w), race_axis_x(hi_b, x0, w)
    box(s, bx1, y0 - 0.12, bx2 - bx1, 3.08, fill="1C1C1E", name="Reprice band")
    text(s, bx1 - 0.6, y0 - 0.52, bx2 - bx1 + 1.2, 0.38, P(R(f"book reprices {band} s after the point (inferred)", 10, GREY_D),
                                                         align="c"), name="Reprice band label")
    ours = N("e2e.ours")
    vb = N("lat.video_band")
    pub = N("lat.webrtc_public")
    espn, wta = N("lat.espn"), N("lat.wta")
    pre_l, cal_l = N("cv.pre.lag"), N("cv.cal.lag")
    tv_lo, tv_hi = VID["band_tv"]["value"]
    VV("band_tv")
    rows = [
        ("Our pipeline, frame → order", 0.054, 0.054, f"{ours} ms", "measured", ORANGE),
        ("Umpire's point stamp", float(pre_l), float(cal_l), f"{pre_l}–{cal_l} s", "unmeasured", GREY_D),
        ("Licensed betting video", 0.5, 8.0, f"{vb} s", "vendor-stated", WHITE),
        ("TV broadcast", tv_lo, tv_hi, f"{tv_lo:g}–{tv_hi:g} s", "published", WHITE),
        ("Public stream", float(pub), float(pub), f"{pub} s", "measured", WHITE),
        ("Score feeds (ESPN, WTA)", float(espn), float(wta), f"{float(espn):.0f}–{float(wta):.0f} s", "measured", WHITE),
    ]
    rh = 0.47
    for i, (lab, a, b, val, how, col) in enumerate(rows):
        y = y0 + i * rh
        text(s, M, y, 2.45, rh, P(R(lab, 13, ORANGE if col == ORANGE else WHITE, bold=col == ORANGE), align="r"),
             anchor="m", name=f"Race row {i}")
        xa, xb = race_axis_x(a, x0, w), race_axis_x(b, x0, w)
        if b > a:
            box(s, xa, y + rh / 2 - 0.05, xb - xa, 0.10, fill=col if col != WHITE else "8E8E93", name=f"Race bar {i}",
                dash=False)
        else:
            box(s, xa - 0.07, y + rh / 2 - 0.07, 0.14, 0.14, fill=col if col != WHITE else "8E8E93",
                shape=MSO_SHAPE.OVAL, name=f"Race dot {i}")
        text(s, xb + 0.12, y, 1.6, rh, P(R(val, 12, ORANGE if col == ORANGE else WHITE, bold=True),
                                          R(f"  {how}", 10, GREY_D)), anchor="m", name=f"Race value {i}")
    ya = y0 + len(rows) * rh + 0.02
    hline(s, x0, ya, w, "48484A", 0.75, name="Race axis")
    for t in (0.05, 0.1, 0.5, 1, 3, 10, 60):
        xt = race_axis_x(t, x0, w)
        text(s, xt - 0.3, ya + 0.04, 0.6, 0.22, P(R(f"{t:g}", 10, GREY_D), align="c"), name=f"Tick {t:g}")
    text(s, x0, ya + 0.27, w, 0.24, P(R("seconds after the point ends (log scale)", 10, GREY_D), align="c"), name="Axis title")

    # right column: the two facts that make it a race
    xr = M + 9.95
    stale = VV("stale_pre_usd", "$" + VID["stale_pre_usd"]["shown"])
    stat(s, xr, 2.6, CW - 9.95, stale, "median resting at the old price 250 ms before the book moves "
         f"(one day, {VV('stale_n')} points)", True, color=ORANGE, big_size=34, cap_size=11, cap_h=1.2, name="Stale depth")
    stat(s, xr, 4.5, CW - 9.95, f"{N('venue.delay')} s", "venue hold on every taker order: know before the book moves",
         True, big_size=34, cap_size=11, cap_h=0.85, name="Venue hold")
    text(s, xr, 6.05, CW - 9.95, 0.8, P(R(f"Book moves {N('lat.book_vs_stamp')} s before the official stamp "
                                           f"(n = {N('lat.n_points')}).", 11, GREY_D), line=1.1), name="Book vs stamp")
    SCRIPTS[2] = (f"The strategy in one sentence: our computer vision calls the point before the ball lands, so we trade the "
                  f"match price before it reprices. It's a race. Our own code turns a frame into an order in {ours} "
                  f"milliseconds. The book reprices about one to two seconds after the point, and just before it does, a "
                  f"median {stale} still rests at the old price. Public streams run {pub} seconds behind, score feeds "
                  f"{float(espn):.0f} to {float(wta):.0f}. Whoever learns the point first takes that stale quote.")
    notes(s, window(1), SCRIPTS[2], "If asked about the stamp: its lag after the point is not measured; pre-registered "
          f"{pre_l} s, post hoc {cal_l} s. The book moves a median {N('lat.book_vs_stamp')} s before the stamp.")


def s03_edge(prs):
    _SLIDE[0] = "3 edge"
    s = new_slide(prs, dark=False)
    chrome(s, 3, "The edge exists", False, label="Polymarket public tapes · wallets' own fills, not our trades")
    set_title(s, "The edge exists, and it is speed", False)
    fit_picture(s, ROOT / "results/paper/v2/fig2_edge.png", M - 0.05, 1.65, 8.45, 4.4, name=f"Fig: edge (paper Fig. {PR('fig:edge')})", align="l")
    text(s, M, 6.15, 8.3, 0.7, P(R("Net 30 s markout after taker fees, ¢ per share; fast tier = walk-forward wallets trading "
                                   f"within 3 s of a score move. Right: v2 at the fast tier's own fills. Source: paper Fig. {PR('fig:edge')}.",
                                   10, GREY_L), line=1.1), name="Fig caption")
    xr, wr = M + 8.75, CW - 8.75
    mi, mo = N("ft.months.is"), N("ft.months.oos")
    stat(s, xr, 1.6, wr, f"{mi} · {mo}", "months positive for the fast tier, in sample · held out", False, color=ORANGE,
         big_size=36, name="Months")
    stat(s, xr, 2.85, wr, f"{N('ft.c.is')}¢ · {N('ft.c.oos')}¢", f"fast tier per share, after fees. Everyone else "
         f"{N('oth.c.is')}¢ · {N('oth.c.oos')}¢; copy them 3 s later {N('copy3.c.is')}¢ · {N('copy3.c.oos')}¢",
         False, big_size=28, cap_h=0.85, name="Per share")
    stat(s, xr, 4.35, wr, f"t = {N('fac.alpha_t')}", f"four-factor alpha (v2 at fast-tier fills); largest factor |t| "
         f"{N('fac.max_t')}, R² {N('fac.r2')}: factor-neutral", False, big_size=28, cap_h=0.85, name="Alpha")
    text(s, xr, 5.85, wr, 0.9, P(R(f"Competition is biting: the edge shrinks {N('ft.slope')}¢ a month "
                                   f"(t = {N('ft.slope.t')}) and stays positive.", 11, GREY_L), line=1.1), name="Decay")
    SCRIPTS[3] = (f"First IC question: does the edge exist? Yes, and it's speed. On public Polymarket tapes, wallets that trade "
                  f"within three seconds of a point earn after fees in {mi} in-sample months and {mo} held-out months: "
                  f"{N('ft.c.is')} and {N('ft.c.oos')} cents a share. Everyone else loses about a cent, and copying the fast "
                  f"tier three seconds later loses too. It isn't market beta: four-factor alpha t-stat {N('fac.alpha_t')}, "
                  f"no factor above {N('fac.max_t')}.")
    notes(s, window(2), SCRIPTS[3], "The video says '11 calendar months of 11': August sits in both periods (9 + 3 rows).")


def s04_models(prs):
    _SLIDE[0] = "4 CV models"
    s = new_slide(prs, dark=True)
    chrome(s, 4, "The CV models", True, label="OpenTTGames held-out games (CC BY-NC-SA 4.0) · tennis: simulated physics")
    set_title(s, "It calls table-tennis points before the ball lands", True)
    clip, poster, dur, src = cv_clip()
    rec(f"{dur:.1f} s clip", src)
    vw = 7.35
    vh = vw * 9 / 16
    pic = s.shapes.add_movie(str(clip), Inches(M), Inches(1.75), Inches(vw), Inches(vh),
                             poster_frame_image=str(poster), mime_type="video/mp4")
    pic.name = "Video: CV models (from the final video, muted, loops)"
    autoplay_video(s, pic, int(round(dur * 1000)), loop=True, mute=True)
    text(s, M, 1.75 + vh + 0.08, vw, 0.5, P(R(f"From our 90 s video (segment {dur:.0f} s, muted, loops): engine calls on real "
                                              "held-out table tennis, our tracker on a licensed tennis rally (no calls), the spin "
                                              f"model in simulated physics. {tennis_credit()[0].upper() + tennis_credit()[1:]}.",
                                              9.5, GREY_D), line=1.05), name="Video caption")
    xr, wr = M + vw + 0.4, CW - vw - 0.4
    tp, nm = N("cv.eng.tp"), N("cv.eng.nmiss")
    blocks = [
        ("Table tennis · real held-out footage · live causal engine",
         f"{tp} of {nm}", f"misses called before the ball got there, none wrong (95% lower bound {N('cv.eng.wil_lo')}); "
         f"median lead {N('cv.eng.lead')} ms; the video's cold open: {VV('cold_lead_ms')} ms early"),
        ("Tennis · spin-aware tracker · simulated physics",
         f"{N('cv.spin.bls200')} cm", f"landing error 200 ms before the bounce, vs {N('cv.spin.base200')} cm without spin; "
         f"OUT precision {float(N('spin.out.prec200')):.0%}, recall {float(N('spin.out.rec200')):.0%}"),
        ("GPU engine · NVIDIA L4",
         f"{N('cv.eng.p50')} ms", f"per frame p50 ({N('cv.eng.p99')} ms p99) at {N('cv.eng.fps')} fps; "
         f"{N('cv.eng.dropped')} of {N('cv.eng.frames')} frames dropped; the video's {VV('pf_lat')} ms is the p50 per "
         f"emitted call"),
    ]
    y = 1.72
    for i, (head, big, cap) in enumerate(blocks):
        text(s, xr, y, wr, 0.28, P(R(head, 11, ORANGE if i == 0 else GREY_D, bold=True)), name=f"Model {i}: head")
        text(s, xr, y + 0.27, wr, 0.62, P(R(big, 32, WHITE, bold=True)), anchor="m", name=f"Model {i}: value")
        text(s, xr, y + 0.9, wr, 0.62, P(R(cap, 11.5, GREY_D), line=1.1), name=f"Model {i}: caption")
        y += 1.68
    SCRIPTS[4] = (f"Can a model be that fast? These are real table-tennis games the model never saw. Streamed causally, our "
                  f"live engine called {tp} of {nm} misses before the ball got there, none wrong, with a median lead of "
                  f"{N('cv.eng.lead')} milliseconds. On one L4 GPU it keeps up with 120-frame video: {N('cv.eng.dropped')} of "
                  f"{N('cv.eng.frames')} frames dropped, {N('cv.eng.p50')} milliseconds a frame. For tennis we built a "
                  f"spin-aware tracker; in simulated physics it cuts landing error from {N('cv.spin.base200')} to "
                  f"{N('cv.spin.bls200')} centimetres 200 milliseconds before the bounce. Tennis is simulation: we have no "
                  f"tennis match video.")
    notes(s, window(3), SCRIPTS[4], "If asked: the offline evaluation used a look-ahead feature; the live engine numbers above "
          "are the causal ones (backup Q6). The clip loops muted; talk over it.")


def s05_pipeline(prs):
    _SLIDE[0] = "5 frame to trade"
    s = new_slide(prs, dark=False)
    chrome(s, 5, "Frame to trade", False, label="paper: order built, never signed or sent · 1 s feed simulated")
    total = N("e2e.total")
    set_title(s, f"Frame to executable order in {float(total.replace(',', '')) / 1000:.1f} s, inside the 3 s bar", False)
    fit_picture(s, ROOT / "results/paper/v2/fig4_frame_to_trade.png", M - 0.05, 1.7, 8.6, 3.7, name=f"Fig: frame to trade (paper Fig. {PR('fig:f2t')})",
                align="l")
    text(s, M, 5.5, 8.4, 0.6, P(R(f"Stage means of {N('e2e.n')} traces: our footage over WebRTC into the CV engine on a laptop, "
                                  "a simulated 1 s licensed feed, the measured network and the venue's 1 s hold. Shaded: when "
                                  f"the book reprices. Source: paper Fig. {PR('fig:f2t')}, results/e2e/summary.json.", 10, GREY_L), line=1.1),
         name="Fig caption")
    xr, wr = M + 8.9, CW - 8.9
    stat(s, xr, 1.65, wr, f"{N('e2e.ours')} ms", "our part, frame to order ready (p50)", False, color=ORANGE, big_size=38,
         name="Ours")
    stat(s, xr, 2.95, wr, f"{total} ms", f"total with a 1 s feed, {N('e2e.net')} ms network and the 1 s venue hold; "
         f"{N('e2e.margin')} ms to spare, every trace under the bar", False, big_size=30, cap_h=0.85, name="Total")
    stat(s, xr, 4.45, wr, f"{N('cv.eng.p50')} ms", f"vision per frame on an L4 GPU, p50 ({VV('pf_lat')} ms per emitted "
         f"call; WebRTC frame to call {N('cv.webrtc')})",
         False, big_size=30, cap_h=0.7, name="GPU")
    box(s, M, 6.18, CW, 0.66, fill=CARD_L, radius=0.08, name="Bar card")
    text(s, M + 0.25, 6.18, CW - 0.5, 0.66, P(
        R("Under 3 s is necessary, not sufficient. ", 13, INK, bold=True),
        R(f"Pre-registered, the call must reach the venue {N('cv.call_before_stamp')} s before the umpire's stamp; "
          f"orders sent: {N('e2e.sent')}.", 13, GREY_L)), anchor="m", name="Bar")
    SCRIPTS[5] = (f"The organisers asked: can you trade inside three seconds? We measured it end to end: our footage over "
                  f"WebRTC into the engine, a call, a paper order against a live book. Our part is {N('e2e.ours')} "
                  f"milliseconds. Add a simulated one-second feed, {N('e2e.net')} milliseconds of network and the venue's "
                  f"one-second hold: {total} milliseconds, every trace under the bar. But under three seconds isn't enough: "
                  f"the call has to reach the venue about {N('cv.call_before_stamp')} seconds before the umpire's stamp.")
    notes(s, window(4), SCRIPTS[5], f"{N('e2e.n')} order traces; the order is unsigned and never sent; table-tennis calls "
          "mapped onto a tennis market for timing only (backup Q1).")


def s06_speed(prs):
    _SLIDE[0] = "6 speed"
    s = new_slide(prs, dark=False)
    chrome(s, 6, "What speed is worth", False,
           label="simulated: assumed feed latency (licensed feed not purchased); parameters measured")
    set_title(s, "Every second of feed delay costs the edge", False)
    fit_picture(s, ROOT / "results/paper/v2/fig3_speed_value.png", M - 0.05, 1.65, 5.95, 2.75, name=f"Fig: speed value (paper Fig. {PR('fig:speed')})",
                align="l")
    text(s, M, 4.45, 5.8, 0.6, P(R("Net $ per day against the assumed feed delay; solid IS, dashed held out. Source: paper "
                                    f"Fig. {PR('fig:speed')}, results/tier0/latency_sweep.json.", 10, GREY_L), line=1.1),
         name="Fig caption")
    # scenario table: pre-registered first, then post hoc
    xt = M + 6.1
    hdr_pre = f"Pre-registered, L = {N('cv.pre.lag')} s"
    hdr_post = f"Post hoc, L = {N('cv.cal.lag')} s"
    sub = GREY_L

    def cell(a, b, bold=False, col=INK):
        return [P(R(f"{a}", 13, col, bold=bold), R(f" · {b}", 13, col if bold else GREY_L, bold=False), align="r")]
    rows = [
        [[P(R("Feed latency (assumed)", 10.5, sub, bold=True))],
         [P(R(hdr_pre, 10.5, INK, bold=True), align="r"), P(R("$/day IS · OOS, Sharpe", 9, sub), align="r")],
         [P(R(hdr_post, 10.5, ORANGE, bold=True), align="r"), P(R("$/day IS · OOS, Sharpe", 9, sub), align="r")]],
    ]
    for v, lab in (("v05", "0.5 s best case"), ("v1", "1 s base case"), ("v3", "3 s requirement")):
        pre = (N(f"sc.pre.is.{v}.usd"), N(f"sc.pre.oos.{v}.usd"), N(f"sc.pre.is.{v}.sr"), N(f"sc.pre.oos.{v}.sr"))
        cal = (N(f"sc.cal.is.{v}.usd"), N(f"sc.cal.oos.{v}.usd"), N(f"sc.cal.is.{v}.sr"), N(f"sc.cal.oos.{v}.sr"))
        rows.append([[P(R(lab, 13, INK, bold=v == "v1"))],
                     [P(R(f"{pre[0]} · {pre[1]}", 13, INK, bold=True), align="r"),
                      P(R(f"Sharpe {pre[2]} · {pre[3]}", 10, GREY_L), align="r")],
                     [P(R(f"{cal[0]} · {cal[1]}", 13, ORANGE, bold=True), align="r"),
                      P(R(f"Sharpe {cal[2]} · {cal[3]}", 10, GREY_L), align="r")]])
    rows.append([[P(R("Break-even delay", 13, INK))],
                 [P(R(f"{N('cv.pre.be.is')} · {N('cv.pre.be.oos')} s", 13, INK), align="r")],
                 [P(R(f"{N('cv.cal.be.is')} · {N('cv.cal.be.oos')} s", 13, INK), align="r")]])
    rows.append([[P(R("Read per point, 1 s", 13, INK))],
                 [P(R(f"{N('pp.pre.is.usd')} · {N('pp.pre.oos.usd')}", 13, INK), align="r")],
                 [P(R(f"{N('pp.cal.is.usd')} · {N('pp.cal.oos.usd')}", 13, INK), align="r")]])
    table(s, xt, 1.62, [1.95, 1.95, 1.93], [0.55, 0.56, 0.56, 0.56, 0.4, 0.4], rows, f"Latency scenarios (paper Table {PR('tab:lat')})")
    text(s, xt, 4.7, CW - 6.1, 0.4, P(R("$/day held out (OOS) is a burned, non-blind window; 20 seeds a cell.", 10, GREY_L)),
         name="Table note")
    # the three takeaways
    y = 5.2
    cards = [
        ("Pre-registered", f"breaks even near {N('cv.pre.be.range')} s: {N('cv.pre.oos.usd')} a day held out at 1 s, "
                           f"{N('cv.pre.oos.c')}¢ {N('cv.pre.oos.c_ci')} a share", INK),
        ("Post hoc", f"the stamp lag {N('cv.cal.lag')} s was inferred after looking (95% CI {N('cv.cal.lag_ci')} s): "
                     f"{N('cv.cal.oos.usd')} a day held out at 1 s; {N('cv.at_lo.oos.usd')} at the CI's low end", ORANGE),
        ("Both readings", f"lose by 3 s. Trades are points that later repriced ≥4¢: selected on outcomes, not ex ante; "
                          f"a replay calling every point on real books loses ({N('rp.v1l2.c')}¢)", INK),
    ]
    cw = (CW - 0.4) / 3
    for i, (h, b, col) in enumerate(cards):
        x = M + i * (cw + 0.2)
        box(s, x, y, cw, 1.6, fill=CARD_L, radius=0.08, name=f"Takeaway {i}: card")
        text(s, x + 0.22, y + 0.14, cw - 0.44, 1.35, [P(R(h, 13, col, bold=True), after=3), P(R(b, 12, INK), line=1.1)],
             name=f"Takeaway {i}")
    SCRIPTS[6] = (f"So what is speed worth? Feed latency is the one input we can't measure without buying a feed, so we show "
                  f"three scenarios. Pre-registered, the CV strategy makes {N('sc.pre.oos.v05.usd')}, {N('sc.pre.oos.v1.usd')} "
                  f"and {N('sc.pre.oos.v3.usd')} a day held out at half a second, one second and three: it breaks even near "
                  f"one second. Our post hoc reading of the umpire's lag gives {N('sc.cal.oos.v05.usd')}, "
                  f"{N('sc.cal.oos.v1.usd')} and {N('sc.cal.oos.v3.usd')}, but that lag was inferred after looking, and read "
                  f"point by point the same data loses {N('cv.stc.oos.usd').replace(MINUS, '')} a day. By three seconds "
                  f"every reading loses.")
    notes(s, window(5), SCRIPTS[6], "Never present the post hoc number without the pre-registered one next to it (backup Q5).")


def s07_backtest(prs, mc):
    _SLIDE[0] = "7 backtest"
    s = new_slide(prs, dark=True)
    chrome(s, 7, "The backtest", True, label="v2 at the fast tier's own fills: the opportunity at their speed, not our execution")
    set_title(s, f"v2 backtest: Sharpe {N('v2.is.sr')} in sample, {N('v2.oos.sr')} held out", True)
    # left: the numbers
    cols = [("In sample", "is", f"{N('v2.is.start')} – {N('v2.is.end')}"),
            ("Held out (burned, non-blind)", "oos", f"{N('v2.oos.start')} – {N('v2.oos.end')}")]
    for j, (lab, k, span) in enumerate(cols):
        x = M + j * 3.05
        text(s, x, 1.68, 2.9, 0.3, P(R(lab, 11, GREY_D, bold=True)), name=f"{k}: label")
        text(s, x, 1.95, 2.9, 0.9, P(R(N(f"v2.{k}.sr"), 54, ORANGE if k == "is" else WHITE, bold=True)), anchor="m",
             name=f"{k}: Sharpe")
        lines = [f"Sharpe 95% CI {N(f'v2.{k}.sr_ci')}",
                 f"deflated Sharpe {N(f'v2.{k}.dsr')}",
                 f"{N(f'v2.{k}.c')}¢ a share {N(f'v2.{k}.ci')}",
                 f"{N(f'v2.{k}.pnl')} · {N(f'v2.{k}.trades')} trades",
                 f"{N(f'v2.{k}.mpos')} months up · max DD {N(f'v2.{k}.dd')}",
                 f"{span}, {N(f'v2.{k}.days')} days"]
        text(s, x, 2.9, 2.9, 2.4, [P(R(t, 13, WHITE if i < 3 else GREY_D), after=4) for i, t in enumerate(lines)],
             name=f"{k}: details")
    text(s, M, 5.25, 6.0, 1.55, [
        P(R(f"Deflated at {N('rig.N3386')} trials, held-out Sharpe is only {N('v2.oos.dsr')}: 40 days cannot rule out "
            f"luck.", 12, WHITE), after=4),
        P(R(f"We assumed a bug above Sharpe 3 and found one: fixing the onset look-ahead cut in-sample Sharpe from "
            f"{N('v2.onset.is.sr')} to {N('v2.is.sr')}. About {N('v2.trades_per_day')} small bets a day, net cap 100 shares "
            f"a match.", 11, GREY_D), line=1.1)], name="Rigor note")
    # right: money counter scorecard
    xr, wr = M + 6.45, CW - 6.45
    box(s, xr, 1.68, wr, 4.62, fill=CARD_D, line=RULE_D, radius=0.12, name="Scorecard card")
    text(s, xr + 0.3, 1.82, wr - 0.6, 0.3, P(R("$ scripts/money_counter.py --speed 50", 11, GREY_D, font=MONO)),
         name="Scorecard command")
    text(s, xr + 0.3, 2.12, wr - 0.6, 0.3, P(R(mc["head"].strip(), 9, GREY_D, font=MONO)),
         name="Scorecard head")
    rec(mc["head"], mc["file"])
    y = 2.6
    for k, lab in (("is", "IN SAMPLE"), ("oos", "OUT OF SAMPLE")):
        r = mc["rows"][k]
        for f in ("start", "end", "pnl", "ret", "days", "fills", "win", "pdays", "sharpe", "mdd"):
            rec(r[f], mc["file"] + f" :: {lab}.{f}")
        text(s, xr + 0.3, y, wr - 0.6, 0.3, P(R(lab, 11, GREY_D, bold=True, font=MONO, spc=1)), name=f"Scorecard {k}: label")
        text(s, xr + 0.3, y + 0.28, wr - 0.6, 0.62, P(R(r["pnl"].replace("-", MINUS), 36, ORANGE if k == "is" else WHITE,
                                                         bold=True, font=MONO), R(f"  {r['ret']}", 16, GREY_D, font=MONO)),
             anchor="m", name=f"Scorecard {k}: P&L")
        text(s, xr + 0.3, y + 0.92, wr - 0.6, 0.62, [
            P(R(f"${r['start']} → ${r['end']} · {r['days']} trading days · {r['fills']} fills", 10, WHITE, font=MONO)),
            P(R(f"win {r['win']}% · days up {r['pdays']}% · Sharpe {r['sharpe']} · max DD {r['mdd']}", 10, WHITE, font=MONO))],
             name=f"Scorecard {k}: details")
        y += 1.62
    text(s, xr + 0.3, 5.74, wr - 0.6, 0.56, P(R(
        f"Paper money, every v2 fill replayed: Sharpe over trading days ({mc['rows']['is']['days']} / "
        f"{mc['rows']['oos']['days']}), max DD trade by trade. The paper uses calendar days ({N('v2.is.days')} / "
        f"{N('v2.oos.days')}) and daily P&L: Sharpe {N('v2.is.sr')} / {N('v2.oos.sr')}, max DD {N('v2.is.dd')} / "
        f"{N('v2.oos.dd')}.", 9, GREY_D), line=1.05),
         name="Scorecard note")
    text(s, xr, 6.42, wr, 0.4, P(R(f"Fees ×2 held out: {N('v2.oos.fx2.c')}¢ a share; the edge does not survive doubled costs.",
                                   10.5, WHITE)), name="Cost note")
    SCRIPTS[7] = (f"The backtest of the market-structure book, v2, which trades at the fast tier's own fills: the opportunity "
                  f"at their speed, not our execution. Sharpe {N('v2.is.sr')} in sample and {N('v2.oos.sr')} on the held-out "
                  f"window, {N('v2.is.c')} and {N('v2.oos.c')} cents a share, both intervals above zero. Our money counter "
                  f"replays every fill: {mc['rows']['is']['pnl']} in sample, {mc['rows']['oos']['pnl']} held out. Deflated for "
                  f"{N('rig.N3386')} trials the held-out Sharpe is only {N('v2.oos.dsr')}: forty days can't rule out luck, "
                  f"and we say so.")
    notes(s, window(6), SCRIPTS[7], "If asked about Sharpe 14.5: backup Q7. If asked about costs: backup Q8.")


def s08_robust(prs, fwd_text, fwd_src):
    _SLIDE[0] = "8 robustness"
    s = new_slide(prs, dark=False)
    chrome(s, 8, "Robustness · what we tested", False, label="IS = in sample · OOS = held out · net ¢ per share, 95% CI")
    set_title(s, "We tried to break it: only v2 clears zero", False)
    # the forest plot is in the paper only while it carries \label{fig:forest}; otherwise it is cited as a repo figure
    forest = (f"paper Fig. {PR('fig:forest')}" if "fig:forest" in REFS["labels"] else
              rec("results/paper/v2/figA4_forest.png", "results/paper/v2/figA4_forest.png") +
              f" (repo figure; the paper lists the same tests in Table {PR('tab:A-all')})")
    fit_picture(s, ROOT / "results/paper/v2/figA4_forest.png", M - 0.05, 1.6, 5.95, 4.65, name=f"Fig: every test ({forest})",
                align="l")
    text(s, M, 6.38, 5.8, 0.5, P(R(f"Every test on one axis; hollow = a held-out test. Source: {forest}.",
                                   10, GREY_L)),
         name="Fig caption")
    xt = M + 6.1
    rows = [["Test", "IS", "OOS / blind", "Verdict"],
            ["v2, ½ / 1 tick worse entry", f"{N('v2.is.slip05')} / {N('v2.is.slip10')}", f"{N('v2.oos.slip05')} / {N('v2.oos.slip10')}", "≈0 at ½ tick"],
            ["v2, fees ×2 / all costs ×2", f"{N('v2.is.fx2.c')} / {N('v2.is.cx2.c')}", f"{N('v2.oos.fx2.c')} / {N('v2.oos.cx2.c')}", "fail OOS"],
            [f"v2, {N('u2.markets')} unseen markets", N("u2.is.c"), N("u2.oos.c"), "fail (blind)"],
            ["Maker v1, per fill", N("mk.is.c"), N("mk.oos.c"), "fail (blind)"],
            ["CV v3 rule, unseen markets", N("t3.is.c"), N("t3.oos.c"), "fail (blind)"],
            ["CV replay, 9 real books, 1 s", "", N("rp.v1l2.c"), "loses"],
            ["v2 after fixed costs, $/day", N("fin.v2.is.net_central"), N("fin.v2.oos.net_central"), "fail OOS"],
            ["PBO · bootstrap P(SR ≤ 0) · deflated Sharpe OOS", f"{N('rig.pbo.lowloss')} · {N('rig.boot.p')}",
             N("v2.oos.dsr"), "luck not ruled out OOS"]]
    table(s, xt, 1.62, [2.4, 1.15, 1.25, 1.03], [0.36] + [0.38] * (len(rows) - 2) + [0.62], rows,
          f"Robustness (paper Table {PR('tab:A-all')})", size=11, header_size=10)
    # the ONE forward-test slot
    rec(fwd_text, fwd_src)
    box(s, xt, 5.32, CW - 6.1, 0.54, fill=CARD_L, radius=0.08, name="Forward slot card")
    text(s, xt + 0.18, 5.32, CW - 6.1 - 0.36, 0.54, P(R(fwd_text[0].upper() + fwd_text[1:], 11.5, INK, bold=True), line=1.05),
         anchor="m", name="Forward test slot")
    text(s, xt, 5.94, CW - 6.1, 0.98, [
        P(R(f"{N('var.total')} variants in all; {VV('n_trials')} strategy variants (the video's count); {N('rig.N3386')} in "
            f"the deflated Sharpe. Held-out data read {N('peeks.n')} times, every look logged; rules changed after a look: "
            f"{N('peeks.rule_changes')} for v2.", 10.5, INK), after=3, line=1.05),
        P(R(f"Also tested: chasing the move ({N('h1.oos.c')}¢ OOS), table tennis (no wallet qualifies; {N('tt.matches')} "
            f"matches, {N('tt.spread')}¢ median spread). The live paper session was stopped and is not used.", 10, GREY_L),
          line=1.05)], name="Rigor tally")
    SCRIPTS[8] = (f"We tried to break it: {N('var.total')} variants, every held-out look logged. Every blind test of a "
                  f"tradable book failed: unseen markets, the maker book, the v3 rule, a replay on nine real books. "
                  f"Doubled fees erase v2 held out; luck is not ruled out. " +
                  ("The forward test ran once: see the box." if forward_ran() else
                   "Our pre-registered forward test was not run in time, and the box says so."))
    notes(s, window(7), SCRIPTS[8], f"The forward-test box follows {fwd_src} at build time. The video's 'blind tests: "
          f"{VV('blind_pass')} pass · {VV('blind_fail')} fail' also counts two blind tests that are not tradable books "
          "(table-tennis H3 precision; v2's unseen markets in sample): every blind test of a tradable book failed.")


def s09_risk(prs):
    _SLIDE[0] = "9 risk capacity financials"
    s = new_slide(prs, dark=False)
    chrome(s, 9, "Risk · capacity · financials", False, label="feed-licence prices are quotes (assumptions); paper trading only")
    set_title(s, "Small, capped and honest about costs", False)
    cw = (CW - 0.5) / 3
    cols = [
        ("Risk limits, in code", [
            (f"{N('risk.order_usd')}", "per order; " + f"{N('risk.netcap')} shares net per match, zone {N('risk.zone')}"),
            (f"{N('risk.maxloss')}", "most one match can lose, plus fees"),
            (f"{N('risk.daily_stop')}", f"daily stop; kill on stale feed > {N('risk.feed_stale')} s, stale vision > "
                                        f"{N('risk.vision_stale')} s, latency above its rolling p95"),
            (f"{N('pol.dd_stop')}", f"drawdown stop; halve size if the 30-day edge < {N('pol.trail_half')}¢, stop at ≤ 0"),
        ]),
        ("Capital capacity", [
            (f"{N('v2.oos.cap')}", "v2: held-out edge holds only at 1× size; 5× loses"),
            (f"{N('v2.is.notional_day')}", f"traded a day by v2: {N('v2.is.share_vol')} of match volume"),
            (f"{N('capcv.half.oos')}", f"CV, post hoc: Sharpe halves here (held out; {N('capcv.half.is')} in sample)"),
            ("none", f"CV, pre-registered: Sharpe {N('capcv.pre.sr0.is')} · {N('capcv.pre.sr0.oos')} at its smallest size"),
        ]),
        ("Financials", [
            (f"{N('fin.fixed.low')}–{N('fin.fixed.high')}", f"fixed costs a day (data licence + VPS; central "
                                                            f"{N('fin.fixed.central')})"),
            (f"{N('fin.v2.oos.net_central')}", f"v2 a day held out after central costs ({N('fin.v2.is.net_central')} in sample)"),
            (f"{N('cv.cal.oos.maxlic')}", f"most the CV book could pay for data a month at 1 s, post hoc "
                                         f"({N('cv.pre.oos.maxlic')} pre-registered)"),
            (f"{N('fin.feed.low')}–{N('fin.feed.high')}", "feed-licence quotes a month"),
        ]),
    ]
    for i, (head, items) in enumerate(cols):
        x = M + i * (cw + 0.25)
        text(s, x, 1.62, cw, 0.32, P(R(head, 13, ORANGE, bold=True)), name=f"Col {i}: head")
        hline(s, x, 1.98, cw, RULE_L, 0.75, name=f"Col {i}: rule")
        y = 2.08
        for j, (big, cap) in enumerate(items):
            text(s, x, y, cw, 0.48, P(R(big, 24, INK, bold=True)), anchor="m", name=f"Col {i} item {j}: value")
            text(s, x, y + 0.48, cw, 0.5, P(R(cap, 11, GREY_L), line=1.05), name=f"Col {i} item {j}: caption")
            y += 1.0
    box(s, M, 6.22, CW, 0.62, fill=BLACK, radius=0.08, name="Verdict card")
    text(s, M + 0.3, 6.22, CW - 0.6, 0.62, P(R(f"At today's {N('fee.rate')} fee COURTSIDE prices speed; it is not yet a business. ", 14, WHITE,
                                               bold=True),
                                             R(f"Our size: {N('capcv.share_inplay')} of in-play volume but {N('capcv.share_fast')} "
                                               "of the fast tier's first 3 s.", 12, GREY_D)), anchor="m", name="Verdict")
    SCRIPTS[9] = (f"Risk and capacity. Limits are in code: {N('risk.netcap')} shares net per match, at most {N('risk.maxloss')} "
                  f"lost on any one match, a {N('risk.daily_stop')} daily stop, kill switches on stale feeds. Capacity is "
                  f"small: v2's held-out edge holds only at about {N('v2.oos.cap')} of capital. Post hoc, the CV book's Sharpe "
                  f"halves by {N('capcv.half.oos')}; pre-registered, it has no capacity. After data costs of "
                  f"{N('fin.fixed.low')} to {N('fin.fixed.high')} a day, v2 makes {N('fin.v2.oos.net_central')} a day held "
                  f"out. Today this prices speed; it isn't yet a business.")
    notes(s, window(8), SCRIPTS[9], "Capacity detail and the capacity figure: backup Q2. Data-cost arithmetic: backup Q9.")


def s10_next(prs):
    _SLIDE[0] = "10 path to deployment"
    s = new_slide(prs, dark=True)
    chrome(s, 10, "What it takes to deploy", True, label="no licensed feed, match video or court access today")
    set_title(s, "One licensed-feed session decides it", True)
    steps = [
        ("License a low-latency feed", f"vendors state {N('lat.video_band')} s for betting video, sold to licensed "
                                       "sportsbooks; Polymarket itself buys official data"),
        ("Measure the umpire's stamp lag", "one session with test orders: the number that sets the sign; the break-even "
                                           "moves one for one with it"),
        ("Trade from London", f"{N('lat.net_ldn')} ms to the venue, vs {N('lat.net_fl')} ms from Florida"),
        ("Permitted venue, legal review", "until then: paper only, no funded account, no courtsiding"),
    ]
    y = 1.75
    for i, (h, b) in enumerate(steps):
        text(s, M, y, 0.6, 0.5, P(R(f"{i + 1}", 26, ORANGE, bold=True)), anchor="t", name=f"Step {i + 1}: number")
        text(s, M + 0.6, y + 0.02, 6.6, 0.4, P(R(h, 19, WHITE, bold=True)), name=f"Step {i + 1}: head")
        text(s, M + 0.6, y + 0.43, 6.6, 0.55, P(R(b, 12.5, GREY_D), line=1.1), name=f"Step {i + 1}: body")
        y += 1.18
    xr, wr = M + 7.3, CW - 7.3
    box(s, xr, 1.75, wr, 3.75, fill=CARD_D, line=RULE_D, radius=0.12, name="Repo card")
    text(s, xr + 0.3, 1.9, wr - 0.6, 3.55, [
        P(R("Reproduce it", 13, ORANGE, bold=True), after=6),
        P(R(REPO.split("/")[0] + "/" + REPO.split("/")[1] + "/", 10, WHITE, font=MONO)),
        P(R(REPO.split("/")[2], 8.5, WHITE, font=MONO), after=10),
        P(R("bash run.sh setup && bash run.sh replay", 13, WHITE, font=MONO, bold=True), after=4),
        P(R("recorded live books through the paper trader, ~15 s, no network", 11, GREY_D), after=10),
        P(R("bash run.sh data && bash run.sh reproduce", 12, WHITE, font=MONO), after=4),
        P(R("every number in the paper, from public Polymarket data", 11, GREY_D), after=10),
        P(R("bash run.sh money", 12, WHITE, font=MONO), after=4),
        P(R("the money counter on slide 7", 11, GREY_D)),
    ], name="Repo")
    rec(REPO, "git remote (README.md)")
    text(s, xr, 5.6, wr, 1.2, P(R("Paper trading only. CV strategy simulated at an assumed feed latency (licensed feed not "
                                  f"purchased). Footage: OpenTTGames, CC BY-NC-SA 4.0; {tennis_credit()}. Video voice: AI "
                                  f"({re.search(r'Voice: AI [(]([^)]+)[)]', VID_LABELS.get('end_card', '')).group(1)}).",
                                  10.5, GREY_D), line=1.1), name="Close label")
    SCRIPTS[10] = ("To deploy it, we'd license a low-latency feed and run one session to measure the umpire's lag, the one "
                   "number that sets the sign. Everything here reproduces from the repo with one command. Paper trading "
                   "only. Thank you.")
    notes(s, window(9), SCRIPTS[10], "Then Q&A: backup slides follow (Q1 latency, Q2 capacity first: the organisers' own).")


# ------------------------------------------------------------------------------------------------ backup slides
def backup(prs, q: int, question: str, answer: list[str], evidence: str, fig: str | None = None):
    _SLIDE[0] = f"Q{q}"
    s = new_slide(prs, dark=False)
    chrome(s, 10 + q, f"Backup · Q{q}", False, label="answer, then the number, then the file", backup=True)
    set_title(s, question, False, size=28)
    w = CW if not fig else 6.9
    paras = [P(R(a, 19 if i == 0 else 16, INK if i == 0 else GREY_L, bold=i == 0), after=12, line=1.12)
             for i, a in enumerate(answer)]
    text(s, M, 1.75, w, 4.6, paras, name="Answer")
    if fig:
        fit_picture(s, ROOT / fig, M + 7.2, 1.75, CW - 7.2, 4.4, name=f"Fig: {fig}")
    text(s, M, 6.45, CW, 0.45, P(R("Evidence: " + evidence, 10, GREY_L, font=FONT)), name="Evidence")
    return s


def backups(prs):
    qs = []
    qs.append(("Can you really trade inside 3 s, frame to order?", [
        f"Yes: {N('e2e.total')} ms with a simulated 1 s feed, {N('e2e.margin')} ms under the 3 s bar, every one of "
        f"{N('e2e.n')} traces.",
        f"Our part is {N('e2e.ours')} ms on a laptop (vision {N('cv.eng.p50')} ms p50 per frame on an L4 GPU at "
        f"{N('cv.eng.fps')} fps, {VV('pf_lat')} ms per emitted call as in the video; "
        f"{N('cv.eng.dropped')} of {N('cv.eng.frames')} frames dropped). WebRTC frame to call: {N('cv.webrtc')}. Network: "
        f"{N('lat.net_fl')} ms from Florida, {N('lat.net_ldn')} ms from London; then the venue holds every taker order "
        f"{N('venue.delay')} s.",
        f"Under 3 s is necessary, not sufficient: pre-registered, the call must reach the venue {N('cv.call_before_stamp')} s "
        f"before the umpire's stamp, and every reading loses by a 3 s feed. Orders sent: {N('e2e.sent')} (unsigned, timing "
        "probes; table-tennis calls mapped onto a tennis market for timing only)."],
        "results/e2e/summary.json; results/engine/online_vs_offline.json; results/webrtc/latency.json; "
        f"paper Fig. {PR('fig:f2t')}", None))
    qs.append(("How much capital can this run?", [
        f"Not much. v2's held-out edge holds only at 1× size ({N('cap.1x.oos.capital')}, {N('cap.1x.oos.c')}¢ "
        f"{N('cap.1x.oos.ci')}); 2× spans zero ({N('cap.2x.oos.c')}¢) and 5× loses ({N('cap.5x.oos.usd')} a day).",
        f"CV book, pre-registered: Sharpe {N('capcv.pre.sr0.is')} · {N('capcv.pre.sr0.oos')} at its smallest size, so no "
        f"capacity. Post hoc: Sharpe halves at {N('capcv.half.oos')} held out ({N('capcv.half.is')} in sample); $/day peaks "
        f"at {N('capcv.pmax.oos.day')} on {N('capcv.pmax.oos')} (Sharpe {N('capcv.pmax.oos.sr')}).",
        f"The binding limit is the stale depth on each point: we would be {N('capcv.share_inplay')} of in-play volume but "
        f"{N('capcv.share_fast')} of the fast tier's first 3 s."],
        "results/capacity/capacity.json; results/alpha/alpha.json::H_capacity; "
        f"paper Section {PR('sec:liq')}, Fig. {PR('fig:capacity')}",
        "results/paper/v2/figA8_capacity.png"))
    qs.append(("Where does a sub-second tennis feed come from?", [
        "Today, nowhere we can reach, and we say so. We bought no feed and have no match video.",
        f"The fastest public stream we measured is {N('lat.webrtc_public')} s behind; public score feeds {N('lat.espn')}–"
        f"{N('lat.wta')} s. Licensed betting video is vendor-stated at {N('lat.video_band')} s (none for tennis) and is sold "
        "to licensed sportsbooks. A spectator camera breaches ITF rules and ticket terms.",
        "A venue-side route exists: Polymarket already buys official data. The deck's numbers at 0.5, 1 and 3 s are "
        "scenarios, not a feed we have."],
        "results/home_stream/sub_second_routes.json; results/tier0/latency_sweep.json::sources; "
        f"paper Fig. {PR('fig:race')}a, Appendix {APPX('Records')}", None))
    qs.append(("Trading only points that later moved ≥4¢: look-ahead?", [
        "Yes for the sweep's trade set, and we label it: selected on outcomes, not ex ante. It prices speed given a point "
        "worth trading; it is not yet a deployable rule.",
        f"The ex-ante test is the replay on 9 real books recorded 2026-10-03, calling every point: {N('rp.v1l2.c')}¢ "
        f"{N('rp.v1l2.ci')} at a 1 s feed; {N('rp.cells_neg')} of {N('rp.cells')} settings lose. An ex-ante Markov swing "
        f"filter (exploratory): {N('rp.sel.t4.c')}¢ {N('rp.sel.t4.ci')}.",
        f"Widening the sweep to all {N('cv.pool.all')} points: {N('cv.pool482.oos')}¢ held out at a zero-delay feed."],
        "results/replay/replay.json; research/v2/tier0/RESULTS.md §8; "
        f"paper Table {PR('tab:A-all')}, Fig. {PR('fig:replay')}", None))
    qs.append(("Isn't the 3.14 s stamp lag tuning on the held-out window?".replace("3.14", N("cv.cal.lag")), [
        f"The pre-registered reading (L = {N('cv.pre.lag')} s) is our result: break-even at a "
        f"{N('cv.pre.be.range')} s feed, {N('cv.pre.oos.usd')} a day held out, {N('cv.pre.oos.c')}¢ {N('cv.pre.oos.c_ci')}.",
        f"{N('cv.cal.lag')} s is a one-day inference from fast-tier prints (95% CI {N('cv.cal.lag_ci')} s; it assumes "
        f"courtside humans). Showing it as a headline was a post hoc choice and is counted as a trial. At the CI's low end "
        f"the 1 s cell makes only {N('cv.at_lo.oos.usd')} a day held out.",
        f"Read per point, the same inference loses {N('cv.stc.oos.usd')} a day (break-even {N('cv.stc.be.oos')}–"
        f"{N('cv.stc.be.is')} s). The tier-0 PREREG was written {N('t0.prereg.written')} UTC, before the first P&L."],
        "research/v2/tier0/PREREG.md; DEVIATIONS.md V3; results/redteam/stamp_lag.json; results/oos_peeks.log", None))
    qs.append(("The call model's offline score used look-ahead. Causally?", [
        f"The live engine is causal: on held-out games it called {N('cv.eng.tp')} of {N('cv.eng.nmiss')} misses early, none "
        f"wrong (95% lower bound {N('cv.eng.wil_lo')}), median lead {N('cv.eng.lead')} ms.",
        f"The offline evaluation's {N('cv.tt.tp50')} of {N('cv.tt.called50')} correct calls at 50 ms used a look-ahead "
        "feature (offline only); we lead with the live numbers.",
        f"It does not drive the 1 s result: with the live engine's own calls the 1 s cells are {N('cv.eng.pre.is.usd')} · "
        f"{N('cv.eng.pre.oos.usd')} pre-registered and {N('cv.eng.cal.is.usd')} · {N('cv.eng.cal.oos.usd')} post hoc "
        f"(IS · OOS a day). With no early calls at all: {N('cv.pess.is.usd')} · {N('cv.pess.oos.usd')}. Phantom calls "
        f"between rallies (~{N('cv.phantom.hr')} an hour) are a known gap: a rally-state gate is coded, not yet evaluated."],
        "results/engine/online_vs_offline.json; results/redteam/causal_cv.json; engine/README.md (Known gaps)", None))
    qs.append(("Sharpe 14.5 on daily data? Assume a bug.".replace("14.5", N("v2.is.sr")), [
        f"We assumed one and found one: the onset look-ahead fix cut in-sample Sharpe from {N('v2.onset.is.sr')} to "
        f"{N('v2.is.sr')}.",
        f"What remains is about {N('v2.trades_per_day')} small, near-independent bets a day with a 100-share net cap per "
        f"match: {N('cap.1x.is.usd')} a day on {N('v2.is.cap')} of capital. It falls fast: {N('v2.oos.slip05')}¢ held out "
        f"at ½ tick worse entry, {N('v2.oos.fx2.c')}¢ with fees doubled.",
        f"Deflated at {N('rig.N3386')} trials: {N('v2.is.dsr')} in sample, {N('v2.oos.dsr')} held out. Forty days cannot "
        "rule out luck."],
        "results/v2/note_metrics.json; results/rigor/rigor.json; results/v2/cost_stress.json; "
        f"paper Table {PR('tab:head')}", None))
    qs.append(("What happens when costs double?", [
        f"In sample it survives; held out it does not. Fees ×2: {N('v2.is.fx2.c')}¢ ({N('v2.is.fx2.mpos')} months) in "
        f"sample, {N('v2.oos.fx2.c')}¢ {N('v2.oos.fx2.ci')} ({N('v2.oos.fx2.mpos')} months) held out.",
        f"All costs ×2: {N('v2.is.cx2.c')}¢ in sample, {N('v2.oos.cx2.c')}¢ held out. Fees are each match's own rate × "
        f"q(1−q): {N('v2.is.fee_bps')} bps of notional in sample, {N('v2.oos.fee_bps')} held out.",
        "Venue fee and delay rules are therefore the first risk, and a fee change is a kill switch."],
        f"results/v2/cost_stress.json; results/v2/note_metrics.json; paper Table {PR('tab:head')}", None))
    qs.append(("After paying for data, what do you make?", [
        f"Today, less than the data costs. The cheapest data stack is {N('fin.fixed.low')} a day, central "
        f"{N('fin.fixed.central')}, high {N('fin.fixed.high')} (licence quotes {N('fin.feed.low')}–{N('fin.feed.high')} a "
        "month; assumptions).",
        f"After central costs: v2 {N('fin.v2.is.net_central')} in sample, {N('fin.v2.oos.net_central')} held out a day; the "
        f"CV book at 1 s {N('cv.cal.oos.net_central')} post hoc and {N('cv.pre.oos.net_central')} pre-registered (held out).",
        f"At 1 s the CV book could pay at most {N('cv.cal.oos.maxlic')} a month for data post hoc and "
        f"{N('cv.pre.oos.maxlic')} pre-registered. COURTSIDE prices speed; it is not yet a business."],
        f"results/financials/financials.json; paper Section {PR('sec:liq')}, Fig. {PR('fig:cap')}, Appendix {APPX('Records')}", None))
    qs.append(("What kills it?", [
        "In order of size: (1) the unmeasured stamp lag, which flips the CV sign; (2) our queue position against the fast "
        "tier; (3) fees: doubling them erases v2 held out; (4) a longer venue hold.",
        f"(5) The edge is shrinking: {N('ft.slope')}¢ a month (t = {N('ft.slope.t')}). (6) Concentration: the top 5 copied "
        f"wallets carry {N('conc.top5.is')} of v2's in-sample P&L and {N('conc.top5.oos')} held out.",
        f"Kill switches in code: {N('risk.daily_stop')} daily stop, stale feed > {N('risk.feed_stale')} s, stale vision > "
        f"{N('risk.vision_stale')} s, latency above its rolling p95; stop at a {N('pol.dd_stop')} drawdown."],
        f"docs/RISK.md; engine/risk/; results/alpha/alpha.json::headline; paper Section {PR('sec:risk')}", None))
    qs.append(("Is this allowed? Isn't it courtsiding?", [
        f"The track allows any liquid, publicly traded market. Polymarket has a public book and public data with no keys; "
        f"{N('univ.volume')} traded across our {N('univ.matches')} matches.",
        "We placed no orders and connected no funded account. US persons are close-only on the international venue, so a "
        "deployment needs a permitted venue, licensed data and legal review.",
        "We do not courtside: the design is a licensed feed. A spectator camera for betting breaks ITF rules and ticket "
        "terms, and we cite them."],
        "research/compliance/REQUIREMENTS.md §G; results/home_stream/sub_second_routes.json::compliance_flags", None))
    qs.append(("Can we run your code and get your numbers?", [
        "Yes. bash run.sh setup, then bash run.sh replay (~15 s, no network) runs recorded live books through the paper "
        "trader; bash run.sh data && bash run.sh reproduce regenerates every number and figure in the paper.",
        "Every number in the paper, the video and this deck is read from a results file through a manifest "
        "(docs/deck/courtside_manifest.json lists this deck's).",
        "One gap: the frozen vision model (12 MB) is not in git, so CV calls cannot be regenerated from a clone; tracking "
        "still runs."],
        "README.md; research/compliance/CLEAN_CLONE.md; docs/deck/courtside_manifest.json", None))
    for i, (q, a, ev, fig) in enumerate(qs, 1):
        backup(prs, i, q, a, ev, fig)
    return len(qs)


# ------------------------------------------------------------------------------------------------ checks
FORBIDDEN = [r"calibrated\s+from the data", r"goes\s+live", r"stricter\s+readings", r"\bconservative\b", r"\btonight\b",
             r"\btomorrow\b", r"\bpending\b", r"\bwarming up\b", r"\bis running\b", r"\bstill running\b", r"\bour feed\b",
             r"\bwe licensed\b", r"\bwe bought (a|the) feed\b", r"live ATP", r"live WTA data", r"Sharpe 12\b"]
OFFLINE_ONLY = [r"11/11", r"11 of 11", r"408\s*ms"]   # offline evaluation numbers: only next to 'offline'


def slide_texts(prs):
    out = []
    for k, s in enumerate(prs.slides, 1):
        vis = [sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        for sh in s.shapes:
            if sh.has_table:
                vis += [c.text_frame.text for row in sh.table.rows for c in row.cells if c.text_frame.text.strip()]
        nt = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
        out.append((k, vis, nt))
    return out


def run_checks(prs, n_main, mc, fwd_text):
    fails, warns = [], []
    T = slide_texts(prs)
    alltext = [(k, t) for k, vis, nt in T for t in vis + ([nt] if nt else [])]
    # 1 forbidden phrases
    for k, t in alltext:
        for pat in FORBIDDEN:
            if re.search(pat, t, re.I):
                fails.append(f"slide {k}: forbidden phrase /{pat}/ in: {t[:90]}")
        for line in t.splitlines():
            if any(re.search(p, line) for p in OFFLINE_ONLY) and not re.search(r"offline|look-?ahead", line, re.I):
                fails.append(f"slide {k}: offline-only number without 'offline': {line[:90]}")
            if re.search(r"real money", line, re.I) and not re.search(r"\bno\b|none|not", line, re.I):
                fails.append(f"slide {k}: 'real money' without a negation: {line[:90]}")
            if re.search(r"live (paper )?session", line, re.I) and not re.search(r"stopped|not used", line, re.I):
                fails.append(f"slide {k}: live-session mention without 'stopped': {line[:90]}")
    # 2 exactly one forward-test slot (visible text)
    fw = [(k, t) for k, vis, _ in T for t in vis if re.search(r"forward test", t, re.I)]
    if len(fw) != 1 or fw[0][1].lower() != fwd_text.lower():
        fails.append(f"forward-test slot: expected exactly one, found {len(fw)}: {fw}")
    # 3 required labels per slide
    need = {1: [r"Ojasva Mishra", r"Yoan Exposito", r"Rafael Penhas", r"Ian Hoang", r"Paper trading only"],
            4: [r"simulated physics", r"CC BY-NC-SA", r"live causal engine"],
            5: [r"simulated", r"never signed or sent", r"3 s"],
            6: [r"assumed feed latency", r"licensed feed not purchased", r"Pre-registered", r"Post hoc",
                r"not ex ante", r"per point"],
            7: [r"fast tier's own fills", r"burned, non-blind", r"deflated", r"SCORECARD"],
            8: [r"blind", r"variants"],
            9: [r"capacity|Capacity", r"daily stop", r"not yet a business"],
            10: [r"bash run\.sh", r"licensed feed not purchased", r"Paper trading only"]}
    for k, pats in need.items():
        blob = " ".join(T[k - 1][1])
        for p in pats:
            if not re.search(p, blob):
                fails.append(f"slide {k}: missing required label /{p}/")
    # 4 pre-registered column before post hoc (slide 6 table)
    tb = next(sh for sh in prs.slides[5].shapes if sh.has_table).table
    h1, h2 = tb.cell(0, 1).text_frame.text, tb.cell(0, 2).text_frame.text
    if not (h1.startswith("Pre-registered") and h2.startswith("Post hoc")):
        fails.append("slide 6: the pre-registered column must come first")
    # 5 timing + notes
    if sum(DUR_S) != TALK_S or len(DUR_S) != n_main:
        fails.append(f"timing: {sum(DUR_S)} s over {len(DUR_S)} slides, expected {TALK_S} s over {n_main}")
    for i in range(n_main):
        nt = T[i][2]
        if not nt.startswith("[" + window(i)):
            fails.append(f"slide {i + 1}: notes must start with its time window")
        words = len(SCRIPTS[i + 1].split())
        rate = words / DUR_S[i]
        if rate > 2.9:
            warns.append(f"slide {i + 1}: script {words} words in {DUR_S[i]} s = {rate:.2f} words/s (fast)")
    # 6 money counter agrees with the paper
    for k in ("is", "oos"):
        r = mc["rows"][k]
        pnl = float(r["pnl"].replace("$", "").replace(",", "").replace("−", "-"))
        if round(pnl) != round(float(NR(f"v2.{k}.pnl"))):
            fails.append(f"money counter {k} P&L {r['pnl']} != paper {N(f'v2.{k}.pnl')}")
        if int(r["fills"].replace(",", "")) != int(NR(f"v2.{k}.trades")):
            fails.append(f"money counter {k} fills {r['fills']} != paper trades {N(f'v2.{k}.trades')}")
    # 7 paper vs video agree where both show a number
    pairs = [("cv.cal.is.usd", "lc_is_day"), ("cv.cal.oos.usd", "lc_oos_day"), ("cv.pre.is.usd", "t_is_day"),
             ("cv.pre.oos.usd", "t_oos_day"), ("e2e.ours", "pp_ours"), ("e2e.total", "pp_total"), ("cv.eng.tp", "pf_recall_tp"),
             ("cv.eng.nmiss", "pf_n_miss_flights"), ("cv.cal.lag", "lc_lag")]
    for pk, vk in pairs:
        a = re.sub(r"[^\d.]", "", str(NUM[pk]["value"]))
        b = re.sub(r"[^\d.]", "", str(VID[vk]["shown"]))
        if a.rstrip("0").rstrip(".") != b.rstrip("0").rstrip("."):
            warns.append(f"paper {pk} = {NUM[pk]['value']} vs video {vk} = {VID[vk]['shown']} (check which is final)")
    # 8 the scenario table agrees with the headline keys
    for a, b in (("sc.pre.oos.v1.usd", "cv.pre.oos.usd"), ("sc.cal.oos.v1.usd", "cv.cal.oos.usd"),
                 ("sc.pre.is.v1.sr", "cv.pre.is.sr"), ("sc.cal.oos.v1.sr", "cv.cal.oos.sr")):
        if NUM[a]["value"] != NUM[b]["value"]:
            fails.append(f"numbers.json disagrees with itself: {a} = {NUM[a]['value']} vs {b} = {NUM[b]['value']}")
    # 9 forward.json present but the paper's numbers.json still says 'runs': the paper needs a rebuild
    if (ROOT / F_FWD).exists() and str(NUM.get("fwd.cell", {}).get("value", "")).startswith("runs"):
        warns.append("results/v2/forward.json exists but numbers.json still has the 'runs …' slot: rebuild the paper too")
    pc = str(NUM.get("fwd.cell", {}).get("value", ""))
    if not (ROOT / F_FWD).exists() and pc and pc.lower() not in fwd_text.lower():
        warns.append(f"forward slot says '{fwd_text}' but the paper's numbers.json fwd.cell is '{pc}': the paper must be "
                     "rebuilt after the last HYPOTHESIS_V2.md amendment (research/compliance/FINAL_ISSUES.md)")
    return fails, warns


# ------------------------------------------------------------------------------------------------ main
def main() -> int:
    mc = money_counter()
    fwd_text, fwd_src = forward_slot()
    prs = Presentation()
    setup_template(prs)
    s01_title(prs)
    s02_strategy(prs)
    s03_edge(prs)
    s04_models(prs)
    s05_pipeline(prs)
    s06_speed(prs)
    s07_backtest(prs, mc)
    s08_robust(prs, fwd_text, fwd_src)
    s09_risk(prs)
    s10_next(prs)
    n_main = len(prs.slides)
    n_q = backups(prs)
    prs.core_properties.title = "COURTSIDE"
    prs.core_properties.author = ", ".join(team())
    prs.core_properties.subject = "Gator Quant Hacks 2026 · Systematic Trading · investment-committee pitch"
    fails, warns = run_checks(prs, n_main, mc, fwd_text)
    prs.save(OUT)
    slides = []
    for k, s in enumerate(prs.slides, 1):
        title = s.shapes.title.text_frame.text if s.shapes.title is not None else ""
        slides.append({"n": k, "kind": "main" if k <= n_main else "backup", "title": title,
                       "seconds": DUR_S[k - 1] if k <= n_main else None,
                       "window": window(k - 1) if k <= n_main else None})
    OUT_MANIFEST.write_text(json.dumps({
        "deck": str(OUT.relative_to(ROOT)), "builder": "docs/deck/build_deck.py",
        "numbers_file": F_NUM, "numbers_generated_utc": _json(F_NUM).get("generated_utc"),
        "video": F_VIDEO, "talk_seconds": TALK_S, "slides": slides,
        "forward_slot": {"text": fwd_text, "source": fwd_src},
        "money_counter": {"fresh_run": mc["fresh"], "capture": mc["file"], "scorecard": [mc["head"]] +
                          [mc["rows"][k]["line"] for k in ("is", "oos")]},
        "checks": {"fail": fails, "warn": warns},
        "values": MANIFEST}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.1f} MB): {n_main} main + {n_q} backup slides; "
          f"{len(MANIFEST)} values in {OUT_MANIFEST.relative_to(ROOT)}")
    print(f"forward slot: {fwd_text}")
    for i in range(n_main):
        print(f"  {i + 1:2d}  [{window(i)}]  {slides[i]['title']}")
    for w in warns:
        print("WARNING:", w)
    for f in fails:
        print("FAIL:", f)
    print("checks:", "FAIL" if fails else "PASS", f"({len(fails)} fail, {len(warns)} warn)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
