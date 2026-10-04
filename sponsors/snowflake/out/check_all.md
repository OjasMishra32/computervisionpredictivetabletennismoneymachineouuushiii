# Every number in the paper, checked

Run 2026-10-04 03:39 local · numbers file `results/paper/numbers.json` (generated 2026-10-04T07:18:57+00:00) · PDF `NOTE.pdf` · script `sponsors/snowflake/check_all.py`

**1040 checked: 46 match (recomputed), 906 lookup-only, 0 mismatched, 88 unresolvable**

*recomputed* = derived here from rows or a formula (DuckDB for CSV sources) and agrees with the print; *lookup-only* = the stored value agrees with the print; a unit scale (x100 for percent, x1000 for s -> ms) and a dropped minus sign are accepted and shown in the `how` column.

## Mismatches (0)

## Unresolvable sources (88)

| key | printed | why | source |
|---|---|---|---|
| `v2.trades_per_day` | 270 | free-text formula | `D: causal.json is_eval n_trades / days` |
| `cv.tt.called50` | 11 | free-text formula | `D: tp + fp at 50 ms (snapshot rule)` |
| `venue.delay` | 1 | regex 'order delay (x s)' found nothing | `results/tier0/latency_sweep.json::model.video (regex 'order delay (x s)')` |
| `cv.pre.be.range` | 1.0–1.1 | free-text formula | `D: min/max of the IS and OOS break-evens` |
| `cv.cal.be.range` | 2.1–2.2 | free-text formula | `D: min/max of the IS and OOS break-evens` |
| `cv.pre.oos.net_central` | −$163 | derived formula over a JSON file (free text) | `D: cv.<r>.oos.usd - results/financials/financials.json::strategies.v2.cost.daily.central` |
| `cv.cal.oos.net_central` | −$110 | derived formula over a JSON file (free text) | `D: cv.<r>.oos.usd - results/financials/financials.json::strategies.v2.cost.daily.central` |
| `cv.cal.react` | 0.25 | selector [stamp_lag_median_s == base.stamp_lag_median_s] not found in results/redteam/stam | `results/redteam/stamp_lag.json::reaction_time[stamp_lag_median_s == base.stamp_lag_median_s].react_s` |
| `cv.pre.persec.range` | $42–74 | free-text formula | `D: min/max of cv.pre.{is,oos}.persec` |
| `t0.dev.n` | 13 | free-text formula | `D: count of '### T<n>.' and '### V<n>.' headings in research/v2/tier0/DEVIATIONS.md` |
| `t0.dev.span` | T1–T3, V1–V10 | source form not recognised | `research/v2/tier0/DEVIATIONS.md headings` |
| `rp.cells_neg` | 36 | derived formula over a JSON file (free text) | `D: count of replay.json::cells[*].all.per_share_mark_c < 0` |
| `rp.cells` | 36 | derived formula over a JSON file (free text) | `D: len(replay.json::cells)` |
| `rp.best` | −0.05 [−0.37, 0.27] | free-text formula | `D: argmax over replay cells` |
| `rp.best.cell` | lag 3 s, V = 0 s | free-text formula | `D: argmax over replay cells` |
| `rp.sel.neg2` | 9 of 9 | free-text formula | `D: selective.json cells with T set and lag 2.0 whose all.per_share_mark_c < 0` |
| `h1.neg` | 20 of 20 | derived formula over a JSON file (free text) | `D: count of summary.json::is.h1.*.mean_pnl_per_share_c < 0` |
| `risk.daily_stop_sigma` | 3.86 | derived formula over a JSON file (free text) | `D: daily_stop_usd / results/rigor/rigor.json::sharpe_moments.v2_is.sd_daily_usd` |
| `risk.months_half` | 1.5 | formula has words left after substituting keys | `D: (v2.oos.c - 0.3) / |ft.slope| (extrapolation)` |
| `risk.months_zero` | 3.0 | formula has words left after substituting keys | `D: v2.oos.c / |ft.slope| (extrapolation)` |
| `peeks.blind` | 7 | free-text formula | `D: keyword class 'blind first run' over results/oos_peeks.log` |
| `peeks.nonblind` | 22 | free-text formula | `D: keyword class 'non-blind' over results/oos_peeks.log` |
| `peeks.desc` | 6 | free-text formula | `D: keyword class 'descriptive' over results/oos_peeks.log` |
| `peeks.audit` | 48 | free-text formula | `D: keyword class 'audit' over results/oos_peeks.log` |
| `peeks.live` | 22 | free-text formula | `D: keyword class 'live' over results/oos_peeks.log` |
| `peeks.other` | 6 | free-text formula | `D: keyword class 'other' over results/oos_peeks.log` |
| `fwd.cell` | pre-registered but not run within the hackathon window (HYPOTHESIS_V2.md A5) | source form not recognised | `HYPOTHESIS_V2.md::Amendment A5 (results/v2/forward.json absent at build time)` |
| `fwd.status` | not run | source form not recognised | `HYPOTHESIS_V2.md::Amendment A5` |
| `live.cell` | stopped by a team decision after 0 fills; not used | source form not recognised | `results/live/STOPPED_TEAM_DECISION; results/live/summary.json::books.B1.fills` |
| `live.status` | stopped | source form not recognised | `results/live/STOPPED_TEAM_DECISION` |
| `spin.ratio200` | 10 | free-text formula | `D: key_numbers.json baseline.sd_cm.200 / bls.sd_cm.200` |
| `calc.sqrt365` | 19.105 | free-text formula | `D: sqrt(365)` |
| `calc.so.dd` | $125.64 | expression not arithmetic: sqrt(mean(min(d,0)^2)), zero-filled calendar days | `D: results/lowloss/daily.csv[a,u1_oos,v2] sqrt(mean(min(d,0)^2)), zero-filled calendar days` |
| `calc.mdd.pct` | −2.06% | formula has words left after substituting keys | `D: calc.mdd / capital` |
| `calc.z1` | 3.436 | formula has words left after substituting keys | `D: Phi^-1(1 - 1/N), N = rig.N3386` |
| `calc.z2` | 3.698 | free-text formula | `D: Phi^-1(1 - 1/(N e))` |
| `calc.sr0d` | 0.574 | free-text formula | `D: sqrt(1/(T-1)) ((1-gamma) z1 + gamma z2)` |
| `calc.fee.q50.c` | 1.25 | formula has words left after substituting keys | `D: r q (1-q) x 100 cents, r = fee.rate` |
| `calc.fee.q50.bps` | 250 | free-text formula | `D: 10,000 r (1-q)` |
| `calc.fee.q80.c` | 0.80 | formula has words left after substituting keys | `D: r q (1-q) x 100 cents, r = fee.rate` |
| `calc.fee.q80.bps` | 100 | free-text formula | `D: 10,000 r (1-q)` |
| `calc.mk.start.p` | 50.0% | free-text formula | `D: src/markov.py TennisModel.win_prob` |
| `calc.mk.start.up` | 51.2% | free-text formula | `D: src/markov.py win_prob after the point is won` |
| `calc.mk.start.dn` | 47.8% | free-text formula | `D: src/markov.py win_prob after the point is lost` |
| `calc.mk.start.lev` | 3.4% | free-text formula | `D: src/markov.py TennisModel.leverage` |
| `calc.mk.bp.p` | 33.7% | free-text formula | `D: src/markov.py TennisModel.win_prob` |
| `calc.mk.bp.up` | 47.3% | free-text formula | `D: src/markov.py win_prob after the point is won` |
| `calc.mk.bp.dn` | 8.9% | free-text formula | `D: src/markov.py win_prob after the point is lost` |
| `calc.mk.bp.lev` | 38.4% | free-text formula | `D: src/markov.py TennisModel.leverage` |
| `calc.vmax.med` | −0.28 | free-text formula | `D: L + R_median - D - delta (pre-registered L)` |
| `calc.vmax.p90` | 0.96 | free-text formula | `D: L + R_p90 - D - delta (pre-registered L)` |
| `calc.roc` | 253% | free-text formula | `D: mean daily $ x 365 / capital (v2 IS)` |
| `gate.lo_range` | 0.5–0.8 | wildcard matched nothing at '.gate_s where correct_kept == gate.corre' in results/engine/r | `results/engine/rally_gate_eval.json::results.emit.*.gate_s where correct_kept == gate.correct.kept_lo` |
| `plat.sizing.pos` | 55 | expression not arithmetic: count(per_share_ci_c[0] > 0) | `research/v2/sizing/out/policies.csv[measure == res, fee_mode == actual] count(per_share_ci_c[0] > 0)` |
| `plat.sizing.cilo` | 0.61 | expression not arithmetic: min(per_share_ci_c[0]) | `research/v2/sizing/out/policies.csv[measure == res, fee_mode == actual] min(per_share_ci_c[0])` |
| `plat.lat.lo` | 0 | ValueError: min() iterable argument is empty | `results/tier0/latency_sweep.json::video_own120 (smallest delay)` |
| `plat.lat.hi` | 60 | ValueError: max() iterable argument is empty | `results/tier0/latency_sweep.json::video_own120 (largest delay)` |
| `plat.lat.rise` | $0.09 | free-text formula | `D: largest rise in $ a day between neighbouring delays, pre-registered and post hoc readings, IS and burned OO` |
| `bt.err.lead` | 0.7–1.2 | cannot descend '300' in results/tennis_tracking/summary.json | `results/tennis_tracking/summary.json::headline.tracknet.median_landing_err_cm.learned.{33..300} (min-max, m)` |
| `wcap.is.cost` | 37% | derived formula over a JSON file (free text) | `D: 1 - results/v2/risk/wallet_cap.json::is_joint_run.with_cap.pnl_usd / is_joint_run.v2_uncapped.pnl_usd` |
| `tab.cv.pre.is.v05.c0` |  | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.pre.oos.v05.c0` | † | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.pre.is.v1.c0` | † | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.pre.oos.v1.c0` | † | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.pre.is.v3.c0` | † | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.pre.oos.v3.c0` | † | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.cal.is.v05.c0` |  | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.cal.oos.v05.c0` |  | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.cal.is.v1.c0` |  | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.cal.oos.v1.c0` |  | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.cal.is.v3.c0` | † | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `tab.cv.cal.oos.v3.c0` | † | key not found at '<reading>.<V>.<period>.net_c_per_share_ci95' in results/tier0/latency_sw | `results/tier0/latency_sweep.json::video_own120.<reading>.<V>.<period>.net_c_per_share_ci95 (dagger if it spans` |
| `cv.fx2.oos.best` | −$13 | wildcard matched nothing at '|oos.seed_mean.fx2_pnl_per_day_usd' in results/tier0/cost_tur | `results/tier0/cost_turnover.json::cells.*|oos.seed_mean.fx2_pnl_per_day_usd (max)` |
| `fresh.traded.range` | 5–10 | selector [*,cov10,all_days] not found in results/fresh_holdout/results.json | `results/fresh_holdout/results.json::table[*,cov10,all_days].n_matches (seed-mean matches with trades, min-max)` |
| `fresh.traded.s2v05` | 7–10 | selector [S2,*,0.5,cov10,all_days] not found in results/fresh_holdout/results.json | `results/fresh_holdout/results.json::table[S2,*,0.5,cov10,all_days].n_matches` |
| `fresh.lic.is.pre` | $787 | key not found at 'licence_breakeven_at_V0.5 ...values_usd_per_month.IS|S2|pre|' in results | `results/fresh_holdout/results.json::licence_breakeven_at_V0.5 ...values_usd_per_month.IS|S2|pre|cov10|all_days` |
| `fresh.lic.is.cal` | $3,976 | key not found at 'licence_breakeven_at_V0.5 ...values_usd_per_month.IS|S2|cal|' in results | `results/fresh_holdout/results.json::licence_breakeven_at_V0.5 ...values_usd_per_month.IS|S2|cal|cov10|all_days` |
| `fresh.lic.oos.pre` | $384 | key not found at 'licence_breakeven_at_V0.5 ...values_usd_per_month.burned_OOS' in results | `results/fresh_holdout/results.json::licence_breakeven_at_V0.5 ...values_usd_per_month.burned_OOS|S2|pre|cov10|` |
| `fresh.lic.oos.cal` | $2,397 | key not found at 'licence_breakeven_at_V0.5 ...values_usd_per_month.burned_OOS' in results | `results/fresh_holdout/results.json::licence_breakeven_at_V0.5 ...values_usd_per_month.burned_OOS|S2|cal|cov10|` |
| `fresh.lic.fresh.pre` | −$701 | key not found at 'licence_breakeven_at_V0.5 ...values_usd_per_month.fresh|S2|p' in results | `results/fresh_holdout/results.json::licence_breakeven_at_V0.5 ...values_usd_per_month.fresh|S2|pre|cov10|all_d` |
| `fresh.lic.fresh.cal` | +$1,467 | key not found at 'licence_breakeven_at_V0.5 ...values_usd_per_month.fresh|S2|c' in results | `results/fresh_holdout/results.json::licence_breakeven_at_V0.5 ...values_usd_per_month.fresh|S2|cal|cov10|all_d` |
| `e2e.feedhold.range` | 93–96% | derived formula over a JSON file (free text) | `D: (feed 1,000 + hold 1,000 ms) / results/sponsors/evidence.json::budget.scenarios.vultr_{london,florida}_cold` |
| `liq.phi.took` | 4–11% | wildcard matched nothing at '.took_share_pooled and phi_official_poin' in results/liquidit | `results/liquidity/impact.json::l2.phi_live_reprices.tau_*.took_share_pooled and phi_official_points.D_ge_3c.ta` |
| `liq.phi.gt_half` | 7–23% | wildcard matched nothing at '.share_events_phi_lo_below_0.5' in results/liquidity/impact.j | `results/liquidity/impact.json::...tau_*.share_events_phi_lo_below_0.5 (events where others took more than half` |
| `liq.v2.1x.oos.cons.ci` | [−$7, $150] | key not found at 'pnl_per_day_boot_{lo,hi}' in results/liquidity/impact.json | `results/liquidity/impact.json::capacity.v2|conservative|burned_OOS.pnl_max.pnl_per_day_boot_{lo,hi}` |
| `liq.cv.half.move` | 1% | free-text formula | `D: |capacity.cv_lagcal|best|central|P / ...|none|P - 1| < 1% (P = IS, burned_OOS)` |
| `liq.cv.pmax.drop` | 6–8% | free-text formula | `D: 1 - capacity.cv_lagcal|best|conservative|P.pnl_max.pnl_per_day_usd / ...|none|P (P = IS, burned_OOS)` |
| `rig2.cvcal.oos.pass` | 4 | key not found at 'PSR0' in results/rigor/psr.json | `D: results/rigor/psr.json::cv.cv_cal_oos (PSR0, PSR2 seed medians >= 0.95; MinTRL met by most seeds; HLZ media` |

## Matches that needed a looser rule (78): check these by eye

A unit scale (x100, x1000, ...), a dropped sign, a range of a list, a count, or digits inside text.

| key | printed | read | rule | source |
|---|---|---|---|---|
| `univ.oos_time` | 10.7% | 0.107449 | x100 | `results/v2/note_metrics.json::holdout.oos_share_of_time` |
| `univ.oos_vol` | 21.2% | 0.212019 | x100 | `results/v2/note_metrics.json::holdout.oos_share_of_volume` |
| `markov.lev` | 5.7% | 0.057157 | x100 | `results/leverage_stats.json::atp.mean_abs_leverage` |
| `fee.rate` | 5% | 0.05 | x100 | `results/financials/financials.json::strategies.v2.periods.OOS.breakeven_taker_fee.uniform_` |
| `ft.slope` | 0.20 | -0.1998 | exact,abs | `results/alpha/alpha.json::headline.fast_tier_slope_c_per_month.IS` |
| `v2.is.start` | Feb 1 | "2026-02-01" | text-digits | `results/lowloss/daily.csv[a,u1_is,v2].date.min` |
| `v2.is.end` | Aug 25 | "2026-08-25" | text-digits | `results/lowloss/daily.csv[a,u1_is,v2].date.max` |
| `v2.oos.start` | Aug 25 | "2026-08-25" | text-digits | `results/lowloss/daily.csv[a,u1_oos,v2].date.min` |
| `v2.oos.end` | Oct 3 | "2026-10-03" | text-digits | `results/lowloss/daily.csv[a,u1_oos,v2].date.max` |
| `v2.is.share_vol` | 0.07% | 0.000717 | x100 | `results/v2/note_metrics.json::is.v2_usd_traded_share_of_match_volume` |
| `decay.sameblock.share` | 98% | 0.984616 | x100 | `D: results/decay/audit_sameblock.json::v2_backtest_trades.IS+burned_OOS same_block.pnl_usd` |
| `conc.top5.is` | 81% | 0.8137 | x100 | `results/alpha/alpha.json::headline.top5_wallet_share_of_pnl.IS` |
| `conc.top5.oos` | 142% | 1.421 | x100 | `results/alpha/alpha.json::headline.top5_wallet_share_of_pnl.OOS` |
| `rig.pbo.lowloss` | 15% | 0.154235 | x100 | `results/rigor/rigor.json::pbo_cscv.lowloss_24_sharpe.pbo` |
| `fac.r2` | 3.3% | 0.0334 | x100 | `results/alpha/alpha.json::C_factor_neutral.IS_committed_spec.r2` |
| `cv.tt.rec50` | 27% | 0.2683 | x100 | `results/tracking/summary.json::early_call.precision_recall_test_snapshot.50ms.recall` |
| `cv.tt.det_recall` | 96.7% | 0.9671 | x100 | `results/tracking/summary.json::detection_accuracy_pooled[test,tracked].recall` |
| `cv.inf` | 20 | 0.02 | x1000 | `results/decay/decay.json::latency_inputs.cv_assumed_s` |
| `lat.book_vs_stamp` | 1.2 | -1.16 | exact,abs | `research/v2/latency/results.json::summary.m1.book_vs_official_T_s.median` |
| `lat.net_fl` | 67 | 0.067 | x1000 | `results/decay/decay.json::latency_inputs.net_florida_s` |
| `lat.net_ldn` | 2 | 0.002 | x1000 | `results/decay/decay.json::latency_inputs.net_london_s` |
| `cv.pre.is.wrong` | 35% | 0.3484 | x100 | `results/tier0/latency_sweep.json::video_own120.tournament.1.IS.wrong_call_share_of_trades` |
| `cv.pre.is.ret` | 30 | 0.30315 | x100 | `D: results/tier0/latency_sweep.csv[video,own120,tournament,IS,x_s=1] pnl_per_day_usd*365/c` |
| `cv.pre.is.dd` | −6.6 | -0.065864 | x100 | `results/tier0/latency_sweep.csv[video,own120,tournament,IS,x_s=1] max_dd_usd/capital_usd` |
| `cv.pre.oos.wrong` | 47% | 0.4723 | x100 | `results/tier0/latency_sweep.json::video_own120.tournament.1.burned_OOS.wrong_call_share_of` |
| `cv.pre.oos.ret` | 11 | 0.11493 | x100 | `D: results/tier0/latency_sweep.csv[video,own120,tournament,burned_OOS,x_s=1] pnl_per_day_u` |
| `cv.pre.oos.dd` | −5.3 | -0.052747 | x100 | `results/tier0/latency_sweep.csv[video,own120,tournament,burned_OOS,x_s=1] max_dd_usd/capit` |
| `cv.cal.is.wrong` | 12% | 0.1208 | x100 | `results/tier0/latency_sweep.json::video_own120.tournament_lagcal.1.IS.wrong_call_share_of_` |
| `cv.cal.is.ret` | 118 | 1.178127 | x100 | `D: results/tier0/latency_sweep.csv[video,own120,tournament_lagcal,IS,x_s=1] pnl_per_day_us` |
| `cv.cal.is.dd` | −1.6 | -0.015857 | x100 | `results/tier0/latency_sweep.csv[video,own120,tournament_lagcal,IS,x_s=1] max_dd_usd/capita` |
| `cv.cal.oos.wrong` | 16% | 0.1597 | x100 | `results/tier0/latency_sweep.json::video_own120.tournament_lagcal.1.burned_OOS.wrong_call_s` |
| `cv.cal.oos.ret` | 91 | 0.914968 | x100 | `D: results/tier0/latency_sweep.csv[video,own120,tournament_lagcal,burned_OOS,x_s=1] pnl_pe` |
| `cv.cal.oos.dd` | −1.6 | -0.016079 | x100 | `results/tier0/latency_sweep.csv[video,own120,tournament_lagcal,burned_OOS,x_s=1] max_dd_us` |
| `venue.batch` | 35% | {"value": 0.349, "source": "results/redteam/stamp_ | x100 | `results/redteam/derived.json::keys.venue.reprices_0_100ms_after_second <- results/redteam/` |
| `risk.feed_stale` | 2 | 2000 | /1000 | `results/engine/demo_run_L4.json::risk_config.feed_stale_ms` |
| `risk.vision_stale` | 1 | 1000 | /1000 | `results/engine/demo_run_L4.json::risk_config.vision_stale_ms` |
| `fin.be_fee.before` | 8.2% | 0.081937 | x100 | `results/financials/financials.json::strategies.v2.periods.OOS.breakeven_taker_fee.rate_bef` |
| `fin.be_fee.central` | 2.4% | 0.024108 | x100 | `results/financials/financials.json::strategies.v2.periods.OOS.breakeven_taker_fee.rate_aft` |
| `liq.spread` | 1 | 0.01 | x100 | `research/v2/latency/results.json::summary.side_market_spreads_live.moneyline.median_spread` |
| `var.maker` | 8 | ["1 maker v1 (primary)", "2 stress (i) queue share | count of list | `results/maker/oos.json::variants_evaluated` |
| `v2s.is.vol` | 15.2% | 0.152365 | x100 | `D: results/rigor/rigor.json::sharpe_moments.v2safe_is.sd_daily_usd / capital_usd x sqrt(36` |
| `v2s.oos.vol` | 18.4% | 0.183527 | x100 | `D: results/rigor/rigor.json::sharpe_moments.v2safe_oos.sd_daily_usd / capital_usd x sqrt(3` |
| `ev.livefill.fill30` | 27% | 0.2672 | x100 | `research/v2/livefill/results.json::by_mode[inside].fill_30s` |
| `ev.livefill.post` | +5.6 | -5.6285 | exact,abs | `research/v2/livefill/results.json::by_mode[inside].post_fill_30s_c (sign: mid move against` |
| `ev.kalshi.first` | 68.9% | 0.688943 | x100 | `research/v2/kalshi/out/leadlag_summary.json::lead_all.p_kalshi_first` |
| `tn.real.ball` | 89% | 0.89 | x100 | `results/viz/v60_assets/tennis_real/tennis_detections.json::stats.ball_detected_share` |
| `gate.n` | 4 | {"0.5": {"gate_s": 0.5, "a_priori": false, "miss_c | count of entries | `results/engine/rally_gate_eval.json::results.emit (gate values run, none chosen)` |
| `gate.sweep` | 0.5–1.2 | [0.5, 0.8, 1.2, 2.0] | checked by hand: rally_gate_eval.json emit gates 0.5/0.8/1.2 (post hoc) and 2.0 (a_priori); printed range is the post hoc sweep: check the sentence says so | `results/engine/rally_gate_eval.json::results.emit.*.gate_s (sweep values)` |
| `plat.pbo` | 9–24% | [{"pbo": 0.15423465423465424, "pbo_strict_lt0": 0. | checked by hand: PBO over research/rigor/out/verify.json::pbo.sharpe* block choices = 0.092-0.243 -> 9-24% | `research/rigor/out/verify.json::pbo.sharpe* (v2-safe grid, Sharpe rule; min-max over block` |
| `plat.lat.n` | 14 | {"0": {"IS": {"net_c_per_share": 1.098, "net_c_per | count of entries | `results/tier0/latency_sweep.json::video_own120.tournament (grid of feed delays)` |
| `ft.months.cal` | 11 | [[1.969, 2.4098, 1.2087, 2.0198, 1.4256, 0.8029, 0 | checked by hand: alpha.json A_source months: 9 IS + 3 OOS, all fast_net30_c > 0; Aug in both -> 11 calendar months | `results/alpha/alpha.json::A_source.{IS,OOS}.months[*].fast_net30_c (calendar months, all >` |
| `cov.mcp.years` | 2020–26 | [[2020, 2026], [2020, 2026]] | year range | `results/data_coverage.json::match_charting_project.{men,women}.years` |
| `pm.out` | 36–41% | [0.362, 0.4125] | x100 | `results/tier0/inputs/point_mix.json::{men,women}.out` |
| `pm.net` | 25–26% | [0.2521, 0.2596] | x100 | `results/tier0/inputs/point_mix.json::{men,women}.net` |
| `pm.win` | 29–35% | [0.3515, 0.2916] | x100 | `results/tier0/inputs/point_mix.json::{men,women}.winner` |
| `bt.rec0` | 50% | 0.5 | x100 | `results/tennis_tracking/summary.json::headline.tracknet.out_calls_margin_rule.ground.test_` |
| `bt.det.prec` | 97% | 0.97387 | x100 | `results/tennis_tracking/summary.json::detector_accuracy_vs_labels.test_games_8_10.precisio` |
| `bt.det.rec` | 94% | 0.942414 | x100 | `results/tennis_tracking/summary.json::detector_accuracy_vs_labels.test_games_8_10.recall_5` |
| `wcap.oos.top5` | 129% | 1.290042 | x100 | `results/v2/risk/wallet_cap.json::oos.with_cap.top5_wallet_share_of_pnl` |
| `fresh.days` | 2 | ["2026-10-03", "2026-10-04"] | count of list | `results/fresh_holdout/results.json::days` |
| `fresh.excluded` | 9 | ["wta-andree-boisson-2026-10-03", "wta-bencic-zakh | count of list | `results/fresh_holdout/results.json::fetch.dropped_live_calibration_matches` |
| `fresh.show.title` | Antonia Ruzic v Leolia Jeanjean | "Adana: Antonia Ruzic vs Leolia Jeanjean" | text-words | `results/fresh_holdout/results.json::showcase.title` |
| `fresh.show.event` | WTA Adana | ["wta", "Adana"] | text-words | `results/fresh_holdout/results.json::showcase.{series,league}` |
| `wcap.oos.top5.cap_only` | 141% | 1.408972 | x100 | `results/v2/risk/wallet_cap.json::oos.decomposition_cap_only.top5_wallet_share_of_pnl` |
| `wcap.oos.top5.retire_only` | 122% | 1.219504 | x100 | `results/v2/risk/wallet_cap.json::oos.decomposition_retire_only.top5_wallet_share_of_pnl` |
| `wcap.is.kept` | 63% | 0.629838 | x100 | `D: results/v2/risk/wallet_cap.json::is_joint_run.with_cap.pnl_usd / is_joint_run.v2_uncapp` |
| `wcap.is.top5` | 87% | 0.872943 | x100 | `results/v2/risk/wallet_cap.json::is_joint_run.with_cap.top5_wallet_share_of_pnl` |
| `wcap.base.is.top5` | 81% | 0.813662 | x100 | `results/v2/risk/wallet_cap.json::is_joint_run.v2_uncapped.top5_wallet_share_of_pnl` |
| `risk.pm.twosided.is` | 79% | 0.787145 | x100 | `results/v2/risk/per_match_loss.json::is.v2_uncapped.share_matches_buying_both_sides` |
| `risk.pm.twosided.oos` | 71% | 0.711433 | x100 | `results/v2/risk/per_match_loss.json::oos.v2_uncapped.share_matches_buying_both_sides` |
| `pers.slope.net` | 0.16 | -0.1551 | exact,abs | `results/economics/persistence.json::fits.linear_wls_cal11.slope_c_per_month.coef` |
| `pers.slope.net.ci` | 0.06–0.25 | [-0.2463, -0.0639] | exact,abs-range | `results/economics/persistence.json::fits.linear_wls_cal11.slope_c_per_month.ci95` |
| `pers.dnet` | 0.85 | -0.8547 | exact,abs | `results/economics/persistence.json::composition.delta_net_c` |
| `pers.dfee` | 0.54 | -0.5371 | exact,abs | `results/economics/persistence.json::composition.fee_part_c` |
| `pers.ddilution` | 0.40 | -0.3961 | exact,abs | `results/economics/persistence.json::composition.entrant_dilution_c` |
| `pers.fee35.jul` | 0.29 | -0.2916 | exact,abs | `results/economics/persistence.json::regime.natural_experiments.fee_3_to_5_jul2026.net30.b_` |
| `pers.fee35.jul.ci` | 0.11–0.47 | [-0.4652, -0.109] | exact,abs-range | `results/economics/persistence.json::regime.natural_experiments.fee_3_to_5_jul2026.net30.ci` |
| `copier.sameside` | 69–80% | [0.6914137533615059, 0.797294383960332] | x100 | `results/rigor/psr.json::copier.{oos,is}.central.share_priced_from_same_side_print` |

## Numbers-file raw values that print differently (3)

- `cv.v0.check`: numbers file raw True does not print as 'identical'
- `t0.prereg.time`: numbers file raw '2026-10-03T15:24:26-04:00' does not print as '19:24'
- `bt.bounces.all`: numbers file raw {'train': 267, 'test': 132} does not print as '399'

## Numbers on PDF pages 1-5 that are not in the numbers file (1)

Candidates for hard-coded numbers. Years, section/figure/table/reference numbers and 0/1 are skipped; many of the rest are harmless (ranges, rule thresholds, citations) and need a human look.

| page | printed | context |
|---|---|---|
| 3 | -$5.2k | cumulative net P&L, $k OOS All costs ×2 OOS −$5.2k Fees ×2 OOS −$2.1k Base OOS +$3.7k |

## Template digits that equal a printed result (65)

Typed into `docs/paper/note.tex.j2` instead of `<< V('key') >>`. Most are rule constants that happen to equal a result; any that *is* the result should use the macro so it can't go stale.

| line | literal | same value as | context |
|---|---|---|---|
| 7 | 5 | fee.rate, v2.is.cx2.mpos, pol.dd_stop | Layout: 5 main pages with 2 tables (headline metr |
| 10 | 11 | cv.tt.tp50, cv.tt.called50, cv.pre.oos.ret | igures_v2.py, house style docs/paper/figstyle.py, 11-12 pt type). #> |
| 10 | 12 | cv.cal.is.wrong, spin.tt.calls50, wcap.n | res_v2.py, house style docs/paper/figstyle.py, 11-12 pt type). #> |
| 11 | 11 | cv.tt.tp50, cv.tt.called50, cv.pre.oos.ret | \documentclass[11pt,letterpaper]{article} |
| 26 | 2.2 | cv.cal.be.range | ine=false,leftline=true,linecolor=gator,linewidth=2.2pt, |
| 27 | 7 | v2.is.mpos, v2.is.mpos, v2.is.fx2.mpos | innerleftmargin=7pt,innerrightmargin=0pt,innertopmargin=1 |
| 28 | 4 | ft.wallets.first, cv.pre.oos.usd, cv.eng.pre.oos.usd | skipabove=4pt,skipbelow=3pt]{firmbox} |
| 36 | 4, | ft.wallets.first, cv.pre.oos.usd, cv.eng.pre.oos.usd | {October 4, 2026}{gqh_logo.png} |
| 52 | 0.5 | lat.video_band, gate.sweep, gate.lo_range | ) post hoc; with a licensed 0.5\,s feed, or |
| 84 | 25 | univ.oosstart, v2.is.end, v2.oos.start | early at an assumed 25\,fps (earliest of right calls at that |
| 99 | 0.25 | cv.cal.react, cv.pool482.oos, pers.slope.net.ci | of quotes still rested at stale prices 0.25\,s before the reprice |
| 100 | 0.5 | lat.video_band, gate.sweep, gate.lo_range | ( after 0.5\,s), and Polymarket holds each taker or |
| 104 | 30 | lat.pmsports, cv.pre.is.ret, cv.phantom.hr | arkets to earn a positive net \emph{markout} over 30\,s (profit at the price 30\,s later, af |
| 104 | 30 | lat.pmsports, cv.pre.is.ret, cv.phantom.hr | et \emph{markout} over 30\,s (profit at the price 30\,s later, after fees), because the |
| 124 | 50 | prereg.hyp.time, calc.mk.start.p, bt.rec0 | settled 50/50 ( never started) and ended in a r |
| 124 | 50 | prereg.hyp.time, calc.mk.start.p, bt.rec0 | settled 50/50 ( never started) and ended in a reti |
| 125 | 80 | sc.cal.is.v05.uci, copier.sameside | tlement price. \emph{In sample} (IS) is the first 80\% of matches by start time, \emph{out o |
| 126 | 20 | cv.inf, cv.seeds, h1.neg | , from (the 20\%-or-two-years rule); we looked at it w |
| 135 | 5 | fee.rate, v2.is.cx2.mpos, pol.dd_stop | and the fee rose from 3\% to 5\%; v2 is positive in each ( ¢ to |
| 141 | 10 | prereg.hyp.time, pol.q_matches, spin.tt.tp50 | 3\,s after a score move (a \(\geq\) ¢ move of the 10\,s price |
| 142 | 60 | plat.lat.hi | from its prior 60\,s) in + matches (\(t > \)). |
| 162 | 95 | risk.maxloss, cov.tn.clips | calls met our 95\% rule. Our live engine makes about p |
| 170 | 10 | prereg.hyp.time, pol.q_matches, spin.tt.tp50 | its own taker fee \(f(q) = r\,q(1-q)\) a share, \(10{,}000\,r(1-q)\) bps |
| 209 | 30 | lat.pmsports, cv.pre.is.ret, cv.phantom.hr | ier earns, and the edge is thin.} (a)~Monthly net 30\,s markout (copying 3\,s later: |
| 217 | 5 | fee.rate, v2.is.cx2.mpos, pol.dd_stop | ; a 5-day block bootstrap): v2 passes all six |
| 218 | 40 | v2.oos.days, cv.pre.oos.days, cv.cal.oos.days | ) but on the 40-day burned OOS (PSR vs 2 is |
| 233 | 0.5 | lat.video_band, gate.sweep, gate.lo_range | \caption{\emph{A firm with a licensed 0.5\,s feed} (counterfactual). (a)~Equity c |
| 234 | 20 | cv.inf, cv.seeds, h1.neg | trader (20-seed mean, whiskers 10--90\%; black pre |
| 234 | 10 | prereg.hyp.time, pol.q_matches, spin.tt.tp50 | trader (20-seed mean, whiskers 10--90\%; black pre-registered, orange pos |
| 234 | 90 | v2s.is.turnover | trader (20-seed mean, whiskers 10--90\%; black pre-registered, orange post ho |
| 240 | 0.5 | lat.video_band, gate.sweep, gate.lo_range | \textbf{If we were a quant firm with a licensed 0.5\,s feed} (Fig.~ ). Counterfactual: real |
| 241 | 0.5 | lat.video_band, gate.sweep, gate.lo_range | calls; no feed bought, no order placed. At \(V = 0.5\)\,s the Table~ trader makes |
| 267 | 5 | fee.rate, v2.is.cx2.mpos, pol.dd_stop | shares net at 5--95¢, which caps the open position at |
| 267 | 95 | risk.maxloss, cov.tn.clips | shares net at 5--95¢, which caps the open position at , no |
| 269 | 3,000 | e2e.req | match made IS, OOS. Only the backtest's \$3,000 gross cap per |
| 271 | 30 | lat.pmsports, cv.pre.is.ret, cv.phantom.hr | sion, or slow latency, halve size if the trailing 30-day edge falls |
| 275 | 0.95 | rp.sel.t4.c, risk.zone, liq.temp.mid.small | always fill, so out calls need confidence \(\geq\)0.95 and one false call |
| 287 | 5 | fee.rate, v2.is.cx2.mpos, pol.dd_stop | v2 holds its OOS edge up to of capital (5\(\times\) loses), trading |
| 291 | 10 | prereg.hyp.time, pol.q_matches, spin.tt.tp50 | size ( ¢ a share at 1--10 shares, ¢ at 10,000+ in the |
| 291 | 10,000 | fin.feed.high | size ( ¢ a share at 1--10 shares, ¢ at 10,000+ in the |
| 292 | 1,000 | risk.order_usd, risk.daily_stop, wcap.W | highest-volume fifth), the mid moves ¢ more per 1,000 shares at 30\,s (less on burned-OOS |
| 315 | 4.0 | ft.wallets.first, cv.pre.oos.usd, cv.eng.pre.oos.usd | ot build: the Match Charting Project (CC BY-NC-SA 4.0), the TrackNet broadcast tennis set and |
| 367 | 5 | fee.rate, v2.is.cx2.mpos, pol.dd_stop | . Resample days in blocks of random length (mean 5 days) |
| 368 | 10,000 | fin.feed.high | 10,000 times and read the percentiles. v2 OOS |
| 372 | 5 | fee.rate, v2.is.cx2.mpos, pol.dd_stop | daily return on capital, with Newey--West errors (5 lags) |
| 379 | 10 | prereg.hyp.time, pol.q_matches, spin.tt.tp50 | \(10{,}000\,r(1-q)\) bps. At \(r = \): \(q |
| 379 | 0.5 | lat.video_band, gate.sweep, gate.lo_range | \(10{,}000\,r(1-q)\) bps. At \(r = \): \(q = 0.5\) pays ¢ |
| 380 | 0.8 | capcv.pre.sr0.oos, h2.oos.c, calc.fee.q80.c | ( \,bps) and \(q = 0.8\) pays ¢ ( \,bps). |
| 385 | 5 | fee.rate, v2.is.cx2.mpos, pol.dd_stop | , so \(\Delta = \). Serving at 5--5, 30--40 in the deciding |
| 385 | 5, | fee.rate, v2.is.cx2.mpos, pol.dd_stop | , so \(\Delta = \). Serving at 5--5, 30--40 in the deciding |
| 385 | 30 | lat.pmsports, cv.pre.is.ret, cv.phantom.hr | , so \(\Delta = \). Serving at 5--5, 30--40 in the deciding |
| 385 | 40 | v2.oos.days, cv.pre.oos.days, cv.cal.oos.days | , so \(\Delta = \). Serving at 5--5, 30--40 in the deciding |
| 396 | 4 | ft.wallets.first, cv.pre.oos.usd, cv.eng.pre.oos.usd | each held 4\,h or until resolution. v2 IS: peak , |
| 445 | 4, | ft.wallets.first, cv.pre.oos.usd, cv.eng.pre.oos.usd | \quad newest matches & same & of & Oct 3--4, 2026 & fresh holdout \\ |
| 451 | 120 | v2.is.fee_bps | OpenTTGames ; Pexels & 120\,fps video; phone video & held-out mi |
| 475 | 95 | risk.maxloss, cov.tn.clips | share by venue regime (taker hold\,/\,fee), 95\% CIs; (b)~net P\&L by month, at the fa |
| 482 | 30 | lat.pmsports, cv.pre.is.ret, cv.phantom.hr | trading every point on real books loses.} (a)~Net 30\,s markout by |
| 484 | 10 | prereg.hyp.time, pol.q_matches, spin.tt.tp50 | 2026-10-03 against their real order books, ever |
| 484 | 30 | lat.pmsports, cv.pre.is.ret, cv.phantom.hr | oks, every point called; net ¢ a share marked at +30\,s with match-clustered |
| 485 | 95 | risk.maxloss, cov.tn.clips | 95\% CIs; \(\times\): the sweep's OOS cell |
| 493 | 3.14 | cv.cal.lag | ed from the pre-registered 2.0\,s to the post hoc 3.14\,s |
| 505 | 50 | prereg.hyp.time, calc.mk.start.p, bt.rec0 | capital (net cap 50 to 5,000 shares, \$250 orders, 10 match |
| 505 | 5,000 | univ.minvol, fin.feed.central | capital (net cap 50 to 5,000 shares, \$250 orders, 10 matches a day, |
| 505 | 250 | fee.bps_q05, calc.fee.q50.bps | capital (net cap 50 to 5,000 shares, \$250 orders, 10 matches a day, half the stal |
| 505 | 10 | prereg.hyp.time, pol.q_matches, spin.tt.tp50 | apital (net cap 50 to 5,000 shares, \$250 orders, 10 matches a day, half the stale depth); c |

## Recomputed from row-level files

- `v2.is.sr` printed 14.5: rows give 14.48 (results/lowloss/daily.csv run a/u1_is/v2: calendar-daily P&L, 206 days, mean/sd x sqrt(365))
- `v2.oos.sr` printed 6.7: rows give 6.668 (results/lowloss/daily.csv run a/u1_oos/v2: calendar-daily P&L, 40 days, mean/sd x sqrt(365))

