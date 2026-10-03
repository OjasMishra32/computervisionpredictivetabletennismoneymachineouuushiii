"""Post-OOS diagnostics (decompositions only; no rule is changed or re-fit)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import run_all
from src import backtest as bt, fasttier, prints, strategies as st
from src.tape import universe

if __name__ == "__main__":
    u = universe()
    p = pd.concat([prints.build("is"), prints.build("oos")], ignore_index=True)
    wf, sh, _ = fasttier.walk_forward(p)
    sh, _ = run_all.shadow_book(sh, u)
    oos0 = int(u.loc[u.oos, "start"].min().timestamp())
    sh["split"] = np.where(sh.ts >= oos0, "oos", "is")
    sh["tok_px"] = np.where(sh.dir > 0, sh.p, 1 - sh.p)
    sh["px_bin"] = pd.cut(sh.tok_px, [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
    sh["pnl"] = sh.shares * sh.net_res
    dec = sh.groupby(["split", "px_bin"], observed=True).agg(
        n=("pnl", "size"), shares_k=("shares", lambda x: x.sum() / 1e3), pnl_usd=("pnl", "sum"),
        net_res_c=("net_res", lambda x: x.mean() * 100)).round(2)
    print(dec.to_string())
    # always-on maker by venue regime (IS + OOS)
    rows = []
    for split, uu in (("is", u[~u.oos]), ("oos", u[u.oos])):
        tr = bt.run(st.h5_fills, uu, always_on=True)
        tr = tr.merge(uu[["cond", "delay", "fee_rate"]], on="cond")
        for (d, f), g in tr.groupby(["delay", "fee_rate"]):
            rows.append({"split": split, "delay": d, "fee": f, "n": len(g), "maker_c": g.pnl_ps.mean() * 100})
    reg = pd.DataFrame(rows).round(3)
    print(reg.to_string())
    Path("results/diagnostics.json").write_text(json.dumps(
        {"shadow_by_price": dec.reset_index().astype(str).to_dict("records"),
         "maker_by_regime": reg.to_dict("records")}, indent=2))
