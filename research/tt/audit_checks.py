"""Audit checks on the table tennis study (provenance, fees/delays, voids, counts, liquidity claims).

    python research/tt/audit_checks.py    # -> results/tt/audit_checks.json (logged in results/tt/peeks.log)

Does NOT import scripts/tt_analyze.py. Reproductions and post-hoc diagnostics only; no rule, parameter or
verdict changes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
OUT = ROOT / "results/tt/audit_checks.json"
BINS = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.93, 0.95, 0.97, 0.98, 0.99, 1.0]


def git(*a) -> str:
    return subprocess.run(["git", *a], capture_output=True, text=True, cwd=ROOT).stdout.strip()


def commit_ts(h: str) -> float:
    return float(git("show", "-s", "--format=%ct", h))


def tape(cond: str) -> pd.DataFrame | None:
    f = ROOT / "data/raw/trades" / f"{cond}.parquet"
    if not f.exists():
        return None
    t = pd.read_parquet(f)
    if t.empty:
        return None
    t["p0"] = np.where(t.outcomeIndex == 0, t.price, 1 - t.price)
    t["usd"] = t["size"] * t["price"]
    return t


def main():
    U = pd.read_parquet("data/tt/universe.parquet")
    Uu = pd.read_parquet("data/tt/universe_unlisted.parquet")
    st = pd.read_parquet("data/tt/build_status.parquet")
    out = {}

    # 1. provenance: pre-registration commit vs first table tennis tape / dataset file; run vs decisions commit
    births = [os.stat(f"data/raw/trades/{c}.parquet").st_birthtime for c in list(U.cond) + list(Uu.cond)]
    dfiles = {p.name: os.stat(p).st_birthtime for p in (ROOT / "data/tt").iterdir()}
    run_line = [x for x in (ROOT / "results/tt/peeks.log").read_text().splitlines() if "TT1-TT4 evaluated" in x][0]
    run_utc = pd.Timestamp(run_line.split()[0]).timestamp()
    out["provenance"] = {
        "prereg_commit_0f01362_utc": dt.datetime.fromtimestamp(commit_ts("0f01362"), dt.timezone.utc).isoformat(),
        "first_tt_tape_created_utc": dt.datetime.fromtimestamp(min(births), dt.timezone.utc).isoformat(),
        "first_data_tt_file_created_utc": dt.datetime.fromtimestamp(min(dfiles.values()), dt.timezone.utc).isoformat(),
        "tapes_created_before_prereg": int(sum(b < commit_ts("0f01362") for b in births)),
        "decisions_commit_eb0e692_utc": dt.datetime.fromtimestamp(commit_ts("eb0e692"), dt.timezone.utc).isoformat(),
        "tt1_tt4_run_logged_utc": run_line.split()[0],
        "seconds_from_decisions_commit_to_run": run_utc - commit_ts("eb0e692"),
        "tt1_tt4_run_lines_in_peeks_log": sum("TT1-TT4 evaluated" in x for x in (ROOT / "results/tt/peeks.log").read_text().splitlines()),
        "tt_analyze_changed_after_eb0e692": bool(git("diff", "--stat", "eb0e692", "HEAD", "--", "scripts/tt_analyze.py")),
        "src_v2_changes_after_845666f": git("log", "--format=%h %s", "845666f..HEAD", "--", "src/v2.py").splitlines(),
        "sizing_engine_changes_after_962371f": git("log", "--format=%h", "962371f..HEAD", "--", "research/v2/sizing/engine.py").splitlines(),
    }

    # 2. fees and delays per market vs the fresh gamma walk
    g = pd.read_parquet("data/tt/gamma_markets.parquet")
    m = U[["cond", "league", "fee_rate", "delay", "start", "res0"]].merge(
        g[["cond", "fee_rate", "fees_enabled", "seconds_delay", "uma_status", "fee_exp"]].rename(columns={"fee_rate": "g_rate"}),
        on="cond", how="left")
    out["fees_delays"] = {
        "markets": int(len(m)), "missing_in_gamma_walk": int(m.fees_enabled.isna().sum()),
        "rate_mismatch": int((m.fee_rate != m.g_rate.fillna(0)).sum()),
        "fees_disabled_but_rate_used": int(((m.fees_enabled == False) & (m.fee_rate > 0)).sum()),  # noqa: E712
        "delay_mismatch": int((m.delay != m.seconds_delay.fillna(1)).sum()),
        "fee_exponent_values": sorted(m.fee_exp.dropna().unique().tolist()),
        "by_league_rate": {f"{a}/{b}": int(n) for (a, b), n in m.groupby(["league", "fee_rate"]).size().items()},
        "uma_status": m.uma_status.value_counts().to_dict(),
    }

    # 3. voids
    ev = set(pd.read_parquet("data/tt/prints.parquet").cond)
    out["voids"] = {"utt_res0_half": int((U.res0 == 0.5).sum()),
                    "res0_half_evaluable": int(U[(U.res0 == 0.5) & U.cond.isin(ev)].shape[0]),
                    "unlisted_res0_half": int((Uu.res0 == 0.5).sum())}

    # 4. counts behind "27 matches (0.75%) reach the 20 in-play prints"
    ge20 = st.status.isin(["ok", "no_jump"])
    out["ge20_inplay"] = {"ge20_inplay_prints": int(ge20.sum()), "share": float(ge20.mean()),
                          "evaluable_ok": int((st.status == "ok").sum()), "dropped_no_jump": int((st.status == "no_jump").sum()),
                          "no_jump_by_league": st[st.status == "no_jump"].league.value_counts().to_dict()}

    # 5. post-hoc: TT1 in-play bins if the 12 no-jump matches (all IS) were kept (first print per match-minute)
    rows = []
    for r in U[U.cond.isin(st[ge20].cond) & U.res0.isin([0.0, 1.0])].itertuples():
        t = tape(r.cond)
        t = t[(t.timestamp >= int(r.start.timestamp())) & (t.timestamp <= int(r.end.timestamp()))]
        rows.append(pd.DataFrame({"cond": r.cond, "ts": t.timestamp.to_numpy(), "p": t.p0.to_numpy(), "res": r.res0}))
    D = pd.concat(rows)
    s = D.assign(minute=D.ts // 60).groupby(["cond", "minute"]).first().reset_index()
    s["fav"] = np.maximum(s.p, 1 - s.p)
    s["bin"] = pd.cut(s.fav, BINS, right=False).astype(str)
    nm = s.groupby("bin").cond.nunique()
    out["tt1_inplay_with_no_jump_matches_posthoc"] = {
        "matches": int(s.cond.nunique()), "obs": int(len(s)),
        "max_matches_in_a_judgeable_bin": int(nm.drop("[0.99, 1.0)", errors="ignore").max()),
        "bins_reaching_30": [b for b, n in nm.items() if n >= 30 and b != "[0.99, 1.0)"]}

    # 6. the 96 zero-listed markets that traded (excluded by the volume > 0 rule)
    ml = pd.read_parquet("data/tt/market_liquidity.parquet")
    mlu = pd.read_parquet("data/tt/market_liquidity_unlisted.parquet")
    out["unlisted"] = {"markets": int(len(mlu)), "tape_usd": float(mlu.usd.sum()), "utt_tape_usd": float(ml.usd.sum()),
                       "share_of_utt_tape_usd": float(mlu.usd.sum() / ml.usd.sum()),
                       "wtt_tape_usd_utt": float(ml[ml.league == "WTT"].usd.sum()),
                       "wtt_tape_usd_unlisted": float(mlu[mlu.league == "WTT"].usd.sum()),
                       "inplay_usd_unlisted": float(mlu.inplay_usd.sum())}

    # 7. capacity context: whole-sport in-play-window taker USD per calendar day (upper bound on any taker's flow)
    days = (U.start.max().normalize() - U.start.min().normalize()).days + 1
    oos = ml[ml.oos]
    oos_days = (U[U.oos].start.max().normalize() - U[U.oos].start.min().normalize()).days + 1
    out["capacity_context"] = {
        "calendar_days": int(days), "inplay_window_usd_all": float(ml.inplay_usd.sum()),
        "inplay_window_usd_per_day_all": float(ml.inplay_usd.sum() / days),
        "inplay_window_usd_per_day_incl_unlisted": float((ml.inplay_usd.sum() + mlu.inplay_usd.sum()) / days),
        "oos_calendar_days": int(oos_days), "oos_inplay_window_usd_per_day": float(oos.inplay_usd.sum() / oos_days),
        "inplay_usd_in_27_evaluable_matches": float(ml[ml.cond.isin(ev)].inplay_usd.sum()),
        "share_of_inplay_usd_in_evaluable_matches": float(ml[ml.cond.isin(ev)].inplay_usd.sum() / ml.inplay_usd.sum()),
    }

    # 8. reproduction: TT1 closing bins (last fill in [start - 24 h, start); res in {0, 1})
    rows = []
    for r in U[U.res0.isin([0.0, 1.0])].itertuples():
        t = tape(r.cond)
        if t is None:
            continue
        s0 = int(r.start.timestamp())
        w = t[(t.timestamp >= s0 - 86_400) & (t.timestamp < s0)]
        if len(w):
            p = float(w.p0.iloc[-1])
            rows.append({"cond": r.cond, "fav": max(p, 1 - p), "won": r.res0 if p >= 0.5 else 1 - r.res0})
    C = pd.DataFrame(rows)
    C["bin"] = pd.cut(C.fav, BINS, right=False).astype(str)
    out["tt1_closing_reproduction"] = {
        "matches": int(len(C)),
        "bins": {b: {"n": int(len(x)), "mean_price": round(float(x.fav.mean()), 3), "won": round(float(x.won.mean()), 3)}
                 for b, x in C.groupby("bin")}}

    out["run_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out["commit"] = git("rev-parse", "HEAD")
    OUT.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
