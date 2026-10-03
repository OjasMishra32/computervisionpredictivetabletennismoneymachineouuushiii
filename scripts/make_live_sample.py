#!/usr/bin/env python3
"""Build tests/fixtures/live_sample.jsonl.gz: the first 10 minutes of a recorded live Polymarket CLOB session.

Source: data/live_v2/clob_20261003_1123_20261003_11.jsonl.gz and its clobmeta_20261003_1123_* token index,
recorded 2026-10-03 from 11:23 UTC on the public, unauthenticated CLOB `market` websocket (read-only; no
orders, no keys). The window starts at the subscription, so every book begins with the venue's own snapshot.

Kept: ATP / WTA / Challenger singles events that started before 2026-10-03 13:00 UTC (HYPOTHESIS_V2.md
excludes every match starting before 13:00 UTC from the forward test, so the sample holds no forward-window
market), moneyline plus the six side-market types maker v1 trades. Price-change lines are cut to those
tokens; best_bid_ask lines are dropped (neither replayer uses them). Nothing else is altered.

Line 1 is the token index in the recorder's clobmeta format ({"tokens": {idx: meta}}); every other line is
a recorder line unchanged (compact clob_ format: e = b | pc | t | market_resolved | conn | error).
Replay it with: bash run.sh replay   (or .venv/bin/python scripts/replay_sample.py)

    .venv/bin/python scripts/make_live_sample.py     # needs data/live_v2 (not in git); ~1 min
"""
from __future__ import annotations

import glob
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "live_v2" / "clob_20261003_1123_20261003_11.jsonl.gz"
META = sorted(glob.glob(str(ROOT / "data" / "live_v2" / "clobmeta_20261003_1123_*")))
OUT = ROOT / "tests" / "fixtures" / "live_sample.jsonl.gz"
MINUTES = 10
FORWARD_START = "2026-10-03T13:00:00Z"
SERIES = {"atp", "wta", "challenger"}
SMT = {"moneyline", "tennis_first_set_winner", "tennis_set_winner", "tennis_set_handicap",
       "tennis_match_totals", "tennis_set_totals", "tennis_first_set_totals"}


def load_meta() -> dict[int, dict]:
    meta: dict[int, dict] = {}
    for f in META:
        op = gzip.open if f.endswith(".gz") else open
        try:
            with op(f, "rt") as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    for k, v in (d.get("tokens") or {}).items():
                        meta[int(k)] = v
        except (EOFError, OSError):
            pass
    return meta


def keep_token(v: dict) -> bool:
    slug = v.get("slug") or ""
    start = v.get("start") or ""
    return (slug.split("-")[0] in SERIES and "doubles" not in slug and bool(start) and start < FORWARD_START
            and (v.get("smt") or "moneyline") in SMT)


def main() -> None:
    if not SRC.exists():
        sys.exit(f"missing {SRC.relative_to(ROOT)} (live recordings are not in git; the committed fixture is the output)")
    meta = load_meta()
    keep = {k for k, v in meta.items() if keep_token(v)}
    conds = {meta[k]["cond"] for k in keep}
    t0 = t1 = None
    n = {"in": 0, "out": 0}
    lines = []
    with gzip.open(SRC, "rt") as fh:
        try:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                rt = d.get("rt") or 0
                if t0 is None:
                    t0, t1 = rt, rt + MINUTES * 60_000
                if rt > t1:
                    break
                n["in"] += 1
                e = d.get("e")
                if e == "pc":
                    c = [x for x in d["c"] if x[0] in keep]
                    if not c:
                        continue
                    d["c"] = c
                elif e in ("b", "t"):
                    if d.get("a") not in keep:
                        continue
                elif e == "market_resolved":
                    if (d.get("raw") or {}).get("market") not in conds:
                        continue
                elif e not in ("conn", "error"):
                    continue
                lines.append(json.dumps(d, separators=(",", ":")))
        except (EOFError, OSError):
            pass
    used = {x[0] for ln in lines for x in json.loads(ln).get("c", ())} | \
           {json.loads(ln).get("a") for ln in lines}
    tokens = {str(k): meta[k] for k in sorted(keep) if k in used}
    head = {"rt": t0, "tokens": tokens,
            "source": f"data/live_v2/{SRC.name} (public CLOB market websocket, read-only), rt {t0}..{t1}",
            "filter": f"atp/wta/challenger singles starting before {FORWARD_START}; smt in {sorted(SMT)}; "
                      "price changes cut to kept tokens; best_bid_ask dropped"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", compresslevel=9) as fh:
        fh.write(json.dumps(head, separators=(",", ":")) + "\n")
        for ln in lines:
            fh.write(ln + "\n")
    n["out"] = len(lines)
    events = {v.get("event_id") for v in tokens.values()}
    print(f"{OUT.relative_to(ROOT)}: {n['out']} of {n['in']} lines, {len(tokens)} tokens, {len(events)} events, "
          f"{OUT.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
