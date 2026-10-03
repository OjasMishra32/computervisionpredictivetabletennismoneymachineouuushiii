"""Numbers for research/spin/TT_RESULTS.md from the single spin-model test run (no model is refitted,
no threshold is changed; this only re-tabulates results/spin/tt/test/* written by tt_early_call --final).

  .venv/bin/python research/spin/tt_report.py
-> results/spin/tt/test/report_numbers.json, test_spin_readout.csv, fig_spin_readout_test.png
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
T = os.path.join(ROOT, "results", "spin", "tt", "test")
LEADS = ["0ms", "25ms", "50ms", "100ms", "150ms", "200ms"]
FPS = 120.0
K50 = 6


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(float(c - h), 4), round(float(c + h), 4)]


def table(lt):
    out = {}
    for L in LEADS:
        r = lt[L]
        tp, fp, fn = r["tp"], r["fp"], r["fn"]
        out[L] = dict(tp=tp, fp=fp, fn=fn, calls=tp + fp,
                      precision=None if tp + fp == 0 else round(tp / (tp + fp), 4),
                      precision_wilson95=wilson(tp, tp + fp),
                      recall=round(tp / (tp + fn), 4) if tp + fn else None,
                      recall_wilson95=wilson(tp, tp + fn))
    return out


def q(x, ps=(5, 25, 50, 75, 95)):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return None
    return {f"p{p}": round(float(np.percentile(x, p)), 1) for p in ps} | {"n": int(len(x)),
                                                                          "mean": round(float(x.mean()), 1)}


def main():
    S = json.load(open(os.path.join(T, "test_summary.json")))
    per = pd.read_csv(os.path.join(T, "test_flights_spin_vs_frozen.csv"))
    out = {"n_test_flights": S["n_test_flights"], "gate_h_s": S["gate_h_s"], "frozen_gate_h_s": S["frozen_gate_h_s"],
           "tau_spin": [S["tau_snapshot"], S["tau_online"]],
           "frozen_reproduction_check": S["frozen_reproduction_check"]}
    for rule in ("snapshot", "online"):
        out[f"{rule}_spin"] = table(S["test_spin"][rule])
        out[f"{rule}_frozen"] = table(S["test_frozen_reproduced"][rule])
    out["first_call_spin"] = S["test_spin"]["first_call"]
    out["first_call_frozen"] = S["test_frozen_reproduced"]["first_call"]
    out["flips_spin_vs_frozen"] = S["flips_spin_vs_frozen_test"]
    # per-flight: who is called, and how much earlier
    y = per.label == "MISS"
    ls, lf = per.spin_first_call_lead_ms, per.frozen_first_call_lead_ms
    both = y & ls.notna() & lf.notna()
    d = (ls - lf)[both]
    out["miss_first_call"] = dict(
        n_miss=int(y.sum()),
        called_spin=int((y & ls.notna()).sum()), called_frozen=int((y & lf.notna()).sum()),
        called_both=int(both.sum()), called_spin_only=int((y & ls.notna() & lf.isna()).sum()),
        called_frozen_only=int((y & ls.isna() & lf.notna()).sum()),
        lead_gain_both_ms=None if d.empty else dict(
            median=round(float(d.median()), 1), mean=round(float(d.mean()), 1),
            n_earlier=int((d > 0).sum()), n_same=int((d == 0).sum()), n_later=int((d < 0).sum())),
        spin_only_leads_ms=sorted(ls[y & ls.notna() & lf.isna()].round(1).tolist()),
        median_lead_spin_ms=None if not (y & ls.notna()).any() else round(float(ls[y].median()), 1),
        median_lead_frozen_ms=None if not (y & lf.notna()).any() else round(float(lf[y].median()), 1),
        # recall-weighted lead: a miss that is never called counts as lead 0
        mean_lead_all_miss_spin_ms=round(float(ls[y].fillna(0).mean()), 1),
        mean_lead_all_miss_frozen_ms=round(float(lf[y].fillna(0).mean()), 1),
        bounce_called_spin=int((~y & ls.notna()).sum()), bounce_called_frozen=int((~y & lf.notna()).sum()))
    # spin readout on test flights (label-independent physics fit)
    F = pd.read_pickle(os.path.join(T, "feats_test.pkl"))
    fl = per[["video", "f_net", "label"]].copy()
    rows = []
    for r in fl.itertuples():
        g = F[(F.video == r.video) & (F.f_net == r.f_net) & (F.ph_ok == 1)].sort_values("t")
        if g.empty:
            continue
        last = g.iloc[-1]
        k = int(g.t.max())
        at50 = g[g.t == k - K50]
        rows.append(dict(video=r.video, f_net=r.f_net, label=r.label, t_last=k, npts_last=last.ph_npts,
                         rms_px_last=last.ph_rms_px, speed_mps=last.ph_speed, anchor=last.ph_anchor,
                         top_rps=last.ph_top, top_sd_rps=last.ph_top_sd, side_rps=last.ph_side,
                         side_sd_rps=last.ph_side_sd, top_z=last.ph_top_z,
                         top_rps_50ms=at50.ph_top.iloc[0] if len(at50) else np.nan,
                         top_sd_rps_50ms=at50.ph_top_sd.iloc[0] if len(at50) else np.nan))
    R = pd.DataFrame(rows)
    R["top_rpm"], R["side_rpm"] = 60 * R.top_rps, 60 * R.side_rps
    R.to_csv(os.path.join(T, "test_spin_readout.csv"), index=False)
    conf = R[R.top_sd_rps <= 20]
    lit = 150.0
    out["spin_readout_test"] = dict(
        note="last decision frame of each test flight (the fit uses the whole flight up to t_ref - 2 frames); "
             "rps; rpm = 60 x rps; top > 0 topspin, < 0 backspin",
        n_flights_with_fit=int(len(R)),
        top_rps_all=q(R.top_rps), side_rps_all=q(R.side_rps), top_sd_rps=q(R.top_sd_rps),
        side_sd_rps=q(R.side_sd_rps),
        top_rpm_all=q(R.top_rpm), side_rpm_all=q(R.side_rpm),
        share_topspin_z_gt_2=round(float((R.top_z > 2).mean()), 3),
        share_backspin_z_lt_minus2=round(float((R.top_z < -2).mean()), 3),
        n_confident_top_sd_le_20rps=int(len(conf)),
        top_rps_confident=q(conf.top_rps), side_rps_confident=q(conf.side_rps),
        by_label={lab: dict(top_rps=q(g.top_rps), side_rps=q(g.side_rps), speed_mps=q(g.speed_mps))
                  for lab, g in R.groupby("label")},
        share_abs_top_le_150rps=round(float((R.top_rps.abs() <= lit).mean()), 3),
        share_abs_side_le_150rps=round(float((R.side_rps.abs() <= lit).mean()), 3),
        top_rps_at_50ms_lead=q(R.top_rps_50ms), top_sd_rps_at_50ms_lead=q(R.top_sd_rps_50ms),
        spin_diagnostics_from_run=S.get("spin_diagnostics_test"))
    json.dump(out, open(os.path.join(T, "report_numbers.json"), "w"), indent=1, default=float)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, col, lab in ((axes[0], "top_rps", "topspin (+) / backspin (-), rps"),
                         (axes[1], "side_rps", "sidespin, rps")):
        bins = np.linspace(-200, 200, 41)
        for lb, c in (("BOUNCE", "#6c757d"), ("MISS", "#d1495b")):
            ax.hist(np.clip(R.loc[R.label == lb, col], -199, 199), bins=bins, color=c, alpha=0.6, label=lb)
        ax.axvspan(-lit, lit, color="#2e86ab", alpha=0.06, lw=0)
        ax.set_xlabel(lab)
        ax.set_ylabel("test flights")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("Spin readout on test_1..7 (fit at t_ref; shaded: |spin| <= 150 rps, the reported upper end for table tennis)\n"
                 "real match footage (OpenTTGames, held-out games; CC BY-NC-SA 4.0)", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(T, "fig_spin_readout_test.png"), dpi=130)
    print(json.dumps({k: out[k] for k in ("snapshot_spin", "snapshot_frozen", "online_spin", "online_frozen",
                                          "miss_first_call")}, indent=1, default=float))
    print(json.dumps(out["spin_readout_test"], indent=1, default=float)[:4000])


if __name__ == "__main__":
    main()
