"""Independent recomputation of numbers quoted in research/financials/FINANCIALS.md and docs/RISK.md.

    .venv/bin/python scripts/financials_audit.py      # about 5 s, 1 process

Reads data/v2_trades_is_oos.parquet (plus the universe's match start times for the IS / burned-OOS split, the
maker fill books, and the cost assumptions) and recomputes each number with plain pandas / numpy. It does not call
the repo's metric code (research/v2/sizing/engine.py metrics / daily_series / peak_locked, scripts/financials.py
helpers, scripts/risk_stats.py), so an error there would show up as a mismatch here. It compares every value with
the number the docs quote (results/financials/financials.json, results/risk/risk_stats.json,
results/financials/pm_compute.json) and writes results/financials/audit_recompute.json. Analysis of existing results
only: no rule is changed, nothing is selected, and the burned-OOS book read here is the one already logged in
results/oos_peeks.log.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tape import universe  # noqa: E402  (match start times only)

CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")
OUT = ROOT / "results/financials/audit_recompute.json"


def jl(p):
    return json.loads((ROOT / p).read_text())


def cal_daily(b: pd.DataFrame) -> pd.Series:
    d = pd.to_datetime(b.ts, unit="s", utc=True).dt.floor("D")
    s = b.pnl.groupby(d).sum()
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D", tz="UTC"), fill_value=0.0)


def peak_locked(b: pd.DataFrame, locks_first: bool) -> float:
    df = pd.DataFrame({"t": np.r_[b.ts.to_numpy(), b.lock_end.to_numpy()],
                       "v": np.r_[b.usd_in.to_numpy(), -b.usd_in.to_numpy()]})
    return float(df.sort_values(["t", "v"], ascending=[True, not locks_first]).v.cumsum().max())


def book(b: pd.DataFrame) -> dict:
    d = cal_daily(b)
    eq = d.cumsum().to_numpy()
    dd = float((eq - np.maximum.accumulate(np.r_[0.0, eq])[1:]).min())
    fee = float((b.rate * b.q * (1 - b.q) * b.shares).sum())
    gross = float((b.gross_res * b.shares).sum())
    cap = 3 * peak_locked(b, locks_first=True)
    return {"n_trades": len(b), "n_matches": int(b.cond.nunique()), "pnl_usd": float(b.pnl.sum()),
            "per_share_c": float(b.pnl.sum() / b.shares.sum() * 100), "days": len(d),
            "pnl_per_day": float(d.mean()), "daily_sd": float(d.std(ddof=1)),
            "sharpe": float(d.mean() / d.std(ddof=1) * np.sqrt(365)), "max_dd_usd": dd, "worst_day": float(d.min()),
            "capital": cap, "capital_releases_first": 3 * peak_locked(b, locks_first=False),
            "fee_share_of_gross": fee / gross, "breakeven_fee_k": gross / fee, "gross": gross, "fee": fee,
            "win_rate": float((b.pnl > 0).mean()), "profit_factor": float(b.pnl[b.pnl > 0].sum() / -b.pnl[b.pnl < 0].sum()),
            "median_hold_h": float(((b.end_ts - b.ts) / 3600).median()), "notional_per_day": float(b.usd_in.sum() / len(d))}


def main():
    t0 = dt.datetime.now(dt.timezone.utc)
    u = universe()
    oos_c = set(u.loc[u.start >= CUT, "cond"])
    tr = pd.read_parquet(ROOT / "data/v2_trades_is_oos.parquet")
    tr = tr[tr.month >= "2026-02"]
    IS, OOS = tr[~tr.cond.isin(oos_c)], tr[tr.cond.isin(oos_c)]
    cur = IS[IS.regime == "1s/5%"]
    bi, bo, bc = book(IS), book(OOS), book(cur)

    F = jl("results/financials/financials.json")
    RS = jl("results/risk/risk_stats.json")
    PM = jl("results/financials/pm_compute.json")
    fv = F["strategies"]["v2"]["periods"]
    fixc = F["strategies"]["v2"]["cost"]["daily"]["central"]

    # wallet concentration and wallet-clustered CI (own bootstrap, seed 0, 2,000 draws)
    wid = OOS.groupby("wallet").agg(p=("pnl", "sum"), s=("shares", "sum"))          # wallets in id order
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(wid), size=(2000, len(wid)))
    est = wid.p.to_numpy()[idx].sum(1) / wid.s.to_numpy()[idx].sum(1) * 100
    wci = list(np.percentile(est, [2.5, 97.5]))     # Monte Carlo: compared with a 0.05c tolerance
    w = wid.sort_values("p", ascending=False)

    # tier-0 fixed costs from the published cost assumptions (own arithmetic)
    C = F["cost_assumptions"]
    dpm = 365 / 12
    cov = F["strategies"]["tier0"]["cost"]["items"]["events_per_day"]["central"]

    def t0cost(lvl):
        mo = C["feed_licence"][lvl] + C["vps_london"][lvl]
        ev = C["event_hours"][lvl] * (C["camera_operator"][lvl] + C["gpu_inference"][lvl]) + C["venue_access"][lvl]
        return mo / dpm + cov * ev + cov * C["camera_kit"][lvl] / 24 / dpm

    # maker fill books
    mk = pd.read_parquet(ROOT / "data/v2_crossmarket/wf_lean_maker.parquet")
    mo = pd.read_csv(ROOT / "research/v2/maker/oos/book_v1.csv")
    fm = F["strategies"]["maker"]["periods"]

    checks = [
        # (what, ours, quoted, source of the quoted number, abs tolerance)
        ("v2 IS net P&L $", bi["pnl_usd"], fv["IS"]["capital_returns"]["pnl_usd"], "financials.json v2.IS", 0.01),
        ("v2 IS trades", bi["n_trades"], fv["IS"]["unit_economics"]["n_trades"], "financials.json v2.IS", 0),
        ("v2 IS net c/share", bi["per_share_c"], fv["IS"]["per_share_c"], "financials.json v2.IS", 1e-9),
        ("v2 IS Sharpe", bi["sharpe"], fv["IS"]["capital_returns"]["sharpe_ann"], "financials.json v2.IS", 1e-6),
        ("v2 IS capital $ (3 x peak locked, 4 h lock)", bi["capital"], fv["IS"]["capital_returns"]["capital_usd"], "financials.json v2.IS", 0.01),
        ("v2 IS max drawdown $", bi["max_dd_usd"], fv["IS"]["capital_returns"]["max_dd_usd"], "financials.json v2.IS", 0.01),
        ("v2 IS taker fees share of gross", bi["fee_share_of_gross"], fv["IS"]["breakeven_taker_fee"]["fee_share_of_gross"], "financials.json v2.IS", 1e-9),
        ("v2 IS trade win rate", bi["win_rate"], fv["IS"]["unit_economics"]["trade_win_rate"], "financials.json v2.IS", 1e-9),
        ("v2 IS profit factor", bi["profit_factor"], fv["IS"]["unit_economics"]["profit_factor"], "financials.json v2.IS", 1e-9),
        ("v2 IS median hours entry to resolution", bi["median_hold_h"], fv["IS"]["unit_economics"]["hold_hours_to_resolution"]["median"], "financials.json v2.IS", 1e-6),
        ("v2 IS daily sd $", bi["daily_sd"], RS["stress"]["is_eval"]["tail_day"]["daily_sd_usd"], "risk_stats stress.is_eval.tail_day", 0.01),
        ("v2 IS $1,000 stop in sigma", 1000 / bi["daily_sd"], RS["stress"]["is_eval"]["tail_day"]["daily_stop_in_sd"], "risk_stats stress.is_eval.tail_day", 0.01),
        ("v2 IS net after central fixed costs $/day", bi["pnl_per_day"] - fixc,
         fv["IS"]["fixed_costs"]["central"]["net_after_costs_usd_per_day"], "financials.json v2.IS", 1e-6),
        ("v2 IS 1 s/5% trades", bc["n_trades"], fv["IS_1s5"]["unit_economics"]["n_trades"], "financials.json v2.IS_1s5", 0),
        ("v2 IS 1 s/5% net P&L $/day", bc["pnl_per_day"], fv["IS_1s5"]["unit_economics"]["per_day_usd"], "financials.json v2.IS_1s5", 1e-6),
        ("v2 IS 1 s/5% Sharpe", bc["sharpe"], fv["IS_1s5"]["capital_returns"]["sharpe_ann"], "financials.json v2.IS_1s5", 1e-6),
        ("v2 OOS net P&L $", bo["pnl_usd"], fv["OOS"]["capital_returns"]["pnl_usd"], "financials.json v2.OOS", 0.01),
        ("v2 OOS net c/share", bo["per_share_c"], fv["OOS"]["per_share_c"], "financials.json v2.OOS", 1e-9),
        ("v2 OOS Sharpe", bo["sharpe"], fv["OOS"]["capital_returns"]["sharpe_ann"], "financials.json v2.OOS", 1e-6),
        ("v2 OOS capital $ (3 x peak locked)", bo["capital"], fv["OOS"]["capital_returns"]["capital_usd"], "financials.json v2.OOS", 0.01),
        ("v2 OOS taker fees share of gross", bo["fee_share_of_gross"], fv["OOS"]["breakeven_taker_fee"]["fee_share_of_gross"], "financials.json v2.OOS", 1e-9),
        ("v2 OOS break-even fee multiple, before fixed costs", bo["breakeven_fee_k"], fv["OOS"]["breakeven_taker_fee"]["fee_multiple_before_fixed_costs"], "financials.json v2.OOS", 1e-9),
        ("v2 OOS break-even fee multiple, after central fixed costs", (bo["gross"] - fixc * bo["days"]) / bo["fee"],
         fv["OOS"]["breakeven_taker_fee"]["fee_multiple_after_central_fixed_costs"], "financials.json v2.OOS", 1e-9),
        ("v2 OOS annualised return on IS capital %", bo["pnl_usd"] / bi["capital"] * 100 * 365 / bo["days"],
         next((x["return_ann_pct"] for x in fv["OOS"]["capital_returns"].get("fixed_capital", []) if x.get("what") == "IS capital"), None),
         "financials.json v2.OOS fixed_capital", 1e-6),
        ("v2 OOS top-1 wallet share of P&L %", float(w.p.iloc[0] / w.p.sum() * 100), RS["concentration"]["burned_oos"]["wallet"]["top1_share_of_net_pct"], "risk_stats concentration", 0.05),
        ("v2 OOS top-5 wallet share of P&L %", float(w.p.iloc[:5].sum() / w.p.sum() * 100), RS["concentration"]["burned_oos"]["wallet"]["top5_share_of_net_pct"], "risk_stats concentration", 0.05),
        ("v2 OOS wallet-clustered CI low (c)", wci[0], PM["p07_wallet_clustered_ci"]["burned_oos"]["ci95_c_wallet_clustered"][0], "pm_compute p07", 0.05),
        ("v2 OOS wallet-clustered CI high (c)", wci[1], PM["p07_wallet_clustered_ci"]["burned_oos"]["ci95_c_wallet_clustered"][1], "pm_compute p07", 0.05),
        ("v2 central fixed cost $/day", (C["feed_licence"]["central"] + C["vps_london"]["central"]) / dpm, fixc, "financials.json v2 cost", 1e-9),
        ("tier-0 fixed cost $/day, low", t0cost("low"), F["strategies"]["tier0"]["cost"]["daily"]["low"], "financials.json tier0 cost", 1e-6),
        ("tier-0 fixed cost $/day, central", t0cost("central"), F["strategies"]["tier0"]["cost"]["daily"]["central"], "financials.json tier0 cost", 1e-6),
        ("tier-0 fixed cost $/day, high", t0cost("high"), F["strategies"]["tier0"]["cost"]["daily"]["high"], "financials.json tier0 cost", 1e-6),
        ("maker IS net P&L $", float(mk[mk.month.astype(str) >= "2026-02"].pnl.sum()), fm["IS"]["capital_returns"]["pnl_usd"], "financials.json maker.IS", 0.01),
        ("maker IS per-fill mean c", float((mk.pnl / mk.shares).mean() * 100), fm["IS"]["per_fill_mean_c"], "financials.json maker.IS", 1e-6),
        ("maker OOS net P&L $", float(mo.pnl.sum()), fm["OOS_blind"]["capital_returns"]["pnl_usd"], "financials.json maker.OOS_blind", 0.01),
        ("maker OOS share-weighted c", float(mo.pnl.sum() / mo.shares.sum() * 100), fm["OOS_blind"]["per_share_c"], "financials.json maker.OOS_blind", 1e-6),
    ]
    rows = []
    for what, ours, quoted, src, tol in checks:
        ok = quoted is not None and abs(float(ours) - float(quoted)) <= tol
        rows.append({"what": what, "ours": float(ours), "quoted": None if quoted is None else float(quoted),
                     "source": src, "tolerance": tol, "match": bool(ok)})
    notes = {
        "capital_tie_rule": ("The engine (research/v2/sizing/engine.py peak_locked) counts a lock and a release at the same "
                             "second as overlapping (locks first). Releases first would give OOS capital "
                             f"${bo['capital_releases_first']:,.0f} instead of ${bo['capital']:,.0f}; IS is unchanged "
                             f"(${bi['capital_releases_first']:,.0f}). src/tier0.py uses releases first. Immaterial, but the two "
                             "conventions differ."),
        "oos_cut_universe": str(u.loc[u.oos, "start"].min()),
    }
    out = {"generated_utc": t0.isoformat(timespec="seconds"), "script": "scripts/financials_audit.py",
           "n_checks": len(rows), "n_match": sum(r["match"] for r in rows), "checks": rows, "notes": notes}
    OUT.write_text(json.dumps(out, indent=1))
    for r in rows:
        print(f"{'ok ' if r['match'] else 'BAD'} {r['what']:62s} ours {r['ours']:>14.4f}  quoted {r['quoted'] if r['quoted'] is None else round(r['quoted'], 4)}")
    print(f"{out['n_match']}/{out['n_checks']} match; {notes['capital_tie_rule']}")


if __name__ == "__main__":
    main()
