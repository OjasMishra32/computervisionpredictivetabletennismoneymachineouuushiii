"""Export compact JSON for the interactive visual (results/viz/viz_data.json)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from src import hawkeye as hk
from src.tape import in_play, load_tape

OUT = Path("results/viz"); OUT.mkdir(parents=True, exist_ok=True)
S = json.loads(Path("results/summary.json").read_text())
viz = {}

# 1. one groundstroke landing ~14 cm long, plus the tracker's estimate at each lead (200 noise draws)
rng = np.random.default_rng(11)
best = None
for _ in range(40):
    s = hk.sample_shots(4000, rng)
    acc = lambda v, a: hk._accel_truth(v, s["w_hat"][a], s["omega"][a])
    land, tl, traj = hk._integrate(s["p0"], s["v0"], acc, record_every=1 / hk.FPS)
    d = hk.signed_out_distance(land, s["serve"])
    y = traj[..., 1]
    cross = np.argmax(np.nan_to_num(y, nan=-1) >= hk.NET_Y, axis=1)
    zc = traj[np.arange(len(d)), cross, 2]
    ok = np.flatnonzero((d > 0.12) & (d < 0.16) & (land[:, 1] > hk.BASELINE) & (np.abs(land[:, 0]) < 3.0)
                        & (zc > hk.NET_H + 0.3) & (tl > 0.8) & (tl < 1.1))
    if len(ok):
        i = ok[0]; best = (traj[i], land[i], tl[i], d[i]); break
traj, land, tl, d = best
n = int(np.floor(tl * hk.FPS)) + 1
traj = traj[:n]
W = int(0.15 * hk.FPS)
preds = []
for L in range(400, -1, -10):
    k = int(np.floor((tl - L / 1000) * hk.FPS))
    if k < W:
        continue
    noisy = traj[None, k - W + 1:k + 1] + rng.normal(0, hk.NOISE, (200, W, 3))
    lh = hk.predict_landing(noisy)
    dh = hk.signed_out_distance(lh, np.zeros(len(lh), bool))
    preds.append({"lead_ms": L, "x": float(np.mean(lh[:, 0])), "y": float(np.mean(lh[:, 1])),
                  "sx": float(np.std(lh[:, 0])), "sy": float(np.std(lh[:, 1])), "p_out": float(np.mean(dh > 0))})
step = max(1, n // 160)
viz["shot"] = {"fps": hk.FPS, "t_bounce": float(tl), "out_cm": float(d * 100),
               "traj": [[round(float(t), 4), *[round(float(c), 4) for c in traj[j]]] for j, t in
                        ((j, j / hk.FPS) for j in range(0, n, step))],
               "land": [float(land[0]), float(land[1])], "preds": preds}

# 2. a real Polymarket jump with fast-tier prints (in sample)
sh = pd.read_parquet("data/derived/shadow_is_uncapped.parquet")
jumps = pd.read_parquet("data/derived/jumps_is.parquet")
u = pd.read_parquet("data/derived/universe_is.parquet").set_index("cond")
# chosen for recognisability (illustration only): Cincinnati Open, Nakashima vs Medvedev, 2026-08-18 (IS)
EXAMPLE = "0x2182f29dc74fa806d339b812e387147dc49422fee17cd67252de6c193f86db18"
cond = EXAMPLE
j = jumps[(jumps.cond == cond) & (jumps["size"].between(0.07, 0.2))]
for _, jj in j.iterrows():
    f = sh[(sh.cond == cond) & (sh.ts >= jj.onset_ts) & (sh.ts <= jj.onset_ts + 3)]
    if len(f) >= 3:
        break
row = u.loc[cond]
t = load_tape(cond)
t = t[(t.timestamp >= jj.onset_ts - 90) & (t.timestamp <= jj.onset_ts + 150)]
fast_keys = set(zip(f.ts.astype(int), f.wallet))
viz["tape"] = {"title": row.title, "date": str(row.start)[:10], "out0": row.out0, "out1": row.out1,
               "volume": float(row.volume), "jump": float(jj["size"]) * float(jj.dir),
               "prints": [{"t": int(r.timestamp - jj.onset_ts), "p": round(float(r.p0), 4), "ask": bool(r.at_ask),
                           "usd": round(float(r.usd), 1), "fast": (int(r.timestamp), r.proxyWallet) in fast_keys}
                          for r in t.itertuples()]}

# 3. charts from the summary
wf = pd.DataFrame(S["is"]["h6_walkforward"]); wo = pd.DataFrame(S["oos"]["h6_walkforward"])
wf_all = pd.concat([wf[wf.month < "2026-08"], wo], ignore_index=True)
viz["walkforward"] = wf_all[["month", "n_wallets", "net30_c", "others_net30_c", "follow_res_c", "usd_k"]].round(3).to_dict("records")
viz["calibration"] = pd.DataFrame(S["is"]["calibration"])[["bin", "mean_price", "win_rate", "lo", "hi", "n_matches"]].round(4).to_dict("records")
viz["physics"] = pd.DataFrame(S["tracking_tennis_physics"])[["lead_ms", "pred_err_sd_cm"]].dropna().round(3).to_dict("records")
h4 = pd.read_csv("results/h4_leads.csv")
viz["h4"] = {"leads": h4.lead_s.round(2).tolist(), "median": float(h4.lead_s.median()), "book_first": float((h4.lead_s > 0).mean())}
viz["tests"] = {
    "h1": {"is": S["is"]["h1"]["J0.04_H30"], "oos": S["oos"]["h1"]["J0.04_H30"]},
    "h2": {"is": S["is"]["h2"]["lo0.85_hi0.97"], "oos": S["oos"]["h2"]["lo0.85_hi0.97"]},
    "h5": {"is": S["is"]["h5"]["J0.04_W30"], "oos": S["oos"]["h5"]["J0.04_W30"]},
    "h6": {"is": S["is"]["h6_shadow"], "oos": S["oos"]["h6_shadow"]},
}
viz["universe"] = S["universe"]
# fast tier vs everyone else by seconds since the score event (same construction as Fig. 1)
from src import fasttier
pr = pd.read_parquet("data/is_prints.parquet", columns=["cond", "ts", "wallet", "bucket", "p", "fee_rate", "mo30", "mo_res", "mo5", "mo15", "delay", "spread", "dir", "usd"])
_, _, bb = fasttier.walk_forward(pr)
order = ["0-3s", "3-6s", "6-10s", "10-20s", "20-40s", "40-120s", ">120s"]
bb = bb.reindex(order)
viz["tiers"] = [{"bucket": k, "fast": round(float(bb.loc[k, "fast"]), 3), "others": round(float(bb.loc[k, "others"]), 3)} for k in order]
del pr
lev = json.loads(Path("results/leverage_stats.json").read_text())
viz["leverage"] = lev
viz["books"] = {"tennis": {"spread_c": 1.0, "top_usd": 8108, "depth2c_usd": 60918, "empty": 0.07},
                "table_tennis": {"spread_c": 89.0, "top_usd": 23, "depth2c_usd": 582, "empty": 0.25}}
Path(OUT / "viz_data.json").write_text(json.dumps(viz, separators=(",", ":"), default=str))
print("shot out_cm", round(d * 100, 1), "t_bounce", round(tl, 3), "preds", len(preds))
print("tape", viz["tape"]["title"], viz["tape"]["date"], "jump", round(viz["tape"]["jump"], 3), "prints", len(viz["tape"]["prints"]),
      "fast", sum(p["fast"] for p in viz["tape"]["prints"]))
print("bytes", (OUT / "viz_data.json").stat().st_size)
