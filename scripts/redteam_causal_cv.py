"""Red-team C5: the tier-0 1 s-feed simulation with the LIVE CAUSAL engine's call accuracy (not the offline
evaluation that used a look-ahead feature). SIMULATED; assumed data: licensed feed/video not purchased;
parameters measured. Paper only.

    python scripts/redteam_causal_cv.py            # IS, then (one logged non-blind read) burned OOS
    python scripts/redteam_causal_cv.py --is-only  # IS only, no peek-log line

Why. Table 2 of the paper uses `own120`: recall by lead from the OFFLINE snapshot rule
(results/tracking/summary.json), which used a whole-flight `hb` feature (look-ahead). The engine that runs live
is causal and called 4 of 41 held-out misses early (precision 1.0; results/engine/online_vs_offline.json
`runs.fp16_cl_fuse_compile_b1_realtime.A_engine_calls.online`). This script reruns the unchanged sweep model with
that table. Nothing is fitted or chosen; every other parameter is the sweep's (scripts/tier0_latency_sweep.py,
imported unchanged; src/tier0.py unchanged).

Pre-specified cells (written before any run):
  own120_engine  leads 0/25/50/100/150/200 ms; recall and precision = A_engine_calls.online[lead] (point
                 estimates, as `own120` uses point estimates); inference 20 ms (= own120's T_INF, so only the
                 call table differs). Usable leads: precision >= 0.95 (the sweep's rule).
  readings       tournament (pre-registered stamp lag 2.0 s) and tournament_lagcal (post hoc 3.14 s inference)
  V grid         0 to 3 s in 0.05 s steps (break-even search), 20 seeds, both periods
  plus           own120_pess (no early calls) under tournament_lagcal at V in {0, 0.5, 1} (Table 2 row 9, post hoc)
  plumbing check own120 / tournament / V = 0 / IS reproduces results/tier0/latency_sweep.json to the cent.
As in the sweep, out balls not called early and every other point ending are still called at the bounce with
precision p_event = 0.95 (the model's CV event detection), so this changes how EARLY calls are, not whether.

Outputs: results/redteam/causal_cv.json, results/redteam/causal_cv_cells.csv (seed means).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import tier0_latency_sweep as LS  # noqa: E402  (chdirs to ROOT)
from src import tier0 as T  # noqa: E402

OUT = ROOT / "results/redteam"
ENGINE = ROOT / "results/engine/online_vs_offline.json"
RUN = "fp16_cl_fuse_compile_b1_realtime"
LABEL = ("SIMULATED: assumed 1 s-class licensed feed (not purchased); parameters measured; CV accuracy = live "
         "causal engine (4 of 41 held-out misses called early); trade set = historical points that later moved "
         ">= 4c (selected on outcomes, not ex ante)")
V_GRID = [round(0.05 * i, 2) for i in range(61)]
PESS_V = [0.0, 0.5, 1.0]
READ = ["tournament", "tournament_lagcal"]
PEEK = ("redteam causal-CV cell (INTEGRATION_TODO C5; scripts/redteam_causal_cv.py): own120_engine = live causal "
        "engine recall/precision at V 0-3 s under tournament (lag 2.0) and tournament_lagcal (3.14), own120_pess "
        "under tournament_lagcal; burned OOS, non-blind, sensitivity; no parameter chosen [logged before the OOS run]")


def engine_system() -> dict:
    A = json.loads(ENGINE.read_text())["runs"][RUN]["A_engine_calls"]["online"]
    leads = [0, 25, 50, 100, 150, 200]
    rec = [A[f"{L}ms"]["recall"] for L in leads]
    prec = [A[f"{L}ms"]["precision"] for L in leads]
    n = [A[f"{L}ms"]["tp"] + A[f"{L}ms"]["fp"] for L in leads]
    usable = [L for L, p in zip(leads, prec) if p >= 0.95]
    return {"leads_ms": leads, "recall": [[r] for r in rec], "precision": prec, "bins_w": [1.0],
            "max_lead_ms": max(usable) if usable else 0, "t_inf": T.T_INF, "precision_n": n,
            "source": f"{ENGINE.relative_to(ROOT)}::runs.{RUN}.A_engine_calls.online"}


def run_jobs(jobs: list[tuple]) -> pd.DataFrame:
    t0 = time.time()
    rows = []
    for i, j in enumerate(jobs):
        rows.append(LS._job(j))
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    return pd.DataFrame(rows)


def jobs_for(period: str) -> list[tuple]:
    out = []
    for s in range(LS.SEEDS):
        for rd in READ:
            for v in V_GRID:
                out.append(("video", rd, v, "own120_engine", period, s))
        for v in PESS_V:
            out.append(("video", "tournament_lagcal", v, "own120_pess", period, s))
    return out


def cell_summary(Sm: pd.DataFrame, rd: str, cv: str, v: float, p: str) -> dict:
    r = Sm[(Sm.reading == rd) & (Sm.cv == cv) & (np.isclose(Sm.x_s, v)) & (Sm.period == p)]
    if r.empty:
        return {}
    r = r.iloc[0]
    f = lambda x, nd=2: None if not np.isfinite(x) else round(float(x), nd)  # noqa: E731
    return {"usd_per_day": f(r.pnl_per_day_usd), "usd_per_day_seed_ci95": [f(r.pnl_per_day_usd_seed_p2_5),
                                                                           f(r.pnl_per_day_usd_seed_p97_5)],
            "net_c_per_share": f(r.per_share_c, 3), "net_c_per_share_ci95": [f(r.per_share_ci95_lo_c, 3),
                                                                              f(r.per_share_ci95_hi_c, 3)],
            "sharpe_ann": f(r.sharpe_ann), "fill_rate": f(r.fill_rate, 4), "n_trades": f(r.n_trades, 1),
            "wrong_call_share_of_trades": f(r.wrong_call_share_of_trades, 4), "capital_usd": f(r.capital_usd, 0),
            "n_seeds_with_trades": int(r.n_seeds_with_trades)}


def breakeven(Sm: pd.DataFrame, rd: str, p: str) -> float | str:
    m = Sm[(Sm.reading == rd) & (Sm.cv == "own120_engine") & (Sm.period == p)].sort_values("x_s")
    be = LS.first_crossing(m.x_s.to_numpy(float), m.pnl_per_day_usd.to_numpy(float))
    return LS._fmt_be(be, 3.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--is-only", action="store_true")
    a = ap.parse_args()
    c = LS.ctx()
    c["cvs"]["own120_engine"] = engine_system()
    # plumbing: V = 0, own120, tournament, IS must equal the published sweep cell
    chk = pd.DataFrame([LS._job(("video", "tournament", 0.0, "own120", "IS", s)) for s in range(LS.SEEDS)])
    pub = json.loads((ROOT / "results/tier0/latency_sweep.json").read_text())["video_own120"]["tournament"]["0"]["IS"]
    got = round(float(chk.pnl_per_day_usd.mean()), 2)
    plumbing = {"own120_tournament_V0_IS_usd_per_day": got, "published": pub["usd_per_day"],
                "match": abs(got - pub["usd_per_day"]) < 0.01}
    print("plumbing", plumbing, flush=True)
    assert plumbing["match"], plumbing
    periods = ["IS"] if a.is_only else ["IS", "burned_OOS"]
    frames = []
    for p in periods:
        if p == "burned_OOS":
            with open(ROOT / "results/oos_peeks.log", "a") as fh:
                fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} {PEEK}\n")
        J = jobs_for(p)
        print(f"{p}: {len(J)} runs", flush=True)
        frames.append(run_jobs(J))
    S = pd.concat(frames, ignore_index=True)
    Sm = LS.summarise(S)
    OUT.mkdir(parents=True, exist_ok=True)
    Sm.round(6).to_csv(OUT / "causal_cv_cells.csv", index=False)
    res = {"label": LABEL, "never_claim": LS.NEVER, "script": "scripts/redteam_causal_cv.py",
           "cv_system_own120_engine": c["cvs"]["own120_engine"], "plumbing_check": plumbing,
           "cells_V1": {}, "cells_V0": {}, "breakeven_V_s": {}, "pessimistic_lagcal": {},
           "compare_offline_own120_V1": {}, "utc": pd.Timestamp.now(tz="UTC").isoformat(),
           "periods_run": periods}
    sweep = json.loads((ROOT / "results/tier0/latency_sweep.json").read_text())["video_own120"]
    for rd in READ:
        res["cells_V1"][rd] = {p: cell_summary(Sm, rd, "own120_engine", 1.0, p) for p in periods}
        res["cells_V0"][rd] = {p: cell_summary(Sm, rd, "own120_engine", 0.0, p) for p in periods}
        res["breakeven_V_s"][rd] = {p: breakeven(Sm, rd, p) for p in periods}
        res["compare_offline_own120_V1"][rd] = {p: sweep[rd]["1"][p]["usd_per_day"] for p in periods}
    res["pessimistic_lagcal"] = {f"V{v:g}": {p: cell_summary(Sm, "tournament_lagcal", "own120_pess", v, p)
                                            for p in periods} for v in PESS_V}
    res["reading_labels"] = {"tournament": "pre-registered: stamp lag 2.0 s, R drawn per tournament (DEVIATIONS V3)",
                             "tournament_lagcal": "post hoc: stamp lag 3.14 s inferred from fast-tier prints "
                                                  "(assumes courtside humans)"}
    (OUT / "causal_cv.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("cells_V1", "breakeven_V_s", "compare_offline_own120_V1")}, indent=1))


if __name__ == "__main__":
    main()
