"""Step 2b: per-print tables joining each IS side market to its own match's moneyline.

Outputs (data/v2_crossmarket/):
  side_prints.parquet  every in-play side-market taker print j, with only-causal context:
     * t_send = ts_j - delay: when an order that filled against print j had to be sent;
     * the latest moneyline jump detected at or before t_send - 1 s (our latency):
       onset, detect, jdir, jsize (from data/derived/jumps_is.parquet);
     * ref_send: the side market's mid proxy at its last print strictly before t_send (q_rs,
       its time ts_rs) and the moneyline mid then (p_rs) and at t_send (p_send);
     * ref_on: the side market's mid proxy at its last print strictly before the jump onset
       (q_ro, ts_ro) and the moneyline mid then (p_ro); moneyline mid at the print (p_now);
     * markouts of the taker who printed: 60 s / 300 s vs the side mid proxy, and to resolution.
  intervals.parquet    consecutive in-play prints of each side market (<= 300 s apart) with the
                       moneyline mid at both times: the sample for the sensitivity (beta) fits.
Mid proxies use tiers._mid_series: mean of the latest bid-side and ask-side prints (<= 30 s old on
the moneyline, <= 120 s on the thinner side markets), else the print itself.
Run: .venv/bin/python research/v2/crossmarket/build.py
"""
from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from common import CACHE, OOS_CUT, ROOT, TRADES_DIR, load_side_tape, side_markets, universe_is  # noqa: E402
from src.tape import load_tape  # noqa: E402
from src.tiers import _mid_series  # noqa: E402

MAX_GAP = 300
WORKERS = 2
OUR_LATENCY = 1


def _last(ts: np.ndarray, t, side="right"):
    return np.searchsorted(ts, t, side) - 1


def process(args):
    ml_row, sides, jumps = args
    s0 = int(pd.Timestamp(ml_row["start"]).timestamp())
    e0 = int(pd.Timestamp(ml_row["end"]).timestamp()) if pd.notna(ml_row["end"]) else s0 + 6 * 3600
    ml = load_tape(ml_row["cond"])
    if ml is None:
        return None, None
    ml = ml[(ml.timestamp >= s0) & (ml.timestamp <= e0)].reset_index(drop=True)
    if len(ml) < 20:
        return None, None
    mts = ml.timestamp.to_numpy().astype(float)
    mmid, _ = _mid_series(mts, ml.p0.to_numpy(), ml.at_ask.to_numpy(), stale=30)

    def ml_at(t, side="right"):
        t = np.asarray(t, float)
        i = _last(mts, t, side)
        return np.where((i >= 0) & np.isfinite(t), mmid[np.maximum(i, 0)], np.nan)

    on = jumps.onset_ts.to_numpy().astype(float)
    det = jumps.detect_ts.to_numpy().astype(float)
    jdir = jumps.dir.to_numpy().astype(float)
    jsz = jumps["size"].to_numpy().astype(float)
    pr_parts, iv_parts = [], []
    for sr in sides:
        t = load_side_tape(sr["cond"])
        if t is None:
            continue
        t = t[(t.timestamp >= s0) & (t.timestamp <= e0)].reset_index(drop=True)
        n = len(t)
        if n < 2:
            continue
        ts = t.timestamp.to_numpy().astype(float)
        q = t.q0.to_numpy()
        aa = t.at_ask.to_numpy()
        smid, _ = _mid_series(ts, q, aa, stale=120)
        d = np.where(aa, 1.0, -1.0)
        p_now = ml_at(ts)
        gap = np.diff(ts)
        ok = gap <= MAX_GAP
        if ok.any():
            i1 = np.flatnonzero(ok) + 1
            iv_parts.append(pd.DataFrame({
                "cond": sr["cond"], "ts": ts[i1], "dt": gap[ok], "q1": q[i1 - 1], "q2": q[i1],
                "m1": smid[i1 - 1], "m2": smid[i1], "a1": aa[i1 - 1], "a2": aa[i1],
                "p1": p_now[i1 - 1], "p2": p_now[i1]}))
        t_send = ts - sr["delay"]
        # latest jump whose detection + our latency is at or before the send time
        k = _last(det, t_send - OUR_LATENCY) if len(det) else np.full(n, -1)
        has = k >= 0
        kk = np.maximum(k, 0)

        def pick(a, fill=np.nan):
            return np.where(has, a[kk], fill) if len(a) else np.full(n, fill)

        onset, detect = pick(on), pick(det)
        # side reference strictly before the send time
        jr = _last(ts, t_send, "left")
        okr = jr >= 0
        q_rs = np.where(okr, smid[np.maximum(jr, 0)], np.nan)
        ts_rs = np.where(okr, ts[np.maximum(jr, 0)], np.nan)
        # side reference strictly before the jump onset
        jo = np.where(has, _last(ts, np.nan_to_num(onset, nan=-1e18), "left"), -1)
        oko = jo >= 0
        q_ro = np.where(oko, smid[np.maximum(jo, 0)], np.nan)
        ts_ro = np.where(oko, ts[np.maximum(jo, 0)], np.nan)
        nxt = np.searchsorted(on, ts, "right") if len(on) else np.zeros(n, int)
        to_next = np.where(nxt < len(on), on[np.minimum(nxt, len(on) - 1)] - ts, np.nan) if len(on) else np.full(n, np.nan)
        res = sr["res_s0"]
        mo = {}
        for h in (60, 300):
            j = _last(ts, ts + h)
            mo[f"mo{h}"] = d * (smid[j] - q)
        pr_parts.append(pd.DataFrame({
            "cond": sr["cond"], "ml_cond": ml_row["cond"], "ts": ts, "q0": q, "at_ask": aa,
            "size": t["size"].to_numpy(), "usd": t.usd.to_numpy(), "wallet": t.proxyWallet.to_numpy(),
            "smid": smid, "p_now": p_now, "t_send": t_send,
            "jump_k": np.where(has, kk, -1), "onset": onset, "detect": detect,
            "jdir": pick(jdir, 0.0), "jsize": pick(jsz),
            "p_pre": ml_at(onset, "left"), "p_det": ml_at(detect), "p_send": ml_at(t_send, "left"),
            "q_rs": q_rs, "ts_rs": ts_rs, "p_rs": ml_at(ts_rs),
            "q_ro": q_ro, "ts_ro": ts_ro, "p_ro": ml_at(ts_ro),
            "to_next_onset": to_next,
            "mo_res": d * (res - q) if res in (0.0, 1.0) else np.full(n, np.nan), **mo}))
    pr = pd.concat(pr_parts, ignore_index=True) if pr_parts else None
    iv = pd.concat(iv_parts, ignore_index=True) if iv_parts else None
    return pr, iv


def main():
    u = universe_is()
    sm = side_markets()
    have = {p.stem for p in TRADES_DIR.glob("*.parquet")}
    sm = sm[sm.cond.isin(have) & (sm.smt != "tennis_completed_match")]
    jumps = pd.read_parquet(ROOT / "data" / "derived" / "jumps_is.parquet").sort_values(["cond", "detect_ts"])
    jg = dict(tuple(jumps.groupby("cond")))
    empty = jumps.iloc[:0]
    ug = u.set_index("event_id")
    tasks = []
    for ev, g in sm.groupby("event_id"):
        r = ug.loc[ev]
        ml_row = {"cond": r.cond, "start": r.start, "end": r.end}
        tasks.append((ml_row, g[["cond", "res_s0", "delay"]].to_dict("records"), jg.get(r.cond, empty)))
    print(len(tasks), "events with side tapes", flush=True)
    prs, ivs = [], []
    with ProcessPoolExecutor(WORKERS) as ex:
        for i, (pr, iv) in enumerate(ex.map(process, tasks, chunksize=16)):
            if pr is not None:
                prs.append(pr)
            if iv is not None:
                ivs.append(iv)
            if i % 1000 == 0:
                print(i, flush=True)
    pr = pd.concat(prs, ignore_index=True)
    iv = pd.concat(ivs, ignore_index=True)
    meta = sm.set_index("cond")[["smt", "line", "align0", "fee_rate", "delay", "res_s0", "event_id", "start"]]
    pr = pr.join(meta, on="cond")
    iv = iv.join(meta, on="cond")
    assert (pr.start < OOS_CUT).all()
    pr.to_parquet(CACHE / "side_prints.parquet")
    iv.to_parquet(CACHE / "intervals.parquet")
    print(len(pr), "side prints;", len(iv), "intervals")


if __name__ == "__main__":
    main()
