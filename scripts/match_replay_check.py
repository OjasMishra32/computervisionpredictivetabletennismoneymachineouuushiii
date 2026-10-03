#!/usr/bin/env python
"""Independent audit of the match replay (scripts/match_replay.py, results/replay/points.csv).

    BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not
    purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real
    recorded order book; paper only.

No video of any match was received, bought or watched. This script does not import scripts/match_replay.py.
It re-reads the raw Polymarket recording with its own parser, rebuilds both tokens' L2 books with its own
code from the text of research/replay/PROTOCOL.md §4, and re-runs the headline cells (stamp lag 2.0 s,
model lead, Florida 67 ms, seed 0, V = 0 / 0.5 / 1 s) from scratch. It checks:

  1. the rebuilt book against the server's own best bid / ask (the best_bid / best_ask fields of every
     price_change message, and the separate best_bid_ask events);
  2. every row of points.csv: timing arithmetic and no look-ahead, the reference ask, the ask at execution,
     the fill (shares and VWAP walked from the rebuilt ladder at the execution instant, never above the limit,
     never below the best ask), the +30 s mark, the held payout against market_resolved, the fee;
  3. the pooled headline numbers of replay.json, recomputed from the independent simulation;
  4. ten points picked by a fixed rule (seeded draw within status strata), with the raw messages that set
     the ask the order met;
  5. book staleness and crossed books at the execution instants;
  6. timing diagnostics against the latency sweep (research/v2/feed_latency/LATENCY_SWEEP.md): the official
     reprice cluster at whole server seconds, and the clock convention of the reprice time;
  7. the venue's matching clock: recorded prints cluster in the first 100 ms of each server second, so delayed
     marketable orders appear to match in whole-second batches. A labelled variant executes each order at the
     first whole server second at or after arrival + 1 s, against the book just before that batch (our order
     first) and 100 ms after it (our order last).

Recorder outages (deviation D1 of RESULTS.md) are found here from the raw receive stream with this script's own
code: a gap > 1 s between consecutive recorded lines (all markets).

Diagnostic variants (section 6; descriptive, labelled, no parameter chosen): the same replay with the
limit at the reference ask (no +1c), on points whose matched book move is >= 3c (the sweep's live pool),
and with the sweep's clock convention (reprice on the receive clock, 10 ms venue network + 2 ms gateway).

Writes results/replay/audit.json and results/replay/audit_handcheck.csv (both labelled).

    .venv/bin/python scripts/match_replay_check.py
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
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
FILES = ["data/live/market_20261003_0946.jsonl.gz", "data/live/market_20261003_1003.jsonl.gz"]
LATE = "data/live/market_20261003_1501.jsonl"
M1 = ROOT / "research/v2/latency/out/m1_points.csv"
EPS = 1e-9


# ============================================================================================ parsing
def load_points():
    P = pd.read_csv(M1).sort_values(["key", "n"], kind="stable").reset_index(drop=True)
    ev = L.events_table(L.load_meta()).drop_duplicates("slug").set_index("slug")
    toks = {s: (ev.loc[s].tok0, ev.loc[s].tok1) for s in P.slug.unique()}
    return P, toks


def parse(toks: dict) -> dict:
    """Raw messages of the 9 moneylines, keyed by slug. Market id taken from the raw messages themselves."""
    tok2 = {}
    for s, (a, b) in toks.items():
        tok2[a] = (s, 0)
        tok2[b] = (s, 1)
    tokb = {t.encode(): v for t, v in tok2.items()}
    cond_of = {}
    out = {s: [] for s in toks}          # (ts, rt, seq, kind, payload)
    seq = 0
    n_lines = 0
    gaps, prev = [], None
    for fn in FILES:
        try:
            with gzip.open(ROOT / fn, "rb") as fh:
                for line in fh:
                    n_lines += 1
                    if line[:6] == b'{"rt":':
                        t_ = int(line[6:19])
                        if prev is not None and t_ - prev > 1000:
                            gaps.append((prev, t_))
                        prev = t_ if prev is None else max(prev, t_)
                    # cheap prefilter: one of our 18 token ids must appear in the line
                    if b'"market_resolved"' in line[:600]:
                        try:
                            r = orjson.loads(line)
                        except orjson.JSONDecodeError:
                            continue
                        w = tok2.get(r.get("winning_asset_id"))
                        if w is not None:
                            seq += 1
                            _keep(r, tok2, out, cond_of, seq)
                        continue
                    j = line.find(b'"asset_id":"')
                    if j < 0:
                        continue
                    hit = None
                    k = j
                    while k >= 0:
                        a = line[k + 12:line.find(b'"', k + 12)]
                        if a in tokb:
                            hit = tokb[a]
                            break
                        k = line.find(b'"asset_id":"', k + 12)
                    if hit is None:
                        continue
                    try:
                        r = orjson.loads(line)
                    except orjson.JSONDecodeError:
                        continue
                    seq += 1
                    _keep(r, tok2, out, cond_of, seq)
        except (EOFError, OSError):
            pass
    # results: market_resolved in the same files, else the later file
    res = {}
    for s, evs in out.items():
        for e in evs:
            if e[3] == "res":
                res[s] = e[4]
    if len(res) < len(toks):
        with open(ROOT / LATE, "rb") as fh:
            for line in fh:
                if b"market_resolved" not in line:
                    continue
                r = orjson.loads(line)
                w = r.get("winning_asset_id")
                if w in tok2:
                    res.setdefault(tok2[w][0], tok2[w][1])
    return {"events": out, "res": res, "cond": cond_of, "n_lines": n_lines, "gaps_rt": gaps}


def _keep(r, tok2, out, cond_of, seq):
    et = r.get("event_type")
    rt = int(r["rt"])
    ts = int(r["timestamp"]) if r.get("timestamp") else rt
    if et == "price_change":
        ch = []
        for x in r.get("price_changes", []):
            t = tok2.get(x.get("asset_id"))
            if t is None:
                continue
            s = t[0]
            ch.append((t[1], x["side"], float(x["price"]), float(x["size"]),
                       float(x["best_bid"]) if x.get("best_bid") not in (None, "") else np.nan,
                       float(x["best_ask"]) if x.get("best_ask") not in (None, "") else np.nan))
        if ch:
            out[s].append((ts, rt, seq, "pc", ch))
            cond_of.setdefault(s, r.get("market"))
    elif et == "book":
        t = tok2.get(r.get("asset_id"))
        if t:
            out[t[0]].append((ts, rt, seq, "book", (t[1], [(float(x["price"]), float(x["size"])) for x in r["bids"]],
                                                     [(float(x["price"]), float(x["size"])) for x in r["asks"]])))
            cond_of.setdefault(t[0], r.get("market"))
    elif et == "best_bid_ask":
        t = tok2.get(r.get("asset_id"))
        if t:
            bb = float(r["best_bid"]) if r.get("best_bid") not in (None, "") else np.nan
            ba = float(r["best_ask"]) if r.get("best_ask") not in (None, "") else np.nan
            out[t[0]].append((ts, rt, seq, "bba", (t[1], bb, ba)))
    elif et == "last_trade_price":
        t = tok2.get(r.get("asset_id"))
        if t:
            out[t[0]].append((ts, rt, seq, "trade", (t[1], float(r["price"]), float(r["size"]), r.get("side"))))
    elif et == "market_resolved":
        t = tok2.get(r.get("winning_asset_id"))
        if t:
            out[t[0]].append((ts, rt, seq, "res", t[1]))


# ======================================================================================== the books
class Book:
    def __init__(self):
        self.b = [{}, {}]
        self.a = [{}, {}]
        self.snap = [False, False]

    def apply(self, kind, d):
        if kind == "pc":
            for tok, side, p, sz, _, _ in d:
                lv = self.b[tok] if side == "BUY" else self.a[tok]
                if sz > 0:
                    lv[p] = sz
                else:
                    lv.pop(p, None)
        elif kind == "book":
            tok, bids, asks = d
            self.b[tok] = {p: s for p, s in bids if s > 0}
            self.a[tok] = {p: s for p, s in asks if s > 0}
            self.snap[tok] = True

    def bb(self, tok):
        return max(self.b[tok]) if self.b[tok] else np.nan

    def ba(self, tok):
        return min(self.a[tok]) if self.a[tok] else np.nan


def recv_latency(events: dict) -> int:
    lat = [rt - ts for evs in events.values() for ts, rt, _, k, _ in evs if k == "pc"]
    return int(round(float(np.median(lat))))


def validate_vs_server(events: dict) -> dict:
    """Recording order: after each price_change message, compare the rebuilt best bid/ask of each token it
    touches with the server's best_bid / best_ask fields of the last change for that token."""
    out = {}
    for s, evs in events.items():
        bk = Book()
        n = ok = 0
        bad = []
        for ts, rt, seq, k, d in sorted(evs, key=lambda e: e[2]):
            if k not in ("pc", "book"):
                continue
            bk.apply(k, d)
            if k != "pc" or not (bk.snap[0] and bk.snap[1]):
                continue
            last = {}
            for tok, side, p, sz, sbb, sba in d:
                last[tok] = (sbb, sba)
            for tok, (sbb, sba) in last.items():
                mb, ma = bk.bb(tok), bk.ba(tok)
                # the server reports 0 / 1 for an empty side
                mb = 0.0 if not np.isfinite(mb) else mb
                ma = 1.0 if not np.isfinite(ma) else ma
                n += 1
                if abs(mb - sbb) < 1e-6 and abs(ma - sba) < 1e-6:
                    ok += 1
                elif len(bad) < 5:
                    bad.append({"ts": ts, "tok": tok, "server": [sbb, sba], "rebuilt": [mb, ma]})
        out[s] = {"checked": n, "agree": ok, "share": ok / n if n else float("nan"), "examples": bad}
    return out


def effective(evs: list, l_recv: int) -> list:
    rows = []
    for ts, rt, seq, k, d in evs:
        if k in ("pc", "book"):
            rows.append(((rt - l_recv) if k == "book" else ts, seq, k, d))
    rows.sort(key=lambda x: (x[0], x[1]))
    return rows


def states_at(rows: list, times) -> dict:
    """Book after every event with effective time <= t. Returns t -> dict."""
    bk = Book()
    out = {}
    j = 0
    last = None
    for t in sorted(set(int(x) for x in times)):
        while j < len(rows) and rows[j][0] <= t:
            bk.apply(rows[j][2], rows[j][3])
            last = rows[j][0]
            j += 1
        out[t] = {"bb": (bk.bb(0), bk.bb(1)), "ba": (bk.ba(0), bk.ba(1)),
                  "asks": (sorted(bk.a[0].items())[:30], sorted(bk.a[1].items())[:30]),
                  "last": last, "snap": tuple(bk.snap)}
    return out


def server_bbo(evs: list) -> dict:
    """Per token: arrays (ts, best_bid, best_ask) from best_bid_ask events and price_change fields."""
    ser = {0: [], 1: []}
    for ts, rt, seq, k, d in evs:
        if k == "bba":
            ser[d[0]].append((ts, seq, d[1], d[2]))
        elif k == "pc":
            last = {}
            for tok, side, p, sz, sbb, sba in d:
                last[tok] = (sbb, sba)
            for tok, (sbb, sba) in last.items():
                ser[tok].append((ts, seq, sbb, sba))
    out = {}
    for tok, v in ser.items():
        v.sort(key=lambda x: (x[0], x[1]))
        a = np.array([(x[0], x[2], x[3]) for x in v], float) if v else np.empty((0, 3))
        out[tok] = a
    return out


def bbo_at(arr, t):
    i = np.searchsorted(arr[:, 0], t, "right") - 1
    return (np.nan, np.nan, np.nan) if i < 0 else (arr[i, 1], arr[i, 2], arr[i, 0])


# ======================================================================================= simulation
def times_for(T, lead, lag_ms, V_ms, net_ms, inf_ms=20, delay_ms=1000):
    bounce = T - lag_ms
    frame = bounce - lead
    call = frame + V_ms + inf_ms
    t_ref = np.minimum(frame, call - net_ms)
    arrive = call + net_ms
    exe = arrive + delay_ms
    return {"bounce": bounce, "frame": frame, "call": call, "t_ref": t_ref, "arrive": arrive, "exec": exe,
            "mark": exe + 30_000}


def _inside(t, win):
    i = int(np.searchsorted(win[:, 0], t, "right")) - 1
    return i >= 0 and win[i, 0] < t < win[i, 1]


def simulate(P, S, tm, correct_u, res, limit_add=0.01, keep=None, l_recv=66, tb_clock="server", win=None,
             book_at=None):
    """book_at: optional dict of arrays overriding the instant the fill and the mark are read (batch variant)."""
    """Protocol §4 steps 4-11 from the text, on the independently rebuilt books S[slug][t]."""
    rows = []
    net = defaultdict(float)
    tb = P.t_book.to_numpy()
    for i, p in enumerate(P.itertuples()):
        st = {"slug": p.slug, "n": int(p.n), "status": "", "shares": 0.0, "vwap": np.nan, "pnl_mark": np.nan,
              "pnl_hold": 0.0, "correct": bool(correct_u[i] < 0.95), "ref_ask": np.nan, "ask_exec": np.nan,
              "limit": np.nan, "mid30": np.nan, "fee": 0.0, "payout": np.nan, "size_sent": 0.0}
        tbs = tb[i] - (l_recv if tb_clock == "server" else 0)
        t_ex = book_at["fill"][i] if book_at is not None else tm["exec"][i]
        st["beat"] = (t_ex < tbs) if np.isfinite(tb[i]) else None
        if keep is not None and not keep[i]:
            st["status"] = "excluded (diagnostic subset)"
            rows.append(st)
            continue
        Sm = S[p.slug]
        tr, te, tk = int(tm["t_ref"][i]), int(tm["exec"][i]), int(tm["mark"][i])
        sr, se, sk = Sm[tr], Sm[te], Sm[tk]
        if not (sr["snap"][0] and sr["snap"][1]) or se["last"] is None or se["last"] < te - 60_000:
            st["status"] = "no book recorded"
            rows.append(st)
            continue
        if win is not None and (_inside(tr, win) or _inside(te, win)):
            st["status"] = "no book recorded"
            rows.append(st)
            continue
        if book_at is not None:
            tf, tk = int(book_at["fill"][i]), int(book_at["mark"][i])
            se, sk = Sm[tf], Sm[tk]
            if win is not None and _inside(tf, win):
                st["status"] = "no book recorded"
                rows.append(st)
                continue
        if win is not None and _inside(tk, win):
            sk = None
        w = int(p.winner)
        c = w if st["correct"] else 1 - w
        d = 1 if c == 0 else -1
        bb, ba = sr["bb"][c], sr["ba"][c]
        st["ref_ask"] = ba
        if not (np.isfinite(bb) and np.isfinite(ba) and ba - bb <= 0.05 + EPS):
            st["status"] = "skipped (no tight quote)"
            rows.append(st)
            continue
        if not (0.05 - EPS <= ba <= 0.95 + EPS):
            st["status"] = "skipped (outside 5-95c)"
            rows.append(st)
            continue
        lim = round(ba + limit_add, 6)
        st["limit"] = lim
        allow = max(0.0, 100.0 - d * net[p.slug])
        if allow <= EPS:
            st["status"] = "blocked (net cap)"
            rows.append(st)
            continue
        size = min(allow, 1000.0 / lim)
        st["size_sent"] = size
        asks = se["asks"][c]
        st["ask_exec"] = asks[0][0] if asks else np.nan
        got = cost = fee = 0.0
        for px, sz in asks:
            if px > lim + EPS or got >= size - EPS:
                break
            take = min(sz, size - got)
            got += take
            cost += take * px
            fee += take * 0.05 * px * (1 - px)
        if got <= EPS:
            st["status"] = "missed"
            rows.append(st)
            continue
        pay = 1.0 if res[p.slug] == c else 0.0
        mb, ma = (sk["bb"][c], sk["ba"][c]) if sk is not None else (np.nan, np.nan)
        mid = (mb + ma) / 2 if (np.isfinite(mb) and np.isfinite(ma)) else np.nan
        net[p.slug] += d * got
        st.update({"status": "filled" if got >= size - 1e-6 else "partial", "shares": got, "vwap": cost / got,
                   "fee": fee, "payout": pay, "pnl_hold": got * pay - cost - fee, "mid30": mid,
                   "pnl_mark": got * mid - cost - fee if np.isfinite(mid) else np.nan})
        rows.append(st)
    return pd.DataFrame(rows)


def pooled(D: pd.DataFrame) -> dict:
    F = D[D.shares > EPS]
    calls = D[~D.status.isin(["no book recorded", "excluded (diagnostic subset)"]) & ~D.status.str.startswith("skipped")]
    wb = calls[calls.beat.notna()]
    Fm = F[F.pnl_mark.notna()]
    sh = F.shares.sum()
    return {"replayable": int((~D.status.isin(["no book recorded", "excluded (diagnostic subset)"])).sum()),
            "calls": int(len(calls)), "orders": int((calls.status != "blocked (net cap)").sum()),
            "fills": int(len(F)), "fills_wrong": int((~F.correct).sum()), "shares": float(sh),
            "pnl_mark_usd": float(Fm.pnl_mark.sum()), "pnl_hold_usd": float(F.pnl_hold.sum()),
            "per_share_mark_c": float(Fm.pnl_mark.sum() / Fm.shares.sum() * 100) if len(Fm) else float("nan"),
            "per_share_hold_c": float(F.pnl_hold.sum() / sh * 100) if sh else float("nan"),
            "calls_beat_book": int(wb.beat.astype(bool).sum()), "calls_with_reprice": int(len(wb)),
            "share_calls_beat_book": float(wb.beat.astype(bool).mean()) if len(wb) else float("nan"),
            "correct_fills_before_reprice": int((F.correct & (F.beat == True)).sum()),  # noqa: E712
            "sweep_def_fill_rate_correct_fills_over_calls": float(F.correct.sum() / len(calls)) if len(calls) else float("nan"),
            "correct_fills_before_reprice_over_calls": float((F.correct & (F.beat == True)).sum() / len(calls))  # noqa: E712
            if len(calls) else float("nan")}


# ============================================================================================== main
def main() -> None:
    P, toks = load_points()
    pts = pd.read_csv(OUT / "points.csv")
    rj = json.loads((OUT / "replay.json").read_text())
    print("parsing the raw recording (own parser) ...")
    R = parse(toks)
    ev = R["events"]
    l_recv = recv_latency(ev)
    print(f"  {R['n_lines']:,} lines; receive latency median {l_recv} ms; results {R['res']}")
    win = np.array([(a - l_recv, b - l_recv) for a, b in R["gaps_rt"]], dtype=np.int64).reshape(-1, 2)
    audit = {"label": LABEL, "independent_of": "scripts/match_replay.py (not imported)",
             "lines_scanned": R["n_lines"], "recv_latency_ms": l_recv,
             "recorder_outages": {"n": int(len(win)), "total_s": float((win[:, 1] - win[:, 0]).sum() / 1000),
                                  "longest_s": float((win[:, 1] - win[:, 0]).max() / 1000)}}
    print(f"  recorder outages (receive gaps > 1 s): {len(win)}, {(win[:, 1] - win[:, 0]).sum() / 1000:.1f} s")

    # ---------------------------------------------------------------- 1. rebuilt book vs the server's BBO
    val = validate_vs_server(ev)
    tot = sum(v["checked"] for v in val.values())
    agr = sum(v["agree"] for v in val.values())
    audit["server_bbo_check"] = {"checked": tot, "agree": agr, "share": agr / tot, "by_match": val}
    print(f"1. rebuilt top of book == server best_bid/best_ask after {agr:,} of {tot:,} price_change messages "
          f"({agr / tot:.4%})")

    # ---------------------------------------------------------------- independent re-run of the headline cells
    cvd = tier0.cv_systems()["own120"]
    p_out = tier0.point_mix()["women"]["out"]
    u = np.random.default_rng(0).random((len(P), 3))
    lead_s, _, called = tier0.lead_and_precision(cvd, u[:, 1], np.zeros(len(P)))
    lead = np.where((u[:, 0] < p_out) & called, np.round(lead_s * 1000), 0).astype(np.int64)
    T = P.T_ms.to_numpy().astype(np.int64)
    cells = {V: times_for(T, lead, 2000, int(V * 1000), 67) for V in (0.0, 0.5, 1.0)}
    # sweep clock convention diagnostic: Europe 10 ms + 2 ms gateway, reprice on the receive clock
    cells_sw = {V: times_for(T, lead, 2000, int(V * 1000), 12) for V in (0.0, 0.5, 1.0)}
    # whole-second batch variant: first whole server second at or after arrival + 1 s
    tick = {V: (np.ceil(cells[V]["exec"] / 1000) * 1000).astype(np.int64) for V in cells}
    batch = {(V, nm): {"fill": tick[V] + off, "mark": tick[V] + 30_000} for V in cells
             for nm, off in (("before_batch", -1), ("after_batch", 100))}
    need = defaultdict(set)
    for tm in list(cells.values()) + list(cells_sw.values()) + list(batch.values()):
        for k in ("t_ref", "exec", "mark", "fill"):
            if k not in tm:
                continue
            for s, t in zip(P.slug, tm[k]):
                need[s].add(int(t))
    rows = {s: effective(e, l_recv) for s, e in ev.items()}
    S = {s: states_at(rows[s], need[s]) for s in toks}
    bbo = {s: server_bbo(ev[s]) for s in toks}

    sims = {V: simulate(P, S, cells[V], u[:, 2], R["res"], l_recv=l_recv, win=win) for V in cells}

    # ---------------------------------------------------------------- 2. row by row against points.csv
    rowchk = {}
    for V, D in sims.items():
        Q = pts[pts.V == V].set_index(["slug", "n"])
        D = D.set_index(["slug", "n"])
        Q = Q.loc[D.index]
        st_q = Q.status.replace({"missed (book already moved)": "missed", "missed (no offers)": "missed"})
        o = Q.status.isin(["filled", "partial", "missed (book already moved)", "missed (no offers)"])
        tmV = cells[V]
        ix = {k: i for i, k in enumerate(zip(P.slug, P.n))}
        ii = np.array([ix[k] for k in D.index])
        timing_ok = bool((Q.exec_ms.to_numpy() == tmV["exec"][ii]).all() and (Q.ref_ms.to_numpy() == tmV["t_ref"][ii]).all()
                         and (Q.call_ms.to_numpy() == tmV["call"][ii]).all())
        no_lookahead = bool((Q.ref_ms <= Q.call_ms - 67).all() and (Q.ref_ms <= Q.frame_ms).all()
                            and (Q.exec_ms - Q.call_ms == 1067).all() and (Q.bounce_ms == Q.T_ms - 2000).all())
        # server BBO ask at exec for every order (called token)
        called_tok = np.where(Q.called_player.to_numpy() == Q.point_winner_name.to_numpy(),
                              P.winner.to_numpy()[ii], 1 - P.winner.to_numpy()[ii]).astype(int)
        srv_ask = np.array([bbo_at(bbo[s][c], te)[1] if oo else np.nan
                            for (s, n), c, te, oo in zip(Q.index, called_tok, Q.exec_ms.to_numpy(), o.to_numpy())])
        srv_age = np.array([te - bbo_at(bbo[s][c], te)[2] if oo else np.nan
                            for (s, n), c, te, oo in zip(Q.index, called_tok, Q.exec_ms.to_numpy(), o.to_numpy())])
        mine_ask = D.ask_exec.to_numpy()
        crossed = np.array([(S[s][int(te)]["bb"][c] >= S[s][int(te)]["ba"][c] - EPS) if oo else False
                            for (s, n), c, te, oo in zip(Q.index, called_tok, Q.exec_ms.to_numpy(), o.to_numpy())])
        stale = np.array([(int(te) - S[s][int(te)]["last"]) / 1000 if oo else np.nan
                          for (s, n), te, oo in zip(Q.index, Q.exec_ms.to_numpy(), o.to_numpy())])
        Fq = Q.shares > EPS
        rowchk[f"V{V:g}"] = {
            "rows": int(len(Q)), "orders": int(o.sum()), "fills": int(Fq.sum()),
            "status_identical": bool((st_q.to_numpy() == D.status.to_numpy()).all()),
            "status_mismatches": int((st_q.to_numpy() != D.status.to_numpy()).sum()),
            "timing_arithmetic_identical": timing_ok, "no_lookahead_and_delays_applied": no_lookahead,
            "ref_ask_identical": bool(np.allclose(Q.ref_ask.to_numpy(float), D.ref_ask.to_numpy(float), equal_nan=True)),
            "ask_at_exec_identical": bool(np.allclose(Q.ask_at_exec.to_numpy(float)[o], mine_ask[o], equal_nan=True)),
            "ask_at_exec_equals_server_bbo_share": float(np.mean(np.isclose(srv_ask[o], Q.ask_at_exec.to_numpy(float)[o]))),
            "server_bbo_age_at_exec_s_median": float(np.nanmedian(srv_age[o]) / 1000),
            "shares_identical": bool(np.allclose(Q.shares.to_numpy(float), D.shares.to_numpy(float), atol=1e-6)),
            "vwap_identical": bool(np.allclose(Q.vwap.to_numpy(float), D.vwap.to_numpy(float), equal_nan=True)),
            "pnl_mark_identical": bool(np.allclose(Q.pnl_mark.to_numpy(float)[Fq], D.pnl_mark.to_numpy(float)[Fq],
                                                   equal_nan=True, atol=1e-6)),
            "pnl_hold_identical": bool(np.allclose(Q.pnl_hold.to_numpy(float), D.pnl_hold.to_numpy(float), atol=1e-6)),
            "fills_above_limit": int((Q.vwap[Fq] > Q.limit[Fq] + EPS).sum()),
            "fills_below_best_ask_at_exec": int((Q.vwap[Fq] < Q.ask_at_exec[Fq] - EPS).sum()),
            "fills_with_crossed_book_at_exec": int(crossed[Fq.to_numpy()].sum()),
            "orders_with_crossed_book_at_exec": int(crossed[o.to_numpy()].sum()),
            "fills_where_server_bbo_ask_differs": int((~np.isclose(srv_ask, Q.ask_at_exec.to_numpy(float)))[Fq.to_numpy()].sum()),
            "book_age_at_exec_s": {"median": float(np.nanmedian(stale[o])), "p99": float(np.nanpercentile(stale[o], 99)),
                                   "max": float(np.nanmax(stale[o])), "orders_older_than_10s": int((stale[o] > 10).sum())},
            "wrong_calls_in_calls": int((~Q.correct_call.astype(bool) & ~Q.status.isin(["no book recorded"])
                                         & ~Q.status.str.startswith("skipped")).sum()),
            "wrong_call_fills": int((~Q.correct_call.astype(bool) & Fq).sum()),
        }
        print(f"2. V={V:g}: {rowchk[f'V{V:g}']}")
    audit["row_checks"] = rowchk

    # ---------------------------------------------------------------- 3. pooled numbers vs replay.json
    pc = {}
    for V, D in sims.items():
        mine = pooled(D)
        theirs = rj["headline_by_V"][f"V{V:g}"]["all"]
        pc[f"V{V:g}"] = {"independent": mine, "replay_json": {k: theirs.get(k) for k in mine if k in theirs},
                         "max_abs_diff": max(abs(float(mine[k]) - float(theirs[k])) for k in mine
                                             if k in theirs and theirs[k] is not None)}
        print(f"3. V={V:g}: fills {mine['fills']} ({theirs['fills']}), $mark {mine['pnl_mark_usd']:.2f} "
              f"({theirs['pnl_mark_usd']:.2f}), c/sh mark {mine['per_share_mark_c']:.3f} ({theirs['per_share_mark_c']:.3f}), "
              f"beat {mine['calls_beat_book']} ({theirs['calls_beat_book']})")
    audit["pooled_vs_replay_json"] = pc

    # ---------------------------------------------------------------- 4. ten points by a fixed rule
    rng = np.random.default_rng(20261003)
    strata = [(1.0, "filled correct", 3), (1.0, "filled wrong", 2), (1.0, "missed", 3), (1.0, "blocked", 1),
              (0.0, "filled correct before reprice", 1)]
    picks = []
    for V, name, k in strata:
        q = pts[pts.V == V]
        if name == "filled correct":
            q = q[(q.shares > 0) & q.correct_call.astype(bool)]
        elif name == "filled wrong":
            q = q[(q.shares > 0) & ~q.correct_call.astype(bool)]
        elif name == "missed":
            q = q[q.status.str.startswith("missed")]
        elif name == "blocked":
            q = q[q.status == "blocked (net cap)"]
        else:
            q = q[(q.shares > 0) & q.correct_call.astype(bool) & (q.beat_book == True)]  # noqa: E712
        q = q.sort_values(["slug", "n"])
        for j in sorted(rng.choice(len(q), size=min(k, len(q)), replace=False)):
            picks.append((V, name, q.iloc[j]))
    hc = []
    for V, name, r in picks:
        s = r.slug
        i = int(np.flatnonzero((P.slug == s).to_numpy() & (P.n == r.n).to_numpy())[0])
        w = int(P.winner[i])
        c = w if r.correct_call else 1 - w
        te, tr = int(r.exec_ms), int(r.ref_ms)
        st_e, st_r = S[s][te], S[s][tr]
        sb_e = bbo_at(bbo[s][c], te)
        sb_r = bbo_at(bbo[s][c], tr)
        # the raw messages that set the called token's asks at or below the limit in the 2 s before execution
        lim = r.limit if np.isfinite(r.limit) else (r.ref_ask + 0.01 if np.isfinite(r.ref_ask) else np.nan)
        raw = []
        for ts, rt, seq, k, d in ev[s]:
            if k == "pc" and te - 2000 <= ts <= te + 300:
                for tok, side, p, sz, sbb, sba in d:
                    if tok == c and side == "SELL" and np.isfinite(lim) and p <= lim + 0.02 + EPS:
                        raw.append(f"{'+' if ts > te else '-'}{abs(ts - te)}ms ask {p:g} -> {sz:g} (server best ask {sba:g})")
        ladder = [(p, round(z, 2)) for p, z in st_e["asks"][c][:4]]
        hc.append({"label": LABEL, "V": V, "stratum": name, "slug": s, "n": int(r.n), "called": r.called_player,
                   "correct_call": bool(r.correct_call), "T_utc": r.T_utc, "ref_utc": pd.Timestamp(tr, unit="ms", tz="UTC").isoformat(),
                   "exec_utc": r.exec_utc, "replay_status": r.status,
                   "ref_ask_replay": r.ref_ask, "ref_ask_rebuilt": st_r["ba"][c], "ref_ask_server_bbo": sb_r[1],
                   "limit": r.limit, "ask_exec_replay": r.ask_at_exec, "ask_exec_rebuilt": st_e["ba"][c],
                   "ask_exec_server_bbo": sb_e[1], "server_bbo_msg_age_ms": te - sb_e[2] if np.isfinite(sb_e[2]) else np.nan,
                   "ladder_at_exec_rebuilt": str(ladder), "size_sent": r.size_sent, "shares_replay": r.shares,
                   "vwap_replay": r.vwap, "mid30_replay": r.mid_30s,
                   "mid30_server_bbo": float(np.mean(bbo_at(bbo[s][c], te + 30_000)[:2])),
                   "t_book_srv_utc": r.t_book_srv_utc, "beat_book": r.beat_book,
                   "raw_ask_messages_exec_-2s_to_+0.3s": " | ".join(raw[-8:])})
    HC = pd.DataFrame(hc)
    HC.to_csv(OUT / "audit_handcheck.csv", index=False, float_format="%.6g")
    ok_hc = (np.isclose(HC.ref_ask_replay, HC.ref_ask_rebuilt, equal_nan=True)
             & np.isclose(HC.ref_ask_replay, HC.ref_ask_server_bbo, equal_nan=True)
             & np.isclose(HC.ask_exec_replay, HC.ask_exec_rebuilt, equal_nan=True)
             & (np.isclose(HC.ask_exec_replay, HC.ask_exec_server_bbo, equal_nan=True) | HC.ask_exec_replay.isna()))
    ok_hc = ok_hc | ((HC.replay_status == "blocked (net cap)") & np.isclose(HC.ref_ask_replay, HC.ref_ask_rebuilt)
                     & np.isclose(HC.ref_ask_replay, HC.ref_ask_server_bbo))
    audit["hand_check"] = {"rule": "rng(20261003) draw within strata: V=1 3 correct fills, 2 wrong fills, 3 misses, "
                                   "1 net-cap block; V=0 1 correct fill before the reprice",
                           "points": HC.drop(columns=["label"]).to_dict("records"), "all_agree": bool(ok_hc.all()),
                           "agree": int(ok_hc.sum())}
    print(f"4. hand-check: {int(ok_hc.sum())} of {len(HC)} agree (rebuilt book, server BBO, points.csv)")

    # ---------------------------------------------------------------- 6. timing diagnostics vs the sweep
    m = P[P.t_book.notna()].copy()
    srv_ms = (m.t_book - l_recv) % 1000
    cluster = float(((srv_ms >= 980) | (srv_ms < 40)).mean())
    R_rcv = (m.t_book - m.T_ms) / 1000
    diag = {"reprice_server_ms_of_second_in_[-20,+40)": cluster,
            "reprice_server_ms_of_second_expected_if_uniform": 0.06,
            "note": "a third of the matched reprices land within 40 ms after a whole server second"}
    lead_m = lead[P.t_book.notna().to_numpy()] / 1000
    for V in (0.0, 0.5, 1.0):
        # replay: exec = T - 2 + V + 0.020 + 0.067 + 1 - lead (server), reprice = t_book - l_recv (server)
        rep = (R_rcv - l_recv / 1000) > (-2 + V + 0.020 + 0.067 + 1.0 - lead_m)
        # sweep: arrival = -lead + 0.020 + V + lat + 0.002 + 1, reprice = R + 2 with R on the receive clock
        sw = {f"lat{lat}ms": float((R_rcv + 2 >= -lead_m + 0.020 + V + lat / 1000 + 0.002 + 1.0).mean())
              for lat in (10, 40, 100)}
        diag[f"V{V:g}"] = {"replay_convention_share_before_reprice": float(rep.mean()), "sweep_convention": sw}
    # the real book under the sweep's timing: correct calls at the sweep's (earlier) execution instant
    sw_sim = {}
    for V in (0.0, 0.5, 1.0):
        D = simulate(P, S, cells_sw[V], u[:, 2], R["res"], l_recv=l_recv, tb_clock="receive", win=win)
        sw_sim[f"V{V:g}"] = pooled(D)
    diag["real_book_at_sweep_timing_12ms_receive_clock_beat"] = sw_sim
    # variants: limit at the reference ask; D >= 3c pool; both
    D3 = (P.D.to_numpy() >= 0.03 - 1e-9) & P.t_book.notna().to_numpy()
    var = {}
    for nm, la, keep in (("limit_at_ref_ask", 0.0, None), ("D>=3c_points", 0.01, D3), ("D>=3c_and_limit_at_ref", 0.0, D3)):
        var[nm] = {f"V{V:g}": pooled(simulate(P, S, cells[V], u[:, 2], R["res"], limit_add=la, keep=keep, l_recv=l_recv,
                                              win=win))
                   for V in (0.0, 0.5, 1.0)}
    diag["variants"] = var
    # 7. the venue's matching clock
    trs = np.array([e[0] for evs in ev.values() for e in evs if e[3] == "trade"])
    diag["prints_ms_of_second_first_100ms_share"] = float((trs % 1000 < 100).mean())
    diag["prints_ms_of_second_first_50ms_share"] = float((trs % 1000 < 50).mean())
    diag["prints_n"] = int(len(trs))
    bv = {}
    for (V, nm), ba_ in batch.items():
        D = simulate(P, S, cells[V], u[:, 2], R["res"], l_recv=l_recv, win=win, book_at=ba_)
        bv.setdefault(nm, {})[f"V{V:g}"] = pooled(D)
    diag["whole_second_batch_variant"] = bv
    audit["sweep_diagnostics"] = diag
    for k, v in diag.items():
        print(f"6. {k}: {v}")

    (OUT / "audit.json").write_text(json.dumps(audit, indent=1, default=lambda o: (
        int(o) if isinstance(o, np.integer) else (None if isinstance(o, float) and not np.isfinite(o) else
                                                  float(o) if isinstance(o, np.floating) else
                                                  bool(o) if isinstance(o, np.bool_) else str(o)))))
    print("wrote results/replay/audit.json, results/replay/audit_handcheck.csv")


if __name__ == "__main__":
    main()
