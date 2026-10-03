"""Table tennis TT1-TT4, exactly as pre-registered in HYPOTHESIS_TT.md (decisions: research/tt/DEVIATIONS.md).

    python scripts/tt_analyze.py              # the single run; logged BEFORE any result is printed
    python scripts/tt_analyze.py --dry OUTDIR # plumbing check on tennis data (already studied); not logged

Tennis code paths are used unchanged: run_all.calibration (TT1), src.fasttier.walk_forward (TT2),
src.v2.run(..., causal=True) with research/v2/sizing/engine.py (TT3). Nothing in src/ or research/v2/ is
edited. Outputs: results/tt/results.json, results/tt/fig_fasttier.png, results/tt/fig_v2_equity.png.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # src.polymarket caches under the relative path data/raw

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from run_all import calibration  # noqa: E402  (also loads src.report's figure style)
from scripts.tt_build import _market_volume  # noqa: E402
from src import fasttier, tiers, v2  # noqa: E402
from src.tape import in_play, load_tape  # noqa: E402

E = v2.E
CUT = pd.Timestamp("2026-09-16 05:30", tz="UTC")
TOP = "[0.99, 1.0)"
BINS = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.97, 0.98, 0.99, 1.0]
MIN_JUDGED = 30
OUT = ROOT / "results/tt"
LOG_TT = OUT / "peeks.log"
LOG_TRACK = ROOT / "results/oos_peeks.log"
CAPACITY_USD_PER_DAY = 1_000


def _f(x):
    """JSON-safe float (NaN -> None)."""
    if x is None:
        return None
    x = float(x)
    return None if not np.isfinite(x) else x


def _boot_ratio(num: np.ndarray, den: np.ndarray, n_boot: int, seed: int):
    rng = np.random.default_rng(seed)
    k = len(num)
    bs = [num[i].sum() / den[i].sum() for i in (rng.integers(0, k, k) for _ in range(n_boot))]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


# ----------------------------------------------------------------------------------------- data
def load(sens: bool = False):
    U = pd.read_parquet("data/tt/universe.parquet")
    P = pd.read_parquet("data/tt/prints.parquet")
    if sens:
        Uu = pd.read_parquet("data/tt/universe_unlisted.parquet")
        Pu = pd.read_parquet("data/tt/prints_unlisted.parquet")
        assert not set(Uu.cond) & set(U.cond)
        U = pd.concat([U, Uu], ignore_index=True)
        P = pd.concat([P, Pu], ignore_index=True)
    return U, P


def tag(df: pd.DataFrame, U: pd.DataFrame) -> pd.DataFrame:
    m = U.set_index("cond")
    return df.assign(league=df.cond.map(m.league), oos=df.cond.map(m.oos).astype(bool))


# ------------------------------------------------------------------------------------------ TT1
def cal_obs_boot(df: pd.DataFrame, n_boot: int = 500, seed: int = 0):
    """The observations and per-bin bootstrap draws of run_all.calibration (same code, same rng order)."""
    df = df[df.res.isin([0.0, 1.0])]
    s = df.assign(minute=(df.ts // 60).astype(int)).groupby(["cond", "minute"]).first().reset_index()
    s["fav"] = np.maximum(s.p, 1 - s.p)
    s["won"] = np.where(s.p >= 0.5, s.res, 1 - s.res)
    s["bin"] = pd.cut(s.fav, BINS, right=False)
    rng = np.random.default_rng(seed)
    bs = {}
    for b, g in s.groupby("bin", observed=True):
        m = g.groupby("cond").agg(w=("won", "sum"), n=("won", "size"))
        bs[str(b)] = np.array([m.w.to_numpy()[i].sum() / m.n.to_numpy()[i].sum()
                               for i in (rng.integers(0, len(m), len(m)) for _ in range(n_boot))])
    return s, bs


def cal_test(df: pd.DataFrame, exclude_top: bool) -> dict:
    d = df[df.res.isin([0.0, 1.0])]
    if d.empty:
        return {"verdict": "no observations", "n_obs": 0, "n_matches": 0, "judged_bins": 0, "bins": []}
    tab = calibration(d)
    _, bs = cal_obs_boot(d)
    for r in tab.itertuples():  # parity with the tennis function
        assert np.isclose(np.percentile(bs[r.bin], 2.5), r.lo) and np.isclose(np.percentile(bs[r.bin], 97.5), r.hi)
    tab["judged"] = (tab.n_matches >= MIN_JUDGED) & ~((tab.bin == TOP) & exclude_top)
    tab["ci_covers_price"] = (tab.lo <= tab.mean_price) & (tab.mean_price <= tab.hi)
    k = int(tab.judged.sum())
    if k:
        a = 0.025 / k
        tab["bonf_lo"] = [np.percentile(bs[b], 100 * a) for b in tab.bin]
        tab["bonf_hi"] = [np.percentile(bs[b], 100 * (1 - a)) for b in tab.bin]
        tab["bonf_covers_price"] = (tab.bonf_lo <= tab.mean_price) & (tab.mean_price <= tab.bonf_hi)
    if k == 0:
        verdict = "not judged (no bin with >= 30 matches)"
    else:
        verdict = "calibrated" if bool(tab[tab.judged].ci_covers_price.all()) else "not calibrated"
    out = {"verdict": verdict, "n_obs": int(tab.n_obs.sum()), "n_matches": int(d.cond.nunique()),
           "judged_bins": k, "failing_judged_bins": tab[tab.judged & ~tab.ci_covers_price].bin.tolist(),
           "bins": json.loads(tab.to_json(orient="records"))}
    if k:
        out["bonferroni_level"] = 1 - 0.05 / k
        out["bonferroni_failing_judged_bins"] = tab[tab.judged & ~tab.bonf_covers_price].bin.tolist()
    return out


def closing_obs(U: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows, n_no_tape = [], 0
    for r in U[U.res0.isin([0.0, 1.0])].itertuples():
        t = load_tape(r.cond)
        if t is None:
            n_no_tape += 1
            continue
        s = int(r.start.timestamp())
        w = t[(t.timestamp >= s - 86_400) & (t.timestamp < s)]
        if len(w):
            rows.append({"cond": r.cond, "ts": float(w.timestamp.iloc[-1]), "p": float(w.p0.iloc[-1]),
                         "res": float(r.res0), "league": r.league, "oos": bool(r.oos)})
    c = pd.DataFrame(rows)
    n_elig = int(U.res0.isin([0.0, 1.0]).sum())
    return c, {"eligible_matches": n_elig, "with_prestart_fill": int(len(c)), "no_tape": n_no_tape,
               "without_prestart_fill": n_elig - int(len(c)) - n_no_tape}


def truncate_at_99(P: pd.DataFrame) -> pd.DataFrame:
    P = P.sort_values(["cond", "ts"], kind="stable")
    hit = (np.maximum(P.p, 1 - P.p) >= 0.99).groupby(P.cond).cummax()
    return P[~hit]


def tt1(P: pd.DataFrame, U: pd.DataFrame) -> dict:
    inplay = cal_test(P, exclude_top=True)
    cobs, cov = closing_obs(U)
    closing = cal_test(cobs, exclude_top=False) if len(cobs) else {"verdict": "no observations", "bins": []}
    closing["coverage"] = cov
    s, _ = cal_obs_boot(P[P.res.isin([0.0, 1.0])])
    x = s[(s.fav >= 0.5) & (s.fav < 0.99)].assign(x=lambda d: d.won - d.fav)
    pooled = {"n_obs": int(len(x)), "n_matches": int(x.cond.nunique())}
    if len(x):
        lo, hi = fasttier.cluster_ci(x, "x", 2000, 0)
        pooled.update(mean_c=x.x.mean() * 100, ci_c=[lo * 100, hi * 100])
    holds = inplay["verdict"] == "calibrated" and closing["verdict"] == "calibrated"
    return {
        "inplay": inplay, "closing": closing,
        "verdict": "PASS" if holds else "FAIL",
        "verdict_detail": f"in-play: {inplay['verdict']}; closing: {closing['verdict']}",
        "secondary": {
            "pooled_won_minus_fav_inplay_050_099": pooled,
            "inplay_truncated_at_first_fav_ge_099": cal_test(truncate_at_99(P), exclude_top=True),
            "inplay_by_league": {lg: cal_test(g, True) for lg, g in P.groupby("league")},
            "closing_by_league": {lg: cal_test(g, False) for lg, g in cobs.groupby("league")} if len(cobs) else {},
        },
    }


# ------------------------------------------------------------------------------------------ TT2
def labelled_03(Pc: pd.DataFrame):
    """The 0-3 s (causal) prints of every evaluated month, labelled fast / other exactly as walk_forward does."""
    X = fasttier.net_cols(Pc.assign(month=pd.to_datetime(Pc.ts, unit="s").dt.to_period("M")))
    months = sorted(X.month.unique())
    parts, qual = [], {}
    for m in months[2:]:
        sel = fasttier.qualify(X[X.month < m], "bucket_c")
        qual[str(m)] = int(len(sel))
        cur = X[(X.month == m) & (X.bucket_c == "0-3s")]
        parts.append(cur.assign(fast=cur.wallet.isin(sel), n_qual=len(sel)))
    L = pd.concat(parts) if parts else X.iloc[:0].assign(fast=False, n_qual=0)
    return L, qual, [str(m) for m in months]


def mean_ci(d: pd.DataFrame, col: str = "net30"):
    if d.empty:
        return None
    lo, hi = fasttier.cluster_ci(d, col, 2000, 0)
    return [d[col].mean() * 100, lo * 100, hi * 100]


def gap_ci(Ld: pd.DataFrame):
    """forward_test.py Primary A: fast minus others, resampling matches (2,000 draws, seed 0)."""
    if not Ld.fast.any() or Ld.fast.all():
        return None
    g = Ld.groupby(["cond", "fast"]).net30.agg(["sum", "size"]).unstack(fill_value=0)
    rng = np.random.default_rng(0)
    k = len(g)

    def diff(ix):
        gg = g.iloc[ix]
        f_ = gg[("sum", True)].sum() / max(gg[("size", True)].sum(), 1)
        o_ = gg[("sum", False)].sum() / max(gg[("size", False)].sum(), 1)
        return (f_ - o_) * 100

    bs = [diff(rng.integers(0, k, k)) for _ in range(2000)]
    return [float(diff(np.arange(k))), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]


def tt2(P: pd.DataFrame):
    Pc = tiers.add_causal_bucket(P)
    wf, sh, by_bucket = fasttier.walk_forward(Pc, start_month=2, bucket="bucket_c")
    L, qual, months = labelled_03(Pc)
    # parity with walk_forward's own output
    assert int(L.fast.sum()) == len(sh), (int(L.fast.sum()), len(sh))
    for r in wf.itertuples():
        cur = L[(L.month.astype(str) == r.month)]
        assert len(cur[cur.fast]) == r.n_prints and qual[r.month] == r.n_wallets
        for a, b in ((cur[cur.fast].net30.mean() * 100, r.net30_c), (cur[~cur.fast].net30.mean() * 100, r.others_net30_c)):
            assert (np.isnan(a) and np.isnan(b)) or np.isclose(a, b)
    Ld = L.dropna(subset=["net30"])
    F, O = Ld[Ld.fast], Ld[~Ld.fast]
    fast, others = mean_ci(F), mean_ci(O)
    O_q = O[O.n_qual >= 1]
    monthly = []
    for m in [str(x) for x in sorted(L.month.unique())] if len(L) else []:
        f_m, o_m = F[F.month.astype(str) == m], O[O.month.astype(str) == m]
        monthly.append({"month": m, "n_qualified_wallets": qual[m],
                        "fast_prints": int(len(f_m)), "fast_matches": int(f_m.cond.nunique()),
                        "fast_usd": float(f_m.usd.sum()), "fast_net30_c": mean_ci(f_m),
                        "others_prints": int(len(o_m)), "others_matches": int(o_m.cond.nunique()),
                        "others_net30_c": mean_ci(o_m)})
    for m in qual:  # evaluated months with no 0-3 s print at all
        if m not in {x["month"] for x in monthly}:
            monthly.append({"month": m, "n_qualified_wallets": qual[m], "fast_prints": 0, "fast_matches": 0,
                            "fast_usd": 0.0, "fast_net30_c": None, "others_prints": 0, "others_matches": 0,
                            "others_net30_c": None})
    monthly.sort(key=lambda x: x["month"])
    m_fast = [x for x in monthly if x["fast_prints"] > 0]
    m_pos = sum(1 for x in m_fast if x["fast_net30_c"][0] > 0)
    per = {}
    for name, flag in (("IS", False), ("OOS", True)):
        d = F[F.oos == flag]
        per[name] = {"fast_prints": int(len(d)), "fast_matches": int(d.cond.nunique()), "fast_net30_c": mean_ci(d)}
    any_q = any(v > 0 for v in qual.values())
    crit = {
        "a_fast_gt0_ci_excl0": bool(fast is not None and fast[1] > 0),
        "b_others_lt0_ci_excl0": bool(others is not None and others[2] < 0),
        "c_fast_gt0_in_2of3_months": bool(len(m_fast) > 0 and m_pos >= 2 / 3 * len(m_fast)),
        "d_fast_gt0_IS_and_OOS": bool(all(per[p]["fast_net30_c"] is not None and per[p]["fast_net30_c"][0] > 0
                                          for p in ("IS", "OOS"))),
    }
    n_fast_matches = int(F.cond.nunique())
    if not any_q:
        verdict = "FAIL (no fast tier detected)"
    else:
        verdict = "PASS" if all(crit.values()) else "FAIL"
    labels = ["underpowered"] if n_fast_matches < 30 else []
    by_b = by_bucket.reset_index() if len(by_bucket) else pd.DataFrame()
    res = {
        "print_months": months, "evaluated_months": list(qual), "qualified_wallets_by_month": qual,
        "any_wallet_qualified": any_q, "fast_net30_c": fast, "others_net30_c": others,
        "gap_fast_minus_others_c": gap_ci(Ld),
        "others_net30_c_months_with_qualified_wallet": mean_ci(O_q),
        "n_fast_prints": int(len(F)), "n_fast_matches": n_fast_matches,
        "n_others_prints": int(len(O)), "n_others_matches": int(O.cond.nunique()),
        "months_with_fast_prints": len(m_fast), "months_fast_positive": m_pos,
        "by_period": per, "criteria": crit, "verdict": verdict, "labels": labels,
        "monthly": monthly, "wf_table": json.loads(wf.to_json(orient="records")),
        "by_bucket_c_net30_c": json.loads(by_b.to_json(orient="records")) if len(by_b) else [],
    }
    return res, L, Pc


# ------------------------------------------------------------------------------------------ TT3
KEYS_STRESS = ("per_share_c", "per_share_ci_c", "total_pnl_usd", "sharpe_ann", "max_dd_pct", "worst_day_usd")


def book_stats(t: pd.DataFrame) -> dict:
    """E.metrics on the full subset (share/$ metrics) with counts from non-empty-training trades (TT-D6)."""
    t = t[t.month >= E.EVAL_START]
    ne = t[~t.empty_train]
    if t.empty or ne.empty:
        return {"n_trades": 0, "n_matches": 0, "n_trades_incl_empty_training": int(len(t))}
    m = E.metrics(t)
    m["n_trades_incl_empty_training"] = int(len(t))
    m["n_trades"], m["n_matches"] = int(len(ne)), int(ne.cond.nunique())
    mn = E.metrics(ne)
    m["per_print_c"], m["per_print_ci_c"] = mn["per_print_c"], mn["per_print_ci_c"]
    g = ne.assign(w=(ne.pnl_ps > 0).astype(float)).groupby("cond").w.agg(["sum", "size"])
    m["trade_win_rate"] = float((ne.pnl_ps > 0).mean())
    m["trade_win_rate_ci"] = list(_boot_ratio(g["sum"].to_numpy(), g["size"].to_numpy(), 2000, 0))
    daily = E.daily_series(t)
    cap = m["capital_usd"]
    rng = np.random.default_rng(0)
    dv = daily.to_numpy()
    bs = [dv[rng.integers(0, len(dv), len(dv))].sum() / cap * 100 for _ in range(2000)] if cap else []
    m["return_on_capital_ci_pct"] = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))] if bs else None
    dn = E.daily_series(ne)
    act = ne.groupby("date").pnl.sum()
    m["calendar_days"] = int(len(dn))
    m["profitable_calendar_days_share"] = float((dn > 0).mean())
    m["active_days"] = int(len(act))
    m["profitable_active_days_share"] = float((act > 0).mean())
    for name, f in (("fee_x2", lambda q: q.pnl_ps - q.fee), ("costs_x2", lambda q: q.pnl_ps - q.fee - 0.005)):
        q = t.assign(pnl_ps=f(t))
        q = q.assign(pnl=q.shares * q.pnl_ps)
        mm = E.metrics(q)
        m[name] = {k: mm[k] for k in KEYS_STRESS}
    return {k: (_f(v) if isinstance(v, (float, np.floating)) else v) for k, v in m.items()}


def tt3(P: pd.DataFrame, U: pd.DataFrame):
    Pc = tiers.add_causal_bucket(P)
    _, sh, _ = fasttier.walk_forward(Pc, bucket="bucket_c")  # the call v2.run makes first
    out = {"shadow_rows": int(len(sh)), "shadow_matches": int(sh.cond.nunique()) if len(sh) else 0}
    if sh.empty:
        out.update({p: {"n_trades": 0, "n_matches": 0, "verdict": "FAIL (no trades)", "labels": []}
                    for p in ("IS", "OOS")})
        out.update(ALL={"n_trades": 0}, verdict="FAIL (no trades)",
                   note="fast-tier shadow is empty: no wallet qualified, so v2 has no opportunity set (TT-D5)",
                   by_league=[], first_shadow_month=None)
        return out, pd.DataFrame()
    ends = U.set_index("cond").end
    tr, _ = v2.run(P, ends, causal=True)
    first_m = sorted(sh.month.astype(str).unique())[0]
    tr = tag(tr, U).assign(empty_train=lambda d: d.month == first_m)
    out["first_shadow_month"] = first_m
    out["trades_rows_incl_empty_training"] = int(len(tr))
    for p, flag in (("IS", False), ("OOS", True)):
        b = book_stats(tr[tr.oos == flag])
        if b["n_trades"] == 0:
            b["verdict"] = "FAIL (no trades)"
        else:
            b["verdict"] = "PASS" if b["per_share_ci_c"][0] > 0 else "FAIL"
        b["labels"] = ["underpowered"] if b["n_matches"] < 30 else []
        out[p] = b
    out["ALL"] = book_stats(tr)
    out["verdict"] = "PASS" if out["IS"]["verdict"] == "PASS" and out["OOS"]["verdict"] == "PASS" else "FAIL"
    t = tr[tr.month >= E.EVAL_START]
    if len(t):
        bg = E.by_group(t, "league")
        bg["n_excl_empty_training"] = bg.league.map(t[~t.empty_train].groupby("league").size()).fillna(0).astype(int)
        ci = {}
        for lg, g in t.groupby("league"):
            mm = E.metrics(g)
            ci[lg] = mm["per_share_ci_c"]
        bg["per_share_ci_c"] = bg.league.map(ci)
        out["by_league"] = json.loads(bg.to_json(orient="records"))
    return out, tr


# ------------------------------------------------------------------------------------------ TT4
def _dist(x) -> dict:
    x = pd.Series(x, dtype=float).dropna()
    if x.empty:
        return {"n": 0}
    return {"n": int(len(x)), "sum": float(x.sum()), "mean": float(x.mean()), "median": float(x.median()),
            "p90": float(x.quantile(0.9))}


def tape_depth(U: pd.DataFrame) -> pd.DataFrame:
    """Per market: in-play fills, minutes, print USD sizes and the _mid_series spread proxy."""
    rows = []
    for r in U.itertuples():
        t = load_tape(r.cond)
        if t is None:
            continue
        ip = in_play(t, r).reset_index(drop=True)
        mins = (r.end - r.start).total_seconds() / 60
        sp = np.array([])
        if len(ip):
            _, spread = tiers._mid_series(ip.timestamp.to_numpy(float), ip.p0.to_numpy(), ip.at_ask.to_numpy())
            sp = spread[np.isfinite(spread)]
        rows.append({"cond": r.cond, "league": r.league, "oos": bool(r.oos), "inplay_fills": int(len(ip)),
                     "window_min": mins, "sizes": ip.usd.to_numpy(), "spreads": sp})
    return pd.DataFrame(rows)


def book_snapshot(max_markets: int = 300) -> dict:
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = "courtside-research/0.1"

    def get(url, params):
        for k in range(5):
            try:
                r = s.get(url, params=params, timeout=30)
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(min(60, 2 ** k))
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException:
                time.sleep(min(60, 2 ** k))
        raise RuntimeError(f"GET failed {url}")

    now = pd.Timestamp.now(tz="UTC")
    mk = []
    for off in range(0, 5000, 100):
        evs = get("https://gamma-api.polymarket.com/events",
                  {"tag_id": 103767, "closed": "false", "limit": 100, "offset": off})
        for e in evs:
            for m in e.get("markets", []):
                if m.get("sportsMarketType") != "moneyline" or m.get("closed"):
                    continue
                toks = json.loads(m.get("clobTokenIds") or "[]")
                st = pd.to_datetime(e.get("startTime"), utc=True, errors="coerce")
                if len(toks) == 2 and pd.notna(st):
                    mk.append({"cond": m.get("conditionId"), "tok0": toks[0], "series": e.get("seriesSlug"),
                               "start": st})
        if len(evs) < 100:
            break
    if not mk:
        return {"taken_utc": now.isoformat(), "open_moneylines": 0}
    M = pd.DataFrame(mk).drop_duplicates("cond")
    M["dist"] = (M.start - now).abs()
    M = M.sort_values("dist").head(max_markets)
    rows = []
    for r in M.itertuples():
        try:
            b = get("https://clob.polymarket.com/book", {"token_id": r.tok0})
        except Exception:
            continue
        bids = [(float(x["price"]), float(x["size"])) for x in b.get("bids", [])]
        asks = [(float(x["price"]), float(x["size"])) for x in b.get("asks", [])]
        row = {"cond": r.cond, "series": r.series, "in_play": bool(r.start <= now), "two_sided": bool(bids and asks)}
        if bids and asks:
            bb, ba = max(p for p, _ in bids), min(p for p, _ in asks)
            mid = (bb + ba) / 2
            row["spread_c"] = (ba - bb) * 100
            for w in (0.01, 0.02):
                row[f"depth_{int(w * 100)}c_usd"] = (sum(p * q for p, q in bids if p >= mid - w - 1e-9)
                                                    + sum(p * q for p, q in asks if p <= mid + w + 1e-9))
        rows.append(row)
        time.sleep(0.1)
    B = pd.DataFrame(rows)
    B["league"] = np.select([B.series.fillna("").str.startswith("wtt"), B.series.fillna("").str.startswith("setka")],
                            ["WTT", "Setka"], "other")
    out = {"taken_utc": now.isoformat(timespec="seconds"), "open_moneylines_listed": int(len(M)),
           "books_read": int(len(B)), "two_sided": int(B.two_sided.sum()), "in_play_books": int(B.in_play.sum()),
           "label": "one snapshot of public clob /book, not history"}
    for (name, g) in [("all", B)] + [(f"league={lg}", g) for lg, g in B.groupby("league")] + \
            [(f"in_play={ip}", g) for ip, g in B.groupby("in_play")]:
        two = g[g.two_sided]
        out[name] = {"books": int(len(g)), "two_sided": int(len(two)),
                     "spread_c": _dist(two.get("spread_c")), "depth_1c_usd": _dist(two.get("depth_1c_usd")),
                     "depth_2c_usd": _dist(two.get("depth_2c_usd"))}
    return out


def tt4(U, Pc, L, tr, tt2_months, book: bool, book_n: int = 300) -> dict:
    mv = pd.DataFrame([_market_volume(r) for r in U[["cond", "start", "end"]].to_dict("records")])
    m = U[["cond", "league", "oos", "volume"]].merge(mv, on="cond")
    m["period"] = np.where(m.oos, "OOS", "IS")
    vol = {}
    for key, g in [("ALL", m)] + [(lg, g) for lg, g in m.groupby("league")] + \
            [(f"{lg}/{p}", g) for (lg, p), g in m.groupby(["league", "period"])] + \
            [(f"ALL/{p}", g) for p, g in m.groupby("period")]:
        vol[key] = {"markets": int(len(g)), "listed_volume_shares": _dist(g.volume), "tape_usd": _dist(g.usd),
                    "prestart_usd": _dist(g.pre_usd), "inplay_window_usd": _dist(g.inplay_usd)}
    D = tape_depth(U)
    depth = {}
    for key, g in [("ALL", D)] + [(lg, g) for lg, g in D.groupby("league")] + \
            [(f"ALL/{'OOS' if o else 'IS'}", g) for o, g in D.groupby("oos")]:
        sizes = np.concatenate(g.sizes.to_numpy()) if len(g) else np.array([])
        sps = np.concatenate(g.spreads.to_numpy()) if len(g) else np.array([])
        w = g[g.window_min > 0]
        per_mkt_sp = [np.median(x) for x in g.spreads if len(x)]
        depth[key] = {"markets": int(len(g)), "inplay_fills": int(g.inplay_fills.sum()),
                      "inplay_print_usd": _dist(sizes),
                      "inplay_prints_per_min": _dist(w.inplay_fills / w.window_min),
                      "spread_proxy_c_pooled_median": _f(np.median(sps) * 100) if len(sps) else None,
                      "spread_proxy_c_median_of_market_medians": _f(np.median(per_mkt_sp) * 100) if per_mkt_sp else None,
                      "spread_proxy_fills": int(len(sps)), "spread_proxy_markets": int(len(per_mkt_sp))}
    # bucket-based (the matches with prints)
    jumps = {}
    for c, g in Pc.sort_values(["cond", "ts"], kind="stable").groupby("cond"):
        jumps[c] = len(tiers.jump_onsets(g.ts.to_numpy(float), g.p.to_numpy(), g.usd.to_numpy()))
    Pc = tag(Pc, U)
    b03 = {}
    for key, g in [("ALL", Pc)] + [(lg, g) for lg, g in Pc.groupby("league")]:
        nj = sum(jumps[c] for c in g.cond.unique())
        u03 = float(g[g.bucket_c == "0-3s"].usd.sum())
        b03[key] = {"matches": int(g.cond.nunique()), "detections": int(nj), "usd_0_3s": u03,
                    "usd_0_3s_per_detection": u03 / nj if nj else None,
                    "inplay_spread_proxy_c_median": _f(g.spread.median() * 100)}
    F = L[L.fast]
    fdays = pd.to_datetime(F.ts, unit="s", utc=True).dt.floor("D")
    fast_vol = {"usd_total": float(F.usd.sum()), "prints": int(len(F)), "matches": int(F.cond.nunique()),
                "usd_per_match_with_fast_prints": float(F.usd.sum() / F.cond.nunique()) if len(F) else 0.0,
                "usd_per_evaluable_match": float(F.usd.sum() / Pc.cond.nunique()) if Pc.cond.nunique() else None,
                "active_days": int(fdays.nunique()),
                "usd_per_active_day": float(F.usd.sum() / fdays.nunique()) if len(F) else 0.0,
                "usd_by_evaluated_month": {mo: float(F[F.month.astype(str) == mo].usd.sum()) for mo in tt2_months}}
    # what v2 could deploy
    t = tr[(tr.month >= E.EVAL_START)] if len(tr) else tr
    ne = t[~t.empty_train] if len(t) else t
    if len(ne):
        cal = E.daily_series(ne)
        usd_cal = float(ne.usd_in.sum() / len(cal))
        dep = {"trades": int(len(ne)), "matches": int(ne.cond.nunique()),
               "usd_in_total": float(t.usd_in.sum()),
               "usd_in_per_match": _dist(ne.groupby("cond").usd_in.sum()),
               "usd_in_per_active_day": _dist(ne.groupby("date").usd_in.sum()),
               "calendar_days_first_to_last_trade": int(len(cal)), "usd_in_per_calendar_day": usd_cal,
               "peak_locked_usd": E.peak_locked(t), "mean_ticket_usd": float(ne.usd_in.mean()),
               "pnl_usd_per_calendar_day": float(t.pnl.sum() / len(cal)),
               "first_trade_day": str(cal.index.min().date()), "last_trade_day": str(cal.index.max().date())}
        ctx_months = sorted(ne.month.unique())
    else:
        usd_cal = 0.0
        dep = {"trades": 0, "usd_in_per_calendar_day": 0.0, "note": "v2 placed no trade on table tennis"}
        ctx_months = list(tt2_months)
    T = pd.read_parquet("data/v2_trades_is_oos.parquet", columns=["cond", "month", "usd_in", "pnl", "date"])
    T = T[T.month.isin(ctx_months)]
    ndays = int(sum(pd.Period(mo, "M").days_in_month for mo in ctx_months))
    tennis = {"months": ctx_months, "calendar_days": ndays, "trades": int(len(T)), "matches": int(T.cond.nunique()),
              "usd_in_per_calendar_day": float(T.usd_in.sum() / ndays) if ndays else None,
              "pnl_usd_per_calendar_day": float(T.pnl.sum() / ndays) if ndays else None,
              "source": "data/v2_trades_is_oos.parquet (tennis v2 causal; context only, not compared)"}
    cap = {"rule": f"v2 deployed USD per calendar day < ${CAPACITY_USD_PER_DAY:,} -> 'capacity is negligible'",
           "usd_in_per_calendar_day": usd_cal,
           "statement": "capacity is negligible" if usd_cal < CAPACITY_USD_PER_DAY else "capacity is not negligible"}
    out = {"volume_per_match": vol, "depth_from_tapes": depth, "bucket_0_3s_from_prints": b03,
           "fast_tier_volume": fast_vol, "v2_deploy": dep, "tennis_v2_context": tennis, "capacity": cap}
    if book:
        try:
            out["book_snapshot"] = book_snapshot(book_n)
        except Exception as err:  # optional item; never stops the run
            out["book_snapshot"] = {"error": repr(err)}
    return out


# ---------------------------------------------------------------------------------------- figures
def fig_fasttier(tt2r: dict, path: Path, title_note: str = ""):
    import matplotlib.pyplot as plt
    from src.report import BLUE, INK2, ORANGE
    mo = tt2r["monthly"]
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    x = np.arange(len(mo))
    for off, key, col, lab in ((-0.12, "fast_net30_c", BLUE, "Fast-tier wallets (qualified on earlier months)"),
                               (0.12, "others_net30_c", ORANGE, "All other takers")):
        pts = [(i + off, r[key]) for i, r in enumerate(mo) if r[key] is not None]
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1][0] for p in pts]
            err = [[p[1][0] - p[1][1] for p in pts], [p[1][2] - p[1][0] for p in pts]]
            ax.errorbar(xs, ys, yerr=err, fmt="o", ms=5, color=col, ecolor=col, elinewidth=1.2, capsize=0, label=lab)
        else:
            ax.plot([], [], "o", color=col, label=lab.split(" (")[0] + ": none")
    ax.axhline(0, color=INK2, lw=0.8)
    ticks = [f"{r['month']}\n{r['n_qualified_wallets']} qual. wallets\n{r['others_prints']} other prints" for r in mo]
    ax.set_xticks(x, ticks, fontsize=7)
    if not any(r["fast_net30_c"] for r in mo):
        ax.text(0.5, 0.92, "No wallet qualified as fast tier in any month", transform=ax.transAxes,
                ha="center", va="top", color=INK2, fontsize=8)
    ax.set_xlim(-0.6, len(mo) - 0.4)
    ax.set_ylabel("Net 30 s markout, ¢/share")
    ax.set_title("Table tennis: 0-3 s after a detected jump, by month" + title_note)
    ax.legend(loc="lower left", fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def fig_equity(tt3r: dict, tr: pd.DataFrame, path: Path):
    import matplotlib.pyplot as plt
    from src.report import BLUE, INK2, ORANGE
    fig, axes = plt.subplots(1, 2, figsize=(6.8, 3.0), sharey=False)
    for ax, (p, flag, col) in zip(axes, (("IS", False, BLUE), ("OOS", True, ORANGE))):
        r = tt3r.get(p, {})
        t = tr[(tr.oos == flag) & (tr.month >= E.EVAL_START)] if len(tr) else tr
        if len(t) and r.get("n_trades", 0) > 0:
            d = E.daily_series(t).cumsum()
            ax.plot(d.index.tz_localize(None), d.values, color=col, lw=2)
            ax.axhline(0, color=INK2, lw=0.8)
            ax.set_title(f"{p}: \\${r['total_pnl_usd']:,.0f}, {r['return_on_capital_pct']:.1f}% return on "
                         f"\\${r['capital_usd']:,.0f} capital", fontsize=8)
            ax.tick_params(axis="x", labelrotation=30, labelsize=7)
        else:
            ax.text(0.5, 0.5, f"{p}: no v2 trades\n({r.get('verdict', 'FAIL (no trades)')})", ha="center",
                    va="center", transform=ax.transAxes, color=INK2, fontsize=9)
            ax.set_title(f"{p}: return on capital n/a", fontsize=8)
            ax.set_xticks([]); ax.set_yticks([])
        ax.set_ylabel("Cumulative P&L, \\$" if p == "IS" else "")
    fig.suptitle("Table tennis: frozen v2 rule (G_50pct_net100, causal), blind", x=0.02, ha="left",
                 fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


# ------------------------------------------------------------------------------------------- main
def analyse(U, P, book: bool, book_n: int = 300):
    P = tag(P, U)
    r1 = tt1(P, U)
    r2, L, Pc = tt2(P.drop(columns=["league", "oos"]).pipe(tag, U))
    r3, tr = tt3(P.drop(columns=["league", "oos"]), U)
    r4 = tt4(U, Pc.drop(columns=["league", "oos"]), L, tr, r2["evaluated_months"], book, book_n)
    counts = {"utt_markets": int(len(U)), "utt_is": int((~U.oos).sum()), "utt_oos": int(U.oos.sum()),
              "evaluable_matches": int(P.cond.nunique()), "print_rows": int(len(P)),
              "evaluable_by_league_period": {f"{lg}/{'OOS' if o else 'IS'}": int(g.cond.nunique())
                                             for (lg, o), g in P.groupby(["league", "oos"])}}
    return {"counts": counts, "TT1": r1, "TT2": r2, "TT3": r3, "TT4": r4}, L, tr


def git_ref() -> str:
    h = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "scripts/tt_analyze.py", "research/tt/DEVIATIONS.md"],
                           capture_output=True, text=True).stdout.strip()
    return h + ("+dirty" if dirty else "")


def dry_inputs(n: int):
    """Tennis U1 IS matches (already studied) dressed as a TT universe, to exercise every code path."""
    from src.tape import universe
    u = universe()
    u = u[~u.oos & (u.start >= "2025-12-01") & (u.start < "2026-05-01")]
    p = pd.read_parquet("data/is_prints.parquet")
    keep = sorted(set(u.cond) & set(p.cond))
    rng = np.random.default_rng(1)
    keep = set(rng.choice(keep, size=min(n, len(keep)), replace=False))
    u = u[u.cond.isin(keep)].sort_values("start", kind="stable").reset_index(drop=True)
    u["oos"] = u.start >= u.start.iloc[int(0.8 * len(u))]
    u["league"] = u.series
    return u, p[p.cond.isin(keep)].reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", metavar="OUTDIR", help="plumbing check on tennis data; not logged")
    ap.add_argument("--dry-n", type=int, default=600)
    ap.add_argument("--rerun", action="store_true", help="allow a logged re-run")
    ap.add_argument("--no-book", action="store_true")
    a = ap.parse_args()
    if a.dry:
        out = Path(a.dry)
        out.mkdir(parents=True, exist_ok=True)
        U, P = dry_inputs(a.dry_n)
        res, L, tr = analyse(U, P, book=not a.no_book, book_n=3)
        (out / "results.json").write_text(json.dumps(res, indent=2, default=str))
        fig_fasttier(res["TT2"], out / "fig_fasttier.png", " (DRY: tennis)")
        fig_equity(res["TT3"], tr, out / "fig_v2_equity.png")
        print("dry run OK:", res["counts"], res["TT1"]["verdict_detail"], res["TT2"]["verdict"], res["TT3"]["verdict"])
        return
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "results.json").exists() and not a.rerun:
        sys.exit("results/tt/results.json exists: TT1-TT4 were already evaluated (use --rerun; it is logged)")
    ref = git_ref()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    what = "table tennis TT1-TT4 evaluated (" + ("RE-RUN" if a.rerun else "first run") + ")"
    with LOG_TRACK.open("a") as f:
        f.write(f"{now} {what}\n")
    with LOG_TT.open("a") as f:
        f.write(f"{now} {what} commit={ref}\n")
    U, P = load()
    res, L, tr = analyse(U, P, book=not a.no_book)
    Us, Ps = load(sens=True)
    sres, _, _ = analyse(Us, Ps, book=False)
    res["sensitivity_with_unlisted"] = {
        "note": "UTT + the 96 zero-listed markets that traded (TT-D8); verdicts above are UTT only",
        "counts": sres["counts"],
        "TT1": {"verdict": sres["TT1"]["verdict"], "verdict_detail": sres["TT1"]["verdict_detail"],
                "inplay_judged_bins": sres["TT1"]["inplay"]["judged_bins"],
                "closing_judged_bins": sres["TT1"]["closing"].get("judged_bins"),
                "closing_failing_judged_bins": sres["TT1"]["closing"].get("failing_judged_bins")},
        "TT2": {k: sres["TT2"][k] for k in ("verdict", "labels", "qualified_wallets_by_month", "fast_net30_c",
                                            "others_net30_c", "gap_fast_minus_others_c", "n_fast_matches")},
        "TT3": {k: sres["TT3"].get(k) for k in ("verdict", "shadow_rows")} |
               {p: {k: sres["TT3"][p].get(k) for k in ("n_trades", "n_matches", "per_share_c", "per_share_ci_c",
                                                        "total_pnl_usd", "verdict")} for p in ("IS", "OOS")},
        "TT4_v2_usd_in_per_calendar_day": sres["TT4"]["capacity"]["usd_in_per_calendar_day"],
    }
    res["run"] = {"utc": now, "commit": ref, "log": what,
                  "hiper_gator": "not used; everything ran locally on the laptop"}
    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=str))
    if len(tr):
        tr.to_parquet("data/tt/v2_trades.parquet")
    fig_fasttier(res["TT2"], OUT / "fig_fasttier.png")
    fig_equity(res["TT3"], tr, OUT / "fig_v2_equity.png")
    print(json.dumps({"TT1": res["TT1"]["verdict"] + " | " + res["TT1"]["verdict_detail"],
                      "TT2": res["TT2"]["verdict"] + " " + str(res["TT2"]["labels"]),
                      "TT3": res["TT3"]["verdict"], "TT4": res["TT4"]["capacity"]["statement"]}, indent=1))


if __name__ == "__main__":
    main()
