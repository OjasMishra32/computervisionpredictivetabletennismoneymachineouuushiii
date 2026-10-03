"""Descriptive in-play book statistics for tennis side markets from the live_v2 recorder (read-only, local files).

Source: data/live_v2/clob_<run>_*.jsonl[.gz] (public CLOB market-channel websocket, recorded by src/live_recorder.py)
and clobmeta_<run>_*.jsonl[.gz] (token index -> market metadata).

What it measures (no strategy is evaluated, no P&L is computed):
  * once per minute of recorder time, for every subscribed side market (outcome-0 token; the outcome-1 book is its
    mirror) whose match has started and that has not resolved: the server's best bid / best ask (from the `pc` and
    `bba` events) and the size resting at those prices (from a book rebuilt from `b` snapshots + `pc` deltas, used
    only when the rebuilt best price equals the server's best price);
  * every tick_size_change event (tick 0.01 <-> 0.001) with the price at which it happened.

Usage: .venv/bin/python research/v2/maker/recorded_books.py [--run 20261003_1123] [--dump]
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT / "data" / "live_v2"
OUT = Path(__file__).resolve().parent / "out"
TOUR_LEAGUES = {"China Open", "Japan Open Tennis Championships"}
INPLAY_MAX_H = 5.0


def lines(path: Path):
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt") as f:
        for ln in f:
            try:
                yield json.loads(ln)
            except ValueError:  # last line of a file being written
                continue


def files(prefix: str, run: str) -> list[Path]:
    fs = [p for p in LIVE.glob(f"{prefix}_{run}_*.jsonl*")]
    return sorted(fs, key=lambda p: p.name.split(".")[0])


def tier_of(info: dict) -> str:
    title = info.get("title") or ""
    league = title.split(":")[0].replace(" (Doubles)", "")
    if "(Doubles)" in title:
        return "doubles"
    if league in TOUR_LEAGUES:
        return "tour"
    if (info.get("slug") or "").startswith("itf"):
        return "itf"
    return "challenger_other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="20261003_1123")
    ap.add_argument("--dump", action="store_true", help="also write the per-minute samples (csv.gz, ~4 MB)")
    a = ap.parse_args()

    meta: dict[int, dict] = {}
    for p in files("clobmeta", a.run):
        for r in lines(p):
            for k, v in r["tokens"].items():
                meta[int(k)] = v
    for v in meta.values():
        v["start_ms"] = dt.datetime.fromisoformat(v["start"].replace("Z", "+00:00")).timestamp() * 1000
        v["tier"] = tier_of(v)
    cond_idx: dict[str, list[int]] = {}
    for i, v in meta.items():
        cond_idx.setdefault(v["cond"], []).append(i)
    watch = {i for i, v in meta.items() if v.get("oi") == 0}

    bids: dict[int, dict] = {}
    asks: dict[int, dict] = {}
    bbo: dict[int, tuple] = {}
    resolved: set[int] = set()
    samples, ticks = [], []
    next_sample = None
    first_rt = last_rt = None

    for p in files("clob", a.run):
        for r in lines(p):
            rt = r.get("rt")
            if rt is None:
                continue
            first_rt = first_rt or rt
            last_rt = rt
            e = r.get("e")
            if e == "b":
                i = r["a"]
                bids[i] = {float(px): float(sz) for px, sz in r.get("b", [])}
                asks[i] = {float(px): float(sz) for px, sz in r.get("k", [])}
            elif e == "pc":
                for i, px, sz, side, bb, ba in r["c"]:
                    book = bids.setdefault(i, {}) if side == "B" else asks.setdefault(i, {})
                    if sz == 0:
                        book.pop(px, None)
                    else:
                        book[px] = sz
                    bbo[i] = (bb, ba)
            elif e == "bba":
                bbo[r["a"]] = (r.get("bb"), r.get("ba"))
            elif e == "market_resolved":
                for i in cond_idx.get((r.get("raw") or {}).get("market"), []):
                    resolved.add(i)
            elif e == "tick_size_change":
                raw = r.get("raw") or {}
                i = r.get("a")
                info = meta.get(i, {})
                ticks.append({"rt": rt, "cond": raw.get("market"), "smt": info.get("smt"), "old": raw.get("old_tick_size"),
                              "new": raw.get("new_tick_size"), "bb": bbo.get(i, (None, None))[0],
                              "ba": bbo.get(i, (None, None))[1]})
            if next_sample is None:
                next_sample = rt + 60_000
            if rt >= next_sample:
                for i in watch:
                    v = meta[i]
                    if i in resolved or i not in bbo:
                        continue
                    h = (rt - v["start_ms"]) / 3.6e6
                    if not (0 <= h <= INPLAY_MAX_H):
                        continue
                    bb, ba = bbo[i]
                    bb = float(bb) if bb is not None else 0.0
                    ba = float(ba) if ba is not None else 1.0
                    b_ok = bb > 0 and bids.get(i) and abs(max(bids[i]) - bb) < 1e-9
                    a_ok = ba < 1 and asks.get(i) and abs(min(asks[i]) - ba) < 1e-9
                    samples.append({"rt": rt, "idx": i, "cond": v["cond"], "smt": v["smt"], "tier": v["tier"],
                                    "title": v["title"], "h_in": round(h, 3), "bb": bb, "ba": ba,
                                    "two_sided": bb > 0 and ba < 1,
                                    "bid_sz": bids[i][bb] if b_ok else np.nan,
                                    "ask_sz": asks[i][ba] if a_ok else np.nan})
                next_sample = rt + 60_000

    s = pd.DataFrame(samples)
    s["spread_c"] = (s.ba - s.bb) * 100
    s["mid"] = (s.ba + s.bb) / 2
    s["side"] = s.smt != "moneyline"

    def summ(g: pd.DataFrame) -> dict:
        two = g[g.two_sided]
        inner = two[(two.mid >= 0.05) & (two.mid <= 0.95)]
        per_mkt = inner.groupby("cond").spread_c.median()
        def med(x):
            x = x.dropna()
            return None if len(x) == 0 else round(float(np.median(x)), 2)
        return {"market_minutes": int(len(g)), "markets": int(g.cond.nunique()),
                "share_two_sided": round(float(g.two_sided.mean()), 3) if len(g) else None,
                "share_no_bid_no_ask": round(float(((g.bb <= 0) & (g.ba >= 1)).mean()), 3) if len(g) else None,
                "two_sided_mid_5_95_minutes": int(len(inner)),
                "median_spread_c": med(inner.spread_c), "p25_spread_c": None if inner.empty else round(float(inner.spread_c.quantile(.25)), 2),
                "p75_spread_c": None if inner.empty else round(float(inner.spread_c.quantile(.75)), 2),
                "share_spread_le_1c": None if inner.empty else round(float((inner.spread_c <= 1.0001).mean()), 3),
                "share_spread_le_3c": None if inner.empty else round(float((inner.spread_c <= 3.0001).mean()), 3),
                "median_of_market_median_spread_c": med(per_mkt),
                "median_top_bid_shares": med(inner.bid_sz), "median_top_ask_shares": med(inner.ask_sz),
                "median_top_bid_usd": med(inner.bid_sz * inner.bb), "median_top_ask_usd": med(inner.ask_sz * inner.ba),
                "size_known_share": None if inner.empty else round(float(inner.bid_sz.notna().mean()), 3)}

    side = s[s.side]
    res = {"run": a.run, "first_rt_utc": dt.datetime.fromtimestamp(first_rt / 1000, dt.timezone.utc).isoformat(),
           "last_rt_utc": dt.datetime.fromtimestamp(last_rt / 1000, dt.timezone.utc).isoformat(),
           "inplay_window_h": INPLAY_MAX_H,
           "side_all": summ(side),
           "side_by_tier": {t: summ(g) for t, g in side.groupby("tier")},
           "side_by_type": {t: summ(g) for t, g in side.groupby("smt")},
           "side_tour_by_type": {t: summ(g) for t, g in side[side.tier == "tour"].groupby("smt")},
           "moneyline_by_tier": {t: summ(g) for t, g in s[~s.side].groupby("tier")},
           "tick_size_changes": {"n": len(ticks), "by_direction": dict(Counter(f"{t['old']}->{t['new']}" for t in ticks)),
                                 "examples": ticks[:12]}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"recorded_books_{a.run}.json").write_text(json.dumps(res, indent=1, default=str))
    if a.dump:
        s.to_csv(OUT / f"recorded_books_{a.run}_minutes.csv.gz", index=False)
    print(json.dumps({k: res[k] for k in ("first_rt_utc", "last_rt_utc", "side_all", "side_by_tier", "moneyline_by_tier")},
                     indent=1, default=str))
    print(json.dumps(res["tick_size_changes"]["by_direction"]))


if __name__ == "__main__":
    main()
