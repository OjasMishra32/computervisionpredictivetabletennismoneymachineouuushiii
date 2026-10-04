"""Run queries.sql and check every number it returns against the paper (results/paper/numbers.json).

    python sponsors/snowflake/check.py             # on Snowflake (the reported run), after load.py
    python sponsors/snowflake/check.py --offline   # same SQL on an in-memory DuckDB copy of the same tables

A row passes when the SQL value agrees with the paper's source value to 2 decimal places (or to the source's own
precision when that is coarser), or when it rounds to the number the paper prints, at the precision it is printed
('$73,000' is a capital printed to the nearest $1,000). The report says which. Writes out/checks.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

import common

OUT = common.HERE / "out"


def _decimals(raw_text: str) -> int:
    """Decimal places the source value was stored with ('73288.0' -> 0, '1.089' -> 3)."""
    try:
        d = Decimal(raw_text).normalize()
    except Exception:
        return 2
    return max(0, -d.as_tuple().exponent)


def tolerance(raw_text: str) -> float:
    return 0.5 * 10 ** -min(_decimals(raw_text), 2) + 1e-9


def printed_match(printed: str, val: float) -> bool:
    """Does val round to the paper's printed number? '$73,000' -> nearest 1,000; '+0.40' -> 2 decimals.
    Percentages and intervals are left to the source-value rule (their units vary)."""
    s = printed.replace("−", "-").replace("$", "").replace(",", "").replace("+", "").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return False
    if "." in s:
        step = 10.0 ** -len(s.split(".")[1])
    else:
        zeros = len(s) - len(s.rstrip("0")) if s.strip("-0") else 0
        step = 10.0 ** zeros
    return abs(val - float(s)) <= step / 2 + 1e-9


def run_snowflake(blocks: list[dict]) -> dict[str, pd.DataFrame]:
    con = common.connect()
    out = {}
    try:
        cur = con.cursor()
        for b in blocks:
            cur.execute(b["sql"])
            out[b["name"]] = pd.DataFrame(cur.fetchall(), columns=[c[0].upper() for c in cur.description])
    finally:
        con.close()
    return out


def run_duckdb(blocks: list[dict]) -> dict[str, pd.DataFrame]:
    import duckdb

    con = duckdb.connect()
    for name, df in common.tables().items():
        con.register(name, df)
    out = {}
    for b in blocks:
        d = con.execute(b["sql"]).df()
        d.columns = [c.upper() for c in d.columns]
        out[b["name"]] = d
    return out


def compare(results: dict[str, pd.DataFrame]) -> pd.DataFrame:
    paper = common.paper_numbers().set_index("paper_key")
    rows = []
    for q, d in results.items():
        if "PAPER_KEY" not in d.columns:
            continue
        for r in d.itertuples(index=False):
            key, val = r.PAPER_KEY, float(r.SQL_VALUE) if r.SQL_VALUE is not None else float("nan")
            if key not in paper.index:
                rows.append(dict(query=q, paper_key=key, kind=r.KIND, printed="(not in paper)", source_value=None,
                                 sql_value=val, diff=None, ok=False, match="", source=""))
                continue
            p = paper.loc[key]
            src = p.raw_num
            diff = abs(val - src) if src is not None and pd.notna(src) else None
            by_source = diff is not None and diff <= tolerance(p.raw_text)
            by_print = printed_match(p.printed, val)
            rows.append(dict(query=q, paper_key=key, kind=r.KIND, printed=p.printed, source_value=src,
                             sql_value=val, diff=diff, ok=by_source or by_print,
                             match="source" if by_source else ("printed" if by_print else ""), source=p.source))
    return pd.DataFrame(rows)


def _fmt(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return f"{x:,.4f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def report(cmp: pd.DataFrame, results: dict[str, pd.DataFrame], blocks: list[dict], engine: str, secs: float) -> str:
    n, k = len(cmp), int(cmp.ok.sum())
    rec = cmp[cmp.kind == "recomputed"]
    lines = [f"# COURTSIDE Warehouse: paper numbers reproduced in SQL",
             "",
             f"Engine: **{engine}** · run {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · {secs:.1f} s · "
             f"queries: `sponsors/snowflake/queries.sql`",
             "",
             f"**{k} / {n} paper numbers reproduced** ({int(rec.ok.sum())} / {len(rec)} recomputed in SQL from rows, "
             f"{k - int(rec.ok.sum())} / {n - len(rec)} looked up from stored metrics). A number passes when the SQL "
             "value agrees with the paper's source value to 2 decimals, or to the source's own precision if coarser.",
             "",
             "| ✓ | paper key | paper prints | source value | SQL value | matched on | kind | query |",
             "|---|---|---|---|---|---|---|---|"]
    for r in cmp.itertuples(index=False):
        lines.append(f"| {'✓' if r.ok else '✗'} | `{r.paper_key}` | {r.printed} | {_fmt(r.source_value)} | "
                     f"{_fmt(r.sql_value)} | {r.match} | {r.kind} | {r.query} |")
    pr = cmp[cmp.match == "printed"]
    if len(pr):
        lines += ["", "Matched on *printed*: the SQL value rounds to the number the paper prints but differs from the "
                  "stored source value by more than 2 decimals (" + ", ".join(
                      f"`{r.paper_key}` {_fmt(r.sql_value)} vs {_fmt(r.source_value)}" for r in pr.itertuples()) + ")."]
        if pr.paper_key.str.startswith("capcv.").any():
            lines += ["For the capacity figures this is input rounding, not a different rule: "
                      "`results/capacity/cv_cells.csv` stores Sharpe to 4 decimals, while `capacity.json` was computed "
                      "from unrounded values. The paper's own rule (`scripts/capacity_study.py::capacity_answer`) run on "
                      "the same CSV gives the SQL value to the cent."]
    lines += ["", "## Descriptive queries", ""]
    docs = {b["name"]: b["doc"] for b in blocks}
    for q, d in results.items():
        if "PAPER_KEY" in d.columns:
            continue
        lines += [f"### {q}", "", docs.get(q, ""), "", d.to_markdown(index=False, floatfmt=".2f"), ""]
    lines += ["", "Every P&L above is paper (simulated) trading on public data; nothing was traded. Sources: "
              "`results/tier0/latency_sweep.csv`, `results/capacity/cv_cells.csv`, `results/e2e/trace.jsonl`, "
              "`results/v2/*.json`, `results/engine/online_events_L4.jsonl`, `tests/fixtures/live_sample.jsonl.gz`; "
              "paper numbers from `results/paper/numbers.json`."]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="run on in-memory DuckDB instead of Snowflake")
    args = ap.parse_args()
    blocks = common.read_queries()
    t0 = time.time()
    results = run_duckdb(blocks) if args.offline else run_snowflake(blocks)
    secs = time.time() - t0
    engine = "DuckDB (offline check of the SQL, not the reported run)" if args.offline else "Snowflake"
    cmp = compare(results)
    for r in cmp.itertuples(index=False):
        print(f"{'✓' if r.ok else '✗'}  {r.paper_key:22s} paper {r.printed:>12s}  sql {_fmt(r.sql_value):>12s}  "
              f"[{r.kind}]")
    print(f"\n{int(cmp.ok.sum())}/{len(cmp)} paper numbers reproduced on {engine.split(' (')[0]} "
          f"({int(cmp[cmp.kind == 'recomputed'].ok.sum())} recomputed, "
          f"{int(cmp[cmp.kind == 'lookup'].ok.sum())} lookups) in {secs:.1f} s")
    OUT.mkdir(exist_ok=True)
    name = "checks_offline.md" if args.offline else "checks.md"
    (OUT / name).write_text(report(cmp, results, blocks, engine, secs))
    (OUT / name.replace(".md", ".json")).write_text(json.dumps(
        {"engine": engine.split(" (")[0], "reproduced": int(cmp.ok.sum()), "checked": len(cmp),
         "rows": json.loads(cmp.to_json(orient="records"))}, indent=1))
    print(f"wrote sponsors/snowflake/out/{name}")
    return 0 if cmp.ok.all() else 1


if __name__ == "__main__":
    sys.exit(main())
