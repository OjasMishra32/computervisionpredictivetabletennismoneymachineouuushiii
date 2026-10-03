"""Step 6: walk-forward backtest of the laggard strategies built in k05.

Per-share P&L by exit (all net of the fees of every leg actually taken):
  res     hold to resolution:            d*(res0 - p_f) - fee_in
  mid60   passive exit at +60 s mid:     d*(mid_60 - p_f) - fee_in - maker_fee_out   (optimistic: assumes the
          resting exit fills at the mid; Polymarket makers pay 0, Kalshi match series charge 0.0175 p(1-p))
  taker60 cross the spread at +60 s:     d*(exit_px_60 - p_f) - fee_in - taker_fee_out
  hedge   cross-venue hedge at fill:     d*(hedge_px - p_f) + d*(settle_traded - settle_hedge) - fee_in - fee_hedge
          (both legs held to resolution; payoffs cancel when both venues settle the same way, so P&L is locked
          at entry except for settlement basis, e.g. Kalshi 'fair price' after a retirement). hedge_px falls back
          to a touch proxy (other side's last <=5 s old print -/+ 2c) when nobody printed on the hedge side in 3 s;
          ps_hedge_strict drops those trades instead (reported as a robustness line).
Fees: Polymarket taker = fee_rate * p(1-p) (per match; 'cur' = 0.05 for the current regime);
      Kalshi taker = 0.07 p(1-p); Kalshi maker = 0.0175 p(1-p) (KXATPMATCH/KXWTAMATCH since 2025-11-15).

Parameters (chosen walk-forward, months < m -> month m; never on OOS):
  G  min gap at signal between leader fair value and laggard's own mid: {0,1,2,3,4,6} c
  E  min edge of the fill vs leader fair value at signal:             {none,0,1,2,3} c
Fixed (not tuned): fill price band [0.05, 0.95], B = 2 s (PM block allowance) / D_K = 1 s (Kalshi delay),
  size = min($1000, 50% of the 3 s same-side print volume at prices within the limit), <= $3000 per match.
Selection: maximise training mean per-share net subject to >= 150 training trades; first eval month needs
  >= 2 training months; if the best training mean is <= 0 the strategy stands aside that month.

Run: .venv/bin/python research/v2/kalshi/k06_backtest.py
Outputs: research/v2/kalshi/out/wf_*.csv, results.json (merged by k07), trades_wf_*.parquet
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from k_common import CACHE, OUT, ROOT  # noqa: E402
from src.backtest import stats  # noqa: E402

GS = [0.0, 0.01, 0.02, 0.03, 0.04, 0.06]
ES = [-9.0, 0.0, 0.01, 0.02, 0.03]
MIN_TRAIN = 150
CAP_TRADE, CAP_MATCH = 1000.0, 3000.0
KALSHI_MAKER_START = pd.Timestamp("2025-11-15", tz="UTC").timestamp()


def pm_fee(p, rate):
    return rate * p * (1 - p)


def k_fee(p):
    return 0.07 * p * (1 - p)


def k_maker(p, ts):
    return np.where(ts >= KALSHI_MAKER_START, 0.0175 * p * (1 - p), 0.0)


def prep(s: pd.DataFrame, venue: str, base_lag: int, cur_fee: bool = False) -> pd.DataFrame:
    s = s[(s.B == base_lag) & s.p_f.between(0.05, 0.95)].copy()
    d, p = s.d.to_numpy(), s.p_f.to_numpy()
    rate = np.full(len(s), 0.05) if cur_fee else s.fee_rate.to_numpy()
    if venue == "pm":  # traded Polymarket, leader = Kalshi
        fee_in = pm_fee(p, rate)
        own60, lead60 = s.pm_mid_60.to_numpy(), s.k_mid_60.to_numpy()
        maker_out = np.zeros(len(s))
        taker_out = pm_fee(s.exit_px_60.to_numpy(), rate)
        fee_h = k_fee(s.hedge_px.to_numpy())
    else:  # traded Kalshi, leader = Polymarket
        fee_in = k_fee(p)
        own60, lead60 = s.k_mid_60.to_numpy(), s.pm_mid_60.to_numpy()
        maker_out = k_maker(own60, s.ts_f.to_numpy())
        taker_out = k_fee(s.exit_px_60.to_numpy())
        fee_h = pm_fee(s.hedge_px.to_numpy(), rate)
    pm_res, k_res = s.res0.to_numpy(), s.k_settle0.to_numpy()
    res = pm_res if venue == "pm" else k_res          # the traded venue settles on its own value
    other = k_res if venue == "pm" else pm_res        # the hedge venue's settlement
    s["fee"] = fee_in
    s["ps_res"] = np.where(np.isfinite(res), d * (res - p) - fee_in, np.nan)
    s["ps_mid60"] = np.where(np.isfinite(own60), d * (own60 - p) - fee_in - maker_out, s.ps_res)
    s["ps_taker60"] = np.where(np.isfinite(s.exit_px_60), d * (s.exit_px_60 - p) - fee_in - taker_out, s.ps_res)
    # hedged: locked spread + settlement basis (non-zero only when the venues settle differently,
    # e.g. Kalshi 'fair price' on a retirement while Polymarket pays 1/0)
    s["ps_hedge"] = d * (s.hedge_px.to_numpy() - p) + d * (res - other) - fee_in - fee_h
    hs = s.hedge_px_strict.to_numpy()  # robustness: only hedges that matched a real print within 3 s
    s["ps_hedge_strict"] = d * (hs - p) + d * (res - other) - fee_in - (k_fee(hs) if venue == "pm" else pm_fee(hs, rate))
    s["ps_fair60"] = d * (lead60 - p) - fee_in  # diagnostic: marked to the LEADING venue's mid
    s["date"] = pd.to_datetime(s.ts_f, unit="s", utc=True).dt.floor("D")
    s["ts"] = s.ts_f
    return s.reset_index(drop=True)


def size_trades(t: pd.DataFrame, E: float) -> pd.DataFrame:
    """Shares: min($1000/p, 50% of 3 s same-side volume within the limit); then <= $3000 per match."""
    t = t.copy()
    lim_vol = np.array([q[(d * (f - pw)) >= E - 1e-9].sum() if E > -1 else q.sum()
                        for pw, q, d, f in zip(t.pw, t.qw, t.d, t.fair)], dtype=float)
    sh = np.minimum(CAP_TRADE / t.p_f.to_numpy(), 0.5 * lim_vol)
    t["shares"] = sh
    t["usd_in"] = sh * t.p_f.to_numpy()
    t = t.sort_values("ts_f", kind="stable")
    cum = t.groupby("cond").usd_in.cumsum()
    over = cum > CAP_MATCH
    prev = cum - t.usd_in
    t.loc[over, "usd_in"] = np.maximum(0.0, CAP_MATCH - prev[over])
    t.loc[over, "shares"] = t.loc[over, "usd_in"] / t.loc[over, "p_f"]
    return t[t.shares > 0]


def select(t: pd.DataFrame, G: float, E: float) -> pd.DataFrame:
    return t[(t.gap >= G - 1e-9) & ((t.edge_f >= E - 1e-9) if E > -1 else True)]


def walk_forward(t: pd.DataFrame, col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    months = sorted(t.month.unique())
    picks, out = [], []
    for i, m in enumerate(months):
        if i < 2:
            continue
        tr = t[t.month < m]
        best = None
        for G, E in itertools.product(GS, ES):
            x = select(tr, G, E)[col].dropna()
            if len(x) < MIN_TRAIN:
                continue
            key = (x.mean(), len(x))
            if best is None or key > best[0]:
                best = (key, G, E)
        if best is None or best[0][0] <= 0:
            # no parameter set had a positive training edge: the walk-forward stands aside this month
            picks.append({"month": m, "G": np.nan, "E": np.nan, "train_mean_c": 100 * best[0][0] if best else np.nan,
                          "train_n": best[0][1] if best else 0, "n": 0, "mean_c": np.nan, "pnl_usd": 0.0, "usd_in": 0.0})
            continue
        _, G, E = best
        te = select(t[t.month == m], G, E).dropna(subset=[col])
        te = size_trades(te, E)
        te = te.assign(pnl_ps=te[col], pnl=te[col] * te.shares, G=G, E=E, exit=col)
        picks.append({"month": m, "G": G, "E": E, "train_mean_c": 100 * best[0][0], "train_n": best[0][1],
                      "n": len(te), "mean_c": 100 * te.pnl_ps.mean() if len(te) else np.nan,
                      "pnl_usd": te.pnl.sum(), "usd_in": te.usd_in.sum()})
        out.append(te)
    return pd.DataFrame(picks), (pd.concat(out, ignore_index=True) if out else pd.DataFrame())


def static_grid(t: pd.DataFrame, cols) -> pd.DataFrame:
    """Full-IS grid, reported for transparency only (NOT used for selection)."""
    rows = []
    for G, E in itertools.product(GS, ES):
        x = select(t, G, E)
        r = {"G": G, "E": E, "n": len(x)}
        for c in cols:
            r[c + "_c"] = 100 * x[c].mean()
        rows.append(r)
    return pd.DataFrame(rows)


def summarize(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n_trades": 0}
    st = stats(tr[["cond", "pnl_ps", "pnl", "fee", "usd_in", "exit", "date"]])
    st["months_positive"] = int((tr.groupby("month").pnl.sum() > 0).sum())
    st["months_total"] = int(tr.month.nunique())
    st["mean_pnl_per_share_c_sharewt"] = float(100 * tr.pnl.sum() / tr.shares.sum())
    return st


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    allres = {}
    n_variants = 0
    for venue, fam, fname, base in (("pm", "jump", "signals_pm.parquet", 2), ("pm", "gap", "signals_pm.parquet", 2),
                                    ("pm", "gaprob", "signals_pm.parquet", 2), ("k", "jump", "signals_k.parquet", 1)):
        raw = pd.read_parquet(CACHE / fname)
        raw = raw[raw.fam == fam]
        for cur in (False, True):
            if cur and venue == "k":
                continue  # the PM fee only enters S_K through the hedge leg; skip
            t = prep(raw, venue, base, cur_fee=cur)
            tag = f"{venue}_{fam}{'_curfee' if cur else ''}"
            cols = ["ps_res", "ps_mid60", "ps_taker60", "ps_hedge", "ps_hedge_strict", "ps_fair60"]
            static_grid(t, cols).to_csv(OUT / f"grid_IS_{tag}.csv", index=False)
            for col in ["ps_res", "ps_mid60", "ps_taker60", "ps_hedge", "ps_hedge_strict"]:
                n_variants += len(GS) * len(ES)
                picks, tr = walk_forward(t, col)
                picks.to_csv(OUT / f"wf_{tag}_{col}.csv", index=False)
                if len(tr):
                    tr.drop(columns=["pw", "qw"]).to_parquet(OUT / f"trades_wf_{tag}_{col}.parquet")
                st = summarize(tr)
                st["by_regime"] = {f"{r}/{d}s": summarize(g) for (r, d), g in tr.groupby(["fee_rate", "delay"])} if len(tr) else {}
                st["picks"] = picks.to_dict("records")
                allres[f"{tag}:{col}"] = st
                print(tag, col, {k: st.get(k) for k in ["n_trades", "mean_pnl_per_share_c", "ci95_pnl_per_share_c",
                                                         "total_pnl_usd", "sharpe_ann", "months_positive", "months_total"]})
                for k, v in st["by_regime"].items():
                    print("    ", k, v.get("n_trades"), round(v.get("mean_pnl_per_share_c", np.nan), 3),
                          [round(x, 2) for x in v.get("ci95_pnl_per_share_c", [np.nan, np.nan])], round(v.get("total_pnl_usd", 0)))
    # latency sensitivity (robustness only, never selected on): PM block allowance B in {0, 4} s for the
    # Kalshi-led families; assumed Kalshi order delay D_K in {0, 3} s for the PM-led family
    sens = {}
    for venue, fam, fname, lags in (("pm", "gap", "signals_pm.parquet", (0, 4)), ("pm", "jump", "signals_pm.parquet", (0, 4)),
                                    ("pm", "gaprob", "signals_pm.parquet", (0, 4)),
                                    ("k", "jump", "signals_k.parquet", (0, 3))):
        raw = pd.read_parquet(CACHE / fname)
        raw = raw[raw.fam == fam]
        for lag in lags:
            t = prep(raw, venue, lag, cur_fee=(venue == "pm"))
            for col in ["ps_mid60", "ps_hedge", "ps_res"]:
                n_variants += len(GS) * len(ES)
                picks, tr = walk_forward(t, col)
                st = summarize(tr)
                key = f"{venue}_{fam}{'_curfee' if venue == 'pm' else ''}:{col}:lag{lag}"
                sens[key] = {k: st.get(k) for k in ["n_trades", "mean_pnl_per_share_c", "ci95_pnl_per_share_c",
                                                    "total_pnl_usd", "sharpe_ann", "months_positive", "months_total"]}
                print("SENS", key, sens[key])
    allres["latency_sensitivity"] = sens
    allres["n_variants_wf"] = n_variants
    (OUT / "backtest_summary.json").write_text(json.dumps(allres, indent=1, default=float))


if __name__ == "__main__":
    main()
