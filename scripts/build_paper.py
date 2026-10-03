"""Build the COURTSIDE paper: docs/NOTE.pdf (LaTeX via tectonic) and its readable companion docs/NOTE.md.

Pipeline (docs/paper/PLAN.md section 1):
  1. read every number from committed result files into one registry -> results/paper/numbers.json
     (each entry: value as printed, raw value, source file::key). A missing key stops the build.
  2. write results/paper/{policy,variants,peeks}.json and docs/paper/numbers.tex (one macro per key)
  3. draw every figure (scripts/paper_figures.py) into results/paper/
  4. render docs/paper/note.tex.j2 -> docs/paper/note.tex and compile with tectonic
  5. acceptance checks (PLAN section 15): main text <= 5 pages, every main-text span >= 11 pt (figure text
     included), 1 in margins, honesty grep, LaTeX log clean, fonts embedded and ours -> results/paper/checks.json
  6. page renders at 110 dpi -> results/paper/pages/, copy to docs/NOTE.pdf, write docs/NOTE.md and docs/NOTE.html

Pending slots: the forward test (results/v2/forward.json) and the live paper session (results/live/FINAL +
summary.json) are filled only from files that already exist; otherwise the paper prints "pending".
scripts/forward_test.py is never imported or run here. Nothing here runs a new evaluation: it reads committed
result files, and Fig. 2(b) re-draws the committed v2 trade file (IS and burned OOS) with the cost-stress lambdas,
asserting the committed totals to the cent.

Usage: .venv/bin/python scripts/build_paper.py [--no-figures] [--no-checks-fail]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
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
    mcal = re.search(r"([0-9.]+) s", SW["grids"]["video_stamp_lag_sensitivity"]["tournament_lagcal"])
    N.add("cv.cal.lag", mcal.group(1), float(mcal.group(1)),
          "results/tier0/latency_sweep.json::grids.video_stamp_lag_sensitivity.tournament_lagcal (regex)")
    N.add("cv.pre.lag", num(SW["model"]["revised_primary"]["stamp_lag"], 1), SW["model"]["revised_primary"]["stamp_lag"],
          "results/tier0/latency_sweep.json::model.revised_primary.stamp_lag")
    for rk, reading in (("cal", "tournament_lagcal"), ("pre", "tournament")):
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
    for rk in ("cal", "pre"):
        v = N.raw(f"cv.{rk}.oos.usd") - fixed["central"]
        N.add(f"cv.{rk}.oos.net_central", usd(v, signed=True), v,
              "D: cv.<r>.oos.usd - results/financials/financials.json::strategies.v2.cost.daily.central")
    chk = SW["check_V0_equals_published_headline"]
    assert chk["IS"]["identical"] and chk["burned_OOS"]["identical"], "V = 0 check failed"
    N.add("cv.v0.check", "identical", True, "results/tier0/latency_sweep.json::check_V0_equals_published_headline")
    N.add("cv.seeds", intc(SW["grids"]["seeds"]), SW["grids"]["seeds"], "results/tier0/latency_sweep.json::grids.seeds")
    N.add("cv.runs", intc(SW["run"]["n_runs"]), SW["run"]["n_runs"], "results/tier0/latency_sweep.json::run.n_runs")
    extra["sweep"] = SW

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
    if fwd_p.exists():
        F = json.loads(fwd_p.read_text())

        def tri(v):
            return f"{sgn(v[0])} {ci(v[1:3])}" if isinstance(v, list) and len(v) >= 3 else str(v)
        parts = []
        if "primary_A_fast_minus_others_c" in F:
            parts.append(f"A {tri(F['primary_A_fast_minus_others_c'])} {F.get('verdict_A_fast_tier', '')}".strip())
        if "primary_m30_per_share_c" in F:
            parts.append(f"B {tri(F['primary_m30_per_share_c'])} {F.get('verdict_B_v2_book', '')}".strip())
        if "v2_trades" in F:
            parts.append(f"n = {intc(F['v2_trades'])}")
        cell = " \u00b7 ".join(parts) if parts else "see results/v2/forward.json"
        status = " / ".join(str(F.get(k)) for k in ("verdict_A_fast_tier", "verdict_B_v2_book") if F.get(k)) or "reported"
        N.add("fwd.cell", cell, F, "results/v2/forward.json")
        N.add("fwd.status", status, status, "results/v2/forward.json::verdict_*")
    else:
        N.add("fwd.cell", "pending (runs once, Oct 4)", None, "results/v2/forward.json (absent at build time)")
        N.add("fwd.status", "pending", None, "results/v2/forward.json (absent at build time)")
    live_p = ROOT / "results/live/summary.json"
    if (ROOT / "results/live/FINAL").exists() and live_p.exists():
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
    return N, extra


# ================================================================================================ outputs
def write_numbers(N: Registry, extra: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "numbers.json").write_text(json.dumps({"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                                  "script": "scripts/build_paper.py", "label_cv": CV_LABEL,
                                                  "numbers": N.d}, indent=1, default=str, ensure_ascii=False))
    (OUT / "policy.json").write_text(json.dumps(extra["policy"], indent=1))
    (OUT / "variants.json").write_text(json.dumps(extra["variants"], indent=1))
    (OUT / "peeks.json").write_text(json.dumps(extra["peeks"], indent=1, ensure_ascii=False))
    lines = ["% generated by scripts/build_paper.py from results/paper/numbers.json; do not edit"]
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
    for f in ("Figure 1", "Figure 2", "Figure 3", "Table 1", "Table 2", "Table 3"):
        if f not in float_pages:
            res["fail"].append(f"{f} not found on pages 1-{last}")
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
def write_companion(N: Registry) -> None:
    v = N.text
    md = f"""# COURTSIDE: Pricing the Value of Speed in In-Play Tennis Prediction Markets

[Author names: team to fill] · University of Florida · Gator Quant Hacks 2026 · Systematic Trading Track · October 4, 2026

**The paper is [`docs/NOTE.pdf`](NOTE.pdf)** (LaTeX, built by `python scripts/build_paper.py`; every number below and in the
PDF is read from `results/paper/numbers.json`, which records the source file and key of each). This file is a short
readable companion; where the two differ, the PDF wins.

**Labels.** CV-strategy results: {CV_LABEL}; simulated at a 1 s licensed-feed baseline. v2 results are measured at
the fast tier's own fills: the opportunity at their speed, not our execution. Real money: none.

## Abstract

We study who profits from speed in Polymarket's in-play tennis moneylines, using public trade tapes for
{v('univ.matches')} matches ({v('univ.volume')} traded). A walk-forward fast tier of wallets trading within 3 s of a
score move earns {v('ft.c.is')}¢ per share after fees in sample and {v('ft.c.oos')}¢ out of sample (positive in
{v('ft.months.is')} and {v('ft.months.oos')} months); every other taker loses, and copying the same trades 3 s later
loses. At the fast tier's own fills a frozen book (v2) earns {v('v2.oos.c')}¢ per share out of sample (Sharpe
{v('v2.oos.sr')}) but turns negative when fees double ({v('v2.oos.fx2.c')}¢). Simulated at a 1 s licensed-feed
baseline ({CV_LABEL}), the computer-vision trader earns {v('cv.cal.oos.usd')}/day out of sample under a calibrated,
post hoc stamp lag and {v('cv.pre.oos.usd')}/day under the pre-registered one, which breaks even at
{v('cv.pre.be.range')} s of feed delay.

## Main result: the CV strategy at the 1 s baseline (Table 2 of the PDF)

| Reading at V = 1 s | IS $/day [seed CI] | IS Sharpe | OOS $/day [seed CI] | OOS Sharpe | OOS ¢/share [CI] | Break-even V (IS / OOS) |
|---|---|---|---|---|---|---|
| Calibrated stamp lag {v('cv.cal.lag')} s (calibrated, post hoc) | {v('cv.cal.is.usd')} {v('cv.cal.is.usd_ci')} | {v('cv.cal.is.sr')} | {v('cv.cal.oos.usd')} {v('cv.cal.oos.usd_ci')} | {v('cv.cal.oos.sr')} | {v('cv.cal.oos.c')} {v('cv.cal.oos.c_ci')} | {v('cv.cal.be.is')} / {v('cv.cal.be.oos')} s |
| Pre-registered stamp lag {v('cv.pre.lag')} s | {v('cv.pre.is.usd')} {v('cv.pre.is.usd_ci')} | {v('cv.pre.is.sr')} | {v('cv.pre.oos.usd')} {v('cv.pre.oos.usd_ci')} | {v('cv.pre.oos.sr')} | {v('cv.pre.oos.c')} {v('cv.pre.oos.c_ci')} | {v('cv.pre.be.is')} / {v('cv.pre.be.oos')} s |

At stamp lag 1.0 s the same trader loses ({v('cv.lag1.is.usd')} IS, {v('cv.lag1.oos.usd')} OOS per day). A replay of
{v('rp.matches')} matches recorded live on 2026-10-03 against their real books loses in {v('rp.cells_neg')} of
{v('rp.cells')} settings ({v('rp.v1l2.c')}¢ per share at V = 1 s, stamp lag 2 s).

## v2 at the fast tier's own fills (Table 1 of the PDF)

| | In sample | Burned OOS (non-blind for v2) |
|---|---|---|
| Net ¢/share [95% CI] | {v('v2.is.c')} {v('v2.is.ci')} | {v('v2.oos.c')} {v('v2.oos.ci')} |
| Annualised return / volatility | {v('v2.is.ret')} / {v('v2.is.vol')} | {v('v2.oos.ret')} / {v('v2.oos.vol')} |
| Sharpe [bootstrap CI] | {v('v2.is.sr')} {v('v2.is.sr_ci')} | {v('v2.oos.sr')} {v('v2.oos.sr_ci')} |
| Max drawdown | {v('v2.is.dd')} | {v('v2.oos.dd')} |
| Skew / worst month | {v('v2.is.skew')} / {v('v2.is.worstmonth')} | {v('v2.oos.skew')} / {v('v2.oos.worstmonth')} |
| Turnover (× capital per year) | {v('v2.is.turnover')} | {v('v2.oos.turnover')} |
| Fees ×2, ¢/share [CI] | {v('v2.is.fx2.c')} {v('v2.is.fx2.ci')} | {v('v2.oos.fx2.c')} {v('v2.oos.fx2.ci')} |
| All costs ×2, ¢/share [CI] | {v('v2.is.cx2.c')} {v('v2.is.cx2.ci')} | {v('v2.oos.cx2.c')} {v('v2.oos.cx2.ci')} |

## What failed or is pending

Fees ×2 out of sample ({v('v2.oos.fx2.c')}¢); v2 on {v('u2.markets')} never-examined markets (blind, {v('u2.verdict')});
tier-0 v3 frozen rule (blind, {v('t3.verdict')}); maker v1 (blind, {v('mk.verdict')}, {v('mk.oos.usd')}); table tennis
(untestable, median spread {v('tt.spread')}¢); v2 out of sample after a central feed licence
({v('fin.v2.oos.net_central')}/day); the live-book replay ({v('rp.v1l2.c')}¢ at 1 s). Forward test: {v('fwd.cell')}.
Live paper session: {v('live.cell')}. Variants tried: {v('var.total')}. Logged reads of held-out data:
{v('peeks.n')} (full list in Table A6 of the PDF).

Reproduce: `bash reproduce.sh` (regenerates the result files, every figure and this paper).
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
    N, extra = collect()
    write_numbers(N, extra)
    print(f"numbers: {len(N.d)} keys -> results/paper/numbers.json")
    if not a.no_figures:
        import paper_figures
        paper_figures.main()
    texp = render_tex(N, extra)
    if not Path(TECTONIC).exists():
        # judges without tectonic: numbers, figures and note.tex are regenerated; the committed PDF stands
        print(f"build_paper: tectonic not found; wrote {texp.relative_to(ROOT)} and results/paper/, kept the "
              "committed docs/NOTE.pdf (install tectonic to rebuild it)")
        write_companion(N)
        return 0
    pdf, log = compile_tex(texp)
    res = checks(pdf, log)
    (OUT / "checks.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    shutil.copyfile(pdf, ROOT / "docs/NOTE.pdf")
    write_companion(N)
    print(f"pages: main {res['main_pages']}, total {res['total_pages']}; smallest main-text span "
          f"{res['smallest_span_pt']} pt; CV label x{res['cv_label_count_main']}; overfull {res['overfull_hbox_pt']}")
    for f in res["fail"]:
        print("CHECK FAILED:", f)
    print("wrote docs/NOTE.pdf, docs/NOTE.md, docs/NOTE.html, results/paper/{numbers,policy,variants,peeks,checks}.json")
    return 0 if (res["ok"] or a.no_checks_fail) else 1


if __name__ == "__main__":
    raise SystemExit(main())
