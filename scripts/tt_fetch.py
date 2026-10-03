"""Table tennis fetch for the pre-registered study (HYPOTHESIS_TT.md, commit 0f01362).

    python scripts/tt_fetch.py catalogue   # gamma: every closed event under tag 103767 and its child tags
    python scripts/tt_fetch.py trades      # data-api: the tape of every UTT market (resumable)
    python scripts/tt_fetch.py zerocheck   # data-api: does any zero-volume moneyline have a fill? (resumable)
    python scripts/tt_fetch.py unlisted    # data-api: full tapes of the zero-volume moneylines that have fills
    python scripts/tt_fetch.py compare     # redo the catalogue comparison from the saved walk (no network)

Public, keyless endpoints only (gamma-api, data-api); nothing here can place an order.

* `catalogue` re-walks gamma in one-day start-date windows (100 per page, offset cap 2,000) over the
  same window as the cached catalogue and keeps every market of every event, with all market types,
  fee fields, secondsDelay and tick. It is a completeness check and a record of the other market types.
  It does NOT change UTT: the pre-registration fixes UTT to the cached catalogue, which is not refreshed.
* `trades` calls src.polymarket.fetch_trades unchanged (same parsing, same cache under
  data/raw/trades/), with a back-off-only wrapper around its HTTP GET: at most 4 concurrent data-api
  requests, exponential back-off on 429/5xx and on network errors, and a non-list reply is retried
  instead of being cached as a short tape.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # src.polymarket caches under the relative path data/raw

import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import requests  # noqa: E402

from scripts import tt_build  # noqa: E402
from src import polymarket as pm  # noqa: E402

OUT = ROOT / "data/tt"
RES = ROOT / "research/tt"
LOG = OUT / "fetch.log"
TAG = "103767"
SINCE, UNTIL = "2025-07-01", "2026-10-03"  # the cached catalogue's window
SPORTS = "https://gamma-api.polymarket.com/sports"
DATA_CONC, GAMMA_CONC = 4, 4
CAP_FILLS = 10_000  # data-api offset cap: fetch_trades stops at offset 10,000 (<= 10,500 fills)

_sem = {"data": threading.BoundedSemaphore(DATA_CONC), "gamma": threading.BoundedSemaphore(GAMMA_CONC)}
_stats = {"requests": 0, "retries": 0, "http": {}}
_lock = threading.Lock()


def log(msg: str) -> None:
    line = f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def get_backoff(url: str, params: dict, tries: int = 9):
    """GET with <= 4 concurrent requests per host and exponential back-off (1, 2, 4, ... 60 s, jittered)."""
    host = "data" if "data-api" in url else "gamma"
    for k in range(tries):
        r, err = None, None
        with _sem[host]:
            try:
                r = pm._session.get(url, params=params, timeout=40)
            except requests.RequestException as e:
                err = e
        with _lock:
            _stats["requests"] += 1
            code = r.status_code if r is not None else "neterr"
            _stats["http"][code] = _stats["http"].get(code, 0) + 1
        if r is not None and r.status_code == 200:
            try:
                js = r.json()
            except ValueError:
                js = None
            if url == pm.TRADES and not isinstance(js, list):
                err = RuntimeError(f"non-list reply: {str(js)[:200]}")
            elif js is not None:
                return js
        elif r is not None and r.status_code != 429 and r.status_code < 500:
            raise RuntimeError(f"HTTP {r.status_code} {url} {params}: {r.text[:200]}")
        with _lock:
            _stats["retries"] += 1
        wait = min(60.0, 2.0 ** k) * (1 + 0.25 * random.random())
        if r is not None and r.headers.get("Retry-After", "").isdigit():
            wait = max(wait, float(r.headers["Retry-After"]))
        time.sleep(wait)
    raise RuntimeError(f"GET failed after {tries} tries: {url} {params} ({err or code})")


pm._get = get_backoff  # back-off-only wrapper; fetch_trades parsing and cache are unchanged


# ---------------------------------------------------------------- catalogue (gamma, metadata only)
def _market_rows(e: dict) -> list[dict]:
    rows = []
    for m in e.get("markets", []) or []:
        outs = json.loads(m.get("outcomes") or "[]")
        prices = json.loads(m.get("outcomePrices") or "[]")
        toks = json.loads(m.get("clobTokenIds") or "[]")
        fs = m.get("feeSchedule") or {}
        rows.append({
            "event_id": str(e.get("id")), "event_slug": e.get("slug"), "title": e.get("title"),
            "series": e.get("seriesSlug"), "start_time": e.get("startTime"), "event_start_date": e.get("startDate"),
            "closed_time": e.get("closedTime"), "finished": e.get("finishedTimestamp"),
            "tag_ids": ",".join(sorted(str(t.get("id")) for t in e.get("tags") or [])),
            "cond": m.get("conditionId"), "market_type": m.get("sportsMarketType"), "question": m.get("question"),
            "n_outcomes": len(outs), "out0": outs[0] if outs else None, "out1": outs[1] if len(outs) > 1 else None,
            "tok0": toks[0] if toks else None, "tok1": toks[1] if len(toks) > 1 else None,
            "res0": float(prices[0]) if prices else None,
            "volume": float(m["volume"]) if m.get("volume") not in (None, "") else 0.0,
            "volume_field_missing": m.get("volume") in (None, ""),
            "fee_rate": fs.get("rate"), "fee_exp": fs.get("exponent"), "fee_taker_only": fs.get("takerOnly"),
            "rebate_rate": fs.get("rebateRate"), "fees_enabled": m.get("feesEnabled"), "fee_type": m.get("feeType"),
            "maker_base_fee": m.get("makerBaseFee"), "taker_base_fee": m.get("takerBaseFee"),
            "seconds_delay": m.get("secondsDelay"), "tick": m.get("orderPriceMinTickSize"),
            "min_size": m.get("orderMinSize"), "uma_status": m.get("umaResolutionStatus"),
            "market_closed": m.get("closed"), "neg_risk": m.get("negRisk"),
        })
    return rows


def _pages(params: dict) -> tuple[list[dict], bool]:
    """Every closed event for `params`, 100 per page up to gamma's ~2,000 offset cap; flag if capped."""
    evs = []
    for offset in range(0, 2000, 100):
        page = pm._get(pm.GAMMA, {**params, "closed": "true", "limit": 100, "offset": offset})
        evs += page
        if len(page) < 100:
            return evs, False
    return evs, True


def _day(d: dt.date):
    lo, hi = d.isoformat(), (d + dt.timedelta(days=1)).isoformat()
    evs, capped = _pages({"tag_id": TAG, "start_date_min": lo, "start_date_max": hi})
    rows = [r for e in evs for r in _market_rows(e)]
    return d, len(evs), capped, rows


def catalogue() -> None:
    log("catalogue: start")
    sports = pm._get(SPORTS, {})
    kids = [s for s in sports if TAG in str(s.get("tags", "")).split(",")]
    child_tags = sorted({t for s in kids for t in str(s["tags"]).split(",")} - {"1", "100639", TAG})
    d0, d1 = dt.date.fromisoformat(SINCE), dt.date.fromisoformat(UNTIL)
    days = [d0 + dt.timedelta(days=i) for i in range((d1 - d0).days)]
    rows, per_day = [], []
    with ThreadPoolExecutor(GAMMA_CONC) as ex:
        for d, n, capped, r in ex.map(_day, days):
            rows += r
            per_day.append({"day": d.isoformat(), "events": n, "capped": capped})
    g = pd.DataFrame(rows).drop_duplicates(["event_id", "cond"]).reset_index(drop=True)
    g.to_parquet(OUT / "gamma_markets.parquet")
    pd.DataFrame(per_day).to_csv(OUT / "gamma_days.csv", index=False)
    main_ids = set(g.event_id)
    # each child tag without a date window (pages up to the offset cap): are its events all in the walk?
    child = []
    for t in child_tags:
        evs, capped = _pages({"tag_id": t})
        ids = {str(e["id"]) for e in evs}
        inwin = {str(e["id"]) for e in evs if SINCE <= (e.get("startDate") or "")[:10] < UNTIL}
        child.append({"tag_id": t, "sport": ",".join(s["sport"] for s in kids if s.get("primaryTagId") == int(t)) or None,
                      "closed_events_seen": len(ids), "offset_capped": capped,
                      "in_window": len(inwin), "in_window_missing_from_walk": len(inwin - main_ids),
                      "series": ",".join(sorted({str(e.get("seriesSlug")) for e in evs}))})
    child = pd.DataFrame(child)
    child.to_csv(RES / "child_tags.csv", index=False)
    log(f"catalogue: {len(main_ids)} events, {len(g)} markets, capped days {sum(p['capped'] for p in per_day)}")
    compare(g, child)


def compare(g: pd.DataFrame, child: pd.DataFrame) -> dict:
    """Fresh gamma walk vs the cached (pre-registered) catalogue. Metadata only."""
    cat = pd.read_parquet(tt_build.CAT)
    ml = g[g.market_type == "moneyline"]
    two = ml[(ml.n_outcomes == 2) & ml.tok1.notna()]
    fresh = two.set_index("cond")
    c = cat.set_index("cond")
    both = c.index.intersection(fresh.index)
    vol_up = both[(fresh.loc[both, "volume"] > 0) & (c.loc[both, "volume"] == 0)]
    vol_diff = both[(fresh.loc[both, "volume"] - c.loc[both, "volume"]).abs() > 0.01]
    u = tt_build.universe()
    types = g.groupby("market_type", dropna=False).agg(markets=("cond", "size"), events=("event_id", "nunique"),
                                                        with_volume=("volume", lambda s: int((s > 0).sum())),
                                                        listed_usd=("volume", "sum"))
    types.index = types.index.fillna("(none)")
    by_series = g.assign(ml=g.market_type == "moneyline").groupby("series", dropna=False).agg(
        events=("event_id", "nunique"), markets=("cond", "size"), moneylines=("ml", "sum"))
    by_series.index = by_series.index.fillna("(none)")
    utt_fresh = fresh.reindex(u.cond)
    out = {
        "window": [SINCE, UNTIL], "events": int(g.event_id.nunique()), "markets_all_types": int(len(g)),
        "events_without_moneyline": int(g.event_id.nunique() - ml.event_id.nunique()),
        "events_with_gt1_moneyline": int((ml.groupby("event_id").size() > 1).sum()),
        "moneylines": int(len(ml)), "moneylines_2_outcomes": int(len(two)),
        "cached_catalogue_rows": int(len(cat)), "cached_in_fresh": int(len(both)),
        "cached_missing_from_fresh": int(len(c.index.difference(fresh.index))),
        "fresh_not_in_cached": int(len(fresh.index.difference(c.index))),
        "fresh_not_in_cached_with_volume": int((fresh.loc[fresh.index.difference(c.index), "volume"] > 0).sum()),
        "volume_changed_gt_1c": int(len(vol_diff)), "zero_in_cache_but_volume_now": int(len(vol_up)),
        "utt_in_fresh": int(utt_fresh.volume.notna().sum()),
        "utt_res0_changed": int((utt_fresh.res0.to_numpy() != u.res0.to_numpy()).sum()),
        "utt_fee_rate_changed": int((utt_fresh.fee_rate.fillna(0).to_numpy() != u.fee_rate.to_numpy()).sum()),
        "utt_delay_changed": int((utt_fresh.seconds_delay.fillna(1).to_numpy() != u.delay.to_numpy()).sum()),
        "utt_tick_now": utt_fresh.tick.value_counts(dropna=False).to_dict(),
        "utt_fee_schedule_now": {str(k): int(v) for k, v in utt_fresh.groupby(
            ["fee_rate", "fee_exp", "fee_taker_only", "rebate_rate"], dropna=False).size().items()},
        "utt_fees_enabled_now": utt_fresh.fees_enabled.astype(str).value_counts().to_dict(),
        "utt_min_size_now": utt_fresh.min_size.astype(str).value_counts().to_dict(),
        "market_types": types.round(2).to_dict("index"),
        "by_series": by_series.to_dict("index"),
        "child_tags": child.to_dict("records"),
    }
    RES.mkdir(parents=True, exist_ok=True)
    (RES / "catalogue_check.json").write_text(json.dumps(out, indent=1, default=str))
    log("catalogue check: " + json.dumps({k: v for k, v in out.items() if isinstance(v, int)}))
    return out


# ---------------------------------------------------------------- trades (data-api)
def _cached(cond: str) -> Path:
    return pm.RAW / "trades" / f"{cond}.parquet"


def manifest(u: pd.DataFrame, failed: dict, name: str = "") -> pd.DataFrame:
    rows = []
    for c in u.cond:
        f = _cached(c)
        n = pq.ParquetFile(f).metadata.num_rows if f.exists() else None
        first = None
        if n:
            first = int(pd.read_parquet(f, columns=["timestamp"]).timestamp.min())
        rows.append({"cond": c, "fetched": f.exists(), "fills": n, "first_ts": first,
                     "capped": bool(n is not None and n >= CAP_FILLS), "error": failed.get(c)})
    m = pd.DataFrame(rows).merge(u[["cond", "league", "oos", "start", "volume"]], on="cond")
    m.to_parquet(OUT / f"fetch_manifest{name}.parquet")
    return m


def trades(name: str = "") -> None:
    if name == "":
        u, what = tt_build.universe(), "UTT"
    else:  # zero-listed-volume moneylines with >= 1 fill (zerocheck); not part of UTT
        z = pd.read_parquet(OUT / "zero_volume_check.parquet")
        cat = pd.read_parquet(tt_build.CAT)
        u = cat[cat.cond.isin(set(z[z.n_first_page > 0].cond))].copy()
        u["start"] = pd.to_datetime(u.start_time, utc=True)
        u["league"] = tt_build.league_of(u.series)
        u["oos"] = u.start >= tt_build.EXPECT["cut"]
        what = "unlisted (listed volume 0, >= 1 fill)"
    todo = [c for c in u.cond if not _cached(c).exists()]
    log(f"trades: {what} {len(u)} markets, {len(u) - len(todo)} cached, {len(todo)} to fetch "
        f"(rule: every market of the set, no sampling; <= {DATA_CONC} concurrent data-api requests)")
    t0, failed = time.time(), {}
    with ThreadPoolExecutor(DATA_CONC) as ex:
        futs = {ex.submit(pm.fetch_trades, c): c for c in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                f.result()
            except Exception as err:  # a failed market is listed, never silently dropped
                failed[futs[f]] = repr(err)[:300]
                log(f"trades: FAILED {futs[f]} {err!r}"[:400])
            if i % 250 == 0:
                log(f"trades: {i}/{len(todo)} done, {len(failed)} failed, {time.time() - t0:.0f}s, http {_stats['http']}")
    m = manifest(u, failed, name)
    (OUT / f"fetch_failed{name}.txt").write_text("".join(f"{c}\t{e}\n" for c, e in failed.items()))
    log(f"trades: done in {time.time() - t0:.0f}s; fetched {int(m.fetched.sum())}/{len(m)}, failed {len(failed)}, "
        f"with fills {int((m.fills > 0).sum())}, fills {int(m.fills.fillna(0).sum())}, capped {int(m.capped.sum())}; "
        f"requests {_stats['requests']}, retries {_stats['retries']}, http {_stats['http']}")


def zerocheck(chunk: int = 1000) -> None:
    """One request (limit=1) per zero-volume moneyline in the cached catalogue: does it have any fill?"""
    cat = pd.read_parquet(tt_build.CAT)
    z = cat[cat.volume <= 0][["cond", "series", "start_time", "res0"]].reset_index(drop=True)
    out_f = OUT / "zero_volume_check.parquet"
    done = pd.read_parquet(out_f) if out_f.exists() else pd.DataFrame(columns=["cond", "n_first_page", "error"])
    todo = z[~z.cond.isin(set(done.cond))].cond.tolist()
    log(f"zerocheck: {len(z)} zero-volume moneylines, {len(todo)} to check")

    def one(c):
        try:
            page = pm._get(pm.TRADES, {"market": c, "limit": 1, "offset": 0})
            return c, len(page), None
        except Exception as err:
            return c, None, repr(err)[:300]

    parts = [done]
    with ThreadPoolExecutor(DATA_CONC) as ex:
        for k in range(0, len(todo), chunk):
            res = pd.DataFrame(list(ex.map(one, todo[k:k + chunk])), columns=["cond", "n_first_page", "error"])
            parts.append(res)
            pd.concat(parts, ignore_index=True).to_parquet(out_f)
            log(f"zerocheck: {min(k + chunk, len(todo))}/{len(todo)}; with a fill so far "
                f"{int((pd.concat(parts).n_first_page.fillna(0) > 0).sum())}, errors {int(pd.concat(parts).error.notna().sum())}")
    r = pd.concat(parts, ignore_index=True).merge(z, on="cond")
    r.to_parquet(out_f)
    log(f"zerocheck: done; {len(r)} checked, with >= 1 fill {int((r.n_first_page.fillna(0) > 0).sum())}, "
        f"errors {int(r.error.notna().sum())}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    RES.mkdir(parents=True, exist_ok=True)
    stage = sys.argv[1] if len(sys.argv) > 1 else "trades"
    if stage == "compare":  # re-run the comparison on the saved walk (no network)
        compare(pd.read_parquet(OUT / "gamma_markets.parquet"), pd.read_csv(RES / "child_tags.csv", dtype={"tag_id": str}))
    else:
        {"catalogue": catalogue, "trades": trades, "zerocheck": zerocheck,
         "unlisted": lambda: trades("_unlisted")}[stage]()
