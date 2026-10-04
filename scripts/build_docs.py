"""Build the public docs (README.md, docs/DEVPOST.md, docs/COMPLIANCE.md) from templates and the paper's numbers.

    python scripts/build_docs.py           # render docs/templates/*.md.in -> README.md, docs/DEVPOST.md, docs/COMPLIANCE.md
    python scripts/build_docs.py --check   # exit 1 if a rendered file differs from the one on disk (stale) or a check fails

Nothing is typed by hand: every number is read at build time from results/paper/numbers.json (written by
scripts/build_paper.py, which records the source file and key of each number), every paper location (Table 1, Fig. A3,
Appendix D, Calculation A9, page numbers) from docs/paper/note.aux and docs/paper/note.tex via scripts/paper_refs.py
(note.aux is gitignored, so the map is also kept in results/paper/labels.json for a clean clone), and the video's own
on-screen numbers from results/viz/v60_assets/manifest.json. So rebuilding after the paper is rebuilt picks up every
change. Read-only apart from the three outputs and results/paper/labels.json. If any placeholder does not resolve, it
writes NOTHING and exits 1 (so a clone without the paper's label map can never overwrite the docs with placeholders).

The blind forward test has ONE slot ({{fwd}}). It fills from results/v2/forward.json (and the tier-0 v3 forward
secondary, results/tier0_v3/forward/results.json) when those exist, with the same formatting as the paper's row.
Otherwise it follows the last HYPOTHESIS_V2.md amendment on the forward test: A5 (2026-10-04T03:32Z, final) says it was
not run, so the slot reads "pre-registered but not run within the hackathon window (HYPOTHESIS_V2.md A5)"
(research/compliance/PAPER_REQUIREMENTS.md addendum 2026-10-04T03:32Z). The live paper session was stopped by a team
decision (research/v2/maker/DEVIATIONS_LIVE.md L15) and no number from it is shown.

Template syntax: {{key}} = numbers.json value; {{ref:label}} = the paper's number for a LaTeX label (e.g. "A1");
{{page:label}} = its page; {{app:Title}} = the letter of the paper's appendix with that title (e.g. {{app:Records}});
{{calc:Title}} = the id of a worked calculation (e.g. {{calc:Taker fee}} -> A9); {{video:key}} = the final video's
on-screen value; {{fwd}} = the forward slot; {{meta:key}} = build metadata (n_numbers, numbers_utc, label_cv,
fwd_label, video_s, main_pages, total_pages, refs_page, app_figs, min_span, margin_violations, tennis_credit, voice;
from numbers.json, the video manifest, results/paper/checks.json and the label map).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.paper_refs import cache_stale, forward_amendment, load as load_refs  # noqa: E402
from scripts.reproduction_contract import sha256_file  # noqa: E402

TEMPLATES = {
    "docs/templates/README.md.in": "README.md",
    "docs/templates/DEVPOST.md.in": "docs/DEVPOST.md",
    "docs/templates/COMPLIANCE.md.in": "docs/COMPLIANCE.md",
}
NUMBERS = ROOT / "results/paper/numbers.json"
HYP2 = ROOT / "HYPOTHESIS_V2.md"
TENNIS_LICENSE = ROOT / "results/viz/v60_assets/tennis_real/LICENSE.md"
VIDEO = ROOT / "results/viz/v60_assets/manifest.json"
FWD = ROOT / "results/v2/forward.json"
CHECKS = ROOT / "results/paper/checks.json"
FWD_V3 = ROOT / "results/tier0_v3/forward/results.json"
FWD_LABEL = "Blind forward test"                                # the paper's row label (Table A1, Appendix D)
FWD_RUNS = "runs 2026-10-04 11:30 UTC (pre-registered)"         # while HYPOTHESIS_V2.md A4 stood
FWD_NOT_RUN = "pre-registered but not run within the hackathon window (HYPOTHESIS_V2.md {a})"   # A3 / A5
MINUS = "\u2212"

# honesty / slot checks on the rendered public docs. 'burned' is not a label we print (the registry's labels are, e.g.
# "OOS, non-blind"); a count of log lines is never printed as reads of held-out data
FORBIDDEN = [r"calibrated from the data", r"goes live", r"stricter readings", r"\bconservative\b", r"\bburned\b",
             r"\b\d[\d,]*\s+(logged\s+)?reads\s+of\s+held-out", r"no look-?ahead in the (tradable|executable)",
             r"all-points (version|book)"]
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


def load_aux(write_cache: bool) -> dict:
    """The paper's label map (scripts/paper_refs.py): labels, appendix letters, calculation ids."""
    return load_refs(write_cache=write_cache)


def load_video() -> dict:
    return json.loads(VIDEO.read_text()) if VIDEO.exists() else {}


def forward_cell(N: dict) -> tuple[str, str, str]:
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
        return (" · ".join(parts) if parts else "see results/v2/forward.json"), src, ""
    am = forward_amendment(HYP2.read_text()) if HYP2.exists() else None
    paper = N.get("fwd.cell", {})
    if am is None:
        return paper.get("value") or FWD_RUNS, paper.get("source", "results/paper/numbers.json::fwd.cell"), ""
    a, _, what = am
    if what.startswith("reinstated"):
        cell = FWD_RUNS
    else:                                                   # 'not run' (A3, A5)
        cell = FWD_NOT_RUN.format(a=a)
    src = f"HYPOTHESIS_V2.md::Amendment {a} (forward test {what}); results/v2/forward.json absent"
    note = ""
    if paper and a not in str(paper.get("source", "")):
        note = (f"results/paper/numbers.json::fwd.cell still follows '{paper.get('source')}' ({paper.get('value')!r}); "
                f"the paper must be rebuilt after HYPOTHESIS_V2.md {a}")
    elif paper.get("value"):
        cell = paper["value"]                               # the paper already follows the amendment: use its words
    return cell, src, note


def render(tpl: str, N: dict, meta: dict, aux: dict, video: dict, fwd: str) -> tuple[str, list[str]]:
    missing: list[str] = []
    vals = video.get("values", {})

    def sub(mo: re.Match) -> str:
        k = mo.group(1).strip()
        if k == "fwd":
            return fwd
        if k.startswith("ref:") or k.startswith("page:"):
            kind, lab = k.split(":", 1)
            if lab not in aux["labels"]:
                missing.append(k)
                return f"⟨{k}⟩"
            return aux["labels"][lab][0 if kind == "ref" else 1]
        if k.startswith("app:") or k.startswith("calc:"):
            kind, title = k.split(":", 1)
            tbl = aux["appendix" if kind == "app" else "calc"]
            if title not in tbl:
                missing.append(k)
                return f"⟨{k}⟩"
            return tbl[title]
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
    aux = load_aux(write_cache=not a.check)
    video = load_video()
    fwd, fwd_src, fwd_note = forward_cell(N)
    fin = video.get("final", {})
    chk = json.loads(CHECKS.read_text()) if CHECKS.exists() else {}
    meta = {"n_numbers": f"{len(N):,}", "numbers_utc": raw.get("generated_utc", "?")[:16].replace("T", " ") + " UTC",
            "label_cv": raw.get("label_cv", ""), "fwd_label": FWD_LABEL, "fwd_label_lc": FWD_LABEL[0].lower() + FWD_LABEL[1:]}
    if fin.get("duration_s"):
        meta.update(video_s=f"{fin['duration_s']:.0f}", video_mb=f"{fin.get('size_mb', 0):.1f}")
    if "main_pages" in chk:
        # "Met" only for a build whose checks passed and whose PDF is the one on disk (a failed build also writes
        # checks.json, and the submitted PDF is then the older one)
        pdf = ROOT / "docs/NOTE.pdf"
        built = chk.get("build", {}).get("pdf_sha256")
        current = bool(chk.get("ok")) and built is not None and pdf.exists() and sha256_file(pdf) == built
        meta["pages_status"] = ("Met" if current and int(chk["main_pages"]) <= 5 else
                                f"NOT MET in the current build ({chk['main_pages']} main pages; checks "
                                f"{'passed' if chk.get('ok') else 'failed'}; docs/NOTE.pdf "
                                f"{'matches' if current else 'is not'} the checked build)")
        meta.update(main_pages=str(chk["main_pages"]), total_pages=str(chk.get("total_pages", "?")),
                    min_span=f"{chk.get('smallest_span_pt', 0):.1f}", margin_violations=str(len(chk.get("margin_violations", []))))
    L = aux["labels"]
    if "lastmain" in L:
        meta["refs_page"] = str(int(L["lastmain"][1]) + 1)
    afig = sorted((int(v[0][1:]), v[0]) for k, v in L.items() if k.startswith("fig:") and re.fullmatch(r"A\d+", v[0]))
    if afig:
        meta["app_figs"] = afig[0][1] + ("–" + afig[-1][1] if len(afig) > 1 else "")
    lic = TENNIS_LICENSE.read_text() if TENNIS_LICENSE.exists() else ""
    mo = re.search(r'Tennis footage: "([^"]+)" by ([^,]+), Pexels \(Pexels License\)', lic)
    if mo:
        meta["tennis_credit"] = f"“{mo.group(1)}” by {mo.group(2)}, Pexels (Pexels License)"
    mo = re.search(r"Voice: AI \(([^)]+)\)", video.get("labels", {}).get("end_card", ""))
    if mo:
        meta["voice"] = mo.group(1).strip()
    problems, stale = [], []
    outs = {}
    for src, dst in TEMPLATES.items():
        tpl = (ROOT / src).read_text()
        head = (f"<!-- GENERATED by scripts/build_docs.py from {src} and results/paper/numbers.json "
                f"({meta['numbers_utc']}); edit the template, then run: bash run.sh docs -->\n")
        out, missing = render(tpl, N, meta, aux, video, fwd)
        out = head + out
        problems += [f"{dst}: unresolved {{{{{k}}}}}" for k in missing]
        problems += checks(dst, out)
        outs[dst] = out
    problems = list(dict.fromkeys(problems))
    unresolved = [x for x in problems if "unresolved" in x]
    for dst, out in outs.items():
        p = ROOT / dst
        if a.check:
            if not p.exists() or p.read_text() != out:
                stale.append(dst)
        elif unresolved:
            pass                                            # never write placeholders over the docs
        else:
            p.write_text(out)
            print(f"wrote {dst}")
    if a.check and cache_stale():
        stale.append("results/paper/labels.json")
    if unresolved and not a.check:
        print(f"NOT WRITTEN: {len(unresolved)} placeholder(s) did not resolve (paper labels from {aux['from']}); "
              "the docs on disk are unchanged")
    print(f"forward slot: {FWD_LABEL}: {fwd}  [{fwd_src}]")
    if fwd_note:
        print("NOTE", fwd_note)
    for x in problems:
        print("CHECK FAIL", x)
    for x in stale:
        print("STALE", x, "(run: bash run.sh docs)")
    return 1 if problems or stale else 0


if __name__ == "__main__":
    sys.exit(main())
