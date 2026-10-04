"""Independent re-derivation of the paper's headline numbers: SQL over row-level files, none of the team's Python.

    python sponsors/snowflake/rederive.py                     # this checkout
    python sponsors/snowflake/rederive.py --root ../ian_check  # another checkout

Runs every sponsors/snowflake/sql/*.sql on DuckDB from the checkout's root (the files read results/... relative
paths, so `duckdb -c ".read sponsors/snowflake/sql/01_v2_daily.sql"` runs them too). Each query returns
paper_key / sql_value (/ sql_value2 for an interval) / how. This script only compares those values with the text the
paper prints (results/paper/numbers.json), at the paper's printed precision, and writes
out/independent_rederivation.md and .json. All arithmetic is in the SQL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import duckdb

from check_all import compare

HERE = Path(__file__).resolve().parent
SQL = HERE / "sql"
OUT = HERE / "out"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=HERE.parents[1], help="checkout whose results/ to read")
    args = ap.parse_args()
    root = args.root.resolve()
    meta = json.loads((root / "results/paper/numbers.json").read_text())
    numbers = meta["numbers"]

    os.chdir(root)
    db = duckdb.connect()
    rows = []
    for f in sorted(SQL.glob("*.sql")):
        for key, v, v2, how in db.execute(f.read_text()).fetchall():
            val = [v, v2] if v2 is not None else v
            x = numbers.get(key)
            if x is None:
                rows.append(dict(key=key, printed="(not printed)", value=val, ok=None, rule="", file=f.name, how=how))
                continue
            ok, rule = compare(str(x["value"]), val)
            rows.append(dict(key=key, printed=str(x["value"]), value=val, ok=ok, rule=rule, file=f.name, how=how,
                             stored=x.get("raw"), source=x.get("source")))

    checked = [r for r in rows if r["ok"] is not None]
    good = sum(r["ok"] for r in checked)
    bad = [r for r in checked if not r["ok"]]
    keys = {r["key"] for r in checked}
    bad_keys = {r["key"] for r in bad}
    line = (f"{len(keys)} headline numbers ({len(checked)} checks, some by two routes) re-derived in SQL from row-level "
            f"files: {len(keys) - len(bad_keys)} ✓, {len(bad_keys)} ✗")
    print(line)
    for r in bad:
        print(f"  ✗ {r['key']}: printed {r['printed']}, SQL {fmt(r['value'])} ({r['file']}): {explain(r)}")

    L = ["# Independent re-derivation of the headline numbers", "",
         f"Run {datetime.now():%Y-%m-%d %H:%M} local on `{root.name}` · numbers file generated "
         f"{meta.get('generated_utc', '?')} · engine DuckDB {duckdb.__version__}", "",
         f"**{line}.**", "",
         "Each number is recomputed by a SQL query in [`sponsors/snowflake/sql/`](../sql/) from row-level files in "
         "git (daily P&L per seed, per-seed sweep cells, trade ledgers, per-seed size cells), without the team's "
         "Python. A number matches when the SQL value rounds to what the paper prints, at the printed precision "
         "(percent printed from a fraction counts as x100). The definition each query uses is in the last column.", ""]
    if bad:
        L += ["## Mismatches", "", "| paper key | printed | SQL value | what differs | SQL file |", "|---|---|---|---|---|"]
        L += [f"| `{r['key']}` | {r['printed']} | {fmt(r['value'])} | {explain(r)} | {r['file']} |"
              for r in bad] + [""]
    L += ["## All re-derived numbers", "", "| paper key | printed | SQL value | match | SQL file | definition |",
          "|---|---|---|---|---|---|"]
    L += [f"| `{r['key']}` | {r['printed']} | {fmt(r['value'])} | {'✓' if r['ok'] else ('✗' if r['ok'] is False else '·')} "
          f"| {r['file']} | {r['how']} |" for r in rows]
    L += ["", "Not re-derived here: v2's capital (3 x peak dollars locked) needs the trade ledger, which is not in git, "
          "so the percentages in `01_v2_daily.sql` divide re-derived dollars by the stored capital from "
          "`results/v2/note_metrics.json`. The fresh-holdout confidence intervals are not seed percentiles of the "
          "committed rows (see `05_fresh_holdout.sql`)."]
    OUT.mkdir(exist_ok=True)
    (OUT / "independent_rederivation.md").write_text("\n".join(L) + "\n")
    (OUT / "independent_rederivation.json").write_text(json.dumps({"summary": line, "rows": rows}, indent=1,
                                                                  default=str))
    print("wrote sponsors/snowflake/out/independent_rederivation.md")
    return 0 if not bad else 1


def explain(r: dict) -> str:
    """Why a re-derived number differs from the print: double rounding (the stored value was already rounded and
    rounding it again for print moved the last digit), or a real difference."""
    from decimal import ROUND_HALF_UP, Decimal
    import re
    nums = re.findall(r"[-\u2212]?\d[\d,]*\.?\d*", r["printed"].replace("$", ""))
    vals = r["value"] if isinstance(r["value"], list) else [r["value"]]
    stored = r.get("stored")
    stored = stored if isinstance(stored, list) else [stored]
    parts = []
    for i, (t, v) in enumerate(zip(nums, vals)):
        t = t.replace("\u2212", "-").replace(",", "")
        dp = len(t.split(".")[1]) if "." in t else 0
        q = Decimal(1).scaleb(-dp)
        right = Decimal(repr(v)).quantize(q, ROUND_HALF_UP)
        if right == Decimal(t):
            continue
        st = stored[i] if i < len(stored) and isinstance(stored[i], (int, float)) else None
        if st is not None and abs(st - v) < 10 ** -(dp + 1) and round(st, dp) == float(t):
            parts.append(f"double rounding: rows give {v:.4f} -> prints {right}; the stored {st} was already rounded "
                         f"and rounding it again gives {t}")
        else:
            parts.append(f"rows give {v:.4f} -> {right}, paper prints {t} (stored {st})")
    return "; ".join(parts) or "differs"


def fmt(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(fmt(x) for x in v) + "]"
    if isinstance(v, float):
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return str(v)


if __name__ == "__main__":
    sys.exit(main())
