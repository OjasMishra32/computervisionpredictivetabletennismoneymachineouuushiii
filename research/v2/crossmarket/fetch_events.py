"""Step 1: side-market catalogue for every IS match (Gamma events, batched by id, sequential).

Output: data/v2_crossmarket/side_markets.parquet, one row per non-moneyline market of an IS event.
Run: .venv/bin/python research/v2/crossmarket/fetch_events.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata

import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from common import CACHE, GAMMA, OOS_CUT, get, universe_is  # noqa: E402

BATCH = 50


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s).strip()


PLAYER_TYPES = ("tennis_first_set_winner", "tennis_set_winner", "tennis_set_handicap", "tennis_game_handicap")


def align(side_out: str, ml0: str, ml1: str, smt: str) -> int:
    """+1 if side outcome names player 0 of the moneyline, -1 if player 1, 0 if not a player."""
    s = _norm(side_out)
    if smt not in PLAYER_TYPES or not s:
        return 0
    a, b = _norm(ml0), _norm(ml1)
    toks = s.split()
    hit_a = s in a or any(t in a.split() for t in toks if len(t) > 2)
    hit_b = s in b or any(t in b.split() for t in toks if len(t) > 2)
    if hit_a and not hit_b:
        return 1
    if hit_b and not hit_a:
        return -1
    return 0


def main():
    u = universe_is()
    cache_json = CACHE / "events_raw"
    cache_json.mkdir(parents=True, exist_ok=True)
    ids = u.event_id.astype(str).tolist()
    rows = []
    for k in range(0, len(ids), BATCH):
        chunk = ids[k:k + BATCH]
        f = cache_json / f"batch_{k:06d}.json"
        if f.exists():
            evs = json.loads(f.read_text())
        else:
            evs = get(GAMMA, [("id", i) for i in chunk] + [("limit", BATCH)])
            # keep only the market fields we use
            slim = []
            for e in evs:
                ms = []
                for m in e.get("markets", []):
                    ms.append({x: m.get(x) for x in (
                        "conditionId", "sportsMarketType", "groupItemTitle", "question", "line",
                        "outcomes", "outcomePrices", "volume", "secondsDelay", "feeSchedule",
                        "clobTokenIds", "closedTime", "orderPriceMinTickSize", "gameStartTime")})
                slim.append({"id": e["id"], "slug": e.get("slug"), "markets": ms})
            evs = slim
            f.write_text(json.dumps(evs))
            time.sleep(0.25)
        for e in evs:
            for m in e["markets"]:
                rows.append({"event_id": str(e["id"]), **m})
        if k % 1000 == 0:
            print(f"events {k}/{len(ids)}", flush=True)
    m = pd.DataFrame(rows)
    ml = u.set_index("event_id")
    m = m[m.event_id.isin(ml.index)]
    m = m[m.sportsMarketType != "moneyline"].copy()
    m["ml_cond"] = m.event_id.map(ml.cond)
    m["start"] = m.event_id.map(ml.start)
    m["end"] = m.event_id.map(ml.end)
    m["ml_res0"] = m.event_id.map(ml.res0)
    m["ml_fee"] = m.event_id.map(ml.fee_rate)
    m["ml_delay"] = m.event_id.map(ml.delay)
    m["series"] = m.event_id.map(ml.series)
    m["ml_volume"] = m.event_id.map(ml.volume)
    jl = lambda s: json.loads(s) if isinstance(s, str) and s else []  # noqa: E731
    outs = m.outcomes.map(jl)
    pr = m.outcomePrices.map(jl)
    toks = m.clobTokenIds.map(jl)
    m = m[(outs.map(len) == 2) & (toks.map(len) == 2)].copy()
    outs, pr, toks = outs[m.index], pr[m.index], toks[m.index]
    m["out0"] = outs.map(lambda x: x[0])
    m["out1"] = outs.map(lambda x: x[1])
    m["res_s0"] = pr.map(lambda x: float(x[0]) if x else float("nan"))
    m["tok0"] = toks.map(lambda x: x[0])
    m["tok1"] = toks.map(lambda x: x[1])
    m["volume"] = m.volume.astype(float).fillna(0.0)
    m["fee_rate"] = m.feeSchedule.map(lambda d: (d or {}).get("rate")).astype(float)
    m["fee_rate"] = m.fee_rate.fillna(m.ml_fee).fillna(0.0)
    m["delay"] = m.secondsDelay.fillna(m.ml_delay).astype(int)
    m["line"] = pd.to_numeric(m.line, errors="coerce")
    ml0 = m.event_id.map(ml.out0)
    ml1 = m.event_id.map(ml.out1)
    m["align0"] = [align(o, a, b, t) for o, a, b, t in zip(m.out0, ml0, ml1, m.sportsMarketType)]
    m = m.rename(columns={"conditionId": "cond", "sportsMarketType": "smt", "groupItemTitle": "title"})
    m = m.drop(columns=["outcomes", "outcomePrices", "clobTokenIds", "feeSchedule"])
    m = m.drop_duplicates("cond").reset_index(drop=True)
    assert (m.start < OOS_CUT).all()
    m.to_parquet(CACHE / "side_markets.parquet")
    print(m.groupby("smt").agg(n=("cond", "size"), vol=("volume", "sum"),
                               med=("volume", "median"), aligned=("align0", lambda s: (s != 0).mean())))


if __name__ == "__main__":
    main()
