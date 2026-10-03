"""(A) maker v1 blind OOS test (PREREG.md sections 2.3-2.9): parity on IS, then ONE run on OOS.

  parity  The OOS code path below must reproduce the IS cell (always, 0.04), months >= 2026-02, on the IS
          per-print table with the IS walk-forward b and the IS model choice by month:
          n = 10,171 fills and $5,326.05 (rel tol 1e-6). Also checks the IS 1s/5% diagnostics, the frozen
          b_T table (sha256 and equality with the walk-forward 2026-08 row) and the frozen code hashes.
          IS data only. Writes research/v2/maker/oos/parity.json.
  istest  Runs the whole evaluation (book, stresses, diagnostics) on IS with the IS walk-forward b, as a code
          test before the single OOS run. IS data only; reported as an IS reference, never as OOS.
  run     Appends the peeks line to results/oos_peeks.log FIRST, then builds the OOS book (frozen b_T,
          lambda = 1.0) and writes research/v2/maker/oos/ (results.json, books, tables) and results/maker/oos.json.
          Refuses to run a second time (see DEVIATIONS.md for the re-run rule).

Paper only: no order is signed or sent; no key is used. Market data: public Polymarket endpoints (cached).
  reproduce  Recomputes the committed OOS numbers from the cached data and compares (logs its own peeks line).
Run from the repo root:  .venv/bin/python research/v2/maker/oos_test.py {parity|istest|run|reproduce}
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CM = ROOT / "research" / "v2" / "crossmarket"
sys.path.insert(0, str(CM))
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import analyze  # noqa: E402  (frozen IS code; imported, not changed)
import model  # noqa: E402
from common import OOS_CUT, month_of, regime, taker_fee  # noqa: E402
from src.backtest import stats  # noqa: E402

OUT = HERE / "oos"
OOS_CACHE = ROOT / "data" / "v2_maker" / "oos"
PEEKS = ROOT / "results" / "oos_peeks.log"
RESULTS_COPY = ROOT / "results" / "maker" / "oos.json"
PEEK_LINE = ("maker v1 blind OOS evaluated (first run) (PREREG research/v2/maker/PREREG.md (A); first use of OOS "
             "side-market tapes; burned OOS moneyline tapes used only as the signal input)")

# ------------------------------------------------------------------ frozen rule (PREREG section 1)
B_T = {
    "tennis_first_set_winner": 1.527875991592811,
    "tennis_set_winner": 1.0781295500280448,
    "tennis_set_handicap": 0.8171462571666066,
    "tennis_match_totals": 1.8243248664803704,
    "tennis_set_totals": 2.721259317541827,
    "tennis_first_set_totals": 3.514143233195978,
}
B_SHA = "f40c53f741d23fc911cfb42857af4b59d5c22cc54efa7fbfcc27d57fbd18466c"
CODE_SHA = {
    "research/v2/crossmarket/analyze.py": "3138af84d0be171c54082956d15f0669754f018223cd04364d80bb6d08a11bb4",
    "research/v2/crossmarket/model.py": "e7b091a941fbb9daa3a6eac19057fdd5dc27808617e5fc0203a30e2bec872f59",
    "research/v2/crossmarket/common.py": "20ca19acc8773cede70c8b63f2c68377de246476234c093e524d64fa2c8df115",
    "research/v2/crossmarket/build.py": "151202928d84a1e3308f7c3f695eded3e37abfeff53e5610f557162e0cf2644d",
    "research/v2/crossmarket/fetch_events.py": "85881cfbb4fc83562b400ef6a68dd11a424864613dd14ed70ac05a687c366275",
    "research/v2/crossmarket/beta_walkforward.csv": "df9196cc3fe7c5cdf97e1078a2921fa79212f5e0e13c2be70dc85ce8dd8dd99d",
    "src/tiers.py": "46a79d75409fd416fdfc2e026c25f02d9ebb3a188a9de1a6ac353561f656363e",
    "src/backtest.py": "dbf82b752942dcff7ba3e0d1fcde2603894d6066938ca1476e8b8f1467a98b46",
}
LAM = 1.0
MIN_IMPL = 0.04
MAX_REF_AGE = 600
SHARE, SHARE_STRESS = 0.2, 0.1
MAX_FILL, MAX_MATCH = 250.0, 2_000.0
REBATE = 0.15
LO, HI = 0.02, 0.98
TT_MAX_AGE = 120
FIRST_EVAL = "2026-02"
IS_TARGET = {"n": 10_171, "pnl_usd": 5326.053215035456}
IS_1S5 = {"net_c": 2.01667311588643, "ci": [0.525350871768348, 3.4842750187222]}
IS_DIAG_1S5 = {"unconditional": (36355, -0.12477008644896942), "anti_lean": (4674, -1.289634795809543)}
N_BOOT, SEED = 2000, 0
PARTIAL = {"2026-08": "partial (Aug 25-31)", "2026-10": "partial (Oct 1-3)"}


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_frozen() -> dict:
    got = {f: sha_file(ROOT / f) for f in CODE_SHA}
    bad = [f for f in CODE_SHA if got[f] != CODE_SHA[f]]
    assert not bad, f"frozen file changed: {bad}"
    bsha = hashlib.sha256(json.dumps({k: repr(v) for k, v in B_T.items()}, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
    assert bsha == B_SHA, "frozen b_T table does not match its pre-registered sha256"
    return {"code_sha256_ok": True, "b_T_sha256": bsha}


# ------------------------------------------------------------------ the OOS code path
def add_cols(pr: pd.DataFrame) -> pd.DataFrame:
    """The columns analyze.load() adds."""
    pr["month"] = month_of(pr.ts)
    pr["dir"] = np.where(pr.at_ask, 1.0, -1.0)
    pr["fee"] = taker_fee(pr.q0, pr.fee_rate)
    pr["regime"] = [regime(d, f) for d, f in zip(pr.delay, pr.fee_rate)]
    return pr


def tt_levels(pr: pd.DataFrame) -> pd.DataFrame:
    """Stress (ii) resting level on each token's axis: price of the market's latest in-play print on that token's
    bid side (a taker SOLD that token) with ts strictly before the information cut t_send = ts - d and
    t_send - ts <= 120 s. L0: our token = outcome 0 (taker sold outcome 0: at_ask False), on outcome 0's axis.
    L1: our token = outcome 1 (taker sold outcome 1 = bought outcome 0: at_ask True), on outcome 1's axis."""
    L0 = np.full(len(pr), np.nan)
    L1 = np.full(len(pr), np.nan)
    ts_all, q_all, aa_all, tsend_all = pr.ts.to_numpy(float), pr.q0.to_numpy(float), pr.at_ask.to_numpy(bool), pr.t_send.to_numpy(float)
    for _, idx in pr.groupby("cond", sort=False).indices.items():
        o = idx[np.argsort(ts_all[idx], kind="stable")]
        ts, q, aa, tsend = ts_all[o], q_all[o], aa_all[o], tsend_all[o]
        for mask, out, tok in ((~aa, L0, lambda x: x), (aa, L1, lambda x: 1 - x)):
            ts_s, q_s = ts[mask], q[mask]
            if len(ts_s) == 0:
                continue
            k = np.searchsorted(ts_s, tsend, "left") - 1
            kk = np.maximum(k, 0)
            ok = (k >= 0) & ((tsend - ts_s[kk]) <= TT_MAX_AGE)
            out[o] = np.where(ok, tok(q_s[kk]), np.nan)
    pr["L0"], pr["L1"] = L0, L1
    return pr


def candidates(pr: pd.DataFrame) -> pd.DataFrame:
    """analyze.lean_maker's signal: implied side move from information strictly before t_send (PREREG 1.4)."""
    c = pr.dropna(subset=["b", "q_rs", "p_rs", "p_send", "res_s0"]).copy()
    c = c[(c.t_send - c.ts_rs) <= MAX_REF_AGE]
    q_imp = model.implied_q0(c.q_rs, c.p_rs, c.p_send, c.smt.to_numpy(), c.align0.to_numpy(), c.b_rs.to_numpy())
    c["impl"] = q_imp - c.q_rs
    c["idir"] = np.sign(c.impl)
    return c


def lean_book(c: pd.DataFrame, share: float = SHARE, rebate: bool = True, trade_through: bool = False,
              maker_fee: bool = False) -> pd.DataFrame:
    """Maker v1 fills (PREREG 1.5-1.6) and the stresses of 2.7 / 2.9 (one switch each)."""
    f = c[(c.dir == -c.idir) & (c.impl.abs() >= MIN_IMPL)]
    tok_px = np.where(f.idir > 0, f.q0, 1 - f.q0)          # the print's price on our token
    if trade_through:
        L = np.where(f.idir > 0, f.L0, f.L1)
        ok = np.isfinite(L) & (tok_px < L) & (L > LO) & (L < HI)
        px = L
    else:
        ok = (tok_px > LO) & (tok_px < HI)
        px = tok_px
    f = f[ok].assign(px=px[ok]).sort_values("ts", kind="stable")
    sh = np.minimum(share * f["size"], MAX_FILL / f.px)
    usd = sh * f.px
    keep = usd.groupby(f.event_id).cumsum() <= MAX_MATCH
    f, sh, usd = f[keep], sh[keep], usd[keep]
    payout = np.where(f.idir > 0, f.res_s0, 1 - f.res_s0)
    if rebate:
        reb = REBATE * taker_fee(f.px if trade_through else f.q0, f.fee_rate)
    else:
        reb = np.zeros(len(f))
    mfee = (f.maker_base_fee / 10_000.0) * f.px * (1 - f.px) if maker_fee else np.zeros(len(f))
    b = pd.DataFrame({"cond": f.event_id, "pnl_ps": payout - f.px + reb - mfee, "fee": -reb + mfee, "usd_in": usd,
                      "exit": "resolution", "date": pd.to_datetime(f.ts, unit="s", utc=True).dt.floor("D"),
                      "shares": sh, "month": f.month, "regime": f.regime, "smt": f.smt, "ts": f.ts,
                      "market": f.cond, "px": f.px, "payout": payout, "rebate": reb, "maker_fee": mfee,
                      "impl": f.impl, "q0_print": f.q0, "print_size": f["size"]})
    b["pnl"] = b.shares * b.pnl_ps
    return b


def diagnostics(c: pd.DataFrame) -> list[dict]:
    """The two IS placebos exactly as analyze.lean_diagnostics computes them (per print, no sizing or cap)."""
    rows = []
    for name, f in (("unconditional maker (every print, both sides, no lean)", c),
                    ("anti-lean placebo (filled by takers trading WITH the implied move, |impl| >= 0.04)",
                     c[(c.dir == c.idir) & (c.impl.abs() >= MIN_IMPL)])):
        long0 = ~f.at_ask.to_numpy()
        px = np.where(long0, f.q0, 1 - f.q0)
        ok = (px > LO) & (px < HI)
        f, px, long0 = f[ok], px[ok], long0[ok]
        payout = np.where(long0, f.res_s0, 1 - f.res_s0)
        g = f.assign(pnl_ps=payout - px + REBATE * taker_fee(f.q0, f.fee_rate))
        for rg, gg in [("all", g)] + list(g.groupby("regime")):
            lo, hi = analyze.boot_ci(gg, "pnl_ps")
            rows.append({"book": name, "regime": rg, "n": int(len(gg)), "matches": int(gg.event_id.nunique()),
                         "net_c": float(gg.pnl_ps.mean() * 100), "ci": [lo * 100, hi * 100],
                         "share_w_net_c": float((gg.pnl_ps * gg["size"]).sum() / gg["size"].sum() * 100)})
    return rows


# ------------------------------------------------------------------ reporting
def cut(g: pd.DataFrame) -> dict:
    lo, hi = analyze.boot_ci(g.assign(event_id=g.cond), "pnl_ps")
    slo, shi = analyze.boot_ci(g.assign(event_id=g.cond), "pnl_ps", w="shares")
    return {"n": int(len(g)), "matches": int(g.cond.nunique()), "net_c": float(g.pnl_ps.mean() * 100),
            "ci": [lo * 100, hi * 100], "share_w_net_c": float(g.pnl.sum() / g.shares.sum() * 100),
            "share_w_ci": [slo * 100, shi * 100], "pnl_usd": float(g.pnl.sum()), "usd_in": float(g.usd_in.sum()),
            "hit_rate": float((g.pnl_ps > 0).mean())}


def headline(book: pd.DataFrame, ends: pd.Series, partial: dict = PARTIAL) -> dict:
    if book.empty:
        return {"n_trades": 0}
    cap = analyze.capital_for(book, ends)
    st = stats(book, n_boot=N_BOOT, seed=SEED, capital=cap)
    daily = book.groupby("date").pnl.sum()
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC")
    daily = daily.reindex(idx, fill_value=0.0)
    eq = cap + daily.cumsum()
    lo, hi = analyze.boot_ci(book.assign(event_id=book.cond), "pnl_ps", w="shares")
    st.update({
        "share_weighted_net_c": float(book.pnl.sum() / book.shares.sum() * 100), "share_weighted_ci": [lo * 100, hi * 100],
        "notional_usd": float(book.usd_in.sum()), "mean_fill_usd": float(book.usd_in.mean()),
        "median_fill_usd": float(book.usd_in.median()), "max_dd_usd": float((eq - eq.cummax()).min()),
        "max_dd_pct_capital": float(st["max_dd"] * 100), "worst_day_usd": float(daily.min()),
        "first_fill_utc": str(pd.to_datetime(book.ts.min(), unit="s", utc=True)),
        "last_fill_utc": str(pd.to_datetime(book.ts.max(), unit="s", utc=True)),
    })
    mon = []
    for m, g in book.groupby("month"):
        mon.append({"month": m, "label": partial.get(m, "full"), "n": int(len(g)), "matches": int(g.cond.nunique()),
                    "net_c": float(g.pnl_ps.mean() * 100), "pnl_usd": float(g.pnl.sum()), "usd_in": float(g.usd_in.sum())})
    st["monthly"] = mon
    st["months_positive_usd"] = int(sum(r["pnl_usd"] > 0 for r in mon))
    st["months_positive_per_share"] = int(sum(r["net_c"] > 0 for r in mon))
    st["months_total"] = len(mon)
    return st


def evaluate(pr: pd.DataFrame, ends: pd.Series, maker_fee_stress: bool, partial: dict = PARTIAL) -> dict:
    """Book 1, its cuts, the stresses and the diagnostics on one prepared per-print table (b_rs attached)."""
    pr = tt_levels(pr)
    c = candidates(pr)
    books = {"v1": lean_book(c),
             "i_queue10": lean_book(c, share=SHARE_STRESS),
             "ii_trade_through": lean_book(c, trade_through=True),
             "iii_no_rebate": lean_book(c, rebate=False),
             "iv_all": lean_book(c, share=SHARE_STRESS, rebate=False, trade_through=True)}
    if maker_fee_stress:
        books["viii_maker_base_fee"] = lean_book(c, maker_fee=True)
    v1 = books["v1"]
    st = headline(v1, ends, partial)
    lo, hi = st["ci95_pnl_per_share_c"]
    under = st["n_trades"] < 500 or st["n_matches"] < 100
    res = {
        "primary": {"statistic": "mean_pnl_per_share_c (fill-weighted, held to resolution)",
                    "value_c": st["mean_pnl_per_share_c"], "ci95_c": [lo, hi],
                    "ci_method": "match-clustered bootstrap (clusters = event_id), 2,000 draws, seed 0 (src.backtest.stats)",
                    "n_fills": st["n_trades"], "n_matches": st["n_matches"],
                    "verdict": "PASS" if lo > 0 else "FAILURE", "underpowered": bool(under)},
        "headline": st,
        "by_regime": [{"regime": k, **cut(g)} for k, g in v1.groupby("regime")],
        "by_type": [{"smt": k, **cut(g)} for k, g in v1.groupby("smt")],
        "consistency": {"is_1s5_net_c": IS_1S5["net_c"], "is_1s5_ci": IS_1S5["ci"],
                        "point_inside_is_1s5_ci": bool(IS_1S5["ci"][0] <= st["mean_pnl_per_share_c"] <= IS_1S5["ci"][1])},
        "stresses": {},
        "diagnostics": diagnostics(c),
        "derived": {"breakeven_maker_fee_rate": float(v1.pnl_ps.mean() / (v1.px * (1 - v1.px)).mean()) if len(v1) else None,
                    "note": "rate r at which mean(pnl_ps - r*px*(1-px)) = 0 on book 1; derived from book 1, not a variant"},
    }
    for k, b in books.items():
        if k == "v1":
            continue
        s = headline(b, ends, partial)
        res["stresses"][k] = {"value_c": s.get("mean_pnl_per_share_c"), "ci95_c": s.get("ci95_pnl_per_share_c"),
                              "lower_bound_gt_0": bool(s.get("ci95_pnl_per_share_c", [0])[0] > 0) if s.get("n_trades") else False,
                              "headline": s}
    iv = res["stresses"]["iv_all"]
    res["cost_label"] = ("cost-robust OOS" if iv["lower_bound_gt_0"] and res["primary"]["verdict"] == "PASS"
                         else "cost-fragile" if (iv["value_c"] is None or iv["value_c"] <= 0)
                         else "neither cost-robust nor cost-fragile")
    return res, books, c


# ------------------------------------------------------------------ IS preparation
def is_prepared():
    pr, iv = analyze.load()
    months_all = sorted(pr.month.unique())
    bwf = model.walk_forward_b(iv, months_all)
    aug = bwf[bwf.month == "2026-08"].set_index("smt").b.to_dict()
    # PREREG's table equals the walk-forward 2026-08 row up to float printing (match_totals differs by 1 ulp,
    # 2.2e-16); the run always uses the PREREG values (sha-checked). DEVIATIONS.md N1.
    b_ok = all(k in aug and abs(aug[k] - v) <= 1e-12 * abs(v) for k, v in B_T.items())
    choice = json.loads((CM / "analysis.json").read_text())["beta_model_choice"]
    sums = model.local_sums(iv)
    pr = analyze.attach_b(pr, bwf, sums, choice)
    sm = analyze.side_markets()
    ends = pd.Series(pd.to_datetime(sm.drop_duplicates("event_id").set_index("event_id").end).map(
        lambda x: x.timestamp() if pd.notna(x) else np.nan)).fillna(pr.groupby("event_id").ts.max())
    return pr, ends, b_ok, aug, choice


def parity() -> dict:
    fz = check_frozen()
    pr, ends, b_ok, aug, choice = is_prepared()
    c = candidates(pr)
    b = lean_book(c)
    ev = b[b.month >= FIRST_EVAL]
    n, pnl = len(ev), float(ev.pnl.sum())
    d = diagnostics(c[c.month >= FIRST_EVAL])
    dd = {r["book"].split(" (")[0]: (r["n"], r["net_c"]) for r in d if r["regime"] == "1s/5%"}
    diag_ok = (dd["unconditional maker"][0] == IS_DIAG_1S5["unconditional"][0]
               and abs(dd["unconditional maker"][1] - IS_DIAG_1S5["unconditional"][1]) < 1e-9
               and dd["anti-lean placebo"][0] == IS_DIAG_1S5["anti_lean"][0]
               and abs(dd["anti-lean placebo"][1] - IS_DIAG_1S5["anti_lean"][1]) < 1e-9)
    ok = (n == IS_TARGET["n"] and abs(pnl - IS_TARGET["pnl_usd"]) / IS_TARGET["pnl_usd"] <= 1e-6 and b_ok and diag_ok)
    out = {"pass": bool(ok), "n": n, "pnl_usd": pnl, "target": IS_TARGET, "rel_err": abs(pnl - IS_TARGET["pnl_usd"]) / IS_TARGET["pnl_usd"],
           "b_T_equals_walkforward_2026_08": b_ok, "walkforward_2026_08": aug,
           "b_T_max_rel_diff": max(abs(aug[k] - v) / abs(v) for k, v in B_T.items()), "model_choice": choice,
           "diagnostics_1s5": dd, "diagnostics_target": IS_DIAG_1S5, "diagnostics_ok": diag_ok, **fz,
           "utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "parity.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({k: out[k] for k in ("pass", "n", "pnl_usd", "rel_err", "b_T_equals_walkforward_2026_08",
                                          "diagnostics_ok")}, default=float))
    return out


def istest() -> dict:
    """Code test of evaluate() on IS (IS walk-forward b), months >= 2026-02. IS only."""
    check_frozen()
    pr, ends, *_ = is_prepared()
    pr = pr[pr.month >= FIRST_EVAL].copy()  # code test: the per-match cap is computed within Feb-Aug only
    pr["maker_base_fee"] = 1000.0  # IS catalogue did not keep this field; assumed equal to the OOS value
    res, books, _ = evaluate(pr, ends, maker_fee_stress=True, partial={"2026-08": "partial (Aug 1-25, IS)"})
    res["label"] = ("IS reference (Feb-Aug 2026, walk-forward b): code test of the OOS evaluation, run after the "
                    "freeze; IS only, not a test")
    (HERE / "is_reference.json").write_text(json.dumps(res, indent=1, default=float))
    p = res["primary"]
    print("IS reference:", json.dumps({"v1": [p["n_fills"], round(p["value_c"], 3), [round(x, 3) for x in p["ci95_c"]]],
                                       **{k: [v["headline"].get("n_trades"), round(v["value_c"], 3)]
                                          for k, v in res["stresses"].items()}}))
    return res


# ------------------------------------------------------------------ the single OOS run
def oos_prepared():
    pr = pd.read_parquet(OOS_CACHE / "side_prints.parquet")
    iv = pd.read_parquet(OOS_CACHE / "intervals.parquet")
    sm = pd.read_parquet(OOS_CACHE / "side_markets.parquet")
    assert (pr.start >= OOS_CUT).all() and (iv.start >= OOS_CUT).all() and (sm.start >= OOS_CUT).all()
    assert set(pr.smt) <= set(B_T), set(pr.smt) - set(B_T)
    pr = add_cols(pr)
    iv["month"] = month_of(iv.ts)
    pr["b"] = pr.smt.map(B_T)
    sums = model.local_sums(iv)
    pr = model.attach_local(pr, sums, "ts_rs", "rs_")
    pr["b_rs"] = model.shrunk_b(pr.b, pr.rs_sxy, pr.rs_sxx, LAM)
    pr["beta_model"] = f"local{LAM}"
    pr["maker_base_fee"] = pr.cond.map(sm.set_index("cond").maker_base_fee).astype(float)
    ends = pd.Series(pd.to_datetime(sm.drop_duplicates("event_id").set_index("event_id").end).map(
        lambda x: x.timestamp() if pd.notna(x) else np.nan)).fillna(pr.groupby("event_id").ts.max())
    return pr, iv, sm, ends


def sample_counts(pr, iv, sm) -> dict:
    six = sm[sm.type_ok]
    return {
        "events_in_window": int(sm.event_id.nunique()),
        "side_markets_catalogue": int(len(sm)),
        "six_type_markets": int(len(six)),
        "excluded_volume_lt_250": int((~six.vol_ok).sum()),
        "excluded_unresolved": int((six.vol_ok & ~six.resolved).sum()),
        "excluded_totals_not_over": int((six.vol_ok & six.resolved & six.totals_not_over).sum()),
        "selected_markets": int(six.selected.sum()),
        "selected_by_type": six[six.selected].smt.value_counts().to_dict(),
        "markets_with_inplay_prints": int(pr.cond.nunique()),
        "events_with_inplay_side_prints": int(pr.event_id.nunique()),
        "inplay_side_prints": int(len(pr)), "intervals": int(len(iv)),
        "regimes_selected": {f"{d}s/{int(round(r * 100))}%": int(n) for (d, r), n in
                             six[six.selected].groupby(["delay", "fee_rate"]).size().items()},
    }


def maker_fee_check(sm: pd.DataFrame) -> dict:
    s = sm[sm.selected]
    return {"takerOnly_false": int((s.taker_only == False).sum()),  # noqa: E712
            "makerBaseFee_gt_0": int((s.maker_base_fee > 0).sum()), "selected": int(len(s)),
            "makerBaseFee_values": {str(k): int(v) for k, v in s.maker_base_fee.value_counts().items()},
            "rebateRate_values": {str(k): int(v) for k, v in s.rebate_rate.value_counts().items()},
            "triggered": bool(((s.taker_only == False) | (s.maker_base_fee > 0)).any())}  # noqa: E712


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except Exception:
        return "unknown"


def run(rerun_reason: str | None) -> dict:
    if (OUT / "results.json").exists() and not rerun_reason:
        sys.exit("refusing: the OOS run already exists (research/v2/maker/oos/results.json). A re-run needs a "
                 "DEVIATIONS.md entry and --rerun '<reason>'; first-run numbers are kept.")
    if rerun_reason:
        assert (HERE / "DEVIATIONS.md").exists(), "a re-run needs research/v2/maker/DEVIATIONS.md first"
    fz = check_frozen()
    par = json.loads((OUT / "parity.json").read_text())
    assert par["pass"], "parity has not passed; the OOS step does not run"
    sm_meta = pd.read_parquet(OOS_CACHE / "side_markets.parquet")
    mfc = maker_fee_check(sm_meta)                      # decided from metadata, before any P&L
    line = PEEK_LINE if not rerun_reason else f"maker v1 blind OOS RE-RUN ({rerun_reason}); first-run numbers kept"
    with PEEKS.open("a") as fh:                         # the peek is logged before any P&L is computed
        fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} {line}\n")
    pr, iv, sm, ends = oos_prepared()
    res, books, c = evaluate(pr, ends, maker_fee_stress=mfc["triggered"])
    variants = ["1 maker v1 (primary)", "2 stress (i) queue share 10%", "3 stress (ii) trade-through",
                "4 stress (iii) no rebate", "5 stress (iv) all three", "6 diagnostic: unconditional maker",
                "7 diagnostic: anti-lean placebo"]
    if mfc["triggered"]:
        variants.append("8 conditional stress: maker fee = makerBaseFee/1e4 * px * (1 - px) (see DEVIATIONS.md D1)")
    res = {"prereg": "research/v2/maker/PREREG.md (A)", "run": "first" if not rerun_reason else f"re-run: {rerun_reason}",
           "run_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "git_head": git_head(), **fz,
           "parity": {k: par[k] for k in ("pass", "n", "pnl_usd", "rel_err", "b_T_equals_walkforward_2026_08", "diagnostics_ok")},
           "frozen": {"b_T": B_T, "lambda": LAM, "min_impl": MIN_IMPL, "max_ref_age_s": MAX_REF_AGE, "share": SHARE,
                      "max_fill_usd": MAX_FILL, "max_match_usd": MAX_MATCH, "rebate": REBATE, "band": [LO, HI]},
           "sample": sample_counts(pr, iv, sm), "maker_fee_check": mfc, "variants_evaluated": variants,
           "signal_candidates": {"prints_with_signal_inputs": int(len(c)),
                                 "lean_contrary_ge_4c": int(((c.dir == -c.idir) & (c.impl.abs() >= MIN_IMPL)).sum())},
           **res}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float))
    RESULTS_COPY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT / "results.json", RESULTS_COPY)
    for k, b in books.items():
        b.drop(columns=["exit"]).to_csv(OUT / f"book_{k}.csv", index=False, float_format="%.6g")
    pd.DataFrame(res["by_type"]).to_csv(OUT / "by_type.csv", index=False)
    pd.DataFrame(res["by_regime"]).to_csv(OUT / "by_regime.csv", index=False)
    pd.DataFrame(res["headline"]["monthly"]).to_csv(OUT / "monthly.csv", index=False)
    p = res["primary"]
    print(json.dumps({"primary": p, "stresses": {k: [v["value_c"], v["ci95_c"]] for k, v in res["stresses"].items()},
                      "cost_label": res["cost_label"]}, indent=1, default=float))
    return res


def reproduce() -> dict:
    """Recompute the committed OOS numbers from the cached data (no file written except the peeks line) and compare.
    For third parties checking the run; it changes nothing and is logged as its own OOS read."""
    check_frozen()
    ref = json.loads((OUT / "results.json").read_text())
    with PEEKS.open("a") as fh:
        fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} maker v1 OOS reproduction "
                 f"(recompute committed results.json; no parameter change)\n")
    pr, iv, sm, ends = oos_prepared()
    res, _, _ = evaluate(pr, ends, maker_fee_stress=ref["maker_fee_check"]["triggered"])
    rows = [("primary", ref["primary"]["value_c"], res["primary"]["value_c"], ref["primary"]["n_fills"], res["primary"]["n_fills"])]
    rows += [(k, v["value_c"], res["stresses"][k]["value_c"], v["headline"].get("n_trades"),
              res["stresses"][k]["headline"].get("n_trades")) for k, v in ref["stresses"].items()]
    ok = all(a == b and na == nb for _, a, b, na, nb in rows) and ref["primary"]["ci95_c"] == res["primary"]["ci95_c"]
    for r in rows:
        print(f"{r[0]:22s} committed {r[1]:+.6f}c n={r[3]}  recomputed {r[2]:+.6f}c n={r[4]}")
    print("REPRODUCED EXACTLY" if ok else "MISMATCH")
    return {"ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("parity", "istest", "run", "reproduce"))
    ap.add_argument("--rerun", default=None, help="reason for a re-run (needs a DEVIATIONS.md entry)")
    a = ap.parse_args()
    {"parity": parity, "istest": istest, "reproduce": reproduce}.get(a.step, lambda: run(a.rerun))()


if __name__ == "__main__":
    main()
