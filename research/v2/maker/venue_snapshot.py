"""Live venue-rule and order-book snapshot for Polymarket tennis side markets (read-only).

Public, keyless GET endpoints only:
  gamma-api  /events?tag_slug=tennis      market list + venue fields (secondsDelay, tick, min size, feeSchedule)
  clob       /book?token_id=...           current order book for outcome 0 (and outcome 1 on a mirror-check subset)
  clob       /markets/{condition_id}      CLOB-side market parameters (subset)
  clob       /clob-markets/{condition_id} compact CLOB parameters incl. fee details (fd), clear-book-on-start (cbos)

No orders, no keys, no signing. <= 3 concurrent requests, exponential back-off on 429/5xx.

Usage (from repo root):
  .venv/bin/python research/v2/maker/venue_snapshot.py --repeat 3 --gap 120
Writes research/v2/maker/out/venue_snapshot_<UTC>.json and books_<UTC>.csv.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

GAMMA = "https://gamma-api.polymarket.com/events"
CLOB = "https://clob.polymarket.com"
OUT = Path(__file__).resolve().parent / "out"
WORKERS = 3
# Tour-level (ATP/WTA 500+) events on the calendar this week; everything else on the atp/wta series is
# Challenger/125/250-level. Dated to the 2026-10-03 snapshot.
TOUR_LEAGUES = {"China Open", "Japan Open Tennis Championships"}

S = requests.Session()
S.headers["User-Agent"] = "courtside-research/0.1 (read-only)"


def get(url: str, params: dict | None = None, tries: int = 6):
    for k in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(30, 0.5 * 2 ** k))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(min(30, 0.5 * 2 ** k))
    raise RuntimeError(f"GET failed: {url} {params}")


def ts(s: str | None):
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))


def tennis_events(now: dt.datetime) -> list[dict]:
    """Open tennis events created in the last 6 days (covers today's in-play and tomorrow's slate)."""
    lo = (now - dt.timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for off in range(0, 3000, 100):
        page = get(GAMMA, {"tag_slug": "tennis", "closed": "false", "limit": 100, "offset": off,
                           "start_date_min": lo, "order": "startDate", "ascending": "false"})
        out += page
        if len(page) < 100:
            break
    return out


def market_rows(events: list[dict], now: dt.datetime) -> pd.DataFrame:
    rows = []
    for e in events:
        st = ts(e.get("startTime"))
        if st is None or e.get("ended") is True:
            continue
        mins = (now - st).total_seconds() / 60
        if 0 <= mins <= 300:
            state = "in_play"
        elif -24 * 60 <= mins < 0:
            state = "pre_match"
        else:
            continue
        series = e.get("seriesSlug") or ""
        league = (e.get("eventMetadata") or {}).get("league")
        if series.endswith("-doubles"):
            tier = "doubles"
        elif series == "itf":
            tier = "itf"
        elif league in TOUR_LEAGUES:
            tier = "tour"
        else:
            tier = "challenger_other"
        for m in e.get("markets", []):
            if not m.get("acceptingOrders") or m.get("closed"):
                continue
            toks = json.loads(m.get("clobTokenIds") or "[]")
            if len(toks) != 2:
                continue
            fs = m.get("feeSchedule") or {}
            rows.append({
                "event_id": e["id"], "event": e.get("title"), "series": series, "league": league, "tier": tier,
                "state": state, "mins_since_start": round(mins, 1),
                "event_live_flag": e.get("live"), "score": e.get("score"),
                "cond": m["conditionId"], "smt": m.get("sportsMarketType"), "title": m.get("groupItemTitle"),
                "tok0": toks[0], "tok1": toks[1],
                "seconds_delay": m.get("secondsDelay"), "tick": m.get("orderPriceMinTickSize"),
                "min_size": m.get("orderMinSize"), "fees_enabled": m.get("feesEnabled"), "fee_type": m.get("feeType"),
                "fee_rate": fs.get("rate"), "fee_exp": fs.get("exponent"), "taker_only": fs.get("takerOnly"),
                "rebate_rate": fs.get("rebateRate"), "clear_book_on_start": m.get("clearBookOnStart"),
                "rewards_min_size": m.get("rewardsMinSize"), "rewards_max_spread": m.get("rewardsMaxSpread"),
                "maker_base_fee": m.get("makerBaseFee"), "taker_base_fee": m.get("takerBaseFee"),
                "volume": float(m.get("volume") or 0),
            })
    return pd.DataFrame(rows)


def book_stats(b: dict) -> dict:
    bids = sorted(((float(x["price"]), float(x["size"])) for x in b.get("bids", [])), reverse=True)
    asks = sorted((float(x["price"]), float(x["size"])) for x in b.get("asks", []))
    d = {"n_bid_lvls": len(bids), "n_ask_lvls": len(asks), "book_ts": b.get("timestamp"),
         "last_trade": b.get("last_trade_price") or None, "book_tick": b.get("tick_size"),
         "book_min_size": b.get("min_order_size")}
    d["bid"] = bids[0][0] if bids else np.nan
    d["ask"] = asks[0][0] if asks else np.nan
    d["bid_sz"] = bids[0][1] if bids else 0.0
    d["ask_sz"] = asks[0][1] if asks else 0.0
    d["bid_usd"] = d["bid_sz"] * d["bid"] if bids else 0.0
    d["ask_usd"] = d["ask_sz"] * (1 - d["ask"]) if asks else 0.0  # $ a buyer of outcome 1 would post = seller's risk
    d["ask_usd_notional"] = d["ask_sz"] * d["ask"] if asks else 0.0
    d["spread_c"] = (d["ask"] - d["bid"]) * 100 if bids and asks else np.nan
    if bids and asks:
        mid = (d["bid"] + d["ask"]) / 2
        d["mid"] = mid
        d["bid_sz_2c"] = sum(s for p, s in bids if p >= mid - 0.02)
        d["ask_sz_2c"] = sum(s for p, s in asks if p <= mid + 0.02)
        d["bid_sz_5c"] = sum(s for p, s in bids if p >= mid - 0.05)
        d["ask_sz_5c"] = sum(s for p, s in asks if p <= mid + 0.05)
    d["book_usd_total"] = sum(p * s for p, s in bids) + sum(p * s for p, s in asks)
    return d


def fetch_books(tokens: list[str]) -> dict[str, dict]:
    with ThreadPoolExecutor(WORKERS) as ex:
        res = list(ex.map(lambda t: get(f"{CLOB}/book", {"token_id": t}), tokens))
    return dict(zip(tokens, res))


def snapshot(df: pd.DataFrame) -> pd.DataFrame:
    t0 = dt.datetime.now(dt.timezone.utc)
    books = fetch_books(df.tok0.tolist())
    st = pd.DataFrame([book_stats(books[t]) for t in df.tok0])
    out = pd.concat([df.reset_index(drop=True), st], axis=1)
    out["snap_utc"] = t0.isoformat()
    return out


def summarise(b: pd.DataFrame) -> dict:
    two = b[b.bid.notna() & b.ask.notna()]
    inner = two[(two.mid >= 0.05) & (two.mid <= 0.95)]
    def med(s):
        return None if len(s) == 0 else round(float(np.median(s)), 3)
    def q(s, p):
        return None if len(s) == 0 else round(float(np.quantile(s, p)), 3)
    return {
        "n_markets": int(len(b)), "n_events": int(b.event_id.nunique()),
        "share_empty": round(float((b.n_bid_lvls.eq(0) & b.n_ask_lvls.eq(0)).mean()), 3) if len(b) else None,
        "share_one_sided": round(float((b.n_bid_lvls.eq(0) ^ b.n_ask_lvls.eq(0)).mean()), 3) if len(b) else None,
        "n_two_sided": int(len(two)), "n_two_sided_mid_5_95": int(len(inner)),
        "two_sided": {
            "median_spread_c": med(two.spread_c), "p25_spread_c": q(two.spread_c, .25), "p75_spread_c": q(two.spread_c, .75),
            "share_spread_1tick": round(float((two.spread_c <= 1.0001).mean()), 3) if len(two) else None,
            "median_top_bid_shares": med(two.bid_sz), "median_top_ask_shares": med(two.ask_sz),
            "median_top_bid_usd": med(two.bid_usd), "median_top_ask_notional_usd": med(two.ask_usd_notional),
            "median_shares_within_2c_bid": med(two.bid_sz_2c), "median_shares_within_2c_ask": med(two.ask_sz_2c),
        },
        "two_sided_mid_5_95": {
            "median_spread_c": med(inner.spread_c), "p25_spread_c": q(inner.spread_c, .25), "p75_spread_c": q(inner.spread_c, .75),
            "median_top_bid_shares": med(inner.bid_sz), "median_top_ask_shares": med(inner.ask_sz),
            "median_top_bid_usd": med(inner.bid_usd), "median_top_ask_notional_usd": med(inner.ask_usd_notional),
            "median_shares_within_2c_bid": med(inner.bid_sz_2c), "median_shares_within_2c_ask": med(inner.ask_sz_2c),
            "median_shares_within_5c_bid": med(inner.bid_sz_5c), "median_shares_within_5c_ask": med(inner.ask_sz_5c),
        },
    }


def mirror_check(b: pd.DataFrame, k: int = 12) -> list[dict]:
    """Does outcome 1's book mirror outcome 0's (bid1 = 1 - ask0, same sizes)? Both books fetched together, fresh."""
    two = b[b.bid.notna() & b.ask.notna() & (b.spread_c < 20)].drop_duplicates("cond").head(k)
    out = []
    for _, r in two.iterrows():
        b0, b1 = get(f"{CLOB}/book", {"token_id": r.tok0}), get(f"{CLOB}/book", {"token_id": r.tok1})
        s0, s1 = book_stats(b0), book_stats(b1)
        ok = (s0["n_bid_lvls"] == s1["n_ask_lvls"] and s0["n_ask_lvls"] == s1["n_bid_lvls"]
              and abs((1 - s0["ask"]) - s1["bid"]) < 1e-9 and abs((1 - s0["bid"]) - s1["ask"]) < 1e-9
              and abs(s0["ask_sz"] - s1["bid_sz"]) < 1e-6 and abs(s0["bid_sz"] - s1["ask_sz"]) < 1e-6)
        out.append({"cond": r.cond, "smt": r.smt, "bid0": s0["bid"], "ask0": s0["ask"], "bid1": s1["bid"],
                    "ask1": s1["ask"], "bid0_sz": s0["bid_sz"], "ask1_sz": s1["ask_sz"], "mirrors": bool(ok)})
    return out


def clob_params(conds: list[str]) -> list[dict]:
    out = []
    for c in conds:
        m = get(f"{CLOB}/markets/{c}")
        cm = get(f"{CLOB}/clob-markets/{c}")
        out.append({"cond": c, "question": m.get("question"),
                    "markets": {k: m.get(k) for k in ("minimum_order_size", "minimum_tick_size", "seconds_delay",
                                                      "maker_base_fee", "taker_base_fee", "accepting_orders",
                                                      "game_start_time", "rewards")},
                    "clob_markets": cm})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--gap", type=float, default=120.0)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%MZ")
    events = tennis_events(now)
    allm = market_rows(events, now)
    side = allm[allm.smt.notna() & (allm.smt != "moneyline")].reset_index(drop=True)
    ml = allm[allm.smt == "moneyline"].reset_index(drop=True)

    # venue fields across every open tennis market in the window (side + moneyline)
    venue = {}
    for col in ("seconds_delay", "tick", "min_size", "fee_rate", "fee_exp", "taker_only", "rebate_rate",
                "fee_type", "clear_book_on_start", "fees_enabled", "maker_base_fee", "taker_base_fee",
                "rewards_min_size", "rewards_max_spread"):
        venue[col] = {str(k): int(v) for k, v in Counter(allm[col].astype(str)).items()}
    venue_by_state = {s: {c: {str(k): int(v) for k, v in Counter(g[c].astype(str)).items()}
                          for c in ("seconds_delay", "tick", "min_size", "fee_rate", "rebate_rate")}
                      for s, g in allm.groupby("state")}

    # every in-play side market on each repeat; pre-match once: every tour-level side market plus a fixed
    # random sample of <= 300 of the rest
    inp = side[side.state == "in_play"]
    pre = side[side.state == "pre_match"]
    rest = pre[pre.tier != "tour"]
    pre = pd.concat([pre[pre.tier == "tour"], rest.sample(min(300, len(rest)), random_state=0)])
    snaps = []
    for i in range(a.repeat):
        snaps.append(snapshot(pd.concat([inp, pre]) if i == 0 else inp))
        if i + 1 < a.repeat:
            time.sleep(a.gap)
    books = pd.concat(snaps, ignore_index=True)
    ml_snap = snapshot(ml[ml.state == "in_play"]) if (ml.state == "in_play").any() else pd.DataFrame()

    summ = {"by_state": {}, "by_state_tier": {}, "by_state_type": {}}
    for s, g in books.groupby("state"):
        summ["by_state"][s] = summarise(g)
        summ["by_state_tier"][s] = {t: summarise(gg) for t, gg in g.groupby("tier")}
        summ["by_state_type"][s] = {t: summarise(gg) for t, gg in g.groupby("smt")}
    if len(ml_snap):
        summ["moneyline_in_play"] = summarise(ml_snap)

    sub = books[(books.state == "in_play")].drop_duplicates("cond")
    pick = pd.concat([sub[sub.bid.notna() & sub.ask.notna()].head(4), sub[sub.bid.isna() & sub.ask.isna()].head(2),
                      books[books.state == "pre_match"].drop_duplicates("cond").head(2)])
    res = {
        "snapshot_utc": now.isoformat(), "repeat": a.repeat, "gap_s": a.gap,
        "n_events_fetched": len(events), "n_open_markets_in_window": int(len(allm)),
        "n_side_markets": {k: int(v) for k, v in side.state.value_counts().items()},
        "venue_fields_all_open_tennis_markets": venue, "venue_fields_by_state": venue_by_state,
        "book_summary": summ,
        "mirror_check": mirror_check(books),
        "clob_params_sample": clob_params(pick.cond.tolist()),
    }
    (OUT / f"venue_snapshot_{stamp}.json").write_text(json.dumps(res, indent=1, default=str))
    keep = [c for c in books.columns if c not in ("tok0", "tok1")]
    books[keep].to_csv(OUT / f"books_{stamp}.csv", index=False)
    print(json.dumps({k: res[k] for k in ("snapshot_utc", "n_events_fetched", "n_open_markets_in_window",
                                          "n_side_markets")}, default=str))
    print(json.dumps(summ["by_state"], indent=1, default=str))
    print(json.dumps({s: {t: {k: v[k] for k in ("n_markets", "share_empty", "share_one_sided", "n_two_sided")}
                          | v["two_sided_mid_5_95"] for t, v in d.items()} for s, d in summ["by_state_tier"].items()},
                     indent=1, default=str))
    print("mirror:", [m["mirrors"] for m in res["mirror_check"]])
    print(stamp)


if __name__ == "__main__":
    main()
