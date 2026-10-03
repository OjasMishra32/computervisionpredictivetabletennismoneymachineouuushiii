"""Tables and figures for the spin-aware tennis tracker from results/spin/tennis/raw/*.parquet.

    .venv/bin/python scripts/spin_tennis_report.py [--tag s7]

Writes results/spin/tennis/
  calls_v2.csv         hawkeye_tennis_calls.csv columns (threshold tuned on half the shots for
                       95 % precision, scored on the other half) + method, cond
  metrics_v2.csv       per cond x method x lead: bias/SD/RMSE of the signed out distance,
                       95 % callable margin, calibration, P(out) >= 0.95 calls, spin readout
  spin_by_kind.csv     spin readout and error by spin type (spin_mix world)
  fig_error_vs_lead.png, fig_robustness.png, fig_spin_readout.png, fig_pout_calls.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import hawkeye as H  # noqa: E402

OUT = ROOT / "results/spin/tennis"
HK_LEADS = (0, 25, 50, 100, 150, 200, 300, 400)
BINS = (0.0, 0.02, 0.05, 0.10, 0.20, 0.40, 1.0)
MAIN = ["baseline", "bls", "bls_bma", "bls_cal", "ukf", "ukf_mm", "ukf_cal"]
COND_ORDER = ["nominal", "exact_t", "cd15", "decay", "wind", "noise2x", "all", "spin_mix", "aero"]
COND_LABEL = {"nominal": "nominal (hawkeye world)", "exact_t": "exact frame clock", "cd15": "Cd ±15 % per shot",
              "decay": "spin decay 2 %/100 ms", "wind": "2 m/s crosswind", "noise2x": "noise ×2",
              "all": "all four mismatches", "spin_mix": "slice/sidespin/gyro mix",
              "aero": "lift −10 %, spin-dependent drag"}
# reference categorical palette (dataviz skill), baseline in neutral ink
STYLE = {"baseline": ("#52514e", "-", "hawkeye baseline"), "bls": ("#2a78d6", "-", "batch fit (BLS)"),
         "bls_bma": ("#1baf7a", "-", "BLS model average"), "ukf": ("#eb6834", "--", "UKF"),
         "ukf_mm": ("#eda100", "--", "UKF multi-model"), "bls_cal": ("#4a3aa7", "-", "BLS session-calibrated"),
         "ukf_cal": ("#e87ba4", "--", "UKF session-calibrated")}


def spin_perp(df: pd.DataFrame, pre: str) -> np.ndarray:
    """Spin component perpendicular to the true velocity (the part that makes Magnus force)."""
    w = df[[f"{pre}_x", f"{pre}_y", f"{pre}_z"]].to_numpy()
    v = df[["v_true_x", "v_true_y", "v_true_z"]].to_numpy()
    vh = v / np.linalg.norm(v, axis=1, keepdims=True)
    return w - np.sum(w * vh, 1, keepdims=True) * vh


def spin_stats(g: pd.DataFrame) -> dict:
    if g["w_hat_x"].isna().all():
        return {}
    wh, wt = spin_perp(g, "w_hat"), spin_perp(g, "w_true")
    k = 60 / (2 * np.pi)
    rh, rt = np.linalg.norm(wh, axis=1) * k, np.linalg.norm(wt, axis=1) * k
    cosang = np.sum(wh * wt, 1) / np.maximum(rh * rt / k**2, 1e-12)
    ang = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
    full = np.linalg.norm(g[["w_hat_x", "w_hat_y", "w_hat_z"]].to_numpy() - g[["w_true_x", "w_true_y", "w_true_z"]].to_numpy(), axis=1) * k
    e = rh - rt
    return {"rpm_err_med_abs": float(np.median(np.abs(e))), "rpm_err_bias": float(np.mean(e)),
            "rpm_err_sd": float(np.std(e)), "rpm_err_rel_med_pct": float(np.median(np.abs(e) / rt) * 100),
            "axis_err_med_deg": float(np.median(ang)), "axis_err_p95_deg": float(np.quantile(ang, 0.95)),
            "spinvec_err_med_rpm": float(np.median(full))}


def metrics(g: pd.DataFrame) -> dict:
    e = (g.d_hat - g.d).to_numpy()
    d = g.d.to_numpy()
    r = {"n": len(g), "bias_cm": e.mean() * 100, "sd_cm": e.std() * 100, "rmse_cm": np.sqrt(np.mean(e**2)) * 100,
         "margin95_cm": np.quantile(np.abs(e), 0.95) * 100, "margin99_cm": np.quantile(np.abs(e), 0.99) * 100,
         "land2d_rmse_cm": np.sqrt(np.mean(g.ex**2 + g.ey**2)) * 100,
         "sign_acc_within_5cm": float((np.sign(g.d_hat[np.abs(d) < 0.05]) == np.sign(d[np.abs(d) < 0.05])).mean())}
    if g.sd_d.notna().all():
        z = e / g.sd_d.to_numpy()
        r.update(pred_sd_med_cm=g.sd_d.median() * 100, z_sd=z.std(), cover95=float((np.abs(z) < 1.96).mean()))
    if g.p_out.notna().all():
        po = g.p_out.to_numpy()
        out = d > 0
        r["brier"] = float(np.mean((po - out) ** 2))
        for thr in (0.95, 0.99):
            c = po >= thr
            t = f"pout{int(thr * 100)}"
            r[f"{t}_precision"] = float(out[c].mean()) if c.any() else np.nan
            r[f"{t}_recall"] = float(c[out].mean())
            r[f"{t}_false_out_rate"] = float(c[~out].mean())
            if thr == 0.95:
                for lo, hi in zip(BINS[:-1], BINS[1:]):
                    grp = (d > lo) & (d <= hi)
                    r[f"{t}_recall_out_{int(lo * 100)}_{int(hi * 100)}cm"] = float(c[grp].mean()) if grp.any() else np.nan
    r.update(spin_stats(g))
    if "c_hat" in g and g.c_hat.notna().all():
        r["cd_err_med_abs_pct"] = float(np.median(np.abs(g.c_hat - g.c_true)) * 100)
    if "lam_hat" in g and g.lam_hat.notna().all():
        r["lam_hat_med"] = float(g.lam_hat.median())
    for m in ("w_M0", "w_M1", "w_M2"):
        if m in g and g[m].notna().any():
            r[m + "_mean"] = float(g[m].mean())
    return r


def calls_table(df: pd.DataFrame) -> pd.DataFrame:
    """hawkeye.calls_at_precision with hawkeye's lead order (so the baseline reproduces the
    published table), then the extra leads in a second call."""
    res = []
    for (cond, method), g in df.groupby(["cond", "method"], sort=False):
        leads = sorted(g.lead_ms.unique())
        for group in ([L for L in HK_LEADS if L in leads], [L for L in leads if L not in HK_LEADS]):
            if not group:
                continue
            rows = [{"lead_ms": L, "d": g[g.lead_ms == L].sort_values("shot").d.to_numpy(),
                     "d_hat": g[g.lead_ms == L].sort_values("shot").d_hat.to_numpy()} for L in group]
            t = pd.DataFrame(H.calls_at_precision(rows))
            t["method"], t["cond"] = method, cond
            res.append(t)
    out = pd.concat(res, ignore_index=True)
    return out.sort_values(["cond", "method", "lead_ms"], key=lambda s: s.map(_order) if s.name != "lead_ms" else s)


def _order(x):
    if x in COND_ORDER:
        return COND_ORDER.index(x)
    order = MAIN + ["bls_decay", "bls_wind", "ukf_decay", "ukf_wind"]
    return order.index(x) if x in order else 99


# ------------------------------------------------------------------ figures

def _style(ax):
    ax.grid(True, which="major", color="#e4e3df", lw=0.6)
    ax.grid(True, which="minor", color="#f0efec", lw=0.4)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#8a8984")
    ax.tick_params(colors="#52514e", labelsize=8)


def fig_error_vs_lead(M: pd.DataFrame, path: Path):
    """Nominal world. bls_cal / ukf_cal are left out: with no environment to learn they coincide
    with bls / ukf (see metrics_v2.csv)."""
    import matplotlib.pyplot as plt
    m = M[M.cond == "nominal"]
    meths = ["baseline", "bls", "bls_bma", "ukf", "ukf_mm"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=False)
    for ax, col, title in zip(axes, ["sd_cm", "margin95_cm"],
                              ["Landing error SD (signed distance to line)", "95 % callable margin (|error| q95)"]):
        for meth in meths:
            g = m[m.method == meth].sort_values("lead_ms")
            if g.empty:
                continue
            c, ls, lab = STYLE[meth]
            ax.plot(g.lead_ms, g[col], ls, color=c, lw=2, marker="o", ms=4, label=lab)
            if meth in ("baseline", "bls"):   # selective direct labels: the two ends that matter
                for L in (100, 200, 300):
                    v = g[g.lead_ms == L][col]
                    if len(v):
                        ax.annotate(f"{v.iloc[0]:.1f}", (L, v.iloc[0]), xytext=(0, 7 if meth == "baseline" else -11),
                                    textcoords="offset points", fontsize=7, color="#52514e", ha="center")
        ax.set_yscale("log")
        ax.set_xlabel("lead before the bounce (ms)", fontsize=9, color="#0b0b0b")
        ax.set_ylabel("cm", fontsize=9, color="#0b0b0b")
        ax.set_title(title, fontsize=10, color="#0b0b0b", loc="left")
        _style(ax)
    axes[0].legend(fontsize=8, frameon=False, loc="lower right")
    fig.suptitle("Spin-aware tracking vs the hawkeye predictor, same 4,948 simulated near-line shots",
                 fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="#fcfcfb")
    plt.close(fig)


def fig_robustness(M: pd.DataFrame, path: Path, col="rmse_cm"):
    import matplotlib.pyplot as plt
    conds = [c for c in COND_ORDER if c in set(M.cond)]
    nc = 3
    nr = int(np.ceil(len(conds) / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(11, 3.2 * nr), sharex=True, sharey=True)
    axes = np.atleast_2d(axes)
    for ax, cond in zip(axes.flat, conds):
        m = M[M.cond == cond]
        for meth in MAIN:
            g = m[m.method == meth].sort_values("lead_ms")
            if g.empty:
                continue
            c, ls, lab = STYLE[meth]
            ax.plot(g.lead_ms, g[col], ls, color=c, lw=1.8, label=lab)
        ax.set_yscale("log")
        ax.set_title(COND_LABEL.get(cond, cond), fontsize=9, loc="left", color="#0b0b0b")
        _style(ax)
    for ax in axes.flat[len(conds):]:
        ax.axis("off")
    for ax in axes[-1]:
        ax.set_xlabel("lead (ms)", fontsize=8)
    for ax in axes[:, 0]:
        ax.set_ylabel("landing RMSE (cm)", fontsize=8)
    axes.flat[0].legend(fontsize=7, frameon=False)
    fig.suptitle("Robustness: landing RMSE (bias included) vs lead under model mismatch", fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="#fcfcfb")
    plt.close(fig)


def fig_spin(df: pd.DataFrame, path: Path, lead=200):
    import matplotlib.pyplot as plt
    k = 60 / (2 * np.pi)
    conds = [c for c in ("nominal", "spin_mix") if c in set(df.cond)]
    meths = ["baseline", "bls", "ukf_mm"]
    fig, axes = plt.subplots(len(conds), len(meths) + 1, figsize=(14, 3.5 * len(conds)))
    axes = np.atleast_2d(axes)
    for r, cond in enumerate(conds):
        for j, meth in enumerate(meths):
            g = df[(df.cond == cond) & (df.method == meth) & (df.lead_ms == lead)]
            ax = axes[r, j]
            if g.empty:
                ax.axis("off")
                continue
            rh = np.linalg.norm(spin_perp(g, "w_hat"), axis=1) * k
            rt = np.linalg.norm(spin_perp(g, "w_true"), axis=1) * k
            ax.scatter(rt, rh, s=3, alpha=0.35, color=STYLE[meth][0], edgecolors="none")
            lim = [0, min(7000, max(4000, np.quantile(rt, 0.999) * 1.05, np.quantile(rh, 0.99) * 1.05))]
            ax.plot(lim, lim, color="#8a8984", lw=0.8)
            ax.set_xlim(lim)
            ax.set_ylim(lim)
            st = spin_stats(g)
            ax.set_title(f"{STYLE[meth][2]} · {COND_LABEL[cond]}\nmedian |err| {st['rpm_err_med_abs']:.0f} rpm, "
                         f"axis {st['axis_err_med_deg']:.1f}°", fontsize=8, loc="left")
            ax.set_xlabel("true spin (rpm, Magnus-active part)", fontsize=8)
            ax.set_ylabel("estimated (rpm)", fontsize=8)
            _style(ax)
        ax = axes[r, -1]
        for meth in MAIN:
            g = df[(df.cond == cond) & (df.method == meth) & (df.lead_ms == lead)]
            if g.empty:
                continue
            wh, wt = spin_perp(g, "w_hat"), spin_perp(g, "w_true")
            ang = np.degrees(np.arccos(np.clip(np.sum(wh * wt, 1) / np.maximum(
                np.linalg.norm(wh, axis=1) * np.linalg.norm(wt, axis=1), 1e-12), -1, 1)))
            xs = np.sort(ang)
            c, ls, lab = STYLE[meth]
            ax.plot(xs, np.arange(1, len(xs) + 1) / len(xs), ls, color=c, lw=1.8, label=lab)
        ax.set_xscale("log")
        ax.set_xlabel("spin-axis error (deg)", fontsize=8)
        ax.set_ylabel("fraction of shots", fontsize=8)
        ax.set_title(f"axis error CDF, lead {lead} ms", fontsize=8, loc="left")
        ax.legend(fontsize=7, frameon=False)
        _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="#fcfcfb")
    plt.close(fig)


def fig_pout(df: pd.DataFrame, path: Path, leads=(100, 200, 300)):
    """Recall of OUT balls by distance out, nominal world, under two decision rules:
    top, hawkeye's rule (call OUT if d_hat > -5 cm, the threshold calls_at_precision picks at every
    lead, about 97 % precision for every method); bottom, the confidence rule P(out) >= 0.95."""
    import matplotlib.pyplot as plt
    meths = ["baseline", "bls", "bls_bma", "ukf", "ukf_mm"]
    fig, axes = plt.subplots(2, len(leads), figsize=(12, 6.6), sharey=True, sharex=True)
    centers = np.array([1, 3.5, 7.5, 15, 30, 70])
    for r, rule in enumerate(("threshold", "pout")):
        for ax, L in zip(axes[r], leads):
            for meth in meths:
                g = df[(df.cond == "nominal") & (df.method == meth) & (df.lead_ms == L)]
                if g.empty or (rule == "pout" and g.p_out.isna().all()):
                    continue
                d = g.d.to_numpy()
                called = g.d_hat.to_numpy() > -0.05 if rule == "threshold" else g.p_out.to_numpy() >= 0.95
                prec = (d[called] > 0).mean()
                rec = [called[(d > lo) & (d <= hi)].mean() for lo, hi in zip(BINS[:-1], BINS[1:])]
                c, ls, lab = STYLE[meth]
                ax.plot(centers, rec, ls, color=c, lw=1.8, marker="o", ms=4, label=f"{lab} (precision {prec:.3f})")
            ax.set_xscale("log")
            ax.set_xticks(centers)
            ax.set_xticklabels(["0-2", "2-5", "5-10", "10-20", "20-40", "40-100"], fontsize=7)
            ax.set_title(("d̂ > −5 cm" if rule == "threshold" else "P(out) ≥ 0.95") + f" · lead {L} ms",
                         fontsize=9, loc="left")
            ax.legend(fontsize=6, frameon=False, loc="lower right")
            _style(ax)
        axes[r, 0].set_ylabel("recall of OUT balls", fontsize=8)
    for ax in axes[-1]:
        ax.set_xlabel("distance out (cm)", fontsize=8)
    fig.suptitle("OUT calls by distance out. Top: hawkeye's tuned threshold rule. Bottom: call only when P(out) ≥ 0.95",
                 fontsize=10, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="#fcfcfb")
    plt.close(fig)


def main(tag: str):
    files = sorted((OUT / "raw").glob(f"*_{tag}.parquet"))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    print(f"{len(files)} worlds, {len(df)} rows: {sorted(df.cond.unique())}")
    calls = calls_table(df)
    cols = list(pd.read_csv(ROOT / "results/hawkeye_tennis_calls.csv").columns) + ["method", "cond"]
    calls[cols].to_csv(OUT / "calls_v2.csv", index=False)
    M = pd.DataFrame([{"cond": c, "method": m, "lead_ms": L, **metrics(g)}
                      for (c, m, L), g in df.groupby(["cond", "method", "lead_ms"])])
    M = M.sort_values(["cond", "method", "lead_ms"], key=lambda s: s.map(_order) if s.name != "lead_ms" else s)
    M.to_csv(OUT / "metrics_v2.csv", index=False)
    sm = df[df.cond == "spin_mix"]
    if len(sm):
        K = pd.DataFrame([{"method": m, "lead_ms": L, "kind": k, "n": len(g),
                           "rmse_cm": np.sqrt(np.mean((g.d_hat - g.d) ** 2)) * 100, **spin_stats(g)}
                          for (m, L, k), g in sm[sm.lead_ms.isin([100, 200, 300])].groupby(["method", "lead_ms", "kind"])])
        K.to_csv(OUT / "spin_by_kind.csv", index=False)
    key = {}
    for meth in M.method.unique():
        m = M[(M.cond == "nominal") & (M.method == meth)].set_index("lead_ms")
        if m.empty:
            continue
        key[meth] = {"sd_cm": m.sd_cm.round(2).to_dict(), "rmse_cm": m.rmse_cm.round(2).to_dict(),
                     "margin95_cm": m.margin95_cm.round(2).to_dict()}
        if "pout95_recall" in m and m.pout95_recall.notna().any():
            key[meth]["pout95_precision"] = m.pout95_precision.round(4).to_dict()
            key[meth]["pout95_recall"] = m.pout95_recall.round(4).to_dict()
            key[meth]["cover95"] = m.cover95.round(3).to_dict()
        if "rpm_err_med_abs" in m:
            key[meth]["rpm_err_med_abs"] = m.rpm_err_med_abs.round(1).to_dict()
            key[meth]["axis_err_med_deg"] = m.axis_err_med_deg.round(2).to_dict()
    rob = M[M.lead_ms.isin([100, 200, 300])].pivot_table(index=["cond", "lead_ms"], columns="method", values="rmse_cm")
    key["robustness_rmse_cm"] = {f"{c}@{L}": r.round(2).dropna().to_dict() for (c, L), r in rob.iterrows()}
    (OUT / "key_numbers.json").write_text(json.dumps(key, indent=1, default=float))
    fig_error_vs_lead(M, OUT / "fig_error_vs_lead.png")
    fig_robustness(M, OUT / "fig_robustness.png")
    fig_spin(df, OUT / "fig_spin_readout.png")
    fig_pout(df, OUT / "fig_pout_calls.png")
    print("wrote calls_v2.csv, metrics_v2.csv, figures")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="s7")
    main(ap.parse_args().tag)
