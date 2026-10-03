"""How much fair value moves per match, and how concentrated it is (Markov model, simulated)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from src.markov import Format, TennisModel, implied_serve_probs, simulate_match

rng = np.random.default_rng(1)
out = {}
for tour, fmt in (("atp", Format(3)), ("wta", Format(3))):
    levs, totals, top10 = [], [], []
    for price in rng.uniform(0.25, 0.75, 40):
        pa, pb = implied_serve_probs(price, tour, fmt)
        m = TennisModel(pa, pb, fmt)
        for _ in range(25):
            pts = simulate_match(m, rng)
            lv = np.array([abs(x[2]) for x in pts])
            # realised move on each point = leverage * (1 - P(that outcome)) ... use |dV| directly
            dv = []
            for (s, v, L, a) in pts:
                nxt = m.step(s, a)
                v2 = (1.0 if a else 0.0) if nxt is None else m.win_prob(nxt)
                dv.append(abs(v2 - v))
            dv = np.sort(np.array(dv))[::-1]
            levs += list(lv); totals.append(dv.sum()); top10.append(dv[:10].sum() / dv.sum())
    out[tour] = {"points_per_match": float(len(levs) / 1000), "mean_abs_leverage": float(np.mean(levs)),
                 "p90_leverage": float(np.percentile(levs, 90)), "max_leverage": float(np.max(levs)),
                 "total_abs_move_per_match": float(np.mean(totals)),
                 "share_of_move_in_top10_points": float(np.mean(top10))}
print(json.dumps(out, indent=2))
Path("results").mkdir(exist_ok=True)
Path("results/leverage_stats.json").write_text(json.dumps(out, indent=2))
