"""Static dashboard from Tiger Data: one match's price path with its jumps, the pipeline race, compression.

    python sponsors/tigerdata/dashboard.py   ->  sponsors/tigerdata/out/dashboard.html (self-contained)
"""
from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import psycopg  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ingest import db_url  # noqa: E402

GREY, BLUE, RED = "#8a8a8a", "#2f6fd6", "#c0392b"


def png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#e6e6e6", linewidth=0.8)


def main():
    with psycopg.connect(db_url()) as conn:
        conn.execute("SET search_path = courtside, public")
        asset, title, outcome = conn.execute(
            "SELECT b.asset_id, m.title, m.outcome FROM bars_1s b JOIN markets m USING (asset_id) "
            "WHERE m.market_type = 'moneyline' AND b.mid BETWEEN 0.05 AND 0.95 "
            "GROUP BY 1, 2, 3 ORDER BY max(b.mid) - min(b.mid) DESC, sum(b.updates) DESC LIMIT 1").fetchone()
        path = conn.execute("SELECT bucket, mid, usd FROM bars_1s WHERE asset_id = %s ORDER BY bucket", (asset,)).fetchall()
        jumps = conn.execute("SELECT detected_at, move_cents FROM jumps WHERE asset_id = %s", (asset,)).fetchall()
        n_jumps, n_assets = conn.execute("SELECT count(*), count(DISTINCT asset_id) FROM jumps").fetchone()
        stages = conn.execute(
            "SELECT stage, p50_ms FROM pipeline_latency WHERE stage LIKE '%->%' AND n >= 20 ORDER BY p50_ms DESC").fetchall()
        totals = dict(conn.execute("SELECT stage, p50_ms FROM pipeline_latency WHERE stage LIKE 'total:%'").fetchall())
        comp = conn.execute(
            "SELECT h, sum(before_compression_total_bytes), sum(after_compression_total_bytes) "
            "FROM unnest(ARRAY['book_updates','trades']) h, LATERAL hypertable_compression_stats(('courtside.' || h)::regclass) "
            "GROUP BY h").fetchall()
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM book_updates), (SELECT count(*) FROM trades), (SELECT count(*) FROM cv_calls), "
            "(SELECT count(*) FROM pipeline_stages), (SELECT count(*) FROM markets)").fetchone()

    fig, ax = plt.subplots(figsize=(9, 3.4))
    ax.plot([r[0] for r in path], [float(r[1]) for r in path], color=GREY, linewidth=1.2)
    for t, mv in jumps:
        ax.axvline(t, color=BLUE, linewidth=1, linestyle="--")
        ax.annotate(f"{float(mv):+.1f}c", (t, ax.get_ylim()[1]), color=BLUE, fontsize=8, ha="left", va="top")
    ax.set_title(f"{title}: price of {outcome}, 1 s bars from Tiger Data ({len(jumps)} jumps flagged)", loc="left", fontsize=10)
    ax.set_ylabel("mid price ($ per share)")
    style(ax)
    chart_path = png(fig)

    fig, ax = plt.subplots(figsize=(9, 3.6))
    top = stages[:10]
    ax.barh([s for s, _ in top][::-1], [float(v) for _, v in top][::-1], color=GREY)
    ax.set_xscale("log")
    ax.set_xlabel("median ms (log scale)")
    ax.set_title("Where the time goes: slowest pipeline stages, camera frame to fill (paper)", loc="left", fontsize=10)
    style(ax)
    chart_stages = png(fig)

    comp_rows = "".join(f"<tr><td>{h}</td><td>{b / 1e6:.1f} MB</td><td>{a / 1e6:.2f} MB</td><td>{b / a:.1f}x</td></tr>"
                        for h, b, a in comp)
    tot = "".join(f"<li>{k.replace('total:', '')}: <b>{v:,.0f} ms</b> median</li>" for k, v in totals.items())
    html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>COURTSIDE Tick Store</title><style>
body{{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1d1d1f;background:#fff}}
h1{{font-size:22px;margin-bottom:4px}} .sub{{color:#666;margin-top:0}} img{{max-width:100%}}
table{{border-collapse:collapse}} td,th{{padding:4px 12px;border-bottom:1px solid #eee;text-align:right}} td:first-child,th:first-child{{text-align:left}}
.k{{display:inline-block;margin-right:28px}} .k b{{font-size:20px;display:block}}
</style></head><body>
<h1>COURTSIDE Tick Store on Tiger Data</h1>
<p class="sub">Public Polymarket order-book ticks, our computer-vision calls and pipeline timings in one TimescaleDB. Paper only; read-only data.</p>
<p><span class="k"><b>{counts[0]:,}</b>book updates</span><span class="k"><b>{counts[1]:,}</b>trades</span>
<span class="k"><b>{counts[4]:,}</b>outcome tokens</span><span class="k"><b>{n_jumps}</b>jumps on {n_assets} tokens</span>
<span class="k"><b>{counts[2]:,}</b>CV calls</span><span class="k"><b>{counts[3]:,}</b>stage timings</span></p>
<h2>One match, second by second</h2><img src="data:image/png;base64,{chart_path}" alt="1 s mid price with jumps">
<h2>The race: our pipeline</h2><ul>{tot}</ul><img src="data:image/png;base64,{chart_stages}" alt="slowest pipeline stages">
<h2>Compression</h2><table><tr><th>hypertable</th><th>before</th><th>after</th><th>ratio</th></tr>{comp_rows}</table>
</body></html>"""
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out/dashboard.html").write_text(html)
    print("wrote", HERE / "out/dashboard.html")


if __name__ == "__main__":
    main()
