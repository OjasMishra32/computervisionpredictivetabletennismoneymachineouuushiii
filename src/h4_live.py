"""H4: does the Polymarket book reprice before Polymarket's own public score feed?

For every game (or tiebreak point) won on the sports feed, find the largest mid move of
that player's token in the matching direction within [-90 s, +30 s] of the feed message.
lead = feed time - move time; positive means the book knew first.
"""
from __future__ import annotations

import glob
import gzip
import json
import re

import numpy as np
import pandas as pd

TENNIS = {"atp", "wta", "challenger", "itf"}
SEG = re.compile(r"(\d+)-(\d+)(?:\((\d+)-(\d+)\))?")


def _read(pattern: str) -> list[dict]:
    out = []
    for f in sorted(glob.glob(pattern)):
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt") as fh:
            try:
                for line in fh:
                    out.append(json.loads(line))
            except (EOFError, json.JSONDecodeError):
                pass
    return out


def _state(score: str):
    segs = [s.strip() for s in (score or "").split(",") if s.strip()]
    parsed = [SEG.fullmatch(s) for s in segs]
    if not parsed or any(p is None for p in parsed):
        return None
    sets_h = sets_a = 0
    for p in parsed[:-1]:
        h, a = int(p.group(1)), int(p.group(2))
        sets_h += h > a
        sets_a += a > h
    last = parsed[-1]
    tb = (int(last.group(3)), int(last.group(4))) if last.group(3) else (0, 0)
    return (sets_h, sets_a, int(last.group(1)), int(last.group(2)), *tb)


def score_changes(sports: list[dict]) -> pd.DataFrame:
    rows = []
    df = pd.DataFrame([s for s in sports if str(s.get("leagueAbbreviation", "")).lower() in TENNIS and "score" in s])
    if df.empty:
        return df
    for gid, g in df.sort_values("rt").groupby("gameId"):
        prev = None
        for r in g.itertuples():
            st = _state(r.score)
            if st is None:
                continue
            if prev is not None and st != prev:
                # who won the unit that just finished (sets > games > tiebreak points)
                d = [st[i] - prev[i] for i in range(6)]
                if d[0] > 0 or d[1] > 0:
                    home_won = d[0] > 0
                elif d[2] != 0 or d[3] != 0:
                    home_won = d[2] > 0
                else:
                    home_won = d[4] > 0
                rows.append({"gameId": gid, "rt": r.rt, "home": r.homeTeam, "away": r.awayTeam,
                             "home_won": bool(home_won), "score": r.score, "first_seen": False})
            prev = st
    return pd.DataFrame(rows)


def mids(market: list[dict]) -> pd.DataFrame:
    rows = [{"asset": m["asset_id"], "rt": m["rt"], "ts": m["rt"],
             "bid": float(m.get("best_bid") or "nan"), "ask": float(m.get("best_ask") or "nan")}
            for m in market if m.get("event_type") == "best_bid_ask"]
    df = pd.DataFrame(rows)
    df = df[(df.ask - df.bid) <= 0.05]
    df["mid"] = (df.bid + df.ask) / 2
    return df.sort_values("ts")


def leads(min_move: float = 0.005) -> pd.DataFrame:
    meta = {}
    for rec in _read("data/live/tokens_*.jsonl"):
        meta.update(rec["tokens"])
    by_game = {}
    for tok, m in meta.items():
        by_game.setdefault(m["gameId"], {})[m["outcome"]] = tok
    ch = score_changes(_read("data/live/sports_*.jsonl"))
    md = mids(_read("data/live/market_*"))
    out = []
    for r in ch.itertuples():
        toks = by_game.get(r.gameId, {})
        tok = toks.get(r.home)
        if tok is None:
            continue
        sign = 1 if r.home_won else -1
        g = md[(md.asset == tok) & (md.ts >= r.rt - 90_000) & (md.ts <= r.rt + 30_000)]
        if len(g) < 3:
            continue
        dm = np.diff(g.mid.to_numpy()) * sign
        k = int(np.argmax(dm))
        if dm[k] < min_move:
            continue
        t_move = int(g.ts.iloc[k + 1])
        out.append({"gameId": r.gameId, "score": r.score, "feed_ms": r.rt, "move_ms": t_move,
                    "lead_s": (r.rt - t_move) / 1000, "move": float(dm[k])})
    return pd.DataFrame(out)


if __name__ == "__main__":
    L = leads()
    print(len(L), "score changes matched to a book move")
    if len(L):
        print(L.lead_s.describe(percentiles=[.1, .25, .5, .75, .9]).round(2))
        print("share where book moved first:", round((L.lead_s > 0).mean(), 3))
        L.to_csv("results/h4_leads.csv", index=False)
