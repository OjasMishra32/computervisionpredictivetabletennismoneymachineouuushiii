"""Lens "exit": taker in (the fast-tier print), maker out (rest at the far touch).

For every walk-forward-selected fast-tier 0-3 s print in data/derived/shadow_is_uncapped.parquet
(IS only), simulate an exit by a passive order resting at the far touch of the side we are long:

  long outcome 0 (dir=+1): rest a SELL of outcome 0 at its ask. Fills on a later print that
      LIFTED outcome 0's ask (at_ask=True).
  long outcome 1 (dir=-1): rest a SELL of outcome 1 at its ask = a BID on outcome 0. Fills on a
      later print with at_ask=False (taker sold outcome 0 / bought outcome 1).

The order is posted at ts+H and lives until ts+H+T (T is measured from posting, so every grid cell
is a non-empty window). Fill models (queue realism, we have no historical depth):

  touch   : first exit-side print in the window whose REMAINING size >= our shares (prints are
            consumed by our own earlier orders, FIFO by post time); fill price = that print's p0
            (an order pegged to the touch).
  through : the first exit-side print in the window reveals our level L; we fill at L only when a
            LATER print in the window trades strictly beyond L by >= 1 tick with remaining size >=
            our shares (level L was cleared).
  pegthrough : pegged to the touch but always at the BACK of the queue: we fill at level L = p0 of an
            exit-side print k (k in the window) only when the NEXT exit-side print k+1 (in the window)
            trades strictly beyond L by >= 1 tick with remaining size >= our shares. Under price-time
            priority a print beyond our resting level cannot happen without filling us first, so
            this is the conservative queue model for a pegged order. (Added after the first run
            showed that the fixed-level "through" order is stranded when price runs away.)
  improve1g : quote ONE TICK INSIDE the touch (pegged), so we are alone at the best price: we fill on the
            first exit-side print in the window with remaining size >= our shares AND a tape spread
            proxy >= 2 ticks at that print (latest opposite-side print <= 30 s old; missing = not
            allowed), i.e. there was room inside the spread. Any taker who paid p0 would have filled
            us first at p0 -/+ 1 tick. The simulator stores the raw p0; analyze_exit.py applies the
            1-tick price give-up. (Added after pegthrough showed the queue assumption is decisive.)
  (touch50, the 50% fill-probability haircut, is applied in analyze_exit.py on top of touch.)

Prints that are themselves fast-tier 0-3 s prints (our replicated entries) never fill our exits.
Fallback B (taker exit after the timeout) uses the first opposite-side print at or after
ts+H+T+delay+1 s (venue delay + 1 s of our latency). A taker-out-at-H baseline is the same with T=0.

Sizing (tape share count, NOT the shadow file's usd/price, which mis-sizes SELL prints):
  sh500 : shares = min(print shares, 500)
  usd1k : shares = min(print shares, $1000 / price paid)
Per match: cumulative entry dollars (shares x price paid) <= $3,000, in time order (as D6).

Run from the repo root:
    .venv/bin/python research/v2/exit/sim_exit.py
Outputs (gitignored cache) under data/v2_exit/: entries.parquet, maker.parquet, fallback.parquet.
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import polymarket as pm  # noqa: E402

OUT = ROOT / "data" / "v2_exit"
HS = (2, 5, 10, 20, 30)
TS = (30, 60, 120, 300)
TS_EXT = (600, 1800)  # extension grid, sh500 + touch/pegthrough only (added after WF kept choosing T=300)
MODELS = ("touch", "through", "pegthrough", "improve1g")
SPREAD_STALE = 30  # s, staleness cutoff for the opposite-side print in the spread proxy (as src/tiers.py)
SIZINGS = ("sh500", "usd1k")
SHARE_CAP, USD_CAP, MATCH_CAP = 500.0, 1000.0, 3000.0
OUR_LATENCY = 1  # s, on top of the venue's secondsDelay, for taker exits
OOS_START = pd.Timestamp("2026-08-25 14:15", tz="UTC")
KEY = ["ts", "p", "dir", "wallet", "usd"]


def load_entries() -> pd.DataFrame:
    cols = ["cond", "ts", "p", "dir", "usd", "wallet", "fee_rate", "delay", "res", "month", "mo30", "mo_res",
            "spread", "with_jump"]
    s = pd.read_parquet(ROOT / "data/derived/shadow_is_uncapped.parquet", columns=cols)
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["cond", "start", "end"])
    # Hard rule: IS only. The shadow file is IS-only already; assert it.
    assert (u.start < OOS_START).all()
    assert pd.to_datetime(s.ts, unit="s", utc=True).min() > pd.Timestamp("2025-01-01", tz="UTC")
    s = s[s.cond.isin(u.cond)]
    s = s.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    s["eid"] = np.arange(len(s), dtype=np.int64)
    s["month"] = s.month.astype(str)
    return s


def _tape(cond: str, start, end) -> pd.DataFrame | None:
    f = pm.RAW / "trades" / f"{cond}.parquet"
    if not f.exists():
        return None
    t = pd.read_parquet(f, columns=["timestamp", "side", "outcomeIndex", "price", "size", "proxyWallet", "p0"])
    if t.empty:
        return None
    s = int(start.timestamp())
    e = int(end.timestamp()) if pd.notna(end) else s + 6 * 3600
    t = t[(t.timestamp >= s) & (t.timestamp <= e)].sort_values("timestamp", kind="stable").reset_index(drop=True)
    t["at_ask"] = (((t.side == "BUY") & (t.outcomeIndex == 0)) | ((t.side == "SELL") & (t.outcomeIndex == 1)))
    t["usd"] = t["size"] * t["price"]
    return t


def sim_match(job):
    cond, e, start, end = job
    t = _tape(cond, start, end)
    if t is None or t.empty:
        return None
    # --- match shadow entries to their tape rows (exact same derivation as src/tiers.py) ---
    tk = pd.DataFrame({"ts": t.timestamp.astype(float), "p": t.p0, "dir": np.where(t.at_ask, 1.0, -1.0),
                       "wallet": t.proxyWallet, "usd": t.usd, "tidx": np.arange(len(t)), "size": t["size"]})
    tk["occ"] = tk.groupby(KEY, sort=False).cumcount()
    e = e.copy()
    e["occ"] = e.groupby(KEY, sort=False).cumcount()
    e = e.merge(tk[KEY + ["occ", "tidx", "size"]], on=KEY + ["occ"], how="left")
    ts_all = t.timestamp.to_numpy().astype(np.int64)
    p_all = t.p0.to_numpy().astype(float)
    ask_all = t.at_ask.to_numpy()
    size_all = t["size"].to_numpy().astype(float)
    # tick: 0.01 if every print sits on the cent grid, else 0.001
    tick = 0.01 if np.all(np.abs(p_all * 100 - np.round(p_all * 100)) < 1e-6) else 0.001
    own = np.zeros(len(t), bool)
    own[e.tidx.dropna().astype(int).to_numpy()] = True  # fast-tier entry prints never fill our exits

    side_idx = {s: np.flatnonzero((ask_all == s) & ~own) for s in (True, False)}
    side_t = {s: ts_all[side_idx[s]] for s in side_idx}
    side_p = {s: p_all[side_idx[s]] for s in side_idx}
    side_sz = {s: size_all[side_idx[s]] for s in side_idx}
    # spread proxy at every exit-side print: distance to the latest opposite-side print (<= 30 s old)
    side_gate = {}
    for s_ in (True, False):
        ot, op = ts_all[ask_all != s_], p_all[ask_all != s_]
        k = np.searchsorted(ot, side_t[s_], "right") - 1
        ok = (k >= 0) & (side_t[s_] - ot[np.maximum(k, 0)] <= SPREAD_STALE) if len(ot) else np.zeros(len(side_t[s_]), bool)
        sp = (side_p[s_] - op[np.maximum(k, 0)]) if s_ else (op[np.maximum(k, 0)] - side_p[s_]) if len(ot) else np.zeros(len(side_t[s_]))
        side_gate[s_] = ok & (sp >= 2 * tick - 1e-9)
    # all-print side arrays for taker fallback prices (any print on the side we would hit)
    hit_t = {s: ts_all[ask_all == s] for s in (True, False)}
    hit_p = {s: p_all[ask_all == s] for s in (True, False)}

    e["matched"] = e.tidx.notna()
    e["size"] = e["size"].astype(float)
    e["pp"] = np.where(e.dir > 0, e.p, 1 - e.p)  # price paid per share of the token we are long
    e["tick"] = tick
    ets = e.ts.to_numpy().astype(np.int64)
    edir = e.dir.to_numpy()
    delay = int(e.delay.iloc[0])

    # --- fallback-B taker exit prices: depend only on the exit time, not on sizing/fills ---
    fb_rows = []
    for H in HS:
        for T in (0,) + TS + TS_EXT:
            tx = ets + H + T + delay + OUR_LATENCY
            px = np.full(len(e), np.nan)
            tt = np.full(len(e), np.nan)
            for s in (True, False):
                m = (edir < 0) if s else (edir > 0)  # long o0 sells o0 -> hits its bid (at_ask False)
                if not m.any() or len(hit_t[s]) == 0:
                    continue
                j = np.searchsorted(hit_t[s], tx[m], "left")
                ok = j < len(hit_t[s])
                jj = np.minimum(j, len(hit_t[s]) - 1)
                px[m] = np.where(ok, hit_p[s][jj], np.nan)
                tt[m] = np.where(ok, hit_t[s][jj] - ets[m], np.nan)
            fb_rows.append(pd.DataFrame({"eid": e.eid.to_numpy(), "H": np.int16(H), "T": np.int16(T),
                                         "dt": tt.astype(np.float32), "px": px.astype(np.float32)}))
    fb = pd.concat(fb_rows, ignore_index=True)

    # --- sizing and per-match cap ---
    mk_rows = []
    for sz in SIZINGS:
        size = e["size"].to_numpy()
        sh = np.minimum(size, SHARE_CAP) if sz == "sh500" else np.minimum(size, USD_CAP / e.pp.to_numpy())
        sh = np.where(e.matched.to_numpy(), sh, np.nan)
        usd = sh * e.pp.to_numpy()
        cum = np.nancumsum(np.nan_to_num(usd))
        acc = e.matched.to_numpy() & (cum <= MATCH_CAP)
        e[f"shares_{sz}"] = sh
        e[f"acc_{sz}"] = acc
        ai = np.flatnonzero(acc)  # already in time order
        if len(ai) == 0:
            continue
        for model in MODELS:
            ext = TS_EXT if (sz == "sh500" and model in ("touch", "pegthrough", "improve1g")) else ()
            for H in HS:
                for T in TS + ext:
                    rem = {s: side_sz[s].copy() for s in side_sz}
                    filled = np.zeros(len(ai), bool)
                    dt = np.full(len(ai), np.nan)
                    px = np.full(len(ai), np.nan)
                    for k, i in enumerate(ai):
                        s = edir[i] > 0  # exit side: long o0 rests at o0's ask -> needs at_ask=True prints
                        st = side_t[s]
                        if len(st) == 0:
                            continue
                        lo = np.searchsorted(st, ets[i] + H, "left")
                        hi = np.searchsorted(st, ets[i] + H + T, "right")
                        if hi <= lo:
                            continue
                        r = rem[s]
                        need = sh[i] - 1e-9
                        if model in ("touch", "improve1g"):
                            ok = r[lo:hi] >= need
                            if model == "improve1g":
                                ok &= side_gate[s][lo:hi]
                            c = np.flatnonzero(ok)
                            if c.size:
                                j = lo + c[0]
                                r[j] -= sh[i]
                                filled[k], dt[k], px[k] = True, st[j] - ets[i], side_p[s][j]
                        elif model == "pegthrough":
                            if hi - lo < 2:
                                continue
                            seg = side_p[s][lo:hi]
                            better = (seg[1:] >= seg[:-1] + tick - 1e-9) if s else (seg[1:] <= seg[:-1] - tick + 1e-9)
                            c = np.flatnonzero(better & (r[lo + 1:hi] >= need))
                            if c.size:
                                j = lo + 1 + c[0]
                                r[j] -= sh[i]
                                filled[k], dt[k], px[k] = True, st[j] - ets[i], side_p[s][j - 1]
                        else:
                            L = side_p[s][lo]
                            seg = side_p[s][lo + 1:hi]
                            better = (seg >= L + tick - 1e-9) if s else (seg <= L - tick + 1e-9)
                            c = np.flatnonzero(better & (r[lo + 1:hi] >= need))
                            if c.size:
                                j = lo + 1 + c[0]
                                r[j] -= sh[i]
                                filled[k], dt[k], px[k] = True, st[j] - ets[i], L
                    mk_rows.append(pd.DataFrame({
                        "eid": e.eid.to_numpy()[ai], "sizing": np.int8(SIZINGS.index(sz)),
                        "model": np.int8(MODELS.index(model)), "H": np.int16(H), "T": np.int16(T),
                        "filled": filled, "dt": dt.astype(np.float32), "px": px.astype(np.float32)}))
    mk = pd.concat(mk_rows, ignore_index=True) if mk_rows else None
    ent = e.drop(columns=["occ", "tidx"])
    ent["end_ts"] = int(end.timestamp()) if pd.notna(end) else int(start.timestamp()) + 6 * 3600
    return ent, mk, fb


def main(workers: int = 2, limit: int | None = None):
    OUT.mkdir(parents=True, exist_ok=True)
    s = load_entries()
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["cond", "start", "end"]).set_index("cond")
    conds = s.cond.unique()
    if limit:
        conds = conds[:limit]
    groups = dict(tuple(s[s.cond.isin(conds)].groupby("cond", sort=False)))
    jobs = [(c, groups[c], u.at[c, "start"], u.at[c, "end"]) for c in conds]
    t0 = time.time()
    ents, mks, fbs = [], [], []
    with ProcessPoolExecutor(workers) as ex:
        for n, res in enumerate(ex.map(sim_match, jobs, chunksize=8)):
            if res is not None:
                ents.append(res[0])
                fbs.append(res[2])
                if res[1] is not None:
                    mks.append(res[1])
            if n % 500 == 0:
                print(f"{n}/{len(jobs)} matches, {time.time() - t0:.0f}s", flush=True)
    ent = pd.concat(ents, ignore_index=True)
    mk = pd.concat(mks, ignore_index=True)
    fb = pd.concat(fbs, ignore_index=True)
    sfx = f"_lim{limit}" if limit else ""
    ent.to_parquet(OUT / f"entries{sfx}.parquet")
    mk.to_parquet(OUT / f"maker{sfx}.parquet")
    fb.to_parquet(OUT / f"fallback{sfx}.parquet")
    print(f"entries {len(ent)} (matched {int(ent.matched.sum())}), maker rows {len(mk)}, fallback rows {len(fb)}; "
          f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=None, help="first N matches only (smoke test)")
    a = ap.parse_args()
    main(a.workers, a.limit)
