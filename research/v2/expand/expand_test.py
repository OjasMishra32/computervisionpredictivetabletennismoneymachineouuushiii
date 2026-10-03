"""U2 out-of-universe test of frozen v2, exactly as pre-registered in research/v2/expand/PREREG.md.

    python scripts/expand_test.py          # (or this file) from the repo root; one command, everything

Inputs: data/is_prints.parquet + data/locked/oos_prints.parquet (U1), data/expand_prints.parquet (U2);
ends from src.tape.universe() (U1) and data/expand_universe.parquet (U2).
Outputs: results/expand/results.json, results/expand/u2_equity.png, data/expand_v2_trades.parquet,
results/expand/run.log (stdout of every run), a line in research/v2/expand/RUN_LOG.

v2 is run frozen: src.v2.run(prints, ends, causal=True). Nothing here changes a parameter.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import fasttier, v2  # noqa: E402
from src.tape import universe  # noqa: E402
from src.tiers import add_causal_bucket  # noqa: E402
from scripts.forward_test import cluster_ci  # noqa: E402  (the pre-registered markout CI)

E = v2.E
OOS_CUT = pd.Timestamp("2026-08-25 14:15", tz="UTC")
# Only the print columns the frozen pipeline reads (since, with_jump, mo60, mo120 and the onset `bucket`
# are never used on the causal path; verified to reproduce results/v2/causal.json exactly on U1).
COLS = ["cond", "ts", "p", "dir", "usd", "wallet", "spread", "fee_rate", "delay", "res",
        "mo5", "mo15", "mo30", "mo_res"]
OUT = ROOT / "results/expand"
SLIPS = (0.0, 0.005, 0.01)
METRIC_KEYS = ("n_trades", "n_matches", "per_share_c", "per_share_ci_c", "per_print_c", "per_usd_c",
               "total_pnl_usd", "total_pnl_ci_usd", "usd_traded", "sharpe_ann", "peak_locked_usd",
               "capital_usd", "return_on_capital_pct", "max_dd_usd", "max_dd_pct", "worst_day_usd",
               "worst_day_pct", "months_positive", "months_total", "worst_month_usd", "days")


LOGFILE = None


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg, flush=True)
    if LOGFILE is not None:
        with open(LOGFILE, "a") as fh:
            fh.write(msg + "\n")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()[:16]


# ------------------------------------------------------------------------------- inputs
def load_universes():
    u1 = universe()
    u2 = pd.read_parquet(ROOT / "data/expand_universe.parquet")
    # pre-registered expectations (catalogue metadata) and the period definition
    exp = {"n": 11307, "series": {"itf": 10855, "atp": 292, "wta": 160}, "is": 7743, "oos": 3564}
    got = {"n": len(u2), "series": u2.series.value_counts().to_dict(), "is": int((~u2.oos).sum()),
           "oos": int(u2.oos.sum())}
    assert got == exp, (got, exp)
    assert u2.cond.is_unique and u2.event_id.nunique() == len(u2)
    assert not set(u2.cond) & set(u1.cond) and not set(u2.event_id) & set(u1.event_id)
    assert (u2.oos == (u2.start >= OOS_CUT)).all()
    assert (u1.oos == (u1.start >= OOS_CUT)).all(), "U1 oos flag must equal start >= 2026-08-25 14:15 UTC"
    return u1, u2


def load_prints(u1, u2):
    parts = [pd.read_parquet(ROOT / f, columns=COLS) for f in
             ("data/is_prints.parquet", "data/locked/oos_prints.parquet", "data/expand_prints.parquet")]
    c1 = set(parts[0].cond) | set(parts[1].cond)
    c2 = set(parts[2].cond)
    assert not c1 & c2 and c2 <= set(u2.cond) and c1 <= set(u1.cond)
    m1 = pd.to_datetime(pd.concat([parts[0].ts, parts[1].ts]), unit="s").dt.to_period("M")
    m2 = pd.to_datetime(parts[2].ts, unit="s").dt.to_period("M")
    assert m2.min() >= m1.min(), "U2 must not add an earlier month (walk-forward grid unchanged)"
    info = {"rows": {"u1_is": len(parts[0]), "u1_oos": len(parts[1]), "u2": len(parts[2])},
            "matches_with_prints": {"u1": len(c1), "u2": len(c2),
                                    "u2_is": int(u2[u2.cond.isin(c2)].pipe(lambda d: (~d.oos).sum())),
                                    "u2_oos": int(u2[u2.cond.isin(c2)].oos.sum())},
            "first_month": str(m1.min())}
    P = pd.concat(parts, ignore_index=True)        # no dedup (identical rows are distinct fills)
    return P, info


# ----------------------------------------------------------------------------- statistics
def book_metrics(tr: pd.DataFrame) -> dict:
    out = {}
    for slip in SLIPS:
        q = tr.assign(pnl_ps=tr.pnl_ps - slip)
        q = q.assign(pnl=q.shares * q.pnl_ps)
        m = E.metrics(q)
        out[f"slip{slip}"] = {k: m[k] for k in METRIC_KEYS if k in m}
    return out


def markout30(tr: pd.DataFrame) -> dict:
    """U2 v2 book 30 s net markout, share-weighted, match-clustered (forward_test.cluster_ci)."""
    ft = tr[tr.month >= E.EVAL_START].dropna(subset=["gross30"]).copy()
    if ft.empty:
        return {"n_trades": 0}
    ft["m30_ps"] = ft.gross30 - (ft.gross_res - ft.pnl_ps)
    assert np.isfinite(ft.m30_ps).all()
    mean, lo, hi = cluster_ci(ft, "m30_ps")
    return {"m30_per_share_c": 100 * mean, "ci_c": [100 * lo, 100 * hi], "n_trades": int(len(ft)),
            "n_matches": int(ft.cond.nunique())}


def fast_minus_others(P: pd.DataFrame, u2: pd.DataFrame) -> dict:
    """Primary-A-style statistic on U2 prints, causal 0-3 s bucket, months >= 2026-02, by period.
    Fast = fasttier.qualify(U1 u U2 prints of months < m, "bucket_c") for the print's month m."""
    p03 = P[P.bucket_c == "0-3s"][["cond", "ts", "p", "wallet", "fee_rate", "mo30"]].copy()
    p03["month"] = pd.to_datetime(p03.ts, unit="s").dt.to_period("M")
    p03["bucket_c"] = "0-3s"
    u2c = set(u2.cond)
    tgt = p03[p03.cond.isin(u2c) & (p03.month >= pd.Period(E.EVAL_START, "M"))].copy()
    tgt["fast"] = False
    n_wallets = {}
    for m in sorted(tgt.month.unique()):
        sel = fasttier.qualify(p03[p03.month < m], "bucket_c")   # == qualify(all prints < m): it keeps 0-3 s only
        n_wallets[str(m)] = int(len(sel))
        ix = tgt.month == m
        tgt.loc[ix, "fast"] = tgt.loc[ix, "wallet"].isin(sel).to_numpy()
    tgt["net30"] = tgt.mo30 - tgt.fee_rate * tgt.p * (1 - tgt.p)
    oos = tgt.cond.map(u2.set_index("cond").oos)
    out = {"qualified_wallets_by_month": n_wallets}
    for name, part in (("u2_is", tgt[~oos]), ("u2_oos", tgt[oos])):
        d = part.dropna(subset=["net30"])
        g = d.groupby(["cond", "fast"]).net30.agg(["sum", "size"]).unstack(fill_value=0)
        g = g.reindex(columns=pd.MultiIndex.from_product([["sum", "size"], [False, True]]), fill_value=0)
        rng = np.random.default_rng(0)
        k = len(g)

        def diff(ix):   # as in Primary A of scripts/forward_test.py
            gg = g.iloc[ix]
            f_ = gg[("sum", True)].sum() / max(gg[("size", True)].sum(), 1)
            o_ = gg[("sum", False)].sum() / max(gg[("size", False)].sum(), 1)
            return (f_ - o_) * 100
        bs = [diff(rng.integers(0, k, k)) for _ in range(2000)] if k else [np.nan]
        out[name] = {"fast_minus_others_c": float(diff(np.arange(k))) if k else float("nan"),
                     "ci_c": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
                     "fast_net30_c": float(d[d.fast].net30.mean() * 100),
                     "others_net30_c": float(d[~d.fast].net30.mean() * 100),
                     "n_prints_fast": int(d.fast.sum()), "n_prints_others": int((~d.fast).sum()),
                     "n_matches": int(k), "n_matches_with_fast": int(d[d.fast].cond.nunique())}
    return out


def exploratory(tr_u2: pd.DataFrame, u2: pd.DataFrame) -> dict:
    """NOT pre-registered, descriptive only: where U2's per-share P&L comes from."""
    t = tr_u2[tr_u2.month >= E.EVAL_START].copy()
    meta = u2.set_index("cond")
    t["series"] = t.cond.map(meta.series)
    t["vol_band"] = pd.cut(t.cond.map(meta.volume), [1e3, 2e3, 5e3, 1e4, 1e5, np.inf], right=False,
                           labels=["1-2k", "2-5k", "5-10k", "10-100k", ">100k"]).astype(str)
    t["period"] = np.where(t.cond.map(meta.oos), "oos", "is")
    out = {}
    for col in ("series", "regime", "vol_band"):
        g = t.groupby(["period", col])
        df = pd.DataFrame({"n_trades": g.size(), "n_matches": g.cond.nunique(), "pnl_usd": g.pnl.sum(),
                           "per_share_c": g.pnl.sum() / g.shares.sum() * 100})
        out[col] = {f"{a}/{b}": {k: float(v) for k, v in r.items()} for (a, b), r in df.iterrows()}
    return out


# ------------------------------------------------------------------------------- figure
def figure(tr_u2: pd.DataFrame, res: dict, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    t = tr_u2[tr_u2.month >= E.EVAL_START]
    daily = E.daily_series(t)
    eq = daily.cumsum()
    x = eq.index.tz_localize(None)
    surf, ink, ink2, grid, blue = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df", "#2a78d6"
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=150)
    fig.patch.set_facecolor(surf); ax.set_facecolor(surf)
    cut = OOS_CUT.tz_localize(None)
    ax.axvspan(cut, x.max() + pd.Timedelta(days=1), color="#efeee9", lw=0, zorder=0)
    ax.axvline(cut, ymax=0.78, color=ink2, lw=0.8, ls=(0, (3, 3)), zorder=1)
    ax.axhline(0, color=ink2, lw=0.8, zorder=1)
    ax.plot(x, eq.to_numpy(), color=blue, lw=2, zorder=3, solid_capstyle="round")
    B = res["books"]
    def lab(k):
        m = B[k]["slip0.0"]
        if m.get("n_trades", 0) == 0:
            return "no trades"
        lo, hi = m["per_share_ci_c"]
        return (f"{m['per_share_c']:+.2f}¢/share [{lo:+.2f}, {hi:+.2f}]\n"
                f"Sharpe {m['sharpe_ann']:.1f} · ${m['total_pnl_usd']:,.0f} · {m['n_matches']:,} matches")
    ymax = ax.get_ylim()[1]
    ax.text(x.min(), ymax, "IS (match start before 25 Aug 14:15 UTC)\n" + lab("u2_is"), va="top", ha="left",
            fontsize=8.5, color=ink2)
    ax.text(x.max() + pd.Timedelta(days=1), ymax, "OOS (shaded)\n" + lab("u2_oos"), va="top", ha="right",
            fontsize=8.5, color=ink2)
    ax.set_ylabel("cumulative net P&L, $ (held to resolution)", color=ink2, fontsize=9)
    verdict = res["primary"]["verdict"]
    ax.set_title(f"Frozen v2 on U2 (unseen ITF + low-volume ATP/WTA moneylines): primary {verdict}",
                 loc="left", fontsize=11, color=ink)
    ax.xaxis.set_major_locator(mdates.MonthLocator()); ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.grid(axis="y", color=grid, lw=0.6); ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(grid)
    ax.tick_params(colors=ink2, labelsize=8.5)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    lo_y, hi_y = ax.get_ylim()
    ax.set_ylim(lo_y, hi_y + 0.28 * (hi_y - lo_y))   # room for the period labels
    for txt in ax.texts:
        txt.set_y(ax.get_ylim()[1])
    fig.text(0.01, 0.01, "Daily P&L of v2 trades in U2 matches, months ≥ 2026-02; shaded = OOS period. "
             "Capital per book = 3× its own peak locked capital (4 h ex-ante lock).", fontsize=7, color=ink2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, facecolor=surf)
    plt.close(fig)


# --------------------------------------------------------------------------------- main
def main():
    global LOGFILE
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    LOGFILE = OUT / "run.log"
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    log(f"U2 out-of-universe test, started {started}, HEAD {head}")
    u1, u2 = load_universes()
    P, pinfo = load_prints(u1, u2)
    log("prints", pinfo, f"{time.time() - t0:.0f}s")
    ends = pd.concat([u1.set_index("cond").end, u2.set_index("cond").end])
    assert ends.index.is_unique
    P = add_causal_bucket(P)                      # v2.run would add the same column; done once, reused below
    log("causal buckets", f"{time.time() - t0:.0f}s")
    tr, wf = v2.run(P, ends, causal=True)
    log("v2.run", len(tr), "trades", f"{time.time() - t0:.0f}s")
    tr.to_parquet(ROOT / "data/expand_v2_trades.parquet")

    start = pd.concat([u1.set_index("cond").start, u2.set_index("cond").start])
    tr["is_u2"] = tr.cond.isin(set(u2.cond))
    tr["oos"] = tr.cond.map(start) >= OOS_CUT
    assert tr.cond.map(start).notna().all()
    books = {"u2_is": tr[tr.is_u2 & ~tr.oos], "u2_oos": tr[tr.is_u2 & tr.oos],
             "combined_is": tr[~tr.oos], "combined_oos": tr[tr.oos],
             "u1_is_context": tr[~tr.is_u2 & ~tr.oos], "u1_oos_context": tr[~tr.is_u2 & tr.oos]}
    res = {"prereg": "research/v2/expand/PREREG.md @ 337bf7c", "run_started_utc": started, "git_head": head,
           "inputs_sha256_16": {f: sha(ROOT / f) for f in ("data/is_prints.parquet", "data/locked/oos_prints.parquet",
                                                           "data/expand_prints.parquet", "data/expand_universe.parquet")},
           "universe": {"u2_markets": len(u2), "u2_series": u2.series.value_counts().to_dict(),
                        "u2_is_markets": int((~u2.oos).sum()), "u2_oos_markets": int(u2.oos.sum())},
           "prints": pinfo, "books": {}, "markout30": {}}
    for k, b in books.items():
        res["books"][k] = book_metrics(b)
        m = res["books"][k]["slip0.0"]
        log(k, {x: (round(m[x], 3) if isinstance(m[x], float) else m[x]) for x in
                ("n_trades", "n_matches", "per_share_c", "per_share_ci_c", "total_pnl_usd", "sharpe_ann",
                 "max_dd_pct", "months_positive", "months_total") if x in m})
    for k in ("u2_is", "u2_oos", "combined_is", "combined_oos"):
        res["markout30"][k] = markout30(books[k])
        log("m30", k, res["markout30"][k])
    res["fast_minus_others_u2"] = fast_minus_others(P, u2)
    log("fast-minus-others", {k: v for k, v in res["fast_minus_others_u2"].items() if k != "qualified_wallets_by_month"})

    prim = {}
    for k in ("u2_is", "u2_oos"):
        m = res["books"][k]["slip0.0"]
        n = m.get("n_matches", 0)
        ok = n > 0 and m["per_share_ci_c"][0] > 0
        prim[k] = {"per_share_c": m.get("per_share_c"), "per_share_ci_c": m.get("per_share_ci_c"),
                   "n_matches_with_trades": n, "pass": bool(ok), "underpowered": bool(n < 30),
                   "label": ("PASS" if ok else "FAILURE") + (" (underpowered)" if n < 30 else "")}
    prim["verdict"] = "PASS" if prim["u2_is"]["pass"] and prim["u2_oos"]["pass"] else "FAIL"
    res["primary"] = prim
    log("PRIMARY", json.dumps(prim))

    res["exploratory_not_preregistered"] = exploratory(tr[tr.is_u2], u2)
    res["walk_forward_months"] = wf.to_dict("records")
    res["runtime_s"] = round(time.time() - t0, 1)
    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    figure(tr[tr.is_u2], res, OUT / "u2_equity.png")
    with open(ROOT / "research/v2/expand/RUN_LOG", "a") as f:
        f.write(f"{started} expand_test run, HEAD {head}, verdict {prim['verdict']}\n")
    peeks = ROOT / "results/oos_peeks.log"
    if "U2 out-of-universe" not in peeks.read_text():   # re-running the same frozen evaluation is not a new peek
        with open(peeks, "a") as f:
            f.write(f"{started} U2 out-of-universe test evaluated (PREREG research/v2/expand, first run)\n")
    log(f"done in {time.time() - t0:.0f}s -> {OUT}/results.json, u2_equity.png")


if __name__ == "__main__":
    main()
