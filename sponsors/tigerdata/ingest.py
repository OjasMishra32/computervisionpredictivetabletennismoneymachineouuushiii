"""Load COURTSIDE's committed data into Tiger Data and report what landed.

    python sponsors/tigerdata/ingest.py            # create the schema, load everything, compress, print stats
    python sponsors/tigerdata/ingest.py --no-reset # append to the existing tables instead

Inputs (all committed, all public or our own):
  tests/fixtures/live_sample.jsonl.gz   10 min of the live Polymarket CLOB websocket (14 tennis events)
  results/engine/online_events_L4.jsonl the CV engine's point-end calls
  results/e2e/trace.jsonl               per-stage timestamps of the end-to-end pipeline
Connection: TIGER_DATABASE_URL from the environment or the repo's .env (never printed).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE = ROOT / "tests/fixtures/live_sample.jsonl.gz"
CV_CALLS = ROOT / "results/engine/online_events_L4.jsonl"
TRACE = ROOT / "results/e2e/trace.jsonl"


def db_url() -> str:
    url = os.environ.get("TIGER_DATABASE_URL")
    env = ROOT / ".env"
    if not url and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("TIGER_DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip("'\"")
    if not url:
        raise SystemExit("TIGER_DATABASE_URL is not set (put it in the repo's .env)")
    return url


def statements(sql: str) -> list[str]:
    """Split a SQL file on semicolons, keeping $$ function bodies whole and dropping comment-only parts.

    Statements run one at a time because TimescaleDB refuses to create a continuous aggregate inside the
    implicit transaction of a multi-statement query."""
    out, buf, in_body = [], [], False
    for line in sql.splitlines():
        if line.strip().startswith("--") and not in_body:
            continue
        buf.append(line)
        in_body ^= line.count("$$") % 2 == 1
        if not in_body and line.split("--")[0].rstrip().endswith(";"):
            out.append("\n".join(buf).strip())
            buf = []
    if "\n".join(buf).strip():
        out.append("\n".join(buf).strip())
    return out


def apply_schema(conn) -> None:
    for st in statements((HERE / "schema.sql").read_text()):
        conn.execute(st)


def utc(ms: float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def parse_fixture(path: Path = FIXTURE):
    """Compact recorder lines -> rows for markets, book_updates and trades."""
    markets, book, trades, winners = {}, [], [], set()
    with gzip.open(path, "rt") as fh:
        head = json.loads(fh.readline())
        tok = {int(k): v for k, v in head["tokens"].items()}
        for v in tok.values():
            start = datetime.fromisoformat(v["start"].replace("Z", "+00:00")) if v.get("start") else None
            markets[v["tok"]] = [v["tok"], v["cond"], v.get("slug"), v.get("title"), v.get("outcome"),
                                 v.get("smt"), start, None, "live_sample"]
        for line in fh:
            d = json.loads(line)
            e = d.get("e")
            if e == "b" and d.get("a") in tok:
                t, rt, m = tok[d["a"]], utc(d["rt"]), tok[d["a"]]["cond"]
                bb = max((p for p, _ in d["b"]), default=None)
                ba = min((p for p, _ in d["k"]), default=None)
                ts = utc(d["ts"])
                book += [(ts, rt, t["tok"], m, "bid", p, s, "snapshot", bb, ba) for p, s in d["b"]]
                book += [(ts, rt, t["tok"], m, "ask", p, s, "snapshot", bb, ba) for p, s in d["k"]]
            elif e == "pc":
                ts, rt = utc(d["ts"]), utc(d["rt"])
                for a, p, s, side, bb, ba in d["c"]:
                    if a in tok:
                        book.append((ts, rt, tok[a]["tok"], tok[a]["cond"], "bid" if side == "B" else "ask",
                                     p, s, "change", bb, ba))
            elif e == "t" and d.get("a") in tok:
                trades.append((utc(d["ts"]), utc(d["rt"]), tok[d["a"]]["tok"], tok[d["a"]]["cond"],
                               d["p"], d["s"], d.get("side"), "live_sample"))
            elif e == "market_resolved":
                w = (d.get("raw") or {}).get("winning_asset_id")
                if w:
                    winners.add(w)
    for asset, row in markets.items():
        if any(markets[a][1] == row[1] for a in winners if a in markets):
            row[7] = asset in winners
    return [tuple(r) for r in markets.values()], book, trades


def parse_cv_calls(path: Path = CV_CALLS):
    rows = []
    for line in path.open():
        d = json.loads(line)
        rows.append((datetime.fromtimestamp(d["t_emit"], tz=timezone.utc), d["call"], d.get("p_miss"),
                     d.get("lead_ms"), d.get("source", "engine")))
    return rows


# Stamps that are not a step of the pipeline: when the book snapshot was taken, and post-hoc fill accounting.
OFF_PATH = {"book_state_stamp", "fill_computed"}


def parse_trace(path: Path = TRACE):
    """Stage durations from each call's monotonic stamps, plus venue round trips.

    The trace stamps are time.monotonic(); the venue round-trip rows carry wall seconds too, which gives
    the offset that maps monotonic time onto wall time (to about a second, enough for a time index)."""
    L = [json.loads(line) for line in path.open()]
    meta = next(d for d in L if d["type"] == "meta")
    offset = statistics.median(d["venue_s"] - d["t"] for d in L if d["type"] == "rtt")
    rows = []
    for d in L:
        if d["type"] == "call" and d.get("t"):
            run = f"{meta['run_id']}/pass{d.get('pass_idx', 0)}"
            stamps = sorted(((k, v) for k, v in d["t"].items() if k not in OFF_PATH), key=lambda kv: kv[1])
            for (s0, t0), (s1, t1) in zip(stamps, stamps[1:]):
                rows.append((datetime.fromtimestamp(offset + t1, tz=timezone.utc), run, f"{s0}->{s1}", (t1 - t0) * 1e3))
            rows.append((datetime.fromtimestamp(offset + stamps[-1][1], tz=timezone.utc), run, f"total:capture->{stamps[-1][0]}",
                         (stamps[-1][1] - stamps[0][1]) * 1e3))
        elif d["type"] == "rtt":
            rows.append((datetime.fromtimestamp(offset + d["t"], tz=timezone.utc), meta["run_id"],
                         f"venue_rtt_{d.get('kind', 'warm')}", d["rtt_ms"]))
    return rows


COLS = {
    "markets": "asset_id, market, slug, title, outcome, market_type, start_ts, winner, source",
    "book_updates": "ts, rt, asset_id, market, side, price, size, kind, best_bid, best_ask",
    "trades": "ts, rt, asset_id, market, price, size, side, source",
    "cv_calls": "ts, call, p_miss, lead_ms, source",
    "pipeline_stages": "ts, run, stage, ms",
}


def copy(cur, table: str, rows) -> tuple[int, float]:
    t = time.perf_counter()
    with cur.copy(f"COPY courtside.{table} ({COLS[table]}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)
    return len(rows), time.perf_counter() - t


def main(reset: bool):
    t0 = time.perf_counter()
    markets, book, trades = parse_fixture()
    data = {"markets": markets, "book_updates": book, "trades": trades,
            "cv_calls": parse_cv_calls(), "pipeline_stages": parse_trace()}
    print(f"parsed in {time.perf_counter() - t0:.1f} s")
    with psycopg.connect(db_url(), autocommit=True) as conn:
        if reset:
            apply_schema(conn)
            print("schema created")
        total_rows, total_s = 0, 0.0
        with conn.cursor() as cur:
            for table, rows in data.items():
                n, s = copy(cur, table, rows)
                total_rows += n
                total_s += s
                print(f"{table:16s} {n:>9,} rows  {s:6.2f} s  {n / max(s, 1e-9):>10,.0f} rows/s")
        print(f"{'total':16s} {total_rows:>9,} rows  {total_s:6.2f} s  {total_rows / total_s:>10,.0f} rows/s")
        for v in ("mid_1s", "trades_1s"):
            conn.execute(f"CALL refresh_continuous_aggregate('courtside.{v}', NULL, NULL)")
        conn.execute("CALL courtside.detect_jumps()")
        n_j = conn.execute("SELECT count(*) FROM courtside.jump_events").fetchone()[0]
        print(f"continuous aggregates refreshed; {n_j} jumps detected")
        for h in ("book_updates", "trades"):
            conn.execute(f"SELECT compress_chunk(c, if_not_compressed => true) FROM show_chunks('courtside.{h}') c")
            b, a = conn.execute(f"SELECT sum(before_compression_total_bytes), sum(after_compression_total_bytes) "
                                f"FROM hypertable_compression_stats('courtside.{h}')").fetchone()
            print(f"{h:16s} compressed {b / 1e6:7.1f} MB -> {a / 1e6:6.1f} MB  ({b / a:.1f}x)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-reset", action="store_true", help="append instead of recreating the schema")
    main(not ap.parse_args().no_reset)
