"""One-shot, cached fetch of the WTA official point-by-point log for today's singles matches.

Gives an official per-point timestamp for every WTA match played while either live recorder was
running (data/live since 09:46 UTC, data/live_v2 since 11:08 UTC), including matches that were
already finished when research/v2/latency/recorder.py started. Polite: one request per match,
cached under data/v2_latency/pbp/ (completed matches are never re-fetched).

    python research/v2/latency/fetch_pbp.py [--date 2026-10-03]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "v2_latency" / "pbp"
WTA = "https://api.wtatennis.com/tennis"
UA = "courtside-research/0.1 (academic latency study; read-only)"


def main(day: str) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})
    d0 = dt.date.fromisoformat(day)
    tl = s.get(f"{WTA}/tournaments/", params={"page": 0, "pageSize": 50, "from": str(d0 - dt.timedelta(days=1)),
                                              "to": str(d0 + dt.timedelta(days=1)), "excludeLevels": "ITF"},
               timeout=20).json()
    n_new = 0
    for t in tl.get("content", []):
        if t.get("status") not in ("live", "inProgress", "past"):
            continue
        tid, yr = t["tournamentGroup"]["id"], t["year"]
        ms = s.get(f"{WTA}/tournaments/{tid}/{yr}/matches", params={"from": day, "to": day}, timeout=20).json()
        time.sleep(1.0)
        for m in ms.get("matches", []):
            if m.get("DrawMatchType") != "S" or m.get("MatchState") not in ("F", "P"):
                continue
            f = CACHE / f"pbp_{tid}_{yr}_{m['MatchID']}.json"
            if f.exists() and json.loads(f.read_text()).get("_state") == "F":
                continue
            r = s.get(f"{WTA}/tournaments/{tid}/{yr}/matches/{m['MatchID']}/point-by-point", timeout=20)
            time.sleep(1.0)
            if r.status_code != 200:
                continue
            d = r.json()
            d["_state"], d["_tid"], d["_yr"], d["_mid"] = m["MatchState"], tid, yr, m["MatchID"]
            d["_fetched_ms"] = int(time.time() * 1000)
            d["_names"] = [f'{m["PlayerNameFirstA"]} {m["PlayerNameLastA"]}', f'{m["PlayerNameFirstB"]} {m["PlayerNameLastB"]}']
            f.write_text(json.dumps(d))
            n_new += 1
            print(tid, m["MatchID"], d["_names"], m["MatchState"], len(d.get("points") or []))
    print("fetched", n_new)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    main(ap.parse_args().date)
