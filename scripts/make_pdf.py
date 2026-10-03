"""docs/NOTE.md -> docs/NOTE.pdf via headless Chrome or Chromium.

Track rule: 11 pt or larger and standard margins. Every text style below is >= 11 pt (text inside figure
images excepted) and the page has 1 in margins on Letter. Check after a rebuild:
    .venv/bin/python -c "import pymupdf;d=pymupdf.open('docs/NOTE.pdf');print(len(d), min(s['size'] for p in d for b in p.get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans'] if s['text'].strip()))"
"""
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

CANDIDATES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium",
              "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"]
CSS = """
@page { size: Letter; margin: 1in; }
body { font-family: 'Charter', 'Georgia', serif; font-size: 11.1pt; line-height: 1.15; color: #0b0b0b; }
h1 { font-family: -apple-system, 'Helvetica Neue', sans-serif; font-size: 16pt; margin: 0 0 2pt; }
h2 { font-family: -apple-system, 'Helvetica Neue', sans-serif; font-size: 12pt; margin: 7pt 0 2pt;
     border-bottom: 1px solid #e4e3df; padding-bottom: 1pt; break-after: avoid-page; page-break-after: avoid; }
p, li { margin: 1.5pt 0; }
ul, ol { padding-left: 14pt; margin: 2pt 0; }
blockquote { margin: 3pt 0 3pt 10pt; padding-left: 8pt; border-left: 2px solid #c9c7c0; }
code { font-family: inherit; font-size: 11.1pt; background: #f1f0ec; padding: 0 1pt; border-radius: 2px; }
table { border-collapse: collapse; width: 100%; font-size: 11.1pt; line-height: 1.13; margin: 3pt 0;
        font-family: 'Avenir Next Condensed', 'Arial Narrow', 'Roboto Condensed', sans-serif; }
th, td { border-bottom: 1px solid #e4e3df; padding: 1.5pt 3pt; text-align: left; vertical-align: top; }
th { color: #3d3c39; font-weight: 600; }
img { width: 100%; margin: 3pt 0 0; }
img[alt="fig2"] { width: 62%; display: block; margin: 3pt auto 0; }
em { color: #3d3c39; }
p > em:only-child { font-size: 11.1pt; display: block; margin-bottom: 3pt; }
"""


def chrome() -> str | None:
    for c in CANDIDATES:
        p = c if Path(c).exists() else shutil.which(c)
        if p:
            return p
    return None


if __name__ == "__main__":
    src = Path("docs/NOTE.md")
    html = markdown.markdown(src.read_text(), extensions=["tables"])
    out_html = Path("docs/NOTE.html")
    out_html.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>COURTSIDE</title>"
                        f"<style>{CSS}</style></head><body>{html}</body></html>")
    pdf = Path("docs/NOTE.pdf").resolve()
    exe = chrome()
    if exe is None:  # judges on Linux without Chrome: the committed PDF stands; don't fail reproduce.sh
        print("make_pdf: no Chrome/Chromium found; wrote docs/NOTE.html, kept the committed docs/NOTE.pdf")
        sys.exit(0)
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", out_html.resolve().as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("wrote", pdf)
