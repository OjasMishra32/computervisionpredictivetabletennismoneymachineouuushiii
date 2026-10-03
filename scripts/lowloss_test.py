"""Pre-registered tests of the frozen v2-safe rule (research/v2/lowloss/PREREG.md, committed 342d515).

    .venv/bin/python scripts/lowloss_test.py            # ~1 min, 1 process
    .venv/bin/python scripts/lowloss_test.py --rebuild  # ignore the feature caches
    .venv/bin/python scripts/lowloss_test.py --figure-only  # redraw daily_pnl.png from saved outputs

(a) burned OOS, NON-BLIND: P = is_prints + locked/oos_prints, ends from src.tape.universe(), one
    joint walk-forward run; book = U1 matches starting >= 2026-08-25 14:15 UTC.
(b) U2, blind (primary): P = is_prints + oos_prints + expand_prints (no dedup), ends from U1 and U2,
    one joint walk-forward run; books = U2 matches only, split by match start at the same cutoff.
(c) the forward window is not run here.

v2-safe = dataclasses.replace(src.v2.POLICY, name="v2_safe_n50", net_cap=50). Nothing else changes.
The frozen v2 is run on the same features for the paired comparison.

src.v2.run() is build_features -> prepare -> 4 h lock -> engine.simulate(f, POLICY, ...). Only the
last step depends on the policy, so the features are built once per run and both policies are
simulated on them. The build uses the int-coded path of scripts/lowloss_select.py (same sort orders).
Before any statistic is computed, the v2 trades of each run must equal the frozen v2 trades
written earlier by the canonical v2.run() calls (data/v2_trades_is_oos.parquet from
scripts/v2_causal.py; data/expand_v2_trades.parquet from scripts/expand_test.py); otherwise the run
stops.

Outputs: results/lowloss/{results.json, daily.csv, daily_pnl.png, run.log},
         data/v2_lowloss/{features,whist}_{u1,u1u2}.parquet (caches), trades_{a,b}.parquet,
         a line in research/v2/lowloss/RUN_LOG, first-run lines in results/oos_peeks.log.
"""
from __future__ import annotations

import datetime as dt
import gc
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import fasttier, v2  # noqa: E402
from src.tape import universe  # noqa: E402
from src.tiers import add_causal_bucket  # noqa: E402

E = v2.E
V2 = v2.POLICY
V2_SAFE = replace(v2.POLICY, name="v2_safe_n50", net_cap=50)
POLS = {"v2": V2, "v2_safe": V2_SAFE}
CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")
IS_CAL = (pd.Timestamp("2026-02-01", tz="UTC"), pd.Timestamp("2026-08-25", tz="UTC"))
OOS_CAL_START = pd.Timestamp("2026-08-25", tz="UTC")
COLS = ["cond", "ts", "p", "dir", "usd", "wallet", "spread", "fee_rate", "delay", "res",
        "mo5", "mo15", "mo30", "mo_res"]
SLIPS = (0.0, 0.005, 0.01)
OUT = ROOT / "results/lowloss"
CACHE = ROOT / "data/v2_lowloss"
PREREG = ROOT / "research/v2/lowloss/PREREG.md"
STITCHED_IS_ACTIVE = ROOT / "research/v2/lowloss/out/results.json"
Z = 1.959963984540054
LOGFILE: Path | None = None


def log(*a):
    msg = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(msg, flush=True)
    if LOGFILE is not None:
        with open(LOGFILE, "a") as fh:
            fh.write(msg + "\n")


def sha16(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()[:16]


# ------------------------------------------------------------------------------------- build
def build(tag: str, files: list[str], ends: pd.Series, rebuild: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """v2.run(causal=True)'s feature table and wallet history for prints `files` (int-coded build)."""
    fp, wp = CACHE / f"features_{tag}.parquet", CACHE / f"whist_{tag}.parquet"
    meta_p = CACHE / f"features_{tag}.json"
    meta = {"files": {f: sha16(ROOT / f) for f in files}, "n_ends": int(len(ends))}
    if not rebuild and fp.exists() and wp.exists() and meta_p.exists() and json.loads(meta_p.read_text()) == meta:
        log(f"[{tag}] cached features")
        return pd.read_parquet(fp), pd.read_parquet(wp)
    CACHE.mkdir(parents=True, exist_ok=True)
    p = pd.concat([pd.read_parquet(ROOT / f, columns=COLS) for f in files], ignore_index=True)  # no dedup
    cc, cond_u = pd.factorize(p.cond, sort=True)
    wc, wal_u = pd.factorize(p.wallet, sort=True)
    p["cond"] = cc.astype(np.int32)
    p["wallet"] = wc.astype(np.int32)
    del cc, wc
    log(f"[{tag}] {len(p):,} prints, {len(cond_u):,} matches; causal bucket")
    lab = add_causal_bucket(p[["cond", "ts", "p", "usd", "dir"]])
    p["bucket_c"] = lab.bucket_c
    del lab
    gc.collect()
    m_all = set(pd.to_datetime(p.ts, unit="s").dt.to_period("M").unique())
    p03 = p[p.bucket_c == "0-3s"].copy()
    assert set(pd.to_datetime(p03.ts, unit="s").dt.to_period("M").unique()) == m_all, "month grid differs"
    log(f"[{tag}] walk-forward on {len(p03):,} causal 0-3 s prints")
    wf, sh, _ = fasttier.walk_forward(p03, bucket="bucket_c")
    ends_c = pd.Series(ends.reindex(pd.Index(cond_u)).to_numpy(), index=np.arange(len(cond_u), dtype=np.int32))
    log(f"[{tag}] features for {len(sh):,} shadow rows")
    keep = p.cond.isin(set(sh.cond))
    f = v2.prepare(v2.build_features(sh, p.loc[keep, ["cond", "ts", "p", "dir", "usd", "wallet"]], ends_c))
    del p, keep, sh
    gc.collect()
    f["lock_end"] = f.ts + v2.LOCK_S
    whist = p03[["wallet", "ts", "mo30"]].copy()
    del p03
    whist["month"] = pd.to_datetime(whist.ts, unit="s").dt.to_period("M").astype(str)
    whist = whist[["wallet", "month", "mo30"]]
    cond_u, wal_u = np.asarray(cond_u, dtype=object), np.asarray(wal_u, dtype=object)
    f["cond"] = cond_u[f.cond.to_numpy()]
    f["wallet"] = wal_u[f.wallet.to_numpy()]
    whist["wallet"] = wal_u[whist.wallet.to_numpy()]
    for c in f.columns:
        if isinstance(f[c].dtype, (pd.CategoricalDtype, pd.PeriodDtype)):
            f[c] = f[c].astype(str)
    f.to_parquet(fp)
    whist.to_parquet(wp)
    meta_p.write_text(json.dumps(meta))
    wf.to_csv(OUT / f"fasttier_wf_{tag}.csv", index=False)
    del f, whist
    gc.collect()
    return pd.read_parquet(fp), pd.read_parquet(wp)


def simulate(f: pd.DataFrame, whist: pd.DataFrame, pol) -> pd.DataFrame:
    E._WCACHE.clear()        # the wallet-effect cache is keyed by month only
    return E.simulate(f, pol, "res", "actual", whist)


def check_reference(tr: pd.DataFrame, ref_path: Path, tag: str) -> dict:
    """The v2 trades must equal the canonical v2.run() output written earlier."""
    ref = pd.read_parquet(ref_path, columns=["cond", "ts", "shares", "pnl"])
    key = lambda d: d.sort_values(["cond", "ts", "shares"], kind="stable")[["shares", "pnl"]].to_numpy()  # noqa: E731
    same = len(ref) == len(tr) and np.allclose(key(ref), key(tr), rtol=1e-9, atol=1e-9)
    chk = {"reference": str(ref_path.relative_to(ROOT)), "n_trades": [int(len(tr)), int(len(ref))],
           "pnl_usd": [float(tr.pnl.sum()), float(ref.pnl.sum())], "identical": bool(same)}
    log(f"[{tag}] v2 reference check", chk)
    assert same, f"v2 trades differ from {ref_path}: stop and find the cause (PREREG Rules)"
    return chk


# ----------------------------------------------------------------------------------- metrics
def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    ph = k / n
    den = 1 + Z * Z / n
    c = (ph + Z * Z / (2 * n)) / den
    h = Z * np.sqrt(ph * (1 - ph) / n + Z * Z / (4 * n * n)) / den
    return float(c - h), float(c + h)


def daily_on(tr: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    d = tr.groupby("date").pnl.sum()
    d.index = pd.DatetimeIndex(d.index).as_unit("ns")
    out = d.reindex(days, fill_value=0.0)
    assert abs(out.sum() - tr.pnl.sum()) < 1e-6 * max(1.0, abs(tr.pnl.sum())), "trade dates outside calendar"
    return out


def calendar(books: dict[str, pd.DataFrame], period: str) -> tuple[pd.DatetimeIndex, bool]:
    """Pre-registered calendar; extended (and flagged) only if a trade falls outside it."""
    last = max((pd.Timestamp(b.date.max()) for b in books.values() if len(b)), default=None)
    first = min((pd.Timestamp(b.date.min()) for b in books.values() if len(b)), default=None)
    if period == "is":
        start, end = IS_CAL
        ext = last is not None and last > end
        end = max(end, last) if last is not None else end
        ext = ext or (first is not None and first < start)
    else:
        start, end = OOS_CAL_START, (last if last is not None else OOS_CAL_START)
        ext = first is not None and first < start
    start = min(start, first) if first is not None else start
    return pd.date_range(start, end, freq="D").as_unit("ns"), bool(ext)


def book_metrics(tr: pd.DataFrame, days: pd.DatetimeIndex) -> dict:
    tr = tr[tr.month >= E.EVAL_START]
    if tr.empty:
        return {"n_trades": 0, "calendar_days": int(len(days))}
    d = daily_on(tr, days)
    eq = d.cumsum().to_numpy()
    peak = np.maximum.accumulate(np.maximum(eq, 0.0))
    dd = float((eq - peak).min())
    down = np.minimum(d.to_numpy(), 0.0)
    sd = d.std()
    act = tr.groupby("date").pnl.sum()
    k_act, n_act = int((act > 0).sum()), int(len(act))
    months = sorted(set(days.tz_localize(None).to_period("M").astype(str)))
    mon = tr.groupby("month").pnl.sum().reindex(months, fill_value=0.0)
    mt = tr.groupby("cond").pnl.sum()
    em = {}
    for s in SLIPS:
        q = tr.assign(pnl_ps=tr.pnl_ps - s)
        q = q.assign(pnl=q.shares * q.pnl_ps)
        em[s] = E.metrics(q)
    m0 = em[0.0]
    cap = m0["capital_usd"]
    return {
        "calendar": [str(days[0].date()), str(days[-1].date())], "calendar_days": int(len(days)),
        "profitable_days_pct": float((d > 0).mean() * 100), "losing_days_pct": float((d < 0).mean() * 100),
        "active_days": n_act, "profitable_active_days": k_act,
        "profitable_active_days_pct": float(k_act / n_act * 100),
        "profitable_active_days_wilson95_pct": [x * 100 for x in wilson(k_act, n_act)],
        "losing_active_days_pct": float((act < 0).mean() * 100),
        "worst_day_usd": float(d.min()), "worst_day_date": str(d.idxmin().date()),
        "worst_month_usd": float(mon.min()), "worst_month": str(mon.idxmin()),
        "monthly_usd": {k: float(v) for k, v in mon.items()},
        "months_positive": int((mon > 0).sum()), "months_total": int(len(mon)),
        "max_dd_usd": dd, "max_dd_pct_cap": float(dd / cap * 100) if cap else float("nan"),
        "sharpe_ann": float(d.mean() / sd * np.sqrt(365)) if sd > 0 else float("nan"),
        "sortino_ann": float(d.mean() / np.sqrt((down ** 2).mean()) * np.sqrt(365)) if (down < 0).any() else float("inf"),
        "pnl_usd": float(tr.pnl.sum()), "pnl_ci_usd": m0["total_pnl_ci_usd"], "mean_daily_usd": float(d.mean()),
        "per_share_c": m0["per_share_c"], "per_share_ci_c": m0["per_share_ci_c"],
        "per_share_slip_half_tick_c": em[0.005]["per_share_c"], "per_share_slip_half_tick_ci_c": em[0.005]["per_share_ci_c"],
        "per_share_slip_one_tick_c": em[0.01]["per_share_c"], "per_share_slip_one_tick_ci_c": em[0.01]["per_share_ci_c"],
        "profitable_matches_pct": float((mt > 0).mean() * 100), "losing_matches_pct": float((mt < 0).mean() * 100),
        "worst_match_usd": float(mt.min()), "n_matches": int(len(mt)), "n_trades": int(len(tr)),
        "shares": float(tr.shares.sum()), "usd_traded": float(tr.usd_in.sum()),
        "peak_locked_usd": m0["peak_locked_usd"], "capital_usd": cap,
        "engine_metrics": m0,   # engine.metrics as-is (its daily series runs first..last trade date)
    }


def primary(m: dict) -> dict:
    """P1 (per-share CI lower bound > 0) and P2 (Wilson lower bound of profitable active-day share > 50%)."""
    if m.get("n_trades", 0) == 0:
        return {"P1": False, "P2": False, "pass": False, "underpowered": True, "label": "FAILURE (no trades)"}
    p1 = m["per_share_ci_c"][0] > 0
    p2 = m["profitable_active_days_wilson95_pct"][0] > 50
    under = m["n_matches"] < 30 or m["active_days"] < 20
    ok = p1 and p2
    return {"P1_per_share_ci_lo_c": m["per_share_ci_c"][0], "P1": bool(p1),
            "P2_wilson_lo_pct": m["profitable_active_days_wilson95_pct"][0], "P2": bool(p2),
            "n_matches": m["n_matches"], "active_days": m["active_days"], "pass": bool(ok),
            "underpowered": bool(under), "label": ("PASS" if ok else "FAILURE") + (" (underpowered)" if under else "")}


def paired(a: pd.DataFrame, b: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    """v2-safe (a) minus v2 (b) on the same days: the union of both books' active days."""
    a, b = a[a.month >= E.EVAL_START], b[b.month >= E.EVAL_START]
    da, db = a.groupby("date").pnl.sum(), b.groupby("date").pnl.sum()
    idx = da.index.union(db.index)
    if len(idx) == 0:
        return {"n_days": 0}
    xa = (da.reindex(idx, fill_value=0.0) > 0).to_numpy(float)
    xb = (db.reindex(idx, fill_value=0.0) > 0).to_numpy(float)
    diff = xa - xb
    rng = np.random.default_rng(seed)
    bs = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(n_boot)]
    return {"n_days": int(len(idx)), "days_only_one_active": int(len(idx.symmetric_difference(da.index.intersection(db.index)))),
            "profitable_share_v2_safe_pct": float(xa.mean() * 100), "profitable_share_v2_pct": float(xb.mean() * 100),
            "diff_pp": float(diff.mean() * 100),
            "diff_ci_pp": [float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)],
            "days_safe_up_v2_down": int(((xa == 1) & (xb == 0)).sum()),
            "days_v2_up_safe_down": int(((xa == 0) & (xb == 1)).sum())}


def evaluate(trades: dict[str, pd.DataFrame], start_of: pd.Series, book_conds: dict[str, set | None]) -> tuple[dict, dict]:
    """Per book (U2 / combined / ...) x period: metrics for both policies on one shared calendar."""
    res, daily = {}, {}
    for t in trades.values():
        t["oos"] = t.cond.map(start_of) >= CUT
        assert t.cond.map(start_of).notna().all(), "trade in a match with no start time"
    for bname, conds in book_conds.items():
        for period in ("is", "oos"):
            key = f"{bname}_{period}"
            parts = {}
            for s, t in trades.items():
                sel = (t.oos if period == "oos" else ~t.oos) & (t.month >= E.EVAL_START)
                if conds is not None:
                    sel &= t.cond.isin(conds)
                parts[s] = t[sel]
            days, ext = calendar(parts, period)
            res[key] = {"calendar_extended": ext}
            for s, part in parts.items():
                res[key][s] = book_metrics(part, days)
                daily[(key, s)] = daily_on(part, days) if len(part) else pd.Series(0.0, index=days)
            res[key]["primary_v2_safe"] = primary(res[key]["v2_safe"])
            res[key]["primary_v2_context"] = primary(res[key]["v2"])
            res[key]["paired_v2_safe_minus_v2"] = paired(parts["v2_safe"], parts["v2"])
            a, b = res[key]["v2_safe"], res[key]["v2"]
            if a.get("n_trades", 0) and b.get("n_trades", 0):
                res[key]["paired_v2_safe_minus_v2"].update({
                    "worst_day_usd": [a["worst_day_usd"], b["worst_day_usd"]],
                    "max_dd_usd": [a["max_dd_usd"], b["max_dd_usd"]],
                    "pnl_ratio": a["pnl_usd"] / b["pnl_usd"] if b["pnl_usd"] else float("nan")})
            log(key, "ext" if ext else "", {s: {k: (round(res[key][s][k], 2) if isinstance(res[key][s].get(k), float) else res[key][s].get(k))
                                                for k in ("n_trades", "n_matches", "profitable_days_pct", "profitable_active_days_pct",
                                                          "worst_day_usd", "max_dd_usd", "pnl_usd", "per_share_c")}
                                            for s in parts})
    return res, daily


def peek(line_key: str, text: str):
    peeks = ROOT / "results/oos_peeks.log"
    if line_key not in peeks.read_text():      # re-running the same frozen evaluation is not a new peek
        with open(peeks, "a") as fh:
            fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} {text}\n")


# ------------------------------------------------------------------------------------ figure
def figure(daily: dict, res: dict, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    surf, plane, ink, ink2, muted, grid, base = "#fcfcfb", "#f0efec", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
    c_v2, c_safe = "#c3c2b7", "#2a78d6"
    panels = [("a", "U1, burned OOS non-blind", "u1"), ("b", "U2, unseen matches (blind)", "u2")]
    panels = [p for p in panels if (f"{p[2]}_is", "v2") in daily.get(p[0], {})]
    fig, axes = plt.subplots(len(panels), 1, figsize=(11, 3.6 * len(panels) + 0.6), dpi=150, squeeze=False)
    fig.patch.set_facecolor(surf)
    for ax, (run, title, bk) in zip(axes[:, 0], panels):
        D = daily[run]
        ser = {s: pd.concat([D[(f"{bk}_is", s)], D[(f"{bk}_oos", s)]]).groupby(level=0).sum() for s in ("v2", "v2_safe")}
        x = ser["v2"].index.tz_localize(None)
        ax.set_facecolor(surf)
        cut = CUT.tz_localize(None)
        ax.axvspan(cut, x.max() + pd.Timedelta(days=1), color=plane, lw=0, zorder=0)
        ax.axvline(cut, color=muted, lw=0.8, zorder=1)
        ax.axhline(0, color=base, lw=0.8, zorder=1)
        ax.bar(x, ser["v2"].reindex(ser["v2"].index).to_numpy(), width=0.9, color=c_v2, lw=0, zorder=2)
        ax.bar(x, ser["v2_safe"].reindex(ser["v2"].index, fill_value=0).to_numpy(), width=0.45, color=c_safe, lw=0, zorder=3)
        R = res[run]

        def usd(v):
            return ("\u2212" if v < 0 else "") + f"\\${abs(v):,.0f}"

        def lab(k, head):
            a, b = R[f"{bk}_{k}"]["v2_safe"], R[f"{bk}_{k}"]["v2"]
            if not a.get("n_trades"):
                return head + "\nno trades"
            row = lambda m: (f"{m['profitable_active_days_pct']:.0f}% of active days up, worst day {usd(m['worst_day_usd'])}, "  # noqa: E731
                             f"total {usd(m['pnl_usd'])}")
            return f"{head}\nv2-safe  {row(a)}\nv2        {row(b)}"
        lo_y, hi_y = ax.get_ylim()
        ax.set_ylim(lo_y, hi_y + 0.5 * (hi_y - lo_y))
        top = ax.get_ylim()[1]
        ax.text(x.min(), top, lab("is", "IS: matches starting before 25 Aug 14:15 UTC"), va="top", ha="left",
                fontsize=7.6, color=ink2, linespacing=1.4)
        ax.text(cut - pd.Timedelta(days=2), top, lab("oos", "OOS (shaded): matches starting from 25 Aug 14:15 UTC"),
                va="top", ha="right", fontsize=7.6, color=ink2, linespacing=1.4)
        ax.set_title(title, loc="left", fontsize=10.5, color=ink, pad=6)
        ax.set_ylabel("daily net P&L, \\$", color=ink2, fontsize=8.5)
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.grid(axis="y", color=grid, lw=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(base)
        ax.tick_params(colors=ink2, labelsize=8)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: ("\u2212" if v < 0 else "") + f"${abs(v):,.0f}"))
        ax.set_xlim(x.min() - pd.Timedelta(days=1), x.max() + pd.Timedelta(days=1))
    fig.legend(handles=[Patch(color=c_v2, label="v2 (net cap 100 shares/match)"),
                        Patch(color=c_safe, label="v2-safe (net cap 50 shares/match)")],
               loc="upper right", ncol=2, frameon=False, fontsize=8.5, labelcolor=ink2, bbox_to_anchor=(0.99, 1.0))
    fig.suptitle("Daily P&L held to resolution, v2 vs v2-safe", x=0.01, ha="left", fontsize=12, color=ink)
    fig.text(0.01, 0.005, "Bars: net P&L of trades entered that UTC day, months >= 2026-02. Wide grey = v2, narrow blue = "
             "v2-safe. Shaded: matches starting at or after 2026-08-25 14:15 UTC. Active day = at least one trade.",
             fontsize=7, color=muted)
    fig.tight_layout(rect=(0, 0.02, 1, 0.965))
    fig.savefig(path, facecolor=surf)
    plt.close(fig)


# -------------------------------------------------------------------------------------- main
def figure_from_saved():
    """Redraw the figure from results/lowloss/{daily.csv, results.json} (no data is re-read)."""
    out = json.loads((OUT / "results.json").read_text())
    names = {"a": "a_burned_oos_nonblind", "b": "b_u2_blind"}
    res = {k: out["runs"][v]["books"] for k, v in names.items() if "books" in out["runs"].get(v, {})}
    dl = pd.read_csv(OUT / "daily.csv", parse_dates=["date"])
    daily = {}
    for (run, book, pol), g in dl.groupby(["run", "book", "policy"]):
        idx = pd.DatetimeIndex(g.date).tz_localize("UTC").as_unit("ns")
        daily.setdefault(run, {})[(book, pol)] = pd.Series(g.pnl_usd.to_numpy(), index=idx)
    figure(daily, res, OUT / "daily_pnl.png")


def main():
    global LOGFILE
    if "--figure-only" in sys.argv:
        return figure_from_saved()
    rebuild = "--rebuild" in sys.argv
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    LOGFILE = OUT / "run.log"
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    log(f"v2-safe pre-registered tests, started {started}, HEAD {head}, PREREG sha256 {sha16(PREREG)}")
    prereg_commit = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%H %cI", "--", "research/v2/lowloss/PREREG.md"],
                                   capture_output=True, text=True).stdout.strip()
    assert prereg_commit, "PREREG.md must be committed before any test is run"
    assert not subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "research/v2/lowloss/PREREG.md"],
                              capture_output=True, text=True).stdout.strip(), "PREREG.md has uncommitted edits"
    log("PREREG commit", prereg_commit)
    assert V2_SAFE.net_cap == 50 and all(getattr(V2_SAFE, k) == getattr(V2, k) for k in
                                         ("sizing", "deploy_frac", "zone", "wallet", "usd_cap", "match_cap", "day_cap",
                                          "wallet_day_cap", "stop_k", "filt"))
    out = {"prereg": f"research/v2/lowloss/PREREG.md @ {prereg_commit}", "git_head": head, "run_started_utc": started,
           "policies": {s: {k: (v if not isinstance(v, float) or np.isfinite(v) else "inf") for k, v in vars(p).items()}
                        for s, p in POLS.items()},
           "cutoff_utc": str(CUT), "runs": {}}
    stitched = json.loads(STITCHED_IS_ACTIVE.read_text())["stitched_is"]
    out["stitched_is_reference"] = {k: stitched[k] for k in ("profitable_days_pct", "profitable_active_days_pct",
                                                             "worst_day_usd", "pnl_usd", "per_share_c")}
    all_daily, results = {}, {}

    # ---------------------------------------------------------------- (a) burned OOS, non-blind
    u1 = universe()
    assert (u1.oos == (u1.start >= CUT)).all(), "U1 oos flag must equal start >= cutoff"
    ends1 = u1.set_index("cond").end
    f, whist = build("u1", ["data/is_prints.parquet", "data/locked/oos_prints.parquet"], ends1, rebuild)
    log(f"[a] features {len(f):,} rows, months {f.month.min()}..{f.month.max()}, {time.time() - t0:.0f}s")
    tr = {s: simulate(f, whist, p) for s, p in POLS.items()}
    del f, whist
    gc.collect()
    chk_a = check_reference(tr["v2"], ROOT / "data/v2_trades_is_oos.parquet", "a")
    for s, t in tr.items():
        t[["cond", "ts", "date", "month", "dir", "q", "shares", "usd_in", "pnl_ps", "pnl", "lock_end"]].assign(policy=s) \
            .to_parquet(CACHE / f"trades_a_{s}.parquet")
    ra, da = evaluate(tr, u1.set_index("cond").start, {"u1": None})
    peek("v2-safe (lowloss PREREG) evaluated on burned OOS", "v2-safe (lowloss PREREG) evaluated on burned OOS (non-blind, labelled)")
    out["runs"]["a_burned_oos_nonblind"] = {"label": "NON-BLIND", "reference_check": chk_a, "books": ra,
                                            "note": "u1_is is context (IS, in-sample for the selection); u1_oos is the burned-OOS test"}
    results["a"], all_daily["a"] = ra, da
    del tr
    gc.collect()

    # ------------------------------------------------------------------------- (b) U2, blind
    u2p = ROOT / "data/expand_prints.parquet"
    if not u2p.exists():
        log("U2 data not there yet: stopping after (a)")
        out["runs"]["b_u2_blind"] = {"status": "not run: data/expand_prints.parquet does not exist"}
    else:
        u2 = pd.read_parquet(ROOT / "data/expand_universe.parquet", columns=["cond", "start", "end", "oos", "series"])
        assert u2.cond.is_unique and not set(u2.cond) & set(u1.cond)
        assert (u2.oos == (u2.start >= CUT)).all()
        ends = pd.concat([ends1, u2.set_index("cond").end])
        start_of = pd.concat([u1.set_index("cond").start, u2.set_index("cond").start])
        assert ends.index.is_unique and start_of.index.is_unique
        files = ["data/is_prints.parquet", "data/locked/oos_prints.parquet", "data/expand_prints.parquet"]
        f, whist = build("u1u2", files, ends, rebuild)
        log(f"[b] features {len(f):,} rows, months {f.month.min()}..{f.month.max()}, {time.time() - t0:.0f}s")
        tr = {s: simulate(f, whist, p) for s, p in POLS.items()}
        del f, whist
        gc.collect()
        ref_b = ROOT / "data/expand_v2_trades.parquet"
        chk_b = check_reference(tr["v2"], ref_b, "b") if ref_b.exists() else {"reference": "missing"}
        for s, t in tr.items():
            t[["cond", "ts", "date", "month", "dir", "q", "shares", "usd_in", "pnl_ps", "pnl", "lock_end"]].assign(policy=s) \
                .to_parquet(CACHE / f"trades_b_{s}.parquet")
        u2c, u1c = set(u2.cond), set(u1.cond)
        rb, db = evaluate(tr, start_of, {"u2": u2c, "combined": None, "u1_context": u1c})
        peek("v2-safe U2 out-of-universe test evaluated", "v2-safe U2 out-of-universe test evaluated (PREREG research/v2/lowloss, first run)")
        prim = {k: rb[f"u2_{k}"]["primary_v2_safe"] for k in ("is", "oos")}
        verdict = "PASS" if prim["is"]["pass"] and prim["oos"]["pass"] else "FAIL"
        reach = {k: bool(rb[f"u2_{k}"]["v2_safe"].get("profitable_active_days_pct", float("nan"))
                         >= stitched["profitable_active_days_pct"]) for k in ("is", "oos")}
        t2 = tr["v2_safe"][(tr["v2_safe"].month >= E.EVAL_START) & tr["v2_safe"].cond.isin(u2c)]
        meta2 = u2.set_index("cond")
        by_series = {f"{per}/{s}": int(n) for (per, s), n in
                     t2.assign(series=t2.cond.map(meta2.series), per=np.where(t2.oos, "oos", "is"))
                     .groupby(["per", "series"]).cond.nunique().items()}
        out["runs"]["b_u2_blind"] = {"label": "BLIND (primary)", "reference_check": chk_b, "books": rb,
                                     "primary": {"u2_is": prim["is"], "u2_oos": prim["oos"], "verdict": verdict},
                                     "reaches_stitched_is_active_share": reach,
                                     "u2_markets": int(len(u2)),
                                     "u2_matches_traded_by_v2_safe_by_period_series": by_series}
        results["b"], all_daily["b"] = rb, db
        log("PRIMARY", json.dumps(out["runs"]["b_u2_blind"]["primary"], default=float))
        with open(ROOT / "research/v2/lowloss/RUN_LOG", "a") as fh:
            fh.write(f"{started} lowloss_test run, HEAD {head}, U2 verdict {verdict}\n")

    rows = []
    for run, D in all_daily.items():
        for (book, s), ser in D.items():
            rows.append(pd.DataFrame({"run": run, "book": book, "policy": s, "date": ser.index.date, "pnl_usd": ser.to_numpy()}))
    pd.concat(rows).to_csv(OUT / "daily.csv", index=False)
    out["runtime_s"] = round(time.time() - t0, 1)
    (OUT / "results.json").write_text(json.dumps(out, indent=2, default=float))
    figure(all_daily, results, OUT / "daily_pnl.png")
    log(f"done in {time.time() - t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()
