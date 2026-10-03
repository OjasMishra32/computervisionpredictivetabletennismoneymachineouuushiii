"""TT5 audit follow-up: what the same-block (since_det = 0) bin holds, where v2's backtest fills sit in it, and the
period mix behind the pooled decay test. Post-hoc diagnostics for the verifier's fixes; not pre-registered, no
verdict change.

    python research/decay/audit_sameblock.py     # -> results/decay/audit_sameblock.json (logged before it runs)

What it does
  1. Labels every tennis taker print (U1 IS + burned OOS) and every UTT table tennis print exactly as
     scripts/signal_decay.py does: src.tiers.jump_onsets per match (via a copy that also returns the index of the
     detection print, checked equal to src.tiers.jump_onsets on every match), since_det / with_jump_det as in
     src.tiers.add_causal_bucket, net30 = mo30 - fee_rate*p*(1-p), and the walk-forward fast tier with
     src.fasttier.qualify. It asserts the same-block counts and means equal results/decay/decay.json.
  2. Splits the same-block bin into prints at or before the detection print (file order inside the block: they are
     the prints that make up the detection, so nothing that reacts to the detection can be among them) and prints
     strictly after it.
  3. Joins data/v2_trades_is_oos.parquet (the frozen v2 backtest trades) to those labels on
     (cond, ts, wallet, p, usd, dir) and splits v2's P&L the same way.
  4. Period mix of the pre-registered decay test: with-jump [1, 2) vs [10, 30) by calendar quarter, and the test
     restricted to 2026-Q2 on (the first quarter with 1 s stamp gaps), net and gross of the fee.
  5. Copies the live-bot read-offs from results/decay/decay.json (no data read for those).

Runs in one process on the laptop (about 3 minutes, ~3 GB).
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src import fasttier, tiers  # noqa: E402
from scripts import signal_decay as SD  # noqa: E402

OUT = ROOT / "results/decay/audit_sameblock.json"
COLS = ["cond", "ts", "p", "dir", "usd", "wallet", "fee_rate", "mo30"]
KEY = ["cond", "ts", "wallet", "p", "usd", "dir"]


def jump_onsets_idx(ts, p, usd, J=0.04, short_w=10, long_w=60):
    """src.tiers.jump_onsets line for line, plus the index i of the print at which each detection fires."""
    pv, v = np.cumsum(p * usd), np.cumsum(usd)
    on, idx, last = [], [], -1e18
    for i in range(len(ts)):
        now = ts[i]
        if now - last < long_w:
            continue
        a = np.searchsorted(ts, now - short_w, "left")
        b = np.searchsorted(ts, now - short_w - long_w, "left")
        if a <= b or a > i:
            continue
        s1 = pv[i] - (pv[a - 1] if a else 0); w1 = v[i] - (v[a - 1] if a else 0)
        s2 = (pv[a - 1] if a else 0) - (pv[b - 1] if b else 0); w2 = (v[a - 1] if a else 0) - (v[b - 1] if b else 0)
        if w1 <= 0 or w2 <= 0:
            continue
        d = s1 / w1 - s2 / w2
        if abs(d) >= J:
            last = now
            on.append((ts[a], np.sign(d), abs(d), now))
            idx.append(i)
    return on, idx


def load(paths: list[tuple[str, str]]) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Prints with cond/wallet as integer codes (factorize(sort=True), as signal_decay.prep); returns the uniques."""
    P = pd.concat([pd.read_parquet(ROOT / f, columns=COLS).assign(period=per) for f, per in paths], ignore_index=True)
    c, cu = pd.factorize(P.cond, sort=True)
    w, wu = pd.factorize(P.wallet, sort=True)
    P["cond"], P["wallet"] = c, w
    return P, np.asarray(cu), np.asarray(wu)


def label(P: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """since_det, with_jump_det (add_causal_bucket's definitions), at_or_before_det, is_det_print, net30, fast."""
    P = P.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)  # add_causal_bucket's order
    cond = P.cond.to_numpy()
    starts = np.flatnonzero(np.r_[True, cond[1:] != cond[:-1]])
    ends = np.r_[starts[1:], len(P)]
    ts_all, p_all, u_all, d_all = (P[c].to_numpy(float) for c in ("ts", "p", "usd", "dir"))
    since = np.full(len(P), -1.0)
    wj = np.zeros(len(P))
    pre = np.zeros(len(P), bool)
    isdet = np.zeros(len(P), bool)
    n_det, mismatch = 0, 0
    for s, e in zip(starts, ends):
        ts, p, u = ts_all[s:e], p_all[s:e], u_all[s:e]
        on, ix = jump_onsets_idx(ts, p, u)
        if on != tiers.jump_onsets(ts, p, u):
            mismatch += 1
        n_det += len(on)
        if not on:
            continue
        dt_ = np.array([o[3] for o in on]); dd = np.array([o[1] for o in on]); ix = np.array(ix)
        k = np.searchsorted(dt_, ts, "right") - 1
        kk = np.maximum(k, 0)
        since[s:e] = np.where(k >= 0, ts - dt_[kk], -1.0)
        wj[s:e] = np.where(k >= 0, d_all[s:e] * dd[kk], 0.0)
        pos = np.arange(e - s)
        pre[s:e] = (k >= 0) & (ts == dt_[kk]) & (pos <= ix[kk])
        isdet[s + ix] = True
    assert mismatch == 0, f"{mismatch} matches where the index copy differs from tiers.jump_onsets"
    P["since_det"], P["with_jump_det"], P["at_or_before_det"], P["is_det_print"] = since, wj, pre, isdet
    P["fee"] = P.fee_rate * P.p * (1 - P.p)
    P["net30"] = P.mo30 - P.fee
    # walk-forward fast tier: signal_decay.prep's loop (qualify sees only the causal 0-3 s rows)
    month = pd.to_datetime(P.ts, unit="s").dt.to_period("M")
    months = sorted(month.unique())
    in03 = ((P.since_det >= 0) & (P.since_det < 3)).to_numpy()
    f03 = P.loc[in03, ["cond", "wallet", "mo30"]].assign(bucket_c="0-3s", month=month[in03])
    fast = np.full(len(P), np.nan)
    for m in months[2:]:
        sel = fasttier.qualify(f03[f03.month < m], "bucket_c")
        cur = (month == m).to_numpy()
        fast[cur] = np.isin(P.wallet.to_numpy()[cur], sel)
    P["fast"] = fast
    P["quarter"] = pd.to_datetime(P.ts, unit="s").dt.to_period("Q")
    return P, {"detections": n_det, "matches": int(P.cond.nunique()), "prints": int(len(P)),
               "jump_onsets_parity_mismatches": mismatch}


def stat(x: pd.DataFrame, col: str = "net30") -> dict:
    x = x[np.isfinite(x[col].to_numpy())]
    if not len(x):
        return {"n": 0}
    out = {"n": int(len(x)), "matches": int(x.cond.nunique()), "mean_c": round(100 * float(x[col].mean()), 4)}
    if x.cond.nunique() > 1:
        lo, hi = fasttier.cluster_ci(x[["cond", col]], col, SD.N_BOOT, SD.SEED)
        out["ci_c"] = [round(100 * lo, 4), round(100 * hi, 4)]
    return out


def same_block(P: pd.DataFrame) -> dict:
    z = P[P.since_det == 0]
    fin = np.isfinite(z.net30.to_numpy())
    r = {"prints": int(len(z)), "at_or_before_det": int(z.at_or_before_det.sum()),
         "detection_prints": int(z.is_det_print.sum()),
         "share_at_or_before": round(float(z.at_or_before_det.mean()), 4) if len(z) else None}
    for name, sel in (("all", np.ones(len(z), bool)), ("with_jump", (z.with_jump_det > 0).to_numpy()),
                      ("fast", (z.fast == 1).to_numpy())):
        g = z[sel & fin]
        r[name] = {"n_with_net30": int(len(g)), "at_or_before_det": int(g.at_or_before_det.sum()),
                   "detection_prints": int(g.is_det_print.sum()),
                   "share_at_or_before": round(float(g.at_or_before_det.mean()), 4) if len(g) else None,
                   "net30_whole_bin": stat(g), "net30_at_or_before": stat(g[g.at_or_before_det]),
                   "net30_strictly_after": stat(g[~g.at_or_before_det])}
    return r


def v2_split(P: pd.DataFrame, cu: np.ndarray, wu: np.ndarray) -> dict:
    T = pd.read_parquet(ROOT / "data/v2_trades_is_oos.parquet",
                        columns=KEY + ["since_det", "pnl", "shares", "usd_in"]).rename(columns={"since_det": "since_det_v2"})
    T["cond"] = pd.Index(cu).get_indexer(T.cond)
    T["wallet"] = pd.Index(wu).get_indexer(T.wallet)
    n_unknown = int(((T.cond < 0) | (T.wallet < 0)).sum())  # cond or wallet absent from the print files
    L = P[KEY + ["since_det", "at_or_before_det", "is_det_print", "period"]].drop_duplicates(KEY, keep=False)
    M = T.merge(L, on=KEY, how="left", validate="m:1")
    ok = M.since_det.notna()
    M = M[ok].copy()
    M["at_or_before_det"] = M.at_or_before_det.astype(bool)
    M["is_det_print"] = M.is_det_print.astype(bool)

    def part(x):
        return {"trades": int(len(x)), "pnl_usd": round(float(x.pnl.sum()), 2), "usd_in": round(float(x.usd_in.sum()), 2),
                "per_share_c": round(100 * float(x.pnl.sum() / x.shares.sum()), 4) if len(x) else None}
    out = {"v2_trades": int(len(T)), "cond_or_wallet_not_in_prints": n_unknown,
           "matched_to_a_unique_print": int(len(M)),
           "since_det_agrees_with_v2_file": round(float((M.since_det == M.since_det_v2).mean()), 6)}
    for per, g in [("IS+burned_OOS", M)] + [(p, M[M.period == p]) for p in ("IS", "burned_OOS")]:
        sb = g[g.since_det == 0]
        out[per] = {"all_matched": part(g), "same_block": part(sb),
                    "same_block_share_of_trades": round(len(sb) / len(g), 4) if len(g) else None,
                    "same_block_at_or_before_det": part(sb[sb.at_or_before_det]),
                    "same_block_detection_print_itself": part(sb[sb.is_det_print]),
                    "same_block_strictly_after_det": part(sb[~sb.at_or_before_det]),
                    "since_det_1_to_2": part(g[g.since_det > 0])}
    return out


def period_mix(P: pd.DataFrame) -> dict:
    w = P[(P.with_jump_det > 0) & np.isfinite(P.net30.to_numpy())]
    by_q = {}
    for q, g in w.groupby("quarter"):
        a = g[(g.since_det >= 1) & (g.since_det < 2)]
        b = g[(g.since_det >= 10) & (g.since_det < 30)]
        by_q[str(q)] = {"n_1_2": int(len(a)), "net30_1_2_c": round(100 * float(a.net30.mean()), 4) if len(a) else None,
                   "fee_1_2_c": round(100 * float(a.fee.mean()), 4) if len(a) else None,
                   "n_10_30": int(len(b)), "net30_10_30_c": round(100 * float(b.net30.mean()), 4) if len(b) else None,
                   "fee_10_30_c": round(100 * float(b.fee.mean()), 4) if len(b) else None}
    q2 = P[P.ts >= pd.Timestamp("2026-04-01", tz="UTC").timestamp()]
    return {"with_jump_by_quarter": by_q,
            "prereg_test_pooled_as_run_net": SD.decay_test(P),
            "prereg_test_pooled_gross": SD.decay_test(P, "mo30"),
            "prereg_test_2026Q2_on_net": SD.decay_test(q2),
            "prereg_test_2026Q2_on_gross": SD.decay_test(q2, "mo30"),
            "prereg_test_2026Q2_on_IS_only_net": SD.decay_test(q2[q2.period == "IS"])}


def readoffs() -> dict:
    """Live-bot read-offs, copied from results/decay/decay.json (no data read)."""
    J = json.loads((ROOT / "results/decay/decay.json").read_text())
    out = {}
    for sub in ("IS+burned_OOS", "burned_OOS"):
        s = J["tennis"]["subsets"][sub]
        out[sub] = {f"{scheme}:{b}": {c: s[k]["curves"][c]["net30"][b] if k else s["curves"][c]["net30"][b]
                                      for c in ("with_jump", "fast")}
                    for scheme, k, bins in (("prereg", None, ("0-0.25", "1-2", "2-3", "3-5")),
                                            ("block", "block", ("1-3",)))
                    for b in bins}
    out["block_lag_s"] = J["latency_inputs"]["block_lag_s"]
    out["net_florida_s"] = J["latency_inputs"]["net_florida_s"]
    return out


def git_ref() -> str:
    h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    d = subprocess.run(["git", "status", "--porcelain", "research/decay/audit_sameblock.py"], cwd=ROOT,
                       capture_output=True, text=True).stdout.strip()
    return h + ("+uncommitted(audit_sameblock.py)" if d else "")


def check(r: dict, J: dict, sub: str, key: str):
    """The labels must reproduce the same-block cells of results/decay/decay.json exactly."""
    for c in ("with_jump", "fast"):
        ref = J[key]["subsets"][sub]["curves"][c]["net30"]["0-0.25"]
        got = r[c]["net30_whole_bin"]
        assert got["n"] == ref["n"] and abs(got["mean_c"] - ref["mean_c"]) < 1e-3, (sub, c, got, ref)


def main():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    ref = git_ref()
    what = ("audit: TT5 same-block split and v2 trade join (research/decay/audit_sameblock.py): re-reads tennis U1 IS + "
            "burned OOS prints (non-blind, already evaluated in 114c722), UTT prints (already evaluated) and "
            "data/v2_trades_is_oos.parquet; post-hoc diagnostics for the verifier's fixes; no rule, parameter or "
            "verdict change")
    with open(ROOT / "results/tt/peeks.log", "a") as f:
        f.write(f"{now} {what} commit={ref}\n")
    with open(ROOT / "results/oos_peeks.log", "a") as f:
        f.write(f"{now} {what}\n")
    t0 = time.time()
    J = json.loads((ROOT / "results/decay/decay.json").read_text())
    out = {"label": "post-hoc audit diagnostics, not pre-registered; no verdict change", "run_utc": now, "commit": ref,
           "where": "laptop, one process; HiPerGator not used"}

    T, _, _ = load([("data/tt/prints.parquet", "UTT")])
    T, tm = label(T)
    out["table_tennis"] = {"meta": tm, "same_block": same_block(T)}
    print("table tennis", tm, round(time.time() - t0), "s", flush=True)

    P, cu, wu = load([("data/is_prints.parquet", "IS"), ("data/locked/oos_prints.parquet", "burned_OOS")])
    P, pm = label(P)
    print("tennis labelled", pm, round(time.time() - t0), "s", flush=True)
    assert pm["detections"] == J["tennis"]["meta"]["detections"]
    out["tennis"] = {"meta": pm}
    for sub, g in (("IS+burned_OOS", P), ("IS", P[P.period == "IS"]), ("burned_OOS", P[P.period == "burned_OOS"])):
        r = same_block(g)
        check(r, J, sub, "tennis")
        out["tennis"][sub] = {"same_block": r}
        print(" ", sub, "same block", r["prints"], r["at_or_before_det"], flush=True)
    out["v2_backtest_trades"] = v2_split(P, cu, wu)
    print("v2 join", json.dumps(out["v2_backtest_trades"]["IS+burned_OOS"])[:600], flush=True)
    out["period_mix"] = period_mix(P)
    out["readoffs_from_decay_json"] = readoffs()
    out["seconds"] = round(time.time() - t0, 1)
    OUT.write_text(json.dumps(out, indent=1, default=float))
    print("wrote", OUT, out["seconds"], "s")


if __name__ == "__main__":
    main()
