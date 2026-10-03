"""Backtest EXAMPLE MATCH for the video: one match of the tier-0 feed-latency backtest, shown trade by trade.

    LABEL: Example match from the backtest (selected for illustration) · simulated 1 s licensed-feed baseline ·
           real Polymarket price path · paper  (+ the share of backtest matches that were profitable)

    python scripts/backtest_example_match.py      # -> results/viz/v60_assets/backtest_match/match.json

The selection rule was committed first (results/viz/v60_assets/backtest_match/SELECTION.md) and is applied here
mechanically. The cell is the latency sweep's ("video", "tournament_lagcal", V = 1.0 s, "own120"): our CV on a
licensed video feed 1 s behind the court, reprice timing drawn once per tournament, stamp lag = the calibrated
3.14 s (an inference, post hoc). scripts/tier0_latency_sweep.py and src/tier0.py are imported and called
unchanged (`SW.cell`, `T.draws`, `T.simulate`, `T.metrics`). The per-call timing decomposition (CV call, order
arrival, reprice) recomputes the same expressions `T.simulate` uses from the same draws and is asserted equal
to the tau that `T.simulate` returns; the sweep's per-seed P&L is asserted reproduced for all 20 seeds.

Real: the Polymarket prints (price path), the historical jump times and directions, match results, fees, venue
delays. Modelled (paper): every call, order, fill price, share count and P&L. No order was ever sent.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from scripts import tier0_latency_sweep as SW  # noqa: E402
from src import tier0 as T  # noqa: E402

warnings.filterwarnings("ignore")

LABEL = ("Example match from the backtest (selected for illustration) · simulated 1 s licensed-feed baseline · "
         "real Polymarket price path · paper")
SOURCE, READING, V, CV = "video", "tournament_lagcal", 1.0, "own120"
OUTDIR = ROOT / "results/viz/v60_assets/backtest_match"
MIN_TRADES = 6
EPS = 1e-9
PRINTS = {"IS": ROOT / "data/is_prints.parquet", "burned_OOS": ROOT / "data/locked/oos_prints.parquet"}


# ------------------------------------------------------------------------------------------ runs
def run(c: dict, period: str, seed: int) -> tuple:
    """The sweep's _job for one (period, seed), keeping the call table. Returns (calls, metrics, sc, cvs, draws)."""
    sc, cvs = SW.cell(SOURCE, READING, V, CV, c)
    P = c["per"][period]
    J = P["J"]
    dr = T.draws(len(J), P["seed"] + seed, max(c["n_tour"], 1))
    calls = T.simulate(J, P["M"], sc, dr, c["pools"], cvs, c["mix"])
    m = T.metrics(calls, T.period_days(J, sc.regime))
    return calls, m, sc, cvs, dr


def match_table(calls: pd.DataFrame) -> pd.DataFrame:
    tr = calls[calls.shares > EPS]
    g = tr.groupby("cond").agg(n_trades=("pnl", "size"), pnl=("pnl", "sum"), start=("start", "first"))
    return g.reset_index()


def share_stats(g: pd.DataFrame) -> dict:
    n = int(len(g))
    k = int((g.pnl > 0).sum())
    return {"traded_matches": n, "profitable_matches": k, "share_profitable": round(k / n, 4) if n else None,
            "median_match_pnl_usd": round(float(g.pnl.median()), 2) if n else None,
            "mean_match_pnl_usd": round(float(g.pnl.mean()), 2) if n else None,
            "total_pnl_usd": round(float(g.pnl.sum()), 2),
            "matches_with_ge6_trades": int((g.n_trades >= MIN_TRADES).sum()),
            "eligible_ge6_trades_and_profitable": int(((g.n_trades >= MIN_TRADES) & (g.pnl > 0)).sum())}


# ------------------------------------------------------------------------ per-call decomposition
def decompose(c: dict, period: str, sc, cvs: dict, dr: dict) -> pd.DataFrame:
    """Per call (index i = position in simulate's filtered X, the 'i' column of its output): the same
    expressions as T.simulate for lead, CV call time, network, order arrival and reprice time (seconds after
    the modelled ball landing), plus the pool point and the correct/wrong draw."""
    P = c["per"][period]
    J, M = P["J"], P["M"]
    cov = T.coverage_set(M, sc.coverage, sc.regime)
    X = J[J.cond.isin(cov)]
    ref = X[sc.stale].to_numpy()
    dirn = X["dir"].to_numpy()
    q_c0 = np.where(dirn > 0, ref, 1 - ref) + sc.stale_adj
    ok = np.isfinite(ref) & (q_c0 >= T.ZONE[0]) & (q_c0 <= T.ZONE[1])
    X = X[ok]
    q_c0 = q_c0[ok]
    r = X.row.to_numpy()
    n = len(X)
    pool = c["pools"][sc.pool]
    pidx = np.minimum((dr["pool"][r] * len(pool)).astype(int), len(pool) - 1)
    men = X.men.to_numpy()
    p_out = np.where(men, c["mix"]["men"]["out"], c["mix"]["women"]["out"])
    is_out = dr["end"][r] < p_out
    cvd = cvs[sc.cv]
    lead, prec_cv, called = T.lead_and_precision(cvd, dr["lead"][r], dr["bin"][r])
    early = is_out & called
    lead = np.where(early, lead, 0.0)
    prec = np.where(early, prec_cv, sc.p_event)
    lat = X.region.map(T.REGION_MS).to_numpy(float) / 1000.0
    t_call = -lead + cvd["t_inf"]                       # CV call on the delayed video (t_inf already holds + V)
    t_gate = t_call + lat + T.GATEWAY                    # order reaches the venue (London gateway)
    arrival = t_gate + X.delay.to_numpy(float)           # order becomes live after the venue's order delay
    R = pool.R.to_numpy()
    assert sc.r_mode == "tournament"
    tu = dr["tour"][X.tour.to_numpy()]
    R_draw = R[np.minimum((tu * len(pool)).astype(int), len(pool) - 1)]
    t_rep = R_draw + sc.stamp_lag + sc.r_shift
    return pd.DataFrame({"i": np.arange(n), "lead_s": lead, "t_cv_call_s": t_call, "network_s": lat,
                         "t_order_at_venue_s": t_gate, "t_order_live_s": arrival, "t_official_stamp_s":
                         np.full(n, sc.stamp_lag), "R_tournament_s": R_draw, "t_book_reprice_s": t_rep,
                         "tau_check": t_rep - arrival, "p_correct": prec, "stale_token_price": q_c0,
                         "ref0": X[sc.stale].to_numpy(), "post30_0": X["post30"].to_numpy(float),
                         "detect_ts": X.detect_ts.to_numpy(float), "jump_dir": dirn[ok], "live_pool_point": pidx})


def miss_reason(row) -> str | None:
    if row.shares > EPS:
        return None
    if row.correct and row.tau < 0:
        return "too late: our limit order would go live after the book repriced (never chases)"
    if row.sh_raw <= EPS:
        return "no stale depth left in the book for our share"
    return "blocked by the 100-share per-match net cap"


# ------------------------------------------------------------------------------------------ main
def main():
    print(LABEL)
    c = SW.ctx()
    sweep = pd.read_csv(ROOT / "results/tier0/latency_sweep_seeds.csv")
    sweep = sweep[(sweep.source == SOURCE) & (sweep.reading == READING) & (sweep.x_s == V) & (sweep.cv == CV)]
    assert len(sweep) == 2 * SW.SEEDS, len(sweep)

    # 1. every seed of the cell (seed choice + supplementary spread); check against the published sweep
    runs, per_seed = {}, []
    for s in range(SW.SEEDS):
        tot = 0.0
        rec = {"seed": s}
        for p in SW.PERIODS:
            calls, m, sc, cvs, dr = run(c, p, s)
            pub = float(sweep[(sweep.period == p) & (sweep.seed == s)].pnl_usd.iloc[0])
            assert abs(m["pnl_usd"] - pub) < 1e-3, (p, s, m["pnl_usd"], pub)
            runs[(p, s)] = (calls, m, sc, cvs, dr)
            tot += m["pnl_usd"]
            st = share_stats(match_table(calls))
            rec[p] = {"pnl_usd": round(m["pnl_usd"], 2), "share_profitable": st["share_profitable"],
                      "median_match_pnl_usd": st["median_match_pnl_usd"], "traded_matches": st["traded_matches"]}
        g = pd.concat([match_table(runs[(p, s)][0]) for p in SW.PERIODS])
        st = share_stats(g)
        rec["pooled"] = {"pnl_usd": round(tot, 2), "share_profitable": st["share_profitable"],
                         "median_match_pnl_usd": st["median_match_pnl_usd"], "traded_matches": st["traded_matches"]}
        rec["total_pnl_usd"] = tot
        per_seed.append(rec)
        print(f"seed {s:2d}  total ${tot:,.2f}  profitable share pooled {st['share_profitable']}", flush=True)

    # 2. median seed by total P&L: rank 10 of 20 ascending (lower median), ties lower index (SELECTION.md)
    order = sorted(per_seed, key=lambda r: (r["total_pnl_usd"], r["seed"]))
    k_med = len(order) // 2 - 1
    seed = order[k_med]["seed"]
    print(f"median seed (rank {k_med + 1} of {len(order)}): {seed}")

    # 3. match table at that seed, both periods pooled; choose
    tabs = []
    for p in SW.PERIODS:
        g = match_table(runs[(p, seed)][0])
        g["period"] = p
        tabs.append(g)
    G = pd.concat(tabs, ignore_index=True)
    elig = G[(G.n_trades >= MIN_TRADES) & (G.pnl > 0)]
    elig = elig.sort_values(["n_trades", "start", "cond"], ascending=[False, True, True], kind="stable")
    pick = elig.iloc[0]
    period, cond = pick.period, pick.cond
    ties = elig[elig.n_trades == pick.n_trades]
    print(f"chosen {cond} ({period}): {int(pick.n_trades)} trades, ${pick.pnl:,.2f}; "
          f"{len(elig)} eligible, {len(ties)} at the max trade count")

    stats = {p: share_stats(G[G.period == p]) for p in SW.PERIODS}
    stats["pooled"] = share_stats(G)

    # 4. the chosen match, call by call
    calls, m, sc, cvs, dr = runs[(period, seed)]
    D = decompose(c, period, sc, cvs, dr)
    mc = calls[calls.cond == cond].merge(D, on="i", how="left", validate="one_to_one")
    assert np.allclose(mc.tau.to_numpy(), mc.tau_check.to_numpy(), atol=1e-9)
    assert (np.where(mc.correct, mc.d0, -mc.d0) == mc.jump_dir).all()   # correct = buy in the jump direction
    mc = mc.sort_values("ts", kind="stable").reset_index(drop=True)
    mc["fill"] = mc.shares > EPS
    mc["cum_pnl"] = np.where(mc.fill, mc.pnl, 0.0).cumsum()
    # edge at the fill vs the post-jump price (the model prices a fill as post-jump price - measured edge, or
    # + measured cost for a wrong call; edge_c is that per-share edge), net of the fee
    mc["edge_usd"] = np.where(mc.fill, mc.shares * (mc.edge_c - mc.fee_ps), 0.0)
    mc["cum_edge"] = mc.edge_usd.cumsum()
    J = c["per"][period]["J"]
    U = c["per"][period]["M"].set_index("cond")
    jm = J[J.cond == cond].iloc[0]
    out0, out1 = (str(U.loc[cond, "out0"]), str(U.loc[cond, "out1"])) if "out0" in U else ("outcome 0", "outcome 1")

    calls_out = []
    for k, r in enumerate(mc.itertuples()):
        tok0 = r.d0 > 0
        # display clock: the modelled reprice is placed at the historical jump onset (ASSUMPTION, display only)
        t0 = float(r.ts) - float(r.t_book_reprice_s)
        rel = {"cv_call": r.t_cv_call_s, "order_at_venue": r.t_order_at_venue_s, "order_live": r.t_order_live_s,
               "official_stamp": r.t_official_stamp_s, "book_reprice": r.t_book_reprice_s}
        calls_out.append({
            "n": k + 1,
            "jump_onset_ts": float(r.ts), "jump_onset_utc": datetime.fromtimestamp(r.ts, timezone.utc).isoformat(),
            "jump_detect_ts": float(r.detect_ts),
            "jump_dir_outcome0": int(r.jump_dir),
            "jump_size": round(float(r.size), 4),
            "stale_price_outcome0_vwap": round(float(r.ref0), 4),
            "post_jump_price_outcome0_vwap30s": None if not np.isfinite(r.post30_0) else round(float(r.post30_0), 4),
            "point_ending": "out ball" if r.is_out else "other ending (winner, net, ...)",
            "cv_called_early": bool(r.early), "cv_lead_s": round(float(r.lead_s), 3),
            "call_correct": bool(r.correct), "p_correct_model": round(float(r.p_correct), 4),
            "times_s_after_ball_landing": {kk: round(float(v), 4) for kk, v in rel.items()},
            "network_to_london_s": round(float(r.network_s), 3), "venue_order_delay_s": int(r.delay),
            "tau_s": round(float(r.tau), 4),
            "display_clock_ts": {kk: round(t0 + float(v), 3) for kk, v in
                                 {"ball_landing": 0.0, **rel}.items()},
            "order": {"side": "BUY", "token": out0 if tok0 else out1, "token_index": 0 if tok0 else 1,
                      "max_usd": sc.trade_cap},
            "result": "fill" if r.fill else "miss",
            "miss_reason": miss_reason(r),
            "fill_price_token": round(float(r.q), 4) if r.fill else None,
            "fill_price_outcome0_equiv": (round(float(r.q if tok0 else 1 - r.q), 4) if r.fill else None),
            "shares": round(float(r.shares), 3), "usd_in": round(float(r.usd_in), 2),
            "shares_before_net_cap": round(float(r.sh_raw), 3),
            "fee_per_share": round(float(r.fee_ps), 5), "payout_per_share": float(r.payout),
            "pnl_per_share": round(float(r.pnl_ps), 5) if r.fill else None,
            "pnl_usd": round(float(r.pnl), 4) if r.fill else 0.0,
            "cum_pnl_usd": round(float(r.cum_pnl), 4),
            "edge_per_share_vs_post_jump": round(float(r.edge_c), 5) if r.fill else None,
            "edge_usd_net_fee": round(float(r.edge_usd), 4),
            "cum_edge_usd_net_fee": round(float(r.cum_edge), 4),
        })

    pr = pd.read_parquet(PRINTS[period], columns=["cond", "ts", "p", "usd"], filters=[("cond", "==", cond)])
    pr = pr.sort_values("ts", kind="stable")
    fills = mc[mc.fill]
    full = {**stats, "chosen_seed_index": seed}
    pct = lambda x: f"{100 * x:.1f}%"  # noqa: E731
    share_line = (f"{stats['pooled']['profitable_matches']} of {stats['pooled']['traded_matches']} traded backtest "
                  f"matches ({pct(stats['pooled']['share_profitable'])}) were profitable at this setting "
                  f"(IS {pct(stats['IS']['share_profitable'])}, burned OOS "
                  f"{pct(stats['burned_OOS']['share_profitable'])}; seed {seed})")
    res = {
        "label": LABEL,
        "label_share": share_line,
        "label_full": f"{LABEL} · {share_line}",
        "what": "One match of the tier-0 backtest at the simulated 1 s licensed-feed baseline (video + our CV, "
                "V = 1.0 s), shown call by call. Real: the Polymarket price path, jump times and directions, "
                "match result, fee, venue delay. Modelled (paper, no order was sent): calls, orders, fills, P&L.",
        "selection": {"rule_file": "results/viz/v60_assets/backtest_match/SELECTION.md",
                      "rule": "reading = calibrated (tournament_lagcal), V = 1.0 s, seed = the median seed by total "
                              "P&L (rank 10 of 20, lower median); among matches with >= 6 trades and positive P&L, "
                              "the one with the most trades; ties by earliest start",
                      "seed_index": seed, "seed_rank": f"{k_med + 1} of {len(order)} by total P&L (IS + burned OOS)",
                      "seed_total_pnl_usd": round(order[k_med]["total_pnl_usd"], 2),
                      "eligible_matches": int(len(elig)),
                      "eligible_at_max_trades": int(len(ties)),
                      "runner_up": None if len(elig) < 2 else {
                          "cond": elig.iloc[1].cond, "period": elig.iloc[1].period,
                          "n_trades": int(elig.iloc[1].n_trades), "pnl_usd": round(float(elig.iloc[1].pnl), 2)},
                      "illustrative_not_typical": "This match was chosen for the most trades among profitable "
                                                  "ones; it is not a typical match. See profitable_share."},
        "setting": {"source": SOURCE, "reading": READING, "reading_label": SW.READ_LABEL[READING],
                    "video_delay_V_s": V, "cv": CV, "stamp_lag_s": sc.stamp_lag,
                    "stamp_lag_note": "calibrated 3.14 s is an inference (fast-tier prints), chosen post hoc; the "
                                      "pre-registered stamp lag is 2.0 s",
                    "period": period, "period_note": None if period == "IS" else
                    "burned OOS: not blind (the OOS set was used in earlier runs)",
                    "seed_draws": int(c["per"][period]["seed"] + seed),
                    "scenario": {k: v for k, v in T.as_dict(sc).items()},
                    "model": "src/tier0.py CORRECTED via scripts/tier0_latency_sweep.py cell(); imported unchanged"},
        "match": {"cond": cond, "slug": jm.slug, "title": jm.title, "series": jm.series, "league": jm.league,
                  "start_utc": pd.Timestamp(jm.start).isoformat(), "end_utc": pd.Timestamp(jm.end).isoformat(),
                  "outcome0": out0, "outcome1": out1, "winner": out0 if jm.res0 == 1 else out1,
                  "res0": float(jm.res0), "volume_usd": round(float(jm.volume), 2), "fee_rate": float(jm.fee_rate),
                  "venue_order_delay_s": int(jm.delay), "region": jm.region,
                  "network_assumption_ms": T.REGION_MS[jm.region]},
        "summary": {"calls": int(len(mc)), "fills": int(mc.fill.sum()), "misses": int((~mc.fill).sum()),
                    "fills_correct": int((mc.fill & mc.correct).sum()), "fills_wrong": int((mc.fill & ~mc.correct).sum()),
                    "misses_by_reason": {k: int(v) for k, v in mc[~mc.fill].apply(miss_reason, axis=1).value_counts().items()},
                    "shares": round(float(fills.shares.sum()), 2), "usd_in": round(float(fills.usd_in.sum()), 2),
                    "pnl_usd": round(float(fills.pnl.sum()), 2),
                    "pnl_c_per_share": round(float(fills.pnl.sum() / fills.shares.sum() * 100), 3),
                    "best_trade_usd": round(float(fills.pnl.max()), 2), "worst_trade_usd": round(float(fills.pnl.min()), 2),
                    "trades_positive": int((fills.pnl > 0).sum()),
                    "edge_usd_net_fee_at_fill": round(float(fills.edge_usd.sum()), 2),
                    "pnl_note": "pnl_usd is settlement P&L (each position held to the match result, as in the backtest), so a correct call on the eventual loser's point still loses at settlement; edge_usd_net_fee is the modelled edge at the fill against the post-jump price, before settlement variance"},
        "profitable_share": full,
        "profitable_share_note": "Traded matches = matches with >= 1 fill at the chosen seed; profitable = match P&L "
                                 "> 0 (fees included). Pooled = IS + burned OOS.",
        "profitable_share_all_seeds": {
            "note": "supplementary, not used for the choice: the same statistics for each of the sweep's 20 seeds",
            "pooled_share_profitable": {"mean": round(float(np.mean([r["pooled"]["share_profitable"] for r in per_seed])), 4),
                                        "min": min(r["pooled"]["share_profitable"] for r in per_seed),
                                        "max": max(r["pooled"]["share_profitable"] for r in per_seed)},
            "IS_share_profitable_mean": round(float(np.mean([r["IS"]["share_profitable"] for r in per_seed])), 4),
            "burned_OOS_share_profitable_mean": round(float(np.mean([r["burned_OOS"]["share_profitable"] for r in per_seed])), 4),
            "pooled_median_match_pnl_usd_mean": round(float(np.mean([r["pooled"]["median_match_pnl_usd"] for r in per_seed])), 2),
            "per_seed": [{k: v for k, v in r.items() if k != "total_pnl_usd"} | {"total_pnl_usd": round(r["total_pnl_usd"], 2)}
                         for r in per_seed]},
        "calls": calls_out,
        "price_path": {"source": str(PRINTS[period].relative_to(ROOT)),
                       "note": "every Polymarket print of this match's in-play tape used by the backtest (real); "
                               "p = outcome-0 price, usd = print size",
                       "outcome": out0, "n": int(len(pr)),
                       "ts": [float(x) for x in pr.ts], "p": [round(float(x), 4) for x in pr.p],
                       "usd": [round(float(x), 2) for x in pr.usd]},
        "fields": {
            "times_s_after_ball_landing": "model clock, origin = the modelled ball landing (point end). cv_call = "
                                          "-CV lead + 20 ms inference + V; order_at_venue = + network to London + 2 ms "
                                          "gateway; order_live = + the venue's order delay; official_stamp = stamp lag; "
                                          "book_reprice = R (drawn per tournament from the live day) + stamp lag",
            "tau_s": "book_reprice - order_live; a correct call fills only if tau >= 0 (limit order)",
            "display_clock_ts": "ASSUMPTION, display only: the model does not place the ball landing on the "
                                "historical clock; here the modelled book reprice is put at the historical jump "
                                "onset (first print of the detector's 10 s window), and the other events keep "
                                "their modelled offsets",
            "jump_dir_outcome0": "+1 = the historical move was up in outcome 0",
            "fill_price_token": "price paid for the bought token (live-book model); fill_price_outcome0_equiv "
                                "puts it on the outcome-0 price axis (1 - price for an outcome-1 buy)",
            "pnl_usd": "settlement P&L: shares x (payout - fill price - fee per share); 0 for a miss",
            "edge_usd_net_fee": "modelled edge at the fill: shares x (edge per share vs the post-jump price - fee per share); negative for a wrong call",
        },
        "checks": {"sweep_pnl_reproduced_all_20_seeds_both_periods": True,
                   "tau_decomposition_equals_simulate": True},
        "oos_peek": "this run reads burned OOS (non-blind) through the sweep's code; results/oos_peeks.log is not "
                    "written by this script",
        "run": {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "script": "scripts/backtest_example_match.py", "python": sys.version.split()[0]},
    }
    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "match.json").write_text(json.dumps(res, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    print(json.dumps({k: res[k] for k in ("label_full", "match", "summary", "profitable_share")}, indent=1, default=str))


if __name__ == "__main__":
    main()
