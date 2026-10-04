"""COURTSIDE v2: the frozen rule in HYPOTHESIS_V2.md, runnable on any period.

Pipeline (each month m only ever learns from months < m):
  prints (all periods) -> walk-forward fast-tier shadow (src.fasttier) -> decision-time features
  -> sizing policy G_50pct_net100 (research/v2/sizing/engine.py, used unchanged) -> trades.

The feature builder is the one in research/v2/sizing/features.py, made period-agnostic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src import fasttier

ROOT = Path(__file__).resolve().parents[1]
# The verified sizing engine, loaded by path under a private name: the top-level `engine/` package
# (the live paper-trading engine) would otherwise shadow it as `engine`.
_spec = importlib.util.spec_from_file_location("courtside_sizing_engine", ROOT / "research/v2/sizing/engine.py")
E = importlib.util.module_from_spec(_spec)
sys.modules["courtside_sizing_engine"] = E
_spec.loader.exec_module(E)

POLICY = E.Policy("G_50pct_net100", sizing="risk_parity", deploy_frac=0.5, zone="0.05-0.95",
                  wallet="filter", net_cap=100, family="G")


def build_features(sh: pd.DataFrame, prints: pd.DataFrame, ends: pd.Series) -> pd.DataFrame:
    """Decision-time features for shadow rows; only earlier-second prints are used (see features.py)."""
    sh = sh.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    pr = prints[prints.cond.isin(set(sh.cond))][["cond", "ts", "p", "dir", "usd", "wallet"]]
    pr = pr.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    feats = {k: np.full(len(sh), np.nan) for k in ("ref", "last", "bid0", "ask0", "n_prior3", "usd_prior3", "clip_k")}
    groups = {c: g for c, g in pr.groupby("cond", sort=False)}
    for c, g in sh.groupby("cond", sort=False):
        P = groups[c]
        ts, p, usd, d, wal = P.ts.to_numpy(), P.p.to_numpy(), P.usd.to_numpy(), P.dir.to_numpy(), P.wallet.to_numpy()
        pv = np.concatenate([[0.0], np.cumsum(p * usd)]); vv = np.concatenate([[0.0], np.cumsum(usd)])
        idx = np.arange(len(ts))
        ask_i = np.maximum.accumulate(np.where(d > 0, idx, -1))
        bid_i = np.maximum.accumulate(np.where(d < 0, idx, -1))
        st, rows = g.ts.to_numpy(), g.index.to_numpy()
        a = np.searchsorted(ts, st - 63, "left"); b = np.searchsorted(ts, st - 3, "left")
        w = vv[b] - vv[a]
        feats["ref"][rows] = np.where(w > 0, (pv[b] - pv[a]) / np.where(w > 0, w, 1), np.nan)
        e = np.searchsorted(ts, st, "left")
        l10 = np.searchsorted(ts, st - 10, "left")
        has = (e - 1 >= l10) & (e > 0)
        feats["last"][rows] = np.where(has, p[np.maximum(e - 1, 0)], np.nan)
        for side_i, key in ((ask_i, "ask0"), (bid_i, "bid0")):
            j = np.where(e > 0, side_i[np.maximum(e - 1, 0)], -1)
            ok = (j >= 0) & (st - ts[np.maximum(j, 0)] <= 30)
            feats[key][rows] = np.where(ok, p[np.maximum(j, 0)], np.nan)
        s3 = np.searchsorted(ts, st - 3, "left")
        feats["n_prior3"][rows] = e - s3
        feats["usd_prior3"][rows] = vv[e] - vv[s3]
        gw = g.wallet.to_numpy()
        feats["clip_k"][rows] = [np.count_nonzero(wal[s3[k]:e[k]] == gw[k]) if e[k] > s3[k] else 0 for k in range(len(st))]
    for k, v in feats.items():
        sh[k] = v
    sh["q"] = np.where(sh.dir > 0, sh.p, 1 - sh.p)
    sh["fee5"] = 0.05 * sh.q * (1 - sh.q)
    sh["pre_move"] = (sh["last"] - sh.ref) * sh.dir
    sh["fill_move"] = (sh.p - sh.ref) * sh.dir
    sh["spread0"] = sh.ask0 - sh.bid0
    sh["end_ts"] = sh.cond.map(ends).map(lambda x: x.timestamp() if pd.notna(x) else np.nan)
    sh["end_ts"] = np.maximum(sh.end_ts.fillna(sh.ts + 4 * 3600), sh.ts)
    sh["mo_res_all"] = sh.dir * (sh.res - sh.p)
    sh["date"] = pd.to_datetime(sh.ts, unit="s", utc=True).dt.floor("D")
    sh["month"] = sh.month.astype(str)
    sh["regime"] = sh.delay.astype(int).astype(str) + "s/" + (sh.fee_rate * 100).round().astype(int).astype(str) + "%"
    return sh.sort_values("ts", kind="stable").reset_index(drop=True)


def prepare(f: pd.DataFrame) -> pd.DataFrame:
    """Same column prep as engine.load(), on an in-memory feature table."""
    f = f[f.month >= "2025-12"].sort_values("ts", kind="stable").reset_index(drop=True)
    f["rate"] = f.fee_rate.astype(float)
    f["gross_res"] = f.mo_res_all
    f["gross30"] = f.mo30
    f["qb"] = np.clip(np.searchsorted(E.QB, f.q.to_numpy(), "right") - 1, 0, len(E.QB) - 2)
    f["lock_end"] = np.minimum(f.end_ts, f.ts + E.MAX_LOCK_S)
    f["their_shares"] = f.usd / f.q
    f["exit_q"] = np.clip(f.q + f.mo30.fillna(0), 0.001, 0.999)
    return f


def _detections(ts, p, usd, J=0.04, short_w=10, long_w=60):
    """src.tiers.jump_onsets line for line (that file is frozen by sha256 in pre-registrations, so it is not
    edited), returning (detection second, direction, tape index of the trigger print) per detection."""
    pv, v = np.cumsum(p * usd), np.cumsum(usd)
    on, last = [], -1e18
    for i in range(len(ts)):
        now = ts[i]
        if now - last < long_w:
            continue
        a = np.searchsorted(ts, now - short_w, "left")
        b = np.searchsorted(ts, now - short_w - long_w, "left")
        if a <= b or a > i:
            continue
        s1 = pv[i] - (pv[a - 1] if a else 0); w1 = v[i] - (v[a - 1] if a else 0)
        s2 = (pv[a - 1] if a else 0) - (pv[b - 1] if b else 0); w2 = (v[a - 1] if a else 0) - (v[b - 1] if b else 0)
        if w1 <= 0 or w2 <= 0:
            continue
        d = s1 / w1 - s2 / w2
        if abs(d) >= J:
            last = now
            on.append((now, np.sign(d), i))
    return on


def strict_causal_bucket(prints: pd.DataFrame, order_col: str | None = None) -> pd.DataFrame:
    """Executable detection labels: a print is measured from a jump detection only if it is known to come
    AFTER the print that fired the detector (the trigger print).

    src.tiers.add_causal_bucket (the frozen rule T3e) measures every print from the latest detection whose
    second is <= the print's second, so the trigger print and prints that came before it within that second
    get since_det = 0 and land in 0-3 s. Here:
      * different seconds: ts > detection second (block timestamps order whole seconds reliably);
      * same second: only if `order_col` names a reliable within-second sequence (e.g. a log index) and the
        print's sequence is greater than the trigger print's. Without one (the default: the public trade tapes
        carry no block, transaction or log index) the whole detection second is excluded.
    Adds since_det_s, with_jump_det_s, det_ts_s (the detection second the label is measured from; NaN if none)
    and bucket_cs. Buckets keep their widths, closed on the right: 0-3s is 0 < since <= 3 (whole seconds
    1, 2, 3; the verifiers' T3f definition in research/v2/verify_v2/leakage_check.py), plus since = 0 for prints
    after the trigger in a reliable within-second order. The detector is the frozen one, run on each match's
    own print table (the in-play tape), as in add_causal_bucket."""
    from src.tiers import BUCKETS, LABELS
    keys = ["cond", "ts"] + ([order_col] if order_col is not None else [])
    out = []
    for c, g in prints.sort_values(keys, kind="stable").groupby("cond", sort=False):
        ts, p, usd = g.ts.to_numpy(float), g.p.to_numpy(), g.usd.to_numpy()
        n = len(ts)
        since, wj, dts = np.full(n, -1.0), np.zeros(n), np.full(n, np.nan)
        on = _detections(ts, p, usd)
        if on:
            dt_ = np.array([o[0] for o in on])
            dd = np.array([o[1] for o in on])
            k = np.searchsorted(dt_, ts, "left") - 1          # latest detection in an EARLIER second
            if order_col is not None:                         # same second, after the trigger in a reliable order
                seq = g[order_col].to_numpy()
                trig_seq = seq[np.array([o[2] for o in on])]
                k2 = np.searchsorted(dt_, ts, "right") - 1    # latest detection at or before this second
                kk2 = np.maximum(k2, 0)
                same = (k2 >= 0) & (dt_[kk2] == ts) & (seq > trig_seq[kk2])
                k = np.where(same, k2, k)
            ok = k >= 0
            kk = np.maximum(k, 0)
            since = np.where(ok, ts - dt_[kk], -1.0)
            wj = np.where(ok, g.dir.to_numpy() * dd[kk], 0.0)
            dts = np.where(ok, dt_[kk], np.nan)
        out.append(pd.DataFrame({"since_det_s": since, "with_jump_det_s": wj, "det_ts_s": dts}, index=g.index))
    prints = prints.join(pd.concat(out))
    edges = [-1e9, -0.5] + [b[0] for b in BUCKETS[2:]] + [1e9]   # (-inf, -0.5] = no detection known yet
    prints["bucket_cs"] = pd.cut(prints.since_det_s, edges, labels=LABELS, right=True)
    return prints


LOCK_S = 4 * 3600  # ex-ante capital lock per position (a scheduled best-of-3 rarely runs longer)


def run(prints: pd.DataFrame, ends: pd.Series, measure: str = "res", causal: bool = True,
        strict: bool = False, order_col: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """v2 trades over every month present in `prints` (walk-forward throughout).

    causal=True, strict=False (the frozen rule T3e after D9, reproduced bit for bit): the 0-3 s window is
    measured from the jump DETECTION second. Every print stamped in that second, including the print that
    fires the detector and prints before it, is in the window, so the trades sit at the fast tier's own
    fills: an observational event study, not an executable book.
    causal=True, strict=True (executable timing): only prints known to come after the trigger print are in
    the window (strict_causal_bucket: the whole detection second is excluded unless `order_col` gives a
    reliable within-second order); qualification, wallet filter and book are re-derived on those labels.
    Price the trades with copier_reprice() for what a copier could get.
    causal=False reproduces the original onset-labelled v2 (kept for comparison)."""
    bucket = "bucket"
    if strict and not causal:
        raise ValueError("strict labels are measured from detection: use causal=True")
    if causal:
        from src.tiers import add_causal_bucket
        if strict:
            if "bucket_cs" not in prints:
                prints = strict_causal_bucket(prints, order_col=order_col)
            bucket = "bucket_cs"
        else:
            if "bucket_c" not in prints:
                prints = add_causal_bucket(prints)
            bucket = "bucket_c"
    wf, sh, _ = fasttier.walk_forward(prints, bucket=bucket)
    f = prepare(build_features(sh, prints, ends))
    if causal:  # ex-ante capital lock instead of the realised match end (affects capital/drawdown only)
        f["lock_end"] = f.ts + LOCK_S
    p03 = prints[prints[bucket] == "0-3s"][["wallet", "ts", "mo30"]].copy()
    p03["month"] = pd.to_datetime(p03.ts, unit="s").dt.to_period("M").astype(str)
    E._WCACHE.clear()
    tr = E.simulate(f, POLICY, measure, "actual", p03[["wallet", "month", "mo30"]])
    return tr, wf


# ------------------------------------------------------------------------------------- executable copier
# A copier cannot trade at the fast wallet's fill. It learns of a qualifying fast print from the chain (the
# only public source that names the wallet) at the print's block time ts_f, and only acts on prints known to
# come after the detection's trigger print (strict labels). Its taker order then crosses the network leg N,
# waits the market's taker hold D (the trade's own `delay`: 3 s before May 2026, 1 s after) and is matched at
# real time ts_f + N + D. Block times run L behind the CLOB match (block lag), so the book it meets is the
# tape's state at  tau = max(ts_f, detection second) + N + D + L  (tape time). Its fill price is the first
# same-side print at or after tau, or the quote state at tau when there is none; no print at or before the
# fast print is ever used as its fill price, except by the labelled optimistic bound, which may use the fast
# print itself.
COPIER_RULES = {
    "central": {"lag": "median", "price": "next_same",
                "what": "block lag median + network leg; first same-side print at/after tau "
                        "(fallback: mid + proxy half-spread at the first print at/after tau)"},
    "harsh": {"lag": "p90", "price": "next_same",
              "what": "block lag p90 + network leg; same price rule as central"},
    "optimistic": {"lag": "median", "price": "prev_same",
                   "what": "block lag median + network leg; last same-side print at/before tau, which can be "
                           "the fast wallet's own fill (upper bound, not attainable in general)"},
}
SAME_SIDE_MAX_S = 30.0


def mid_path(ts: np.ndarray, p: np.ndarray, at_ask: np.ndarray, stale: float = 30.0):
    """Vectorised src.tiers._mid_series: mean of the latest bid-side and ask-side prints <= stale s old."""
    idx = np.arange(len(ts))
    la = np.maximum.accumulate(np.where(at_ask, idx, -1))
    lb = np.maximum.accumulate(np.where(~at_ask, idx, -1))
    ask = np.where((la >= 0) & (ts - ts[np.maximum(la, 0)] <= stale), p[np.maximum(la, 0)], np.nan)
    bid = np.where((lb >= 0) & (ts - ts[np.maximum(lb, 0)] <= stale), p[np.maximum(lb, 0)], np.nan)
    mid = np.where(np.isfinite(bid) & np.isfinite(ask) & (ask >= bid), (bid + ask) / 2, p)
    return mid, ask - bid


def copier_arrival(ts_f, det_ts, delay, lag_s: float, net_s: float) -> np.ndarray:
    """Tape time at which the copier's taker order meets the book (see the block comment above)."""
    known = np.fmax(np.asarray(ts_f, float), np.asarray(det_ts, float))  # NaN detection -> the print itself
    return known + net_s + np.asarray(delay, float) + lag_s


def copier_fill(ts, p, at_ask, ts_f, d, det_ts, delay, lag_s: float, net_s: float, price: str) -> dict:
    """Copier entry prices (outcome-0 scale) on one match's in-play tape (ts sorted, whole seconds).

    ts_f, d, det_ts, delay: the fast prints being copied (block time, direction on outcome 0, detection
    second the label is measured from, taker hold). Returns c0, tau, fill_ts (NaN when the fallback quote is
    used), same (a same-side print was used) and beyond (tau is past the end of the tape)."""
    ts, p, at_ask = np.asarray(ts, float), np.asarray(p, float), np.asarray(at_ask, bool)
    ts_f, d = np.asarray(ts_f, float), np.asarray(d, float)
    n, m = len(ts), len(ts_f)
    tau = copier_arrival(ts_f, det_ts, delay, lag_s, net_s)
    if n == 0:
        return {"c0": np.full(m, np.nan), "tau": tau, "fill_ts": np.full(m, np.nan),
                "same": np.zeros(m, bool), "beyond": np.ones(m, bool)}
    mid, spr = mid_path(ts, p, at_ask)
    j = np.searchsorted(ts, tau, "left")
    beyond = j >= n
    j = np.minimum(j, n - 1)                                  # bounded lookup; beyond rows are rejected below
    hs = np.where(np.isfinite(spr[j]) & (spr[j] > 0), np.clip(spr[j], 0.01, 0.10), 0.01) / 2
    c0 = mid[j] + d * hs
    fill_ts = np.full(m, np.nan)
    same = np.zeros(m, bool)
    for side, sel in ((np.flatnonzero(at_ask), d > 0), (np.flatnonzero(~at_ask), d < 0)):
        if not sel.any() or len(side) == 0:
            continue
        w = np.flatnonzero(sel)
        if price == "next_same":
            k = np.searchsorted(ts[side], tau[w], "left")
            ok = k < len(side)
            kk = side[np.minimum(k, len(side) - 1)]
            ok &= (ts[kk] - tau[w]) <= SAME_SIDE_MAX_S
        elif price == "prev_same":
            k = np.searchsorted(ts[side], tau[w], "right") - 1
            ok = k >= 0
            kk = side[np.maximum(k, 0)]
        else:
            raise ValueError(price)
        c0[w[ok]] = p[kk[ok]]
        fill_ts[w[ok]] = ts[kk[ok]]
        same[w[ok]] = True
    # No recorded state supports an execution after the tape ends. Keeping the last price would create
    # a synthetic fill (including for the optimistic bound). Retain the attempted order for coverage,
    # but provide no price or fill time and exclude it from the executable book.
    c0 = np.where(beyond, np.nan, np.clip(c0, 0.001, 0.999))
    fill_ts[beyond] = np.nan
    same[beyond] = False
    return {"c0": c0, "tau": tau, "fill_ts": fill_ts, "same": same, "beyond": beyond}


def copier_reprice(trades: pd.DataFrame, u: pd.DataFrame, lat: dict, tape_loader=None) -> pd.DataFrame:
    """Copier prices for v2 trades under each COPIER_RULES rule. `u` is the universe indexed by cond;
    lat = {"median": s, "p90": s, "net_s": s}. Needs the strict detection second (det_ts_s) on the trades."""
    from src.tape import in_play, load_tape
    tape_loader = tape_loader or (lambda c: load_tape(c))
    out = {f"{k}_{r}": np.full(len(trades), np.nan) for r in COPIER_RULES for k in ("c0", "tau", "fill_ts")}
    out.update({f"{k}_{r}": np.zeros(len(trades), bool) for r in COPIER_RULES for k in ("same", "beyond")})
    pos = pd.Series(np.arange(len(trades)), index=trades.index)
    det = trades["det_ts_s"] if "det_ts_s" in trades else pd.Series(np.nan, index=trades.index)
    for cond, g in trades.groupby("cond", sort=False):
        tp = tape_loader(cond)
        if tp is None:
            raise FileNotFoundError(f"no tape for {cond}")
        tp = in_play(tp, u.loc[cond]).reset_index(drop=True)
        rows = pos.loc[g.index].to_numpy()
        for r, spec in COPIER_RULES.items():
            f = copier_fill(tp.timestamp.to_numpy(float), tp.p0.to_numpy(float), tp.at_ask.to_numpy(bool),
                            g.ts.to_numpy(float), g.dir.to_numpy(float), det.loc[g.index].to_numpy(float),
                            g.delay.to_numpy(float), lat[spec["lag"]], lat["net_s"], spec["price"])
            for k in ("c0", "tau", "fill_ts", "same", "beyond"):
                out[f"{k}_{r}"][rows] = f[k]
    return pd.DataFrame(out, index=trades.index)


def copier_book(tr: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Supported fills, re-priced at the copier's entry: per share = dir (res - c) - fee(c).

    Arrival beyond the tape and missing prices cannot contribute P&L, fees, capital or turnover.
    The caller reports these rejected attempts separately instead of silently treating them as fills.
    """
    validity = f"beyond_{rule}"
    if validity not in tr:
        raise ValueError(f"missing copier execution coverage: {validity}")
    tr = tr.loc[tr[validity].eq(False) & np.isfinite(tr[f"c0_{rule}"])].copy()
    c0 = tr[f"c0_{rule}"].to_numpy(float)
    q = np.where(tr.dir > 0, c0, 1 - c0)
    ps = tr.dir.to_numpy() * (tr.res.to_numpy() - c0) - tr.rate.to_numpy() * q * (1 - q)
    ps = np.where(np.isfinite(tr.res.to_numpy()), ps, 0.0)   # the book's convention (engine.simulate nan_to_num)
    return tr.assign(q=q, pnl_ps=ps, usd_in=tr.shares * q, pnl=tr.shares * ps)


def table1_metrics(tr: pd.DataFrame) -> dict:
    """engine.metrics plus the Table-1 extras, on a book with shares, q, rate, pnl_ps (evaluation months only)."""
    tr = tr.assign(usd_in=tr.shares * tr.q, pnl=tr.shares * tr.pnl_ps)
    m = E.metrics(tr)
    if not m.get("n_trades"):
        return {"n_trades": 0}
    ev = tr[tr.month >= E.EVAL_START]
    daily = E.daily_series(ev)
    cap = m["capital_usd"]
    fee = ev.rate * ev.q * (1 - ev.q)
    m.update({
        "c_share": m["per_share_c"], "c_share_ci95": m["per_share_ci_c"], "sharpe": m["sharpe_ann"],
        "usd_day": float(ev.pnl.sum() / len(daily)),
        "ret_ann": float(daily.mean() * 365 / cap), "vol_ann": float(daily.std() * np.sqrt(365) / cap),
        "turnover_x": float(ev.usd_in.sum() / cap),
        "fees_x2_c_share": float(((ev.pnl_ps - fee) * ev.shares).sum() / ev.shares.sum() * 100),
    })
    return m
