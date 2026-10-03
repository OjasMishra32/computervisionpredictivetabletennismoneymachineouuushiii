#!/usr/bin/env python
"""Match replay: the tier-0 video trader walked through every official point of the 9 WTA matches recorded
live on 2026-10-03, each order priced against the real recorded Polymarket order book.

    BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not
    purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real
    recorded order book; paper only.

No video of these matches was received, bought or watched. The feed, its delay V, the camera call and its
lead are assumptions; the official point stamps and winners, the order books, the venue delay, the fee and
the match results are real. Nothing is sent anywhere. Protocol (committed before any P&L):
research/replay/PROTOCOL.md.

    .venv/bin/python scripts/match_replay.py                 # everything -> results/replay/, research/replay/RESULTS.md
    .venv/bin/python scripts/match_replay.py --cache F.pkl   # cache the parsed recording (outside the repo)
    .venv/bin/python scripts/match_replay.py --figures-only  # redraw figures from results/replay/
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import gzip
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import orjson
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research/v2/latency"))
import load as L  # noqa: E402
from src import tier0  # noqa: E402

LABEL = ("BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not "
         "purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real "
         "recorded order book; paper only")
OUT = ROOT / "results" / "replay"
DOC = ROOT / "research" / "replay"
M1 = ROOT / "research/v2/latency/out/m1_points.csv"
MARKET_FILES = ["data/live/market_20261003_0946.jsonl.gz", "data/live/market_20261003_1003.jsonl.gz"]
LATE_FILE = "data/live/market_20261003_1501.jsonl"       # read for market_resolved only

# ---- fixed by the protocol (tier-0 model + task); nothing here is chosen from results
LAGS = (1.0, 2.0, 3.0)            # stamp lag t_stamp - t_bounce, s (2.0 primary)
VS = (0.0, 0.5, 1.0)              # video feed delay, s (1.0 headline)
LEADS = ("model", "zero")
NETS = {"florida": 67, "london": 2}   # one-way ms to the matching engine
T_INF_MS = 20                     # CV inference
TAKER_DELAY_MS = 1000             # venue taker delay
NET_CAP = 100.0                   # |net outcome-0 shares| per match
ORDER_CAP_USD = 1000.0
LIMIT_ADD = 0.01                  # limit = reference ask + 1c
PRECISION = 0.95
FEE_RATE = 0.05
MAX_SPREAD = 0.05
ZONE = (0.05, 0.95)
GAP_MS = 60_000                   # need a recorded message for the market within 60 s before exec
OUTAGE_MS = 1_000                 # audit fix (RESULTS.md, deviation D1): a gap in the recorder's own receive stream
#                                   (all markets, ~300 messages/s, p99.99 gap 0.22 s) longer than this is an outage;
#                                   the book is unobserved inside it. All 33 such gaps are > 2 s.
MARK_MS = 30_000
P_OUT_WOMEN = None                # filled from tier0.point_mix()
HEADLINE = {"lag": 2.0, "V": 1.0, "lead": "model", "net": "florida"}
SEEDS = range(20)
N_BOOT = 10_000


# ======================================================================================= loading
def iso(ms) -> str:
    if ms is None or not np.isfinite(ms):
        return ""
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_points() -> tuple[pd.DataFrame, pd.DataFrame]:
    P = pd.read_csv(M1)
    P = P.sort_values(["key", "n"], kind="stable").reset_index(drop=True)
    ev = L.events_table(L.load_meta()).drop_duplicates("slug").set_index("slug")
    conds = {}
    for rec in L.read("tokens", L.LEGACY):
        for tok, m in (rec.get("tokens") or {}).items():
            conds.setdefault(m["slug"], m["cond"])
    M = []
    for (key, slug), g in P.groupby(["key", "slug"], sort=False):
        e = ev.loc[slug]
        M.append({"key": key, "slug": slug, "cond": conds[slug], "tok0": e.tok0, "tok1": e.tok1, "n0": e.n0,
                  "n1": e.n1, "points": len(g), "matched": int(g.t_book.notna().sum()),
                  "first_T": float(g.T_ms.min()), "last_T": float(g.T_ms.max())})
    M = pd.DataFrame(M)
    # selection rule (PROTOCOL §3): most points with a matched reprice; ties by earliest first stamp
    M = M.sort_values(["matched", "first_T"], ascending=[False, True], kind="stable").reset_index(drop=True)
    M["selected"] = M.index == 0
    return P, M


def parse_recording(M: pd.DataFrame, cache: str | None) -> dict:
    """Events of the 9 markets from the raw recording: per cond a list of
    (ts_server, rt, kind, data) with kind 0 price_change [(tok, is_bid, price, size)], 1 book (tok, bids, asks),
    2 trade (tok, price, size, side), 3 resolved (winning tok)."""
    if cache and Path(cache).exists():
        with open(cache, "rb") as f:
            out = pickle.load(f)
        if "outages_rt" not in out:          # caches written before the audit fix
            out["outages_rt"] = recorder_outages()
        return out
    tokidx = {}
    for r in M.itertuples():
        tokidx[r.tok0] = (r.cond, 0)
        tokidx[r.tok1] = (r.cond, 1)
    conds = {c.encode(): c for c in M.cond}
    ev = {c: [] for c in M.cond}
    lat = []
    n_lines = 0
    gaps, prev = [], None
    for fn in MARKET_FILES:
        try:
            with gzip.open(ROOT / fn, "rb") as fh:
                for line in fh:
                    n_lines += 1
                    if line.startswith(b'{"rt":'):
                        rt_ = int(line[6:19])
                        if prev is not None and rt_ - prev > OUTAGE_MS:
                            gaps.append((prev, rt_))
                        prev = rt_ if prev is None else max(prev, rt_)
                    i = line.find(b'"market":"', 0, 80)
                    if i < 0:
                        continue
                    c = conds.get(line[i + 10:i + 76])
                    if c is None:
                        continue
                    try:
                        r = orjson.loads(line)
                    except orjson.JSONDecodeError:
                        continue
                    _add(ev, c, r, tokidx, lat)
        except (EOFError, OSError) as exc:        # the 0946 file is truncated at its end
            print(f"  {fn}: stopped at a truncated end ({type(exc).__name__}) after {n_lines:,} lines")
    resolved = {c for c in ev if any(k == 3 for _, _, k, _ in ev[c])}
    if len(resolved) < len(ev):
        with open(ROOT / LATE_FILE, "rb") as fh:
            for line in fh:
                if b"market_resolved" not in line:
                    continue
                r = orjson.loads(line)
                c = r.get("market")
                if c in ev and r.get("event_type") == "market_resolved":
                    _add(ev, c, r, tokidx, lat)
    out = {"events": ev, "recv_latency_ms": lat, "n_lines": n_lines, "outages_rt": gaps}
    if cache:
        with open(cache, "wb") as f:
            pickle.dump(out, f, protocol=pickle.HIGHEST_PROTOCOL)
    return out


def recorder_outages() -> list:
    """(last receive time before, first receive time after) of every gap > OUTAGE_MS in the recorder's own
    receive stream, over the market files in recording order."""
    gaps, prev = [], None
    for fn in MARKET_FILES:
        try:
            with gzip.open(ROOT / fn, "rb") as fh:
                for line in fh:
                    if line.startswith(b'{"rt":'):
                        rt_ = int(line[6:19])
                        if prev is not None and rt_ - prev > OUTAGE_MS:
                            gaps.append((prev, rt_))
                        prev = rt_ if prev is None else max(prev, rt_)
        except (EOFError, OSError):
            pass
    return gaps


def in_outage(t: int, win: np.ndarray) -> bool:
    """True if server instant t lies strictly inside a recorder outage window (server clock)."""
    if not len(win):
        return False
    i = int(np.searchsorted(win[:, 0], t, "right")) - 1
    return i >= 0 and win[i, 0] < t < win[i, 1]


def _add(ev, c, r, tokidx, lat):
    et = r.get("event_type")
    rt = int(r["rt"])
    ts = int(r["timestamp"]) if r.get("timestamp") else rt
    if et == "price_change":
        ch = []
        for x in r.get("price_changes", []):
            t = tokidx.get(x.get("asset_id"))
            if t is None:
                continue
            ch.append((t[1], x["side"] == "BUY", float(x["price"]), float(x["size"])))
        if ch:
            ev[c].append((ts, rt, 0, ch))
            lat.append(rt - ts)
    elif et == "book":
        t = tokidx.get(r.get("asset_id"))
        if t is None:
            return
        b = [(float(x["price"]), float(x["size"])) for x in r.get("bids", [])]
        k = [(float(x["price"]), float(x["size"])) for x in r.get("asks", [])]
        ev[c].append((ts, rt, 1, (t[1], b, k)))
    elif et == "last_trade_price":
        t = tokidx.get(r.get("asset_id"))
        if t is not None:
            ev[c].append((ts, rt, 2, (t[1], float(r["price"]), float(r["size"]), r.get("side"))))
    elif et == "market_resolved":
        t = tokidx.get(r.get("winning_asset_id"))
        if t is not None:
            ev[c].append((ts, rt, 3, t[1]))


def effective_events(ev: list, l_recv: int) -> list:
    """Server-time order: price changes / trades / resolutions at their server timestamp; book snapshots at
    rt - L_recv (their timestamp field can be the time of the book's last change). Ties keep recording order."""
    rows = [((rt - l_recv) if k == 1 else ts, i, k, d) for i, (ts, rt, k, d) in enumerate(ev)]
    rows.sort(key=lambda x: (x[0], x[1]))
    return rows


def capture(rows: list, times: np.ndarray, depth: bool = True) -> dict:
    """Book state of both tokens after every event with effective time <= t, for each t in `times`
    (sorted unique ints). Returns t -> (bb0, ba0, bb1, ba1, asks0, asks1, last_eff, snap0, snap1)."""
    bids = [{}, {}]
    asks = [{}, {}]
    snap = [False, False]
    out = {}
    j = 0
    last = -1
    n = len(rows)
    for t in times:
        while j < n and rows[j][0] <= t:
            eff, _, k, d = rows[j]
            if k == 0:
                for tok, is_bid, p, sz in d:
                    side = bids[tok] if is_bid else asks[tok]
                    if sz > 0:
                        side[p] = sz
                    else:
                        side.pop(p, None)
                last = eff
            elif k == 1:
                tok, b, a = d
                bids[tok] = {p: s for p, s in b if s > 0}
                asks[tok] = {p: s for p, s in a if s > 0}
                snap[tok] = True
                last = eff
            j += 1
        bb0 = max(bids[0]) if bids[0] else np.nan
        ba0 = min(asks[0]) if asks[0] else np.nan
        bb1 = max(bids[1]) if bids[1] else np.nan
        ba1 = min(asks[1]) if asks[1] else np.nan
        if depth:
            a0 = tuple(sorted(asks[0].items())[:40])
            a1 = tuple(sorted(asks[1].items())[:40])
        else:
            a0 = a1 = ()
        out[int(t)] = (bb0, ba0, bb1, ba1, a0, a1, last, snap[0], snap[1])
    return out


# ==================================================================================== simulation
def draws(n: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    u = rng.random((n, 3))
    return {"end": u[:, 0], "lead": u[:, 1], "prec": u[:, 2]}


def leads_ms(dr: dict, cvd: dict, p_out: float) -> np.ndarray:
    lead, _, called = tier0.lead_and_precision(cvd, dr["lead"], np.zeros(len(dr["lead"])))
    is_out = dr["end"] < p_out
    return np.where(is_out & called, np.round(lead * 1000), 0).astype(np.int64)


def cell_times(P: pd.DataFrame, lead: np.ndarray, lag: float, V: float, net_ms: int) -> dict:
    T = P.T_ms.to_numpy().astype(np.int64)
    bounce = T - int(round(lag * 1000))
    frame = bounce - lead
    call = frame + int(round(V * 1000)) + T_INF_MS
    t_ref = np.minimum(frame, call - net_ms)
    arrive = call + net_ms
    exe = arrive + TAKER_DELAY_MS
    return {"T": T, "bounce": bounce, "frame": frame, "call": call, "t_ref": t_ref, "arrive": arrive,
            "exec": exe, "mark": exe + MARK_MS}


def simulate(P, M, snaps, times, dr, lead, winners, l_recv, cell, outages=None) -> pd.DataFrame:
    rows = []
    net = {}
    cidx = dict(zip(M.slug, M.cond))
    tb = P.t_book.to_numpy()
    for i, p in enumerate(P.itertuples()):
        cond = cidx[p.slug]
        S = snaps[cond]
        tr, te, tm = int(times["t_ref"][i]), int(times["exec"][i]), int(times["mark"][i])
        winner = int(p.winner)
        correct = bool(dr["prec"][i] < PRECISION)
        c = winner if correct else 1 - winner
        d = 1 if c == 0 else -1
        t_book_srv = tb[i] - l_recv if np.isfinite(tb[i]) else np.nan
        row = {"slug": p.slug, "key": p.key, "n": int(p.n), "set": int(p.set), "game": int(p.game),
               "score_after": f"{p.ga}-{p.gb}", "game_end": bool(p.game_end), "point_winner": winner,
               "T_ms": int(times["T"][i]), "bounce_ms": int(times["bounce"][i]), "lead_ms": int(lead[i]),
               "frame_ms": int(times["frame"][i]), "call_ms": int(times["call"][i]), "ref_ms": tr,
               "arrive_ms": int(times["arrive"][i]), "exec_ms": te, "t_book_srv_ms": t_book_srv,
               "exec_minus_book_s": (te - t_book_srv) / 1000 if np.isfinite(t_book_srv) else np.nan,
               "beat_book": bool(te < t_book_srv) if np.isfinite(t_book_srv) else None,
               "called_side": c, "correct_call": correct, "ref_ask": np.nan, "limit": np.nan,
               "ask_at_exec": np.nan, "status": "", "size_sent": 0.0, "shares": 0.0, "vwap": np.nan,
               "fee": 0.0, "payout": np.nan, "pnl_hold": 0.0, "mid_30s": np.nan, "pnl_mark": 0.0,
               "net0_after": net.get(cond, 0.0), "no_book_reason": ""}
        s_ref, s_exe, s_mark = S.get(tr), S.get(te), S.get(tm)
        ok = (s_ref is not None and s_ref[7] and s_ref[8] and s_exe is not None and s_exe[6] >= te - GAP_MS)
        if not ok:
            row["status"] = "no book recorded"
            row["no_book_reason"] = "outside the recording"
            rows.append(row)
            continue
        if outages is not None and (in_outage(tr, outages) or in_outage(te, outages)):
            row["status"] = "no book recorded"          # deviation D1: the book is unobserved at that instant
            row["no_book_reason"] = "recorder outage at the reference or execution instant"
            rows.append(row)
            continue
        if outages is not None and in_outage(tm, outages):
            s_mark = None                                # no observed +30 s mid: the fill is held but not marked
        bb, ba = (s_ref[0], s_ref[1]) if c == 0 else (s_ref[2], s_ref[3])
        row["ref_ask"] = ba
        if not (np.isfinite(bb) and np.isfinite(ba) and ba - bb <= MAX_SPREAD + 1e-9):
            row["status"] = "skipped (no tight quote)"
            rows.append(row)
            continue
        if not (ZONE[0] <= ba <= ZONE[1]):
            row["status"] = "skipped (outside 5-95c)"
            rows.append(row)
            continue
        limit = round(ba + LIMIT_ADD, 6)
        row["limit"] = limit
        n0 = net.get(cond, 0.0)
        allow = max(0.0, NET_CAP - d * n0)
        if allow <= 1e-9:
            row["status"] = "blocked (net cap)"
            rows.append(row)
            continue
        size = min(allow, ORDER_CAP_USD / limit)
        row["size_sent"] = size
        asks = s_exe[4] if c == 0 else s_exe[5]
        row["ask_at_exec"] = asks[0][0] if asks else np.nan
        got = cost = fee = 0.0
        for px, sz in asks:
            if px > limit + 1e-9:
                break
            take = min(sz, size - got)
            got += take
            cost += take * px
            fee += take * FEE_RATE * px * (1 - px)
            if got >= size - 1e-9:
                break
        if got <= 1e-9:
            row["status"] = "missed (no offers)" if not asks else "missed (book already moved)"
            rows.append(row)
            continue
        vwap = cost / got
        payout = 1.0 if winners[cond] == c else 0.0
        mid = np.nan
        if s_mark is not None:
            mb, ma = (s_mark[0], s_mark[1]) if c == 0 else (s_mark[2], s_mark[3])
            if np.isfinite(mb) and np.isfinite(ma):
                mid = (mb + ma) / 2
        net[cond] = n0 + d * got
        row.update({"status": "filled" if got >= size - 1e-6 else "partial", "shares": got, "vwap": vwap,
                    "fee": fee, "payout": payout, "pnl_hold": got * payout - cost - fee, "mid_30s": mid,
                    "pnl_mark": (got * mid - cost - fee) if np.isfinite(mid) else np.nan,
                    "net0_after": net[cond]})
        rows.append(row)
    D = pd.DataFrame(rows)
    for k, v in cell.items():
        D[k] = v
    return D


# ========================================================================================= stats
def cluster_ci(F: pd.DataFrame, col: str, seed: int = 0) -> list:
    g = F.groupby("slug").agg(p=(col, "sum"), s=("shares", "sum"))
    g = g[g.s > 0]
    if len(g) == 0:
        return [np.nan, np.nan]
    P, S = g.p.to_numpy(), g.s.to_numpy()
    idx = np.random.default_rng(seed).integers(0, len(g), (N_BOOT, len(g)))
    ps = P[idx].sum(1) / S[idx].sum(1) * 100
    return [float(np.percentile(ps, 2.5)), float(np.percentile(ps, 97.5))]


def stats(D: pd.DataFrame, ci: bool = True) -> dict:
    rep = D[D.status != "no book recorded"]
    calls = rep[~rep.status.str.startswith("skipped")]
    orders = calls[calls.status != "blocked (net cap)"]
    F = orders[orders.shares > 1e-9]
    wb = calls[calls.beat_book.notna()]
    sh = float(F.shares.sum())
    out = {
        "official_points": int(len(D)), "replayable_points": int(len(rep)), "calls": int(len(calls)),
        "skipped": int(len(rep) - len(calls)), "blocked_net_cap": int((calls.status == "blocked (net cap)").sum()),
        "orders": int(len(orders)), "fills": int(len(F)),
        "fill_rate": float(len(F) / len(orders)) if len(orders) else float("nan"),
        "fills_correct": int(F.correct_call.sum()), "fills_wrong": int((~F.correct_call.astype(bool)).sum()),
        "wrong_calls": int((~calls.correct_call.astype(bool)).sum()),
        "missed_book_moved": int((orders.status == "missed (book already moved)").sum()),
        "calls_with_reprice": int(len(wb)), "calls_beat_book": int(wb.beat_book.astype(bool).sum()),
        "share_calls_beat_book": float(wb.beat_book.astype(bool).mean()) if len(wb) else float("nan"),
        "correct_fills_before_reprice": int((F.correct_call.astype(bool) & (F.beat_book == True)).sum()),  # noqa: E712
        "shares": sh, "usd_in": float((F.shares * F.vwap).sum()),
        "pnl_hold_usd": float(F.pnl_hold.sum()), "pnl_mark_usd": float(F.pnl_mark.sum(skipna=True)),
        "per_share_hold_c": float(F.pnl_hold.sum() / sh * 100) if sh else float("nan"),
        "per_share_mark_c": float(F.pnl_mark.sum(skipna=True) / F.shares[F.pnl_mark.notna()].sum() * 100)
        if sh and F.pnl_mark.notna().any() else float("nan"),
        "win_rate_hold": float((F.pnl_hold > 0).mean()) if len(F) else float("nan"),
        "win_rate_mark": float((F.pnl_mark > 0).mean()) if len(F) else float("nan"),
        "pnl_hold_correct_usd": float(F[F.correct_call.astype(bool)].pnl_hold.sum()),
        "pnl_hold_wrong_usd": float(F[~F.correct_call.astype(bool)].pnl_hold.sum()),
        "pnl_mark_correct_usd": float(F[F.correct_call.astype(bool)].pnl_mark.sum(skipna=True)),
        "pnl_mark_wrong_usd": float(F[~F.correct_call.astype(bool)].pnl_mark.sum(skipna=True)),
        "median_exec_minus_book_s": float(calls.exec_minus_book_s.median()) if len(calls) else float("nan"),
    }
    if ci:
        out["per_share_hold_ci95_c"] = cluster_ci(F, "pnl_hold")
        Fm = F[F.pnl_mark.notna()]
        out["per_share_mark_ci95_c"] = cluster_ci(Fm, "pnl_mark")
        out["matches_with_fills"] = int(F.slug.nunique())
    return out


def cell_name(c: dict) -> str:
    return f"V{c['V']:g}|lag{c['lag']:g}|lead_{c['lead']}|{c['net']}"


# ========================================================================================== main
def run(cache: str | None) -> dict:
    P, M = load_points()
    sel = M[M.selected].iloc[0]
    print(f"selected match (most matched reprices, ties by earliest start): {sel.slug} ({sel.matched} of {sel.points})")
    print("parsing the recording ...")
    R = parse_recording(M, cache)
    lat = np.array(R["recv_latency_ms"])
    l_recv = int(round(float(np.median(lat))))
    print(f"  receive latency rt - server ts: median {l_recv} ms (p10 {np.percentile(lat, 10):.0f}, "
          f"p90 {np.percentile(lat, 90):.0f}; n {len(lat):,})")
    rows = {c: effective_events(e, l_recv) for c, e in R["events"].items()}
    outages = np.array([(a - l_recv, b - l_recv) for a, b in R["outages_rt"]], dtype=np.int64).reshape(-1, 2)
    print(f"  recorder outages (receive gaps > {OUTAGE_MS} ms): {len(outages)}, "
          f"{(outages[:, 1] - outages[:, 0]).sum() / 1000:.1f} s in all; longest "
          f"{(outages[:, 1] - outages[:, 0]).max() / 1000:.1f} s")
    winners = {}
    for c, e in R["events"].items():
        w = [d for _, _, k, d in e if k == 3]
        winners[c] = w[-1] if w else None
    missing = [c for c, w in winners.items() if w is None]
    if missing:
        raise SystemExit(f"no market_resolved for {missing}")
    M["winner_idx"] = M.cond.map(winners)
    M["winner_name"] = np.where(M.winner_idx == 0, M.n0, M.n1)

    cvd = tier0.cv_systems()["own120"]
    p_out = tier0.point_mix()["women"]["out"]
    cells = [{"V": V, "lag": lag, "lead": ld, "net": nt} for V in VS for lag in LAGS for ld in LEADS for nt in NETS]
    seed_cells = [{"V": V, **{k: HEADLINE[k] for k in ("lag", "lead", "net")}} for V in VS]
    # every instant we need a book for, per market
    plan = []
    for seed in SEEDS:
        dr = draws(len(P), seed)
        lead_m = leads_ms(dr, cvd, p_out)
        for c in (cells if seed == 0 else seed_cells):
            lead = lead_m if c["lead"] == "model" else np.zeros(len(P), np.int64)
            plan.append((seed, c, dr, lead, cell_times(P, lead, c["lag"], c["V"], NETS[c["net"]])))
    cond_of = P.slug.map(dict(zip(M.slug, M.cond))).to_numpy()
    need = {c: set() for c in M.cond}
    for _, _, _, _, tm in plan:
        for k in ("t_ref", "exec", "mark"):
            for c, t in zip(cond_of, tm[k]):
                need[c].add(int(t))
    print(f"capturing books at {sum(len(v) for v in need.values()):,} instants ...")
    snaps = {c: capture(rows[c], np.array(sorted(need[c]), dtype=np.int64)) for c in M.cond}

    # mirror check: is token 1's own best ask the mirror of token 0's best bid at the execution instants?
    agree = []
    for c in M.cond:
        for t, s in snaps[c].items():
            if np.isfinite(s[0]) and np.isfinite(s[3]):
                agree.append(abs(s[3] - (1 - s[0])) < 1e-6)
    mirror = float(np.mean(agree)) if agree else float("nan")
    print(f"  token-1 best ask == 1 - token-0 best bid at {mirror:.1%} of captured instants")

    res_cells, frames, seed_rows = {}, [], []
    for seed, c, dr, lead, tm in plan:
        D = simulate(P, M, snaps, tm, dr, lead, winners, l_recv, {**c, "seed": seed}, outages)
        if seed == 0:
            nm = cell_name(c)
            res_cells[nm] = {"cell": c, "all": stats(D),
                             "by_match": {s: stats(g) for s, g in D.groupby("slug", sort=False)}}
            if c["lag"] == HEADLINE["lag"] and c["lead"] == HEADLINE["lead"] and c["net"] == HEADLINE["net"]:
                frames.append(D)
        if c in seed_cells:
            s = stats(D, ci=False)
            seed_rows.append({"seed": seed, "V": c["V"], **{k: s[k] for k in (
                "calls", "orders", "fills", "fill_rate", "fills_correct", "fills_wrong", "calls_beat_book",
                "shares", "pnl_hold_usd", "pnl_mark_usd", "per_share_hold_c", "per_share_mark_c")}})
    pts = pd.concat(frames, ignore_index=True)
    SR = pd.DataFrame(seed_rows)
    seeds = {}
    for V, g in SR.groupby("V"):
        seeds[f"V{V:g}"] = {k: {"mean": float(g[k].mean()), "sd": float(g[k].std(ddof=1)),
                                "min": float(g[k].min()), "max": float(g[k].max())}
                            for k in g.columns if k not in ("seed", "V")}

    # ------------------------------------------------------------------ outputs
    OUT.mkdir(parents=True, exist_ok=True)
    pts = pts.merge(M[["slug", "n0", "n1", "winner_name"]], on="slug", how="left")
    pts["called_player"] = np.where(pts.called_side == 0, pts.n0, pts.n1)
    pts["point_winner_name"] = np.where(pts.point_winner == 0, pts.n0, pts.n1)
    for k in ("T", "bounce", "frame", "call", "ref", "arrive", "exec", "t_book_srv"):
        col = f"{k}_ms"
        pts[f"{k}_utc"] = pts[col].map(iso)
    pts.insert(0, "label", LABEL)
    pts["selected_match"] = pts.slug == sel.slug
    cols = ["label", "V", "lag", "lead", "net", "seed", "slug", "selected_match", "n", "set", "game", "score_after",
            "game_end", "point_winner_name", "called_player", "correct_call", "no_book_reason", "lead_ms", "T_utc",
            "bounce_utc",
            "call_utc", "arrive_utc", "exec_utc", "t_book_srv_utc", "exec_minus_book_s", "beat_book", "ref_ask",
            "limit", "ask_at_exec", "status", "size_sent", "shares", "vwap", "fee", "payout", "pnl_hold", "mid_30s",
            "pnl_mark", "net0_after", "winner_name", "T_ms", "bounce_ms", "frame_ms", "call_ms", "ref_ms",
            "arrive_ms", "exec_ms", "t_book_srv_ms"]
    pts["t_book_srv_ms"] = pts.t_book_srv_ms.round().astype("Int64")   # keep full ms precision in the CSV
    pts[cols].to_csv(OUT / "points.csv", index=False, float_format="%.6g")

    head = {V: res_cells[cell_name({**HEADLINE, "V": V})] for V in VS}
    story = selected_story(pts, sel.slug)
    res = {
        "label": LABEL,
        "protocol": "research/replay/PROTOCOL.md (committed before any P&L)",
        "not_evidence": "one day (2026-10-03), 9 WTA matches, a few hundred replayable points: an illustration "
                        "and a consistency check against research/v2/tier0/LATENCY_SWEEP.md, not new evidence",
        "inputs": {"points": str(M1.relative_to(ROOT)), "recording": MARKET_FILES,
                   "results_from": "market_resolved messages in the same recording (+ " + LATE_FILE + ")",
                   "lines_scanned": R["n_lines"]},
        "model": {"stamp_lags_s": LAGS, "video_delays_s": VS, "leads": "tier-0 own120 model (0/25/50/100 ms) or 0",
                  "p_out_women": p_out, "inference_ms": T_INF_MS, "network_ms": NETS, "taker_delay_ms": TAKER_DELAY_MS,
                  "net_cap_shares": NET_CAP, "order_cap_usd": ORDER_CAP_USD, "limit": "reference ask + 1c",
                  "precision": PRECISION, "fee": "0.05*q*(1-q) per share", "spread_max": MAX_SPREAD, "zone": ZONE,
                  "headline": HEADLINE, "recv_latency_ms_median": l_recv,
                  "recv_latency_ms_p10_p90": [float(np.percentile(lat, 10)), float(np.percentile(lat, 90))],
                  "mirror_check_tok1_ask_eq_1_minus_tok0_bid": mirror,
                  "recorder_outages": {"rule": f"gap > {OUTAGE_MS} ms in the recorder's receive stream (all markets); "
                                               "reference or execution instant inside one -> no book recorded; +30 s "
                                               "mark inside one -> not marked (deviation D1, after the audit)",
                                       "n": int(len(outages)),
                                       "total_s": float((outages[:, 1] - outages[:, 0]).sum() / 1000),
                                       "windows_utc": [[iso(a), iso(b)] for a, b in outages]}},
        "matches": M.assign(first_T=M.first_T.map(iso), last_T=M.last_T.map(iso)).drop(columns=["tok0", "tok1"])
                    .to_dict("records"),
        "selected_match": sel.slug,
        "headline_by_V": {f"V{V:g}": {"all": head[V]["all"], "by_match": head[V]["by_match"]} for V in VS},
        "cells": res_cells,
        "seed_robustness": {"cells": [cell_name(c) for c in seed_cells], "seeds": list(SEEDS), "summary": seeds},
        "selected_story": story,
        "sweep_reference": {"headline_reading_IS_c": {"V0": 1.10, "V0.5": 0.61, "V1": 0.40},
                            "headline_reading_OOS_c": {"V0": 0.58, "V0.5": -0.02, "V1": -0.38},
                            "fill_rate_IS": {"V0": 0.251, "V0.5": 0.109, "V1": 0.079},
                            "source": "research/v2/tier0/LATENCY_SWEEP.md §2 (commit f5ff9ff)"},
    }
    (OUT / "replay.json").write_text(json.dumps(res, indent=1, default=_js))
    SR.insert(0, "label", LABEL)
    SR.to_csv(OUT / "seed_robustness.csv", index=False, float_format="%.6g")
    timeline(rows[sel.cond], sel, pts)
    return res


def _js(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def selected_story(pts: pd.DataFrame, slug: str) -> dict:
    out = {}
    for V, g in pts[pts.slug == slug].groupby("V"):
        calls = g[~g.status.isin(["no book recorded"]) & ~g.status.str.startswith("skipped")]
        F = g[g.shares > 1e-9]
        beat = calls[calls.beat_book == True]  # noqa: E712
        out[f"V{V:g}"] = {
            "points": int(len(g)), "replayable": int((g.status != "no book recorded").sum()), "calls": int(len(calls)),
            "calls_with_reprice": int(calls.beat_book.notna().sum()), "beat_book": int(len(beat)),
            "beat_book_points": beat.n.astype(int).tolist(),
            "fills": int(len(F)), "fills_correct": int(F.correct_call.sum()),
            "fills_wrong": int((~F.correct_call.astype(bool)).sum()),
            "fills_beat_book": int((F.beat_book == True).sum()),  # noqa: E712
            "missed_book_moved": int((g.status == "missed (book already moved)").sum()),
            "blocked_net_cap": int((g.status == "blocked (net cap)").sum()),
            "pnl_hold_usd": float(F.pnl_hold.sum()), "pnl_mark_usd": float(F.pnl_mark.sum(skipna=True)),
            "shares": float(F.shares.sum()),
            "median_exec_minus_book_s": float(calls.exec_minus_book_s.median()),
        }
    return out


def timeline(rows: list, sel, pts: pd.DataFrame) -> None:
    """Top of book of the selected match every 250 ms (for figures and the demo), from the same replay."""
    g = pts[pts.slug == sel.slug]
    t0 = int(g.T_ms.min()) - 120_000
    t1 = int(g.T_ms.max()) + 60_000
    ts = np.arange(t0 - t0 % 250, t1, 250, dtype=np.int64)
    S = capture(rows, ts, depth=False)
    tl = pd.DataFrame([(t, *S[t][:4]) for t in ts], columns=["t_ms", "bid0", "ask0", "bid1", "ask1"])
    tl["mid0"] = (tl.bid0 + tl.ask0) / 2
    with open(OUT / "selected_match_book.csv", "w") as f:     # label + match in a comment header (pandas: comment="#")
        f.write(f"# {LABEL}\n# {sel.slug}: outcome 0 = {sel.n0}, outcome 1 = {sel.n1}; top of book every 250 ms, "
                f"server clock (UTC ms)\n")
        tl.to_csv(f, index=False, float_format="%.6g")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=None, help="pickle of the parsed recording (keep it outside the repo)")
    ap.add_argument("--figures-only", action="store_true")
    a = ap.parse_args()
    if not a.figures_only:
        run(a.cache)
    try:
        from scripts import match_replay_report as rep
    except ImportError:
        import match_replay_report as rep  # type: ignore
    rep.main()
