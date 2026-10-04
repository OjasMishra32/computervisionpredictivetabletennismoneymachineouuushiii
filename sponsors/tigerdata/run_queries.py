"""Run every query in queries.sql against Tiger Data, print a preview and the time each took.

    python sponsors/tigerdata/run_queries.py    ->  sponsors/tigerdata/out/query_results.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ingest import db_url  # noqa: E402


def queries() -> list[tuple[str, str]]:
    text = (HERE / "queries.sql").read_text()
    parts = re.split(r"^-- name: (\w+)\s*$", text, flags=re.M)
    return [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts), 2)]


def main(repeats: int = 3):
    out = {}
    with psycopg.connect(db_url(), autocommit=True) as conn:
        for name, sql in queries():
            body = [s for s in sql.split(";") if s.strip() and not s.strip().upper().startswith("SET")]
            conn.execute("SET search_path = courtside, public")
            times = []
            for _ in range(repeats):
                t = time.perf_counter()
                cur = conn.execute(body[-1])
                rows = cur.fetchall()
                times.append((time.perf_counter() - t) * 1e3)
            cols = [c.name for c in cur.description]
            best = min(times)
            print(f"\n== {name}: {len(rows)} rows, best of {repeats} {best:.1f} ms (includes network round trip)")
            print(" | ".join(cols))
            for r in rows[:8]:
                print(" | ".join(str(x) for x in r))
            out[name] = {"ms_best": round(best, 1), "n_rows": len(rows), "columns": cols,
                         "rows": [[str(x) for x in r] for r in rows]}
        t = time.perf_counter()
        conn.execute("SELECT 1").fetchall()
        rtt = (time.perf_counter() - t) * 1e3
    out["_network_rtt_ms"] = round(rtt, 1)
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out/query_results.json").write_text(json.dumps(out, indent=1))
    print(f"\nnetwork round trip to the database: {rtt:.1f} ms; wrote out/query_results.json")


if __name__ == "__main__":
    main()
