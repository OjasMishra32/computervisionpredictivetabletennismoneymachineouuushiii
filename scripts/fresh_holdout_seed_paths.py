"""Per-seed daily P&L paths for the fresh-holdout figure (descriptive re-run; no number changes).

    COUNTERFACTUAL WITH ASSUMED DATA. Real: Polymarket prices, fills (public trade tapes), match results, taker fees
    and the venue's 1 s order delay. Simulated: the camera/CV calls, made at an ASSUMED licensed-feed delay V
    (0.5 / 1 / 3 s). No feed or video was bought, received or watched; no order is placed anywhere.

results/fresh_holdout/daily.csv stores, per day, the 20-seed mean and the 10th / 90th percentile of that day's P&L.
A band on CUMULATIVE P&L needs each seed's whole path (the sum of daily percentiles is not a percentile of the sum),
so this script re-runs the frozen cells of scripts/fresh_holdout.py with the same code, cached data and seeds
(IS 0-19, burned OOS 1000-1019, fresh 4000-4019; primary coverage, every V and reading, S1 and S2) and writes every
seed's daily P&L. It checks that the seed mean reproduces daily.csv to 1e-6 on every row and refuses to write
otherwise. Nothing is chosen here: it is the same simulation, kept per seed.

    python scripts/fresh_holdout_seed_paths.py      -> results/fresh_holdout/seed_daily_paths.csv

The fresh window and burned OOS are re-read (deterministic re-run); a line goes to results/oos_peeks.log first.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fresh_holdout as FH  # noqa: E402  (chdir to ROOT, the frozen cells, seeds and label)

T = FH.T
OUT = FH.OUT / "seed_daily_paths.csv"


def seed_paths(ctx: dict, seeds: list[int], strats, period: str) -> list[dict]:
    """Each (strategy, reading, V) cell at primary coverage, every seed's zero-filled daily P&L (FH.metr's vector)."""
    lsc = {"cvs": ctx["cvs"], "pools": ctx["pools"], "calib": ctx["calib"]}
    rows = []
    for s in strats:
        for rd in FH.READINGS:
            for V in FH.VS:
                sc, cvs = FH.vd(s, lsc, rd, V, FH.COVERAGES["cov10"])
                if s == "S1":
                    FH.install_v3(ctx, FH.COVERAGES["cov10"], cvs)
                D = []
                for seed in seeds:
                    calls = FH.sim_S1(ctx, sc, seed) if s == "S1" else FH.sim_S2(ctx, sc, cvs, seed)
                    _, dv = FH.metr(calls, ctx["days"])
                    D.append(np.asarray(dv, float))
                D = np.vstack(D)
                for i, d in enumerate(ctx["days"]):
                    r = {"label": FH.LABEL, "period": period, "strategy": s, "reading": rd, "V_s": V,
                         "coverage": "cov10", "date": str(d.date()), "seed_first": seeds[0]}
                    r.update({f"pnl_usd_seed_k{k:02d}": float(D[k, i]) for k in range(len(seeds))})
                    rows.append(r)
    return rows


def fresh_ctx() -> dict:
    """The fresh-window context exactly as FH.run() builds it (cached data/fresh tapes, same window universe)."""
    w = pd.read_parquet(FH.DATA / "window_universe.parquet")
    with FH.fresh_raw():
        tb = FH.build_tables(w)
    w, J = tb["w"], tb["J"]
    J = J.reset_index(drop=True)
    J["row"] = np.arange(len(J))
    tour = T.tournament_codes(w)
    J["tour"] = J.cond.map(tour).astype(int)
    M = w[["cond", "start", "delay", "prestart_usd"]].reset_index(drop=True)
    days = T.period_days(J, FH.BASE.regime)
    return {"J": J, "M": M, "days": days, "n_rows": len(J), "n_tour": int(tour.max()) + 1,
            "pools": {p: T.live_points(p) for p in ("D>=3c", "all")}, "cvs": T.cv_systems(), "mix": T.point_mix(),
            "calib": T.calibrate_stamp_lag(), "v3_shared": FH.v3_shared()}


def main() -> None:
    t0 = time.time()
    FH.peek("fresh holdout per-seed daily paths (scripts/fresh_holdout_seed_paths.py): RE-RUN of the frozen cells "
            "(same code, cached data, seeds IS 0-19 / burned OOS 1000-1019 / fresh 4000-4019; primary coverage) to "
            "keep each seed's daily P&L for the cumulative band of the firm-scenario figure; descriptive, no number "
            "changes, nothing chosen; COUNTERFACTUAL")
    rows = []
    C = FH.ctx_is_oos()
    for p in ("IS", "burned_OOS"):
        seeds = [FH.SEED_HIST[p] + k for k in range(FH.N_SEEDS)]
        rows += seed_paths(C[p], seeds, ("S2",), p)
        rows += seed_paths(C["IS_v3"] if p == "IS" else C[p], seeds, ("S1",), p)
        FH.say(f"{p} done ({time.time() - t0:.0f}s)")
    rows += seed_paths(fresh_ctx(), [FH.SEED_FRESH + k for k in range(FH.N_SEEDS)], ("S1", "S2"), "fresh")
    FH.say(f"fresh done ({time.time() - t0:.0f}s)")
    P = pd.DataFrame(rows)
    # ---- check against the stored 20-seed means (results/fresh_holdout/daily.csv) before writing anything
    D = pd.read_csv(FH.OUT / "daily.csv")
    D = D[(D.coverage == "cov10") & (D.subset == "all_days")]
    key = ["period", "strategy", "reading", "V_s", "date"]
    scols = [c for c in P.columns if c.startswith("pnl_usd_seed_k")]
    P["mean"] = P[scols].mean(1)
    P["p10"] = np.percentile(P[scols].to_numpy(), 10, axis=1)
    P["p90"] = np.percentile(P[scols].to_numpy(), 90, axis=1)
    m = P.merge(D[key + ["pnl_mean_usd", "pnl_p10_usd", "pnl_p90_usd"]], on=key, how="outer", indicator=True)
    if (m._merge != "both").any():
        raise SystemExit(f"row sets differ from daily.csv:\n{m[m._merge != 'both'][key + ['_merge']]}")
    err = max(float((m["mean"] - m.pnl_mean_usd).abs().max()), float((m.p10 - m.pnl_p10_usd).abs().max()),
              float((m.p90 - m.pnl_p90_usd).abs().max()))
    FH.say(f"max |diff| vs daily.csv (mean, p10, p90): {err:.2e} over {len(m)} rows")
    if err > 1e-6:
        raise SystemExit("REFUSED: the re-run does not reproduce daily.csv; not writing")
    P.drop(columns=["mean", "p10", "p90"]).to_csv(OUT, index=False, float_format="%.6f")
    FH.peek(f"fresh holdout per-seed daily paths DONE -> {OUT.relative_to(ROOT)} (reproduces daily.csv, max |diff| "
            f"{err:.1e}; COUNTERFACTUAL)")
    FH.say(f"-> {OUT} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
