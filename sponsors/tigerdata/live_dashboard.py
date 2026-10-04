"""COURTSIDE Live Lab dashboard: a local page that re-reads Tiger Data every 3 s while live_ingest.py streams.

    python sponsors/tigerdata/live_ingest.py --minutes 120 &     # terminal 1
    python sponsors/tigerdata/live_dashboard.py                  # terminal 2, then open http://localhost:8790

Every number on the page is one SQL query against the hypertables, continuous aggregates and views in
schema.sql. Read-only: the page never writes to the database.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ingest import db_url  # noqa: E402

PORT = 8790
REFRESH_S = 3.0

QUERIES = {
    "totals": """
        SELECT (SELECT count(*) FROM book_updates WHERE rt > now() - interval '1 minute') / 60.0 AS book_rows_per_s,
               (SELECT count(*) FROM book_updates)                       AS book_rows,
               (SELECT count(*) FROM wallet_trades)                      AS wallet_trades,
               (SELECT count(DISTINCT wallet) FROM wallet_trades)        AS wallets,
               (SELECT count(*) FROM jump_events)                        AS points,
               (SELECT count(DISTINCT market) FROM book_updates WHERE rt > now() - interval '2 minutes') AS live_matches""",
    "lag": """
        SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY p50_ms)::numeric, 0) AS p50_ms,
               round(max(p99_ms)::numeric, 0) AS p99_ms
        FROM ingest_lag WHERE stream = 'book' AND ts > now() - interval '1 minute'""",
    "who_gets_paid": """
        SELECT after_point, trades, wallets, usd, cents_per_share_5s, cents_per_share_30s FROM who_gets_paid
        ORDER BY array_position(ARRAY['0-3 s','3-10 s','10-60 s','60 s+','no recent point'], after_point)""",
    "fast_tier": """
        SELECT left(wallet, 6) || '…' || right(wallet, 4) AS wallet, fast_trades, tokens, usd,
               cents_per_share_30s, pnl_usd_30s FROM fast_tier LIMIT 8""",
    "points": """
        SELECT to_char(j.detected_at AT TIME ZONE 'UTC', 'HH24:MI:SS') AS utc, m.title, m.outcome, j.move_cents
        FROM jump_events j JOIN markets m USING (asset_id)
        ORDER BY j.detected_at DESC LIMIT 12""",
    "match": """
        WITH pick AS (
            SELECT j.asset_id FROM jump_events j JOIN markets m USING (asset_id)
            WHERE m.source = 'live' ORDER BY j.detected_at DESC LIMIT 1
        )
        SELECT m.title, m.outcome,
               (SELECT json_agg(json_build_array(extract(epoch FROM bucket) * 1000, mid) ORDER BY bucket)
                FROM mid_1s WHERE asset_id = pick.asset_id AND bucket > now() - interval '20 minutes') AS path,
               (SELECT json_agg(json_build_array(extract(epoch FROM detected_at) * 1000, move_cents))
                FROM jump_events WHERE asset_id = pick.asset_id AND detected_at > now() - interval '20 minutes') AS jumps
        FROM pick JOIN markets m USING (asset_id)""",
}

STATE: dict = {"ok": False, "error": "starting"}


def _plain(v):
    return float(v) if isinstance(v, Decimal) else v


def refresher():
    while True:
        try:
            with psycopg.connect(db_url(), autocommit=True) as conn:
                conn.execute("SET search_path = courtside, public")
                while True:
                    t0 = time.perf_counter()
                    out, timing = {}, {}
                    for name, sql in QUERIES.items():
                        t = time.perf_counter()
                        cur = conn.execute(sql)
                        cols = [c.name for c in cur.description]
                        out[name] = [{k: _plain(v) for k, v in zip(cols, r)} for r in cur.fetchall()]
                        timing[name] = round((time.perf_counter() - t) * 1e3, 1)
                    STATE.clear()
                    STATE.update(ok=True, data=out, query_ms=timing, total_ms=round((time.perf_counter() - t0) * 1e3, 1),
                                 at=time.strftime("%H:%M:%S"))
                    time.sleep(REFRESH_S)
        except Exception as ex:  # keep serving the last good state; retry the connection
            STATE.update(ok=False, error=repr(ex)[:300])
            time.sleep(3)


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>COURTSIDE Live Lab</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#fbfbfa;--card:#fff;--ink:#1d1d1f;--quiet:#6b6b6b;--rule:#e7e7e4;--accent:#2f6fd6;--good:#2e8b57;--bad:#c0392b}
@media (prefers-color-scheme: dark){:root{--bg:#121212;--card:#1c1c1e;--ink:#f2f2f2;--quiet:#9a9a9a;--rule:#2c2c2e;--accent:#6ea0ff;--good:#5cc28a;--bad:#ff7a6b}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:22px;margin:0} .sub{color:var(--quiet);margin:4px 0 18px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.k,.card{background:var(--card);border:1px solid var(--rule);border-radius:10px;padding:12px 14px}
.k b{display:block;font-size:24px;font-variant-numeric:tabular-nums} .k span{color:var(--quiet);font-size:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px} @media (max-width:800px){.grid{grid-template-columns:1fr}}
h2{font-size:15px;margin:0 0 8px} .note{color:var(--quiet);font-size:12px;margin-top:6px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums} th,td{padding:5px 6px;border-bottom:1px solid var(--rule);text-align:right}
th:first-child,td:first-child{text-align:left} th{color:var(--quiet);font-weight:500;font-size:12px}
.pos{color:var(--good)} .neg{color:var(--bad)} .wide{grid-column:1/-1} #status{font-size:12px;color:var(--quiet)}
</style></head><body><main>
<h1>COURTSIDE Live Lab <span id="status"></span></h1>
<p class="sub">Who gets paid in the seconds after a tennis point, measured live in Tiger Data from public Polymarket data. Paper only: nothing here trades.</p>
<div class="kpis">
 <div class="k"><b id="k_rate">–</b><span>order-book ticks / s</span></div>
 <div class="k"><b id="k_lag">–</b><span>exchange → stored, p50</span></div>
 <div class="k"><b id="k_matches">–</b><span>live matches</span></div>
 <div class="k"><b id="k_points">–</b><span>points detected in SQL</span></div>
 <div class="k"><b id="k_wallets">–</b><span>wallets scored</span></div>
 <div class="k"><b id="k_ms">–</b><span>all queries, ms</span></div>
</div>
<div class="grid">
 <div class="card wide"><h2 id="m_title">Latest point</h2><div style="height:260px"><canvas id="c_match"></canvas></div>
  <div class="note">1-second mid from the <code>mid_1s</code> real-time continuous aggregate; dashed lines = points found by the in-database <code>detect_jumps</code> job.</div></div>
 <div class="card"><h2>Who gets paid after a point</h2><table id="t_paid"></table>
  <div class="note">Every wallet trade marked to the mid 5 s and 30 s later (<code>markouts</code> view), grouped by seconds since the last point. The paper: only the first 3 s profit.</div></div>
 <div class="card"><h2>Fast tier: top wallets trading within 3 s</h2><table id="t_fast"></table>
  <div class="note">Public proxy wallets, shortened. P&amp;L marked at 30 s, not realised.</div></div>
 <div class="card wide"><h2>Latest points</h2><table id="t_points"></table></div>
</div></main>
<script>
const $=id=>document.getElementById(id), fmt=(v,d=0)=>v==null?'–':Number(v).toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d});
const sign=v=>v==null?'':(v>0?'pos':v<0?'neg':'');
function table(el, rows, cols){ el.innerHTML='<tr>'+cols.map(c=>`<th>${c[1]}</th>`).join('')+'</tr>'+
  rows.map(r=>'<tr>'+cols.map(c=>`<td class="${c[3]?sign(r[c[0]]):''}">${typeof r[c[0]]==='number'?fmt(r[c[0]],c[2]||0):(r[c[0]]??'–')}</td>`).join('')+'</tr>').join(''); }
const css=getComputedStyle(document.documentElement), accent=css.getPropertyValue('--accent').trim(), quiet=css.getPropertyValue('--quiet').trim();
const chart=new Chart($('c_match'),{type:'line',data:{datasets:[{data:[],borderColor:quiet,borderWidth:1.5,pointRadius:0,tension:0}]},
 options:{animation:false,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{type:'linear',ticks:{callback:v=>new Date(v).toISOString().slice(11,19),maxTicksLimit:8,color:quiet},grid:{display:false}},y:{title:{display:true,text:'mid ($ per share)',color:quiet},ticks:{color:quiet}}}},
 plugins:[{id:'jumps',afterDatasetsDraw(c){const j=c.$jumps||[],{ctx,chartArea:a,scales:{x}}=c;ctx.save();ctx.strokeStyle=accent;ctx.fillStyle=accent;ctx.setLineDash([4,4]);
  j.forEach(([t,mv])=>{const px=x.getPixelForValue(t);if(px<a.left||px>a.right)return;ctx.beginPath();ctx.moveTo(px,a.top);ctx.lineTo(px,a.bottom);ctx.stroke();ctx.fillText((mv>0?'+':'')+Number(mv).toFixed(1)+'¢',px+4,a.top+12)});ctx.restore();}}]});
async function tick(){
 try{const s=await (await fetch('/api/state')).json();
  if(!s.ok){$('status').textContent='· waiting for database: '+s.error;return}
  const d=s.data,t=d.totals[0]||{},l=d.lag[0]||{};
  $('k_rate').textContent=fmt(t.book_rows_per_s);$('k_lag').textContent=l.p50_ms==null?'–':fmt(l.p50_ms)+' ms';
  $('k_matches').textContent=fmt(t.live_matches);$('k_points').textContent=fmt(t.points);$('k_wallets').textContent=fmt(t.wallets);$('k_ms').textContent=fmt(s.total_ms);
  $('status').textContent='· updated '+s.at;
  table($('t_paid'),d.who_gets_paid,[['after_point','after the point'],['trades','trades'],['usd','$ traded'],['cents_per_share_5s','¢/share at 5 s',2,1],['cents_per_share_30s','¢/share at 30 s',2,1]]);
  table($('t_fast'),d.fast_tier,[['wallet','wallet'],['fast_trades','trades'],['usd','$ traded'],['cents_per_share_30s','¢/share',2,1],['pnl_usd_30s','P&L $',2,1]]);
  table($('t_points'),d.points,[['utc','UTC'],['title','match'],['outcome','token'],['move_cents','move ¢',1,1]]);
  const m=(d.match||[])[0]; if(m){$('m_title').textContent='Latest point: '+m.title+' ('+m.outcome+')';
   chart.data.datasets[0].data=(m.path||[]).map(([x,y])=>({x,y}));chart.$jumps=m.jumps||[];chart.update();}
 }catch(e){$('status').textContent='· '+e}
}
tick();setInterval(tick,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body, ctype = (json.dumps(STATE, default=str).encode(), "application/json") if self.path.startswith("/api/state") \
            else (PAGE.encode(), "text/html; charset=utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=refresher, daemon=True).start()
    print(f"COURTSIDE Live Lab on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
