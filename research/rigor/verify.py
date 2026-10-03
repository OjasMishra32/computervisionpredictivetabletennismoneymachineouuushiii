"""Independent check of results/rigor/rigor.json: PSR/DSR for v2 IS and burned OOS, PBO for the v2-safe grid.

    .venv/bin/python research/rigor/verify.py      # ~15 s, 1 process -> research/rigor/out/verify.json + stdout

Own code: nothing is imported from scripts/rigor_pack.py. Analysis of existing results only; no strategy rule
is touched. Rows of matches starting on/after 2026-10-03 13:00 UTC are dropped before anything else.
Daily series are rebuilt from the trade parquet (date = UTC floor of ts), not read from rigor_pack's CSVs.
The sizing-grid variance uses rigor_pack's saved rebuild, re-checked here column by column against
research/v2/sizing/out/policies.csv.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import integrate, stats

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.tape import universe  # noqa: E402

CUT = pd.Timestamp("2026-10-03 13:00", tz="UTC")
ANN, GAMMA = np.sqrt(365), np.euler_gamma
IS_D = pd.date_range("2026-02-01", "2026-08-25", freq="D", tz="UTC")
OOS_D = pd.date_range("2026-08-25", "2026-10-03", freq="D", tz="UTC")
SAFE, BASE = "n50_d50_z05-95_sinf", "n100_d50_z05-95_sinf"
NS = {"N44": 44, "N3386": 3386, "N3410": 3410}
REF = json.loads((ROOT / "results/rigor/rigor.json").read_text())


# --------------------------------------------------------------------------- statistics (own code)
def moments(x):
    x = np.asarray(x, float)
    T, d = len(x), x - x.mean()
    m2, m3, m4 = (d ** 2).mean(), (d ** 3).mean(), (d ** 4).mean()
    g1, b2 = m3 / m2 ** 1.5, m4 / m2 ** 2                        # population skew, Pearson kurtosis
    G1 = g1 * np.sqrt(T * (T - 1)) / (T - 2)                      # Joanes-Gill adjusted
    G2 = (T - 1) / ((T - 2) * (T - 3)) * ((T + 1) * (b2 - 3) + 6) + 3
    return {"T": T, "sr": x.mean() / x.std(ddof=1), "skew": G1, "kurt": G2, "skew_pop": g1, "kurt_pop": b2,
            "ac1": float(np.corrcoef(x[:-1], x[1:])[0, 1])}


def psr(sr, sr0, T, skew, kurt):
    """Bailey & Lopez de Prado (2012): per-period SR, Pearson kurtosis (normal = 3), sqrt(T - 1)."""
    return float(stats.norm.cdf((sr - sr0) * np.sqrt(T - 1) / np.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr ** 2)))


def emax_approx(n):
    return (1 - GAMMA) * stats.norm.ppf(1 - 1 / n) + GAMMA * stats.norm.ppf(1 - 1 / (n * np.e))


def emax_exact(n):
    """E[max of n iid N(0,1)] by quadrature."""
    f = lambda z: z * n * stats.norm.pdf(z) * stats.norm.cdf(z) ** (n - 1)  # noqa: E731
    return integrate.quad(f, -12, 12, limit=400)[0]


def sharpe_cols(M):
    return M.mean(0) / M.std(0, ddof=1)


def cscv(M, S=16, rule="sharpe", base=None, blocks="split"):
    """CSCV (Bailey, Borwein, Lopez de Prado, Zhu 2017), plain loop over all C(S, S/2) splits."""
    T, N = M.shape
    if blocks == "split":
        B = np.array_split(np.arange(T), S)
    else:                                       # equal blocks: drop the earliest T mod S days
        k = T // S
        B = [np.arange(T - k * S + i * k, T - k * S + (i + 1) * k) for i in range(S)]
    lam, xs, ys = [], [], []
    for c in itertools.combinations(range(S), S // 2):
        J = M[np.concatenate([B[i] for i in c])]
        Jb = M[np.concatenate([B[i] for i in range(S) if i not in c])]
        if rule == "sharpe":
            pi, po = sharpe_cols(J), sharpe_cols(Jb)
            n = int(np.argmax(pi))
        else:                                   # GRID.md rule on the IS half, scored by OOS-half share
            pi, po, mu = (J > 0).mean(0), (Jb > 0).mean(0), J.mean(0)
            feas = mu >= 0.5 * mu[base]
            if not feas.any():
                n = base
            else:
                cand = np.flatnonzero(feas & (pi == pi[feas].max()))
                n = int(cand[np.argmax(mu[cand])])
        w = stats.rankdata(po)[n] / (N + 1)
        lam.append(np.log(w / (1 - w)))
        xs.append(pi[n])
        ys.append(po[n])
    lam, xs, ys = map(np.asarray, (lam, xs, ys))
    sc = ANN if rule == "sharpe" else 1.0
    lr = stats.linregress(xs * sc, ys * sc)
    return {"pbo": float(np.mean(lam <= 0)), "pbo_strict_lt0": float(np.mean(lam < 0)),
            "n_lambda_eq_0": int(np.sum(lam == 0)), "n_splits": int(len(lam)),
            "logit_mean": float(lam.mean()), "logit_median": float(np.median(lam)), "logit_sd": float(lam.std()),
            "logit_p05": float(np.percentile(lam, 5)), "logit_p95": float(np.percentile(lam, 95)),
            "slope": float(lr.slope), "r2": float(lr.rvalue ** 2),
            "is_mean": float(xs.mean() * sc), "oos_mean": float(ys.mean() * sc)}


# --------------------------------------------------------------------------- data
def load():
    u = universe()
    t = pd.read_parquet(ROOT / "data/v2_trades_is_oos.parquet", columns=["cond", "ts", "pnl", "month"])
    start = t.cond.map(u.set_index("cond").start)
    assert start.notna().all()
    t = t[start < CUT]                                             # cutoff guard first
    oos = set(u.loc[u.oos, "cond"])
    t["day"] = pd.to_datetime(t.ts, unit="s", utc=True).dt.floor("D")
    is_m = (~t.cond.isin(oos)) & (t.month >= "2026-02")
    d_is = t[is_m].groupby("day").pnl.sum()
    d_oos = t[t.cond.isin(oos)].groupby("day").pnl.sum()
    assert d_is.index.isin(IS_D).all() and d_oos.index.isin(OOS_D).all()
    jan = t[(~t.cond.isin(oos)) & (t.month < "2026-02")]
    g = pd.read_csv(ROOT / "research/v2/lowloss/out/daily.csv", parse_dates=["date"]).set_index("date").reindex(IS_D)
    bk = pd.read_csv(ROOT / "results/lowloss/daily.csv", parse_dates=["date"])
    bk = bk[(bk.run == "a") & (bk.book == "u1_oos") & (bk.policy == "v2_safe")]
    safe_oos = bk.set_index(pd.DatetimeIndex(bk.date).tz_localize("UTC")).pnl_usd.reindex(OOS_D)
    sz = pd.read_csv(ROOT / "research/rigor/out/sizing_daily_is_res_actual.csv", index_col=0, parse_dates=True)
    pol = pd.read_csv(ROOT / "research/v2/sizing/out/policies.csv")
    pol = pol[(pol.measure == "res") & (pol.fee_mode == "actual")].set_index("policy").sharpe_ann
    sz_err = max(abs(sharpe_cols(sz[[c]].to_numpy())[0] * ANN - pol[c]) for c in sz.columns)
    return (d_is.reindex(IS_D, fill_value=0.0), d_oos.reindex(OOS_D, fill_value=0.0), g, safe_oos, sz, sz_err,
            {"n_trades_is": int(is_m.sum()), "n_trades_oos": int(t.cond.isin(oos).sum()),
             "n_trades_jan_not_in_is": int(len(jan))})


def main():
    d_is, d_oos, g, safe_oos, sz, sz_err, meta = load()
    causal = json.loads((ROOT / "results/v2/causal.json").read_text())
    var = pd.read_csv(ROOT / "research/v2/lowloss/out/variants.csv").set_index("variant").sharpe_ann
    out = {"inputs": meta, "checks": {}}
    ck = out["checks"]
    ck["v2_is_sharpe_vs_causal"] = abs(sharpe_cols(d_is.to_numpy()[:, None])[0] * ANN - causal["causal/is_eval/slip0.0"]["sharpe_ann"])
    ck["v2_oos_sharpe_vs_causal"] = abs(sharpe_cols(d_oos.to_numpy()[:, None])[0] * ANN - causal["causal/burned_oos/slip0.0"]["sharpe_ann"])
    ck["v2_is_total_vs_causal"] = abs(d_is.sum() - causal["causal/is_eval/slip0.0"]["total_pnl_usd"])
    ck["v2_oos_total_vs_causal"] = abs(d_oos.sum() - causal["causal/burned_oos/slip0.0"]["total_pnl_usd"])
    ck["grid_max_sharpe_diff_vs_variants_csv"] = float(np.max(np.abs(sharpe_cols(g.to_numpy()) * ANN - var[g.columns].to_numpy())))
    ck["grid_base_eq_v2_is_max_abs_usd"] = float(np.max(np.abs(g[BASE].to_numpy() - d_is.to_numpy())))
    ck["sizing_csv_max_sharpe_diff_vs_policies_csv"] = float(sz_err)

    # ---- moments + PSR / DSR
    ser = {"v2_is": d_is, "v2_oos": d_oos, "v2safe_is": g[SAFE], "v2safe_oos": safe_oos}
    V = {"lowloss_grid_24": float(np.var(sharpe_cols(g.to_numpy()), ddof=1)),
         "sizing_grid_55": float(np.var(sharpe_cols(sz.to_numpy()), ddof=1))}
    rows, cmp = {}, []
    for k, s in ser.items():
        m = moments(s.to_numpy())
        ref_m, ref_r = REF["sharpe_moments"][k], next(r for r in REF["psr_dsr"]["rows"] if r["series"] == k)
        r = {"sharpe_ann": m["sr"] * ANN, "skew": m["skew"], "kurt": m["kurt"], "ac1": m["ac1"], "T": m["T"],
             "psr0": psr(m["sr"], 0, m["T"], m["skew"], m["kurt"]), "dsr": {}}
        for nl, n in NS.items():
            for vl, v in (("null", 1 / (m["T"] - 1)), *V.items()):
                s0 = np.sqrt(v) * emax_approx(n)
                r["dsr"][f"{nl}/{vl}"] = {"sr0_ann": s0 * ANN, "dsr": psr(m["sr"], s0, m["T"], m["skew"], m["kurt"])}
        # sensitivity: the classic convention errors, to show what each would have produced
        r["wrong_annualised_sr_in_psr0"] = psr(m["sr"] * ANN, 0, m["T"], m["skew"], m["kurt"])
        r["wrong_excess_kurt_dsr_N3386_null"] = psr(m["sr"], np.sqrt(1 / (m["T"] - 1)) * emax_approx(3386), m["T"], m["skew"], m["kurt"] - 3)
        r["pop_moments_dsr_N3386_null"] = psr(m["sr"], np.sqrt(1 / (m["T"] - 1)) * emax_approx(3386), m["T"], m["skew_pop"], m["kurt_pop"])
        r["exact_emax_dsr_N3386_null"] = psr(m["sr"], np.sqrt(1 / (m["T"] - 1)) * emax_exact(3386), m["T"], m["skew"], m["kurt"])
        rho = m["ac1"]                       # AR(1) inflation of var(mean): (1 + rho) / (1 - rho)
        r["ar1_psr0"] = float(stats.norm.cdf(stats.norm.ppf(r["psr0"]) / np.sqrt((1 + rho) / (1 - rho)))) if r["psr0"] < 1 else 1.0
        rows[k] = r
        for lab, a, b in (("sharpe_ann", r["sharpe_ann"], ref_m["sharpe_ann"]), ("skew", r["skew"], ref_m["skew"]),
                          ("kurtosis", r["kurt"], ref_m["kurtosis"]), ("ac1", r["ac1"], ref_m["ac1"]),
                          ("psr_vs_0", r["psr0"], ref_r["psr_vs_0"]),
                          *((f"dsr {kk}", vv["dsr"], ref_r["dsr"][kk]["dsr"]) for kk, vv in r["dsr"].items()),
                          *((f"sr0 {kk}", vv["sr0_ann"], ref_r["dsr"][kk]["sr0_ann"]) for kk, vv in r["dsr"].items())):
            cmp.append((k, lab, a, b, abs(a - b)))
    for vl in V:
        cmp.append(("V", vl, V[vl], REF["psr_dsr"]["variance_sources"][vl]["var_daily_sr"],
                    abs(V[vl] - REF["psr_dsr"]["variance_sources"][vl]["var_daily_sr"])))
    out["psr_dsr"] = rows
    out["emax"] = {n: {"approx": float(emax_approx(n)), "exact": float(emax_exact(n))} for n in (2, 4, 6, 24, 44, 3386)}
    # OOS deflated only by the number of strategies actually looked at on the OOS (holdout reading)
    out["oos_dsr_small_N_null_T40"] = {
        k: {n: psr(moments(ser[k].to_numpy())["sr"], np.sqrt(1 / 39) * emax_exact(n), 40,
                   moments(ser[k].to_numpy())["skew"], moments(ser[k].to_numpy())["kurt"]) for n in (2, 4, 6, 24)}
        for k in ("v2_oos", "v2safe_oos")}
    # trials were scored on IS (T=206), so the IS-sample null variance is the matching one for SR*
    out["oos_dsr_N3386_null_T206"] = {k: psr(moments(ser[k].to_numpy())["sr"], np.sqrt(1 / 205) * emax_approx(3386), 40,
                                             moments(ser[k].to_numpy())["skew"], moments(ser[k].to_numpy())["kurt"])
                                      for k in ("v2_oos", "v2safe_oos")}
    C = np.corrcoef(g.to_numpy().T)
    rho_bar = float(C[np.triu_indices_from(C, 1)].mean())
    out["lowloss_grid_avg_pairwise_corr"] = rho_bar
    out["lowloss_grid_N_eff"] = rho_bar + (1 - rho_bar) * 24

    # ---- PBO, v2-safe grid
    M = g.to_numpy()
    base = list(g.columns).index(BASE)
    _, first = np.unique(np.round(M, 9), axis=1, return_index=True)
    keep = np.sort(first)
    pb = {"sharpe": cscv(M), "selection_rule": cscv(M, rule="share", base=base),
          "sharpe_equal_blocks_192d": cscv(M, blocks="trunc"),
          "sharpe_dedup_twins": cscv(M[:, keep]),
          "selection_rule_dedup_twins": cscv(M[:, keep], rule="share", base=int(np.flatnonzero(keep == base)[0]))}
    for S in (8, 10, 12, 14):
        pb[f"sharpe_S{S}"] = cscv(M, S=S)
    pb["n_distinct"] = int(len(keep))
    out["pbo"] = pb
    for mine, theirs in (("sharpe", "lowloss_24_sharpe"), ("selection_rule", "lowloss_24_selection_rule")):
        R = REF["pbo_cscv"][theirs]
        for lab, a, b in (("pbo", pb[mine]["pbo"], R["pbo"]), ("logit_mean", pb[mine]["logit_mean"], R["logit"]["mean"]),
                          ("logit_median", pb[mine]["logit_median"], R["logit"]["median"]),
                          ("logit_sd", pb[mine]["logit_sd"], R["logit"]["sd"]),
                          ("logit_p05", pb[mine]["logit_p05"], R["logit"]["p05"]),
                          ("logit_p95", pb[mine]["logit_p95"], R["logit"]["p95"]),
                          ("slope", pb[mine]["slope"], R["degradation"]["slope"]), ("r2", pb[mine]["r2"], R["degradation"]["r2"]),
                          ("is_mean", pb[mine]["is_mean"], R["degradation"]["is_mean"]),
                          ("oos_mean", pb[mine]["oos_mean"], R["degradation"]["oos_mean"])):
            cmp.append((f"pbo/{mine}", lab, a, b, abs(a - b)))

    out["comparison_max_abs_diff"] = max(c[4] for c in cmp)
    out["comparison"] = [{"series": a, "stat": b, "mine": c, "rigor_json": d, "abs_diff": e} for a, b, c, d, e in cmp]
    (ROOT / "research/rigor/out").mkdir(parents=True, exist_ok=True)
    (ROOT / "research/rigor/out/verify.json").write_text(json.dumps(out, indent=1, default=float))

    print("== input checks (abs diff)")
    for k, v in ck.items():
        print(f"  {k:45s} {v:.2e}")
    print(f"  trades: IS {meta['n_trades_is']}, OOS {meta['n_trades_oos']}, Jan (excluded from IS) {meta['n_trades_jan_not_in_is']}")
    print(f"== mine vs rigor.json: {len(cmp)} numbers, max abs diff {out['comparison_max_abs_diff']:.2e}")
    for a, b, c, d, e in cmp:
        if e > 1e-9:
            print(f"  DIFF {a:22s} {b:28s} mine {c:.6g} rigor {d:.6g}")
    print("== PSR / DSR (mine)")
    for k, r in rows.items():
        d = r["dsr"]
        print(f"  {k:10s} SR {r['sharpe_ann']:6.2f} skew {r['skew']:+.2f} kurt {r['kurt']:.2f} PSR0 {r['psr0']:.4f} | "
              f"DSR N44 null/ll/sz {d['N44/null']['dsr']:.3f}/{d['N44/lowloss_grid_24']['dsr']:.3f}/{d['N44/sizing_grid_55']['dsr']:.3f} | "
              f"N3386 {d['N3386/null']['dsr']:.3f}/{d['N3386/lowloss_grid_24']['dsr']:.3f}/{d['N3386/sizing_grid_55']['dsr']:.3f}")
        print(f"  {'':10s} if annualised SR in PSR0: {r['wrong_annualised_sr_in_psr0']:.4f}; if excess kurt, DSR3386null: "
              f"{r['wrong_excess_kurt_dsr_N3386_null']:.4f}; pop moments: {r['pop_moments_dsr_N3386_null']:.4f}; "
              f"exact E[max]: {r['exact_emax_dsr_N3386_null']:.4f}; AR(1)-adj PSR0: {r['ar1_psr0']:.4f}")
    print("== E[max of N std normals] approx vs exact:", {n: (round(v['approx'], 3), round(v['exact'], 3)) for n, v in out["emax"].items()})
    print("== OOS DSR, null V at T=40, N = OOS looks only:", {k: {n: round(x, 3) for n, x in v.items()} for k, v in out["oos_dsr_small_N_null_T40"].items()})
    print("== OOS DSR, N=3386 with IS-sample null V (T=206):", {k: round(v, 3) for k, v in out["oos_dsr_N3386_null_T206"].items()})
    print(f"== lowloss grid: avg pairwise corr {rho_bar:.3f}, N_eff {out['lowloss_grid_N_eff']:.2f}, distinct {pb['n_distinct']}")
    print("== PBO (mine)")
    for k, p in pb.items():
        if isinstance(p, dict):
            print(f"  {k:28s} PBO {p['pbo']:.4f} (lambda<0: {p['pbo_strict_lt0']:.4f}, ==0: {p['n_lambda_eq_0']}) splits {p['n_splits']:5d} "
                  f"logit {p['logit_mean']:+.3f}/{p['logit_median']:+.3f}/{p['logit_sd']:.3f} slope {p['slope']:+.3f} R2 {p['r2']:.2f} "
                  f"IS->OOS {p['is_mean']:.3f}->{p['oos_mean']:.3f}")


if __name__ == "__main__":
    main()
