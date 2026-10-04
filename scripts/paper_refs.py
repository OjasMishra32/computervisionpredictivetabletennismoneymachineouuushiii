"""The paper's cross-reference numbers, read at build time, for the docs (scripts/build_docs.py) and the deck.

    from scripts.paper_refs import load
    R = load()
    R["labels"]["tab:head"]          -> ["1", "3"]      (number, page) from docs/paper/note.aux
    R["appendix"]["Records"]         -> "D"             from docs/paper/note.tex (\\section*{Appendix D\\quad Records})
    R["calc"]["Taker fee"]           -> "A9"            from docs/paper/note.tex (\\para{A9. Taker fee})

docs/paper/note.aux is a tectonic intermediate and is gitignored, so a clean clone has none. Whenever it exists, the
map is also written to results/paper/labels.json (committed), and a clone without note.aux reads that file. Nothing
here edits the paper.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUX = ROOT / "docs/paper/note.aux"
TEX = ROOT / "docs/paper/note.tex"
CACHE = ROOT / "results/paper/labels.json"


def _from_paper() -> dict:
    aux = AUX.read_text(errors="replace")
    labels = {name: [n, p] for name, n, p in
              re.findall(r"\\newlabel\{([^}@]+)\}\{\{([^}]*)\}\{([^}]*)\}", aux)}
    tex = TEX.read_text(errors="replace") if TEX.exists() else ""
    appendix = {t.strip(): a for a, t in re.findall(r"\\section\*\{Appendix ([A-Z])\\quad ([^}]+)\}", tex)}
    calc = {t.strip(): k for k, t in re.findall(r"\\para\{(A\d+)\.\s+([^}]+)\}", tex)}
    return {"labels": labels, "appendix": appendix, "calc": calc,
            "source": "docs/paper/note.aux (labels) and docs/paper/note.tex (appendix letters, calculation ids)"}


def load(write_cache: bool = False) -> dict:
    """The live map when note.aux exists (optionally refreshing the committed cache), else the committed cache."""
    if AUX.exists():
        d = _from_paper()
        if write_cache:
            old = json.loads(CACHE.read_text()) if CACHE.exists() else None
            if old != d:
                CACHE.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
        d["from"] = "docs/paper/note.aux"
        return d
    if CACHE.exists():
        d = json.loads(CACHE.read_text())
        d["from"] = "results/paper/labels.json (no docs/paper/note.aux: clean clone)"
        return d
    return {"labels": {}, "appendix": {}, "calc": {}, "from": "none"}


def cache_stale() -> bool:
    """True when note.aux exists and results/paper/labels.json does not match it."""
    if not AUX.exists():
        return False
    return not CACHE.exists() or json.loads(CACHE.read_text()) != _from_paper()


def forward_amendment(hyp: str) -> tuple[str, str, str] | None:
    """(amendment id, its UTC stamp, 'not run' | 'reinstated' | ...) of the last HYPOTHESIS_V2.md amendment that
    decided the blind forward test."""
    am = re.findall(r"^## Amendment (A\d+) \(([^)]+)\): forward test ([^\n(]+)", hyp, re.M)
    if not am:
        return None
    a, t, what = am[-1]
    return a, t, what.strip()
