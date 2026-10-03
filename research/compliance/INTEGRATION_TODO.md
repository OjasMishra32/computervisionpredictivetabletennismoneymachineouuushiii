# Integration TODO: judge attacks → paper, video, deck (exact edit list)

Written 2026-10-03 ~22:45 UTC by the Q&A-prep workflow. This file is **instructions only**: it edits none of the
files it names, because other workflows own them (paper: `docs/paper/**`, `scripts/build_paper.py`,
`scripts/paper_figures.py`; video: `docs/video_script_v2.md`, `scripts/make_video_v2.py`; e2e and capacity:
`engine/e2e/**`, `scripts/capacity_study.py`, `results/e2e|capacity`; replay: `results/replay/**`; showcase:
`scripts/cv_showcase*.py`; WebRTC: `engine/webrtc/**`). The deck (`docs/deck/build_deck.py`), README and
DEVPOST have no listed owner; apply those edits in the integration pass. The answers that go with these edits are
in `docs/QA_PREP.md` (Q-numbers below).

Rules for every edit: every number comes from a results file through the existing macro or manifest mechanism
(never typed); never run `scripts/forward_test.py` or `scripts/tier0_v3_forward.py`; any new read of burned-OOS or
forward data gets a `results/oos_peeks.log` line **before** the run; paper stays ≤ 5 pages at 11 pt
(`\pageref{lastmain} ≤ 5`).

Severity: **P0** = can trigger the criterion-5 cap ("lookahead bias or tuning on the out-of-sample period",
REQUIREMENTS item 53), a claims-vs-code mismatch, or an on-screen contradiction; **P1** = the organizer's own
questions or a criterion 1/4 hit; **P2** = consistency and ops.

## Status after the red-team / integration pass (2026-10-03, about 23:45 UTC)

Done in this pass (files no other workflow was editing): the deck (D-1 to D-8, rebuilt; `run_checks` passes), README
(§4 rows, the judge box, CLEAN_CLONE N12), DEVPOST (§4), `docs/RISK.md`, `run.sh` (`redteam`, `preflight`),
CLEAN_CLONE N2 (`run_all.py` guard) and N3 (`scripts/money_counter.py` guard), C3, C4, C5, C6, C9 and the §7
acceptance checks as a script. Every remaining item is QUEUED with its owner below; §8 adds the new items this pass
found. Run `bash run.sh redteam` for the current acceptance table, and `bash run.sh preflight` before 11:20 UTC.

| Item | Status | Where |
|---|---|---|
| P-1 … P-16 | QUEUED → paper workflow (`docs/paper/**`, `scripts/build_paper.py`, `scripts/paper_figures.py`) | read every P-13 key from `results/redteam/derived.json::keys.<key>.value` (§8 R-2) |
| V-1 … V-9 | QUEUED → video workflow (`docs/video_script_v2.md`, `scripts/make_video_v2.py`) | acceptance check 1 still finds "Calibrated from the data", "Stricter readings lose" and "goes live" in `docs/video_script_v2.md` (lines 180, 181, 261 at 23:30 UTC) |
| D-1 … D-8 | DONE | slide 7 is now "The 1 s baseline" (four readings, pre-registered first; $/day-vs-V chart; L needed; data ceiling); slide 4 shows the live causal engine (4/4 correct, 4 of 41, 162.5 ms; GPU 4.6 ms); slide 8 has the measured frame → executable-order strip from `results/e2e/summary.json`; slide 9 has capacity and the data ceiling and a CV @ 1 s row; slide 10 "Next"; backups Q10 rewritten, Q11–Q14 added (Q13 = Dom's latency, Q14 = Dom's capacity) |
| §4 README / DEVPOST | DONE | 9/9 + 3/3 months; live-engine CV numbers; the 1 s row leads with the pre-registered break-even; capacity row; `bash run.sh redteam` |
| C1 | QUEUED → replay workflow | see C-table |
| C2 | NOT FEASIBLE | documented in C-table |
| C3, C4, C5, C6 | DONE | `results/redteam/` |
| C7, C8 | IN PROGRESS (owners) | acceptance checks `C7`, `C8` |
| C9 | DONE (script); run once after the pinned runs | `python scripts/forward_test_safe.py --end "<results/v2/forward.json window[1]>"` |
| §6 ops | `bash run.sh preflight` added (read-only); the user actions remain the user's | §8 R-8 |
| §7 acceptance | automated: `scripts/redteam_acceptance.py` (`--strict` before the final push) | 10 FAIL at 23:30 UTC, all in paper/video files owned by other workflows |
| `engine/strategy.py` rally-state gate | DONE (code + 3 tests, after the e2e run finished and was committed): `StrategyConfig.rally_gate_s`, **off by default** so the committed demo/e2e reproduce; the HiPerGator evaluation on the full event log is QUEUED | §8 R-3 |
| CLEAN_CLONE N1 (`src/polymarket.py` back-off) | QUEUED until after 11:30 UTC: `src/polymarket.py` is on the pinned forward path | — |
| CLEAN_CLONE N4, N5 (`scripts/live_paper.py`), N7 (`engine/run.py`), N10 (`docs/NOTE.md`), N11 | QUEUED → owners (live session running; e2e imports `engine.run`; paper workflow) | — |
| CLEAN_CLONE N6 (publish the frozen model), N8 (commit live/e2e/capacity results), N13 (push) | USER: needs `gh release` / `git push`, which this pass may not do | §6 runbook |

---

## 0. Merged attack ledger (six reviewer passes, deduplicated to 14)

| ID | Attack (short) | Raised by | Sev | Q&A | Paper | Video | Deck | Compute |
|---|---|---|---|---|---|---|---|---|
| U1 | CV trade set = points that later moved ≥ 4¢ (selected on outcomes); the ex-ante replay loses 36/36 | Jane Street 1, microstructure 2, UF 1 | P0 | Q4 | P-1, P-2, P-3, P-4, P-6 | V-1, V-5 | D-1, D-7 | C1 |
| U2 | Headline uses the post hoc 3.14 s lag; "calibrated from the data"; timing reading revised after first P&L (V3); PREREG committed with results | Jane Street 2, Citadel 1, UF 2, organizer 1 | P0 | Q5, Q11 | P-1, P-2, P-3, P-11 | V-1 | D-1, D-2 | C3 |
| U3 | The same inference applied per point loses $17/day (break-even 0.34/0.30 s) and is not shown; "calibrated" names two different readings | Jane Street 2, microstructure 1, organizer 1 | P0 | Q6 | P-3, P-9 | V-1 | D-1 | C4 |
| U4 | CV recall/leads come from an offline evaluation with a look-ahead feature (`hb`); live causal engine calls 4/41; the paper plan's Fig. 1b caption says the engine "matches the offline evaluation exactly" | organizer 2, microstructure 2 | P0 | Q10 | P-5, P-3 | V-3, V-4 | D-3, D-7 | C5 |
| U5 | Video S02 says the book reprices 0.7–1.3 s after the bounce; a 1 s order lands ≈ 2.05 s after it | microstructure 1, organizer 1(b) | P0 | Q7 | P-4 | V-2 | D-2 | none |
| U6 | 1 s at L = 3.14 s is the courtside-camera result relabelled (exact model identity) | microstructure 1, UF 2, organizer 1(c) | P1 | Q8 | P-4, P-9 | V-1 | D-1 | none |
| U7 | Inference assumes human courtsiders (0.25 s); machines? | Citadel 1, Jane Street 2 | P1 | Q9 | P-8 | none | D-7 | done (QA_PREP §5); C3 |
| U8 | **Dom:** prove the pipeline trades inside < 3 s, frame to order | organizer (Dom), UF 3 | P1 | Q1 | P-10, P-4 | V-7 | D-4, D-7 | C7 |
| U9 | **Dom:** capital capacity | organizer (Dom) | P1 | Q2 | P-7 | V-8 | D-5 | C8 |
| U10 | After data costs it is not a business; "license a feed and this goes live" is unsupported | Citadel 2, organizer 1(d) | P0 | Q12 | P-7, P-8 | V-6 | D-5, D-6 | done (QA_PREP §5) |
| U11 | Sub-second tennis video is sold only to licensed sportsbooks | organizer 1(e), UF 3 | P1 | Q3 | P-8 | V-1, V-8 | D-7 | none |
| U12 | "Which number is your performance?" Headline picks the only positive reading | organizer 1 | P0 | Q11 | P-1, P-2 | V-1, V-5, V-6 | D-1, D-6 | none |
| U13 | Disclosure: sweep cells and the lag choice not in the trial count; V = 1 s chosen after the sweep; peek line 63 logged after its run | organizer 1(a), UF 2, Citadel 1 | P1 | Q17, Q25 | P-11 | V-8 | D-7 | none |
| U14 | Readiness: overnight power, RAM/disk, deadline vs the 11:30 UTC runs, the promised v2-safe forward result, stale "running" cells | readiness | P0 ops | Q23 | P-14 | V-8 | D-4 | C9, §6 |

---

## 1. Paper: `docs/paper/PLAN.md`, `main.tex`, `scripts/build_paper.py`, `scripts/paper_figures.py` (paper workflow)

Highest severity first. "⟨key⟩" = macro from `numbers.json`; new keys are listed in P-13.

**[QUEUED → paper workflow]** **P-1 (P0; U1, U2, U12) Abstract.** Replace the whole abstract (PLAN §4 "Abstract") with this text. It is 135
words, under the 140 cap.

> We study who profits from speed in Polymarket's in-play tennis moneylines (⟨univ.matches⟩ matches, public tapes).
> A walk-forward fast tier of wallets trading within 3 s of a score move earns after fees in every in-sample and
> held-out month; other takers lose, and copying the same trades 3 s later loses. At the fast tier's own fills a
> frozen book earns ⟨v2.oos.c⟩¢ per share out of sample (Sharpe ⟨v2.oos.sr⟩) but turns negative when fees double.
> We then price the speed a computer-vision trader needs (simulated; assumed feed latency, licensed feed not
> purchased; parameters measured). Pre-registered, it breaks even at a ⟨cv.pre.be.oos⟩–⟨cv.pre.be.is⟩ s feed
> delay: at a 1 s licensed-feed baseline it earns ⟨cv.pre.oos.usd⟩/day out of sample (⟨cv.pre.oos.c⟩¢ per share).
> A post hoc stamp-lag inference gives ⟨cv.cal.oos.usd⟩/day; a one-day replay on real books loses. Real money: none.

**[QUEUED → paper workflow]** **P-2 (P0; U1, U2, U12) Key-findings box, bullets 3–5.** Replace:
* Bullet 3 → "**Headline OOS.** v2 at fast-tier fills: ⟨v2.oos.c⟩¢ [⟨v2.oos.ci⟩], Sharpe ⟨v2.oos.sr⟩. CV at the 1 s
  baseline, pre-registered: ⟨cv.pre.oos.usd⟩/day, ⟨cv.pre.oos.c⟩¢ [⟨cv.pre.oos.ci⟩] (break-even). Post hoc (stamp lag
  ⟨cv.cal.lag⟩ s; trade set selected on outcomes): ⟨cv.cal.oos.usd⟩/day. Replay on real books: ⟨rp.v1l2.c⟩¢."
* Bullet 4 → "**Speed.** Pre-registered break-even ⟨cv.pre.be.oos⟩–⟨cv.pre.be.is⟩ s: the call must reach the venue
  ⟨cv.call_before_stamp⟩ s before the umpire's stamp. Post hoc readings: ⟨cv.cal.be.oos⟩–⟨cv.cal.be.is⟩ s or
  ⟨cv.stc.be.oos⟩–⟨cv.stc.be.is⟩ s."
* Bullet 5 → "**What failed.** Fees ×2 OOS (⟨v2.oos.fx2.c⟩¢); the blind unseen-market, maker and tier-0 v3 tests;
  table tennis; v2 OOS net of a central feed licence (⟨fin.v2.oos.net_central⟩/day)." (The replay moved to bullet 3;
  "Real money: none" is already in the abstract and the footnote.)
* Net change about +5 words. Delete "Public streams … lose" from bullet 4; it stays in Fig. 1a and Fig. 3a.

**[QUEUED → paper workflow]** **P-3 (P0; U1, U2, U3, U4) Table 2.**
* **Column order:** the **pre-registered** group (L = 2.0 s) comes first and its header is bold; then "**Post hoc**
  L = ⟨cv.cal.lag⟩ s (assumes courtside humans)". Rename every "calibrated" label in the paper to "post hoc"
  (plan §0.4, §4, §7, §13, Fig. 3 captions). The word "calibrated" must not appear without "post hoc".
* **Caption** → "**Table 2.** *At a simulated 1 s licensed-feed baseline the pre-registered reading breaks even;
  the sign turns on one unmeasured number, the stamp lag.*" Keep the second sentence ("Simulated at a 1 s
  licensed-feed baseline: assumed feed latency (licensed feed not purchased); parameters measured.").
* **New row 8:** "Same clocks read per point, $/day (break-even V)". Pre-registered cells: stamp-noise reading
  `video_own120.stamp["1"].{IS,burned_OOS}.usd_per_day` (−17 / −17; "none"). Post hoc cells: stamp-calibrated
  `video_own120.stamp_calibrated["1"]…usd_per_day` (−17 / −17) with `breakeven_video_delay.stamp_calibrated.{IS,burned_OOS}.breakeven_V_s_seed_mean_curve`
  (0.34 / 0.30 s).
* **New row 9:** "No early CV calls (pessimistic), $/day". Pre-registered cells:
  `video_cv_pessimistic.tournament["1"]…usd_per_day` (+8 / −13). Post hoc cells: the C5 run when it exists;
  until then print `video_cv_pessimistic.tournament["0"]` (+73 / +32) with the dagger note "† at L = 3.0 s,
  exact by Eq. (3) (V = 0 at L = 2.0 s)".
* **Notes, replace the current list with:**
  1. "Trade set: historical points the market later repriced by ≥ 4¢, selected on outcomes (not ex ante), so
     every column is an upper bound. The ex-ante replay on nine real books loses at every V and lag (Fig. 3d,
     Table 3); widening the pool to all 482 live points halves the edge (⟨cv.pool482.oos.c⟩¢ OOS at V = 0)."
  2. "Both groups use the per-tournament timing reading adopted after the first P&L run (`DEVIATIONS.md` V3).
     The post hoc lag assumes the fast tier are courtside humans (0.25 s reaction); it was a pre-registered grid
     point, not the primary."
  3. "CV recall is the offline snapshot rule, which used a look-ahead feature; the live causal engine calls
     ⟨eng.tp⟩ of ⟨eng.nmiss⟩ misses (Fig. 1b). Row 9 removes early calls entirely."
  4. Keep "Pre-registered OOS: positive $/day but negative ¢/share; both are shown."
  5. Keep "Seed means over 20 simulated tournament draws; Sharpe is a ranking of a simulation and ignores model
     risk."
  6. Merge the turnover and equity-curve notes: "No turnover or equity curve at V = 1 s (the sweep stores no daily
     path; Fig. 3 shows the dispersion)."
  7. Move "At stamp lag 1.0 s …" and "V = 0 reproduces the published tier-0 headline" to the Table A1 notes.
* Build assert: rows 8–9 equal the JSON cells; the pre-registered group is the first `\cmidrule` group.

**[QUEUED → paper workflow]** **P-4 (P0; U1, U5, U6, U8) §4 Methodology, CV paragraph.**
* After "…fills against the live recorded books (482 official points)." insert: "The trade set is the historical
  ≥ 4¢ detector set, selected on realised moves (not ex ante); the replay (§5) calls every point. Only
  t_reprice − t_b enters Eq. (3), so the 1 s cell at L = ⟨cv.cal.lag⟩ s equals the pre-registered model with a
  camera ⟨cv.cal.shift⟩ s ahead of the bounce." (+53 words.)
* Replace "L is unmeasured, so we report two readings: the **pre-registered** L = ⟨cv.pre.lag⟩ s and the
  **calibrated, post hoc** L = ⟨cv.cal.lag⟩ s, inferred from fast-tier timing." with "L is unmeasured; Table 2
  shows every reading." (−20 words.)
* Delete "V is swept from 0 to 60 s with 20 seeds per cell." (−12 words; the Fig. 3 caption carries it.)
* Optional, if P-10's e2e number exists: add to the same paragraph "Our own pipeline, frame to order-ready, takes
  ⟨e2e.p50⟩ ms p50 (Fig. 1a); the venue's 1 s hold dominates." (+20 words; take from T3.)
* Eq. (3) text under the equation: keep "the CV call must be made about ⟨cv.call_before_stamp⟩ s before the stamp"
  and add "(pre-registered reading)".

**[QUEUED → paper workflow]** **P-5 (P0; U4) Fig. 1b and its caption (claims-vs-code).** The plan's caption footnote "the streamed engine
matches the offline evaluation exactly (`online_vs_offline.json::...online_rule_precision_recall`)" is false: the
offline recomputation equals `summary.json`, but the engine's emitted calls are 4 of 41 against 8 offline (online
rule) and 24 offline (snapshot, 0 ms). Change:
* Plot the **live causal engine** as the primary series (solid): `online_vs_offline.json::runs.fp16_cl_fuse_compile_b1_realtime.A_engine_calls.online.<lead>.{precision,recall,precision_wilson95}`.
  Plot the offline snapshot rule dashed, direct-labelled "offline (look-ahead feature)".
* Direct label → "live engine: ⟨eng.tp⟩ of ⟨eng.tp⟩ calls correct, ⟨eng.tp⟩ of ⟨eng.nmiss⟩ misses called (median
  lead ⟨eng.lead_med⟩ ms)".
* Caption footnote → "The offline rule used a look-ahead feature (a whole-flight median) and kept deciding after
  a far-side bounce; the causal engine is the deployable number (`engine/README.md`)."
* Fig. 1 caption line count unchanged.

**[QUEUED → paper workflow]** **P-6 (P0; U1) §5 "The 1 s baseline".** Replace "The two readings bracket the result. Under the alternative
stamp-noise timing reading the trader loses at every V (Table A1). The replay on live-recorded books loses at every
V and lag (Fig. 3d), because it calls every point rather than ≥ 4¢ jumps." with "Table 2 gives every reading;
the per-point readings lose. The replay calls every point ex ante and loses at every V and lag (Fig. 3d); the
sweep trades only points that later moved ≥ 4¢. The gap is the value of knowing in advance which points matter,
which no tested rule supplies yet." (+12 words.)

**[QUEUED → paper workflow]** **P-7 (P0/P1; U9, U10) §7 Liquidity & capacity.**
* Replace the last sentence ("At the 1 s baseline, OOS trading P&L against that stack is …") with: "At the 1 s
  baseline the book can pay at most ⟨cv.cal.oos.maxlic⟩/month for data post hoc and ⟨cv.pre.oos.maxlic⟩
  pre-registered, against quotes of ⟨fin.feed.low⟩–⟨fin.feed.high⟩; the video licence is unpriced. At today's
  fee COURTSIDE prices speed; it is not yet a business." (+15 words.)
* Size bullet: append "The CV book at 1 s uses ⟨cv.pre.oos.cap⟩–⟨cv.cal.is.cap⟩ of capital at a 100-share net cap;
  stale depth per point is a median ⟨liq.stale_pre⟩, so a 1,000-share cap loses OOS (⟨cv.netcap1000.oos.usd⟩/day)."
  When `results/capacity/capacity.json` exists, replace this sentence with its capacity statement (C8).
* Fig. 4b: the hatched "CV @ 1 s, OOS" group shows both Table 2 OOS readings minus low/central/high stacks (it
  already does); add a marker at ⟨cv.cal.oos.maxlic⟩/month.

**[QUEUED → paper workflow]** **P-8 (P0/P1; U7, U10, U11) §8 Limitations & next steps.**
* Replace "Licensing that feed turns the simulation into deployment. Polymarket US already buys official data and
  streams: Genius Sports for selected leagues, and ATP Tour streaming rights." with "Licensing that feed is a
  purchase decision, not yet a deployment: sub-second match video is sold to licensed sportsbooks (Table A9),
  and at 1 s the book covers the cheapest data quote only if L ≥ ⟨cv.L_for_low.oos⟩ s. Polymarket US already
  licenses official data and streams (Genius Sports for selected leagues; ATP Tour rights)." (+20 words; take
  them from T3.)
* In "The key uncertainty" add after the first sentence: "The post hoc value assumes the fast tier react to the
  bounce; its reaction-time assumption matters little, because the 1 s hold dominates (L ≥ ⟨cv.L_bot⟩ s even for a
  20 ms bot)." (+28 words; if over budget, put this in the Table A1 notes instead.)

**[QUEUED → paper workflow]** **P-9 (P1; U3, U6) Fig. 3(a)–(b).**
* Add the stamp-calibrated curve (thin dashed orange, label "post hoc, per point") from `latency_sweep.csv`
  rows `reading=stamp_calibrated`, both periods.
* The dotted V = 1 s line label "expected latency: licensed feed" → "assumed: licensed feed (not purchased)".
* At the post hoc curve's V = 1 point, a small text label: "= camera ⟨cv.cal.shift⟩ s ahead, L = 2.0 s (Eq. 3)".
* Caption (a): "…for the pre-registered and post hoc stamp lags, and the per-point reading of the same post hoc
  inference…".

**[QUEUED → paper workflow]** **P-10 (P1; U8) Fig. 1(a), "Our WebRTC → CV pipeline" row.** Source order: `results/e2e/*.json` (frame → order
ready, when present; label "our pipeline, own footage, paper order") → `results/webrtc/latency.json` →
`results/webrtc/summary_20261003T212750Z.json::runs[run=slowmo10_engine].capture_to_decision_ms.{p50,p99}`
(40.7 / 53.9 ms) with the label "laptop, 10 fps". For capture-to-decision use only engine runs with
`calls_valid: true`; transport-only runs are valid for the video leg alone.

**[QUEUED → paper workflow]** **P-11 (P1; U2, U13) Disclosure: Table 3 notes, Tables A4, A6, A7, §5 peek sentence.**
* Table A4 (variants): add the row "Post hoc presentation choices: headline stamp-lag reading (⟨cv.cal.lag⟩ s)
  and the 1 s baseline, both fixed after the sweep's burned-OOS cells were computed (peek lines 43, 50, 61–64;
  replay protocol `0e083ed`)", counted as 2 post hoc trials. Table 3 notes: "latency-sweep and replay cells are
  sensitivities; the headline reading and V = 1 s were chosen after looking (Table A4)."
* Table A6: flag line 63 ("LOGGED AFTER THE RUN") in bold.
* Table A7: add the row "tier-0 PREREG: text says written 17:25 UTC; committed with its results in `a5769c7`
  (19:24 UTC); OOS grid first run 17:29 UTC (peek line 5)".
* `peeks.n` = line count at build time (68 at 22:30 UTC Oct 3, including lines other workflows had not yet committed).

**[QUEUED → paper workflow]** **P-12 (P0) §13 honesty guardrails and the §15 build grep.** Add to the fail list (case-insensitive): "calibrated
from the data"; "calibrated reading" not followed within 40 characters by "post hoc"; "goes live"; "11 of 11"
and "408 ms" unless the same sentence has "offline" (P-5). Add to the required strings on pages 1–5: "not ex ante"
(Table 2 note 1) and "post hoc" (≥ 3 times).

**[QUEUED → paper workflow]** **P-13 New `numbers.json` keys (§12).**

| Key | Value now | Source |
|---|---|---|
| cv.stc.{is,oos}.usd | −17.25 / −16.84 | `latency_sweep.json::video_own120.stamp_calibrated["1"].{IS,burned_OOS}.usd_per_day` |
| cv.stc.be.{is,oos} | 0.34 / 0.30 s | `breakeven_video_delay.stamp_calibrated.{IS,burned_OOS}.breakeven_V_s_seed_mean_curve` |
| cv.stn.{is,oos}.usd | −17.25 / −16.84 | `video_own120.stamp["1"]…usd_per_day` |
| cv.pess.pre.{is,oos}.usd | +8.18 / −12.60 | `video_cv_pessimistic.tournament["1"]…usd_per_day` |
| cv.pess.l3.{is,oos}.usd | +72.98 / +32.33 | `video_cv_pessimistic.tournament["0"]…usd_per_day` (= L 3.0 at V 1 by Eq. 3) |
| cv.pre.oos.ci | [−2.08, 1.21] | `video_own120.tournament["1"].burned_OOS.net_c_per_share_ci95` |
| cv.cal.shift | 0.14 s | D `cv.cal.lag − cv.pre.lag − 1.0` |
| cv.{cal,pre}.{is,oos}.maxlic | $2,793 / $1,644 / $373 / $55 per month | D `usd_per_day × 30.42 − financials.json::cost_assumptions.vps_london.central` |
| cv.L_for_low.oos | 2.98 s | D: on `latency_sweep.csv` (video, own120, tournament, burned_OOS, x_s ≤ 3), V* = first V where `pnl_per_day_usd` < `strategies.v2.cost.daily.low`; L = 3.0 − V* |
| cv.L_bot | 2.85 s | D `cv.cal.lag + (0.02 − 0.25) + (0.002 − 0.067)` (linear form of `calibrate_stamp_lag`, checked against `results/tier0/results.json::inputs.stamp_lag_calibration.grid`) |
| cv.pool482.oos.c | +0.25 [−0.35, 0.86] | `results/tier0/results.json::stresses_corrected["live pool = all 482 points"]` (burned OOS) |
| cv.netcap1000.oos.usd | −$51 | `results/tier0/results.json::stresses_corrected["net cap 1000"]` |
| cv.{pre,cal}.{is,oos}.cap | $17.8k / $13.8k / $29.2k / $22.6k | `latency_sweep.csv::capital_usd` at x_s = 1.0 |
| eng.tp / eng.nmiss / eng.wil_lo / eng.lead_med | 4 / 41 / 51 % / 162.5 ms | `online_vs_offline.json::runs.fp16_cl_fuse_compile_b1_realtime.A_engine_calls.{online["50ms"].tp, miss_first_call_lead_ms.n_miss, online["50ms"].precision_wilson95[0], miss_first_call_lead_ms.median}` |
| e2e.p50 / p99 | pending | `results/e2e/*.json` (C7) |

**[QUEUED → paper workflow]** **P-14 (P0 ops; U14) Pending cells.** (a) Key the live cell on `results/live/summary.json::status`: when it
starts with "settling", print "quoting stopped 11:30 UTC; B1 ⟨fills⟩ fills, P&L ⟨pnl⟩ marked to mid as of ⟨file
mtime⟩; settlement pending". (b) Add a Table 3 row "Tier-0 v3 forward (blind, run once)" from
`results/tier0_v3/forward/results.json::results.frozen_v3["primary (lag 2.0 | tournament | trunc 0 | queue 0)"].full_window.{per_share_c,per_share_ci95_c_lo,per_share_ci95_c_hi,n_matches}`;
"pending" if absent. (c) The paper rebuild after the 11:30 UTC runs must finish by 14:15 UTC (deadline 15:00 UTC).

**[QUEUED → paper workflow]** **P-15 Page budget (net).** P-1 0, P-2 +0.4, P-3 +2.4 (two rows; notes rewritten at equal length), P-4 0
(+53 −32 words; optional e2e sentence paid by T3), P-6 +0.9, P-7 +1.1, P-8 +1.4 → about **+6.2 lines** against
about 2.6 lines of slack. Apply trims **T3** (−1.4), **T4** (−1.2) and **T6** (−1.6) now, and move the P-8 second
sentence to the Table A1 notes if needed (−2.0). Then check `\pageref{lastmain} ≤ 5`. Never trim the
pre-registered column, the new rows 8–9, Table 2 note 1, or the replay.

**[QUEUED → paper workflow]** **P-16** Regenerate `docs/NOTE.md` from the same numbers (it is the companion). Then update `docs/COMPLIANCE.md` per
PLAN §14 item 8.

---

## 2. Video: `docs/video_script_v2.md` and `scripts/make_video_v2.py` (video workflow)

**[QUEUED → video workflow]** **V-1 (P0; U1, U2, U3, U6, U11, U12) S06 "The one-second baseline".** Replace the five narration lines with:

> So what's it worth? Fast match video is sold to bookmakers; vendors claim as little as {vid_lo_s} seconds. We didn't buy it... so we simulate a one-second licensed feed.
> Faster wins, and from {all_lose_s} seconds on, every reading loses.
> At one second, our pre-registered reading breaks even: {t_oos_day} dollars a day held out, {t_oos_c} cents a share. The call has to beat the umpire's stamp by {call_before_stamp} seconds.
> If umpires log points about {lc_lag} seconds after the bounce, which we inferred after the fact, it's {lc_is_day} and {lc_oos_day} dollars a day. Read the same clocks point by point, and it loses {stc_oos_day_abs}.
> And it only trades points that later moved four cents or more... so that's an upper bound. It all hinges on one number we haven't measured: how fast the umpire logs the point.

* New numbers: `t_oos_day` = `video_own120.tournament["1"].burned_OOS.usd_per_day` (integer); `t_oos_c` =
  `….net_c_per_share` (2 dp, signed, spoken "minus"); `call_before_stamp` = `cv.pre.lag − be_t_is − 0.02`
  (1 dp; 0.9); `stc_oos_day_abs` = abs(`video_own120.stamp_calibrated["1"].burned_OOS.usd_per_day`) (spoken "17
  dollars a day"); `lc_lag` spoken at 1 dp ("3.1").
* Sharpe moves to screen only: chips "pre-registered Sharpe {t_is_sh} / {t_oos_sh}" and **then** "post hoc
  {lc_is_sh} / {lc_oos_sh}", in that order, same size.
* Labels: replace "Calibrated reading = stamp lag inferred from the data, post hoc." with "Post hoc reading: stamp
  lag inferred after the fact, assumes courtside humans. Trade set = points that later moved ≥ 4¢ (not ex
  ante)."
* Visual: add the stamp-calibrated curve (dashed orange, "same inference, per point"); at V = 1 on the post hoc
  curve, a tag "= courtside camera 0.14 s early (model identity)".
* Guard `stricter_lose`: delete it (the "Stricter readings lose." line is gone). Add guard `pre_be`: speak line 3
  only if `t_oos_day` < 10 and `t_oos_c` < 0; else "At one second, our pre-registered reading makes {t_oos_day}
  dollars a day held out."
* Never speak "calibrated from the data", "conservative" or "stricter".

**[QUEUED → video workflow]** **V-2 (P0; U5) S02.** Replace line 2 (both branches) with:
> [if t_lc_med] When a point ends, the book moves about a second before the umpire's official stamp. How long after the ball lands, nobody has measured: {t0_preB} to {t_lc_med} seconds in our readings.
> [else t_lc_med] When a point ends, the book reprices within seconds of the ball landing.

* `t_lc_med` = `results/tier0/results.json::timing["calibrated_stamp_lag_s (inference)"] + timing.median_t_reprice_minus_t_stamp_s`
  (3.142 − 1.32 = 1.8; 1 dp). Visual: replace "({t0_preB} to {t0_calB} s after the bounce, both estimates)" with
  "({t0_preB}–{t_lc_med} s after the bounce: readings, not measured)". `t0_calB` is no longer spoken.

**[QUEUED → video workflow]** **V-3 (P0; U4) S01 hook.**
* `tt_lead_ms` → `results/engine/online_vs_offline.json::runs.fp16_cl_fuse_compile_b1_realtime.flights_called_or_miss[video=test_2,f_net=2819].lead_engine_call_ms`
  (325). Guard: if that record is absent, keep the clip but drop the spoken number.
* The on-screen stamp must read "MISS CALLED {tt_lead_ms} ms BEFORE CONTACT (live engine)". If the showcase reel
  has 408 burned in, the `cv_showcase*.py` owner must re-render the stamp from the engine key (instruction to
  that workflow), or the renderer overlays a corrected stamp.
* Footnote → "Live causal engine on held-out games: {eng_tp} of {eng_nmiss} misses called early, all correct,
  median {eng_lead_med} ms. Offline evaluation with a look-ahead feature: {tt_lead_off} ms on this flight." Drop
  "Longest early call" (`hook_is_longest`) unless it is recomputed on engine leads.

**[QUEUED → video workflow]** **V-4 (P0; U4) S04 vision.** Replace narration line 2 with:
> Run live and causally on a GPU, it called {eng_tp} misses before contact on held-out games, a median {eng_lead_med} milliseconds early... and every call was right. It's cautious: {eng_tp} of {eng_nmiss}.

* Numbers: `eng_tp`, `eng_nmiss`, `eng_lead_med` as P-13. On screen: "precision 1.0 (95 % lower bound
  {eng_wil_lo} %); offline evaluation 11/11 used a look-ahead feature (`engine/README.md`)". Remove `calls50_phrase`
  and `wil50` from the narration.

**[QUEUED → video workflow]** **V-5 (P0; U1, U12) S07 replay.** Replace "…it {rep_verb} {rep_v1_c_abs} cents a share. One second is right on the
edge." with "…it {rep_verb} {rep_v1_c_abs} cents a share. On these real books it lost at every delay we tried...
even zero." Guard `rep_all_neg`: `all(cells[*].all.per_share_mark_c < 0)` in `results/replay/replay.json`; if
false, end the line after "a share."

**[QUEUED → video workflow]** **V-6 (P0; U10, U12) S09 close.** Replace "License a feed, measure that one number, and this goes live." with:
> Next: one session with a licensed feed measures that number. If the umpire lags about three seconds and data costs under {maxlic_k} thousand dollars a month, it pays. If not, the speed belongs to someone else.

* `maxlic_k` = `cv.cal.oos.maxlic / 1000` (1 dp; 1.6). Line 1 "a real edge, fast vision, and speed is the whole
  trade" stays.

**[QUEUED → video workflow]** **V-7 (P1; U8, Dom's latency question) Pipeline scene.** Implement VIDEO_REQUIREMENTS item 6 as the S05
replacement and **do not skip it** while e2e is pending. Boxes and their measured ms:
* WebRTC video leg 3.8 ms p50 at 1080p120 (`research/webrtc/README.md`; run `215353Z`; key in
  `results/webrtc/summary_20261003T215353Z.json::runs[native120_transport].video_leg_ms.p50`);
* GPU CV call-ready 4.6 ms p50 / 12.2 ms p99 at 120 fps, 0 dropped (`online_vs_offline.json::headline…after_startup`);
* decision, risk and order (from `results/e2e/*.json` when present, else "measured in e2e run: pending");
* network Florida 67 ms / London 2 ms (`results/decay/decay.json::latency_inputs`);
* venue hold 1,000 ms;
* total, drawn against a 3,000 ms bar and the "beat the stamp by 0.9 s" marker.

Narration:
> Can we trade that fast? Our part takes about a tenth of a second: video in, a call in under five milliseconds on a GPU, an order to the venue. The venue then holds every order for a second. So under three seconds is easy... the real bar is beating the umpire's stamp by nine-tenths of a second.

Labels: "Own stream of OpenTTGames footage, not a match feed; paper order, not sent"; "frame-to-order in one process:
{e2e_state}". Never quote capture-to-decision from engine runs with `calls_valid: false` or from the laptop
real-time runs with a 1.5–7.9 s backlog (`native120_engine`); transport-only runs are fine for the video leg.

**[QUEUED → video workflow]** **V-8 (P1; U9, U11, U13, U14) S08 and the IC segment.**
* S08: add a capacity line, spoken: "Capacity is small: the held-out edge holds up to about {cap_hi} thousand
  dollars of capital, and five times the size loses." (`alpha.json::headline.oos_capital_capacity_usd[1]`; the 5×
  guard is `H_capacity.rows[size=5x].OOS.pnl_usd_per_day < 0`.) Replace with `results/capacity/capacity.json` when
  present (C8).
* On-screen scoreboard: add "post hoc choices disclosed: stamp-lag reading, 1 s baseline" and "OOS looks logged:
  {peeks}".
* **IC questions segment (VIDEO_REQUIREMENTS addendum, 25–30 s; one card each; answer, number, file).** Card 3
  must carry Dom's latency answer and card 4 his capacity answer:
  1. Who pays? Slower takers; fast tier positive 11/11 months; factor α t = 8.5 (`alpha.json`).
  2. Why does it persist? Speed costs money; sub-second video is sold only to sportsbooks (`sub_second_routes.json` A9).
  3. How fast, and can you? Our pipeline ≈ 0.1 s + the 1 s hold; break-even 1.0–1.1 s pre-registered (`latency_sweep.json`).
  4. How much capital? $23–34k for v2 OOS; 5× loses (`alpha.json::H_capacity`).
  5. What does it cost? Data ASSUMPTION $1.25–10k a month; the CV book can pay at most $1.6k post hoc (`financials.json`; derived).
  6. What kills it? The unmeasured stamp lag, queue position, fees ×2, a shrinking edge (−0.20¢ a month), top-5 wallet concentration.
  7. Overfit? Pre-registrations, blind tests (most failed), DSR 0.075 OOS at N = 3,410, every peek logged.
  8. Legal? Licensed feed only; no courtsiding; paper only (Terms 5.3).
  9. To go live? One licensed-feed session to measure the stamp lag, a London gateway, an ex-ante point filter (C1).

**[QUEUED → video workflow]** **V-9** Honesty rules section of the script: add rule 9, "The CV P&L is never spoken without the pre-registered
number first, and never without 'post hoc' on the 3.14 s reading", and rule 10, "Offline CV numbers (11/11,
408 ms, 74 %) are never spoken; on-screen only with 'offline, look-ahead feature'". Re-render; total stays under
6,000 TTS characters (S06 grows by about 150).

---

## 3. Deck: `docs/deck/build_deck.py` (integration pass)

**[DONE (red-team/integration pass, `docs/deck/build_deck.py`)]** **D-1 (P0; U1, U2, U3, U6, U12) Slide 7 "Tier-0 counterfactual" → "The 1 s baseline: break-even, and one unmeasured
number".**
* Replace the two V = 0 cards with four cards at V = 1 from `results/tier0/latency_sweep.json::video_own120`, in
  this order: **pre-registered** (+15 / +4 $/day, −0.38¢ OOS, break-even 1.09 / 1.01 s); post hoc L = 3.14 s
  (+94 / +57); same inference per point (−17 / −17; break-even 0.34 / 0.30 s); replay on 9 real books (−0.92¢,
  36/36 cells < 0, `results/replay/replay.json`).
* Subtitle: "Simulated: assumed 1 s licensed feed (not purchased); parameters measured. Trade set = points that
  later moved ≥ 4¢ (not ex ante). In the model, 1 s at L = 3.0 s = the courtside camera at L = 2.0 s."
* `TIER0_LABEL` → "SIMULATED: assumed 1 s licensed feed (not purchased); parameters measured; trade set selected
  on outcomes". Update the `run_checks` assertion that requires "COUNTERFACTUAL" in the label to require
  "SIMULATED" and "not ex ante" (or "selected on outcomes").
* Notes: say the pre-registered number first (QA_PREP §1, 20-second version).

**[DONE (red-team/integration pass, `docs/deck/build_deck.py`)]** **D-2 (P0; U2, U5) Slide 2 "Economics", tier 3 row (line ~1173).** Change `f"{lag} after the bounce (inferred)"`
to "1–3 s after the bounce, unmeasured (post hoc inference ≈3.1 s)". Change the slide footer text "stamp-to-bounce
lag is inferred, not measured" to "stamp-to-bounce lag is unmeasured; the post hoc inference assumes courtside
humans". Keep "book reprices 1.32 s before the stamp".

**[DONE (red-team/integration pass, `docs/deck/build_deck.py`)]** **D-3 (P0; U4) Slide 4 "CV in action".** Replace the big stat `{calls}` ("11/11") with the live engine's
"{eng_tp}/{eng_tp} correct" and the caption "live causal engine on held-out games: called {eng_tp} of
{eng_nmiss} misses before contact, median lead {eng_lead_med} ms; 95 % lower bound {eng_wil_lo} %". Add a muted
line: "offline evaluation 11/11 at 50 ms used a look-ahead feature (`engine/README.md`)". The `lead_max` note
(408 ms) → 325 ms from the engine key (V-3). Speaker notes: QA_PREP Q10.

**[DONE (red-team/integration pass, `docs/deck/build_deck.py`)]** **D-4 (P1; U8, U14) Slide 8 "Live engine".** Add a stage-latency strip from the same sources as V-7, with the
"our part ≈ 0.1 s + 1 s venue hold" total and the e2e result when present ("pending" otherwise). Keep the live
session state guarded per CLEAN_CLONE N5.

**[DONE (red-team/integration pass, `docs/deck/build_deck.py`)]** **D-5 (P1; U9, U10) Slide 9 "Risk + liquidity + financials".** Add two lines: "CV @ 1 s can pay at most $1.6k a
month for data (post hoc) / $55 (pre-registered) vs quotes $1.25–10k (ASSUMPTION)" (derived keys as P-13), and
"capacity: v2 OOS $23–34k; CV @ 1 s $14–29k at a 100-share cap" (or `results/capacity/capacity.json`). Replace
any "−$4,060/day" tier-0 camera economics shown at V = 0 with the 1 s rows, or label it "camera counterfactual".

**[DONE (red-team/integration pass, `docs/deck/build_deck.py`)]** **D-6 (P0; U10, U12) Slide 10 "Close".** No "goes live" wording. Use "Next: one licensed-feed session to measure
the stamp lag; an ex-ante point filter; then decide whether to buy a feed."

**[DONE (red-team/integration pass, `docs/deck/build_deck.py`)]** **D-7 (P1) Backup slides.** Change the eyebrow "Q{q} OF 10" to "OF 14". Rewrite Q10 ("What does the computer vision
actually add?") with the causal numbers (D-3). Add four slides via `slide_q`, each with bullets and evidence taken
verbatim from QA_PREP:
* Q11 "Isn't the CV trade set chosen on outcomes?" (QA_PREP Q4)
* Q12 "Why headline a post hoc lag? The same inference loses." (QA_PREP Q5 + Q6, with the six-reading table from §1)
* Q13 "Prove you can trade inside 3 s" (QA_PREP Q1; Dom)
* Q14 "What's left after paying for data? How much capital?" (QA_PREP Q2 + Q12; Dom)

The deck's `talk_seconds` stays 285: main-talk timing does not change.

**[DONE (red-team/integration pass, `docs/deck/build_deck.py`)]** **D-8** Re-run the deck build; the manifest must list every new number with its file and key; `run_checks` must
pass.

---

## 4. Other public text (integration pass)

* `README.md` line 39 and `docs/DEVPOST.md` line 34: "misses called 50 ms early, 11 of 11 calls correct (recall
  27%)" → "live causal engine: 4 of 41 held-out misses called before contact, all correct (median lead 162.5 ms);
  the offline 11 of 11 used a look-ahead feature (engine/README.md)". (U4)
* `README.md` line 34, `docs/DEVPOST.md` line 21: "11/11 months (8 in sample, 3 out of sample)" → "9/9 in-sample
  and 3/3 out-of-sample months (11 calendar months; August in both)", from `alpha.json::headline.fast_tier_net30_c_months_positive`. (P2)
* Any DEVPOST or README sentence presenting the CV P&L must lead with the pre-registered break-even (U12).
* `docs/NOTE.md`: regenerated by the paper build (P-16).

---

## 5. Computations still needed (priority order)

| # | What | Owner | Cost | Peek rule | Feeds | Status (23:45 UTC) |
|---|---|---|---|---|---|---|
| **C1** | **Ex-ante point filter on the replay.** At call time the score and the CV-called winner are known, so the implied move is known: \|ΔFV\| = \|P(win \| called outcome, pre-point score) − P(win \| pre-point score)\| from `src/markov.py`, with the pre-point score rebuilt from `results/replay/points.csv`. Trade iff \|ΔFV\| ≥ 4¢ (the detector's own threshold, so nothing is tuned). Run V ∈ {0, 0.5, 1} × lag ∈ {1, 2, 3, 3.14} under both fill rules (the replay's ≤ 1¢ allowance and the sweep's "fill only before the reprice"). Also report the overlap with the realised ≥ 4¢ set and ¢/share on each set. Report whatever the sign. | replay workflow (`scripts/match_replay.py`, `research/replay/PROTOCOL.md` amendment A1 committed **before** the run) | minutes, local, light | one `oos_peeks.log` line before the run ("forward live recordings … ex-ante filter; threshold fixed at 4c; no parameter chosen") | Q4, P-3 note 1, P-6, D-7 Q11, V-1 | **QUEUED → replay workflow (an exploratory selective variant is in `results/oos_peeks.log` 23:01 UTC; it must be labelled post hoc, or re-run under a PROTOCOL amendment)** |
| C2 | The same ex-ante filter on the historical sweep. **Not feasible as specified:** the historical tapes have no point-by-point score, so Markov leverage cannot be computed before 2026-10-03. Say so in the paper; the existing "all 482 points" stress is the nearest sensitivity. | tier-0 owner | none | none | P-3 note 1 | **NOT FEASIBLE (documented; nearest sensitivity = all-482 pool)** |
| C3 | **Calibration robustness** (descriptive, the 12:45 UTC live-day snapshot, which predates the forward window): bootstrap the 49 points for a CI on L; windows [−0.25, 0) and [−1, 0) (with-move share 98 % in (−0.5, 0] vs 62 % in (−1, −0.5], `research/v2/latency/results.json::summary.trades_around_reprice`); exclude prints ≤ 100 ms before the reprice; test whether first-print times cluster on the whole-second clock (33 % of reprices land 50–100 ms after a second). | tier-0 owner (`src/tier0.py::calibrate_stamp_lag`) | seconds | none if the snapshot predates 14:00 UTC; otherwise log a line | Q5, Q9, P-8 | **DONE → `results/redteam/stamp_lag.json` (`scripts/redteam_stamp_lag.py`)** |
| C4 | **Per-point lag reading at V = 1:** draw t_reprice − t_bounce from the calibration's own 49-point distribution instead of 3.14 s + pool R. IS first; OOS as one logged non-blind read. | tier-0 / sweep owner | minutes | one line before the OOS cell | Q6, Table 2 row 8 | **DONE as an exact bound (no simulation needed) → `results/redteam/stamp_lag.json::per_point_reading_V1`** |
| C5 | **Causal-CV cell:** add `own120_engine` to `src/tier0.py::cv_systems()` with the engine's recall/precision (`A_engine_calls.online`, 4/41, precision 1.0) and run V = 1 under `tournament` and `tournament_lagcal`; also run `own120_pess` under `tournament_lagcal`. IS is free; OOS is one logged read. | tier-0 / sweep owner | minutes | one line before the OOS cells | Q10, Table 2 row 9 | **DONE → `results/redteam/causal_cv.json` (`scripts/redteam_causal_cv.py`; IS, then one logged burned-OOS read, peek line 23:18:38 UTC)** |
| C6 | Licence ceilings, the L needed at 1 s, reaction-time sensitivity. **Done by arithmetic in `docs/QA_PREP.md` §5**; the paper must recompute them in `build_paper.py` from JSON (P-13), not copy them. | paper | none | none | Q9, Q12, P-7, P-8 | **DONE → `results/redteam/derived.json` (`scripts/redteam_derived.py`); the paper must read it, not copy** |
| C7 | **e2e proof (Dom 1).** The JSON in `results/e2e/` must carry: per-stage p50/p99 ms (capture, WebRTC video leg, decode, detect + track + call, fair value, risk checks, order build, network to the venue gateway or its measured RTT/2, venue hold 1,000 ms), the total against 3,000 ms, host and GPU, fps, frames dropped, `calls_valid`, and the label "paper; order not sent". Best: camera → order in one process on the GPU host, which `engine/README.md` "Known gaps" says has never been run. | e2e workflow | in progress | none (own footage) | Q1, P-10, V-7, D-4 | **IN PROGRESS (e2e workflow); `results/e2e/summary.json` exists (24 traces at 23:15 UTC); checked by `scripts/redteam_acceptance.py`** |
| C8 | **Capacity (Dom 2).** `results/capacity/capacity.json` must give, for v2 and the CV book at 1 s (both readings): $/day, ¢/share with CI, Sharpe and capital by net cap and coverage; the largest capital whose OOS ¢/share CI lower bound is > 0; and the share of stale depth / ADV used. | capacity workflow | in progress (logged at 22:18 UTC) | logged | Q2, P-7, V-8, D-5 | **IN PROGRESS (capacity workflow); `results/capacity/capacity.json` exists; its paragraph must lead with the pre-registered reading (§8 R-5)** |
| C9 | **v2-safe forward script** (promised by `HYPOTHESIS_V2.md` A2 and `research/v2/lowloss/PREREG.md` (c); no script produces it). New file `scripts/forward_test_safe.py`, importing `forward_test` unchanged (it is sha-pinned), with `V2_SAFE = dataclasses.replace(v2.POLICY, name='v2_safe_n50', net_cap=50)`, a required `--end` equal to `results/v2/forward.json` window[1], a `--dry` mode, and a `results/forward_peeks.log` line before any read. Run it once, after the pinned runs. | v2 / lowloss owner | light | its own forward log line | Q23, Table 3 G2 | **DONE (script) → `scripts/forward_test_safe.py` (`--plan` checked; tests in `tests/test_redteam.py`); RUN ONCE after the pinned runs** |

---

## 6. Ops before 11:30 UTC (user actions; from the readiness pass; nothing here was run by this workflow)

* Keep the laptop on AC with the lid open until 16:00 UTC (settlement window). `caffeinate -i -w 2001` does not stop
  lid-close or low-battery sleep. Stronger: `nohup caffeinate -dims -w 2001 >/dev/null 2>&1 &`. Changing
  `pmset disablesleep` is a system setting: the user decides and runs it.
* Disk was 8 GB free (99 %) at 22:30 UTC, with swap nearly full. The real forward run uses 6 workers (the dry run
  peaked at 12.3 GB with 2). Free space and memory before 11:20 UTC; the orphaned `multiprocessing` workers from
  another project (`~/pokerface`) are the user's call. After the recorder exits around 09:02 UTC, gzip
  `data/live/market_20261003_1501.jsonl` (1.2 GB).
* From 11:25 to 11:50 UTC: no renders and no WebRTC, e2e or capacity jobs.
* **Runbook (UTC):** 11:20 preflight → 11:30:30 `forward_test.py` → `tier0_v3_forward.py` → C9 → 11:45 commit and
  push the results → 12:00–13:30 rebuild the paper, deck and video → 14:15 final push and backup → 14:30 PDF to
  Devpost → **15:00 hard stop** (11:00 EDT; later commits are not reviewed).
* Push `main` (CLEAN_CLONE N13) and publish the frozen vision model (N6) before the deadline.

---

## 7. Acceptance checks for the integration pass

1. `grep -ri "calibrated from the data\|goes live\|stricter readings"` over `docs/` and `results/viz/v2_assets/` returns nothing.
2. Every place that shows the post hoc 1 s P&L shows the pre-registered number first (abstract, box, Table 2,
   S06, slide 7).
3. The phrase "not ex ante" (or "selected on outcomes") appears in the Table 2 notes, S06 labels and slide 7.
4. No "11/11", "11 of 11 calls" or "408 ms" without "offline" in the paper, video, deck, README or DEVPOST.
5. The stamp-calibrated reading (−$17/day, break-even 0.30–0.34 s) appears in Table 2, Fig. 3a, S06 and slide 7.
6. Dom's two questions each have a video beat (V-7, V-8), a deck slide (D-4/D-5 plus backups Q13/Q14) and a paper
   sentence (P-4/P-10, P-7), with "pending" wording that switches to the e2e/capacity numbers when they land.
7. Paper: `\pageref{lastmain} ≤ 5`, no text under 10.9 pt, and the build asserts for P-3 rows 8–9 pass.

---

## 8. Red-team pass additions (2026-10-03, about 23:45 UTC): new findings and exact instructions

Computed by `scripts/redteam_{stamp_lag,derived,causal_cv,acceptance}.py` into `results/redteam/` (`bash run.sh redteam`
reruns all but the causal cell in about 10 s). Only C5 read held-out data: one burned-OOS read, logged before the run
(`results/oos_peeks.log`, 23:18:38 UTC). No rule, threshold or parameter was chosen from any of it.

**R-1 (P0; U2, U7, Q5, Q9) The post hoc 3.14 s stamp lag is one mode of a two-mode estimate.** Bootstrap 95% CI of the
median lag [2.23, 3.22] s; 33% of resamples fall below 2.5 s; the [−0.25, 0) print window gives 2.23 s
(`results/redteam/stamp_lag.json::bootstrap`, `windows`). Cause: the official stamp has 1 s resolution (every
`T_ms mod 1000 = 0`), so the per-point lags cluster about 1 s apart (quartiles 2.20 / 3.14 / 3.23 s). At L = 2.23 s the 1 s cell is about
+$19/day IS and +$8/day held out (`derived.json::cv.at_L_boot_lo.*`), below the cheapest data stack ($42/day).
* Paper (P-3 note 2, P-8): append "Its bootstrap 95% CI is ⟨cv.L_boot_ci⟩ (the stamp has 1 s resolution); at its low
  end the 1 s cell makes ⟨cv.at_L_boot_lo.oos.usd⟩/day held out." New macro keys: `cv.L_boot_ci`,
  `cv.L_boot_share_below_2_5`, `cv.at_L_boot_lo.{is,oos}.usd`.
* Video S06 (V-1): on-screen tag under the post hoc number: "inferred lag 3.14 s, 95% CI {2.2}–{3.2} s".
* Deck: done (slide 7 card 2, backup Q12).

**R-2 (P0, paper) One source for the derived numbers.** `results/redteam/derived.json::keys.<key>.value` carries every
P-13 key under the same name (with `source` and `formula`), plus `cv.call_before_stamp`, `cv.L_breakeven.{is,oos}`,
`cv.L_for_central.*`, `cv.{pre,cal}.{is,oos}.{net_low,net_central,annual_gross}`, `eng.hook_lead_ms` (325),
`eng.hook_lead_offline_ms` (408), `eng.call_ready_p{50,99}_ms`, `eng.phantom_*`, `venue.*`. `build_paper.py` should
load it like any results file (recompute with `python scripts/redteam_derived.py` first). Note `eng.lead_med` is
162.5 ms (the sheet's "163" was rounded); print "162.5 ms" or "about 160 ms", never 163.

**R-3 (P1; U4, Q10) Rally-state gate. DONE in code at about 23:50 UTC, after the e2e run finished (`d11e74e`); the
evaluation below is QUEUED.** The
live engine fired 7 MISS calls on balls outside the 171 scored flights in 851 s (`online_vs_offline.json::runs.
fp16_cl_fuse_compile_b1_realtime.calls.unmatched`; about 30/hour; 5 between rallies). Ungated, at about $1.75 a
phantom trade (100 shares × fee 1.25¢ + half spread 0.5¢), the held-out 1 s P&L survives about 32 phantom trades a
day post hoc and 2.5 pre-registered (`derived.json::eng.phantom_*`). What was implemented (the evaluation is
still queued):
* `engine/strategy.py`: `StrategyConfig.rally_gate_s: float | None = None` (off by default so committed runs reproduce;
  use 2.0 s for any live run, fixed a priori: a table-tennis rally bounces every ~0.5 s; not tuned on test data).
  `CourtsideStrategy.note_call()` (called by `on_call`) records the last BOUNCE/IN call per match; `evaluate()` returns
  SKIP `no_rally_in_progress` for a MISS/OUT call unless such a call on the same match came 0–`rally_gate_s` before it.
* `tests/test_engine_strategy.py` (3 new tests, pass): a MISS with no prior BOUNCE → SKIP `no_rally_in_progress`; a MISS
  0.6 s after a BOUNCE → SEND as before; default `None` → unchanged behaviour. `engine/README.md` Known gaps updated.
* QUEUED (engine/vision owner): evaluate once on the HiPerGator event log (`online_vs_offline_raw_compile.pkl`): report how many of the 12 MISS calls
  pass (target: the 4 scored true positives kept, the 5 between-rally calls removed), labelled post hoc on test data.
  For tennis the analogue is a serve detector, which does not exist; say so.
* Paper §8 / video IC card 6: "a rally-state gate is in the code, off by default and not yet evaluated on the event
  log; tennis needs a serve detector" (deck Q10 and QA_PREP Q27 say this already).

**R-4 (P0; U4, Q10) Causal call table (C5 result).** With the live causal engine's own call table (4 of 41 early, precision 1.0;
`own120_engine`) the 1 s cells barely move (`results/redteam/causal_cv.json::cells_V1`, 20 seeds; offline table in
brackets): pre-registered +$17.02 [+14.78] IS and **+$3.81 [+4.35] held out, −0.49¢ [−2.23, 1.17]**, break-even
1.10 / 1.01 s; post hoc +$98.00 [+94.35] IS and +$57.42 [+56.59] held out, +0.65¢ [0.11, 1.20], break-even 2.23 /
2.13 s. Reason: at a 1 s feed the race is decided by reprice timing, not by a 50–200 ms CV lead, and the engine's
precision is 1.0. So the look-ahead in the offline evaluation inflates recall but not the 1 s result. Row 9 post hoc
cell (pessimistic CV, no early calls, lag 3.14 s): +$87.75 IS / +$48.97 held out, +0.54¢ [−0.04, 1.10]
(`pessimistic_lagcal.V1`), replacing the † placeholder in P-3.
* Paper P-3 note 3: "… the live causal engine calls ⟨eng.tp⟩ of ⟨eng.nmiss⟩ misses; with its own call table the 1 s
  cells are ⟨ccv.pre.oos.usd⟩ and ⟨ccv.cal.oos.usd⟩/day held out (`results/redteam/causal_cv.json`), so the
  look-ahead does not drive Table 2." Macro keys `ccv.{pre,cal}.{is,oos}.usd` =
  `causal_cv.json::cells_V1.{tournament,tournament_lagcal}.{IS,burned_OOS}.usd_per_day`; row 9 post hoc =
  `pessimistic_lagcal.V1.{IS,burned_OOS}.usd_per_day`.
* Video S04 (V-4) on-screen line: "with the live engine's own calls the 1 s result is unchanged ({ccv_pre_oos}/day
  pre-registered)". Deck backup Q10: done (reads the file).
* Table A6: the C5 read is the 23:18:38 UTC peek line (R-9).

**R-5 (P1; U9, Dom 2) Capacity paragraph (capacity workflow).** `results/capacity/capacity.json::paragraph` (23:00 UTC
version) opens with the post hoc reading ("the calibrated 3.14 s stamp lag … Sharpe ≥ 5") and only later says "At the
pre-registered 2.0 s stamp lag … no capacity to speak of". Reorder: first sentence = the pre-registered result; replace
"calibrated" by "post hoc" (P-12 grep); keep "simulated at a 1 s licensed-feed baseline". `scripts/redteam_acceptance.py`
check C8 turns PASS when it does.

**R-6 (P0; U8, Dom 1) e2e numbers for paper, video and deck.** `results/e2e/summary.json` now measures frame →
executable paper order in one process (24 traces at 23:15 UTC, laptop, 10 fps stream, live tennis book, order unsigned
and not sent). Keys: `budget_with_1s_simulated_feed.{ours_capture_to_order_ready_ms,network_one_way_ms,venue_delay_ms,
total_ms,margin_to_requirement_ms}.p50` (54 / 65 / 1,000 / 2,119 / 881 ms at 23:15 UTC). Paper P-10 and P-4 (optional
sentence), video V-7 (pipeline scene: replace "measured in e2e run: pending" by these keys) and the deck (slide 8
strip, backup Q13: done) read those keys. Always add "plus a simulated 1 s feed" and "laptop; on a GPU the vision call
is ready in 4.6 ms".

**R-7 (P0, paper) Claims-vs-code lines still in the paper source.** `docs/paper/note.tex:101` "Our tracker gets 11 of 11
out-calls right 50 ms before …" (P-5); `docs/NOTE.md` quotes the post hoc $/day before the pre-registered one (acceptance
check 2). Run `python scripts/redteam_acceptance.py --strict` after the paper build; it must report 0 FAIL.

**R-8 (P0 ops; U14) Overnight host.** At 23:10 UTC: 9 GB disk free, swap 12.4 of 13.3 GB used, a video render
(`make_video_60`, ffmpeg) and the e2e job running. The pinned forward run uses 6 workers and peaked at 12.3 GB with 2 in
its dry run, so an out-of-memory kill is the main way to lose the one blind read. Before 11:20 UTC (user): stop every
render/e2e/capacity/WebRTC job, quit heavy apps, gzip `data/live/market_20261003_1501.jsonl` once the recorder exits,
then `bash run.sh preflight` (read-only) and proceed only if disk ≥ 15 GB and nothing heavy is listed.

**R-9 (P1; U13) Peek-log disclosure.** Add the C5 line (23:18:38 UTC, "redteam causal-CV cell … burned OOS, non-blind,
sensitivity; no parameter chosen") to Table A6 as a non-blind sensitivity read; `peeks.n` is the line count at build
time (71 at 23:20 UTC).

**R-10 (P2; U5, U8) Venue clock.** 35% of reprices and 65% of the first informed prints land within 100 ms after a whole
UTC second (uniform 10%; `stamp_lag.json::whole_second_clock`), consistent with delayed orders being released on a 1 s
clock (already noted in `latency_sweep.json::timing_diagnostics`). Paper §8 / Table A1 note: "the model treats the hold
as a continuous 1.000 s; release on a whole-second clock is not modelled." `docs/RISK.md` has it.

**R-11 (P1; U3, Q6) Per-point reading as an exact bound (C4).** Read per point, every reprice is at most 1.78 s after
the bounce; a 1 s-feed order cannot land before 1.83 s even with a 200 ms early call, so no correct call fills at V = 1
(`stamp_lag.json::per_point_reading_V1`). Use this sentence for the Table 2 row 8 note and QA_PREP Q6; it explains the
−$17/day without a new simulation.
