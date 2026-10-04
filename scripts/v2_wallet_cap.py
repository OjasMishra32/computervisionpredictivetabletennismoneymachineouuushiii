"""v2 per-wallet cap and wallet retirement: IS grid + selection, then ONE burned-OOS run; per-match loss check.

    .venv/bin/python scripts/v2_wallet_cap.py --is    # IS only (research/v2/risk/GRID_wallet_cap.md), ~1 min
        -> results/v2/risk/wallet_cap_is.json
    .venv/bin/python scripts/v2_wallet_cap.py --oos   # frozen rule (research/v2/risk/PREREG_wallet_cap.md), once
        -> results/v2/risk/wallet_cap.json, results/v2/risk/per_match_loss.json, one line in results/oos_peeks.log

--is reads only data/v2_lowloss/{features,whist}_is.parquet (IS-only causal v2 feature table built by
scripts/lowloss_select.py from data/is_prints.parquet). --oos reads data/v2_lowloss/{features,whist}_u1.parquet
(the joint IS + burned-OOS build of scripts/lowloss_test.py, checked against its file hashes), and
data/v2_trades_is_oos.parquet (the canonical frozen v2 trades of scripts/v2_causal.py) for a reference check.

Every variant runs through the verified sizing engine (research/v2/sizing/engine.py): month_targets ->
apply_caps, hold to resolution, actual fees. The per-wallet cap is the engine's own Policy.wallet_day_cap
(gross $ per (wallet, UTC day)); retirement zeroes the targets of a wallet whose trailing 30-day net 30 s
markout (>= 50 prints, each known 30 s after it) is <= 0.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import v2  # noqa: E402

E = v2.E
OUT = ROOT / "results/v2/risk"
GRID_MD = ROOT / "research/v2/risk/GRID_wallet_cap.md"
PREREG_MD = ROOT / "research/v2/risk/PREREG_wallet_cap.md"
PEEKS = ROOT / "results/oos_peeks.log"
CACHE = ROOT / "data/v2_lowloss"

CAPS = [np.inf, 4000.0, 2000.0, 1000.0, 500.0, 250.0]     # $ gross per (copied wallet, UTC day)
RETIRE = [False, True]
RET_WIN_S, RET_LAG_S, RET_MIN_N = 30 * 86400, 30, 50       # trailing 30 d, markout known 30 s later, >= 50 prints
FEAS_PNL_FRAC = 0.5

# Frozen by research/v2/risk/PREREG_wallet_cap.md (set from the --is selection; --oos asserts they agree).
FROZEN_W: float | None = 1000.0   # W1000_Ron, chosen by --is on 2026-10-04 (results/v2/risk/wallet_cap_is.json::selection)
FROZEN_R: bool | None = True

IS_CAL = pd.date_range("2026-02-01", "2026-08-25", freq="D", tz="UTC")     # as scripts/rigor_pack.py
OOS_CAL = pd.date_range("2026-08-25", "2026-10-03", freq="D", tz="UTC")
CUTOFF = pd.Timestamp("2026-10-03 13:00", tz="UTC")
ANN = np.sqrt(365.0)
SR_SEED, SR_BOOT, SR_BLOCK = 20261003, 10_000, 5                          # as scripts/rigor_pack.py
CI_SEED, CI_BOOT = 0, 1_000                                                # as engine.metrics

# stated limits (paper section 6 / engine/risk/limits.py RiskConfig) and the backtest's own per-match gross cap
ORDER_USD, NET_CAP, DAILY_STOP, ZONE_HI = 1_000.0, 100.0, 1_000.0, 0.95
MATCH_GROSS_CAP = float(E.BASE_MATCH_CAP)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sha256(path: Path, n: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()[:n] if n else h.hexdigest()


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def name(W: float, R: bool) -> str:
    return f"W{'inf' if np.isinf(W) else int(W)}_R{'on' if R else 'off'}"


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


# ------------------------------------------------------------------------------------- engine
def retired_flags(f: pd.DataFrame) -> np.ndarray:
    """True where the row's wallet is retired at the row's time (trailing 30 d net 30 s markout <= 0, n >= 50)."""
    out = np.zeros(len(f), bool)
    net = (f.gross30 - f.rate * f.q * (1 - f.q)).to_numpy()
    ts = f.ts.to_numpy()
    for _, idx in f.groupby("wallet", sort=False).indices.items():
        idx = idx[np.argsort(ts[idx], kind="stable")]
        t, x = ts[idx], net[idx]
        ok = np.isfinite(x)
        cn = np.concatenate([[0], np.cumsum(ok)])
        cs = np.concatenate([[0.0], np.cumsum(np.where(ok, x, 0.0))])
        lo = np.searchsorted(t, t - RET_WIN_S, "left")
        hi = np.searchsorted(t, t - RET_LAG_S, "right")
        n = cn[hi] - cn[lo]
        s = cs[hi] - cs[lo]
        out[idx] = (n >= RET_MIN_N) & (s <= 0)
    return out


def simulate(f: pd.DataFrame, wh: pd.DataFrame, W: float, R: bool, stop_usd: float | None = None,
             ret: np.ndarray | None = None) -> pd.DataFrame:
    """engine.simulate with the wallet-day cap, optional retirement mask and optional fixed-$ daily stop."""
    pol = replace(v2.POLICY, name=name(W, R), wallet_day_cap=W)
    sig = None
    if stop_usd is not None:   # engine daily stop at -stop_k * sigma: stop_k = 1, sigma = $ for every month
        pol = replace(pol, stop_k=1.0)
    E._WCACHE.clear()
    months = sorted(m for m in f.month.unique() if m >= E.RUN_START)
    parts = [E.month_targets(f[f.month == m], f[f.month < m], pol, "actual", wh, m, "res") for m in months]
    run = f[f.month >= E.RUN_START].reset_index(drop=True)
    tgt = np.concatenate(parts)
    tgt0 = tgt.copy()
    if R:
        r = (ret if ret is not None else retired_flags(f))[f.month.to_numpy() >= E.RUN_START]
        tgt[r] = 0.0
    if stop_usd is not None:
        sig = {m: float(stop_usd) for m in set(run.month)}
    pnl = np.nan_to_num(E.pnl_ps(run, "res", "actual"))
    shares = E.apply_caps(run, tgt, pol, pnl, "res", sig)
    tr = run.assign(shares=shares, pnl_ps=pnl, target=tgt, target0=tgt0)
    tr = tr[tr.shares > 0].copy()
    tr["usd_in"] = tr.shares * tr.q
    tr["pnl"] = tr.shares * tr.pnl_ps
    tr.attrs["opp_usd"] = float((tgt0 * run.q.to_numpy())[run.month.to_numpy() >= E.EVAL_START].sum())
    tr.attrs["retired_usd"] = float(((tgt0 - tgt) * run.q.to_numpy())[run.month.to_numpy() >= E.EVAL_START].sum())
    return tr


# ------------------------------------------------------------------------------------- stats
def stationary_idx(T: int, B: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / mean_block
    idx = np.empty((B, T), dtype=np.int32)
    idx[:, 0] = rng.integers(0, T, B)
    new = rng.random((B, T)) < p
    starts = rng.integers(0, T, (B, T))
    for t in range(1, T):
        idx[:, t] = np.where(new[:, t], starts[:, t], (idx[:, t - 1] + 1) % T)
    return idx


def daily(tr: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.Series:
    d = tr.groupby("date").pnl.sum()
    d.index = pd.DatetimeIndex(d.index).as_unit("ns")
    cal = cal.as_unit("ns")
    assert d.index.isin(cal).all(), "trade dates outside the calendar"
    return d.reindex(cal, fill_value=0.0)


def sharpe_block(d: np.ndarray) -> dict:
    sd = d.std(ddof=1)
    sr = float(d.mean() / sd * ANN) if sd > 0 else float("nan")
    xb = d[stationary_idx(len(d), SR_BOOT, SR_BLOCK, np.random.default_rng(SR_SEED))]
    s = xb.std(axis=1, ddof=1)
    b = np.where(s > 0, xb.mean(axis=1) / np.where(s > 0, s, 1), np.nan) * ANN
    return {"sharpe_ann": sr, "sharpe_ann_ci95": [float(np.nanpercentile(b, 2.5)), float(np.nanpercentile(b, 97.5))],
            "p_sharpe_le_0": float(np.mean(b <= 0))}


def ratio_ci(df: pd.DataFrame, by: str, seed: int = CI_SEED, n: int = CI_BOOT) -> list[float]:
    g = df.groupby(by).agg(p=("pnl", "sum"), s=("shares", "sum"))
    P, S = g.p.to_numpy(), g.s.to_numpy()
    rng = np.random.default_rng(seed)
    k = len(g)
    bs = [P[i].sum() / S[i].sum() * 100 for i in (rng.integers(0, k, k) for _ in range(n))]
    return [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]


def book_metrics(tr: pd.DataFrame, cal: pd.DatetimeIndex) -> dict:
    tr = tr[tr.month >= E.EVAL_START]
    m = E.metrics(tr)   # match-clustered per-share CI, 1,000 draws, seed 0
    d = daily(tr, cal)
    sb = sharpe_block(d.to_numpy())
    eq = d.cumsum().to_numpy()
    tot = float(tr.pnl.sum())
    w = tr.groupby("wallet").agg(pnl=("pnl", "sum"), usd=("usd_in", "sum")).sort_values("pnl", ascending=False)
    top5 = set(w.index[:5])
    rest = tr[~tr.wallet.isin(top5)]
    wd = tr.groupby(["wallet", "date"]).agg(pnl=("pnl", "sum"), usd=("usd_in", "sum"))
    return {
        "n_trades": int(len(tr)), "n_matches": int(tr.cond.nunique()), "n_wallets": int(len(w)),
        "pnl_usd": tot, "usd_traded": float(tr.usd_in.sum()),
        "per_share_c": m["per_share_c"], "per_share_ci95_c_match": m["per_share_ci_c"],
        "per_share_ci95_c_wallet": ratio_ci(tr, "wallet"),
        "sharpe_ann_calendar": sb["sharpe_ann"], "sharpe_ann_ci95_stationary_bootstrap": sb["sharpe_ann_ci95"],
        "p_sharpe_le_0": sb["p_sharpe_le_0"], "sharpe_ann_engine": m["sharpe_ann"],
        "max_dd_usd": float((eq - np.maximum.accumulate(np.maximum(eq, 0.0))).min()),
        "max_dd_usd_engine": m["max_dd_usd"], "worst_day_usd": float(d.min()),
        "capital_usd_3x_peak_locked": m["capital_usd"], "return_on_capital_pct": m["return_on_capital_pct"],
        "months_positive": m["months_positive"], "months_total": m["months_total"],
        "top1_wallet_share_of_pnl": float(w.pnl.iloc[:1].sum() / tot) if tot else float("nan"),
        "top5_wallet_share_of_pnl": float(w.pnl.iloc[:5].sum() / tot) if tot else float("nan"),
        "top5_wallets_pnl_usd": float(w.pnl.iloc[:5].sum()),
        "ex_top5": {"n_trades": int(len(rest)), "pnl_usd": float(rest.pnl.sum()),
                    "per_share_c": float(rest.pnl.sum() / rest.shares.sum() * 100) if len(rest) else float("nan"),
                    "per_share_ci95_c_match": ratio_ci(rest, "cond") if len(rest) else None},
        "largest_wallet_share_of_gross_usd": float(w.usd.max() / w.usd.sum()),
        "worst_wallet_day_pnl_usd": float(wd.pnl.min()), "max_wallet_day_gross_usd": float(wd.usd.max()),
        "calendar": [str(cal[0].date()), str(cal[-1].date())],
    }


def per_match_loss(tr: pd.DataFrame, cal: pd.DatetimeIndex, tr_stop: pd.DataFrame | None = None) -> dict:
    tr = tr[tr.month >= E.EVAL_START].sort_values("ts", kind="stable")
    g = tr.groupby("cond")
    pm = g.pnl.sum()
    gross = g.usd_in.sum()
    netsh = tr.assign(x=tr.dir * tr.shares).groupby("cond").x
    run_net = tr.assign(x=tr.dir * tr.shares).groupby("cond").x.cumsum()
    both = g.dir.nunique() > 1
    d = daily(tr, cal)
    worst = pm.idxmin()
    wt = tr[tr.cond == worst]
    out = {
        "n_matches": int(len(pm)), "n_losing": int((pm < 0).sum()),
        "worst_match_pnl_usd": float(pm.min()),
        "p99_match_loss_usd": float(-np.percentile(pm, 1)),
        "p999_match_loss_usd": float(-np.percentile(pm, 0.1)),
        "p99_loss_among_losing_matches_usd": float(-np.percentile(pm[pm < 0], 1)) if (pm < 0).any() else 0.0,
        "n_matches_losing_more_than_95": int((pm < -95).sum()),
        "share_matches_losing_more_than_95": float((pm < -95).mean()),
        "worst_day_usd": float(d.min()),
        "worst_match": {"gross_usd": float(gross[worst]), "n_trades": int(len(wt)),
                        "final_net_shares": float(netsh.sum()[worst]),
                        "bought_both_sides": bool(both[worst]),
                        "max_abs_running_net_shares": float(run_net[tr.cond == worst].abs().max())},
        "max_abs_running_net_shares_any_match": float(run_net.abs().max()),
        "max_match_gross_usd": float(gross.max()),
        "max_order_usd": float(tr.usd_in.max()),
        "share_matches_buying_both_sides": float(both.mean()),
        "share_of_loss_usd_in_two_sided_matches": float(pm[(pm < 0) & both].sum() / pm[pm < 0].sum()),
    }
    if tr_stop is not None:
        ts_ = tr_stop[tr_stop.month >= E.EVAL_START]
        ds = daily(ts_, cal)
        changed = sorted(set(tr.date.astype(str)).symmetric_difference(set(ts_.date.astype(str))) |
                         {str(k) for k in (d - ds).index[(d - ds).abs() > 1e-9]})
        out["with_1000_daily_stop"] = {
            "days_changed_by_stop": len(changed), "pnl_usd": float(ts_.pnl.sum()), "worst_day_usd": float(ds.min()),
            "worst_match_pnl_usd": float(ts_.groupby("cond").pnl.sum().min()),
            "note": "engine.apply_caps daily stop with a fixed $1,000 threshold: day mark = 30 s markout at "
                    "entry + 30 s, remainder at the 4 h lock end (backtest proxy for the live marked P&L)"}
    return out


def theoretical_bound(rate_max: float) -> dict:
    """Worst case per match for buy-and-hold tokens with a gross cap G, |net| <= N and price <= hi."""
    G, N, hi = MATCH_GROSS_CAP, NET_CAP, ZONE_HI
    shares = G / hi
    loss = G - (shares - N) / 2
    fee = rate_max * hi * (1 - hi) * shares
    return {"one_sided_net_cap_x_zone_usd": N * hi,
            "with_backtest_match_gross_cap_usd": loss, "fees_at_bound_usd": fee, "bound_incl_fees_usd": loss + fee,
            "rate_max": rate_max, "assumptions": f"every trade buys a token at q <= {hi} and holds to resolution; "
            f"gross $ per match <= {G:.0f} (engine BASE_MATCH_CAP); |net outcome-0 shares| <= {N:.0f} at all times "
            "(risk-reducing trades allowed). Worst case: buy both tokens at 0.95, net within the cap; "
            "payout = min(A, B) >= (G/0.95 - N)/2. Without the gross cap (live engine RiskConfig has none) "
            "the per-match limits give no bound; only the daily stop does."}


# ------------------------------------------------------------------------------------- IS phase
def run_is() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    f = pd.read_parquet(CACHE / "features_is.parquet")
    wh = pd.read_parquet(CACHE / "whist_is.parquet")
    log(f"IS features {len(f):,} rows, {f.wallet.nunique()} wallets, ts max "
        f"{pd.to_datetime(f.ts.max(), unit='s', utc=True)}")
    ref = json.loads((ROOT / "results/v2/causal.json").read_text())["causal/is_eval/slip0.0"]
    E._WCACHE.clear()
    canon = E.simulate(f, v2.POLICY, "res", "actual", wh)
    base = simulate(f, wh, np.inf, False)
    key = lambda d: d.sort_values(["cond", "ts", "shares"], kind="stable")[["shares", "pnl"]].to_numpy()  # noqa: E731
    assert len(canon) == len(base) and np.allclose(key(canon), key(base), atol=1e-9), "wrapper != engine.simulate"
    be = base[base.month >= E.EVAL_START]
    assert len(be) == ref["n_trades"] and abs(be.pnl.sum() - ref["total_pnl_usd"]) < 1e-6, "baseline != causal.json"
    log(f"baseline reproduces causal.json is_eval: {len(be):,} trades, ${be.pnl.sum():,.2f}")
    ret = retired_flags(f)
    books, rows = {}, []
    for R in RETIRE:
        for W in CAPS:
            tr = simulate(f, wh, W, R, ret=ret)
            books[(W, R)] = tr
            m = book_metrics(tr, IS_CAL)
            m.update({"variant": name(W, R), "W": W, "R": R,
                      "gross_usd_vs_baseline": m["usd_traded"] / books[(np.inf, False)][lambda x: x.month >= E.EVAL_START].usd_in.sum(),
                      "retired_opportunity_usd_share": tr.attrs["retired_usd"] / tr.attrs["opp_usd"]})
            rows.append(m)
            log(f"{m['variant']:>12}: ${m['pnl_usd']:>9,.0f}  {m['per_share_c']:+.3f}c "
                f"[{m['per_share_ci95_c_match'][0]:+.3f},{m['per_share_ci95_c_match'][1]:+.3f}]  SR {m['sharpe_ann_calendar']:.2f}  "
                f"top5 {m['top5_wallet_share_of_pnl']:.2f}  ex5 {m['ex_top5']['per_share_c']:+.3f}c  "
                f"maxW {m['largest_wallet_share_of_gross_usd']:.3f}  worstWD ${m['worst_wallet_day_pnl_usd']:,.0f}")
    by = {r["variant"]: r for r in rows}

    def select(get) -> dict:
        b = get(np.inf, False)
        feas = [W for W in CAPS if np.isfinite(W) and get(W, False)["pnl_usd"] >= FEAS_PNL_FRAC * b["pnl_usd"]
                and get(W, False)["per_share_ci95_c_match"][0] > 0]
        W = min(feas) if feas else np.inf
        off, on = get(W, False), get(W, True)
        R = bool(on["per_share_c"] > off["per_share_c"] and on["sharpe_ann_calendar"] > off["sharpe_ann_calendar"])
        return {"W": W, "R": R, "feasible_W": feas, "variant": name(W, R)}

    sel = select(lambda W, R: by[name(W, R)])
    log("SELECTION (full IS):", sel)
    stab = {}
    for last in ("2026-04", "2026-05", "2026-06", "2026-07"):
        cal = pd.date_range("2026-02-01", pd.Period(last, "M").end_time.date(), freq="D", tz="UTC")
        cache = {}

        def get(W, R, last=last, cal=cal, cache=cache):
            k = (W, R)
            if k not in cache:
                tr = books[k]
                tr = tr[tr.month <= last]
                cache[k] = book_metrics(tr, cal)
            return cache[k]
        stab[f"2026-02..{last}"] = select(get)
    log("stability:", {k: v["variant"] for k, v in stab.items()})
    pml = {"baseline_v2": per_match_loss(base, IS_CAL, simulate(f, wh, np.inf, False, stop_usd=DAILY_STOP)),
           "selected": per_match_loss(books[(sel["W"], sel["R"])], IS_CAL,
                                      simulate(f, wh, sel["W"], sel["R"], stop_usd=DAILY_STOP, ret=ret))}
    res = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "script": "scripts/v2_wallet_cap.py --is", "git_head": git("rev-parse", "HEAD"),
           "grid_md": {"path": str(GRID_MD.relative_to(ROOT)), "sha256": sha256(GRID_MD),
                       "commit": git("log", "-1", "--format=%H %cI", "--", str(GRID_MD.relative_to(ROOT)))},
           "data": {"features": "data/v2_lowloss/features_is.parquet", "features_sha16": sha256(CACHE / "features_is.parquet", 16),
                    "whist": "data/v2_lowloss/whist_is.parquet", "oos_read": False},
           "baseline_check": {"n_trades": int(len(be)), "pnl_usd": float(be.pnl.sum()),
                              "ref": "results/v2/causal.json::causal/is_eval/slip0.0", "identical": True},
           "grid": {"W_usd_per_wallet_day": CAPS, "R": RETIRE, "retire_rule": {"window_days": 30, "lag_s": RET_LAG_S, "min_n": RET_MIN_N,
                    "retire_if": "mean(gross30 - rate*q*(1-q)) <= 0"}},
           "selection_rule": "smallest finite W (R off) with IS $ P&L >= 50% of baseline and match-clustered per-share CI lower > 0; "
                             "R on only if it raises both per-share and calendar Sharpe at that W",
           "selection": sel, "stability_expanding_history": stab, "variants": rows,
           "per_match_loss_is": pml,
           "theoretical_per_match_bound": theoretical_bound(float(f.rate.max()))}
    (OUT / "wallet_cap_is.json").write_text(json.dumps(jsonable(res), indent=1))
    log("wrote", OUT / "wallet_cap_is.json")


# ------------------------------------------------------------------------------------- OOS phase
def run_oos(repro: bool) -> None:
    assert FROZEN_W is not None and FROZEN_R is not None, "rule not frozen in this script"
    rel = str(PREREG_MD.relative_to(ROOT))
    commit = git("log", "-1", "--format=%H %cI", "--", rel)
    assert commit, "PREREG_wallet_cap.md is not committed: no OOS read"
    for p in (rel, "scripts/v2_wallet_cap.py"):
        assert subprocess.run(["git", "diff", "--quiet", "HEAD", "--", p], cwd=ROOT).returncode == 0, f"{p} differs from HEAD"
    isj = json.loads((OUT / "wallet_cap_is.json").read_text())
    assert isj["selection"]["W"] == (None if np.isinf(FROZEN_W) else FROZEN_W) and isj["selection"]["R"] == FROZEN_R
    final = OUT / "wallet_cap.json"
    first = not final.exists()
    assert first or repro, "the burned-OOS run was already done; use --repro to recompute (not a new peek)"
    # --repro recomputes the logged first run: keep its record (first_run) and mark the file as a reproduction
    first_run = first or bool(json.loads(final.read_text()).get("first_run", False))
    if first:   # logged BEFORE any OOS data is read
        with open(PEEKS, "a") as fh:
            fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} v2 per-wallet cap {name(FROZEN_W, FROZEN_R)} "
                     f"evaluated once on burned OOS (non-blind, labelled; PREREG {rel} commit {commit.split()[0][:7]}; "
                     "scripts/v2_wallet_cap.py --oos reads data/v2_lowloss/features_u1 + whist_u1 and "
                     "data/v2_trades_is_oos.parquet; frozen v2 and capped book, plus per-match loss check; "
                     "no parameter chosen) [logged before the run]\n")
    meta = json.loads((CACHE / "features_u1.json").read_text())
    for fpath, h in meta["files"].items():
        assert sha256(ROOT / fpath, 16) == h, f"features_u1 cache is stale for {fpath}"
    f = pd.read_parquet(CACHE / "features_u1.parquet")
    wh = pd.read_parquet(CACHE / "whist_u1.parquet")
    from src.tape import universe
    u = universe()
    oos = set(u.loc[u.oos, "cond"])
    start = u.set_index("cond").start
    log(f"U1 features {len(f):,} rows; {len(oos):,} OOS matches in the universe")
    base = simulate(f, wh, np.inf, False)
    refp = ROOT / "data/v2_trades_is_oos.parquet"
    ref = pd.read_parquet(refp, columns=["cond", "ts", "shares", "pnl"])
    key = lambda d: d.sort_values(["cond", "ts", "shares"], kind="stable")[["shares", "pnl"]].to_numpy()  # noqa: E731
    same = len(ref) == len(base) and np.allclose(key(ref), key(base), atol=1e-9)
    assert same, "frozen v2 from features_u1 differs from data/v2_trades_is_oos.parquet"
    out, pml_books, verdict = evaluate(f, wh, oos, start, IS_CAL, OOS_CAL)
    res = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "script": "scripts/v2_wallet_cap.py --oos", "git_head": git("rev-parse", "HEAD"),
           "label": "burned OOS, NON-BLIND: the rule was designed because the OOS concentration was known; "
                    "parameters chosen on IS only (research/v2/risk/GRID_wallet_cap.md)",
           "prereg": {"path": rel, "commit": commit, "sha256": sha256(PREREG_MD)},
           "frozen_rule": {"variant": name(FROZEN_W, FROZEN_R), "W_usd_per_wallet_day": FROZEN_W, "retire": FROZEN_R},
           "first_run": first_run, "reproduction_of_first_run": not first, "reference_check": {"file": "data/v2_trades_is_oos.parquet", "identical": bool(same),
                                                    "n_trades": int(len(base))},
           "is_selection_run": {"source": "results/v2/risk/wallet_cap_is.json", "selected": isj["selection"],
                                "v2_uncapped": next(v for v in isj["variants"] if v["variant"] == "Winf_Roff"),
                                "with_cap": next(v for v in isj["variants"] if v["variant"] == name(FROZEN_W, FROZEN_R))},
           "verdict": verdict, "oos": out["oos"], "is_joint_run": out["is"]}
    pml = {"limits_stated": {"order_usd": ORDER_USD, "net_cap_shares": NET_CAP, "daily_stop_usd": DAILY_STOP,
                             "zone_hi": ZONE_HI, "backtest_match_gross_cap_usd": MATCH_GROSS_CAP,
                             "paper_claim": "one match can lose at most $95 plus fees (net_cap x zone_hi)"},
           "theoretical": theoretical_bound(float(f.rate.max())), **pml_books,
           "generated_utc": res["generated_utc"], "script": res["script"], "label": res["label"]}
    final.write_text(json.dumps(jsonable(res), indent=1))
    (OUT / "per_match_loss.json").write_text(json.dumps(jsonable(pml), indent=1))
    log("wrote", final, OUT / "per_match_loss.json")


def evaluate(f: pd.DataFrame, wh: pd.DataFrame, oos: set, start: pd.Series, cal_is, cal_oos):
    """Frozen rule vs frozen v2 (+ decomposition) on one joint walk-forward run; books split by match."""
    base = simulate(f, wh, np.inf, False)
    ret = retired_flags(f) if FROZEN_R else None
    capd = simulate(f, wh, FROZEN_W, FROZEN_R, ret=ret)
    cap_only = simulate(f, wh, FROZEN_W, False)                                  # pre-declared decomposition
    ret_only = simulate(f, wh, np.inf, True, ret=ret if ret is not None else retired_flags(f))
    stop_b = simulate(f, wh, np.inf, False, stop_usd=DAILY_STOP)
    stop_c = simulate(f, wh, FROZEN_W, FROZEN_R, stop_usd=DAILY_STOP, ret=ret)

    def split(tr):
        st = tr.cond.map(start)
        assert st.notna().all()
        tr = tr[st < CUTOFF]
        return {"is": tr[(tr.month >= E.EVAL_START) & ~tr.cond.isin(oos)], "oos": tr[tr.cond.isin(oos)]}
    B, C, SB, SC = split(base), split(capd), split(stop_b), split(stop_c)
    D1, D2 = split(cap_only), split(ret_only)
    cal = {"is": cal_is, "oos": cal_oos}
    out = {}
    for per in ("oos", "is"):
        out[per] = {"v2_uncapped": book_metrics(B[per], cal[per]), "with_cap": book_metrics(C[per], cal[per]),
                    "decomposition_cap_only": book_metrics(D1[per], cal[per]),
                    "decomposition_retire_only": book_metrics(D2[per], cal[per])}
        log(per, {k: {x: round(v[x], 3) if isinstance(v[x], float) else v[x] for x in
                      ("pnl_usd", "per_share_c", "per_share_ci95_c_match", "sharpe_ann_calendar",
                       "sharpe_ann_ci95_stationary_bootstrap", "max_dd_usd", "worst_day_usd", "top5_wallet_share_of_pnl")}
                  for k, v in out[per].items()})
    o = out["oos"]
    pass_a = o["with_cap"]["top5_wallet_share_of_pnl"] < o["v2_uncapped"]["top5_wallet_share_of_pnl"]
    pass_b = o["with_cap"]["per_share_c"] > 0 and o["with_cap"]["per_share_ci95_c_match"][0] > 0
    verdict = {"a_top5_share_lower_than_uncapped": bool(pass_a), "b_per_share_ci_excludes_0": bool(pass_b),
               "result": "PASS" if (pass_a and pass_b) else "FAIL"}
    log("VERDICT", verdict)
    pml_books = {per: {"v2_uncapped": per_match_loss(B[per], cal[per], SB[per]),
                       "with_cap": per_match_loss(C[per], cal[per], SC[per])} for per in ("is", "oos")}
    return out, pml_books, verdict


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--is", dest="is_", action="store_true")
    g.add_argument("--oos", action="store_true")
    ap.add_argument("--repro", action="store_true", help="recompute an already-run OOS evaluation (not a new peek)")
    a = ap.parse_args()
    run_is() if a.is_ else run_oos(a.repro)
