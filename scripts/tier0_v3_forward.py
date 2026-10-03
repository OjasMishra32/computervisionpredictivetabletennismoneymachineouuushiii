"""Tier-0 v3 FORWARD test (secondary test (c) of research/v2/tier0_v3/PREREG.md). Run ONCE; refuses a second run.

    COUNTERFACTUAL WITH ASSUMED DATA. Assumed: licensed live feed + courtside camera, NOT purchased;
    parameters from our measurements. No live ATP/WTA point feed was bought or used. The forward window's
    prices, results, fees and venue delays are real public Polymarket tapes; the tier-0 trader's timing, fills
    and call accuracy are modelled (src/tier0.py CORRECTED model + the frozen v3 rule).

    python scripts/tier0_v3_forward.py            # THE pre-registered run: once, logged, refuses a second run
    python scripts/tier0_v3_forward.py --dry --start 2026-08-10T00:00 --end 2026-08-13T00:00
                                                   # plumbing check on an IN-SAMPLE window: not logged,
                                                   # written to results/tier0_v3/forward_dry/

Window (HYPOTHESIS_V2.md with A1, via scripts/forward_test.window_universe): ATP/WTA singles moneylines,
volume >= $5k, start >= 2026-10-03 14:00 UTC, resolved at run time. Tier-0 regime: 1 s-delay matches only.
Coverage: per UTC start date, the 10 window matches with the highest pre-start volume (T.coverage_set).
Depth scaled by min(1, match volume / live-day volume) exactly as tier-0. Jumps: src.tiers.jump_onsets on each
match's in-play prints (the historical >= 4c detector set, selected on realised moves; see PREREG).

Frozen v3: theta 0.90 | hold to resolution | leverage sizing | zone [0.05, 0.95] | limit stale + 2c, on the
revised tier-0 primary (T.CORRECTED). 20 seeds (4000-4019). Every number is a 20-seed mean +/- SD; per-share CIs
(match-clustered and day-clustered bootstrap, 1,000 draws) are averaged over seeds.

Guards (the real run): refuses if results/forward_peeks.log already holds a tier-0 v3 forward START line, if
the output exists, before EARLIEST_RUN, or if any pinned code/input hash differs from PREREG.md (unless
--ack-deviation names a DEVIATIONS.md entry, which is logged). The START line is written before any
forward-window tape is read, so a crash after it still counts as the one run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from src import polymarket as pm, tiers  # noqa: E402
from src import tier0 as T  # noqa: E402
import tier0_v3_optimise as O  # noqa: E402
from forward_test import window_universe  # noqa: E402  (the HYPOTHESIS_V2 window definition, unchanged)

LABEL = ("COUNTERFACTUAL WITH ASSUMED DATA - assumed: licensed live feed + courtside camera, not purchased; "
         "parameters from our measurements. No live ATP/WTA point feed was used. Tier-0 v3 forward test "
         "(secondary), research/v2/tier0_v3/PREREG.md.")
FWD_START = "2026-10-03T14:00"                       # HYPOTHESIS_V2.md A1
BLIND_START = pd.Timestamp("2026-10-03 22:00", tz="UTC")   # sub-window starting after v3 was pre-registered
EARLIEST_RUN = pd.Timestamp("2026-10-04 11:30", tz="UTC")  # planned with the v2 forward run (HYPOTHESIS_V2)
LOG = ROOT / "results/forward_peeks.log"
RUN_TAG = "tier0 v3 forward test (scripts/tier0_v3_forward.py)"
OUT = ROOT / "results/tier0_v3/forward"
OUT_DRY = ROOT / "results/tier0_v3/forward_dry"
SEED_BASE, N_SEEDS = 4000, 20
N_BOOT = 1000
WORKERS = 3                                          # <= 3 local processes / fetch threads
REGIME1_START = pd.Timestamp("2026-05-15", tz="UTC")
MIN_MATCHES = 30                                     # fewer covered matches with trades -> "underpowered"
MIN_DAYS_DAY_CI = 10                                 # fewer trade days -> day-clustered CI reported as n/a

FROZEN = O.V3(theta=0.90, exit_d=None, sizing="lev", zone=(0.05, 0.95), limit=0.02)
CONFIGS = {
    "frozen_v3": FROZEN,
    "frozen_v3 + limit also enforced in the historical-price frame (DEVIATIONS D2 stress)": replace(FROZEN, hist_limit=True),
    "v2_headline (reference only: sweeps to the realised new mid, not ex-ante)": O.V2_HEADLINE,
}
BASE = T.CORRECTED

# SHA-256 of the frozen code and inputs, as recorded in research/v2/tier0_v3/PREREG.md
PINNED = {
    "src/tier0.py": "7aec73c8055368a53ceb1b040b612ce02bfb69414ae72e5a3e40dfa41371b16f",
    "scripts/tier0_v3_optimise.py": "ee867e6f8562ea82eefdd10ec66bfb6537be0ef5aa2b586f557972b9ab60b6af",
    "scripts/forward_test.py": "68e5271ddd8eda2b9fb12896331611ad2cd5ce1e3383fcacdf3e4b69d3e47083",
    "src/tiers.py": "46a79d75409fd416fdfc2e026c25f02d9ebb3a188a9de1a6ac353561f656363e",
    "src/tape.py": "4627f5a8d13ec8d0f51acb0f77ecc0a0651d95cfe18eb10f7af0c8f1a9a3cb77",
    "src/polymarket.py": "f42bb0d84b4d69aa3c16949d5a1093c6a32f5616b14d939fe9201a92e2a09ab3",
    "results/tier0/inputs/live_edge_curve.csv": "32e758a1a6a021694861dac7047b2f2d8bdce5124ec142b5850825a32a3ce782",
    "results/tier0/inputs/live_match_volumes.csv": "3a1d3f49cf056c333945669eb4dda564ff2f222c742599f370d7d6a7168d2b62",
    "results/tier0/inputs/point_mix.json": "b646fa9ffe419a0491307d1bbaf2677f94e91496551cb15caacc503b55e2bc02",
    "results/tier0_v3/is/inputs/leverage_table.csv": "d9dc68f96951c2c6a85e2f0039895a0092df3d77d997f988829639461476c647",
    "results/tier0_v3/is/inputs/live_limit_curve.csv": "be88a988b1b9b133ef00a0951a87661e67f2f2a75ec283acb4eaaa26609fb93d",
    "results/tier0_v3/is/inputs/bundle/pool_D3c.parquet": "03ca284787cc83cd61fcf42ba490e2d469400665167d12837025e2b9c2a36be8",
    "results/tier0_v3/is/inputs/bundle/pool_all.parquet": "cc4094bcd6195d6b8ef64849490cef3721b83933b29aed192ebe87d543e2429e",
    "results/tier0_v3/is/inputs/bundle/limit_curve.parquet": "d37f501e5a9b8cca7337b816de1498b5686b637160e2c5d1941153c630700a2f",
    "results/tier0_v3/is/inputs/bundle/lev.parquet": "c4e95b3fb8990bb8669239488e8c08c731aacc3dc21746098bb3660da4c5760c",
    "results/tier0_v3/is/inputs/bundle/meta.json": "ef2f68a84db07bc0ff2b7741da17ebcc7edbae81f27f26ed776b79828715fcf9",
}


def say(msg: str) -> None:
    print(f"[{pd.Timestamp.now(tz='UTC').strftime('%H:%M:%S')}Z] {msg}", flush=True)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def git_head() -> str:
    try:
        h = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        d = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
        return h + ("+dirty" if d else "")
    except Exception:
        return "unknown"


# ============================================================================================ guards
def already_run() -> list[str]:
    if not LOG.exists():
        return []
    return [ln.rstrip() for ln in LOG.read_text().splitlines() if RUN_TAG in ln and " START " in ln]


def check_hashes() -> dict:
    bad = {}
    for rel, want in PINNED.items():
        p = ROOT / rel
        got = sha256(p) if p.exists() else "missing"
        if got != want:
            bad[rel] = {"pinned": want, "now": got}
    return bad


def check_frozen() -> None:
    wf = json.loads((ROOT / "results/tier0_v3/is/walkforward.json").read_text())
    assert wf["frozen_v3"] == FROZEN.name() == "th0.9|hold|lev|z0.05-0.95|X2c", (wf["frozen_v3"], FROZEN.name())
    assert BASE == T.CORRECTED and BASE.stamp_lag == 2.0 and BASE.r_mode == "tournament" and BASE.phi == 0.5 \
        and BASE.coverage == 10 and BASE.p_event == 0.95 and BASE.net_cap == 100.0 and BASE.trade_cap == 1000.0 \
        and BASE.price == "live" and BASE.wrong_price == "live" and BASE.order == "limit" and BASE.cv == "own120" \
        and BASE.r_shift == 0.0 and BASE.queue_s == 0.0 and BASE.regime == "delay1"


# ============================================================================================== data
def refresh_tapes(w: pd.DataFrame, dry: bool) -> dict:
    """A cached tape written before its match ended is incomplete: move it aside (data/raw/trades_stale/, nothing
    is deleted) and refetch. Tapes written >= 10 min after the match end are used as they are (pm.fetch_trades
    caches). A dry run only counts them."""
    stale_dir = pm.RAW / "trades_stale"
    moved = 0
    for r in w.itertuples():
        f = pm.RAW / "trades" / f"{r.cond}.parquet"
        if f.exists() and pd.notna(r.end):
            mt = pd.Timestamp(f.stat().st_mtime, unit="s", tz="UTC")
            if mt < r.end + pd.Timedelta(minutes=10):
                moved += 1
                if not dry:
                    stale_dir.mkdir(parents=True, exist_ok=True)
                    f.rename(stale_dir / f"{r.cond}.{int(f.stat().st_mtime)}.parquet")
    pm.fetch_many_trades(w.cond.tolist(), workers=WORKERS)
    have = sum((pm.RAW / "trades" / f"{c}.parquet").exists() for c in w.cond)
    return {"stale_tapes_refetched": moved, "tapes_present": int(have), "matches": int(len(w))}


def _prints(r):
    try:
        return tiers.match_prints(SimpleNamespace(**r))
    except Exception:
        return None


def build_prints(w: pd.DataFrame) -> pd.DataFrame:
    rows = w[["cond", "start", "end", "res0", "fee_rate", "delay"]].to_dict("records")
    with ProcessPoolExecutor(WORKERS) as ex:
        parts = [d for d in ex.map(_prints, rows, chunksize=4) if d is not None]
    if not parts:
        return pd.DataFrame(columns=["cond", "ts", "p", "usd"])
    P = pd.concat(parts, ignore_index=True)
    P["cond"] = P.cond.astype(str)
    return P


def prestart_usd(w: pd.DataFrame) -> pd.Series:
    """T.prestart_volume's rule (ex-ante match size): $ traded before the scheduled start, from the raw tape."""
    out = {}
    for r in w.itertuples():
        f = pm.RAW / "trades" / f"{r.cond}.parquet"
        v = 0.0
        if f.exists():
            t = pd.read_parquet(f, columns=["timestamp", "size", "price"])
            pre = t[t.timestamp < int(r.start.timestamp())]
            v = float((pre["size"] * pre["price"]).sum())
        out[r.cond] = v
    return pd.Series(out, name="prestart_usd")


def post30(pr: pd.DataFrame, J: pd.DataFrame) -> np.ndarray:
    """T.post_prices' rule: VWAP of outcome-0 prints in [detect, detect + 30 s); pricing only."""
    groups = {c: g for c, g in pr.groupby("cond", sort=False)}
    out = np.full(len(J), np.nan)
    for c, g in J.groupby("cond", sort=False):
        P = groups.get(c)
        if P is None:
            continue
        ts, p, usd = P.ts.to_numpy(), P.p.to_numpy(), P.usd.to_numpy()
        pv = np.concatenate([[0.0], np.cumsum(p * usd)])
        vv = np.concatenate([[0.0], np.cumsum(usd)])
        det = g.detect_ts.to_numpy(float)
        a = np.searchsorted(ts, det, "left")
        b = np.searchsorted(ts, det + T.POST_W, "left")
        wt = vv[b] - vv[a]
        out[g.index.to_numpy()] = np.where(wt > 0, (pv[b] - pv[a]) / np.where(wt > 0, wt, 1), np.nan)
    return out


def jump_table(P: pd.DataFrame, w: pd.DataFrame) -> pd.DataFrame:
    """The tier-0 jump table (T.oos_jumps + T.jump_table + T.post_prices rules) for the window's matches."""
    pr = P[["cond", "ts", "p", "usd"]].sort_values(["cond", "ts"], kind="stable")
    rows = []
    for c, g in pr.groupby("cond", sort=False):
        for o in tiers.jump_onsets(g.ts.to_numpy(float), g.p.to_numpy(), g.usd.to_numpy()):
            rows.append({"cond": c, "onset_ts": o[0], "dir": o[1], "size": o[2], "detect_ts": o[3]})
    cols = ["cond", "onset_ts", "dir", "size", "detect_ts"]
    J = pd.DataFrame(rows, columns=cols)
    if J.empty:
        return J
    J = T._refs(pr, J)
    keep = ["cond", "slug", "title", "series", "league", "start", "end", "res0", "volume", "fee_rate", "delay"]
    J = J.merge(w[keep], on="cond", how="left", validate="many_to_one")
    assert J.start.notna().all()
    J["region"] = [T.region_of(a, b) for a, b in zip(J.league, J.title)]
    J["men"] = J.series.isin(["atp", "challenger"])
    J["post30"] = post30(pr, J)
    return J


# ======================================================================================= simulation
def install_context(J: pd.DataFrame, M: pd.DataFrame, n_tour: int) -> dict:
    """Point the frozen v3 simulator (O.simulate_v3, unchanged) at the window: shared measured inputs come from
    the IS bundle (live pools + limit curve, CV tables, point mix, stamp-lag calibration, leverage table)."""
    c = O.context()
    shared = {k: c[k] for k in ("pools", "cvs", "mix", "calib", "lev")}
    cov = T.coverage_set(M, BASE.coverage, BASE.regime)
    Jc = J[J.cond.isin(cov)].reset_index(drop=True)
    E = pd.DataFrame({"t_rep": np.full(len(Jc), np.nan), "rep_found": np.zeros(len(Jc), bool)})   # hold only
    days = T.period_days(J, BASE.regime)
    O._C.clear()
    O._C.update(shared, J=J, Jc=Jc, M=M, E=E, days=days, n_rows=len(J), n_tour=max(int(n_tour), 1))
    return O._C


def boot_ci(tr: pd.DataFrame, key: str, seed: int = 0) -> tuple[float, float, int]:
    g = tr.groupby(key).agg(p=("pnl", "sum"), s=("shares", "sum"))
    k = len(g)
    if k < 2:
        return float("nan"), float("nan"), k
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, (N_BOOT, k))
    P, S = g.p.to_numpy(), g.s.to_numpy()
    ps = P[idx].sum(1) / S[idx].sum(1) * 100
    return float(np.percentile(ps, 2.5)), float(np.percentile(ps, 97.5)), k


def metrics_test(calls: pd.DataFrame, days: pd.DatetimeIndex, J: pd.DataFrame) -> tuple[dict, np.ndarray]:
    """O.metrics_v3 (match-clustered CI, Sharpe, Sortino, drawdown, profitable days, capital) + the day-clustered
    and tournament-clustered CIs and the period's own months."""
    m, dv = O.metrics_v3(calls, days)
    for k in [k for k in m if k.startswith("pnl_2026-")] + ["months_positive", "months_total"]:
        m.pop(k, None)
    tr = calls[calls.shares > 1e-9] if len(calls) else calls
    mo = np.array(days.strftime("%Y-%m"))
    monthly = {x: float(dv[mo == x].sum()) for x in sorted(set(mo))}
    m.update({f"pnl_{k}": v for k, v in monthly.items()})
    m["months_positive"] = int(sum(v > 0 for v in monthly.values()))
    m["months_total"] = len(monthly)
    if len(tr):
        lo, hi, nd = boot_ci(tr, "date")
        m["per_share_day_ci95_c_lo"], m["per_share_day_ci95_c_hi"], m["n_trade_days"] = lo, hi, nd
        trt = tr.assign(tour=J.tour.to_numpy()[tr.row.to_numpy()])
        lo, hi, nt = boot_ci(trt, "tour")
        m["per_share_tour_ci95_c_lo"], m["per_share_tour_ci95_c_hi"], m["n_tournaments"] = lo, hi, nt
    return m, dv


def summarise(ms: list[dict], dvs: list[np.ndarray]) -> dict:
    F = pd.DataFrame(ms).replace([np.inf, -np.inf], np.nan)
    out = {"n_seeds": len(ms)}
    for c in F.columns:
        if pd.api.types.is_numeric_dtype(F[c]):
            out[c] = round(float(F[c].mean()), 4) if F[c].notna().any() else None
            out[f"{c}_sd"] = round(float(F[c].std(ddof=0)), 4) if F[c].notna().any() else None
    dv = np.vstack(dvs) if dvs else np.zeros((1, 1))
    out["sortino_pooled_ann"] = O.pooled_sortino(dv) if dv.size else None
    return out


def labels(s: dict) -> dict:
    """Pre-registered reading of a summary (forward = secondary: reported, not tested)."""
    ps = s.get("per_share_c")
    nd = s.get("n_trade_days") or 0
    out = {"per_share_net_positive": bool(ps is not None and ps > 0),
           "match_ci_excludes_0": bool((s.get("per_share_ci95_c_lo") or -1) > 0),
           "day_ci_excludes_0": (bool((s.get("per_share_day_ci95_c_lo") or -1) > 0) if nd >= MIN_DAYS_DAY_CI
                                 else f"n/a ({nd:.0f} trade days < {MIN_DAYS_DAY_CI})"),
           "profitable_days_share_active_pct": s.get("profitable_days_pct_active"),
           "majority_of_days_profitable": bool((s.get("profitable_days_pct_active") or 0) > 50),
           "underpowered": bool((s.get("n_matches") or 0) < MIN_MATCHES)}
    return out


def run_set(J: pd.DataFrame, subsets: dict) -> tuple[dict, dict, pd.DataFrame]:
    c = O._C
    calib = c["calib"]["central"]["stamp_lag_s"]
    scen = {"primary (lag 2.0 | tournament | trunc 0 | queue 0)": BASE}
    brk = O.bracket_scenarios(calib)
    res, keep, daily = {}, [], {}
    start_of_row = J.start.reset_index(drop=True)
    t0 = time.time()
    jobs = [(cn, v, sn, sc) for cn, v in CONFIGS.items() for sn, sc in scen.items()] + \
           [("frozen_v3", FROZEN, f"bracket {bn}", sc) for bn, sc in brk.items()]
    for k, (cn, v, sn, sc) in enumerate(jobs):
        per_sub = {sub: ([], []) for sub in subsets}
        for s in range(N_SEEDS):
            dr = T.draws(c["n_rows"], SEED_BASE + s, c["n_tour"])
            calls = O.simulate_v3(sc, v, dr)
            calls["start"] = start_of_row.iloc[calls.row.to_numpy()].to_numpy() if len(calls) else []
            for sub, (lo_start, days) in subsets.items():
                cl = calls[pd.to_datetime(calls.start, utc=True) >= lo_start] if len(calls) else calls
                m, dv = metrics_test(cl, days, J)
                per_sub[sub][0].append(m)
                per_sub[sub][1].append(dv)
            if cn == "frozen_v3" and sn.startswith("primary"):
                keep.append(calls.assign(seed=SEED_BASE + s))
        for sub, (ms, dvs) in per_sub.items():
            res.setdefault(cn, {}).setdefault(sn, {})[sub] = summarise(ms, dvs)
            if cn == "frozen_v3" and sn.startswith("primary"):
                daily[sub] = np.vstack(dvs)
        if (k + 1) % 10 == 0 or k + 1 == len(jobs):
            say(f"simulated {k + 1}/{len(jobs)} configs x {N_SEEDS} seeds ({time.time() - t0:.0f}s)")
    tr = pd.concat(keep, ignore_index=True) if keep else pd.DataFrame()
    return res, daily, tr


def bracket_summary(res: dict, sub: str) -> dict:
    rows = []
    for sn, d in res["frozen_v3"].items():
        if not sn.startswith("bracket "):
            continue
        s = d[sub]
        bn = sn[len("bracket "):]
        lag, rd, tr_, qu = bn.split("|")
        rows.append({"scenario": bn, "stamp_lag": lag[3:], "reading": rd, "trunc": tr_[5:], "queue": qu[5:],
                     "pnl_per_day_usd": s.get("pnl_per_day_usd") or 0.0, "pnl_usd": s.get("pnl_usd") or 0.0,
                     "per_share_c": s.get("per_share_c"), "ci_lo": s.get("per_share_ci95_c_lo"),
                     "ci_hi": s.get("per_share_ci95_c_hi")})
    B = pd.DataFrame(rows)
    if B.empty:
        return {}
    return {"n_scenarios": int(len(B)),
            "pnl_per_day": {"min": float(B.pnl_per_day_usd.min()), "median": float(B.pnl_per_day_usd.median()),
                            "max": float(B.pnl_per_day_usd.max())},
            "share_scenarios_positive": float((B.pnl_usd > 0).mean()),
            "share_scenarios_match_ci_excludes_0": float((B.ci_lo.fillna(-1) > 0).mean()),
            "by_stamp_lag_median_pnl_per_day": B.groupby("stamp_lag").pnl_per_day_usd.median().round(2).to_dict(),
            "by_reading_median_pnl_per_day": B.groupby("reading").pnl_per_day_usd.median().round(2).to_dict(),
            "verifier_stresses_at_lag2_tournament": {
                r.scenario: {"pnl_per_day_usd": round(r.pnl_per_day_usd, 2), "per_share_c": r.per_share_c,
                             "per_share_ci95_c": [r.ci_lo, r.ci_hi]}
                for r in B[(B.stamp_lag == "2") & (B.reading == "tournament")].itertuples()},
            "rows": B.round(4).to_dict("records")}


# ============================================================================================== main
def main(a) -> None:
    now = pd.Timestamp.now(tz="UTC")
    start = pd.Timestamp(a.start, tz="UTC")
    end = pd.Timestamp(a.end, tz="UTC") if a.end else now
    out_dir = OUT_DRY if a.dry else OUT
    check_frozen()
    bad = check_hashes()
    if a.dry:
        if end > T.OOS_START or start < REGIME1_START:
            raise SystemExit("--dry is a plumbing check on an IN-SAMPLE 1 s-regime window only "
                             f"([{REGIME1_START}, {T.OOS_START})); refusing (no data read).")
        if bad:
            say(f"WARNING (dry): pinned hashes differ: {bad}")
    else:
        prior = already_run()
        if prior:
            raise SystemExit("REFUSED: the tier-0 v3 forward test has already been run (results/forward_peeks.log):\n  "
                             + "\n  ".join(prior))
        if (out_dir / "results.json").exists():
            raise SystemExit(f"REFUSED: {out_dir / 'results.json'} exists; the forward test runs once.")
        if a.start != FWD_START:
            raise SystemExit(f"REFUSED: the pre-registered window starts at {FWD_START} (HYPOTHESIS_V2.md A1).")
        if now < EARLIEST_RUN:
            raise SystemExit(f"REFUSED: the pre-registered run is not before {EARLIEST_RUN} (now {now}); nothing read.")
        if bad and not a.ack_deviation:
            raise SystemExit("REFUSED: pinned code/input hashes differ from PREREG.md; log the change in "
                             "research/v2/tier0_v3/DEVIATIONS.md and pass --ack-deviation 'D<k>: ...':\n"
                             + json.dumps(bad, indent=1))
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(f"{now.isoformat()} {RUN_TAG} START window [{a.start}, {end.isoformat()}) "
                     f"commit={git_head()} hash_mismatch={sorted(bad) if bad else 'none'}"
                     f"{' ack=' + repr(a.ack_deviation) if a.ack_deviation else ''} (COUNTERFACTUAL; secondary test; "
                     f"PREREG research/v2/tier0_v3/PREREG.md)\n")
    t0 = time.time()
    say(f"{'DRY RUN (in-sample window)' if a.dry else 'FORWARD RUN'}: window [{start}, {end})")
    w = window_universe(start, end)
    say(f"window matches (ATP/WTA, >= $5k, resolved): {len(w)}; 1 s delay: {int((w.delay == 1).sum())}")
    info = {"window": [str(start), str(end)], "matches_in_window": int(len(w)),
            "matches_1s_delay": int((w.delay == 1).sum())}
    if len(w):
        info.update(refresh_tapes(w, a.dry))
        say(f"tapes: {info['tapes_present']}/{len(w)} present, {info['stale_tapes_refetched']} refetched")
        w["prestart_usd"] = w.cond.map(prestart_usd(w)).fillna(0.0)
        P = build_prints(w)
    else:
        P = pd.DataFrame(columns=["cond", "ts", "p", "usd"])
    info["matches_with_inplay_prints"] = int(P.cond.nunique()) if len(P) else 0
    J = jump_table(P, w) if len(P) else pd.DataFrame()
    say(f"in-play prints: {len(P):,} rows, {info['matches_with_inplay_prints']} matches; jumps: {len(J)}")
    out = {"label": LABEL, "test": "tier-0 v3 forward test (secondary; reported, not tested)",
           "prereg": "research/v2/tier0_v3/PREREG.md", "dry_run": bool(a.dry), "run_utc": now.isoformat(),
           "commit": git_head(), "hash_mismatch": bad, "ack_deviation": a.ack_deviation,
           "frozen_v3": {"variant": FROZEN.name(), "rule": asdict(FROZEN)},
           "base_scenario": {k: v for k, v in asdict(BASE).items()}, "seeds": [SEED_BASE, SEED_BASE + N_SEEDS - 1],
           "blind_subwindow_start": str(BLIND_START), **info}
    out_dir.mkdir(parents=True, exist_ok=True)
    J1 = J[J.delay == 1] if len(J) else J
    if J1 is None or len(J1) == 0:
        out["result"] = "no 1 s-delay jumps in the window: no tier-0 calls"
        (out_dir / "results.json").write_text(json.dumps(out, indent=1, default=str))
        say(out["result"])
        return
    J = J.reset_index(drop=True)
    J["row"] = np.arange(len(J))
    tour = T.tournament_codes(w)
    J["tour"] = J.cond.map(tour).astype(int)
    M = w[["cond", "start", "delay", "prestart_usd"]].reset_index(drop=True)
    c = install_context(J, M, int(tour.max()) + 1)
    out["covered_matches"] = int(len(T.coverage_set(M, BASE.coverage, BASE.regime)))
    out["covered_matches_with_jumps"] = int(c["Jc"].cond.nunique())
    out["covered_jumps"] = int(len(c["Jc"]))
    out["days"] = [str(c["days"][0].date()), str(c["days"][-1].date()), int(len(c["days"]))]
    out["region_unmapped_share_of_covered_jumps"] = float((c["Jc"].region == "unmapped").mean())
    say(f"covered: {out['covered_matches']} matches ({out['covered_matches_with_jumps']} with jumps), "
        f"{out['covered_jumps']} jumps, days {out['days']}")
    if len(c["Jc"]) == 0:
        out["result"] = "no covered 1 s-delay jumps in the window: no tier-0 calls"
        (out_dir / "results.json").write_text(json.dumps(out, indent=1, default=str))
        say(out["result"])
        return
    Jb = J[(J.start >= BLIND_START) & (J.delay == 1)]
    subsets = {"full_window": (start, c["days"])}
    if len(Jb):
        subsets[f"blind_subwindow (start >= {BLIND_START})"] = (BLIND_START, T.period_days(Jb, BASE.regime))
    res, daily, tr = run_set(J, subsets)
    out["results"] = res
    out["readings"] = {sub: labels(res["frozen_v3"][next(iter(res["frozen_v3"]))][sub]) for sub in subsets}
    out["bracket_frozen_v3"] = {sub: bracket_summary(res, sub) for sub in subsets}
    if len(tr):
        out["diagnostics_frozen_v3 (by realised jump size = DIAGNOSTIC ONLY)"] = O.diagnostics(tr, len(c["days"]))
        tr.assign(label=LABEL).to_parquet(out_dir / "trades_frozen_v3.parquet")
    for sub, dv in daily.items():
        dd = pd.DataFrame(dv.T, columns=[f"seed{SEED_BASE + s}" for s in range(N_SEEDS)])
        dd.insert(0, "label", LABEL)
        dd.to_csv(out_dir / f"daily_frozen_v3_{sub.split(' ')[0]}.csv", index=False)
    (out_dir / "results.json").write_text(json.dumps(out, indent=1, default=str))
    p = res["frozen_v3"][next(iter(res["frozen_v3"]))]
    for sub in subsets:
        s = p[sub]
        say(f"{sub}: frozen v3 {s.get('per_share_c')}c/share [match CI {s.get('per_share_ci95_c_lo')}, "
            f"{s.get('per_share_ci95_c_hi')}] [day CI {s.get('per_share_day_ci95_c_lo')}, "
            f"{s.get('per_share_day_ci95_c_hi')}], ${s.get('pnl_usd')} (${s.get('pnl_per_day_usd')}/day), "
            f"trades {s.get('n_trades')}, matches {s.get('n_matches')}, profitable days "
            f"{s.get('profitable_days_pct_active')}% -> {out['readings'][sub]}")
    if not a.dry:
        with LOG.open("a") as fh:
            s = p["full_window"]
            fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} {RUN_TAG} DONE "
                     f"per_share_c={s.get('per_share_c')} match_ci=[{s.get('per_share_ci95_c_lo')}, "
                     f"{s.get('per_share_ci95_c_hi')}] trades={s.get('n_trades')} -> {out_dir / 'results.json'}\n")
    say(f"done in {time.time() - t0:.0f}s -> {out_dir / 'results.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=FWD_START)
    ap.add_argument("--end", default=None, help="window end (default: now); dry runs only need it")
    ap.add_argument("--dry", action="store_true", help="plumbing check on an in-sample window; not logged")
    ap.add_argument("--ack-deviation", default=None, help="DEVIATIONS.md entry acknowledging a pinned-hash change")
    main(ap.parse_args())
