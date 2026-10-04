"""Fresh holdout: "a firm with a licensed 0.5 s feed" on matches played after the burned OOS.

    COUNTERFACTUAL WITH ASSUMED DATA. Real: Polymarket prices, fills (public trade tapes), match results, taker fees
    and the venue's 1 s order delay. Simulated: the camera/CV calls, made at an ASSUMED licensed-feed delay V
    (0.5 / 1 / 3 s). No feed or video was bought, received or watched; no order is placed anywhere.

Pre-registration: research/v2/tier0_v3/fresh/PREREG_FRESH.md (commit dc95717, 2026-10-04 05:34:34 UTC), written
and committed before any fresh-window tape, price or result was fetched.

    python scripts/fresh_holdout.py --history       # G1 code reproduction + IS / burned-OOS cells (already-read data)
    python scripts/fresh_holdout.py --equivalence   # G2: rebuild 2026-10-02 from freshly fetched raw data, compare
    python scripts/fresh_holdout.py --fetch         # fresh window: Gamma listing + Data API tapes -> data/fresh/
    python scripts/fresh_holdout.py --run           # frozen strategies on the fresh window -> results/fresh_holdout/
    python scripts/fresh_holdout.py --all           # the four steps in order (a rerun reuses data/fresh/ caches)
    add --refetch to --fetch / --all to list and download the window again (new fetch time T_f)

Strategies (both frozen, reported side by side):
  S1  frozen tier-0 v3 th0.9|hold|lev|z0.05-0.95|X2c  (O.simulate_v3 on T.CORRECTED, pinned IS-bundle inputs)
  S2  the paper's Table-2 CV trader = tier-0 revised primary (T.simulate on T.CORRECTED; latency-sweep model)
Feed delay V: t_inf -> t_inf + V exactly as scripts/tier0_latency_sweep.cell("video", ...). Readings: stamp lag 2.0 s
(pre-registered, `tournament`) and 3.142 s (post hoc, `tournament_lagcal`). Seeds 4000-4019 on the fresh window,
the backtest's own streams (IS 0-19, burned OOS 1000-1019) on the history.

Outputs: results/fresh_holdout/{results.json, daily.csv, showcase_ledger.csv, showcase_price_1s.csv,
equivalence_check.json, history.json}. Raw and derived data stay in data/fresh/ (gitignored). Public read-only
Polymarket endpoints only (Gamma, Data API), at most 4 concurrent requests, backing off on 429 (src.polymarket._get).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
import warnings
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)                      # src.polymarket caches under the relative path data/raw
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")

import tier0_latency_sweep as LS  # noqa: E402  (the sweep's feed-delay cell, unchanged)
import tier0_v3_forward as F  # noqa: E402      (pinned window builder: prints -> jumps -> post30 -> pre-start $)
import tier0_v3_optimise as O  # noqa: E402     (frozen v3 simulator)
from forward_test import window_universe  # noqa: E402  (HYPOTHESIS_V2 A1 window rule, unchanged)
from src import polymarket as pm, tiers  # noqa: E402
from src import tier0 as T  # noqa: E402
from src.tape import load_tape, universe  # noqa: E402

LABEL = ("COUNTERFACTUAL WITH ASSUMED DATA: real Polymarket prices, fills, match results, taker fees and venue "
         "delays; SIMULATED camera/CV calls at an assumed licensed-feed delay V (no feed purchased, no video "
         "watched, no orders placed). Trades are the historical >= 4c jump set, selected on outcomes, not ex ante.")
PREREG = "research/v2/tier0_v3/fresh/PREREG_FRESH.md"
PREREG_COMMIT = "dc95717"
PREREG_UTC = "2026-10-04T05:34:34Z"
OUT = ROOT / "results/fresh_holdout"
DATA = ROOT / "data/fresh"
FRESH_RAW = DATA / "raw"
DER = DATA / "derived"
LOG = ROOT / "results/oos_peeks.log"

WINDOW_START = pd.Timestamp("2026-10-03 07:10:00", tz="UTC")   # latest U1 (= burned-OOS) start; window is AFTER it
SUB14 = pd.Timestamp("2026-10-03 14:00:00", tz="UTC")          # the never-run forward window's start (sub-window)
END_MARGIN = pd.Timedelta(minutes=10)                           # a match must finish >= 10 min before T_f
EQUIV_DAY = (pd.Timestamp("2026-10-02", tz="UTC"), pd.Timestamp("2026-10-03", tz="UTC"))
EXCLUDE = ["wta-rybakin-charaev-2026-10-01", "wta-kartal-wa-2026-10-01", "wta-bouzkov-birrell-2026-10-01",
           "wta-zhen-kalinsk-2026-10-01", "wta-bencic-zakharo-2026-10-01", "wta-su-bucsa-2026-10-02",
           "wta-jovic-dart-2026-10-02", "wta-rakhimo-fernand-2026-10-01", "wta-andree-boisson-2026-10-03"]
GRAND_SLAM = re.compile(r"australian open|roland garros|french open|wimbledon|us open", re.I)

VS = (0.5, 1.0, 3.0)
READINGS = {"pre": "tournament", "cal": "tournament_lagcal"}
READING_LABEL = {"pre": "pre-registered stamp lag 2.0 s", "cal": "post hoc stamp lag 3.142 s (calibrated inference)"}
STRATS = {"S1": "frozen tier-0 v3 (th0.9|hold|lev|z0.05-0.95|X2c)",
          "S2": "paper Table-2 CV trader (tier-0 revised primary, T.CORRECTED; takes stale depth to the realised new mid)"}
COVERAGES = {"cov10": 10, "all": 10 ** 6}
COVERAGE_LABEL = {"cov10": "primary: top 10 per UTC day by pre-start volume (frozen)",
                  "all": "secondary: every eligible 1 s-delay window match"}
SEED_FRESH, N_SEEDS = 4000, 20
SEED_HIST = {"IS": 0, "burned_OOS": 1000}
SHOW_SEED = 4000
FROZEN = F.FROZEN
BASE = T.CORRECTED
MIN_MATCHES = 30
MIN_DAYS_SHARPE = 10
DAYS_PER_MONTH = 30.42
FETCH_WORKERS = 4


def say(msg: str) -> None:
    print(f"[{pd.Timestamp.now(tz='UTC').strftime('%H:%M:%S')}Z] {msg}", flush=True)


def peek(msg: str) -> None:
    with LOG.open("a") as fh:
        fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} {msg}\n")


def git_head() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True).stdout.strip()
    except Exception:
        return "unknown"


def jdump(obj) -> str:
    def conv(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (pd.Timestamp,)):
            return o.isoformat()
        if isinstance(o, np.ndarray):
            return o.tolist()
        return str(o)

    def clean(o):
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, float) and not np.isfinite(o):
            return None
        return o
    return json.dumps(clean(json.loads(json.dumps(obj, default=conv))), indent=1)


@contextlib.contextmanager
def fresh_raw():
    """Point src.polymarket's tape cache (read by fetch_trades, load_tape, prestart_usd) at data/fresh/raw, so the
    fresh path never reads the cached data/raw tapes."""
    old = pm.RAW
    pm.RAW = FRESH_RAW
    try:
        yield
    finally:
        pm.RAW = old


# ===================================================================================== simulation core
def vd(S: dict, lsc: dict, rd: str, V: float, cov: int) -> tuple[T.Scenario, dict]:
    """Scenario + CV tables for one (reading, V, coverage) cell: the latency sweep's own cell()."""
    sc, cvs = LS.cell("video", READINGS[rd], V, "own120", lsc)
    if cov != BASE.coverage:
        sc = replace(sc, coverage=cov)
    return sc, cvs


def sim_S2(ctx: dict, sc: T.Scenario, cvs: dict, seed: int) -> pd.DataFrame:
    dr = T.draws(ctx["n_rows"], seed, max(ctx["n_tour"], 1))
    return T.simulate(ctx["J"], ctx["M"], sc, dr, ctx["pools"], cvs, ctx["mix"])


def install_v3(ctx: dict, cov: int, cvs: dict) -> None:
    """O.simulate_v3 reads everything from O._C: shared measured inputs from the pinned IS bundle (live pools + limit
    curve, leverage table, point mix, calibration), this test set's jumps / universe / days, and the CV tables with
    the feed delay added (as tier0_v3_forward.install_context, plus the coverage and CV-table arguments)."""
    v3 = ctx["v3_shared"]
    cset = T.coverage_set(ctx["M"], cov, BASE.regime)
    Jc = ctx["J"][ctx["J"].cond.isin(cset)].reset_index(drop=True)
    if "E_by_row" in ctx:
        E = ctx["E_by_row"].loc[Jc.row.to_numpy()]
    else:
        E = pd.DataFrame({"t_rep": np.full(len(Jc), np.nan), "rep_found": np.zeros(len(Jc), bool)})
    O._C.clear()
    O._C.update({k: v3[k] for k in ("pools", "mix", "calib", "lev")}, cvs=cvs, J=ctx["J"], Jc=Jc, M=ctx["M"],
                E=E, days=ctx["days"], n_rows=ctx["n_rows"], n_tour=ctx["n_tour"])


def sim_S1(ctx: dict, sc: T.Scenario, seed: int) -> pd.DataFrame:
    dr = T.draws(ctx["n_rows"], seed, max(ctx["n_tour"], 1))
    calls = O.simulate_v3(sc, FROZEN, dr)
    if len(calls):
        calls["start"] = ctx["J"].set_index("row").start.reindex(calls.row.to_numpy()).to_numpy()
    return calls


def v3_shared() -> dict:
    O._C.clear()
    c = O.context()
    out = {k: c[k] for k in ("pools", "mix", "calib", "lev", "cvs")}
    out["is_ctx"] = {k: c[k] for k in ("J", "M", "E", "days", "n_rows", "n_tour")}
    O._C.clear()
    return out


def metr(calls: pd.DataFrame, days: pd.DatetimeIndex) -> tuple[dict, np.ndarray]:
    """O.metrics_v3 (per-share with the match-clustered bootstrap CI, rng seed 0, 1,000 draws; Sharpe; hit rate;
    drawdown; capital) plus the match-bootstrap CI of the total P&L (same draws) and the call-timing share."""
    nd = len(days)
    if calls is None or len(calls) == 0 or "shares" not in calls:
        return {"n_calls": 0, "n_trades": 0, "n_matches": 0, "pnl_usd": 0.0, "pnl_per_day_usd": 0.0}, np.zeros(nd)
    m, dv = O.metrics_v3(calls, days)
    for k in [k for k in m if k.startswith("pnl_2026-")] + ["months_positive", "months_total"]:
        m.pop(k, None)
    m.setdefault("n_matches", 0)
    tr = calls[calls.shares > 1e-9]
    if len(tr):
        g = tr.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
        rng = np.random.default_rng(0)
        idx = rng.integers(0, len(g), (1000, len(g)))
        tot = g.p.to_numpy()[idx].sum(1)
        m["pnl_ci95_usd_lo"], m["pnl_ci95_usd_hi"] = float(np.percentile(tot, 2.5)), float(np.percentile(tot, 97.5))
        m["pnl_per_day_ci95_usd_lo"], m["pnl_per_day_ci95_usd_hi"] = m["pnl_ci95_usd_lo"] / nd, m["pnl_ci95_usd_hi"] / nd
    m["calls_share_before_reprice"] = float((calls.tau >= 0).mean())
    return m, dv


def agg(ms: list[dict], dvs: list[np.ndarray], days: pd.DatetimeIndex) -> tuple[dict, pd.DataFrame]:
    Fm = pd.DataFrame(ms)
    for c in ("n_calls", "n_trades", "n_matches", "pnl_usd", "pnl_per_day_usd", "pnl_correct_usd", "pnl_wrong_usd"):
        if c in Fm:
            Fm[c] = Fm[c].fillna(0.0)
    Fm = Fm.replace([np.inf, -np.inf], np.nan)
    out = {"n_seeds": int(len(ms)), "n_seeds_with_trades": int((Fm.n_trades > 0).sum()), "days": int(len(days)),
           "first_day": str(days[0].date()) if len(days) else None, "last_day": str(days[-1].date()) if len(days) else None}
    for c in Fm.columns:
        if pd.api.types.is_numeric_dtype(Fm[c]) and Fm[c].notna().any():
            out[c] = round(float(Fm[c].mean()), 4)
            out[f"{c}_sd"] = round(float(Fm[c].std(ddof=0)), 4)
    for c in ("pnl_per_day_usd", "sharpe_ann", "per_share_c", "pnl_usd"):
        if c in Fm and Fm[c].notna().any():
            out[f"{c}_seed_p2_5"] = round(float(np.nanpercentile(Fm[c], 2.5)), 4)
            out[f"{c}_seed_p97_5"] = round(float(np.nanpercentile(Fm[c], 97.5)), 4)
    out["anecdotal (mean matches with trades < 30)"] = bool(out.get("n_matches", 0) < MIN_MATCHES)
    out["sharpe_note"] = (f"not meaningful ({len(days)} days < {MIN_DAYS_SHARPE})" if len(days) < MIN_DAYS_SHARPE
                          else "daily Sharpe, sqrt(365), zero-filled")
    D = np.vstack(dvs) if dvs else np.zeros((1, len(days)))
    daily = pd.DataFrame({"date": [str(d.date()) for d in days], "pnl_mean_usd": D.mean(0),
                          "pnl_p10_usd": np.percentile(D, 10, axis=0), "pnl_p90_usd": np.percentile(D, 90, axis=0),
                          "pnl_sd_usd": D.std(0), "n_seeds": D.shape[0]})
    return out, daily


def run_cells(ctx: dict, seeds: list[int], vs=VS, covs=("cov10",), strats=("S1", "S2"), subsets=None,
              keep: dict | None = None) -> tuple[dict, list[pd.DataFrame]]:
    """Every (strategy, reading, V, coverage) cell over `seeds`. subsets: {name: (min_start, days)} evaluated on the
    same calls (match start >= min_start). keep: {(strategy, reading, V, coverage, seed): None} -> calls returned."""
    lsc = {"cvs": ctx["cvs"], "pools": ctx["pools"], "calib": ctx["calib"]}
    subsets = subsets or {"all_days": (None, ctx["days"])}
    res, dailies = {}, []
    for s in strats:
        for rd in READINGS:
            for V in vs:
                for cv in covs:
                    sc, cvs = vd(s, lsc, rd, V, COVERAGES[cv])
                    if s == "S1":
                        install_v3(ctx, COVERAGES[cv], cvs)
                    per = {k: ([], []) for k in subsets}
                    for seed in seeds:
                        calls = sim_S1(ctx, sc, seed) if s == "S1" else sim_S2(ctx, sc, cvs, seed)
                        if keep is not None and (s, rd, V, cv, seed) in keep:
                            keep[(s, rd, V, cv, seed)] = calls
                        for sub, (lo, days) in subsets.items():
                            cl = calls
                            if lo is not None and len(calls):
                                cl = calls[pd.to_datetime(calls.start, utc=True) >= lo]
                            m, dv = metr(cl, days)
                            m["seed"] = seed
                            per[sub][0].append(m)
                            per[sub][1].append(dv)
                    for sub, (ms, dvs) in per.items():
                        a, daily = agg(ms, dvs, subsets[sub][1])
                        a["per_seed"] = [{k: m.get(k) for k in ("seed", "pnl_usd", "pnl_per_day_usd", "per_share_c",
                                                                 "n_trades", "n_matches", "sharpe_ann")} for m in ms]
                        res.setdefault(s, {}).setdefault(rd, {}).setdefault(str(V), {}).setdefault(cv, {})[sub] = a
                        dailies.append(daily.assign(strategy=s, reading=rd, V_s=V, coverage=cv, subset=sub))
    return res, dailies


# ================================================================================= history (G1 + cells)
def ctx_is_oos() -> dict:
    """IS and burned-OOS contexts, built exactly as the published runs built them: S2 from tier0_backtest.context
    (via the sweep's ctx), S1 on the same tables with the pinned IS bundle's shared inputs."""
    c = LS.ctx()
    sh = v3_shared()
    out = {}
    for p in ("IS", "burned_OOS"):
        P = c["per"][p]
        J = P["J"]
        out[p] = {"J": J, "M": P["M"], "days": T.period_days(J, BASE.regime), "n_rows": len(J), "n_tour": c["n_tour"],
                  "pools": c["pools"], "cvs": c["cvs"], "mix": c["mix"], "calib": c["calib"], "v3_shared": sh,
                  "seed0": P["seed"]}
    # IS: the bundle's own J / M / exit table (the published frozen-v3 IS runs used exactly these)
    ic = sh["is_ctx"]
    out["IS_v3"] = {**out["IS"], "J": ic["J"], "M": ic["M"], "days": ic["days"], "n_rows": ic["n_rows"],
                    "n_tour": ic["n_tour"], "E_by_row": ic["E"]}
    return out


def history() -> dict:
    peek("fresh holdout (scripts/fresh_holdout.py --history; PREREG research/v2/tier0_v3/fresh/PREREG_FRESH.md "
         "commit dc95717): G1 code reproduction + IS / burned-OOS cells at feed delay V = 0.5/1/3 s, both stamp-lag "
         "readings, S1 frozen v3 and S2 Table-2 CV trader (burned OOS non-blind; S1 at V > 0 are new cells on "
         "already-burned data; no parameter chosen; COUNTERFACTUAL)")
    t0 = time.time()
    C = ctx_is_oos()
    out = {"label": LABEL, "prereg": PREREG, "prereg_commit": PREREG_COMMIT, "commit": git_head(),
           "seeds": {"IS": "0-19", "burned_OOS": "1000-1019"}}
    # ---- G1a: S2 against the published sweep, seed for seed
    Sw = pd.read_csv(ROOT / "results/tier0/latency_sweep_seeds.csv")
    Sw = Sw[(Sw.source == "video") & (Sw.cv == "own120")]
    g1 = {"S2_vs_latency_sweep_seeds_csv": {}, "max_abs_diff": {"pnl_per_day_usd": 0.0, "per_share_c": 0.0,
                                                                 "per_share_ci95_c_lo": 0.0}}
    cells, dailies = {}, []
    for p in ("IS", "burned_OOS"):
        seeds = [SEED_HIST[p] + k for k in range(N_SEEDS)]
        ctx_s2 = C[p]
        ctx_s1 = C["IS_v3"] if p == "IS" else C[p]
        r2, d2 = run_cells(ctx_s2, seeds, strats=("S2",))
        r1, d1 = run_cells(ctx_s1, seeds, strats=("S1",))
        cells[p] = {**r1, **r2}
        for d in d1 + d2:
            dailies.append(d.assign(period=p))
        for rd, rdn in READINGS.items():
            for V in VS:
                ps = r2["S2"][rd][str(V)]["cov10"]["all_days"]["per_seed"]
                ref = Sw[(Sw.reading == rdn) & (Sw.period == p) & np.isclose(Sw.x_s, V)].set_index("seed")
                diffs = []
                for k, m in enumerate(ps):
                    rr = ref.loc[k]
                    diffs.append({"pnl_per_day_usd": abs(m["pnl_per_day_usd"] - rr.pnl_per_day_usd),
                                  "per_share_c": abs(m["per_share_c"] - rr.per_share_c)})
                mx = {c: max(d[c] for d in diffs) for c in ("pnl_per_day_usd", "per_share_c")}
                g1["S2_vs_latency_sweep_seeds_csv"][f"{p}|{rd}|V{V:g}"] = mx
                for c in mx:
                    g1["max_abs_diff"][c] = max(g1["max_abs_diff"][c], mx[c])
                lo = r2["S2"][rd][str(V)]["cov10"]["all_days"].get("per_share_ci95_c_lo")
                lo_ref = Sw[(Sw.reading == rdn) & (Sw.period == p) & np.isclose(Sw.x_s, V)].per_share_ci95_c_lo.mean()
                g1["max_abs_diff"]["per_share_ci95_c_lo"] = max(g1["max_abs_diff"]["per_share_ci95_c_lo"],
                                                                abs(lo - lo_ref) if lo is not None else 0.0)
        say(f"history {p}: S1 + S2 cells done ({time.time() - t0:.0f}s)")
    g1["passed_S2"] = bool(g1["max_abs_diff"]["pnl_per_day_usd"] < 1e-6 and g1["max_abs_diff"]["per_share_c"] < 1e-6)
    # ---- G1b: S1 at V = 0 (own camera) against the published frozen-v3 IS and burned-OOS results
    g1b = {}
    for p, ref_file, key in (("IS", "results/tier0_v3/is/results.json", ("frozen_v3",)),
                             ("burned_OOS", "results/tier0_v3/burned_oos/results.json", ("burned_oos", "primary"))):
        ref = json.loads((ROOT / ref_file).read_text())
        for k in key:
            ref = ref[k]
        ctx = C["IS_v3"] if p == "IS" else C[p]
        install_v3(ctx, BASE.coverage, ctx["v3_shared"]["cvs"])
        ms = []
        for k in range(N_SEEDS):
            m, _ = metr(sim_S1(ctx, BASE, SEED_HIST[p] + k), ctx["days"])
            ms.append(m)
        Fm = pd.DataFrame(ms)
        got = {"per_share_c": float(Fm.per_share_c.mean()), "pnl_per_day_usd": float(Fm.pnl_per_day_usd.mean())}
        want = {"per_share_c": ref["per_share_c"], "pnl_per_day_usd": ref["pnl_per_day_usd"]}
        ok = all(abs(got[c] - want[c]) <= 5e-4 * max(1.0, abs(want[c])) for c in got)
        g1b[p] = {"got": got, "published": want, "file": ref_file, "reproduced": bool(ok)}
    g1["S1_V0_vs_published_frozen_v3"] = g1b
    g1["passed_S1"] = all(v["reproduced"] for v in g1b.values())
    g1["passed"] = bool(g1["passed_S2"] and g1["passed_S1"])
    g1["note"] = ("src/tier0.py differs from the v3 PREREG pin (commit 6ecc04d added capacity-study options whose "
                  "defaults are the committed model); this gate checks the current code reproduces the stored runs.")
    out["G1_code_reproduction"] = g1
    say(f"G1: S2 max |diff| $/day {g1['max_abs_diff']['pnl_per_day_usd']:.2e}, c/share "
        f"{g1['max_abs_diff']['per_share_c']:.2e}; S1 V=0 {g1b} -> passed={g1['passed']}")
    # ---- cells (comparators) + licence break-even
    out["cells"] = slim_cells(cells)
    out["licence_breakeven_at_V0.5"] = licence_from(cells, "history")
    sw = json.loads((ROOT / "results/tier0/latency_sweep.json").read_text())["video_own120"]
    out["latency_sweep_json_at_V0.5 (S2, already published)"] = {
        rd: {p: {"usd_per_day": sw[READINGS[rd]]["0.5"][p]["usd_per_day"],
                 "net_c_per_share": sw[READINGS[rd]]["0.5"][p]["net_c_per_share"],
                 "net_c_per_share_ci95": sw[READINGS[rd]]["0.5"][p]["net_c_per_share_ci95"],
                 "sharpe_ann": sw[READINGS[rd]]["0.5"][p]["sharpe_ann"]} for p in ("IS", "burned_OOS")}
        for rd in READINGS}
    DER.mkdir(parents=True, exist_ok=True)
    pd.concat(dailies, ignore_index=True).to_parquet(DER / "history_daily.parquet")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "history.json").write_text(jdump(out))
    say(f"history -> {OUT / 'history.json'} ({time.time() - t0:.0f}s)")
    if not g1["passed"]:
        raise SystemExit("G1 FAILED: the current code does not reproduce the stored runs; fix before the fresh run")
    return out


def slim_cells(cells: dict) -> dict:
    """Drop per-seed lists for the compact JSON (they stay in the full results where needed)."""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k != "per_seed"}
        return o
    return strip(cells)


def licence_from(cells: dict, kind: str) -> dict:
    fin = json.loads((ROOT / "results/financials/financials.json").read_text())
    vps = float(fin["cost_assumptions"]["vps_london"]["central"])
    feed = fin["cost_assumptions"]["feed_licence"]
    out = {"formula": f"$/day x {DAYS_PER_MONTH} - {vps:.2f} (London VPS, central): the most a firm could pay per "
                      "month for the feed and still break even (scripts/redteam_derived.py cv.*.maxlic rule)",
           "feed_licence_assumption_usd_per_month": {"low": feed["low"], "central": feed["central"], "high": feed["high"]},
           "values_usd_per_month": {}}
    for p, pc in cells.items():
        for s, sd in pc.items():
            for rd in READINGS:
                for cv, cd in sd[rd]["0.5"].items():
                    for sub, a in cd.items():
                        usd = a.get("pnl_per_day_usd", 0.0)
                        out["values_usd_per_month"][f"{p}|{s}|{rd}|{cv}|{sub}"] = {
                            "usd_per_day": usd, "max_licence_usd_per_month": round(usd * DAYS_PER_MONTH - vps, 0)}
    return out


# ============================================================================================ builders
def build_prints(w: pd.DataFrame) -> pd.DataFrame:
    """tier0_v3_forward.build_prints' rule (tiers.match_prints on each in-play tape), in-process so the tape cache
    redirection to data/fresh/raw holds (no worker processes)."""
    parts = []
    for r in w[["cond", "start", "end", "res0", "fee_rate", "delay"]].to_dict("records"):
        d = F._prints(r)
        if d is not None:
            parts.append(d)
    if not parts:
        return pd.DataFrame(columns=["cond", "ts", "p", "usd"])
    P = pd.concat(parts, ignore_index=True)
    P["cond"] = P.cond.astype(str)
    return P


def tape_stats(conds) -> dict:
    n, cap, missing = 0, [], []
    for c in conds:
        f = pm.RAW / "trades" / f"{c}.parquet"
        if not f.exists():
            missing.append(c)
            continue
        k = len(pd.read_parquet(f, columns=["timestamp"]))
        n += 1
        if k >= 10000:
            cap.append(c)
    return {"tapes_present": n, "tapes_missing": missing, "tapes_at_data_api_offset_cap (>= 10,000 fills)": cap}


def build_tables(w: pd.DataFrame) -> dict:
    """Fresh-path tables for a window universe w (tape cache must already point at data/fresh/raw)."""
    w = w.copy()
    w["prestart_usd"] = w.cond.map(F.prestart_usd(w)).fillna(0.0)
    P = build_prints(w)
    J = F.jump_table(P, w) if len(P) else pd.DataFrame()
    return {"w": w, "P": P, "J": J}


# ======================================================================================= G2 equivalence
def equivalence() -> dict:
    peek("fresh holdout G2 pipeline-equivalence check (scripts/fresh_holdout.py --equivalence; PREREG "
         "research/v2/tier0_v3/fresh/PREREG_FRESH.md section 4): fresh Gamma listing + fresh Data API tapes of the "
         "2026-10-02 U1 matches (burned OOS, non-blind) into data/fresh/raw, rebuilt with the fresh-window path and "
         "compared with the stored tables and the seed-1000 day P&L (no parameter chosen; COUNTERFACTUAL)")
    t0 = time.time()
    lo, hi = EQUIV_DAY
    out = {"label": LABEL, "prereg": PREREG, "prereg_commit": PREREG_COMMIT, "commit": git_head(),
           "day": [str(lo), str(hi)], "run_utc": pd.Timestamp.now(tz="UTC").isoformat()}
    u = universe()
    ud = u[(u.start >= lo) & (u.start < hi)].reset_index(drop=True)
    DER.mkdir(parents=True, exist_ok=True)
    f_w = DATA / "equiv_universe.parquet"
    if f_w.exists():
        w = pd.read_parquet(f_w)
    else:
        w = window_universe(lo, hi)
        w.to_parquet(f_w)
    out["gamma_listing_utc"] = pd.Timestamp(f_w.stat().st_mtime, unit="s", tz="UTC").isoformat()
    a, b = set(ud.cond), set(w.cond)
    out["matches"] = {"stored_U1": len(a), "fresh_listing": len(b), "both": len(a & b),
                      "only_stored": sorted(a - b), "only_fresh": sorted(b - a)}
    wf = w[w.cond.isin(a)].set_index("cond").loc[sorted(a & b)]
    us = ud.set_index("cond").loc[sorted(a & b)]
    facts = {}
    for c in ("start", "end", "volume", "fee_rate", "delay", "res0", "series", "league", "title", "slug"):
        x, y = wf[c], us[c]
        if c in ("volume", "fee_rate", "res0"):
            eq = np.isclose(x.astype(float).to_numpy(), y.astype(float).to_numpy(), rtol=0, atol=1e-6)
        else:
            eq = (x.astype(str).to_numpy() == y.astype(str).to_numpy())
        facts[c] = {"identical": int(eq.sum()), "different": int((~eq).sum())}
        if (~eq).any():
            facts[c]["examples"] = [{"cond": k, "fresh": str(x.loc[k]), "stored": str(y.loc[k])}
                                    for k in list(x.index[~eq])[:5]]
    out["match_facts"] = facts
    w_cmp = w[w.cond.isin(a)].reset_index(drop=True)
    with fresh_raw():
        say(f"G2: fetching {len(w_cmp)} fresh tapes for {lo.date()} into {FRESH_RAW / 'trades'}")
        pm.fetch_many_trades(w_cmp.cond.tolist(), workers=FETCH_WORKERS)
        out["tapes"] = tape_stats(w_cmp.cond)
        tb = build_tables(w_cmp)
    P, Jf, wb = tb["P"], tb["J"], tb["w"]
    # ---- prints
    Ps = pd.read_parquet(ROOT / "data/locked/oos_prints.parquet", columns=["cond", "ts", "p", "usd"],
                         filters=[("cond", "in", sorted(a))])
    Ps["cond"] = Ps.cond.astype(str)
    pr = {"rows_fresh": int(len(P)), "rows_stored": int(len(Ps)), "matches_fresh": int(P.cond.nunique()),
          "matches_stored": int(Ps.cond.nunique())}
    per_match = []
    for c in sorted(set(P.cond) | set(Ps.cond)):
        x = P[P.cond == c].sort_values(["ts", "p", "usd"], kind="stable")
        y = Ps[Ps.cond == c].sort_values(["ts", "p", "usd"], kind="stable")
        same = (len(x) == len(y)) and np.allclose(x[["ts", "p", "usd"]].to_numpy(float),
                                                  y[["ts", "p", "usd"]].to_numpy(float), atol=1e-9)
        per_match.append({"cond": c, "fresh": len(x), "stored": len(y), "identical": bool(same)})
    pm_df = pd.DataFrame(per_match)
    pr["matches_identical"] = int(pm_df.identical.sum()) if len(pm_df) else 0
    pr["matches_different"] = pm_df[~pm_df.identical].to_dict("records") if len(pm_df) else []
    out["inplay_prints"] = pr
    # ---- jumps
    Js_all = T.jump_table("oos").reset_index(drop=True)
    Js_all["row"] = np.arange(len(Js_all))
    Js_all["post30"] = T.post_prices("oos", Js_all)
    Js = Js_all[Js_all.cond.isin(a)].sort_values(["cond", "onset_ts"], kind="stable").reset_index(drop=True)
    Jf = Jf.sort_values(["cond", "onset_ts"], kind="stable").reset_index(drop=True)
    jr = {"jumps_fresh": int(len(Jf)), "jumps_stored": int(len(Js)),
          "jumps_fresh_delay1": int((Jf.delay == 1).sum()) if len(Jf) else 0}
    cols = ["onset_ts", "detect_ts", "dir", "size", "ref", "ref_short", "post30", "volume", "fee_rate", "delay", "res0"]
    if len(Jf) == len(Js) and (Jf.cond.to_numpy() == Js.cond.to_numpy()).all():
        jr["columns"] = {}
        for col in cols:
            x, y = Jf[col].to_numpy(float), Js[col].to_numpy(float)
            same = np.array_equal(np.isnan(x), np.isnan(y)) and np.allclose(x[~np.isnan(x)], y[~np.isnan(y)],
                                                                            atol=1e-12, rtol=0)
            jr["columns"][col] = bool(same)
        for col in ("start", "men", "region"):
            jr["columns"][col] = bool((Jf[col].astype(str).to_numpy() == Js[col].astype(str).to_numpy()).all())
        jr["all_columns_identical"] = all(jr["columns"].values())
    else:
        jr["all_columns_identical"] = False
        jr["per_match_counts"] = (pd.DataFrame({"fresh": Jf.groupby("cond").size(), "stored": Js.groupby("cond").size()})
                                  .fillna(0).astype(int).query("fresh != stored").reset_index().to_dict("records"))
    out["jumps"] = jr
    # ---- pre-start volumes and coverage
    pv = T.prestart_volume(sorted(u.cond))
    x = wb.set_index("cond").prestart_usd.loc[sorted(a)]
    y = pv.reindex(sorted(a)).fillna(0.0)
    out["prestart_usd"] = {"identical": int(np.isclose(x.to_numpy(), y.to_numpy(), atol=1e-6).sum()),
                           "different": int((~np.isclose(x.to_numpy(), y.to_numpy(), atol=1e-6)).sum()),
                           "max_abs_diff_usd": float(np.abs(x.to_numpy() - y.to_numpy()).max())}
    Mf = wb[["cond", "start", "delay", "prestart_usd"]].reset_index(drop=True)
    uu = u.copy()
    uu["prestart_usd"] = uu.cond.map(pv).fillna(0.0)
    cov_f = T.coverage_set(Mf, BASE.coverage, BASE.regime)
    cov_s = T.coverage_set(uu, BASE.coverage, BASE.regime) & a
    out["coverage_set"] = {"fresh": sorted(cov_f), "stored": sorted(cov_s), "identical": cov_f == cov_s}
    # ---- day P&L, seed 1000
    C = ctx_is_oos()
    oos = C["burned_OOS"]
    key = Js_all.set_index(["cond", "onset_ts"]).row
    Jb = Jf.copy()
    rows = key.reindex(pd.MultiIndex.from_arrays([Jb.cond, Jb.onset_ts]))
    pnl = {"rows_mapped_to_stored_oos_rows": int(rows.notna().sum()), "rows_fresh": int(len(Jb))}
    if rows.notna().all():
        Jb["row"] = rows.to_numpy().astype(int)
        Jb["tour"] = Jb.cond.map(dict(zip(oos["J"].cond, oos["J"].tour))).to_numpy().astype(int)
        rb = {**oos, "J": Jb, "M": Mf}           # fresh tables, OOS draw rows / tournament codes / n_rows / n_tour
        # S1 at V = 0 vs the stored burned-OOS trades of seed 1000
        st = pd.read_parquet(ROOT / "results/tier0_v3/burned_oos/trades_frozen_v3_burned_oos.parquet")
        st = st[(st.seed == 1000) & st.cond.isin(a)].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
        install_v3(rb, BASE.coverage, rb["v3_shared"]["cvs"])
        cb = sim_S1(rb, BASE, 1000)
        cb = cb[cb.shares > 1e-9].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
        same = len(cb) == len(st) and all(np.allclose(cb[c].to_numpy(float), st[c].to_numpy(float), atol=1e-9)
                                          for c in ("ts", "q", "shares", "pnl"))
        pnl["S1_V0_seed1000_vs_stored_burned_oos_trades"] = {
            "trades_fresh": int(len(cb)), "trades_stored": int(len(st)), "pnl_usd_fresh": float(cb.pnl.sum()),
            "pnl_usd_stored": float(st.pnl.sum()), "row_for_row_identical": bool(same)}
        # S1 / S2 at V = 0.5 s, both readings: fresh tables vs stored tables
        lsc = {"cvs": oos["cvs"], "pools": oos["pools"], "calib": oos["calib"]}
        for s in ("S1", "S2"):
            for rd in READINGS:
                sc, cvs = vd(s, lsc, rd, 0.5, BASE.coverage)
                if s == "S1":
                    install_v3(oos, BASE.coverage, cvs)
                    x = sim_S1(oos, sc, 1000)
                    install_v3(rb, BASE.coverage, cvs)
                    y = sim_S1(rb, sc, 1000)
                else:
                    x = sim_S2(oos, sc, cvs, 1000)
                    y = sim_S2(rb, sc, cvs, 1000)
                x = x[x.cond.isin(a) & (x.shares > 1e-9)].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
                y = y[(y.shares > 1e-9)].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
                same = len(x) == len(y) and all(np.allclose(x[c].to_numpy(float), y[c].to_numpy(float), atol=1e-9)
                                                for c in ("ts", "q", "shares", "pnl"))
                pnl[f"{s}_{rd}_V0.5_seed1000"] = {"trades_stored_tables": int(len(x)), "trades_fresh_tables": int(len(y)),
                                                 "pnl_usd_stored_tables": float(x.pnl.sum()),
                                                 "pnl_usd_fresh_tables": float(y.pnl.sum()),
                                                 "row_for_row_identical": bool(same)}
    out["day_pnl_seed1000"] = pnl
    checks = [out["matches"]["only_stored"] == [] and out["matches"]["only_fresh"] == [],
              all(v["different"] == 0 for v in facts.values()),
              pr["matches_identical"] == len(pm_df), jr.get("all_columns_identical", False),
              out["prestart_usd"]["different"] == 0, out["coverage_set"]["identical"]]
    checks += [v["row_for_row_identical"] for k, v in pnl.items() if isinstance(v, dict)]
    out["agreement"] = bool(all(checks) and len(checks) == 6 + 5)
    out["seconds"] = round(time.time() - t0, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    prev = json.loads((OUT / "equivalence_check.json").read_text()) if (OUT / "equivalence_check.json").exists() else {}
    g1 = prev.get("G1_code_reproduction")
    if g1 is None and (OUT / "history.json").exists():
        g1 = json.loads((OUT / "history.json").read_text()).get("G1_code_reproduction")
    if g1 is not None:
        out["G1_code_reproduction"] = g1
    (OUT / "equivalence_check.json").write_text(jdump(out))
    say(f"G2 agreement={out['agreement']} -> {OUT / 'equivalence_check.json'} ({out['seconds']}s)")
    return out


# =========================================================================================== fresh window
def fetch(refetch: bool = False) -> dict:
    f_w, f_meta = DATA / "window_universe.parquet", DATA / "window_meta.json"
    if f_w.exists() and f_meta.exists() and not refetch:
        meta = json.loads(f_meta.read_text())
        say(f"fresh window already fetched at {meta['fetch_time_utc']} ({meta['eligible_matches']} matches); "
            "reusing data/fresh (pass --refetch for a new listing)")
        return meta
    if not (OUT / "equivalence_check.json").exists():
        raise SystemExit("REFUSED: run --equivalence (gate G2) before fetching the fresh window")
    first = not f_meta.exists()
    peek("fresh holdout (scripts/fresh_holdout.py --fetch; PREREG research/v2/tier0_v3/fresh/PREREG_FRESH.md commit "
         f"dc95717): {'FIRST READ' if first else 'RE-FETCH (--refetch; new T_f)'} of the fresh window (start > 2026-10-03 07:10 UTC): Gamma catalogue (carries match "
         "results) + Data API tapes into data/fresh/raw; no strategy computed yet; COUNTERFACTUAL")
    Tf = pd.Timestamp.now(tz="UTC").floor("s")
    w0 = window_universe(WINDOW_START, Tf)
    u1 = set(universe().cond)
    meta = {"label": LABEL, "fetch_time_utc": Tf.isoformat(), "window_start_exclusive_utc": WINDOW_START.isoformat(),
            "listed_closed_resolved_atp_wta_ge5k": int(len(w0))}
    w = w0[w0.start > WINDOW_START]
    meta["dropped_start_equal_to_window_start"] = int(len(w0) - len(w))
    meta["dropped_in_U1"] = sorted(w[w.cond.isin(u1)].slug)
    w = w[~w.cond.isin(u1)]
    meta["dropped_live_calibration_matches"] = sorted(w[w.slug.isin(EXCLUDE)].slug)
    w = w[~w.slug.isin(EXCLUDE)]
    late = w.end.isna() | (w.end > Tf - END_MARGIN)
    meta["dropped_finished_within_10min_of_fetch"] = sorted(w[late].slug)
    w = w[~late].reset_index(drop=True)
    meta["eligible_matches"] = int(len(w))
    DATA.mkdir(parents=True, exist_ok=True)
    w.to_parquet(f_w)
    with fresh_raw():
        say(f"fresh window: {len(w)} eligible matches; fetching tapes into {FRESH_RAW / 'trades'} "
            f"(<= {FETCH_WORKERS} concurrent)")
        pm.fetch_many_trades(w.cond.tolist(), workers=FETCH_WORKERS)
        meta.update(tape_stats(w.cond))
    meta["tapes_fetched_by_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
    f_meta.write_text(jdump(meta))
    unresolved_check(Tf)
    say(f"fetch done: {meta['tapes_present']}/{len(w)} tapes")
    return meta


def unresolved_check(Tf: pd.Timestamp) -> dict:
    """Catalogue only (no tape, no price): how many ATP/WTA/challenger moneylines >= $5k had started in the window by
    T_f but were NOT yet closed on Gamma (so the pre-registered rule leaves them out). Informational."""
    days = pd.date_range((WINDOW_START - pd.Timedelta(days=4)).normalize(), Tf.normalize(), freq="D")
    rows = []
    for d in days:
        lo, hi = d.strftime("%Y-%m-%d"), (d + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        for offset in range(0, 2000, 100):
            evs = pm._get(pm.GAMMA, {"tag_slug": "tennis", "closed": "false", "limit": 100, "offset": offset,
                                     "start_date_min": lo, "start_date_max": hi})
            for e in evs:
                rows += pm._slim(e)
            if len(evs) < 100:
                break
    o = pd.DataFrame(rows)
    out = {"checked_utc": pd.Timestamp.now(tz="UTC").isoformat(), "T_f": Tf.isoformat()}
    if len(o):
        o = o.drop_duplicates("cond")
        o["start"] = pd.to_datetime(o.start_time, utc=True, format="mixed")
        o = o[o.series.isin(["atp", "wta", "challenger"]) & (o.volume >= 5_000) & (o.start > WINDOW_START)
              & (o.start < Tf)]
        out.update({"started_in_window_not_closed": int(len(o)), "by_series": o.series.value_counts().to_dict(),
                    "slugs": sorted(o.slug)})
    else:
        out["started_in_window_not_closed"] = 0
    (DATA / "unresolved_check.json").write_text(jdump(out))
    return out


def counts(w: pd.DataFrame, J: pd.DataFrame, M: pd.DataFrame) -> dict:
    cov = T.coverage_set(M, BASE.coverage, BASE.regime)
    w1 = w[w.delay == 1]
    gs = w.league.fillna("").str.contains(GRAND_SLAM) | w.title.fillna("").str.contains(GRAND_SLAM)
    tour = (w.league.fillna("?").str.replace(r",\s*Qualification.*$", "", regex=True)).value_counts().to_dict()
    return {"eligible_matches": int(len(w)), "by_series": w.series.value_counts().to_dict(),
            "grand_slam_matches": int(gs.sum()), "by_delay": w.delay.value_counts().to_dict(),
            "eligible_1s_delay": int(len(w1)), "eligible_1s_by_series": w1.series.value_counts().to_dict(),
            "by_tournament": tour, "covered_primary": int(len(cov)),
            "covered_primary_by_series": w[w.cond.isin(cov)].series.value_counts().to_dict(),
            "covered_primary_by_day": w[w.cond.isin(cov)].start.dt.strftime("%Y-%m-%d").value_counts().sort_index().to_dict(),
            "matches_with_inplay_prints": int(J.cond.nunique()) if len(J) else 0,
            "jumps_all": int(len(J)), "jumps_1s": int((J.delay == 1).sum()) if len(J) else 0,
            "covered_primary_with_jumps": int(J[J.cond.isin(cov)].cond.nunique()) if len(J) else 0,
            "covered_primary_jumps": int(J.cond.isin(cov).sum()) if len(J) else 0,
            "start_range_utc": [str(w.start.min()), str(w.start.max())]}


def ledger(calls: pd.DataFrame, J: pd.DataFrame, w: pd.DataFrame, s: str, rd: str, V: float, seed: int) -> pd.DataFrame:
    if calls is None or len(calls) == 0:
        return pd.DataFrame()
    c = calls.copy()
    if "row" not in c:
        key = J.set_index(["cond", "onset_ts"]).row
        c["row"] = key.reindex(pd.MultiIndex.from_arrays([c.cond, c.ts])).to_numpy().astype(int)
    j = J.set_index("row").loc[c.row.to_numpy()]
    tok0 = (c.d0.to_numpy() > 0) if "d0" in c else c.tok0.to_numpy().astype(bool)
    wi = w.set_index("cond")
    out0 = wi.out0.reindex(c.cond).to_numpy()
    out1 = wi.out1.reindex(c.cond).to_numpy()
    filled = c.shares.to_numpy() > 1e-9
    return pd.DataFrame({
        "label": LABEL, "strategy": s, "reading": READING_LABEL[rd], "V_s": V, "seed": seed, "cond": c.cond.to_numpy(),
        "jump_onset_utc": pd.to_datetime(c.ts.to_numpy(), unit="s", utc=True).astype(str),
        "jump_detect_utc": pd.to_datetime(j.detect_ts.to_numpy(), unit="s", utc=True).astype(str),
        "jump_dir_outcome0": j["dir"].to_numpy(), "jump_size_c_realised_DIAGNOSTIC": 100 * j["size"].to_numpy(),
        "pre_jump_price_outcome0 (ref, 60 s VWAP)": j["ref"].to_numpy(),
        "post_jump_price_outcome0 (30 s VWAP)": j["post30"].to_numpy(),
        "simulated_call": np.where(c.correct.to_numpy(), "correct", "wrong"),
        "cv_early_out_call": c.early.to_numpy(),
        "tau_s (order reaches book this many s before (+) / after (-) the modelled reprice)": c.tau.to_numpy(),
        "token_bought": np.where(tok0, out0, out1), "filled": filled,
        "fill_price": np.where(filled, c.q.to_numpy(), np.nan), "shares": c.shares.to_numpy(),
        "usd_in": c.shares.to_numpy() * c.q.to_numpy(), "fee_per_share": c.fee_ps.to_numpy(),
        "exit": "hold to resolution", "exit_payout_per_share": c.payout.to_numpy(),
        "pnl_per_share": np.where(filled, c.pnl_ps.to_numpy(), np.nan), "pnl_usd": c.pnl.to_numpy()})


def price_path(cond: str, row: pd.Series) -> pd.DataFrame:
    t = load_tape(cond)
    s, e = int(row.start.timestamp()), int(row.end.timestamp())
    t = t[(t.timestamp >= s) & (t.timestamp <= e)]
    t = t.assign(pv=t.p0 * t.usd)
    g = t.groupby("timestamp").agg(n_prints=("p0", "size"), usd=("usd", "sum"), pv=("pv", "sum"),
                                   p_last=("p0", "last"), p_min=("p0", "min"), p_max=("p0", "max")).reset_index()
    g["vwap_outcome0"] = g.pv / g.usd.where(g.usd > 0)
    g["utc"] = pd.to_datetime(g.timestamp, unit="s", utc=True).astype(str)
    g.insert(0, "label", LABEL)
    g.insert(1, "outcome0", row.out0)
    return g[["label", "outcome0", "utc", "timestamp", "n_prints", "usd", "vwap_outcome0", "p_last", "p_min", "p_max"]]


def run() -> dict:
    f_w, f_meta = DATA / "window_universe.parquet", DATA / "window_meta.json"
    if not f_meta.exists():
        raise SystemExit("run --fetch first")
    eq = json.loads((OUT / "equivalence_check.json").read_text())
    hist = json.loads((OUT / "history.json").read_text()) if (OUT / "history.json").exists() else None
    if hist is None or not hist["G1_code_reproduction"]["passed"]:
        raise SystemExit("REFUSED: gate G1 has not passed (run --history)")
    if not eq.get("agreement"):
        raise SystemExit("REFUSED: gate G2 did not agree; explain it in equivalence_check.json before the fresh run")
    meta = json.loads(f_meta.read_text())
    w = pd.read_parquet(f_w)
    t0 = time.time()
    with fresh_raw():
        tb = build_tables(w)
        w, P, J = tb["w"], tb["P"], tb["J"]
        inplay = P.groupby("cond").usd.sum() if len(P) else pd.Series(dtype=float)
        if len(J):
            J = J.reset_index(drop=True)
            J["row"] = np.arange(len(J))
            tour = T.tournament_codes(w)
            J["tour"] = J.cond.map(tour).astype(int)
            n_tour = int(tour.max()) + 1
        else:
            n_tour = 1
        M = w[["cond", "start", "delay", "prestart_usd"]].reset_index(drop=True)
        DER.mkdir(parents=True, exist_ok=True)
        J.to_parquet(DER / "fresh_jumps.parquet")
        P[["cond", "ts", "p", "usd"]].to_parquet(DER / "fresh_prints.parquet")
        res = {"label": LABEL, "test": "fresh holdout: a firm with a licensed feed at assumed delay V (0.5 / 1 / 3 s)",
               "prereg": PREREG, "prereg_commit": PREREG_COMMIT, "prereg_committed_utc": PREREG_UTC,
               "commit": git_head(), "run_utc": pd.Timestamp.now(tz="UTC").isoformat(), "fetch": meta,
               "window": {"start_exclusive_utc": WINDOW_START.isoformat(), "end_fetch_time_utc": meta["fetch_time_utc"]},
               "strategies": STRATS, "readings": READING_LABEL, "coverages": COVERAGE_LABEL,
               "V_s": list(VS), "seeds": [SEED_FRESH, SEED_FRESH + N_SEEDS - 1],
               "frozen_v3": {"variant": FROZEN.name(), "rule": asdict(FROZEN)},
               "base_scenario": asdict(BASE), "counts": counts(w, J, M)}
        if (DATA / "unresolved_check.json").exists():
            res["window_matches_left_out_as_unresolved (catalogue only)"] = json.loads(
                (DATA / "unresolved_check.json").read_text())
        J1 = J[J.delay == 1] if len(J) else J
        if len(J1) == 0:
            res["result"] = "no 1 s-delay jumps in the window: no calls"
            (OUT / "results.json").write_text(jdump(res))
            return res
        days = T.period_days(J, BASE.regime)
        Jsub = J[(J.start >= SUB14) & (J.delay == 1)]
        subsets = {"all_days": (None, days)}
        if len(Jsub):
            subsets["sub_start_ge_1400"] = (SUB14, T.period_days(Jsub, BASE.regime))
        sh = v3_shared()
        ctx = {"J": J, "M": M, "days": days, "n_rows": len(J), "n_tour": n_tour, "pools": {p: T.live_points(p) for p in ("D>=3c", "all")},
               "cvs": T.cv_systems(), "mix": T.point_mix(), "calib": T.calibrate_stamp_lag(), "v3_shared": sh}
        cov10 = T.coverage_set(M, BASE.coverage, BASE.regime)
        cand = inplay[inplay.index.isin(cov10 & set(w[w.delay == 1].cond))]
        show = str(cand.idxmax()) if len(cand) else None
        keep = {(s, rd, 0.5, "cov10", SEED_FRESH + k): None for s in ("S1", "S2") for rd in READINGS
                for k in range(N_SEEDS)}
        first_sim = not (OUT / "results.json").exists()
        peek(f"fresh holdout (scripts/fresh_holdout.py --run): {'FIRST SIMULATION' if first_sim else 'RE-RUN (same cached data, same seeds)'} on the fresh window START "
             f"(window ({WINDOW_START.isoformat()}, {meta['fetch_time_utc']}), {meta['eligible_matches']} eligible "
             f"matches; S1 frozen v3 + S2 Table-2 CV trader x V 0.5/1/3 s x 2 readings x 2 coverages x seeds 4000-4019; "
             f"commit {git_head()}; COUNTERFACTUAL)")
        cells, dailies = run_cells(ctx, [SEED_FRESH + k for k in range(N_SEEDS)], covs=tuple(COVERAGES),
                                   subsets=subsets, keep=keep)
        say(f"fresh cells done ({time.time() - t0:.0f}s)")
        res["cells"] = cells
        res["table"] = table(cells)
        res["licence_breakeven_at_V0.5 (fresh, anecdotal)"] = licence_from({"fresh": cells}, "fresh")
        res["days"] = [str(d.date()) for d in days]
        # ---- showcase
        if show is not None:
            wr = w.set_index("cond").loc[show]
            led = pd.concat([ledger(keep[(s, rd, 0.5, "cov10", SHOW_SEED)], J, w, s, rd, 0.5, SHOW_SEED)
                             .pipe(lambda d: d[d.cond == show] if len(d) else d)
                             for s in ("S1", "S2") for rd in READINGS], ignore_index=True)
            led.to_csv(OUT / "showcase_ledger.csv", index=False)
            allt = pd.concat([ledger(keep[(s, rd, 0.5, "cov10", SEED_FRESH + k)], J, w, s, rd, 0.5, SEED_FRESH + k)
                              .pipe(lambda d: d[(d.cond == show) & d.filled] if len(d) else d)
                              for s in ("S1", "S2") for rd in READINGS for k in range(N_SEEDS)], ignore_index=True)
            allt.to_csv(OUT / "showcase_trades_all_seeds.csv", index=False)
            price_path(show, wr).to_csv(OUT / "showcase_price_1s.csv", index=False)
            per_match = {}
            for s in ("S1", "S2"):
                for rd in READINGS:
                    for V in VS:
                        sc_pm = match_pnl(ctx, s, rd, V, show)
                        per_match[f"{s}|{rd}|V{V:g}"] = sc_pm
            winner = wr.out0 if wr.res0 == 1.0 else (wr.out1 if wr.res0 == 0.0 else "void / split")
            res["showcase"] = {
                "rule": "eligible covered (primary) 1 s-delay window match with the highest in-play traded $ "
                        "(PREREG_FRESH.md section 5; not chosen on P&L)",
                "cond": show, "slug": wr.slug, "title": wr.title, "league": wr.league, "series": wr.series,
                "start_utc": str(wr.start), "end_utc": str(wr.end), "winner": winner, "res0": float(wr.res0),
                "inplay_usd": float(inplay.loc[show]), "polymarket_volume_usd": float(wr.volume),
                "prestart_usd": float(wr.prestart_usd), "jumps": int((J.cond == show).sum()),
                "runner_up_inplay_usd": [{"slug": w.set_index("cond").slug.loc[k], "inplay_usd": float(v)}
                                         for k, v in cand.sort_values(ascending=False).iloc[1:4].items()],
                "ledger_seed": SHOW_SEED, "ledger_rows": int(len(led)),
                "ledger_seed_filled_trades": {f"{s}|{rd}|V0.5": int(led[(led.strategy == s) & (led.reading == READING_LABEL[rd])].filled.sum())
                                              for s in ("S1", "S2") for rd in READINGS},
                "all_seed_filled_trades_file": "results/fresh_holdout/showcase_trades_all_seeds.csv",
                "all_seed_filled_trades": {f"{s}|{rd}|V0.5": int(((allt.strategy == s) & (allt.reading == READING_LABEL[rd])).sum())
                                           for s in ("S1", "S2") for rd in READINGS} if len(allt) else {},
                "pnl_20_seed_mean_usd": per_match,
                "ledger_seed_pnl_usd": {f"{s}|{rd}|V0.5": float(led[(led.strategy == s) & (led.reading == READING_LABEL[rd])].pnl_usd.sum())
                                        for s in ("S1", "S2") for rd in READINGS}}
    # ---- daily.csv: history (IS, burned OOS) + fresh
    fd = pd.concat(dailies, ignore_index=True).assign(period="fresh")
    parts = [fd]
    if (DER / "history_daily.parquet").exists():
        parts.insert(0, pd.read_parquet(DER / "history_daily.parquet"))
    D = pd.concat(parts, ignore_index=True)
    D.insert(0, "label", LABEL)
    D["strategy_name"] = D.strategy.map(STRATS)
    D["reading_name"] = D.reading.map(READING_LABEL)
    cols = ["label", "period", "strategy", "strategy_name", "reading", "reading_name", "V_s", "coverage", "subset",
            "date", "pnl_mean_usd", "pnl_p10_usd", "pnl_p90_usd", "pnl_sd_usd", "n_seeds"]
    D[cols].to_csv(OUT / "daily.csv", index=False)
    if hist is not None:
        res["history_comparators (IS seeds 0-19, burned OOS 1000-1019; from history.json)"] = {
            p: {s: {rd: {str(V): {k: hist["cells"][p][s][rd][str(V)]["cov10"]["all_days"].get(k)
                                  for k in ("per_share_c", "per_share_ci95_c_lo", "per_share_ci95_c_hi",
                                            "pnl_per_day_usd", "pnl_per_day_ci95_usd_lo", "pnl_per_day_ci95_usd_hi",
                                            "sharpe_ann", "n_trades", "n_matches", "profitable_trades_pct")}
                         for V in VS} for rd in READINGS} for s in ("S1", "S2")} for p in ("IS", "burned_OOS")}
        res["licence_breakeven_at_V0.5 (IS / burned OOS)"] = hist["licence_breakeven_at_V0.5"]
    res["equivalence_check"] = {"agreement": eq.get("agreement"), "file": "results/fresh_holdout/equivalence_check.json"}
    res["notes_beyond_prereg"] = [
        "showcase_trades_all_seeds.csv (every filled trade on the showcase match, all 20 seeds, V = 0.5 s) was added "
        "after the run because the pre-registered ledger seed (4000) has no fill on that match; descriptive only, no "
        "number changes (research/v2/tier0_v3/fresh/DEVIATIONS_FRESH.md).",
        "The count of window matches that had started but were not closed on Gamma at T_f (catalogue only) was "
        "added to explain the window's size; it changes no number."]
    res["caveats"] = [
        "Simulated calls: no feed or video was bought or watched; call timing, accuracy and fill depth are modelled "
        "from our measurements plus an assumed feed delay V.",
        "Trades are the historical >= 4c detector jumps, found with prices up to 10 s after the point: selected on "
        "outcomes, not ex ante.",
        "Sample: about one day of matches; cells with < 30 matches with trades are anecdotal (no edge claim either way).",
        "Sharpe over fewer than 10 days is not meaningful.",
        "Model inputs (book depth, reprice timing) come from 9 WTA matches on 2026-10-03, excluded from this window.",
        "S2 takes the stale depth up to the realised new mid (not ex ante); S1 is the ex-ante limit-price rule."]
    (OUT / "results.json").write_text(jdump(res))
    peek(f"fresh holdout (scripts/fresh_holdout.py --run) DONE -> results/fresh_holdout/results.json "
         f"(showcase {res.get('showcase', {}).get('slug')}; COUNTERFACTUAL)")
    say(f"run -> {OUT / 'results.json'} ({time.time() - t0:.0f}s)")
    return res


def match_pnl(ctx: dict, s: str, rd: str, V: float, cond: str) -> dict:
    lsc = {"cvs": ctx["cvs"], "pools": ctx["pools"], "calib": ctx["calib"]}
    sc, cvs = vd(s, lsc, rd, V, BASE.coverage)
    if s == "S1":
        install_v3(ctx, BASE.coverage, cvs)
    v = []
    nt = []
    for k in range(N_SEEDS):
        c = sim_S1(ctx, sc, SEED_FRESH + k) if s == "S1" else sim_S2(ctx, sc, cvs, SEED_FRESH + k)
        c = c[(c.cond == cond)] if len(c) else c
        v.append(float(c.pnl.sum()) if len(c) else 0.0)
        nt.append(int((c.shares > 1e-9).sum()) if len(c) else 0)
    return {"mean_usd": round(float(np.mean(v)), 2), "seed_p10_usd": round(float(np.percentile(v, 10)), 2),
            "seed_p90_usd": round(float(np.percentile(v, 90)), 2), "mean_trades": round(float(np.mean(nt)), 2),
            "seeds_positive": int(sum(x > 0 for x in v))}


def table(cells: dict) -> list[dict]:
    rows = []
    for s in ("S1", "S2"):
        for rd in READINGS:
            for V in VS:
                for cv in COVERAGES:
                    for sub, a in cells[s][rd][str(V)][cv].items():
                        rows.append({"strategy": s, "reading": rd, "V_s": V, "coverage": cv, "subset": sub,
                                     "pnl_usd": a.get("pnl_usd"), "pnl_per_day_usd": a.get("pnl_per_day_usd"),
                                     "pnl_per_day_ci95_usd": [a.get("pnl_per_day_ci95_usd_lo"), a.get("pnl_per_day_ci95_usd_hi")],
                                     "pnl_per_day_seed_range95": [a.get("pnl_per_day_usd_seed_p2_5"), a.get("pnl_per_day_usd_seed_p97_5")],
                                     "per_share_c": a.get("per_share_c"),
                                     "per_share_ci95_c": [a.get("per_share_ci95_c_lo"), a.get("per_share_ci95_c_hi")],
                                     "sharpe_ann": a.get("sharpe_ann"),
                                     "sharpe_seed_range95": [a.get("sharpe_ann_seed_p2_5"), a.get("sharpe_ann_seed_p97_5")],
                                     "sharpe_note": a.get("sharpe_note"),
                                     "sharpe_display": (a.get("sharpe_note") if (a.get("days") or 0) < MIN_DAYS_SHARPE
                                                        else a.get("sharpe_ann")),
                                     "hit_rate_pct": a.get("profitable_trades_pct"),
                                     "wrong_call_share": a.get("wrong_call_share_of_trades"),
                                     "n_trades": a.get("n_trades"), "n_matches": a.get("n_matches"),
                                     "n_calls": a.get("n_calls"), "days": a.get("days"),
                                     "n_seeds_with_trades": a.get("n_seeds_with_trades"),
                                     "anecdotal": a.get("anecdotal (mean matches with trades < 30)")})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--equivalence", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--refetch", action="store_true")
    a = ap.parse_args()
    if a.all or a.history:
        history()
    if a.all or a.equivalence:
        equivalence()
    if a.all or a.fetch:
        fetch(a.refetch)
    if a.all or a.run:
        run()


if __name__ == "__main__":
    main()
