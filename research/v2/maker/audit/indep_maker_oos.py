"""Audit: independent recompute of the maker v1 blind OOS primary (PREREG research/v2/maker/PREREG.md section 1, 2.5).

Own code. Does NOT import scripts/maker_oos.py, research/v2/maker/oos_test.py, oos_build.py or the crossmarket
lens code. Reads only raw cached public data:
  - src.tape.universe() (the frozen OOS split definition; cached Gamma catalogue)
  - data/v2_maker/oos/events_raw/*.json (cached Gamma /events responses)
  - data/v2_maker/oos/trades/<cond>.parquet (side tapes, data-api)
  - data/raw/trades/<ml_cond>.parquet (burned OOS moneyline tapes; used ONLY as the signal input)
Paper only, no network access in this script.

Usage: python indep_maker_oos.py [extra_cut_seconds ...]
"""
from __future__ import annotations

import glob
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from src.tape import universe  # noqa: E402  (frozen OOS split; not an audited script)

OOS_START = pd.Timestamp("2026-08-25 14:15", tz="UTC")
OOS_END = pd.Timestamp("2026-10-03 14:00", tz="UTC")
B_T = {"tennis_first_set_winner": 1.527875991592811, "tennis_set_winner": 1.0781295500280448,
       "tennis_set_handicap": 0.8171462571666066, "tennis_match_totals": 1.8243248664803704,
       "tennis_set_totals": 2.721259317541827, "tennis_first_set_totals": 3.514143233195978}
PLAYER = {"tennis_first_set_winner", "tennis_set_winner", "tennis_set_handicap"}
TOTALS = {"tennis_match_totals", "tennis_set_totals", "tennis_first_set_totals"}


# ----------------------------------------------------------------- catalogue (own parse of the Gamma cache)
def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s).strip()


def align(o, a, b, smt):
    s = norm(o)
    if smt not in PLAYER and smt != "tennis_game_handicap" or not s:
        return 0
    a, b = norm(a), norm(b)
    toks = s.split()
    ha = s in a or any(t in a.split() for t in toks if len(t) > 2)
    hb = s in b or any(t in b.split() for t in toks if len(t) > 2)
    return 1 if ha and not hb else (-1 if hb and not ha else 0)


def catalogue():
    u = universe()
    u = u[u.oos & (u.start >= OOS_START) & (u.start < OOS_END)].copy()
    u["event_id"] = u.event_id.astype(str)
    ug = u.set_index("event_id")
    rows = []
    for f in sorted(glob.glob("data/v2_maker/oos/events_raw/batch_*.json")):
        for e in json.loads(Path(f).read_text()):
            for m in e["markets"]:
                rows.append({"event_id": str(e["id"]), **m})
    m = pd.DataFrame(rows)
    m = m[m.event_id.isin(ug.index) & (m.sportsMarketType != "moneyline")]
    m = m.drop_duplicates("conditionId")
    out = []
    for r in m.itertuples(index=False):
        smt = r.sportsMarketType
        if smt not in B_T:
            continue
        outs = json.loads(r.outcomes) if r.outcomes else []
        toks = json.loads(r.clobTokenIds) if r.clobTokenIds else []
        px = json.loads(r.outcomePrices) if r.outcomePrices else []
        if len(outs) != 2 or len(toks) != 2:
            continue
        vol = float(r.volume) if r.volume is not None else 0.0
        vol = 0.0 if vol != vol else vol
        res = tuple(float(x) for x in px) if len(px) == 2 else None
        resolved = res in ((1.0, 0.0), (0.0, 1.0), (0.5, 0.5))
        over_first = str(outs[0]).strip().lower().startswith("over")
        fs = r.feeSchedule or {}
        mlr = ug.loc[r.event_id]
        rate = fs.get("rate")
        rate = float(rate) if rate is not None else (float(mlr.fee_rate) if pd.notna(mlr.fee_rate) else 0.0)
        delay = int(r.secondsDelay) if r.secondsDelay is not None else int(mlr.delay)
        out.append({"event_id": r.event_id, "cond": r.conditionId, "smt": smt, "vol": vol, "resolved": resolved,
                    "res_s0": res[0] if res else np.nan, "over_first": over_first, "fee_rate": rate, "delay": delay,
                    "align0": align(outs[0], mlr.out0, mlr.out1, smt), "ml_cond": mlr.cond,
                    "start": mlr.start, "end": mlr.end})
    c = pd.DataFrame(out)
    c["selected"] = (c.vol >= 250) & c.resolved & ~(c.smt.isin(TOTALS) & ~c.over_first)
    return u, c


# ----------------------------------------------------------------- per-print computation (own implementation)
def tape(path, axis_col=None):
    t = pd.read_parquet(path)
    if t.empty:
        return None
    t = t.sort_values("timestamp", kind="stable").reset_index(drop=True)
    at_ask = (((t.side == "BUY") & (t.outcomeIndex == 0)) | ((t.side == "SELL") & (t.outcomeIndex == 1))).to_numpy()
    q0 = np.where(t.outcomeIndex == 0, t.price, 1 - t.price).astype(float)
    return pd.DataFrame({"ts": t.timestamp.astype(float).to_numpy(), "q0": q0, "at_ask": at_ask,
                         "size": t["size"].astype(float).to_numpy()})


def mid_proxy(ts, p, aa, stale):
    """Mean of the latest at-ask and latest at-bid prints (each <= stale s old) if ask >= bid, else the print."""
    s = pd.DataFrame({"ap": np.where(aa, p, np.nan), "ats": np.where(aa, ts, np.nan),
                      "bp": np.where(~aa, p, np.nan), "bts": np.where(~aa, ts, np.nan)}).ffill()
    ask = np.where(ts - s["ats"].to_numpy() <= stale, s.ap.to_numpy(), np.nan)
    bid = np.where(ts - s["bts"].to_numpy() <= stale, s.bp.to_numpy(), np.nan)
    ok = np.isfinite(ask) & np.isfinite(bid) & (ask >= bid)
    return np.where(ok, (ask + bid) / 2, p)


def lg(x):
    x = np.clip(x, 0.005, 0.995)
    return np.log(x / (1 - x))


def ex(z):
    return 1 / (1 + np.exp(-z))


def per_print(u, cat, extra_cut=0.0):
    sel = cat[cat.selected]
    rows = []
    for ev, g in sel.groupby("event_id"):
        r = u.set_index("event_id").loc[ev] if False else UIDX.loc[ev]
        s0 = int(pd.Timestamp(r.start).timestamp())
        e0 = int(pd.Timestamp(r.end).timestamp()) if pd.notna(r.end) else s0 + 6 * 3600
        mlf = ROOT / "data" / "raw" / "trades" / f"{r.cond}.parquet"
        if not mlf.exists():
            continue
        ml = tape(mlf)
        if ml is None:
            continue
        ml = ml[(ml.ts >= s0) & (ml.ts <= e0)].reset_index(drop=True)
        if len(ml) < 20:
            continue
        mts = ml.ts.to_numpy()
        mmid = mid_proxy(mts, ml.q0.to_numpy(), ml.at_ask.to_numpy(), 30)

        def ml_le(t):   # ML mid at last ML print with ts <= t
            i = np.searchsorted(mts, t, "right") - 1
            return np.where((i >= 0) & np.isfinite(t), mmid[np.maximum(i, 0)], np.nan)

        def ml_lt(t):   # ML mid at last ML print with ts < t
            i = np.searchsorted(mts, t, "left") - 1
            return np.where((i >= 0) & np.isfinite(t), mmid[np.maximum(i, 0)], np.nan)

        for m in g.itertuples(index=False):
            f = ROOT / "data" / "v2_maker" / "oos" / "trades" / f"{m.cond}.parquet"
            t = tape(f)
            if t is None:
                continue
            t = t[(t.ts >= s0) & (t.ts <= e0)].reset_index(drop=True)
            n = len(t)
            if n < 2:
                continue
            ts, q, aa = t.ts.to_numpy(), t.q0.to_numpy(), t.at_ask.to_numpy()
            smid = mid_proxy(ts, q, aa, 120)
            pnow = ml_le(ts)
            # intervals: consecutive prints <= 300 s apart, ending at ts[i]
            i1 = np.flatnonzero(np.diff(ts) <= 300) + 1
            m1, m2, p1, p2 = smid[i1 - 1], smid[i1], pnow[i1 - 1], pnow[i1]
            player = m.smt in PLAYER
            if player:
                if m.align0 == -1:
                    m1, m2 = 1 - m1, 1 - m2
                x = lg(p2) - lg(p1)
            else:
                x = 4 * p2 * (1 - p2) - 4 * p1 * (1 - p1)
            y = lg(m2) - lg(m1)
            ok = ((m1 > .03) & (m1 < .97) & (m2 > .03) & (m2 < .97) & (p1 > .03) & (p1 < .97) & (p2 > .03)
                  & (p2 < .97) & np.isfinite(x) & np.isfinite(y))
            if player and m.align0 == 0:
                ok[:] = False
            cxy = np.cumsum(np.where(ok, x * y, 0.0))
            cxx = np.cumsum(np.where(ok, x * x, 0.0))
            iv_end = ts[i1]
            # signal at each print j, information cut t* = ts_j - d (- extra)
            tstar = ts - m.delay - extra_cut
            jr = np.searchsorted(ts, tstar, "left") - 1     # last side print strictly before t*
            has = jr >= 0
            jrr = np.maximum(jr, 0)
            ts_r = np.where(has, ts[jrr], np.nan)
            q_ref = np.where(has, smid[jrr], np.nan)
            p_ref = ml_le(ts_r)
            p_new = ml_lt(tstar)
            k = np.searchsorted(iv_end, np.nan_to_num(ts_r, nan=-1e18), "right") - 1   # intervals ending <= ts_r
            sxy = np.where(k >= 0, cxy[np.maximum(k, 0)] if len(cxy) else 0.0, 0.0)
            sxx = np.where(k >= 0, cxx[np.maximum(k, 0)] if len(cxx) else 0.0, 0.0)
            bT = B_T[m.smt]
            b = (sxy + 1.0 * bT) / (sxx + 1.0)
            if player:
                flip = m.align0 == -1
                qa = 1 - q_ref if flip else q_ref
                qn = ex(lg(qa) + b * (lg(p_new) - lg(p_ref)))
                qn = 1 - qn if flip else qn
            else:
                qn = ex(lg(q_ref) + b * (4 * p_new * (1 - p_new) - 4 * p_ref * (1 - p_ref)))
            impl = qn - q_ref
            rows.append(pd.DataFrame({"event_id": ev, "cond": m.cond, "smt": m.smt, "ts": ts, "q0": q, "at_ask": aa,
                                      "size": t["size"].to_numpy(), "tstar": tstar, "ts_r": ts_r, "q_ref": q_ref,
                                      "p_ref": p_ref, "p_new": p_new, "impl": impl, "res_s0": m.res_s0,
                                      "fee_rate": m.fee_rate}))
    return pd.concat(rows, ignore_index=True)


def book(pp, min_impl=0.04, side="lean"):
    c = pp.dropna(subset=["q_ref", "p_ref", "p_new", "impl", "res_s0"])
    c = c[(c.tstar - c.ts_r) <= 600]
    idir = np.sign(c.impl)
    tdir = np.where(c.at_ask, 1.0, -1.0)
    if side == "lean":
        f = c[(tdir == -idir) & (c.impl.abs() >= min_impl)].copy()
    else:
        f = c[(tdir == idir) & (c.impl.abs() >= min_impl)].copy()
    long0 = ~f.at_ask.to_numpy()        # maker long outcome 0 when the taker sold outcome 0
    f["px"] = np.where(long0, f.q0, 1 - f.q0)
    f = f[(f.px > 0.02) & (f.px < 0.98)].sort_values("ts", kind="stable")
    long0 = ~f.at_ask.to_numpy()
    f["shares"] = np.minimum(0.2 * f["size"], 250.0 / f.px)
    f["usd"] = f.shares * f.px
    f = f[f.groupby("event_id").usd.cumsum() <= 2000.0].copy()
    long0 = ~f.at_ask.to_numpy()
    f["payout"] = np.where(long0, f.res_s0, 1 - f.res_s0)
    f["rebate"] = 0.15 * f.fee_rate * f.q0 * (1 - f.q0)
    f["pnl_ps"] = f.payout - f.px + f.rebate
    f["pnl"] = f.shares * f.pnl_ps
    return f, len(c)


def cluster_ci(f, col="pnl_ps", w=None, seed=0, n_boot=2000):
    ww = f[w].to_numpy() if w else np.ones(len(f))
    g = pd.DataFrame({"s": f[col].to_numpy() * ww, "n": ww, "c": f.event_id.to_numpy()}).groupby("c").sum()
    s, n = g.s.to_numpy(), g.n.to_numpy()
    rng = np.random.default_rng(seed)
    k = len(g)
    bs = np.array([(lambda p: s[p].sum() / n[p].sum())(rng.integers(0, k, k)) for _ in range(n_boot)])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return float(lo * 100), float(hi * 100)


UIDX = None

if __name__ == "__main__":
    extra = [float(x) for x in sys.argv[1:]] or [0.0]
    u, cat = catalogue()
    UIDX = u.set_index("event_id")
    six = cat
    print("catalogue (own parse): six-type binary markets", len(six), "| vol<250", int((six.vol < 250).sum()),
          "| vol ok & unresolved", int(((six.vol >= 250) & ~six.resolved).sum()),
          "| selected", int(six.selected.sum()))
    print("selected by type", six[six.selected].smt.value_counts().to_dict())
    print("regimes", six[six.selected].groupby(["delay", "fee_rate"]).size().to_dict())
    out = {}
    for x in extra:
        pp = per_print(u, cat, x)
        f, nsig = book(pp)
        lo, hi = cluster_ci(f)
        slo, shi = cluster_ci(f, w="shares")
        r = {"extra_cut_s": x, "inplay_prints": len(pp), "markets": pp.cond.nunique(), "events": pp.event_id.nunique(),
             "with_signal": nsig, "fills": len(f), "matches": f.event_id.nunique(),
             "net_c": f.pnl_ps.mean() * 100, "ci": [lo, hi],
             "share_w_c": f.pnl.sum() / f.shares.sum() * 100, "share_w_ci": [slo, shi],
             "pnl_usd": f.pnl.sum(), "notional": f.usd.sum()}
        print(json.dumps(r, default=float))
        out[x] = (pp, f)
        if x == 0.0:
            pp.to_parquet(Path(__file__).with_name("indep_pp.parquet"))
            f.to_parquet(Path(__file__).with_name("indep_book.parquet"))
            a, _ = book(pp, side="anti")
            a2 = a.copy()
            print("anti-lean (sized, own code): n", len(a), "net_c", a.pnl_ps.mean() * 100)
