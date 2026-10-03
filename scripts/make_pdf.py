"""Fallback only: docs/NOTE.md -> docs/NOTE.html (and, with --pdf, docs/NOTE_fallback.pdf via headless Chrome).

The paper itself is docs/NOTE.pdf, built from LaTeX by `python scripts/build_paper.py` (tectonic). This script
exists for machines without tectonic: it renders the readable companion docs/NOTE.md (which build_paper.py writes
from the same results/paper/numbers.json) as a print-styled HTML page. It never overwrites docs/NOTE.pdf.

Every text style is >= 11 pt with 1 in margins on Letter, as the track requires.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium",
              "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"]
FONTS = (ROOT / "docs/paper/fonts").as_uri()
CSS = f"""
@font-face {{ font-family: 'Source Sans 3'; src: url('{FONTS}/SourceSans3-Regular.ttf'); }}
@font-face {{ font-family: 'Source Sans 3'; font-weight: 600; src: url('{FONTS}/SourceSans3-Semibold.ttf'); }}
@font-face {{ font-family: 'Source Sans 3'; font-style: italic; src: url('{FONTS}/SourceSans3-It.ttf'); }}
@font-face {{ font-family: 'Oswald'; font-weight: 300; src: url('{FONTS}/Oswald-Light.ttf'); }}
@page {{ size: Letter; margin: 1in; }}
body {{ font-family: 'Source Sans 3', sans-serif; font-size: 11pt; line-height: 1.3; color: #111;
       text-align: justify; max-width: 6.5in; margin: 0 auto; }}
h1 {{ font-family: 'Oswald', sans-serif; font-weight: 300; font-size: 22pt; text-align: center; margin: 0 0 6pt; }}
h2 {{ font-weight: 400; font-size: 14pt; margin: 10pt 0 3pt; border-bottom: 2px solid #F26B21; }}
table {{ border-collapse: collapse; width: 100%; font-size: 11pt; margin: 4pt 0; }}
th, td {{ padding: 1.5pt 4pt; text-align: right; vertical-align: top; }}
th:first-child, td:first-child {{ text-align: left; }}
thead th {{ border-top: 1.2px solid #000; border-bottom: 0.6px solid #000; font-weight: 600; }}
tbody tr:last-child td {{ border-bottom: 1.2px solid #000; }}
code {{ font-family: inherit; }}
a {{ color: #1F3A5F; text-decoration: none; }}
"""


def chrome() -> str | None:
    for c in CANDIDATES:
        p = c if Path(c).exists() else shutil.which(c)
        if p:
            return p
    return None


def write_html(src: Path = ROOT / "docs/NOTE.md", out: Path = ROOT / "docs/NOTE.html") -> Path:
    html = markdown.markdown(src.read_text(), extensions=["tables"])
    out.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>COURTSIDE note</title>"
                   f"<style>{CSS}</style></head><body>{html}</body></html>", encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true", help="also print docs/NOTE_fallback.pdf with headless Chrome")
    a = ap.parse_args()
    html = write_html()
    print("wrote", html.relative_to(ROOT))
    if a.pdf:
        exe = chrome()
        if exe is None:
            print("make_pdf: no Chrome/Chromium found; only docs/NOTE.html was written")
            sys.exit(0)
        pdf = (ROOT / "docs/NOTE_fallback.pdf").resolve()
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        html.resolve().as_uri()], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("wrote", pdf.relative_to(ROOT))
