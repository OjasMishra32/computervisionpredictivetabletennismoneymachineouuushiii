"""Build the public docs (README.md, docs/DEVPOST.md, docs/COMPLIANCE.md) from templates and the paper's numbers.

    python scripts/build_docs.py           # render docs/templates/*.md.in -> README.md, docs/DEVPOST.md, docs/COMPLIANCE.md
    python scripts/build_docs.py --check   # exit 1 if a rendered file differs from the one on disk (stale) or a check fails

Nothing is typed by hand: every number is read at build time from results/paper/numbers.json (written by
scripts/build_paper.py, which records the source file and key of each number), every paper location (Table 1, Fig. A4,
page numbers) from docs/paper/note.aux, and the video's own on-screen numbers from results/viz/v60_assets/manifest.json.
So rebuilding after the paper is rebuilt picks up every change. Read-only apart from the three outputs.

The blind forward test has ONE slot ({{fwd}}). It fills from results/v2/forward.json (and the tier-0 v3 forward
secondary, results/tier0_v3/forward/results.json) when those exist, with the same formatting as the paper's Table 3
row; until then it reads "runs 2026-10-04 11:30 UTC (pre-registered)" (HYPOTHESIS_V2.md Amendment A4). The live paper
session was stopped by a team decision (research/v2/maker/DEVIATIONS_LIVE.md L15) and no number from it is shown.

Template syntax: {{key}} = numbers.json value; {{ref:label}} = the paper's number for a LaTeX label (e.g. "A4");
{{page:label}} = its page; {{video:key}} = the final video's on-screen value; {{fwd}} = the forward slot;
{{meta:key}} = build metadata (n_numbers, numbers_utc, label_cv, fwd_label, video_s, main_pages, total_pages, refs_page,
app_page, min_span, margin_violations; from numbers.json, the video manifest, results/paper/checks.json and note.aux).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {
    "docs/templates/README.md.in": "README.md",
    "docs/templates/DEVPOST.md.in": "docs/DEVPOST.md",
    "docs/templates/COMPLIANCE.md.in": "docs/COMPLIANCE.md",
}
NUMBERS = ROOT / "results/paper/numbers.json"
AUX = ROOT / "docs/paper/note.aux"
VIDEO = ROOT / "results/viz/v60_assets/manifest.json"
FWD = ROOT / "results/v2/forward.json"
CHECKS = ROOT / "results/paper/checks.json"
FWD_V3 = ROOT / "results/tier0_v3/forward/results.json"
FWD_LABEL = "Blind forward test (v2; tier-0 v3 secondary)"     # the paper's Table 3 row label
FWD_DEFAULT = "runs 2026-10-04 11:30 UTC (pre-registered)"      # PAPER_REQUIREMENTS addendum 2026-10-04T02:59Z
MINUS = "\u2212"

# honesty / slot checks on the rendered public docs
FORBIDDEN = [r"calibrated from the data", r"goes live", r"stricter readings", r"\bconservative\b"]
STALE_SLOTS = [r"\bpending\b", r"\btonight\b", r"\btomorrow\b", r"\b(still|currently|now) running\b", r"\bruns until\b",
               r"\bsettl(ing|ement) pending\b", r"\bin progress\b"]
OFFLINE_ONLY = [r"11/11", r"11 of 11", r"408\s*ms"]
MONTHS_OK = r"months?|calendar"


def m(s: str) -> str:
    return s.replace("-", MINUS)


def sgn(x: float, nd: int = 2) -> str:
    return m(f"{0.0 if round(x, nd) == 0 else x:+.{nd}f}")


def num(x: float, nd: int = 2) -> str:
    return m(f"{0.0 if round(x, nd) == 0 else x:.{nd}f}")


def ci(v, nd: int = 2) -> str:
    return f"[{num(v[0], nd)}, {num(v[1], nd)}]"


def intc(x) -> str:
    return f"{int(round(x)):,}"


def load_numbers() -> tuple[dict, dict]:
    d = json.loads(NUMBERS.read_text())
    return d["numbers"], d


def load_aux() -> dict:
    """\\newlabel{name}{{number}{page}{title}{anchor}{}} -> {name: (number, page)}."""
    out = {}
    if AUX.exists():
        for name, n, p in re.findall(r"\\newlabel\{([^}]+)\}\{\{([^}]*)\}\{([^}]*)\}", AUX.read_text(errors="replace")):
            out[name] = (n, p)
    return out


def load_video() -> dict:
    return json.loads(VIDEO.read_text()) if VIDEO.exists() else {}


def forward_cell(N: dict) -> tuple[str, str]:
    """(cell text, source). Same formatting as scripts/build_paper.py's fwd.cell, read directly from the result files
    so the docs fill even if they are rebuilt before the paper."""
    if FWD.exists():
        F = json.loads(FWD.read_text())

        def tri(v):
            return f"{sgn(v[0])} {ci(v[1:3])}" if isinstance(v, list) and len(v) >= 3 else str(v)
        parts = []
        if "primary_A_fast_minus_others_c" in F:
            parts.append(f"A {tri(F['primary_A_fast_minus_others_c'])}¢ {F.get('verdict_A_fast_tier', '')}".strip())
        if "primary_m30_per_share_c" in F:
            parts.append(f"B {tri(F['primary_m30_per_share_c'])}¢ {F.get('verdict_B_v2_book', '')}".strip())
        if "v2_trades" in F:
            parts.append(f"n = {intc(F['v2_trades'])}")
        src = "results/v2/forward.json"
        if FWD_V3.exists():
            src += " ; results/tier0_v3/forward/results.json"
            try:
                R3 = json.loads(FWD_V3.read_text())["results"]["frozen_v3"][
                    "primary (lag 2.0 | tournament | trunc 0 | queue 0)"]["full_window"]
                parts.append(f"v3 {sgn(R3['per_share_c'])}¢ [{num(R3['per_share_ci95_c_lo'])}, {num(R3['per_share_ci95_c_hi'])}]")
            except (KeyError, TypeError):
                parts.append("v3: see results/tier0_v3/forward/results.json")
        return (" · ".join(parts) if parts else "see results/v2/forward.json"), src
    cell = N.get("fwd.cell", {}).get("value") or FWD_DEFAULT
    return cell, N.get("fwd.cell", {}).get("source", "HYPOTHESIS_V2.md::Amendment A4")


def render(tpl: str, N: dict, meta: dict, aux: dict, video: dict, fwd: str) -> tuple[str, list[str]]:
    missing: list[str] = []
    vals = video.get("values", {})

    def sub(mo: re.Match) -> str:
        k = mo.group(1).strip()
        if k == "fwd":
            return fwd
        if k.startswith("ref:") or k.startswith("page:"):
            kind, lab = k.split(":", 1)
            if lab not in aux:
                missing.append(k)
                return f"⟨{k}⟩"
            return aux[lab][0 if kind == "ref" else 1]
        if k.startswith("video:"):
            v = vals.get(k[6:], {})
            if v.get("shown") in (None, "") or v.get("pending"):
                missing.append(k)
                return f"⟨{k}⟩"
            return str(v["shown"])
        if k.startswith("meta:"):
            if k[5:] not in meta:
                missing.append(k)
                return f"⟨{k}⟩"
            return str(meta[k[5:]])
        if k not in N:
            missing.append(k)
            return f"⟨{k}⟩"
        return str(N[k]["value"])

    return re.sub(r"\{\{([^{}]+)\}\}", sub, tpl), missing


def checks(name: str, text: str) -> list[str]:
    bad = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("<!--"):
            continue
        for p in FORBIDDEN:
            if re.search(p, line, re.I):
                bad.append(f"{name}:{i}: forbidden phrase /{p}/")
        for p in STALE_SLOTS:
            if re.search(p, line, re.I):
                bad.append(f"{name}:{i}: stale/pending slot /{p}/: {line.strip()[:100]}")
        if (any(re.search(p, line) for p in OFFLINE_ONLY) and not re.search(r"offline|look-?ahead", line, re.I)
                and not re.search(MONTHS_OK, line, re.I)):
            bad.append(f"{name}:{i}: offline CV number without 'offline': {line.strip()[:100]}")
    if name in ("README.md", "docs/DEVPOST.md"):
        n = text.count(FWD_LABEL)
        if n != 1:
            bad.append(f"{name}: the forward-test slot '{FWD_LABEL}' appears {n} times (must be exactly 1)")
        if re.search(r"live paper session(?![^.\n]{0,80}(stopped|not used))", text, re.I):
            bad.append(f"{name}: mentions the live paper session without saying it was stopped and is not used")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if any output is stale or a check fails")
    a = ap.parse_args()
    N, raw = load_numbers()
    aux = load_aux()
    video = load_video()
    fwd, fwd_src = forward_cell(N)
    fin = video.get("final", {})
    chk = json.loads(CHECKS.read_text()) if CHECKS.exists() else {}
    meta = {"n_numbers": f"{len(N):,}", "numbers_utc": raw.get("generated_utc", "?")[:16].replace("T", " ") + " UTC",
            "label_cv": raw.get("label_cv", ""), "fwd_label": FWD_LABEL, "fwd_label_lc": FWD_LABEL[0].lower() + FWD_LABEL[1:]}
    if fin.get("duration_s"):
        meta.update(video_s=f"{fin['duration_s']:.0f}", video_mb=f"{fin.get('size_mb', 0):.1f}")
    if "main_pages" in chk:
        meta.update(main_pages=str(chk["main_pages"]), total_pages=str(chk.get("total_pages", "?")),
                    min_span=f"{chk.get('smallest_span_pt', 0):.1f}", margin_violations=str(len(chk.get("margin_violations", []))))
    if "lastmain" in aux:
        meta["refs_page"] = str(int(aux["lastmain"][1]) + 1)
    if "fig:race" in aux:      # first appendix float (the appendix starts on a new page after the references)
        meta["app_page"] = aux["fig:race"][1]
    problems, stale = [], []
    for src, dst in TEMPLATES.items():
        tpl = (ROOT / src).read_text()
        head = (f"<!-- GENERATED by scripts/build_docs.py from {src} and results/paper/numbers.json "
                f"({meta['numbers_utc']}); edit the template, then run: bash run.sh docs -->\n")
        out, missing = render(tpl, N, meta, aux, video, fwd)
        out = head + out
        problems += [f"{dst}: unresolved {{{{{k}}}}}" for k in missing]
        problems += checks(dst, out)
        p = ROOT / dst
        if a.check:
            if not p.exists() or p.read_text() != out:
                stale.append(dst)
        else:
            p.write_text(out)
            print(f"wrote {dst}")
    print(f"forward slot: {FWD_LABEL}: {fwd}  [{fwd_src}]")
    for x in problems:
        print("CHECK FAIL", x)
    for x in stale:
        print("STALE", x, "(run: bash run.sh docs)")
    return 1 if problems or stale else 0


if __name__ == "__main__":
    sys.exit(main())
