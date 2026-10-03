"""Detail tables, figures and results.json for the recommended policy (run after walkforward.py).

    python research/v2/sizing/report.py
      -> out/recommended_{monthly,regime}.csv, out/scale_curve.csv, out/noise.csv, out/risk_budget.csv,
         out/fig_cum.png, out/fig_frontier.png, out/fig_edge_by_q.png, results.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine as E  # noqa: E402
import walkforward as W  # noqa: E402

OUT = HERE / "out"
REC = W.RECOMMENDED           # what the clean walk-forward meta-selector holds (see meta.csv)
ALT = ["G_50pct_net250", "G_100pct_net250", "F10_F8_25pct", "F8_rp_zone05_wallet_net2000", "F9_F8_stop2sigma"]
SCALE = [  # (policy, shape label, deploy fraction)
    ("F6_usd_25pct", "usd mirror", .25), ("A1_usd_half", "usd mirror", .5), ("F7_usd_75pct", "usd mirror", .75),
    ("A0_base_usd1k_match3k", "usd mirror", 1.0),
    ("F10_F8_25pct", "rp+wallet+zone, net<=2000", .25), ("F8_rp_zone05_wallet_net2000", "rp+wallet+zone, net<=2000", .5),
    ("F11_F8_75pct", "rp+wallet+zone, net<=2000", .75), ("F12_F8_100pct", "rp+wallet+zone, net<=2000", 1.0),
    ("G_25pct_net500", "rp+wallet+zone, net<=500", .25), ("G_50pct_net500", "rp+wallet+zone, net<=500", .5),
    ("G_100pct_net500", "rp+wallet+zone, net<=500", 1.0),
    ("G_25pct_net250", "rp+wallet+zone, net<=250", .25), ("G_50pct_net250", "rp+wallet+zone, net<=250", .5),
    ("G_100pct_net250", "rp+wallet+zone, net<=250", 1.0),
    ("G_25pct_net100", "rp+wallet+zone, net<=100", .25), ("G_50pct_net100", "rp+wallet+zone, net<=100", .5),
    ("G_100pct_net100", "rp+wallet+zone, net<=100", 1.0)]
BASE = "A0_base_usd1k_match3k"
POL = {p.name: p for p in W.POLICIES}


def cluster_ci(tr, n_boot=2000, seed=0):
    g = tr.groupby("cond").agg(p=("pnl", "sum"), s=("shares", "sum"))
    if len(g) < 5:
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    P, S = g.p.to_numpy(), g.s.to_numpy()
    bs = [P[i].sum() / S[i].sum() for i in (rng.integers(0, len(g), len(g)) for _ in range(n_boot))]
    return float(np.percentile(bs, 2.5) * 100), float(np.percentile(bs, 97.5) * 100)


def summarize(tr, label):
    tr = tr[tr.month >= E.EVAL_START]
    lo, hi = cluster_ci(tr)
    d = E.daily_series(tr) if len(tr) else pd.Series(dtype=float)
    eq = d.cumsum()
    return {"subset": label, "n": len(tr), "matches": tr.cond.nunique(), "usd_traded": tr.usd_in.sum(),
            "pnl_usd": tr.pnl.sum(), "per_share_c": tr.pnl.sum() / tr.shares.sum() * 100 if len(tr) else np.nan,
            "ci_lo_c": lo, "ci_hi_c": hi, "per_print_c": tr.pnl_ps.mean() * 100,
            "sharpe_ann": d.mean() / d.std() * np.sqrt(365) if d.std() > 0 else np.nan,
            "worst_day_usd": d.min(), "max_dd_usd": (eq - eq.cummax()).min(), "days": len(d)}


def risk_budget(f, wh, pol):
    """The k that turns 1000/sqrt(q(1-q)) into shares, per month -> R = per-trade resolution-risk budget."""
    rows = []
    for m in sorted(x for x in f.month.unique() if x >= E.RUN_START):
        train, test = f[f.month < m], f[f.month == m]
        rate_now = float(test.rate.max())
        tr_raw = E.raw_cap(train, pol, train, "actual", wh, m, rate_override=rate_now)
        target = pol.deploy_frac * np.minimum(train.usd.to_numpy(), E.BASE_USD_CAP).mean()
        lo, hi = 1e-8, 1e8
        for _ in range(90):
            mid = np.sqrt(lo * hi)
            if (E.shares_from(tr_raw, mid, train, pol) * train.q.to_numpy()).mean() < target:
                lo = mid
            else:
                hi = mid
        k = np.sqrt(lo * hi)
        R = k * E.BASE_USD_CAP
        eff, pool = E.wallet_effect(wh, m)
        fee = rate_now * test.q * (1 - test.q)
        keep = (pool + test.wallet.map(eff).fillna(0) - fee) > 0
        rows.append({"month": m, "fee_rate_now": rate_now, "R_usd_sd_per_trade": R,
                     "max_shares_q50": R / 0.5, "max_usd_q50": R / 0.5 * 0.5,
                     "max_shares_q10": R / np.sqrt(0.09), "max_usd_q10": R / np.sqrt(0.09) * 0.1,
                     "max_shares_q90": R / np.sqrt(0.09), "max_usd_q90": min(R / np.sqrt(0.09) * 0.9, E.BASE_USD_CAP),
                     "wallets_passing": int(test.wallet[keep].nunique()), "wallets_in_tier": int(test.wallet.nunique()),
                     "prints_passing_share": float(keep.mean())})
    return pd.DataFrame(rows)


def main():
    f, wh = E.load(), E.load_wallet_hist()
    runs = {}
    for name in dict.fromkeys([REC, *ALT, BASE, *[s[0] for s in SCALE]]):
        pol = POL[name]
        for me in (("res", "m30", "m30x") if name in (REC, *ALT, BASE) else ("res", "m30")):
            sig = None
            if np.isfinite(pol.stop_k):
                sig = E.sigma_from_history(E.simulate(f, W.replace(pol, stop_k=np.inf), me, "actual", wh))
            runs[(name, me)] = E.simulate(f, pol, me, "actual", wh, sig)

    # recommended: monthly and regime tables, both measures
    rows = []
    for me in ("res", "m30", "m30x"):
        tr = runs[(REC, me)]
        for m in sorted(tr.month.unique()):
            if m >= E.EVAL_START:
                rows.append({"measure": me, "month": m, **summarize(tr[tr.month == m], m)})
    mon = pd.DataFrame(rows)
    mon.round(4).to_csv(OUT / "recommended_monthly.csv", index=False)
    rows = []
    for name in [REC, *ALT, BASE]:
        for me in ("res", "m30", "m30x"):
            tr = runs[(name, me)]
            rows.append({"policy": name, "measure": me, **summarize(tr, "all")})
            for rg in sorted(tr.regime.unique()):
                rows.append({"policy": name, "measure": me, **summarize(tr[tr.regime == rg], rg)})
    reg = pd.DataFrame(rows)
    reg.round(4).to_csv(OUT / "recommended_regime.csv", index=False)

    # scale curve (capacity): F8 shape at 25/50/75/100% vs dollar mirror at 25/50/75/100%
    rows = []
    days5 = (f[f.regime == "1s/5%"].ts.max() - f[f.regime == "1s/5%"].ts.min()) / 86400
    for name, shape, frac in SCALE:
        for me in ("res", "m30"):
            if (name, me) not in runs:
                runs[(name, me)] = E.simulate(f, POL[name], me, "actual", wh)
            tr = runs[(name, me)]
            s_all = summarize(tr, "all")
            s5 = summarize(tr[tr.regime == "1s/5%"], "1s/5%")
            cap = 3 * E.peak_locked(tr[tr.month >= E.EVAL_START])
            rows.append({"policy": name, "shape": shape, "deploy_frac": frac, "measure": me,
                         "sharpe_ann": s_all["sharpe_ann"], "pnl_usd": s_all["pnl_usd"], "per_share_c": s_all["per_share_c"],
                         "capital_usd": cap, "max_dd_pct": s_all["max_dd_usd"] / cap * 100,
                         "worst_day_pct": s_all["worst_day_usd"] / cap * 100,
                         "sharpe_1s5": s5["sharpe_ann"],
                         "usd_traded_per_30d_1s5": s5["usd_traded"] / days5 * 30,
                         "pnl_per_30d_1s5": s5["pnl_usd"] / days5 * 30, "per_share_1s5_c": s5["per_share_c"],
                         "ci_1s5": [s5["ci_lo_c"], s5["ci_hi_c"]]})
    scale = pd.DataFrame(rows)
    scale.round(4).to_csv(OUT / "scale_curve.csv", index=False)

    # noise decomposition: daily P&L variance with hold-to-resolution vs 30 s exit
    rows = []
    for name in [BASE, "F8_rp_zone05_wallet_net2000", "G_50pct_net250", REC]:
        for sub in ("all", "1s/5%"):
            a, b = runs[(name, "res")], runs[(name, "m30")]
            if sub != "all":
                a, b = a[a.regime == sub], b[b.regime == sub]
            a, b = a[a.month >= E.EVAL_START], b[b.month >= E.EVAL_START]
            da, db = E.daily_series(a), E.daily_series(b).reindex(E.daily_series(a).index, fill_value=0)
            rows.append({"policy": name, "subset": sub, "pnl_res": a.pnl.sum(), "pnl_m30": b.pnl.sum(),
                         "resolution_component_usd": a.pnl.sum() - b.pnl.sum(),
                         "daily_sd_res": da.std(), "daily_sd_m30": db.std(),
                         "share_of_daily_var_from_resolution": 1 - db.var() / da.var()})
    noise = pd.DataFrame(rows)
    noise.round(4).to_csv(OUT / "noise.csv", index=False)

    # per-match P&L tails (held to resolution)
    rows = []
    for name in [BASE, "F8_rp_zone05_wallet_net2000", "G_50pct_net250", REC]:
        tr = runs[(name, "res")]
        tr = tr[tr.month >= E.EVAL_START]
        for sub, t in (("all", tr), ("1s/5%", tr[tr.regime == "1s/5%"])):
            pm = t.groupby("cond").pnl.sum()
            net = t.assign(ns=t.shares * t.dir).groupby("cond").ns.sum().abs()
            rows.append({"policy": name, "subset": sub, "matches": len(pm), "worst_match_usd": pm.min(),
                         "p01_match_usd": pm.quantile(.01), "p99_match_usd": pm.quantile(.99),
                         "share_matches_negative": (pm < 0).mean(), "median_abs_net_shares": net.median(),
                         "max_abs_net_shares": net.max()})
    tails = pd.DataFrame(rows)
    tails.round(3).to_csv(OUT / "match_tails.csv", index=False)
    print(tails.round(2).to_string(index=False))

    rb = risk_budget(f, wh, POL[REC])
    rb.round(3).to_csv(OUT / "risk_budget.csv", index=False)

    # ---------------------------------------------------------------- figures
    import matplotlib.dates as mdates
    caps = {n: 3 * E.peak_locked(runs[(n, "res")][runs[(n, "res")].month >= E.EVAL_START])
            for n in (BASE, "F8_rp_zone05_wallet_net2000", "G_50pct_net250", REC)}
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    for i, me in enumerate(("res", "m30")):
        for name, lab, c in [(BASE, "baseline: $ mirror, <=$1k/trade, <=$3k/match", "#999999"),
                             ("F8_rp_zone05_wallet_net2000", "risk parity (R~$100) + wallet + zone, net <=2000 sh", "#7fa7d9"),
                             ("G_50pct_net250", "same, net exposure <=250 sh/match", "#3c78c3"),
                             (REC, "recommended: same, net <=100 sh/match", "#0b2e66")]:
            d = E.daily_series(runs[(name, me)][runs[(name, me)].month >= E.EVAL_START]).cumsum() / caps[name] * 100
            ax[i].plot(d.index.tz_localize(None), d.values, label=lab, color=c, lw=1.5)
        ax[i].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax[i].axvspan(pd.Timestamp("2026-07-11"), pd.Timestamp("2026-08-25"), color="#f2c14e", alpha=.25, lw=0)
        ax[i].set_title({"res": "Held to resolution (net of fee)", "m30": "Exit at 30 s mid (net of entry fee)"}[me], fontsize=10)
        ax[i].set_ylabel("cumulative P&L, % of capital"); ax[i].grid(alpha=.3)
    ax[0].legend(fontsize=7, loc="upper left")
    ax[1].text(pd.Timestamp("2026-07-13"), ax[1].get_ylim()[1] * 0.9, "1 s / 5% fee", fontsize=8)
    fig.suptitle("Walk-forward shadow book, IS Feb-Aug 2026 (rules fitted on earlier months; capital = 3 x peak locked $)", fontsize=10)
    fig.tight_layout(); fig.savefig(OUT / "fig_cum.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.6, 3.8))
    for shape, c in [("usd mirror", "#999999"), ("rp+wallet+zone, net<=2000", "#7fa7d9"),
                     ("rp+wallet+zone, net<=250", "#3c78c3"), ("rp+wallet+zone, net<=100", "#0b2e66")]:
        s = scale[(scale["shape"] == shape) & (scale.measure == "res")].sort_values("deploy_frac")
        ax.plot(s.capital_usd / 1e3, s.sharpe_ann, "o-", color=c, label=shape)
        for _, r in s.iterrows():
            ax.annotate(f"{int(r.deploy_frac*100)}%", (r.capital_usd / 1e3, r.sharpe_ann), fontsize=7,
                        xytext=(3, 3 if r.deploy_frac != 1.0 or "100" not in shape else -9), textcoords="offset points")
    ax.set_xlabel("capital = 3 x peak locked, $k"); ax.set_ylabel("annualised Sharpe (held to resolution)")
    ax.text(0.98, 0.02, "at 100% the risk-parity cap no longer binds\n(= $ mirror + wallet + zone + net cap)", fontsize=6,
            ha="right", va="bottom", transform=ax.transAxes, color="#555555")
    ax.grid(alpha=.3); ax.legend(fontsize=7); ax.set_title("Sharpe vs capital (labels: target % of baseline $ per trade)", fontsize=9)
    fig.tight_layout(); fig.savefig(OUT / "fig_frontier.png", dpi=160); plt.close(fig)

    eq = pd.read_csv(OUT / "edge_by_q.csv")
    e = eq[eq.subset == "all"]
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    x = np.arange(len(e))
    ax.bar(x - 0.2, e.gross30, 0.4, label="gross 30 s markout", color="#1f5aa6")
    ax.bar(x + 0.2, e.net30_5, 0.4, label="net of 5% fee", color="#f2a900")
    ax.errorbar(x + 0.2, e.net30_5, yerr=[e.net30_5 - e.net30_5_lo, e.net30_5_hi - e.net30_5], fmt="none", color="k", lw=.8)
    ax.set_xticks(x); ax.set_xticklabels([b.replace("(", "").replace("]", "") for b in e.bucket], rotation=60, fontsize=7)
    ax.set_xlabel("token price paid q"); ax.set_ylabel("cents / share"); ax.grid(alpha=.3, axis="y")
    ax.legend(fontsize=8); ax.set_title("Fast-tier edge vs price: flat gross, fee = 5q(1-q)", fontsize=9)
    fig.tight_layout(); fig.savefig(OUT / "fig_edge_by_q.png", dpi=160); plt.close(fig)

    # ---------------------------------------------------------------- results.json
    pol_df = pd.read_csv(OUT / "policies.csv")
    meta = pd.read_csv(OUT / "meta.csv")
    vc = json.loads((OUT / "variant_count.json").read_text())
    dsr = pd.read_csv(OUT / "deflated_sharpe.csv")

    def pick(name, me, fm="actual"):
        r = pol_df[(pol_df.policy == name) & (pol_df.measure == me) & (pol_df.fee_mode == fm)].iloc[0].to_dict()
        return {k: (json.loads(v) if isinstance(v, str) and v.startswith("[") else v) for k, v in r.items()}

    rg = reg.set_index(["policy", "measure", "subset"])
    out = {
        "lens": "sizing",
        "recommended_policy": REC,
        "recommended_definition": {k: (str(v) if isinstance(v, float) and not np.isfinite(v) else v)
                                   for k, v in W.asdict(POL[REC]).items()},
        "risk_budget_by_month": rb.round(3).to_dict("records"),
        "eval_months": "2026-02..2026-08 (IS; Aug ends at the OOS boundary)",
        "baseline": {me: pick(BASE, me) for me in ("res", "m30", "m30x")},
        "recommended": {me: pick(REC, me) for me in ("res", "m30", "m30x")},
        "recommended_5pct_fee_mode": {me: pick(REC, me, "5pct") for me in ("res", "m30")},
        "alternatives": {n: {me: pick(n, me) for me in ("res", "m30")} for n in ALT},
        "regime_1s5": {n: {me: rg.loc[(n, me, "1s/5%")].to_dict() for me in ("res", "m30", "m30x")} for n in [REC, BASE, *ALT]},
        "meta_selection": meta.to_dict("records"),
        "deflated_sharpe": dsr[dsr.policy.isin([REC, BASE, *ALT])].to_dict("records"),
        "noise": noise.to_dict("records"),
        "match_tails": tails.to_dict("records"),
        "scale_curve": scale.to_dict("records"),
        "variant_count": vc,
    }
    (HERE / "results.json").write_text(json.dumps(out, indent=2, default=lambda o: float(o) if isinstance(o, np.floating) else str(o)))
    pd.set_option("display.width", 250)
    print(mon.round(2).to_string(index=False))
    print(reg.round(2).to_string(index=False))
    print(scale.round(2).to_string(index=False))
    print(noise.round(3).to_string(index=False))
    print(rb.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
