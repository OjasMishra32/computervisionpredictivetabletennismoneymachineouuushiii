"""Lens "exit": P&L accounting, walk-forward selection of (H_min, T), baselines, stats.

Reads the simulator cache (data/v2_exit/*.parquet from sim_exit.py) and writes
research/v2/exit/results.json, research/v2/exit/tables/*.csv.

    .venv/bin/python research/v2/exit/analyze_exit.py

Walk-forward rule (pre-declared): for each month m, within a family (sizing, fill model, fallback,
rebate), pick the (H_min, T) cell with the largest summed net P&L over months < m (equivalently the
best share-weighted net per share, since the entry set is identical across cells). If months < m hold
fewer than 1,000 accepted entries, use the pre-declared default (H_min=5 s, T=60 s). The reported
series is the concatenation of each month's chosen cell evaluated on that month only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

CACHE = ROOT / "data" / "v2_exit"
HERE = Path(__file__).resolve().parent
TAB = HERE / "tables"
HS = (2, 5, 10, 20, 30)
TS = (30, 60, 120, 300)
TS_EXT = (600, 1800)
MODELS = ("touch", "through", "pegthrough", "improve1g")  # sim_exit.py model ids
SIZINGS = ("sh500", "usd1k")
DEFAULT = (5, 60)
MIN_PAST = 1000
REBATE = 0.15
HAIRCUT_SEED = 0
PRIMARY = ("sh500", "touch", "B", False)  # pre-declared before any P&L was computed


def load(sfx=""):
    ent = pd.read_parquet(CACHE / f"entries{sfx}.parquet")
    mk = pd.read_parquet(CACHE / f"maker{sfx}.parquet")
    fb = pd.read_parquet(CACHE / f"fallback{sfx}.parquet")
    ent["fee"] = ent.fee_rate * ent.p * (1 - ent.p)
    ent["regime"] = ent.delay.astype(str) + "s/" + (ent.fee_rate * 100).round().astype(int).astype(str) + "%"
    ent["date"] = pd.to_datetime(ent.ts, unit="s", utc=True).dt.floor("D")
    rng = np.random.default_rng(HAIRCUT_SEED)
    ent["u_haircut"] = rng.random(len(ent))  # one fixed draw per entry, shared by every cell
    return ent, mk, fb


# ----------------------------------------------------------------------------- P&L per cell
def fallback_cols(ent, fb, H, T):
    f = fb[(fb.H == H) & (fb["T"] == T)].set_index("eid").reindex(ent.eid)
    px, dt = f.px.to_numpy(float), f.dt.to_numpy(float)
    has = np.isfinite(px)
    pnlB = np.where(has, ent.dir * (np.nan_to_num(px) - ent.p) - ent.fee - ent.fee_rate * np.nan_to_num(px) * (1 - np.nan_to_num(px)),
                    ent.dir * (ent.res - ent.p) - ent.fee)
    tB = np.where(has, dt, ent.end_ts - ent.ts)
    return pnlB, tB, has


def cell_pnl(ent, mk_cell, fb, H, T, model, fallback, rebate):
    """Per-entry net P&L per share and holding time for one (H, T, model, fallback, rebate) cell."""
    m = mk_cell.set_index("eid").reindex(ent.eid)
    filled = m.filled.fillna(False).to_numpy(bool)
    if model == "touch50":
        filled = filled & (ent.u_haircut.to_numpy() >= 0.5)
    px = m.px.to_numpy(float)
    if model in ("improve1", "improve1g"):  # quote 1 tick inside the touch: alone at the best price, 1 tick worse
        px = px - ent.dir.to_numpy() * ent.tick.to_numpy()
    pnl_m = ent.dir * (px - ent.p) - ent.fee
    if rebate:
        pnl_m = pnl_m + REBATE * ent.fee_rate * px * (1 - px)
    if fallback == "A":
        pnl_f = (ent.dir * (ent.res - ent.p) - ent.fee).to_numpy()
        t_f = (ent.end_ts - ent.ts).to_numpy(float)
        how_f = np.full(len(ent), "res", dtype=object)
    else:
        pnl_f, t_f, has = fallback_cols(ent, fb, H, T)
        how_f = np.where(has, "taker", "res").astype(object)
    pnl = np.where(filled, pnl_m, pnl_f)
    hold = np.where(filled, m.dt.to_numpy(float), t_f)
    how = np.where(filled, "maker", how_f)
    return pd.DataFrame({"eid": ent.eid.to_numpy(), "pnl_ps": pnl, "hold_s": hold, "how": how})


def book(ent, sz, cells: pd.DataFrame) -> pd.DataFrame:
    """Attach sizing to per-entry P&L."""
    e = ent[["eid", "cond", "ts", "date", "month", "regime", "fee", "pp", "end_ts", f"shares_{sz}"]].rename(
        columns={f"shares_{sz}": "shares"})
    tr = e.merge(cells, on="eid")
    tr["pnl"] = tr.shares * tr.pnl_ps
    tr["usd_in"] = tr.shares * tr.pp
    return tr


# ----------------------------------------------------------------------------- statistics
def cluster_ci(tr, n_boot=1000, seed=0):
    g = tr.groupby("cond").agg(s=("pnl_ps", "sum"), n=("pnl_ps", "size"), d=("pnl", "sum"), sh=("shares", "sum"))
    rng = np.random.default_rng(seed)
    k = len(g)
    s, n, d, sh = (g[c].to_numpy() for c in ("s", "n", "d", "sh"))
    tw, swt = [], []
    for _ in range(n_boot):
        i = rng.integers(0, k, k)
        tw.append(s[i].sum() / n[i].sum())
        swt.append(d[i].sum() / sh[i].sum())
    return np.percentile(tw, [2.5, 97.5]) * 100, np.percentile(swt, [2.5, 97.5]) * 100


def peak_locked(tr):
    end = tr.ts + np.nan_to_num(tr.hold_s, nan=0.0)
    ev = pd.concat([pd.DataFrame({"t": tr.ts, "d": tr.usd_in}), pd.DataFrame({"t": end, "d": -tr.usd_in})])
    ev = ev.sort_values(["t", "d"], kind="stable")  # exits before entries at the same second
    return float(ev.d.cumsum().max())


def summarize(tr, n_boot=1000, capital=None) -> dict:
    tr = tr[np.isfinite(tr.pnl_ps)]
    if tr.empty:
        return {"n_trades": 0}
    daily = tr.groupby("date").pnl.sum()
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC")
    daily = daily.reindex(idx, fill_value=0.0)
    peak = peak_locked(tr)
    cap = capital if capital else 3 * peak
    eq = daily.cumsum()
    dd_usd = float((eq - eq.cummax()).min())
    ci_tw, ci_sw = cluster_ci(tr, n_boot)
    monthly = tr.groupby("month").pnl.sum()
    ps_m = tr.groupby("month").apply(lambda g: g.pnl.sum() / g.shares.sum(), include_groups=False)
    out = {
        "n_trades": int(len(tr)), "n_matches": int(tr.cond.nunique()),
        "per_share_net_c": float(tr.pnl_ps.mean() * 100), "ci95_c": [float(ci_tw[0]), float(ci_tw[1])],
        "per_share_net_sw_c": float(tr.pnl.sum() / tr.shares.sum() * 100), "ci95_sw_c": [float(ci_sw[0]), float(ci_sw[1])],
        "hit_rate": float((tr.pnl_ps > 0).mean()), "mean_fee_c": float(tr.fee.mean() * 100),
        "total_pnl_usd": float(tr.pnl.sum()), "shares": float(tr.shares.sum()), "usd_in": float(tr.usd_in.sum()),
        "sharpe_daily_ann": float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else float("nan"),
        "max_dd_usd": dd_usd, "peak_locked_usd": peak, "capital_3x_peak": cap,
        "max_dd_pct_of_capital": float(dd_usd / cap * 100) if cap > 0 else float("nan"),
        "worst_day_usd": float(daily.min()), "days": int(len(idx)),
        "months_positive": int((monthly > 0).sum()), "months_total": int(len(monthly)),
        "months_positive_per_share": int((ps_m > 0).sum()),
        "fill_rate_maker": float((tr.how == "maker").mean()) if "how" in tr else None,
        "share_taker_fallback": float((tr.how == "taker").mean()) if "how" in tr else None,
        "share_resolution": float((tr.how == "res").mean()) if "how" in tr else None,
        "hold_median_s": float(np.nanmedian(tr.hold_s)) if "hold_s" in tr else None,
        "hold_p90_s": float(np.nanpercentile(tr.hold_s, 90)) if "hold_s" in tr else None,
    }
    return out


def by(tr, col):
    rows = []
    for k, g in tr.groupby(col):
        g = g[np.isfinite(g.pnl_ps)]
        rows.append({col: k, "n": len(g), "matches": g.cond.nunique(), "per_share_c": g.pnl_ps.mean() * 100,
                     "per_share_sw_c": g.pnl.sum() / g.shares.sum() * 100, "pnl_usd": g.pnl.sum(),
                     "maker_fill": (g.how == "maker").mean() if "how" in g else np.nan,
                     "hold_med_s": np.nanmedian(g.hold_s) if "hold_s" in g else np.nan,
                     "H": g.H.iloc[0] if "H" in g else np.nan, "T": g["T"].iloc[0] if "T" in g else np.nan})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- walk-forward
def walk_forward(grid_tr: dict, months: list[str], default=DEFAULT):
    """grid_tr[(H,T)] -> per-entry trades (same entries in every cell). Returns WF trades + choices."""
    sums = pd.DataFrame({k: v.groupby("month").pnl.sum() for k, v in grid_tr.items()}).reindex(months).fillna(0.0)
    counts = next(iter(grid_tr.values())).groupby("month").size().reindex(months).fillna(0)
    parts, choices = [], []
    for i, m in enumerate(months):
        past = months[:i]
        if counts[past].sum() < MIN_PAST:
            pick = default
        else:
            pick = sums.loc[past].sum().idxmax()
        parts.append(grid_tr[pick][grid_tr[pick].month == m].assign(H=pick[0], T=pick[1]))
        choices.append({"month": m, "H": int(pick[0]), "T": int(pick[1]), "past_trades": int(counts[past].sum())})
    return pd.concat(parts, ignore_index=True), pd.DataFrame(choices)


def main(sfx=""):
    TAB.mkdir(exist_ok=True)
    ent, mk, fb = load(sfx)
    months = sorted(ent.month.unique())
    n_variants = 0
    res = {"months": months, "families": {}, "baselines": {}, "grid_full_is_descriptive": {}}
    cells_seen = set()

    for si, sz in enumerate(SIZINGS):
        E = ent[ent[f"acc_{sz}"]].reset_index(drop=True)
        # ---------------- baselines on the same entry set and sizing
        base = {
            "hold_to_resolution": pd.DataFrame({"eid": E.eid, "pnl_ps": E.dir * (E.res - E.p) - E.fee,
                                                "hold_s": (E.end_ts - E.ts).astype(float), "how": "res"}),
            "mid30_markout_benchmark": pd.DataFrame({"eid": E.eid, "pnl_ps": E.mo30 - E.fee, "hold_s": 30.0, "how": "mid"}),
        }
        for name, cells in base.items():
            n_variants += 1
            tr = book(E, sz, cells)
            res["baselines"][f"{sz}/{name}"] = {"all": summarize(tr),
                                                "regime_1s5": summarize(tr[tr.regime == "1s/5%"]),
                                                "by_regime": by(tr, "regime").to_dict("records")}
            by(tr, "month").to_csv(TAB / f"baseline_{sz}_{name}_by_month.csv", index=False)
            if sz == PRIMARY[0]:
                tr.to_parquet(CACHE / f"tr_{sz}_{name}{sfx}.parquet")
        # taker-out at H (no maker leg), H walk-forward
        tk = {}
        for H in HS:
            n_variants += 1
            pnlB, tB, has = fallback_cols(E, fb, H, 0)
            tk[(H, 0)] = book(E, sz, pd.DataFrame({"eid": E.eid, "pnl_ps": pnlB, "hold_s": tB,
                                                   "how": np.where(has, "taker", "res")}))
        wf_tk, ch_tk = walk_forward(tk, months, default=(DEFAULT[0], 0))
        res["baselines"][f"{sz}/taker_out_wf"] = {"all": summarize(wf_tk), "regime_1s5": summarize(wf_tk[wf_tk.regime == "1s/5%"]),
                                                  "choices": ch_tk.to_dict("records"),
                                                  "full_is_by_H_c": {str(H): float(v.pnl.sum() / v.shares.sum() * 100) for (H, _), v in tk.items()}}
        if sz == PRIMARY[0]:
            wf_tk.to_parquet(CACHE / f"tr_{sz}_taker_out_wf{sfx}.parquet")

        # ---------------- maker-exit families
        fams = [(m, fbk, rb, TS, "") for m in ("touch", "touch50", "through", "pegthrough", "improve1g")
                for fbk in ("A", "B") for rb in (False, True)]
        if sz == "sh500":
            fams += [("improve1", "B", False, TS, ""), ("improve1", "B", True, TS, ""),
                     ("touch", "B", False, TS + TS_EXT, "/ext"), ("pegthrough", "B", False, TS + TS_EXT, "/ext"),
                     ("improve1g", "B", False, TS + TS_EXT, "/ext"), ("improve1g", "B", True, TS + TS_EXT, "/ext")]
        cache_mk = {}
        for model, fallback, rebate, Ts, tag in fams:
            src_model = model if model in MODELS else "touch"
            mi = MODELS.index(src_model)
            if mi not in cache_mk:
                mkm = mk[(mk.sizing == si) & (mk.model == mi)]
                cache_mk[mi] = {k: g for k, g in mkm.groupby(["H", "T"])}
            cell_mk = cache_mk[mi]
            grid = {}
            for H in HS:
                for T in Ts:
                    cells_seen.add((sz, model, fallback, rebate, H, T))
                    grid[(H, T)] = book(E, sz, cell_pnl(E, cell_mk[(H, T)], fb, H, T, model, fallback, rebate))
            wf, ch = walk_forward(grid, months)
            key = f"{sz}/{model}/fb{fallback}/{'rebate' if rebate else 'norebate'}{tag}"
            fam = {"all": summarize(wf), "regime_1s5": summarize(wf[wf.regime == "1s/5%"]),
                   "by_regime": by(wf, "regime").to_dict("records"), "choices": ch.to_dict("records")}
            res["families"][key] = fam
            # descriptive full-IS grid (NOT used for selection)
            res["grid_full_is_descriptive"][key] = {
                f"H{H}_T{T}": {"ps_tw_c": float(g.pnl_ps.mean() * 100), "ps_sw_c": float(g.pnl.sum() / g.shares.sum() * 100),
                               "ps_1s5_tw_c": float(g[g.regime == "1s/5%"].pnl_ps.mean() * 100),
                               "ps_1s5_sw_c": float(g[g.regime == "1s/5%"].pnl.sum() / max(g[g.regime == "1s/5%"].shares.sum(), 1e-9) * 100),
                               "maker_fill": float((g.how == "maker").mean()), "pnl_usd": float(g.pnl.sum())}
                for (H, T), g in grid.items()}
            bm = by(wf, "month")
            bm.to_csv(TAB / f"wf_{key.replace('/', '_')}_by_month.csv", index=False)
            fam["by_month"] = bm.to_dict("records")
            if (sz, model, fallback, rebate) == PRIMARY and not tag:
                wf.to_parquet(CACHE / f"tr_primary{sfx}.parquet")
            if sz == "sh500" and fallback == "B" and not rebate:
                wf.to_parquet(CACHE / f"tr_{key.replace('/', '_')}{sfx}.parquet")
            print(key, f"{fam['all']['per_share_net_c']:.2f}c tw, {fam['all']['per_share_net_sw_c']:.2f}c sw, "
                  f"${fam['all']['total_pnl_usd']:,.0f}, SR {fam['all']['sharpe_daily_ann']:.2f}, "
                  f"1s5 {fam['regime_1s5'].get('per_share_net_c', float('nan')):.2f}c tw", flush=True)

    n_variants += len(cells_seen)
    res["n_variants"] = n_variants
    res["primary_key"] = "/".join([PRIMARY[0], PRIMARY[1], "fb" + PRIMARY[2], "rebate" if PRIMARY[3] else "norebate"])
    (HERE / "results_full.json").write_text(json.dumps(res, indent=1, default=float))
    print("variants", n_variants)
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sfx", default="", help="cache suffix, e.g. _lim100 for the smoke test")
    main(ap.parse_args().sfx)
