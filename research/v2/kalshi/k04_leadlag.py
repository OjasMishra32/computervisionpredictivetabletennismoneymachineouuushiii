"""Step 4: Kalshi <-> Polymarket lead-lag on matched IS tennis matches.

Three measurements, all on a common 1-second grid (state at the end of each second; Kalshi
timestamps are microsecond trade times floored to the second, Polymarket timestamps are the
data-api trade timestamps in whole seconds = Polygon block time, which is >= the CLOB match time):

 A. Cross-correlation of 1 s mid-proxy returns at lags -30..+30 s, pooled over matches.
 B. Event study: anchors = Polymarket jumps (data/derived/jumps_is, detect_ts) U Kalshi jumps
    (same detector, src.tiers.jump_onsets, on Kalshi prints), merged within 30 s/same direction.
    For each event and venue: pre = median mid over [A-60, A-30], post = median mid over [A+30, A+60],
    move = d*(post-pre); t50 = first second in [A-30, A+30] where d*(mid-pre) >= move/2.
    lead = t50_PM - t50_K (> 0: Kalshi reprices first). Only events where BOTH venues moved >= 2c.
 C. Fast-tier check: for every 0-3 s Polymarket print (fast-tier wallets vs everyone else), how far
    Kalshi's mid was already ahead of the print price 1 s before the print.

Outputs: research/v2/kalshi/out/leadlag_events.parquet, ccf.csv, fasttier_vs_kalshi.csv, leadlag_summary.json
Run: .venv/bin/python research/v2/kalshi/k04_leadlag.py
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from k_common import OUT, ROOT, load_k, load_matched, load_pm, mid_grid, window  # noqa: E402
from src.tiers import jump_onsets  # noqa: E402

LAGS = np.arange(-30, 31)
_J = None
_FAST = None


def _init():
    global _J, _FAST
    j = pd.read_parquet(ROOT / "data/derived/jumps_is.parquet", columns=["cond", "detect_ts", "onset_ts", "dir", "size"])
    _J = {c: g for c, g in j.groupby("cond")}
    f = pd.read_parquet(ROOT / "data/derived/prints_0_3s_is.parquet", columns=["cond", "ts", "p", "dir", "usd", "wallet"])
    s = pd.read_parquet(ROOT / "data/derived/shadow_is_uncapped.parquet", columns=["cond", "ts", "wallet"])
    s["fast"] = True
    f = f.merge(s.drop_duplicates(["cond", "ts", "wallet"]), on=["cond", "ts", "wallet"], how="left")
    f["fast"] = f.fast.fillna(False).astype(bool)
    _FAST = {c: g for c, g in f.groupby("cond")}


def one(row) -> dict | None:
    pm, k = load_pm(row), load_k(row)
    if pm is None or k is None or len(pm) < 20 or len(k) < 20:
        return None
    s, e = window(row)
    grid = np.arange(int(s), int(e) + 1, dtype=float)
    if len(grid) < 600:
        return None
    mp, ap, bp = mid_grid(pm.ts.values, pm.p.values, pm.ask.values, grid)
    mk, ak, bk = mid_grid(k.ts.values, k.p.values, k.ask.values, grid)

    # A. CCF of 1 s returns (sum of products, pooled later)
    rp, rk = np.diff(mp), np.diff(mk)
    ok = np.isfinite(rp) & np.isfinite(rk)
    rp, rk = np.where(ok, rp, 0.0), np.where(ok, rk, 0.0)
    n = len(rp)
    cc = np.array([np.dot(rp[max(0, -L):n - max(0, L)], rk[max(0, L):n - max(0, -L)]) for L in LAGS])
    # cc[L] = sum_t rp(t) * rk(t+L): peak at L>0 means PM moves first, L<0 means Kalshi moves first
    a_out = {"cc": cc, "spp": float(rp @ rp), "skk": float(rk @ rk), "n": int(ok.sum())}

    # B. events
    kj = jump_onsets(k.ts.values, k.p.values, k.usd.values)  # (onset, dir, size, detect)
    pj = _J.get(row.cond)
    anchors = [(d_t, int(dr), "k") for (_, dr, _, d_t) in kj]
    if pj is not None:
        anchors += [(float(x.detect_ts), int(x.dir), "pm") for x in pj.itertuples()]
    anchors.sort()
    events, cur = [], None
    for t, dr, src in anchors:
        if cur and dr == cur["d"] and t - cur["A"] <= 30:
            cur["src"].add(src)
            cur.setdefault(f"det_{src}", t)
            continue
        if cur:
            events.append(cur)
        cur = {"A": t, "d": dr, "src": {src}, f"det_{src}": t}
    if cur:
        events.append(cur)
    ev_rows = []
    for ev in events:
        A, d = int(ev["A"]), ev["d"]
        i0 = int(A - grid[0])
        if i0 - 60 < 0 or i0 + 60 >= len(grid):
            continue
        rec = {"cond": row.cond, "A": ev["A"], "d": d, "src": "+".join(sorted(ev["src"])),
               "det_pm": ev.get("det_pm", np.nan), "det_k": ev.get("det_k", np.nan)}
        for name, m in (("pm", mp), ("k", mk)):
            pre = np.nanmedian(m[i0 - 60:i0 - 29])
            post = np.nanmedian(m[i0 + 30:i0 + 61])
            mv = d * (post - pre)
            rec[f"move_{name}"] = mv
            rec[f"pre_{name}"] = pre
            seg = d * (m[i0 - 30:i0 + 31] - pre)
            t50 = t10 = np.nan
            if np.isfinite(mv) and mv >= 0.02:
                h = np.nonzero(seg >= 0.5 * mv)[0]
                t50 = float(h[0] - 30) if len(h) else np.nan
                h = np.nonzero(seg >= 0.2 * mv)[0]
                t10 = float(h[0] - 30) if len(h) else np.nan
            rec[f"t50_{name}"], rec[f"t20_{name}"] = t50, t10
            # normalised path for the average curve
            rec[f"path_{name}"] = (seg / mv).astype(np.float32) if np.isfinite(mv) and mv >= 0.02 else None
        ev_rows.append(rec)

    # C. fast-tier prints vs Kalshi state
    c_rows = []
    f = _FAST.get(row.cond)
    if f is not None and len(f):
        idx = (f.ts.values - grid[0]).astype(int)
        okf = (idx - 10 >= 0) & (idx + 30 < len(grid))
        for x, i in zip(f[okf].itertuples(), idx[okf]):
            c_rows.append({"cond": row.cond, "ts": x.ts, "fast": x.fast, "dir": x.dir, "p": x.p, "usd": x.usd,
                           "k_lead_1": x.dir * (mk[i - 1] - x.p), "k_lead_5": x.dir * (mk[i - 5] - x.p),
                           "k_lead_10": x.dir * (mk[i - 10] - x.p),
                           "k_mo30": x.dir * (mk[i + 30] - x.p), "pm_mo30": x.dir * (mp[i + 30] - x.p)})
    return {"cond": row.cond, "A": a_out, "ev": ev_rows, "fast": c_rows,
            "n_pm": len(pm), "n_k": len(k), "q_pm_usd": float(pm.usd.sum()), "q_k_usd": float(k.usd.sum())}


def main():
    m = load_matched()
    rows = [SimpleNamespace(**r) for r in m.to_dict("records")]
    with ProcessPoolExecutor(2, initializer=_init) as ex:
        res = [r for r in ex.map(one, rows, chunksize=8) if r is not None]
    meta = m.set_index("cond")
    # A
    cc = sum(r["A"]["cc"] for r in res)
    spp = sum(r["A"]["spp"] for r in res); skk = sum(r["A"]["skk"] for r in res)
    ccf = pd.DataFrame({"lag": LAGS, "corr": cc / np.sqrt(spp * skk)})
    OUT.mkdir(parents=True, exist_ok=True)
    ccf.to_csv(OUT / "ccf.csv", index=False)
    by_delay = {}
    for dly in (1, 3):
        rr = [r for r in res if meta.loc[r["cond"], "delay"] == dly]
        c = sum(r["A"]["cc"] for r in rr); a = sum(r["A"]["spp"] for r in rr); b = sum(r["A"]["skk"] for r in rr)
        by_delay[dly] = (c / np.sqrt(a * b)).tolist()
    pd.DataFrame({"lag": LAGS, "delay1": by_delay[1], "delay3": by_delay[3]}).to_csv(OUT / "ccf_by_delay.csv", index=False)
    # B
    ev = pd.DataFrame([e for r in res for e in r["ev"]])
    ev = ev.merge(m[["cond", "month", "delay", "fee_rate", "series"]], on="cond")
    paths = ev[["path_pm", "path_k"]]
    ev.drop(columns=["path_pm", "path_k"]).to_parquet(OUT / "leadlag_events.parquet")
    both = ev[(ev.move_pm >= 0.02) & (ev.move_k >= 0.02) & ev.t50_pm.notna() & ev.t50_k.notna()].copy()
    both["lead"] = both.t50_pm - both.t50_k
    avg = {}
    for name in ("pm", "k"):
        P = np.stack([p for p in paths.loc[both.index, f"path_{name}"]])
        avg[name] = np.nanmean(np.clip(P, -1, 2), axis=0)
    pd.DataFrame({"tau": np.arange(-30, 31), "pm": avg["pm"], "k": avg["k"]}).to_csv(OUT / "event_avg_path.csv", index=False)
    # C
    fc = pd.DataFrame([c for r in res for c in r["fast"]])
    fc.to_parquet(OUT / "fasttier_vs_kalshi.parquet")

    def lead_stats(x):
        return {"n": int(len(x)), "median_lead_s": float(x.lead.median()), "mean_lead_s": float(x.lead.mean()),
                "p_kalshi_first": float((x.lead > 0).mean()), "p_same_second": float((x.lead == 0).mean()),
                "p_pm_first": float((x.lead < 0).mean()),
                "q10": float(x.lead.quantile(.1)), "q25": float(x.lead.quantile(.25)),
                "q75": float(x.lead.quantile(.75)), "q90": float(x.lead.quantile(.9))}

    summ = {
        "matches_used": len(res),
        "pm_prints": int(sum(r["n_pm"] for r in res)), "kalshi_prints": int(sum(r["n_k"] for r in res)),
        "pm_usd_inplay": float(sum(r["q_pm_usd"] for r in res)), "kalshi_usd_inplay": float(sum(r["q_k_usd"] for r in res)),
        "ccf_peak_lag": int(ccf.lag[ccf["corr"].idxmax()]), "ccf_peak": float(ccf["corr"].max()),
        "ccf_lag0": float(ccf.loc[ccf.lag == 0, "corr"].iloc[0]),
        "ccf_sum_kalshi_leads(lags<0)": float(ccf.loc[ccf.lag < 0, "corr"].sum()),
        "ccf_sum_pm_leads(lags>0)": float(ccf.loc[ccf.lag > 0, "corr"].sum()),
        "events_total": int(len(ev)), "events_both_moved": int(len(both)),
        "lead_all": lead_stats(both),
        "lead_by_delay": {int(k): lead_stats(g) for k, g in both.groupby("delay")},
        "lead_by_regime": {f"{r}/{d}s": lead_stats(g) for (r, d), g in both.groupby(["fee_rate", "delay"])},
        "lead_by_src": {k: lead_stats(g) for k, g in both.groupby("src")},
        "lead_by_month": {k: lead_stats(g) for k, g in both.groupby("month")},
        "t50_pm_median": float(both.t50_pm.median()), "t50_k_median": float(both.t50_k.median()),
        "fasttier": {
            k: {"n": int(len(g)), "k_lead_1_mean_c": float(100 * g.k_lead_1.mean()),
                "k_lead_5_mean_c": float(100 * g.k_lead_5.mean()), "k_lead_10_mean_c": float(100 * g.k_lead_10.mean()),
                "share_k_ahead_1c": float((g.k_lead_1 >= 0.01).mean()),
                "pm_mo30_c": float(100 * g.pm_mo30.mean()), "k_mo30_c": float(100 * g.k_mo30.mean())}
            for k, g in fc.groupby(fc.fast.map({True: "fast_tier", False: "others"}))} if len(fc) else {},
    }
    (OUT / "leadlag_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps({k: v for k, v in summ.items() if k != "lead_by_month"}, indent=1))


if __name__ == "__main__":
    main()
