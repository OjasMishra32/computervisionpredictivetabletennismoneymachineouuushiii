"""Numbers for docs/RISK.md (risk register). Reads existing result files only.

    .venv/bin/python scripts/risk_stats.py

Inputs (all already in the repo or its data/ cache; nothing is fetched, no strategy is re-run or re-tuned):
  data/v2_trades_is_oos.parquet       frozen causal v2 book, trade level (scripts/v2_causal.py)
  data/expand_v2_trades.parquet       joint U1+U2 run of frozen v2 (research/v2/expand), for the U2 check
  data/expand_universe.parquet        U2 market list
  data/raw/events_tennis_*.parquet    cached Gamma event table (src.tape.universe)
  results/tracking/summary.json, results/tracking/label_audit.json   table-tennis early-call counts
  results/spin/tennis/raw/nominal_s7_m300.parquet                     simulated tennis P(out) calls (if absent,
                                                                      the counts saved in results/risk/spin_tennis_calls.json)
  results/lowloss/daily.csv, research/rigor/out/daily_series.csv     daily P&L series
  results/v2/causal.json, results/v2/cost_stress.json                 reproduction checks
  results/oos_peeks.log                                               peek count

Output: results/risk/risk_stats.json. The burned-OOS rows are the same trades already reported as non-blind in
results/v2/causal.json; this script only slices them (concentration, regime, settlement, stress). It evaluates no
new rule, so it does not append to results/oos_peeks.log.

Conventions follow research/v2/sizing/engine.metrics: IS = months >= 2026-02 and match start before the OOS cut;
burned OOS = U1 matches starting on or after 2026-08-25 14:15 UTC; capital = 3 x peak locked (4 h ex-ante lock);
per-share CIs are match-clustered bootstraps (1,000 draws, seed 0); Sharpe = daily (zero-filled) mean/sd x sqrt(365).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tape import universe  # noqa: E402

# the verified sizing engine, loaded under a private name (avoids the `engine` package name clash)
_spec = importlib.util.spec_from_file_location("v2_sizing_engine", ROOT / "research/v2/sizing/engine.py")
E = importlib.util.module_from_spec(_spec)
sys.modules["v2_sizing_engine"] = E  # dataclasses look the module up by name
_spec.loader.exec_module(E)

OUT = ROOT / "results/risk"
SEED = 0
Z95 = 1.959963984540054


# ---------------------------------------------------------------------------------------------- helpers
def wilson(k: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + Z95**2 / n
    c = (p + Z95**2 / (2 * n)) / d
    h = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def pr(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None, "precision_wilson95": wilson(tp, tp + fp),
            "recall": round(tp / (tp + fn), 4) if tp + fn else None, "recall_wilson95": wilson(tp, tp + fn)}


def cluster_ci(df: pd.DataFrame, n_boot: int = 1000, seed: int = SEED) -> list[float]:
    """Match-clustered bootstrap CI of sum(pnl)/sum(shares), in cents (same draw scheme as engine.metrics)."""
    g = df.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
    if len(g) < 2:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    P, S, k = g.p.to_numpy(), g.s.to_numpy(), len(g)
    bs = []
    for _ in range(n_boot):
        i = rng.integers(0, k, k)
        bs.append(P[i].sum() / S[i].sum())
    return [float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)]


def per_share(df: pd.DataFrame) -> float:
    return float(df.pnl.sum() / df.shares.sum() * 100) if len(df) else float("nan")


def r(x, n=4):
    if isinstance(x, (list, tuple)):
        return [r(v, n) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if not np.isfinite(x) else round(float(x), n)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def tournament(title: str) -> str:
    t = str(title).split(":")[0]
    t = re.sub(r",\s*Qualification.*$", "", t)
    return t.strip()


# ---------------------------------------------------------------------------------------------- data
u = universe()
oos_conds = set(u.loc[u.oos, "cond"])
meta = u.set_index("cond")
tr = pd.read_parquet(ROOT / "data/v2_trades_is_oos.parquet")
tr["tournament"] = tr.cond.map(meta.title).map(tournament)
tr["start"] = tr.cond.map(meta.start)
tr["closed"] = pd.to_datetime(tr.cond.map(meta.closed_time), utc=True, format="mixed")
tr["volume"] = tr.cond.map(meta.volume)
BOOKS = {"is_eval": tr[(tr.month >= E.EVAL_START) & ~tr.cond.isin(oos_conds)].copy(),
         "burned_oos": tr[tr.cond.isin(oos_conds)].copy()}

out: dict = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "script": "scripts/risk_stats.py", "seed": SEED}

# reproduction check against the committed headline numbers
causal = json.loads((ROOT / "results/v2/causal.json").read_text())
chk = {}
for b, df in BOOKS.items():
    ref = causal[f"causal/{b}/slip0.0"]
    m = E.metrics(df)
    chk[b] = {"n_trades": [int(len(df)), ref["n_trades"]], "total_pnl_usd": [r(df.pnl.sum(), 2), r(ref["total_pnl_usd"], 2)],
              "sharpe": [r(m["sharpe_ann"]), r(ref["sharpe_ann"])], "capital_usd": [r(m["capital_usd"], 2), r(ref["capital_usd"], 2)]}
    assert len(df) == ref["n_trades"] and abs(df.pnl.sum() - ref["total_pnl_usd"]) < 1e-6, b
    assert abs(m["sharpe_ann"] - ref["sharpe_ann"]) < 1e-9, b
out["reproduction_check"] = {"vs": "results/v2/causal.json causal/<book>/slip0.0", "books": chk, "ok": True}
CAP = {b: E.metrics(df)["capital_usd"] for b, df in BOOKS.items()}


# ---------------------------------------------------------------------------------------------- 1. concentration
def concentration(df: pd.DataFrame, key: str, k_list=(1, 5, 10)) -> dict:
    g = df.groupby(key).agg(pnl=("pnl", "sum"), shares=("shares", "sum"), n=("pnl", "size")).sort_values("pnl", ascending=False)
    tot = g.pnl.sum()
    pos = g.pnl[g.pnl > 0].sum()
    res = {"n_units": int(len(g)), "total_pnl_usd": r(tot, 2), "gross_positive_pnl_usd": r(pos, 2),
           "units_with_positive_pnl": int((g.pnl > 0).sum())}
    for k in k_list:
        top = g.pnl.head(k).sum()
        res[f"top{k}_pnl_usd"] = r(top, 2)
        res[f"top{k}_share_of_net_pct"] = r(top / tot * 100, 1) if tot else None
        res[f"top{k}_share_of_gross_positive_pct"] = r(top / pos * 100, 1) if pos else None
    top5 = list(g.index[:5])
    rest = df[~df[key].isin(top5)]
    res["ex_top5_pnl_usd"] = r(rest.pnl.sum(), 2)
    res["ex_top5_per_share_c"] = r(per_share(rest))
    res["ex_top5_per_share_ci_c"] = r(cluster_ci(rest))
    res["top5_share_of_trades_pct"] = r(df[key].isin(top5).mean() * 100, 1)
    res["top5_share_of_shares_pct"] = r(df.loc[df[key].isin(top5), "shares"].sum() / df.shares.sum() * 100, 1)
    lab = (lambda x: str(x)[:10]) if key in ("wallet", "cond") else str
    res["top5"] = [{"unit": lab(i), "pnl_usd": r(v, 2), "n_trades": int(g.n[i])} for i, v in g.pnl.head(5).items()]
    res["worst5"] = [{"unit": lab(i), "pnl_usd": r(v, 2), "n_trades": int(g.n[i])} for i, v in g.pnl.tail(5)[::-1].items()]
    return res


conc = {}
for b, df in BOOKS.items():
    df = df.assign(day=df.date.dt.strftime("%Y-%m-%d"))
    conc[b] = {"wallet": concentration(df, "wallet"), "match": concentration(df, "cond"),
               "day": concentration(df, "day"), "tournament": concentration(df, "tournament")}
# U2-OOS (blind out-of-universe) wallet concentration, as a check of the NOTE's "top five carry 98%"
x = pd.read_parquet(ROOT / "data/expand_v2_trades.parquet")
u2 = pd.read_parquet(ROOT / "data/expand_universe.parquet")
u2oos = set(u2.loc[u2.oos, "cond"])
x = x[(x.month >= E.EVAL_START) & x.cond.isin(u2oos)]
conc["u2_oos_blind_wallet"] = concentration(x, "wallet")
conc["u2_oos_blind_wallet"]["n_trades"] = int(len(x))
out["concentration"] = conc


# ---------------------------------------------------------------------------------------------- 2. settlement
SET_RE = re.compile(r"^\s*(\d+)-(\d+)")


def score_complete(score) -> str:
    """'complete' | 'incomplete' (retired/abandoned after play started) | 'not_started' ('0-0': walkover or
    cancellation) | 'none' (no score string)."""
    if not isinstance(score, str) or not score.strip():
        return "none"
    sets = [s.strip() for s in score.split(",") if s.strip()]
    if all(re.fullmatch(r"0-0", x) for x in sets):
        return "not_started"
    won = [0, 0]
    last_ok = False
    for s in sets:
        m = SET_RE.match(s)
        if not m:
            return "unparsed"
        a, b = int(m.group(1)), int(m.group(2))
        hi, lo = max(a, b), min(a, b)
        ok = (hi == 6 and lo <= 4) or (hi == 7 and lo in (5, 6)) or (hi > 7 and hi - lo == 2)  # incl. long final sets
        last_ok = ok
        if ok:
            won[0 if a > b else 1] += 1
    return "complete" if last_ok and max(won) >= 2 else "incomplete"


u["score_state"] = u.score.map(score_complete)
u["res_class"] = np.where(u.res0 == 0.5, "50/50", "winner")
fin = pd.to_datetime(u.finished, utc=True, format="mixed")
cl = pd.to_datetime(u.closed_time, utc=True, format="mixed")
lag_h = (cl - fin).dt.total_seconds() / 3600
start_to_close_h = (cl - u.start).dt.total_seconds() / 3600
settle = {"universe_matches": int(len(u))}
for name, part in (("all", u), ("is", u[~u.oos]), ("oos", u[u.oos])):
    settle[name] = {"n": int(len(part)), "res_50_50": int((part.res0 == 0.5).sum()),
                    "res_50_50_pct": r((part.res0 == 0.5).mean() * 100, 2),
                    "score_state_by_resolution": {k: {kk: int(vv) for kk, vv in v.items()} for k, v in
                                                  part.groupby("res_class").score_state.value_counts().unstack(fill_value=0).to_dict("index").items()}}
inc = u[u.score_state == "incomplete"]
settle["incomplete_score_resolution_by_month_note"] = ("matches whose final score shows play started but no "
    "player finished the match (retirement/abandonment), by start month: how they resolved")
settle["incomplete_score_resolution_by_month"] = {
    str(k): {"res_50_50": int((g.res0 == 0.5).sum()), "res_to_a_player": int((g.res0 != 0.5).sum())}
    for k, g in inc.groupby(inc.start.dt.strftime("%Y-%m"))}
ok = lag_h.notna()
settle["close_minus_finish_hours"] = {"n_with_finish_stamp": int(ok.sum()), "n_missing_finish": int((~ok).sum()),
                                      "quantiles": {q: r(lag_h[ok].quantile(q), 3) for q in (0.5, 0.9, 0.99, 0.999)},
                                      "max": r(lag_h[ok].max(), 1),
                                      "over_24h": int((lag_h > 24).sum()), "over_72h": int((lag_h > 72).sum()),
                                      "over_7d": int((lag_h > 168).sum()), "negative": int((lag_h < 0).sum()),
                                      "note": "Gamma closedTime minus finishedTimestamp. UMA dispute status is not in the cached event "
                                              "table, so long gaps are a proxy for disputes/late settlement, not a count of disputes."}
settle["start_to_close_hours"] = {q: r(start_to_close_h.quantile(q), 2) for q in (0.5, 0.9, 0.99)}
settle["start_to_close_over_4h_pct"] = r((start_to_close_h > 4).mean() * 100, 1)
# exposure of the v2 book to each settlement class
expo = {}
st = u.set_index("cond")
for b, df in BOOKS.items():
    s = df.cond.map(st.score_state)
    lg = df.cond.map(pd.Series(lag_h.values, index=u.cond))
    rows = {}
    for lab, mask in (("res_50_50", df.res == 0.5), ("score_incomplete_retired", s == "incomplete"),
                      ("no_score", s == "none"), ("score_0_0_not_started", s == "not_started"), ("close_gt_24h_after_finish", lg > 24),
                      ("close_gt_72h_after_finish", lg > 72)):
        rows[lab] = {"trades": int(mask.sum()), "matches": int(df.loc[mask, "cond"].nunique()),
                     "pnl_usd": r(df.loc[mask, "pnl"].sum(), 2),
                     "share_of_book_pnl_pct": r(df.loc[mask, "pnl"].sum() / df.pnl.sum() * 100, 1)}
    expo[b] = rows
settle["v2_book_exposure"] = expo
settle["retirement_rule"] = ("Current Polymarket tennis rule (market page, Oct 2026): a retirement after the start resolves to "
                             "the advancing player; walkover, cancellation, tie or no winner within 14 days resolves 50-50.")
out["settlement"] = settle


# ---------------------------------------------------------------------------------------------- 3. CV calls
trk = json.loads((ROOT / "results/tracking/summary.json").read_text())["early_call"]
aud = json.loads((ROOT / "results/tracking/label_audit.json").read_text())
cv = {"table_tennis_120fps": {"source": "results/tracking/summary.json early_call; labels audited in label_audit.json",
                              "n_test_miss": 41, "n_test_bounce": 130}}
for key, lab in (("precision_recall_test_snapshot", "test_snapshot_primary"), ("precision_recall_test_online", "test_online"),
                 ("precision_recall_train_oof_snapshot", "train_oof_snapshot")):
    cv["table_tennis_120fps"][lab] = {lead: pr(v["tp"], v["fp"], v["fn"]) for lead, v in trk[key].items()}
for key in ("test_audited_relabelled", "test_audited_drop_rally_continues"):
    cv["table_tennis_120fps"][key] = {lead: pr(v["tp"], v["fp"], v["fn"]) for lead, v in aud[key]["snapshot"].items()}
    cv["table_tennis_120fps"][key + "_n_miss"] = aud[key]["n_miss"]
SPIN_RAW = ROOT / "results/spin/tennis/raw/nominal_s7_m300.parquet"
SPIN_CACHE = OUT / "spin_tennis_calls.json"   # counts kept so the register reproduces if the raw run is re-generated
if SPIN_RAW.exists():
    sp = pd.read_parquet(SPIN_RAW)
    sp = sp[sp.cond == "nominal"]
    spin = {}
    for (meth, lead), g in sp.groupby(["method", "lead_ms"]):
        if g.p_out.isna().any() or lead not in (0, 100, 200, 300, 400):
            continue
        is_out = (g.d > 0).to_numpy()
        call = (g.p_out >= 0.95).to_numpy()
        spin.setdefault(meth, {})[int(lead)] = {**pr(int((call & is_out).sum()), int((call & ~is_out).sum()),
                                                     int((~call & is_out).sum())),
                                                "n_shots": int(len(g)), "n_out": int(is_out.sum())}
    spin_blk = {"source": "results/spin/tennis/raw/nominal_s7_m300.parquet (physics simulation, Hawk-Eye-class camera "
                          "world, not real footage); call = P(out) >= 0.95",
                "by_method_lead_ms": spin}
    OUT.mkdir(parents=True, exist_ok=True)
    SPIN_CACHE.write_text(json.dumps({"computed_utc": out["generated_utc"], **spin_blk}, indent=1))
else:
    spin_blk = json.loads(SPIN_CACHE.read_text())
    spin_blk["note"] = f"raw parquet absent at run time; counts from {SPIN_CACHE.relative_to(ROOT)}"
cv["tennis_simulated_spin_pout95"] = spin_blk
# how many consecutive correct calls (no false call) before the 95% Wilson lower bound on precision reaches 0.95
n_needed = next(n for n in range(1, 10_000) if wilson(n, n)[0] >= 0.95)
cv["calls_needed_for_precision_lb_0.95_with_zero_false"] = n_needed
out["cv_calls"] = cv


# ---------------------------------------------------------------------------------------------- 4. execution, liquidity, capital
liq = {}
for b, df in BOOKS.items():
    part = (df.shares / df.their_shares).replace([np.inf], np.nan)
    # engine.month_targets already caps the risk-parity size at the copied print; apply_caps then cuts by the
    # $3k gross per-match cap and the 100-share net cap
    target_is_print = np.isclose(df.target, df.their_shares)
    cut = df.shares < df.target - 1e-9
    so = df.sort_values("ts", kind="stable")
    net_path = (so.dir * so.shares).groupby(so.cond).cumsum()
    gross_match = df.groupby("cond").usd_in.sum()
    # realised lock: from fill to the market's close (resolution) time
    lock_real_h = (df.closed - pd.to_datetime(df.ts, unit="s", utc=True)).dt.total_seconds() / 3600
    real = df.assign(lock_end=df.ts + lock_real_h.clip(lower=0).fillna(4).to_numpy() * 3600)
    peak_real = E.peak_locked(real)
    m = df.groupby(df.month).agg(usd=("usd_in", "sum"))
    liq[b] = {"trades": int(len(df)), "usd_traded": r(df.usd_in.sum(), 2),
              "usd_per_trade_quantiles": {q: r(df.usd_in.quantile(q), 2) for q in (0.5, 0.9, 0.99)},
              "max_usd_per_trade": r(df.usd_in.max(), 2), "max_shares_per_trade": r(df.shares.max(), 1),
              "participation_of_copied_print": {q: r(part.quantile(q), 3) for q in (0.5, 0.9)},
              "target_bound_by_copied_print_pct": r(target_is_print.mean() * 100, 1),
              "size_cut_by_match_caps_pct": r(cut.mean() * 100, 1),
              "max_abs_net_shares_any_match": r(net_path.abs().max(), 2),
              "gross_usd_per_match_quantiles": {q: r(gross_match.quantile(q), 2) for q in (0.5, 0.99)},
              "max_gross_usd_any_match": r(gross_match.max(), 2),
              "match_gross_cap_3k_ever_binds": bool(gross_match.max() >= 3000 - 1e-6),
              "peak_locked_usd_4h_ex_ante": r(E.peak_locked(df), 2),
              "peak_locked_usd_realised_close": r(peak_real, 2),
              "realised_lock_hours_quantiles": {q: r(lock_real_h.quantile(q), 2) for q in (0.5, 0.9, 0.99)},
              "realised_lock_over_4h_pct": r((lock_real_h > 4).mean() * 100, 1),
              "capital_usd_3x_peak_4h": r(CAP[b], 2), "capital_usd_3x_peak_realised": r(3 * peak_real, 2),
              "usd_traded_by_month": {k: r(v, 0) for k, v in m.usd.items()}}
    # concurrency: open matches at once (4 h lock)
    ev = pd.concat([pd.DataFrame({"t": df.groupby("cond").ts.min(), "d": 1}),
                    pd.DataFrame({"t": df.groupby("cond").ts.max() + 4 * 3600, "d": -1})]).sort_values("t", kind="stable")
    liq[b]["max_concurrent_open_matches_4h"] = int(ev.d.cumsum().max())
wf = pd.read_csv(ROOT / "results/fasttier_walkforward_is.csv")
fast_usd = dict(zip(wf.month, wf.usd_k * 1e3))
summ = json.loads((ROOT / "results/summary.json").read_text())
for row in summ["oos"]["h6_walkforward"]:
    fast_usd.setdefault(row["month"] + " (OOS, onset-labelled)", row["usd_k"] * 1e3)
liq["fast_tier_0_3s_usd_by_month"] = {k: r(v, 0) for k, v in fast_usd.items()}
liq["v2_share_of_fast_tier_usd_is_pct"] = {mo: r(liq["is_eval"]["usd_traded_by_month"].get(mo, 0) / fast_usd[mo] * 100, 1)
                                           for mo in wf.month if mo >= E.EVAL_START}
out["liquidity_capital"] = liq


# ---------------------------------------------------------------------------------------------- 5. signal decay, regime
decay, regime, month = {}, {}, {}
for b, df in BOOKS.items():
    decay[b] = {f"since_detection_{int(s)}s": {"trades": int(len(g)), "per_share_c": r(per_share(g)), "ci_c": r(cluster_ci(g)),
                                               "pnl_usd": r(g.pnl.sum(), 2)}
                for s, g in df.groupby(df.since_det.round())}
    regime[b] = {}
    for k, g in df.groupby("regime"):
        m = E.metrics(g)
        regime[b][k] = {"trades": int(len(g)), "matches": int(g.cond.nunique()), "per_share_c": r(per_share(g)),
                        "ci_c": r(cluster_ci(g)), "pnl_usd": r(g.pnl.sum(), 2), "active_days": int(g.date.nunique()),
                        "sharpe_ann_own_calendar": r(m["sharpe_ann"], 2)}
    month[b] = {k: {"trades": int(len(g)), "per_share_c": r(per_share(g)), "pnl_usd": r(g.pnl.sum(), 2)}
                for k, g in df.groupby("month")}
out["signal_decay_within_window"] = decay
out["regime"] = regime
out["by_month"] = month


# ---------------------------------------------------------------------------------------------- 6. correlation
corr = {}
dl = pd.read_csv(ROOT / "research/rigor/out/daily_series.csv", index_col=0)
c_is = dl[["v2_is", "v2safe_is"]].dropna()
c_oos = dl[["v2_oos", "v2safe_oos", "v2_u2oos_blind"]].dropna()
corr["v2_vs_v2safe_daily_is"] = r(c_is.v2_is.corr(c_is.v2safe_is), 3)
corr["v2_vs_v2safe_daily_burned_oos"] = r(c_oos.v2_oos.corr(c_oos.v2safe_oos), 3)
corr["v2_u1_oos_vs_v2_u2_oos_daily"] = r(c_oos.v2_oos.corr(c_oos.v2_u2oos_blind), 3)
for b, df in BOOKS.items():
    mp = df.groupby(["date", "cond"]).pnl.sum()
    mu = mp.mean()
    xd = (mp - mu)
    num = (xd.groupby(level=0).sum() ** 2).sum()
    den = (xd ** 2).sum()
    nd = mp.groupby(level=0).size()
    n_eff = float((nd ** 2).sum() / nd.sum())
    vr = float(num / den)
    corr[b] = {"variance_ratio_day_sum_vs_independent": r(vr, 3),
               "implied_mean_pairwise_corr_same_day": r((vr - 1) / (n_eff - 1), 4) if n_eff > 1 else None,
               "matches_per_active_day_mean": r(nd.mean(), 1),
               "lag1_autocorr_daily": r(E.daily_series(df).autocorr(1), 3)}
out["correlation"] = corr


# ---------------------------------------------------------------------------------------------- 7. stress
def fee_at(q, rate):
    return rate * q * (1 - q)


def worst_quartile_penalty(df: pd.DataFrame) -> tuple[pd.Series, float, float]:
    """Price add-on if every fill lands at the worst quartile of the fast tier's own fills in the same burst.

    Burst = same match, same direction, prints <= 3 s apart (all inside one causal 0-3 s window). Within a burst of
    2+ v2 trades the add-on is max(0, q75 - q) on the token price paid. Singletons get the pooled p75 of
    (q - burst best price) over multi-trade bursts. Fee is re-charged at the worse price."""
    t = df.sort_values(["cond", "dir", "ts"], kind="stable")
    new = (t.cond != t.cond.shift()) | (t.dir != t.dir.shift()) | (t.ts - t.ts.shift() > 3)
    cl = new.cumsum()
    size = cl.map(cl.value_counts())
    q75 = t.groupby(cl).q.transform(lambda s: s.quantile(0.75))
    qmin = t.groupby(cl).q.transform("min")
    multi = size > 1
    pooled = float((t.q - qmin)[multi].quantile(0.75))
    add = np.where(multi, np.maximum(0.0, q75 - t.q), pooled)
    return pd.Series(add, index=t.index).reindex(df.index), pooled, float(multi.mean())


def late_cost(df: pd.DataFrame) -> pd.Series:
    """src/fasttier.py follower: enter at +delay+3 s (move to mo5 or mo15) and pay half the spread (1c default)."""
    lag_mo = np.where(df.delay >= 3, df.mo15, df.mo5)
    return pd.Series(np.nan_to_num(lag_mo, nan=0.0) + df.spread.fillna(0.01).to_numpy() / 2, index=df.index)


stress = {}
for b, df in BOOKS.items():
    add_wq, pooled, frac_multi = worst_quartile_penalty(df)
    q_wq = (df.q + add_wq).clip(upper=0.999)
    wq_cost = add_wq + fee_at(q_wq, df.rate) - fee_at(df.q, df.rate)
    lc = late_cost(df)
    scen = {
        "base": df.pnl_ps,
        "fees_x2": df.pnl_ps - df.fee,
        "costs_x2 (fee x2 + 0.5c)": df.pnl_ps - df.fee - 0.005,
        "slippage +0.5c (half tick)": df.pnl_ps - 0.005,
        "slippage +1c (one tick)": df.pnl_ps - 0.01,
        "fills at worst quartile of the burst": df.pnl_ps - wq_cost,
        "late entry: copy at +delay+3 s": df.pnl_ps - lc,
        "fees_x2 + worst-quartile fills": df.pnl_ps - df.fee - wq_cost,
    }
    rows = {}
    for name, ps in scen.items():
        q = df.assign(pnl_ps=ps, pnl=df.shares * ps)
        m = E.metrics(q, capital=CAP[b])
        rows[name] = {"per_share_c": r(m["per_share_c"]), "ci_c": r(m["per_share_ci_c"]), "pnl_usd": r(m["total_pnl_usd"], 2),
                      "sharpe_ann": r(m["sharpe_ann"], 2), "max_dd_pct_of_base_capital": r(m["max_dd_pct"], 2),
                      "worst_day_usd": r(m["worst_day_usd"], 2), "months_positive": f'{m["months_positive"]}/{m["months_total"]}'}
    daily = E.daily_series(df)
    sd, mean = float(daily.std()), float(daily.mean())
    rows["_assumptions"] = {"worst_quartile_pooled_addon_c": r(pooled * 100, 3),
                            "share_of_trades_in_multi_trade_bursts_pct": r(frac_multi * 100, 1),
                            "worst_quartile_mean_addon_c": r(wq_cost.mean() * 100, 3),
                            "late_entry_mean_cost_c": r(lc.mean() * 100, 3),
                            "capital_usd": r(CAP[b], 2)}
    rows["tail_day"] = {"daily_mean_usd": r(mean, 2), "daily_sd_usd": r(sd, 2),
                        "five_sigma_loss_day_usd": r(-5 * sd, 2), "five_sigma_loss_pct_of_capital": r(-5 * sd / CAP[b] * 100, 2),
                        "worst_day_usd": r(daily.min(), 2), "worst_day_in_sd": r((daily.min() - mean) / sd, 2),
                        "days_below_mean_minus_3sd": int((daily < mean - 3 * sd).sum()), "days": int(len(daily)),
                        "daily_stop_usd_engine": 1000.0,
                        "five_sigma_vs_daily_stop": r(5 * sd / 1000.0, 2),
                        "daily_stop_in_sd": r(1000.0 / sd, 2),
                        "peak_locked_usd_all_open_positions_lose": r(E.peak_locked(df), 2),
                        "peak_locked_pct_of_capital": r(E.peak_locked(df) / CAP[b] * 100, 1),
                        "worst_match_usd": r(df.groupby("cond").pnl.sum().min(), 2)}
    stress[b] = rows
# cross-check against the committed cost stress
cs = json.loads((ROOT / "results/v2/cost_stress.json").read_text())
for b in BOOKS:
    for k_ours, k_ref in (("base", "base"), ("fees_x2", "fee_x2"), ("costs_x2 (fee x2 + 0.5c)", "costs_x2")):
        assert abs(stress[b][k_ours]["pnl_usd"] - cs[f"{b}/{k_ref}"]["total_pnl_usd"]) < 0.01, (b, k_ours)
stress["cross_check"] = "base, fees_x2 and costs_x2 equal results/v2/cost_stress.json to the cent"
out["stress"] = stress


# ---------------------------------------------------------------------------------------------- 7b. fixed-cost breakeven
# annualised P&L of the paper book (calendar days incl. zero days): the most a fixed annual cost (data licence,
# camera crew, co-location) could be before it consumes the whole measured opportunity at v2's caps
out["fixed_cost_breakeven"] = {b: {"days": int(len(E.daily_series(df))), "pnl_usd": r(df.pnl.sum(), 2),
                                   "annualised_pnl_usd": r(df.pnl.sum() / len(E.daily_series(df)) * 365, 0)}
                               for b, df in BOOKS.items()}

# ---------------------------------------------------------------------------------------------- 8. overfitting bookkeeping
peeks = [ln for ln in (ROOT / "results/oos_peeks.log").read_text().splitlines() if ln.strip()]
rig = json.loads((ROOT / "results/rigor/rigor.json").read_text())
out["overfitting"] = {"oos_peeks_logged": len(peeks), "oos_peeks_first": peeks[0][:19], "oos_peeks_last": peeks[-1][:19],
                      "trial_counts": rig["psr_dsr"]["N"],
                      "pbo_lowloss_sharpe": r(rig["pbo_cscv"]["lowloss_24_sharpe"]["pbo"], 3),
                      "pbo_lowloss_selection_rule": r(rig["pbo_cscv"]["lowloss_24_selection_rule"]["pbo"], 3),
                      "pbo_sizing_55": r(rig["pbo_cscv"]["sizing_55_res_actual_sharpe"]["pbo"], 3),
                      "min_trl_days": {k: r(v["min_trl_days_vs_0"], 1) for k, v in rig["min_trl"].items()}}

# ---------------------------------------------------------------------------------------------- 9. universe filter (survivorship / look-ahead)
uv = {}
for b, df in BOOKS.items():
    bands = pd.cut(df.volume, [5e3, 2e4, 1e5, 1e6, np.inf], right=False, labels=["$5-20k", "$20-100k", "$0.1-1M", ">$1M"])
    uv[b] = {str(k): {"trades": int(len(g)), "per_share_c": r(per_share(g)), "pnl_usd": r(g.pnl.sum(), 2)}
             for k, g in df.groupby(bands, observed=True)}
uv["note"] = ("The universe keeps markets whose FINAL lifetime volume is >= $5k (src/tape.py), which is not known at "
              "match start. This table shows how much P&L sits near the threshold.")
out["universe_volume_filter"] = uv

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "risk_stats.json").write_text(json.dumps(out, indent=1, default=str))
print(json.dumps({"concentration_wallet_top5_net_pct": {b: conc[b]["wallet"]["top5_share_of_net_pct"] for b in BOOKS},
                  "u2_oos_wallet_top5_net_pct": conc["u2_oos_blind_wallet"]["top5_share_of_net_pct"],
                  "written": str(OUT / "risk_stats.json")}, indent=1))
