"""Figures for the H3 tracking analysis."""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from common import FPS, WORK

C_MISS = "#d1495b"
C_BOUNCE = "#2e86ab"
C_GREY = "#6c757d"


def plot_precision_vs_lead(cur_te, cur_te_snap, cur_tr, tau, path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharex=True)
    ax = axes[0]
    ax.fill_between(cur_te.lead_ms, cur_te.prec_lo95, cur_te.prec_hi95, color=C_MISS, alpha=0.15,
                    lw=0, label="test 95% Wilson CI")
    ax.plot(cur_te.lead_ms, cur_te.precision, color=C_MISS, lw=2, label="test (online rule)")
    ax.plot(cur_te_snap.lead_ms, cur_te_snap.precision, color=C_MISS, lw=1.2, ls="--",
            label="test (snapshot rule)")
    ax.plot(cur_tr.lead_ms, cur_tr.precision, color=C_GREY, lw=1.5, label="train, leave-one-game-out")
    ax.axhline(0.95, color="k", lw=0.8, ls=":")
    ax.axvline(50, color="k", lw=0.8, ls=":")
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("lead before contact / table end (ms)")
    ax.set_ylabel("precision of MISS calls")
    ax.set_title("Precision of the MISS call vs lead")
    ax.legend(fontsize=8, loc="lower left", frameon=False)
    ax = axes[1]
    ax.plot(cur_te.lead_ms, cur_te.recall, color=C_MISS, lw=2, label="test (online rule)")
    ax.plot(cur_te_snap.lead_ms, cur_te_snap.recall, color=C_MISS, lw=1.2, ls="--", label="test (snapshot)")
    ax.plot(cur_tr.lead_ms, cur_tr.recall, color=C_GREY, lw=1.5, label="train, leave-one-game-out")
    ax.axvline(50, color="k", lw=0.8, ls=":")
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("lead before contact / table end (ms)")
    ax.set_ylabel("recall of MISS flights")
    ax.set_title(f"Recall at the frozen threshold (tau = {tau:.2f})")
    ax.legend(fontsize=8, loc="upper right", frameon=False)
    for a in axes:
        a.spines[["top", "right"]].set_visible(False)
        a.grid(alpha=0.25, lw=0.5)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _arc(F, t_dec, horizon=0.35):
    """Fitted prefix + extrapolated arc (image px) at decision frame t_dec."""
    from early_call import LAG, NFIT, robust_quadfit
    m = F.fr <= t_dec - LAG
    fr, u, w = F.fr[m][-NFIT:], F.u[m][-NFIT:], F.w[m][-NFIT:]
    tau = (fr - (t_dec - LAG)) / FPS
    cu, _ = robust_quadfit(tau, u)
    cw, _ = robust_quadfit(tau, w)
    tt = np.linspace(tau[0], horizon, 80)
    return np.polyval(cu, tt), np.polyval(cw, tt)


def _to_px(u, w, g, d):
    L = g["x_right"] - g["x_left"]
    x = g["x_left"] + u * L if d > 0 else g["x_right"] - u * L
    af, bf = g["far_line"]
    an, bn = g["near_line"]
    ymid = 0.5 * ((af + an) * x + bf + bn)
    return x, ymid - w * L


def plot_examples(fl, objs, model, name, geo, path, lead_ms=50):
    """A few test flights over a frame of their video, with the arc extrapolated at T_ref - 50 ms."""
    from early_call import FEATS_ALL, FEATS_PHYS, k_of
    feats = FEATS_PHYS if name == "physics" else FEATS_ALL
    k = k_of(lead_ms)
    vids = fl.groupby("video").label.apply(lambda s: (s == "MISS").sum()).sort_values(ascending=False)
    chosen = []
    for v in vids.index[:2]:
        sub = fl[fl.video == v]
        miss = sub[sub.label == "MISS"]
        bnc = sub[sub.label == "BOUNCE"]
        pick = list(miss.index[:3]) + list(bnc.index[:: max(1, len(bnc) // 3)][:3])
        chosen.append((v, pick))
    fig, axes = plt.subplots(len(chosen), 1, figsize=(10, 5.8 * len(chosen)))
    axes = np.atleast_1d(axes)
    for ax, (v, pick) in zip(axes, chosen):
        g = geo[v]
        img_p = os.path.join(WORK, "frames", f"{v}.jpg")
        if os.path.exists(img_p):
            img = plt.imread(img_p)
            ax.imshow(img, extent=(0, 1920, 1080, 0))
        ax.set_xlim(0, 1920)
        ax.set_ylim(1080, 0)
        cx = np.r_[g["corners"][:, 0], g["corners"][0, 0]]
        cy = np.r_[g["corners"][:, 1], g["corners"][0, 1]]
        ax.plot(cx, cy, color="w", lw=1, alpha=0.8)
        for fid in pick:
            F = objs[fid]
            r = fl.loc[fid]
            col = C_MISS if r.label == "MISS" else C_BOUNCE
            x, y = _to_px(F.u, F.w, g, r.dir)
            t_dec = r.t_ref - k
            seen = F.fr <= t_dec - 2
            ax.plot(x[seen], y[seen], "o", ms=2.5, color=col)
            ax.plot(x[~seen], y[~seen], "o", ms=2.5, mfc="none", color=col, alpha=0.8)
            if seen.sum() >= 5:
                au, aw = _arc(F, t_dec)
                ax_, ay_ = _to_px(au, aw, g, r.dir)
                ax.plot(ax_, ay_, "-", lw=1.2, color=col, alpha=0.9)
                f = F.features(t_dec)
                if f is not None:
                    p = model.predict_proba(np.array([[f[c] for c in feats]]))[0, 1]
                    ax.annotate(f"{r.label.lower()}{'/' + r.miss_type if r.miss_type == r.miss_type and r.miss_type else ''}"
                                f" p={p:.2f}", (x[seen][-1], y[seen][-1]), color="w", fontsize=7,
                                xytext=(4, -8), textcoords="offset points")
        ax.set_title(f"{v}: filled = track seen at T_ref - {lead_ms} ms (minus 2-frame detector lag), "
                     f"open = rest; line = arc extrapolated at decision time\n"
                     f"red = MISS flights, blue = TABLE BOUNCE flights; p = model P(miss)", fontsize=9)
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
