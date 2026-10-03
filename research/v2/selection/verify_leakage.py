"""Adversarial reviewer: independent re-computation + leakage checks for the selection lens (IS only).

    .venv/bin/python research/v2/selection/verify_leakage.py        (from the repo root, ~3-5 min, 1 core)

Does NOT import the lens engine (common.py / qualify_grid.py). Re-implements the stated rules from the raw
IS files, then:
  A. contamination: universe/prints/is_prints all IS; lens code never touches data/locked
  B. integrity: per-print fee rate / delay = the match's own (universe), mo_res sign, dir domain
  C. baseline wallet sets vs the original H6 code (src.fasttier.qualify) month by month
  D. full 288-variant grid + nested meta-choice, re-derived; TRUNCATION TEST: for each month m the whole
     procedure is re-run on a copy of the data with every print of month >= m deleted and must give the same
     choice and the same selected wallets for m
  E. headline numbers (whole IS and 1 s / 5%) and the paired difference vs the H6 baseline
  F. adversarial extras: $-weighted vs trade-weighted, per-month 1 s / 5%, longshot / big-ticket share,
     and the same selection evaluated on trade sets that need NO hindsight (all buckets; 0-3 s after the
     jump detector actually fired)
Writes research/v2/selection/out/verify_leakage.json
"""
from __future__ import annotations

import itertools
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
OOS = pd.Timestamp("2026-08-25 14:15", tz="UTC")
T0 = time.time()
CHECKS: dict = {}
REPORT: dict = {}


def check(name, ok, info=""):
    CHECKS[name] = bool(ok)
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{info}]" if info != "" else ""), flush=True)


# ------------------------------------------------------------------------------------------- A. contamination
u = pd.read_parquet(ROOT / "data/derived/universe_is.parquet",
                    columns=["cond", "start", "end", "fee_rate", "delay", "res0"])
check("A1 universe_is: every match starts before OOS", u.start.max() < OOS, str(u.start.max()))
P = pd.read_parquet(ROOT / "data/derived/prints_0_3s_is.parquet",
                    columns=["cond", "ts", "p", "dir", "usd", "wallet", "since", "fee_rate", "delay", "res", "mo30",
                             "mo_res", "bucket"])
check("A2 0-3s prints: every cond in IS universe", P.cond.isin(set(u.cond)).all())
st = P.cond.map(u.set_index("cond").start)
check("A3 0-3s prints: every match start < OOS", bool((st < OOS).all()), f"max print ts "
      f"{pd.to_datetime(P.ts.max(), unit='s')} (match started {st.max()})")
ic = set()
for _b in pq.ParquetFile(ROOT / "data/is_prints.parquet").iter_batches(batch_size=1_000_000, columns=["cond"]):
    ic |= set(_b.column(0).unique().to_pylist())
check("A4 is_prints.parquet (used by decay.all_buckets): conds subset of IS universe", ic <= set(u.cond))
hits = []
for f in sorted(HERE.glob("*.py")):
    if f.name == "verify_leakage.py":
        continue
    for i, line in enumerate(f.read_text().splitlines(), 1):
        if re.search(r"locked|oos_prints|data/live|gamma-api|data-api|load_tape|fetch", line):
            hits.append(f"{f.name}:{i}: {line.strip()}")
check("A5 lens code: no reference to data/locked, OOS prints, live data or API fetches outside docstrings",
      all("Nothing here reads" in h or "data/locked/ or any OOS" in h for h in hits), hits)

# ----------------------------------------------------------------------------------------------- B. integrity
um = u.set_index("cond")
check("B1 print fee_rate == its own match's universe fee_rate", (P.fee_rate.to_numpy() == P.cond.map(um.fee_rate).to_numpy()).all())
check("B2 print delay == its own match's universe delay", (P.delay.to_numpy() == P.cond.map(um.delay).to_numpy()).all())
check("B3 dir in {-1,+1}", set(np.unique(P.dir)) <= {-1.0, 1.0})
r0 = P.cond.map(um.res0).to_numpy()
exp_mores = np.where(np.isin(r0, [0.0, 1.0]), P.dir * (r0 - P.p), np.nan)
check("B4 mo_res == dir*(res0 - p) (outcome-0 frame; NaN for 50/50)",
      np.allclose(exp_mores, P.mo_res, equal_nan=True))
check("B5 since in [0,3) for the 0-3 s file", bool(((P.since >= 0) & (P.since < 3)).all()))

# ------------------------------------------------------------------------------------- derived columns (mine)
dt_ = pd.to_datetime(P.ts, unit="s")
P["mi"] = (dt_.dt.year * 12 + dt_.dt.month - 1).astype(int)          # month index
P["date"] = dt_.dt.floor("D")
P["pq"] = P.p * (1 - P.p)
P["fee"] = P.fee_rate * P.pq                                          # symmetric: same for outcome-1 buyer
P["net30"] = P.mo30 - P.fee
P["net_res"] = P.mo_res - P.fee
P["px"] = np.where(P.dir > 0, P.p, 1 - P.p)                           # price of the token actually bought
P["usd_in"] = P.usd.clip(upper=1000.0)
P["shares"] = P.usd_in / P.px
P["r15"] = (P.delay < 3) & (P.fee_rate >= 0.04)
P["mo30sq"] = P.mo30 ** 2
MONTHS = sorted(P.mi.unique())
EVAL = MONTHS[2:]
lab = lambda mi: f"{mi // 12}-{mi % 12 + 1:02d}"


def fee_now(mi, uu):
    t0 = pd.Timestamp(year=mi // 12, month=mi % 12 + 1, day=1, tz="UTC")
    prev = uu[uu.start < t0].sort_values("start")
    return float(prev.fee_rate.iloc[-1]) if len(prev) else 0.0


FEE_NOW = {m: fee_now(m, u) for m in MONTHS + [MONTHS[-1] + 1]}
REPORT["fee_now"] = {lab(m): v for m, v in FEE_NOW.items()}
print("fee_now by month:", REPORT["fee_now"])


def wallet_month(Pp):
    return Pp.groupby(["wallet", "mi"], observed=True).agg(
        n=("ts", "size"), nv=("mo30", "count"), s1=("mo30", "sum"), s2=("mo30sq", "sum"), spq=("pq", "sum"),
        nm=("cond", "nunique")).reset_index()


def weights(age, look):
    if look == "all":
        return np.ones(len(age))
    if look.endswith("m"):
        return (age <= int(look[:-1])).astype(float)
    return 0.5 ** ((age - 1) / float(look[2:]))


def scores(A, m, look, mm, fee):
    h = A[A.mi < m]
    w = weights((m - h.mi).to_numpy(), look)
    z = pd.DataFrame({"wallet": h.wallet.to_numpy(), "n": w * h.n, "nv": w * h.nv, "nv2": w * w * h.nv,
                      "s1": w * h.s1, "s2": w * h.s2, "spq": w * h.spq, "nm": w * h.nm, "nm2": w * w * h.nm})
    z = z[w > 0].groupby("wallet").sum()
    z = z[(z.n >= 3 * mm) & (z.nm >= mm) & (z.nv > 1)]
    mean = z.s1 / z.nv
    var = ((z.s2 - z.nv * mean ** 2) / (z.nv - z.nv2 / z.nv)).clip(lower=0)
    se = np.sqrt(var) / np.sqrt(z.nm ** 2 / z.nm2)
    s = pd.DataFrame({"mean": mean, "se": se, "sd": np.sqrt(var), "fw": fee * z.spq / z.n})
    s = s[s.sd > 0]
    s["t"] = s["mean"] / s.se
    s["tnet"] = (s["mean"] - s.fw) / s.se
    if len(s) >= 5:                                                   # DerSimonian-Laird
        wi = 1 / s.se ** 2
        mfe = (wi * s["mean"]).sum() / wi.sum()
        Q = (wi * (s["mean"] - mfe) ** 2).sum()
        tau2 = max(0.0, (Q - (len(s) - 1)) / (wi.sum() - (wi ** 2).sum() / wi.sum()))
        ws = 1 / (s.se ** 2 + tau2)
        mu0 = (ws * s["mean"]).sum() / ws.sum()
        B = tau2 / (tau2 + s.se ** 2)
        s["eb"] = mu0 + B * (s["mean"] - mu0)
    else:
        s["eb"] = s["mean"]
    s["ebnet"] = s.eb - s.fw
    return s


def pick(s, score, thr):
    if s.empty:
        return set()
    if score == "t":
        return set(s.index[s.t > thr])
    if score == "top":
        return set(s[s.t > 2].sort_values("t", ascending=False).index[: int(thr)])
    if score == "tnet":
        return set(s.index[s.tnet > thr])
    if score == "eb":
        return set(s.index[s.ebnet > thr])
    raise ValueError(score)


LOOKS = ["all", "1m", "2m", "3m", "6m", "ew1", "ew2", "ew3"]
SCORES = [("t", 2), ("t", 3), ("t", 4), ("t", 5), ("top", 10), ("top", 25), ("top", 50),
          ("tnet", 2), ("tnet", 3), ("eb", 0.0), ("eb", 0.0025), ("eb", 0.005)]
MMS = [5, 10, 20]
GRID = [(l, s, t, mm) for l, (s, t), mm in itertools.product(LOOKS, SCORES, MMS)]
name = lambda r: f"{r[0]}|{r[1]}{(f'{r[2] * 100:g}c' if r[1] == 'eb' else f'{r[2]:g}')}|mm{r[3]}"
BASE = ("all", "t", 3.0, 10)
BYM = {m: g for m, g in P.groupby("mi")}


def cap(tr):
    tr = tr.sort_values("ts", kind="stable")
    return tr[tr.groupby("cond").usd_in.cumsum() <= 3000.0]


def trades(selmap, src=BYM):
    parts = [src[m][src[m].wallet.isin(sel)] for m, sel in selmap.items() if sel]
    return cap(pd.concat(parts)) if parts else P.iloc[:0]


class Grid:
    """All 288 variants on a (possibly truncated) print set."""

    def __init__(self, Pp, months_eval, uu):
        self.A = wallet_month(Pp)
        self.bym = {m: g for m, g in Pp.groupby("mi")}
        self.months = months_eval
        self.fee = {m: fee_now(m, uu) for m in months_eval}
        self._sc = {}

    def sc(self, m, look, mm):
        k = (m, look, mm)
        if k not in self._sc:
            self._sc[k] = scores(self.A, m, look, mm, self.fee[m])
        return self._sc[k]

    def sel(self, r, m):
        return pick(self.sc(m, r[0], r[3]), r[1], r[2])

    def month_rows(self, r):
        tr = trades({m: self.sel(r, m) for m in self.months}, self.bym)
        g = tr.assign(a=tr.shares * tr.mo30.fillna(0), b=tr.shares * tr.pq).groupby("mi")[["a", "b"]].sum()
        return g.reindex(self.months, fill_value=0.0)

    def nested(self, min_hist=3):
        rows = {r: self.month_rows(r) for r in GRID}
        ch = {}
        for i, m in enumerate(self.months):
            if i < min_hist:
                ch[m] = BASE
                continue
            best, bv = None, -np.inf
            for r in GRID:
                x = rows[r].loc[self.months[:i]]
                v = float((x.a - FEE_NOW[m] * x.b).sum())
                if v > bv:
                    best, bv = r, v
            ch[m] = best if bv > 0 else None
        return ch, rows


# ------------------------------------------------------------------------------------- C. baseline vs H6 code
from src import fasttier  # noqa: E402  (original H6 qualify, a different code path)

G = Grid(P, EVAL, u)
mism = {}
for m in EVAL:
    past = P[P.mi < m].assign(bucket="0-3s")
    h6 = set(fasttier.qualify(past))
    mine = G.sel(BASE, m)
    if h6 != mine:
        mism[lab(m)] = {"h6_only": len(h6 - mine), "mine_only": len(mine - h6)}
check("C1 baseline wallet sets == src.fasttier.qualify for every month", not mism, mism)
bt = trades({m: G.sel(BASE, m) for m in EVAL})
check("C2 baseline shadow trades == 131,414 (lens/H6 claim)", len(bt) == 131414, len(bt))

# ---------------------------------------------------------------------------- D. grid + nested + truncation test
CH, ROWS = G.nested()
claimed = json.loads((HERE / "results.json").read_text())["nested_choices_stage1"]
mine_ch = {lab(m): (name(r) if r else "stand_aside") for m, r in CH.items()}
REPORT["nested_choice_mine"] = mine_ch
check("D1 re-derived nested choices == lens's", mine_ch == claimed, mine_ch)
frozen = max(GRID, key=lambda r: float((ROWS[r].a - 0.05 * ROWS[r].b).sum()))
check("D2 frozen next-month rule (all IS months, 5% fee) == ew2|eb0.5c|mm5", name(frozen) == "ew2|eb0.5c|mm5", name(frozen))

trunc_bad = {}
for i, m in enumerate(EVAL):
    if i < 3:
        continue
    Pt = P[P.mi < m]                                   # delete month m and everything after it
    ut = u[u.start < pd.Timestamp(year=m // 12, month=m % 12 + 1, day=1, tz="UTC")]
    Gt = Grid(Pt, EVAL[:i], ut)
    Gt.fee[m] = fee_now(m, ut)
    # choice for m from truncated data: re-run the meta step with month m appended as "next"
    rows_t = {r: Gt.month_rows(r) for r in GRID}
    best, bv = None, -np.inf
    for r in GRID:
        v = float((rows_t[r].a - fee_now(m, ut) * rows_t[r].b).sum())
        if v > bv:
            best, bv = r, v
    best = best if bv > 0 else None
    same_choice = best == CH[m]
    same_sel = (best is None) or (Gt.sel(best, m) == G.sel(CH[m], m))
    if not (same_choice and same_sel):
        trunc_bad[lab(m)] = {"trunc": name(best) if best else None, "full": name(CH[m]) if CH[m] else None,
                             "same_sel": same_sel}
    print(f"   truncation {lab(m)}: trunc choice {name(best) if best else None} | full {name(CH[m])} | "
          f"same wallets {same_sel}  ({time.time() - T0:.0f}s)", flush=True)
check("D3 truncation test: data >= m deleted gives identical choice and wallets for every m", not trunc_bad, trunc_bad)

# ---------------------------------------------------------------------------------------- E. headline numbers
NT = trades({m: (G.sel(CH[m], m) if CH[m] else set()) for m in EVAL})
rng0 = np.random.default_rng(0)


def boot_ratio(tr, col, n=2000, seed=0):
    g = tr.groupby("cond")[col].agg(["sum", "count"]).to_numpy()
    rng = np.random.default_rng(seed)
    b = [(lambda x: x[:, 0].sum() / x[:, 1].sum())(g[rng.integers(0, len(g), len(g))]) for _ in range(n)]
    return [round(float(np.percentile(b, 2.5) * 100), 3), round(float(np.percentile(b, 97.5) * 100), 3)]


def paired(a, b, col, n=2000, seed=0):
    ga = a.groupby("cond")[col].agg(["sum", "count"])
    gb = b.groupby("cond")[col].agg(["sum", "count"])
    S = ga.join(gb, lsuffix="a", rsuffix="b", how="outer").fillna(0).to_numpy()
    f = lambda x: x[:, 0].sum() / x[:, 1].sum() - x[:, 2].sum() / x[:, 3].sum()
    rng = np.random.default_rng(seed)
    bs = [f(S[rng.integers(0, len(S), len(S))]) for _ in range(n)]
    return round(float(f(S) * 100), 3), [round(float(np.percentile(bs, 2.5) * 100), 3),
                                          round(float(np.percentile(bs, 97.5) * 100), 3)]


def stats(tr, days=None):
    pnl = tr.shares * tr.net_res
    d = pnl.groupby(tr.date).sum()
    if days is not None:
        d = d.reindex(days, fill_value=0.0)
    v = tr.net30.notna()
    return {"n": int(len(tr)), "net30_c": round(tr.net30.mean() * 100, 3), "net30_ci": boot_ratio(tr, "net30"),
            "net_res_c": round(tr.net_res.mean() * 100, 3), "net_res_ci": boot_ratio(tr, "net_res"),
            "net30_share_wtd_c": round(float((tr.shares * tr.net30).sum() / tr.shares[v].sum() * 100), 3),
            "pnl_usd": round(float(pnl.sum())), "pnl30_usd": round(float((tr.shares * tr.net30).sum())),
            "usd_in": round(float(tr.usd_in.sum())),
            "sharpe": round(float(d.mean() / d.std() * np.sqrt(365)), 2)}


DAYS_ALL = pd.date_range(pd.Timestamp(year=EVAL[0] // 12, month=EVAL[0] % 12 + 1, day=1), P.date.max(), freq="D")
DAYS_15 = pd.date_range(pd.Timestamp("2026-07-01"), P.date.max(), freq="D")
E = {"nested_all": stats(NT, DAYS_ALL), "baseline_all": stats(bt, DAYS_ALL),
     "nested_1s5": stats(NT[NT.r15], DAYS_15), "baseline_1s5": stats(bt[bt.r15], DAYS_15),
     "paired_1s5_net30": paired(NT[NT.r15], bt[bt.r15], "net30"),
     "paired_1s5_net_res": paired(NT[NT.r15], bt[bt.r15], "net_res"),
     "paired_all_net30": paired(NT, bt, "net30")}
REPORT["headline_recomputed"] = E
for k, v in E.items():
    print(f"   {k}: {v}")
cl = {"nested_1s5_net30": 1.167, "nested_1s5_net_res": 1.338, "base_1s5_net30": 0.621, "base_1s5_net_res": 0.544,
      "nested_all_net_res": 1.759, "nested_all_net30": 1.450}
mine = {"nested_1s5_net30": E["nested_1s5"]["net30_c"], "nested_1s5_net_res": E["nested_1s5"]["net_res_c"],
        "base_1s5_net30": E["baseline_1s5"]["net30_c"], "base_1s5_net_res": E["baseline_1s5"]["net_res_c"],
        "nested_all_net_res": E["nested_all"]["net_res_c"], "nested_all_net30": E["nested_all"]["net30_c"]}
check("E1 headline per-share numbers reproduce to 0.005c", all(abs(mine[k] - cl[k]) < 0.005 for k in cl), mine)
check("E2 nested trade count == 90,143", len(NT) == 90143, len(NT))

# ---------------------------------------------------------------------------------------- F. adversarial extras
F = {}
G1 = Grid(P, EVAL, u)
# F1: is "every one of the 288 variants beats the baseline on net30 in 1s/5%" true?
v15 = {}
for r in GRID:
    tr = trades({m: G1.sel(r, m) for m in EVAL})
    t5 = tr[tr.r15]
    v15[name(r)] = (t5.net30.mean() * 100, float((t5.shares * t5.net_res).sum()), float((t5.shares * t5.net30).sum()))
b15 = v15[name(BASE)]
F["grid_variants_below_baseline_net30_1s5"] = int(sum(x[0] < b15[0] for x in v15.values()))
F["grid_variants_below_baseline_pnl_res_1s5"] = int(sum(x[1] < b15[1] for x in v15.values()))
F["grid_variants_below_baseline_pnl30_1s5"] = int(sum(x[2] < b15[2] for x in v15.values()))
check("F1 claim 'all 288 variants beat the baseline on net30 in 1s/5%'",
      F["grid_variants_below_baseline_net30_1s5"] == 0,
      f"{F['grid_variants_below_baseline_net30_1s5']} variants below baseline net30; "
      f"{F['grid_variants_below_baseline_pnl_res_1s5']} below baseline $ P&L (net_res); "
      f"{F['grid_variants_below_baseline_pnl30_1s5']} below baseline $ pnl30")

# F2: per month in 1s/5%
pm = []
for nm_, tr in (("nested", NT), ("baseline", bt)):
    t5 = tr[tr.r15]
    for m, g in t5.groupby("mi"):
        pm.append({"series": nm_, "month": lab(m), "n": len(g), "net30_c": round(g.net30.mean() * 100, 3),
                   "net_res_c": round(g.net_res.mean() * 100, 3), "pnl": round(float((g.shares * g.net_res).sum())),
                   "pnl30": round(float((g.shares * g.net30).sum()))})
F["per_month_1s5"] = pm
# F3: where the $ comes from in 1s/5% (nested)
t5 = NT[NT.r15].assign(pnl=lambda x: x.shares * x.net_res, pnl30=lambda x: x.shares * x.net30)
tot = t5.pnl.sum()
F["nested_1s5_pnl_share_px_lt_0.15"] = round(float(t5.pnl[t5.px < 0.15].sum() / tot), 3)
F["nested_1s5_pnl_share_usd_ge_1k"] = round(float(t5.pnl[t5.usd >= 1000].sum() / tot), 3)
F["nested_1s5_pnl30_share_usd_ge_1k"] = round(float(t5.pnl30[t5.usd >= 1000].sum() / t5.pnl30.sum()), 3)
F["nested_1s5_top20_matches_pnl_share"] = round(float(t5.groupby("cond").pnl.sum().nlargest(20).sum() / tot), 3)

# F4: no-hindsight trade sets. Same (wallet, month) selections, but trades defined WITHOUT the hindsight onset:
#     (a) all buckets, (b) 0-3 s after the jump DETECTOR fired (detect_ts known at decision time)
selN = {m: (G.sel(CH[m], m) if CH[m] else set()) for m in EVAL}
selB = {m: G.sel(BASE, m) for m in EVAL}
union = set().union(*selN.values(), *selB.values())
cols = ["cond", "ts", "p", "dir", "usd", "wallet", "fee_rate", "delay", "mo30", "mo_res", "bucket"]
parts = []
for b in pq.ParquetFile(ROOT / "data/is_prints.parquet").iter_batches(batch_size=500_000, columns=cols):
    x = b.to_pandas()
    x = x[x.wallet.isin(union)]
    if len(x):
        parts.append(x)
X = pd.concat(parts, ignore_index=True)
assert X.cond.isin(set(u.cond)).all()
d2 = pd.to_datetime(X.ts, unit="s")
X["mi"] = (d2.dt.year * 12 + d2.dt.month - 1).astype(int)
X["date"] = d2.dt.floor("D")
X["pq"] = X.p * (1 - X.p)
X["fee"] = X.fee_rate * X.pq
X["net30"], X["net_res"] = X.mo30 - X.fee, X.mo_res - X.fee
X["px"] = np.where(X.dir > 0, X.p, 1 - X.p)
X["usd_in"] = X.usd.clip(upper=1000.0)
X["shares"] = X.usd_in / X.px
X["r15"] = (X.delay < 3) & (X.fee_rate >= 0.04)
J = pd.read_parquet(ROOT / "data/derived/jumps_is.parquet", columns=["cond", "detect_ts"])
jd = {c: np.sort(g.detect_ts.to_numpy()) for c, g in J.groupby("cond")}
sdet = np.full(len(X), -1.0)
for c, ix in X.groupby("cond").indices.items():
    a = jd.get(c)
    if a is None:
        continue
    tt = X.ts.to_numpy()[ix]
    k = np.searchsorted(a, tt, "right") - 1
    sdet[ix] = np.where(k >= 0, tt - a[np.maximum(k, 0)], -1.0)
X["since_det"] = sdet
XB = {m: g for m, g in X.groupby("mi")}
sets = {"all_buckets": lambda g: g, "det_0_3s": lambda g: g[(g.since_det >= 0) & (g.since_det < 3)],
        "not_0_3s_onset": lambda g: g[g.bucket.astype(str) != "0-3s"]}
nh = {}
for sname, f in sets.items():
    src = {m: f(g) for m, g in XB.items()}
    a = trades(selN, src)
    b_ = trades(selB, src)
    a5, b5 = a[a.r15], b_[b_.r15]
    nh[sname] = {"nested_1s5": {"n": len(a5), "net30_c": round(a5.net30.mean() * 100, 3),
                                "net_res_c": round(a5.net_res.mean() * 100, 3),
                                "pnl30": round(float((a5.shares * a5.net30).sum()))},
                 "baseline_1s5": {"n": len(b5), "net30_c": round(b5.net30.mean() * 100, 3),
                                  "net_res_c": round(b5.net_res.mean() * 100, 3),
                                  "pnl30": round(float((b5.shares * b5.net30).sum()))},
                 "paired_1s5_net30": paired(a5, b5, "net30"),
                 "nested_all_net30_c": round(a.net30.mean() * 100, 3),
                 "baseline_all_net30_c": round(b_.net30.mean() * 100, 3)}
    print(f"   no-hindsight set {sname}: {nh[sname]}", flush=True)
F["no_hindsight_trade_sets"] = nh
REPORT["adversarial"] = F
for k, v in F.items():
    if k != "no_hindsight_trade_sets":
        print(f"   {k}: {v}")

REPORT["checks"] = CHECKS
(HERE / "out" / "verify_leakage.json").write_text(json.dumps(REPORT, indent=1, default=str))
print(f"done in {time.time() - T0:.0f}s; {sum(CHECKS.values())}/{len(CHECKS)} checks pass")
