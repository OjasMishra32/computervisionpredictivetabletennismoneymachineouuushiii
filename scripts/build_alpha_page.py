#!/usr/bin/env python3
"""Render results/alpha/alpha.json as one self-contained page: docs/live/alpha.html.

Pure render. The only input is results/alpha/alpha.json (written by scripts/alpha_pack.py); no
trade file is read and nothing is evaluated. The few numbers the page derives itself (factor-beta
95% CIs from beta and t, counts of positive splits, the end points of the calendar trend line,
failure-panel counts) are written back into alpha.json under "page_derived", each with an entry
under "sources", so every number on the page has a source key.

Page contract: <title> Courtside Alpha; no external requests except Google Fonts; all data
inline; dark-first colour tokens with a light override; charts are inline SVG drawn by the
inline script, each with axis labels, units, a one-line takeaway and a table view.

    .venv/bin/python scripts/build_alpha_page.py
    bash scripts/serve_live.sh   ->  http://localhost:8765/alpha.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "results" / "alpha" / "alpha.json"
OUT = ROOT / "docs" / "live" / "alpha.html"
ME = "computed in scripts/build_alpha_page.py"
D_SPLITS = ("by_price_decile_q", "by_regime_delay_fee", "by_time_of_day_utc", "by_month",
            "by_seconds_since_detection", "by_direction_vs_jump")


def month_index(m: str) -> int:
    """Months since 2025-12, the index scripts/alpha_pack.py uses for the calendar OLS."""
    return (int(m[:4]) - 2025) * 12 + int(m[5:7]) - 12


def derive(d: dict) -> tuple[dict, dict]:
    der: dict = {}
    src: dict = {}

    c = d["C_factor_neutral"]["committed"]
    der["C_beta_ci95"] = {}
    for f in ("MktRF", "SMB", "HML", "Mom"):
        b, t = c["betas"][f], c["betas_t"][f]
        se = abs(b / t)
        der["C_beta_ci95"][f] = [round(b - 1.96 * se, 4), round(b + 1.96 * se, 4)]
    src["page_derived.C_beta_ci95"] = (
        f"{ME}: beta +/- 1.96*|beta/t| from C_factor_neutral.committed.(betas, betas_t); normal "
        "approximation; t is rounded to 2 dp in the source, so the interval is approximate")

    der["D_counts"] = {}
    for p in ("IS", "OOS"):
        der["D_counts"][p] = {}
        for split in D_SPLITS:
            rows = d["D_where"][p][split]
            der["D_counts"][p][split] = {
                "n": len(rows),
                "net_positive": sum(r["net_c_per_share"] > 0 for r in rows),
                "ci_above_zero": sum(r["net_ci95_c_match_clustered"][0] > 0 for r in rows),
                "ci_below_zero": sum(r["net_ci95_c_match_clustered"][1] < 0 for r in rows),
            }
    src["page_derived.D_counts"] = (
        f"{ME}: per period and split of D_where, the number of groups with net_c_per_share > 0 and "
        "with a match-clustered 95% CI wholly above / below zero")

    o = d["E_decay"]["over_calendar_time"]["IS_plus_OOS_rows"]
    months = [m["month"] for p in ("IS", "OOS") for m in d["A_source"][p]["months"]]
    i0, i1 = min(map(month_index, months)), max(map(month_index, months))
    der["E_trend_line"] = {
        "month_index_origin": "2025-12",
        "month_index": [i0, i1],
        "fitted_c": [round(o["intercept_c"] + o["slope_c_per_month"] * i, 4) for i in (i0, i1)],
    }
    src["page_derived.E_trend_line"] = (
        f"{ME}: intercept_c + slope_c_per_month x month index at the first and last month, from "
        "E_decay.over_calendar_time.IS_plus_OOS_rows (drawn as the trend line)")

    rows = d["I_failures"]["rows"]
    pend = sum("pending" in r["verdict"].lower() for r in rows)
    der["I_counts"] = {"n_rows": len(rows), "pending": pend, "not_pending": len(rows) - pend}
    src["page_derived.I_counts"] = f"{ME}: rows of I_failures.rows with and without the verdict 'pending'"
    return der, src


def script_json(obj: dict) -> str:
    # '<' only occurs inside JSON strings, so < keeps the payload valid JSON and inert HTML.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def main() -> int:
    d = json.loads(SRC.read_text())
    der, src = derive(d)
    d["page_derived"] = der
    d["sources"] = {k: v for k, v in d["sources"].items() if not k.startswith("page_derived.")} | src
    SRC.write_text(json.dumps(d, indent=1, default=float, allow_nan=False))

    html = TEMPLATE.replace("__ALPHA_JSON__", script_json(d))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(html.encode()) / 1024:.0f} KiB) from "
          f"{SRC.relative_to(ROOT)} (generated {d['generated_utc']}, {len(d['sources'])} source keys)")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Courtside Alpha</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600;700&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one editorial column (max 1120px). Hero = thesis, four figures, the caveats; then
   sections A-I keyed to alpha.json, each = takeaway headline, chart with a table twin, source
   keys; footer = definitions, checks, every source, the command. Mission Control palette. */
:root{
  color-scheme:dark;
  --bg:#07111b; --panel:#0c1a28; --band:#14283c; --line:#1d3044; --grid:#172a3d;
  --ink:#e8eef4; --ink2:#bccad7; --muted:#8fa2b5;
  --fast:#3987e5; --loss:#e45f48; --copy:#9a78e8; --amber:#f2b33d;
  --shadow:0 8px 28px rgba(0,0,0,.5);
  --display:"Saira Condensed","Arial Narrow",sans-serif;
  --body:"Public Sans","Helvetica Neue",Arial,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme: light){
  :root:not([data-theme="dark"]){
    color-scheme:light;
    --bg:#eef2f6; --panel:#ffffff; --band:#e9eff5; --line:#d3dce5; --grid:#e6ecf2;
    --ink:#0b1a29; --ink2:#2f4256; --muted:#5a6d80;
    --fast:#1f6fd1; --loss:#d9452b; --copy:#8a5cd6; --amber:#b7791f;
    --shadow:0 8px 24px rgba(11,26,41,.16);
  }
}
:root[data-theme="light"]{
  color-scheme:light;
  --bg:#eef2f6; --panel:#ffffff; --band:#e9eff5; --line:#d3dce5; --grid:#e6ecf2;
  --ink:#0b1a29; --ink2:#2f4256; --muted:#5a6d80;
  --fast:#1f6fd1; --loss:#d9452b; --copy:#8a5cd6; --amber:#b7791f;
  --shadow:0 8px 24px rgba(11,26,41,.16);
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink)}
body{font:15px/1.55 var(--body);-webkit-text-size-adjust:100%;text-size-adjust:100%}
a{color:inherit;text-underline-offset:2px}
a:focus-visible,button:focus-visible{outline:2px solid var(--fast);outline-offset:2px}
.wrap{max-width:1120px;margin-inline:auto;padding-inline:16px;padding-block:28px 72px}
@media (min-width:720px){.wrap{padding-inline:32px}}

/* hero */
.kicker{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;font:500 11.5px/1.3 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.kicker .sq{width:9px;height:9px;background:var(--fast);border-radius:2px}
.kicker .gen{letter-spacing:.04em;text-transform:none}
h1{font:700 clamp(40px,7vw,76px)/.92 var(--display);text-transform:uppercase;letter-spacing:.01em;margin:16px 0 0}
.thesis{font:600 clamp(23px,3.2vw,34px)/1.14 var(--display);margin:18px 0 0;max-width:30em;text-wrap:balance}
.defs-row{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:16px;font-size:13px;color:var(--ink2);max-width:80em}
.defs-row span{display:inline-flex;gap:8px;align-items:baseline;min-width:0}
.chip{display:inline-flex;align-items:center;gap:6px;flex:none;font:500 10.5px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;padding:4px 7px;border:1px solid var(--line);border-radius:4px;color:var(--ink);white-space:nowrap}
.chip::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--muted)}
.chip.oos::before,.chip.cf::before,.chip.warn::before{background:var(--amber)}
.chip.h6::before{background:var(--fast)}
.chip.fail::before{background:var(--loss)}
.chip.pend::before{background:transparent;border:1.5px solid var(--amber);width:5px;height:5px}
.chip.cf{border-color:var(--amber)}
.figs4{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,232px),1fr));gap:0 28px;margin-top:30px}
.f4{border-top:1px solid var(--line);padding-block:14px 8px;min-width:0}
.f4 .lab{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;font:500 11.5px/1.3 var(--mono);letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.f4 .val{font:600 clamp(40px,5vw,54px)/1 var(--body);letter-spacing:-.02em;margin-top:12px;white-space:nowrap}
.f4 .val small{font:500 15px var(--body);letter-spacing:0;color:var(--ink2);margin:0 10px 0 5px}
.f4 .sub{font-size:13px;line-height:1.45;color:var(--ink2);margin-top:9px}
.caveats{margin-top:26px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding-block:14px}
.caveats h3{margin:0 0 10px;font:500 11.5px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.caveats ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:10px 28px}
.caveats li{display:grid;grid-template-columns:10px 1fr;gap:10px;font-size:13.5px;line-height:1.45;min-width:0}
.caveats li::before{content:"";width:8px;height:8px;margin-top:6px;background:var(--amber);border-radius:2px}
.caveats a{text-decoration:none;border-bottom:1px solid var(--line)}
.toc{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:20px;font:400 12.5px/1.3 var(--mono);color:var(--ink2)}
.toc a{text-decoration:none;border-bottom:1px solid var(--line);padding-bottom:2px}
.toc b{font-weight:500;color:var(--ink);margin-right:5px}

/* sections */
.sec{padding-top:60px;scroll-margin-top:12px}
.sec-head{display:flex;align-items:baseline;gap:12px;border-top:1px solid var(--line);padding-top:14px}
.sec-key{font:700 44px/.9 var(--display);color:var(--muted)}
.sec-name{font:500 11.5px/1.3 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
h2{font:600 clamp(23px,2.8vw,32px)/1.15 var(--display);margin:12px 0 0;max-width:36em;text-wrap:balance}
.lede{color:var(--ink2);max-width:76ch;margin:10px 0 0;font-size:14.5px}
.grid2{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;margin-top:18px}
.grid2>.fig,.grid2>.kt{margin-top:0}
@media (min-width:920px){.grid2{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.grid2.wide-left{grid-template-columns:minmax(0,1.35fr) minmax(0,1fr)}}

/* figures */
.fig{margin:18px 0 0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 12px 12px;min-width:0}
@media (min-width:720px){.fig{padding:16px 18px 14px}}
.fig-bar{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px 16px}
.fig-title{font:600 14px/1.35 var(--body);min-width:0}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden;flex:none}
.seg button{font:500 11.5px/1 var(--mono);letter-spacing:.04em;background:transparent;color:var(--muted);border:0;padding:7px 11px;cursor:pointer}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-pressed="true"]{background:var(--band);color:var(--ink)}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.tabs button{font:500 12px/1 var(--mono);background:transparent;color:var(--ink2);border:1px solid var(--line);border-radius:6px;padding:7px 10px;cursor:pointer}
.tabs button[aria-pressed="true"]{background:var(--band);color:var(--ink);border-color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:10px;font-size:12.5px;line-height:1.35;color:var(--ink2)}
.lg{display:inline-flex;align-items:center;gap:7px;min-width:0}
.sw{flex:none;width:12px;height:12px;border-radius:3px;background:var(--c)}
.sw.dot{border-radius:50%}
.sw.ring{border-radius:50%;background:transparent;border:2px solid var(--c)}
.sw.tint{background:transparent;border:1.5px solid var(--c);position:relative;overflow:hidden}
.sw.tint::after{content:"";position:absolute;inset:0;background:var(--c);opacity:.32}
.sw.light{opacity:.5}
.sw.line{width:16px;height:2px;border-radius:1px}
.sw.band{background:var(--band);border:1px solid var(--line)}
.c-fast{--c:var(--fast)} .c-loss{--c:var(--loss)} .c-copy{--c:var(--copy)} .c-ink{--c:var(--ink2)} .c-amber{--c:var(--amber)} .c-band{--c:var(--band)}
.plot{margin-top:10px;overflow-x:auto;overflow-y:hidden}
.plot.custom{overflow:visible}
.plot svg{display:block}
.tbl{margin-top:10px}
.tscroll,.tbl{overflow-x:auto}
figcaption{margin-top:10px;font-size:13.5px;line-height:1.45;color:var(--ink)}
figcaption b{font-weight:600}
.notes{font-size:12.5px;line-height:1.5;color:var(--muted);margin:6px 0 0;max-width:110ch}
.src{font:400 11px/1.55 var(--mono);color:var(--muted);margin:8px 0 0;overflow-wrap:anywhere}
.src a{color:var(--muted)}

/* tables */
table{border-collapse:collapse;width:100%;font:400 12.5px/1.35 var(--mono);font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;vertical-align:top}
thead th{font-weight:500;color:var(--muted);font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;vertical-align:bottom;white-space:normal;min-width:64px}
th:first-child,td:first-child{text-align:left}
tbody th{font-weight:400;color:var(--ink);white-space:normal;min-width:150px;max-width:340px}
td.wrap{white-space:normal;min-width:220px;text-align:left}
.kt{margin-top:18px;min-width:0}
.kt-title{font:600 13px/1.3 var(--body);margin-bottom:6px}
.kt table{font-size:12.5px}
@media (max-width:600px){.kt tbody th{min-width:112px}.kt td{white-space:normal;min-width:84px}.kt th,.kt td{padding-inline:6px}}
.hdr{paint-order:stroke;stroke:var(--panel);stroke-width:5px;stroke-linejoin:round}

/* ladder + failure rows */
.ladder{display:grid}
.lrow{display:grid;grid-template-columns:minmax(0,1fr);gap:6px 22px;padding-block:12px;border-bottom:1px solid var(--line)}
.lrow:last-child{border-bottom:0}
@media (min-width:760px){.lrow{grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);align-items:center}}
.lmeta{min-width:0}
.lname{font:600 13.5px/1.35 var(--body)}
.lsub{display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center;font-size:12px;line-height:1.4;color:var(--muted);margin-top:4px}
.lvals{font:400 12px/1.5 var(--mono);color:var(--ink2);margin-top:4px;font-variant-numeric:tabular-nums}
.lwarn{display:grid;grid-template-columns:10px 1fr;gap:8px;font-size:12.5px;line-height:1.4;color:var(--ink);margin-top:6px}
.lwarn::before{content:"";width:8px;height:8px;margin-top:5px;background:var(--amber);border-radius:2px}
.lplot{min-width:0}
.lplot svg{display:block}
.lnote{margin:0;font-size:12.5px;line-height:1.45;color:var(--ink2)}
.laxis .lmeta{font-size:12px;color:var(--muted)}

/* svg */
.tick{font:400 10.5px var(--mono);fill:var(--muted);font-variant-numeric:tabular-nums}
.axt{font:400 11.5px var(--body);fill:var(--ink2)}
.vlab{font:500 11px var(--mono);fill:var(--ink);font-variant-numeric:tabular-nums}
.plab{font:500 10.5px var(--mono);letter-spacing:.08em;fill:var(--muted)}
.rlab{font:500 12px var(--body);fill:var(--ink)}
.rsub{font:400 10.5px var(--mono);fill:var(--muted)}
.gl{stroke:var(--grid);stroke-width:1;shape-rendering:crispEdges}
.z{stroke:var(--muted);stroke-width:1;stroke-opacity:.75;shape-rendering:crispEdges}
.sep{stroke:var(--line);stroke-width:1;shape-rendering:crispEdges}
.refl{stroke:var(--ink2);stroke-width:1;shape-rendering:crispEdges}
.conn{stroke:var(--muted);stroke-width:1;stroke-opacity:.7;shape-rendering:crispEdges}
.slip{stroke:var(--muted);stroke-width:2}
.band{fill:var(--band)}
.f-fast{fill:var(--fast)} .f-loss{fill:var(--loss)} .f-copy{fill:var(--copy)}
.s-fast{stroke:var(--fast)} .s-loss{stroke:var(--loss)} .s-copy{stroke:var(--copy)} .s-ink{stroke:var(--ink2)}
.dot{stroke:var(--panel);stroke-width:2}
.ring{fill:var(--panel);stroke-width:2}
.tint{fill-opacity:.32;stroke-width:1.5}
.stress{fill-opacity:.5}
.wh{fill:none;stroke-width:1.5;stroke-linecap:round}
.ciband{fill-opacity:.14;stroke:none}
.ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.trend{fill:none;stroke:var(--ink2);stroke-width:1.5}
.hb{fill:transparent}
.hit .mk{transition:filter .12s}
.hit:hover .mk{filter:brightness(1.22)}
#tip{position:fixed;z-index:20;pointer-events:none;max-width:300px;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px 10px;font:400 12px/1.45 var(--body);color:var(--ink2);box-shadow:var(--shadow)}
#tip b{display:block;font:600 13px/1.35 var(--mono);color:var(--ink);font-variant-numeric:tabular-nums}

/* footer */
.foot{margin-top:72px;border-top:1px solid var(--line);padding-top:22px;display:grid;gap:30px}
.foot h3{margin:0 0 10px;font:500 11.5px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.defs{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:14px 30px;margin:0}
.defs div{min-width:0}
.defs dt{font:600 13px/1.3 var(--body)}
.defs dd{margin:4px 0 0;font-size:13px;line-height:1.5;color:var(--ink2)}
.checks{list-style:none;margin:0;padding:0;display:grid;gap:6px;font:400 12px/1.45 var(--mono);color:var(--ink2)}
.checks li{display:grid;grid-template-columns:auto 1fr;gap:10px;min-width:0}
.srcs{columns:2 380px;column-gap:30px;font:400 11px/1.5 var(--mono);color:var(--muted)}
.srcs div{break-inside:avoid;margin-bottom:7px;overflow-wrap:anywhere;scroll-margin-top:12px}
.srcs div:target{color:var(--ink)}
.srcs b{display:block;font-weight:500;color:var(--ink2)}
.cmd{display:flex;flex-wrap:wrap;gap:8px;align-items:stretch}
.cmd pre{margin:0;flex:1 1 320px;min-width:0;overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px;font:400 12.5px/1.5 var(--mono);color:var(--ink)}
.cmd button{font:500 12px/1 var(--mono);background:var(--band);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:0 14px;min-height:38px;cursor:pointer}
.prov{font-size:12.5px;line-height:1.5;color:var(--muted);margin:0;overflow-wrap:anywhere}
.foot>*{min-width:0}
@media (prefers-reduced-motion: reduce){.hit .mk{transition:none}}
</style>
</head>
<body>
<div class="wrap">
  <header id="hero"></header>
  <main id="main"></main>
  <footer class="foot" id="foot"></footer>
</div>
<noscript><p style="padding:16px">This page draws its charts and tables with JavaScript. Every number is in results/alpha/alpha.json.</p></noscript>
<script id="alpha-data" type="application/json">__ALPHA_JSON__</script>
<script>
(function () {
'use strict';
const D = JSON.parse(document.getElementById('alpha-data').textContent);
const NS = 'http://www.w3.org/2000/svg';
const MINUS = '−';

/* ---------- formatting ---------- */
const ok = v => typeof v === 'number' && isFinite(v);
const fx = (v, d = 2) => { if (!ok(v)) return '—'; const a = Math.abs(v).toFixed(d); return (v < 0 && +a !== 0 ? MINUS : '') + a; };
const sg = (v, d = 2) => { if (!ok(v)) return '—'; const a = Math.abs(v).toFixed(d); return +a === 0 ? a : (v > 0 ? '+' : MINUS) + a; };
const ci = (a, d = 2) => a ? '[' + fx(a[0], d) + ', ' + fx(a[1], d) + ']' : '';
const pc = (v, d = 1) => ok(v) ? fx(v * 100, d) + '%' : '—';
const usd = (v, d = 0) => ok(v) ? (v < 0 ? MINUS : '') + '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}) : '—';
const usdk = v => { const a = Math.abs(v); return (v < 0 ? MINUS : '') + '$' + (a >= 1e6 ? (a / 1e6).toFixed(2) + 'M' : a >= 1e3 ? (a / 1e3).toFixed(1) + 'k' : a.toFixed(0)); };
const n0 = v => ok(v) ? Math.round(v).toLocaleString('en-US') : '—';
const pretty = s => String(s == null ? '' : s).replace(/(^|[\s(\[\/:=~,])-(?=\.?\d)/g, '$1' + MINUS).replace(/\bR2\b/g, 'R²');
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const mon = m => MON[+m.slice(5, 7) - 1];
const monY = m => mon(m) + ' ' + m.slice(0, 4);
const mi = m => (+m.slice(0, 4) - 2025) * 12 + (+m.slice(5, 7)) - 12;
const r1 = v => Math.round(v * 10) / 10;
const slug = k => k.replace(/[^A-Za-z0-9._-]+/g, '-');
const tl = (v, d) => Math.abs(v) < 1e-9 ? '0' : fx(v, d);
const dash = s => String(s).replace(/(\d)-(\d)/g, '$1–$2');
const PV = {IS: 'in sample', OOS: 'burned OOS, non-blind'};
const cap = s => { s = String(s); return s.charAt(0).toUpperCase() + s.slice(1); };

/* ---------- DOM helpers ---------- */
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (attrs) for (const k of Object.keys(attrs)) {
    const v = attrs[k];
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v; else e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) e.append(k instanceof Node ? k : String(k));
  return e;
}
function S(parent, tag, attrs, text) {
  const e = document.createElementNS(NS, tag);
  if (attrs) for (const k of Object.keys(attrs)) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}
function table(spec) {
  const t = h('table');
  t.append(h('thead', null, h('tr', null, spec.cols.map(c => h('th', {scope: 'col'}, c)))));
  const tb = h('tbody');
  for (const r of spec.rows) tb.append(h('tr', null, r.map((c, i) => i === 0 ? h('th', {scope: 'row'}, c) : h('td', spec.wrapCols && spec.wrapCols.includes(i) ? {class: 'wrap'} : null, c))));
  t.append(tb);
  return t;
}
function legend(items) {
  return h('div', {class: 'legend'}, items.map(([c, kind, label]) => h('span', {class: 'lg'}, h('i', {class: 'sw ' + kind + ' c-' + c, 'aria-hidden': 'true'}), label)));
}
function srcLine(keys) {
  return h('p', {class: 'src'}, 'Source keys: ', keys.map((k, i) => [i ? ' · ' : '', h('a', {href: '#src-' + slug(k)}, k)]));
}
function kt(title, cols, rows, notes) {
  return h('div', {class: 'kt'}, title ? h('div', {class: 'kt-title'}, title) : null,
    h('div', {class: 'tscroll'}, table({cols, rows})), (notes || []).map(n => h('p', {class: 'notes'}, n)));
}

/* ---------- scales ---------- */
const lin = (d0, d1, r0, r1_) => v => r0 + (v - d0) / (d1 - d0) * (r1_ - r0);
const lg = (d0, d1, r0, r1_) => { const a = Math.log(d0), b = Math.log(d1); return v => r0 + (Math.log(v) - a) / (b - a) * (r1_ - r0); };
function nice(lo, hi, n) {
  if (hi - lo < 1e-9) hi = lo + 1;
  const raw = (hi - lo) / (n || 5), mag = Math.pow(10, Math.floor(Math.log10(raw))), e = raw / mag;
  const st = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * mag;
  const L = Math.floor(lo / st + 1e-9) * st, Hh = Math.ceil(hi / st - 1e-9) * st, t = [];
  for (let v = L; v <= Hh + st / 2; v += st) t.push(+v.toFixed(10));
  return {lo: L, hi: Hh, st, t, dec: st >= 1 ? 0 : Math.ceil(-Math.log10(st) - 1e-9)};
}
function padded(vals, n, frac) {
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals), p = (hi - lo) * (frac || 0);
  return nice(lo < 0 ? lo - p : lo, hi > 0 ? hi + p : hi, n);
}
function yTicks(g, sc, y, x0, x1, fmt) {
  for (const v of sc.t) {
    const yy = r1(y(v)) + 0.5;
    if (Math.abs(v) > 1e-9) S(g, 'line', {x1: x0, x2: x1, y1: yy, y2: yy, class: 'gl'});
    S(g, 'text', {x: x0 - 6, y: yy + 3.5, class: 'tick', 'text-anchor': 'end'}, fmt ? fmt(v) : tl(v, sc.dec));
  }
}
function zeroY(g, y, x0, x1) { const yy = r1(y(0)) + 0.5; S(g, 'line', {x1: x0, x2: x1, y1: yy, y2: yy, class: 'z'}); }
function zeroX(g, x, y0, y1) { const xx = r1(x(0)) + 0.5; S(g, 'line', {x1: xx, x2: xx, y1: y0, y2: y1, class: 'z'}); }
function vbar(x, w, y0, y1, r) {
  const L = Math.abs(y1 - y0); r = Math.min(r == null ? 4 : r, L, w / 2);
  if (L < 0.5) return 'M' + x + ',' + y0 + 'h' + w;
  if (y1 < y0) return `M${x},${y0}V${r1(y1 + r)}Q${x},${y1} ${r1(x + r)},${y1}H${r1(x + w - r)}Q${r1(x + w)},${y1} ${r1(x + w)},${r1(y1 + r)}V${y0}Z`;
  return `M${x},${y0}V${r1(y1 - r)}Q${x},${y1} ${r1(x + r)},${y1}H${r1(x + w - r)}Q${r1(x + w)},${y1} ${r1(x + w)},${r1(y1 - r)}V${y0}Z`;
}
function hbar(y, t, x0, x1, r) {
  const L = Math.abs(x1 - x0); r = Math.min(r == null ? 4 : r, L, t / 2);
  if (L < 0.5) return 'M' + x0 + ',' + y + 'v' + t;
  if (x1 > x0) return `M${x0},${y}H${r1(x1 - r)}Q${x1},${y} ${x1},${r1(y + r)}V${r1(y + t - r)}Q${x1},${r1(y + t)} ${r1(x1 - r)},${r1(y + t)}H${x0}Z`;
  return `M${x0},${y}H${r1(x1 + r)}Q${x1},${y} ${x1},${r1(y + r)}V${r1(y + t - r)}Q${x1},${r1(y + t)} ${r1(x1 + r)},${r1(y + t)}H${x0}Z`;
}
const hit = (g, tip) => S(g, 'g', {class: 'hit', 'data-tip': tip});

/* ---------- tooltip ---------- */
const tip = h('div', {id: 'tip', role: 'tooltip', hidden: true});
document.body.append(tip);
let tipFor = null;
function placeTip(x, y) {
  const r = tip.getBoundingClientRect();
  let L = x + 14, T = y + 16;
  if (L + r.width > innerWidth - 8) L = x - r.width - 14;
  if (L < 8) L = 8;
  if (T + r.height > innerHeight - 8) T = y - r.height - 14;
  if (T < 8) T = 8;
  tip.style.left = L + 'px'; tip.style.top = T + 'px';
}
function onPointer(e) {
  const t = e.target && e.target.closest ? e.target.closest('[data-tip]') : null;
  if (!t) { if (tipFor) { tip.hidden = true; tipFor = null; } return; }
  if (t !== tipFor) {
    tip.textContent = '';
    const lines = t.getAttribute('data-tip').split('\n');
    tip.append(h('b', null, lines[0]));
    for (const l of lines.slice(1)) tip.append(h('div', null, l));
    tip.hidden = false; tipFor = t;
  }
  placeTip(e.clientX, e.clientY);
}
document.addEventListener('pointermove', onPointer);
document.addEventListener('pointerdown', onPointer);
addEventListener('scroll', () => { if (tipFor) { tip.hidden = true; tipFor = null; } }, {passive: true});

/* ---------- figure with chart / table toggle ---------- */
function figure(o) {
  const bC = h('button', {type: 'button', 'aria-pressed': 'true'}, 'Chart');
  const bT = h('button', {type: 'button', 'aria-pressed': 'false'}, 'Table');
  const plot = h('div', {class: 'plot' + (o.custom ? ' custom' : '')});
  const tbl = h('div', {class: 'tbl', hidden: true});
  const take = h('span');
  const fig = h('figure', {class: 'fig'},
    h('div', {class: 'fig-bar'}, h('div', {class: 'fig-title'}, o.title), h('div', {class: 'seg', role: 'group', 'aria-label': 'Show as'}, bC, bT)),
    o.controls || null, o.legend ? legend(o.legend) : null, plot, tbl,
    h('figcaption', null, h('b', null, 'Takeaway: '), take),
    (o.notes || []).map(n => h('p', {class: 'notes'}, n)),
    o.keys ? srcLine(o.keys) : null);
  let svg = null, lastW = 0;
  if (o.custom) plot.append(o.custom.el);
  else { svg = S(null, 'svg', {role: 'img', 'aria-label': o.title}); plot.append(svg); }
  const setTake = () => { take.textContent = typeof o.take === 'function' ? o.take() : o.take; };
  const render = force => {
    const cw = plot.clientWidth; if (!cw) return;
    const W = Math.max(o.minW || 0, Math.floor(cw));
    if (W === lastW && !force) return;
    lastW = W;
    if (o.custom) { o.custom.redraw(W); return; }
    svg.textContent = '';
    const H = o.draw(svg, W);
    svg.setAttribute('width', W); svg.setAttribute('height', H); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  };
  const fillTable = () => { tbl.textContent = ''; tbl.append(table(o.table())); };
  bC.addEventListener('click', () => { bC.setAttribute('aria-pressed', 'true'); bT.setAttribute('aria-pressed', 'false'); tbl.hidden = true; plot.hidden = false; render(true); });
  bT.addEventListener('click', () => { bT.setAttribute('aria-pressed', 'true'); bC.setAttribute('aria-pressed', 'false'); fillTable(); plot.hidden = true; tbl.hidden = false; });
  fig.refresh = () => { setTake(); if (!plot.hidden) render(true); if (!tbl.hidden) fillTable(); };
  fig.render = render;
  setTake();
  if ('ResizeObserver' in window) new ResizeObserver(() => render(false)).observe(plot);
  else addEventListener('resize', () => render(false));
  FIGS.push(fig);
  return fig;
}
const FIGS = [];

function section(key, name, title, lede, ...kids) {
  const s = h('section', {class: 'sec', id: key, 'aria-labelledby': 'h-' + key},
    h('div', {class: 'sec-head'}, h('span', {class: 'sec-key', 'aria-hidden': 'true'}, key), h('span', {class: 'sec-name'}, name)),
    h('h2', {id: 'h-' + key}, title),
    lede ? h('p', {class: 'lede'}, lede) : null, kids);
  document.getElementById('main').append(s);
  return s;
}

/* ---------- shared horizontal dot plot (IS filled, OOS hollow, 95% CI whiskers) ---------- */
function dotRows(svg, W, c) {
  const rh = c.rh || 30, m = {t: c.ref ? 30 : 14, r: 14, b: 48, l: Math.min(c.lw, Math.round(W * 0.42))};
  const items = []; let yy = m.t;
  for (const r of c.rows) {
    if (r.group) { items.push({hdr: r.group, y: yy + 18}); yy += 28; }
    else { items.push({r, y: yy + rh / 2}); yy += rh; }
  }
  const H = yy + m.b, x0 = m.l, x1 = W - m.r, vals = [];
  for (const it of items) if (it.r) for (const p of ['IS', 'OOS']) {
    const d = it.r[p]; if (!d) continue;
    if (ok(d.v)) vals.push(d.v);
    if (ok(d.lo)) vals.push(d.lo, d.hi);
  }
  if (c.ref) vals.push(c.ref.v);
  const nt = Math.max(3, Math.min(c.nt || 6, Math.floor((x1 - x0) / 56)));
  const sc = nice(Math.min(0, ...vals), Math.max(0, ...vals), nt), x = lin(sc.lo, sc.hi, x0, x1);
  for (const v of sc.t) {
    const xx = r1(x(v)) + 0.5;
    if (Math.abs(v) > 1e-9) S(svg, 'line', {x1: xx, x2: xx, y1: m.t - 4, y2: yy, class: 'gl'});
    S(svg, 'text', {x: xx, y: yy + 16, class: 'tick', 'text-anchor': 'middle'}, c.fmt ? c.fmt(v) : tl(v, sc.dec));
  }
  if (c.ref) {
    const xx = r1(x(c.ref.v)) + 0.5, est = c.ref.label.length * 6.3, right = xx + 6 + est <= W;
    S(svg, 'line', {x1: xx, x2: xx, y1: m.t - 10, y2: yy, class: 'refl'});
    S(svg, 'text', {x: right ? xx + 6 : xx - 6, y: m.t - 14, class: 'rsub', 'text-anchor': right ? 'start' : 'end'}, c.ref.label);
  }
  zeroX(svg, x, m.t - 4, yy);
  for (const it of items) {
    if (it.hdr) { S(svg, 'text', {x: 0, y: it.y, class: 'plab hdr'}, it.hdr); continue; }
    const r = it.r, both = !!(r.IS && r.OOS);
    S(svg, 'text', {x: 0, y: it.y + 4, class: 'rlab'}, r.label);
    for (const p of ['IS', 'OOS']) {
      const d = r[p]; if (!d) continue;
      const cy = it.y + (both ? (p === 'IS' ? -5 : 5) : 0), k = d.k || (d.v >= 0 ? 'fast' : 'loss');
      const g = hit(svg, d.tip);
      S(g, 'rect', {x: x0, y: r1(both ? (p === 'IS' ? it.y - rh / 2 : it.y) : it.y - rh / 2), width: r1(x1 - x0), height: both ? rh / 2 : rh, class: 'hb'});
      if (ok(d.lo)) S(g, 'line', {x1: r1(x(d.lo)), x2: r1(x(d.hi)), y1: cy, y2: cy, class: 'wh s-' + k});
      if (ok(d.v)) S(g, 'circle', {cx: r1(x(d.v)), cy, r: 4.5, class: 'mk ' + (p === 'IS' ? 'dot f-' + k : 'ring s-' + k)});
    }
  }
  if (c.xTitle) { const est = c.xTitle.length * 6.1, cx = Math.min(Math.max((x0 + x1) / 2, est / 2 + 2), W - est / 2 - 2);
    S(svg, 'text', {x: r1(cx), y: H - 10, class: 'axt', 'text-anchor': 'middle'}, c.xTitle); }
  return H;
}
const DOT_LEGEND = [['fast', 'dot', 'IS, net > 0'], ['fast', 'ring', 'OOS (burned, non-blind), net > 0'], ['loss', 'dot', 'IS, net < 0'], ['loss', 'ring', 'OOS, net < 0'], ['ink', 'line', '95% CI, match-clustered']];

/* =====================================================================
   HERO
   ===================================================================== */
const A = D.A_source, B = D.B_size, C = D.C_factor_neutral, DW = D.D_where, E = D.E_decay, F = D.F_concentration,
  G = D.G_tier_ladder, HC = D.H_capacity, I = D.I_failures, HD = D.headline, PD = D.page_derived, L = D.labels;
const netStep = p => B[p].waterfall.find(s => /^net \(at/.test(s.step));
const stepAt = (p, re) => B[p].waterfall.find(s => re.test(s.step));
const feeRow = I.rows.find(r => /fees x2/.test(r.test));

(function hero() {
  const nIS = netStep('IS'), nO = netStep('OOS'), cm = C.committed;
  const f4 = (lab, chip, val, sub, href) => h('div', {class: 'f4'},
    h('div', {class: 'lab'}, h('a', {href, style: 'text-decoration:none'}, lab), chip),
    h('div', {class: 'val'}, val), h('div', {class: 'sub'}, sub));
  const trend = E.over_calendar_time.IS_plus_OOS_rows;
  document.getElementById('hero').append(
    h('div', {class: 'kicker'}, h('span', {class: 'sq', 'aria-hidden': 'true'}), h('span', null, 'Courtside · Polymarket tennis match-winner markets'),
      h('span', {class: 'gen'}, 'alpha.json ' + D.generated_utc.replace('T', ' ').replace('Z', ' UTC') + ' · git ' + D.git_head)),
    h('h1', null, 'Courtside Alpha'),
    h('p', {class: 'thesis'}, pretty(HD.one_line)),
    h('div', {class: 'defs-row'},
      h('span', null, h('span', {class: 'chip'}, 'IS'), L.IS),
      h('span', null, h('span', {class: 'chip oos'}, 'OOS'), L.OOS),
      h('span', null, h('span', {class: 'chip h6'}, 'v2'), L.v2_fills)),
    h('div', {class: 'figs4'},
      f4('v2 net, in sample', h('span', {class: 'chip'}, 'IS'),
        [sg(nIS.c_per_share), h('small', null, 'c/share')],
        `95% CI ${ci(nIS.ci95_c_match_clustered)} · ${fx(nIS.bps_of_notional, 0)} bps of notional · ${n0(B.IS.n_trades)} trades. At the fast tier's fills, not our execution.`, '#B'),
      f4('v2 net, burned OOS', h('span', {class: 'chip oos'}, 'non-blind'),
        [sg(nO.c_per_share), h('small', null, 'c/share')],
        `95% CI ${ci(nO.ci95_c_match_clustered)} · ${fx(nO.bps_of_notional, 0)} bps · ${n0(B.OOS.n_trades)} trades over ${B.OOS.days} days. Same fills caveat.`, '#B'),
      f4('Factor alpha t-stat', h('span', {class: 'chip'}, 'FF3 + Mom'),
        [fx(cm.alpha_t, 1), h('small', null, 't')],
        `Alpha ${sg(cm.alpha_pct_per_day, 2)}%/day; largest factor |t| ${fx(cm.max_abs_factor_t, 2)}, R² ${pc(cm.r2)}. ${cm.n_days} weekdays, the last 7 burned OOS; IS-only spec t = ${fx(C.IS_only_calendar_days.alpha_t, 2)}.`, '#C'),
      f4('Months the fast tier won', h('span', {class: 'chip h6'}, 'IS + H6 OOS'),
        [A.IS.months_fast_positive, h('small', null, 'IS'), A.OOS.months_fast_positive, h('small', null, 'OOS')],
        `Net 30 s markout above zero after the fee. Everyone else: ${A.IS.months_others_positive} IS, ${A.OOS.months_others_positive} OOS. Trend ${sg(trend.slope_c_per_month)} c/month.`, '#A')),
    h('div', {class: 'caveats'}, h('h3', null, 'Read it with'),
      h('ul', null,
        h('li', null, h('span', null, h('a', {href: '#I'}, 'Costs'), `: with taker fees doubled, OOS v2 nets ${sg(HD.fees_x2_OOS_c)} c/share (${feeRow ? feeRow.OOS.months_positive : '—'} months positive). A 1 c worse entry gives ${sg(stepAt('OOS', /\+1c/).c_per_share)}.`)),
        h('li', null, h('span', null, h('a', {href: '#F'}, 'Concentration'), `: the top 5 copied wallets carry ${pc(HD.top5_wallet_share_of_pnl.OOS, 0)} of OOS P&L (IS ${pc(HD.top5_wallet_share_of_pnl.IS, 0)}).`)),
        h('li', null, h('span', null, h('a', {href: '#E'}, 'Decay'), `: the fast tier's monthly edge trends ${sg(trend.slope_c_per_month)} c/month (t = ${fx(trend.slope_t)}) as wallets grew ${E.over_calendar_time.wallets_first_to_last.join(' → ')}.`)),
        h('li', null, h('span', null, h('a', {href: '#B'}, 'Luck'), `: OOS deflated Sharpe ${fx(B.luck.OOS_deflated_sharpe_N3386, 3)} at N = 3,386 trials (IS ${fx(B.luck.IS_deflated_sharpe_N3386, 3)}); ${B.OOS.days} OOS days.`)))),
    h('nav', {class: 'toc', 'aria-label': 'Sections'},
      [['A', 'Source'], ['B', 'Size'], ['C', 'Factor-neutral'], ['D', 'Where in the book'], ['E', 'Decay'], ['F', 'Concentration'], ['G', 'Tier ladder'], ['H', 'Capacity'], ['I', 'What fails'], ['sources', 'Sources']]
        .map(([k, n]) => h('a', {href: '#' + k}, h('b', null, k.length === 1 ? k : '→'), n))));
})();

/* =====================================================================
   A  SOURCE
   ===================================================================== */
(function secA() {
  const rows = [...A.IS.months.map(m => ({...m, p: 'IS'})), ...A.OOS.months.map(m => ({...m, p: 'OOS'}))];
  const SER = [['fast_net30_c', 'fast', 'Fast tier', 'net 30 s markout'],
    ['others_net30_c', 'loss', 'Everyone else 0–3 s after detection', 'net 30 s markout'],
    ['copy_3s_later_net_to_resolution_c', 'copy', 'Copy the fast tier 3 s later', 'net to resolution']];
  const short = /Oct 2026 is 3 days/.test(A.note);
  const draw = (svg, W) => {
    const H = 330, m = {t: 58, r: 6, b: 56, l: 40}, x0 = m.l, x1 = W - m.r;
    const vals = rows.flatMap(r => SER.map(s => r[s[0]]));
    const sc = nice(Math.min(0, ...vals), Math.max(0, ...vals), 6), y = lin(sc.lo, sc.hi, H - m.b, m.t);
    const band = (x1 - x0) / rows.length, iO = rows.findIndex(r => r.p !== 'IS');
    S(svg, 'text', {x: 0, y: 12, class: 'axt'}, 'Net c/share after the taker fee');
    if (iO >= 0) S(svg, 'rect', {x: r1(x0 + iO * band), y: m.t - 24, width: r1(band * (rows.length - iO)), height: r1(H - m.b - m.t + 24), class: 'band'});
    S(svg, 'text', {x: x0 + 4, y: m.t - 10, class: 'plab'}, 'IN SAMPLE');
    if (iO >= 0) S(svg, 'text', {x: r1(x0 + iO * band + 6), y: m.t - 10, class: 'plab'}, 'OOS (H6)');
    yTicks(svg, sc, y, x0, x1);
    const bw = Math.min(24, Math.max(3, (band * 0.8 - 4) / 3)), gw = bw * 3 + 4;
    rows.forEach((r, i) => {
      const bx = x0 + i * band + (band - gw) / 2;
      SER.forEach(([k, c, name, hz], j) => {
        const v = r[k], xx = bx + j * (bw + 2);
        const g = hit(svg, `${sg(v)} c/share · ${name}\n${hz} · ${monY(r.month)} · ${r.p === 'IS' ? 'in sample' : 'OOS (H6 held out)'}\n${n0(r.n_prints)} fast-tier prints · ${n0(r.n_wallets)} wallets · ${n0(r.n_matches)} matches`);
        S(g, 'rect', {x: r1(xx - 1), y: m.t, width: r1(bw + 2), height: H - m.b - m.t, class: 'hb'});
        S(g, 'path', {d: vbar(r1(xx), r1(bw), r1(y(0)), r1(y(v))), class: 'mk f-' + c});
      });
      const lx = r1(x0 + i * band + band / 2);
      S(svg, 'text', {x: lx, y: H - m.b + 16, class: 'tick', 'text-anchor': 'middle'}, mon(r.month));
      const yr = band < 34 ? '’' + r.month.slice(2, 4) : r.month.slice(0, 4);
      const second = (i === 0 || r.month.endsWith('-01')) ? yr : (short && r.month === '2026-10' ? (band < 34 ? '3 d' : '3 days') : null);
      if (second) S(svg, 'text', {x: lx, y: H - m.b + 29, class: 'tick', 'text-anchor': 'middle'}, second);
    });
    zeroY(svg, y, x0, x1);
    S(svg, 'text', {x: r1((x0 + x1) / 2), y: H - 6, class: 'axt', 'text-anchor': 'middle'}, W < 520 ? 'Month of match start (Aug split 25 Aug)' : 'Month of match start (August is split at 25 Aug 14:15 UTC)');
    return H;
  };
  const fig = figure({
    title: 'Net c/share by month: the fast tier, everyone else, and a 3 s-late copy',
    legend: [['fast', 'bar', 'Fast tier · net 30 s markout'], ['loss', 'bar', 'Everyone else 0–3 s after detection · net 30 s markout'], ['copy', 'bar', 'Copy the fast tier 3 s later · net to resolution'], ['band', 'band', 'OOS: H6 held-out matches']],
    minW: 330, draw,
    table: () => ({cols: ['Month', 'Period', 'Fast tier net 30 s', 'Everyone else net 30 s', 'Fast − others', 'Fast tier to resolution', 'Copy 3 s later to resolution', 'Wallets', 'Fast-tier prints', 'Matches', 'Fast-tier volume'],
      rows: rows.map(r => [monY(r.month), r.p === 'IS' ? 'IS' : 'OOS (H6)', sg(r.fast_net30_c), sg(r.others_net30_c), sg(r.fast_minus_others_c), sg(r.fast_net_to_resolution_c), sg(r.copy_3s_later_net_to_resolution_c), n0(r.n_wallets), n0(r.n_prints), n0(r.n_matches), usdk(r.volume_usd_k * 1000)])}),
    take: `Fast tier positive in ${A.IS.months_fast_positive} IS and ${A.OOS.months_fast_positive} OOS months; everyone else in ${A.IS.months_others_positive} and ${A.OOS.months_others_positive}; a 3 s-late copy in ${A.IS.months_copy_3s_later_positive} and ${A.OOS.months_copy_3s_later_positive}. Values in c/share; table has all columns.`,
    notes: [pretty(A.note), 'OOS here: ' + A.OOS.label + '.'],
    keys: ['A.IS.months', 'A.OOS.months', 'A.copy_3s_later_note']
  });
  const u = A.unseen_markets_check, pw = p => A[p].print_weighted;
  const facts = kt('Pooled numbers (c/share)', ['Measure', 'IS', 'OOS (H6 held out)'], [
    ['Fast tier, net 30 s markout, weighted by prints', sg(pw('IS').fast_net30_c), sg(pw('OOS').fast_net30_c)],
    ['Fast tier, net to resolution, weighted by prints', sg(pw('IS').fast_net_to_resolution_c), sg(pw('OOS').fast_net_to_resolution_c)],
    ['Everyone else, net 30 s, mean of monthly values', sg(A.IS.unweighted_month_mean.others_net30_c), sg(A.OOS.unweighted_month_mean.others_net30_c)],
    ['Copy 3 s later, net to resolution, weighted by prints', sg(pw('IS').copy_3s_later_net_to_resolution_c), sg(pw('OOS').copy_3s_later_net_to_resolution_c)],
    [u.label + ': fast tier minus others, 95% CI', sg(u.IS_fast_minus_others_c) + ' ' + ci(u.IS_ci95_c), sg(u.OOS_fast_minus_others_c) + ' ' + ci(u.OOS_ci95_c)],
    ['Fast-tier prints · volume', n0(A.IS.fast_tier_prints) + ' · ' + usdk(A.IS.fast_tier_volume_usd_k * 1000), n0(A.OOS.fast_tier_prints) + ' · ' + usdk(A.OOS.fast_tier_volume_usd_k * 1000)]
  ], ['Others are averaged over months because the results file has no per-month count of other takers’ prints.']);
  section('A', 'Source · where the edge comes from',
    `The fast tier is up in ${A.IS.months_fast_positive} IS and ${A.OOS.months_fast_positive} OOS months. Everyone else trading the same jumps is up in ${A.IS.months_others_positive} and ${A.OOS.months_others_positive}.`,
    pretty(A.what), fig, facts, srcLine(['A.IS.print_weighted', 'A.OOS.print_weighted', 'A.unseen.IS', 'A.unseen.OOS']));
})();

/* =====================================================================
   B  SIZE
   ===================================================================== */
(function secB() {
  const XL = [['Gross'], ['Fee'], ['Slip.'], ['Net'], ['Net', '+½c'], ['Net', '+1c']];
  const panel = (g, W, H, p, sc) => {
    const wf = B[p].waterfall, m = {t: 54, r: 4, b: 42, l: 38}, x0 = m.l, x1 = W - m.r;
    S(g, 'text', {x: 0, y: 13, class: 'plab'}, p === 'IS' ? 'IN SAMPLE' : 'BURNED OOS · NON-BLIND');
    S(g, 'text', {x: 0, y: 32, class: 'axt'}, `c per share · ${n0(B[p].n_trades)} trades`);
    const y = lin(sc.lo, sc.hi, H - m.b, m.t);
    yTicks(g, sc, y, x0, x1);
    const n = wf.length, band = (x1 - x0) / n, bw = Math.min(24, band * 0.5), cx = i => x0 + band * i + band / 2;
    let level = 0; const levels = [];
    wf.forEach((s, i) => {
      const v = s.c_per_share, X = cx(i) - bw / 2;
      let a, b, cls;
      if (/fee/.test(s.step)) { a = level; b = level + v; level = b; cls = 'f-loss'; }
      else if (/slippage/.test(s.step)) { a = b = level + v; level = b; cls = null; }
      else if (/^gross/.test(s.step)) { a = 0; b = v; level = v; cls = 'f-fast'; }
      else { a = 0; b = v; cls = (v >= 0 ? 'f-fast' : 'f-loss') + (/stress/.test(s.step) ? ' stress' : ''); }
      levels.push(b);
      const tipTxt = [`${sg(v)} c/share · ${s.step}`, `${PV[p]} · ${sg(s.bps_of_notional, 1)} bps of notional · ${usd(s.usd)}`,
        s.ci95_c_match_clustered ? `95% CI ${ci(s.ci95_c_match_clustered)}, match-clustered` : null,
        ok(s.sharpe_ann) ? `Sharpe ${fx(s.sharpe_ann, 2)} · months positive ${s.months_positive}` : null].filter(Boolean).join('\n');
      const gg = hit(g, tipTxt);
      S(gg, 'rect', {x: r1(X - 8), y: m.t, width: r1(bw + 16), height: H - m.b - m.t, class: 'hb'});
      if (cls) S(gg, 'path', {d: vbar(r1(X), r1(bw), r1(y(a)), r1(y(b))), class: 'mk ' + cls});
      else S(gg, 'line', {x1: r1(X), x2: r1(X + bw), y1: r1(y(a)), y2: r1(y(a)), class: 'slip'});
      const c = s.ci95_c_match_clustered;
      if (c) {
        const xx = r1(cx(i)) + 0.5;
        S(gg, 'line', {x1: xx, x2: xx, y1: r1(y(c[0])), y2: r1(y(c[1])), class: 'wh s-ink'});
        for (const e of c) S(gg, 'line', {x1: xx - 4, x2: xx + 4, y1: r1(y(e)), y2: r1(y(e)), class: 'wh s-ink'});
      }
      const top = Math.max(a, b, c ? c[1] : -Infinity), bot = Math.min(a, b, c ? c[0] : Infinity);
      const above = !/fee/.test(s.step) && v >= 0;
      S(g, 'text', {x: r1(cx(i)), y: above ? r1(y(top)) - 7 : r1(y(bot)) + 15, class: 'vlab', 'text-anchor': 'middle'}, sg(v));
      XL[i].forEach((t, j) => S(g, 'text', {x: r1(cx(i)), y: H - m.b + 16 + j * 13, class: 'tick', 'text-anchor': 'middle'}, t));
    });
    for (let i = 0; i < 3; i++) S(g, 'line', {x1: r1(cx(i) + bw / 2), x2: r1(cx(i + 1) - bw / 2), y1: r1(y(levels[i])) + 0.5, y2: r1(y(levels[i])) + 0.5, class: 'conn'});
    zeroY(g, y, x0, x1);
  };
  const draw = (svg, W) => {
    const side = W >= 700, gap = 32, pw = side ? (W - gap) / 2 : W, ph = 300, all = [];
    for (const p of ['IS', 'OOS']) for (const s of B[p].waterfall) { all.push(s.c_per_share); if (s.ci95_c_match_clustered) all.push(...s.ci95_c_match_clustered); }
    const sc = padded(all, 6, 0.08);
    ['IS', 'OOS'].forEach((p, k) => panel(S(svg, 'g', {transform: side ? `translate(${r1(k * (pw + gap))},0)` : `translate(0,${k * (ph + 26)})`}), pw, ph, p, sc));
    return side ? ph : ph * 2 + 26;
  };
  const nIS = netStep('IS'), nO = netStep('OOS'), s1 = p => stepAt(p, /\+1c/), s05 = p => stepAt(p, /\+0\.5c/);
  const fig = figure({
    title: 'Gross edge → taker fee → net, per share, with entry-price stress',
    legend: [['fast', 'bar', 'Edge or net > 0'], ['loss', 'bar', 'Fee, or net < 0'], ['fast', 'bar light', 'Stress: every entry 0.5 c or 1 c worse'], ['ink', 'line', '95% CI, match-clustered']],
    minW: 320, draw,
    table: () => ({cols: ['Step', 'IS c/share', 'IS 95% CI', 'IS bps', 'IS $', 'OOS c/share', 'OOS 95% CI', 'OOS bps', 'OOS $'],
      rows: B.IS.waterfall.map((s, i) => { const o = B.OOS.waterfall[i]; return [s.step, sg(s.c_per_share), ci(s.ci95_c_match_clustered), sg(s.bps_of_notional, 1), usd(s.usd), sg(o.c_per_share), ci(o.ci95_c_match_clustered), sg(o.bps_of_notional, 1), usd(o.usd)]; })}),
    take: `Net ${sg(nIS.c_per_share)} c IS vs ${sg(nO.c_per_share)} c OOS; with a 0.5 c worse entry ${sg(s05('IS').c_per_share)} vs ${sg(s05('OOS').c_per_share)}, with 1 c worse ${sg(s1('IS').c_per_share)} vs ${sg(s1('OOS').c_per_share)}.`,
    notes: ['v2 is ' + L.v2_fills + '. Slip. = slippage modelled at fast-tier fills, zero because those prints already crossed the spread; the ½c and 1c rows are the committed entry-price stress.', pretty(B.what)],
    keys: ['B.IS.decomposition', 'B.OOS.decomposition', 'B.IS.net_ci', 'B.OOS.net_ci', 'B.IS.slip0.005', 'B.OOS.slip0.005', 'B.IS.slip0.01', 'B.OOS.slip0.01']
  });
  const P = p => B[p], lk = B.luck, gs = B.gross_split_IS_only;
  const facts = kt('Book-level numbers', ['Measure', 'IS', 'OOS (burned, non-blind)'], [
    ['Trades · matches', n0(P('IS').n_trades) + ' · ' + n0(P('IS').n_matches), n0(P('OOS').n_trades) + ' · ' + n0(P('OOS').n_matches)],
    ['Notional traded · average price paid', usd(P('IS').usd_traded) + ' · ' + fx(P('IS').avg_price_per_share * 100, 1) + ' c', usd(P('OOS').usd_traded) + ' · ' + fx(P('OOS').avg_price_per_share * 100, 1) + ' c'],
    ['P&L, 95% CI', usd(P('IS').pnl_usd) + ' [' + usd(P('IS').pnl_ci95_usd[0]) + ', ' + usd(P('IS').pnl_ci95_usd[1]) + ']', usd(P('OOS').pnl_usd) + ' [' + usd(P('OOS').pnl_ci95_usd[0]) + ', ' + usd(P('OOS').pnl_ci95_usd[1]) + ']'],
    ['Days · capital', P('IS').days + ' · ' + usd(P('IS').capital_usd), P('OOS').days + ' · ' + usd(P('OOS').capital_usd)],
    ['Annual return · annual volatility', fx(P('IS').ann_return_pct, 1) + '% · ' + fx(P('IS').ann_vol_pct, 1) + '%', fx(P('OOS').ann_return_pct, 1) + '% · ' + fx(P('OOS').ann_vol_pct, 1) + '%'],
    ['Sharpe (annual), 95% CI', fx(P('IS').sharpe_ann, 2) + ' ' + ci(lk.IS_sharpe_ci95_block_bootstrap), fx(P('OOS').sharpe_ann, 2) + ' ' + ci(lk.OOS_sharpe_ci95_bootstrap)],
    ['Deflated Sharpe, N = 3,386 trials', fx(lk.IS_deflated_sharpe_N3386, 3), fx(lk.OOS_deflated_sharpe_N3386, 3)],
    ['Max drawdown · worst day', fx(P('IS').max_dd_pct, 2) + '% · ' + fx(P('IS').worst_day_pct, 2) + '%', fx(P('OOS').max_dd_pct, 2) + '% · ' + fx(P('OOS').worst_day_pct, 2) + '%'],
    ['Daily skew · turnover', fx(P('IS').skew, 2) + ' · ' + fx(P('IS').turnover_x_per_year, 1) + '×/yr', fx(P('OOS').skew, 2) + ' · ' + fx(P('OOS').turnover_x_per_year, 1) + '×/yr'],
    ['Fee · net edge, bps of notional', fx(P('IS').fee_bps_of_notional_note_metrics, 0) + ' · ' + fx(P('IS').net_edge_bps_of_notional_note_metrics, 1), fx(P('OOS').fee_bps_of_notional_note_metrics, 0) + ' · ' + fx(P('OOS').net_edge_bps_of_notional_note_metrics, 1)],
    ['Months positive', P('IS').months_positive, P('OOS').months_positive]
  ], [pretty(lk.reading) + ' Expected best Sharpe of 3,386 zero-skill trials: ' + fx(lk.OOS_expected_best_of_3386_null_sharpe, 2) + '.',
    'Capital rule: ' + P('IS').capital_rule + '.',
    `Where the IS gross comes from (${gs.label}): ${pc(gs.share_of_gross_from_stale_quote)} of the ${sg(gs.gross_fill_to_resolution_c)} c is the stale quote (fill vs mid 30 s later, ${sg(gs.stale_quote_fill_vs_mid_30s_c)} c: ${sg(gs.of_which_fill_vs_mid_5s_c)} c in the first 5 s, ${sg(gs.of_which_mid_5s_to_mid_30s_c)} c from 5 to 30 s); drift from 30 s to resolution adds ${sg(gs.drift_mid_30s_to_resolution_c)} c ${ci(gs.drift_ci95_c)}.`]);
  section('B', 'Size · how big it is after costs',
    `At the fast tier’s fills, v2 nets ${sg(nIS.c_per_share)} c/share in sample and ${sg(nO.c_per_share)} c on the burned OOS. A 1 c worse entry takes the OOS to ${sg(s1('OOS').c_per_share)}.`,
    'v2 copies fast-tier prints at their own fill prices, so this is the opportunity at their speed, not our execution.',
    fig, facts, srcLine(['B.IS.annualised', 'B.OOS.annualised', 'B.IS.pnl', 'B.OOS.pnl', 'B.luck.IS', 'B.luck.OOS', 'B.luck.dsr', 'B.gross_split_IS']));
})();

/* =====================================================================
   C  FACTOR-NEUTRAL
   ===================================================================== */
(function secC() {
  const cm = C.committed, io = C.IS_only_calendar_days, CI = PD.C_beta_ci95;
  const FAC = [['MktRF', 'Market', 'Mkt − RF'], ['SMB', 'Size', 'SMB'], ['HML', 'Value', 'HML'], ['Mom', 'Momentum', 'Mom']];
  const fig = figure({
    title: 'Factor betas of v2 daily returns, with 95% CI',
    legend: [['fast', 'dot', 'Beta (committed regression)'], ['fast', 'line', '95% CI = beta ± 1.96 × |beta / t|']],
    minW: 300,
    draw: (svg, W) => dotRows(svg, W, {lw: 104, rh: 40, nt: 5,
      rows: FAC.map(([k, name, code]) => ({label: name, IS: {k: 'fast', v: cm.betas[k], lo: CI[k][0], hi: CI[k][1],
        tip: `beta ${sg(cm.betas[k], 3)} · ${name} (${code})\nt = ${fx(cm.betas_t[k], 2)} · 95% CI ${ci(CI[k], 3)}\nCommitted spec, ${cm.n_days} weekdays`}})),
      xTitle: 'Beta (per unit of factor return)'}),
    table: () => ({cols: ['Factor', 'Beta', 't', '95% CI (derived)'], rows: FAC.map(([k, name, code]) => [name + ' (' + code + ')', sg(cm.betas[k], 4), fx(cm.betas_t[k], 2), ci(CI[k], 3)])}),
    take: `Every factor CI spans zero; the largest |t| is ${fx(cm.max_abs_factor_t, 2)} and R² is ${pc(cm.r2)}.`,
    notes: [cm.label + '.', 'The CI is derived on this page from beta and its rounded t (normal approximation).'],
    keys: ['C.committed', 'page_derived.C_beta_ci95']
  });
  const facts = kt('Alpha', ['Measure', 'Committed spec', 'IS only, calendar days'], [
    ['Alpha, % per day', sg(cm.alpha_pct_per_day, 3), sg(io.alpha_pct_per_day, 3)],
    ['Alpha t-stat', fx(cm.alpha_t, 2), fx(io.alpha_t, 2)],
    ['Alpha, annualised', fx(cm.alpha_annualised_pct, 1) + '%', '—'],
    ['R²', pc(cm.r2), pc(io.r2)],
    ['Correlation with the market', fx(cm.corr_with_market, 3), fx(io.corr_with_market, 3)],
    ['Largest factor |t|', fx(cm.max_abs_factor_t, 2), fx(io.max_abs_factor_t, 2)],
    ['Days', cm.n_days + ' weekdays', io.n_days + ' calendar days']
  ], ['Committed: ' + cm.label + '.', 'IS only: ' + io.label + '.']);
  section('C', 'Factor-neutral · is it just market exposure',
    `No equity factor explains the P&L: alpha ${sg(cm.alpha_pct_per_day, 2)}%/day (t = ${fx(cm.alpha_t, 1)}), largest factor |t| = ${fx(cm.max_abs_factor_t, 2)}, R² = ${pc(cm.r2)}.`,
    'Daily v2 returns regressed on the Fama-French three factors plus momentum. If the P&L were disguised market, size, value or momentum exposure, the betas would be large and their intervals would exclude zero.',
    h('div', {class: 'grid2 wide-left'}, fig, facts), srcLine(['C.committed', 'C.IS_only_calendar_days']));
})();

/* =====================================================================
   D  WHERE IN THE BOOK
   ===================================================================== */
(function secD() {
  const cnt = PD.D_counts;
  const pt = (r, p, label) => r ? {v: r.net_c_per_share, lo: r.net_ci95_c_match_clustered[0], hi: r.net_ci95_c_match_clustered[1],
    tip: `${sg(r.net_c_per_share)} c/share net ${ci(r.net_ci95_c_match_clustered)}\n${label} · ${PV[p]}\ngross ${sg(r.gross_c_per_share)} − fee ${fx(r.fee_c_per_share)} · win rate ${pc(r.win_rate)}\n${n0(r.n_trades)} trades · ${n0(r.n_matches)} matches · P&L ${usd(r.pnl_usd)} (${pc(r.share_of_period_pnl)} of period)`} : null;
  const merged = (split, labelOf, sortKey) => {
    const groups = [];
    for (const p of ['IS', 'OOS']) for (const r of DW[p][split]) if (!groups.includes(r.group)) groups.push(r.group);
    if (sortKey) groups.sort(sortKey);
    return groups.map(gk => {
      const ri = DW.IS[split].find(r => r.group === gk), ro = DW.OOS[split].find(r => r.group === gk), lab = labelOf(gk);
      return {label: lab, IS: pt(ri, 'IS', lab), OOS: pt(ro, 'OOS', lab), ri, ro};
    });
  };
  const regimeLabel = g => { const m = /^(\d+)s\/(\d+)%$/.exec(g); return m ? `${m[1]} s delay · ${m[2]}% fee` : g; };
  const tableFor = (rows, first) => ({cols: [first, 'Period', 'Net c/share', '95% CI', 'Gross', 'Fee', 'Win rate', 'Trades', 'Matches', 'P&L', 'Share of period P&L'],
    rows: rows.flatMap(o => ['IS', 'OOS'].map(p => { const r = p === 'IS' ? o.ri : o.ro; return r ? [o.label, p === 'IS' ? 'IS' : 'OOS (burned)', sg(r.net_c_per_share), ci(r.net_ci95_c_match_clustered), sg(r.gross_c_per_share), fx(r.fee_c_per_share), pc(r.win_rate), n0(r.n_trades), n0(r.n_matches), usd(r.pnl_usd), pc(r.share_of_period_pnl)] : null; }).filter(Boolean))});
  const ctxt = (split, unit) => { const a = cnt.IS[split], b = cnt.OOS[split];
    return `IS: net > 0 in ${a.net_positive}/${a.n} ${unit}, CI above zero in ${a.ci_above_zero}. OOS: net > 0 in ${b.net_positive}/${b.n}, CI above zero in ${b.ci_above_zero}, below zero in ${b.ci_below_zero}.`; };

  const zones = merged('by_price_decile_q', dash);
  const fz = figure({
    title: 'Net c/share by price paid (IS price deciles)',
    legend: DOT_LEGEND, minW: 300,
    draw: (svg, W) => dotRows(svg, W, {lw: 84, rows: zones, xTitle: 'Net c/share at fast-tier fills, held to resolution'}),
    table: () => tableFor(zones, 'Price paid ($/share)'),
    take: ctxt('by_price_decile_q', 'zones'),
    notes: ['Rows are the price paid per share in dollars; edges are IS deciles, used for both periods.'],
    keys: ['D.IS', 'D.OOS', 'page_derived.D_counts']
  });
  const regs = merged('by_regime_delay_fee', regimeLabel);
  const oosReg = DW.OOS.by_regime_delay_fee;
  const fr = figure({
    title: 'Net c/share by venue regime (taker delay · fee)',
    legend: DOT_LEGEND, minW: 300,
    draw: (svg, W) => dotRows(svg, W, {lw: 132, rows: regs, xTitle: 'Net c/share at fast-tier fills, held to resolution'}),
    table: () => tableFor(regs, 'Regime'),
    take: `${ctxt('by_regime_delay_fee', 'regimes').split(' OOS:')[0]} OOS ran only under ${oosReg.map(r => regimeLabel(r.group)).join(', ')}: ${oosReg.map(r => sg(r.net_c_per_share) + ' c ' + ci(r.net_ci95_c_match_clustered)).join(', ')}.`,
    notes: ['Regimes in calendar order: the venue moved from a 3 s taker delay with no fee to 1 s with a 5% fee.'],
    keys: ['D.IS', 'D.OOS', 'page_derived.D_counts']
  });

  const SPL = [['by_seconds_since_detection', 'Seconds since detection', 'Seconds since detection', 96, null],
    ['by_direction_vs_jump', 'Direction vs the jump', 'Direction', 124, null],
    ['by_time_of_day_utc', 'Time of day (UTC)', 'Time of day', 96, null],
    ['by_month', 'Month', 'Month', 84, (a, b) => a < b ? -1 : 1]];
  let cur = 0;
  const built = SPL.map(([k, , , , sorter]) => merged(k, k === 'by_month' ? monY : dash, sorter));
  const tabs = h('div', {class: 'tabs', role: 'group', 'aria-label': 'Split'});
  const fo = figure({
    title: 'More splits of the same trades',
    controls: tabs, legend: DOT_LEGEND, minW: 300,
    draw: (svg, W) => dotRows(svg, W, {lw: SPL[cur][3], rows: built[cur], xTitle: 'Net c/share at fast-tier fills, held to resolution'}),
    table: () => ({cols: ['Split', ...tableFor([], 'Group').cols], rows: SPL.flatMap(([k, , lab], i) => tableFor(built[i], '').rows.map(r => [lab, ...r]))}),
    take: () => {
      const k = SPL[cur][0];
      if (k === 'by_seconds_since_detection') {
        const g = (p, gk) => DW[p][k].find(r => r.group === gk) || {};
        return `Detection second (0 s): ${sg(g('IS', '0 s').net_c_per_share)} c IS, ${sg(g('OOS', '0 s').net_c_per_share)} c OOS, ${pc(g('IS', '0 s').share_of_period_pnl, 0)} and ${pc(g('OOS', '0 s').share_of_period_pnl, 0)} of P&L. At 2 s: ${sg(g('IS', '2 s').net_c_per_share)} IS, ${sg(g('OOS', '2 s').net_c_per_share)} OOS.`;
      }
      if (k === 'by_direction_vs_jump') {
        const g = (p, gk) => DW[p][k].find(r => r.group === gk) || {};
        return `With the jump: ${sg(g('IS', 'with the jump').net_c_per_share)} c IS, ${sg(g('OOS', 'with the jump').net_c_per_share)} c OOS (${pc(g('IS', 'with the jump').share_of_period_pnl, 0)} / ${pc(g('OOS', 'with the jump').share_of_period_pnl, 0)} of P&L). Against it: ${sg(g('IS', 'against the jump').net_c_per_share)} / ${sg(g('OOS', 'against the jump').net_c_per_share)}.`;
      }
      return ctxt(k, k === 'by_month' ? 'months' : 'time bands');
    },
    notes: ['The table view lists all four splits.'],
    keys: ['D.IS', 'D.OOS', 'page_derived.D_counts']
  });
  SPL.forEach(([, lab], i) => {
    const b = h('button', {type: 'button', 'aria-pressed': i === 0 ? 'true' : 'false'}, lab);
    b.addEventListener('click', () => { cur = i; tabs.querySelectorAll('button').forEach((x, j) => x.setAttribute('aria-pressed', j === i ? 'true' : 'false')); fo.refresh(); });
    tabs.append(b);
  });
  const W_ = p => DW[p];
  const facts = kt('Win rate and payoff', ['Measure', 'IS', 'OOS (burned, non-blind)'], [
    ['Trade win rate, 95% CI (match-clustered)', pc(W_('IS').trade_win_rate) + ' ' + ci(W_('IS').trade_win_rate_ci95_match_clustered.map(v => v * 100), 1), pc(W_('OOS').trade_win_rate) + ' ' + ci(W_('OOS').trade_win_rate_ci95_match_clustered.map(v => v * 100), 1)],
    ['Share-weighted win rate · average price paid', pc(W_('IS').share_weighted_win_rate) + ' · ' + fx(B.IS.avg_price_per_share * 100, 1) + ' c', pc(W_('OOS').share_weighted_win_rate) + ' · ' + fx(B.OOS.avg_price_per_share * 100, 1) + ' c'],
    ['Average win · loss, c/share', sg(W_('IS').avg_win_c_per_share, 1) + ' · ' + sg(W_('IS').avg_loss_c_per_share, 1), sg(W_('OOS').avg_win_c_per_share, 1) + ' · ' + sg(W_('OOS').avg_loss_c_per_share, 1)],
    ['Average win · loss, $ per trade', usd(W_('IS').avg_win_usd, 2) + ' · ' + usd(W_('IS').avg_loss_usd, 2), usd(W_('OOS').avg_win_usd, 2) + ' · ' + usd(W_('OOS').avg_loss_usd, 2)],
    ['Payoff ratio ($)', fx(W_('IS').payoff_ratio_usd, 3), fx(W_('OOS').payoff_ratio_usd, 3)],
    ['Wins · losses', n0(W_('IS').n_wins) + ' · ' + n0(W_('IS').n_losses), n0(W_('OOS').n_wins) + ' · ' + n0(W_('OOS').n_losses)],
    ['Net c/share, 95% CI', sg(W_('IS').net_c_per_share) + ' ' + ci(W_('IS').net_ci95_c_match_clustered), sg(W_('OOS').net_c_per_share) + ' ' + ci(W_('OOS').net_ci95_c_match_clustered)]
  ], ['IS: ' + pretty(W_('IS').reading_win_rate), 'OOS: ' + pretty(W_('OOS').reading_win_rate), 'Side markets: ' + DW.side_market_type]);
  const zc = cnt.IS.by_price_decile_q, zo = cnt.OOS.by_price_decile_q, rc = cnt.IS.by_regime_delay_fee;
  section('D', 'Where in the book · price, regime, timing',
    `In sample, v2 nets above zero in ${zc.net_positive} of ${zc.n} price zones and ${rc.net_positive} of ${rc.n} fee regimes. On the burned OOS it is ${zo.net_positive} of ${zo.n} zones, with wide intervals.`,
    'v2 is ' + DW.label + '. ' + pretty(DW.what),
    h('div', {class: 'grid2'}, fz, fr), fo, facts);
})();

/* =====================================================================
   E  DECAY
   ===================================================================== */
(function secE() {
  const W1 = E.within_a_point, CT = E.over_calendar_time;
  const XC = {'0 s': 0.5, '1 s': 1.5, '2 s': 2.5, '3-4 s': 4, '5-9 s': 7.5, '10-29 s': 20};
  const binKey = b => b.split(' (')[0];
  const panel = (g, W, H, p, sc) => {
    const w = W1[p], m = {t: 52, r: 76, b: 52, l: 40}, x0 = m.l, x1 = W - m.r;
    S(g, 'text', {x: 0, y: 13, class: 'plab'}, p === 'IS' ? 'IN SAMPLE' : 'BURNED OOS · NON-BLIND');
    S(g, 'text', {x: 0, y: 32, class: 'axt'}, 'Net 30 s markout, c/share');
    const y = lin(sc.lo, sc.hi, H - m.b, m.t), x = lg(0.35, 30, x0, x1);
    yTicks(g, sc, y, x0, W - 6);
    for (const t of [0.5, 1, 2, 5, 10, 20]) {
      const xx = r1(x(t)) + 0.5;
      S(g, 'line', {x1: xx, x2: xx, y1: m.t, y2: H - m.b, class: 'gl'});
      S(g, 'text', {x: xx, y: H - m.b + 16, class: 'tick', 'text-anchor': 'middle'}, String(t));
    }
    const pts = w.rows.filter(r => XC[binKey(r.bin)] != null), base = w.rows.find(r => /^baseline/.test(r.bin));
    const X = r => r1(x(XC[binKey(r.bin)]));
    for (const [s, k] of [['others', 'loss'], ['fast', 'fast']]) {
      const up = pts.map(r => X(r) + ',' + r1(y(r[s].ci95_c[1]))), dn = pts.slice().reverse().map(r => X(r) + ',' + r1(y(r[s].ci95_c[0])));
      S(g, 'polygon', {points: up.concat(dn).join(' '), class: 'ciband f-' + k});
      S(g, 'path', {d: 'M' + pts.map(r => X(r) + ',' + r1(y(r[s].net30_c))).join('L'), class: 'ln s-' + k});
    }
    for (const [s, k, nm] of [['others', 'loss', 'everyone else'], ['fast', 'fast', 'fast tier']]) for (const r of pts) {
      const d = r[s], gg = hit(g, `${sg(d.net30_c)} c/share · ${nm}\n${r.bin} after detection · ${p === 'IS' ? 'in sample' : 'burned OOS, non-blind'}\n95% CI ${ci(d.ci95_c)} · ${n0(d.n)} prints`);
      S(gg, 'circle', {cx: X(r), cy: r1(y(d.net30_c)), r: 11, class: 'hb'});
      S(gg, 'circle', {cx: X(r), cy: r1(y(d.net30_c)), r: 4, class: 'mk dot f-' + k});
    }
    const gx = x1 + 16, bx = x1 + 46;
    S(g, 'line', {x1: gx + 0.5, x2: gx + 0.5, y1: m.t, y2: H - m.b, class: 'sep'});
    if (base) for (const [s, k, dx, nm] of [['fast', 'fast', -7, 'fast tier'], ['others', 'loss', 7, 'everyone else']]) {
      const d = base[s], gg = hit(g, `${sg(d.net30_c)} c/share · ${nm}\n${base.bin} · ${p === 'IS' ? 'in sample' : 'burned OOS, non-blind'}\n95% CI ${ci(d.ci95_c)} · ${n0(d.n)} prints`);
      S(gg, 'rect', {x: bx + dx - 7, y: m.t, width: 14, height: H - m.b - m.t, class: 'hb'});
      S(gg, 'line', {x1: bx + dx, x2: bx + dx, y1: r1(y(d.ci95_c[0])), y2: r1(y(d.ci95_c[1])), class: 'wh s-' + k});
      S(gg, 'circle', {cx: bx + dx, cy: r1(y(d.net30_c)), r: 4, class: 'mk dot f-' + k});
    }
    S(g, 'text', {x: bx, y: H - m.b + 16, class: 'tick', 'text-anchor': 'middle'}, 'no jump');
    S(g, 'text', {x: bx, y: H - m.b + 29, class: 'tick', 'text-anchor': 'middle'}, 'baseline');
    zeroY(g, y, x0, W - 6);
    S(g, 'text', {x: r1((x0 + x1) / 2), y: H - 8, class: 'axt', 'text-anchor': 'middle'}, 'Seconds since jump detection (log scale, bin centres)');
  };
  const draw1 = (svg, W) => {
    const side = W >= 740, gap = 32, pw = side ? (W - gap) / 2 : W, ph = 310, all = [];
    for (const p of ['IS', 'OOS']) for (const r of W1[p].rows) for (const s of ['fast', 'others']) all.push(r[s].net30_c, ...r[s].ci95_c);
    const sc = nice(Math.min(0, ...all), Math.max(0, ...all), 6);
    ['IS', 'OOS'].forEach((p, k) => panel(S(svg, 'g', {transform: side ? `translate(${r1(k * (pw + gap))},0)` : `translate(0,${k * (ph + 26)})`}), pw, ph, p, sc));
    return side ? ph : ph * 2 + 26;
  };
  const pre = p => W1[p].decay_test_prereg;
  const f1 = figure({
    title: 'Within a point: net 30 s markout by seconds since the jump was detected',
    legend: [['fast', 'line', 'Fast tier'], ['loss', 'line', 'Everyone else'], ['ink', 'band', 'Shaded: 95% CI, match-clustered']],
    minW: 320, draw: draw1,
    table: () => ({cols: ['Bin', 'Period', 'Fast tier', 'Fast 95% CI', 'Fast prints', 'Everyone else', 'Others 95% CI', 'Others prints', 'All prints', 'With the jump'],
      rows: ['IS', 'OOS'].flatMap(p => W1[p].rows.map(r => [r.bin, p === 'IS' ? 'IS' : 'OOS (burned)', sg(r.fast.net30_c), ci(r.fast.ci95_c), n0(r.fast.n), sg(r.others.net30_c), ci(r.others.ci95_c), n0(r.others.n), sg(r.all.net30_c), sg(r.with_jump.net30_c)]))}),
    take: pretty(W1.reading),
    notes: [pretty(W1.resolution_note) + ' Empty bins: ' + W1.empty_bins.map(b => b.replace('-', '–') + ' s').join(', ') + '.',
      `Pre-registered decay test (with-jump prints at 1 s minus at 10–29 s): IS ${sg(pre('IS').stat_c)} c ${ci(pre('IS').ci_c)}, decays: ${pre('IS').decays ? 'yes' : 'no'}; OOS ${sg(pre('OOS').stat_c)} c ${ci(pre('OOS').ci_c)}, decays: ${pre('OOS').decays ? 'yes' : 'no'}.`,
      `Prints: IS ${n0(W1.IS.prints)} (${n0(W1.IS.matches)} matches); ${W1.OOS.label}: ${n0(W1.OOS.prints)} (${n0(W1.OOS.matches)} matches). ${pretty(W1.what)}`],
    keys: ['E.within_a_point']
  });

  const fastRows = [...A.IS.months.map(m => ({...m, p: 'IS'})), ...A.OOS.months.map(m => ({...m, p: 'OOS'}))];
  const v2Rows = [...CT.v2_monthly_net_c.IS.map(m => ({...m, p: 'IS'})), ...CT.v2_monthly_net_c.OOS.map(m => ({...m, p: 'OOS'}))];
  const tl_ = PD.E_trend_line, iMax = Math.max(...fastRows.map(r => mi(r.month)), ...v2Rows.map(r => mi(r.month)));
  const dup = rows => { const c = {}; rows.forEach(r => { c[r.month] = (c[r.month] || 0) + 1; }); return r => c[r.month] > 1 ? (r.p === 'IS' ? -5 : 5) : 0; };
  const monthAxis = (g, x, H, m) => { const narrow = x(1) - x(0) < 34; for (let i = 0; i <= iMax; i++) { const xx = r1(x(i)), mm = (i + 11) % 12;
    S(g, 'text', {x: xx, y: H - m.b + 16, class: 'tick', 'text-anchor': 'middle'}, MON[mm]);
    if (i === 0 || mm === 0) { const yv = String(2025 + Math.floor((i + 11) / 12)); S(g, 'text', {x: xx, y: H - m.b + 29, class: 'tick', 'text-anchor': 'middle'}, narrow ? '’' + yv.slice(2) : yv); } } };
  const panelA = (g, W, H) => {
    const m = {t: 52, r: 8, b: 50, l: 40}, x0 = m.l, x1 = W - m.r, x = lin(-0.5, iMax + 0.5, x0, x1), off = dup(fastRows);
    S(g, 'text', {x: 0, y: 13, class: 'plab'}, 'FAST TIER · NET 30 S MARKOUT');
    S(g, 'text', {x: 0, y: 32, class: 'axt'}, 'c/share, by month');
    const sc = nice(0, Math.max(...fastRows.map(r => r.fast_net30_c)), 5), y = lin(sc.lo, sc.hi, H - m.b, m.t);
    yTicks(g, sc, y, x0, x1);
    S(g, 'line', {x1: r1(x(tl_.month_index[0])), x2: r1(x(tl_.month_index[1])), y1: r1(y(tl_.fitted_c[0])), y2: r1(y(tl_.fitted_c[1])), class: 'trend'});
    for (const r of fastRows) {
      const cx = r1(x(mi(r.month)) + off(r)), cy = r1(y(r.fast_net30_c));
      const gg = hit(g, `${sg(r.fast_net30_c)} c/share · fast tier, net 30 s\n${monY(r.month)} · ${r.p === 'IS' ? 'in sample' : 'OOS (H6 held out)'}\n${n0(r.n_wallets)} wallets · ${n0(r.n_prints)} prints`);
      S(gg, 'circle', {cx, cy, r: 11, class: 'hb'});
      S(gg, 'circle', {cx, cy, r: 4.5, class: 'mk ' + (r.p === 'IS' ? 'dot f-fast' : 'ring s-fast')});
    }
    monthAxis(g, x, H, m); zeroY(g, y, x0, x1);
    S(g, 'text', {x: r1((x0 + x1) / 2), y: H - 6, class: 'axt', 'text-anchor': 'middle'}, 'Month of match start');
  };
  const panelB = (g, W, H) => {
    const m = {t: 52, r: 8, b: 50, l: 40}, x0 = m.l, x1 = W - m.r, x = lin(-0.5, iMax + 0.5, x0, x1), off = dup(v2Rows);
    S(g, 'text', {x: 0, y: 13, class: 'plab'}, 'V2 · NET TO RESOLUTION AT FAST-TIER FILLS');
    S(g, 'text', {x: 0, y: 32, class: 'axt'}, 'c/share, by month, 95% CI');
    const vals = v2Rows.flatMap(r => [r.net_c_per_share, ...r.ci95]), sc = nice(Math.min(0, ...vals), Math.max(0, ...vals), 5), y = lin(sc.lo, sc.hi, H - m.b, m.t);
    yTicks(g, sc, y, x0, x1);
    const first = v2Rows.reduce((a, r) => r.month < a ? r.month : a, '9999');
    if (mi(first) > 0) S(g, 'text', {x: r1(x0 + 4), y: r1(y(sc.hi) + 14), class: 'rsub'}, 'v2 starts ' + monY(first));
    for (const r of v2Rows) {
      const k = r.net_c_per_share >= 0 ? 'fast' : 'loss', cx = r1(x(mi(r.month)) + off(r));
      const gg = hit(g, `${sg(r.net_c_per_share)} c/share · v2 net\n${monY(r.month)} · ${PV[r.p]}\n95% CI ${ci(r.ci95)}`);
      S(gg, 'rect', {x: cx - 8, y: m.t, width: 16, height: H - m.b - m.t, class: 'hb'});
      S(gg, 'line', {x1: cx, x2: cx, y1: r1(y(r.ci95[0])), y2: r1(y(r.ci95[1])), class: 'wh s-' + k});
      S(gg, 'circle', {cx, cy: r1(y(r.net_c_per_share)), r: 4.5, class: 'mk ' + (r.p === 'IS' ? 'dot f-' + k : 'ring s-' + k)});
    }
    monthAxis(g, x, H, m); zeroY(g, y, x0, x1);
    S(g, 'text', {x: r1((x0 + x1) / 2), y: H - 6, class: 'axt', 'text-anchor': 'middle'}, 'Month of match start');
  };
  const draw2 = (svg, W) => {
    const side = W >= 740, gap = 32, pw = side ? (W - gap) / 2 : W, ph = 290;
    panelA(S(svg, 'g', {}), pw, ph);
    panelB(S(svg, 'g', {transform: side ? `translate(${r1(pw + gap)},0)` : `translate(0,${ph + 26})`}), pw, ph);
    return side ? ph : ph * 2 + 26;
  };
  const tr = CT.IS_plus_OOS_rows, ti = CT.IS_months;
  const f2 = figure({
    title: 'Across the calendar: the fast tier’s edge and v2’s net, month by month',
    legend: [['fast', 'dot', 'IS month'], ['fast', 'ring', 'OOS month (fast tier: H6 held out; v2: burned, non-blind)'], ['loss', 'dot', 'Net < 0'], ['ink', 'line', `OLS trend, all ${tr.n_points} rows: ${sg(tr.slope_c_per_month)} c/month`]],
    minW: 320, draw: draw2,
    table: () => ({cols: ['Month', 'Period', 'Fast tier net 30 s', 'Wallets', 'v2 net c/share', 'v2 95% CI'],
      rows: [...new Set([...fastRows, ...v2Rows].map(r => r.month + '|' + r.p))].sort().map(key => { const [mo, p] = key.split('|'); const f = fastRows.find(r => r.month === mo && r.p === p), v = v2Rows.find(r => r.month === mo && r.p === p);
        return [monY(mo), p === 'IS' ? 'IS' : 'OOS', f ? sg(f.fast_net30_c) : '—', f ? n0(f.n_wallets) : '—', v ? sg(v.net_c_per_share) : '—', v ? ci(v.ci95) : '—']; })}),
    take: `Fitted trend ${sg(tr.slope_c_per_month)} c/month (t = ${fx(tr.slope_t)}) over all ${tr.n_points} rows, ${sg(ti.slope_c_per_month)} c/month (t = ${fx(ti.slope_t)}) over IS months only; qualifying wallets grew from ${CT.wallets_first_to_last[0]} to ${CT.wallets_first_to_last[1]}.`,
    notes: [pretty(CT.reading), pretty(CT.what) + ' ' + tr.note + '.'],
    keys: ['E.over_calendar_time', 'page_derived.E_trend_line']
  });
  section('E', 'Decay · within a point and across months',
    `The edge sits in the detection second, and month by month it is shrinking: ${sg(tr.slope_c_per_month)} c/month (t = ${fx(tr.slope_t)}).`,
    null, f1, f2);
})();

/* =====================================================================
   F  CONCENTRATION
   ===================================================================== */
(function secF() {
  const U = [['wallets', 'wallet', 'wallets', 'Copied wallets'], ['matches', 'match', 'matches', 'Matches'], ['days', 'day', 'days', 'Days']];
  const rows = U.flatMap(([k, one, many, title]) => [{group: `${title.toUpperCase()} · ${n0(F.IS[k].n)} IS · ${n0(F.OOS[k].n)} OOS`},
    ...[1, 5, 10].map(n => { const lab = `Top ${n} ${n === 1 ? one : many}`;
      const mk = p => ({k: 'fast', v: F[p][k]['top' + n + '_share_of_pnl'] * 100,
        tip: `${pc(F[p][k]['top' + n + '_share_of_pnl'])} of ${p === 'IS' ? 'IS' : 'OOS'} P&L (${usd(F[p].total_pnl_usd)})\n${lab} · ${PV[p]}\n${F[p][k].n} ${many}, ${F[p][k].n_positive} with positive P&L`});
      return {label: lab, IS: mk('IS'), OOS: mk('OOS')}; })]);
  const fig = figure({
    title: 'Share of v2 P&L carried by the top 1, 5 and 10 wallets, matches and days',
    legend: [['fast', 'dot', 'IS'], ['fast', 'ring', 'OOS (burned, non-blind)'], ['ink', 'line', '100% = the whole period’s P&L']],
    minW: 300,
    draw: (svg, W) => dotRows(svg, W, {lw: 116, rows, ref: {v: 100, label: '100% of the period’s P&L'}, fmt: v => v + '%', xTitle: 'Share of the period’s v2 P&L (%)'}),
    table: () => ({cols: ['Unit', 'Top k', 'IS share of P&L', 'OOS share of P&L'], rows: U.flatMap(([k, , , title]) => [1, 5, 10].map(n => [title, 'Top ' + n, pc(F.IS[k]['top' + n + '_share_of_pnl']), pc(F.OOS[k]['top' + n + '_share_of_pnl'])]))}),
    take: `Top 5 wallets: ${pc(F.IS.wallets.top5_share_of_pnl, 0)} of IS P&L, ${pc(F.OOS.wallets.top5_share_of_pnl, 0)} of OOS P&L. Top 5 matches: ${pc(F.IS.matches.top5_share_of_pnl, 1)} and ${pc(F.OOS.matches.top5_share_of_pnl, 1)}.`,
    notes: ['v2 is ' + F.label + '. ' + pretty(F.what)],
    keys: ['F.IS', 'F.OOS']
  });
  const P = p => F[p], ex = p => F[p].wallets.ex_top5_wallets;
  const facts = kt('Without the top wallets', ['Measure', 'IS', 'OOS (burned, non-blind)'], [
    ['Period P&L', usd(P('IS').total_pnl_usd), usd(P('OOS').total_pnl_usd)],
    ['Copied wallets · with positive P&L', P('IS').wallets.n + ' · ' + P('IS').wallets.n_positive, P('OOS').wallets.n + ' · ' + P('OOS').wallets.n_positive],
    ['Top wallet P&L', usd(P('IS').wallets.top1_pnl_usd), usd(P('OOS').wallets.top1_pnl_usd)],
    ['Fewest wallets reaching 100% of P&L', P('IS').wallets.fewest_units_reaching_100pct_of_pnl, P('OOS').wallets.fewest_units_reaching_100pct_of_pnl],
    ['Without the top 5 wallets: net c/share, 95% CI', sg(ex('IS').net_c_per_share) + ' ' + ci(ex('IS').ci95_c_match_clustered), sg(ex('OOS').net_c_per_share) + ' ' + ci(ex('OOS').ci95_c_match_clustered)],
    ['Without the top 5: trades · share of trades · P&L', n0(ex('IS').n_trades) + ' · ' + pc(ex('IS').share_of_trades) + ' · ' + usd(ex('IS').pnl_usd), n0(ex('OOS').n_trades) + ' · ' + pc(ex('OOS').share_of_trades) + ' · ' + usd(ex('OOS').pnl_usd)],
    ['Net c/share, 95% CI clustered by wallet', ci(F.wallet_clustered_ci95_c.IS), ci(F.wallet_clustered_ci95_c.OOS)],
    ['Matches with positive P&L · fewest reaching 100%', n0(P('IS').matches.n_positive) + '/' + n0(P('IS').matches.n) + ' · ' + P('IS').matches.fewest_units_reaching_100pct_of_pnl, n0(P('OOS').matches.n_positive) + '/' + n0(P('OOS').matches.n) + ' · ' + P('OOS').matches.fewest_units_reaching_100pct_of_pnl],
    ['Days with positive P&L · fewest reaching 100%', P('IS').days.n_positive + '/' + P('IS').days.n + ' · ' + P('IS').days.fewest_units_reaching_100pct_of_pnl, P('OOS').days.n_positive + '/' + P('OOS').days.n + ' · ' + P('OOS').days.fewest_units_reaching_100pct_of_pnl]
  ]);
  section('F', 'Concentration · how many wallets carry it',
    `On the burned OOS, the top 5 of ${F.OOS.wallets.n} copied wallets carry ${pc(F.OOS.wallets.top5_share_of_pnl, 0)} of P&L; without them v2 nets ${sg(ex('OOS').net_c_per_share)} c/share.`,
    pretty(F.reading), fig, facts, srcLine(['F.wallet_clustered_ci95_c']));
})();

/* =====================================================================
   shared row-strip chart (ladder and failures)
   ===================================================================== */
function stripRows(rows, axisTitle, axisNote) {
  const vals = rows.flatMap(r => r.pts.flatMap(d => [d.v, ...(d.ci || [])])).filter(ok);
  const sc = nice(Math.min(0, ...vals), Math.max(0, ...vals), 6);
  const box = h('div', {class: 'ladder'}), strips = [];
  for (const r of rows) {
    const cell = h('div', {class: 'lplot'});
    if (r.pts.length) { const svg = S(null, 'svg', {role: 'img', 'aria-label': r.aria}); cell.append(svg); strips.push([svg, r]); }
    else cell.append(h('p', {class: 'lnote'}, r.empty));
    box.append(h('div', {class: 'lrow'}, r.meta, cell));
  }
  const axCell = h('div', {class: 'lplot'}), axSvg = S(null, 'svg', {'aria-hidden': 'true'});
  axCell.append(axSvg);
  box.append(h('div', {class: 'lrow laxis'}, h('div', {class: 'lmeta'}, axisNote), axCell));
  const redraw = () => {
    const W = Math.floor(axCell.clientWidth); if (!W) return;
    const x = lin(sc.lo, sc.hi, 22, W - 22);
    for (const [svg, r] of strips) {
      svg.textContent = '';
      const bh = r.bars ? 12 : 10, gap = 6, pad = 8, n = r.pts.length, H = pad * 2 + n * bh + (n - 1) * gap;
      svg.setAttribute('width', W); svg.setAttribute('height', H); svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
      for (const v of sc.t) if (Math.abs(v) > 1e-9) { const xx = r1(x(v)) + 0.5; S(svg, 'line', {x1: xx, x2: xx, y1: 0, y2: H, class: 'gl'}); }
      r.pts.forEach((d, j) => {
        const y0 = pad + j * (bh + gap), cy = y0 + bh / 2, k = (ok(d.v) ? d.v : (d.ci[0] + d.ci[1]) / 2) >= 0 ? 'fast' : 'loss';
        const g = hit(svg, d.tip);
        S(g, 'rect', {x: 0, y: y0 - gap / 2, width: W, height: bh + gap, class: 'hb'});
        if (r.bars && ok(d.v)) S(g, 'path', {d: hbar(y0, bh, r1(x(0)), r1(x(d.v)), 3), class: 'mk f-' + k + (d.p === 'OOS' ? ' tint s-' + k : '')});
        if (d.ci) {
          S(g, 'line', {x1: r1(x(d.ci[0])), x2: r1(x(d.ci[1])), y1: cy, y2: cy, class: 'wh ' + (r.bars ? 's-ink' : 's-' + k)});
          if (r.bars) for (const e of d.ci) S(g, 'line', {x1: r1(x(e)), x2: r1(x(e)), y1: cy - 4, y2: cy + 4, class: 'wh s-ink'});
        }
        if (!r.bars && ok(d.v)) S(g, 'circle', {cx: r1(x(d.v)), cy, r: 4.5, class: 'mk ' + (d.p === 'OOS' ? 'ring s-' + k : 'dot f-' + k)});
        const ref = ok(d.v) ? d.v : (d.ci[0] + d.ci[1]) / 2, lo = Math.min(0, ref, d.ci ? d.ci[0] : 0), hi = Math.max(0, ref, d.ci ? d.ci[1] : 0);
        const txt = d.short + ' ' + (ok(d.v) ? sg(d.v) : ci(d.ci)), right = ref < 0, est = txt.length * 6.4;
        let tx = right ? r1(x(hi)) + 7 : r1(x(lo)) - 7, anchor = right ? 'start' : 'end';
        if (anchor === 'end' && tx - est < 0) { tx = r1(x(hi)) + 7; anchor = 'start'; }
        if (anchor === 'start' && tx + est > W) { tx = r1(x(lo)) - 7; anchor = 'end'; }
        S(svg, 'text', {x: tx, y: cy + 3.8, class: 'vlab', 'text-anchor': anchor}, txt);
      });
      const zz = r1(x(0)) + 0.5; S(svg, 'line', {x1: zz, x2: zz, y1: 0, y2: H, class: 'z'});
    }
    axSvg.textContent = '';
    const H = 38; axSvg.setAttribute('width', W); axSvg.setAttribute('height', H); axSvg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    for (const v of sc.t) S(axSvg, 'text', {x: r1(x(v)), y: 12, class: 'tick', 'text-anchor': 'middle'}, tl(v, sc.dec));
    S(axSvg, 'text', {x: r1(W / 2), y: 31, class: 'axt', 'text-anchor': 'middle'}, axisTitle);
  };
  return {el: box, redraw};
}

/* =====================================================================
   G  TIER LADDER
   ===================================================================== */
(function secG() {
  const rows = G.rows.map(r => {
    const cf = /counterfactual/i.test(r.label);
    let pts = [];
    const mk = (p, v, c, short) => ({p, v, ci: c, short,
      tip: `${sg(v)} c/share net · ${short}${c ? ' · 95% CI ' + ci(c) : ''}\n${r.tier}\nhorizon: ${r.horizon || '—'}${cf ? '\nCounterfactual: assumes licensed feed + courtside camera (not purchased)' : ''}`});
    if (r.net_c_all_calls) pts = ['IS', 'OOS'].map(p => mk(p, r.net_c_all_calls[p], r.net_ci95_c_all_calls && r.net_ci95_c_all_calls[p], p));
    else if (typeof r.net_c === 'number') pts = [mk('LIVE', r.net_c, null, 'live day')];
    else if (r.net_c) { const c = r.net_ci95_c || r.ci95_c || {}; pts = ['IS', 'OOS'].map(p => mk(p, r.net_c[p], c[p], p)); }
    const extra = [];
    if (cf) extra.push(`Correct calls only: gross vs new mid ${sg(r.gross_c_correct_calls_vs_new_mid.IS)} IS / ${sg(r.gross_c_correct_calls_vs_new_mid.OOS)} OOS, net ${sg(r.net_c_correct_calls.IS)} / ${sg(r.net_c_correct_calls.OOS)}. Wrong calls ${pc(r.wrong_call_share_of_trades.IS)} / ${pc(r.wrong_call_share_of_trades.OOS)} of trades; ${usd(r.usd_per_day.IS, 2)} / ${usd(r.usd_per_day.OOS, 2)} per day.`);
    if (typeof r.net_c === 'number') extra.push(`Gross ${sg(r.gross_c)}, net ${sg(r.net_c)} on ${r.n_prints} prints; all points: gross ${sg(r.all_points.gross_c)}, net ${sg(r.all_points.net_c)}, ${r.all_points.n_prints} prints.`);
    if (r.months_positive) extra.push(`Months positive: ${r.months_positive.IS} IS, ${r.months_positive.OOS} OOS.`);
    const meta = h('div', {class: 'lmeta'},
      h('div', {class: 'lname'}, r.tier),
      h('div', {class: 'lsub'}, cf ? h('span', {class: 'chip cf'}, 'Counterfactual') : null, h('span', null, r.label + (r.horizon ? ' · horizon: ' + r.horizon : ''))),
      extra.length ? h('div', {class: 'lvals'}, extra.join(' ')) : null,
      cf && r.sign_flip ? h('div', {class: 'lwarn'}, h('span', null, pretty(r.sign_flip))) : null);
    return {meta, pts, bars: true, aria: r.tier, r,
      empty: r.reading ? pretty(r.reading) + ` Book first on ${pc(r.share_book_first)} of ${r.n_points} points (median lead ${fx(r.book_leads_public_score_median_s, 2)} s); max calibration edge ${fx(r.calibration_max_abs_edge_c.IS, 2)} c IS, ${fx(r.calibration_max_abs_edge_c.OOS, 2)} c OOS.` : 'No per-share figure.'};
  });
  const strip = stripRows(rows, 'Net c/share (horizon stated per row)', 'Fastest at the top. Solid = IS or live day, tinted = OOS.');
  const copy = G.rows.find(r => /3 s later/.test(r.tier)), t0 = G.rows[0], ft = G.rows.find(r => /walk-forward/.test(r.tier));
  const fig = figure({
    title: 'Who earns what, fastest to slowest',
    legend: [['fast', 'bar', 'IS (or live day), net > 0'], ['fast', 'tint', 'OOS, net > 0'], ['loss', 'bar', 'IS, net < 0'], ['loss', 'tint', 'OOS, net < 0'], ['ink', 'line', '95% CI where available']],
    custom: strip,
    table: () => ({cols: ['Tier', 'Label', 'Horizon', 'IS or live net', 'IS 95% CI', 'OOS net', 'OOS 95% CI', 'Detail', 'Source'], wrapCols: [1, 7, 8],
      rows: rows.map(o => { const r = o.r, a = o.pts.find(d => d.p !== 'OOS'), b = o.pts.find(d => d.p === 'OOS');
        return [r.tier, r.label, r.horizon || '—', a ? sg(a.v) + (a.p === 'LIVE' ? ' (live day)' : '') : '—', a && a.ci ? ci(a.ci) : '', b ? sg(b.v) : '—', b && b.ci ? ci(b.ci) : '',
          o.pts.length ? [o.meta.querySelector('.lvals') ? o.meta.querySelector('.lvals').textContent : '', r.sign_flip ? pretty(r.sign_flip) : ''].join(' ').trim() : o.empty, r.sources]; })}),
    take: `Tier 0 (counterfactual) ${sg(t0.net_c_all_calls.IS)} IS / ${sg(t0.net_c_all_calls.OOS)} OOS and the fast tier ${sg(ft.net_c.IS)} / ${sg(ft.net_c.OOS)} are positive; copying 3 s later is ${sg(copy.net_c.IS)} / ${sg(copy.net_c.OOS)}.`,
    notes: ['Tier 0 is ' + L.tier0 + '. OOS for the tier-0 and v2 rows is the burned, non-blind OOS; for the fast-tier rows it is the H6 held-out read.', pretty(G.what)],
    keys: G.rows.map((_, i) => 'G.rows[' + i + ']')
  });
  section('G', 'Tier ladder · who earns what',
    `Only the fastest tiers earn. Copying the fast tier 3 s later, which is our speed today, nets ${sg(copy.net_c.IS)} c IS and ${sg(copy.net_c.OOS)} c OOS.`,
    null, fig);
})();

/* =====================================================================
   H  CAPACITY
   ===================================================================== */
(function secH() {
  const R = HC.rows, ce = HC.capacity_estimate;
  const all = R.flatMap(r => [r.IS.pnl_usd_per_day, r.OOS.pnl_usd_per_day]), top = Math.max(...all), floor = -top / 2;
  const inR = all.filter(v => v >= floor), sc = nice(Math.min(0, ...inR) - top * 0.06, top * 1.14, 5);
  const caps = R.flatMap(r => [r.IS.capital_usd, r.OOS.capital_usd]), xs = [Math.min(...caps) * 0.75, Math.max(...caps) * 1.25];
  const sz = s => s === 'all prints' ? 'all' : s.replace('x', '×');
  const panel = (g, W, H, p) => {
    const m = {t: 54, r: 18, b: 50, l: 50}, x0 = m.l, x1 = W - m.r, y = lin(sc.lo, sc.hi, H - m.b, m.t), x = lg(xs[0], xs[1], x0, x1);
    S(g, 'text', {x: 0, y: 13, class: 'plab'}, p === 'IS' ? 'IN SAMPLE' : 'BURNED OOS · NON-BLIND');
    S(g, 'text', {x: 0, y: 32, class: 'axt'}, 'v2 P&L, $ per day');
    yTicks(g, sc, y, x0, x1, v => (v < 0 ? MINUS : '') + '$' + Math.abs(v));
    for (const t of [1e4, 2e4, 5e4, 1e5, 2e5, 5e5, 1e6]) if (t >= xs[0] && t <= xs[1]) {
      const xx = r1(x(t)) + 0.5;
      S(g, 'line', {x1: xx, x2: xx, y1: m.t, y2: H - m.b, class: 'gl'});
      S(g, 'text', {x: xx, y: H - m.b + 16, class: 'tick', 'text-anchor': 'middle'}, '$' + (t >= 1e6 ? t / 1e6 + 'M' : t / 1e3 + 'k'));
    }
    const pts = R.map(r => ({size: r.size, d: r[p]})), cy = v => r1(y(Math.max(sc.lo, v)));
    S(g, 'path', {d: 'M' + pts.map(o => r1(x(o.d.capital_usd)) + ',' + cy(o.d.pnl_usd_per_day)).join('L'), class: 'ln s-ink', 'stroke-width': 1.5});
    for (const o of pts) {
      const v = o.d.pnl_usd_per_day, off = v < sc.lo, k = v >= 0 ? 'fast' : 'loss', px = r1(x(o.d.capital_usd)), py = cy(v);
      const gg = hit(g, `${usd(v, 2)} per day · size ${sz(o.size)}\n${PV[p]} · capital ${usd(o.d.capital_usd)} · notional ${usd(o.d.notional_usd_per_day)}/day\n${sg(o.d.per_share_c)} c/share ${ci(o.d.per_share_ci95_c)} · Sharpe ${fx(o.d.sharpe_ann, 2)} · max DD ${fx(o.d.max_dd_pct, 2)}%\n${n0(o.d.n_trades)} trades`);
      S(gg, 'circle', {cx: px, cy: py, r: 13, class: 'hb'});
      if (off) S(gg, 'path', {d: `M${px - 6},${py - 9}L${px + 6},${py - 9}L${px},${py}Z`, class: 'mk f-loss'});
      else S(gg, 'circle', {cx: px, cy: py, r: 5, class: 'mk dot f-' + k});
      const lab = sz(o.size), est = lab.length * 6.4;
      const anchor = px + est / 2 > W ? 'end' : px - est / 2 < 0 ? 'start' : 'middle';
      S(g, 'text', {x: anchor === 'end' ? W - 2 : anchor === 'start' ? 2 : px, y: py - (off ? 14 : 10), class: 'vlab', 'text-anchor': anchor}, lab);
      if (off) S(g, 'text', {x: x1, y: m.t + 4, class: 'rsub', 'text-anchor': 'end'}, '▼ ' + sz(o.size) + ': ' + usd(v) + '/day, below the axis');
    }
    zeroY(g, y, x0, x1);
    S(g, 'text', {x: r1((x0 + x1) / 2), y: H - 8, class: 'axt', 'text-anchor': 'middle'}, 'Capital required, $ (log scale)');
  };
  const draw = (svg, W) => {
    const side = W >= 720, gap = 32, pw = side ? (W - gap) / 2 : W, ph = 290;
    ['IS', 'OOS'].forEach((p, k) => panel(S(svg, 'g', {transform: side ? `translate(${r1(k * (pw + gap))},0)` : `translate(0,${k * (ph + 26)})`}), pw, ph, p));
    return side ? ph : ph * 2 + 26;
  };
  const fig = figure({
    title: 'v2 $ per day against the capital it needs, at 0.5× to 5× size and copying every print',
    legend: [['fast', 'dot', '$ per day > 0'], ['loss', 'dot', '$ per day < 0 (triangle: below the axis)'], ['ink', 'line', 'Sizes in order: 0.5×, 1×, 2×, 5×, all prints']],
    minW: 320, draw,
    table: () => ({cols: ['Size', 'Period', '$ per day', 'c/share', '95% CI', 'Capital', 'Notional per day', 'Sharpe', 'Max DD', 'Trades'],
      rows: R.flatMap(r => ['IS', 'OOS'].map(p => [sz(r.size), p === 'IS' ? 'IS' : 'OOS (burned)', usd(r[p].pnl_usd_per_day, 2), sg(r[p].per_share_c), ci(r[p].per_share_ci95_c), usd(r[p].capital_usd), usd(r[p].notional_usd_per_day), fx(r[p].sharpe_ann, 2), fx(r[p].max_dd_pct, 2) + '%', n0(r[p].n_trades)]))}),
    take: 'OOS $ per day by size: ' + R.map(r => sz(r.size) + ' ' + usd(r.OOS.pnl_usd_per_day)).join(', ') + '. IS: ' + R.map(r => sz(r.size) + ' ' + usd(r.IS.pnl_usd_per_day)).join(', ') + '.',
    notes: [pretty(HC.what), HC.label + '.'],
    keys: ['H.rows']
  });
  const facts = kt('Capacity', ['Measure', 'IS', 'OOS (burned, non-blind)'], [
    ['Capacity: capital from 1× (OOS $/day peak) to 2× (largest size still positive)', '—', usd(ce.OOS_capital_usd_range[0]) + '–' + usd(ce.OOS_capital_usd_range[1])],
    ['Outer ceiling: every fast-tier print, $ per day', usd(ce.outer_ceiling_fast_tier_print_usd_per_day.IS), usd(ce.outer_ceiling_fast_tier_print_usd_per_day.OOS)],
    ['v2 share of match volume', pc(ce.v2_share_of_match_volume_IS, 3), '—']
  ], [pretty(ce.statement), 'Superseded: ' + pretty(ce.superseded)]);
  section('H', 'Capacity · how much money it can take',
    pretty(ce.statement), null, fig, facts, srcLine(['H.capacity_estimate']));
})();

/* =====================================================================
   I  WHAT FAILS
   ===================================================================== */
(function secI() {
  const vcls = v => /pending/i.test(v) ? 'pend' : /includes 0|cannot rule out|luck/i.test(v) ? 'warn' : 'fail';
  const desc = o => {
    if (!o) return '—';
    const s = [];
    if (ok(o.c)) s.push(sg(o.c) + ' c');
    if (ok(o.c_per_fill)) s.push(sg(o.c_per_fill) + ' c per fill');
    if (o.ci95) s.push(ci(o.ci95));
    if (ok(o.share_weighted_c)) s.push('share-weighted ' + sg(o.share_weighted_c) + ' c');
    if (ok(o.pnl_usd)) s.push('P&L ' + usd(o.pnl_usd));
    if (ok(o.n_fills)) s.push(n0(o.n_fills) + ' fills');
    if (ok(o.usd_per_day)) s.push(usd(o.usd_per_day, 1) + '/day');
    if (o.months_positive) s.push(o.months_positive + ' months > 0');
    if (ok(o.dsr)) s.push('deflated Sharpe ' + fx(o.dsr, 3));
    if (o.verdict) s.push(o.verdict);
    return s.join(' · ');
  };
  const rows = I.rows.map(r => {
    const pts = [];
    for (const p of ['IS', 'OOS']) {
      const o = r[p]; if (!o) continue;
      const v = ok(o.c) ? o.c : ok(o.c_per_fill) ? o.c_per_fill : null;
      if (v == null && !o.ci95) continue;
      pts.push({p, v, ci: o.ci95, short: p, tip: `${p === 'IS' ? 'in sample' : 'OOS'}: ${desc(o)}\n${r.test}`});
    }
    const meta = h('div', {class: 'lmeta'}, h('div', {class: 'lname'}, r.test),
      h('div', {class: 'lsub'}, h('span', {class: 'chip ' + vcls(r.verdict)}, r.verdict)),
      h('div', {class: 'lvals'}, r.IS ? h('div', null, 'IS: ' + desc(r.IS)) : null, r.OOS ? h('div', null, 'OOS: ' + desc(r.OOS)) : null));
    const empty = r.OOS && ok(r.OOS.dsr) ? `Deflated Sharpe ${fx(r.OOS.dsr, 3)} at N = 3,386 trials; no c/share figure.` : 'Not yet run: ' + r.source + '.';
    return {meta, pts, bars: false, aria: r.test, r, empty};
  });
  const strip = stripRows(rows, 'Net c/share (or c per fill for maker v1)', 'Dot = IS, ring = OOS; line = 95% CI.');
  const ic = PD.I_counts;
  const fig = figure({
    title: 'Stress tests, blind tests and robustness checks that go against the alpha',
    legend: [['fast', 'dot', 'IS, > 0'], ['fast', 'ring', 'OOS, > 0'], ['loss', 'dot', 'IS, < 0'], ['loss', 'ring', 'OOS, < 0'], ['ink', 'line', '95% CI where available']],
    custom: strip,
    table: () => ({cols: ['Test', 'IS', 'OOS', 'Verdict', 'Source'], wrapCols: [1, 2, 4], rows: I.rows.map(r => [r.test, desc(r.IS), desc(r.OOS), r.verdict, r.source])}),
    take: `${ic.not_pending} of ${ic.n_rows} rows go against the strategy out of sample; ${ic.pending} (the blind forward test) is pending.`,
    notes: [I.what + ' OOS rows for v2 are the burned, non-blind OOS; the maker v1, v1 and never-examined-market rows are blind tests.'],
    keys: I.rows.map((_, i) => 'I.rows[' + i + ']').concat(['page_derived.I_counts'])
  });
  section('I', 'What fails · shown next to the alpha',
    `Doubling fees, a 1 c worse entry and 5× size all turn the OOS negative; the blind never-examined-market test and maker v1 failed; the OOS cannot rule out luck.`,
    null, fig);
})();

/* =====================================================================
   FOOTER
   ===================================================================== */
(function foot() {
  const f = document.getElementById('foot'), tf = D.trade_file;
  const cmd = '.venv/bin/python scripts/alpha_pack.py && .venv/bin/python scripts/build_alpha_page.py';
  const pre = h('pre', null, cmd), btn = h('button', {type: 'button'}, 'Copy');
  btn.addEventListener('click', () => {
    const done = () => { btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = 'Copy'; }, 1600); };
    const fallback = () => { const r = document.createRange(); r.selectNodeContents(pre); const s = getSelection(); s.removeAllRanges(); s.addRange(r); btn.textContent = 'Selected, press Ctrl+C'; };
    try { navigator.clipboard.writeText(cmd).then(done, fallback); } catch (e) { fallback(); }
  });
  const nOk = D.checks.filter(c => c.ok).length;
  f.append(
    h('div', null, h('h3', null, 'Definitions'), h('dl', {class: 'defs'},
      h('div', null, h('dt', null, 'In sample (IS)'), h('dd', null, cap(tf.split) + '.')),
      h('div', null, h('dt', null, 'Out of sample (OOS)'), h('dd', null, cap(L.OOS) + '. For the fast-tier test (A, and the fast-tier rows of G and E) OOS is the H6 read: ' + A.OOS.label + '.')),
      h('div', null, h('dt', null, 'v2'), h('dd', null, 'The frozen v2 book, ' + L.v2_fills + '.')),
      h('div', null, h('dt', null, 'Tier 0'), h('dd', null, cap(L.tier0) + '.')),
      h('div', null, h('dt', null, 'Trade file'), h('dd', null, `${tf.path}: ${n0(tf.rows_in_file)} rows, ${n0(tf.rows_training_only_excluded)} training-only rows excluded; OOS starts ${tf.oos_start_utc}.`)),
      h('div', null, h('dt', null, 'Units'), h('dd', null, 'c/share = US cents per share (a share pays $1 if it wins); bps = basis points of notional; CIs are 95%, match-clustered unless stated.')))),
    h('div', null, h('h3', null, `Reconciliation checks · ${nOk}/${D.checks.length} pass`), h('ul', {class: 'checks'},
      D.checks.map(c => h('li', null, h('span', {class: 'chip ' + (c.ok ? '' : 'fail')}, c.ok ? 'pass' : 'fail'), h('span', null, `${c.what}: ours ${c.ours}, repo ${c.repo}` + (c.n_trades_ours != null ? ` (${n0(c.n_trades_ours)} vs ${n0(c.n_trades_repo)} trades)` : '')))))),
    h('div', {id: 'sources'}, h('h3', null, `Sources · ${Object.keys(D.sources).length} keys`), h('div', {class: 'srcs'},
      Object.entries(D.sources).map(([k, v]) => h('div', {id: 'src-' + slug(k)}, h('b', null, k), v)))),
    h('div', null, h('h3', null, 'Rebuild'), h('div', {class: 'cmd'}, pre, btn),
      h('p', {class: 'prov', style: 'margin-top:8px'}, 'alpha_pack.py needs the crawled data (bash run.sh data); build_alpha_page.py needs only results/alpha/alpha.json. Paper only: nothing here trades.')),
    h('p', {class: 'prov'}, `results/alpha/alpha.json generated ${D.generated_utc} by ${D.script} at git ${D.git_head} (pack runtime ${D.runtime_s} s). Repository: `,
      h('a', {href: 'https://github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii', rel: 'noopener'}, 'github.com/OjasMishra32/computervisionpredictivetabletennismoneymachineouuushiii'), '.'));
})();

FIGS.forEach(fg => fg.render(true));
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
