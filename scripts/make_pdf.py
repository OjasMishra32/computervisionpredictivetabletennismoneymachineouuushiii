"""docs/NOTE.md -> docs/NOTE.pdf via headless Chrome."""
import subprocess
from pathlib import Path

import markdown

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CSS = """
@page { size: Letter; margin: 0.6in 0.65in; }
body { font-family: 'Charter', 'Georgia', serif; font-size: 10pt; line-height: 1.38; color: #0b0b0b; }
h1 { font-family: -apple-system, 'Helvetica Neue', sans-serif; font-size: 17pt; margin: 0 0 4pt; }
h2 { font-family: -apple-system, 'Helvetica Neue', sans-serif; font-size: 11.5pt; margin: 12pt 0 4pt;
     border-bottom: 1px solid #e4e3df; padding-bottom: 2pt; }
p, li { margin: 3pt 0; }
ul { padding-left: 16pt; margin: 3pt 0; }
code { font-family: 'SF Mono', Menlo, monospace; font-size: 8.5pt; background: #f3f2ee; padding: 0 2pt; border-radius: 2px; }
table { border-collapse: collapse; width: 100%; font-size: 8.3pt; margin: 6pt 0; font-family: -apple-system, 'Helvetica Neue', sans-serif; }
th, td { border-bottom: 1px solid #e4e3df; padding: 3pt 4pt; text-align: left; vertical-align: top; }
th { color: #52514e; font-weight: 600; }
img { width: 100%; margin: 6pt 0 0; }
em { color: #52514e; }
p > em:only-child { font-size: 8.5pt; display: block; margin-bottom: 6pt; }
"""

if __name__ == "__main__":
    src = Path("docs/NOTE.md")
    html = markdown.markdown(src.read_text(), extensions=["tables"])
    out_html = Path("docs/NOTE.html")
    out_html.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>COURTSIDE</title>"
                        f"<style>{CSS}</style></head><body>{html}</body></html>")
    pdf = Path("docs/NOTE.pdf").resolve()
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", out_html.resolve().as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("wrote", pdf)
