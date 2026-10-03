"""Placebo: the identical maker-out exit applied to NON-fast-tier 0-3 s prints.

If the exit model handed out the spread for free, slow takers would look profitable too. Entries:
0-3 s post-jump prints in the shadow months (2025-12..2026-08, IS only) whose wallet was NOT in the
walk-forward fast tier (i.e. not in shadow_is_uncapped), in a seeded random sample of 1,500 shadow
matches, at most 16 random prints per match (about the shadow book's density). Same simulator, same
sizing (sh500), same cap, same cells.

    .venv/bin/python research/v2/exit/placebo_exit.py
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from research.v2.exit import analyze_exit as ax  # noqa: E402
from research.v2.exit.sim_exit import sim_match  # noqa: E402

CACHE = ROOT / "data" / "v2_exit"
HERE = Path(__file__).resolve().parent
N_MATCH, PER_MATCH, SEED = 1500, 16, 0
CELLS = [(5, 60), (30, 300)]


def build():
    cols = ["cond", "ts", "p", "dir", "usd", "wallet", "fee_rate", "delay", "res", "mo30", "mo_res", "spread", "with_jump"]
    sh = pd.read_parquet(ROOT / "data/derived/shadow_is_uncapped.parquet", columns=["cond", "ts", "wallet", "p", "dir", "usd"])
    pr = pd.read_parquet(ROOT / "data/derived/prints_0_3s_is.parquet", columns=cols)
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["cond", "start", "end"])
    pr = pr[pr.cond.isin(u.cond)]
    pr["month"] = pd.to_datetime(pr.ts, unit="s").dt.to_period("M").astype(str)
    pr = pr[pr.month >= "2025-12"]
    pr = pr.merge(sh.assign(fast=True), on=["cond", "ts", "wallet", "p", "dir", "usd"], how="left")
    pr = pr[pr.fast.isna()].drop(columns="fast")
    rng = np.random.default_rng(SEED)
    conds = rng.choice(np.sort(sh.cond.unique()), N_MATCH, replace=False)
    pr = pr[pr.cond.isin(conds)]
    pr = pr.assign(_r=rng.random(len(pr)))
    pr = pr[pr.groupby("cond")._r.rank(method="first") <= PER_MATCH].drop(columns="_r")
    pr = pr.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    pr["eid"] = np.arange(len(pr), dtype=np.int64)
    return pr, u.set_index("cond")


def main():
    pr, u = build()
    jobs = [(c, g, u.at[c, "start"], u.at[c, "end"]) for c, g in pr.groupby("cond", sort=False)]
    ents, mks, fbs = [], [], []
    with ProcessPoolExecutor(2) as ex:
        for res in ex.map(sim_match, jobs, chunksize=8):
            if res is not None:
                ents.append(res[0]); fbs.append(res[2])
                if res[1] is not None:
                    mks.append(res[1])
    pd.concat(ents, ignore_index=True).to_parquet(CACHE / "entries_placebo.parquet")
    pd.concat(mks, ignore_index=True).to_parquet(CACHE / "maker_placebo.parquet")
    pd.concat(fbs, ignore_index=True).to_parquet(CACHE / "fallback_placebo.parquet")
    ent, mk, fb = ax.load("_placebo")
    E = ent[ent.acc_sh500].reset_index(drop=True)
    rows = []
    hold = ax.book(E, "sh500", pd.DataFrame({"eid": E.eid, "pnl_ps": E.dir * (E.res - E.p) - E.fee,
                                             "hold_s": (E.end_ts - E.ts).astype(float), "how": "res"}))
    mid = ax.book(E, "sh500", pd.DataFrame({"eid": E.eid, "pnl_ps": E.mo30 - E.fee, "hold_s": 30.0, "how": "mid"}))
    for name, t in (("hold_to_resolution", hold), ("mid30_benchmark", mid)):
        for reg, g in (("all", t), ("1s/5%", t[t.regime == "1s/5%"])):
            ci, _ = ax.cluster_ci(g[np.isfinite(g.pnl_ps)], 500)
            rows.append({"exit": name, "H": None, "T": None, "regime": reg, "n": len(g), "ps_c": g.pnl_ps.mean() * 100,
                         "ci_lo": ci[0], "ci_hi": ci[1], "maker_fill": np.nan})
    for model in ("touch", "improve1", "pegthrough"):
        mi = ax.MODELS.index("touch" if model == "improve1" else model)
        for H, T in CELLS:
            cm = mk[(mk.sizing == 0) & (mk.model == mi) & (mk.H == H) & (mk["T"] == T)]
            t = ax.book(E, "sh500", ax.cell_pnl(E, cm, fb, H, T, model, "B", False))
            for reg, g in (("all", t), ("1s/5%", t[t.regime == "1s/5%"])):
                ci, _ = ax.cluster_ci(g, 500)
                rows.append({"exit": f"maker_{model}_fbB", "H": H, "T": T, "regime": reg, "n": len(g),
                             "ps_c": g.pnl_ps.mean() * 100, "ci_lo": ci[0], "ci_hi": ci[1],
                             "maker_fill": (g.how == "maker").mean()})
    out = pd.DataFrame(rows)
    (HERE / "tables").mkdir(exist_ok=True)
    out.to_csv(HERE / "tables" / "placebo_nonfast_0_3s.csv", index=False)
    (HERE / "placebo.json").write_text(json.dumps({"n_entries": int(len(E)), "n_matches": int(E.cond.nunique()),
                                                    "n_variants": 2 + 3 * len(CELLS), "rows": out.to_dict("records")},
                                                   indent=1, default=float))
    print(out.round(3).to_string())


if __name__ == "__main__":
    main()
