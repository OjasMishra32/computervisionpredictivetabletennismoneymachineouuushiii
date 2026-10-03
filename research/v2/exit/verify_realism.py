"""Adversarial realism check of the "exit" lens (IS data only; no OOS, no network, no locked data).

Stress-tests the recommended rule (sh500 / improve1 / fallback B / no rebate) against:

  A. Reproduction of the headline from the simulator cache (data/v2_exit/).
  B. Tick-grid audit. The simulator infers tick = 0.001 for every match whose tape has ANY print off the cent
     grid. Off-cent prints are mostly per-taker-order AVERAGE prices (dollar-sized market buys that sweep
     levels: ~91% have a round-cent USD notional, ~97% are BUYs). Per match we measure the share of
     mid-range prints (0.06 < p < 0.94) that sit on the 0.001 grid but not on the cent grid. If makers could
     quote in 0.001 steps in mid-range, many would; where they do not, the effective mid-range tick is 0.01
     (Polymarket's dynamic tick: 0.001 only beyond 0.04 / 0.96). tick_eff = 0.001 if that share >= 5%, else
     0.01 (sensitivity at 2% and 10% thresholds).
  C. Fill-price realism. A data-api print's price is the taker order's average over the levels it swept. A
     resting order at the touch is filled at the touch, which is <= the average for a taker buy (>= for a
     taker sell). We snap each maker fill price to the touch on the tick_eff grid (floor for exits that sell
     into taker buys, ceil for exits that buy from taker sells), then charge the improvement tick at tick_eff.
     Re-run the (H, T) walk-forward on all IS under that pricing.
  D. Re-simulation of the 1 s / 5% entries (and the frozen H=10/T=300 cell):
       - touch model replicated (must match the cache fill for fill),
       - touch with OTHER fast-tier prints allowed to fill our resting exit (the cache excludes every
         fast-tier 0-3 s print in the match from filling exits, i.e. exactly the most toxic flow),
       - a volume-at-level queue model: pegged at the (snapped) touch with Q shares ahead; we fill at L when
         cumulative print volume at L since we (re)joined reaches Q + our size, or when a print trades beyond
         L (level cleared). A print at a worse level re-pegs us to the back. Q in {0, 500, 2000, 8000};
         variant "repeg-up": a better-level print with no volume at L since we joined re-pegs us upward
         instead of filling (makers cancelled).
       - room flag: snapped spread proxy (latest opposite-side print <= 30 s old) >= 2 * tick_eff.
       - mixed policy: improve 1 tick_eff inside where the proxy shows room (unknown counted as room),
         otherwise join the touch queue (Q = 2000).
       - D2, partial-fill version of the queue model (pf_*): each print at our level first clears the Q
         shares ahead, then fills us partially at L; partial fills are kept; the unfilled remainder goes to
         fallback B. pf_improve = alone 1 tick_eff inside the touch (Q = 0), room always assumed (generous).
  E. Min order 5 shares; concentration by fast-tier wallet, match and day; day-clustered bootstrap;
     deflated Sharpe (Bailey & Lopez de Prado) for N = 902 and smaller effective N.

    .venv/bin/python research/v2/exit/verify_realism.py        # ~2 min on 2 workers (fresh); caches reused after
Writes research/v2/exit/verify_realism.json and data/v2_exit/verify_*.parquet (cache).
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import norm, kurtosis, skew  # noqa: E402

from research.v2.exit import analyze_exit as ax  # noqa: E402
from research.v2.exit.sim_exit import KEY, OOS_START, SPREAD_STALE, _tape  # noqa: E402

CACHE = ROOT / "data" / "v2_exit"
HERE = Path(__file__).resolve().parent
REG = "1s/5%"
CELLS = [(30, 300), (10, 300)]  # WF choice for every 1s/5% month, and the frozen OOS rule
QS = (0, 500, 2000, 8000)
MID_LO, MID_HI = 0.06, 0.94
TICK_THR = 0.05
N_BOOT = 1000


def snap(p, tick, up):
    """Touch level implied by an average print price: floor (taker buy swept up) or ceil (taker sell)."""
    p = np.asarray(p, float)
    return np.where(up, np.floor(p / tick + 1e-3) * tick, np.ceil(p / tick - 1e-3) * tick)


def grid_audit(price: np.ndarray) -> tuple[float, int]:
    m = (price > MID_LO) & (price < MID_HI)
    p = price[m]
    if len(p) == 0:
        return np.nan, 0
    on2 = np.abs(p * 100 - np.round(p * 100)) < 1e-4
    on3 = np.abs(p * 1000 - np.round(p * 1000)) < 1e-4
    return float((on3 & ~on2).mean()), int(len(p))


def audit_job(job):
    cond, start, end = job
    f = ROOT / "data/raw/trades" / f"{cond}.parquet"
    if not f.exists():
        return cond, np.nan, 0
    t = pd.read_parquet(f, columns=["timestamp", "price"])
    s = int(start.timestamp())
    e = int(end.timestamp()) if pd.notna(end) else s + 6 * 3600
    t = t[(t.timestamp >= s) & (t.timestamp <= e)]
    fr, n = grid_audit(t.price.to_numpy(float))
    return cond, fr, n


def sim_job(job):
    """Re-simulate exits for one match's accepted entries at CELLS under several fill models."""
    cond, e_all, start, end, tick_eff = job
    t = _tape(cond, start, end)
    if t is None or t.empty:
        return None
    tk = pd.DataFrame({"ts": t.timestamp.astype(float), "p": t.p0, "dir": np.where(t.at_ask, 1.0, -1.0),
                       "wallet": t.proxyWallet, "usd": t.usd, "tidx": np.arange(len(t))})
    tk["occ"] = tk.groupby(KEY, sort=False).cumcount()
    e = e_all.copy()
    e["occ"] = e.groupby(KEY, sort=False).cumcount()
    e = e.merge(tk[KEY + ["occ", "tidx"]], on=KEY + ["occ"], how="left")
    ts_all = t.timestamp.to_numpy().astype(np.int64)
    p_all = t.p0.to_numpy().astype(float)
    ask_all = t.at_ask.to_numpy()
    size_all = t["size"].to_numpy().astype(float)
    own = np.zeros(len(t), bool)
    own[e.tidx.dropna().astype(int).to_numpy()] = True

    def sides(mask):
        idx = {s: np.flatnonzero((ask_all == s) & ~mask) for s in (True, False)}
        return ({s: ts_all[idx[s]] for s in idx}, {s: p_all[idx[s]] for s in idx},
                {s: size_all[idx[s]] for s in idx})

    S_mask = sides(own)
    S_nomask = sides(np.zeros(len(t), bool))
    # opposite-side snapped levels for the room proxy (all prints)
    opp = {s: (ts_all[ask_all != s], snap(p_all[ask_all != s], tick_eff, up=(not s))) for s in (True, False)}

    acc = e[e.acc_sh500].sort_values("ts", kind="stable")
    ets = acc.ts.to_numpy().astype(np.int64)
    edir = acc.dir.to_numpy()
    sh = acc.shares_sh500.to_numpy(float)
    out = []
    for H, T in CELLS:
        res = {"eid": acc.eid.to_numpy(), "H": H, "T": T}
        # ---- touch model (replica) and no-mask variant; room flag at the touch fill
        for tag, (st_, sp_, ssz_) in (("touch", S_mask), ("touch_nomask", S_nomask)):
            rem = {s: ssz_[s].copy() for s in ssz_}
            fil = np.zeros(len(acc), bool)
            px = np.full(len(acc), np.nan)
            dt = np.full(len(acc), np.nan)
            room = np.full(len(acc), np.nan)
            for k in range(len(acc)):
                s = edir[k] > 0
                st = st_[s]
                lo = np.searchsorted(st, ets[k] + H, "left")
                hi = np.searchsorted(st, ets[k] + H + T, "right")
                if hi <= lo:
                    continue
                c = np.flatnonzero(rem[s][lo:hi] >= sh[k] - 1e-9)
                if c.size:
                    j = lo + c[0]
                    rem[s][j] -= sh[k]
                    fil[k], px[k], dt[k] = True, sp_[s][j], st[j] - ets[k]
                    if tag == "touch":
                        ot, ol = opp[s]
                        q = np.searchsorted(ot, st[j], "right") - 1
                        if q >= 0 and st[j] - ot[q] <= SPREAD_STALE:
                            lvl = snap(sp_[s][j], tick_eff, up=s)
                            spr = (lvl - ol[q]) if s else (ol[q] - lvl)
                            room[k] = float(spr >= 2 * tick_eff - 1e-9)
            res[f"{tag}_filled"], res[f"{tag}_px"], res[f"{tag}_dt"] = fil, px, dt
            if tag == "touch":
                res["room"] = room
        # ---- queue model on snapped levels (masked like the cache)
        st_, sp_, ssz_ = S_mask
        lvl_side = {s: snap(sp_[s], tick_eff, up=s) for s in (True, False)}
        for Q in QS:
            for mode in ("cons", "repeg"):
                if mode == "repeg" and Q not in (500, 2000):
                    continue
                rem = {s: ssz_[s].copy() for s in ssz_}
                fil = np.zeros(len(acc), bool)
                px = np.full(len(acc), np.nan)
                dt = np.full(len(acc), np.nan)
                for k in range(len(acc)):
                    s = edir[k] > 0
                    st = st_[s]
                    lo = np.searchsorted(st, ets[k] + H, "left")
                    hi = np.searchsorted(st, ets[k] + H + T, "right")
                    if hi <= lo:
                        continue
                    lv, r = lvl_side[s], rem[s]
                    L, v, vt = None, 0.0, 0.0  # v: volume at L since we joined; vt: same, excluding the revealing print
                    for j in range(lo, hi):
                        if L is None:
                            L, v, vt = lv[j], 0.0, -1.0
                        better = (lv[j] > L + 1e-9) if s else (lv[j] < L - 1e-9)
                        worse = (lv[j] < L - 1e-9) if s else (lv[j] > L + 1e-9)
                        if better:
                            if mode == "repeg" and vt <= 0:
                                L, v, vt = lv[j], 0.0, -1.0  # level vanished without trades: makers cancelled, re-peg up
                            else:
                                fil[k], px[k], dt[k] = True, L, st[j] - ets[k]
                                break
                        elif worse:
                            L, v, vt = lv[j], 0.0, -1.0  # touch moved against us: re-peg, back of the queue
                        v += r[j]
                        vt = 0.0 if vt < 0 else vt + r[j]
                        if v >= Q + sh[k] - 1e-9:
                            r[j] = max(r[j] - sh[k], 0.0)
                            fil[k], px[k], dt[k] = True, L, st[j] - ets[k]
                            break
                tag = f"q{Q}_{mode}"
                res[f"{tag}_filled"], res[f"{tag}_px"], res[f"{tag}_dt"] = fil, px, dt
        # ---- partial-fill queue model (D2). Pegged at the snapped touch L (or imp inside it, then alone: Q=0).
        # Each exit-side print at our level first clears the Q shares ahead of us, then fills us (partially);
        # a print at a better level clears our level (fill the rest at L; "repeg": if nothing traded at L
        # since we joined, the level vanished by cancellation and we re-peg upward instead); a print at a
        # worse level re-pegs us to the back of the new level. Partial fills are kept at their own price.
        for tag, Q, imp_on in ([(f"pf_q{Q}", Q, False) for Q in QS] + [("pf_improve", 0, True)]):
            for mode in ("cons", "repeg"):
                if mode == "repeg" and Q > 2000:
                    continue
                imp = tick_eff if imp_on else 0.0
                rem = {s: ssz_[s].copy() for s in ssz_}
                frac = np.zeros(len(acc))
                px = np.full(len(acc), np.nan)
                dt = np.full(len(acc), np.nan)
                for k in range(len(acc)):
                    s = edir[k] > 0
                    st = st_[s]
                    lo = np.searchsorted(st, ets[k] + H, "left")
                    hi = np.searchsorted(st, ets[k] + H + T, "right")
                    if hi <= lo:
                        continue
                    lv, r = lvl_side[s], rem[s]
                    our = (lambda L: L - imp) if s else (lambda L: L + imp)
                    need = sh[k]
                    got, val = 0.0, 0.0
                    # traded: a print at L AFTER the print that revealed L (else L vanished by cancellation)
                    L, ahead, traded, reveal = None, 0.0, False, True
                    for j in range(lo, hi):
                        if L is None:
                            L, ahead, traded, reveal = lv[j], float(Q), False, True
                        better = (lv[j] > L + 1e-9) if s else (lv[j] < L - 1e-9)
                        worse = (lv[j] < L - 1e-9) if s else (lv[j] > L + 1e-9)
                        if better:
                            if mode == "repeg" and not traded:
                                L, ahead, traded, reveal = lv[j], float(Q), False, True
                            else:
                                val += (need - got) * our(L)
                                got = need
                                dt[k] = st[j] - ets[k]
                                break
                        elif worse:
                            L, ahead, traded, reveal = lv[j], float(Q), False, True
                        x = r[j]
                        if reveal:
                            reveal = False
                        else:
                            traded = traded or x > 0
                        a = min(ahead, x)
                        ahead -= a
                        x -= a
                        f = min(x, need - got)
                        if f > 0:
                            got += f
                            val += f * our(L)
                            r[j] -= f
                        if got >= need - 1e-9:
                            dt[k] = st[j] - ets[k]
                            break
                    if got > 0:
                        frac[k] = got / need
                        px[k] = val / got
                res[f"{tag}_{mode}_frac"], res[f"{tag}_{mode}_px"], res[f"{tag}_{mode}_dt"] = frac, px, dt
        out.append(pd.DataFrame(res))
    return pd.concat(out, ignore_index=True)


# ----------------------------------------------------------------------------- helpers
def pnl_frame_partial(E: pd.DataFrame, frac, px_exit, fb_px, fb_dt, maker_dt):
    """Partial maker fill: frac of the shares exit at px_exit (no fee), the rest via fallback B / resolution."""
    full = pnl_frame(E, np.ones(len(E), bool), np.nan_to_num(px_exit, nan=0.5), fb_px, fb_dt, maker_dt)
    none = pnl_frame(E, np.zeros(len(E), bool), np.nan_to_num(px_exit, nan=0.5), fb_px, fb_dt, maker_dt)
    tr = none.copy()
    tr["pnl_ps"] = frac * full.pnl_ps.to_numpy() + (1 - frac) * none.pnl_ps.to_numpy()
    tr["how"] = np.where(frac >= 1 - 1e-9, "maker", none.how.to_numpy())
    tr["maker_frac"] = frac
    tr["pnl"] = tr.shares * tr.pnl_ps
    return tr
def pnl_frame(E: pd.DataFrame, filled, px_exit, fb_px, fb_dt, maker_dt):
    """Per-entry net P&L/share: maker exit at px_exit (no fee), else fallback B (taker, fee) else resolution."""
    fee_in = E.fee.to_numpy()
    d, p = E.dir.to_numpy(), E.p.to_numpy()
    has = np.isfinite(fb_px)
    fpx = np.nan_to_num(fb_px)
    pnl_fb = np.where(has, d * (fpx - p) - fee_in - E.fee_rate.to_numpy() * fpx * (1 - fpx), d * (E.res.to_numpy() - p) - fee_in)
    pnl = np.where(filled, d * (px_exit - p) - fee_in, pnl_fb)
    how = np.where(filled, "maker", np.where(has, "taker", "res"))
    hold = np.where(filled, maker_dt, np.where(has, fb_dt, (E.end_ts - E.ts).to_numpy(float)))
    tr = E[["eid", "cond", "ts", "date", "month", "regime", "wallet", "pp", "end_ts"]].copy()
    tr["shares"] = E.shares_sh500.to_numpy()
    tr["pnl_ps"], tr["how"], tr["hold_s"] = pnl, how, hold
    tr["pnl"] = tr.shares * tr.pnl_ps
    tr["usd_in"] = tr.shares * tr.pp
    return tr


def quick(tr: pd.DataFrame, n_boot=N_BOOT) -> dict:
    tr = tr[np.isfinite(tr.pnl_ps)]
    ci, ci_sw = ax.cluster_ci(tr, n_boot)
    daily = tr.groupby("date").pnl.sum()
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D", tz="UTC")
    daily = daily.reindex(idx, fill_value=0.0)
    return {"n": int(len(tr)), "ps_c": float(tr.pnl_ps.mean() * 100), "ci_c": [float(ci[0]), float(ci[1])],
            "ps_sw_c": float(tr.pnl.sum() / tr.shares.sum() * 100), "pnl_usd": float(tr.pnl.sum()),
            "maker_fill": float((tr.how == "maker").mean()), "taker_fb": float((tr.how == "taker").mean()),
            "sharpe_daily_ann": float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else None,
            "worst_day": float(daily.min())}


def day_cluster_ci(tr, n_boot=N_BOOT, seed=1):
    g = tr.groupby("date").agg(s=("pnl_ps", "sum"), n=("pnl_ps", "size"))
    rng = np.random.default_rng(seed)
    s, n = g.s.to_numpy(), g.n.to_numpy()
    bs = [s[i].sum() / n[i].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(n_boot))]
    return [float(x) for x in np.percentile(bs, [2.5, 97.5]) * 100]


def deflated_sharpe(daily: pd.Series, n_trials: int) -> dict:
    x = daily.to_numpy(float)
    T = len(x)
    sr = x.mean() / x.std(ddof=1)
    g3, g4 = skew(x), kurtosis(x, fisher=False)
    se = np.sqrt((1 - g3 * sr + (g4 - 1) / 4 * sr ** 2) / (T - 1))
    gam = 0.5772156649
    sr0 = se * ((1 - gam) * norm.ppf(1 - 1 / n_trials) + gam * norm.ppf(1 - 1 / (n_trials * np.e))) if n_trials > 1 else 0.0
    return {"T_days": T, "sr_daily": float(sr), "sr_ann": float(sr * np.sqrt(365)), "sr0_daily": float(sr0),
            "dsr_prob": float(norm.cdf((sr - sr0) / se)), "n_trials": n_trials}


def wf_select(grid: dict, months: list[str]):
    sums = pd.DataFrame({k: v.groupby("month").pnl.sum() for k, v in grid.items()}).reindex(months).fillna(0.0)
    counts = next(iter(grid.values())).groupby("month").size().reindex(months).fillna(0)
    parts, ch = [], []
    for i, m in enumerate(months):
        past = months[:i]
        pick = ax.DEFAULT if counts[past].sum() < ax.MIN_PAST else sums.loc[past].sum().idxmax()
        parts.append(grid[pick][grid[pick].month == m].assign(H=pick[0], T=pick[1]))
        ch.append((m, int(pick[0]), int(pick[1])))
    return pd.concat(parts, ignore_index=True), ch


# ----------------------------------------------------------------------------- main
def main(workers: int = 2):
    t0 = time.time()
    out = {"variants_tried_by_this_check": None}
    ent, mk, fb = ax.load()
    u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet", columns=["cond", "start", "end"])
    assert (u.start < OOS_START).all()
    u = u.set_index("cond")
    rec = pd.read_parquet(CACHE / "tr_sh500_improve1_fbB_norebate.parquet")

    # ---------------- A. reproduce headline
    A = {"all": quick(rec), REG: quick(rec[rec.regime == REG])}
    out["A_reproduce_recommended"] = A
    print("A", json.dumps(A, default=float)[:400], flush=True)

    # ---------------- B. tick-grid audit per match
    aud_f = CACHE / "verify_tick_audit.parquet"
    if aud_f.exists():
        aud = pd.read_parquet(aud_f)
    else:
        conds = ent.cond.unique()
        with ProcessPoolExecutor(workers) as ex:
            rows = list(ex.map(audit_job, [(c, u.at[c, "start"], u.at[c, "end"]) for c in conds], chunksize=32))
        aud = pd.DataFrame(rows, columns=["cond", "frac_mil_mid", "n_mid"])
        aud.to_parquet(aud_f)
    print(f"B audit done {time.time() - t0:.0f}s", flush=True)
    aud["tick_eff"] = np.where(aud.frac_mil_mid >= TICK_THR, 0.001, 0.01)
    E = ent[ent.acc_sh500].reset_index(drop=True).merge(aud[["cond", "frac_mil_mid", "tick_eff"]], on="cond", how="left")
    E["tick_eff"] = E.tick_eff.fillna(0.01)
    B = {"matches": int(len(aud)), "frac_mil_mid_quantiles": aud.frac_mil_mid.quantile([.1, .25, .5, .75, .9]).round(4).to_dict(),
         "share_matches_tick_eff_0.01": {str(th): float((aud.frac_mil_mid < th).mean()) for th in (0.02, 0.05, 0.10)},
         "share_entries_tick_eff_0.01": float((E.tick_eff == 0.01).mean()),
         "share_entries_1s5_tick_eff_0.01": float((E[E.regime == REG].tick_eff == 0.01).mean()),
         "simulator_tick_0.001_share_of_entries": float((E.tick == 0.001).mean())}
    out["B_tick_audit"] = B
    print("B", B, flush=True)

    # ---------------- C. snapped pricing + real tick, walk-forward re-run on cached touch fills (all IS)
    months = sorted(E.month.unique())
    mk0 = mk[(mk.sizing == 0) & (mk.model == 0)]
    grids = {"improve1_tick_eff": {}, "improve1_tick_eff_snapped": {}, "touch_snapped": {}, "improve1_repro": {}}
    snap_gap = []
    for (H, T), g in mk0.groupby(["H", "T"]):
        if T not in ax.TS:
            continue
        m = g.set_index("eid").reindex(E.eid)
        filled = m.filled.fillna(False).to_numpy(bool)
        px = m.px.to_numpy(float)
        up = E.dir.to_numpy() > 0
        sn = np.where(np.isfinite(px), snap(np.nan_to_num(px, nan=0.5), E.tick_eff.to_numpy(), up), np.nan)
        f = fb[(fb.H == H) & (fb["T"] == T)].set_index("eid").reindex(E.eid)
        fpx, fdt = f.px.to_numpy(float), f.dt.to_numpy(float)
        d = E.dir.to_numpy()
        grids["improve1_repro"][(H, T)] = pnl_frame(E, filled, px - d * E.tick.to_numpy(), fpx, fdt, m.dt.to_numpy(float))
        grids["improve1_tick_eff"][(H, T)] = pnl_frame(E, filled, px - d * E.tick_eff.to_numpy(), fpx, fdt, m.dt.to_numpy(float))
        grids["improve1_tick_eff_snapped"][(H, T)] = pnl_frame(E, filled, sn - d * E.tick_eff.to_numpy(), fpx, fdt, m.dt.to_numpy(float))
        grids["touch_snapped"][(H, T)] = pnl_frame(E, filled, sn, fpx, fdt, m.dt.to_numpy(float))
        if (H, T) == (30, 300):
            gap = (d * (px - sn))[filled]
            snap_gap = {"fills": int(filled.sum()), "share_fills_off_grid": float((np.abs(gap) > 1e-6).mean()),
                        "mean_price_overstatement_c": float(np.nanmean(gap) * 100),
                        "mean_overstatement_on_off_grid_fills_c": float(np.nanmean(gap[np.abs(gap) > 1e-6]) * 100),
                        "1s5_mean_price_overstatement_c": float(np.nanmean((d * (px - sn))[filled & (E.regime == REG).to_numpy()]) * 100)}
    out["C_snap_gap_H30_T300"] = snap_gap
    C = {}
    for name, grid in grids.items():
        wf, ch = wf_select(grid, months)
        C[name] = {"wf_choices": ch, "all": quick(wf), REG: quick(wf[wf.regime == REG])}
        if name == "improve1_tick_eff_snapped":
            wf.to_parquet(CACHE / "verify_tr_improve1_real.parquet")
        print("C", name, C[name]["all"]["ps_c"], C[name][REG]["ps_c"], C[name][REG]["ci_c"], ch[-3:], flush=True)
    # tick threshold sensitivity on the corrected improve1 at the WF cells chosen above
    sens = {}
    for th in (0.02, 0.10):
        te = np.where(E.frac_mil_mid.fillna(0) >= th, 0.001, 0.01)
        g = mk0[(mk0.H == 30) & (mk0["T"] == 300)].set_index("eid").reindex(E.eid)
        f = fb[(fb.H == 30) & (fb["T"] == 300)].set_index("eid").reindex(E.eid)
        px = g.px.to_numpy(float)
        sn = np.where(np.isfinite(px), snap(np.nan_to_num(px, nan=0.5), te, E.dir.to_numpy() > 0), np.nan)
        tr = pnl_frame(E, g.filled.fillna(False).to_numpy(bool), sn - E.dir.to_numpy() * te, f.px.to_numpy(float),
                       f.dt.to_numpy(float), g.dt.to_numpy(float))
        sens[str(th)] = quick(tr[tr.regime == REG], 300)
    C["improve1_real_H30T300_1s5_tick_threshold_sensitivity"] = sens
    out["C_pricing_walkforward"] = C

    # ---------------- D. re-simulation of 1s/5% entries
    sim_f = CACHE / "verify_sim_1s5.parquet"
    E5 = E[E.regime == REG]
    if sim_f.exists():
        sim = pd.read_parquet(sim_f)
    else:
        s_all = ent  # every shadow entry (accepted or not) for the own-print mask
        groups = dict(tuple(s_all[s_all.cond.isin(E5.cond.unique())].groupby("cond", sort=False)))
        te = aud.set_index("cond").tick_eff
        jobs = [(c, groups[c], u.at[c, "start"], u.at[c, "end"], float(te.get(c, 0.01))) for c in E5.cond.unique()]
        parts = []
        with ProcessPoolExecutor(workers) as ex:
            for n, r in enumerate(ex.map(sim_job, jobs, chunksize=8)):
                if r is not None:
                    parts.append(r)
                if n % 500 == 0:
                    print(f"  sim {n}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
        sim = pd.concat(parts, ignore_index=True)
        sim.to_parquet(sim_f)
    print(f"D sim done {time.time() - t0:.0f}s", flush=True)
    D = {}
    for H, T in CELLS:
        s = sim[(sim.H == H) & (sim["T"] == T)].set_index("eid").reindex(E5.eid)
        cache = mk0[(mk0.H == H) & (mk0["T"] == T)].set_index("eid").reindex(E5.eid)
        same = (s.touch_filled.to_numpy(bool) == cache.filled.fillna(False).to_numpy(bool))
        samepx = np.allclose(np.nan_to_num(s.touch_px.to_numpy(float)), np.nan_to_num(cache.px.to_numpy(float)), atol=1e-6)
        f = fb[(fb.H == H) & (fb["T"] == T)].set_index("eid").reindex(E5.eid)
        fpx, fdt = f.px.to_numpy(float), f.dt.to_numpy(float)
        d = E5.dir.to_numpy()
        up = d > 0
        te = E5.tick_eff.to_numpy()
        cell = {"replica_fill_agreement": float(same.mean()), "replica_px_identical": bool(samepx)}

        def run(name, filled, px, dt):
            tr = pnl_frame(E5, filled, px, fpx, fdt, dt)
            cell[name] = quick(tr)
            return tr

        tpx = s.touch_px.to_numpy(float)
        tsn = np.where(np.isfinite(tpx), snap(np.nan_to_num(tpx, nan=0.5), te, up), np.nan)
        tf = s.touch_filled.to_numpy(bool)
        run("authors_improve1", tf, tpx - d * E5.tick.to_numpy(), s.touch_dt.to_numpy(float))
        run("authors_touch", tf, tpx, s.touch_dt.to_numpy(float))
        run("touch_snapped_front_of_queue", tf, tsn, s.touch_dt.to_numpy(float))
        tr_real = run("improve1_tick_eff_snapped", tf, tsn - d * te, s.touch_dt.to_numpy(float))
        npx = s.touch_nomask_px.to_numpy(float)
        nsn = np.where(np.isfinite(npx), snap(np.nan_to_num(npx, nan=0.5), te, up), np.nan)
        nf = s.touch_nomask_filled.to_numpy(bool)
        run("authors_improve1_nomask", nf, npx - d * E5.tick.to_numpy(), s.touch_nomask_dt.to_numpy(float))
        run("improve1_tick_eff_snapped_nomask", nf, nsn - d * te, s.touch_nomask_dt.to_numpy(float))
        for Q in QS:
            for mode in ("cons", "repeg"):
                k = f"q{Q}_{mode}"
                if f"{k}_filled" not in s:
                    continue
                run(f"queue_{k}", s[f"{k}_filled"].fillna(False).to_numpy(bool), s[f"{k}_px"].to_numpy(float),
                    s[f"{k}_dt"].to_numpy(float))
        room = s.room.to_numpy(float)
        cell["room_at_touch_fills"] = {"share_room": float(np.nanmean(room[tf] == 1)), "share_no_room": float(np.nanmean(room[tf] == 0)),
                                       "share_unknown": float(np.isnan(room[tf]).mean())}
        # mixed: improve where room (unknown counted as room), else touch queue Q=2000 (conservative)
        qf = s["q2000_cons_filled"].fillna(False).to_numpy(bool)
        qpx = s["q2000_cons_px"].to_numpy(float)
        mf = np.where(tf & (room != 0), True, qf)
        mpx = np.where(tf & (room != 0), tsn - d * te, qpx)
        mdt = np.where(tf & (room != 0), s.touch_dt.to_numpy(float), s["q2000_cons_dt"].to_numpy(float))
        tr_mix = run("mixed_improve_if_room_else_queue2000", mf, mpx, mdt)
        mf2 = np.where(tf & (room == 1), True, qf)
        mpx2 = np.where(tf & (room == 1), tsn - d * te, qpx)
        mdt2 = np.where(tf & (room == 1), s.touch_dt.to_numpy(float), s["q2000_cons_dt"].to_numpy(float))
        run("mixed_improve_if_room_known_else_queue2000", mf2, mpx2, mdt2)

        # ---- D2: partial-fill queue model
        def runp(name, frac, px, dt):
            tr = pnl_frame_partial(E5, frac, px, fpx, fdt, dt)
            cell[name] = quick(tr)
            cell[name]["mean_maker_frac"] = float(np.mean(frac))
            return tr
        pf = {}
        for c in s.columns:
            if c.startswith("pf_") and c.endswith("_frac"):
                k = c[:-5]
                pf[k] = runp(k, s[c].fillna(0).to_numpy(float), s[f"{k}_px"].to_numpy(float), s[f"{k}_dt"].to_numpy(float))
        # mixed on the partial-fill model: improve 1 tick_eff inside where the room proxy is not "no room"
        # (unknown counted as room, generous), else join the touch queue with Q = 2000 / Q = 500
        for qq in (500, 2000):
            fr_i, px_i = s["pf_improve_repeg_frac"].fillna(0).to_numpy(float), s["pf_improve_repeg_px"].to_numpy(float)
            fr_q, px_q = s[f"pf_q{qq}_repeg_frac"].fillna(0).to_numpy(float), s[f"pf_q{qq}_repeg_px"].to_numpy(float)
            use = room != 0  # room proxy evaluated at the touch-model fill; NaN (no touch fill / stale) counts as room
            tr_pm = runp(f"pf_mixed_improve_if_room_else_q{qq}_repeg", np.where(use, fr_i, fr_q), np.where(use, px_i, px_q),
                         np.where(use, s["pf_improve_repeg_dt"].to_numpy(float), s[f"pf_q{qq}_repeg_dt"].to_numpy(float)))
            if (H, T) == (30, 300) and qq == 2000:
                tr_pm.to_parquet(CACHE / "verify_tr_1s5_pf_mixed.parquet")
        if (H, T) == (30, 300):
            tr_real.to_parquet(CACHE / "verify_tr_1s5_improve1_real.parquet")
            tr_mix.to_parquet(CACHE / "verify_tr_1s5_mixed.parquet")
        D[f"H{H}_T{T}"] = cell
        print("D", H, T, {k: (round(v["ps_c"], 3), [round(x, 2) for x in v["ci_c"]]) for k, v in cell.items() if isinstance(v, dict) and "ps_c" in v}, flush=True)
    out["D_resim_1s5"] = D

    # ---------------- E. min order, concentration, clustering, deflated Sharpe
    r5 = rec[rec.regime == REG].merge(E[["eid", "wallet"]], on="eid", how="left")
    Ed = {}
    Ed["min_order_5"] = {"share_entries_lt5_all": float((rec.shares < 5).mean()), "share_entries_lt5_1s5": float((r5.shares < 5).mean()),
                         "recommended_1s5_excl_lt5": quick(r5[r5.shares >= 5]) if "wallet" in r5 else None}
    w = r5.groupby("wallet").agg(n=("pnl", "size"), pnl=("pnl", "sum"), ps=("pnl_ps", "mean")).sort_values("pnl", ascending=False)
    Ed["wallets_1s5"] = {"n_wallets": int(len(w)), "top1_share_of_pnl": float(w.pnl.iloc[0] / w.pnl.sum()),
                         "top3_share_of_pnl": float(w.pnl.iloc[:3].sum() / w.pnl.sum()),
                         "top1_share_of_trades": float(w.n.iloc[0] / w.n.sum()),
                         "drop_top1_ps_c": float(r5[~r5.wallet.isin(w.index[:1])].pnl_ps.mean() * 100),
                         "drop_top3_ps_c": float(r5[~r5.wallet.isin(w.index[:3])].pnl_ps.mean() * 100),
                         "wallets_negative_ps": int((w.ps < 0).sum()),
                         "top5": w.head(5).assign(ps=lambda x: x.ps * 100).round(3).reset_index().assign(wallet=lambda x: x.wallet.str[:10]).to_dict("records")}
    mm = r5.groupby("cond").pnl.sum().sort_values(ascending=False)
    Ed["matches_1s5"] = {"n": int(len(mm)), "top10_share_of_pnl": float(mm.iloc[:10].sum() / mm.sum()),
                         "top1pct_share_of_pnl": float(mm.iloc[:max(1, len(mm) // 100)].sum() / mm.sum())}
    dd = r5.groupby("date").pnl.sum()
    Ed["days_1s5"] = {"n_days": int(len(dd)), "positive_days": int((dd > 0).sum()),
                      "weekly_positive": f"{int((r5.groupby(r5.date.dt.to_period('W')).pnl.sum() > 0).sum())}/{r5.date.dt.to_period('W').nunique()}"}
    Ed["day_cluster_ci_1s5"] = {"recommended": day_cluster_ci(r5)}
    rr = pd.read_parquet(CACHE / "verify_tr_1s5_improve1_real.parquet")
    Ed["day_cluster_ci_1s5"]["improve1_tick_eff_snapped"] = day_cluster_ci(rr)
    # deflated Sharpe on daily P&L
    def daily_of(tr):
        d = tr.groupby("date").pnl.sum()
        return d.reindex(pd.date_range(d.index.min(), d.index.max(), freq="D", tz="UTC"), fill_value=0.0)
    n_mine = None
    Ed["deflated_sharpe"] = {}
    for lab, tr in (("recommended_all_IS", rec), ("recommended_1s5", rec[rec.regime == REG]),
                    ("improve1_real_1s5", rr)):
        Ed["deflated_sharpe"][lab] = {str(N): deflated_sharpe(daily_of(tr), N) for N in (20, 100, 902, 940)}
    out["E_robustness"] = Ed

    # monthly series of the corrected recommended rule (real tick + snapped price, WF re-run on all IS)
    wr = pd.read_parquet(CACHE / "verify_tr_improve1_real.parquet")
    bm = wr.groupby("month").apply(lambda g: pd.Series({"n": len(g), "ps_c": g.pnl_ps.mean() * 100, "pnl_usd": g.pnl.sum(),
                                                         "H": g.H.iloc[0], "T": g["T"].iloc[0]}), include_groups=False)
    out["F_corrected_improve1_wf_by_month"] = bm.reset_index().to_dict("records")
    out["F_corrected_improve1_wf_months_positive"] = f"{int((bm.ps_c > 0).sum())}/{len(bm)}"
    # entry timing: share of 1s/5% fast-tier entries in the same second as the jump onset (order sent >= 1 s earlier)
    sh = pd.read_parquet(ROOT / "data/derived/shadow_is_uncapped.parquet", columns=["since", "delay", "fee_rate", "mo30", "fee"])
    g = sh[(sh.delay == 1) & (sh.fee_rate == 0.05)]
    out["G_entry_timing_1s5"] = {"n": int(len(g)), "share_since_0s": float((g.since < 0.5).mean()),
                                 "net30_c_by_since": {str(k): float((v.mo30 - v.fee).mean() * 100) for k, v in g.groupby(g.since.round())}}

    # variants evaluated by this script (stress scenarios, not selected on P&L)
    n_c = 4 * 20  # four pricing grids x 20 cells (walk-forward re-run)
    n_d = len(CELLS) * (6 + len(QS) + 2 + 2 + (len(QS) + 3) + 2 + 2)  # per cell: 6 pricing/mask, queue cons+repeg, 2 mixed, pf cons+repeg, pf improve x2, pf mixed x2
    out["variants_tried_by_this_check"] = {"C_grids": n_c, "C_tick_threshold": 2, "D_scenarios": n_d,
                                           "total": n_c + 2 + n_d,
                                           "note": "stress scenarios; none chosen on P&L; the lens's own count is 902"}
    (HERE / "verify_realism.json").write_text(json.dumps(out, indent=1, default=float))
    print(f"done {time.time() - t0:.0f}s")
    return out


if __name__ == "__main__":
    main()
