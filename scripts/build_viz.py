"""Inject results/viz/viz_data.json into docs/viz/template.html -> docs/viz/courtside.html."""
from pathlib import Path

if __name__ == "__main__":
    tpl = Path("docs/viz/template.html").read_text()
    data = Path("results/viz/viz_data.json").read_text()
    out = Path("docs/viz/courtside.html")
    out.write_text(tpl.replace("/*__DATA__*/null", data))
    print("wrote", out, out.stat().st_size, "bytes")
