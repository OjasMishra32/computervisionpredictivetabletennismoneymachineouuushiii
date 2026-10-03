"""TT5: signal decay vs latency (HYPOTHESIS_TT.md, TT5; pre-run decisions in research/decay/PRERUN.md).

For every in-play taker print, `since_det` is the number of seconds since the latest jump DETECTION in that
match (src.tiers.add_causal_bucket, unchanged). Net markouts by since_det bin show how fast the edge from a
score event decays. Each latency stack is then read off the curve.

    python scripts/signal_decay.py            # -> results/decay/decay.json, results/decay/fig_signal_decay.png

Inputs (all real, all public):
  tennis        data/is_prints.parquet (U1 IS) + data/locked/oos_prints.parquet (burned OOS, non-blind)
  table tennis  data/tt/prints.parquet (UTT, primary), data/tt/prints_unlisted.parquet (sensitivity only),
                data/tt/universe.parquet (oos flag, league)
  latency       research/v2/blocklag/results.json (block-time lag), results/summary.json h4 (book vs public
                score), research/v2/latency/RESULTS.md (ESPN, the fastest public feed), results/engine/
                vision_bench.json (measured CV call latency), src/tier0.py (T_INF, T_INF_PESS, GATEWAY)
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import fasttier  # noqa: E402
from src.tiers import add_causal_bucket  # noqa: E402
from src.tier0 import GATEWAY, T_INF, T_INF_PESS  # noqa: E402

OUT = ROOT / "results/decay"
COLS = ["cond", "ts", "p", "dir", "usd", "wallet", "fee_rate", "delay", "res", "mo30", "mo_res"]
N_BOOT, SEED = 2000, 0

# Pre-registered bins (left-closed), then the baseline row.
EDGES = [0, 0.25, 0.5, 1, 2, 3, 5, 10, 30]
BINS = ["0-0.25", "0.25-0.5", "0.5-1", "1-2", "2-3", "3-5", "5-10", "10-30"]
BASE = "baseline"
EMPTY_BY_CONSTRUCTION = ["0.25-0.5", "0.5-1"]  # integer-second block stamps: since_det is a whole number
# Block-resolution bins (research/decay/PRERUN.md TT5-D3): stamps step in ~2 s Polygon blocks, so [1,2) and
# [2,3) are merged into [1,3), "the next block". [3,5) already spans one block.
BEDGES = [0, 0.25, 1, 3, 5, 10, 30]
BBINS = ["0-0.25", "0.25-1", "1-3", "3-5", "5-10", "10-30"]
SCHEMES = {"prereg": (EDGES, BINS, "bin"), "block": (BEDGES, BBINS, "bin_b")}

# ------------------------------------------------------------------------------------- latency inputs
CAMERA = 1 / 120                                  # one frame at 120 fps (OpenTTGames)
NET_FL = 0.067                                    # Florida one-way, measured median (HYPOTHESIS_TT.md)
NET_LDN = GATEWAY                                 # London co-located gateway, 2 ms (inferred; src/tier0.py)
REACT = 0.25                                      # human reaction after seeing the point (research/v2/tier0/PREREG.md)
STREAM = (5.0, 30.0)                              # public stream delay range: an ASSUMPTION, not measured
ESPN_BEHIND_BOOK = 28.2                           # research/v2/latency/RESULTS.md 3a (ESPN game vs book, median)


def _json(p):
    return json.loads((ROOT / p).read_text())


def latency_inputs() -> dict:
    blk = _json("research/v2/blocklag/results.json")
    h4 = _json("results/summary.json")["h4"]
    vb = _json("results/engine/vision_bench.json")
    # the only configuration that bounds its lag at 120 fps input (it skips frames); lowest p50 if several
    best = min((s for s in vb["summary"] if s.get("bounded_call_latency_ms")),
               key=lambda s: s["bounded_call_latency_ms"]["p50"])
    bounded = best["bounded_call_latency_ms"]
    return {
        "block_lag_s": {"median": blk["median_lag_s"], "p10": blk["p10"], "p90": blk["p90"], "n": blk["n"],
                        "source": "research/v2/blocklag/results.json (data-api block time minus CLOB ws match time, "
                                  "5,472 trades matched by tx hash)"},
        "camera_s": CAMERA, "cv_assumed_s": T_INF, "cv_pessimistic_s": T_INF_PESS,
        "cv_measured_s": {"p50": bounded["p50"] / 1e3, "p90": bounded["p90"] / 1e3, "config": best["config"],
                          "frames_skipped": bounded.get("frames_skipped"), "max_lag_ms": bounded.get("max_lag_ms"),
                          "keeps_up_with_120fps": best["keeps_up_with_120fps"], "calls_enabled": best["calls_enabled"],
                          "source": "results/engine/vision_bench.json summary[].bounded_call_latency_ms (laptop M4, "
                                    "frame skipping to bound lag; stand-in classifier, calls disabled)"},
        "net_florida_s": NET_FL, "net_london_s": NET_LDN, "human_reaction_s": REACT,
        "stream_delay_s_assumed": list(STREAM),
        "h4_book_leads_public_score_s": {"median": h4["median_lead_s"], "n": h4["n"],
                                         "share_book_first": h4["share_book_first"], "source": "results/summary.json h4"},
        "espn_behind_book_s": ESPN_BEHIND_BOOK,
    }


def stacks(L: dict) -> list[dict]:
    """Pre-venue latency l per stack (s). The venue delay delta_m is added per market in Reading A."""
    cv_m = L["cv_measured_s"]["p50"]
    h4 = L["h4_book_leads_public_score_s"]["median"]
    S = [
        # (c) courtside camera + CV + Florida, (d) the same from London: the four pre-registered stacks first
        ("c", "FL-20", "camera + CV 20 ms + Florida 67 ms", CAMERA + T_INF + NET_FL, True),
        ("c", "FL-50", "camera + CV 50 ms + Florida 67 ms", CAMERA + T_INF_PESS + NET_FL, True),
        ("d", "LDN-20", "camera + CV 20 ms + London 2 ms", CAMERA + T_INF + NET_LDN, True),
        ("d", "LDN-50", "camera + CV 50 ms + London 2 ms", CAMERA + T_INF_PESS + NET_LDN, True),
        ("c", "FL-meas", f"camera + measured CV {cv_m * 1e3:.1f} ms + Florida 67 ms", CAMERA + cv_m + NET_FL, False),
        ("d", "LDN-meas", f"camera + measured CV {cv_m * 1e3:.1f} ms + London 2 ms", CAMERA + cv_m + NET_LDN, False),
        # (a) public stream viewer, (b) public score feed
        ("a", "stream-5s", "stream 5 s + reaction 0.25 s + Florida 67 ms", STREAM[0] + REACT + NET_FL, False),
        ("a", "stream-30s", "stream 30 s + reaction 0.25 s + Florida 67 ms", STREAM[1] + REACT + NET_FL, False),
        ("b", "feed-ESPN", "ESPN 28.2 s behind the book + Florida 67 ms", ESPN_BEHIND_BOOK + NET_FL, False),
        ("b", "feed-h4", f"public score {h4:.1f} s behind the book (h4) + Florida 67 ms", h4 + NET_FL, False),
    ]
    return [{"group": g, "name": n, "what": w, "l_s": round(l, 4), "preregistered": pr} for g, n, w, l, pr in S]


# ------------------------------------------------------------------------------------- prints
def bin_of(x, edges=EDGES, labels=BINS) -> np.ndarray:
    x = np.asarray(x, float)
    i = np.searchsorted(edges, x, "right") - 1
    lab = np.array(labels + [BASE], dtype=object)
    return np.where((x < 0) | (x >= edges[-1]), BASE, lab[np.clip(i, 0, len(labels) - 1)])


def load(paths: list[tuple[str, str]]) -> pd.DataFrame:
    out = []
    for path, period in paths:
        d = pd.read_parquet(ROOT / path, columns=COLS)
        out.append(d.assign(period=period))
    return pd.concat(out, ignore_index=True)


def prep(P: pd.DataFrame, keep_cond_str: bool = False) -> tuple[pd.DataFrame, dict]:
    """Causal labels, fees, bins and walk-forward fast-tier labels. cond/wallet become integer codes
    (factorize(sort=True), so groupby order, and so every seeded bootstrap, matches the string keys)."""
    if keep_cond_str:
        P["cond_str"] = P.cond
    P["cond"] = pd.factorize(P.cond, sort=True)[0]
    P["wallet"] = pd.factorize(P.wallet, sort=True)[0]
    t0 = time.time()
    # add_causal_bucket (unchanged) on the columns it reads; its labels are joined back by index
    lab = add_causal_bucket(P[["cond", "ts", "p", "usd", "dir"]])
    for c in ("since_det", "with_jump_det", "bucket_c"):
        P[c] = lab[c]
    del lab
    t_causal = time.time() - t0
    P["fee"] = P.fee_rate * P.p * (1 - P.p)
    P["net30"] = P.mo30 - P.fee
    P["net_res"] = P.mo_res - P.fee
    P["bin"] = bin_of(P.since_det)
    P["bin_b"] = bin_of(P.since_det, BEDGES, BBINS)
    # walk-forward fast tier, exactly the loop in fasttier.walk_forward (qualify sees only "0-3s" rows)
    month = pd.to_datetime(P.ts, unit="s").dt.to_period("M")
    months = sorted(month.unique())
    f03 = P.loc[P.bucket_c == "0-3s", ["cond", "wallet", "mo30", "bucket_c"]].assign(month=month)
    fast = np.full(len(P), np.nan)
    wf = []
    for m in months[2:]:
        sel = fasttier.qualify(f03[f03.month < m], "bucket_c")
        cur = (month == m).to_numpy()
        isf = np.isin(P.wallet.to_numpy()[cur], sel)
        fast[cur] = isf
        wf.append({"month": str(m), "n_wallets": int(len(sel)), "n_fast_prints": int(isf.sum())})
    P["fast"] = fast  # 1 = qualified wallet, 0 = other wallet, NaN = month not evaluated
    # every detection is stamped at its own detection print (since_det = 0), so this counts detections exactly
    post = P[P.since_det >= 0]
    n_det = int(pd.DataFrame({"c": post.cond, "t": post.ts - post.since_det}).drop_duplicates().shape[0])
    meta = {"prints": int(len(P)), "matches": int(P.cond.nunique()),
            "matches_with_detection": int(post.cond.nunique()), "detections": n_det,
            "months": [str(m) for m in months], "fast_tier_walk_forward": wf, "add_causal_bucket_s": round(t_causal, 1)}
    return P, meta


# ------------------------------------------------------------------------------------- statistics
def summarize(x: pd.DataFrame, col: str) -> dict:
    x = x[np.isfinite(x[col].to_numpy())]
    if not len(x):
        return {"n": 0, "matches": 0, "mean_c": None, "ci_c": None}
    lo, hi = fasttier.cluster_ci(x[["cond", col]], col, N_BOOT, SEED)
    return {"n": int(len(x)), "matches": int(x.cond.nunique()), "mean_c": round(100 * float(x[col].mean()), 4),
            "ci_c": [round(100 * lo, 4), round(100 * hi, 4)], "fee_c": round(100 * float(x.fee.mean()), 4)}


CURVES = {
    "all": lambda d: d,
    "with_jump": lambda d: d[d.with_jump_det > 0],
    "against_jump": lambda d: d[d.with_jump_det < 0],
    "fast": lambda d: d[d.fast == 1],
    "others": lambda d: d[d.fast == 0],
    "fast_with_jump": lambda d: d[(d.fast == 1) & (d.with_jump_det > 0)],
}
PREREG_CURVES = ("all", "with_jump", "against_jump")


def curves(P: pd.DataFrame, scheme="prereg", measures=("net30", "net_res")) -> dict:
    _, labels, col = SCHEMES[scheme]
    out = {}
    groups = {b: g for b, g in P.groupby(col, sort=False)}
    for cname, f in CURVES.items():
        out[cname] = {}
        for meas in measures:
            rows = {}
            for b in labels + [BASE]:
                g = groups.get(b)
                rows[b] = summarize(f(g), meas) if g is not None else {"n": 0, "matches": 0, "mean_c": None, "ci_c": None}
                if b in EMPTY_BY_CONSTRUCTION + ["0.25-1"]:
                    rows[b]["note"] = "not resolvable on block-time tapes (since_det is a whole number of seconds)"
            out[cname][meas] = rows
    return out


def decay_test(P: pd.DataFrame, col="net30", a=(1, 2), b=(10, 30)) -> dict:
    """Pre-registered: with-jump net30 in [1,2) minus [10,30); paired match-clustered bootstrap."""
    w = P[(P.with_jump_det > 0) & np.isfinite(P[col].to_numpy())]
    A = w[(w.since_det >= a[0]) & (w.since_det < a[1])]
    B = w[(w.since_det >= b[0]) & (w.since_det < b[1])]
    if not len(A) or not len(B):
        return {"stat_c": None, "ci_c": None, "decays": None, "n_a": int(len(A)), "n_b": int(len(B)),
                "note": "a bin is empty"}
    conds = np.union1d(A.cond.unique(), B.cond.unique())
    ga = A.groupby("cond")[col].agg(["sum", "size"]).reindex(conds, fill_value=0)
    gb = B.groupby("cond")[col].agg(["sum", "size"]).reindex(conds, fill_value=0)
    sa, na, sb, nb = (ga["sum"].to_numpy(), ga["size"].to_numpy(), gb["sum"].to_numpy(), gb["size"].to_numpy())
    rng = np.random.default_rng(SEED)
    k = len(conds)
    d = np.empty(N_BOOT)
    for r in range(N_BOOT):
        i = rng.integers(0, k, k)
        nA, nB = na[i].sum(), nb[i].sum()
        d[r] = (sa[i].sum() / nA - sb[i].sum() / nB) if nA and nB else np.nan
    lo, hi = np.nanpercentile(d, [2.5, 97.5])
    stat = A[col].mean() - B[col].mean()
    return {"stat_c": round(100 * stat, 4), "ci_c": [round(100 * lo, 4), round(100 * hi, 4)],
            "decays": bool(lo > 0), "a_c": round(100 * A[col].mean(), 4), "b_c": round(100 * B[col].mean(), 4),
            "n_a": int(len(A)), "n_b": int(len(B)), "matches": int(k),
            "matches_a": int(A.cond.nunique()), "matches_b": int(B.cond.nunique()),
            "undefined_draws": int(np.isnan(d).sum())}


def read_stack(P: pd.DataFrame, l: float, scheme="prereg") -> dict:
    """Reading A: x = l + delta_m per print's own market, bin containing x. Reading B: x = l."""
    edges, labels, col = SCHEMES[scheme]
    out = {}
    for reading in ("A", "B"):
        sel = np.zeros(len(P), bool)
        per_delay = {}
        for d in sorted(P.delay.unique()):
            x = l + d if reading == "A" else l
            bx = bin_of([x], edges, labels)[0]
            m = (P.delay == d).to_numpy() & (P[col] == bx).to_numpy()
            if bx == BASE:  # >= 30 s after the latest detection (prints before any detection carry no direction)
                m &= (P.since_det >= EDGES[-1]).to_numpy()
            sel |= m
            per_delay[f"{int(d)}s"] = {"x_s": round(x, 4), "bin": bx}
        S = P[sel]
        out[reading] = {"per_delay": per_delay,
                        "with_jump": {"net30": summarize(CURVES["with_jump"](S), "net30"),
                                      "net_res": summarize(CURVES["with_jump"](S), "net_res")},
                        "all": {"net30": summarize(S, "net30")},
                        "fast": {"net30": summarize(CURVES["fast"](S), "net30")}}
    return out


def sport_block(P: pd.DataFrame, subsets: dict[str, pd.DataFrame], S: list[dict], primary: str) -> dict:
    res = {"subsets": {}}
    for name, d in subsets.items():
        t0 = time.time()
        sd = d.since_det[(d.since_det >= 0) & (d.since_det <= 10)].round().astype(int).value_counts().sort_index()
        r = {"prints": int(len(d)), "matches": int(d.cond.nunique()),
             "prints_since_det_ge0": int((d.since_det >= 0).sum()),
             "since_det_counts_0_10": {str(k): int(v) for k, v in sd.items()},
             "delays": {f"{int(k)}s": int(v) for k, v in d.groupby("delay").cond.nunique().items()},
             "curves": curves(d), "decay_test": decay_test(d), "decay_test_net_res": decay_test(d, "net_res"),
             "stacks": {s["name"]: read_stack(d, s["l_s"]) for s in S},
             "block": {"curves": curves(d, "block"), "decay_test": decay_test(d, a=(1, 3)),
                       "decay_test_net_res": decay_test(d, "net_res", a=(1, 3)),
                       "stacks": {s["name"]: read_stack(d, s["l_s"], "block") for s in S}}}
        r["seconds"] = round(time.time() - t0, 1)
        res["subsets"][name] = r
        print(f"  {name}: {r['matches']} matches, {r['prints']:,} prints, {r['seconds']} s, decay(prereg) "
              f"{r['decay_test']}, decay(block) {r['block']['decay_test']}", flush=True)
    res["primary"] = primary
    return res


# ------------------------------------------------------------------------------------- figure
def figure(J: dict, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    C = {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#8a8984", "grid": "#e4e3df",
         "with": "#2a78d6", "fast": "#eb6834", "all": "#1baf7a", "stack": "#52514e", "band": "#f0efec"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": C["grid"],
                         "axes.labelcolor": C["ink2"], "xtick.color": C["ink2"], "ytick.color": C["ink2"]})
    X0, X1 = 0.02, 100.0
    seg = {"0-0.25": (X0, 0.25), "1-3": (1, 3), "3-5": (3, 5), "5-10": (5, 10), "10-30": (10, 30), BASE: (30, X1)}
    panels = [("tennis", "Tennis · Polymarket ATP/WTA moneylines · U1 IS + burned OOS (non-blind)"),
              ("table_tennis", "Table tennis · Polymarket WTT + Setka moneylines · UTT (first look)")]
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 11.5), facecolor=C["surface"])
    for ax, (sport, title) in zip(axes, panels):
        B = J[sport]
        sub = B["subsets"][B["primary"]]
        blk = sub["block"]  # block-resolution bins (PRERUN.md TT5-D3)
        ax.set_facecolor(C["surface"])
        ax.set_xscale("log")
        ax.set_xlim(X0, X1)
        series = [("with_jump", "with-jump takers (trade in the jump's direction)", C["with"]),
                  ("all", "all takers", C["all"]),
                  ("fast", "fast tier (walk-forward wallets)", C["fast"])]
        ymin, ymax = 0, 0
        shown = []
        for key, lab, col in series:
            rows = blk["curves"][key]["net30"]
            if not any(rows[b]["n"] for b in seg):
                continue
            for b, (a, z) in seg.items():
                r = rows[b]
                if not r["n"]:
                    continue
                lo, hi = r["ci_c"]
                ax.fill_between([a, z], lo, hi, color=col, alpha=0.10, lw=0, zorder=1)
                ax.plot([a, z], [r["mean_c"]] * 2, color=col, lw=2, solid_capstyle="round", zorder=3)
                ymin, ymax = min(ymin, lo), max(ymax, hi)
            pts = [(seg[b], rows[b]["mean_c"]) for b in seg if rows[b]["n"]]
            for (s0, v0), (s1, v1) in zip(pts, pts[1:]):  # thin risers so each curve reads as one line
                if s0[1] == s1[0]:
                    ax.plot([s0[1], s0[1]], [v0, v1], color=col, lw=1, alpha=0.6, zorder=2)
            shown.append((lab, col))
        ax.axhline(0, color=C["ink2"], lw=0.8, zorder=2)
        rng_ = (ymax - ymin) or 1.0
        ylo, yhi = ymin - 0.10 * rng_, ymax + 0.80 * rng_  # the top strip holds the stack labels
        ax.set_ylim(ylo, yhi)
        H = yhi - ylo
        # bins the tape cannot resolve
        ax.add_patch(Rectangle((0.25, ylo), 0.75, H, facecolor=C["band"], edgecolor="none", zorder=0))
        for x, t in ((0.5, "0.25–1 s: not resolvable\n(whole-second stamps,\n~2 s blocks)"), (0.075, "same block\n(0 s)"),
                     (1.73, "next block\n(1–2 s)"), (55, "baseline\n(≥ 30 s)")):
            ax.text(x, ylo + 0.03 * H, t, ha="center", va="bottom", fontsize=7.8, color=C["muted"], zorder=4)
        ax.axvline(30, color=C["grid"], lw=1, zorder=0)
        # latency stacks: Reading A positions for a 1 s venue delay; Reading B (x = l) dotted
        st = {s["name"]: s for s in J["stacks"]}
        A = lambda n: st[n]["l_s"] + 1.0  # noqa: E731
        rd = lambda n, k="A", c="with_jump": blk["stacks"][n][k][c]["net30"]  # noqa: E731

        def val(r):
            if not r["n"]:
                return "no prints"
            small = f"\n({r['n']} print{'s' if r['n'] > 1 else ''}, {r['matches']} match{'es' if r['matches'] > 1 else ''})" \
                if r["n"] < 30 else ""
            return f"{r['mean_c']:+.2f}¢ [{r['ci_c'][0]:+.2f}, {r['ci_c'][1]:+.2f}]{small}"
        box = dict(boxstyle="round,pad=0.25", fc=C["surface"], ec="none", alpha=0.9)
        row1, row2 = yhi - 0.02 * H, yhi - 0.25 * H
        for n in ("LDN-20", "FL-meas"):
            ax.axvline(st[n]["l_s"], color=C["stack"], lw=0.8, ls=(0, (2, 2)), alpha=0.7, zorder=2)
        ax.text(0.022, row1, f"Reading B (x = ℓ, {st['LDN-20']['l_s']:.2f}–{st['FL-meas']['l_s']:.2f} s)\n"
                f"upper bound: venue delay\ncancels on the tape clock\nwith-jump {val(rd('FL-20', 'B'))}\n"
                f"fast tier {val(rd('FL-20', 'B', 'fast'))}",
                fontsize=7.6, color=C["ink"], va="top", ha="left", bbox=box, zorder=5)
        for n in ("LDN-20", "FL-meas"):
            ax.axvline(A(n), color=C["stack"], lw=1, alpha=0.85, zorder=2)
        ax.text(A("FL-meas") * 1.05, row1,
                f"(c) Florida / (d) London: camera + CV\n+ network + venue delay 1 s\n"
                f"x = {A('LDN-20'):.2f}–{A('FL-meas'):.2f} s (all in one bin)\n"
                f"Reading A (each market's own δ):\nwith-jump {val(rd('FL-20'))}\nfast tier {val(rd('FL-20', 'A', 'fast'))}",
                fontsize=7.6, color=C["ink"], va="top", ha="left", bbox=box, zorder=5)
        a0, a1 = A("stream-5s"), A("stream-30s")
        yb = row2 - 0.005 * H
        ax.plot([a0, a1], [yb, yb], color=C["stack"], lw=1, zorder=2)
        for x in (a0, a1):
            ax.plot([x, x], [yb - 0.02 * H, yb + 0.02 * H], color=C["stack"], lw=1, zorder=2)
        ax.text(a0 * 1.04, yb - 0.03 * H,
                f"(a) public stream viewer, x = {a0:.1f}–{a1:.1f} s\n(5–30 s stream delay, assumed)\n"
                f"at 5 s: with-jump {val(rd('stream-5s'))}", fontsize=7.6, color=C["ink"], va="top", ha="left",
                bbox=box, zorder=5)
        ax.axvline(A("feed-h4"), color=C["stack"], lw=1, alpha=0.85, zorder=2)
        ax.text(A("feed-h4") / 1.05, row1, f"(b) public score feed\nx = {A('feed-h4'):.1f} s (h4)\nwith-jump {val(rd('feed-h4'))}",
                fontsize=7.6, color=C["ink"], va="top", ha="right", bbox=box, zorder=5)
        for n, x in (("stream-5s", a0), ("feed-h4", A("feed-h4"))):  # these read the same bin for 1 s and 3 s markets
            r = rd(n)
            if r["n"]:
                ax.plot([x], [r["mean_c"]], "o", ms=8, color=C["with"], mec=C["surface"], mew=2, zorder=6)
        ax.set_xticks([0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 30, 100])
        ax.set_xticklabels(["0.02", "0.05", "0.1", "0.25", "0.5", "1", "2", "3", "5", "10", "30", "100"])
        ax.minorticks_off()
        ax.grid(axis="y", color=C["grid"], lw=1)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.set_ylabel("net 30 s markout, ¢/share, after taker fee")

        def _d(t, lab):
            if t["stat_c"] is None:
                return f"{lab}: not computable (0 with-jump prints in the early bin)"
            return (f"{lab}: {t['stat_c']:+.2f}¢ [{t['ci_c'][0]:+.2f}, {t['ci_c'][1]:+.2f}], "
                    f"{'decays' if t['decays'] else 'no decay shown'} (n = {t['n_a']:,} vs {t['n_b']:,} prints)")
        ax.set_title(f"{title}\n{sub['matches']:,} matches · {sub['prints']:,} taker prints · "
                     + _d(blk["decay_test"], "decay test, with-jump [1,3) − [10,30)") + "\n"
                     + _d(sub["decay_test"], "pre-registered [1,2) − [10,30)"),
                     loc="left", fontsize=9.5, color=C["ink"], pad=24)
        handles = [plt.Line2D([], [], color=col, lw=2) for _, col in shown]
        ax.legend(handles, [lab for lab, _ in shown], loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3,
                  frameon=False, fontsize=8.3, borderaxespad=0.2, handlelength=1.6)
        if not any(blk["curves"]["fast"]["net30"][b]["n"] for b in seg):
            ax.text(0.008, 0.70, "fast tier: no wallet qualified\n(≥ 30 prints over ≥ 10 matches\nin past months)",
                    transform=ax.transAxes, ha="left", va="top", fontsize=7.8, color=C["muted"], bbox=box, zorder=5)
    axes[-1].set_xlabel("seconds after jump detection (block clock, log scale)")
    bl = J["latency_inputs"]["block_lag_s"]
    foot = [
        "Steps: print-weighted mean per bin; bands: match-clustered 95% CI (2,000 draws). Stack markers are drawn for a 1 s venue delay. "
        "Reading A uses each market's own delay",
        "(1 s markets read [1,3), 3 s markets read [3,5)), so the (c)+(d) value is not the [1,3) step. "
        f"Tape stamps are block times, a median {bl['median']:.2f} s (p10 {bl['p10']:.2f}, p90 {bl['p90']:.2f}) after the trade.",
        "since_det is a difference of two stamps, so that lag cancels up to ~1 s of jitter; a detector fed by the data-api tape "
        "sees the jump ~2 s late, so it cannot act before x ≈ 2 s.",
        "Assumes the point happens at detection (detection can lag the move by up to 10 s). Bins: research/decay/PRERUN.md (TT5-D3).",
    ]
    fig.text(0.01, 0.005, "\n".join(foot), fontsize=7.6, color=C["ink2"], va="bottom")
    fig.tight_layout(rect=(0, 0.065, 1, 1))
    fig.savefig(path, dpi=150, facecolor=C["surface"])
    plt.close(fig)


# ------------------------------------------------------------------------------------- main
def git_hash() -> str:
    h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "scripts/signal_decay.py"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    return h + ("+dirty(signal_decay.py)" if dirty else "")


def dev(n_matches: int):
    """Code check on the first n tennis IS matches only (no table tennis, no OOS, nothing logged)."""
    import os
    L = latency_inputs()
    S = stacks(L)
    P = pd.read_parquet(ROOT / "data/is_prints.parquet", columns=COLS)
    keep = P.cond.drop_duplicates().iloc[:n_matches]
    P = P[P.cond.isin(keep)].reset_index(drop=True).assign(period="IS")
    P, meta = prep(P)
    J = {"latency_inputs": L, "stacks": S, "tennis": sport_block(P, {"IS": P}, S, "IS"),
         "table_tennis": sport_block(P, {"IS": P}, S, "IS")}
    J["tennis"]["meta"] = meta
    out = Path(os.environ.get("DEV_OUT", "/tmp"))
    (out / "decay_dev.json").write_text(json.dumps(J, indent=1, default=float))
    figure(J, out / "fig_dev.png")
    print(json.dumps(meta)[:800])


def tables(J: dict) -> str:
    """Markdown tables for research/decay/RESULTS.md, from results/decay/decay.json only."""
    def f(r):
        if not r or not r.get("n"):
            return "–"
        return f"{r['mean_c']:+.2f} [{r['ci_c'][0]:+.2f}, {r['ci_c'][1]:+.2f}]"

    def nm(r):
        return f"{r['n']:,} / {r['matches']:,}" if r and r.get("n") else "0"
    out = []
    for sport in ("tennis", "table_tennis"):
        B = J[sport]
        for name, sub in B["subsets"].items():
            out.append(f"\n#### {sport} · {name} ({sub['matches']:,} matches, {sub['prints']:,} prints)\n")
            out.append(f"since_det counts 0–10 s: {sub['since_det_counts_0_10']}\n")
            for scheme, C, labels in (("pre-registered bins", sub["curves"], BINS), ("block-resolution bins", sub["block"]["curves"], BBINS)):
                for meas in ("net30", "net_res"):
                    out.append(f"\n{scheme}, {meas} (¢/share, match-clustered 95% CI); n prints / matches for all and with-jump\n")
                    out.append("| bin | all | with-jump | against-jump | fast tier | others | n all | n with |")
                    out.append("|---|---|---|---|---|---|---|---|")
                    for bb in labels + [BASE]:
                        row = [C[k][meas][bb] for k in ("all", "with_jump", "against_jump", "fast", "others")]
                        out.append(f"| {bb} | " + " | ".join(f(r) for r in row) + f" | {nm(row[0])} | {nm(row[1])} |")
            out.append("\nfee check, net30 + mean fee = gross 30 s markout (¢/share), pre-registered bins\n")
            out.append("| bin | with-jump net30 | mean fee | with-jump gross | fast net30 | fast mean fee | fast gross |")
            out.append("|---|---|---|---|---|---|---|")
            for bb in BINS + [BASE]:
                w, fs = sub["curves"]["with_jump"]["net30"][bb], sub["curves"]["fast"]["net30"][bb]
                g = lambda r: (f"{r['mean_c']:+.2f} | {r['fee_c']:.2f} | {r['mean_c'] + r['fee_c']:+.2f}"  # noqa: E731
                               if r.get("n") else "– | – | –")
                out.append(f"| {bb} | {g(w)} | {g(fs)} |")
            for lab, t in (("pre-registered decay [1,2)-[10,30)", sub["decay_test"]),
                           ("block decay [1,3)-[10,30)", sub["block"]["decay_test"]),
                           ("block decay, net_res", sub["block"]["decay_test_net_res"])):
                if t["stat_c"] is None:
                    out.append(f"\n{lab}: not computable (n_a={t['n_a']}, n_b={t['n_b']})")
                else:
                    out.append(f"\n{lab}: {t['stat_c']:+.2f} [{t['ci_c'][0]:+.2f}, {t['ci_c'][1]:+.2f}] decays={t['decays']} "
                               f"(a {t['a_c']:+.2f}, b {t['b_c']:+.2f}; n {t['n_a']}/{t['n_b']}; matches {t['matches']})")
            out.append("\n| stack | l (s) | reading | bins by delay | with-jump net30 (prereg bins) | with-jump net30 (block) | "
                       "with-jump net_res (block) | all takers net30 (block) | fast tier net30 (block) |")
            out.append("|---|---|---|---|---|---|---|---|---|")
            for st in J["stacks"]:
                for rd in ("A", "B"):
                    P_, K_ = sub["stacks"][st["name"]][rd], sub["block"]["stacks"][st["name"]][rd]
                    bins = ", ".join(f"{k}:{v['bin']}" for k, v in K_["per_delay"].items())
                    out.append(f"| {st['name']} | {st['l_s']:.4f} | {rd} | {bins} | {f(P_['with_jump']['net30'])} | "
                               f"{f(K_['with_jump']['net30'])} | {f(K_['with_jump']['net_res'])} | {f(K_['all']['net30'])} | "
                               f"{f(K_['fast']['net30'])} |")
        out.append(f"\n{sport} meta: " + json.dumps(B.get("meta"), default=str)[:3000])
    return "\n".join(out)


def stamp_gaps() -> dict:
    """Tape time resolution: share of 1..6 s gaps between consecutive in-play prints of a match, by quarter.
    Reads timestamps only (no price, markout or P&L)."""
    out = {}
    for path in ("data/is_prints.parquet", "data/locked/oos_prints.parquet", "data/tt/prints.parquet"):
        P = pd.read_parquet(ROOT / path, columns=["cond", "ts"])
        d = P.groupby("cond").ts.diff()
        q = pd.to_datetime(P.ts, unit="s").dt.to_period("Q").astype(str)
        k = d.notna() & (d > 0) & (d <= 6)
        tab = pd.crosstab(q[k], d[k].astype(int))
        out[path] = {"share_of_1_to_6s_gaps": {qq: {str(g): round(float(v), 4) for g, v in (row / row.sum()).items()}
                                               for qq, row in tab.iterrows()},
                     "n_gaps": {qq: int(row.sum()) for qq, row in tab.iterrows()},
                     "share_zero_gap": round(float((d[d.notna()] == 0).mean()), 4)}
    (OUT / "stamp_gaps.json").write_text(json.dumps(out, indent=1))
    return out


def main():
    if "--gaps" in sys.argv:  # timestamp structure only -> results/decay/stamp_gaps.json
        return print(json.dumps(stamp_gaps(), indent=1))
    if "--tables" in sys.argv:  # print markdown tables from the saved results; no data is read
        return print(tables(json.loads((OUT / "decay.json").read_text())))
    if "--dev" in sys.argv:
        return dev(int(sys.argv[sys.argv.index("--dev") + 1]))
    if "--figure" in sys.argv:  # re-render from the saved results; no data is read
        return figure(json.loads((OUT / "decay.json").read_text()), OUT / "fig_signal_decay.png")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    gh = git_hash()
    (ROOT / "results/tt").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "results/tt/peeks.log", "a") as f:
        f.write(f"{now} {gh} TT5 signal decay run (scripts/signal_decay.py; research/decay/PRERUN.md): "
                f"UTT prints (IS+OOS) + unlisted sensitivity; tennis U1 IS + burned OOS (non-blind)\n")
    with open(ROOT / "results/oos_peeks.log", "a") as f:
        f.write(f"{now} TT5 signal decay (scripts/signal_decay.py, commit {gh}): reads table tennis UTT OOS prints "
                f"(first look, descriptive curve) and tennis burned OOS prints (non-blind); no rule or parameter chosen\n")
    L = latency_inputs()
    S = stacks(L)
    J = {"generated_utc": now, "git": gh, "hypothesis": "HYPOTHESIS_TT.md TT5; research/decay/PRERUN.md",
         "bins": BINS, "baseline": "since_det < 0 (before the first detection) or >= 30 s after the latest one",
         "empty_by_construction": EMPTY_BY_CONSTRUCTION, "measures": {
             "net30": "dir*(mid(t+30s) - p) - fee_rate*p*(1-p)  [pre-registered]",
             "net_res": "dir*(res - p) - fee_rate*p*(1-p)  [secondary, not pre-registered]"},
         "ci": "fasttier.cluster_ci: resample matches, 2,000 draws, seed 0; values in cents per share",
         "latency_inputs": L, "stacks": S}

    print("table tennis ...", flush=True)
    u = pd.read_parquet(ROOT / "data/tt/universe.parquet", columns=["cond", "oos", "league"])
    T = load([("data/tt/prints.parquet", "UTT")])
    T, tmeta = prep(T, keep_cond_str=True)
    T = T.merge(u.rename(columns={"cond": "cond_str"}), on="cond_str", how="left", validate="m:1")
    assert T.oos.notna().all()
    TU = load([("data/tt/prints.parquet", "UTT"), ("data/tt/prints_unlisted.parquet", "unlisted")])
    TU, tumeta = prep(TU)
    J["table_tennis"] = sport_block(T, {"UTT": T, "WTT": T[T.league == "WTT"], "Setka": T[T.league == "Setka"],
                                        "IS": T[~T.oos], "OOS": T[T.oos], "UTT+unlisted (sensitivity)": TU}, S, "UTT")
    J["table_tennis"]["meta"] = {"UTT": tmeta, "UTT+unlisted": tumeta}

    print("tennis ...", flush=True)
    P = load([("data/is_prints.parquet", "IS"), ("data/locked/oos_prints.parquet", "burned_OOS")])
    P, pmeta = prep(P)
    print(f"  add_causal_bucket {pmeta['add_causal_bucket_s']} s", flush=True)
    J["tennis"] = sport_block(P, {"IS+burned_OOS": P, "IS": P[P.period == "IS"],
                                  "burned_OOS": P[P.period == "burned_OOS"]}, S, "IS+burned_OOS")
    J["tennis"]["meta"] = pmeta

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "decay.json").write_text(json.dumps(J, indent=1, default=float))
    figure(J, OUT / "fig_signal_decay.png")
    print("wrote", OUT / "decay.json", OUT / "fig_signal_decay.png")


if __name__ == "__main__":
    main()
