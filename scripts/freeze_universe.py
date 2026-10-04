"""Pin the public event list to the paper's universe (13,084 matches) so a fresh crawl reproduces the 80/20 split.

    python scripts/freeze_universe.py           # enumerate the events if not cached, then drop the newer matches
    python scripts/freeze_universe.py --check   # report only

Polymarket's public event list keeps growing: a crawl made late on 2026-10-03 also returns matches that started or
resolved that day after the authors' crawl (a clean clone found 13,109 universe matches, not 13,084), and every extra
match would move the locked 80/20 cut. results/universe_conds.txt.gz holds the condition ids of the paper's 13,084
matches. This script removes, from the cached event list data/raw/events_tennis_<SINCE>_<UNTIL>.parquet, only the
rows that would enter src.tape.universe() but are not in that list (the removed rows are kept next to it in
..._newer.parquet). src/tape.py and the pinned forward pipeline are not modified. `bash run.sh data` and
`bash run.sh reproduce` run it; on the authors' cache it changes nothing.
"""
from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import polymarket as pm  # noqa: E402
from src.tape import MIN_VOL, SINCE, UNTIL  # noqa: E402

FROZEN = ROOT / "results/universe_conds.txt.gz"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only; do not rewrite the event cache")
    a = ap.parse_args()
    keep = set(gzip.open(FROZEN, "rt").read().split())
    cache = pm.RAW / f"events_tennis_{SINCE}_{UNTIL}.parquet"
    ev = pm.enumerate_events("tennis", SINCE, UNTIL)          # cached after the first call
    in_univ = ev.series.isin(["atp", "wta", "challenger"]) & (ev.volume >= MIN_VOL)
    extra = in_univ & ~ev.cond.isin(keep)
    missing = keep - set(ev.cond[in_univ])
    print(f"universe: {int(in_univ.sum()):,} matches in the event list; frozen list {len(keep):,}; "
          f"{int(extra.sum())} newer to drop; {len(missing)} frozen id(s) absent")
    if missing:
        print(f"WARNING: {len(missing)} of the paper's matches are not in this crawl's event list; the split may differ")
    if extra.any() and not a.check:
        ev[extra].to_parquet(cache.with_name(cache.stem + "_newer.parquet"))
        ev[~extra].reset_index(drop=True).to_parquet(cache)
        print(f"wrote {cache} without the {int(extra.sum())} newer matches")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
