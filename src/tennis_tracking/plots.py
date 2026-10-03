"""Figures for the tennis tracking module (static, light mode, same palette as src/report.py)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from geometry import COURT_KPS, HALF_LEN, SERVICE_Y, SINGLES_HALF_W, DOUBLES_HALF_W  # noqa: E402

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"
plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
    "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False, "lines.linewidth": 2,
})
HAWKEYE = {25: 0.72, 50: 1.13, 100: 2.37, 150: 3.95, 200: 5.76, 300: 10.66}
NAMES = {"ground": "Last point on ground", "phys3d": "3D ballistic fit", "learned": "Learned correction"}
COL = {"ground": AQUA, "phys3d": ORANGE, "learned": BLUE}


def _lead_series(T, k, split, stat):
    from run_eval import at_leads
    x = at_leads(T)
    x = x[x.split == split]
    if stat == "median":
        s = x.groupby("lead")[f"{k}_err_cm"].median()
    else:
        d = 100 * (x[f"{k}_d"] - x.d_true)
        s = d.groupby(x.lead).apply(lambda v: 1.4826 * np.median(np.abs(v - v.median())))
    return s.index.values, s.values


def _p95_signed(T, k, split):
    from run_eval import at_leads
    x = at_leads(T)
    x = x[x.split == split]
    d = 100 * (x[f"{k}_d"] - x.d_true)
    s = d.groupby(x.lead).apply(lambda v: np.nanpercentile(v, 95))
    return s.index.values, s.values


def lead_vs_error(tables, summary, path):
    fig, axs = plt.subplots(1, 2, figsize=(10.0, 4.0))
    hk = np.array(sorted(HAWKEYE.items()))
    # left: callable margin, same metric for both systems (one-sided 95% bound on the
    # signed out-distance error; Hawk-Eye MC = 1.645 SD of its Gaussian error)
    ax = axs[0]
    T = tables["labels"]
    for k in ("ground", "learned"):
        L, m = _p95_signed(T, k, "test")
        ax.plot(L, m, color=COL[k], marker="o", ms=5, label=f"Broadcast: {NAMES[k].lower()} (labels)")
    L, m = _p95_signed(tables["tracknet"], "learned", "test")
    ax.plot(L, m, color=COL["learned"], ls="--", marker="s", ms=5, mfc=SURF,
            label="Broadcast: learned (TrackNet detector)")
    ax.plot(hk[:, 0], 1.645 * hk[:, 1], color=INK, marker="^", ms=5, label="Hawk-Eye-class MC (340 fps)")
    ax.set_yscale("log")
    ax.set_xlabel("Lead before the bounce, ms")
    ax.set_ylabel("Ball must land this far out, cm (log)")
    ax.set_title("Callable margin at 95% (test games 8-10)")
    ax.set_xlim(-10, 310)
    ax.legend(loc="lower right", fontsize=7.5)
    # right: landing-point error of each predictor
    ax = axs[1]
    for k in ("ground", "phys3d", "learned"):
        L, m = _lead_series(T, k, "test", "median")
        ax.plot(L, m, color=COL[k], marker="o", ms=5, label=f"{NAMES[k]} (labels)")
    L, m = _lead_series(tables["tracknet"], "learned", "test", "median")
    ax.plot(L, m, color=COL["learned"], ls="--", marker="s", ms=5, mfc=SURF, label="Learned correction (TrackNet)")
    ax.plot(hk[:, 0], hk[:, 1], color=INK, marker="^", ms=5, label="Hawk-Eye-class MC, error SD")
    ax.set_yscale("log")
    ax.set_xlabel("Lead before the bounce, ms")
    ax.set_ylabel("Landing-point error, cm (log)")
    n = int(T[T.split == "test"].fid.nunique())
    ax.set_title(f"Median landing-point error ({n} test bounces)")
    ax.set_xlim(-10, 310)
    ax.legend(loc="lower right", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _court_lines():
    W, H, D, S = SINGLES_HALF_W, HALF_LEN, DOUBLES_HALF_W, SERVICE_Y
    segs = [((-D, -H), (D, -H)), ((-D, H), (D, H)), ((-D, -H), (-D, H)), ((D, -H), (D, H)),
            ((-W, -H), (-W, H)), ((W, -H), (W, H)), ((-W, -S), (W, -S)), ((-W, S), (W, S)),
            ((0, -S), (0, S)), ((-D - 0.9, 0), (D + 0.9, 0))]
    return segs


def example(P, T, sources, path):
    """One test flight that lands out (largest number of predictions), labelled track."""
    from run_eval import at_leads
    fl = P["flights"]
    x = at_leads(T)
    te = x[(x.split == "test") & x.is_out & ~x.serve_flag.astype(bool)]
    if not len(te):
        te = x[x.split == "test"]
    full = te.groupby("fid").size()
    te = te[te.fid.isin(full[full == full.max()].index)]
    fid = int(te.sort_values("d_true").fid.iloc[-1])      # fixed rule: the rally ball that lands furthest out
    r = fl.loc[fid]
    cam = P["cams"][(r.game, r["clip"])]["cam"]
    rows = x[x.fid == fid].sort_values("lead")
    fig, axs = plt.subplots(1, 2, figsize=(10.0, 4.6), gridspec_kw={"width_ratios": [1.7, 1]})
    ax = axs[0]
    for (a, b) in _court_lines():
        p = cam.project(np.array([[a[0], a[1], 0.0], [b[0], b[1], 0.0]]))
        ax.plot(p[:, 0], p[:, 1], color=MUTED, lw=1)
    k0, k1 = max(r.hit - 3, 0), min(int(r.bounce) + 6, len(sources["labels"][(r.game, r["clip"])]))
    lab = sources["labels"][(r.game, r["clip"])][k0:k1]
    det = sources["tracknet"][(r.game, r["clip"])][k0:k1]
    ax.plot(lab[:, 0], lab[:, 1], "o", color=INK, ms=4, label="Labelled ball (per frame)")
    ax.plot(det[:, 0], det[:, 1], "x", color=ORANGE, ms=5, label="TrackNet detection")
    ax.plot(r.u_b, r.v_b, "*", color=BLUE, ms=14, mec=SURF, label="True bounce (sub-frame)")
    ax.set_xlim(0, 1280)
    ax.set_ylim(720, 0)
    ax.set_aspect("equal")
    ax.grid(False)
    ax.set_title(f"Test game {r.game} {r['clip']}: image plane, court lines from the camera")
    ax.legend(loc="lower left", fontsize=7.5)
    ax = axs[1]
    for (a, b) in _court_lines():
        ax.plot([a[0], b[0]], [a[1], b[1]], color=MUTED, lw=1)
    for k, mk in (("ground", "D"), ("phys3d", "s"), ("learned", "o")):
        ax.plot(rows[f"{k}_x"], rows[f"{k}_y"], "-", color=COL[k], lw=1, alpha=0.6)
        ax.plot(rows[f"{k}_x"], rows[f"{k}_y"], mk, color=COL[k], ms=5, mec=SURF, label=NAMES[k])
        for _, q in rows.iloc[[0, -1]].iterrows():
            ax.annotate(f"{int(q.lead)} ms", (q[f"{k}_x"], q[f"{k}_y"]), xytext=(4, -3), textcoords="offset points",
                        fontsize=6.5, color=INK2)
    ax.plot(r.x_b, r.y_b, "*", color=INK, ms=14, mec=SURF)
    ax.plot([], [], "*", color=INK, ms=10, label=f"True landing (out by {100 * r.d_true:.0f} cm)")
    ys = np.r_[[rows[f"{k}_y"].values for k in ("ground", "phys3d", "learned")]].ravel() * np.sign(r.y_b)
    ys = ys[np.isfinite(ys)]
    top = float(np.clip(max(ys.max() if len(ys) else 0, abs(r.y_b)) + 1.5, 13.5, 32))
    ax.set_aspect("equal")
    ax.set_xlim(-7.5, 7.5)
    ax.set_ylim((-1, top) if r.y_b > 0 else (-top, 1))
    ax.set_title("Top view (m), receiver's half")
    ax.legend(loc="lower center" if r.y_b > 0 else "upper center", fontsize=7, framealpha=0.9, frameon=True)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
