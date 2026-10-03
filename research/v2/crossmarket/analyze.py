"""Steps 2-5 of the crossmarket lens on the IS side-market tapes.

  A. capacity: in-play side-market volume by type and month vs the moneyline
  B. sensitivity b per type, walk-forward, with month-m predictive fit
  C. event study: markouts of side takers after a moneyline jump, implied vs contrary direction;
     catch-up of side prices to the implied move by seconds since detection
  D. backtest: take a stale side quote after a moneyline jump; walk-forward (k, min_impl)
Run: .venv/bin/python research/v2/crossmarket/analyze.py   (after fetch_events, fetch_tapes, build)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from common import CACHE, OOS_CUT, OUT, ROOT, month_of, regime, side_markets, taker_fee  # noqa: E402
import model  # noqa: E402
from src.backtest import stats  # noqa: E402

FIRST_EVAL = __import__("os").environ.get("CM_FIRST_EVAL", "2026-02")          # need >= 1 earlier month of side tapes to fit b
OUR_LATENCY = 1
W_FILL = 30                     # seconds after detection + latency in which a send may happen
MAX_REF_AGE = 600               # side reference print must be <= 600 s before the send
MAX_USD_TRADE, PRINT_SHARE, MAX_USD_MATCH = 1_000, 0.5, 3_000
K_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
MIN_IMPL_GRID = (0.01, 0.02, 0.04)
EXITS = ("res", "taker60", "passive")
N_BOOT = 2000
REBATE = 0.15
VARIANTS = []                   # every variant evaluated, for the count


def boot_ci(x: pd.DataFrame, col: str, by: str = "event_id", w: str | None = None, seed: int = 0):
    """Cluster bootstrap CI of a (share-weighted if w) mean, clusters = matches."""
    if len(x) == 0:
        return (np.nan, np.nan)
    ww = x[w].to_numpy() if w else np.ones(len(x))
    g = pd.DataFrame({"s": x[col].to_numpy() * ww, "n": ww, "c": x[by].to_numpy()}).groupby("c").sum()
    s, n = g.s.to_numpy(), g.n.to_numpy()
    rng = np.random.default_rng(seed)
    k = len(g)
    bs = np.empty(N_BOOT)
    for i in range(N_BOOT):
        pick = rng.integers(0, k, k)
        bs[i] = s[pick].sum() / n[pick].sum()
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def load():
    pr = pd.read_parquet(CACHE / "side_prints.parquet")
    iv = pd.read_parquet(CACHE / "intervals.parquet")
    assert (pr.start < OOS_CUT).all() and (iv.start < OOS_CUT).all()
    pr["month"] = month_of(pr.ts)
    iv["month"] = month_of(iv.ts)
    pr["dir"] = np.where(pr.at_ask, 1.0, -1.0)
    pr["fee"] = taker_fee(pr.q0, pr.fee_rate)
    pr["regime"] = [regime(d, f) for d, f in zip(pr.delay, pr.fee_rate)]
    return pr, iv


# ---------------------------------------------------------------- A. capacity
def capacity(pr: pd.DataFrame) -> dict:
    sm = side_markets()
    sm = sm[sm.smt != "tennis_completed_match"]
    sm["month"] = sm.start.dt.tz_localize(None).dt.to_period("M").astype(str)
    life = sm.groupby("smt").agg(markets=("cond", "size"), lifetime_vol_usd=("volume", "sum"))
    inplay = pr.groupby("smt").agg(inplay_prints=("q0", "size"), inplay_usd=("usd", "sum"),
                                   median_print_usd=("usd", "median"),
                                   p90_print_usd=("usd", lambda s: s.quantile(0.9)),
                                   matches=("event_id", "nunique"))
    by_type = life.join(inplay)
    by_type["inplay_share_of_lifetime"] = by_type.inplay_usd / by_type.lifetime_vol_usd
    ml = pd.read_parquet(ROOT / "data" / "is_prints.parquet", columns=["ts", "usd"])
    ml_m = ml.groupby(month_of(ml.ts)).usd.sum()
    del ml
    side_m = pr.groupby("month").usd.sum()
    by_month = pd.DataFrame({"side_inplay_usd": side_m, "ml_inplay_usd": ml_m}).fillna(0)
    by_month["side_over_ml"] = by_month.side_inplay_usd / by_month.ml_inplay_usd
    by_type.to_csv(OUT / "capacity_by_type.csv")
    by_month.to_csv(OUT / "capacity_by_month.csv")
    tm = pr.pivot_table(index="month", columns="smt", values="usd", aggfunc="sum").fillna(0)
    tm.to_csv(OUT / "capacity_type_month.csv")
    return {"by_type": by_type.reset_index().to_dict("records"),
            "by_month": by_month.reset_index(names="month").to_dict("records")}


# ---------------------------------------------------------------- B. sensitivity
def sensitivity(iv: pd.DataFrame, months: list[str]):
    bwf = model.walk_forward_b(iv, months)
    x, y = model.xy(iv)
    iv = iv.assign(x=x, y=y)
    rows = []
    for (m, smt), b in bwf.set_index(["month", "smt"]).b.items():
        cur = iv[(iv.month == m) & (iv.smt == smt)].dropna(subset=["x", "y"])
        if len(cur) < 30:
            rows.append({"month": m, "smt": smt, "b": b, "n": len(cur)})
            continue
        pred = b * cur.x
        r2 = 1 - ((cur.y - pred) ** 2).sum() / ((cur.y - cur.y.mean()) ** 2).sum()
        b_m = (cur.x * cur.y).sum() / (cur.x ** 2).sum()
        rows.append({"month": m, "smt": smt, "b": b, "n": len(cur), "b_fit_month_m": float(b_m),
                     "corr_pred_actual": float(np.corrcoef(pred, cur.y)[0, 1]), "r2_oos_month": float(r2)})
    # linear-in-price diagnostic (variant, not used downstream): dq' = beta dp for player markets
    pl = iv[iv.smt.isin(model.PLAYER) & (iv.align0 != 0)].dropna(subset=["p1", "p2"])
    s = np.where(pl.align0 == -1, -1.0, 1.0)
    lin = {}
    for smt, g in pl.assign(dq=s * (pl.m2 - pl.m1), dp=pl.p2 - pl.p1).groupby("smt"):
        lin[smt] = {"beta_linear_full_is": float((g.dq * g.dp).sum() / (g.dp ** 2).sum()),
                    "corr": float(np.corrcoef(g.dq, g.dp)[0, 1]), "n": int(len(g))}
    VARIANTS.append("beta model: logit (primary)")
    VARIANTS.append("beta model: linear dq=beta*dp (diagnostic only)")
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "beta_walkforward.csv", index=False)
    return bwf, t, lin


def model_choice(iv: pd.DataFrame, bwf: pd.DataFrame, months: list[str]):
    """Walk-forward choice between the type-level b and in-match (local) b shrunk to it, by pooled
    predictive R^2 (vs a zero forecast) of d logit on earlier months' intervals."""
    sums = model.local_sums(iv)
    iv = iv.assign(ts_start=iv.ts - iv.dt)
    iv = model.attach_local(iv, sums, "ts_start", "pre_")
    x, y = model.xy(iv)
    iv = iv.assign(x=x, y=y).merge(bwf, on=["month", "smt"], how="left").dropna(subset=["x", "y", "b"])
    names = ["type"] + [f"local{l}" for l in model.LAMBDA_GRID]
    r2 = []
    for m, g in iv.groupby("month"):
        row = {"month": m, "n": len(g)}
        for nm in names:
            b = g.b if nm == "type" else model.shrunk_b(g.b, g.pre_sxy, g.pre_sxx, float(nm[5:]))
            row[nm] = float(1 - ((g.y - b * g.x) ** 2).sum() / (g.y ** 2).sum())
        r2.append(row)
    r2 = pd.DataFrame(r2)
    for nm in names[1:]:
        VARIANTS.append(f"beta model: {nm} (in-match beta shrunk to type b)")
    choice = {}
    for m in months:
        past = r2[r2.month < m]
        if past.empty:
            choice[m] = "type"
            continue
        w = past.n / past.n.sum()
        choice[m] = max(names, key=lambda nm: float((past[nm] * w).sum()))
    r2.to_csv(OUT / "beta_model_r2_by_month.csv", index=False)
    return sums, r2, choice


def attach_b(pr: pd.DataFrame, bwf: pd.DataFrame, sums=None, choice=None) -> pd.DataFrame:
    pr = pr.merge(bwf, on=["month", "smt"], how="left")
    pr["b_rs"] = pr.b
    pr["b_ro"] = pr.b
    if sums is None:
        return pr
    pr = model.attach_local(pr, sums, "ts_rs", "rs_")
    pr = model.attach_local(pr, sums, "ts_ro", "ro_")
    nm = pr.month.map(choice).fillna("type")
    for name in set(nm):
        if name == "type":
            continue
        lam = float(name[5:])
        sel = nm == name
        pr.loc[sel, "b_rs"] = model.shrunk_b(pr.b[sel], pr.rs_sxy[sel], pr.rs_sxx[sel], lam)
        pr.loc[sel, "b_ro"] = model.shrunk_b(pr.b[sel], pr.ro_sxy[sel], pr.ro_sxx[sel], lam)
    pr["beta_model"] = nm
    return pr


# ---------------------------------------------------------------- C. event study
BUCKETS = [(-60, 0, "pre-onset 60s (placebo)"), (0, 1, "0-1s"), (1, 3, "1-3s"), (3, 6, "3-6s"),
           (6, 10, "6-10s"), (10, 20, "10-20s"), (20, 60, "20-60s"), (60, 300, "60-300s"),
           (300, 1e9, ">300s")]


def event_study(pr: pd.DataFrame, min_impl: float = 0.01) -> dict:
    e = pr[pr.month >= FIRST_EVAL].dropna(subset=["b"]).copy()
    e["s"] = e.ts - e.detect
    # implied move from the side's pre-onset state to the moneyline now (at the print)
    q_imp = model.implied_q0(e.q_ro, e.p_ro, e.p_now, e.smt.to_numpy(), e.align0.to_numpy(), e.b_ro.to_numpy())
    e["impl"] = q_imp - e.q_ro
    e["ref_age_on"] = e.onset - e.ts_ro
    # placebo: prints in the 60 s before the next onset, implied direction = that next jump's direction
    e["bucket"] = None
    for lo, hi, lab in BUCKETS[1:]:
        e.loc[(e.s >= lo) & (e.s < hi), "bucket"] = lab
    e["net_res"] = e.mo_res - e.fee
    e["net60"] = e.mo60 - e.fee
    e["net300"] = e.mo300 - e.fee
    base = e.dropna(subset=["net_res"])
    rows = [{"bucket": "all in-play side takers", "side": "all", "n": len(base), "matches": base.event_id.nunique(),
             "usd": base.usd.sum(), "net_res_c": base.net_res.mean() * 100,
             "ci": [c * 100 for c in boot_ci(base, "net_res")], "net60_c": base.net60.mean() * 100,
             "fee_c": base.fee.mean() * 100}]
    ok = e.dropna(subset=["impl", "net_res"])
    ok = ok[(ok.impl.abs() >= min_impl) & (ok.ref_age_on <= MAX_REF_AGE)]
    ok["with"] = np.sign(ok.impl) == ok.dir
    for _, _, lab in BUCKETS[1:]:
        for w, name in ((True, "implied"), (False, "contrary")):
            g = ok[(ok.bucket == lab) & (ok["with"] == w)]
            if len(g) == 0:
                continue
            rows.append({"bucket": lab, "side": name, "n": len(g), "matches": g.event_id.nunique(),
                         "usd": g.usd.sum(), "net_res_c": g.net_res.mean() * 100,
                         "ci": [c * 100 for c in boot_ci(g, "net_res")],
                         "net60_c": g.net60.mean() * 100, "net300_c": g.net300.mean() * 100,
                         "fee_c": g.fee.mean() * 100, "mean_abs_impl_c": g.impl.abs().mean() * 100})
    # placebo: 60 s before an onset, "implied" = direction the next jump will go (not knowable)
    # catch-up: fraction of the implied move already in the side price, by bucket
    cu = ok[(ok.ref_age_on <= 300) & (ok.impl.abs() >= 0.02)].copy()
    cu["frac"] = ((cu.smid - cu.q_ro) / cu.impl).clip(-2, 3)
    catch = cu.groupby("bucket").frac.agg(["size", "median", "mean"]).reindex(
        [b[2] for b in BUCKETS[1:]]).dropna(how="all")
    # moneyline reference: fraction of the moneyline move (pre-onset -> +60 s) done at each bucket
    by_regime = []
    win = ok[(ok.s >= ok.delay + OUR_LATENCY) & (ok.s <= 60)]
    for (rg, w), g in win.groupby(["regime", "with"]):
        by_regime.append({"regime": rg, "side": "implied" if w else "contrary", "n": len(g),
                          "matches": g.event_id.nunique(), "net_res_c": g.net_res.mean() * 100,
                          "ci": [c * 100 for c in boot_ci(g, "net_res")], "net60_c": g.net60.mean() * 100})
    by_type = []
    for (smt, w), g in win.groupby(["smt", "with"]):
        by_type.append({"smt": smt, "side": "implied" if w else "contrary", "n": len(g),
                        "matches": g.event_id.nunique(), "net_res_c": g.net_res.mean() * 100,
                        "ci": [c * 100 for c in boot_ci(g, "net_res")], "net60_c": g.net60.mean() * 100})
    # who takes the stale side quotes? moneyline fast-tier wallets, selected walk-forward (src.fasttier.qualify
    # on 0-3 s moneyline prints of months < m), vs everyone else, in the delay+1 .. 10 s window
    from src.fasttier import qualify
    f03 = pd.read_parquet(ROOT / "data" / "derived" / "prints_0_3s_is.parquet", columns=["ts", "wallet", "mo30", "cond", "bucket"])
    f03["month"] = month_of(f03.ts)
    early = ok[(ok.s >= ok.delay + OUR_LATENCY) & (ok.s < 10)].copy()
    early["fast"] = False
    for m in early.month.unique():
        sel = set(qualify(f03[f03.month < m]))
        mm = early.month == m
        early.loc[mm, "fast"] = early.loc[mm, "wallet"].isin(sel)
    who = []
    for (w, fast), g in early.groupby(["with", "fast"]):
        who.append({"side": "implied" if w else "contrary", "ml_fast_tier": bool(fast), "n": len(g),
                    "usd": g.usd.sum(), "matches": g.event_id.nunique(), "net_res_c": g.net_res.mean() * 100,
                    "ci": [c * 100 for c in boot_ci(g, "net_res")], "net60_c": g.net60.mean() * 100})
    VARIANTS.append(f"event study min_impl={min_impl}")
    pd.DataFrame(rows).to_csv(OUT / f"event_study_minimpl{min_impl}.csv", index=False)
    catch.to_csv(OUT / "catchup.csv")
    return {"rows": rows, "catchup": catch.reset_index().to_dict("records"), "by_regime": by_regime,
            "by_type": by_type, "who_takes_early": who}


# ---------------------------------------------------------------- D. backtest
def candidates(pr: pd.DataFrame) -> pd.DataFrame:
    """Every side print an order sent in [detect + latency, detect + latency + W_FILL] could fill
    against, with the model-implied side price at send time (causal: refs strictly before send)."""
    c = pr.dropna(subset=["b", "detect", "q_rs", "p_rs", "p_send"]).copy()
    c["s_send"] = c.t_send - c.detect
    c = c[(c.s_send >= OUR_LATENCY) & (c.s_send <= OUR_LATENCY + W_FILL)]
    c = c[(c.t_send - c.ts_rs) <= MAX_REF_AGE]
    q_imp = model.implied_q0(c.q_rs, c.p_rs, c.p_send, c.smt.to_numpy(), c.align0.to_numpy(), c.b_rs.to_numpy())
    c["impl"] = q_imp - c.q_rs
    c["q_imp"] = q_imp
    c["idir"] = np.sign(c.impl)
    # the print must be on the side we would hit: buying outcome 0 lifts its ask
    c = c[((c.idir > 0) & c.at_ask) | ((c.idir < 0) & ~c.at_ask)]
    c["moved"] = (c.q0 - c.q_rs) * c.idir
    c["px"] = np.where(c.idir > 0, c.q0, 1 - c.q0)
    c["tgt"] = np.where(c.idir > 0, c.q_imp, 1 - c.q_imp)    # model-implied price of the token we buy
    c = c[(c.px > 0.02) & (c.px < 0.98)]
    return c


def exit_prices(pr: pd.DataFrame, tr: pd.DataFrame, H: int = 60) -> np.ndarray:
    """Taker exit: first print >= entry + H on the side we would hit to sell; else resolution."""
    out = np.full(len(tr), np.nan)
    g = pr.groupby("cond")
    idx = g.indices
    ts_all, q_all, aa_all = pr.ts.to_numpy(), pr.q0.to_numpy(), pr.at_ask.to_numpy()
    for i, (cond, t0, d) in enumerate(zip(tr.cond, tr.ts, tr.idir)):
        ii = idx[cond]
        ts = ts_all[ii]
        j0 = np.searchsorted(ts, t0 + H, "left")
        for j in range(j0, len(ii)):
            # selling outcome 0 hits its bid (a print with at_ask False), selling outcome 1 lifts it
            if (d > 0 and not aa_all[ii[j]]) or (d < 0 and aa_all[ii[j]]):
                out[i] = q_all[ii[j]] if d > 0 else 1 - q_all[ii[j]]
                break
    return out


def exit_passive(pr: pd.DataFrame, tr: pd.DataFrame) -> np.ndarray:
    """Passive exit: right after entry, rest a sell of our token at the model-implied price (target).
    Filled at the target (maker: no fee, 15% rebate) by the first later print in which a taker BOUGHT
    our token at >= target with at least our size; otherwise held to resolution (NaN here)."""
    out = np.full(len(tr), np.nan)
    idx = pr.groupby("cond").indices
    ts_all, q_all, aa_all, sz_all = pr.ts.to_numpy(), pr.q0.to_numpy(), pr.at_ask.to_numpy(), pr["size"].to_numpy()
    for i, (cond, t0, d, tgt, sh) in enumerate(zip(tr.cond, tr.ts, tr.idir, tr.tgt, tr.shares)):
        ii = idx[cond]
        ts = ts_all[ii]
        for j in range(np.searchsorted(ts, t0, "right"), len(ii)):
            g = ii[j]
            # a taker buying outcome 0 lifts its ask (at_ask True); buying outcome 1 hits outcome 0's bid
            buy_ours = aa_all[g] if d > 0 else not aa_all[g]
            px = q_all[g] if d > 0 else 1 - q_all[g]
            if buy_ours and px >= tgt and sz_all[g] >= sh:
                out[i] = tgt
                break
    return out


def trades(c: pd.DataFrame, k: float, min_impl: float, exit_px: pd.Series | None = None,
           exit_pv: pd.Series | None = None) -> pd.DataFrame:
    sel = c[(c.impl.abs() >= min_impl) & (c.moved < k * c.impl.abs())]
    sel = sel.sort_values("ts", kind="stable").drop_duplicates(["cond", "jump_k"], keep="first")
    if sel.empty:
        return sel
    sh = np.minimum(MAX_USD_TRADE / sel.px, PRINT_SHARE * sel["size"])
    usd = sh * sel.px
    # per-match cap on gross dollars committed
    cum = usd.groupby(sel.event_id).cumsum()
    keep = cum <= MAX_USD_MATCH
    sel, sh, usd = sel[keep], sh[keep], usd[keep]
    payout = np.where(sel.idir > 0, sel.res_s0, 1 - sel.res_s0)
    fee_in = taker_fee(sel.px, sel.fee_rate)
    t = sel.assign(shares=sh, usd_in=usd, payout=payout, fee_in=fee_in)
    t["pnl_ps_res"] = t.payout - t.px - t.fee_in
    if exit_px is not None:
        xp = exit_px.reindex(t.index).to_numpy()
        has = np.isfinite(xp)
        fee_out = np.where(has, taker_fee(np.nan_to_num(xp, nan=0.5), t.fee_rate), 0.0)
        t["pnl_ps_taker60"] = np.where(has, xp - t.px - t.fee_in - fee_out, t.pnl_ps_res)
        t["fee_taker60"] = t.fee_in + fee_out
    if exit_pv is not None:
        xp = exit_pv.reindex(t.index).to_numpy()
        has = np.isfinite(xp)
        reb = np.where(has, REBATE * taker_fee(np.nan_to_num(xp, nan=0.5), t.fee_rate), 0.0)
        t["pnl_ps_passive"] = np.where(has, xp - t.px - t.fee_in + reb, t.pnl_ps_res)
        t["fee_passive"] = t.fee_in - reb
    t["date"] = pd.to_datetime(t.ts, unit="s", utc=True).dt.floor("D")
    return t


def as_book(t: pd.DataFrame, exit_: str) -> pd.DataFrame:
    fee = {"res": t.fee_in, "taker60": t.get("fee_taker60"), "passive": t.get("fee_passive")}[exit_]
    b = pd.DataFrame({"cond": t.event_id, "pnl_ps": t[f"pnl_ps_{exit_}"],
                      "fee": fee, "usd_in": t.usd_in,
                      "exit": "resolution" if exit_ == "res" else "tape", "date": t.date,
                      "shares": t.shares, "month": t.month, "regime": t.regime, "smt": t.smt, "ts": t.ts})
    b["pnl"] = b.shares * b.pnl_ps
    return b


def capital_for(book: pd.DataFrame, pr_end: pd.Series) -> float:
    """3x the peak dollars locked in open positions (entry -> match end), as in the shadow book."""
    if book.empty:
        return 1.0
    ends = pr_end.reindex(book.cond).to_numpy()
    ev = np.r_[book.ts.to_numpy(), ends]
    dv = np.r_[book.usd_in.to_numpy(), -book.usd_in.to_numpy()]
    o = np.argsort(ev, kind="stable")
    return float(3 * max(np.cumsum(dv[o]).max(), 1.0))


def summarize(book: pd.DataFrame, ends: pd.Series) -> dict:
    if book.empty:
        return {"n_trades": 0}
    cap = capital_for(book, ends)
    st = stats(book, capital=cap)
    lo, hi = st["ci95_pnl_per_share_c"]
    wps = (book.pnl.sum() / book.shares.sum()) * 100
    st["share_weighted_net_c"] = float(wps)
    st["months_positive"] = int((book.groupby("month").pnl.sum() > 0).sum())
    st["months_total"] = int(book.month.nunique())
    return st


def backtest(pr: pd.DataFrame, months: list[str]) -> dict:
    c = candidates(pr)
    ends = pd.Series(pd.to_datetime(side_markets().drop_duplicates("event_id").set_index("event_id").end).map(
        lambda x: x.timestamp() if pd.notna(x) else np.nan))
    ends = ends.fillna(pr.groupby("event_id").ts.max())
    grid = [(k, mi) for k in K_GRID for mi in MIN_IMPL_GRID]
    xp_all = None
    full = {}
    for k, mi in grid:
        full[(k, mi)] = trades(c, k, mi)
        VARIANTS.append(f"backtest k={k} min_impl={mi} exit=res")
    # taker exit prices for every trade that appears in any grid cell (computed once)
    allt = pd.concat([t for t in full.values() if len(t)])
    allt = allt[~allt.index.duplicated()]
    prs = pr[["cond", "ts", "q0", "at_ask", "size"]].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    xp_all = pd.Series(exit_prices(prs, allt), index=allt.index)
    sh_all = np.minimum(MAX_USD_TRADE / allt.px, PRINT_SHARE * allt["size"])
    pv_all = pd.Series(exit_passive(prs, allt.assign(shares=sh_all)), index=allt.index)
    for key in grid:
        full[key] = trades(c, *key, exit_px=xp_all, exit_pv=pv_all)
        VARIANTS.append(f"backtest k={key[0]} min_impl={key[1]} exit=taker60")
        VARIANTS.append(f"backtest k={key[0]} min_impl={key[1]} exit=passive")
    # every grid cell over all eval months (reported, not used to choose)
    grid_rows = []
    for (k, mi), t in full.items():
        t = t[t.month >= FIRST_EVAL]
        for ex in EXITS:
            b = as_book(t, ex) if len(t) else pd.DataFrame()
            grid_rows.append({"k": k, "min_impl": mi, "exit": ex, "n": len(b),
                              "net_c": float(b.pnl_ps.mean() * 100) if len(b) else np.nan,
                              "pnl_usd": float(b.pnl.sum()) if len(b) else 0.0,
                              "usd_in": float(b.usd_in.sum()) if len(b) else 0.0})
    gr = pd.DataFrame(grid_rows)
    gr.to_csv(OUT / "backtest_grid_all_cells.csv", index=False)
    # walk-forward choice of (k, min_impl): max cumulative net $ P&L (hold to resolution) on months < m
    wf_parts, choice = [], []
    for m in months:
        best, best_p = None, -np.inf
        for key, t in full.items():
            past = t[t.month < m]
            if len(past) < 30:
                continue
            p = (past.shares * past.pnl_ps_res).sum()
            if p > best_p:
                best, best_p = key, p
        if best is None:
            continue
        cur = full[best]
        cur = cur[cur.month == m]
        choice.append({"month": m, "k": best[0], "min_impl": best[1], "past_pnl_usd": float(best_p),
                       "n": len(cur)})
        wf_parts.append(cur)
    wf = pd.concat(wf_parts) if wf_parts else pd.DataFrame()
    out = {"choices": choice, "grid_all_cells": grid_rows}
    # variant: same walk-forward (k, min_impl), plus keep only market types whose past (months < m)
    # trades under that month's chosen rule had positive net $ P&L with >= 30 trades
    tf_parts, tf_types = [], []
    for ch in choice:
        m, key = ch["month"], (ch["k"], ch["min_impl"])
        t = full[key]
        past = t[t.month < m]
        g = past.assign(p=past.shares * past.pnl_ps_res).groupby("smt").agg(n=("p", "size"), p=("p", "sum"))
        keep = g.index[(g.n >= 30) & (g.p > 0)].tolist()
        tf_types.append({"month": m, "types": keep})
        cur = t[(t.month == m) & t.smt.isin(keep)]
        tf_parts.append(cur)
    VARIANTS.append("backtest wf(k,min_impl) + wf type filter, exit=res")
    tf = pd.concat(tf_parts) if tf_parts else pd.DataFrame()
    out["typefilter_types"] = tf_types
    out["wf_typefilter_res"] = summarize(as_book(tf, "res"), ends) if len(tf) else {"n_trades": 0}
    if len(tf):
        bt_ = as_book(tf, "res")
        out["wf_typefilter_res_monthly"] = bt_.groupby("month").agg(
            n=("pnl", "size"), net_c=("pnl_ps", lambda s: s.mean() * 100), pnl_usd=("pnl", "sum"),
            usd_in=("usd_in", "sum")).reset_index().to_dict("records")
    for ex in EXITS:
        b = as_book(wf, ex) if len(wf) else pd.DataFrame()
        out[f"wf_{ex}"] = summarize(b, ends)
        if len(b):
            mon = b.groupby("month").agg(n=("pnl", "size"), net_c=("pnl_ps", lambda s: s.mean() * 100),
                                         pnl_usd=("pnl", "sum"), usd_in=("usd_in", "sum"))
            out[f"wf_{ex}_monthly"] = mon.reset_index().to_dict("records")
            reg = []
            for rg, g in b.groupby("regime"):
                lo, hi = boot_ci(g.assign(event_id=g.cond), "pnl_ps")
                reg.append({"regime": rg, "n": len(g), "net_c": g.pnl_ps.mean() * 100, "ci": [lo * 100, hi * 100],
                            "pnl_usd": g.pnl.sum(), "usd_in": g.usd_in.sum()})
            out[f"wf_{ex}_by_regime"] = reg
            typ = []
            for s_, g in b.groupby("smt"):
                lo, hi = boot_ci(g.assign(event_id=g.cond), "pnl_ps")
                typ.append({"smt": s_, "n": len(g), "net_c": g.pnl_ps.mean() * 100, "ci": [lo * 100, hi * 100],
                            "pnl_usd": g.pnl.sum(), "usd_in": g.usd_in.sum()})
            out[f"wf_{ex}_by_type"] = typ
            b.to_parquet(CACHE / f"wf_trades_{ex}.parquet")
    # fixed-rule reference (k=1, min_impl=0.02) in the current regime only, for the note
    t = full[(1.0, 0.02)]
    cur = t[t.regime == "1s/5%"]
    out["fixed_k1_mi0.02_1s5"] = summarize(as_book(cur, "res"), ends) if len(cur) else {"n_trades": 0}
    pd.DataFrame(choice).to_csv(OUT / "backtest_wf_choices.csv", index=False)
    return out


# ---------------------------------------------------------------- E. maker variant (exploratory)
MK_SHARE, MK_MAX_FILL, MK_MAX_MATCH = 0.2, 250, 2_000
MK_H = (0.0, 0.01, 0.02)


def maker(pr: pd.DataFrame, months: list[str]) -> dict:
    """Quote both sides of every side market at the moneyline-implied fair +- h, refreshed from
    information strictly before t_send (= print time - delay, conservative for a maker who can cancel
    instantly). A taker print that paid at least our quote fills us at OUR price, share 0.2, <= $250,
    <= $2,000 gross per match; held to resolution; 15% fee rebate; makers pay no fee.
    Windows: always-on, or only within 60 s after a moneyline jump detection."""
    c = pr.dropna(subset=["b", "q_rs", "p_rs", "p_send", "res_s0"]).copy()
    c = c[(c.t_send - c.ts_rs) <= MAX_REF_AGE]
    c["fair"] = model.implied_q0(c.q_rs, c.p_rs, c.p_send, c.smt.to_numpy(), c.align0.to_numpy(), c.b_rs.to_numpy())
    c["s"] = c.ts - c.detect
    ends = pd.Series(pd.to_datetime(side_markets().drop_duplicates("event_id").set_index("event_id").end).map(
        lambda x: x.timestamp() if pd.notna(x) else np.nan)).fillna(pr.groupby("event_id").ts.max())
    books = {}
    for win in ("always", "post_jump60"):
        for h in MK_H:
            VARIANTS.append(f"maker window={win} h={h}")
            x = c if win == "always" else c[(c.s >= 0) & (c.s <= 60)]
            # taker bought outcome 0 at q0 >= fair + h -> we sold outcome 0 (= bought outcome 1) at fair + h
            sell = x.at_ask & (x.q0 >= x.fair + h)
            buy = ~x.at_ask & (x.q0 <= x.fair - h)
            f = x[sell | buy].copy()
            f["long0"] = ~f.at_ask
            f["px"] = np.where(f.long0, f.fair - h, 1 - (f.fair + h))
            f = f[(f.px > 0.02) & (f.px < 0.98)].sort_values("ts", kind="stable")
            sh = np.minimum(MK_SHARE * f["size"], MK_MAX_FILL / f.px)
            usd = sh * f.px
            keep = usd.groupby(f.event_id).cumsum() <= MK_MAX_MATCH
            f, sh, usd = f[keep], sh[keep], usd[keep]
            payout = np.where(f.long0, f.res_s0, 1 - f.res_s0)
            reb = REBATE * taker_fee(np.where(f.long0, f.px, 1 - f.px), f.fee_rate)
            b = pd.DataFrame({"cond": f.event_id, "pnl_ps": payout - f.px + reb, "fee": -reb, "usd_in": usd,
                              "exit": "resolution", "date": pd.to_datetime(f.ts, unit="s", utc=True).dt.floor("D"),
                              "shares": sh, "month": f.month, "regime": f.regime, "smt": f.smt, "ts": f.ts})
            b["pnl"] = b.shares * b.pnl_ps
            books[(win, h)] = b
    choice, parts = [], []
    for m in months:
        best, bp = None, -np.inf
        for key, b in books.items():
            past = b[b.month < m]
            if len(past) >= 30 and past.pnl.sum() > bp:
                best, bp = key, past.pnl.sum()
        if best is None:
            continue
        cur = books[best][books[best].month == m]
        choice.append({"month": m, "window": best[0], "h": best[1], "past_pnl_usd": float(bp), "n": len(cur)})
        parts.append(cur)
    wf = pd.concat(parts) if parts else pd.DataFrame()
    out = {"choices": choice, "wf": summarize(wf, ends) if len(wf) else {"n_trades": 0},
           "cells": [{"window": k[0], "h": k[1], "n": len(b[b.month >= FIRST_EVAL]),
                      "net_c": float(b[b.month >= FIRST_EVAL].pnl_ps.mean() * 100),
                      "pnl_usd": float(b[b.month >= FIRST_EVAL].pnl.sum())} for k, b in books.items()]}
    if len(wf):
        out["wf_monthly"] = wf.groupby("month").agg(n=("pnl", "size"), net_c=("pnl_ps", lambda s: s.mean() * 100),
                                                    pnl_usd=("pnl", "sum"), usd_in=("usd_in", "sum")
                                                    ).reset_index().to_dict("records")
        reg = []
        for rg, g in wf.groupby("regime"):
            lo, hi = boot_ci(g.assign(event_id=g.cond), "pnl_ps")
            reg.append({"regime": rg, "n": len(g), "net_c": g.pnl_ps.mean() * 100, "ci": [lo * 100, hi * 100],
                        "pnl_usd": g.pnl.sum(), "usd_in": g.usd_in.sum()})
        out["wf_by_regime"] = reg
        wf.to_parquet(CACHE / "wf_maker.parquet")
    return out


# ---------------------------------------------------------------- F. leaning maker (added after C; exploratory)
LEAN_MIN_IMPL = (0.01, 0.02, 0.04)


def lean_diagnostics(c: pd.DataFrame) -> list[dict]:
    """Same fill model, eval months, always-on, min_impl 0.04 unless stated: (i) unconditional maker
    (both sides, every print, no lean), (ii) anti-lean placebo (filled only by takers trading WITH the
    implied move), (iii) the lean book itself, by regime. Diagnostics only, never chosen."""
    c = c[c.month >= FIRST_EVAL]
    rows = []
    for name, f in (("unconditional maker (all prints, |impl| any)", c),
                    ("anti-lean placebo (|impl|>=0.04)", c[(c.dir == c.idir) & (c.impl.abs() >= 0.04)]),
                    ("lean (|impl|>=0.04)", c[(c.dir == -c.idir) & (c.impl.abs() >= 0.04)])):
        VARIANTS.append(f"lean diagnostic: {name}")
        long0 = ~f.at_ask.to_numpy()            # maker is long outcome 0 when the taker sold it
        px = np.where(long0, f.q0, 1 - f.q0)
        ok = (px > 0.02) & (px < 0.98)
        f, px, long0 = f[ok], px[ok], long0[ok]
        payout = np.where(long0, f.res_s0, 1 - f.res_s0)
        g = f.assign(pnl_ps=payout - px + REBATE * taker_fee(f.q0, f.fee_rate))
        for rg, gg in [("all", g)] + list(g.groupby("regime")):
            lo, hi = boot_ci(gg, "pnl_ps")
            rows.append({"book": name, "regime": rg, "n": len(gg), "net_c": gg.pnl_ps.mean() * 100,
                         "ci": [lo * 100, hi * 100],
                         "share_w_net_c": float((gg.pnl_ps * gg["size"]).sum() / gg["size"].sum() * 100),
                         "flow_usd_per_month": float(gg.usd.sum() / max(gg.month.nunique(), 1)),
                         "months": int(gg.month.nunique())})
    return rows


def lean_maker(pr: pd.DataFrame, months: list[str]) -> dict:
    """One-sided quoting that leans with the moneyline: when the moneyline-implied side move since the
    side market's last print (computed from information strictly before t_send) is >= min_impl, rest
    only on the side that gains from it (a bid on outcome 0 if the implied move is up). We are filled
    only by takers trading AGAINST the implied move, at the print price (we joined that level), share
    0.2 of the print, <= $250 per fill, <= $2,000 gross per match; held to resolution; 0 fee, 15% rebate.
    Windows: always-on, or only within 60 s after a moneyline jump detection."""
    c = pr.dropna(subset=["b", "q_rs", "p_rs", "p_send", "res_s0"]).copy()
    c = c[(c.t_send - c.ts_rs) <= MAX_REF_AGE]
    q_imp = model.implied_q0(c.q_rs, c.p_rs, c.p_send, c.smt.to_numpy(), c.align0.to_numpy(), c.b_rs.to_numpy())
    c["impl"] = q_imp - c.q_rs
    c["idir"] = np.sign(c.impl)
    c["s"] = c.ts - c.detect
    diag = lean_diagnostics(c)
    c = c[c.dir == -c.idir]                     # taker traded against the implied move: hits our quote
    c["px"] = np.where(c.idir > 0, c.q0, 1 - c.q0)
    c = c[(c.px > 0.02) & (c.px < 0.98)]
    ends = pd.Series(pd.to_datetime(side_markets().drop_duplicates("event_id").set_index("event_id").end).map(
        lambda x: x.timestamp() if pd.notna(x) else np.nan)).fillna(pr.groupby("event_id").ts.max())
    books = {}
    for win in ("always", "post_jump60"):
        for mi in LEAN_MIN_IMPL:
            VARIANTS.append(f"lean maker window={win} min_impl={mi}")
            f = c[c.impl.abs() >= mi]
            if win == "post_jump60":
                f = f[(f.s >= 0) & (f.s <= 60)]
            f = f.sort_values("ts", kind="stable")
            sh = np.minimum(MK_SHARE * f["size"], MK_MAX_FILL / f.px)
            usd = sh * f.px
            keep = usd.groupby(f.event_id).cumsum() <= MK_MAX_MATCH
            f, sh, usd = f[keep], sh[keep], usd[keep]
            payout = np.where(f.idir > 0, f.res_s0, 1 - f.res_s0)
            reb = REBATE * taker_fee(f.q0, f.fee_rate)
            b = pd.DataFrame({"cond": f.event_id, "pnl_ps": payout - f.px + reb, "fee": -reb, "usd_in": usd,
                              "exit": "resolution", "date": pd.to_datetime(f.ts, unit="s", utc=True).dt.floor("D"),
                              "shares": sh, "month": f.month, "regime": f.regime, "smt": f.smt, "ts": f.ts})
            b["pnl"] = b.shares * b.pnl_ps
            books[(win, mi)] = b
    choice, parts = [], []
    for m in months:
        best, bp = None, -np.inf
        for key, b in books.items():
            past = b[b.month < m]
            if len(past) >= 30 and past.pnl.sum() > bp:
                best, bp = key, past.pnl.sum()
        if best is None:
            continue
        cur = books[best][books[best].month == m]
        choice.append({"month": m, "window": best[0], "min_impl": best[1], "past_pnl_usd": float(bp), "n": len(cur)})
        parts.append(cur)
    wf = pd.concat(parts) if parts else pd.DataFrame()
    ev = lambda b: b[b.month >= FIRST_EVAL]  # noqa: E731
    out = {"choices": choice, "wf": summarize(wf, ends) if len(wf) else {"n_trades": 0}, "diagnostics": diag,
           "cells": [{"window": k[0], "min_impl": k[1], "n": len(ev(b)), "net_c": float(ev(b).pnl_ps.mean() * 100),
                      "share_w_net_c": float(ev(b).pnl.sum() / ev(b).shares.sum() * 100),
                      "pnl_usd": float(ev(b).pnl.sum()), "usd_in": float(ev(b).usd_in.sum())}
                     for k, b in books.items()]}
    if len(wf):
        out["wf_monthly"] = wf.groupby("month").agg(n=("pnl", "size"), net_c=("pnl_ps", lambda s: s.mean() * 100),
                                                    pnl_usd=("pnl", "sum"), usd_in=("usd_in", "sum")
                                                    ).reset_index().to_dict("records")
        reg, typ = [], []
        for rg, g in wf.groupby("regime"):
            lo, hi = boot_ci(g.assign(event_id=g.cond), "pnl_ps")
            reg.append({"regime": rg, "n": len(g), "net_c": g.pnl_ps.mean() * 100, "ci": [lo * 100, hi * 100],
                        "share_w_net_c": g.pnl.sum() / g.shares.sum() * 100,
                        "pnl_usd": g.pnl.sum(), "usd_in": g.usd_in.sum(), "months": g.month.nunique()})
        for s_, g in wf.groupby("smt"):
            lo, hi = boot_ci(g.assign(event_id=g.cond), "pnl_ps")
            typ.append({"smt": s_, "n": len(g), "net_c": g.pnl_ps.mean() * 100, "ci": [lo * 100, hi * 100],
                        "pnl_usd": g.pnl.sum(), "usd_in": g.usd_in.sum()})
        out["wf_by_regime"] = reg
        out["wf_by_type"] = typ
        wf.to_parquet(CACHE / "wf_lean_maker.parquet")
    return out


def main():
    pr, iv = load()
    months = sorted(m for m in pr.month.unique() if m >= FIRST_EVAL)
    res = {"capacity": capacity(pr)}
    bwf, bt, lin = sensitivity(iv, sorted(pr.month.unique()))
    res["beta_walkforward"] = bt.to_dict("records")
    res["beta_linear_diag"] = lin
    sums, r2, mchoice = model_choice(iv, bwf, months)
    res["beta_model_r2"] = r2.to_dict("records")
    res["beta_model_choice"] = mchoice
    pr = attach_b(pr, bwf, sums, mchoice)
    res["event_study"] = event_study(pr, 0.01)
    res["event_study_2c"] = event_study(pr, 0.02)
    res["backtest"] = backtest(pr, months)
    res["maker"] = maker(pr, months)
    res["lean_maker"] = lean_maker(pr, months)
    res["variants"] = VARIANTS
    res["n_variants"] = len(VARIANTS)
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: res["backtest"][k] for k in ("wf_res", "wf_taker60", "choices")}, indent=1, default=float))


if __name__ == "__main__":
    main()
