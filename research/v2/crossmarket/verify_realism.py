"""Adversarial realism / statistics checks on the crossmarket lens's best variant (leaning side-market maker).

Run from the repo root:
    .venv/bin/python research/v2/crossmarket/verify_realism.py
Output: research/v2/crossmarket/verify_realism.json (and a printed summary).
IS data only (side_prints/intervals built from universe_is, is_prints for the moneyline mid).
The lens pipeline is re-run in memory; its scratch writes are redirected to data/v2_crossmarket/verify/
so the lens's own CSVs / parquets are not touched.

Checks
  0. reproduce the headline walk-forward lean-maker numbers from the lens's own code
  1. price grid: is the in-play tick really 0.001 on side markets? (share of prints on 1c vs 0.1c levels)
  2. fill-model stress (each re-run with the same walk-forward cell choice rule):
       VWAP prints (sweeps reported at the average price) moved to the top level
       stepping ahead of the queue: +1 tick (1c / 0.1c) at 20% or 100% of the print
       back of the queue: fill = burst $ beyond Q dollars queued ahead (Q = 25/50/100/250)
       no maker rebate
  3. latency: implied move recomputed with X extra seconds of information lag (X = 2/5/10/30 s)
     and P&L split by whether the moneyline reversed between t_send and the print (pick-off risk)
  4. edge by print size (does the edge live in the small prints a back-of-queue maker never sees?)
  5. concentration: months, matches, counterparty wallets, leave-one-month-out
  6. multiple testing: deflated Sharpe (Bailey & Lopez de Prado), Bonferroni haircut of Sharpe and of
     the per-share t-stat, using the lens's 68 variants (+ these reviewer variants)
  7. plateau of the min_impl threshold (fixed rules, never chosen)
  8. current regime (1 s / 5%) per-share under each stress and capacity per 30 days
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
import analyze  # noqa: E402
import model  # noqa: E402
from common import CACHE, OOS_CUT, ROOT, taker_fee  # noqa: E402
from src.tiers import _mid_series  # noqa: E402

VER = CACHE / "verify"
VER.mkdir(parents=True, exist_ok=True)
analyze.OUT = VER          # the lens's sensitivity/model_choice write here instead (lean_maker: CACHE, set after load)
REBATE = analyze.REBATE
SHARE, MAXF, MAXM = analyze.MK_SHARE, analyze.MK_MAX_FILL, analyze.MK_MAX_MATCH
GRID = [(w, mi) for w in ("always", "post_jump60") for mi in analyze.LEAN_MIN_IMPL]
CUR = "1s/5%"
REV = []                   # reviewer variants (counted for the multiple-testing haircut)
N_BOOT = 2000


# ------------------------------------------------------------------ helpers
def ci(df, col="pnl_ps", w=None, by="cond"):
    if len(df) == 0:
        return [np.nan, np.nan]
    ww = df[w].to_numpy() if w else np.ones(len(df))
    g = pd.DataFrame({"s": df[col].to_numpy() * ww, "n": ww, "c": df[by].to_numpy()}).groupby("c").sum()
    s, n = g.s.to_numpy(), g.n.to_numpy()
    rng = np.random.default_rng(0)
    k = len(g)
    bs = np.empty(N_BOOT)
    for i in range(N_BOOT):
        p = rng.integers(0, k, k)
        bs[i] = s[p].sum() / n[p].sum()
    return [float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100), float(bs.std() * 100)]


def daily(b, lo=None, hi=None):
    d = b.groupby("date").pnl.sum()
    lo = lo or d.index.min()
    hi = hi or d.index.max()
    return d.reindex(pd.date_range(lo, hi, freq="D", tz="UTC"), fill_value=0.0)


def sharpe_ann(d):
    return float(d.mean() / d.std() * np.sqrt(365)) if d.std() > 0 else np.nan


def summ(b, label=""):
    """Per-fill mean, share-weighted mean (= $ P&L / shares), cluster CIs, $ and regime split."""
    if len(b) == 0:
        return {"label": label, "n": 0}
    cur = b[b.regime == CUR]
    out = {"label": label, "n": int(len(b)), "matches": int(b.cond.nunique()),
           "per_fill_c": float(b.pnl_ps.mean() * 100), "per_fill_ci": ci(b)[:2],
           "share_w_c": float(b.pnl.sum() / b.shares.sum() * 100), "share_w_ci": ci(b, w="shares")[:2],
           "pnl_usd": float(b.pnl.sum()), "notional_usd": float(b.usd_in.sum()),
           "months_pos_usd": int((b.groupby("month").pnl.sum() > 0).sum()), "months": int(b.month.nunique()),
           "sharpe_ann": sharpe_ann(daily(b))}
    if len(cur):
        days = (cur.ts.max() - cur.ts.min()) / 86400 + 1
        out.update({"cur_n": int(len(cur)), "cur_per_fill_c": float(cur.pnl_ps.mean() * 100),
                    "cur_per_fill_ci": ci(cur)[:2], "cur_share_w_c": float(cur.pnl.sum() / cur.shares.sum() * 100),
                    "cur_share_w_ci": ci(cur, w="shares")[:2], "cur_pnl_usd": float(cur.pnl.sum()),
                    "cur_notional_per_30d": float(cur.usd_in.sum() / days * 30),
                    "cur_pnl_per_30d": float(cur.pnl.sum() / days * 30)})
    return out


def book(f, px=None, fill_usd=None, share=SHARE, rebate=True, cap_fill=MAXF):
    """Lean-maker book from candidate fills f (rows where a contrary taker printed). px: our price per
    share of the token we buy (default the print price); fill_usd: $ we get filled (default share * print)."""
    f = f.copy()
    f["px_"] = f.px if px is None else px
    if fill_usd is None:
        sh = np.minimum(share * f["size"], cap_fill / f.px_)
    else:
        sh = np.minimum(fill_usd, cap_fill) / f.px_
    f["sh_"] = sh
    f = f[(f.sh_ > 0) & (f.px_ > 0.02) & (f.px_ < 0.98)].sort_values("ts", kind="stable")
    usd = f.sh_ * f.px_
    keep = usd.groupby(f.event_id).cumsum() <= MAXM
    f, usd = f[keep], usd[keep]
    payout = np.where(f.idir > 0, f.res_s0, 1 - f.res_s0)
    reb = REBATE * taker_fee(f.q0, f.fee_rate) if rebate else 0.0
    b = pd.DataFrame({"cond": f.event_id, "pnl_ps": payout - f.px_ + reb, "usd_in": usd, "shares": f.sh_,
                      "date": pd.to_datetime(f.ts, unit="s", utc=True).dt.floor("D"), "month": f.month,
                      "regime": f.regime, "smt": f.smt, "ts": f.ts, "wallet": f.wallet, "usd_print": f.usd,
                      "side_cond": f.cond}, index=f.index)
    b["pnl"] = b.shares * b.pnl_ps
    return b


def cells(c, months, **kw):
    """The lens's 6 cells (window x min_impl) under a fill model, then its walk-forward choice rule."""
    books = {}
    for win, mi in GRID:
        f = c[c.impl.abs() >= mi]
        if win == "post_jump60":
            f = f[(f.s >= 0) & (f.s <= 60)]
        books[(win, mi)] = book(f, **kw)
    return books


def walk_forward(books, months):
    choice, parts = [], []
    for m in months:
        best, bp = None, -np.inf
        for key, b in books.items():
            past = b[b.month < m]
            if len(past) >= 30 and past.pnl.sum() > bp:
                best, bp = key, past.pnl.sum()
        if best is None:
            continue
        choice.append({"month": m, "cell": list(best)})
        parts.append(books[best][books[best].month == m])
    return (pd.concat(parts) if parts else pd.DataFrame()), choice


def lean_candidates(pr, q_ref, ts_ref, p_ref, p_send, b, t_send_eff):
    """Rows where a contrary taker printed against the implied move (the lens's fill event)."""
    c = pr.assign(q_ref=q_ref, ts_ref=ts_ref, p_ref=p_ref, p_snd=p_send, b_use=b)
    c = c.dropna(subset=["b", "q_ref", "p_ref", "p_snd", "b_use", "res_s0"])
    c = c[(t_send_eff.reindex(c.index) - c.ts_ref) <= analyze.MAX_REF_AGE]
    q_imp = model.implied_q0(c.q_ref, c.p_ref, c.p_snd, c.smt.to_numpy(), c.align0.to_numpy(), c.b_use.to_numpy())
    c = c.assign(impl=q_imp - c.q_ref)
    c["idir"] = np.sign(c.impl)
    c["s"] = c.ts - c.detect
    c["ml_dir"] = np.sign(c.p_snd - c.p_ref)
    c = c[c.dir == -c.idir]
    c["px"] = np.where(c.idir > 0, c.q0, 1 - c.q0)
    return c[(c.px > 0.02) & (c.px < 0.98)]


def asof_keyed(codes_q, t_q, codes_s, t_s, vals, side):
    """Value of the last series point (same code) at or before (side='right') / strictly before ('left')."""
    ks = codes_s.astype(np.float64) * 1e10 + t_s
    o = np.argsort(ks, kind="stable")
    ks, vs, cs = ks[o], vals[o], codes_s[o]
    kq = codes_q.astype(np.float64) * 1e10 + t_q
    i = np.searchsorted(ks, kq, side) - 1
    ok = (i >= 0) & np.isfinite(t_q)
    ii = np.maximum(i, 0)
    ok &= cs[ii] == codes_q
    return np.where(ok, vs[ii], np.nan), np.where(ok, ks[ii] - codes_q.astype(np.float64) * 1e10, np.nan)


# ------------------------------------------------------------------ main
def main():
    R = {}
    pr, iv = analyze.load()
    analyze.CACHE = VER        # lean_maker writes its wf parquet here, not over the lens's copy
    assert (pr.start < OOS_CUT).all()
    months = sorted(m for m in pr.month.unique() if m >= analyze.FIRST_EVAL)
    bwf, _, _ = analyze.sensitivity(iv, sorted(pr.month.unique()))
    sums, _, mchoice = analyze.model_choice(iv, bwf, months)
    pr = analyze.attach_b(pr, bwf, sums, mchoice)

    # ---- 0. reproduce
    rep = analyze.lean_maker(pr, months)
    claimed = json.loads((HERE / "results.json").read_text())["lean_maker"]["wf"]
    R["0_reproduce"] = {"claimed": claimed, "rerun": {k: rep["wf"][k] for k in (
        "n_trades", "mean_pnl_per_share_c", "ci95_pnl_per_share_c", "total_pnl_usd", "sharpe_ann", "max_dd",
        "share_weighted_net_c", "months_positive", "months_total", "best_month_share", "worst_day_pct")},
        "rerun_by_regime": rep["wf_by_regime"], "choices": rep["choices"]}

    # ---- 1. price grid of in-play prints (mid-range)
    def grid_share(x):
        x = x[(x > 0.05) & (x < 0.95)]
        on1 = np.abs(x * 100 - np.round(x * 100)) < 1e-3
        on01 = np.abs(x * 1000 - np.round(x * 1000)) < 1e-2
        return {"n": int(len(x)), "on_1c": float(on1.mean()), "on_0.1c_not_1c": float((on01 & ~on1).mean()),
                "off_grid_vwap": float((~on01).mean())}
    mlp = pq.read_table(ROOT / "data" / "is_prints.parquet", columns=["p"]).column("p").to_numpy()
    R["1_price_grid"] = {"side_markets": grid_share(pr.q0.to_numpy()), "moneyline": grid_share(mlp),
                         "note": "If the tick were 0.001 in play, makers would not cluster ~98% of on-grid prints "
                                 "on whole cents. Polymarket uses a 0.01 tick between 0.04 and 0.96 and switches to "
                                 "0.001 only at extremes; the gamma orderPriceMinTickSize was read after resolution."}
    del mlp

    # ---- base candidate set (identical to the lens) and reproduction through this file's book()
    c0 = lean_candidates(pr, pr.q_rs, pr.ts_rs, pr.p_rs, pr.p_send, pr.b_rs, pr.t_send)
    base_books = cells(c0, months)
    wf0, ch0 = walk_forward(base_books, months)
    R["2_fill_stress"] = {"base (lens fill model)": summ(wf0, "base") | {"choices": ch0}}
    R["2_cells_base"] = {f"{w}/{mi}": summ(b[b.month >= analyze.FIRST_EVAL], f"{w}/{mi}") for (w, mi), b in base_books.items()}

    # off-grid (VWAP) prints: the top level was at least one cent better for the taker
    x = c0.q0.to_numpy()
    offg = np.abs(x * 1000 - np.round(x * 1000)) >= 1e-2
    c0["offgrid"] = offg
    px_vwapfix = np.where(offg, np.ceil(c0.px * 100 - 1e-9) / 100, c0.px)

    stress = {}
    REV.append("stress: VWAP prints to top level")
    stress["vwap_to_top_level"] = (dict(px=pd.Series(px_vwapfix, index=c0.index)), c0)
    for tick in (0.01, 0.001):
        for sh in (0.2, 1.0):
            REV.append(f"stress: step ahead +{tick} share {sh}")
            stress[f"step_ahead_tick{tick}_share{sh}"] = (
                dict(px=pd.Series(px_vwapfix + tick, index=c0.index), share=sh), c0)
    REV.append("stress: no rebate")
    stress["no_rebate"] = (dict(rebate=False), c0)
    for name, (kw, cc) in stress.items():
        bk = {}
        for (w, mi) in GRID:
            f = cc[cc.impl.abs() >= mi]
            if w == "post_jump60":
                f = f[(f.s >= 0) & (f.s <= 60)]
            kk = dict(kw)
            if "px" in kk:
                kk["px"] = kk["px"].reindex(f.index)
            bk[(w, mi)] = book(f, **kk)
        wf, ch = walk_forward(bk, months)
        R["2_fill_stress"][name] = summ(wf, name) | {"choices": ch}

    # back of the queue: bursts (same side market, second, taker side) aggregated; we fill only the burst
    # dollars beyond Q queued ahead of us, at the burst's best (top) level, VWAP-corrected
    cq = c0.assign(px_top=px_vwapfix)
    agg = cq.groupby(["cond", "ts", "at_ask"], sort=False).agg(burst_usd=("usd", "sum"), px_best=("px_top", "max"))
    cq = cq.join(agg, on=["cond", "ts", "at_ask"])
    first = ~cq.duplicated(["cond", "ts", "at_ask"])
    cq = cq[first]
    qbooks = {}
    for Q in (0, 25, 50, 100, 250):
        REV.append(f"stress: back of queue Q={Q}")
        bk = {}
        for (w, mi) in GRID:
            f = cq[cq.impl.abs() >= mi]
            if w == "post_jump60":
                f = f[(f.s >= 0) & (f.s <= 60)]
            bk[(w, mi)] = book(f, px=f.px_best, fill_usd=np.maximum(f.burst_usd - Q, 0.0))
        wf, ch = walk_forward(bk, months)
        qbooks[Q] = wf
        R["2_fill_stress"][f"queue_ahead_Q{Q}_usd"] = summ(wf, f"Q={Q}") | {"choices": ch}

    # ---- 3. latency: extra information lag X seconds (always window; min_impl walk-forward)
    tb = pq.read_table(ROOT / "data" / "is_prints.parquet", columns=["cond", "ts", "p", "dir"])
    ml = tb.to_pandas(strings_to_categorical=True)
    del tb
    ml = ml[ml.cond.isin(set(pr.ml_cond.unique()))]
    ml = ml.sort_values(["cond", "ts"], kind="stable")
    mid = np.empty(len(ml))
    cats = ml.cond.cat.codes.to_numpy()
    tsv, pv, av = ml.ts.to_numpy(), ml.p.to_numpy(), (ml.dir.to_numpy() > 0)
    bounds = np.flatnonzero(np.diff(cats)) + 1
    for a, z in zip(np.r_[0, bounds], np.r_[bounds, len(ml)]):
        mid[a:z] = _mid_series(tsv[a:z], pv[a:z], av[a:z], stale=30)[0]
    code_of = {c: i for i, c in enumerate(ml.cond.cat.categories)}
    mlq = pr.ml_cond.map(code_of).fillna(-1).astype(np.int64).to_numpy()
    mls = cats.astype(np.int64)
    # sanity: recompute p_send at X=0
    p_send0, _ = asof_keyed(mlq, pr.t_send.to_numpy(), mls, tsv, mid, "left")
    okk = np.isfinite(p_send0) & np.isfinite(pr.p_send.to_numpy())
    agree = float(np.mean(np.abs(p_send0[okk] - pr.p_send.to_numpy()[okk]) < 0.005))
    side_codes = pr.cond.astype("category")
    sc = side_codes.cat.codes.to_numpy().astype(np.int64)
    smid = pr.smid.to_numpy()
    sts = pr.ts.to_numpy()
    lag = {"ml_mid_agreement_with_build_at_X0": agree}
    lagged_c = {}
    for X in (0, 2, 5, 10, 30):
        T = pr.t_send.to_numpy() - X
        q_ref, ts_ref = asof_keyed(sc, T, sc, sts, smid, "left")
        p_ref, _ = asof_keyed(mlq, ts_ref, mls, tsv, mid, "right")
        p_snd, _ = asof_keyed(mlq, T, mls, tsv, mid, "left")
        tmp = pr[["cond"]].assign(ts_x=ts_ref)
        tmp = model.attach_local(tmp, sums, "ts_x", "x_")
        nm = pr.month.map(mchoice).fillna("type")
        b_use = pr.b.to_numpy().copy()
        for name in set(nm):
            if name == "type":
                continue
            sel = (nm == name).to_numpy()
            b_use[sel] = model.shrunk_b(pr.b.to_numpy()[sel], tmp.x_sxy.to_numpy()[sel],
                                        tmp.x_sxx.to_numpy()[sel], float(name[5:]))
        cX = lean_candidates(pr, q_ref, ts_ref, p_ref, p_snd, b_use, pd.Series(T, index=pr.index))
        REV.append(f"latency: extra lag {X}s")
        lagged_c[X] = cX
        bk = {("always", mi): book(cX[cX.impl.abs() >= mi]) for mi in analyze.LEAN_MIN_IMPL}
        wf, ch = walk_forward(bk, months)
        fixed = bk[("always", 0.04)]
        lag[f"X={X}s"] = {"wf": summ(wf, f"lag{X}") | {"choices": ch},
                          "fixed_always_4c": summ(fixed[fixed.month >= analyze.FIRST_EVAL], f"lag{X} fixed")}
    R["3_latency_lag"] = lag
    del ml, mid

    # pick-off: did the moneyline reverse between t_send and the print? (base book, chosen cells)
    w0 = wf0.join(c0[["p_snd", "p_now", "ml_dir"]], how="left")
    late = (w0.p_now - w0.p_snd) * w0.ml_dir
    po = {}
    for name, sel in (("ml_reversed_ge_1c", late <= -0.01), ("ml_flat", late.abs() < 0.01),
                      ("ml_continued_ge_1c", late >= 0.01)):
        g = w0[sel]
        po[name] = {"n": int(len(g)), "per_fill_c": float(g.pnl_ps.mean() * 100), "pnl_usd": float(g.pnl.sum()),
                    "share_w_c": float(g.pnl.sum() / g.shares.sum() * 100) if len(g) else np.nan}
    R["3_pickoff_split"] = po

    # ---- 4. edge by print size (fixed always/4c cell, eval months)
    f4 = base_books[("always", 0.04)]
    f4 = f4[f4.month >= analyze.FIRST_EVAL]
    sz = {}
    for lo, hi in ((0, 5), (5, 20), (20, 100), (100, 500), (500, 1e12)):
        g = f4[(f4.usd_print >= lo) & (f4.usd_print < hi)]
        gc = g[g.regime == CUR]
        sz[f"${lo}-{hi:g}"] = {"n": int(len(g)), "per_fill_c": float(g.pnl_ps.mean() * 100), "ci": ci(g)[:2],
                               "pnl_usd": float(g.pnl.sum()), "cur_n": int(len(gc)),
                               "cur_per_fill_c": float(gc.pnl_ps.mean() * 100) if len(gc) else None,
                               "cur_ci": ci(gc)[:2] if len(gc) else None}
    R["4_edge_by_print_usd"] = sz

    # ---- 5. concentration (lens walk-forward book)
    w = wf0
    mo = w.groupby("month").agg(pnl=("pnl", "sum"), n=("pnl", "size"), per_fill_c=("pnl_ps", lambda s: s.mean() * 100))
    bym = w.groupby("cond").pnl.sum().sort_values(ascending=False)
    byw = w.groupby("wallet").agg(pnl=("pnl", "sum"), n=("pnl", "size")).sort_values("pnl", ascending=False)
    byday = w.groupby("date").pnl.sum().sort_values(ascending=False)
    loo = {}
    for m in mo.index:
        g = w[w.month != m]
        loo[m] = {"per_fill_c": float(g.pnl_ps.mean() * 100), "pnl_usd": float(g.pnl.sum())}
    cur = w[w.regime == CUR]
    bymc = cur.groupby("cond").pnl.sum().sort_values(ascending=False)
    curw = cur.groupby("wallet").pnl.sum().sort_values(ascending=False)
    R["5_concentration"] = {
        "monthly": mo.reset_index().to_dict("records"),
        "aug_share_of_pnl": float(mo.pnl.get("2026-08", 0) / w.pnl.sum()),
        "pnl_ex_aug": float(w[w.month != "2026-08"].pnl.sum()),
        "matches": int(len(bym)), "top1_match_pnl": float(bym.iloc[0]), "top10_matches_pnl": float(bym.iloc[:10].sum()),
        "pnl_ex_top10_matches": float(bym.iloc[10:].sum()), "pnl_ex_top20_matches": float(bym.iloc[20:].sum()),
        "top5_days_pnl": float(byday.iloc[:5].sum()), "pnl_ex_top5_days": float(byday.iloc[5:].sum()),
        "counterparty_wallets": int(len(byw)), "top10_wallets_pnl": float(byw.pnl.iloc[:10].sum()),
        "top10_wallets_fills": int(byw.n.iloc[:10].sum()),
        "leave_one_month_out": loo,
        "cur_regime": {"n": int(len(cur)), "matches": int(len(bymc)), "pnl": float(cur.pnl.sum()),
                       "top10_matches_pnl": float(bymc.iloc[:10].sum()),
                       "pnl_ex_top10_matches": float(bymc.iloc[10:].sum()),
                       "top5_wallets_pnl": float(curw.iloc[:5].sum()),
                       "jul_part": summ(cur[cur.month == "2026-07"], "jul 11-31"),
                       "aug_part": summ(cur[cur.month == "2026-08"], "aug 1-25")},
    }

    # ---- 6. multiple testing
    lo_d, hi_d = w.date.min(), w.date.max()
    trial_srs = {}
    for (wn, mi), b in base_books.items():
        bb = b[b.month >= analyze.FIRST_EVAL]
        trial_srs[f"lean {wn}/{mi}"] = daily(bb, lo_d, hi_d)
    # the lens's stale-quote taker cells (hold to resolution) and its symmetric maker cells, same days
    cand = analyze.candidates(pr)
    for k in analyze.K_GRID:
        for mi in analyze.MIN_IMPL_GRID:
            t = analyze.trades(cand, k, mi)
            t = t[t.month >= analyze.FIRST_EVAL]
            if len(t) >= 30:
                bb = analyze.as_book(t, "res")
                trial_srs[f"taker k={k} mi={mi}"] = daily(bb, lo_d, hi_d)
    cm = pr.dropna(subset=["b", "q_rs", "p_rs", "p_send", "res_s0"])
    cm = cm[(cm.t_send - cm.ts_rs) <= analyze.MAX_REF_AGE].copy()
    cm["fair"] = model.implied_q0(cm.q_rs, cm.p_rs, cm.p_send, cm.smt.to_numpy(), cm.align0.to_numpy(), cm.b_rs.to_numpy())
    cm["s"] = cm.ts - cm.detect
    cm = cm[cm.month >= analyze.FIRST_EVAL]
    for win in ("always", "post_jump60"):
        for h in analyze.MK_H:
            x_ = cm if win == "always" else cm[(cm.s >= 0) & (cm.s <= 60)]
            f = x_[(x_.at_ask & (x_.q0 >= x_.fair + h)) | (~x_.at_ask & (x_.q0 <= x_.fair - h))].copy()
            f["idir"] = np.where(~f.at_ask, 1.0, -1.0)
            f["px"] = np.where(f.idir > 0, f.fair - h, 1 - (f.fair + h))
            bb = book(f, px=f.px)
            trial_srs[f"symmaker {win} h={h}"] = daily(bb, lo_d, hi_d)
    srs = pd.Series({k: v.mean() / v.std() for k, v in trial_srs.items() if v.std() > 0})
    d0 = daily(w, lo_d, hi_d)
    T = len(d0)
    sr = d0.mean() / d0.std()
    g3 = float(((d0 - d0.mean()) ** 3).mean() / d0.std(ddof=0) ** 3)
    g4 = float(((d0 - d0.mean()) ** 4).mean() / d0.std(ddof=0) ** 4)
    V = float(srs.var())
    emc = 0.5772156649
    mt = {"daily_sr": float(sr), "ann_sr": float(sr * np.sqrt(365)), "T_days": T, "skew": g3, "kurt": g4,
          "n_trial_srs_used_for_variance": int(len(srs)), "trial_sr_daily_var": V,
          "trial_ann_sr_range": [float(srs.min() * np.sqrt(365)), float(srs.max() * np.sqrt(365))]}
    for N in (68, 100, 200):
        sr0 = np.sqrt(V) * ((1 - emc) * norm.ppf(1 - 1 / N) + emc * norm.ppf(1 - 1 / (N * np.e)))
        z = (sr - sr0) * np.sqrt(T - 1) / np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)
        tstat = sr * np.sqrt(T)
        p1 = 2 * (1 - norm.cdf(tstat))
        pb = min(1.0, p1 * N)
        t_adj = norm.ppf(1 - pb / 2) if pb < 1 else 0.0
        mt[f"N={N}"] = {"sr0_daily": float(sr0), "sr0_ann": float(sr0 * np.sqrt(365)), "DSR_prob": float(norm.cdf(z)),
                        "t_single": float(tstat), "p_single": float(p1), "p_bonferroni": float(pb),
                        "haircut_ann_sr": float(t_adj / np.sqrt(T) * np.sqrt(365))}
    # per-share t-stat in the current regime (cluster SE), Bonferroni critical value
    cur_ci = ci(cur)
    se = cur_ci[2]
    mean_c = cur.pnl_ps.mean() * 100
    for N in (68, 100):
        zc = norm.ppf(1 - 0.025 / N)
        mt[f"cur_per_fill_bonf_lower_N{N}"] = float(mean_c - zc * se)
    curw_ci = ci(cur, w="shares")
    mt["cur_per_fill_t"] = float(mean_c / se)
    mt["cur_share_w_t"] = float((cur.pnl.sum() / cur.shares.sum() * 100) / curw_ci[2])
    # current-regime daily Sharpe and its DSR
    dc = daily(cur)
    src = dc.mean() / dc.std()
    sr0c = np.sqrt(V) * ((1 - emc) * norm.ppf(1 - 1 / 68) + emc * norm.ppf(1 - 1 / (68 * np.e)))
    g3c = float(((dc - dc.mean()) ** 3).mean() / dc.std(ddof=0) ** 3)
    g4c = float(((dc - dc.mean()) ** 4).mean() / dc.std(ddof=0) ** 4)
    zc_ = (src - sr0c) * np.sqrt(len(dc) - 1) / np.sqrt(1 - g3c * src + (g4c - 1) / 4 * src ** 2)
    mt["cur_regime_daily"] = {"days": int(len(dc)), "ann_sr": float(src * np.sqrt(365)), "DSR_prob_N68": float(norm.cdf(zc_)),
                              "positive_days_share": float((dc > 0).mean()), "skew": g3c, "kurt": g4c}
    # the symmetric-maker cells have hugely negative Sharpes and inflate V; recompute with narrower families
    for fam, keys in (("lean_cells_only", [k for k in srs.index if k.startswith("lean")]),
                      ("lean_plus_taker_cells", [k for k in srs.index if not k.startswith("symmaker")])):
        Vf = float(srs[keys].var())
        row = {"n_cells": len(keys), "trial_sr_daily_var": Vf}
        for N in (68, 100):
            sr0 = np.sqrt(Vf) * ((1 - emc) * norm.ppf(1 - 1 / N) + emc * norm.ppf(1 - 1 / (N * np.e)))
            z = (sr - sr0) * np.sqrt(T - 1) / np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)
            zc2 = (src - sr0) * np.sqrt(len(dc) - 1) / np.sqrt(1 - g3c * src + (g4c - 1) / 4 * src ** 2)
            row[f"N={N}"] = {"sr0_ann": float(sr0 * np.sqrt(365)), "DSR_prob_full": float(norm.cdf(z)),
                             "DSR_prob_cur_regime": float(norm.cdf(zc2))}
        mt[f"DSR_{fam}"] = row
    R["6_multiple_testing"] = mt

    # ---- 7. plateau of min_impl (fixed always window; diagnostics, never chosen)
    pl = {}
    for mi in (0.0, 0.005, 0.01, 0.02, 0.03, 0.04, 0.06, 0.08, 0.12):
        REV.append(f"plateau always min_impl={mi}")
        b = book(c0[c0.impl.abs() >= mi])
        b = b[b.month >= analyze.FIRST_EVAL]
        s_ = summ(b, f"always/{mi}")
        pl[str(mi)] = {k: s_.get(k) for k in ("n", "per_fill_c", "share_w_c", "pnl_usd", "cur_n", "cur_per_fill_c",
                                              "cur_per_fill_ci", "cur_share_w_c", "cur_pnl_usd")}
    R["7_plateau_min_impl"] = pl

    # ---- 8. combined conservative current-regime scenario: VWAP fix + 1c step-ahead at 20% share, no rebate
    REV.append("combined: vwap fix + 1c step + no rebate")
    bk = {}
    for (wn, mi) in GRID:
        f = c0[c0.impl.abs() >= mi]
        if wn == "post_jump60":
            f = f[(f.s >= 0) & (f.s <= 60)]
        bk[(wn, mi)] = book(f, px=pd.Series(px_vwapfix + 0.01, index=c0.index).reindex(f.index), rebate=False)
    wf, ch = walk_forward(bk, months)
    R["8_combined_conservative"] = summ(wf, "vwap+1c+no rebate") | {"choices": ch}
    REV.append("combined: vwap fix + back of queue Q=50 + no rebate")
    bk = {}
    for (wn, mi) in GRID:
        f = cq[cq.impl.abs() >= mi]
        if wn == "post_jump60":
            f = f[(f.s >= 0) & (f.s <= 60)]
        bk[(wn, mi)] = book(f, px=f.px_best, fill_usd=np.maximum(f.burst_usd - 50, 0.0), rebate=False)
    wf, ch = walk_forward(bk, months)
    R["8_combined_queue50"] = summ(wf, "vwap+Q50+no rebate") | {"choices": ch}

    # ---- 8b. 2 s extra information lag on top of the execution adjustments (always window, wf min_impl)
    cX = lagged_c[2].copy()
    xx = cX.q0.to_numpy()
    offx = np.abs(xx * 1000 - np.round(xx * 1000)) >= 1e-2
    cX["px_top"] = np.where(offx, np.ceil(cX.px * 100 - 1e-9) / 100, cX.px)
    REV.append("combined: lag2s + vwap fix + 1c step + no rebate")
    bk = {("always", mi): book(cX[cX.impl.abs() >= mi], px=cX.px_top[cX.impl.abs() >= mi] + 0.01, rebate=False)
          for mi in analyze.LEAN_MIN_IMPL}
    wf, ch = walk_forward(bk, months)
    R["8b_lag2_vwap_1c_norebate"] = summ(wf, "lag2+vwap+1c+no rebate") | {"choices": ch}
    agg2 = cX.groupby(["cond", "ts", "at_ask"], sort=False).agg(burst_usd=("usd", "sum"), px_best=("px_top", "max"))
    cX2 = cX.join(agg2, on=["cond", "ts", "at_ask"])
    cX2 = cX2[~cX2.duplicated(["cond", "ts", "at_ask"])]
    REV.append("combined: lag2s + vwap fix + Q50 + no rebate")
    bk = {}
    for mi in analyze.LEAN_MIN_IMPL:
        f = cX2[cX2.impl.abs() >= mi]
        bk[("always", mi)] = book(f, px=f.px_best, fill_usd=np.maximum(f.burst_usd - 50, 0.0), rebate=False)
    wf, ch = walk_forward(bk, months)
    R["8b_lag2_vwap_Q50_norebate"] = summ(wf, "lag2+vwap+Q50+no rebate") | {"choices": ch}
    cbq = wf[wf.regime == CUR].groupby("cond").pnl.sum().sort_values(ascending=False)
    R["8b_lag2_vwap_Q50_norebate"]["cur_pnl_ex_top10_matches"] = float(cbq.iloc[10:].sum())

    # ---- 9. who pays? counterparty concentration of the base and back-of-queue books (current regime);
    # wallets ranked by the NOTIONAL we filled against them (not by P&L, which would bias the drop test)
    conc = {}
    for name, bk_ in (("base", wf0), ("Q50", qbooks[50]), ("Q0", qbooks[0])):
        cb = bk_[bk_.regime == CUR]
        wn = cb.groupby("wallet").agg(usd=("usd_in", "sum"), pnl=("pnl", "sum"), n=("pnl", "size"),
                                      matches=("cond", "nunique")).sort_values("usd", ascending=False)
        top = wn.head(5)
        allw = bk_.groupby("wallet").agg(months=("month", "nunique"))
        row = {"fills": int(len(cb)), "wallets": int(len(wn)), "pnl": float(cb.pnl.sum()),
               "top5_by_notional": [{"wallet": w_[:10], "usd": float(r.usd), "pnl": float(r.pnl), "fills": int(r.n),
                                     "matches": int(r.matches), "months_active_in_book": int(allw.months.get(w_, 0))}
                                    for w_, r in top.iterrows()],
               "top5_share_of_notional": float(top.usd.sum() / wn.usd.sum())}
        for k in (1, 5, 10):
            drop = set(wn.index[:k])
            g = cb[~cb.wallet.isin(drop)]
            row[f"ex_top{k}_wallets"] = {"n": int(len(g)), "per_fill_c": float(g.pnl_ps.mean() * 100),
                                          "per_fill_ci": ci(g)[:2], "share_w_c": float(g.pnl.sum() / g.shares.sum() * 100),
                                          "pnl_usd": float(g.pnl.sum())}
        bymm = cb.groupby("cond").pnl.sum().sort_values(ascending=False)
        row["top10_matches_pnl"] = float(bymm.iloc[:10].sum())
        row["pnl_ex_top10_matches"] = float(bymm.iloc[10:].sum())
        conc[name] = row
    R["9_counterparty_concentration_cur"] = conc

    R["reviewer_variants"] = REV
    R["n_reviewer_variants"] = len(REV)
    (HERE / "verify_realism.json").write_text(json.dumps(R, indent=1, default=float))

    # ---- printed summary
    def line(s):
        return (f"{s['label']:<34} n={s.get('n', 0):>6} fill={s.get('per_fill_c', np.nan):6.2f}c "
                f"shw={s.get('share_w_c', np.nan):6.2f}c ${s.get('pnl_usd', 0):>8.0f} | 1s5%: "
                f"fill={s.get('cur_per_fill_c', np.nan):6.2f}c {np.round(s.get('cur_per_fill_ci', [np.nan] * 2), 2)} "
                f"shw={s.get('cur_share_w_c', np.nan):6.2f}c ${s.get('cur_pnl_usd', 0):>7.0f} "
                f"not/30d=${s.get('cur_notional_per_30d', 0):>7.0f}")
    print("REPRODUCE", json.dumps(R["0_reproduce"]["rerun"], default=float))
    print("GRID", json.dumps(R["1_price_grid"], default=float))
    for k, s in R["2_fill_stress"].items():
        print(line(s))
    print("LAG agreement", lag["ml_mid_agreement_with_build_at_X0"])
    for X in (0, 2, 5, 10, 30):
        print(line(lag[f"X={X}s"]["wf"]))
    print("PICKOFF", json.dumps(po, default=float))
    print("SIZE", json.dumps(sz, default=float))
    print("CONC", json.dumps({k: v for k, v in R["5_concentration"].items() if k not in ("monthly",)}, default=float)[:3000])
    print("MT", json.dumps(mt, default=float))
    print("PLATEAU", json.dumps(pl, default=float))
    print(line(R["8_combined_conservative"]))
    print(line(R["8_combined_queue50"]))
    print(line(R["8b_lag2_vwap_1c_norebate"]))
    print(line(R["8b_lag2_vwap_Q50_norebate"]), R["8b_lag2_vwap_Q50_norebate"]["cur_pnl_ex_top10_matches"])
    print("N reviewer variants", len(REV))
    print("DSR", json.dumps({k: v for k, v in mt.items() if k.startswith("DSR_")}, default=float))
    print("CONC9", json.dumps(conc, default=float))


if __name__ == "__main__":
    main()
