"""Create the COURTSIDE database in Snowflake and load every warehouse table from the committed results.

    python sponsors/snowflake/load.py      # create database/schema, (re)load all tables, print row counts

Re-running replaces the tables (overwrite), so the warehouse always mirrors the files in git.
"""
from __future__ import annotations

import time

from snowflake.connector.pandas_tools import write_pandas

import common


def main() -> None:
    s = common.settings()
    t0 = time.time()
    tables = common.tables()
    print(f"built {len(tables)} tables from committed files in {time.time() - t0:.1f} s")

    con = common.connect(with_db=False)
    try:
        cur = con.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {s['database']}")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {s['database']}.{s['schema']}")
        cur.execute(f"USE SCHEMA {s['database']}.{s['schema']}")
        for name, df in tables.items():
            t = time.time()
            ok, _, nrows, _ = write_pandas(con, df, table_name=name, auto_create_table=True, overwrite=True,
                                           quote_identifiers=False)
            if not ok:
                raise SystemExit(f"load failed: {name}")
            cur.execute(f"COMMENT ON TABLE {name} IS 'COURTSIDE: loaded from committed repo files by "
                        f"sponsors/snowflake/load.py; read-only copy, paper trading only'")
            print(f"  {name:16s} {nrows:>9,} rows  ({time.time() - t:.1f} s)")
        print("\nrow counts in Snowflake:")
        for name in tables:
            cur.execute(f"SELECT COUNT(*) FROM {name}")
            print(f"  {name:16s} {cur.fetchone()[0]:>9,}")
    finally:
        con.close()
    print(f"done in {time.time() - t0:.1f} s -> {s['database']}.{s['schema']}")


if __name__ == "__main__":
    main()
