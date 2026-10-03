"""(A) data build for the maker v1 blind OOS test (PREREG.md section 2.2). Computes no P&L.

Steps (each cached, so a rerun never hits the network twice):
  1. catalogue  Gamma /events by id, 50 per request, sequential, with the fields and parsing of
                crossmarket/fetch_events.py (plus makerBaseFee / takerBaseFee, and rebateRate / takerOnly
                from feeSchedule). Output: data/v2_maker/oos/side_markets.parquet
  2. tapes      data-api /trades per selected side market, as crossmarket/fetch_tapes.py: <= 4 concurrent,
                exponential back-off on 429/5xx, the same 10,500-fill offset cap.
                Cached to data/v2_maker/oos/trades/ (separate from the IS cache).
  3. tables     per-print and interval tables with the logic of crossmarket/build.py: process, using the raw
                OOS moneyline tape (src.tape.load_tape) as the signal input. The markout columns
                (mo60, mo300, mo_res) are NOT computed; the jump columns are left NaN (always-on window).
The build prints counts only: events, side markets by type, tapes, prints, intervals, excluded markets.

Sample (PREREG 2.1): src.tape.universe() rows with oos == True and start in [2026-08-25 14:15, 2026-10-03 14:00) UTC;
side markets of the six frozen types with Gamma volume >= $250 and a resolved outcomePrices
((1,0), (0,1) or (0.5,0.5)); totals markets whose outcome 0 is not "Over..." are skipped and counted.

Read-only: public keyless endpoints only. No order code, no keys.

Run from the repo root:
  .venv/bin/python research/v2/maker/oos_build.py                 # all three steps
  .venv/bin/python research/v2/maker/oos_build.py --step tapes
  .venv/bin/python research/v2/maker/oos_build.py --check-is 400  # build-code parity on IS events (IS data only)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CM = ROOT / "research" / "v2" / "crossmarket"
sys.path.insert(0, str(CM))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # src.polymarket.RAW is relative to the repo root

from common import GAMMA, OOS_CUT, TRADES, get, universe_is  # noqa: E402
from fetch_events import BATCH, align  # noqa: E402
from src.tape import load_tape, universe  # noqa: E402
from src.tiers import _mid_series  # noqa: E402

CACHE = ROOT / "data" / "v2_maker" / "oos"
TRADES_DIR = CACHE / "trades"
IS_TRADES_DIR = ROOT / "data" / "v2_crossmarket" / "trades"
OOS_START = pd.Timestamp("2026-08-25 14:15", tz="UTC")
OOS_END = pd.Timestamp("2026-10-03 14:00", tz="UTC")
MIN_VOL = 250.0
TYPES = ("tennis_first_set_winner", "tennis_set_winner", "tennis_set_handicap",
         "tennis_match_totals", "tennis_set_totals", "tennis_first_set_totals")
TOTALS = ("tennis_match_totals", "tennis_set_totals", "tennis_first_set_totals")
SLIM_FIELDS = ("conditionId", "sportsMarketType", "groupItemTitle", "question", "line",
               "outcomes", "outcomePrices", "volume", "secondsDelay", "feeSchedule",
               "clobTokenIds", "closedTime", "orderPriceMinTickSize", "gameStartTime",
               "makerBaseFee", "takerBaseFee")
FIELDS = ("timestamp", "side", "outcomeIndex", "price", "size", "proxyWallet", "transactionHash")
MAX_GAP = 300
WORKERS = 2


# ------------------------------------------------------------------ sample
def oos_universe() -> pd.DataFrame:
    u = universe()
    o = u[u.oos & (u.start >= OOS_START) & (u.start < OOS_END)].copy()
    o["event_id"] = o.event_id.astype(str)
    isu = universe_is()
    assert (o.start >= OOS_CUT).all(), "OOS universe has a match before the OOS cut"
    assert not o.event_id.isin(isu.event_id.astype(str)).any(), "OOS event also in universe_is"
    assert not o.cond.isin(isu.cond).any(), "OOS moneyline also in universe_is"
    return o.reset_index(drop=True)


# ------------------------------------------------------------------ 1. catalogue
def catalogue() -> pd.DataFrame:
    u = oos_universe()
    raw = CACHE / "events_raw"
    raw.mkdir(parents=True, exist_ok=True)
    ids = u.event_id.tolist()
    rows = []
    for k in range(0, len(ids), BATCH):
        chunk = ids[k:k + BATCH]
        f = raw / f"batch_{k:06d}.json"
        if f.exists():
            evs = json.loads(f.read_text())
        else:
            evs = get(GAMMA, [("id", i) for i in chunk] + [("limit", BATCH)])
            evs = [{"id": e["id"], "slug": e.get("slug"),
                    "markets": [{x: m.get(x) for x in SLIM_FIELDS} for m in e.get("markets", [])]}
                   for e in evs]
            f.write_text(json.dumps(evs))
            time.sleep(0.25)
        for e in evs:
            for m in e["markets"]:
                rows.append({"event_id": str(e["id"]), **m})
    m = pd.DataFrame(rows)
    got = set(m.event_id) if len(m) else set()
    ml = u.set_index("event_id")
    m = m[m.event_id.isin(ml.index)]
    m = m[m.sportsMarketType != "moneyline"].copy()
    # same derived columns as fetch_events.py
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
    n_not_binary = int(((outs.map(len) != 2) | (toks.map(len) != 2)).sum())
    m = m[(outs.map(len) == 2) & (toks.map(len) == 2)].copy()
    outs, pr, toks = outs[m.index], pr[m.index], toks[m.index]
    m["out0"] = outs.map(lambda x: x[0])
    m["out1"] = outs.map(lambda x: x[1])
    m["res_s0"] = pr.map(lambda x: float(x[0]) if x else float("nan"))
    m["res_s1"] = pr.map(lambda x: float(x[1]) if len(x) > 1 else float("nan"))
    m["tok0"] = toks.map(lambda x: x[0])
    m["tok1"] = toks.map(lambda x: x[1])
    m["volume"] = m.volume.astype(float).fillna(0.0)
    fs = m.feeSchedule.map(lambda d: d or {})
    m["fee_rate"] = fs.map(lambda d: d.get("rate")).astype(float)
    m["fee_rate"] = m.fee_rate.fillna(m.ml_fee).fillna(0.0)
    m["rebate_rate"] = fs.map(lambda d: d.get("rebateRate")).astype(float)
    m["taker_only"] = fs.map(lambda d: d.get("takerOnly"))
    m["maker_base_fee"] = pd.to_numeric(m.makerBaseFee, errors="coerce")
    m["taker_base_fee"] = pd.to_numeric(m.takerBaseFee, errors="coerce")
    m["delay"] = m.secondsDelay.fillna(m.ml_delay).astype(int)
    m["line"] = pd.to_numeric(m.line, errors="coerce")
    ml0 = m.event_id.map(ml.out0)
    ml1 = m.event_id.map(ml.out1)
    m["align0"] = [align(o, a, b, t) for o, a, b, t in zip(m.out0, ml0, ml1, m.sportsMarketType)]
    m = m.rename(columns={"conditionId": "cond", "sportsMarketType": "smt", "groupItemTitle": "title"})
    m = m.drop(columns=["outcomes", "outcomePrices", "clobTokenIds", "feeSchedule", "makerBaseFee", "takerBaseFee"])
    m = m.drop_duplicates("cond").reset_index(drop=True)
    # PREREG 2.1 selection flags (kept in the table, applied in the tapes/tables steps)
    m["type_ok"] = m.smt.isin(TYPES)
    m["vol_ok"] = m.volume >= MIN_VOL
    pair = list(zip(m.res_s0, m.res_s1))
    m["resolved"] = [p in ((1.0, 0.0), (0.0, 1.0), (0.5, 0.5)) for p in pair]
    m["totals_not_over"] = m.smt.isin(TOTALS) & ~m.out0.astype(str).str.strip().str.lower().str.startswith("over")
    m["selected"] = m.type_ok & m.vol_ok & m.resolved & ~m.totals_not_over
    assert (m.start >= OOS_START).all() and (m.start < OOS_END).all()
    assert not m.event_id.isin(universe_is().event_id.astype(str)).any()
    m.to_parquet(CACHE / "side_markets.parquet")
    print(f"OOS events in window: {len(u)}; events returned by Gamma: {len(got)}; "
          f"events with side markets: {m.event_id.nunique()}; side markets: {len(m)}; "
          f"non-binary dropped: {n_not_binary}")
    t = m.groupby("smt").agg(markets=("cond", "size"), vol_ge_250=("vol_ok", "sum"),
                             resolved=("resolved", "sum"), totals_not_over=("totals_not_over", "sum"),
                             selected=("selected", "sum"))
    print(t.to_string())
    ex = m[m.type_ok]
    print("six-type markets excluded: volume < $250:", int((~ex.vol_ok).sum()),
          "| vol ok but unresolved:", int((ex.vol_ok & ~ex.resolved).sum()),
          "| totals not 'Over':", int((ex.vol_ok & ex.resolved & ex.totals_not_over).sum()))
    print("fee metadata (six types):", ex.groupby(["delay", "fee_rate", "rebate_rate", "taker_only"],
                                                    dropna=False).size().to_dict())
    print("maker fee check: takerOnly false:", int((ex.taker_only == False).sum()),  # noqa: E712
          "| takerOnly missing:", int(ex.taker_only.isna().sum()),
          "| makerBaseFee > 0:", int((ex.maker_base_fee > 0).sum()),
          "| makerBaseFee missing:", int(ex.maker_base_fee.isna().sum()))
    return m


def side_markets() -> pd.DataFrame:
    sm = pd.read_parquet(CACHE / "side_markets.parquet")
    assert (sm.start >= OOS_CUT).all()
    return sm


# ------------------------------------------------------------------ 2. tapes
def fetch(cond: str) -> int:
    """Same as crossmarket/fetch_tapes.py: fetch, OOS cache directory."""
    f = TRADES_DIR / f"{cond}.parquet"
    if f.exists():
        return -1
    out = []
    for offset in range(0, 10001, 500):
        page = get(TRADES, {"market": cond, "limit": 500, "offset": offset})
        if not isinstance(page, list) or not page:
            break
        out += [{k: r.get(k) for k in FIELDS} for r in page]
        if len(page) < 500:
            break
    df = pd.DataFrame(out, columns=list(FIELDS))
    if len(df):
        df = df.drop_duplicates().sort_values("timestamp", kind="stable").reset_index(drop=True)
    tmp = f.with_suffix(".tmp")
    df.to_parquet(tmp)
    tmp.rename(f)
    return len(df)


def tapes(workers: int = 4):
    assert workers <= 4
    sm = side_markets()
    sm = sm[sm.selected].sort_values("start", ascending=False)
    TRADES_DIR.mkdir(parents=True, exist_ok=True)
    todo = [c for c in sm.cond if not (TRADES_DIR / f"{c}.parquet").exists()]
    print(f"{len(sm)} selected side markets; {len(todo)} tapes to fetch", flush=True)
    t0, fails = time.time(), []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fetch, c): c for c in todo}
        for i, fu in enumerate(as_completed(futs)):
            try:
                fu.result()
            except Exception as err:  # logged, not fatal; counted below
                fails.append(futs[fu])
                print("fail", futs[fu], err, flush=True)
            if i % 500 == 0:
                print(f"{i}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
    have = sum((TRADES_DIR / f"{c}.parquet").exists() for c in sm.cond)
    print(f"tapes on disk: {have}/{len(sm)}; failed this run: {len(fails)}", flush=True)


# ------------------------------------------------------------------ 3. tables
def load_side_tape(tdir: str, cond: str) -> pd.DataFrame | None:
    """crossmarket/common.load_side_tape with the tape directory as an argument."""
    f = Path(tdir) / f"{cond}.parquet"
    if not f.exists():
        return None
    t = pd.read_parquet(f)
    if t.empty:
        return None
    buy0 = ((t.side == "BUY") & (t.outcomeIndex == 0)) | ((t.side == "SELL") & (t.outcomeIndex == 1))
    t = t.assign(at_ask=buy0.to_numpy(), usd=t["size"] * t["price"],
                 q0=np.where(t.outcomeIndex == 0, t.price, 1 - t.price))
    return t[["timestamp", "q0", "at_ask", "size", "usd", "proxyWallet"]].sort_values(
        "timestamp", kind="stable").reset_index(drop=True)


def _last(ts: np.ndarray, t, side="right"):
    return np.searchsorted(ts, t, side) - 1


def process(args):
    """crossmarket/build.py: process without markouts and without jumps (always-on window)."""
    ml_row, sides, tdir = args
    s0 = int(pd.Timestamp(ml_row["start"]).timestamp())
    e0 = int(pd.Timestamp(ml_row["end"]).timestamp()) if pd.notna(ml_row["end"]) else s0 + 6 * 3600
    ml = load_tape(ml_row["cond"])
    if ml is None:
        return None, None
    ml = ml[(ml.timestamp >= s0) & (ml.timestamp <= e0)].reset_index(drop=True)
    if len(ml) < 20:
        return None, None
    mts = ml.timestamp.to_numpy().astype(float)
    mmid, _ = _mid_series(mts, ml.p0.to_numpy(), ml.at_ask.to_numpy(), stale=30)

    def ml_at(t, side="right"):
        t = np.asarray(t, float)
        i = _last(mts, t, side)
        return np.where((i >= 0) & np.isfinite(t), mmid[np.maximum(i, 0)], np.nan)

    pr_parts, iv_parts = [], []
    for sr in sides:
        t = load_side_tape(tdir, sr["cond"])
        if t is None:
            continue
        t = t[(t.timestamp >= s0) & (t.timestamp <= e0)].reset_index(drop=True)
        n = len(t)
        if n < 2:
            continue
        ts = t.timestamp.to_numpy().astype(float)
        q = t.q0.to_numpy()
        aa = t.at_ask.to_numpy()
        smid, _ = _mid_series(ts, q, aa, stale=120)
        p_now = ml_at(ts)
        gap = np.diff(ts)
        ok = gap <= MAX_GAP
        if ok.any():
            i1 = np.flatnonzero(ok) + 1
            iv_parts.append(pd.DataFrame({
                "cond": sr["cond"], "ts": ts[i1], "dt": gap[ok], "q1": q[i1 - 1], "q2": q[i1],
                "m1": smid[i1 - 1], "m2": smid[i1], "a1": aa[i1 - 1], "a2": aa[i1],
                "p1": p_now[i1 - 1], "p2": p_now[i1]}))
        t_send = ts - sr["delay"]
        jr = _last(ts, t_send, "left")  # side reference strictly before the information cut
        okr = jr >= 0
        q_rs = np.where(okr, smid[np.maximum(jr, 0)], np.nan)
        ts_rs = np.where(okr, ts[np.maximum(jr, 0)], np.nan)
        nan = np.full(n, np.nan)
        pr_parts.append(pd.DataFrame({
            "cond": sr["cond"], "ml_cond": ml_row["cond"], "ts": ts, "q0": q, "at_ask": aa,
            "size": t["size"].to_numpy(), "usd": t.usd.to_numpy(), "wallet": t.proxyWallet.to_numpy(),
            "smid": smid, "p_now": p_now, "t_send": t_send,
            "jump_k": np.full(n, -1), "onset": nan, "detect": nan, "jdir": nan, "jsize": nan,
            "p_send": ml_at(t_send, "left"),
            "q_rs": q_rs, "ts_rs": ts_rs, "p_rs": ml_at(ts_rs)}))
    pr = pd.concat(pr_parts, ignore_index=True) if pr_parts else None
    iv = pd.concat(iv_parts, ignore_index=True) if iv_parts else None
    return pr, iv


META = ["smt", "line", "align0", "fee_rate", "delay", "res_s0", "event_id", "start"]


def _run_tables(u: pd.DataFrame, sm: pd.DataFrame, tdir: Path):
    ug = u.set_index("event_id")
    tasks = []
    for ev, g in sm.groupby("event_id"):
        r = ug.loc[ev]
        ml_row = {"cond": r.cond, "start": r.start, "end": r.end}
        tasks.append((ml_row, g[["cond", "res_s0", "delay"]].to_dict("records"), str(tdir)))
    prs, ivs = [], []
    with ProcessPoolExecutor(WORKERS) as ex:
        for pr, iv in ex.map(process, tasks, chunksize=16):
            if pr is not None:
                prs.append(pr)
            if iv is not None:
                ivs.append(iv)
    pr = pd.concat(prs, ignore_index=True)
    iv = pd.concat(ivs, ignore_index=True)
    meta = sm.set_index("cond")[META]
    return pr.join(meta, on="cond"), iv.join(meta, on="cond"), len(tasks)


def tables():
    u = oos_universe()
    sm = side_markets()
    sel = sm[sm.selected]
    have = {p.stem for p in TRADES_DIR.glob("*.parquet")}
    sel_t = sel[sel.cond.isin(have)]
    pr, iv, n_ev = _run_tables(u, sel_t, TRADES_DIR)
    assert (pr.start >= OOS_CUT).all() and (iv.start >= OOS_CUT).all()
    assert pr.smt.isin(TYPES).all()
    pr.to_parquet(CACHE / "side_prints.parquet")
    iv.to_parquet(CACHE / "intervals.parquet")
    empty = sum(1 for c in sel_t.cond if pd.read_parquet(TRADES_DIR / f"{c}.parquet", columns=["timestamp"]).empty)
    print(f"events with selected side tapes: {n_ev}; events with in-play side prints: {pr.event_id.nunique()}")
    print(f"selected markets: {len(sel)}; tapes on disk: {len(sel_t)} (empty: {empty}); "
          f"markets with in-play prints: {pr.cond.nunique()}")
    print(f"in-play side prints: {len(pr)}; intervals: {len(iv)}")
    print(pr.groupby("smt").agg(markets=("cond", "nunique"), prints=("q0", "size")).to_string())


# ------------------------------------------------------------------ IS build-code parity (IS data only)
def check_is(n_events: int, seed: int = 0):
    """Rebuild n IS events with process() above and compare with the IS per-print / interval tables
    (data/v2_crossmarket), on every column this build produces except the jump columns."""
    from common import side_markets as is_side_markets  # noqa: E402
    u = universe_is().copy()
    u["event_id"] = u.event_id.astype(str)
    sm = is_side_markets()
    have = {p.stem for p in IS_TRADES_DIR.glob("*.parquet")}
    sm = sm[sm.cond.isin(have) & (sm.smt != "tennis_completed_match")]
    ref_pr = pd.read_parquet(ROOT / "data" / "v2_crossmarket" / "side_prints.parquet")
    ref_iv = pd.read_parquet(ROOT / "data" / "v2_crossmarket" / "intervals.parquet")
    evs = pd.Series(sorted(ref_pr.event_id.unique())).sample(n_events, random_state=seed)
    sm = sm[sm.event_id.isin(set(evs))]
    pr, iv, _ = _run_tables(u, sm, IS_TRADES_DIR)
    a = ref_pr[ref_pr.event_id.isin(set(evs))].sort_values(["cond", "ts", "q0", "size"], kind="stable").reset_index(drop=True)
    b = pr.sort_values(["cond", "ts", "q0", "size"], kind="stable").reset_index(drop=True)
    assert len(a) == len(b), (len(a), len(b))
    cols = ["cond", "ml_cond", "ts", "q0", "at_ask", "size", "usd", "wallet", "smid", "p_now", "t_send",
            "p_send", "q_rs", "ts_rs", "p_rs"] + META
    bad = []
    for c in cols:
        x, y = a[c].to_numpy(), b[c].to_numpy()
        if x.dtype.kind == "f":
            same = np.allclose(x, y, rtol=0, atol=0, equal_nan=True)
        else:
            same = bool((pd.Series(x) == pd.Series(y)).all())
        if not same:
            bad.append(c)
    ai = ref_iv[ref_iv.event_id.isin(set(evs))].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    bi = iv.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    assert len(ai) == len(bi), (len(ai), len(bi))
    for c in ai.columns:
        x, y = ai[c].to_numpy(), bi[c].to_numpy()
        same = (np.allclose(x, y, rtol=0, atol=0, equal_nan=True) if x.dtype.kind == "f"
                else bool((pd.Series(x) == pd.Series(y)).all()))
        if not same:
            bad.append("iv." + c)
    print(f"IS build parity on {n_events} IS events: {len(b)} prints, {len(bi)} intervals; "
          f"mismatched columns: {bad or 'none'}")
    assert not bad
    return {"events": n_events, "prints": len(b), "intervals": len(bi), "mismatched": bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", choices=("catalogue", "tapes", "tables", "all"), default="all")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--check-is", type=int, default=0)
    a = ap.parse_args()
    if a.check_is:
        check_is(a.check_is)
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    if a.step in ("catalogue", "all"):
        catalogue()
    if a.step in ("tapes", "all"):
        tapes(a.workers)
    if a.step in ("tables", "all"):
        tables()


if __name__ == "__main__":
    main()
