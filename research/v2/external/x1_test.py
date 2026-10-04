"""X1: the single predeclared out-of-universe run of the frozen corrected v2 copier.

Contract: research/v2/external/PREREG_EXTERNAL.md (committed with this file, before any X1 tape was fetched).

    .venv/bin/python research/v2/external/x1_test.py              # THE run: universe check, fetch, build, evaluate
    .venv/bin/python research/v2/external/x1_test.py --selftest --out <path>
        # plumbing check on U1 in-sample prints only (stand-in "window" = U1 IS matches starting on or after
        # 2026-07-18 18:00 UTC); reads no X1 tape, no X1 resolution and no held-out file; writes no log line

The run writes one START line to results/oos_peeks.log before the first X1 fetch, one END line after
results/external_validation/results.json is written, and refuses to run again once that file exists
(a byte-identical rerun is a reproduction: --reproduction, logged as such, output to a separate file).
No parameter, threshold, rule, latency or sizing setting is chosen here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore", category=RuntimeWarning)

import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from src import polymarket as pm, tiers, v2  # noqa: E402
from src.tape import universe  # noqa: E402
from src.tiers import add_causal_bucket  # noqa: E402

SCHEMA = "courtside.external.x1/1"
CATALOGUE = Path("data/raw/events_tennis_2025-07-01_2026-10-03.parquet")
CATALOGUE_SHA = "03986becf3cfd0ce22ed8e65c0dd9bbd0a684f621e744d53aa742eebd534cfd5"
FETCHED_DIR = Path("data/raw/trades")
FETCHED_N, FETCHED_SHA = 28075, "4b12de915631b8ed4aa4b5b96fd8e4f3e8c3df3f72479bf74f3f5d6d67274ada"
X1_RAW = Path("data/external_x1/raw")          # X1 tapes; data/raw/trades (the pinned snapshot) is left unchanged
X1_PRINTS = Path("data/external_x1/x1_prints.parquet")
MIN_VOL = 5_000                                 # src/tape.py MIN_VOL
META_COLS = ["slug", "title", "series", "league", "start_time", "finished", "closed_time", "cond", "tok0", "tok1",
             "volume", "seconds_delay", "fee_rate", "event_id", "game_id"]   # no score, res0, out0, out1
EXPECT = {"n_x1": 767, "first": "2025-09-19 06:00:00+00:00", "last": "2026-10-02 09:00:00+00:00",
          "days": 378.125, "cut": "2026-07-18 18:00:00+00:00", "n_window": 108,
          "series": {"atp-doubles": 51, "wta-doubles": 39, "daviscup-games": 18}, "start_days": 43,
          "window_sha": "2eceed5ee9f9d6826022928059f2b1b155456826ac277ba777a76c3bdd2f021e"}
WORKERS = 4                                     # at most 4 concurrent HTTP requests
FETCH_CAP_ROWS = 10_000                         # tapes this long may be truncated by the data-api offset cap
MIN_MATCHES, MIN_DAYS = 30, 20                  # underpowered label (never changes the verdict)
SLIPS = (0.005, 0.01)                           # entry slippage on the central book, $ per share
OUT = Path("results/external_validation/results.json")
OOS_LOG = Path("results/oos_peeks.log")
FROZEN_FILES = ("src/v2.py", "src/tiers.py", "src/tape.py", "src/polymarket.py", "src/fasttier.py",
                "research/v2/sizing/engine.py", "results/decay/decay.json",
                "research/v2/external/x1_test.py", "research/v2/external/PREREG_EXTERNAL.md")
KEEP = ("n_trades", "n_matches", "c_share", "c_share_ci95", "per_share_c", "per_share_ci_c", "total_pnl_usd",
        "total_pnl_ci_usd", "usd_traded", "usd_day", "sharpe", "ret_ann", "vol_ann", "capital_usd",
        "peak_locked_usd", "max_dd_usd", "max_dd_pct", "worst_day_usd", "worst_day_pct", "turnover_x",
        "months_positive", "months_total", "days")


def H(ids) -> str:
    """sha256 of "\\n".join(sorted(ids)), no trailing newline (the plan's hash convention)."""
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def git(*a: str) -> str:
    return subprocess.run(["git", *a], capture_output=True, text=True, cwd=ROOT).stdout.strip()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def log_line(text: str, repro: bool) -> str:
    t = now()
    path = Path("results/repro/reads.log") if os.environ.get("COURTSIDE_REPRO") == "1" else OOS_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(f"{t} {'REPRODUCTION ' if repro else ''}{text}\n")
    return t


def pick(m: dict) -> dict:
    return {k: m[k] for k in KEEP if k in m}


# ------------------------------------------------------------------------------- universe (metadata only)
def x1_universe() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    assert sha_file(CATALOGUE) == CATALOGUE_SHA, "catalogue changed"
    ev = pd.read_parquet(CATALOGUE, columns=META_COLS)
    fetched = sorted(f.stem for f in FETCHED_DIR.glob("*.parquet"))
    assert (len(fetched), H(fetched)) == (FETCHED_N, FETCHED_SHA), ("fetched list changed", len(fetched))
    u1 = set(gzip.open("results/universe_conds.txt.gz", "rt").read().split())
    u2 = set(pd.read_parquet("data/expand_universe.parquet", columns=["cond"]).cond)
    m = (~ev.cond.isin(set(fetched)) & ~ev.cond.isin(u1) & ~ev.cond.isin(u2)
         & (ev.volume >= MIN_VOL) & ev.start_time.notna())
    x = ev[m].copy()
    x["start"] = pd.to_datetime(x.start_time, utc=True, format="ISO8601")
    first, last = x.start.min(), x.start.max()
    cut = first + 0.8 * (last - first)
    w = x[x.start >= cut].copy()
    got = {"n_x1": len(x), "first": str(first), "last": str(last), "days": (last - first) / pd.Timedelta(days=1),
           "cut": str(cut), "n_window": len(w), "series": w.series.value_counts().to_dict(),
           "start_days": int(w.start.dt.floor("D").nunique()), "window_sha": H(w.cond)}
    assert got == EXPECT, (got, EXPECT)
    assert w.cond.is_unique and (w.seconds_delay == 1).all() and (w.fee_rate == 0.05).all()
    # prepared as in src.tape.universe()
    w["end"] = pd.to_datetime(w.finished.fillna(w.closed_time), utc=True, format="mixed")
    w["fee_rate"] = w.fee_rate.fillna(0.0)
    w["delay"] = w.seconds_delay.fillna(1).astype(int)
    w = w.sort_values("start", kind="stable").reset_index(drop=True)
    return x, w, got


# ------------------------------------------------------------------------------- data build
def fetch(w: pd.DataFrame) -> dict:
    pm.RAW = X1_RAW
    pm.fetch_many_trades(w.cond.tolist(), workers=WORKERS)
    have = {f.stem for f in (X1_RAW / "trades").glob("*.parquet")}
    miss = sorted(c for c in w.cond if c not in have)
    return {"n_requested": len(w), "n_fetched": len(w) - len(miss), "failed": miss}


def build(w: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Per-print tables with src.tiers.match_prints (which also writes its usual per-print markout columns).
    res0 is read here, after the freeze commit, for the window markets only."""
    pm.RAW = X1_RAW
    res = pd.read_parquet(CATALOGUE, columns=["cond", "res0"]).set_index("cond").res0
    w = w.assign(res0=w.cond.map(res))
    tapes, n_rows = {}, {}
    for c in w.cond:
        f = X1_RAW / "trades" / f"{c}.parquet"
        if f.exists():
            tapes[c] = sha_file(f)
            n_rows[c] = pq.ParquetFile(f).metadata.num_rows
    no_tape = [c for c in w.cond if c not in tapes]
    bad_res = sorted(w.loc[w.cond.isin(tapes) & ~w.res0.isin([0.0, 0.5, 1.0]), "cond"])
    rows = w[w.cond.isin(tapes) & w.res0.isin([0.0, 0.5, 1.0])]
    parts, few, raised = [], [], []
    for r in rows[["cond", "start", "end", "res0", "fee_rate", "delay"]].to_dict("records"):
        try:   # as the U1 and U2 builders (src/prints.py::_one, build_u2.py::_one): a market whose build raises is dropped
            d = tiers.match_prints(SimpleNamespace(**r))
        except Exception:
            raised.append(r["cond"])
            continue
        (parts.append(d) if d is not None else few.append(r["cond"]))
    P = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    X1_PRINTS.parent.mkdir(parents=True, exist_ok=True)
    P.to_parquet(X1_PRINTS)
    kept = sorted(set(P.cond)) if len(P) else []
    info = {"n_window": len(w), "n_no_tape": len(no_tape), "no_tape": no_tape,
            "n_resolution_not_0_half_1": len(bad_res), "resolution_not_0_half_1": bad_res,
            "n_empty_tape_or_lt20_inplay_prints": len(few), "empty_tape_or_lt20_inplay_prints": sorted(few),
            "n_match_prints_raised": len(raised), "match_prints_raised": sorted(raised),
            "match_prints_raised_note": "dropped as in the U1/U2 builders (e.g. >= 20 in-play prints but no jump "
                                        "detection, where src.tiers.match_prints indexes an empty onset array); "
                                        "see research/v2/external/DEVIATIONS.md D1",
            "n_matches_with_prints": len(kept), "n_print_rows": int(len(P)),
            "n_tapes_ge_10000_rows_possibly_truncated": int(sum(v >= FETCH_CAP_ROWS for v in n_rows.values())),
            "tape_rows_total": int(sum(n_rows.values())),
            "prints_sha256": sha_file(X1_PRINTS), "prints_path": str(X1_PRINTS),
            "tape_sha256": dict(sorted(tapes.items())),
            "kept_cond_sha256": H(kept),
            "resolution_counts_kept": {str(k): int(v) for k, v in
                                       w[w.cond.isin(kept)].res0.value_counts().sort_index().items()}}
    return P, w, info


def x1_tape(cond: str):
    """src.tape.load_tape on the X1 tape directory."""
    from src.tape import load_tape
    pm.RAW = X1_RAW
    return load_tape(cond)


# ------------------------------------------------------------------------------- evaluation
def evaluate(P: pd.DataFrame, ends: pd.Series, window: pd.DataFrame, lat: dict, tape_loader) -> dict:
    wc = set(window.cond)
    P = add_causal_bucket(P)
    P = v2.strict_causal_bucket(P)                       # order_col=None: the whole detection second is excluded
    print("labels done", flush=True)
    tr, wf = v2.run(P, ends, causal=True, strict=True)   # POLICY G_50pct_net100; wallets from months < m only
    assert (tr.ts > tr.det_ts_s).all(), "a strict trade sits at or before its detection second"
    A = tr[(tr.month >= v2.E.EVAL_START) & tr.cond.isin(wc)].copy()
    print(f"window trades attempted: {len(A)}", flush=True)
    A = A.join(v2.copier_reprice(A, window.set_index("cond"), lat, tape_loader=tape_loader))
    out = {"copier": {}}
    for r, spec in v2.COPIER_RULES.items():
        b = v2.copier_book(A, r)
        m = v2.table1_metrics(b)
        out["copier"][r] = {"what": spec["what"], **pick(m),
                            "n_attempted_trades": int(len(A)), "n_unsupported_fills": int(len(A) - len(b)),
                            "share_beyond_tape_end": float(A[f"beyond_{r}"].mean()) if len(A) else None,
                            "share_same_side_print": float(b[f"same_{r}"].mean()) if len(b) else None,
                            "trade_days": int(b.date.nunique()) if len(b) else 0}
    out["copier"]["optimistic"]["label"] = "upper bound: may use the fast wallet's own fill; not attainable in general"
    central = v2.copier_book(A, "central")
    out["central_slippage"] = {}
    for s in SLIPS:
        bs = central.assign(pnl_ps=central.pnl_ps - s)
        out["central_slippage"][f"plus_{s * 100:g}c"] = pick(v2.table1_metrics(bs))
    out["central_by_series"] = {}
    ser = window.set_index("cond").series
    for name, sel in (("doubles", central.cond.map(ser).str.contains("doubles")),
                      ("daviscup", central.cond.map(ser).eq("daviscup-games"))):
        out["central_by_series"][name] = pick(v2.table1_metrics(central[sel.fillna(False)]))
    out["event_study_fast_fills"] = {"label": "observational: the strict book at the fast tier's own fills; a copier "
                                              "cannot get these prices", **pick(v2.table1_metrics(A))}
    # provenance (not a return): wallets seen in P in months before the market's month
    P_month = pd.to_datetime(P.ts, unit="s", utc=True).dt.strftime("%Y-%m")
    first_month = pd.DataFrame({"wallet": P.wallet, "m": P_month}).groupby("wallet").m.min()
    mk_month = window.set_index("cond").start.dt.strftime("%Y-%m")
    xp = P[P.cond.isin(wc)]
    seen_p = xp.wallet.map(first_month) < xp.cond.map(mk_month)
    seen_t = A.wallet.map(first_month) < A.cond.map(mk_month) if len(A) else pd.Series(dtype=bool)
    out["wallet_overlap"] = {
        "share_x1_inplay_prints_wallet_in_P_before_market_month": float(seen_p.mean()) if len(xp) else None,
        "n_x1_inplay_prints": int(len(xp)),
        "share_copier_trigger_prints_wallet_in_P_before_market_month": float(seen_t.mean()) if len(A) else None,
        "n_copier_trigger_prints": int(len(A))}
    out["n_wallets_by_month_strict"] = {str(k): int(v) for k, v in zip(wf.month, wf.n_wallets)}
    c = out["copier"]["central"]
    ci = c.get("c_share_ci95")
    out["verdict"] = "PASS" if (c.get("n_trades") and ci is not None and ci[0] > 0) else "FAIL"
    n_m, n_d = c.get("n_matches", 0) or 0, c.get("trade_days", 0)
    out["underpowered"] = bool(n_m < MIN_MATCHES or n_d < MIN_DAYS)
    out["underpowered_rule"] = (f"fewer than {MIN_MATCHES} X1 matches with central copier trades ({n_m}) or fewer "
                                f"than {MIN_DAYS} trade days ({n_d}); reported alongside the verdict, never changes it")
    return out


def latency() -> tuple[dict, dict]:
    li = json.loads(Path("results/decay/decay.json").read_text())["latency_inputs"]
    blk = li["block_lag_s"]
    lat = {"median": float(blk["median"]), "p90": float(blk["p90"]), "net_s": float(li["net_florida_s"])}
    return lat, {**lat, "n_block_lag": blk["n"], "decay_json_sha256": sha_file(Path("results/decay/decay.json"))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--reproduction", action="store_true", help="rerun after results.json exists (logged as such)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    lat, lat_rec = latency()

    if a.selftest:
        assert a.out and not Path(a.out).resolve().is_relative_to((ROOT / "results").resolve()), \
            "--selftest needs --out outside results/"
        u = universe()
        win = u[(~u.oos) & (u.start >= pd.Timestamp(EXPECT["cut"]))].copy()
        P = pd.read_parquet("data/is_prints.parquet")
        P = P[P.cond.isin(set(u.loc[~u.oos, "cond"]))]
        from src.tape import load_tape
        r = evaluate(P, u.set_index("cond").end, win, lat, lambda c: load_tape(c))
        r = {"selftest": "U1 in-sample stand-in window; not an X1 result", "n_window": len(win), **r}
        Path(a.out).write_text(json.dumps(r, indent=2, default=float))
        print(f"selftest wrote {a.out}", flush=True)
        return

    out_path = OUT
    if OUT.exists():
        if not a.reproduction:
            sys.exit(f"{OUT} exists: X1 is evaluated once (use --reproduction for a logged reproduction)")
        out_path = OUT.with_name("results_reproduction.json")
    dirty = git("status", "--porcelain", "--", *FROZEN_FILES)
    assert not dirty, f"frozen files differ from the commit:\n{dirty}"
    head = git("rev-parse", "HEAD")
    x, w, meta = x1_universe()
    t_start = log_line(f"x1_test.py (HEAD {head[:7]}) START: X1 out-of-universe check of the frozen corrected v2 "
                       f"copier (research/v2/external/PREREG_EXTERNAL.md): fetch of the {len(w)} never-fetched X1 "
                       "window tapes, print build (first read of X1 resolutions) and the single evaluation; reads "
                       "data/is_prints.parquet and data/locked/oos_prints.parquet (U1 OOS, non-blind) as input to "
                       "X1 wallet qualification only; U1 trades regenerated by the run are not inspected or reported",
                       a.reproduction)
    print("START", t_start, flush=True)
    fetch_info = fetch(w)
    print("fetch", {k: v for k, v in fetch_info.items() if k != "failed"}, flush=True)
    X, w, build_info = build(w)
    print("build", {k: v for k, v in build_info.items() if not isinstance(v, (list, dict))}, flush=True)
    u1 = universe()
    parts = [pd.read_parquet("data/is_prints.parquet"), pd.read_parquet("data/locked/oos_prints.parquet")]
    c1 = set(parts[0].cond) | set(parts[1].cond)
    assert not c1 & set(w.cond)
    if len(X):
        X = X[parts[0].columns.intersection(X.columns)]
        parts.append(X)
    P = pd.concat(parts, ignore_index=True)       # no dedup (identical rows are distinct fills)
    ends = pd.concat([u1.set_index("cond").end, w.set_index("cond").end])
    print(f"prints {len(P):,}", flush=True)
    win = w[w.cond.isin(set(X.cond))] if len(X) else w.iloc[0:0]
    res = evaluate(P, ends, win, lat, x1_tape) if len(win) else {
        "copier": {"central": {"n_trades": 0}}, "verdict": "FAIL", "underpowered": True}
    out = {
        "schema": SCHEMA,
        "generated_utc": now(),
        "git_head": head,
        "prereg": "research/v2/external/PREREG_EXTERNAL.md",
        "prereg_commit": git("log", "-1", "--format=%h", "--", "research/v2/external/PREREG_EXTERNAL.md"),
        "reproduction": bool(a.reproduction),
        "log_start_utc": t_start,
        "primary": {"metric": "central copier net per-share P&L held to resolution (c_share, c_share_ci95; "
                              "share-weighted, match-clustered bootstrap, 1,000 draws, seed 0)",
                    "rule": "PASS only if the 95% CI lower bound > 0; otherwise FAIL",
                    "verdict": res["verdict"], "underpowered": res["underpowered"],
                    "c_share": res["copier"]["central"].get("c_share"),
                    "c_share_ci95": res["copier"]["central"].get("c_share_ci95"),
                    "n_trades": res["copier"]["central"].get("n_trades"),
                    "n_matches": res["copier"]["central"].get("n_matches"),
                    "trade_days": res["copier"]["central"].get("trade_days")},
        "universe": meta,
        "fetch": fetch_info,
        "build": build_info,
        "latency_inputs": lat_rec,
        "frozen_file_sha256": {f: sha_file(Path(f)) for f in FROZEN_FILES},
        "labels": {"status": "prospective, predeclared out-of-universe check (X1); NOT the organizer's "
                             "latest-20%-by-time OOS test of the declared universe",
                   "camera": "not tested on X1 (see the pre-registration)"},
        **res,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=float))
    t_end = log_line(f"x1_test.py (HEAD {head[:7]}) END: {out_path} written (X1 single evaluation; verdict "
                     f"{res['verdict']}{', underpowered' if res['underpowered'] else ''})", a.reproduction)
    print("END", t_end, "wrote", out_path, flush=True)


if __name__ == "__main__":
    main()
