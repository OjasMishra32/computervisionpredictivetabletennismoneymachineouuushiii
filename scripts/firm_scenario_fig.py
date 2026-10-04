"""Paper figure: "if we were a quant firm with a licensed 0.5 s feed" (fresh-holdout scenario), on the CONDITIONAL
jump-set benchmark (trades = the historical >= 4c jumps, selected on outcomes; not a tradable book).

    COUNTERFACTUAL WITH ASSUMED DATA. Real: Polymarket prices, fills (public trade tapes), match results, taker fees
    and the venue's 1 s order delay. Simulated: the camera/CV calls, made at an ASSUMED licensed-feed delay V.
    No feed or video was bought, received or watched; no order was placed. The figure carries this label.

    python scripts/firm_scenario_fig.py   -> results/scenario/fig_firm_05s.{pdf,png} + caption.txt

Strategy: S2, the paper's Table-2 CV trader (the latency-sweep model behind Table 2 and the licence figures), primary
coverage (10 matches a day). Inputs, all already on disk; nothing is simulated here:
  results/fresh_holdout/seed_daily_paths.csv   every seed's daily P&L (scripts/fresh_holdout_seed_paths.py; its
                                               seed means reproduce daily.csv exactly)
  results/fresh_holdout/results.json           burned-OOS $/day and Sharpe (history comparators), fresh $/day table,
                                               showcase match facts and 20-seed match P&L
  results/fresh_holdout/showcase_price_1s.csv  the showcase match's 1 s price path (public tape)
  results/fresh_holdout/showcase_ledger.csv    the pre-registered ledger seed's simulated calls (seed 4000)
  results/fresh_holdout/showcase_trades_all_seeds.csv   every filled trade on that match, all 20 seeds

(a) Cumulative P&L at V = 0.5 s, both stamp-lag readings (pre-registered 2.0 s, post hoc 3.142 s): mean over 20 seeds
    and the 10-90 % range of the seeds' cumulative paths, IS -> burned OOS on one scale, then the fresh holdout on
    its own scale (2 days, from $0); thin dotted lines are the post hoc reading at V = 1 s and 3 s.
(b) The pre-registered showcase match (highest in-play volume in the fresh window, not chosen on P&L): 1 s price,
    simulated calls, the fills of all 20 seeds, and the 20-seed mean P&L marked to the 1 s price (resolution at the
    end; the end values are results.json's 20-seed means).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs/paper"))
import figstyle as fs  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402  (figstyle selected the Agg backend)
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator  # noqa: E402

FH = ROOT / "results/fresh_holdout"
OUT = ROOT / "results/scenario"
NAME = "fig_firm_05s"
STRAT = "S2"
LABEL_FIG = ("Conditional benchmark. Real Polymarket prices, fills, fees and venue delay; calls simulated at an assumed "
             "feed delay (no feed purchased), only on the historical >=4c jumps.")
LABEL_LONG = ("COUNTERFACTUAL WITH ASSUMED DATA: real Polymarket prices, fills, match results, taker fees and venue "
              "delays; SIMULATED camera/CV calls at an assumed licensed-feed delay V (no feed purchased, no video "
              "watched, no orders placed). Trades are the historical >= 4c jump set, selected on outcomes, not ex ante: "
              "a conditional benchmark (src/tier0.TRADE_SET_LABEL['jumps']), not a tradable book; the causal "
              "every-point book is scripts/cv_causal_points.py.")
READ_LAB = {"pre": "pre-registered stamp lag 2.0 s", "cal": "post hoc stamp lag 3.142 s"}

W, H = fs.FIG_W, 2.45


# ===================================================================================================== data
def load() -> dict:
    R = json.loads((FH / "results.json").read_text())
    P = pd.read_csv(FH / "seed_daily_paths.csv")
    P = P[(P.strategy == STRAT) & (P.coverage == "cov10")]
    scols = sorted(c for c in P.columns if c.startswith("pnl_usd_seed_k"))
    hist = R["history_comparators (IS seeds 0-19, burned OOS 1000-1019; from history.json)"]
    tab = {(t["strategy"], t["reading"], t["V_s"]): t for t in R["table"]
           if t["coverage"] == "cov10" and t["subset"] == "all_days"}
    return {"R": R, "P": P, "scols": scols, "hist": hist, "tab": tab}


def paths(D: dict, rd: str, V: float, period: str) -> tuple[list[str], np.ndarray]:
    """(dates, seeds x days daily P&L) for one cell and period, in date order."""
    p = D["P"]
    q = p[(p.reading == rd) & np.isclose(p.V_s, V) & (p.period == period)].sort_values("date")
    return q.date.tolist(), q[D["scols"]].to_numpy(float).T


def hist_cum(D: dict, rd: str, V: float) -> dict:
    """IS -> burned OOS cumulative P&L per seed on a day-index axis (x = days elapsed; each period's days in order;
    the IS / OOS boundary day 2026-08-25 appears once in each period, as in the stored runs)."""
    d_is, a_is = paths(D, rd, V, "IS")
    d_oos, a_oos = paths(D, rd, V, "burned_OOS")
    n_is = len(d_is)
    A = np.hstack([np.zeros((a_is.shape[0], 1)), a_is, a_oos])   # seeds x (1 + days)
    C = np.cumsum(A, axis=1)
    x = np.arange(C.shape[1], dtype=float)
    return {"x": x, "C": C, "n_is": n_is, "dates_is": d_is, "dates_oos": d_oos}


def fresh_cum(D: dict, rd: str, V: float) -> dict:
    d, a = paths(D, rd, V, "fresh")
    C = np.cumsum(np.hstack([np.zeros((a.shape[0], 1)), a]), axis=1)
    return {"x": np.arange(C.shape[1], dtype=float), "C": C, "dates": d}


def epoch_s(col: pd.Series) -> pd.Series:
    """UTC timestamp strings -> integer epoch seconds (independent of pandas' datetime resolution)."""
    return (pd.to_datetime(col, utc=True) - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1s")


def showcase(D: dict) -> dict:
    R = D["R"]
    sh = R["showcase"]
    px = pd.read_csv(FH / "showcase_price_1s.csv")
    led = pd.read_csv(FH / "showcase_ledger.csv")
    tr = pd.read_csv(FH / "showcase_trades_all_seeds.csv")
    out0 = px.outcome0.iloc[0]
    t0 = pd.Timestamp(sh["start_utc"])
    t_end = pd.Timestamp(sh["end_utc"])
    ts = px.timestamp.to_numpy(int)
    p0 = px.vwap_outcome0.to_numpy(float)
    # per-second grid from the first print to the end of the match; price forward-filled
    grid = np.arange(ts[0], int(t_end.timestamp()) + 1)
    pg = pd.Series(p0, index=ts).reindex(grid).ffill().to_numpy()
    res0 = float(sh["res0"])
    mtm = {}
    fills = {}
    for rd, rname in READ_LAB.items():
        f = tr[(tr.strategy == STRAT) & tr.reading.str.startswith(rname[:8]) & np.isclose(tr.V_s, 0.5)].copy()
        f["t"] = epoch_s(f.jump_onset_utc)
        tok0 = (f.token_bought == out0).to_numpy()
        f["y0"] = np.where(tok0, f.fill_price, 1.0 - f.fill_price)      # fill price in Ruzic (outcome 0) terms
        val = np.zeros(len(grid))
        for t, k0, q, sh_, fee in zip(f.t, tok0, f.fill_price, f.shares, f.fee_per_share):
            v = pg if k0 else 1.0 - pg
            on = grid >= t
            val[on] += sh_ * (v[on] - q - fee)
        n_seeds = 20
        mt = val / n_seeds
        # resolution: every position pays out at the result
        fin = sum(s_ * ((res0 if k0 else 1.0 - res0) - q - fee) for k0, q, s_, fee in
                  zip(tok0, f.fill_price, f.shares, f.fee_per_share)) / n_seeds
        assert abs(fin - f.pnl_usd.sum() / n_seeds) < 1e-9
        want = R["showcase"]["pnl_20_seed_mean_usd"][f"{STRAT}|{rd}|V0.5"]["mean_usd"]
        assert abs(fs.r(fin, 2) - want) < 1e-9, (rd, fin, want)
        mtm[rd] = (np.append(grid, grid[-1] + 1), np.append(mt, fin))
        fills[rd] = f
    calls = led[(led.strategy == STRAT) & led.reading.str.startswith(READ_LAB["cal"][:8])]
    call_t = epoch_s(calls.jump_onset_utc).to_numpy()
    return {"sh": sh, "grid": grid, "pg": pg, "ts": ts, "p0": p0, "mtm": mtm, "fills": fills, "call_t": call_t,
            "t0": t0, "t_end": t_end, "out0": out0, "n_calls": int(len(calls)),
            "n_fills": {rd: int(len(f)) for rd, f in fills.items()},
            "seeds_with_fills": {rd: int(f.seed.nunique()) for rd, f in fills.items()}}


# ===================================================================================================== figure
def k_fmt(v, _pos=None) -> str:
    if abs(v) < 1e-9:
        return "0"
    s = f"{v / 1e3:g}k"
    return s.replace("-", fs.MINUS)


def plain_fmt(v, _pos=None) -> str:
    if abs(v) < 1e-9:
        return "0"
    return f"{v:g}".replace("-", fs.MINUS)


def panel_a(fig, D: dict, L: dict) -> dict:
    ax = fs.axes_in(fig, *L["a_main"])
    axf = fs.axes_in(fig, *L["a_fresh"])
    CELLS = (("pre", 0.5), ("cal", 0.5), ("cal", 1.0), ("cal", 3.0), ("pre", 1.0), ("pre", 3.0))
    H = {(rd, V): hist_cum(D, rd, V) for rd, V in CELLS}
    Fr = {(rd, V): fresh_cum(D, rd, V) for rd, V in CELLS}
    n_is = H[("pre", 0.5)]["n_is"]
    x = H[("pre", 0.5)]["x"]
    n_tot = len(x) - 1
    col = {"pre": fs.INK, "cal": fs.ORANGE}

    # ---- main: IS -> burned OOS
    ax.set_xlim(0, n_tot + 1.5)
    wx = np.array(L["a_whisk"])
    lo_all = min([h["C"].mean(0).min() for h in H.values()]
                 + [np.percentile(H[(rd, 0.5)]["C"][:, wx], 10, axis=0).min() for rd in ("pre", "cal")])
    hi_all = max([h["C"].mean(0).max() for h in H.values()]
                 + [np.percentile(H[(rd, 0.5)]["C"][:, wx], 90, axis=0).max() for rd in ("pre", "cal")])
    ax.set_ylim(min(-1500.0, lo_all - 0.04 * (hi_all - lo_all)), hi_all + 0.04 * (hi_all - lo_all))
    ax.axvspan(n_is, n_tot + 1.5, color=fs.SHADE, lw=0, zorder=0)
    ax.axvline(n_is, color=fs.GREY, lw=0.6, zorder=1.6)
    fs.hgrid(ax)
    fs.zero_line(ax)
    for rd in ("cal", "pre"):
        h = H[(rd, 0.5)]
        m = h["C"].mean(0)
        lo, hi = np.percentile(h["C"], 10, axis=0), np.percentile(h["C"], 90, axis=0)
        # the two readings' seed ranges overlap: thin whiskers at a few days, never two translucent fills
        wx = np.array(L["a_whisk"])
        fs.whiskers(ax, wx + L["a_whisk_off"][rd], m[wx], lo[wx], hi[wx], col[rd], lw=0.9, zorder=3)
        ax.plot(x[: n_is + 1], m[: n_is + 1], color=col[rd], lw=fs.LW, ls=fs.IS_LS, zorder=4)
        ax.plot(x[n_is:], m[n_is:], color=col[rd], lw=fs.LW, ls=fs.OOS_LS, zorder=4)
    dot = {1.0: (fs.ORANGE, fs.ORANGE), 3.0: (fs.ORANGE_LIGHT, fs.ORANGE_LIGHT_TEXT)}
    for V, (c, _) in dot.items():
        ax.plot(x, H[("cal", V)]["C"].mean(0), color=c, lw=0.9, ls=fs.DOT_LS, zorder=3)
    # the pre-registered reading at 1 s and 3 s (thin dotted black; unlabelled at the line ends, named in the caption):
    # every cell whose Sharpe the paper prints gets an equity curve
    for V in (1.0, 3.0):
        ax.plot(x, H[("pre", V)]["C"].mean(0), color=fs.INK, lw=0.8, ls=fs.DOT_LS, zorder=2.9)
    # month ticks on the day-index axis
    d_is, d_oos = H[("pre", 0.5)]["dates_is"], H[("pre", 0.5)]["dates_oos"]
    ticks, labs = [], []
    for mo, lab in (("2026-06-01", "Jun"), ("2026-07-01", "Jul"), ("2026-08-01", "Aug"), ("2026-09-01", "Sep"),
                    ("2026-10-01", "Oct")):
        if mo in d_is:
            ticks.append(d_is.index(mo))
        elif mo in d_oos:
            ticks.append(n_is + d_oos.index(mo))
        else:
            continue
        labs.append(lab)
    ax.xaxis.set_major_locator(FixedLocator(ticks))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.set_xticklabels(labs)
    ax.yaxis.set_major_locator(FixedLocator([v for v in (0, 5000, 10000, 15000, 20000)
                                             if ax.get_ylim()[0] <= v <= ax.get_ylim()[1]]))
    ax.yaxis.set_major_formatter(FuncFormatter(k_fmt))
    ax.set_ylabel("Cumulative P&L ($)")
    # region labels above the frame
    for xv, lab in ((0, "In-sample"), (n_is, "Burned OOS")):
        ax.annotate(lab, xy=(xv, 1.0), xycoords=("data", "axes fraction"), xytext=(2.0, 2.0),
                    textcoords="offset points", ha="left", va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED,
                    annotation_clip=False)
    # inline identity labels on the IS segments
    for rd, xi, dy, txt in L["a_inline"]:
        m = H[(rd, 0.5)]["C"].mean(0)
        ax.annotate(txt, xy=(xi, m[int(xi)]), xytext=(0, dy), textcoords="offset points", ha="center",
                    va="bottom" if dy > 0 else "top", fontsize=fs.FS, color=col[rd] if rd == "pre" else fs.ORANGE,
                    path_effects=fs.halo(2.6, "white"), zorder=8)
    # line-end labels: burned-OOS $/day and Sharpe (results.json history comparators)
    hc = D["hist"]["burned_OOS"][STRAT]
    items = []
    for rd in ("cal", "pre"):
        c = hc[rd]["0.5"]
        items.append({"x": n_tot, "y": H[(rd, 0.5)]["C"].mean(0)[-1], "color": col[rd],
                      "text": f"{fs.usd(c['pnl_per_day_usd'], 0, sign=True)}/day\nSharpe {fs.f(c['sharpe_ann'], 1)}"})
    for V, (_, tc) in dot.items():
        items.append({"x": n_tot, "y": H[("cal", V)]["C"].mean(0)[-1], "color": tc, "text": f"{V:g}{fs.THIN}s"})
    fs.direct_label(ax, items, dx_pt=4.0, bounds=L["a_lab_bounds"], pad_pt=0.5)

    # ---- fresh holdout: own scale, from $0
    axf.set_facecolor(fs.SHADE)
    axf.set_xlim(-0.12, 2.12)
    fs.hgrid(axf)
    fs.zero_line(axf)
    off = {"cal": 0.07, "pre": -0.07}
    for V, (c, _) in dot.items():
        axf.plot(Fr[("cal", V)]["x"], Fr[("cal", V)]["C"].mean(0), color=c, lw=0.9, ls=fs.DOT_LS, zorder=3)
    for V in (1.0, 3.0):
        axf.plot(Fr[("pre", V)]["x"], Fr[("pre", V)]["C"].mean(0), color=fs.INK, lw=0.8, ls=fs.DOT_LS, zorder=2.9)
    for rd in ("cal", "pre"):
        fr = Fr[(rd, 0.5)]
        m = fr["C"].mean(0)
        lo, hi = np.percentile(fr["C"], 10, axis=0), np.percentile(fr["C"], 90, axis=0)
        fs.whiskers(axf, fr["x"][1:] + off[rd], m[1:], lo[1:], hi[1:], col[rd], lw=0.9, zorder=3)
        axf.plot(fr["x"], m, color=col[rd], lw=fs.LW, ls=fs.OOS_LS, zorder=4, marker="o", ms=fs.MS,
                 markevery=[1, 2])
    lo_f = min(np.percentile(Fr[k]["C"], 10, axis=0).min() for k in Fr)
    hi_f = max(np.percentile(Fr[k]["C"], 90, axis=0).max() for k in Fr)
    pad = 0.08 * (hi_f - lo_f)
    axf.set_ylim(lo_f - pad, hi_f + pad)
    step = 100.0
    yt = np.arange(np.ceil((lo_f - pad) / step) * step, hi_f + pad + 1e-9, step)
    axf.yaxis.set_major_locator(FixedLocator(list(yt)))
    axf.yaxis.set_major_formatter(FuncFormatter(plain_fmt))
    axf.xaxis.set_major_locator(FixedLocator([1.0]))
    fd = [pd.Timestamp(d) for d in Fr[("pre", 0.5)]["dates"]]
    axf.set_xticklabels([f"{fd[0].day}{fs.NDASH}{fd[-1].day} {fd[-1].strftime('%b')}" if len(fd) > 1
                         else f"{fd[0].day} {fd[0].strftime('%b')}"])
    axf.tick_params(axis="x", length=0)
    for sp in ("left", "bottom"):
        axf.spines[sp].set_color(fs.AXIS)
    axf.annotate(f"Fresh holdout, {len(Fr[('pre', 0.5)]['dates'])} days", xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0.0, 2.0),
                 textcoords="offset points", ha="left", va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED,
                 annotation_clip=False)
    t = D["tab"]
    fitems = [{"x": 2.0, "y": Fr[(rd, 0.5)]["C"].mean(0)[-1], "color": col[rd],
               "text": f"{fs.usd(t[(STRAT, rd, 0.5)]['pnl_per_day_usd'], 0, sign=True)}/day"} for rd in ("cal", "pre")]
    fs.direct_label(axf, fitems, dx_pt=5.0, pad_pt=0.5)
    return {"H": H, "Fr": Fr, "ax": ax, "axf": axf}


def panel_b(fig, D: dict, L: dict) -> dict:
    S = showcase(D)
    axp = fs.axes_in(fig, *L["b_price"])
    axm = fs.axes_in(fig, *L["b_pnl"])
    t0 = S["t0"].timestamp()
    tm = lambda t: (np.asarray(t, float) - t0) / 60.0  # minutes since the scheduled start  # noqa: E731
    xmax = tm(S["t_end"].timestamp() + 1)
    for a in (axp, axm):
        a.set_xlim(0, xmax)
        fs.hgrid(a)
    # price path (market) and simulated calls
    axp.plot(tm(S["grid"]), 100 * S["pg"], color=fs.GREY, lw=0.9, zorder=2)
    axp.set_ylim(0, 112)
    axp.yaxis.set_major_locator(FixedLocator([0, 50, 100]))
    axp.yaxis.set_major_formatter(FuncFormatter(plain_fmt))
    for tc in tm(S["call_t"]):
        axp.plot([tc, tc], [103, 111], color=fs.INK, lw=0.6, zorder=3, solid_capstyle="butt")
    col = {"pre": fs.INK, "cal": fs.ORANGE}
    for rd in ("cal", "pre"):
        f = S["fills"][rd]
        axp.plot(tm(f.t), 100 * f.y0, ls="none", marker="o", ms=2.6 if rd == "cal" else 2.4,
                 mfc=col[rd] if rd == "cal" else "none", mec=col[rd], mew=0.6, alpha=0.75, zorder=4)
    # 20-seed mean P&L marked to the 1 s price; resolution at the end
    fs.zero_line(axm)
    ends = {}
    for rd in ("pre", "cal"):
        g, v = S["mtm"][rd]
        axm.plot(tm(g), v, color=col[rd], lw=1.2, ls=(0, (3.0, 1.4)), zorder=4)
        ends[rd] = v[-1]
    lo = min(v.min() for _, v in S["mtm"].values())
    hi = max(v.max() for _, v in S["mtm"].values())
    rng = hi - lo
    h_in = L["b_pnl"][3]
    room = 0.19                                               # inches for an end label above / below the lines
    u = rng / (h_in - 2 * room)                               # data units per inch
    axm.set_ylim(lo - room * u, hi + room * u)
    y_lo, y_hi = axm.get_ylim()
    step = 20.0 * max(1.0, np.ceil((y_hi - y_lo) / 60.0))   # zero and the positive steps: few ticks on a short axis
    yt = np.arange(0.0, y_hi + 1e-9, step)
    axm.yaxis.set_major_locator(FixedLocator(list(yt)))
    axm.yaxis.set_major_formatter(FuncFormatter(plain_fmt))
    axm.set_ylabel("P&L ($)", labelpad=2.0)
    axp.set_ylabel(f"Ruzic ({fs.CENT})", labelpad=2.0)
    hi_rd = max(ends, key=ends.get)
    for rd, v in ends.items():                               # 20-seed mean at resolution (results.json)
        up = rd == hi_rd
        y_lab = hi if up else lo                              # clear of both paths: above the top / below the bottom
        axm.annotate(fs.usd(v, 1, sign=True), xy=(xmax, y_lab), xytext=(-1.0, 2.0 if up else -2.0),
                     textcoords="offset points", ha="right", va="bottom" if up else "top", fontsize=fs.FS_SMALL,
                     color=col[rd], bbox=fs.knockout(0.6) if up else None, zorder=8)
    # what the marks are (the colours are panel a's readings)
    axp.annotate("simulated calls", xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0.0, 2.0),
                 textcoords="offset points", ha="left", va="bottom", fontsize=fs.FS_SMALL, color=fs.MUTED,
                 annotation_clip=False)
    axp.text(0.02, 0.04, "fills", transform=axp.transAxes, ha="left", va="bottom", fontsize=fs.FS_SMALL,
             color=fs.MUTED, zorder=8)
    xt = [x_ for x_ in (45, 105) if x_ <= xmax]           # 16:00 and 17:00 UTC
    for a in (axp, axm):
        a.xaxis.set_major_locator(FixedLocator(xt))
    axm.set_xticklabels([(S["t0"] + pd.Timedelta(minutes=x_)).strftime("%H:%M") for x_ in xt])
    axp.tick_params(axis="x", labelbottom=False)
    return S


def build() -> tuple[list[str], dict, dict, dict]:
    fs.apply()
    D = load()
    fig = plt.figure(figsize=(W, H))
    y0, y1 = 0.66, 2.01                       # plot band (inches from the bottom)
    L = {
        "a_main": (0.58, y0, 1.78, y1 - y0),
        "a_fresh": (3.58, y0, 0.46, y1 - y0),
        "a_whisk": [20, 103, 143],
        "a_whisk_off": {"cal": 1.3, "pre": -1.3},
        "a_lab_bounds": (0.02, 0.98),
        "a_inline": [("cal", 48, 6, "post hoc"), ("pre", 66, 3, "pre-registered")],
        "b_price": (5.25, 1.37, 1.16, y1 - 1.37),
        "b_pnl": (5.25, y0, 1.16, 1.25 - y0),
    }
    A = panel_a(fig, D, L)
    S = panel_b(fig, D, L)
    title_y = H - 0.20
    fs.panel(A["ax"], "a", f"Assumed 0.5{fs.THIN}s feed: the P&L shrinks out of sample", x_in=0.06, y_in=title_y)
    sh = S["sh"]
    day = pd.Timestamp(sh["start_utc"]).strftime("%-d %b")
    names = [n.split()[-1] for n in sh["title"].split(": ", 1)[1].split(" vs ")]
    fs.panel(A["ax"], "b", f"{names[0]} v {names[1]}, {day}", x_in=4.47, y_in=title_y)
    fig.text(0.06 / W, 0.22 / H, "Counterfactual. " + LABEL_FIG.split("; ")[0] + ";", ha="left", va="baseline",
             fontsize=fs.FS_SMALL, style="italic", color=fs.MUTED)
    fig.text(0.06 / W, 0.05 / H, LABEL_FIG.split("; ")[1], ha="left", va="baseline", fontsize=fs.FS_SMALL,
             style="italic", color=fs.MUTED)
    meta = {"Creator": "scripts/firm_scenario_fig.py", "Subject": LABEL_LONG}
    out = fs.save_fig(fig, NAME, OUT, meta=meta)
    return out, D, A, S


def numbers(D: dict, A: dict, S: dict) -> dict:
    """Every number the figure and caption print, with its source (results/scenario/fig_firm_05s_numbers.json)."""
    R, t, hc = D["R"], D["tab"], D["hist"]
    sh = S["sh"]
    num = {"label": LABEL_LONG, "strategy": f"{STRAT}: {R['strategies'][STRAT]}", "coverage": "cov10 (10 matches a day)",
           "readings": READ_LAB, "sources": ["results/fresh_holdout/results.json",
                                             "results/fresh_holdout/seed_daily_paths.csv",
                                             "results/fresh_holdout/showcase_price_1s.csv",
                                             "results/fresh_holdout/showcase_ledger.csv",
                                             "results/fresh_holdout/showcase_trades_all_seeds.csv"],
           "cum_pnl_end_usd_20_seed_mean": {}, "burned_oos": {}, "fresh": {}, "showcase": {}}
    for (rd, V), h in A["H"].items():
        m = h["C"].mean(0)
        num["cum_pnl_end_usd_20_seed_mean"][f"{rd}|V{V:g}"] = {"IS_end": float(m[h["n_is"]]), "burned_OOS_end": float(m[-1]),
                                                               "fresh_end": float(A["Fr"][(rd, V)]["C"].mean(0)[-1])}
    for rd in READ_LAB:
        c = hc["burned_OOS"][STRAT][rd]["0.5"]
        num["burned_oos"][rd] = {k: c[k] for k in ("pnl_per_day_usd", "sharpe_ann", "pnl_per_day_ci95_usd_lo",
                                                    "pnl_per_day_ci95_usd_hi", "n_matches")}
        for V in (0.5, 1.0, 3.0):
            tv = t[(STRAT, rd, V)]
            num["fresh"][f"{rd}|V{V:g}"] = {"pnl_per_day_usd": tv["pnl_per_day_usd"],
                                            "pnl_per_day_ci95_usd": tv["pnl_per_day_ci95_usd"],
                                            "n_matches_traded_seed_mean": tv["n_matches"],
                                            "sharpe": tv["sharpe_display"], "anecdotal": tv["anecdotal"]}
        num["fresh"][f"S1|{rd}|V0.5"] = {"pnl_per_day_usd": t[("S1", rd, 0.5)]["pnl_per_day_usd"]}
    num["fresh"]["covered_matches"] = R["counts"]["covered_primary"]
    num["fresh"]["days"] = R["days"]
    num["fresh"]["window"] = R["window"]
    num["showcase"] = {"title": sh["title"], "league": sh["league"], "series": sh["series"],
                       "start_utc": sh["start_utc"], "winner": sh["winner"],
                       "inplay_usd": sh["inplay_usd"], "rule": sh["rule"], "simulated_calls_ledger_seed": S["n_calls"],
                       "ledger_seed": sh["ledger_seed"], "ledger_seed_filled": sh["ledger_seed_filled_trades"],
                       "fills_all_20_seeds": S["n_fills"], "seeds_with_fills": S["seeds_with_fills"],
                       "pnl_20_seed_mean_usd": {rd: sh["pnl_20_seed_mean_usd"][f"{STRAT}|{rd}|V0.5"] for rd in READ_LAB},
                       "pnl_path": "20-seed mean, marked to the 1 s VWAP price (forward-filled), resolution payout at the end"}
    return num


def caption(N: dict) -> str:
    f, b, sc = N["fresh"], N["burned_oos"], N["showcase"]
    day = pd.Timestamp(sc["start_utc"])
    a_, b_ = sc["title"].split(": ", 1)[1].split(" vs ")
    ci = lambda c: f"[{fs.usd(c[0], 0, sign=True)}, {fs.usd(c[1], 0, sign=True)}]"  # noqa: E731
    nm = sorted(round(f[f"{rd}|V0.5"]["n_matches_traded_seed_mean"]) for rd in READ_LAB)
    s1 = (f"Counterfactual with assumed data: real Polymarket prices, fills, taker fees and the venue{fs.RSQUO}s 1{fs.THIN}s "
          f"order delay, with the camera calls simulated at an assumed licensed-feed delay (no feed purchased, no "
          f"order placed); (a) cumulative P&L of the conditional jump-set benchmark (the paper{fs.RSQUO}s Table 2 CV trader, "
          f"trading only the historical jumps of at least 4{fs.CENT}) on 10 matches a day at a "
          f"0.5{fs.THIN}s feed (mean of 20 seeds, whiskers 10{fs.NDASH}90{fs.THIN}% of seeds) under the pre-registered "
          f"2.0{fs.THIN}s stamp lag (black) and the post hoc 3.14{fs.THIN}s lag (orange), dotted lines the same two "
          f"readings at 1{fs.THIN}s and 3{fs.THIN}s (only the post hoc ones are labelled), end labels the burned-OOS $/day and annualised Sharpe "
          f"({fs.usd(b['cal']['pnl_per_day_usd'], 0, sign=True)} and {fs.f(b['cal']['sharpe_ann'], 1)} post hoc, "
          f"{fs.usd(b['pre']['pnl_per_day_usd'], 0, sign=True)} and {fs.f(b['pre']['sharpe_ann'], 1)} pre-registered).")
    w0 = pd.Timestamp(f["window"]["start_exclusive_utc"])
    s2 = (f"On the fresh holdout, pre-registered before its data were fetched and drawn on its own scale "
          f"({f['covered_matches']} covered matches starting after {w0.day} {w0.strftime('%b %H:%M')} UTC, "
          f"{len(f['days'])} UTC days), the trader returned {fs.usd(f['cal|V0.5']['pnl_per_day_usd'], 1, sign=True)}/day post hoc and "
          f"{fs.usd(f['pre|V0.5']['pnl_per_day_usd'], 1, sign=True)}/day pre-registered, with match-bootstrap 95{fs.THIN}% "
          f"CIs of {ci(f['cal|V0.5']['pnl_per_day_ci95_usd'])} and {ci(f['pre|V0.5']['pnl_per_day_ci95_usd'])} on "
          f"{nm[0]}{fs.NDASH}{nm[1]} traded matches, so the result is anecdotal, a {len(f['days'])}-day Sharpe is not "
          f"meaningful, and neither sign is evidence for or against an edge (the frozen tier-0 v3 rule: "
          f"{fs.usd(f['S1|cal|V0.5']['pnl_per_day_usd'], 1, sign=True)} and "
          f"{fs.usd(f['S1|pre|V0.5']['pnl_per_day_usd'], 1, sign=True)}/day).")
    pm = sc["pnl_20_seed_mean_usd"]
    s3 = (f"(b) The pre-registered showcase match, the covered match with the highest in-play volume, not chosen on P&L ({a_} v {b_}, "
          f"{sc['series'].upper()} {sc['league']}, "
          f"{day.day} {day.strftime('%b %Y')}, {fs.usd(sc['inplay_usd'], 0, k=True)} traded in play, {sc['winner'].split()[-1]} won): "
          f"Ruzic{fs.RSQUO}s 1{fs.THIN}s price, the {sc['simulated_calls_ledger_seed']} simulated calls of the ledger seed (ticks), "
          f"the fills of all 20 seeds (dots; the ledger seed filled none) and the 20-seed mean P&L marked to the "
          f"1{fs.THIN}s price (UTC), {fs.usd(pm['cal']['mean_usd'], 1, sign=True)} post hoc and "
          f"{fs.usd(pm['pre']['mean_usd'], 1, sign=True)} pre-registered at resolution; in both panels the trades are "
          f"the historical price jumps of at least 4{fs.CENT}, which are selected on outcomes, so neither panel is a "
          f"tradable book.")
    return "\n".join([s1, s2, s3]) + "\n"


if __name__ == "__main__":
    out, D, A, S = build()
    N = numbers(D, A, S)
    (OUT / f"{NAME}_numbers.json").write_text(json.dumps(N, indent=1, default=str))
    cap = caption(N)
    (OUT / "caption.txt").write_text(cap)
    print(out + [str((OUT / "caption.txt").relative_to(ROOT)), str((OUT / f"{NAME}_numbers.json").relative_to(ROOT))])
    print(cap)
