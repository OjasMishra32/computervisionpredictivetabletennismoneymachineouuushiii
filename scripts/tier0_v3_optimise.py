"""Tier-0 v3 optimisation, IN SAMPLE ONLY (COUNTERFACTUAL WITH ASSUMED DATA).

    ASSUMED: licensed live feed + courtside camera, NOT purchased; parameters from our measurements.
    No live ATP/WTA point feed was bought or used.

Pre-registration of the grid and of the walk-forward rule: research/v2/tier0_v3/GRID.md (written first).
The base model is the verified tier-0 CORRECTED model (src/tier0.py, research/v2/tier0/RESULTS.md): fills priced
from the measured live book on both sides, limit-order fills, R drawn per tournament, +0.5c stale correction,
20 seeds. v3 adds five trader-controlled dimensions (call-precision threshold, lock-in exit, ex-ante leverage
sizing, pre-point price zone, limit price stale + X) and selects among them by monthly walk-forward on IS.

    python scripts/tier0_v3_optimise.py --build            # v3 inputs + portable bundle (IS only)
    python scripts/tier0_v3_optimise.py --check            # reproduce the v2 headline with the v3 simulator
    python scripts/tier0_v3_optimise.py --grid             # 360 variants x 20 seeds, local workers
    python scripts/tier0_v3_optimise.py --part i --nparts N --jobs grid   # one SLURM array task (HiPerGator)
    python scripts/tier0_v3_optimise.py --collect          # walk-forward, stitched IS, bracket jobs, report
    python scripts/tier0_v3_optimise.py --bracket          # frozen v3 / default / v2 over the unmeasured bracket
    python scripts/tier0_v3_optimise.py --report           # results.json + figures from saved parts

Data read: data/derived/tier0_jumps_is.parquet, data/derived/tier0_post30_is.parquet, data/is_prints.parquet,
the frozen measured inputs (results/tier0/inputs, research/v2/latency/out) and the latency recorder's book replay
(data/live_v2, data/live) for the limit-price table. Never: data/locked/*, burned-OOS tables, data/expand_*.
"""
from __future__ import annotations

import argparse
import itertools
import json
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import tier0 as T  # noqa: E402

LABEL = ("COUNTERFACTUAL WITH ASSUMED DATA - assumed: licensed live feed + courtside camera, not purchased; "
         "parameters from our measurements. In-sample (IS) optimisation only; no live ATP/WTA data was used.")
OUT = ROOT / "results/tier0_v3/is"
INP = OUT / "inputs"
BUNDLE = INP / "bundle"
PARTS = OUT / "parts"
SEEDS = 20
IS_SPLIT = T.OOS_START                      # 2026-08-25 14:15 UTC
REGIME1_START = pd.Timestamp("2026-05-15", tz="UTC")
MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08"]

THETAS = (0.85, 0.90, 0.95, 0.97)
EXITS = (None, 2.0, 5.0, 10.0, 30.0)        # None = hold to resolution
SIZINGS = ("flat", "lev")
ZONES = ((0.05, 0.95), (0.10, 0.90), (0.20, 0.80))
LIMITS = (0.005, 0.01, 0.02)
OFFSETS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 30, 45, 60)   # exit-time grid after the tape reprice (s)
EXIT_VWAP_W = 5.0                            # exit reference = VWAP of prints in [max(t_rep, t_exit-5), t_exit]
HALF_SPREAD = 0.005
REP_MOVE = 0.02                              # tape reprice = first print >= 2c from ref in the jump direction


def xkey(x: float) -> str:
    return {0.005: "05", 0.01: "1", 0.02: "2"}[round(x, 4)]


@dataclass(frozen=True)
class V3:
    theta: float = 0.85
    exit_d: float | None = None     # None = hold to resolution; else lock-in at t_reprice + D
    sizing: str = "flat"            # flat | lev
    zone: tuple = (0.05, 0.95)
    limit: float | None = None      # stale + X; None = v2 sweep to the realised new mid (reference only)
    hist_limit: bool = False        # STRESS (post hoc, DEVIATIONS.md D2): also require the modelled fill price
    #                                 (historical post-jump price -/+ live edge/cost) <= stale + X

    def name(self) -> str:
        ex = "hold" if self.exit_d is None else f"lock{self.exit_d:g}s"
        lim = "sweep" if self.limit is None else f"X{self.limit * 100:g}c"
        h = "|histlimit" if self.hist_limit else ""
        return f"th{self.theta:g}|{ex}|{self.sizing}|z{self.zone[0]:g}-{self.zone[1]:g}|{lim}{h}"


GRID = [V3(th, ex, sz, z, x) for th, ex, sz, z, x in itertools.product(THETAS, EXITS, SIZINGS, ZONES, LIMITS)]
DEFAULT = V3(0.85, 5.0, "flat", (0.05, 0.95), 0.02)
V2_HEADLINE = V3(0.85, None, "flat", (0.05, 0.95), None)
REFERENCE = {"v2_headline (hold, sweep to realised new mid)": V2_HEADLINE,
             "v2_headline + lock-in 5 s (sweep)": replace(V2_HEADLINE, exit_d=5.0)}
assert DEFAULT in GRID and len(GRID) == 360
BASE = T.CORRECTED


# =============================================================================================== inputs
def live_limit_curve(refresh: bool = False) -> pd.DataFrame:
    """MEASURED, from the latency recorder's book replay (2026-10-03, same code path as T.live_edge_curve).
    Per live point (m1_points ok) and snapshot (2 / 1 / 0.25 s before the reprice), the part of the stale book
    a limit order at stale + X can reach, m0 = the point's pre-point mid (m1_points.m0, outcome-0 terms):
      correct  SX_<snap>_<x>  winner-token stale shares (better than m_new) priced <= winner m0 + X
               EX_<snap>_<x>  their $ edge vs m_new;  UX_<snap>_<x> their $ cost (winner-token prices)
      wrong    SWX/WX/UWX     loser-token asks priced <= loser m0 + X (= winner-token bids >= m0 - X): shares,
                              $ loss vs m_new, $ cost in loser-token prices
    Levels are sorted best first, so each set is a prefix of the T.live_edge_curve level list. The unrestricted
    columns (S_, E_*_all, SW_, W_*_all, U_) are recomputed and must equal live_edge_curve.csv / stale_depth.csv."""
    f = INP / "live_limit_curve.csv"
    if f.exists() and not refresh:
        return pd.read_csv(f)
    sys.path.insert(0, str(ROOT / "research/v2/latency"))
    import load as L  # noqa: E402
    m1 = pd.read_csv(T.LAT / "m1_points.csv")
    meta = L.load_meta()
    ev = L.events_table(meta)
    e = ev[ev.slug.isin(set(m1.slug))].drop_duplicates("slug").set_index("slug")
    books = L.Books(set(e.tok0) | set(e.tok1), set(e.tok0), dict(zip(meta.ra, meta.tok)))
    P = m1[m1.ok == True]  # noqa: E712
    rows = []
    for r in P.itertuples():
        tok = e.loc[r.slug].tok0
        t, mid, _, _ = books.mid_series(tok)
        d = 1 if r.winner == 0 else -1
        j = np.searchsorted(t, r.t_book + 3000, "right") - 1
        m_new = mid[j] if j >= 0 else np.nan
        m0 = float(r.m0)
        row = {"slug": r.slug, "n": r.n, "D": r.D, "m_new": m_new, "m0": m0}
        for lab, dt in T.EDGE_SNAPS:
            bids, asks = books.book_at(tok, r.t_book - dt)
            if not np.isfinite(m_new):
                good, bad = [], []
            elif d > 0:   # correct buys outcome-0 asks below m_new; wrong sells outcome-0 bids (buys token 1)
                good = [(p, m_new - p, s_) for p, s_ in sorted(asks.items()) if p < m_new]
                bad = [(p, m_new - p, s_) for p, s_ in sorted(bids.items(), reverse=True)]
            else:         # correct sells outcome-0 bids above m_new (buys token 1); wrong lifts outcome-0 asks
                good = [(p, p - m_new, s_) for p, s_ in sorted(bids.items(), reverse=True) if p > m_new]
                bad = [(p, p - m_new, s_) for p, s_ in sorted(asks.items())]
            tokpx_g = (lambda p: p) if d > 0 else (lambda p: 1 - p)     # winner-token price of a level
            tokpx_b = (lambda p: 1 - p) if d > 0 else (lambda p: p)     # loser-token price of a level
            row[f"S_{lab}"] = sum(s for _, _, s in good)
            row[f"E_{lab}_all"] = sum(s * x for _, x, s in good)
            row[f"U_{lab}"] = sum(s * tokpx_g(p) for p, _, s in good)
            row[f"SW_{lab}"] = sum(s for _, _, s in bad)
            row[f"W_{lab}_all"] = sum(s * x for _, x, s in bad)
            for X in LIMITS:
                k = xkey(X)
                if d > 0:
                    gl = [g for g in good if g[0] <= m0 + X + 1e-9]
                    bl = [b for b in bad if b[0] >= m0 - X - 1e-9]
                else:
                    gl = [g for g in good if g[0] >= m0 - X - 1e-9]
                    bl = [b for b in bad if b[0] <= m0 + X + 1e-9]
                assert gl == good[:len(gl)] and bl == bad[:len(bl)]          # prefixes of the level lists
                row[f"SX_{lab}_{k}"] = sum(s for _, _, s in gl)
                row[f"EX_{lab}_{k}"] = sum(s * x for _, x, s in gl)
                row[f"UX_{lab}_{k}"] = sum(s * tokpx_g(p) for p, _, s in gl)
                row[f"SWX_{lab}_{k}"] = sum(s for _, _, s in bl)
                row[f"WX_{lab}_{k}"] = sum(s * x for _, x, s in bl)
                row[f"UWX_{lab}_{k}"] = sum(s * tokpx_b(p) for p, _, s in bl)
        rows.append(row)
    out = pd.DataFrame(rows)
    # reproduction checks against the frozen v2 inputs
    cur = pd.read_csv(T.INPUTS / "live_edge_curve.csv")
    chk = out.merge(cur, on=["slug", "n"], suffixes=("", "_v2"), validate="one_to_one")
    for lab, _ in T.EDGE_SNAPS:
        for c in (f"S_{lab}", f"E_{lab}_all", f"SW_{lab}", f"W_{lab}_all"):
            assert np.allclose(chk[c].fillna(-1), chk[f"{c}_v2"].fillna(-1), atol=1e-6), c
    sd = pd.read_csv(T.LAT / "stale_depth.csv")
    chk2 = out.merge(sd, on=["slug", "n"], validate="one_to_one")
    for lab, c in (("2", "usd_pre2s"), ("1", "usd_pre1s"), ("025", "usd_pre")):
        assert np.allclose(chk2[f"U_{lab}"].fillna(-1), chk2[c].fillna(-1), atol=1e-6), c
    out.insert(0, "label", LABEL)
    INP.mkdir(parents=True, exist_ok=True)
    out.to_csv(f, index=False)
    return out


def exit_table(J: pd.DataFrame) -> pd.DataFrame:
    """Tape reprice time and outcome-0 exit reference prices per IS 1 s-regime jump (J row-aligned subset).
    t_rep = first outcome-0 print in [onset_ts, detect_ts] that has moved >= 2c from `ref` in the jump direction
    (fallback detect_ts). For each offset s in OFFSETS, x<s> = VWAP of prints in [max(t_rep, t_rep+s-5), t_rep+s],
    or the last print at or before t_rep+s if that window is empty. Uses no print after t_rep + s."""
    f = INP / "exit_prices_is.parquet"
    Jd = J[(J.delay == 1)]
    if f.exists():
        x = pd.read_parquet(f)
        if len(x) == len(Jd) and (x.row.to_numpy() == Jd.row.to_numpy()).all():
            return x
    pr = pd.read_parquet(ROOT / "data/is_prints.parquet", columns=["cond", "ts", "p", "usd"])
    pr["cond"] = pr.cond.astype(str)
    pr = pr[pr.cond.isin(set(Jd.cond))].sort_values(["cond", "ts"], kind="stable")
    groups = {c: g for c, g in pr.groupby("cond", sort=False)}
    n = len(Jd)
    out = {"row": Jd.row.to_numpy(), "t_rep": np.full(n, np.nan), "rep_found": np.zeros(n, bool)}
    for s in OFFSETS:
        out[f"x{s}"] = np.full(n, np.nan)
    pos = pd.Series(np.arange(n), index=Jd.index)
    for c, g in Jd.groupby("cond", sort=False):
        P = groups.get(c)
        if P is None:
            continue
        ts, p, usd = P.ts.to_numpy(float), P.p.to_numpy(float), P.usd.to_numpy(float)
        pv = np.concatenate([[0.0], np.cumsum(p * usd)])
        vv = np.concatenate([[0.0], np.cumsum(usd)])
        ii = pos[g.index].to_numpy()
        on, det, ref, dr = (g.onset_ts.to_numpy(float), g.detect_ts.to_numpy(float), g.ref.to_numpy(float),
                            g["dir"].to_numpy(float))
        trep = det.copy()
        found = np.zeros(len(g), bool)
        for k in range(len(g)):
            if not np.isfinite(ref[k]):
                continue
            a = np.searchsorted(ts, on[k], "left")
            b = np.searchsorted(ts, det[k], "right")
            mv = dr[k] * (p[a:b] - ref[k]) >= REP_MOVE - 1e-12
            if mv.any():
                trep[k] = ts[a + int(np.argmax(mv))]
                found[k] = True
        out["t_rep"][ii] = trep
        out["rep_found"][ii] = found
        for s in OFFSETS:
            te = trep + s
            lo = np.maximum(trep, te - EXIT_VWAP_W)
            i0 = np.searchsorted(ts, lo, "left")
            i1 = np.searchsorted(ts, te, "right")
            w = vv[i1] - vv[i0]
            vw = np.where(w > 0, (pv[i1] - pv[i0]) / np.where(w > 0, w, 1), np.nan)
            last = np.where(i1 > 0, p[np.maximum(i1 - 1, 0)], np.nan)
            out[f"x{s}"][ii] = np.where(np.isfinite(vw), vw, last)
    X = pd.DataFrame(out)
    X.insert(0, "label", LABEL)
    X.to_parquet(f)
    return X


def leverage_table(J: pd.DataFrame) -> pd.DataFrame:
    """Ex-ante leverage lev(q) = E[|point move| | pre-point price], fitted on IS jumps of the 3 s-delay regime
    (match start < 2026-05-15; never traded in the walk-forward): mean detector move by the point-winner token's
    stale price q = ref (+0.5c), 5c bins on [0.05, 0.95], centred 3-bin mean. w(q) = lev(q) / max lev."""
    f = INP / "leverage_table.csv"
    if f.exists():
        return pd.read_csv(f)
    X = J[(J.delay != 1) & (J.start < REGIME1_START)]
    q = np.where(X["dir"] > 0, X.ref, 1 - X.ref) + BASE.stale_adj
    ok = np.isfinite(q) & (q >= 0.05) & (q <= 0.95)
    edges = np.round(np.arange(0.05, 0.9501, 0.05), 4)
    b = np.clip(np.searchsorted(edges, q[ok], "right") - 1, 0, len(edges) - 2)
    sz = X["size"].to_numpy()[ok]
    nb = len(edges) - 1
    cnt = np.bincount(b, minlength=nb)
    mean = np.bincount(b, weights=sz, minlength=nb) / np.maximum(cnt, 1)
    sm = np.array([mean[max(0, i - 1):i + 2][cnt[max(0, i - 1):i + 2] > 0].mean() for i in range(nb)])
    out = pd.DataFrame({"label": LABEL, "q_lo": edges[:-1], "q_hi": edges[1:], "n_jumps": cnt,
                        "mean_move": mean, "lev": sm, "w": sm / sm.max(),
                        "source": "IS jumps, 3 s-delay regime (start < 2026-05-15), detector move"})
    out.to_csv(f, index=False)
    return out


def lev_weight(lev: pd.DataFrame, q: np.ndarray) -> np.ndarray:
    lo = lev.q_lo.to_numpy()
    i = np.clip(np.searchsorted(lo, q, "right") - 1, 0, len(lo) - 1)
    return lev.w.to_numpy()[i]


def build() -> None:
    """Every v3 input (IS only) and a portable bundle for HiPerGator."""
    from src.tape import universe
    t0 = time.time()
    J = T.jump_table("is").reset_index(drop=True)
    assert (J.start < IS_SPLIT).all() and not J.oos.any()
    J["row"] = np.arange(len(J))
    J["post30"] = T.post_prices("is", J)
    u = universe()
    v = T.prestart_volume(sorted(u.cond))
    u["prestart_usd"] = u.cond.map(v).fillna(0.0)
    tour = T.tournament_codes(u)
    J["tour"] = J.cond.map(tour).astype(int)
    n_tour = int(tour.max()) + 1
    print(f"jumps {len(J)}, universe {len(u)}, tournaments {n_tour}  ({time.time() - t0:.0f}s)", flush=True)
    lc = live_limit_curve()
    print(f"live limit curve: {len(lc)} points ({time.time() - t0:.0f}s)", flush=True)
    ex = exit_table(J)
    print(f"exit table: {len(ex)} jumps, reprice print found {ex.rep_found.mean():.3f} ({time.time() - t0:.0f}s)",
          flush=True)
    lev = leverage_table(J)
    print(lev[["q_lo", "n_jumps", "mean_move", "w"]].round(4).to_string(index=False), flush=True)
    BUNDLE.mkdir(parents=True, exist_ok=True)
    keep = ["row", "cond", "onset_ts", "detect_ts", "dir", "size", "ref", "ref_short", "start", "res0", "volume",
            "fee_rate", "delay", "region", "men", "post30", "tour"]
    J[keep].to_parquet(BUNDLE / "J.parquet")
    u[["cond", "start", "delay", "prestart_usd"]].to_parquet(BUNDLE / "M.parquet")
    for p in ("D>=3c", "all"):
        T.live_points(p).to_parquet(BUNDLE / f"pool_{'D3c' if p == 'D>=3c' else 'all'}.parquet")
    lc.to_parquet(BUNDLE / "limit_curve.parquet")
    ex.to_parquet(BUNDLE / "exit.parquet")
    lev.to_parquet(BUNDLE / "lev.parquet")
    meta = {"label": LABEL, "cvs": T.cv_systems(), "mix": T.point_mix(), "calib": T.calibrate_stamp_lag(),
            "n_tour": n_tour}
    (BUNDLE / "meta.json").write_text(json.dumps(meta, default=float))
    print(f"bundle written ({time.time() - t0:.0f}s)", flush=True)


# ============================================================================================== context
_C: dict = {}


def context(bundle: Path = BUNDLE) -> dict:
    if _C:
        return _C
    J = pd.read_parquet(bundle / "J.parquet")
    M = pd.read_parquet(bundle / "M.parquet")
    meta = json.loads((bundle / "meta.json").read_text())
    lc = pd.read_parquet(bundle / "limit_curve.parquet")
    lcols = [c for c in lc.columns if c.startswith(("SX_", "EX_", "UX_", "SWX_", "WX_", "UWX_"))] + ["m0"]
    pools = {}
    for p, f in (("D>=3c", "pool_D3c.parquet"), ("all", "pool_all.parquet")):
        pl = pd.read_parquet(bundle / f)
        pools[p] = pl.merge(lc[["slug", "n"] + lcols], on=["slug", "n"], how="left", validate="one_to_one")
        assert pools[p][lcols].notna().all().all()
    ex = pd.read_parquet(bundle / "exit.parquet")
    lev = pd.read_parquet(bundle / "lev.parquet")
    cov = T.coverage_set(M, BASE.coverage, BASE.regime)
    Jc = J[J.cond.isin(cov)].reset_index(drop=True)
    # exit prices aligned to covered jump rows (all covered jumps are 1 s regime)
    exi = ex.set_index("row")
    assert set(Jc.row) <= set(exi.index)
    E = exi.loc[Jc.row.to_numpy()]
    days = T.period_days(J, BASE.regime)
    _C.update(J=J, Jc=Jc, M=M, pools=pools, cvs=meta["cvs"], mix=meta["mix"], calib=meta["calib"],
              n_tour=meta["n_tour"], lev=lev, E=E, days=days, n_rows=len(J))
    return _C


# =========================================================================================== simulation
def _depth_cols(pool, idx, tau, cols):
    u2, u1, u025, upost = (pool[c].to_numpy()[idx] for c in cols)
    out = np.zeros(len(tau))
    a = tau >= 2.0
    out[a] = u2[a]
    b = (tau >= 1.0) & (tau < 2.0)
    out[b] = u1[b] + (u2[b] - u1[b]) * (tau[b] - 1.0)
    c = (tau >= 0.25) & (tau < 1.0)
    out[c] = u025[c] + (u1[c] - u025[c]) * (tau[c] - 0.25) / 0.75
    d = (tau >= 0) & (tau < 0.25)
    out[d] = u025[d]
    e = (tau >= -T.DECAY_S) & (tau < 0)
    out[e] = u025[e] + (upost[e] - u025[e]) * (-tau[e] / T.DECAY_S)
    return np.maximum(out, 0.0)


def _snap_limited(curve, side, idx, m, lab, k):
    """Per-share value of the first m live shares at snapshot lab when only the limit-reachable prefix
    (SX / SWX shares, cumulative EX / WX) exists. Cumulative value is linear between the EDGE_N grid points and
    the prefix end."""
    grid = np.array((0,) + T.EDGE_N, float)
    kk = np.clip(np.searchsorted(grid, m, "right") - 1, 0, len(grid) - 2)
    ar = np.arange(len(idx))
    sx = curve[f"{'SX' if side == 'E' else 'SWX'}_{lab}_{k}"].to_numpy()[idx]
    gx = curve[f"{'EX' if side == 'E' else 'WX'}_{lab}_{k}"].to_numpy()[idx]
    G = np.column_stack([np.zeros(len(idx))] + [curve[f"{side}_{lab}_{N}"].to_numpy()[idx] for N in T.EDGE_N])
    lo, hi = grid[kk], grid[kk + 1]
    up = np.minimum(hi, sx)
    gup = np.where(sx < hi, gx, G[ar, kk + 1])
    gm = G[ar, kk] + (gup - G[ar, kk]) * (m - lo) / np.maximum(up - lo, 1e-12)
    gm = np.where((m >= sx) | (m >= grid[-1]), gx, gm)
    return np.where(sx > 0, gm / np.minimum(m, np.maximum(sx, 1e-9)), 0.0)


def curve_v3(curve, side, idx, n, scale, tau, after, limit):
    """T.curve_per_share, with the stale-book prefix restricted to a limit at stale + X before the reprice
    (tau >= 0). After the reprice the v2 (unrestricted) value is used (GRID.md section 5)."""
    base = T.curve_per_share(curve, side, idx, n, scale, tau, after)
    if limit is None:
        return base
    k = xkey(limit)
    m = np.maximum(n / np.maximum(scale, 1e-9), 1e-6)
    v = {lab: _snap_limited(curve, side, idx, m, lab, k) for lab, _ in T.EDGE_SNAPS}
    out = np.zeros(len(tau))
    a = tau >= 2.0
    out[a] = v["2"][a]
    b = (tau >= 1.0) & (tau < 2.0)
    out[b] = v["1"][b] + (v["2"][b] - v["1"][b]) * (tau[b] - 1.0)
    c = (tau >= 0.25) & (tau < 1.0)
    out[c] = v["025"][c] + (v["1"][c] - v["025"][c]) * (tau[c] - 0.25) / 0.75
    d = (tau >= 0) & (tau < 0.25)
    out[d] = v["025"][d]
    out = np.maximum(out, 0.0) if side == "E" else out
    return np.where(tau >= 0, out, base)


def simulate_v3(sc: T.Scenario, v: V3, dr: dict, keep_cols: bool = False) -> pd.DataFrame:
    """T.simulate (verified CORRECTED path: price='live', wrong_price='live', order='limit') on the covered IS
    jumps, plus the v3 trader controls. With v = V2_HEADLINE it reproduces T.simulate exactly (checked)."""
    c = context()
    X = c["Jc"]
    E = c["E"]
    pool = c["pools"][sc.pool]
    assert sc.price == "live" and sc.wrong_price == "live" and sc.order == "limit"
    ref = X[sc.stale].to_numpy()
    dirn = X["dir"].to_numpy()
    q_c0 = np.where(dirn > 0, ref, 1 - ref) + sc.stale_adj
    ok = np.isfinite(ref) & (q_c0 >= v.zone[0]) & (q_c0 <= v.zone[1])
    X = X[ok]
    Eo = E[ok]
    q_c0, dirn = q_c0[ok], dirn[ok]
    r = X.row.to_numpy()
    n = len(X)
    pidx = np.minimum((dr["pool"][r] * len(pool)).astype(int), len(pool) - 1)
    men = X.men.to_numpy()
    p_out = np.where(men, c["mix"]["men"]["out"], c["mix"]["women"]["out"])
    is_out = dr["end"][r] < p_out
    cvd = c["cvs"][sc.cv]
    lead, prec_cv, called = T.lead_and_precision(cvd, dr["lead"][r], dr["bin"][r])
    early = is_out & called
    lead = np.where(early, lead, 0.0)
    prec = np.where(early, prec_cv, sc.p_event)
    fired = prec >= v.theta - 1e-9
    lat = (np.full(n, 0.100) if sc.lat_map == "all100" else X.region.map(T.REGION_MS).to_numpy(float) / 1000.0)
    arrival = -lead + cvd["t_inf"] + lat + T.GATEWAY + X.delay.to_numpy(float)
    R = pool.R.to_numpy()
    if sc.r_mode == "point":
        t_rep = R[pidx] + sc.stamp_lag + sc.r_shift
    elif sc.r_mode == "tournament":
        tu = dr["tour"][X.tour.to_numpy()]
        t_rep = R[np.minimum((tu * len(pool)).astype(int), len(pool) - 1)] + sc.stamp_lag + sc.r_shift
    elif sc.r_mode == "stamp":
        t_rep = np.full(n, float(np.median(R)) + sc.stamp_lag + sc.r_shift)
    else:
        raise ValueError(sc.r_mode)
    tau = t_rep - arrival
    ratio = X.volume.to_numpy(float) / pool.V_live.to_numpy()[pidx]
    scale = {"cap1": np.minimum(1.0, ratio), "none": np.ones(n), "sym3": np.minimum(3.0, ratio)}[sc.vol_scale]
    correct = dr["prec"][r] < prec
    size = X["size"].to_numpy()
    lo = sc.queue_s
    fill_ok = tau >= lo
    if v.limit is None:
        dep_c = T._depth(pool, pidx, tau) * scale * sc.phi
    else:
        k = xkey(v.limit)
        dep_c = _depth_cols(pool, pidx, tau, (f"UX_2_{k}", f"UX_1_{k}", f"UX_025_{k}", "usd_post")) * scale * sc.phi
    if v.sizing == "lev":
        q_sz = np.where(correct, q_c0, 1 - q_c0 + 2 * sc.stale_adj)
        levcap = lev_weight(c["lev"], q_sz) * sc.net_cap
    else:
        levcap = np.full(n, np.inf)
    post = X["post30"].to_numpy(float)
    post_tok = np.where(dirn > 0, post, 1 - post)
    post_tok = np.where(np.isfinite(post_tok), post_tok, q_c0 + size)
    escl = (size / pool.D.to_numpy()[pidx]) if sc.edge_scale else np.ones(n)
    e_c = curve_v3(pool, "E", pidx, np.full(n, 100.0), scale, tau, "zero", v.limit) * escl
    for _ in range(2):
        q_c = np.clip(post_tok - e_c, 0.01, 0.99)
        n_sh = np.minimum(np.minimum(sc.trade_cap, dep_c) / q_c, levcap)
        e_c = curve_v3(pool, "E", pidx, n_sh, scale, tau, "zero", v.limit) * escl
    q_c = np.clip(post_tok - e_c, 0.01, 0.99)
    if v.hist_limit and v.limit is not None:
        fill_ok = fill_ok & (q_c <= q_c0 + v.limit + 1e-9)
    sh_c = np.where(fill_ok, np.minimum(np.minimum(sc.trade_cap / q_c, dep_c / q_c), levcap), 0.0)
    if v.limit is None:
        dep_w = T._depth(pool, pidx, np.maximum(tau, 0.0)) * scale
    else:
        k = xkey(v.limit)
        dw = _depth_cols(pool, pidx, np.maximum(tau, 0.0), (f"UWX_2_{k}", f"UWX_1_{k}", f"UWX_025_{k}", "usd_post"))
        dep_w = np.where(tau >= 0, dw, T._depth(pool, pidx, np.zeros(n))) * scale
    post_l = np.where(dirn > 0, 1 - post, post)
    post_l = np.where(np.isfinite(post_l), post_l, (1 - q_c0) - size)
    w = curve_v3(pool, "W", pidx, np.full(n, 100.0), scale, tau, "spread", v.limit)
    for _ in range(2):
        q_w = np.clip(post_l + w, 0.01, 0.99)
        w = curve_v3(pool, "W", pidx, np.minimum(np.minimum(sc.trade_cap, dep_w) / q_w, levcap), scale, tau,
                     "spread", v.limit)
    q_w = np.clip(post_l + w, 0.01, 0.99)
    sh_w = np.minimum(np.minimum(sc.trade_cap / q_w, dep_w / q_w), levcap)
    if v.hist_limit and v.limit is not None:
        sh_w = np.where(q_w <= (1 - q_c0 + 2 * sc.stale_adj) + v.limit + 1e-9, sh_w, 0.0)
    q = np.where(correct, q_c, q_w)
    sh = np.where(correct, sh_c, sh_w)
    tok0 = np.where(correct, dirn > 0, dirn < 0)
    res0 = X.res0.to_numpy(float)
    payout = np.where(tok0, res0, 1 - res0)
    rate = X.fee_rate.to_numpy(float)
    Tt = pd.DataFrame({"cond": X.cond.to_numpy(), "ts": X.onset_ts.to_numpy(), "q": q, "sh_raw": sh,
                       "d0": np.where(tok0, 1.0, -1.0), "payout": payout, "fee_ps": rate * q * (1 - q),
                       "correct": correct, "tau": tau, "early": early, "prec": prec, "fired": fired,
                       "dep_c": dep_c, "size": size, "rate": rate, "edge_c": np.where(correct, e_c, -w),
                       "i": np.arange(n), "q_stale": np.where(correct, q_c0, 1 - q_c0 + 2 * sc.stale_adj),
                       "post_b": np.where(correct, post_tok, post_l), "tok0": tok0,
                       "t_rep_tape": Eo.t_rep.to_numpy(), "row": r})
    Tt = Tt[Tt.fired].sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
    if v.exit_d is None:
        Tt["shares"] = T._net_cap(Tt, sc.net_cap)
        Tt["lock_end"] = Tt.ts + T.LOCK_S
    else:
        need = np.maximum(v.exit_d, -Tt.tau.to_numpy())
        offs = np.array(OFFSETS, float)
        oi = np.minimum(np.searchsorted(offs, need - 1e-9, "left"), len(offs) - 1)
        off = offs[oi]
        Tt["exit_off"] = off
        Tt["lock_end"] = Tt.t_rep_tape.to_numpy() + off
        xm = np.column_stack([Eo[f"x{s}"].to_numpy() for s in OFFSETS])
        # map back to the (filtered, sorted) Tt rows through i
        x0 = xm[Tt.i.to_numpy(), oi]
        Tt["exit_tok"] = np.where(Tt.tok0, x0, 1 - x0)
        Tt["shares"] = _net_cap_lock(Tt, sc.net_cap)
    if True:   # re-price live fills for the shares actually sent after the net cap (as T.simulate)
        m = (Tt.correct & (Tt.shares > 1e-9)).to_numpy()
        i = Tt.i.to_numpy()[m]
        e2 = curve_v3(pool, "E", pidx[i], Tt.shares.to_numpy()[m], scale[i], tau[i], "zero", v.limit) * escl[i]
        qn = np.clip(post_tok[i] - e2, 0.01, 0.99)
        Tt.loc[m, "q"] = qn
        Tt.loc[m, "edge_c"] = e2
        Tt.loc[m, "fee_ps"] = Tt.rate.to_numpy()[m] * qn * (1 - qn)
        m = (~Tt.correct & (Tt.shares > 1e-9)).to_numpy()
        i = Tt.i.to_numpy()[m]
        w2 = curve_v3(pool, "W", pidx[i], Tt.shares.to_numpy()[m], scale[i], tau[i], "spread", v.limit)
        qn = np.clip(post_l[i] + w2, 0.01, 0.99)
        Tt.loc[m, "q"] = qn
        Tt.loc[m, "edge_c"] = -w2
        Tt.loc[m, "fee_ps"] = Tt.rate.to_numpy()[m] * qn * (1 - qn)
    if v.exit_d is None:
        Tt["pnl_ps"] = Tt.payout - Tt.q - Tt.fee_ps
    else:
        sell = np.clip(Tt.exit_tok.to_numpy() - HALF_SPREAD, 0.01, 0.99)
        Tt["sell"] = sell
        Tt["fee2_ps"] = Tt.rate.to_numpy() * sell * (1 - sell)
        Tt["pnl_ps"] = sell - Tt.q - Tt.fee_ps - Tt.fee2_ps
    Tt["pnl"] = Tt.shares * Tt.pnl_ps
    Tt["usd_in"] = Tt.shares * Tt.q
    Tt["date"] = pd.to_datetime(Tt.ts, unit="s", utc=True).dt.floor("D")
    Tt["month"] = Tt.date.dt.strftime("%Y-%m")
    return Tt


def _net_cap_lock(Tt: pd.DataFrame, cap: float) -> np.ndarray:
    """Net cap with lock-in exits: a position counts toward its match's net from entry (ts) until lock_end.
    Rows sorted by (cond, ts). When every exit precedes the next entry of the same match (always, for D <= 30 s:
    the detector's 60 s refractory puts the next onset >= 50 s after this detect), each order starts flat."""
    s = Tt.sh_raw.to_numpy().copy()
    if not np.isfinite(cap):
        return s
    cond = Tt.cond.to_numpy()
    same = np.r_[cond[1:] == cond[:-1], False]
    overlap = same & (Tt.lock_end.to_numpy() > np.r_[Tt.ts.to_numpy()[1:], np.inf])
    if not overlap.any():
        return np.minimum(s, cap)
    d, ts, le = Tt.d0.to_numpy(), Tt.ts.to_numpy(), Tt.lock_end.to_numpy()
    open_: list = []
    last = None
    for k in range(len(s)):
        if cond[k] != last:
            open_, last = [], cond[k]
        open_ = [(e, x) for e, x in open_ if e > ts[k]]
        net = sum(x for _, x in open_)
        s[k] = min(s[k], max(0.0, cap - d[k] * net))
        open_.append((le[k], d[k] * s[k]))
    return s


# ============================================================================================== metrics
def month_of(days: pd.DatetimeIndex) -> np.ndarray:
    return np.array(days.strftime("%Y-%m"))


def metrics_v3(calls: pd.DataFrame, days: pd.DatetimeIndex, n_boot: int = 1000, seed: int = 0) -> tuple[dict, np.ndarray]:
    n_calls = len(calls)
    tr = calls[calls.shares > 1e-9]
    nd = len(days)
    if tr.empty:
        return {"n_calls": n_calls, "n_trades": 0, "pnl_usd": 0.0, "pnl_per_day_usd": 0.0}, np.zeros(nd)
    daily = tr.groupby("date").pnl.sum().reindex(days, fill_value=0.0)
    dv = daily.to_numpy()
    eq = np.cumsum(dv)
    dd = float((eq - np.maximum.accumulate(eq)).min())
    peak = T.peak_locked(tr)
    cap = T.CAPITAL_MULT * peak
    g = tr.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
    P, S = g.p.to_numpy(), g.s.to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n_boot, len(g)))
    ps = P[idx].sum(1) / S[idx].sum(1) * 100
    sd = daily.std()
    down = float(np.sqrt(np.mean(np.minimum(dv, 0.0) ** 2)))
    mu = float(dv.mean())
    active = np.asarray(days.isin(tr.date.unique()))
    mo = month_of(days)
    monthly = np.array([dv[mo == m].sum() for m in MONTHS])
    good = tr[tr.correct]
    out = {
        "n_calls": int(n_calls), "n_trades": int(len(tr)), "n_trades_correct": int(len(good)),
        "n_matches": int(len(g)), "fill_rate": float(len(good) / n_calls) if n_calls else float("nan"),
        "wrong_call_share_of_trades": float(1 - len(good) / len(tr)),
        "shares": float(tr.shares.sum()), "usd_traded": float(tr.usd_in.sum()),
        "median_usd_per_fill": float(tr.usd_in.median()),
        "per_share_c": float(tr.pnl.sum() / tr.shares.sum() * 100),
        "per_share_ci95_c_lo": float(np.percentile(ps, 2.5)), "per_share_ci95_c_hi": float(np.percentile(ps, 97.5)),
        "pnl_usd": float(tr.pnl.sum()), "pnl_correct_usd": float(good.pnl.sum()),
        "pnl_wrong_usd": float(tr[~tr.correct].pnl.sum()),
        "days": nd, "pnl_per_day_usd": float(tr.pnl.sum() / nd),
        "sharpe_ann": float(mu / sd * np.sqrt(365)) if sd > 0 else float("nan"),
        "sortino_ann": float(mu / down * np.sqrt(365)) if down > 0 else (float("inf") if mu > 0 else float("nan")),
        "max_dd_usd": dd, "worst_day_usd": float(dv.min()), "best_day_usd": float(dv.max()),
        "profitable_days_pct_active": float((dv[active] > 0).mean() * 100) if active.any() else float("nan"),
        "profitable_days_pct_calendar": float((dv > 0).mean() * 100),
        "profitable_trades_pct": float((tr.pnl > 0).mean() * 100),
        "months_positive": int((monthly > 0).sum()), "months_total": len(MONTHS),
        **{f"pnl_{m}": float(x) for m, x in zip(MONTHS, monthly)},
        "peak_locked_usd": peak, "capital_usd": cap,
        "return_on_capital_pct": float(tr.pnl.sum() / cap * 100) if cap else float("nan"),
        "return_on_capital_ann_pct": float(tr.pnl.sum() / cap * 100 * 365 / nd) if cap else float("nan"),
    }
    return out, dv


def run_one(v: V3, seed: int, sc: T.Scenario = BASE, keep: bool = False):
    c = context()
    dr = T.draws(c["n_rows"], seed, max(c["n_tour"], 1))
    calls = simulate_v3(sc, v, dr)
    m, dv = metrics_v3(calls, c["days"])
    return (m, dv, calls) if keep else (m, dv)


# =============================================================================================== jobs
def grid_jobs() -> list[tuple]:
    """(job id, variant dict, scenario dict, seed). Reference variants first, then the 360-variant grid."""
    jobs = []
    vs = [("ref", k, v) for k, v in REFERENCE.items()] + [("grid", v.name(), v) for v in GRID]
    for kind, name, v in vs:
        for s in range(SEEDS):
            jobs.append(((kind, name, s), asdict(v), asdict(BASE), s))
    return jobs


def bracket_scenarios(calib: float) -> dict[str, T.Scenario]:
    out = {}
    for lag in (1.0, 2.0, 3.0, calib):
        for rd in ("tournament", "point", "stamp"):
            for trunc in (0.0, -0.5):
                for qs in (0.0, 0.25):
                    out[f"lag{lag:g}|{rd}|trunc{trunc:g}|queue{qs:g}"] = replace(
                        BASE, stamp_lag=lag, r_mode=rd, r_shift=trunc, queue_s=qs)
    return out


def bracket_jobs(variants: dict[str, V3]) -> list[tuple]:
    calib = context()["calib"]["central"]["stamp_lag_s"]
    jobs = []
    for vn, v in variants.items():
        for bn, sc in bracket_scenarios(calib).items():
            for s in range(SEEDS):
                jobs.append(((vn, bn, s), asdict(v), asdict(sc), s))
    return jobs


def _v_from(d: dict) -> V3:
    d = dict(d)
    d["zone"] = tuple(d["zone"])
    return V3(**d)


def _job(args):
    jid, vd, scd, s = args
    m, dv = run_one(_v_from(vd), s, T.Scenario(**scd))
    return jid, m, dv.astype(np.float64)


def run_jobs(jobs: list[tuple], workers: int, tag: str) -> list:
    t0 = time.time()
    out = []
    with ProcessPoolExecutor(workers) as ex:
        for k, res in enumerate(ex.map(_job, jobs, chunksize=8)):
            out.append(res)
            if (k + 1) % 400 == 0 or k + 1 == len(jobs):
                el = time.time() - t0
                print(f"[{tag}] {k + 1}/{len(jobs)} runs, {el / 60:.1f} min elapsed, "
                      f"~{el / (k + 1) * (len(jobs) - k - 1) / 60:.1f} min left", flush=True)
    return out


# ======================================================================================== walk-forward
def assemble(results: list) -> tuple[pd.DataFrame, dict]:
    """Per-job results -> per-variant 20-seed summary table + daily arrays {variant: (seeds, days)}."""
    rows, daily = [], {}
    for jid, m, dv in results:
        kind, name, s = jid
        rows.append({"kind": kind, "variant": name, "seed": s, **m})
        daily.setdefault(name, {})[s] = dv
    R = pd.DataFrame(rows)
    D = {k: np.vstack([v[s] for s in sorted(v)]) for k, v in daily.items()}
    return R, D


def assemble_grid(results: list) -> tuple[pd.DataFrame, dict]:
    """assemble() with reference variants keyed by V3.name() (their jobs carry the descriptive key)."""
    R, D = assemble(results)
    ren = {k: v.name() for k, v in REFERENCE.items()}
    R["variant"] = R.variant.replace(ren)
    return R, {ren.get(k, k): v for k, v in D.items()}


def summarise(R: pd.DataFrame, D: dict) -> pd.DataFrame:
    """20-seed mean and SD per variant; Sortino also pooled over (seed, day)."""
    num = [c for c in R.columns if c not in ("kind", "variant", "seed") and pd.api.types.is_numeric_dtype(R[c])]
    out = []
    for (kind, name), g in R.groupby(["kind", "variant"], sort=False):
        row = {"label": LABEL, "kind": kind, "variant": name, "n_seeds": len(g)}
        for c in num:
            x = g[c].replace([np.inf, -np.inf], np.nan)
            row[c] = float(x.mean())
            row[f"{c}_sd"] = float(x.std(ddof=0))
        dv = D[name]
        down = np.sqrt(np.mean(np.minimum(dv, 0) ** 2))
        row["sortino_pooled_ann"] = float(dv.mean() / down * np.sqrt(365)) if down > 0 else float("inf")
        row["n_seeds_sortino_inf"] = int(np.isinf(g.sortino_ann).sum()) if "sortino_ann" in g else 0
        out.append(row)
    return pd.DataFrame(out)


def pooled_sortino(dv: np.ndarray) -> float:
    down = np.sqrt(np.mean(np.minimum(dv, 0) ** 2))
    mu = dv.mean()
    if down > 0:
        return float(mu / down * np.sqrt(365))
    return float("inf") if mu > 0 else float("-inf")


def walk_forward(D: dict, days: pd.DatetimeIndex) -> dict:
    mo = month_of(days)
    names = [v.name() for v in GRID]
    dname = DEFAULT.name()
    out = {"rule": "GRID.md: month m uses argmax pooled-seed Sortino over months < m among variants with mean "
                   "daily P&L >= 0.5 x default's (>= default's if the default's is <= 0); May = default",
           "default": dname, "months": {}}
    monthly_rows = []
    for name in names:
        for m in MONTHS:
            dv = D[name][:, mo == m]
            monthly_rows.append({"label": LABEL, "variant": name, "month": m, "pnl_per_day_usd": float(dv.mean()),
                                 "pnl_per_day_usd_sd_seeds": float(dv.mean(1).std()), "sortino_pooled_ann": pooled_sortino(dv)})
    chosen = {}
    for j, m in enumerate(MONTHS):
        if j == 0:
            chosen[m] = dname
            out["months"][m] = {"chosen": dname, "why": "pre-declared default (no prior month)"}
            continue
        past = np.isin(mo, MONTHS[:j])
        pdef = float(D[dname][:, past].mean())
        bar = 0.5 * pdef if pdef > 0 else pdef
        cand = []
        for k, name in enumerate(names):
            dv = D[name][:, past]
            pv = float(dv.mean())
            cand.append((name, pooled_sortino(dv), pv, k, pv >= bar - 1e-12))
        elig = [x for x in cand if x[4]]
        best = sorted(elig, key=lambda x: (-x[1], -x[2], x[3]))[0]
        top = sorted(elig, key=lambda x: (-x[1], -x[2], x[3]))[:10]
        chosen[m] = best[0]
        out["months"][m] = {"chosen": best[0], "selection_months": MONTHS[:j],
                            "default_pnl_per_day_past": pdef, "eligibility_bar_usd_per_day": bar,
                            "n_eligible": len(elig), "chosen_sortino_past": best[1], "chosen_pnl_per_day_past": best[2],
                            "default_sortino_past": next(x[1] for x in cand if x[0] == dname),
                            "top10": [{"variant": a, "sortino": b, "pnl_per_day": c} for a, b, c, _, _ in top]}
    out["chosen"] = chosen
    out["frozen_v3"] = chosen[MONTHS[-1]]
    return out, pd.DataFrame(monthly_rows)


def stitched(chosen: dict, workers: int) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Per seed, month m's trades from the variant chosen for m; metrics on the stitched trades."""
    c = context()
    names = {v.name(): v for v in GRID}
    need = sorted(set(chosen.values()))
    jobs = [(nm, s) for nm in need for s in range(SEEDS)]
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_keep_job, [(asdict(names[nm]), s) for nm, s in jobs], chunksize=2))
    trades = {(nm, s): t for (nm, s), t in zip(jobs, res)}
    ms, dvs, all_tr = [], [], []
    for s in range(SEEDS):
        parts = [trades[(chosen[m], s)].loc[lambda x: x.month == m].assign(variant=chosen[m]) for m in MONTHS]
        st = pd.concat(parts, ignore_index=True)
        mm, dv = metrics_v3(st, c["days"])
        ms.append(mm)
        dvs.append(dv)
        all_tr.append(st.assign(seed=s))
    F = pd.DataFrame(ms).replace([np.inf, -np.inf], np.nan)
    dv = np.vstack(dvs)
    summ = {"n_seeds": SEEDS, "mean": F.mean().to_dict(), "sd": F.std(ddof=0).to_dict(),
            "sortino_pooled_ann": pooled_sortino(dv), "chosen": chosen}
    daily = pd.DataFrame(dv.T, index=c["days"], columns=[f"seed{s}" for s in range(SEEDS)])
    daily.insert(0, "variant", [chosen[m] for m in month_of(c["days"])])
    daily.insert(0, "label", LABEL)
    return summ, daily, pd.concat(all_tr, ignore_index=True)


def _keep_job(args):
    vd, s = args
    _, _, calls = run_one(_v_from(vd), s, BASE, keep=True)
    return calls


def diagnostics(tr: pd.DataFrame, n_days: int) -> dict:
    """Pooled over seeds: per-share decomposition (correct / wrong) and P&L by REALISED jump size (diagnostic
    only: the trade set is selected on realised moves; no v3 rule uses the size)."""
    n_seeds = tr.seed.nunique()
    tr = tr[tr.shares > 1e-9]
    out = {}
    lock = "sell" in tr and tr["sell"].notna().any()
    dec = {}
    for lab, z in (("correct", tr[tr.correct]), ("wrong", tr[~tr.correct])):
        if z.empty:
            continue
        w = z.shares.sum()
        d = {"share_of_trades": float(len(z) / len(tr)), "share_of_shares": float(w / tr.shares.sum()),
             "book_edge_or_cost_c": float((z.edge_c * z.shares).sum() / w * 100),
             "fee_entry_c": float(-(z.fee_ps * z.shares).sum() / w * 100), "net_c": float(z.pnl.sum() / w * 100)}
        zl = z[z.get("sell", pd.Series(np.nan, index=z.index)).notna()] if lock else z.iloc[0:0]
        zh = z.drop(zl.index)
        if len(zl):
            wl = zl.shares.sum()
            d["lockin"] = {"shares": float(wl), "half_spread_c": -HALF_SPREAD * 100,
                           "fee_exit_c": float(-(zl.fee2_ps * zl.shares).sum() / wl * 100),
                           "tape_exit_minus_post30_c": float(((zl.exit_tok - zl.post_b) * zl.shares).sum() / wl * 100)}
        if len(zh):
            wh = zh.shares.sum()
            d["hold"] = {"shares": float(wh),
                         "payout_minus_post30_c": float(((zh.payout - zh.post_b) * zh.shares).sum() / wh * 100)}
        dec[lab] = d
    out["decomposition"] = dec
    sb = pd.cut(tr["size"], [0.04, 0.05, 0.07, 0.10, 1.0], right=False)
    out["by_realised_jump_size_DIAGNOSTIC"] = {
        str(k): {"share_of_shares": float(z.shares.sum() / tr.shares.sum()),
                 "net_c": float(z.pnl.sum() / z.shares.sum() * 100),
                 "pnl_per_day_usd": float(z.pnl.sum() / n_seeds / n_days)} for k, z in tr.groupby(sb, observed=True)}
    out["tau_of_fills"] = {"correct_median_s": float(tr[tr.correct].tau.median()) if tr.correct.any() else None,
                           "wrong_share_after_reprice": float((tr[~tr.correct].tau < 0).mean()) if (~tr.correct).any() else None}
    out["fill_price_above_stale_plus_X_share"] = None
    return out


# ================================================================================================ main
def save_part(obj, name: str) -> None:
    PARTS.mkdir(parents=True, exist_ok=True)
    with open(PARTS / name, "wb") as fh:
        pickle.dump(obj, fh)


def load_parts(prefix: str) -> list:
    out = []
    for f in sorted(PARTS.glob(f"{prefix}_[0-9]*.pkl")):
        with open(f, "rb") as fh:
            out += pickle.load(fh)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--time", action="store_true")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--part", type=int, default=None)
    ap.add_argument("--nparts", type=int, default=1)
    ap.add_argument("--jobs", default="grid", help="grid | bracket (with --part)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--posthoc", action="store_true")
    a = ap.parse_args()
    if a.build:
        build()
        return
    if a.check:
        check(a.workers)
        return
    if a.time:
        c = context()
        for v in (V2_HEADLINE, DEFAULT, V3(0.95, 30.0, "lev", (0.2, 0.8), 0.005)):
            t0 = time.time()
            m, _ = run_one(v, 0)
            print(v.name(), f"{time.time() - t0:.2f}s", {k: round(m[k], 3) for k in ("n_trades", "per_share_c", "pnl_per_day_usd")})
        return
    if a.part is not None:
        jobs = grid_jobs() if a.jobs == "grid" else pickle.load(open(PARTS / "bracket_jobs.pkl", "rb"))
        mine = jobs[a.part::a.nparts]
        res = run_jobs(mine, a.workers, f"{a.jobs} part {a.part}/{a.nparts}")
        save_part(res, f"{a.jobs}_{a.part:03d}.pkl")
        return
    if a.grid:
        res = run_jobs(grid_jobs(), a.workers, "grid")
        save_part(res, "grid_000.pkl")
        return
    if a.collect:
        collect(a.workers)
        return
    if a.report:
        report()
        return
    if a.posthoc:
        post_hoc(a.workers)
        return


def check(workers: int) -> None:
    """The v3 simulator with V2_HEADLINE must reproduce T.simulate(CORRECTED) row for row on IS."""
    c = context()
    for s in (0, 7):
        dr = T.draws(c["n_rows"], s, max(c["n_tour"], 1))
        a = simulate_v3(BASE, V2_HEADLINE, dr)
        J = c["J"].copy()
        b = T.simulate(J, c["M"].assign(oos=False), BASE, dr, c["pools"], c["cvs"], c["mix"])
        a2 = a.sort_values(["cond", "ts"], kind="stable").reset_index(drop=True)
        assert len(a2) == len(b), (len(a2), len(b))
        for col in ("q", "shares", "pnl", "tau", "fee_ps"):
            assert np.allclose(a2[col].to_numpy(), b[col].to_numpy(), atol=1e-12), col
        print(f"seed {s}: v3 simulator == T.simulate (CORRECTED), {len(a2)} calls, P&L ${a2.pnl.sum():,.2f}")
    res = run_jobs([(("ref", "v2", s), asdict(V2_HEADLINE), asdict(BASE), s) for s in range(SEEDS)], workers, "check")
    F = pd.DataFrame([m for _, m, _ in res])
    print("v2 headline, IS, 20 seeds: c/share {:.3f} ± {:.3f}  $/day {:.1f} ± {:.1f}  Sharpe {:.2f} ± {:.2f}  "
          "trades {:.0f} ± {:.0f}  calls {:.0f}".format(F.per_share_c.mean(), F.per_share_c.std(ddof=0),
                                                       F.pnl_per_day_usd.mean(), F.pnl_per_day_usd.std(ddof=0),
                                                       F.sharpe_ann.mean(), F.sharpe_ann.std(ddof=0),
                                                       F.n_trades.mean(), F.n_trades.std(ddof=0), F.n_calls.mean()))


def _fmt_summary(row: pd.Series | dict) -> dict:
    keys = ["n_calls", "n_trades", "fill_rate", "wrong_call_share_of_trades", "per_share_c", "per_share_ci95_c_lo",
            "per_share_ci95_c_hi", "pnl_usd", "pnl_per_day_usd", "sharpe_ann", "sortino_ann", "max_dd_usd",
            "worst_day_usd", "profitable_days_pct_active", "profitable_days_pct_calendar", "profitable_trades_pct",
            "months_positive", "capital_usd", "return_on_capital_pct", "return_on_capital_ann_pct",
            "median_usd_per_fill"] + [f"pnl_{m}" for m in MONTHS]
    out = {}
    for k in keys:
        if k in row and pd.notna(row[k]):
            out[k] = round(float(row[k]), 4)
            if f"{k}_sd" in row and pd.notna(row[f"{k}_sd"]):
                out[f"{k}_sd"] = round(float(row[f"{k}_sd"]), 4)
    if "sortino_pooled_ann" in row:
        out["sortino_pooled_ann"] = round(float(row["sortino_pooled_ann"]), 4)
    return out


def collect(workers: int) -> None:
    """Grid parts -> grid.csv, walk-forward, stitched IS result, frozen v3, diagnostics; writes the bracket job
    list for the HiPerGator array."""
    c = context()
    res = load_parts("grid")
    assert len(res) == (len(GRID) + len(REFERENCE)) * SEEDS, len(res)
    R, D = assemble_grid(res)
    G = summarise(R, D)
    vcols = pd.DataFrame([asdict(v) | {"variant": v.name()} for v in GRID] +
                         [asdict(v) | {"variant": v.name()} for v in REFERENCE.values()]).drop_duplicates("variant")
    vcols["zone"] = vcols.zone.astype(str)
    vcols["exit"] = vcols.exit_d.map(lambda x: "hold" if pd.isna(x) else f"lock{x:g}s")
    G = G.merge(vcols, on="variant", how="left")
    G["is_default"] = G.variant == DEFAULT.name()
    G.to_csv(OUT / "grid.csv", index=False)
    print(f"grid: {len(G)} rows -> grid.csv", flush=True)
    wf, MO = walk_forward(D, c["days"])
    MO.to_csv(OUT / "monthly.csv", index=False)
    (OUT / "walkforward.json").write_text(json.dumps({"label": LABEL, **wf}, indent=1, default=float))
    for m, d in wf["months"].items():
        print(m, "->", d["chosen"], {k: round(v, 2) for k, v in d.items() if isinstance(v, float)}, flush=True)
    st, daily, st_tr = stitched(wf["chosen"], workers)
    daily.to_csv(OUT / "stitched_daily.csv")
    names = {v.name(): v for v in GRID}
    frozen = names[wf["frozen_v3"]]
    # frozen v3 trades (20 seeds) for diagnostics
    with ProcessPoolExecutor(workers) as ex:
        ftr = list(ex.map(_keep_job, [(asdict(frozen), s) for s in range(SEEDS)], chunksize=2))
    ftr = pd.concat([t.assign(seed=s) for s, t in enumerate(ftr)], ignore_index=True)
    nd = len(c["days"])
    diag = {"frozen_v3_full_IS": diagnostics(ftr, nd), "stitched": diagnostics(st_tr, nd)}
    if frozen.limit is not None:
        cr = ftr[ftr.correct & (ftr.shares > 1e-9)]
        diag["frozen_v3_full_IS"]["fill_price_above_stale_plus_X_share"] = float(
            ((cr.q > cr.q_stale + frozen.limit + 1e-9) * cr.shares).sum() / cr.shares.sum())
    # drift of the tape after the reprice vs the fill model's post-30 s anchor (no P&L; all covered jumps)
    E, Jc = c["E"], c["Jc"]
    d = Jc["dir"].to_numpy()
    diag["tape_minus_post30_in_jump_direction_c"] = {
        f"t_rep+{s}s": round(float(np.nanmean((E[f"x{s}"].to_numpy() - Jc.post30.to_numpy()) * d) * 100), 3)
        for s in (2, 3, 5, 10, 30, 60)}
    diag["tape_reprice_print_found_share"] = float(E.rep_found.mean())
    G2 = G.set_index("variant")
    out = {"label": LABEL, "grid_md": "research/v2/tier0_v3/GRID.md", "period": "IS only (1 s regime, "
           "2026-05-15 -> 2026-08-25 14:15 UTC, 103 days); no burned OOS, no U2, no forward data",
           "base_model": {k: (v if not isinstance(v, float) or np.isfinite(v) else str(v)) for k, v in asdict(BASE).items()},
           "n_variants": len(GRID), "n_seeds": SEEDS,
           "default": {"variant": DEFAULT.name(), **_fmt_summary(G2.loc[DEFAULT.name()])},
           "reference": {k: {"variant": v.name(), **_fmt_summary(G2.loc[v.name()])} for k, v in REFERENCE.items()},
           "walk_forward": wf,
           "stitched_IS": {"chosen_by_month": wf["chosen"],
                           **{k: round(float(v), 4) for k, v in st["mean"].items() if np.isfinite(v)},
                           "sd": {k: round(float(v), 4) for k, v in st["sd"].items() if np.isfinite(v)},
                           "sortino_pooled_ann": st["sortino_pooled_ann"]},
           "frozen_v3": {"variant": frozen.name(), "rule": asdict(frozen),
                         "full_IS_NOTE": "frozen v3 over all IS months; May-July are its selection months, so this "
                                         "is in-sample-selected. The stitched series is the IS result.",
                         **_fmt_summary(G2.loc[frozen.name()])},
           "diagnostics": diag,
           "marginals_IS": marginals(G)}
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=float))
    pickle.dump(bracket_jobs({"frozen_v3": frozen, "default": DEFAULT, "v2_headline": V2_HEADLINE}),
                open(PARTS / "bracket_jobs.pkl", "wb"))
    print("stitched:", json.dumps(out["stitched_IS"], default=float)[:1500], flush=True)
    print("frozen v3:", json.dumps(out["frozen_v3"], default=float)[:1200], flush=True)


def marginals(G: pd.DataFrame) -> dict:
    g = G[G.kind == "grid"]
    out = {}
    for dim in ("theta", "exit", "sizing", "zone", "limit"):
        out[dim] = (g.groupby(dim).agg(pnl_per_day_median=("pnl_per_day_usd", "median"),
                                       pnl_per_day_max=("pnl_per_day_usd", "max"),
                                       per_share_c_median=("per_share_c", "median"),
                                       sortino_median=("sortino_pooled_ann", "median"),
                                       share_positive=("pnl_usd", lambda s: float((s > 0).mean())))
                    .round(3).reset_index().astype({dim: str}).set_index(dim).to_dict("index"))
    return out


def report() -> None:
    """Bracket parts -> bracket.csv; adds the bracket to results.json; equity figure."""
    c = context()
    res = load_parts("bracket")
    rows = []
    for (vn, bn, s), m, _ in res:
        rows.append({"config": vn, "scenario": bn, "seed": s, **m})
    B = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
    num = [k for k in B.columns if k not in ("config", "scenario", "seed")]
    gb = B.groupby(["config", "scenario"], sort=False)[num]
    agg = gb.mean().join(gb.std(ddof=0).add_suffix("_sd"))
    agg = agg.reset_index()
    parts = agg.scenario.str.extract(r"lag(?P<stamp_lag>[\d.]+)\|(?P<reading>\w+)\|trunc(?P<trunc>[-\d.]+)\|queue(?P<queue>[\d.]+)")
    agg = pd.concat([agg[["config", "scenario"]], parts, agg.drop(columns=["config", "scenario"])], axis=1)
    agg.insert(0, "label", LABEL)
    agg.to_csv(OUT / "bracket.csv", index=False)
    out = json.loads((OUT / "results.json").read_text())
    br = {}
    for cfg, g in agg.groupby("config", sort=False):
        br[cfg] = {"n_scenarios": int(len(g)),
                   "pnl_per_day": {"min": float(g.pnl_per_day_usd.min()), "median": float(g.pnl_per_day_usd.median()),
                                   "max": float(g.pnl_per_day_usd.max())},
                   "per_share_c": {"min": float(g.per_share_c.min()), "median": float(g.per_share_c.median()),
                                   "max": float(g.per_share_c.max())},
                   "share_scenarios_positive": float((g.pnl_usd > 0).mean()),
                   "share_scenarios_ci_excludes_0": float((g.per_share_ci95_c_lo > 0).mean()),
                   "by_stamp_lag_median_pnl_per_day": g.groupby("stamp_lag").pnl_per_day_usd.median().round(2).to_dict(),
                   "by_reading_median_pnl_per_day": g.groupby("reading").pnl_per_day_usd.median().round(2).to_dict(),
                   "verifier_stresses_at_lag2_tournament": {
                       r.scenario: {"pnl_per_day_usd": round(r.pnl_per_day_usd, 2), "pnl_per_day_usd_sd": round(r.pnl_per_day_usd_sd, 2),
                                    "per_share_c": round(r.per_share_c, 3),
                                    "per_share_ci95_c": [round(r.per_share_ci95_c_lo, 3), round(r.per_share_ci95_c_hi, 3)],
                                    "sharpe_ann": round(r.sharpe_ann, 2)}
                       for r in g[(g.stamp_lag == "2") & (g.reading == "tournament")].itertuples()}}
    out["bracket_IS"] = br
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=float))
    figure(c)
    print(json.dumps(br, indent=1, default=float)[:4000])


def post_hoc(workers: int) -> None:
    """DEVIATIONS.md D2 (post hoc, not selectable): frozen v3 and the best-$/day variant with the limit also enforced
    in the historical-price frame; plus the v2 headline reproduction check. Written to results.json."""
    out = json.loads((OUT / "results.json").read_text())
    names = {v.name(): v for v in GRID}
    fz = names[out["frozen_v3"]["variant"]]
    G = pd.read_csv(OUT / "grid.csv")
    best = names[G[G.kind == "grid"].sort_values("pnl_per_day_usd", ascending=False).variant.iloc[0]]
    vs = {"frozen_v3": fz, "frozen_v3 + limit enforced in historical frame": replace(fz, hist_limit=True),
          "best $/day variant": best, "best $/day variant + limit in historical frame": replace(best, hist_limit=True)}
    jobs = [((k, v.name(), s), asdict(v), asdict(BASE), s) for k, v in vs.items() for s in range(SEEDS)]
    res = run_jobs(jobs, workers, "post-hoc")
    ph = {}
    for k, v in vs.items():
        F = pd.DataFrame([m for (kk, _, _), m, _ in res if kk == k]).replace([np.inf, -np.inf], np.nan)
        ph[k] = {"variant": v.name(), **{c: round(float(F[c].mean()), 4) for c in F.columns},
                 **{f"{c}_sd": round(float(F[c].std(ddof=0)), 4) for c in ("per_share_c", "pnl_per_day_usd", "sharpe_ann")}}
    out["post_hoc_stresses (DEVIATIONS D2; not used for selection)"] = ph
    out["v2_headline_reproduction"] = {"v3 simulator == T.simulate(CORRECTED) row for row (seeds 0, 7)": True,
                                       **out["reference"]["v2_headline (hold, sweep to realised new mid)"]}
    (OUT / "results.json").write_text(json.dumps(out, indent=1, default=float))
    for k, d in ph.items():
        print(f"{k:50s} c/sh {d['per_share_c']:.3f} [{d['per_share_ci95_c_lo']:.2f},{d['per_share_ci95_c_hi']:.2f}] "
              f"$/day {d['pnl_per_day_usd']:.1f} ± {d['pnl_per_day_usd_sd']:.1f} Sharpe {d['sharpe_ann']:.2f}")


def figure(c: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    days = c["days"]
    st = pd.read_csv(OUT / "stitched_daily.csv", index_col=0, parse_dates=True)
    S = st[[k for k in st.columns if k.startswith("seed")]].cumsum()
    res = load_parts("grid")
    _, D = assemble_grid(res)
    ink, ink2, grid_c, surf = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    fig, ax = plt.subplots(figsize=(10, 4.6))
    fig.patch.set_facecolor(surf)
    ax.set_facecolor(surf)
    for k in S.columns:
        ax.plot(S.index, S[k].values, color="#2a78d6", lw=0.5, alpha=0.25)
    ax.plot(S.index, S.mean(1).values, color="#2a78d6", lw=2.2, label="v3 stitched walk-forward (20-seed mean)")
    wf = json.loads((OUT / "walkforward.json").read_text())
    for name, col, ls, lab in ((wf["frozen_v3"], "#2a78d6", "--", f"frozen v3 over all IS (in-sample-selected): {wf['frozen_v3']}"),
                               (DEFAULT.name(), "#eb6834", "-", "default (lock-in 5 s, X 2c)"),
                               (V2_HEADLINE.name(), "#a3a29e", "-", "v2 headline (hold, sweep to realised new mid; not ex-ante)")):
        ax.plot(days, np.cumsum(D[name].mean(0)), color=col, lw=1.6, ls=ls, label=lab)
    for m in MONTHS[1:]:
        ax.axvline(pd.Timestamp(m + "-01", tz="UTC"), color=grid_c, lw=1)
    ax.axhline(0, color=grid_c, lw=1)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.set_ylabel("cumulative P&L, $")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    ax.set_title("Tier-0 v3, in sample: monthly walk-forward over 360 trader-rule variants", loc="left", color=ink, fontsize=11)
    import textwrap
    fig.text(0.01, 0.01, "\n".join(textwrap.wrap(LABEL + " Means over 20 seeds; thin lines = seeds of the stitched series.", 150)),
             color=ink2, fontsize=7.5, ha="left")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(OUT / "equity_stitched_IS.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
