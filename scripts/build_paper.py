"""Build the COURTSIDE paper: docs/NOTE.pdf (LaTeX via tectonic) and its readable companion docs/NOTE.md.

Pipeline (docs/paper/PLAN.md section 1):
  1. read every number from committed result files into one registry -> results/paper/numbers.json
     (each entry: value as printed, raw value, source file::key). A missing key stops the build.
  2. write results/paper/{policy,variants,peeks}.json and docs/paper/numbers.tex (one macro per key)
  3. draw every figure (scripts/paper_figures_v2.py, house style docs/paper/figstyle.py) into results/paper/v2/
  4. render docs/paper/note.tex.j2 -> docs/paper/note.tex and compile with tectonic
  5. acceptance checks (PLAN section 15): main text <= 5 pages, every main-text span >= 11 pt (figure text
     included), 1 in margins, honesty grep, LaTeX log clean, fonts embedded and ours -> results/paper/checks.json
  6. page renders at 110 dpi -> results/paper/pages/, copy to docs/NOTE.pdf, write docs/NOTE.md and docs/NOTE.html

The one pending slot is the blind forward test (HYPOTHESIS_V2.md A4): it fills from results/v2/forward.json when that
file exists and otherwise says when the pre-registered run happens. The live paper session was stopped and appears only
as one line in the appendix records. scripts/forward_test.py is never imported or run here. Nothing here runs a new evaluation: it reads committed
result files, and Fig. 2(b) re-draws the committed v2 trade file (IS and burned OOS) with the cost-stress lambdas,
asserting the committed totals to the cent.

Usage: .venv/bin/python scripts/build_paper.py [--no-figures] [--no-checks-fail]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from reproduction_contract import atomic_copy, sha256_file

PAPER = ROOT / "docs/paper"
OUT = ROOT / "results/paper"
MINUS = "\u2212"
TECTONIC = shutil.which("tectonic") or "/opt/homebrew/bin/tectonic"
CV_LABEL = "assumed feed latency (licensed feed not purchased); parameters measured"


# ================================================================================================ helpers
def J(rel: str):
    return json.loads((ROOT / rel).read_text())


def get(d, *path):
    for p in path:
        d = d[p]
    return d


def m(s: str) -> str:
    return s.replace("-", MINUS)


def sgn(x: float, nd: int = 2) -> str:
    if round(x, nd) == 0:
        x = 0.0
    return m(f"{x:+.{nd}f}")


def num(x: float, nd: int = 2) -> str:
    if round(x, nd) == 0:
        x = 0.0
    return m(f"{x:.{nd}f}")


def ci(v, nd: int = 2) -> str:
    return f"[{num(v[0], nd)}, {num(v[1], nd)}]"


def usd(x: float, nd: int = 0, signed: bool = False) -> str:
    s = f"{abs(x):,.{nd}f}"
    if x < 0 and round(abs(x), nd) > 0:
        return f"{MINUS}${s}"
    return f"+${s}" if signed else f"${s}"


def intc(x) -> str:
    return f"{int(round(x)):,}"


def pct(x: float, nd: int = 1) -> str:
    return num(x, nd) + "%"


def tex_breakable(s: str) -> str:
    """tex() plus break points after / , _ and - so long paths wrap inside narrow table cells."""
    out = tex(s)
    for a in ("/", ",", r"\_", "-"):
        out = out.replace(a, a + r"\allowbreak{}")
    return out


def tex(s: str) -> str:
    """Plain printed value -> LaTeX-safe text."""
    out = str(s)
    for a, b in (("\\", r"\textbackslash{}"), ("$", r"\$"), ("%", r"\%"), ("&", r"\&"), ("#", r"\#"),
                 ("_", r"\_"), ("~", r"\textasciitilde{}")):
        out = out.replace(a, b)
    return out


class Registry:
    def __init__(self):
        self.d: dict[str, dict] = {}

    def add(self, key: str, value: str, raw, source: str) -> None:
        if key in self.d:
            raise KeyError(f"duplicate number key {key}")
        if isinstance(raw, (np.floating, np.integer)):
            raw = raw.item()
        self.d[key] = {"value": value, "raw": raw, "source": source}

    def __call__(self, key: str) -> str:
        if key not in self.d:
            raise KeyError(f"COURTSIDE: missing number {key}")
        return tex(self.d[key]["value"])

    def text(self, key: str) -> str:
        if key not in self.d:
            raise KeyError(f"COURTSIDE: missing number {key}")
        return self.d[key]["value"]

    def raw(self, key: str):
        return self.d[key]["raw"]


def src_line(rel: str, pattern: str) -> str:
    """file:line of the first line matching pattern (provenance for policy constants)."""
    for i, line in enumerate((ROOT / rel).read_text().splitlines(), 1):
        if re.search(pattern, line):
            return f"{rel}:{i}"
    raise KeyError(f"policy constant not found: {pattern} in {rel}")


# ================================================================================================ numbers
def collect() -> tuple[Registry, dict]:
    N = Registry()
    extra: dict = {}

    # ---------------------------------------------------------------- universe and data (PLAN 12.1)
    S = J("results/summary.json")
    NM = J("results/v2/note_metrics.json")
    u = S["universe"]
    N.add("univ.matches", intc(u["matches"]), u["matches"], "results/summary.json::universe.matches")
    N.add("univ.volume", f"${u['volume_usd'] / 1e9:.2f}B", u["volume_usd"], "results/summary.json::universe.volume_usd")
    N.add("univ.is", intc(u["is"]), u["is"], "results/summary.json::universe.is")
    N.add("univ.oos", intc(u["oos"]), u["oos"], "results/summary.json::universe.oos")
    t0 = pd.Timestamp(u["oos_start"])
    N.add("univ.oosstart", t0.strftime("%Y-%m-%d %H:%M UTC"), u["oos_start"], "results/summary.json::universe.oos_start")
    h = NM["holdout"]
    for k, key in (("univ.first", "first_start"), ("univ.last", "last_start")):
        t = pd.Timestamp(h[key])
        N.add(k, t.strftime("%b %-d, %Y"), h[key], f"results/v2/note_metrics.json::holdout.{key}")
    N.add("univ.oos_time", pct(h["oos_share_of_time"] * 100), h["oos_share_of_time"],
          "results/v2/note_metrics.json::holdout.oos_share_of_time")
    N.add("univ.oos_vol", pct(h["oos_share_of_volume"] * 100), h["oos_share_of_volume"],
          "results/v2/note_metrics.json::holdout.oos_share_of_volume")
    N.add("univ.timesplit", pd.Timestamp(h["time_based_20pct_start"]).strftime("%b %-d"), h["time_based_20pct_start"],
          "results/v2/note_metrics.json::holdout.time_based_20pct_start")
    from src.tape import MIN_VOL  # noqa: E402
    N.add("univ.minvol", usd(MIN_VOL), MIN_VOL, src_line("src/tape.py", r"^MIN_VOL\s*="))
    g = NM["data_gaps"]
    N.add("data.offsetcap", intc(g["tapes_at_offset_cap_10500_rows"]), g["tapes_at_offset_cap_10500_rows"],
          "results/v2/note_metrics.json::data_gaps.tapes_at_offset_cap_10500_rows")
    N.add("data.nofee", intc(g["no_fee_schedule_matches"]), g["no_fee_schedule_matches"],
          "results/v2/note_metrics.json::data_gaps.no_fee_schedule_matches")
    RS = J("results/risk/risk_stats.json")
    r5 = RS["settlement"]["all"]["res_50_50_pct"]
    N.add("data.res5050", pct(r5, 2), r5, "results/risk/risk_stats.json::settlement.all.res_50_50_pct")
    DJ = J("results/decay/decay.json")
    bl = DJ["latency_inputs"]["block_lag_s"]
    N.add("data.blocklag", num(bl["median"], 2), bl["median"], "results/decay/decay.json::latency_inputs.block_lag_s.median")
    N.add("data.blocklag.n", intc(bl["n"]), bl["n"], "results/decay/decay.json::latency_inputs.block_lag_s.n")
    LV = J("results/leverage_stats.json")
    N.add("markov.points", intc(LV["atp"]["points_per_match"]), LV["atp"]["points_per_match"],
          "results/leverage_stats.json::atp.points_per_match")
    N.add("markov.lev", pct(LV["atp"]["mean_abs_leverage"] * 100), LV["atp"]["mean_abs_leverage"],
          "results/leverage_stats.json::atp.mean_abs_leverage")
    FIN = J("results/financials/financials.json")
    rate = FIN["strategies"]["v2"]["periods"]["OOS"]["breakeven_taker_fee"]["uniform_rate_charged"]
    N.add("fee.rate", pct(rate * 100, 0), rate,
          "results/financials/financials.json::strategies.v2.periods.OOS.breakeven_taker_fee.uniform_rate_charged")
    N.add("fee.bps_q05", intc(NM["fee_formula_bps_today"]["q=0.5"]), NM["fee_formula_bps_today"]["q=0.5"],
          "results/v2/note_metrics.json::fee_formula_bps_today.q=0.5")
    EX = J("results/expand/results.json")
    N.add("u2.markets", intc(EX["universe"]["u2_markets"]), EX["universe"]["u2_markets"],
          "results/expand/results.json::universe.u2_markets")
    gl = subprocess.run(["git", "log", "--diff-filter=A", "--format=%h %aI", "--", "HYPOTHESIS.md"], cwd=ROOT,
                        capture_output=True, text=True).stdout.strip().splitlines()
    if not gl:
        raise KeyError("COURTSIDE: missing number prereg.hyp.commit (git log)")
    hc, ht = gl[-1].split()
    N.add("prereg.hyp.commit", hc, hc, "git log --diff-filter=A -- HYPOTHESIS.md")
    N.add("prereg.hyp.time", pd.Timestamp(ht).tz_convert("UTC").strftime("%Y-%m-%d %H:%M UTC"), ht,
          "git log --diff-filter=A -- HYPOTHESIS.md")

    # ---------------------------------------------------------------- fast tier (12.2)
    AL = J("results/alpha/alpha.json")
    hd = AL["headline"]
    N.add("ft.months.is", hd["fast_tier_net30_c_months_positive"]["IS"], hd["fast_tier_net30_c_months_positive"]["IS"],
          "results/alpha/alpha.json::headline.fast_tier_net30_c_months_positive.IS")
    N.add("ft.months.oos", hd["fast_tier_net30_c_months_positive"]["OOS"], hd["fast_tier_net30_c_months_positive"]["OOS"],
          "results/alpha/alpha.json::headline.fast_tier_net30_c_months_positive.OOS")
    for per, P in (("is", "IS"), ("oos", "OOS")):
        N.add(f"ft.c.{per}", sgn(hd["fast_tier_net30_c_print_weighted"][P]), hd["fast_tier_net30_c_print_weighted"][P],
              f"results/alpha/alpha.json::headline.fast_tier_net30_c_print_weighted.{P}")
        N.add(f"oth.c.{per}", sgn(hd["others_net30_c_month_mean"][P]), hd["others_net30_c_month_mean"][P],
              f"results/alpha/alpha.json::headline.others_net30_c_month_mean.{P}")
        N.add(f"copy3.c.{per}", sgn(hd["copy_3s_later_c"][P]), hd["copy_3s_later_c"][P],
              f"results/alpha/alpha.json::headline.copy_3s_later_c.{P}")
    N.add("ft.wallets.first", intc(S["is"]["h6_walkforward"][0]["n_wallets"]), S["is"]["h6_walkforward"][0]["n_wallets"],
          "results/summary.json::is.h6_walkforward[0].n_wallets")
    N.add("ft.wallets.last", intc(S["oos"]["h6_walkforward"][-1]["n_wallets"]), S["oos"]["h6_walkforward"][-1]["n_wallets"],
          "results/summary.json::oos.h6_walkforward[-1].n_wallets")
    sl = hd["fast_tier_slope_c_per_month"]
    N.add("ft.slope", num(abs(sl["IS"]), 2), sl["IS"], "results/alpha/alpha.json::headline.fast_tier_slope_c_per_month.IS")
    N.add("ft.slope.t", num(sl["IS_t"], 2), sl["IS_t"], "results/alpha/alpha.json::headline.fast_tier_slope_c_per_month.IS_t")
    N.add("h4.lead", num(S["h4"]["median_lead_s"], 1), S["h4"]["median_lead_s"], "results/summary.json::h4.median_lead_s")
    N.add("h4.n", intc(S["h4"]["n"]), S["h4"]["n"], "results/summary.json::h4.n")

    # ---------------------------------------------------------------- v2 (Table 1; 12.3)
    C = J("results/v2/causal.json")
    CS = J("results/v2/cost_stress.json")
    RG = J("results/rigor/rigor.json")
    for per, P, nmk in (("is", "is_eval", "is"), ("oos", "burned_oos", "burned_oos")):
        c0 = C[f"causal/{P}/slip0.0"]
        nm = NM[nmk]
        src = f"results/v2/causal.json::causal/{P}/slip0.0"
        N.add(f"v2.{per}.trades", intc(c0["n_trades"]), c0["n_trades"], src + ".n_trades")
        N.add(f"v2.{per}.matches", intc(c0["n_matches"]), c0["n_matches"], src + ".n_matches")
        N.add(f"v2.{per}.days", intc(c0["days"]), c0["days"], src + ".days")
        N.add(f"v2.{per}.c", sgn(c0["per_share_c"]), c0["per_share_c"], src + ".per_share_c")
        N.add(f"v2.{per}.ci", ci(c0["per_share_ci_c"]), c0["per_share_ci_c"], src + ".per_share_ci_c")
        N.add(f"v2.{per}.pnl", usd(c0["total_pnl_usd"], signed=True), c0["total_pnl_usd"], src + ".total_pnl_usd")
        N.add(f"v2.{per}.mpos", f"{c0['months_positive']}/{c0['months_total']}", [c0["months_positive"], c0["months_total"]],
              src + ".{months_positive,months_total}")
        N.add(f"v2.{per}.worstday_usd", usd(c0["worst_day_usd"]), c0["worst_day_usd"], src + ".worst_day_usd")
        nsrc = f"results/v2/note_metrics.json::{nmk}"
        N.add(f"v2.{per}.net_bps", intc(nm["net_edge_bps_of_notional"]), nm["net_edge_bps_of_notional"], nsrc + ".net_edge_bps_of_notional")
        N.add(f"v2.{per}.fee_bps", intc(nm["fee_bps_of_notional"]), nm["fee_bps_of_notional"], nsrc + ".fee_bps_of_notional")
        N.add(f"v2.{per}.ret", pct(nm["ann_return_pct"], 0), nm["ann_return_pct"], nsrc + ".ann_return_pct")
        N.add(f"v2.{per}.vol", pct(nm["ann_vol_pct"], 1), nm["ann_vol_pct"], nsrc + ".ann_vol_pct")
        N.add(f"v2.{per}.sr", num(nm["sharpe_ann"], 1), nm["sharpe_ann"], nsrc + ".sharpe_ann")
        bci = RG["bootstrap"][f"v2_{per}"]["sharpe_ann_ci95"]
        N.add(f"v2.{per}.sr_ci", ci(bci, 1), bci, f"results/rigor/rigor.json::bootstrap.v2_{per}.sharpe_ann_ci95")
        N.add(f"v2.{per}.dd", pct(nm["max_dd_pct"], 1), nm["max_dd_pct"], nsrc + ".max_dd_pct")
        N.add(f"v2.{per}.worstday", pct(nm["worst_day_pct"], 1), nm["worst_day_pct"], nsrc + ".worst_day_pct")
        N.add(f"v2.{per}.skew", sgn(nm["skew"]), nm["skew"], nsrc + ".skew")
        N.add(f"v2.{per}.kurt", num(nm["kurtosis_pearson"]), nm["kurtosis_pearson"], nsrc + ".kurtosis_pearson")
        N.add(f"v2.{per}.worstmonth", usd(nm["worst_month_usd"], signed=True), nm["worst_month_usd"], nsrc + ".worst_month_usd")
        N.add(f"v2.{per}.turnover", intc(nm["turnover_x_per_year"]), nm["turnover_x_per_year"], nsrc + ".turnover_x_per_year")
        N.add(f"v2.{per}.cap", usd(nm["capital_usd"]), nm["capital_usd"], nsrc + ".capital_usd")
        for slip, k in (("0.005", "slip05"), ("0.01", "slip10")):
            v = C[f"causal/{P}/slip{slip}"]["per_share_c"]
            N.add(f"v2.{per}.{k}", sgn(v), v, f"results/v2/causal.json::causal/{P}/slip{slip}.per_share_c")
        for sc, k in (("fee_x2", "fx2"), ("costs_x2", "cx2")):
            d = CS[f"{P}/{sc}"]
            s2 = f"results/v2/cost_stress.json::{P}/{sc}"
            N.add(f"v2.{per}.{k}.c", sgn(d["per_share_c"]), d["per_share_c"], s2 + ".per_share_c")
            N.add(f"v2.{per}.{k}.ci", ci(d["per_share_ci_c"]), d["per_share_ci_c"], s2 + ".per_share_ci_c")
            N.add(f"v2.{per}.{k}.mpos", f"{d['months_positive']}/{d['months_total']}", [d["months_positive"], d["months_total"]],
                  s2 + ".{months_positive,months_total}")
            N.add(f"v2.{per}.{k}.usd", usd(d["total_pnl_usd"], signed=True), d["total_pnl_usd"], s2 + ".total_pnl_usd")
    dly = pd.read_csv(ROOT / "results/lowloss/daily.csv")
    dly = dly[(dly.run == "a") & (dly.policy == "v2")]
    for per, book in (("is", "u1_is"), ("oos", "u1_oos")):
        dd_ = pd.to_datetime(dly[dly.book == book].date)
        N.add(f"v2.{per}.start", dd_.min().strftime("%b %-d"), str(dd_.min().date()), f"results/lowloss/daily.csv[a,{book},v2].date.min")
        N.add(f"v2.{per}.end", dd_.max().strftime("%b %-d"), str(dd_.max().date()), f"results/lowloss/daily.csv[a,{book},v2].date.max")
    N.add("v2.is.hs_bps", intc(NM["is"]["half_spread_0.5c_bps_of_notional"]), NM["is"]["half_spread_0.5c_bps_of_notional"],
          "results/v2/note_metrics.json::is.half_spread_0.5c_bps_of_notional")
    N.add("v2.is.notional_day", usd(NM["is"]["usd_traded_per_day"]), NM["is"]["usd_traded_per_day"],
          "results/v2/note_metrics.json::is.usd_traded_per_day")
    N.add("v2.is.share_vol", pct(NM["is"]["v2_usd_traded_share_of_match_volume"] * 100, 2),
          NM["is"]["v2_usd_traded_share_of_match_volume"], "results/v2/note_metrics.json::is.v2_usd_traded_share_of_match_volume")
    tpd = C["causal/is_eval/slip0.0"]["n_trades"] / C["causal/is_eval/slip0.0"]["days"]
    N.add("v2.trades_per_day", intc(tpd), tpd, "D: causal.json is_eval n_trades / days")
    PM = J("results/financials/pm_compute.json")
    wc = PM["p07_wallet_clustered_ci"]["burned_oos"]["ci95_c_wallet_clustered"]
    N.add("v2.oos.ci_wallet", ci(wc), wc,
          "results/financials/pm_compute.json::p07_wallet_clustered_ci.burned_oos.ci95_c_wallet_clustered")
    on = C["onset/is_eval/slip0.0"]["sharpe_ann"]
    N.add("v2.onset.is.sr", num(on, 1), on, "results/v2/causal.json::onset/is_eval/slip0.0.sharpe_ann")
    for k, r in (("3s0", "3s/0%"), ("3s3", "3s/3%"), ("1s3", "1s/3%"), ("1s5", "1s/5%")):
        v = RS["regime"]["is_eval"][r]["per_share_c"]
        N.add(f"v2.reg.{k}", sgn(v), v, f"results/risk/risk_stats.json::regime.is_eval.{r}.per_share_c")
    au = J("results/decay/audit_sameblock.json")["v2_backtest_trades"]["IS+burned_OOS"]
    sh = au["same_block"]["pnl_usd"] / au["all_matched"]["pnl_usd"]
    N.add("decay.sameblock.share", pct(sh * 100, 0), sh,
          "D: results/decay/audit_sameblock.json::v2_backtest_trades.IS+burned_OOS same_block.pnl_usd / all_matched.pnl_usd")
    for per, P in (("is", "IS"), ("oos", "OOS")):
        v = hd["top5_wallet_share_of_pnl"][P]
        N.add(f"conc.top5.{per}", pct(v * 100, 0), v, f"results/alpha/alpha.json::headline.top5_wallet_share_of_pnl.{P}")
    cr = RS["correlation"]["is_eval"]["implied_mean_pairwise_corr_same_day"]
    N.add("risk.corr_sameday", f"{cr:.4f}", cr, "results/risk/risk_stats.json::correlation.is_eval.implied_mean_pairwise_corr_same_day")

    # ---------------------------------------------------------------- rigor and factor (12.4)
    NN = RG["psr_dsr"]["N"]
    N.add("rig.N", intc(NN["all_plus_v2safe_grid"]), NN["all_plus_v2safe_grid"], "results/rigor/rigor.json::psr_dsr.N.all_plus_v2safe_grid")
    N.add("rig.N3386", intc(NN["all_NOTE_s8"]), NN["all_NOTE_s8"], "results/rigor/rigor.json::psr_dsr.N.all_NOTE_s8")
    N.add("rig.N44", intc(NN["H1_H6"]), NN["H1_H6"], "results/rigor/rigor.json::psr_dsr.N.H1_H6")
    rows = {r["series"]: r for r in RG["psr_dsr"]["rows"]}
    d_is = rows["v2_is"]["dsr"]["N3386/sizing_grid_55"]["dsr"]
    N.add("rig.dsr.is", f"{d_is:.3f}", d_is, "results/rigor/rigor.json::psr_dsr.rows[v2_is].dsr.N3386/sizing_grid_55.dsr")
    rr = hd["v2_oos_dsr_N3386_range"]
    N.add("rig.dsr.oos", f"{rr[0]:.3f}\u2013{rr[1]:.3f}", rr, "results/alpha/alpha.json::headline.v2_oos_dsr_N3386_range")
    pb = RG["pbo_cscv"]
    N.add("rig.pbo.lowloss", pct(pb["lowloss_24_sharpe"]["pbo"] * 100, 0), pb["lowloss_24_sharpe"]["pbo"],
          "results/rigor/rigor.json::pbo_cscv.lowloss_24_sharpe.pbo")
    N.add("rig.boot.p", f"{RG['bootstrap']['v2_oos']['p_sharpe_le_0']:.4f}", RG["bootstrap"]["v2_oos"]["p_sharpe_le_0"],
          "results/rigor/rigor.json::bootstrap.v2_oos.p_sharpe_le_0")
    fc = AL["C_factor_neutral"]["IS_committed_spec"]
    N.add("fac.alpha_t", num(fc["alpha_t"]), fc["alpha_t"], "results/alpha/alpha.json::C_factor_neutral.IS_committed_spec.alpha_t")
    N.add("fac.max_t", num(fc["max_abs_factor_t"]), fc["max_abs_factor_t"], "results/alpha/alpha.json::C_factor_neutral.IS_committed_spec.max_abs_factor_t")
    N.add("fac.r2", pct(fc["r2"] * 100, 1), fc["r2"], "results/alpha/alpha.json::C_factor_neutral.IS_committed_spec.r2")
    N.add("fac.n", intc(fc["n_days"]), fc["n_days"], "results/alpha/alpha.json::C_factor_neutral.IS_committed_spec.n_days")
    extra["factor"] = AL["C_factor_neutral"]

    # ---------------------------------------------------------------- CV, vision, engine (12.5)
    TR = J("results/tracking/summary.json")
    nf = TR["n_flights"]["test"]
    N.add("cv.tt.n_miss", intc(nf["MISS"]), nf["MISS"], "results/tracking/summary.json::n_flights.test.MISS")
    N.add("cv.tt.n_bounce", intc(nf["BOUNCE"]), nf["BOUNCE"], "results/tracking/summary.json::n_flights.test.BOUNCE")
    s50 = TR["early_call"]["precision_recall_test_snapshot"]["50ms"]
    N.add("cv.tt.tp50", intc(s50["tp"]), s50["tp"], "results/tracking/summary.json::early_call.precision_recall_test_snapshot.50ms.tp")
    N.add("cv.tt.called50", intc(s50["tp"] + s50["fp"]), s50["tp"] + s50["fp"], "D: tp + fp at 50 ms (snapshot rule)")
    N.add("cv.tt.rec50", pct(s50["recall"] * 100, 0), s50["recall"], "results/tracking/summary.json::early_call.precision_recall_test_snapshot.50ms.recall")
    N.add("cv.tt.wil50", ci(s50["precision_wilson95"]), s50["precision_wilson95"],
          "results/tracking/summary.json::early_call.precision_recall_test_snapshot.50ms.precision_wilson95")
    det = next(r for r in TR["detection_accuracy_pooled"] if r["split"] == "test" and r["source"] == "tracked")
    N.add("cv.tt.det_recall", pct(det["recall"] * 100, 1), det["recall"], "results/tracking/summary.json::detection_accuracy_pooled[test,tracked].recall")
    OV = J("results/engine/online_vs_offline.json")["headline"]["fp16_cl_fuse_compile_b1_realtime"]["stream"]
    N.add("cv.eng.fps", num(OV["fps"], 1), OV["fps"], "results/engine/online_vs_offline.json::headline.fp16_cl_fuse_compile_b1_realtime.stream.fps")
    N.add("cv.eng.dropped", intc(OV["dropped"]), OV["dropped"], "…stream.dropped")
    N.add("cv.eng.frames", intc(OV["frames"]), OV["frames"], "…stream.frames")
    cr_ms = OV["after_startup"]["call_ready_ms"]
    N.add("cv.eng.p50", num(cr_ms["p50"], 1), cr_ms["p50"], "…stream.after_startup.call_ready_ms.p50")
    N.add("cv.eng.p99", num(cr_ms["p99"], 1), cr_ms["p99"], "…stream.after_startup.call_ready_ms.p99")
    VB = J("results/engine/vision_bench.json")
    N.add("cv.laptop.fps", num(VB["summary"][0]["fps_sustained"], 1), VB["summary"][0]["fps_sustained"],
          "results/engine/vision_bench.json::summary[0].fps_sustained")
    SP = J("results/spin/tennis/key_numbers.json")
    N.add("cv.spin.bls200", num(SP["bls"]["sd_cm"]["200"]), SP["bls"]["sd_cm"]["200"], "results/spin/tennis/key_numbers.json::bls.sd_cm.200")
    N.add("cv.spin.base200", num(SP["baseline"]["sd_cm"]["200"]), SP["baseline"]["sd_cm"]["200"],
          "results/spin/tennis/key_numbers.json::baseline.sd_cm.200")
    li = DJ["latency_inputs"]
    N.add("cv.inf", intc(li["cv_assumed_s"] * 1000), li["cv_assumed_s"], "results/decay/decay.json::latency_inputs.cv_assumed_s")
    from paper_figures import webrtc_latency, public_stream_s  # noqa: E402
    wr = webrtc_latency()
    if wr:
        N.add("cv.webrtc", f"{num(wr['p50'], 0)} ms p50, {num(wr['p99'], 0)} ms p99", wr,
              f"results/webrtc/latency.json::{wr['key']}.{{p50,p99}}")
        N.add("cv.webrtc.n", intc(wr["n"]) if wr.get("n") else "n/a", wr.get("n"), f"results/webrtc/latency.json::{wr['key']}.n")
    else:
        N.add("cv.webrtc", "pending", None, "results/webrtc/latency.json (absent at build time)")
        N.add("cv.webrtc.n", "n/a", None, "results/webrtc/latency.json (absent at build time)")

    # ---------------------------------------------------------------- latency ladder (12.6)
    LT = J("research/v2/latency/results.json")["summary"]
    m1 = LT["m1"]
    b = m1["book_vs_official_T_s"]
    N.add("lat.book_vs_stamp", num(-b["median"], 1), b["median"], "research/v2/latency/results.json::summary.m1.book_vs_official_T_s.median")
    N.add("lat.book_vs_stamp_signed", num(b["median"], 2), b["median"], "research/v2/latency/results.json::summary.m1.book_vs_official_T_s.median")
    N.add("lat.n_points", intc(b["n"]), b["n"], "research/v2/latency/results.json::summary.m1.book_vs_official_T_s.n")
    for k, s in (("espn", "espn:game"), ("pmsports", "pm_sports:game"), ("wta", "wta:point")):
        v = -m1[s]["lead_vs_book_s"]["median"]
        N.add(f"lat.{k}", num(v, 1), v, f"research/v2/latency/results.json::summary.m1.{s}.lead_vs_book_s.median (negated)")
    pub = public_stream_s()
    if pub is None:
        raise KeyError("COURTSIDE: missing number lat.webrtc_public")
    N.add("lat.webrtc_public", num(pub, 1), pub, "results/home_stream/sub_second_routes.json::bottom_line.why_not_match (regex 'median ([0-9.]+) s')")
    N.add("lat.net_fl", intc(li["net_florida_s"] * 1000), li["net_florida_s"], "results/decay/decay.json::latency_inputs.net_florida_s")
    N.add("lat.net_ldn", intc(li["net_london_s"] * 1000), li["net_london_s"], "results/decay/decay.json::latency_inputs.net_london_s")
    LM = J("results/engine/live_market_run.json")
    N.add("lat.feed_p50", intc(LM["feed"]["latency"]["p50_ms"]), LM["feed"]["latency"]["p50_ms"],
          "results/engine/live_market_run.json::feed.latency.p50_ms")
    SW = J("results/tier0/latency_sweep.json")
    mm = re.search(r"order delay \(([0-9.]+) s\)", SW["model"]["video"])
    N.add("venue.delay", f"{float(mm.group(1)):g}", float(mm.group(1)), "results/tier0/latency_sweep.json::model.video (regex 'order delay (x s)')")
    bv = next(s for s in SW["sources"] if s["key"] == "betting_video")["band_s"]
    N.add("lat.video_band", f"{bv[0]:g}\u2013{bv[1]:g}", bv, "results/tier0/latency_sweep.json::sources[betting_video].band_s")
    lag = SW["grids"]["stamp_lag_s"]
    N.add("lat.stamp_band", f"{min(lag):g}\u2013{max(lag):g}", lag, "results/tier0/latency_sweep.json::grids.stamp_lag_s")

    # ---------------------------------------------------------------- CV strategy at the 1 s baseline (12.7, Table 2)
    df = pd.read_csv(ROOT / "results/tier0/latency_sweep.csv")
    df = df[(df.source == "video") & (df.cv == "own120")]
    # order: the pre-registered reading (cv.pre.*) first, then the post hoc estimate (cv.cal.*)
    # (research/compliance/PAPER_REQUIREMENTS.md, addendum after the red team)
    N.add("cv.pre.lag", num(SW["model"]["revised_primary"]["stamp_lag"], 1), SW["model"]["revised_primary"]["stamp_lag"],
          "results/tier0/latency_sweep.json::model.revised_primary.stamp_lag")
    mcal = re.search(r"([0-9.]+) s", SW["grids"]["video_stamp_lag_sensitivity"]["tournament_lagcal"])
    N.add("cv.cal.lag", mcal.group(1), float(mcal.group(1)),
          "results/tier0/latency_sweep.json::grids.video_stamp_lag_sensitivity.tournament_lagcal (regex)")
    for rk, reading in (("pre", "tournament"), ("cal", "tournament_lagcal")):
        for per, P in (("is", "IS"), ("oos", "burned_OOS")):
            c = SW["video_own120"][reading]["1"][P]
            s0 = f"results/tier0/latency_sweep.json::video_own120.{reading}.1.{P}"
            N.add(f"cv.{rk}.{per}.usd", usd(c["usd_per_day"], signed=True), c["usd_per_day"], s0 + ".usd_per_day")
            N.add(f"cv.{rk}.{per}.usd_ci", "[" + ", ".join(m(f"{x:.0f}") for x in c["usd_per_day_seed_ci95"]) + "]",
                  c["usd_per_day_seed_ci95"], s0 + ".usd_per_day_seed_ci95")
            N.add(f"cv.{rk}.{per}.c", sgn(c["net_c_per_share"]), c["net_c_per_share"], s0 + ".net_c_per_share")
            N.add(f"cv.{rk}.{per}.c_ci", ci(c["net_c_per_share_ci95"]), c["net_c_per_share_ci95"], s0 + ".net_c_per_share_ci95")
            N.add(f"cv.{rk}.{per}.sr", num(c["sharpe_ann"], 1), c["sharpe_ann"], s0 + ".sharpe_ann")
            N.add(f"cv.{rk}.{per}.wrong", pct(c["wrong_call_share_of_trades"] * 100, 0), c["wrong_call_share_of_trades"],
                  s0 + ".wrong_call_share_of_trades")
            row = df[(df.reading == reading) & (df.period == P) & (np.isclose(df.x_s, 1.0))].iloc[0]
            # D: annualised return = mean $/day x 365 / capital; vol = return / Sharpe (ratio of 20-seed means)
            ret = row.pnl_per_day_usd * 365 / row.capital_usd * 100
            vol = ret / row.sharpe_ann if row.sharpe_ann else float("nan")
            csrc = f"results/tier0/latency_sweep.csv[video,own120,{reading},{P},x_s=1]"
            N.add(f"cv.{rk}.{per}.ret", num(ret, 0), ret, "D: " + csrc + " pnl_per_day_usd*365/capital_usd")
            N.add(f"cv.{rk}.{per}.vol", num(vol, 1), vol, "D: " + csrc + " ret/sharpe_ann")
            N.add(f"cv.{rk}.{per}.dd", num(row.max_dd_usd / row.capital_usd * 100, 1), row.max_dd_usd / row.capital_usd,
                  csrc + " max_dd_usd/capital_usd")
            N.add(f"cv.{rk}.{per}.worstday", usd(row.worst_day_usd), row.worst_day_usd, csrc + " worst_day_usd")
            N.add(f"cv.{rk}.{per}.tpd", intc(row.n_trades / row.days), row.n_trades / row.days, csrc + " n_trades/days")
            N.add(f"cv.{rk}.{per}.days", intc(row.days), row.days, csrc + " days")
            be = SW["breakeven_video_delay"][reading][P]
            N.add(f"cv.{rk}.be.{per}", num(be["breakeven_V_s_seed_mean_curve"], 2), be["breakeven_V_s_seed_mean_curve"],
                  f"results/tier0/latency_sweep.json::breakeven_video_delay.{reading}.{P}.breakeven_V_s_seed_mean_curve")
            N.add(f"cv.{rk}.be_ci.{per}", ci(be["breakeven_V_s_seed_bootstrap_ci95"]), be["breakeven_V_s_seed_bootstrap_ci95"],
                  f"results/tier0/latency_sweep.json::breakeven_video_delay.{reading}.{P}.breakeven_V_s_seed_bootstrap_ci95")
            # consistency: the CSV cell equals the JSON cell
            assert abs(row.pnl_per_day_usd - c["usd_per_day"]) < 0.01, (reading, P, row.pnl_per_day_usd, c["usd_per_day"])
        # short break-even ranges, one decimal (abstract, box)
        lo_be = min(N.raw(f"cv.{rk}.be.is"), N.raw(f"cv.{rk}.be.oos"))
        hi_be = max(N.raw(f"cv.{rk}.be.is"), N.raw(f"cv.{rk}.be.oos"))
        N.add(f"cv.{rk}.be.range", f"{lo_be:.1f}\u2013{hi_be:.1f}", [lo_be, hi_be], "D: min/max of the IS and OOS break-evens")
    for per, P in (("is", "IS"), ("oos", "burned_OOS")):
        v = SW["video_own120"]["tournament_lag1"]["1"][P]["usd_per_day"]
        N.add(f"cv.lag1.{per}.usd", usd(v, signed=True), v, f"results/tier0/latency_sweep.json::video_own120.tournament_lag1.1.{P}.usd_per_day")
        v3 = SW["video_own120"]["stamp"]["1"][P]["usd_per_day"]
        N.add(f"cv.stamp.{per}.usd", usd(v3, signed=True), v3, f"results/tier0/latency_sweep.json::video_own120.stamp.1.{P}.usd_per_day")
    cbs = N.raw("cv.pre.lag") - N.raw("cv.pre.be.is") - li["cv_assumed_s"]
    N.add("cv.call_before_stamp", num(cbs, 2), cbs, "D: cv.pre.lag - cv.pre.be.is - cv.inf")
    fixed = FIN["strategies"]["v2"]["cost"]["daily"]
    for rk in ("pre", "cal"):
        v = N.raw(f"cv.{rk}.oos.usd") - fixed["central"]
        N.add(f"cv.{rk}.oos.net_central", usd(v, signed=True), v,
              "D: cv.<r>.oos.usd - results/financials/financials.json::strategies.v2.cost.daily.central")
    chk = SW["check_V0_equals_published_headline"]
    assert chk["IS"]["identical"] and chk["burned_OOS"]["identical"], "V = 0 check failed"
    N.add("cv.v0.check", "identical", True, "results/tier0/latency_sweep.json::check_V0_equals_published_headline")
    N.add("cv.seeds", intc(SW["grids"]["seeds"]), SW["grids"]["seeds"], "results/tier0/latency_sweep.json::grids.seeds")
    N.add("cv.runs", intc(SW["run"]["n_runs"]), SW["run"]["n_runs"], "results/tier0/latency_sweep.json::run.n_runs")
    extra["sweep"] = SW

    # ---------------------------------------------------------------- the 1 s cell under the red team's readings
    # (PAPER_REQUIREMENTS.md addendum; results/redteam/ derives these from committed files, no new evaluation)
    RD = J("results/redteam/derived.json")["keys"]

    def dk(key):
        return RD[key]["value"]

    def dsrc(key):
        return f"results/redteam/derived.json::keys.{key} <- {RD[key]['source']}"
    SL = J("results/redteam/stamp_lag.json")
    lo_, hi_ = SL["bootstrap"]["median_L_ci95_s"]
    N.add("cv.cal.lag_ci", f"{lo_:.2f}\u2013{hi_:.2f}", [lo_, hi_], "results/redteam/stamp_lag.json::bootstrap.median_L_ci95_s")
    base_l = SL["base"]["stamp_lag_median_s"]
    rt = next(r for r in SL["reaction_time"] if abs(r["stamp_lag_median_s"] - base_l) < 1e-9)
    N.add("cv.cal.react", f"{rt['react_s']:g}", rt["react_s"],
          "results/redteam/stamp_lag.json::reaction_time[stamp_lag_median_s == base.stamp_lag_median_s].react_s")
    N.add("cv.cal.n", intc(SL["base"]["n_points"]), SL["base"]["n_points"], "results/redteam/stamp_lag.json::base.n_points")
    N.add("cv.L_bot", num(dk("cv.L_bot"), 2), dk("cv.L_bot"), dsrc("cv.L_bot"))
    for per in ("is", "oos"):
        N.add(f"cv.at_lo.{per}.usd", usd(dk(f"cv.at_L_boot_lo.{per}.usd"), signed=True), dk(f"cv.at_L_boot_lo.{per}.usd"),
              dsrc(f"cv.at_L_boot_lo.{per}.usd"))
    N.add("cv.cal.shift", num(dk("cv.cal.shift"), 2), dk("cv.cal.shift"), dsrc("cv.cal.shift"))
    # per point: the same post hoc inference applied point by point (stamp_calibrated); stamp noise at L = 2.0 (stamp)
    for per, P in (("is", "IS"), ("oos", "burned_OOS")):
        sc_ = SW["video_own120"]["stamp_calibrated"]
        s0 = f"results/tier0/latency_sweep.json::video_own120.stamp_calibrated"
        N.add(f"cv.stc.{per}.usd", usd(sc_["1"][P]["usd_per_day"], signed=True), sc_["1"][P]["usd_per_day"], f"{s0}.1.{P}.usd_per_day")
        N.add(f"cv.stc.{per}.v0", usd(sc_["0"][P]["usd_per_day"], signed=True), sc_["0"][P]["usd_per_day"], f"{s0}.0.{P}.usd_per_day")
        b_ = SW["breakeven_video_delay"]["stamp_calibrated"][P]["breakeven_V_s_seed_mean_curve"]
        N.add(f"cv.stc.be.{per}", num(b_, 2), b_,
              f"results/tier0/latency_sweep.json::breakeven_video_delay.stamp_calibrated.{P}.breakeven_V_s_seed_mean_curve")
    # live causal engine's own calls at V = 1 (results/redteam/causal_cv.json; same sweep, CV table swapped)
    CC = J("results/redteam/causal_cv.json")
    for rk, reading in (("pre", "tournament"), ("cal", "tournament_lagcal")):
        for per, P in (("is", "IS"), ("oos", "burned_OOS")):
            v = CC["cells_V1"][reading][P]["usd_per_day"]
            N.add(f"cv.eng.{rk}.{per}.usd", usd(v, signed=True), v, f"results/redteam/causal_cv.json::cells_V1.{reading}.{P}.usd_per_day")
    N.add("cv.eng.tp", intc(dk("eng.tp")), dk("eng.tp"), dsrc("eng.tp"))
    N.add("cv.eng.nmiss", intc(dk("eng.nmiss")), dk("eng.nmiss"), dsrc("eng.nmiss"))
    N.add("cv.eng.wil_lo", f"{dk('eng.wil_lo'):.0f}%", dk("eng.wil_lo"), dsrc("eng.wil_lo"))
    N.add("cv.eng.lead", num(dk("eng.lead_med"), 0), dk("eng.lead_med"), dsrc("eng.lead_med"))
    N.add("cv.phantom.hr", num(dk("eng.phantom_miss_per_hour"), 0), dk("eng.phantom_miss_per_hour"), dsrc("eng.phantom_miss_per_hour"))
    N.add("cv.phantom.pre", num(dk("eng.phantom_budget_per_day.pre"), 1), dk("eng.phantom_budget_per_day.pre"),
          dsrc("eng.phantom_budget_per_day.pre"))
    N.add("cv.phantom.cal", num(dk("eng.phantom_budget_per_day.cal"), 0), dk("eng.phantom_budget_per_day.cal"),
          dsrc("eng.phantom_budget_per_day.cal"))
    # wrong calls, the value of a second, pessimistic CV (sweep CSV / JSON at V = 1)
    for rk, reading in (("pre", "tournament"), ("cal", "tournament_lagcal")):
        for per, P in (("is", "IS"), ("oos", "burned_OOS")):
            row = df[(df.reading == reading) & (df.period == P) & (np.isclose(df.x_s, 1.0))].iloc[0]
            csrc = f"results/tier0/latency_sweep.csv[video,own120,{reading},{P},x_s=1]"
            N.add(f"cv.{rk}.{per}.wrong_usd", usd(row.pnl_wrong_usd), row.pnl_wrong_usd, csrc + " pnl_wrong_usd")
            N.add(f"cv.{rk}.{per}.cap", usd(row.capital_usd), row.capital_usd, csrc + " capital_usd")
            v0 = SW["video_own120"][reading]["0"][P]["usd_per_day"]
            v1 = SW["video_own120"][reading]["1"][P]["usd_per_day"]
            N.add(f"cv.{rk}.{per}.persec", usd(v0 - v1, signed=True), v0 - v1,
                  f"D: latency_sweep.json::video_own120.{reading}.0.{P}.usd_per_day - .1.{P}.usd_per_day")
    pv = [N.raw(f"cv.pre.{p}.persec") for p in ("is", "oos")]
    N.add("cv.pre.persec.range", f"${min(pv):,.0f}\u2013{max(pv):,.0f}", pv, "D: min/max of cv.pre.{is,oos}.persec")
    for per, P in (("is", "IS"), ("oos", "burned_OOS")):
        v = SW["video_cv_pessimistic"]["tournament"]["1"][P]["usd_per_day"]
        N.add(f"cv.pess.{per}.usd", usd(v, signed=True), v, f"results/tier0/latency_sweep.json::video_cv_pessimistic.tournament.1.{P}.usd_per_day")
    T0R = J("results/tier0/results.json")
    lp = T0R["inputs"]["live_pool_sizes"]
    N.add("cv.pool.d3", intc(lp["D>=3c"]), lp["D>=3c"], "results/tier0/results.json::inputs.live_pool_sizes.D>=3c")
    N.add("cv.pool.all", intc(lp["all"]), lp["all"], "results/tier0/results.json::inputs.live_pool_sizes.all")
    N.add("cv.pool482.oos", f"{sgn(dk('cv.pool482.oos.c'))} {ci(dk('cv.pool482.oos.ci'))}", [dk("cv.pool482.oos.c"), dk("cv.pool482.oos.ci")],
          dsrc("cv.pool482.oos.c") + " ; " + dsrc("cv.pool482.oos.ci"))
    # business case (derived.json): most the 10-match book can pay for data; stamp lag needed for the cheapest stack
    for rk in ("pre", "cal"):
        N.add(f"cv.{rk}.oos.maxlic", usd(dk(f"cv.{rk}.oos.maxlic")), dk(f"cv.{rk}.oos.maxlic"), dsrc(f"cv.{rk}.oos.maxlic"))
    lfl = [dk("cv.L_for_low.is"), dk("cv.L_for_low.oos")]
    N.add("cv.L_go", f"{max(lfl):.1f}", max(lfl), dsrc("cv.L_for_low.is") + " ; " + dsrc("cv.L_for_low.oos") + " (max of IS and OOS, 1 dp: the stricter)")
    N.add("cv.L_go.range", f"{lfl[0]:.2f}\u2013{lfl[1]:.2f}", lfl, dsrc("cv.L_for_low.is") + " ; " + dsrc("cv.L_for_low.oos"))
    lc_ = [str(dk("cv.L_for_central.is")), str(dk("cv.L_for_central.oos"))]
    mlc = [re.fullmatch(r"not covered at any L <= ([0-9.]+)", x) for x in lc_]
    if not all(mlc):  # the text says "covered at no L <= x"; a covered value would need a different sentence
        raise KeyError(f"COURTSIDE: cv.L_for_central changed: {lc_}")
    N.add("cv.L_central", mlc[0].group(1), lc_, dsrc("cv.L_for_central.is") + " ; " + dsrc("cv.L_for_central.oos"))
    vb = dk("venue.reprices_0_100ms_after_second")
    N.add("venue.batch", pct(vb * 100, 0), vb, dsrc("venue.reprices_0_100ms_after_second"))
    # end-to-end timing proof (paper; no order sent): results/e2e/summary.json
    E2 = J("results/e2e/summary.json")
    N.add("e2e.ours", num(E2["our_pipeline_frame_to_order_ready_ms"]["p50"], 0), E2["our_pipeline_frame_to_order_ready_ms"]["p50"],
          "results/e2e/summary.json::our_pipeline_frame_to_order_ready_ms.p50")
    tt_ = E2["budget_with_1s_simulated_feed"]["total_ms"]["p50"]
    N.add("e2e.total", intc(tt_), tt_, "results/e2e/summary.json::budget_with_1s_simulated_feed.total_ms.p50")
    N.add("e2e.n", intc(E2["counts"]["complete_order_traces"]), E2["counts"]["complete_order_traces"],
          "results/e2e/summary.json::counts.complete_order_traces")
    N.add("e2e.sent", intc(E2["counts"]["orders_sent"]), E2["counts"]["orders_sent"], "results/e2e/summary.json::counts.orders_sent")
    # capacity of the CV book (results/capacity/capacity.json; 10 covered matches a day, phi 0.5, growth 1)
    CAPA = J("results/capacity/capacity.json")["answers"]["cv"]
    for per, P in (("is", "IS"), ("oos", "burned_OOS")):
        for cov, k in (("cov10", "half"), ("covall", "halfall")):
            h_ = CAPA[f"lagcal|phi0.5|{cov}|g1|{P}"]["at_half_sharpe"]
            s0 = f"results/capacity/capacity.json::answers.cv.lagcal|phi0.5|{cov}|g1|{P}.at_half_sharpe"
            N.add(f"capcv.{k}.{per}", usd(round(h_["capital_usd"], -3)), h_["capital_usd"], s0 + ".capital_usd")
            N.add(f"capcv.{k}.{per}.day", usd(h_["pnl_per_day_usd"]), h_["pnl_per_day_usd"], s0 + ".pnl_per_day_usd")
        sr0 = CAPA[f"prereg|phi0.5|cov10|g1|{P}"]["sharpe_ref_smallest_size"]
        N.add(f"capcv.pre.sr0.{per}", num(sr0, 1), sr0, f"results/capacity/capacity.json::answers.cv.prereg|phi0.5|cov10|g1|{P}.sharpe_ref_smallest_size")
        cf = CAPA[f"lagcal|phi0.5|covall|g1|{P}"]["fixed_costs"]["camera_free_central"]
        s0 = f"results/capacity/capacity.json::answers.cv.lagcal|phi0.5|covall|g1|{P}.fixed_costs.camera_free_central"
        N.add(f"capcv.cf.{per}", usd(round(cf["capital_needed_usd"], -3)), cf["capital_needed_usd"], s0 + ".capital_needed_usd")
        N.add(f"capcv.cf.{per}.cost", usd(cf["cost_usd_per_day"]), cf["cost_usd_per_day"], s0 + ".cost_usd_per_day")
    adv = CAPA["lagcal|phi0.5|cov10|g1|IS"]["at_half_sharpe"]["last_cell_above"]
    s0 = "results/capacity/capacity.json::answers.cv.lagcal|phi0.5|cov10|g1|IS.at_half_sharpe.last_cell_above"
    N.add("capcv.share_inplay", pct(adv["share_of_inplay_volume_pct"], 2), adv["share_of_inplay_volume_pct"], s0 + ".share_of_inplay_volume_pct")
    N.add("capcv.share_fast", pct(adv["share_of_fasttier_03s_volume_pct"], 0), adv["share_of_fasttier_03s_volume_pct"],
          s0 + ".share_of_fasttier_03s_volume_pct")
    # pre-registration trail of the tier-0 (CV) simulation
    pre_t0 = (ROOT / "research/v2/tier0/PREREG.md").read_text()
    mw = re.search(r"Written (\d{4}-\d\d-\d\d) (\d\d:\d\d) UTC", pre_t0)
    N.add("t0.prereg.written", mw.group(2), f"{mw.group(1)} {mw.group(2)}", "research/v2/tier0/PREREG.md (line 'Written ... UTC')")
    gl0 = subprocess.run(["git", "log", "--diff-filter=A", "--format=%h %aI", "--", "research/v2/tier0/PREREG.md"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip().splitlines()
    c0_, t0_ = gl0[-1].split()
    N.add("t0.prereg.commit", c0_, c0_, "git log --diff-filter=A -- research/v2/tier0/PREREG.md")
    N.add("t0.prereg.time", pd.Timestamp(t0_).tz_convert("UTC").strftime("%H:%M"), t0_, "git log --diff-filter=A -- research/v2/tier0/PREREG.md")
    pk = next(ln for ln in (ROOT / "results/oos_peeks.log").read_text().splitlines()
              if re.search(r"tier0 counterfactual grid evaluated on burned OOS", ln))
    N.add("t0.oos_first", pd.Timestamp(pk.split()[0]).strftime("%H:%M"), pk.split()[0],
          "results/oos_peeks.log (first line 'tier0 counterfactual grid evaluated on burned OOS')")
    dev0 = (ROOT / "research/v2/tier0/DEVIATIONS.md").read_text()
    n_t = len(re.findall(r"^### T\d+\.", dev0, re.M))
    n_v = len(re.findall(r"^### V\d+\.", dev0, re.M))
    N.add("t0.dev.n", intc(n_t + n_v), n_t + n_v, "D: count of '### T<n>.' and '### V<n>.' headings in research/v2/tier0/DEVIATIONS.md")
    N.add("t0.dev.span", f"T1\u2013T{n_t}, V1\u2013V{n_v}", [n_t, n_v], "research/v2/tier0/DEVIATIONS.md headings")

    # ---------------------------------------------------------------- market-side decay (12.8)
    sub = DJ["tennis"]["subsets"]
    for k, s in (("oos", "burned_OOS"), ("pool", "IS+burned_OOS")):
        t = sub[s]["decay_test"]
        N.add(f"decay.test.{k}", f"{sgn(t['stat_c'])} {ci(t['ci_c'])}", t, f"results/decay/decay.json::tennis.subsets.{s}.decay_test")
    N.add("decay.prints", f"{DJ['tennis']['meta']['prints'] / 1e6:.2f}M", DJ["tennis"]["meta"]["prints"], "results/decay/decay.json::tennis.meta.prints")
    N.add("decay.detections", intc(DJ["tennis"]["meta"]["detections"]), DJ["tennis"]["meta"]["detections"],
          "results/decay/decay.json::tennis.meta.detections")
    for who in ("fast", "others"):
        for per, s in (("is", "IS"), ("oos", "burned_OOS")):
            v = sub[s]["curves"][who]["net30"]["0-0.25"]["mean_c"]
            N.add(f"decay.{who}.0.{per}", sgn(v), v, f"results/decay/decay.json::tennis.subsets.{s}.curves.{who}.net30.0-0.25.mean_c")

    # ---------------------------------------------------------------- replay (12.9)
    RP = J("results/replay/replay.json")
    a = RP["cells"]["V1|lag2|lead_model|florida"]["all"]
    s0 = "results/replay/replay.json::cells.V1|lag2|lead_model|florida.all"
    N.add("rp.v1l2.c", sgn(a["per_share_mark_c"]), a["per_share_mark_c"], s0 + ".per_share_mark_c")
    N.add("rp.v1l2.ci", ci(a["per_share_mark_ci95_c"]), a["per_share_mark_ci95_c"], s0 + ".per_share_mark_ci95_c")
    N.add("rp.v1l2.usd_mark", usd(a["pnl_mark_usd"], signed=True), a["pnl_mark_usd"], s0 + ".pnl_mark_usd")
    N.add("rp.beat", intc(a["calls_beat_book"]), a["calls_beat_book"], s0 + ".calls_beat_book")
    N.add("rp.of", intc(a["calls_with_reprice"]), a["calls_with_reprice"], s0 + ".calls_with_reprice")
    neg = sum(1 for c in RP["cells"].values() if c["all"]["per_share_mark_c"] < 0)
    N.add("rp.cells_neg", intc(neg), neg, "D: count of replay.json::cells[*].all.per_share_mark_c < 0")
    N.add("rp.cells", intc(len(RP["cells"])), len(RP["cells"]), "D: len(replay.json::cells)")
    bk, bv_ = max(RP["cells"].items(), key=lambda kv: kv[1]["all"]["per_share_mark_c"])
    N.add("rp.best", f"{sgn(bv_['all']['per_share_mark_c'])} {ci(bv_['all']['per_share_mark_ci95_c'])}", bk, "D: argmax over replay cells")
    N.add("rp.best.cell", bk.split("|")[1].replace("lag", "lag ") + " s, V = " + bk.split("|")[0][1:] + " s", bk, "D: argmax over replay cells")
    N.add("rp.matches", intc(len(RP["matches"])), len(RP["matches"]), "results/replay/replay.json::matches (len)")
    N.add("rp.replayable", intc(a["replayable_points"]), a["replayable_points"], s0 + ".replayable_points")
    N.add("rp.official", intc(a["official_points"]), a["official_points"], s0 + ".official_points")
    N.add("rp.recv_ms", intc(J("results/replay/audit.json")["recv_latency_ms"]), J("results/replay/audit.json")["recv_latency_ms"],
          "results/replay/audit.json::recv_latency_ms")
    # ex-ante selective replay (EXPLORATORY, added after the all-points replay; results/replay/selective/selective.json)
    SEL = J("results/replay/selective/selective.json")
    sc4 = SEL["cells"]["T4c|lag2|V1"]["all"]
    s0 = "results/replay/selective/selective.json::cells.T4c|lag2|V1.all"
    N.add("rp.sel.t4.c", sgn(sc4["per_share_mark_c"]), sc4["per_share_mark_c"], s0 + ".per_share_mark_c")
    N.add("rp.sel.t4.ci", ci(sc4["per_share_mark_ci95_c"]), sc4["per_share_mark_ci95_c"], s0 + ".per_share_mark_ci95_c")
    N.add("rp.sel.t4.fills", intc(sc4["fills"]), sc4["fills"], s0 + ".fills")
    sel2 = [c for c in SEL["cells"].values() if c["T"] is not None and c["lag"] == 2.0]
    nneg2 = sum(1 for c in sel2 if c["all"]["per_share_mark_c"] < 0)
    N.add("rp.sel.neg2", f"{nneg2} of {len(sel2)}", [nneg2, len(sel2)],
          "D: selective.json cells with T set and lag 2.0 whose all.per_share_mark_c < 0")
    extra["selective"] = SEL["cells"]

    # ---------------------------------------------------------------- blind tests and failures (12.10, Table 3)
    for k, key in (("h1", "J0.04_H30"), ("h2", "lo0.85_hi0.97"), ("h5", "J0.04_W30")):
        for per in ("is", "oos"):
            d = S[per][k][key]
            N.add(f"{k}.{per}.c", sgn(d["mean_pnl_per_share_c"]), d["mean_pnl_per_share_c"],
                  f"results/summary.json::{per}.{k}.{key}.mean_pnl_per_share_c")
            N.add(f"{k}.{per}.ci", ci(d["ci95_pnl_per_share_c"]), d["ci95_pnl_per_share_c"],
                  f"results/summary.json::{per}.{k}.{key}.ci95_pnl_per_share_c")
    h1neg = sum(1 for v in S["is"]["h1"].values() if v["mean_pnl_per_share_c"] < 0)
    N.add("h1.neg", f"{h1neg} of {len(S['is']['h1'])}", [h1neg, len(S["is"]["h1"])], "D: count of summary.json::is.h1.*.mean_pnl_per_share_c < 0")
    N.add("v1.is.c", sgn(S["is"]["h6_shadow"]["mean_pnl_per_share_c"]), S["is"]["h6_shadow"]["mean_pnl_per_share_c"],
          "results/summary.json::is.h6_shadow.mean_pnl_per_share_c")
    N.add("v1.oos.usd", usd(S["oos"]["h6_shadow"]["total_pnl_usd"], signed=True), S["oos"]["h6_shadow"]["total_pnl_usd"],
          "results/summary.json::oos.h6_shadow.total_pnl_usd")
    N.add("v1.oos.c", sgn(S["oos"]["h6_shadow"]["mean_pnl_per_share_c"]), S["oos"]["h6_shadow"]["mean_pnl_per_share_c"],
          "results/summary.json::oos.h6_shadow.mean_pnl_per_share_c")
    for per in ("is", "oos"):
        p = EX["primary"][f"u2_{per}"]
        N.add(f"u2.{per}.c", sgn(p["per_share_c"]), p["per_share_c"], f"results/expand/results.json::primary.u2_{per}.per_share_c")
        N.add(f"u2.{per}.ci", ci(p["per_share_ci_c"]), p["per_share_ci_c"], f"results/expand/results.json::primary.u2_{per}.per_share_ci_c")
        fmo = EX["fast_minus_others_u2"][f"u2_{per}"]["fast_minus_others_c"]
        N.add(f"u2.fmo.{per}", sgn(fmo), fmo, f"results/expand/results.json::fast_minus_others_u2.u2_{per}.fast_minus_others_c")
    N.add("u2.verdict", EX["primary"]["verdict"], EX["primary"]["verdict"], "results/expand/results.json::primary.verdict")
    T3 = J("results/tier0_v3/blind.json")
    for per in ("is", "oos"):
        p = T3["sets"][f"u2_{per}"]["primary"]
        N.add(f"t3.{per}.c", sgn(p["per_share_c"]), p["per_share_c"], f"results/tier0_v3/blind.json::sets.u2_{per}.primary.per_share_c")
    N.add("t3.verdict", T3["verdicts"]["U2 (primary, test b)"]["overall"].split(" ")[0], T3["verdicts"], "results/tier0_v3/blind.json::verdicts")
    MK = J("results/maker/oos.json")
    N.add("mk.is.c", sgn(MK["consistency"]["is_1s5_net_c"]), MK["consistency"]["is_1s5_net_c"], "results/maker/oos.json::consistency.is_1s5_net_c")
    N.add("mk.oos.c", sgn(MK["primary"]["value_c"]), MK["primary"]["value_c"], "results/maker/oos.json::primary.value_c")
    N.add("mk.oos.ci", ci(MK["primary"]["ci95_c"]), MK["primary"]["ci95_c"], "results/maker/oos.json::primary.ci95_c")
    N.add("mk.oos.usd", usd(MK["headline"]["total_pnl_usd"], signed=True), MK["headline"]["total_pnl_usd"], "results/maker/oos.json::headline.total_pnl_usd")
    N.add("mk.verdict", MK["primary"]["verdict"], MK["primary"]["verdict"], "results/maker/oos.json::primary.verdict")
    TT = J("results/tt/results.json")
    N.add("tt.matches", intc(TT["counts"]["evaluable_matches"]), TT["counts"]["evaluable_matches"], "results/tt/results.json::counts.evaluable_matches")
    N.add("tt.spread", intc(TT["TT4"]["book_snapshot"]["all"]["spread_c"]["median"]), TT["TT4"]["book_snapshot"]["all"]["spread_c"]["median"],
          "results/tt/results.json::TT4.book_snapshot.all.spread_c.median")
    N.add("tt.qualified", "none" if not TT["TT2"]["any_wallet_qualified"] else "some", TT["TT2"]["any_wallet_qualified"],
          "results/tt/results.json::TT2.any_wallet_qualified")

    # ---------------------------------------------------------------- risk, capacity, financials (12.11)
    rc = J("results/engine/demo_run_L4.json")["risk_config"]
    from engine.risk.limits import RiskConfig  # noqa: E402
    rcd = RiskConfig()
    for k in ("max_order_usd", "net_cap_shares", "daily_stop_usd", "feed_stale_ms", "vision_stale_ms"):
        assert float(getattr(rcd, k)) == float(rc[k]), f"RiskConfig.{k} {getattr(rcd, k)} != demo_run_L4 {rc[k]}"
    assert list(rcd.zone) == list(rc["zone"]), "RiskConfig.zone differs from demo_run_L4"
    rs0 = "results/engine/demo_run_L4.json::risk_config"
    N.add("risk.order_usd", usd(rc["max_order_usd"]), rc["max_order_usd"], rs0 + ".max_order_usd")
    N.add("risk.netcap", intc(rc["net_cap_shares"]), rc["net_cap_shares"], rs0 + ".net_cap_shares")
    N.add("risk.zone", f"{rc['zone'][0]:.2f}\u2013{rc['zone'][1]:.2f}", rc["zone"], rs0 + ".zone")
    N.add("risk.daily_stop", usd(rc["daily_stop_usd"]), rc["daily_stop_usd"], rs0 + ".daily_stop_usd")
    N.add("risk.feed_stale", f"{rc['feed_stale_ms'] / 1000:g}", rc["feed_stale_ms"], rs0 + ".feed_stale_ms")
    N.add("risk.vision_stale", f"{rc['vision_stale_ms'] / 1000:g}", rc["vision_stale_ms"], rs0 + ".vision_stale_ms")
    sd = RG["sharpe_moments"]["v2_is"]["sd_daily_usd"]
    N.add("risk.daily_stop_sigma", num(rc["daily_stop_usd"] / sd, 2), rc["daily_stop_usd"] / sd,
          "D: daily_stop_usd / results/rigor/rigor.json::sharpe_moments.v2_is.sd_daily_usd")
    lc = RS["liquidity_capital"]["is_eval"]
    N.add("risk.cap_realised", usd(lc["capital_usd_3x_peak_realised"]), lc["capital_usd_3x_peak_realised"],
          "results/risk/risk_stats.json::liquidity_capital.is_eval.capital_usd_3x_peak_realised")
    N.add("liq.trade_med", usd(lc["usd_per_trade_quantiles"]["0.5"]), lc["usd_per_trade_quantiles"]["0.5"],
          "results/risk/risk_stats.json::liquidity_capital.is_eval.usd_per_trade_quantiles.0.5")
    ml = rc["net_cap_shares"] * rc["zone"][1]
    N.add("risk.maxloss", usd(ml), ml, "D: " + rs0 + ".net_cap_shares x zone[1] (held to resolution, before fees)")
    # months for v2's OOS edge to reach the half-size trigger / zero if it fell at the fast tier's IS pace
    slope = abs(hd["fast_tier_slope_c_per_month"]["IS"])
    m_half = (N.raw("v2.oos.c") - 0.3) / slope
    m_zero = N.raw("v2.oos.c") / slope
    N.add("risk.months_half", num(m_half, 1), m_half, "D: (v2.oos.c - 0.3) / |ft.slope| (extrapolation)")
    N.add("risk.months_zero", num(m_zero, 1), m_zero, "D: v2.oos.c / |ft.slope| (extrapolation)")
    tm = PM["p25_kill_rules_is"]["trailing_30d_edge_rule_v2_is"]["trailing_edge_c_min"]
    N.add("risk.trail_min", sgn(tm), tm, "results/financials/pm_compute.json::p25_kill_rules_is.trailing_30d_edge_rule_v2_is.trailing_edge_c_min")
    sc = FIN["strategies"]["v2"]["scaling"]
    for size, k in (("0.5x", "0.5x"), ("1x", "1x"), ("2x", "2x"), ("5x", "5x"), ("all prints", "all")):
        for per, P in (("is", "IS"), ("oos", "OOS")):
            d = sc[size][P]
            s0 = f"results/financials/financials.json::strategies.v2.scaling.{size}.{P}"
            N.add(f"cap.{k}.{per}.c", sgn(d["per_share_c"]), d["per_share_c"], s0 + ".per_share_c")
            N.add(f"cap.{k}.{per}.ci", ci(d["per_share_ci95_c"]), d["per_share_ci95_c"], s0 + ".per_share_ci95_c")
            N.add(f"cap.{k}.{per}.usd", usd(d["pnl_usd_per_day"], signed=True), d["pnl_usd_per_day"], s0 + ".pnl_usd_per_day")
            N.add(f"cap.{k}.{per}.capital", usd(d["capital_usd"]), d["capital_usd"], s0 + ".capital_usd")
    ce = FIN["strategies"]["v2"]["ceiling"]
    for per, P in (("is", "IS"), ("oos", "OOS")):
        N.add(f"cap.ceiling.{per}", usd(ce[P]["fast_tier_qualified_print_usd_per_day"]), ce[P]["fast_tier_qualified_print_usd_per_day"],
              f"results/financials/financials.json::strategies.v2.ceiling.{P}.fast_tier_qualified_print_usd_per_day")
        w = FIN["strategies"]["v2"]["periods"][P]["waterfall"]["usd_per_day"]
        for kk in ("gross_edge", "taker_fees", "net_trading"):
            N.add(f"fin.{per}.{kk}", usd(w[kk], signed=kk != "gross_edge"), w[kk],
                  f"results/financials/financials.json::strategies.v2.periods.{P}.waterfall.usd_per_day.{kk}")
    for k in ("low", "central", "high"):
        N.add(f"fin.fixed.{k}", usd(fixed[k]), fixed[k], f"results/financials/financials.json::strategies.v2.cost.daily.{k}")
    hl = {(r["strategy"], r["period"]): r for r in FIN["headline"]}
    for per, P in (("is", "IS"), ("oos", "OOS (burned, non-blind)")):
        v = hl[("v2 (frozen fast-tier book)", P)]["net_after_costs_usd_per_day"]["central"]
        N.add(f"fin.v2.{per}.net_central", usd(v, signed=True), v,
              f"results/financials/financials.json::headline[v2,{P}].net_after_costs_usd_per_day.central")
    bf = FIN["strategies"]["v2"]["periods"]["OOS"]["breakeven_taker_fee"]
    N.add("fin.be_fee.before", pct(bf["rate_before_fixed_costs"] * 100, 1), bf["rate_before_fixed_costs"],
          "results/financials/financials.json::strategies.v2.periods.OOS.breakeven_taker_fee.rate_before_fixed_costs")
    N.add("fin.be_fee.central", pct(bf["rate_after_central_fixed_costs"] * 100, 1), bf["rate_after_central_fixed_costs"],
          "results/financials/financials.json::strategies.v2.periods.OOS.breakeven_taker_fee.rate_after_central_fixed_costs")
    fl = FIN["cost_assumptions"]["feed_licence"]
    N.add("fin.feed.central", usd(fl["central"]), fl["central"], "results/financials/financials.json::cost_assumptions.feed_licence.central")
    N.add("fin.feed.low", usd(fl["low"]), fl["low"], "results/financials/financials.json::cost_assumptions.feed_licence.low")
    N.add("fin.feed.high", usd(fl["high"]), fl["high"], "results/financials/financials.json::cost_assumptions.feed_licence.high")
    extra["cost_assumptions"] = FIN["cost_assumptions"]
    sdp = LT["stale_depth"]
    for k, s in (("pre", "pre"), ("1s", "pre1s"), ("2s", "pre2s")):
        N.add(f"liq.stale_{k}", usd(sdp[s]["median_usd"]), sdp[s]["median_usd"],
              f"research/v2/latency/results.json::summary.stale_depth.{s}.median_usd")
    spr = LT["side_market_spreads_live"]["moneyline"]["median_spread"] * 100
    N.add("liq.spread", num(spr, 0), spr, "research/v2/latency/results.json::summary.side_market_spreads_live.moneyline.median_spread")

    # ---------------------------------------------------------------- policy constants (12.15) -> policy.json
    from src import fasttier  # noqa: E402
    policy = {
        "detector_move_c": {"value": 4, "source": src_line("src/tiers.py", r"def jump_onsets\(.*J=0.04")},
        "detector_short_window_s": {"value": 10, "source": src_line("src/tiers.py", r"def jump_onsets\(.*short_w=10")},
        "detector_long_window_s": {"value": 60, "source": src_line("src/tiers.py", r"def jump_onsets\(.*long_w=60")},
        "qualify_min_prints": {"value": fasttier.MIN_PRINTS, "source": src_line("src/fasttier.py", r"^MIN_PRINTS, MIN_MATCHES, MIN_T")},
        "qualify_min_matches": {"value": fasttier.MIN_MATCHES, "source": src_line("src/fasttier.py", r"^MIN_PRINTS, MIN_MATCHES, MIN_T")},
        "qualify_min_t": {"value": fasttier.MIN_T, "source": src_line("src/fasttier.py", r"^MIN_PRINTS, MIN_MATCHES, MIN_T")},
        "shrinkage_n0": {"value": 200, "source": src_line("HYPOTHESIS_V2.md", r"n0 = 200")},
        "zone": {"value": [0.05, 0.95], "source": src_line("HYPOTHESIS_V2.md", r"Price zone")},
        "lock_s": {"value": 4 * 3600, "source": src_line("src/v2.py", r"^LOCK_S")},
        "trailing_edge_half_c": {"value": 0.3, "source": src_line("docs/RISK.md", r"Trailing 30-day net edge < 0.3")},
        "drawdown_stop_pct": {"value": 5, "source": src_line("docs/RISK.md", r"Drawdown from equity peak > 5%")},
        "rule_changes_after_a_look": {"value": 2, "source": src_line("DEVIATIONS.md", r"^## D9")},
    }
    for k, key in (("pol.det_c", "detector_move_c"), ("pol.q_prints", "qualify_min_prints"),
                   ("pol.q_matches", "qualify_min_matches"), ("pol.q_t", "qualify_min_t"),
                   ("pol.trail_half", "trailing_edge_half_c"), ("pol.dd_stop", "drawdown_stop_pct"),
                   ("pol.n0", "shrinkage_n0"), ("peeks.rule_changes", "rule_changes_after_a_look")):
        v = policy[key]["value"]
        txt = f"{v:g}" if isinstance(v, (int, float)) else str(v)
        if key == "drawdown_stop_pct":
            txt += "%"
        N.add(k, txt, v, "results/paper/policy.json::" + key + " <- " + policy[key]["source"])
    extra["policy"] = policy

    # ---------------------------------------------------------------- variants (12.12) -> variants.json
    g0 = pd.read_csv(ROOT / "results/tier0/grid.csv", usecols=["period"]) if "period" in pd.read_csv(ROOT / "results/tier0/grid.csv", nrows=1).columns else None
    n_t0 = int((g0.period == "IS").sum()) if g0 is not None else None
    g3 = pd.read_csv(ROOT / "results/tier0_v3/is/grid.csv", usecols=["kind"])
    n_t3 = int((g3.kind == "grid").sum())
    n_cs = len({k.split("/")[1] for k in CS if not k.endswith("/base")})
    tt_tests = [k for k in TT if re.fullmatch(r"TT\d", k)]
    if "table_tennis" in DJ:
        tt_tests = sorted(set(tt_tests) | {"TT5"})
    variants = [
        {"family": "H1-H6 pre-registered and H5/H6 rules", "count": NN["H1_H6"], "chose": "frozen primaries (DEVIATIONS D6)",
         "source": "results/rigor/rigor.json::psr_dsr.N.H1_H6"},
        {"family": "v2 lenses (exit, sizing, selection, cross-market, latency, Kalshi)", "count": NN["all_NOTE_s8"] - NN["H1_H6"],
         "chose": "v2 (G_50pct_net100), IS only", "source": "D: psr_dsr.N.all_NOTE_s8 - N.H1_H6"},
        {"family": "v2-safe grid", "count": NN["all_plus_v2safe_grid"] - NN["all_NOTE_s8"], "chose": "v2-safe (secondary)",
         "source": "D: psr_dsr.N.all_plus_v2safe_grid - N.all_NOTE_s8"},
        {"family": "tier-0 pre-registered scenarios", "count": n_t0, "chose": "none (sensitivity grid)",
         "source": "results/tier0/grid.csv rows with period == IS"},
        {"family": "tier-0 v3 in-sample grid", "count": n_t3, "chose": "frozen v3 rule (blind: FAIL)",
         "source": "results/tier0_v3/is/grid.csv rows with kind == grid"},
        {"family": "maker v1 evaluated variants", "count": len(MK["variants_evaluated"]), "chose": "maker v1 primary (blind: FAIL)",
         "source": "len(results/maker/oos.json::variants_evaluated)"},
        {"family": "cost-stress cases", "count": n_cs, "chose": "none (stress)", "source": "results/v2/cost_stress.json keys minus base"},
        {"family": "table-tennis tests TT1-TT5", "count": 5, "chose": "none (untestable)",
         "source": "results/tt/results.json TT1-TT4 + results/decay/decay.json::table_tennis"},
    ]
    if any(v["count"] is None for v in variants):
        raise KeyError("COURTSIDE: missing variant count")
    total = sum(v["count"] for v in variants)
    sens = {"latency-sweep cells": int(len(pd.read_csv(ROOT / "results/tier0/latency_sweep.csv", usecols=["x_s"]))),
            "replay cells": len(RP["cells"])}
    N.add("var.total", intc(total), total, "results/paper/variants.json (sum of families)")
    N.add("var.strategy", intc(NN["all_plus_v2safe_grid"]), NN["all_plus_v2safe_grid"], "results/rigor/rigor.json::psr_dsr.N.all_plus_v2safe_grid")
    N.add("var.tier0", intc(n_t0), n_t0, "results/tier0/grid.csv (period == IS)")
    N.add("var.tier0v3", intc(n_t3), n_t3, "results/tier0_v3/is/grid.csv (kind == grid)")
    N.add("var.maker", intc(len(MK["variants_evaluated"])), len(MK["variants_evaluated"]), "results/maker/oos.json::variants_evaluated")
    N.add("var.sweep", intc(sens["latency-sweep cells"]), sens["latency-sweep cells"], "results/tier0/latency_sweep.csv rows")
    extra["variants"] = {"families": variants, "total": total, "sensitivities_none_chosen": sens}

    # ---------------------------------------------------------------- peeks (12.13) -> peeks.json
    rules = [("live", r"REPLAY|live paper|session"), ("audit", r"audit|reproduc|RE-RUN|rebuild|recompute"),
             ("descriptive", r"descriptive|no strategy|no P&L|plumbing|selection check|provenance"),
             ("non-blind", r"non-blind"), ("blind first run", r"first run|first use|blind|PREREG")]
    lines = [ln for ln in (ROOT / "results/oos_peeks.log").read_text().splitlines() if ln.strip()]
    peeks = []
    for ln in lines:
        cls = next((c for c, rx in rules if re.search(rx, ln, re.I)), "other")
        ts, _, desc = ln.partition(" ")
        peeks.append({"utc": ts, "class": cls, "line": desc})
    counts = {c: sum(1 for p in peeks if p["class"] == c) for c, _ in rules + [("other", "")]}
    N.add("peeks.n", intc(len(peeks)), len(peeks), "results/oos_peeks.log (lines at build time)")
    for c, k in (("blind first run", "blind"), ("non-blind", "nonblind"), ("descriptive", "desc"), ("audit", "audit"),
                 ("live", "live"), ("other", "other")):
        N.add(f"peeks.{k}", intc(counts[c]), counts[c], f"D: keyword class '{c}' over results/oos_peeks.log")
    extra["peeks"] = {"n": len(peeks), "counts": counts, "rules": rules, "lines": peeks}

    # ---------------------------------------------------------------- pending slots (12.14)
    fwd_p = ROOT / "results/v2/forward.json"
    hv2 = (ROOT / "HYPOTHESIS_V2.md").read_text()
    a3 = re.search(r"^## Amendment A3 \(([^)]+)\): forward test not run", hv2, re.M)
    a4 = re.search(r"^## Amendment A4 \(([^)]+)\): forward test reinstated", hv2, re.M)
    v3_p = ROOT / "results/tier0_v3/forward/results.json"
    am_fwd = re.findall(r"^## Amendment (A\d+) \(([^)]+)\): forward test ([^\n(]+)", hv2, re.M)
    last_fwd = am_fwd[-1] if am_fwd else None
    # ONE slot for the blind forward test (research/compliance/PAPER_REQUIREMENTS.md, addendum 2026-10-04T02:59Z): it
    # fills from results/v2/forward.json (and the tier-0 v3 forward secondary) at build time; until then it says when
    # the pre-registered run happens. The live paper session stays out of the results.
    if fwd_p.exists():
        F = json.loads(fwd_p.read_text())

        def tri(v):
            return f"{sgn(v[0])} {ci(v[1:3])}" if isinstance(v, list) and len(v) >= 3 else str(v)
        parts = []
        if "primary_A_fast_minus_others_c" in F:
            parts.append(f"A {tri(F['primary_A_fast_minus_others_c'])}¢ {F.get('verdict_A_fast_tier', '')}".strip())
        if "primary_m30_per_share_c" in F:
            parts.append(f"B {tri(F['primary_m30_per_share_c'])}¢ {F.get('verdict_B_v2_book', '')}".strip())
        if "v2_trades" in F:
            parts.append(f"n = {intc(F['v2_trades'])}")
        if v3_p.exists():
            try:
                R3 = json.loads(v3_p.read_text())["results"]["frozen_v3"]["primary (lag 2.0 | tournament | trunc 0 | queue 0)"]["full_window"]
                parts.append(f"v3 {sgn(R3['per_share_c'])}¢ [{num(R3['per_share_ci95_c_lo'])}, {num(R3['per_share_ci95_c_hi'])}]")
            except (KeyError, TypeError):
                parts.append("v3: see results/tier0_v3/forward/results.json")
        cell = " · ".join(parts) if parts else "see results/v2/forward.json"
        status = " / ".join(str(F.get(k)) for k in ("verdict_A_fast_tier", "verdict_B_v2_book") if F.get(k)) or "reported"
        N.add("fwd.cell", cell, F, "results/v2/forward.json" + (" ; results/tier0_v3/forward/results.json" if v3_p.exists() else ""))
        N.add("fwd.status", status, status, "results/v2/forward.json::verdict_*")
    elif last_fwd and last_fwd[2].strip().startswith("not run") and last_fwd[0] not in ("A3",):
        # the LAST amendment on the forward test decides (A5, 2026-10-04T03:32Z, final: not run within the hackathon
        # window; research/compliance/PAPER_REQUIREMENTS.md addendum of the same time)
        N.add("fwd.cell", f"pre-registered but not run within the hackathon window (HYPOTHESIS_V2.md {last_fwd[0]})",
              last_fwd[1], f"HYPOTHESIS_V2.md::Amendment {last_fwd[0]} (results/v2/forward.json absent at build time)")
        N.add("fwd.status", "not run", None, f"HYPOTHESIS_V2.md::Amendment {last_fwd[0]}")
    elif a4:
        N.add("fwd.cell", "runs 2026-10-04 11:30 UTC (pre-registered)", a4.group(1),
              "HYPOTHESIS_V2.md::Amendment A4 (results/v2/forward.json absent at build time)")
        N.add("fwd.status", "runs once", None, "HYPOTHESIS_V2.md::Amendment A4")
    elif a3:
        N.add("fwd.cell", "not run (submitted before the forward window closed)", a3.group(1), "HYPOTHESIS_V2.md::Amendment A3")
        N.add("fwd.status", "not run", None, "HYPOTHESIS_V2.md::Amendment A3")
    else:
        N.add("fwd.cell", "pending (runs once, Oct 4)", None, "results/v2/forward.json (absent at build time)")
        N.add("fwd.status", "pending", None, "results/v2/forward.json (absent at build time)")
    live_p = ROOT / "results/live/summary.json"
    stop_p = ROOT / "results/live/STOPPED_TEAM_DECISION"
    if stop_p.exists() and live_p.exists():
        L = json.loads(live_p.read_text())["books"]["B1"]
        N.add("live.cell", f"stopped by a team decision after {intc(L['fills'])} fills; not used", L,
              "results/live/STOPPED_TEAM_DECISION; results/live/summary.json::books.B1.fills")
        N.add("live.status", "stopped", "stopped", "results/live/STOPPED_TEAM_DECISION")
    elif (ROOT / "results/live/FINAL").exists() and live_p.exists():
        L = json.loads(live_p.read_text())["books"]["B1"]
        cell = f"{intc(L['fills'])} fills, P&L {usd(L['pnl'], 2, signed=True)}"
        if L.get("net_c_per_share") is not None:
            cell += f", {sgn(L['net_c_per_share'])}\u00a2/share"
        N.add("live.cell", cell, L, "results/live/summary.json::books.B1 (FINAL present)")
        N.add("live.status", "final", "final", "results/live/FINAL")
    else:
        fills = json.loads(live_p.read_text())["books"]["B1"]["fills"] if live_p.exists() else 0
        N.add("live.cell", f"pending (paper; {intc(fills)} fills so far)", fills,
              "results/live/summary.json::books.B1.fills (FINAL absent)")
        N.add("live.status", "pending", None, "results/live/FINAL (absent at build time)")

    # ---------------------------------------------------------------- pre-registration trail (Table A7)
    trail = subprocess.run(["git", "log", "--format=%h|%aI|%s", "--", "HYPOTHESIS.md", "HYPOTHESIS_V2.md", "HYPOTHESIS_TT.md",
                            "DEVIATIONS.md", "research/replay/PROTOCOL.md"] + [str(p.relative_to(ROOT)) for p in
                                                                              (ROOT / "research").glob("*/PREREG.md")]
                           + [str(p.relative_to(ROOT)) for p in (ROOT / "research").glob("*/*/PREREG.md")],
                           cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()
    rows_ = []
    for t in trail:
        c_, tm_, subj_ = t.split("|", 2)
        rows_.append({"commit": c_, "time": pd.Timestamp(tm_).tz_convert("UTC").strftime("%Y-%m-%d %H:%M"), "subject": subj_})
    extra["trail"] = rows_[::-1]
    collect_final(N, extra)
    collect_evidence(N)
    collect_revision(N)  # before the appendix rows below, which use its keys
    collect_integration(N)  # the integration pass after the organizers' brief (new keys only)
    # ---------------------------------------------------------------- authors (research/compliance/TEAM.md)
    tm_ = ROOT / "research/compliance/TEAM.md"
    authors = "[Author names: team to fill]"
    if tm_.exists():
        for ln in tm_.read_text().splitlines():
            mm_ = re.match(r"^([A-Z][^()\n#]+?)\s*\(University of Florida\)\s*$", ln.strip())
            if mm_:
                authors = mm_.group(1).strip()
                break
    extra["authors"] = authors
    # ---------------------------------------------------------------- 'Everything we tested' rows (appendix B)
    # one row per test: (test, what it was, best result, verdict); a 1-tuple starts a group. The robustness rows
    # (worse entry, doubled costs, fixed costs, rigor pack) live here too, so the appendix has one table of tests.
    V = N
    ev = [
        ("Who is fast, and what they earn (public tapes)",),
        ("H1 follow the jump", r"take the direction of a $\geq$4¢ move, hold 30\,s",
         f"OOS {V('h1.oos.c')}¢ {V('h1.oos.ci')}; {V('h1.neg')} IS variants below zero", "rejected"),
        ("H2 favourites", "buy in-play favourites priced 85--97¢", f"OOS {V('h2.oos.c')}¢ {V('h2.oos.ci')}", "no edge"),
        ("H4 score feeds", "do public score feeds lag the book?", f"median lag {V('h4.lead')}\\,s ($n = {V('h4.n')}$)", "confirmed"),
        ("H5 quote after jumps", "post maker quotes after a move", f"OOS {V('h5.oos.c')}¢ {V('h5.oos.ci')}", "not significant"),
        ("H6 fast tier", "wallets trading 0--3\\,s after a move, picked on past months",
         f"{V('ft.c.is')}\\,/\\,{V('ft.c.oos.only')}¢ net 30\\,s markout (IS\\,/\\,OOS prints only; {V('ft.c.oos')}¢ with August's IS prints); {V('ft.months.is')} and {V('ft.months.oos')} months positive", "confirmed"),
        ("Kalshi lead-lag", "Kalshi vs Polymarket on the same points",
         f"Kalshi first in {V('ev.kalshi.first')} of {V('ev.kalshi.n')} repricings (median {V('ev.kalshi.lead')}\\,s)", "lag mostly mechanical"),
        ("Signal decay (TT5)", "with-jump markout at 1--2\\,s minus 10--30\\,s after a move",
         f"OOS {V('decay.test.oos')}¢; whole year {V('decay.test.pool')}¢; fast tier {V('decay.fast.0.is')} to {V('decay.fast.12.is')}¢ (IS, 0 to 1--2\\,s)",
         "decays in today's regime only"),
        ("Clocks", "when the book, the stamp and the tape move",
         f"book {V('lat.book_vs_stamp')}\\,s before the stamp ($n = {V('lat.n_points')}$); tape {V('ev.blocklag')}\\,s late", "measured"),
        ("Factor regression", "Fama--French three factors and momentum",
         f"$\\alpha$ $t = {V('fac.alpha_t')}$; largest factor $|t| = {V('fac.max_t')}$", "no factor exposure"),
        ("Copying the fast tier (v2 and relatives)",),
        ("v1", "copy the fast tier, dollar sizing; OOS opened once", f"IS {V('v1.is.c')}¢; OOS {V('v1.oos.c')}¢, {V('v1.oos.usd')}", "failed"),
        ("Sizing", f"{V('sel.sizing.n')} sizing policies, walk-forward",
         f"\\texttt{{{V('sel.sizing.pick')}}}: Sharpe {V('v2.is.sr')} IS; all {V('plat.sizing.pos')} with IS CI above zero (Sharpe {V('plat.sizing.sr')})",
         "adopted (v2); plateau"),
        ("Exits", f"maker exit instead of holding ({V('ev.exit.n')} variants)",
         f"IS {V('ev.exit.c')}¢ {V('ev.exit.ci')} (1\\,s\\,/\\,5\\% regime); live fills adverse ({V('ev.livefill.fill30')} filled in 30\\,s)", "not adopted"),
        ("Trade selection", f"which fast-tier trades to take ({V('ev.sel.n')} variants)",
         f"nested walk-forward {V('ev.sel.c')}¢ {V('ev.sel.ci')} vs {V('ev.sel.base')}¢ (IS)", "IS only"),
        ("Side markets", f"side markets vs the match market ({V('ev.cm.n')} variants)",
         f"leaning maker {V('ev.cm.c')}¢ {V('ev.cm.ci')} (IS); taking stale side quotes: no edge", "IS only; tiny"),
        ("v2", "frozen copy book at the fast tier's own prices",
         f"Sharpe {V('v2.is.sr')}\\,/\\,{V('v2.oos.sr')}; OOS {V('v2.oos.c')}¢ {V('v2.oos.ci')}", "headline (Table~\\ref{tab:head})"),
        ("v2, worse entry", "enter ½ or 1 tick worse",
         f"IS {V('v2.is.slip05')}\\,/\\,{V('v2.is.slip10')}¢; OOS {V('v2.oos.slip05')}\\,/\\,{V('v2.oos.slip10')}¢", "about zero OOS"),
        ("v2, costs doubled", "fees $\\times$2\\,/\\,all costs $\\times$2",
         f"IS {V('v2.is.fx2.c')}\\,/\\,{V('v2.is.cx2.c')}¢; OOS {V('v2.oos.fx2.c')}\\,/\\,{V('v2.oos.cx2.c')}¢", "fails OOS"),
        ("v2, fixed costs", "after central data and running costs",
         f"IS {V('fin.v2.is.net_central')} a day; OOS {V('fin.v2.oos.net_central')} a day", "fails OOS"),
        ("v2, unseen markets", f"{V('u2.markets')} markets we never examined (blind)",
         f"IS {V('u2.is.c')}¢; OOS {V('u2.oos.c')}¢ {V('u2.oos.ci')}", "fail"),
        ("v2-safe", "net cap 50, fixed after v2's OOS losses",
         f"Sharpe {V('v2s.is.sr')}\\,/\\,{V('v2s.oos.sr')}; blind {V('v2s.u2.c')}¢ {V('v2s.u2.ci')}", "fail (blind)"),
        ("Per-wallet cap", f"{V('wcap.W')} a wallet a day plus retirement, chosen on IS from {V('wcap.n')} variants, pre-registered",
         f"OOS {V('wcap.oos.c')}¢ {V('wcap.oos.ci')}, Sharpe {V('wcap.oos.sr')}, {V('wcap.oos.pnl')} vs {V('wcap.base.oos.pnl')}; max DD {V('wcap.oos.maxdd')} vs {V('wcap.base.oos.maxdd')}; top five {V('wcap.oos.top5')} (was {V('conc.top5.oos')})",
         "pass (burned OOS); a loss limit, backtest only"),
        ("Copier fill stress", "v2 filled after the venue hold and the measured block lag, on the real tape",
         f"next same-side print: IS {V('copier.is.c')}¢, OOS {V('copier.oos.c')}¢; optimistic: IS {V('copier.opt.is.c')}¢, OOS {V('copier.opt.oos.c')}¢ {V('copier.opt.oos.ci')}",
         "a copier loses"),
        ("Maker v1", "pre-registered maker book (blind)", f"{V('mk.oos.c')}¢ {V('mk.oos.ci')} per fill, {V('mk.oos.usd')}", "fail"),
        ("Rigor pack", "deflated Sharpe, PBO, block bootstrap",
         f"DSR {V('v2.is.dsr')}\\,/\\,{V('v2.oos.dsr')}; PBO {V('rig.pbo.lowloss')} ({V('plat.pbo')} by block choice); $P(\\text{{SR}}\\leq 0) = {V('rig.boot.p')}$", "luck not ruled out OOS"),
        ("PSR, MinTRL, haircut", f"six tests incl. a Bonferroni haircut over {V('var.total')} variants",
         f"v2 IS 6 of 6 (haircut Sharpe {V('rig2.v2is.hlz_sr')}); v2 OOS {V('rig2.v2oos.pass')} of 6 ($t = {V('rig2.v2oos.t')}$ vs {V('rig2.t_req')}); CV pre-registered 0, post hoc {V('rig2.cvcal.oos.pass')} OOS",
         "no book passes all six OOS"),
        ("Edge persistence", "monthly decay, fee vs entrants, venue-rule breaks",
         f"net {V('pers.slope.net')}¢ a month down, before-fee {V('pers.slope.gross')}¢ {V('pers.slope.gross.ci')}; line hits zero in {V('pers.zero.months')} months ({V('pers.zero.ci')}), a May step fits as well",
         "cannot tell"),
        ("Blind forward test", "v2 on new matches, CV rule v3 as secondary", "FWD", ""),
        ("Being fast ourselves (computer vision)",),
        ("H3 early call", "table-tennis MISS call 50\\,ms before contact, precision $\\geq$0.95",
         f"live causal engine: {V('cv.eng.tp')} of {V('cv.eng.nmiss')} misses, none wrong; offline evaluation (look-ahead feature): {V('cv.tt.tp50')}/{V('cv.tt.called50')}",
         "precision passes; recall low"),
        ("Spin model, table tennis", "spin-aware early call, held-out footage",
         f"{V('spin.tt.tp50')}/{V('spin.tt.calls50')} right at 50\\,ms vs the frozen model's {V('cv.tt.tp50')}/{V('cv.tt.called50')} (both offline)", "not adopted"),
        ("Tennis tracker, real clip", "public TrackNet detector with our linking and court-line fit on a Pexels rally (no labels)",
         f"ball in {V('tn.real.ball')} of {V('tn.real.frames')} frames; {V('tn.real.spot')} spot-checks on the ball; court lines {V('tn.real.court_px')}\\,px (median)",
         "tracks; no in/out calls"),
        ("Broadcast tennis", "single-camera landing and out calls, TrackNet games 8--10 (tuned on 1--7)",
         f"out calls {V('bt.call.0')} at the bounce, {V('bt.call.33')} at 33\\,ms, {V('bt.call.67')} at 67\\,ms; landing {V('bt.err0')}\\,cm at the bounce, {V('bt.err.lead')}\\,m at 33--300\\,ms",
         "bounce only at 95\\%; detector saw all games"),
        ("Tennis spin model", "spin-aware landing model (simulated physics)",
         f"{V('cv.spin.bls200')} vs {V('cv.spin.base200')}\\,cm at 200\\,ms; OUT precision {V('spin.out.prec200')}, recall {V('spin.out.rec200')}", "simulation only"),
        ("Rally gate", f"a miss call trades only within {V('gate.s')}\\,s of a bounce call (engine log; {V('gate.sweep')}\\,s also run)",
         f"removes {V('gate.out.removed')} of {V('gate.out.total')} calls on unlabelled balls; keeps {V('gate.correct.kept')} of {V('gate.correct.total')} right ones ({V('gate.correct.kept_lo')} at {V('gate.lo_range')}\\,s)",
         "not enough"),
        ("GPU engine", "streamed causal engine on one L4", f"{V('cv.eng.fps')}\\,fps; {V('cv.eng.p50')}\\,ms p50; {V('cv.eng.dropped')} frames dropped", "measured"),
        ("WebRTC pipeline", "our clip over WebRTC into the engine", f"{V('cv.webrtc')} frame to call; video leg {V('webrtc.leg')}\\,ms", "measured"),
        ("End to end", "video frame to unsigned order on a live book",
         f"{V('e2e.ours')}\\,ms ours; {V('e2e.total')}\\,ms with a 1\\,s feed vs {V('e2e.req')}\\,ms", "pass (paper)"),
        ("Courtside camera", "CV trader with a camera at the venue ($V = 0$)", f"{V('ev.t0.v0.is')}\\,/\\,{V('ev.t0.v0.oos')} a day (pre-registered)", "simulated; no camera"),
        ("Latency sweep", f"$V$ from 0 to 60\\,s, six stamp-lag readings ({V('var.sweep')} cells)",
         f"pre-registered break-even {V('cv.pre.be.oos')}--{V('cv.pre.be.is')}\\,s", "Table~\\ref{tab:head}"),
        ("CV trader, fees doubled", "each fill pays its fee twice (Table~\\ref{tab:head})",
         f"every OOS cell loses (best {V('cv.fx2.oos.best')} a day); fee {V('cv.fee_bps.range')}\\,bps of notional", "fails OOS"),
        ("Fresh holdout, 0.5\\,s feed", f"Table-2 trader on {V('fresh.covered')} newer matches, pre-registered at \\texttt{{{V('fresh.prereg.commit')}}}",
         f"{V('fresh.s2.pre.v05.usd')} (pre-registered) and {V('fresh.s2.cal.v05.usd')} (post hoc) a day; CIs {V('fresh.s2.pre.v05.ci')}, {V('fresh.s2.cal.v05.ci')}",
         "anecdotal (2 days)"),
        ("Price impact", f"log-size cost from {V('liq.orders.n')} IS taker orders; live-book walk",
         f"v2 1$\\times$ OOS {V('liq.v2.1x.oos.central')} a day (conservative {V('liq.v2.1x.oos.cons')}, CI {V('liq.v2.1x.oos.cons.ci')}); others took {V('liq.phi.took')} of stale depth",
         "capacity holds; P\\&L thinner"),
        ("CV rule v3", f"rule tuned on {V('var.tier0v3')} IS variants", f"IS {V('t3.is.c')}¢; blind {V('t3.oos.c')}¢", "fail"),
        ("Replay, all points", f"{V('rp.matches')} matches' real books, every point called",
         f"{V('rp.v1l2.c')}¢ {V('rp.v1l2.ci')} at $V = 1$\\,s; {V('rp.cells_neg')} of {V('rp.cells')} settings below zero", "loses"),
        ("Replay, big points", "only points with a large Markov swing (exploratory)",
         f"{V('rp.sel.t4.c')}¢ {V('rp.sel.t4.ci')}; {V('rp.sel.neg2')} cells below zero", "loses"),
        ("Capacity", "size grid for the CV book and v2", f"post hoc Sharpe halves at {V('capcv.half.oos')}--{V('capcv.half.is')}; pre-registered: none", "small"),
        ("Table-tennis markets", "TT1--TT5 on Polymarket table tennis", f"no fast wallet qualifies; spread {V('tt.spread')}¢", "untestable"),
    ]
    extra["everything"] = ev
    # the blind forward test slot: filled from results/v2/forward.json when it exists; otherwise it follows the last
    # HYPOTHESIS_V2.md amendment on the forward test (A4 reinstated it; A5, final, says it was not run)
    mw = re.search(r"run\s+ONCE\s+at\s+or\s+after\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+UTC", hv2)
    if not fwd_p.exists() and N.text("fwd.status") == "runs once" and mw:
        extra["fwd_text"] = f"runs once on {mw.group(1)} at {mw.group(2)} UTC (pre-registered)"
    else:
        extra["fwd_text"] = N.text("fwd.cell")
    extra["fwd_verdict"] = {"not run": "not run", "runs once": "pending"}.get(N.text("fwd.status"), N.text("fwd.status"))
    extra["peeks_late"] = sum(1 for p in extra["peeks"]["lines"] if "logged after" in p["line"].lower())
    return N, extra


# ================================================================================================ final paper keys
def collect_final(N: Registry, extra: dict) -> None:
    """Keys for the final paper (research/compliance/PAPER_REQUIREMENTS.md): the 0.5 / 1 / 3 s latency scenarios,
    the headline-metrics table (v2 and v2-safe), the components table, capacity in $, the pipeline, the
    'Everything we tested' appendix table and the worked examples of the Calculations appendix. Every value is read
    from a committed result file (or is arithmetic on such values, marked D:); nothing here runs an evaluation."""
    from scipy.stats import norm
    SW = J("results/tier0/latency_sweep.json")
    # ---------------------------------------------------------------- latency scenarios (Table 3)
    scen = (("v05", "0.5"), ("v1", "1"), ("v3", "3"))
    for rk, reading in (("pre", "tournament"), ("cal", "tournament_lagcal")):
        for per, P in (("is", "IS"), ("oos", "burned_OOS")):
            for vk, V in scen:
                c = SW["video_own120"][reading][V][P]
                s0 = f"results/tier0/latency_sweep.json::video_own120.{reading}.{V}.{P}"
                N.add(f"sc.{rk}.{per}.{vk}.usd", usd(c["usd_per_day"], signed=True), c["usd_per_day"], s0 + ".usd_per_day")
                N.add(f"sc.{rk}.{per}.{vk}.uci", "[" + ", ".join(m(f"{x:.0f}") for x in c["usd_per_day_seed_ci95"]) + "]",
                      c["usd_per_day_seed_ci95"], s0 + ".usd_per_day_seed_ci95")
                N.add(f"sc.{rk}.{per}.{vk}.sr", num(c["sharpe_ann"], 1), c["sharpe_ann"], s0 + ".sharpe_ann")
                N.add(f"sc.{rk}.{per}.{vk}.c", sgn(c["net_c_per_share"]), c["net_c_per_share"], s0 + ".net_c_per_share")
                N.add(f"sc.{rk}.{per}.{vk}.cci", ci(c["net_c_per_share_ci95"]), c["net_c_per_share_ci95"],
                      s0 + ".net_c_per_share_ci95")
    # per-point readings at V = 1 (Table 3 row 'same clocks read per point'): stamp noise at L = 2.0 (pre-registered
    # column) and the post hoc inference applied per point (post hoc column)
    for rk, reading in (("pre", "stamp"), ("cal", "stamp_calibrated")):
        for per, P in (("is", "IS"), ("oos", "burned_OOS")):
            v = SW["video_own120"][reading]["1"][P]["usd_per_day"]
            N.add(f"pp.{rk}.{per}.usd", usd(v, signed=True), v, f"results/tier0/latency_sweep.json::video_own120.{reading}.1.{P}.usd_per_day")
            b_ = SW["breakeven_video_delay"].get(reading, {}).get(P, {}).get("breakeven_V_s_seed_mean_curve")
            N.add(f"pp.{rk}.{per}.be", num(b_, 2) if isinstance(b_, (int, float)) else "none", b_,
                  f"results/tier0/latency_sweep.json::breakeven_video_delay.{reading}.{P}.breakeven_V_s_seed_mean_curve")
    CC = J("results/redteam/causal_cv.json")
    for per, P in (("is", "IS"), ("oos", "burned_OOS")):
        v = CC["pessimistic_lagcal"]["V1"][P]["usd_per_day"]
        N.add(f"pess.cal.{per}.usd", usd(v, signed=True), v, f"results/redteam/causal_cv.json::pessimistic_lagcal.V1.{P}.usd_per_day")
    # ---------------------------------------------------------------- headline metrics: v2 and v2-safe (Table 1)
    RG = J("results/rigor/rigor.json")
    rows = {r_["series"]: r_ for r_ in RG["psr_dsr"]["rows"]}
    N.add("v2.is.dsr", f"{rows['v2_is']['dsr_min_N3386']:.3f}", rows["v2_is"]["dsr_min_N3386"],
          "results/rigor/rigor.json::psr_dsr.rows[v2_is].dsr_min_N3386 (min over the three variance sources)")
    N.add("v2.oos.dsr", f"{rows['v2_oos']['dsr_min_N3386']:.3f}", rows["v2_oos"]["dsr_min_N3386"],
          "results/rigor/rigor.json::psr_dsr.rows[v2_oos].dsr_min_N3386 (min over the three variance sources)")
    N.add("v2.oos.psr", f"{rows['v2_oos']['psr_vs_0']:.3f}", rows["v2_oos"]["psr_vs_0"], "results/rigor/rigor.json::psr_dsr.rows[v2_oos].psr_vs_0")
    LL = J("results/lowloss/results.json")
    books = LL["runs"]["a_burned_oos_nonblind"]["books"]
    for per, book, ser in (("is", "u1_is", "v2safe_is"), ("oos", "u1_oos", "v2safe_oos")):
        b = books[book]["v2_safe"]
        sm = RG["sharpe_moments"][ser]
        sb = f"results/lowloss/results.json::runs.a_burned_oos_nonblind.books.{book}.v2_safe"
        sr0 = f"results/rigor/rigor.json::sharpe_moments.{ser}"
        N.add(f"v2s.{per}.sr", num(sm["sharpe_ann"], 1), sm["sharpe_ann"], sr0 + ".sharpe_ann")
        N.add(f"v2s.{per}.sr_ci", ci(RG["bootstrap"][ser]["sharpe_ann_ci95"], 1), RG["bootstrap"][ser]["sharpe_ann_ci95"],
              f"results/rigor/rigor.json::bootstrap.{ser}.sharpe_ann_ci95")
        N.add(f"v2s.{per}.dsr", f"{rows[ser]['dsr_min_N3410']:.3f}", rows[ser]["dsr_min_N3410"],
              f"results/rigor/rigor.json::psr_dsr.rows[{ser}].dsr_min_N3410 (N includes the v2-safe grid)")
        N.add(f"v2s.{per}.c", sgn(b["per_share_c"]), b["per_share_c"], sb + ".per_share_c")
        N.add(f"v2s.{per}.ci", ci(b["per_share_ci_c"]), b["per_share_ci_c"], sb + ".per_share_ci_c")
        ret = sm["mean_daily_ret_pct"] * 365
        vol = sm["sd_daily_usd"] / sm["capital_usd"] * math.sqrt(365) * 100
        N.add(f"v2s.{per}.ret", pct(ret, 0), ret, "D: " + sr0 + ".mean_daily_ret_pct x 365")
        N.add(f"v2s.{per}.vol", pct(vol, 1), vol, "D: " + sr0 + ".sd_daily_usd / capital_usd x sqrt(365)")
        N.add(f"v2s.{per}.dd", pct(b["max_dd_pct_cap"], 1), b["max_dd_pct_cap"], sb + ".max_dd_pct_cap")
        N.add(f"v2s.{per}.worstmonth", usd(b["worst_month_usd"], signed=True), b["worst_month_usd"], sb + ".worst_month_usd")
        to = b["usd_traded"] / b["capital_usd"] / b["calendar_days"] * 365
        N.add(f"v2s.{per}.turnover", intc(to), to, "D: " + sb + ".usd_traded / capital_usd / calendar_days x 365")
        N.add(f"v2s.{per}.skew", sgn(sm["skew"]), sm["skew"], sr0 + ".skew")
        N.add(f"v2s.{per}.cap", usd(b["capital_usd"]), b["capital_usd"], sb + ".capital_usd")
        # the same turnover formula reproduces v2's committed figure (note_metrics.json)
        v2b = books[book]["v2"]
        to2 = v2b["usd_traded"] / v2b["capital_usd"] / v2b["calendar_days"] * 365
        assert abs(to2 - N.raw(f"v2.{per}.turnover")) < 1.0, (per, to2, N.raw(f"v2.{per}.turnover"))
    u2 = LL["runs"]["b_u2_blind"]
    v = u2["books"]["u2_oos"]["v2_safe"]
    N.add("v2s.u2.c", sgn(v["per_share_c"]), v["per_share_c"], "results/lowloss/results.json::runs.b_u2_blind.books.u2_oos.v2_safe.per_share_c")
    N.add("v2s.u2.ci", ci(v["per_share_ci_c"]), v["per_share_ci_c"], "results/lowloss/results.json::runs.b_u2_blind.books.u2_oos.v2_safe.per_share_ci_c")
    N.add("v2s.u2.is.c", sgn(u2["books"]["u2_is"]["v2_safe"]["per_share_c"]), u2["books"]["u2_is"]["v2_safe"]["per_share_c"],
          "results/lowloss/results.json::runs.b_u2_blind.books.u2_is.v2_safe.per_share_c")
    N.add("v2s.u2.verdict", u2["primary"]["verdict"], u2["primary"]["verdict"], "results/lowloss/results.json::runs.b_u2_blind.primary.verdict")
    SZ = J("research/v2/sizing/results.json")
    N.add("sel.sizing.n", intc(SZ["variant_count"]["policies"]), SZ["variant_count"]["policies"],
          "research/v2/sizing/results.json::variant_count.policies")
    N.add("sel.sizing.pick", SZ["recommended_policy"], SZ["recommended_policy"],
          "research/v2/sizing/results.json::recommended_policy")
    pb = RG["pbo_cscv"]["lowloss_24_sharpe"]
    N.add("rig.pbo.n", intc(pb["N_variants"]), pb["N_variants"], "results/rigor/rigor.json::pbo_cscv.lowloss_24_sharpe.N_variants")
    N.add("rig.pbo.splits", intc(pb["n_splits"]), pb["n_splits"], "results/rigor/rigor.json::pbo_cscv.lowloss_24_sharpe.n_splits")
    N.add("rig.pbo.S", intc(pb["S_blocks"]), pb["S_blocks"], "results/rigor/rigor.json::pbo_cscv.lowloss_24_sharpe.S_blocks")
    N.add("rig.pbo.logit_med", num(pb["logit"]["median"], 2), pb["logit"]["median"],
          "results/rigor/rigor.json::pbo_cscv.lowloss_24_sharpe.logit.median")
    # ---------------------------------------------------------------- CV models, engine, pipeline (Table 2)
    RN = J("results/spin/tt/test/report_numbers.json")
    s50 = RN["snapshot_spin"]["50ms"]
    N.add("spin.tt.tp50", intc(s50["tp"]), s50["tp"], "results/spin/tt/test/report_numbers.json::snapshot_spin.50ms.tp")
    N.add("spin.tt.calls50", intc(s50["calls"]), s50["calls"], "results/spin/tt/test/report_numbers.json::snapshot_spin.50ms.calls")
    SP = J("results/spin/tennis/key_numbers.json")
    N.add("spin.out.prec200", f"{SP['bls']['pout95_precision']['200']:g}", SP["bls"]["pout95_precision"]["200"],
          "results/spin/tennis/key_numbers.json::bls.pout95_precision.200")
    N.add("spin.out.rec200", num(SP["bls"]["pout95_recall"]["200"], 2), SP["bls"]["pout95_recall"]["200"],
          "results/spin/tennis/key_numbers.json::bls.pout95_recall.200")
    N.add("spin.rpm200", num(SP["bls"]["rpm_err_med_abs"]["200"], 1), SP["bls"]["rpm_err_med_abs"]["200"],
          "results/spin/tennis/key_numbers.json::bls.rpm_err_med_abs.200")
    rr = SP["baseline"]["sd_cm"]["200"] / SP["bls"]["sd_cm"]["200"]
    N.add("spin.ratio200", f"{rr:.0f}", rr, "D: key_numbers.json baseline.sd_cm.200 / bls.sd_cm.200")
    E2 = J("results/e2e/summary.json")
    bud = E2["budget_with_1s_simulated_feed"]
    N.add("e2e.net", num(bud["network_one_way_ms"]["p50"], 0), bud["network_one_way_ms"]["p50"],
          "results/e2e/summary.json::budget_with_1s_simulated_feed.network_one_way_ms.p50")
    N.add("e2e.margin", intc(bud["margin_to_requirement_ms"]["p50"]), bud["margin_to_requirement_ms"]["p50"],
          "results/e2e/summary.json::budget_with_1s_simulated_feed.margin_to_requirement_ms.p50")
    N.add("e2e.req", intc(bud["requirement_ms"]), bud["requirement_ms"], "results/e2e/summary.json::budget_with_1s_simulated_feed.requirement_ms")
    N.add("e2e.p99", intc(bud["total_ms"]["p99"]), bud["total_ms"]["p99"], "results/e2e/summary.json::budget_with_1s_simulated_feed.total_ms.p99")
    dl = N.raw("e2e.ours") + bud["network_one_way_ms"]["p50"]
    N.add("e2e.delta", intc(dl), dl, "D: e2e.ours + e2e.net (p50, ms)")
    N.add("e2e.delta_s", num(dl / 1000, 3), dl / 1000, "D: (e2e.ours + e2e.net) / 1000")
    WL = J("results/webrtc/latency.json")
    legs = [st["transport_only"]["video_leg_ms"]["p50"] for st in WL["settings"].values()
            if isinstance(st.get("transport_only"), dict) and "video_leg_ms" in st["transport_only"]]
    N.add("webrtc.leg", f"{min(legs):.0f}–{max(legs):.0f}", legs,
          "results/webrtc/latency.json::settings[*].transport_only.video_leg_ms.p50 (min-max over settings)")
    # ---------------------------------------------------------------- capacity in $ (Section 7, Fig. 4)
    CAPJ = J("results/capacity/capacity.json")
    CAPA = CAPJ["answers"]["cv"]
    for per, P in (("is", "IS"), ("oos", "burned_OOS")):
        a = CAPA[f"lagcal|phi0.5|cov10|g1|{P}"]
        s0 = f"results/capacity/capacity.json::answers.cv.lagcal|phi0.5|cov10|g1|{P}"
        pm_ = a["pnl_max"]
        N.add(f"capcv.pmax.{per}", usd(round(pm_["capital_usd"], -3)), pm_["capital_usd"], s0 + ".pnl_max.capital_usd")
        N.add(f"capcv.pmax.{per}.day", usd(pm_["pnl_per_day_usd"]), pm_["pnl_per_day_usd"], s0 + ".pnl_max.pnl_per_day_usd")
        N.add(f"capcv.pmax.{per}.sr", num(pm_["sharpe_ann"], 1), pm_["sharpe_ann"], s0 + ".pnl_max.sharpe_ann")
        for key, k in (("licence_low", "low"), ("licence_central", "central")):
            cn = a["fixed_costs"][key]["capital_needed_usd"]
            N.add(f"capcv.{k}.{per}", usd(round(cn, -3)) if cn else "not covered", cn, s0 + f".fixed_costs.{key}.capital_needed_usd")
        sr_ = a["sharpe_ref_smallest_size"]
        N.add(f"capcv.sr0.{per}", num(sr_, 1), sr_, s0 + ".sharpe_ref_smallest_size")
    lc = CAPA["lagcal|phi0.5|cov10|g1|IS"]["at_half_sharpe"]["last_cell_above"]
    md = CAPJ["market_denominators"]["cv_periods"]["IS"]
    N.add("capcv.notional", usd(lc["notional_usd_per_day"]), lc["notional_usd_per_day"],
          "results/capacity/capacity.json::answers.cv.lagcal|phi0.5|cov10|g1|IS.at_half_sharpe.last_cell_above.notional_usd_per_day")
    N.add("cap.inplay", f"${md['inplay_usd'] / 1e6:.2f}M", md["inplay_usd"], "results/capacity/capacity.json::market_denominators.cv_periods.IS.inplay_usd")
    N.add("cap.fastq", usd(md["fasttier_q_usd"]), md["fasttier_q_usd"], "results/capacity/capacity.json::market_denominators.cv_periods.IS.fasttier_q_usd")
    sh1 = lc["notional_usd_per_day"] / md["inplay_usd"] * 100
    assert abs(sh1 - N.raw("capcv.share_inplay")) < 0.01, (sh1, N.raw("capcv.share_inplay"))
    # ---------------------------------------------------------------- Calculations appendix: worked examples
    sm = RG["sharpe_moments"]
    for ser, k in (("v2_is", "is"), ("v2_oos", "oos")):
        N.add(f"calc.{k}.mean", usd(sm[ser]["mean_daily_usd"], 2), sm[ser]["mean_daily_usd"], f"results/rigor/rigor.json::sharpe_moments.{ser}.mean_daily_usd")
        N.add(f"calc.{k}.sd", usd(sm[ser]["sd_daily_usd"], 2), sm[ser]["sd_daily_usd"], f"results/rigor/rigor.json::sharpe_moments.{ser}.sd_daily_usd")
        N.add(f"calc.{k}.T", intc(sm[ser]["T_days"]), sm[ser]["T_days"], f"results/rigor/rigor.json::sharpe_moments.{ser}.T_days")
        N.add(f"calc.{k}.srd", num(sm[ser]["sharpe_daily"], 3), sm[ser]["sharpe_daily"], f"results/rigor/rigor.json::sharpe_moments.{ser}.sharpe_daily")
        N.add(f"calc.{k}.sr", num(sm[ser]["sharpe_ann"], 2), sm[ser]["sharpe_ann"], f"results/rigor/rigor.json::sharpe_moments.{ser}.sharpe_ann")
        N.add(f"calc.{k}.skew", num(sm[ser]["skew"], 3), sm[ser]["skew"], f"results/rigor/rigor.json::sharpe_moments.{ser}.skew")
        N.add(f"calc.{k}.kurt", num(sm[ser]["kurtosis"], 2), sm[ser]["kurtosis"], f"results/rigor/rigor.json::sharpe_moments.{ser}.kurtosis")
        N.add(f"calc.{k}.cap", usd(sm[ser]["capital_usd"]), sm[ser]["capital_usd"], f"results/rigor/rigor.json::sharpe_moments.{ser}.capital_usd")
    N.add("calc.sqrt365", num(math.sqrt(365), 3), math.sqrt(365), "D: sqrt(365)")
    # Sortino of v2 OOS from the committed daily file (zero-filled calendar days), checked against lowloss
    dly = pd.read_csv(ROOT / "results/lowloss/daily.csv")
    x = dly[(dly.run == "a") & (dly.book == "u1_oos") & (dly.policy == "v2")].copy()
    x["date"] = pd.to_datetime(x.date)
    cal = pd.date_range(books["u1_oos"]["v2"]["calendar"][0], books["u1_oos"]["v2"]["calendar"][1])
    sday = x.set_index("date").pnl_usd.reindex(cal, fill_value=0.0)
    ddv = float(np.sqrt(np.mean(np.minimum(sday, 0.0) ** 2)))
    so = float(sday.mean() / ddv * math.sqrt(365))
    assert abs(so - books["u1_oos"]["v2"]["sortino_ann"]) < 1e-6, (so, books["u1_oos"]["v2"]["sortino_ann"])
    N.add("calc.so.dd", usd(ddv, 2), ddv, "D: results/lowloss/daily.csv[a,u1_oos,v2] sqrt(mean(min(d,0)^2)), zero-filled calendar days")
    N.add("calc.so", num(so, 1), so, "results/lowloss/results.json::runs.a_burned_oos_nonblind.books.u1_oos.v2.sortino_ann")
    mdd = books["u1_oos"]["v2"]["max_dd_usd"]
    N.add("calc.mdd", usd(mdd), mdd, "results/lowloss/results.json::runs.a_burned_oos_nonblind.books.u1_oos.v2.max_dd_usd")
    N.add("calc.mdd.pct", pct(mdd / sm["v2_oos"]["capital_usd"] * 100, 2), mdd / sm["v2_oos"]["capital_usd"], "D: calc.mdd / capital")
    # PSR and DSR of v2 OOS, recomputed here and checked against rigor.json
    mo = sm["v2_oos"]
    srd, T_, g3, g4 = mo["sharpe_daily"], mo["T_days"], mo["skew"], mo["kurtosis"]

    def psr(sr_, sr0_):
        return float(norm.cdf((sr_ - sr0_) * math.sqrt(T_ - 1) / math.sqrt(1 - g3 * sr_ + (g4 - 1) / 4 * sr_ ** 2)))
    p0 = psr(srd, 0.0)
    assert abs(p0 - rows["v2_oos"]["psr_vs_0"]) < 1e-9
    gam = 0.5772156649015329
    Nn = RG["psr_dsr"]["N"]["all_NOTE_s8"]
    z1, z2 = norm.ppf(1 - 1 / Nn), norm.ppf(1 - 1 / (Nn * math.e))
    sr0d = math.sqrt(1 / (T_ - 1)) * ((1 - gam) * z1 + gam * z2)
    dsr_ = psr(srd, sr0d)
    assert abs(dsr_ - rows["v2_oos"]["dsr"]["N3386/null"]["dsr"]) < 1e-9
    N.add("calc.z1", num(z1, 3), z1, "D: Phi^-1(1 - 1/N), N = rig.N3386")
    N.add("calc.z2", num(z2, 3), z2, "D: Phi^-1(1 - 1/(N e))")
    N.add("calc.sr0d", num(sr0d, 3), sr0d, "D: sqrt(1/(T-1)) ((1-gamma) z1 + gamma z2)")
    N.add("calc.sr0a", num(sr0d * math.sqrt(365), 2), sr0d * math.sqrt(365), "results/rigor/rigor.json::psr_dsr.rows[v2_oos].dsr.N3386/null.sr0_ann")
    N.add("calc.psr0", f"{p0:.3f}", p0, "results/rigor/rigor.json::psr_dsr.rows[v2_oos].psr_vs_0")
    N.add("calc.dsr", f"{dsr_:.3f}", dsr_, "results/rigor/rigor.json::psr_dsr.rows[v2_oos].dsr.N3386/null.dsr")
    bs = RG["bootstrap"]["v2_oos"]
    N.add("calc.boot.se", num(bs["sharpe_ann_boot_se"], 2), bs["sharpe_ann_boot_se"], "results/rigor/rigor.json::bootstrap.v2_oos.sharpe_ann_boot_se")
    # factor regression (alpha.json)
    fc = J("results/alpha/alpha.json")["C_factor_neutral"]["IS_committed_spec"]
    N.add("calc.ff.alpha", num(fc["alpha_pct_per_day"], 3) + "%", fc["alpha_pct_per_day"], "results/alpha/alpha.json::C_factor_neutral.IS_committed_spec.alpha_pct_per_day")
    for f_ in ("MktRF", "SMB", "HML", "Mom"):
        N.add(f"calc.ff.{f_}", num(fc["betas"][f_], 3), fc["betas"][f_], f"results/alpha/alpha.json::C_factor_neutral.IS_committed_spec.betas.{f_}")
        N.add(f"calc.ff.{f_}.t", num(fc["betas_t"][f_], 2), fc["betas_t"][f_], f"results/alpha/alpha.json::C_factor_neutral.IS_committed_spec.betas_t.{f_}")
    # taker fee in cents per share and bps of notional at two prices
    r_ = N.raw("fee.rate")
    for q, k in ((0.5, "q50"), (0.8, "q80")):
        c_ = r_ * q * (1 - q) * 100
        N.add(f"calc.fee.{k}.c", num(c_, 2), c_, "D: r q (1-q) x 100 cents, r = fee.rate")
        N.add(f"calc.fee.{k}.bps", intc(1e4 * r_ * (1 - q)), 1e4 * r_ * (1 - q), "D: 10,000 r (1-q)")
    # Markov leverage: two states of an even ATP best-of-three (src/markov.py; serve-point rate TOUR_SERVE['atp'])
    from src.markov import TennisModel, State, TOUR_SERVE
    ps = TOUR_SERVE["atp"]
    tm = TennisModel(ps, ps)
    s_start = State()
    s_bp = State(sa=1, sb=1, ga=5, gb=5, pa=2, pb=3, server=0)
    for st_, k in ((s_start, "start"), (s_bp, "bp")):
        up, dn = tm.step(st_, True), tm.step(st_, False)
        vu = 1.0 if up is None else tm.win_prob(up)
        vd = 0.0 if dn is None else tm.win_prob(dn)
        N.add(f"calc.mk.{k}.p", pct(tm.win_prob(st_) * 100, 1), tm.win_prob(st_), "D: src/markov.py TennisModel.win_prob")
        N.add(f"calc.mk.{k}.up", pct(vu * 100, 1), vu, "D: src/markov.py win_prob after the point is won")
        N.add(f"calc.mk.{k}.dn", pct(vd * 100, 1), vd, "D: src/markov.py win_prob after the point is lost")
        N.add(f"calc.mk.{k}.lev", pct(tm.leverage(st_) * 100, 1), tm.leverage(st_), "D: src/markov.py TennisModel.leverage")
    N.add("calc.mk.ps", f"{ps:.3f}", ps, "src/markov.py::TOUR_SERVE['atp']")
    # latency budget example: measured delta, the venue delay, the pre-registered L and the reprice percentiles
    LTb = J("research/v2/latency/results.json")["summary"]["m1"]["book_vs_official_T_s"]
    N.add("calc.R.p90", num(LTb["p90"], 2), LTb["p90"], "research/v2/latency/results.json::summary.m1.book_vs_official_T_s.p90")
    d_s = N.raw("e2e.delta_s")
    vmed = N.raw("cv.pre.lag") + LTb["median"] - N.raw("venue.delay") - d_s
    v90 = N.raw("cv.pre.lag") + LTb["p90"] - N.raw("venue.delay") - d_s
    N.add("calc.vmax.med", num(vmed, 2), vmed, "D: L + R_median - D - delta (pre-registered L)")
    N.add("calc.vmax.p90", num(v90, 2), v90, "D: L + R_p90 - D - delta (pre-registered L)")
    # capital and return on capital (v2 IS)
    pk = books["u1_is"]["v2"]["peak_locked_usd"]
    N.add("calc.peak", usd(pk), pk, "results/lowloss/results.json::runs.a_burned_oos_nonblind.books.u1_is.v2.peak_locked_usd")
    roc = sm["v2_is"]["mean_daily_usd"] * 365 / sm["v2_is"]["capital_usd"] * 100
    N.add("calc.roc", pct(roc, 0), roc, "D: mean daily $ x 365 / capital (v2 IS)")
    # ---------------------------------------------------------------- Everything we tested (appendix table)
    LF = J("research/v2/livefill/results.json")
    ins = next(m_ for m_ in LF["by_mode"] if m_["mode"] == "inside")
    N.add("ev.livefill.fill30", pct(ins["fill_30s"] * 100, 0), ins["fill_30s"], "research/v2/livefill/results.json::by_mode[inside].fill_30s")
    N.add("ev.livefill.post", sgn(-ins["post_fill_30s_c"], 1), -ins["post_fill_30s_c"],
          "research/v2/livefill/results.json::by_mode[inside].post_fill_30s_c (sign: mid move against the seller)")
    EXr = J("research/v2/exit/results.json")["recommended"]
    N.add("ev.exit.c", sgn(EXr["regime_1s5pct_per_share_c"]), EXr["regime_1s5pct_per_share_c"],
          "research/v2/exit/results.json::recommended.regime_1s5pct_per_share_c")
    N.add("ev.exit.ci", ci(EXr["regime_1s5pct_ci_c"]), EXr["regime_1s5pct_ci_c"], "research/v2/exit/results.json::recommended.regime_1s5pct_ci_c")
    N.add("ev.exit.n", intc(J("research/v2/exit/results.json")["n_variants"]), J("research/v2/exit/results.json")["n_variants"],
          "research/v2/exit/results.json::n_variants")
    SLr = J("research/v2/selection/results.json")
    nest = SLr["series"]["nested"]["all"]
    N.add("ev.sel.c", sgn(nest["net_res_c"]), nest["net_res_c"], "research/v2/selection/results.json::series.nested.all.net_res_c")
    N.add("ev.sel.ci", ci(nest["net_res_ci_c"]), nest["net_res_ci_c"], "research/v2/selection/results.json::series.nested.all.net_res_ci_c")
    N.add("ev.sel.base", sgn(SLr["series"]["baseline"]["all"]["net_res_c"]), SLr["series"]["baseline"]["all"]["net_res_c"],
          "research/v2/selection/results.json::series.baseline.all.net_res_c")
    N.add("ev.sel.n", intc(SLr["variant_count"]["total"]), SLr["variant_count"]["total"], "research/v2/selection/results.json::variant_count.total")
    CM = J("research/v2/crossmarket/analysis.json")
    lw = CM["lean_maker"]["wf"]
    N.add("ev.cm.c", sgn(lw["mean_pnl_per_share_c"]), lw["mean_pnl_per_share_c"], "research/v2/crossmarket/analysis.json::lean_maker.wf.mean_pnl_per_share_c")
    N.add("ev.cm.ci", ci(lw["ci95_pnl_per_share_c"]), lw["ci95_pnl_per_share_c"], "research/v2/crossmarket/analysis.json::lean_maker.wf.ci95_pnl_per_share_c")
    N.add("ev.cm.n", intc(CM["n_variants"]), CM["n_variants"], "research/v2/crossmarket/analysis.json::n_variants")
    KL = J("research/v2/kalshi/out/leadlag_summary.json")
    N.add("ev.kalshi.first", pct(KL["lead_all"]["p_kalshi_first"] * 100, 1), KL["lead_all"]["p_kalshi_first"],
          "research/v2/kalshi/out/leadlag_summary.json::lead_all.p_kalshi_first")
    N.add("ev.kalshi.lead", f"{KL['lead_all']['median_lead_s']:g}", KL["lead_all"]["median_lead_s"],
          "research/v2/kalshi/out/leadlag_summary.json::lead_all.median_lead_s")
    N.add("ev.kalshi.n", intc(KL["events_both_moved"]), KL["events_both_moved"], "research/v2/kalshi/out/leadlag_summary.json::events_both_moved")
    v0p = SW["video_own120"]["tournament"]["0"]
    for per, P in (("is", "IS"), ("oos", "burned_OOS")):
        N.add(f"ev.t0.v0.{per}", usd(v0p[P]["usd_per_day"], signed=True), v0p[P]["usd_per_day"],
              f"results/tier0/latency_sweep.json::video_own120.tournament.0.{P}.usd_per_day")
    hl = J("research/v2/blocklag/results.json")
    N.add("ev.blocklag", num(hl["median_lag_s"], 2), hl["median_lag_s"], "research/v2/blocklag/results.json::median_lag_s")


def collect_evidence(N: Registry) -> None:
    """Keys added for the last revision (new keys only; every earlier key is unchanged): the tennis tracker on a real
    licensed rally, the rally-in-progress gate replayed on the engine's held-out call log, the parameter plateau
    (sizing grid, PBO across block choices, the latency curve) and the fast tier's months and decay in seconds."""
    # ---------------------------------------------------------------- real tennis footage (Pexels rally)
    TD = J("results/viz/v60_assets/tennis_real/tennis_detections.json")
    s0 = "results/viz/v60_assets/tennis_real/tennis_detections.json"
    st_ = TD["stats"]
    N.add("tn.real.frames", intc(st_["frames"]), st_["frames"], s0 + "::stats.frames")
    N.add("tn.real.ball", pct(st_["ball_detected_share"] * 100, 0), st_["ball_detected_share"], s0 + "::stats.ball_detected_share")
    N.add("tn.real.ball_n", intc(st_["ball_frames_detected"]), st_["ball_frames_detected"], s0 + "::stats.ball_frames_detected")
    qa = TD["qa"]
    mq = re.match(r"(\d+) of (\d+) sampled tracked positions are on the ball in play", qa["result_by_eye"])
    assert mq and int(mq.group(2)) == len(qa["frames"]), qa["result_by_eye"]
    N.add("tn.real.spot", f"{mq.group(1)}/{mq.group(2)}", [int(mq.group(1)), int(mq.group(2))], s0 + "::qa.result_by_eye (by-eye check of qa.frames)")
    ct = st_["court"]
    N.add("tn.real.court_frames", intc(ct["frames_registered"]), ct["frames_registered"], s0 + "::stats.court.frames_registered")
    N.add("tn.real.court_px", num(ct["line_fit_px_median_p90_max"][0], 2), ct["line_fit_px_median_p90_max"][0],
          s0 + "::stats.court.line_fit_px_median_p90_max[0]")
    # ---------------------------------------------------------------- rally gate (scripts/rally_gate_eval.py)
    RGE = J("results/engine/rally_gate_eval.json")
    s1 = "results/engine/rally_gate_eval.json::results.emit"
    ap = next(r for r in RGE["results"]["emit"].values() if r["a_priori"])
    sw = [r for r in RGE["results"]["emit"].values() if not r["a_priori"]]
    N.add("gate.s", f"{ap['gate_s']:.1f}", ap["gate_s"], f"{s1}.{ap['gate_s']:g}.gate_s (a priori value)")
    for k, f in (("gate.out.removed", "outside_flights_removed"), ("gate.out.total", "outside_flights_total"),
                 ("gate.between.removed", "between_rallies_removed"), ("gate.between.total", "between_rallies_total"),
                 ("gate.correct.kept", "correct_kept"), ("gate.correct.total", "correct_total")):
        N.add(k, f"{ap[f]:g}", ap[f], f"{s1}.{ap['gate_s']:g}.{f}")
    N.add("gate.hr", num(ap["outside_flights_per_hour_gated"], 0), ap["outside_flights_per_hour_gated"],
          f"{s1}.{ap['gate_s']:g}.outside_flights_per_hour_gated")
    lo = min(sw, key=lambda r: r["gate_s"])
    kept_lo = sorted({r["correct_kept"] for r in sw})
    N.add("gate.n", intc(len(RGE["results"]["emit"])), len(RGE["results"]["emit"]), f"{s1} (gate values run, none chosen)")
    N.add("gate.sweep", f"{min(r['gate_s'] for r in sw):g}–{max(r['gate_s'] for r in sw):g}",
          [r["gate_s"] for r in sw], f"{s1}.*.gate_s (sweep values)")
    N.add("gate.correct.kept_lo", f"{lo['correct_kept']:g}", lo["correct_kept"], f"{s1}.{lo['gate_s']:g}.correct_kept")
    N.add("gate.correct.kept_range", "–".join(f"{x:g}" for x in (kept_lo[0], kept_lo[-1])) if len(kept_lo) > 1 else f"{kept_lo[0]:g}",
          kept_lo, f"{s1}.*.correct_kept (min-max over the sweep)")
    lo_g = [r["gate_s"] for r in sw if r["correct_kept"] == lo["correct_kept"]]
    N.add("gate.lo_range", f"{min(lo_g):g}–{max(lo_g):g}", lo_g, f"{s1}.*.gate_s where correct_kept == gate.correct.kept_lo")
    # ---------------------------------------------------------------- plateau: sizing grid, PBO by block choice, latency curve
    pol = pd.read_csv(ROOT / "research/v2/sizing/out/policies.csv")
    pr = pol[(pol.measure == "res") & (pol.fee_mode == "actual")]
    cil = pr.per_share_ci_c.apply(lambda s_: json.loads(s_)[0])
    RGr = J("results/rigor/rigor.json")
    assert len(pr) == RGr["inputs"]["sizing_rebuild"]["n_res"] == int(N.raw("sel.sizing.n")), (len(pr), N.raw("sel.sizing.n"))
    sr_rng = RGr["psr_dsr"]["variance_sources"]["sizing_grid_55"]["sr_ann_range"]
    assert abs(sr_rng[0] - pr.sharpe_ann.min()) < 1e-9 and abs(sr_rng[1] - pr.sharpe_ann.max()) < 1e-9
    sp0 = "research/v2/sizing/out/policies.csv[measure == res, fee_mode == actual]"
    N.add("plat.sizing.pos", intc((cil > 0).sum()), int((cil > 0).sum()), sp0 + " count(per_share_ci_c[0] > 0)")
    N.add("plat.sizing.cilo", num(cil.min(), 2), float(cil.min()), sp0 + " min(per_share_ci_c[0])")
    N.add("plat.sizing.sr", f"{sr_rng[0]:.1f}–{sr_rng[1]:.1f}", sr_rng,
          "results/rigor/rigor.json::psr_dsr.variance_sources.sizing_grid_55.sr_ann_range")
    VF = J("research/rigor/out/verify.json")["pbo"]
    pk_ = [k for k in VF if k.startswith("sharpe")]
    pv = [VF[k]["pbo"] for k in pk_]
    assert abs(VF["sharpe"]["pbo"] - RGr["pbo_cscv"]["lowloss_24_sharpe"]["pbo"]) < 1e-12
    N.add("plat.pbo", f"{min(pv) * 100:.0f}–{max(pv) * 100:.0f}%", dict(zip(pk_, pv)),
          "research/rigor/out/verify.json::pbo.sharpe* (v2-safe grid, Sharpe rule; min-max over block choices)")
    SW = J("results/tier0/latency_sweep.json")["video_own120"]
    rises, ngrid = [], None
    for reading in ("tournament", "tournament_lagcal"):
        ks = sorted(SW[reading], key=float)
        ngrid = len(ks)
        for P in ("IS", "burned_OOS"):
            ys = [SW[reading][k][P]["usd_per_day"] for k in ks]
            rises += [b_ - a_ for a_, b_ in zip(ys, ys[1:])]
    N.add("plat.lat.n", intc(ngrid), ngrid, "results/tier0/latency_sweep.json::video_own120.tournament (grid of feed delays)")
    N.add("plat.lat.lo", f"{float(min(ks, key=float)):g}", float(min(ks, key=float)), "results/tier0/latency_sweep.json::video_own120 (smallest delay)")
    N.add("plat.lat.hi", f"{float(max(ks, key=float)):g}", float(max(ks, key=float)), "results/tier0/latency_sweep.json::video_own120 (largest delay)")
    N.add("plat.lat.rise", usd(max(rises), 2), max(rises),
          "D: largest rise in $ a day between neighbouring delays, pre-registered and post hoc readings, IS and burned OOS")
    # ---------------------------------------------------------------- fast tier: calendar months, decay in seconds
    AS = J("results/alpha/alpha.json")["A_source"]
    mo = [(m_["month"], m_["fast_net30_c"]) for P in ("IS", "OOS") for m_ in AS[P]["months"]]
    cal_m = sorted({m_ for m_, _ in mo})
    assert all(v_ > 0 for _, v_ in mo)
    N.add("ft.months.cal", intc(len(cal_m)), cal_m,
          "results/alpha/alpha.json::A_source.{IS,OOS}.months[*].fast_net30_c (calendar months, all > 0; Aug split at the hold-out)")
    DC = J("results/decay/decay.json")["tennis"]["subsets"]
    for per, P in (("is", "IS"), ("oos", "burned_OOS")):
        for b_, k in (("1-2", "12"), ("2-3", "23")):
            v_ = DC[P]["curves"]["fast"]["net30"][b_]["mean_c"]
            N.add(f"decay.fast.{k}.{per}", sgn(v_), v_, f"results/decay/decay.json::tennis.subsets.{P}.curves.fast.net30.{b_}.mean_c")


def collect_revision(N: Registry) -> None:
    """Keys added for the data-coverage and CV-forward revision (new keys only; every earlier key is unchanged): the
    real data behind each result (results/data_coverage.json, scripts/data_coverage.py), how charted points end, the
    single-camera out calls on real broadcast tennis (results/tennis_tracking/summary.json), the blind test's
    pre-registered secondary statistics, wallet concentration, the kill rules replayed in sample and the stale
    quotes seen from the maker side. Every value is read from a committed result file; nothing here evaluates."""
    # ---------------------------------------------------------------- real data behind each result
    DC = J("results/data_coverage.json")
    s0 = "results/data_coverage.json::"
    pu = DC["polymarket_backtest_universe"]
    assert pu["n_matches"] == N.raw("univ.matches"), (pu["n_matches"], N.raw("univ.matches"))
    assert pu["grand_slam"]["wimbledon"]["all"] == 0  # Wimbledon is a separate Polymarket series, outside the universe
    N.add("cov.pm.atp", intc(pu["by_series"]["atp"]), pu["by_series"]["atp"], s0 + "polymarket_backtest_universe.by_series.atp")
    N.add("cov.pm.wta", intc(pu["by_series"]["wta"]), pu["by_series"]["wta"], s0 + "polymarket_backtest_universe.by_series.wta")
    gs = pu["grand_slam"]
    N.add("cov.gs.all", intc(gs["total"]["all"]), gs["total"]["all"], s0 + "polymarket_backtest_universe.grand_slam.total.all")
    N.add("cov.gs.main", intc(gs["total"]["main_draw"]), gs["total"]["main_draw"],
          s0 + "polymarket_backtest_universe.grand_slam.total.main_draw")
    N.add("cov.gs.qual", intc(gs["total"]["qualifying"]), gs["total"]["qualifying"],
          s0 + "polymarket_backtest_universe.grand_slam.total.qualifying")
    for k, slam in (("ao", "australian_open"), ("rg", "roland_garros"), ("uso", "us_open")):
        N.add(f"cov.gs.{k}", intc(gs[slam]["all"]), gs[slam]["all"], s0 + f"polymarket_backtest_universe.grand_slam.{slam}.all")
    tp = DC["tier0_pool_1s_delay"]
    N.add("cov.pool.n", intc(tp["n_matches"]), tp["n_matches"], s0 + "tier0_pool_1s_delay.n_matches")
    N.add("cov.pool.gs", intc(tp["grand_slam"]["total"]["all"]), tp["grand_slam"]["total"]["all"],
          s0 + "tier0_pool_1s_delay.grand_slam.total.all")
    N.add("cov.pool.first", pd.Timestamp(tp["first_start"]).strftime("%b %-d"), tp["first_start"], s0 + "tier0_pool_1s_delay.first_start")
    tt = DC["tier0_traded_matches"]
    N.add("cov.t0.is", intc(tt["IS_mean"]), tt["IS_mean"], s0 + "tier0_traded_matches.IS_mean")
    N.add("cov.t0.oos", intc(tt["burned_OOS_mean"]), tt["burned_OOS_mean"], s0 + "tier0_traded_matches.burned_OOS_mean")
    vb = DC["v2_backtest_matches"]
    assert vb["IS"] == N.raw("v2.is.matches") and vb["burned_OOS"] == N.raw("v2.oos.matches"), (vb, N.raw("v2.is.matches"))
    N.add("cov.v2.is", intc(vb["IS"]), vb["IS"], s0 + "v2_backtest_matches.IS")
    N.add("cov.v2.oos", intc(vb["burned_OOS"]), vb["burned_OOS"], s0 + "v2_backtest_matches.burned_OOS")
    mc = DC["match_charting_project"]
    N.add("cov.mcp.n", intc(mc["n_matches"]), mc["n_matches"], s0 + "match_charting_project.n_matches")
    N.add("cov.mcp.men", intc(mc["men"]["n_matches"]), mc["men"]["n_matches"], s0 + "match_charting_project.men.n_matches")
    N.add("cov.mcp.women", intc(mc["women"]["n_matches"]), mc["women"]["n_matches"], s0 + "match_charting_project.women.n_matches")
    N.add("cov.mcp.points", intc(mc["n_points"]), mc["n_points"], s0 + "match_charting_project.n_points")
    yr = mc["men"]["years"] + mc["women"]["years"]
    N.add("cov.mcp.years", f"{min(yr)}–{str(max(yr))[2:]}", [min(yr), max(yr)], s0 + "match_charting_project.{men,women}.years")
    tn = DC["tracknet_broadcast_tennis"]
    N.add("cov.tn.matches", intc(tn["matches"]), tn["matches"], s0 + "tracknet_broadcast_tennis.matches")
    N.add("cov.tn.clips", intc(tn["clips"]), tn["clips"], s0 + "tracknet_broadcast_tennis.clips")
    N.add("cov.tn.frames", intc(tn["frames_labelled"]), tn["frames_labelled"], s0 + "tracknet_broadcast_tennis.frames_labelled")
    # how charted points end (the tier-0 simulation's point mix)
    PMX = J("results/tier0/inputs/point_mix.json")
    for k, f in (("out", "out"), ("net", "net"), ("win", "winner")):
        v = [PMX["men"][f], PMX["women"][f]]
        N.add(f"pm.{k}", f"{min(v) * 100:.0f}–{max(v) * 100:.0f}%", v, f"results/tier0/inputs/point_mix.json::{{men,women}}.{f}")
    # ---------------------------------------------------------------- out calls from one broadcast camera (TrackNet set)
    TT = J("results/tennis_tracking/summary.json")
    s1 = "results/tennis_tracking/summary.json::"
    nb = TT["n_bounces_evaluated"]
    assert nb == tn["bounces_evaluated"], (nb, tn["bounces_evaluated"])
    N.add("bt.bounces.test", intc(nb["test"]), nb["test"], s1 + "n_bounces_evaluated.test")
    N.add("bt.bounces.all", intc(nb["train"] + nb["test"]), nb, s1 + "n_bounces_evaluated.{train,test} (sum)")
    hl = TT["headline"]["tracknet"]
    e0 = hl["median_landing_err_cm"]["ground"]["0"]
    N.add("bt.err0", f"{e0:.0f}", e0, s1 + "headline.tracknet.median_landing_err_cm.ground.0")
    le = [v for k, v in hl["median_landing_err_cm"]["learned"].items() if 33 <= int(k) <= 300]
    N.add("bt.err.lead", f"{min(le) / 100:.1f}–{max(le) / 100:.1f}", le,
          s1 + "headline.tracknet.median_landing_err_cm.learned.{33..300} (min-max, m)")
    gr = hl["out_calls_margin_rule"]["ground"]
    for L in ("0", "33", "67", "100"):
        c = gr["test_by_lead"][L]
        N.add(f"bt.call.{L}", f"{c['tp']} of {c['calls']}", [c["tp"], c["calls"]],
              s1 + f"headline.tracknet.out_calls_margin_rule.ground.test_by_lead.{L}.{{tp,calls}}")
    r0 = gr["test_by_lead"]["0"]["recall"]
    assert abs(r0 - 0.5) < 1e-9, r0  # the text says "half the outs"
    N.add("bt.rec0", pct(r0 * 100, 0), r0, s1 + "headline.tracknet.out_calls_margin_rule.ground.test_by_lead.0.recall")
    ml = gr["max_lead_ms_with_train_precision_ge_95_and_3plus_calls"]
    assert ml == 0, ml  # the text says only the bounce-time call met the 95% train precision rule
    N.add("bt.maxlead", f"{ml}", ml, s1 + "headline.tracknet.out_calls_margin_rule.ground.max_lead_ms_with_train_precision_ge_95_and_3plus_calls")
    lb = TT["headline"]["labels"]["out_calls_margin_rule"]["ground"]["test_by_lead"]["67"]
    N.add("bt.lab67", f"{lb['tp']} of {lb['calls']}", [lb["tp"], lb["calls"]],
          s1 + "headline.labels.out_calls_margin_rule.ground.test_by_lead.67.{tp,calls}")
    da = TT["detector_accuracy_vs_labels"]
    assert "all 10 games" in da["note"]  # detector leakage: the pretrained weights saw frames of every game
    N.add("bt.det.prec", pct(da["test_games_8_10"]["precision_5px"] * 100, 0), da["test_games_8_10"]["precision_5px"],
          s1 + "detector_accuracy_vs_labels.test_games_8_10.precision_5px")
    N.add("bt.det.rec", pct(da["test_games_8_10"]["recall_5px"] * 100, 0), da["test_games_8_10"]["recall_5px"],
          s1 + "detector_accuracy_vs_labels.test_games_8_10.recall_5px")
    # ---------------------------------------------------------------- the blind test's pre-registered secondary statistics
    EX = J("results/expand/results.json")
    s2 = "results/expand/results.json::"
    N.add("u2.itf", intc(EX["universe"]["u2_series"]["itf"]), EX["universe"]["u2_series"]["itf"], s2 + "universe.u2_series.itf")
    for per in ("is", "oos"):
        fc = EX["fast_minus_others_u2"][f"u2_{per}"]["ci_c"]
        N.add(f"u2.fmo.{per}.ci", ci(fc), fc, s2 + f"fast_minus_others_u2.u2_{per}.ci_c")
    m30 = EX["markout30"]["u2_oos"]
    N.add("u2.m30.oos.c", sgn(m30["m30_per_share_c"]), m30["m30_per_share_c"], s2 + "markout30.u2_oos.m30_per_share_c")
    N.add("u2.m30.oos.ci", ci(m30["ci_c"]), m30["ci_c"], s2 + "markout30.u2_oos.ci_c")
    gl = subprocess.run(["git", "log", "--diff-filter=A", "--format=%h", "--", "research/v2/expand/PREREG.md"], cwd=ROOT,
                        capture_output=True, text=True).stdout.strip().splitlines()
    if not gl:
        raise KeyError("COURTSIDE: missing number u2.prereg.commit (git log)")
    N.add("u2.prereg.commit", gl[-1], gl[-1], "git log --diff-filter=A -- research/v2/expand/PREREG.md")
    # ---------------------------------------------------------------- causal engine Sharpe, concentration, kill rules, stale quotes
    CC = J("results/redteam/causal_cv.json")
    v = CC["cells_V1"]["tournament_lagcal"]["burned_OOS"]["sharpe_ann"]
    N.add("cv.eng.cal.oos.sr", num(v, 1), v, "results/redteam/causal_cv.json::cells_V1.tournament_lagcal.burned_OOS.sharpe_ann")
    FC = J("results/alpha/alpha.json")["F_concentration"]["OOS"]["wallets"]["ex_top5_wallets"]
    s3 = "results/alpha/alpha.json::F_concentration.OOS.wallets.ex_top5_wallets"
    N.add("conc.ex5.oos.c", sgn(FC["net_c_per_share"]), FC["net_c_per_share"], s3 + ".net_c_per_share")
    N.add("conc.ex5.oos.ci", ci(FC["ci95_c_match_clustered"]), FC["ci95_c_match_clustered"], s3 + ".ci95_c_match_clustered")
    KR = J("results/financials/pm_compute.json")["p25_kill_rules_is"]
    tr_ = KR["trailing_30d_edge_rule_v2_is"]
    nf = tr_["days_half"] + tr_["days_stopped"]
    assert nf == 0 and not KR["drawdown_5pct_stop_v2_is"]["fires"] and KR["daily_stop_1000_v2_is"]["fires_days"] == 0  # text: "none of these rules fires"
    N.add("risk.kill.days", intc(nf), nf, "results/financials/pm_compute.json::p25_kill_rules_is.trailing_30d_edge_rule_v2_is.{days_half,days_stopped} (sum)")
    LT = J("research/v2/latency/results.json")["summary"]["stale_depth"]
    N.add("liq.stale_post", usd(LT["post"]["median_usd"]), LT["post"]["median_usd"],
          "research/v2/latency/results.json::summary.stale_depth.post.median_usd")
    N.add("liq.stale.n", intc(LT["pre"]["n"]), LT["pre"]["n"], "research/v2/latency/results.json::summary.stale_depth.pre.n")
    # ---------------------------------------------------------------- per-match loss under the stated limits
    # (results/v2/risk/per_match_loss.json): the net cap bounds the open position, not the loss of a match
    PML = J("results/v2/risk/per_match_loss.json")
    s4 = "results/v2/risk/per_match_loss.json::"
    for per in ("is", "oos"):
        v = PML[per]["v2_uncapped"]["worst_match_pnl_usd"]
        N.add(f"risk.pm.worst.{per}", usd(v), v, s4 + f"{per}.v2_uncapped.worst_match_pnl_usd")
    assert PML["is"]["v2_uncapped"]["with_1000_daily_stop"]["days_changed_by_stop"] == 0  # text: the stop never fired
    # ---------------------------------------------------------------- per-wallet cap, pre-registered on IS, run once on the
    # burned OOS (non-blind; research/v2/risk/PREREG_wallet_cap.md, scripts/v2_wallet_cap.py)
    WC = J("results/v2/risk/wallet_cap.json")
    s5 = "results/v2/risk/wallet_cap.json::"
    fr = WC["frozen_rule"]
    assert fr["variant"] == "W1000_Ron" and fr["retire"] and WC["first_run"]
    N.add("wcap.W", usd(fr["W_usd_per_wallet_day"]), fr["W_usd_per_wallet_day"], s5 + "frozen_rule.W_usd_per_wallet_day")
    N.add("wcap.commit", WC["prereg"]["commit"].split()[0][:7], WC["prereg"]["commit"], s5 + "prereg.commit")
    N.add("wcap.verdict", WC["verdict"]["result"], WC["verdict"], s5 + "verdict")
    WI = J("results/v2/risk/wallet_cap_is.json")
    N.add("wcap.n", intc(len(WI["variants"])), len(WI["variants"]), "results/v2/risk/wallet_cap_is.json::variants (len; grid 6 x 2)")
    wo = WC["oos"]["with_cap"]
    N.add("wcap.oos.c", sgn(wo["per_share_c"]), wo["per_share_c"], s5 + "oos.with_cap.per_share_c")
    N.add("wcap.oos.ci", ci(wo["per_share_ci95_c_match"]), wo["per_share_ci95_c_match"], s5 + "oos.with_cap.per_share_ci95_c_match")
    N.add("wcap.oos.sr", num(wo["sharpe_ann_calendar"], 1), wo["sharpe_ann_calendar"], s5 + "oos.with_cap.sharpe_ann_calendar")
    N.add("wcap.oos.top5", pct(wo["top5_wallet_share_of_pnl"] * 100, 0), wo["top5_wallet_share_of_pnl"],
          s5 + "oos.with_cap.top5_wallet_share_of_pnl")
    N.add("wcap.oos.worstday", usd(wo["worst_day_usd"]), wo["worst_day_usd"], s5 + "oos.with_cap.worst_day_usd")
    bo = WC["oos"]["v2_uncapped"]
    assert abs(bo["top5_wallet_share_of_pnl"] - N.raw("conc.top5.oos")) < 1e-3, (bo["top5_wallet_share_of_pnl"], N.raw("conc.top5.oos"))
    N.add("wcap.base.oos.worstday", usd(bo["worst_day_usd"]), bo["worst_day_usd"], s5 + "oos.v2_uncapped.worst_day_usd")
    wi = WC["is_joint_run"]
    kept = wi["with_cap"]["pnl_usd"] / wi["v2_uncapped"]["pnl_usd"]
    N.add("wcap.is.cost", pct((1 - kept) * 100, 0), 1 - kept,
          "D: 1 - " + s5 + "is_joint_run.with_cap.pnl_usd / is_joint_run.v2_uncapped.pnl_usd")


def collect_integration(N: Registry) -> None:
    """Keys for the integration pass after the organizers' brief (new keys only; every earlier key is unchanged):
    the CV trader's return, volatility, drawdown, turnover, fee bps and fees-doubled result for every printed cell
    (results/tier0/cost_turnover.json), data problems, the fresh holdout ("a firm with a licensed 0.5 s feed",
    results/fresh_holdout/results.json, COUNTERFACTUAL), sponsor latency and the SQL reproduction
    (results/sponsors/evidence.json), the per-wallet cap and the true per-match loss bound (results/v2/risk/), the
    price-impact model (results/liquidity/impact.json), edge persistence (results/economics/persistence.json), PSR /
    MinTRL / haircut Sharpe and the copier stress (results/rigor/psr.json) and the CV teaser figure
    (results/cv_teaser/teaser_numbers.json). Every value is read from a committed result file (D: = arithmetic on
    such values); nothing here runs an evaluation. Wording fixes from the adversarial verifiers are applied where the
    numbers are used (scratchpad evidence_results.json and fresh_results.json of the integration session)."""
    # ---------------------------------------------------------------- the CV trader: every printed cell (Table 2)
    CT = J("results/tier0/cost_turnover.json")
    s0 = "results/tier0/cost_turnover.json::cells"
    assert CT["check"]["seeds_checked"] == 240 and CT["check"]["max_abs_pnl_diff_usd"] < 1e-3, CT["check"]
    SW = J("results/tier0/latency_sweep.json")["video_own120"]
    fee_bps, fx2_oos = [], []
    for rk in ("pre", "cal"):
        for vk in ("v05", "v1", "v3"):
            for per in ("is", "oos"):
                c = CT["cells"][f"{rk}|{vk}|{per}"]
                r, m_ = c["ratio_of_seed_means"], c["seed_mean"]
                src = f"{s0}.{rk}|{vk}|{per}"
                # consistency: the re-run's seed means are the published Table-2 cells
                assert abs(m_["pnl_per_day_usd"] - N.raw(f"sc.{rk}.{per}.{vk}.usd")) < 0.01, (rk, vk, per)
                assert abs(m_["sharpe_ann"] - N.raw(f"sc.{rk}.{per}.{vk}.sr")) < 0.01, (rk, vk, per)
                assert abs(m_["per_share_c"] - N.raw(f"sc.{rk}.{per}.{vk}.c")) < 0.01, (rk, vk, per)
                k = f"tab.cv.{rk}.{per}.{vk}"
                N.add(k + ".ret", pct(r["ann_return_pct"], 0), r["ann_return_pct"], src + ".ratio_of_seed_means.ann_return_pct")
                N.add(k + ".vol", pct(r["ann_vol_pct"], 1), r["ann_vol_pct"], src + ".ratio_of_seed_means.ann_vol_pct")
                N.add(k + ".dd", pct(r["max_dd_pct"], 1), r["max_dd_pct"], src + ".ratio_of_seed_means.max_dd_pct")
                N.add(k + ".to", intc(r["turnover_x_per_year"]), r["turnover_x_per_year"],
                      src + ".ratio_of_seed_means.turnover_x_per_year")
                N.add(k + ".fee", intc(m_["fee_bps_of_notional"]), m_["fee_bps_of_notional"], src + ".seed_mean.fee_bps_of_notional")
                N.add(k + ".fx2c", sgn(m_["fx2_per_share_c"]), m_["fx2_per_share_c"], src + ".seed_mean.fx2_per_share_c")
                N.add(k + ".fx2usd", usd(m_["fx2_pnl_per_day_usd"], signed=True), m_["fx2_pnl_per_day_usd"],
                      src + ".seed_mean.fx2_pnl_per_day_usd")
                ci_ = SW["tournament" if rk == "pre" else "tournament_lagcal"][{"v05": "0.5", "v1": "1", "v3": "3"}[vk]][
                    "IS" if per == "is" else "burned_OOS"]["net_c_per_share_ci95"]
                N.add(k + ".c0", "†" if ci_[0] <= 0 <= ci_[1] else "", ci_,
                      f"results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans 0)")
                fee_bps.append(m_["fee_bps_of_notional"])
                if per == "oos":
                    fx2_oos.append(m_["fx2_pnl_per_day_usd"])
    N.add("cv.fee_bps.range", f"{min(fee_bps):.0f}–{max(fee_bps):.0f}", [min(fee_bps), max(fee_bps)],
          f"{s0}.*.seed_mean.fee_bps_of_notional (min-max over the 12 cells)")
    assert max(fx2_oos) < 0  # the text says fees x2 turn every OOS cell negative
    N.add("cv.fx2.oos.best", usd(max(fx2_oos), signed=True), max(fx2_oos), f"{s0}.*|oos.seed_mean.fx2_pnl_per_day_usd (max)")
    CJ = J("results/v2/causal.json")
    for per, P in (("is", "is_eval"), ("oos", "burned_oos")):
        c0 = CJ[f"causal/{P}/slip0.0"]
        v = c0["total_pnl_usd"] / c0["days"]
        N.add(f"tab.v2.{per}.usd", usd(v, signed=True), v, f"D: results/v2/causal.json::causal/{P}/slip0.0 total_pnl_usd / days")
    # ---------------------------------------------------------------- data problems (point-in-time universe)
    ST = J("results/risk/risk_stats.json")["settlement"]["all"]["score_state_by_resolution"]
    s1 = "results/risk/risk_stats.json::settlement.all.score_state_by_resolution"
    N.add("data.walk", intc(ST["50/50"]["not_started"]), ST["50/50"]["not_started"], s1 + ".50/50.not_started")
    ret_ = ST["winner"]["incomplete"] + ST["50/50"]["incomplete"]
    N.add("data.retired", intc(ret_), ret_, s1 + ".{winner,50/50}.incomplete (sum)")
    rs = J("results/risk/risk_stats.json")["settlement"]["all"]["res_50_50"]
    N.add("data.res5050.n", intc(rs), rs, "results/risk/risk_stats.json::settlement.all.res_50_50")
    # ---------------------------------------------------------------- fresh holdout: a firm with a licensed 0.5 s feed
    FR = J("results/fresh_holdout/results.json")
    s2 = "results/fresh_holdout/results.json::"
    assert FR["prereg_commit"] == "dc95717" and FR["equivalence_check"]["agreement"]
    N.add("fresh.prereg.commit", FR["prereg_commit"], FR["prereg_commit"], s2 + "prereg_commit")
    N.add("fresh.prereg.time", pd.Timestamp(FR["prereg_committed_utc"]).strftime("%H:%M UTC"), FR["prereg_committed_utc"],
          s2 + "prereg_committed_utc")
    N.add("fresh.fetch.time", pd.Timestamp(FR["fetch"]["fetch_time_utc"]).strftime("%H:%M UTC"), FR["fetch"]["fetch_time_utc"],
          s2 + "fetch.fetch_time_utc")
    N.add("fresh.start", pd.Timestamp(FR["window"]["start_exclusive_utc"]).strftime("%b %-d, %H:%M UTC"),
          FR["window"]["start_exclusive_utc"], s2 + "window.start_exclusive_utc")
    cn = FR["counts"]
    N.add("fresh.eligible", intc(cn["eligible_matches"]), cn["eligible_matches"], s2 + "counts.eligible_matches")
    N.add("fresh.covered", intc(cn["covered_primary"]), cn["covered_primary"], s2 + "counts.covered_primary")
    N.add("fresh.days", intc(len(FR["days"])), len(FR["days"]), s2 + "days")
    N.add("fresh.excluded", intc(len(FR["fetch"]["dropped_live_calibration_matches"])), FR["fetch"]["dropped_live_calibration_matches"],
          s2 + "fetch.dropped_live_calibration_matches")
    tab = {(t["strategy"], t["reading"], t["V_s"]): t for t in FR["table"] if t["coverage"] == "cov10" and t["subset"] == "all_days"}
    nm_ = []
    for st in ("S1", "S2"):
        for rk in ("pre", "cal"):
            for vk, V in (("v05", 0.5), ("v1", 1.0), ("v3", 3.0)):
                t = tab[(st, rk, V)]
                k = f"fresh.{st.lower()}.{rk}.{vk}"
                src = s2 + f"table[{st},{rk},{V},cov10,all_days]"
                N.add(k + ".usd", usd(t["pnl_per_day_usd"], 1, signed=True), t["pnl_per_day_usd"], src + ".pnl_per_day_usd")
                lo, hi = t["pnl_per_day_ci95_usd"]
                N.add(k + ".ci", f"[{usd(lo, 0, signed=True)}, {usd(hi, 0, signed=True)}]", [lo, hi], src + ".pnl_per_day_ci95_usd")
                assert t["anecdotal"] if "anecdotal" in t else True
                nm_.append(t["n_matches"])
    N.add("fresh.traded.range", f"{min(nm_):.0f}–{max(nm_):.0f}", [min(nm_), max(nm_)],
          s2 + "table[*,cov10,all_days].n_matches (seed-mean matches with trades, min-max)")
    n05 = [tab[("S2", rk, 0.5)]["n_matches"] for rk in ("pre", "cal")]
    N.add("fresh.traded.s2v05", f"{min(n05):.0f}–{max(n05):.0f}", n05, s2 + "table[S2,*,0.5,cov10,all_days].n_matches")
    hr = [tab[("S2", rk, 0.5)]["hit_rate_pct"] for rk in ("pre", "cal")]
    N.add("fresh.hit.pre", pct(hr[0], 0), hr[0], s2 + "table[S2,pre,0.5,cov10,all_days].hit_rate_pct")
    N.add("fresh.hit.cal", pct(hr[1], 0), hr[1], s2 + "table[S2,cal,0.5,cov10,all_days].hit_rate_pct")
    LB = FR["licence_breakeven_at_V0.5 (IS / burned OOS)"]["values_usd_per_month"]
    LF = FR["licence_breakeven_at_V0.5 (fresh, anecdotal)"]["values_usd_per_month"]
    for per, key, src_ in (("is", "IS", LB), ("oos", "burned_OOS", LB), ("fresh", "fresh", LF)):
        for rk in ("pre", "cal"):
            v = src_[f"{key}|S2|{rk}|cov10|all_days"]["max_licence_usd_per_month"]
            N.add(f"fresh.lic.{per}.{rk}", usd(v, signed=per == "fresh"), v,
                  s2 + f"licence_breakeven_at_V0.5 ...values_usd_per_month.{key}|S2|{rk}|cov10|all_days.max_licence_usd_per_month")
    sh = FR["showcase"]
    N.add("fresh.show.title", sh["title"].split(": ", 1)[1].replace(" vs ", " v "), sh["title"], s2 + "showcase.title")
    N.add("fresh.show.event", f"{sh['series'].upper()} {sh['league']}", [sh["series"], sh["league"]], s2 + "showcase.{series,league}")
    N.add("fresh.show.inplay", f"${sh['inplay_usd'] / 1e3:.0f}k", sh["inplay_usd"], s2 + "showcase.inplay_usd")
    N.add("fresh.show.winner", sh["winner"].split()[-1], sh["winner"], s2 + "showcase.winner")
    for rk in ("pre", "cal"):
        v = sh["pnl_20_seed_mean_usd"][f"S2|{rk}|V0.5"]["mean_usd"]
        N.add(f"fresh.show.{rk}", usd(v, 1, signed=True), v, s2 + f"showcase.pnl_20_seed_mean_usd.S2|{rk}|V0.5.mean_usd")
    FN = J("results/scenario/fig_firm_05s_numbers.json")["showcase"]
    N.add("fresh.show.calls", intc(FN["simulated_calls_ledger_seed"]), FN["simulated_calls_ledger_seed"],
          "results/scenario/fig_firm_05s_numbers.json::showcase.simulated_calls_ledger_seed")
    # ---------------------------------------------------------------- sponsor evidence: measured network legs, SQL reproduction
    SE = J("results/sponsors/evidence.json")
    s3 = "results/sponsors/evidence.json::"
    pk = SE["paper_keys"]
    for k in ("vultr.matched", "vultr.lon_first", "vultr.adv.p50", "vultr.clock", "vultr.adv.lb", "vultr.lon.rtt",
              "vultr.fl.rtt", "e2e.lon.total", "e2e.fl.total", "e2e.worst.total", "e2e.worst.margin", "e2e.lon.margin",
              "snow.recomputed"):
        N.add(k, pk[k]["value"], pk[k]["raw"], s3 + f"paper_keys.{k} <- {pk[k]['source']}")
    hg = SE["budget"]["london_saving_vs_florida_ms"]["half_rtt_p50"]
    N.add("vultr.halfgap", intc(hg), hg, s3 + "budget.london_saving_vs_florida_ms.half_rtt_p50 (clock-free check)")
    sc_ = SE["budget"]["scenarios"]
    sh_ = [(SE["budget"]["inputs"]["feed_simulated_ms"] + SE["budget"]["inputs"]["venue_delay_ms"]) / sc_[s]["p50"]["total_ms"]
           for s in ("vultr_london_cold_half_rtt", "vultr_florida_cold_half_rtt")]
    N.add("e2e.feedhold.range", f"{min(sh_) * 100:.0f}–{max(sh_) * 100:.0f}%", sh_,
          "D: (feed 1,000 + hold 1,000 ms) / " + s3 + "budget.scenarios.vultr_{london,florida}_cold_half_rtt.p50.total_ms")
    rc = SE["snowflake"]["recheck"]
    assert rc["reproduced"] == rc["checked"] == 62 and not rc["failing"]
    N.add("snow.repro", f"{rc['reproduced']} of {rc['checked']}", [rc["reproduced"], rc["checked"]], s3 + "snowflake.recheck.{reproduced,checked}")
    N.add("snow.lookup", intc(rc["lookup_ok"]), rc["lookup_ok"], s3 + "snowflake.recheck.lookup_ok")
    # ---------------------------------------------------------------- per-wallet cap (verifier B's fixes) and per-match loss
    WC = J("results/v2/risk/wallet_cap.json")
    s4 = "results/v2/risk/wallet_cap.json::"
    wo, bo = WC["oos"]["with_cap"], WC["oos"]["v2_uncapped"]
    N.add("wcap.oos.pnl", usd(wo["pnl_usd"]), wo["pnl_usd"], s4 + "oos.with_cap.pnl_usd")
    N.add("wcap.base.oos.pnl", usd(bo["pnl_usd"]), bo["pnl_usd"], s4 + "oos.v2_uncapped.pnl_usd")
    N.add("wcap.oos.maxdd", usd(wo["max_dd_usd"]), wo["max_dd_usd"], s4 + "oos.with_cap.max_dd_usd")
    N.add("wcap.base.oos.maxdd", usd(bo["max_dd_usd"]), bo["max_dd_usd"], s4 + "oos.v2_uncapped.max_dd_usd")
    N.add("wcap.oos.sr_ci", ci(wo["sharpe_ann_ci95_stationary_bootstrap"], 1), wo["sharpe_ann_ci95_stationary_bootstrap"],
          s4 + "oos.with_cap.sharpe_ann_ci95_stationary_bootstrap")
    N.add("wcap.base.oos.sr", num(bo["sharpe_ann_calendar"], 1), bo["sharpe_ann_calendar"], s4 + "oos.v2_uncapped.sharpe_ann_calendar")
    N.add("wcap.base.oos.sr_ci", ci(bo["sharpe_ann_ci95_stationary_bootstrap"], 1), bo["sharpe_ann_ci95_stationary_bootstrap"],
          s4 + "oos.v2_uncapped.sharpe_ann_ci95_stationary_bootstrap")
    N.add("wcap.oos.ex5.c", sgn(wo["ex_top5"]["per_share_c"]), wo["ex_top5"]["per_share_c"], s4 + "oos.with_cap.ex_top5.per_share_c")
    N.add("wcap.base.oos.ex5.c", sgn(bo["ex_top5"]["per_share_c"]), bo["ex_top5"]["per_share_c"], s4 + "oos.v2_uncapped.ex_top5.per_share_c")
    N.add("wcap.oos.ci_wallet", ci(wo["per_share_ci95_c_wallet"]), wo["per_share_ci95_c_wallet"], s4 + "oos.with_cap.per_share_ci95_c_wallet")
    for k, d_ in (("cap_only", "decomposition_cap_only"), ("retire_only", "decomposition_retire_only")):
        v = WC["oos"][d_]["top5_wallet_share_of_pnl"]
        N.add(f"wcap.oos.top5.{k}", pct(v * 100, 0), v, s4 + f"oos.{d_}.top5_wallet_share_of_pnl")
    N.add("wcap.oos.wwd", usd(wo["worst_wallet_day_pnl_usd"]), wo["worst_wallet_day_pnl_usd"], s4 + "oos.with_cap.worst_wallet_day_pnl_usd")
    N.add("wcap.base.oos.wwd", usd(bo["worst_wallet_day_pnl_usd"]), bo["worst_wallet_day_pnl_usd"], s4 + "oos.v2_uncapped.worst_wallet_day_pnl_usd")
    wi = WC["is_joint_run"]
    kept = wi["with_cap"]["pnl_usd"] / wi["v2_uncapped"]["pnl_usd"]
    N.add("wcap.is.kept", pct(kept * 100, 0), kept, "D: " + s4 + "is_joint_run.with_cap.pnl_usd / is_joint_run.v2_uncapped.pnl_usd")
    N.add("wcap.is.sr", num(wi["with_cap"]["sharpe_ann_calendar"], 1), wi["with_cap"]["sharpe_ann_calendar"], s4 + "is_joint_run.with_cap.sharpe_ann_calendar")
    N.add("wcap.is.maxdd", usd(wi["with_cap"]["max_dd_usd"]), wi["with_cap"]["max_dd_usd"], s4 + "is_joint_run.with_cap.max_dd_usd")
    N.add("wcap.base.is.maxdd", usd(wi["v2_uncapped"]["max_dd_usd"]), wi["v2_uncapped"]["max_dd_usd"], s4 + "is_joint_run.v2_uncapped.max_dd_usd")
    N.add("wcap.is.top5", pct(wi["with_cap"]["top5_wallet_share_of_pnl"] * 100, 0), wi["with_cap"]["top5_wallet_share_of_pnl"],
          s4 + "is_joint_run.with_cap.top5_wallet_share_of_pnl")
    N.add("wcap.base.is.top5", pct(wi["v2_uncapped"]["top5_wallet_share_of_pnl"] * 100, 0), wi["v2_uncapped"]["top5_wallet_share_of_pnl"],
          s4 + "is_joint_run.v2_uncapped.top5_wallet_share_of_pnl")
    PML = J("results/v2/risk/per_match_loss.json")
    s5 = "results/v2/risk/per_match_loss.json::"
    for per in ("is", "oos"):
        u = PML[per]["v2_uncapped"]
        N.add(f"risk.pm.twosided.{per}", pct(u["share_matches_buying_both_sides"] * 100, 0), u["share_matches_buying_both_sides"],
              s5 + f"{per}.v2_uncapped.share_matches_buying_both_sides")
        N.add(f"risk.pm.p99.{per}", usd(u["p99_match_loss_usd"]), u["p99_match_loss_usd"], s5 + f"{per}.v2_uncapped.p99_match_loss_usd")
    b_ = PML["theoretical"]["bound_incl_fees_usd"]
    N.add("risk.pm.bound", usd(b_), b_, s5 + "theoretical.bound_incl_fees_usd (backtest's $3,000 gross cap per match; none in the live engine)")
    # ---------------------------------------------------------------- price impact (verifier C's fixes)
    IM = J("results/liquidity/impact.json")
    s6 = "results/liquidity/impact.json::"
    no = IM["data"]["IS"]["n_orders"]
    N.add("liq.orders.n", f"{no / 1e6:.1f} million", no, s6 + "data.IS.n_orders")
    N.add("liq.orders.matches", intc(IM["data"]["IS"]["n_matches"]), IM["data"]["IS"]["n_matches"], s6 + "data.IS.n_matches")
    nf = IM["temporary_IS"]["n_orders"]
    N.add("liq.orders.fit", f"{nf / 1e6:.1f} million", nf, s6 + "temporary_IS.n_orders (orders with a usable print-based mid)")
    bins = IM["temporary_IS"]["bins"]
    for k, i in (("top.small", 30), ("top.large", 37), ("mid.small", 14), ("mid.large", 21)):
        N.add(f"liq.temp.{k}", num(bins[i]["mean_c"], 2), bins[i]["mean_c"], s6 + f"temporary_IS.bins[{i}].mean_c")
    l30 = IM["permanent_IS"]["30"]["lambda_c_per_1k"]
    N.add("liq.lambda30", f"{min(l30):.2f}–{max(l30):.2f}", l30, s6 + "permanent_IS.30.lambda_c_per_1k (min-max over volume fifths)")
    lo30 = IM["permanent_OOS"]["30"]["lambda_c_per_1k"][4]
    N.add("liq.oos.lambda30.top", f"{lo30:.3f}", lo30, s6 + "permanent_OOS.30.lambda_c_per_1k[4] (highest-volume fifth)")
    N.add("liq.is.lambda30.top", f"{l30[4]:.3f}", l30[4], s6 + "permanent_IS.30.lambda_c_per_1k[4]")
    N.add("liq.M", f"{IM['model']['M']:.2f}", IM["model"]["M"], s6 + "model.M (post-jump book-walk multiplier)")
    N.add("liq.l2.reprices", intc(IM["l2"]["n_reprices"]), IM["l2"]["n_reprices"], s6 + "l2.n_reprices")
    N.add("liq.l2.matches", intc(IM["l2"]["n_matches"]), IM["l2"]["n_matches"], s6 + "l2.n_matches")
    npo = IM["phi_official_points"]["D_ge_3c"]["n_events"]
    N.add("liq.phi.official", intc(npo), npo, s6 + "phi_official_points.D_ge_3c.n_events")
    took = [IM["l2"]["phi_live_reprices"][t]["took_share_pooled"] for t in ("tau_2s", "tau_1s", "tau_0.25s")] + \
           [IM["phi_official_points"]["D_ge_3c"][t]["took_share_pooled"] for t in ("tau_2s", "tau_1s", "tau_0.25s")]
    N.add("liq.phi.took", f"{min(took) * 100:.0f}–{max(took) * 100:.0f}%", took,
          s6 + "l2.phi_live_reprices.tau_*.took_share_pooled and phi_official_points.D_ge_3c.tau_*.took_share_pooled (min-max)")
    gth = [IM["l2"]["phi_live_reprices"][t]["share_events_phi_lo_below_0.5"] for t in ("tau_2s", "tau_1s", "tau_0.25s")] + \
          [IM["phi_official_points"]["D_ge_3c"][t]["share_events_phi_lo_below_0.5"] for t in ("tau_2s", "tau_1s", "tau_0.25s")]
    N.add("liq.phi.gt_half", f"{min(gth) * 100:.0f}–{max(gth) * 100:.0f}%", gth,
          s6 + "...tau_*.share_events_phi_lo_below_0.5 (events where others took more than half; min-max)")
    cap_ = IM["capacity"]
    for k, var in (("none", "none"), ("central", "central"), ("cons", "conservative")):
        c = cap_[f"v2|{var}|burned_OOS"]
        N.add(f"liq.v2.half.oos.{k}", f"${c['capital_where_sharpe_halves_usd'] / 1e3:.1f}k", c["capital_where_sharpe_halves_usd"],
              s6 + f"capacity.v2|{var}|burned_OOS.capital_where_sharpe_halves_usd")
        N.add(f"liq.v2.1x.oos.{k}", usd(c["pnl_max"]["pnl_per_day_usd"]), c["pnl_max"]["pnl_per_day_usd"],
              s6 + f"capacity.v2|{var}|burned_OOS.pnl_max.pnl_per_day_usd")
    cc = cap_["v2|conservative|burned_OOS"]["pnl_max"]
    N.add("liq.v2.1x.oos.cons.ci", f"[{usd(cc['pnl_per_day_boot_lo'])}, {usd(cc['pnl_per_day_boot_hi'])}]",
          [cc["pnl_per_day_boot_lo"], cc["pnl_per_day_boot_hi"]], s6 + "capacity.v2|conservative|burned_OOS.pnl_max.pnl_per_day_boot_{lo,hi}")
    mv = [abs(cap_[f"cv_lagcal|best|central|{P}"]["capital_where_sharpe_halves_usd"] / cap_[f"cv_lagcal|best|none|{P}"]["capital_where_sharpe_halves_usd"] - 1)
          for P in ("IS", "burned_OOS")]
    assert max(mv) < 0.01  # text: "moves under 1%"
    N.add("liq.cv.half.move", "1%", mv, "D: |capacity.cv_lagcal|best|central|P / ...|none|P - 1| < 1% (P = IS, burned_OOS)")
    dr = [1 - cap_[f"cv_lagcal|best|conservative|{P}"]["pnl_max"]["pnl_per_day_usd"] / cap_[f"cv_lagcal|best|none|{P}"]["pnl_max"]["pnl_per_day_usd"]
          for P in ("IS", "burned_OOS")]
    N.add("liq.cv.pmax.drop", f"{min(dr) * 100:.0f}–{max(dr) * 100:.0f}%", dr,
          "D: 1 - capacity.cv_lagcal|best|conservative|P.pnl_max.pnl_per_day_usd / ...|none|P (P = IS, burned_OOS)")
    # ---------------------------------------------------------------- edge persistence (verifier D's fixes)
    PE = J("results/economics/persistence.json")
    s7 = "results/economics/persistence.json::"

    def pe(path):
        d = PE
        for k_ in path.split("."):
            d = d[k_]
        return d
    for k, path, f in (("pers.slope.net", "fits.linear_wls_cal11.slope_c_per_month.coef", lambda x: num(abs(x), 2)),
                       ("pers.slope.net.ci", "fits.linear_wls_cal11.slope_c_per_month.ci95", lambda x: f"{abs(x[1]):.2f}–{abs(x[0]):.2f}"),
                       ("pers.slope.gross", "fits.gross_linear_wls_cal11.slope_c_per_month.coef", lambda x: sgn(x, 2)),
                       ("pers.slope.gross.ci", "fits.gross_linear_wls_cal11.slope_c_per_month.ci95", ci),
                       ("pers.slope.fee", "fits.fee_linear_wls_cal11.slope_c_per_month.coef", lambda x: num(x, 2)),
                       ("pers.dnet", "composition.delta_net_c", lambda x: num(abs(x), 2)),
                       ("pers.dfee", "composition.fee_part_c", lambda x: num(abs(x), 2)),
                       ("pers.ddilution", "composition.entrant_dilution_c", lambda x: num(abs(x), 2)),
                       ("pers.inc.trend.ci", "composition.incumbents_gross_trend_jan_aug.month_level_primary.ci95", ci),
                       ("pers.zero.months", "projections.linear_wls_cal11.months_to_zero", lambda x: num(x, 1)),
                       ("pers.zero.ci", "projections.linear_wls_cal11.ci95", lambda x: f"{x[0]:.1f}–{x[1]:.1f}"),
                       ("pers.step.trend", "projections.step_model_may2026.trend_given_step_c_per_month", lambda x: sgn(x, 2)),
                       ("pers.step.trend.ci", "projections.step_model_may2026.trend_given_step_ci95", ci),
                       ("pers.befee", "projections.breakeven_fee_rate_pct.is_1s_5pct_prints", lambda x: pct(x, 1)),
                       ("pers.pool.mayaug", "profit.is_may_aug_mean_pnl30_usd_per_month", lambda x: f"${x / 1e3:.0f}k"),
                       ("pers.pool.elast", "profit.total_elasticity_wrt_wallets.elasticity.coef", lambda x: num(x, 2)),
                       ("pers.pool.elast.ci", "profit.total_elasticity_wrt_wallets.elasticity.ci95", ci),
                       ("pers.pool.pw.janmay", "profit.per_wallet_jan_may_mean_usd", usd),
                       ("pers.pool.pw.aug", "profit.per_wallet_aug_is_usd", usd),
                       ("pers.delay.may", "regime.natural_experiments.delay_3s_to_1s_may2026.net30.b_minus_a_c", lambda x: sgn(x, 2)),
                       ("pers.delay.may.ci", "regime.natural_experiments.delay_3s_to_1s_may2026.net30.ci95", ci),
                       ("pers.fee35.jul", "regime.natural_experiments.fee_3_to_5_jul2026.net30.b_minus_a_c", lambda x: num(abs(x), 2)),
                       ("pers.fee35.jul.ci", "regime.natural_experiments.fee_3_to_5_jul2026.net30.ci95", lambda x: f"{abs(x[1]):.2f}–{abs(x[0]):.2f}"),
                       ("ft.c.oos.only", "aug_overlap.oos_print_weighted_net30_c_oos_prints_only_derived", lambda x: sgn(x, 2))):
        v = pe(path)
        N.add(k, f(v), v, s7 + path)
    # ---------------------------------------------------------------- PSR, MinTRL, haircut Sharpe, copier (verifier E's fixes)
    PS = J("results/rigor/psr.json")
    s8 = "results/rigor/psr.json::"
    hd = PS["headline"]
    so = PS["series"]["v2_oos"]
    assert hd["N_tests"] == N.raw("var.total")
    for k, v, f, src in (("rig2.v2is.hlz_sr", hd["v2_is_hlz_sr_haircut_ann"], lambda x: num(x, 1), "headline.v2_is_hlz_sr_haircut_ann"),
                         ("rig2.v2oos.psr0", so["psr_sr0"], lambda x: f"{x:.3f}", "series.v2_oos.psr_sr0"),
                         ("rig2.v2oos.psr2", so["psr_sr2"], lambda x: f"{x:.2f}", "series.v2_oos.psr_sr2"),
                         ("rig2.v2oos.mintrl0", so["mintrl_days_sr0"], intc, "series.v2_oos.mintrl_days_sr0"),
                         ("rig2.v2oos.mintrl2", so["mintrl_days_sr2"], intc, "series.v2_oos.mintrl_days_sr2"),
                         ("rig2.v2oos.t", so["hlz"]["t_stat"], lambda x: num(x, 2), "series.v2_oos.hlz.t_stat"),
                         ("rig2.t_req", so["hlz"]["t_required_bonferroni_5pct"], lambda x: num(x, 2), "series.v2_oos.hlz.t_required_bonferroni_5pct"),
                         ("rig2.v2oos.days_req", so["hlz"]["days_required_at_this_sr"], intc, "series.v2_oos.hlz.days_required_at_this_sr"),
                         ("rig2.v2oos.hlz_sr", so["hlz"]["sr_haircut_ann_bonferroni"], lambda x: num(x, 0), "series.v2_oos.hlz.sr_haircut_ann_bonferroni"),
                         ("copier.is.c", hd["copier_central_is_c"], lambda x: sgn(x, 2), "headline.copier_central_is_c"),
                         ("copier.oos.c", hd["copier_central_oos_c"], lambda x: sgn(x, 2), "headline.copier_central_oos_c"),
                         ("copier.opt.is.c", hd["copier_same_prev_is_c"], lambda x: sgn(x, 2), "headline.copier_same_prev_is_c"),
                         ("copier.opt.oos.c", hd["copier_same_prev_oos_c"], lambda x: sgn(x, 2), "headline.copier_same_prev_oos_c"),
                         ("copier.opt.oos.ci", hd["copier_same_prev_oos_ci95_c"], ci, "headline.copier_same_prev_oos_ci95_c"),
                         ("cv.pre.psr0.is", hd["cv_pre_is_psr_sr0_seed_median"], lambda x: num(x, 2), "headline.cv_pre_is_psr_sr0_seed_median"),
                         ("cv.pre.psr0.oos", hd["cv_pre_oos_psr_sr0_seed_median"], lambda x: num(x, 2), "headline.cv_pre_oos_psr_sr0_seed_median")):
        N.add(k, f(v), v, s8 + src)
    ld = PS["copier"]["oos"]["central"]["share_priced_from_same_side_print"]
    li = PS["copier"]["is"]["central"]["share_priced_from_same_side_print"]
    N.add("copier.sameside", f"{ld * 100:.0f}–{li * 100:.0f}%", [ld, li], s8 + "copier.{oos,is}.central.share_priced_from_same_side_print")
    bl = PS["copier"]["definition"]["block_lag_s"]["median"]
    N.add("copier.lag", num(bl, 2), bl, s8 + "copier.definition.block_lag_s.median")
    co = PS["cv"]["cv_cal_oos"]
    n_pass = sum([co["psr_sr0_seed_median"] >= 0.95, co["psr_sr2_seed_median"] >= 0.95,
                  co["mintrl_sr0_seeds_track_long_enough"] > co["n_seeds"] / 2, co["mintrl_sr2_seeds_track_long_enough"] > co["n_seeds"] / 2,
                  co["hlz"]["sr_haircut_ann_bonferroni_seed_median"] > 0,
                  not (co["bootstrap_pooled_over_seeds"]["sharpe_ann_ci95"][0] <= 0)])
    N.add("rig2.cvcal.oos.pass", intc(n_pass), n_pass, "D: " + s8 + "cv.cv_cal_oos (PSR0, PSR2 seed medians >= 0.95; MinTRL met by most seeds; HLZ median > 0; bootstrap CI > 0)")
    vp = next(r for r in PS["survives"] if r["series"] == "v2_oos")["n_pass_of_6"]
    N.add("rig2.v2oos.pass", intc(vp), vp, s8 + "survives[v2_oos].n_pass_of_6")
    assert not hd["oos_series_passing_all_6"]
    # ---------------------------------------------------------------- CV teaser figure (verifier F's fixes)
    TN = J("results/cv_teaser/teaser_numbers.json")["numbers"]
    s9 = "results/cv_teaser/teaser_numbers.json::numbers."
    for k in ("a.shot_detected", "a.shot_frames", "b.lead_ms", "b.err_cm", "b.d_hat_m", "b.d_true_cm", "b.tau_cm", "b.game",
              "c.live_s", "c.late_vs_pre_ms", "c.early_vs_post_ms"):
        N.add("cvt." + k, TN[k]["text"], TN[k]["raw"], s9 + k + " <- " + str(TN[k]["source"])[:160])


# ================================================================================================ outputs
def write_numbers(N: Registry, extra: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "numbers.json").write_text(json.dumps({"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                                  "script": "scripts/build_paper.py", "label_cv": CV_LABEL,
                                                  "numbers": N.d}, indent=1, default=str, ensure_ascii=False))
    (OUT / "policy.json").write_text(json.dumps(extra["policy"], indent=1))
    (OUT / "variants.json").write_text(json.dumps(extra["variants"], indent=1))
    (OUT / "peeks.json").write_text(json.dumps(extra["peeks"], indent=1, ensure_ascii=False))
    lines = ["% generated by scripts/build_paper.py from results/paper/numbers.json; do not edit",
             "% CV readings: cv.pre.* = the pre-registered stamp-lag reading (listed first), cv.cal.* = the post hoc "
             "estimate; the CV trade set is selected on outcomes, not ex ante"]
    for k, v in N.d.items():
        lines.append(f"\\expandafter\\def\\csname cs@{k}\\endcsname{{{tex(v['value'])}}}")
    (PAPER / "numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_tex(N: Registry, extra: dict) -> Path:
    import jinja2
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(PAPER)), undefined=jinja2.StrictUndefined,
                             block_start_string="<%", block_end_string="%>", variable_start_string="<<",
                             variable_end_string=">>", comment_start_string="<#", comment_end_string="#>",
                             trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.globals.update(V=N, R=N.raw, T=tex, TB=tex_breakable, X=extra, CV_LABEL=CV_LABEL, sgn=sgn, num=num, ci=ci, usd=usd, intc=intc)
    out = env.get_template("note.tex.j2").render()
    p = PAPER / "note.tex"
    p.write_text(out, encoding="utf-8")
    return p


def prepare_logo() -> Path:
    """The event's own logo (docs/brand/gqh_wallie.png) cropped to the drawing for the page-1 title block: the source
    has wide empty borders and a stray light column on its right edge. Written to docs/paper/gqh_logo.png."""
    from PIL import Image
    src = ROOT / "docs/brand/gqh_wallie.png"
    im = Image.open(src).convert("RGBA")
    a = np.asarray(im).astype(int)
    ink = (a[..., 3] > 128) & (a[..., :3].min(axis=2) < 200)
    rows, cols = np.where(ink.sum(1) > 3)[0], np.where(ink.sum(0) > 3)[0]
    pad = 6
    box = (max(cols[0] - pad, 0), max(rows[0] - pad, 0), min(cols[-1] + pad + 1, im.width), min(rows[-1] + pad + 1, im.height))
    out = PAPER / "gqh_logo.png"
    im.crop(box).save(out, dpi=(300, 300))
    return out


def compile_tex(tex_path: Path) -> tuple[Path, str]:
    r = subprocess.run([TECTONIC, "--keep-intermediates", "--keep-logs", "--reruns", "4", tex_path.name], cwd=PAPER,
                       capture_output=True, text=True)
    log = r.stdout + r.stderr
    if r.returncode != 0:
        print(log[-6000:])
        raise SystemExit("tectonic failed")
    return tex_path.with_suffix(".pdf"), log


# ================================================================================================ checks
FORBIDDEN = ["our feed", "our licensed", "licensed feed we", "we licensed", "we purchased", "we bought",
             "received video", "match footage we", "our camera at", "courtside camera we", "live atp data",
             "live wta data"]


def checks(pdf: Path, tex_log: str) -> dict:
    import pymupdf
    res: dict = {"fail": []}
    aux = (PAPER / "note.aux").read_text()
    mm = re.search(r"\\newlabel\{lastmain\}\{\{[^}]*\}\{(\d+)\}", aux)
    last = int(mm.group(1)) if mm else 99
    res["main_pages"] = last
    if last > 5:
        res["fail"].append(f"main text ends on page {last} (> 5)")
    doc = pymupdf.open(pdf)
    res["total_pages"] = len(doc)
    W, H = doc[0].rect.width, doc[0].rect.height
    small, margin_viol, main_text = [], [], []
    min_size = 99.0
    float_pages = {}
    for pno in range(min(last, len(doc))):
        page = doc[pno]
        d = page.get_text("dict")
        for blk in d["blocks"]:
            for ln in blk.get("lines", []):
                for sp in ln["spans"]:
                    t = sp["text"].strip()
                    if not t:
                        continue
                    x0, y0, x1, y1 = sp["bbox"]
                    is_header = y1 < 72 and t == "COURTSIDE"
                    is_footer = y0 > H - 72 and re.fullmatch(r"\d+", t) is not None
                    # strict: every span on the main pages (body, tables, captions, math, figure text, header,
                    # footer) must be >= 11.0 pt in the PDF; only true superscripts (none at present) are exempt
                    sup = bool(sp["flags"] & 1)
                    if sp["size"] < 10.95 and not sup:
                        small.append({"page": pno + 1, "size": round(sp["size"], 2), "font": sp["font"], "text": t[:40]})
                    min_size = min(min_size, sp["size"])
                    if not (is_header or is_footer):
                        # tolerance 2.5 pt: microtype protrudes punctuation into the margin by design, and a
                        # heading's ascenders may sit just above the top of the text block
                        # bottom: the last baseline sits on the 1 in line, so descenders may reach 4.5 pt below it
                        if x0 < 72 - 2.5 or x1 > W - 72 + 2.5 or y0 < 72 - 2.5 or y1 > H - 72 + 4.5:
                            margin_viol.append({"page": pno + 1, "bbox": [round(v, 1) for v in sp["bbox"]], "text": t[:40]})
                    main_text.append(sp["text"])
        txt = page.get_text()
        for mm2 in re.finditer(r"(Figure|Table) (\d)\.", txt):
            float_pages.setdefault(f"{mm2.group(1)} {mm2.group(2)}", pno + 1)
    res["min_font_size_main"] = min((s["size"] for s in small), default=None)
    res["smallest_span_pt"] = round(min_size, 2)
    res["spans_below_11pt"] = small[:40]
    res["n_spans_below_11pt"] = len(small)
    if small:
        res["fail"].append(f"{len(small)} main-text spans below 11 pt")
    res["margin_violations"] = margin_viol[:40]
    if margin_viol:
        res["fail"].append(f"{len(margin_viol)} spans inside the 1 in margins")
    res["float_pages"] = float_pages
    # main text: the headline-metrics table and the latency-scenario table, and 3-4 figures (the rest is appendix)
    for f in ("Figure 1", "Figure 2", "Figure 3", "Table 1"):   # teaser, v2 edge, firm scenario; the metrics table
        if f not in float_pages:
            res["fail"].append(f"{f} not found on pages 1-{last}")
    n_tab = sum(1 for k in float_pages if k.startswith("Table"))
    n_fig = sum(1 for k in float_pages if k.startswith("Figure"))
    res["main_tables"], res["main_figures"] = n_tab, n_fig
    if n_tab > 2 or n_fig > 4:
        res["fail"].append(f"main text has {n_tab} tables and {n_fig} figures (max 2 and 4)")
    full_main = " ".join(main_text)
    flat = re.sub(r"\s+", " ", full_main).lower()
    hits = [f for f in FORBIDDEN if f in flat]
    res["honesty_hits"] = hits
    if hits:
        res["fail"].append(f"forbidden phrases: {hits}")
    all_text = re.sub(r"\s+", " ", " ".join(p.get_text() for p in doc)).lower()
    hits_all = [f for f in FORBIDDEN if f in all_text]
    if hits_all:
        res["fail"].append(f"forbidden phrases (whole PDF): {hits_all}")
    # INTEGRATION_TODO P-12 honesty guardrails: on pages 1-5, 'calibrated' never appears (the post hoc reading is
    # called 'post hoc'), 'not ex ante' appears, 'post hoc' at least three times; nowhere 'calibrated from the data' or
    # 'goes live'; '11 of 11' / '11/11' / '408 ms' only in a sentence that says 'offline'
    flat_nh = re.sub(r"(\w)[\u2010\u2011-] (\w)", r"\1\2", flat)
    if "calibrated" in flat_nh:
        res["fail"].append("'calibrated' on pages 1-5 (use 'post hoc')")
    if "not ex ante" not in flat_nh:
        res["fail"].append("'not ex ante' missing on pages 1-5")
    res["post_hoc_count_main"] = flat_nh.count("post hoc")
    if res["post_hoc_count_main"] < 3:
        res["fail"].append(f"'post hoc' appears {res['post_hoc_count_main']} times on pages 1-5 (< 3)")
    for bad in ("calibrated from the data", "goes live", "stricter readings"):
        if bad in all_text:
            res["fail"].append(f"forbidden phrase in the PDF: {bad!r}")
    off_bad = []
    for sent in re.split(r"(?<=[.;])\s+", all_text):
        if re.search(r"\b11 of 11\b|\b11/11\b|\b408\s?ms", sent) and "offline" not in sent:
            off_bad.append(sent[:120])
    res["offline_label_misses"] = off_bad
    if off_bad:
        res["fail"].append(f"'11 of 11' / '408 ms' without 'offline' in the same sentence: {off_bad[:3]}")
    n_label = flat.replace("-\n", "").count("assumed feed latency")
    res["cv_label_count_main"] = n_label
    if n_label < 3:
        res["fail"].append(f"CV label appears {n_label} times on pages 1-5 (< 3)")
    lg = (PAPER / "note.log").read_text(errors="replace") if (PAPER / "note.log").exists() else tex_log
    over = [float(x) for x in re.findall(r"Overfull \\hbox \(([0-9.]+)pt too wide\)", lg)]
    res["overfull_hbox_pt"] = over
    if any(o > 1.0 for o in over):
        res["fail"].append(f"overfull hbox > 1 pt: {[o for o in over if o > 1.0]}")
    undef = re.findall(r"(?:Reference|Citation) `([^']+)' .*undefined", lg)
    res["undefined_refs"] = sorted(set(undef))
    if undef:
        res["fail"].append(f"undefined refs/cites: {sorted(set(undef))}")
    if "COURTSIDE: missing number" in lg:
        res["fail"].append("missing number macro in the log")
    fonts = set()
    for p in doc:
        for f in p.get_fonts(full=True):
            fonts.add((f[3], f[1]))
    ours = ("SourceSans3", "Oswald", "FiraMath")
    bad = sorted({n for n, ext in fonts if not any(o in n for o in ours)})
    unembedded = sorted({n for n, ext in fonts if ext in ("n/a", "")})
    res["fonts"] = sorted({n for n, _ in fonts})
    if bad:
        res["fail"].append(f"fonts not from docs/paper/fonts: {bad}")
    if unembedded:
        res["fail"].append(f"fonts not embedded: {unembedded}")
    # page renders
    pdir = OUT / "pages"
    pdir.mkdir(parents=True, exist_ok=True)
    for old in pdir.glob("p*.png"):
        old.unlink()
    for i, p in enumerate(doc, 1):
        p.get_pixmap(dpi=110).save(str(pdir / f"p{i}.png"))
    res["ok"] = not res["fail"]
    return res


# ================================================================================================ companion
def write_companion(N: Registry, extra: dict | None = None) -> None:
    v = N.text
    authors = (extra or {}).get("authors", "[Author names: team to fill]")

    def row3(rk):  # latency-scenario rows of one reading
        out = []
        for vk, lab in (("v05", "0.5 s, best case"), ("v1", "1 s, base case"), ("v3", "3 s, requirement")):
            out.append(f"| {lab} | {v(f'sc.{rk}.is.{vk}.usd')} | {v(f'sc.{rk}.is.{vk}.sr')} | {v(f'sc.{rk}.is.{vk}.c')} "
                       f"{v(f'sc.{rk}.is.{vk}.cci')} | {v(f'sc.{rk}.oos.{vk}.usd')} | {v(f'sc.{rk}.oos.{vk}.sr')} | "
                       f"{v(f'sc.{rk}.oos.{vk}.c')} {v(f'sc.{rk}.oos.{vk}.cci')} |")
        return "\n".join(out)
    extra_fwd = (extra or {}).get("fwd_text", v("fwd.cell"))
    md = f"""# COURTSIDE: Calling the Point Before It Lands
## Predictive Ball Tracking and the Value of Speed in In-Play Tennis Markets

{authors} · University of Florida · Gator Quant Hacks 2026 · Systematic Trading Track · October 4, 2026

**The paper is [`docs/NOTE.pdf`](NOTE.pdf).** This page is a short companion built from the same numbers
(`results/paper/numbers.json`, which names the source file of every value). If the two ever differ, the PDF wins.

**How to read the labels.** The computer-vision (CV) results are simulated: {CV_LABEL}. Their trades are past points
where the price later moved at least 4¢, so they are selected on outcomes, not ex ante. We show the pre-registered
stamp-lag reading first and the post hoc estimate ({v('cv.cal.lag')} s, 95% CI {v('cv.cal.lag_ci')} s) second. v2 is our
copy of the fast tier's trades at their own prices: it measures what their speed is worth, not what we could earn.
"OOS" for v2 and the CV simulation is a burned hold-out (we had looked at it), not a blind one. No real money was used
and no order was ever sent.

## Abstract

We built a predictive ball-tracking engine that calls a point (ball out, or into the net) before the ball lands. On
held-out real table-tennis video our live causal engine made its calls a median {v('cv.eng.lead')} ms before the ball
reached the table end, none wrong but few ({v('cv.eng.tp')} of {v('cv.eng.nmiss')} misses), in real time at
{v('cv.eng.fps')} fps; a frame becomes a ready order in {v('e2e.ours')} ms. On real broadcast tennis (one TV camera,
held-out games) its out calls were right {v('bt.call.0')} at the bounce and {v('bt.call.33')} when 33 ms ahead. Speed is
worth money because, in real Polymarket data on {v('univ.matches')} ATP and WTA matches ({v('cov.gs.all')} at Grand
Slams), whoever learns the point first sets the price: wallets trading within 3 s of a point earn after fees in all
{v('ft.months.cal')} months, and each second of feed delay costs a simulated computer-vision (CV) trader
{v('cv.pre.persec.range')} a day. Copying those wallets at their own fills has a Sharpe ratio of {v('v2.is.sr')} in sample
and {v('v2.oos.sr')} out of sample, which doubled fees erase. At an assumed 1 s feed our CV trader makes
{v('sc.pre.oos.v1.usd')} a day out of sample pre-registered and {v('sc.cal.oos.v1.usd')} (Sharpe {v('sc.cal.oos.v1.sr')})
post hoc. Every blind test of a book we could trade failed.

## The real data behind every result

Simulated: only when our CV would see each point (an assumed feed latency) and the spin-aware Hawk-Eye-class model.

| Source | What is real | Matches | Period | Used for |
|---|---|---|---|---|
| Polymarket books and trades | prices, fills, fees, taker delays | {v('univ.matches')} ({v('cov.pm.atp')} ATP, {v('cov.pm.wta')} WTA); {v('cov.gs.all')} at Grand Slams (Australian Open {v('cov.gs.ao')}, Roland Garros {v('cov.gs.rg')}, US Open {v('cov.gs.uso')}) | Oct 2025 – Oct 2026 | fast tier; v2 (traded in {v('cov.v2.is')} IS, {v('cov.v2.oos')} OOS); CV trader ({v('cov.pool.n')} matches at a 1 s hold, about {v('cov.t0.is')} IS and {v('cov.t0.oos')} OOS traded per seed) |
| Polymarket, held back | same | {v('u2.markets')} ({v('u2.itf')} ITF) | same | blind test |
| Match Charting Project (Sackmann) | {v('cov.mcp.points')} charted points | {v('cov.mcp.n')} ({v('cov.mcp.men')} men, {v('cov.mcp.women')} women) | {v('cov.mcp.years')} | how points end (out {v('pm.out')}, net {v('pm.net')}, winner {v('pm.win')}) |
| TrackNet broadcast set (Huang et al. 2019) | {v('cov.tn.frames')} labelled frames | {v('cov.tn.matches')} ({v('cov.tn.clips')} clips) | | court, landing and out-call models (tuned on games 1–7, tested once on 8–10) |
| OpenTTGames; Pexels rally | 120 fps match video; phone video | {v('cv.eng.nmiss')} held-out misses; one rally | | early-call engine; tracker end to end |

Wimbledon is listed under a separate Polymarket series and is outside our universe.

## v2, our copy of the fast tier's trades (Table 1 of the PDF, top rows)

Sharpe uses daily P&L on every calendar day × √365; 95% CIs from a stationary block bootstrap; the deflated Sharpe
corrects for {v('rig.N3386')} trials.

| | IS | OOS (burned) |
|---|---|---|
| Net ¢ a share [95% CI] | {v('v2.is.c')} {v('v2.is.ci')} | {v('v2.oos.c')} {v('v2.oos.ci')} |
| Sharpe [95% CI] | {v('v2.is.sr')} {v('v2.is.sr_ci')} | {v('v2.oos.sr')} {v('v2.oos.sr_ci')} |
| Deflated Sharpe | {v('v2.is.dsr')} | {v('v2.oos.dsr')} |
| Annual return / volatility | {v('v2.is.ret')} / {v('v2.is.vol')} | {v('v2.oos.ret')} / {v('v2.oos.vol')} |
| Max drawdown / worst month | {v('v2.is.dd')} / {v('v2.is.worstmonth')} | {v('v2.oos.dd')} / {v('v2.oos.worstmonth')} |
| Turnover (× a year) / skew | {v('v2.is.turnover')} / {v('v2.is.skew')} | {v('v2.oos.turnover')} / {v('v2.oos.skew')} |
| Fees paid, bps of notional | {v('v2.is.fee_bps')} | {v('v2.oos.fee_bps')} |
| PSR / MinTRL / haircut tests passed (of 6) | 6 | {v('rig2.v2oos.pass')} |
| Net ¢, fees ×2 / all costs ×2 | {v('v2.is.fx2.c')} / {v('v2.is.cx2.c')} | {v('v2.oos.fx2.c')} / {v('v2.oos.cx2.c')} |

## The CV strategy at three assumed feed delays (Table 1 of the PDF, lower rows)

Simulated ({CV_LABEL}; {v('cv.seeds')} seeds a cell). Pre-registered stamp lag {v('cv.pre.lag')} s (break-even feed
delay {v('cv.pre.be.is')} s IS, {v('cv.pre.be.oos')} s OOS):

| Feed delay V | IS $/day | IS Sharpe | IS ¢/share [95% CI] | OOS $/day | OOS Sharpe | OOS ¢/share [95% CI] |
|---|---|---|---|---|---|---|
{row3('pre')}

Post hoc estimate {v('cv.cal.lag')} s (assumes humans at the court; break-even {v('cv.cal.be.is')} s IS,
{v('cv.cal.be.oos')} s OOS):

| Feed delay V | IS $/day | IS Sharpe | IS ¢/share [95% CI] | OOS $/day | OOS Sharpe | OOS ¢/share [95% CI] |
|---|---|---|---|---|---|---|
{row3('cal')}

Return, volatility, max drawdown, turnover and the fees-doubled result of every cell are in Table 1 of the PDF
(`results/tier0/cost_turnover.json`); fees run {v('cv.fee_bps.range')} bps of notional, and with fees doubled every
out-of-sample cell loses (best {v('cv.fx2.oos.best')} a day). Read per point, the post hoc inference loses
({v('pp.cal.oos.usd')} a day at 1 s). A replay of {v('rp.matches')}
matches recorded live against their real order books calls every point ex ante and loses in {v('rp.cells_neg')} of
{v('rp.cells')} settings ({v('rp.v1l2.c')}¢ a share at 1 s).

## If we were a quant firm with a licensed 0.5 s feed (counterfactual)

Real Polymarket prices, fills, fees and the venue's 1 s hold; simulated camera calls at an assumed feed delay; no feed
bought, no order placed. At 0.5 s the trader makes {v('sc.pre.is.v05.usd')} / {v('sc.cal.is.v05.usd')} a day in sample
and {v('sc.pre.oos.v05.usd')} / {v('sc.cal.oos.v05.usd')} on the burned OOS (pre-registered / post hoc). A fresh holdout,
pre-registered at `{v('fresh.prereg.commit')}` before its data were fetched ({v('fresh.covered')} newer matches,
{v('fresh.days')} UTC days), returned {v('fresh.s2.pre.v05.usd')} / {v('fresh.s2.cal.v05.usd')} a day (CIs
{v('fresh.s2.pre.v05.ci')}, {v('fresh.s2.cal.v05.ci')}): anecdotal, evidence neither for nor against an edge. The most a
firm could pay a month for the feed is {v('fresh.lic.oos.pre')} / {v('fresh.lic.oos.cal')} on the burned OOS, against
quotes of {v('fin.feed.low')}–{v('fin.feed.high')}. Fig. 3 of the PDF; `results/fresh_holdout/`, `results/scenario/`.

## Speed, capacity and what failed

- **Pipeline (paper; order built, not sent).** On our own footage a video frame becomes a built order in
  {v('e2e.ours')} ms. With a simulated 1 s feed, {v('e2e.net')} ms of network and the 1 s venue hold, the order can
  execute {v('e2e.total')} ms after the point ends, inside the organizers' 3,000 ms bar.
- **Vision on real video.** On the TrackNet broadcast set (tuned on games 1–7, tested once on games 8–10,
  {v('bt.bounces.test')} bounces), one TV camera and the pretrained detector's own track put the landing point
  {v('bt.err0')} cm off at the bounce and {v('bt.err.lead')} m off 33–300 ms ahead (median); out calls were right
  {v('bt.call.0')} at the bounce, {v('bt.call.33')} at 33 ms and {v('bt.call.67')} at 67 ms ahead, and fail from 100 ms
  ({v('bt.call.100')}). Only the bounce-time call met our 95% precision rule on the training games, and the detector
  weights (not ours) saw frames of all ten games, so these are in-distribution numbers. On held-out table tennis the
  live causal engine called {v('cv.eng.tp')} of {v('cv.eng.nmiss')} misses early (median lead {v('cv.eng.lead')} ms), none
  wrongly, at {v('cv.eng.fps')} fps on one L4 GPU. On a Pexels rally our tennis tracker found the ball in
  {v('tn.real.ball')} of {v('tn.real.frames')} frames. Tennis trading is simulated.
- **Nearby settings also work.** All {v('plat.sizing.pos')} sizing rules have a per-share 95% CI above zero in sample
  (Sharpe {v('plat.sizing.sr')}); the v2-safe grid's probability of backtest overfitting is {v('plat.pbo')} across
  block choices; the CV profit falls across all {v('plat.lat.n')} feed delays from {v('plat.lat.lo')} to
  {v('plat.lat.hi')} s, never rising by more than {v('plat.lat.rise')} a day.
- **Per-match loss and a per-wallet cap (risk).** The 100-share net cap limits the open position, not the loss:
  the worst match lost {v('risk.pm.worst.is')} in sample and {v('risk.pm.worst.oos')} out of sample. A per-wallet cap
  ({v('wcap.W')} a day plus retirement), chosen in sample and pre-registered, ran once on the burned OOS (non-blind):
  {v('wcap.oos.c')}¢ {v('wcap.oos.ci')}, Sharpe {v('wcap.oos.sr')}; the top five wallets still carry {v('wcap.oos.top5')}.
- **Rally gate (risk).** Replayed on the engine's held-out call log (`scripts/rally_gate_eval.py`), the gate in our
  strategy code (a miss call trades only within {v('gate.s')} s of a bounce call, set before the test) removes
  {v('gate.out.removed')} of the {v('gate.out.total')} calls on balls outside labelled flights
  ({v('gate.between.removed')} of {v('gate.between.total')} between rallies) but keeps only {v('gate.correct.kept')} of
  {v('gate.correct.total')} correct calls ({v('gate.correct.kept_lo')} at {v('gate.lo_range')} s); about
  {v('gate.hr')} phantom calls an hour remain, so it is not yet safe to trade.
- **Capacity.** v2's OOS edge holds up to 1× size ({v('cap.1x.oos.capital')} of capital); 5× loses. The CV book has no
  capacity at the pre-registered lag; post hoc its Sharpe halves at {v('capcv.half.oos')} (OOS) to {v('capcv.half.is')}
  (IS) of capital. At 1 s it could pay at most {v('cv.cal.oos.maxlic')} a month for data post hoc and
  {v('cv.pre.oos.maxlic')} pre-registered, against reported feed prices of {v('fin.feed.low')}–{v('fin.feed.high')}.
  COURTSIDE prices speed; it is not yet a business.
- **What failed.** Doubled fees out of sample ({v('v2.oos.fx2.c')}¢); v2 on {v('u2.markets')} never-examined markets
  (blind); v2-safe's blind test; the CV rule v3 (blind); the maker book (blind); table-tennis markets (untestable); v2
  after a central data licence ({v('fin.v2.oos.net_central')} a day); the live-book replay. Blind forward test:
  {extra_fwd}. We tried {v('var.total')} variants and logged {v('peeks.n')} reads of held-out data (Appendix D of the
  PDF). Every test is in Appendix B; every formula with a worked example is in Appendix A.

Reproduce: `bash reproduce.sh` (rebuilds the result files, every figure and this paper).
"""
    (ROOT / "docs/NOTE.md").write_text(md, encoding="utf-8")
    try:
        import make_pdf  # same directory; renders the companion as print-styled HTML (fallback page)
        make_pdf.write_html()
    except ImportError:
        pass


# ================================================================================================ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-figures", action="store_true")
    ap.add_argument("--no-checks-fail", action="store_true", help="report failed checks but exit 0")
    a = ap.parse_args()
    if a.no_checks_fail:
        print("build_paper: --no-checks-fail cannot publish a verified paper; remove this option", file=sys.stderr)
        return 2
    if not Path(TECTONIC).is_file() or not os.access(TECTONIC, os.X_OK):
        print("build_paper: an executable tectonic compiler is required to rebuild docs/NOTE.pdf", file=sys.stderr)
        return 2
    N, extra = collect()
    write_numbers(N, extra)
    print(f"numbers: {len(N.d)} keys -> results/paper/numbers.json")
    if not a.no_figures:
        import paper_figures_v2  # the house-style figures (results/paper/v2); paper_figures.py keeps the loaders
        paper_figures_v2.main()
    prepare_logo()
    texp = render_tex(N, extra)
    pdf, log = compile_tex(texp)
    res = checks(pdf, log)
    res["build"] = {"numbers_sha256": sha256_file(OUT / "numbers.json"),
                    "pdf_sha256": sha256_file(pdf)}
    (OUT / "checks.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"pages: main {res['main_pages']}, total {res['total_pages']}; smallest main-text span "
          f"{res['smallest_span_pt']} pt; CV label x{res['cv_label_count_main']}; overfull {res['overfull_hbox_pt']}")
    for f in res["fail"]:
        print("CHECK FAILED:", f)
    if not res["ok"]:
        print("build_paper: failed checks; the submitted docs/NOTE.pdf was not replaced", file=sys.stderr)
        return 1
    atomic_copy(pdf, ROOT / "docs/NOTE.pdf")
    write_companion(N, extra)
    print("wrote docs/NOTE.pdf, docs/NOTE.md, docs/NOTE.html, results/paper/{numbers,policy,variants,peeks,checks}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
