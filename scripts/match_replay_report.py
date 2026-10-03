#!/usr/bin/env python
"""Figures and research/replay/RESULTS.md for the match replay (scripts/match_replay.py).

    BACKTEST REPLAY on a real match recorded live on 2026-10-03 — assumed 1 s licensed video feed (not
    purchased); bounce time = official point stamp - assumed stamp lag; fills priced against the real
    recorded order book; paper only.

Reads results/replay/{replay.json, points.csv, seed_robustness.csv, selected_match_book.csv} and, when present,
results/replay/audit.json (scripts/match_replay_check.py); writes results/replay/fig_*.png and
research/replay/RESULTS.md. Every number in RESULTS.md is read from those files, except the protocol-literal
numbers of deviation D1, which are the committed values of c6c728d.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "replay"
DOC = ROOT / "research" / "replay"
M1 = ROOT / "research/v2/latency/out/m1_points.csv"
SWEEP = "research/v2/feed_latency/LATENCY_SWEEP.md"   # moved from research/v2/tier0/ in 84c3898
# protocol-literal headline (60 s rule only, before deviation D1), committed in c6c728d
LITERAL = {"V0": (174, -0.61, -181, -213), "V0.5": (169, -0.65, -174, -226), "V1": (151, -0.92, -229, -387)}

# reference palette (dataviz skill, light mode): categorical slots 1-3 + neutrals
SURF, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
VCOL = {0.0: BLUE, 0.5: ORANGE, 1.0: AQUA}


def _style():
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
                         "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF,
                         "savefig.facecolor": SURF, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titlecolor": INK, "legend.frameon": False})


def _footer(fig, label, y=0.006):
    fig.text(0.01, y, "\n".join(textwrap.wrap(label, 165)), fontsize=7.2, color=INK2, ha="left", va="bottom")


def _dt(ms):
    return pd.to_datetime(ms, unit="ms", utc=True)


def load():
    res = json.loads((OUT / "replay.json").read_text())
    pts = pd.read_csv(OUT / "points.csv")
    sr = pd.read_csv(OUT / "seed_robustness.csv")
    tl = pd.read_csv(OUT / "selected_match_book.csv", comment="#")
    return res, pts, sr, tl


def load_audit():
    f = OUT / "audit.json"
    return json.loads(f.read_text()) if f.exists() else None


def fill_class(g: pd.DataFrame) -> pd.Series:
    cb = g.correct_call.astype(bool)
    bb = g.beat_book == True  # noqa: E712
    return np.where(~cb, "wrong call", np.where(bb, "correct, before the reprice", "correct, not before a reprice"))


def decomposition(pts: pd.DataFrame) -> pd.DataFrame:
    F = pts[pts.shares > 1e-9].copy()
    F["cls"] = fill_class(F)
    F["gross_mark"] = F.shares * (F.mid_30s - F.vwap)
    rows = []
    for (V, c), g in F.groupby(["V", "cls"]):
        sh = g.shares.sum()
        rows.append({"V": V, "class": c, "fills": len(g), "shares": sh,
                     "gross_c": g.gross_mark.sum() / sh * 100, "fee_c": g.fee.sum() / sh * 100,
                     "net_mark_c": g.pnl_mark.sum() / sh * 100, "pnl_mark": g.pnl_mark.sum(),
                     "pnl_hold": g.pnl_hold.sum()})
    return pd.DataFrame(rows)


# ===================================================================================== figures
def fig_selected(res, pts, tl):
    sel = res["selected_match"]
    m = next(x for x in res["matches"] if x["slug"] == sel)
    g = pts[pts.slug == sel]
    lab = res["label"]
    fig, ax = plt.subplots(2, 1, figsize=(12, 7.6), sharex=True, gridspec_kw={"height_ratios": [2.1, 1.25]})
    t = _dt(tl.t_ms)
    ax[0].plot(t, tl.mid0, color=INK2, lw=1.0, label=f"recorded Polymarket mid, {m['n0']} to win")
    h = g[g.V == 1.0]
    T = _dt(h.T_ms)
    ax[0].vlines(T, 0.02, 0.05, color=MUTED, lw=0.6)
    ax[0].text(T.min(), 0.065, "official points", fontsize=8, color=INK2)
    F = h[h.shares > 1e-9]
    p0 = np.where(F.called_player == m["n0"], F.vwap, 1 - F.vwap)    # fill price in outcome-0 terms
    c = F.correct_call.astype(bool).to_numpy()
    ax[0].scatter(_dt(F.exec_ms)[c], p0[c], s=46, color=BLUE, edgecolor=SURF, lw=1.2, zorder=3,
                  label=f"fill, correct call ({c.sum()})")
    ax[0].scatter(_dt(F.exec_ms)[~c], p0[~c], s=46, color=ORANGE, edgecolor=SURF, lw=1.2, marker="D", zorder=3,
                  label=f"fill, simulated wrong call ({(~c).sum()})")
    Mx = h[h.status == "missed (book already moved)"]
    pm = np.where(Mx.called_player == m["n0"], Mx.limit, 1 - Mx.limit)
    ax[0].scatter(_dt(Mx.exec_ms), pm, s=30, marker="x", color=MUTED, lw=1.1, zorder=2,
                  label=f"missed: book already moved past the limit ({len(Mx)})")
    ax[0].set_ylim(0, 1)
    ax[0].set_ylabel(f"price of {m['n0']} (outcome 0)")
    ax[0].grid(axis="y", color=GRID, lw=0.6)
    ax[0].legend(loc="upper left", fontsize=8.5, ncol=2)
    ax[0].set_title(f"{m['n0']} v {m['n1']} (winner {m['winner_name']}), WTA Beijing, 2026-10-03: replayed point by "
                    f"point at V = 1.0 s video delay", loc="left", fontsize=11.5)
    for V in (0.0, 0.5, 1.0):
        x = g[g.V == V].sort_values("exec_ms")
        cum = x.pnl_mark.fillna(0).cumsum()
        st = res["selected_story"][f"V{V:g}"]
        ax[1].step(_dt(x.exec_ms), cum, where="post", color=VCOL[V], lw=2,
                   label=f"V = {V:g} s: {st['fills']} fills, beat the book on {st['beat_book']} of "
                         f"{st['calls_with_reprice']} calls, {usd(st['pnl_mark_usd'])} marked")
    ax[1].axhline(0, color=INK2, lw=0.8)
    ax[1].set_ylabel("cumulative P&L, $\n(marked at +30 s mid)")
    ax[1].grid(axis="y", color=GRID, lw=0.6)
    ax[1].legend(loc="lower left", fontsize=8.5)
    ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz="UTC"))
    ax[1].set_xlabel("UTC, 2026-10-03")
    _footer(fig, lab)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "fig_selected_match.png", dpi=160)
    plt.close(fig)


def example_points(res, pts):
    """Display only. (a) the selected match's largest matched book move (m1 D) among points whose call was
    quoted at every V; (b) the largest matched move among points where the V = 0 order filled before the
    reprice (chosen to show a race that is won; this one is selected on the replay's own outcome)."""
    sel = res["selected_match"]
    m1 = pd.read_csv(M1)
    s = pts[pts.slug == sel]
    bad = set(s[s.status.str.startswith("skipped") | (s.status == "no book recorded")].n)
    c = m1[(m1.slug == sel) & m1.t_book.notna() & ~m1.n.isin(bad)]
    na = int(c.loc[c.D.idxmax(), "n"])
    won = set(s[(s.V == 0.0) & (s.shares > 0) & (s.beat_book == True) & s.correct_call.astype(bool)].n)  # noqa: E712
    cw = c[c.n.isin(won)]
    nb = int(cw.loc[cw.D.idxmax(), "n"]) if len(cw) else na
    Dm = dict(zip(c.n, c.D))
    return [(na, Dm[na], "largest book move in the match"), (nb, Dm[nb], "largest move where the V = 0 order won")]


def _race_panel(ax, res, pts, tl, n, D, why, m):
    sel = res["selected_match"]
    g = pts[(pts.slug == sel) & (pts.n == n)].set_index("V")
    r = g.loc[1.0]
    T = r.T_ms
    w = (tl.t_ms >= T - 4500) & (tl.t_ms <= T + 3500)
    x = (tl.t_ms[w] - T) / 1000
    win0 = r.point_winner_name == m["n0"]
    ya = tl.ask0[w] if win0 else tl.ask1[w]
    ax.step(x, ya, where="post", color=INK, lw=1.9, label=f"best ask of {r.point_winner_name} (won the point)")
    ax.axhline(r.limit, color=INK2, lw=1.0, ls="-.", label=f"our limit: ask at the bounce + 1c = {r.limit:.2f}")
    ax.axvline((r.bounce_ms - T) / 1000, color=MUTED, lw=1.2, ls=":", label="assumed bounce (stamp - 2.0 s)")
    ax.axvline(0, color=INK2, lw=1.2, ls=":", label="official umpire stamp")
    ax.axvline((r.t_book_srv_ms - T) / 1000, color=INK, lw=1.3, ls="--", label="book reprices (half-move)")
    for V in (0.0, 0.5, 1.0):
        rr = g.loc[V]
        xe = (rr.exec_ms - T) / 1000
        out = (f"filled {rr.shares:.0f} @ {rr.vwap:.3f}" if rr.shares > 0 else rr.status)
        ax.axvline(xe, color=VCOL[V], lw=2.4, label=f"V = {V:g} s order executes at {xe:+.2f} s: {out}")
    lo, hi = float(np.nanmin(ya)), float(np.nanmax(ya))
    pad = max(0.02, (hi - lo) * 0.25)
    ax.set_ylim(lo - pad, hi + pad * 2.6)
    ax.set_xlim(x.iloc[0], x.iloc[-1])
    ax.set_xlabel("seconds from the official point stamp")
    ax.set_ylabel(f"price of {r.point_winner_name}")
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.legend(loc="upper left", fontsize=7.6, handlelength=1.6)
    ax.set_title(f"Point {n} (score after {r.score_after}): {why}, {D * 100:.1f}c", loc="left", fontsize=10.5)


def fig_point(res, pts, tl):
    sel = res["selected_match"]
    m = next(x for x in res["matches"] if x["slug"] == sel)
    ex = example_points(res, pts)
    fig, axs = plt.subplots(1, 2, figsize=(14, 6.2))
    for ax, (n, D, why) in zip(axs, ex):
        _race_panel(ax, res, pts, tl, n, D, why, m)
    fig.suptitle(f"The race on single points, {m['n0']} v {m['n1']}: our order (after the 1 s taker delay) against "
                 f"the book's reprice", x=0.01, ha="left", fontsize=12, color=INK)
    _footer(fig, res["label"])
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    fig.savefig(OUT / "fig_point_race.png", dpi=160)
    plt.close(fig)
    return ex


def fig_race(res, pts):
    fig, ax = plt.subplots(figsize=(10, 5))
    for V in (0.0, 0.5, 1.0):
        g = pts[(pts.V == V) & pts.exec_minus_book_s.notna() & ~pts.status.isin(["no book recorded"])
                & ~pts.status.str.startswith("skipped")]
        x = np.sort(g.exec_minus_book_s.clip(-4, 6).to_numpy())
        yv = np.arange(1, len(x) + 1) / len(x)
        a = res["headline_by_V"][f"V{V:g}"]["all"]
        ax.step(x, yv, where="post", color=VCOL[V], lw=2,
                label=f"V = {V:g} s: order beats the reprice on {a['calls_beat_book']} of {a['calls_with_reprice']} "
                      f"calls ({a['share_calls_beat_book']:.0%})")
    ax.axvline(0, color=INK, lw=1)
    ax.text(-0.08, 0.98, "our order executes\nbefore the book reprices", ha="right", va="top", fontsize=8.5, color=INK)
    ax.text(0.08, 0.98, "after: the stale price is gone", ha="left", va="top", fontsize=8.5, color=INK)
    ax.set_xlim(-4, 6)
    ax.set_ylim(0, 1)
    ax.set_xlabel("order execution time minus book reprice time, s (clipped to [-4, 6])")
    ax.set_ylabel("share of calls (cumulative)")
    ax.grid(color=GRID, lw=0.6)
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_title("Who gets there first, all 9 matches (stamp lag 2.0 s, Florida 67 ms, 1 s taker delay)",
                 loc="left", fontsize=11)
    _footer(fig, res["label"])
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(OUT / "fig_race.png", dpi=160)
    plt.close(fig)


def fig_pnl(res, dec):
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.9), gridspec_kw={"width_ratios": [1.05, 1]})
    Vs = [0.0, 0.5, 1.0]
    for j, (k, nm, off) in enumerate((("mark", "marked at +30 s mid", -0.09), ("hold", "held to the match result", 0.09))):
        for i, V in enumerate(Vs):
            a = res["headline_by_V"][f"V{V:g}"]["all"]
            v, ci = a[f"per_share_{k}_c"], a[f"per_share_{k}_ci95_c"]
            ax[0].errorbar([i + off], [v], yerr=[[v - ci[0]], [ci[1] - v]], fmt="o" if k == "mark" else "s",
                           ms=8, color=BLUE if k == "mark" else ORANGE, lw=1.6, capsize=0,
                           label=f"replay, {nm} (match-clustered 95 % CI)" if i == 0 else None)
    ref = res["sweep_reference"]
    for i, V in enumerate(Vs):
        kk = f"V{V:g}" if V != 1.0 else "V1"
        ax[0].scatter([i + 0.27], [ref["headline_reading_IS_c"][kk]], marker="^", s=50, facecolor="none",
                      edgecolor=INK2, lw=1.3, label="latency sweep, in sample" if i == 0 else None)
        ax[0].scatter([i + 0.27], [ref["headline_reading_OOS_c"][kk]], marker="v", s=50, facecolor="none",
                      edgecolor=MUTED, lw=1.3, label="latency sweep, burned OOS" if i == 0 else None)
    ax[0].axhline(0, color=INK2, lw=0.8)
    ax[0].set_xticks(range(3), [f"V = {V:g} s" for V in Vs])
    ax[0].set_ylabel("net P&L per share, cents")
    ax[0].grid(axis="y", color=GRID, lw=0.6)
    ax[0].legend(fontsize=8, loc="lower left")
    ax[0].set_title("Net per share, 9 matches (seed 0)", loc="left", fontsize=11)
    cls = ["correct, before the reprice", "correct, not before a reprice", "wrong call"]
    col = {cls[0]: BLUE, cls[1]: AQUA, cls[2]: ORANGE}
    wdt = 0.26
    for j, c in enumerate(cls):
        vals = [float(dec[(dec.V == V) & (dec["class"] == c)].pnl_mark.sum()) for V in Vs]
        xs = np.arange(3) + (j - 1) * (wdt + 0.02)
        ax[1].bar(xs, vals, width=wdt, color=col[c], edgecolor=SURF, lw=2, label=c)
        for xv, yv in zip(xs, vals):
            ax[1].text(xv, yv + (4 if yv >= 0 else -4), f"{yv:+.0f}", ha="center", va="bottom" if yv >= 0 else "top",
                       fontsize=8, color=INK)
    ax[1].axhline(0, color=INK2, lw=0.8)
    ax[1].set_xticks(range(3), [f"V = {V:g} s" for V in Vs])
    ax[1].set_ylabel("$ P&L marked at +30 s mid")
    ax[1].grid(axis="y", color=GRID, lw=0.6)
    ax[1].legend(fontsize=8, loc="lower left")
    ax[1].set_title("Where the money comes from (fills by type)", loc="left", fontsize=11)
    _footer(fig, res["label"])
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(OUT / "fig_pnl_by_v.png", dpi=160)
    plt.close(fig)


# ===================================================================================== markdown
def f2(x, nd=2, sign=True):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def ci(c):
    return f"[{c[0]:+.2f}, {c[1]:+.2f}]" if c and c[0] is not None else ""


def usd(x):
    return ("−$" if x < 0 else "+$") + f"{abs(x):,.0f}"


def headline_table(res) -> str:
    H = {V: res["headline_by_V"][f"V{V:g}"]["all"] for V in (0.0, 0.5, 1.0)}
    rows = [
        ("replayable official points", lambda a: f"{a['replayable_points']}"),
        ("calls (quoted, inside 5-95c)", lambda a: f"{a['calls']}"),
        ("of which simulated wrong calls", lambda a: f"{a['wrong_calls']}"),
        ("calls whose order executes before the book reprices", lambda a: f"{a['calls_beat_book']} of {a['calls_with_reprice']} ({a['share_calls_beat_book']:.0%})"),
        ("blocked by the 100-share net cap", lambda a: f"{a['blocked_net_cap']}"),
        ("orders sent", lambda a: f"{a['orders']}"),
        ("missed: book already moved past the limit", lambda a: f"{a['missed_book_moved']}"),
        ("fills (correct / wrong call)", lambda a: f"{a['fills']} ({a['fills_correct']} / {a['fills_wrong']})"),
        ("fill rate (fills / orders)", lambda a: f"{a['fill_rate']:.0%}"),
        ("correct-call fills executed before the reprice", lambda a: f"{a['correct_fills_before_reprice']}"),
        ("shares / $ deployed", lambda a: f"{a['shares']:,.0f} / ${a['usd_in']:,.0f}"),
        ("**net per share, marked at +30 s mid [95 % CI]**", lambda a: f"**{f2(a['per_share_mark_c'])}c** {ci(a['per_share_mark_ci95_c'])}"),
        ("**net per share, held to the match result [95 % CI]**", lambda a: f"**{f2(a['per_share_hold_c'])}c** {ci(a['per_share_hold_ci95_c'])}"),
        ("**$ P&L, marked / held**", lambda a: f"**{usd(a['pnl_mark_usd'])} / {usd(a['pnl_hold_usd'])}**"),
        ("win rate of fills, marked / held", lambda a: f"{a['win_rate_mark']:.0%} / {a['win_rate_hold']:.0%}"),
        ("median (execution - reprice), s", lambda a: f"{a['median_exec_minus_book_s']:+.2f}"),
    ]
    s = "| | V = 0 s (venue-camera bound) | V = 0.5 s | **V = 1.0 s (headline)** |\n|---|---|---|---|\n"
    for nm, fn in rows:
        s += f"| {nm} | {fn(H[0.0])} | {fn(H[0.5])} | {fn(H[1.0])} |\n"
    return s


def _c(x):
    return f"{x:+.2f}c"


def consistency_bullet(res, aud) -> str:
    ref = res["sweep_reference"]
    t = ("* **Consistency with the latency sweep:** same mechanism and same direction (the edge needs the order to "
         "beat the reprice, and it shrinks with V), but a lower level than the sweep's in-sample curve "
         f"({ref['headline_reading_IS_c']['V0']:+.2f} / {ref['headline_reading_IS_c']['V0.5']:+.2f} / "
         f"{ref['headline_reading_IS_c']['V1']:+.2f}c), and the gap at V = 0 is larger than sampling noise. ")
    if aud is None:
        return t
    d = aud["sweep_diagnostics"]
    v = d["variants"]["D>=3c_and_limit_at_ref"]
    return t + ("The audit explains it (§6): the sweep times the book's reprice on the recorder's receive clock, "
                f"{aud['recv_latency_ms']} ms late, and a third of reprices sit at a whole server second, which "
                f"alone lifts the share of calls before the reprice from {d['V0']['replay_convention_share_before_reprice']:.0%} "
                f"to {d['V0']['sweep_convention']['lat10ms']:.0%} at V = 0 on these same points; and on the sweep's own "
                f"trade set (moves ≥ 3c, limit at the stale ask) the replay is {_c(v['V0']['per_share_mark_c'])} / "
                f"{_c(v['V0.5']['per_share_mark_c'])} / {_c(v['V1']['per_share_mark_c'])} per share, about the "
                "sweep's burned-OOS reading, not its in-sample curve. ")


def sweep_gap_text(aud, H=None) -> str:
    if aud is None:
        return "(Run `scripts/match_replay_check.py` for the decomposition.)\n"
    d = aud["sweep_diagnostics"]
    sw = d["real_book_at_sweep_timing_12ms_receive_clock_beat"]
    v = d["variants"]
    out = []
    out.append(
        f"1. **Clock convention of the reprice (explains the share of calls before the reprice).** The sweep's R is "
        f"`book_vs_T_s` from `m1_points.csv`, i.e. the reprice on the recorder's *receive* clock; the venue repriced "
        f"{aud['recv_latency_ms']} ms earlier. The sweep also uses a 10-140 ms venue network (Europe 10 ms) where the "
        f"replay uses 67 ms (Florida). That would not matter if reprices were spread evenly, but "
        f"{d['reprice_server_ms_of_second_in_[-20,+40)']:.0%} of the matched reprices fall within 40 ms after a whole "
        f"server second (6 % if uniform), right where a V = 0 order lands (stamp − 2 s + 1.087 s). On the same 461 "
        f"points the share of calls before the reprice is {d['V0']['replay_convention_share_before_reprice']:.0%} / "
        f"{d['V0.5']['replay_convention_share_before_reprice']:.0%} / {d['V1']['replay_convention_share_before_reprice']:.0%} "
        f"(V = 0 / 0.5 / 1 s) with the replay's convention and "
        f"{d['V0']['sweep_convention']['lat10ms']:.0%} / {d['V0.5']['sweep_convention']['lat10ms']:.0%} / "
        f"{d['V1']['sweep_convention']['lat10ms']:.0%} with the sweep's (10 ms; 40 ms gives "
        f"{d['V0']['sweep_convention']['lat40ms']:.0%} / {d['V0.5']['sweep_convention']['lat40ms']:.0%} / "
        f"{d['V1']['sweep_convention']['lat40ms']:.0%}), which reproduces the sweep's 44 / 19 / 14 %. The 66 ms is a "
        f"credit the real book does not give: executing at the sweep's earlier instants against the recorded book "
        f"gives {_c(sw['V0']['per_share_mark_c'])} / {_c(sw['V0.5']['per_share_mark_c'])} / "
        f"{_c(sw['V1']['per_share_mark_c'])} per share marked, about the replay's own. This is an optimistic bias in "
        f"the sweep (`src/tier0.py` uses R as is), flagged to its owners; it is outside this replay's files.\n")
    a, b, c = v["limit_at_ref_ask"], v["D>=3c_points"], v["D>=3c_and_limit_at_ref"]
    out.append(
        f"2. **Trade set (explains most of the level).** Same replay, same books, as labelled variants: limit at the "
        f"stale ask instead of +1c: {_c(a['V0']['per_share_mark_c'])} / {_c(a['V0.5']['per_share_mark_c'])} / "
        f"{_c(a['V1']['per_share_mark_c'])}; only points whose matched book move is ≥ 3c (the sweep's live pool): "
        f"{_c(b['V0']['per_share_mark_c'])} / {_c(b['V0.5']['per_share_mark_c'])} / {_c(b['V1']['per_share_mark_c'])}; "
        f"both, i.e. the sweep's trade set: {_c(c['V0']['per_share_mark_c'])} / {_c(c['V0.5']['per_share_mark_c'])} / "
        f"{_c(c['V1']['per_share_mark_c'])} on {c['V0']['fills']} / {c['V0.5']['fills']} / {c['V1']['fills']} fills "
        f"({usd(c['V0']['pnl_mark_usd'])} / {usd(c['V0.5']['pnl_mark_usd'])} / {usd(c['V1']['pnl_mark_usd'])} marked). "
        + (f"Against the headline ({_c(H[0.0]['per_share_mark_c'])} / {_c(H[0.5]['per_share_mark_c'])} / "
           f"{_c(H[1.0]['per_share_mark_c'])}), calling every point instead of the ≥ 3c moves costs "
           f"{b['V0']['per_share_mark_c'] - H[0.0]['per_share_mark_c']:.2f} / "
           f"{b['V0.5']['per_share_mark_c'] - H[0.5]['per_share_mark_c']:.2f} / "
           f"{b['V1']['per_share_mark_c'] - H[1.0]['per_share_mark_c']:.2f}c per share and the +1c limit "
           f"{a['V0']['per_share_mark_c'] - H[0.0]['per_share_mark_c']:.2f} / "
           f"{a['V0.5']['per_share_mark_c'] - H[0.5]['per_share_mark_c']:.2f} / "
           f"{a['V1']['per_share_mark_c'] - H[1.0]['per_share_mark_c']:.2f}c. " if H else "")
        + "The move filter uses the realised move (hindsight), as the sweep's historical jump table does.\n")
    out.append(
        "3. **What is left is the sweep's pricing model.** On its own trade set the replay is near zero at V ≤ 0.5 s and "
        "negative at 1 s, below the sweep's in-sample curve (+1.10 / +0.61 / +0.40c) and close to its burned-OOS reading "
        "(+0.58 [−0.08, +1.21] / −0.02 / −0.38c). The sweep prices fills from a measured edge curve and a 50 % share of "
        "the stale depth; the replay walks the recorded book. The variants are a few dozen fills on 7 matches, so they "
        "locate the gap but do not measure it precisely.\n")
    return "\n".join(out) + "\n"


def batch_caveat(aud) -> str:
    if aud is None:
        return "see §9."
    d = aud["sweep_diagnostics"]
    bb, ab = d["whole_second_batch_variant"]["before_batch"], d["whole_second_batch_variant"]["after_batch"]
    return (f"{d['prints_ms_of_second_first_100ms_share']:.0%} of the {d['prints_n']:,} recorded prints of these 9 "
            f"markets carry a server time in the first 100 ms of a second ({d['prints_ms_of_second_first_50ms_share']:.0%} "
            "in the first 50 ms; 10 % and 5 % if uniform), while book updates are spread evenly. Delayed marketable "
            "orders appear to be matched in whole-second batches, which the venue does not document. If our order "
            "matched at the first whole second at or after arrival + 1 s, the replay would be worse: "
            f"{_c(bb['V0']['per_share_mark_c'])} to {_c(ab['V0']['per_share_mark_c'])} per share at V = 0 and "
            f"{_c(bb['V1']['per_share_mark_c'])} to {_c(ab['V1']['per_share_mark_c'])} at 1 s (our order first or last "
            f"in the batch), and V = 0 and 0.5 s would mostly land in the same batch. The headline keeps the "
            "protocol's continuous 1 s delay; a live test order is the only way to settle this.")


def deviation_text(res) -> str:
    ro = res["model"].get("recorder_outages")
    if not ro:
        return "None in the trading rule, the cells, the seeds or the statistics.\n"
    rows = "\n".join(f"| V = {k[1:]} s | {LITERAL[k][0]} | {f2(LITERAL[k][1])}c | {usd(LITERAL[k][2])} | {usd(LITERAL[k][3])} | "
                     f"{res['headline_by_V'][k]['all']['fills']} | {f2(res['headline_by_V'][k]['all']['per_share_mark_c'])}c | "
                     f"{usd(res['headline_by_V'][k]['all']['pnl_mark_usd'])} | {usd(res['headline_by_V'][k]['all']['pnl_hold_usd'])} |"
                     for k in ("V0", "V0.5", "V1"))
    return ("**D1 (after the audit; data validity, not a trading rule).** The protocol's replayability rule (a "
            "recorded message for the market within 60 s before execution) let orders execute while the recorder was "
            f"disconnected. The recorder's own receive stream has {ro['n']} gaps longer than 1 s ({ro['total_s']:.0f} s "
            "in all: a 2.0-2.6 s resubscribe every 10 minutes and a 47 s outage at 11:12:51-11:13:39 UTC); "
            "the next-longest gap is 0.22 s at the 99.99th percentile. Inside a gap the book is not observed. In the "
            "protocol-literal run, 2 fills per V executed inside the 47 s outage on a book 7-19 s old (Sun v Bucsa "
            "point 76, Jovic v Dart point 174), 4 reference prices were read inside gaps, and 3-4 fills were marked at a "
            "+30 s mid inside a gap. Now a point whose reference or execution instant falls inside a gap is "
            "`no book recorded` (`no_book_reason` in `points.csv`), and a +30 s mark inside a gap is not taken (the fill "
            "is held, not marked). 7 of 500 replayable points drop out. The effect is small and does not change any "
            "sign:\n\n| | literal fills | literal c/share marked | literal $ marked | literal $ held | fills | "
            "c/share marked | $ marked | $ held |\n|---|---|---|---|---|---|---|---|---|\n" + rows + "\n\n"
            "Nothing else in the trading rule, the cells, the seeds or the statistics changed.\n")


def audit_text(aud) -> str:
    if aud is None:
        return ""
    rc = aud["row_checks"]
    pc = aud["pooled_vs_replay_json"]
    hc = aud["hand_check"]
    sb = aud["server_bbo_check"]
    out = ["## 9. Independent audit\n",
           "`scripts/match_replay_check.py` does not import the replay. It re-reads the raw recording with its own "
           "parser, rebuilds both tokens' books with its own code from the text of `PROTOCOL.md` §4, re-runs the three "
           "headline cells, and writes `results/replay/audit.json` and `audit_handcheck.csv`.\n",
           f"* **Rebuilt book vs the server's own top of book:** after {sb['agree']:,} of {sb['checked']:,} price_change "
           f"messages ({sb['share']:.2%}) the rebuilt best bid and ask equal the `best_bid` / `best_ask` the server put "
           "in the message; the rest sit at reconnect snapshots and same-millisecond bursts.\n",
           "* **Row by row:** status, reference ask, ask at execution, shares, VWAP, fee, held and marked P&L are "
           "identical to `points.csv` on all 994 points at V = 0, 0.5 and 1 s; pooled fills and $ match "
           f"`replay.json` exactly (largest difference {max(v['max_abs_diff'] for v in pc.values()):.1g}). Timing arithmetic is identical: "
           "reference instant ≤ call − 67 ms and ≤ the landing frame (no look-ahead), execution = call + 67 ms + "
           "1.000 s.\n",
           "* **Fills:** none above its limit, none below the best ask at execution; the ask at execution equals the "
           f"server's own best ask (last `best_bid_ask` / `price_change` field at or before the instant) on every fill "
           f"and on {min(v['ask_at_exec_equals_server_bbo_share'] for v in rc.values()):.1%}+ of orders. Oldest book "
           f"at an execution instant: {max(v['book_age_at_exec_s']['max'] for v in rc.values()):.2f} s (after D1). "
           "One fill per V executes on a rebuilt book whose token-0 bid equals its ask (Sun v Bucsa point 67, a stale "
           "0.40 bid); the server's best ask confirms the 0.40 fill price.\n",
           f"* **Wrong calls:** {rc['V1']['wrong_calls_in_calls']} of the calls are simulated wrong calls (seed 0), "
           f"traded like any other: {rc['V0']['wrong_call_fills']} / {rc['V0.5']['wrong_call_fills']} / "
           f"{rc['V1']['wrong_call_fills']} fills at V = 0 / 0.5 / 1 s.\n",
           f"* **Hand check of 10 points** (rule: {hc['rule']}): {hc['agree']} of 10 agree "
           "on the reference ask, the ask at execution and the fill, by the rebuilt book and by the server's own "
           "best ask. `audit_handcheck.csv` lists each with the raw ask messages around the execution instant.\n",
           "* **Protocol before P&L:** `PROTOCOL.md` was committed at 17:14:49 EDT (0e083ed) and is unchanged since; "
           "the first parse of the recording is 17:18:59 and the first outputs 17:27:45. The selection rule applied to "
           "`m1_points.csv` gives Sun v Bucsa (125 of 128 matched; next Jovic v Dart, 110). `PROTOCOL.md` cites the "
           "sweep at `research/v2/tier0/LATENCY_SWEEP.md`; the file moved to `research/v2/feed_latency/` in 84c3898 "
           "(the protocol is left as committed).\n",
           "* **Labels:** every output carries the BACKTEST REPLAY label: a `label` column (`points.csv`, "
           "`seed_robustness.csv`, `audit_handcheck.csv`), a `label` key (`replay.json`, `audit.json`), a `#` header "
           "line (the other CSVs), a footer on every figure, and the ribbon, title card and footer of the video.\n",
           "* **Not fixed here (outside this replay's files):** the sweep's receive-clock reprice time (§6, item 1) "
           "and the whole-second batch question (§7) belong to `src/tier0.py` and "
           f"`{SWEEP}`; numbers quoted elsewhere from the protocol-literal run (−0.92c, −$229, −$387, 6 of 121) "
           "are superseded by the D1 table above.\n"]
    return "\n".join(out) + "\n"


def write_md(res, pts, sr, dec, ex, aud=None):
    H = {V: res["headline_by_V"][f"V{V:g}"]["all"] for V in (0.0, 0.5, 1.0)}
    s1 = pts[(pts.slug == res["selected_match"]) & (pts.V == 1.0) & (pts.beat_book == True)  # noqa: E712
             & ~pts.status.str.startswith(("no book", "skipped"))]
    n_beat_blocked = int((s1.status == "blocked (net cap)").sum())
    st = res["selected_story"]
    sel = res["selected_match"]
    m = next(x for x in res["matches"] if x["slug"] == sel)
    S = res["seed_robustness"]["summary"]
    md = []
    md.append("# Match replay: the 1 s video trader on real matches recorded live on 2026-10-03\n")
    md.append(f"> **{res['label']}.**\n>\n> We did not receive, buy or watch any video of these matches. The feed, its "
              "1 s delay, the camera call and its lead are assumed. Real: the official WTA point stamps and winners, the "
              "Polymarket order books and trades recorded live today, the venue's 1 s taker delay, the fee and the match "
              "results. No order was sent. Protocol, committed before any P&L: `PROTOCOL.md`. **One day, 9 matches, a "
              "small sample: this is an illustration and a consistency check against the latency sweep "
              f"(`{SWEEP}`), not new evidence.**\n")
    a1, a0, a5 = H[1.0], H[0.0], H[0.5]
    cb = dec[dec["class"] == "correct, before the reprice"].set_index("V")
    g_lo, g_hi = sorted([float(cb.loc[0.0, "gross_c"]), float(cb.loc[0.5, "gross_c"])])
    md.append("## Bottom line\n")
    md.append(
        f"* **At the headline 1 s feed delay the replayed trader loses money:** {a1['fills']} fills over the 9 matches, "
        f"**{f2(a1['per_share_mark_c'])}c per share** marked at the +30 s mid (match-clustered 95 % CI "
        f"{ci(a1['per_share_mark_ci95_c'])}), {usd(a1['pnl_mark_usd'])} marked and {usd(a1['pnl_hold_usd'])} held to "
        f"the result. Its order executes before the book reprices on only {a1['calls_beat_book']} of "
        f"{a1['calls_with_reprice']} calls ({a1['share_calls_beat_book']:.0%}).\n"
        f"* **It still loses at V = 0.5 s and at V = 0** (a camera at the venue): {f2(a5['per_share_mark_c'])}c and "
        f"{f2(a0['per_share_mark_c'])}c per share marked, {usd(a5['pnl_mark_usd'])} and {usd(a0['pnl_mark_usd'])}. "
        f"Faster helps in the right direction: the share of calls that beat the book goes "
        f"{a0['share_calls_beat_book']:.0%} → {a5['share_calls_beat_book']:.0%} → {a1['share_calls_beat_book']:.0%} "
        f"from V = 0 to 1 s, and correct-call fills before the reprice go {a0['correct_fills_before_reprice']} → "
        f"{a5['correct_fills_before_reprice']} → {a1['correct_fills_before_reprice']}.\n"
        f"* **Why:** the only fills that make money are correct calls that execute before the reprice (gross edge "
        f"{g_lo:.1f}-{g_hi:.1f}c per share against the +30 s mid at V ≤ 0.5 s, about half the live fast tier's 2.24c; "
        f"see §2). They are outnumbered by correct calls that land just after a ≤ 1c reprice (the 1c limit lets them "
        f"through at a roughly fair price, so they pay the fee) and by the simulated wrong calls, which always fill "
        f"because the loser's price is falling. Because every point is called, the 100-share net cap blocks "
        f"{a1['blocked_net_cap']} of {a1['calls']} calls at 1 s, including {n_beat_blocked} of the {len(s1)} that beat "
        f"the book in the selected match.\n"
        f"* **Selected match** ({m['n0']} v {m['n1']}, {m['matched']} matched points; chosen by the pre-committed rule): "
        f"at V = 1.0 s the order beats the book on **{st['V1']['beat_book']} of {st['V1']['calls_with_reprice']}** calls "
        f"and fills on **{st['V1']['fills_beat_book']}** of them; at V = 0.5 s {st['V0.5']['beat_book']} "
        f"({st['V0.5']['fills_beat_book']} filled); at V = 0, {st['V0']['beat_book']} ({st['V0']['fills_beat_book']} filled).\n"
        + consistency_bullet(res, aud) +
        "Every one of the 36 sensitivity cells is negative marked; the best is stamp lag 3.0 s at V = 0 (§5).\n")
    md.append("![selected match](../../results/replay/fig_selected_match.png)\n")
    md.append("`results/replay/fig_selected_match.png`: the recorded mid of the selected match, every official point, "
              "and the replayed V = 1.0 s trader's fills (blue: correct call; orange: simulated wrong call; grey x: "
              "missed because the book had already moved past the limit). Bottom: cumulative marked P&L at V = 0, "
              "0.5 and 1.0 s.\n")
    md.append("## 1. Headline: 9 matches, stamp lag 2.0 s, model lead, Florida 67 ms, seed 0\n")
    md.append(headline_table(res))
    md.append(
        "\nPer-share net = Σ P&L / Σ shares over fills. CI: 10,000 bootstrap resamples of the matches with at least one "
        f"fill ({a0['matches_with_fills']} / {a5['matches_with_fills']} / {a1['matches_with_fills']} matches at "
        "V = 0 / 0.5 / 1.0 s). Win rate counts fills with P&L > 0. Held-to-result P&L is mostly the match result on a "
        "≤ 100-share net position, so it is far noisier than the marked P&L; read the marked figure for the edge.\n")
    md.append("**20 seeds** (lead draws and wrong calls re-drawn; same books and points): mean ± SD over seeds.\n")
    md.append("| | V = 0 s | V = 0.5 s | V = 1.0 s |\n|---|---|---|---|")
    for k, nm, fmt in (("fills", "fills", "{:.1f} ± {:.1f}"), ("fills_wrong", "wrong-call fills", "{:.1f} ± {:.1f}"),
                       ("calls_beat_book", "calls beating the book", "{:.1f} ± {:.1f}"),
                       ("per_share_mark_c", "net c/share, marked", "{:+.2f} ± {:.2f}"),
                       ("per_share_hold_c", "net c/share, held", "{:+.2f} ± {:.2f}"),
                       ("pnl_mark_usd", "$ marked", "{:+.0f} ± {:.0f}"), ("pnl_hold_usd", "$ held", "{:+.0f} ± {:.0f}")):
        md.append(f"| {nm} | " + " | ".join(fmt.format(S[f'V{V:g}'][k]['mean'], S[f'V{V:g}'][k]['sd'])
                                             for V in (0.0, 0.5, 1.0)) + " |")
    md.append(f"\nSeed 0 (the replay shown everywhere) drew {a0['wrong_calls']} wrong calls out of {a0['calls']} "
              f"({a0['wrong_calls'] / a0['calls']:.0%}, against 5 % expected), so it sits on the unlucky side of the seed spread; the sign does not change "
              f"in any of the 20 seeds at any V (marked $ range: "
              + ", ".join(f"V = {V:g}: {S[f'V{V:g}']['pnl_mark_usd']['min']:+.0f} to {S[f'V{V:g}']['pnl_mark_usd']['max']:+.0f}"
                          for V in (0.0, 0.5, 1.0)) + ").\n")
    md.append("## 2. Where the P&L comes from (accounting split of the same fills)\n")
    md.append("Gross = +30 s mid - fill price; net = gross - fee. Classes: whether the call was correct, and whether the "
              "order executed before the book's half-move reprice (`t_book`); \"not before a reprice\" includes the few "
              "fills on points with no matched reprice. This split uses `t_book`, which a trader would not know at the "
              "time; it explains the result and is not a trading rule.\n")
    md.append("| V | fill class | fills | shares | gross c/share | fee c/share | net c/share (marked) | $ marked | $ held |\n"
              "|---|---|---|---|---|---|---|---|---|")
    order = ["correct, before the reprice", "correct, not before a reprice", "wrong call"]
    for V in (0.0, 0.5, 1.0):
        for c in order:
            r = dec[(dec.V == V) & (dec["class"] == c)]
            if not len(r):
                md.append(f"| {V:g} s | {c} | 0 | | | | | | |")
                continue
            r = r.iloc[0]
            md.append(f"| {V:g} s | {c} | {r.fills} | {r.shares:,.0f} | {r.gross_c:+.2f} | {r.fee_c:.2f} | "
                      f"{r.net_mark_c:+.2f} | {usd(r.pnl_mark)} | {usd(r.pnl_hold)} |")
    md.append(f"\nThe correct fills that beat the book earn a gross {g_lo:.1f}-{g_hi:.1f}c per share at V ≤ 0.5 s, about "
              "half of the live fast tier's 2.24c (`research/v2/tier0/RESULTS.md` §1), and keep a few tenths of a cent "
              "after the fee. At V = 1 s the few that remain earn nothing. There are too few of them: most correct "
              "calls either arrive after the reprice or are blocked by the net cap.\n")
    md.append("![P&L by V](../../results/replay/fig_pnl_by_v.png)\n")
    md.append("`results/replay/fig_pnl_by_v.png`: left, net per share with match-clustered 95 % CI at V = 0, 0.5, 1.0 s "
              "(marked and held), next to the latency sweep's headline-reading curve (in sample and burned OOS; a "
              "different trade set). Right, marked $ by fill class.\n")
    md.append("![race](../../results/replay/fig_race.png)\n")
    md.append("`results/replay/fig_race.png`: for every call with a matched reprice, our execution time minus the book's "
              "reprice time. Left of zero, the stale price is still there when our order executes.\n")
    md.append(f"## 3. The selected match, point by point: {m['n0']} v {m['n1']}\n")
    md.append(f"Selection rule (`PROTOCOL.md` §3): most points with a matched book reprice, ties by earliest start. "
              f"`{sel}`: {m['points']} official points, {m['matched']} matched, first stamp {m['first_T']}, "
              f"last {m['last_T']}; winner {m['winner_name']}. Every point is in `results/replay/points.csv` "
              f"(`selected_match = True`) with its bounce, call, execution and reprice times, the reference and "
              f"execution prices, the status and the P&L.\n")
    md.append("| | V = 0 s | V = 0.5 s | V = 1.0 s |\n|---|---|---|---|")
    for k, nm in (("calls", "calls"), ("calls_with_reprice", "calls with a matched reprice"),
                  ("beat_book", "**calls whose order beats the reprice**"), ("blocked_net_cap", "blocked by net cap"),
                  ("missed_book_moved", "missed (book already moved)"), ("fills", "fills"),
                  ("fills_correct", "of which correct calls"), ("fills_wrong", "of which wrong calls"),
                  ("fills_beat_book", "**fills that beat the reprice**"), ("shares", "shares")):
        md.append(f"| {nm} | " + " | ".join((f"{st[f'V{V:g}'][k]:,.0f}" if k == "shares" else str(st[f'V{V:g}'][k]))
                                            for V in (0.0, 0.5, 1.0)) + " |")
    md.append("| $ marked / held | " + " | ".join(f"{usd(st[f'V{V:g}']['pnl_mark_usd'])} / {usd(st[f'V{V:g}']['pnl_hold_usd'])}"
                                                  for V in (0.0, 0.5, 1.0)) + " |")
    md.append("| median execution - reprice, s | " + " | ".join(f"{st[f'V{V:g}']['median_exec_minus_book_s']:+.2f}"
                                                               for V in (0.0, 0.5, 1.0)) + " |")
    g1 = pts[(pts.slug == sel) & (pts.V == 1.0) & (pts.beat_book == True)  # noqa: E712
             & ~pts.status.str.startswith(("no book", "skipped"))]
    md.append(f"\n**The {len(g1)} calls that beat the book at V = 1.0 s:**\n")
    md.append("| point | score after | point winner | called | execution - reprice (s) | ask at bounce → at execution | status |\n|---|---|---|---|---|---|---|")
    for r in g1.itertuples():
        md.append(f"| {r.n} | {r.score_after} | {r.point_winner_name} | {r.called_player}"
                  f"{'' if r.correct_call else ' (wrong call)'} | {r.exec_minus_book_s:+.2f} | "
                  f"{r.ref_ask:.2f} → {('-' if not np.isfinite(r.ask_at_exec) else f'{r.ask_at_exec:.2f}')} | {r.status} |")
    md.append("\nThe large leads (8-18 s) are points where the book's matched reprice comes long after the stamp; the "
              f"latency write-up flags those as probable mismatches (`{SWEEP}` §3). "
              f"Without those, the 1 s trader beats the book on {len(g1[g1.exec_minus_book_s > -5])} points of the "
              f"whole match.\n")
    (na, Da, _), (nb, Db, _) = ex
    md.append("![single points](../../results/replay/fig_point_race.png)\n")
    md.append(f"`results/replay/fig_point_race.png`: two points of the selected match with the assumed bounce, the "
              f"official stamp, the book's reprice and the execution instant at V = 0, 0.5 and 1.0 s, and the result "
              f"of each order. Left, point {na}: the match's largest matched book move among quoted points "
              f"({Da * 100:.1f}c; a rule on the market move). Right, point {nb}: the largest matched move among points "
              f"where the V = 0 order filled before the reprice ({Db * 100:.1f}c; chosen on the replay's own outcome, "
              f"to show what a won race looks like, so it is not representative).\n")
    md.append("## 4. Per match (headline V = 1.0 s, and V = 0 for reference)\n")
    md.append("| match | points | replayable | calls | beat the book | fills (wrong) | c/share marked | $ marked | $ held | V = 0: fills, $ marked |\n|---|---|---|---|---|---|---|---|---|---|")
    bm1 = res["headline_by_V"]["V1"]["by_match"]
    bm0 = res["headline_by_V"]["V0"]["by_match"]
    for mm in res["matches"]:
        s = mm["slug"]
        a, b = bm1[s], bm0[s]
        star = " (selected)" if s == sel else ""
        md.append(f"| {mm['n0']} v {mm['n1']}{star} | {a['official_points']} | {a['replayable_points']} | {a['calls']} | "
                  f"{a['calls_beat_book']} of {a['calls_with_reprice']} | {a['fills']} ({a['fills_wrong']}) | "
                  f"{f2(a['per_share_mark_c'])} | {usd(a['pnl_mark_usd'])} | {usd(a['pnl_hold_usd'])} | "
                  f"{b['fills']}, {usd(b['pnl_mark_usd'])} |")
    md.append("\nRecorder coverage starts at 09:46 UTC, so the three early matches (Rakhimova-Fernandez, Bencic-Zakharova, "
              "Zheng-Kalinskaya) are mostly unreplayable; Rybakina-Charaeva has only 4 points in the frozen 12:45 UTC "
              "snapshot.\n")
    md.append("## 5. Sensitivity: all 36 cells (seed 0, pooled over the 9 matches)\n")
    md.append("| V | stamp lag | lead | network | fills | calls beating the book | correct fills before reprice | c/share marked [95 % CI] | $ marked | c/share held | $ held |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for nm, c in res["cells"].items():
        cc, a = c["cell"], c["all"]
        bold = cc == {"V": 1.0, "lag": 2.0, "lead": "model", "net": "florida"}
        b = "**" if bold else ""
        md.append(f"| {b}{cc['V']:g} s{b} | {cc['lag']:g} s | {cc['lead']} | {cc['net']} | {a['fills']} | "
                  f"{a['calls_beat_book']} | {a['correct_fills_before_reprice']} | {b}{f2(a['per_share_mark_c'])}{b} "
                  f"{ci(a['per_share_mark_ci95_c'])} | {usd(a['pnl_mark_usd'])} | {f2(a['per_share_hold_c'])} | "
                  f"{usd(a['pnl_hold_usd'])} |")
    md.append("\nThe stamp lag matters most, as in the sweep: at 1.0 s the book has usually repriced before the assumed "
              "bounce, so almost no call beats it; at 3.0 s about two thirds of calls beat it at V = 0 and the result is "
              "near zero. The camera lead (0-100 ms) and London co-location (65 ms faster) change little.\n")
    md.append("## 6. Consistency check against the latency sweep\n")
    ref = res["sweep_reference"]
    md.append("| | V = 0 | V = 0.5 s | V = 1.0 s |\n|---|---|---|---|")
    md.append("| sweep, in sample, net c/share (headline reading) | " + " | ".join(
        f"{ref['headline_reading_IS_c'][k]:+.2f}" for k in ("V0", "V0.5", "V1")) + " |")
    md.append("| sweep, burned OOS, net c/share | " + " | ".join(
        f"{ref['headline_reading_OOS_c'][k]:+.2f}" for k in ("V0", "V0.5", "V1")) + " |")
    md.append("| replay, net c/share marked [CI] | " + " | ".join(
        f"{f2(H[V]['per_share_mark_c'])} {ci(H[V]['per_share_mark_ci95_c'])}" for V in (0.0, 0.5, 1.0)) + " |")
    md.append("| sweep, in sample: calls before the reprice | 44 % | 19 % | 14 % |")
    md.append("| replay: calls that beat the reprice | " + " | ".join(
        f"{H[V]['share_calls_beat_book']:.0%}" for V in (0.0, 0.5, 1.0)) + " |")
    md.append("| sweep, in sample: fill rate (filled correct calls / calls; all before the reprice) | 25 % | 11 % | 8 % |")
    md.append("| replay: correct-call fills before the reprice / calls | " + " | ".join(
        f"{H[V]['correct_fills_before_reprice'] / H[V]['calls']:.0%}" for V in (0.0, 0.5, 1.0)) + " |")
    md.append("| replay: all correct-call fills / calls (incl. ≤ 1c after the reprice) | " + " | ".join(
        f"{(H[V]['fills'] - H[V]['fills_wrong']) / H[V]['calls']:.0%}" for V in (0.0, 0.5, 1.0)) + " |")
    md.append("\n**Consistent:** in both, money is made only by correct calls that execute before the reprice; the share "
              "of such calls falls with V; the stamp lag dominates. **Not consistent in level, and not within sampling "
              "noise:** at V = 0 the replay's CI lies below the sweep's in-sample CI (+0.82 to +1.38c). The audit "
              "(`scripts/match_replay_check.py`, `results/replay/audit.json`) splits the gap into three parts.\n")
    md.append(sweep_gap_text(aud, H))
    md.append("## 7. What this does not show\n")
    md.append("* **No video.** No feed was bought, received or watched. V, the CV call, its lead and its 95 % precision "
              "are assumptions from the tier-0 model.\n"
              "* **The bounce time is not observed.** It is the official stamp minus an assumed 1-3 s lag. Every number "
              "moves with that assumption (§5).\n"
              "* **One day, 9 WTA matches, mostly WTA 1000 Beijing**, about 500 replayable points. The CIs are over 9 "
              "matches and are wide; a different day can differ.\n"
              "* **Our orders do not move the book.** The real fast tier is already in the recording; we take what it "
              "left. We do not model being seen by makers.\n"
              "* **Costs not deducted:** a feed licence, colocation, data.\n"
              "* **The venue's matching clock is assumed continuous.** The recorded prints say otherwise: "
              + batch_caveat(aud) + "\n"
              "* **Same data as the sweep's inputs.** The reprice times and books that parameterise the sweep come from "
              "this day, so agreement is a consistency check, not an independent test.\n")
    md.append("## 8. How to describe this in the paper\n")
    md.append("Accurate: *\"We replay the trader on 9 WTA matches recorded live on 2026-10-03. For every official point "
              "we take the umpire's timestamp, assume the ball landed 2 s earlier, and assume a licensed video feed "
              "delivers it 1 s later (0 and 0.5 s as bounds). The simulated order is priced against the real "
              "Polymarket order book recorded at the instant it would have executed, after the venue's 1 s taker "
              "delay. We did not buy or receive match video.\"* Not accurate, and not to be written: that we received "
              "Polymarket or match footage over WebRTC (or any other way), that the replay used live video, or that "
              "the trader made money. A faster licensed feed is the stated limitation: the replay shows what a "
              "faster feed would have to beat (the reprice), not that one exists at a price that pays.\n")
    md.append("## Deviations from the protocol\n")
    md.append(deviation_text(res))
    md.append("Additions after P&L was seen, all descriptive: the accounting split of §2 (uses `t_book`, which is "
              "hindsight), the figures (the example points in `fig_point_race.png` are chosen by stated display rules, "
              "one of them on the replay's outcome), the per-match V = 0 column in §4, and the audit diagnostics of §6 "
              "and §9 (variants, not choices: none of them replaces the headline).\n")
    md.append(audit_text(aud))
    md.append("## Reproduce\n")
    md.append("```bash\n.venv/bin/python scripts/match_replay.py          # ~2-3 min: parses the recording, replays 93 cells, "
              "writes everything\n.venv/bin/python scripts/match_replay_check.py    # ~1 min: independent audit -> "
              "results/replay/audit.json, audit_handcheck.csv\n.venv/bin/python scripts/match_replay.py --figures-only   "
              "# redraw figures + this file (reads audit.json)\n.venv/bin/python scripts/match_replay_extras.py && "
              ".venv/bin/python scripts/match_replay_figs.py && .venv/bin/python scripts/match_replay_video.py\n```\n")
    md.append(f"Recording lines scanned: {res['inputs']['lines_scanned']:,}. Receive latency (local receive - server "
              f"timestamp) median {res['model']['recv_latency_ms_median']} ms (p10-p90 "
              f"{res['model']['recv_latency_ms_p10_p90'][0]:.0f}-{res['model']['recv_latency_ms_p10_p90'][1]:.0f} ms); "
              f"token 1's best ask equals 1 - token 0's best bid at "
              f"{res['model']['mirror_check_tok1_ask_eq_1_minus_tok0_bid']:.2%} of captured instants (the two books "
              f"mirror each other).\n")
    md.append("Outputs in `results/replay/`: `replay.json` (label, model, matches, every cell overall and per match, seed "
              "summary, selected-match story), `points.csv` (every official point of the 9 matches at V = 0, 0.5, "
              "1.0 s, headline settings, seed 0), `seed_robustness.csv`, `selected_match_book.csv` (top of book every "
              "250 ms), `fig_selected_match.png`, `fig_point_race.png`, `fig_race.png`, `fig_pnl_by_v.png`.\n")
    DOC.mkdir(parents=True, exist_ok=True)
    (DOC / "RESULTS.md").write_text("\n".join(md))


def main():
    _style()
    res, pts, sr, tl = load()
    dec = decomposition(pts)
    fig_selected(res, pts, tl)
    ex = fig_point(res, pts, tl)
    fig_race(res, pts)
    fig_pnl(res, dec)
    write_md(res, pts, sr, dec, ex, load_audit())
    print("wrote research/replay/RESULTS.md and results/replay/fig_*.png")


if __name__ == "__main__":
    main()
