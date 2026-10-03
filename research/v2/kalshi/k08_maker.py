"""Step 8 (variant family): the PASSIVE laggard trade -- quote Polymarket using Kalshi as the fair-value oracle.

Polymarket holds marketable orders for D s while makers cancel instantly. A maker that cancels whenever Kalshi
has moved against its quote is only filled by takers whose price is still on the right side of Kalshi's fair
value as of the cancel deadline. We infer such fills from the Polymarket taker tape:

  for every Polymarket taker print (block ts t, price p, taker direction dir):
     kf   = Kalshi mid using Kalshi prints <= t - B - c   (B = 2 s block allowance, c = 0.3 s cancel latency)
     edge = dir * (p - kf)   (> 0: the taker paid more than Kalshi's fair value, i.e. we would sell to them rich)
     we are the counterparty only if edge >= h  (quote rule: never quote through Kalshi fair +- h)
     maker P&L/share at horizon H = dir * (p - mid_H) + rebate,  rebate = 0.15 * rate * p(1-p)
     (mid_H = Polymarket mid at t + H; also reported vs Kalshi mid and vs resolution)
     hedged maker: immediately take the same side as the PM taker on Kalshi (first Kalshi print on that side at
     ts >= t + off, off = -1 s base: we learn of the fill ~1 s before its block timestamp; +0.25 / -1.75 tested):
     dir*(p - hk) + dir*(k_settle0 - res0) + rebate - 0.07 hk(1-hk)   (locked at entry up to settlement basis)
  quote-price model ('qb_*', more conservative on price): we rest at kf +- h, i.e. strictly at or better than
     the observed touch, so the taker would have filled US first at our price kf + dir*h (not at p):
     P&L = dir*(kf - mid_H) + h + rebate(kf); hedged: dir*(kf - hk) + h + basis + rebate - Kalshi taker fee
  participation: 25% of each qualifying print's shares (queue priority NOT modelled -> optimistic), <= $250/print

Walk-forward: h in {none, 0, 0.5, 1, 2, 3} c chosen on months < m by training mean per-share P&L of the
exit being evaluated, applied to month m; if no h has a positive training mean the strategy stands aside. Fee: current 5% for
the rebate in the 'cur' variant, per-match rate otherwise.
Run: .venv/bin/python research/v2/kalshi/k08_maker.py
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from k_common import CACHE, OUT, load_k, load_matched, load_pm, mid_at, mid_grid, window  # noqa: E402
from src.backtest import stats  # noqa: E402

B, C = 2.0, 0.3
HS_ = [0.0, 0.005, 0.01, 0.02, 0.03]
PART, CAP = 0.25, 250.0
HEDGE_OFFS = {"m1": -1.0, "p025": 0.25, "m175": -1.75}  # hedge send time relative to the PM block timestamp


def one(row):
    pm, k = load_pm(row), load_k(row)
    if pm is None or k is None or len(pm) < 20 or len(k) < 20:
        return None
    s, e = window(row)
    grid = np.arange(int(s), int(e) + 400, dtype=float)
    mp, _, _ = mid_grid(pm.ts.values, pm.p.values, pm.ask.values, grid)
    t = pm.ts.values
    kf = mid_at(k.ts.values, k.p.values, k.ask.values, t - B - C)
    out = {"cond": row.cond, "ts": t, "p": pm.p.values, "dir": np.where(pm.ask.values, 1.0, -1.0),
           "q": pm.q.values, "kf": kf}
    for b in (0, 1):  # block-allowance sensitivity for the cancel deadline (B = 0 / 1 s instead of 2 s)
        out[f"kf_b{b}"] = mid_at(k.ts.values, k.p.values, k.ask.values, t - b - C)
    for H in (30, 60):
        i = (t + H - grid[0]).astype(int)
        ok = (i < len(grid)) & (t + H <= e)
        out[f"pm{H}"] = np.where(ok, mp[np.minimum(i, len(grid) - 1)], np.nan)
        out[f"k{H}"] = np.where(ok, mid_at(k.ts.values, k.p.values, k.ask.values, t + H), np.nan)
    # cross-venue hedge of each maker fill on Kalshi (taker): if the PM taker bought outcome 0 (dir=+1) we sold
    # it, so we lift Kalshi's outcome-0 ask; first same-side Kalshi print with ts >= t + off, within 3 s.
    kts, kp, kask = k.ts.values, k.p.values, k.ask.values
    for name, off in HEDGE_OFFS.items():
        hp = np.full(len(t), np.nan)
        for side, dsel in ((True, 1.0), (False, -1.0)):
            sel = out["dir"] == dsel
            ts_s, p_s = kts[kask == side], kp[kask == side]
            if not len(ts_s) or not sel.any():
                continue
            j = np.searchsorted(ts_s, t[sel] + off, "left")
            okj = j < len(ts_s)
            jj = np.minimum(j, len(ts_s) - 1)
            v = np.where(okj & (ts_s[jj] <= t[sel] + off + 3), p_s[jj], np.nan)
            # touch proxy when nobody printed on that side within 3 s: last (<= 5 s old) print on the other
            # side +- 2c (conservative 2c spread), same rule as k05.touch_proxy
            to, po = kts[kask != side], kp[kask != side]
            if len(to):
                io = np.searchsorted(to, t[sel] + off, "right") - 1
                okp = (io >= 0) & ((t[sel] + off) - to[np.maximum(io, 0)] <= 5)
                prox = np.where(okp, po[np.maximum(io, 0)] + dsel * 0.02, np.nan)
                v = np.where(np.isfinite(v), v, prox)
            hp[sel] = v
        out[f"hk_{name}"] = hp
    df = pd.DataFrame(out)
    df = df[np.isfinite(df.kf) & df.p.between(0.05, 0.95)]
    for c in df.columns:
        if df[c].dtype == np.float64 and c not in ("ts",):
            df[c] = df[c].astype(np.float32)
    df["month"], df["fee_rate"], df["delay"], df["res0"] = row.month, row.fee_rate, row.delay, row.res0
    df["k_settle0"] = row.k_settle0
    return df


def build() -> pd.DataFrame:
    f = CACHE / "maker_prints.parquet"
    if f.exists():
        return pd.read_parquet(f)
    m = load_matched()
    rows = [SimpleNamespace(**r) for r in m.to_dict("records")]
    with ProcessPoolExecutor(2) as ex:
        parts = [d for d in ex.map(one, rows, chunksize=8) if d is not None]
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(f)
    return df


def pnl(df: pd.DataFrame, cur: bool) -> pd.DataFrame:
    rate = 0.05 if cur else df.fee_rate.to_numpy()
    p, d = df.p.to_numpy(np.float64), df.dir.to_numpy(np.float64)
    reb = 0.15 * rate * p * (1 - p)
    x = df[["cond", "ts", "month", "fee_rate", "delay"]].copy()
    x["edge"] = d * (p - df.kf.to_numpy())
    x["ps_pm60"] = d * (p - df.pm60.to_numpy()) + reb
    x["ps_pm30"] = d * (p - df.pm30.to_numpy()) + reb
    x["ps_k60"] = d * (p - df.k60.to_numpy()) + reb
    res = df.res0.to_numpy()
    x["ps_res"] = np.where(np.isin(res, [0.0, 1.0]), d * (p - res) + reb, np.nan)
    for name in HEDGE_OFFS:
        hk = df[f"hk_{name}"].to_numpy(np.float64)
        x[f"ps_hedge_{name}"] = (d * (p - hk) + d * (df.k_settle0.to_numpy() - res) + reb
                                 - 0.07 * hk * (1 - hk))
    # quote-price model ('qb_' columns): we rest at kf +- h (price priority over the observed touch), so a
    # qualifying taker print fills us at OUR price kf + dir*h, not at the print price. P&L = qb_col + h.
    kf = df.kf.to_numpy(np.float64)
    reb_q = 0.15 * rate * kf * (1 - kf)
    x["qb_pm60"] = d * (kf - df.pm60.to_numpy()) + reb_q
    x["qb_k60"] = d * (kf - df.k60.to_numpy()) + reb_q
    hk = df["hk_m1"].to_numpy(np.float64)
    x["qb_hedge_m1"] = d * (kf - hk) + d * (df.k_settle0.to_numpy() - res) + reb_q - 0.07 * hk * (1 - hk)
    x["fee"] = -reb
    x["shares"] = np.minimum(PART * df.q.to_numpy(), CAP / p)
    x["usd_in"] = x.shares * p
    x["date"] = pd.to_datetime(x.ts, unit="s", utc=True).dt.floor("D")
    return x


def wf(x: pd.DataFrame, col: str):
    months = sorted(x.month.unique())
    picks, out = [], []
    for i, m in enumerate(months):
        if i < 2:
            continue
        tr = x[x.month < m]
        best = None
        q = col.startswith("qb_")
        for h in (HS_ if q else [-9.0] + HS_):
            v = tr.loc[tr.edge >= h - 1e-9, col].dropna() + (h if q else 0.0)
            if len(v) < 1000:
                continue
            key = (v.mean(), len(v))
            if best is None or key > best[0]:
                best = (key, h)
        if best is None or best[0][0] <= 0:  # no positive training edge: stand aside this month
            picks.append({"month": m, "h": np.nan, "train_mean_c": 100 * best[0][0] if best else np.nan, "n": 0,
                          "mean_c": np.nan, "pnl_usd": 0.0, "usd_in": 0.0})
            continue
        h = best[1]
        te = x[(x.month == m) & (x.edge >= h - 1e-9)].dropna(subset=[col])
        val = te[col] + (h if q else 0.0)
        te = te.assign(pnl_ps=val, pnl=val * te.shares, exit=col, h=h)
        picks.append({"month": m, "h": h, "train_mean_c": 100 * best[0][0], "n": len(te),
                      "mean_c": 100 * te.pnl_ps.mean(), "pnl_usd": te.pnl.sum(), "usd_in": te.usd_in.sum()})
        out.append(te)
    cols = list(x.columns) + ["pnl_ps", "pnl", "exit", "h"]
    return pd.DataFrame(picks), (pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=cols))


def main():
    df = build()
    res, nvar = {}, 0
    for cur in (False, True):
        x = pnl(df, cur)
        tag = "maker" + ("_curfee" if cur else "")
        # transparency grid by regime (NOT used for selection)
        rows = []
        for (r, dl), g in x.groupby(["fee_rate", "delay"]):
            for h in [-9.0] + HS_:
                v = g[g.edge >= h - 1e-9]
                rows.append({"regime": f"{r}/{dl}s", "h": h, "n": len(v), **{c + "_c": 100 * v[c].mean() for c in
                             ["ps_pm30", "ps_pm60", "ps_k60", "ps_res", "ps_hedge_m1", "ps_hedge_p025", "ps_hedge_m175"]}})
        pd.DataFrame(rows).to_csv(OUT / f"grid_IS_{tag}.csv", index=False)
        for col in ["ps_pm60", "ps_k60", "ps_res", "ps_hedge_m1", "ps_hedge_p025", "ps_hedge_m175",
                    "qb_pm60", "qb_k60", "qb_hedge_m1"]:
            nvar += len(HS_) + (0 if col.startswith("qb_") else 1)
            picks, tr = wf(x, col)
            picks.to_csv(OUT / f"wf_{tag}_{col}.csv", index=False)
            st = stats(tr[["cond", "pnl_ps", "pnl", "fee", "usd_in", "exit", "date"]], n_boot=500)
            st["months_positive"] = int((tr.groupby("month").pnl.sum() > 0).sum())
            st["months_total"] = int(tr.month.nunique())
            st["by_regime"] = {}
            for (r, dl), g in tr.groupby(["fee_rate", "delay"]):
                s2 = stats(g[["cond", "pnl_ps", "pnl", "fee", "usd_in", "exit", "date"]], n_boot=500)
                st["by_regime"][f"{r}/{dl}s"] = {k: s2.get(k) for k in ["n_trades", "mean_pnl_per_share_c",
                                                 "ci95_pnl_per_share_c", "total_pnl_usd", "sharpe_ann"]}
            st["picks"] = picks.to_dict("records")
            st["usd_per_month_1s5pct"] = float(tr[(tr.fee_rate == 0.05) & (tr.delay == 1)].groupby("month").usd_in.sum().mean())
            res[f"{tag}:{col}"] = st
            tr[["cond", "ts", "month", "fee_rate", "delay", "edge", "pnl_ps", "pnl", "shares", "usd_in", "h"]].to_parquet(
                OUT / f"trades_wf_{tag}_{col}.parquet")
            print(tag, col, {k: st.get(k) for k in ["n_trades", "mean_pnl_per_share_c", "ci95_pnl_per_share_c",
                                                     "total_pnl_usd", "sharpe_ann", "max_dd", "months_positive"]})
            for k, v in st["by_regime"].items():
                print("    ", k, v)
    # sensitivity (robustness only): quote-price maker with the cancel deadline at t - B - c for B = 0, 1 s
    sens = {}
    for b in (0, 1):
        d2 = df.copy()
        d2["kf"] = d2[f"kf_b{b}"]
        x = pnl(d2, True)
        for col in ["qb_pm60", "qb_k60", "ps_pm60"]:
            nvar += len(HS_) + (0 if col.startswith("qb_") else 1)
            picks, tr = wf(x, col)
            cur_ = tr[(tr.fee_rate == 0.05) & (tr.delay == 1)]
            st = stats(tr[["cond", "pnl_ps", "pnl", "fee", "usd_in", "exit", "date"]], n_boot=300)
            s2 = stats(cur_[["cond", "pnl_ps", "pnl", "fee", "usd_in", "exit", "date"]], n_boot=300)
            sens[f"maker_curfee:{col}:B{b}"] = {"all": {k: st.get(k) for k in ["n_trades", "mean_pnl_per_share_c",
                                                "ci95_pnl_per_share_c", "total_pnl_usd"]},
                                                "1s5pct": {k: s2.get(k) for k in ["n_trades", "mean_pnl_per_share_c",
                                                "ci95_pnl_per_share_c", "total_pnl_usd"]}}
            print("SENS", f"B{b}", col, sens[f"maker_curfee:{col}:B{b}"])
    res["latency_sensitivity"] = sens
    res["n_variants_wf"] = nvar
    (OUT / "maker_summary.json").write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
