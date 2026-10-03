#!/usr/bin/env python3
"""Replay the committed 10-minute live sample (tests/fixtures/live_sample.jsonl.gz) through both replayers.

PAPER ONLY. The sample is recorded public Polymarket CLOB market data (see tests/fixtures/README.md); nothing
here connects to anything, signs anything or sends an order.

    .venv/bin/python scripts/replay_sample.py paper  [live_paper.py args, e.g. --no-dashboard]
        maker v1 live paper engine (scripts/live_paper.py --replay), unchanged. live_paper.py picks the
        recorder format from the file name (clob_* + clobmeta_*), so this links the fixture under those names
        in a temp dir and calls it. Like every live_paper.py replay, it appends one line to
        results/oos_peeks.log and writes results/live/replay_*.
    .venv/bin/python scripts/replay_sample.py engine
        COURTSIDE engine order books (engine/market/clob.py ReplayClobFeed), unchanged. The fixture is in the
        recorder's compact format; this expands each line back to the venue's message shape and feeds it in.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "live_sample.jsonl.gz"
TAG = "20261003_1123"   # recorder run tag of the source file; live_paper.py pairs clob_<tag>_* with clobmeta_<tag>_*


def _link(src: Path, dst: Path) -> None:
    try:
        os.symlink(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def paper(args: list[str]) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="courtside_sample_"))
    try:
        _link(FIXTURE, tmp / f"clob_{TAG}_sample.jsonl.gz")
        _link(FIXTURE, tmp / f"clobmeta_{TAG}_sample.jsonl.gz")   # line 1 holds the token index
        cmd = [sys.executable, str(ROOT / "scripts" / "live_paper.py"), "--replay",
               str(tmp / f"clob_{TAG}_*"), "--test", *args]
        print("$", " ".join(cmd[1:]), flush=True)
        return subprocess.call(cmd, cwd=ROOT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def expand(path: Path = FIXTURE):
    """Compact recorder lines -> venue-shaped market messages (book / price_change / last_trade_price /
    market_resolved), plus the token index {token_id: meta}."""
    with gzip.open(path, "rt") as fh:
        head = json.loads(fh.readline())
        tok = {int(k): v["tok"] for k, v in head["tokens"].items()}
        cond = {int(k): v["cond"] for k, v in head["tokens"].items()}
        meta = {v["tok"]: v for v in head["tokens"].values()}
        msgs = []
        for line in fh:
            d = json.loads(line)
            e, rt = d.get("e"), d.get("rt")
            if e == "pc":
                ch = [{"asset_id": tok[c[0]], "price": str(c[1]), "size": str(c[2]),
                       "side": "BUY" if c[3] == "B" else "SELL"} for c in d["c"] if c[0] in tok]
                if ch:
                    msgs.append({"event_type": "price_change", "market": cond[d["c"][0][0]], "timestamp": str(d["ts"]),
                                 "price_changes": ch, "rt": rt})
            elif e == "b" and d.get("a") in tok:
                msgs.append({"event_type": "book", "asset_id": tok[d["a"]], "market": cond[d["a"]],
                             "timestamp": str(d["ts"]), "rt": rt,
                             "bids": [{"price": str(x), "size": str(z)} for x, z in d["b"]],
                             "asks": [{"price": str(x), "size": str(z)} for x, z in d["k"]]})
            elif e == "t" and d.get("a") in tok:
                msgs.append({"event_type": "last_trade_price", "asset_id": tok[d["a"]], "market": cond[d["a"]],
                             "timestamp": str(d["ts"]), "price": str(d["p"]), "size": str(d["s"]),
                             "side": d.get("side"), "rt": rt})
            elif e == "market_resolved":
                raw = d.get("raw") or {}
                msgs.append({"event_type": "market_resolved", "market": raw.get("market"),
                             "winning_asset_id": raw.get("winning_asset_id"),
                             "timestamp": str(raw.get("timestamp") or d.get("ts") or rt), "rt": rt})
    return head, meta, msgs


def engine() -> int:
    sys.path.insert(0, str(ROOT))
    from engine.market.clob import ReplayClobFeed, _fmt_book
    head, meta, msgs = expand()
    t = time.perf_counter()
    trades = []
    feed = ReplayClobFeed(messages=msgs, clock="recorded")
    feed.on(lambda ev: trades.append(ev) if ev.kind == "trade" else None)
    feed.run_sync()
    dt = time.perf_counter() - t
    s = feed.summary()
    print(f"COURTSIDE engine order books on the committed live sample ({head['source']})")
    print(json.dumps(s, indent=1, default=str))
    print(f"replayed {s['msgs']} messages in {dt:.1f} s; {len(trades)} trades seen; "
          f"{len(feed.resolved)} markets resolved in the window")
    active = sorted(feed.books, key=lambda a: -feed.books[a].n_updates)[:10]
    print("\nmost active books at the end of the window (bid x size | ask x size):")
    for a in active:
        print("  " + _fmt_book(feed, a, meta))
    return 0


def main(argv: list[str]) -> int:
    if not FIXTURE.exists():
        sys.exit(f"missing {FIXTURE}")
    mode = argv[0] if argv else "paper"
    if mode == "paper":
        return paper(argv[1:])
    if mode == "engine":
        return engine()
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
