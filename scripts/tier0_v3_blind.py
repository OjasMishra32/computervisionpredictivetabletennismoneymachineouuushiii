"""Tier-0 v3 BLIND tests (a) burned OOS and (b) U2, both periods, of research/v2/tier0_v3/PREREG.md.

    COUNTERFACTUAL WITH ASSUMED DATA. Assumed: licensed live feed + courtside camera, NOT purchased;
    parameters from our measurements. No live ATP/WTA point feed was bought or used, and we have no camera footage
    of any match. Historical prices, results, fees and venue delays are real (public Polymarket tapes); the tier-0
    trader's timing, fills and call accuracy are modelled (src/tier0.py CORRECTED model + the frozen v3 rule).
    No orders are placed.

Order (PREREG section 7), each step once:
    python scripts/tier0_v3_blind.py --oos-gate        # (a) START line, then the reproduction gate on burned OOS
    python scripts/tier0_v3_blind.py --run burned_oos  # (a) frozen v3 (+ D2 stress, v2 reference, 48-scenario bracket)
    python scripts/tier0_v3_blind.py --builder-check   # (b) builder check on U1 IS data (2026-08-10 -> 08-13)
    python scripts/tier0_v3_blind.py --build-u2        # (b) START line, then U2 jump tables + pre-start volumes
    python scripts/tier0_v3_blind.py --run u2_is       # (b) U2-IS period (seeds 2000-2019)
    python scripts/tier0_v3_blind.py --run u2_oos      # (b) U2-OOS period (seeds 3000-3019)
    python scripts/tier0_v3_blind.py --collect         # verdicts, results.json per set, blind.json, figure
  --run SET --part i --nparts n  runs every n-th job (SLURM array on HiPerGator); --workers <= 3 locally.

The simulator is O.simulate_v3 (scripts/tier0_v3_optimise.py, pinned) on T.CORRECTED, unchanged. Each test set
supplies its own jump table, universe and days through tier0_v3_forward.install_context (pinned), which takes the
shared measured inputs (live pools + limit curve, CV tables, point mix, stamp-lag calibration, leverage table) from
the IS bundle. Metrics: tier0_v3_forward.metrics_test = O.metrics_v3 (match-clustered CI) + the day-clustered and
tournament-clustered CIs (1,000 draws, rng seed 0). Every headline number is a 20-seed mean +/- SD; CI bounds are
averaged over seeds. Implementation notes logged before the runs: research/v2/tier0_v3/DEVIATIONS.md D4-D9.
"""
from __future__ import annotations

import argparse
import json
import pickle
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from src import tier0 as T  # noqa: E402
import tier0_v3_optimise as O  # noqa: E402
import tier0_v3_forward as F  # noqa: E402

LABEL = ("COUNTERFACTUAL WITH ASSUMED DATA - assumed: licensed live feed + courtside camera, not purchased; "
         "parameters from our measurements. No live ATP/WTA point feed was used. Tier-0 v3 blind tests "
         "(a) burned OOS (non-blind window) and (b) U2 unseen markets, research/v2/tier0_v3/PREREG.md.")
OUT = ROOT / "results/tier0_v3"
CTX = ROOT / "data/derived/tier0_v3_blind"          # test-set contexts (derived OOS/U2 tables; not committed)
PARTS = CTX / "parts"
LOG = ROOT / "results/oos_peeks.log"
FROZEN = F.FROZEN
BASE = T.CORRECTED
N_SEEDS = 20
SEED_BASE = {"burned_oos": 1000, "u2_is": 2000, "u2_oos": 3000}
PRIMARY_BN = "lag2|tournament|trunc0|queue0"
CONFIGS = {"frozen_v3": FROZEN,
           "frozen_v3_D2": replace(FROZEN, hist_limit=True),
           "v2_headline": O.V2_HEADLINE}
CONFIG_LABEL = {"frozen_v3": "frozen v3 (th0.9|hold|lev|z0.05-0.95|X2c)",
                "frozen_v3_D2": "frozen v3 + limit also enforced in the historical-price frame (D2 stress; never a verdict)",
                "v2_headline": "tier-0 v2 headline (reference only: sweeps to the realised new mid, not ex-ante)"}
U2_UNIVERSE = ROOT / "data/expand_universe.parquet"
U2_PRINTS = ROOT / "data/expand_prints.parquet"
WOMEN_RE = re.compile(r"\bwomen\b|\bW\d{2,3}\b", re.I)
MEN_LABEL_RE = re.compile(r"\bmen\b|\bM\d{2,3}\b", re.I)    # only to report how many U2 matches carry a men's label
MIN_MATCHES, MIN_TRADE_DAYS = 30, 20
BUILDER_WINDOW = (pd.Timestamp("2026-08-10", tz="UTC"), pd.Timestamp("2026-08-13", tz="UTC"))
KEEP_COLS = ["cond", "row", "ts", "date", "month", "q", "shares", "pnl", "pnl_ps", "usd_in", "correct", "tau",
             "fee_ps", "edge_c", "payout", "post_b", "q_stale", "size", "rate", "tok0", "early", "prec", "lock_end"]


def say(msg: str) -> None:
    print(f"[{pd.Timestamp.now(tz='UTC').strftime('%H:%M:%S')}Z] {msg}", flush=True)


def peek(msg: str) -> None:
    with LOG.open("a") as fh:
        fh.write(f"{pd.Timestamp.now(tz='UTC').isoformat()} {msg}\n")


def guard() -> None:
    F.check_frozen()
    bad = F.check_hashes()
    if bad:
        raise SystemExit("REFUSED: pinned code/input hashes differ from PREREG.md:\n" + json.dumps(bad, indent=1))


def calib() -> float:
    meta = json.loads((O.BUNDLE / "meta.json").read_text())
    return float(meta["calib"]["central"]["stamp_lag_s"])


def scenarios() -> dict:
    sc = O.bracket_scenarios(calib())
    assert sc[PRIMARY_BN] == BASE, "bracket primary must be T.CORRECTED"
    return sc


# ============================================================================================ contexts
def women_label(u: pd.DataFrame) -> np.ndarray:
    """PREREG section 4: women if series == wta, or league / title prefix (text before the first ':') matches
    \\bwomen\\b or \\bW\\d{2,3}\\b (case-insensitive). Everything else takes the men's point mix."""
    txt = u.league.fillna("") + " || " + u.title.fillna("").str.split(":").str[0]
    return ((u.series == "wta") | txt.str.contains(WOMEN_RE)).to_numpy()


def save_ctx(name: str, c: dict, extra: dict | None = None) -> None:
    CTX.mkdir(parents=True, exist_ok=True)
    keep = {k: c[k] for k in ("pools", "cvs", "mix", "calib", "lev", "J", "Jc", "M", "E", "days", "n_rows", "n_tour")}
    with open(CTX / f"{name}.pkl", "wb") as fh:
        pickle.dump({"label": LABEL, "ctx": keep, "extra": extra or {}}, fh)


def load_ctx(name: str) -> dict:
    with open(CTX / f"{name}.pkl", "rb") as fh:
        d = pickle.load(fh)
    O._C.clear()
    O._C.update(d["ctx"])
    return d


def ctx_burned_oos() -> dict:
    """Tier-0 v2's burned-OOS tables, exactly as scripts/tier0_backtest.context builds them."""
    from src.tape import universe
    J = T.jump_table("oos").reset_index(drop=True)
    J["row"] = np.arange(len(J))
    J["post30"] = T.post_prices("oos", J)
    u = universe()
    v = T.prestart_volume(sorted(u.cond))
    u["prestart_usd"] = u.cond.map(v).fillna(0.0)
    tour = T.tournament_codes(u)
    J["tour"] = J.cond.map(tour).astype(int)
    M = u.reset_index(drop=True)
    c = F.install_context(J, M, int(tour.max()) + 1)
    return c


# ======================================================================================= (a) OOS gate
def oos_gate() -> dict:
    guard()
    peek("tier0 v3 blind test (a) burned OOS START (scripts/tier0_v3_blind.py; PREREG research/v2/tier0_v3/PREREG.md "
         "section 5; non-blind window seen by v1/v2/tier-0 v2; v3 chosen on IS only; COUNTERFACTUAL): reproduction "
         "gate with V2_HEADLINE, then frozen v3 once (seeds 1000-1019)")
    t0 = time.time()
    c = ctx_burned_oos()
    save_ctx("burned_oos", c)
    say(f"burned OOS: {len(c['J'])} jumps, {len(c['Jc'])} covered jumps, {c['Jc'].cond.nunique()} covered matches "
        f"with jumps, {len(c['days'])} days, n_tour {c['n_tour']} ({time.time() - t0:.0f}s)")
    out = {"rows": {}}
    for s in (1000, 1007):
        dr = T.draws(c["n_rows"], s, max(c["n_tour"], 1))
        a = O.simulate_v3(BASE, O.V2_HEADLINE, dr).sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
        b = T.simulate(c["J"], c["M"], BASE, dr, c["pools"], c["cvs"], c["mix"])
        assert len(a) == len(b), (len(a), len(b))
        for col in ("q", "shares", "pnl", "tau", "fee_ps"):
            assert np.allclose(a[col].to_numpy(), b[col].to_numpy(), atol=1e-12), col
        out["rows"][str(s)] = {"calls": int(len(a)), "pnl_usd": float(a.pnl.sum()), "row_for_row": True}
        say(f"seed {s}: v3 simulator == T.simulate(CORRECTED) row for row: {len(a)} calls, P&L ${a.pnl.sum():,.2f}")
    ms = []
    for k in range(N_SEEDS):
        dr = T.draws(c["n_rows"], 1000 + k, max(c["n_tour"], 1))
        m, _ = O.metrics_v3(O.simulate_v3(BASE, O.V2_HEADLINE, dr), c["days"])
        ms.append(m)
    Fm = pd.DataFrame(ms)
    got = {"per_share_c": Fm.per_share_c.mean(), "per_share_c_sd": Fm.per_share_c.std(ddof=0),
           "per_share_ci95_c_lo": Fm.per_share_ci95_c_lo.mean(), "per_share_ci95_c_hi": Fm.per_share_ci95_c_hi.mean(),
           "pnl_per_day_usd": Fm.pnl_per_day_usd.mean(), "pnl_per_day_usd_sd": Fm.pnl_per_day_usd.std(ddof=0),
           "n_trades": Fm.n_trades.mean(), "sharpe_ann": Fm.sharpe_ann.mean()}
    h = json.loads((ROOT / "results/tier0/results.json").read_text())["headline"]["burned_OOS"]
    want = {"per_share_c": h["mean"]["per_share_c"], "per_share_c_sd": h["sd"]["per_share_c"],
            "per_share_ci95_c_lo": h["mean"]["per_share_ci95_c_lo"], "per_share_ci95_c_hi": h["mean"]["per_share_ci95_c_hi"],
            "pnl_per_day_usd": h["mean"]["pnl_per_day_usd"], "pnl_per_day_usd_sd": h["sd"]["pnl_per_day_usd"],
            "n_trades": h["mean"]["n_trades"], "sharpe_ann": h["mean"]["sharpe_ann"]}
    diff = {k: float(got[k] - want[k]) for k in want}
    ok = all(abs(d) < 5e-4 * max(1.0, abs(want[k])) for k, d in diff.items())
    out.update({"v2_headline_20_seeds": {k: round(float(v), 4) for k, v in got.items()},
                "tier0_v2_results_json": want, "diff": diff, "reproduced": bool(ok),
                "printed": "+0.58c +/- 0.37 [-0.08, 1.21], $46 +/- 39/day"})
    say(f"gate: v2 headline on burned OOS {got['per_share_c']:.4f}c ± {got['per_share_c_sd']:.4f} "
        f"[{got['per_share_ci95_c_lo']:.4f}, {got['per_share_ci95_c_hi']:.4f}], ${got['pnl_per_day_usd']:.2f} ± "
        f"{got['pnl_per_day_usd_sd']:.2f}/day -> reproduced={ok} (max |diff| {max(abs(d) for d in diff.values()):.2e})")
    CTX.mkdir(parents=True, exist_ok=True)
    (CTX / "gate.json").write_text(json.dumps({"label": LABEL, **out}, indent=1, default=float))
    if not ok:
        raise SystemExit("GATE FAILED: fix the plumbing and log it in DEVIATIONS.md before computing frozen v3")
    return out


# ================================================================================ (b) builder check
def builder_check() -> dict:
    """PREREG section 3/7: tier0_v3_forward's builder (jump_table, post30, prestart_usd) on an IS window must
    reproduce data/derived/tier0_jumps_is.parquet / tier0_post30_is.parquet / the pre-start volumes and coverage,
    and, with IS row and tournament indices, the IS frozen-v3 trades row for row (seeds 0 and 7). U1 IS only."""
    guard()
    from src.tape import universe
    t0 = time.time()
    lo, hi = BUILDER_WINDOW
    u = universe()
    w = u[(u.start >= lo) & (u.start < hi)].reset_index(drop=True)
    P = pd.read_parquet(ROOT / "data/is_prints.parquet", columns=["cond", "ts", "p", "usd"],
                        filters=[("cond", "in", sorted(w.cond))])
    P["cond"] = P.cond.astype(str)
    Jb = F.jump_table(P, w)
    Jis = T.jump_table("is").reset_index(drop=True)
    post_is = T.post_prices("is", Jis)
    Jis = Jis.assign(post30=post_is, row=np.arange(len(Jis)))
    ref = Jis[Jis.cond.isin(set(w.cond))].sort_values(["cond", "onset_ts"], kind="stable").reset_index(drop=True)
    res = {"window": [str(lo), str(hi)], "matches": int(len(w)), "jumps_builder": int(len(Jb)), "jumps_is_table": int(len(ref))}
    assert len(Jb) == len(ref), res
    cols = ["onset_ts", "detect_ts", "dir", "size", "ref", "ref_short", "post30", "volume", "fee_rate", "delay", "res0"]
    for col in cols:
        a, b = Jb[col].to_numpy(float), ref[col].to_numpy(float)
        assert np.array_equal(np.isnan(a), np.isnan(b)) and np.allclose(a[~np.isnan(a)], b[~np.isnan(b)], atol=1e-12, rtol=0), col
    assert (Jb.cond.to_numpy() == ref.cond.to_numpy()).all() and (Jb.start.to_numpy() == ref.start.to_numpy()).all()
    assert (Jb.men.to_numpy() == ref.men.to_numpy()).all() and (Jb.region.to_numpy() == ref.region.to_numpy()).all()
    res["columns_identical"] = cols + ["cond", "start", "men", "region"]
    ps = F.prestart_usd(w)
    pv = T.prestart_volume(sorted(u.cond))
    assert np.allclose(ps.reindex(w.cond).to_numpy(), pv.reindex(w.cond).to_numpy(), atol=1e-9)
    w["prestart_usd"] = w.cond.map(ps)
    u["prestart_usd"] = u.cond.map(pv).fillna(0.0)
    cov_w = T.coverage_set(w, BASE.coverage, BASE.regime)
    cov_u = T.coverage_set(u, BASE.coverage, BASE.regime) & set(w.cond)
    assert cov_w == cov_u
    res["prestart_identical"] = True
    res["coverage_set_identical"] = int(len(cov_w))
    # row for row: IS frozen v3 vs the builder's tables carrying IS row / tournament indices
    O._C.clear()
    c = O.context()
    rowmap = ref.set_index(["cond", "onset_ts"]).row
    Jb2 = Jb.copy()
    Jb2["row"] = rowmap.reindex(pd.MultiIndex.from_arrays([Jb2.cond, Jb2.onset_ts])).to_numpy().astype(int)
    Jb2["tour"] = c["J"].set_index("row").tour.reindex(Jb2.row).to_numpy().astype(int)
    shared = {k: c[k] for k in ("pools", "cvs", "mix", "calib", "lev")}
    n_rows, n_tour, M_is = c["n_rows"], c["n_tour"], c["M"]
    res["rows"] = {}
    for s in (0, 7):
        O._C.clear()
        c = O.context()
        dr = T.draws(n_rows, s, max(n_tour, 1))
        a = O.simulate_v3(BASE, FROZEN, dr)
        a = a[a.cond.isin(set(w.cond))].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
        cov = T.coverage_set(M_is, BASE.coverage, BASE.regime)
        O._C.clear()
        O._C.update(shared, J=Jb2, Jc=Jb2[Jb2.cond.isin(cov)].reset_index(drop=True), M=M_is,
                    E=pd.DataFrame({"t_rep": np.full(int(Jb2.cond.isin(cov).sum()), np.nan),
                                    "rep_found": np.zeros(int(Jb2.cond.isin(cov).sum()), bool)}),
                    days=T.period_days(Jb2, BASE.regime), n_rows=n_rows, n_tour=n_tour)
        b = O.simulate_v3(BASE, FROZEN, dr).sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
        assert len(a) == len(b), (len(a), len(b))
        for col in ("q", "shares", "pnl", "tau", "fee_ps", "correct"):
            assert np.allclose(a[col].to_numpy(float), b[col].to_numpy(float), atol=1e-12), col
        res["rows"][str(s)] = {"calls": int(len(a)), "trades": int((a.shares > 1e-9).sum()), "pnl_usd": float(a.pnl.sum())}
        say(f"builder check seed {s}: frozen v3 trades row for row ({len(a)} calls, P&L ${a.pnl.sum():,.2f})")
    O._C.clear()
    res["passed"] = True
    res["seconds"] = round(time.time() - t0, 1)
    say(f"builder check passed: {res['matches']} matches, {res['jumps_builder']} jumps, coverage {res['coverage_set_identical']}")
    CTX.mkdir(parents=True, exist_ok=True)
    (CTX / "builder_check.json").write_text(json.dumps({"label": LABEL, **res}, indent=1, default=float))
    return res


# ===================================================================================== (b) U2 build
def _prestart_chunk(w: pd.DataFrame) -> pd.Series:
    return F.prestart_usd(w)


def build_u2(workers: int) -> dict:
    guard()
    assert (CTX / "builder_check.json").exists(), "run --builder-check first (PREREG section 7)"
    peek("tier0 v3 blind test (b) U2 START (scripts/tier0_v3_blind.py; PREREG research/v2/tier0_v3/PREREG.md section 4; "
         "first tier-0 table on U2: jump tables + pre-start volumes from data/expand_prints.parquet and cached raw "
         "U2 tapes, then frozen v3 once per period, seeds 2000-2019 / 3000-3019; COUNTERFACTUAL)")
    t0 = time.time()
    u = pd.read_parquet(U2_UNIVERSE)
    u["cond"] = u.cond.astype(str)
    tour = T.tournament_codes(u)                       # all 11,307 U2 rows (D5)
    w = u[u.delay == 1].reset_index(drop=True)        # tier-0 regime (PREREG section 4)
    assert len(u) == 11307 and len(w) == 10952
    chunks = [w.iloc[i::workers][["cond", "start"]] for i in range(workers)]
    with ProcessPoolExecutor(workers) as ex:
        ps = pd.concat(list(ex.map(_prestart_chunk, chunks)))
    w["prestart_usd"] = w.cond.map(ps).fillna(0.0)
    say(f"U2 pre-start volumes: {len(w)} markets, median ${w.prestart_usd.median():,.0f}, "
        f"zero for {int((w.prestart_usd <= 0).sum())} ({time.time() - t0:.0f}s)")
    P = pd.read_parquet(U2_PRINTS, columns=["cond", "ts", "p", "usd"])
    P["cond"] = P.cond.astype(str)
    P = P[P.cond.isin(set(w.cond))]
    women = pd.Series(women_label(w), index=w.cond)
    M = w[["cond", "start", "delay", "prestart_usd"]].reset_index(drop=True)
    n_tour = int(tour.max()) + 1
    info = {"universe_rows": int(len(u)), "delay1_markets": int(len(w)), "n_tour": n_tour,
            "prints_rows": int(len(P)), "matches_with_prints": int(P.cond.nunique()),
            "women_labelled": int(women.sum()), "men_mix": int((~women).sum()),
            "men_labelled": int((~women.to_numpy() & ((w.series.isin(["atp", "challenger"])) |
                                                     (w.league.fillna("") + " || " + w.title.fillna("").str.split(":").str[0])
                                                     .str.contains(MEN_LABEL_RE)).to_numpy()).sum())}
    info["unlabelled"] = info["men_mix"] - info["men_labelled"]
    cov = T.coverage_set(M, BASE.coverage, BASE.regime)
    for per, mask in (("u2_is", w.start < T.OOS_START), ("u2_oos", w.start >= T.OOS_START)):
        wp = w[mask].reset_index(drop=True)
        Pp = P[P.cond.isin(set(wp.cond))]
        J = F.jump_table(Pp, wp)
        J["men"] = ~J.cond.map(women).astype(bool)      # PREREG section 4 gender rule (U2 only)
        J = J.reset_index(drop=True)
        J["row"] = np.arange(len(J))
        J["tour"] = J.cond.map(tour).astype(int)
        J.assign(label=LABEL).to_parquet(CTX / f"{per}_jumps.parquet")
        c = F.install_context(J, M, n_tour)
        covp = cov & set(wp.cond)
        extra = {"markets": int(len(wp)), "covered_markets": int(len(covp)),
                 "covered_markets_with_prints": int(len(covp & set(Pp.cond))),
                 "covered_markets_with_jumps": int(c["Jc"].cond.nunique()), "jumps": int(len(J)),
                 "covered_jumps": int(len(c["Jc"])), "days": [str(c["days"][0].date()), str(c["days"][-1].date()), int(len(c["days"]))],
                 "matches_with_prints": int(Pp.cond.nunique())}
        save_ctx(per, c, extra)
        info[per] = extra
        say(f"{per}: {extra['markets']} markets, {extra['matches_with_prints']} with prints, {extra['jumps']} jumps; "
            f"covered {extra['covered_markets']} markets ({extra['covered_markets_with_jumps']} with jumps, "
            f"{extra['covered_jumps']} jumps), days {extra['days']} ({time.time() - t0:.0f}s)")
    M.assign(label=LABEL).to_parquet(CTX / "u2_M.parquet")
    (CTX / "u2_build.json").write_text(json.dumps({"label": LABEL, **info}, indent=1, default=float))
    return info


# ============================================================================================== runs
def job_list(name: str) -> list[tuple]:
    sb = SEED_BASE[name]
    jobs = [(cn, PRIMARY_BN, sb + k) for cn in ("frozen_v3", "frozen_v3_D2", "v2_headline") for k in range(N_SEEDS)]
    jobs += [("frozen_v3", bn, sb + k) for bn in scenarios() if bn != PRIMARY_BN for k in range(N_SEEDS)]
    return jobs


_W: dict = {}


def _init(name: str) -> None:
    load_ctx(name)
    _W["sc"] = scenarios()


def _job(args):
    cn, bn, seed = args
    c = O._C
    dr = T.draws(c["n_rows"], seed, c["n_tour"])
    calls = O.simulate_v3(_W["sc"][bn], CONFIGS[cn], dr)
    m, dv = F.metrics_test(calls, c["days"], c["J"])
    keep = None
    if cn == "frozen_v3" and bn == PRIMARY_BN:
        keep = calls[calls.shares > 1e-9][KEEP_COLS].assign(seed=seed)
    return (cn, bn, seed), m, dv.astype(np.float64), keep


def run(name: str, workers: int, part: int | None, nparts: int) -> None:
    guard()
    jobs = job_list(name)
    if part is not None:
        jobs = jobs[part::nparts]
    t0 = time.time()
    out = []
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(name,)) as ex:
        for k, r in enumerate(ex.map(_job, jobs, chunksize=4)):
            out.append(r)
            if (k + 1) % 100 == 0 or k + 1 == len(jobs):
                el = time.time() - t0
                say(f"[{name}] {k + 1}/{len(jobs)} runs, {el / 60:.1f} min, ~{el / (k + 1) * (len(jobs) - k - 1) / 60:.1f} min left")
            if k + 1 == 3 * N_SEEDS and part is None:
                prim = [m for (cn, bn, _), m, _, _ in out if cn == "frozen_v3" and bn == PRIMARY_BN]
                if prim:
                    Fm = pd.DataFrame(prim)
                    say(f"[{name}] frozen v3 primary ({len(prim)} seeds): {Fm.per_share_c.mean():.3f}c "
                        f"[match {Fm.per_share_ci95_c_lo.mean():.2f}, {Fm.per_share_ci95_c_hi.mean():.2f}] "
                        f"[day {Fm.per_share_day_ci95_c_lo.mean():.2f}, {Fm.per_share_day_ci95_c_hi.mean():.2f}] "
                        f"${Fm.pnl_per_day_usd.mean():.2f}/day, profitable days {Fm.profitable_days_pct_active.mean():.1f}%")
    PARTS.mkdir(parents=True, exist_ok=True)
    tag = f"{name}_{'all' if part is None else f'{part:03d}of{nparts:03d}'}"
    with open(PARTS / f"{tag}.pkl", "wb") as fh:
        pickle.dump(out, fh)
    say(f"[{name}] saved {len(out)} runs -> {PARTS / (tag + '.pkl')} ({(time.time() - t0) / 60:.1f} min)")


# =========================================================================================== collect
def load_runs(name: str) -> list:
    out = []
    for f in sorted(PARTS.glob(f"{name}_*.pkl")):
        with open(f, "rb") as fh:
            out += pickle.load(fh)
    keys = [r[0] for r in out]
    assert len(keys) == len(set(keys)), f"{name}: duplicate runs"
    assert set(keys) == set(job_list(name)), f"{name}: {len(set(keys))} of {len(job_list(name))} runs present"
    return out


def reading(s: dict) -> dict:
    """PREREG section 4 pass rule (same three per-share conditions for burned OOS, section 5)."""
    def gt0(x):
        return bool(x is not None and np.isfinite(x) and x > 0)
    c1, c2, c3 = gt0(s.get("per_share_c")), gt0(s.get("per_share_ci95_c_lo")), gt0(s.get("per_share_day_ci95_c_lo"))
    nm, nd = s.get("n_matches") or 0, s.get("n_trade_days") or 0
    pdays = s.get("profitable_days_pct_active")
    return {"per_share_net_gt_0": c1, "match_ci_lo_gt_0": c2, "day_ci_lo_gt_0": c3,
            "verdict": "PASS" if (c1 and c2 and c3) else "FAIL",
            "underpowered": bool(nm < MIN_MATCHES or nd < MIN_TRADE_DAYS),
            "underpowered_inputs": {"covered_matches_with_trades": nm, "trade_days": nd,
                                    "thresholds": [MIN_MATCHES, MIN_TRADE_DAYS]},
            "co_primary_profitable_days_pct_active": pdays,
            "co_primary_benchmark_gt_50pct_met": bool(pdays is not None and pdays > 50)}


def bracket_table(res: dict) -> tuple[pd.DataFrame, dict]:
    rows = []
    for bn, s in res["frozen_v3"].items():
        lag, rd, tr_, qu = bn.split("|")
        rows.append({"scenario": bn, "stamp_lag": lag[3:], "reading": rd, "trunc": tr_[5:], "queue": qu[5:],
                     "per_share_c": s.get("per_share_c"), "per_share_c_sd": s.get("per_share_c_sd"),
                     "match_ci_lo": s.get("per_share_ci95_c_lo"), "match_ci_hi": s.get("per_share_ci95_c_hi"),
                     "day_ci_lo": s.get("per_share_day_ci95_c_lo"), "day_ci_hi": s.get("per_share_day_ci95_c_hi"),
                     "pnl_usd": s.get("pnl_usd") or 0.0, "pnl_per_day_usd": s.get("pnl_per_day_usd") or 0.0,
                     "pnl_per_day_usd_sd": s.get("pnl_per_day_usd_sd"), "n_trades": s.get("n_trades"),
                     "profitable_days_pct_active": s.get("profitable_days_pct_active"), "sharpe_ann": s.get("sharpe_ann")})
    B = pd.DataFrame(rows)
    summ = {"n_scenarios": int(len(B)),
            "pnl_per_day": {k: float(getattr(B.pnl_per_day_usd, k)()) for k in ("min", "median", "max")},
            "per_share_c": {k: float(getattr(B.per_share_c.astype(float), k)()) for k in ("min", "median", "max")},
            "share_scenarios_pnl_positive": float((B.pnl_usd > 0).mean()),
            "share_scenarios_match_ci_lo_gt_0": float((B.match_ci_lo.astype(float).fillna(-1) > 0).mean()),
            "share_scenarios_day_ci_lo_gt_0": float((B.day_ci_lo.astype(float).fillna(-1) > 0).mean()),
            "by_stamp_lag_median_per_share_c": B.groupby("stamp_lag").per_share_c.median().round(4).to_dict(),
            "by_stamp_lag_median_pnl_per_day": B.groupby("stamp_lag").pnl_per_day_usd.median().round(3).to_dict(),
            "by_reading_median_per_share_c": B.groupby("reading").per_share_c.median().round(4).to_dict(),
            "by_reading_median_pnl_per_day": B.groupby("reading").pnl_per_day_usd.median().round(3).to_dict(),
            "verifier_stresses_at_lag2_tournament": {
                r.scenario: {"per_share_c": r.per_share_c, "match_ci": [r.match_ci_lo, r.match_ci_hi],
                             "day_ci": [r.day_ci_lo, r.day_ci_hi], "pnl_per_day_usd": r.pnl_per_day_usd,
                             "pnl_per_day_usd_sd": r.pnl_per_day_usd_sd}
                for r in B[(B.stamp_lag == "2") & (B.reading == "tournament")].itertuples()}}
    return B, summ


def splits(tr: pd.DataFrame, meta: pd.DataFrame, n_days: int, covered: set) -> dict:
    """U2 descriptive splits of the frozen-v3 primary trades (20 seeds): per-share net per seed (mean +/- SD),
    pooled $ per day, shares. meta: cond -> series_group, gender, region_group, fee."""
    t = tr.merge(meta, on="cond", how="left", validate="many_to_one")
    out = {}
    for dim in ("series_group", "gender_label", "region_group", "fee_rate_label"):
        d = {}
        for k, z in t.groupby(dim):
            per_seed = z.groupby("seed").apply(lambda g: g.pnl.sum() / g.shares.sum() * 100, include_groups=False)
            d[str(k)] = {"per_share_c_mean_over_seeds": float(per_seed.mean()), "per_share_c_sd": float(per_seed.std(ddof=0)),
                         "per_share_c_pooled": float(z.pnl.sum() / z.shares.sum() * 100),
                         "seeds_with_trades": int(per_seed.size),
                         "trades_per_seed": float(len(z) / N_SEEDS), "matches_per_seed": float(z.groupby("seed").cond.nunique().sum() / N_SEEDS),
                         "share_of_shares": float(z.shares.sum() / t.shares.sum()),
                         "pnl_per_day_usd": float(z.pnl.sum() / N_SEEDS / n_days)}
        out[dim] = d
    per_seed_m = t.groupby("seed").cond.nunique()
    out["share_of_covered_markets_with_any_trade"] = {
        "mean": float((per_seed_m / max(len(covered), 1)).mean()), "sd": float((per_seed_m / max(len(covered), 1)).std(ddof=0)),
        "covered_markets": int(len(covered))}
    return out


def collect() -> None:
    import subprocess
    guard()
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    gate = json.loads((CTX / "gate.json").read_text())
    bchk = json.loads((CTX / "builder_check.json").read_text())
    u2b = json.loads((CTX / "u2_build.json").read_text())
    blind = {"label": LABEL, "prereg": "research/v2/tier0_v3/PREREG.md (commit ba0c3d4)", "head": head,
             "pinned_hashes": "all 16 match PREREG.md", "frozen_v3": {"variant": FROZEN.name(), "rule": asdict(FROZEN)},
             "base_scenario": asdict(BASE), "seeds": {k: [v, v + N_SEEDS - 1] for k, v in SEED_BASE.items()},
             "reproduction_gate_burned_oos": gate, "builder_check_u1_is": bchk, "u2_build": u2b, "sets": {}}
    u2u = pd.read_parquet(U2_UNIVERSE)
    u2u["cond"] = u2u.cond.astype(str)
    meta = pd.DataFrame({"cond": u2u.cond,
                         "series_group": np.where(u2u.series == "itf", "ITF", "ATP/WTA (< $5k)"),
                         "gender_label": np.where(women_label(u2u), "women", "men's mix (men-labelled or unlabelled)"),
                         "region_group": ["unmapped (100 ms)" if T.region_of(a, b) == "unmapped" else "mapped"
                                          for a, b in zip(u2u.league, u2u.title)],
                         "fee_rate_label": u2u.fee_rate.map(lambda x: f"{x:.0%}")})
    M2 = pd.read_parquet(CTX / "u2_M.parquet")
    cov2 = T.coverage_set(M2, BASE.coverage, BASE.regime)
    daily_all = {}
    for name in ("burned_oos", "u2_is", "u2_oos"):
        d = load_ctx(name)
        c = O._C
        runs = load_runs(name)
        by = {}
        dvs = {}
        trs = []
        for (cn, bn, seed), m, dv, keep in runs:
            by.setdefault(cn, {}).setdefault(bn, []).append((seed, m, dv))
            if keep is not None:
                trs.append(keep)
        res = {}
        for cn, d1 in by.items():
            for bn, lst in d1.items():
                lst = sorted(lst, key=lambda x: x[0])
                res.setdefault(cn, {})[bn] = F.summarise([m for _, m, _ in lst], [dv for _, _, dv in lst])
                if cn == "frozen_v3" and bn == PRIMARY_BN:
                    dvs = np.vstack([dv for _, _, dv in lst])
        tr = pd.concat(trs, ignore_index=True)
        prim = res["frozen_v3"][PRIMARY_BN]
        B, bsum = bracket_table(res)
        nd = len(c["days"])
        diag = O.diagnostics(tr, nd)
        cr = tr[tr.correct]
        diag["fill_price_above_stale_plus_X_share"] = float(((cr.q > cr.q_stale + FROZEN.limit + 1e-9) * cr.shares).sum()
                                                            / cr.shares.sum()) if len(cr) else None
        sd = {"label": LABEL, "test_set": name,
              "description": {"burned_oos": "test (a): U1 1 s-delay matches with start >= 2026-08-25 14:15 UTC; burned "
                                            "OOS, non-blind window (seen by v1/v2/tier-0 v2); v3 chosen on IS only",
                              "u2_is": "test (b) U2-IS period: U2 1 s-delay markets with start < 2026-08-25 14:15 UTC "
                                       "(unseen by every tier-0 version; 'IS' is the calendar split only)",
                              "u2_oos": "test (b) U2-OOS period: U2 1 s-delay markets with start >= 2026-08-25 14:15 UTC "
                                        "(unseen by every tier-0 version)"}[name],
              "seeds": [SEED_BASE[name], SEED_BASE[name] + N_SEEDS - 1],
              "days": [str(c["days"][0].date()), str(c["days"][-1].date()), nd],
              "jumps": int(len(c["J"])), "covered_jumps": int(len(c["Jc"])), "covered_matches_with_jumps": int(c["Jc"].cond.nunique()),
              "primary": {"config": CONFIG_LABEL["frozen_v3"], "scenario": PRIMARY_BN, **prim},
              "reading": reading(prim),
              "d2_stress": {"config": CONFIG_LABEL["frozen_v3_D2"], **res["frozen_v3_D2"][PRIMARY_BN]},
              "d2_stress_reading_label_only": reading(res["frozen_v3_D2"][PRIMARY_BN]),
              "v2_headline_reference": {"config": CONFIG_LABEL["v2_headline"], **res["v2_headline"][PRIMARY_BN]},
              "bracket_frozen_v3": bsum,
              "diagnostics (by realised jump size = DIAGNOSTIC ONLY; decomposition)": diag}
        if name.startswith("u2"):
            sd["u2_period_build"] = d["extra"]
            covp = cov2 & set(c["M"][(c["M"].start < T.OOS_START) if name == "u2_is" else (c["M"].start >= T.OOS_START)].cond)
            sd["splits (descriptive; not tested)"] = splits(tr, meta, nd, covp)
        else:
            covp = T.coverage_set(c["M"], BASE.coverage, BASE.regime) & set(c["M"][c["M"].start >= T.OOS_START].cond)
            per_seed_m = tr.groupby("seed").cond.nunique()
            sd["share_of_covered_markets_with_any_trade"] = {"mean": float((per_seed_m / len(covp)).mean()),
                                                             "covered_markets": int(len(covp))}
        blind["sets"][name] = sd
        dd = pd.DataFrame(dvs.T, index=c["days"], columns=[f"seed{SEED_BASE[name] + k}" for k in range(N_SEEDS)])
        daily_all[name] = dd
        sub = OUT / ("burned_oos" if name == "burned_oos" else "u2")
        sub.mkdir(parents=True, exist_ok=True)
        dd.insert(0, "label", LABEL)
        dd.to_csv(sub / f"daily_frozen_v3_{name}.csv")
        B.insert(0, "label", LABEL)
        B.to_csv(sub / f"bracket_frozen_v3_{name}.csv", index=False)
        tr.assign(label=LABEL).to_parquet(sub / f"trades_frozen_v3_{name}.parquet")
        r = sd["reading"]
        say(f"{name}: frozen v3 {prim['per_share_c']:.3f}c ± {prim['per_share_c_sd']:.3f} [match {prim['per_share_ci95_c_lo']:.3f}, "
            f"{prim['per_share_ci95_c_hi']:.3f}] [day {prim['per_share_day_ci95_c_lo']:.3f}, {prim['per_share_day_ci95_c_hi']:.3f}] "
            f"${prim['pnl_per_day_usd']:.2f} ± {prim['pnl_per_day_usd_sd']:.2f}/day, days+ {prim['profitable_days_pct_active']:.1f}% "
            f"-> {r['verdict']}{' (underpowered)' if r['underpowered'] else ''}")
    v_is, v_oos = blind["sets"]["u2_is"]["reading"]["verdict"], blind["sets"]["u2_oos"]["reading"]["verdict"]
    blind["verdicts"] = {
        "U2 (primary, test b)": {"U2-IS period": v_is, "U2-OOS period": v_oos,
                                 "overall": "PASS" if v_is == v_oos == "PASS" else
                                 "FAIL (out-of-universe generalisation failure in: " +
                                 ", ".join(p for p, v in (("U2-IS", v_is), ("U2-OOS", v_oos)) if v != "PASS") + ")"},
        "burned OOS (test a; non-blind, cannot by itself confirm v3)": blind["sets"]["burned_oos"]["reading"]["verdict"],
        "forward (test c)": "not run here (scripts/tier0_v3_forward.py, not before 2026-10-04 11:30 UTC)"}
    (OUT / "blind.json").write_text(json.dumps(blind, indent=1, default=float))
    (OUT / "burned_oos" / "results.json").write_text(json.dumps(
        {k: v for k, v in blind.items() if k not in ("sets", "u2_build", "builder_check_u1_is")} |
        {"burned_oos": blind["sets"]["burned_oos"]}, indent=1, default=float))
    (OUT / "u2" / "results.json").write_text(json.dumps(
        {k: v for k, v in blind.items() if k not in ("sets", "reproduction_gate_burned_oos")} |
        {"u2_is": blind["sets"]["u2_is"], "u2_oos": blind["sets"]["u2_oos"]}, indent=1, default=float))
    figure(daily_all)
    done = any("tier0 v3 blind tests (a)+(b) DONE" in ln for ln in LOG.read_text().splitlines())
    peek(f"tier0 v3 blind tests (a)+(b) {'RE-COLLECT of the saved runs (no new simulation; same numbers)' if done else 'DONE'}: burned OOS {blind['verdicts']['burned OOS (test a; non-blind, cannot by itself confirm v3)']}, "
         f"U2-IS {v_is}, U2-OOS {v_oos} -> results/tier0_v3/blind.json")
    say(json.dumps(blind["verdicts"]))


def figure(daily: dict) -> None:
    """Cumulative P&L, 20-seed mean with the seeds' 10th-90th percentile band. Colour follows the calendar period
    (blue = before the 2026-08-25 14:15 UTC split, orange = after), panels follow the universe; separate $ scales."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import textwrap
    pd.plotting.register_matplotlib_converters()
    ink, ink2, gridc, surf = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    pre, post = "#2a78d6", "#eb6834"          # reference categorical slots 1-2 (validated pair)
    st = pd.read_csv(OUT / "is/stitched_daily.csv", index_col=0, parse_dates=True)
    S = st[[k for k in st.columns if k.startswith("seed")]]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.9), gridspec_kw={"width_ratios": [1.15, 1]})
    fig.patch.set_facecolor(surf)

    def seeds(D):
        return D[[k for k in D.columns if str(k).startswith("seed")]]

    def money(x, nd=0):
        return ("\u2212" if x < 0 else "+") + f"${abs(x):,.{nd}f}"

    def band(ax, D, col, lab, offset=0.0, nd=0):
        E = D.cumsum() + offset
        ax.fill_between(E.index, E.quantile(0.1, axis=1), E.quantile(0.9, axis=1), color=col, alpha=0.14, lw=0)
        mu = E.mean(axis=1)
        ax.plot(E.index, mu, color=col, lw=2.0, solid_capstyle="round",
                label=f"{lab}: {money(float(D.sum().mean()), nd)} in the period")
        return mu

    ax = axes[0]
    e_is = band(ax, S, pre, "IS, v3 stitched walk-forward")
    band(ax, seeds(daily["burned_oos"]), post, "burned OOS (non-blind window), frozen v3", offset=float(e_is.iloc[-1]))
    ax.set_title("U1: ATP/WTA moneylines \u2265 $5k, 10 cameras/day", loc="left", color=ink, fontsize=10.5)
    ax2 = axes[1]
    e1 = band(ax2, seeds(daily["u2_is"]), pre, "U2-IS period, frozen v3", nd=2)
    band(ax2, seeds(daily["u2_oos"]), post, "U2-OOS period, frozen v3", offset=float(e1.iloc[-1]), nd=2)
    ax2.set_title("U2: 10,952 unseen 1 s-delay markets (mostly ITF, median volume $4.4k)", loc="left", color=ink,
                  fontsize=10.5)
    for a in axes:
        a.set_facecolor(surf)
        a.axhline(0, color=gridc, lw=1)
        a.axvline(T.OOS_START, color=gridc, lw=1, ls="--")
        a.grid(axis="y", color=gridc, lw=0.6)
        for sp in ("top", "right"):
            a.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            a.spines[sp].set_color(gridc)
        a.xaxis.set_major_locator(mdates.MonthLocator())
        a.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        a.legend(frameon=False, fontsize=8, loc="upper left")
        a.tick_params(colors=ink2, labelsize=8.5)
        a.margins(x=0.03)
    axes[0].set_ylabel("cumulative P&L, $ (20-seed mean; band = seeds' 10th-90th pct)", fontsize=8.5, color=ink2)
    fig.suptitle("Tier-0 v3 frozen rule (θ 0.90 · hold · leverage sizing · zone [0.05, 0.95] · limit stale + 2c): "
                 "cumulative P&L", x=0.01, ha="left", color=ink, fontsize=11.5)
    fig.text(0.01, 0.01, "\n".join(textwrap.wrap(
        LABEL + " The two panels use different $ scales: U2 depth is scaled by min(1, V/V_live), so U2 fills are a few "
        "shares. Dashed line = 2026-08-25 14:15 UTC split.", 200)), color=ink2, fontsize=7)
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    fig.savefig(OUT / "equity_is_oos_u2.png", dpi=160)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--oos-gate", action="store_true")
    ap.add_argument("--builder-check", action="store_true")
    ap.add_argument("--build-u2", action="store_true")
    ap.add_argument("--run", choices=list(SEED_BASE))
    ap.add_argument("--part", type=int, default=None)
    ap.add_argument("--nparts", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--time", choices=list(SEED_BASE))
    a = ap.parse_args()
    if a.oos_gate:
        oos_gate()
    elif a.builder_check:
        builder_check()
    elif a.build_u2:
        build_u2(min(a.workers, 3))
    elif a.run:
        run(a.run, a.workers, a.part, a.nparts)
    elif a.collect:
        collect()
    elif a.time:
        _init(a.time)
        for cn, bn in (("frozen_v3", PRIMARY_BN), ("v2_headline", PRIMARY_BN)):
            t0 = time.time()
            r = _job((cn, bn, SEED_BASE[a.time]))
            print(cn, f"{time.time() - t0:.2f}s")


if __name__ == "__main__":
    main()
