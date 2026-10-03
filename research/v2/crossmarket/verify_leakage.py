"""Adversarial review of the crossmarket lens: leakage / OOS checks + independent recomputation of the
leaning-maker headline (+2.73c/share walk-forward, 8,905 fills, $4,162; 1s/5% +2.02c).

Written by the reviewer; does not import analyze.py or model.py (re-implements the rules from the
RESULTS.md text). Reads only IS files: universe_is, side_markets/side_prints (data/v2_crossmarket),
raw side tapes for a random IS sample, raw moneyline tapes for the same sample.
Run: .venv/bin/python research/v2/crossmarket/verify_leakage.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.tape import load_tape  # noqa: E402

LENS = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "v2_crossmarket"
CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")
PLAYER = ("tennis_first_set_winner", "tennis_set_winner", "tennis_set_handicap", "tennis_game_handicap")
OUT = {}


def logit(x):
    x = np.clip(x, 0.005, 0.995)
    return np.log(x / (1 - x))


def mid_series(ts, p, at_ask, stale):
    """Own mid proxy: mean of last bid-side and ask-side prints (<= stale s), else the print."""
    n = len(ts)
    out = np.empty(n)
    lb = la = None
    tb = ta = -1e18
    for i in range(n):
        if at_ask[i]:
            la, ta = p[i], ts[i]
        else:
            lb, tb = p[i], ts[i]
        b = lb if (lb is not None and ts[i] - tb <= stale) else None
        a = la if (la is not None and ts[i] - ta <= stale) else None
        out[i] = (a + b) / 2 if (a is not None and b is not None and a >= b) else p[i]
    return out


# ------------------------------------------------------------------ 1. OOS / locked guards
def guards(pr):
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["event_id", "start", "cond"])
    sm = pd.read_parquet(CACHE / "side_markets.parquet", columns=["event_id", "start", "cond"])
    src_txt = "\n".join(p.read_text() for p in LENS.glob("*.py") if p.name != "verify_leakage.py")
    g = {
        "universe_is_max_start": str(u.start.max()),
        "side_markets_max_start": str(sm.start.max()),
        "side_prints_max_start": str(pr.start.max()),
        "side_prints_events_not_in_universe_is": int((~pr.event_id.astype(str).isin(u.event_id.astype(str))).sum()),
        "side_prints_start_ge_cut": int((pr.start >= CUT).sum()),
        "lens_code_mentions_data_locked": bool(re.search(r"data[/\"' ,]+locked", src_txt)),
        "lens_code_reads_live": bool(re.search(r"data[/\"' ,]+live", src_txt)),
        "ts_rs_not_before_send": int((pr.ts_rs >= pr.t_send).sum()),
        "detect_after_send_minus_1": int((pr.detect > pr.t_send - 1).sum()),
    }
    OUT["guards"] = g
    print("guards", json.dumps(g, indent=1))


# ------------------------------------------------------------------ 2. spot-check build.py from raw tapes
def spot_check(pr, n=300, seed=7):
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["cond", "start", "end"]).set_index("cond")
    rng = np.random.default_rng(seed)
    samp = pr.iloc[rng.choice(len(pr), n, replace=False)]
    bad = {"q_rs": 0, "p_send": 0, "p_rs": 0, "q0": 0, "dir": 0}
    checked = 0
    for cond, g in samp.groupby("cond"):
        side = pd.read_parquet(CACHE / "trades" / f"{cond}.parquet")
        mlc = g.ml_cond.iloc[0]
        ml = load_tape(mlc)
        r = u.loc[mlc]
        s0 = int(r.start.timestamp())
        e0 = int(r.end.timestamp()) if pd.notna(r.end) else s0 + 6 * 3600
        side = side[(side.timestamp >= s0) & (side.timestamp <= e0)].sort_values("timestamp", kind="stable").reset_index(drop=True)
        ml = ml[(ml.timestamp >= s0) & (ml.timestamp <= e0)].reset_index(drop=True)
        q0 = np.where(side.outcomeIndex == 0, side.price, 1 - side.price)
        aa = (((side.side == "BUY") & (side.outcomeIndex == 0)) | ((side.side == "SELL") & (side.outcomeIndex == 1))).to_numpy()
        sts = side.timestamp.to_numpy().astype(float)
        smid = mid_series(sts, q0, aa, 120)
        mts = ml.timestamp.to_numpy().astype(float)
        mmid = mid_series(mts, ml.p0.to_numpy(), ml.at_ask.to_numpy(), 30)
        for _, row in g.iterrows():
            t_send = row.ts - row.delay
            jr = np.flatnonzero(sts < t_send)
            q_rs = smid[jr[-1]] if len(jr) else np.nan
            ts_rs = sts[jr[-1]] if len(jr) else np.nan
            im = np.flatnonzero(mts < t_send)
            p_send = mmid[im[-1]] if len(im) else np.nan
            ir = np.flatnonzero(mts <= ts_rs) if np.isfinite(ts_rs) else []
            p_rs = mmid[ir[-1]] if len(ir) else np.nan
            # the print itself: some raw print at that ts with the same q0 / direction
            hit = (sts == row.ts) & np.isclose(q0, row.q0) & (aa == row.at_ask)
            bad["q0"] += int(not hit.any())
            for k, v in (("q_rs", q_rs), ("p_send", p_send), ("p_rs", p_rs)):
                sv = row[k]
                if not ((np.isnan(v) and np.isnan(sv)) or np.isclose(v, sv, atol=1e-9)):
                    bad[k] += 1
            checked += 1
    OUT["spot_check"] = {"checked": checked, "mismatches": bad}
    print("spot check", OUT["spot_check"])


# ------------------------------------------------------------------ 3. independent lean-maker recomputation
def intervals_from_prints(pr):
    """Rebuild the beta sample from side_prints (consecutive in-play prints <= 300 s apart)."""
    d = pr[["cond", "ts", "smid", "p_now", "smt", "align0"]].copy()
    d["ord"] = np.arange(len(d))
    d = d.sort_values(["cond", "ts", "ord"], kind="stable")
    prev = d.groupby("cond").shift(1)
    iv = pd.DataFrame({"cond": d.cond, "ts": d.ts, "dt": d.ts - prev.ts, "m1": prev.smid, "m2": d.smid,
                       "p1": prev.p_now, "p2": d.p_now, "smt": d.smt, "align0": d.align0})
    iv = iv[iv.dt.notna() & (iv.dt <= 300)].copy()
    pl = iv.smt.isin(PLAYER).to_numpy()
    flip = pl & (iv.align0.to_numpy() == -1)
    m1 = np.where(flip, 1 - iv.m1, iv.m1)
    m2 = np.where(flip, 1 - iv.m2, iv.m2)
    close = lambda p: 4 * p * (1 - p)  # noqa: E731
    x = np.where(pl, logit(iv.p2) - logit(iv.p1), close(iv.p2) - close(iv.p1))
    y = logit(m2) - logit(m1)
    ok = ((m1 > .03) & (m1 < .97) & (m2 > .03) & (m2 < .97) & (iv.p1 > .03) & (iv.p1 < .97)
          & (iv.p2 > .03) & (iv.p2 < .97) & np.isfinite(x) & np.isfinite(y) & ~(pl & (iv.align0 == 0)))
    iv["x"] = np.where(ok, x, np.nan)
    iv["y"] = np.where(ok, y, np.nan)
    iv["month"] = pd.to_datetime(iv.ts, unit="s").dt.to_period("M").astype(str)
    return iv


def wf_type_b(iv, months):
    rows = []
    v = iv.dropna(subset=["x", "y"])
    for m in months:
        past = v[v.month < m]
        for smt, g in past.groupby("smt"):
            if len(g) >= 200 and (g.x ** 2).sum() > 0:
                rows.append((m, smt, float((g.x * g.y).sum() / (g.x ** 2).sum())))
    return pd.DataFrame(rows, columns=["month", "smt", "b"])


def cum_local(iv):
    v = iv[["cond", "ts", "x", "y"]].copy()
    ok = v.x.notna() & v.y.notna()
    v["sxy"] = np.where(ok, v.x * v.y, 0.0)
    v["sxx"] = np.where(ok, v.x ** 2, 0.0)
    v = v.sort_values(["cond", "ts"], kind="stable")
    v[["sxy", "sxx"]] = v.groupby("cond")[["sxy", "sxx"]].cumsum()
    return v.groupby(["cond", "ts"], as_index=False)[["sxy", "sxx"]].last()


def asof(df, sums, col):
    left = df[["cond", col]].reset_index().rename(columns={col: "ts"}).dropna(subset=["ts"]).sort_values("ts")
    r = pd.merge_asof(left, sums.sort_values("ts"), on="ts", by="cond", direction="backward").set_index("index")
    return r.sxy.reindex(df.index).fillna(0.0).to_numpy(), r.sxx.reindex(df.index).fillna(0.0).to_numpy()


def boot(pnl_ps, clusters, w=None, n=2000, seed=0):
    w = np.ones(len(pnl_ps)) if w is None else w
    g = pd.DataFrame({"s": pnl_ps * w, "n": w, "c": clusters}).groupby("c").sum()
    s, k = g.s.to_numpy(), g.n.to_numpy()
    rng = np.random.default_rng(seed)
    bs = [s[i].sum() / k[i].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(n))]
    return [float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)]


def summ(b, label):
    if len(b) == 0:
        return {"label": label, "n": 0}
    r = {"label": label, "n": int(len(b)), "matches": int(b.event_id.nunique()),
         "mean_c": float(b.pnl_ps.mean() * 100), "ci": boot(b.pnl_ps.to_numpy(), b.event_id.to_numpy()),
         "share_w_c": float(b.pnl.sum() / b.sh.sum() * 100), "pnl_usd": float(b.pnl.sum()),
         "usd_in": float(b.usd.sum()), "months_pos_usd": int((b.groupby("month").pnl.sum() > 0).sum()),
         "months_pos_ps": int((b.groupby("month").pnl_ps.mean() > 0).sum()), "months": int(b.month.nunique())}
    return r


def lean_books(c, mi_grid=(0.01, 0.02, 0.04), share=0.2, max_fill=250, max_match=2000, extra=None):
    books = {}
    base = c[c.dir == -c.idir].copy()
    base["px"] = np.where(base.idir > 0, base.q0, 1 - base.q0)
    base = base[(base.px > 0.02) & (base.px < 0.98)]
    if extra is not None:
        base = extra(base)
    for win in ("always", "post_jump60"):
        for mi in mi_grid:
            f = base[base.impl.abs() >= mi]
            if win == "post_jump60":
                f = f[(f.s >= 0) & (f.s <= 60)]
            f = f.sort_values("ts", kind="stable").copy()
            f["sh"] = np.minimum(share * f["size"], max_fill / f.px)
            f["usd"] = f.sh * f.px
            f = f[f.groupby("event_id").usd.cumsum() <= max_match].copy()
            pay = np.where(f.idir > 0, f.res_s0, 1 - f.res_s0)
            f["pnl_ps"] = pay - f.px + 0.15 * f.fee_rate * f.q0 * (1 - f.q0)
            f["pnl"] = f.sh * f.pnl_ps
            books[(win, mi)] = f
    return books


def walk_forward(books, months):
    parts, picks = [], []
    for m in months:
        best, bp = None, -np.inf
        for k, b in books.items():
            past = b[b.month < m]
            if len(past) >= 30 and past.pnl.sum() > bp:
                best, bp = k, past.pnl.sum()
        if best is None:
            continue
        picks.append((m, best))
        parts.append(books[best][books[best].month == m])
    return (pd.concat(parts) if parts else pd.DataFrame()), picks


def main():
    cols = ["cond", "ml_cond", "ts", "q0", "at_ask", "size", "usd", "smid", "p_now", "t_send", "detect", "q_rs",
            "ts_rs", "p_rs", "p_send", "smt", "align0", "fee_rate", "delay", "res_s0", "event_id", "start"]
    pr = pd.read_parquet(CACHE / "side_prints.parquet", columns=cols)
    assert (pr.start < CUT).all()
    guards(pr)
    spot_check(pr)
    pr["month"] = pd.to_datetime(pr.ts, unit="s").dt.to_period("M").astype(str)
    pr["dir"] = np.where(pr.at_ask, 1.0, -1.0)
    pr["regime"] = pr.delay.astype(int).astype(str) + "s/" + (pr.fee_rate * 100).round().astype(int).astype(str) + "%"
    months_all = sorted(pr.month.unique())
    evm = [m for m in months_all if m >= "2026-02"]

    iv = intervals_from_prints(pr)
    OUT["intervals_rebuilt"] = int(len(iv))
    bwf = wf_type_b(iv, months_all)
    sums = cum_local(iv)
    # model choice: pooled predictive R^2 (vs zero) of type b vs local shrink, months < m
    ivc = iv.merge(bwf, on=["month", "smt"], how="left").dropna(subset=["x", "y", "b"])
    ivc["ts_start"] = ivc.ts - ivc.dt
    ivc = ivc.reset_index(drop=True)
    sxy, sxx = asof(ivc, sums, "ts_start")
    names = {"type": None, "local0.05": 0.05, "local0.25": 0.25, "local1.0": 1.0}
    r2 = []
    for m, g in ivc.groupby("month"):
        row = {"month": m, "n": len(g)}
        for nm, lam in names.items():
            b = g.b.to_numpy() if lam is None else (sxy[g.index] + lam * g.b.to_numpy()) / (sxx[g.index] + lam)
            row[nm] = 1 - ((g.y - b * g.x) ** 2).sum() / (g.y ** 2).sum()
        r2.append(row)
    r2 = pd.DataFrame(r2)
    choice = {}
    for m in evm:
        past = r2[r2.month < m]
        choice[m] = "type" if past.empty else max(names, key=lambda nm: float((past[nm] * past.n / past.n.sum()).sum()))
    OUT["beta_model_choice"] = choice

    c = pr.merge(bwf, on=["month", "smt"], how="left").dropna(subset=["b", "q_rs", "p_rs", "p_send", "res_s0"])
    c = c[(c.t_send - c.ts_rs) <= 600].reset_index(drop=True)
    rs_sxy, rs_sxx = asof(c, sums, "ts_rs")
    lam = c.month.map(choice).map(names)
    lamv = lam.fillna(-1).to_numpy()
    b_loc = np.where(lamv > 0, (rs_sxy + np.where(lamv > 0, lamv, 0) * c.b) / (rs_sxx + np.where(lamv > 0, lamv, 1)), c.b)
    c["b_use"] = b_loc

    def implied(c, b):
        pl = c.smt.isin(PLAYER).to_numpy()
        flip = pl & (c.align0.to_numpy() == -1)
        qa = np.where(flip, 1 - c.q_rs, c.q_rs)
        close = lambda p: 4 * p * (1 - p)  # noqa: E731
        dx = np.where(pl, logit(c.p_send) - logit(c.p_rs), close(c.p_send) - close(c.p_rs))
        qn = 1 / (1 + np.exp(-(logit(qa) + b * dx)))
        return np.where(flip, 1 - qn, qn) - c.q_rs.to_numpy()

    c["impl"] = implied(c, c.b_use.to_numpy())
    c["idir"] = np.sign(c.impl)
    c["s"] = c.ts - c.detect

    books = lean_books(c)
    wf, picks = walk_forward(books, evm)
    head = summ(wf, "reviewer re-implementation, walk-forward (should match 2.73c / 8,905 / $4,162)")
    head["picks"] = [(m, list(k)) for m, k in picks]
    head["by_regime"] = {rg: summ(g, rg) for rg, g in wf.groupby("regime")}
    OUT["headline_recomputed"] = head
    print(json.dumps(head, indent=1, default=str))

    # ---- sensitivity / bias probes (same walk-forward machinery unless noted)
    probes = {}
    def run(label, **kw):
        bk = lean_books(c, **kw)
        w, pk = walk_forward(bk, evm)
        s = summ(w, label)
        s["by_regime_1s5"] = summ(w[w.regime == "1s/5%"], "1s/5%")
        probes[label] = s

    run("exclude 50-50 (void) resolutions", extra=lambda f: f[f.res_s0.isin([0.0, 1.0])])
    run("px in [0.10, 0.90] only", extra=lambda f: f[(f.px >= 0.10) & (f.px <= 0.90)])
    run("drop fills with px > 0.90 (near-decided side)", extra=lambda f: f[f.px <= 0.90])
    run("only fills >= 10 s after the side reference print", extra=lambda f: f[(f.ts - f.ts_rs) >= 10])
    run("fill one tick worse (px + 0.01)", extra=lambda f: f.assign(px=f.px + 0.01))
    run("fill two ticks worse (px + 0.02)", extra=lambda f: f.assign(px=f.px + 0.02))
    run("only prints >= $20 (min-order-size realism)", extra=lambda f: f[f.usd >= 20])
    # type-level b only (no local shrink)
    c2 = c.copy()
    c2["impl"] = implied(c2, c2.b.to_numpy())
    c2["idir"] = np.sign(c2.impl)
    bk = lean_books(c2)
    w2, _ = walk_forward(bk, evm)
    probes["type-level b only"] = summ(w2, "type-level b only")
    # fixed rule always/4c over all eval months and per regime (no selection)
    fx = books[("always", 0.04)]
    fx = fx[fx.month >= "2026-02"]
    probes["fixed always/4c, Feb-Aug"] = summ(fx, "fixed always/4c")
    probes["fixed always/4c, 1s/5%"] = summ(fx[fx.regime == "1s/5%"], "fixed always/4c 1s/5%")
    # P&L by price bucket in the walk-forward book
    wf["pxb"] = pd.cut(wf.px, [0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0])
    probes["wf_by_px_bucket"] = {str(k): {"n": int(len(g)), "mean_c": float(g.pnl_ps.mean() * 100),
                                          "pnl_usd": float(g.pnl.sum())} for k, g in wf.groupby("pxb", observed=True)}
    probes["wf_res_0.5_share"] = {"n": int((wf.res_s0 == 0.5).sum()), "pnl_usd": float(wf.loc[wf.res_s0 == 0.5, "pnl"].sum())}
    # concentration: P&L of the top 10 matches
    em = wf.groupby("event_id").pnl.sum().sort_values()
    probes["concentration"] = {"top10_matches_usd": float(em.tail(10).sum()), "bottom10_usd": float(em.head(10).sum()),
                               "total": float(em.sum()), "aug_usd": float(wf[wf.month == "2026-08"].pnl.sum())}
    # sweep / same-second clusters: the fill model gives us 20% of EVERY contrary print, each at its own
    # price, including deeper levels of one taker sweep. A single resting quote at the touch would fill
    # once, at the touch (the worst price for us in the cluster). Re-price each (market, second) cluster
    # at its worst px for us and keep one fill of the cluster's total size share.
    cl = wf.groupby(["cond", "ts"])
    probes["same_second_clusters"] = {"fills": int(len(wf)), "clusters": int(cl.ngroups),
                                      "fills_in_multi_print_clusters": int((cl.px.transform("size") > 1).sum())}
    w3 = wf.assign(px_touch=cl.px.transform("max"))
    pay = np.where(w3.idir > 0, w3.res_s0, 1 - w3.res_s0)
    w3["pnl_ps"] = pay - w3.px_touch + 0.15 * w3.fee_rate * w3.q0 * (1 - w3.q0)
    w3["pnl"] = w3.sh * w3.pnl_ps
    probes["wf repriced at cluster touch"] = summ(w3, "wf, every fill repriced at the touch of its same-second cluster")
    probes["wf repriced at cluster touch, 1s/5%"] = summ(w3[w3.regime == "1s/5%"], "1s/5%")
    # contribution by how far the print traded through the prior side mid (in the implied direction)
    wf["thru"] = (wf.q_rs - wf.q0) * wf.idir   # >0: print traded below (bid case) the prior mid
    wf["thrub"] = pd.cut(wf.thru, [-1, -0.02, 0, 0.02, 0.05, 1])
    probes["wf_by_trade_through_prior_mid"] = {str(k): {"n": int(len(g)), "mean_c": float(g.pnl_ps.mean() * 100),
                                                        "pnl_usd": float(g.pnl.sum())}
                                               for k, g in wf.groupby("thrub", observed=True)}
    # share-weighted (what a book actually earns per share) CIs and match-cluster bootstrap of total $
    def dollar_ci(b, n=2000, seed=0):
        g = b.groupby("event_id").pnl.sum().to_numpy()
        rng = np.random.default_rng(seed)
        bs = [g[rng.integers(0, len(g), len(g))].sum() for _ in range(n)]
        return [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
    for lab, b in (("all", wf), ("1s/5%", wf[wf.regime == "1s/5%"])):
        probes[f"share_weighted_ci_{lab}"] = {
            "share_w_c": float(b.pnl.sum() / b.sh.sum() * 100),
            "ci": boot(b.pnl_ps.to_numpy(), b.event_id.to_numpy(), w=b.sh.to_numpy()),
            "total_usd": float(b.pnl.sum()), "total_usd_ci": dollar_ci(b)}
    # 1s/5% by month
    probes["wf_1s5_by_month"] = {m: summ(g, m) for m, g in wf[wf.regime == "1s/5%"].groupby("month")}
    OUT["probes"] = probes
    print(json.dumps(probes, indent=1, default=str))
    (LENS / "verify_leakage.json").write_text(json.dumps(OUT, indent=1, default=str))


if __name__ == "__main__":
    main()
